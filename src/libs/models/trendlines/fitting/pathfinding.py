"""Pathfinding-based trendline fitter.

This is the first fitter extracted into the fresh trendlines module because it
has a small dependency surface and cleanly demonstrates the intended plugin
shape for future fitters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from libs.models.trendlines.pivots import FractalPivotExtractor, PivotExtractor
from libs.models.trendlines.fitting.base import register_fitter
from libs.models.trendlines.contracts import PivotSet, Trendline, TrendlineFitResult
from libs.models.trendlines.config import GridSearchConfig


PathPoint = Tuple[int, float]

_cfg = GridSearchConfig().pathfinding

@register_fitter(
    "pathfinding",
    search_grid=[
        {"fitter": {"name": "pathfinding", "params": {"pivot_window": pw}}}
        for pw in _cfg.pivot_windows
    ],
)
@dataclass
class PathfindingFitter:
    """Fit support and resistance lines using a pivot-path dynamic program."""

    pivot_window: int = 3
    pivot_extractor: PivotExtractor | None = None
    line_fit_mode: str = "endpoint"

    def fit(self, df: pd.DataFrame, pivots: PivotSet | None = None) -> TrendlineFitResult:
        self._validate_frame(df)
        if pivots is None:
            pivot_set = self._resolve_extractor().extract(df)
        else:
            pivot_set = pivots

        resistance_path = self._find_path(
            pivot_indices=pivot_set.high_indices,
            pivot_values=pivot_set.high_values,
            df=df,
            is_support=False,
        )
        support_path = self._find_path(
            pivot_indices=pivot_set.low_indices,
            pivot_values=pivot_set.low_values,
            df=df,
            is_support=True,
        )

        resistance_line = self._build_line(
            path=resistance_path,
            is_support=False,
            total_bars=len(df),
        )
        support_line = self._build_line(
            path=support_path,
            is_support=True,
            total_bars=len(df),
        )

        support_lines = [support_line] if support_line is not None else []
        resistance_lines = [resistance_line] if resistance_line is not None else []
        return TrendlineFitResult(
            support_lines=support_lines,
            resistance_lines=resistance_lines,
            is_valid=bool(support_lines or resistance_lines),
            metadata={
                "method": "pathfinding",
                "pivot_window": self.pivot_window,
                "line_fit_mode": self.line_fit_mode,
                "n_rows": len(df),
                "extractor": "provided" if pivots else self._resolve_extractor().__class__.__name__,
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
                f"PathfindingFitter requires columns {sorted(required_columns)}; missing {missing}"
            )
        if self.pivot_window < 1:
            raise ValueError("pivot_window must be >= 1")
        if self.line_fit_mode not in {"endpoint", "ols_on_path"}:
            raise ValueError("line_fit_mode must be one of: endpoint, ols_on_path")
        if len(df) < (self.pivot_window * 2 + 3):
            raise ValueError("Dataframe is too short for the configured pivot window")

    def _find_path(
        self,
        *,
        pivot_indices,
        pivot_values,
        df: pd.DataFrame,
        is_support: bool,
    ) -> List[PathPoint]:
        opens = df["open"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        if len(pivot_indices) < 2:
            return []

        pivot_price_by_index = {
            int(index): float(value)
            for index, value in zip(pivot_indices.tolist(), pivot_values.tolist())
        }
        dp = {int(pivot): {"score": 0, "prev": -1} for pivot in pivot_indices.tolist()}

        ordered_indices = [int(index) for index in pivot_indices.tolist()]
        for current_pos, current_idx in enumerate(ordered_indices):
            current_value = pivot_price_by_index[current_idx]
            for previous_pos in range(current_pos):
                previous_idx = ordered_indices[previous_pos]
                previous_value = pivot_price_by_index[previous_idx]
                if not self._segment_is_valid(
                    previous_idx=previous_idx,
                    previous_value=previous_value,
                    current_idx=current_idx,
                    current_value=current_value,
                    opens=opens,
                    closes=closes,
                    is_support=is_support,
                ):
                    continue

                segment_length = current_idx - previous_idx
                new_score = dp[previous_idx]["score"] + segment_length
                if new_score > dp[current_idx]["score"]:
                    dp[current_idx]["score"] = new_score
                    dp[current_idx]["prev"] = previous_idx

        best_end = max(dp, key=lambda pivot: dp[pivot]["score"])
        if dp[best_end]["score"] == 0:
            return []

        path: List[PathPoint] = []
        cursor = best_end
        while cursor != -1:
            path.append((cursor, pivot_price_by_index[cursor]))
            cursor = dp[cursor]["prev"]
        path.reverse()
        return path

    def _segment_is_valid(
        self,
        *,
        previous_idx: int,
        previous_value: float,
        current_idx: int,
        current_value: float,
        opens: np.ndarray,
        closes: np.ndarray,
        is_support: bool,
    ) -> bool:
        slope = (current_value - previous_value) / (current_idx - previous_idx)
        intercept = previous_value - slope * previous_idx

        for index in range(previous_idx + 1, current_idx):
            line_value = slope * index + intercept
            body_top = max(opens[index], closes[index])
            body_bottom = min(opens[index], closes[index])
            if is_support:
                if line_value > body_bottom:
                    return False
            else:
                if line_value < body_top:
                    return False
        return True

    def _build_line(
        self,
        *,
        path: Sequence[PathPoint],
        is_support: bool,
        total_bars: int,
    ) -> Optional[Trendline]:
        if len(path) < 2:
            return None

        if self.line_fit_mode == "ols_on_path":
            fit_indices = np.array([point[0] for point in path], dtype=float)
            fit_values = np.array([point[1] for point in path], dtype=float)
            slope, intercept = np.polyfit(fit_indices, fit_values, 1)
            start_index = int(path[0][0])
            end_index = int(path[-1][0])
            start_value = float(slope * start_index + intercept)
            end_value = float(slope * end_index + intercept)
        else:
            start_index, start_value = path[-2]
            end_index, end_value = path[-1]
            slope = (end_value - start_value) / max(end_index - start_index, 1)
            intercept = start_value - slope * start_index
        coverage = 0.0
        if total_bars > 1:
            coverage = (path[-1][0] - path[0][0]) / (total_bars - 1)

        return Trendline(
            start_index=start_index,
            end_index=end_index,
            start_value=start_value,
            end_value=end_value,
            slope=slope,
            intercept=intercept,
            touch_count=len(path),
            is_support=is_support,
            method="pathfinding",
            score=float(max(coverage, 0.0)),
            metadata={
                "path_points": [[index, value] for index, value in path],
                "line_fit_mode": self.line_fit_mode,
                "coverage": float(max(coverage, 0.0)),
            },
        )


__all__ = ["PathfindingFitter"]