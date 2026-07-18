"""Immutable result contracts for the SR-V2.0 displacement-origin study."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import re

from libs.models.sr.domain import CandidateLevel, ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash, utc_isoformat
from libs.models.sr.research.evidence.baseline_adequacy.contracts import ControlOutcome
from libs.models.sr.research.metrics.first_touch import FirstTouchOutcome


class OutcomeStatus(str, Enum):
    OUTSIDE_FOLDS = "OUTSIDE_FOLDS"
    NO_TOUCH = "NO_TOUCH"
    RIGHT_CENSORED = "RIGHT_CENSORED"
    COMPLETED = "COMPLETED"


class DisplacementOriginDisposition(str, Enum):
    BEATS_NAIVE_NULL = "DISPLACEMENT_ORIGIN_BEATS_NAIVE_NULL"
    NOT_BETTER_THAN_NAIVE_NULL = "DISPLACEMENT_ORIGIN_NOT_BETTER_THAN_NAIVE_NULL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


_COMMIT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def _finite(value: object, *, path: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{path} must be numeric")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{path} must be finite") from exc
    if not math.isfinite(number):
        raise ContractValidationError(f"{path} must be finite")
    if minimum is not None and number < minimum:
        raise ContractValidationError(f"{path} must be >= {minimum}")
    return 0.0 if number == 0.0 else number


def _integer(value: object, *, path: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ContractValidationError(f"{path} must be an integer >= {minimum}")
    return value


def _string(value: object, *, path: str) -> str:
    if type(value) is not str or not value:
        raise ContractValidationError(f"{path} must be a non-empty string")
    return value


def candidate_payload(candidate: CandidateLevel) -> dict[str, object]:
    if type(candidate) is not CandidateLevel:
        raise ContractValidationError("candidate must be exactly CandidateLevel")
    return {
        "candidate_id": candidate.candidate_id,
        "state_key": {
            "venue": candidate.state_key.venue,
            "symbol": candidate.state_key.symbol,
            "timeframe": candidate.state_key.timeframe,
        },
        "side": candidate.side.value,
        "geometry": {
            "center": candidate.geometry.center,
            "half_width": candidate.geometry.half_width,
            "lower_bound": candidate.geometry.lower_bound,
            "upper_bound": candidate.geometry.upper_bound,
        },
        "source": candidate.source,
        "formed_at": utc_isoformat(candidate.formed_at),
        "available_at": utc_isoformat(candidate.available_at),
        "atr_at_creation": candidate.atr_at_creation,
    }


@dataclass(frozen=True)
class CandidateCase:
    candidate: CandidateLevel
    confirmation_bar_id: str
    confirmation_index: int
    base_distance_bars: int
    fold: str | None
    status: OutcomeStatus
    outcome: FirstTouchOutcome | None
    zone_width_atr: float

    def __post_init__(self) -> None:
        if type(self.candidate) is not CandidateLevel:
            raise ContractValidationError("case.candidate must be exactly CandidateLevel")
        object.__setattr__(self, "confirmation_bar_id", _string(self.confirmation_bar_id, path="case.confirmation_bar_id"))
        object.__setattr__(self, "confirmation_index", _integer(self.confirmation_index, path="case.confirmation_index"))
        object.__setattr__(self, "base_distance_bars", _integer(self.base_distance_bars, path="case.base_distance_bars", minimum=1))
        if self.fold is not None:
            object.__setattr__(self, "fold", _string(self.fold, path="case.fold"))
        if type(self.status) is not OutcomeStatus:
            raise ContractValidationError("case.status must be exactly OutcomeStatus")
        object.__setattr__(self, "zone_width_atr", _finite(self.zone_width_atr, path="case.zone_width_atr", minimum=0.0))
        if self.zone_width_atr <= 0.0:
            raise ContractValidationError("case.zone_width_atr must be positive")
        if self.status is OutcomeStatus.COMPLETED:
            if type(self.outcome) is not FirstTouchOutcome or not self.outcome.completed:
                raise ContractValidationError("completed case requires completed FirstTouchOutcome")
        elif self.status is OutcomeStatus.RIGHT_CENSORED:
            if type(self.outcome) is not FirstTouchOutcome or not self.outcome.right_censored:
                raise ContractValidationError("right-censored case requires censored FirstTouchOutcome")
        elif self.outcome is not None:
            raise ContractValidationError("non-touch case must not contain an outcome")
        if self.status is OutcomeStatus.OUTSIDE_FOLDS and self.fold is not None:
            raise ContractValidationError("outside-fold case cannot name a fold")
        if self.status is not OutcomeStatus.OUTSIDE_FOLDS and self.fold is None:
            raise ContractValidationError("in-fold case requires a fold")
        if self.outcome is not None and self.outcome.zone_id != self.candidate.candidate_id:
            raise ContractValidationError("case outcome zone_id does not match candidate")

    @property
    def case_id(self) -> str:
        return deterministic_hash(self.identity_payload())

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate": candidate_payload(self.candidate),
            "confirmation_bar_id": self.confirmation_bar_id,
            "confirmation_index": self.confirmation_index,
            "base_distance_bars": self.base_distance_bars,
            "fold": self.fold,
            "status": self.status.value,
            "outcome": None if self.outcome is None else self.outcome.to_payload(),
            "zone_width_atr": self.zone_width_atr,
        }

    def to_payload(self) -> dict[str, object]:
        return {**self.identity_payload(), "case_id": self.case_id}


@dataclass(frozen=True)
class MatchedControl:
    real_case_id: str
    candidate_id: str
    zone_width_atr: float
    outcome: ControlOutcome

    def __post_init__(self) -> None:
        object.__setattr__(self, "real_case_id", _string(self.real_case_id, path="control.real_case_id"))
        object.__setattr__(self, "candidate_id", _string(self.candidate_id, path="control.candidate_id"))
        object.__setattr__(self, "zone_width_atr", _finite(self.zone_width_atr, path="control.zone_width_atr", minimum=0.0))
        if self.zone_width_atr <= 0.0:
            raise ContractValidationError("control.zone_width_atr must be positive")
        if type(self.outcome) is not ControlOutcome:
            raise ContractValidationError("control.outcome must be exactly ControlOutcome")

    def to_payload(self) -> dict[str, object]:
        return {
            "real_case_id": self.real_case_id,
            "candidate_id": self.candidate_id,
            "zone_width_atr": self.zone_width_atr,
            "outcome": self.outcome.to_payload(),
        }


@dataclass(frozen=True)
class FoldMetrics:
    fold: str
    completed_real_count: int
    support_control_count: int
    resistance_control_count: int
    comparable: bool
    median_excess_quality_atr: float | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "fold", _string(self.fold, path="fold_metrics.fold"))
        for name in ("completed_real_count", "support_control_count", "resistance_control_count"):
            object.__setattr__(self, name, _integer(getattr(self, name), path=f"fold_metrics.{name}"))
        if type(self.comparable) is not bool:
            raise ContractValidationError("fold_metrics.comparable must be boolean")
        if self.median_excess_quality_atr is not None:
            object.__setattr__(self, "median_excess_quality_atr", _finite(self.median_excess_quality_atr, path="fold_metrics.median_excess_quality_atr"))
        if self.comparable != (self.median_excess_quality_atr is not None):
            raise ContractValidationError("fold metric comparability and median do not reconcile")

    def to_payload(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class GateResult:
    name: str
    category: str
    value: float | int | None
    threshold: float | int
    operator: str
    passed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _string(self.name, path="gate.name"))
        if self.category not in {"readiness", "utility"}:
            raise ContractValidationError("gate.category is unknown")
        if self.value is not None:
            object.__setattr__(self, "value", _finite(self.value, path="gate.value"))
        object.__setattr__(self, "threshold", _finite(self.threshold, path="gate.threshold"))
        if self.operator not in {">=", "=="}:
            raise ContractValidationError("gate.operator is unsupported")
        if type(self.passed) is not bool:
            raise ContractValidationError("gate.passed must be boolean")
        derived = self.value is not None and (
            self.value >= self.threshold if self.operator == ">=" else self.value == self.threshold
        )
        if self.passed != derived:
            raise ContractValidationError("gate.passed does not match its value and threshold")

    def to_payload(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class Decision:
    disposition: DisplacementOriginDisposition
    gates: tuple[GateResult, ...]
    reason: str

    def __post_init__(self) -> None:
        if type(self.disposition) is not DisplacementOriginDisposition:
            raise ContractValidationError("decision.disposition must be exactly DisplacementOriginDisposition")
        if type(self.gates) is not tuple or not self.gates or any(type(item) is not GateResult for item in self.gates):
            raise ContractValidationError("decision.gates must be a non-empty GateResult tuple")
        if len({item.name for item in self.gates}) != len(self.gates):
            raise ContractValidationError("decision.gates must have unique names")
        object.__setattr__(self, "reason", _string(self.reason, path="decision.reason"))

    def to_payload(self) -> dict[str, object]:
        return {"disposition": self.disposition.value, "gates": [item.to_payload() for item in self.gates], "reason": self.reason}


@dataclass(frozen=True)
class DisplacementOriginStudy:
    implementation_commit: str
    config_hash: str
    source_bundle_id: str
    source_id: str
    cases: tuple[CandidateCase, ...]
    controls: tuple[MatchedControl, ...]
    fold_metrics: tuple[FoldMetrics, ...]
    pooled_median_excess_quality_atr: float | None
    positive_comparable_fold_fraction: float | None
    worst_comparable_fold_excess_atr: float | None
    decision: Decision
    study_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "implementation_commit", _string(self.implementation_commit, path="study.implementation_commit"))
        if _COMMIT_RE.fullmatch(self.implementation_commit) is None:
            raise ContractValidationError("study.implementation_commit must be a lowercase git SHA")
        for name in ("config_hash", "source_bundle_id", "source_id"):
            value = _string(getattr(self, name), path=f"study.{name}")
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ContractValidationError(f"study.{name} must be lowercase SHA-256")
            object.__setattr__(self, name, value)
        if type(self.cases) is not tuple or any(type(item) is not CandidateCase for item in self.cases):
            raise ContractValidationError("study.cases must be a CandidateCase tuple")
        if len({item.case_id for item in self.cases}) != len(self.cases):
            raise ContractValidationError("study cases must be unique")
        if type(self.controls) is not tuple or any(type(item) is not MatchedControl for item in self.controls):
            raise ContractValidationError("study.controls must be a MatchedControl tuple")
        if type(self.fold_metrics) is not tuple or any(type(item) is not FoldMetrics for item in self.fold_metrics):
            raise ContractValidationError("study.fold_metrics must be a FoldMetrics tuple")
        if len({item.fold for item in self.fold_metrics}) != len(self.fold_metrics):
            raise ContractValidationError("study fold metrics must be unique")
        for name in ("pooled_median_excess_quality_atr", "positive_comparable_fold_fraction", "worst_comparable_fold_excess_atr"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _finite(value, path=f"study.{name}"))
        if type(self.decision) is not Decision:
            raise ContractValidationError("study.decision must be exactly Decision")
        object.__setattr__(self, "study_id", deterministic_hash(self.identity_payload()))

    @property
    def completed_cases(self) -> tuple[CandidateCase, ...]:
        return tuple(item for item in self.cases if item.status is OutcomeStatus.COMPLETED)

    def casebook_payload(self) -> dict[str, object]:
        return {
            "cases": [item.to_payload() for item in self.cases],
            "controls": [item.to_payload() for item in self.controls],
        }

    def identity_payload(self) -> dict[str, object]:
        return {
            "implementation_commit": self.implementation_commit,
            "config_hash": self.config_hash,
            "source_bundle_id": self.source_bundle_id,
            "source_id": self.source_id,
            "casebook_id": deterministic_hash(self.casebook_payload()),
            "fold_metrics": [item.to_payload() for item in self.fold_metrics],
            "pooled_median_excess_quality_atr": self.pooled_median_excess_quality_atr,
            "positive_comparable_fold_fraction": self.positive_comparable_fold_fraction,
            "worst_comparable_fold_excess_atr": self.worst_comparable_fold_excess_atr,
            "decision": self.decision.to_payload(),
        }

    def to_payload(self) -> dict[str, object]:
        return {**self.identity_payload(), "study_id": self.study_id}


__all__ = [
    "CandidateCase",
    "Decision",
    "DisplacementOriginDisposition",
    "DisplacementOriginStudy",
    "FoldMetrics",
    "GateResult",
    "MatchedControl",
    "OutcomeStatus",
    "candidate_payload",
]
