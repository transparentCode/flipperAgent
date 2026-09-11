"""Offline playbook edge labels for RegimeProbV1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from libs.models.regime_prob_v1.config import RegimeProbLabelConfig
from libs.models.regime_v2.config import scale_bars, timeframe_scaled_config
from libs.models.regime_v2.data_quality import prepare_ohlcv

_PLAYBOOKS = (
    "trend_following",
    "breakout",
    "mean_reversion",
    "scalping",
    "countertrend",
)

_PLAYBOOK_SCORE_COLUMNS = {
    "trend_following": "policy_trend_score",
    "breakout": "policy_breakout_score",
    "mean_reversion": "policy_mean_reversion_score",
    "scalping": "policy_scalping_score",
    "countertrend": "policy_countertrend_score",
}


@dataclass(frozen=True)
class PurgedFourWaySplitConfig:
    """Train/calibration/validation/OOS split with purge gaps."""

    train_ratio: float = 0.50
    calibration_ratio: float = 0.20
    validation_ratio: float = 0.15
    oos_ratio: float = 0.15
    purge_bars: int = 24
    min_segment_bars: int = 20


@dataclass(frozen=True)
class PurgedFourWaySplit:
    """Index boundaries for one four-way temporal split."""

    train_start: int
    train_end: int
    calibration_start: int
    calibration_end: int
    validation_start: int
    validation_end: int
    oos_start: int
    oos_end: int
    purge_bars: int

    @property
    def train_slice(self) -> slice:
        return slice(self.train_start, self.train_end)

    @property
    def calibration_slice(self) -> slice:
        return slice(self.calibration_start, self.calibration_end)

    @property
    def validation_slice(self) -> slice:
        return slice(self.validation_start, self.validation_end)

    @property
    def oos_slice(self) -> slice:
        return slice(self.oos_start, self.oos_end)


@dataclass(frozen=True)
class EdgeLabelResult:
    """Offline edge labels plus temporal split metadata."""

    frame: pd.DataFrame
    split: PurgedFourWaySplit
    diagnostics: dict[str, Any]


def build_regime_prob_edge_labels(
    feature_frame: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    timeframe: str,
    config: RegimeProbLabelConfig | None = None,
    split_config: PurgedFourWaySplitConfig | None = None,
) -> EdgeLabelResult:
    """Build playbook-specific forward-return labels on a separate offline path."""
    cfg = config or RegimeProbLabelConfig()
    split_cfg = split_config or PurgedFourWaySplitConfig(purge_bars=int(cfg.purge_bars))
    split = build_purged_four_way_split(len(feature_frame), config=split_cfg)
    if feature_frame.empty:
        return EdgeLabelResult(
            frame=pd.DataFrame(index=feature_frame.index.copy()),
            split=split,
            diagnostics={"status": "empty_feature_frame"},
        )

    prepared = prepare_ohlcv(ohlcv, ("open", "high", "low", "close", "volume"))
    close = (
        prepared.reindex(feature_frame.index)["close"]
        .astype(float)
        .replace([np.inf, -np.inf], np.nan)
    )
    label_frame = pd.DataFrame(index=feature_frame.index)
    label_frame["close"] = close
    label_frame["temporal_segment"] = _segment_series(feature_frame.index, split)

    side_columns = _side_columns(feature_frame, close=close, timeframe=timeframe, cfg=cfg)
    for name, series in side_columns.items():
        label_frame[name] = series.astype(float)

    fee_return = 2.0 * float(cfg.fee_bps) / 10_000.0
    log_close = np.log(close.replace(0.0, np.nan))
    for horizon in cfg.horizons:
        fwd_log_return = (log_close.shift(-int(horizon)) - log_close).astype(float)
        label_frame[f"fwd_log_return_h{int(horizon)}"] = fwd_log_return
        label_frame[f"fwd_abs_log_return_h{int(horizon)}"] = fwd_log_return.abs()
        for playbook in _PLAYBOOKS:
            side = label_frame[f"{playbook}_side"].astype(float)
            net = (side * fwd_log_return) - fee_return
            valid = side != 0.0
            net = net.where(valid).where(fwd_log_return.notna())
            label_frame[f"{playbook}_edge_return_h{int(horizon)}"] = net.astype(float)
            label_frame[f"{playbook}_edge_positive_h{int(horizon)}"] = _binary_label(net > 0.0, valid=net.notna())
            label_frame[f"{playbook}_adverse_excursion_h{int(horizon)}"] = _adverse_excursion(
                log_close.to_numpy(dtype=float),
                side.to_numpy(dtype=float),
                horizon=int(horizon),
            )

    diagnostics = {
        "status": "ok",
        "rows": int(len(feature_frame)),
        "horizons": [int(horizon) for horizon in cfg.horizons],
        "fee_bps": float(cfg.fee_bps),
        "purge_bars": int(split.purge_bars),
        "segment_counts": {
            segment: int((label_frame["temporal_segment"] == segment).sum())
            for segment in ("train", "calibration", "validation", "oos", "purge")
        },
    }
    return EdgeLabelResult(frame=label_frame, split=split, diagnostics=diagnostics)


def build_purged_four_way_split(
    n_rows: int,
    *,
    config: PurgedFourWaySplitConfig | None = None,
) -> PurgedFourWaySplit:
    """Split one history into train/calibration/validation/OOS with purge gaps."""
    cfg = config or PurgedFourWaySplitConfig()
    total_ratio = cfg.train_ratio + cfg.calibration_ratio + cfg.validation_ratio + cfg.oos_ratio
    if abs(total_ratio - 1.0) > 1e-6:
        raise ValueError("four-way split ratios must sum to 1.0")

    min_bars = 4 * int(cfg.min_segment_bars) + 3 * int(cfg.purge_bars)
    if n_rows < min_bars:
        raise ValueError(
            f"Insufficient data: {n_rows} bars, need >= {min_bars} "
            f"(4×{cfg.min_segment_bars} usable + 3×{cfg.purge_bars} purge)"
        )

    usable = n_rows - 3 * int(cfg.purge_bars)
    train_size = int(usable * cfg.train_ratio)
    calibration_size = int(usable * cfg.calibration_ratio)
    validation_size = int(usable * cfg.validation_ratio)
    oos_size = usable - train_size - calibration_size - validation_size
    sizes = (train_size, calibration_size, validation_size, oos_size)
    if min(sizes) < int(cfg.min_segment_bars):
        raise ValueError(
            "Insufficient data after ratio allocation for minimum segment size "
            f"{cfg.min_segment_bars}: sizes={sizes}"
        )

    train_start = 0
    train_end = train_start + train_size
    calibration_start = train_end + int(cfg.purge_bars)
    calibration_end = calibration_start + calibration_size
    validation_start = calibration_end + int(cfg.purge_bars)
    validation_end = validation_start + validation_size
    oos_start = validation_end + int(cfg.purge_bars)
    oos_end = oos_start + oos_size
    return PurgedFourWaySplit(
        train_start=train_start,
        train_end=train_end,
        calibration_start=calibration_start,
        calibration_end=calibration_end,
        validation_start=validation_start,
        validation_end=validation_end,
        oos_start=oos_start,
        oos_end=oos_end,
        purge_bars=int(cfg.purge_bars),
    )


def playbook_score_column(playbook: str) -> str:
    """Return the deterministic score column used as the initial raw edge score."""
    normalized = str(playbook).strip().lower()
    if normalized not in _PLAYBOOK_SCORE_COLUMNS:
        raise KeyError(f"Unsupported playbook: {playbook}")
    return _PLAYBOOK_SCORE_COLUMNS[normalized]


def playbook_label_column(playbook: str, horizon: int) -> str:
    """Return the binary label column name for one playbook/horizon."""
    normalized = str(playbook).strip().lower()
    if normalized not in _PLAYBOOK_SCORE_COLUMNS:
        raise KeyError(f"Unsupported playbook: {playbook}")
    return f"{normalized}_edge_positive_h{int(horizon)}"


def _side_columns(
    feature_frame: pd.DataFrame,
    *,
    close: pd.Series,
    timeframe: str,
    cfg: RegimeProbLabelConfig,
) -> dict[str, pd.Series]:
    trend = _direction_side(feature_frame.get("trend_direction"), positive=("bull", "up"), negative=("bear", "down"))
    breakout_raw = feature_frame.get("breakout_direction")
    if breakout_raw is None and cfg.require_directional_breakout:
        breakout = pd.Series(0.0, index=feature_frame.index, dtype=float)
    else:
        breakout = _direction_side(breakout_raw, positive=("up", "bull"), negative=("down", "bear"))

    mr = _mean_reversion_side(close, timeframe=timeframe)
    scalping = _scalping_side(close, timeframe=timeframe)
    countertrend = np.where(trend != 0.0, -trend, mr)

    return {
        "trend_following_side": trend,
        "breakout_side": breakout,
        "mean_reversion_side": mr,
        "scalping_side": scalping,
        "countertrend_side": pd.Series(countertrend, index=feature_frame.index, dtype=float),
    }


def _direction_side(
    values: pd.Series | None,
    *,
    positive: tuple[str, ...],
    negative: tuple[str, ...],
) -> pd.Series:
    if values is None:
        return pd.Series(dtype=float)
    normalized = values.astype(str).str.lower()
    out = pd.Series(0.0, index=normalized.index, dtype=float)
    out.loc[normalized.isin(positive)] = 1.0
    out.loc[normalized.isin(negative)] = -1.0
    return out


def _mean_reversion_side(close: pd.Series, *, timeframe: str) -> pd.Series:
    cfg = timeframe_scaled_config(timeframe).mean_reversion
    center = close.rolling(cfg.center_window, min_periods=5).mean()
    band = close.rolling(cfg.band_window, min_periods=5).std(ddof=0).replace(0.0, np.nan)
    z = ((close - center) / band).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    side = np.where(z > 0.0, -1.0, np.where(z < 0.0, 1.0, 0.0))
    return pd.Series(side, index=close.index, dtype=float)


def _scalping_side(close: pd.Series, *, timeframe: str) -> pd.Series:
    lookback = scale_bars(3, timeframe, floor=1)
    momentum = close.diff(lookback).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    side = np.sign(momentum).astype(float)
    return pd.Series(side, index=close.index, dtype=float)


def _segment_series(index: pd.Index, split: PurgedFourWaySplit) -> pd.Series:
    out = pd.Series("purge", index=index, dtype=object)
    out.iloc[split.train_slice] = "train"
    out.iloc[split.calibration_slice] = "calibration"
    out.iloc[split.validation_slice] = "validation"
    out.iloc[split.oos_slice] = "oos"
    return out


def _binary_label(condition: pd.Series, *, valid: pd.Series) -> pd.Series:
    out = pd.Series(np.nan, index=condition.index, dtype=float)
    out.loc[valid] = condition.loc[valid].astype(float)
    return out


def _adverse_excursion(log_close: np.ndarray, side: np.ndarray, *, horizon: int) -> np.ndarray:
    out = np.full(len(log_close), np.nan, dtype=float)
    if horizon <= 0:
        return out
    for idx in range(0, max(len(log_close) - horizon, 0)):
        if not np.isfinite(side[idx]) or side[idx] == 0.0 or not np.isfinite(log_close[idx]):
            continue
        future = log_close[idx + 1 : idx + horizon + 1]
        if future.size < horizon or not np.isfinite(future).all():
            continue
        path = side[idx] * (future - log_close[idx])
        out[idx] = float(np.min(path))
    return out


__all__ = [
    "EdgeLabelResult",
    "PurgedFourWaySplit",
    "PurgedFourWaySplitConfig",
    "build_purged_four_way_split",
    "build_regime_prob_edge_labels",
    "playbook_label_column",
    "playbook_score_column",
]
