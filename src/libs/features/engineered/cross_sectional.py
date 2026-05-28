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


# ---------------------------------------------------------------------------
# New cross-asset regime features
# ---------------------------------------------------------------------------


@EngineeredFeatureRegistry.register("btc_dominance_momentum")
class BTCDominanceMomentum(EngineeredFeature):
    """Normalized momentum of BTC.D: (close - SMA(close, period)) / ATR(period).

    Positive → BTC.D rising (alts weakening).
    Negative → BTC.D falling (alt season starting).
    """

    @property
    def name(self) -> str:
        return "btc_dominance_momentum"

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
        high = btc_d.get("high")
        low = btc_d.get("low")
        if close is None:
            return 0.0

        sma_period = self.params.get("sma_period", 10)
        atr_period = self.params.get("atr_period", 14)

        # Initialize rolling state
        if "closes" not in state:
            state["closes"] = deque(maxlen=sma_period)
            state["tr_values"] = deque(maxlen=atr_period)
            state["prev_close"] = None

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

        if len(state["closes"]) < sma_period or len(state["tr_values"]) < atr_period:
            return 0.0

        sma = sum(state["closes"]) / len(state["closes"])
        atr = sum(state["tr_values"]) / len(state["tr_values"])

        if atr <= 0:
            return 0.0

        return (close - sma) / atr


@EngineeredFeatureRegistry.register("total3_momentum_z")
class Total3MomentumZ(EngineeredFeature):
    """Z-score of TOTAL3 momentum relative to its own rolling distribution.

    Uses Welford's online algorithm for rolling mean/std.
    Clipped to [-clip_range, clip_range].
    """

    @property
    def name(self) -> str:
        return "total3_momentum_z"

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
        if close is None:
            return 0.0

        sma_period = self.params.get("sma_period", 20)
        z_period = self.params.get("z_period", 50)
        clip_range = self.params.get("clip_range", 3.0)

        # Initialize rolling state
        if "closes" not in state:
            state["closes"] = deque(maxlen=sma_period)
            state["mom_values"] = deque(maxlen=z_period)

        state["closes"].append(close)

        if len(state["closes"]) < sma_period:
            return 0.0

        sma = sum(state["closes"]) / len(state["closes"])
        raw_mom = close - sma

        state["mom_values"].append(raw_mom)

        if len(state["mom_values"]) < z_period:
            return 0.0

        # Welford's online mean/std from the deque
        n = len(state["mom_values"])
        mean = sum(state["mom_values"]) / n
        variance = sum((v - mean) ** 2 for v in state["mom_values"]) / n
        std = math.sqrt(variance) if variance > 0 else 0.0

        if std < 1e-12:
            return 0.0

        z = (raw_mom - mean) / std
        return max(-clip_range, min(clip_range, z))


@EngineeredFeatureRegistry.register("relative_strength_vs_total3")
class RelativeStrengthVsTotal3(EngineeredFeature):
    """Per-asset relative strength vs TOTAL3.

    RS = (asset_return_N - TOTAL3_return_N) / max(abs(TOTAL3_return_N), epsilon)
    """

    @property
    def name(self) -> str:
        return "relative_strength_vs_total3"

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

        if not index_data or "TOTAL3" not in index_data:
            return 0.0

        t3_close = index_data["TOTAL3"].get("close")
        if t3_close is None:
            return 0.0

        period = self.params.get("period", 20)

        if "asset_closes" not in state:
            state["asset_closes"] = deque(maxlen=period + 1)
            state["t3_closes"] = deque(maxlen=period + 1)

        state["asset_closes"].append(asset_close)
        state["t3_closes"].append(t3_close)

        if len(state["asset_closes"]) <= period:
            return 0.0

        asset_old = state["asset_closes"][-period - 1]
        t3_old = state["t3_closes"][-period - 1]

        if asset_old <= 0 or t3_old <= 0:
            return 0.0

        asset_ret = (asset_close - asset_old) / asset_old
        t3_ret = (t3_close - t3_old) / t3_old

        clip_range = self.params.get("clip_range", 10.0)
        raw = (asset_ret - t3_ret) / max(abs(t3_ret), 1e-4)
        return max(-clip_range, min(clip_range, raw))


@EngineeredFeatureRegistry.register("cross_asset_regime_state")
class CrossAssetRegimeState(EngineeredFeature):
    """4-state regime classifier from BTC.D momentum + altcoin momentum.

    States: RISK_OFF=0, ALT_SEASON=1, ROTATION=2, BROAD_SELLOFF=3.
    """

    @property
    def name(self) -> str:
        return "cross_asset_regime_state"

    @property
    def depends_on_engineered(self) -> bool:
        return True

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
        btc_d_mom = features.get("eng_btc_dominance_momentum", 0.0)
        t3_mom = features.get("eng_altcoin_market_momentum", 0.0)

        btc_d_threshold = self.params.get("btc_d_threshold", 0.3)
        t3_threshold = self.params.get("t3_threshold", 0.3)

        btc_d_rising = btc_d_mom > btc_d_threshold
        btc_d_falling = btc_d_mom < -btc_d_threshold
        t3_rising = t3_mom > t3_threshold
        t3_falling = t3_mom < -t3_threshold

        if btc_d_rising and t3_falling:
            return 0  # RISK_OFF
        elif btc_d_falling and t3_rising:
            return 1  # ALT_SEASON
        elif btc_d_rising and t3_rising:
            return 2  # ROTATION
        elif btc_d_falling and t3_falling:
            return 3  # BROAD_SELLOFF
        else:
            return 2  # ROTATION (default neutral)


@EngineeredFeatureRegistry.register("regime_alignment_score")
class RegimeAlignmentScore(EngineeredFeature):
    """Continuous composite regime alignment score in [-1, 1].

    regime_alignment = w1*tanh(btc_d_mom) + w2*tanh(t3_mom)
                     + w3*tanh(breadth) + w4*tanh(rs)
    """

    @property
    def name(self) -> str:
        return "regime_alignment_score"

    @property
    def depends_on_engineered(self) -> bool:
        return True

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
        btc_d_mom = features.get("eng_btc_dominance_momentum", 0.0)
        t3_mom = features.get("eng_altcoin_market_momentum", 0.0)
        breadth = features.get("eng_market_cap_breadth", 0.0)
        rs = features.get("eng_relative_strength_vs_total3", 0.0)

        w1 = self.params.get("w_btc_d", 0.3)
        w2 = self.params.get("w_t3", 0.3)
        w3 = self.params.get("w_breadth", 0.2)
        w4 = self.params.get("w_rs", 0.2)
        breadth_scale = self.params.get("breadth_scale", 10.0)

        # Normalize each component to [-1, 1] via tanh, then weight
        # Negate btc_d_mom because rising BTC.D is bearish for alts
        score = (
            w1 * math.tanh(-btc_d_mom)
            + w2 * math.tanh(t3_mom)
            + w3 * math.tanh(breadth * breadth_scale)
            + w4 * math.tanh(rs)
        )

        return max(-1.0, min(1.0, score))
