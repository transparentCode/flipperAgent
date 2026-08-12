from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from apps.ingestion_app.domain.instrument import Instrument, MarketLane


def _instrument(**changes: object) -> Instrument:
    values: dict[str, object] = {
        "instrument_id": "BTC-USDT-PERP",
        "venue": "binance",
        "market_type": "perpetual",
        "base_asset": "BTC",
        "quote_asset": "USDT",
        "settlement_asset": "USDT",
    }
    values.update(changes)
    return Instrument(**values)  # type: ignore[arg-type]


def test_valid_perpetual_instrument() -> None:
    instrument = _instrument()

    assert instrument.instrument_id == "BTC-USDT-PERP"
    assert instrument.settlement_asset == "USDT"


def test_instrument_allows_missing_settlement_asset() -> None:
    assert _instrument(settlement_asset=None).settlement_asset is None


@pytest.mark.parametrize(
    "field_name",
    ["instrument_id", "venue", "market_type", "base_asset", "quote_asset"],
)
def test_instrument_rejects_empty_identity_fields(field_name: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        _instrument(**{field_name: " "})


def test_instrument_rejects_blank_settlement_asset() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        _instrument(settlement_asset="\t")


def test_instrument_does_not_normalize_identity() -> None:
    instrument = _instrument(
        instrument_id=" btc-custom ",
        venue=" Binance ",
        base_asset="btc",
        quote_asset="usdt",
        settlement_asset=" usdt ",
    )

    assert instrument.instrument_id == " btc-custom "
    assert instrument.venue == " Binance "
    assert instrument.base_asset == "btc"
    assert instrument.quote_asset == "usdt"
    assert instrument.settlement_asset == " usdt "


def test_instrument_is_immutable() -> None:
    instrument = _instrument()

    with pytest.raises(FrozenInstanceError):
        instrument.venue = "other"  # type: ignore[misc]


def test_valid_arbitrary_timeframe_market_lane_is_hashable() -> None:
    lane = MarketLane(
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        timeframe="2h",
    )
    values = {lane: "subscription"}

    assert values[lane] == "subscription"
    assert not hasattr(lane, "provider")


def test_market_lane_is_immutable() -> None:
    lane = MarketLane("binance", "BTC-USDT-PERP", "1m")

    with pytest.raises(FrozenInstanceError):
        lane.timeframe = "2h"  # type: ignore[misc]


@pytest.mark.parametrize("field_name", ["venue", "instrument_id", "timeframe"])
def test_market_lane_rejects_empty_fields(field_name: str) -> None:
    values = {
        "venue": "binance",
        "instrument_id": "BTC-USDT-PERP",
        "timeframe": "2h",
    }
    values[field_name] = ""

    with pytest.raises(ValueError, match="non-empty"):
        MarketLane(**values)
