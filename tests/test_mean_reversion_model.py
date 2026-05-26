"""Tests for simplified MeanReversion model — RSI + tight BB + ADX regime gate."""

import pytest
import pandas as pd
import numpy as np

from libs.contracts.schemas import FeatureVector, ModelOutput
from libs.models.registry import ModelRegistry
from libs.models.mean_reversion import MeanReversionModel


# ── Helpers ─────────────────────────────────────────────────────────────

DEFAULT_PARAMS = {
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "bb_entry_std": 2.0,
    "adx_regime_threshold": 25.0,
    "holding_period": 5,
}


def _make_model(**overrides) -> MeanReversionModel:
    p = {**DEFAULT_PARAMS, **overrides}
    return MeanReversionModel(params=p)


def _make_fv(
    rsi=50, bb_upper=110, bb_lower=90,
    adx=15.0, close=100, high=110, low=90, volume=1000,
):
    return FeatureVector(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1000.0,
        features={
            "RSI": rsi,
            "BollingerBands": {"upper": bb_upper, "lower": bb_lower},
            "ADX": {"adx": adx, "plus_di": 20.0, "minus_di": 15.0},
        },
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

    def test_five_params_total(self):
        assert len(MeanReversionModel.meta.hyperparameter_schema) == 5

    def test_required_indicators(self):
        assert set(MeanReversionModel.meta.required_indicators) == {"RSI", "BollingerBands", "ADX"}


# ── 3. Long signal ─────────────────────────────────────────────────────

class TestLongSignal:
    def test_long_on_rsi_oversold_and_below_bb_lower(self):
        model = _make_model()
        fv = _make_fv(rsi=20, close=85, bb_lower=90, adx=15.0)
        output = model.evaluate(fv)
        assert output.direction == 1
        assert output.metadata["trigger"] == "oversold"

    def test_long_conviction_scales_with_rsi_distance(self):
        model = _make_model()
        fv1 = _make_fv(rsi=25, close=85, bb_lower=90, adx=15.0)
        o1 = model.evaluate(fv1)
        model2 = _make_model()
        fv2 = _make_fv(rsi=10, close=85, bb_lower=90, adx=15.0)
        o2 = model2.evaluate(fv2)
        assert o2.conviction > o1.conviction

    def test_no_long_if_rsi_above_oversold(self):
        model = _make_model()
        fv = _make_fv(rsi=35, close=85, bb_lower=90, adx=15.0)
        output = model.evaluate(fv)
        assert output.direction == 0

    def test_no_long_if_close_above_bb_lower(self):
        model = _make_model()
        fv = _make_fv(rsi=20, close=95, bb_lower=90, adx=15.0)
        output = model.evaluate(fv)
        assert output.direction == 0


# ── 4. Short signal ────────────────────────────────────────────────────

class TestShortSignal:
    def test_short_on_rsi_overbought_and_above_bb_upper(self):
        model = _make_model()
        fv = _make_fv(rsi=80, close=115, bb_upper=110, adx=15.0)
        output = model.evaluate(fv)
        assert output.direction == -1
        assert output.metadata["trigger"] == "overbought"

    def test_short_conviction_scales(self):
        model = _make_model()
        fv1 = _make_fv(rsi=75, close=115, bb_upper=110, adx=15.0)
        o1 = model.evaluate(fv1)
        model2 = _make_model()
        fv2 = _make_fv(rsi=90, close=115, bb_upper=110, adx=15.0)
        o2 = model2.evaluate(fv2)
        assert o2.conviction > o1.conviction

    def test_no_short_if_rsi_below_overbought(self):
        model = _make_model()
        fv = _make_fv(rsi=65, close=115, bb_upper=110, adx=15.0)
        output = model.evaluate(fv)
        assert output.direction == 0


# ── 5. ADX regime gate ─────────────────────────────────────────────────

class TestADXGate:
    def test_adx_gate_blocks_long_when_trending(self):
        model = _make_model()
        fv = _make_fv(rsi=20, close=85, bb_lower=90, adx=30.0)
        output = model.evaluate(fv)
        assert output.direction == 0

    def test_adx_gate_blocks_short_when_trending(self):
        model = _make_model()
        fv = _make_fv(rsi=80, close=115, bb_upper=110, adx=30.0)
        output = model.evaluate(fv)
        assert output.direction == 0

    def test_adx_at_threshold_blocks(self):
        model = _make_model(adx_regime_threshold=25.0)
        fv = _make_fv(rsi=20, close=85, bb_lower=90, adx=25.0)
        output = model.evaluate(fv)
        assert output.direction == 0

    def test_adx_just_below_threshold_passes(self):
        model = _make_model(adx_regime_threshold=25.0)
        fv = _make_fv(rsi=20, close=85, bb_lower=90, adx=24.9)
        output = model.evaluate(fv)
        assert output.direction == 1


# ── 6. BB entry std parameter ──────────────────────────────────────────

class TestBBEntryStd:
    def test_tight_bb_generates_more_signals(self):
        model_tight = _make_model(bb_entry_std=1.0)
        model_wide = _make_model(bb_entry_std=3.0)
        fv = _make_fv(rsi=20, close=88, bb_lower=90, bb_upper=110, adx=15.0)
        tight_out = model_tight.evaluate(fv)
        wide_out = model_wide.evaluate(fv)
        assert tight_out.direction == 1
        assert wide_out.direction == 0


# ── 7. Neutral RSI ─────────────────────────────────────────────────────

class TestNeutralRSI:
    def test_no_signal_in_neutral_rsi(self):
        model = _make_model()
        fv = _make_fv(rsi=50, close=100, adx=15.0)
        output = model.evaluate(fv)
        assert output.direction == 0
        assert output.conviction == 0.0


# ── 8. Metadata contents ──────────────────────────────────────────────

class TestMetadata:
    def test_metadata_has_rsi_and_adx(self):
        model = _make_model()
        fv = _make_fv(rsi=20, close=85, bb_lower=90, adx=15.0)
        output = model.evaluate(fv)
        assert "rsi_value" in output.metadata
        assert "adx" in output.metadata
        assert output.metadata["rsi_value"] == 20

    def test_metadata_has_trigger_on_signal(self):
        model = _make_model()
        fv = _make_fv(rsi=20, close=85, bb_lower=90, adx=15.0)
        output = model.evaluate(fv)
        assert "trigger" in output.metadata


# ── 9. Feature validation ─────────────────────────────────────────────

class TestFeatureValidation:
    def test_validate_features_all_present(self):
        model = _make_model()
        available = {"RSI", "BollingerBands", "ADX"}
        assert model.validate_features(available) == []

    def test_validate_features_missing(self):
        model = _make_model()
        available = {"RSI"}
        missing = model.validate_features(available)
        assert "BollingerBands" in missing
        assert "ADX" in missing


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
            "ADX_adx": np.ones(n) * 15,
        }, index=idx)
        shuffled = df.iloc[np.random.permutation(len(df))]
        with pytest.raises(ValueError, match="monotonically"):
            model.batch_evaluate(shuffled)

    def test_batch_long_signal(self):
        model = _make_model(holding_period=1)
        n = 50
        df = pd.DataFrame({
            "close": [85.0] * n,
            "RSI": [20.0] * n,
            "BollingerBands_upper": [110.0] * n,
            "BollingerBands_lower": [90.0] * n,
            "ADX_adx": [15.0] * n,
        })
        result = model.batch_evaluate(df)
        assert (result == 1).all()

    def test_batch_short_signal(self):
        model = _make_model(holding_period=1)
        n = 50
        df = pd.DataFrame({
            "close": [115.0] * n,
            "RSI": [80.0] * n,
            "BollingerBands_upper": [110.0] * n,
            "BollingerBands_lower": [90.0] * n,
            "ADX_adx": [15.0] * n,
        })
        result = model.batch_evaluate(df)
        assert (result == -1).all()

    def test_batch_adx_gate_blocks(self):
        model = _make_model(holding_period=1)
        n = 50
        df = pd.DataFrame({
            "close": [85.0] * n,
            "RSI": [20.0] * n,
            "BollingerBands_upper": [110.0] * n,
            "BollingerBands_lower": [90.0] * n,
            "ADX_adx": [30.0] * n,
        })
        result = model.batch_evaluate(df)
        assert (result == 0).all()

    def test_batch_no_adx_column_defaults_pass(self):
        model = _make_model(holding_period=1)
        n = 50
        df = pd.DataFrame({
            "close": [85.0] * n,
            "RSI": [20.0] * n,
            "BollingerBands_upper": [110.0] * n,
            "BollingerBands_lower": [90.0] * n,
        })
        result = model.batch_evaluate(df)
        assert (result == 1).all()


