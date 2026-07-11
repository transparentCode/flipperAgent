"""Transition-risk helpers for the RegimeProbV1 state model."""

from __future__ import annotations

import numpy as np
import pandas as pd


def transition_matrix_self_probability(
    posteriors: np.ndarray,
    transmat: np.ndarray | None,
) -> np.ndarray:
    """Return per-bar P(stay in current latent state)."""
    if transmat is None or len(posteriors) == 0:
        return np.full(len(posteriors), 0.5, dtype=float)
    out = np.full(len(posteriors), 0.5, dtype=float)
    for idx in range(len(posteriors)):
        state = int(np.argmax(posteriors[idx]))
        if 0 <= state < transmat.shape[0]:
            out[idx] = float(np.clip(transmat[state, state], 0.0, 1.0))
    return out


def posterior_shift_series(
    posteriors: np.ndarray,
    index: pd.Index,
) -> pd.Series:
    """Half-L1 posterior drift between consecutive bars."""
    if len(posteriors) == 0:
        return pd.Series(dtype=float, index=index)
    shift = np.zeros(len(posteriors), dtype=float)
    if len(posteriors) > 1:
        delta = np.abs(np.diff(posteriors, axis=0)).sum(axis=1)
        shift[1:] = 0.5 * delta
    return pd.Series(np.clip(shift, 0.0, 1.0), index=index, dtype=float)


def combine_transition_probability(
    feature_frame: pd.DataFrame,
    *,
    base_transition: pd.Series,
    self_transition_prob: pd.Series,
    posterior_shift: pd.Series,
) -> pd.Series:
    """Blend HMM and deterministic transition evidence into one probability."""
    index = feature_frame.index
    transition_inputs = [
        _clip01(base_transition, index),
        _clip01(1.0 - self_transition_prob, index),
        _clip01(posterior_shift, index),
        _series(feature_frame, "changepoint_prob", index),
        _series(feature_frame, "cp_recent_max", index),
        _series(feature_frame, "transition_risk_raw", index),
        _series(feature_frame, "structural_break_risk", index),
        0.75 * _series(feature_frame, "uncertainty", index),
    ]
    return pd.concat(transition_inputs, axis=1).max(axis=1).clip(0.0, 1.0).astype(float)


def _series(frame: pd.DataFrame, column: str, index: pd.Index) -> pd.Series:
    return pd.to_numeric(frame.get(column), errors="coerce").reindex(index).fillna(0.0).clip(0.0, 1.0)


def _clip01(series: pd.Series | np.ndarray | float, index: pd.Index) -> pd.Series:
    if isinstance(series, pd.Series):
        values = pd.to_numeric(series.reindex(index), errors="coerce").fillna(0.0)
    else:
        values = pd.Series(series, index=index, dtype=float)
    return values.clip(0.0, 1.0)


__all__ = [
    "combine_transition_probability",
    "posterior_shift_series",
    "transition_matrix_self_probability",
]
