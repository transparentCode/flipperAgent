"""Certify the normal containerized ingestion BTC operating path.

The command is intentionally dry-run by default.  ``--execute`` is required
to start or restart Compose services.  It only operates on the named services
used by this certification; it has no database deletion, Valkey flush, stream
reset, or rollback option.
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
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import asyncpg
import yaml
from valkey.exceptions import ResponseError

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from apps.signal_app.models import SignalPair, SignalPairState
from apps.signal_app.observability.runtime_state import SignalRuntimeStateStore
from apps.signal_app.ohlcv_source import stream_key_for_binding
from apps.signal_app.settings import SignalWorkerSettings
from libs.common.asset_manifest import AssetManifestStore
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.timeframes import timeframe_to_seconds

INGESTION_BASE_URL = "http://127.0.0.1:8003"
BTC_VENUE = "binance"
BTC_INSTRUMENT_ID = "BTC-USDT-PERP"
BTC_ASSET = "BTCUSDT"
BTC_TIMEFRAMES = ("1h", "4h")
BASE_TIMEFRAME = "1m"
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
SAFETY_SERVICES = (
    "signal-worker",
    "strategy-worker",
    "risk-worker",
    "execution-worker",
    "portfolio-worker",
)
OPERATION_TIMEOUT = 300.0
LIVE_CANDLE_TIMEOUT = 240.0
SIGNAL_STOP_HARD_BOUNDARY_SECONDS = 10.0


class N1COperationError(RuntimeError):
    """An operational certification failure with its required status."""

    def __init__(
        self, status: str, message: str, *, evidence: dict[str, Any] | None = None
    ) -> None:
        self.status = status
        self.evidence = evidence or {}
        super().__init__(message)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(args),
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise N1COperationError(
            "BLOCKED_N1C_COMPOSE",
            f"command failed ({completed.returncode}): {' '.join(args)}\n"
            f"stdout={completed.stdout[-2000:]}\nstderr={completed.stderr[-2000:]}",
        )
    return completed


def _compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run("docker", "compose", *args, check=check)


def _compose_container_ids(service: str) -> tuple[str, ...]:
    output = _compose("ps", "-a", "-q", service, check=False).stdout
    return tuple(line.strip() for line in output.splitlines() if line.strip())


def _service_state(service: str) -> dict[str, Any]:
    containers: list[dict[str, str]] = []
    for container_id in _compose_container_ids(service):
        inspected = _run(
            "docker",
            "inspect",
            "-f",
            "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}",
            container_id,
        ).stdout.strip()
        state, _, remainder = inspected.partition("|")
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


def _capture_service_states() -> dict[str, dict[str, Any]]:
    return {service: _service_state(service) for service in COMPOSE_SERVICES}


def _compose_config() -> dict[str, Any]:
    json_result = _compose("config", "--format", "json", check=False)
    if json_result.returncode == 0:
        try:
            return json.loads(json_result.stdout)
        except json.JSONDecodeError as exc:
            raise N1COperationError(
                "BLOCKED_N1C_COMPOSE",
                f"docker compose config returned invalid JSON: {exc}",
            ) from exc

    yaml_result = _compose("config")
    try:
        return yaml.safe_load(yaml_result.stdout) or {}
    except yaml.YAMLError as exc:
        raise N1COperationError(
            "BLOCKED_N1C_COMPOSE",
            f"docker compose config returned invalid YAML: {exc}",
        ) from exc


def validate_compose_contract() -> dict[str, Any]:
    """Validate only the N1C service contract; do not start services."""
    config = _compose_config()
    services = config.get("services", {})
    service = services.get("ingestion")
    if not isinstance(service, dict):
        raise N1COperationError("BLOCKED_N1C_COMPOSE", "ingestion service is absent")

    command = str(service.get("command", ""))
    ports = service.get("ports", [])
    depends_on = service.get("depends_on", {})
    db_dependency = depends_on.get("db") if isinstance(depends_on, dict) else None
    healthcheck = service.get("healthcheck")
    if "apps.ingestion_app.main" not in command:
        raise N1COperationError(
            "BLOCKED_N1C_COMPOSE", f"unexpected ingestion command: {command}"
        )
    has_expected_port = any(
        isinstance(port, dict)
        and port.get("host_ip") == "127.0.0.1"
        and str(port.get("published")) == "8003"
        and str(port.get("target")) == "8003"
        for port in ports
    ) or "127.0.0.1:8003:8003" in json.dumps(ports, sort_keys=True)
    if not has_expected_port:
        raise N1COperationError(
            "BLOCKED_N1C_COMPOSE", f"unexpected ingestion port: {ports}"
        )
    if (
        not isinstance(db_dependency, dict)
        or db_dependency.get("condition") != "service_healthy"
    ):
        raise N1COperationError(
            "BLOCKED_N1C_COMPOSE", "ingestion lacks the DB health dependency"
        )
    if isinstance(depends_on, dict) and "broker" in depends_on:
        raise N1COperationError(
            "BLOCKED_N1C_COMPOSE", "broker is a hard ingestion dependency"
        )
    if not isinstance(healthcheck, dict) or not healthcheck.get("test"):
        raise N1COperationError(
            "BLOCKED_N1C_COMPOSE", "ingestion healthcheck is absent"
        )

    return {
        "services": sorted(services),
        "ingestion": {
            "command": command,
            "ports": service.get("ports", []),
            "depends_on": depends_on,
            "healthcheck": healthcheck,
            "broker_hard_dependency": False,
        },
    }


def _require_preconditions(states: dict[str, dict[str, Any]]) -> None:
    db_state = _service_state("db")
    if not db_state["running"] or not db_state["healthy"]:
        raise N1COperationError(
            "ENVIRONMENT_PRECONDITION_CHANGED",
            f"Timescale must be running and healthy: {db_state}",
        )
    active = {
        service: states[service]
        for service in SAFETY_SERVICES
        if states[service]["running"]
    }
    if active:
        raise N1COperationError(
            "ENVIRONMENT_PRECONDITION_CHANGED",
            f"safety services must be stopped: {active}",
        )


def _compose_action(action: str, *services: str, build: bool = False) -> None:
    if action == "up":
        args = ["up", "-d"]
        if build:
            args.append("--build")
        args.extend(services)
    elif action in {"start", "stop", "restart"}:
        args = [action, *services]
    else:  # pragma: no cover - private caller guard
        raise ValueError(action)
    _compose(*args)


def _wait_sync(predicate: Any, *, timeout: float, description: str) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(1)
    raise N1COperationError(
        "BLOCKED_N1C_HEALTH",
        f"timed out waiting for {description}: {last}",
    )


def _http(path: str, *, method: str = "GET") -> tuple[int, dict[str, Any] | str]:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(f"{INGESTION_BASE_URL}{path}", method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8")
            try:
                return response.status, json.loads(body)
            except json.JSONDecodeError:
                return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body
    except (OSError, urllib.error.URLError):
        return 0, "unreachable"


def _ingestion_runtime() -> dict[str, Any] | None:
    status, payload = _http("/runtime")
    return payload if status == 200 and isinstance(payload, dict) else None


def _wait_ingestion_live(*, timeout: float = OPERATION_TIMEOUT) -> dict[str, Any]:
    def ready() -> dict[str, Any] | None:
        service = _service_state("ingestion")
        runtime = _ingestion_runtime()
        live_status, _ = _http("/health/live")
        ready_status, _ = _http("/health/ready")
        if (
            service["running"]
            and service["healthy"]
            and live_status == 200
            and ready_status == 200
            and runtime is not None
            and runtime.get("state") == "live"
        ):
            return {
                "service": service,
                "runtime": runtime,
                "live_status": live_status,
                "ready_status": ready_status,
            }
        return None

    try:
        return _wait_sync(ready, timeout=timeout, description="ingestion LIVE/ready")
    except N1COperationError as exc:
        exc.status = "BLOCKED_N1C_CONTAINER_RUNTIME"
        raise


def _database_dsn() -> str:
    return os.getenv(
        "POSTGRES_URI",
        "postgresql://flipper:flipperpass@localhost:5432/flipper_db",
    )


async def _btc_state(connection: asyncpg.Connection) -> dict[str, Any]:
    rows = await connection.fetch(
        """
        SELECT timeframe, count(*) AS row_count, min(open_time) AS first_open,
               max(open_time) AS last_open, max(close_time) AS last_close
        FROM ingestion.candles
        WHERE venue = $1 AND instrument_id = $2
        GROUP BY timeframe
        ORDER BY timeframe
        """,
        BTC_VENUE,
        BTC_INSTRUMENT_ID,
    )
    outbox = await connection.fetchrow(
        """
        SELECT count(*) AS total,
               count(*) FILTER (WHERE published_at IS NULL) AS pending,
               count(*) FILTER (WHERE published_at IS NOT NULL) AS published
        FROM ingestion.outbox
        WHERE payload->>'instrument_id' = $1
        """,
        BTC_INSTRUMENT_ID,
    )
    return {
        "candles": {
            row["timeframe"]: {
                "rows": int(row["row_count"]),
                "first_open": _iso(row["first_open"]),
                "last_open": _iso(row["last_open"]),
                "last_close": _iso(row["last_close"]),
            }
            for row in rows
        },
        "outbox": {
            "total": int(outbox["total"]),
            "pending": int(outbox["pending"]),
            "published": int(outbox["published"]),
        },
    }


async def _latest_base_open(connection: asyncpg.Connection) -> datetime | None:
    return await connection.fetchval(
        """
        SELECT max(open_time)
        FROM ingestion.candles
        WHERE venue = $1 AND instrument_id = $2 AND timeframe = $3
        """,
        BTC_VENUE,
        BTC_INSTRUMENT_ID,
        BASE_TIMEFRAME,
    )


async def _new_base_rows(
    connection: asyncpg.Connection,
    *,
    after: datetime,
    limit: int = 8,
) -> list[dict[str, Any]]:
    rows = await connection.fetch(
        """
        SELECT open_time, close_time, source_type, source_provider,
               source_timeframe, volume, taker_buy_base
        FROM ingestion.candles
        WHERE venue = $1 AND instrument_id = $2 AND timeframe = $3
          AND open_time > $4
        ORDER BY open_time
        LIMIT $5
        """,
        BTC_VENUE,
        BTC_INSTRUMENT_ID,
        BASE_TIMEFRAME,
        after,
        limit,
    )
    return [
        {
            "open_time": row["open_time"],
            "close_time": row["close_time"],
            "source_type": row["source_type"],
            "source_provider": row["source_provider"],
            "source_timeframe": row["source_timeframe"],
            "volume": str(row["volume"]),
            "taker_buy_base": str(row["taker_buy_base"])
            if row["taker_buy_base"] is not None
            else None,
        }
        for row in rows
    ]


def _validate_base_rows(rows: list[dict[str, Any]]) -> None:
    interval = timedelta(seconds=timeframe_to_seconds(BASE_TIMEFRAME))
    for previous, current in pairwise(rows):
        if current["open_time"] != previous["open_time"] + interval:
            raise N1COperationError(
                "BLOCKED_N1C_CANONICAL_CONTINUITY",
                f"BTC base gap after {_iso(previous['open_time'])}",
            )
    for row in rows:
        if (
            row["close_time"] != row["open_time"] + interval
            or row["source_type"] != "provider"
            or row["source_provider"] != "binance_native"
            or row["source_timeframe"] is not None
            or row["taker_buy_base"] is None
        ):
            raise N1COperationError(
                "BLOCKED_N1C_CANONICAL_CONTINUITY",
                f"invalid BTC base provenance/geometry at {_iso(row['open_time'])}",
            )


async def _wait_for_new_base_rows(
    connection: asyncpg.Connection,
    *,
    after: datetime,
    count: int,
    timeout: float,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = await _new_base_rows(connection, after=after)
        if len(rows) >= count:
            selected = rows[:count]
            _validate_base_rows(selected)
            return selected
        await asyncio.sleep(2)
    raise N1COperationError(
        "BLOCKED_N1C_CANONICAL_CONTINUITY",
        f"timed out waiting for {count} new BTC base candles after {_iso(after)}",
    )


async def _wait_pending_zero(
    connection: asyncpg.Connection,
    *,
    timeout: float,
) -> dict[str, int]:
    deadline = time.monotonic() + timeout
    last: dict[str, int] = {}
    while time.monotonic() < deadline:
        row = await connection.fetchrow(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE published_at IS NULL) AS pending,
                   count(*) FILTER (WHERE published_at IS NOT NULL) AS published
            FROM ingestion.outbox
            WHERE payload->>'instrument_id' = $1
            """,
            BTC_INSTRUMENT_ID,
        )
        last = {key: int(row[key]) for key in ("total", "pending", "published")}
        if last["pending"] == 0:
            return last
        await asyncio.sleep(2)
    raise N1COperationError(
        "BLOCKED_N1C_PUBLICATION",
        f"BTC pending outbox did not drain: {last}",
    )


