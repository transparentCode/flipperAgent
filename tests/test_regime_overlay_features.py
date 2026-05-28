"""Tests for cross-asset regime overlay engineered features."""

import math

import pytest

from libs.features.engineered.cross_sectional import (
    BTCDominanceMomentum,
    Total3MomentumZ,
    RelativeStrengthVsTotal3,
    CrossAssetRegimeState,
    RegimeAlignmentScore,
)
from libs.features.engineered.manager import EngineeredFeatureManager


# ---------------------------------------------------------------------------
# BTCDominanceMomentum
# ---------------------------------------------------------------------------


class TestBTCDominanceMomentum:
    def setup_method(self):
        self.feat = BTCDominanceMomentum(params={"sma_period": 10, "atr_period": 14})
        self.state: dict = {}

    def test_name_and_requirements(self):
        assert self.feat.name == "btc_dominance_momentum"
        assert self.feat.required_indicators == []
        assert self.feat.required_bar_fields == []
        assert self.feat.depends_on_engineered is False

    def test_missing_index_returns_zero(self):
        assert self.feat.compute({}, {}, self.state, index_data=None) == 0.0
        assert self.feat.compute({}, {}, self.state, index_data={}) == 0.0
        assert self.feat.compute({}, {}, self.state, index_data={"TOTAL3": {"close": 1.0}}) == 0.0

    def test_missing_close_returns_zero(self):
        assert self.feat.compute({}, {}, self.state, index_data={"BTC.D": {"high": 55.0}}) == 0.0

    def test_warmup_returns_zero(self):
        """Not enough data for SMA/ATR should return 0.0."""
        for i in range(9):
            result = self.feat.compute(
                {}, {}, self.state,
                index_data={"BTC.D": {"close": 50.0 + i * 0.1, "high": 50.5 + i * 0.1, "low": 49.5 + i * 0.1}},
            )
            assert result == 0.0

    def test_produces_value_after_warmup(self):
        """After enough bars, should produce a non-zero value."""
        for i in range(20):
            result = self.feat.compute(
                {}, {}, self.state,
                index_data={"BTC.D": {"close": 50.0 + i * 0.5, "high": 50.5 + i * 0.5, "low": 49.5 + i * 0.5}},
            )
        # Rising close should produce positive momentum
        assert result > 0.0


# ---------------------------------------------------------------------------
# Total3MomentumZ
# ---------------------------------------------------------------------------


class TestTotal3MomentumZ:
    def setup_method(self):
        self.feat = Total3MomentumZ(params={"sma_period": 5, "z_period": 10, "clip_range": 3.0})
        self.state: dict = {}

    def test_name_and_requirements(self):
        assert self.feat.name == "total3_momentum_z"
        assert self.feat.depends_on_engineered is False

    def test_missing_index_returns_zero(self):
        assert self.feat.compute({}, {}, self.state, index_data=None) == 0.0

    def test_warmup_returns_zero(self):
        for i in range(14):
            result = self.feat.compute(
                {}, {}, self.state,
                index_data={"TOTAL3": {"close": 1000.0 + i}},
            )
            assert result == 0.0

    def test_produces_bounded_value(self):
        for i in range(20):
            result = self.feat.compute(
                {}, {}, self.state,
                index_data={"TOTAL3": {"close": 1000.0 + i * 10}},
            )
        assert result is not None
        assert -3.0 <= result <= 3.0

    def test_clipping(self):
        """Extreme values should be clipped."""
        # Feed stable data then a spike
        for i in range(15):
            self.feat.compute(
                {}, {}, self.state,
                index_data={"TOTAL3": {"close": 1000.0}},
            )
        result = self.feat.compute(
            {}, {}, self.state,
            index_data={"TOTAL3": {"close": 10000.0}},
        )
        # May or may not be clipped depending on std, but should be bounded
        if result is not None:
            assert -3.0 <= result <= 3.0


# ---------------------------------------------------------------------------
# RelativeStrengthVsTotal3
# ---------------------------------------------------------------------------


