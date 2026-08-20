"""Measured disposable D11C default-topology certification.

The trial deliberately uses the real repository processes and the same
authority/effect-progress primitives as D11B.  The fixture is isolated by
Compose project, ports, and named volumes; no ordinary root runtime state is
used.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import valkey.asyncio as valkey
import yaml

from apps.decision_app.storage.shadow_progress import LaneEffectProgressRepository
from apps.ingestion_app.publication.publisher import OutboxPublisher
from apps.ingestion_app.services.candle_ingestion import (
    CandleIngestionService,
    canonicalize_observation,
)
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.settings import PublicationSettings
from apps.ingestion_app.storage.repository import CandleRepository
from libs.common.asset_manifest import (
    AssetLifecycleEvent,
    AssetLifecycleEventType,
    AssetManifestStore,
)
from libs.common.signal_authority import (
    TARGET_SIGNAL_ROUTES,
    SignalAuthorityStore,
    signal_authority_key,
)
from libs.contracts.serialization import valkey_decode
from libs.contracts.signal import FeatureVector
from scripts.decision_d11b_authority_cutover import (
    D11BAuthorityController,
    cutback_fast_forward_boundary,
    feature_close_cutoff_ms,
    market_bar_identity_fingerprint,
)
from tests.combined import d11b_real
from tests.combined.c4a_harness import (
    _cleanup_probe,
    _free_port,
    _manifest,
    _run,
)
from tests.combined.d11a_harness import progress_rows, signal_entries

ROOT = Path(__file__).resolve().parents[2]
D11C_COMPOSE_FILE = ROOT / "tests/combined/fixtures/d11c/docker-compose.yml"
TARGET_FEATURE_ROUTES = d11b_real.TARGET_FEATURE_ROUTES
ROUTE_TIMEFRAMES = dict(TARGET_FEATURE_ROUTES)
ALL_STRATEGY_ROUTES = (
    "BNBUSDT:30m",
    "BTCUSDT:1h",
    "BTCUSDT:4h",
    "DOGEUSDT:1h",
    "DOGEUSDT:4h",
    "ETHUSDT:4h",
    "SOLUSDT:1h",
    "XRPUSDT:1h",
)
UNRELATED_STRATEGY_ROUTES = tuple(
    route for route in ALL_STRATEGY_ROUTES if route not in TARGET_SIGNAL_ROUTES
)
ALL_SERVICES = (
    "db",
    "broker",
    "ingestion",
    "signal-worker",
    "strategy-worker",
    "decision",
    "risk-worker",
    "execution-worker",
)


def _free_ports(count: int) -> tuple[int, ...]:
    ports: list[int] = []
    while len(ports) < count:
        value = _free_port()
        if value not in ports:
            ports.append(value)
    return tuple(ports)


@dataclass(slots=True)
class D11CInfrastructure:
    trial_name: str
    db_port: int = field(init=False)
    broker_port: int = field(init=False)
    ingestion_port: int = field(init=False)
    decision_port: int = field(init=False)
    project_name: str = field(init=False)

    def __post_init__(self) -> None:
        (
            self.db_port,
            self.broker_port,
            self.ingestion_port,
            self.decision_port,
        ) = _free_ports(4)
        token = re.sub(r"[^A-Za-z0-9_]", "_", self.trial_name)
        self.project_name = f"flipper_d11c_{os.getpid()}_{token}"

    @property
    def environment(self) -> dict[str, str]:
        values = os.environ.copy()
        values.update(
            {
                "D11C_DB_PORT": str(self.db_port),
                "D11C_BROKER_PORT": str(self.broker_port),
                "D11C_INGESTION_PORT": str(self.ingestion_port),
                "D11C_DECISION_PORT": str(self.decision_port),
                "COMPOSE_PROJECT_NAME": self.project_name,
                "COMPOSE_DISABLE_ENV_FILE": "1",
                "OTEL_SDK_DISABLED": "true",
            }
        )
        return values

    def command(self, *arguments: str) -> list[str]:
        return [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            str(D11C_COMPOSE_FILE),
            "-p",
            self.project_name,
            *arguments,
        ]

    async def compose(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return await asyncio.to_thread(
            _run,
            self.command(*arguments),
            env=self.environment,
        )

    async def up(self, *services: str, build: bool = False, wait: bool = False) -> None:
        arguments = ["up", "-d"]
        if build:
            arguments.append("--build")
        if wait:
            arguments.append("--wait")
        arguments.extend(services)
        result = await self.compose(*arguments)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)

    async def start_foundation(self) -> None:
        await self.up("db", "broker", build=False, wait=True)

    async def start_ingestion(self) -> None:
        await self.up("ingestion", build=True, wait=True)

    async def stop_ingestion(self) -> None:
        result = await self.compose("stop", "ingestion")
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)

    async def start_support(self) -> None:
        await self.up(
            "signal-worker",
            "risk-worker",
            "execution-worker",
            build=True,
        )

    async def start_signal(self) -> None:
        await self.up("signal-worker", build=True)

    async def stop_signal(self) -> None:
        result = await self.compose("stop", "signal-worker")
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)

    async def start_strategy(self) -> None:
        await self.up("strategy-worker", build=True)

    async def stop_strategy(self) -> None:
        result = await self.compose("stop", "strategy-worker")
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)

    async def restart_strategy(self) -> None:
        await self.stop_strategy()
        await self.start_strategy()

    async def start_decision(self) -> None:
        await self.up("decision", build=True, wait=True)

    async def start_decision_unseeded(self) -> None:
        await self.up("decision", build=True, wait=False)

    async def stop_decision(self) -> None:
        result = await self.compose("stop", "decision")
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)

    async def restart_decision(self) -> None:
        await self.stop_decision()
        await self.start_decision()

    async def stop_all(self) -> None:
        result = await self.compose("stop", *ALL_SERVICES)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)

    async def cold_restart(self) -> dict[str, bool]:
        await self.stop_all()
        # Decision is a default service in the disposable D11C topology.  Do
        # not select it explicitly here: this is the real profile-free root
        # startup proof.
        await self.up(build=True, wait=True)
        return {"default_root_start": True}

    async def logs(self, service: str) -> str:
        result = await self.compose("logs", "--no-color", service)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        return result.stdout

    async def stats(self, stage: str) -> dict[str, object]:
        samples: dict[str, object] = {}
        for service in ALL_SERVICES:
            ps = await self.compose("ps", "-a", "-q", service)
            container_id = ps.stdout.strip()
            if not container_id:
                samples[service] = {"running": False, "stage": stage}
                continue
            result = await asyncio.to_thread(
                _run,
                [
                    "docker",
                    "stats",
                    "--no-stream",
                    "--format",
                    "{{json .}}",
                    container_id,
                ],
                env=self.environment,
            )
            inspect = await asyncio.to_thread(
                _run,
                ["docker", "inspect", container_id],
                env=self.environment,
            )
            payload: object = {}
            if result.returncode == 0 and result.stdout.strip():
                payload = json.loads(result.stdout.strip().splitlines()[0])
            metadata: object = {}
            restart_count: object = None
            if inspect.returncode == 0 and inspect.stdout.strip():
                inspect_payload = json.loads(inspect.stdout)[0]
                metadata = inspect_payload.get("State", {})
                restart_count = inspect_payload.get("RestartCount")
            samples[service] = {
                "stage": stage,
                "container_id": container_id,
                "stats": payload,
                "state": metadata,
                "restart_count": restart_count,
                "running": isinstance(metadata, Mapping)
                and metadata.get("Running") is True,
            }
        return samples

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
        return f"postgresql://d11c_user:d11c_password@127.0.0.1:{self.db_port}/d11c_db"

    @property
    def valkey_uri(self) -> str:
        return f"redis://127.0.0.1:{self.broker_port}/0"

    @property
    def decision_url(self) -> str:
        return f"http://127.0.0.1:{self.decision_port}"


async def _seed_all_manifests(broker: Any) -> None:
    store = AssetManifestStore(broker)
    manifest_timeframes = {
        "BTC": ("1m", "1h", "4h"),
        "ETH": ("1m", "4h"),
        "DOGE": ("1m", "1h", "4h"),
        "XRP": ("1m", "1h"),
        "SOL": ("1m", "1h"),
        "BNB": ("1m", "30m"),
    }
    for symbol, timeframes in manifest_timeframes.items():
        manifest, timeframe_manifests = _manifest(symbol, timeframes)
        await store.sync_manifest(manifest, timeframe_manifests)


async def _active_strategy_routes(broker: Any) -> list[str]:
    active: list[str] = []
    for route in ALL_STRATEGY_ROUTES:
        asset, timeframe = route.split(":", 1)
        try:
            consumers = await broker.xinfo_consumers(
                f"features:{route}", d11b_real.GROUP_NAME
            )
        except Exception:  # noqa: BLE001, S112 - absent stream/group is inactive
            continue
        expected_name = f"strategy_worker_{asset}_{timeframe}"
        for consumer in consumers:
            name = d11b_real._group_value(consumer, "name", "")
            idle = d11b_real._group_value(consumer, "idle", None)
            try:
                is_recent = int(idle) <= 5_000
            except (TypeError, ValueError):
                is_recent = False
            if name == expected_name and is_recent:
                active.append(route)
                break
    return active


async def _wait_active_strategy_routes(
    broker: Any, expected: set[str], *, label: str
) -> list[str]:
    async def probe() -> list[str] | None:
        active = await _active_strategy_routes(broker)
        return active if expected.issubset(active) else None

    return await d11b_real._wait_for(probe, timeout=180, label=label)


async def _wait_exact_active_strategy_routes(
    broker: Any, expected: set[str], *, label: str
) -> list[str]:
    async def probe() -> list[str] | None:
        active = await _active_strategy_routes(broker)
        return active if set(active) == expected else None

    return await d11b_real._wait_for(probe, timeout=180, label=label)


async def _signal_input_quiescence(
    broker: Any,
) -> dict[str, dict[str, object]] | None:
    """Read all real Signal source groups and require them fully drained."""

    snapshots: dict[str, dict[str, object]] = {}
    async for raw_key in broker.scan_iter(match="stream:ohlcv:ingestion:*"):
        stream_key = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
        try:
            groups = await broker.xinfo_groups(stream_key)
        except Exception:  # noqa: BLE001, S112 - stream may disappear between scans
            continue
        for raw_group in groups:
            group_name = d11b_real._group_value(raw_group, "name", "")
            if group_name != "signal_app_group":
                continue
            snapshots[stream_key] = {
                "exists": True,
                "pending": int(d11b_real._group_value(raw_group, "pending", -1)),
                "lag": int(d11b_real._group_value(raw_group, "lag", -1)),
                "last_delivered_id": str(
                    d11b_real._group_value(raw_group, "last-delivered-id", "0-0")
                ),
            }
    if not snapshots or any(
        value["pending"] != 0 or value["lag"] != 0 for value in snapshots.values()
    ):
        return None
    return snapshots


async def _wait_target_feature_quiescence_stable(
    broker: Any, *, label: str, timeout: float = 60
) -> dict[str, dict[str, object]]:
    """Drain late feature rows after the Signal producer has stopped."""

    previous: dict[str, dict[str, object]] | None = None

    async def probe() -> dict[str, dict[str, object]] | None:
        nonlocal previous
        current = await d11b_real._wait_feature_quiescence(broker)
        if current is None:
            previous = None
            return None
        if current == previous:
            return current
        previous = current
        return None

    return await d11b_real._wait_for(probe, timeout=timeout, label=label)


async def _wait_legacy_producer_quiescence(
    broker: Any, *, label: str, timeout: float = 240
) -> dict[str, object]:
    """Require stable Signal inputs and stable target feature-group drains."""

    previous: dict[str, object] | None = None

    async def probe() -> dict[str, object] | None:
        nonlocal previous
        feature_groups = await d11b_real._wait_feature_quiescence(broker)
        signal_groups = await _signal_input_quiescence(broker)
        if feature_groups is None or signal_groups is None:
            previous = None
            return None
        current = {
            "feature_groups": feature_groups,
            "signal_input_groups": signal_groups,
        }
        if current == previous:
            return current
        previous = current
        return None

    return await d11b_real._wait_for(probe, timeout=timeout, label=label)


async def _legacy_feature_snapshot(broker: Any) -> dict[str, object]:
    """Capture bounded raw feature-stream evidence before cutback SETID."""

    snapshot: dict[str, object] = {}
    for route, timeframe in TARGET_FEATURE_ROUTES:
        stream_key = f"features:{route}"
        group = await d11b_real._group(broker, stream_key)
        raw_entries = await broker.xrange(stream_key, "-", "+")
        entries: list[dict[str, object]] = []
        for raw_id, fields in raw_entries:
            entry_id = raw_id.decode() if isinstance(raw_id, bytes) else str(raw_id)
            vector = valkey_decode(dict(fields), FeatureVector)
            entries.append(
                {
                    "id": entry_id,
                    "timestamp_ms": int(vector.timestamp),
                    "close_cutoff_ms": feature_close_cutoff_ms(
                        int(vector.timestamp), timeframe
                    ),
                    "asset": vector.asset,
                    "timeframe": vector.timeframe,
                    "bar_data": dict(vector.bar_data),
                    "bar_identity_fingerprint": market_bar_identity_fingerprint(
                        {
                            "asset": vector.asset,
                            "timeframe": vector.timeframe,
                            "timestamp_ms": int(vector.timestamp),
                            "bar_data": dict(vector.bar_data),
                        }
                    ),
                }
            )
        snapshot[route] = {
            "group": group,
            "stream_length": len(entries),
            "first": entries[0] if entries else None,
            "last": entries[-1] if entries else None,
            "entries": entries,
        }
    return snapshot


async def _wait_outbox_empty(pool: asyncpg.Pool) -> dict[str, object]:
    async def probe() -> dict[str, object] | None:
        pending = int(
            await pool.fetchval(
                "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
            )
        )
        return {"pending": pending} if pending == 0 else None

    return await d11b_real._wait_for(probe, timeout=180, label="D11C outbox drain")


async def _baseline_seed_outbox(pool: asyncpg.Pool) -> int:
    """Close seed-only outbox rows before live producer windows begin."""

    result = await pool.execute(
        """
        UPDATE ingestion.outbox
        SET published_at = $1
        WHERE published_at IS NULL
        """,
        datetime(2030, 1, 1, tzinfo=UTC),
    )
    return int(str(result).rsplit(" ", 1)[-1])


async def _drain_outbox_bounded(pool: asyncpg.Pool, broker: Any) -> dict[str, int]:
    publisher = OutboxPublisher(
        repository=CandleRepository(pool),
        valkey_client=broker,
        publication=PublicationSettings(
            batch_size=1000,
            idle_sleep_seconds=1,
            error_backoff_seconds=1,
            stream_maxlen=10_000,
            stream_approximate=False,
        ),
        now_fn=lambda: datetime(2030, 1, 1, tzinfo=UTC),
    )
    attempts = 0
    published = 0
    while attempts < 100:
        attempts += 1
        published += await publisher.publish_once()
        pending = int(
            await pool.fetchval(
                "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
            )
        )
        if pending == 0:
            return {"attempts": attempts, "published": published}
    raise RuntimeError("D11C outbox did not drain within 100 bounded batches")


async def _materialize_window_no_drain(
    pool: asyncpg.Pool,
    config: Any,
    *,
    bucket_start: datetime,
    index_offset: int,
    count: int,
) -> dict[str, object]:
    repository = CandleRepository(pool)
    ingestion = CandleIngestionService(repository)
    htf = HTFAggregationService(repository=repository, ingestion_service=ingestion)
    assets = {"BTC": ("1h", "4h"), "ETH": ("4h",)}
    counts: dict[str, int] = {}
    for asset, timeframes in assets.items():
        inserted = 0
        for index in range(count):
            absolute_index = index_offset + index
            observation = d11b_real._d11b_provider_observation(
                asset=asset,
                opened=bucket_start + timedelta(minutes=absolute_index),
                index=absolute_index,
            )
            status = await ingestion.commit_observation(observation)
            if status.value == "conflict":
                raise AssertionError(f"unexpected {asset} canonical conflict")
            if status.value == "inserted":
                inserted += 1
            await htf.process_base_candle(
                canonicalize_observation(observation),
                base_duration=timedelta(minutes=1),
                target_durations={
                    timeframe: config.timeframe_grid.duration(timeframe)
                    for timeframe in timeframes
                },
                alignment_origin=config.timeframe_grid.alignment_origin,
            )
        counts[asset] = inserted
    return {"base_inserted": counts}


async def _wait_strategy_catalog(
    infrastructure: D11CInfrastructure, expected_count: int = 8
) -> dict[str, object]:
    return await d11b_real._wait_strategy_catalog(infrastructure, expected_count)


async def _wait_decision_ready(infrastructure: D11CInfrastructure) -> dict[str, object]:
    return await d11b_real._wait_decision_ready(infrastructure.decision_url)


async def _wait_decision_not_ready(
    infrastructure: D11CInfrastructure, *, label: str
) -> dict[str, object]:
    async def probe() -> dict[str, object] | None:
        try:
            status, payload = await d11b_real.http_json(
                infrastructure.decision_url, "/health/ready"
            )
        except OSError:
            sample = (await infrastructure.stats("readiness_probe")).get("decision")
            state = sample.get("state") if isinstance(sample, Mapping) else None
            if (
                isinstance(sample, Mapping)
                and sample.get("running") is False
                and isinstance(state, Mapping)
                and state.get("Status") in {"exited", "dead"}
            ):
                return {
                    "status_code": None,
                    "payload": {},
                    "ready": False,
                    "container_running": False,
                    "startup_failed_closed": True,
                }
            return None
        if status == 200 and payload.get("status") == "ready":
            return None
        return {
            "status_code": status,
            "payload": payload,
            "ready": False,
            "container_running": True,
            "startup_failed_closed": False,
        }

    return await d11b_real._wait_for(probe, timeout=90, label=label)


async def _raw_authority_hash(broker: Any, route: str) -> dict[str, str]:
    raw = await broker.hgetall(signal_authority_key(route))
    return {
        (key.decode() if isinstance(key, bytes) else str(key)): (
            value.decode() if isinstance(value, bytes) else str(value)
        )
        for key, value in raw.items()
    }


def _authority_record_payload(record: object) -> dict[str, object] | None:
    if record is None:
        return None
    return {
        "owner": record.owner,
        "epoch": record.epoch,
        "boundary_ms": record.boundary_ms,
        "schema_version": record.schema_version,
        "route": record.route,
    }


async def _authority_payload(authority: SignalAuthorityStore) -> dict[str, object]:
    return {
        route: _authority_record_payload(await authority.read(route))
        for route in TARGET_SIGNAL_ROUTES
    }


async def _strategy_lifecycle_event(
    broker: Any,
    symbol: str,
    *,
    action: str = "resume",
    event_type: AssetLifecycleEventType = AssetLifecycleEventType.ASSET_RESUMED,
    command_type: str = "RESUME_ASSET",
    desired_state: str = "LIVE",
    enabled: bool = True,
) -> tuple[str, str]:
    event = AssetLifecycleEvent(
        event_id=f"d11c-{symbol.lower()}-{action}",
        event_type=event_type,
        command_type=command_type,
        symbol=symbol,
        publish_timeframes=["1h", "4h"],
        timeframes=["1m", "1h", "4h"],
        enabled=enabled,
        desired_state=desired_state,
        emitted_at=datetime.now(UTC).timestamp(),
        source="ingestion",
        requested_by="ingestion",
        reason="D11C lifecycle admission probe",
    )
    stream_id = await AssetManifestStore(broker).publish_event(event)
    return event.event_id, str(stream_id)


async def _wait_service_stopped(
    infrastructure: D11CInfrastructure, service: str, *, label: str
) -> dict[str, object]:
    async def probe() -> dict[str, object] | None:
        samples = await infrastructure.stats(label)
        sample = samples.get(service)
        return (
            sample
            if isinstance(sample, Mapping) and sample.get("running") is False
            else None
        )

    return await d11b_real._wait_for(probe, timeout=60, label=label)


async def _materialize_and_publish(
    infrastructure: D11CInfrastructure,
    pool: asyncpg.Pool,
    broker: Any,
    config: Any,
    *,
    bucket_start: datetime,
    index_offset: int,
    count: int,
) -> dict[str, object]:
    """Use the real ingestion service between deterministic producer windows.

    The repository producer is the already-certified CandleIngestionService;
    stopping its resident outbox loop for the bounded write window avoids two
    publishers racing on the same durable row.  The actual OutboxPublisher
    then drains the rows before the service is brought back healthy.
    """

    await infrastructure.stop_ingestion()
    try:
        await _materialize_window_no_drain(
            pool,
            config,
            bucket_start=bucket_start,
            index_offset=index_offset,
            count=count,
        )
        outbox = await _drain_outbox_bounded(pool, broker)
    finally:
        await infrastructure.start_ingestion()
    return outbox


@dataclass(slots=True)
class _TrialContext:
    infrastructure: D11CInfrastructure
    pool: Any
    broker: Any
    config: Any
    authority: SignalAuthorityStore
    bucket_start: datetime
    seed: dict[str, object] | None = None
    controller: D11BAuthorityController | None = None


async def _run_unseeded_phase(context: _TrialContext) -> dict[str, object]:
    """Measure unseeded/corrupt admission and establish Strategy epoch zero."""

    infrastructure = context.infrastructure
    broker = context.broker
    authority = context.authority
    await infrastructure.start_strategy()
    catalog = await _wait_strategy_catalog(infrastructure)
    unseeded_active = await _wait_active_strategy_routes(
        broker,
        set(UNRELATED_STRATEGY_ROUTES),
        label="D11C unseeded unrelated Strategy admission",
    )
    unseeded_authority = await _authority_payload(authority)
    await infrastructure.start_decision_unseeded()
    unseeded_decision = await _wait_decision_not_ready(
        infrastructure, label="D11C unseeded Decision fail-closed readiness"
    )
    await infrastructure.stop_decision()
    unseeded_authority_after = await _authority_payload(authority)
    unseeded = {
        "authority_records": unseeded_authority,
        "catalog": catalog,
        "active_routes": unseeded_active,
        "target_routes_blocked": not set(TARGET_SIGNAL_ROUTES) & set(unseeded_active),
        "unrelated_routes_active": set(UNRELATED_STRATEGY_ROUTES).issubset(
            unseeded_active
        ),
        "target_signal_count": len(await signal_entries(broker)),
        "decision_attempt": {
            **unseeded_decision,
            "authority_records_after": unseeded_authority_after,
        },
    }

    await authority.seed_strategy()
    await broker.hset(
        signal_authority_key("ETHUSDT:4h"),
        mapping={"owner": "corrupt"},
    )
    await infrastructure.restart_strategy()
    corrupt_active = await _wait_active_strategy_routes(
        broker,
        set(UNRELATED_STRATEGY_ROUTES) | {"BTCUSDT:1h", "BTCUSDT:4h"},
        label="D11C corrupt-route isolation",
    )
    await infrastructure.start_decision_unseeded()
    corrupt_decision = await _wait_decision_not_ready(
        infrastructure, label="D11C corrupt-authority Decision fail-closed readiness"
    )
    await infrastructure.stop_decision()
    corrupt_raw = await _raw_authority_hash(broker, "ETHUSDT:4h")
    corrupt = {
        "corrupt_route": "ETHUSDT:4h",
        "active_routes": corrupt_active,
        "corrupt_route_blocked": "ETHUSDT:4h" not in corrupt_active,
        "unrelated_routes_active": set(UNRELATED_STRATEGY_ROUTES).issubset(
            corrupt_active
        ),
        "decision_attempt": corrupt_decision,
        "authority_repaired": corrupt_raw.get("owner") != "corrupt",
    }

    await broker.delete(signal_authority_key("ETHUSDT:4h"))
    await authority.seed_strategy()
    await infrastructure.restart_strategy()
    strategy_zero_active = await _wait_active_strategy_routes(
        broker,
        set(ALL_STRATEGY_ROUTES),
        label="D11C Strategy epoch-0 admission",
    )
    return {
        "catalog": catalog,
        "unseeded": unseeded,
        "missing_corrupt_isolation": corrupt,
        "authority": {"strategy_epoch_0": await _authority_payload(authority)},
        "strategy_admission": {
            "strategy_epoch_0_active": strategy_zero_active,
            "all_eight_admitted": set(strategy_zero_active) == set(ALL_STRATEGY_ROUTES),
        },
        "resources_strategy_zero": await infrastructure.stats("strategy0"),
    }


async def _run_decision_epoch_one_and_cold_restart(
    context: _TrialContext,
    strategy_epoch_zero: Mapping[str, object],
) -> dict[str, object]:
    """Measure controller cutover, Decision flow, restart, and cold startup."""

    infrastructure = context.infrastructure
    pool = context.pool
    broker = context.broker
    config = context.config
    authority = context.authority
    await _materialize_and_publish(
        infrastructure,
        pool,
        broker,
        config,
        bucket_start=context.bucket_start,
        index_offset=0,
        count=300,
    )
    await _wait_outbox_empty(pool)
    await d11b_real._wait_for(
        lambda: d11b_real._wait_feature_progress(broker),
        timeout=180,
        label="D11C strategy feature progress",
    )
    await d11b_real._wait_for(
        lambda: d11b_real._wait_feature_quiescence(broker),
        timeout=240,
        label="D11C Strategy epoch-0 feature quiescence",
    )
    await infrastructure.stop_strategy()
    await _wait_service_stopped(
        infrastructure, "strategy-worker", label="D11C Strategy stop"
    )
    legacy_boundary = await d11b_real._stable_target_feature_boundaries(broker)
    boundaries = {
        route: int(value["close_cutoff_ms"])
        for route, value in legacy_boundary["final"].items()
    }
    await d11b_real._wait_for(
        lambda: d11b_real._wait_risk_quiescence(broker),
        timeout=180,
        label="D11C risk quiescence before cutover",
    )
    seed = await d11b_real._seed_effect_progress(pool, boundaries)
    context.seed = seed
    controller = D11BAuthorityController(
        authority,
        progress_repository=LaneEffectProgressRepository(pool),
        identities=seed["identities"],
    )
    context.controller = controller
    handoff_one = await controller.cutover_to_decision(
        expected_epochs={route: 0 for route in TARGET_SIGNAL_ROUTES},
        boundary_ms_by_route=boundaries,
    )
    authority_evidence = {
        "strategy_epoch_0": strategy_epoch_zero,
        "decision_epoch_1": {
            record.route: _authority_record_payload(record) for record in handoff_one
        },
    }
    await infrastructure.start_decision()
    decision_ready = await _wait_decision_ready(infrastructure)
    decision_runtime = await d11b_real._runtime_snapshot(infrastructure.decision_url)
    resources_decision_one = await infrastructure.stats("decision1")
    live_before = await signal_entries(broker)
    await _materialize_and_publish(
        infrastructure,
        pool,
        broker,
        config,
        bucket_start=context.bucket_start,
        index_offset=300,
        count=240,
    )
    await _wait_outbox_empty(pool)
    await d11b_real._wait_for(
        lambda: d11b_real._wait_effect_progress(
            pool, datetime.fromtimestamp(0, tz=UTC)
        ),
        timeout=240,
        label="D11C Decision progress",
    )
    live_after = await signal_entries(broker)
    live_progress = await progress_rows(pool)
    risk_live = await d11b_real._wait_for(
        lambda: d11b_real._wait_risk_quiescence(broker),
        timeout=180,
        label="D11C risk quiescence after Decision flow",
    )
    flow = {
        "decision_ready": decision_ready,
        "decision_runtime": decision_runtime,
        "signals_before": len(live_before),
        "signals_after": len(live_after),
        "decision_signal_delta": d11b_real._signal_delta(live_before, live_after),
        "progress": live_progress,
        "risk_groups": risk_live,
    }
    await infrastructure.restart_decision()
    restart_ready = await _wait_decision_ready(infrastructure)
    restart = {
        "ready": restart_ready,
        "progress": await progress_rows(pool),
        "signals": len(await signal_entries(broker)),
    }
    resources_before_cold_restart = await infrastructure.stats("decision1")
    pre_cold_restart_feature_streams = await _legacy_feature_snapshot(broker)
    cold_start = await infrastructure.cold_restart()
    cold_ready = await _wait_decision_ready(infrastructure)
    post_cold_restart_feature_streams = await _legacy_feature_snapshot(broker)
    cold_restart = {
        "ready": cold_ready,
        **cold_start,
        "owners": await _authority_payload(authority),
        "progress": await progress_rows(pool),
        "feature_streams": post_cold_restart_feature_streams,
        "risk_groups": await d11b_real._wait_for(
            lambda: d11b_real._wait_risk_quiescence(broker),
            timeout=180,
            label="D11C risk quiescence after cold restart",
        ),
    }
    return {
        "authority": authority_evidence,
        "controller_cutover": controller.last_observation,
        "flow": flow,
        "restart": restart,
        "resources_decision1": resources_decision_one,
        "resources_before_cold_restart": resources_before_cold_restart,
        "pre_cold_restart_feature_streams": pre_cold_restart_feature_streams,
        "resources_cold_restart": await infrastructure.stats("cold_restart"),
        "cold_restart": cold_restart,
    }


async def _run_cutback_and_recutover(
    context: _TrialContext,
) -> dict[str, object]:
    """Measure rollback, lifecycle admission, and Decision epoch three."""

    infrastructure = context.infrastructure
    pool = context.pool
    broker = context.broker
    config = context.config
    authority = context.authority
    seed = context.seed
    controller = context.controller
    if not isinstance(seed, Mapping) or controller is None:
        raise RuntimeError("D11C cutback requires seeded controller context")
    await infrastructure.stop_decision()
    await _wait_service_stopped(infrastructure, "decision", label="D11C Decision stop")
    await infrastructure.stop_strategy()
    await _wait_service_stopped(
        infrastructure, "strategy-worker", label="D11C Strategy cutback stop"
    )
    stable_progress = await d11b_real._stable_progress_rows(pool)
    identities = seed["identities"]
    current_r = d11b_real._progress_cutoffs(stable_progress["final"], identities)
    cutback_preflight = await _legacy_feature_snapshot(broker)
    logical_analysis: dict[str, object] = {}
    for route, timeframe in TARGET_FEATURE_ROUTES:
        value = cutback_preflight[route]
        if not isinstance(value, Mapping):
            raise TypeError(f"missing feature snapshot for {route}")
        logical_analysis[route] = cutback_fast_forward_boundary(
            value["entries"],
            progress_cutoff_ms=current_r[route],
            timeframe=timeframe,
        )
    cutback_preflight["logical_analysis"] = logical_analysis
    handoff_two = await controller.cutback_to_strategy(
        expected_epochs={route: 1 for route in TARGET_SIGNAL_ROUTES},
        progress_cutoff_ms_by_route=current_r,
        boundary_ms_by_route=current_r,
        timeframe_by_route=ROUTE_TIMEFRAMES,
    )
    controller_cutback_observation = dict(controller.last_observation)
    cutback_groups = controller_cutback_observation.get("groups", {})
    await infrastructure.start_strategy()
    strategy_two_active = await _wait_active_strategy_routes(
        broker,
        set(ALL_STRATEGY_ROUTES),
        label="D11C Strategy epoch-2 admission",
    )
    resources_strategy_two = await infrastructure.stats("strategy2")

    await _materialize_and_publish(
        infrastructure,
        pool,
        broker,
        config,
        bucket_start=context.bucket_start,
        index_offset=540,
        count=240,
    )
    await _wait_outbox_empty(pool)
    rollback_quiescence = await _wait_legacy_producer_quiescence(
        broker,
        timeout=240,
        label="D11C Strategy rollback backlog",
    )
    rollback_groups = rollback_quiescence["feature_groups"]
    rollback_signal_groups = rollback_quiescence["signal_input_groups"]

    lifecycle_active_before_stop = await _wait_active_strategy_routes(
        broker,
        set(ALL_STRATEGY_ROUTES),
        label="D11C lifecycle pre-stop Strategy admission",
    )
    stop_event_id, stop_stream_id = await _strategy_lifecycle_event(
        broker,
        "BTCUSDT",
        action="stop",
        event_type=AssetLifecycleEventType.ASSET_STOPPED,
        command_type="STOP_ASSET",
        desired_state="STOPPED",
        enabled=False,
    )
    await d11b_real._wait_for(
        lambda: broker.exists(f"strategy:lifecycle:event:{stop_event_id}"),
        timeout=60,
        label="D11C lifecycle strategy stop processing",
    )
    lifecycle_active_after_stop = await _wait_exact_active_strategy_routes(
        broker,
        set(ALL_STRATEGY_ROUTES) - {"BTCUSDT:1h", "BTCUSDT:4h"},
        label="D11C lifecycle Strategy target removal",
    )
    rollback_event_id, rollback_stream_id = await _strategy_lifecycle_event(
        broker, "BTCUSDT"
    )
    await d11b_real._wait_for(
        lambda: broker.exists(f"strategy:lifecycle:event:{rollback_event_id}"),
        timeout=60,
        label="D11C lifecycle strategy resume processing",
    )
    rollback_active_after_event = await _wait_active_strategy_routes(
        broker,
        set(ALL_STRATEGY_ROUTES),
        label="D11C lifecycle Strategy target re-admission",
    )
    lifecycle_quiescence = await _wait_legacy_producer_quiescence(
        broker,
        timeout=60,
        label="D11C lifecycle re-admission quiescence",
    )
    lifecycle_groups = lifecycle_quiescence["feature_groups"]
    lifecycle_signal_groups = lifecycle_quiescence["signal_input_groups"]
    await infrastructure.stop_signal()
    await _wait_service_stopped(
        infrastructure, "signal-worker", label="D11C Signal producer recutover stop"
    )
    post_signal_feature_groups = await _wait_target_feature_quiescence_stable(
        broker,
        label="D11C late feature drain after Signal stop",
    )
    cutback = {
        "effect_progress": current_r,
        "groups": cutback_groups,
        "authority": {
            record.route: _authority_record_payload(record) for record in handoff_two
        },
        "strategy_epoch_2_active": strategy_two_active,
        "lifecycle_active_before_stop": lifecycle_active_before_stop,
        "lifecycle_stop_event_id": stop_event_id,
        "lifecycle_stop_stream_id": stop_stream_id,
        "lifecycle_stop_processed": bool(
            await broker.exists(f"strategy:lifecycle:event:{stop_event_id}")
        ),
        "lifecycle_active_after_stop": lifecycle_active_after_stop,
        "lifecycle_event_id": rollback_event_id,
        "lifecycle_stream_id": rollback_stream_id,
        "lifecycle_resume_processed": bool(
            await broker.exists(f"strategy:lifecycle:event:{rollback_event_id}")
        ),
        "lifecycle_processed": bool(
            await broker.exists(f"strategy:lifecycle:event:{rollback_event_id}")
        ),
        "lifecycle_re_admitted_routes": rollback_active_after_event,
        "controller_operation": controller_cutback_observation,
        "rollback_groups": rollback_groups,
        "rollback_signal_input_groups": rollback_signal_groups,
        "lifecycle_groups": lifecycle_groups,
        "lifecycle_signal_input_groups": lifecycle_signal_groups,
        "signal_stopped_for_recutover": True,
        "post_signal_feature_groups": post_signal_feature_groups,
    }
    await infrastructure.stop_strategy()
    await _wait_service_stopped(
        infrastructure, "strategy-worker", label="D11C Strategy re-cutover stop"
    )
    restored_boundary = await d11b_real._stable_target_feature_boundaries(broker)
    recutover_boundaries = {
        route: int(value["close_cutoff_ms"])
        for route, value in restored_boundary["final"].items()
    }
    handoff_three = await controller.recutover_to_decision(
        expected_epochs={route: 2 for route in TARGET_SIGNAL_ROUTES},
        boundary_ms_by_route=recutover_boundaries,
    )
    controller_recutover_observation = dict(controller.last_observation)
    await infrastructure.start_decision()
    final_ready = await _wait_decision_ready(infrastructure)
    await infrastructure.start_signal()
    await infrastructure.start_strategy()
    final_strategy_active = await _wait_active_strategy_routes(
        broker,
        set(UNRELATED_STRATEGY_ROUTES),
        label="D11C final unrelated Strategy admission",
    )
    (
        final_lifecycle_event_id,
        final_lifecycle_stream_id,
    ) = await _strategy_lifecycle_event(broker, "BTC")
    final_runtime_evidence: dict[str, object] = {}

    async def _decision_lifecycle_processed() -> dict[str, object] | None:
        nonlocal final_runtime_evidence
        try:
            final_runtime_evidence = await d11b_real._runtime_snapshot(
                infrastructure.decision_url
            )
        except OSError:
            return None
        lifecycle = final_runtime_evidence.get("last_lifecycle_evidence")
        if not isinstance(lifecycle, Mapping):
            return None
        event_ids = lifecycle.get("event_ids")
        return (
            final_runtime_evidence
            if isinstance(event_ids, list) and final_lifecycle_stream_id in event_ids
            else None
        )

    await d11b_real._wait_for(
        _decision_lifecycle_processed,
        timeout=90,
        label="D11C Decision-owned lifecycle processing",
    )
    lifecycle_decision_active = await _active_strategy_routes(broker)
    await infrastructure.restart_decision()
    post_restart_ready = await _wait_decision_ready(infrastructure)
    await infrastructure.restart_decision()
    broker_persistence = await _authority_payload(authority)
    final_stats = await infrastructure.stats("decision3")
    execution_document = yaml.safe_load((ROOT / "configs/execution.yaml").read_text())
    execution_section = (
        execution_document.get("execution")
        if isinstance(execution_document, Mapping)
        else None
    )
    execution_mode = (
        execution_section.get("mode")
        if isinstance(execution_section, Mapping)
        else None
    )
    recutover = {
        "authority": {
            record.route: _authority_record_payload(record) for record in handoff_three
        },
        "ready": final_ready,
        "strategy_active": final_strategy_active,
        "lifecycle_decision_owned_active": lifecycle_decision_active,
        "post_restart_ready": post_restart_ready,
        "lifecycle_event_id": final_lifecycle_event_id,
        "lifecycle_stream_id": final_lifecycle_stream_id,
        "lifecycle_processed": final_lifecycle_stream_id
        in final_runtime_evidence.get("last_lifecycle_evidence", {}).get(
            "event_ids", []
        ),
        "controller_operation": controller_recutover_observation,
        "broker_persistence": broker_persistence,
        "progress": await progress_rows(pool),
        "signals": await signal_entries(broker),
    }
    return {
        "cutback_preflight": cutback_preflight,
        "cutback": cutback,
        "controller_recutover": controller_recutover_observation,
        "recutover": recutover,
        "resources_strategy_two": resources_strategy_two,
        "resources_final": final_stats,
        "execution": {
            "mode": execution_mode,
            "mode_source": "config",
            "container_running": bool(
                final_stats.get("execution-worker", {}).get("running")
            ),
        },
    }


async def run_measured_trial(trial_name: str) -> dict[str, object]:
    """Run one complete default-topology paper promotion trial."""

    infrastructure = D11CInfrastructure(trial_name)
    pool: asyncpg.Pool | None = None
    broker: Any | None = None
    trial: dict[str, object] = {
        "evidence_origin": "measured_disposable",
        "real_disposable_stack": True,
        "trial_name": trial_name,
        "configured_strategy_routes": list(ALL_STRATEGY_ROUTES),
        "unrelated_strategy_routes": list(UNRELATED_STRATEGY_ROUTES),
    }
    try:
        config = d11b_real._load_production_config()
        await infrastructure.start_foundation()
        pool = await asyncpg.create_pool(
            infrastructure.postgres_dsn, min_size=1, max_size=6
        )
        broker = valkey.Valkey.from_url(
            infrastructure.valkey_uri, decode_responses=True
        )
        await d11b_real._ensure_risk_schema(pool)
        await d11b_real.apply_ingestion_schema(pool)
        await d11b_real.ensure_checkpoint_schema(pool)
        bucket_start = await d11b_real._seed_d11b_future_history(pool, config)
        trial["seed_outbox_rows_closed"] = await _baseline_seed_outbox(pool)
        await _seed_all_manifests(broker)
        await infrastructure.start_ingestion()
        await infrastructure.start_support()
        authority = SignalAuthorityStore(broker)
        context = _TrialContext(
            infrastructure=infrastructure,
            pool=pool,
            broker=broker,
            config=config,
            authority=authority,
            bucket_start=bucket_start,
        )

        unseeded = await _run_unseeded_phase(context)
        trial.update(unseeded)
        authority_evidence = unseeded.get("authority")
        if not isinstance(authority_evidence, Mapping):
            raise TypeError("unseeded authority evidence is not a mapping")
        strategy_epoch_zero = authority_evidence.get("strategy_epoch_0")
        if not isinstance(strategy_epoch_zero, Mapping):
            raise TypeError("missing Strategy epoch-zero authority evidence")

        decision = await _run_decision_epoch_one_and_cold_restart(
            context, strategy_epoch_zero
        )
        trial.update(decision)
        trial.update(await _run_cutback_and_recutover(context))
        trial["cleanup_expected"] = True
        return trial
    except Exception as exc:  # noqa: BLE001 - raw failure is part of evidence
        trial["error"] = f"{type(exc).__name__}: {exc}"
        trial["failed"] = True
        if broker is not None:
            try:
                trial["failure_feature_groups"] = {
                    route: await d11b_real._group(broker, f"features:{route}")
                    for route, _timeframe in TARGET_FEATURE_ROUTES
                }
            except Exception as group_exc:  # noqa: BLE001 - preserve failure evidence
                trial["failure_feature_groups_error"] = (
                    f"{type(group_exc).__name__}: {group_exc}"
                )
        for service in ("decision", "strategy-worker", "ingestion"):
            try:
                trial[f"{service}_logs"] = await infrastructure.logs(service)
            except Exception as log_exc:  # noqa: BLE001 - preserve original failure
                trial[f"{service}_logs_error"] = f"{type(log_exc).__name__}: {log_exc}"
        return trial
    finally:
        if broker is not None:
            await broker.aclose()
        if pool is not None:
            await pool.close()
        trial["cleanup"] = await infrastructure.cleanup()


def _feature_stream_projection(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    result: dict[str, object] = {}
    for route, snapshot in value.items():
        entries = snapshot.get("entries", []) if isinstance(snapshot, Mapping) else []
        if not isinstance(entries, list):
            result[str(route)] = None
            continue
        result[str(route)] = {
            "multiplicity": len(entries),
            "cutoffs": [
                item.get("close_cutoff_ms")
                for item in entries
                if isinstance(item, Mapping)
            ],
            "bar_identity_fingerprints": [
                item.get("bar_identity_fingerprint")
                for item in entries
                if isinstance(item, Mapping)
            ],
        }
    return result


_SEMANTIC_VOLATILE_KEYS = {
    "anchor_id",
    "before_last_delivered_id",
    "container_id",
    "cursor",
    "event_id",
    "event_ids",
    "first_id",
    "id",
    "last_delivered_id",
    "last_id",
    "last_id_through_progress",
    "last_lifecycle_evidence",
    "last_poll_at",
    "last_rebuild_at",
    "lifecycle_cursor",
    "lifecycle_event_id",
    "lifecycle_stop_stream_id",
    "lifecycle_stream_id",
    "latest_stream_id",
    "setid",
    "started_at",
    "stream_id",
}


def _semantic_projection(value: object) -> object:
    """Keep causal/authority semantics while removing disposable transport IDs."""

    if isinstance(value, Mapping):
        projected: dict[str, object] = {}
        for key, item in value.items():
            name = str(key)
            if name in _SEMANTIC_VOLATILE_KEYS or name.endswith("_at"):
                continue
            projected[name] = _semantic_projection(item)
        return projected
    if isinstance(value, list):
        return [_semantic_projection(item) for item in value]
    if isinstance(value, tuple):
        return [_semantic_projection(item) for item in value]
    return value


async def run_measured_certification() -> dict[str, object]:
    trials = [await run_measured_trial("trial_a"), await run_measured_trial("trial_b")]
    semantic = []
    for trial in trials:
        semantic.append(
            _semantic_projection(
                {
                    "authority": trial.get("authority"),
                    "strategy_admission": trial.get("strategy_admission"),
                    "flow": trial.get("flow"),
                    "cutback": trial.get("cutback"),
                    "cutback_preflight": _feature_stream_projection(
                        trial.get("cutback_preflight")
                    ),
                    "recutover": trial.get("recutover"),
                    "cold_restart": trial.get("cold_restart"),
                    "pre_cold_restart_feature_streams": _feature_stream_projection(
                        trial.get("pre_cold_restart_feature_streams")
                    ),
                    "post_cold_restart_feature_streams": _feature_stream_projection(
                        trial.get("cold_restart", {}).get("feature_streams")
                        if isinstance(trial.get("cold_restart"), Mapping)
                        else None
                    ),
                }
            )
        )
    return {
        "evidence_origin": "measured_disposable",
        "trials": trials,
        "trial_semantic_parity": {
            "trial_a": _digest(semantic[0]),
            "trial_b": _digest(semantic[1]),
            "matches": semantic[0] == semantic[1],
        },
    }


def _digest(value: object) -> str:
    return (
        __import__("hashlib")
        .sha256(
            json.dumps(
                value, sort_keys=True, default=str, separators=(",", ":")
            ).encode()
        )
        .hexdigest()
    )


__all__ = ["D11CInfrastructure", "run_measured_certification", "run_measured_trial"]
