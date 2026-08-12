"""Retire the completed legacy ingestion runtime's storage and Valkey state.

The command is read-only by default.  ``--execute`` requires
``INGESTION_RUN_N3B_RETIREMENT=1`` and performs only the explicitly listed
legacy table/key removals.  It never uses CASCADE, FLUSHDB, or FLUSHALL and it
does not touch ingestion candles, outbox rows, manifests, streams, or signal groups.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import asyncpg
import valkey.asyncio as valkey
from valkey.exceptions import ResponseError

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
for _path in (REPOSITORY_ROOT, SOURCE_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from apps.ingestion_app.settings import load_ingestion_settings
from apps.signal_app.ohlcv_source import stream_key_for_binding
from apps.signal_app.runtime_pairs import build_signal_pairs
from apps.signal_app.settings import SignalWorkerSettings
from libs.common.config import ConfigManager
from libs.common.connections import init_db_pools
from libs.common.db.pool_manager import DBPoolManager

ARTIFACT_DIR = REPOSITORY_ROOT / "artifacts/ingestion_n3b"
EXECUTE_STATE_ARTIFACT = ARTIFACT_DIR / "retirement_execute_state.json"
VERIFY_STATE_ARTIFACT = ARTIFACT_DIR / "retirement_verify_state.json"
ALL_ASSETS = ("BTC", "ETH", "XRP", "SOL", "BNB", "DOGE")
ALL_SYMBOLS = tuple(f"{asset}USDT" for asset in ALL_ASSETS)
ALL_INSTRUMENTS = tuple(f"{asset}-USDT-PERP" for asset in ALL_ASSETS)
EXPECTED_SIGNAL_PAIRS = {
    ("BNBUSDT", "30m"),
    ("BTCUSDT", "1h"),
    ("BTCUSDT", "4h"),
    ("DOGEUSDT", "1h"),
    ("DOGEUSDT", "4h"),
    ("ETHUSDT", "4h"),
    ("SOLUSDT", "1h"),
    ("XRPUSDT", "1h"),
}

LEGACY_TABLES = (
    "public.ohlcv",
    "public.ingestion_assets",
    "ingestion.provider_candles",
)
LEGACY_EXACT_KEYS = (
    "stream:control:ingestion",
    "stream:events:ingestion",
)
LEGACY_KEY_PATTERNS = (
    "stream:ohlcv:*",
    "ingestion:state:*",
    "ingestion:state_updated_ts:*",
    "ingestion:disconnect_ts:*",
    "ingestion:last_live_ts:*",
    "ingestion:last_ready_ts:*",
    "ingestion:disconnect_count:*",
    "ingestion:resume_backfill_required:*",
    "ingestion:last_closed_published:*",
    "ingestion:publish_dedup:*",
    "ingestion:runtime_status:*",
    "ingestion:registry_projection:*",
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
    "alert-worker",
    "alert-api",
    "api-server",
    "scraper-service",
    "scraper-tradingview",
    "scheduler",
)
SAFETY_SERVICES = COMPOSE_SERVICES[2:]
INGESTION_STREAM_PREFIX = "stream:ohlcv:ingestion:"
VOLATILE_CONSUMER_FIELDS = frozenset({"idle", "inactive"})


class N3BError(RuntimeError):
    """A bounded retirement failure with a handoff-facing status."""

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


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _compose_service_state(service: str) -> dict[str, Any]:
    ids = tuple(
        line.strip()
        for line in _run(
            "docker", "compose", "ps", "-a", "-q", service
        ).stdout.splitlines()
        if line.strip()
    )
    containers: list[dict[str, Any]] = []
    for container_id in ids:
        inspected = _run(
            "docker",
            "inspect",
            "-f",
            "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}",
            container_id,
        )
        if inspected.returncode != 0:
            continue
        state, health, exit_code, oom_killed = (
            inspected.stdout.strip().split("|", 3) + [""] * 4
        )[:4]
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


def _capture_service_states() -> dict[str, dict[str, Any]]:
    return {service: _compose_service_state(service) for service in COMPOSE_SERVICES}


def _fresh_manager() -> ConfigManager:
    ConfigManager.reset_singleton()
    return ConfigManager()


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(_json_value(value), sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _resolved_valkey_db(client: Any) -> object:
    """Return the logical DB selected by the instantiated Valkey pool."""
    pool = getattr(client, "connection_pool", None)
    kwargs = getattr(pool, "connection_kwargs", None)
    if not isinstance(kwargs, dict):
        return None
    return kwargs.get("db")


def _require_production_db0(client: Any) -> int:
    """Fail closed unless the supplied client is explicitly connected to DB0."""
    resolved_db = _resolved_valkey_db(client)
    if resolved_db != 0:
        raise N3BError(
            "BLOCKED_N3B_VALKEY_PROTECTION",
            "N3B retirement requires an explicitly resolved production Valkey DB0",
            evidence={"resolved_db": resolved_db, "required_db": 0},
        )
    return 0


def _ingestion_stream_key(venue: str, instrument_id: str, timeframe: str) -> str:
    return (
        "stream:ohlcv:ingestion:"
        f"{quote(venue.strip(), safe='')}:"
        f"{quote(instrument_id.strip(), safe='')}:"
        f"{quote(timeframe.strip(), safe='')}"
    )


def _expected_ingestion_state(ingestion_settings: Any) -> dict[str, list[str]]:
    """Derive protected ingestion manifests and OHLCV lanes from active settings."""
    manifest_keys: set[str] = set()
    stream_keys: set[str] = set()
    for asset_settings in ingestion_settings.assets.values():
        if not asset_settings.enabled:
            continue
        for instrument_id, instrument in asset_settings.instruments.items():
            manifest_keys.add(
                f"asset:{instrument.provider_symbols[instrument.live_provider]}"
            )
            stream_keys.update(
                _ingestion_stream_key(instrument.venue, instrument_id, timeframe)
                for timeframe in instrument.timeframes
            )
    return {
        "manifest_keys": sorted(manifest_keys),
        "stream_keys": sorted(stream_keys),
    }


async def _scan(client: Any, pattern: str) -> list[str]:
    return sorted([str(key) async for key in client.scan_iter(match=pattern)])


async def _stream_groups(client: Any, key: str) -> list[dict[str, Any]]:
    try:
        groups = await client.xinfo_groups(key)
    except ResponseError as exc:
        if "no such key" in str(exc).lower():
            return []
        raise
    result: list[dict[str, Any]] = []
    for group in groups:
        normalized = _json_value(group)
        group_name = str(normalized.get("name", ""))
        try:
            consumers = await client.xinfo_consumers(key, group_name)
        except ResponseError as exc:
            if "no such key" in str(exc).lower():
                consumers = []
            else:
                raise
        normalized_consumers = []
        for consumer in _json_value(consumers):
            if isinstance(consumer, dict):
                normalized_consumers.append(
                    {
                        field: value
                        for field, value in consumer.items()
                        if field not in VOLATILE_CONSUMER_FIELDS
                    }
                )
            else:
                normalized_consumers.append(consumer)
        normalized["consumers_detail"] = normalized_consumers
        result.append(normalized)
    return sorted(result, key=lambda item: str(item.get("name", "")))


async def _stream_snapshot(client: Any, key: str) -> dict[str, Any]:
    exists = bool(await client.exists(key))
    if not exists:
        return {"exists": False, "length": 0, "groups": []}
    return {
        "exists": True,
        "length": int(await client.xlen(key)),
        "groups": await _stream_groups(client, key),
    }


async def _asset_snapshot(client: Any) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for key in await _scan(client, "asset:*"):
        key_type = str(await client.type(key))
        if key_type == "hash":
            value = await client.hgetall(key)
        elif key_type == "stream":
            value = await _stream_snapshot(client, key)
        elif key_type == "set":
            value = sorted(_json_value(await client.smembers(key)))
        else:
            value = _json_value(await client.get(key))
        snapshot[key] = {
            "type": key_type,
            "value_hash": _stable_hash(value),
            "value": _json_value(value),
        }
    return snapshot


async def _ingestion_stream_snapshot(client: Any) -> dict[str, Any]:
    keys = await _scan(client, f"{INGESTION_STREAM_PREFIX}*")
    return {key: await _stream_snapshot(client, key) for key in keys}


def _consumer_name(
    prefix: str,
    asset: str,
    decision_timeframe: str,
    trigger_timeframe: str,
) -> str:
    if decision_timeframe == trigger_timeframe:
        return f"{prefix}_{asset}_{decision_timeframe}"
    return f"{prefix}_{asset}_{decision_timeframe}__{trigger_timeframe}"


async def _signal_group_snapshot(
    client: Any,
    settings: SignalWorkerSettings,
    pairs: list[Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for pair in pairs:
        trigger = pair.trigger_timeframe or pair.timeframe
        key = stream_key_for_binding(settings.source_binding(pair.asset), trigger)
        result[key] = {
            "pair": {
                "asset": pair.asset,
                "timeframe": pair.timeframe,
                "trigger_timeframe": trigger,
            },
            "expected_consumer": _consumer_name(
                settings.consumer_name_prefix,
                pair.asset,
                pair.timeframe,
                trigger,
            ),
            "groups": await _stream_groups(client, key),
        }
    return result


async def _legacy_inventory(client: Any) -> dict[str, Any]:
    _require_production_db0(client)
    keys: set[str] = set()
    for pattern in LEGACY_KEY_PATTERNS:
        keys.update(await _scan(client, pattern))
    for key in LEGACY_EXACT_KEYS:
        if await client.exists(key):
            keys.add(key)
    keys = {key for key in keys if not key.startswith(INGESTION_STREAM_PREFIX)}
    streams: dict[str, Any] = {}
    for key in sorted(keys):
        if str(await client.type(key)) == "stream":
            streams[key] = await _stream_snapshot(client, key)
    return {
        "keys": sorted(keys),
        "key_count": len(keys),
        "stream_count": len(streams),
        "streams": streams,
        "patterns": list(LEGACY_KEY_PATTERNS),
        "exact_keys": list(LEGACY_EXACT_KEYS),
    }


async def _valkey_snapshot(
    client: Any,
    signal_settings: SignalWorkerSettings,
    pairs: list[Any],
) -> dict[str, Any]:
    _require_production_db0(client)
    legacy = await _legacy_inventory(client)
    ingestion_streams = await _ingestion_stream_snapshot(client)
    assets = await _asset_snapshot(client)
    return {
        "legacy": legacy,
        "protected": {
            "asset_keys": assets,
            "ingestion_streams": ingestion_streams,
            "signal_groups": await _signal_group_snapshot(
                client, signal_settings, pairs
            ),
            "asset_lifecycle": await _stream_snapshot(client, "asset:lifecycle"),
        },
        "dbsize": int(await client.dbsize()),
    }


def _assert_protected_ingestion_state(
    snapshot: dict[str, Any],
    config: dict[str, Any],
) -> None:
    """Require the current production ingestion broker state before/after retirement."""
    protected = snapshot["protected"]
    assets = protected["asset_keys"]
    expected_manifests = set(config["expected_manifest_keys"])
    missing_manifests = sorted(expected_manifests - set(assets))
    invalid_manifests: dict[str, Any] = {}
    for key in sorted(expected_manifests & set(assets)):
        value = assets[key].get("value", {})
        if (
            assets[key].get("type") != "hash"
            or value.get("source") != "ingestion"
            or str(value.get("desired_state", "")).upper() != "LIVE"
            or str(value.get("enabled", "")).lower() != "true"
        ):
            invalid_manifests[key] = value
    if missing_manifests or invalid_manifests:
        raise N3BError(
            "BLOCKED_N3B_VALKEY_PROTECTION",
            "protected ingestion production manifests are missing or not LIVE-owned",
            evidence={
                "missing_manifests": missing_manifests,
                "invalid_manifests": invalid_manifests,
            },
        )

    lifecycle = protected["asset_lifecycle"]
    if not lifecycle.get("exists") or lifecycle.get("length", 0) <= 0:
        raise N3BError(
            "BLOCKED_N3B_VALKEY_PROTECTION",
            "protected asset:lifecycle stream is absent or empty",
            evidence={"asset_lifecycle": lifecycle},
        )

    expected_streams = set(config["expected_ingestion_stream_keys"])
    actual_streams = set(protected["ingestion_streams"])
    missing_streams = sorted(expected_streams - actual_streams)
    if missing_streams:
        raise N3BError(
            "BLOCKED_N3B_VALKEY_PROTECTION",
            "configured ingestion OHLCV streams are missing",
            evidence={"missing_streams": missing_streams},
        )

    invalid_groups: dict[str, Any] = {}
    for stream_key, details in protected["signal_groups"].items():
        groups = details.get("groups", [])
        matching = [
            group for group in groups if group.get("name") == "signal_app_group"
        ]
        expected_consumer = details["expected_consumer"]
        if len(matching) != 1:
            invalid_groups[stream_key] = {
                "reason": "signal_app_group missing or duplicated",
                "groups": groups,
            }
            continue
        group = matching[0]
        consumers = group.get("consumers_detail", [])
        if (
            int(group.get("pending", 0) or 0) != 0
            or int(group.get("lag", -1) if group.get("lag") is not None else -1) != 0
            or expected_consumer
            not in {
                str(item.get("name")) for item in consumers if isinstance(item, dict)
            }
        ):
            invalid_groups[stream_key] = {
                "expected_consumer": expected_consumer,
                "group": group,
            }
    if invalid_groups:
        raise N3BError(
            "BLOCKED_N3B_VALKEY_PROTECTION",
            "protected ingestion signal groups are missing, pending, lagging, or stale",
            evidence={"invalid_signal_groups": invalid_groups},
        )


def _assert_no_active_legacy_consumers(inventory: dict[str, Any]) -> None:
    active: dict[str, Any] = {}
    for key, stream in inventory["legacy"]["streams"].items():
        for group in stream["groups"]:
            pending = int(group.get("pending", 0) or 0)
            consumers = int(group.get("consumers", 0) or 0)
            if pending or consumers:
                active[key] = {
                    "group": group.get("name"),
                    "pending": pending,
                    "consumers": consumers,
                }
    if active:
        raise N3BError(
            "BLOCKED_N3B_LEGACY_CONSUMER_ACTIVE",
            "a legacy stream still has consumers or pending entries",
            evidence=active,
        )


async def _db_snapshot(pool: asyncpg.Pool) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    dependencies: dict[str, Any] = {}
    async with pool.acquire() as connection:
        for table in LEGACY_TABLES:
            relation = await connection.fetchval(
                "SELECT to_regclass($1)::text",
                table,
            )
            rows = None
            if relation is not None:
                rows = int(
                    await connection.fetchval(f"SELECT count(*)::bigint FROM {table}")
                )
            schema, name = table.split(".", 1)
            views = await connection.fetch(
                """
                SELECT view_schema AS table_schema, view_name AS table_name
                FROM information_schema.view_table_usage
                WHERE table_schema = $1 AND table_name = $2
                ORDER BY view_schema, view_name
                """,
                schema,
                name,
            )
            foreign_keys = await connection.fetch(
                """
                SELECT tc.table_schema, tc.table_name, tc.constraint_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.constraint_column_usage AS ccu
                  ON ccu.constraint_schema = tc.constraint_schema
                 AND ccu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND ccu.table_schema = $1
                  AND ccu.table_name = $2
                ORDER BY tc.table_schema, tc.table_name, tc.constraint_name
                """,
                schema,
                name,
            )
            tables[table] = {"relation": relation, "rows": rows}
            dependencies[table] = {
                "views": [_json_value(dict(row)) for row in views],
                "foreign_keys": [_json_value(dict(row)) for row in foreign_keys],
            }
        ingestion = await connection.fetchrow(
            """
            SELECT
              (SELECT count(*)::bigint FROM ingestion.candles) AS candles,
              (SELECT count(*)::bigint FROM ingestion.outbox) AS outbox,
              (SELECT count(*)::bigint FROM ingestion.outbox WHERE published_at IS NULL) AS pending
            """
        )
    return {
        "legacy_tables": tables,
        "dependencies": dependencies,
        "ingestion_protected": {
            key: int(ingestion[key]) for key in ("candles", "outbox", "pending")
        },
    }


def _assert_db_preconditions(snapshot: dict[str, Any]) -> None:
    invalid = {
        table: details
        for table, details in snapshot["legacy_tables"].items()
        if details["relation"] is None or details["rows"] != 0
    }
    if invalid:
        raise N3BError(
            "BLOCKED_N3B_DATABASE_NOT_EMPTY",
            "legacy retirement tables are absent or non-empty",
            evidence=invalid,
        )
    dependencies = {
        table: details
        for table, details in snapshot["dependencies"].items()
        if details["views"] or details["foreign_keys"]
    }
    if dependencies:
        raise N3BError(
            "BLOCKED_N3B_DATABASE_DEPENDENCY",
            "legacy retirement tables have dependent views or foreign keys",
            evidence=dependencies,
        )
    if snapshot["ingestion_protected"]["pending"] != 0:
        raise N3BError(
            "BLOCKED_N3B_DATABASE_PROTECTION",
            "ingestion pending outbox is not zero before retirement",
            evidence=snapshot["ingestion_protected"],
        )


def _config_snapshot(
    manager: ConfigManager,
) -> tuple[dict[str, Any], SignalWorkerSettings, list[Any]]:
    try:
        ingestion_settings = load_ingestion_settings(manager)
        signal_settings = SignalWorkerSettings.from_config(manager)
        pairs = build_signal_pairs(manager)
    except Exception as exc:
        raise N3BError(
            "BLOCKED_N3B_CONFIG_AUTHORITY",
            "active ingestion or signal configuration could not be resolved",
            evidence={"error": repr(exc)},
        ) from exc

    enabled = sorted(
        asset.asset for asset in ingestion_settings.assets.values() if asset.enabled
    )
    owners = sorted(
        asset.asset
        for asset in ingestion_settings.assets.values()
        if asset.owns_manifest_lifecycle
    )
    actual_pairs = sorted((pair.asset, pair.timeframe) for pair in pairs)
    if enabled != sorted(ALL_ASSETS) or owners != sorted(ALL_ASSETS):
        raise N3BError(
            "ENVIRONMENT_PRECONDITION_CHANGED",
            "six-asset ingestion enablement/ownership is not active",
            evidence={"enabled_assets": enabled, "owned_assets": owners},
        )
    if set(actual_pairs) != EXPECTED_SIGNAL_PAIRS or len(actual_pairs) != 8:
        raise N3BError(
            "ENVIRONMENT_PRECONDITION_CHANGED",
            "configured signal graph is not the certified eight-pair graph",
            evidence={"actual_pairs": actual_pairs},
        )
    expected_ingestion_state = _expected_ingestion_state(ingestion_settings)
    bindings = {}
    for symbol in ALL_SYMBOLS:
        binding = signal_settings.source_binding(symbol)
        if (
            binding.source != "ingestion"
            or not binding.venue
            or not binding.instrument_id
        ):
            raise N3BError(
                "BLOCKED_N3B_SIGNAL_LEGACY_FALLBACK",
                f"invalid ingestion source binding for {symbol}",
            )
        bindings[symbol] = {
            "source": binding.source,
            "venue": binding.venue,
            "instrument_id": binding.instrument_id,
        }
    return (
        {
            "enabled_assets": enabled,
            "manifest_owners": owners,
            "expected_manifest_keys": expected_ingestion_state["manifest_keys"],
            "expected_ingestion_stream_keys": expected_ingestion_state["stream_keys"],
            "source_bindings": bindings,
            "signal_pairs": actual_pairs,
        },
        signal_settings,
        pairs,
    )


async def _drop_tables(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as connection:
        try:
            async with connection.transaction():
                for table in LEGACY_TABLES:
                    await connection.execute(f"DROP TABLE {table}")
        except Exception as exc:
            raise N3BError(
                "BLOCKED_N3B_DATABASE_DEPENDENCY",
                "ordinary legacy table drop failed; no CASCADE was attempted",
                evidence={"tables": LEGACY_TABLES, "error": repr(exc)},
            ) from exc


async def _delete_legacy_keys(client: Any, keys: list[str]) -> int:
    _require_production_db0(client)
    deleted = 0
    for start in range(0, len(keys), 500):
        batch = keys[start : start + 500]
        if batch:
            deleted += int(await client.delete(*batch))
    return deleted


async def _assert_deleted_keys(client: Any, keys: list[str]) -> None:
    remaining = [key for key in keys if await client.exists(key)]
    if remaining:
        raise N3BError(
            "BLOCKED_N3B_VALKEY_PROTECTION",
            "one or more retired Valkey keys remain after deletion",
            evidence={"remaining": remaining},
        )


async def _assert_db_dropped(pool: asyncpg.Pool) -> dict[str, Any]:
    async with pool.acquire() as connection:
        relations = {
            table: await connection.fetchval("SELECT to_regclass($1)::text", table)
            for table in LEGACY_TABLES
        }
    if any(value is not None for value in relations.values()):
        raise N3BError(
            "BLOCKED_N3B_DATABASE_PROTECTION",
            "a legacy retirement relation still exists",
            evidence=relations,
        )
    return relations


async def _run_retirement(execute: bool) -> dict[str, Any]:
    manager = _fresh_manager()
    pool: asyncpg.Pool | None = None
    client: Any | None = None
    try:
        config, signal_settings, pairs = _config_snapshot(manager)
        states = _capture_service_states()
        active = {
            service: state
            for service, state in states.items()
            if service in SAFETY_SERVICES and state["running"]
        }
        if active:
            raise N3BError(
                "ENVIRONMENT_PRECONDITION_CHANGED",
                "all application services must be stopped before legacy retirement",
                evidence=active,
            )
        if not states["db"]["running"] or not states["db"]["healthy"]:
            raise N3BError(
                "ENVIRONMENT_PRECONDITION_CHANGED",
                "Timescale must be running and healthy",
                evidence={"db": states["db"]},
            )

        await init_db_pools(manager)
        pool = DBPoolManager.get_writer_pool()
        client_uri = (
            os.getenv("N3B_VALKEY_URI")
            or os.getenv("VALKEY_URI")
            or os.getenv("REDIS_URI")
            or str(manager.get("valkey.uri", "redis://localhost:6379/0"))
        )
        client = valkey.Valkey.from_url(client_uri, decode_responses=True)
        resolved_db = _require_production_db0(client)
        await client.ping()

        db_before = await _db_snapshot(pool)
        _assert_db_preconditions(db_before)
        valkey_before = await _valkey_snapshot(client, signal_settings, pairs)
        _assert_no_active_legacy_consumers(valkey_before)
        if any(
            key.startswith(INGESTION_STREAM_PREFIX)
            for key in valkey_before["legacy"]["keys"]
        ):
            raise N3BError(
                "BLOCKED_N3B_VALKEY_PROTECTION",
                "legacy deletion inventory included a protected ingestion stream",
                evidence={"keys": valkey_before["legacy"]["keys"]},
            )
        _assert_protected_ingestion_state(valkey_before, config)

        result: dict[str, Any] = {
            "status": "DRY_RUN" if not execute else "READY_FOR_REVIEW",
            "starting_sha": _run("git", "rev-parse", "HEAD").stdout.strip(),
            "config": config,
            "services": states,
            "database_before": db_before,
            "valkey_before": valkey_before,
            "execute": execute,
            "resolved_db": resolved_db,
            "production_db0_flush_issued": False,
            "valkey_flush_commands_issued": False,
        }
        if not execute:
            return result

        await _drop_tables(pool)
        deleted = await _delete_legacy_keys(client, valkey_before["legacy"]["keys"])
        await _assert_deleted_keys(client, valkey_before["legacy"]["keys"])
        db_after = await _assert_db_dropped(pool)
        valkey_after = await _valkey_snapshot(client, signal_settings, pairs)
        _assert_protected_ingestion_state(valkey_after, config)
        if valkey_after["protected"] != valkey_before["protected"]:
            raise N3BError(
                "BLOCKED_N3B_VALKEY_PROTECTION",
                "protected ingestion Valkey state changed during legacy cleanup",
                evidence={
                    "before": valkey_before["protected"],
                    "after": valkey_after["protected"],
                },
            )
        db_protected_after = await _db_snapshot(pool)
        if (
            db_protected_after["ingestion_protected"]
            != db_before["ingestion_protected"]
        ):
            raise N3BError(
                "BLOCKED_N3B_DATABASE_PROTECTION",
                "protected ingestion database counts changed during legacy cleanup",
                evidence={
                    "before": db_before["ingestion_protected"],
                    "after": db_protected_after["ingestion_protected"],
                },
            )
        result.update(
            {
                "legacy_valkey_deleted": deleted,
                "database_after": db_after,
                "database_protected_after": db_protected_after["ingestion_protected"],
                "valkey_after": valkey_after,
            }
        )
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        EXECUTE_STATE_ARTIFACT.write_text(
            json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        return result
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                await client.aclose()
        await DBPoolManager.close_pools()
        with contextlib.suppress(Exception):
            manager.shutdown()
        ConfigManager.reset_singleton()


async def _verify_completed_retirement() -> dict[str, Any]:
    """Verify a previously completed destructive run without mutating state."""
    manager = _fresh_manager()
    pool: asyncpg.Pool | None = None
    client: Any | None = None
    try:
        config, signal_settings, pairs = _config_snapshot(manager)
        states = _capture_service_states()
        active = {
            service: state
            for service, state in states.items()
            if service in SAFETY_SERVICES and state["running"]
        }
        if active:
            raise N3BError(
                "ENVIRONMENT_PRECONDITION_CHANGED",
                "all application services must be stopped during retirement verification",
                evidence=active,
            )
        if not states["db"]["running"] or not states["db"]["healthy"]:
            raise N3BError(
                "ENVIRONMENT_PRECONDITION_CHANGED",
                "Timescale must be running and healthy",
                evidence={"db": states["db"]},
            )

        await init_db_pools(manager)
        pool = DBPoolManager.get_writer_pool()
        client_uri = (
            os.getenv("N3B_VALKEY_URI")
            or os.getenv("VALKEY_URI")
            or os.getenv("REDIS_URI")
            or str(manager.get("valkey.uri", "redis://localhost:6379/0"))
        )
        client = valkey.Valkey.from_url(client_uri, decode_responses=True)
        resolved_db = _require_production_db0(client)
        await client.ping()

        database = await _db_snapshot(pool)
        remaining_relations = {
            table: details["relation"]
            for table, details in database["legacy_tables"].items()
            if details["relation"] is not None
        }
        if remaining_relations:
            raise N3BError(
                "BLOCKED_N3B_DATABASE_PROTECTION",
                "a legacy retirement relation remains during verification",
                evidence=remaining_relations,
            )

        valkey_state = await _valkey_snapshot(client, signal_settings, pairs)
        if valkey_state["legacy"]["keys"]:
            raise N3BError(
                "BLOCKED_N3B_VALKEY_PROTECTION",
                "retired legacy Valkey keys remain during verification",
                evidence={"keys": valkey_state["legacy"]["keys"]},
            )
        _assert_protected_ingestion_state(valkey_state, config)
        if database["ingestion_protected"]["pending"] != 0:
            raise N3BError(
                "BLOCKED_N3B_DATABASE_PROTECTION",
                "ingestion pending outbox is non-zero during verification",
                evidence=database["ingestion_protected"],
            )

        result = {
            "status": "READY_FOR_REVIEW",
            "verification_only": True,
            "starting_sha": _run("git", "rev-parse", "HEAD").stdout.strip(),
            "config": config,
            "resolved_db": resolved_db,
            "services": states,
            "database_after": database,
            "valkey_after": valkey_state,
            "production_db0_flush_issued": False,
            "valkey_flush_commands_issued": False,
        }
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        VERIFY_STATE_ARTIFACT.write_text(
            json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        return result
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                await client.aclose()
        await DBPoolManager.close_pools()
        with contextlib.suppress(Exception):
            manager.shutdown()
        ConfigManager.reset_singleton()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        if args.execute and os.getenv("INGESTION_RUN_N3B_RETIREMENT") != "1":
            raise N3BError(
                "ENVIRONMENT_PRECONDITION_CHANGED",
                "set INGESTION_RUN_N3B_RETIREMENT=1 for N3B execution",
            )
        result = asyncio.run(
            _verify_completed_retirement()
            if args.verify
            else _run_retirement(args.execute)
        )
    except N3BError as exc:
        print(
            json.dumps(
                {"status": exc.status, "message": str(exc), "evidence": exc.evidence},
                indent=2,
                default=str,
            )
        )
        return 1
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
