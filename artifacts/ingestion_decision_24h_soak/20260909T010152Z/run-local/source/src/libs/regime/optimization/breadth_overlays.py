"""Breadth overlay experiments for regime evaluation.

These helpers reuse the existing TradingView breadth feature definitions and
project them onto the same regime benchmark contract used by the evaluation
runner. The goal is to test breadth as an additive overlay, not to replace the
core regime classifier.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from libs.features.engineered.cross_sectional import (
    AltcoinMarketMomentum,
    BTCDominanceMomentum,
    CrossAssetRegimeState,
    MarketCapBreadth,
    RegimeAlignmentScore,
    RelativeStrengthVsTotal3,
)
from libs.regime.optimization.ablations import _compose_position_scale, _compose_regime

DEFAULT_BREADTH_VARIANTS = (
    "regime_only",
    "breadth_gate",
    "breadth_blend",
    "breadth_regime",
)

_TV_SYMBOLS = ("BTC.D", "TOTAL2", "TOTAL3")
_TV_FILE_SUFFIX = "_1h.csv"
_TV_TOLERANCE = pd.Timedelta(hours=2)
_BULL = "BULL"
_BEAR = "BEAR"
_FLAT = "FLAT"
_BREADTH_FEATURE_PARAMS = {
    "btc_dominance_momentum": {"sma_period": 10, "atr_period": 14},
    "relative_strength_vs_total3": {"period": 20, "clip_range": 10.0},
    "cross_asset_regime_state": {"btc_d_threshold": 0.3, "t3_threshold": 0.3},
    "regime_alignment_score": {
        "w_btc_d": 0.3,
        "w_t3": 0.3,
        "w_breadth": 0.2,
        "w_rs": 0.2,
        "breadth_scale": 10.0,
    },
}


def compute_breadth_features(
    asset_frame: pd.DataFrame,
    *,
    data_dir: str | Path = "data/tv_index",
) -> pd.DataFrame:
    """Compute aligned breadth features for an asset OHLCV frame.

    The TradingView files are currently stored at 1h granularity. For lower
    asset timeframes we backward-fill the most recent breadth snapshot with a
    tight tolerance so the breadth context behaves like a slower overlay.
    """
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(asset_frame.columns)
    if missing:
        raise ValueError(f"Asset frame missing required columns: {sorted(missing)}")
    if asset_frame.empty:
        return pd.DataFrame(index=asset_frame.index)

    aligned = _align_index_data(asset_frame, data_dir=Path(data_dir))
    result = _compute_feature_rows(aligned)
    result = result.reindex(asset_frame.index)
    result.index = asset_frame.index
    return result


def build_breadth_variants(
    regime_features_df: pd.DataFrame,
    breadth_features_df: pd.DataFrame,
    *,
    position_scale_cfg: dict[str, float],
    cp_position_decay: float,
    vol_squeeze_pct: float,
    variants: tuple[str, ...] = DEFAULT_BREADTH_VARIANTS,
) -> dict[str, pd.DataFrame]:
    """Build breadth-aware variants from an existing regime feature frame."""
    required = {
        "regime",
        "p_trending",
        "vol_regime",
        "vol_percentile",
        "changepoint_prob",
        "trend_direction",
        "position_scale",
    }
    missing = required.difference(regime_features_df.columns)
    if missing:
        raise ValueError(f"Cannot build breadth overlays, missing columns: {sorted(missing)}")

    breadth = breadth_features_df.reindex(regime_features_df.index).copy()
    breadth["eng_regime_alignment_score"] = (
        breadth.get("eng_regime_alignment_score", pd.Series(0.0, index=breadth.index))
        .fillna(0.0)
        .clip(-1.0, 1.0)
    )
    breadth["eng_cross_asset_regime_state"] = (
        breadth.get("eng_cross_asset_regime_state", pd.Series(2.0, index=breadth.index))
        .fillna(2.0)
        .astype(int)
    )

    frame = regime_features_df.copy()
    score = breadth["eng_regime_alignment_score"].to_numpy(dtype=float)
    state = breadth["eng_cross_asset_regime_state"].to_numpy(dtype=int)

    actual_p = frame["p_trending"].clip(0.0, 1.0).to_numpy(dtype=float)
    actual_vol_regime = frame["vol_regime"].fillna("LOW_VOL").astype(str).to_numpy()
    actual_vol_pct = frame["vol_percentile"].fillna(50.0).to_numpy(dtype=float)
    actual_cp = frame["changepoint_prob"].clip(0.0, 1.0).to_numpy(dtype=float)
    actual_direction = frame["trend_direction"].fillna(_FLAT).astype(str).to_numpy()
    actual_scale = frame["position_scale"].fillna(0.0).to_numpy(dtype=float)

    breadth_prob = np.clip((score + 1.0) / 2.0, 0.0, 1.0)
    state_bias = np.select(
        [state == 1, state == 2, state == 0, state == 3],
        [0.85, 0.60, 0.20, 0.10],
        default=0.50,
    )
    gate = np.select(
        [state == 1, state == 2, state == 0, state == 3],
        [1.20, 1.00, 0.60, 0.40],
        default=0.85,
    )
    gate = np.clip(gate * (1.0 + 0.35 * score), 0.25, 1.50)
    blended_prob = np.clip(0.70 * actual_p + 0.30 * (0.5 * breadth_prob + 0.5 * state_bias), 0.0, 1.0)
    breadth_only_prob = np.clip(0.5 * breadth_prob + 0.5 * state_bias, 0.0, 1.0)

    breadth_direction = np.where(
        state == 1,
        _BULL,
        np.where(
            state == 0,
            _BEAR,
            np.where(
                state == 3,
                _BEAR,
                np.where(score > 0.15, _BULL, np.where(score < -0.15, _BEAR, actual_direction)),
            ),
        ),
    )
    blend_direction = np.where(
        (state == 1) & (score >= 0.0),
        _BULL,
        np.where(
            (state == 0) | ((state == 3) & (score <= 0.0)),
            _BEAR,
            actual_direction,
        ),
    )

    results: dict[str, pd.DataFrame] = {}
    for variant in variants:
        variant_df = frame.copy()
        if variant == "regime_only":
            results[variant] = variant_df
            continue
        if variant == "breadth_gate":
            variant_df["position_scale"] = np.clip(actual_scale * gate, 0.0, 1.5)
            results[variant] = variant_df
            continue
        if variant == "breadth_blend":
            p_trending = blended_prob
            direction = blend_direction
        elif variant == "breadth_regime":
            p_trending = breadth_only_prob
            direction = breadth_direction
        else:
            raise ValueError(f"Unknown breadth overlay variant: {variant}")

        regime = _compose_regime(
            p_trending=p_trending,
            vol_regime=actual_vol_regime,
            vol_percentile=actual_vol_pct,
            direction=direction,
            vol_squeeze_pct=vol_squeeze_pct,
        )
        position_scale = _compose_position_scale(
            p_trending=p_trending,
            vol_regime=actual_vol_regime,
            cp_prob=actual_cp,
            direction=direction,
            position_scale_cfg=position_scale_cfg,
            cp_position_decay=cp_position_decay,
        )
        variant_df["p_trending"] = p_trending
        variant_df["trend_direction"] = direction
        variant_df["regime"] = regime
        variant_df["position_scale"] = np.clip(position_scale * gate, 0.0, 1.5)
        results[variant] = variant_df
    return results


def _align_index_data(asset_frame: pd.DataFrame, *, data_dir: Path) -> pd.DataFrame:
    asset = asset_frame.reset_index().rename(columns={asset_frame.index.name or "index": "timestamp"})
    asset["timestamp"] = _normalize_timestamp_unit(pd.to_datetime(asset["timestamp"], utc=True))
    aligned = asset.sort_values("timestamp").reset_index(drop=True)

    for symbol in _TV_SYMBOLS:
        index_df = _load_tv_csv(symbol, data_dir=data_dir)
        aligned = pd.merge_asof(
            aligned,
            index_df,
            left_on="timestamp",
            right_on="timestamp",
            direction="backward",
            tolerance=_TV_TOLERANCE,
        )
    critical = [f"{_symbol_key(symbol)}_close" for symbol in _TV_SYMBOLS]
    aligned = aligned.dropna(subset=critical).reset_index(drop=True)
    return aligned


def _load_tv_csv(symbol: str, *, data_dir: Path) -> pd.DataFrame:
    path = data_dir / f"{symbol.replace('.', '_')}{_TV_FILE_SUFFIX}"
    if not path.exists():
        raise FileNotFoundError(f"TradingView breadth data not found: {path}")
    df = pd.read_csv(path)
    if "datetime" not in df.columns:
        raise ValueError(f"TradingView data missing datetime column: {path}")
    df["timestamp"] = _normalize_timestamp_unit(pd.to_datetime(df["datetime"], utc=True))
    prefix = _symbol_key(symbol)
    columns = ["timestamp", "open", "high", "low", "close", "volume"]
    missing = [col for col in columns[1:] if col not in df.columns]
    if missing:
        raise ValueError(f"TradingView data missing columns {missing}: {path}")
    return (
        df[columns]
        .rename(columns={col: f"{prefix}_{col}" for col in columns if col != "timestamp"})
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def _compute_feature_rows(aligned: pd.DataFrame) -> pd.DataFrame:
    features_pass1 = [
        ("eng_btc_dominance_momentum", BTCDominanceMomentum(_BREADTH_FEATURE_PARAMS["btc_dominance_momentum"])),
        ("eng_altcoin_market_momentum", AltcoinMarketMomentum()),
        ("eng_market_cap_breadth", MarketCapBreadth()),
        ("eng_relative_strength_vs_total3", RelativeStrengthVsTotal3(_BREADTH_FEATURE_PARAMS["relative_strength_vs_total3"])),
    ]
    features_pass2 = [
        ("eng_cross_asset_regime_state", CrossAssetRegimeState(_BREADTH_FEATURE_PARAMS["cross_asset_regime_state"])),
        ("eng_regime_alignment_score", RegimeAlignmentScore(_BREADTH_FEATURE_PARAMS["regime_alignment_score"])),
    ]
    states = {name: {} for name, _ in features_pass1 + features_pass2}
    rows: list[dict[str, Any]] = []

    for row in aligned.itertuples(index=False):
        idx = pd.Timestamp(row.timestamp)
        index_data = {
            "BTC.D": _row_to_index_payload(row, "btcd"),
            "TOTAL2": _row_to_index_payload(row, "total2"),
            "TOTAL3": _row_to_index_payload(row, "total3"),
        }
        bar_data = {
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume),
        }
        computed: dict[str, float] = {}
        for name, feature in features_pass1:
            value = feature.compute(
                features=computed,
                bar_data=bar_data,
                state=states[name],
                index_data=index_data,
            )
            computed[name] = 0.0 if value is None else float(value)
        for name, feature in features_pass2:
            value = feature.compute(
                features=computed,
                bar_data=bar_data,
                state=states[name],
                index_data=index_data,
            )
            computed[name] = 0.0 if value is None else float(value)
        computed["timestamp"] = idx
        rows.append(computed)

    result = pd.DataFrame(rows)
    if result.empty:
        return result.set_index(pd.Index([], name="timestamp"))
    return result.set_index("timestamp").sort_index()


def _row_to_index_payload(row: Any, prefix: str) -> dict[str, float]:
    return {
        "open": float(getattr(row, f"{prefix}_open")),
        "high": float(getattr(row, f"{prefix}_high")),
        "low": float(getattr(row, f"{prefix}_low")),
        "close": float(getattr(row, f"{prefix}_close")),
        "volume": float(getattr(row, f"{prefix}_volume")),
    }


def _symbol_key(symbol: str) -> str:
    return symbol.lower().replace(".", "")


def _normalize_timestamp_unit(values: pd.Series) -> pd.Series:
    if hasattr(values.dt, "as_unit"):
        return values.dt.as_unit("ns")
    return pd.to_datetime(values.astype(str), utc=True)
