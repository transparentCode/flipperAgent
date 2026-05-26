"""Tests for ModelManager — config-driven model loading and feature validation."""

import pytest

from libs.common.exceptions import ConfigurationError
from libs.contracts.schemas import FeatureVector
from apps.strategy_app.model_manager import ModelManager


class TestModelManager:
    def test_loads_models_for_btcusdt_1h(self):
        mm = ModelManager("BTCUSDT", "1h")
        assert len(mm.models) >= 1
        names = [m.meta.name for m in mm.models]
        assert "MeanReversion" in names

    def test_loads_models_for_default(self):
        mm = ModelManager("UNKNOWNASSET", "99m")
        # Should fall back to default/default
        assert len(mm.models) >= 1

    def test_validate_feature_coverage_pass(self):
        mm = ModelManager("BTCUSDT", "1h")
        # Providing all required indicators
        mm.validate_feature_coverage({"RSI", "BollingerBands", "MACD", "EMA", "ATR", "KAMA", "KeltnerChannel", "LinReg"})

    def test_validate_feature_coverage_fail(self):
        mm = ModelManager("BTCUSDT", "1h")
        with pytest.raises(ConfigurationError, match="requires"):
            mm.validate_feature_coverage({"RSI"})

    def test_evaluate_returns_outputs(self):
        mm = ModelManager("BTCUSDT", "1h")
        fv = FeatureVector(
            asset="BTCUSDT", timeframe="1h", timestamp=1000.0,
            features={
                "RSI": {"value": 20},
                "BollingerBands": {"upper": 110, "lower": 95},
            },
            bar_data={"close": 90, "high": 95, "low": 85, "volume": 100},
        )
        outputs = mm.evaluate(fv)
        assert len(outputs) >= 1
        assert outputs[0].model_name == "MeanReversion"
