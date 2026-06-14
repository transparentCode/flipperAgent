"""Ingestion per-asset state machine backed by Valkey.

Both worker-streams (controller.py) and worker-queue (tasks.py) share the same
Valkey keys so they can coordinate the REST→WS handoff without polling TimescaleDB.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from libs.common.config import ConfigManager
from libs.common.db.pool_manager import DBPoolManager
from libs.common.db.timescale_reader import TimescaleReader
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)

_STATE_KEY_PREFIX = "ingestion:state"
_STATE_UPDATED_TS_PREFIX = "ingestion:state_updated_ts"
_DISCONNECT_TS_PREFIX = "ingestion:disconnect_ts"
_LAST_LIVE_TS_PREFIX = "ingestion:last_live_ts"
_DISCONNECT_COUNT_PREFIX = "ingestion:disconnect_count"
_RESUME_BACKFILL_PREFIX = "ingestion:resume_backfill_required"


class IngestionState(str, Enum):
    COLD = "COLD"
    BACKFILLING = "BACKFILLING"
    WARMING = "WARMING"   # gap-fill complete, WS authorised to connect
    LIVE = "LIVE"         # WS connected and streaming
    ERROR = "ERROR"


class IngestionCoordinator:
    """Manages per-asset ingestion state in Valkey.

    Single authoritative source for:
    - staleness checks (replaces duplicated DB polls in lifespan + verify_and_launch_ws)
    - state key reads/writes (replaces module-level app_state dict)
    - WARMING/LIVE gate for WebSocket launch

    Both worker-streams and worker-queue instantiate this class against the same
    Valkey instance so transitions are visible across containers.
    """

    def __init__(
        self,
        valkey_client: Any,
        config_manager: ConfigManager | None = None,
    ) -> None:
        self._valkey = valkey_client
        self._config = config_manager or ConfigManager()

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _state_key(symbol: str, tf: str) -> str:
        return f"{_STATE_KEY_PREFIX}:{symbol}:{tf}"

    @staticmethod
    def _disconnect_ts_key(symbol: str, tf: str) -> str:
        return f"{_DISCONNECT_TS_PREFIX}:{symbol}:{tf}"

    @staticmethod
    def _state_updated_ts_key(symbol: str, tf: str) -> str:
        return f"{_STATE_UPDATED_TS_PREFIX}:{symbol}:{tf}"

    @staticmethod
    def _last_live_ts_key(symbol: str, tf: str) -> str:
        return f"{_LAST_LIVE_TS_PREFIX}:{symbol}:{tf}"

    @staticmethod
    def _disconnect_count_key(symbol: str, tf: str) -> str:
        return f"{_DISCONNECT_COUNT_PREFIX}:{symbol}:{tf}"

    @staticmethod
    def _resume_backfill_key(symbol: str, tf: str) -> str:
        return f"{_RESUME_BACKFILL_PREFIX}:{symbol}:{tf}"

    # ------------------------------------------------------------------ public API

    async def get_state(self, symbol: str, tf: str) -> IngestionState:
        """Read current state from Valkey. Returns COLD when the key is absent."""
        raw = await self._valkey.get(self._state_key(symbol, tf))
        if raw is None:
            return IngestionState.COLD
        try:
            return IngestionState(raw)
        except ValueError:
            return IngestionState.COLD

    async def transition(self, symbol: str, tf: str, state: IngestionState) -> None:
        """Write a state transition to Valkey and emit a log line.

        Side-effects on specific states:
        - LIVE  → records last_live_ts
        - COLD  → records disconnect_ts, increments rolling disconnect counter
                   (counter TTL = ingestion.observability.disconnect_window_seconds)
        """
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        await self._valkey.set(self._state_key(symbol, tf), state.value)
        await self._valkey.set(self._state_updated_ts_key(symbol, tf), str(now_ms))

        if state == IngestionState.LIVE:
            await self._valkey.set(self._last_live_ts_key(symbol, tf), str(now_ms))

        elif state == IngestionState.COLD:
            await self._valkey.set(self._disconnect_ts_key(symbol, tf), str(now_ms))
            window_s: int = self._config.get(
                "ingestion.observability.disconnect_window_seconds", 3600
            )
            count_key = self._disconnect_count_key(symbol, tf)
            count = await self._valkey.incr(count_key)
            if count == 1:
                # First increment in this window — set the TTL
                await self._valkey.expire(count_key, window_s)

        logger.info(f"[{symbol}:{tf}] ingestion state → {state.value}")

    async def get_disconnect_count(self, symbol: str, tf: str) -> int:
        """Return the number of COLD transitions within the current disconnect window."""
        raw = await self._valkey.get(self._disconnect_count_key(symbol, tf))
        return int(raw) if raw is not None else 0

    async def mark_resume_backfill_required(self, symbol: str, tf: str) -> None:
        await self._valkey.set(self._resume_backfill_key(symbol, tf), "1")

    async def resume_backfill_required(self, symbol: str, tf: str) -> bool:
        raw = await self._valkey.get(self._resume_backfill_key(symbol, tf))
        return raw is not None and str(raw) == "1"

    async def clear_resume_backfill_required(self, symbol: str, tf: str) -> None:
        await self._valkey.delete(self._resume_backfill_key(symbol, tf))

    async def get_observability_snapshot(self, symbol: str, tf: str) -> dict:
        """Return a per-asset observability dict suitable for the /ingestion/status endpoint."""
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        state_raw = await self._valkey.get(self._state_key(symbol, tf))
        state_updated_ts_raw = await self._valkey.get(self._state_updated_ts_key(symbol, tf))
        disconnect_ts_raw = await self._valkey.get(self._disconnect_ts_key(symbol, tf))
        last_live_ts_raw = await self._valkey.get(self._last_live_ts_key(symbol, tf))
        count_raw = await self._valkey.get(self._disconnect_count_key(symbol, tf))
        state_updated_ts = int(state_updated_ts_raw) if state_updated_ts_raw else None
        last_live_ts = int(last_live_ts_raw) if last_live_ts_raw else None
        last_disconnect_ts = int(disconnect_ts_raw) if disconnect_ts_raw else None
        return {
            "state": state_raw or IngestionState.COLD.value,
            "state_updated_ts": state_updated_ts,
            "state_age_ms": (now_ms - state_updated_ts) if state_updated_ts is not None else None,
            "last_live_ts": last_live_ts,
            "last_live_age_ms": (now_ms - last_live_ts) if last_live_ts is not None else None,
            "last_disconnect_ts": last_disconnect_ts,
            "disconnects_in_window": int(count_raw) if count_raw else 0,
        }

    async def is_stale(self, symbol: str, tf: str) -> bool:
        """Single authoritative staleness check.

        Returns True when TimescaleDB has no data for the symbol/tf pair or the
        latest candle is older than ingestion.websocket.warmup_threshold_ms.
        """
        warmup_threshold_ms: int = self._config.get(
            "ingestion.websocket.warmup_threshold_ms", 300_000
        )
        reader = TimescaleReader(DBPoolManager.get_reader_pool())
        max_ts = await reader.get_max_timestamp(symbol, tf)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        return max_ts == 0 or (now_ms - max_ts) > warmup_threshold_ms

    async def wait_until_warmed(
        self,
        symbol: str,
        tf: str,
        poll_interval_s: float | None = None,
        timeout_s: float | None = None,
    ) -> bool:
        """Block until state reaches WARMING or LIVE (WS safe to connect).

        Returns True on success, False if ERROR state is detected.
        Raises asyncio.TimeoutError if timeout_s is exceeded without resolution.

        Returns immediately True when already in WARMING or LIVE.
        """
        if poll_interval_s is None:
            poll_interval_s = float(
                self._config.get("ingestion.websocket.verification_sleep_seconds", 10)
            )
        if timeout_s is None:
            timeout_s = float(
                self._config.get("ingestion.websocket.warmup_timeout_seconds", 600)
            )

        initial = await self.get_state(symbol, tf)
        if initial in (IngestionState.WARMING, IngestionState.LIVE):
            return True
        if initial == IngestionState.ERROR:
            return False

        async def _poll() -> bool:
            while True:
                state = await self.get_state(symbol, tf)
                if state in (IngestionState.WARMING, IngestionState.LIVE):
                    return True
                if state == IngestionState.ERROR:
                    return False
                await asyncio.sleep(poll_interval_s)

        return await asyncio.wait_for(_poll(), timeout=timeout_s)
