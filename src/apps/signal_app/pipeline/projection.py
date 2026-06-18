"""Helpers for building decision-timeframe projections from source bars."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math

from libs.common.timeframes import timeframe_to_seconds
from libs.contracts.signal import StreamOHLCVPayload

BarTuple = tuple[float, ...]


@dataclass(frozen=True)
class ProjectedBar:
    bar: BarTuple
    bucket_start: float
    bucket_end: float
    source_timeframe: str
    decision_timeframe: str
    closed: bool

    def to_candle(
        self,
        *,
        asset: str,
        base_timeframe: str,
        provider: str,
        origin: str,
        ingestion_timestamp: float = 0.0,
        publication_lag_ms: int = 0,
    ) -> StreamOHLCVPayload:
        return StreamOHLCVPayload(
            symbol=asset,
            timeframe=self.decision_timeframe,
            timestamp=self.bucket_start,
            open=float(self.bar[0]),
            high=float(self.bar[1]),
            low=float(self.bar[2]),
            close=float(self.bar[3]),
            volume=float(self.bar[4]),
            taker_buy_base=float(self.bar[6]) if len(self.bar) > 6 else 0.0,
            bar_closed=self.closed,
            base_timeframe=base_timeframe,
            bar_span_seconds=timeframe_to_seconds(self.decision_timeframe),
            close_timestamp=self.bucket_end,
            ingestion_timestamp=ingestion_timestamp,
            publication_lag_ms=publication_lag_ms,
            provider=provider,
            origin=origin,
        )


def project_current_decision_bar(
    source_bars: Sequence[BarTuple],
    *,
    decision_timeframe: str,
    source_timeframe: str,
) -> ProjectedBar | None:
    if not source_bars:
        return None

    decision_seconds = max(timeframe_to_seconds(decision_timeframe), 1)
    source_seconds = max(timeframe_to_seconds(source_timeframe), 1)
    latest_ts = float(source_bars[-1][5])
    bucket_start = math.floor(latest_ts / decision_seconds) * decision_seconds
    bucket_end = bucket_start + decision_seconds
    window = [
        bar for bar in source_bars
        if bucket_start <= float(bar[5]) < bucket_end
    ]
    if not window:
        return None

    taker_buy_total = sum(float(bar[6]) if len(bar) > 6 else 0.0 for bar in window)
    projected_tuple: BarTuple = (
        float(window[0][0]),
        max(float(bar[1]) for bar in window),
        min(float(bar[2]) for bar in window),
        float(window[-1][3]),
        sum(float(bar[4]) for bar in window),
        bucket_start,
        taker_buy_total,
    )
    source_close_ts = latest_ts + source_seconds
    return ProjectedBar(
        bar=projected_tuple,
        bucket_start=bucket_start,
        bucket_end=bucket_end,
        source_timeframe=source_timeframe,
        decision_timeframe=decision_timeframe,
        closed=source_close_ts >= bucket_end,
    )


__all__ = ["BarTuple", "ProjectedBar", "project_current_decision_bar"]
