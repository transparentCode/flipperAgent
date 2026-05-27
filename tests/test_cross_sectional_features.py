"""Unit tests for cross-sectional engineered features."""

import math
from unittest.mock import patch, MagicMock

import pytest

from libs.features.engineered.registry import EngineeredFeatureRegistry
from libs.features.engineered.cross_sectional import (
    BTCDominanceRegime,
    AltcoinMarketMomentum,
    MarketCapBreadth,
    AltcoinBeta,
)
from libs.features.engineered.manager import EngineeredFeatureManager


# ---------------------------------------------------------------------------
# BTCDominanceRegime
# ---------------------------------------------------------------------------


class TestBTCDominanceRegime:
    def setup_method(self):
        self.feat = BTCDominanceRegime()
        self.state: dict = {}

    def test_name_and_requirements(self):
        assert self.feat.name == "btc_dominance_regime"
        assert self.feat.required_indicators == []
        assert self.feat.required_bar_fields == []

    def test_btc_d_at_center_returns_near_zero(self):
        result = self.feat.compute(
            {}, {}, self.state,
            index_data={"BTC.D": {"close": 50.0}},
        )
        assert result == pytest.approx(0.0)

    def test_btc_d_high_returns_positive(self):
        result = self.feat.compute(
            {}, {}, self.state,
            index_data={"BTC.D": {"close": 70.0}},
        )
        expected = math.tanh((70.0 - 50.0) / 10.0)
        assert result == pytest.approx(expected)
        assert result > 0

    def test_btc_d_low_returns_negative(self):
        result = self.feat.compute(
            {}, {}, self.state,
            index_data={"BTC.D": {"close": 30.0}},
        )
        expected = math.tanh((30.0 - 50.0) / 10.0)
        assert result == pytest.approx(expected)
        assert result < 0

    def test_missing_index_returns_zero(self):
        result = self.feat.compute(
            {}, {}, self.state,
            index_data={"TOTAL2": {"close": 100.0}},
        )
        assert result == 0.0

    def test_index_data_none_returns_zero(self):
        result = self.feat.compute({}, {}, self.state, index_data=None)
        assert result == 0.0

    def test_empty_index_data_returns_zero(self):
        result = self.feat.compute({}, {}, self.state, index_data={})
        assert result == 0.0

    def test_missing_close_in_btc_d_returns_zero(self):
        result = self.feat.compute(
            {}, {}, self.state,
            index_data={"BTC.D": {"high": 55.0}},
        )
        assert result == 0.0


# ---------------------------------------------------------------------------
# AltcoinMarketMomentum
# ---------------------------------------------------------------------------


class TestAltcoinMarketMomentum:
    def setup_method(self):
        self.feat = AltcoinMarketMomentum()
        self.state: dict = {}

    def test_name_and_requirements(self):
        assert self.feat.name == "altcoin_market_momentum"
        assert self.feat.required_indicators == []
        assert self.feat.required_bar_fields == []

    def test_warmup_returns_zero(self):
        # Feed < 20 ticks
        for i in range(19):
            result = self.feat.compute(
                {}, {}, self.state,
                index_data={"TOTAL3": {"close": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i}},
            )
            assert result == 0.0, f"Should be 0.0 at tick {i}"

    def test_after_warmup_with_rising_prices(self):
        # Feed 20 ticks with rising closes
        for i in range(20):
            self.feat.compute(
                {}, {}, self.state,
                index_data={"TOTAL3": {"close": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i}},
            )
        # 21st tick with a high value (above SMA)
        result = self.feat.compute(
            {}, {}, self.state,
            index_data={"TOTAL3": {"close": 130.0, "high": 131.0, "low": 129.0}},
        )
        assert result is not None
        assert result > 0  # price above SMA → positive momentum

    def test_missing_index_returns_zero(self):
        result = self.feat.compute(
            {}, {}, self.state,
            index_data={"BTC.D": {"close": 50.0}},
        )
        assert result == 0.0

    def test_index_data_none_returns_zero(self):
        result = self.feat.compute({}, {}, self.state, index_data=None)
        assert result == 0.0

    def test_empty_index_data_returns_zero(self):
        result = self.feat.compute({}, {}, self.state, index_data={})
        assert result == 0.0

    def test_missing_close_returns_zero(self):
        result = self.feat.compute(
            {}, {}, self.state,
            index_data={"TOTAL3": {"high": 101.0, "low": 99.0}},
        )
        assert result == 0.0


# ---------------------------------------------------------------------------
# MarketCapBreadth
# ---------------------------------------------------------------------------


