"""Unit tests for engineered features, registry, and manager."""

import math
from collections import deque
from unittest.mock import patch, MagicMock

import pytest

from libs.features.engineered.base import EngineeredFeature
from libs.features.engineered.registry import EngineeredFeatureRegistry
from libs.features.engineered.features import (
    VolumeAdjustedMomentum,
    ATRNormalizedReturn,
    ResidualMomentum,
    SqueezeIntensity,
    RegimeScore,
    MeanReversionZ,
)
from libs.features.engineered.manager import EngineeredFeatureManager


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestEngineeredFeatureRegistry:
    def test_all_six_features_registered(self):
        names = EngineeredFeatureRegistry.list_all()
        expected = [
            "volume_adjusted_momentum",
            "atr_normalized_return",
            "residual_momentum",
            "squeeze_intensity",
            "regime_score",
            "mean_reversion_z",
        ]
        for name in expected:
            assert name in names

    def test_get_returns_correct_class(self):
        cls = EngineeredFeatureRegistry.get("regime_score")
        assert cls is RegimeScore

    def test_get_unknown_raises(self):
        with pytest.raises(KeyError, match="not found"):
            EngineeredFeatureRegistry.get("nonexistent_feature")


# ---------------------------------------------------------------------------
# VolumeAdjustedMomentum
# ---------------------------------------------------------------------------


class TestVolumeAdjustedMomentum:
    def setup_method(self):
        self.feat = VolumeAdjustedMomentum()
        self.state: dict = {}

    def test_name_and_requirements(self):
        assert self.feat.name == "volume_adjusted_momentum"
        assert "Momentum" in self.feat.required_indicators
        assert "volume" in self.feat.required_bar_fields

    def test_returns_none_until_20_volumes(self):
        for i in range(19):
            result = self.feat.compute(
                {"Momentum": 5.0}, {"volume": 100.0}, self.state
            )
            assert result is None

    def test_returns_value_at_20_volumes(self):
        for i in range(19):
            self.feat.compute({"Momentum": 5.0}, {"volume": 100.0}, self.state)
        # 20th volume
        result = self.feat.compute({"Momentum": 5.0}, {"volume": 100.0}, self.state)
        assert result is not None
        # vol_ratio = 100 / 100 = 1.0, so VAM = 5.0 * 1.0 = 5.0
        assert result == pytest.approx(5.0)

    def test_high_volume_amplifies(self):
        for i in range(20):
            self.feat.compute({"Momentum": 5.0}, {"volume": 100.0}, self.state)
        # Now send a high-volume bar
        result = self.feat.compute({"Momentum": 5.0}, {"volume": 200.0}, self.state)
        # SMA window has 19 x 100 + 1 x 200 = 2100/20 = 105
        # vol_ratio = 200 / 105
        expected = 5.0 * (200.0 / 105.0)
        assert result == pytest.approx(expected)

    def test_missing_momentum_returns_none(self):
        for i in range(20):
            self.feat.compute({"Momentum": 5.0}, {"volume": 100.0}, self.state)
        result = self.feat.compute({}, {"volume": 100.0}, self.state)
        assert result is None

    def test_zero_volume_mean_returns_none(self):
        for i in range(20):
            self.feat.compute({"Momentum": 5.0}, {"volume": 0.0}, self.state)
        result = self.feat.compute({"Momentum": 5.0}, {"volume": 0.0}, self.state)
        assert result is None


# ---------------------------------------------------------------------------
# ATRNormalizedReturn
# ---------------------------------------------------------------------------


class TestATRNormalizedReturn:
    def setup_method(self):
        self.feat = ATRNormalizedReturn()
        self.state: dict = {}

    def test_first_tick_returns_none(self):
        result = self.feat.compute({"ATR": 2.0}, {"close": 100.0}, self.state)
        assert result is None

    def test_second_tick_returns_value(self):
        self.feat.compute({"ATR": 2.0}, {"close": 100.0}, self.state)
        result = self.feat.compute({"ATR": 2.0}, {"close": 104.0}, self.state)
        # (104 - 100) / 2.0 = 2.0
        assert result == pytest.approx(2.0)

    def test_negative_return(self):
        self.feat.compute({"ATR": 5.0}, {"close": 100.0}, self.state)
        result = self.feat.compute({"ATR": 5.0}, {"close": 90.0}, self.state)
        # (90 - 100) / 5.0 = -2.0
        assert result == pytest.approx(-2.0)

    def test_zero_atr_returns_zero(self):
        self.feat.compute({"ATR": 0.0}, {"close": 100.0}, self.state)
        result = self.feat.compute({"ATR": 0.0}, {"close": 105.0}, self.state)
        assert result == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# ResidualMomentum
# ---------------------------------------------------------------------------


