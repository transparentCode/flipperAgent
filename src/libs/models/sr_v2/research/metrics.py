"""Probability metrics and deterministic matched-block inference."""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from ..contracts import ForecastOutcome, require_utc
from ..forecast.targets import TargetObservation
from .observations import (
    ResearchObservation,
    canonical_matching_strata,
    validate_issuance_calendar_block,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchMetrics:
    sample_count: int
    outcome_counts: Mapping[str, int]
    brier: float
    multiclass_log_loss: float
    censoring_rate: float
    ambiguity_rate: float
    conclusion: str = "INCONCLUSIVE"
    reason: str | None = None
    observation_count: int = 0
    uncensored_count: int = 0
    lineage_count: int = 0
    touched_count: int = 0
    calibration_bins: tuple[Mapping[str, float], ...] = ()
    expected_calibration_error: float = float("nan")
    brier_interval: tuple[float, float] | None = None
    log_loss_interval: tuple[float, float] | None = None
    brier_delta_upper: float | None = None
    log_loss_delta_upper: float | None = None
    sign_reversal: bool = False
    # Explicit asset/seven-day-block values are retained so null comparison
    # can pair observations instead of subtracting marginal intervals.
    brier_values_by_block: Mapping[str, tuple[float, ...]] = field(default_factory=dict)
    log_loss_values_by_block: Mapping[str, tuple[float, ...]] = field(default_factory=dict)
    block_intervals: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    paired_delta_intervals: Mapping[str, Mapping[str, tuple[float, float]]] = field(default_factory=dict)
    paired_block_results: Mapping[str, Mapping[str, Mapping[str, tuple[float, float]]]] = field(default_factory=dict)
    resolved_reversals: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # Scores are keyed by the immutable source observation identity.  Block
    # tuples remain a reporting view only; inference must pair these maps.
    brier_values_by_observation: Mapping[str, float] = field(default_factory=dict)
    log_loss_values_by_observation: Mapping[str, float] = field(default_factory=dict)
    block_by_observation: Mapping[str, str] = field(default_factory=dict)
    strata_by_observation: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


def _observation_identity(item: TargetObservation | ResearchObservation) -> str:
    if isinstance(item, ResearchObservation):
        identity = item.source_observation_id or item.observation_id
    elif isinstance(item, TargetObservation):
        identity = item.zone_id
    else:
        raise TypeError("observations must contain TargetObservation or ResearchObservation")
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError("observation source identity must be non-empty")
    return identity


def _target_values(
    observations: Iterable[TargetObservation | ResearchObservation],
    *,
    bootstrap_block: timedelta,
    bootstrap_epoch: datetime,
    matching_strata: object,
) -> tuple[tuple[TargetObservation, ...], tuple[str, ...], tuple[str, ...], tuple[tuple[str, ...], ...]]:
    selected_strata = canonical_matching_strata(matching_strata)
    targets: list[TargetObservation] = []
    blocks: list[str] = []
    identities: list[str] = []
    strata: list[tuple[str, ...]] = []
    for item in observations:
        if isinstance(item, ResearchObservation):
            target = item.require_target()
            block_label = validate_issuance_calendar_block(
                item.issued_at,
                item.issuance_calendar_block,
                block=bootstrap_block,
                epoch=bootstrap_epoch,
            )
            block = f"{item.asset}|{block_label}"
            item_strata = item.strata_key_for(selected_strata)
        elif isinstance(item, TargetObservation):
            target = item
            # The pure metric helper still has a deterministic block contract;
            # protected evaluation always supplies ResearchObservation records.
            block = f"__unbound__|{item.zone_id}"
            item_strata = ()
        else:
            raise TypeError("observations must contain TargetObservation or ResearchObservation")
        targets.append(target)
        blocks.append(block)
        identities.append(_observation_identity(item))
        strata.append(item_strata)
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate observation source identity")
    return tuple(targets), tuple(blocks), tuple(identities), tuple(strata)


def _score(
    values: tuple[TargetObservation, ...],
    probabilities: Mapping[tuple[str, object], Mapping[ForecastOutcome, float]],
) -> tuple[list[float], list[float], list[float]]:
    expected_keys = {(item.zone_id, item.horizon) for item in values}
    actual_keys = set(probabilities)
    if actual_keys != expected_keys:
        missing = expected_keys - actual_keys
        extra = actual_keys - expected_keys
        raise ValueError(
            "probability vectors must match observation identities exactly "
            f"(missing={len(missing)}, extra={len(extra)})"
        )
    brier_values: list[float] = []
    log_values: list[float] = []
    predicted_touch: list[float] = []
    for item in values:
        predicted = probabilities.get((item.zone_id, item.horizon))
        if predicted is None:
            raise ValueError("missing probability vector")
        if set(predicted) != set(ForecastOutcome):
            raise ValueError("probability vector must cover all outcomes")
        total = sum(float(value) for value in predicted.values())
        if abs(total - 1.0) > 1e-12:
            raise ValueError("probability vector must sum to one")
        brier_values.append(
            sum(
                (float(predicted[outcome]) - (1.0 if outcome is item.outcome else 0.0)) ** 2
                for outcome in ForecastOutcome
            )
        )
        log_values.append(-math.log(max(float(predicted[item.outcome]), 1e-15)))
        predicted_touch.append(
            float(
                predicted[ForecastOutcome.TOUCH_THEN_BOUNCE]
                + predicted[ForecastOutcome.TOUCH_THEN_BREAK]
                + predicted[ForecastOutcome.TOUCH_UNRESOLVED]
            )
        )
    return brier_values, log_values, predicted_touch


def _quantile_interval(samples: list[float], *, confidence: float) -> tuple[float, float] | None:
    if not samples:
        return None
    if not math.isfinite(confidence) or not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be finite and strictly between zero and one")
    samples.sort()
    alpha = (1.0 - confidence) / 2.0
    lower_index = max(0, int(alpha * len(samples)) - 1)
    upper_index = min(len(samples) - 1, int((1.0 - alpha) * len(samples)))
    return samples[lower_index], samples[upper_index]


def _bootstrap_block_interval(
    values_by_block: Mapping[str, Sequence[float]],
    *,
    repetitions: int,
    seed: str,
    confidence: float,
) -> tuple[float, float] | None:
    """Bootstrap complete asset/calendar blocks, never individual rows."""

    if repetitions <= 0:
        raise ValueError("bootstrap repetitions must be positive")
    blocks = tuple(sorted(key for key, values in values_by_block.items() if values))
    if not blocks:
        return None
    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(repetitions):
        selected = [blocks[rng.randrange(len(blocks))] for _ in blocks]
        values = [float(value) for block in selected for value in values_by_block[block]]
        samples.append(sum(values) / len(values))
    return _quantile_interval(samples, confidence=confidence)


def _validate_metric_controls(
    *,
    repetitions: int,
    seed: str,
    block: timedelta,
    epoch: datetime,
    ece_bins: int,
    confidence: float,
) -> None:
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions <= 0:
        raise ValueError("bootstrap repetitions must be a positive integer")
    if not isinstance(seed, str) or not seed.strip():
        raise ValueError("bootstrap seed must be non-empty")
    if not isinstance(block, timedelta) or block <= timedelta(0):
        raise ValueError("bootstrap block must be positive")
    require_utc(epoch, field_name="bootstrap_epoch")
    if isinstance(ece_bins, bool) or not isinstance(ece_bins, int) or ece_bins <= 0:
        raise ValueError("ECE bins must be a positive integer")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise TypeError("confidence must be a finite probability")
    if not math.isfinite(float(confidence)) or not 0.0 < float(confidence) < 1.0:
        raise ValueError("confidence must be finite and strictly between zero and one")


def _ece(
    predicted: list[float],
    values: tuple[TargetObservation, ...],
    *,
    bins: int,
) -> tuple[tuple[Mapping[str, float], ...], float]:
    if not predicted:
        return (), float("nan")
    records: list[Mapping[str, float]] = []
    total_error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        selected = [
            (probability, item)
            for probability, item in zip(predicted, values)
            if lower <= probability < upper or (index == bins - 1 and probability <= upper)
        ]
        if not selected:
            continue
        confidence = sum(item[0] for item in selected) / len(selected)
        frequency = sum(item[1].outcome is not ForecastOutcome.NO_TOUCH for item in selected) / len(selected)
        weight = len(selected) / len(values)
        total_error += weight * abs(confidence - frequency)
        records.append({"lower": lower, "upper": upper, "count": len(selected), "confidence": confidence, "frequency": frequency})
    return tuple(records), total_error


def evaluate_observations(
    observations: Iterable[TargetObservation | ResearchObservation],
    probabilities: Mapping[tuple[str, object], Mapping[ForecastOutcome, float]],
    *,
    bootstrap_repetitions: int,
    bootstrap_seed: str,
    bootstrap_block: timedelta,
    bootstrap_epoch: datetime,
    ece_bins: int,
    confidence: float,
    matching_strata: object,
) -> ResearchMetrics:
    _validate_metric_controls(
        repetitions=bootstrap_repetitions,
        seed=bootstrap_seed,
        block=bootstrap_block,
        epoch=bootstrap_epoch,
        ece_bins=ece_bins,
        confidence=confidence,
    )
    raw_values = tuple(observations)
    values, blocks, identities, strata = _target_values(
        raw_values,
        bootstrap_block=bootstrap_block,
        bootstrap_epoch=bootstrap_epoch,
        matching_strata=matching_strata,
    )
    uncensored_indices = tuple(index for index, item in enumerate(values) if not item.censored)
    uncensored = tuple(values[index] for index in uncensored_indices)
    uncensored_blocks = tuple(blocks[index] for index in uncensored_indices)
    uncensored_strata = tuple(strata[index] for index in uncensored_indices)
    counts = Counter(item.outcome.value for item in values)
    if not values:
        if probabilities:
            raise ValueError("probability vectors contain extra observation identities")
        return ResearchMetrics(
            sample_count=0,
            observation_count=0,
            uncensored_count=0,
            lineage_count=0,
            touched_count=0,
            outcome_counts={},
            brier=float("nan"),
            multiclass_log_loss=float("nan"),
            censoring_rate=0.0,
            ambiguity_rate=0.0,
            reason="no observations",
        )
    brier_values, log_values, predicted_touch = _score(uncensored, probabilities)
    brier_by_block: dict[str, list[float]] = defaultdict(list)
    log_by_block: dict[str, list[float]] = defaultdict(list)
    uncensored_identities = tuple(identities[index] for index in uncensored_indices)
    scored = sorted(
        zip(uncensored_identities, uncensored_blocks, uncensored_strata, brier_values, log_values),
        key=lambda item: item[0],
    )
    brier_by_observation = {identity: brier for identity, _, _, brier, _ in scored}
    log_by_observation = {identity: log_loss for identity, _, _, _, log_loss in scored}
    block_by_observation = {identity: block for identity, block, _, _, _ in scored}
    strata_by_observation = {identity: item_strata for identity, _, item_strata, _, _ in scored}
    for _, block, _, brier, log_loss in scored:
        brier_by_block[block].append(brier)
        log_by_block[block].append(log_loss)
    brier_by_block_tuple = {key: tuple(value) for key, value in sorted(brier_by_block.items())}
    log_by_block_tuple = {key: tuple(value) for key, value in sorted(log_by_block.items())}
    bins, ece = _ece(predicted_touch, uncensored, bins=ece_bins)
    block_intervals: dict[str, tuple[float, float]] = {}
    for key, block_values in brier_by_block_tuple.items():
        interval = _bootstrap_block_interval(
            {key: block_values},
            repetitions=bootstrap_repetitions,
            seed=f"{bootstrap_seed}:{key}",
            confidence=confidence,
        )
        if interval is not None:
            block_intervals[key] = interval
    return ResearchMetrics(
        sample_count=len(uncensored),
        observation_count=len(values),
        uncensored_count=len(uncensored),
        lineage_count=len({item.zone_id for item in values}),
        touched_count=sum(item.touch_at is not None for item in values),
        outcome_counts=dict(counts),
        brier=(sum(brier_values) / len(brier_values) if brier_values else float("nan")),
        multiclass_log_loss=(sum(log_values) / len(log_values) if log_values else float("nan")),
        censoring_rate=sum(item.censored for item in values) / len(values),
        ambiguity_rate=sum(item.ambiguous for item in values) / len(values),
        calibration_bins=bins,
        expected_calibration_error=ece,
        brier_interval=_bootstrap_block_interval(
            brier_by_block_tuple,
            repetitions=bootstrap_repetitions,
            seed=f"{bootstrap_seed}:brier",
            confidence=confidence,
        ),
        log_loss_interval=_bootstrap_block_interval(
            log_by_block_tuple,
            repetitions=bootstrap_repetitions,
            seed=f"{bootstrap_seed}:log",
            confidence=confidence,
        ),
        brier_values_by_block=brier_by_block_tuple,
        log_loss_values_by_block=log_by_block_tuple,
        brier_values_by_observation=brier_by_observation,
        log_loss_values_by_observation=log_by_observation,
        block_by_observation=block_by_observation,
        strata_by_observation=strata_by_observation,
        block_intervals=block_intervals,
        reason=("censored observations excluded from ordinary scores" if len(uncensored) < len(values) else None),
    )


def _paired_block_intervals(
    primary_values: Mapping[str, float],
    null_values: Mapping[str, float],
    primary_blocks: Mapping[str, str],
    null_blocks: Mapping[str, str],
    primary_strata: Mapping[str, tuple[str, ...]],
    null_strata: Mapping[str, tuple[str, ...]],
    *,
    repetitions: int,
    seed: str,
    confidence: float,
) -> tuple[tuple[float, float] | None, dict[str, tuple[float, ...]]]:
    primary_ids = set(primary_values)
    null_ids = set(null_values)
    if not primary_ids or primary_ids != null_ids:
        raise ValueError("paired scores require an exact source_observation_id match")
    if set(primary_blocks) != primary_ids or set(null_blocks) != null_ids:
        raise ValueError("paired scores require one block for every source_observation_id")
    if set(primary_strata) != primary_ids or set(null_strata) != null_ids:
        raise ValueError("paired scores require one configured strata key for every source_observation_id")
    deltas_by_block: dict[str, list[float]] = defaultdict(list)
    for source_id in sorted(primary_ids):
        primary_block = primary_blocks[source_id]
        null_block = null_blocks[source_id]
        if primary_block != null_block:
            raise ValueError("paired scores require identical calendar block keys")
        if primary_strata[source_id] != null_strata[source_id]:
            raise ValueError("paired scores require identical configured strata keys")
        deltas_by_block[primary_block].append(
            float(primary_values[source_id]) - float(null_values[source_id])
        )
    deltas = {block: tuple(values) for block, values in sorted(deltas_by_block.items())}
    return (
        _bootstrap_block_interval(deltas, repetitions=repetitions, seed=seed, confidence=confidence),
        deltas,
    )


def compare_against_nulls(
    primary: ResearchMetrics,
    nulls: Mapping[str, ResearchMetrics],
    *,
    bootstrap_repetitions: int,
    bootstrap_seed: str,
    confidence: float,
) -> ResearchMetrics:
    """Attach paired matched-block deltas; marginal interval subtraction is forbidden."""

    if not isinstance(primary, ResearchMetrics):
        raise TypeError("primary must be ResearchMetrics")
    if not nulls:
        raise ValueError("at least one matched null is required")
    paired: dict[str, Mapping[str, tuple[float, float]]] = {}
    paired_blocks: dict[str, Mapping[str, Mapping[str, tuple[float, float]]]] = {}
    reversals: dict[str, tuple[str, ...]] = {}
    brier_uppers: list[float] = []
    log_uppers: list[float] = []
    for name, metric in sorted(nulls.items()):
        brier_interval, brier_deltas = _paired_block_intervals(
            primary.brier_values_by_observation,
            metric.brier_values_by_observation,
            primary.block_by_observation,
            metric.block_by_observation,
            primary.strata_by_observation,
            metric.strata_by_observation,
            repetitions=bootstrap_repetitions,
            seed=f"{bootstrap_seed}:{name}:brier",
            confidence=confidence,
        )
        log_interval, log_deltas = _paired_block_intervals(
            primary.log_loss_values_by_observation,
            metric.log_loss_values_by_observation,
            primary.block_by_observation,
            metric.block_by_observation,
            primary.strata_by_observation,
            metric.strata_by_observation,
            repetitions=bootstrap_repetitions,
            seed=f"{bootstrap_seed}:{name}:log",
            confidence=confidence,
        )
        if brier_interval is None or log_interval is None:
            continue
        paired[name] = {"brier": brier_interval, "log_loss": log_interval}
        common_blocks = sorted(set(brier_deltas) & set(log_deltas))
        paired_blocks[name] = {
            block: {
                "brier": block_interval,
                "log_loss": log_interval_for_block,
            }
            for block in common_blocks
            for block_interval, log_interval_for_block in [
                (
                    _bootstrap_block_interval(
                        {block: brier_deltas[block]},
                        repetitions=bootstrap_repetitions,
                        seed=f"{bootstrap_seed}:{name}:{block}:brier",
                        confidence=confidence,
                    ),
                    _bootstrap_block_interval(
                        {block: log_deltas[block]},
                        repetitions=bootstrap_repetitions,
                        seed=f"{bootstrap_seed}:{name}:{block}:log",
                        confidence=confidence,
                    ),
                )
            ]
            if block_interval is not None and log_interval_for_block is not None
        }
        brier_uppers.append(brier_interval[1])
        log_uppers.append(log_interval[1])
        resolved: list[str] = []
        if brier_interval[0] > 0:
            resolved.append("aggregate:brier")
        if log_interval[0] > 0:
            resolved.append("aggregate:log_loss")
        for block, block_intervals in paired_blocks[name].items():
            if block_intervals["brier"][0] > 0:
                resolved.append(f"{block}:brier")
            if block_intervals["log_loss"][0] > 0:
                resolved.append(f"{block}:log_loss")
        if resolved:
            reversals[name] = tuple(resolved)
    if not paired:
        return replace(
            primary,
            reason="matched block deltas are incomplete",
            brier_delta_upper=None,
            log_loss_delta_upper=None,
            sign_reversal=False,
            paired_delta_intervals={},
            paired_block_results={},
            resolved_reversals={},
        )
    return replace(
        primary,
        brier_delta_upper=max(brier_uppers),
        log_loss_delta_upper=max(log_uppers),
        sign_reversal=bool(reversals),
        paired_delta_intervals=paired,
        paired_block_results=paired_blocks,
        resolved_reversals=reversals,
    )


__all__ = [
    "ResearchMetrics",
    "compare_against_nulls",
    "evaluate_observations",
]
