"""Certify N2C retention and destructive-Valkey-loss recovery.

The command is read-only by default.  ``--execute`` requires
``INGESTION_RUN_N2C_RETENTION=1`` and performs only the explicitly scoped
fixtures and isolated Valkey DB15 recovery proof.  It never flushes Valkey DB0,
deletes production streams/groups, or replays already-published outbox rows.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
for _path in (REPOSITORY_ROOT, SOURCE_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from apps.ingestion_app.domain.candle import CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.publication.outbox import build_candle_committed_event
from apps.ingestion_app.services.asset_lifecycle import (
    MANIFEST_SOURCE,
    AssetLifecycleReconciler,
)
from apps.ingestion_app.services.retention import RetentionJanitor
from apps.ingestion_app.settings import (
    IngestionSettings,
    load_ingestion_settings,
)
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from apps.ingestion_app.storage.repository import CandleRepository
from apps.signal_app.catalog import SignalPairCatalog
from apps.signal_app.models import SignalPair, SignalPairState
from apps.signal_app.observability.runtime_state import SignalRuntimeStateStore
from apps.signal_app.ohlcv_source import IngestionHistoryFetcher
from apps.signal_app.runtime.runner import SignalRuntimeRunner
from apps.signal_app.runtime_pairs import build_signal_pairs
from apps.signal_app.settings import SignalWorkerSettings
from libs.common.asset_manifest import AssetManifestStore
from libs.common.config import ConfigManager
from libs.common.connections import init_db_pools
from libs.common.db.pool_manager import DBPoolManager
from libs.common.stream_keys import feature_stream_key, price_update_stream_key

INGESTION_URL = "http://127.0.0.1:8003"
DB15_URI = os.getenv("N2C_VALKEY_DB15_URI", "redis://localhost:6380/15")
ALL_ASSETS = ("BTC", "ETH", "XRP", "SOL", "BNB", "DOGE")
ALL_SYMBOLS = tuple(f"{asset}USDT" for asset in ALL_ASSETS)
ALL_INSTRUMENTS = tuple(f"{asset}-USDT-PERP" for asset in ALL_ASSETS)
SIGNAL_PAIRS = (
    ("BNBUSDT", "30m"),
    ("BTCUSDT", "1h"),
    ("BTCUSDT", "4h"),
    ("DOGEUSDT", "1h"),
    ("DOGEUSDT", "4h"),
    ("ETHUSDT", "4h"),
    ("SOLUSDT", "1h"),
    ("XRPUSDT", "1h"),
)
COMPOSE_SERVICES = (
    "db",
    "broker",
    "ingestion",
    "signal-worker",
    "strategy-worker",
    "risk-worker",
    "execution-worker",
    "portfolio-worker",
)
SAFETY_SERVICES = COMPOSE_SERVICES[2:]
OPERATION_TIMEOUT = 180.0


class N2CError(RuntimeError):
    """A bounded N2C failure with handoff-facing status and evidence."""

    def __init__(
        self,
        status: str,
        message: str,
        *,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        self.status = status
        self.evidence = evidence or {}
        super().__init__(message)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _resolved_valkey_db(client: Any) -> Any:
    pool = getattr(client, "connection_pool", None)
    connection_kwargs = getattr(pool, "connection_kwargs", None)
    if not isinstance(connection_kwargs, dict):
        return None
    return connection_kwargs.get("db")


def _require_db15_client(client: Any) -> int:
    resolved_db = _resolved_valkey_db(client)
    if resolved_db != 15:
        raise N2CError(
            "BLOCKED_N2C_VALKEY_ISOLATION",
            "N2C destructive certification requires logical Valkey DB15; "
            f"resolved DB={resolved_db!r}",
            evidence={"resolved_db": resolved_db, "configured_uri": DB15_URI},
        )
    return resolved_db


def _validate_db15_uri() -> int:
    import valkey

    client = None
    try:
        client = valkey.Valkey.from_url(DB15_URI, decode_responses=True)
        return _require_db15_client(client)
    except N2CError:
        raise
    except Exception as exc:
        raise N2CError(
            "BLOCKED_N2C_VALKEY_ISOLATION",
            "unable to resolve the configured Valkey logical database",
            evidence={"configured_uri": DB15_URI, "error": repr(exc)},
        ) from exc
    finally:
        if client is not None:
            client.close()


def _fixture_publication_times(now: datetime) -> tuple[datetime, datetime]:
    return now - timedelta(days=8), now - timedelta(days=6)


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise N2CError(
            "BLOCKED_N2C_RESOURCE_RESTORE",
            f"command failed ({result.returncode}): {' '.join(args)}",
            evidence={
                "stdout": result.stdout[-2000:],
                "stderr": result.stderr[-2000:],
            },
        )
    return result


def _compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run("docker", "compose", *args, check=check)


def _service_state(service: str) -> dict[str, Any]:
    ids = tuple(
        line.strip()
        for line in _compose("ps", "-a", "-q", service, check=False).stdout.splitlines()
        if line.strip()
    )
    containers: list[dict[str, Any]] = []
    for container_id in ids:
        raw = _run(
            "docker",
            "inspect",
            "-f",
            "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}",
            container_id,
        ).stdout.strip()
        state, _, remainder = raw.partition("|")
        health, _, remainder = remainder.partition("|")
        exit_code, _, oom_killed = remainder.partition("|")
        containers.append(
            {
                "id": container_id,
                "state": state,
                "health": health or "not_configured",
                "exit_code": exit_code,
                "oom_killed": oom_killed.lower() == "true",
            }
        )
    return {
        "present": bool(containers),
        "running": any(item["state"] == "running" for item in containers),
        "healthy": any(
            item["state"] == "running" and item["health"] == "healthy"
            for item in containers
        ),
        "containers": containers,
    }


def _capture_states() -> dict[str, dict[str, Any]]:
    return {service: _service_state(service) for service in COMPOSE_SERVICES}


def _git_sha() -> str:
    return _run("git", "rev-parse", "HEAD").stdout.strip()


async def _create_pool() -> asyncpg.Pool:
    dsn = os.getenv(
        "POSTGRES_URI",
        "postgresql://flipper:flipperpass@localhost:5432/flipper_db",
    )
    return await asyncpg.create_pool(dsn, min_size=1, max_size=4)


def _fresh_manager() -> ConfigManager:
    ConfigManager.reset_singleton()
    return ConfigManager()


def _require_preconditions(states: dict[str, dict[str, Any]]) -> None:
    if not states["db"]["running"] or not states["db"]["healthy"]:
        raise N2CError(
            "ENVIRONMENT_PRECONDITION_CHANGED",
            "Timescale must be running and healthy",
            evidence={"db": states["db"]},
        )
    active = {
        service: states[service]
        for service in SAFETY_SERVICES
        if states[service]["running"]
    }
    if active:
        raise N2CError(
            "ENVIRONMENT_PRECONDITION_CHANGED",
            "ingestion, signal, and trading services must be stopped",
            evidence=active,
        )


async def _production_inventory(pool: asyncpg.Pool) -> dict[str, Any]:
    async with pool.acquire() as connection:
        candle = await connection.fetchrow(
            """
            SELECT count(*)::bigint AS rows, min(open_time) AS first_open,
                   max(close_time) AS last_close,
                   pg_total_relation_size('ingestion.candles')::bigint AS bytes
            FROM ingestion.candles
            """
        )
        outbox = await connection.fetchrow(
            """
            SELECT count(*)::bigint AS rows,
                   count(*) FILTER (WHERE published_at IS NULL)::bigint AS pending,
                   count(*) FILTER (WHERE published_at IS NOT NULL)::bigint AS published,
                   min(published_at) FILTER (WHERE published_at IS NOT NULL) AS first_published,
                   max(published_at) FILTER (WHERE published_at IS NOT NULL) AS last_published,
                   pg_total_relation_size('ingestion.outbox')::bigint AS bytes
            FROM ingestion.outbox
            """
        )
        per_asset = await connection.fetch(
            """
            SELECT instrument_id, count(*)::bigint AS rows,
                   min(open_time) AS first_open, max(close_time) AS last_close
            FROM ingestion.candles
            WHERE instrument_id = ANY($1::text[])
            GROUP BY instrument_id ORDER BY instrument_id
            """,
            list(ALL_INSTRUMENTS),
        )
        chunk_info = await connection.fetchrow(
            """
            SELECT hypertable_name, time_interval::text AS chunk_interval
            FROM timescaledb_information.dimensions
            WHERE hypertable_schema = 'ingestion'
              AND hypertable_name = 'candles'
              AND column_name = 'open_time'
            """
        )
        chunk_count = await connection.fetchval(
            "SELECT count(*)::bigint FROM show_chunks('ingestion.candles')"
        )
        candle_chunk_bytes = await connection.fetchval(
            """
            SELECT COALESCE(sum(pg_total_relation_size(chunk)), 0)::bigint
            FROM show_chunks('ingestion.candles') AS chunk
            """
        )
        database_bytes = await connection.fetchval(
            "SELECT pg_database_size(current_database())::bigint"
        )
        index_exists = await connection.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM pg_indexes
                WHERE schemaname='ingestion'
                  AND indexname='ingestion_outbox_published_idx'
            )
            """
        )
    return {
        "candles": {
            "rows": int(candle["rows"]),
            "first_open": _iso(candle["first_open"]),
            "last_close": _iso(candle["last_close"]),
            "bytes": int(candle_chunk_bytes),
            "hypertable_root_bytes": int(candle["bytes"]),
        },
        "outbox": {
            "rows": int(outbox["rows"]),
            "pending": int(outbox["pending"]),
            "published": int(outbox["published"]),
            "first_published": _iso(outbox["first_published"]),
            "last_published": _iso(outbox["last_published"]),
            "bytes": int(outbox["bytes"]),
        },
        "database_bytes": int(database_bytes),
        "per_asset": {
            row["instrument_id"]: {
                "rows": int(row["rows"]),
                "first_open": _iso(row["first_open"]),
                "last_close": _iso(row["last_close"]),
            }
            for row in per_asset
        },
        "chunks": {
            "count": int(chunk_count),
            "interval": chunk_info["chunk_interval"] if chunk_info else None,
        },
        "published_index_exists": bool(index_exists),
    }