class TestResidualMomentum:
    def setup_method(self):
        self.feat = ResidualMomentum()
        self.state: dict = {}

    def test_cold_start_returns_none(self):
        for i in range(49):
            result = self.feat.compute(
                {"Momentum": float(i), "RSI": 50.0 + i * 0.1}, {}, self.state
            )
            assert result is None, f"Should be None at bar {i}"

    def test_returns_value_at_50_bars(self):
        for i in range(49):
            self.feat.compute(
                {"Momentum": float(i), "RSI": 50.0 + i * 0.1}, {}, self.state
            )
        result = self.feat.compute(
            {"Momentum": 50.0, "RSI": 55.0}, {}, self.state
        )
        assert result is not None
        assert isinstance(result, float)

    def test_pure_momentum_with_constant_rsi(self):
        # If RSI is constant at 50 (rsi_norm=0), residual should equal momentum
        for i in range(50):
            result = self.feat.compute(
                {"Momentum": 3.0, "RSI": 50.0}, {}, self.state
            )
        # rsi_norm = 0 for all bars, so beta ~ 0 (indeterminate, but
        # sum_xx = 0, so beta defaults to 0), residual = 3.0 - 0*0 = 3.0
        assert result == pytest.approx(3.0)

    def test_missing_rsi_returns_none(self):
        result = self.feat.compute({"Momentum": 5.0}, {}, self.state)
        assert result is None


# ---------------------------------------------------------------------------
# SqueezeIntensity
# ---------------------------------------------------------------------------


class TestSqueezeIntensity:
    def setup_method(self):
        self.feat = SqueezeIntensity()
        self.state: dict = {}

    def test_squeeze_bb_inside_kc(self):
        # BB: middle=100, upper=102, lower=98 → bw=4
        # KC: middle=100, upper=105, lower=95 → kw=10
        bb = (100.0, 102.0, 98.0)
        kc = (100.0, 105.0, 95.0)
        result = self.feat.compute(
            {"BollingerBands": bb, "KeltnerChannel": kc}, {}, self.state
        )
        # 4 / 10 = 0.4
        assert result == pytest.approx(0.4)
        assert result < 1.0  # squeeze condition

    def test_no_squeeze(self):
        # BB wider than KC
        bb = (100.0, 110.0, 90.0)  # bw = 20
        kc = (100.0, 105.0, 95.0)  # kw = 10
        result = self.feat.compute(
            {"BollingerBands": bb, "KeltnerChannel": kc}, {}, self.state
        )
        assert result == pytest.approx(2.0)
        assert result > 1.0

    def test_zero_kc_width_returns_one(self):
        bb = (100.0, 102.0, 98.0)
        kc = (100.0, 100.0, 100.0)  # kw = 0
        result = self.feat.compute(
            {"BollingerBands": bb, "KeltnerChannel": kc}, {}, self.state
        )
        assert result == pytest.approx(1.0)

    def test_missing_bb_returns_none(self):
        kc = (100.0, 105.0, 95.0)
        result = self.feat.compute(
            {"KeltnerChannel": kc}, {}, self.state
        )
        assert result is None

    def test_missing_kc_returns_none(self):
        bb = (100.0, 102.0, 98.0)
        result = self.feat.compute(
            {"BollingerBands": bb}, {}, self.state
        )
        assert result is None


# ---------------------------------------------------------------------------
# RegimeScore
# ---------------------------------------------------------------------------


class TestRegimeScore:
    def setup_method(self):
        self.feat = RegimeScore()
        self.state: dict = {}

    def test_adx_25_returns_zero(self):
        result = self.feat.compute({"ADX": 25.0}, {}, self.state)
        assert result == pytest.approx(0.0)

    def test_adx_50_positive(self):
        result = self.feat.compute({"ADX": 50.0}, {}, self.state)
        expected = math.tanh((50 - 25) / 10)
        assert result == pytest.approx(expected)
        assert result > 0

    def test_adx_10_negative(self):
        result = self.feat.compute({"ADX": 10.0}, {}, self.state)
        expected = math.tanh((10 - 25) / 10)
        assert result == pytest.approx(expected)
        assert result < 0

    def test_missing_adx_returns_none(self):
        result = self.feat.compute({}, {}, self.state)
        assert result is None

    def test_bounded(self):
        # tanh output is always in (-1, 1)
        high = self.feat.compute({"ADX": 100.0}, {}, self.state)
        low = self.feat.compute({"ADX": 0.0}, {}, self.state)
        assert -1.0 < high < 1.0
        assert -1.0 < low < 1.0


# ---------------------------------------------------------------------------
# MeanReversionZ
# ---------------------------------------------------------------------------


