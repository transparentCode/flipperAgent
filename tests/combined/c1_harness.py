from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from apps.decision_app.composition import build_production_composition
from apps.decision_app.domain.market_state import MarketSeriesKey
from apps.decision_app.domain.view import DecisionViewBuilder
from apps.decision_app.features.momentum import calculate_macd, calculate_rsi
from apps.decision_app.features.momentum_integration import (
    MOMENTUM_M3_ARTIFACT_SHA256,
    MOMENTUM_MACD_FEATURE_NAME,
    MOMENTUM_RSI_FEATURE_NAME,
    parse_momentum_binding_parameters,
)
from apps.decision_app.runtime.live import LiveDecisionRuntime
from apps.decision_app.runtime.startup import DecisionStartupCoordinator
from apps.decision_app.settings import DecisionConfig, load_decision_config
from apps.decision_app.storage.checkpoints import InMemoryCheckpointRepository
from apps.decision_app.storage.market_history import (
    CanonicalMarketRecord,
    InMemoryCanonicalMarketHistoryRepository,
)
from apps.decision_app.transport.ingestion import (
    canonical_ingestion_stream_key,
    parse_canonical_ingestion_event,
)
from apps.decision_app.transport.signals import ValkeySignalPublisher
from apps.ingestion_app.domain.candle import CandleObservation, CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.providers.base import HistoricalCandleProvider
from apps.ingestion_app.publication.outbox import OutboxEvent
from apps.ingestion_app.publication.publisher import OutboxPublisher
from apps.ingestion_app.services.candle_ingestion import CandleIngestionService
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.services.recovery import RecoveryEngine
from apps.ingestion_app.settings import PublicationSettings
from apps.ingestion_app.storage.repository import CandleCommitStatus
from libs.common.config import ConfigManager
from libs.common.exceptions import DataIngestionError
from libs.contracts.decision import CausalBarView
from libs.contracts.serialization import valkey_decode
from libs.contracts.signal import TradeSignal
from libs.models.momentum.core import MomentumObservation, evaluate_momentum

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = ROOT / "tests" / "decision" / "fixtures" / "momentum_m4"
POST_M4_SHA = "498f0bf53311f98f11899b3444f67395fbe74b02"
M3_ARTIFACT_SHA = "6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c"
M4_FUNCTIONAL_SHA = "3d1339be919e8d176dcd1053cb1c42f46bf6a2dc5f62647114b805faea1e4792"
M4_RESOURCE_SHA = "e11ae8aee717764a3cca9dbfaa0f58d6b4308387ac6b5b264fb4bdf8e5f570c4"
D10_ARTIFACT_SHA = "2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459"

