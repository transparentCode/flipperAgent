"""Invariant canonical domain enums and coercion helpers."""

from __future__ import annotations

from enum import Enum
from typing import Any

from .validation import ContractValidationError

class FamilyRole(str, Enum):
    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"
    UNCLASSIFIED = "UNCLASSIFIED"


class FamilyLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    ARCHIVED = "ARCHIVED"


class FamilyTransitionType(str, Enum):
    BIRTH = "BIRTH"
    CONTINUE = "CONTINUE"
    STRENGTHEN = "STRENGTHEN"
    WEAKEN = "WEAKEN"
    DORMANT = "DORMANT"
    REACTIVATE = "REACTIVATE"
    BREAK_CONFIRMED = "BREAK_CONFIRMED"
    ROLE_REVERSED = "ROLE_REVERSED"
    EXPIRE = "EXPIRE"
class InteractionObservationState(str, Enum):
    FAR = "FAR"
    APPROACHING = "APPROACHING"
    IN_ZONE = "IN_ZONE"
    WICK_BREACH = "WICK_BREACH"
    BODY_BREACH = "BODY_BREACH"
    CLOSE_BEYOND = "CLOSE_BEYOND"


class InteractionEventState(str, Enum):
    """Persistent, confirmed-bar interaction lifecycle state."""

    FAR = "FAR"
    APPROACHING = "APPROACHING"
    IN_ZONE = "IN_ZONE"
    REJECTING = "REJECTING"
    PRESSURING = "PRESSURING"
    WICK_BREACHED = "WICK_BREACHED"
    BODY_BREACHED = "BODY_BREACHED"
    BREAK_PENDING = "BREAK_PENDING"
    BREAK_CONFIRMED = "BREAK_CONFIRMED"
    RETEST_PENDING = "RETEST_PENDING"
    RETEST_SUCCESS = "RETEST_SUCCESS"
    FAILED_BREAK = "FAILED_BREAK"
    ROLE_REVERSED = "ROLE_REVERSED"


class InteractionCompatibilityLabel(str, Enum):
    """Read-only legacy-friendly interpretation of persisted event evidence."""

    BREAKOUT = "breakout"
    BREAKDOWN = "breakdown"
    BOUNCE = "bounce"
    REJECTION = "rejection"


class CandleDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


def _role(value: Any) -> FamilyRole:
    try:
        return value if isinstance(value, FamilyRole) else FamilyRole(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid family role: {value!r}") from exc


def _lifecycle(value: Any) -> FamilyLifecycleState:
    try:
        return value if isinstance(value, FamilyLifecycleState) else FamilyLifecycleState(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid lifecycle state: {value!r}") from exc


def _transition_type(value: Any) -> FamilyTransitionType:
    try:
        return value if isinstance(value, FamilyTransitionType) else FamilyTransitionType(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid transition type: {value!r}") from exc


def _interaction_state(value: Any) -> InteractionObservationState:
    try:
        return value if isinstance(value, InteractionObservationState) else InteractionObservationState(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid interaction observation state: {value!r}") from exc


def _event_state(value: Any) -> InteractionEventState:
    try:
        return value if isinstance(value, InteractionEventState) else InteractionEventState(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid interaction event state: {value!r}") from exc


def _candle_direction(value: Any) -> CandleDirection:
    try:
        return value if isinstance(value, CandleDirection) else CandleDirection(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid candle direction: {value!r}") from exc
