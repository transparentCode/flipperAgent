"""Feature-space ablations for the regime pipeline.

These ablations reuse the live regime output contract and neutralize selected
overlays so we can compare marginal value without changing the training path.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd


DEFAULT_VARIANTS = (
    "direction_only",
    "direction_plus_hmm",
    "direction_plus_vol",
    "direction_plus_cp",
    "direction_plus_hmm_plus_vol",
    "full",
)

_BULL = "BULL"
_BEAR = "BEAR"
_FLAT = "FLAT"
_HIGH_VOL = "HIGH_VOL"
_LOW_VOL = "LOW_VOL"

_CLEAN_TREND_BULL = "CLEAN_TREND_BULL"
_CLEAN_TREND_BEAR = "CLEAN_TREND_BEAR"
_CLEAN_TREND_FLAT = "CLEAN_TREND_FLAT"
_VOLATILE_TREND_BULL = "VOLATILE_TREND_BULL"
_VOLATILE_TREND_BEAR = "VOLATILE_TREND_BEAR"
_VOLATILE_TREND_FLAT = "VOLATILE_TREND_FLAT"
_QUIET_MR_RANGE = "QUIET_MR_RANGE"
_QUIET_MR_SQUEEZE = "QUIET_MR_SQUEEZE"
_CHOPPY = "CHOPPY"


def build_variants(
    features_df: pd.DataFrame,
    *,
    position_scale_cfg: dict[str, float],
    cp_position_decay: float,
    vol_squeeze_pct: float,
    variants: Iterable[str] = DEFAULT_VARIANTS,
) -> dict[str, pd.DataFrame]:
    """Build comparable feature ablations from a live regime feature frame."""
    required = {
        "regime",
        "p_trending",
        "vol_regime",
        "vol_percentile",
        "changepoint_prob",
        "trend_direction",
        "position_scale",
    }
    missing = required.difference(features_df.columns)
    if missing:
        raise ValueError(f"Cannot build ablations, missing columns: {sorted(missing)}")

    results: dict[str, pd.DataFrame] = {}
    for variant in variants:
        results[variant] = _build_variant(
            features_df,
            variant=variant,
            position_scale_cfg=position_scale_cfg,
            cp_position_decay=cp_position_decay,
            vol_squeeze_pct=vol_squeeze_pct,
        )
    return results


def _build_variant(
    features_df: pd.DataFrame,
    *,
    variant: str,
    position_scale_cfg: dict[str, float],
    cp_position_decay: float,
    vol_squeeze_pct: float,
) -> pd.DataFrame:
    frame = features_df.copy()
    direction = frame["trend_direction"].fillna(_FLAT).astype(str).to_numpy()
    actual_p = frame["p_trending"].clip(0.0, 1.0).to_numpy(dtype=float)
    actual_vol_regime = frame["vol_regime"].fillna(_LOW_VOL).astype(str).to_numpy()
    actual_vol_pct = frame["vol_percentile"].fillna(50.0).to_numpy(dtype=float)
    actual_cp = frame["changepoint_prob"].clip(0.0, 1.0).to_numpy(dtype=float)
    direction_p = np.where(np.isin(direction, [_BULL, _BEAR]), 1.0, 0.0)

    if variant == "full":
        return frame
    if variant == "direction_only":
        p_trending = direction_p
        vol_regime = np.full(len(frame), _LOW_VOL, dtype=object)
        vol_pct = np.full(len(frame), 50.0, dtype=float)
        cp_prob = np.zeros(len(frame), dtype=float)
    elif variant == "direction_plus_hmm":
        p_trending = actual_p
        vol_regime = np.full(len(frame), _LOW_VOL, dtype=object)
        vol_pct = np.full(len(frame), 50.0, dtype=float)
        cp_prob = np.zeros(len(frame), dtype=float)
    elif variant == "direction_plus_vol":
        p_trending = direction_p
        vol_regime = actual_vol_regime
        vol_pct = actual_vol_pct
        cp_prob = np.zeros(len(frame), dtype=float)
    elif variant == "direction_plus_cp":
        p_trending = direction_p
        vol_regime = np.full(len(frame), _LOW_VOL, dtype=object)
        vol_pct = np.full(len(frame), 50.0, dtype=float)
        cp_prob = actual_cp
    elif variant == "direction_plus_hmm_plus_vol":
        p_trending = actual_p
        vol_regime = actual_vol_regime
        vol_pct = actual_vol_pct
        cp_prob = np.zeros(len(frame), dtype=float)
    else:
        raise ValueError(f"Unknown ablation variant: {variant}")

    regime = _compose_regime(
        p_trending=p_trending,
        vol_regime=vol_regime,
        vol_percentile=vol_pct,
        direction=direction,
        vol_squeeze_pct=vol_squeeze_pct,
    )
    position_scale = _compose_position_scale(
        p_trending=p_trending,
        vol_regime=vol_regime,
        cp_prob=cp_prob,
        direction=direction,
        position_scale_cfg=position_scale_cfg,
        cp_position_decay=cp_position_decay,
    )

    frame["p_trending"] = p_trending
    frame["vol_regime"] = vol_regime
    frame["vol_percentile"] = vol_pct
    frame["changepoint_prob"] = cp_prob
    frame["regime"] = regime
    frame["position_scale"] = position_scale
    return frame


def _compose_regime(
    *,
    p_trending: np.ndarray,
    vol_regime: np.ndarray,
    vol_percentile: np.ndarray,
    direction: np.ndarray,
    vol_squeeze_pct: float,
) -> np.ndarray:
    trending = p_trending >= 0.5
    high_vol = vol_regime == _HIGH_VOL
    is_bull = direction == _BULL
    is_bear = direction == _BEAR
    is_flat = ~is_bull & ~is_bear

    conditions = [
        trending & ~high_vol & is_bull,
        trending & ~high_vol & is_bear,
        trending & ~high_vol & is_flat,
        trending & high_vol & is_bull,
        trending & high_vol & is_bear,
        trending & high_vol & is_flat,
        ~trending & high_vol,
        ~trending & ~high_vol & (vol_percentile < vol_squeeze_pct),
        ~trending & ~high_vol,
    ]
    choices = [
        _CLEAN_TREND_BULL,
        _CLEAN_TREND_BEAR,
        _CLEAN_TREND_FLAT,
        _VOLATILE_TREND_BULL,
        _VOLATILE_TREND_BEAR,
        _VOLATILE_TREND_FLAT,
        _CHOPPY,
        _QUIET_MR_SQUEEZE,
        _QUIET_MR_RANGE,
    ]
    return np.select(conditions, choices, default=_CHOPPY)


def _compose_position_scale(
    *,
    p_trending: np.ndarray,
    vol_regime: np.ndarray,
    cp_prob: np.ndarray,
    direction: np.ndarray,
    position_scale_cfg: dict[str, float],
    cp_position_decay: float,
) -> np.ndarray:
    high_vol = vol_regime == _HIGH_VOL
    is_bull = direction == _BULL
    is_bear = direction == _BEAR

    t_scale = np.where(
        is_bull,
        np.where(
            high_vol,
            position_scale_cfg[_VOLATILE_TREND_BULL],
            position_scale_cfg[_CLEAN_TREND_BULL],
        ),
        np.where(
            is_bear,
            np.where(
                high_vol,
                position_scale_cfg[_VOLATILE_TREND_BEAR],
                position_scale_cfg[_CLEAN_TREND_BEAR],
            ),
            np.where(
                high_vol,
                position_scale_cfg[_VOLATILE_TREND_FLAT],
                position_scale_cfg[_CLEAN_TREND_FLAT],
            ),
        ),
    )
    nt_scale = np.where(
        high_vol,
        position_scale_cfg[_CHOPPY],
        position_scale_cfg[_QUIET_MR_RANGE],
    )
    blended = p_trending * t_scale + (1.0 - p_trending) * nt_scale
    decay = 1.0 - (1.0 - cp_position_decay) * cp_prob
    return np.round(blended * decay, 4)