class TestMeanReversionZ:
    def setup_method(self):
        self.feat = MeanReversionZ()
        self.state: dict = {}

    def test_price_above_kama(self):
        result = self.feat.compute(
            {"KAMA_slow": 100.0, "ATR": 5.0}, {"close": 110.0}, self.state
        )
        # (110 - 100) / 5 = 2.0
        assert result == pytest.approx(2.0)

    def test_price_below_kama(self):
        result = self.feat.compute(
            {"KAMA_slow": 100.0, "ATR": 5.0}, {"close": 85.0}, self.state
        )
        # (85 - 100) / 5 = -3.0
        assert result == pytest.approx(-3.0)

    def test_price_at_kama(self):
        result = self.feat.compute(
            {"KAMA_slow": 100.0, "ATR": 5.0}, {"close": 100.0}, self.state
        )
        assert result == pytest.approx(0.0)

    def test_zero_atr_returns_zero(self):
        result = self.feat.compute(
            {"KAMA_slow": 100.0, "ATR": 0.0}, {"close": 110.0}, self.state
        )
        assert result == pytest.approx(0.0)

    def test_missing_kama_returns_none(self):
        result = self.feat.compute(
            {"ATR": 5.0}, {"close": 110.0}, self.state
        )
        assert result is None

    def test_missing_close_returns_none(self):
        result = self.feat.compute(
            {"KAMA_slow": 100.0, "ATR": 5.0}, {}, self.state
        )
        assert result is None


# ---------------------------------------------------------------------------
# State accumulation across multiple ticks
# ---------------------------------------------------------------------------


class TestStateAccumulation:
    def test_atr_normalized_return_tracks_prev_close(self):
        feat = ATRNormalizedReturn()
        state: dict = {}
        closes = [100.0, 102.0, 101.0, 105.0]
        results = []
        for c in closes:
            r = feat.compute({"ATR": 2.0}, {"close": c}, state)
            results.append(r)
        assert results[0] is None
        assert results[1] == pytest.approx(1.0)   # (102-100)/2
        assert results[2] == pytest.approx(-0.5)   # (101-102)/2
        assert results[3] == pytest.approx(2.0)    # (105-101)/2

    def test_volume_adjusted_momentum_rolling_window(self):
        feat = VolumeAdjustedMomentum()
        state: dict = {}
        # Feed 20 bars with volume=100
        for _ in range(20):
            feat.compute({"Momentum": 1.0}, {"volume": 100.0}, state)
        # 21st bar with volume=200 — window still has mostly 100s
        result = feat.compute({"Momentum": 1.0}, {"volume": 200.0}, state)
        assert result is not None
        assert result > 1.0  # amplified by volume


# ---------------------------------------------------------------------------
# EngineeredFeatureManager tests
# ---------------------------------------------------------------------------


