"""Tier 5 — Fold Stability benchmark.

Measures cross-fold variance of fitness scores.  Low variance
(stability_score → 1.0) means the params generalise well across
different time periods.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np


def compute(fold_fitness_scores: List[float]) -> Dict[str, float]:
    """Compute fold stability from a list of per-fold fitness values.

    Returns
    -------
    dict with keys: ``fitness_cv``, ``stability_score``.
    """
    if len(fold_fitness_scores) < 2:
        return {"fitness_cv": 0.0, "stability_score": 1.0}

    scores = np.array(fold_fitness_scores, dtype=float)
    mean = float(np.mean(scores))
    std = float(np.std(scores))

    cv = (std / mean) if mean > 1e-9 else 1.0
    stability = max(0.0, min(1.0, 1.0 - cv))

    return {
        "fitness_cv": round(cv, 6),
        "stability_score": round(stability, 6),
    }
