"""SR candidate-level contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ._validation import _number, _string
from .bars import SRStateKey, _state_key
from .errors import ContractValidationError
from .geometry import ZoneGeometry, _geometry
from .identity import hash_candidate_level, require_utc
from .zones import ZoneSide, _side


@dataclass(frozen=True)
class CandidateLevel:
    state_key: SRStateKey
    side: ZoneSide
    geometry: ZoneGeometry
    source: str
    formed_at: datetime
    available_at: datetime
    atr_at_creation: float
    candidate_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_key", _state_key(self.state_key))
        object.__setattr__(self, "side", _side(self.side))
        object.__setattr__(self, "geometry", _geometry(self.geometry))
        object.__setattr__(self, "source", _string(self.source, field_name="source"))
        object.__setattr__(
            self, "formed_at", require_utc(self.formed_at, field_name="formed_at")
        )
        object.__setattr__(
            self,
            "available_at",
            require_utc(self.available_at, field_name="available_at"),
        )
        object.__setattr__(
            self,
            "atr_at_creation",
            _number(
                self.atr_at_creation,
                field_name="atr_at_creation",
                minimum=0.0,
            ),
        )
        if self.atr_at_creation <= 0:
            raise ContractValidationError("atr_at_creation must be positive")
        if self.available_at < self.formed_at:
            raise ContractValidationError("available_at must be >= formed_at")
        object.__setattr__(self, "candidate_id", hash_candidate_level(self))


__all__ = ["CandidateLevel"]
