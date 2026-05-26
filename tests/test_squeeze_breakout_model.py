"""Tests for SqueezeBreakout model — v4 signal parity."""

import pytest
import pandas as pd
import numpy as np

from libs.contracts.schemas import FeatureVector, ModelOutput
from libs.models.registry import ModelRegistry
from libs.models.squeeze_breakout import SqueezeBreakoutModel


# ── Default params matching v4 ──────────────────────────────────────────

V4_PARAMS = {
    "kama_fast_period": 5,
    "kama_slow_period": 30,
    "mom_period": 20,
    "squeeze_lookback": 1,
    "ss_threshold": 0,
    "cci_period": 5,
    "adx_period": 14,
    "adx_threshold": 18.0,
    "ad_sma_period": 21,
    "mfi_period": 14,
    "mfi_sma_period": 9,
    "mom_lr_period": 14,
    "mom_lr_mom_period": 10,
}


def _make_model(ss_threshold: int = 0, **overrides) -> SqueezeBreakoutModel:
    p = {**V4_PARAMS, "ss_threshold": ss_threshold, **overrides}
    return SqueezeBreakoutModel(params=p)


def _make_fv(
    bb_upper=110, bb_lower=90,
    kc_upper=115, kc_lower=85,
    kama_fast=105, kama_slow=100,
    cci=50, adx=20.0, plus_di=25.0, minus_di=15.0,
    ad_val=1000.0, mfi=60.0, momentum=5.0,
    close=105, high=110, low=100, volume=1000,
):
    return FeatureVector(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1000.0,
        features={
            "BollingerBands": {"upper": bb_upper, "lower": bb_lower},
            "KeltnerChannel": {"upper": kc_upper, "lower": kc_lower},
            "KAMA_fast": kama_fast,
            "KAMA_slow": kama_slow,
            "CCI": cci,
            "ADX": {"adx": adx, "plus_di": plus_di, "minus_di": minus_di},
            "ADLine": ad_val,
            "MFI": mfi,
            "Momentum": momentum,
            "ATR": 10.0,
        },
        bar_data={"close": close, "high": high, "low": low, "volume": volume},
    )


def _warm_ttm(model: SqueezeBreakoutModel, n: int = 45, close: float = 100.0):
    """Feed the model enough ticks to warm up TTM delta-linreg internal buffers.
    
    Needs 2 * mom_period ticks: mom_period to fill close/high/low bufs,
    then mom_period more to fill delta buf for linreg.
    """
    for i in range(n):
        fv = _make_fv(
            bb_upper=110, bb_lower=90,  # squeeze ON
            kc_upper=115, kc_lower=85,
            kama_fast=100, kama_slow=100,
            close=close + i * 0.1,
            high=close + i * 0.1 + 2,
            low=close + i * 0.1 - 2,
        )
        model.evaluate(fv)


# ── Registry ────────────────────────────────────────────────────────────

class TestSqueezeBreakoutRegistry:
    def test_registered(self):
        assert "SqueezeBreakout" in ModelRegistry.list_all()

    def test_get_returns_class(self):
        cls = ModelRegistry.get("SqueezeBreakout")
        assert cls is SqueezeBreakoutModel


# ── Squeeze release + KAMA crossover ───────────────────────────────────

