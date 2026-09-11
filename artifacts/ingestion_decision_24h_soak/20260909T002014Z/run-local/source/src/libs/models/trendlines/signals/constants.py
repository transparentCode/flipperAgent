"""Constants for trendlines-native signal extraction."""

from __future__ import annotations

from typing import Dict, FrozenSet, Tuple

from libs.models.trendlines.boundary import INTERACTION_DIRECTION, interaction_direction

BULLISH_INTERACTIONS: FrozenSet[str] = frozenset(
    {
        "GEOMETRIC_BOUNCE_SUPPORT",
        "STRUCTURAL_BREAKOUT",
    }
)

BEARISH_INTERACTIONS: FrozenSet[str] = frozenset(
    {
        "GEOMETRIC_BOUNCE_RESISTANCE",
        "STRUCTURAL_BREAKDOWN",
    }
)

BREAKOUT_STATES: FrozenSet[str] = frozenset(
    {
        "STRUCTURAL_BREAKOUT",
        "STRUCTURAL_BREAKDOWN",
    }
)

INSIDE_STATES: FrozenSet[str] = frozenset(
    {
        "NONE",
        "GEOMETRIC_BOUNCE_SUPPORT",
        "GEOMETRIC_BOUNCE_RESISTANCE",
    }
)

STATE_TRANSITIONS: Dict[Tuple[str, str], Tuple[float, float]] = {}

__all__ = [
    "BEARISH_INTERACTIONS",
    "BREAKOUT_STATES",
    "BULLISH_INTERACTIONS",
    "INSIDE_STATES",
    "INTERACTION_DIRECTION",
    "STATE_TRANSITIONS",
    "interaction_direction",
]