"""Frozen contracts for descriptive regression geometry context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .channel import StructuralChannelEstimate


class ResidualRegion(str, Enum):
    """The five regions defined by one structural residual channel."""

    BELOW_OUTER = "BELOW_OUTER"
    LOWER_OUTER_BAND = "LOWER_OUTER_BAND"
    INNER_CHANNEL = "INNER_CHANNEL"
    UPPER_OUTER_BAND = "UPPER_OUTER_BAND"
    ABOVE_OUTER = "ABOVE_OUTER"


@dataclass(frozen=True)
class RegressionContextSnapshot:
    """Immutable current channel geometry and one-step causal context."""

    channel: StructuralChannelEstimate
    context_id: str
    region: ResidualRegion
    outer_channel_position: float
    inner_width_log: float
    outer_width_log: float
    inner_width_fraction: float
    outer_width_fraction: float
    upper_outer_breach: bool
    lower_outer_breach: bool
    previous_region: ResidualRegion | None
    reentered_from_upper_outer: bool | None
    reentered_from_lower_outer: bool | None
