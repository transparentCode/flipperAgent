"""Boundary adapter typed configurations."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BoundaryAdapterConfig:
    interaction_tolerance_atr: float = 0.25
    atr_window: int = 14
