"""Offline M4 certification for the explicit Momentum Decision composition."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import resource
import subprocess
import threading
import time
import tracemalloc
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from apps.decision_app.composition import build_production_composition
from apps.decision_app.domain.market_state import (
    MarketSeriesKey,
    compile_bar_store_capacities,
)
from apps.decision_app.domain.view import DecisionViewBuilder
from apps.decision_app.features.momentum import calculate_macd, calculate_rsi
from apps.decision_app.features.momentum_integration import (
    MOMENTUM_M3_ARTIFACT_SHA256,
    MOMENTUM_MACD_FEATURE_NAME,
    MOMENTUM_ROUTE_PROFILE_LOCKS,
    MOMENTUM_RSI_FEATURE_NAME,
    momentum_route_profile_digest,
    parse_momentum_binding_parameters,
)
from apps.decision_app.features.planning import compile_feature_bar_store_capacities
from apps.decision_app.runtime.live import LiveDecisionRuntime
from apps.decision_app.runtime.startup import DecisionStartupCoordinator
from apps.decision_app.settings import DecisionConfig, load_decision_config
from apps.decision_app.storage.checkpoints import InMemoryCheckpointRepository
from apps.decision_app.storage.market_history import (
    CanonicalMarketRecord,
    InMemoryCanonicalMarketHistoryRepository,
)
from apps.decision_app.transport.ingestion import canonical_ingestion_stream_key
from apps.decision_app.transport.signals import ValkeySignalPublisher
from libs.common.config import ConfigManager
from libs.contracts.decision import CausalBarView
from libs.contracts.serialization import valkey_decode
from libs.contracts.signal import TradeSignal
from libs.models.momentum.core import MomentumObservation, evaluate_momentum

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "decision" / "fixtures" / "momentum_m4"
M3_ARTIFACT = (
    ROOT
    / "artifacts"
    / "decision_m3"
    / ("m3_momentum_feature_semantics_certification.json")
)
D10_ARTIFACT = (
    ROOT / "artifacts" / "decision_d10" / ("d10_resource_capacity_certification.json")
)

D10_ARTIFACT_SHA256 = "2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459"


def _series_label(key: MarketSeriesKey) -> str:
    return f"{key.asset}/{key.timeframe}"


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _source_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _load_config() -> DecisionConfig:
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(ROOT / "configs"))
    try:
        return load_decision_config(
            manager,
            global_file=FIXTURE_ROOT / "global.yaml",
            assets_directory=FIXTURE_ROOT / "assets",
        )
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()


def _validate_m3_identity(config: DecisionConfig) -> dict[str, Any]:
    raw = M3_ARTIFACT.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MOMENTUM_M3_ARTIFACT_SHA256:
        raise RuntimeError("protected M3 artifact hash does not match the lock")
    artifact = json.loads(raw)
    routes = {
        f"{item['asset']}/{item['timeframe']}": item for item in artifact["routes"]
    }
    for lane in config.lane_specs():
        route = f"{lane.asset}/{lane.decision_timeframe}"
        route_artifact = routes.get(route)
        if route_artifact is None:
            raise RuntimeError(f"M3 artifact has no route evidence for {route}")
        parameters = next(
            binding.parameters
            for binding in lane.bindings
            if binding.slot_name == "primary"
        )
        envelope = parse_momentum_binding_parameters(
            parameters,
            expected_asset=lane.asset,
            expected_decision_timeframe=lane.decision_timeframe,
        )
        if route_artifact["momentum_parameters"] != envelope.model_config.to_mapping():
            raise RuntimeError(f"M3 model parameters drifted for {route}")
        horizon = route_artifact["recommended_candidate"]["horizon"]
        if horizon["rsi_bars"] != envelope.feature_profile.rsi_history_bars:
            raise RuntimeError(f"M3 RSI history drifted for {route}")
        if horizon["macd_bars"] != envelope.feature_profile.macd_history_bars:
            raise RuntimeError(f"M3 MACD history drifted for {route}")
        digest = momentum_route_profile_digest(
            asset=envelope.asset,
            decision_timeframe=envelope.decision_timeframe,
            model_config=envelope.model_config,
            feature_profile=envelope.feature_profile,
        )
        if digest != MOMENTUM_ROUTE_PROFILE_LOCKS[route]:
            raise RuntimeError(f"M3 route profile lock drifted for {route}")
    return artifact


def _series_keys(config: DecisionConfig) -> tuple[MarketSeriesKey, ...]:
    return tuple(
        sorted(
            {
                MarketSeriesKey(
                    asset=lane.asset,
                    venue=lane.venue,
                    instrument_id=lane.instrument_id,
                    timeframe=lane.decision_timeframe,
                )
                for lane in config.lane_specs()
            },
            key=lambda key: (key.asset, key.timeframe),
        )
    )


def _bars(key: MarketSeriesKey, grid, count: int = 544) -> tuple[CausalBarView, ...]:
    duration = grid.duration(key.timeframe)
    start = grid.alignment_origin + duration * 200_000
    result: list[CausalBarView] = []
    for index in range(count):
        opened = start + duration * index
        closed = opened + duration
        close = Decimal(100) + Decimal(index) / Decimal(10)
        result.append(
            CausalBarView(
                timeframe=key.timeframe,
                bar_open_at=opened,
                bar_close_at=closed,
                market_as_of=closed,
                open=close,
                high=close + Decimal(1),
                low=close - Decimal(1),
                close=close,
                volume=Decimal(10),
                taker_buy_base=Decimal(4),
                closed=True,
            )
        )
    return tuple(result)


def _fields(bar: CausalBarView, key: MarketSeriesKey) -> dict[str, str]:
    payload = {
        "venue": key.venue,
        "instrument_id": key.instrument_id,
        "timeframe": key.timeframe,
        "open_time": bar.bar_open_at.isoformat().replace("+00:00", "Z"),
        "close_time": bar.bar_close_at.isoformat().replace("+00:00", "Z"),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": str(bar.volume),
        "taker_buy_base": str(bar.taker_buy_base),
        "source_type": "provider",
        "source_provider": "binance",
        "source_timeframe": None,
    }
    return {
        "event_id": f"m4-{key.asset}-{key.timeframe}-{bar.bar_open_at.isoformat()}",
        "event_type": "candle.committed",
        "schema_version": "1",
        "producer": "ingestion",
        "occurred_at": bar.bar_close_at.isoformat().replace("+00:00", "Z"),
        "payload": json.dumps(payload),
    }


class _StartupStream:
    async def xrevrange(self, *_args: object, **_kwargs: object) -> list[object]:
        return []


class _LiveStream(_StartupStream):
    def __init__(self) -> None:
        self.pending: tuple[str, str, Mapping[object, object]] | None = None

    async def xread(
        self,
        _streams: Mapping[str, str],
        *,
        count: int,
        block: int,
    ) -> list[tuple[str, list[tuple[str, Mapping[object, object]]]]]:
        if self.pending is None:
            return []
        stream_key, stream_id, fields = self.pending
        self.pending = None
        assert count == 10
        assert block == 1000
        return [(stream_key, [(stream_id, fields)])]


class _RecordingPublisher:
    def __init__(self, publisher: ValkeySignalPublisher) -> None:
        self.publisher = publisher
        self.envelopes: list[Any] = []

    async def publish(self, envelope):
        self.envelopes.append(envelope)
        return await self.publisher.publish(envelope)


class _RecordingCanonicalHistoryRepository:
    """Mutable deterministic history seam with observed fetch evidence."""

    def __init__(
        self,
        histories: Mapping[MarketSeriesKey, Sequence[CausalBarView]],
        timeframe_grid,
    ) -> None:
        self._histories = {key: tuple(values) for key, values in histories.items()}
        self._grid = timeframe_grid
        self.fetch_bars_calls: list[dict[str, object]] = []
        self._delegate = self._build_delegate()

    def _build_delegate(self) -> InMemoryCanonicalMarketHistoryRepository:
        records = {
            key: tuple(
                CanonicalMarketRecord(
                    series_key=key,
                    bar=bar,
                    source_type="provider",
                    source_provider="binance",
                    source_timeframe=None,
                )
                for bar in values
            )
            for key, values in self._histories.items()
        }
        return InMemoryCanonicalMarketHistoryRepository(
            self._histories,
            timeframe_grid=self._grid,
            records_by_series=records,
        )

    def append(self, key: MarketSeriesKey, bar: CausalBarView) -> None:
        self._histories[key] = (*self._histories[key], bar)
        self._delegate = self._build_delegate()

    async def fetch_latest_cutoff(self, key: MarketSeriesKey):
        return await self._delegate.fetch_latest_cutoff(key)

    async def fetch_record_at(self, key: MarketSeriesKey, bar_open_at):
        return await self._delegate.fetch_record_at(key, bar_open_at)

    async def fetch_bars(self, key: MarketSeriesKey, **kwargs: object):
        self.fetch_bars_calls.append(
            {
                "series": _series_label(key),
                "limit": kwargs.get("limit"),
                "start": _jsonable(kwargs.get("start")),
                "through": _jsonable(kwargs.get("through")),
            }
        )
        return await self._delegate.fetch_bars(key, **kwargs)


class _SignalClient:
    def __init__(self) -> None:
        self.entries: dict[str, dict[str, Mapping[object, object]]] = {}
        self.fail_xadd = False

    async def xrange(self, stream: str, minimum: str, maximum: str):
        return [
            (entry_id, fields)
            for entry_id, fields in self.entries.get(stream, {}).items()
            if entry_id == minimum == maximum
        ]

    async def xrevrange(self, stream: str, *_args: object, count: int = 1):
        values = self.entries.get(stream, {})
        ordered = sorted(
            values,
            key=lambda value: tuple(int(part) for part in value.split("-")),
            reverse=True,
        )
        return [(entry_id, values[entry_id]) for entry_id in ordered[:count]]

    async def xadd(
        self,
        stream: str,
        fields: Mapping[object, object],
        *,
        id: str,
        maxlen: int,
        approximate: bool,
    ) -> str:
        del maxlen, approximate
        if self.fail_xadd:
            raise RuntimeError("isolated broker unavailable")
        self.entries.setdefault(stream, {})[id] = fields
        return id


async def _startup(
    config: DecisionConfig,
    composition,
    *,
    histories_override: Mapping[MarketSeriesKey, Sequence[CausalBarView]] | None = None,
    repository_factory: Callable[..., object] | None = None,
):
    histories = (
        dict(histories_override)
        if histories_override is not None
        else {key: _bars(key, config.timeframe_grid) for key in _series_keys(config)}
    )
    repository = (
        repository_factory(histories, config.timeframe_grid)
        if repository_factory is not None
        else InMemoryCanonicalMarketHistoryRepository(
            histories,
            timeframe_grid=config.timeframe_grid,
        )
    )
    result = await DecisionStartupCoordinator(
        decision_config=config,
        plugin_catalog=composition.plugin_catalog,
        feature_catalog=composition.feature_catalog,
        feature_policy=composition.feature_policy,
        data_policy=composition.data_policy,
        source_catalog=composition.data_source_catalog,
        runtime_plugin_catalog=composition.runtime_plugin_catalog,
        history_repository=repository,
        stream_client=_StartupStream(),
        checkpoint_repository=InMemoryCheckpointRepository(),
        data_resolver=composition.data_resolver,
        policy_catalog=composition.policy_catalog,
    ).start()
    return result, repository, histories


def _view_at(
    config: DecisionConfig,
    startup,
    lane,
    cutoff,
    *,
    input_read_cursor=None,
    lane_commit_watermark=None,
):
    key = MarketSeriesKey(
        asset=lane.asset,
        venue=lane.venue,
        instrument_id=lane.instrument_id,
        timeframe=lane.trigger_timeframe,
    )
    if input_read_cursor is None:
        input_read_cursor = startup.snapshot.input_cursors[
            canonical_ingestion_stream_key(key)
        ]
    if lane_commit_watermark is None:
        lane_commit_watermark = startup.snapshot.lane_watermarks[lane.lane_id]
    return DecisionViewBuilder(startup.bar_store, config.timeframe_grid).build(
        lane,
        startup.lane_requirements[lane.lane_id],
        cutoff,
        input_read_cursor=input_read_cursor,
        lane_commit_watermark=lane_commit_watermark,
    )


def _view(config: DecisionConfig, startup, lane):
    cutoff = startup.snapshot.lane_evidence[lane.lane_id].resume_cutoff
    return _view_at(config, startup, lane, cutoff)


def _next_bar(
    key: MarketSeriesKey,
    bars: Sequence[CausalBarView],
    grid,
) -> CausalBarView:
    previous = bars[-1]
    duration = grid.duration(key.timeframe)
    opened = previous.bar_close_at
    close = previous.close + Decimal("0.1")
    return CausalBarView(
        timeframe=key.timeframe,
        bar_open_at=opened,
        bar_close_at=opened + duration,
        market_as_of=opened + duration,
        open=previous.close,
        high=close + Decimal(1),
        low=previous.close - Decimal(1),
        close=close,
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        closed=True,
    )


def _prepared_evidence(prepared) -> dict[str, Any]:
    shared = prepared.feature_resolution.shared_features
    feature_values = {
        name: {
            "name": snapshot.name,
            "version": snapshot.version,
            "market_as_of": snapshot.market_as_of.isoformat(),
            "value": _jsonable(snapshot.value),
        }
        for name, snapshot in sorted(shared.items())
    }
    executed = [
        result.outcome
        for result in prepared.binding_results.values()
        if result.status == "EXECUTED" and result.outcome is not None
    ]
    if len(executed) != 1:
        raise RuntimeError("M4 Momentum evidence requires one executed outcome")
    outcome = executed[0]
    decision = outcome.decision
    return {
        "market_as_of": prepared.market_as_of.isoformat(),
        "feature_fingerprint": _digest(feature_values),
        "features": feature_values,
        "artifact": {
            "artifact_type": outcome.artifact.artifact_type,
            "market_as_of": outcome.artifact.market_as_of.isoformat(),
            "value": _jsonable(outcome.artifact.value),
        },
        "decision": None
        if decision is None
        else {
            "binding_id": decision.binding_id,
            "market_as_of": decision.market_as_of.isoformat(),
            "signal_time": decision.signal_time.isoformat(),
            "direction_hint": decision.direction_hint,
            "score": decision.score,
            "conviction": decision.conviction,
        },
    }


async def _measure_route_reconstruction(
    config: DecisionConfig,
    composition,
    base_histories: Mapping[MarketSeriesKey, Sequence[CausalBarView]],
    lane,
) -> dict[str, Any]:
    key = MarketSeriesKey(
        asset=lane.asset,
        venue=lane.venue,
        instrument_id=lane.instrument_id,
        timeframe=lane.decision_timeframe,
    )
    sequential_startup, sequential_repository, histories = await _startup(
        config,
        composition,
        histories_override=base_histories,
        repository_factory=_RecordingCanonicalHistoryRepository,
    )
    next_bar = _next_bar(key, histories[key], config.timeframe_grid)
    stream = _LiveStream()
    stream.pending = (
        canonical_ingestion_stream_key(key),
        "1-0",
        _fields(next_bar, key),
    )
    sequential_client = _SignalClient()
    sequential_runtime = LiveDecisionRuntime(
        startup=sequential_startup,
        timeframe_grid=config.timeframe_grid,
        stream_client=stream,
        history_repository=sequential_repository,
        signal_publisher=ValkeySignalPublisher(sequential_client),
        batch_size=10,
        block_ms=1000,
        now_fn=lambda: next_bar.market_as_of + timedelta(seconds=1),
    )
    sequential_poll = await sequential_runtime.poll_once()
    sequential_result = sequential_poll.lane_results[lane.lane_id]
    live_lane = sequential_runtime.lanes[lane.lane_id]
    sequential_view = _view_at(
        config,
        sequential_startup,
        lane,
        next_bar.market_as_of,
        input_read_cursor=sequential_runtime.input.cursor_for(key),
        lane_commit_watermark=live_lane.finalizer.watermark,
    )
    sequential_prepared = await live_lane.runtime.prepare_live(
        sequential_view,
        resolver_knowledge_cutoff=next_bar.market_as_of + timedelta(seconds=1),
    )

    fresh_histories = dict(base_histories)
    fresh_histories[key] = (*fresh_histories[key], next_bar)
    fresh_startup, _fresh_repository, _ = await _startup(
        config,
        composition,
        histories_override=fresh_histories,
    )
    fresh_lane = next(
        item
        for item in fresh_startup.decision_plan.lanes
        if item.lane_id == lane.lane_id
    )
    fresh_view = _view(config, fresh_startup, fresh_lane)
    fresh_prepared = await fresh_startup.runtimes[lane.lane_id].prepare_live(
        fresh_view,
        resolver_knowledge_cutoff=fresh_view.market_as_of + timedelta(seconds=1),
    )
    fresh_publication_client = _SignalClient()
    fresh_publisher = _RecordingPublisher(
        ValkeySignalPublisher(fresh_publication_client)
    )
    sequential_evidence = _prepared_evidence(sequential_prepared)
    fresh_evidence = _prepared_evidence(fresh_prepared)
    feature_equal = sequential_evidence["features"] == fresh_evidence["features"]
    outcome_equal = sequential_evidence["artifact"] == fresh_evidence["artifact"] and (
        sequential_evidence["decision"] == fresh_evidence["decision"]
    )
    publication_count = sum(
        len(values) for values in sequential_client.entries.values()
    )
    reconstruction_status = (
        sequential_result.status == "LIVE"
        and sequential_result.trigger_cutoff == next_bar.market_as_of
        and fresh_startup.snapshot.status == "STARTUP_READY"
        and feature_equal
        and outcome_equal
        and fresh_startup.snapshot.lane_evidence[lane.lane_id].replay_step_count == 0
        and not fresh_publisher.envelopes
    )
    return {
        "route": f"{lane.asset}/{lane.decision_timeframe}",
        "cutoff": next_bar.market_as_of.isoformat(),
        "sequential": sequential_evidence,
        "fresh": fresh_evidence,
        "features_equal": feature_equal,
        "outcome_equal": outcome_equal,
        "replay_steps": fresh_startup.snapshot.lane_evidence[
            lane.lane_id
        ].replay_step_count,
        "publication_count_during_reconstruction": len(fresh_publisher.envelopes),
        "sequential_live_publication_count": publication_count,
        "status": "PASS" if reconstruction_status else "BLOCKED",
    }


def _configured_candle_days() -> int:
    document = yaml.safe_load((ROOT / "configs/ingestion/global.yaml").read_text())
    return int(document["ingestion"]["retention"]["candle_days"])


def build_retention_coverage(config: DecisionConfig) -> dict[str, Any]:
    required_bars = 544
    timeframe = "4h"
    duration = config.timeframe_grid.duration(timeframe)
    reference_open = config.timeframe_grid.alignment_origin + duration * 100
    next_boundary = reference_open + duration
    phases = {
        "boundary": next_boundary,
        "just_after": next_boundary + timedelta(seconds=1),
        "mid_bucket": next_boundary + duration / 2,
        "just_before_next_boundary": next_boundary
        + duration
        - timedelta(microseconds=1),
    }
    phase_evidence: list[dict[str, Any]] = []
    for phase, market_as_of in phases.items():
        latest_closed_cutoff = config.timeframe_grid.expected_closed_cutoff(
            timeframe,
            market_as_of,
        )
        latest_closed_open = latest_closed_cutoff - duration
        oldest_required_open = latest_closed_open - duration * (required_bars - 1)
        required_age = market_as_of - oldest_required_open
        phase_evidence.append(
            {
                "phase": phase,
                "market_as_of": market_as_of.isoformat(),
                "latest_closed_open_at": latest_closed_open.isoformat(),
                "oldest_required_open_at": oldest_required_open.isoformat(),
                "required_age_hours": required_age.total_seconds() / 3600,
            }
        )
    worst_required_hours = max(item["required_age_hours"] for item in phase_evidence)
    configured_days = _configured_candle_days()
    configured_hours = configured_days * 24
    minimum_days = math.ceil(worst_required_hours / 24)
    for item in phase_evidence:
        oldest_required_open = datetime.fromisoformat(item["oldest_required_open_at"])
        market_as_of = datetime.fromisoformat(item["market_as_of"])
        item["ninety_day_includes_oldest_open"] = (
            oldest_required_open >= market_as_of - timedelta(days=90)
        )
        item["configured_retention_includes_oldest_open"] = (
            oldest_required_open >= market_as_of - timedelta(days=configured_days)
        )
    return {
        "required_bars": required_bars,
        "bar_duration_hours": duration.total_seconds() / 3600,
        "worst_phase_required_hours": worst_required_hours,
        "configured_retention_days": configured_days,
        "configured_retention_hours": configured_hours,
        "minimum_whole_days": minimum_days,
        "ninety_day_bar_capacity": int(timedelta(days=90) // duration),
        "configured_bar_capacity": int(timedelta(days=configured_days) // duration),
        "margin_hours": configured_hours - worst_required_hours,
        "phases": phase_evidence,
        "status": (
            "PASS"
            if minimum_days <= configured_days
            and any(
                not item["ninety_day_includes_oldest_open"] for item in phase_evidence
            )
            and all(
                item["configured_retention_includes_oldest_open"]
                for item in phase_evidence
            )
            else "BLOCKED"
        ),
    }


def evaluate_functional_gates(evidence: Mapping[str, Any]) -> Mapping[str, bool]:
    routes = evidence.get("routes", ())
    startup = evidence.get("startup", {})
    reconstruction = evidence.get("historical_reconstruction_parity", {})
    live = evidence.get("live_path", {})
    duplicate = evidence.get("duplicate_path", {})
    failure = evidence.get("publication_failure_path", {})
    retention = evidence.get("retention_coverage", {})
    protected = evidence.get("protected_artifacts", {})
    return {
        "protected_artifacts": protected
        == {
            "m3_sha256": MOMENTUM_M3_ARTIFACT_SHA256,
            "d10_sha256": D10_ARTIFACT_SHA256,
        },
        "route_profile_locks": all(
            item.get("route_profile_sha256")
            == MOMENTUM_ROUTE_PROFILE_LOCKS.get(item.get("route"))
            for item in routes
        )
        and len(routes) == len(MOMENTUM_ROUTE_PROFILE_LOCKS),
        "feature_parity": all(
            item.get("feature_parity", {}).get("rsi") is True
            and item.get("feature_parity", {}).get("macd") is True
            and bool(item.get("feature_parity", {}).get("cutoff"))
            for item in routes
        ),
        "momentum_parity": all(
            all(value is True for value in item.get("momentum_parity", {}).values())
            for item in routes
        ),
        "startup_ready": startup.get("status") == "STARTUP_READY"
        and len(startup.get("lane_statuses", {})) == len(routes)
        and all(
            status == "STARTUP_READY"
            for status in startup.get("lane_statuses", {}).values()
        ),
        "stateless_startup": startup.get("stateful_binding_count") == 0
        and len(startup.get("replay_step_counts", {})) == len(routes)
        and all(value == 0 for value in startup.get("replay_step_counts", {}).values()),
        "historical_reconstruction": reconstruction.get("all_routes_equal") is True
        and reconstruction.get("all_publication_counts_zero") is True
        and all(
            item.get("status") == "PASS"
            and item.get("features_equal") is True
            and item.get("outcome_equal") is True
            and item.get("publication_count_during_reconstruction") == 0
            for item in reconstruction.get("routes", ())
        ),
        "live_signal_finalization": live.get("lane_status") == "LIVE"
        and live.get("policy_status") == "SIGNAL"
        and live.get("publication_outcome") == "PUBLISHED"
        and live.get("finalization_status") == "COMMITTED",
        "canonical_duplicate": duplicate.get("disposition") == "DUPLICATE"
        and duplicate.get("lane_status") == "LIVE"
        and duplicate.get("no_second_transaction") is True
        and duplicate.get("publication_count") == 1
        and duplicate.get("envelope_count") == 1,
        "publisher_retry": duplicate.get("publisher_retry_outcome")
        == "ALREADY_IDENTICAL",
        "publication_failure": failure.get("publication_outcome") == "FAILED"
        and failure.get("finalization_status") == "ABORTED"
        and failure.get("publication_count") == 0,
        "retention_coverage": retention.get("status") == "PASS",
    }


async def _collect() -> tuple[dict[str, Any], dict[str, Any]]:
    config = _load_config()
    m3_artifact = _validate_m3_identity(config)
    if hashlib.sha256(D10_ARTIFACT.read_bytes()).hexdigest() != D10_ARTIFACT_SHA256:
        raise RuntimeError("protected D10 artifact hash does not match the lock")
    composition = build_production_composition(config)
    threads_before = threading.active_count()
    tasks_before = len(asyncio.all_tasks())
    base_histories = {
        key: _bars(key, config.timeframe_grid) for key in _series_keys(config)
    }
    startup, repository, histories = await _startup(
        config,
        composition,
        histories_override=base_histories,
        repository_factory=_RecordingCanonicalHistoryRepository,
    )
    route_evidence: list[dict[str, Any]] = []
    for lane in startup.decision_plan.lanes:
        parameters = next(
            binding.parameters
            for binding in lane.bindings.values()
            if binding.slot_name == "primary"
        )
        envelope = parse_momentum_binding_parameters(
            parameters,
            expected_asset=lane.asset,
            expected_decision_timeframe=lane.decision_timeframe,
        )
        view = _view(config, startup, lane)
        prepared = await startup.runtimes[lane.lane_id].prepare_live(
            view,
            resolver_knowledge_cutoff=view.market_as_of + timedelta(seconds=1),
        )
        key = MarketSeriesKey(
            asset=lane.asset,
            venue=lane.venue,
            instrument_id=lane.instrument_id,
            timeframe=lane.decision_timeframe,
        )
        bars = histories[key]
        rsi_bars = bars[-envelope.feature_profile.rsi_history_bars :]
        macd_bars = bars[-envelope.feature_profile.macd_history_bars :]
        expected_rsi = calculate_rsi(
            [float(bar.close) for bar in rsi_bars],
            period=envelope.feature_profile.rsi_period,
        )
        expected_macd = calculate_macd(
            [float(bar.close) for bar in macd_bars],
            fast_period=envelope.feature_profile.macd_fast_period,
            slow_period=envelope.feature_profile.macd_slow_period,
            signal_period=envelope.feature_profile.macd_signal_period,
        )
        feature_values = prepared.feature_resolution.shared_features
        model_result = next(iter(prepared.binding_results.values()))
        assert model_result.outcome is not None
        expected = evaluate_momentum(
            MomentumObservation(
                rsi=expected_rsi,
                macd_histogram=expected_macd.histogram,
                macd_line=expected_macd.line,
            ),
            envelope.model_config,
        )
        route_evidence.append(
            {
                "route": f"{lane.asset}/{lane.decision_timeframe}",
                "lane_id": lane.lane_id,
                "binding_id": next(iter(prepared.binding_results)),
                "route_profile_sha256": momentum_route_profile_digest(
                    asset=envelope.asset,
                    decision_timeframe=envelope.decision_timeframe,
                    model_config=envelope.model_config,
                    feature_profile=envelope.feature_profile,
                ),
                "feature_profile": envelope.feature_profile.to_mapping(),
                "model_parameters": envelope.model_config.to_mapping(),
                "feature_parity": {
                    "rsi": feature_values[MOMENTUM_RSI_FEATURE_NAME].value
                    == expected_rsi,
                    "macd": feature_values[MOMENTUM_MACD_FEATURE_NAME].value
                    == {
                        "line": expected_macd.line,
                        "signal": expected_macd.signal,
                        "histogram": expected_macd.histogram,
                    },
                    "cutoff": view.market_as_of.isoformat(),
                },
                "momentum_parity": {
                    "direction": model_result.outcome.artifact.value["direction"]
                    == expected.direction,
                    "conviction": model_result.outcome.artifact.value["conviction"]
                    == expected.conviction,
                    "score": model_result.outcome.artifact.value["score"]
                    == expected.score,
                    "artifact_type": model_result.outcome.artifact.artifact_type
                    == "momentum.signal.v1",
                },
                "policy_status": "SIGNAL" if expected.direction else "NO_SIGNAL",
            }
        )

    reconstruction_routes = [
        await _measure_route_reconstruction(
            config,
            composition,
            base_histories,
            lane,
        )
        for lane in startup.decision_plan.lanes
    ]

    eth_key = MarketSeriesKey(
        asset="ETHUSDT",
        venue="binance",
        instrument_id="ETH-USDT-PERP",
        timeframe="4h",
    )
    previous = histories[eth_key][-1]
    duration = config.timeframe_grid.duration(eth_key.timeframe)
    next_open = previous.bar_close_at
    next_close = next_open + duration
    next_bar = CausalBarView(
        timeframe=eth_key.timeframe,
        bar_open_at=next_open,
        bar_close_at=next_close,
        market_as_of=next_close,
        open=previous.close,
        high=previous.close + Decimal("1.1"),
        low=previous.close - Decimal(1),
        close=previous.close + Decimal("0.1"),
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        closed=True,
    )
    input_stream = _LiveStream()
    input_stream.pending = (
        canonical_ingestion_stream_key(eth_key),
        "1-0",
        {
            "event_id": "m4-certification-live",
            "event_type": "candle.committed",
            "schema_version": "1",
            "producer": "ingestion",
            "occurred_at": next_bar.bar_close_at.isoformat().replace("+00:00", "Z"),
            "payload": json.dumps(
                {
                    "venue": eth_key.venue,
                    "instrument_id": eth_key.instrument_id,
                    "timeframe": eth_key.timeframe,
                    "open_time": next_bar.bar_open_at.isoformat().replace(
                        "+00:00", "Z"
                    ),
                    "close_time": next_bar.bar_close_at.isoformat().replace(
                        "+00:00", "Z"
                    ),
                    "open": str(next_bar.open),
                    "high": str(next_bar.high),
                    "low": str(next_bar.low),
                    "close": str(next_bar.close),
                    "volume": str(next_bar.volume),
                    "taker_buy_base": str(next_bar.taker_buy_base),
                    "source_type": "provider",
                    "source_provider": "binance",
                    "source_timeframe": None,
                }
            ),
        },
    )
    signal_client = _SignalClient()
    publisher = _RecordingPublisher(ValkeySignalPublisher(signal_client))
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=config.timeframe_grid,
        stream_client=input_stream,
        history_repository=repository,
        signal_publisher=publisher,
        batch_size=10,
        block_ms=1000,
        now_fn=lambda: next_bar.market_as_of + timedelta(seconds=1),
    )
    live_poll = await runtime.poll_once()
    live_result = live_poll.lane_results["ETHUSDT:momentum_4h"]
    signal_stream = "signals:ETHUSDT:4h"
    signal_payload: dict[str, Any] = {}
    if signal_stream in signal_client.entries:
        entry_id, fields = next(iter(signal_client.entries[signal_stream].items()))
        signal = valkey_decode(dict(fields), TradeSignal)
        signal_payload = {
            "entry_id": entry_id,
            "asset": signal.asset,
            "timeframe": signal.timeframe,
            "timestamp": signal.timestamp,
            "model_name": signal.model_name,
            "direction": signal.direction,
            "conviction": signal.conviction,
        }

    repository.append(eth_key, next_bar)
    input_stream.pending = (
        canonical_ingestion_stream_key(eth_key),
        "2-0",
        _fields(next_bar, eth_key),
    )
    duplicate_poll = await runtime.poll_once()
    duplicate_result = duplicate_poll.lane_results["ETHUSDT:momentum_4h"]
    duplicate_input = next(
        item for item in duplicate_poll.input_results if item.disposition == "DUPLICATE"
    )
    publisher_retry = await publisher.publisher.publish(publisher.envelopes[0])

    failure_startup, failure_repository, failure_histories = await _startup(
        config,
        composition,
        histories_override=base_histories,
        repository_factory=_RecordingCanonicalHistoryRepository,
    )
    failure_bar = _next_bar(eth_key, failure_histories[eth_key], config.timeframe_grid)
    failure_stream = _LiveStream()
    failure_stream.pending = (
        canonical_ingestion_stream_key(eth_key),
        "1-0",
        _fields(failure_bar, eth_key),
    )
    failure_client = _SignalClient()
    failure_client.fail_xadd = True
    failure_runtime = LiveDecisionRuntime(
        startup=failure_startup,
        timeframe_grid=config.timeframe_grid,
        stream_client=failure_stream,
        history_repository=failure_repository,
        signal_publisher=ValkeySignalPublisher(failure_client),
        batch_size=10,
        block_ms=1000,
        now_fn=lambda: failure_bar.market_as_of + timedelta(seconds=1),
    )
    failure_poll = await failure_runtime.poll_once()
    failure_result = failure_poll.lane_results["ETHUSDT:momentum_4h"]

    capacities = {
        f"{key.asset}/{key.timeframe}": startup.bar_store.capacity_for(key)
        for key in startup.bar_store.series_keys
    }
    base_capacities = compile_bar_store_capacities(
        startup.decision_plan,
        config.timeframe_grid,
    )
    feature_capacities = compile_feature_bar_store_capacities(
        startup.decision_plan,
        startup.feature_plans,
        composition.feature_catalog,
        config.timeframe_grid,
    )
    feature_history_requirements = {
        lane.lane_id: {
            name: {
                _series_label(key): count
                for key, count in sorted(
                    requirements.items(),
                    key=lambda item: _series_label(item[0]),
                )
            }
            for name, requirements in sorted(
                startup.feature_plans[lane.lane_id].history_requirements.items()
            )
        }
        for lane in startup.decision_plan.lanes
    }
    startup_fetch_limits: dict[str, list[int]] = {}
    for call in repository.fetch_bars_calls:
        limit = call["limit"]
        if isinstance(limit, int):
            startup_fetch_limits.setdefault(str(call["series"]), []).append(limit)
    startup_fetch_limits = {
        key: sorted(values) for key, values in sorted(startup_fetch_limits.items())
    }
    retention_coverage = build_retention_coverage(config)
    all_publication_counts_zero = all(
        item["publication_count_during_reconstruction"] == 0
        for item in reconstruction_routes
    )
    historical_reconstruction = {
        "routes": reconstruction_routes,
        "all_routes_equal": all(
            item["features_equal"] and item["outcome_equal"]
            for item in reconstruction_routes
        ),
        "all_publication_counts_zero": all_publication_counts_zero,
        "publication_suppressed": all_publication_counts_zero,
        "stateless_restart_reconstruction": all(
            item["status"] == "PASS" for item in reconstruction_routes
        ),
    }
    duplicate_path = {
        "disposition": duplicate_input.disposition,
        "reason": duplicate_input.reason,
        "lane_status": duplicate_result.status,
        "trigger_cutoff": duplicate_result.trigger_cutoff,
        "policy_status": duplicate_result.policy_status,
        "publication_outcome": duplicate_result.publication_outcome,
        "finalization_status": duplicate_result.finalization_status,
        "no_second_transaction": (
            duplicate_result.trigger_cutoff is None
            and duplicate_result.policy_status is None
            and duplicate_result.publication_outcome is None
            and duplicate_result.finalization_status is None
        ),
        "publication_count": sum(
            len(values) for values in signal_client.entries.values()
        ),
        "envelope_count": len(publisher.envelopes),
        "publisher_retry_outcome": publisher_retry.outcome,
    }
    publication_failure_path = {
        "lane_status": failure_result.status,
        "publication_outcome": failure_result.publication_outcome,
        "finalization_status": failure_result.finalization_status,
        "publication_count": sum(
            len(values) for values in failure_client.entries.values()
        ),
    }
    functional = {
        "schema_version": 1,
        "source_sha": _source_sha(),
        "m3_artifact_sha256": MOMENTUM_M3_ARTIFACT_SHA256,
        "m3_source_sha": m3_artifact["source_sha"],
        "protected_artifacts": {
            "m3_sha256": MOMENTUM_M3_ARTIFACT_SHA256,
            "d10_sha256": D10_ARTIFACT_SHA256,
        },
        "composition": {
            "plugins": [
                f"{item.name}@{item.version}" for item in composition.plugin_catalog
            ],
            "runtime_plugins": [
                f"{item.plugin_name}@{item.plugin_version}"
                for item in composition.runtime_plugin_catalog
            ],
            "features": [
                f"{item.name}@{item.version}" for item in composition.feature_catalog
            ],
            "lane_count": len(startup.decision_plan.lanes),
        },
        "routes": sorted(route_evidence, key=lambda item: item["route"]),
        "compiled_feature_histories": {
            item.name: item.history_requirements[0].bars
            for item in composition.feature_catalog
            if item.name in {MOMENTUM_RSI_FEATURE_NAME, MOMENTUM_MACD_FEATURE_NAME}
        },
        "compiled_capacities": capacities,
        "retention_coverage": retention_coverage,
        "startup": {
            "status": startup.snapshot.status,
            "lane_statuses": {
                key: value.status
                for key, value in startup.snapshot.lane_evidence.items()
            },
            "replay_step_counts": {
                key: value.replay_step_count
                for key, value in startup.snapshot.lane_evidence.items()
            },
            "stateful_binding_count": sum(
                len(runtime.stateful_binding_ids)
                for runtime in startup.runtimes.values()
            ),
            "retained_bar_count_at_steady_state": sum(
                startup.bar_store.capacity_for(key)
                for key in startup.bar_store.series_keys
            ),
        },
        "historical_reconstruction_parity": historical_reconstruction,
        "live_path": {
            "lane_status": live_result.status,
            "policy_status": live_result.policy_status,
            "publication_outcome": live_result.publication_outcome,
            "finalization_status": live_result.finalization_status,
            "signal_stream": signal_stream,
            "signal": signal_payload,
        },
        "duplicate_path": duplicate_path,
        "publication_failure_path": publication_failure_path,
        "resource_structure": {
            "configured_asset_count": len(config.assets),
            "configured_lane_count": len(startup.decision_plan.lanes),
            "series_keys": sorted(capacities),
            "base_d3_capacities": {
                _series_label(key): count
                for key, count in sorted(
                    base_capacities.items(),
                    key=lambda item: _series_label(item[0]),
                )
            },
            "feature_history_requirements": feature_history_requirements,
            "feature_merged_capacities": {
                _series_label(key): count
                for key, count in sorted(
                    feature_capacities.items(),
                    key=lambda item: _series_label(item[0]),
                )
            },
            "final_merged_capacities": capacities,
            "startup_fetch_limits": startup_fetch_limits,
            "retained_count_at_steady_capacity": sum(capacities.values()),
            "runtime_instance_count": len(startup.runtimes),
            "stateful_binding_count": sum(
                len(runtime.stateful_binding_ids)
                for runtime in startup.runtimes.values()
            ),
        },
        "deferred_gates": [
            "production decision asset activation",
            "real Timescale/Valkey soak and cutover",
            "D11 combined certification",
            "final model-mix resource recertification",
            "legacy signal_app sparse feature fallback discrepancy",
        ],
        "terminal_status": "MOMENTUM_M4_DECISION_INTEGRATION_REMEDIATION_BLOCKED",
    }
    functional["functional_gates"] = dict(evaluate_functional_gates(functional))
    functional_ready = all(functional["functional_gates"].values())
    functional["functional_status"] = "PASS" if functional_ready else "BLOCKED"
    functional["terminal_status"] = (
        "MOMENTUM_M4_DECISION_INTEGRATION_REMEDIATION_READY_FOR_REVIEW"
        if functional_ready
        else "MOMENTUM_M4_DECISION_INTEGRATION_REMEDIATION_BLOCKED"
    )
    identity_payload = {
        "schema_version": functional["schema_version"],
        "source_sha": functional["source_sha"],
        "protected_artifacts": functional["protected_artifacts"],
        "composition": functional["composition"],
        "routes": [
            {
                "route": route["route"],
                "lane_id": route["lane_id"],
                "binding_id": route["binding_id"],
                "route_profile_sha256": route["route_profile_sha256"],
                "feature_profile": route["feature_profile"],
                "model_parameters": route["model_parameters"],
            }
            for route in functional["routes"]
        ],
        "compiled_feature_histories": functional["compiled_feature_histories"],
        "compiled_capacities": functional["compiled_capacities"],
        "resource_structure": functional["resource_structure"],
    }
    functional["deterministic_identity_sha256"] = _digest(identity_payload)
    measurement_payload = dict(functional)
    measurement_payload.pop("deterministic_identity_sha256", None)
    measurement_payload.pop("measurement_payload_sha256", None)
    functional["measurement_payload_sha256"] = _digest(measurement_payload)

    threads_after = threading.active_count()
    tasks_after = len(asyncio.all_tasks())
    resource_measurement = {
        "schema_version": 1,
        "source_sha": functional["source_sha"],
        "scenario": "momentum_m4_compiled_graph_and_isolated_live_path",
        "configured_assets": sorted(config.assets),
        "configured_lane_count": len(startup.decision_plan.lanes),
        "compiled_series_keys": sorted(capacities),
        "capacity_decomposition": functional["resource_structure"],
        "compiled_capacities": capacities,
        "total_retained_bars": sum(capacities.values()),
        "runtime_instance_count": len(startup.runtimes),
        "stateful_binding_count": functional["startup"]["stateful_binding_count"],
        "threads_before": threads_before,
        "threads_after": threads_after,
        "tasks_before": tasks_before,
        "tasks_after": tasks_after,
        "thread_leak_gate": threads_after <= threads_before,
        "task_leak_gate": tasks_after <= tasks_before,
        "process_peak_rss_bytes": _peak_rss_bytes(),
        "tracemalloc_peak_bytes": 0,
        "cpu_seconds": 0.0,
        "wall_seconds": 0.0,
        "targets": {
            "normal_working_set_bytes": 5 * 1024**3,
            "hard_memory_bytes": 8 * 1024**3,
            "cpu_cores": 4,
        },
        "status": "BLOCKED",
    }
    return functional, resource_measurement


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if value > 1024 * 1024 else value * 1024


def resource_measurement_placeholder() -> int:
    """Return zero until the outer measurement wrapper supplies the peak."""

    return 0


def build_functional_artifact() -> dict[str, Any]:
    return asyncio.run(_collect())[0]


def write_artifacts(output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    tracemalloc.start()
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    functional, resource_artifact = asyncio.run(_collect())
    wall_seconds = time.perf_counter() - start_wall
    cpu_seconds = time.process_time() - start_cpu
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    resource_artifact["tracemalloc_peak_bytes"] = peak
    resource_artifact["process_peak_rss_bytes"] = _peak_rss_bytes()
    resource_artifact["cpu_seconds"] = round(cpu_seconds, 6)
    resource_artifact["wall_seconds"] = round(wall_seconds, 6)
    resource_artifact["cpu_core_equivalent"] = round(
        cpu_seconds / wall_seconds if wall_seconds else 0.0,
        6,
    )
    resource_artifact["normal_working_set_gate"] = (
        resource_artifact["process_peak_rss_bytes"]
        < resource_artifact["targets"]["normal_working_set_bytes"]
    )
    resource_artifact["hard_memory_gate"] = (
        resource_artifact["process_peak_rss_bytes"]
        < resource_artifact["targets"]["hard_memory_bytes"]
    )
    resource_artifact["cpu_gate"] = (
        resource_artifact["cpu_core_equivalent"]
        < resource_artifact["targets"]["cpu_cores"]
    )
    resource_artifact["status"] = (
        "PASS"
        if resource_artifact["normal_working_set_gate"]
        and resource_artifact["hard_memory_gate"]
        and resource_artifact["cpu_gate"]
        and resource_artifact["thread_leak_gate"]
        and resource_artifact["task_leak_gate"]
        else "BLOCKED"
    )
    resource_artifact["measurement_payload_sha256"] = _digest(resource_artifact)
    functional_path = output_dir / "m4_momentum_decision_integration_certification.json"
    resource_path = output_dir / "m4_momentum_resource_certification.json"
    functional_path.write_bytes(_json_bytes(functional) + b"\n")
    resource_path.write_bytes(_json_bytes(resource_artifact) + b"\n")
    return functional_path, resource_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "artifacts" / "decision_m4",
    )
    args = parser.parse_args()
    functional_path, resource_path = write_artifacts(args.output_dir)
    print(functional_path)
    print(resource_path)
    print(hashlib.sha256(functional_path.read_bytes()).hexdigest())
    print(hashlib.sha256(resource_path.read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
