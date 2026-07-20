"""Deterministic, sample-aware metrics for Phase-I stage evaluators."""

from __future__ import annotations

from collections import defaultdict
import math
from statistics import mean, median, pstdev
from typing import Iterable, Sequence

from .contracts import MetricRecord, ObjectiveSpec, WindowResult


def ratio_metric(
    name: str,
    *,
    numerator: float,
    denominator: float,
    sample_count: int,
    valid_row_count: int | None = None,
    excluded_row_count: int = 0,
    metric_version: str = "v1",
) -> MetricRecord:
    if denominator == 0.0:
        return MetricRecord(
            name=name,
            value=None,
            numerator=numerator,
            denominator=denominator,
            sample_count=sample_count,
            valid_row_count=valid_row_count or 0,
            excluded_row_count=excluded_row_count,
            undefined_reason="zero_denominator",
            metric_version=metric_version,
        )
    return MetricRecord(
        name=name,
        value=numerator / denominator,
        numerator=numerator,
        denominator=denominator,
        sample_count=sample_count,
        valid_row_count=sample_count if valid_row_count is None else valid_row_count,
        excluded_row_count=excluded_row_count,
        metric_version=metric_version,
    )


def mean_metric(
    name: str,
    values: Iterable[float],
    *,
    sample_count: int | None = None,
    excluded_row_count: int = 0,
    metric_version: str = "v1",
) -> MetricRecord:
    usable = [float(value) for value in values if math.isfinite(float(value))]
    total = len(usable) if sample_count is None else sample_count
    if not usable:
        return MetricRecord(
            name=name,
            value=None,
            sample_count=total,
            valid_row_count=0,
            excluded_row_count=excluded_row_count,
            undefined_reason="no_valid_values",
            metric_version=metric_version,
        )
    return MetricRecord(
        name=name,
        value=mean(usable),
        numerator=sum(usable),
        denominator=float(len(usable)),
        sample_count=total,
        valid_row_count=len(usable),
        excluded_row_count=excluded_row_count,
        metric_version=metric_version,
    )


def binary_classification_metrics(
    *,
    labels: Sequence[bool],
    predictions: Sequence[bool],
    metric_prefix: str = "",
) -> tuple[MetricRecord, ...]:
    if len(labels) != len(predictions):
        raise ValueError("labels and predictions must have equal length")
    positives = sum(labels)
    negatives = len(labels) - positives
    predicted_positive = sum(predictions)
    true_positive = sum(label and prediction for label, prediction in zip(labels, predictions, strict=True))
    true_negative = sum(not label and not prediction for label, prediction in zip(labels, predictions, strict=True))
    false_positive = predicted_positive - true_positive
    false_negative = positives - true_positive
    positive_precision = ratio_metric(f"{metric_prefix}precision", numerator=true_positive, denominator=predicted_positive, sample_count=len(labels))
    positive_recall = ratio_metric(f"{metric_prefix}recall", numerator=true_positive, denominator=positives, sample_count=len(labels))
    negative_precision = ratio_metric(f"{metric_prefix}negative_precision", numerator=true_negative, denominator=true_negative + false_negative, sample_count=len(labels))
    negative_recall = ratio_metric(f"{metric_prefix}specificity", numerator=true_negative, denominator=negatives, sample_count=len(labels))
    positive_f1 = _f1_metric(f"{metric_prefix}positive_f1", positive_precision, positive_recall)
    negative_f1 = _f1_metric(f"{metric_prefix}negative_f1", negative_precision, negative_recall)
    macro_f1 = _macro_f1_metric(f"{metric_prefix}macro_f1", positive_f1, negative_f1, sample_count=len(labels))
    return (
        positive_precision,
        positive_recall,
        negative_precision,
        negative_recall,
        positive_f1,
        negative_f1,
        macro_f1,
        ratio_metric(f"{metric_prefix}false_early_rate", numerator=false_positive, denominator=predicted_positive, sample_count=len(labels)),
        ratio_metric(f"{metric_prefix}missed_event_rate", numerator=false_negative, denominator=positives, sample_count=len(labels)),
    )


