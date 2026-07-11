"""Empirical bucket calibrator for RegimeProbV1 playbook edge probabilities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from libs.models.regime_prob_v1.edge.calibration_report import build_empirical_calibration_report
from libs.models.regime_prob_v1.edge.labels import (
    PurgedFourWaySplit,
    playbook_label_column,
    playbook_score_column,
)


@dataclass(frozen=True)
class EmpiricalCalibratorModel:
    """Quantile-bucket empirical probability calibrator."""

    strategy: str
    bin_edges: tuple[float, ...]
    bin_probabilities: tuple[float, ...]
    counts: tuple[int, ...]
    global_rate: float
    min_bin_count: int

    def predict_proba(self, scores: pd.Series | np.ndarray) -> np.ndarray:
        values = np.asarray(scores, dtype=float)
        out = np.full(values.shape, np.nan, dtype=float)
        finite = np.isfinite(values)
        if not np.any(finite):
            return out
        idx = _assign_bins(values[finite], np.asarray(self.bin_edges, dtype=float))
        probs = np.asarray(self.bin_probabilities, dtype=float)
        out[finite] = probs[idx]
        return out

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlaybookCalibrationResult:
    """One calibrated playbook/horizon result with segment reports."""

    playbook: str
    horizon: int
    score_column: str
    label_column: str
    model: EmpiricalCalibratorModel
    probabilities: pd.Series
    reports: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "playbook": self.playbook,
            "horizon": self.horizon,
            "score_column": self.score_column,
            "label_column": self.label_column,
            "model": self.model.to_dict(),
            "reports": self.reports,
        }


def fit_empirical_calibrator(
    scores: pd.Series | np.ndarray,
    labels: pd.Series | np.ndarray,
    *,
    n_bins: int = 10,
    min_bin_count: int = 10,
    strategy: str = "quantile",
) -> EmpiricalCalibratorModel:
    """Fit an empirical bucket calibrator from raw scores and binary labels."""
    joined = pd.DataFrame(
        {
            "score": pd.Series(scores, copy=False),
            "label": pd.Series(labels, copy=False),
        }
    ).replace([np.inf, -np.inf], np.nan)
    joined = joined.loc[joined["score"].notna() & joined["label"].notna()]
    if joined.empty:
        return EmpiricalCalibratorModel(
            strategy=strategy,
            bin_edges=(0.0, 1.0),
            bin_probabilities=(0.0,),
            counts=(0,),
            global_rate=0.0,
            min_bin_count=int(min_bin_count),
        )

    score_arr = joined["score"].to_numpy(dtype=float)
    label_arr = joined["label"].to_numpy(dtype=float)
    global_rate = float(np.mean(label_arr))
    edges = _build_bin_edges(score_arr, n_bins=int(n_bins), strategy=strategy)
    bucket_index = _assign_bins(score_arr, edges)
    bucket_probs: list[float] = []
    counts: list[int] = []
    for idx in range(len(edges) - 1):
        mask = bucket_index == idx
        count = int(mask.sum())
        counts.append(count)
        if count <= 0:
            bucket_probs.append(global_rate)
            continue
        actual_rate = float(np.mean(label_arr[mask]))
        shrink = max(int(min_bin_count) - count, 0)
        calibrated = (actual_rate * count + global_rate * shrink) / max(count + shrink, 1)
        bucket_probs.append(float(np.clip(calibrated, 0.0, 1.0)))

    return EmpiricalCalibratorModel(
        strategy=strategy,
        bin_edges=tuple(float(edge) for edge in edges),
        bin_probabilities=tuple(bucket_probs),
        counts=tuple(counts),
        global_rate=global_rate,
        min_bin_count=int(min_bin_count),
    )


def fit_playbook_empirical_calibrator(
    feature_frame: pd.DataFrame,
    label_frame: pd.DataFrame,
    *,
    playbook: str,
    horizon: int,
    split: PurgedFourWaySplit | None = None,
    score_column: str | None = None,
    n_bins: int = 10,
    min_bin_count: int = 10,
    strategy: str = "quantile",
) -> PlaybookCalibrationResult:
    """Fit one playbook/horizon empirical calibrator and score each segment."""
    score_col = score_column or playbook_score_column(playbook)
    label_col = playbook_label_column(playbook, horizon)
    if score_col not in feature_frame.columns:
        raise KeyError(f"Missing score column: {score_col}")
    if label_col not in label_frame.columns:
        raise KeyError(f"Missing label column: {label_col}")
    if split is None and "temporal_segment" not in label_frame.columns:
        raise KeyError("label_frame must include temporal_segment when split is not provided")

    if split is not None:
        segments = pd.Series("purge", index=label_frame.index, dtype=object)
        segments.iloc[split.train_slice] = "train"
        segments.iloc[split.calibration_slice] = "calibration"
        segments.iloc[split.validation_slice] = "validation"
        segments.iloc[split.oos_slice] = "oos"
    else:
        segments = label_frame["temporal_segment"].astype(str)

    calibration_mask = segments == "calibration"
    model = fit_empirical_calibrator(
        feature_frame.loc[calibration_mask, score_col],
        label_frame.loc[calibration_mask, label_col],
        n_bins=n_bins,
        min_bin_count=min_bin_count,
        strategy=strategy,
    )
    probabilities = pd.Series(
        model.predict_proba(feature_frame[score_col]),
        index=feature_frame.index,
        name=f"{playbook}_p_edge_h{int(horizon)}",
    )
    reports = {
        segment: build_empirical_calibration_report(
            feature_frame.loc[segments == segment, score_col],
            label_frame.loc[segments == segment, label_col],
            model,
        )
        for segment in ("train", "calibration", "validation", "oos")
    }
    return PlaybookCalibrationResult(
        playbook=str(playbook),
        horizon=int(horizon),
        score_column=score_col,
        label_column=label_col,
        model=model,
        probabilities=probabilities,
        reports=reports,
    )


def _build_bin_edges(scores: np.ndarray, *, n_bins: int, strategy: str) -> np.ndarray:
    clean = scores[np.isfinite(scores)]
    if clean.size == 0:
        return np.array([0.0, 1.0], dtype=float)
    if strategy == "equal_width":
        left = float(np.min(clean))
        right = float(np.max(clean))
        if abs(right - left) < 1e-9:
            width = max(abs(left) * 0.01, 1e-6)
            return np.array([left - width, right + width], dtype=float)
        return np.linspace(left, right, max(int(n_bins), 1) + 1)
    quantiles = np.linspace(0.0, 1.0, max(int(n_bins), 1) + 1)
    edges = np.unique(np.quantile(clean, quantiles))
    if edges.size < 2:
        value = float(clean[0])
        width = max(abs(value) * 0.01, 1e-6)
        return np.array([value - width, value + width], dtype=float)
    return edges.astype(float)


def _assign_bins(scores: np.ndarray, edges: np.ndarray) -> np.ndarray:
    idx = np.searchsorted(edges, scores, side="right") - 1
    return np.clip(idx, 0, len(edges) - 2).astype(int)


__all__ = [
    "EmpiricalCalibratorModel",
    "PlaybookCalibrationResult",
    "fit_empirical_calibrator",
    "fit_playbook_empirical_calibrator",
]
