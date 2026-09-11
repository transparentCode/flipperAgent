"""
Walk-Forward Cross-Validation for Regression Optimization.

Time-series aware splits with purge gap to prevent data leakage.
Zero v1 dependencies — pure pandas/numpy interface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("app.regression.optimization")


@dataclass
class WalkForwardSplit:
    """Describes a single train/test fold."""

    fold_id: int
    train_start: int
    train_end: int  # exclusive
    test_start: int
    test_end: int  # exclusive

    @property
    def train_size(self) -> int:
        return self.train_end - self.train_start

    @property
    def test_size(self) -> int:
        return self.test_end - self.test_start


class WalkForwardValidator:
    """
    Rolling walk-forward cross-validator for time series.

    Structure per fold:
        |--- train (train_bars) ---|--- purge (purge_bars) ---|--- test (test_bars) ---|
        Then step forward by step_bars.

    Usage
    -----
    wf = WalkForwardValidator(train_bars=4320, test_bars=720, step_bars=720, purge_bars=24)
    for split, train_df, test_df in wf.iterate_splits(df):
        score = evaluate(train_df, test_df)
    """

    def __init__(
        self,
        train_bars: int = 4320,
        test_bars: int = 720,
        step_bars: int = 720,
        purge_bars: int = 24,
        min_train_bars: int = 2160,
    ):
        self.train_bars = train_bars
        self.test_bars = test_bars
        self.step_bars = step_bars
        self.purge_bars = purge_bars
        self.min_train_bars = min_train_bars

    def n_folds(self, n_bars: int) -> int:
        if n_bars < self.min_train_bars * 2:
            raise ValueError(f"Insufficient data for walk-forward validation: {n_bars} bars available, need at least {self.min_train_bars * 2}.")
            
        train_bars = min(self.train_bars, int(n_bars * 0.6))
        usable = n_bars - train_bars - self.purge_bars
        if usable < self.test_bars:
            return 0
        return max(1, (usable - self.test_bars) // self.step_bars + 1)

    def get_splits(self, n_bars: int) -> List[WalkForwardSplit]:
        """Return all fold descriptors for a dataset of n_bars."""
        if n_bars < self.min_train_bars * 2:
            raise ValueError(f"Insufficient data for walk-forward validation: {n_bars} bars available, need at least {self.min_train_bars * 2}.")

        train_bars = min(self.train_bars, int(n_bars * 0.6))
        splits: List[WalkForwardSplit] = []
        fold_id = 0
        train_start = 0

        while True:
            train_end = train_start + train_bars
            test_start = train_end + self.purge_bars
            test_end = test_start + self.test_bars

            if test_end > n_bars:
                break
            if (train_end - train_start) < self.min_train_bars:
                break

            splits.append(WalkForwardSplit(
                fold_id=fold_id,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            ))
            train_start += self.step_bars
            fold_id += 1

        return splits

    def iterate_splits(
        self, df: pd.DataFrame,
    ) -> Iterator[Tuple[WalkForwardSplit, pd.DataFrame, pd.DataFrame]]:
        """Yield (split, train_df, test_df) for each fold."""
        n_bars = len(df)
        for split in self.get_splits(n_bars):
            train_df = df.iloc[split.train_start:split.train_end].copy()
            test_df = df.iloc[split.test_start:split.test_end].copy()
            yield split, train_df, test_df

    def expanding_window_splits(
        self,
        n_bars: int,
        initial_train_bars: Optional[int] = None,
    ) -> List[WalkForwardSplit]:
        """Expanding (anchored) window: train_start always at 0, train grows."""
        initial = initial_train_bars or self.train_bars
        splits: List[WalkForwardSplit] = []
        fold_id = 0
        train_end = initial

        while True:
            test_start = train_end + self.purge_bars
            test_end = test_start + self.test_bars

            if test_end > n_bars:
                break
            if train_end < self.min_train_bars:
                break

            splits.append(WalkForwardSplit(
                fold_id=fold_id,
                train_start=0,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            ))
            train_end += self.step_bars
            fold_id += 1

        return splits
