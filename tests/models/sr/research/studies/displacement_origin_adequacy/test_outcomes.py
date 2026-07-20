from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from libs.models.sr.domain import CandidateLevel, ClosedBar, SRStateKey, ZoneGeometry, ZoneSide
from libs.models.sr.research.studies.displacement_origin_adequacy.config import (
    load_displacement_origin_adequacy_config,
)
from libs.models.sr.research.studies.displacement_origin_adequacy.contracts import (
    CandidateCase,
    OutcomeStatus,
)
from libs.models.sr.research.studies.displacement_origin_adequacy.outcomes import (
    build_naive_controls,
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


def test_first_touch_starts_after_availability_and_builds_two_independent_naive_controls() -> None:
    config = load_displacement_origin_adequacy_config(_CONFIG)
    bars = _completed_touch_bars()

    cases = evaluate_candidates(bars, config=config)

    assert len(cases) == 1
    case = cases[0]
    assert case.status is OutcomeStatus.COMPLETED
    assert case.outcome is not None
    assert case.outcome.touch_bar_id == "bar-6"
    assert case.outcome.tenth_outcome_bar_closed_at == bars[16].closed_at
    controls = build_naive_controls(cases, bars, config=config)
    assert len(controls) == 2
    assert {item.candidate.side.value for item in controls} == {"SUPPORT", "RESISTANCE"}
    assert all(item.candidate.geometry.center == bars[4].close for item in controls)
    assert all(item.candidate.geometry.half_width == case.candidate.geometry.half_width for item in controls)
    assert all(item.zone_width_atr == case.zone_width_atr for item in controls)
    assert all(item.candidate.available_at == case.candidate.available_at for item in controls)


def test_real_and_same_side_naive_band_can_touch_on_different_bars() -> None:
    config = load_displacement_origin_adequacy_config(_CONFIG)
    bars = list(_completed_touch_bars())
    # Nearest opposing base moves to bar 2 (98-102); prior close is 104, so
    # same-width naïve support is 102-106.
    bars[3] = _bar(3, open_price=99, high=101, low=97, close=100)
    bars[4] = _bar(4, open_price=100, high=105, low=100, close=104)
    bars[6] = _bar(6, open_price=104, high=106, low=104, close=105)
    bars[7] = _bar(7, open_price=100, high=101, low=99, close=100)
    bars.append(_bar(17, open_price=108, high=110, low=106, close=109))

    cases = evaluate_candidates(tuple(bars), config=config)
    controls = build_naive_controls(cases, tuple(bars), config=config)

    assert len(cases) == 1
    assert cases[0].outcome is not None
    same_side = next(item for item in controls if item.candidate.side is cases[0].candidate.side)
    assert same_side.outcome is not None
    assert cases[0].outcome.touch_bar_id == "bar-7"
    assert same_side.outcome.touch_bar_id == "bar-6"


def test_no_intersection_before_expiry_is_explicitly_accounted() -> None:
    config = load_displacement_origin_adequacy_config(_CONFIG)
    bars = list(_completed_touch_bars())
    for index in range(6, len(bars)):
        bars[index] = _bar(index, open_price=110, high=112, low=109, close=111)

    cases = evaluate_candidates(tuple(bars), config=config)

    assert len(cases) == 1
    assert cases[0].status is OutcomeStatus.NO_TOUCH
    assert cases[0].outcome is None
    controls = build_naive_controls(cases, tuple(bars), config=config)
    assert len(controls) == 2


def test_controls_bind_causal_confirmation_identity_not_future_real_outcome() -> None:
    config = load_displacement_origin_adequacy_config(_CONFIG)
    bars = _completed_touch_bars()
    completed_case = evaluate_candidates(bars, config=config)[0]
    no_touch_case = replace(completed_case, status=OutcomeStatus.NO_TOUCH, outcome=None)

    completed_controls = build_naive_controls((completed_case,), bars, config=config)
    no_touch_controls = build_naive_controls((no_touch_case,), bars, config=config)

    assert completed_case.case_id != no_touch_case.case_id
    assert completed_case.confirmation_id == no_touch_case.confirmation_id
    assert completed_controls == no_touch_controls
    assert tuple(item.control_id for item in completed_controls) == tuple(
        item.control_id for item in no_touch_controls
    )
    assert all(
        control.real_confirmation_id == completed_case.confirmation_id
        for control in completed_controls
    )


def test_changing_real_width_changes_naive_bounds_and_touch_result() -> None:
    config = load_displacement_origin_adequacy_config(_CONFIG)
    bars = tuple(
        _bar(index, open_price=101.75, high=102.0, low=101.5, close=101.8)
        for index in range(17)
    )
    bars = (
        bars[:4]
        + (_bar(4, open_price=100.0, high=101.0, low=99.0, close=100.0),)
        + (_bar(5, open_price=100.0, high=101.0, low=99.0, close=100.0),)
        + bars[6:]
    )

    def case(half_width: float) -> CandidateCase:
        candidate = CandidateLevel(
            state_key=SRStateKey("binance_usdm", "TAOUSDT", "1d"),
            side=ZoneSide.SUPPORT,
            geometry=ZoneGeometry(center=200.0, half_width=half_width),
            source="displacement_origin_v2",
            formed_at=bars[4].closed_at,
            available_at=bars[5].closed_at,
            atr_at_creation=1.0,
        )
        return CandidateCase(
            candidate=candidate,
            confirmation_bar_id=bars[5].bar_id,
            confirmation_index=5,
            base_distance_bars=1,
            fold="2024_q3",
            status=OutcomeStatus.NO_TOUCH,
            outcome=None,
            zone_width_atr=2.0 * half_width,
        )

    wide_case, narrow_case = case(2.0), case(0.25)
    wide_control = next(
        item
        for item in build_naive_controls((wide_case,), bars, config=config)
        if item.candidate.side is ZoneSide.SUPPORT
    )
    narrow_control = next(
        item
        for item in build_naive_controls((narrow_case,), bars, config=config)
        if item.candidate.side is ZoneSide.SUPPORT
    )

    assert (wide_control.candidate.geometry.lower_bound, wide_control.candidate.geometry.upper_bound) == (98.0, 102.0)
    assert (narrow_control.candidate.geometry.lower_bound, narrow_control.candidate.geometry.upper_bound) == (99.75, 100.25)
    assert wide_control.status is OutcomeStatus.COMPLETED
    assert narrow_control.status is OutcomeStatus.NO_TOUCH


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
