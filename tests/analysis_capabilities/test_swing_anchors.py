from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from libs.analysis_capabilities.execution import execute_analysis_capability
from libs.analysis_capabilities.ta.swing_anchors import (
    SwingAnchor,
    SwingAnchorBar,
    SwingAnchorRequest,
    SwingAnchorSnapshot,
    compute_swing_anchors,
)

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _bar(index: int, *, high: float, low: float) -> SwingAnchorBar:
    return SwingAnchorBar(
        closed_at=_START + timedelta(hours=index),
        high=high,
        low=low,
    )


def test_strict_extrema_emit_exact_prices_and_confirmation_times() -> None:
    bars = (
        _bar(0, high=10, low=5),
        _bar(1, high=20, low=8),
        _bar(2, high=12, low=6),
        _bar(3, high=11, low=1),
        _bar(4, high=13, low=7),
    )

    snapshot = compute_swing_anchors(SwingAnchorRequest(bars, span=1))

    assert snapshot.market_as_of == bars[-1].closed_at
    assert snapshot.anchors == (
        SwingAnchor("swing_high", bars[1].closed_at, bars[2].closed_at, 20.0),
        SwingAnchor("swing_low", bars[3].closed_at, bars[4].closed_at, 1.0),
    )


def test_ties_are_not_anchors_and_wide_bar_can_have_both_roles() -> None:
    tied = (
        _bar(0, high=10, low=5),
        _bar(1, high=20, low=5),
        _bar(2, high=20, low=6),
    )
    dual = (
        _bar(0, high=10, low=5),
        _bar(1, high=20, low=1),
        _bar(2, high=10, low=5),
    )

    assert compute_swing_anchors(SwingAnchorRequest(tied, span=1)).anchors == ()
    assert tuple(
        anchor.kind
        for anchor in compute_swing_anchors(SwingAnchorRequest(dual, span=1)).anchors
    ) == ("swing_high", "swing_low")


def test_insufficient_history_is_a_valid_empty_snapshot() -> None:
    bars = (_bar(0, high=10, low=5), _bar(1, high=11, low=4))
    snapshot = compute_swing_anchors(SwingAnchorRequest(bars, span=2))

    assert snapshot.span == 2
    assert snapshot.market_as_of == bars[-1].closed_at
    assert snapshot.anchors == ()


def test_dataclasses_and_request_validation_are_fail_closed() -> None:
    anchor = SwingAnchor("swing_high", _START, _START + timedelta(hours=1), 10)
    with pytest.raises(FrozenInstanceError):
        anchor.price = 11
    assert not hasattr(anchor, "__dict__")

    with pytest.raises(ValueError):
        SwingAnchor("swing_high", _START, _START, 10)
    with pytest.raises(TypeError):
        SwingAnchorRequest([_bar(0, high=10, low=5)], span=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        SwingAnchorRequest((_bar(0, high=10, low=5),), span=0)
    with pytest.raises(TypeError):
        SwingAnchorRequest((_bar(0, high=10, low=5),), span=True)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        SwingAnchorSnapshot(1, _START, [anchor])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="duplicate"):
        SwingAnchorSnapshot(1, _START + timedelta(hours=1), (anchor, anchor))


def test_dispatcher_matches_direct_provider() -> None:
    bars = (
        _bar(0, high=10, low=5),
        _bar(1, high=20, low=1),
        _bar(2, high=10, low=5),
    )
    request = SwingAnchorRequest(bars, span=1)

    assert execute_analysis_capability(
        "ta.swing_anchors", request
    ) == compute_swing_anchors(request)
