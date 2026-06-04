"""Regime classification feature producer.

This model emits continuous descriptors and probability-style fields. It does
not emit a trade direction, position size, or hard regime label.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from libs.contracts.schemas import FeatureVector, ModelOutput
from libs.models.base import BaseModel, ModelMeta
from libs.models.registry import ModelRegistry
from libs.models.regime_classification.config import (
    DEFAULT_L2_COLUMNS,
    REGIME_CLASSIFICATION_PARAMS,
)
from libs.models.regime_classification.contracts import RegimeFeatureOutput

_EPS = 1e-12


@ModelRegistry.register("RegimeClassification")
class RegimeClassificationModel(BaseModel):
    """Feature-only regime descriptor model."""

    meta = ModelMeta(
        name="RegimeClassification",
        model_type="feature_producer",
        required_indicators=[],
        required_fields=["close"],
        hyperparameter_schema=REGIME_CLASSIFICATION_PARAMS,
        min_history_bars=240,
        external_data_sources=["ohlcv", "optional_l2"],
    )

    def evaluate(self, features: FeatureVector) -> ModelOutput:
        output = self._evaluate_single(features)
        return ModelOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            direction=0,
            conviction=float(output.descriptors.get("confidence", 0.0)),
            metadata={
                "probabilities": output.probabilities,
                "descriptors": output.descriptors,
                **output.flatten(),
            },
        )

    def emit_frame(self, feature_df: pd.DataFrame) -> pd.DataFrame:
        """Return the full descriptor matrix for offline research and validation."""
        self._validate_temporal_ordering(feature_df)
        close = _extract_close(feature_df)
        returns = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        short_window = int(self.params["short_vol_window"])
        long_window = int(self.params["long_vol_window"])
        trend_window = int(self.params["trend_window"])
        rank_window = int(self.params["vol_rank_window"])
        ewma_lambda = float(self.params["ewma_lambda"])

        realized_vol_short = returns.rolling(short_window, min_periods=max(3, short_window // 4)).std()
        realized_vol_long = returns.rolling(long_window, min_periods=max(5, long_window // 4)).std()
        vol_ratio = realized_vol_short / realized_vol_long.replace(0.0, np.nan)
        vol_percentile = realized_vol_long.rolling(rank_window, min_periods=20).rank(pct=True) * 100.0
        ewma_fwd_vol = _ewma_vol(returns, ewma_lambda)
        trend_strength = _trend_efficiency(close, trend_window)
        trend_abs = trend_strength.abs().clip(0.0, 1.0)
        high_vol = (vol_percentile / 100.0).clip(0.0, 1.0)
        low_vol = (1.0 - high_vol).clip(0.0, 1.0)
        mean_reversion = (1.0 - trend_abs).clip(0.0, 1.0)
        risk_off = (high_vol * (-trend_strength).clip(0.0, 1.0)).clip(0.0, 1.0)

        probs = pd.DataFrame(
            {
                "regime_prob_trend": trend_abs,
                "regime_prob_mean_reversion": mean_reversion,
                "regime_prob_high_vol": high_vol,
                "regime_prob_low_vol": low_vol,
                "regime_prob_risk_off": risk_off,
            },
            index=feature_df.index,
        ).fillna(0.0)
        entropy = _normalized_entropy(probs)
        confidence = (1.0 - entropy).clip(0.0, 1.0)

        descriptors = pd.DataFrame(
            {
                "regime_trend_strength": trend_strength,
                "regime_realized_vol_short": realized_vol_short,
                "regime_realized_vol_long": realized_vol_long,
                "regime_vol_ratio": vol_ratio,
                "regime_vol_percentile": vol_percentile,
                "regime_ewma_fwd_vol": ewma_fwd_vol,
                "regime_state_entropy": entropy,
                "regime_confidence": confidence,
            },
            index=feature_df.index,
        )
        l2 = _extract_l2_columns(feature_df)
        return pd.concat([probs, descriptors, l2], axis=1).replace([np.inf, -np.inf], np.nan)

    def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series:
        emitted = self.emit_frame(feature_df)
        return emitted["regime_confidence"].fillna(0.0).astype(float)

    def _evaluate_single(self, features: FeatureVector) -> RegimeFeatureOutput:
        data = {**features.bar_data, **features.features}
        probabilities = {
            "trend": _float_feature(data, "regime_prob_trend"),
            "mean_reversion": _float_feature(data, "regime_prob_mean_reversion"),
            "high_vol": _float_feature(data, "regime_prob_high_vol"),
            "low_vol": _float_feature(data, "regime_prob_low_vol"),
            "risk_off": _float_feature(data, "regime_prob_risk_off"),
        }
        descriptors = {
            "trend_strength": _float_feature(data, "regime_trend_strength"),
            "realized_vol_short": _float_feature(data, "regime_realized_vol_short"),
            "realized_vol_long": _float_feature(data, "regime_realized_vol_long"),
            "vol_ratio": _float_feature(data, "regime_vol_ratio"),
            "vol_percentile": _float_feature(data, "regime_vol_percentile"),
            "ewma_fwd_vol": _float_feature(data, "regime_ewma_fwd_vol"),
            "state_entropy": _float_feature(data, "regime_state_entropy"),
            "confidence": _float_feature(data, "regime_confidence"),
        }
        for col in DEFAULT_L2_COLUMNS:
            descriptors[col] = _float_feature(data, col)
        return RegimeFeatureOutput(probabilities=probabilities, descriptors=descriptors)


def _extract_close(feature_df: pd.DataFrame) -> pd.Series:
    if "close" in feature_df.columns:
        return feature_df["close"].astype(float)
    if "Close" in feature_df.columns:
        return feature_df["Close"].astype(float)
    raise ValueError("RegimeClassification requires a close column")


def _trend_efficiency(close: pd.Series, window: int) -> pd.Series:
    directional_move = close.diff(window)
    path_length = close.diff().abs().rolling(window, min_periods=max(3, window // 4)).sum()
    return (directional_move / path_length.replace(0.0, np.nan)).clip(-1.0, 1.0)


def _ewma_vol(returns: pd.Series, lam: float) -> pd.Series:
    variance = returns.pow(2).ewm(alpha=1.0 - lam, adjust=False).mean()
    return np.sqrt(variance)


def _normalized_entropy(probabilities: pd.DataFrame) -> pd.Series:
    clipped = probabilities.clip(lower=_EPS)
    total = clipped.sum(axis=1).replace(0.0, np.nan)
    normalized = clipped.div(total, axis=0).fillna(0.0)
    entropy = -(normalized * np.log(normalized.clip(lower=_EPS))).sum(axis=1)
    return (entropy / np.log(max(len(probabilities.columns), 2))).clip(0.0, 1.0)


def _extract_l2_columns(feature_df: pd.DataFrame) -> pd.DataFrame:
    l2 = pd.DataFrame(index=feature_df.index)
    for col in DEFAULT_L2_COLUMNS:
        l2[col] = feature_df[col].astype(float) if col in feature_df.columns else np.nan
    return l2


def _float_feature(data: dict[str, Any], key: str) -> float:
    value = data.get(key, np.nan)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")
