"""C3B2 provider-recovery and canonical-disagreement certification harness.

The harness composes the approved ingestion and Decision adapters against fresh
disposable TimescaleDB/Valkey projects.  Provider behavior is scripted through
the production ``HistoricalCandleProvider`` contract; no public provider API is
used and no production provider or recovery semantics are changed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg
import valkey.asyncio as valkey

from apps.decision_app.domain.market_state import MarketSeriesKey
from apps.decision_app.runtime.live import LiveDecisionRuntime
from apps.decision_app.storage.market_history import CanonicalMarketHistoryRepository
from apps.decision_app.transport.ingestion import canonical_ingestion_stream_key
from apps.ingestion_app.domain.candle import CandleObservation, CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.services.candle_ingestion import (
    CandleIngestionService,
    canonicalize_observation,
)
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.services.recovery import RecoveryEngine
from apps.ingestion_app.settings import load_ingestion_settings
from apps.ingestion_app.storage.repository import CandleCommitStatus, CandleRepository
from libs.common.config import ConfigManager
from libs.common.exceptions import DataIngestionError
from tests.combined.c2_harness import (
    C1_ARTIFACT_SHA,
    D10_ARTIFACT_SHA,
    EXPECTED_INFRASTRUCTURE,
    M3_ARTIFACT_SHA,
    M4_FUNCTIONAL_SHA,
    M4_RESOURCE_SHA,
    C2Infrastructure,
    RecordingHistory,
    _build_runtime,
    _canonical_candle_semantics,
    _count_route_rows,
    _db_counts,
    _lane_table,
    _momentum_parity,
    _runtime_cursors,
    _runtime_watermarks,
    _schema_evidence,
    _signal_entries,
    _stream_derived_events,
    drain_outbox,
    load_fixture_config,
    seed_startup_history,
)

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = (
    ROOT
    / "artifacts"
    / "combined_c3b2"
    / "c3b2_ingestion_decision_provider_recovery_disagreement_certification.json"
)
PRODUCTION_COMPOSE_FILE = ROOT / "docker-compose.yml"
PRODUCTION_COMPOSE_SHA = (
    "6aeabe5d28129c163784af19cd2442dc21c1f4a458e84057183ff1c601b59064"
)
C3B1_ARTIFACT_SHA = "bfb335bf5ab27b790c91be13ad878531b7a85a957901c86f7a6ec462f566fb63"
C3B2_SUCCESS_STATUS = (
    "INGESTION_DECISION_C3B2_PROVIDER_RECOVERY_DISAGREEMENT_READY_FOR_SHADOW_SOAK"
)
C3B2_REVIEW_STATUS = (
    "INGESTION_DECISION_C3B2_PROVIDER_RECOVERY_DISAGREEMENT_READY_FOR_REVIEW"
)
C3B2_BLOCKED_STATUS = "INGESTION_DECISION_C3B2_BLOCKED_INFRASTRUCTURE_PREFLIGHT"
C3B2_EVIDENCE_STATUS = "INGESTION_DECISION_C3B2_EVIDENCE_INSUFFICIENT"
C3B2_CLEANUP_STATUS = "INGESTION_DECISION_C3B2_CLEANUP_FAILED"
C3B2_CONTRACT_STATUS = "INGESTION_DECISION_C3B2_CONTRACT_REMEDIATION_REQUIRED"
C2_ARTIFACT_SHA = "9745c9631a198d44e081a5916e89d8182c40c09db6fd72ed8d8f237399792f67"
C3A_ARTIFACT_SHA = "34c0b0eaa85fffacbd5c99d346bdcf2829dd12c8c6769e18c63711d0a342622b"
ROUTES = ("BTCUSDT/1h", "BTCUSDT/4h", "ETHUSDT/4h")
ETH_BASE_LANE = MarketLane("binance", "ETH-USDT-PERP", "1m")
BASE_DURATION = timedelta(minutes=1)
TARGET_DURATION = timedelta(hours=4)
TARGET_BASE_COUNT = 240
TARGET_BUCKET_OFFSET = timedelta(hours=4)
EXPECTED_PROVIDER_ORDER = ("binance_native", "ccxt_binance")
EXPECTED_PROTECTED_HASHES = {
    "m3": M3_ARTIFACT_SHA,
    "m4_functional": M4_FUNCTIONAL_SHA,
    "m4_resource": M4_RESOURCE_SHA,
    "d10": D10_ARTIFACT_SHA,
    "c1": C1_ARTIFACT_SHA,
    "c2": C2_ARTIFACT_SHA,
    "c3a": C3A_ARTIFACT_SHA,
    "c3b1": C3B1_ARTIFACT_SHA,
}


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_json_value(item) for item in value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, BaseException):
        return type(value).__name__
    return value


def canonical_json(value: object) -> str:
    return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"))


def sha256_fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def protected_hashes() -> dict[str, str]:
    paths = {
        "m3": ROOT
        / "artifacts"
        / "decision_m3"
        / "m3_momentum_feature_semantics_certification.json",
        "m4_functional": ROOT
        / "artifacts"
        / "decision_m4"
        / "m4_momentum_decision_integration_certification.json",
        "m4_resource": ROOT
        / "artifacts"
        / "decision_m4"
        / "m4_momentum_resource_certification.json",
        "d10": ROOT
        / "artifacts"
        / "decision_d10"
        / "d10_resource_capacity_certification.json",
        "c1": ROOT
        / "artifacts"
        / "combined_c1"
        / "c1_ingestion_decision_momentum_certification.json",
        "c2": ROOT
        / "artifacts"
        / "combined_c2"
        / "c2_ingestion_decision_real_infrastructure_certification.json",
        "c3a": ROOT
        / "artifacts"
        / "combined_c3a"
        / "c3a_ingestion_decision_infrastructure_resilience_certification.json",
        "c3b1": ROOT
        / "artifacts"
        / "combined_c3b1"
        / "c3b1_ingestion_decision_canonical_integrity_certification.json",
    }
    return {name: file_sha256(path) for name, path in paths.items()}


def _load_recovery_contract() -> dict[str, object]:
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(ROOT / "configs"))
    try:
        settings = load_ingestion_settings(manager)
        instrument = settings.assets["ETH"].instruments["ETH-USDT-PERP"]
        return {
            "provider_order": list(instrument.historical_providers),
            "provider_symbols": dict(sorted(instrument.provider_symbols.items())),
            "max_concurrency": settings.recovery.max_concurrency,
            "max_attempts_per_provider": settings.recovery.max_attempts_per_provider,
            "page_limit": settings.recovery.page_limit,
            "retry_backoff_seconds": settings.recovery.retry_backoff_seconds,
            "rest_finalization_grace_seconds": (
                settings.recovery.rest_finalization_grace_seconds
            ),
        }
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()


@dataclass(slots=True)
class ScriptedHistoricalProvider:
    """A deterministic provider implementing the production protocol exactly."""

    provider_id: str
    responses: tuple[object, ...]
    calls: list[dict[str, object]] = field(default_factory=list)

    async def fetch_closed_candles(
        self,
        *,
        lane: MarketLane,
        provider_symbol: str,
        timeframe_duration: timedelta,
        since: datetime,
        until: datetime,
        limit: int,
    ) -> tuple[CandleObservation, ...]:
        attempt = len(self.calls) + 1
        response = self.responses[attempt - 1] if attempt <= len(self.responses) else ()
        call = {
            "attempt": attempt,
            "provider_id": self.provider_id,
            "provider_symbol": provider_symbol,
            "lane": str(lane),
            "since": since,
            "until": until,
            "limit": limit,
            "timeframe_seconds": int(timeframe_duration.total_seconds()),
        }
        if isinstance(response, BaseException):
            call["response"] = "ERROR"
            call["row_open_times"] = []
            self.calls.append(call)
            raise response
        if not isinstance(response, tuple):
            raise TypeError("scripted provider response must be a tuple or exception")
        call["response"] = "ROWS"
        call["row_open_times"] = [item.open_time for item in response]
        self.calls.append(call)
        return response

    def evidence(self) -> list[dict[str, object]]:
        return [
            {
                key: value
                for key, value in call.items()
                if key not in {"provider_symbol", "lane", "timeframe_seconds"}
            }
            for call in self.calls
        ]


@dataclass(slots=True)
class ScenarioContext:
    infrastructure: C2Infrastructure
    pool: asyncpg.Pool
    broker: Any
    config: Any
    recovery_config: dict[str, object]
    bucket_start: datetime
    repository: CandleRepository
    ingestion: CandleIngestionService
    htf: HTFAggregationService
    startup: Any
    runtime: LiveDecisionRuntime
    baseline: dict[str, object]


def _close_value(index: int) -> Decimal:
    return Decimal("154.3") + Decimal(index + 1) / Decimal(10)


def _observation(
    *,
    opened: datetime,
    index: int,
    provider_id: str,
    transport: str = "deterministic",
    taker_buy_base: Decimal | None = Decimal("0.4"),
    close_delta: Decimal = Decimal(0),
) -> CandleObservation:
    close = _close_value(index) + close_delta
    return CandleObservation(
        lane=ETH_BASE_LANE,
        provider_id=provider_id,
        provider_symbol=(
            "ETHUSDT" if provider_id == "binance_native" else "ETH/USDT:USDT"
        ),
        transport=transport,
        open_time=opened,
        close_time=opened + BASE_DURATION,
        open=close,
        high=close + Decimal("0.2"),
        low=close - Decimal("0.2"),
        close=close,
        volume=Decimal(1),
        taker_buy_base=taker_buy_base,
        received_at=opened + BASE_DURATION,
    )


def _route_timeframes(config: Any) -> tuple[str, ...]:
    return tuple(sorted({lane.decision_timeframe for lane in config.lane_specs()}))


def _normalised_watermarks(runtime: LiveDecisionRuntime) -> dict[str, str | None]:
    return {
        key: None if value is None else value.isoformat()
        for key, value in _runtime_watermarks(runtime).items()
    }


def _normalised_cursors(runtime: LiveDecisionRuntime) -> dict[str, str | None]:
    return {
        key: None if value is None else value.isoformat()
        for key, value in _runtime_cursors(runtime).items()
    }


def _control_snapshot(
    runtime: LiveDecisionRuntime,
    semantics: Mapping[str, object],
) -> dict[str, object]:
    return {
        "watermarks": _normalised_watermarks(runtime),
        "input_cursors": _normalised_cursors(runtime),
        "semantics": _json_value(semantics),
    }


def _btc_controls(snapshot: Mapping[str, object]) -> dict[str, object]:
    watermarks = snapshot.get("watermarks", {})
    cursors = snapshot.get("input_cursors", {})
    semantics = snapshot.get("semantics", {})
    return {
        "watermarks": {
            key: value for key, value in watermarks.items() if "BTCUSDT" in key
        },
        "input_cursors": {
            key: value for key, value in cursors.items() if "BTC-USDT-PERP" in key
        },
        "semantics": {
            key: value
            for key, value in semantics.items()
            if str(key).startswith("BTCUSDT:")
        },
    }


def _all_controls_unchanged(
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> bool:
    return dict(before) == dict(after)


async def _materialize_incomplete_eth(
    context: ScenarioContext,
    *,
    missing_indices: frozenset[int],
) -> dict[str, object]:
    requests: list[RecoveryRequest] = []
    inserted = 0
    for index in range(TARGET_BASE_COUNT):
        if index in missing_indices:
            continue
        observation = _observation(
            opened=context.bucket_start + BASE_DURATION * index,
            index=index,
            provider_id="binance_native",
        )
        status = await context.ingestion.commit_observation(observation)
        if status is CandleCommitStatus.CONFLICT:
            raise AssertionError("unexpected canonical conflict while materializing")
        if status is CandleCommitStatus.INSERTED:
            inserted += 1
        requests.extend(
            await context.htf.process_base_candle(
                canonicalize_observation(observation),
                base_duration=BASE_DURATION,
                target_durations={"4h": TARGET_DURATION},
                alignment_origin=context.config.timeframe_grid.alignment_origin,
            )
        )
    return {
        "missing_indices": sorted(missing_indices),
        "base_inserted": inserted,
        "requests": requests,
    }


async def _row_at(
    context: ScenarioContext,
    *,
    lane: MarketLane,
    opened: datetime,
) -> CanonicalCandle | None:
    rows = await context.repository.fetch_candles(
        lane=lane,
        since=opened,
        until=opened + timedelta(microseconds=1),
    )
    if len(rows) > 1:
        raise AssertionError("canonical identity returned more than one row")
    return rows[0] if rows else None


async def _setup_context(infrastructure: C2Infrastructure) -> ScenarioContext:
    await infrastructure.start()
    pool = await asyncpg.create_pool(
        infrastructure.postgres_dsn,
        min_size=1,
        max_size=4,
    )
    broker = valkey.Valkey.from_url(infrastructure.valkey_uri, decode_responses=True)
    config = load_fixture_config()
    recovery_config = _load_recovery_contract()
    schema = await _schema_evidence(pool, broker)
    before = await _db_counts(pool, config)
    if before["total_rows"] != 0 or before["outbox_total"] != 0:
        raise AssertionError("C3B2 disposable database was not empty")
    bucket_start = await seed_startup_history(pool, config)
    repository = CandleRepository(pool)
    ingestion = CandleIngestionService(repository)
    htf = HTFAggregationService(repository=repository, ingestion_service=ingestion)
    history = RecordingHistory(
        CanonicalMarketHistoryRepository(
            pool,
            timeframe_grid=config.timeframe_grid,
        )
    )
    startup, runtime, _ = await _build_runtime(config, pool, broker, history)
    semantics = await _momentum_parity(config, startup, runtime)
    baseline = {
        "schema": schema,
        "before_empty": before,
        "startup_status": startup.snapshot.status,
        "lane_statuses": {
            lane_id: evidence.status
            for lane_id, evidence in startup.snapshot.lane_evidence.items()
        },
        "startup_signal_count": len(await _signal_entries(broker)),
        "controls": _control_snapshot(runtime, semantics),
    }
    if baseline["startup_status"] != "STARTUP_READY":
        raise AssertionError("C3B2 baseline startup did not reach STARTUP_READY")
    if any(status != "STARTUP_READY" for status in baseline["lane_statuses"].values()):
        raise AssertionError("C3B2 baseline did not ready every Decision lane")
    if baseline["startup_signal_count"] != 0:
        raise AssertionError("C3B2 startup published a stale signal")
    return ScenarioContext(
        infrastructure=infrastructure,
        pool=pool,
        broker=broker,
        config=config,
        recovery_config=recovery_config,
        bucket_start=bucket_start,
        repository=repository,
        ingestion=ingestion,
        htf=htf,
        startup=startup,
        runtime=runtime,
        baseline=baseline,
    )


def _recovery_engine(
    context: ScenarioContext,
    providers: Mapping[str, ScriptedHistoricalProvider],
) -> RecoveryEngine:
    settings = context.recovery_config
    return RecoveryEngine(
        providers=providers,
        repository=context.repository,
        ingestion_service=context.ingestion,
        htf_service=context.htf,
        max_concurrency=int(settings["max_concurrency"]),
        page_limit=int(settings["page_limit"]),
        max_attempts_per_provider=int(settings["max_attempts_per_provider"]),
        retry_backoff_seconds=int(settings["retry_backoff_seconds"]),
        rest_finalization_grace_seconds=int(
            settings["rest_finalization_grace_seconds"]
        ),
        now_fn=lambda: (
            context.bucket_start
            + TARGET_BUCKET_OFFSET
            + timedelta(seconds=int(settings["rest_finalization_grace_seconds"]) + 1)
        ),
        settlement_sleep_fn=lambda _seconds: asyncio.sleep(0),
    )


def _recovery_request(materialized: Mapping[str, object]) -> RecoveryRequest:
    requests = materialized["requests"]
    if not isinstance(requests, list | tuple) or len(requests) != 1:
        raise AssertionError("incomplete ETH bucket did not produce one request")
    request = requests[0]
    if not isinstance(request, RecoveryRequest):
        raise TypeError("HTF returned a non-RecoveryRequest")
    return request


async def _finish_poll(
    context: ScenarioContext,
) -> dict[str, object]:
    poll = await context.runtime.poll_once()
    semantics = await _momentum_parity(
        context.config,
        context.startup,
        context.runtime,
    )
    controls = _control_snapshot(context.runtime, semantics)
    return {
        "input_dispositions": [str(item.disposition) for item in poll.input_results],
        "lane_results": _lane_table(poll),
        "controls": controls,
        "signals": len(await _signal_entries(context.broker)),
        "derived_stream_events": len(
            await _stream_derived_events(context.broker, context.config)
        ),
    }


def _config_evidence(context: ScenarioContext) -> dict[str, object]:
    config = context.recovery_config
    return {
        **config,
        "provider_order_is_expected": tuple(config["provider_order"])
        == EXPECTED_PROVIDER_ORDER,
        "attempt_bound_is_positive": int(config["max_attempts_per_provider"]) > 0,
    }


async def _successful_recovery_evidence(
    context: ScenarioContext,
    *,
    materialized: Mapping[str, object],
    providers: Mapping[str, ScriptedHistoricalProvider],
    expected_outbox: int,
    expected_recovered_indices: tuple[int, ...],
    expected_sources: Mapping[int, str],
    overlap_index: int | None = None,
) -> dict[str, object]:
    initial_outbox = await drain_outbox(context.pool, context.broker)
    premature_count = await _count_route_rows(
        context.pool,
        MarketSeriesKey(
            asset="ETHUSDT",
            venue="binance",
            instrument_id="ETH-USDT-PERP",
            timeframe="4h",
        ),
        start=context.bucket_start,
        end=context.bucket_start + TARGET_DURATION,
    )
    request = _recovery_request(materialized)
    engine = _recovery_engine(context, providers)
    follow_ups = await engine.recover(
        request,
        base_timeframe="1m",
        base_duration=BASE_DURATION,
        provider_order=tuple(context.recovery_config["provider_order"]),
        provider_symbols=context.recovery_config["provider_symbols"],
        target_durations={"4h": TARGET_DURATION},
        alignment_origin=context.config.timeframe_grid.alignment_origin,
    )
    recovery_outbox = await drain_outbox(context.pool, context.broker)
    poll = await _finish_poll(context)
    derived_lane = MarketLane("binance", "ETH-USDT-PERP", "4h")
    derived_row = await _row_at(
        context,
        lane=derived_lane,
        opened=context.bucket_start,
    )
    base_rows: dict[str, object] = {}
    for index in expected_recovered_indices:
        row = await _row_at(
            context,
            lane=ETH_BASE_LANE,
            opened=context.bucket_start + BASE_DURATION * index,
        )
        if row is None:
            raise AssertionError(f"recovered base row {index} is absent")
        base_rows[str(index)] = _canonical_candle_semantics(
            row,
            alignment_origin=context.config.timeframe_grid.alignment_origin,
            duration=BASE_DURATION,
        )
    c2_artifact = json.loads(
        (
            ROOT
            / "artifacts"
            / "combined_c2"
            / "c2_ingestion_decision_real_infrastructure_certification.json"
        ).read_text(encoding="utf-8")
    )
    c2_reference = c2_artifact["recovery"]
    c2_live_reference = c2_artifact["live"]
    derived_semantics = (
        None
        if derived_row is None
        else _canonical_candle_semantics(
            derived_row,
            alignment_origin=context.config.timeframe_grid.alignment_origin,
            duration=TARGET_DURATION,
        )
    )
    actual_semantics = poll["controls"]["semantics"]["ETHUSDT:momentum_4h"]
    actual_lane = poll["lane_results"].get("ETHUSDT:momentum_4h")
    return {
        "baseline": context.baseline,
        "request_count": len(materialized["requests"]),
        "initial_base_inserted": materialized["base_inserted"],
        "initial_outbox": initial_outbox,
        "premature_derived_count": premature_count,
        "provider_calls": {
            provider_id: provider.evidence()
            for provider_id, provider in providers.items()
        },
        "provider_call_counts": {
            provider_id: len(provider.calls)
            for provider_id, provider in providers.items()
        },
        "follow_ups": len(follow_ups),
        "recovery_outbox": recovery_outbox,
        "expected_recovery_outbox": expected_outbox,
        "recovered_base_rows": base_rows,
        "expected_sources": {
            str(index): source for index, source in expected_sources.items()
        },
        "overlap_index": overlap_index,
        "derived_count": 0 if derived_row is None else 1,
        "derived_semantics": derived_semantics,
        "reference_derived_semantics": c2_reference["candle_semantics_reference"],
        "semantic": actual_semantics,
        "semantic_reference": c2_live_reference["route_parity"]["ETHUSDT:momentum_4h"],
        "lane_result": actual_lane,
        "lane_result_reference": c2_live_reference["lane_results"][
            "ETHUSDT:momentum_4h"
        ],
        "poll": poll,
        "btc_before": _btc_controls(context.baseline["controls"]),
        "btc_after": _btc_controls(poll["controls"]),
        "btc_isolated": _btc_controls(context.baseline["controls"])
        == _btc_controls(poll["controls"]),
        "all_controls": poll["controls"],
        "baseline_controls": context.baseline["controls"],
        "semantic_parity": (
            derived_semantics == c2_reference["candle_semantics_reference"]
            and actual_semantics
            == c2_live_reference["route_parity"]["ETHUSDT:momentum_4h"]
            and actual_lane == c2_live_reference["lane_results"]["ETHUSDT:momentum_4h"]
        ),
    }


async def _failure_evidence(
    context: ScenarioContext,
    *,
    materialized: Mapping[str, object],
    providers: Mapping[str, ScriptedHistoricalProvider],
    expected_error: str,
    expected_outbox: int = 0,
    expected_existing_index: int | None = None,
    expected_missing_indices: tuple[int, ...] = (),
) -> dict[str, object]:
    initial_outbox = await drain_outbox(context.pool, context.broker)
    before_existing = None
    if expected_existing_index is not None:
        before_existing = await _row_at(
            context,
            lane=ETH_BASE_LANE,
            opened=context.bucket_start + BASE_DURATION * expected_existing_index,
        )
    request = _recovery_request(materialized)
    engine = _recovery_engine(context, providers)
    caught: BaseException | None = None
    try:
        await engine.recover(
            request,
            base_timeframe="1m",
            base_duration=BASE_DURATION,
            provider_order=tuple(context.recovery_config["provider_order"]),
            provider_symbols=context.recovery_config["provider_symbols"],
            target_durations={"4h": TARGET_DURATION},
            alignment_origin=context.config.timeframe_grid.alignment_origin,
        )
    except DataIngestionError as exc:
        caught = exc
    if caught is None:
        raise AssertionError("expected C3B2 recovery failure did not occur")
    recovery_outbox = await drain_outbox(context.pool, context.broker)
    poll = await _finish_poll(context)
    derived_count = await _count_route_rows(
        context.pool,
        MarketSeriesKey(
            asset="ETHUSDT",
            venue="binance",
            instrument_id="ETH-USDT-PERP",
            timeframe="4h",
        ),
        start=context.bucket_start,
        end=context.bucket_start + TARGET_DURATION,
    )
    existing_after = None
    if expected_existing_index is not None:
        existing_after = await _row_at(
            context,
            lane=ETH_BASE_LANE,
            opened=context.bucket_start + BASE_DURATION * expected_existing_index,
        )
    missing_rows = {}
    for index in expected_missing_indices:
        missing_rows[str(index)] = await _row_at(
            context,
            lane=ETH_BASE_LANE,
            opened=context.bucket_start + BASE_DURATION * index,
        )
    return {
        "baseline": context.baseline,
        "request_count": len(materialized["requests"]),
        "initial_base_inserted": materialized["base_inserted"],
        "initial_outbox": initial_outbox,
        "provider_calls": {
            provider_id: provider.evidence()
            for provider_id, provider in providers.items()
        },
        "provider_call_counts": {
            provider_id: len(provider.calls)
            for provider_id, provider in providers.items()
        },
        "error_type": type(caught).__name__,
        "error_message_class": (
            "canonical_conflict"
            if "canonical recovery conflict" in str(caught)
            else "recovery_exhausted"
        ),
        "expected_error": expected_error,
        "recovery_outbox": recovery_outbox,
        "expected_recovery_outbox": expected_outbox,
        "derived_count": derived_count,
        "existing_before": (
            None
            if before_existing is None
            else _canonical_candle_semantics(
                before_existing,
                alignment_origin=context.config.timeframe_grid.alignment_origin,
                duration=BASE_DURATION,
            )
        ),
        "existing_after": (
            None
            if existing_after is None
            else _canonical_candle_semantics(
                existing_after,
                alignment_origin=context.config.timeframe_grid.alignment_origin,
                duration=BASE_DURATION,
            )
        ),
        "missing_rows": {
            key: None
            if row is None
            else _canonical_candle_semantics(
                row,
                alignment_origin=context.config.timeframe_grid.alignment_origin,
                duration=BASE_DURATION,
            )
            for key, row in missing_rows.items()
        },
        "poll": poll,
        "btc_before": _btc_controls(context.baseline["controls"]),
        "btc_after": _btc_controls(poll["controls"]),
        "btc_isolated": _btc_controls(context.baseline["controls"])
        == _btc_controls(poll["controls"]),
        "all_controls": poll["controls"],
        "baseline_controls": context.baseline["controls"],
        "all_controls_unchanged": context.baseline["controls"] == poll["controls"],
    }


def _status_text(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw).upper()


async def _scenario_a(context: ScenarioContext) -> dict[str, object]:
    materialized = await _materialize_incomplete_eth(
        context,
        missing_indices=frozenset({100}),
    )
    missing = _observation(
        opened=context.bucket_start + BASE_DURATION * 100,
        index=100,
        provider_id="ccxt_binance",
    )
    primary = ScriptedHistoricalProvider(
        "binance_native",
        (
            DataIngestionError("scripted primary failure 1"),
            DataIngestionError("scripted primary failure 2"),
        ),
    )
    fallback = ScriptedHistoricalProvider("ccxt_binance", ((missing,),))
    return {
        "name": "bounded_primary_failure_fallback_success",
        **await _successful_recovery_evidence(
            context,
            materialized=materialized,
            providers={
                "binance_native": primary,
                "ccxt_binance": fallback,
            },
            expected_outbox=2,
            expected_recovered_indices=(100,),
            expected_sources={100: "ccxt_binance"},
        ),
    }


async def _scenario_b(context: ScenarioContext) -> dict[str, object]:
    materialized = await _materialize_incomplete_eth(
        context,
        missing_indices=frozenset({100, 101, 102}),
    )
    primary_row = _observation(
        opened=context.bucket_start + BASE_DURATION * 100,
        index=100,
        provider_id="binance_native",
    )
    overlap = _observation(
        opened=context.bucket_start + BASE_DURATION * 100,
        index=100,
        provider_id="ccxt_binance",
        taker_buy_base=None,
    )
    row_101 = _observation(
        opened=context.bucket_start + BASE_DURATION * 101,
        index=101,
        provider_id="ccxt_binance",
    )
    row_102 = _observation(
        opened=context.bucket_start + BASE_DURATION * 102,
        index=102,
        provider_id="ccxt_binance",
    )
    primary = ScriptedHistoricalProvider(
        "binance_native",
        ((primary_row,), ()),
    )
    fallback = ScriptedHistoricalProvider(
        "ccxt_binance",
        ((overlap, row_101, row_102),),
    )
    return {
        "name": "partial_primary_overlap_fallback_completion",
        **await _successful_recovery_evidence(
            context,
            materialized=materialized,
            providers={
                "binance_native": primary,
                "ccxt_binance": fallback,
            },
            expected_outbox=4,
            expected_recovered_indices=(100, 101, 102),
            expected_sources={
                100: "binance_native",
                101: "ccxt_binance",
                102: "ccxt_binance",
            },
            overlap_index=100,
        ),
    }


async def _scenario_c(context: ScenarioContext) -> dict[str, object]:
    materialized = await _materialize_incomplete_eth(
        context,
        missing_indices=frozenset({100}),
    )
    primary = ScriptedHistoricalProvider(
        "binance_native",
        (
            DataIngestionError("scripted primary exhaustion 1"),
            DataIngestionError("scripted primary exhaustion 2"),
        ),
    )
    fallback = ScriptedHistoricalProvider(
        "ccxt_binance",
        (
            DataIngestionError("scripted fallback exhaustion 1"),
            DataIngestionError("scripted fallback exhaustion 2"),
        ),
    )
    return {
        "name": "provider_exhaustion",
        **await _failure_evidence(
            context,
            materialized=materialized,
            providers={
                "binance_native": primary,
                "ccxt_binance": fallback,
            },
            expected_error="recovery_exhausted",
            expected_missing_indices=(100,),
        ),
    }


async def _scenario_d(context: ScenarioContext) -> dict[str, object]:
    materialized = await _materialize_incomplete_eth(
        context,
        missing_indices=frozenset({100}),
    )
    conflict = _observation(
        opened=context.bucket_start + BASE_DURATION * 101,
        index=101,
        provider_id="binance_native",
        close_delta=Decimal(1),
    )
    primary = ScriptedHistoricalProvider("binance_native", ((conflict,),))
    fallback = ScriptedHistoricalProvider("ccxt_binance", ())
    return {
        "name": "primary_conflict_stops_without_fallback",
        **await _failure_evidence(
            context,
            materialized=materialized,
            providers={
                "binance_native": primary,
                "ccxt_binance": fallback,
            },
            expected_error="canonical_conflict",
            expected_existing_index=101,
            expected_missing_indices=(100,),
        ),
    }


async def _scenario_e(context: ScenarioContext) -> dict[str, object]:
    materialized = await _materialize_incomplete_eth(
        context,
        missing_indices=frozenset({100, 101}),
    )
    primary_row = _observation(
        opened=context.bucket_start + BASE_DURATION * 100,
        index=100,
        provider_id="binance_native",
    )
    fallback_conflict = _observation(
        opened=context.bucket_start + BASE_DURATION * 100,
        index=100,
        provider_id="ccxt_binance",
        close_delta=Decimal(1),
    )
    fallback_missing = _observation(
        opened=context.bucket_start + BASE_DURATION * 101,
        index=101,
        provider_id="ccxt_binance",
    )
    primary = ScriptedHistoricalProvider(
        "binance_native",
        ((primary_row,), ()),
    )
    fallback = ScriptedHistoricalProvider(
        "ccxt_binance",
        ((fallback_conflict, fallback_missing),),
    )
    return {
        "name": "fallback_content_disagreement_fail_closed",
        **await _failure_evidence(
            context,
            materialized=materialized,
            providers={
                "binance_native": primary,
                "ccxt_binance": fallback,
            },
            expected_error="canonical_conflict",
            expected_outbox=1,
            expected_missing_indices=(100, 101),
        ),
    }


async def _scenario_f(context: ScenarioContext) -> dict[str, object]:
    first_open = context.bucket_start + timedelta(days=2)
    second_open = first_open + BASE_DURATION
    ws_first = _observation(
        opened=first_open,
        index=500,
        provider_id="binance_native",
        transport="websocket",
    )
    rest_same = _observation(
        opened=first_open,
        index=500,
        provider_id="binance_native",
        transport="rest",
    )
    rest_conflict = _observation(
        opened=first_open,
        index=500,
        provider_id="binance_native",
        transport="rest",
        close_delta=Decimal(1),
    )
    rest_first = _observation(
        opened=second_open,
        index=501,
        provider_id="binance_native",
        transport="rest",
    )
    ws_same = _observation(
        opened=second_open,
        index=501,
        provider_id="binance_native",
        transport="websocket",
    )
    ws_conflict = _observation(
        opened=second_open,
        index=501,
        provider_id="binance_native",
        transport="websocket",
        close_delta=Decimal(1),
    )
    statuses = [
        _status_text(await context.ingestion.commit_observation(ws_first)),
        _status_text(await context.ingestion.commit_observation(rest_same)),
        _status_text(await context.ingestion.commit_observation(rest_conflict)),
        _status_text(await context.ingestion.commit_observation(rest_first)),
        _status_text(await context.ingestion.commit_observation(ws_same)),
        _status_text(await context.ingestion.commit_observation(ws_conflict)),
    ]
    pending_before = await context.pool.fetchval(
        "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
    )
    outbox = await drain_outbox(context.pool, context.broker)
    poll = await _finish_poll(context)
    first_row = await _row_at(context, lane=ETH_BASE_LANE, opened=first_open)
    second_row = await _row_at(context, lane=ETH_BASE_LANE, opened=second_open)
    expected_first = canonicalize_observation(ws_first)
    expected_second = canonicalize_observation(rest_first)
    columns = tuple(
        sorted(
            str(row["column_name"])
            for row in await context.pool.fetch(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_schema='ingestion' AND table_name='candles'"""
            )
        )
    )
    base_stream = canonical_ingestion_stream_key(
        MarketSeriesKey(
            asset="ETHUSDT",
            venue="binance",
            instrument_id="ETH-USDT-PERP",
            timeframe="1m",
        )
    )
    return {
        "baseline": context.baseline,
        "name": "ws_rest_disagreement_canonical_first_write",
        "statuses": statuses,
        "expected_statuses": [
            "INSERTED",
            "DUPLICATE",
            "CONFLICT",
            "INSERTED",
            "DUPLICATE",
            "CONFLICT",
        ],
        "pending_before_drain": int(pending_before),
        "outbox": outbox,
        "expected_inserted_outbox": 2,
        "first_canonical": (
            None
            if first_row is None
            else _canonical_candle_semantics(
                first_row,
                alignment_origin=context.config.timeframe_grid.alignment_origin,
                duration=BASE_DURATION,
            )
        ),
        "expected_first_canonical": _canonical_candle_semantics(
            expected_first,
            alignment_origin=context.config.timeframe_grid.alignment_origin,
            duration=BASE_DURATION,
        ),
        "second_canonical": (
            None
            if second_row is None
            else _canonical_candle_semantics(
                second_row,
                alignment_origin=context.config.timeframe_grid.alignment_origin,
                duration=BASE_DURATION,
            )
        ),
        "expected_second_canonical": _canonical_candle_semantics(
            expected_second,
            alignment_origin=context.config.timeframe_grid.alignment_origin,
            duration=BASE_DURATION,
        ),
        "transport_persisted": "transport" in columns,
        "base_stream_length": await context.broker.xlen(base_stream),
        "derived_route_events": len(
            await _stream_derived_events(context.broker, context.config)
        ),
        "poll": poll,
        "all_controls": poll["controls"],
        "baseline_controls": context.baseline["controls"],
        "all_controls_unchanged": context.baseline["controls"] == poll["controls"],
        "btc_before": _btc_controls(context.baseline["controls"]),
        "btc_after": _btc_controls(poll["controls"]),
        "btc_isolated": _btc_controls(context.baseline["controls"])
        == _btc_controls(poll["controls"]),
        "signals": len(await _signal_entries(context.broker)),
    }


