"""Walk-forward 3-way temporal splitting with purge bars."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WalkForwardSplit:
    """Index boundaries for a single Train / Validate / OOS fold."""

    train_start: int
    train_end: int  # exclusive
    val_start: int
    val_end: int  # exclusive
    oos_start: int
    oos_end: int  # exclusive

    @property
    def train_size(self) -> int:
        return self.train_end - self.train_start

    @property
    def val_size(self) -> int:
        return self.val_end - self.val_start

    @property
    def oos_size(self) -> int:
        return self.oos_end - self.oos_start


class WalkForwardSplitter:
    """Single-fold 3-way temporal split with purge bars.

    Layout:
    |--- train ---|-- purge --|--- validate ---|-- purge --|--- OOS ---|

    Default ratios: 60% train, 20% validate, 20% OOS.
    Purge bars create a gap between splits to prevent look-ahead leakage
    from lagged indicators (default: 24 bars = 1 day for 1h data).

    NOTE: This is a single-fold splitter, NOT a rolling walk-forward.
    Rolling walk-forward is deferred to a future iteration. A single
    proper split already eliminates the full-dataset overfitting problem.
    """

    def __init__(
        self,
        train_ratio: float = 0.60,
        val_ratio: float = 0.20,
        oos_ratio: float = 0.20,
        purge_bars: int = 24,
    ):
        assert abs(train_ratio + val_ratio + oos_ratio - 1.0) < 1e-6
        self.train_ratio = train_ratio
        self.val_ratio = val_ratio
        self.oos_ratio = oos_ratio
        self.purge_bars = purge_bars

    def split(self, n_bars: int) -> WalkForwardSplit:
        """Compute index boundaries for the 3-way split.

        Raises ValueError if dataset is too small to accommodate
        purge gaps and minimum segment sizes.
        """
        min_bars = 100 + 2 * self.purge_bars
        if n_bars < min_bars:
            raise ValueError(
                f"Insufficient data: {n_bars} bars, need >= {min_bars} "
                f"(100 usable + 2×{self.purge_bars} purge)"
            )

        usable = n_bars - 2 * self.purge_bars
        train_size = int(usable * self.train_ratio)
        val_size = int(usable * self.val_ratio)
        oos_size = usable - train_size - val_size

        train_start = 0
        train_end = train_size
        val_start = train_end + self.purge_bars
        val_end = val_start + val_size
        oos_start = val_end + self.purge_bars
        oos_end = oos_start + oos_size

        return WalkForwardSplit(
            train_start=train_start,
            train_end=train_end,
            val_start=val_start,
            val_end=val_end,
            oos_start=oos_start,
            oos_end=oos_end,
        )
