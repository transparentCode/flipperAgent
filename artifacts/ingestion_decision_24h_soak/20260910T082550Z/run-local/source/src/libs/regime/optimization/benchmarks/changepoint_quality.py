"""
Tier 5: Changepoint Quality Benchmark (10% of objective).

Measures BCPD detection accuracy using vol_regime transitions
(LOW_VOL ↔ HIGH_VOL flips from VolOverlay) as ground-truth structural breaks.

This is semantically aligned: BCPD should detect the same structural vol
shifts that VolOverlay independently classifies as regime transitions.

Metrics:
  cp_precision    — fraction of BCPD signals within detection_window of a vol flip
  cp_recall       — fraction of vol flips that had a BCPD signal within window
  detection_lag   — mean bars between vol flip and closest BCPD signal (lower = better)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute(
    features_df: pd.DataFrame,
    returns: np.ndarray,
    detection_window: int = 12,   # bars within which a CP counts as detected
) -> dict:
    """
    Compute Tier-5 changepoint quality metrics.

    Parameters
    ----------
    features_df      : must have 'vol_regime' and 'changepoint_prob' columns.
                       'bcpd_signal' column used for detection if present.
    returns          : 1-D log-return array aligned with features_df (unused
                       directly but kept for API consistency with other tiers)
    detection_window : bars ± for a CP detection to count as a true positive

    Returns
    -------
    dict with: cp_precision, cp_recall, detection_lag
    """
    required = {"vol_regime", "changepoint_prob"}
    if not required.issubset(features_df.columns):
        return _empty()

    n = len(features_df)
    if n < 20:
        return _empty()

    # Ground-truth breakpoints: LOW_VOL ↔ HIGH_VOL transitions from VolOverlay
    gt_indices = _vol_transition_indices(features_df)

    # Detected changepoints: use bcpd_signal column if present, else local maxima
    cp_prob = features_df["changepoint_prob"].values
    det_indices = _detected_cp_indices(features_df, cp_prob)

    if len(gt_indices) == 0 or len(det_indices) == 0:
        return _empty()

    precision, recall, mean_lag = _match(gt_indices, det_indices, detection_window)

    return {
        "cp_precision": float(precision),
        "cp_recall": float(recall),
        "detection_lag": float(mean_lag),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vol_transition_indices(features_df: pd.DataFrame) -> np.ndarray:
    """
    Integer positions where vol_regime flips between LOW_VOL and HIGH_VOL.

    A transition at position i means features_df['vol_regime'][i] !=
    features_df['vol_regime'][i-1].  Position 0 is never a transition.
    """
    vol = features_df["vol_regime"].values
    # Compare each bar to the previous; +1 offsets the diff back to original index
    transitions = np.where(vol[1:] != vol[:-1])[0] + 1
    return transitions.astype(int)


def _detected_cp_indices(
    features_df: pd.DataFrame,
    cp_prob: np.ndarray,
    min_prob: float = 0.3,
) -> np.ndarray:
    """
    Prefer bcpd_signal column (direct threshold from ChangeDetector).
    Falls back to local maxima of cp_prob > min_prob when column is absent.
    """
    if "bcpd_signal" in features_df.columns:
        signals = features_df["bcpd_signal"].values
        # Handle both bool and numeric (0/1) signal columns
        return np.where(signals.astype(bool))[0].astype(int)

    # Fallback: local maxima above min_prob
    detected = []
    n = len(cp_prob)
    for i in range(1, n - 1):
        if (cp_prob[i] > min_prob
                and cp_prob[i] >= cp_prob[i - 1]
                and cp_prob[i] >= cp_prob[i + 1]):
            detected.append(i)
    return np.array(detected, dtype=int)


def _match(
    gt: np.ndarray,
    det: np.ndarray,
    window: int,
) -> tuple:
    """
    Match detected CPs to ground-truth CPs within ±window bars.

    Returns (precision, recall, mean_lag).
    mean_lag is mean bars between each matched gt and its closest det.
    """
    # Precision: fraction of detections within window of any ground-truth
    tp_det = sum(1 for d in det if np.any(np.abs(gt - d) <= window))
    precision = tp_det / len(det)

    # Recall: fraction of ground-truth transitions detected within window
    tp_gt = 0
    lags = []
    for g in gt:
        within = det[np.abs(det - g) <= window]
        if len(within) > 0:
            tp_gt += 1
            lags.append(int(np.min(np.abs(within - g))))
    recall = tp_gt / len(gt)
    mean_lag = float(np.mean(lags)) if lags else float(window)

    return precision, recall, mean_lag


def _empty() -> dict:
    return {
        "cp_precision": 0.0,
        "cp_recall": 0.0,
        "detection_lag": 999.0,
    }
