from __future__ import annotations

import numpy as np
import pandas as pd

from libs.contracts.schemas import FeatureVector
from libs.models.regime_classification.l2_features import compute_l2_snapshot_features
from libs.models.regime_classification.model import RegimeClassificationModel
from libs.models.registry import ModelRegistry


def _frame(n: int = 260) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    trend = np.linspace(100.0, 125.0, n)
    wave = np.sin(np.linspace(0.0, 18.0, n)) * 2.0
    return pd.DataFrame({"close": trend + wave}, index=index)


def test_emit_frame_returns_probability_descriptors():
    model = RegimeClassificationModel({})

    emitted = model.emit_frame(_frame())

    assert "regime_prob_trend" in emitted.columns
    assert "regime_ewma_fwd_vol" in emitted.columns
    assert "regime_state_entropy" in emitted.columns
    assert emitted["regime_prob_trend"].dropna().between(0.0, 1.0).all()
    assert emitted["regime_state_entropy"].dropna().between(0.0, 1.0).all()


def test_batch_evaluate_returns_confidence_series():
    model = RegimeClassificationModel({})
    frame = _frame()

    confidence = model.batch_evaluate(frame)

    assert len(confidence) == len(frame)
    assert confidence.dropna().between(0.0, 1.0).all()


def test_evaluate_returns_flat_feature_producer_output():
    model = RegimeClassificationModel({})
    features = FeatureVector(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1.0,
        features={
            "regime_prob_trend": 0.7,
            "regime_prob_mean_reversion": 0.2,
            "regime_prob_high_vol": 0.4,
            "regime_prob_low_vol": 0.6,
            "regime_prob_risk_off": 0.1,
            "regime_confidence": 0.8,
        },
        bar_data={"close": 100.0},
    )

    output = model.evaluate(features)

    assert output.direction == 0
    assert output.conviction == 0.8
    assert output.metadata["probabilities"]["trend"] == 0.7
    assert output.metadata["regime_prob_trend"] == 0.7


def test_l2_snapshot_features_are_finite_for_valid_book():
    bids = [(100.0, 5.0), (99.9, 3.0), (99.8, 2.0)]
    asks = [(100.1, 4.0), (100.2, 2.0), (100.3, 1.0)]

    row = compute_l2_snapshot_features(bids, asks)

    assert row["l2_bid_ask_imbalance"] > 0.0
    assert row["l2_spread_bps"] > 0.0
    assert np.isfinite(row["l2_microprice_deviation_bps"])


def test_model_registry_auto_discovers_regime_classification():
    ModelRegistry.auto_discover()

    assert ModelRegistry.get("RegimeClassification") is RegimeClassificationModel
