from statistics import median

from libs.models.sr.research.studies.adaptive_context_calibration.contracts import (
    AdaptiveDisposition,
)
from libs.models.sr.research.studies.adaptive_context_calibration.metrics import (
    _sample_cell_replicas,
    bootstrap_summary,
    disposition,
)
from libs.models.sr.research.studies.adaptive_context_calibration.runner import (
    compute_study,
)


class _ReplicaGenerator:
    def integers(self, _low: int, _high: int, *, size: int):
        return (0,) * size


def test_duplicate_bootstrap_cells_remain_independent_replicas() -> None:
    cells = (
        ("TAO/1d/2025_q1", ((0.0, 10.0, 0.0, 10.0, 0.0),)),
        ("ETH/1d/2025_q1", ((10.0, 0.0, 10.0, 0.0, 0.0),)),
    )
    replicas = _sample_cell_replicas(cells, (0, 0, 1), _ReplicaGenerator())
    improvements = [values[0][1] - values[0][0] for values in replicas]
    assert improvements == [10.0, 10.0, -10.0]
    assert median(improvements) == 10.0


def test_bootstrap_is_deterministic(config, synthetic_source_bundle) -> None:
    study = compute_study(
        config,
        source_bundle=synthetic_source_bundle,
        implementation_commit="60331170abbbb5e538a4a67fa3a970a137160758",
    )
    assert bootstrap_summary(study.predictions, study.cases, config=config) == bootstrap_summary(
        study.predictions,
        study.cases,
        config=config,
    )


def test_exact_disposition_precedence() -> None:
    empty = {"lower_90": None, "upper_90": None}
    assert disposition(
        {
            "pooled_brier_improvement": empty,
            "pooled_log_loss_improvement": empty,
            "pooled_mean_paired_excess_quality_atr": empty,
            "median_cohort_brier_improvement": empty,
        }
    ) is AdaptiveDisposition.INSUFFICIENT_CALIBRATION_EVIDENCE

    supported = {"lower_90": 0.1, "upper_90": 0.2}
    assert disposition(
        {
            "pooled_brier_improvement": supported,
            "pooled_log_loss_improvement": {"lower_90": 0.0, "upper_90": 0.2},
            "pooled_mean_paired_excess_quality_atr": supported,
            "median_cohort_brier_improvement": supported,
        }
    ) is AdaptiveDisposition.ADAPTIVE_CONTEXT_SUPPORTED_FOR_SHADOW

    assert disposition(
        {
            "pooled_brier_improvement": {"lower_90": -0.2, "upper_90": 0.0},
            "pooled_log_loss_improvement": supported,
            "pooled_mean_paired_excess_quality_atr": supported,
            "median_cohort_brier_improvement": supported,
        }
    ) is AdaptiveDisposition.ADAPTIVE_CONTEXT_NOT_SUPPORTED

    assert disposition(
        {
            "pooled_brier_improvement": {"lower_90": -0.1, "upper_90": 0.2},
            "pooled_log_loss_improvement": supported,
            "pooled_mean_paired_excess_quality_atr": supported,
            "median_cohort_brier_improvement": supported,
        }
    ) is AdaptiveDisposition.INSUFFICIENT_CALIBRATION_EVIDENCE