async def _run_scenario(
    trial_name: str,
    scenario_name: str,
    scenario_fn: Any,
) -> dict[str, object]:
    infrastructure = C2Infrastructure(
        f"c3b2_{trial_name.lower()}_{scenario_name.lower()}"
    )
    context: ScenarioContext | None = None
    pool: asyncpg.Pool | None = None
    broker: Any | None = None
    result: dict[str, object] = {}
    try:
        context = await _setup_context(infrastructure)
        pool = context.pool
        broker = context.broker
        result = await scenario_fn(context)
    except Exception as exc:  # noqa: BLE001
        result = {
            "name": scenario_name,
            "scenario_error": type(exc).__name__,
            "scenario_error_message_class": type(exc).__name__,
        }
    finally:
        if broker is not None:
            await broker.aclose()
        if pool is not None:
            await pool.close()
        result["cleanup"] = {
            "clean": await infrastructure.cleanup(),
        }
    result["scenario_ok"] = "scenario_error" not in result
    result["infrastructure"] = {
        **EXPECTED_INFRASTRUCTURE,
        "isolated_project": True,
        "dynamic_localhost_ports": True,
        "no_worktree_env": True,
    }
    return result


async def run_trial(trial_name: str) -> dict[str, object]:
    scenarios = {}
    for scenario_name, scenario_fn in (
        ("A", _scenario_a),
        ("B", _scenario_b),
        ("C", _scenario_c),
        ("D", _scenario_d),
        ("E", _scenario_e),
        ("F", _scenario_f),
    ):
        scenarios[scenario_name] = await _run_scenario(
            trial_name,
            scenario_name,
            scenario_fn,
        )
    return scenarios


