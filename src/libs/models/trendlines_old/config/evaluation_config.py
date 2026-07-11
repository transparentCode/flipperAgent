"""Evaluation and pipeline workflow typed configurations."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class FitnessConfig:
    slope_tolerance: float = 0.25
    min_tolerance_atr_frac: float = 0.1
    consecutive_penetration_bars: int = 3
    forward_lookahead_bars: int = 3
    touch_accuracy_floor: float = 0.01
    pivot_count_min: int = 5
    pivot_density_min: float = 2.0
    pivot_density_optimal_lo: float = 8.0
    pivot_density_optimal_hi: float = 25.0
    line_count_penalty_threshold: int = 6
    line_count_penalty_factor: float = 0.1


@dataclass(frozen=True)
class WalkForwardDefaults:
    train_bars: int = 2160
    test_bars: int = 720
    step_bars: int = 720
    purge_bars: int = 24
    min_train_bars: int = 1440
    auto_split_tiers: Tuple[Tuple[int, int, int], ...] = (
        (96, 14, 3),   # >= 96 daily bars: 14 days train, 3 days test
        (24, 30, 7),   # >= 24 daily bars: 30 days train, 7 days test
        (6, 60, 14),   # >= 6 daily bars: 60 days train, 14 days test
    )
    auto_split_fallback: Tuple[int, int] = (200, 50)


@dataclass(frozen=True)
class LookbackGridConfig:
    fractions: Tuple[float, ...] = (0.4, 0.6, 0.8)
    min_bars: int = 20


@dataclass(frozen=True)
class DriftMonitorConfig:
    threshold: float = 0.15


@dataclass(frozen=True)
class EvaluationConfig:
    fitness: FitnessConfig = field(default_factory=FitnessConfig)
    walk_forward: WalkForwardDefaults = field(default_factory=WalkForwardDefaults)
    lookback_grid: LookbackGridConfig = field(default_factory=LookbackGridConfig)
    drift_monitor: DriftMonitorConfig = field(default_factory=DriftMonitorConfig)
