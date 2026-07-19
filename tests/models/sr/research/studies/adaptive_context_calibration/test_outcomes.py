from libs.models.sr.domain import ZoneSide
from libs.models.sr.research.studies.adaptive_context_calibration.contracts import NormalizationStatus
from libs.models.sr.research.studies.adaptive_context_calibration.outcomes import (
    build_candidate_cases,
    build_model_bars,
    build_swing_observations,
)
from libs.models.sr.research.studies.adaptive_context_calibration.normalization import (
    SaliencePoint,
    normalize_salience,
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