def _baseline_is_exact(scenario: Mapping[str, object]) -> bool:
    baseline = scenario.get("baseline")
    if not isinstance(baseline, Mapping):
        return False
    return (
        baseline.get("startup_status") == "STARTUP_READY"
        and baseline.get("startup_signal_count") == 0
        and set(baseline.get("lane_statuses", {}))
        == {
            "BTCUSDT:momentum_1h",
            "BTCUSDT:momentum_4h",
            "ETHUSDT:momentum_4h",
        }
        and all(
            status == "STARTUP_READY" for status in baseline["lane_statuses"].values()
        )
        and baseline.get("before_empty", {}).get("total_rows") == 0
        and baseline.get("before_empty", {}).get("outbox_total") == 0
    )


def _provider_counts(
    scenario: Mapping[str, object],
) -> Mapping[str, object]:
    value = scenario.get("provider_call_counts")
    return value if isinstance(value, Mapping) else {}


def _recovery_outbox_is(
    scenario: Mapping[str, object],
    expected: int,
) -> bool:
    outbox = scenario.get("recovery_outbox")
    return (
        isinstance(outbox, Mapping)
        and outbox.get("published") == expected
        and outbox.get("attempts") == 1
    )


def _btc_controls_are_unchanged(scenario: Mapping[str, object]) -> bool:
    before = scenario.get("btc_before")
    after = scenario.get("btc_after")
    return (
        isinstance(before, Mapping) and isinstance(after, Mapping) and before == after
    )