async def _pending_state(pool: asyncpg.Pool) -> dict[str, int]:
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT count(*)::bigint AS total,
                   count(*) FILTER (WHERE published_at IS NULL)::bigint AS pending,
                   count(*) FILTER (WHERE published_at IS NOT NULL)::bigint AS published
            FROM ingestion.outbox
            """
        )
    return {key: int(row[key]) for key in ("total", "pending", "published")}


def _runtime_service_states() -> dict[str, dict[str, Any]]:
    return {service: _service_state(service) for service in ("broker", "ingestion")}


async def _require_runtime_services_alive() -> dict[str, dict[str, Any]]:
    states = await asyncio.to_thread(_runtime_service_states)
    if any(
        not state.get("running") or not state.get("healthy")
        for state in states.values()
    ):
        raise N2CError(
            "BLOCKED_N2C_RETENTION_LIVENESS",
            "broker and ingestion must remain alive while the publisher drains",
            evidence={"services": states},
        )
    return states


async def _wait_pending_zero(
    pool: asyncpg.Pool, timeout: float = 180.0
) -> dict[str, int]:
    deadline = time.monotonic() + timeout
    await _require_runtime_services_alive()
    last = await _pending_state(pool)
    while time.monotonic() < deadline:
        await _require_runtime_services_alive()
        if last["pending"] == 0:
            return last
        await asyncio.sleep(2)
        last = await _pending_state(pool)
    raise N2CError(
        "BLOCKED_N2C_PUBLISHED_OUTBOX_CLEANUP",
        "production outbox did not drain",
        evidence=last,
    )


async def _assert_pending_zero(pool: asyncpg.Pool, *, phase: str) -> dict[str, int]:
    """Read the already-established quiescent state without waiting."""
    state = await _pending_state(pool)
    if state["pending"] != 0:
        raise N2CError(
            "BLOCKED_N2C_PUBLISHED_OUTBOX_CLEANUP",
            f"production outbox was not quiescent after {phase}",
            evidence={"phase": phase, **state},
        )
    return state


def _http(path: str) -> tuple[int, dict[str, Any] | None]:
    try:
        with urllib.request.urlopen(f"{INGESTION_URL}{path}", timeout=4) as response:
            body = response.read()
            return response.status, json.loads(body) if body else None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return 0, None


def _http_post(path: str) -> tuple[int, dict[str, Any] | None]:
    try:
        request = urllib.request.Request(f"{INGESTION_URL}{path}", method="POST")
        with urllib.request.urlopen(request, timeout=4) as response:
            body = response.read()
            return response.status, json.loads(body) if body else None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return 0, None


async def _wait_ingestion_live(timeout: float = 180.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        live, _ = await asyncio.to_thread(_http, "/health/live")
        ready, _ = await asyncio.to_thread(_http, "/health/ready")
        runtime_status, runtime = await asyncio.to_thread(_http, "/runtime")
        last = {"live": live, "ready": ready, "runtime": runtime}
        if (
            live == 200
            and ready == 200
            and runtime_status == 200
            and str((runtime or {}).get("state", "")).upper() == "LIVE"
        ):
            return last
        service = await asyncio.to_thread(_service_state, "ingestion")
        if service["present"] and not service["running"]:
            raise N2CError(
                "BLOCKED_N2C_RETENTION_LIVENESS",
                "ingestion exited before reaching LIVE",
                evidence={"service": service, "http": last},
            )
        await asyncio.sleep(2)
    raise N2CError(
        "BLOCKED_N2C_RETENTION_LIVENESS", "ingestion did not reach LIVE", evidence=last
    )


async def _pause_ingestion_runtime(
    timeout: float = OPERATION_TIMEOUT,
) -> dict[str, Any]:
    pause_status, pause_response = await asyncio.to_thread(_http_post, "/runtime/pause")
    if pause_status != 200 or pause_response is None:
        raise N2CError(
            "BLOCKED_N2C_RETENTION_LIVENESS",
            "ingestion runtime pause request failed",
            evidence={"http_status": pause_status, "response": pause_response},
        )

    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        runtime_status, runtime = await asyncio.to_thread(_http, "/runtime")
        last = {"http_status": runtime_status, "runtime": runtime}
        if (
            runtime_status == 200
            and runtime is not None
            and str(runtime.get("desired_state", "")).lower() == "paused"
            and str(runtime.get("state", "")).lower() == "stopped"
        ):
            return {
                "pause_request": {
                    "http_status": pause_status,
                    "response": pause_response,
                },
                "paused_runtime": last,
            }
        await asyncio.sleep(2)
    raise N2CError(
        "BLOCKED_N2C_RETENTION_LIVENESS",
        "ingestion runtime did not reach paused/stopped state",
        evidence=last,
    )


async def _chunk_isolation_check(
    pool: asyncpg.Pool,
    *,
    instrument_id: str,
    cutoff: datetime,
) -> dict[str, Any]:
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT tableoid::regclass::text AS chunk_name,
                   count(*)::bigint AS total_rows,
                   count(*) FILTER (WHERE instrument_id=$1)::bigint AS fixture_rows
            FROM ingestion.candles
            WHERE open_time < $2
            GROUP BY tableoid
            """,
            instrument_id,
            cutoff,
        )
    evidence = [
        {
            "chunk_name": row["chunk_name"],
            "total_rows": int(row["total_rows"]),
            "fixture_rows": int(row["fixture_rows"]),
        }
        for row in rows
    ]
    if len(evidence) != 1 or evidence[0]["total_rows"] != evidence[0]["fixture_rows"]:
        raise N2CError(
            "BLOCKED_N2C_RETENTION_FIXTURE_ISOLATION",
            "old fixture chunk contains non-fixture production rows",
            evidence={"chunks": evidence, "instrument_id": instrument_id},
        )
    return {"chunks": evidence}


