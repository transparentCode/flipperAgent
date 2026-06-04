"""NaN-safe L2 orderbook feature helpers for regime classification."""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd

from libs.models.regime_classification.config import DEFAULT_L2_COLUMNS

_EPS = 1e-12


def empty_l2_feature_row() -> dict[str, float]:
    """Return the optional L2 feature set as NaN values."""
    return {name: math.nan for name in DEFAULT_L2_COLUMNS}


def compute_l2_snapshot_features(
    bids: Iterable[tuple[float, float]],
    asks: Iterable[tuple[float, float]],
) -> dict[str, float]:
    """Compute compact L2 descriptors from one orderbook snapshot."""
    bid_arr = np.array(list(bids), dtype=float)
    ask_arr = np.array(list(asks), dtype=float)
    if bid_arr.size == 0 or ask_arr.size == 0:
        return empty_l2_feature_row()

    bid_px, bid_qty = bid_arr[:, 0], bid_arr[:, 1]
    ask_px, ask_qty = ask_arr[:, 0], ask_arr[:, 1]
    bid_depth = float(np.nansum(bid_qty))
    ask_depth = float(np.nansum(ask_qty))
    best_bid = float(bid_px[0])
    best_ask = float(ask_px[0])
    mid = (best_bid + best_ask) / 2.0
    top = min(5, len(bid_qty), len(ask_qty))
    bid_top = float(np.nansum(bid_qty[:top]))
    ask_top = float(np.nansum(ask_qty[:top]))
    weighted_mid = ((best_bid * ask_top) + (best_ask * bid_top)) / max(bid_top + ask_top, _EPS)

    return {
        "l2_bid_ask_imbalance": (bid_depth - ask_depth) / max(bid_depth + ask_depth, _EPS),
        "l2_spread_bps": ((best_ask - best_bid) / max(mid, _EPS)) * 10_000.0,
        "l2_depth_ratio_5": bid_top / max(ask_top, _EPS),
        "l2_depth_decay_bid": _depth_decay(bid_qty),
        "l2_depth_decay_ask": _depth_decay(ask_qty),
        "l2_wall_bid": float(np.nanmax(bid_qty) / max(np.nanmean(bid_qty), _EPS)),
        "l2_wall_ask": float(np.nanmax(ask_qty) / max(np.nanmean(ask_qty), _EPS)),
        "l2_microprice_deviation_bps": ((weighted_mid - mid) / max(mid, _EPS)) * 10_000.0,
    }


def aggregate_l2_features(snapshot_df: pd.DataFrame, *, rule: str = "1h") -> pd.DataFrame:
    """Aggregate precomputed 5m L2 features into bar-level mean/std/trend columns."""
    if snapshot_df.empty:
        return pd.DataFrame()
    numeric = snapshot_df[[col for col in DEFAULT_L2_COLUMNS if col in snapshot_df.columns]].astype(float)
    grouped = numeric.resample(rule)
    mean = grouped.mean().add_suffix("_mean")
    std = grouped.std().add_suffix("_std")
    trend = grouped.apply(_last_minus_first).add_suffix("_trend")
    return pd.concat([mean, std, trend], axis=1)


def _depth_decay(qty: np.ndarray) -> float:
    valid = np.asarray(qty, dtype=float)
    valid = valid[np.isfinite(valid) & (valid > 0.0)]
    if len(valid) < 2:
        return math.nan
    levels = np.arange(1, len(valid) + 1, dtype=float)
    slope, _ = np.polyfit(levels, np.log(valid), deg=1)
    return float(-slope)


def _last_minus_first(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)
    return frame.iloc[-1] - frame.iloc[0]
