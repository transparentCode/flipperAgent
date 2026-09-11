from datetime import UTC, datetime, timedelta

import pytest

from libs.analysis_capabilities.ta.swing_anchors import (
    SwingAnchorBar,
    SwingAnchorRequest,
    compute_swing_anchors,
)

_START = datetime(2026, 2, 1, tzinfo=UTC)


def _bars() -> tuple[SwingAnchorBar, ...]:
    values = (
        (12.0, 10.0),
        (13.0, 9.0),
        (20.0, 15.0),
        (14.0, 8.0),
        (15.0, 7.0),
        (11.0, 11.0),
        (18.0, 12.0),
        (10.0, 9.0),
        (16.0, 13.0),
    )
    return tuple(
        SwingAnchorBar(
            closed_at=_START + timedelta(hours=index),
            high=high,
            low=low,
        )
        for index, (high, low) in enumerate(values)
    )


def test_anchor_is_invisible_until_the_right_confirmation_bar_closes() -> None:
    bars = _bars()
    span = 2
    full = compute_swing_anchors(SwingAnchorRequest(bars, span))
    target = next(
        anchor for anchor in full.anchors if anchor.formed_at == bars[2].closed_at
    )

    before_confirmation = compute_swing_anchors(SwingAnchorRequest(bars[:4], span))
    at_confirmation = compute_swing_anchors(SwingAnchorRequest(bars[:5], span))

    assert target.available_at == bars[4].closed_at
    assert target not in before_confirmation.anchors
    assert target in at_confirmation.anchors


@pytest.mark.parametrize("cutoff", tuple(range(1, 10)))
def test_prefix_invariance_across_all_confirmation_boundaries(cutoff: int) -> None:
    bars = _bars()
    span = 2
    full = compute_swing_anchors(SwingAnchorRequest(bars, span))
    prefix = compute_swing_anchors(SwingAnchorRequest(bars[:cutoff], span))
    expected = tuple(
        anchor for anchor in full.anchors if anchor.available_at <= prefix.market_as_of
    )

    assert prefix.anchors == expected


def test_future_extension_and_post_availability_mutation_cannot_rewrite_anchor() -> (
    None
):
    bars = _bars()
    span = 2
    base = compute_swing_anchors(SwingAnchorRequest(bars[:6], span))
    extended = compute_swing_anchors(SwingAnchorRequest(bars, span))
    base_anchor = next(
        anchor for anchor in base.anchors if anchor.formed_at == bars[2].closed_at
    )
    extended_anchor = next(
        anchor for anchor in extended.anchors if anchor.formed_at == bars[2].closed_at
    )

    changed = list(bars)
    changed[5] = SwingAnchorBar(
        closed_at=bars[5].closed_at,
        high=1000.0,
        low=0.5,
    )
    changed_after_availability = compute_swing_anchors(
        SwingAnchorRequest(tuple(changed), span)
    )
    changed_anchor = next(
        anchor
        for anchor in changed_after_availability.anchors
        if anchor.formed_at == bars[2].closed_at
    )

    assert base_anchor == extended_anchor == changed_anchor


def test_non_increasing_timestamps_are_not_repaired() -> None:
    bars = _bars()
    invalid = list(bars)
    invalid[3] = SwingAnchorBar(
        closed_at=bars[2].closed_at,
        high=bars[3].high,
        low=bars[3].low,
    )

    with pytest.raises(ValueError, match="strictly increasing"):
        SwingAnchorRequest(tuple(invalid), span=2)