def _f1_metric(name: str, precision: MetricRecord, recall: MetricRecord) -> MetricRecord:
    if precision.value is None or recall.value is None or precision.value + recall.value == 0.0:
        return MetricRecord(name=name, value=None, undefined_reason="undefined_class_f1")
    return MetricRecord(
        name=name,
        value=2.0 * precision.value * recall.value / (precision.value + recall.value),
        sample_count=min(precision.sample_count, recall.sample_count),
        valid_row_count=min(precision.valid_row_count, recall.valid_row_count),
        metric_version="binary_f1_v1",
    )


def _macro_f1_metric(name: str, positive: MetricRecord, negative: MetricRecord, *, sample_count: int) -> MetricRecord:
    if positive.value is None or negative.value is None:
        return MetricRecord(name=name, value=None, sample_count=sample_count, undefined_reason="undefined_class_f1")
    return MetricRecord(
        name=name,
        value=(positive.value + negative.value) / 2.0,
        sample_count=sample_count,
        valid_row_count=sample_count,
        metric_version="macro_f1_v1",
    )


def aggregate_window_metrics(
    results: Iterable[WindowResult], *, objective: ObjectiveSpec | None = None
) -> dict[str, MetricRecord]:
    """Aggregate comparable validation windows without fabricating undefined values."""

    values: dict[str, list[float]] = defaultdict(list)
    samples: dict[str, int] = defaultdict(int)
    valid_rows: dict[str, int] = defaultdict(int)
    excluded: dict[str, int] = defaultdict(int)
    for result in results:
        for metric in result.metrics:
            samples[metric.name] += metric.sample_count
            valid_rows[metric.name] += metric.valid_row_count
            excluded[metric.name] += metric.excluded_row_count
            if metric.value is not None:
                values[metric.name].append(metric.value)
    aggregate: dict[str, MetricRecord] = {}
    for name in sorted(samples):
        series = values[name]
        if series:
            aggregate[name] = MetricRecord(
                name=name,
                value=mean(series),
                numerator=sum(series),
                denominator=float(len(series)),
                sample_count=samples[name],
                valid_row_count=valid_rows[name],
                excluded_row_count=excluded[name],
                metric_version="aggregate_v1",
            )
        else:
            aggregate[name] = MetricRecord(
                name=name,
                value=None,
                sample_count=samples[name],
                valid_row_count=0,
                excluded_row_count=excluded[name],
                undefined_reason="no_defined_window_metric",
                metric_version="aggregate_v1",
            )
        if series:
            aggregate[f"{name}__median"] = MetricRecord(name=f"{name}__median", value=median(series), sample_count=len(series), valid_row_count=len(series), metric_version="aggregate_v1")
            aggregate[f"{name}__std"] = MetricRecord(name=f"{name}__std", value=pstdev(series) if len(series) > 1 else 0.0, sample_count=len(series), valid_row_count=len(series), metric_version="aggregate_v1")
            aggregate[f"{name}__minimum"] = MetricRecord(name=f"{name}__minimum", value=min(series), sample_count=len(series), valid_row_count=len(series), metric_version="aggregate_v1")
            aggregate[f"{name}__maximum"] = MetricRecord(name=f"{name}__maximum", value=max(series), sample_count=len(series), valid_row_count=len(series), metric_version="aggregate_v1")
            worst = max(series) if objective is not None and name == objective.primary_metric and not objective.maximize else min(series)
            aggregate[f"{name}__worst"] = MetricRecord(name=f"{name}__worst", value=worst, sample_count=len(series), valid_row_count=len(series), metric_version="aggregate_v1")
    return aggregate


def metric_delta(name: str, baseline: MetricRecord | None, candidate: MetricRecord | None) -> MetricRecord:
    if baseline is None or candidate is None or baseline.value is None or candidate.value is None:
        return MetricRecord(name=name, value=None, undefined_reason="incompatible_or_undefined_metric")
    return MetricRecord(
        name=name,
        value=candidate.value - baseline.value,
        numerator=candidate.value,
        denominator=baseline.value,
        sample_count=min(baseline.sample_count, candidate.sample_count),
        valid_row_count=min(baseline.valid_row_count, candidate.valid_row_count),
        metric_version="delta_v1",
    )


__all__ = ["aggregate_window_metrics", "binary_classification_metrics", "mean_metric", "metric_delta", "ratio_metric"]
