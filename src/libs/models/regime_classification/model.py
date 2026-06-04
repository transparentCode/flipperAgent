"""
RegimeClassificationModel — feature-producing model.

Orchestrates BCPD, HMM, Vol, Hilbert, and Hurst kernels to emit
a continuous probability matrix plus descriptors per bar.
Direction is always 0 (flat) — this model produces features, not signals.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

from libs.contracts.schemas import FeatureVector, ModelOutput, ParamDef
from libs.models.base import BaseModel, ModelMeta
from libs.models.regime_classification.config import (
    BCPDConfig,
    EWMAVolConfig,
    HilbertConfig,
    HMMConfig,
    RegimeClassificationConfig,
    TrendStrengthConfig,
    VolConfig,
)
from libs.models.regime_classification.contracts import (
    RegimeFeatureOutput,
)
from libs.models.regime_classification.kernels.bcpd import bcpd_detect
from libs.models.regime_classification.kernels.hilbert import HilbertCycle
from libs.models.regime_classification.kernels.hmm import (
    HMMClassifier,
    HMMClassifierConfig,
)
from libs.models.regime_classification.kernels.hurst import rolling_hurst
from libs.models.regime_classification.kernels.vol_percentile import (
    VolPercentile,
    VolPercentileConfig,
)

logger = logging.getLogger(__name__)


class RegimeClassificationModel(BaseModel):
    """
    Feature-producing model that emits regime probability matrix.

    Output is packed into ModelOutput.metadata via RegimeFeatureOutput.to_dict().
    direction=0 and conviction=0.0 always (not a signal model).
    """

    meta = ModelMeta(
        name="RegimeClassification",
        required_indicators=[],
        required_fields=["close"],
        hyperparameter_schema={
            "bcpd_hazard_lambda": ParamDef(
                type="float", default=150.0, low=50.0, high=500.0, step=10.0
            ),
            "hurst_lookback": ParamDef(
                type="int", default=100, low=30, high=300, step=10
            ),
            "hmm_student_df": ParamDef(
                type="float", default=5.0, low=2.5, high=20.0, step=0.5
            ),
            "hilbert_min_period": ParamDef(
                type="int", default=10, low=5, high=20, step=1
            ),
            "hilbert_max_period": ParamDef(
                type="int", default=40, low=20, high=80, step=5
            ),
        },
        min_history_bars=200,
        model_type="feature_producer",
        external_data_sources=["l2_orderbook"],
        sub_models=[],
    )

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params or {})
        self._cfg = self._build_config()
        self._hmm = HMMClassifier(
            HMMClassifierConfig(
                retrain_window=self._cfg.hmm.retrain_window,
                min_train_bars=self._cfg.hmm.min_train_bars,
                log_vol_lookback=self._cfg.hmm.log_vol_lookback,
                hurst_lookback=self.params["hurst_lookback"],
                use_hurst=self._cfg.hmm.use_hurst,
                use_volume=self._cfg.hmm.use_volume,
                hmm_n_states=self._cfg.hmm.hmm_n_states,
                hmm_max_states=self._cfg.hmm.hmm_max_states,
                hmm_covariance_type=self._cfg.hmm.hmm_covariance_type,
                hmm_robust_scoring=self._cfg.hmm.hmm_robust_scoring,
                hmm_student_df=self.params["hmm_student_df"],
                hmm_crisis_vol_mult=self._cfg.hmm.hmm_crisis_vol_mult,
            )
        )
        self._vol = VolPercentile(
            VolPercentileConfig(
                lookback=self._cfg.vol.lookback,
                rank_window=self._cfg.vol.rank_window,
            )
        )
        self._hilbert = HilbertCycle(
            min_period=self.params["hilbert_min_period"],
            max_period=self.params["hilbert_max_period"],
            stability_bars=self._cfg.hilbert.stability_bars,
        )
        self._ewma_var: float = 0.0
        self._ewma_bars: int = 0

    def _build_config(self) -> RegimeClassificationConfig:
        return RegimeClassificationConfig(
            bcpd=BCPDConfig(
                hazard_lambda=self.params["bcpd_hazard_lambda"],
            ),
            hmm=HMMConfig(
                hurst_lookback=self.params["hurst_lookback"],
                hmm_student_df=self.params["hmm_student_df"],
            ),
            vol=VolConfig(),
            hilbert=HilbertConfig(
                min_period=self.params["hilbert_min_period"],
                max_period=self.params["hilbert_max_period"],
            ),
            ewma_vol=EWMAVolConfig(),
            trend=TrendStrengthConfig(),
        )

    # ------------------------------------------------------------------
    # Single-bar evaluation
    # ------------------------------------------------------------------

    def evaluate(self, features: FeatureVector) -> ModelOutput:
        """Single-bar: uses bar_data for OHLCV, features dict for L2."""
        bar = features.bar_data
        close = bar.get("close", 0.0)
        if close <= 0:
            return self._empty_output(features)

        output = RegimeFeatureOutput()

        # L2 orderbook (from features dict, NaN if absent)
        output.bid_ask_imbalance = features.features.get(
            "bid_ask_imbalance", math.nan
        )
        output.depth_ratio = features.features.get("depth_ratio", math.nan)
        output.spread_bps = features.features.get("spread_bps", math.nan)
        output.depth_decay_bid = features.features.get(
            "depth_decay_bid", math.nan
        )
        output.depth_decay_ask = features.features.get(
            "depth_decay_ask", math.nan
        )

        # Note: BCPD, HMM, Hurst, Hilbert, Vol require history — single-bar
        # evaluation returns defaults for those fields. Use batch_evaluate
        # for full pipeline with history.

        return ModelOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            direction=0,
            conviction=0.0,
            metadata=output.to_dict(),
        )

    # ------------------------------------------------------------------
    # Batch evaluation
    # ------------------------------------------------------------------

    def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series:
        """
        Run all 5 kernels over the full history and emit per-bar features.

        Returns a Series of dicts (RegimeFeatureOutput.to_dict()).
        """
        n = len(feature_df)
        close = feature_df["close"].values.astype(float)
        has_volume = "volume" in feature_df.columns

        # ----- 1. BCPD -----
        returns = np.diff(np.log(close + 1e-10))
        cp_probs = np.zeros(n)
        run_lengths = np.zeros(n, dtype=int)
        cp_entropies = np.zeros(n)

        if len(returns) >= 20:
            rl_post, changepoint_probs = bcpd_detect(
                returns,
                hazard_lambda=self._cfg.bcpd.hazard_lambda,
                hazard_shape=self._cfg.bcpd.hazard_shape,
                truncation=self._cfg.bcpd.truncation,
            )
            cp_probs[1:] = changepoint_probs
            run_lengths[1:] = np.argmax(rl_post, axis=1)
            # Entropy of run-length posterior per bar
            for t in range(rl_post.shape[0]):
                row = rl_post[t]
                row = row[row > 1e-30]
                cp_entropies[t + 1] = -np.sum(row * np.log(row))

        # ----- 2. Hurst -----
        hurst_arr = rolling_hurst(
            close,
            lookback=self.params["hurst_lookback"],
            min_periods=min(50, self.params["hurst_lookback"] // 2),
        )

        # ----- 3. Hilbert -----
        try:
            periods, confidences = self._hilbert.calculate_series(close)
        except Exception:
            periods = np.full(n, 40.0)
            confidences = np.zeros(n)

        # ----- 4. Vol percentile -----
        vol_df = self._vol.compute_series(feature_df)
        vol_pcts = vol_df["vol_percentile"].values
        vol_rolling = vol_df["vol_rolling"].values

        # ----- 5. HMM -----
        hmm_df = self._hmm.classify_series(feature_df)

        # ----- 6. EWMA forward vol -----
        fwd_vol = self._compute_ewma_vol(returns)

        # ----- 7. Trend strength -----
        trend_str = self._compute_trend_strength(close)

        # ----- 8. L2 features (from feature_df if present) -----
        l2_cols = [
            "bid_ask_imbalance",
            "depth_ratio",
            "spread_bps",
            "depth_decay_bid",
            "depth_decay_ask",
        ]

        # ----- Assemble per-bar output -----
        results = []
        max_states = self._cfg.hmm.hmm_max_states
        for i in range(n):
            hmm_posteriors = tuple(
                float(hmm_df.iloc[i].get(f"hmm_p_state_{s}", 0.0))
                for s in range(max_states)
                if f"hmm_p_state_{s}" in hmm_df.columns
            )
            hmm_n = int(hmm_df.iloc[i].get("hmm_n_states", 2))
            hmm_crisis = float(hmm_df.iloc[i].get("hmm_crisis_prob", 0.0))
            hmm_trans = float(hmm_df.iloc[i].get("hmm_transition_prob", 0.5))

            output = RegimeFeatureOutput(
                hmm_posteriors=hmm_posteriors,
                hmm_n_states=hmm_n,
                hmm_transition_prob=hmm_trans,
                hmm_crisis_prob=hmm_crisis,
                vol_percentile=float(vol_pcts[i]),
                realized_vol=float(vol_rolling[i]) if np.isfinite(vol_rolling[i]) else 0.0,
                fwd_vol_ewma=float(fwd_vol[i]),
                trend_strength=float(trend_str[i]),
                hurst=float(hurst_arr[i]) if np.isfinite(hurst_arr[i]) else 0.5,
                changepoint_prob=float(cp_probs[i]),
                run_length=int(run_lengths[i]),
                cp_entropy=float(cp_entropies[i]),
                hilbert_period=float(periods[i]) if np.isfinite(periods[i]) else 40.0,
                hilbert_confidence=float(confidences[i]) if np.isfinite(confidences[i]) else 0.0,
            )

            # L2 features
            for col in l2_cols:
                if col in feature_df.columns:
                    setattr(output, col, float(feature_df.iloc[i][col]))

            results.append(output.to_dict())

        return pd.Series(results, index=feature_df.index)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_ewma_vol(self, returns: np.ndarray) -> np.ndarray:
        """EWMA forward vol: σ²_t = λ*σ²_{t-1} + (1-λ)*r²_t."""
        decay = self._cfg.ewma_vol.decay_factor
        n = len(returns) + 1  # +1 because returns has one fewer element
        result = np.zeros(n)

        if len(returns) == 0:
            return result

        var = float(returns[0] ** 2)
        result[0] = 0.0  # no estimate for first bar
        for t in range(len(returns)):
            var = decay * var + (1 - decay) * (returns[t] ** 2)
            result[t + 1] = math.sqrt(max(var, 0.0))

        return result

    def _compute_trend_strength(self, close: np.ndarray) -> np.ndarray:
        """Directional efficiency ratio: |net move| / sum(|bar moves|)."""
        lookback = self._cfg.trend.lookback
        n = len(close)
        result = np.zeros(n)

        for i in range(lookback, n):
            window = close[i - lookback : i + 1]
            net_move = abs(window[-1] - window[0])
            bar_moves = np.sum(np.abs(np.diff(window)))
            if bar_moves > 1e-10:
                result[i] = net_move / bar_moves
            else:
                result[i] = 0.0

        return result

    def _empty_output(self, features: FeatureVector) -> ModelOutput:
        return ModelOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            direction=0,
            conviction=0.0,
            metadata=RegimeFeatureOutput().to_dict(),
        )
