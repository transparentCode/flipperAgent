"""Explicit in-memory state ownership for the offline decision runtime.

The state store is deliberately small.  It owns only lane-scoped model state;
input-reader progress, lane publication watermarks, and durable checkpoints are
outside D6.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

from apps.decision_app.contracts import CommitDisposition
from libs.contracts.decision import (
    FrozenMapping,
    ModelState,
    freeze_model_state,
    require_utc,
)

BindingRuntimeHealth = Literal["WARMING", "LIVE", "DEGRADED", "INVALID"]


def _require_non_empty(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _normalize_ids(values: Sequence[str], *, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} must be a sequence of strings")
    normalized = tuple(
        _require_non_empty(value, field_name=field_name) for value in values
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicates")
    return tuple(sorted(normalized))


@dataclass(frozen=True, slots=True, kw_only=True)
class LaneExecutionIdentity:
    """All material D2-D5 inputs that identify a state store."""

    lane_id: str
    effective_lane_revision: str
    feature_plan_fingerprint: str
    data_plan_fingerprint: str

    def __post_init__(self) -> None:
        for field_name in (
            "lane_id",
            "effective_lane_revision",
            "feature_plan_fingerprint",
            "data_plan_fingerprint",
        ):
            _require_non_empty(getattr(self, field_name), field_name=field_name)


@dataclass(frozen=True, slots=True, kw_only=True)
class BindingRuntimeState:
    """One binding's committed state and health."""

    binding_id: str
    health: BindingRuntimeHealth
    committed_market_as_of: datetime | None = None
    committed_state: ModelState = None
    last_failure_reason: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.binding_id, field_name="binding_id")
        if self.health not in {"WARMING", "LIVE", "DEGRADED", "INVALID"}:
            raise ValueError("binding health is not supported")
        if self.committed_market_as_of is not None:
            require_utc(
                self.committed_market_as_of,
                field_name="committed_market_as_of",
            )
        if self.last_failure_reason is not None:
            _require_non_empty(self.last_failure_reason, field_name="failure reason")
        object.__setattr__(
            self, "committed_state", freeze_model_state(self.committed_state)
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PreparedStateTransition:
    """An uncommitted state proposal tied to its exact base record."""

    identity: LaneExecutionIdentity
    binding_id: str
    market_as_of: datetime
    base_state_record: BindingRuntimeState
    proposed_next_state: ModelState

    def __post_init__(self) -> None:
        if not isinstance(self.identity, LaneExecutionIdentity):
            raise TypeError("identity must be LaneExecutionIdentity")
        _require_non_empty(self.binding_id, field_name="binding_id")
        require_utc(self.market_as_of, field_name="market_as_of")
        if not isinstance(self.base_state_record, BindingRuntimeState):
            raise TypeError("base_state_record must be BindingRuntimeState")
        if self.base_state_record.binding_id != self.binding_id:
            raise ValueError("transition binding_id must match base state record")
        object.__setattr__(
            self,
            "proposed_next_state",
            freeze_model_state(self.proposed_next_state),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class StateCommitReceipt:
    """Evidence returned by an explicitly authorized in-memory commit."""

    identity: LaneExecutionIdentity
    market_as_of: datetime
    disposition: CommitDisposition
    committed_binding_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.identity, LaneExecutionIdentity):
            raise TypeError("identity must be LaneExecutionIdentity")
        require_utc(self.market_as_of, field_name="market_as_of")
        if self.disposition not in {"published", "no_signal"}:
            raise ValueError("disposition must be published or no_signal")
        object.__setattr__(
            self,
            "committed_binding_ids",
            _normalize_ids(
                self.committed_binding_ids,
                field_name="committed_binding_ids",
            ),
        )


class LaneStateStore:
    """Mutable, single-process state store for one execution identity."""

    __slots__ = ("_identity", "_records", "_stateful_binding_ids")

    def __init__(
        self,
        identity: LaneExecutionIdentity,
        stateful_binding_ids: Sequence[str],
    ) -> None:
        if not isinstance(identity, LaneExecutionIdentity):
            raise TypeError("identity must be LaneExecutionIdentity")
        normalized_ids = _normalize_ids(
            stateful_binding_ids,
            field_name="stateful_binding_ids",
        )
        self._identity = identity
        self._stateful_binding_ids = normalized_ids
        self._records = {
            binding_id: BindingRuntimeState(
                binding_id=binding_id,
                health="WARMING",
            )
            for binding_id in normalized_ids
        }

    @property
    def identity(self) -> LaneExecutionIdentity:
        return self._identity

    @property
    def stateful_binding_ids(self) -> tuple[str, ...]:
        return self._stateful_binding_ids

    @property
    def records(self) -> Mapping[str, BindingRuntimeState]:
        return FrozenMapping(dict(self._records))

    def assert_identity(self, identity: LaneExecutionIdentity) -> None:
        if identity != self._identity:
            raise ValueError("state store execution identity does not match")

    def get(self, binding_id: str) -> BindingRuntimeState:
        _require_non_empty(binding_id, field_name="binding_id")
        try:
            return self._records[binding_id]
        except KeyError as exc:
            raise KeyError(f"unknown stateful binding: {binding_id}") from exc

    def mark_health(
        self,
        binding_id: str,
        health: BindingRuntimeHealth,
        *,
        reason: str | None = None,
    ) -> BindingRuntimeState:
        current = self.get(binding_id)
        updated = replace(
            current,
            health=health,
            last_failure_reason=reason,
        )
        self._records[binding_id] = updated
        return updated

    def commit(
        self,
        identity: LaneExecutionIdentity,
        market_as_of: datetime,
        transitions: Mapping[str, PreparedStateTransition],
        disposition: CommitDisposition,
    ) -> StateCommitReceipt:
        """Atomically apply all stateful transitions after full validation."""

        self.assert_identity(identity)
        require_utc(market_as_of, field_name="market_as_of")
        if disposition not in {"published", "no_signal"}:
            raise ValueError("disposition must be published or no_signal")
        if not isinstance(transitions, Mapping):
            raise TypeError("transitions must be a mapping")
        normalized = dict(transitions)
        if set(normalized) != set(self._stateful_binding_ids):
            raise ValueError("commit transitions must cover every stateful binding")

        for binding_id in self._stateful_binding_ids:
            transition = normalized[binding_id]
            if not isinstance(transition, PreparedStateTransition):
                raise TypeError(
                    "transitions must contain PreparedStateTransition values"
                )
            if transition.binding_id != binding_id:
                raise ValueError("transition map key must match binding_id")
            if transition.identity != identity:
                raise ValueError("transition identity does not match state store")
            if transition.market_as_of != market_as_of:
                raise ValueError("transition market_as_of must match commit cutoff")
            current = self._records[binding_id]
            if current != transition.base_state_record:
                raise ValueError("prepared transition base state is stale")
            if (
                current.committed_market_as_of is not None
                and current.committed_market_as_of >= market_as_of
            ):
                raise ValueError("stateful binding cutoff must advance strictly")

        updated = {
            binding_id: replace(
                self._records[binding_id],
                health="LIVE",
                committed_market_as_of=market_as_of,
                committed_state=normalized[binding_id].proposed_next_state,
                last_failure_reason=None,
            )
            for binding_id in self._stateful_binding_ids
        }
        self._records.update(updated)
        return StateCommitReceipt(
            identity=identity,
            market_as_of=market_as_of,
            disposition=disposition,
            committed_binding_ids=self._stateful_binding_ids,
        )

    def abort(
        self,
        identity: LaneExecutionIdentity,
        transitions: Mapping[str, PreparedStateTransition],
        reason: str,
    ) -> None:
        """Discard proposals and degrade only transition-bearing bindings."""

        self.assert_identity(identity)
        _require_non_empty(reason, field_name="abort reason")
        if not isinstance(transitions, Mapping):
            raise TypeError("transitions must be a mapping")
        normalized = dict(transitions)
        for binding_id, transition in normalized.items():
            if binding_id not in self._records:
                raise ValueError("abort contains an unknown stateful binding")
            if not isinstance(transition, PreparedStateTransition):
                raise TypeError(
                    "transitions must contain PreparedStateTransition values"
                )
            if transition.binding_id != binding_id:
                raise ValueError("transition map key must match binding_id")
            if transition.identity != identity:
                raise ValueError("transition identity does not match state store")
            if self._records[binding_id] != transition.base_state_record:
                raise ValueError("prepared transition base state is stale")

        for binding_id in normalized:
            current = self._records[binding_id]
            self._records[binding_id] = replace(
                current,
                health="DEGRADED",
                last_failure_reason=reason,
            )

    def install_rewarm(
        self,
        identity: LaneExecutionIdentity,
        records: Mapping[str, BindingRuntimeState],
    ) -> None:
        """Atomically install a fully reconstructed shadow state."""

        self.assert_identity(identity)
        if not isinstance(records, Mapping):
            raise TypeError("rewarm records must be a mapping")
        normalized = dict(records)
        if set(normalized) != set(self._stateful_binding_ids):
            raise ValueError("rewarm records must cover every stateful binding")
        for binding_id in self._stateful_binding_ids:
            record = normalized[binding_id]
            if not isinstance(record, BindingRuntimeState):
                raise TypeError(
                    "rewarm records must contain BindingRuntimeState values"
                )
            if record.binding_id != binding_id:
                raise ValueError("rewarm record map key must match binding_id")
            if record.health != "LIVE":
                raise ValueError("rewarm records must be LIVE")
            if record.committed_market_as_of is None:
                raise ValueError("rewarm records require a committed cutoff")

        cutoffs = {
            normalized[binding_id].committed_market_as_of
            for binding_id in self._stateful_binding_ids
        }
        if len(cutoffs) != 1:
            raise ValueError("rewarm records must share one committed cutoff")

        self._records.update(normalized)


__all__ = [
    "BindingRuntimeHealth",
    "BindingRuntimeState",
    "LaneExecutionIdentity",
    "LaneStateStore",
    "PreparedStateTransition",
    "StateCommitReceipt",
]
