from datetime import datetime, timedelta, timezone

from libs.models.sr.domain import (
    CandidateLevel,
    ClosedBar,
    SRStateKey,
    ZoneGeometry,
    ZoneSide,
)
from libs.models.sr.research.metrics.first_revisit import first_revisit_outcome
from libs.models.sr.research.studies.adaptive_context_calibration.contracts import (
    NormalizationStatus,
)
from libs.models.sr.research.studies.adaptive_context_calibration.normalization import (
    SaliencePoint,
    normalize_salience,
)
from libs.models.sr.research.studies.adaptive_context_calibration.outcomes import (
    build_candidate_cases,
    build_model_bars,
    build_swing_observations,
)


def _bar(index: int, *, touches: bool = False) -> ClosedBar:
    price = 10.0 if touches else 12.5
    return ClosedBar(
        SRStateKey("venue", "asset", "12h"),
        f"bar-{index}",
        datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(hours=12 * (index + 1)),
        price,
        10.5 if touches else 13.0,
        9.5 if touches else 12.0,
        price,
        1.0,
    )


def _candidate(bars: tuple[ClosedBar, ...]) -> CandidateLevel:
    return CandidateLevel(
        state_key=bars[0].state_key,
        side=ZoneSide.SUPPORT,
        geometry=ZoneGeometry(center=10.0, half_width=0.5),
        source="test",
        formed_at=bars[0].closed_at,
        available_at=bars[0].closed_at,
        atr_at_creation=1.0,
    )


def test_cases_have_exact_two_matched_controls_and_causal_labels(config, synthetic_source_bundle) -> None:
    member = next(item for item in synthetic_source_bundle.assets if (item.asset, item.timeframe) == ("TAOUSDT", "12h"))
    bars = build_model_bars(member, config=config)
    observations, _ = build_swing_observations(member, bars)
    points = tuple(
        SaliencePoint(member.asset, member.timeframe, bars[item.confirmation_index].closed_at, item.raw_salience_atr)
        for item in observations
    )
    normalized = {
        (member.asset, member.timeframe, observation.confirmation_bar_id): normalize_salience(
            point,
            points[:index],
        )
        for index, (observation, point) in enumerate(zip(observations, points))
    }
    cases = build_candidate_cases(member, bars, observations, config=config, normalized=normalized)
    assert cases
    for case in cases:
        assert tuple(control.side for control in case.controls) == (ZoneSide.SUPPORT, ZoneSide.RESISTANCE)
        assert all(control.zone_width_atr == case.zone_width_atr for control in case.controls)
        assert all(control.candidate.available_at == case.candidate.available_at for control in case.controls)
        if case.label is not None:
            assert case.label_available_at > case.candidate.available_at
    assert all(case.normalization_status in set(NormalizationStatus) for case in cases)


def test_touch_search_and_fold_end_boundaries_are_half_open() -> None:
    bars = tuple(_bar(index, touches=index == 50) for index in range(62))
    outcome = first_revisit_outcome(
        _candidate(bars),
        confirmation_index=0,
        fold_end=bars[-1].closed_at + timedelta(hours=12),
        bars=bars,
        first_touch_offset_bars=1,
        touch_search_bars=50,
        horizon_bars=10,
    )
    assert outcome is not None and outcome.completed and outcome.touch_bar_id == "bar-50"

    after_window = tuple(_bar(index, touches=index == 51) for index in range(62))
    assert first_revisit_outcome(
        _candidate(after_window),
        confirmation_index=0,
        fold_end=after_window[-1].closed_at + timedelta(hours=12),
        bars=after_window,
        first_touch_offset_bars=1,
        touch_search_bars=50,
        horizon_bars=10,
    ) is None

    boundary = tuple(_bar(index, touches=index == 1) for index in range(13))
    censored = first_revisit_outcome(
        _candidate(boundary),
        confirmation_index=0,
        fold_end=boundary[11].closed_at,
        bars=boundary,
        first_touch_offset_bars=1,
        touch_search_bars=50,
        horizon_bars=10,
    )
    assert censored is not None and censored.right_censored
