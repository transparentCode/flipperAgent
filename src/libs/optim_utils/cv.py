"""Purged k-fold cross-validation for time-series data."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class CVFold:
    """A single cross-validation fold."""

    fold_idx: int
    train_df: pd.DataFrame
    test_df: pd.DataFrame


def purged_kfold_cv(
    df: pd.DataFrame,
    n_splits: int = 5,
    embargo_bars: int = 50,
) -> list[CVFold]:
    """Purged walk-forward k-fold cross-validation for time series.

    Splits data into *n_splits* contiguous blocks.  For each fold *i*:
      - Train = blocks[0 : i] (all blocks before test)
      - Embargo = last *embargo_bars* rows removed from train
      - Test  = blocks[i]

    This is expanding-window: earlier folds have less training data.
    Fold 0 is skipped because it has no training data.

    Parameters
    ----------
    df : pd.DataFrame
        Time-sorted feature DataFrame.
    n_splits : int
        Number of folds (default 5).
    embargo_bars : int
        Bars removed from the end of the training set to prevent
        look-ahead from stateful indicator computation.

    Returns
    -------
    list[CVFold]
        Folds 1 through n_splits-1.
    """
    n = len(df)
    block_size = n // n_splits
    if block_size == 0:
        return []

    folds: list[CVFold] = []
    for i in range(1, n_splits):
        test_start = i * block_size
        test_end = (i + 1) * block_size if i < n_splits - 1 else n

        train_end = max(0, test_start - embargo_bars)
        if train_end <= 0:
            continue

        train_df = df.iloc[:train_end]
        test_df = df.iloc[test_start:test_end]

        if len(train_df) == 0 or len(test_df) == 0:
            continue

        folds.append(CVFold(fold_idx=i, train_df=train_df, test_df=test_df))

    return folds
