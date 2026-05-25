"""Tests for the model-strategy layer: BaseModel, ModelRegistry, concrete models."""

import pytest
import pandas as pd

from libs.contracts.schemas import FeatureVector, ModelOutput, ParamDef
from libs.models.base import BaseModel, ModelMeta
from libs.models.registry import ModelRegistry
from libs.models.mean_reversion import MeanReversionModel
from libs.models.trend_following import TrendFollowingModel
from libs.models.momentum import MomentumModel


# ---------------------------------------------------------------------------
# ModelRegistry
# ---------------------------------------------------------------------------

class TestModelRegistry:
    def test_mean_reversion_registered(self):
        assert "MeanReversion" in ModelRegistry.list_all()

    def test_trend_following_registered(self):
        assert "TrendFollowing" in ModelRegistry.list_all()

    def test_momentum_registered(self):
        assert "Momentum" in ModelRegistry.list_all()

    def test_get_returns_class(self):
        cls = ModelRegistry.get("MeanReversion")
        assert cls is MeanReversionModel

    def test_get_trend_following(self):
        cls = ModelRegistry.get("TrendFollowing")
        assert cls is TrendFollowingModel

    def test_get_momentum(self):
        cls = ModelRegistry.get("Momentum")
        assert cls is MomentumModel

    def test_get_unknown_raises(self):
        with pytest.raises(KeyError, match="not found in registry"):
            ModelRegistry.get("NoSuchModel")

    def test_list_all_returns_list(self):
        result = ModelRegistry.list_all()
        assert isinstance(result, list)
        assert len(result) >= 3


# ---------------------------------------------------------------------------
# Temporal Guard (Follow-up C)
# ---------------------------------------------------------------------------

class TestTemporalGuard:
    @pytest.fixture
    def model(self):
        return MeanReversionModel(params={"holding_period": 1})

    def test_batch_evaluate_rejects_non_monotonic_index(self, model):
        df = pd.DataFrame(
            {"RSI": [20, 50, 80], "BollingerBands_lower": [95, 90, 80],
             "BollingerBands_upper": [105, 110, 95], "close": [90, 100, 100]},
            index=[3, 1, 2],
        )
        with pytest.raises(ValueError, match="monotonically increasing"):
            model.batch_evaluate(df)

    def test_batch_evaluate_passes_monotonic_index(self, model):
        df = pd.DataFrame(
            {"RSI": [20, 50, 80], "BollingerBands_lower": [95, 90, 80],
             "BollingerBands_upper": [105, 110, 95], "close": [90, 100, 100]},
            index=[0, 1, 2],
        )
        result = model.batch_evaluate(df)
        assert len(result) == 3

    def test_batch_evaluate_rejects_mismatched_result_length(self):
        """Subclass returning wrong-length result should raise."""
        class BadModel(BaseModel):
            meta = ModelMeta(name="Bad", required_indicators=[], required_fields=[])

            def evaluate(self, features):
                ...

            def _batch_evaluate_impl(self, feature_df):
                return pd.Series([0])  # wrong length

        bad = BadModel(params={})
        df = pd.DataFrame({"a": [1, 2, 3]})
        with pytest.raises(ValueError, match="result length"):
            bad.batch_evaluate(df)


# ---------------------------------------------------------------------------
# MeanReversionModel — evaluate()
# ---------------------------------------------------------------------------

class TestMeanReversionEvaluate:
    @pytest.fixture
    def model(self):
        return MeanReversionModel(params={"rsi_oversold": 30, "rsi_overbought": 70})

    def _make_fv(self, rsi, bb_upper, bb_lower, close):
        return FeatureVector(
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1000.0,
            features={
                "RSI": {"value": rsi},
                "BollingerBands": {"upper": bb_upper, "lower": bb_lower},
            },
            bar_data={"close": close, "high": close + 10, "low": close - 10, "volume": 100},
        )

    def test_long_signal(self, model):
        fv = self._make_fv(rsi=20, bb_upper=110, bb_lower=95, close=90)
        output = model.evaluate(fv)
        assert output.direction == 1
        assert output.conviction > 0
        assert output.model_name == "MeanReversion"

    def test_short_signal(self, model):
        fv = self._make_fv(rsi=80, bb_upper=95, bb_lower=80, close=100)
        output = model.evaluate(fv)
        assert output.direction == -1
        assert output.conviction > 0

    def test_flat_signal(self, model):
        fv = self._make_fv(rsi=50, bb_upper=110, bb_lower=90, close=100)
        output = model.evaluate(fv)
        assert output.direction == 0
        assert output.conviction == 0.0

    def test_output_fields(self, model):
        fv = self._make_fv(rsi=50, bb_upper=110, bb_lower=90, close=100)
        output = model.evaluate(fv)
        assert isinstance(output, ModelOutput)
        assert output.asset == "BTCUSDT"
        assert output.timeframe == "1h"
        assert output.timestamp == 1000.0

    def test_holding_period_in_metadata(self, model):
        fv = self._make_fv(rsi=50, bb_upper=110, bb_lower=90, close=100)
        output = model.evaluate(fv)
        assert "holding_period" in output.metadata
        assert output.metadata["holding_period"] == model.params["holding_period"]

    def test_bb_entry_std_default_matches_original(self):
        """bb_entry_std=2.0 (default) should produce same signals as original logic."""
        model = MeanReversionModel(params={"bb_entry_std": 2.0})
        fv = self._make_fv(rsi=20, bb_upper=110, bb_lower=90, close=85)
        output = model.evaluate(fv)
        assert output.direction == 1

    def test_bb_entry_std_wider_suppresses_signal(self):
        """bb_entry_std > indicator num_std widens bands, making entry harder."""
        model = MeanReversionModel(params={"bb_entry_std": 3.0})
        # With default bb_entry_std=2.0, close=89 <= bb_lower=90 triggers long.
        # With bb_entry_std=3.0, model_lower = 100 - 1.5 * 10 = 85, so 89 > 85 = no signal.
        fv = self._make_fv(rsi=20, bb_upper=110, bb_lower=90, close=89)
        output = model.evaluate(fv)
        assert output.direction == 0


