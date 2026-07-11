"""Calibration reports for RegimeProbV1 empirical probabilities."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def build_empirical_calibration_report(
    scores: pd.Series | np.ndarray,
    labels: pd.Series | np.ndarray,
    model: Any,
) -> dict[str, Any]:
    """Build bucket and probability diagnostics for one calibrated edge head."""
    joined = pd.DataFrame(
        {
            "score": pd.Series(scores, copy=False),
            "label": pd.Series(labels, copy=False),
        }
    ).replace([np.inf, -np.inf], np.nan)
    joined = joined.loc[joined["score"].notna() & joined["label"].notna()]
    if joined.empty:
        return _empty_report()

    score_arr = joined["score"].to_numpy(dtype=float)
    label_arr = joined["label"].to_numpy(dtype=float)
    probs = np.asarray(model.predict_proba(score_arr), dtype=float)
    valid = np.isfinite(probs) & np.isfinite(label_arr)
    if not np.any(valid):
        return _empty_report()
    score_arr = score_arr[valid]
    label_arr = label_arr[valid]
    probs = probs[valid]

    bucket_index = _assign_bins(score_arr, np.asarray(model.bin_edges, dtype=float))
    buckets: list[dict[str, Any]] = []
    for idx in range(len(model.bin_probabilities)):
        mask = bucket_index == idx
        if not np.any(mask):
            continue
        actual_rate = float(np.mean(label_arr[mask]))
        buckets.append(
            {
                "bucket": int(idx),
                "lower_bound": float(model.bin_edges[idx]),
                "upper_bound": float(model.bin_edges[idx + 1]),
                "count": int(mask.sum()),
                "predicted_prob": float(model.bin_probabilities[idx]),
                "actual_rate": actual_rate,
            }
        )

    top_bottom_spread = 0.0
    if len(buckets) >= 2:
        ordered = sorted(buckets, key=lambda row: row["predicted_prob"])
        top_bottom_spread = float(ordered[-1]["actual_rate"] - ordered[0]["actual_rate"])

    return {
        "support_count": int(len(label_arr)),
        "positive_rate": float(np.mean(label_arr)),
        "mean_probability": float(np.mean(probs)),
        "brier_score": float(np.mean((probs - label_arr) ** 2)),
        "log_loss": _log_loss(label_arr, probs),
        "expected_calibration_error": _expected_calibration_error(label_arr, probs, n_bins=10),
        "top_bottom_bucket_spread": top_bottom_spread,
        "bucket_count": int(len(buckets)),
        "bucket_predicted_prob": [float(row["predicted_prob"]) for row in buckets],
        "bucket_actual_rate": [float(row["actual_rate"]) for row in buckets],
        "buckets": buckets,
    }


def render_empirical_calibration_markdown(
    report: dict[str, Any],
    *,
    playbook: str,
    horizon: int,
    segment: str,
) -> str:
    """Render a compact Markdown summary for one playbook/horizon segment."""
    lines = [
        "# RegimeProbV1 Calibration Report",
        "",
        f"- Playbook: {playbook}",
        f"- Horizon: {int(horizon)}",
        f"- Segment: {segment}",
        f"- Support: {report.get('support_count', 0)}",
        f"- Positive rate: {report.get('positive_rate', 0.0):.4f}",
        f"- Mean probability: {report.get('mean_probability', 0.0):.4f}",
        f"- Brier: {report.get('brier_score', 1.0):.4f}",
        f"- Log loss: {report.get('log_loss', 0.0):.4f}",
        f"- ECE: {report.get('expected_calibration_error', 1.0):.4f}",
        f"- Top-bottom spread: {report.get('top_bottom_bucket_spread', 0.0):.4f}",
        "",
        "| Bucket | Count | Predicted | Actual |",
        "|---:|---:|---:|---:|",
    ]
    for bucket in report.get("buckets", []):
        lines.append(
            "| {bucket} | {count} | {predicted:.4f} | {actual:.4f} |".format(
                bucket=bucket.get("bucket"),
                count=bucket.get("count"),
                predicted=float(bucket.get("predicted_prob", 0.0)),
                actual=float(bucket.get("actual_rate", 0.0)),
            )
        )
    return "\n".join(lines)


def _expected_calibration_error(labels: np.ndarray, probs: np.ndarray, n_bins: int) -> float:
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    total = len(labels)
    error = 0.0
    for left, right in zip(edges[:-1], edges[1:]):
        if right == 1.0:
            mask = (probs >= left) & (probs <= right)
        else:
            mask = (probs >= left) & (probs < right)
        if not np.any(mask):
            continue
        acc = float(np.mean(labels[mask]))
        conf = float(np.mean(probs[mask]))
        error += abs(acc - conf) * (mask.sum() / total)
    return float(error)


def _log_loss(labels: np.ndarray, probs: np.ndarray) -> float:
    clipped = np.clip(probs, 1e-6, 1.0 - 1e-6)
    return float(-np.mean(labels * np.log(clipped) + (1.0 - labels) * np.log(1.0 - clipped)))


def _assign_bins(scores: np.ndarray, edges: np.ndarray) -> np.ndarray:
    idx = np.searchsorted(edges, scores, side="right") - 1
    return np.clip(idx, 0, len(edges) - 2).astype(int)


def _empty_report() -> dict[str, Any]:
    return {
        "support_count": 0,
        "positive_rate": 0.0,
        "mean_probability": 0.0,
        "brier_score": 1.0,
        "log_loss": 0.0,
        "expected_calibration_error": 1.0,
        "top_bottom_bucket_spread": 0.0,
        "bucket_count": 0,
        "bucket_predicted_prob": [],
        "bucket_actual_rate": [],
        "buckets": [],
    }


__all__ = [
    "build_empirical_calibration_report",
    "render_empirical_calibration_markdown",
]
