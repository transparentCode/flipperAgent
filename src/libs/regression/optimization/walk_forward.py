"""
Walk-Forward Cross-Validation for V2 Regression Optimization.
Implements a strict 3-way split: Train -> Validate -> OOS.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

logger = logging.getLogger("app.regression.optimization")

class InsufficientDataError(Exception):
    pass

@dataclass
class WalkForwardSplit3Way:
    """Describes a single Train / Validate / OOS fold."""
    fold_id: int
    train_start: int
    train_end: int  # exclusive
    val_start: int
    val_end: int    # exclusive
    test_start: int
    test_end: int   # exclusive

    @property
    def train_size(self) -> int:
        return self.train_end - self.train_start

    @property
    def val_size(self) -> int:
        return self.val_end - self.val_start

    @property
    def test_size(self) -> int:
        return self.test_end - self.test_start


class WalkForwardValidator:
    """
    Rolling 3-way walk-forward cross-validator.

    Structure per fold:
    |-- train --|- purge -|-- validate --|- purge -|-- test --|
    Then step forward by step_bars.
    """

    def __init__(
        self,
        train_bars: int = 4320,
        validate_bars: int = 720,
        test_bars: int = 720,
        step_bars: int = 720,
        purge_bars: int = 24,
        min_train_bars: int = 2160,
        max_train_ratio: float = 0.6,
        expanding_window: bool = False,
    ):
        self.train_bars = train_bars
        self.validate_bars = validate_bars
        self.test_bars = test_bars
        self.step_bars = step_bars
        self.purge_bars = purge_bars
        self.min_train_bars = min_train_bars
        self.max_train_ratio = max_train_ratio
        self.expanding_window = expanding_window

    def get_splits(self, n_bars: int) -> List[WalkForwardSplit3Way]:
        """Return all 3-way fold descriptors for a dataset of n_bars."""
        if n_bars < self.min_train_bars + self.validate_bars + self.test_bars + (self.purge_bars * 2):
            raise InsufficientDataError(
                f"Insufficient data for 3-way walk-forward: {n_bars} bars available."
            )

        max_train = min(self.train_bars, int(n_bars * self.max_train_ratio))
        splits: List[WalkForwardSplit3Way] = []
        fold_id = 0

        if self.expanding_window:
            # Expanding: train always starts at 0, grows each fold
            train_start = 0
            # First fold: use max_train or available, then expand
            fold_end_cursor = max_train
            while True:
                train_end = fold_end_cursor
                if (train_end - train_start) < self.min_train_bars:
                    break

                val_start = train_end + self.purge_bars
                val_end = val_start + self.validate_bars
                test_start = val_end + self.purge_bars
                test_end = test_start + self.test_bars

                if test_end > n_bars:
                    break

                splits.append(WalkForwardSplit3Way(
                    fold_id=fold_id,
                    train_start=train_start,
                    train_end=train_end,
                    val_start=val_start,
                    val_end=val_end,
                    test_start=test_start,
                    test_end=test_end,
                ))
                fold_end_cursor += self.step_bars
                fold_id += 1
        else:
            # Fixed-size: train window moves forward each fold
            train_start = 0
            while True:
                train_end = train_start + max_train

                val_start = train_end + self.purge_bars
                val_end = val_start + self.validate_bars
                test_start = val_end + self.purge_bars
                test_end = test_start + self.test_bars

                if test_end > n_bars:
                    break
                if (train_end - train_start) < self.min_train_bars:
                    break

                splits.append(WalkForwardSplit3Way(
                    fold_id=fold_id,
                    train_start=train_start,
                    train_end=train_end,
                    val_start=val_start,
                    val_end=val_end,
                    test_start=test_start,
                    test_end=test_end,
                ))
                train_start += self.step_bars
                fold_id += 1

        if not splits:
            raise InsufficientDataError("Could not generate any valid folds.")

        return splits
