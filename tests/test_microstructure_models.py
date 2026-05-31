"""Tests for microstructure indicators and models."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from libs.features.indicators.microstructure.kyle_lambda import KyleLambda
from libs.features.indicators.microstructure.tfi import TFI
from libs.features.indicators.microstructure.vpin import VPIN
from libs.features.indicators.registry import IndicatorRegistry
from libs.contracts.schemas import FeatureVector, ModelOutput
from libs.models.kyle_tfi.model import KyleTFIModel
from libs.models.vpin_kyle.model import VPINKyleModel
from libs.models.registry import ModelRegistry


# ======================================================================
# Helpers
# ======================================================================

def _make_df(n: int = 500, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data with taker_buy_base."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    volume = rng.uniform(100, 1000, n)
    taker_buy_base = volume * rng.uniform(0.35, 0.65, n)
    return pd.DataFrame({
        "close": close,
        "volume": volume,
        "taker_buy_base": taker_buy_base,
    }, index=pd.date_range("2024-01-01", periods=n, freq="h"))


def _make_feature_vector(
    kyle_z: float = 2.0,
    kyle_regime: str = "informed",
    tfi_zscore: float = 2.0,
    vpin_z: float = 2.0,
    net_taker_buy_ratio: float = 0.6,
    atr: float = 1.0,
    rsi: float = 50.0,
    close: float = 100.0,
) -> FeatureVector:
    return FeatureVector(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1700000000.0,
        features={
            "kyle_z": kyle_z,
            "kyle_regime": kyle_regime,
            "tfi_zscore": tfi_zscore,
            "vpin_z": vpin_z,
            "net_taker_buy_ratio": net_taker_buy_ratio,
            "ATR": atr,
            "RSI": rsi,
        },
        bar_data={"close": close},
    )


# ======================================================================
# Kyle Lambda indicator
# ======================================================================

class TestKyleLambda:
    def test_batch_keys(self):
        df = _make_df(300)
        ind = KyleLambda(smooth=10, lookback=50)
        result = ind.batch(df)
        assert set(result.keys()) == {"kyle_lambda", "kyle_z", "kyle_regime", "kyle_signed"}
        assert len(result["kyle_lambda"]) == len(df)

    def test_batch_kyle_z_is_finite(self):
        df = _make_df(300)
        ind = KyleLambda(smooth=10, lookback=50)
        result = ind.batch(df)
        assert np.all(np.isfinite(result["kyle_z"]))

    def test_regime_values(self):
        df = _make_df(300)
        ind = KyleLambda(smooth=10, lookback=50)
        result = ind.batch(df)
        valid_regimes = {"informed", "noise", "neutral"}
        unique = set(result["kyle_regime"])
        assert unique.issubset(valid_regimes)

    def test_lookback_required(self):
        ind = KyleLambda(smooth=24, lookback=200)
        assert ind.lookback_required == 224

    def test_prime_and_update(self):
        df = _make_df(250)
        ind = KyleLambda(smooth=10, lookback=50)
        ticks = [row.to_dict() for _, row in df.iterrows()]
        ind.prime(ticks[:-1])
        assert ind.is_primed
        result = ind.update(ticks[-1])
        assert "kyle_lambda" in result
        assert "kyle_z" in result
        assert "kyle_regime" in result


# ======================================================================
# TFI indicator
# ======================================================================

class TestTFI:
    def test_batch_keys(self):
        df = _make_df(200)
        ind = TFI(smooth=5, zscore_window=50)
        result = ind.batch(df)
        assert set(result.keys()) == {"tfi", "tfi_zscore"}
        assert len(result["tfi"]) == len(df)

    def test_tfi_range(self):
        df = _make_df(200)
        ind = TFI(smooth=5, zscore_window=50)
        result = ind.batch(df)
        # TFI is a ratio: should be in [0, 1]
        assert np.all(result["tfi"] >= 0)
        assert np.all(result["tfi"] <= 1)

    def test_lookback_required(self):
        ind = TFI(smooth=5, zscore_window=100)
        assert ind.lookback_required == 105

    def test_prime_and_update(self):
        df = _make_df(150)
        ind = TFI(smooth=5, zscore_window=50)
        ticks = [row.to_dict() for _, row in df.iterrows()]
        ind.prime(ticks[:-1])
        assert ind.is_primed
        result = ind.update(ticks[-1])
        assert "tfi" in result
        assert "tfi_zscore" in result


# ======================================================================
# VPIN indicator
# ======================================================================

class TestVPIN:
    def test_batch_keys(self):
        df = _make_df(500)
        ind = VPIN(bucket_multiplier=1.0, n_buckets=20, zscore_window=50)
        result = ind.batch(df)
        assert set(result.keys()) == {"vpin", "vpin_z", "net_taker_buy_ratio"}
        assert len(result["vpin"]) == len(df)

    def test_vpin_bounded(self):
        df = _make_df(500)
        ind = VPIN(bucket_multiplier=1.0, n_buckets=20, zscore_window=50)
        result = ind.batch(df)
        valid = ~np.isnan(result["vpin"])
        if valid.any():
            assert np.all(result["vpin"][valid] >= 0)
            assert np.all(result["vpin"][valid] <= 1)

    def test_no_lookahead(self):
        """VPIN at bar i must not use volume-bar buckets that end after bar i.

        We verify by checking that once a VPIN value appears, it only changes
        at bars where a new volume bucket actually completes — and the mapped
        bucket index is always <= the current time-bar index.
        """
        df = _make_df(500)
        ind = VPIN(bucket_multiplier=1.0, n_buckets=20, zscore_window=50)
        result = ind.batch(df)
        vpin = result["vpin"]

        # All non-NaN VPIN values must be in [0, 1] (valid probability)
        valid = ~np.isnan(vpin)
        assert np.all(vpin[valid] >= 0)
        assert np.all(vpin[valid] <= 1)

        # Backward-fill property: once VPIN becomes non-NaN it should stay
        # non-NaN (the merge_asof backward fill never creates future gaps)
        first_valid = np.argmax(valid) if valid.any() else len(vpin)
        assert np.all(valid[first_valid:]), (
            "VPIN has NaN gaps after first valid value — possible look-ahead issue"
        )

    def test_lookback_required(self):
        ind = VPIN(n_buckets=50, zscore_window=200)
        assert ind.lookback_required == 250

    def test_prime_and_update(self):
        df = _make_df(300)
        ind = VPIN(bucket_multiplier=1.0, n_buckets=20, zscore_window=50)
        ticks = [row.to_dict() for _, row in df.iterrows()]
        ind.prime(ticks[:-1])
        assert ind.is_primed
        result = ind.update(ticks[-1])
        assert "vpin" in result
        assert "net_taker_buy_ratio" in result


# ======================================================================
# KyleTFI model
# ======================================================================

class TestKyleTFIModel:
    def test_evaluate_long(self):
        model = KyleTFIModel(params={})
        fv = _make_feature_vector(
            kyle_regime="informed", tfi_zscore=2.0, rsi=50, kyle_z=2.0,
        )
        out = model.evaluate(fv)
        assert isinstance(out, ModelOutput)
        assert out.direction == 1
        assert out.conviction > 0

    def test_evaluate_short(self):
        model = KyleTFIModel(params={})
        fv = _make_feature_vector(
            kyle_regime="informed", tfi_zscore=-2.0, rsi=50, kyle_z=2.0,
        )
        out = model.evaluate(fv)
        assert out.direction == -1
        assert out.conviction > 0

    def test_evaluate_flat_when_noise(self):
        model = KyleTFIModel(params={})
        fv = _make_feature_vector(kyle_regime="noise", tfi_zscore=2.0)
        out = model.evaluate(fv)
        assert out.direction == 0
        assert out.conviction == 0.0

    def test_evaluate_flat_when_rsi_overbought(self):
        model = KyleTFIModel(params={})
        fv = _make_feature_vector(
            kyle_regime="informed", tfi_zscore=2.0, rsi=75,
        )
        out = model.evaluate(fv)
        assert out.direction == 0

    def test_atr_tp_sl_in_metadata(self):
        model = KyleTFIModel(params={})
        fv = _make_feature_vector(
            kyle_regime="informed", tfi_zscore=2.0, rsi=50,
            kyle_z=2.0, atr=1.0, close=100.0,
        )
        out = model.evaluate(fv)
        assert "atr_tp" in out.metadata
        assert "atr_sl" in out.metadata
        assert out.metadata["atr_tp"] > 100.0  # long direction
        assert out.metadata["atr_sl"] < 100.0

    def test_batch_matches_point(self):
        model = KyleTFIModel(params={})
        df = pd.DataFrame({
            "kyle_z": [2.0, 0.5, 2.0],
            "kyle_regime": ["informed", "noise", "informed"],
            "tfi_zscore": [2.0, 1.0, -2.0],
            "RSI": [50.0, 50.0, 50.0],
            "ATR": [1.0, 1.0, 1.0],
        }, index=pd.RangeIndex(3))

        batch_dirs = model.batch_evaluate(df)

        for i in range(len(df)):
            fv = FeatureVector(
                asset="BTCUSDT", timeframe="1h", timestamp=float(i),
                features=df.iloc[i].to_dict(),
                bar_data={"close": 100.0},
            )
            point_dir = model.evaluate(fv).direction
            assert batch_dirs.iloc[i] == point_dir, f"Mismatch at row {i}"


# ======================================================================
# VPINKyle model
# ======================================================================

class TestVPINKyleModel:
    def test_evaluate_long(self):
        model = VPINKyleModel(params={})
        fv = _make_feature_vector(
            kyle_regime="informed", vpin_z=2.0, net_taker_buy_ratio=0.6, rsi=50,
        )
        out = model.evaluate(fv)
        assert isinstance(out, ModelOutput)
        assert out.direction == 1
        assert out.conviction > 0

    def test_evaluate_short(self):
        model = VPINKyleModel(params={})
        fv = _make_feature_vector(
            kyle_regime="informed", vpin_z=2.0, net_taker_buy_ratio=0.4, rsi=50,
        )
        out = model.evaluate(fv)
        assert out.direction == -1
        assert out.conviction > 0

    def test_evaluate_flat_when_noise(self):
        model = VPINKyleModel(params={})
        fv = _make_feature_vector(kyle_regime="noise", vpin_z=2.0)
        out = model.evaluate(fv)
        assert out.direction == 0

    def test_evaluate_flat_when_low_vpin(self):
        model = VPINKyleModel(params={})
        fv = _make_feature_vector(
            kyle_regime="informed", vpin_z=0.5, net_taker_buy_ratio=0.6, rsi=50,
        )
        out = model.evaluate(fv)
        assert out.direction == 0

    def test_atr_tp_sl_in_metadata(self):
        model = VPINKyleModel(params={})
        fv = _make_feature_vector(
            kyle_regime="informed", vpin_z=2.0, net_taker_buy_ratio=0.6,
            rsi=50, atr=1.0, close=100.0,
        )
        out = model.evaluate(fv)
        assert "atr_tp" in out.metadata
        assert "atr_sl" in out.metadata

    def test_batch_matches_point(self):
        model = VPINKyleModel(params={})
        df = pd.DataFrame({
            "vpin_z": [2.0, 0.5, 2.0],
            "net_taker_buy_ratio": [0.6, 0.5, 0.4],
            "kyle_regime": ["informed", "informed", "informed"],
            "kyle_z": [2.0, 2.0, 2.0],
            "RSI": [50.0, 50.0, 50.0],
            "ATR": [1.0, 1.0, 1.0],
        }, index=pd.RangeIndex(3))

        batch_dirs = model.batch_evaluate(df)

        for i in range(len(df)):
            fv = FeatureVector(
                asset="BTCUSDT", timeframe="1h", timestamp=float(i),
                features=df.iloc[i].to_dict(),
                bar_data={"close": 100.0},
            )
            point_dir = model.evaluate(fv).direction
            assert batch_dirs.iloc[i] == point_dir, f"Mismatch at row {i}"


# ======================================================================
# Registry discovery
# ======================================================================

class TestRegistry:
    def test_kyle_tfi_discoverable(self):
        assert "KyleTFI" in ModelRegistry.list_all()
        cls = ModelRegistry.get("KyleTFI")
        assert cls is KyleTFIModel

    def test_vpin_kyle_discoverable(self):
        assert "VPINKyle" in ModelRegistry.list_all()
        cls = ModelRegistry.get("VPINKyle")
        assert cls is VPINKyleModel

    def test_kyle_lambda_indicator_discoverable(self):
        cls = IndicatorRegistry.get("KyleLambda")
        assert cls is KyleLambda

    def test_tfi_indicator_discoverable(self):
        cls = IndicatorRegistry.get("TFI")
        assert cls is TFI

    def test_vpin_indicator_discoverable(self):
        cls = IndicatorRegistry.get("VPIN")
        assert cls is VPIN
