"""ReturnsBuilder — resample equity curve to fixed-interval return series."""

from __future__ import annotations

import math

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import EquityPoint

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


def resample_equity_curve(
    equity_points: list[EquityPoint],
    interval_seconds: int = 3600,
) -> list[EquityPoint]:
    """Resample irregular equity points to a fixed-interval time grid.

    Uses forward-fill (last observation carried forward) for intervals
    with no equity change. Drops leading intervals before first observation.
    """
    if not equity_points or interval_seconds <= 0:
        return []

    sorted_pts = sorted(equity_points, key=lambda p: p.timestamp)
    start_ts = sorted_pts[0].timestamp
    end_ts = sorted_pts[-1].timestamp

    if end_ts <= start_ts:
        return [sorted_pts[0]]

    # Build grid
    grid: list[EquityPoint] = []
    ptr = 0
    current_ts = start_ts

    while current_ts <= end_ts:
        # Advance pointer to the last point at or before current_ts
        while ptr + 1 < len(sorted_pts) and sorted_pts[ptr + 1].timestamp <= current_ts:
            ptr += 1

        src = sorted_pts[ptr]
        grid.append(EquityPoint(
            timestamp=current_ts,
            equity=src.equity,
            balance=src.balance,
            unrealized_pnl=src.unrealized_pnl,
            drawdown_pct=src.drawdown_pct,
            open_position_count=src.open_position_count,
        ))
        current_ts += interval_seconds

    return grid


def compute_log_returns(
    resampled_points: list[EquityPoint],
) -> list[float]:
    """Compute log returns from resampled (fixed-interval) equity points.

    return_i = ln(equity_i / equity_{i-1})
    Skips any interval where previous equity is <= 0.
    """
    if len(resampled_points) < 2:
        return []

    returns: list[float] = []
    for i in range(1, len(resampled_points)):
        prev_eq = resampled_points[i - 1].equity
        curr_eq = resampled_points[i].equity
        if prev_eq > 0:
            returns.append(math.log(curr_eq / prev_eq))
        else:
            returns.append(0.0)
    return returns


def compute_simple_returns(
    resampled_points: list[EquityPoint],
) -> list[float]:
    """Compute simple returns: (equity_i - equity_{i-1}) / equity_{i-1}."""
    if len(resampled_points) < 2:
        return []

    returns: list[float] = []
    for i in range(1, len(resampled_points)):
        prev_eq = resampled_points[i - 1].equity
        if prev_eq > 0:
            returns.append((resampled_points[i].equity - prev_eq) / prev_eq)
        else:
            returns.append(0.0)
    return returns


def get_return_timestamps(
    resampled_points: list[EquityPoint],
) -> list[float]:
    """Get timestamps corresponding to each return (uses the later point's timestamp)."""
    if len(resampled_points) < 2:
        return []
    return [p.timestamp for p in resampled_points[1:]]
