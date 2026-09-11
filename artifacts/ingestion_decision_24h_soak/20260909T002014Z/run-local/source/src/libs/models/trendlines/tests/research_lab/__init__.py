"""Shared deterministic fixtures for research-lab tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from libs.models.trendlines.research_lab import (
    TrendlineReplayWindow,
    run_research_lab,
    synthetic_lab_controls,
)


def session_for(timeframes: tuple[str, ...] = ("1h",), include_signals: bool = True):
    """Build one small, isolated mutable session for one focused test."""

    windows = {
        timeframe: TrendlineReplayWindow(19, 20, 31, 1)
        for timeframe in timeframes
    }
    controls = synthetic_lab_controls(
        asset="BTCUSDT",
        timeframes=timeframes,
        primary_timeframe=timeframes[0],
        seed=7,
        start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        bar_counts={timeframe: 32 for timeframe in timeframes},
        replay_windows=windows,
        include_signals=include_signals,
        viewer_lookback_bars=16,
        start_inline_viewers=False,
        permanent_export=False,
    )
    return asyncio.run(run_research_lab(controls))