def _decode_value(value: Any) -> Any:
    return value.decode("utf-8") if isinstance(value, bytes) else value


async def _group_snapshot(
    client: Any,
    *,
    stream_key: str,
    group_name: str,
    expected_consumer: str,
    consumer_idle_limit_ms: int,
) -> dict[str, Any]:
    groups = await client.xinfo_groups(stream_key)
    for raw_group in groups:
        group = {
            _decode_value(key): _decode_value(value) for key, value in raw_group.items()
        }
        if group.get("name") == group_name:
            raw_consumers = await client.xinfo_consumers(stream_key, group_name)
            consumers = [
                {
                    _decode_value(key): _decode_value(value)
                    for key, value in raw_consumer.items()
                }
                for raw_consumer in raw_consumers
            ]
            consumer = next(
                (item for item in consumers if item.get("name") == expected_consumer),
                None,
            )
            consumer_idle_ms = int(consumer["idle"]) if consumer is not None else None
            return {
                "stream_key": stream_key,
                "group": group_name,
                "consumers": int(group.get("consumers") or 0),
                "pending": int(group.get("pending") or 0),
                "last_delivered_id": str(group.get("last-delivered-id")),
                "entries_read": group.get("entries-read"),
                "lag": group.get("lag"),
                "expected_consumer": expected_consumer,
                "consumer": consumer,
                "consumer_idle_ms": consumer_idle_ms,
                "consumer_idle_limit_ms": consumer_idle_limit_ms,
                "consumer_fresh": (
                    consumer_idle_ms is not None
                    and consumer_idle_ms <= consumer_idle_limit_ms
                ),
            }
    raise N1COperationError(
        "BLOCKED_N1C_SIGNAL_STARTUP",
        f"consumer group {group_name} absent on {stream_key}",
    )