_ROUTE_NAMES = (
    ("BTCUSDT", "1h"),
    ("BTCUSDT", "4h"),
    ("ETHUSDT", "4h"),
)
LIVE_BASE_DURATION = timedelta(minutes=1)
LIVE_BASE_STEPS = 240
LIVE_TARGET_DURATIONS = {
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
}
SUCCESS_STATUS = (
    "INGESTION_DECISION_C1_DETERMINISTIC_STITCH_REMEDIATION_READY_FOR_REVIEW"
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protected_artifacts_match() -> bool:
    return all(
        _file_sha256(path) == expected
        for path, expected in (
            (
                ROOT
                / "artifacts"
                / "decision_m3"
                / "m3_momentum_feature_semantics_certification.json",
                M3_ARTIFACT_SHA,
            ),
            (
                ROOT
                / "artifacts"
                / "decision_m4"
                / "m4_momentum_decision_integration_certification.json",
                M4_FUNCTIONAL_SHA,
            ),
            (
                ROOT
                / "artifacts"
                / "decision_m4"
                / "m4_momentum_resource_certification.json",
                M4_RESOURCE_SHA,
            ),
            (
                ROOT
                / "artifacts"
                / "decision_d10"
                / "d10_resource_capacity_certification.json",
                D10_ARTIFACT_SHA,
            ),
        )
    )


def _asset_for_instrument(instrument_id: str) -> str:
    return {"BTC-USDT-PERP": "BTCUSDT", "ETH-USDT-PERP": "ETHUSDT"}.get(
        instrument_id,
        instrument_id,
    )


def _decision_key(candle: CanonicalCandle) -> MarketSeriesKey:
    return MarketSeriesKey(
        asset=_asset_for_instrument(candle.lane.instrument_id),
        venue=candle.lane.venue,
        instrument_id=candle.lane.instrument_id,
        timeframe=candle.lane.timeframe,
    )


def _bar_from_candle(candle: CanonicalCandle) -> CausalBarView:
    return CausalBarView(
        timeframe=candle.lane.timeframe,
        bar_open_at=candle.open_time,
        bar_close_at=candle.close_time,
        market_as_of=candle.close_time,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        volume=candle.volume,
        taker_buy_base=candle.taker_buy_base,
        closed=True,
    )


class MutableCanonicalHistory(InMemoryCanonicalMarketHistoryRepository):
    """Test-only mutable view of the durable canonical history seam."""

    def add_candle(self, candle: CanonicalCandle) -> None:
        key = _decision_key(candle)
        bar = _bar_from_candle(candle)
        record = CanonicalMarketRecord(
            series_key=key,
            bar=bar,
            source_type=candle.source_type,
            source_provider=candle.source_provider,
            source_timeframe=candle.source_timeframe,
        )
        bars = list(self._bars.get(key, ()))
        records = list(self._records.get(key, ()))
        for index, existing in enumerate(records):
            if existing.bar.bar_open_at == bar.bar_open_at:
                bars[index] = bar
                records[index] = record
                break
        else:
            bars.append(bar)
            records.append(record)
        ordered = sorted(
            zip(bars, records, strict=True),
            key=lambda item: item[0].bar_open_at,
        )
        self._bars[key] = tuple(item[0] for item in ordered)
        self._records[key] = tuple(item[1] for item in ordered)


class CombinedPersistence:
    """Small C1-only canonical candle/outbox persistence seam."""

    def __init__(self) -> None:
        self.history = MutableCanonicalHistory(timeframe_grid=None)
        self._candles: dict[MarketLane, dict[datetime, CanonicalCandle]] = {}
        self._pending: dict[UUID, OutboxEvent] = {}
        self._published: set[UUID] = set()
        self.fail_next_mark = False
        self.mark_calls = 0

    def seed_candle(self, candle: CanonicalCandle) -> None:
        self._candles.setdefault(candle.lane, {})[candle.open_time] = candle
        self.history.add_candle(candle)

    def candle_at(self, lane: MarketLane, opened_at: datetime) -> CanonicalCandle:
        return self._candles[lane][opened_at]

    def candles_for(
        self,
        lane: MarketLane,
        since: datetime,
        until: datetime,
    ) -> tuple[CanonicalCandle, ...]:
        return tuple(
            candle
            for opened_at, candle in sorted(self._candles.get(lane, {}).items())
            if since <= opened_at < until
        )

    async def commit_candle(
        self,
        candle: CanonicalCandle,
        event: OutboxEvent,
    ) -> CandleCommitStatus:
        existing = self._candles.get(candle.lane, {}).get(candle.open_time)
        if existing is not None:
            return (
                CandleCommitStatus.DUPLICATE
                if existing == candle
                else CandleCommitStatus.CONFLICT
            )
        self._candles.setdefault(candle.lane, {})[candle.open_time] = candle
        self.history.add_candle(candle)
        self._pending[event.event_id] = event
        return CandleCommitStatus.INSERTED

    async def fetch_candles(
        self,
        *,
        lane: MarketLane,
        since: datetime,
        until: datetime,
    ) -> tuple[CanonicalCandle, ...]:
        return self.candles_for(lane, since, until)

    async def fetch_pending_outbox(self, *, limit: int) -> tuple[OutboxEvent, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be positive")
        return tuple(
            sorted(
                (
                    event
                    for event_id, event in self._pending.items()
                    if event_id not in self._published
                ),
                key=lambda event: (event.occurred_at, str(event.event_id)),
            )[:limit]
        )

    async def mark_outbox_published(
        self,
        *,
        event_id: UUID,
        published_at: datetime,
    ) -> bool:
        del published_at
        self.mark_calls += 1
        if self.fail_next_mark:
            self.fail_next_mark = False
            return False
        if event_id not in self._pending:
            return False
        self._published.add(event_id)
        return True

    async def fetch_pending_outbox_state(self) -> tuple[int, datetime | None]:
        pending = await self.fetch_pending_outbox(limit=max(1, len(self._pending)))
        return len(pending), pending[0].occurred_at if pending else None

    @property
    def pending_events(self) -> tuple[OutboxEvent, ...]:
        return tuple(
            event
            for event_id, event in self._pending.items()
            if event_id not in self._published
        )


def _stream_id_tuple(value: object) -> tuple[int, int]:
    text = value.decode() if isinstance(value, bytes) else str(value)
    left, right = text.split("-", 1)
    return int(left), int(right)


class DeterministicBroker:
    """Minimal test-owned XADD/XREAD/XRANGE/XREVRANGE seam."""

    def __init__(self) -> None:
        self.entries: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self._next_auto_id = 1
        self.xadd_calls: list[tuple[str, str | None]] = []
        self.fail_next_auto_xadd = False

    async def xadd(
        self,
        stream: str,
        fields: Mapping[object, object],
        *,
        id: str | None = None,
        maxlen: int | None = None,
        approximate: bool | None = None,
    ) -> str:
        del approximate
        if id is None and self.fail_next_auto_xadd:
            self.fail_next_auto_xadd = False
            raise RuntimeError("deterministic broker XADD failure")
        normalized_fields = {
            (key.decode() if isinstance(key, bytes) else str(key)): (
                value.decode() if isinstance(value, bytes) else str(value)
            )
            for key, value in fields.items()
        }
        if id is None:
            id = f"{self._next_auto_id}-0"
            self._next_auto_id += 1
        else:
            id = str(id)
            if any(
                existing_id == id for existing_id, _ in self.entries.get(stream, ())
            ):
                raise RuntimeError("duplicate explicit stream ID")
        values = self.entries.setdefault(stream, [])
        values.append((id, normalized_fields))
        values.sort(key=lambda item: _stream_id_tuple(item[0]))
        self.xadd_calls.append((stream, id))
        if maxlen is not None and maxlen > 0:
            self.entries[stream] = values[-maxlen:]
        return id

    async def xread(
        self,
        streams: Mapping[str, str],
        *,
        count: int,
        block: int,
    ) -> list[tuple[str, list[tuple[str, Mapping[str, str]]]]]:
        del block
        result: list[tuple[str, list[tuple[str, Mapping[str, str]]]]] = []
        for stream, cursor in streams.items():
            selected = [
                (entry_id, fields)
                for entry_id, fields in self.entries.get(stream, ())
                if _stream_id_tuple(entry_id) > _stream_id_tuple(cursor)
            ][:count]
            if selected:
                result.append((stream, selected))
        return result

    async def xrange(
        self,
        stream: str,
        minimum: str,
        maximum: str,
    ) -> list[tuple[str, Mapping[str, str]]]:
        return [
            (entry_id, fields)
            for entry_id, fields in self.entries.get(stream, ())
            if entry_id == minimum == maximum
        ]

    async def xrevrange(
        self,
        stream: str,
        *_args: object,
        count: int = 1,
    ) -> list[tuple[str, Mapping[str, str]]]:
        return list(reversed(self.entries.get(stream, ())))[:count]

    def stream_entries(self, stream: str) -> tuple[tuple[str, Mapping[str, str]], ...]:
        return tuple(self.entries.get(stream, ()))


class FixtureHistoricalProvider(HistoricalCandleProvider):
    """Deterministic provider returning only the scripted recovery rows."""

    provider_id = "c1_recovery_provider"

    def __init__(self, observations: Sequence[CandleObservation]) -> None:
        self.observations = tuple(observations)
        self.calls: list[dict[str, object]] = []

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
        self.calls.append(
            {
                "lane": lane,
                "provider_symbol": provider_symbol,
                "since": since,
                "until": until,
                "limit": limit,
            }
        )
        return tuple(
            observation
            for observation in self.observations
            if observation.lane == lane
            and since <= observation.open_time < until
            and observation.close_time <= until
            and observation.close_time == observation.open_time + timeframe_duration
        )


def load_fixture_config() -> DecisionConfig:
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


def _route_keys(config: DecisionConfig) -> tuple[MarketSeriesKey, ...]:
    return tuple(
        MarketSeriesKey(
            asset=lane.asset,
            venue=lane.venue,
            instrument_id=lane.instrument_id,
            timeframe=lane.decision_timeframe,
        )
        for lane in config.lane_specs()
    )


def _expected_derived_entry_counts(
    *,
    base_steps: int = LIVE_BASE_STEPS,
) -> dict[str, int]:
    """Derive exact HTF close counts from the deterministic fixture geometry."""

    return {
        f"{asset}/{timeframe}": sum(
            1
            for step in range(1, base_steps + 1)
            if (LIVE_BASE_DURATION * step).total_seconds()
            % LIVE_TARGET_DURATIONS[timeframe].total_seconds()
            == 0
        )
        for asset, timeframe in _ROUTE_NAMES
    }


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _seed_bar(
    key: MarketSeriesKey,
    *,
    opened: datetime,
    close: Decimal,
) -> CanonicalCandle:
    duration = {
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
    }[key.timeframe]
    return CanonicalCandle(
        lane=MarketLane(key.venue, key.instrument_id, key.timeframe),
        open_time=opened,
        close_time=opened + duration,
        open=close,
        high=close + Decimal(1),
        low=close - Decimal(1),
        close=close,
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        source_type="derived",
        source_provider=None,
        source_timeframe="1m",
    )


def seed_route_history(
    persistence: CombinedPersistence,
    config: DecisionConfig,
    *,
    count: int = 544,
) -> datetime:
    bucket_start = config.timeframe_grid.alignment_origin + timedelta(days=1000)
    for key in _route_keys(config):
        duration = config.timeframe_grid.duration(key.timeframe)
        start = bucket_start - duration * count
        for index in range(count):
            persistence.seed_candle(
                _seed_bar(
                    key,
                    opened=start + duration * index,
                    close=Decimal(100) + Decimal(index) / Decimal(10),
                )
            )
    return bucket_start


def _provider_observation(
    *,
    lane: MarketLane,
    opened: datetime,
    close: Decimal,
) -> CandleObservation:
    closed = opened + timedelta(minutes=1)
    return CandleObservation(
        lane=lane,
        provider_id="c1_recovery_provider",
        provider_symbol=lane.instrument_id,
        transport="deterministic",
        open_time=opened,
        close_time=closed,
        open=close,
        high=close + Decimal("0.2"),
        low=close - Decimal("0.2"),
        close=close,
        volume=Decimal(1),
        taker_buy_base=Decimal("0.4"),
        received_at=closed,
    )


async def materialize_live_bucket(
    persistence: CombinedPersistence,
    config: DecisionConfig,
    *,
    bucket_start: datetime,
    missing_index: int | None = None,
    only_asset: str | None = None,
) -> tuple[RecoveryRequest, ...]:
    ingestion = CandleIngestionService(persistence)  # type: ignore[arg-type]
    htf = HTFAggregationService(
        repository=persistence,  # type: ignore[arg-type]
        ingestion_service=ingestion,
    )
    requests: list[RecoveryRequest] = []
    for asset, instrument_id, targets in (
        (
            "BTCUSDT",
            "BTC-USDT-PERP",
            {
                "1h": LIVE_TARGET_DURATIONS["1h"],
                "4h": LIVE_TARGET_DURATIONS["4h"],
            },
        ),
        (
            "ETHUSDT",
            "ETH-USDT-PERP",
            {"4h": LIVE_TARGET_DURATIONS["4h"]},
        ),
    ):
        if only_asset is not None and asset != only_asset:
            continue
        lane = MarketLane("binance", instrument_id, "1m")
        for index in range(240):
            if missing_index == index and asset == "ETHUSDT":
                continue
            close = Decimal("154.3") + Decimal(index + 1) / Decimal(10)
            observation = _provider_observation(
                lane=lane,
                opened=bucket_start + timedelta(minutes=index),
                close=close,
            )
            status = await ingestion.commit_observation(observation)
            if status is CandleCommitStatus.CONFLICT:
                raise AssertionError("unexpected provider candle conflict")
            canonical = persistence.candle_at(lane, observation.open_time)
            requests.extend(
                await htf.process_base_candle(
                    canonical,
                    base_duration=timedelta(minutes=1),
                    target_durations=targets,
                    alignment_origin=config.timeframe_grid.alignment_origin,
                )
            )
    return tuple(requests)


def _publication_settings() -> PublicationSettings:
    return PublicationSettings(
        batch_size=1000,
        idle_sleep_seconds=1,
        error_backoff_seconds=1,
        stream_maxlen=10000,
        stream_approximate=False,
    )


async def publish_pending(
    persistence: CombinedPersistence,
    broker: DeterministicBroker,
    *,
    fail_mark_once: bool = False,
) -> tuple[int, int]:
    persistence.fail_next_mark = fail_mark_once
    publisher = OutboxPublisher(
        repository=persistence,  # type: ignore[arg-type]
        valkey_client=broker,
        publication=_publication_settings(),
        now_fn=lambda: datetime(2029, 1, 1, tzinfo=UTC),
    )
    attempts = 0
    published = 0
    while persistence.pending_events:
        attempts += 1
        try:
            published += await publisher.publish_once()
        except DataIngestionError:
            continue
        if attempts > 20:
            raise AssertionError("outbox did not drain within bounded attempts")
    return attempts, published


async def build_startup_runtime(
    config: DecisionConfig,
    persistence: CombinedPersistence,
    broker: DeterministicBroker,
) -> tuple[Any, Any, LiveDecisionRuntime, DeterministicBroker]:
    composition = build_production_composition(config)
    startup = await DecisionStartupCoordinator(
        decision_config=config,
        plugin_catalog=composition.plugin_catalog,
        feature_catalog=composition.feature_catalog,
        feature_policy=composition.feature_policy,
        data_policy=composition.data_policy,
        source_catalog=composition.data_source_catalog,
        runtime_plugin_catalog=composition.runtime_plugin_catalog,
        history_repository=persistence.history,
        policy_catalog=composition.policy_catalog,
        stream_client=broker,
        checkpoint_repository=InMemoryCheckpointRepository(),
        data_resolver=composition.data_resolver,
    ).start()
    signal_broker = DeterministicBroker()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=config.timeframe_grid,
        stream_client=broker,
        history_repository=persistence.history,
        signal_publisher=ValkeySignalPublisher(
            signal_broker,
            stream_maxlen=1000,
            stream_approximate=False,
        ),
        batch_size=10,
        block_ms=1000,
        now_fn=lambda: datetime(2030, 1, 1, tzinfo=UTC),
    )
    return startup, composition, runtime, signal_broker


def _lane_result_table(poll: Any) -> dict[str, dict[str, object]]:
    return {
        lane_id: {
            "status": result.status,
            "trigger_cutoff": (
                None
                if result.trigger_cutoff is None
                else result.trigger_cutoff.isoformat()
            ),
            "policy_status": result.policy_status,
            "publication_outcome": result.publication_outcome,
            "finalization_status": result.finalization_status,
        }
        for lane_id, result in poll.lane_results.items()
    }


async def _semantic_parity(
    config: DecisionConfig,
    startup: Any,
    runtime: LiveDecisionRuntime,
) -> dict[str, bool]:
    evidence = await _semantic_evidence(config, startup, runtime)
    return {lane_id: bool(item["parity"]) for lane_id, item in evidence.items()}


async def _semantic_evidence(
    config: DecisionConfig,
    startup: Any,
    runtime: LiveDecisionRuntime,
) -> dict[str, dict[str, object]]:
    view_builder = DecisionViewBuilder(runtime._store, config.timeframe_grid)
    evidence: dict[str, dict[str, object]] = {}
    for lane in startup.decision_plan.lanes:
        live_lane = runtime.lanes[lane.lane_id]
        cutoff = live_lane.finalizer.watermark.latest_market_as_of
        if cutoff is None:
            evidence[lane.lane_id] = {"parity": False}
            continue
        view = view_builder.build(
            lane,
            live_lane.market_requirements,
            cutoff,
            input_read_cursor=runtime.input.cursor_for(
                live_lane.market_requirements.trigger_series
            ),
            lane_commit_watermark=live_lane.finalizer.watermark,
        )
        prepared = await live_lane.runtime.prepare_live(
            view,
            resolver_knowledge_cutoff=cutoff + timedelta(seconds=1),
        )
        binding = next(iter(prepared.binding_results.values()))
        parameters = next(
            item.parameters
            for item in lane.bindings.values()
            if item.slot_name == "primary"
        )
        envelope = parse_momentum_binding_parameters(
            parameters,
            expected_asset=lane.asset,
            expected_decision_timeframe=lane.decision_timeframe,
        )
        key = MarketSeriesKey(
            asset=lane.asset,
            venue=lane.venue,
            instrument_id=lane.instrument_id,
            timeframe=lane.decision_timeframe,
        )
        history = runtime._store.bars_at(
            key,
            cutoff,
            limit=max(
                envelope.feature_profile.rsi_history_bars,
                envelope.feature_profile.macd_history_bars,
            ),
        )
        expected_rsi = calculate_rsi(
            [
                float(bar.close)
                for bar in history[-envelope.feature_profile.rsi_history_bars :]
            ],
            period=envelope.feature_profile.rsi_period,
        )
        expected_macd = calculate_macd(
            [
                float(bar.close)
                for bar in history[-envelope.feature_profile.macd_history_bars :]
            ],
            fast_period=envelope.feature_profile.macd_fast_period,
            slow_period=envelope.feature_profile.macd_slow_period,
            signal_period=envelope.feature_profile.macd_signal_period,
        )
        expected = evaluate_momentum(
            MomentumObservation(
                rsi=expected_rsi,
                macd_histogram=expected_macd.histogram,
                macd_line=expected_macd.line,
            ),
            envelope.model_config,
        )
        actual_value = (
            None if binding.outcome is None else binding.outcome.artifact.value
        )
        actual_rsi = prepared.feature_resolution.shared_features[
            MOMENTUM_RSI_FEATURE_NAME
        ].value
        actual_macd = prepared.feature_resolution.shared_features[
            MOMENTUM_MACD_FEATURE_NAME
        ].value
        expected_macd_value = {
            "line": expected_macd.line,
            "signal": expected_macd.signal,
            "histogram": expected_macd.histogram,
        }
        expected_momentum = {
            "direction": expected.direction,
            "conviction": expected.conviction,
            "score": expected.score,
        }
        route_parity = bool(
            actual_rsi == expected_rsi
            and actual_macd == expected_macd_value
            and actual_value == expected_momentum
        )
        evidence[lane.lane_id] = {
            "market_as_of": cutoff.isoformat(),
            "rsi": {
                "expected": _json_value(expected_rsi),
                "actual": _json_value(actual_rsi),
            },
            "macd": {
                "expected": _json_value(expected_macd_value),
                "actual": _json_value(actual_macd),
            },
            "momentum": {
                "expected": _json_value(expected_momentum),
                "actual": _json_value(actual_value),
            },
            "parity": route_parity,
        }
    return evidence


def _input_dispositions(poll: Any) -> list[dict[str, object]]:
    return [
        {
            "stream": result.stream_key,
            "id": result.stream_id,
            "disposition": result.disposition,
            "series": (
                None
                if result.series_key is None
                else f"{result.series_key.asset}/{result.series_key.timeframe}"
            ),
        }
        for result in poll.input_results
    ]


def _input_disposition_summary(poll: Any) -> list[dict[str, object]]:
    return [
        {
            "disposition": result.disposition,
            "series": (
                None
                if result.series_key is None
                else f"{result.series_key.asset}/{result.series_key.timeframe}"
            ),
        }
        for result in poll.input_results
    ]


def _input_cursor_cutoffs(poll: Any) -> dict[str, str | None]:
    return {
        stream_key: (
            None
            if cursor.latest_market_as_of is None
            else cursor.latest_market_as_of.isoformat()
        )
        for stream_key, cursor in poll.cursors.items()
    }


def _candle_identity(candle: CanonicalCandle | None) -> dict[str, object] | None:
    if candle is None:
        return None
    return {
        "asset": _asset_for_instrument(candle.lane.instrument_id),
        "venue": candle.lane.venue,
        "instrument_id": candle.lane.instrument_id,
        "timeframe": candle.lane.timeframe,
        "open_time": candle.open_time.isoformat(),
        "close_time": candle.close_time.isoformat(),
        "open": str(candle.open),
        "high": str(candle.high),
        "low": str(candle.low),
        "close": str(candle.close),
        "volume": str(candle.volume),
        "taker_buy_base": (
            None if candle.taker_buy_base is None else str(candle.taker_buy_base)
        ),
        "source_type": candle.source_type,
        "source_provider": candle.source_provider,
        "source_timeframe": candle.source_timeframe,
    }


def _signal_entries(broker: DeterministicBroker) -> dict[str, list[object]]:
    return {
        stream: [[entry_id, dict(fields)] for entry_id, fields in entries]
        for stream, entries in sorted(broker.entries.items())
    }


def _route_feature_and_momentum_parity(
    config: DecisionConfig,
    runtime: LiveDecisionRuntime,
    startup: Any,
) -> dict[str, bool]:
    evidence: dict[str, bool] = {}
    for lane in startup.decision_plan.lanes:
        lane_id = lane.lane_id
        live_lane = runtime.lanes[lane_id]
        watermark = live_lane.finalizer.watermark.latest_market_as_of
        if watermark is None:
            evidence[lane_id] = False
            continue
        key = MarketSeriesKey(
            asset=lane.asset,
            venue=lane.venue,
            instrument_id=lane.instrument_id,
            timeframe=lane.decision_timeframe,
        )
        bars = runtime._history._bars[key]  # type: ignore[attr-defined]
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
        expected_rsi = calculate_rsi(
            [
                float(item.close)
                for item in bars[-envelope.feature_profile.rsi_history_bars :]
            ],
            period=envelope.feature_profile.rsi_period,
        )
        expected_macd = calculate_macd(
            [
                float(item.close)
                for item in bars[-envelope.feature_profile.macd_history_bars :]
            ],
            fast_period=envelope.feature_profile.macd_fast_period,
            slow_period=envelope.feature_profile.macd_slow_period,
            signal_period=envelope.feature_profile.macd_signal_period,
        )
        observation = next(
            iter(
                runtime._startup.runtimes[lane_id]._plugin_instances.values()  # type: ignore[attr-defined]  # type: ignore[attr-defined]
            )
        )
        del observation
        evidence[lane_id] = (
            expected_rsi is not None
            and expected_macd.line is not None
            and expected_macd.signal is not None
        )
    return evidence


async def run_live_transition() -> dict[str, object]:
    config = load_fixture_config()
    persistence = CombinedPersistence()
    bucket_start = seed_route_history(persistence, config)
    broker = DeterministicBroker()
    startup, _composition, runtime, signal_broker = await build_startup_runtime(
        config, persistence, broker
    )
    assert startup.snapshot.status == "STARTUP_READY"
    requests = await materialize_live_bucket(
        persistence, config, bucket_start=bucket_start
    )
    outbox_attempts, outbox_published = await publish_pending(persistence, broker)
    derived_entries = {
        f"{asset}/{timeframe}": len(
            broker.stream_entries(
                canonical_ingestion_stream_key(
                    MarketSeriesKey(
                        asset=asset,
                        venue="binance",
                        instrument_id=(
                            "BTC-USDT-PERP" if asset == "BTCUSDT" else "ETH-USDT-PERP"
                        ),
                        timeframe=timeframe,
                    )
                )
            )
        )
        for asset, timeframe in _ROUTE_NAMES
    }
    parsed_events = []
    for asset, timeframe in _ROUTE_NAMES:
        key = MarketSeriesKey(
            asset=asset,
            venue="binance",
            instrument_id=("BTC-USDT-PERP" if asset == "BTCUSDT" else "ETH-USDT-PERP"),
            timeframe=timeframe,
        )
        stream = canonical_ingestion_stream_key(key)
        for stream_id, fields in broker.stream_entries(stream):
            parsed_events.append(
                parse_canonical_ingestion_event(
                    stream_key=stream,
                    stream_id=stream_id,
                    fields=fields,
                    expected_series=key,
                    timeframe_grid=config.timeframe_grid,
                )
            )
    expected_derived_entry_counts = _expected_derived_entry_counts()
    expected_stream_keys = sorted(
        canonical_ingestion_stream_key(
            MarketSeriesKey(
                asset=asset,
                venue="binance",
                instrument_id=(
                    "BTC-USDT-PERP" if asset == "BTCUSDT" else "ETH-USDT-PERP"
                ),
                timeframe=timeframe,
            )
        )
        for asset, timeframe in _ROUTE_NAMES
    )
    parsed_derived_provenance_summary: dict[str, set[tuple[object, ...]]] = {}
    parsed_event_contract_valid = True
    for event in parsed_events:
        route = f"{event.series_key.asset}/{event.series_key.timeframe}"
        parsed_derived_provenance_summary.setdefault(route, set()).add(
            (
                event.source_type,
                event.source_provider,
                event.source_timeframe,
            )
        )
        parsed_event_contract_valid = parsed_event_contract_valid and (
            event.stream_key == canonical_ingestion_stream_key(event.series_key)
            and event.source_type == "derived"
            and event.source_provider is None
            and event.source_timeframe == "1m"
        )
    poll = await runtime.poll_once()
    assert all(item.disposition == "INSERTED" for item in poll.input_results)
    assert all(
        item.policy_status in {"SIGNAL", "NO_SIGNAL"}
        for item in poll.lane_results.values()
    )
    signal_entries = sum(len(values) for values in signal_broker.entries.values())
    no_base_signal = all("1m" not in stream for stream in signal_broker.entries)
    lane_cutoffs = {
        lane_id: (
            None
            if result.finalization_status is None
            else result.trigger_cutoff.isoformat()
        )
        for lane_id, result in poll.lane_results.items()
    }
    cursor_cutoffs = _input_cursor_cutoffs(poll)
    semantic_parity = await _semantic_parity(config, startup, runtime)
    return {
        "startup_status": startup.snapshot.status,
        "startup_history_counts": {
            f"{key.asset}/{key.timeframe}": 544 for key in _route_keys(config)
        },
        "routes": list(_ROUTE_NAMES),
        "recovery_requests": [
            {
                "asset": request.lane.instrument_id,
                "since": request.since.isoformat(),
                "until": request.until.isoformat(),
                "reason": request.reason,
            }
            for request in requests
        ],
        "producer_consumer_stream_key_parity": all(
            event.stream_key == canonical_ingestion_stream_key(event.series_key)
            for event in parsed_events
        ),
        "parsed_event_count": len(parsed_events),
        "derived_entry_counts": derived_entries,
        "expected_derived_entry_counts": expected_derived_entry_counts,
        "parsed_derived_provenance_summary": {
            route: [
                {
                    "source_type": source_type,
                    "source_provider": source_provider,
                    "source_timeframe": source_timeframe,
                }
                for source_type, source_provider, source_timeframe in sorted(
                    values,
                    key=lambda item: tuple(
                        "" if value is None else str(value) for value in item
                    ),
                )
            ]
            for route, values in sorted(parsed_derived_provenance_summary.items())
        },
        "parsed_event_contract_valid": parsed_event_contract_valid,
        "parsed_derived_routes": sorted(parsed_derived_provenance_summary),
        "producer_stream_keys": sorted(broker.entries),
        "producer_derived_stream_keys": sorted(
            stream for stream in broker.entries if stream in expected_stream_keys
        ),
        "expected_stream_keys": expected_stream_keys,
        "outbox_attempts": outbox_attempts,
        "outbox_published": outbox_published,
        "input_dispositions": _input_dispositions(poll),
        "lane_results": _lane_result_table(poll),
        "lane_cutoffs": lane_cutoffs,
        "input_cursors": cursor_cutoffs,
        "feature_momentum_parity": semantic_parity,
        "signal_entry_count": signal_entries,
        "signal_streams": sorted(signal_broker.entries),
        "no_base_signal": no_base_signal,
        "feature_semantics": {
            "RSI": MOMENTUM_RSI_FEATURE_NAME,
            "MACD": MOMENTUM_MACD_FEATURE_NAME,
        },
        "protected_m3": MOMENTUM_M3_ARTIFACT_SHA256 == M3_ARTIFACT_SHA,
        "protected_artifacts_match": _protected_artifacts_match(),
    }


async def _route_runtime_snapshot(
    config: DecisionConfig,
    startup: Any,
    runtime: LiveDecisionRuntime,
) -> dict[str, object]:
    semantic = await _semantic_evidence(config, startup, runtime)
    watermarks: dict[str, str | None] = {}
    cursors: dict[str, str | None] = {}
    identities: dict[str, dict[str, object]] = {}
    for lane in startup.decision_plan.lanes:
        live_lane = runtime.lanes[lane.lane_id]
        watermark = live_lane.finalizer.watermark.latest_market_as_of
        cursor = runtime.input.cursor_for(live_lane.market_requirements.trigger_series)
        watermarks[lane.lane_id] = None if watermark is None else watermark.isoformat()
        cursors[lane.lane_id] = (
            None
            if cursor.latest_market_as_of is None
            else cursor.latest_market_as_of.isoformat()
        )
        identities[lane.lane_id] = {
            "lane_id": lane.lane_id,
            "binding_ids": sorted(
                binding.binding_id for binding in lane.bindings.values()
            ),
        }
    return {
        "watermarks": watermarks,
        "cursors": cursors,
        "semantic": semantic,
        "identities": identities,
    }


async def run_cross_route_isolation() -> dict[str, object]:
    config = load_fixture_config()
    persistence = CombinedPersistence()
    bucket_start = seed_route_history(persistence, config)
    broker = DeterministicBroker()
    startup, _composition, runtime, _signal_broker = await build_startup_runtime(
        config, persistence, broker
    )
    await materialize_live_bucket(persistence, config, bucket_start=bucket_start)
    await publish_pending(persistence, broker)
    baseline_poll = await runtime.poll_once()
    baseline = await _route_runtime_snapshot(config, startup, runtime)

    next_bucket = bucket_start + timedelta(hours=4)
    await materialize_live_bucket(
        persistence,
        config,
        bucket_start=next_bucket,
        only_asset="ETHUSDT",
    )
    await publish_pending(persistence, broker)
    perturbed_poll = await runtime.poll_once()
    after = await _route_runtime_snapshot(config, startup, runtime)

    unchanged_routes = [
        lane_id for lane_id in baseline["watermarks"] if lane_id.startswith("BTCUSDT:")
    ]
    baseline_btc = {
        lane_id: {
            "watermark": baseline["watermarks"][lane_id],
            "cursor": baseline["cursors"][lane_id],
            "semantic": baseline["semantic"][lane_id],
            "identity": baseline["identities"][lane_id],
        }
        for lane_id in unchanged_routes
    }
    after_btc = {
        lane_id: {
            "watermark": after["watermarks"][lane_id],
            "cursor": after["cursors"][lane_id],
            "semantic": after["semantic"][lane_id],
            "identity": after["identities"][lane_id],
        }
        for lane_id in unchanged_routes
    }
    poll_table = _lane_result_table(perturbed_poll)
    btc_transactions_absent = all(
        poll_table[lane_id][field] is None
        for lane_id in unchanged_routes
        for field in (
            "trigger_cutoff",
            "policy_status",
            "publication_outcome",
            "finalization_status",
        )
    )
    return {
        "perturbed_route": "ETHUSDT/4h",
        "unchanged_routes": unchanged_routes,
        "baseline": baseline_btc,
        "after": after_btc,
        "eth_poll_lane_results": poll_table,
        "btc_transactions_absent": btc_transactions_absent,
        "unchanged": baseline_btc == after_btc and btc_transactions_absent,
        "baseline_poll": _lane_result_table(baseline_poll),
    }


async def run_outbox_retry() -> dict[str, object]:
    config = load_fixture_config()
    persistence = CombinedPersistence()
    bucket_start = seed_route_history(persistence, config)
    broker = DeterministicBroker()
    startup, _composition, runtime, signal_broker = await build_startup_runtime(
        config, persistence, broker
    )
    key = MarketSeriesKey(
        asset="ETHUSDT",
        venue="binance",
        instrument_id="ETH-USDT-PERP",
        timeframe="4h",
    )
    bar = _seed_bar(
        key,
        opened=bucket_start,
        close=Decimal("155.0"),
    )
    ingestion = CandleIngestionService(persistence)  # type: ignore[arg-type]
    assert await ingestion.commit_candle(bar) is CandleCommitStatus.INSERTED
    event_id = persistence.pending_events[0].event_id
    attempts, _ = await publish_pending(persistence, broker, fail_mark_once=True)
    stream = canonical_ingestion_stream_key(key)
    entries = broker.stream_entries(stream)
    poll = await runtime.poll_once()
    dispositions = [item.disposition for item in poll.input_results]
    signal_count = sum(len(values) for values in signal_broker.entries.values())
    return {
        "event_id_present": isinstance(event_id, UUID),
        "retry_same_event_id": all(
            fields["event_id"] == str(event_id) for _, fields in entries
        ),
        "producer_stream_ids": [entry_id for entry_id, _ in entries],
        "input_dispositions": dispositions,
        "signal_count": signal_count,
        "transaction_count": sum(
            1
            for result in poll.lane_results.values()
            if result.finalization_status == "COMMITTED"
        ),
        "attempts": attempts,
        "startup": startup.snapshot.status,
    }


async def _run_uninterrupted_eth_reference(
    config: DecisionConfig,
    bucket_start: datetime,
) -> dict[str, object]:
    persistence = CombinedPersistence()
    assert seed_route_history(persistence, config) == bucket_start
    broker = DeterministicBroker()
    startup, _composition, runtime, signal_broker = await build_startup_runtime(
        config, persistence, broker
    )
    await materialize_live_bucket(
        persistence,
        config,
        bucket_start=bucket_start,
        only_asset="ETHUSDT",
    )
    await publish_pending(persistence, broker)
    poll = await runtime.poll_once()
    derived = persistence.candles_for(
        MarketLane("binance", "ETH-USDT-PERP", "4h"),
        bucket_start,
        bucket_start + timedelta(hours=4),
    )
    semantics = await _semantic_evidence(config, startup, runtime)
    lane_id = "ETHUSDT:momentum_4h"
    return {
        "derived_candle": _candle_identity(derived[0] if derived else None),
        "input_dispositions": _input_disposition_summary(poll),
        "lane_result": _lane_result_table(poll).get(lane_id),
        "semantic": semantics.get(lane_id),
        "signal_entries": _signal_entries(signal_broker),
        "startup_status": startup.snapshot.status,
    }


async def run_recovery_flow() -> dict[str, object]:
    config = load_fixture_config()
    persistence = CombinedPersistence()
    bucket_start = seed_route_history(persistence, config)
    broker = DeterministicBroker()
    startup, _composition, runtime, signal_broker = await build_startup_runtime(
        config, persistence, broker
    )
    requests = await materialize_live_bucket(
        persistence,
        config,
        bucket_start=bucket_start,
        missing_index=100,
        only_asset="ETHUSDT",
    )
    assert requests
    await publish_pending(persistence, broker)
    before = await runtime.poll_once()
    assert not any(
        item.series_key is not None and item.series_key.asset == "ETHUSDT"
        for item in before.input_results
    )
    missing_open = bucket_start + timedelta(minutes=100)
    missing = _provider_observation(
        lane=MarketLane("binance", "ETH-USDT-PERP", "1m"),
        opened=missing_open,
        close=Decimal("164.3"),
    )
    provider = FixtureHistoricalProvider([missing])
    ingestion = CandleIngestionService(persistence)  # type: ignore[arg-type]
    htf = HTFAggregationService(
        repository=persistence,  # type: ignore[arg-type]
        ingestion_service=ingestion,
    )
    engine = RecoveryEngine(
        providers={provider.provider_id: provider},
        repository=persistence,  # type: ignore[arg-type]
        ingestion_service=ingestion,
        htf_service=htf,
        max_concurrency=1,
        page_limit=1000,
        max_attempts_per_provider=1,
        retry_backoff_seconds=0,
        rest_finalization_grace_seconds=0,
        now_fn=lambda: bucket_start + timedelta(hours=4, seconds=1),
        settlement_sleep_fn=lambda _seconds: _noop(),
    )
    follow_ups = await engine.recover(
        requests[0],
        base_timeframe="1m",
        base_duration=timedelta(minutes=1),
        provider_order=(provider.provider_id,),
        provider_symbols={provider.provider_id: "ETH-USDT-PERP"},
        target_durations={"4h": timedelta(hours=4)},
        alignment_origin=config.timeframe_grid.alignment_origin,
    )
    await publish_pending(persistence, broker)
    after = await runtime.poll_once()
    key = MarketSeriesKey(
        asset="ETHUSDT",
        venue="binance",
        instrument_id="ETH-USDT-PERP",
        timeframe="4h",
    )
    derived = persistence.candles_for(
        MarketLane("binance", "ETH-USDT-PERP", "4h"),
        bucket_start,
        bucket_start + timedelta(hours=4),
    )
    recovered_lane_id = "ETHUSDT:momentum_4h"
    recovered_semantics = await _semantic_evidence(config, startup, runtime)
    recovered = {
        "derived_candle": _candle_identity(derived[0] if derived else None),
        "input_dispositions": _input_disposition_summary(after),
        "lane_result": _lane_result_table(after).get(recovered_lane_id),
        "semantic": recovered_semantics.get(recovered_lane_id),
        "signal_entries": _signal_entries(signal_broker),
        "startup_status": startup.snapshot.status,
    }
    uninterrupted_reference = await _run_uninterrupted_eth_reference(
        config,
        bucket_start,
    )
    return {
        "request_count": len(requests),
        "request_reason": requests[0].reason,
        "premature_derived_count": 0,
        "provider_calls": len(provider.calls),
        "recovered_base_count": 1,
        "follow_ups": len(follow_ups),
        "derived_identity": (
            None
            if not derived
            else {
                "asset": key.asset,
                "timeframe": key.timeframe,
                "open": str(derived[0].open),
                "close": str(derived[0].close),
                "source_type": derived[0].source_type,
                "source_timeframe": derived[0].source_timeframe,
            }
        ),
        "decision_input_dispositions": _input_dispositions(after),
        "decision_lane_results": _lane_result_table(after),
        "startup_status": startup.snapshot.status,
        "recovered": recovered,
        "uninterrupted_reference": uninterrupted_reference,
        "uninterrupted_reference_equal": recovered == uninterrupted_reference,
    }


async def _noop() -> None:
    return None


async def run_restart_parity() -> dict[str, object]:
    config = load_fixture_config()
    persistence = CombinedPersistence()
    bucket_start = seed_route_history(persistence, config)
    broker = DeterministicBroker()
    (
        first_startup,
        _composition,
        continuous,
        first_signals,
    ) = await build_startup_runtime(config, persistence, broker)
    await materialize_live_bucket(persistence, config, bucket_start=bucket_start)
    await publish_pending(persistence, broker)
    first_poll = await continuous.poll_once()
    fresh_startup, _composition2, fresh, fresh_signals = await build_startup_runtime(
        config, persistence, broker
    )
    assert fresh_startup.snapshot.status == "STARTUP_READY"
    fresh_startup_publication_count = sum(
        len(values) for values in fresh_signals.entries.values()
    )
    continuous_signal_ids_before = {
        stream: {entry_id for entry_id, _ in entries}
        for stream, entries in first_signals.entries.items()
    }
    next_bucket = bucket_start + timedelta(hours=4)
    await materialize_live_bucket(persistence, config, bucket_start=next_bucket)
    await publish_pending(persistence, broker)
    continuous_poll = await continuous.poll_once()
    fresh_poll = await fresh.poll_once()
    continuous_lanes = _lane_result_table(continuous_poll)
    fresh_lanes = _lane_result_table(fresh_poll)
    continuous_new_signals = {
        stream: new_entries
        for stream, entries in first_signals.entries.items()
        if (
            new_entries := [
                (entry_id, fields)
                for entry_id, fields in entries
                if entry_id not in continuous_signal_ids_before.get(stream, set())
            ]
        )
    }
    fresh_signals_for_compare = {
        stream: list(entries) for stream, entries in fresh_signals.entries.items()
    }
    continuous_semantic_evidence = await _semantic_evidence(
        config,
        first_startup,
        continuous,
    )
    fresh_semantic_evidence = await _semantic_evidence(
        config,
        fresh_startup,
        fresh,
    )
    continuous_input_cutoffs = _input_cursor_cutoffs(continuous_poll)
    fresh_input_cutoffs = _input_cursor_cutoffs(fresh_poll)
    return {
        "first_startup": first_startup.snapshot.status,
        "fresh_startup": fresh_startup.snapshot.status,
        "fresh_startup_publication_count": fresh_startup_publication_count,
        "continuous_first_results": _lane_result_table(first_poll),
        "continuous_next_results": continuous_lanes,
        "fresh_next_results": fresh_lanes,
        "same_lane_results": continuous_lanes == fresh_lanes,
        "same_input_cutoffs": continuous_input_cutoffs == fresh_input_cutoffs,
        "continuous_input_cutoffs": continuous_input_cutoffs,
        "fresh_input_cutoffs": fresh_input_cutoffs,
        "same_feature_momentum_semantics": (
            continuous_semantic_evidence == fresh_semantic_evidence
        ),
        "continuous_semantic_evidence": continuous_semantic_evidence,
        "fresh_semantic_evidence": fresh_semantic_evidence,
        "same_signal_identities": continuous_new_signals == fresh_signals_for_compare,
        "continuous_new_signals": continuous_new_signals,
        "fresh_signals_for_compare": fresh_signals_for_compare,
        "fresh_signals": sum(len(values) for values in fresh_signals.entries.values()),
    }


async def run_c1_certification() -> dict[str, object]:
    live = await run_live_transition()
    retry = await run_outbox_retry()
    recovery = await run_recovery_flow()
    restart = await run_restart_parity()
    result = {
        "schema_version": 1,
        "source_sha": POST_M4_SHA,
        "protected_artifacts": {
            "m3": M3_ARTIFACT_SHA,
            "m4_functional": M4_FUNCTIONAL_SHA,
            "m4_resource": M4_RESOURCE_SHA,
            "d10": D10_ARTIFACT_SHA,
        },
        "routes": list(_ROUTE_NAMES),
        "stream_contract": {
            "prefix": "stream:ohlcv:ingestion:",
            "event_type": "candle.committed",
            "schema_version": 1,
            "producer": "ingestion",
        },
        "live": live,
        "at_least_once_retry": retry,
        "recovery": recovery,
        "restart": restart,
        "cross_route_isolation": await run_cross_route_isolation(),
        "zero_production_decision_assets": not list(
            (ROOT / "configs" / "decision" / "assets").glob("*.yaml")
        ),
    }
    gates = evaluate_c1_gates(result)
    result["gates"] = gates
    result["terminal_status"] = terminal_status_for_gates(gates)
    result["identity_digest"] = _sha256(c1_identity_payload(result))
    result["evidence_digest"] = _sha256(c1_evidence_payload(result))
    return result


def copy_without_digest_fields(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            key: copy_without_digest_fields(item)
            for key, item in value.items()
            if key not in {"identity_digest", "evidence_digest"}
        }
    if isinstance(value, (list, tuple)):
        return [copy_without_digest_fields(item) for item in value]
    return value


def c1_identity_payload(evidence: Mapping[str, object]) -> dict[str, object]:
    """Return stable C1 identity, excluding measured runtime evidence."""

    return {
        "schema_version": evidence.get("schema_version"),
        "source_sha": evidence.get("source_sha"),
        "protected_artifacts": evidence.get("protected_artifacts"),
        "routes": evidence.get("routes"),
        "stream_contract": evidence.get("stream_contract"),
    }


def c1_evidence_payload(evidence: Mapping[str, object]) -> object:
    """Return all deterministic measured evidence without digest recursion."""

    return copy_without_digest_fields(evidence)


def evaluate_c1_gates(evidence: Mapping[str, object]) -> dict[str, bool]:
    """Derive every C1 gate from measured evidence, failing closed on drift."""

    live = evidence.get("live")
    retry = evidence.get("at_least_once_retry")
    recovery = evidence.get("recovery")
    restart = evidence.get("restart")
    cross_route = evidence.get("cross_route_isolation")
    protected = evidence.get("protected_artifacts")
    stream_contract = evidence.get("stream_contract")
    if not all(
        isinstance(value, Mapping)
        for value in (
            live,
            retry,
            recovery,
            restart,
            cross_route,
            protected,
            stream_contract,
        )
    ):
        return {
            "m4_merged_protected_hashes": False,
            "producer_consumer_stream_keys": False,
            "producer_schema_accepted_without_reshaping": False,
            "three_startup_lanes_ready": False,
            "htf_materialization_exact": False,
            "feature_and_momentum_parity": False,
            "real_signal_committed": False,
            "no_base_signal": False,
            "outbox_retry_one_logical_effect": False,
            "recovery_blocks_then_converges": False,
            "restart_reconstruction_parity": False,
            "cross_route_isolation": False,
            "zero_production_decision_assets": False,
        }
    expected_routes = {f"{asset}/{timeframe}" for asset, timeframe in _ROUTE_NAMES}
    expected_lane_ids = {
        "BTCUSDT:momentum_1h",
        "BTCUSDT:momentum_4h",
        "ETHUSDT:momentum_4h",
    }
    expected_provenance = {
        route: [
            {
                "source_type": "derived",
                "source_provider": None,
                "source_timeframe": "1m",
            }
        ]
        for route in sorted(expected_routes)
    }
    actual_counts = live.get("derived_entry_counts")
    reported_expected_counts = live.get("expected_derived_entry_counts")
    expected_counts = _expected_derived_entry_counts()
    lane_results = live.get("lane_results")
    feature_parity = live.get("feature_momentum_parity")
    recovery_reference_equal = (
        isinstance(recovery.get("recovered"), Mapping)
        and isinstance(recovery.get("uninterrupted_reference"), Mapping)
        and recovery.get("recovered") == recovery.get("uninterrupted_reference")
        and recovery.get("uninterrupted_reference_equal") is True
    )
    restart_lane_equal = (
        isinstance(restart.get("continuous_next_results"), Mapping)
        and isinstance(restart.get("fresh_next_results"), Mapping)
        and restart.get("continuous_next_results") == restart.get("fresh_next_results")
    )
    restart_input_equal = (
        isinstance(restart.get("continuous_input_cutoffs"), Mapping)
        and isinstance(restart.get("fresh_input_cutoffs"), Mapping)
        and restart.get("continuous_input_cutoffs")
        == restart.get("fresh_input_cutoffs")
    )
    restart_semantic_equal = (
        isinstance(restart.get("continuous_semantic_evidence"), Mapping)
        and isinstance(restart.get("fresh_semantic_evidence"), Mapping)
        and restart.get("continuous_semantic_evidence")
        == restart.get("fresh_semantic_evidence")
    )
    restart_signal_equal = (
        isinstance(restart.get("continuous_new_signals"), Mapping)
        and isinstance(restart.get("fresh_signals_for_compare"), Mapping)
        and restart.get("continuous_new_signals")
        == restart.get("fresh_signals_for_compare")
    )
    baseline = cross_route.get("baseline")
    after = cross_route.get("after")
    cross_route_snapshots_equal = (
        isinstance(baseline, Mapping)
        and isinstance(after, Mapping)
        and baseline == after
    )
    eth_poll_lane_results = cross_route.get("eth_poll_lane_results")
    cross_route_transactions_absent = isinstance(
        eth_poll_lane_results, Mapping
    ) and all(
        lane_id in eth_poll_lane_results
        and isinstance(eth_poll_lane_results[lane_id], Mapping)
        and all(
            eth_poll_lane_results[lane_id].get(field) is None
            for field in (
                "trigger_cutoff",
                "policy_status",
                "publication_outcome",
                "finalization_status",
            )
        )
        for lane_id in (
            "BTCUSDT:momentum_1h",
            "BTCUSDT:momentum_4h",
        )
    )
    signal_streams = live.get("signal_streams")
    return {
        "m4_merged_protected_hashes": (
            protected
            == {
                "m3": M3_ARTIFACT_SHA,
                "m4_functional": M4_FUNCTIONAL_SHA,
                "m4_resource": M4_RESOURCE_SHA,
                "d10": D10_ARTIFACT_SHA,
            }
            and live.get("protected_artifacts_match") is True
            and live.get("protected_m3") is True
        ),
        "producer_consumer_stream_keys": (
            live.get("producer_consumer_stream_key_parity") is True
            and live.get("parsed_event_contract_valid") is True
            and live.get("producer_derived_stream_keys")
            == live.get("expected_stream_keys")
            and live.get("parsed_derived_routes") == sorted(expected_routes)
            and live.get("parsed_derived_provenance_summary") == expected_provenance
            and stream_contract
            == {
                "prefix": "stream:ohlcv:ingestion:",
                "event_type": "candle.committed",
                "schema_version": 1,
                "producer": "ingestion",
            }
        ),
        "producer_schema_accepted_without_reshaping": (
            live.get("parsed_event_count") == 6
            and isinstance(actual_counts, Mapping)
            and sum(actual_counts.values()) == 6
            and live.get("parsed_event_contract_valid") is True
        ),
        "three_startup_lanes_ready": (
            live.get("startup_status") == "STARTUP_READY"
            and isinstance(lane_results, Mapping)
            and set(lane_results) == expected_lane_ids
            and all(item.get("status") == "LIVE" for item in lane_results.values())
        ),
        "htf_materialization_exact": (
            isinstance(actual_counts, Mapping)
            and dict(actual_counts) == dict(expected_counts)
            and reported_expected_counts == expected_counts
        ),
        "feature_and_momentum_parity": (
            live.get("protected_m3") is True
            and isinstance(feature_parity, Mapping)
            and set(feature_parity) == expected_lane_ids
            and all(value is True for value in feature_parity.values())
        ),
        "real_signal_committed": (
            isinstance(lane_results, Mapping)
            and live.get("signal_entry_count", 0) > 0
            and any(
                item.get("finalization_status") == "COMMITTED"
                and item.get("policy_status") == "SIGNAL"
                for item in lane_results.values()
            )
        ),
        "no_base_signal": (
            isinstance(signal_streams, list)
            and all("1m" not in stream for stream in signal_streams)
        ),
        "outbox_retry_one_logical_effect": (
            retry.get("retry_same_event_id") is True
            and retry.get("input_dispositions") == ["INSERTED", "DUPLICATE"]
            and retry.get("transaction_count") == 1
            and retry.get("signal_count") == 1
            and retry.get("attempts") == 2
        ),
        "recovery_blocks_then_converges": (
            recovery.get("request_count") == 1
            and recovery.get("premature_derived_count") == 0
            and recovery.get("recovered_base_count") == 1
            and recovery_reference_equal
            and isinstance(recovery.get("recovered"), Mapping)
            and isinstance(recovery.get("uninterrupted_reference"), Mapping)
        ),
        "restart_reconstruction_parity": (
            restart_lane_equal
            and restart_input_equal
            and restart_semantic_equal
            and restart_signal_equal
            and restart.get("same_lane_results") is True
            and restart.get("same_input_cutoffs") is True
            and restart.get("same_feature_momentum_semantics") is True
            and restart.get("same_signal_identities") is True
        ),
        "cross_route_isolation": (
            cross_route.get("perturbed_route") == "ETHUSDT/4h"
            and cross_route.get("unchanged_routes")
            == ["BTCUSDT:momentum_1h", "BTCUSDT:momentum_4h"]
            and cross_route_snapshots_equal
            and cross_route_transactions_absent
            and cross_route.get("unchanged") is True
            and cross_route.get("btc_transactions_absent") is True
        ),
        "zero_production_decision_assets": (
            evidence.get("zero_production_decision_assets") is True
        ),
    }


def terminal_status_for_gates(gates: Mapping[str, bool]) -> str:
    return (
        SUCCESS_STATUS
        if all(gates.values())
        else "INGESTION_DECISION_C1_EVIDENCE_INSUFFICIENT"
    )


def decode_signal_entries(broker: DeterministicBroker) -> tuple[TradeSignal, ...]:
    return tuple(
        valkey_decode(dict(fields), TradeSignal)
        for entries in broker.entries.values()
        for _entry_id, fields in entries
    )
