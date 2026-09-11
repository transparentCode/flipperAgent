from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from libs.analysis_capabilities.ta.fibonacci_trend_extension_geometry import (
    FibonacciTrendExtensionRequest,
    compute_fibonacci_trend_extension,
)
from libs.analysis_capabilities.ta.swing_anchors import SwingAnchor

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _up_request(
    *, ratios: tuple[float, ...] = (1.0, 1.5)
) -> FibonacciTrendExtensionRequest:
    return FibonacciTrendExtensionRequest(
        start_anchor=SwingAnchor(
            "swing_low", _START, _START + timedelta(hours=1), 100.0
        ),
        impulse_end_anchor=SwingAnchor(
            "swing_high",
            _START + timedelta(hours=2),
            _START + timedelta(hours=3),
            160.0,
        ),
        retracement_anchor=SwingAnchor(
            "swing_low",
            _START + timedelta(hours=4),
            _START + timedelta(hours=5),
            130.0,
        ),
        market_as_of=_START + timedelta(hours=5),
        extension_ratios=ratios,
    )


def test_three_point_extension_uses_signed_impulse_from_explicit_anchors() -> None:
    result = compute_fibonacci_trend_extension(_up_request())

    assert result.direction == "up"
    assert result.extension_levels == result.levels
    assert tuple(level.ratio for level in result.levels) == (1.0, 1.5)
    assert tuple(level.price for level in result.levels) == (190.0, 220.0)


def test_downward_extension_preserves_signed_impulse() -> None:
    request = FibonacciTrendExtensionRequest(
        start_anchor=SwingAnchor(
            "swing_high", _START, _START + timedelta(hours=1), 200.0
        ),
        impulse_end_anchor=SwingAnchor(
            "swing_low",
            _START + timedelta(hours=2),
            _START + timedelta(hours=3),
            140.0,
        ),
        retracement_anchor=SwingAnchor(
            "swing_high",
            _START + timedelta(hours=4),
            _START + timedelta(hours=5),
            170.0,
        ),
        market_as_of=_START + timedelta(hours=5),
        extension_ratios=(1.0, 1.5),
    )

    result = compute_fibonacci_trend_extension(request)

    assert result.direction == "down"
    assert tuple(level.price for level in result.levels) == (110.0, 80.0)


@pytest.mark.parametrize(
    "ratios",
    (
        (0.0,),
        (1.0, 1.0),
        (1.5, 1.0),
        (float("inf"),),
    ),
)
def test_ratios_are_explicit_positive_finite_and_strictly_ordered(
    ratios: tuple[float, ...],
) -> None:
    with pytest.raises((ValueError, TypeError)):
        _up_request(ratios=ratios)


def test_empty_explicit_ratio_tuple_does_not_invent_levels() -> None:
    result = compute_fibonacci_trend_extension(_up_request(ratios=()))

    assert result.levels == ()


def test_anchor_order_and_kinds_are_authenticated() -> None:
    with pytest.raises(ValueError, match="strictly ordered"):
        FibonacciTrendExtensionRequest(
            start_anchor=SwingAnchor(
                "swing_low",
                _START + timedelta(hours=2),
                _START + timedelta(hours=3),
                100.0,
            ),
            impulse_end_anchor=SwingAnchor(
                "swing_high", _START, _START + timedelta(hours=1), 160.0
            ),
            retracement_anchor=SwingAnchor(
                "swing_low",
                _START + timedelta(hours=4),
                _START + timedelta(hours=5),
                130.0,
            ),
            market_as_of=_START + timedelta(hours=5),
            extension_ratios=(1.0,),
        )

    with pytest.raises(ValueError, match="opposite kinds"):
        FibonacciTrendExtensionRequest(
            start_anchor=SwingAnchor(
                "swing_low", _START, _START + timedelta(hours=1), 100.0
            ),
            impulse_end_anchor=SwingAnchor(
                "swing_low",
                _START + timedelta(hours=2),
                _START + timedelta(hours=3),
                160.0,
            ),
            retracement_anchor=SwingAnchor(
                "swing_low",
                _START + timedelta(hours=4),
                _START + timedelta(hours=5),
                130.0,
            ),
            market_as_of=_START + timedelta(hours=5),
            extension_ratios=(1.0,),
        )


def test_anchor_availability_must_not_follow_the_cutoff() -> None:
    request = _up_request()
    with pytest.raises(ValueError, match="available"):
        FibonacciTrendExtensionRequest(
            start_anchor=request.start_anchor,
            impulse_end_anchor=request.impulse_end_anchor,
            retracement_anchor=SwingAnchor(
                "swing_low",
                _START + timedelta(hours=4),
                _START + timedelta(hours=6),
                130.0,
            ),
            market_as_of=_START + timedelta(hours=5),
            extension_ratios=(1.0,),
        )


def test_low_to_high_kind_topology_cannot_hide_a_downward_impulse() -> None:
    with pytest.raises(ValueError, match="up impulse"):
        compute_fibonacci_trend_extension(
            replace(
                _up_request(),
                start_anchor=SwingAnchor(
                    "swing_low", _START, _START + timedelta(hours=1), 200.0
                ),
                impulse_end_anchor=SwingAnchor(
                    "swing_high",
                    _START + timedelta(hours=2),
                    _START + timedelta(hours=3),
                    150.0,
                ),
            )
        )


def test_high_to_low_kind_topology_cannot_hide_an_upward_impulse() -> None:
    with pytest.raises(ValueError, match="down impulse"):
        compute_fibonacci_trend_extension(
            FibonacciTrendExtensionRequest(
                start_anchor=SwingAnchor(
                    "swing_high", _START, _START + timedelta(hours=1), 100.0
                ),
                impulse_end_anchor=SwingAnchor(
                    "swing_low",
                    _START + timedelta(hours=2),
                    _START + timedelta(hours=3),
                    150.0,
                ),
                retracement_anchor=SwingAnchor(
                    "swing_high",
                    _START + timedelta(hours=4),
                    _START + timedelta(hours=5),
                    120.0,
                ),
                market_as_of=_START + timedelta(hours=5),
                extension_ratios=(1.0,),
            )
        )


def test_snapshot_replace_rechecks_price_direction() -> None:
    result = compute_fibonacci_trend_extension(_up_request())
    with pytest.raises(ValueError, match="up impulse"):
        replace(
            result,
            start_anchor=SwingAnchor(
                "swing_low", _START, _START + timedelta(hours=1), 200.0
            ),
            impulse_end_anchor=SwingAnchor(
                "swing_high",
                _START + timedelta(hours=2),
                _START + timedelta(hours=3),
                150.0,
            ),
        )
