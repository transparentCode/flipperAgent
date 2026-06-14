from __future__ import annotations

import json
import time
from typing import Any

from apps.strategy_app.observability.runtime_state import StrategyRuntimeStateStore
from apps.strategy_app.state import StrategyPair, StrategyPairState, StrategyRuntimeStatus


def signal_stream_key(asset: str, timeframe: str) -> str:
    return f"signals:{asset}:{timeframe}"


class StrategyObservabilityService:
    def __init__(self, redis_client: Any, pairs: list[StrategyPair]) -> None:
        self.redis_client = redis_client
        self.pairs = pairs
        self.state_store = StrategyRuntimeStateStore(redis_client)

    async def latest_signals(self) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        latest: dict[str, Any] = {}
        for pair in self.pairs:
            latest[pair.key] = await self._latest_stream_entry(
                signal_stream_key(pair.asset, pair.timeframe),
                now_ms,
            )
        return latest

    async def status(self) -> dict[str, StrategyRuntimeStatus]:
        latest = await self.latest_signals()
        result: dict[str, StrategyRuntimeStatus] = {}
        for pair in self.pairs:
            entry = latest.get(pair.key, {})
            stored = await self.state_store.read(pair)
            latest_signal_ts = _coerce_float(entry.get("timestamp"))
            if stored is None:
                result[pair.key] = StrategyRuntimeStatus(
                    pair=pair,
                    state=_infer_state_from_latest(entry),
                    last_signal_ts=latest_signal_ts,
                    lag_ms=entry.get("lag_ms") if isinstance(entry.get("lag_ms"), int) else None,
                    detail={"latest_status": entry.get("status", "unknown")},
                )
                continue

            merged_detail = dict(stored.detail)
            merged_detail["latest_status"] = entry.get("status", "unknown")
            result[pair.key] = stored.model_copy(
                update={
                    "last_signal_ts": latest_signal_ts or stored.last_signal_ts,
                    "lag_ms": (
                        entry.get("lag_ms")
                        if isinstance(entry.get("lag_ms"), int)
                        else stored.lag_ms
                    ),
                    "detail": merged_detail,
                }
            )
        return result

    async def _latest_stream_entry(self, stream: str, now_ms: int) -> dict[str, Any]:
        if self.redis_client is None:
            return {"stream": stream, "status": "unavailable"}

        try:
            messages = await self.redis_client.xrevrange(stream, count=1)
        except Exception as exc:
            return {"stream": stream, "status": "error", "error": str(exc)}

        if not messages:
            return {"stream": stream, "status": "no_data"}

        message_id, payload = messages[0]
        decoded = _decode_stream_payload(payload)
        timestamp = decoded.get("timestamp")
        lag_ms = _compute_lag_ms(timestamp, now_ms)
        return {
            "stream": stream,
            "message_id": message_id.decode() if isinstance(message_id, bytes) else message_id,
            "timestamp": timestamp,
            "lag_ms": lag_ms,
            "status": "ok",
            "direction": decoded.get("direction"),
            "conviction": decoded.get("conviction"),
            "price": decoded.get("price"),
            "model_name": decoded.get("model_name", ""),
            "idempotency_key": decoded.get("idempotency_key", ""),
            "metadata": decoded.get("metadata", {}),
        }


def _decode_stream_payload(payload: dict[Any, Any]) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for key, value in payload.items():
        decoded_key = key.decode() if isinstance(key, bytes) else str(key)
        decoded_value = value.decode() if isinstance(value, bytes) else value
        if isinstance(decoded_value, str):
            try:
                decoded[decoded_key] = json.loads(decoded_value)
            except json.JSONDecodeError:
                decoded[decoded_key] = decoded_value
        else:
            decoded[decoded_key] = decoded_value
    return decoded


def _compute_lag_ms(timestamp: Any, now_ms: int) -> int | None:
    ts = _coerce_float(timestamp)
    if ts is None:
        return None
    ts_ms = ts * 1000 if ts < 1e12 else ts
    return now_ms - int(ts_ms)


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _infer_state_from_latest(entry: dict[str, Any]) -> StrategyPairState:
    status = entry.get("status")
    if status == "ok":
        return StrategyPairState.LIVE
    if status == "error":
        return StrategyPairState.FAILED
    return StrategyPairState.WARMING