async def _signal_snapshot(
    client: Any,
    *,
    settings: SignalWorkerSettings,
) -> dict[str, Any]:
    binding = settings.source_binding(BTC_ASSET)
    state_store = SignalRuntimeStateStore(client)
    statuses: dict[str, dict[str, Any] | None] = {}
    groups: dict[str, dict[str, Any]] = {}
    consumer_idle_limit_ms = max(settings.block_ms * 5, 5_000)
    for timeframe in BTC_TIMEFRAMES:
        pair = SignalPair(asset=BTC_ASSET, timeframe=timeframe)
        status = await state_store.read(pair)
        statuses[timeframe] = status.model_dump(mode="json") if status else None
        stream_key = stream_key_for_binding(binding, timeframe)
        expected_consumer = f"{settings.consumer_name_prefix}_{BTC_ASSET}_{timeframe}"
        try:
            groups[timeframe] = await _group_snapshot(
                client,
                stream_key=stream_key,
                group_name=settings.consumer_group,
                expected_consumer=expected_consumer,
                consumer_idle_limit_ms=consumer_idle_limit_ms,
            )
        except (N1COperationError, ResponseError) as exc:
            groups[timeframe] = {"stream_key": stream_key, "error": str(exc)}
    manifests = await AssetManifestStore(client).list_assets()
    return {
        "statuses": statuses,
        "groups": groups,
        "manifest_symbols": [manifest.symbol for manifest in manifests],
        "manifest_btc_present": any(
            manifest.symbol == BTC_ASSET for manifest in manifests
        ),
        "binding": {
            "source": binding.source,
            "venue": binding.venue,
            "instrument_id": binding.instrument_id,
        },
    }


