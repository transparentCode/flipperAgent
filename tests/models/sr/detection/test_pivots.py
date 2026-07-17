from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from libs.models.sr import (
    ClosedBar,
    ContractValidationError,
    DetectionConfig,
    SRStateKey,
    ZoneSide,
)
from libs.models.sr.detection import detect_confirmed_pivots


_T0 = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def _key(symbol: str = "BTCUSDT") -> SRStateKey:
    return SRStateKey(venue="binance", symbol=symbol, timeframe="1h")


def _config(*, span: int = 1, width: float = 0.25) -> DetectionConfig:
    return DetectionConfig(pivot_span_bars=span, zone_half_width_atr=width)


def _bar(
    index: int,
    *,
    high: float = 105.0,
    low: float = 95.0,
    atr: float = 1.0,
    state_key: SRStateKey | None = None,
    bar_id: str | None = None,
    closed_at: datetime | None = None,
) -> ClosedBar:
    return ClosedBar(
        state_key=state_key or _key(),
        bar_id=bar_id or f"bar-{index}",
        closed_at=closed_at or _T0 + timedelta(minutes=index),
        open=(high + low) / 2,
        high=high,
        low=low,
        close=(high + low) / 2,
        atr_at_close=atr,
    )


def _both_side_window(*, confirmation_atr: float = 1.0) -> tuple[ClosedBar, ...]:
    return (
        _bar(0, high=100.0, low=95.0),
        _bar(1, high=110.0, low=90.0),
        _bar(2, high=101.0, low=94.0, atr=confirmation_atr),
    )


def test_no_candidate_before_full_causal_window() -> None:
    assert detect_confirmed_pivots((_bar(0), _bar(1)), _config()) == ()


def test_unique_center_extremum_emits_both_sides_after_confirmation() -> None:
    bars = _both_side_window(confirmation_atr=2.0)

    candidates = detect_confirmed_pivots(bars, _config())

    assert {candidate.side for candidate in candidates} == {
        ZoneSide.SUPPORT,
        ZoneSide.RESISTANCE,
    }
    by_side = {candidate.side: candidate for candidate in candidates}
    assert by_side[ZoneSide.SUPPORT].geometry.center == 90.0
    assert by_side[ZoneSide.RESISTANCE].geometry.center == 110.0
    assert all(candidate.formed_at == bars[1].closed_at for candidate in candidates)
    assert all(
        candidate.available_at == bars[2].closed_at for candidate in candidates
    )
    assert all(candidate.atr_at_creation == 2.0 for candidate in candidates)
    assert all(candidate.geometry.half_width == 0.5 for candidate in candidates)


@pytest.mark.parametrize(
    "highs, lows, expected_sides",
    [
        ((100.0, 110.0, 110.0), (95.0, 90.0, 94.0), {ZoneSide.SUPPORT}),
        ((100.0, 110.0, 101.0), (95.0, 90.0, 90.0), {ZoneSide.RESISTANCE}),
    ],
)
def test_tied_extrema_reject_only_tied_pivot(
    highs: tuple[float, float, float],
    lows: tuple[float, float, float],
    expected_sides: set[ZoneSide],
) -> None:
    bars = tuple(_bar(index, high=highs[index], low=lows[index]) for index in range(3))

    candidates = detect_confirmed_pivots(bars, _config())

    assert {candidate.side for candidate in candidates} == expected_sides


def test_line_geometry_uses_zero_width_multiplier() -> None:
    candidates = detect_confirmed_pivots(
        _both_side_window(),
        _config(width=0.0),
    )

    assert candidates
    assert all(candidate.geometry.half_width == 0.0 for candidate in candidates)


def test_confirmation_bar_owns_atr_and_width() -> None:
    bars = _both_side_window(confirmation_atr=3.5)

    candidates = detect_confirmed_pivots(bars, _config(width=0.5))

    assert all(candidate.atr_at_creation == 3.5 for candidate in candidates)
    assert all(candidate.geometry.half_width == 1.75 for candidate in candidates)


def test_detector_uses_final_window_and_returns_stable_order() -> None:
    prefix = (_bar(0, high=90.0, low=80.0),)
    bars = prefix + _both_side_window()

    first = detect_confirmed_pivots(bars, _config())
    second = detect_confirmed_pivots(bars, _config())

    assert first == second
    assert [
        (candidate.formed_at, candidate.available_at, candidate.candidate_id)
        for candidate in first
    ] == sorted(
        (candidate.formed_at, candidate.available_at, candidate.candidate_id)
        for candidate in first
    )


@pytest.mark.parametrize(
    "bars, expected",
    [
        (
            (
                _bar(0),
                _bar(1, state_key=_key("ETHUSDT")),
                _bar(2),
            ),
            "state_key",
        ),
        (
            (_bar(0), _bar(1), _bar(1, bar_id="bar-1")),
            "duplicate bar_id",
        ),
        (
            (
                _bar(0),
                _bar(
                    1,
                    closed_at=_T0,
                ),
                _bar(2),
            ),
            "strictly increasing",
        ),
    ],
)
def test_invalid_window_metadata_fails_closed(
    bars: tuple[ClosedBar, ...], expected: str
) -> None:
    with pytest.raises(ContractValidationError, match=expected):
        detect_confirmed_pivots(bars, _config())


def test_detector_rejects_wrong_container_and_item_type() -> None:
    with pytest.raises(ContractValidationError, match="exactly a tuple"):
        detect_confirmed_pivots(list(_both_side_window()), _config())  # type: ignore[arg-type]
    with pytest.raises(ContractValidationError, match="exactly ClosedBar"):
        detect_confirmed_pivots((object(),), _config())  # type: ignore[arg-type]


def test_width_product_overflow_fails_closed() -> None:
    with pytest.raises(ContractValidationError, match="zone half_width"):
        detect_confirmed_pivots(
            _both_side_window(confirmation_atr=2.0),
            _config(width=1e308),
        )


def test_final_geometry_bound_overflow_fails_closed() -> None:
    bars = (
        _bar(0, high=2.0, low=1.0),
        _bar(1, high=1e308, low=1.0),
        _bar(2, high=2.0, low=1.0, atr=1e308),
    )

    with pytest.raises(ContractValidationError, match="candidate upper_bound"):
        detect_confirmed_pivots(bars, _config(width=1.0))


def test_detector_does_not_mutate_input_bars() -> None:
    bars = _both_side_window()
    before = tuple(bars)

    detect_confirmed_pivots(bars, _config())

    assert bars == before
