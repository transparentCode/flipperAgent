"""Causal scoring, deterministic bootstrap uncertainty, and disposition."""

from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any

import numpy as np

from libs.models.sr.domain import ContractValidationError

from .calibration import brier_loss, log_loss
from .config import AdaptiveContextCalibrationConfig
from .contracts import AdaptiveDisposition, CandidateCase, PredictionRecord


def _mean(values: list[float]) -> float | None:
    return None if not values else float(sum(values) / len(values))


def _group_key(asset: str, timeframe: str, fold: str) -> str:
    return f"{asset}/{timeframe}/{fold}"


def _score_records(
    predictions: tuple[PredictionRecord, ...],
    cases: dict[str, CandidateCase],
) -> tuple[dict[str, list[tuple[float, float, float, float, float]]], dict[str, int]]:
    records: dict[str, list[tuple[float, float, float, float, float]]] = defaultdict(list)
    censoring: dict[str, int] = defaultdict(int)
    for prediction in predictions:
        key = _group_key(prediction.asset, prediction.timeframe, prediction.fold)
        case = cases.get(prediction.case_id)
        if case is None:
            raise ContractValidationError("prediction references an unknown case")
        if case.real_status is not None and case.real_status.value == "RIGHT_CENSORED":
            censoring[key] += 1
        if prediction.label is None:
            continue
        adaptive = prediction.adaptive_final.probability
        null = prediction.null.probability
        records[key].append(
            (
                brier_loss(adaptive, prediction.label),
                brier_loss(null, prediction.label),
                log_loss(adaptive, prediction.label),
                log_loss(null, prediction.label),
                case.paired_excess_quality_atr if case.paired_excess_quality_atr is not None else 0.0,
            )
        )
    return dict(records), dict(censoring)


def _metric_for_records(records: list[tuple[float, float, float, float, float]]) -> dict[str, Any]:
    if not records:
        return {
            "prediction_count": 0,
            "mean_brier_loss": None,
            "mean_log_loss": None,
            "base_rate_brier": None,
            "base_rate_log_loss": None,
            "brier_improvement": None,
            "log_loss_improvement": None,
            "mean_paired_excess_quality_atr": None,
            "median_paired_excess_quality_atr": None,
        }
    adaptive_brier = [item[0] for item in records]
    null_brier = [item[1] for item in records]
    adaptive_log = [item[2] for item in records]
    null_log = [item[3] for item in records]
    excess = [item[4] for item in records]
    return {
        "prediction_count": len(records),
        "mean_brier_loss": float(sum(adaptive_brier) / len(records)),
        "mean_log_loss": float(sum(adaptive_log) / len(records)),
        "base_rate_brier": float(sum(null_brier) / len(records)),
        "base_rate_log_loss": float(sum(null_log) / len(records)),
        "brier_improvement": float(sum(null_brier) / len(records) - sum(adaptive_brier) / len(records)),
        "log_loss_improvement": float(sum(null_log) / len(records) - sum(adaptive_log) / len(records)),
        "mean_paired_excess_quality_atr": float(sum(excess) / len(excess)),
        "median_paired_excess_quality_atr": float(median(excess)),
    }


def compute_metrics(
    predictions: tuple[PredictionRecord, ...],
    cases: tuple[CandidateCase, ...],
) -> dict[str, Any]:
    if type(predictions) is not tuple or any(type(item) is not PredictionRecord for item in predictions) or type(cases) is not tuple or any(type(item) is not CandidateCase for item in cases):
        raise ContractValidationError("metrics require typed predictions and cases")
    case_map = {item.case_id: item for item in cases}
    grouped, censoring = _score_records(predictions, case_map)
    scored = [record for values in grouped.values() for record in values]
    by_bucket: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for prediction in predictions:
        if prediction.label is not None:
            by_bucket[prediction.bucket.value].append((prediction.adaptive_final.probability, prediction.label))
    bucket_metrics = {
        bucket: {
            "prediction_count": len(values),
            "predicted_rate": _mean([item[0] for item in values]),
            "observed_rate": _mean([float(item[1]) for item in values]),
            "absolute_calibration_gap": None if not values else abs(_mean([item[0] for item in values]) - _mean([float(item[1]) for item in values])),
        }
        for bucket, values in sorted(by_bucket.items())
    }
    cohort_metrics = {key: _metric_for_records(values) for key, values in sorted(grouped.items())}
    return {
        "prediction_count": len(predictions),
        "scored_prediction_count": len(scored),
        "unscored_prediction_count": len(predictions) - len(scored),
        "censored_prediction_count": sum(censoring.values()),
        "adaptive_null_case_ids_identical": all(
            type(item.case_id) is str
            for item in predictions
        ),
        "pooled": _metric_for_records(scored),
        "by_cohort_fold": cohort_metrics,
        "predicted_vs_observed_by_salience_bucket": bucket_metrics,
        "posterior_final_mean": _mean([item.adaptive_final.probability for item in predictions]),
        "posterior_final_interval_width_mean": _mean([item.adaptive_final.upper_90 - item.adaptive_final.lower_90 for item in predictions]),
    }


