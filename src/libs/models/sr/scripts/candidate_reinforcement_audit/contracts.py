"""Immutable ledger, lineage, accounting, and decision contracts for V1.12."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import math
import re
from typing import Any

from libs.models.sr.domain.contracts import (
    ContractValidationError,
    SRStateKey,
    ZoneSide,
    ZoneStatus,
)
from libs.models.sr.domain.identity import deterministic_hash, require_utc, utc_isoformat

from .config import (
    APPROVED_ASSET,
    APPROVED_STAGE,
    APPROVED_TIMEFRAME,
    BARS_SHA256,
    DECISION_CATEGORIES,
    FOLD_NAMES,
    SOURCE_BUNDLE_ID,
    SOURCE_ID,
    UPSTREAM_SOURCE_BUNDLE_ID,
    V10_AUDIT_ID,
    V10_BUNDLE_ID,
    V11_BUNDLE_ID,
    V11_STUDY_ID,
    V19_BUNDLE_ID,
    V19_STUDY_ID,
)


SCHEMA_VERSION = "1.0"
_HASH_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")
_TERMINAL = frozenset({ZoneStatus.BROKEN, ZoneStatus.EXPIRED})
PARITY_CHECKS = (
    "state_identity_payload_each_bar",
    "snapshot_identity_payload_each_bar",
    "event_order_and_payload_each_bar",
    "candidate_order_each_bar",
    "created_zone_ids",
    "terminal_statuses",
    "final_state",
    "checkpoint_resume",
    "canonical_v1_replay",
)


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


def _number(value: Any, *, path: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{path} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{path} must be finite") from exc
    if not math.isfinite(result):
        raise ContractValidationError(f"{path} must be finite")
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{path} must be >= {minimum}")
    return 0.0 if result == 0.0 else result


def _integer(value: Any, *, path: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or type(value) is not int or value < minimum:
        raise ContractValidationError(f"{path} must be an integer >= {minimum}")
    return value


def _timestamp(value: Any, *, path: str) -> datetime:
    try:
        return require_utc(value, field_name=path)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"{path} must be UTC-aware") from exc


def _side(value: Any, *, path: str) -> ZoneSide:
    if type(value) is not ZoneSide:
        raise ContractValidationError(f"{path} must be exactly ZoneSide")
    return value


def _status(value: Any, *, path: str) -> ZoneStatus:
    if type(value) is not ZoneStatus:
        raise ContractValidationError(f"{path} must be exactly ZoneStatus")
    return value


def _optional_hash(value: Any, *, path: str) -> str | None:
    return None if value is None else _hash(value, path=path)


def _state_key_payload(value: SRStateKey) -> dict[str, str]:
    return {"venue": value.venue, "symbol": value.symbol, "timeframe": value.timeframe}


def _state_key(value: Any, *, path: str) -> SRStateKey:
    if type(value) is not SRStateKey:
        raise ContractValidationError(f"{path} must be exactly SRStateKey")
    if value.symbol != APPROVED_ASSET or value.timeframe != APPROVED_TIMEFRAME:
        raise ContractValidationError(f"{path} is outside approved TAOUSDT/1d scope")
    return value


class DecisionCategory(str, Enum):
    CREATED_ZONE = "CREATED_ZONE"
    MATCHED_START_ZONE_SUPPRESSED = "MATCHED_START_ZONE_SUPPRESSED"
    MATCHED_SAME_BATCH_ZONE_SUPPRESSED = "MATCHED_SAME_BATCH_ZONE_SUPPRESSED"
    CAPACITY_SUPPRESSED = "CAPACITY_SUPPRESSED"


class AuditDisposition(str, Enum):
    INVALID_EVIDENCE = "INVALID_EVIDENCE"
    INSUFFICIENT_REINFORCEMENT_EVIDENCE = "INSUFFICIENT_REINFORCEMENT_EVIDENCE"
    READY_FOR_REINFORCEMENT_DETECTOR_CHALLENGER = "READY_FOR_REINFORCEMENT_DETECTOR_CHALLENGER"


@dataclass(frozen=True)
class CandidateDecisionRecord:
    candidate_id: str
    state_key: SRStateKey
    side: ZoneSide
    source: str
    formed_at: datetime
    available_at: datetime
    formed_bar_id: str
    available_bar_id: str
    replay_bar_id: str
    replay_closed_at: datetime
    center: float
    half_width: float
    lower_bound: float
    upper_bound: float
    atr_at_creation: float
    decision: DecisionCategory
    target_zone_id: str | None
    created_zone_id: str | None
    target_seed_candidate_id: str | None
    target_pre_advance_status: ZoneStatus | None
    target_post_advance_status: ZoneStatus | None
    center_distance: float | None
    center_distance_atr: float | None
    merge_threshold_price: float
    merge_distance_atr: float
    active_zone_count_before_capacity: int
    fold: str | None
    eligible_reinforcement: bool
    decision_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _hash(self.candidate_id, path="candidate.candidate_id"))
        object.__setattr__(self, "state_key", _state_key(self.state_key, path="candidate.state_key"))
        object.__setattr__(self, "side", _side(self.side, path="candidate.side"))
        object.__setattr__(self, "source", _string(self.source, path="candidate.source"))
        formed = _timestamp(self.formed_at, path="candidate.formed_at")
        available = _timestamp(self.available_at, path="candidate.available_at")
        replay_closed = _timestamp(self.replay_closed_at, path="candidate.replay_closed_at")
        if available < formed:
            raise ContractValidationError("candidate.available_at must be >= formed_at")
        if available > replay_closed:
            raise ContractValidationError("candidate.available_at cannot be after replay bar close")
        object.__setattr__(self, "formed_at", formed)
        object.__setattr__(self, "available_at", available)
        object.__setattr__(self, "replay_closed_at", replay_closed)
        for name in ("formed_bar_id", "available_bar_id", "replay_bar_id"):
            object.__setattr__(self, name, _string(getattr(self, name), path=f"candidate.{name}"))
        center = _number(self.center, path="candidate.center", minimum=0.0)
        half_width = _number(self.half_width, path="candidate.half_width", minimum=0.0)
        lower = _number(self.lower_bound, path="candidate.lower_bound", minimum=0.0)
        upper = _number(self.upper_bound, path="candidate.upper_bound", minimum=0.0)
        if center <= 0 or lower <= 0 or upper < lower or not lower <= center <= upper:
            raise ContractValidationError("candidate geometry is invalid")
        if lower != center - half_width or upper != center + half_width:
            raise ContractValidationError("candidate geometry bounds do not reconcile")
        object.__setattr__(self, "center", center)
        object.__setattr__(self, "half_width", half_width)
        object.__setattr__(self, "lower_bound", lower)
        object.__setattr__(self, "upper_bound", upper)
        object.__setattr__(self, "atr_at_creation", _number(self.atr_at_creation, path="candidate.atr_at_creation", minimum=0.0))
        if self.atr_at_creation <= 0:
            raise ContractValidationError("candidate.atr_at_creation must be positive")
        if type(self.decision) is not DecisionCategory:
            raise ContractValidationError("candidate.decision must be exactly DecisionCategory")
        target = _optional_hash(self.target_zone_id, path="candidate.target_zone_id")
        created = _optional_hash(self.created_zone_id, path="candidate.created_zone_id")
        seed = _optional_hash(self.target_seed_candidate_id, path="candidate.target_seed_candidate_id")
        object.__setattr__(self, "target_zone_id", target)
        object.__setattr__(self, "created_zone_id", created)
        object.__setattr__(self, "target_seed_candidate_id", seed)
        pre = None if self.target_pre_advance_status is None else _status(self.target_pre_advance_status, path="candidate.target_pre_advance_status")
        post = None if self.target_post_advance_status is None else _status(self.target_post_advance_status, path="candidate.target_post_advance_status")
        object.__setattr__(self, "target_pre_advance_status", pre)
        object.__setattr__(self, "target_post_advance_status", post)
        object.__setattr__(self, "merge_threshold_price", _number(self.merge_threshold_price, path="candidate.merge_threshold_price", minimum=0.0))
        object.__setattr__(self, "merge_distance_atr", _number(self.merge_distance_atr, path="candidate.merge_distance_atr", minimum=0.0))
        if self.merge_threshold_price <= 0 or self.merge_distance_atr <= 0:
            raise ContractValidationError("candidate merge threshold values must be positive")
        if self.merge_threshold_price != self.merge_distance_atr * self.atr_at_creation:
            raise ContractValidationError("candidate merge threshold does not reconcile")
        object.__setattr__(self, "active_zone_count_before_capacity", _integer(self.active_zone_count_before_capacity, path="candidate.active_zone_count_before_capacity"))
        if self.fold is not None:
            fold = _string(self.fold, path="candidate.fold")
            if fold not in FOLD_NAMES:
                raise ContractValidationError("candidate.fold is not approved")
            object.__setattr__(self, "fold", fold)
        if type(self.eligible_reinforcement) is not bool:
            raise ContractValidationError("candidate.eligible_reinforcement must be boolean")
        if self.eligible_reinforcement and self.fold is None:
            raise ContractValidationError("eligible reinforcement must belong to an evaluation fold")
        if self.decision is DecisionCategory.CREATED_ZONE:
            if self.created_zone_id is None or any(value is not None for value in (self.target_zone_id, self.target_seed_candidate_id, self.target_pre_advance_status, self.target_post_advance_status, self.center_distance, self.center_distance_atr)) or self.eligible_reinforcement:
                raise ContractValidationError("created candidate decision fields do not reconcile")
        elif self.decision is DecisionCategory.CAPACITY_SUPPRESSED:
            if self.target_zone_id is not None or self.created_zone_id is not None or self.target_seed_candidate_id is not None or self.target_pre_advance_status is not None or self.target_post_advance_status is not None or self.center_distance is not None or self.center_distance_atr is not None or self.eligible_reinforcement:
                raise ContractValidationError("capacity decision fields do not reconcile")
        elif self.decision is DecisionCategory.MATCHED_START_ZONE_SUPPRESSED:
            if self.target_zone_id is None or self.created_zone_id is not None or self.target_seed_candidate_id is None or self.target_pre_advance_status is None or self.target_post_advance_status is None:
                raise ContractValidationError("start-match decision fields are incomplete")
            if self.center_distance is None or self.center_distance_atr is None:
                raise ContractValidationError("matched candidate distance is missing")
            if self.eligible_reinforcement and self.target_post_advance_status in _TERMINAL:
                raise ContractValidationError("terminal target cannot be eligible reinforcement")
        else:
            if self.target_zone_id is None or self.created_zone_id is not None or self.target_seed_candidate_id is None or self.target_pre_advance_status is not None or self.target_post_advance_status is None or self.eligible_reinforcement:
                raise ContractValidationError("same-batch decision fields do not reconcile")
            if self.center_distance is None or self.center_distance_atr is None:
                raise ContractValidationError("same-batch distance is missing")
        if self.center_distance is None:
            if self.center_distance_atr is not None:
                raise ContractValidationError("center distance ATR requires center distance")
        else:
            distance = _number(self.center_distance, path="candidate.center_distance", minimum=0.0)
            distance_atr = _number(self.center_distance_atr, path="candidate.center_distance_atr", minimum=0.0)
            if abs(distance / self.atr_at_creation - distance_atr) > 1e-12:
                raise ContractValidationError("center distance ATR does not reconcile")
            if distance > self.merge_threshold_price or distance_atr > self.merge_distance_atr:
                raise ContractValidationError("matched candidate is outside the frozen merge threshold")
            object.__setattr__(self, "center_distance", distance)
            object.__setattr__(self, "center_distance_atr", distance_atr)
        object.__setattr__(self, "decision_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "candidate_id": self.candidate_id,
            "state_key": _state_key_payload(self.state_key),
            "side": self.side.value,
            "source": self.source,
            "formed_at": utc_isoformat(self.formed_at),
            "available_at": utc_isoformat(self.available_at),
            "formed_bar_id": self.formed_bar_id,
            "available_bar_id": self.available_bar_id,
            "replay_bar_id": self.replay_bar_id,
            "replay_closed_at": utc_isoformat(self.replay_closed_at),
            "center": self.center,
            "half_width": self.half_width,
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
            "atr_at_creation": self.atr_at_creation,
            "decision": self.decision.value,
            "target_zone_id": self.target_zone_id,
            "created_zone_id": self.created_zone_id,
            "target_seed_candidate_id": self.target_seed_candidate_id,
            "target_pre_advance_status": None if self.target_pre_advance_status is None else self.target_pre_advance_status.value,
            "target_post_advance_status": None if self.target_post_advance_status is None else self.target_post_advance_status.value,
            "center_distance": self.center_distance,
            "center_distance_atr": self.center_distance_atr,
            "merge_threshold_price": self.merge_threshold_price,
            "merge_distance_atr": self.merge_distance_atr,
            "active_zone_count_before_capacity": self.active_zone_count_before_capacity,
            "fold": self.fold,
            "eligible_reinforcement": self.eligible_reinforcement,
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "decision_id": self.decision_id}


@dataclass(frozen=True)
class ZoneSeedLineage:
    zone_id: str
    seed_candidate_id: str
    state_key: SRStateKey
    side: ZoneSide
    formed_at: datetime
    available_at: datetime
    lineage_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "zone_id", _hash(self.zone_id, path="lineage.zone_id"))
        object.__setattr__(self, "seed_candidate_id", _hash(self.seed_candidate_id, path="lineage.seed_candidate_id"))
        object.__setattr__(self, "state_key", _state_key(self.state_key, path="lineage.state_key"))
        object.__setattr__(self, "side", _side(self.side, path="lineage.side"))
        formed = _timestamp(self.formed_at, path="lineage.formed_at")
        available = _timestamp(self.available_at, path="lineage.available_at")
        if available < formed:
            raise ContractValidationError("lineage availability precedes formation")
        object.__setattr__(self, "formed_at", formed)
        object.__setattr__(self, "available_at", available)
        object.__setattr__(self, "lineage_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "zone_id": self.zone_id, "seed_candidate_id": self.seed_candidate_id, "state_key": _state_key_payload(self.state_key), "side": self.side.value, "formed_at": utc_isoformat(self.formed_at), "available_at": utc_isoformat(self.available_at)}

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "lineage_id": self.lineage_id}


def _first_confirmation_by_zone(
    candidates: tuple[CandidateDecisionRecord, ...],
) -> dict[str, CandidateDecisionRecord]:
    confirmations: dict[str, CandidateDecisionRecord] = {}
    ordered = sorted(
        (item for item in candidates if item.eligible_reinforcement),
        key=lambda item: (item.replay_closed_at, item.formed_at, item.available_at, item.candidate_id),
    )
    for item in ordered:
        if item.target_zone_id is None:
            raise ContractValidationError("eligible reinforcement lacks target zone")
        confirmations.setdefault(item.target_zone_id, item)
    return confirmations


@dataclass(frozen=True)
class FoldAccounting:
    fold: str
    candidate_count: int
    created_zone_count: int
    eligible_match_count: int
    unique_reinforced_zone_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "fold", _string(self.fold, path="fold_accounting.fold"))
        if self.fold not in FOLD_NAMES:
            raise ContractValidationError("fold accounting contains unknown fold")
        for name in ("candidate_count", "created_zone_count", "eligible_match_count", "unique_reinforced_zone_count"):
            object.__setattr__(self, name, _integer(getattr(self, name), path=f"fold_accounting.{name}"))
        if self.unique_reinforced_zone_count > self.eligible_match_count:
            raise ContractValidationError("fold unique reinforcement count exceeds eligible matches")

    def to_payload(self) -> dict[str, int | str]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class StatusCount:
    status: ZoneStatus
    count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _status(self.status, path="status_count.status"))
        object.__setattr__(self, "count", _integer(self.count, path="status_count.count"))

    def to_payload(self) -> dict[str, Any]:
        return {"status": self.status.value, "count": self.count}


@dataclass(frozen=True)
class ReinforcementZoneCount:
    zone_id: str
    eligible_match_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "zone_id", _hash(self.zone_id, path="reinforcement.zone_id"))
        object.__setattr__(self, "eligible_match_count", _integer(self.eligible_match_count, path="reinforcement.eligible_match_count", minimum=1))

    def to_payload(self) -> dict[str, Any]:
        return {"zone_id": self.zone_id, "eligible_match_count": self.eligible_match_count}


@dataclass(frozen=True)
class ReplayParity:
    passed: bool
    bar_count: int
    checkpoint_split_index: int
    state_digest: str
    snapshot_digest: str
    event_digest: str
    candidate_digest: str
    checkpoint_state_digest: str
    checkpoint_snapshot_digest: str
    checkpoint_event_digest: str
    checks: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.passed) is not bool or not self.passed:
            raise ContractValidationError("V1.12 replay parity must pass")
        object.__setattr__(self, "bar_count", _integer(self.bar_count, path="parity.bar_count", minimum=1))
        object.__setattr__(self, "checkpoint_split_index", _integer(self.checkpoint_split_index, path="parity.checkpoint_split_index", minimum=1))
        if self.checkpoint_split_index >= self.bar_count:
            raise ContractValidationError("parity checkpoint split must be inside replay")
        for name in ("state_digest", "snapshot_digest", "event_digest", "candidate_digest", "checkpoint_state_digest", "checkpoint_snapshot_digest", "checkpoint_event_digest"):
            object.__setattr__(self, name, _hash(getattr(self, name), path=f"parity.{name}"))
        if self.checks != PARITY_CHECKS:
            raise ContractValidationError("parity checks do not match approved matrix")

    def to_payload(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__ if name != "checks"} | {"checks": list(self.checks)}


@dataclass(frozen=True)
class AuditAccounting:
    source_case_count: int
    total_candidates: int
    created_zone_count: int
    matched_start_zone_suppressed: int
    matched_same_batch_zone_suppressed: int
    capacity_suppressed: int
    eligible_reinforcement_count: int
    unique_reinforced_zone_count: int
    one_reinforcement_zone_count: int
    two_reinforcement_zone_count: int
    three_or_more_reinforcement_zone_count: int
    support_candidate_count: int
    resistance_candidate_count: int
    out_of_fold_candidate_count: int
    unmatched_reconciliation_count: int
    target_post_advance_status_counts: tuple[StatusCount, ...]
    reinforcement_zone_counts: tuple[ReinforcementZoneCount, ...]
    folds: tuple[FoldAccounting, ...]

    def __post_init__(self) -> None:
        for name in ("source_case_count", "total_candidates", "created_zone_count", "matched_start_zone_suppressed", "matched_same_batch_zone_suppressed", "capacity_suppressed", "eligible_reinforcement_count", "unique_reinforced_zone_count", "one_reinforcement_zone_count", "two_reinforcement_zone_count", "three_or_more_reinforcement_zone_count", "support_candidate_count", "resistance_candidate_count", "out_of_fold_candidate_count", "unmatched_reconciliation_count"):
            object.__setattr__(self, name, _integer(getattr(self, name), path=f"accounting.{name}"))
        if self.source_case_count != 36:
            raise ContractValidationError("V1.12 source case count must be 36")
        category_total = self.created_zone_count + self.matched_start_zone_suppressed + self.matched_same_batch_zone_suppressed + self.capacity_suppressed
        if category_total != self.total_candidates:
            raise ContractValidationError("candidate decision categories do not reconcile")
        if self.support_candidate_count + self.resistance_candidate_count != self.total_candidates:
            raise ContractValidationError("candidate side counts do not reconcile")
        if self.out_of_fold_candidate_count > self.total_candidates:
            raise ContractValidationError("out-of-fold count exceeds candidates")
        if self.unmatched_reconciliation_count != 0:
            raise ContractValidationError("candidate reconciliation count must be zero")
        if type(self.target_post_advance_status_counts) is not tuple or tuple(item.status for item in self.target_post_advance_status_counts) != tuple(ZoneStatus):
            raise ContractValidationError("target post-advance status counts are incomplete")
        if type(self.reinforcement_zone_counts) is not tuple:
            raise ContractValidationError("reinforcement zone counts must be a tuple")
        if tuple(item.zone_id for item in self.reinforcement_zone_counts) != tuple(sorted(item.zone_id for item in self.reinforcement_zone_counts)):
            raise ContractValidationError("reinforcement zone counts are not canonical")
        if len({item.zone_id for item in self.reinforcement_zone_counts}) != len(self.reinforcement_zone_counts):
            raise ContractValidationError("reinforcement zones must be unique")
        if len(self.reinforcement_zone_counts) != self.unique_reinforced_zone_count:
            raise ContractValidationError("unique reinforcement count does not reconcile")
        counts = [item.eligible_match_count for item in self.reinforcement_zone_counts]
        if sum(counts) != self.eligible_reinforcement_count:
            raise ContractValidationError("eligible reinforcement count does not reconcile")
        if sum(count == 1 for count in counts) != self.one_reinforcement_zone_count or sum(count == 2 for count in counts) != self.two_reinforcement_zone_count or sum(count >= 3 for count in counts) != self.three_or_more_reinforcement_zone_count:
            raise ContractValidationError("reinforcement multiplicity accounting does not reconcile")
        if type(self.folds) is not tuple or tuple(item.fold for item in self.folds) != FOLD_NAMES:
            raise ContractValidationError("fold accounting does not match frozen order")

    def to_payload(self) -> dict[str, Any]:
        return {name: [item.to_payload() for item in value] if isinstance(value, tuple) else value for name, value in ((name, getattr(self, name)) for name in self.__dataclass_fields__)}


_GATE_SPECS = {
    "readiness.unique_reinforced_zones": ("readiness", 16),
    "readiness.comparable_folds": ("readiness", 4),
    "readiness.minimum_reinforced_zones_per_comparable_fold": ("readiness", 2),
}


@dataclass(frozen=True)
class GateResult:
    name: str
    category: str
    value: int
    threshold: int
    operator: str
    passed: bool
    reason: str

    def __post_init__(self) -> None:
        name = _string(self.name, path="gate.name")
        if name not in _GATE_SPECS:
            raise ContractValidationError("unknown V1.12 gate name")
        category, threshold = _GATE_SPECS[name]
        if type(self.category) is not str or type(self.operator) is not str or type(self.threshold) is not int or self.category != category or self.operator != ">=" or self.threshold != threshold:
            raise ContractValidationError("V1.12 gate schema is not approved")
        object.__setattr__(self, "value", _integer(self.value, path="gate.value"))
        if type(self.passed) is not bool or self.passed != (self.value >= threshold):
            raise ContractValidationError("V1.12 gate passed flag does not match value")
        if type(self.reason) is not str or not self.reason:
            raise ContractValidationError("V1.12 gate reason must be non-empty")

    def to_payload(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class AuditDecision:
    contract_valid: bool
    disposition: AuditDisposition
    gates: tuple[GateResult, ...]
    reason: str

    def __post_init__(self) -> None:
        if type(self.contract_valid) is not bool or type(self.disposition) is not AuditDisposition:
            raise ContractValidationError("V1.12 decision types are invalid")
        if type(self.gates) is not tuple or tuple(item.name for item in self.gates) != tuple(_GATE_SPECS):
            raise ContractValidationError("V1.12 gates do not match exact schema")
        if type(self.reason) is not str or not self.reason:
            raise ContractValidationError("V1.12 decision reason must be non-empty")
        if not self.contract_valid:
            expected = AuditDisposition.INVALID_EVIDENCE
        elif not all(item.passed for item in self.gates):
            expected = AuditDisposition.INSUFFICIENT_REINFORCEMENT_EVIDENCE
        else:
            expected = AuditDisposition.READY_FOR_REINFORCEMENT_DETECTOR_CHALLENGER
        if self.disposition is not expected:
            raise ContractValidationError("V1.12 disposition does not match gate precedence")

    def to_payload(self) -> dict[str, Any]:
        return {"contract_valid": self.contract_valid, "disposition": self.disposition.value, "gates": [item.to_payload() for item in self.gates], "reason": self.reason}


@dataclass(frozen=True)
class CandidateReinforcementAudit:
    implementation_commit: str
    config_hash: str
    v11_bundle_id: str
    v11_study_id: str
    v19_bundle_id: str
    v19_study_id: str
    v10_bundle_id: str
    v10_audit_id: str
    source_bundle_id: str
    upstream_source_bundle_id: str
    source_id: str
    bars_sha256: str
    candidates: tuple[CandidateDecisionRecord, ...]
    lineage: tuple[ZoneSeedLineage, ...]
    accounting: AuditAccounting
    parity: ReplayParity
    decision: AuditDecision
    audit_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "implementation_commit", _commit(self.implementation_commit, path="audit.implementation_commit"))
        object.__setattr__(self, "config_hash", _hash(self.config_hash, path="audit.config_hash"))
        for name, expected in (("v11_bundle_id", V11_BUNDLE_ID), ("v11_study_id", V11_STUDY_ID), ("v19_bundle_id", V19_BUNDLE_ID), ("v19_study_id", V19_STUDY_ID), ("v10_bundle_id", V10_BUNDLE_ID), ("v10_audit_id", V10_AUDIT_ID), ("source_bundle_id", SOURCE_BUNDLE_ID), ("upstream_source_bundle_id", UPSTREAM_SOURCE_BUNDLE_ID), ("source_id", SOURCE_ID), ("bars_sha256", BARS_SHA256)):
            value = _hash(getattr(self, name), path=f"audit.{name}")
            if value != expected:
                raise ContractValidationError(f"audit.{name} is not approved")
            object.__setattr__(self, name, value)
        if type(self.candidates) is not tuple or any(type(item) is not CandidateDecisionRecord for item in self.candidates):
            raise ContractValidationError("audit candidate ledger is invalid")
        if tuple((item.replay_closed_at, item.formed_at, item.available_at, item.candidate_id) for item in self.candidates) != tuple(sorted((item.replay_closed_at, item.formed_at, item.available_at, item.candidate_id) for item in self.candidates)):
            raise ContractValidationError("audit candidate ledger is not canonical")
        if len({item.candidate_id for item in self.candidates}) != len(self.candidates):
            raise ContractValidationError("candidate IDs must be unique")
        if type(self.lineage) is not tuple or any(type(item) is not ZoneSeedLineage for item in self.lineage):
            raise ContractValidationError("audit seed lineage is invalid")
        if tuple(item.zone_id for item in self.lineage) != tuple(sorted(item.zone_id for item in self.lineage)):
            raise ContractValidationError("seed lineage is not canonical")
        if len({item.zone_id for item in self.lineage}) != len(self.lineage) or len({item.seed_candidate_id for item in self.lineage}) != len(self.lineage):
            raise ContractValidationError("seed lineage must be one-to-one")
        by_candidate = {item.candidate_id: item for item in self.candidates}
        by_zone = {item.zone_id: item for item in self.lineage}
        candidate_indices = {item.candidate_id: index for index, item in enumerate(self.candidates)}
        created = tuple(item for item in self.candidates if item.decision is DecisionCategory.CREATED_ZONE)
        if len(created) != len(self.lineage) or any(item.created_zone_id not in by_zone or by_zone[item.created_zone_id].seed_candidate_id != item.candidate_id for item in created):
            raise ContractValidationError("created-zone seed lineage does not reconcile")
        for item in self.candidates:
            if item.decision in {DecisionCategory.MATCHED_START_ZONE_SUPPRESSED, DecisionCategory.MATCHED_SAME_BATCH_ZONE_SUPPRESSED}:
                if item.target_zone_id not in by_zone or item.target_seed_candidate_id not in by_candidate:
                    raise ContractValidationError("matched candidate references unknown lineage")
                target_lineage = by_zone[item.target_zone_id]
                if target_lineage.seed_candidate_id != item.target_seed_candidate_id or target_lineage.state_key != item.state_key or target_lineage.side is not item.side:
                    raise ContractValidationError("matched candidate seed lineage mismatch")
                if item.decision is DecisionCategory.MATCHED_SAME_BATCH_ZONE_SUPPRESSED and candidate_indices[item.target_seed_candidate_id] >= candidate_indices[item.candidate_id]:
                    raise ContractValidationError("same-batch target seed must precede its match")
            if item.eligible_reinforcement:
                seed = by_candidate[item.target_seed_candidate_id]
                if item.candidate_id == seed.candidate_id or item.formed_at <= seed.formed_at or item.available_at <= by_zone[item.target_zone_id].available_at:
                    raise ContractValidationError("eligible reinforcement causality does not reconcile")
        accounting = self.accounting
        category_counts = {category: sum(item.decision.value == category for item in self.candidates) for category in DECISION_CATEGORIES}
        if (accounting.total_candidates, accounting.created_zone_count, accounting.matched_start_zone_suppressed, accounting.matched_same_batch_zone_suppressed, accounting.capacity_suppressed) != (len(self.candidates), category_counts[DECISION_CATEGORIES[0]], category_counts[DECISION_CATEGORIES[1]], category_counts[DECISION_CATEGORIES[2]], category_counts[DECISION_CATEGORIES[3]]):
            raise ContractValidationError("audit candidate category accounting mismatch")
        eligible = tuple(item for item in self.candidates if item.eligible_reinforcement)
        first_confirmations = _first_confirmation_by_zone(self.candidates)
        if accounting.eligible_reinforcement_count != len(eligible) or accounting.unique_reinforced_zone_count != len(first_confirmations):
            raise ContractValidationError("audit reinforcement accounting mismatch")
        if accounting.support_candidate_count != sum(item.side is ZoneSide.SUPPORT for item in self.candidates) or accounting.resistance_candidate_count != sum(item.side is ZoneSide.RESISTANCE for item in self.candidates):
            raise ContractValidationError("audit side accounting mismatch")
        if accounting.out_of_fold_candidate_count != sum(item.fold is None for item in self.candidates):
            raise ContractValidationError("audit fold-boundary accounting mismatch")
        expected_status_counts = tuple(
            sum(item.target_post_advance_status is status for item in self.candidates if item.target_post_advance_status is not None)
            for status in ZoneStatus
        )
        if tuple(item.count for item in accounting.target_post_advance_status_counts) != expected_status_counts:
            raise ContractValidationError("audit target-status accounting mismatch")
        expected_folds = tuple(
            (
                sum(item.fold == fold for item in self.candidates),
                sum(item.fold == fold and item.decision is DecisionCategory.CREATED_ZONE for item in self.candidates),
                sum(item.fold == fold and item.eligible_reinforcement for item in self.candidates),
                sum(item.fold == fold for item in first_confirmations.values()),
            )
            for fold in FOLD_NAMES
        )
        actual_folds = tuple(
            (item.candidate_count, item.created_zone_count, item.eligible_match_count, item.unique_reinforced_zone_count)
            for item in accounting.folds
        )
        if actual_folds != expected_folds:
            raise ContractValidationError("audit fold accounting mismatch")
        if type(self.parity) is not ReplayParity or type(self.decision) is not AuditDecision:
            raise ContractValidationError("audit parity/decision types are invalid")
        object.__setattr__(self, "audit_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "stage": APPROVED_STAGE,
            "implementation_commit": self.implementation_commit,
            "config_hash": self.config_hash,
            "v11_bundle_id": self.v11_bundle_id,
            "v11_study_id": self.v11_study_id,
            "v19_bundle_id": self.v19_bundle_id,
            "v19_study_id": self.v19_study_id,
            "v10_bundle_id": self.v10_bundle_id,
            "v10_audit_id": self.v10_audit_id,
            "source_bundle_id": self.source_bundle_id,
            "upstream_source_bundle_id": self.upstream_source_bundle_id,
            "source_id": self.source_id,
            "bars_sha256": self.bars_sha256,
            "candidates": [item.to_payload() for item in self.candidates],
            "lineage": [item.to_payload() for item in self.lineage],
            "accounting": self.accounting.to_payload(),
            "parity": self.parity.to_payload(),
            "decision": self.decision.to_payload(),
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "audit_id": self.audit_id}


def validate_audit_payload(payload: Any, expected: CandidateReinforcementAudit) -> None:
    if type(payload) is not dict or payload != expected.to_payload():
        raise ContractValidationError("V1.12 audit does not match semantic recomputation")


__all__ = [
    "AuditAccounting", "AuditDecision", "AuditDisposition", "CandidateDecisionRecord",
    "CandidateReinforcementAudit", "DecisionCategory", "FoldAccounting", "GateResult",
    "ReinforcementZoneCount", "ReplayParity", "StatusCount", "ZoneSeedLineage",
    "validate_audit_payload",
]
