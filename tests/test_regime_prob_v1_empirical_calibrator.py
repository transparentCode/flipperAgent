from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_prob_v1 import (
    RegimeProbLabelConfig,
    build_regime_prob_edge_labels,
    build_regime_prob_feature_frame,
    build_empirical_calibration_report,
    fit_empirical_calibrator,
    fit_playbook_empirical_calibrator,
)


def _make_ohlcv(n: int = 260, *, trend: float = 0.003, noise: float = 0.001) -> pd.DataFrame:
    rng = np.random.default_rng(77)
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    returns = trend + rng.normal(0.0, noise, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * 1.004
    low = np.minimum(open_, close) * 0.996
    volume = 1000.0 + rng.normal(0.0, 20.0, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def test_empirical_calibrator_fits_and_reports_bucket_metrics():
    scores = pd.Series(np.linspace(0.0, 1.0, 100))
    labels = pd.Series((scores >= 0.6).astype(float))

    model = fit_empirical_calibrator(scores, labels, n_bins=5, min_bin_count=5)
    probabilities = model.predict_proba(scores)
    report = build_empirical_calibration_report(scores, labels, model)

    assert len(model.bin_probabilities) >= 1
    assert np.isfinite(probabilities).all()
    assert probabilities[-1] >= probabilities[0]
    assert 0.0 <= report["brier_score"] <= 1.0
    assert report["bucket_count"] >= 1
    assert report["top_bottom_bucket_spread"] >= 0.0


def test_fit_playbook_empirical_calibrator_scores_segments_from_feature_and_label_frames():
    df = _make_ohlcv()
    features = build_regime_prob_feature_frame(df, asset="BTCUSDT", timeframe="1h")
    labels = build_regime_prob_edge_labels(
        features,
        df,
        timeframe="1h",
        config=RegimeProbLabelConfig(horizons=(3,), fee_bps=0.0),
    )

    result = fit_playbook_empirical_calibrator(
        features,
        labels.frame,
        playbook="trend_following",
        horizon=3,
        split=labels.split,
        n_bins=5,
        min_bin_count=3,
    )

    assert result.score_column == "policy_trend_score"
    assert result.label_column == "trend_following_edge_positive_h3"
    assert result.probabilities.index.equals(features.index)
    assert result.reports["calibration"]["support_count"] > 0
    assert 0.0 <= result.reports["oos"]["brier_score"] <= 1.0
