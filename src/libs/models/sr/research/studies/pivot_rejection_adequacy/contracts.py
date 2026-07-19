"""Immutable causal records for the SR-V2.1 pivot-rejection study."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import re

from libs.models.sr.domain import CandidateLevel, ContractValidationError, ZoneSide
from libs.models.sr.domain.identity import deterministic_hash, utc_isoformat
from libs.models.sr.research.metrics.first_touch import FirstTouchOutcome

from .config import APPROVED_GATES


_COMMIT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_NAIVE_SOURCE = "prior_close_naive_v2_1"
_GATE_TOPOLOGY = (
    (
        "readiness.completed_pairs",
        "readiness",
        APPROVED_GATES["minimum_completed_pairs"],
    ),
    (
        "readiness.comparable_folds",
        "readiness",
        APPROVED_GATES["minimum_comparable_folds"],
    ),
    (
        "readiness.pairs_per_comparable_fold",
        "readiness",
        APPROVED_GATES["minimum_pairs_per_comparable_fold"],
    ),
    (
        "readiness.naive_controls_per_side_per_comparable_fold",
        "readiness",
        APPROVED_GATES["minimum_completed_naive_controls_per_side_per_comparable_fold"],
    ),
    (
        "utility.pooled_median_paired_excess_quality_atr",
        "utility",
        APPROVED_GATES["minimum_pooled_median_excess_quality_atr"],
    ),
    (
        "utility.positive_comparable_fold_fraction",
        "utility",
        APPROVED_GATES["minimum_positive_comparable_fold_fraction"],
    ),
    (
        "utility.worst_comparable_fold_paired_excess_atr",
        "utility",
        APPROVED_GATES["minimum_worst_comparable_fold_excess_atr"],
    ),
)
_GATE_BY_NAME = {
    name: (category, threshold) for name, category, threshold in _GATE_TOPOLOGY
}
_READINESS_GATE_COUNT = 4


def _string(value: object, *, path: str) -> str:
    if type(value) is not str or not value:
        raise ContractValidationError(f"{path} must be a non-empty string")
    return value


def _integer(value: object, *, path: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ContractValidationError(f"{path} must be an integer >= {minimum}")
    return value


def _finite(value: object, *, path: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{path} must be numeric")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{path} must be finite") from exc
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        raise ContractValidationError(
            f"{path} must be finite"
            if minimum is None
            else f"{path} must be finite and >= {minimum}"
        )
    return 0.0 if number == 0.0 else number


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


class OutcomeStatus(str, Enum):
    OUTSIDE_FOLDS = "OUTSIDE_FOLDS"
    NO_TOUCH = "NO_TOUCH"
    RIGHT_CENSORED = "RIGHT_CENSORED"
    COMPLETED = "COMPLETED"


class PivotRejectionDisposition(str, Enum):
    BEATS_NAIVE_NULL = "PIVOT_REJECTION_BEATS_NAIVE_NULL"
    NOT_BETTER_THAN_NAIVE_NULL = "PIVOT_REJECTION_NOT_BETTER_THAN_NAIVE_NULL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


def _validate_outcome(
    outcome: FirstTouchOutcome | None,
    status: OutcomeStatus,
    *,
    candidate_id: str,
    path: str,
) -> None:
    if status is OutcomeStatus.COMPLETED and (
        type(outcome) is not FirstTouchOutcome or not outcome.completed
    ):
        raise ContractValidationError(
            f"{path} completed status requires completed outcome"
        )
    if status is OutcomeStatus.RIGHT_CENSORED and (
        type(outcome) is not FirstTouchOutcome or not outcome.right_censored
    ):
        raise ContractValidationError(
            f"{path} censored status requires censored outcome"
        )
    if (
        status in {OutcomeStatus.OUTSIDE_FOLDS, OutcomeStatus.NO_TOUCH}
        and outcome is not None
    ):
        raise ContractValidationError(f"{path} non-touch status cannot contain outcome")
    if outcome is not None and outcome.zone_id != candidate_id:
        raise ContractValidationError(f"{path} outcome zone identity mismatch")


@dataclass(frozen=True)
class CandidateCase:
    candidate: CandidateLevel
    confirmation_bar_id: str
    confirmation_index: int
    pivot_index: int
    prior_close: float
    fold: str | None
    status: OutcomeStatus
    outcome: FirstTouchOutcome | None
    zone_width_atr: float

    def __post_init__(self) -> None:
        if (
            type(self.candidate) is not CandidateLevel
            or type(self.status) is not OutcomeStatus
        ):
            raise ContractValidationError("case has invalid candidate or status type")
        object.__setattr__(
            self,
            "confirmation_bar_id",
            _string(self.confirmation_bar_id, path="case.confirmation_bar_id"),
        )
        object.__setattr__(
            self,
            "confirmation_index",
            _integer(self.confirmation_index, path="case.confirmation_index"),
        )
        object.__setattr__(
            self, "pivot_index", _integer(self.pivot_index, path="case.pivot_index")
        )
        if self.pivot_index >= self.confirmation_index:
            raise ContractValidationError("case pivot must precede confirmation")
        object.__setattr__(
            self,
            "prior_close",
            _finite(self.prior_close, path="case.prior_close", minimum=0.0),
        )
        if self.prior_close <= 0.0:
            raise ContractValidationError("case.prior_close must be positive")
        if self.fold is not None:
            object.__setattr__(self, "fold", _string(self.fold, path="case.fold"))
        object.__setattr__(
            self,
            "zone_width_atr",
            _finite(self.zone_width_atr, path="case.zone_width_atr", minimum=0.0),
        )
        if self.zone_width_atr <= 0.0 or (
            (self.status is OutcomeStatus.OUTSIDE_FOLDS) != (self.fold is None)
        ):
            raise ContractValidationError(
                "case fold/status or width does not reconcile"
            )
        _validate_outcome(
            self.outcome,
            self.status,
            candidate_id=self.candidate.candidate_id,
            path="case",
        )

    @property
    def case_id(self) -> str:
        return deterministic_hash(self.causal_identity_payload())

    def causal_identity_payload(self) -> dict[str, object]:
        return {
            "candidate": candidate_payload(self.candidate),
            "confirmation_bar_id": self.confirmation_bar_id,
            "confirmation_index": self.confirmation_index,
            "pivot_index": self.pivot_index,
            "prior_close": self.prior_close,
            "fold": self.fold,
            "zone_width_atr": self.zone_width_atr,
        }

    def to_payload(self) -> dict[str, object]:
        return {
            **self.causal_identity_payload(),
            "status": self.status.value,
            "outcome": None if self.outcome is None else self.outcome.to_payload(),
            "case_id": self.case_id,
        }


@dataclass(frozen=True)
class NaiveControl:
    real_case_id: str
    candidate: CandidateLevel
    confirmation_bar_id: str
    confirmation_index: int
    fold: str
    prior_close: float
    status: OutcomeStatus
    outcome: FirstTouchOutcome | None
    zone_width_atr: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "real_case_id",
            _string(self.real_case_id, path="control.real_case_id"),
        )
        if (
            type(self.candidate) is not CandidateLevel
            or self.candidate.source != _NAIVE_SOURCE
            or type(self.status) is not OutcomeStatus
            or self.status is OutcomeStatus.OUTSIDE_FOLDS
        ):
            raise ContractValidationError("control has invalid candidate/status")
        object.__setattr__(
            self,
            "confirmation_bar_id",
            _string(self.confirmation_bar_id, path="control.confirmation_bar_id"),
        )
        object.__setattr__(
            self,
            "confirmation_index",
            _integer(self.confirmation_index, path="control.confirmation_index"),
        )
        object.__setattr__(self, "fold", _string(self.fold, path="control.fold"))
        object.__setattr__(
            self,
            "prior_close",
            _finite(self.prior_close, path="control.prior_close", minimum=0.0),
        )
        object.__setattr__(
            self,
            "zone_width_atr",
            _finite(self.zone_width_atr, path="control.zone_width_atr", minimum=0.0),
        )
        if (
            self.prior_close <= 0.0
            or self.zone_width_atr <= 0.0
            or self.candidate.geometry.center != self.prior_close
        ):
            raise ContractValidationError(
                "control must be centered on the confirmation prior close"
            )
        _validate_outcome(
            self.outcome,
            self.status,
            candidate_id=self.candidate.candidate_id,
            path="control",
        )

    @property
    def control_id(self) -> str:
        return deterministic_hash(self.causal_identity_payload())

    def causal_identity_payload(self) -> dict[str, object]:
        return {
            "real_case_id": self.real_case_id,
            "candidate": candidate_payload(self.candidate),
            "confirmation_bar_id": self.confirmation_bar_id,
            "confirmation_index": self.confirmation_index,
            "fold": self.fold,
            "prior_close": self.prior_close,
            "zone_width_atr": self.zone_width_atr,
        }

    def to_payload(self) -> dict[str, object]:
        return {
            **self.causal_identity_payload(),
            "status": self.status.value,
            "outcome": None if self.outcome is None else self.outcome.to_payload(),
            "control_id": self.control_id,
        }


@dataclass(frozen=True)
class PairedOutcome:
    real_case_id: str
    control_id: str
    candidate_id: str
    fold: str
    side: ZoneSide
    paired_excess_quality_atr: float

    def __post_init__(self) -> None:
        for name in ("real_case_id", "control_id", "candidate_id", "fold"):
            object.__setattr__(
                self, name, _string(getattr(self, name), path=f"pair.{name}")
            )
        if type(self.side) is not ZoneSide:
            raise ContractValidationError("pair.side must be exactly ZoneSide")
        object.__setattr__(
            self,
            "paired_excess_quality_atr",
            _finite(
                self.paired_excess_quality_atr, path="pair.paired_excess_quality_atr"
            ),
        )

    @property
    def pair_id(self) -> str:
        return deterministic_hash(
            {
                "real_case_id": self.real_case_id,
                "control_id": self.control_id,
                "candidate_id": self.candidate_id,
                "fold": self.fold,
                "side": self.side.value,
            }
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "real_case_id": self.real_case_id,
            "control_id": self.control_id,
            "candidate_id": self.candidate_id,
            "fold": self.fold,
            "side": self.side.value,
            "paired_excess_quality_atr": self.paired_excess_quality_atr,
            "pair_id": self.pair_id,
        }


@dataclass(frozen=True)
class FoldMetrics:
    fold: str
    completed_real_count: int
    support_control_count: int
    resistance_control_count: int
    completed_pair_count: int
    comparable: bool
    median_paired_excess_quality_atr: float | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "fold", _string(self.fold, path="fold_metrics.fold"))
        for name in (
            "completed_real_count",
            "support_control_count",
            "resistance_control_count",
            "completed_pair_count",
        ):
            object.__setattr__(
                self, name, _integer(getattr(self, name), path=f"fold_metrics.{name}")
            )
        if type(self.comparable) is not bool:
            raise ContractValidationError("fold_metrics.comparable must be boolean")
        if self.median_paired_excess_quality_atr is not None:
            object.__setattr__(
                self,
                "median_paired_excess_quality_atr",
                _finite(
                    self.median_paired_excess_quality_atr,
                    path="fold_metrics.median_paired_excess_quality_atr",
                ),
            )
        if self.comparable != (self.median_paired_excess_quality_atr is not None):
            raise ContractValidationError(
                "fold metric comparability does not reconcile"
            )

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
        expected = _GATE_BY_NAME.get(self.name)
        if expected is None or self.category != expected[0] or self.operator != ">=":
            raise ContractValidationError("gate name/category/operator is unsupported")
        if self.value is not None:
            object.__setattr__(self, "value", _finite(self.value, path="gate.value"))
        object.__setattr__(
            self, "threshold", _finite(self.threshold, path="gate.threshold")
        )
        if self.threshold != expected[1]:
            raise ContractValidationError(
                "gate threshold is not the approved V2.1 value"
            )
        if type(self.passed) is not bool or self.passed != (
            self.value is not None and self.value >= self.threshold
        ):
            raise ContractValidationError("gate.passed does not match value")

    def to_payload(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class Decision:
    disposition: PivotRejectionDisposition
    gates: tuple[GateResult, ...]
    reason: str

    def __post_init__(self) -> None:
        if (
            type(self.disposition) is not PivotRejectionDisposition
            or type(self.gates) is not tuple
            or not self.gates
            or any(type(item) is not GateResult for item in self.gates)
            or len({item.name for item in self.gates}) != len(self.gates)
        ):
            raise ContractValidationError("decision has invalid disposition or gates")
        if tuple(item.name for item in self.gates) != tuple(
            name for name, _, _ in _GATE_TOPOLOGY
        ):
            raise ContractValidationError(
                "decision gate topology is incomplete or unordered"
            )
        reason = _string(self.reason, path="decision.reason")
        readiness = self.gates[:_READINESS_GATE_COUNT]
        utility = self.gates[_READINESS_GATE_COUNT:]
        if any(not item.passed for item in readiness):
            expected_disposition = PivotRejectionDisposition.INSUFFICIENT_EVIDENCE
            expected_reason = "readiness gates failed"
        elif all(item.passed for item in utility):
            expected_disposition = PivotRejectionDisposition.BEATS_NAIVE_NULL
            expected_reason = "all utility gates passed after readiness"
        else:
            expected_disposition = PivotRejectionDisposition.NOT_BETTER_THAN_NAIVE_NULL
            expected_reason = "one or more utility gates failed after readiness"
        if self.disposition is not expected_disposition or reason != expected_reason:
            raise ContractValidationError(
                "decision disposition/reason does not reconcile to gates"
            )
        object.__setattr__(self, "reason", reason)

    def to_payload(self) -> dict[str, object]:
        return {
            "disposition": self.disposition.value,
            "gates": [item.to_payload() for item in self.gates],
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PivotRejectionStudy:
    implementation_commit: str
    config_hash: str
    source_bundle_id: str
    source_capsule_bundle_id: str
    source_id: str
    cases: tuple[CandidateCase, ...]
    controls: tuple[NaiveControl, ...]
    pairs: tuple[PairedOutcome, ...]
    fold_metrics: tuple[FoldMetrics, ...]
    pooled_median_paired_excess_quality_atr: float | None
    positive_comparable_fold_fraction: float | None
    worst_comparable_fold_paired_excess_atr: float | None
    decision: Decision
    study_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "implementation_commit",
            _string(self.implementation_commit, path="study.implementation_commit"),
        )
        if _COMMIT_RE.fullmatch(self.implementation_commit) is None:
            raise ContractValidationError(
                "study.implementation_commit must be a lowercase git SHA"
            )
        for name in (
            "config_hash",
            "source_bundle_id",
            "source_capsule_bundle_id",
            "source_id",
        ):
            value = _string(getattr(self, name), path=f"study.{name}")
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ContractValidationError(f"study.{name} must be lowercase SHA-256")
        if (
            type(self.cases) is not tuple
            or any(type(item) is not CandidateCase for item in self.cases)
            or type(self.controls) is not tuple
            or any(type(item) is not NaiveControl for item in self.controls)
            or type(self.pairs) is not tuple
            or any(type(item) is not PairedOutcome for item in self.pairs)
            or type(self.fold_metrics) is not tuple
            or any(type(item) is not FoldMetrics for item in self.fold_metrics)
            or type(self.decision) is not Decision
        ):
            raise ContractValidationError("study records have invalid types")
        if len({item.case_id for item in self.cases}) != len(self.cases) or len(
            {item.control_id for item in self.controls}
        ) != len(self.controls):
            raise ContractValidationError(
                "study case/control identities must be unique"
            )
        for name in (
            "pooled_median_paired_excess_quality_atr",
            "positive_comparable_fold_fraction",
            "worst_comparable_fold_paired_excess_atr",
        ):
            if getattr(self, name) is not None:
                object.__setattr__(
                    self, name, _finite(getattr(self, name), path=f"study.{name}")
                )
        object.__setattr__(
            self, "study_id", deterministic_hash(self.identity_payload())
        )

    def casebook_payload(self) -> dict[str, object]:
        return {
            "cases": [item.to_payload() for item in self.cases],
            "controls": [item.to_payload() for item in self.controls],
            "pairs": [item.to_payload() for item in self.pairs],
        }

    def identity_payload(self) -> dict[str, object]:
        return {
            "implementation_commit": self.implementation_commit,
            "config_hash": self.config_hash,
            "source_bundle_id": self.source_bundle_id,
            "source_capsule_bundle_id": self.source_capsule_bundle_id,
            "source_id": self.source_id,
            "casebook_id": deterministic_hash(self.casebook_payload()),
            "fold_metrics": [item.to_payload() for item in self.fold_metrics],
            "pooled_median_paired_excess_quality_atr": self.pooled_median_paired_excess_quality_atr,
            "positive_comparable_fold_fraction": self.positive_comparable_fold_fraction,
            "worst_comparable_fold_paired_excess_atr": self.worst_comparable_fold_paired_excess_atr,
            "decision": self.decision.to_payload(),
        }

    def to_payload(self) -> dict[str, object]:
        return {**self.identity_payload(), "study_id": self.study_id}


__all__ = [
    "CandidateCase",
    "Decision",
    "FoldMetrics",
    "GateResult",
    "NaiveControl",
    "OutcomeStatus",
    "PairedOutcome",
    "PivotRejectionDisposition",
    "PivotRejectionStudy",
    "candidate_payload",
]
