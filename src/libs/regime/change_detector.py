"""
Change Detector
===============
Wraps the NumPy BCPD kernel to produce ChangePointSignal output.

Multi-channel BCPD (log-returns + volatility) by default. Uses MAD standardisation
for robustness. Config has 10 essential fields — all other behaviour is fixed internally.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from app.regime.kernels.changepoint.core import bcpd_detect
from app.regime.market_structure import MarketStructure
from app.regime.models import ChangePointSignal

logger = logging.getLogger("app.regime")

_EPS = 1e-10


@dataclass(frozen=True)
class ChangeDetectorConfig:
    """Minimal config for ChangeDetector — 10 fields."""
    hazard_lambda: float = 150.0    # Expected bars between changepoints
    hazard_shape: float = 1.0       # Weibull shape (1.0=constant, >1.0=increasing hazard)
    alpha: float = 1.0              # Normal-Gamma prior shape
    beta: float = 1.0               # Normal-Gamma prior rate
    signal_threshold: float = 0.35  # cp_prob above which change_detected=True
    zscore_max_window: int = 2000   # Max window for bounded-expanding z-score
    min_periods: int = 20           # Minimum periods for z-score (else fill 0.0)
    truncation: int = 500           # Max run length tracked
    zscore_clip: float = 5.0        # Winsorization bound for z-scores (±clip)
    multichannel: bool = True       # Enable multi-channel BCPD

    @classmethod
    def load(
        cls,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        **overrides,
    ) -> "ChangeDetectorConfig":
        """
        Load from app/regime/config/regime.yaml with per-asset/TF overrides.

        Priority: overrides > assets.{asset}.{tf} > defaults
        """
        try:
            from app.utils.ConfigLoader import ConfigLoader
            raw = ConfigLoader.load("app/regime/config/regime.yaml")
        except Exception:
            raw = {}

        defaults = raw.get("defaults", {})
        asset_cfg: dict = {}
        if asset:
            asset_cfg = (
                raw.get("assets", {})
                .get(asset, {})
                .get(timeframe or "", {})
            )

        def _get(key: str, fallback):
            return overrides.get(key, asset_cfg.get(key, defaults.get(key, fallback)))

        return cls(
            hazard_lambda=float(_get("bcpd_hazard_lambda", 150.0)),
            hazard_shape=float(_get("bcpd_hazard_shape", 1.0)),
            alpha=float(_get("bcpd_alpha", 1.0)),
            beta=float(_get("bcpd_beta", 1.0)),
            signal_threshold=float(_get("bcpd_signal_threshold", 0.35)),
            zscore_max_window=int(_get("zscore_max_window", 2000)),
            zscore_clip=float(_get("bcpd_zscore_clip", 5.0)),
            min_periods=int(_get("min_periods", 20)),
            truncation=int(_get("truncation", 500)),
            multichannel=bool(_get("bcpd_multichannel", True)),
        )


class ChangeDetector:
    """
    Structural break detector using Bayesian Online Changepoint Detection.

    Single-channel: standardised log-returns only.
    Non-hindsight: BCPD forward message-passing (no future data).

    Usage
    -----
    detector = ChangeDetector.create("BTCUSDT", "1h")
    signal   = detector.detect(df)
    """

    def __init__(
        self,
        config: ChangeDetectorConfig,
        asset: Optional[str] = None,
        market_structure: Optional[MarketStructure] = None,
    ):
        self.config = config
        self.asset = asset
        self.market_structure = market_structure

    @classmethod
    def create(
        cls,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        market_structure: Optional[MarketStructure] = None,
        **overrides,
    ) -> "ChangeDetector":
        config = ChangeDetectorConfig.load(asset, timeframe, **overrides)
        return cls(config, asset, market_structure)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, df: pd.DataFrame) -> ChangePointSignal:
        """
        Run BCPD on df and return signal for the last bar.

        Parameters
        ----------
        df : DataFrame with 'close' column, at least 3 rows.
        """
        if "close" not in df.columns or len(df) < 3:
            ts = df.index[-1] if len(df) > 0 else pd.Timestamp.now()
            return self._empty_signal(ts)

        returns = self._log_returns(df["close"].values)
        if self.market_structure is not None:
            timestamps = df.index if isinstance(df.index, pd.DatetimeIndex) else None
            returns = self.market_structure.clean_returns(returns, timestamps)
        std_ret = self._standardize(returns)
        rl_posterior, cp_probs = bcpd_detect(
            std_ret,
            hazard_lambda=self.config.hazard_lambda,
            hazard_shape=self.config.hazard_shape,
            alpha=self.config.alpha,
            beta=self.config.beta,
            truncation=self.config.truncation,
        )

        cp_prob = float(cp_probs[-1])
        run_length = self._run_length(cp_probs)
        magnitude = float(np.abs(std_ret[-1])) if len(std_ret) > 0 else 0.0
        ts = df.index[-1] if isinstance(df.index, pd.DatetimeIndex) else pd.Timestamp.now()

        # Compute entropy of the last bar's run-length posterior
        last_rl = rl_posterior[-1] if len(rl_posterior) > 0 else np.array([1.0])
        with np.errstate(divide="ignore", invalid="ignore"):
            entropy = float(-np.where(last_rl > 0, last_rl * np.log(last_rl), 0.0).sum())

        return ChangePointSignal(
            timestamp=ts,
            change_point_prob=cp_prob,
            run_length=run_length,
            magnitude=magnitude,
            change_detected=cp_prob > self.config.signal_threshold,
            entropy=entropy,
            metadata={"asset": self.asset},
        )

    def detect_series(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Run BCPD on df and return the full series as additional columns.

        Adds columns: bcpd_prob, bcpd_run_length, bcpd_signal, bcpd_magnitude.
        """
        if "close" not in df.columns or len(df) < 3:
            return self._empty_series(df)

        returns = self._log_returns(df["close"].values)
        if self.market_structure is not None:
            timestamps = df.index if isinstance(df.index, pd.DatetimeIndex) else None
            returns = self.market_structure.clean_returns(returns, timestamps)
        std_ret = self._standardize(returns)
        _, cp_probs = bcpd_detect(
            std_ret,
            hazard_lambda=self.config.hazard_lambda,
            hazard_shape=self.config.hazard_shape,
            alpha=self.config.alpha,
            beta=self.config.beta,
            truncation=self.config.truncation,
            return_posterior=False,
        )

        # Pad to df length (first bar has no return)
        pad = np.zeros(len(df) - len(cp_probs))
        cp_padded = np.concatenate([pad, cp_probs])

        result = pd.DataFrame(index=df.index)
        result["bcpd_prob"] = cp_padded
        result["bcpd_signal"] = (cp_padded > self.config.signal_threshold).astype(int)
        result["bcpd_magnitude"] = np.concatenate(
            [pad, np.abs(std_ret)]
        )
        # Rolling run length: bars since last signal
        result["bcpd_run_length"] = self._run_length_series(result["bcpd_signal"].values)

        # Store gap mask for downstream use (stocks only)
        if self.market_structure is not None:
            timestamps = df.index if isinstance(df.index, pd.DatetimeIndex) else None
            if timestamps is not None:
                gap_mask = self.market_structure.get_gap_mask(timestamps)
                # Pad: first bar has no return, so no gap flag
                result["is_gap_bar"] = np.concatenate([[False], gap_mask])
            else:
                result["is_gap_bar"] = False
        return result

    def detect_series_multichannel(self, df: pd.DataFrame) -> pd.DataFrame:
        """Run independent BCPDs on returns, volume-change, and range channels.

        Channels:
        1. Standardized log-returns (existing)
        2. Standardized log-volume-change: diff(log(volume+1))
        3. Standardized log-range: log(high/low)

        Fusion: cp_prob = max(cp_prob_returns, cp_prob_volume, cp_prob_range)

        Falls back to single-channel if volume/high/low columns are missing.
        """
        if "close" not in df.columns or len(df) < 3:
            return self._empty_series_multichannel(df)

        n = len(df)
        bcpd_kwargs = dict(
            hazard_lambda=self.config.hazard_lambda,
            hazard_shape=self.config.hazard_shape,
            alpha=self.config.alpha,
            beta=self.config.beta,
            truncation=self.config.truncation,
            return_posterior=False,
        )

        # --- Channel 1: log-returns (always available) ---
        returns = self._log_returns(df["close"].values)
        if self.market_structure is not None:
            timestamps = df.index if isinstance(df.index, pd.DatetimeIndex) else None
            returns = self.market_structure.clean_returns(returns, timestamps)
        std_ret = self._standardize(returns)
        _, cp_returns = bcpd_detect(std_ret, **bcpd_kwargs)
        pad_ret = np.zeros(n - len(cp_returns))
        cp_returns_padded = np.concatenate([pad_ret, cp_returns])

        # --- Channel 2: log-volume-change (if volume column exists) ---
        has_volume = "volume" in df.columns
        if has_volume:
            vol_raw = df["volume"].values.astype(np.float64)
            log_vol = np.log(vol_raw + 1.0)
            vol_diff = np.diff(log_vol)
            std_vol = self._standardize(vol_diff)
            _, cp_volume = bcpd_detect(std_vol, **bcpd_kwargs)
            pad_vol = np.zeros(n - len(cp_volume))
            cp_volume_padded = np.concatenate([pad_vol, cp_volume])
        else:
            cp_volume_padded = np.zeros(n)
            logger.debug("Multi-channel BCPD: 'volume' column missing, skipping volume channel")

        # --- Channel 3: log-range (if high and low columns exist) ---
        has_range = "high" in df.columns and "low" in df.columns
        if has_range:
            high = df["high"].values.astype(np.float64)
            low = df["low"].values.astype(np.float64)
            log_range = np.log((high / (low + _EPS)) + _EPS)
            # log_range is same length as df (no diff), so we take diff for stationarity
            range_diff = np.diff(log_range)
            std_range = self._standardize(range_diff)
            _, cp_range = bcpd_detect(std_range, **bcpd_kwargs)
            pad_range = np.zeros(n - len(cp_range))
            cp_range_padded = np.concatenate([pad_range, cp_range])
        else:
            cp_range_padded = np.zeros(n)
            logger.debug("Multi-channel BCPD: 'high'/'low' columns missing, skipping range channel")

        # --- Fusion: max across channels ---
        cp_fused = np.maximum(np.maximum(cp_returns_padded, cp_volume_padded), cp_range_padded)

        result = pd.DataFrame(index=df.index)
        result["bcpd_prob_returns"] = cp_returns_padded
        result["bcpd_prob_volume"] = cp_volume_padded
        result["bcpd_prob_range"] = cp_range_padded
        result["bcpd_prob"] = cp_fused
        result["bcpd_signal"] = (cp_fused > self.config.signal_threshold).astype(int)
        result["bcpd_magnitude"] = np.concatenate(
            [pad_ret, np.abs(std_ret)]
        )
        result["bcpd_run_length"] = self._run_length_series(result["bcpd_signal"].values)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _log_returns(prices: np.ndarray) -> np.ndarray:
        return np.diff(np.log(prices + _EPS))

    def _standardize(self, returns: np.ndarray) -> np.ndarray:
        """
        Bounded-expanding z-score standardisation, winsorised at ±5σ.

        Uses a rolling window capped at zscore_max_window (default 2000 bars)
        rather than pure expanding. This prevents sensitivity decay: with
        unbounded expanding, the std grows monotonically stable and genuine
        regime shifts at bar 5000+ produce muted z-scores compared to the
        same shift at bar 500. The bounded window keeps the baseline
        sensitive to recent regime structure while still being much longer
        than the expected changepoint interval (hazard_lambda ~ 50-200).
        """
        s = pd.Series(returns)
        w = self.config.zscore_max_window
        rolling_mean = s.rolling(w, min_periods=self.config.min_periods).mean()
        rolling_std = (
            s.rolling(w, min_periods=self.config.min_periods)
            .std()
            .replace(0, np.nan)
            .ffill()
            .fillna(1.0)
        )
        c = self.config.zscore_clip
        std = ((s - rolling_mean) / rolling_std).clip(-c, c).fillna(0.0)
        return std.values

    @staticmethod
    def _run_length(cp_probs: np.ndarray) -> int:
        """Bars since last detected changepoint (where prob was highest)."""
        if len(cp_probs) == 0:
            return 0
        last_peak = int(np.argmax(cp_probs))
        return len(cp_probs) - 1 - last_peak

    @staticmethod
    def _run_length_series(signal: np.ndarray) -> np.ndarray:
        """Rolling counter of bars since last signal=1."""
        rl = np.zeros(len(signal), dtype=int)
        count = 0
        for i, s in enumerate(signal):
            count = 0 if s else count + 1
            rl[i] = count
        return rl

    def _empty_signal(self, timestamp: pd.Timestamp) -> ChangePointSignal:
        return ChangePointSignal(
            timestamp=timestamp,
            change_point_prob=0.0,
            run_length=0,
            magnitude=0.0,
            metadata={"asset": self.asset, "empty": True},
        )

    def _empty_series(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        for col in ("bcpd_prob", "bcpd_magnitude"):
            result[col] = 0.0
        for col in ("bcpd_signal", "bcpd_run_length"):
            result[col] = 0
        return result

    def _empty_series_multichannel(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        for col in ("bcpd_prob_returns", "bcpd_prob_volume", "bcpd_prob_range",
                     "bcpd_prob", "bcpd_magnitude"):
            result[col] = 0.0
        for col in ("bcpd_signal", "bcpd_run_length"):
            result[col] = 0
        return result
