"""Tests for MeanReversion v2 — continuous z-score scoring model.

This file replaces the old binary-threshold model tests.
See tests/models/test_mr_v2.py for comprehensive v2 acceptance tests.
"""

import pytest
import pandas as pd
import numpy as np

from libs.contracts.schemas import FeatureVector
from libs.contracts.signal import ScoringOutput
from libs.models.registry import ModelRegistry
from libs.models.scoring_base import ScoringModel
from libs.models.mean_reversion import MeanReversionModel


# ── Helpers ─────────────────────────────────────────────────────────────

DEFAULT_PARAMS = {
    "rsi_scale": 15.0,
    "w_rsi": 0.4,
    "w_bb": 0.4,
    "w_kama": 0.2,
    "adx_center": 25.0,
    "adx_steepness": 5.0,
}


def _make_model(**overrides) -> MeanReversionModel:
    p = {**DEFAULT_PARAMS, **overrides}
    return MeanReversionModel(params=p)


def _make_fv(
    rsi=50, bb_upper=110, bb_lower=90,
    adx=15.0, close=100, high=110, low=90, volume=1000,
    kama=100, atr=2.0,
):
    features: dict = {
        "RSI": rsi,
        "BollingerBands": {"upper": bb_upper, "lower": bb_lower},
        "ADX": {"adx": adx, "plus_di": 20.0, "minus_di": 15.0},
    }
    if kama is not None:
        features["KAMA_fast"] = kama
    if atr is not None:
        features["ATR"] = atr
    return FeatureVector(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1000.0,
        features=features,
        bar_data={"close": close, "high": high, "low": low, "volume": volume},
    )


# ── 1. Registration ────────────────────────────────────────────────────

class TestRegistry:
    def test_registered(self):
        assert "MeanReversion" in ModelRegistry.list_all()

    def test_get_returns_class(self):
        cls = ModelRegistry.get("MeanReversion")
        assert cls is MeanReversionModel


# ── 2. Default params ──────────────────────────────────────────────────

class TestDefaults:
    def test_all_defaults_match_schema(self):
        model = MeanReversionModel(params={})
        for key, pdef in model.meta.hyperparameter_schema.items():
            assert model.params[key] == pdef.default, f"{key} default mismatch"

    def test_six_params_total(self):
        assert len(MeanReversionModel.meta.hyperparameter_schema) == 6

    def test_required_indicators(self):
        assert set(MeanReversionModel.meta.required_indicators) == {
            "RSI", "BollingerBands", "ADX", "KAMA_fast", "ATR",
        }


# ── 3. Long signal (positive edge for low RSI) ────────────────────────

class TestLongSignal:
    def test_positive_edge_on_low_rsi_below_bb(self):
        model = _make_model()
        fv = _make_fv(rsi=20, close=85, bb_lower=90, adx=15.0)
        output = model.evaluate(fv)
        assert output.edge_score > 0, "Low RSI + below BB → positive edge expected"

    def test_edge_increases_with_lower_rsi(self):
        model = _make_model()
        fv1 = _make_fv(rsi=25, close=85, bb_lower=90, adx=15.0)
        o1 = model.evaluate(fv1)
        model2 = _make_model()
        fv2 = _make_fv(rsi=10, close=85, bb_lower=90, adx=15.0)
        o2 = model2.evaluate(fv2)
        assert o2.edge_score > o1.edge_score


# ── 4. Short signal (negative edge for high RSI) ──────────────────────

class TestShortSignal:
    def test_negative_edge_on_high_rsi_above_bb(self):
        model = _make_model()
        fv = _make_fv(rsi=80, close=115, bb_upper=110, adx=15.0)
        output = model.evaluate(fv)
        assert output.edge_score < 0, "High RSI + above BB → negative edge expected"

    def test_edge_magnitude_increases_with_higher_rsi(self):
        model = _make_model()
        fv1 = _make_fv(rsi=75, close=115, bb_upper=110, adx=15.0)
        o1 = model.evaluate(fv1)
        model2 = _make_model()
        fv2 = _make_fv(rsi=90, close=115, bb_upper=110, adx=15.0)
        o2 = model2.evaluate(fv2)
        assert abs(o2.edge_score) > abs(o1.edge_score)


