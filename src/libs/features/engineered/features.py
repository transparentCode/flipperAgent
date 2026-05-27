"""Concrete engineered feature implementations.

Each feature is registered via @EngineeredFeatureRegistry.register("name").

Indicator output formats used here (from actual indicator code):
- BollingerBands.update() -> (middle, upper, lower)  tuple of 3 floats
- KeltnerChannel.update() -> (middle, upper, lower)   tuple of 3 floats
- ATR.update() -> float
- KAMA.update() -> float  (config key may be KAMA_slow, KAMA_fast, etc.)
- Momentum.update() -> float
- RSI.update() -> float
- ADX.update() -> float
"""

import math
from collections import deque
from typing import Any

from libs.features.engineered.base import EngineeredFeature
from libs.features.engineered.registry import EngineeredFeatureRegistry


@EngineeredFeatureRegistry.register("volume_adjusted_momentum")
class VolumeAdjustedMomentum(EngineeredFeature):
    """Momentum weighted by relative volume: Momentum × (V / SMA(V, 20))."""

    @property
    def name(self) -> str:
        return "volume_adjusted_momentum"

    @property
    def required_indicators(self) -> list[str]:
        return ["Momentum"]

    @property
    def required_bar_fields(self) -> list[str]:
        return ["volume"]

    def compute(
        self,
        features: dict[str, Any],
        bar_data: dict[str, float],
        state: dict[str, Any],
    ) -> float | None:
        momentum = features.get("Momentum")
        volume = bar_data.get("volume")
        if momentum is None or volume is None:
            return None

        if "vol_window" not in state:
            state["vol_window"] = deque(maxlen=20)

        state["vol_window"].append(volume)

        if len(state["vol_window"]) < 20:
            return None

        vol_mean = sum(state["vol_window"]) / len(state["vol_window"])
        if vol_mean == 0:
            return None

        vol_ratio = volume / vol_mean
        return momentum * vol_ratio


@EngineeredFeatureRegistry.register("atr_normalized_return")
class ATRNormalizedReturn(EngineeredFeature):
    """Bar-to-bar return scaled by ATR: (close - prev_close) / ATR."""

    @property
    def name(self) -> str:
        return "atr_normalized_return"

    @property
    def required_indicators(self) -> list[str]:
        return ["ATR"]

    @property
    def required_bar_fields(self) -> list[str]:
        return ["close"]

    def compute(
        self,
        features: dict[str, Any],
        bar_data: dict[str, float],
        state: dict[str, Any],
    ) -> float | None:
        atr = features.get("ATR")
        close = bar_data.get("close")
        if atr is None or close is None:
            return None

        result = None
        if state.get("prev_close") is not None:
            raw_return = close - state["prev_close"]
            result = raw_return / atr if atr > 0 else 0.0

        state["prev_close"] = close
        return result


@EngineeredFeatureRegistry.register("residual_momentum")
class ResidualMomentum(EngineeredFeature):
    """Momentum component unexplained by RSI: Momentum - β × RSI_norm.

    β is estimated via Welford-style online OLS over a rolling 50-bar window.
    """

    @property
    def name(self) -> str:
        return "residual_momentum"

    @property
    def required_indicators(self) -> list[str]:
        return ["Momentum", "RSI"]

    @property
    def required_bar_fields(self) -> list[str]:
        return []

    def compute(
        self,
        features: dict[str, Any],
        bar_data: dict[str, float],
        state: dict[str, Any],
    ) -> float | None:
        momentum = features.get("Momentum")
        rsi = features.get("RSI")
        if momentum is None or rsi is None:
            return None

        rsi_norm = (rsi - 50) / 50  # center and scale to [-1, 1]

        # Initialize rolling window deque if needed
        if "window" not in state:
            state["window"] = deque(maxlen=50)
            state["sum_x"] = 0.0
            state["sum_y"] = 0.0
            state["sum_xx"] = 0.0
            state["sum_xy"] = 0.0

        window = state["window"]

        # If window is full, remove the oldest entry from accumulators
        if len(window) == 50:
            old_x, old_y = window[0]
            state["sum_x"] -= old_x
            state["sum_y"] -= old_y
            state["sum_xx"] -= old_x * old_x
            state["sum_xy"] -= old_x * old_y

        # Add current entry
        window.append((rsi_norm, momentum))
        state["sum_x"] += rsi_norm
        state["sum_y"] += momentum
        state["sum_xx"] += rsi_norm * rsi_norm
        state["sum_xy"] += rsi_norm * momentum

        n = len(window)
        if n < 50:
            return None

        # OLS: β = (n * sum_xy - sum_x * sum_y) / (n * sum_xx - sum_x^2)
        denominator = n * state["sum_xx"] - state["sum_x"] ** 2
        if abs(denominator) < 1e-12:
            beta = 0.0
        else:
            beta = (n * state["sum_xy"] - state["sum_x"] * state["sum_y"]) / denominator

        residual = momentum - beta * rsi_norm
        return residual


@EngineeredFeatureRegistry.register("squeeze_intensity")
class SqueezeIntensity(EngineeredFeature):
    """BB_bandwidth / KC_width. Values < 1.0 indicate a squeeze."""

    @property
    def name(self) -> str:
        return "squeeze_intensity"

    @property
    def required_indicators(self) -> list[str]:
        return ["BollingerBands", "KeltnerChannel"]

    @property
    def required_bar_fields(self) -> list[str]:
        return []

    def compute(
        self,
        features: dict[str, Any],
        bar_data: dict[str, float],
        state: dict[str, Any],
    ) -> float | None:
        bb = features.get("BollingerBands")
        kc = features.get("KeltnerChannel")
        if bb is None or kc is None:
            return None

        # BollingerBands.update() returns (middle, upper, lower)
        bb_bw = bb[1] - bb[2]  # upper - lower

        # KeltnerChannel.update() returns (middle, upper, lower)
        kc_w = kc[1] - kc[2]  # upper - lower

        if kc_w <= 0:
            return 1.0

        return bb_bw / kc_w


@EngineeredFeatureRegistry.register("regime_score")
class RegimeScore(EngineeredFeature):
    """Continuous regime indicator: tanh((ADX - 25) / 10)."""

    @property
    def name(self) -> str:
        return "regime_score"

    @property
    def required_indicators(self) -> list[str]:
        return ["ADX"]

    @property
    def required_bar_fields(self) -> list[str]:
        return []

    def compute(
        self,
        features: dict[str, Any],
        bar_data: dict[str, float],
        state: dict[str, Any],
    ) -> float | None:
        adx = features.get("ADX")
        if adx is None:
            return None

        return math.tanh((adx - 25) / 10)


@EngineeredFeatureRegistry.register("mean_reversion_z")
class MeanReversionZ(EngineeredFeature):
    """Z-score of price deviation from KAMA_slow, normalized by ATR."""

    @property
    def name(self) -> str:
        return "mean_reversion_z"

    @property
    def required_indicators(self) -> list[str]:
        return ["KAMA_slow", "ATR"]

    @property
    def required_bar_fields(self) -> list[str]:
        return ["close"]

    def compute(
        self,
        features: dict[str, Any],
        bar_data: dict[str, float],
        state: dict[str, Any],
    ) -> float | None:
        kama_slow = features.get("KAMA_slow")
        atr = features.get("ATR")
        close = bar_data.get("close")
        if kama_slow is None or atr is None or close is None:
            return None

        if atr <= 0:
            return 0.0

        return (close - kama_slow) / atr
