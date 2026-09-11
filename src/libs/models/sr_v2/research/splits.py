"""Chronological, purged, embargoed research split validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

from ..contracts import require_utc


@dataclass(frozen=True, slots=True, kw_only=True)
class ChronologicalSplits:
    development_train: tuple[datetime, datetime]
    calibration: tuple[datetime, datetime]
    validation: tuple[datetime, datetime]
    protected_holdout: tuple[datetime, datetime]
    embargo: timedelta
    lineage_intervals: tuple[tuple[datetime, datetime], ...] = ()


def validate_splits(splits: ChronologicalSplits, *, max_horizon: timedelta) -> ChronologicalSplits:
    if not isinstance(splits, ChronologicalSplits):
        raise TypeError("splits must be ChronologicalSplits")
    if splits.embargo < max_horizon:
        raise ValueError("split embargo must cover maximum horizon")
    windows = (
        splits.development_train,
        splits.calibration,
        splits.validation,
        splits.protected_holdout,
    )
    for start, end in windows:
        require_utc(start, field_name="split start")
        require_utc(end, field_name="split end")
        if end <= start:
            raise ValueError("split end must follow start")
    for previous, current in pairwise(windows):
        if current[0] < previous[1] + splits.embargo:
            raise ValueError("chronological splits overlap or violate embargo")
    for start, end in splits.lineage_intervals:
        require_utc(start, field_name="lineage start")
        require_utc(end, field_name="lineage end")
        if end <= start:
            raise ValueError("lineage interval must be positive")
        memberships = [
            index
            for index, (window_start, window_end) in enumerate(windows)
            if window_start <= start and end <= window_end
        ]
        if len(memberships) != 1:
            raise ValueError("lineage observation interval crosses a research split or embargo")
    return splits


def purge_lineage_intervals(
    intervals: tuple[tuple[datetime, datetime], ...],
    *,
    boundary: datetime,
    embargo: timedelta,
) -> tuple[tuple[datetime, datetime], ...]:
    """Drop lineages touching a boundary or its embargo window."""

    require_utc(boundary, field_name="boundary")
    if embargo < timedelta(0):
        raise ValueError("embargo must be non-negative")
    lower = boundary - embargo
    upper = boundary + embargo
    return tuple(
        interval
        for interval in intervals
        if interval[1] <= lower or interval[0] >= upper
    )


__all__ = ["ChronologicalSplits", "purge_lineage_intervals", "validate_splits"]
