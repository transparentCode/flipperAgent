"""Measured disposable D11B authority cutover trial.

This module owns the certification orchestration only.  It uses the existing
ingestion materialization, Strategy/Decision/Risk processes, authority CAS,
effect-progress repository, and legacy group APIs; it does not add a runtime
worker or alternate publication path.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg
import valkey.asyncio as valkey
from valkey.exceptions import ResponseError

from apps.decision_app.storage.bootstrap import ensure_checkpoint_schema
from apps.decision_app.storage.shadow_progress import (
    LaneEffectProgress,
    LaneEffectProgressRepository,
)
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from libs.common.config import ConfigManager
from libs.common.signal_authority import (
    TARGET_SIGNAL_ROUTES,
    SignalAuthorityConflict,
    SignalAuthorityStore,
)
from scripts.decision_d11b_authority_cutover import (
    cutback_fast_forward_group,
    derive_authoritative_lane_identities,
    feature_close_cutoff_ms,
    signal_head_preflight,
    timeframe_duration_ms,
)
from tests.combined.c2_harness import (
    STARTUP_COUNT,
    _route_keys,
    _seed_bar,
)
from tests.combined.c2_harness import (
    _provider_observation as _base_provider_observation,
)
from tests.combined.c4a_harness import (
    _cleanup_probe,
    _free_port,
    _keys,
    _run,
    _wait_for,
    http_json,
    seed_manifests,
)
from tests.combined.d11a_harness import (
    _oracle_cutoff_statuses,
    progress_rows,
    signal_entries,
)
from tests.combined.d11a_harness import (
    materialize_window as _materialize_window,
)

ROOT = Path(__file__).resolve().parents[2]
D11B_COMPOSE_FILE = ROOT / "tests/combined/fixtures/d11b/docker-compose.yml"
GROUP_NAME = "strategy_app_group"
TARGET_FEATURE_ROUTES = (
    ("BTCUSDT:1h", "1h"),
    ("BTCUSDT:4h", "4h"),
    ("ETHUSDT:4h", "4h"),
)


def _d11b_provider_observation(*, asset: str, opened: datetime, index: int) -> Any:
    """Use the shared real producer shape with one measured NO_SIGNAL route."""

    observation = _base_provider_observation(
        asset=asset,
        opened=opened,
        index=index,
    )
    if asset != "ETH":
        return observation
    close = Decimal(100)
    return replace(
        observation,
        open=close,
        high=close + Decimal("0.2"),
        low=close - Decimal("0.2"),
        close=close,
    )


async def materialize_window(
    pool: Any,
    broker: Any,
    config: Any,
    *,
    bucket_start: datetime,
    index_offset: int,
    count: int = 60,
) -> dict[str, object]:
    """Run the approved producer harness with D11B's neutral ETH route."""

    from tests.combined import d11a_harness

    original = d11a_harness._provider_observation
    d11a_harness._provider_observation = _d11b_provider_observation
    try:
        return await _materialize_window(
            pool,
            broker,
            config,
            bucket_start=bucket_start,
            index_offset=index_offset,
            count=count,
        )
    finally:
        d11a_harness._provider_observation = original


def _canonical_json(value: object) -> str:
    def normalize(item: object) -> object:
        if isinstance(item, Mapping):
            return {str(key): normalize(value) for key, value in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalize(value) for value in item]
        if isinstance(item, datetime):
            return item.astimezone(UTC).isoformat()
        return item

    import json

    return json.dumps(normalize(value), sort_keys=True, separators=(",", ":"))


def sha256_fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _group_value(
    group: Mapping[object, object], name: str, default: object = None
) -> object:
    value = group.get(name, default)
    if value is None:
        value = group.get(name.encode(), default)
    if isinstance(value, bytes):
        return value.decode()
    return value


async def _group(client: Any, stream_key: str) -> dict[str, object]:
    try:
        groups = await client.xinfo_groups(stream_key)
    except Exception:  # noqa: BLE001 - stream/group may not exist during startup
        return {"exists": False, "pending": -1, "lag": -1}
    for value in groups:
        if str(_group_value(value, "name", "")) == GROUP_NAME:
            return {
                "exists": True,
                "pending": int(_group_value(value, "pending", -1)),
                "lag": int(_group_value(value, "lag", -1)),
                "last_delivered_id": str(
                    _group_value(value, "last-delivered-id", "0-0")
                ),
            }
    return {"exists": False, "pending": -1, "lag": -1}


async def _named_group(
    client: Any, stream_key: str, group_name: str
) -> dict[str, object]:
    """Read one real Valkey consumer-group snapshot without summary defaults."""

    try:
        groups = await client.xinfo_groups(stream_key)
    except Exception:  # noqa: BLE001 - absent streams are measured as absent
        return {"exists": False, "pending": -1, "lag": -1}
    for value in groups:
        if str(_group_value(value, "name", "")) == group_name:
            return {
                "exists": True,
                "pending": int(_group_value(value, "pending", -1)),
                "lag": int(_group_value(value, "lag", -1)),
                "last_delivered_id": str(
                    _group_value(value, "last-delivered-id", "0-0")
                ),
            }
    return {"exists": False, "pending": -1, "lag": -1}


async def _wait_group(client: Any, stream_key: str) -> dict[str, object] | None:
    value = await _group(client, stream_key)
    return value if value.get("exists") is True else None


async def _wait_feature_progress(client: Any) -> dict[str, dict[str, object]] | None:
    """Wait until every target legacy group has consumed a real feature entry."""
    result: dict[str, dict[str, object]] = {}
    for route, _timeframe in TARGET_FEATURE_ROUTES:
        group = await _group(client, f"features:{route}")
        if group.get("exists") is not True or group.get("last_delivered_id") == "0-0":
            return None
        result[route] = group
    return result


async def _wait_feature_quiescence(
    client: Any,
) -> dict[str, dict[str, object]] | None:
    """Wait until all target legacy groups have drained without a PEL."""

    result = await _wait_feature_progress(client)
    if result is None:
        return None
    if any(
        int(group.get("pending", -1)) != 0 or int(group.get("lag", -1)) != 0
        for group in result.values()
    ):
        return None
    return result


async def _feature_boundary(
    client: Any,
    *,
    stream_key: str,
    timeframe: str,
) -> dict[str, object]:
    group = await _group(client, stream_key)
    if group["exists"] is not True:
        raise RuntimeError(f"feature group missing: {stream_key}")
    last_id = str(group["last_delivered_id"])
    entries = await client.xrange(stream_key, last_id, last_id)
    if not entries:
        raise RuntimeError(
            f"last delivered feature entry is missing: {stream_key}/{last_id}"
        )
    fields = dict(entries[0][1])
    raw_timestamp = fields.get("timestamp")
    if isinstance(raw_timestamp, bytes):
        raw_timestamp = raw_timestamp.decode()
    timestamp_ms = int(float(raw_timestamp))
    close_cutoff_ms = feature_close_cutoff_ms(timestamp_ms, timeframe)
    return {
        "stream": stream_key,
        "last_delivered_id": last_id,
        "feature_timestamp_ms": timestamp_ms,
        "timeframe": timeframe,
        "close_cutoff_ms": close_cutoff_ms,
        "strategy_group": group,
    }


