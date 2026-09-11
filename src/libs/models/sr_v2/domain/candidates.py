"""Kernel candidate contract with explicit formed/available timing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from ..contracts import ZoneSide, require_utc


@dataclass(frozen=True, slots=True, kw_only=True)
class Candidate:
    candidate_key: str
    venue: str
    instrument_id: str
    asset: str
    source_timeframe: str
    kernel_id: str
    kernel_version: str
    side: ZoneSide
    center: Decimal
    lower: Decimal
    upper: Decimal
    formed_at: datetime
    available_at: datetime
    source_evidence_id: str
    creation_atr: Decimal

    def __post_init__(self) -> None:
        for name in (
            "candidate_key",
            "venue",
            "instrument_id",
            "asset",
            "source_timeframe",
            "kernel_id",
            "kernel_version",
            "source_evidence_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if not isinstance(self.side, ZoneSide):
            raise TypeError("side must be ZoneSide")
        for name in ("center", "lower", "upper", "creation_atr"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise TypeError(f"{name} must be a finite Decimal")
        if self.creation_atr <= 0:
            raise ValueError("creation_atr must be positive")
        if self.lower > self.center or self.center > self.upper:
            raise ValueError("candidate geometry must satisfy lower <= center <= upper")
        require_utc(self.formed_at, field_name="formed_at")
        require_utc(self.available_at, field_name="available_at")
        if self.available_at < self.formed_at:
            raise ValueError("available_at cannot precede formed_at")


__all__ = ["Candidate"]