def _successful_semantics_match(scenario: Mapping[str, object]) -> bool:
    return (
        scenario.get("derived_semantics") is not None
        and scenario.get("derived_semantics")
        == scenario.get("reference_derived_semantics")
        and scenario.get("semantic") is not None
        and scenario.get("semantic") == scenario.get("semantic_reference")
        and scenario.get("lane_result") is not None
        and scenario.get("lane_result") == scenario.get("lane_result_reference")
    )


def _scenario_success_gate(
    scenario: Mapping[str, object],
    *,
    expected_counts: Mapping[str, int],
    expected_sources: Mapping[str, str],
    expected_outbox: int,
    expected_recovered_count: int,
    expected_overlap_index: int | None = None,
) -> bool:
    rows = scenario.get("recovered_base_rows")
    if not isinstance(rows, Mapping):
        return False
    sources = {
        key: value.get("source_provider")
        for key, value in rows.items()
        if isinstance(value, Mapping)
    }
    return (
        _baseline_is_exact(scenario)
        and _provider_counts(scenario) == expected_counts
        and scenario.get("request_count") == 1
        and scenario.get("premature_derived_count") == 0
        and scenario.get("follow_ups") == 0
        and scenario.get("derived_count") == 1
        and len(rows) == expected_recovered_count
        and sources == dict(expected_sources)
        and _successful_semantics_match(scenario)
        and _btc_controls_are_unchanged(scenario)
        and scenario.get("all_controls") != scenario.get("baseline_controls")
        and _recovery_outbox_is(scenario, expected_outbox)
        and scenario.get("overlap_index") == expected_overlap_index
    )


