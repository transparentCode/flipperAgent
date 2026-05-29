"""Tests for WalkForwardSplitter."""

import pytest

from libs.optim_utils.walk_forward import WalkForwardSplit, WalkForwardSplitter


class TestWalkForwardSplitter:
    def test_split_boundaries_correct(self):
        """train + purge + val + purge + oos = n_bars."""
        splitter = WalkForwardSplitter(purge_bars=24)
        n_bars = 17520  # ~2 years of 1h data
        split = splitter.split(n_bars)

        total = (
            split.train_size
            + 24  # purge between train and val
            + split.val_size
            + 24  # purge between val and oos
            + split.oos_size
        )
        assert total == n_bars
        assert split.oos_end == n_bars

    def test_split_ratios_respected(self):
        """Segment sizes match 60/20/20 ratios ± 1 bar."""
        splitter = WalkForwardSplitter(purge_bars=24)
        n_bars = 17520
        split = splitter.split(n_bars)

        usable = n_bars - 2 * 24
        assert abs(split.train_size - int(usable * 0.60)) <= 1
        assert abs(split.val_size - int(usable * 0.20)) <= 1
        # OOS gets remainder, so it's always exact
        assert split.train_size + split.val_size + split.oos_size == usable

    def test_purge_gap_exact(self):
        """val_start == train_end + purge_bars."""
        splitter = WalkForwardSplitter(purge_bars=24)
        split = splitter.split(17520)

        assert split.val_start == split.train_end + 24
        assert split.oos_start == split.val_end + 24

    def test_insufficient_data_raises(self):
        """n_bars < minimum → ValueError."""
        splitter = WalkForwardSplitter(purge_bars=24)
        with pytest.raises(ValueError, match="Insufficient data"):
            splitter.split(100)  # needs >= 148

    def test_custom_ratios(self):
        """70/15/15 split."""
        splitter = WalkForwardSplitter(
            train_ratio=0.70, val_ratio=0.15, oos_ratio=0.15, purge_bars=10
        )
        n_bars = 1000
        split = splitter.split(n_bars)

        usable = n_bars - 2 * 10
        assert abs(split.train_size - int(usable * 0.70)) <= 1
        assert abs(split.val_size - int(usable * 0.15)) <= 1
        total = split.train_size + split.val_size + split.oos_size + 2 * 10
        assert total == n_bars

    def test_zero_purge(self):
        """purge_bars=0 is valid."""
        splitter = WalkForwardSplitter(purge_bars=0)
        split = splitter.split(200)

        assert split.val_start == split.train_end
        assert split.oos_start == split.val_end
        total = split.train_size + split.val_size + split.oos_size
        assert total == 200
