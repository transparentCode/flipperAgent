"""Cross-sectional engineered features consuming TradingView index data.

These features use market-wide indices (BTC.D, TOTAL2, TOTAL3) as
regime and breadth signals.  They degrade gracefully to 0.0 when
index data is unavailable.
"""

import math
from collections import deque
from typing import Any

from libs.features.engineered.base import EngineeredFeature
from libs.features.engineered.registry import EngineeredFeatureRegistry


@EngineeredFeatureRegistry.register("btc_dominance_regime")
class BTCDominanceRegime(EngineeredFeature):
    """Regime signal from BTC dominance: tanh((BTC.D - center) / scale)."""

    @property
    def name(self) -> str:
        return "btc_dominance_regime"

    @property
    def required_indicators(self) -> list[str]:
        return []

    @property
    def required_bar_fields(self) -> list[str]:
        return []

    def compute(
        self,
        features: dict[str, Any],
        bar_data: dict[str, float],
        state: dict[str, Any],
        index_data: dict[str, dict[str, float]] | None = None,
    ) -> float | None:
        if not index_data or "BTC.D" not in index_data:
            return 0.0

        btc_d = index_data["BTC.D"]
        close = btc_d.get("close")
        if close is None:
            return 0.0

        center = 50.0
        scale = 10.0
        return math.tanh((close - center) / scale)


@EngineeredFeatureRegistry.register("altcoin_market_momentum")
class AltcoinMarketMomentum(EngineeredFeature):
    """Normalized momentum of TOTAL3: (close - SMA20) / ATR14."""

    @property
    def name(self) -> str:
        return "altcoin_market_momentum"

    @property
    def required_indicators(self) -> list[str]:
        return []

    @property
    def required_bar_fields(self) -> list[str]:
        return []

    def compute(
        self,
        features: dict[str, Any],
        bar_data: dict[str, float],
        state: dict[str, Any],
        index_data: dict[str, dict[str, float]] | None = None,
    ) -> float | None:
        if not index_data or "TOTAL3" not in index_data:
            return 0.0

        t3 = index_data["TOTAL3"]
        close = t3.get("close")
        high = t3.get("high")
        low = t3.get("low")
        if close is None:
            return 0.0

        # Initialize rolling state
        if "closes" not in state:
            state["closes"] = deque(maxlen=20)
            state["tr_values"] = deque(maxlen=14)
            state["prev_close"] = None
            state["atr"] = None

        state["closes"].append(close)

        # Compute True Range for ATR
        prev_close = state["prev_close"]
        if prev_close is not None and high is not None and low is not None:
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )
            state["tr_values"].append(tr)
        elif high is not None and low is not None:
            state["tr_values"].append(high - low)

        state["prev_close"] = close

        # Need at least 20 closes for SMA and 14 TRs for ATR
        if len(state["closes"]) < 20 or len(state["tr_values"]) < 14:
            return 0.0

        sma = sum(state["closes"]) / len(state["closes"])
        atr = sum(state["tr_values"]) / len(state["tr_values"])

        if atr <= 0:
            return 0.0

        return (close - sma) / atr


@EngineeredFeatureRegistry.register("market_cap_breadth")
class MarketCapBreadth(EngineeredFeature):
    """Rate of change of TOTAL2/TOTAL3 ratio."""

    @property
    def name(self) -> str:
        return "market_cap_breadth"

    @property
    def required_indicators(self) -> list[str]:
        return []

    @property
    def required_bar_fields(self) -> list[str]:
        return []

    def compute(
        self,
        features: dict[str, Any],
        bar_data: dict[str, float],
        state: dict[str, Any],
        index_data: dict[str, dict[str, float]] | None = None,
    ) -> float | None:
        if not index_data:
            return 0.0
        if "TOTAL2" not in index_data or "TOTAL3" not in index_data:
            return 0.0

        t2_close = index_data["TOTAL2"].get("close")
        t3_close = index_data["TOTAL3"].get("close")
        if t2_close is None or t3_close is None or t3_close <= 0:
            return 0.0

        ratio = t2_close / t3_close
        prev_ratio = state.get("prev_ratio")
        state["prev_ratio"] = ratio

        if prev_ratio is None or prev_ratio <= 0:
            return 0.0

        return (ratio - prev_ratio) / prev_ratio


@EngineeredFeatureRegistry.register("altcoin_beta")
class AltcoinBeta(EngineeredFeature):
    """Rolling 20-bar beta of asset returns vs TOTAL2 returns.

    beta = Cov(R_asset, R_total2) / Var(R_total2)
    Uses Welford-style online computation.
    """

    @property
    def name(self) -> str:
        return "altcoin_beta"

    @property
    def required_indicators(self) -> list[str]:
        return []

    @property
    def required_bar_fields(self) -> list[str]:
        return ["close"]

    def compute(
        self,
        features: dict[str, Any],
        bar_data: dict[str, float],
        state: dict[str, Any],
        index_data: dict[str, dict[str, float]] | None = None,
    ) -> float | None:
        asset_close = bar_data.get("close")
        if asset_close is None:
            return 0.0

        if not index_data or "TOTAL2" not in index_data:
            return 0.0

        t2_close = index_data["TOTAL2"].get("close")
        if t2_close is None:
            return 0.0

        # Initialize state
        if "return_pairs" not in state:
            state["return_pairs"] = deque(maxlen=20)
            state["prev_asset_close"] = None
            state["prev_total2_close"] = None

        prev_asset = state["prev_asset_close"]
        prev_total2 = state["prev_total2_close"]
        state["prev_asset_close"] = asset_close
        state["prev_total2_close"] = t2_close

        # Need previous closes to compute returns
        if prev_asset is None or prev_total2 is None:
            return 0.0
        if prev_asset <= 0 or prev_total2 <= 0:
            return 0.0

        asset_ret = (asset_close - prev_asset) / prev_asset
        total2_ret = (t2_close - prev_total2) / prev_total2

        state["return_pairs"].append((asset_ret, total2_ret))

        if len(state["return_pairs"]) < 20:
            return 0.0

        # Compute Cov and Var from rolling window
        pairs = state["return_pairs"]
        n = len(pairs)
        sum_x = sum(p[1] for p in pairs)  # total2 returns
        sum_y = sum(p[0] for p in pairs)  # asset returns
        sum_xx = sum(p[1] ** 2 for p in pairs)
        sum_xy = sum(p[0] * p[1] for p in pairs)

        var_x = n * sum_xx - sum_x ** 2
        if abs(var_x) < 1e-12:
            return 0.0

        cov_xy = n * sum_xy - sum_x * sum_y
        beta = cov_xy / var_x
        return beta
