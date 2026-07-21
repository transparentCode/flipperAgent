"""Pure point-in-time read context over published canonical state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .events import FamilyInteractionEvent
from .families import TrendlineFamilyState
from .snapshots import TrendlineFamilySnapshot
from .validation import ContractValidationError, require_utc

TrendlineSnapshot = TrendlineFamilySnapshot


@dataclass(frozen=True)
class TrendlineContext:
    """Immutable presentation-neutral state known at one explicit UTC instant."""

    asset: str
    timeframe: str
    as_of: datetime
    families: tuple[TrendlineFamilyState, ...]
    events: tuple[FamilyInteractionEvent, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.asset, str) or not self.asset:
            raise ContractValidationError("context asset must be a non-empty string")
        if not isinstance(self.timeframe, str) or not self.timeframe:
            raise ContractValidationError("context timeframe must be a non-empty string")
        object.__setattr__(self, "as_of", require_utc(self.as_of, field_name="context as_of"))
        families = tuple(self.families)
        if any(not isinstance(family, TrendlineFamilyState) for family in families):
            raise ContractValidationError("context families must use TrendlineFamilyState")
        if len({family.family_id for family in families}) != len(families):
            raise ContractValidationError("context family IDs must be unique")
        if tuple(sorted(families, key=lambda family: family.family_id)) != families:
            raise ContractValidationError("context families must have deterministic family ID ordering")
        if any(family.asset != self.asset or family.timeframe != self.timeframe for family in families):
            raise ContractValidationError("context families must match context asset and timeframe")
        if any(family.updated_at > self.as_of for family in families):
            raise ContractValidationError("context cannot include family state known after as_of")
        object.__setattr__(self, "families", families)
        events = tuple(self.events)
        if any(not isinstance(event, FamilyInteractionEvent) for event in events):
            raise ContractValidationError("context events must use FamilyInteractionEvent")
        if len({event.event_id for event in events}) != len(events):
            raise ContractValidationError("context event IDs must be unique")
        if tuple(sorted(events, key=lambda event: (event.updated_at, event.event_id))) != events:
            raise ContractValidationError("context events must have deterministic known-time ordering")
        if any(event.asset != self.asset or event.timeframe != self.timeframe for event in events):
            raise ContractValidationError("context events must match context asset and timeframe")
        if any(event.updated_at > self.as_of for event in events):
            raise ContractValidationError("context cannot include event state known after as_of")
        object.__setattr__(self, "events", events)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "as_of": self.as_of.isoformat(),
            "families": [family.to_dict() for family in self.families],
            "events": [event.to_dict() for event in self.events],
        }


def trendline_context_from_snapshot(snapshot: TrendlineSnapshot) -> TrendlineContext:
    """Create read context from one already-confirmed published snapshot."""

    if not isinstance(snapshot, TrendlineSnapshot):
        raise ContractValidationError("context source must use TrendlineFamilySnapshot")
    return TrendlineContext(
        asset=snapshot.asset,
        timeframe=snapshot.timeframe,
        as_of=snapshot.timestamp,
        families=tuple(sorted(snapshot.active_families + snapshot.dormant_families, key=lambda family: family.family_id)),
        events=tuple(sorted(snapshot.interaction_events, key=lambda event: (event.updated_at, event.event_id))),
    )


__all__ = ["TrendlineContext", "TrendlineSnapshot", "trendline_context_from_snapshot"]