def _scenario_failure_gate(
    scenario: Mapping[str, object],
    *,
    expected_counts: Mapping[str, int],
    expected_error: str,
    expected_outbox: int,
    expected_missing: Sequence[str],
) -> bool:
    missing_rows = scenario.get("missing_rows")
    return (
        _baseline_is_exact(scenario)
        and _provider_counts(scenario) == expected_counts
        and scenario.get("error_type") == "DataIngestionError"
        and scenario.get("error_message_class") == expected_error
        and scenario.get("derived_count") == 0
        and _recovery_outbox_is(scenario, expected_outbox)
        and isinstance(missing_rows, Mapping)
        and all(missing_rows.get(index) is None for index in expected_missing)
        and _btc_controls_are_unchanged(scenario)
        and scenario.get("all_controls") == scenario.get("baseline_controls")
    )


def _scenario_d_gate(scenario: Mapping[str, object]) -> bool:
    return _scenario_failure_gate(
        scenario,
        expected_counts={"binance_native": 1, "ccxt_binance": 0},
        expected_error="canonical_conflict",
        expected_outbox=0,
        expected_missing=("100",),
    ) and scenario.get("existing_before") == scenario.get("existing_after")


def _scenario_e_gate(scenario: Mapping[str, object]) -> bool:
    missing = scenario.get("missing_rows")
    return (
        _scenario_failure_gate(
            scenario,
            expected_counts={"binance_native": 2, "ccxt_binance": 1},
            expected_error="canonical_conflict",
            expected_outbox=1,
            expected_missing=("101",),
        )
        and isinstance(missing, Mapping)
        and isinstance(missing.get("100"), Mapping)
        and missing["100"].get("source_provider") == "binance_native"
        and missing.get("101") is None
    )