# ── 11. Holding period cooldown ────────────────────────────────────────

class TestHoldingPeriod:
    def test_cooldown_1_allows_every_signal(self):
        model = _make_model(holding_period=1)
        n = 10
        df = pd.DataFrame({
            "close": [85.0] * n,
            "RSI": [20.0] * n,
            "BollingerBands_upper": [110.0] * n,
            "BollingerBands_lower": [90.0] * n,
            "ADX_adx": [15.0] * n,
        })
        result = model.batch_evaluate(df)
        assert (result == 1).all()


# ── 12. Model output contract ─────────────────────────────────────────

class TestModelOutput:
    def test_output_type(self):
        model = _make_model()
        fv = _make_fv(rsi=20, close=85, bb_lower=90, adx=15.0)
        output = model.evaluate(fv)
        assert isinstance(output, ModelOutput)
        assert output.model_name == "MeanReversion"
        assert output.asset == "BTCUSDT"
        assert output.timeframe == "1h"

    def test_conviction_range(self):
        model = _make_model()
        fv = _make_fv(rsi=5, close=85, bb_lower=90, adx=15.0)
        output = model.evaluate(fv)
        assert 0.0 < output.conviction <= 1.0

    def test_no_signal_zero_conviction(self):
        model = _make_model()
        fv = _make_fv(rsi=50, close=100, adx=15.0)
        output = model.evaluate(fv)
        assert output.direction == 0
        assert output.conviction == 0.0