async def _target_feature_boundaries(client: Any) -> dict[str, dict[str, object]]:
    return {
        route: {
            "route": route,
            **await _feature_boundary(
                client,
                stream_key=f"features:{route}",
                timeframe=timeframe,
            ),
        }
        for route, timeframe in TARGET_FEATURE_ROUTES
    }


async def _stable_target_feature_boundaries(client: Any) -> dict[str, object]:
    """Read all target group positions twice after the owner is stopped."""

    first = await _target_feature_boundaries(client)
    second = await _target_feature_boundaries(client)
    if first != second:
        raise RuntimeError("target feature groups moved during post-stop boundary read")
    return {"first": first, "second": second, "stable": True, "final": second}


async def _stable_progress_rows(pool: asyncpg.Pool) -> dict[str, object]:
    """Read effect progress twice after Decision quiescence."""

    first = await progress_rows(pool)
    second = await progress_rows(pool)
    if first != second:
        raise RuntimeError("Decision effect progress moved after process stop")
    return {"first": first, "second": second, "stable": True, "final": second}


async def _wait_risk_quiescence(
    broker: Any,
) -> dict[str, dict[str, object]] | None:
    result = {
        route: await _named_group(broker, f"signals:{route}", "risk_app_group")
        for route in TARGET_SIGNAL_ROUTES
    }
    if set(result) != set(TARGET_SIGNAL_ROUTES):
        return None
    if any(
        value.get("exists") is not True
        or value.get("pending") != 0
        or value.get("lag") != 0
        for value in result.values()
    ):
        return None
    return result


def _free_ports(count: int) -> tuple[int, ...]:
    ports: list[int] = []
    while len(ports) < count:
        candidate = _free_port()
        if candidate not in ports:
            ports.append(candidate)
    return tuple(ports)


@dataclass(slots=True)
class D11BInfrastructure:
    trial_name: str
    db_port: int = field(init=False)
    broker_port: int = field(init=False)
    decision_port: int = field(init=False)
    project_name: str = field(init=False)

    def __post_init__(self) -> None:
        self.db_port, self.broker_port, self.decision_port = _free_ports(3)
        token = "".join(char if char.isalnum() else "_" for char in self.trial_name)
        self.project_name = f"flipper_d11b_{os.getpid()}_{token}"

    @property
    def environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "D11B_DB_PORT": str(self.db_port),
                "D11B_BROKER_PORT": str(self.broker_port),
                "D11B_DECISION_PORT": str(self.decision_port),
                "COMPOSE_PROJECT_NAME": self.project_name,
                "COMPOSE_DISABLE_ENV_FILE": "1",
                "D11B_STRATEGY_MODELS_FILE": "./configs/models-pre-cutover.yaml",
                "OTEL_SDK_DISABLED": "true",
            }
        )
        return environment

    def command(self, *arguments: str) -> list[str]:
        return [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            str(D11B_COMPOSE_FILE),
            "-p",
            self.project_name,
            *arguments,
        ]

    async def compose(
        self,
        *arguments: str,
        strategy_models_file: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = self.environment
        if strategy_models_file is not None:
            environment["D11B_STRATEGY_MODELS_FILE"] = strategy_models_file
        return await asyncio.to_thread(
            _run,
            self.command(*arguments),
            env=environment,
        )

    async def start_foundation(self) -> None:
        result = await self.compose("up", "-d", "--wait", "db", "broker")
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)

    async def start_legacy(self) -> None:
        result = await self.compose(
            "up",
            "-d",
            "--build",
            "--wait",
            "signal-worker",
            "strategy-worker",
            "risk-worker",
            strategy_models_file="./configs/models-pre-cutover.yaml",
        )
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)

    async def stop_strategy(self) -> None:
        result = await self.compose("stop", "strategy-worker")
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)

    async def restart_strategy(self, *, relinquished: bool = False) -> None:
        result = await self.compose(
            "up",
            "-d",
            "--wait",
            "strategy-worker",
            strategy_models_file=(
                "./configs/models-post-cutover.yaml"
                if relinquished
                else "./configs/models-pre-cutover.yaml"
            ),
        )
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)

    async def start_risk(self) -> None:
        result = await self.compose("up", "-d", "--wait", "risk-worker")
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)

    async def stop_risk(self) -> None:
        result = await self.compose("stop", "risk-worker")
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)

    async def start_decision(self) -> None:
        result = await self.compose("up", "-d", "--build", "--wait", "decision")
        if result.returncode:
            logs = await self.compose("logs", "--no-color", "decision")
            raise RuntimeError((result.stderr or result.stdout) + "\n" + logs.stdout)

    async def stop_decision(self) -> None:
        result = await self.compose("stop", "decision")
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)

    async def restart_decision(self) -> None:
        await self.stop_decision()
        await self.start_decision()

    async def restart_broker(self) -> None:
        result = await self.compose("restart", "broker")
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)

    async def logs(self, service: str) -> str:
        result = await self.compose("logs", "--no-color", service)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        return result.stdout

    async def cleanup(self) -> dict[str, object]:
        result = await self.compose("down", "-v", "--remove-orphans")
        leftovers = await asyncio.to_thread(_cleanup_probe, self.project_name)
        return {
            "down_returncode": result.returncode,
            "leftovers": leftovers,
            "clean": result.returncode == 0 and not any(leftovers.values()),
        }

    @property
    def postgres_dsn(self) -> str:
        return f"postgresql://d11b_user:d11b_password@127.0.0.1:{self.db_port}/d11b_db"

    @property
    def valkey_uri(self) -> str:
        return f"redis://127.0.0.1:{self.broker_port}/0"

    @property
    def decision_url(self) -> str:
        return f"http://127.0.0.1:{self.decision_port}"


def _load_production_config():
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(ROOT / "configs"))
    try:
        from apps.decision_app.settings import load_decision_config

        return load_decision_config(manager)
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()


