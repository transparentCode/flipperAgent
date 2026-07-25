"""Shared workflow contracts and promotion helpers for trendlines runs."""

from app.trendlines.workflows.common.contracts import (
    PIPELINE_WORKFLOW_SEMANTICS_VERSION,
    PipelineOptimizationSpec,
    WorkflowExperimentSpec,
    WorkflowPromotionDecision,
    WorkflowPromotionSpec,
    WorkflowStudyStatus,
    default_study_status,
    normalize_study_status,
)
from app.trendlines.workflows.common.promotion import decide_pipeline_promotion

__all__ = [
    "PIPELINE_WORKFLOW_SEMANTICS_VERSION",
    "PipelineOptimizationSpec",
    "WorkflowExperimentSpec",
    "WorkflowPromotionDecision",
    "WorkflowPromotionSpec",
    "WorkflowStudyStatus",
    "decide_pipeline_promotion",
    "default_study_status",
    "normalize_study_status",
]