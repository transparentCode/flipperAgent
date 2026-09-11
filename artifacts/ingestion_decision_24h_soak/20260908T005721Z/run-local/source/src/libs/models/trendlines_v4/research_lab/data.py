"""Data loading, normalization, and canonical V4 analysis helpers."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Mapping
from datetime import UTC, datetime
from numbers import Real
from typing import Any

import pandas as pd

from libs.market_data import BINANCE_KLINE_PAGE_LIMIT, BinanceNativeAdapter
from libs.models.trendlines_v4.core_v2 import (
    HISTORY_CAPACITY_BARS,
    TrendlineBar,
    TrendlineSnapshotV2,
    analyze_trendlines_v2,
)
from libs.models.trendlines_v4.engine.types import TrendlineGeometry

_PRICE_COLUMNS = ("open", "high", "low", "close")
_NORMALIZED_COLUMNS = ("closed_at", *_PRICE_COLUMNS, "volume")


def _utc_datetime(value: object, name: str) -> datetime:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a timestamp")
    if isinstance(value, Real):
        timestamp = pd.to_datetime(value, unit="ms", utc=True)
    else:
        timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return timestamp.tz_convert("UTC").to_pydatetime()


def _timestamp_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_window_boundary(value: datetime | str, name: str) -> datetime:
    return _utc_datetime(value, name)


def _close_times(frame: pd.DataFrame) -> pd.Series:
    if "close_time" in frame.columns:
        raw = frame["close_time"]
        if pd.api.types.is_datetime64_any_dtype(raw):
            return pd.to_datetime(raw, utc=True, errors="raise")
        numeric = pd.to_numeric(raw, errors="coerce")
        if numeric.notna().all():
            return pd.to_datetime(numeric, unit="ms", utc=True, errors="raise")
        return pd.to_datetime(raw, utc=True, errors="raise")
    if "closed_at" in frame.columns:
        return pd.to_datetime(frame["closed_at"], utc=True, errors="raise")
    raise ValueError("frame must contain close_time or closed_at")


def normalize_native_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a validated native-candle frame using close time as cutoff."""

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")
    missing = [column for column in _PRICE_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"frame is missing price columns: {missing}")

    normalized = frame.copy()
    normalized["closed_at"] = _close_times(frame)
    for column in _PRICE_COLUMNS:
        normalized[column] = pd.to_numeric(normalized[column], errors="raise").astype(
            float
        )
    if "volume" in normalized.columns:
        normalized["volume"] = pd.to_numeric(
            normalized["volume"], errors="raise"
        ).astype(float)
    else:
        normalized["volume"] = float("nan")

    normalized = normalized.loc[:, list(_NORMALIZED_COLUMNS)].reset_index(drop=True)
    if normalized["closed_at"].isna().any():
        raise ValueError("closed_at values must be present")
    if normalized["closed_at"].duplicated().any():
        raise ValueError("closed_at values must be unique")
    if not normalized["closed_at"].is_monotonic_increasing:
        raise ValueError("closed_at values must be strictly increasing")
    return normalized


def frame_to_trendline_bars(frame: pd.DataFrame) -> tuple[TrendlineBar, ...]:
    """Convert normalized native candles into the canonical V4 bar contract."""

    normalized = normalize_native_frame(frame)
    return tuple(
        TrendlineBar(
            closed_at=row.closed_at.to_pydatetime(),
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
        )
        for row in normalized.itertuples(index=False)
    )


def _request_native(
    adapter: BinanceNativeAdapter,
    symbol: str,
    timeframe: str,
    start_at: datetime,
    end_at: datetime,
) -> Awaitable[pd.DataFrame] | pd.DataFrame:
    return adapter.get_historical_ohlcv(
        symbol,
        timeframe,
        since=int(start_at.timestamp() * 1000),
        until=int(end_at.timestamp() * 1000),
        limit=BINANCE_KLINE_PAGE_LIMIT,
        include_close_time=True,
    )


def _filter_window(
    frame: pd.DataFrame, start_at: datetime, end_at: datetime
) -> pd.DataFrame:
    normalized = normalize_native_frame(frame)
    mask = normalized["closed_at"].between(
        pd.Timestamp(start_at), pd.Timestamp(end_at), inclusive="both"
    )
    return normalized.loc[mask].reset_index(drop=True)