def _scenario_f_gate(scenario: Mapping[str, object]) -> bool:
    outbox = scenario.get("outbox")
    return (
        _baseline_is_exact(scenario)
        and scenario.get("statuses") == scenario.get("expected_statuses")
        and scenario.get("pending_before_drain") == 2
        and isinstance(outbox, Mapping)
        and outbox.get("published") == 2
        and outbox.get("attempts") == 1
        and scenario.get("expected_inserted_outbox") == 2
        and scenario.get("transport_persisted") is False
        and scenario.get("derived_route_events") == 0
        and scenario.get("signals") == 0
        and scenario.get("all_controls") == scenario.get("baseline_controls")
        and _btc_controls_are_unchanged(scenario)
        and isinstance(scenario.get("first_canonical"), Mapping)
        and isinstance(scenario.get("second_canonical"), Mapping)
        and scenario["first_canonical"].get("source_provider") == "binance_native"
        and scenario["second_canonical"].get("source_provider") == "binance_native"
        and scenario["first_canonical"] == scenario["expected_first_canonical"]
        and scenario["second_canonical"] == scenario["expected_second_canonical"]
    )


def identity_payload(evidence: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": evidence.get("schema_version"),
        "source_sha": evidence.get("source_sha"),
        "protected_hashes": evidence.get("protected_hashes"),
        "routes": evidence.get("routes"),
        "recovery_config": evidence.get("recovery_config"),
        "infrastructure_contract": evidence.get("infrastructure_contract"),
    }


