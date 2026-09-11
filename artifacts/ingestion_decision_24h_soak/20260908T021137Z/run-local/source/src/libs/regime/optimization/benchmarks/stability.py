"""
Tier 4: Stability Benchmark (20% of objective).

Measures regime sequence quality — penalises flip-flop and rewards persistence.

Metrics:
  avg_regime_duration  — mean bars per regime episode (longer = more stable)
  flip_flop_rate       — fraction of bars where regime changed (lower = better)
  transition_entropy   — entropy of empirical transition matrix (lower = more predictable)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute(features_df: pd.DataFrame) -> dict:
    """
    Compute Tier-4 stability metrics.

    Parameters
    ----------
    features_df : must have 'regime' column

    Returns
    -------
    dict with: avg_regime_duration, flip_flop_rate, transition_entropy
    """
    if "regime" not in features_df.columns or len(features_df) < 10:
        return _empty()

    regimes = features_df["regime"].values
    n = len(regimes)

    # Flip-flop rate: fraction of transitions
    changes = np.sum(regimes[1:] != regimes[:-1])
    flip_flop_rate = float(changes / max(n - 1, 1))

    # Average regime duration (run lengths)
    durations = _run_lengths(regimes)
    avg_regime_duration = float(np.mean(durations)) if durations else 1.0

    # Transition entropy
    transition_entropy = _transition_entropy(regimes)

    return {
        "avg_regime_duration": avg_regime_duration,
        "flip_flop_rate": flip_flop_rate,
        "transition_entropy": transition_entropy,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_lengths(regimes: np.ndarray) -> list:
    """Compute lengths of consecutive same-regime runs."""
    if len(regimes) == 0:
        return []
    durations = []
    count = 1
    for i in range(1, len(regimes)):
        if regimes[i] == regimes[i - 1]:
            count += 1
        else:
            durations.append(count)
            count = 1
    durations.append(count)
    return durations


def _transition_entropy(regimes: np.ndarray) -> float:
    """
    Shannon entropy of the empirical regime transition matrix.
    Lower entropy = more predictable transitions.
    """
    unique = np.unique(regimes)
    n_states = len(unique)
    if n_states < 2:
        return 0.0

    state_to_idx = {s: i for i, s in enumerate(unique)}
    counts = np.zeros((n_states, n_states))
    for i in range(len(regimes) - 1):
        from_idx = state_to_idx[regimes[i]]
        to_idx = state_to_idx[regimes[i + 1]]
        counts[from_idx, to_idx] += 1

    # Row-normalise to transition probabilities
    row_sums = counts.sum(axis=1, keepdims=True)
    row_sums = np.where(row_sums == 0, 1, row_sums)
    probs = counts / row_sums

    # Shannon entropy per row, averaged
    with np.errstate(divide="ignore", invalid="ignore"):
        h = -np.where(probs > 0, probs * np.log2(probs + 1e-10), 0.0)
    return float(h.sum(axis=1).mean())


def _empty() -> dict:
    return {
        "avg_regime_duration": 1.0,
        "flip_flop_rate": 1.0,
        "transition_entropy": 2.0,
    }