async def _insert_outbox_fixture(
    pool: asyncpg.Pool,
    *,
    event_id: UUID,
    label: str,
    occurred_at: datetime,
    published_at: datetime | None,
) -> None:
    async with pool.acquire() as connection:
        await connection.execute(
            """
            INSERT INTO ingestion.outbox
                (event_id,event_type,schema_version,producer,occurred_at,payload,published_at)
            VALUES ($1,'n2c.fixture',1,'n2c', $2, $3::jsonb, $4)
            """,
            event_id,
            occurred_at,
            json.dumps({"n2c_fixture": label}),
            published_at,
        )


async def _delete_fixture_rows(
    pool: asyncpg.Pool,
    *,
    instrument_id: str,
    event_ids: tuple[UUID, ...],
) -> None:
    async with pool.acquire() as connection:
        await connection.execute(
            "DELETE FROM ingestion.candles WHERE instrument_id=$1",
            instrument_id,
        )
        await connection.execute(
            "DELETE FROM ingestion.outbox WHERE event_id=ANY($1::uuid[])",
            list(event_ids),
        )


async def _retention_fixture(
    pool: asyncpg.Pool,
    settings: IngestionSettings,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=settings.retention.candle_days)
    async with pool.acquire() as connection:
        old_count = await connection.fetchval(
            "SELECT count(*)::bigint FROM ingestion.candles WHERE open_time < $1",
            cutoff,
        )
    if int(old_count) != 0:
        raise N2CError(
            "ENVIRONMENT_PRECONDITION_CHANGED",
            "legitimate production candle history is older than the N2C cutoff",
            evidence={"cutoff": _iso(cutoff), "old_rows": int(old_count)},
        )

    run_id = uuid4().hex[:12].upper()
    instrument_id = f"N2C-{run_id}-USDT-PERP"
    old_open = (cutoff - timedelta(days=30)).replace(second=0, microsecond=0)
    candle = CanonicalCandle(
        lane=MarketLane("binance", instrument_id, "1m"),
        open_time=old_open,
        close_time=old_open + timedelta(minutes=1),
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal("100.5"),
        volume=Decimal(1),
        taker_buy_base=Decimal("0.5"),
        source_type="provider",
        source_provider="binance_native",
        source_timeframe=None,
    )
    event = build_candle_committed_event(candle)
    repository = CandleRepository(pool)
    status = await repository.commit_candle(candle, event)
    if str(status) != "inserted":
        raise N2CError(
            "BLOCKED_N2C_CANDLE_RETENTION",
            "old canonical fixture did not insert",
            evidence={"status": str(status)},
        )
    old_published_at, recent_published_at = _fixture_publication_times(now)
    async with pool.acquire() as connection:
        await connection.execute(
            "UPDATE ingestion.outbox SET published_at=$2 WHERE event_id=$1",
            event.event_id,
            old_published_at,
        )

    fixture_ids = {
        "old_candle": event.event_id,
        "old_published": uuid4(),
        "recent_published": uuid4(),
        "pending": uuid4(),
    }
    await _insert_outbox_fixture(
        pool,
        event_id=fixture_ids["old_published"],
        label="old-published",
        occurred_at=old_published_at,
        published_at=old_published_at,
    )
    await _insert_outbox_fixture(
        pool,
        event_id=fixture_ids["recent_published"],
        label="recent-published",
        occurred_at=recent_published_at,
        published_at=recent_published_at,
    )
    await _insert_outbox_fixture(
        pool,
        event_id=fixture_ids["pending"],
        label="pending-old",
        occurred_at=old_published_at,
        published_at=None,
    )

    try:
        isolation = await _chunk_isolation_check(
            pool,
            instrument_id=instrument_id,
            cutoff=cutoff,
        )
        janitor = RetentionJanitor(
            repository=repository,
            settings=settings.retention,
        )
        evidence = await janitor.cleanup_once()
        async with pool.acquire() as connection:
            old_candle_rows = await connection.fetchval(
                "SELECT count(*)::bigint FROM ingestion.candles WHERE instrument_id=$1",
                instrument_id,
            )
            remaining = await connection.fetch(
                "SELECT event_id FROM ingestion.outbox WHERE event_id=ANY($1::uuid[])",
                list(fixture_ids.values()),
            )
        remaining_ids = {row["event_id"] for row in remaining}
        if int(old_candle_rows) != 0:
            raise N2CError(
                "BLOCKED_N2C_CANDLE_RETENTION",
                "old fixture candle survived chunk retention",
                evidence={"rows": int(old_candle_rows), "cleanup": asdict(evidence)},
            )
        if fixture_ids["old_published"] in remaining_ids:
            raise N2CError(
                "BLOCKED_N2C_PUBLISHED_OUTBOX_CLEANUP",
                "eligible published fixture survived cleanup",
            )
        if fixture_ids["recent_published"] not in remaining_ids:
            raise N2CError(
                "BLOCKED_N2C_PUBLISHED_OUTBOX_CLEANUP",
                "recent published fixture was deleted",
            )
        if fixture_ids["pending"] not in remaining_ids:
            raise N2CError(
                "BLOCKED_N2C_PENDING_SAFETY",
                "pending fixture was deleted",
            )
        if evidence.outbox_rows_deleted < 2 or not evidence.candle_chunks_dropped:
            raise N2CError(
                "BLOCKED_N2C_PUBLISHED_OUTBOX_CLEANUP",
                "retention fixture did not report expected deletions",
                evidence={
                    "outbox_rows_deleted": evidence.outbox_rows_deleted,
                    "chunks": evidence.candle_chunks_dropped,
                },
            )
        return {
            "instrument_id": instrument_id,
            "cutoff": _iso(cutoff),
            "isolation": isolation,
            "cleanup": {
                "started_at": _iso(evidence.started_at),
                "candle_cutoff": _iso(evidence.candle_cutoff),
                "published_outbox_cutoff": _iso(evidence.published_outbox_cutoff),
                "outbox_rows_deleted": evidence.outbox_rows_deleted,
                "outbox_batches": evidence.outbox_batches,
                "candle_chunks_dropped": evidence.candle_chunks_dropped,
                "completed_at": _iso(evidence.completed_at),
            },
            "old_published_deleted": True,
            "recent_published_retained": True,
            "pending_retained": True,
            "fixture_publication_ages_days": {
                "old_published": 8,
                "recent_published": 6,
                "pending": None,
            },
        }
    finally:
        await _delete_fixture_rows(
            pool,
            instrument_id=instrument_id,
            event_ids=tuple(fixture_ids.values()),
        )


