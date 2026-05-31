"""
Walk-Forward Cross-Validation for Regime Optimization.

Time-series aware splits with purge gap to prevent data leakage.

Classes:
  WalkForwardSplit      — descriptor for a single fold
  WalkForwardValidator  — rolling/expanding window split generator + evaluator
  CombinatorialPurgedCV — combinatorial purged CV (CPCV) for advanced use
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from typing import Callable, Iterator, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("app.regime")


@dataclass
class WalkForwardSplit:
    """Describes a single train/test fold."""
    fold_id: int
    train_start: int
    train_end: int    # exclusive
    test_start: int
    test_end: int     # exclusive

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
        purge_hours: Optional[float] = None,
        timeframe: Optional[str] = None,
    ):
        self.train_bars = train_bars
        self.test_bars = test_bars
        self.step_bars = step_bars
        self.min_train_bars = min_train_bars

        # Compute purge_bars from purge_hours + timeframe if both provided
        if purge_hours is not None and timeframe is not None:
            import math
            from app.regime.orchestrator import timeframe_to_hours
            bar_hours = timeframe_to_hours(timeframe)
            self.purge_bars = max(1, math.ceil(purge_hours / bar_hours))
        else:
            self.purge_bars = purge_bars

    def n_folds(self, n_bars: int) -> int:
        usable = n_bars - self.train_bars - self.purge_bars
        if usable < self.test_bars:
            return 0
        return max(1, (usable - self.test_bars) // self.step_bars + 1)

    def get_splits(self, n_bars: int) -> List[WalkForwardSplit]:
        """Return all fold descriptors for a dataset of n_bars."""
        splits = []
        fold_id = 0
        train_start = 0

        while True:
            train_end = train_start + self.train_bars
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
        self, df: pd.DataFrame
    ) -> Iterator[Tuple[WalkForwardSplit, pd.DataFrame, pd.DataFrame]]:
        """Yield (split, train_df, test_df) for each fold."""
        n_bars = len(df)
        for split in self.get_splits(n_bars):
            train_df = df.iloc[split.train_start : split.train_end].copy()
            test_df = df.iloc[split.test_start : split.test_end].copy()
            yield split, train_df, test_df

    def expanding_window_splits(
        self,
        n_bars: int,
        initial_train_bars: Optional[int] = None,
    ) -> List[WalkForwardSplit]:
        """
        Expanding (anchored) window: train_start always at 0, train grows each fold.
        """
        initial_train = initial_train_bars or self.min_train_bars
        splits = []
        fold_id = 0
        train_end = initial_train

        while True:
            test_start = train_end + self.purge_bars
            test_end = test_start + self.test_bars

            if test_end > n_bars:
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

    def validate_params_across_folds(
        self,
        df: pd.DataFrame,
        params: dict,
        evaluation_fn: Callable[[pd.DataFrame, pd.DataFrame, dict], float],
    ) -> float:
        """
        Run evaluation_fn on every fold and return mean score.

        evaluation_fn(train_df, test_df, params) -> float
        """
        fold_scores = []
        for split, train_df, test_df in self.iterate_splits(df):
            try:
                score = evaluation_fn(train_df, test_df, params)
                fold_scores.append(float(score))
            except Exception as exc:
                logger.warning("Fold %d failed: %s", split.fold_id, exc)
                fold_scores.append(0.0)

        valid_scores = [s for s in fold_scores if np.isfinite(s)]
        return float(np.mean(valid_scores)) if valid_scores else 0.0

    def summary(self, n_bars: int) -> dict:
        splits = self.get_splits(n_bars)
        return {
            "n_folds": len(splits),
            "total_train_bars": sum(s.train_size for s in splits),
            "total_test_bars": sum(s.test_size for s in splits),
            "train_bars": self.train_bars,
            "test_bars": self.test_bars,
            "purge_bars": self.purge_bars,
            "step_bars": self.step_bars,
            "first_test_start": splits[0].test_start if splits else None,
            "last_test_end": splits[-1].test_end if splits else None,
        }


class CombinatorialPurgedCV:
    """
    Combinatorial Purged Cross-Validation (CPCV).

    Groups bars into n_splits blocks; each combination of (n_splits - k) blocks
    forms a training set, the remaining k blocks form the test set.
    Purge gap applied around each test block to prevent leakage.

    Reference: López de Prado (2018), Advances in Financial Machine Learning.
    """

    def __init__(
        self,
        n_splits: int = 5,
        purge_bars: int = 24,
        embargo_bars: int = 12,
        purge_hours: Optional[float] = None,
        embargo_hours: Optional[float] = None,
        timeframe: Optional[str] = None,
    ):
        self.n_splits = n_splits

        # Compute bar counts from hours + timeframe if provided
        if timeframe is not None:
            import math
            from app.regime.orchestrator import timeframe_to_hours
            bar_hours = timeframe_to_hours(timeframe)
            self.purge_bars = (
                max(1, math.ceil(purge_hours / bar_hours))
                if purge_hours is not None else purge_bars
            )
            self.embargo_bars = (
                max(1, math.ceil(embargo_hours / bar_hours))
                if embargo_hours is not None else embargo_bars
            )
        else:
            self.purge_bars = purge_bars
            self.embargo_bars = embargo_bars

    def get_splits(
        self, n_bars: int, test_groups: int = 2
    ) -> List[Tuple[np.ndarray, np.ndarray]]:
        """
        Return (train_indices, test_indices) for each combinatorial fold.

        Parameters
        ----------
        n_bars      : total number of bars
        test_groups : number of groups held out as test per fold (default 2)
        """
        group_size = n_bars // self.n_splits
        groups: List[np.ndarray] = [
            np.arange(i * group_size, min((i + 1) * group_size, n_bars))
            for i in range(self.n_splits)
        ]

        splits = []
        for test_combo in itertools.combinations(range(self.n_splits), test_groups):
            test_indices = np.concatenate([groups[i] for i in test_combo])
            train_groups = [g for i, g in enumerate(groups) if i not in test_combo]
            train_indices_list = []
            for g in train_groups:
                purged = [
                    idx for idx in g
                    if all(
                        abs(idx - t) > self.purge_bars + self.embargo_bars
                        for t in test_indices
                    )
                ]
                train_indices_list.extend(purged)

            train_indices = np.array(sorted(train_indices_list))
            if len(train_indices) > 0 and len(test_indices) > 0:
                splits.append((train_indices, test_indices))

        return splits
