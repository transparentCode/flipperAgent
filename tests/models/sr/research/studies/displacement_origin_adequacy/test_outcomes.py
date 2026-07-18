from __future__ import annotations

from datetime import datetime, timedelta, timezone

from libs.models.sr.domain import ClosedBar, SRStateKey
from libs.models.sr.research.studies.displacement_origin_adequacy.config import (
    load_displacement_origin_adequacy_config,
)
from libs.models.sr.research.studies.displacement_origin_adequacy.contracts import (
    OutcomeStatus,
)
from libs.models.sr.research.studies.displacement_origin_adequacy.outcomes import (
    build_matched_controls,
    evaluate_candidates,
)


_CONFIG = "configs/sr_trials/sr_v2_0_taousdt_1d_displacement_origin_adequacy.yaml"
_T0 = datetime(2024, 7, 1, tzinfo=timezone.utc)


def _bar(
    index: int,
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
) -> ClosedBar:
    return ClosedBar(
        state_key=SRStateKey("binance_usdm", "TAOUSDT", "1d"),
        bar_id=f"bar-{index}",
        closed_at=_T0 + timedelta(days=index),
        open=open_price,
        high=high,
        low=low,
        close=close,
        atr_at_close=1.0,
    )


def _completed_touch_bars() -> tuple[ClosedBar, ...]:
    bars = [
        _bar(0, open_price=100, high=103, low=99, close=101),
        _bar(1, open_price=102, high=104, low=100, close=101),
        _bar(2, open_price=100, high=102, low=98, close=99),
        _bar(3, open_price=99, high=101, low=97, close=100),
        _bar(4, open_price=101, high=102, low=98, close=100),
        _bar(5, open_price=100, high=107, low=99, close=106),
        _bar(6, open_price=106, high=108, low=100, close=107),
    ]
    bars.extend(
        _bar(index, open_price=107, high=109 + index, low=106, close=108)
        for index in range(7, 17)
    )
    return tuple(bars)


def test_first_touch_starts_after_availability_and_builds_two_matched_controls() -> None:
    config = load_displacement_origin_adequacy_config(_CONFIG)
    bars = _completed_touch_bars()

    cases = evaluate_candidates(bars, config=config)

    assert len(cases) == 1
    case = cases[0]
    assert case.status is OutcomeStatus.COMPLETED
    assert case.outcome is not None
    assert case.outcome.touch_bar_id == "bar-6"
    assert case.outcome.tenth_outcome_bar_closed_at == bars[16].closed_at
    controls = build_matched_controls(cases, bars, config=config)
    assert len(controls) == 2
    assert {item.outcome.side.value for item in controls} == {"SUPPORT", "RESISTANCE"}
    assert all(item.outcome.anchor_at == case.outcome.first_touch_at for item in controls)
    assert all(item.zone_width_atr == case.zone_width_atr for item in controls)


def test_no_intersection_before_expiry_is_explicitly_accounted() -> None:
    config = load_displacement_origin_adequacy_config(_CONFIG)
    bars = list(_completed_touch_bars())
    for index in range(6, len(bars)):
        bars[index] = _bar(index, open_price=110, high=112, low=109, close=111)

    cases = evaluate_candidates(tuple(bars), config=config)

    assert len(cases) == 1
    assert cases[0].status is OutcomeStatus.NO_TOUCH
    assert cases[0].outcome is None


def test_touch_at_the_fifty_first_search_bar_is_excluded() -> None:
    config = load_displacement_origin_adequacy_config(_CONFIG)
    bars = list(_completed_touch_bars())
    for index in range(6, len(bars)):
        bars[index] = _bar(index, open_price=110, high=112, low=109, close=111)
    bars.extend(
        _bar(index, open_price=110, high=112, low=109, close=111)
        for index in range(len(bars), 56)
    )
    # The search includes bars 6 through 55.  This touching doji is bar 56,
    # immediately after the configured 50-bar search window.
    bars.append(_bar(56, open_price=101, high=112, low=100, close=101))

    cases = evaluate_candidates(tuple(bars), config=config)

    assert len(cases) == 1
    assert cases[0].confirmation_bar_id == "bar-5"
    assert cases[0].status is OutcomeStatus.NO_TOUCH
    assert cases[0].outcome is None


def test_horizon_ending_at_or_after_fold_end_is_right_censored() -> None:
    config = load_displacement_origin_adequacy_config(_CONFIG)
    bars = list(_completed_touch_bars())
    start = datetime(2024, 9, 20, tzinfo=timezone.utc)
    for index, bar in enumerate(bars):
        object.__setattr__(bar, "closed_at", start + timedelta(days=index))

    cases = evaluate_candidates(tuple(bars), config=config)

    assert len(cases) == 1
    assert cases[0].status is OutcomeStatus.RIGHT_CENSORED
    assert cases[0].outcome is not None
    assert cases[0].outcome.right_censored
