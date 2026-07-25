"""Derived state transition table built from market logic.

Replaces the 28-scalar config table with a deterministic derivation from:
1. Interaction direction map (market physics — a bounce off support is always bullish)
2. Three archetype confidence levels (reversal, continuation, fade)

The direction of every transition is computed algebraically from the inherent
direction of the from-state and to-state. The confidence is classified into
one of three archetypes based on the transition type.
"""

from __future__ import annotations

from typing import Dict, Tuple

# Inline interaction directions (market physics — never changes)
_INTERACTION_DIRECTION: Dict[str, float] = {
    "GEOMETRIC_BOUNCE_SUPPORT": 1.0,
    "GEOMETRIC_BOUNCE_RESISTANCE": -1.0,
    "STRUCTURAL_BREAKOUT": 1.0,
    "STRUCTURAL_BREAKDOWN": -1.0,
    "NONE": 0.0,
}

# All meaningful state pairs
_STATE_PAIRS = [
    ("NONE", "GEOMETRIC_BOUNCE_SUPPORT"),
    ("NONE", "GEOMETRIC_BOUNCE_RESISTANCE"),
    ("NONE", "STRUCTURAL_BREAKOUT"),
    ("NONE", "STRUCTURAL_BREAKDOWN"),
    ("GEOMETRIC_BOUNCE_SUPPORT", "STRUCTURAL_BREAKDOWN"),
    ("GEOMETRIC_BOUNCE_RESISTANCE", "STRUCTURAL_BREAKOUT"),
    ("GEOMETRIC_BOUNCE_SUPPORT", "NONE"),
    ("GEOMETRIC_BOUNCE_RESISTANCE", "NONE"),
    ("STRUCTURAL_BREAKOUT", "NONE"),
    ("STRUCTURAL_BREAKDOWN", "NONE"),
    ("STRUCTURAL_BREAKOUT", "GEOMETRIC_BOUNCE_RESISTANCE"),
    ("STRUCTURAL_BREAKDOWN", "GEOMETRIC_BOUNCE_SUPPORT"),
    ("STRUCTURAL_BREAKOUT", "GEOMETRIC_BOUNCE_SUPPORT"),
    ("STRUCTURAL_BREAKDOWN", "GEOMETRIC_BOUNCE_RESISTANCE"),
]


def _classify_transition(from_state: str, to_state: str) -> str:
    """Classify a state pair into reversal / continuation / fade."""
    from_dir = _INTERACTION_DIRECTION.get(from_state, 0.0)
    to_dir = _INTERACTION_DIRECTION.get(to_state, 0.0)

    # Either state is NONE → fade
    if from_dir == 0.0 or to_dir == 0.0:
        return "fade"

    # Opposite direction → reversal
    if (from_dir > 0 and to_dir < 0) or (from_dir < 0 and to_dir > 0):
        return "reversal"

    # Same direction → continuation
    return "continuation"


def _compute_direction(from_state: str, to_state: str) -> float:
    """Derive the directional signal from a state transition.

    Logic:
    - If entering an active state from NONE → direction of the new state
    - If leaving to NONE → damped reversal of the original state
    - If reversing (opposing directions) → direction of the new state, full magnitude
    - If continuing (same direction) → weakened reversal (exhaustion hypothesis for
      structural→geometric same-side transitions)
    """
    from_dir = _INTERACTION_DIRECTION.get(from_state, 0.0)
    to_dir = _INTERACTION_DIRECTION.get(to_state, 0.0)

    # NONE → active: adopt the new state's direction
    if from_dir == 0.0 and to_dir != 0.0:
        return to_dir

    # active → NONE: reversal of old state, damped
    if from_dir != 0.0 and to_dir == 0.0:
        # Structural fades are stronger signals than geometric fades
        magnitude = 0.6 if "STRUCTURAL" in from_state else 0.3
        return -from_dir * magnitude

    # Full reversal (opposing directions)
    if (from_dir > 0 and to_dir < 0) or (from_dir < 0 and to_dir > 0):
        # Structural-to-geometric same sign as to_dir
        is_opposing_structural = (
            ("STRUCTURAL" in from_state and "GEOMETRIC" in to_state)
            or ("GEOMETRIC" in from_state and "STRUCTURAL" in to_state)
        )
        magnitude = 1.0 if is_opposing_structural else 0.9
        return to_dir * magnitude

    # Same-side continuation (e.g., BREAKOUT → same-side BOUNCE)
    # Treat as mild exhaustion signal
    return -from_dir * 0.9


def build_state_transition_table(
    conf_reversal: float = 0.85,
    conf_continuation: float = 0.65,
    conf_fade: float = 0.45,
) -> Dict[Tuple[str, str], Tuple[float, float]]:
    """Build the full transition table from 3 archetype confidences.

    Returns ``{(from_state, to_state): (direction, confidence)}`` for all
    14 meaningful state pairs.

    The 3 confidence archetypes replace the 14 individual confidence values
    that were previously stored in StateTransitionsConfig.
    """
    table: Dict[Tuple[str, str], Tuple[float, float]] = {}

    for from_state, to_state in _STATE_PAIRS:
        archetype = _classify_transition(from_state, to_state)
        direction = _compute_direction(from_state, to_state)

        if archetype == "reversal":
            confidence = conf_reversal
        elif archetype == "continuation":
            confidence = conf_continuation
        else:
            confidence = conf_fade

        # Fade from NONE to active gets slightly higher confidence
        # because it's a fresh signal (market just engaged a level)
        from_dir = _INTERACTION_DIRECTION.get(from_state, 0.0)
        to_dir = _INTERACTION_DIRECTION.get(to_state, 0.0)
        if from_dir == 0.0 and to_dir != 0.0:
            # NONE → active: bumped by ~0.1 since it's a fresh interaction
            if "STRUCTURAL" in to_state:
                confidence = min(1.0, conf_fade + 0.05)
            else:
                confidence = min(1.0, conf_fade + 0.15)

        table[(from_state, to_state)] = (round(direction, 2), round(confidence, 2))

    return table


__all__ = ["build_state_transition_table"]
