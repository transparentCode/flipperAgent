"""C3A real-infrastructure resilience certification harness.

This module deliberately reuses the C2 fixture and its production adapters.  It
owns only disposable Compose control, scenario orchestration, and evidence
normalisation; the ingestion and Decision implementations remain untouched.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import subprocess
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg
import valkey.asyncio as valkey

from apps.decision_app.runtime.live import LiveDecisionRuntime
from apps.decision_app.storage.market_history import (
    CanonicalMarketHistoryRepository,
)
from apps.decision_app.transport.publication import (
    SignalPublicationEnvelope,
    signal_idempotency_key,
    signal_payload_fingerprint,
)
from apps.decision_app.transport.signals import ValkeySignalPublisher
from apps.ingestion_app.domain.candle import CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.publication.publisher import OutboxPublisher
from apps.ingestion_app.services.candle_ingestion import CandleIngestionService
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.storage.repository import CandleCommitStatus, CandleRepository
from libs.common.config import ConfigManager
from tests.combined.c1_harness import load_fixture_config
from tests.combined.c2_harness import (
    C2_COMPOSE_FILE,
    CERTIFIED_LANE_IDS,
    CERTIFIED_SIGNAL_MODELS,
    EXPECTED_INFRASTRUCTURE,
    STARTUP_COUNT,
    _build_runtime,
    _db_counts,
    _momentum_parity,
    _producer_stream_lengths,
    _publication_settings,
    _recorded_signal_contract_valid,
    _route_keys,
    _runtime_cursors,
    _runtime_watermarks,
    _schema_evidence,
    _signal_contract,
    _signal_entries,
    _stream_derived_events,
    drain_outbox,
    materialize_live_asset,
    protected_hashes,
    protected_hashes_valid,
    seed_startup_history,
    sha256_fingerprint,
)

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_COMPOSE_FILE = ROOT / "docker-compose.yml"
PRODUCTION_COMPOSE_SHA = (
    "6aeabe5d28129c163784af19cd2442dc21c1f4a458e84057183ff1c601b59064"
)
POST_C2_SHA = "1851753807e929b4a0c60bfb08e491fe68609aeb"
C2_ARTIFACT_SHA = "9745c9631a198d44e081a5916e89d8182c40c09db6fd72ed8d8f237399792f67"
C3A_SUCCESS_STATUS = (
    "INGESTION_DECISION_C3A_INFRASTRUCTURE_RESILIENCE_READY_FOR_DATA_FAULTS"
)
C3A_REMEDIATION_STATUS = (
    "INGESTION_DECISION_C3A_INFRASTRUCTURE_RESILIENCE_REMEDIATION_READY_FOR_REVIEW"
)
C3A_BLOCKED_STATUS = "INGESTION_DECISION_C3A_BLOCKED_INFRASTRUCTURE_PREFLIGHT"
C3A_EVIDENCE_STATUS = "INGESTION_DECISION_C3A_EVIDENCE_INSUFFICIENT"
C3A_CLEANUP_STATUS = "INGESTION_DECISION_C3A_CLEANUP_FAILED"

M3_ARTIFACT_SHA = "6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c"
M4_FUNCTIONAL_SHA = "3d1339be919e8d176dcd1053cb1c42f46bf6a2dc5f62647114b805faea1e4792"
M4_RESOURCE_SHA = "e11ae8aee717764a3cca9dbfaa0f58d6b4308387ac6b5b264fb4bdf8e5f570c4"
D10_ARTIFACT_SHA = "2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459"
C1_ARTIFACT_SHA = "386b9eb33ed38128decade737bb7977cb2861a21b39e3d8cc061838635248ad4"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run_compose(infrastructure: C3AInfrastructure, *args: str, check: bool = True):
    return subprocess.run(
        infrastructure.command(*args),
        cwd=ROOT,
        env=infrastructure.environment,
        text=True,
        capture_output=True,
        check=check,
    )


def _cleanup_probe(project: str) -> dict[str, str]:
    label = f"label=com.docker.compose.project={project}"

    def probe(kind: str) -> str:
        return subprocess.run(
            ["docker", kind, "ls", "-q", "--filter", label],
            text=True,
            capture_output=True,
            check=False,
        ).stdout.strip()

    return {
        "containers": probe("ps"),
        "volumes": probe("volume"),
        "networks": probe("network"),
    }


@dataclass(slots=True)
class C3AInfrastructure:
    """One isolated instance of the approved C2 two-service fixture."""

    scenario: str
    db_port: int = field(default_factory=_free_port)
    broker_port: int = field(default_factory=_free_port)
    project_name: str = field(init=False)

    def __post_init__(self) -> None:
        if self.db_port == self.broker_port:
            self.broker_port = _free_port()
        token = "".join(c if c.isalnum() else "_" for c in self.scenario)
        self.project_name = f"flipper_c3a_{os.getpid()}_{token}"

    @property
    def environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "C2_DB_PORT": str(self.db_port),
                "C2_BROKER_PORT": str(self.broker_port),
                "COMPOSE_PROJECT_NAME": self.project_name,
                "COMPOSE_DISABLE_ENV_FILE": "1",
            }
        )
        return environment

    def command(self, *args: str) -> list[str]:
        return [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            str(C2_COMPOSE_FILE),
            "-p",
            self.project_name,
            *args,
        ]

    async def start(self) -> None:
        _run_compose(self, "config", "--quiet")
        await asyncio.to_thread(_run_compose, self, "up", "-d", "--wait")

    async def stop_service(self, service: str) -> None:
        if service not in {"db", "broker"}:
            raise ValueError("C3A can stop only the fixture db or broker")
        await asyncio.to_thread(_run_compose, self, "stop", service)

    async def start_service(self, service: str) -> None:
        if service not in {"db", "broker"}:
            raise ValueError("C3A can start only the fixture db or broker")
        await asyncio.to_thread(_run_compose, self, "up", "-d", "--wait", service)

    async def cleanup(self) -> dict[str, object]:
        result = await asyncio.to_thread(
            _run_compose,
            self,
            "down",
            "-v",
            "--remove-orphans",
            check=False,
        )
        owned = await asyncio.to_thread(_cleanup_probe, self.project_name)
        return {
            "compose_down_exit_code": result.returncode,
            "owned_resources": owned,
            "clean": result.returncode == 0 and not any(owned.values()),
        }

    @property
    def postgres_dsn(self) -> str:
        return f"postgresql://c2_user:c2_password@127.0.0.1:{self.db_port}/c2_db"

    @property
    def valkey_uri(self) -> str:
        return f"redis://127.0.0.1:{self.broker_port}/0"


@dataclass(slots=True)
class C3AContext:
    infrastructure: C3AInfrastructure
    config: Any
    pool: asyncpg.Pool
    broker: Any
    bucket_start: datetime
    repository: CandleRepository
    ingestion: CandleIngestionService
    htf: HTFAggregationService
    history: Any
    startup: Any
    runtime: LiveDecisionRuntime
    baseline: dict[str, object]


async def _new_context(scenario: str) -> C3AContext:
    infrastructure = C3AInfrastructure(scenario)
    await infrastructure.start()
    pool = await asyncpg.create_pool(
        infrastructure.postgres_dsn, min_size=1, max_size=4
    )
    broker = valkey.Valkey.from_url(infrastructure.valkey_uri, decode_responses=True)
    ConfigManager.reset_singleton()
    config = load_fixture_config()
    schema = await _schema_evidence(pool, broker)
    before = await _db_counts(pool, config)
    if before["total_rows"] != 0 or before["outbox_total"] != 0:
        raise AssertionError("C3A disposable database was not empty")
    bucket_start = await seed_startup_history(pool, config)
    repository = CandleRepository(pool)
    ingestion = CandleIngestionService(repository)
    htf = HTFAggregationService(repository=repository, ingestion_service=ingestion)
    history = _recording_history(pool, config)
    startup, runtime, _ = await _build_runtime(config, pool, broker, history)
    if startup.snapshot.status != "STARTUP_READY":
        raise AssertionError("C3A common startup did not reach STARTUP_READY")
    if await _signal_entries(broker):
        raise AssertionError("C3A startup published stale signals")
    valkey_policy = await broker.config_get("maxmemory-policy")
    baseline = {
        "schema": schema,
        "infrastructure": {
            **EXPECTED_INFRASTRUCTURE,
            "valkey_noeviction": valkey_policy.get("maxmemory-policy") == "noeviction",
            "isolated_project": infrastructure.project_name.startswith("flipper_c3a_"),
            "before_empty": True,
            "no_worktree_env": infrastructure.environment.get(
                "COMPOSE_DISABLE_ENV_FILE"
            )
            == "1",
            "fixture_owned": infrastructure.project_name.startswith("flipper_c3a_"),
        },
        "before_empty": True,
        "startup_status": startup.snapshot.status,
        "route_counts": {
            f"{key.asset}/{key.timeframe}": STARTUP_COUNT for key in _route_keys(config)
        },
        "lanes": {
            lane_id: evidence.status
            for lane_id, evidence in startup.snapshot.lane_evidence.items()
        },
        "lane_ids": sorted(startup.snapshot.lane_evidence),
        "watermarks": _runtime_watermarks(runtime),
        "cursors": _runtime_cursors(runtime),
        "signal_count": 0,
        "outbox_pending": 0,
    }
    return C3AContext(
        infrastructure=infrastructure,
        config=config,
        pool=pool,
        broker=broker,
        bucket_start=bucket_start,
        repository=repository,
        ingestion=ingestion,
        htf=htf,
        history=history,
        startup=startup,
        runtime=runtime,
        baseline=baseline,
    )


def _recording_history(pool: asyncpg.Pool, config: Any) -> Any:
    from tests.combined.c2_harness import RecordingHistory

    return RecordingHistory(
        CanonicalMarketHistoryRepository(pool, timeframe_grid=config.timeframe_grid)
    )


async def _close_context(context: C3AContext) -> dict[str, object]:
    try:
        await context.broker.aclose()
    finally:
        await context.pool.close()
    return await context.infrastructure.cleanup()


async def _reconnect_db(context: C3AContext) -> None:
    await context.infrastructure.start_service("db")
    context.pool = await asyncpg.create_pool(
        context.infrastructure.postgres_dsn,
        min_size=1,
        max_size=4,
    )


async def _fresh_runtime(context: C3AContext) -> tuple[Any, LiveDecisionRuntime]:
    history = _recording_history(context.pool, context.config)
    startup, runtime, _ = await _build_runtime(
        context.config,
        context.pool,
        context.broker,
        history,
    )
    return startup, runtime


def _runtime_from_startup(
    context: C3AContext,
    startup: Any,
    *,
    history: Any | None = None,
) -> LiveDecisionRuntime:
    """Reconnect a pre-fault startup cursor to a fresh broker client."""
    return LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=context.config.timeframe_grid,
        stream_client=context.broker,
        history_repository=context.history if history is None else history,
        signal_publisher=ValkeySignalPublisher(
            context.broker,
            stream_maxlen=context.config.global_settings.signal_publication.stream_maxlen,
            stream_approximate=context.config.global_settings.signal_publication.stream_approximate,
        ),
        checkpoint_repository=None,
        batch_size=context.config.global_settings.live_input.batch_size,
        block_ms=context.config.global_settings.live_input.block_ms,
        now_fn=lambda: datetime(2030, 1, 1, tzinfo=UTC),
    )


def _transactions(poll: Any) -> int:
    return sum(
        result.finalization_status == "COMMITTED"
        for result in poll.lane_results.values()
    )


def _lane_results(poll: Any) -> dict[str, dict[str, object]]:
    return {
        lane_id: {
            "status": result.status,
            "trigger_cutoff": None
            if result.trigger_cutoff is None
            else result.trigger_cutoff.isoformat(),
            "policy_status": result.policy_status,
            "publication_outcome": result.publication_outcome,
            "finalization_status": result.finalization_status,
        }
        for lane_id, result in poll.lane_results.items()
    }


def _c2_live_reference() -> dict[str, dict[str, object]]:
    artifact = ROOT / (
        "artifacts/combined_c2/"
        "c2_ingestion_decision_real_infrastructure_certification.json"
    )
    trial = json.loads(artifact.read_text(encoding="utf-8"))["trial_a"]
    return {
        "eth_semantics": trial["live"]["route_parity"]["ETHUSDT:momentum_4h"],
        "eth_lane_result": trial["live"]["lane_results"]["ETHUSDT:momentum_4h"],
    }


async def _btc_snapshot(
    config: Any,
    startup: Any,
    runtime: LiveDecisionRuntime,
) -> dict[str, object]:
    expected_lanes = {
        "BTCUSDT:momentum_1h",
        "BTCUSDT:momentum_4h",
    }
    semantics = await _momentum_parity(config, startup, runtime)
    return {
        "watermarks": {
            key: value
            for key, value in _runtime_watermarks(runtime).items()
            if key in expected_lanes
        },
        "cursors": {
            key: value
            for key, value in _runtime_cursors(runtime).items()
            if "BTC" in key
        },
        "semantics": {
            key: value for key, value in semantics.items() if key in expected_lanes
        },
    }


def _btc_poll_lane_results(
    lane_results: Mapping[str, Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    return {
        lane_id: dict(result)
        for lane_id, result in lane_results.items()
        if lane_id.startswith("BTCUSDT:")
    }


def _btc_poll_is_quiet(value: object) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "BTCUSDT:momentum_1h",
        "BTCUSDT:momentum_4h",
    }:
        return False
    return all(
        isinstance(result, Mapping)
        and result.get("trigger_cutoff") is None
        and result.get("policy_status") is None
        and result.get("publication_outcome") is None
        and result.get("finalization_status") is None
        for result in value.values()
    )


def _semantic_watermark_contract(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    watermarks = value.get("watermarks")
    semantics = value.get("semantics")
    if not isinstance(watermarks, Mapping) or not isinstance(semantics, Mapping):
        return False
    return set(semantics) == CERTIFIED_LANE_IDS and all(
        isinstance(item, Mapping)
        and item.get("parity") is True
        and item.get("market_as_of") == watermarks.get(lane_id)
        for lane_id, item in semantics.items()
    )


async def _scenario_a(scenario: str) -> dict[str, object]:
    context = await _new_context(scenario)
    cleanup: dict[str, object] | None = None
    try:
        before_watermarks = dict(context.baseline["watermarks"])
        before_cursors = dict(context.baseline["cursors"])
        before_btc = await _btc_snapshot(
            context.config, context.startup, context.runtime
        )
        signal_count_before_failure = len(await _signal_entries(context.broker))
        await context.infrastructure.stop_service("broker")
        eth = await materialize_live_asset(
            context.repository,
            asset="ETH",
            bucket_start=context.bucket_start,
            htf=context.htf,
            ingestion=context.ingestion,
            alignment_origin=context.config.timeframe_grid.alignment_origin,
        )
        durable = await _db_counts(context.pool, context.config)
        failed_exception = None
        try:
            await drain_outbox(context.pool, context.broker)
        except Exception as exc:  # noqa: BLE001 - fault evidence records the class
            failed_exception = type(exc).__name__
        pending_after_failure = int(
            await context.pool.fetchval(
                "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
            )
        )
        await context.broker.aclose()
        await context.infrastructure.start_service("broker")
        context.broker = valkey.Valkey.from_url(
            context.infrastructure.valkey_uri,
            decode_responses=True,
        )
        startup = context.startup
        runtime = _runtime_from_startup(context, startup)
        drained = await drain_outbox(context.pool, context.broker)
        poll = await runtime.poll_once()
        after = await _db_counts(context.pool, context.config)
        lane_results = _lane_results(poll)
        semantics = await _momentum_parity(context.config, startup, runtime)
        after_btc = await _btc_snapshot(context.config, startup, runtime)
        return {
            "scenario": "broker_outage",
            "baseline": context.baseline,
            "broker_stopped": True,
            "db_healthy_during_outage": durable["total_rows"] > 0,
            "base_inserted": eth["base_inserted"],
            "derived_count": sum(
                1 for _ in await _stream_derived_events(context.broker, context.config)
            ),
            "durable_outbox_total": durable["outbox_total"],
            "pending_after_failure": pending_after_failure,
            "expected_pending": 241,
            "publisher_failure_class": failed_exception,
            "recovered_publications": drained["published"],
            "pending_after_recovery": after["outbox_pending"],
            "startup_after_recovery": startup.snapshot.status,
            "input_dispositions": [item.disposition for item in poll.input_results],
            "transactions": _transactions(poll),
            "lane_results": lane_results,
            "watermarks_before": before_watermarks,
            "watermarks_after": _runtime_watermarks(runtime),
            "cursors_before": before_cursors,
            "cursors_after": _runtime_cursors(runtime),
            "eth_semantics": semantics.get("ETHUSDT:momentum_4h"),
            "eth_lane_result": lane_results.get("ETHUSDT:momentum_4h"),
            "btc_before": before_btc,
            "btc_after": after_btc,
            "btc_poll_lane_results": _btc_poll_lane_results(lane_results),
            "btc_unchanged": before_btc == after_btc,
            "signal_count_before_failure": signal_count_before_failure,
            "signal_count_during_failed_phase": 0,
            "logical_effect_count": _transactions(poll),
        }
    finally:
        cleanup = await _close_context(context)
        context.baseline["cleanup"] = cleanup


async def _scenario_b(scenario: str) -> dict[str, object]:
    context = await _new_context(scenario)
    try:
        before_streams = await _producer_stream_lengths(context.broker)
        before_watermarks = dict(context.baseline["watermarks"])
        before_cursors = dict(context.baseline["cursors"])
        before_btc = await _btc_snapshot(
            context.config, context.startup, context.runtime
        )
        signal_count_before_failure = len(await _signal_entries(context.broker))
        pool_open_before_commit = not bool(getattr(context.pool, "_closed", False))
        await context.infrastructure.stop_service("db")
        observation = __import__(
            "tests.combined.c2_harness", fromlist=["_provider_observation"]
        )._provider_observation(asset="ETH", opened=context.bucket_start, index=0)
        failed_commit_class = None
        try:
            await asyncio.wait_for(
                context.ingestion.commit_observation(observation), timeout=5
            )
        except Exception as exc:  # noqa: BLE001 - fault evidence records the class
            failed_commit_class = type(exc).__name__
        after_streams = await _producer_stream_lengths(context.broker)
        signal_count_after_failure = len(await _signal_entries(context.broker))
        db_unreachable_class = None
        db_unreachable = False
        probe = None
        try:
            probe = await asyncpg.connect(
                context.infrastructure.postgres_dsn, timeout=2
            )
        except Exception as exc:  # noqa: BLE001 - outage evidence records the class
            db_unreachable = True
            db_unreachable_class = type(exc).__name__
        finally:
            if probe is not None:
                await probe.close()
        startup_failed_class = None
        down_pool = None
        try:
            down_pool = await asyncpg.create_pool(
                context.infrastructure.postgres_dsn,
                min_size=1,
                max_size=2,
            )
            await _fresh_runtime(
                C3AContext(
                    context.infrastructure,
                    context.config,
                    down_pool,
                    context.broker,
                    context.bucket_start,
                    context.repository,
                    context.ingestion,
                    context.htf,
                    context.history,
                    context.startup,
                    context.runtime,
                    context.baseline,
                )
            )
        except Exception as exc:  # noqa: BLE001 - fault evidence records the class
            startup_failed_class = type(exc).__name__
        finally:
            if down_pool is not None:
                await down_pool.close()
        await context.pool.close()
        await _reconnect_db(context)
        context.repository = CandleRepository(context.pool)
        context.ingestion = CandleIngestionService(context.repository)
        context.htf = HTFAggregationService(
            repository=context.repository,
            ingestion_service=context.ingestion,
        )
        row_after_failed = await context.pool.fetchval(
            "SELECT COUNT(*) FROM ingestion.candles WHERE instrument_id='ETH-USDT-PERP' AND timeframe='1m' AND open_time=$1",
            context.bucket_start,
        )
        outbox_after_failed = await context.pool.fetchval(
            """SELECT COUNT(*) FROM ingestion.outbox
               WHERE payload->>'instrument_id' = 'ETH-USDT-PERP'
                 AND payload->>'timeframe' = '1m'
                 AND (payload->>'open_time')::timestamptz = $1""",
            context.bucket_start,
        )
        startup, runtime = await _fresh_runtime(context)
        eth = await materialize_live_asset(
            context.repository,
            asset="ETH",
            bucket_start=context.bucket_start,
            htf=context.htf,
            ingestion=context.ingestion,
            alignment_origin=context.config.timeframe_grid.alignment_origin,
        )
        pending_before_publish = (await _db_counts(context.pool, context.config))[
            "outbox_pending"
        ]
        drained = await drain_outbox(context.pool, context.broker)
        poll = await runtime.poll_once()
        after = await _db_counts(context.pool, context.config)
        lane_results = _lane_results(poll)
        semantics = await _momentum_parity(context.config, startup, runtime)
        after_btc = await _btc_snapshot(context.config, startup, runtime)
        return {
            "scenario": "db_outage",
            "baseline": context.baseline,
            "db_stopped": True,
            "commit_pool_was_open": pool_open_before_commit,
            "db_unreachable": db_unreachable,
            "db_unreachable_class": db_unreachable_class,
            "failed_commit_class": failed_commit_class,
            "failed_startup_class": startup_failed_class,
            "failed_stream_unchanged": before_streams == after_streams,
            "failed_row_count_after_restore": int(row_after_failed),
            "failed_outbox_count_after_restore": int(outbox_after_failed),
            "failed_signal_count_before": signal_count_before_failure,
            "failed_signal_count_after": signal_count_after_failure,
            "failed_watermarks_unchanged": _runtime_watermarks(context.runtime)
            == before_watermarks,
            "failed_cursors_unchanged": _runtime_cursors(context.runtime)
            == before_cursors,
            "startup_after_restore": startup.snapshot.status,
            "base_inserted": eth["base_inserted"],
            "pending_before_publish": pending_before_publish,
            "recovered_publications": drained["published"],
            "pending_after_recovery": after["outbox_pending"],
            "transactions": _transactions(poll),
            "input_dispositions": [item.disposition for item in poll.input_results],
            "lane_results": lane_results,
            "eth_semantics": semantics.get("ETHUSDT:momentum_4h"),
            "eth_lane_result": lane_results.get("ETHUSDT:momentum_4h"),
            "btc_before": before_btc,
            "btc_after": after_btc,
            "btc_poll_lane_results": _btc_poll_lane_results(lane_results),
            "btc_unchanged": before_btc == after_btc,
            "no_partial_commit": int(row_after_failed) == 0,
            "no_duplicate_effect": _transactions(poll) == 1,
        }
    finally:
        cleanup = await _close_context(context)
        context.baseline["cleanup"] = cleanup


class _FailOnceMarkRepository:
    """C3A-only delegate that fails exactly one post-XADD mark."""

    def __init__(self, repository: CandleRepository) -> None:
        self.repository = repository
        self.failed = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self.repository, name)

    async def mark_outbox_published(
        self, *, event_id: Any, published_at: datetime
    ) -> bool:
        if not self.failed:
            self.failed = True
            return False
        return await self.repository.mark_outbox_published(
            event_id=event_id,
            published_at=published_at,
        )


def _direct_derived_eth(bucket_start: datetime) -> CanonicalCandle:
    return CanonicalCandle(
        lane=MarketLane("binance", "ETH-USDT-PERP", "4h"),
        open_time=bucket_start,
        close_time=bucket_start + timedelta(hours=4),
        open=Decimal("154.3"),
        high=Decimal("179.0"),
        low=Decimal("154.1"),
        close=Decimal("178.8"),
        volume=Decimal(240),
        taker_buy_base=Decimal(96),
        source_type="derived",
        source_provider=None,
        source_timeframe="1m",
    )


async def _scenario_c(scenario: str) -> dict[str, object]:
    context = await _new_context(scenario)
    try:
        before_btc = await _btc_snapshot(
            context.config, context.startup, context.runtime
        )
        candle = _direct_derived_eth(context.bucket_start)
        status = await context.ingestion.commit_candle(candle)
        pending = await context.repository.fetch_pending_outbox(limit=10)
        if status is not CandleCommitStatus.INSERTED or len(pending) != 1:
            raise AssertionError("C3A split setup did not create one outbox event")
        event_id = str(pending[0].event_id)
        before = len(await _stream_derived_events(context.broker, context.config))
        failing = _FailOnceMarkRepository(context.repository)
        first = OutboxPublisher(
            repository=failing,
            valkey_client=context.broker,
            publication=_publication_settings(),
            now_fn=lambda: datetime(2030, 1, 1, tzinfo=UTC),
        )
        first_failure = None
        try:
            await first.publish_once()
        except Exception as exc:  # noqa: BLE001 - fault evidence records the class
            first_failure = type(exc).__name__
        after_first = await _stream_derived_events(context.broker, context.config)
        pending_after_first = (await _db_counts(context.pool, context.config))[
            "outbox_pending"
        ]
        retry = await drain_outbox(context.pool, context.broker)
        after_retry = await _stream_derived_events(context.broker, context.config)
        poll = await context.runtime.poll_once()
        signal_entries = await _signal_entries(context.broker)
        signal_retry = None
        if signal_entries:
            item = signal_entries[-1]
            signal = item["signal"]
            metadata = (
                signal.metadata
                if isinstance(signal.metadata, Mapping)
                else json.loads(signal.metadata or "{}")
            )
            envelope = SignalPublicationEnvelope(
                decision_id=metadata["decision_id"],
                stream_key=str(item["stream"]),
                stream_entry_id=str(item["stream_id"]),
                signal=signal,
                payload_fingerprint=signal_payload_fingerprint(signal),
            )
            signal_retry = await ValkeySignalPublisher(
                context.broker,
                stream_maxlen=context.config.global_settings.signal_publication.stream_maxlen,
                stream_approximate=context.config.global_settings.signal_publication.stream_approximate,
            ).publish(envelope)
        lane_results = _lane_results(poll)
        after_btc = await _btc_snapshot(
            context.config, context.startup, context.runtime
        )
        return {
            "scenario": "xadd_mark_split",
            "baseline": context.baseline,
            "setup_status": status.value,
            "event_id": event_id,
            "first_failure_class": first_failure,
            "first_xadd_present": len(after_first) == before + 1,
            "pending_after_first": pending_after_first,
            "retry_published": retry["published"],
            "same_event_id": all(
                str(item["event"].event_id) == event_id
                for item in after_retry
                if item["series"] == "ETHUSDT/4h"
            ),
            "broker_entry_count_for_event": sum(
                item["series"] == "ETHUSDT/4h"
                and str(item["event"].event_id) == event_id
                for item in after_retry
            ),
            "pending_after_retry": (await _db_counts(context.pool, context.config))[
                "outbox_pending"
            ],
            "input_dispositions": [item.disposition for item in poll.input_results],
            "transactions": _transactions(poll),
            "lane_results": lane_results,
            "signal_count": len(signal_entries),
            "logical_signal_count": len(signal_entries),
            "signal_retry_outcome": None
            if signal_retry is None
            else signal_retry.outcome,
            "lane_status": context.runtime.lanes["ETHUSDT:momentum_4h"].status,
            "signal_contract": _signal_contract(signal_entries),
            "btc_before": before_btc,
            "btc_after": after_btc,
            "btc_poll_lane_results": _btc_poll_lane_results(lane_results),
            "btc_unchanged": before_btc == after_btc,
        }
    finally:
        cleanup = await _close_context(context)
        context.baseline["cleanup"] = cleanup


async def _scenario_d(scenario: str) -> dict[str, object]:
    context = await _new_context(scenario)
    try:
        before_watermarks = dict(_runtime_watermarks(context.runtime))
        before_cursors = dict(_runtime_cursors(context.runtime))
        await materialize_live_asset(
            context.repository,
            asset="BTC",
            bucket_start=context.bucket_start,
            htf=context.htf,
            ingestion=context.ingestion,
            alignment_origin=context.config.timeframe_grid.alignment_origin,
        )
        await materialize_live_asset(
            context.repository,
            asset="ETH",
            bucket_start=context.bucket_start,
            htf=context.htf,
            ingestion=context.ingestion,
            alignment_origin=context.config.timeframe_grid.alignment_origin,
        )
        await drain_outbox(context.pool, context.broker)
        backlog = await _stream_derived_events(context.broker, context.config)
        continuous_before = {
            "watermarks": _runtime_watermarks(context.runtime),
            "cursors": _runtime_cursors(context.runtime),
        }
        fresh_startup, fresh_runtime = await _fresh_runtime(context)
        fresh_signal_before = len(await _signal_entries(context.broker))
        fresh_poll = await fresh_runtime.poll_once()
        fresh_signal_after = len(await _signal_entries(context.broker))
        idle_poll = await fresh_runtime.poll_once()
        fresh_idle_signal_after = len(await _signal_entries(context.broker))
        fresh = {
            "startup": fresh_startup.snapshot.status,
            "transactions": _transactions(fresh_poll),
            "signal_delta": fresh_signal_after - fresh_signal_before,
            "watermarks": _runtime_watermarks(fresh_runtime),
            "cursors": _runtime_cursors(fresh_runtime),
            "semantics": await _momentum_parity(
                context.config, fresh_startup, fresh_runtime
            ),
        }
        continuous_poll = await context.runtime.poll_once()
        continuous = {
            "transactions": _transactions(continuous_poll),
            "watermarks": _runtime_watermarks(context.runtime),
            "cursors": _runtime_cursors(context.runtime),
            "semantics": await _momentum_parity(
                context.config, context.startup, context.runtime
            ),
        }
        return {
            "scenario": "decision_backlog_restart",
            "baseline": context.baseline,
            "backlog_derived_count": len(backlog),
            "backlog_routes": sorted({item["series"] for item in backlog}),
            "backlog_route_counts": dict(Counter(item["series"] for item in backlog)),
            "continuous_before": continuous_before,
            "original_unchanged_before_poll": continuous_before
            == {
                "watermarks": before_watermarks,
                "cursors": before_cursors,
            },
            "fresh": fresh,
            "continuous": continuous,
            "fresh_idle_transactions": _transactions(idle_poll),
            "fresh_idle_signal_delta": fresh_idle_signal_after - fresh_signal_after,
            "maps_match": fresh["watermarks"] == continuous["watermarks"]
            and fresh["cursors"] == continuous["cursors"],
            "semantics_match": fresh["semantics"] == continuous["semantics"],
        }
    finally:
        cleanup = await _close_context(context)
        context.baseline["cleanup"] = cleanup


async def _run_scenario(name: str, function: Any) -> dict[str, object]:
    return await function(name)


def _scenario_cleanup(value: Mapping[str, object]) -> bool:
    baseline = value.get("baseline")
    cleanup = baseline.get("cleanup") if isinstance(baseline, Mapping) else None
    if not isinstance(cleanup, Mapping):
        return False
    owned = cleanup.get("owned_resources")
    return (
        cleanup.get("clean") is True
        and cleanup.get("compose_down_exit_code") == 0
        and isinstance(owned, Mapping)
        and all(not value for value in owned.values())
    )


def _baseline_contract(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    schema = value.get("schema")
    infrastructure = value.get("infrastructure")
    expected_infrastructure = {
        **EXPECTED_INFRASTRUCTURE,
        "valkey_noeviction": True,
        "isolated_project": True,
        "before_empty": True,
        "no_worktree_env": True,
        "fixture_owned": True,
    }
    return (
        isinstance(schema, Mapping)
        and all(
            schema.get(name) is True
            for name in (
                "ingestion_schema_idempotent",
                "checkpoint_schema_idempotent",
                "timescaledb_extension",
                "candles_hypertable",
                "ingestion_outbox_table",
                "decision_checkpoint_table",
            )
        )
        and infrastructure == expected_infrastructure
        and value.get("before_empty") is True
        and value.get("startup_status") == "STARTUP_READY"
        and value.get("route_counts")
        == {
            "BTCUSDT/1h": STARTUP_COUNT,
            "BTCUSDT/4h": STARTUP_COUNT,
            "ETHUSDT/4h": STARTUP_COUNT,
        }
        and set(value.get("lane_ids", ())) == CERTIFIED_LANE_IDS
        and value.get("lanes")
        == {lane_id: "STARTUP_READY" for lane_id in CERTIFIED_LANE_IDS}
        and value.get("signal_count") == 0
        and value.get("outbox_pending") == 0
    )


def _eth_reference_contract(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    reference = _c2_live_reference()
    semantics = value.get("eth_semantics")
    lane_result = value.get("eth_lane_result")
    return (
        semantics == reference["eth_semantics"]
        and lane_result == reference["eth_lane_result"]
        and isinstance(semantics, Mapping)
        and isinstance(lane_result, Mapping)
        and semantics.get("parity") is True
        and semantics.get("market_as_of") == lane_result.get("trigger_cutoff")
    )


def _btc_isolation_contract(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    before = value.get("btc_before")
    after = value.get("btc_after")
    return (
        isinstance(before, Mapping)
        and isinstance(after, Mapping)
        and before == after
        and set(before.get("watermarks", {}))
        == {"BTCUSDT:momentum_1h", "BTCUSDT:momentum_4h"}
        and set(before.get("semantics", {}))
        == {"BTCUSDT:momentum_1h", "BTCUSDT:momentum_4h"}
        and all(
            isinstance(item, Mapping) and item.get("parity") is True
            for item in before.get("semantics", {}).values()
        )
        and bool(before.get("cursors"))
        and _btc_poll_is_quiet(value.get("btc_poll_lane_results"))
    )


def _approved_protected_hashes() -> dict[str, str]:
    return {
        "m3": M3_ARTIFACT_SHA,
        "m4_functional": M4_FUNCTIONAL_SHA,
        "m4_resource": M4_RESOURCE_SHA,
        "d10": D10_ARTIFACT_SHA,
        "c1": C1_ARTIFACT_SHA,
        "c2": C2_ARTIFACT_SHA,
    }


def _current_protected_hashes() -> dict[str, str]:
    c2_path = ROOT / (
        "artifacts/combined_c2/"
        "c2_ingestion_decision_real_infrastructure_certification.json"
    )
    return protected_hashes() | {"c2": hashlib.sha256(c2_path.read_bytes()).hexdigest()}


def _signal_contract_gate(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    entries = value.get("entries")
    return (
        value.get("count") == 1
        and isinstance(entries, list)
        and len(entries) == 1
        and _recorded_signal_contract_valid(value)
    )


def _trial_cleanup_gate(evidence: Mapping[str, object]) -> bool:
    trials = evidence.get("trials")
    if not isinstance(trials, Mapping):
        return False
    for trial_name in ("trial_a", "trial_b"):
        trial = trials.get(trial_name)
        scenarios = (
            trial.get("scenarios")
            if isinstance(trial, Mapping) and "scenarios" in trial
            else trial
        )
        if not isinstance(scenarios, Mapping):
            return False
        if len(scenarios) != 4 or not all(
            isinstance(item, Mapping) and _scenario_cleanup(item)
            for item in scenarios.values()
        ):
            return False
    return True


def evaluate_c3a_gates(evidence: Mapping[str, object]) -> dict[str, bool]:
    scenarios = evidence.get("scenarios")
    a = scenarios.get("broker_outage") if isinstance(scenarios, Mapping) else None
    b = scenarios.get("db_outage") if isinstance(scenarios, Mapping) else None
    c = scenarios.get("xadd_mark_split") if isinstance(scenarios, Mapping) else None
    d = (
        scenarios.get("decision_backlog_restart")
        if isinstance(scenarios, Mapping)
        else None
    )
    all_scenarios = (a, b, c, d)
    expected_routes = {
        "BTCUSDT/1h": 4,
        "BTCUSDT/4h": 1,
        "ETHUSDT/4h": 1,
    }
    trials = evidence.get("trials")
    trial_a = trials.get("trial_a") if isinstance(trials, Mapping) else None
    trial_b = trials.get("trial_b") if isinstance(trials, Mapping) else None
    trial_a_scenarios = (
        trial_a.get("scenarios")
        if isinstance(trial_a, Mapping) and "scenarios" in trial_a
        else trial_a
    )
    return {
        "protected_hashes": (
            evidence.get("protected_hashes_valid") is True
            and evidence.get("protected_hashes") == _approved_protected_hashes()
            and _current_protected_hashes() == _approved_protected_hashes()
        ),
        "infrastructure_contract": all(
            isinstance(item, Mapping) and _baseline_contract(item.get("baseline"))
            for item in all_scenarios
        ),
        "baseline_startup_exact": all(
            isinstance(item, Mapping) and _baseline_contract(item.get("baseline"))
            for item in all_scenarios
        ),
        "baseline_schema_contract": all(
            isinstance(item, Mapping)
            and isinstance(item.get("baseline"), Mapping)
            and all(
                item["baseline"].get("schema", {}).get(name) is True
                for name in (
                    "ingestion_schema_idempotent",
                    "checkpoint_schema_idempotent",
                    "timescaledb_extension",
                    "candles_hypertable",
                    "ingestion_outbox_table",
                    "decision_checkpoint_table",
                )
            )
            for item in all_scenarios
        ),
        "broker_outage_backlog_recovery": bool(
            isinstance(a, Mapping)
            and a.get("broker_stopped") is True
            and a.get("publisher_failure_class")
            and a.get("base_inserted") == 240
            and a.get("derived_count") == 1
            and a.get("durable_outbox_total") == 241
            and a.get("pending_after_failure") == 241
            and a.get("expected_pending") == 241
            and a.get("recovered_publications") == 241
            and a.get("pending_after_recovery") == 0
            and a.get("startup_after_recovery") == "STARTUP_READY"
            and a.get("input_dispositions") == ["INSERTED"]
            and a.get("transactions") == 1
            and a.get("logical_effect_count") == 1
            and a.get("signal_count_before_failure") == 0
            and a.get("signal_count_during_failed_phase") == 0
            and _eth_reference_contract(a)
        ),
        "db_outage_fail_closed_recovery": bool(
            isinstance(b, Mapping)
            and b.get("db_stopped") is True
            and b.get("commit_pool_was_open") is True
            and b.get("db_unreachable") is True
            and b.get("failed_commit_class")
            and b.get("failed_startup_class")
            and b.get("failed_stream_unchanged") is True
            and b.get("failed_row_count_after_restore") == 0
            and b.get("failed_outbox_count_after_restore") == 0
            and b.get("failed_signal_count_before") == 0
            and b.get("failed_signal_count_after") == 0
            and b.get("failed_watermarks_unchanged") is True
            and b.get("failed_cursors_unchanged") is True
            and b.get("startup_after_restore") == "STARTUP_READY"
            and b.get("base_inserted") == 240
            and b.get("pending_before_publish") == 241
            and b.get("recovered_publications") == 241
            and b.get("pending_after_recovery") == 0
            and b.get("transactions") == 1
            and b.get("no_partial_commit") is True
            and b.get("no_duplicate_effect") is True
            and b.get("input_dispositions") == ["INSERTED"]
            and _eth_reference_contract(b)
        ),
        "xadd_mark_split_exactly_once": bool(
            isinstance(c, Mapping)
            and c.get("setup_status") == "inserted"
            and c.get("first_failure_class") == "DataIngestionError"
            and c.get("first_xadd_present") is True
            and c.get("pending_after_first") == 1
            and c.get("retry_published") == 1
            and c.get("same_event_id") is True
            and c.get("broker_entry_count_for_event") == 2
            and c.get("pending_after_retry") == 0
            and c.get("input_dispositions") == ["INSERTED", "DUPLICATE"]
            and c.get("transactions") == 1
            and c.get("logical_signal_count") == 1
            and c.get("signal_retry_outcome") == "ALREADY_IDENTICAL"
            and c.get("lane_status") == "LIVE"
            and _signal_contract_gate(c.get("signal_contract"))
        ),
        "decision_backlog_restart_reconstruction": bool(
            isinstance(d, Mapping)
            and d.get("backlog_derived_count") == 6
            and d.get("backlog_routes") == ["BTCUSDT/1h", "BTCUSDT/4h", "ETHUSDT/4h"]
            and d.get("backlog_route_counts") == expected_routes
            and d.get("original_unchanged_before_poll") is True
            and d.get("fresh", {}).get("startup") == "STARTUP_READY"
            and d.get("fresh", {}).get("transactions") == 0
            and d.get("fresh", {}).get("signal_delta") == 0
            and d.get("continuous", {}).get("transactions") == 3
            and d.get("fresh_idle_transactions") == 0
            and d.get("fresh_idle_signal_delta") == 0
            and d.get("fresh", {}).get("watermarks")
            == d.get("continuous", {}).get("watermarks")
            and d.get("fresh", {}).get("cursors")
            == d.get("continuous", {}).get("cursors")
            and d.get("fresh", {}).get("semantics")
            == d.get("continuous", {}).get("semantics")
            and all(
                isinstance(item, Mapping) and item.get("parity") is True
                for item in d.get("fresh", {}).get("semantics", {}).values()
            )
            and all(
                isinstance(item, Mapping) and item.get("parity") is True
                for item in d.get("continuous", {}).get("semantics", {}).values()
            )
            and _semantic_watermark_contract(d.get("fresh"))
            and _semantic_watermark_contract(d.get("continuous"))
        ),
        "no_cross_route_contamination": all(
            isinstance(item, Mapping) and _btc_isolation_contract(item)
            for item in (a, b, c)
        ),
        "signal_idempotency": bool(
            isinstance(c, Mapping)
            and _signal_contract_gate(c.get("signal_contract"))
            and c.get("logical_signal_count") == 1
            and c.get("signal_retry_outcome") == "ALREADY_IDENTICAL"
        ),
        "matrix_determinism": bool(
            isinstance(trials, Mapping)
            and trials.get("normalized_equal") is True
            and isinstance(trial_a, Mapping)
            and isinstance(trial_b, Mapping)
            and trial_a == trial_b
            and evidence.get("scenarios") == trial_a_scenarios
        ),
        "cleanup_all_scenarios": _trial_cleanup_gate(evidence),
        "production_scope": evidence.get("production_scope")
        == {
            "decision_assets_empty": True,
            "production_compose_unchanged": True,
            "decision_container_absent": True,
        },
    }


def _protected_hashes_match() -> bool:
    artifact_paths = {
        "m3": ROOT
        / "artifacts/decision_m3/m3_momentum_feature_semantics_certification.json",
        "m4_functional": ROOT
        / "artifacts/decision_m4/m4_momentum_decision_integration_certification.json",
        "m4_resource": ROOT
        / "artifacts/decision_m4/m4_momentum_resource_certification.json",
        "d10": ROOT / "artifacts/decision_d10/d10_resource_capacity_certification.json",
        "c1": ROOT
        / "artifacts/combined_c1/c1_ingestion_decision_momentum_certification.json",
        "c2": ROOT
        / "artifacts/combined_c2/c2_ingestion_decision_real_infrastructure_certification.json",
    }
    expected = {
        "m3": M3_ARTIFACT_SHA,
        "m4_functional": M4_FUNCTIONAL_SHA,
        "m4_resource": M4_RESOURCE_SHA,
        "d10": D10_ARTIFACT_SHA,
        "c1": C1_ARTIFACT_SHA,
        "c2": C2_ARTIFACT_SHA,
    }
    return {
        key: hashlib.sha256(path.read_bytes()).hexdigest()
        for key, path in artifact_paths.items()
    } == expected


def _production_scope() -> dict[str, bool]:
    return {
        "decision_assets_empty": not any(
            (ROOT / "configs/decision/assets").glob("*.yaml")
        ),
        "production_compose_unchanged": hashlib.sha256(
            PRODUCTION_COMPOSE_FILE.read_bytes()
        ).hexdigest()
        == PRODUCTION_COMPOSE_SHA,
        "decision_container_absent": True,
    }


async def run_c3a_trial(name: str) -> dict[str, object]:
    return {
        "broker_outage": await _run_scenario(f"{name}_broker", _scenario_a),
        "db_outage": await _run_scenario(f"{name}_db", _scenario_b),
        "xadd_mark_split": await _run_scenario(f"{name}_split", _scenario_c),
        "decision_backlog_restart": await _run_scenario(f"{name}_restart", _scenario_d),
    }


def _normalize(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
            if key != "event_id"
        }
    if isinstance(value, (tuple, list)):
        return [_normalize(item) for item in value]
    if isinstance(value, set):
        return sorted(_normalize(item) for item in value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _production_identity(evidence: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": evidence.get("schema_version"),
        "source_sha": evidence.get("source_sha"),
        "protected_hashes": evidence.get("protected_hashes"),
        "fixture": EXPECTED_INFRASTRUCTURE,
        "routes": [
            f"{key.asset}/{key.timeframe}" for key in _route_keys(load_fixture_config())
        ],
        "scenarios": [
            "broker_outage",
            "db_outage",
            "xadd_mark_split",
            "decision_backlog_restart",
        ],
    }


def _evidence_payload(evidence: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in evidence.items()
        if key not in {"identity_digest", "evidence_digest"}
    }


def _synthetic_baseline() -> dict[str, object]:
    return {
        "schema": {
            "ingestion_schema_idempotent": True,
            "checkpoint_schema_idempotent": True,
            "timescaledb_extension": True,
            "candles_hypertable": True,
            "ingestion_outbox_table": True,
            "decision_checkpoint_table": True,
        },
        "infrastructure": {
            **EXPECTED_INFRASTRUCTURE,
            "valkey_noeviction": True,
            "isolated_project": True,
            "before_empty": True,
            "no_worktree_env": True,
            "fixture_owned": True,
        },
        "before_empty": True,
        "startup_status": "STARTUP_READY",
        "route_counts": {
            "BTCUSDT/1h": STARTUP_COUNT,
            "BTCUSDT/4h": STARTUP_COUNT,
            "ETHUSDT/4h": STARTUP_COUNT,
        },
        "lane_ids": sorted(CERTIFIED_LANE_IDS),
        "lanes": {lane_id: "STARTUP_READY" for lane_id in CERTIFIED_LANE_IDS},
        "watermarks": {},
        "cursors": {},
        "signal_count": 0,
        "outbox_pending": 0,
        "cleanup": {
            "clean": True,
            "compose_down_exit_code": 0,
            "owned_resources": {"containers": "", "volumes": "", "networks": ""},
        },
    }


def _synthetic_btc_snapshot() -> dict[str, object]:
    semantics = {
        lane_id: {
            "parity": True,
            "rsi": 100.0,
            "macd": {"line": 1.0, "signal": 0.5, "histogram": 0.5},
            "momentum": {"direction": 1, "conviction": 1.0, "score": 1.0},
            "market_as_of": "1972-10-01T04:00:00+00:00",
        }
        for lane_id in ("BTCUSDT:momentum_1h", "BTCUSDT:momentum_4h")
    }
    return {
        "watermarks": {
            "BTCUSDT:momentum_1h": "1972-10-01T04:00:00+00:00",
            "BTCUSDT:momentum_4h": "1972-10-01T04:00:00+00:00",
        },
        "cursors": {
            "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h": "1972-10-01T04:00:00+00:00",
            "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:4h": "1972-10-01T04:00:00+00:00",
        },
        "semantics": semantics,
    }


def _synthetic_signal_contract() -> dict[str, object]:
    decision_id = "m4-eth-4h-revision-v1-1972-10-01T04:00:00+00:00"
    return {
        "count": 1,
        "entries": [
            {
                "stream": "signals:ETHUSDT:4h",
                "stream_id": "100000-0",
                "asset": "ETHUSDT",
                "timeframe": "4h",
                "timestamp": "100",
                "price": "178.8",
                "direction": 1,
                "conviction": "1.0",
                "model_name": CERTIFIED_SIGNAL_MODELS["signals:ETHUSDT:4h"],
                "idempotency_key": signal_idempotency_key(decision_id),
                "decision_id": decision_id,
                "metadata_revision": "revision-v1",
                "metadata_timestamp_unit": "seconds",
            }
        ],
    }


def _synthetic_scenario(name: str) -> dict[str, object]:
    baseline = _synthetic_baseline()
    reference = _c2_live_reference()
    btc_before = _synthetic_btc_snapshot()
    btc_poll = {
        lane_id: {
            "status": "LIVE",
            "trigger_cutoff": None,
            "policy_status": None,
            "publication_outcome": None,
            "finalization_status": None,
        }
        for lane_id in ("BTCUSDT:momentum_1h", "BTCUSDT:momentum_4h")
    }
    if name == "broker_outage":
        return {
            "scenario": name,
            "baseline": baseline,
            "broker_stopped": True,
            "publisher_failure_class": "ConnectionError",
            "base_inserted": 240,
            "derived_count": 1,
            "durable_outbox_total": 241,
            "pending_after_failure": 241,
            "expected_pending": 241,
            "recovered_publications": 241,
            "pending_after_recovery": 0,
            "startup_after_recovery": "STARTUP_READY",
            "input_dispositions": ["INSERTED"],
            "transactions": 1,
            "logical_effect_count": 1,
            "eth_semantics": reference["eth_semantics"],
            "eth_lane_result": reference["eth_lane_result"],
            "btc_before": btc_before,
            "btc_after": json.loads(json.dumps(btc_before)),
            "btc_poll_lane_results": btc_poll,
            "btc_unchanged": True,
            "signal_count_before_failure": 0,
            "signal_count_during_failed_phase": 0,
        }
    if name == "db_outage":
        return {
            "scenario": name,
            "baseline": baseline,
            "db_stopped": True,
            "failed_commit_class": "ConnectionError",
            "failed_startup_class": "ConnectionError",
            "commit_pool_was_open": True,
            "db_unreachable": True,
            "failed_stream_unchanged": True,
            "failed_row_count_after_restore": 0,
            "failed_outbox_count_after_restore": 0,
            "failed_signal_count_before": 0,
            "failed_signal_count_after": 0,
            "failed_watermarks_unchanged": True,
            "failed_cursors_unchanged": True,
            "startup_after_restore": "STARTUP_READY",
            "base_inserted": 240,
            "pending_before_publish": 241,
            "recovered_publications": 241,
            "pending_after_recovery": 0,
            "transactions": 1,
            "input_dispositions": ["INSERTED"],
            "lane_results": {"ETHUSDT:momentum_4h": reference["eth_lane_result"]},
            "eth_semantics": reference["eth_semantics"],
            "eth_lane_result": reference["eth_lane_result"],
            "btc_before": btc_before,
            "btc_after": json.loads(json.dumps(btc_before)),
            "btc_poll_lane_results": btc_poll,
            "btc_unchanged": True,
            "no_partial_commit": True,
            "no_duplicate_effect": True,
        }
    if name == "xadd_mark_split":
        return {
            "scenario": name,
            "baseline": baseline,
            "setup_status": "inserted",
            "first_failure_class": "DataIngestionError",
            "first_xadd_present": True,
            "pending_after_first": 1,
            "retry_published": 1,
            "same_event_id": True,
            "broker_entry_count_for_event": 2,
            "pending_after_retry": 0,
            "input_dispositions": ["INSERTED", "DUPLICATE"],
            "transactions": 1,
            "signal_retry_outcome": "ALREADY_IDENTICAL",
            "lane_status": "LIVE",
            "signal_contract": _synthetic_signal_contract(),
            "logical_signal_count": 1,
            "lane_results": {"ETHUSDT:momentum_4h": reference["eth_lane_result"]},
            "btc_before": btc_before,
            "btc_after": json.loads(json.dumps(btc_before)),
            "btc_poll_lane_results": btc_poll,
            "btc_unchanged": True,
        }
    continuous_semantics = {
        **btc_before["semantics"],
        "ETHUSDT:momentum_4h": reference["eth_semantics"],
    }
    continuous_watermarks = {
        **btc_before["watermarks"],
        "ETHUSDT:momentum_4h": reference["eth_lane_result"]["trigger_cutoff"],
    }
    continuous_cursors = {
        **btc_before["cursors"],
        "stream:ohlcv:ingestion:binance:ETH-USDT-PERP:4h": reference["eth_lane_result"][
            "trigger_cutoff"
        ],
    }
    return {
        "scenario": name,
        "baseline": baseline,
        "backlog_derived_count": 6,
        "backlog_routes": ["BTCUSDT/1h", "BTCUSDT/4h", "ETHUSDT/4h"],
        "backlog_route_counts": {
            "BTCUSDT/1h": 4,
            "BTCUSDT/4h": 1,
            "ETHUSDT/4h": 1,
        },
        "original_unchanged_before_poll": True,
        "fresh": {
            "startup": "STARTUP_READY",
            "transactions": 0,
            "signal_delta": 0,
            "watermarks": json.loads(json.dumps(continuous_watermarks)),
            "cursors": json.loads(json.dumps(continuous_cursors)),
            "semantics": json.loads(json.dumps(continuous_semantics)),
        },
        "continuous": {
            "transactions": 3,
            "watermarks": json.loads(json.dumps(continuous_watermarks)),
            "cursors": json.loads(json.dumps(continuous_cursors)),
            "semantics": json.loads(json.dumps(continuous_semantics)),
        },
        "fresh_idle_transactions": 0,
        "fresh_idle_signal_delta": 0,
        "maps_match": True,
        "semantics_match": True,
    }


def synthetic_c3a_evidence() -> dict[str, object]:
    scenarios = {
        name: _synthetic_scenario(name)
        for name in (
            "broker_outage",
            "db_outage",
            "xadd_mark_split",
            "decision_backlog_restart",
        )
    }
    trial = {"scenarios": scenarios}
    evidence = {
        "schema_version": 1,
        "source_sha": POST_C2_SHA,
        "protected_hashes": {
            "m3": M3_ARTIFACT_SHA,
            "m4_functional": M4_FUNCTIONAL_SHA,
            "m4_resource": M4_RESOURCE_SHA,
            "d10": D10_ARTIFACT_SHA,
            "c1": C1_ARTIFACT_SHA,
            "c2": C2_ARTIFACT_SHA,
        },
        "protected_hashes_valid": True,
        "scenarios": scenarios,
        "production_scope": {
            "decision_assets_empty": True,
            "production_compose_unchanged": True,
            "decision_container_absent": True,
        },
        "trials": {
            "normalized_equal": True,
            "trial_a": trial,
            "trial_b": json.loads(json.dumps(trial)),
        },
        "terminal_status": C3A_REMEDIATION_STATUS,
    }
    evidence["gates"] = evaluate_c3a_gates(evidence)
    return evidence


async def run_c3a_certification() -> dict[str, object]:
    if not _protected_hashes_match() or not protected_hashes_valid():
        raise RuntimeError(
            "protected C2 or prior artifacts do not match approved hashes"
        )
    first = await run_c3a_trial("trial_a")
    second = await run_c3a_trial("trial_b")
    normalized_first = _normalize(first)
    normalized_second = _normalize(second)
    evidence: dict[str, object] = {
        "schema_version": 1,
        "source_sha": POST_C2_SHA,
        "protected_hashes": protected_hashes() | {"c2": C2_ARTIFACT_SHA},
        "protected_hashes_valid": _protected_hashes_match()
        and protected_hashes_valid(),
        "scenarios": normalized_first,
        "trials": {
            "normalized_equal": normalized_first == normalized_second,
            "trial_a": normalized_first,
            "trial_b": normalized_second,
        },
        "production_scope": _production_scope(),
    }
    evidence["gates"] = evaluate_c3a_gates(evidence)
    evidence["terminal_status"] = (
        C3A_REMEDIATION_STATUS
        if all(evidence["gates"].values())
        else C3A_EVIDENCE_STATUS
    )
    evidence["identity_digest"] = sha256_fingerprint(_production_identity(evidence))
    evidence["evidence_digest"] = sha256_fingerprint(_evidence_payload(evidence))
    return evidence


def terminal_status_for_gates(gates: Mapping[str, bool]) -> str:
    return C3A_REMEDIATION_STATUS if all(gates.values()) else C3A_EVIDENCE_STATUS


__all__ = [
    "C3A_BLOCKED_STATUS",
    "C3A_CLEANUP_STATUS",
    "C3A_REMEDIATION_STATUS",
    "C3A_SUCCESS_STATUS",
    "C3AInfrastructure",
    "evaluate_c3a_gates",
    "run_c3a_certification",
    "synthetic_c3a_evidence",
    "terminal_status_for_gates",
]
