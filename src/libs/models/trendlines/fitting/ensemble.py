"""Ensemble fitter that pools lines from pathfinding, least-squares, and RANSAC.

Each sub-fitter produces at most 1 support + 1 resistance line. The ensemble
runs all three on the same pivot set and deduplicates near-identical lines,
yielding up to 3 support + 3 resistance lines per call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from app.trendlines.contracts import PivotSet, Trendline, TrendlineFitResult
from app.trendlines.fitting.base import register_fitter
from app.trendlines.fitting.least_squares import LeastSquaresFitter
from app.trendlines.fitting.pathfinding import PathfindingFitter
from app.trendlines.fitting.ransac import RansacFitter
from app.trendlines.pivots import FractalPivotExtractor, PivotExtractor

logger = logging.getLogger(__name__)


def _slope_intercept_similar(
    a: Trendline,
    b: Trendline,
    slope_atol: float,
    intercept_atol: float,
) -> bool:
    """Return True when two lines are near-identical in slope/intercept space."""
    return (
        abs(a.slope - b.slope) <= slope_atol
        and abs(a.intercept - b.intercept) <= intercept_atol
    )


def _deduplicate(
    lines: List[Trendline],
    slope_atol: float,
    intercept_atol: float,
) -> List[Trendline]:
    """Remove near-duplicate lines, keeping the one with the higher score."""
    if len(lines) <= 1:
        return list(lines)

    # Sort descending by score so the first occurrence is the best.
    ranked = sorted(lines, key=lambda ln: ln.score, reverse=True)
    kept: List[Trendline] = []
    for candidate in ranked:
        if not any(
            _slope_intercept_similar(candidate, existing, slope_atol, intercept_atol)
            for existing in kept
        ):
            kept.append(candidate)
    return kept


@register_fitter("ensemble")
@dataclass
class EnsembleFitter:
    """Meta-fitter that pools lines from all three registered fitters.

    Parameters
    ----------
    pivot_window : int
        Shared pivot-window for every sub-fitter.
    slope_dedup_atol : float
        Absolute tolerance on slope difference for dedup (per-bar units).
    intercept_dedup_atr_frac : float
        Intercept similarity threshold expressed as a fraction of mean ATR.
    pathfinding_line_fit_mode : str
        Final-line construction mode for the pathfinding sub-fitter.
    """

    pivot_window: int = 3
    pivot_extractor: PivotExtractor | None = None
    slope_dedup_atol: float = 1e-4
    intercept_dedup_atr_frac: float = 0.15
    pathfinding_line_fit_mode: str = "endpoint"

    def fit(self, df: pd.DataFrame, pivots: PivotSet | None = None) -> TrendlineFitResult:
        self._validate_frame(df)

        if pivots is None:
            extractor = self._resolve_extractor()
            pivot_set = extractor.extract(df)
            extractor_name = extractor.__class__.__name__
        else:
            pivot_set = pivots
            extractor_name = "provided"

        # Build sub-fitters with shared pivot_window.
        sub_fitters: List[tuple[str, Any]] = [
            (
                "pathfinding",
                PathfindingFitter(
                    pivot_window=self.pivot_window,
                    line_fit_mode=self.pathfinding_line_fit_mode,
                ),
            ),
            ("least_squares", LeastSquaresFitter(pivot_window=self.pivot_window)),
            ("ransac", RansacFitter(pivot_window=self.pivot_window)),
        ]

        all_support: List[Trendline] = []
        all_resistance: List[Trendline] = []
        sub_meta: Dict[str, Any] = {}

        for name, fitter in sub_fitters:
            try:
                result = fitter.fit(df, pivots=pivot_set)
            except Exception as exc:
                logger.debug("EnsembleFitter: %s failed: %s", name, exc)
                sub_meta[name] = {"error": str(exc)}
                continue

            all_support.extend(result.support_lines)
            all_resistance.extend(result.resistance_lines)
            sub_meta[name] = {
                "n_support": len(result.support_lines),
                "n_resistance": len(result.resistance_lines),
            }

        # Compute ATR-based intercept tolerance for dedup.
        mean_atr = self._mean_atr(df)
        intercept_atol = self.intercept_dedup_atr_frac * mean_atr

        support_deduped = _deduplicate(all_support, self.slope_dedup_atol, intercept_atol)
        resistance_deduped = _deduplicate(all_resistance, self.slope_dedup_atol, intercept_atol)

        return TrendlineFitResult(
            support_lines=support_deduped,
            resistance_lines=resistance_deduped,
            is_valid=bool(support_deduped or resistance_deduped),
            metadata={
                "method": "ensemble",
                "extractor": extractor_name,
                "n_rows": len(df),
                "sub_fitters": sub_meta,
                "pre_dedup_support": len(all_support),
                "pre_dedup_resistance": len(all_resistance),
                "pathfinding_line_fit_mode": self.pathfinding_line_fit_mode,
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_extractor(self) -> PivotExtractor:
        if self.pivot_extractor is not None:
            return self.pivot_extractor
        return FractalPivotExtractor(
            window_left=self.pivot_window,
            window_right=self.pivot_window,
        )

    def _validate_frame(self, df: pd.DataFrame) -> None:
        required = {"open", "high", "low", "close"}
        missing = sorted(required.difference(df.columns))
        if missing:
            raise ValueError(
                f"EnsembleFitter requires columns {sorted(required)}; missing {missing}"
            )
        if self.pathfinding_line_fit_mode not in {"endpoint", "ols_on_path"}:
            raise ValueError("pathfinding_line_fit_mode must be one of: endpoint, ols_on_path")

    @staticmethod
    def _mean_atr(df: pd.DataFrame, period: int = 14) -> float:
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        prev_close = np.concatenate(([close[0]], close[:-1]))
        tr = np.maximum.reduce([
            high - low,
            np.abs(high - prev_close),
            np.abs(low - prev_close),
        ])
        atr = pd.Series(tr).rolling(period, min_periods=1).mean().to_numpy(dtype=float)
        return float(max(np.nanmean(atr), 1e-9))
