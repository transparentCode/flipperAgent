"""Fractal-style pivot extractor for the trendlines module."""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from libs.models.trendlines.pivots.base import register_extractor
from libs.models.trendlines.pivots.capabilities import (
    ExtractorCapabilities,
    PivotFinality,
    TrendlineExecutionMode,
)
from libs.models.trendlines.contracts import PivotSet
from libs.models.trendlines.config import GridSearchConfig


_cfg = GridSearchConfig().fractal

@register_extractor(
    "fractal",
    capabilities=ExtractorCapabilities(
        supported_modes=frozenset(
            {TrendlineExecutionMode.RUNTIME, TrendlineExecutionMode.RESEARCH}
        ),
        finality=PivotFinality.CONFIRMED_APPEND_ONLY,
    ),
    search_grid=[
        {"extractor": {"name": "fractal", "params": {"window_left": wl, "window_right": wr}}}
        for wl, wr in itertools.product(_cfg.left_windows, _cfg.right_windows)
    ],
)
@dataclass
class FractalPivotExtractor:
    """Extract swing highs and lows using exact left/right window comparison."""

    window_left: int = 3
    window_right: int = 3

    def extract(self, df: pd.DataFrame) -> PivotSet:
        self._validate_frame(df)

        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        window_size = self.window_left + 1 + self.window_right

        if len(df) < window_size:
            return PivotSet(
                high_indices=np.array([], dtype=int),
                high_values=np.array([], dtype=float),
                low_indices=np.array([], dtype=int),
                low_values=np.array([], dtype=float),
            )

        high_windows = sliding_window_view(highs, window_shape=window_size)
        low_windows = sliding_window_view(lows, window_shape=window_size)
        core_slice = slice(self.window_left, len(df) - self.window_right)

        is_high_core = highs[core_slice] == np.max(high_windows, axis=1)
        is_low_core = lows[core_slice] == np.min(low_windows, axis=1)

        high_mask = np.zeros(len(df), dtype=bool)
        low_mask = np.zeros(len(df), dtype=bool)
        high_mask[core_slice] = is_high_core
        low_mask[core_slice] = is_low_core

        high_indices = self._select_closed_plateau_midpoints(np.flatnonzero(high_mask), highs)
        low_indices = self._select_closed_plateau_midpoints(np.flatnonzero(low_mask), lows)

        return PivotSet(
            high_indices=high_indices,
            high_values=highs[high_indices],
            low_indices=low_indices,
            low_values=lows[low_indices],
        )

    def _validate_frame(self, df: pd.DataFrame) -> None:
        required_columns = {"high", "low"}
        missing = sorted(required_columns.difference(df.columns))
        if missing:
            raise ValueError(
                f"FractalPivotExtractor requires columns {sorted(required_columns)}; missing {missing}"
            )
        if self.window_left < 0 or self.window_right < 0:
            raise ValueError("window_left and window_right must be >= 0")

    @staticmethod
    def _select_closed_plateau_midpoints(indices: np.ndarray, values: np.ndarray) -> np.ndarray:
        """Select midpoints only from equal-price runs closed in the frame.

        A terminal or still-continuing equal-price run can gain candidates when
        later bars arrive. Suppressing it until the next raw value differs keeps
        emitted plateau midpoints append-only. ``window_right=0`` therefore has
        an effective one-bar plateau-closure delay.
        """
        if len(indices) <= 1:
            if len(indices) == 0:
                return indices
            last_index = int(indices[0])
            if last_index >= len(values) - 1 or values[last_index + 1] == values[last_index]:
                return np.array([], dtype=int)
            return indices

        groups: list[list[int]] = []
        current_group = [int(indices[0])]
        for index in indices[1:]:
            candidate = int(index)
            if candidate - current_group[-1] == 1 and values[candidate] == values[current_group[0]]:
                current_group.append(candidate)
            else:
                groups.append(current_group)
                current_group = [candidate]
        groups.append(current_group)

        selected: list[int] = []
        for group in groups:
            last_index = group[-1]
            plateau_value = values[group[0]]
            if last_index >= len(values) - 1 or values[last_index + 1] == plateau_value:
                continue
            selected.append(group[len(group) // 2])
        return np.array(selected, dtype=int)


__all__ = ["FractalPivotExtractor"]
