"""Grid search typed configurations."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class FractalSearchGrid:
    left_windows: Tuple[int, ...] = (3, 5, 7, 10)
    right_windows: Tuple[int, ...] = (3, 5, 7, 10)


@dataclass(frozen=True)
class RDPSearchGrid:
    epsilon_atr_values: Tuple[float, ...] = (0.2, 0.3, 0.5, 0.8, 1.0)
    min_segment_bars_values: Tuple[int, ...] = (1, 3, 5)


@dataclass(frozen=True)
class PathfindingSearchGrid:
    pivot_windows: Tuple[int, ...] = (2, 3, 5)


@dataclass(frozen=True)
class LeastSquaresSearchGrid:
    pivot_windows: Tuple[int, ...] = (2, 3, 5)
    residual_thresholds: Tuple[float, ...] = (0.3, 0.5, 0.8)


@dataclass(frozen=True)
class RansacSearchGrid:
    pivot_windows: Tuple[int, ...] = (2, 3)
    residual_thresholds: Tuple[float, ...] = (0.3, 0.5)
    max_cut_fractions: Tuple[float, ...] = (0.1, 0.2)


@dataclass(frozen=True)
class GridSearchConfig:
    fractal: FractalSearchGrid = field(default_factory=FractalSearchGrid)
    rdp_zigzag: RDPSearchGrid = field(default_factory=RDPSearchGrid)
    pathfinding: PathfindingSearchGrid = field(default_factory=PathfindingSearchGrid)
    least_squares: LeastSquaresSearchGrid = field(default_factory=LeastSquaresSearchGrid)
    ransac: RansacSearchGrid = field(default_factory=RansacSearchGrid)
