"""Tests for ModelManager — config-driven model loading and feature validation."""

import pytest

from libs.common.exceptions import ConfigurationError
from libs.contracts.schemas import FeatureVector
from apps.strategy_app.model_manager import ModelManager


class TestModelManager:
    def test_loads_models_for_btcusdt_1h(self):
        mm = ModelManager("BTCUSDT", "1h")
        # MR is now migration_mode=scoring, loaded into scoring_models
        all_names = (
            [m.meta.name for m in mm.models]
            + [m.meta.name for m in mm.scoring_models]
        )
        assert "MeanReversion" in all_names

    def test_loads_models_for_default(self):
        mm = ModelManager("UNKNOWNASSET", "99m")
        # Should fall back to default/default — MR is scoring
        all_count = len(mm.models) + len(mm.scoring_models)
        assert all_count >= 1

    def test_validate_feature_coverage_pass(self):
        mm = ModelManager("BTCUSDT", "1h")
        # Providing all required indicators
        mm.validate_feature_coverage({
            "RSI", "BollingerBands", "MACD", "EMA", "ATR",
            "KAMA_fast", "KAMA_slow", "KeltnerChannel", "LinReg",
            "CCI", "ADX", "ADLine", "MFI", "Momentum",
            "KyleLambda", "TFI", "VPIN",
        })

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
                "KAMA_fast": 100.0,
                "ATR": 2.0,
                "ADX": {"adx": 15.0},
            },
            bar_data={"close": 90, "high": 95, "low": 85, "volume": 100},
        )
        # MR is now scoring mode — test via evaluate_scoring
        scoring_outputs = mm.evaluate_scoring(fv)
        mr_outputs = [o for o in scoring_outputs if o.model_name == "MeanReversion"]
        assert len(mr_outputs) >= 1
        assert mr_outputs[0].model_name == "MeanReversion"
