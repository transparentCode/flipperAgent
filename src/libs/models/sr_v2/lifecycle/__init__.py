"""Deterministic immutable zone lifecycle transitions."""

from .engine import (
    advance_zone,
    apply_candidates_with_replacements,
)
from .rules import LifecycleRules
from .transitions import LifecycleTransition, TransitionType

__all__ = [
    "LifecycleRules",
    "LifecycleTransition",
    "TransitionType",
    "advance_zone",
    "apply_candidates_with_replacements",
]
