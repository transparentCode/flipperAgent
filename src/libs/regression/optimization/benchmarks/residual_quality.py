"""
Tier 3: Residual Quality — GATE (not weighted).

Computes Durbin-Watson on *first-differenced* residuals:
    e_t   = close_t - midline_t[-1]      (level residual)
    Δe_t  = e_t - e_{t-1}                (change in residual)
    DW    = Σ(Δe_t - Δe_{t-1})² / Σ(Δe_t²)

First-differencing removes the slow trend, producing DW values in the
1.0–2.5 range which meaningfully discriminate parameter quality.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from app.regression.contracts.result import RegressionResult
from app.regression.optimization.benchmarks._common import extract_result_arrays
from app.regression.optimization.constants import (
    DEFAULT_MIN_DURBIN_WATSON,
    EPSILON,
    MIN_RESIDUAL_SAMPLES_ABS,
    MIN_RESIDUAL_SAMPLES_FRAC,
)


def compute(
    results: List[RegressionResult],
    closes: np.ndarray,
    min_dw: float = DEFAULT_MIN_DURBIN_WATSON,
    arrays: Optional[Dict[str, np.ndarray]] = None,
) -> Dict[str, float]:
    """Compute Durbin-Watson on first-differenced regression residuals."""
    if arrays is None:
        arrays = extract_result_arrays(results, closes)
    indices = arrays["indices"]
    mid_vals = arrays["mid_vals"]

    if len(indices) == 0:
        return {"durbin_watson": 0.0, "passed_residual_gate": False}

    residuals = closes[indices] - mid_vals
    residuals = residuals[np.isfinite(residuals)]

    min_required = max(MIN_RESIDUAL_SAMPLES_ABS, int(len(closes) * MIN_RESIDUAL_SAMPLES_FRAC))

    if len(residuals) < min_required:
        return {"durbin_watson": 0.0, "passed_residual_gate": False}

    de = np.diff(residuals)
    if len(de) < min_required - 1:
        return {"durbin_watson": 0.0, "passed_residual_gate": False}

    diffs = np.diff(de)
    dw = float(np.sum(diffs ** 2) / (np.sum(de ** 2) + EPSILON))

    return {
        "durbin_watson": dw,
        "passed_residual_gate": dw >= min_dw,
    }

