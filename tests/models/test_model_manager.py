"""Tests for ModelManager — config-driven model loading and feature validation."""

import pytest

from libs.common.config import ConfigManager
from libs.common.exceptions import ConfigurationError
from libs.contracts.schemas import FeatureVector
from apps.strategy_app.model_manager import ModelManager


@pytest.fixture(autouse=True)
def reset_config_manager_singleton():
    ConfigManager.reset_singleton()
    yield
    ConfigManager.reset_singleton()


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

    def test_available_features_from_config_expands_composite_and_microstructure_fields(self):
        mm = ModelManager("BTCUSDT", "1h")
        available = mm._available_features_from_config()

        assert "MACD_histogram" in available
        assert "MACD_line" in available
        assert "BollingerBands_upper" in available
        assert "KeltnerChannel_upper" in available
        assert "kyle_z" in available
        assert "tfi_zscore" in available
        assert "vpin_z" in available
        assert "ctx_transport" in available
        assert "ctx_transport.publication_lag_ms" in available
        assert "ctx_transport.origin" in available

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

    def test_runtime_spec_defaults_to_tf_and_base_1m(self):
        mm = ModelManager("BTCUSDT", "1h")

        spec = mm.runtime_specs["Momentum"]

        assert spec.model_name == "Momentum"
        assert spec.asset == "BTCUSDT"
        assert spec.config_timeframe == "1h"
        assert spec.decision_timeframe == "1h"
        assert spec.base_timeframe == "1m"
        assert spec.trigger_mode == "on_bar_close"
        assert spec.required_context_profiles == []
        assert spec.warmup_bars >= 0

    def test_runtime_spec_reads_model_runtime_block(self, tmp_path, monkeypatch):
        ConfigManager.reset_singleton()
        config_dir = tmp_path
        monkeypatch.chdir(config_dir)
        (config_dir / "base.yaml").write_text("{}", encoding="utf-8")
        (config_dir / "features.yaml").write_text("features: {}\n", encoding="utf-8")
        (config_dir / "models.yaml").write_text(
            """
models:
  assets:
    BTCUSDT:
      timeframes:
        4h:
          Momentum:
            enabled: true
            runtime:
              decision_timeframe: "4h"
              base_timeframe: "1m"
              trigger_mode: "on_base_bar_close"
              required_context_profiles:
                - "volatility_60m"
              required_fields:
                - "ctx_ltf_volatility_60m.value"
              warmup_bars: 240
              stateful: true
              priority_class: "high"
            params: {}
""".strip()
            + "\n",
            encoding="utf-8",
        )

        manager = ConfigManager(config_dir=str(config_dir))
        manager.register_file(config_dir / "models.yaml")
        manager.register_file(config_dir / "features.yaml")
        mm = ModelManager("BTCUSDT", "4h", config_manager=manager)

        spec = mm.runtime_specs["Momentum"]
        assert spec.decision_timeframe == "4h"
        assert spec.base_timeframe == "1m"
        assert spec.trigger_mode == "on_base_bar_close"
        assert spec.required_context_profiles == ["volatility_60m"]
        assert spec.required_fields == ["ctx_ltf_volatility_60m.value"]
        assert spec.warmup_bars == 240
        assert spec.stateful is True
        assert spec.priority_class == "high"