async def _wait_signal_live(
    client: Any,
    *,
    settings: SignalWorkerSettings,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = await _signal_snapshot(client, settings=settings)
        statuses = last["statuses"]
        groups = last["groups"]
        if all(
            isinstance(statuses[timeframe], dict)
            and statuses[timeframe].get("state") == SignalPairState.LIVE.value
            for timeframe in BTC_TIMEFRAMES
        ) and all(
            isinstance(groups[timeframe], dict)
            and "error" not in groups[timeframe]
            and groups[timeframe].get("consumers", 0) >= 1
            and groups[timeframe].get("pending", 0) == 0
            and groups[timeframe].get("lag") == 0
            and groups[timeframe].get("consumer_fresh") is True
            for timeframe in BTC_TIMEFRAMES
        ):
            return last
        await asyncio.sleep(2)
    raise N1COperationError(
        "BLOCKED_N1C_SIGNAL_STARTUP",
        f"BTC signal workers did not reach LIVE with fresh consumers and empty groups: {last}",
    )


def _stop_service_with_evidence(service: str) -> dict[str, Any]:
    started = time.monotonic()
    _compose_action("stop", service)
    elapsed = time.monotonic() - started
    state = _service_state(service)
    containers = state["containers"]
    exit_codes = [
        int(container["exit_code"])
        for container in containers
        if container["exit_code"] != ""
    ]
    oom_killed = any(container["oom_killed"] for container in containers)
    evidence = {
        "service": state,
        "elapsed_seconds": elapsed,
        "hard_boundary_seconds": SIGNAL_STOP_HARD_BOUNDARY_SECONDS,
        "exit_codes": exit_codes,
        "oom_killed": oom_killed,
    }
    if (
        state["running"]
        or not containers
        or any(exit_code != 0 for exit_code in exit_codes)
        or oom_killed
        or elapsed >= SIGNAL_STOP_HARD_BOUNDARY_SECONDS
    ):
        raise N1COperationError(
            "BLOCKED_N1C_SIGNAL_SHUTDOWN",
            f"{service} did not stop cleanly within the Compose boundary: {evidence}",
            evidence=evidence,
        )
    return evidence


def _group_cursor_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    fields = ("last_delivered_id", "entries_read", "pending")
    return any(before.get(field) != after.get(field) for field in fields)


async def _stream_latest_id(client: Any, key: str) -> str | None:
    rows = await client.xrevrange(key, count=1)
    if not rows:
        return None
    return str(_decode_value(rows[0][0]))


async def _stream_contains_open_time(
    client: Any,
    *,
    key: str,
    open_time: datetime,
) -> bool:
    expected = _iso(open_time)
    rows = await client.xrange(key)
    for _, fields in rows:
        normalized = {_decode_value(k): _decode_value(v) for k, v in fields.items()}
        payload = normalized.get("payload")
        if not payload:
            continue
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if decoded.get("open_time") == expected:
            return True
    return False


async def _run_execute() -> dict[str, Any]:
    compose_report = validate_compose_contract()
    initial_states = _capture_service_states()
    _require_preconditions(initial_states)
    dsn = _database_dsn()
    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=2)
    manager: ConfigManager | None = None
    client: Any | None = None
    report: dict[str, Any] = {
        "status": "READY_FOR_REVIEW",
        "compose": compose_report,
        "initial_states": initial_states,
        "BTC_LEGACY_MANIFEST_DEPENDENCY_TEMPORARY": True,
        "AUTOMATIC_PUBLISHED_OUTBOX_REPLAY": "ABSENT",
        "N1_PUBLISHED_OUTBOX_CLEANUP": "DISABLED",
        "BTC_N1_AUTOMATIC_ROLLBACK_TO_LEGACY": False,
    }
    try:
        async with pool.acquire() as connection:
            report["initial_database"] = await _btc_state(connection)

        _compose_action("up", "broker")
        _wait_sync(
            lambda: _service_state("broker")["healthy"],
            timeout=OPERATION_TIMEOUT,
            description="Valkey health",
        )
        _compose_action("up", "ingestion", build=True)
        report["container_start"] = _wait_ingestion_live()

        async with pool.acquire() as connection:
            baseline_open = await _latest_base_open(connection)
            if baseline_open is None:
                raise N1COperationError(
                    "BLOCKED_N1C_CONTAINER_RUNTIME",
                    "BTC base history is empty after ingestion startup",
                )
            new_rows = await _wait_for_new_base_rows(
                connection,
                after=baseline_open,
                count=2,
                timeout=LIVE_CANDLE_TIMEOUT,
            )
            report["containerized_base_progression"] = {
                "baseline_open": _iso(baseline_open),
                "rows": [
                    {
                        "open": _iso(row["open_time"]),
                        "close": _iso(row["close_time"]),
                        "source_type": row["source_type"],
                        "source_provider": row["source_provider"],
                        "taker_buy_base": row["taker_buy_base"],
                    }
                    for row in new_rows
                ],
            }
            report["publication_after_start"] = await _wait_pending_zero(
                connection,
                timeout=OPERATION_TIMEOUT,
            )

        manager = ConfigManager()
        signal_settings = SignalWorkerSettings.from_config(manager)
        binding = signal_settings.source_binding(BTC_ASSET)
        if binding.source != "ingestion":
            raise N1COperationError(
                "BLOCKED_N1C_SOURCE_BINDING",
                f"BTC source is not ingestion: {binding}",
            )
        non_btc = {
            asset: signal_settings.source_binding(asset).source
            for asset in ("ETHUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT")
        }
        # N1C was originally certified during the BTC-only cutover.  FINAL
        # reuses this operational gate after N2B2, where all six production
        # bindings are intentionally ingestion-owned.
        if any(source != "ingestion" for source in non_btc.values()):
            raise N1COperationError(
                "BLOCKED_N1C_SOURCE_BINDING",
                f"non-BTC source binding is not ingestion: {non_btc}",
            )

        _compose_action("up", "signal-worker", build=True)
        client = await create_valkey_client(manager)
        report["signal_start"] = await _wait_signal_live(
            client,
            settings=signal_settings,
            timeout=OPERATION_TIMEOUT,
        )
        report["non_btc_sources"] = non_btc

        report["signal_graceful_shutdown"] = _stop_service_with_evidence(
            "signal-worker"
        )
        _compose_action("up", "signal-worker")
        report["signal_after_graceful_restart"] = await _wait_signal_live(
            client,
            settings=signal_settings,
            timeout=OPERATION_TIMEOUT,
        )

        before_pause = await _signal_snapshot(client, settings=signal_settings)
        status, pause_payload = _http("/runtime/pause", method="POST")
        if status != 200:
            raise N1COperationError(
                "BLOCKED_N1C_SIGNAL_RESTART_REPLAY",
                f"runtime pause failed: {status} {pause_payload}",
            )
        report["pause"] = pause_payload
        _wait_sync(
            lambda: (_ingestion_runtime() or {}).get("desired_state") == "paused",
            timeout=30,
            description="ingestion pause",
        )
        before_restart_groups = before_pause["groups"]
        _compose_action("restart", "signal-worker")
        _wait_sync(
            lambda: _service_state("signal-worker")["running"],
            timeout=OPERATION_TIMEOUT,
            description="signal-worker restart",
        )
        after_restart = await _wait_signal_live(
            client,
            settings=signal_settings,
            timeout=OPERATION_TIMEOUT,
        )
        for timeframe in BTC_TIMEFRAMES:
            before_group = before_restart_groups[timeframe]
            after_group = after_restart["groups"][timeframe]
            if _group_cursor_changed(before_group, after_group):
                raise N1COperationError(
                    "BLOCKED_N1C_SIGNAL_RESTART_REPLAY",
                    f"{timeframe} group cursor changed during paused signal restart",
                    evidence={"before": before_group, "after": after_group},
                )
        report["signal_restart"] = {
            "before": before_pause,
            "after": after_restart,
            "bootstrap_classification": "bootstrap snapshots are not OHLCV replay",
        }

        status, resume_payload = _http("/runtime/resume", method="POST")
        if status != 200:
            raise N1COperationError(
                "BLOCKED_N1C_CONTAINER_RUNTIME",
                f"runtime resume failed: {status} {resume_payload}",
            )
        report["resume"] = resume_payload
        report["post_resume"] = _wait_ingestion_live()

        async with pool.acquire() as connection:
            before_ingestion_restart = await _latest_base_open(connection)
        _compose_action("restart", "ingestion")
        report["ingestion_restart"] = _wait_ingestion_live()
        async with pool.acquire() as connection:
            restarted_rows = await _wait_for_new_base_rows(
                connection,
                after=before_ingestion_restart,
                count=1,
                timeout=LIVE_CANDLE_TIMEOUT,
            )
            _validate_base_rows(restarted_rows)
            report["ingestion_restart"]["continuation"] = {
                "before_open": _iso(before_ingestion_restart),
                "rows": [_iso(row["open_time"]) for row in restarted_rows],
                "outbox": await _wait_pending_zero(
                    connection, timeout=OPERATION_TIMEOUT
                ),
            }

        _compose_action("stop", "signal-worker")
        if client is not None:
            await client.aclose()
            client = None
        outage_started = datetime.now(UTC)
        _compose_action("stop", "broker")
        broker_stopped = not _service_state("broker")["running"]
        if not broker_stopped:
            raise N1COperationError("BLOCKED_N1C_BROKER_OUTAGE", "broker did not stop")
        outage_ready, _ = _http("/health/ready")
        outage_live, _ = _http("/health/live")
        if outage_ready != 200 or outage_live != 200:
            raise N1COperationError(
                "BLOCKED_N1C_BROKER_OUTAGE",
                f"ingestion lost readiness during broker outage: live={outage_live}, ready={outage_ready}",
            )
        async with pool.acquire() as connection:
            outage_baseline = await _latest_base_open(connection)
            outage_rows = await _wait_for_new_base_rows(
                connection,
                after=outage_baseline,
                count=1,
                timeout=LIVE_CANDLE_TIMEOUT,
            )
            outage_row = outage_rows[0]
            pending = await connection.fetchval(
                """
                SELECT count(*)
                FROM ingestion.outbox
                WHERE payload->>'instrument_id' = $1
                  AND payload->>'timeframe' = $2
                  AND payload->>'open_time' = $3
                  AND published_at IS NULL
                """,
                BTC_INSTRUMENT_ID,
                BASE_TIMEFRAME,
                _iso(outage_row["open_time"]),
            )
            if int(pending) != 1:
                raise N1COperationError(
                    "BLOCKED_N1C_BROKER_OUTAGE",
                    f"outage candle did not remain pending: {pending}",
                )
            report["broker_outage"] = {
                "started_at": _iso(outage_started),
                "health_live": outage_live,
                "health_ready": outage_ready,
                "canonical": {
                    "open": _iso(outage_row["open_time"]),
                    "close": _iso(outage_row["close_time"]),
                    "source_type": outage_row["source_type"],
                    "source_provider": outage_row["source_provider"],
                },
                "pending_outbox": int(pending),
            }

        _compose_action("start", "broker")
        _wait_sync(
            lambda: _service_state("broker")["healthy"],
            timeout=OPERATION_TIMEOUT,
            description="Valkey recovery",
        )
        client = await create_valkey_client(manager)
        async with pool.acquire() as connection:
            report["broker_recovery"] = await _wait_pending_zero(
                connection,
                timeout=OPERATION_TIMEOUT,
            )
        _compose_action("up", "signal-worker", build=True)
        recovered_signal = await _wait_signal_live(
            client,
            settings=signal_settings,
            timeout=OPERATION_TIMEOUT,
        )
        for timeframe in BTC_TIMEFRAMES:
            group = recovered_signal["groups"][timeframe]
            if group.get("pending") != 0 or group.get("lag") != 0:
                raise N1COperationError(
                    "BLOCKED_N1C_BROKER_RECOVERY",
                    f"{timeframe} group did not recover cleanly: {group}",
                )
        report["post_outage_signal"] = recovered_signal
        report["broker_outage"]["signal_duplicate_suppression"] = (
            "history priming plus ingestion timestamp cursor; group PEL/lag returned to zero"
        )
        report["final_database"] = None
        async with pool.acquire() as connection:
            report["final_database"] = await _btc_state(connection)
        return report
    except N1COperationError as exc:
        report["status"] = exc.status
        report["failure"] = str(exc)
        report["failure_evidence"] = exc.evidence
        raise
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                await client.aclose()
        if manager is not None:
            with contextlib.suppress(Exception):
                manager.shutdown()
            ConfigManager.reset_singleton()
        await pool.close()


