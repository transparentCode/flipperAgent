from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.decision_app.domain.market_state import MarketSeriesKey, TimeframeGrid
from apps.decision_app.settings import (
    CanonicalInstrument,
    DecisionAssetSettings,
    DecisionConfig,
    DecisionGlobalSettings,
    DecisionLaneSettings,
    DecisionPolicySettings,
    load_canonical_ingestion_contract,
)
from apps.decision_app.storage.market_history import (
    CanonicalHistoryError,
    CanonicalMarketHistoryRepository,
    InMemoryCanonicalMarketHistoryRepository,
)
from libs.common.config import ConfigManager
from libs.contracts.decision import CausalBarView

BASE = datetime(2026, 1, 5, tzinfo=UTC)
GRID = TimeframeGrid(
    alignment_origin=BASE,
    durations={"1h": timedelta(hours=1)},
)


def _decision_config(*, instrument_id: str = "BTC-USDT-PERP") -> DecisionConfig:
    lane = DecisionLaneSettings(
        decision_timeframe="1h",
        trigger_timeframe="1h",
        trigger_mode="on_bar_close",
        policy=DecisionPolicySettings(
            name="passthrough",
            version="1",
            parameters={"source_slot": "primary"},
        ),
        bindings={
            "primary": {
                "plugin": "synthetic",
                "version": "1",
            }
        },
    )
    asset = DecisionAssetSettings(
        manifest_asset="BTC",
        decision_asset="BTCUSDT",
        venue="binance",
        instrument_id=instrument_id,
        lanes={"main": lane},
    )
    return DecisionConfig(
        global_settings=DecisionGlobalSettings(),
        assets={"BTC": asset},
        timeframe_grid=GRID,
        instruments={
            "BTC:BTC-USDT-PERP": CanonicalInstrument(
                manifest_asset="BTC",
                instrument_id="BTC-USDT-PERP",
                venue="binance",
                timeframes=("1h",),
            )
        },
    )


def _bar(index: int) -> CausalBarView:
    opened = BASE + timedelta(hours=index)
    closed = opened + timedelta(hours=1)
    return CausalBarView(
        timeframe="1h",
        bar_open_at=opened,
        bar_close_at=closed,
        market_as_of=closed,
        open=Decimal(100),
        high=Decimal(103),
        low=Decimal(99),
        close=Decimal(101),
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        closed=True,
    )


def test_decision_config_is_strict_and_nested_values_are_immutable() -> None:
    with pytest.raises(ValueError):
        DecisionLaneSettings.model_validate(
            {
                "decision_timeframe": "1h",
                "trigger_timeframe": "1h",
                "trigger_mode": "on_bar_close",
                "policy": {"name": "passthrough", "version": "1"},
                "bindings": {"primary": {"plugin": "x", "version": "1"}},
                "unexpected": True,
            }
        )

    config = _decision_config()
    with pytest.raises(TypeError):
        config.assets["BTC"].lanes["main"].policy.parameters["new"] = True
    with pytest.raises(AttributeError):
        config.assets = {}


def test_manifest_and_decision_asset_identity_are_not_conflated() -> None:
    with pytest.raises(ValueError, match="unknown ingestion instrument"):
        _decision_config(instrument_id="ETH-USDT-PERP")

    asset = _decision_config().assets["BTC"]
    assert asset.manifest_asset == "BTC"
    assert asset.decision_asset == "BTCUSDT"
    assert asset.instrument_id == "BTC-USDT-PERP"


def test_canonical_ingestion_contract_is_loaded_through_config_manager() -> None:
    grid, instruments = load_canonical_ingestion_contract(ConfigManager())

    assert grid.duration("1m") == timedelta(minutes=1)
    assert grid.duration("4h") == timedelta(hours=4)
    assert len(instruments) == 6
    assert any(
        instrument.manifest_asset == "BTC"
        and instrument.instrument_id == "BTC-USDT-PERP"
        for instrument in instruments.values()
    )