# ── 5. ADX soft scaling ───────────────────────────────────────────────

class TestADXGate:
    def test_adx_low_preserves_edge(self):
        model = _make_model()
        fv = _make_fv(rsi=20, close=85, bb_lower=90, adx=10.0)
        output = model.evaluate(fv)
        assert abs(output.edge_score) > 0.1

    def test_adx_high_attenuates_edge(self):
        model = _make_model()
        fv_low = _make_fv(rsi=20, close=85, bb_lower=90, adx=10.0)
        fv_high = _make_fv(rsi=20, close=85, bb_lower=90, adx=40.0)
        low_out = model.evaluate(fv_low)
        high_out = model.evaluate(fv_high)
        assert abs(low_out.edge_score) > abs(high_out.edge_score)

    def test_adx_at_center_halves_scaling(self):
        model = _make_model(adx_center=25.0)
        fv = _make_fv(rsi=20, close=85, bb_lower=90, adx=25.0)
        output = model.evaluate(fv)
        # At ADX=center, sigmoid ≈ 0.5
        assert output.metadata["adx_scale"] == pytest.approx(0.5, abs=0.01)


# ── 7. Neutral RSI ─────────────────────────────────────────────────────

class TestNeutralRSI:
    def test_near_zero_edge_for_neutral_rsi(self):
        model = _make_model()
        fv = _make_fv(rsi=50, close=100, bb_upper=110, bb_lower=90, adx=15.0)
        output = model.evaluate(fv)
        # RSI=50 → z_rsi=0, close at midband → z_bb≈0
        assert abs(output.edge_score) < 0.5


# ── 8. Metadata contents ──────────────────────────────────────────────

class TestMetadata:
    def test_metadata_has_rsi_and_adx(self):
        model = _make_model()
        fv = _make_fv(rsi=20, close=85, bb_lower=90, adx=15.0)
        output = model.evaluate(fv)
        assert "rsi" in output.metadata
        assert "adx" in output.metadata
        assert output.metadata["rsi"] == 20

    def test_metadata_has_z_components(self):
        model = _make_model()
        fv = _make_fv(rsi=20, close=85, bb_lower=90, adx=15.0)
        output = model.evaluate(fv)
        assert "z_rsi" in output.metadata
        assert "z_bb" in output.metadata
        assert "z_kama" in output.metadata
        assert "raw_edge" in output.metadata
        assert "adx_scale" in output.metadata


# ── 9. Feature validation ─────────────────────────────────────────────

class TestFeatureValidation:
    def test_validate_features_all_present(self):
        model = _make_model()
        available = {"RSI", "BollingerBands", "ADX", "KAMA_fast", "ATR"}
        assert model.validate_features(available) == []

    def test_validate_features_missing(self):
        model = _make_model()
        available = {"RSI"}
        missing = model.validate_features(available)
        assert "BollingerBands" in missing
        assert "ADX" in missing
        assert "KAMA_fast" in missing
        assert "ATR" in missing


# ── 10. Batch evaluation ──────────────────────────────────────────────

