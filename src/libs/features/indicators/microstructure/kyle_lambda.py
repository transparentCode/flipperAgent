"""KyleLambda — Kyle's Lambda price-impact indicator."""

from __future__ import annotations

from collections import deque
from typing import Any, Sequence

import numpy as np
import pandas as pd

from libs.features.indicators.base import Indicator
from libs.features.indicators.registry import IndicatorRegistry


@IndicatorRegistry.register("KyleLambda")
class KyleLambda(Indicator):
    """Estimates adverse-selection cost via |Δlog(close)| / √volume.

    Parameters
    ----------
    smooth : int
        Rolling-median window applied to raw kyle values.
    lookback : int
        Window for z-score normalisation of the smoothed lambda.
    informed_z : float
        Z-score threshold above which regime is 'informed'.
    noise_z : float
        Z-score threshold below which regime is 'noise'.
    """

    def __init__(
        self,
        smooth: int = 24,
        lookback: int = 200,
        informed_z: float = 1.0,
        noise_z: float = -0.5,
    ) -> None:
        super().__init__()
        self.smooth = smooth
        self.lookback = lookback
        self.informed_z = informed_z
        self.noise_z = noise_z

        # Live streaming state
        self._raw_buf: deque[float] = deque(maxlen=lookback + smooth)
        self._lambda_buf: deque[float] = deque(maxlen=lookback)
        self._last_close: float | None = None

    @property
    def lookback_required(self) -> int:
        return self.lookback + self.smooth

    # ------------------------------------------------------------------
    # Batch (vectorised)
    # ------------------------------------------------------------------

    def batch(self, data: pd.DataFrame) -> dict[str, Any]:
        """Compute Kyle Lambda over a DataFrame.

        Expected columns: close, volume, taker_buy_base.
        """
        close = data["close"].values.astype(np.float64)
        volume = data["volume"].values.astype(np.float64)
        taker_buy_base = data["taker_buy_base"].values.astype(np.float64)

        # Raw kyle lambda: |Δlog(close)| / √volume
        log_close = np.log(close)
        delta_log = np.abs(np.diff(log_close, prepend=log_close[0]))
        sqrt_vol = np.sqrt(np.maximum(volume, 1e-12))
        kyle_raw = delta_log / sqrt_vol

        # Smooth with rolling median
        kyle_raw_series = pd.Series(kyle_raw)
        kyle_lambda = kyle_raw_series.rolling(self.smooth, min_periods=1).median().values

        # Z-score over lookback
        kyle_series = pd.Series(kyle_lambda)
        roll_mean = kyle_series.rolling(self.lookback, min_periods=1).mean().values
        roll_std = kyle_series.rolling(self.lookback, min_periods=1).std(ddof=0).values
        roll_std = np.where(roll_std < 1e-12, 1e-12, roll_std)
        kyle_z = (kyle_lambda - roll_mean) / roll_std

        # Regime
        kyle_regime = np.where(
            kyle_z > self.informed_z,
            "informed",
            np.where(kyle_z < self.noise_z, "noise", "neutral"),
        )

        # Signed lambda: sign(net_taker) * kyle_lambda
        net_taker = taker_buy_base - (volume - taker_buy_base)
        kyle_signed = np.sign(net_taker) * kyle_lambda

        return {
            "kyle_lambda": kyle_lambda,
            "kyle_z": kyle_z,
            "kyle_regime": kyle_regime,
            "kyle_signed": kyle_signed,
        }

    # ------------------------------------------------------------------
    # Prime (streaming warm-up)
    # ------------------------------------------------------------------

    def prime(self, historical_data: Sequence[dict[str, float]]) -> None:
        self._raw_buf.clear()
        self._lambda_buf.clear()
        self._last_close = None

        for tick in historical_data:
            self._push_tick(tick)

        self._is_primed = True

    # ------------------------------------------------------------------
    # Update (streaming single tick)
    # ------------------------------------------------------------------

    def update(self, new_value: dict[str, float]) -> dict[str, Any]:
        if not self.is_primed:
            raise RuntimeError("Indicator must be primed before update() can be called.")
        return self._push_tick(new_value)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _push_tick(self, tick: dict[str, float]) -> dict[str, Any]:
        close = float(tick["close"])
        volume = float(tick["volume"])
        taker_buy_base = float(tick["taker_buy_base"])

        if self._last_close is None:
            raw = 0.0
        else:
            delta_log = abs(np.log(close) - np.log(self._last_close))
            raw = delta_log / np.sqrt(max(volume, 1e-12))
        self._last_close = close
        self._raw_buf.append(raw)

        # Rolling median over smooth window
        window = list(self._raw_buf)[-self.smooth :]
        kyle_lam = float(np.median(window))
        self._lambda_buf.append(kyle_lam)

        # Z-score over lookback
        buf_arr = np.array(self._lambda_buf)
        mean = float(np.mean(buf_arr))
        std = float(np.std(buf_arr))
        if std < 1e-12:
            std = 1e-12
        kyle_z = (kyle_lam - mean) / std

        # Regime
        if kyle_z > self.informed_z:
            regime = "informed"
        elif kyle_z < self.noise_z:
            regime = "noise"
        else:
            regime = "neutral"

        # Signed
        net_taker = taker_buy_base - (volume - taker_buy_base)
        kyle_signed = float(np.sign(net_taker)) * kyle_lam

        return {
            "kyle_lambda": kyle_lam,
            "kyle_z": kyle_z,
            "kyle_regime": regime,
            "kyle_signed": kyle_signed,
        }
