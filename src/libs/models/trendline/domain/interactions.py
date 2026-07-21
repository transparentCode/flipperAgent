"""Canonical interaction zones and confirmed-bar observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, Mapping

from .enums import (
    CandleDirection,
    FamilyRole,
    InteractionObservationState,
    _candle_direction,
    _interaction_state,
    _role,
)
from .validation import (
    ContractValidationError,
    _decode,
    _integer,
    _interaction_close,
    _number,
    _optional_number,
    _primitive,
    _required,
    _string,
    parse_utc_isoformat,
    require_utc,
)

@dataclass(frozen=True)
class InteractionZone:
    """A derived symmetric half-width around one exact representative line.

    ``width_atr`` is the selected price half-width divided by interaction ATR.
    """

    line_id: str
    timestamp: datetime
    center_price: float
    lower_price: float
    upper_price: float
    width_atr: float
    policy_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_id", _string(self.line_id, field_name="line_id"))
        object.__setattr__(self, "policy_name", _string(self.policy_name, field_name="policy_name"))
        object.__setattr__(self, "timestamp", require_utc(self.timestamp))
        for name in ("center_price", "lower_price", "upper_price"):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=name))
        object.__setattr__(self, "width_atr", _number(self.width_atr, field_name="width_atr", minimum=0.0))
        if self.lower_price > self.center_price or self.upper_price < self.center_price:
            raise ContractValidationError("interaction zone bounds are invalid")
        if not math.isclose(
            self.center_price - self.lower_price,
            self.upper_price - self.center_price,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ContractValidationError("interaction zone bounds must be symmetric around the exact center")

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InteractionZone":
        return _decode("InteractionZone", value, lambda item: cls(
            line_id=_required(item, "line_id", owner="InteractionZone"), timestamp=parse_utc_isoformat(_required(item, "timestamp", owner="InteractionZone")),
            center_price=_required(item, "center_price", owner="InteractionZone"), lower_price=_required(item, "lower_price", owner="InteractionZone"),
            upper_price=_required(item, "upper_price", owner="InteractionZone"), width_atr=_required(item, "width_atr", owner="InteractionZone"),
            policy_name=_required(item, "policy_name", owner="InteractionZone"),
        ))
@dataclass(frozen=True)
class FamilyInteractionObservation:
    """One confirmed-bar observation around an exact family representative line."""

    observation_id: str
    family_id: str
    role: FamilyRole | str
    timestamp: datetime
    state: InteractionObservationState | str
    exact_line_price: float
    zone: InteractionZone
    interaction_atr: float
    interaction_atr_method: str
    interaction_atr_sample_count: int
    distance_to_line_atr: float
    distance_to_zone_atr: float
    wick_penetration_atr: float
    body_penetration_atr: float
    close_penetration_atr: float
    candle_direction: CandleDirection | str
    close_location: float
    tick_size: float | None
    minimum_zone_ticks: int
    atr_half_width: float
    tick_half_width: float | None
    tick_floor_applied: bool
    # Added in Phase F so retest and failed-break logic can consume the
    # persisted confirmed-bar evidence without reclassifying a candle.
    close_price: float | None = None

    def __post_init__(self) -> None:
        for name in ("observation_id", "family_id", "interaction_atr_method"):
            object.__setattr__(self, name, _string(getattr(self, name), field_name=name))
        object.__setattr__(self, "role", _role(self.role))
        if self.role not in {FamilyRole.SUPPORT, FamilyRole.RESISTANCE}:
            raise ContractValidationError("interaction observation role must be SUPPORT or RESISTANCE")
        object.__setattr__(self, "timestamp", require_utc(self.timestamp, field_name="interaction timestamp"))
        object.__setattr__(self, "state", _interaction_state(self.state))
        object.__setattr__(self, "candle_direction", _candle_direction(self.candle_direction))
        if not isinstance(self.zone, InteractionZone):
            raise ContractValidationError("interaction observation zone must use InteractionZone")
        if self.zone.line_id != self.family_id or self.zone.timestamp != self.timestamp:
            raise ContractValidationError("interaction observation zone must identify the same family and timestamp")
        object.__setattr__(self, "exact_line_price", _number(self.exact_line_price, field_name="exact_line_price"))
        if not _interaction_close(self.exact_line_price, self.zone.center_price):
            raise ContractValidationError("interaction observation exact line price must equal zone center")
        object.__setattr__(self, "interaction_atr", _number(self.interaction_atr, field_name="interaction_atr", minimum=0.0))
        if self.interaction_atr <= 0.0:
            raise ContractValidationError("interaction_atr must be positive")
        object.__setattr__(
            self,
            "interaction_atr_sample_count",
            _integer(self.interaction_atr_sample_count, field_name="interaction_atr_sample_count", minimum=1),
        )
        for name in (
            "distance_to_line_atr",
            "distance_to_zone_atr",
            "wick_penetration_atr",
            "body_penetration_atr",
            "close_penetration_atr",
            "atr_half_width",
        ):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=name, minimum=0.0))
        absolute_half_width = self.zone.upper_price - self.zone.center_price
        if not _interaction_close(self.zone.center_price - self.zone.lower_price, absolute_half_width):
            raise ContractValidationError("interaction observation zone bounds must have equal half-widths")
        if not _interaction_close(self.zone.width_atr, absolute_half_width / self.interaction_atr):
            raise ContractValidationError("interaction observation width_atr must match zone half-width and interaction ATR")
        if self.wick_penetration_atr + 1e-12 < self.body_penetration_atr:
            raise ContractValidationError("wick penetration cannot be below body penetration")
        if self.body_penetration_atr + 1e-12 < self.close_penetration_atr:
            raise ContractValidationError("body penetration cannot be below close penetration")
        penetrations = (
            self.wick_penetration_atr,
            self.body_penetration_atr,
            self.close_penetration_atr,
        )
        if self.state in {
            InteractionObservationState.FAR,
            InteractionObservationState.APPROACHING,
            InteractionObservationState.IN_ZONE,
        } and any(value != 0.0 for value in penetrations):
            raise ContractValidationError("non-breach observations cannot report adverse penetration")
        if self.state is InteractionObservationState.WICK_BREACH and (
            self.wick_penetration_atr <= 0.0
            or self.body_penetration_atr != 0.0
            or self.close_penetration_atr != 0.0
        ):
            raise ContractValidationError("WICK_BREACH requires only positive wick penetration")
        if self.state is InteractionObservationState.BODY_BREACH and (
            self.body_penetration_atr <= 0.0 or self.close_penetration_atr != 0.0
        ):
            raise ContractValidationError("BODY_BREACH requires positive body penetration and zero close penetration")
        if self.state is InteractionObservationState.CLOSE_BEYOND and self.close_penetration_atr <= 0.0:
            raise ContractValidationError("CLOSE_BEYOND requires positive close penetration")
        object.__setattr__(self, "close_location", _number(self.close_location, field_name="close_location", minimum=0.0, maximum=1.0))
        object.__setattr__(
            self,
            "minimum_zone_ticks",
            _integer(self.minimum_zone_ticks, field_name="minimum_zone_ticks", minimum=1),
        )
        if not isinstance(self.tick_floor_applied, bool):
            raise ContractValidationError("tick_floor_applied must be boolean")
        if self.tick_size is None:
            if self.tick_half_width is not None or self.tick_floor_applied:
                raise ContractValidationError("tick floor cannot apply without tick_size")
            selected_half_width = self.atr_half_width
        else:
            object.__setattr__(self, "tick_size", _number(self.tick_size, field_name="tick_size", minimum=0.0))
            if self.tick_size <= 0.0:
                raise ContractValidationError("tick_size must be positive when supplied")
            object.__setattr__(
                self,
                "tick_half_width",
                _number(self.tick_half_width, field_name="tick_half_width", minimum=0.0),
            )
            if self.tick_half_width <= 0.0:
                raise ContractValidationError("tick_half_width must be positive when tick_size is supplied")
            expected_tick_half_width = self.tick_size * self.minimum_zone_ticks
            if not _interaction_close(self.tick_half_width, expected_tick_half_width):
                raise ContractValidationError("tick_half_width must equal tick_size times minimum_zone_ticks")
            expected_tick_floor_applied = self.tick_half_width >= self.atr_half_width
            if self.tick_floor_applied is not expected_tick_floor_applied:
                raise ContractValidationError("tick_floor_applied must reflect the selected tick floor")
            selected_half_width = max(self.atr_half_width, self.tick_half_width)
        if not _interaction_close(absolute_half_width, selected_half_width):
            raise ContractValidationError("interaction observation zone half-width must match the selected ATR/tick width")
        expected_distance_to_zone = max(self.distance_to_line_atr - self.zone.width_atr, 0.0)
        if not _interaction_close(self.distance_to_zone_atr, expected_distance_to_zone):
            raise ContractValidationError("distance_to_zone_atr must use the close-based line-distance relation")
        object.__setattr__(self, "close_price", _optional_number(self.close_price, field_name="close_price"))
        if self.close_price is not None:
            expected_distance_to_line = abs(self.close_price - self.exact_line_price) / self.interaction_atr
            if not _interaction_close(self.distance_to_line_atr, expected_distance_to_line):
                raise ContractValidationError(
                    "interaction observation close_price must match distance_to_line_atr"
                )
            if self.role is FamilyRole.SUPPORT and self.state is InteractionObservationState.CLOSE_BEYOND and self.close_price >= self.zone.lower_price:
                raise ContractValidationError("support CLOSE_BEYOND close must be below the interaction zone")
            if self.role is FamilyRole.RESISTANCE and self.state is InteractionObservationState.CLOSE_BEYOND and self.close_price <= self.zone.upper_price:
                raise ContractValidationError("resistance CLOSE_BEYOND close must be above the interaction zone")

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilyInteractionObservation":
        return _decode("FamilyInteractionObservation", value, lambda item: cls(
            observation_id=_required(item, "observation_id", owner="FamilyInteractionObservation"),
            family_id=_required(item, "family_id", owner="FamilyInteractionObservation"),
            role=_required(item, "role", owner="FamilyInteractionObservation"),
            timestamp=parse_utc_isoformat(_required(item, "timestamp", owner="FamilyInteractionObservation"), field_name="interaction timestamp"),
            state=_required(item, "state", owner="FamilyInteractionObservation"),
            exact_line_price=_required(item, "exact_line_price", owner="FamilyInteractionObservation"),
            zone=InteractionZone.from_dict(_required(item, "zone", owner="FamilyInteractionObservation")),
            interaction_atr=_required(item, "interaction_atr", owner="FamilyInteractionObservation"),
            interaction_atr_method=_required(item, "interaction_atr_method", owner="FamilyInteractionObservation"),
            interaction_atr_sample_count=_required(item, "interaction_atr_sample_count", owner="FamilyInteractionObservation"),
            distance_to_line_atr=_required(item, "distance_to_line_atr", owner="FamilyInteractionObservation"),
            distance_to_zone_atr=_required(item, "distance_to_zone_atr", owner="FamilyInteractionObservation"),
            wick_penetration_atr=_required(item, "wick_penetration_atr", owner="FamilyInteractionObservation"),
            body_penetration_atr=_required(item, "body_penetration_atr", owner="FamilyInteractionObservation"),
            close_penetration_atr=_required(item, "close_penetration_atr", owner="FamilyInteractionObservation"),
            candle_direction=_required(item, "candle_direction", owner="FamilyInteractionObservation"),
            close_location=_required(item, "close_location", owner="FamilyInteractionObservation"),
            tick_size=item.get("tick_size"),
            minimum_zone_ticks=_required(item, "minimum_zone_ticks", owner="FamilyInteractionObservation"),
            atr_half_width=_required(item, "atr_half_width", owner="FamilyInteractionObservation"),
            tick_half_width=item.get("tick_half_width"),
            tick_floor_applied=_required(item, "tick_floor_applied", owner="FamilyInteractionObservation"),
            close_price=item.get("close_price"),
        ))
