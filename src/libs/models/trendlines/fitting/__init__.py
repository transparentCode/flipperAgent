"""Trendline fitter implementations and base contracts."""

from app.trendlines.fitting.base import FITTER_REGISTRY, TrendlineFitter, register_fitter
from app.trendlines.fitting.ensemble import EnsembleFitter
from app.trendlines.fitting.least_squares import LeastSquaresFitter
from app.trendlines.fitting.pathfinding import PathfindingFitter
from app.trendlines.fitting.ransac import RansacFitter

__all__ = [
    "EnsembleFitter",
    "FITTER_REGISTRY",
    "LeastSquaresFitter",
    "PathfindingFitter",
    "RansacFitter",
    "TrendlineFitter",
    "register_fitter",
]
