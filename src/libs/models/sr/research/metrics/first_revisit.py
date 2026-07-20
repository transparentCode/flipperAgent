"""Pure, detector-neutral first-revisit band operations.

The functions deliberately accept only immutable domain values and explicit
window inputs.  They perform no study configuration, I/O, or artifact work.
"""

from __future__ import annotations

from datetime import datetime
import math

from libs.models.sr.domain import (
    CandidateLevel,
    ClosedBar,
    ContractValidationError,
    ZoneGeometry,
    ZoneSide,
)
from libs.models.sr.research.metrics.first_touch import FirstTouchOutcome


def intersects_band(bar: ClosedBar, candidate: CandidateLevel) -> bool:
    """Return inclusive OHLC intersection with a candidate band."""
    if type(bar) is not ClosedBar or type(candidate) is not CandidateLevel:
        raise ContractValidationError(
            "band intersection requires ClosedBar/CandidateLevel"
        )
    return (
        bar.high >= candidate.geometry.lower_bound
        and bar.low <= candidate.geometry.upper_bound
    )


def first_revisit_outcome(
    candidate: CandidateLevel,
    *,
    confirmation_index: int,
    fold_end: datetime,
    bars: tuple[ClosedBar, ...],
    first_touch_offset_bars: int,
    touch_search_bars: int,
    horizon_bars: int,
) -> FirstTouchOutcome | None:
    """Find a causal first revisit and compute its fixed reaction horizon.

    ``None`` represents no eligible first touch.  A present but incomplete
    horizon is represented by a right-censored ``FirstTouchOutcome``.
    """
    if (
        type(candidate) is not CandidateLevel
        or type(bars) is not tuple
        or any(type(bar) is not ClosedBar for bar in bars)
    ):
        raise ContractValidationError(
            "first revisit requires CandidateLevel and ClosedBar tuple"
        )
    if type(confirmation_index) is not int or not 0 <= confirmation_index < len(bars):
        raise ContractValidationError("first revisit confirmation index is invalid")
    if (
        type(first_touch_offset_bars) is not int
        or type(touch_search_bars) is not int
        or type(horizon_bars) is not int
        or min(first_touch_offset_bars, touch_search_bars, horizon_bars) < 1
    ):
        raise ContractValidationError(
            "first revisit window values must be positive integers"
        )
    start = confirmation_index + first_touch_offset_bars
    stop = min(start + touch_search_bars, len(bars))
    touch_index = next(
        (
            index
            for index in range(start, stop)
            if bars[index].closed_at < fold_end
            and intersects_band(bars[index], candidate)
        ),
        None,
    )
    if touch_index is None:
        return None
    touch = bars[touch_index]
    horizon = bars[
        touch_index + first_touch_offset_bars : touch_index
        + first_touch_offset_bars
        + horizon_bars
    ]
    if len(horizon) != horizon_bars or any(
        bar.closed_at >= fold_end for bar in horizon
    ):
        return FirstTouchOutcome(
            zone_id=candidate.candidate_id,
            side=candidate.side,
            first_touch_at=touch.closed_at,
            touch_bar_id=touch.bar_id,
            anchor_close=touch.close,
            reference_atr_14=touch.atr_at_close,
            completed=False,
            right_censored=True,
            tenth_outcome_bar_closed_at=None,
            favorable_reference_atr=None,
            adverse_reference_atr=None,
            quality_reference_atr=None,
            invalidated=False,
        )
    if candidate.side is ZoneSide.SUPPORT:
        favorable_raw = max(max(bar.high for bar in horizon) - touch.close, 0.0)
        adverse_raw = max(touch.close - min(bar.low for bar in horizon), 0.0)
    else:
        favorable_raw = max(touch.close - min(bar.low for bar in horizon), 0.0)
        adverse_raw = max(max(bar.high for bar in horizon) - touch.close, 0.0)
    favorable, adverse = (
        favorable_raw / touch.atr_at_close,
        adverse_raw / touch.atr_at_close,
    )
    quality = favorable - adverse
    if not all(math.isfinite(value) for value in (favorable, adverse, quality)):
        raise ContractValidationError("first revisit outcome metrics must be finite")
    return FirstTouchOutcome(
        zone_id=candidate.candidate_id,
        side=candidate.side,
        first_touch_at=touch.closed_at,
        touch_bar_id=touch.bar_id,
        anchor_close=touch.close,
        reference_atr_14=touch.atr_at_close,
        completed=True,
        right_censored=False,
        tenth_outcome_bar_closed_at=horizon[-1].closed_at,
        favorable_reference_atr=favorable,
        adverse_reference_atr=adverse,
        quality_reference_atr=quality,
        invalidated=False,
    )


def prior_close_control_candidate(
    candidate: CandidateLevel,
    *,
    prior_bar: ClosedBar,
    side: ZoneSide,
    source: str,
) -> CandidateLevel:
    """Construct a same-width prior-close band from confirmation-time data."""
    if (
        type(candidate) is not CandidateLevel
        or type(prior_bar) is not ClosedBar
        or type(side) is not ZoneSide
    ):
        raise ContractValidationError(
            "prior-close control requires typed candidate/bar/side"
        )
    if prior_bar.state_key != candidate.state_key:
        raise ContractValidationError(
            "prior-close control state key does not match real candidate"
        )
    if type(source) is not str or not source:
        raise ContractValidationError("prior-close control source must be non-empty")
    return CandidateLevel(
        state_key=candidate.state_key,
        side=side,
        geometry=ZoneGeometry(
            center=prior_bar.close, half_width=candidate.geometry.half_width
        ),
        source=source,
        formed_at=prior_bar.closed_at,
        available_at=candidate.available_at,
        atr_at_creation=candidate.atr_at_creation,
    )


__all__ = ["first_revisit_outcome", "intersects_band", "prior_close_control_candidate"]