class TestMarketCapBreadth:
    def setup_method(self):
        self.feat = MarketCapBreadth()
        self.state: dict = {}

    def test_name_and_requirements(self):
        assert self.feat.name == "market_cap_breadth"
        assert self.feat.required_indicators == []
        assert self.feat.required_bar_fields == []

    def test_first_tick_returns_zero(self):
        result = self.feat.compute(
            {}, {}, self.state,
            index_data={"TOTAL2": {"close": 1000.0}, "TOTAL3": {"close": 500.0}},
        )
        assert result == 0.0  # no prev_ratio

    def test_increasing_ratio_returns_positive(self):
        # First tick: ratio = 1000/500 = 2.0
        self.feat.compute(
            {}, {}, self.state,
            index_data={"TOTAL2": {"close": 1000.0}, "TOTAL3": {"close": 500.0}},
        )
        # Second tick: ratio = 1200/500 = 2.4, change = (2.4-2.0)/2.0 = 0.2
        result = self.feat.compute(
            {}, {}, self.state,
            index_data={"TOTAL2": {"close": 1200.0}, "TOTAL3": {"close": 500.0}},
        )
        assert result == pytest.approx(0.2)
        assert result > 0

    def test_decreasing_ratio_returns_negative(self):
        self.feat.compute(
            {}, {}, self.state,
            index_data={"TOTAL2": {"close": 1000.0}, "TOTAL3": {"close": 500.0}},
        )
        # ratio = 800/500 = 1.6, change = (1.6-2.0)/2.0 = -0.2
        result = self.feat.compute(
            {}, {}, self.state,
            index_data={"TOTAL2": {"close": 800.0}, "TOTAL3": {"close": 500.0}},
        )
        assert result == pytest.approx(-0.2)
        assert result < 0

    def test_missing_total2_returns_zero(self):
        result = self.feat.compute(
            {}, {}, self.state,
            index_data={"TOTAL3": {"close": 500.0}},
        )
        assert result == 0.0

    def test_missing_total3_returns_zero(self):
        result = self.feat.compute(
            {}, {}, self.state,
            index_data={"TOTAL2": {"close": 1000.0}},
        )
        assert result == 0.0

    def test_index_data_none_returns_zero(self):
        result = self.feat.compute({}, {}, self.state, index_data=None)
        assert result == 0.0

    def test_empty_index_data_returns_zero(self):
        result = self.feat.compute({}, {}, self.state, index_data={})
        assert result == 0.0

    def test_zero_total3_close_returns_zero(self):
        result = self.feat.compute(
            {}, {}, self.state,
            index_data={"TOTAL2": {"close": 1000.0}, "TOTAL3": {"close": 0.0}},
        )
        assert result == 0.0


# ---------------------------------------------------------------------------
# AltcoinBeta
# ---------------------------------------------------------------------------


class TestAltcoinBeta:
    def setup_method(self):
        self.feat = AltcoinBeta()
        self.state: dict = {}

    def test_name_and_requirements(self):
        assert self.feat.name == "altcoin_beta"
        assert self.feat.required_indicators == []
        assert "close" in self.feat.required_bar_fields

    def test_warmup_returns_zero(self):
        # Need 21 ticks to get 20 return pairs (first tick has no prev)
        for i in range(20):
            result = self.feat.compute(
                {}, {"close": 100.0 + i}, self.state,
                index_data={"TOTAL2": {"close": 1000.0 + i * 10}},
            )
            assert result == 0.0, f"Should be 0.0 at tick {i}"

    def test_correlated_returns_beta_near_one(self):
        # Feed 21 ticks with perfectly correlated returns (same %)
        base_asset = 100.0
        base_total2 = 1000.0
        for i in range(22):
            pct = 1.0 + 0.01 * (i % 5 - 2)  # oscillate ±2%
            asset_price = base_asset * pct
            total2_price = base_total2 * pct
            result = self.feat.compute(
                {}, {"close": asset_price}, self.state,
                index_data={"TOTAL2": {"close": total2_price}},
            )
            base_asset = asset_price
            base_total2 = total2_price
        # With identical % moves, beta should be ≈ 1.0
        assert result is not None
        assert result == pytest.approx(1.0, abs=0.1)

    def test_missing_total2_returns_zero(self):
        result = self.feat.compute(
            {}, {"close": 100.0}, self.state,
            index_data={"BTC.D": {"close": 50.0}},
        )
        assert result == 0.0

    def test_index_data_none_returns_zero(self):
        result = self.feat.compute(
            {}, {"close": 100.0}, self.state, index_data=None,
        )
        assert result == 0.0

    def test_empty_index_data_returns_zero(self):
        result = self.feat.compute(
            {}, {"close": 100.0}, self.state, index_data={},
        )
        assert result == 0.0

    def test_missing_asset_close_returns_zero(self):
        result = self.feat.compute(
            {}, {}, self.state,
            index_data={"TOTAL2": {"close": 1000.0}},
        )
        assert result == 0.0


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


