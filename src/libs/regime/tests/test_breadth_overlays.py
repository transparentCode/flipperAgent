from __future__ import annotations

import numpy as np
import pandas as pd

from libs.regime.optimization.breadth_overlays import (
    DEFAULT_BREADTH_VARIANTS,
    build_breadth_variants,
    compute_breadth_features,
)


def _position_scale_cfg() -> dict[str, float]:
    return {
        "CLEAN_TREND_BULL": 1.0,
        "CLEAN_TREND_BEAR": 0.2,
        "CLEAN_TREND_FLAT": 0.4,
        "VOLATILE_TREND_BULL": 0.6,
        "VOLATILE_TREND_BEAR": 0.1,
        "VOLATILE_TREND_FLAT": 0.2,
        "QUIET_MR_RANGE": 0.3,
        "QUIET_MR_SQUEEZE": 0.15,
        "CHOPPY": 0.05,
    }


def _make_regime_frame(n: int = 80) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "regime": ["CLEAN_TREND_BULL"] * n,
            "p_trending": np.linspace(0.4, 0.8, n),
            "vol_regime": ["LOW_VOL"] * n,
            "vol_percentile": np.linspace(20.0, 60.0, n),
            "changepoint_prob": np.linspace(0.0, 0.3, n),
            "trend_direction": ["BULL"] * n,
            "position_scale": np.linspace(0.2, 1.0, n),
        },
        index=idx,
    )


def _write_tv_csv(path, datetimes, base):
    df = pd.DataFrame(
        {
            "datetime": datetimes,
            "open": base + np.linspace(0.0, 10.0, len(datetimes)),
            "high": base + np.linspace(0.5, 10.5, len(datetimes)),
            "low": base + np.linspace(-0.5, 9.5, len(datetimes)),
            "close": base + np.linspace(0.1, 10.1, len(datetimes)),
            "volume": np.linspace(1000.0, 2000.0, len(datetimes)),
        }
    )
    df.to_csv(path, index=False)


def test_compute_breadth_features_reads_tv_csvs(tmp_path):
    asset_idx = pd.date_range("2025-01-01", periods=90, freq="1h", tz="UTC")
    asset_frame = pd.DataFrame(
        {
            "open": np.linspace(100.0, 150.0, len(asset_idx)),
            "high": np.linspace(101.0, 151.0, len(asset_idx)),
            "low": np.linspace(99.0, 149.0, len(asset_idx)),
            "close": np.linspace(100.5, 150.5, len(asset_idx)),
            "volume": np.linspace(10.0, 30.0, len(asset_idx)),
        },
        index=asset_idx,
    )

    _write_tv_csv(tmp_path / "BTC_D_1h.csv", asset_idx, 60.0)
    _write_tv_csv(tmp_path / "TOTAL2_1h.csv", asset_idx, 500.0)
    _write_tv_csv(tmp_path / "TOTAL3_1h.csv", asset_idx, 300.0)

    result = compute_breadth_features(asset_frame, data_dir=tmp_path)

    assert not result.empty
    assert len(result) == len(asset_frame)
    assert "eng_regime_alignment_score" in result.columns
    assert "eng_cross_asset_regime_state" in result.columns
    assert result.index.equals(asset_frame.index)


def test_build_breadth_variants_returns_all_expected_variants():
    frame = _make_regime_frame()
    breadth = pd.DataFrame(
        {
            "eng_regime_alignment_score": np.concatenate(
                [np.full(40, -0.8), np.full(40, 0.8)]
            ),
            "eng_cross_asset_regime_state": np.concatenate(
                [np.zeros(40), np.ones(40)]
            ),
        },
        index=frame.index,
    )

    variants = build_breadth_variants(
        frame,
        breadth,
        position_scale_cfg=_position_scale_cfg(),
        cp_position_decay=0.5,
        vol_squeeze_pct=30.0,
    )

    assert set(DEFAULT_BREADTH_VARIANTS) == set(variants)
    for variant in variants.values():
        assert {"regime", "p_trending", "position_scale", "trend_direction"}.issubset(variant.columns)

    gate_variant = variants["breadth_gate"]
    assert gate_variant["position_scale"].iloc[0] < frame["position_scale"].iloc[0]
    assert gate_variant["position_scale"].iloc[-1] > frame["position_scale"].iloc[-1] * 0.9

    regime_variant = variants["breadth_regime"]
    assert regime_variant["trend_direction"].iloc[0] == "BEAR"
    assert regime_variant["trend_direction"].iloc[-1] == "BULL"
