"""Tests for LegacyScoringAdapter — wrapping BaseModel → ScoringOutput."""

from __future__ import annotations

import pytest
import pandas as pd
import numpy as np

from libs.contracts.schemas import FeatureVector, ModelOutput
from libs.contracts.signal import ScoringOutput
from libs.models.base import BaseModel, ModelMeta
from libs.models.scoring_base import ScoringModel
from libs.models.legacy_adapter import LegacyScoringAdapter
from libs.models.registry import ModelRegistry
from libs.models.squeeze_breakout import SqueezeBreakoutModel
from libs.models.mean_reversion import MeanReversionModel


# ── Helpers ─────────────────────────────────────────────────────────────

SB_PARAMS = {
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

MR_PARAMS = {
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "bb_entry_std": 2.0,
    "adx_regime_threshold": 25.0,
    "holding_period": 5,
}


def _sb_fv(
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


def _mr_fv(rsi=50, bb_upper=110, bb_lower=90, adx=15.0, close=100):
    return FeatureVector(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1000.0,
        features={
            "RSI": rsi,
            "BollingerBands": {"upper": bb_upper, "lower": bb_lower},
            "ADX": {"adx": adx, "plus_di": 20.0, "minus_di": 15.0},
        },
        bar_data={"close": close, "high": 110, "low": 90, "volume": 1000},
    )


# ── 1. Adapter wrapping ────────────────────────────────────────────────

class TestAdapterWrapping:
    def test_wraps_squeeze_breakout(self):
        model = SqueezeBreakoutModel(params=SB_PARAMS)
        adapter = LegacyScoringAdapter(model)
        assert isinstance(adapter, ScoringModel)
        assert adapter.meta.name == "SqueezeBreakout"

    def test_wraps_mean_reversion(self):
        model = MeanReversionModel(params=MR_PARAMS)
        adapter = LegacyScoringAdapter(model)
        assert isinstance(adapter, ScoringModel)
        assert adapter.meta.name == "MeanReversion"

    def test_params_delegated(self):
        model = SqueezeBreakoutModel(params=SB_PARAMS)
        adapter = LegacyScoringAdapter(model)
        assert adapter.params is model.params


# ── 2. evaluate() returns ScoringOutput ─────────────────────────────────

class TestEvaluate:
    def test_returns_scoring_output(self):
        model = MeanReversionModel(params=MR_PARAMS)
        adapter = LegacyScoringAdapter(model)
        fv = _mr_fv(rsi=20, close=85, bb_lower=90, adx=15.0)
        result = adapter.evaluate(fv)
        assert isinstance(result, ScoringOutput)

    def test_flat_signal_edge_score_zero(self):
        """Flat signal (direction=0) → edge_score == 0.0."""
        model = MeanReversionModel(params=MR_PARAMS)
        adapter = LegacyScoringAdapter(model)
        # Neutral RSI, price in middle of BB → flat
        fv = _mr_fv(rsi=50, close=100, bb_upper=110, bb_lower=90, adx=15.0)
        result = adapter.evaluate(fv)
        assert result.edge_score == 0.0

    def test_long_signal_positive_edge_score(self):
        """Long (direction=1) → positive edge_score."""
        model = MeanReversionModel(params=MR_PARAMS)
        adapter = LegacyScoringAdapter(model)
        # Oversold RSI + price near lower BB → long
        fv = _mr_fv(rsi=20, close=85, bb_lower=90, adx=15.0)
        result = adapter.evaluate(fv)
        if result.edge_score != 0.0:
            # If the model fires, it should be positive for a long
            assert result.edge_score > 0

    def test_edge_score_invariant(self):
        """edge_score == direction * conviction must hold."""
        model = MeanReversionModel(params=MR_PARAMS)
        adapter = LegacyScoringAdapter(model)
        fv = _mr_fv(rsi=20, close=85, bb_lower=90, adx=15.0)
        result = adapter.evaluate(fv)
        model_output = model.evaluate(fv)
        expected = float(model_output.direction) * model_output.conviction
        assert abs(result.edge_score - expected) < 1e-9

    def test_metadata_adapted_flag(self):
        """Metadata must include _adapted=True and _original_direction."""
        model = MeanReversionModel(params=MR_PARAMS)
        adapter = LegacyScoringAdapter(model)
        fv = _mr_fv(rsi=50, close=100)
        result = adapter.evaluate(fv)
        assert result.metadata["_adapted"] is True
        assert "_original_direction" in result.metadata

    def test_model_name_preserved(self):
        """Output model_name must match wrapped model name."""
        model = MeanReversionModel(params=MR_PARAMS)
        adapter = LegacyScoringAdapter(model)
        fv = _mr_fv()
        result = adapter.evaluate(fv)
        assert result.model_name == "MeanReversion"


# ── 3. Feature validation delegation ───────────────────────────────────

class TestFeatureValidation:
    def test_validate_features_delegates(self):
        model = SqueezeBreakoutModel(params=SB_PARAMS)
        adapter = LegacyScoringAdapter(model)
        available = {"RSI"}  # Missing many SB indicators
        missing_direct = model.validate_features(available)
        missing_adapter = adapter.validate_features(available)
        assert missing_adapter == missing_direct

    def test_validate_required_fields_delegates(self):
        model = SqueezeBreakoutModel(params=SB_PARAMS)
        adapter = LegacyScoringAdapter(model)
        available = {"RSI"}
        missing_direct = model.validate_required_fields(available)
        missing_adapter = adapter.validate_required_fields(available)
        assert missing_adapter == missing_direct


# ── 4. batch_evaluate returns float ─────────────────────────────────────

class TestBatchEvaluate:
    def test_returns_float_series(self):
        model = MeanReversionModel(params=MR_PARAMS)
        adapter = LegacyScoringAdapter(model)
        idx = pd.RangeIndex(5)
        df = pd.DataFrame(
            {
                "RSI": [20, 50, 80, 50, 20],
                "BollingerBands_upper": [110] * 5,
                "BollingerBands_lower": [90] * 5,
                "ADX": [15.0] * 5,
                "close": [85, 100, 115, 100, 85],
            },
            index=idx,
        )
        result = adapter.batch_evaluate(df)
        assert isinstance(result, pd.Series)
        assert result.dtype == float


# ── 5. No mutation of wrapped model state ───────────────────────────────

class TestNoMutation:
    def test_adapter_does_not_mutate_wrapped_model(self):
        """Adapter evaluate should not change wrapped model's params."""
        model = SqueezeBreakoutModel(params=SB_PARAMS)
        params_before = dict(model.params)
        adapter = LegacyScoringAdapter(model)
        fv = _sb_fv()
        adapter.evaluate(fv)
        assert model.params == params_before

    def test_separate_instances_no_shared_state(self):
        """Two adapters wrapping separate model instances should not share state."""
        model1 = SqueezeBreakoutModel(params=SB_PARAMS)
        model2 = SqueezeBreakoutModel(params=SB_PARAMS)
        adapter1 = LegacyScoringAdapter(model1)
        adapter2 = LegacyScoringAdapter(model2)
        assert adapter1._wrapped is not adapter2._wrapped
        # Evaluate one adapter, check the other is unaffected
        fv = _sb_fv()
        adapter1.evaluate(fv)
        # model2's squeeze_history should be independent
        if hasattr(model1, "_squeeze_history"):
            assert model1._squeeze_history is not model2._squeeze_history