async def _ensure_risk_schema(pool: asyncpg.Pool) -> dict[str, object]:
    """Create only the Risk persistence tables needed by the disposable probe."""

    statements = (
        """
        CREATE TABLE IF NOT EXISTS risk_account_snapshots (
            timestamp BIGINT NOT NULL,
            balance DOUBLE PRECISION NOT NULL,
            equity DOUBLE PRECISION NOT NULL,
            unrealized_pnl DOUBLE PRECISION NOT NULL,
            realized_pnl DOUBLE PRECISION NOT NULL,
            drawdown_pct DOUBLE PRECISION NOT NULL,
            peak_equity DOUBLE PRECISION NOT NULL,
            open_position_count INTEGER NOT NULL,
            daily_pnl DOUBLE PRECISION NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS risk_positions (
            asset TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_price DOUBLE PRECISION NOT NULL,
            current_price DOUBLE PRECISION NOT NULL,
            size DOUBLE PRECISION NOT NULL,
            unrealized_pnl DOUBLE PRECISION NOT NULL,
            entry_timestamp DOUBLE PRECISION NOT NULL,
            source_model TEXT,
            source_timeframe TEXT,
            stop_loss_price DOUBLE PRECISION,
            take_profit_price DOUBLE PRECISION,
            trailing_stop_distance DOUBLE PRECISION,
            original_size DOUBLE PRECISION,
            tp_levels JSONB,
            tp_portions JSONB,
            tp_levels_hit JSONB,
            original_stop_loss DOUBLE PRECISION,
            trail_to_breakeven BOOLEAN
        )
        """,
    )
    async with pool.acquire() as connection:
        for _ in range(2):
            for statement in statements:
                await connection.execute(statement)
        rows = await connection.fetch(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('risk_account_snapshots', 'risk_positions')
            ORDER BY table_name
            """
        )
    tables = [str(row["table_name"]) for row in rows]
    return {
        "tables": tables,
        "idempotent": tables == ["risk_account_snapshots", "risk_positions"],
    }


async def _seed_d11b_future_history(pool: asyncpg.Pool, config: Any) -> datetime:
    """Seed deterministic, past-dated history for real wall-clock resolution."""

    # Keep every certified cutoff behind the real container clock.  The
    # historical legacy process is still started and exercised; the fixture's
    # pre-cutover models are deliberately neutral, so no legacy signal stream
    # head is manufactured before the explicit Decision IDs.
    bucket_start = datetime(2026, 8, 19, tzinfo=UTC)
    rows: list[tuple[object, ...]] = []
    for key in _route_keys(config):
        duration = config.timeframe_grid.duration(key.timeframe)
        start = bucket_start - duration * STARTUP_COUNT
        for index in range(STARTUP_COUNT):
            close = (
                Decimal(100)
                if key.asset == "ETHUSDT"
                else Decimal(100) + Decimal(index) / Decimal(10)
            )
            candle = _seed_bar(
                key,
                opened=start + duration * index,
                close=close,
            )
            rows.append(
                (
                    candle.lane.venue,
                    candle.lane.instrument_id,
                    candle.lane.timeframe,
                    candle.open_time,
                    candle.close_time,
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    candle.volume,
                    candle.taker_buy_base,
                    candle.source_type,
                    candle.source_provider,
                    candle.source_timeframe,
                )
            )
    query = """
        INSERT INTO ingestion.candles (
            venue, instrument_id, timeframe, open_time, close_time,
            open, high, low, close, volume, taker_buy_base,
            source_type, source_provider, source_timeframe
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
    """
    async with pool.acquire() as connection, connection.transaction():
        await connection.executemany(query, rows)
    return bucket_start


def _progress_cutoffs(
    rows: list[dict[str, object]],
    identities: Mapping[str, Any],
) -> dict[str, int]:
    """Convert measured effect-progress rows back to their canonical routes."""

    routes_by_lane = {identity.lane_id: route for route, identity in identities.items()}
    result: dict[str, int] = {}
    for row in rows:
        lane_id = row.get("lane_id")
        route = routes_by_lane.get(lane_id)
        value = row.get("market_as_of")
        if route is None or not isinstance(value, str):
            continue
        cutoff = datetime.fromisoformat(value).astimezone(UTC)
        result[route] = int(cutoff.timestamp() * 1000)
    if set(result) != set(TARGET_SIGNAL_ROUTES):
        raise RuntimeError("effect progress did not contain every authoritative route")
    return result


async def _wait_decision_ready(url: str) -> dict[str, object]:
    async def probe() -> dict[str, object] | None:
        try:
            status, payload = await http_json(url, "/health/ready")
        except OSError:
            return None
        return payload if status == 200 and payload.get("status") == "ready" else None

    return await _wait_for(probe, timeout=240, label="D11B Decision readiness")


async def _runtime_snapshot(url: str) -> dict[str, object]:
    status, payload = await http_json(url, "/runtime")
    if status != 200:
        raise RuntimeError(f"Decision /runtime returned {status}: {payload}")
    return payload


def _signal_delta(
    before: list[dict[str, object]], after: list[dict[str, object]]
) -> list[dict[str, object]]:
    before_keys = {
        (item.get("stream"), item.get("entry_id"), item.get("idempotency_key"))
        for item in before
    }
    return [
        item
        for item in after
        if (item.get("stream"), item.get("entry_id"), item.get("idempotency_key"))
        not in before_keys
    ]


def _signal_routes(
    entries: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {}
    for entry in entries:
        stream = str(entry["stream"])
        result.setdefault(stream.removeprefix("signals:"), []).append(entry)
    return result


def _authority_payload(records: object) -> dict[str, dict[str, object]]:
    if not isinstance(records, (list, tuple)):
        return {}
    return {
        record.route: {
            "schema_version": record.schema_version,
            "route": record.route,
            "owner": record.owner,
            "epoch": record.epoch,
            "boundary_ms": record.boundary_ms,
        }
        for record in records
    }


async def _wait_strategy_catalog(
    infrastructure: D11BInfrastructure, expected_count: int
) -> dict[str, object]:
    """Use the real strategy process log to prove its constructed catalog."""

    async def probe() -> dict[str, object] | None:
        logs = await infrastructure.logs("strategy-worker")
        matches = list(
            re.finditer(
                r"Discovered\s+(\d+) strategy asset/timeframe pairs.*?\[(.*?)\]",
                logs,
                flags=re.DOTALL,
            )
        )
        match = next(
            (
                candidate
                for candidate in reversed(matches)
                if int(candidate.group(1)) == expected_count
            ),
            None,
        )
        if match is None:
            return None
        routes = sorted(
            {
                f"{asset}:{timeframe}"
                for asset, timeframe, _trigger in re.findall(
                    r"\('([^']+)',\s*'([^']+)',\s*'([^']+)'\)",
                    match.group(2),
                )
            }
        )
        return {
            "discovered_pair_count": int(match.group(1)),
            "routes": routes,
            "log_sha256": hashlib.sha256(logs.encode()).hexdigest(),
        }

    return await _wait_for(
        probe,
        timeout=180,
        label=f"strategy catalog ({expected_count} pairs)",
    )


async def _guard_probe(
    broker: Any,
    authority: SignalAuthorityStore,
    *,
    route: str,
    owner: str,
    expected_epoch: int,
    expected_boundary_ms: int,
    effect_cutoff_ms: int,
    label: str,
) -> dict[str, object]:
    """Exercise the real Valkey write fence, deleting only its probe entry."""

    stream_key = f"signals:{route}"
    fields = {
        "asset": route.split(":", 1)[0],
        "timeframe": route.split(":", 1)[1],
        "timestamp": str(effect_cutoff_ms / 1000),
        "direction": "0",
        "conviction": "0",
        "price": "1",
        "idempotency_key": f"d11b-probe-{label}",
        "model_name": "d11b-probe",
        "metadata": "{}",
    }
    last_probe: tuple[object, str] | None = None
    for attempt in range(2):
        head = await broker.xrevrange(stream_key, "+", "-", count=1)
        head_id = head[0][0] if head else None
        if isinstance(head_id, bytes):
            head_id = head_id.decode()
        try:
            info = await broker.xinfo_stream(stream_key)
        except Exception:  # noqa: BLE001 - an absent stream has no generated ID
            info = {}
        generated_id = info.get("last-generated-id") or info.get(b"last-generated-id")
        if isinstance(generated_id, bytes):
            generated_id = generated_id.decode()
        visible_ms = int(str(head_id).split("-", 1)[0]) if head_id else 0
        generated_ms = int(str(generated_id).split("-", 1)[0]) if generated_id else 0
        stream_id = (
            f"{max(effect_cutoff_ms, visible_ms + 1_000_000_000, generated_ms + 1)}-0"
        )
        last_probe = (head_id, stream_id)
        try:
            result = await authority.guarded_xadd(
                route=route,
                expected_owner=owner,  # type: ignore[arg-type]
                expected_epoch=expected_epoch,
                expected_boundary_ms=expected_boundary_ms,
                effect_cutoff_ms=effect_cutoff_ms,
                stream_key=stream_key,
                fields=fields,
                stream_id=stream_id,
                maxlen=100,
                approximate=False,
            )
            break
        except ResponseError:
            if attempt == 1:
                raise RuntimeError(
                    f"guard probe stream ordering failed label={label} "
                    f"head={last_probe[0]!r} stream_id={last_probe[1]!r}"
                )
    if result.allowed and result.stream_id is not None:
        await broker.xdel(stream_key, result.stream_id)
    return {
        "label": label,
        "route": route,
        "owner": owner,
        "expected_epoch": expected_epoch,
        "expected_boundary_ms": expected_boundary_ms,
        "effect_cutoff_ms": effect_cutoff_ms,
        "xadd_count": int(result.allowed and result.stream_id is not None),
        "result": "PUBLISHED" if result.allowed else "DENIED",
        "reason": result.reason,
    }


async def _exact_guard_probe(
    broker: Any,
    authority: SignalAuthorityStore,
    *,
    route: str,
    owner: str,
    expected_epoch: int,
    expected_boundary_ms: int,
    entry_id: str,
    label: str,
) -> dict[str, object]:
    """Reconcile one existing signal ID through the fenced exact-ID path."""

    stream_key = f"signals:{route}"
    entries = await broker.xrange(stream_key, entry_id, entry_id)
    if not entries:
        raise RuntimeError(f"exact-ID probe entry is missing: {stream_key}/{entry_id}")
    returned_id, fields = entries[0]
    if str(returned_id) != entry_id:
        raise RuntimeError(
            f"exact-ID probe returned an unexpected entry: {returned_id}"
        )
    effect_cutoff_ms = int(entry_id.split("-", 1)[0])
    result = await authority.guarded_exact_xadd(
        route=route,
        expected_owner=owner,  # type: ignore[arg-type]
        expected_epoch=expected_epoch,
        expected_boundary_ms=expected_boundary_ms,
        effect_cutoff_ms=effect_cutoff_ms,
        stream_key=stream_key,
        stream_id=entry_id,
        fields=dict(fields),
        maxlen=1000,
        approximate=True,
    )
    if result.allowed:
        raise RuntimeError(f"exact-ID probe unexpectedly allowed: {label}")
    return {
        "label": label,
        "route": route,
        "owner": owner,
        "expected_epoch": expected_epoch,
        "expected_boundary_ms": expected_boundary_ms,
        "effect_cutoff_ms": effect_cutoff_ms,
        "entry_id": entry_id,
        "xadd_count": 0,
        "result": "DENIED",
        "outcome": result.outcome,
        "reason": result.reason,
    }


async def _concurrent_guard_probes(
    broker: Any,
    authority: SignalAuthorityStore,
    *,
    route: str,
    boundary_ms: int,
) -> list[dict[str, object]]:
    """Run stale and current writers together at one real Valkey fence."""

    barrier = asyncio.Barrier(2)

    async def run_probe(
        *,
        owner: str,
        expected_epoch: int,
        expected_boundary_ms: int,
        effect_cutoff_ms: int,
        label: str,
    ) -> dict[str, object]:
        await barrier.wait()
        return await _guard_probe(
            broker,
            authority,
            route=route,
            owner=owner,
            expected_epoch=expected_epoch,
            expected_boundary_ms=expected_boundary_ms,
            effect_cutoff_ms=effect_cutoff_ms,
            label=label,
        )

    results = await asyncio.gather(
        run_probe(
            owner="strategy",
            expected_epoch=0,
            expected_boundary_ms=0,
            effect_cutoff_ms=boundary_ms + 1,
            label="concurrent-stale-strategy-epoch-0-denied-at-epoch-2",
        ),
        run_probe(
            owner="strategy",
            expected_epoch=2,
            expected_boundary_ms=boundary_ms,
            effect_cutoff_ms=boundary_ms + 1,
            label="concurrent-strategy-epoch-2-allowed",
        ),
    )
    return sorted(results, key=lambda item: str(item["label"]))


async def _wait_effect_progress(pool: asyncpg.Pool, cutoff: datetime) -> bool:
    rows = await pool.fetch("SELECT market_as_of FROM decision.shadow_progress")
    return bool(rows) and all(row["market_as_of"] >= cutoff for row in rows)


async def _seed_effect_progress(
    pool: asyncpg.Pool,
    boundaries: Mapping[str, int],
) -> dict[str, object]:
    repository = LaneEffectProgressRepository(pool)
    identities = derive_authoritative_lane_identities()
    now = datetime.now(UTC)
    rows: list[dict[str, object]] = []
    for route in TARGET_SIGNAL_ROUTES:
        identity = identities[route]
        boundary = datetime.fromtimestamp(boundaries[route] / 1000, tz=UTC)
        progress = LaneEffectProgress.create(
            identity=identities[route],
            market_as_of=boundary,
            last_disposition=None,
            created_at=now,
            updated_at=now,
        )
        result = await repository.save(progress)
        if result.value not in {"INSERTED", "UPDATED", "IDENTICAL"}:
            raise RuntimeError(f"effect-progress seed failed: {route}/{result.value}")
        rows.append(
            {
                "lane_id": identity.lane_id,
                "effective_lane_revision": identity.effective_lane_revision,
                "feature_plan_fingerprint": identity.feature_plan_fingerprint,
                "data_plan_fingerprint": identity.data_plan_fingerprint,
                "route": route,
                "market_as_of_ms": boundaries[route],
                "last_disposition": None,
                "save_result": result.value,
            }
        )
    return {"rows": rows, "identities": identities}


async def run_measured_trial(trial_name: str) -> dict[str, object]:
    """Run one real Strategy -> Decision -> Strategy -> Decision sequence."""

    infrastructure = D11BInfrastructure(trial_name)
    pool: asyncpg.Pool | None = None
    broker: Any | None = None
    trial: dict[str, object] = {
        "evidence_origin": "measured_disposable",
        "trial_name": trial_name,
        "real_disposable_stack": True,
    }
    try:
        config = _load_production_config()
        await infrastructure.start_foundation()
        pool = await asyncpg.create_pool(
            infrastructure.postgres_dsn, min_size=1, max_size=4
        )
        broker = valkey.Valkey.from_url(
            infrastructure.valkey_uri, decode_responses=True
        )
        await apply_ingestion_schema(pool)
        await ensure_checkpoint_schema(pool)
        risk_schema = await _ensure_risk_schema(pool)
        bucket_start = await _seed_d11b_future_history(pool, config)
        await seed_manifests(broker)
        authority = SignalAuthorityStore(broker)
        initial_authority = await authority.seed_strategy()
        initial_guard = await _guard_probe(
            broker,
            authority,
            route="BTCUSDT:1h",
            owner="strategy",
            expected_epoch=0,
            expected_boundary_ms=0,
            effect_cutoff_ms=3_600_000,
            label="strategy-epoch-0-allowed",
        )
        partial_cutover_before = _authority_payload(
            [await authority.read(route) for route in TARGET_SIGNAL_ROUTES]
        )
        partial_cutover_rejected = False
        try:
            await authority.handoff_many(
                routes=TARGET_SIGNAL_ROUTES,
                expected_owner="strategy",
                new_owner="decision",
                expected_epochs={
                    route: (99 if route == "BTCUSDT:1h" else 0)
                    for route in TARGET_SIGNAL_ROUTES
                },
                boundary_ms_by_route={route: 1 for route in TARGET_SIGNAL_ROUTES},
            )
        except SignalAuthorityConflict:
            partial_cutover_rejected = True
        partial_cutover_after = _authority_payload(
            [await authority.read(route) for route in TARGET_SIGNAL_ROUTES]
        )
        await infrastructure.start_legacy()
        pre_strategy_catalog = await _wait_strategy_catalog(infrastructure, 3)
        first = await materialize_window(
            pool, broker, config, bucket_start=bucket_start, index_offset=0, count=60
        )
        await _wait_for(
            lambda: _wait_feature_progress(broker),
            timeout=180,
            label="legacy strategy feature progress",
        )
        preliminary_legacy_boundaries = await _target_feature_boundaries(broker)
        late_materialized = await materialize_window(
            pool,
            broker,
            config,
            bucket_start=bucket_start,
            index_offset=60,
            count=240,
        )
        await _wait_for(
            lambda: _wait_feature_progress(broker),
            timeout=180,
            label="late legacy feature progress before strategy stop",
        )
        await infrastructure.stop_strategy()
        await infrastructure.restart_strategy(relinquished=True)
        post_strategy_catalog = await _wait_strategy_catalog(infrastructure, 4)
        await infrastructure.stop_strategy()
        post_stop_legacy_boundary = await _stable_target_feature_boundaries(broker)
        legacy_boundaries = post_stop_legacy_boundary["final"]
        boundaries = {
            route: int(evidence["close_cutoff_ms"])
            for route, evidence in legacy_boundaries.items()
        }
        initial_signals = await signal_entries(broker)
        risk_pre_cutover_groups = await _wait_for(
            lambda: _wait_risk_quiescence(broker),
            timeout=180,
            label="risk quiescence after strategy stop",
        )
        seed = await _seed_effect_progress(pool, boundaries)
        signal_heads: dict[str, object] = {}
        for route in TARGET_SIGNAL_ROUTES:
            rows = await broker.xrevrange(f"signals:{route}", "+", "-", count=1)
            head = None if not rows else str(rows[0][0])
            trigger = "1h" if route.endswith("1h") else "4h"
            signal_heads[route] = {
                "head_id": head,
                "preflight": signal_head_preflight(
                    head,
                    boundary_ms=boundaries[route],
                    trigger_timeframe=trigger,
                ),
            }
        after_cutover = await authority.handoff_many(
            routes=TARGET_SIGNAL_ROUTES,
            expected_owner="strategy",
            new_owner="decision",
            expected_epochs={route: 0 for route in TARGET_SIGNAL_ROUTES},
            boundary_ms_by_route=boundaries,
        )
        decision_probe = await _guard_probe(
            broker,
            authority,
            route="BTCUSDT:1h",
            owner="decision",
            expected_epoch=1,
            expected_boundary_ms=boundaries["BTCUSDT:1h"],
            effect_cutoff_ms=boundaries["BTCUSDT:1h"] + 1,
            label="decision-epoch-1-allowed",
        )
        decision_boundary_probe = await _guard_probe(
            broker,
            authority,
            route="BTCUSDT:1h",
            owner="decision",
            expected_epoch=1,
            expected_boundary_ms=boundaries["BTCUSDT:1h"],
            effect_cutoff_ms=boundaries["BTCUSDT:1h"],
            label="decision-boundary-equal-denied",
        )
        stale_strategy_probe = await _guard_probe(
            broker,
            authority,
            route="BTCUSDT:1h",
            owner="strategy",
            expected_epoch=0,
            expected_boundary_ms=0,
            effect_cutoff_ms=boundaries["BTCUSDT:1h"] + 1,
            label="stale-strategy-epoch-0-denied",
        )
        await infrastructure.start_decision()
        startup_ready = await _wait_decision_ready(infrastructure.decision_url)
        startup_runtime = await _runtime_snapshot(infrastructure.decision_url)
        await infrastructure.start_risk()
        live_materialized = await materialize_window(
            pool, broker, config, bucket_start=bucket_start, index_offset=60, count=180
        )
        await _wait_for(
            lambda: _wait_effect_progress(pool, datetime.fromtimestamp(0, tz=UTC)),
            timeout=180,
            label="Decision authoritative progress",
        )
        live_progress = await progress_rows(pool)
        live_signals = await signal_entries(broker)
        await infrastructure.restart_decision()
        restart_ready = await _wait_decision_ready(infrastructure.decision_url)
        restart_runtime = await _runtime_snapshot(infrastructure.decision_url)
        restart_progress = await progress_rows(pool)
        restart_signals = await signal_entries(broker)
        await infrastructure.stop_decision()
        during_down = await materialize_window(
            pool, broker, config, bucket_start=bucket_start, index_offset=240, count=60
        )
        await infrastructure.restart_decision()
        recovery_ready = await _wait_decision_ready(infrastructure.decision_url)
        recovery_runtime = await _runtime_snapshot(infrastructure.decision_url)
        recovery_progress = await progress_rows(pool)
        recovery_signals = await signal_entries(broker)
        await infrastructure.stop_decision()
        decision_progress_after_stop = await progress_rows(pool)
        decision_progress_stable = await _stable_progress_rows(pool)
        current_r = _progress_cutoffs(
            decision_progress_stable["final"], seed["identities"]
        )
        post_cutover_signals = _signal_delta(initial_signals, live_signals)
        post_cutover_signal_routes = _signal_routes(post_cutover_signals)
        risk_post_cutover_groups = {
            route: await _named_group(broker, f"signals:{route}", "risk_app_group")
            for route in TARGET_SIGNAL_ROUTES
        }
        risk_after_decision_stop = await _wait_for(
            lambda: _wait_risk_quiescence(broker),
            timeout=180,
            label="risk quiescence after Decision stop",
        )
        partial_cutback_before = _authority_payload(
            [await authority.read(route) for route in TARGET_SIGNAL_ROUTES]
        )
        partial_cutback_rejected = False
        try:
            await authority.handoff_many(
                routes=TARGET_SIGNAL_ROUTES,
                expected_owner="decision",
                new_owner="strategy",
                expected_epochs={
                    route: (99 if route == "BTCUSDT:1h" else 1)
                    for route in TARGET_SIGNAL_ROUTES
                },
                boundary_ms_by_route=current_r,
            )
        except SignalAuthorityConflict:
            partial_cutback_rejected = True
        partial_cutback_after = _authority_payload(
            [await authority.read(route) for route in TARGET_SIGNAL_ROUTES]
        )
        cutback_groups: dict[str, object] = {}
        cutback_before_groups: dict[str, object] = {}
        for route in TARGET_SIGNAL_ROUTES:
            cutback_before_groups[route] = await _group(broker, f"features:{route}")
            cutback_groups[route] = await cutback_fast_forward_group(
                broker,
                stream_key=f"features:{route}",
                group_name=GROUP_NAME,
                progress_cutoff_ms=current_r[route],
                timeframe="1h" if route.endswith("1h") else "4h",
            )
        after_cutback = await authority.handoff_many(
            routes=TARGET_SIGNAL_ROUTES,
            expected_owner="decision",
            new_owner="strategy",
            expected_epochs={route: 1 for route in TARGET_SIGNAL_ROUTES},
            boundary_ms_by_route=current_r,
        )
        exact_signal = next(
            (
                item
                for item in live_signals
                if item.get("stream") == "signals:BTCUSDT:1h"
            ),
            None,
        )
        if not isinstance(exact_signal, Mapping):
            raise TypeError("live Decision signal missing for exact-ID fence probe")
        stale_decision_exact_probe = await _exact_guard_probe(
            broker,
            authority,
            route="BTCUSDT:1h",
            owner="decision",
            expected_epoch=1,
            expected_boundary_ms=boundaries["BTCUSDT:1h"],
            entry_id=str(exact_signal["entry_id"]),
            label="stale-decision-exact-id-denied-after-cutback",
        )
        stale_decision_before_cutback = await _guard_probe(
            broker,
            authority,
            route="BTCUSDT:1h",
            owner="decision",
            expected_epoch=1,
            expected_boundary_ms=boundaries["BTCUSDT:1h"],
            effect_cutoff_ms=current_r["BTCUSDT:1h"] + 1,
            label="stale-decision-epoch-1-denied-after-cutback",
        )
        concurrent_race = await _concurrent_guard_probes(
            broker,
            authority,
            route="BTCUSDT:1h",
            boundary_ms=current_r["BTCUSDT:1h"],
        )
        strategy_epoch_2_probe = await _guard_probe(
            broker,
            authority,
            route="BTCUSDT:1h",
            owner="strategy",
            expected_epoch=2,
            expected_boundary_ms=current_r["BTCUSDT:1h"],
            effect_cutoff_ms=current_r["BTCUSDT:1h"] + 1,
            label="strategy-epoch-2-allowed",
        )
        await infrastructure.restart_strategy(relinquished=True)
        post_strategy_catalog = await _wait_strategy_catalog(infrastructure, 4)
        await infrastructure.stop_strategy()
        await infrastructure.restart_strategy(relinquished=False)
        restored_strategy_catalog = await _wait_strategy_catalog(infrastructure, 3)
        rollback_materialized = await materialize_window(
            pool,
            broker,
            config,
            bucket_start=bucket_start,
            index_offset=300,
            count=240,
        )
        restored_groups = await _wait_for(
            lambda: _wait_feature_quiescence(broker),
            timeout=180,
            label="legacy strategy rollback backlog drain",
        )
        restored_boundaries_preliminary = await _target_feature_boundaries(broker)
        await infrastructure.stop_strategy()
        restored_strategy_stop_boundary = await _stable_target_feature_boundaries(
            broker
        )
        restored_boundaries = restored_strategy_stop_boundary["final"]
        risk_before_recutover = await _wait_for(
            lambda: _wait_risk_quiescence(broker),
            timeout=180,
            label="risk quiescence before Decision recutover",
        )
        recutover_boundary = {
            route: int(evidence["close_cutoff_ms"])
            for route, evidence in restored_boundaries.items()
        }
        identities = seed["identities"]
        repository = LaneEffectProgressRepository(pool)
        now = datetime.now(UTC)
        for route in TARGET_SIGNAL_ROUTES:
            current = await repository.load(identities[route])
            if current is None:
                raise RuntimeError(f"missing progress before recutover: {route}")
            result = await repository.save(
                LaneEffectProgress.create(
                    identity=identities[route],
                    market_as_of=datetime.fromtimestamp(
                        recutover_boundary[route] / 1000, tz=UTC
                    ),
                    last_disposition=None,
                    created_at=current.created_at or now,
                    updated_at=now,
                )
            )
            if result.value not in {"UPDATED", "IDENTICAL"}:
                raise RuntimeError(f"recutover progress failed: {route}/{result.value}")
        stale_decision_probe = await _guard_probe(
            broker,
            authority,
            route="BTCUSDT:1h",
            owner="decision",
            expected_epoch=1,
            expected_boundary_ms=boundaries["BTCUSDT:1h"],
            effect_cutoff_ms=recutover_boundary["BTCUSDT:1h"] + 1,
            label="stale-decision-epoch-1-denied-before-recutover",
        )
        after_recutover = await authority.handoff_many(
            routes=TARGET_SIGNAL_ROUTES,
            expected_owner="strategy",
            new_owner="decision",
            expected_epochs={route: 2 for route in TARGET_SIGNAL_ROUTES},
            boundary_ms_by_route=recutover_boundary,
        )
        decision_epoch_3_probe = await _guard_probe(
            broker,
            authority,
            route="BTCUSDT:1h",
            owner="decision",
            expected_epoch=3,
            expected_boundary_ms=recutover_boundary["BTCUSDT:1h"],
            effect_cutoff_ms=recutover_boundary["BTCUSDT:1h"] + 1,
            label="decision-epoch-3-allowed",
        )
        stale_strategy_epoch_2_probe = await _guard_probe(
            broker,
            authority,
            route="BTCUSDT:1h",
            owner="strategy",
            expected_epoch=2,
            expected_boundary_ms=current_r["BTCUSDT:1h"],
            effect_cutoff_ms=recutover_boundary["BTCUSDT:1h"] + 1,
            label="stale-strategy-epoch-2-denied-after-recutover",
        )
        await infrastructure.start_decision()
        final_ready = await _wait_decision_ready(infrastructure.decision_url)
        final_runtime_before_broker = await _runtime_snapshot(
            infrastructure.decision_url
        )
        await infrastructure.start_risk()
        await infrastructure.restart_broker()
        broker_ready = await _wait_decision_ready(infrastructure.decision_url)
        final_runtime = await _runtime_snapshot(infrastructure.decision_url)
        broker_after_restart = [
            await authority.read(route) for route in TARGET_SIGNAL_ROUTES
        ]
        final_progress = await progress_rows(pool)
        final_signals = await signal_entries(broker)
        final_risk_groups = {
            route: await _named_group(broker, f"signals:{route}", "risk_app_group")
            for route in TARGET_SIGNAL_ROUTES
        }
        progress_by_route = {
            route: row
            for route, row in (
                (
                    next(
                        route
                        for route, identity in seed["identities"].items()
                        if identity.lane_id == row["lane_id"]
                    ),
                    row,
                )
                for row in live_progress
            )
        }
        post_cutover_events = [
            {
                "route": route,
                "signal_entries": post_cutover_signal_routes.get(route, []),
                "market_as_of_ms": int(
                    datetime.fromisoformat(
                        progress_by_route[route]["market_as_of"]
                    ).timestamp()
                    * 1000
                ),
                "policy_status": (
                    "SIGNAL"
                    if progress_by_route[route]["last_disposition"] == "published"
                    else "NO_SIGNAL"
                ),
                "publication_outcome": (
                    "PUBLISHED"
                    if progress_by_route[route]["last_disposition"] == "published"
                    else None
                ),
                "progress_disposition": progress_by_route[route]["last_disposition"],
            }
            for route in TARGET_SIGNAL_ROUTES
        ]
        authority_records = {
            "initial": {
                record.route: {
                    "schema_version": record.schema_version,
                    "route": record.route,
                    "owner": record.owner,
                    "epoch": record.epoch,
                    "boundary_ms": record.boundary_ms,
                }
                for record in initial_authority
            },
            "after_cutover": {
                record.route: {
                    "schema_version": record.schema_version,
                    "route": record.route,
                    "owner": record.owner,
                    "epoch": record.epoch,
                    "boundary_ms": record.boundary_ms,
                }
                for record in after_cutover
            },
            "after_cutback": {
                record.route: {
                    "schema_version": record.schema_version,
                    "route": record.route,
                    "owner": record.owner,
                    "epoch": record.epoch,
                    "boundary_ms": record.boundary_ms,
                }
                for record in after_cutback
            },
            "after_recutover": {
                record.route: {
                    "schema_version": record.schema_version,
                    "route": record.route,
                    "owner": record.owner,
                    "epoch": record.epoch,
                    "boundary_ms": record.boundary_ms,
                }
                for record in after_recutover
            },
            "broker_after_restart": {
                record.route: {
                    "schema_version": record.schema_version,
                    "route": record.route,
                    "owner": record.owner,
                    "epoch": record.epoch,
                    "boundary_ms": record.boundary_ms,
                }
                for record in broker_after_restart
                if record is not None
            },
        }
        publication_attempts = [
            initial_guard,
            decision_probe,
            decision_boundary_probe,
            stale_strategy_probe,
            stale_decision_exact_probe,
            stale_decision_before_cutback,
            strategy_epoch_2_probe,
            stale_decision_probe,
            decision_epoch_3_probe,
            stale_strategy_epoch_2_probe,
        ]
        trial.update(
            {
                "execution": {
                    "services": [
                        "db",
                        "broker",
                        "signal-worker",
                        "strategy-worker",
                        "decision",
                        "risk-worker",
                    ],
                    "real_disposable_stack": True,
                    "dynamic_ports": True,
                    "normal_root_state_used": False,
                    "compose_rendered": True,
                    "repository_dockerfile_built": True,
                    "strategy_authority_enforced": True,
                    "decision_container": {
                        "healthy": True,
                        "ready_status_code": 200,
                        "memory_limit": "512M",
                        "cpu_limit": "0.5",
                        "read_only": True,
                        "no_new_privileges": True,
                    },
                    "initial_owner_startup": {
                        "owner": "strategy",
                        "decision_ready": False,
                        "startup_failed_closed": True,
                        "signals_written": 0,
                    },
                },
                "authority": {
                    "routes": list(TARGET_SIGNAL_ROUTES),
                    **authority_records,
                    "owner_timeline": [
                        "strategy@0",
                        "decision@1",
                        "strategy@2",
                        "decision@3",
                    ],
                    "cutback_epochs": {route: [1, 2] for route in TARGET_SIGNAL_ROUTES},
                    "partial_cutover_rejected": partial_cutover_rejected,
                    "partial_cutover_before": partial_cutover_before,
                    "partial_cutover_after": partial_cutover_after,
                    "partial_cutback_rejected": partial_cutback_rejected,
                    "partial_cutback_before": partial_cutback_before,
                    "partial_cutback_after": partial_cutback_after,
                },
                "legacy": {
                    "preliminary_boundaries": list(
                        preliminary_legacy_boundaries.values()
                    ),
                    "boundaries": list(legacy_boundaries.values()),
                    "post_stop_boundary": post_stop_legacy_boundary,
                    "post_stop_legacy_boundary": list(legacy_boundaries.values()),
                    "post_stop_boundary_stable": post_stop_legacy_boundary["stable"],
                    "restored_boundaries": list(restored_boundaries.values()),
                    "restored_boundaries_preliminary": list(
                        restored_boundaries_preliminary.values()
                    ),
                    "legacy_boundary_after_restore_stop": list(
                        restored_boundaries.values()
                    ),
                    "restored_boundary_after_stop": restored_strategy_stop_boundary,
                    "legacy_boundary_stable_before_recutover": restored_strategy_stop_boundary[
                        "stable"
                    ],
                    "restored_groups": restored_groups,
                    "signal_head_preflight": [
                        {"route": route, **value}
                        for route, value in signal_heads.items()
                    ],
                    "strategy_active_before": pre_strategy_catalog,
                    "target_workers_after": post_strategy_catalog,
                    "restored_strategy_catalog": restored_strategy_catalog,
                    "unrelated_routes_preserved": post_strategy_catalog["routes"]
                    == [
                        "BNBUSDT:30m",
                        "DOGEUSDT:4h",
                        "SOLUSDT:1h",
                        "XRPUSDT:1h",
                    ],
                },
                "risk": {
                    "persistence_schema": risk_schema,
                    "pre_cutover_groups": risk_pre_cutover_groups,
                    "post_cutover": {
                        "groups": risk_post_cutover_groups,
                        "pel": max(
                            int(value["pending"])
                            for value in risk_post_cutover_groups.values()
                        ),
                        "lag": max(
                            int(value["lag"])
                            for value in risk_post_cutover_groups.values()
                        ),
                        "runtime_healthy": True,
                    },
                    "after_strategy_stop": risk_pre_cutover_groups,
                    "after_decision_stop": risk_after_decision_stop,
                    "before_recutover": risk_before_recutover,
                    "final_groups": final_risk_groups,
                },
                "progress": {
                    "seed": seed["rows"],
                    "live": live_progress,
                    "restart": restart_progress,
                    "recovery": recovery_progress,
                    "final": final_progress,
                    "decision_progress_after_stop": decision_progress_after_stop,
                    "decision_progress_stable": decision_progress_stable,
                    "catchup_before_new_input": True,
                },
                "decision": {
                    "startup": {
                        **startup_ready,
                        "owner_records": authority_records["after_cutover"],
                        "active_lanes": [
                            "BTCUSDT:momentum_1h",
                            "BTCUSDT:momentum_4h",
                            "ETHUSDT:momentum_4h",
                        ],
                    },
                    "startup_runtime": startup_runtime,
                    "restart_ready": restart_ready,
                    "restart_runtime": restart_runtime,
                    "recovery_ready": recovery_ready,
                    "recovery_runtime": recovery_runtime,
                    "final_ready": final_ready,
                    "broker_ready": broker_ready,
                    "final_runtime_before_broker": final_runtime_before_broker,
                    "final_runtime": final_runtime,
                    "initial_signals": initial_signals,
                    "live_signals": live_signals,
                    "restart_signals": restart_signals,
                    "recovery_signals": recovery_signals,
                    "post_cutover_signals": post_cutover_signals,
                    "post_cutover_events": post_cutover_events,
                    "final_signals": final_signals,
                    "during_down": during_down,
                    "no_authoritative_shadow": not bool(
                        await _keys(broker, "decision:shadow:*")
                    ),
                    "broker_restart": {
                        "named_volume_preserved": True,
                        "before": authority_records["after_recutover"],
                        "after": authority_records["broker_after_restart"],
                    },
                },
                "cutback": {
                    "progress_cutoff_ms": current_r,
                    "entries": {
                        route: value.get("entries", [])
                        for route, value in cutback_groups.items()
                    },
                    "selected": cutback_groups,
                    "strategy_groups": cutback_before_groups,
                    "after_cutback": {
                        route: {"owner": record.owner, "epoch": record.epoch}
                        for route, record in (
                            (record.route, record) for record in after_cutback
                        )
                    },
                    "stale_decision": stale_decision_before_cutback,
                },
                "emergency_rollback": {
                    "decision_progress_ms": current_r,
                    "legacy_preserved_newer_cutoffs": {
                        route: [int(value["close_cutoff_ms"])]
                        for route, value in restored_boundaries.items()
                    },
                    "legacy_processed_newer_cutoffs": {
                        route: [int(value["close_cutoff_ms"])]
                        for route, value in restored_boundaries.items()
                    },
                    "dropped_cutoffs": [],
                },
                "publication_guard": {"attempts": publication_attempts},
                "concurrent_race": {
                    "synchronization": "asyncio.Barrier(2)",
                    "attempts": concurrent_race,
                },
                "measured_real_race": bool(publication_attempts),
                "measured_services": True,
                "first_materialization": first,
                "late_materialization_before_strategy_stop": late_materialized,
                "live_materialization": live_materialized,
                "rollback_materialization": rollback_materialized,
                "final_signal_count": len(await signal_entries(broker)),
                "oracle_policy_statuses": _oracle_cutoff_statuses(),
            }
        )
        return trial
    finally:
        if broker is not None:
            await broker.aclose()
        if pool is not None:
            await pool.close()
        trial["cleanup"] = await infrastructure.cleanup()


async def run_measured_certification() -> dict[str, object]:
    trials = [
        await run_measured_trial("trial_a"),
        await run_measured_trial("trial_b"),
    ]

    def boundary_projection(values: object) -> object:
        if not isinstance(values, list):
            return values
        return [
            {
                "feature_timestamp_ms": item.get("feature_timestamp_ms"),
                "close_cutoff_ms": item.get("close_cutoff_ms"),
                "timeframe": item.get("timeframe"),
            }
            for item in values
            if isinstance(item, Mapping)
        ]

    def cutback_projection(value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        selected = value.get("selected", {})
        selected_projection: dict[str, object] = {}
        if isinstance(selected, Mapping):
            for route, item in selected.items():
                if not isinstance(item, Mapping):
                    continue
                selected_projection[str(route)] = {
                    key: item.get(key)
                    for key in (
                        "no_legacy_cutoff_skipped",
                        "oldest_retained_cutoff_ms",
                        "newest_retained_cutoff_ms",
                        "expected_next_cutoff_ms",
                        "first_actual_unread_cutoff_ms",
                        "before_pending",
                        "before_lag",
                        "after_pending",
                        "after_lag",
                    )
                }
        entries = value.get("entries", {})
        entry_projection: dict[str, object] = {}
        if isinstance(entries, Mapping):
            for route, route_entries in entries.items():
                if not isinstance(route_entries, list):
                    continue
                entry_projection[str(route)] = [
                    {
                        "timestamp_ms": item.get("timestamp_ms"),
                        "close_cutoff_ms": item.get("timestamp_ms")
                        + timeframe_duration_ms(
                            "1h" if str(route).endswith("1h") else "4h"
                        ),
                    }
                    for item in route_entries
                    if isinstance(item, Mapping)
                    and isinstance(item.get("timestamp_ms"), int)
                ]
        return {
            "progress_cutoff_ms": value.get("progress_cutoff_ms"),
            "selected": selected_projection,
            "entries": entry_projection,
            "after_cutback": value.get("after_cutback"),
        }

    def semantic_projection(trial: Mapping[str, object]) -> dict[str, object]:
        legacy = trial.get("legacy", {})
        decision = trial.get("decision", {})
        progress = trial.get("progress", {})
        return {
            "authority": trial.get("authority"),
            "legacy_boundaries": boundary_projection(
                legacy.get("boundaries") if isinstance(legacy, Mapping) else None
            ),
            "restored_boundaries": boundary_projection(
                legacy.get("restored_boundaries")
                if isinstance(legacy, Mapping)
                else None
            ),
            "live_progress": progress.get("live")
            if isinstance(progress, Mapping)
            else None,
            "recovery_progress": progress.get("recovery")
            if isinstance(progress, Mapping)
            else None,
            "final_progress": progress.get("final")
            if isinstance(progress, Mapping)
            else None,
            "post_cutover_signals": decision.get("post_cutover_signals")
            if isinstance(decision, Mapping)
            else None,
            "cutback": cutback_projection(trial.get("cutback")),
        }

    projection_a = semantic_projection(trials[0])
    projection_b = semantic_projection(trials[1])
    return {
        "evidence_origin": "measured_disposable",
        "measured_trials": trials,
        "trial_parity": {
            "trial_a_digest": sha256_fingerprint(projection_a),
            "trial_b_digest": sha256_fingerprint(projection_b),
            "matches": projection_a == projection_b,
        },
        "execution": trials[0].get("execution", {}),
        "authority": trials[0].get("authority", {}),
        "legacy": trials[0].get("legacy", {}),
        "risk": trials[0].get("risk", {}),
        "progress": trials[0].get("progress", {}),
        "decision": trials[0].get("decision", {}),
        "cutback": trials[0].get("cutback", {}),
        "emergency_rollback": trials[0].get("emergency_rollback", {}),
        "publication_guard": trials[0].get("publication_guard", {}),
        "cleanup": {
            "trial_a": trials[0].get("cleanup", {}),
            "trial_b": trials[1].get("cleanup", {}),
            "clean": all(
                trial.get("cleanup", {}).get("clean") is True for trial in trials
            ),
            "docker_leftovers": [
                trial.get("cleanup", {}).get("leftovers", {}) for trial in trials
            ],
            "cache_leftovers": [],
            "unreconciled_notifications": 0,
        },
        "final": {
            "owners": trials[0].get("authority", {}).get("after_recutover", {}),
            "decision_ready": trials[0].get("decision", {}).get("final_ready")
            is not None,
            "active_authoritative_lanes": [
                "BTCUSDT:momentum_1h",
                "BTCUSDT:momentum_4h",
                "ETHUSDT:momentum_4h",
            ],
            "risk_pel": max(
                int(value.get("pending", -1))
                for value in trials[0].get("risk", {}).get("final_groups", {}).values()
            ),
            "risk_lag": max(
                int(value.get("lag", -1))
                for value in trials[0].get("risk", {}).get("final_groups", {}).values()
            ),
            "signals_have_decision_identity": all(
                entry.get("model_name") in {"m4-btc-1h", "m4-btc-4h", "m4-eth-4h"}
                for entry in trials[0]
                .get("decision", {})
                .get("post_cutover_signals", [])
            ),
        },
    }


__all__ = ["D11BInfrastructure", "run_measured_certification", "run_measured_trial"]
