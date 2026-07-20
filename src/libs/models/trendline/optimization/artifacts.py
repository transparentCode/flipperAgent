"""Verified, content-addressed Phase-I review artifacts. Never runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ..contracts import ContractValidationError
from .contracts import (
    OPTIMIZATION_SCHEMA_VERSION,
    FinalistFreeze,
    HoldoutOpenAudit,
    ObjectiveSpec,
    OptimizationStage,
    PromotionDecision,
    PromotionRecommendation,
    StageEvaluationSpec,
    TrialConfig,
    TrialResult,
    canonical_json,
    freeze,
    primitive,
    semantic_id,
)
from .folds import FoldPlan
from .evaluator import (
    build_promotion_recommendation,
    enumerate_grid,
    select_validation_finalist,
    validate_stage_overrides,
    verify_persisted_trial_result,
)


def _text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class RunManifest:
    """The complete semantic request, not merely version labels, for one offline run."""

    requested_stages: tuple[OptimizationStage | str, ...]
    assets: tuple[str, ...]
    timeframes: tuple[str, ...]
    dataset_hashes: Mapping[str, str]
    fold_plan_ids: Mapping[str, str]
    baseline_config_hashes: Mapping[str, str]
    search_spaces: Mapping[str, Mapping[str, Any]]
    objective_versions: Mapping[str, str]
    seeds: Mapping[str, int]
    model_version: str
    config_version: str
    objective_specs: Mapping[str, ObjectiveSpec] = field(default_factory=dict)
    stage_evaluation_specs: Mapping[str, StageEvaluationSpec] = field(default_factory=dict)
    stage_baseline_parameter_values: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    expected_primary_trial_ids: tuple[str, ...] = ()
    maximum_trial_count: int = 1
    search_strategy: str = "bounded_deterministic_grid_v1"
    holdout_policy: Mapping[str, Any] = field(default_factory=lambda: {"open_holdout": False, "requires_finalist_freeze": True})
    finalist_freeze_id: str | None = None
    holdout_open_audit_ids: tuple[str, ...] = ()
    completion_index_id: str | None = None
    codebase_project: str | None = None
    run_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    completion_status: str = "pending"
    failed_stage_reasons: Mapping[str, str] = field(default_factory=dict)
    resolved_configurations: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            stages = tuple(OptimizationStage(stage) for stage in self.requested_stages)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("run manifest has invalid requested stage") from exc
        if not stages or len(set(stages)) != len(stages):
            raise ContractValidationError("run manifest requires unique requested stages")
        object.__setattr__(self, "requested_stages", tuple(sorted(stages, key=lambda item: item.value)))
        for name in ("assets", "timeframes"):
            values = tuple(_text(item, field_name=f"run manifest {name}") for item in getattr(self, name))
            if not values:
                raise ContractValidationError(f"run manifest {name} cannot be empty")
            object.__setattr__(self, name, tuple(sorted(set(values))))
        for name in (
            "dataset_hashes", "fold_plan_ids", "baseline_config_hashes", "search_spaces", "objective_versions",
            "seeds", "holdout_policy", "failed_stage_reasons", "resolved_configurations",
        ):
            object.__setattr__(self, name, freeze(getattr(self, name), field_name=name))
        objectives: dict[str, ObjectiveSpec] = {}
        for key, objective in self.objective_specs.items():
            objectives[_text(key, field_name="objective stage")] = objective if isinstance(objective, ObjectiveSpec) else ObjectiveSpec.from_dict(objective)
        specs: dict[str, StageEvaluationSpec] = {}
        for key, specification in self.stage_evaluation_specs.items():
            specs[_text(key, field_name="evaluation stage")] = specification if isinstance(specification, StageEvaluationSpec) else StageEvaluationSpec.from_dict(specification)
        for stage in self.requested_stages:
            key = stage.value
            if key not in objectives:
                raise ContractValidationError("run manifest objective_specs must cover requested stages")
            if key not in specs:
                raise ContractValidationError("run manifest stage_evaluation_specs must cover requested stages")
            if key in objectives and objectives[key].objective_version != self.objective_versions.get(key):
                raise ContractValidationError("run manifest objective version mismatch")
            if key in specs and specs[key].stage is not stage:
                raise ContractValidationError("run manifest evaluation spec stage mismatch")
        object.__setattr__(self, "objective_specs", MappingProxyType(dict(sorted(objectives.items()))))
        object.__setattr__(self, "stage_evaluation_specs", MappingProxyType(dict(sorted(specs.items()))))
        requested_stage_names = {stage.value for stage in self.requested_stages}
        if set(self.search_spaces) != requested_stage_names:
            raise ContractValidationError("run manifest search_spaces must cover exactly requested stages")
        if self.resolved_configurations:
            required_scopes = {f"{asset}:{timeframe}" for asset in self.assets for timeframe in self.timeframes}
            if set(self.resolved_configurations) != required_scopes:
                raise ContractValidationError("run manifest resolved_configurations must cover every asset/timeframe")
        baseline_parameters = freeze(
            self.stage_baseline_parameter_values,
            field_name="stage_baseline_parameter_values",
        )
        expected_parameter_stages = {
            stage.value
            for stage in self.requested_stages
            if self.search_spaces.get(stage.value)
        }
        if set(baseline_parameters) != expected_parameter_stages:
            raise ContractValidationError("run manifest baseline parameter values must cover exactly searched stages")
        for stage_name in expected_parameter_stages:
            values = baseline_parameters[stage_name]
            if not isinstance(values, Mapping) or set(values) != set(self.search_spaces[stage_name]):
                raise ContractValidationError("run manifest baseline parameter values must cover exactly searched parameters")
        object.__setattr__(self, "stage_baseline_parameter_values", baseline_parameters)
        if isinstance(self.maximum_trial_count, bool) or not isinstance(self.maximum_trial_count, int) or self.maximum_trial_count < 1:
            raise ContractValidationError("maximum_trial_count must be a positive integer")
        object.__setattr__(self, "search_strategy", _text(self.search_strategy, field_name="search_strategy"))
        if self.finalist_freeze_id is not None:
            object.__setattr__(self, "finalist_freeze_id", _text(self.finalist_freeze_id, field_name="finalist_freeze_id"))
        audit_ids = tuple(_text(item, field_name="holdout_open_audit_id") for item in self.holdout_open_audit_ids)
        if len(set(audit_ids)) != len(audit_ids):
            raise ContractValidationError("holdout_open_audit_ids must be unique")
        if audit_ids and self.finalist_freeze_id is None:
            raise ContractValidationError("holdout audit IDs require finalist_freeze_id")
        object.__setattr__(self, "holdout_open_audit_ids", tuple(sorted(audit_ids)))
        if self.completion_index_id is not None:
            object.__setattr__(self, "completion_index_id", _text(self.completion_index_id, field_name="completion_index_id"))
        for name in ("model_version", "config_version", "completion_status"):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        if self.codebase_project is not None:
            object.__setattr__(self, "codebase_project", _text(self.codebase_project, field_name="codebase_project"))
        for name in ("started_at", "completed_at"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset().total_seconds() != 0):
                raise ContractValidationError(f"run manifest {name} must be timezone-aware UTC")
        derived_trial_ids = _derive_expected_primary_trial_ids(self)
        supplied_trial_ids = tuple(_text(item, field_name="expected_primary_trial_id") for item in self.expected_primary_trial_ids)
        if supplied_trial_ids and tuple(sorted(set(supplied_trial_ids))) != derived_trial_ids:
            raise ContractValidationError("run manifest expected primary trial IDs do not match semantic search request")
        object.__setattr__(self, "expected_primary_trial_ids", derived_trial_ids)
        expected = semantic_id("trendline-family-phase-i-run", self.identity_payload())
        if self.run_id is not None and self.run_id != expected:
            raise ContractValidationError("run_id does not match semantic run request")
        object.__setattr__(self, "run_id", expected)

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema_version": OPTIMIZATION_SCHEMA_VERSION,
            "requested_stages": self.requested_stages,
            "assets": self.assets,
            "timeframes": self.timeframes,
            "dataset_hashes": self.dataset_hashes,
            "fold_plan_ids": self.fold_plan_ids,
            "baseline_config_hashes": self.baseline_config_hashes,
            "search_spaces": self.search_spaces,
            "objective_versions": self.objective_versions,
            "objective_specs": {key: value.to_dict() for key, value in self.objective_specs.items()},
            "stage_evaluation_specs": {key: value.to_dict() for key, value in self.stage_evaluation_specs.items()},
            "stage_baseline_parameter_values": self.stage_baseline_parameter_values,
            "expected_primary_trial_ids": self.expected_primary_trial_ids,
            "maximum_trial_count": self.maximum_trial_count,
            "search_strategy": self.search_strategy,
            "holdout_policy": self.holdout_policy,
            "finalist_freeze_id": self.finalist_freeze_id,
            "holdout_open_audit_ids": self.holdout_open_audit_ids,
            "seeds": self.seeds,
            "model_version": self.model_version,
            "config_version": self.config_version,
            "codebase_project": self.codebase_project,
        }
        if self.resolved_configurations:
            payload["resolved_configurations"] = self.resolved_configurations
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {
            **primitive(self.identity_payload()),
            "run_id": self.run_id,
            "started_at": None if self.started_at is None else self.started_at.isoformat(),
            "completed_at": None if self.completed_at is None else self.completed_at.isoformat(),
            "completion_status": self.completion_status,
            "failed_stage_reasons": primitive(self.failed_stage_reasons),
            "completion_index_id": self.completion_index_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RunManifest":
        if not isinstance(value, Mapping):
            raise ContractValidationError("RunManifest payload must be a mapping")
        objectives = {key: ObjectiveSpec.from_dict(item) for key, item in value.get("objective_specs", {}).items()}
        specifications = {key: StageEvaluationSpec.from_dict(item) for key, item in value.get("stage_evaluation_specs", {}).items()}
        return cls(
            requested_stages=tuple(value.get("requested_stages", ())), assets=tuple(value.get("assets", ())),
            timeframes=tuple(value.get("timeframes", ())), dataset_hashes=value.get("dataset_hashes", {}),
            fold_plan_ids=value.get("fold_plan_ids", {}), baseline_config_hashes=value.get("baseline_config_hashes", {}),
            search_spaces=value.get("search_spaces", {}), objective_versions=value.get("objective_versions", {}), seeds=value.get("seeds", {}),
            model_version=value.get("model_version"), config_version=value.get("config_version"), objective_specs=objectives,
            stage_evaluation_specs=specifications, maximum_trial_count=value.get("maximum_trial_count", 1),
            stage_baseline_parameter_values=value.get("stage_baseline_parameter_values", {}),
            expected_primary_trial_ids=tuple(value.get("expected_primary_trial_ids", ())),
            search_strategy=value.get("search_strategy", "bounded_deterministic_grid_v1"), holdout_policy=value.get("holdout_policy", {}),
            finalist_freeze_id=value.get("finalist_freeze_id"), holdout_open_audit_ids=tuple(value.get("holdout_open_audit_ids", ())),
            completion_index_id=value.get("completion_index_id"),
            codebase_project=value.get("codebase_project"), run_id=value.get("run_id"),
            started_at=None if value.get("started_at") is None else datetime.fromisoformat(str(value.get("started_at")).replace("Z", "+00:00")),
            completed_at=None if value.get("completed_at") is None else datetime.fromisoformat(str(value.get("completed_at")).replace("Z", "+00:00")),
            completion_status=value.get("completion_status", "pending"), failed_stage_reasons=value.get("failed_stage_reasons", {}),
            resolved_configurations=value.get("resolved_configurations", {}),
        )


def _derive_expected_primary_trial_ids(manifest: RunManifest) -> tuple[str, ...]:
    """Rebuild the full bounded grid so completion cannot omit an attempted request."""

    trial_ids: list[str] = []
    for stage in manifest.requested_stages:
        search_space = manifest.search_spaces.get(stage.value)
        if search_space is None:
            raise ContractValidationError("run manifest search_spaces must cover requested stages")
        validate_stage_overrides(stage, search_space)
        for overrides in enumerate_grid(search_space, maximum_trial_count=manifest.maximum_trial_count):
            if not overrides:
                continue
            for asset in manifest.assets:
                for timeframe in manifest.timeframes:
                    scope = f"{asset}:{timeframe}"
                    for mapping, field_name in (
                        (manifest.dataset_hashes, "dataset_hashes"),
                        (manifest.fold_plan_ids, "fold_plan_ids"),
                        (manifest.baseline_config_hashes, "baseline_config_hashes"),
                    ):
                        if scope not in mapping:
                            raise ContractValidationError(f"run manifest {field_name} must cover every asset/timeframe")
                    trial = TrialConfig(
                        stage=stage,
                        asset=asset,
                        timeframe=timeframe,
                        parameter_overrides=overrides,
                        baseline_config_hash=manifest.baseline_config_hashes[scope],
                        dataset_hash=manifest.dataset_hashes[scope],
                        fold_plan_id=manifest.fold_plan_ids[scope],
                        objective=manifest.objective_specs[stage.value],
                        model_version=manifest.model_version,
                        config_version=manifest.config_version,
                        seed=manifest.seeds.get(stage.value, 0),
                        evaluation_spec=manifest.stage_evaluation_specs[stage.value],
                    )
                    trial_ids.append(trial.trial_id)
    if len(set(trial_ids)) != len(trial_ids):
        raise ContractValidationError("run manifest search request produces duplicate primary trials")
    return tuple(sorted(trial_ids))


@dataclass(frozen=True)
class CompletionArtifactIndex:
    """Exact persisted artifact membership for one finalized Phase-I run."""

    run_id: str
    baseline_validation_result_id: str
    primary_trial_results: tuple[tuple[str, str], ...]
    counterfactual_trial_results: tuple[tuple[str, str], ...]
    finalist_validation_result_id: str | None
    baseline_holdout_result_id: str | None
    finalist_holdout_result_id: str | None
    finalist_freeze_id: str | None
    holdout_open_audit_ids: tuple[str, ...]
    recommendation_id: str
    summary_id: str
    report_id: str
    completion_status: str
    index_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "run_id", "baseline_validation_result_id", "recommendation_id", "summary_id", "report_id", "completion_status",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        for name in ("finalist_validation_result_id", "baseline_holdout_result_id", "finalist_holdout_result_id", "finalist_freeze_id"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _text(value, field_name=name))
        for name in ("primary_trial_results", "counterfactual_trial_results"):
            pairs = tuple(tuple(item) for item in getattr(self, name))
            if any(len(item) != 2 for item in pairs):
                raise ContractValidationError(f"{name} entries must be trial/result pairs")
            normalized = tuple((_text(item[0], field_name=f"{name} trial_id"), _text(item[1], field_name=f"{name} result_id")) for item in pairs)
            if len({item[0] for item in normalized}) != len(normalized):
                raise ContractValidationError(f"{name} trial IDs must be unique")
            object.__setattr__(self, name, tuple(sorted(normalized)))
        audit_ids = tuple(_text(item, field_name="holdout_open_audit_id") for item in self.holdout_open_audit_ids)
        if len(set(audit_ids)) != len(audit_ids):
            raise ContractValidationError("completion index audit IDs must be unique")
        object.__setattr__(self, "holdout_open_audit_ids", tuple(sorted(audit_ids)))
        expected = semantic_id("trendline-family-phase-i-completion-index", self.identity_payload())
        if self.index_id is not None and self.index_id != expected:
            raise ContractValidationError("completion index ID does not match artifact membership")
        object.__setattr__(self, "index_id", expected)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "baseline_validation_result_id": self.baseline_validation_result_id,
            "primary_trial_results": self.primary_trial_results,
            "counterfactual_trial_results": self.counterfactual_trial_results,
            "finalist_validation_result_id": self.finalist_validation_result_id,
            "baseline_holdout_result_id": self.baseline_holdout_result_id,
            "finalist_holdout_result_id": self.finalist_holdout_result_id,
            "finalist_freeze_id": self.finalist_freeze_id,
            "holdout_open_audit_ids": self.holdout_open_audit_ids,
            "recommendation_id": self.recommendation_id,
            "summary_id": self.summary_id,
            "report_id": self.report_id,
            "completion_status": self.completion_status,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**primitive(self.identity_payload()), "index_id": self.index_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CompletionArtifactIndex":
        if not isinstance(value, Mapping):
            raise ContractValidationError("CompletionArtifactIndex payload must be a mapping")
        return cls(
            run_id=value.get("run_id"), baseline_validation_result_id=value.get("baseline_validation_result_id"),
            primary_trial_results=tuple(tuple(item) for item in value.get("primary_trial_results", ())),
            counterfactual_trial_results=tuple(tuple(item) for item in value.get("counterfactual_trial_results", ())),
            finalist_validation_result_id=value.get("finalist_validation_result_id"),
            baseline_holdout_result_id=value.get("baseline_holdout_result_id"),
            finalist_holdout_result_id=value.get("finalist_holdout_result_id"),
            finalist_freeze_id=value.get("finalist_freeze_id"),
            holdout_open_audit_ids=tuple(value.get("holdout_open_audit_ids", ())),
            recommendation_id=value.get("recommendation_id"), summary_id=value.get("summary_id"),
            report_id=value.get("report_id"), completion_status=value.get("completion_status"), index_id=value.get("index_id"),
        )


@dataclass(frozen=True)
class ArtifactEnvelope:
    run_id: str
    kind: str
    payload: Mapping[str, Any]
    schema_version: str = OPTIMIZATION_SCHEMA_VERSION
    artifact_id: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _text(self.run_id, field_name="artifact run_id"))
        object.__setattr__(self, "kind", _text(self.kind, field_name="artifact kind"))
        object.__setattr__(self, "payload", freeze(self.payload, field_name="artifact payload"))
        object.__setattr__(self, "schema_version", _text(self.schema_version, field_name="artifact schema_version"))
        expected = semantic_id(
            "trendline-family-phase-i-artifact",
            {"schema_version": self.schema_version, "run_id": self.run_id, "kind": self.kind, "payload": _semantic_artifact_payload(self.payload)},
        )
        if self.artifact_id is not None and self.artifact_id != expected:
            raise ContractValidationError("artifact_id does not match content")
        object.__setattr__(self, "artifact_id", expected)
        if self.created_at is not None and (self.created_at.tzinfo is None or self.created_at.utcoffset().total_seconds() != 0):
            raise ContractValidationError("artifact created_at must be timezone-aware UTC")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "run_id": self.run_id,
            "kind": self.kind,
            "created_at": (self.created_at or datetime.now(timezone.utc)).isoformat(),
            "payload": primitive(self.payload),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactEnvelope":
        if not isinstance(value, Mapping):
            raise ContractValidationError("artifact envelope must be a mapping")
        raw_created = value.get("created_at")
        return cls(
            schema_version=value.get("schema_version", OPTIMIZATION_SCHEMA_VERSION), artifact_id=value.get("artifact_id"),
            run_id=value.get("run_id"), kind=value.get("kind"), payload=value.get("payload", {}),
            created_at=None if raw_created is None else datetime.fromisoformat(str(raw_created).replace("Z", "+00:00")),
        )


@dataclass(frozen=True)
class VerifiedRunBundle:
    manifest: RunManifest
    fold_plan: FoldPlan
    baseline_validation: TrialResult
    trials: tuple[TrialResult, ...]
    recommendation: PromotionRecommendation
    completion_index: CompletionArtifactIndex
    baseline_holdout: TrialResult | None = None
    finalist_holdout: TrialResult | None = None
    finalist_freeze: FinalistFreeze | None = None
    holdout_open_audits: tuple[HoldoutOpenAudit, ...] = ()

    def __post_init__(self) -> None:
        if self.manifest.fold_plan_ids.get(f"{self.fold_plan.asset}:{self.fold_plan.timeframe}") != self.fold_plan.fold_plan_id:
            raise ContractValidationError("manifest does not bind fold plan")
        expected_stage = self.manifest.requested_stages[0]
        all_results = (self.baseline_validation,) + tuple(self.trials) + tuple(
            item for item in (self.baseline_holdout, self.finalist_holdout) if item is not None
        )
        for result in all_results:
            trial = result.trial
            if trial.stage is not expected_stage or trial.fold_plan_id != self.fold_plan.fold_plan_id:
                raise ContractValidationError("bundle trial identity does not match manifest/fold plan")
            if trial.dataset_hash != self.fold_plan.data_hash or trial.asset != self.fold_plan.asset or trial.timeframe != self.fold_plan.timeframe:
                raise ContractValidationError("bundle trial dataset identity mismatch")
            specification = self.manifest.stage_evaluation_specs.get(trial.stage.value)
            if specification is not None and specification.spec_id != trial.evaluation_spec.spec_id:
                raise ContractValidationError("bundle trial evaluator semantics mismatch")
            if trial.baseline_config_hash != self.manifest.baseline_config_hashes.get(f"{trial.asset}:{trial.timeframe}"):
                raise ContractValidationError("bundle trial baseline config mismatch")
            objective = self.manifest.objective_specs.get(trial.stage.value)
            if objective is not None and trial.objective != objective:
                raise ContractValidationError("bundle trial objective mismatch")
        result_ids = {result.result_id for result in all_results}
        actual_primary_trial_ids = tuple(sorted(trial.trial.trial_id for trial in self.trials))
        if actual_primary_trial_ids != self.manifest.expected_primary_trial_ids:
            raise ContractValidationError("completion primary trials do not match manifest expected request set")
        if self.recommendation.baseline_result_id not in result_ids:
            raise ContractValidationError("recommendation baseline result is absent from bundle")
        if self.recommendation.finalist_result_id is not None and self.recommendation.finalist_result_id not in result_ids:
            raise ContractValidationError("recommendation finalist result is absent from bundle")
        if self.recommendation.stage is not expected_stage:
            raise ContractValidationError("recommendation stage does not match manifest")
        if self.manifest.finalist_freeze_id is not None:
            if self.finalist_freeze is None or self.finalist_freeze.freeze_id != self.manifest.finalist_freeze_id:
                raise ContractValidationError("manifest finalist freeze evidence mismatch")
        if tuple(sorted(audit.audit_id for audit in self.holdout_open_audits)) != self.manifest.holdout_open_audit_ids:
            raise ContractValidationError("manifest holdout audit evidence mismatch")
        if self.manifest.completion_index_id != self.completion_index.index_id:
            raise ContractValidationError("manifest completion index evidence mismatch")
        _verify_completion_index(
            index=self.completion_index,
            manifest=self.manifest,
            baseline=self.baseline_validation,
            trials=self.trials,
            recommendation=self.recommendation,
            baseline_holdout=self.baseline_holdout,
            finalist_holdout=self.finalist_holdout,
            finalist_freeze=self.finalist_freeze,
            holdout_open_audits=self.holdout_open_audits,
        )
        if self.finalist_freeze is not None:
            if self.finalist_freeze.fold_plan_id != self.fold_plan.fold_plan_id:
                raise ContractValidationError("finalist freeze fold plan mismatch")
            if self.finalist_freeze.baseline_validation_result_id != self.baseline_validation.result_id:
                raise ContractValidationError("finalist freeze baseline mismatch")
            if self.recommendation.finalist_result_id is not None and self.finalist_freeze.finalist_validation_result_id != self.recommendation.finalist_result_id:
                raise ContractValidationError("finalist freeze recommendation mismatch")
        if self.holdout_open_audits:
            if self.finalist_freeze is None or len(self.holdout_open_audits) != 2:
                raise ContractValidationError("holdout opening requires two audited frozen requests")
            if {audit.target for audit in self.holdout_open_audits} != {"baseline", "finalist"}:
                raise ContractValidationError("holdout audit targets must cover baseline and finalist")
            if any(audit.finalist_freeze_id != self.finalist_freeze.freeze_id or audit.holdout_plan_id != self.fold_plan.holdout.holdout_plan_id for audit in self.holdout_open_audits):
                raise ContractValidationError("holdout audit provenance mismatch")
            audits_by_target = {audit.target: audit for audit in self.holdout_open_audits}
            if audits_by_target["baseline"].validation_result_id != self.baseline_validation.result_id:
                raise ContractValidationError("baseline holdout audit does not bind baseline validation")
            if self.recommendation.finalist_result_id is None or audits_by_target["finalist"].validation_result_id != self.recommendation.finalist_result_id:
                raise ContractValidationError("finalist holdout audit does not bind frozen finalist")
            if self.baseline_holdout is None or self.finalist_holdout is None:
                raise ContractValidationError("holdout audits require both holdout results")
            if audits_by_target["baseline"].trial_id != self.baseline_holdout.trial.trial_id or audits_by_target["finalist"].trial_id != self.finalist_holdout.trial.trial_id:
                raise ContractValidationError("holdout result trial identities do not match audits")
        if self.recommendation.decision is PromotionDecision.PROMOTE:
            if self.baseline_holdout is None or self.finalist_holdout is None or self.finalist_freeze is None or len(self.holdout_open_audits) != 2:
                raise ContractValidationError("promote bundle requires verified holdout evidence")
        self._verify_derived_truth()

    def _verify_derived_truth(self) -> None:
        verify_persisted_trial_result(
            result=self.baseline_validation, fold_plan=self.fold_plan, window_kind="validation", baseline=None
        )
        for trial in self.trials:
            if trial.trial.trial_kind != "primary":
                raise ContractValidationError("completion primary trial set contains non-primary trial")
            verify_persisted_trial_result(
                result=trial,
                fold_plan=self.fold_plan,
                window_kind="validation",
                baseline=self.baseline_validation,
                baseline_parameter_values=self.manifest.stage_baseline_parameter_values[trial.trial.stage.value],
            )
        if self.baseline_holdout is not None:
            verify_persisted_trial_result(
                result=self.baseline_holdout,
                fold_plan=self.fold_plan,
                window_kind="holdout",
                baseline=None,
                baseline_parameter_values=self.manifest.stage_baseline_parameter_values[
                    self.baseline_holdout.trial.stage.value
                ],
            )
        if self.finalist_holdout is not None:
            verify_persisted_trial_result(
                result=self.finalist_holdout,
                fold_plan=self.fold_plan,
                window_kind="holdout",
                baseline=self.baseline_holdout,
                baseline_parameter_values=self.manifest.stage_baseline_parameter_values[
                    self.finalist_holdout.trial.stage.value
                ],
            )
        winner = select_validation_finalist(baseline=self.baseline_validation, trials=self.trials)
        if winner is None:
            if self.recommendation.finalist_result_id is not None or self.finalist_freeze is not None:
                raise ContractValidationError("bundle declares finalist when deterministic validation has none")
        else:
            if winner.result_id == self.baseline_validation.result_id:
                raise ContractValidationError("baseline cannot be its own finalist")
            if self.recommendation.finalist_result_id != winner.result_id:
                raise ContractValidationError("recommendation finalist is not deterministic validation winner")
            if self.finalist_freeze is not None and self.finalist_freeze.finalist_validation_result_id != winner.result_id:
                raise ContractValidationError("frozen finalist is not deterministic validation winner")
            if self.finalist_freeze is not None:
                manifest_spec = self.manifest.stage_evaluation_specs[winner.trial.stage.value]
                if self.finalist_freeze.stage is not winner.trial.stage:
                    raise ContractValidationError("finalist freeze stage does not match deterministic winner")
                if self.finalist_freeze.objective != winner.trial.objective:
                    raise ContractValidationError("finalist freeze objective does not match deterministic winner")
                if self.finalist_freeze.evaluation_spec_id != winner.trial.evaluation_spec.spec_id:
                    raise ContractValidationError("finalist freeze evaluator does not match deterministic winner")
                if self.finalist_freeze.evaluation_spec_id != manifest_spec.spec_id:
                    raise ContractValidationError("finalist freeze evaluator does not match manifest")
                if self.finalist_freeze.fold_plan_id != self.fold_plan.fold_plan_id:
                    raise ContractValidationError("finalist freeze fold plan does not match bundle")
                if self.baseline_holdout is not None and self.baseline_holdout.trial.evaluation_spec.spec_id != self.finalist_freeze.evaluation_spec_id:
                    raise ContractValidationError("baseline holdout evaluator does not match finalist freeze")
                if self.finalist_holdout is not None and self.finalist_holdout.trial.evaluation_spec.spec_id != self.finalist_freeze.evaluation_spec_id:
                    raise ContractValidationError("finalist holdout evaluator does not match finalist freeze")
                for holdout in (self.baseline_holdout, self.finalist_holdout):
                    if holdout is None:
                        continue
                    if holdout.trial.objective != self.finalist_freeze.objective:
                        raise ContractValidationError("holdout objective does not match finalist freeze")
                    if holdout.trial.fold_plan_id != self.finalist_freeze.fold_plan_id:
                        raise ContractValidationError("holdout fold plan does not match finalist freeze")
            if [audit.to_dict() for audit in self.recommendation.parameter_effect_audits] != [
                audit.to_dict() for audit in winner.parameter_effect_audits
            ]:
                raise ContractValidationError("recommendation audits do not equal finalist audits")
        expected = build_promotion_recommendation(
            baseline_validation=self.baseline_validation,
            finalist_validation=winner,
            baseline_holdout=self.baseline_holdout,
            finalist_holdout=self.finalist_holdout,
            validation_trials=self.trials,
        )
        if self.recommendation.to_dict() != expected.to_dict():
            raise ContractValidationError("persisted promotion recommendation does not match derived evidence")


def artifact_envelope(*, run_id: str, kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    return ArtifactEnvelope(run_id=run_id, kind=kind, payload=payload).to_dict()


def _semantic_artifact_payload(value: Any) -> Any:
    operational_keys = {"created_at", "started_at", "completed_at", "runtime_diagnostics", "runtime_seconds", "latency_ms", "bars_per_second", "artifact_size_bytes"}
    if isinstance(value, Mapping):
        return {key: _semantic_artifact_payload(item) for key, item in value.items() if key not in operational_keys}
    if isinstance(value, tuple):
        return tuple(_semantic_artifact_payload(item) for item in value)
    return value


def atomic_write_json(path: str | Path, payload: Mapping[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = canonical_json(payload) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return target


def load_artifact_envelope(path: str | Path) -> ArtifactEnvelope:
    try:
        payload = json.loads(Path(path).read_text(encoding="ascii"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractValidationError("artifact payload cannot be read") from exc
    return ArtifactEnvelope.from_dict(payload)


def build_completion_artifact_index(
    *,
    manifest: RunManifest,
    baseline: TrialResult,
    trials: Sequence[TrialResult],
    recommendation: PromotionRecommendation,
    baseline_holdout: TrialResult | None = None,
    finalist_holdout: TrialResult | None = None,
    finalist_freeze: FinalistFreeze | None = None,
    holdout_open_audits: Sequence[HoldoutOpenAudit] = (),
) -> CompletionArtifactIndex:
    summary = _summary_payload(baseline, trials)
    report = _render_report(manifest=manifest, recommendation=recommendation, baseline=baseline, trials=trials)
    return CompletionArtifactIndex(
        run_id=manifest.run_id,
        baseline_validation_result_id=baseline.result_id,
        primary_trial_results=tuple((trial.trial.trial_id, trial.result_id) for trial in trials),
        counterfactual_trial_results=tuple(
            (counterfactual.trial.trial_id, counterfactual.result_id)
            for trial in trials
            for counterfactual in trial.counterfactual_results
        ),
        finalist_validation_result_id=recommendation.finalist_result_id,
        baseline_holdout_result_id=None if baseline_holdout is None else baseline_holdout.result_id,
        finalist_holdout_result_id=None if finalist_holdout is None else finalist_holdout.result_id,
        finalist_freeze_id=None if finalist_freeze is None else finalist_freeze.freeze_id,
        holdout_open_audit_ids=tuple(audit.audit_id for audit in holdout_open_audits),
        recommendation_id=recommendation.recommendation_id,
        summary_id=semantic_id("trendline-family-phase-i-summary", summary),
        report_id=semantic_id("trendline-family-phase-i-report", report),
        completion_status=manifest.completion_status,
    )


def _verify_completion_index(
    *,
    index: CompletionArtifactIndex,
    manifest: RunManifest,
    baseline: TrialResult,
    trials: Sequence[TrialResult],
    recommendation: PromotionRecommendation,
    baseline_holdout: TrialResult | None,
    finalist_holdout: TrialResult | None,
    finalist_freeze: FinalistFreeze | None,
    holdout_open_audits: Sequence[HoldoutOpenAudit],
) -> None:
    expected = build_completion_artifact_index(
        manifest=manifest,
        baseline=baseline,
        trials=trials,
        recommendation=recommendation,
        baseline_holdout=baseline_holdout,
        finalist_holdout=finalist_holdout,
        finalist_freeze=finalist_freeze,
        holdout_open_audits=holdout_open_audits,
    )
    if index.to_dict() != expected.to_dict():
        raise ContractValidationError("completion index does not match complete run evidence")


def write_phase_i_artifacts(
    *,
    output_root: str | Path,
    manifest: RunManifest,
    fold_plan: FoldPlan,
    baseline: TrialResult,
    trials: Sequence[TrialResult],
    recommendation: PromotionRecommendation,
    baseline_holdout: TrialResult | None = None,
    finalist_holdout: TrialResult | None = None,
    finalist_freeze: FinalistFreeze | None = None,
    holdout_open_audits: Sequence[HoldoutOpenAudit] = (),
    completion_index: CompletionArtifactIndex | None = None,
) -> Mapping[str, Path]:
    if completion_index is None:
        raise ContractValidationError("Phase-I artifacts require CompletionArtifactIndex")
    bundle = VerifiedRunBundle(
        manifest=manifest, fold_plan=fold_plan, baseline_validation=baseline, trials=tuple(trials), recommendation=recommendation,
        baseline_holdout=baseline_holdout, finalist_holdout=finalist_holdout, finalist_freeze=finalist_freeze,
        holdout_open_audits=tuple(holdout_open_audits), completion_index=completion_index,
    )
    del bundle
    root = Path(output_root)
    stage = recommendation.stage.value
    paths: dict[str, Path] = {}

    def write(key: str, path: Path, kind: str, payload: Mapping[str, Any]) -> None:
        paths[key] = atomic_write_json(path, artifact_envelope(run_id=manifest.run_id, kind=kind, payload=payload))

    write("manifest", root / "run_manifest.json", "run_manifest", manifest.to_dict())
    write("fold_plan", root / "fold_plan.json", "fold_plan", fold_plan.to_dict())
    write("baseline", root / "baseline" / f"{baseline.result_id}.json", "baseline_validation", baseline.to_dict())
    trial_root = root / stage / "trials"
    for trial in sorted(trials, key=lambda item: item.trial.trial_id):
        write(f"trial:{trial.trial.trial_id}", trial_root / f"{trial.trial.trial_id}.json", "trial_result", trial.to_dict())
        for counterfactual in trial.counterfactual_results:
            write(
                f"counterfactual:{counterfactual.trial.trial_id}", trial_root / "counterfactuals" / f"{counterfactual.trial.trial_id}.json",
                "counterfactual_result", counterfactual.to_dict(),
            )
    if finalist_freeze is not None:
        write("finalist_freeze", root / stage / "holdout" / "finalist_freeze.json", "finalist_freeze", finalist_freeze.to_dict())
    for audit in holdout_open_audits:
        write(f"holdout_audit:{audit.target}", root / stage / "holdout" / f"{audit.target}_open_audit.json", "holdout_open_audit", audit.to_dict())
    if baseline_holdout is not None:
        write("baseline_holdout", root / stage / "holdout" / "baseline.json", "baseline_holdout", baseline_holdout.to_dict())
    if finalist_holdout is not None:
        write("finalist_holdout", root / stage / "holdout" / "finalist.json", "finalist_holdout", finalist_holdout.to_dict())
    write("summary", root / stage / "summary.json", "stage_summary", _summary_payload(baseline, trials))
    write("recommendation", root / stage / "recommendation.json", "promotion_recommendation", recommendation.to_dict())
    write("completion_index", root / "completion_index.json", "completion_index", completion_index.to_dict())
    report_path = root / "final_report.md"
    _atomic_write_text(report_path, _render_report(manifest=manifest, recommendation=recommendation, baseline=baseline, trials=trials))
    paths["report"] = report_path
    verify_artifact_bundle(paths)
    return paths


def verify_artifact_bundle(paths: Mapping[str, Path]) -> None:
    """Read every JSON envelope and rebuild typed contracts to detect tampering."""

    envelopes = {key: load_artifact_envelope(path) for key, path in paths.items() if path.suffix == ".json"}
    required = {"manifest", "fold_plan", "baseline", "summary", "recommendation", "completion_index", "report"}
    missing = required.difference(paths)
    if missing:
        raise ContractValidationError(f"artifact bundle missing required paths: {sorted(missing)}")
    manifest = RunManifest.from_dict(envelopes["manifest"].payload)
    if any(envelope.run_id != manifest.run_id for envelope in envelopes.values()):
        raise ContractValidationError("artifact envelope run IDs do not match manifest")
    expected_kinds = {
        "manifest": "run_manifest",
        "fold_plan": "fold_plan",
        "baseline": "baseline_validation",
        "recommendation": "promotion_recommendation",
        "summary": "stage_summary",
        "completion_index": "completion_index",
    }
    for key, expected_kind in expected_kinds.items():
        if envelopes[key].kind != expected_kind:
            raise ContractValidationError("artifact kind does not match bundle role")
    fold_plan = FoldPlan.from_dict(envelopes["fold_plan"].payload)
    baseline = TrialResult.from_dict(envelopes["baseline"].payload)
    completion_index = CompletionArtifactIndex.from_dict(envelopes["completion_index"].payload)
    expected_paths = {
        "manifest",
        "fold_plan",
        "baseline",
        "summary",
        "recommendation",
        "completion_index",
        "report",
        *(f"trial:{trial_id}" for trial_id, _ in completion_index.primary_trial_results),
        *(f"counterfactual:{trial_id}" for trial_id, _ in completion_index.counterfactual_trial_results),
    }
    if completion_index.finalist_freeze_id is not None:
        expected_paths.add("finalist_freeze")
    if completion_index.baseline_holdout_result_id is not None:
        expected_paths.add("baseline_holdout")
    if completion_index.finalist_holdout_result_id is not None:
        expected_paths.add("finalist_holdout")
    if completion_index.holdout_open_audit_ids:
        expected_paths.update({"holdout_audit:baseline", "holdout_audit:finalist"})
    if set(paths) != expected_paths:
        raise ContractValidationError("artifact path set does not match completion index")
    trials = tuple(
        TrialResult.from_dict(envelope.payload)
        for key, envelope in envelopes.items()
        if key.startswith("trial:")
    )
    persisted_counterfactuals = {
        TrialResult.from_dict(envelope.payload).result_id
        for key, envelope in envelopes.items()
        if key.startswith("counterfactual:")
    }
    nested_counterfactuals = {
        counterfactual.result_id
        for trial in trials
        for counterfactual in trial.counterfactual_results
    }
    if persisted_counterfactuals != nested_counterfactuals:
        raise ContractValidationError("counterfactual artifacts do not match parent trial audits")
    recommendation = PromotionRecommendation.from_dict(envelopes["recommendation"].payload)
    baseline_holdout = None if "baseline_holdout" not in envelopes else TrialResult.from_dict(envelopes["baseline_holdout"].payload)
    finalist_holdout = None if "finalist_holdout" not in envelopes else TrialResult.from_dict(envelopes["finalist_holdout"].payload)
    finalist_freeze = None if "finalist_freeze" not in envelopes else FinalistFreeze.from_dict(envelopes["finalist_freeze"].payload)
    audits = tuple(HoldoutOpenAudit.from_dict(envelope.payload) for key, envelope in envelopes.items() if key.startswith("holdout_audit:"))
    primary_by_id = {trial.trial.trial_id: trial.result_id for trial in trials}
    counter_by_id = {
        TrialResult.from_dict(envelope.payload).trial.trial_id: TrialResult.from_dict(envelope.payload).result_id
        for key, envelope in envelopes.items()
        if key.startswith("counterfactual:")
    }
    if tuple(sorted(primary_by_id.items())) != completion_index.primary_trial_results:
        raise ContractValidationError("persisted primary trials do not match completion index")
    if tuple(sorted(counter_by_id.items())) != completion_index.counterfactual_trial_results:
        raise ContractValidationError("persisted counterfactuals do not match completion index")
    summary = _summary_payload(baseline, trials)
    if envelopes["summary"].payload != freeze(summary, field_name="summary payload"):
        raise ContractValidationError("persisted summary does not match primary trial set")
    if completion_index.summary_id != semantic_id("trendline-family-phase-i-summary", summary):
        raise ContractValidationError("completion index summary identity mismatch")
    report_text = Path(paths["report"]).read_text(encoding="utf-8")
    if completion_index.report_id != semantic_id("trendline-family-phase-i-report", report_text):
        raise ContractValidationError("completion index report identity mismatch")
    VerifiedRunBundle(
        manifest=manifest, fold_plan=fold_plan, baseline_validation=baseline, trials=trials, recommendation=recommendation,
        baseline_holdout=baseline_holdout, finalist_holdout=finalist_holdout, finalist_freeze=finalist_freeze, holdout_open_audits=audits,
        completion_index=completion_index,
    )


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _summary_payload(baseline: TrialResult, trials: Sequence[TrialResult]) -> dict[str, Any]:
    return {
        "baseline_result_id": baseline.result_id,
        "trial_result_ids": tuple(item.result_id for item in sorted(trials, key=lambda item: item.trial.trial_id)),
        "completed_count": sum(item.status.value == "completed" for item in trials),
        "failed_or_invalid_count": sum(item.status.value != "completed" for item in trials),
    }


def _render_report(*, manifest: RunManifest, recommendation: PromotionRecommendation, baseline: TrialResult, trials: Sequence[TrialResult]) -> str:
    return "\n".join(
        (
            "# Trendline Family Phase-I Review", "", f"- Run ID: `{manifest.run_id}`", f"- Stage: `{recommendation.stage.value}`",
            f"- Recommendation: `{recommendation.decision.value}`", f"- Baseline result: `{baseline.result_id}`",
            f"- Trial count: `{len(trials)}`", "", "## Rationale", *(f"- {item}" for item in recommendation.rationale), "",
            "## Runtime Safety", "- Review artifacts only. No runtime YAML, adapter, or active policy was changed.", "",
        )
    )


__all__ = [
    "ArtifactEnvelope", "RunManifest", "VerifiedRunBundle", "artifact_envelope", "atomic_write_json", "load_artifact_envelope",
    "verify_artifact_bundle", "write_phase_i_artifacts",
]
