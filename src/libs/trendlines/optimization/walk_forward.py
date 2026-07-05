"""Walk-forward cross-validation for trendlines optimisation.

Provides the same ``WalkForwardValidator`` interface as the regression module
but delegates to the existing trendlines temporal split infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

import pandas as pd

from app.trendlines.data import TemporalSplitSpec, build_temporal_split_manifest


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
    """Rolling walk-forward cross-validator for time series.

    Structure per fold::

        |--- train ---|--- purge ---|--- test ---|
        Then step forward by step_bars.
    """

    def __init__(
        self,
        train_bars: int = 2160,
        test_bars: int = 720,
        step_bars: int = 720,
        purge_bars: int = 24,
        min_train_bars: int = 1440,
    ):
        self.train_bars = train_bars
        self.test_bars = test_bars
        self.step_bars = step_bars
        self.purge_bars = purge_bars
        self.min_train_bars = min_train_bars

    def n_folds(self, n_bars: int) -> int:
        splits = self.get_splits(n_bars)
        return len(splits)

    def get_splits(self, n_bars: int) -> List[WalkForwardSplit]:
        spec = TemporalSplitSpec(
            split_kind="walk_forward",
            train_bars=self.train_bars,
            test_bars=self.test_bars,
            step_bars=self.step_bars,
            purge_bars=self.purge_bars,
            min_train_bars=self.min_train_bars,
            policy_name="optimization",
            policy_version="v1",
        )
        manifest = build_temporal_split_manifest(n_bars, spec)
        splits = []
        for i, fold in enumerate(manifest.folds):
            splits.append(WalkForwardSplit(
                fold_id=i,
                train_start=fold.train_start,
                train_end=fold.train_end,
                test_start=fold.test_start,
                test_end=fold.test_end,
            ))
        return splits

    def iterate_splits(
        self, df: pd.DataFrame,
    ) -> Iterator[Tuple[WalkForwardSplit, pd.DataFrame, pd.DataFrame]]:
        """Yield ``(split, train_df, test_df)`` for each fold."""
        n_bars = len(df)
        for split in self.get_splits(n_bars):
            train_df = df.iloc[split.train_start:split.train_end].copy()
            test_df = df.iloc[split.test_start:split.test_end].copy()
            yield split, train_df, test_df
