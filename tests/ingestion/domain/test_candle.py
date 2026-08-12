from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.ingestion_app.domain.candle import CandleObservation, CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane

LANE = MarketLane("binance", "BTC-USDT-PERP", "2h")
OPEN_TIME = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
CLOSE_TIME = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)


def _observation(**changes: object) -> CandleObservation:
    values: dict[str, object] = {
        "lane": LANE,
        "provider_id": "binance_native",
        "provider_symbol": "BTCUSDT",
        "transport": "rest",
        "open_time": OPEN_TIME,
        "close_time": CLOSE_TIME,
        "open": Decimal(10),
        "high": Decimal(12),
        "low": Decimal(9),
        "close": Decimal(11),
        "volume": Decimal(3),
        "taker_buy_base": None,
        "received_at": CLOSE_TIME,
    }
    values.update(changes)
    return CandleObservation(**values)  # type: ignore[arg-type]


def _canonical(**changes: object) -> CanonicalCandle:
    values: dict[str, object] = {
        "lane": LANE,
        "open_time": OPEN_TIME,
        "close_time": CLOSE_TIME,
        "open": Decimal(10),
        "high": Decimal(12),
        "low": Decimal(9),
        "close": Decimal(11),
        "volume": Decimal(3),
        "taker_buy_base": None,
        "source_type": "provider",
        "source_provider": "binance_native",
        "source_timeframe": None,
    }
    values.update(changes)
    return CanonicalCandle(**values)  # type: ignore[arg-type]


def test_valid_provider_observation() -> None:
    observation = _observation(provider_event_id="event-1")

    assert observation.provider_event_id == "event-1"
    assert observation.close_time == CLOSE_TIME
    assert not hasattr(observation, "finalized")


def test_observation_is_immutable() -> None:
    observation = _observation()

    with pytest.raises(FrozenInstanceError):
        observation.close = Decimal("11.5")  # type: ignore[misc]


@pytest.mark.parametrize("field_name", ["provider_id", "provider_symbol", "transport"])
def test_observation_rejects_missing_provider_metadata(field_name: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        _observation(**{field_name: " "})


def test_blank_provider_event_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        _observation(provider_event_id=" ")


@pytest.mark.parametrize("field_name", ["open", "high", "low", "close", "volume"])
@pytest.mark.parametrize("invalid_value", [1, 1.0, "1"])
def test_observation_requires_decimal_numeric_values(
    field_name: str,
    invalid_value: object,
) -> None:
    with pytest.raises(TypeError, match=f"{field_name} must be a Decimal"):
        _observation(**{field_name: invalid_value})


@pytest.mark.parametrize(
    "invalid_value",
    [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")],
)
def test_observation_rejects_non_finite_decimal(invalid_value: Decimal) -> None:
    with pytest.raises(ValueError, match="open must be finite"):
        _observation(open=invalid_value)


@pytest.mark.parametrize(
    "changes",
    [
        {"high": Decimal(9)},
        {"high": Decimal(10)},
        {"low": Decimal(11)},
        {"low": Decimal(12)},
        {"low": Decimal(13), "high": Decimal(12)},
    ],
)
def test_observation_rejects_invalid_ohlc_bounds(changes: dict[str, Decimal]) -> None:
    with pytest.raises(ValueError):
        _observation(**changes)


def test_observation_rejects_negative_volume_and_accepts_zero() -> None:
    with pytest.raises(ValueError, match="volume must be non-negative"):
        _observation(volume=Decimal(-1))

    assert _observation(volume=Decimal(0)).volume == Decimal(0)


def test_observation_taker_buy_base_is_optional_but_non_negative() -> None:
    assert _observation(taker_buy_base=None).taker_buy_base is None
    assert _observation(taker_buy_base=Decimal(0)).taker_buy_base == Decimal(0)
    with pytest.raises(ValueError, match="taker_buy_base must be non-negative"):
        _observation(taker_buy_base=Decimal(-1))


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("open_time", datetime(2026, 1, 1)),  # noqa: DTZ001
        ("close_time", datetime(2026, 1, 1, 0, 1)),  # noqa: DTZ001
        ("received_at", datetime(2026, 1, 1, 0, 1)),  # noqa: DTZ001
        ("provider_close_time", datetime(2026, 1, 1, 0, 1)),  # noqa: DTZ001
        (
            "open_time",
            datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))),
        ),
    ],
)
def test_observation_requires_utc_timestamps(
    field_name: str,
    invalid_value: datetime,
) -> None:
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        _observation(**{field_name: invalid_value})


@pytest.mark.parametrize(
    "close_time",
    [OPEN_TIME, datetime(2025, 12, 31, 23, 59, tzinfo=UTC)],
)
def test_observation_requires_positive_time_range(close_time: datetime) -> None:
    with pytest.raises(ValueError, match="close_time must be after open_time"):
        _observation(close_time=close_time)


def test_observation_does_not_validate_timeframe_alignment() -> None:
    observation = _observation()

    assert observation.lane.timeframe == "2h"
    assert observation.close_time - observation.open_time == timedelta(minutes=1)


def test_valid_provider_canonical_candle() -> None:
    candle = _canonical()

    assert candle.source_type == "provider"
    assert candle.source_provider == "binance_native"
    assert candle.source_timeframe is None


def test_valid_derived_canonical_candle() -> None:
    candle = _canonical(
        source_type="derived",
        source_provider=None,
        source_timeframe="1m",
    )

    assert candle.source_type == "derived"
    assert candle.source_provider is None
    assert candle.source_timeframe == "1m"


@pytest.mark.parametrize(
    "changes",
    [
        {"source_type": "provider", "source_provider": None},
        {"source_type": "provider", "source_timeframe": "1m"},
        {"source_type": "derived", "source_provider": "binance_native"},
        {"source_type": "derived", "source_timeframe": None},
        {"source_type": "unknown"},
    ],
)
def test_canonical_provenance_invariants(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _canonical(**changes)


def test_canonical_candle_is_immutable_and_uses_common_validation() -> None:
    candle = _canonical()

    with pytest.raises(FrozenInstanceError):
        candle.close = Decimal("11.5")  # type: ignore[misc]
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        _canonical(open_time=datetime(2026, 1, 1))  # noqa: DTZ001
    with pytest.raises(TypeError):
        _canonical(open=1.0)
    with pytest.raises(ValueError):
        _canonical(volume=Decimal(-1))
