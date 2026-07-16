"""Immutable contracts for the SR-V1.8 geometry sensitivity study."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import re
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash
from libs.models.sr.scripts.cohort_readiness.contracts import (
    APPROVED_ASSETS,
    AssetEvaluation,
    CohortAggregate,
    MacroAggregate,
)


SCHEMA_VERSION = "1.0"
PARAMETER_FAMILY = "detection_geometry"
_HASH_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")
_OVERRIDE_PATHS = ("detection.pivot_span_bars", "detection.zone_half_width_atr")
_PROMOTION_GATE_PREFIXES = (
    "structural.",
    "sample.",
    "comparability.",
    "quality.",
    "guardrail.",
    "stability.",
    "baseline.",
)
_DIAGNOSTIC_GATE_PREFIX = "diagnostic."


def _string(value: Any, *, path: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContractValidationError(f"{path} must be a non-empty string")
    return value


def _hash(value: Any, *, path: str) -> str:
    value = _string(value, path=path)
    if _HASH_RE.fullmatch(value) is None:
        raise ContractValidationError(f"{path} must be a lowercase SHA-256 hex string")
    return value


def _commit(value: Any, *, path: str) -> str:
    value = _string(value, path=path)
    if _COMMIT_RE.fullmatch(value) is None:
        raise ContractValidationError(f"{path} must be a git SHA")
    return value


def _integer(value: Any, *, path: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or type(value) is not int or value < minimum:
        raise ContractValidationError(f"{path} must be an integer >= {minimum}")
    return value


def _number(value: Any, *, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{path} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{path} must be finite") from exc
    if not math.isfinite(result):
        raise ContractValidationError(f"{path} must be finite")
    return 0.0 if result == 0.0 else result


def _finite_payload(value: Any, *, path: str = "value") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractValidationError(f"{path} must be finite")
    if isinstance(value, dict):
        for key, item in value.items():
            _finite_payload(item, path=f"{path}.{key}")
    elif isinstance(value, (tuple, list)):
        for index, item in enumerate(value):
            _finite_payload(item, path=f"{path}[{index}]")


def _tuple_pairs(value: Any, *, path: str) -> tuple[tuple[str, Any], ...]:
    if type(value) is not tuple:
        raise ContractValidationError(f"{path} must be a tuple")
    result: list[tuple[str, Any]] = []
    for index, entry in enumerate(value):
        if type(entry) is not tuple or len(entry) != 2:
            raise ContractValidationError(f"{path}[{index}] must be a pair")
        result.append((_string(entry[0], path=f"{path}[{index}].path"), entry[1]))
    return tuple(result)


@dataclass(frozen=True)
class GeometryCandidate:
    """One immutable point in the predeclared 3x3 Cartesian grid."""

    pivot_span_bars: int
    zone_half_width_atr: float
    baseline: bool
    grid_position: tuple[int, int]
    candidate_id: str = field(init=False)
    manhattan_distance: float = field(init=False)

    def __post_init__(self) -> None:
        pivot = _integer(self.pivot_span_bars, path="candidate.pivot_span_bars", minimum=1)
        width = _number(self.zone_half_width_atr, path="candidate.zone_half_width_atr")
        if width <= 0:
            raise ContractValidationError("candidate.zone_half_width_atr must be positive")
        if type(self.baseline) is not bool:
            raise ContractValidationError("candidate.baseline must be boolean")
        if type(self.grid_position) is not tuple or len(self.grid_position) != 2 or any(type(value) is not int or isinstance(value, bool) or value < 0 for value in self.grid_position):
            raise ContractValidationError("candidate.grid_position must be a pair of non-negative integers")
        if (pivot, width) == (5, 0.25):
            expected_baseline = True
        else:
            expected_baseline = False
        if self.baseline != expected_baseline:
            raise ContractValidationError("candidate baseline flag does not match the frozen baseline pair")
        position = (self.grid_position[0], self.grid_position[1])
        identity = {
            "schema_version": SCHEMA_VERSION,
            "parameter_family": PARAMETER_FAMILY,
            "pivot_span_bars": pivot,
            "zone_half_width_atr": width,
        }
        object.__setattr__(self, "pivot_span_bars", pivot)
        object.__setattr__(self, "zone_half_width_atr", width)
        object.__setattr__(self, "grid_position", position)
        object.__setattr__(self, "candidate_id", deterministic_hash(identity))
        distance = abs(pivot - 5) / 2.0 + abs(width - 0.25) / 0.10
        object.__setattr__(self, "manhattan_distance", _number(distance, path="candidate.manhattan_distance"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "parameter_family": PARAMETER_FAMILY,
            "pivot_span_bars": self.pivot_span_bars,
            "zone_half_width_atr": self.zone_half_width_atr,
        }

    def to_payload(self) -> dict[str, Any]:
        return {
            **self.identity_payload(),
            "candidate_id": self.candidate_id,
            "baseline": self.baseline,
            "grid_position": list(self.grid_position),
            "manhattan_distance": self.manhattan_distance,
        }


@dataclass(frozen=True)
class TrialOverride:
    path: str
    baseline_value: int | float
    candidate_value: int | float
    source: str = "study_candidate"

    def __post_init__(self) -> None:
        path = _string(self.path, path="trial_override.path")
        if path not in _OVERRIDE_PATHS:
            raise ContractValidationError("trial override path is outside the two approved detection fields")
        source = _string(self.source, path="trial_override.source")
        if source != "study_candidate":
            raise ContractValidationError("trial override source must be study_candidate")
        _number(self.baseline_value, path=f"trial_override.{path}.baseline_value")
        _number(self.candidate_value, path=f"trial_override.{path}.candidate_value")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "baseline_value", 0.0 if self.baseline_value == 0 else self.baseline_value)
        object.__setattr__(self, "candidate_value", 0.0 if self.candidate_value == 0 else self.candidate_value)

    def to_payload(self) -> dict[str, Any]:
        return {"path": self.path, "baseline_value": self.baseline_value, "candidate_value": self.candidate_value, "source": self.source}


@dataclass(frozen=True)
class StudyGate:
    name: str
    passed: bool
    value: Any
    threshold: Any
    reason: str
    asset: str | None = None
    fold: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _string(self.name, path="gate.name"))
        if type(self.passed) is not bool:
            raise ContractValidationError("gate.passed must be boolean")
        object.__setattr__(self, "reason", _string(self.reason, path="gate.reason"))
        if self.asset is not None:
            object.__setattr__(self, "asset", _string(self.asset, path="gate.asset"))
        if self.fold is not None:
            object.__setattr__(self, "fold", _string(self.fold, path="gate.fold"))
        _finite_payload(self.value, path="gate.value")
        _finite_payload(self.threshold, path="gate.threshold")

    def to_payload(self) -> dict[str, Any]:
        return {"name": self.name, "asset": self.asset, "fold": self.fold, "passed": self.passed, "value": self.value, "threshold": self.threshold, "reason": self.reason}


@dataclass(frozen=True)
class CandidateAssetResult:
    asset: str
    source_id: str
    inherited_resolved_config_hash: str
    effective_resolved_config_hash: str
    effective_field_provenance: tuple[tuple[str, str], ...]
    trial_overrides: tuple[TrialOverride, ...]
    evaluation: AssetEvaluation
    structural_gates: tuple[StudyGate, ...]

    def __post_init__(self) -> None:
        asset = _string(self.asset, path="candidate_asset.asset")
        if asset not in APPROVED_ASSETS or self.evaluation.asset != asset:
            raise ContractValidationError("candidate asset ownership mismatch")
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "source_id", _hash(self.source_id, path="candidate_asset.source_id"))
        object.__setattr__(self, "inherited_resolved_config_hash", _hash(self.inherited_resolved_config_hash, path="candidate_asset.inherited_resolved_config_hash"))
        object.__setattr__(self, "effective_resolved_config_hash", _hash(self.effective_resolved_config_hash, path="candidate_asset.effective_resolved_config_hash"))
        if type(self.effective_field_provenance) is not tuple or len(self.effective_field_provenance) != 8:
            raise ContractValidationError("candidate effective provenance must cover eight SR fields")
        paths = tuple(path for path, _ in self.effective_field_provenance)
        if len(set(paths)) != 8 or any(type(path) is not str or type(source) is not str or not source for path, source in self.effective_field_provenance):
            raise ContractValidationError("candidate effective provenance is malformed")
        if type(self.trial_overrides) is not tuple or tuple(item.path for item in self.trial_overrides) != _OVERRIDE_PATHS:
            raise ContractValidationError("candidate trial overrides must cover exactly the two detection fields")
        if type(self.evaluation) is not AssetEvaluation or self.evaluation.source_id != self.source_id:
            raise ContractValidationError("candidate evaluation/source identity mismatch")
        if type(self.structural_gates) is not tuple or any(type(gate) is not StudyGate for gate in self.structural_gates):
            raise ContractValidationError("candidate structural gates are malformed")

    @property
    def metrics(self):
        return self.evaluation.metrics

    def to_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "source_id": self.source_id,
            "inherited_resolved_config_hash": self.inherited_resolved_config_hash,
            "effective_resolved_config_hash": self.effective_resolved_config_hash,
            "effective_field_provenance": [list(pair) for pair in self.effective_field_provenance],
            "trial_overrides": [item.to_payload() for item in self.trial_overrides],
            "replay_id": self.evaluation.replay_id,
            "trace_id": self.evaluation.trace_id,
            "evaluation": self.evaluation.to_payload(),
            "structural_gates": [gate.to_payload() for gate in self.structural_gates],
        }


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate: GeometryCandidate
    assets: tuple[CandidateAssetResult, ...]
    micro: CohortAggregate
    macro: MacroAggregate
    asset_pooled_deltas: tuple[tuple[str, float | None], ...]
    asset_fold_deltas: tuple[tuple[str, str, float | None], ...]
    eligibility_gates: tuple[StudyGate, ...]
    guardrail_diagnostics: tuple[StudyGate, ...]

    def __post_init__(self) -> None:
        if type(self.candidate) is not GeometryCandidate:
            raise ContractValidationError("candidate evaluation candidate is invalid")
        if type(self.assets) is not tuple or tuple(item.asset for item in self.assets) != APPROVED_ASSETS or any(type(item) is not CandidateAssetResult for item in self.assets):
            raise ContractValidationError("candidate assets must be canonical and complete")
        if type(self.micro) is not CohortAggregate or self.micro.view != "micro" or type(self.macro) is not MacroAggregate:
            raise ContractValidationError("candidate aggregates are invalid")
        if type(self.asset_pooled_deltas) is not tuple or tuple(asset for asset, _ in self.asset_pooled_deltas) != APPROVED_ASSETS:
            raise ContractValidationError("asset pooled deltas must be canonical")
        for asset, value in self.asset_pooled_deltas:
            if value is not None:
                _number(value, path=f"asset_pooled_deltas.{asset}")
        if type(self.asset_fold_deltas) is not tuple:
            raise ContractValidationError("asset fold deltas must be a tuple")
        for asset, fold, value in self.asset_fold_deltas:
            _string(asset, path="asset_fold_deltas.asset")
            _string(fold, path="asset_fold_deltas.fold")
            if value is not None:
                _number(value, path="asset_fold_deltas.value")
        for name, value in (("eligibility_gates", self.eligibility_gates), ("guardrail_diagnostics", self.guardrail_diagnostics)):
            if type(value) is not tuple or any(type(item) is not StudyGate for item in value):
                raise ContractValidationError(f"{name} are malformed")

    @property
    def fully_evaluable(self) -> bool:
        # Per-fold sample records are diagnostics.  Only structural gates and
        # the two aggregate sample gates determine candidate eligibility.
        return all(
            gate.passed
            for gate in self.eligibility_gates
            if not gate.name.startswith("diagnostic.")
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_payload(),
            "assets": [item.to_payload() for item in self.assets],
            "micro": self.micro.to_payload(),
            "macro": self.macro.to_payload(),
            "asset_pooled_deltas": [[asset, value] for asset, value in self.asset_pooled_deltas],
            "asset_fold_deltas": [[asset, fold, value] for asset, fold, value in self.asset_fold_deltas],
            "eligibility_gates": [gate.to_payload() for gate in self.eligibility_gates],
            "guardrail_diagnostics": [gate.to_payload() for gate in self.guardrail_diagnostics],
        }


@dataclass(frozen=True)
class CandidateDecision:
    candidate_id: str
    is_baseline: bool
    fully_evaluable: bool
    passes_quality: bool
    passes_guardrails: bool
    passes_stability: bool
    gates: tuple[StudyGate, ...]
    median_asset_delta: float | None
    micro_delta: float | None
    positive_asset_count: int
    worst_asset_delta: float | None
    comparable_asset_fold_count: int
    asset_fold_win_fraction: float | None
    comparable_folds_by_asset: tuple[tuple[str, int], ...]
    neighbor_support_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _hash(self.candidate_id, path="decision.candidate_id"))
        if type(self.is_baseline) is not bool or type(self.fully_evaluable) is not bool or type(self.passes_quality) is not bool or type(self.passes_guardrails) is not bool or type(self.passes_stability) is not bool:
            raise ContractValidationError("decision flags must be booleans")
        if type(self.gates) is not tuple or any(type(item) is not StudyGate for item in self.gates):
            raise ContractValidationError("decision gates are malformed")
        for name in ("median_asset_delta", "micro_delta", "worst_asset_delta", "asset_fold_win_fraction"):
            value = getattr(self, name)
            if value is not None:
                _number(value, path=f"decision.{name}")
        object.__setattr__(self, "positive_asset_count", _integer(self.positive_asset_count, path="decision.positive_asset_count"))
        object.__setattr__(self, "comparable_asset_fold_count", _integer(self.comparable_asset_fold_count, path="decision.comparable_asset_fold_count"))
        if self.asset_fold_win_fraction is not None and not 0 <= self.asset_fold_win_fraction <= 1:
            raise ContractValidationError("decision asset_fold_win_fraction must be in [0,1]")
        if type(self.comparable_folds_by_asset) is not tuple or tuple(asset for asset, _ in self.comparable_folds_by_asset) != APPROVED_ASSETS:
            raise ContractValidationError("decision comparable folds must use canonical assets")
        if type(self.neighbor_support_ids) is not tuple or tuple(sorted(self.neighbor_support_ids)) != self.neighbor_support_ids or len(set(self.neighbor_support_ids)) != len(self.neighbor_support_ids):
            raise ContractValidationError("decision neighbor IDs must be sorted and unique")

    @property
    def passes_all_gates(self) -> bool:
        known_prefixes = _PROMOTION_GATE_PREFIXES + (_DIAGNOSTIC_GATE_PREFIX,)
        if any(not gate.name.startswith(known_prefixes) for gate in self.gates):
            return False
        authoritative = tuple(
            gate for gate in self.gates if gate.name.startswith(_PROMOTION_GATE_PREFIXES)
        )
        return (
            bool(authoritative)
            and self.fully_evaluable
            and self.passes_quality
            and self.passes_guardrails
            and self.passes_stability
            and all(gate.passed for gate in authoritative)
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "is_baseline": self.is_baseline,
            "fully_evaluable": self.fully_evaluable,
            "passes_quality": self.passes_quality,
            "passes_guardrails": self.passes_guardrails,
            "passes_stability": self.passes_stability,
            "passes_all_gates": self.passes_all_gates,
            "gates": [gate.to_payload() for gate in self.gates],
            "median_asset_delta": self.median_asset_delta,
            "micro_delta": self.micro_delta,
            "positive_asset_count": self.positive_asset_count,
            "worst_asset_delta": self.worst_asset_delta,
            "comparable_asset_fold_count": self.comparable_asset_fold_count,
            "asset_fold_win_fraction": self.asset_fold_win_fraction,
            "comparable_folds_by_asset": [list(item) for item in self.comparable_folds_by_asset],
            "neighbor_support_ids": list(self.neighbor_support_ids),
        }


class GeometryDisposition(str, Enum):
    SELECT_GLOBAL_CHALLENGER = "SELECT_GLOBAL_CHALLENGER"
    RETAIN_BASELINE_GEOMETRY = "RETAIN_BASELINE_GEOMETRY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class GeometrySensitivityStudy:
    implementation_commit: str
    config_hash: str
    v17_config_hash: str
    source_bundle_id: str
    v17_evaluation_bundle_id: str
    v17_evaluation_id: str
    frozen_sr_config_hash: str
    frozen_input_hash: str
    candidates: tuple[GeometryCandidate, ...]
    baseline_candidate_id: str
    evaluations: tuple[CandidateEvaluation, ...]
    decisions: tuple[CandidateDecision, ...]
    selected_candidate_id: str | None
    disposition: GeometryDisposition
    study_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "implementation_commit", _commit(self.implementation_commit, path="study.implementation_commit"))
        for name in ("config_hash", "v17_config_hash", "source_bundle_id", "v17_evaluation_bundle_id", "v17_evaluation_id", "frozen_sr_config_hash", "frozen_input_hash"):
            object.__setattr__(self, name, _hash(getattr(self, name), path=f"study.{name}"))
        if type(self.candidates) is not tuple or len(self.candidates) != 9 or any(type(item) is not GeometryCandidate for item in self.candidates):
            raise ContractValidationError("study must contain exactly nine candidates")
        if type(self.evaluations) is not tuple or tuple(item.candidate.candidate_id for item in self.evaluations) != tuple(item.candidate_id for item in self.candidates):
            raise ContractValidationError("study evaluations must follow canonical candidate order")
        if any(type(item) is not CandidateEvaluation for item in self.evaluations):
            raise ContractValidationError("study evaluations are malformed")
        if type(self.decisions) is not tuple or tuple(item.candidate_id for item in self.decisions) != tuple(item.candidate_id for item in self.candidates) or any(type(item) is not CandidateDecision for item in self.decisions):
            raise ContractValidationError("study decisions must follow canonical candidate order")
        object.__setattr__(self, "baseline_candidate_id", _hash(self.baseline_candidate_id, path="study.baseline_candidate_id"))
        if self.baseline_candidate_id != next(item.candidate_id for item in self.candidates if item.baseline):
            raise ContractValidationError("study baseline identity mismatch")
        if self.selected_candidate_id is not None:
            object.__setattr__(self, "selected_candidate_id", _hash(self.selected_candidate_id, path="study.selected_candidate_id"))
            selected = [item for item in self.decisions if item.candidate_id == self.selected_candidate_id]
            if not selected or selected[0].is_baseline or not selected[0].passes_all_gates:
                raise ContractValidationError("study selected candidate is not a passing challenger")
        if type(self.disposition) is not GeometryDisposition:
            raise ContractValidationError("study disposition is invalid")
        passing = [item for item in self.decisions if not item.is_baseline and item.passes_all_gates]
        fully_evaluable = [item for item in self.decisions if not item.is_baseline and item.fully_evaluable]
        if self.disposition is GeometryDisposition.SELECT_GLOBAL_CHALLENGER:
            if self.selected_candidate_id is None or len(passing) == 0:
                raise ContractValidationError("selected disposition requires a passing challenger")
        elif self.selected_candidate_id is not None:
            raise ContractValidationError("non-selected disposition cannot carry a challenger")
        if self.disposition is GeometryDisposition.INSUFFICIENT_EVIDENCE and fully_evaluable:
            raise ContractValidationError("insufficient disposition cannot contain a fully evaluable challenger")
        if self.disposition is GeometryDisposition.RETAIN_BASELINE_GEOMETRY and not fully_evaluable:
            raise ContractValidationError("retain disposition requires a fully evaluable challenger")
        object.__setattr__(self, "study_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "implementation_commit": self.implementation_commit,
            "config_hash": self.config_hash,
            "v17_config_hash": self.v17_config_hash,
            "source_bundle_id": self.source_bundle_id,
            "v17_evaluation_bundle_id": self.v17_evaluation_bundle_id,
            "v17_evaluation_id": self.v17_evaluation_id,
            "frozen_sr_config_hash": self.frozen_sr_config_hash,
            "frozen_input_hash": self.frozen_input_hash,
            "candidates": [item.to_payload() for item in self.candidates],
            "baseline_candidate_id": self.baseline_candidate_id,
            "evaluations": [item.to_payload() for item in self.evaluations],
            "decisions": [item.to_payload() for item in self.decisions],
            "selected_candidate_id": self.selected_candidate_id,
            "disposition": self.disposition.value,
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "study_id": self.study_id}


__all__ = [
    "CandidateAssetResult", "CandidateDecision", "CandidateEvaluation", "GeometryCandidate", "GeometryDisposition",
    "GeometrySensitivityStudy", "PARAMETER_FAMILY", "SCHEMA_VERSION", "StudyGate", "TrialOverride",
]