class TestCrossSectionalRegistry:
    def test_all_four_registered(self):
        names = EngineeredFeatureRegistry.list_all()
        expected = [
            "btc_dominance_regime",
            "altcoin_market_momentum",
            "market_cap_breadth",
            "altcoin_beta",
        ]
        for name in expected:
            assert name in names, f"'{name}' not found in registry"

    def test_get_returns_correct_classes(self):
        assert EngineeredFeatureRegistry.get("btc_dominance_regime") is BTCDominanceRegime
        assert EngineeredFeatureRegistry.get("altcoin_market_momentum") is AltcoinMarketMomentum
        assert EngineeredFeatureRegistry.get("market_cap_breadth") is MarketCapBreadth
        assert EngineeredFeatureRegistry.get("altcoin_beta") is AltcoinBeta


# ---------------------------------------------------------------------------
# Existing features backward compatibility
# ---------------------------------------------------------------------------


class TestExistingFeaturesCompatibility:
    """Verify Phase 1 features still work with the new index_data parameter."""

    def test_regime_score_with_index_data_none(self):
        from libs.features.engineered.features import RegimeScore
        feat = RegimeScore()
        result = feat.compute({"ADX": 30.0}, {}, {}, index_data=None)
        assert result == pytest.approx(math.tanh(5.0 / 10.0))

    def test_regime_score_without_index_data_kwarg(self):
        from libs.features.engineered.features import RegimeScore
        feat = RegimeScore()
        # Omitting index_data entirely should still work (default=None)
        result = feat.compute({"ADX": 30.0}, {}, {})
        assert result == pytest.approx(math.tanh(5.0 / 10.0))

    def test_squeeze_intensity_with_empty_index_data(self):
        from libs.features.engineered.features import SqueezeIntensity
        feat = SqueezeIntensity()
        bb = (100.0, 102.0, 98.0)
        kc = (100.0, 105.0, 95.0)
        result = feat.compute(
            {"BollingerBands": bb, "KeltnerChannel": kc}, {}, {},
            index_data={},
        )
        assert result == pytest.approx(0.4)

    def test_mean_reversion_z_with_index_data(self):
        from libs.features.engineered.features import MeanReversionZ
        feat = MeanReversionZ()
        result = feat.compute(
            {"KAMA_slow": 100.0, "ATR": 5.0}, {"close": 110.0}, {},
            index_data={"BTC.D": {"close": 50.0}},
        )
        assert result == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Manager integration with index_data
# ---------------------------------------------------------------------------


class TestManagerWithIndexData:
    def _mock_config(self, config_state):
        mock_mgr = MagicMock()
        mock_mgr.get.side_effect = lambda key, default=None: config_state.get(key, default)
        mock_mgr.register_file = MagicMock()
        return mock_mgr

    @patch("libs.features.engineered.manager.ConfigManager")
    def test_manager_passes_index_data(self, MockConfigManager):
        config_state = {
            "engineered_features": {
                "assets": {
                    "default": {
                        "timeframes": {
                            "default": {
                                "btc_dominance_regime": {"enabled": True},
                            }
                        }
                    }
                }
            }
        }
        MockConfigManager.return_value = self._mock_config(config_state)

        mgr = EngineeredFeatureManager("BTCUSDT", "1h")
        result = mgr.compute(
            {}, {},
            index_data={"BTC.D": {"close": 60.0}},
        )
        assert "eng_btc_dominance_regime" in result
        expected = math.tanh((60.0 - 50.0) / 10.0)
        assert result["eng_btc_dominance_regime"] == pytest.approx(expected)

    @patch("libs.features.engineered.manager.ConfigManager")
    def test_manager_without_index_data(self, MockConfigManager):
        config_state = {
            "engineered_features": {
                "assets": {
                    "default": {
                        "timeframes": {
                            "default": {
                                "btc_dominance_regime": {"enabled": True},
                                "regime_score": {"enabled": True},
                            }
                        }
                    }
                }
            }
        }
        MockConfigManager.return_value = self._mock_config(config_state)

        mgr = EngineeredFeatureManager("BTCUSDT", "1h")
        # Without index_data, cross-sectional features return 0.0,
        # and Phase 1 features work normally
        result = mgr.compute({"ADX": 30.0}, {})
        # btc_dominance_regime returns 0.0 (not None), so it's included
        assert "eng_btc_dominance_regime" in result
        assert result["eng_btc_dominance_regime"] == 0.0
        assert "eng_regime_score" in result
        assert result["eng_regime_score"] == pytest.approx(math.tanh(5.0 / 10.0))

    @patch("libs.features.engineered.manager.ConfigManager")
    def test_manager_compute_with_none_index_data(self, MockConfigManager):
        config_state = {
            "engineered_features": {
                "assets": {
                    "default": {
                        "timeframes": {
                            "default": {
                                "btc_dominance_regime": {"enabled": True},
                            }
                        }
                    }
                }
            }
        }
        MockConfigManager.return_value = self._mock_config(config_state)

        mgr = EngineeredFeatureManager("BTCUSDT", "1h")
        result = mgr.compute({}, {}, index_data=None)
        assert "eng_btc_dominance_regime" in result
        assert result["eng_btc_dominance_regime"] == 0.0
