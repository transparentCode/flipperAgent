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
    @staticmethod
    def _compat_manager(tmp_path, monkeypatch) -> ModelManager:
        ConfigManager.reset_singleton()
        config_dir = tmp_path
        monkeypatch.chdir(config_dir)
        (config_dir / "base.yaml").write_text("{}", encoding="utf-8")
        (config_dir / "features.yaml").write_text(
            """
features:
  assets:
    default:
      timeframes:
        default:
          RSI: {}
          BollingerBands: {}
          ADX: {}
          KAMA_fast: {}
          ATR: {}
""".strip()
            + "\n",
            encoding="utf-8",
        )
        (config_dir / "models.yaml").write_text(
            """
models:
  assets:
    default:
      timeframes:
        default:
          MeanReversion:
            enabled: true
            migration_mode: scoring
            params:
              rsi_scale: 15.0
              w_rsi: 0.4
              w_bb: 0.4
              w_kama: 0.2
              adx_center: 25.0
              adx_steepness: 5.0
""".strip()
            + "\n",
            encoding="utf-8",
        )
        manager = ConfigManager(config_dir=str(config_dir))
        manager.register_file(config_dir / "models.yaml")
        manager.register_file(config_dir / "features.yaml")
        return ModelManager("UNKNOWNASSET", "99m", config_manager=manager)

    def test_live_canonical_pair_loads_no_legacy_models(self):
        mm = ModelManager("BTCUSDT", "1h")
        all_count = (
            len(mm.models)
            + len(mm.adapted_models)
            + len(mm.scoring_models)
            + len(mm.shadow_models)
        )
        assert all_count == 0

    def test_loads_models_for_default(self, tmp_path, monkeypatch):
        mm = self._compat_manager(tmp_path, monkeypatch)
        # Should fall back to default/default compatibility config.
        all_count = len(mm.models) + len(mm.scoring_models)
        assert all_count >= 1

    def test_validate_feature_coverage_pass(self, tmp_path, monkeypatch):
        mm = self._compat_manager(tmp_path, monkeypatch)
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

    def test_validate_feature_coverage_fail(self, tmp_path, monkeypatch):
        mm = self._compat_manager(tmp_path, monkeypatch)
        with pytest.raises(ConfigurationError, match="requires"):
            mm.validate_feature_coverage({"RSI"})

    def test_evaluate_returns_outputs(self, tmp_path, monkeypatch):
        mm = self._compat_manager(tmp_path, monkeypatch)
        fv = FeatureVector(
            asset="UNKNOWNASSET", timeframe="99m", timestamp=1000.0,
            features={
                "RSI": {"value": 20},
                "BollingerBands": {"upper": 110, "lower": 95},
                "KAMA_fast": 100.0,
                "ATR": 2.0,
                "ADX": {"adx": 15.0},
            },
            bar_data={"close": 90, "high": 95, "low": 85, "volume": 100},
        )
        scoring_outputs = mm.evaluate_scoring(fv)
        mr_outputs = [o for o in scoring_outputs if o.model_name == "MeanReversion"]
        assert len(mr_outputs) >= 1
        assert mr_outputs[0].model_name == "MeanReversion"

    def test_runtime_specs_empty_for_live_canonical_pair(self):
        mm = ModelManager("BTCUSDT", "1h")
        assert mm.runtime_specs == {}

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
