"""RDP-based ZigZag pivot extractor for the trendlines module."""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.trendlines.pivots.base import register_extractor
from app.trendlines.contracts import PivotSet


from app.trendlines.config import GridSearchConfig

_cfg = GridSearchConfig().rdp_zigzag

@register_extractor(
    "rdp_zigzag",
    search_grid=[
        {
            "extractor": {
                "name": "rdp_zigzag",
                "params": {"epsilon_atr": epsilon_atr, "min_segment_bars": min_segment_bars},
            }
        }
        for epsilon_atr, min_segment_bars in itertools.product(
            _cfg.epsilon_atr_values, _cfg.min_segment_bars_values
        )
    ],
)
@dataclass
class RDPZigZagPivotExtractor:
    """Extract swing pivots by simplifying the close path with RDP."""

    epsilon_atr: float = 0.5
    min_segment_bars: int = 3
    atr_window: int = 14

    def extract(self, df: pd.DataFrame) -> PivotSet:
        self._validate_frame(df)

        closes = df["close"].to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        n_rows = len(df)
        if n_rows < 4:
            return self._empty_pivot_set()

        atr = self._compute_atr(df)
        mean_atr = float(np.nanmean(atr)) if len(atr) else 0.0
        epsilon = max(mean_atr * self.epsilon_atr, 1e-9)

        x = np.arange(n_rows, dtype=float)
        kept = self._rdp_iterative(x, closes, epsilon)
        if len(kept) < 3:
            return self._empty_pivot_set()

        high_indices: list[int] = []
        low_indices: list[int] = []
        last_accepted_bar = int(kept[0])

        for position in range(1, len(kept) - 1):
            index = int(kept[position])
            prev_index = int(kept[position - 1])
            next_index = int(kept[position + 1])
            if (index - last_accepted_bar) < self.min_segment_bars:
                continue

            value = closes[index]
            prev_value = closes[prev_index]
            next_value = closes[next_index]

            if value > prev_value and value > next_value:
                high_indices.append(index)
                last_accepted_bar = index
            elif value < prev_value and value < next_value:
                low_indices.append(index)
                last_accepted_bar = index

        high_idx_array = np.array(high_indices, dtype=int)
        low_idx_array = np.array(low_indices, dtype=int)
        return PivotSet(
            high_indices=high_idx_array,
            high_values=highs[high_idx_array] if len(high_idx_array) else np.array([], dtype=float),
            low_indices=low_idx_array,
            low_values=lows[low_idx_array] if len(low_idx_array) else np.array([], dtype=float),
        )

    def _validate_frame(self, df: pd.DataFrame) -> None:
        required_columns = {"high", "low", "close"}
        missing = sorted(required_columns.difference(df.columns))
        if missing:
            raise ValueError(
                f"RDPZigZagPivotExtractor requires columns {sorted(required_columns)}; missing {missing}"
            )
        if self.epsilon_atr < 0:
            raise ValueError("epsilon_atr must be >= 0")
        if self.min_segment_bars < 1:
            raise ValueError("min_segment_bars must be >= 1")
        if self.atr_window < 1:
            raise ValueError("atr_window must be >= 1")

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

    @staticmethod
    def _rdp_iterative(x: np.ndarray, y: np.ndarray, epsilon: float) -> np.ndarray:
        n_rows = len(x)
        if n_rows <= 2:
            return np.arange(n_rows, dtype=int)

        keep = np.zeros(n_rows, dtype=bool)
        keep[0] = True
        keep[-1] = True
        stack: list[tuple[int, int]] = [(0, n_rows - 1)]

        while stack:
            start, end = stack.pop()
            if end - start < 2:
                continue

            dx = x[end] - x[start]
            dy = y[end] - y[start]
            segment_length_sq = dx * dx + dy * dy
            max_distance = 0.0
            max_index = start

            for index in range(start + 1, end):
                if segment_length_sq < 1e-12:
                    distance = np.sqrt((x[index] - x[start]) ** 2 + (y[index] - y[start]) ** 2)
                else:
                    cross = abs(dy * (x[index] - x[start]) - dx * (y[index] - y[start]))
                    distance = cross / np.sqrt(segment_length_sq)
                if distance > max_distance:
                    max_distance = distance
                    max_index = index

            if max_distance > epsilon:
                keep[max_index] = True
                stack.append((start, max_index))
                stack.append((max_index, end))

        return np.where(keep)[0].astype(int)

    @staticmethod
    def _empty_pivot_set() -> PivotSet:
        return PivotSet(
            high_indices=np.array([], dtype=int),
            high_values=np.array([], dtype=float),
            low_indices=np.array([], dtype=int),
            low_values=np.array([], dtype=float),
        )


__all__ = ["RDPZigZagPivotExtractor"]
