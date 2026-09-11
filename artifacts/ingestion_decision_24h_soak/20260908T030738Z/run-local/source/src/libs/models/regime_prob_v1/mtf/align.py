"""As-of alignment utilities for higher-timeframe probability frames."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from libs.common.timeframes import timeframe_to_seconds


@dataclass(frozen=True)
class MTFAlignConfig:
    """Controls HTF alignment tolerance relative to the LTF."""

    availability_grace_factor: float = 1.0


def align_mtf_probability_frames(
    base_index: pd.Index,
    mtf_frames: Mapping[str, pd.DataFrame] | None,
    *,
    base_timeframe: str,
    config: MTFAlignConfig | None = None,
) -> pd.DataFrame:
    """As-of align completed HTF probability frames to a lower-timeframe index."""
    cfg = config or MTFAlignConfig()
    if mtf_frames is None:
        return pd.DataFrame(index=base_index)

    out = pd.DataFrame(index=base_index)
    for timeframe, frame in mtf_frames.items():
        if not isinstance(frame, pd.DataFrame):
            continue
        aligned = align_single_mtf_probability_frame(
            base_index,
            frame,
            base_timeframe=base_timeframe,
            higher_timeframe=timeframe,
            config=cfg,
        )
        for column in aligned.columns:
            out[column] = aligned[column]
    return out


def align_single_mtf_probability_frame(
    base_index: pd.Index,
    htf_frame: pd.DataFrame,
    *,
    base_timeframe: str,
    higher_timeframe: str,
    config: MTFAlignConfig | None = None,
) -> pd.DataFrame:
    """Backward-only align one HTF frame to LTF timestamps."""
    cfg = config or MTFAlignConfig()
    prefix = _tf_prefix(higher_timeframe)
    if htf_frame.empty:
        return pd.DataFrame(
            {
                f"{prefix}_available": False,
                f"{prefix}_staleness_bars": np.nan,
            },
            index=base_index,
        )

    target = pd.DataFrame({"timestamp": pd.to_datetime(base_index, utc=True)})
    source = htf_frame.copy()
    source.index = pd.to_datetime(source.index, utc=True)
    source = source[~source.index.duplicated(keep="last")].sort_index()
    source = source.reset_index(names="source_timestamp")

    merged = pd.merge_asof(
        target.sort_values("timestamp"),
        source,
        left_on="timestamp",
        right_on="source_timestamp",
        direction="backward",
    ).set_index(pd.Index(base_index))

    staleness_bars = _staleness_in_base_bars(
        merged["timestamp"],
        merged["source_timestamp"],
        base_timeframe=base_timeframe,
    )
    allowed_bars = _allowed_staleness_bars(
        base_timeframe=base_timeframe,
        higher_timeframe=higher_timeframe,
        grace_factor=cfg.availability_grace_factor,
    )
    available = merged["source_timestamp"].notna() & (staleness_bars <= allowed_bars)

    out = pd.DataFrame(index=base_index)
    out[f"{prefix}_available"] = available.astype(bool)
    out[f"{prefix}_staleness_bars"] = staleness_bars
    out[f"{prefix}_source_timestamp"] = merged["source_timestamp"]
    for column in merged.columns:
        if column in {"timestamp", "source_timestamp"}:
            continue
        out[f"{prefix}_{column}"] = merged[column]
    return out


def _allowed_staleness_bars(*, base_timeframe: str, higher_timeframe: str, grace_factor: float) -> int:
    base_seconds = max(timeframe_to_seconds(base_timeframe), 1)
    higher_seconds = max(timeframe_to_seconds(higher_timeframe), base_seconds)
    ratio = higher_seconds / base_seconds
    return max(int(math.ceil(ratio * max(float(grace_factor), 0.0))), 1)


def _staleness_in_base_bars(
    target_timestamps: pd.Series,
    source_timestamps: pd.Series,
    *,
    base_timeframe: str,
) -> pd.Series:
    base_seconds = max(timeframe_to_seconds(base_timeframe), 1)
    lag_seconds = (pd.to_datetime(target_timestamps, utc=True) - pd.to_datetime(source_timestamps, utc=True)).dt.total_seconds()
    out = np.floor((lag_seconds / float(base_seconds)).clip(lower=0.0)).astype(float)
    out.loc[source_timestamps.isna()] = np.nan
    out.index = source_timestamps.index
    return out


def _tf_prefix(timeframe: str) -> str:
    return f"mtf_{str(timeframe).lower().replace('.', '_')}"


__all__ = [
    "MTFAlignConfig",
    "align_mtf_probability_frames",
    "align_single_mtf_probability_frame",
]
