"""
Tier 3: Statistical Validity Benchmark — HARD GATE.

Tests whether the regime labels produce statistically distinguishable
return distributions. Uses Levene's test (variance homogeneity) because
regimes predict *volatility structure*, not necessarily return direction.

Gate: Levene p-value must be < validity_p_threshold (default 0.05).
Bonus/penalty: Cohen's d effect size.

If gate fails in soft mode, the objective is penalised.
In hard mode, the trial is discarded.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def compute(
    features_df: pd.DataFrame,
    returns: np.ndarray,
) -> dict:
    """
    Compute Tier-3 statistical validity metrics.

    Parameters
    ----------
    features_df : must have 'regime' column
    returns     : 1-D log-return array aligned with features_df

    Returns
    -------
    dict with: levene_p_value, cohens_d, passed_validity_gate (p < 0.05)
    """
    if len(returns) < 20 or "regime" not in features_df.columns:
        return _empty()

    n = min(len(returns), len(features_df))
    ret = returns[-n:]
    regime_col = features_df["regime"].values[-n:]

    # Group returns by regime
    groups = {}
    for regime, r in zip(regime_col, ret):
        if np.isfinite(r):
            groups.setdefault(regime, []).append(r)

    # Need at least 2 non-trivial groups
    valid_groups = [np.array(v) for v in groups.values() if len(v) >= 5]
    if len(valid_groups) < 2:
        return _empty()

    # Levene's test
    try:
        _, p_value = stats.levene(*valid_groups)
    except Exception:
        return _empty()
    levene_p = float(p_value) if np.isfinite(p_value) else 1.0

    # Cohen's d (between the two largest groups by variance spread)
    cohens_d = _cohens_d(valid_groups)

    return {
        "levene_p_value": levene_p,
        "cohens_d": cohens_d,
        "passed_validity_gate": levene_p < 0.05,
    }


def gate_penalty(
    levene_p_value: float,
    validity_p_threshold: float = 0.05,
    penalty_factor: float = 5.0,
    soft_gate: bool = True,
) -> float:
    """
    Return a multiplier to apply to the objective score.

    - If gate passed: 1.0 (no penalty)
    - If gate failed, soft mode: divides score by penalty_factor
    - If gate failed, hard mode: caller should discard trial
    """
    if levene_p_value < validity_p_threshold:
        return 1.0
    if soft_gate:
        return 1.0 / penalty_factor
    return 0.0   # hard gate: zero score (caller discards)


def cohens_d_bonus(cohens_d: float) -> float:
    """
    Convert Cohen's d to an additive objective bonus/penalty.
    d < 0.2  → -0.05 penalty
    d 0.2-0.5 → 0.0
    d 0.5-0.8 → +0.05 bonus
    d > 0.8   → +0.10 bonus
    """
    if cohens_d < 0.2:
        return -0.05
    if cohens_d < 0.5:
        return 0.0
    if cohens_d < 0.8:
        return 0.05
    return 0.10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cohens_d(groups: list) -> float:
    """Cohen's d between the two groups with highest mean difference."""
    if len(groups) < 2:
        return 0.0
    best_d = 0.0
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            a, b = groups[i], groups[j]
            mean_diff = abs(np.mean(a) - np.mean(b))
            pooled_std = np.sqrt((np.var(a) + np.var(b)) / 2.0 + 1e-10)
            d = mean_diff / pooled_std
            if d > best_d:
                best_d = d
    return float(best_d)


def _empty() -> dict:
    return {
        "levene_p_value": 1.0,
        "cohens_d": 0.0,
        "passed_validity_gate": False,
    }