class TestEngineeredFeatureManager:
    def _mock_config(self, config_state):
        """Patch ConfigManager to return a controlled config state."""
        mock_mgr = MagicMock()
        mock_mgr.get.side_effect = lambda key, default=None: config_state.get(key, default)
        mock_mgr.register_file = MagicMock()
        return mock_mgr

    @patch("libs.features.engineered.manager.ConfigManager")
    def test_loads_features_from_config(self, MockConfigManager):
        config_state = {
            "engineered_features": {
                "assets": {
                    "default": {
                        "timeframes": {
                            "default": {
                                "regime_score": {"enabled": True},
                                "squeeze_intensity": {"enabled": True},
                            }
                        }
                    }
                }
            }
        }
        MockConfigManager.return_value = self._mock_config(config_state)

        mgr = EngineeredFeatureManager("BTCUSDT", "1h")
        assert len(mgr._features) == 2
        names = {f.name for f in mgr._features}
        assert "regime_score" in names
        assert "squeeze_intensity" in names

    @patch("libs.features.engineered.manager.ConfigManager")
    def test_disabled_feature_skipped(self, MockConfigManager):
        config_state = {
            "engineered_features": {
                "assets": {
                    "default": {
                        "timeframes": {
                            "default": {
                                "regime_score": {"enabled": True},
                                "squeeze_intensity": {"enabled": False},
                            }
                        }
                    }
                }
            }
        }
        MockConfigManager.return_value = self._mock_config(config_state)

        mgr = EngineeredFeatureManager("BTCUSDT", "1h")
        assert len(mgr._features) == 1
        assert mgr._features[0].name == "regime_score"

    @patch("libs.features.engineered.manager.ConfigManager")
    def test_empty_config_no_features(self, MockConfigManager):
        config_state = {}
        MockConfigManager.return_value = self._mock_config(config_state)

        mgr = EngineeredFeatureManager("BTCUSDT", "1h")
        assert len(mgr._features) == 0

    @patch("libs.features.engineered.manager.ConfigManager")
    def test_compute_returns_eng_prefixed_keys(self, MockConfigManager):
        config_state = {
            "engineered_features": {
                "assets": {
                    "default": {
                        "timeframes": {
                            "default": {
                                "regime_score": {"enabled": True},
                            }
                        }
                    }
                }
            }
        }
        MockConfigManager.return_value = self._mock_config(config_state)

        mgr = EngineeredFeatureManager("BTCUSDT", "1h")
        result = mgr.compute({"ADX": 30.0}, {})
        assert "eng_regime_score" in result
        assert result["eng_regime_score"] == pytest.approx(math.tanh(5.0 / 10))

    @patch("libs.features.engineered.manager.ConfigManager")
    def test_compute_omits_none_values(self, MockConfigManager):
        config_state = {
            "engineered_features": {
                "assets": {
                    "default": {
                        "timeframes": {
                            "default": {
                                "atr_normalized_return": {"enabled": True},
                            }
                        }
                    }
                }
            }
        }
        MockConfigManager.return_value = self._mock_config(config_state)

        mgr = EngineeredFeatureManager("BTCUSDT", "1h")
        # First call — no prev_close yet, returns None → omitted
        result = mgr.compute({"ATR": 2.0}, {"close": 100.0})
        assert "eng_atr_normalized_return" not in result

    @patch("libs.features.engineered.manager.ConfigManager")
    def test_validate_inputs_catches_missing(self, MockConfigManager):
        config_state = {
            "engineered_features": {
                "assets": {
                    "default": {
                        "timeframes": {
                            "default": {
                                "volume_adjusted_momentum": {"enabled": True},
                                "regime_score": {"enabled": True},
                            }
                        }
                    }
                }
            }
        }
        MockConfigManager.return_value = self._mock_config(config_state)

        mgr = EngineeredFeatureManager("BTCUSDT", "1h")

        # Missing Momentum and volume
        missing = mgr.validate_inputs(
            available_indicators={"ADX"},
            available_bar_fields={"close"},
        )
        assert any("Momentum" in m for m in missing)
        assert any("volume" in m for m in missing)

    @patch("libs.features.engineered.manager.ConfigManager")
    def test_validate_inputs_all_present(self, MockConfigManager):
        config_state = {
            "engineered_features": {
                "assets": {
                    "default": {
                        "timeframes": {
                            "default": {
                                "regime_score": {"enabled": True},
                            }
                        }
                    }
                }
            }
        }
        MockConfigManager.return_value = self._mock_config(config_state)

        mgr = EngineeredFeatureManager("BTCUSDT", "1h")
        missing = mgr.validate_inputs(
            available_indicators={"ADX"},
            available_bar_fields=set(),
        )
        assert missing == []

    @patch("libs.features.engineered.manager.ConfigManager")
    def test_asset_specific_config_override(self, MockConfigManager):
        config_state = {
            "engineered_features": {
                "assets": {
                    "BTCUSDT": {
                        "timeframes": {
                            "1h": {
                                "regime_score": {"enabled": True},
                            }
                        }
                    },
                    "default": {
                        "timeframes": {
                            "default": {
                                "squeeze_intensity": {"enabled": True},
                            }
                        }
                    },
                }
            }
        }
        MockConfigManager.return_value = self._mock_config(config_state)

        mgr = EngineeredFeatureManager("BTCUSDT", "1h")
        assert len(mgr._features) == 1
        assert mgr._features[0].name == "regime_score"

    @patch("libs.features.engineered.manager.ConfigManager")
    def test_unknown_feature_in_config_skipped(self, MockConfigManager):
        config_state = {
            "engineered_features": {
                "assets": {
                    "default": {
                        "timeframes": {
                            "default": {
                                "nonexistent_feature": {"enabled": True},
                            }
                        }
                    }
                }
            }
        }
        MockConfigManager.return_value = self._mock_config(config_state)

        # Should not raise — just logs a warning and skips
        mgr = EngineeredFeatureManager("BTCUSDT", "1h")
        assert len(mgr._features) == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_features_dict(self):
        feat = RegimeScore()
        result = feat.compute({}, {}, {})
        assert result is None

    def test_squeeze_intensity_negative_kc_width(self):
        feat = SqueezeIntensity()
        # Negative KC width (pathological, shouldn't happen but handle safely)
        kc = (100.0, 95.0, 105.0)  # upper < lower → width = -10
        bb = (100.0, 102.0, 98.0)
        result = feat.compute(
            {"BollingerBands": bb, "KeltnerChannel": kc}, {}, {}
        )
        # kc_w = 95 - 105 = -10, which is <= 0, so returns 1.0
        assert result == pytest.approx(1.0)

    def test_mean_reversion_z_negative_atr(self):
        feat = MeanReversionZ()
        result = feat.compute(
            {"KAMA_slow": 100.0, "ATR": -1.0}, {"close": 110.0}, {}
        )
        assert result == pytest.approx(0.0)
