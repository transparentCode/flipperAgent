from collections import Counter
from pathlib import Path

from libs.models.sr.research.studies.adaptive_context_calibration.contracts import (
    AdaptiveDisposition,
    CaseMembership,
    NormalizationStatus,
)
from libs.models.sr.research.studies.adaptive_context_calibration.outcomes import (
    build_model_bars,
    build_swing_observations,
)
from libs.models.sr.research.studies.adaptive_context_calibration.runner import (
    compute_study,
)
from libs.models.sr.research.studies.adaptive_context_calibration.source import (
    load_v23_source_bundle,
)


def test_full_offline_replay_has_same_cases_for_adaptive_and_null(config, synthetic_source_bundle) -> None:
    study = compute_study(
        config,
        source_bundle=synthetic_source_bundle,
        implementation_commit="60331170abbbb5e538a4a67fa3a970a137160758",
    )
    assert study.cases
    assert study.predictions
    assert study.metrics["adaptive_null_case_ids_identical"] is True
    assert study.metrics["fixed_v2_2_detector_candidate_counts"]["affects_v2_3_disposition"] is False
    assert study.disposition in set(AdaptiveDisposition)
    case_map = {case.case_id: case for case in study.cases}
    assert all(case_map[item.case_id].normalization_status is NormalizationStatus.READY for item in study.predictions)
    assert all(case_map[item.case_id].membership is CaseMembership.IN_FOLD for item in study.predictions)
    assert sum(study.metrics["cohort_case_counts"].values()) == len(study.cases)
    assert Counter(f"{item.asset}/{item.timeframe}" for item in study.predictions)


def test_history_only_cases_seed_first_2025_prediction_without_scoring(config, synthetic_source_bundle) -> None:
    study = compute_study(
        config,
        source_bundle=synthetic_source_bundle,
        implementation_commit="60331170abbbb5e538a4a67fa3a970a137160758",
    )
    history = tuple(item for item in study.cases if item.membership is CaseMembership.HISTORY_ONLY)
    assert history
    assert all(item.fold == "HISTORY_ONLY" for item in history)
    prediction_case_ids = {item.case_id for item in study.predictions}
    assert prediction_case_ids.isdisjoint(item.case_id for item in history)

    first = min(study.predictions, key=lambda item: item.prediction_at)
    eligible = tuple(
        item
        for item in study.cases
        if item.normalization_status is NormalizationStatus.READY
        and item.label in (0, 1)
        and item.label_available_at is not None
        and item.label_available_at < first.prediction_at
    )
    expected_successes = sum(item.label == 1 for item in eligible)
    assert first.null.successes == expected_successes
    assert first.null.failures == len(eligible) - expected_successes
    assert any(item.membership is CaseMembership.HISTORY_ONLY for item in eligible)


def test_complete_frozen_source_prefix_replay_is_exact(config) -> None:
    source = load_v23_source_bundle(
        Path(
            "research/tmp_sr_v2_3/source/"
            "041618553c8ce85cfcbc81e6415e2cccf3711e73f66bcd3651b526124a5b473e"
        )
    )
    for member in source.assets:
        bars = build_model_bars(member, config=config)
        full, _ = build_swing_observations(member, bars)
        for stop in range(1, len(bars) + 1):
            prefix, _ = build_swing_observations(member, bars[:stop])
            assert prefix == full[: len(prefix)]
