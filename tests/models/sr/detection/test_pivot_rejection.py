from datetime import datetime, timedelta, timezone

import pytest

from libs.models.sr.detection.pivot_rejection import (
    PivotRejectionConfig,
    detect_pivot_rejection_bands,
)
from libs.models.sr.domain import (
    ClosedBar,
    ContractValidationError,
    SRStateKey,
    ZoneSide,
)


def _bar(
    index: int,
    *,
    high: float,
    low: float,
    open_: float = 10.0,
    close: float = 11.0,
    atr: float = 2.0,
) -> ClosedBar:
    return ClosedBar(
        SRStateKey("venue", "asset", "1d"),
        str(index),
        datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=index),
        open_,
        high,
        low,
        close,
        atr,
    )


def test_strict_outside_pivot_emits_two_wick_bands_with_confirmation_atr() -> None:
    bars = tuple(_bar(index, high=12.0, low=8.0) for index in range(11))
    bars = (
        bars[:5]
        + (_bar(5, high=20.0, low=1.0, open_=10.0, close=15.0),)
        + bars[6:10]
        + (_bar(10, high=12.0, low=8.0, atr=3.0),)
    )
    candidates = detect_pivot_rejection_bands(bars, PivotRejectionConfig(5))
    assert [item.side for item in candidates] == [ZoneSide.RESISTANCE, ZoneSide.SUPPORT]
    assert [
        (item.geometry.lower_bound, item.geometry.upper_bound) for item in candidates
    ] == [(15.0, 20.0), (1.0, 10.0)]
    assert all(
        item.atr_at_creation == 3.0 and item.available_at == bars[-1].closed_at
        for item in candidates
    )


def test_tied_pivot_is_rejected_and_invalid_config_fails_closed() -> None:
    bars = tuple(
        _bar(index, high=20.0 if index in {4, 5} else 12.0, low=8.0)
        for index in range(11)
    )
    assert detect_pivot_rejection_bands(bars, PivotRejectionConfig(5)) == ()
    with pytest.raises(ContractValidationError):
        PivotRejectionConfig(True)


def test_prefix_parity_preconfirmation_unavailability_and_zero_wick_suppression() -> (
    None
):
    bars = tuple(_bar(index, high=12.0, low=8.0) for index in range(11))
    bars = bars[:5] + (_bar(5, high=20.0, low=1.0, open_=10.0, close=15.0),) + bars[6:]
    config = PivotRejectionConfig(5)
    assert all(
        detect_pivot_rejection_bands(bars[:index], config) == () for index in range(11)
    )
    extended_bars = bars + tuple(
        _bar(index, high=12.0, low=8.0) for index in range(11, 16)
    )
    assert detect_pivot_rejection_bands(bars, config) == detect_pivot_rejection_bands(
        extended_bars, config
    )

    zero_wick = (
        bars[:5] + (_bar(5, high=15.0, low=1.0, open_=15.0, close=14.0),) + bars[6:]
    )
    assert [item.side for item in detect_pivot_rejection_bands(zero_wick, config)] == [
        ZoneSide.SUPPORT
    ]


def test_malformed_detector_inputs_fail_closed() -> None:
    bars = tuple(_bar(index, high=12.0, low=8.0) for index in range(11))
    with pytest.raises(ContractValidationError, match="tuple"):
        detect_pivot_rejection_bands(list(bars), PivotRejectionConfig(5))  # type: ignore[arg-type]
    duplicated = bars[:10] + (_bar(10, high=12.0, low=8.0),)
    duplicated = duplicated[:10] + (bars[0],)
    with pytest.raises(ContractValidationError, match="duplicate"):
        detect_pivot_rejection_bands(duplicated, PivotRejectionConfig(5))
