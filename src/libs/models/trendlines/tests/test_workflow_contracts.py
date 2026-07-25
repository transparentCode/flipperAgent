from app.trendlines.data import TrendlineArtifactRef, TrendlineDataRequest, resolve_trendline_auto_split_spec
from app.trendlines.workflows import PipelineOptimizationSpec as RootPipelineOptimizationSpec, decide_pipeline_promotion
from app.trendlines.workflows.common import PipelineOptimizationSpec, WorkflowStudyStatus
from app.trendlines.workflows.common.contracts import (
    PIPELINE_WORKFLOW_SEMANTICS_VERSION,
    WorkflowPromotionDecision,
    WorkflowPromotionSpec,
    default_study_status,
    normalize_study_status,
)
from app.trendlines.workflows.common.promotion import TRENDLINE_PIPELINE_PROMOTION_FITNESS_THRESHOLD
from app.trendlines.workflows.pipeline import __all__ as pipeline_all


def test_workflow_root_exports_match_common_contracts():
    assert RootPipelineOptimizationSpec is PipelineOptimizationSpec
    assert "optimize_timeframe" in pipeline_all
    assert "build_pipeline_optimization_spec" in pipeline_all


def test_pipeline_optimization_spec_round_trip_is_deterministic():
    spec = PipelineOptimizationSpec(
        objective="maximize_trendline_boundary_fitness",
        dataset=TrendlineDataRequest(asset="BTCUSDT", timeframes=("1h", "4h"), lookback_days=90),
        artifact=TrendlineArtifactRef(
            artifact_root="app/trendlines/results",
            relative_path="pipeline/btcusdt_1h.json",
        ),
        semantics_version=PIPELINE_WORKFLOW_SEMANTICS_VERSION,
        search_space={
            "engine": "trendlines",
            "extractor_grid_size": 3,
            "fitter_grid_size": 4,
        },
        temporal_split=resolve_trendline_auto_split_spec("1h"),
        promotion=WorkflowPromotionSpec(
            mode="manual_review",
            criteria={"minimum_best_fitness": TRENDLINE_PIPELINE_PROMOTION_FITNESS_THRESHOLD},
        ),
        metadata={"parameter_stages": ["extractor", "fitter", "lookback"]},
    )

    restored = PipelineOptimizationSpec.from_dict(spec.to_dict())

    assert restored == spec
    assert restored.spec_hash == spec.spec_hash


def test_decide_pipeline_promotion_matches_expected_threshold_behavior():
    blocked = decide_pipeline_promotion(
        {"timeframe": "1h", "best_fitness": 0.03, "best_fitness_std": 0.01, "n_windows": 4}
    )
    recommended = decide_pipeline_promotion(
        {"timeframe": "4h", "best_fitness": 0.08, "best_fitness_std": 0.02, "n_windows": 5}
    )
    failed = decide_pipeline_promotion({"timeframe": "1h", "best_fitness": 0.2, "n_windows": 0})

    assert isinstance(blocked, WorkflowPromotionDecision)
    assert blocked.status == "promotion_blocked"
    assert blocked.should_promote is False
    assert recommended.status == "promotion_recommended"
    assert recommended.should_promote is True
    assert failed.status == "failed_no_windows"


def test_study_status_helpers_default_and_normalize_consistently():
    assert default_study_status(has_valid_optimum=True) == WorkflowStudyStatus.COMPLETED_VALID.value
    assert normalize_study_status(None, has_valid_optimum=False) == WorkflowStudyStatus.COMPLETED_NO_VALID_OPTIMUM.value
    assert normalize_study_status(WorkflowStudyStatus.FAILED, has_valid_optimum=True) == WorkflowStudyStatus.FAILED.value