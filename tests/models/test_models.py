"""Tests for the model-strategy layer: BaseModel, ModelRegistry, MeanReversionModel."""

import pytest
import pandas as pd

from libs.contracts.schemas import FeatureVector, ModelOutput, ParamDef
from libs.models.base import BaseModel, ModelMeta
from libs.models.registry import ModelRegistry
from libs.models.mean_reversion import MeanReversionModel


# ---------------------------------------------------------------------------
# ModelRegistry
# ---------------------------------------------------------------------------

class TestModelRegistry:
    def test_mean_reversion_registered(self):
        assert "MeanReversion" in ModelRegistry.list_all()

    def test_get_returns_class(self):
        cls = ModelRegistry.get("MeanReversion")
        assert cls is MeanReversionModel

    def test_get_unknown_raises(self):
        with pytest.raises(KeyError, match="not found in registry"):
            ModelRegistry.get("NoSuchModel")

    def test_list_all_returns_list(self):
        result = ModelRegistry.list_all()
        assert isinstance(result, list)
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# MeanReversionModel — evaluate()
# ---------------------------------------------------------------------------

class TestMeanReversionEvaluate:
    @pytest.fixture
    def model(self):
        return MeanReversionModel(params={"rsi_oversold": 30, "rsi_overbought": 70})

    def _make_fv(self, rsi, bb_upper, bb_lower, close):
        return FeatureVector(
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1000.0,
            features={
                "RSI": {"value": rsi},
                "BollingerBands": {"upper": bb_upper, "lower": bb_lower},
            },
            bar_data={"close": close, "high": close + 10, "low": close - 10, "volume": 100},
        )

    def test_long_signal(self, model):
        fv = self._make_fv(rsi=20, bb_upper=110, bb_lower=95, close=90)
        output = model.evaluate(fv)
        assert output.direction == 1
        assert output.conviction > 0
        assert output.model_name == "MeanReversion"

    def test_short_signal(self, model):
        fv = self._make_fv(rsi=80, bb_upper=95, bb_lower=80, close=100)
        output = model.evaluate(fv)
        assert output.direction == -1
        assert output.conviction > 0

    def test_flat_signal(self, model):
        fv = self._make_fv(rsi=50, bb_upper=110, bb_lower=90, close=100)
        output = model.evaluate(fv)
        assert output.direction == 0
        assert output.conviction == 0.0

    def test_output_fields(self, model):
        fv = self._make_fv(rsi=50, bb_upper=110, bb_lower=90, close=100)
        output = model.evaluate(fv)
        assert isinstance(output, ModelOutput)
        assert output.asset == "BTCUSDT"
        assert output.timeframe == "1h"
        assert output.timestamp == 1000.0


# ---------------------------------------------------------------------------
# MeanReversionModel — batch_evaluate()
# ---------------------------------------------------------------------------

class TestMeanReversionBatch:
    @pytest.fixture
    def model(self):
        return MeanReversionModel(params={"rsi_oversold": 30, "rsi_overbought": 70})

    def test_batch_directions(self, model):
        df = pd.DataFrame({
            "RSI": [20, 50, 80],
            "BollingerBands_lower": [95, 90, 80],
            "BollingerBands_upper": [105, 110, 95],
            "close": [90, 100, 100],
        })
        result = model.batch_evaluate(df)
        assert list(result) == [1, 0, -1]


# ---------------------------------------------------------------------------
# MeanReversionModel — validate_features
# ---------------------------------------------------------------------------

class TestValidateFeatures:
    def test_all_present(self):
        model = MeanReversionModel(params={})
        missing = model.validate_features({"RSI", "BollingerBands", "MACD"})
        assert missing == []

    def test_missing_indicator(self):
        model = MeanReversionModel(params={})
        missing = model.validate_features({"RSI"})
        assert "BollingerBands" in missing

    def test_defaults_applied(self):
        model = MeanReversionModel(params={})
        assert model.params["rsi_oversold"] == 30
        assert model.params["rsi_overbought"] == 70


# ---------------------------------------------------------------------------
# Pydantic contracts round-trip
# ---------------------------------------------------------------------------

class TestContracts:
    def test_feature_vector_validation(self):
        fv = FeatureVector(
            asset="BTCUSDT", timeframe="1h", timestamp=1.0,
            features={"RSI": 42}, bar_data={"close": 100.0},
        )
        assert fv.asset == "BTCUSDT"

    def test_feature_vector_rejects_bad_input(self):
        with pytest.raises(Exception):
            FeatureVector(asset="X", timeframe="1h", timestamp="not_a_float",
                          features="invalid", bar_data={})

    def test_model_output_conviction_bounds(self):
        with pytest.raises(Exception):
            ModelOutput(
                model_name="X", asset="A", timeframe="1h",
                timestamp=1.0, direction=1, conviction=1.5, metadata={},
            )

    def test_param_def(self):
        p = ParamDef(type="float", default=2.0, low=1.0, high=3.0, step=0.1)
        assert p.default == 2.0
