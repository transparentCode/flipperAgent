"""Signal layer typed configurations.

NOTE: After the hyperparam segregation refactor, most fields that were here
are now either:
- Hardcoded module-level constants (in signals/structural.py, temporal.py, etc.)
- Derived at runtime via config/derive.py + config/resolve.py
- Moved to OptimizableDefaults / ResolvedSignalConfig

These dataclasses are kept for backward compatibility. New code should use
ResolvedConfig / ResolvedSignalConfig from config/resolve.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass(frozen=True)
class QualityConfig:
    """Backward-compat stub. Constants now live in signals/quality.py."""
    price_blend_weight: float = 0.5
    agreeing_blend_weight: float = 0.5
    confidence_agreement_base: float = 0.4
    confidence_agreement_scale: float = 0.6
    oscillation_feature_weights: Tuple[float, ...] = (0.5, 0.25, 0.15, 0.10)


@dataclass(frozen=True)
class StateTransitionEntry:
    direction: float
    confidence: float


@dataclass(frozen=True)
class StateTransitionsConfig:
    """Backward-compat stub. Replaced by config/state_transitions.py build_state_transition_table()."""
    none_geometric_bounce_support: StateTransitionEntry = field(default_factory=lambda: StateTransitionEntry(1.0, 0.6))
    none_geometric_bounce_resistance: StateTransitionEntry = field(default_factory=lambda: StateTransitionEntry(-1.0, 0.6))
    none_structural_breakout: StateTransitionEntry = field(default_factory=lambda: StateTransitionEntry(1.0, 0.5))
    none_structural_breakdown: StateTransitionEntry = field(default_factory=lambda: StateTransitionEntry(-1.0, 0.5))
    geometric_bounce_support_structural_breakdown: StateTransitionEntry = field(default_factory=lambda: StateTransitionEntry(-1.0, 0.85))
    geometric_bounce_resistance_structural_breakout: StateTransitionEntry = field(default_factory=lambda: StateTransitionEntry(1.0, 0.85))
    geometric_bounce_support_none: StateTransitionEntry = field(default_factory=lambda: StateTransitionEntry(-0.3, 0.4))
    geometric_bounce_resistance_none: StateTransitionEntry = field(default_factory=lambda: StateTransitionEntry(0.3, 0.4))
    structural_breakout_none: StateTransitionEntry = field(default_factory=lambda: StateTransitionEntry(-0.6, 0.65))
    structural_breakdown_none: StateTransitionEntry = field(default_factory=lambda: StateTransitionEntry(0.6, 0.65))
    structural_breakout_geometric_bounce_resistance: StateTransitionEntry = field(default_factory=lambda: StateTransitionEntry(-0.8, 0.75))
    structural_breakdown_geometric_bounce_support: StateTransitionEntry = field(default_factory=lambda: StateTransitionEntry(0.8, 0.75))
    structural_breakout_geometric_bounce_support: StateTransitionEntry = field(default_factory=lambda: StateTransitionEntry(-0.9, 0.8))
    structural_breakdown_geometric_bounce_resistance: StateTransitionEntry = field(default_factory=lambda: StateTransitionEntry(0.9, 0.8))

    def as_dict(self) -> Dict[Tuple[str, str], Tuple[float, float]]:
        """Returns {(state1, state2): (direction, confidence)} for temporal logic."""
        return {
            ("NONE", "GEOMETRIC_BOUNCE_SUPPORT"): (self.none_geometric_bounce_support.direction, self.none_geometric_bounce_support.confidence),
            ("NONE", "GEOMETRIC_BOUNCE_RESISTANCE"): (self.none_geometric_bounce_resistance.direction, self.none_geometric_bounce_resistance.confidence),
            ("NONE", "STRUCTURAL_BREAKOUT"): (self.none_structural_breakout.direction, self.none_structural_breakout.confidence),
            ("NONE", "STRUCTURAL_BREAKDOWN"): (self.none_structural_breakdown.direction, self.none_structural_breakdown.confidence),
            ("GEOMETRIC_BOUNCE_SUPPORT", "STRUCTURAL_BREAKDOWN"): (self.geometric_bounce_support_structural_breakdown.direction, self.geometric_bounce_support_structural_breakdown.confidence),
            ("GEOMETRIC_BOUNCE_RESISTANCE", "STRUCTURAL_BREAKOUT"): (self.geometric_bounce_resistance_structural_breakout.direction, self.geometric_bounce_resistance_structural_breakout.confidence),
            ("GEOMETRIC_BOUNCE_SUPPORT", "NONE"): (self.geometric_bounce_support_none.direction, self.geometric_bounce_support_none.confidence),
            ("GEOMETRIC_BOUNCE_RESISTANCE", "NONE"): (self.geometric_bounce_resistance_none.direction, self.geometric_bounce_resistance_none.confidence),
            ("STRUCTURAL_BREAKOUT", "NONE"): (self.structural_breakout_none.direction, self.structural_breakout_none.confidence),
            ("STRUCTURAL_BREAKDOWN", "NONE"): (self.structural_breakdown_none.direction, self.structural_breakdown_none.confidence),
            ("STRUCTURAL_BREAKOUT", "GEOMETRIC_BOUNCE_RESISTANCE"): (self.structural_breakout_geometric_bounce_resistance.direction, self.structural_breakout_geometric_bounce_resistance.confidence),
            ("STRUCTURAL_BREAKDOWN", "GEOMETRIC_BOUNCE_SUPPORT"): (self.structural_breakdown_geometric_bounce_support.direction, self.structural_breakdown_geometric_bounce_support.confidence),
            ("STRUCTURAL_BREAKOUT", "GEOMETRIC_BOUNCE_SUPPORT"): (self.structural_breakout_geometric_bounce_support.direction, self.structural_breakout_geometric_bounce_support.confidence),
            ("STRUCTURAL_BREAKDOWN", "GEOMETRIC_BOUNCE_RESISTANCE"): (self.structural_breakdown_geometric_bounce_resistance.direction, self.structural_breakdown_geometric_bounce_resistance.confidence),
        }


@dataclass(frozen=True)
class StructuralSignalConfig:
    """Slimmed — only optimizable/derived params remain. Constants now in signals/structural.py."""
    asymmetry_threshold: float = 0.3
    squeeze_threshold: float = 3.0
    full_confidence_touches: float = 5.0


@dataclass(frozen=True)
class TemporalSignalConfig:
    """Slimmed — only derived params remain. Constants now in signals/temporal.py."""
    min_history: int = 3
    slope_match_tol: float = 0.05
    convergence_rate_threshold: float = 0.2
    slope_accel_threshold: float = 0.01


@dataclass(frozen=True)
class PatternSignalConfig:
    """Slimmed — only derived params remain. Constants now in signals/patterns.py."""
    parallel_tol: float = 0.02
    flat_tol: float = 0.01
    full_confidence_touches: float = 8.0


@dataclass(frozen=True)
class FakeoutSignalConfig:
    hold_bars: int = 3
    volume_lookback: int = 20
    wick_rejection_ratio: float = 0.5


@dataclass(frozen=True)
class SignalConfig:
    quality: QualityConfig = field(default_factory=QualityConfig)
    state_transitions: StateTransitionsConfig = field(default_factory=StateTransitionsConfig)
    structural: StructuralSignalConfig = field(default_factory=StructuralSignalConfig)
    temporal: TemporalSignalConfig = field(default_factory=TemporalSignalConfig)
    pattern: PatternSignalConfig = field(default_factory=PatternSignalConfig)
    fakeout: FakeoutSignalConfig = field(default_factory=FakeoutSignalConfig)
    default_weight: float = 1.0
    weights: Tuple[Tuple[str, float], ...] = ()

    def weights_as_dict(self) -> Dict[str, float]:
        return dict(self.weights)
