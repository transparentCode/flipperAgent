"""
L2 Orderbook Feature Aggregation.

Computes microstructure features from L2 depth snapshots.
All features return NaN when input is unavailable — downstream
consumers must be NaN-safe.

Designed for 5m REST snapshots (20 levels), not streaming.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class L2Features:
    """Aggregated L2 features for a single snapshot."""

    bid_ask_imbalance: float = math.nan  # -1 to +1
    depth_ratio: float = math.nan  # top-N bid/ask quantity ratio
    spread_bps: float = math.nan  # spread in basis points
    depth_decay_bid: float = math.nan  # exponential decay rate
    depth_decay_ask: float = math.nan  # exponential decay rate

    def to_dict(self) -> dict[str, float]:
        return {
            "bid_ask_imbalance": self.bid_ask_imbalance,
            "depth_ratio": self.depth_ratio,
            "spread_bps": self.spread_bps,
            "depth_decay_bid": self.depth_decay_bid,
            "depth_decay_ask": self.depth_decay_ask,
        }


def compute_l2_features(
    bids: Optional[np.ndarray],
    asks: Optional[np.ndarray],
    top_n: int = 5,
) -> L2Features:
    """
    Compute L2 features from bid/ask arrays.

    Parameters
    ----------
    bids : (N, 2) array of [price, quantity], sorted descending by price
    asks : (N, 2) array of [price, quantity], sorted ascending by price
    top_n : number of top levels for imbalance/ratio computation

    Returns
    -------
    L2Features with NaN for any field that can't be computed
    """
    if bids is None or asks is None:
        return L2Features()

    bids = np.asarray(bids, dtype=float)
    asks = np.asarray(asks, dtype=float)

    if bids.ndim != 2 or asks.ndim != 2 or len(bids) == 0 or len(asks) == 0:
        return L2Features()

    best_bid = bids[0, 0]
    best_ask = asks[0, 0]
    if best_bid <= 0 or best_ask <= 0 or best_ask <= best_bid:
        return L2Features()

    mid = (best_bid + best_ask) / 2.0

    # Spread in basis points
    spread_bps = (best_ask - best_bid) / mid * 10_000

    # Top-N bid/ask imbalance: (bid_qty - ask_qty) / (bid_qty + ask_qty)
    bid_qty = bids[:top_n, 1].sum()
    ask_qty = asks[:top_n, 1].sum()
    total_qty = bid_qty + ask_qty
    if total_qty > 1e-10:
        imbalance = (bid_qty - ask_qty) / total_qty
    else:
        imbalance = 0.0

    # Depth ratio: total bid qty / total ask qty
    total_bid = bids[:, 1].sum()
    total_ask = asks[:, 1].sum()
    if total_ask > 1e-10:
        depth_ratio = total_bid / total_ask
    else:
        depth_ratio = math.nan

    # Depth decay: fit exponential decay to quantity vs distance from mid
    decay_bid = _fit_depth_decay(bids, mid, side="bid")
    decay_ask = _fit_depth_decay(asks, mid, side="ask")

    return L2Features(
        bid_ask_imbalance=imbalance,
        depth_ratio=depth_ratio,
        spread_bps=spread_bps,
        depth_decay_bid=decay_bid,
        depth_decay_ask=decay_ask,
    )


def _fit_depth_decay(
    levels: np.ndarray, mid: float, side: str
) -> float:
    """
    Fit exponential decay rate to order book depth.

    Models quantity ~ exp(-decay * distance_from_mid).
    Returns decay coefficient. Higher = thinner book.
    """
    if len(levels) < 3:
        return math.nan

    prices = levels[:, 0]
    quantities = levels[:, 1]

    distances = np.abs(prices - mid) / mid * 10_000  # in bps
    log_qty = np.log(quantities + 1e-10)

    # Simple OLS: log(qty) = a - decay * distance
    if distances.std() < 1e-10:
        return math.nan

    n = len(distances)
    mean_d = distances.mean()
    mean_q = log_qty.mean()
    cov = ((distances - mean_d) * (log_qty - mean_q)).sum()
    var = ((distances - mean_d) ** 2).sum()

    if var < 1e-10:
        return math.nan

    slope = cov / var
    return float(-slope)  # negate so positive = decay
