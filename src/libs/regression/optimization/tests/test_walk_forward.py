"""
Test for 3-way Walk-Forward Validator in optimization.
"""

import pytest

from app.regression.optimization.walk_forward import WalkForwardValidator


def test_3_way_split():
    # 4320 train, 720 val, 720 test, 24 purge
    # Minimum required data: 2160 + 720 + 720 + 48 = 3648 bars

    validator = WalkForwardValidator(
        train_bars=4320,
        validate_bars=720,
        test_bars=720,
        step_bars=720,
        purge_bars=24,
        min_train_bars=2160,
    )

    # 5000 bars should yield at least 1 fold
    splits = validator.get_splits(5000)
    assert len(splits) > 0, "Should generate at least 1 fold"

    s = splits[0]
    assert s.train_size >= 2160, f"Train size {s.train_size} too small"
    assert s.val_size == 720, f"Val size {s.val_size} != 720"
    assert s.test_size == 720, f"Test size {s.test_size} != 720"

    # Check boundaries
    assert s.val_start == s.train_end + 24
    assert s.test_start == s.val_end + 24


def test_insufficient_data_raises():
    validator = WalkForwardValidator(
        train_bars=4320,
        validate_bars=720,
        test_bars=720,
        step_bars=720,
        purge_bars=24,
        min_train_bars=2160,
    )
    with pytest.raises(Exception, match="Insufficient data"):
        validator.get_splits(1000)


def test_max_train_ratio():
    """Custom max_train_ratio limits the train set size."""
    validator = WalkForwardValidator(
        train_bars=10000,
        validate_bars=500,
        test_bars=500,
        step_bars=500,
        purge_bars=10,
        min_train_bars=500,
        max_train_ratio=0.4,
    )
    splits = validator.get_splits(5000)
    assert len(splits) > 0
    for s in splits:
        assert s.train_size <= 2000  # 0.4 * 5000


def test_multiple_folds():
    """Large dataset should generate multiple folds."""
    validator = WalkForwardValidator(
        train_bars=1000,
        validate_bars=200,
        test_bars=200,
        step_bars=200,
        purge_bars=10,
        min_train_bars=500,
    )
    splits = validator.get_splits(5000)
    assert len(splits) >= 3, f"Expected >=3 folds, got {len(splits)}"

    # Folds should not overlap in test windows
    for i in range(len(splits) - 1):
        assert splits[i].test_end <= splits[i + 1].test_start


def test_purge_gap_maintained():
    """Purge gaps between train/val and val/test are always maintained."""
    validator = WalkForwardValidator(
        train_bars=2000,
        validate_bars=500,
        test_bars=500,
        step_bars=500,
        purge_bars=50,
        min_train_bars=1000,
    )
    splits = validator.get_splits(8000)
    for s in splits:
        assert s.val_start - s.train_end >= 50
        assert s.test_start - s.val_end >= 50


def test_expanding_window():
    """Expanding window: train always starts at 0, grows each fold."""
    validator = WalkForwardValidator(
        train_bars=1000,
        validate_bars=200,
        test_bars=200,
        step_bars=200,
        purge_bars=10,
        min_train_bars=500,
        expanding_window=True,
    )
    splits = validator.get_splits(5000)
    assert len(splits) >= 2

    # All folds start at 0
    for s in splits:
        assert s.train_start == 0

    # Each successive fold has a larger train set
    for i in range(1, len(splits)):
        assert splits[i].train_size > splits[i - 1].train_size

    # Purge gaps still maintained
    for s in splits:
        assert s.val_start - s.train_end >= 10
        assert s.test_start - s.val_end >= 10


def test_fixed_window_train_size_constant():
    """Fixed window: all folds have the same train size."""
    validator = WalkForwardValidator(
        train_bars=1000,
        validate_bars=200,
        test_bars=200,
        step_bars=200,
        purge_bars=10,
        min_train_bars=500,
        expanding_window=False,
    )
    splits = validator.get_splits(5000)
    assert len(splits) >= 2
    sizes = {s.train_size for s in splits}
    assert len(sizes) == 1  # All same size