async def _production_noop(
    pool: asyncpg.Pool,
    settings: IngestionSettings,
    before: dict[str, Any],
) -> dict[str, Any]:
    evidence = await RetentionJanitor(
        repository=CandleRepository(pool),
        settings=settings.retention,
    ).cleanup_once()
    after = await _production_inventory(pool)
    if evidence.outbox_rows_deleted != 0 or evidence.candle_chunks_dropped:
        raise N2CError(
            "BLOCKED_N2C_CANDLE_RETENTION",
            "normal production retention run was not a no-op",
            evidence={"cleanup": asdict(evidence)},
        )
    if after["candles"] != before["candles"] or after["outbox"] != before["outbox"]:
        raise N2CError(
            "BLOCKED_N2C_CANDLE_RETENTION",
            "protected production storage changed during no-op retention run",
            evidence={"before": before, "after": after},
        )
    return {
        "cleanup": {
            "outbox_rows_deleted": evidence.outbox_rows_deleted,
            "candle_chunks_dropped": evidence.candle_chunks_dropped,
        },
        "before": before,
        "after": after,
    }


async def _history_evidence(
    pool: asyncpg.Pool,
    manager: ConfigManager,
) -> dict[str, Any]:
    settings = SignalWorkerSettings.from_config(manager)
    catalog = SignalPairCatalog(config_manager=manager)
    pairs = catalog.list_pairs()
    runner = SignalRuntimeRunner(
        catalog=catalog,
        initial_pairs=pairs,
        worker_settings=settings,
    )
    evidence: dict[str, Any] = {}
    for worker in runner.build_workers():
        trigger_timeframe = worker.trigger_timeframe
        pair = SignalPair(
            asset=worker.asset,
            timeframe=worker.timeframe,
            trigger_timeframe=(
                None if trigger_timeframe == worker.timeframe else trigger_timeframe
            ),
        )
        pair_key = pair.key
        rows = await IngestionHistoryFetcher(
            settings.source_binding(worker.asset),
            pool=pool,
        )(worker.asset, trigger_timeframe, worker.max_lookback)
        evidence[pair_key] = {
            "asset": worker.asset,
            "timeframe": worker.timeframe,
            "trigger_timeframe": trigger_timeframe,
            "required": worker.max_lookback,
            "returned": len(rows),
            "source": "ingestion.candles",
        }
        if len(rows) != worker.max_lookback:
            raise N2CError(
                "BLOCKED_N2C_SIGNAL_REPRIME",
                f"post-retention history is short for {pair_key}",
                evidence=evidence[pair_key],
            )
    return evidence


