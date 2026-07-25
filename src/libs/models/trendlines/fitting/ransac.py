"""Local RANSAC-style trendline fitter for the trendlines module."""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.trendlines.pivots import FractalPivotExtractor, PivotExtractor
from app.trendlines.fitting.base import register_fitter
from app.trendlines.contracts import PivotSet, Trendline, TrendlineFitResult
from app.trendlines.config import GridSearchConfig


_cfg = GridSearchConfig().ransac

@register_fitter(
    "ransac",
    search_grid=[
        {
            "fitter": {
                "name": "ransac",
                "params": {
                    "pivot_window": pw,
                    "residual_threshold_atr": rt,
                    "max_cut_fraction": mc,
                },
            }
        }
        for pw, rt, mc in itertools.product(_cfg.pivot_windows, _cfg.residual_thresholds, _cfg.max_cut_fractions)
    ],
)
@dataclass
class RansacFitter:
    """Fit support and resistance lines using pair-sampled robust regression."""

    pivot_window: int = 3
    pivot_extractor: PivotExtractor | None = None
    residual_threshold_atr: float = 0.5
    max_trials: int = 250
    max_cut_fraction: float = 0.15
    min_coverage: float = 0.3
    atr_window: int = 14
    seed: int | None = 42

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
        body_highs = np.maximum(df["open"].to_numpy(dtype=float), df["close"].to_numpy(dtype=float))
        body_lows = np.minimum(df["open"].to_numpy(dtype=float), df["close"].to_numpy(dtype=float))

        support_line = self._fit_side(
            pivot_indices=pivot_set.low_indices,
            pivot_values=pivot_set.low_values,
            atr=atr,
            body_highs=body_highs,
            body_lows=body_lows,
            is_support=True,
        )
        resistance_line = self._fit_side(
            pivot_indices=pivot_set.high_indices,
            pivot_values=pivot_set.high_values,
            atr=atr,
            body_highs=body_highs,
            body_lows=body_lows,
            is_support=False,
        )

        support_lines = [support_line] if support_line is not None else []
        resistance_lines = [resistance_line] if resistance_line is not None else []
        return TrendlineFitResult(
            support_lines=support_lines,
            resistance_lines=resistance_lines,
            is_valid=bool(support_lines or resistance_lines),
            metadata={
                "method": "ransac",
                "extractor": extractor_name,
                "n_rows": len(df),
                "max_trials": self.max_trials,
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
                f"RansacFitter requires columns {sorted(required_columns)}; missing {missing}"
            )
        if self.max_trials < 1:
            raise ValueError("max_trials must be >= 1")
        if self.pivot_window < 1:
            raise ValueError("pivot_window must be >= 1")

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
        body_highs: np.ndarray,
        body_lows: np.ndarray,
        is_support: bool,
    ) -> Trendline | None:
        if len(pivot_indices) < 2:
            return None

        rng = np.random.default_rng(self.seed)
        n_points = len(pivot_indices)
        n_bars = len(body_highs)
        mean_atr = float(max(np.nanmean(atr), 1e-9))
        cut_tolerance = self.residual_threshold_atr * mean_atr

        best_candidate: dict[str, float | np.ndarray] | None = None

        for _ in range(self.max_trials):
            sampled = rng.choice(n_points, size=2, replace=False)
            idx_a, idx_b = sorted(sampled.tolist())
            x1 = float(pivot_indices[idx_a])
            x2 = float(pivot_indices[idx_b])
            if abs(x2 - x1) < 1e-9:
                continue
            y1 = float(pivot_values[idx_a])
            y2 = float(pivot_values[idx_b])

            slope = (y2 - y1) / (x2 - x1)
            intercept = y1 - slope * x1
            projected = slope * pivot_indices.astype(float) + intercept
            threshold = self.residual_threshold_atr * np.maximum(atr[pivot_indices.astype(int)], 1e-9)
            residuals = np.abs(pivot_values - projected)
            inlier_mask = residuals <= threshold
            inlier_count = int(np.sum(inlier_mask))
            if inlier_count < 2:
                continue

            inlier_indices = pivot_indices[inlier_mask].astype(float)
            coverage = float((np.max(inlier_indices) - np.min(inlier_indices)) / max(n_bars - 1, 1))
            if coverage < self.min_coverage:
                continue

            all_x = np.arange(n_bars, dtype=float)
            projected_all = slope * all_x + intercept
            if is_support:
                cuts = int(np.sum(body_lows < (projected_all - cut_tolerance)))
            else:
                cuts = int(np.sum(body_highs > (projected_all + cut_tolerance)))
            cut_fraction = cuts / max(n_bars, 1)
            if cut_fraction > self.max_cut_fraction:
                continue

            inlier_ratio = inlier_count / max(n_points, 1)
            score = float(inlier_ratio * coverage * (1.0 - cut_fraction))
            if best_candidate is None or score > float(best_candidate["score"]):
                best_candidate = {
                    "slope": slope,
                    "intercept": intercept,
                    "score": score,
                    "inlier_mask": inlier_mask,
                    "coverage": coverage,
                    "cut_fraction": cut_fraction,
                    "inlier_ratio": inlier_ratio,
                }

        if best_candidate is None:
            return None

        inlier_mask = best_candidate["inlier_mask"]
        inlier_x = pivot_indices[inlier_mask].astype(float)
        inlier_y = pivot_values[inlier_mask].astype(float)

        if len(inlier_x) >= 2:
            slope, intercept = np.polyfit(inlier_x, inlier_y, 1)
        else:
            slope = float(best_candidate["slope"])
            intercept = float(best_candidate["intercept"])

        fitted = slope * inlier_x + intercept
        ss_res = float(np.sum((inlier_y - fitted) ** 2))
        ss_tot = float(np.sum((inlier_y - np.mean(inlier_y)) ** 2))
        r_squared = 0.0 if ss_tot <= 1e-12 else max(0.0, min(1.0, 1.0 - ss_res / ss_tot))

        start_index = int(np.min(inlier_x))
        end_index = int(np.max(inlier_x))
        start_value = float(slope * start_index + intercept)
        end_value = float(slope * end_index + intercept)

        return Trendline(
            start_index=start_index,
            end_index=end_index,
            start_value=start_value,
            end_value=end_value,
            slope=float(slope),
            intercept=float(intercept),
            touch_count=int(np.sum(inlier_mask)),
            is_support=is_support,
            method="ransac",
            score=float(best_candidate["score"]),
            metadata={
                "coverage": float(best_candidate["coverage"]),
                "cut_fraction": float(best_candidate["cut_fraction"]),
                "inlier_ratio": float(best_candidate["inlier_ratio"]),
                "r_squared": r_squared,
                "inlier_indices": [int(index) for index in pivot_indices[inlier_mask].tolist()],
            },
        )


__all__ = ["RansacFitter"]