def _quantile(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"lower_90": None, "upper_90": None}
    return {"lower_90": float(np.quantile(values, 0.05)), "upper_90": float(np.quantile(values, 0.95))}


def bootstrap_summary(
    predictions: tuple[PredictionRecord, ...],
    cases: tuple[CandidateCase, ...],
    *,
    config: AdaptiveContextCalibrationConfig,
) -> dict[str, Any]:
    """Bootstrap cohort-fold cells, then cases inside selected cells."""

    if type(config) is not AdaptiveContextCalibrationConfig:
        raise ContractValidationError("bootstrap requires typed V2.3 configuration")
    grouped, _ = _score_records(predictions, {item.case_id: item for item in cases})
    cells = tuple((key, tuple(values)) for key, values in sorted(grouped.items()) if values)
    draws = config.bootstrap.expected["draws"]
    if not cells:
        empty = {"lower_90": None, "upper_90": None}
        return {
            "protocol": config.bootstrap.to_payload(),
            "draw_count": draws,
            "pooled_brier_improvement": empty,
            "pooled_log_loss_improvement": empty,
            "pooled_mean_paired_excess_quality_atr": empty,
            "median_cohort_brier_improvement": empty,
        }
    generator = np.random.Generator(np.random.PCG64(config.bootstrap.expected["seed"]))
    brier_values: list[float] = []
    log_values: list[float] = []
    quality_values: list[float] = []
    median_cohort_values: list[float] = []
    cell_count = len(cells)
    for _ in range(draws):
        selected = generator.integers(0, cell_count, size=cell_count)
        sampled_by_cohort: dict[str, list[tuple[float, float, float, float, float]]] = defaultdict(list)
        for selected_index in selected:
            key, values = cells[int(selected_index)]
            indices = generator.integers(0, len(values), size=len(values))
            sampled_by_cohort[key].extend(values[int(index)] for index in indices)
        sampled = [item for values in sampled_by_cohort.values() for item in values]
        adaptive_brier = sum(item[0] for item in sampled) / len(sampled)
        null_brier = sum(item[1] for item in sampled) / len(sampled)
        adaptive_log = sum(item[2] for item in sampled) / len(sampled)
        null_log = sum(item[3] for item in sampled) / len(sampled)
        quality_values.append(sum(item[4] for item in sampled) / len(sampled))
        brier_values.append(null_brier - adaptive_brier)
        log_values.append(null_log - adaptive_log)
        cohort_improvements = []
        for values in sampled_by_cohort.values():
            cohort_improvements.append(sum(item[1] - item[0] for item in values) / len(values))
        median_cohort_values.append(float(median(cohort_improvements)))
    return {
        "protocol": config.bootstrap.to_payload(),
        "draw_count": draws,
        "pooled_brier_improvement": _quantile(brier_values),
        "pooled_log_loss_improvement": _quantile(log_values),
        "pooled_mean_paired_excess_quality_atr": _quantile(quality_values),
        "median_cohort_brier_improvement": _quantile(median_cohort_values),
    }


def disposition(
    bootstrap: dict[str, Any],
) -> AdaptiveDisposition:
    brier = bootstrap["pooled_brier_improvement"]
    log = bootstrap["pooled_log_loss_improvement"]
    quality = bootstrap["pooled_mean_paired_excess_quality_atr"]
    median_cohort = bootstrap["median_cohort_brier_improvement"]
    if any(value["lower_90"] is None for value in (brier, log, quality, median_cohort)):
        return AdaptiveDisposition.INSUFFICIENT_CALIBRATION_EVIDENCE
    if brier["lower_90"] > 0.0 and log["lower_90"] >= 0.0 and quality["lower_90"] > 0.0 and median_cohort["lower_90"] > 0.0:
        return AdaptiveDisposition.ADAPTIVE_CONTEXT_SUPPORTED_FOR_SHADOW
    if brier["upper_90"] <= 0.0 or quality["upper_90"] <= 0.0:
        return AdaptiveDisposition.ADAPTIVE_CONTEXT_NOT_SUPPORTED
    return AdaptiveDisposition.INSUFFICIENT_CALIBRATION_EVIDENCE


__all__ = ["bootstrap_summary", "compute_metrics", "disposition"]
