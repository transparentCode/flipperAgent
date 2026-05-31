"""Tests for ConfigManager.validate_feature_model_alignment()."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from libs.common.config import ConfigManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config_state(features_assets: dict, models_assets: dict) -> dict:
    return {
        "features": {"assets": features_assets},
        "models": {"assets": models_assets},
    }


def _make_mock_cm(state: dict) -> ConfigManager:
    """Build a ConfigManager whose .get() reads from *state* dict."""
    cm = object.__new__(ConfigManager)
    cm._state = state
    cm._lock = ConfigManager._lock
    return cm


# Minimal stub meta so ModelRegistry.get works in tests
class _StubMeta:
    def __init__(self, name: str, required_indicators: list[str]):
        self.name = name
        self.required_indicators = required_indicators


class _StubModel:
    def __init__(self, name: str, required_indicators: list[str]):
        self.meta = _StubMeta(name, required_indicators)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestValidateFeatureModelAlignment:
    """Unit tests for validate_feature_model_alignment()."""

    @patch("libs.models.registry.ModelRegistry.get")
    def test_no_warnings_when_aligned(self, mock_get):
        """All model indicators satisfied → empty warnings."""
        stub = _StubModel("MeanReversion", ["RSI", "BollingerBands"])
        mock_get.return_value = stub

        state = _make_config_state(
            features_assets={
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "RSI": {"period": 14},
                            "BollingerBands": {"period": 20},
                        }
                    }
                },
            },
            models_assets={
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "MeanReversion": {"enabled": True, "params": {}},
                        }
                    }
                },
            },
        )
        cm = _make_mock_cm(state)
        warnings = cm.validate_feature_model_alignment()
        assert warnings == []

    @patch("libs.models.registry.ModelRegistry.get")
    def test_missing_indicator_warning(self, mock_get):
        """Model requires CCI but features.yaml lacks it → warning."""
        stub = _StubModel("SqueezeBreakout", ["RSI", "CCI"])
        mock_get.return_value = stub

        state = _make_config_state(
            features_assets={
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "RSI": {"period": 14},
                        }
                    }
                },
            },
            models_assets={
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "SqueezeBreakout": {"enabled": True, "params": {}},
                        }
                    }
                },
            },
        )
        cm = _make_mock_cm(state)
        warnings = cm.validate_feature_model_alignment()
        assert len(warnings) == 1
        assert "CCI" in warnings[0]
        assert "SqueezeBreakout" in warnings[0]

    @patch("libs.models.registry.ModelRegistry.get")
    def test_feature_without_model_consumer(self, mock_get):
        """Features exist for ETHUSDT/4h but no model uses it → standby warning."""
        stub = _StubModel("MeanReversion", ["RSI"])
        mock_get.return_value = stub

        state = _make_config_state(
            features_assets={
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {"RSI": {"period": 14}},
                    }
                },
                "ETHUSDT": {
                    "timeframes": {
                        "4h": {"RSI": {"period": 14}},
                    }
                },
            },
            models_assets={
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "MeanReversion": {"enabled": True, "params": {}},
                        }
                    }
                },
                # No ETHUSDT models at all
            },
        )
        cm = _make_mock_cm(state)
        warnings = cm.validate_feature_model_alignment()
        assert any("ETHUSDT/4h" in w and "standby" in w for w in warnings)

    @patch("libs.models.registry.ModelRegistry.get")
    def test_disabled_model_ignored(self, mock_get):
        """Disabled models should not trigger missing-indicator warnings."""
        stub = _StubModel("TrendFollowing", ["EMA", "MACD", "ATR"])
        mock_get.return_value = stub

        state = _make_config_state(
            features_assets={
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {"RSI": {"period": 14}},
                    }
                },
            },
            models_assets={
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "TrendFollowing": {"enabled": False, "params": {}},
                        }
                    }
                },
            },
        )
        cm = _make_mock_cm(state)
        warnings = cm.validate_feature_model_alignment()
        # disabled model → no missing indicator warning
        # but features exist with no enabled model → standby warning
        missing_indicator_warnings = [w for w in warnings if "requires" in w]
        assert len(missing_indicator_warnings) == 0

    @patch("libs.models.registry.ModelRegistry.get")
    def test_default_features_fallback(self, mock_get):
        """Model's required indicators satisfied via default/default fallback."""
        stub = _StubModel("MeanReversion", ["RSI", "BollingerBands"])
        mock_get.return_value = stub

        state = _make_config_state(
            features_assets={
                "default": {
                    "timeframes": {
                        "default": {
                            "RSI": {"period": 14},
                            "BollingerBands": {"period": 20},
                        }
                    }
                },
            },
            models_assets={
                "SOLUSDT": {
                    "timeframes": {
                        "1h": {
                            "MeanReversion": {"enabled": True, "params": {}},
                        }
                    }
                },
            },
        )
        cm = _make_mock_cm(state)
        warnings = cm.validate_feature_model_alignment()
        # No missing indicator warnings — defaults cover it
        missing_indicator_warnings = [w for w in warnings if "requires" in w]
        assert len(missing_indicator_warnings) == 0

    @patch("libs.models.registry.ModelRegistry.get")
    def test_type_alias_resolves(self, mock_get):
        """Indicator with type alias (EMA_fast → type: EMA) satisfies 'EMA' requirement."""
        stub = _StubModel("TrendFollowing", ["EMA"])
        mock_get.return_value = stub

        state = _make_config_state(
            features_assets={
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "EMA_fast": {"type": "EMA", "period": 12},
                        }
                    }
                },
            },
            models_assets={
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "TrendFollowing": {"enabled": True, "params": {}},
                        }
                    }
                },
            },
        )
        cm = _make_mock_cm(state)
        warnings = cm.validate_feature_model_alignment()
        missing_indicator_warnings = [w for w in warnings if "requires" in w]
        assert len(missing_indicator_warnings) == 0

    @patch("libs.models.registry.ModelRegistry.get")
    def test_returns_list_of_strings(self, mock_get):
        """Return type is always list[str]."""
        state = _make_config_state(
            features_assets={},
            models_assets={},
        )
        cm = _make_mock_cm(state)
        result = cm.validate_feature_model_alignment()
        assert isinstance(result, list)

    @patch("libs.models.registry.ModelRegistry.get")
    def test_unknown_model_skipped(self, mock_get):
        """Models not found in registry don't crash, just skip."""
        mock_get.side_effect = KeyError("UnknownModel")

        state = _make_config_state(
            features_assets={
                "BTCUSDT": {"timeframes": {"1h": {"RSI": {"period": 14}}}},
            },
            models_assets={
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "UnknownModel": {"enabled": True, "params": {}},
                        }
                    }
                },
            },
        )
        cm = _make_mock_cm(state)
        warnings = cm.validate_feature_model_alignment()
        # No crash, and no missing-indicator warning (model class not found)
        missing_indicator_warnings = [w for w in warnings if "requires" in w]
        assert len(missing_indicator_warnings) == 0