async def _db15_client() -> Any:
    import valkey.asyncio as valkey

    client = valkey.Valkey.from_url(DB15_URI, decode_responses=True)
    try:
        _require_db15_client(client)
        await client.ping()
    except Exception:
        await client.aclose()
        raise
    return client


async def _stream_tail(client: Any, key: str) -> str | None:
    rows = await client.xrevrange(key, count=1)
    if not rows:
        return None
    value = rows[0][0]
    return value.decode() if isinstance(value, bytes) else str(value)


async def _db15_signal_snapshot(
    client: Any,
    manager: ConfigManager,
    runner: SignalRuntimeRunner,
) -> dict[str, Any]:
    settings = SignalWorkerSettings.from_config(manager)
    state_store = SignalRuntimeStateStore(client)
    result: dict[str, Any] = {}
    for worker in runner.workers:
        pair = SignalPair(
            asset=worker.asset,
            timeframe=worker.timeframe,
            trigger_timeframe=(
                None
                if worker.trigger_timeframe == worker.timeframe
                else worker.trigger_timeframe
            ),
        )
        status = await state_store.read(pair)
        group_data: dict[str, Any] | None = None
        consumer_data: dict[str, Any] | None = None
        probe_error: str | None = None
        try:
            groups = await client.xinfo_groups(worker.stream_key)
            group_data = next(
                (
                    {
                        (key.decode() if isinstance(key, bytes) else key): (
                            value.decode() if isinstance(value, bytes) else value
                        )
                        for key, value in group.items()
                    }
                    for group in groups
                    if (group.get("name") or group.get(b"name"))
                    in {settings.consumer_group, settings.consumer_group.encode()}
                ),
                None,
            )
            if group_data is not None:
                consumers = await client.xinfo_consumers(
                    worker.stream_key,
                    settings.consumer_group,
                )
                for raw in consumers:
                    normalized = {
                        (key.decode() if isinstance(key, bytes) else key): (
                            value.decode() if isinstance(value, bytes) else value
                        )
                        for key, value in raw.items()
                    }
                    if normalized.get("name") == worker.consumer_name:
                        consumer_data = normalized
                        break
        except Exception as exc:  # noqa: BLE001 - status is reported below
            probe_error = repr(exc)
        result[f"{worker.asset}:{worker.timeframe}"] = {
            "state": status.state.value if status else None,
            "stream": worker.stream_key,
            "consumer": consumer_data,
            "group": group_data,
            "status_probe_error": probe_error,
            "feature_tail": await _stream_tail(
                client, feature_stream_key(worker.asset, worker.timeframe)
            ),
            "price_tail": await _stream_tail(
                client, price_update_stream_key(worker.asset, worker.timeframe)
            ),
        }
    return result


