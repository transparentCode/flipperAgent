from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.decision_app.composition import sr_initialization_requirement
from apps.decision_app.data.resolver import DataPolicy, DataResolver, DataSourceCatalog
from apps.decision_app.domain.market_state import MarketSeriesKey, TimeframeGrid
from apps.decision_app.features.definitions import SR_ATR_DEFINITION
from apps.decision_app.features.planning import FeatureCatalog, FeaturePolicy
from apps.decision_app.planning.catalog import PluginCatalog
from apps.decision_app.runtime.plugins import (
    RuntimePluginCatalog,
    RuntimePluginDefinition,
)
from apps.decision_app.runtime.startup import DecisionStartupCoordinator
from apps.decision_app.settings import (
    CanonicalInstrument,
    DecisionAssetSettings,
    DecisionConfig,
    DecisionGlobalSettings,
    DecisionLaneSettings,
    DecisionPolicySettings,
)
from apps.decision_app.storage.checkpoints import InMemoryCheckpointRepository
from apps.decision_app.storage.market_history import (
    InMemoryCanonicalMarketHistoryRepository,
)
from apps.decision_app.transport.ingestion import canonical_ingestion_stream_key
from libs.contracts.decision import CausalBarView
from libs.models.sr.adapters.decision_plugin import SR_MODEL_SPEC, SRDecisionPlugin

BASE = datetime(2026, 1, 5, tzinfo=UTC)
GRID = TimeframeGrid(
    alignment_origin=BASE,
    durations={"1h": timedelta(hours=1)},
)
SERIES = MarketSeriesKey(
    asset="BTCUSDT",
    venue="binance",
    instrument_id="BTC-USDT-PERP",
    timeframe="1h",
)
RAW_SR_CONFIG = {
    "version": "1",
    "defaults": {
        "detection": {"pivot_span_bars": 1, "zone_half_width_atr": 0.0},
        "association": {"merge_distance_atr": 0.5},
        "lifecycle": {
            "touch_tolerance_atr": 0.25,
            "break_buffer_atr": 0.5,
            "break_confirm_closes": 2,
            "max_age_bars": 20,
        },
        "runtime": {"max_active_zones": 8},
    },
}


def _bar(index: int) -> CausalBarView:
    opened = BASE + timedelta(hours=index)
    closed = opened + timedelta(hours=1)
    close = Decimal(101 + index % 3)
    return CausalBarView(
        timeframe="1h",
        bar_open_at=opened,
        bar_close_at=closed,
        market_as_of=closed,
        open=Decimal(100 + index % 2),
        high=close + Decimal(3),
        low=close - Decimal(3),
        close=close,
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        closed=True,
    )


def _stream_fields(index: int) -> dict[str, str]:
    bar = _bar(index)
    payload = {
        "venue": SERIES.venue,
        "instrument_id": SERIES.instrument_id,
        "timeframe": SERIES.timeframe,
        "open_time": bar.bar_open_at.isoformat().replace("+00:00", "Z"),
        "close_time": bar.bar_close_at.isoformat().replace("+00:00", "Z"),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": str(bar.volume),
        "taker_buy_base": str(bar.taker_buy_base),
        "source_type": "provider",
        "source_provider": "test",
        "source_timeframe": None,
    }
    return {
        "event_id": f"event-{index}",
        "event_type": "candle.committed",
        "schema_version": "1",
        "producer": "ingestion",
        "occurred_at": bar.bar_close_at.isoformat().replace("+00:00", "Z"),
        "payload": json.dumps(payload),
    }


class _TailClient:
    def __init__(self, index: int) -> None:
        self.index = index

    async def xrevrange(self, stream: str, *_args: object, count: int = 1):
        assert stream == canonical_ingestion_stream_key(SERIES)
        assert count == 1
        return [(f"{self.index}-0", _stream_fields(self.index))]


def _config() -> DecisionConfig:
    lane = DecisionLaneSettings(
        decision_timeframe="1h",
        trigger_timeframe="1h",
        trigger_mode="on_bar_close",
        policy=DecisionPolicySettings(
            name="passthrough",
            version="1",
            parameters={"source_slot": "sr_primary"},
        ),
        bindings={
            "sr_primary": {
                "plugin": "sr",
                "version": "1",
                "parameters": {"sr_config": RAW_SR_CONFIG},
            }
        },
    )
    asset = DecisionAssetSettings(
        manifest_asset="BTC",
        decision_asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        lanes={"main": lane},
    )
    return DecisionConfig(
        global_settings=DecisionGlobalSettings(),
        assets={"BTC": asset},
        timeframe_grid=GRID,
        instruments={
            "BTC": CanonicalInstrument(
                manifest_asset="BTC",
                instrument_id="BTC-USDT-PERP",
                venue="binance",
                timeframes=("1h",),
            )
        },
    )


