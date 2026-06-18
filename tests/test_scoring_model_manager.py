"""Tests for ScoringModelManager."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from libs.common.config import ConfigManager
from libs.contracts.schemas import FeatureVector
from libs.contracts.signal import ScoringOutput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_config_get(
    scoring_node: dict,
    engineered_node: dict | None = None,
    features_node: dict | None = None,
):
    """Return a side_effect function for ConfigManager.get that returns scoring_node."""
    def _get(key, default=None):
        if key == "scoring_models":
            return scoring_node
        if key == "features":
            return features_node or {}
        if key == "engineered_features":
            return engineered_node or {}
        return default
    return _get


def _make_feature_vec(**overrides) -> FeatureVector:
    defaults = dict(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1700000000.0,
        features={},
        bar_data={"close": 100.0},
    )
    defaults.update(overrides)
    return FeatureVector(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestScoringModelManager:
    """Ensures ScoringModelManager loads, validates, and evaluates correctly."""

    def _make_manager(
        self,
        scoring_node: dict,
        asset: str = "BTCUSDT",
        timeframe: str = "1h",
        engineered_node: dict | None = None,
        features_node: dict | None = None,
    ):
        """Construct a ScoringModelManager with mocked config."""
        from apps.strategy_app.scoring_model_manager import ScoringModelManager

        with patch("apps.strategy_app.scoring_model_manager.ConfigManager") as MockCM:
            instance = MockCM.return_value
            instance.get.side_effect = _mock_config_get(scoring_node, engineered_node, features_node)
            instance.register_file = MagicMock()
            mgr = ScoringModelManager(asset, timeframe)
        return mgr

    def test_load_from_default_default(self):
        """Fallback: default/default loads models."""
        node = {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "RegimePullbackScorer": {"enabled": True, "params": {}},
                        }
                    }
                }
            }
        }
        mgr = self._make_manager(node, asset="ETHUSDT", timeframe="4h")
        names = [m.meta.name for m in mgr.models]
        assert "RegimePullbackScorer" in names

    def test_asset_tf_overrides_default(self):
        """Specific asset/tf overrides default."""
        node = {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "RegimePullbackScorer": {"enabled": True, "params": {}},
                        }
                    }
                },
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "RegimePullbackScorer": {"enabled": True, "params": {"btc_dom_weight": 0.0}},
                            "DivergenceEdgeScorer": {"enabled": True, "params": {}},
                        }
                    }
                }
            }
        }
        mgr = self._make_manager(node)
        names = [m.meta.name for m in mgr.models]
        assert "RegimePullbackScorer" in names
        assert "DivergenceEdgeScorer" in names

    def test_disabled_model_skipped(self):
        node = {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "RegimePullbackScorer": {"enabled": False, "params": {}},
                            "DivergenceEdgeScorer": {"enabled": True, "params": {}},
                        }
                    }
                }
            }
        }
        mgr = self._make_manager(node)
        names = [m.meta.name for m in mgr.models]
        assert "RegimePullbackScorer" not in names
        assert "DivergenceEdgeScorer" in names

    def test_unknown_model_skipped(self):
        node = {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "NonExistentScorer999": {"enabled": True, "params": {}},
                        }
                    }
                }
            }
        }
        mgr = self._make_manager(node)
        assert len(mgr.models) == 0

    def test_evaluate_returns_scoring_outputs(self):
        node = {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "RegimePullbackScorer": {"enabled": True, "params": {}},
                        }
                    }
                }
            }
        }
        mgr = self._make_manager(node)
        fv = _make_feature_vec()
        results = mgr.evaluate(fv)
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, ScoringOutput)

    def test_fallback_chain_asset_default_tf(self):
        """asset/default should be used when specific tf not found."""
        node = {
            "assets": {
                "BTCUSDT": {
                    "timeframes": {
                        "default": {
                            "DivergenceEdgeScorer": {"enabled": True, "params": {}},
                        }
                    }
                }
            }
        }
        mgr = self._make_manager(node, asset="BTCUSDT", timeframe="15m")
        names = [m.meta.name for m in mgr.models]
        assert "DivergenceEdgeScorer" in names

    def test_fallback_chain_default_tf(self):
        """default/tf should be used when specific asset not found."""
        node = {
            "assets": {
                "default": {
                    "timeframes": {
                        "4h": {
                            "RegimePullbackScorer": {"enabled": True, "params": {}},
                        }
                    }
                }
            }
        }
        mgr = self._make_manager(node, asset="ADAUSDT", timeframe="4h")
        names = [m.meta.name for m in mgr.models]
        assert "RegimePullbackScorer" in names

    def test_validate_feature_coverage_passes(self):
        node = {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "RegimePullbackScorer": {"enabled": True, "params": {}},
                        }
                    }
                }
            }
        }
        mgr = self._make_manager(node)
        available = {
            "KAMA_slow", "ATR", "ADX", "RSI", "BollingerBands", "KeltnerChannel",
            "eng_regime_score", "eng_mean_reversion_z", "eng_squeeze_intensity",
            "eng_btc_dominance_regime", "eng_market_cap_breadth",
            "eng_cross_asset_regime_state", "eng_regime_alignment_score",
        }
        mgr.validate_feature_coverage(available)  # Should not raise

    def test_validate_feature_coverage_raises(self):
        from libs.common.exceptions import ConfigurationError
        node = {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "RegimePullbackScorer": {"enabled": True, "params": {}},
                        }
                    }
                }
            }
        }
        mgr = self._make_manager(node)
        with pytest.raises(ConfigurationError):
            mgr.validate_feature_coverage({"RSI"})  # Missing many required

    def test_non_scoring_model_in_scoring_config_raises(self):
        from libs.common.exceptions import ConfigurationError

        node = {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "Momentum": {"enabled": True, "params": {}},
                        }
                    }
                }
            }
        }

        with pytest.raises(ConfigurationError, match="must extend ScoringModel"):
            self._make_manager(node)

    def test_validate_feature_coverage_uses_engineered_features_config(self):
        node = {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "RegimePullbackScorer": {"enabled": True, "params": {}},
                        }
                    }
                }
            }
        }
        engineered = {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "regime_score": {"enabled": True},
                            "mean_reversion_z": {"enabled": True},
                            "squeeze_intensity": {"enabled": True},
                            "btc_dominance_regime": {"enabled": True},
                            "market_cap_breadth": {"enabled": True},
                            "cross_asset_regime_state": {"enabled": True},
                            "regime_alignment_score": {"enabled": True},
                        }
                    }
                }
            }
        }
        features = {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "KAMA_slow": {},
                            "ATR": {},
                            "ADX": {},
                            "RSI": {},
                            "BollingerBands": {},
                            "KeltnerChannel": {},
                        }
                    }
                }
            }
        }
        mgr = self._make_manager(node, engineered_node=engineered, features_node=features)
        mgr.validate_feature_coverage()

    def test_available_features_from_config_expands_flattened_indicator_fields(self):
        node = {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "RegimePullbackScorer": {"enabled": True, "params": {}},
                        }
                    }
                }
            }
        }
        features = {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "MACD": {},
                            "BollingerBands": {},
                            "KeltnerChannel": {},
                            "ADX": {},
                        }
                    }
                }
            }
        }
        mgr = self._make_manager(node, features_node=features)
        available = mgr._available_features_from_config()

        assert "MACD_histogram" in available
        assert "MACD_line" in available
        assert "BollingerBands_upper" in available
        assert "KeltnerChannel_upper" in available
        assert "ADX_plus_di" in available


    def test_runtime_spec_defaults_for_scoring_models(self):
        node = {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "RegimePullbackScorer": {"enabled": True, "params": {}},
                        }
                    }
                }
            }
        }
        mgr = self._make_manager(node)

        spec = mgr.runtime_specs["RegimePullbackScorer"]
        assert spec.decision_timeframe == "1h"
        assert spec.base_timeframe == "1m"
        assert spec.trigger_mode == "on_bar_close"
        assert spec.stateful is False

    def test_runtime_spec_reads_scoring_model_runtime_block(self, tmp_path, monkeypatch):
        ConfigManager.reset_singleton()
        config_dir = tmp_path
        monkeypatch.chdir(config_dir)
        (config_dir / "base.yaml").write_text("{}", encoding="utf-8")
        (config_dir / "features.yaml").write_text("features: {}\n", encoding="utf-8")
        (config_dir / "models.yaml").write_text(
            """
scoring_models:
  assets:
    BTCUSDT:
      timeframes:
        1h:
          RegimePullbackScorer:
            enabled: true
            runtime:
              decision_timeframe: "1h"
              base_timeframe: "1m"
              trigger_mode: "every_bar_close"
              required_context_profiles:
                - "breakout_pressure_15m"
              warmup_bars: 120
              priority_class: "low"
            params: {}
""".strip()
            + "\n",
            encoding="utf-8",
        )

        manager = ConfigManager(config_dir=str(config_dir))
        manager.register_file(config_dir / "models.yaml")
        manager.register_file(config_dir / "features.yaml")

        from apps.strategy_app.scoring_model_manager import ScoringModelManager

        mgr = ScoringModelManager("BTCUSDT", "1h", config_manager=manager)
        spec = mgr.runtime_specs["RegimePullbackScorer"]
        assert spec.decision_timeframe == "1h"
        assert spec.base_timeframe == "1m"
        assert spec.trigger_mode == "every_bar_close"
        assert spec.required_context_profiles == ["breakout_pressure_15m"]
        assert spec.warmup_bars == 120
        assert spec.priority_class == "low"
