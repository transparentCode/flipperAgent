from __future__ import annotations

import numpy as np
import pandas as pd

from libs.regime.optimization.ablations import DEFAULT_VARIANTS, build_variants


def _make_features() -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=4, freq="1h")
    return pd.DataFrame(
        {
            "regime": [
                "CLEAN_TREND_BULL",
                "VOLATILE_TREND_BEAR",
                "QUIET_MR_RANGE",
                "CHOPPY",
            ],
            "p_trending": [0.8, 0.7, 0.2, 0.1],
            "vol_regime": ["LOW_VOL", "HIGH_VOL", "LOW_VOL", "HIGH_VOL"],
            "vol_percentile": [20.0, 90.0, 40.0, 95.0],
            "changepoint_prob": [0.0, 0.4, 0.8, 0.2],
            "trend_direction": ["BULL", "BEAR", "FLAT", "BULL"],
            "position_scale": [0.9, -0.5, 0.1, 0.0],
        },
        index=idx,
    )


def _position_scale_cfg() -> dict[str, float]:
    return {
        "CLEAN_TREND_BULL": 1.0,
        "CLEAN_TREND_BEAR": -1.0,
        "CLEAN_TREND_FLAT": 0.0,
        "VOLATILE_TREND_BULL": 0.6,
        "VOLATILE_TREND_BEAR": -0.6,
        "VOLATILE_TREND_FLAT": 0.0,
        "QUIET_MR_RANGE": 0.3,
        "QUIET_MR_SQUEEZE": 0.0,
        "CHOPPY": 0.0,
    }


def test_build_variants_returns_all_default_variants():
    variants = build_variants(
        _make_features(),
        position_scale_cfg=_position_scale_cfg(),
        cp_position_decay=0.5,
        vol_squeeze_pct=35.0,
    )

    assert tuple(variants.keys()) == DEFAULT_VARIANTS
    for name, frame in variants.items():
        assert len(frame) == 4, name
        assert frame.index.equals(_make_features().index), name


def test_direction_only_neutralizes_non_directional_overlays():
    variants = build_variants(
        _make_features(),
        position_scale_cfg=_position_scale_cfg(),
        cp_position_decay=0.5,
        vol_squeeze_pct=35.0,
    )

    direction_only = variants["direction_only"]
    assert np.allclose(direction_only["changepoint_prob"].values, 0.0)
    assert set(direction_only["vol_regime"]) == {"LOW_VOL"}
    assert direction_only["regime"].tolist() == [
        "CLEAN_TREND_BULL",
        "CLEAN_TREND_BEAR",
        "QUIET_MR_RANGE",
        "CLEAN_TREND_BULL",
    ]
    assert direction_only["position_scale"].tolist() == [1.0, -1.0, 0.3, 1.0]


def test_direction_plus_hmm_keeps_probability_but_removes_vol_and_cp():
    features = _make_features()
    variants = build_variants(
        features,
        position_scale_cfg=_position_scale_cfg(),
        cp_position_decay=0.5,
        vol_squeeze_pct=35.0,
    )

    frame = variants["direction_plus_hmm"]
    assert np.allclose(frame["p_trending"].values, features["p_trending"].values)
    assert set(frame["vol_regime"]) == {"LOW_VOL"}
    assert np.allclose(frame["changepoint_prob"].values, 0.0)
    assert frame["regime"].tolist() == [
        "CLEAN_TREND_BULL",
        "CLEAN_TREND_BEAR",
        "QUIET_MR_RANGE",
        "QUIET_MR_RANGE",
    ]


def test_direction_plus_cp_only_changes_position_scale():
    features = _make_features()
    variants = build_variants(
        features,
        position_scale_cfg=_position_scale_cfg(),
        cp_position_decay=0.5,
        vol_squeeze_pct=35.0,
    )

    direction_only = variants["direction_only"]
    cp_only = variants["direction_plus_cp"]
    assert direction_only["regime"].tolist() == cp_only["regime"].tolist()
    assert cp_only["position_scale"].iloc[1] == -0.8
    assert cp_only["position_scale"].iloc[2] == 0.18


def test_full_variant_is_passthrough():
    features = _make_features()
    variants = build_variants(
        features,
        position_scale_cfg=_position_scale_cfg(),
        cp_position_decay=0.5,
        vol_squeeze_pct=35.0,
    )

    assert variants["full"].equals(features)
