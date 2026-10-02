from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from apps.ingestion_app.domain.instrument import MarketLane


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
