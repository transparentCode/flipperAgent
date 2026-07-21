"""Canonical family and interaction event transition records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from .enums import (
    FamilyRole,
    FamilyTransitionType,
    InteractionEventState,
    _event_state,
    _role,
    _transition_type,
)
from .validation import (
    ContractValidationError,
    _decode,
    _freeze_mapping,
    _hash,
    _integer,
    _mapping,
    _number,
    _optional_integer,
    _optional_number,
    _optional_string,
    _primitive,
    _required,
    _string,
    _tuple_of_strings,
    parse_utc_isoformat,
    require_utc,
)

_ALLOWED_EVENT_TRANSITIONS: dict[InteractionEventState, frozenset[InteractionEventState]] = {
    InteractionEventState.FAR: frozenset({InteractionEventState.APPROACHING, InteractionEventState.IN_ZONE, InteractionEventState.WICK_BREACHED, InteractionEventState.BODY_BREACHED, InteractionEventState.BREAK_PENDING}),
    InteractionEventState.APPROACHING: frozenset({InteractionEventState.FAR, InteractionEventState.IN_ZONE, InteractionEventState.WICK_BREACHED, InteractionEventState.BODY_BREACHED, InteractionEventState.BREAK_PENDING}),
    InteractionEventState.IN_ZONE: frozenset({InteractionEventState.PRESSURING, InteractionEventState.WICK_BREACHED, InteractionEventState.BODY_BREACHED, InteractionEventState.BREAK_PENDING, InteractionEventState.REJECTING}),
    InteractionEventState.REJECTING: frozenset({InteractionEventState.FAR, InteractionEventState.APPROACHING, InteractionEventState.IN_ZONE, InteractionEventState.WICK_BREACHED, InteractionEventState.BODY_BREACHED, InteractionEventState.BREAK_PENDING}),
    InteractionEventState.PRESSURING: frozenset({InteractionEventState.REJECTING, InteractionEventState.WICK_BREACHED, InteractionEventState.BODY_BREACHED, InteractionEventState.BREAK_PENDING}),
    InteractionEventState.WICK_BREACHED: frozenset({InteractionEventState.IN_ZONE, InteractionEventState.PRESSURING, InteractionEventState.BODY_BREACHED, InteractionEventState.BREAK_PENDING, InteractionEventState.REJECTING}),
    InteractionEventState.BODY_BREACHED: frozenset({InteractionEventState.IN_ZONE, InteractionEventState.PRESSURING, InteractionEventState.WICK_BREACHED, InteractionEventState.BREAK_PENDING, InteractionEventState.REJECTING}),
    InteractionEventState.BREAK_PENDING: frozenset({InteractionEventState.IN_ZONE, InteractionEventState.WICK_BREACHED, InteractionEventState.BODY_BREACHED, InteractionEventState.BREAK_CONFIRMED, InteractionEventState.REJECTING}),
    InteractionEventState.BREAK_CONFIRMED: frozenset({InteractionEventState.RETEST_PENDING, InteractionEventState.FAILED_BREAK}),
    InteractionEventState.RETEST_PENDING: frozenset({InteractionEventState.RETEST_SUCCESS, InteractionEventState.FAILED_BREAK, InteractionEventState.FAR}),
    InteractionEventState.RETEST_SUCCESS: frozenset({InteractionEventState.ROLE_REVERSED}),
    InteractionEventState.FAILED_BREAK: frozenset(),
    InteractionEventState.ROLE_REVERSED: frozenset(),
}


def is_allowed_event_transition(
    from_state: InteractionEventState,
    to_state: InteractionEventState,
) -> bool:
    """Return whether the invariant event-state transition is permitted."""

    return to_state in _ALLOWED_EVENT_TRANSITIONS[from_state]

@dataclass(frozen=True)
class FamilyTransition:
    transition_id: str
    family_id: str
    timestamp: datetime
    transition_type: FamilyTransitionType | str
    previous_version: int | None
    new_version: int
    matched_candidate_ids: tuple[str, ...]
    association_score: float | None
    reason_codes: tuple[str, ...]
    metrics: Mapping[str, float]
    model_version: str
    config_version: str
    resolved_config_hash: str
    added_member_ids: tuple[str, ...] = ()
    continued_member_ids: tuple[str, ...] = ()
    removed_member_ids: tuple[str, ...] = ()
    previous_representative_member_id: str | None = None
    current_representative_member_id: str | None = None
    representative_changed: bool = False
    previous_rail_count: int = 0
    current_rail_count: int = 0
    source_group_id: str | None = None
    source_group_candidate_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "transition_id", _string(self.transition_id, field_name="transition_id"))
        object.__setattr__(self, "family_id", _string(self.family_id, field_name="family_id"))
        object.__setattr__(self, "timestamp", require_utc(self.timestamp))
        object.__setattr__(self, "transition_type", _transition_type(self.transition_type))
        object.__setattr__(self, "previous_version", _optional_integer(self.previous_version, field_name="previous_version", minimum=1))
        object.__setattr__(self, "new_version", _integer(self.new_version, field_name="new_version", minimum=1))
        if self.transition_type is FamilyTransitionType.BIRTH:
            if self.previous_version is not None or self.new_version != 1:
                raise ContractValidationError("BIRTH transition requires previous_version=None and new_version=1")
        elif self.previous_version is None or self.new_version != self.previous_version + 1:
            raise ContractValidationError("non-BIRTH transition must advance exactly one version")
        matched_candidate_ids = _tuple_of_strings(
            self.matched_candidate_ids,
            field_name="matched_candidate_ids",
        )
        if len(set(matched_candidate_ids)) != len(matched_candidate_ids):
            raise ContractValidationError("matched_candidate_ids must not contain duplicates")
        object.__setattr__(self, "matched_candidate_ids", matched_candidate_ids)
        object.__setattr__(self, "association_score", _optional_number(self.association_score, field_name="association_score", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "reason_codes", _tuple_of_strings(self.reason_codes, field_name="reason_codes"))
        metrics = _mapping(self.metrics, field_name="metrics")
        object.__setattr__(self, "metrics", MappingProxyType({key: _number(value, field_name=f"metrics.{key}") for key, value in metrics.items()}))
        object.__setattr__(self, "model_version", _string(self.model_version, field_name="model_version"))
        object.__setattr__(self, "config_version", _string(self.config_version, field_name="config_version"))
        object.__setattr__(self, "resolved_config_hash", _hash(self.resolved_config_hash, field_name="resolved_config_hash"))
        for name in ("added_member_ids", "continued_member_ids", "removed_member_ids"):
            values = _tuple_of_strings(getattr(self, name), field_name=name)
            if len(set(values)) != len(values):
                raise ContractValidationError(f"{name} must not contain duplicates")
            object.__setattr__(self, name, values)
        if set(self.added_member_ids) & set(self.continued_member_ids):
            raise ContractValidationError("added and continued member IDs must be disjoint")
        if set(self.removed_member_ids) & (set(self.added_member_ids) | set(self.continued_member_ids)):
            raise ContractValidationError("removed member IDs must be disjoint from current members")
        object.__setattr__(
            self,
            "previous_representative_member_id",
            _optional_string(
                self.previous_representative_member_id,
                field_name="previous_representative_member_id",
            ),
        )
        object.__setattr__(
            self,
            "current_representative_member_id",
            _optional_string(
                self.current_representative_member_id,
                field_name="current_representative_member_id",
            ),
        )
        if not isinstance(self.representative_changed, bool):
            raise ContractValidationError("representative_changed must be boolean")
        object.__setattr__(
            self,
            "previous_rail_count",
            _integer(self.previous_rail_count, field_name="previous_rail_count", minimum=0),
        )
        object.__setattr__(
            self,
            "current_rail_count",
            _integer(self.current_rail_count, field_name="current_rail_count", minimum=0),
        )
        object.__setattr__(
            self,
            "source_group_id",
            _optional_string(self.source_group_id, field_name="source_group_id"),
        )
        source_group_candidate_ids = _tuple_of_strings(
            self.source_group_candidate_ids,
            field_name="source_group_candidate_ids",
        )
        if len(set(source_group_candidate_ids)) != len(source_group_candidate_ids):
            raise ContractValidationError("source_group_candidate_ids must not contain duplicates")
        object.__setattr__(
            self,
            "source_group_candidate_ids",
            source_group_candidate_ids,
        )
        if self.previous_rail_count != len(self.continued_member_ids) + len(self.removed_member_ids):
            raise ContractValidationError("previous_rail_count must match continued and removed members")
        if self.current_rail_count != len(self.continued_member_ids) + len(self.added_member_ids):
            raise ContractValidationError("current_rail_count must match continued and added members")
        if self.representative_changed is not (
            self.previous_representative_member_id is not None
            and self.current_representative_member_id is not None
            and self.previous_representative_member_id
            != self.current_representative_member_id
        ):
            raise ContractValidationError("representative_changed must match representative IDs")

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilyTransition":
        return _decode("FamilyTransition", value, lambda item: cls(
            transition_id=_required(item, "transition_id", owner="FamilyTransition"), family_id=_required(item, "family_id", owner="FamilyTransition"),
            timestamp=parse_utc_isoformat(_required(item, "timestamp", owner="FamilyTransition")), transition_type=_required(item, "transition_type", owner="FamilyTransition"),
            previous_version=item.get("previous_version"), new_version=_required(item, "new_version", owner="FamilyTransition"),
            matched_candidate_ids=tuple(_required(item, "matched_candidate_ids", owner="FamilyTransition")), association_score=item.get("association_score"),
            reason_codes=tuple(_required(item, "reason_codes", owner="FamilyTransition")), metrics=_required(item, "metrics", owner="FamilyTransition"),
            model_version=_required(item, "model_version", owner="FamilyTransition"), config_version=_required(item, "config_version", owner="FamilyTransition"),
            resolved_config_hash=_required(item, "resolved_config_hash", owner="FamilyTransition"),
            added_member_ids=tuple(item.get("added_member_ids", ())),
            continued_member_ids=tuple(item.get("continued_member_ids", ())),
            removed_member_ids=tuple(item.get("removed_member_ids", ())),
            previous_representative_member_id=item.get("previous_representative_member_id"),
            current_representative_member_id=item.get("current_representative_member_id"),
            representative_changed=item.get("representative_changed", False),
            previous_rail_count=item.get("previous_rail_count", 0),
            current_rail_count=item.get("current_rail_count", 0),
            source_group_id=item.get("source_group_id"),
            source_group_candidate_ids=tuple(item.get("source_group_candidate_ids", ())),
        ))
@dataclass(frozen=True)
class FamilyInteractionEvent:
    """Immutable multi-bar lifecycle evidence for one published family."""

    event_id: str
    family_id: str
    asset: str
    timeframe: str
    state: InteractionEventState | str
    started_at: datetime
    updated_at: datetime
    starting_role: FamilyRole | str
    current_event_role: FamilyRole | str
    previous_state: InteractionEventState | str | None
    last_observation_id: str
    age_bars: int
    bars_in_state: int
    pressure_bars: int | None
    rejection_bars: int | None
    close_beyond_streak: int | None
    retest_age_bars: int | None
    retest_contact_seen: bool
    retest_confirmation_streak: int | None
    retest_window_expired: bool
    role_reversal_applied: bool
    max_wick_penetration_atr: float
    max_body_penetration_atr: float
    max_close_penetration_atr: float
    break_pending_at: datetime | None
    break_confirmed_at: datetime | None
    retest_started_at: datetime | None
    retest_succeeded_at: datetime | None
    failed_break_at: datetime | None
    pending_role_reversal: bool
    required_close_confirmation_bars: int
    required_retest_confirmation_bars: int
    model_version: str
    config_version: str
    resolved_config_hash: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("event_id", "family_id", "asset", "timeframe", "last_observation_id", "model_version", "config_version"):
            object.__setattr__(self, name, _string(getattr(self, name), field_name=name))
        object.__setattr__(self, "state", _event_state(self.state))
        object.__setattr__(self, "previous_state", None if self.previous_state is None else _event_state(self.previous_state))
        object.__setattr__(self, "started_at", require_utc(self.started_at, field_name="event started_at"))
        object.__setattr__(self, "updated_at", require_utc(self.updated_at, field_name="event updated_at"))
        if self.started_at > self.updated_at:
            raise ContractValidationError("event started_at cannot follow updated_at")
        for name in (
            "break_pending_at",
            "break_confirmed_at",
            "retest_started_at",
            "retest_succeeded_at",
            "failed_break_at",
        ):
            value = getattr(self, name)
            normalized = None if value is None else require_utc(value, field_name=name)
            if normalized is not None and (normalized < self.started_at or normalized > self.updated_at):
                raise ContractValidationError(f"{name} must be within the event lifetime")
            object.__setattr__(self, name, normalized)
        object.__setattr__(self, "starting_role", _role(self.starting_role))
        object.__setattr__(self, "current_event_role", _role(self.current_event_role))
        if self.starting_role not in {FamilyRole.SUPPORT, FamilyRole.RESISTANCE}:
            raise ContractValidationError("event starting_role must be SUPPORT or RESISTANCE")
        if self.current_event_role not in {FamilyRole.SUPPORT, FamilyRole.RESISTANCE}:
            raise ContractValidationError("event current_event_role must be SUPPORT or RESISTANCE")
        for name in ("age_bars", "bars_in_state"):
            object.__setattr__(self, name, _integer(getattr(self, name), field_name=name, minimum=0))
        if self.age_bars < 1 or self.bars_in_state < 1:
            raise ContractValidationError("event age_bars and bars_in_state must be positive")
        for name in ("pressure_bars", "rejection_bars", "close_beyond_streak"):
            object.__setattr__(self, name, _optional_integer(getattr(self, name), field_name=name, minimum=0))
        object.__setattr__(self, "retest_age_bars", _optional_integer(self.retest_age_bars, field_name="retest_age_bars", minimum=0))
        if not isinstance(self.retest_contact_seen, bool):
            raise ContractValidationError("retest_contact_seen must be boolean")
        object.__setattr__(
            self,
            "retest_confirmation_streak",
            _optional_integer(
                self.retest_confirmation_streak,
                field_name="retest_confirmation_streak",
                minimum=0,
            ),
        )
        if not isinstance(self.retest_window_expired, bool):
            raise ContractValidationError("retest_window_expired must be boolean")
        if not isinstance(self.role_reversal_applied, bool):
            raise ContractValidationError("role_reversal_applied must be boolean")
        for name in (
            "max_wick_penetration_atr",
            "max_body_penetration_atr",
            "max_close_penetration_atr",
        ):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=name, minimum=0.0))
        if self.max_wick_penetration_atr + 1e-12 < self.max_body_penetration_atr:
            raise ContractValidationError("event wick maximum cannot be below body maximum")
        if self.max_body_penetration_atr + 1e-12 < self.max_close_penetration_atr:
            raise ContractValidationError("event body maximum cannot be below close maximum")
        if not isinstance(self.pending_role_reversal, bool):
            raise ContractValidationError("event pending_role_reversal must be boolean")
        object.__setattr__(
            self,
            "required_close_confirmation_bars",
            _integer(
                self.required_close_confirmation_bars,
                field_name="required_close_confirmation_bars",
                minimum=2,
            ),
        )
        object.__setattr__(
            self,
            "required_retest_confirmation_bars",
            _integer(
                self.required_retest_confirmation_bars,
                field_name="required_retest_confirmation_bars",
                minimum=1,
            ),
        )
        if self.break_pending_at is not None and self.break_confirmed_at is not None and self.break_pending_at > self.break_confirmed_at:
            raise ContractValidationError("break_pending_at cannot follow break_confirmed_at")
        if self.break_confirmed_at is not None and self.retest_started_at is not None and self.break_confirmed_at > self.retest_started_at:
            raise ContractValidationError("break_confirmed_at cannot follow retest_started_at")
        if self.retest_started_at is not None and self.retest_succeeded_at is not None and self.retest_started_at > self.retest_succeeded_at:
            raise ContractValidationError("retest_started_at cannot follow retest_succeeded_at")
        if self.break_confirmed_at is not None and self.failed_break_at is not None and self.break_confirmed_at > self.failed_break_at:
            raise ContractValidationError("break_confirmed_at cannot follow failed_break_at")
        if self.state is InteractionEventState.BREAK_PENDING:
            if self.break_pending_at is None or self.close_beyond_streak is None or self.close_beyond_streak < 1:
                raise ContractValidationError("BREAK_PENDING requires a pending timestamp and close streak")
        if self.state in {
            InteractionEventState.BREAK_CONFIRMED,
            InteractionEventState.RETEST_PENDING,
            InteractionEventState.RETEST_SUCCESS,
            InteractionEventState.FAILED_BREAK,
            InteractionEventState.ROLE_REVERSED,
        }:
            if self.break_confirmed_at is None:
                raise ContractValidationError("post-break event states require break_confirmed_at")
        if self.state is InteractionEventState.BREAK_CONFIRMED and (
            self.close_beyond_streak is None
            or self.close_beyond_streak < self.required_close_confirmation_bars
        ):
            raise ContractValidationError("BREAK_CONFIRMED requires the configured consecutive close evidence")
        if self.state is InteractionEventState.BREAK_CONFIRMED and (
            self.previous_state is not InteractionEventState.BREAK_PENDING
            or self.break_pending_at is None
        ):
            raise ContractValidationError("BREAK_CONFIRMED requires a BREAK_PENDING predecessor")
        retest_states = {
            InteractionEventState.RETEST_PENDING,
            InteractionEventState.RETEST_SUCCESS,
            InteractionEventState.ROLE_REVERSED,
        }
        if self.state in retest_states and self.retest_started_at is None:
            raise ContractValidationError("retest event states require retest_started_at")
        if self.state is InteractionEventState.RETEST_PENDING and (
            self.previous_state
            not in {InteractionEventState.BREAK_CONFIRMED, InteractionEventState.RETEST_PENDING}
            or self.retest_age_bars is None
            or self.retest_confirmation_streak is None
        ):
            raise ContractValidationError("RETEST_PENDING requires a valid post-break predecessor and typed retest state")
        if self.state in {InteractionEventState.RETEST_SUCCESS, InteractionEventState.ROLE_REVERSED} and self.retest_succeeded_at is None:
            raise ContractValidationError("successful retest states require retest_succeeded_at")
        if self.state is InteractionEventState.RETEST_SUCCESS and (
            self.previous_state is not InteractionEventState.RETEST_PENDING
            or not self.retest_contact_seen
            or self.retest_confirmation_streak is None
            or self.retest_confirmation_streak < self.required_retest_confirmation_bars
        ):
            raise ContractValidationError("RETEST_SUCCESS requires typed confirmed retest evidence")
        if self.state is InteractionEventState.FAILED_BREAK and self.failed_break_at is None:
            raise ContractValidationError("FAILED_BREAK requires failed_break_at")
        if self.state is InteractionEventState.FAILED_BREAK and self.previous_state not in {
            InteractionEventState.BREAK_CONFIRMED,
            InteractionEventState.RETEST_PENDING,
        }:
            raise ContractValidationError("FAILED_BREAK requires a post-break predecessor")
        if self.pending_role_reversal is not (self.state is InteractionEventState.RETEST_SUCCESS):
            raise ContractValidationError("pending role reversal is valid only for RETEST_SUCCESS")
        if self.state is InteractionEventState.ROLE_REVERSED:
            if (
                self.current_event_role is self.starting_role
                or self.previous_state is not InteractionEventState.RETEST_SUCCESS
                or not self.role_reversal_applied
            ):
                raise ContractValidationError("ROLE_REVERSED requires a successful pending retest reversal")
        elif self.current_event_role is not self.starting_role:
            raise ContractValidationError("only ROLE_REVERSED may change the current event role")
        elif self.role_reversal_applied:
            raise ContractValidationError("role_reversal_applied is valid only for ROLE_REVERSED")
        if self.state not in retest_states and (
            self.retest_contact_seen
            or self.retest_confirmation_streak is not None
        ):
            raise ContractValidationError("non-retest event states cannot retain typed retest progress")
        if self.retest_window_expired and (
            self.state is not InteractionEventState.FAR
            or self.previous_state is not InteractionEventState.RETEST_PENDING
        ):
            raise ContractValidationError("retest window expiry must resolve directly from RETEST_PENDING to FAR")
        object.__setattr__(self, "resolved_config_hash", _hash(self.resolved_config_hash, field_name="resolved_config_hash"))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, field_name="event metadata"))

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilyInteractionEvent":
        return _decode("FamilyInteractionEvent", value, lambda item: cls(
            event_id=_required(item, "event_id", owner="FamilyInteractionEvent"),
            family_id=_required(item, "family_id", owner="FamilyInteractionEvent"),
            asset=_required(item, "asset", owner="FamilyInteractionEvent"),
            timeframe=_required(item, "timeframe", owner="FamilyInteractionEvent"),
            state=_required(item, "state", owner="FamilyInteractionEvent"),
            started_at=parse_utc_isoformat(_required(item, "started_at", owner="FamilyInteractionEvent"), field_name="event started_at"),
            updated_at=parse_utc_isoformat(_required(item, "updated_at", owner="FamilyInteractionEvent"), field_name="event updated_at"),
            starting_role=_required(item, "starting_role", owner="FamilyInteractionEvent"),
            current_event_role=_required(item, "current_event_role", owner="FamilyInteractionEvent"),
            previous_state=item.get("previous_state"),
            last_observation_id=_required(item, "last_observation_id", owner="FamilyInteractionEvent"),
            age_bars=_required(item, "age_bars", owner="FamilyInteractionEvent"),
            bars_in_state=_required(item, "bars_in_state", owner="FamilyInteractionEvent"),
            pressure_bars=_required(item, "pressure_bars", owner="FamilyInteractionEvent"),
            rejection_bars=_required(item, "rejection_bars", owner="FamilyInteractionEvent"),
            close_beyond_streak=_required(item, "close_beyond_streak", owner="FamilyInteractionEvent"),
            retest_age_bars=item.get("retest_age_bars"),
            retest_contact_seen=_required(item, "retest_contact_seen", owner="FamilyInteractionEvent"),
            retest_confirmation_streak=item.get("retest_confirmation_streak"),
            retest_window_expired=_required(item, "retest_window_expired", owner="FamilyInteractionEvent"),
            role_reversal_applied=_required(item, "role_reversal_applied", owner="FamilyInteractionEvent"),
            max_wick_penetration_atr=_required(item, "max_wick_penetration_atr", owner="FamilyInteractionEvent"),
            max_body_penetration_atr=_required(item, "max_body_penetration_atr", owner="FamilyInteractionEvent"),
            max_close_penetration_atr=_required(item, "max_close_penetration_atr", owner="FamilyInteractionEvent"),
            break_pending_at=None if item.get("break_pending_at") is None else parse_utc_isoformat(item["break_pending_at"], field_name="break_pending_at"),
            break_confirmed_at=None if item.get("break_confirmed_at") is None else parse_utc_isoformat(item["break_confirmed_at"], field_name="break_confirmed_at"),
            retest_started_at=None if item.get("retest_started_at") is None else parse_utc_isoformat(item["retest_started_at"], field_name="retest_started_at"),
            retest_succeeded_at=None if item.get("retest_succeeded_at") is None else parse_utc_isoformat(item["retest_succeeded_at"], field_name="retest_succeeded_at"),
            failed_break_at=None if item.get("failed_break_at") is None else parse_utc_isoformat(item["failed_break_at"], field_name="failed_break_at"),
            pending_role_reversal=_required(item, "pending_role_reversal", owner="FamilyInteractionEvent"),
            required_close_confirmation_bars=_required(item, "required_close_confirmation_bars", owner="FamilyInteractionEvent"),
            required_retest_confirmation_bars=_required(item, "required_retest_confirmation_bars", owner="FamilyInteractionEvent"),
            model_version=_required(item, "model_version", owner="FamilyInteractionEvent"),
            config_version=_required(item, "config_version", owner="FamilyInteractionEvent"),
            resolved_config_hash=_required(item, "resolved_config_hash", owner="FamilyInteractionEvent"),
            metadata=item.get("metadata", {}),
        ))


@dataclass(frozen=True)
class FamilyInteractionEventTransition:
    """Content-addressed audit record for one event-state transition."""

    transition_id: str
    event_id: str
    family_id: str
    from_state: InteractionEventState | str
    to_state: InteractionEventState | str
    timestamp: datetime
    trigger_observation_id: str
    reason_code: str
    bars_in_previous_state: int
    metrics: Mapping[str, float]
    model_version: str
    config_version: str
    resolved_config_hash: str

    def __post_init__(self) -> None:
        for name in ("transition_id", "event_id", "family_id", "trigger_observation_id", "reason_code", "model_version", "config_version"):
            object.__setattr__(self, name, _string(getattr(self, name), field_name=name))
        object.__setattr__(self, "from_state", _event_state(self.from_state))
        object.__setattr__(self, "to_state", _event_state(self.to_state))
        if self.from_state is self.to_state:
            raise ContractValidationError("event transition requires distinct states")
        object.__setattr__(self, "timestamp", require_utc(self.timestamp, field_name="event transition timestamp"))
        object.__setattr__(self, "bars_in_previous_state", _integer(self.bars_in_previous_state, field_name="bars_in_previous_state", minimum=1))
        metrics = _mapping(self.metrics, field_name="event transition metrics")
        object.__setattr__(self, "metrics", MappingProxyType({key: _number(value, field_name=f"event transition metrics.{key}") for key, value in metrics.items()}))
        object.__setattr__(self, "resolved_config_hash", _hash(self.resolved_config_hash, field_name="resolved_config_hash"))

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilyInteractionEventTransition":
        return _decode("FamilyInteractionEventTransition", value, lambda item: cls(
            transition_id=_required(item, "transition_id", owner="FamilyInteractionEventTransition"),
            event_id=_required(item, "event_id", owner="FamilyInteractionEventTransition"),
            family_id=_required(item, "family_id", owner="FamilyInteractionEventTransition"),
            from_state=_required(item, "from_state", owner="FamilyInteractionEventTransition"),
            to_state=_required(item, "to_state", owner="FamilyInteractionEventTransition"),
            timestamp=parse_utc_isoformat(_required(item, "timestamp", owner="FamilyInteractionEventTransition"), field_name="event transition timestamp"),
            trigger_observation_id=_required(item, "trigger_observation_id", owner="FamilyInteractionEventTransition"),
            reason_code=_required(item, "reason_code", owner="FamilyInteractionEventTransition"),
            bars_in_previous_state=_required(item, "bars_in_previous_state", owner="FamilyInteractionEventTransition"),
            metrics=_required(item, "metrics", owner="FamilyInteractionEventTransition"),
            model_version=_required(item, "model_version", owner="FamilyInteractionEventTransition"),
            config_version=_required(item, "config_version", owner="FamilyInteractionEventTransition"),
            resolved_config_hash=_required(item, "resolved_config_hash", owner="FamilyInteractionEventTransition"),
        ))


TrendlineEvent = FamilyInteractionEvent
TrendlineEventTransition = FamilyInteractionEventTransition

__all__ = [
    "FamilyInteractionEvent",
    "FamilyInteractionEventTransition",
    "FamilyTransition",
    "TrendlineEvent",
    "TrendlineEventTransition",
    "is_allowed_event_transition",
]
