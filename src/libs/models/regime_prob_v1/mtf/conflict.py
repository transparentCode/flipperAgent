"""Derived MTF confirmation and conflict features."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


def build_mtf_context_frame(
    aligned_frame: pd.DataFrame,
    *,
    higher_timeframes: Sequence[str],
    horizon: int,
) -> pd.DataFrame:
    """Aggregate HTF confirmations/conflicts from aligned probability frames."""
    out = pd.DataFrame(index=aligned_frame.index)
    trend_cols: list[pd.Series] = []
    breakout_cols: list[pd.Series] = []
    mr_cols: list[pd.Series] = []
    conflict_cols: list[pd.Series] = []
    entropy_cols: list[pd.Series] = []
    transition_cols: list[pd.Series] = []

    for timeframe in higher_timeframes:
        prefix = _tf_prefix(timeframe)
        available = _series(aligned_frame.get(f"{prefix}_available"), aligned_frame.index, default=0.0)
        trend_state = _series(aligned_frame.get(f"{prefix}_p_trend_state"), aligned_frame.index)
        range_state = _series(aligned_frame.get(f"{prefix}_p_range_state"), aligned_frame.index)
        chop_state = _series(aligned_frame.get(f"{prefix}_p_chop_state"), aligned_frame.index)
        breakout_state = _series(aligned_frame.get(f"{prefix}_p_breakout_state"), aligned_frame.index)
        shock_state = _series(aligned_frame.get(f"{prefix}_p_vol_shock_state"), aligned_frame.index)
        transition_state = _series(aligned_frame.get(f"{prefix}_p_transition_state"), aligned_frame.index)
        entropy = _series(aligned_frame.get(f"{prefix}_state_entropy"), aligned_frame.index)

        trend_edge = _first_present(
            aligned_frame,
            aligned_frame.index,
            [
                f"{prefix}_trend_following_p_edge_h{int(horizon)}",
                f"{prefix}_p_trend_following_edge",
            ],
        )
        breakout_edge = _first_present(
            aligned_frame,
            aligned_frame.index,
            [
                f"{prefix}_breakout_p_edge_h{int(horizon)}",
                f"{prefix}_p_breakout_edge",
            ],
        )
        mr_edge = _first_present(
            aligned_frame,
            aligned_frame.index,
            [
                f"{prefix}_mean_reversion_p_edge_h{int(horizon)}",
                f"{prefix}_p_mr_edge",
                f"{prefix}_p_mean_reversion_edge",
            ],
        )

        trend_confirmation = np.clip(np.maximum(trend_state, trend_edge) * (1.0 - 0.5 * transition_state), 0.0, 1.0)
        breakout_confirmation = np.clip(np.maximum(breakout_state, breakout_edge) * (1.0 - shock_state), 0.0, 1.0)
        mr_confirmation = np.clip(np.maximum.reduce([range_state, chop_state, mr_edge]) * (1.0 - 0.5 * trend_state), 0.0, 1.0)
        conflict_score = np.clip(
            np.maximum.reduce(
                [
                    trend_confirmation * mr_confirmation,
                    breakout_confirmation * shock_state,
                    np.maximum(trend_state, breakout_state) * transition_state,
                ]
            ),
            0.0,
            1.0,
        )

        out[f"{prefix}_trend_confirmation"] = (trend_confirmation * available).astype(float)
        out[f"{prefix}_breakout_confirmation"] = (breakout_confirmation * available).astype(float)
        out[f"{prefix}_mr_confirmation"] = (mr_confirmation * available).astype(float)
        out[f"{prefix}_conflict_score"] = (conflict_score * available).astype(float)
        out[f"{prefix}_entropy"] = (entropy * available).astype(float)
        out[f"{prefix}_transition"] = (transition_state * available).astype(float)

        trend_cols.append(out[f"{prefix}_trend_confirmation"])
        breakout_cols.append(out[f"{prefix}_breakout_confirmation"])
        mr_cols.append(out[f"{prefix}_mr_confirmation"])
        conflict_cols.append(out[f"{prefix}_conflict_score"])
        entropy_cols.append(out[f"{prefix}_entropy"])
        transition_cols.append(out[f"{prefix}_transition"])

    out["mtf_trend_confirmation"] = _max_across(trend_cols, aligned_frame.index)
    out["mtf_breakout_confirmation"] = _max_across(breakout_cols, aligned_frame.index)
    out["mtf_mr_confirmation"] = _max_across(mr_cols, aligned_frame.index)
    out["mtf_conflict_score"] = _max_across(conflict_cols, aligned_frame.index)
    out["mtf_entropy_max"] = _max_across(entropy_cols, aligned_frame.index)
    out["mtf_transition_max"] = _max_across(transition_cols, aligned_frame.index)
    return out


def _series(values: pd.Series | None, index: pd.Index, *, default: float = 0.0) -> pd.Series:
    if values is None:
        return pd.Series(default, index=index, dtype=float)
    return pd.to_numeric(values.reindex(index), errors="coerce").fillna(default)


def _first_present(frame: pd.DataFrame, index: pd.Index, candidates: list[str]) -> pd.Series:
    for column in candidates:
        if column in frame.columns:
            return pd.to_numeric(frame[column].reindex(index), errors="coerce").fillna(0.0)
    return pd.Series(0.0, index=index, dtype=float)


def _max_across(columns: list[pd.Series], index: pd.Index) -> pd.Series:
    if not columns:
        return pd.Series(0.0, index=index, dtype=float)
    return pd.concat(columns, axis=1).max(axis=1).fillna(0.0)


def _tf_prefix(timeframe: str) -> str:
    return f"mtf_{str(timeframe).lower().replace('.', '_')}"


__all__ = [
    "build_mtf_context_frame",
]
