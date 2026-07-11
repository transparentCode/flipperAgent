"""Staleness helpers for optional external context alignment."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from libs.common.timeframes import timeframe_to_seconds


def canonicalize_source_name(raw: str) -> str:
    """Normalize a context source key to a stable short name."""
    name = str(raw).strip()
    if ":" in name:
        _, name = name.split(":", 1)
    return name.upper()


def normalize_source_frames(
    external_context_frames: Mapping[str, pd.DataFrame] | None,
) -> dict[str, pd.DataFrame]:
    """Canonicalize source names while keeping the last frame on collisions."""
    if not external_context_frames:
        return {}
    return {
        canonicalize_source_name(name): frame
        for name, frame in external_context_frames.items()
        if isinstance(frame, pd.DataFrame)
    }


def prepare_external_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare one external frame with a UTC, monotonic timestamp column."""
    if df.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    frame = df.copy()
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    columns = [column for column in ("open", "high", "low", "close", "volume") if column in frame.columns]
    out = frame.loc[:, columns].copy()
    out.insert(0, "timestamp", out.index)
    return out.reset_index(drop=True)


def align_external_series(
    asset_index: pd.Index,
    source_frame: pd.DataFrame,
    *,
    timeframe: str,
    max_staleness_bars: int,
) -> pd.DataFrame:
    """As-of align an external frame to the asset index and score staleness."""
    target = pd.DataFrame({"timestamp": pd.to_datetime(asset_index, utc=True)})
    source = prepare_external_frame(source_frame)
    if source.empty or "close" not in source.columns:
        return pd.DataFrame(
            {
                "source_timestamp": pd.NaT,
                "close": np.nan,
                "high": np.nan,
                "low": np.nan,
                "staleness_bars": np.nan,
                "available": False,
            },
            index=asset_index,
        )

    renamed = source.rename(
        columns={
            "timestamp": "source_timestamp",
            "close": "close",
            "high": "high",
            "low": "low",
        }
    )
    merged = pd.merge_asof(
        target.sort_values("timestamp"),
        renamed.sort_values("source_timestamp"),
        left_on="timestamp",
        right_on="source_timestamp",
        direction="backward",
    ).set_index(pd.Index(asset_index))

    staleness = compute_staleness_bars(
        merged["timestamp"],
        merged["source_timestamp"],
        timeframe=timeframe,
    )
    available = merged["source_timestamp"].notna() & (staleness <= int(max_staleness_bars))
    return pd.DataFrame(
        {
            "source_timestamp": merged["source_timestamp"],
            "close": pd.to_numeric(merged.get("close"), errors="coerce"),
            "high": pd.to_numeric(merged.get("high"), errors="coerce"),
            "low": pd.to_numeric(merged.get("low"), errors="coerce"),
            "staleness_bars": staleness,
            "available": available.astype(bool),
        },
        index=asset_index,
    )


def compute_staleness_bars(
    target_timestamps: pd.Series | pd.Index,
    source_timestamps: pd.Series,
    *,
    timeframe: str,
) -> pd.Series:
    """Convert timestamp lag into asset-bar staleness."""
    target = pd.Series(pd.to_datetime(target_timestamps, utc=True))
    source = pd.Series(pd.to_datetime(source_timestamps, utc=True))
    bar_seconds = max(timeframe_to_seconds(timeframe), 1)
    lag_seconds = (target - source).dt.total_seconds()
    out = (lag_seconds / float(bar_seconds)).clip(lower=0.0)
    out = np.floor(out).astype(float)
    out.loc[source.isna()] = np.nan
    out.index = source.index
    return out


def neutral_context_frame(index: pd.Index) -> pd.DataFrame:
    """Standard neutral external-context frame used when context is absent."""
    return pd.DataFrame(
        {
            "external_context_available": False,
            "external_context_coverage_ratio": 0.0,
            "external_context_staleness_bars": np.nan,
            "btc_d_available": False,
            "total2_available": False,
            "total3_available": False,
            "btc_available": False,
            "eth_available": False,
        },
        index=index,
    )


__all__ = [
    "align_external_series",
    "canonicalize_source_name",
    "compute_staleness_bars",
    "neutral_context_frame",
    "normalize_source_frames",
    "prepare_external_frame",
]
