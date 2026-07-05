"""Shared workflow/application contracts for trendlines-first studies."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict

from app.trendlines.data import TrendlineArtifactRef, TrendlineDataRequest, TemporalSplitSpec


PIPELINE_WORKFLOW_SEMANTICS_VERSION = "2026-04-08-v1"


def _stable_hash(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class WorkflowStudyStatus(str, Enum):
    """Canonical workflow terminal states for trendlines studies."""

    COMPLETED_VALID = "completed_valid"
    COMPLETED_NO_VALID_OPTIMUM = "completed_no_valid_optimum"
    SKIPPED = "skipped"
    SKIPPED_NO_VALID_OPTIMUM = "skipped_no_valid_optimum"
    FAILED = "failed"


def default_study_status(*, has_valid_optimum: bool) -> str:
    return (
        WorkflowStudyStatus.COMPLETED_VALID.value
        if has_valid_optimum
        else WorkflowStudyStatus.COMPLETED_NO_VALID_OPTIMUM.value
    )


def normalize_study_status(
    value: str | WorkflowStudyStatus | None,
    *,
    has_valid_optimum: bool,
) -> str:
    if value is None:
        return default_study_status(has_valid_optimum=has_valid_optimum)
    if isinstance(value, WorkflowStudyStatus):
        return value.value
    return str(value).strip().lower() or default_study_status(has_valid_optimum=has_valid_optimum)


@dataclass(frozen=True)
class WorkflowPromotionDecision:
    """Serializable promotion result attached to workflow outputs."""

    status: str = "not_evaluated"
    should_promote: bool = False
    selected_candidate: str | int | None = None
    reason: str | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "should_promote": self.should_promote,
            "selected_candidate": self.selected_candidate,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "WorkflowPromotionDecision":
        raw = dict(payload or {})
        return cls(
            status=str(raw.get("status", "not_evaluated")),
            should_promote=bool(raw.get("should_promote", False)),
            selected_candidate=raw.get("selected_candidate"),
            reason=raw.get("reason"),
            metadata=dict(raw.get("metadata", {})),
        )


@dataclass(frozen=True)
class WorkflowPromotionSpec:
    """Promotion criteria attached to a trendlines workflow experiment."""

    mode: str = "manual_review"
    criteria: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"mode": self.mode, "criteria": dict(self.criteria)}

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "WorkflowPromotionSpec":
        raw = dict(payload or {})
        return cls(
            mode=str(raw.get("mode", "manual_review")),
            criteria=dict(raw.get("criteria", {})),
        )


@dataclass(frozen=True)
class WorkflowExperimentSpec:
    """Serializable workflow specification for deterministic trendlines runs."""

    objective: str
    dataset: TrendlineDataRequest
    artifact: TrendlineArtifactRef
    semantics_version: str
    search_space: Dict[str, Any] = field(default_factory=dict)
    temporal_split: TemporalSplitSpec | None = None
    promotion: WorkflowPromotionSpec = field(default_factory=WorkflowPromotionSpec)
    metadata: Dict[str, Any] = field(default_factory=dict)
    workflow_kind: str = "workflow"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_kind": self.workflow_kind,
            "objective": self.objective,
            "dataset": self.dataset.to_dict(),
            "artifact": self.artifact.to_dict(),
            "semantics_version": self.semantics_version,
            "search_space": dict(self.search_space),
            "temporal_split": self.temporal_split.to_dict() if self.temporal_split else None,
            "promotion": self.promotion.to_dict(),
            "metadata": dict(self.metadata),
        }

    @property
    def spec_hash(self) -> str:
        return _stable_hash(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "WorkflowExperimentSpec":
        raw = dict(payload or {})
        temporal_payload = raw.get("temporal_split")
        return cls(
            objective=str(raw.get("objective", "")),
            dataset=TrendlineDataRequest.from_dict(raw.get("dataset")),
            artifact=TrendlineArtifactRef.from_dict(raw.get("artifact")),
            semantics_version=str(raw.get("semantics_version", "")),
            search_space=dict(raw.get("search_space", {})),
            temporal_split=TemporalSplitSpec.from_dict(temporal_payload) if temporal_payload else None,
            promotion=WorkflowPromotionSpec.from_dict(raw.get("promotion")),
            metadata=dict(raw.get("metadata", {})),
            workflow_kind=str(raw.get("workflow_kind", "workflow")),
        )


@dataclass(frozen=True)
class PipelineOptimizationSpec(WorkflowExperimentSpec):
    workflow_kind: str = "pipeline_optimization"

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "PipelineOptimizationSpec":
        raw = dict(payload or {})
        temporal_payload = raw.get("temporal_split")
        return cls(
            objective=str(raw.get("objective", "")),
            dataset=TrendlineDataRequest.from_dict(raw.get("dataset")),
            artifact=TrendlineArtifactRef.from_dict(raw.get("artifact")),
            semantics_version=str(raw.get("semantics_version", PIPELINE_WORKFLOW_SEMANTICS_VERSION)),
            search_space=dict(raw.get("search_space", {})),
            temporal_split=TemporalSplitSpec.from_dict(temporal_payload) if temporal_payload else None,
            promotion=WorkflowPromotionSpec.from_dict(raw.get("promotion")),
            metadata=dict(raw.get("metadata", {})),
            workflow_kind=str(raw.get("workflow_kind", "pipeline_optimization")),
        )


__all__ = [
    "PIPELINE_WORKFLOW_SEMANTICS_VERSION",
    "PipelineOptimizationSpec",
    "WorkflowExperimentSpec",
    "WorkflowPromotionDecision",
    "WorkflowPromotionSpec",
    "WorkflowStudyStatus",
    "default_study_status",
    "normalize_study_status",
]