# ---------------------------------------------------------------------------
# MeanReversionModel — batch_evaluate()
# ---------------------------------------------------------------------------

class TestMeanReversionBatch:
    @pytest.fixture
    def model(self):
        """Use holding_period=1 to disable cooldown for basic direction tests."""
        return MeanReversionModel(params={
            "rsi_oversold": 30, "rsi_overbought": 70, "holding_period": 1,
        })

    def test_batch_directions(self, model):
        df = pd.DataFrame({
            "RSI": [20, 50, 80],
            "BollingerBands_lower": [95, 90, 80],
            "BollingerBands_upper": [105, 110, 95],
            "close": [90, 100, 100],
        })
        result = model.batch_evaluate(df)
        assert list(result) == [1, 0, -1]

    def test_batch_holding_period_cooldown(self):
        """Holding period suppresses direction changes."""
        model = MeanReversionModel(params={
            "rsi_oversold": 30, "rsi_overbought": 70,
            "holding_period": 3,
        })
        df = pd.DataFrame({
            "RSI": [20, 80, 80, 80, 80],
            "BollingerBands_lower": [95, 80, 80, 80, 80],
            "BollingerBands_upper": [105, 95, 95, 95, 95],
            "close": [90, 100, 100, 100, 100],
        })
        result = model.batch_evaluate(df)
        # Bar 0: long signal, cooldown = 2
        # Bar 1: cooldown active, held at 1
        # Bar 2: cooldown active, held at 1
        # Bar 3: cooldown expired, short signal, cooldown = 2
        # Bar 4: cooldown active, held at -1
        assert list(result) == [1, 1, 1, -1, -1]


# ---------------------------------------------------------------------------
# MeanReversionModel — validate_features
# ---------------------------------------------------------------------------

class TestValidateFeatures:
    def test_all_present(self):
        model = MeanReversionModel(params={})
        missing = model.validate_features({"RSI", "BollingerBands", "MACD"})
        assert missing == []

    def test_missing_indicator(self):
        model = MeanReversionModel(params={})
        missing = model.validate_features({"RSI"})
        assert "BollingerBands" in missing

    def test_defaults_applied(self):
        model = MeanReversionModel(params={})
        assert model.params["rsi_oversold"] == 30
        assert model.params["rsi_overbought"] == 70


# ---------------------------------------------------------------------------
# TrendFollowingModel (Follow-up A)
# ---------------------------------------------------------------------------

