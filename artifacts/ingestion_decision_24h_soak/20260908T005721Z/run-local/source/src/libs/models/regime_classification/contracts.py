"""
Emission contracts for RegimeClassificationModel.

All fields are continuous — no discrete labels.
Consumed by downstream models via ModelOutput.metadata.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class HMMStateLocal:
    """Per-bar HMM posterior output (local to regime_classification)."""

    posteriors: Tuple[float, ...]  # (p_state_0, p_state_1, ..., p_state_N)
    n_states: int
    transition_prob: float  # P(stay in current state)
    crisis_prob: float  # P(crisis state), 0 if no crisis state


@dataclass(frozen=True)
class VolStateLocal:
    """Per-bar volatility output (local to regime_classification)."""

    vol_percentile: float  # 0–100, rolling percentile rank
    rolling_vol: float  # raw rolling std of log-returns


@dataclass
class RegimeFeatureOutput:
    """
    Per-bar output of RegimeClassificationModel.

    All fields are continuous — no discrete labels.
    Consumed by downstream models via ModelOutput.metadata.
    """

    # HMM posteriors (N-state, not collapsed)
    hmm_posteriors: Tuple[float, ...] = ()
    hmm_n_states: int = 2
    hmm_transition_prob: float = 0.5
    hmm_crisis_prob: float = 0.0

    # Volatility
    vol_percentile: float = 50.0  # 0–100, rolling percentile rank
    realized_vol: float = 0.0  # rolling std of log-returns
    fwd_vol_ewma: float = 0.0  # EWMA forward vol estimate

    # Trend / persistence
    trend_strength: float = 0.0  # 0–1, directional efficiency ratio
    hurst: float = 0.5  # 0–1, R/S Hurst exponent

    # Changepoint
    changepoint_prob: float = 0.0  # 0–1, P(changepoint at t)
    run_length: int = 0  # bars since last changepoint
    cp_entropy: float = 0.0  # run-length distribution entropy

    # Cycle
    hilbert_period: float = 40.0  # dominant cycle period (bars)
    hilbert_confidence: float = 0.0  # 0–1, period stability

    # L2 orderbook (NaN if not available)
    bid_ask_imbalance: float = math.nan  # -1 to +1
    depth_ratio: float = math.nan  # top-N bid/ask qty ratio
    spread_bps: float = math.nan  # bid-ask spread in basis points
    depth_decay_bid: float = math.nan  # exponential decay rate
    depth_decay_ask: float = math.nan  # exponential decay rate

    # Composite
    condition_scale: float = 0.0  # blended regime score

    def to_dict(self) -> Dict[str, Any]:
        """Flatten to dict for ModelOutput.metadata packing.

        Returns Dict[str, Any] because L2 fields may be None when absent.
        """
        d: Dict[str, float] = {}

        # Flatten HMM posteriors into separate keys
        for i, p in enumerate(self.hmm_posteriors):
            d[f"hmm_p_state_{i}"] = p
        d["hmm_n_states"] = float(self.hmm_n_states)
        d["hmm_transition_prob"] = self.hmm_transition_prob
        d["hmm_crisis_prob"] = self.hmm_crisis_prob

        # Volatility
        d["vol_percentile"] = self.vol_percentile
        d["realized_vol"] = self.realized_vol
        d["fwd_vol_ewma"] = self.fwd_vol_ewma

        # Trend / persistence
        d["trend_strength"] = self.trend_strength
        d["hurst"] = self.hurst

        # Changepoint
        d["changepoint_prob"] = self.changepoint_prob
        d["run_length"] = float(self.run_length)
        d["cp_entropy"] = self.cp_entropy

        # Cycle
        d["hilbert_period"] = self.hilbert_period
        d["hilbert_confidence"] = self.hilbert_confidence

        # L2 orderbook (None instead of NaN for JSON/Valkey safety)
        d["bid_ask_imbalance"] = None if math.isnan(self.bid_ask_imbalance) else self.bid_ask_imbalance
        d["depth_ratio"] = None if math.isnan(self.depth_ratio) else self.depth_ratio
        d["spread_bps"] = None if math.isnan(self.spread_bps) else self.spread_bps
        d["depth_decay_bid"] = None if math.isnan(self.depth_decay_bid) else self.depth_decay_bid
        d["depth_decay_ask"] = None if math.isnan(self.depth_decay_ask) else self.depth_decay_ask

        # Composite
        d["condition_scale"] = self.condition_scale

        return d
