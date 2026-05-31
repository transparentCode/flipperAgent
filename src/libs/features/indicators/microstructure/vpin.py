"""VPIN — Volume-synchronised Probability of Informed Trading indicator."""

from __future__ import annotations

from collections import deque
from typing import Any, Sequence

import numpy as np
import pandas as pd

from libs.features.indicators.base import Indicator
from libs.features.indicators.registry import IndicatorRegistry


@IndicatorRegistry.register("VPIN")
class VPIN(Indicator):
    """Converts time bars to volume bars, computes VPIN, maps back without look-ahead.

    Parameters
    ----------
    bucket_multiplier : float
        bucket_size = median(volume) * bucket_multiplier.
    n_buckets : int
        Number of rolling volume-bar buckets for VPIN calculation.
    zscore_window : int
        Rolling window for z-score normalisation of VPIN.
    """

    def __init__(
        self,
        bucket_multiplier: float = 1.0,
        n_buckets: int = 50,
        zscore_window: int = 200,
    ) -> None:
        super().__init__()
        self.bucket_multiplier = bucket_multiplier
        self.n_buckets = n_buckets
        self.zscore_window = zscore_window

        # Live streaming state
        self._bucket_size: float | None = None
        self._partial_buy: float = 0.0
        self._partial_sell: float = 0.0
        self._partial_vol: float = 0.0
        self._bucket_buf: deque[tuple[float, float, float]] = deque(maxlen=n_buckets)
        self._vpin_buf: deque[float] = deque(maxlen=zscore_window)

    @property
    def lookback_required(self) -> int:
        return self.zscore_window + self.n_buckets

    # ------------------------------------------------------------------
    # Batch (vectorised)
    # ------------------------------------------------------------------

    def batch(self, data: pd.DataFrame) -> dict[str, Any]:
        """Compute VPIN over a DataFrame.

        Expected columns: close, volume, taker_buy_base.
        The DataFrame index must be a timestamp-like for merge_asof.
        """
        volume = data["volume"].values.astype(np.float64)
        taker_buy_base = data["taker_buy_base"].values.astype(np.float64)

        bucket_size = float(np.median(volume)) * self.bucket_multiplier
        if bucket_size < 1e-12:
            bucket_size = 1.0

        taker_sell_base = volume - taker_buy_base
        net_taker_buy_ratio = taker_buy_base / np.maximum(volume, 1e-12)

        # --- Build volume bars ---
        buckets_buy: list[float] = []
        buckets_sell: list[float] = []
        buckets_vol: list[float] = []
        buckets_time_idx: list[int] = []  # integer index of the *last* time bar in this bucket

        partial_buy = 0.0
        partial_sell = 0.0
        partial_vol = 0.0

        for i in range(len(volume)):
            remaining_buy = taker_buy_base[i]
            remaining_sell = taker_sell_base[i]
            remaining_vol = volume[i]

            while remaining_vol > 0:
                space = bucket_size - partial_vol
                fill = min(remaining_vol, space)
                fraction = fill / max(remaining_vol, 1e-12)

                partial_buy += remaining_buy * fraction
                partial_sell += remaining_sell * fraction
                partial_vol += fill

                remaining_buy -= remaining_buy * fraction
                remaining_sell -= remaining_sell * fraction
                remaining_vol -= fill

                if partial_vol >= bucket_size - 1e-12:
                    buckets_buy.append(partial_buy)
                    buckets_sell.append(partial_sell)
                    buckets_vol.append(partial_vol)
                    buckets_time_idx.append(i)
                    partial_buy = 0.0
                    partial_sell = 0.0
                    partial_vol = 0.0

        if not buckets_buy:
            n = len(data)
            return {
                "vpin": np.full(n, np.nan),
                "vpin_z": np.full(n, np.nan),
                "net_taker_buy_ratio": net_taker_buy_ratio,
            }

        b_buy = np.array(buckets_buy)
        b_sell = np.array(buckets_sell)
        b_vol = np.array(buckets_vol)
        b_idx = np.array(buckets_time_idx)

        # --- Rolling VPIN over n_buckets ---
        n_b = len(b_buy)
        vpin_arr = np.full(n_b, np.nan)
        for j in range(self.n_buckets - 1, n_b):
            start = j - self.n_buckets + 1
            window_imb = np.abs(b_buy[start : j + 1] - b_sell[start : j + 1])
            window_vol = b_vol[start : j + 1]
            total_vol = window_vol.sum()
            if total_vol > 0:
                vpin_arr[j] = window_imb.sum() / total_vol

        # --- Map back to time bars via backward fill (no look-ahead) ---
        # Build a bucket-level DataFrame with integer index from original data
        bucket_df = pd.DataFrame({"vpin_bucket": vpin_arr, "time_idx": b_idx})
        bucket_df = bucket_df.dropna(subset=["vpin_bucket"])

        vpin_time = np.full(len(data), np.nan)
        if not bucket_df.empty:
            # For each time bar, find the latest bucket that ended at or before it
            time_idx_series = pd.Series(range(len(data)), name="time_idx")
            merged = pd.merge_asof(
                time_idx_series.to_frame(),
                bucket_df.rename(columns={"time_idx": "bucket_end_idx"}),
                left_on="time_idx",
                right_on="bucket_end_idx",
                direction="backward",
            )
            vpin_time = merged["vpin_bucket"].values

        # --- Z-score ---
        vpin_series = pd.Series(vpin_time)
        roll_mean = vpin_series.rolling(self.zscore_window, min_periods=1).mean().values
        roll_std = vpin_series.rolling(self.zscore_window, min_periods=1).std(ddof=0).values
        roll_std = np.where(roll_std < 1e-12, 1e-12, roll_std)
        vpin_z = (vpin_time - roll_mean) / roll_std

        return {
            "vpin": vpin_time,
            "vpin_z": vpin_z,
            "net_taker_buy_ratio": net_taker_buy_ratio,
        }

    # ------------------------------------------------------------------
    # Prime
    # ------------------------------------------------------------------

    def prime(self, historical_data: Sequence[dict[str, float]]) -> None:
        self._bucket_buf.clear()
        self._vpin_buf.clear()
        self._partial_buy = 0.0
        self._partial_sell = 0.0
        self._partial_vol = 0.0

        # Estimate bucket size from historical volume
        volumes = np.array([float(t["volume"]) for t in historical_data])
        self._bucket_size = float(np.median(volumes)) * self.bucket_multiplier
        if self._bucket_size < 1e-12:
            self._bucket_size = 1.0

        for tick in historical_data:
            self._push_tick(tick)

        self._is_primed = True

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, new_value: dict[str, float]) -> dict[str, Any]:
        if not self.is_primed:
            raise RuntimeError("Indicator must be primed before update() can be called.")
        return self._push_tick(new_value)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _push_tick(self, tick: dict[str, float]) -> dict[str, Any]:
        volume = float(tick["volume"])
        taker_buy_base = float(tick["taker_buy_base"])
        taker_sell_base = volume - taker_buy_base

        remaining_buy = taker_buy_base
        remaining_sell = taker_sell_base
        remaining_vol = volume

        while remaining_vol > 1e-12:
            if self._bucket_size is None:
                self._bucket_size = max(volume, 1e-12)
            space = self._bucket_size - self._partial_vol
            fill = min(remaining_vol, space)
            fraction = fill / max(remaining_vol, 1e-12)

            self._partial_buy += remaining_buy * fraction
            self._partial_sell += remaining_sell * fraction
            self._partial_vol += fill

            remaining_buy -= remaining_buy * fraction
            remaining_sell -= remaining_sell * fraction
            remaining_vol -= fill

            if self._partial_vol >= self._bucket_size - 1e-12:
                self._bucket_buf.append(
                    (self._partial_buy, self._partial_sell, self._partial_vol)
                )
                self._partial_buy = 0.0
                self._partial_sell = 0.0
                self._partial_vol = 0.0

        # Compute VPIN from bucket buffer
        vpin = np.nan
        if len(self._bucket_buf) >= self.n_buckets:
            bufs = list(self._bucket_buf)[-self.n_buckets :]
            imb = sum(abs(b - s) for b, s, _ in bufs)
            total_vol = sum(v for _, _, v in bufs)
            if total_vol > 0:
                vpin = imb / total_vol

        if not np.isnan(vpin):
            self._vpin_buf.append(vpin)

        # Z-score
        vpin_z = np.nan
        if len(self._vpin_buf) > 1:
            buf_arr = np.array(self._vpin_buf)
            mean = float(np.mean(buf_arr))
            std = float(np.std(buf_arr))
            if std < 1e-12:
                std = 1e-12
            vpin_z = (vpin - mean) / std

        net_ratio = taker_buy_base / max(volume, 1e-12)

        return {
            "vpin": vpin,
            "vpin_z": vpin_z,
            "net_taker_buy_ratio": net_ratio,
        }