class TestTrendFollowingEvaluate:
    @pytest.fixture
    def model(self):
        return TrendFollowingModel(params={})

    def _make_fv(self, ema_fast, ema_slow, macd_hist, atr, close=100.0):
        return FeatureVector(
            asset="BTCUSDT", timeframe="1h", timestamp=1000.0,
            features={
                "EMA_fast": ema_fast,
                "EMA_slow": ema_slow,
                "MACD": {"line": 0.5, "signal": 0.3, "histogram": macd_hist},
                "ATR": atr,
            },
            bar_data={"close": close},
        )

    def test_long_signal(self, model):
        fv = self._make_fv(ema_fast=105, ema_slow=100, macd_hist=0.5, atr=5)
        out = model.evaluate(fv)
        assert out.direction == 1
        assert out.conviction > 0

    def test_short_signal(self, model):
        fv = self._make_fv(ema_fast=95, ema_slow=100, macd_hist=-0.5, atr=5)
        out = model.evaluate(fv)
        assert out.direction == -1

    def test_flat_when_macd_disagrees(self, model):
        """With require_macd_confirm=True (default), MACD must agree."""
        fv = self._make_fv(ema_fast=105, ema_slow=100, macd_hist=-0.5, atr=5)
        out = model.evaluate(fv)
        assert out.direction == 0

    def test_long_without_macd_confirm(self):
        model = TrendFollowingModel(params={"require_macd_confirm": False})
        fv = self._make_fv(ema_fast=105, ema_slow=100, macd_hist=-0.5, atr=5)
        out = model.evaluate(fv)
        assert out.direction == 1

    def test_fast_ge_slow_raises(self):
        with pytest.raises(ValueError, match="ema_fast_period must be less"):
            TrendFollowingModel(params={"ema_fast_period": 26, "ema_slow_period": 26})

    def test_validate_features(self):
        model = TrendFollowingModel(params={})
        missing = model.validate_features({"RSI"})
        assert "EMA" in missing
        assert "ATR" in missing


class TestTrendFollowingBatch:
    def test_batch_directions(self):
        model = TrendFollowingModel(params={})
        df = pd.DataFrame({
            "EMA_fast": [105, 95, 100],
            "EMA_slow": [100, 100, 100],
            "MACD_histogram": [0.5, -0.5, 0.0],
            "ATR": [5, 5, 5],
        })
        result = model.batch_evaluate(df)
        assert list(result) == [1, -1, 0]


# ---------------------------------------------------------------------------
# MomentumModel (Follow-up A)
# ---------------------------------------------------------------------------

class TestMomentumEvaluate:
    @pytest.fixture
    def model(self):
        return MomentumModel(params={})

    def _make_fv(self, rsi, macd_hist, macd_line=0.5):
        return FeatureVector(
            asset="BTCUSDT", timeframe="1h", timestamp=1000.0,
            features={
                "RSI": {"value": rsi},
                "MACD": {"line": macd_line, "signal": 0.3, "histogram": macd_hist},
            },
            bar_data={"close": 100.0},
        )

    def test_long_signal(self, model):
        fv = self._make_fv(rsi=60, macd_hist=0.5)
        out = model.evaluate(fv)
        assert out.direction == 1
        assert out.conviction > 0

    def test_short_signal(self, model):
        fv = self._make_fv(rsi=40, macd_hist=-0.5, macd_line=-0.5)
        out = model.evaluate(fv)
        assert out.direction == -1

    def test_flat_in_neutral_zone(self, model):
        fv = self._make_fv(rsi=50, macd_hist=0.5)
        out = model.evaluate(fv)
        assert out.direction == 0

    def test_threshold_constraint_raises(self):
        with pytest.raises(ValueError, match="rsi_short_threshold must be less"):
            MomentumModel(params={"rsi_short_threshold": 60, "rsi_long_threshold": 55})

    def test_histogram_min_abs_filters_noise(self):
        model = MomentumModel(params={"histogram_min_abs": 1.0})
        fv = self._make_fv(rsi=60, macd_hist=0.5)  # abs(0.5) < 1.0
        out = model.evaluate(fv)
        assert out.direction == 0

    def test_validate_features(self):
        model = MomentumModel(params={})
        missing = model.validate_features({"EMA"})
        assert "RSI" in missing
        assert "MACD" in missing


class TestMomentumBatch:
    def test_batch_directions(self):
        model = MomentumModel(params={})
        df = pd.DataFrame({
            "RSI": [60, 40, 50],
            "MACD_histogram": [0.5, -0.5, 0.0],
            "MACD_line": [0.5, -0.5, 0.0],
        })
        result = model.batch_evaluate(df)
        assert list(result) == [1, -1, 0]


# ---------------------------------------------------------------------------
# Pydantic contracts round-trip
# ---------------------------------------------------------------------------

class TestContracts:
    def test_feature_vector_validation(self):
        fv = FeatureVector(
            asset="BTCUSDT", timeframe="1h", timestamp=1.0,
            features={"RSI": 42}, bar_data={"close": 100.0},
        )
        assert fv.asset == "BTCUSDT"

    def test_feature_vector_rejects_bad_input(self):
        with pytest.raises(Exception):
            FeatureVector(asset="X", timeframe="1h", timestamp="not_a_float",
                          features="invalid", bar_data={})

    def test_model_output_conviction_bounds(self):
        with pytest.raises(Exception):
            ModelOutput(
                model_name="X", asset="A", timeframe="1h",
                timestamp=1.0, direction=1, conviction=1.5, metadata={},
            )

    def test_param_def(self):
        p = ParamDef(type="float", default=2.0, low=1.0, high=3.0, step=0.1)
        assert p.default == 2.0