class TestRelativeStrengthVsTotal3:
    def setup_method(self):
        self.feat = RelativeStrengthVsTotal3(params={"period": 5})
        self.state: dict = {}

    def test_name_and_requirements(self):
        assert self.feat.name == "relative_strength_vs_total3"
        assert self.feat.required_bar_fields == ["close"]
        assert self.feat.depends_on_engineered is False

    def test_missing_index_returns_zero(self):
        assert self.feat.compute({}, {"close": 100.0}, self.state, index_data=None) == 0.0

    def test_warmup_returns_zero(self):
        for i in range(5):
            result = self.feat.compute(
                {}, {"close": 100.0 + i}, self.state,
                index_data={"TOTAL3": {"close": 1000.0 + i * 10}},
            )
            assert result == 0.0

    def test_outperformance_positive(self):
        """Asset rising faster than TOTAL3 → positive RS."""
        for i in range(7):
            result = self.feat.compute(
                {}, {"close": 100.0 + i * 5.0}, self.state,
                index_data={"TOTAL3": {"close": 1000.0 + i * 1.0}},
            )
        assert result > 0.0

    def test_underperformance_negative(self):
        """Asset rising slower than TOTAL3 → negative RS."""
        for i in range(7):
            result = self.feat.compute(
                {}, {"close": 100.0 + i * 0.1}, self.state,
                index_data={"TOTAL3": {"close": 1000.0 + i * 50.0}},
            )
        assert result < 0.0


# ---------------------------------------------------------------------------
# CrossAssetRegimeState
# ---------------------------------------------------------------------------


class TestCrossAssetRegimeState:
    def setup_method(self):
        self.feat = CrossAssetRegimeState(params={"btc_d_threshold": 0.5, "t3_threshold": 0.5})
        self.state: dict = {}

    def test_name_and_dependencies(self):
        assert self.feat.name == "cross_asset_regime_state"
        assert self.feat.depends_on_engineered is True

    def test_risk_off(self):
        """BTC.D rising + TOTAL3 falling → RISK_OFF = 0."""
        result = self.feat.compute(
            {"eng_btc_dominance_momentum": 1.0, "eng_altcoin_market_momentum": -1.0},
            {}, self.state,
        )
        assert result == 0

    def test_alt_season(self):
        """BTC.D falling + TOTAL3 rising → ALT_SEASON = 1."""
        result = self.feat.compute(
            {"eng_btc_dominance_momentum": -1.0, "eng_altcoin_market_momentum": 1.0},
            {}, self.state,
        )
        assert result == 1

    def test_rotation(self):
        """Both rising → ROTATION = 2."""
        result = self.feat.compute(
            {"eng_btc_dominance_momentum": 1.0, "eng_altcoin_market_momentum": 1.0},
            {}, self.state,
        )
        assert result == 2

    def test_broad_selloff(self):
        """Both falling → BROAD_SELLOFF = 3."""
        result = self.feat.compute(
            {"eng_btc_dominance_momentum": -1.0, "eng_altcoin_market_momentum": -1.0},
            {}, self.state,
        )
        assert result == 3

    def test_neutral_defaults_to_rotation(self):
        """Values within thresholds → default ROTATION = 2."""
        result = self.feat.compute(
            {"eng_btc_dominance_momentum": 0.1, "eng_altcoin_market_momentum": 0.1},
            {}, self.state,
        )
        assert result == 2

    def test_missing_features_defaults_neutral(self):
        """Missing eng features → 0.0 defaults → within threshold → ROTATION."""
        result = self.feat.compute({}, {}, self.state)
        assert result == 2


# ---------------------------------------------------------------------------
# RegimeAlignmentScore
# ---------------------------------------------------------------------------