class TestSqueezeBreakoutKAMACrossover:
    def test_long_on_squeeze_release_kama_fast_above_slow(self):
        model = _make_model()
        _warm_ttm(model)
        model._squeeze_history.append(True)
        fv = _make_fv(
            bb_upper=120, bb_lower=80,  # squeeze OFF
            kc_upper=115, kc_lower=85,
            kama_fast=110, kama_slow=100,  # fast > slow
            close=105, high=112, low=98,
        )
        output = model.evaluate(fv)
        assert output.direction == 1

    def test_short_on_squeeze_release_kama_fast_below_slow(self):
        model = _make_model()
        _warm_ttm(model)
        model._squeeze_history.append(True)
        fv = _make_fv(
            bb_upper=120, bb_lower=80,
            kc_upper=115, kc_lower=85,
            kama_fast=90, kama_slow=100,  # fast < slow
            close=95, high=102, low=88,
        )
        output = model.evaluate(fv)
        assert output.direction == -1

    def test_flat_when_squeeze_on(self):
        model = _make_model()
        _warm_ttm(model)
        fv = _make_fv(
            bb_upper=110, bb_lower=90,  # BB inside KC → squeeze ON
            kc_upper=115, kc_lower=85,
        )
        output = model.evaluate(fv)
        assert output.direction == 0


# ── TTM momentum polarity ──────────────────────────────────────────────

class TestTTMMomentum:
    def test_no_signal_during_warmup(self):
        """Model should not fire until TTM buffers are warm."""
        model = _make_model()
        model._squeeze_history.append(True)
        fv = _make_fv(
            bb_upper=120, bb_lower=80,
            kc_upper=115, kc_lower=85,
            kama_fast=110, kama_slow=100,
        )
        output = model.evaluate(fv)
        # TTM buffers need mom_period ticks; first tick can't produce lr_mom
        assert output.direction == 0

    def test_warmup_then_signal(self):
        model = _make_model()
        _warm_ttm(model)
        model._squeeze_history.append(True)
        fv = _make_fv(
            bb_upper=120, bb_lower=80,
            kc_upper=115, kc_lower=85,
            kama_fast=110, kama_slow=100,
            close=105, high=112, low=98,
        )
        output = model.evaluate(fv)
        # After warmup with rising prices, lr_mom should be > 0 → long
        assert output.direction == 1


# ── Signal strength voters (individual) ────────────────────────────────

class TestSSVoters:
    def test_cci_rising_adds_vote(self):
        model = _make_model()
        model._prev_cci = 40.0
        ss = model._compute_signal_strength(
            direction=1, cci_val=50.0,
            adx_val=None, plus_di=None, minus_di=None,
            ad_val=None, mfi_val=None, mom_val=None,
        )
        assert ss >= 1

    def test_adx_plus_di_adds_vote(self):
        model = _make_model()
        ss = model._compute_signal_strength(
            direction=1, cci_val=None,
            adx_val=25.0, plus_di=30.0, minus_di=15.0,
            ad_val=None, mfi_val=None, mom_val=None,
        )
        assert ss >= 1

    def test_adx_below_threshold_no_vote(self):
        model = _make_model()
        ss = model._compute_signal_strength(
            direction=1, cci_val=None,
            adx_val=10.0, plus_di=30.0, minus_di=15.0,
            ad_val=None, mfi_val=None, mom_val=None,
        )
        assert ss == 0

    def test_ad_above_sma_adds_vote(self):
        model = _make_model()
        # Fill ad_buf with values below current
        for _ in range(model.params["ad_sma_period"]):
            model._ad_buf.append(500.0)
        ss = model._compute_signal_strength(
            direction=1, cci_val=None,
            adx_val=None, plus_di=None, minus_di=None,
            ad_val=1000.0, mfi_val=None, mom_val=None,
        )
        assert ss >= 1

    def test_mfi_above_sma_adds_vote(self):
        model = _make_model()
        for _ in range(model.params["mfi_sma_period"]):
            model._mfi_buf.append(40.0)
        ss = model._compute_signal_strength(
            direction=1, cci_val=None,
            adx_val=None, plus_di=None, minus_di=None,
            ad_val=None, mfi_val=60.0, mom_val=None,
        )
        assert ss >= 1


# ── SS threshold gating ────────────────────────────────────────────────

