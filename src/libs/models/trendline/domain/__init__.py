"""Canonical presentation-independent trendline domain."""

from .candidates import LineCandidate, LineDiagnostics
from .context import TrendlineContext, TrendlineSnapshot, trendline_context_from_snapshot
from .enums import (
    CandleDirection,
    FamilyLifecycleState,
    FamilyRole,
    FamilyTransitionType,
    InteractionCompatibilityLabel,
    InteractionEventState,
    InteractionObservationState,
)
from .events import FamilyInteractionEvent, FamilyInteractionEventTransition, FamilyTransition
from .families import (
    FamilyCorridor,
    FamilyMember,
    FamilyRailProjection,
    FamilySourceGroupAudit,
    LineUncertainty,
    TrendlineFamilyState,
)
from .geometry import AnchorRef, LineGeometry
from .identity import canonical_json, deterministic_hash, deterministic_id
from .interactions import FamilyInteractionObservation, InteractionZone
from .serialization import serialize_domain, to_primitive
from .snapshots import TrendlineFamilyOutput, TrendlineFamilySnapshot
from .validation import ContractValidationError, parse_utc_isoformat, require_utc, utc_isoformat

TrendlineFamily = TrendlineFamilyState
TrendlineEvent = FamilyInteractionEvent
TrendlineEventTransition = FamilyInteractionEventTransition

__all__ = [
    "AnchorRef",
    "CandleDirection",
    "ContractValidationError",
    "FamilyCorridor",
    "FamilyInteractionEvent",
    "FamilyInteractionEventTransition",
    "FamilyInteractionObservation",
    "FamilyLifecycleState",
    "FamilyMember",
    "FamilyRailProjection",
    "FamilyRole",
    "FamilySourceGroupAudit",
    "FamilyTransition",
    "FamilyTransitionType",
    "InteractionCompatibilityLabel",
    "InteractionEventState",
    "InteractionObservationState",
    "InteractionZone",
    "LineCandidate",
    "LineDiagnostics",
    "LineGeometry",
    "LineUncertainty",
    "TrendlineContext",
    "TrendlineEvent",
    "TrendlineEventTransition",
    "TrendlineFamily",
    "TrendlineFamilyOutput",
    "TrendlineFamilySnapshot",
    "TrendlineFamilyState",
    "TrendlineSnapshot",
    "canonical_json",
    "deterministic_hash",
    "deterministic_id",
    "parse_utc_isoformat",
    "require_utc",
    "serialize_domain",
    "to_primitive",
    "trendline_context_from_snapshot",
    "utc_isoformat",
]
