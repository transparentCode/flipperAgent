"""Trendline fitter implementations and base contracts."""

from libs.models.trendlines.fitting.base import FITTER_REGISTRY, TrendlineFitter, register_fitter
from libs.models.trendlines.fitting.ensemble import EnsembleFitter
from libs.models.trendlines.fitting.least_squares import LeastSquaresFitter
from libs.models.trendlines.fitting.pathfinding import PathfindingFitter
from libs.models.trendlines.fitting.ransac import RansacFitter

__all__ = [
    "EnsembleFitter",
    "FITTER_REGISTRY",
    "LeastSquaresFitter",
    "PathfindingFitter",
    "RansacFitter",
    "TrendlineFitter",
    "register_fitter",
]