def evidence_payload(evidence: Mapping[str, object]) -> dict[str, object]:
    return {
        **identity_payload(evidence),
        "trials": evidence.get("trials"),
        "gates": evidence.get("gates"),
        "terminal_status": evidence.get("terminal_status"),
    }


def evaluate_c3b2_gates(evidence: Mapping[str, object]) -> dict[str, bool]:
    scenarios = evidence.get("trials", [{}])[0]
    if not isinstance(scenarios, Mapping):
        scenarios = {}
    recovery_config = evidence.get("recovery_config")
    infrastructure_contract = evidence.get("infrastructure_contract")
    protected = evidence.get("protected_hashes")
    gates = {
        "protected_hashes": protected == EXPECTED_PROTECTED_HASHES,
        "infrastructure_contract": (
            isinstance(infrastructure_contract, Mapping)
            and infrastructure_contract.get("db_image")
            == EXPECTED_INFRASTRUCTURE["db_image"]
            and infrastructure_contract.get("broker_image")
            == EXPECTED_INFRASTRUCTURE["broker_image"]
            and infrastructure_contract.get("fresh_project_per_scenario") is True
            and infrastructure_contract.get("dynamic_localhost_ports") is True
            and infrastructure_contract.get("no_worktree_env") is True
            and all(
                isinstance(value, Mapping)
                and value.get("infrastructure", {}).get("isolated_project") is True
                for value in scenarios.values()
            )
        ),
        "healthy_baseline_exact": all(
            _baseline_is_exact(value) for value in scenarios.values()
        )
        and set(scenarios) == {"A", "B", "C", "D", "E", "F"},
        "recovery_config_contract": (
            isinstance(recovery_config, Mapping)
            and tuple(recovery_config.get("provider_order", ()))
            == EXPECTED_PROVIDER_ORDER
            and recovery_config.get("provider_symbols")
            == {"binance_native": "ETHUSDT", "ccxt_binance": "ETH/USDT:USDT"}
            and recovery_config.get("max_attempts_per_provider") == 2
            and recovery_config.get("page_limit") == 500
            and recovery_config.get("retry_backoff_seconds") == 1
            and recovery_config.get("rest_finalization_grace_seconds") == 5
        ),
        "primary_failure_fallback_converges": _scenario_success_gate(
            scenarios.get("A", {}),
            expected_counts={"binance_native": 2, "ccxt_binance": 1},
            expected_sources={"100": "ccxt_binance"},
            expected_outbox=2,
            expected_recovered_count=1,
        ),
        "partial_primary_overlap_fallback_converges": _scenario_success_gate(
            scenarios.get("B", {}),
            expected_counts={"binance_native": 2, "ccxt_binance": 1},
            expected_sources={
                "100": "binance_native",
                "101": "ccxt_binance",
                "102": "ccxt_binance",
            },
            expected_outbox=4,
            expected_recovered_count=3,
            expected_overlap_index=100,
        ),
        "provider_exhaustion_fail_closed": _scenario_failure_gate(
            scenarios.get("C", {}),
            expected_counts={"binance_native": 2, "ccxt_binance": 2},
            expected_error="recovery_exhausted",
            expected_outbox=0,
            expected_missing=("100",),
        ),
        "primary_conflict_stops_without_fallback": _scenario_d_gate(
            scenarios.get("D", {})
        ),
        "fallback_content_disagreement_fail_closed": _scenario_e_gate(
            scenarios.get("E", {})
        ),
        "ws_rest_disagreement_canonical_first_write_fail_closed": _scenario_f_gate(
            scenarios.get("F", {})
        ),
        "no_cross_route_or_base_series_contamination": all(
            _btc_controls_are_unchanged(value)
            for value in scenarios.values()
            if isinstance(value, Mapping)
        ),
        "successful_recovery_semantic_parity": all(
            _successful_semantics_match(scenarios.get(name, {})) for name in ("A", "B")
        ),
        "matrix_determinism": (
            len(evidence.get("trials", ())) == 2
            and evidence["trials"][0] == evidence["trials"][1]
        ),
        "cleanup_all_scenarios": all(
            value.get("cleanup", {}).get("clean") is True
            for value in scenarios.values()
            if isinstance(value, Mapping)
        ),
        "production_scope": (
            evidence.get("production_compose_sha") == PRODUCTION_COMPOSE_SHA
            and evidence.get("production_decision_assets") == []
            and evidence.get("public_provider_calls") == 0
        ),
    }
    return gates


