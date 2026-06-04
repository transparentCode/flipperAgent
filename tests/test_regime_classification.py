"""
Unit tests for RegimeClassificationModel.

Tests:
1. Model instantiation and defaults
2. Single-bar evaluate returns correct shape
3. Batch evaluate runs all kernels
4. Zero imports from libs.regime
5. L2 features handle NaN inputs
6. Contracts to_dict round-trip
"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from libs.contracts.schemas import FeatureVector, ModelOutput
from libs.models.regime_classification.contracts import (
    RegimeFeatureOutput,
    HMMStateLocal,
    VolStateLocal,
)
from libs.models.regime_classification.l2_features import (
    L2Features,
    compute_l2_features,
)
from libs.models.regime_classification.model import RegimeClassificationModel


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def model():
    return RegimeClassificationModel()


@pytest.fixture
def sample_df():
    """Generate synthetic OHLCV data for testing."""
    np.random.seed(42)
    n = 500
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    close = np.maximum(close, 1.0)  # avoid zero/negative prices
    return pd.DataFrame({
        "open": close * (1 + np.random.randn(n) * 0.001),
        "high": close * (1 + np.abs(np.random.randn(n) * 0.005)),
        "low": close * (1 - np.abs(np.random.randn(n) * 0.005)),
        "close": close,
        "volume": np.random.exponential(1000, n),
    }, index=pd.RangeIndex(n))


@pytest.fixture
def feature_vector():
    return FeatureVector(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1700000000.0,
        features={},
        bar_data={"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0},
    )


# ------------------------------------------------------------------
# 1. Instantiation
# ------------------------------------------------------------------

class TestInstantiation:

    def test_model_creates_with_defaults(self, model):
        assert model.meta.name == "RegimeClassification"
        assert model.meta.model_type == "feature_producer"
        assert model.params["bcpd_hazard_lambda"] == 150.0
        assert model.params["hurst_lookback"] == 100
        assert model.params["hmm_student_df"] == 5.0

    def test_model_creates_with_custom_params(self):
        m = RegimeClassificationModel({"bcpd_hazard_lambda": 200.0})
        assert m.params["bcpd_hazard_lambda"] == 200.0

    def test_meta_required_fields(self, model):
        assert "close" in model.meta.required_fields
        assert model.meta.required_indicators == []


# ------------------------------------------------------------------
# 2. Single-bar evaluate
# ------------------------------------------------------------------

class TestSingleBarEvaluate:

    def test_returns_model_output(self, model, feature_vector):
        result = model.evaluate(feature_vector)
        assert isinstance(result, ModelOutput)

    def test_direction_always_zero(self, model, feature_vector):
        result = model.evaluate(feature_vector)
        assert result.direction == 0

    def test_conviction_always_zero(self, model, feature_vector):
        result = model.evaluate(feature_vector)
        assert result.conviction == 0.0

    def test_metadata_has_regime_keys(self, model, feature_vector):
        result = model.evaluate(feature_vector)
        meta = result.metadata
        assert "hmm_n_states" in meta
        assert "vol_percentile" in meta
        assert "changepoint_prob" in meta
        assert "hurst" in meta
        assert "hilbert_period" in meta

    def test_l2_features_nan_when_absent(self, model, feature_vector):
        result = model.evaluate(feature_vector)
        meta = result.metadata
        assert meta["bid_ask_imbalance"] is None
        assert meta["spread_bps"] is None

    def test_l2_features_present_when_provided(self, model):
        fv = FeatureVector(
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1700000000.0,
            features={"bid_ask_imbalance": 0.3, "spread_bps": 1.5},
            bar_data={"close": 100.0},
        )
        result = model.evaluate(fv)
        assert result.metadata["bid_ask_imbalance"] == 0.3
        assert result.metadata["spread_bps"] == 1.5


# ------------------------------------------------------------------
# 3. Batch evaluate
# ------------------------------------------------------------------

class TestBatchEvaluate:

    def test_returns_series_of_dicts(self, model, sample_df):
        result = model.batch_evaluate(sample_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(sample_df)
        assert isinstance(result.iloc[0], dict)

    def test_all_regime_keys_present(self, model, sample_df):
        result = model.batch_evaluate(sample_df)
        meta = result.iloc[-1]
        expected_keys = [
            "hmm_n_states", "vol_percentile", "realized_vol",
            "fwd_vol_ewma", "trend_strength", "hurst",
            "changepoint_prob", "run_length", "cp_entropy",
            "hilbert_period", "hilbert_confidence",
        ]
        for key in expected_keys:
            assert key in meta, f"Missing key: {key}"

    def test_hmm_posteriors_sum_to_one(self, model, sample_df):
        result = model.batch_evaluate(sample_df)
        meta = result.iloc[-1]
        # Find all hmm_p_state_* keys
        state_probs = [v for k, v in meta.items() if k.startswith("hmm_p_state_")]
        total = sum(state_probs)
        assert abs(total - 1.0) < 0.05, f"HMM posteriors sum to {total}"

    def test_vol_percentile_in_range(self, model, sample_df):
        result = model.batch_evaluate(sample_df)
        for meta in result.iloc[-50:]:
            vp = meta["vol_percentile"]
            assert 0 <= vp <= 100, f"vol_percentile out of range: {vp}"

    def test_hurst_in_range(self, model, sample_df):
        result = model.batch_evaluate(sample_df)
        for meta in result.iloc[-50:]:
            h = meta["hurst"]
            if not math.isnan(h):
                assert -0.1 <= h <= 1.1, f"hurst out of range: {h}"

    def test_trend_strength_in_range(self, model, sample_df):
        result = model.batch_evaluate(sample_df)
        for meta in result.iloc[-50:]:
            ts = meta["trend_strength"]
            assert 0.0 <= ts <= 1.0, f"trend_strength out of range: {ts}"


# ------------------------------------------------------------------
# 4. Zero imports from libs.regime
# ------------------------------------------------------------------

class TestIndependence:

    def test_no_imports_from_old_regime(self):
        """Verify zero actual import statements from libs.regime."""
        model_dir = Path(__file__).resolve().parent.parent / "src" / "libs" / "models" / "regime_classification"
        if not model_dir.exists():
            # Fall back to searching from workspace root
            model_dir = Path(__file__).resolve()
            while model_dir.name != "flipperAgent" and model_dir != model_dir.parent:
                model_dir = model_dir.parent
            model_dir = model_dir / "src" / "libs" / "models" / "regime_classification"

        violations = []
        for py_file in model_dir.rglob("*.py"):
            content = py_file.read_text()
            for i, line in enumerate(content.splitlines(), 1):
                stripped = line.strip()
                if (
                    stripped.startswith("from libs.regime")
                    or stripped.startswith("import libs.regime")
                ):
                    violations.append(f"{py_file.name}:{i}: {stripped}")

        assert violations == [], (
            f"Found imports from libs.regime:\n" + "\n".join(violations)
        )


# ------------------------------------------------------------------
# 5. L2 features
# ------------------------------------------------------------------

class TestL2Features:

    def test_nan_on_none_input(self):
        result = compute_l2_features(None, None)
        assert math.isnan(result.bid_ask_imbalance)
        assert math.isnan(result.spread_bps)

    def test_valid_orderbook(self):
        bids = np.array([
            [100.0, 10.0],
            [99.5, 20.0],
            [99.0, 30.0],
            [98.5, 15.0],
            [98.0, 25.0],
        ])
        asks = np.array([
            [100.5, 8.0],
            [101.0, 15.0],
            [101.5, 25.0],
            [102.0, 10.0],
            [102.5, 20.0],
        ])
        result = compute_l2_features(bids, asks)
        assert not math.isnan(result.bid_ask_imbalance)
        assert -1.0 <= result.bid_ask_imbalance <= 1.0
        assert result.spread_bps > 0
        assert result.depth_ratio > 0

    def test_to_dict(self):
        result = compute_l2_features(None, None)
        d = result.to_dict()
        assert "bid_ask_imbalance" in d
        assert "spread_bps" in d


# ------------------------------------------------------------------
# 6. Contracts
# ------------------------------------------------------------------

class TestContracts:

    def test_regime_feature_output_defaults(self):
        r = RegimeFeatureOutput()
        d = r.to_dict()
        assert d["hmm_n_states"] == 2.0
        assert d["hurst"] == 0.5
        assert d["bid_ask_imbalance"] is None

    def test_regime_feature_output_with_hmm(self):
        r = RegimeFeatureOutput(
            hmm_posteriors=(0.6, 0.3, 0.1),
            hmm_n_states=3,
        )
        d = r.to_dict()
        assert d["hmm_p_state_0"] == 0.6
        assert d["hmm_p_state_1"] == 0.3
        assert d["hmm_p_state_2"] == 0.1
        assert d["hmm_n_states"] == 3.0

    def test_hmm_state_local_frozen(self):
        s = HMMStateLocal(posteriors=(0.5, 0.5), n_states=2, transition_prob=0.8, crisis_prob=0.0)
        with pytest.raises(AttributeError):
            s.n_states = 3  # type: ignore[misc]

    def test_vol_state_local_frozen(self):
        v = VolStateLocal(vol_percentile=75.0, rolling_vol=0.02)
        with pytest.raises(AttributeError):
            v.rolling_vol = 0.05  # type: ignore[misc]
