from collections import Counter

from libs.models.sr.research.studies.adaptive_context_calibration.contracts import (
    AdaptiveDisposition,
    NormalizationStatus,
)
from libs.models.sr.research.studies.adaptive_context_calibration.runner import compute_study


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
    assert sum(study.metrics["cohort_case_counts"].values()) == len(study.cases)
    assert Counter(f"{item.asset}/{item.timeframe}" for item in study.predictions)