async def fetch_native_window_async(
    symbol: str,
    timeframe: str,
    start_at: datetime | str,
    end_at: datetime | str,
    *,
    adapter: BinanceNativeAdapter | None = None,
) -> pd.DataFrame:
    """Fetch one bounded native-timeframe window behind explicit notebook opt-in."""

    if not isinstance(symbol, str) or not symbol:
        raise ValueError("symbol must be a non-empty string")
    if not isinstance(timeframe, str) or not timeframe:
        raise ValueError("timeframe must be a non-empty native timeframe")
    start = _parse_window_boundary(start_at, "start_at")
    end = _parse_window_boundary(end_at, "end_at")
    if end < start:
        raise ValueError("end_at must not precede start_at")
    source = adapter if adapter is not None else BinanceNativeAdapter()
    result = _request_native(source, symbol, timeframe, start, end)
    if inspect.isawaitable(result):
        result = await result
    return _filter_window(result, start, end)


def fetch_native_window(
    symbol: str,
    timeframe: str,
    start_at: datetime | str,
    end_at: datetime | str,
    *,
    adapter: BinanceNativeAdapter | None = None,
) -> pd.DataFrame:
    """Synchronous convenience wrapper for scripts and non-notebook callers."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            fetch_native_window_async(
                symbol, timeframe, start_at, end_at, adapter=adapter
            )
        )
    raise RuntimeError("an active event loop requires fetch_native_window_async")


def analyze_frame(frame: pd.DataFrame) -> TrendlineSnapshotV2:
    """Analyze one frame through the canonical fixed 3/300 V2 engine."""

    return analyze_trendlines_v2(frame_to_trendline_bars(frame))


def analyze_frames(
    frames: Mapping[str, pd.DataFrame],
) -> dict[str, TrendlineSnapshotV2]:
    if not isinstance(frames, Mapping):
        raise TypeError("frames must be a mapping of timeframe to DataFrame")
    return {timeframe: analyze_frame(frame) for timeframe, frame in frames.items()}


def _line_payload(line: TrendlineGeometry | None) -> dict[str, Any] | None:
    if line is None:
        return None
    return {
        "side": line.side,
        "start_anchor_at": _timestamp_text(line.start_anchor_at),
        "start_anchor_price": line.start_anchor_price,
        "end_anchor_at": _timestamp_text(line.end_anchor_at),
        "end_anchor_price": line.end_anchor_price,
        "slope_per_bar": line.slope_per_bar,
        "projected_price_at_market_as_of": line.projected_price_at_market_as_of,
        "post_anchor_body_crossed": line.post_anchor_body_crossed,
        "post_anchor_body_cross_count": line.post_anchor_body_cross_count,
        "projection_positive": line.projection_positive,
    }


def snapshot_payload(snapshot: TrendlineSnapshotV2) -> dict[str, Any]:
    """Project a V2 snapshot using public factual fields only."""

    if not isinstance(snapshot, TrendlineSnapshotV2):
        raise TypeError("snapshot must be TrendlineSnapshotV2")

    def side_payload(side: Any) -> dict[str, Any]:
        return {
            "structural": _line_payload(side.structural),
            "current_valid": _line_payload(side.current_valid),
            "secondary": _line_payload(side.secondary),
            "same_geometry": side.same_geometry,
        }

    return {
        "schema_version": snapshot.schema_version,
        "history_bar_count": snapshot.history_bar_count,
        "history_capacity_bars": snapshot.history_capacity_bars,
        "pivot_window": snapshot.pivot_window,
        "history_start_at": _timestamp_text(snapshot.history_start_at),
        "market_as_of": _timestamp_text(snapshot.market_as_of),
        "support": side_payload(snapshot.support),
        "resistance": side_payload(snapshot.resistance),
    }


snapshot_to_payload = snapshot_payload


def snapshot_json(snapshot: TrendlineSnapshotV2) -> str:
    return json.dumps(snapshot_payload(snapshot), indent=2, sort_keys=True)


def _bounded_bars(
    frame: pd.DataFrame, snapshot: TrendlineSnapshotV2
) -> tuple[TrendlineBar, ...]:
    bars = frame_to_trendline_bars(frame)[-HISTORY_CAPACITY_BARS:]
    if not bars or bars[-1].closed_at != snapshot.market_as_of:
        raise ValueError("frame and snapshot do not share the same cutoff")
    return bars


__all__ = [
    "analyze_frame",
    "analyze_frames",
    "fetch_native_window",
    "fetch_native_window_async",
    "frame_to_trendline_bars",
    "normalize_native_frame",
    "snapshot_json",
    "snapshot_payload",
    "snapshot_to_payload",
]
