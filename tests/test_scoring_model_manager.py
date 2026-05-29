"""Tests for ScoringModelManager."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from libs.contracts.schemas import FeatureVector
from libs.contracts.signal import ScoringOutput
from libs.models.registry import ModelRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_config_get(scoring_node: dict):
    """Return a side_effect function for ConfigManager.get that returns scoring_node."""
    def _get(key, default=None):
        if key == "scoring_models":
            return scoring_node
        if key == "features":
            return {}
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

    def _make_manager(self, scoring_node: dict, asset: str = "BTCUSDT", timeframe: str = "1h"):
        """Construct a ScoringModelManager with mocked config."""
        from apps.strategy_app.scoring_model_manager import ScoringModelManager

        with patch("apps.strategy_app.scoring_model_manager.ConfigManager") as MockCM:
            instance = MockCM.return_value
            instance.get.side_effect = _mock_config_get(scoring_node)
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