class TestRegimeAlignmentScore:
    def setup_method(self):
        self.feat = RegimeAlignmentScore(params={
            "w_btc_d": 0.3, "w_t3": 0.3, "w_breadth": 0.2, "w_rs": 0.2,
        })
        self.state: dict = {}

    def test_name_and_dependencies(self):
        assert self.feat.name == "regime_alignment_score"
        assert self.feat.depends_on_engineered is True

    def test_all_zero_returns_zero(self):
        result = self.feat.compute({}, {}, self.state)
        assert result == pytest.approx(0.0)

    def test_bounded_output(self):
        """Output should always be in [-1, 1]."""
        result = self.feat.compute(
            {
                "eng_btc_dominance_momentum": 10.0,
                "eng_altcoin_market_momentum": 10.0,
                "eng_market_cap_breadth": 1.0,
                "eng_relative_strength_vs_total3": 5.0,
            },
            {}, self.state,
        )
        assert -1.0 <= result <= 1.0

    def test_alt_favorable_positive(self):
        """BTC.D falling + TOTAL3 rising → positive alignment for alt longs."""
        result = self.feat.compute(
            {
                "eng_btc_dominance_momentum": -2.0,  # tanh(-(-2)) = tanh(2) ≈ 0.96
                "eng_altcoin_market_momentum": 2.0,   # tanh(2) ≈ 0.96
                "eng_market_cap_breadth": 0.0,
                "eng_relative_strength_vs_total3": 0.0,
            },
            {}, self.state,
        )
        assert result > 0.0


# ---------------------------------------------------------------------------
# Two-pass compute ordering (integration)
# ---------------------------------------------------------------------------


class TestTwoPassComputeOrdering:
    """Verify EngineeredFeatureManager runs dependent features after independents."""

    def test_dependent_features_can_read_pass1_results(self):
        """CrossAssetRegimeState and RegimeAlignmentScore should read eng_* from pass 1."""
        from unittest.mock import patch, MagicMock

        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key, default=None: {
            "engineered_features": {
                "assets": {
                    "default": {
                        "timeframes": {
                            "default": {
                                "btc_dominance_regime": {"enabled": True},
                                "altcoin_market_momentum": {"enabled": True},
                                "market_cap_breadth": {"enabled": True},
                                "btc_dominance_momentum": {
                                    "enabled": True,
                                    "params": {"sma_period": 3, "atr_period": 3},
                                },
                                "cross_asset_regime_state": {
                                    "enabled": True,
                                    "params": {"btc_d_threshold": 0.5, "t3_threshold": 0.5},
                                },
                                "regime_alignment_score": {
                                    "enabled": True,
                                    "params": {"w_btc_d": 0.3, "w_t3": 0.3, "w_breadth": 0.2, "w_rs": 0.2},
                                },
                            }
                        }
                    }
                }
            },
        }.get(key, default)

        with patch("libs.features.engineered.manager.ConfigManager") as MockCM:
            MockCM.return_value = mock_config

            mgr = EngineeredFeatureManager("ETHUSDT", "1h")

            # Verify dependent features exist
            dep_features = [f for f in mgr._features if f.depends_on_engineered]
            indep_features = [f for f in mgr._features if not f.depends_on_engineered]
            assert len(dep_features) >= 2, "Should have cross_asset_regime_state and regime_alignment_score"
            assert len(indep_features) >= 3, "Should have independent features"

            # Feed enough bars to warm up
            index_data = {
                "BTC.D": {"close": 55.0, "high": 56.0, "low": 54.0},
                "TOTAL2": {"close": 500.0},
                "TOTAL3": {"close": 300.0},
            }
            features: dict = {}
            bar_data = {"close": 100.0}

            for i in range(20):
                idx = {
                    "BTC.D": {"close": 50.0 + i * 0.5, "high": 51.0 + i * 0.5, "low": 49.0 + i * 0.5},
                    "TOTAL2": {"close": 500.0 + i},
                    "TOTAL3": {"close": 300.0 - i * 2},
                }
                result = mgr.compute(features, bar_data, index_data=idx)

            # cross_asset_regime_state should be present and have a valid state
            assert "eng_cross_asset_regime_state" in result
            assert result["eng_cross_asset_regime_state"] in [0, 1, 2, 3]

            # regime_alignment_score should be present and bounded
            assert "eng_regime_alignment_score" in result
            assert -1.0 <= result["eng_regime_alignment_score"] <= 1.0
