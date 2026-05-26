"""Tests for SqueezeBreakout model."""

import pytest
import pandas as pd
import numpy as np

from libs.contracts.schemas import FeatureVector, ModelOutput
from libs.models.registry import ModelRegistry
from libs.models.squeeze_breakout import SqueezeBreakoutModel


class TestSqueezeBreakoutRegistry:
    def test_registered(self):
        assert "SqueezeBreakout" in ModelRegistry.list_all()

    def test_get_returns_class(self):
        cls = ModelRegistry.get("SqueezeBreakout")
        assert cls is SqueezeBreakoutModel


class TestSqueezeBreakoutEvaluate:
    @pytest.fixture
    def model(self):
        return SqueezeBreakoutModel(params={"ss_threshold": 0})

    def _make_fv(
        self,
        bb_upper=110, bb_lower=90,
        kc_upper=115, kc_lower=85,
        kama=100, linreg=5.0,
        rsi=50, close=105,
    ):
        return FeatureVector(
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1000.0,
            features={
                "BollingerBands": {"upper": bb_upper, "lower": bb_lower},
                "KeltnerChannel": {"upper": kc_upper, "lower": kc_lower},
                "KAMA": kama,
                "LinReg": linreg,
                "RSI": {"value": rsi},
                "ATR": 10.0,
            },
            bar_data={"close": close, "high": close + 5, "low": close - 5, "volume": 100},
        )

    def test_output_type(self, model):
        fv = self._make_fv()
        output = model.evaluate(fv)
        assert isinstance(output, ModelOutput)

    def test_direction_in_valid_range(self, model):
        fv = self._make_fv()
        output = model.evaluate(fv)
        assert output.direction in {-1, 0, 1}

    def test_long_signal_squeeze_off(self, model):
        """Squeeze off (BB not inside KC), positive momentum, close > KAMA → LONG."""
        # Pre-seed squeeze history so model detects a release
        model._squeeze_history.append(True)
        fv = self._make_fv(
            bb_upper=120, bb_lower=80,  # BB outside KC → squeeze off
            kc_upper=115, kc_lower=85,
            kama=100, linreg=5.0, close=105,
        )
        output = model.evaluate(fv)
        assert output.direction == 1
        assert output.conviction > 0

    def test_short_signal_squeeze_off(self, model):
        """Squeeze off, negative momentum, close < KAMA → SHORT."""
        model._squeeze_history.append(True)
        fv = self._make_fv(
            bb_upper=120, bb_lower=80,  # BB outside KC
            kc_upper=115, kc_lower=85,
            kama=100, linreg=-5.0, close=95,
        )
        output = model.evaluate(fv)
        assert output.direction == -1

    def test_flat_when_squeeze_on(self, model):
        """Squeeze on (BB inside KC) → no signal."""
        fv = self._make_fv(
            bb_upper=110, bb_lower=90,  # BB inside KC
            kc_upper=115, kc_lower=85,
        )
        output = model.evaluate(fv)
        assert output.direction == 0

    def test_flat_when_momentum_conflicts_trend(self, model):
        """Squeeze off but momentum positive and close < KAMA → no signal."""
        fv = self._make_fv(
            bb_upper=120, bb_lower=80,
            kc_upper=115, kc_lower=85,
            kama=110, linreg=5.0, close=105,  # close < kama
        )
        output = model.evaluate(fv)
        assert output.direction == 0

    def test_model_name_in_output(self, model):
        fv = self._make_fv()
        output = model.evaluate(fv)
        assert output.model_name == "SqueezeBreakout"


class TestSqueezeBreakoutSignalStrength:
    def test_ss_filter_suppresses_weak_signal(self):
        """With ss_threshold=3, a signal with SS < 3 should be suppressed."""
        model = SqueezeBreakoutModel(params={"ss_threshold": 3})
        fv = FeatureVector(
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1000.0,
            features={
                "BollingerBands": {"upper": 120, "lower": 80},
                "KeltnerChannel": {"upper": 115, "lower": 85},
                "KAMA": 100,
                "LinReg": 5.0,
                "RSI": {"value": 50},
                "ATR": 10.0,
            },
            bar_data={"close": 105, "high": 110, "low": 100, "volume": 100},
        )
        output = model.evaluate(fv)
        # Without prev_kama or avg_volume, SS is limited
        # Should be suppressed because SS < 3
        assert output.direction == 0

    def test_ss_filter_disabled_at_zero(self):
        """With ss_threshold=0, no filtering applied."""
        model = SqueezeBreakoutModel(params={"ss_threshold": 0})
        model._squeeze_history.append(True)
        fv = FeatureVector(
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1000.0,
            features={
                "BollingerBands": {"upper": 120, "lower": 80},
                "KeltnerChannel": {"upper": 115, "lower": 85},
                "KAMA": 100,
                "LinReg": 5.0,
                "RSI": {"value": 50},
                "ATR": 10.0,
            },
            bar_data={"close": 105, "high": 110, "low": 100, "volume": 100},
        )
        output = model.evaluate(fv)
        assert output.direction == 1


class TestSqueezeBreakoutBatch:
    @pytest.fixture
    def model(self):
        return SqueezeBreakoutModel(params={"ss_threshold": 0, "squeeze_lookback": 1})

    def test_batch_output_length(self, model):
        n = 50
        df = pd.DataFrame({
            "BollingerBands_upper": np.linspace(110, 120, n),
            "BollingerBands_lower": np.linspace(90, 80, n),
            "KeltnerChannel_upper": [115] * n,
            "KeltnerChannel_lower": [85] * n,
            "KAMA": [100] * n,
            "LinReg": [5.0] * n,
            "close": [105] * n,
        })
        result = model.batch_evaluate(df)
        assert len(result) == n

    def test_squeeze_detection_in_batch(self, model):
        """When BB is inside KC, squeeze is on → no signal.
        When BB expands outside KC, squeeze release → signal."""
        n = 10
        # First 5 bars: squeeze ON (BB inside KC)
        # Last 5 bars: squeeze OFF (BB outside KC) + positive momentum + uptrend
        bb_upper = [110] * 5 + [120] * 5
        bb_lower = [90] * 5 + [80] * 5
        kc_upper = [115] * 10
        kc_lower = [85] * 10
        kama_vals = [100] * 10
        linreg_vals = [5.0] * 10
        close_vals = [105] * 10

        df = pd.DataFrame({
            "BollingerBands_upper": bb_upper,
            "BollingerBands_lower": bb_lower,
            "KeltnerChannel_upper": kc_upper,
            "KeltnerChannel_lower": kc_lower,
            "KAMA": kama_vals,
            "LinReg": linreg_vals,
            "close": close_vals,
        })
        result = model.batch_evaluate(df)

        # First 5 bars should be 0 (squeeze on)
        assert list(result[:5]) == [0, 0, 0, 0, 0]
        # Bar 5 should be 1 (squeeze release with positive momentum)
        assert result.iloc[5] == 1

    def test_batch_rejects_non_monotonic(self, model):
        df = pd.DataFrame({
            "BollingerBands_upper": [120, 120],
            "BollingerBands_lower": [80, 80],
            "KeltnerChannel_upper": [115, 115],
            "KeltnerChannel_lower": [85, 85],
            "KAMA": [100, 100],
            "LinReg": [5, 5],
            "close": [105, 105],
        }, index=[2, 1])
        with pytest.raises(ValueError, match="monotonically"):
            model.batch_evaluate(df)