def _restore_services(
    initial_states: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    for service in ("signal-worker", "ingestion"):
        initial_running = initial_states[service]["running"]
        current_running = _service_state(service)["running"]
        if initial_running and not current_running:
            _compose_action("up", service)
        elif not initial_running and current_running:
            if service == "signal-worker":
                _stop_service_with_evidence(service)
            else:
                _compose_action("stop", service)

    initial_broker_running = initial_states["broker"]["running"]
    current_broker_running = _service_state("broker")["running"]
    if initial_broker_running and not current_broker_running:
        _compose_action("start", "broker")
        _wait_sync(
            lambda: _service_state("broker")["healthy"],
            timeout=OPERATION_TIMEOUT,
            description="restored broker health",
        )
    elif not initial_broker_running and current_broker_running:
        _compose_action("stop", "broker")

    final_states = _capture_service_states()
    for service in ("signal-worker", "ingestion"):
        if initial_states[service]["running"]:
            continue
        state = final_states[service]
        if state["running"]:
            raise N1COperationError(
                "BLOCKED_N1C_RESOURCE_RESTORE",
                f"{service} remained running after restoration: {state}",
            )
        if service == "signal-worker":
            containers = state["containers"]
            exit_codes = [
                int(container["exit_code"])
                for container in containers
                if container["exit_code"] != ""
            ]
            if (
                not containers
                or any(exit_code != 0 for exit_code in exit_codes)
                or any(container["oom_killed"] for container in containers)
            ):
                raise N1COperationError(
                    "BLOCKED_N1C_RESOURCE_RESTORE",
                    f"signal-worker did not leave a clean stopped state: {state}",
                    evidence={"final_states": final_states},
                )
    return final_states


def run_certification(*, execute: bool = False) -> dict[str, Any]:
    """Run the N1C dry-run or the guarded operational certification."""
    compose_report = validate_compose_contract()
    states = _capture_service_states()
    _require_preconditions(states)
    result: dict[str, Any] = {
        "status": "DRY_RUN",
        "compose": compose_report,
        "initial_states": states,
        "Timescale": states.get("db"),
        "BTC_LEGACY_MANIFEST_DEPENDENCY_TEMPORARY": True,
        "AUTOMATIC_PUBLISHED_OUTBOX_REPLAY": "ABSENT",
        "N1_PUBLISHED_OUTBOX_CLEANUP": "DISABLED",
        "BTC_N1_AUTOMATIC_ROLLBACK_TO_LEGACY": False,
        "BTC_N1_LIVE_CANARY_STARTED": False,
    }
    if not execute:
        return result

    try:
        result = asyncio.run(_run_execute())
    except Exception:
        _restore_services(states)
        raise
    result["service_restoration"] = _restore_services(states)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="start/restart the owned Compose services and run the certification",
    )
    args = parser.parse_args()
    try:
        result = run_certification(execute=args.execute)
    except N1COperationError as exc:
        print(
            json.dumps(
                {"status": exc.status, "failure": str(exc), "evidence": exc.evidence},
                indent=2,
            )
        )
        return 1
    print(json.dumps(result, indent=2, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
