"""Tests for MeanReversion v2 — continuous z-score scoring model."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from libs.contracts.schemas import FeatureVector
from libs.contracts.signal import ScoringOutput
from libs.models.mean_reversion.model import MeanReversionModel, _batch_mr_zscore
from libs.models.registry import ModelRegistry
from libs.models.scoring_base import ScoringModel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def model() -> MeanReversionModel:
    return MeanReversionModel({})


def _make_feature_vec(
    rsi: float | None = 40.0,
    bb_upper: float | None = 105.0,
    bb_lower: float | None = 95.0,
    close: float = 98.0,
    kama: float | None = 100.0,
    atr: float | None = 2.0,
    adx: float | None = 20.0,
    asset: str = "BTCUSDT",
    timeframe: str = "1h",
    timestamp: float = 1700000000.0,
) -> FeatureVector:
    features: dict = {}
    if rsi is not None:
        features["RSI"] = rsi
    if bb_upper is not None and bb_lower is not None:
        features["BollingerBands"] = {"upper": bb_upper, "lower": bb_lower}
    if kama is not None:
        features["KAMA_fast"] = kama
    if atr is not None:
        features["ATR"] = atr
    if adx is not None:
        features["ADX"] = {"adx": adx}
    bar_data = {"close": close}
    return FeatureVector(
        asset=asset, timeframe=timeframe, timestamp=timestamp,
        features=features, bar_data=bar_data,
    )


def _make_batch_df(n: int = 100, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "RSI": rng.uniform(20, 80, n),
        "BollingerBands_upper": 105.0 + rng.normal(0, 2, n),
        "BollingerBands_lower": 95.0 + rng.normal(0, 2, n),
        "close": 100.0 + rng.normal(0, 3, n),
        "KAMA_fast": 100.0 + rng.normal(0, 1, n),
        "ATR": rng.uniform(1.0, 5.0, n),
        "ADX_adx": rng.uniform(10, 50, n),
    })


# ---------------------------------------------------------------------------
# S1: isinstance(model, ScoringModel)
# ---------------------------------------------------------------------------

def test_s1_isinstance_scoring_model(model: MeanReversionModel) -> None:
    assert isinstance(model, ScoringModel)


# ---------------------------------------------------------------------------
# S2: evaluate() returns ScoringOutput
# ---------------------------------------------------------------------------

def test_s2_evaluate_returns_scoring_output(model: MeanReversionModel) -> None:
    fv = _make_feature_vec()
    result = model.evaluate(fv)
    assert isinstance(result, ScoringOutput)
    assert result.model_name == "MeanReversion"
    assert result.asset == "BTCUSDT"


# ---------------------------------------------------------------------------
# S3: edge_score is continuous (not just -1/0/1)
# ---------------------------------------------------------------------------

def test_s3_edge_score_continuous(model: MeanReversionModel) -> None:
    scores = set()
    for rsi in range(20, 80, 3):
        for close_offset in [-5, -2, 0, 2, 5]:
            fv = _make_feature_vec(rsi=float(rsi), close=100.0 + close_offset)
            result = model.evaluate(fv)
            scores.add(round(result.edge_score, 6))
    # Must have >10 distinct values (continuous, not just {-1, 0, 1})
    assert len(scores) > 10, f"Only {len(scores)} distinct edge_scores — not continuous"


# ---------------------------------------------------------------------------
# S4: batch returns float64 Series
# ---------------------------------------------------------------------------

def test_s4_batch_returns_float64(model: MeanReversionModel) -> None:
    df = _make_batch_df()
    result = model.batch_evaluate(df)
    assert isinstance(result, pd.Series)
    assert result.dtype == np.float64
    assert len(result) == len(df)


# ---------------------------------------------------------------------------
# S5: batch/live parity
# ---------------------------------------------------------------------------

def test_s5_batch_live_parity(model: MeanReversionModel) -> None:
    df = _make_batch_df(n=50)
    batch_result = model.batch_evaluate(df)

    for i in range(min(10, len(df))):
        row = df.iloc[i]
        adx_val = row.get("ADX_adx")
        fv = _make_feature_vec(
            rsi=row["RSI"],
            bb_upper=row["BollingerBands_upper"],
            bb_lower=row["BollingerBands_lower"],
            close=row["close"],
            kama=row["KAMA_fast"],
            atr=row["ATR"],
            adx=adx_val if not np.isnan(adx_val) else None,
        )
        live_result = model.evaluate(fv)
        assert abs(batch_result.iloc[i] - live_result.edge_score) < 1e-10, (
            f"Row {i}: batch={batch_result.iloc[i]}, live={live_result.edge_score}"
        )


# ---------------------------------------------------------------------------
# S6: ADX scaling (low ADX → larger |edge| than high ADX)
# ---------------------------------------------------------------------------

def test_s6_adx_scaling(model: MeanReversionModel) -> None:
    # Strong MR condition
    fv_low_adx = _make_feature_vec(rsi=25.0, close=96.0, adx=15.0)
    fv_high_adx = _make_feature_vec(rsi=25.0, close=96.0, adx=40.0)

    result_low = model.evaluate(fv_low_adx)
    result_high = model.evaluate(fv_high_adx)

    assert abs(result_low.edge_score) > abs(result_high.edge_score), (
        f"Low ADX |edge| ({abs(result_low.edge_score):.4f}) should be > "
        f"high ADX |edge| ({abs(result_high.edge_score):.4f})"
    )


# ---------------------------------------------------------------------------
# S7: graceful degradation (missing inputs)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing_field", ["rsi", "bb", "kama", "atr", "adx"])
def test_s7_graceful_degradation(model: MeanReversionModel, missing_field: str) -> None:
    kwargs = dict(rsi=40.0, bb_upper=105.0, bb_lower=95.0, close=98.0,
                  kama=100.0, atr=2.0, adx=20.0)
    if missing_field == "rsi":
        kwargs["rsi"] = None
    elif missing_field == "bb":
        kwargs["bb_upper"] = None
        kwargs["bb_lower"] = None
    elif missing_field == "kama":
        kwargs["kama"] = None
    elif missing_field == "atr":
        kwargs["atr"] = None
    elif missing_field == "adx":
        kwargs["adx"] = None

    fv = _make_feature_vec(**kwargs)
    result = model.evaluate(fv)
    assert isinstance(result, ScoringOutput)
    # Should not crash; edge_score should still be a float
    assert isinstance(result.edge_score, float)
    assert isinstance(result.conviction, float)


def test_s7_missing_close(model: MeanReversionModel) -> None:
    fv = _make_feature_vec(close=0.0)
    result = model.evaluate(fv)
    assert result.edge_score == 0.0
    assert result.conviction == 0.0
    assert result.metadata.get("trigger") == "missing_close"


# ---------------------------------------------------------------------------
# S8: registry key unchanged
# ---------------------------------------------------------------------------

def test_s8_registry_key(model: MeanReversionModel) -> None:
    cls = ModelRegistry.get("MeanReversion")
    assert cls is MeanReversionModel


# ---------------------------------------------------------------------------
# S10: Numba compilation works
# ---------------------------------------------------------------------------

def test_s10_numba_compiles() -> None:
    n = 10
    rsi = np.array([40.0] * n, dtype=np.float64)
    bb_upper = np.array([105.0] * n, dtype=np.float64)
    bb_lower = np.array([95.0] * n, dtype=np.float64)
    close = np.array([98.0] * n, dtype=np.float64)
    kama = np.array([100.0] * n, dtype=np.float64)
    atr = np.array([2.0] * n, dtype=np.float64)
    adx = np.array([20.0] * n, dtype=np.float64)

    result = _batch_mr_zscore(
        rsi, bb_upper, bb_lower, close, kama, atr, adx,
        15.0, 0.4, 0.4, 0.2, 25.0, 5.0,
    )
    assert result.dtype == np.float64
    assert len(result) == n
    # All values should be identical (same inputs)
    assert np.allclose(result, result[0])


# ---------------------------------------------------------------------------
# Additional: model_type is "scoring"
# ---------------------------------------------------------------------------

def test_model_type_scoring(model: MeanReversionModel) -> None:
    assert model.meta.model_type == "scoring"


# ---------------------------------------------------------------------------
# Additional: conviction is in [0, 1)
# ---------------------------------------------------------------------------

def test_conviction_range(model: MeanReversionModel) -> None:
    for rsi in [20, 30, 40, 50, 60, 70, 80]:
        fv = _make_feature_vec(rsi=float(rsi))
        result = model.evaluate(fv)
        assert 0.0 <= result.conviction < 1.0, (
            f"Conviction {result.conviction} out of range for RSI={rsi}"
        )
