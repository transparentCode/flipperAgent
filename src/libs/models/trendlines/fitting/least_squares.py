"""Deterministic least-squares trendline fitter."""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.trendlines.pivots import FractalPivotExtractor, PivotExtractor
from app.trendlines.fitting.base import register_fitter
from app.trendlines.contracts import PivotSet, Trendline, TrendlineFitResult
from app.trendlines.config import GridSearchConfig


_cfg = GridSearchConfig().least_squares

@register_fitter(
    "least_squares",
    search_grid=[
        {
            "fitter": {
                "name": "least_squares",
                "params": {
                    "pivot_window": pw,
                    "residual_threshold_atr": rt,
                },
            }
        }
        for pw, rt in itertools.product(_cfg.pivot_windows, _cfg.residual_thresholds)
    ],
)
@dataclass
class LeastSquaresFitter:
    """Fit support and resistance lines with ordinary least squares."""

    pivot_window: int = 3
    pivot_extractor: PivotExtractor | None = None
    residual_threshold_atr: float = 0.5
    atr_window: int = 14

    def fit(self, df: pd.DataFrame, pivots: PivotSet | None = None) -> TrendlineFitResult:
        self._validate_frame(df)

        if pivots is None:
            extractor = self._resolve_extractor()
            pivot_set = extractor.extract(df)
            extractor_name = extractor.__class__.__name__
        else:
            pivot_set = pivots
            extractor_name = "provided"

        atr = self._compute_atr(df)
        support_line = self._fit_side(
            pivot_indices=pivot_set.low_indices,
            pivot_values=pivot_set.low_values,
            atr=atr,
            is_support=True,
            n_bars=len(df),
        )
        resistance_line = self._fit_side(
            pivot_indices=pivot_set.high_indices,
            pivot_values=pivot_set.high_values,
            atr=atr,
            is_support=False,
            n_bars=len(df),
        )

        support_lines = [support_line] if support_line is not None else []
        resistance_lines = [resistance_line] if resistance_line is not None else []
        return TrendlineFitResult(
            support_lines=support_lines,
            resistance_lines=resistance_lines,
            is_valid=bool(support_lines or resistance_lines),
            metadata={
                "method": "least_squares",
                "extractor": extractor_name,
                "n_rows": len(df),
                "residual_threshold_atr": self.residual_threshold_atr,
            },
        )

    def _resolve_extractor(self) -> PivotExtractor:
        if self.pivot_extractor is not None:
            return self.pivot_extractor
        return FractalPivotExtractor(
            window_left=self.pivot_window,
            window_right=self.pivot_window,
        )

    def _validate_frame(self, df: pd.DataFrame) -> None:
        required_columns = {"open", "high", "low", "close"}
        missing = sorted(required_columns.difference(df.columns))
        if missing:
            raise ValueError(
                f"LeastSquaresFitter requires columns {sorted(required_columns)}; missing {missing}"
            )
        if self.pivot_window < 1:
            raise ValueError("pivot_window must be >= 1")
        if self.residual_threshold_atr < 0:
            raise ValueError("residual_threshold_atr must be >= 0")

    def _compute_atr(self, df: pd.DataFrame) -> np.ndarray:
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        previous_close = np.concatenate(([close[0]], close[:-1]))
        true_range = np.maximum.reduce(
            [
                high - low,
                np.abs(high - previous_close),
                np.abs(low - previous_close),
            ]
        )
        return pd.Series(true_range).rolling(self.atr_window, min_periods=1).mean().to_numpy(dtype=float)

    def _fit_side(
        self,
        *,
        pivot_indices: np.ndarray,
        pivot_values: np.ndarray,
        atr: np.ndarray,
        is_support: bool,
        n_bars: int,
    ) -> Trendline | None:
        if len(pivot_indices) < 2:
            return None

        x = pivot_indices.astype(float)
        y = pivot_values.astype(float)
        slope, intercept = np.polyfit(x, y, 1)
        fitted = slope * x + intercept
        ss_res = float(np.sum((y - fitted) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r_squared = 0.0 if ss_tot <= 1e-12 else max(0.0, min(1.0, 1.0 - ss_res / ss_tot))

        threshold = self.residual_threshold_atr * np.maximum(atr[pivot_indices.astype(int)], 1e-9)
        inlier_mask = np.abs(y - fitted) <= threshold
        inlier_x = x[inlier_mask]
        inlier_count = int(np.sum(inlier_mask))

        start_index = int(np.min(x))
        end_index = int(np.max(x))
        coverage = float((end_index - start_index) / max(n_bars - 1, 1))

        metadata = {
            "inlier_count": inlier_count,
            "inlier_ratio": float(inlier_count / max(len(x), 1)),
            "coverage": coverage,
            "r_squared": r_squared,
            "inlier_indices": [int(index) for index in pivot_indices[inlier_mask].tolist()],
        }

        return Trendline(
            start_index=start_index,
            end_index=end_index,
            start_value=float(slope * start_index + intercept),
            end_value=float(slope * end_index + intercept),
            slope=float(slope),
            intercept=float(intercept),
            touch_count=max(inlier_count, 2),
            is_support=is_support,
            method="least_squares",
            score=r_squared,
            metadata=metadata,
        )


__all__ = ["LeastSquaresFitter"]