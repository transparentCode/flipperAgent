"""Tests for purged k-fold CV."""

from __future__ import annotations

import pandas as pd
import pytest

from libs.optim_utils.cv import CVFold, purged_kfold_cv


def _make_df(n: int) -> pd.DataFrame:
    """Create a simple DataFrame with n rows."""
    return pd.DataFrame({"close": range(n), "ts": range(n)})


class TestPurgedKfoldCV:

    def test_fold_count(self):
        df = _make_df(500)
        folds = purged_kfold_cv(df, n_splits=5, embargo_bars=10)
        # Fold 0 skipped → 4 folds
        assert len(folds) == 4

    def test_no_temporal_overlap(self):
        df = _make_df(1000)
        folds = purged_kfold_cv(df, n_splits=5, embargo_bars=20)
        for fold in folds:
            train_idx = set(fold.train_df.index.tolist())
            test_idx = set(fold.test_df.index.tolist())
            assert train_idx.isdisjoint(test_idx), f"Overlap in fold {fold.fold_idx}"

    def test_embargo_gap(self):
        df = _make_df(1000)
        embargo = 30
        folds = purged_kfold_cv(df, n_splits=5, embargo_bars=embargo)
        for fold in folds:
            if len(fold.train_df) == 0:
                continue
            train_last = fold.train_df.index[-1]
            test_first = fold.test_df.index[0]
            assert test_first - train_last >= embargo, (
                f"Embargo gap too small in fold {fold.fold_idx}: "
                f"train_last={train_last}, test_first={test_first}"
            )

    def test_expanding_window(self):
        df = _make_df(1000)
        folds = purged_kfold_cv(df, n_splits=5, embargo_bars=10)
        train_sizes = [len(f.train_df) for f in folds]
        for i in range(1, len(train_sizes)):
            assert train_sizes[i] >= train_sizes[i - 1], (
                "Training window should be expanding"
            )

    def test_empty_df(self):
        df = _make_df(0)
        folds = purged_kfold_cv(df, n_splits=5)
        assert folds == []

    def test_too_few_rows(self):
        df = _make_df(3)
        folds = purged_kfold_cv(df, n_splits=5, embargo_bars=50)
        assert folds == []

    def test_fold_type(self):
        df = _make_df(500)
        folds = purged_kfold_cv(df, n_splits=5, embargo_bars=10)
        for fold in folds:
            assert isinstance(fold, CVFold)
            assert isinstance(fold.train_df, pd.DataFrame)
            assert isinstance(fold.test_df, pd.DataFrame)