def test_minimal_decision_global_namespace_is_strict_and_has_no_asset_graph() -> None:
    manager = ConfigManager()
    manager.register_file("configs/decision/global.yaml")

    assert manager.get("decision") == {
        "server": {"host": "0.0.0.0", "port": 8004},
        "live_input": {"batch_size": 10, "block_ms": 1000},
        "signal_publication": {
            "stream_maxlen": 1000,
            "stream_approximate": True,
        },
        "price_relay": {
            "stream_maxlen": 200,
            "stream_approximate": True,
        },
        "shadow_publication": {
            "stream_maxlen": 1000,
            "stream_approximate": True,
        },
    }
    with pytest.raises(ValueError):
        DecisionGlobalSettings.model_validate({"unexpected": True})
    with pytest.raises(ValueError, match="must contain assets"):
        from apps.decision_app.settings import load_decision_config

        load_decision_config(ConfigManager())


class _Connection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.query = ""

    async def fetch(self, query: str, *_args: object) -> list[dict[str, object]]:
        self.query = query
        return self.rows

    async def fetchrow(self, query: str, *_args: object) -> dict[str, object] | None:
        self.query = query
        return self.rows[0] if self.rows else None


class _Acquire:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _Connection:
        return self.connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)


def _row(bar: CausalBarView) -> dict[str, object]:
    return {
        "venue": "binance",
        "instrument_id": "BTC-USDT-PERP",
        "timeframe": "1h",
        "open_time": bar.bar_open_at,
        "close_time": bar.bar_close_at,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "taker_buy_base": bar.taker_buy_base,
        "source_type": "provider",
        "source_provider": "test",
        "source_timeframe": None,
    }


@pytest.mark.asyncio
async def test_db_history_limit_returns_latest_rows_in_causal_order() -> None:
    key = MarketSeriesKey(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        timeframe="1h",
    )
    newest = _row(_bar(3))
    previous = _row(_bar(2))
    connection = _Connection([newest, previous])
    repository = CanonicalMarketHistoryRepository(
        _Pool(connection), timeframe_grid=GRID
    )

    bars = await repository.fetch_bars(key, through=_bar(3).market_as_of, limit=2)

    assert "ORDER BY open_time DESC" in connection.query
    assert tuple(bar.bar_open_at for bar in bars) == (
        _bar(2).bar_open_at,
        _bar(3).bar_open_at,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_type", "source_provider", "source_timeframe", "accepted"),
    [
        ("provider", "test", None, True),
        ("derived", None, "1m", True),
        ("provider", None, None, False),
        ("derived", "test", "1m", False),
        ("derived", None, None, False),
        ("unknown", "test", "1m", False),
    ],
)
async def test_db_history_enforces_canonical_provenance(
    source_type: str,
    source_provider: str | None,
    source_timeframe: str | None,
    accepted: bool,
) -> None:
    key = MarketSeriesKey(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        timeframe="1h",
    )
    row = _row(_bar(3))
    row.update(
        source_type=source_type,
        source_provider=source_provider,
        source_timeframe=source_timeframe,
    )
    repository = CanonicalMarketHistoryRepository(
        _Pool(_Connection([row])), timeframe_grid=GRID
    )

    if accepted:
        bars = await repository.fetch_bars(key, limit=1)
        assert len(bars) == 1
    else:
        with pytest.raises(CanonicalHistoryError, match="provenance"):
            await repository.fetch_bars(key, limit=1)


@pytest.mark.asyncio
async def test_db_latest_cutoff_enforces_canonical_provenance() -> None:
    key = MarketSeriesKey(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        timeframe="1h",
    )
    row = _row(_bar(3))
    row.update(source_type="derived", source_provider=None, source_timeframe="1m")
    repository = CanonicalMarketHistoryRepository(
        _Pool(_Connection([row])), timeframe_grid=GRID
    )

    assert await repository.fetch_latest_cutoff(key) == _bar(3).market_as_of


def test_in_memory_canonical_history_rejects_projected_bars() -> None:
    projected = CausalBarView(
        timeframe="1h",
        bar_open_at=BASE,
        bar_close_at=BASE + timedelta(hours=1),
        market_as_of=BASE + timedelta(minutes=30),
        open=Decimal(100),
        high=Decimal(103),
        low=Decimal(99),
        close=Decimal(101),
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        closed=False,
    )
    key = MarketSeriesKey(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        timeframe="1h",
    )
    with pytest.raises(ValueError, match="closed bars"):
        InMemoryCanonicalMarketHistoryRepository(
            {key: (projected,)}, timeframe_grid=GRID
        )