class TestBatchEvaluate:
    def test_result_alignment(self):
        model = _make_model()
        rng = np.random.default_rng(42)
        n = 100
        close = 100.0 + np.cumsum(rng.normal(0, 1, n))
        df = pd.DataFrame({
            "close": close,
            "RSI": rng.uniform(10, 90, n),
            "BollingerBands_upper": close + 10,
            "BollingerBands_lower": close - 10,
            "KAMA_fast": close + rng.normal(0, 1, n),
            "ATR": rng.uniform(1, 5, n),
            "ADX_adx": rng.uniform(10, 40, n),
        })
        result = model.batch_evaluate(df)
        assert len(result) == 100

    def test_temporal_guard_rejects_non_monotonic(self):
        model = _make_model()
        n = 100
        idx = pd.date_range("2025-01-01", periods=n, freq="h")
        df = pd.DataFrame({
            "close": np.ones(n) * 100,
            "RSI": np.ones(n) * 50,
            "BollingerBands_upper": np.ones(n) * 110,
            "BollingerBands_lower": np.ones(n) * 90,
            "KAMA_fast": np.ones(n) * 100,
            "ATR": np.ones(n) * 2,
            "ADX_adx": np.ones(n) * 15,
        }, index=idx)
        shuffled = df.iloc[np.random.permutation(len(df))]
        with pytest.raises(ValueError, match="monotonically"):
            model.batch_evaluate(shuffled)

    def test_batch_positive_edge_for_oversold(self):
        model = _make_model()
        n = 50
        df = pd.DataFrame({
            "close": [85.0] * n,
            "RSI": [20.0] * n,
            "BollingerBands_upper": [110.0] * n,
            "BollingerBands_lower": [90.0] * n,
            "KAMA_fast": [100.0] * n,
            "ATR": [2.0] * n,
            "ADX_adx": [15.0] * n,
        })
        result = model.batch_evaluate(df)
        assert (result > 0).all(), "All oversold bars should have positive edge"

    def test_batch_negative_edge_for_overbought(self):
        model = _make_model()
        n = 50
        df = pd.DataFrame({
            "close": [115.0] * n,
            "RSI": [80.0] * n,
            "BollingerBands_upper": [110.0] * n,
            "BollingerBands_lower": [90.0] * n,
            "KAMA_fast": [100.0] * n,
            "ATR": [2.0] * n,
            "ADX_adx": [15.0] * n,
        })
        result = model.batch_evaluate(df)
        assert (result < 0).all(), "All overbought bars should have negative edge"

    def test_batch_adx_high_attenuates(self):
        model = _make_model()
        n = 50
        df_low = pd.DataFrame({
            "close": [85.0] * n,
            "RSI": [20.0] * n,
            "BollingerBands_upper": [110.0] * n,
            "BollingerBands_lower": [90.0] * n,
            "KAMA_fast": [100.0] * n,
            "ATR": [2.0] * n,
            "ADX_adx": [10.0] * n,
        })
        df_high = pd.DataFrame({
            "close": [85.0] * n,
            "RSI": [20.0] * n,
            "BollingerBands_upper": [110.0] * n,
            "BollingerBands_lower": [90.0] * n,
            "KAMA_fast": [100.0] * n,
            "ATR": [2.0] * n,
            "ADX_adx": [40.0] * n,
        })
        result_low = model.batch_evaluate(df_low)
        result_high = model.batch_evaluate(df_high)
        assert result_low.abs().mean() > result_high.abs().mean()

    def test_batch_no_adx_column_uses_neutral(self):
        model = _make_model()
        n = 50
        df = pd.DataFrame({
            "close": [85.0] * n,
            "RSI": [20.0] * n,
            "BollingerBands_upper": [110.0] * n,
            "BollingerBands_lower": [90.0] * n,
            "KAMA_fast": [100.0] * n,
            "ATR": [2.0] * n,
        })
        result = model.batch_evaluate(df)
        # Without ADX column, alpha_ADX = 0.5 (neutral), edge still positive
        assert (result > 0).all()


# ── 12. Model output contract ─────────────────────────────────────────

class TestModelOutput:
    def test_output_type(self):
        model = _make_model()
        fv = _make_fv(rsi=20, close=85, bb_lower=90, adx=15.0)
        output = model.evaluate(fv)
        assert isinstance(output, ScoringOutput)
        assert output.model_name == "MeanReversion"
        assert output.asset == "BTCUSDT"
        assert output.timeframe == "1h"

    def test_conviction_range(self):
        model = _make_model()
        fv = _make_fv(rsi=5, close=85, bb_lower=90, adx=15.0)
        output = model.evaluate(fv)
        assert 0.0 <= output.conviction < 1.0

    def test_neutral_rsi_low_conviction(self):
        model = _make_model()
        fv = _make_fv(rsi=50, close=100, adx=15.0)
        output = model.evaluate(fv)
        # RSI=50 → z_rsi=0, close at midband → small raw_edge → low conviction
        assert output.conviction < 0.5
