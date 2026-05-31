"""
Market Structure Handler
========================
Lightweight preprocessing for cross-asset robustness.

Handles market-specific quirks:
- **Stocks**: Overnight gaps produce outsized log-returns that trigger false
  BCPD changepoints.  Gap returns are attenuated (not zeroed) to preserve
  some directional information while preventing false positives.
- **FX**: 24/5 continuous — no special handling needed.
- **Crypto**: 24/7 continuous — pass-through, no changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("app.regime")


@dataclass(frozen=True)
class MarketStructureConfig:
    """Config for market structure preprocessing."""
    asset_type: str = "crypto"          # crypto | stock | fx
    gap_attenuation: float = 0.3        # Multiply gap returns by this factor
    gap_threshold_mult: float = 2.0     # Gap if bar delta > mult × median delta


ASSET_TYPES = {"crypto", "stock", "fx"}

# Common crypto quote currencies / bases
_CRYPTO_SUFFIXES = ("USDT", "BUSD", "USDC", "TUSD", "BTC", "ETH", "BNB", "PERP")


def infer_asset_type(asset: str) -> str:
    """
    Infer asset type from symbol name.

    Heuristics (applied in order):
    1. Ends with a known crypto suffix (USDT, BUSD, BTC, ETH, ...) -> crypto
    2. Contains '/' (EUR/USD, GBP/JPY) -> fx
    3. Otherwise -> stock
    """
    if not asset:
        return "crypto"

    upper = asset.upper().replace("-", "")
    for suffix in _CRYPTO_SUFFIXES:
        if upper.endswith(suffix):
            return "crypto"

    if "/" in asset:
        return "fx"

    return "stock"


class MarketStructure:
    """
    Handles market-specific data preprocessing.

    Used by ChangeDetector and VolOverlay to clean returns before
    standardization / vol estimation, preventing false signals from
    overnight gaps (stocks) or session boundaries.
    """

    def __init__(self, config: Optional[MarketStructureConfig] = None):
        self.config = config or MarketStructureConfig()
        if self.config.asset_type not in ASSET_TYPES:
            raise ValueError(
                f"Unknown asset_type '{self.config.asset_type}', "
                f"expected one of {ASSET_TYPES}"
            )

    @classmethod
    def for_asset(cls, asset: str, **overrides) -> "MarketStructure":
        """Factory: infer type from symbol and build."""
        asset_type = overrides.pop("asset_type", None) or infer_asset_type(asset)
        return cls(MarketStructureConfig(asset_type=asset_type, **overrides))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def clean_returns(
        self,
        returns: np.ndarray,
        timestamps: Optional[pd.DatetimeIndex] = None,
    ) -> np.ndarray:
        """
        Clean returns based on asset type.

        For stocks:
            Detect overnight gaps (time delta > gap_threshold_mult × median
            bar duration) and attenuate gap returns by gap_attenuation factor.
        For FX / crypto:
            Pass through unchanged.

        Parameters
        ----------
        returns    : Array of log-returns (length N-1 for N prices).
        timestamps : DatetimeIndex of the *price* bars (length N).
                     Only needed for stock gap detection.  If None and
                     asset_type is stock, returns are passed through unchanged.

        Returns
        -------
        Cleaned returns array (same shape as input).
        """
        if self.config.asset_type != "stock":
            return returns

        if timestamps is None or len(timestamps) < 2:
            return returns

        gap_mask = self.get_gap_mask(timestamps)
        if not gap_mask.any():
            return returns

        cleaned = returns.copy()
        cleaned[gap_mask] *= self.config.gap_attenuation

        n_gaps = int(gap_mask.sum())
        logger.debug(
            "MarketStructure: attenuated %d gap returns (factor=%.2f)",
            n_gaps,
            self.config.gap_attenuation,
        )
        return cleaned

    def get_gap_mask(self, timestamps: pd.DatetimeIndex) -> np.ndarray:
        """
        Return boolean mask where True = gap bar.

        A gap is detected when the time delta between consecutive bars
        exceeds ``gap_threshold_mult`` times the median bar duration.

        The mask has length ``len(timestamps) - 1`` (aligned with returns).
        """
        if len(timestamps) < 2:
            return np.zeros(0, dtype=bool)

        deltas = np.diff(timestamps.asi8)  # nanosecond diffs
        median_delta = np.median(deltas)

        if median_delta <= 0:
            return np.zeros(len(deltas), dtype=bool)

        threshold = self.config.gap_threshold_mult * median_delta
        return deltas > threshold