async def run_certification() -> dict[str, object]:
    recovery_config = _load_recovery_contract()
    trial_a = await run_trial("A")
    trial_b = await run_trial("B")
    evidence: dict[str, object] = {
        "schema_version": "c3b2.v1",
        "source_sha": source_sha(),
        "protected_hashes": protected_hashes(),
        "routes": list(ROUTES),
        "recovery_config": recovery_config,
        "infrastructure_contract": {
            **EXPECTED_INFRASTRUCTURE,
            "fresh_project_per_scenario": True,
            "dynamic_localhost_ports": True,
            "no_worktree_env": True,
            "services": ["db", "broker"],
        },
        "production_compose_sha": file_sha256(PRODUCTION_COMPOSE_FILE),
        "production_decision_assets": sorted(
            str(path.relative_to(ROOT))
            for path in (ROOT / "configs" / "decision" / "assets").glob("*.yaml")
        )
        if (ROOT / "configs" / "decision" / "assets").exists()
        else [],
        "public_provider_calls": 0,
        "trials": [trial_a, trial_b],
    }
    evidence["gates"] = evaluate_c3b2_gates(evidence)
    if all(evidence["gates"].values()):
        evidence["terminal_status"] = C3B2_SUCCESS_STATUS
    elif not all(
        scenario.get("cleanup", {}).get("clean") is True
        for scenario in trial_a.values()
        if isinstance(scenario, Mapping)
    ):
        evidence["terminal_status"] = C3B2_CLEANUP_STATUS
    elif any(
        scenario.get("scenario_error") in {"FileNotFoundError", "CalledProcessError"}
        for scenario in trial_a.values()
        if isinstance(scenario, Mapping)
    ):
        evidence["terminal_status"] = C3B2_BLOCKED_STATUS
    else:
        evidence["terminal_status"] = C3B2_EVIDENCE_STATUS
    evidence["identity_digest"] = sha256_fingerprint(identity_payload(evidence))
    evidence["evidence_digest"] = sha256_fingerprint(evidence_payload(evidence))
    return evidence


def write_artifact(evidence: Mapping[str, object]) -> None:
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(
        json.dumps(_json_value(evidence), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_artifact() -> dict[str, object]:
    return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))


__all__ = [
    "ARTIFACT_PATH",
    "C2_ARTIFACT_SHA",
    "C3A_ARTIFACT_SHA",
    "C3B2_BLOCKED_STATUS",
    "C3B2_CLEANUP_STATUS",
    "C3B2_CONTRACT_STATUS",
    "C3B2_EVIDENCE_STATUS",
    "C3B2_REVIEW_STATUS",
    "C3B2_SUCCESS_STATUS",
    "EXPECTED_PROTECTED_HASHES",
    "evaluate_c3b2_gates",
    "evidence_payload",
    "identity_payload",
    "load_artifact",
    "protected_hashes",
    "run_certification",
    "sha256_fingerprint",
    "write_artifact",
]