async def _wait_db15_signal(
    client: Any,
    manager: ConfigManager,
    runner: SignalRuntimeRunner,
    start_task: asyncio.Task[Any],
    timeout: float = 180.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        if start_task.done():
            result = start_task.exception()
            if result is not None:
                raise N2CError(
                    "BLOCKED_N2C_SIGNAL_BOOTSTRAP",
                    "signal runner terminated during DB15 recovery",
                    evidence={"error": repr(result)},
                )
            raise N2CError(
                "BLOCKED_N2C_SIGNAL_BOOTSTRAP",
                "signal runner exited unexpectedly",
            )
        last = await _db15_signal_snapshot(client, manager, runner)
        good = len(last) == len(SIGNAL_PAIRS)
        for asset, timeframe in SIGNAL_PAIRS:
            item = last.get(f"{asset}:{timeframe}", {})
            group = item.get("group") or {}
            consumer = item.get("consumer") or {}
            if (
                item.get("state") != SignalPairState.LIVE.value
                or item.get("feature_tail") is None
                or item.get("price_tail") is None
                or int(group.get("pending") or 0) != 0
                or int(group.get("lag") or 0) != 0
                or consumer.get("name") is None
            ):
                good = False
                break
        if good:
            return last
        await asyncio.sleep(2)
    raise N2CError(
        "BLOCKED_N2C_SIGNAL_BOOTSTRAP",
        "not all eight pairs reached LIVE from Timescale on empty DB15",
        evidence=last,
    )


async def _db15_recovery(
    manager: ConfigManager,
    settings: IngestionSettings,
) -> dict[str, Any]:
    client = await _db15_client()
    db_pool_started = False
    runner: SignalRuntimeRunner | None = None
    start_task: asyncio.Task[Any] | None = None
    validated_db15 = False
    try:
        _require_db15_client(client)
        validated_db15 = True
        await client.flushdb()
        if await client.dbsize() != 0:
            raise N2CError("BLOCKED_N2C_VALKEY_ISOLATION", "DB15 did not start empty")
        store = AssetManifestStore(
            client,
            lifecycle_stream_maxlen=settings.publication.stream_maxlen,
            lifecycle_stream_approximate=settings.publication.stream_approximate,
        )
        reconciler = AssetLifecycleReconciler(
            settings_provider=lambda: settings,
            manifest_store=store,
        )
        events = await reconciler.reconcile_all()
        manifests = await store.list_assets()
        if {manifest.symbol for manifest in manifests} != set(ALL_SYMBOLS) or len(
            events
        ) != 6:
            raise N2CError(
                "BLOCKED_N2C_MANIFEST_REBUILD",
                "empty DB15 did not rebuild six ingestion manifests/events",
                evidence={
                    "manifests": [item.model_dump(mode="json") for item in manifests],
                    "events": [item.model_dump(mode="json") for item in events],
                },
            )
        if any(
            item.source != MANIFEST_SOURCE
            or not item.enabled
            or item.desired_state != "LIVE"
            for item in manifests
        ):
            raise N2CError(
                "BLOCKED_N2C_MANIFEST_REBUILD",
                "DB15 manifests are not all ingestion LIVE-owned",
            )
        lifecycle_length = await client.xlen("asset:lifecycle")

        await init_db_pools(manager)
        db_pool_started = True
        signal_settings = SignalWorkerSettings.from_config(manager)
        pairs = build_signal_pairs(manager, live_manifests=manifests)
        pair_keys = {
            (pair.asset, pair.trigger_timeframe or pair.timeframe) for pair in pairs
        }
        if pair_keys != set(SIGNAL_PAIRS):
            raise N2CError(
                "BLOCKED_N2C_SIGNAL_BOOTSTRAP",
                "DB15 recovery resolved an unexpected signal graph",
                evidence={"pairs": sorted(pair_keys)},
            )
        runner = SignalRuntimeRunner(
            catalog=SignalPairCatalog(config_manager=manager),
            initial_pairs=pairs,
            worker_settings=signal_settings,
        )
        baseline_streams = {
            worker.stream_key: await client.xlen(worker.stream_key)
            for worker in runner.build_workers()
        }
        if any(baseline_streams.values()):
            raise N2CError(
                "BLOCKED_N2C_VALKEY_ISOLATION",
                "DB15 contained historical ingestion OHLCV stream entries",
                evidence={"streams": baseline_streams},
            )
        await runner.connect(client)
        start_task = asyncio.create_task(runner.start(), name="n2c-db15-signal-runner")
        signal = await _wait_db15_signal(client, manager, runner, start_task)
        return {
            "db": 15,
            "manifests": len(manifests),
            "lifecycle_events": len(events),
            "lifecycle_stream_length": int(lifecycle_length),
            "pre_signal_ohlcv_streams": baseline_streams,
            "signal": signal,
            "automatic_published_outbox_replay": False,
        }
    finally:
        if runner is not None:
            await runner.stop()
        if start_task is not None:
            start_task.cancel()
            await asyncio.gather(start_task, return_exceptions=True)
        if db_pool_started:
            await DBPoolManager.close_pools()
        if validated_db15:
            await client.flushdb()
            if await client.dbsize() != 0:
                raise N2CError("BLOCKED_N2C_VALKEY_ISOLATION", "DB15 cleanup failed")
        await client.aclose()


async def _startup_janitor_and_runtime(
    pool: asyncpg.Pool,
    states: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    broker_started = False
    ingestion_started = False
    try:
        if not states["broker"]["running"]:
            _compose("up", "-d", "broker")
            broker_started = True
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                current = await asyncio.to_thread(_service_state, "broker")
                if current["running"] and current["healthy"]:
                    break
                await asyncio.sleep(2)
            else:
                raise N2CError(
                    "BLOCKED_N2C_RETENTION_LIVENESS",
                    "broker did not become healthy for ingestion startup gate",
                )
        started_at = datetime.now(UTC)
        _compose("up", "-d", "ingestion")
        ingestion_started = True
        runtime = await _wait_ingestion_live()
        pause = await _pause_ingestion_runtime()
        pre_stop_outbox = await _wait_pending_zero(pool)
        pre_stop_services = await _require_runtime_services_alive()
        logs = _compose(
            "logs",
            "--since",
            _iso(started_at) or "now",
            "--no-color",
            "ingestion",
            check=False,
        ).stdout
        if "ingestion retention cleanup completed" not in logs:
            raise N2CError(
                "BLOCKED_N2C_RETENTION_LIVENESS",
                "startup janitor completion was not present in ingestion logs",
                evidence={"logs": logs[-4000:]},
            )
        return {
            "runtime": runtime,
            "pause": pause,
            "pre_stop_services": pre_stop_services,
            "pre_stop_outbox": pre_stop_outbox,
            "pending": pre_stop_outbox,
            "startup_janitor_log_seen": True,
        }
    finally:
        if ingestion_started:
            _compose("stop", "ingestion", check=False)
        if broker_started:
            _compose("stop", "broker", check=False)


async def _execute() -> dict[str, Any]:
    states = _capture_states()
    _require_preconditions(states)
    manager = _fresh_manager()
    pool: asyncpg.Pool | None = None
    try:
        settings = load_ingestion_settings(manager)
        if any(not settings.assets[asset].enabled for asset in ALL_ASSETS):
            raise N2CError(
                "ENVIRONMENT_PRECONDITION_CHANGED",
                "N2B2 six-asset ingestion configuration is not active",
            )
        if any(
            not settings.assets[asset].owns_manifest_lifecycle for asset in ALL_ASSETS
        ):
            raise N2CError(
                "ENVIRONMENT_PRECONDITION_CHANGED",
                "N2B2 six-asset manifest ownership is not active",
            )
        signal_settings = SignalWorkerSettings.from_config(manager)
        if any(
            signal_settings.source_binding(f"{asset}USDT").source != "ingestion"
            for asset in ALL_ASSETS
        ):
            raise N2CError(
                "ENVIRONMENT_PRECONDITION_CHANGED",
                "not all six signal bindings use ingestion",
            )
        certification_db_index = _validate_db15_uri()
        pool = await _create_pool()
        await apply_ingestion_schema(pool)
        before = await _production_inventory(pool)
        if before["outbox"]["pending"] != 0:
            raise N2CError(
                "ENVIRONMENT_PRECONDITION_CHANGED",
                "production pending outbox must be zero before N2C",
                evidence=before["outbox"],
            )
        if not before["published_index_exists"]:
            raise N2CError(
                "BLOCKED_N2C_OUTBOX_INDEX",
                "published outbox index is absent",
            )
        fixture = await _retention_fixture(pool, settings)
        noop = await _production_noop(pool, settings, before)
        history = await _history_evidence(pool, manager)
        startup = await _startup_janitor_and_runtime(pool, states)
        broker_was_running = states["broker"]["running"]
        if not broker_was_running:
            _compose("up", "-d", "broker")
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                broker = await asyncio.to_thread(_service_state, "broker")
                if broker["running"] and broker["healthy"]:
                    break
                await asyncio.sleep(2)
            else:
                raise N2CError(
                    "BLOCKED_N2C_VALKEY_ISOLATION",
                    "broker did not become healthy for DB15 recovery",
                )
        db15 = await _db15_recovery(manager, settings)
        if not broker_was_running:
            _compose("stop", "broker", check=False)
        final_inventory = await _production_inventory(pool)
        final_pending = await _assert_pending_zero(pool, phase="runtime_stop")
        return {
            "status": "READY_FOR_REVIEW",
            "starting_sha": _git_sha(),
            "retention_config": settings.retention.model_dump(),
            "production_before": before,
            "retention_fixture": fixture,
            "production_noop": noop,
            "post_retention_history": history,
            "startup_janitor": startup,
            "db15_recovery": db15,
            "production_db_index": 0,
            "certification_db_index": certification_db_index,
            "production_db0_flush_issued": False,
            "production_final": final_inventory,
            "final_pending_outbox": final_pending,
            "automatic_published_outbox_replay": False,
            "production_db0_untouched_by_db15_flush": True,
        }
    finally:
        if pool is not None:
            await pool.close()
        with contextlib.suppress(Exception):
            manager.shutdown()
        ConfigManager.reset_singleton()


def _dry_run() -> dict[str, Any]:
    manager = _fresh_manager()
    try:
        settings = load_ingestion_settings(manager)
        signal_settings = SignalWorkerSettings.from_config(manager)
        certification_db_index = _validate_db15_uri()
        return {
            "status": "DRY_RUN",
            "starting_sha": _git_sha(),
            "current_state_precondition": "typed_config_and_live_storage_checks",
            "retention_config": settings.retention.model_dump(),
            "enabled_assets": [
                asset.asset for asset in settings.assets.values() if asset.enabled
            ],
            "owned_assets": [
                asset.asset
                for asset in settings.assets.values()
                if asset.owns_manifest_lifecycle
            ],
            "source_bindings": {
                asset: {
                    "source": signal_settings.source_binding(asset).source,
                    "venue": signal_settings.source_binding(asset).venue,
                    "instrument_id": signal_settings.source_binding(
                        asset
                    ).instrument_id,
                }
                for asset in ALL_SYMBOLS
            },
            "isolated_valkey_uri": DB15_URI,
            "certification_db_index": certification_db_index,
            "production_db_index": 0,
            "production_db0_flush_issued": False,
            "automatic_published_outbox_replay": False,
            "N2C_STARTED": False,
        }
    finally:
        with contextlib.suppress(Exception):
            manager.shutdown()
        ConfigManager.reset_singleton()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.execute:
            if os.getenv("INGESTION_RUN_N2C_RETENTION") != "1":
                raise N2CError(
                    "ENVIRONMENT_PRECONDITION_CHANGED",
                    "set INGESTION_RUN_N2C_RETENTION=1 for N2C execution",
                )
            result = asyncio.run(_execute())
        else:
            result = _dry_run()
    except N2CError as exc:
        print(
            json.dumps(
                {
                    "status": exc.status,
                    "message": str(exc),
                    "evidence": exc.evidence,
                },
                indent=2,
                default=str,
            )
        )
        return 1
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
