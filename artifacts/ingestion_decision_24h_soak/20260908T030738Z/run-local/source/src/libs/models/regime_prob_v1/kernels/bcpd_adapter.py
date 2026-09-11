"""BCPD adapter for RegimeProbV1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from libs.models.regime_classification.config import (
    scale_bars_for_timeframe,
    timeframe_scaled_config,
)
from libs.models.regime_classification.kernels.bcpd import bcpd_detect


@dataclass(frozen=True)
class BCPDAdapterConfig:
    """Configuration for the BCPD adapter."""

    hazard_lambda: float | None = None
    hazard_shape: float | None = None
    truncation: int | None = None
    min_returns: int = 20
    recent_max_window: int | None = None
    decay_halflife: int | None = None


@dataclass(frozen=True)
class BCPDAdapterOutput:
    """Aligned BCPD feature frame and diagnostics."""

    frame: pd.DataFrame
    diagnostics: dict[str, Any]


def compute_bcpd_features(
    df: pd.DataFrame,
    *,
    timeframe: str = "1h",
    config: BCPDAdapterConfig | None = None,
) -> BCPDAdapterOutput:
    """Compute point-in-time BCPD features aligned to the input index."""
    cfg = _resolve_config(timeframe, config)
    index = df.index.copy()
    neutral = _neutral_frame(index)

    if df.empty:
        return BCPDAdapterOutput(frame=neutral, diagnostics={"status": "empty_input"})
    if "close" not in df.columns:
        return BCPDAdapterOutput(frame=neutral, diagnostics={"status": "missing_close"})

    close = pd.to_numeric(df["close"], errors="coerce").astype(float)
    if close.isna().any() or (close <= 0).any():
        return BCPDAdapterOutput(
            frame=neutral,
            diagnostics={"status": "invalid_close_series", "rows": int(len(df))},
        )

    prices = close.to_numpy(dtype=float)
    returns = np.diff(np.log(prices + 1e-10))
    if len(returns) < cfg.min_returns:
        return BCPDAdapterOutput(
            frame=neutral,
            diagnostics={
                "status": "insufficient_data",
                "rows": int(len(df)),
                "returns": int(len(returns)),
                "min_returns": int(cfg.min_returns),
            },
        )

    posterior, cp_prob_returns = bcpd_detect(
        returns,
        hazard_lambda=cfg.hazard_lambda,
        hazard_shape=cfg.hazard_shape,
        truncation=cfg.truncation,
        return_posterior=True,
    )
    cp_probs = np.zeros(len(df), dtype=float)
    cp_probs[1:] = cp_prob_returns

    run_length = np.zeros(len(df), dtype=int)
    cp_entropy = np.zeros(len(df), dtype=float)
    if posterior.size:
        run_length[1:] = np.argmax(posterior, axis=1).astype(int)
        cp_entropy[1:] = _posterior_entropy(posterior)

    cp_recent_max = (
        pd.Series(cp_probs, index=index)
        .rolling(window=cfg.recent_max_window, min_periods=1)
        .max()
        .to_numpy(dtype=float)
    )
    cp_decay_score = _decay_score(cp_probs, halflife=cfg.decay_halflife)
    entropy_scale = max(float(np.log(cfg.truncation + 1)), 1.0)
    cp_entropy_norm = np.clip(cp_entropy / entropy_scale, 0.0, 1.0)
    transition_risk_raw = np.clip(
        0.50 * cp_probs
        + 0.25 * cp_decay_score
        + 0.15 * cp_recent_max
        + 0.10 * cp_entropy_norm,
        0.0,
        1.0,
    )

    frame = pd.DataFrame(
        {
            "changepoint_prob": cp_probs.astype(float),
            "run_length": run_length.astype(int),
            "cp_entropy": cp_entropy.astype(float),
            "cp_recent_max": cp_recent_max.astype(float),
            "cp_decay_score": cp_decay_score.astype(float),
            "transition_risk_raw": transition_risk_raw.astype(float),
        },
        index=index,
    )
    diagnostics = {
        "status": "ok",
        "rows": int(len(df)),
        "returns": int(len(returns)),
        "hazard_lambda": float(cfg.hazard_lambda),
        "hazard_shape": float(cfg.hazard_shape),
        "truncation": int(cfg.truncation),
        "mean_changepoint_prob": float(np.mean(cp_probs)),
        "max_changepoint_prob": float(np.max(cp_probs)),
    }
    return BCPDAdapterOutput(frame=frame, diagnostics=diagnostics)


def _resolve_config(timeframe: str, config: BCPDAdapterConfig | None) -> BCPDAdapterConfig:
    base = timeframe_scaled_config(timeframe).bcpd
    raw = config or BCPDAdapterConfig()
    return BCPDAdapterConfig(
        hazard_lambda=base.hazard_lambda if raw.hazard_lambda is None else raw.hazard_lambda,
        hazard_shape=base.hazard_shape if raw.hazard_shape is None else raw.hazard_shape,
        truncation=base.truncation if raw.truncation is None else raw.truncation,
        min_returns=int(raw.min_returns),
        recent_max_window=(
            scale_bars_for_timeframe(24, timeframe, floor=3)
            if raw.recent_max_window is None
            else int(raw.recent_max_window)
        ),
        decay_halflife=(
            scale_bars_for_timeframe(24, timeframe, floor=3)
            if raw.decay_halflife is None
            else int(raw.decay_halflife)
        ),
    )


def _neutral_frame(index: pd.Index) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "changepoint_prob": np.zeros(len(index), dtype=float),
            "run_length": np.zeros(len(index), dtype=int),
            "cp_entropy": np.zeros(len(index), dtype=float),
            "cp_recent_max": np.zeros(len(index), dtype=float),
            "cp_decay_score": np.zeros(len(index), dtype=float),
            "transition_risk_raw": np.zeros(len(index), dtype=float),
        },
        index=index,
    )


def _decay_score(cp_probs: np.ndarray, *, halflife: int) -> np.ndarray:
    if len(cp_probs) == 0:
        return np.zeros(0, dtype=float)
    decay = 0.5 ** (1.0 / max(int(halflife), 1))
    out = np.zeros(len(cp_probs), dtype=float)
    for i, prob in enumerate(cp_probs):
        previous = out[i - 1] * decay if i > 0 else 0.0
        out[i] = max(float(prob), float(previous))
    return out


def _posterior_entropy(posterior: np.ndarray) -> np.ndarray:
    posterior = np.asarray(posterior, dtype=float)
    if posterior.size == 0:
        return np.zeros(0, dtype=float)
    totals = posterior.sum(axis=1, keepdims=True)
    safe = np.divide(
        posterior,
        np.where(totals > 0.0, totals, 1.0),
        out=np.zeros_like(posterior, dtype=float),
        where=True,
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        log_probs = np.where(safe > 0.0, np.log(safe), 0.0)
    return -(safe * log_probs).sum(axis=1).astype(float)


__all__ = [
    "BCPDAdapterConfig",
    "BCPDAdapterOutput",
    "compute_bcpd_features",
]