def _coordinator(
    history: InMemoryCanonicalMarketHistoryRepository,
    checkpoints: InMemoryCheckpointRepository,
    tail_index: int,
) -> DecisionStartupCoordinator:
    source_catalog = DataSourceCatalog([])
    return DecisionStartupCoordinator(
        decision_config=_config(),
        plugin_catalog=PluginCatalog([SR_MODEL_SPEC]),
        feature_catalog=FeatureCatalog([SR_ATR_DEFINITION]),
        feature_policy=FeaturePolicy(
            name="operator", version="1", allowed_features=("ATR",)
        ),
        data_policy=DataPolicy(name="operator", version="1", concepts={}),
        source_catalog=source_catalog,
        runtime_plugin_catalog=RuntimePluginCatalog(
            [
                RuntimePluginDefinition(
                    plugin_name="sr",
                    plugin_version="1",
                    factory=SRDecisionPlugin,
                    initialization_requirement=sr_initialization_requirement,
                )
            ]
        ),
        history_repository=history,
        stream_client=_TailClient(tail_index),
        checkpoint_repository=checkpoints,
        data_resolver=DataResolver(source_catalog),
    )


@pytest.mark.asyncio
async def test_real_sr_startup_and_checkpointed_restart_are_publication_free() -> None:
    checkpoints = InMemoryCheckpointRepository()
    first_history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: tuple(_bar(index) for index in range(50))},
        timeframe_grid=GRID,
    )

    first = await _coordinator(first_history, checkpoints, tail_index=49).start()
    first_runtime = next(iter(first.runtimes.values()))
    first_checkpoint = await checkpoints.load(first_runtime.identity)

    assert first.snapshot.status == "STARTUP_READY"
    assert first.snapshot.no_publication is True
    assert first.snapshot.lane_evidence["BTCUSDT:main"].checkpoint_loaded is False
    assert first.snapshot.lane_evidence["BTCUSDT:main"].replay_step_count == 20
    assert first_checkpoint is not None
    assert first_checkpoint.market_as_of == _bar(49).market_as_of
    assert first_checkpoint.state_inception_at == _bar(30).market_as_of

    second_history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: tuple(_bar(index) for index in range(55))},
        timeframe_grid=GRID,
    )
    second = await _coordinator(second_history, checkpoints, tail_index=54).start()
    second_runtime = next(iter(second.runtimes.values()))
    second_checkpoint = await checkpoints.load(second_runtime.identity)

    assert second.snapshot.status == "STARTUP_READY"
    assert second.snapshot.no_publication is True
    assert second.snapshot.lane_evidence["BTCUSDT:main"].checkpoint_loaded is True
    assert second.snapshot.lane_evidence["BTCUSDT:main"].replay_step_count == 5
    assert second_checkpoint is not None
    assert second_checkpoint.market_as_of == _bar(54).market_as_of
    assert second_checkpoint.state_payload != first_checkpoint.state_payload
    assert second.snapshot.lane_watermarks["BTCUSDT:main"].last_disposition is None


@pytest.mark.asyncio
async def test_real_sr_checkpoint_catchup_exceeds_initialization_horizon() -> None:
    checkpoints = InMemoryCheckpointRepository()
    first_history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: tuple(_bar(index) for index in range(50))},
        timeframe_grid=GRID,
    )
    first = await _coordinator(first_history, checkpoints, tail_index=49).start()
    first_runtime = next(iter(first.runtimes.values()))
    first_checkpoint = await checkpoints.load(first_runtime.identity)
    assert first_checkpoint is not None

    # The SR initialization horizon is 20 bars, but a valid process restart
    # may need to replay a much longer retained interval from the checkpoint.
    second_history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: tuple(_bar(index) for index in range(100))},
        timeframe_grid=GRID,
    )
    second = await _coordinator(second_history, checkpoints, tail_index=99).start()
    second_runtime = next(iter(second.runtimes.values()))
    second_checkpoint = await checkpoints.load(second_runtime.identity)

    assert second.snapshot.status == "STARTUP_READY"
    assert second.snapshot.lane_evidence["BTCUSDT:main"].checkpoint_loaded is True
    assert second.snapshot.lane_evidence["BTCUSDT:main"].replay_step_count == 50
    assert second_checkpoint is not None
    assert second_checkpoint.market_as_of == _bar(99).market_as_of
    assert second_checkpoint.state_payload != first_checkpoint.state_payload
    # The temporary catch-up store must not enlarge the returned steady-state
    # BarStore beyond the D3/D4 capacity (ATR requires 15 bars here).
    assert second.bar_store.capacity_for(SERIES) == 15
    assert second.bar_store.retained_count(SERIES) == 15