class TestSSThresholdGating:
    def test_ss_filter_suppresses_weak_signal(self):
        model = _make_model(ss_threshold=3)
        _warm_ttm(model)
        model._squeeze_history.append(True)
        fv = _make_fv(
            bb_upper=120, bb_lower=80,
            kc_upper=115, kc_lower=85,
            kama_fast=110, kama_slow=100,
            close=105, high=112, low=98,
        )
        output = model.evaluate(fv)
        # SS voters mostly unprimed → score < 3 → suppressed
        assert output.direction == 0

    def test_ss_disabled_at_zero_threshold(self):
        model = _make_model(ss_threshold=0)
        _warm_ttm(model)
        model._squeeze_history.append(True)
        fv = _make_fv(
            bb_upper=120, bb_lower=80,
            kc_upper=115, kc_lower=85,
            kama_fast=110, kama_slow=100,
            close=105, high=112, low=98,
        )
        output = model.evaluate(fv)
        assert output.direction == 1


# ── Batch evaluation ───────────────────────────────────────────────────

class TestSqueezeBreakoutBatch:
    @pytest.fixture
    def model(self):
        return _make_model()

    def test_batch_output_length(self, model):
        n = 50
        df = pd.DataFrame({
            "BollingerBands_upper": np.linspace(110, 120, n),
            "BollingerBands_lower": np.linspace(90, 80, n),
            "KeltnerChannel_upper": [115] * n,
            "KeltnerChannel_lower": [85] * n,
            "KAMA_fast": [105] * n,
            "KAMA_slow": [100] * n,
            "close": [105] * n,
            "high": [110] * n,
            "low": [100] * n,
        })
        result = model.batch_evaluate(df)
        assert len(result) == n

    def test_squeeze_detection_in_batch(self, model):
        n = 30
        # First 10 bars: squeeze ON (BB inside KC)
        # Last 20 bars: squeeze OFF (BB outside KC) + KAMA_fast > KAMA_slow
        bb_upper = [110] * 10 + [120] * 20
        bb_lower = [90] * 10 + [80] * 20
        close_vals = list(np.linspace(100, 110, n))
        high_vals = [c + 3 for c in close_vals]
        low_vals = [c - 3 for c in close_vals]

        df = pd.DataFrame({
            "BollingerBands_upper": bb_upper,
            "BollingerBands_lower": bb_lower,
            "KeltnerChannel_upper": [115] * n,
            "KeltnerChannel_lower": [85] * n,
            "KAMA_fast": [108] * n,
            "KAMA_slow": [100] * n,
            "close": close_vals,
            "high": high_vals,
            "low": low_vals,
        })
        result = model.batch_evaluate(df)

        # First 10 bars: squeeze ON → no signal
        assert all(result[:10] == 0)
        # Bar 10 is squeeze release; TTM needs mom_period warmup so may be 0
        # But some bars after warmup should have signal
        assert result.iloc[10] in {0, 1}

    def test_batch_rejects_non_monotonic(self, model):
        df = pd.DataFrame({
            "BollingerBands_upper": [120, 120],
            "BollingerBands_lower": [80, 80],
            "KeltnerChannel_upper": [115, 115],
            "KeltnerChannel_lower": [85, 85],
            "KAMA_fast": [105, 105],
            "KAMA_slow": [100, 100],
            "close": [105, 105],
            "high": [110, 110],
            "low": [100, 100],
        }, index=[2, 1])
        with pytest.raises(ValueError, match="monotonically"):
            model.batch_evaluate(df)


# ── Output format ──────────────────────────────────────────────────────

class TestSqueezeBreakoutOutput:
    def test_output_type(self):
        model = _make_model()
        fv = _make_fv()
        output = model.evaluate(fv)
        assert isinstance(output, ModelOutput)

    def test_direction_in_valid_range(self):
        model = _make_model()
        fv = _make_fv()
        output = model.evaluate(fv)
        assert output.direction in {-1, 0, 1}

    def test_model_name_in_output(self):
        model = _make_model()
        fv = _make_fv()
        output = model.evaluate(fv)
        assert output.model_name == "SqueezeBreakout"
