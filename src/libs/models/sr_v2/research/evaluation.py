"""Calibration-free, development-only evaluation of scientific SR v2 labels."""

from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from types import MappingProxyType

from ..contracts import require_utc
from ..domain.identity import canonical_hash
from ..forecast.targets import ScientificReaction
from ..research.observations import canonical_issuance_calendar_block
from ..research_lab.scientific_compiler import (
    CompiledScientificSet,
    ScientificGroupKey,
    ScientificObservation,
)


class DevelopmentStatus(str, Enum):
    """The only statuses emitted by Package-1 development evaluation."""

    INVALID = "INVALID"
    INSUFFICIENT = "INSUFFICIENT"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True, kw_only=True)
class DevelopmentForecast:
    """One typed probability vector bound to one scientific observation."""

    observation_id: str
    group: ScientificGroupKey
    issued_at: datetime
    source_manifest_id: str
    source_sha256: str
    touch_probability: float
    bounce_probability: float
    break_probability: float

    def __post_init__(self) -> None:
        if not isinstance(self.observation_id, str) or not self.observation_id.strip():
            raise ValueError("observation_id must be non-empty")
        if not isinstance(self.group, ScientificGroupKey):
            raise TypeError("group must be ScientificGroupKey")
        require_utc(self.issued_at, field_name="issued_at")
        for name in ("source_manifest_id", "source_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class DevelopmentEvaluationControls:
    """Explicit support and joint-calendar bootstrap controls."""

    expected_groups: tuple[ScientificGroupKey, ...]
    minimum_uncensored_lineages: int
    minimum_touched_lineages: int
    bootstrap_repetitions: int
    bootstrap_seed: str
    bootstrap_block: timedelta
    bootstrap_epoch: datetime
    confidence: float
    ece_bins: int
    source_manifest_id: str
    source_sha256: str

    def __post_init__(self) -> None:
        groups = tuple(sorted(self.expected_groups))
        if not groups or any(
            not isinstance(group, ScientificGroupKey) for group in groups
        ):
            raise TypeError("expected_groups must contain ScientificGroupKey values")
        if len(set(groups)) != len(groups):
            raise ValueError("expected_groups must be unique")
        _positive_int(self.minimum_uncensored_lineages, "minimum_uncensored_lineages")
        _positive_int(self.minimum_touched_lineages, "minimum_touched_lineages")
        _positive_int(self.bootstrap_repetitions, "bootstrap_repetitions")
        _positive_int(self.ece_bins, "ece_bins")
        if not isinstance(self.bootstrap_seed, str) or not self.bootstrap_seed.strip():
            raise ValueError("bootstrap_seed must be non-empty")
        if not isinstance(
            self.bootstrap_block, timedelta
        ) or self.bootstrap_block <= timedelta(0):
            raise ValueError("bootstrap_block must be positive")
        require_utc(self.bootstrap_epoch, field_name="bootstrap_epoch")
        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise TypeError("confidence must be a finite probability")
        if (
            not math.isfinite(float(self.confidence))
            or not 0.0 < float(self.confidence) < 1.0
        ):
            raise ValueError("confidence must be strictly between zero and one")
        for name in ("source_manifest_id", "source_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        object.__setattr__(self, "expected_groups", groups)


@dataclass(frozen=True, slots=True, kw_only=True)
class DevelopmentGroupMetrics:
    """Independent metrics and evidence counts for one expected group."""

    group: ScientificGroupKey
    status: DevelopmentStatus
    reason: str | None
    observation_count: int
    uncensored_count: int
    touched_count: int
    reaction_count: int
    cutoff_count: int
    touch_brier: float
    touch_log_loss: float
    reaction_brier: float
    reaction_log_loss: float
    touch_interval: tuple[float, float] | None = None
    reaction_interval: tuple[float, float] | None = None
    calendar_blocks: tuple[str, ...] = ()
    calibration_bins: tuple[dict[str, float], ...] = ()
    expected_calibration_error: float = float("nan")


@dataclass(frozen=True, slots=True, kw_only=True)
class DevelopmentEvaluationReport:
    """A report that cannot encode POSITIVE, NEGATIVE, or promotion."""

    status: DevelopmentStatus
    expected_groups: tuple[ScientificGroupKey, ...]
    metrics_by_group: dict[ScientificGroupKey, DevelopmentGroupMetrics]
    source_manifest_id: str
    source_sha256: str
    reason: str | None
    calendar_blocks: tuple[str, ...]
    macro_touch_brier: float
    macro_reaction_brier: float
    macro_touch_interval: tuple[float, float] | None
    macro_reaction_interval: tuple[float, float] | None
    report_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, DevelopmentStatus):
            raise TypeError("status must be DevelopmentStatus")
        object.__setattr__(self, "expected_groups", tuple(self.expected_groups))
        object.__setattr__(
            self, "metrics_by_group", MappingProxyType(dict(self.metrics_by_group))
        )
        object.__setattr__(self, "calendar_blocks", tuple(self.calendar_blocks))


def _positive_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _probability(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a finite probability")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite probability") from exc
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be a finite probability in [0, 1]")
    return result


def _forecast_map(
    forecasts: Sequence[DevelopmentForecast],
) -> dict[str, DevelopmentForecast]:
    result: dict[str, DevelopmentForecast] = {}
    for forecast in forecasts:
        if not isinstance(forecast, DevelopmentForecast):
            raise TypeError("forecasts must contain DevelopmentForecast values")
        if forecast.observation_id in result:
            raise ValueError("forecast identities must be unique")
        result[forecast.observation_id] = forecast
    return result


def _probabilities(forecast: DevelopmentForecast) -> tuple[float, float, float]:
    touch = _probability(forecast.touch_probability, "touch_probability")
    bounce = _probability(forecast.bounce_probability, "bounce_probability")
    break_probability = _probability(forecast.break_probability, "break_probability")
    if abs(bounce + break_probability - 1.0) > 1e-9:
        raise ValueError("reaction probabilities must sum to one")
    return touch, bounce, break_probability


def _block(issued_at: datetime, controls: DevelopmentEvaluationControls) -> str:
    return canonical_issuance_calendar_block(
        issued_at,
        block=controls.bootstrap_block,
        epoch=controls.bootstrap_epoch,
    )


def _cutoff_mean(rows: Sequence[tuple[datetime, float]]) -> float:
    by_cutoff: dict[datetime, list[float]] = defaultdict(list)
    for cutoff, value in rows:
        by_cutoff[cutoff].append(value)
    if not by_cutoff:
        return float("nan")
    cutoff_means = tuple(
        sum(values) / len(values) for _, values in sorted(by_cutoff.items())
    )
    return sum(cutoff_means) / len(cutoff_means)


def _score_rows(
    rows: Sequence[tuple[datetime, float, bool]],
) -> tuple[float, float]:
    brier = tuple(
        (at, (probability - float(actual)) ** 2) for at, probability, actual in rows
    )
    log_loss = tuple(
        (at, -math.log(max(probability if actual else 1.0 - probability, 1e-15)))
        for at, probability, actual in rows
    )
    return _cutoff_mean(brier), _cutoff_mean(log_loss)


def _calibration(
    rows: Sequence[tuple[datetime, float, bool]],
    bins: int,
) -> tuple[tuple[dict[str, float], ...], float]:
    if not rows:
        return (), float("nan")
    result: list[dict[str, float]] = []
    error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        selected = [
            (probability, actual)
            for _, probability, actual in rows
            if lower <= probability < upper
            or index == bins - 1
            and probability <= upper
        ]
        if not selected:
            continue
        confidence = sum(probability for probability, _ in selected) / len(selected)
        frequency = sum(actual for _, actual in selected) / len(selected)
        error += len(selected) / len(rows) * abs(confidence - frequency)
        result.append(
            {
                "lower": lower,
                "upper": upper,
                "count": float(len(selected)),
                "confidence": confidence,
                "frequency": frequency,
            }
        )
    return tuple(result), error


def bootstrap_joint_calendar_blocks(
    issued_at_by_group: dict[ScientificGroupKey, Sequence[datetime]],
    *,
    repetitions: int,
    seed: str,
    block: timedelta,
    epoch: datetime,
) -> tuple[tuple[str, ...], ...]:
    """Draw shared UTC calendar-block slots with replacement.

    Repeated labels remain repeated slots in each draw.  Asset is absent from a
    label by construction, so every asset/group receives the same draw.  With
    one available block there is no inferential interval to report.
    """

    _positive_int(repetitions, "repetitions")
    if not isinstance(seed, str) or not seed.strip():
        raise ValueError("seed must be non-empty")
    if not isinstance(block, timedelta) or block <= timedelta(0):
        raise ValueError("block must be positive")
    require_utc(epoch, field_name="epoch")
    labels = sorted(
        {
            canonical_issuance_calendar_block(value, block=block, epoch=epoch)
            for values in issued_at_by_group.values()
            for value in values
        }
    )
    if len(labels) <= 1:
        return ()
    rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest(), 16))
    return tuple(
        tuple(labels[rng.randrange(len(labels))] for _ in labels)
        for _ in range(repetitions)
    )


def _sample_metric(
    rows: Sequence[tuple[datetime, float, bool, str]],
    slots: Sequence[str],
) -> float | None:
    by_block: dict[str, list[tuple[datetime, float, bool]]] = defaultdict(list)
    for at, probability, actual, label in rows:
        by_block[label].append((at, probability, actual))
    slot_scores: list[float] = []
    for label in slots:
        selected = by_block.get(label, ())
        if not selected:
            continue
        slot_scores.append(_score_rows(tuple(selected))[0])
    return sum(slot_scores) / len(slot_scores) if slot_scores else None


def _intervals(
    rows_by_group: dict[
        ScientificGroupKey, Sequence[tuple[datetime, float, bool, str]]
    ],
    draws: Sequence[Sequence[str]],
    confidence: float,
) -> dict[ScientificGroupKey, tuple[float, float] | None]:
    result: dict[ScientificGroupKey, tuple[float, float] | None] = {}
    for group, rows in rows_by_group.items():
        samples = [
            value
            for slots in draws
            if (value := _sample_metric(rows, slots)) is not None
        ]
        if not samples:
            result[group] = None
            continue
        ordered = sorted(samples)
        alpha = (1.0 - confidence) / 2.0
        lower = min(len(ordered) - 1, max(0, math.floor(alpha * len(ordered))))
        upper = min(
            len(ordered) - 1, max(0, math.ceil((1.0 - alpha) * len(ordered)) - 1)
        )
        result[group] = ordered[lower], ordered[upper]
    return result


def _macro_interval(
    rows_by_group: dict[
        ScientificGroupKey, Sequence[tuple[datetime, float, bool, str]]
    ],
    draws: Sequence[Sequence[str]],
    confidence: float,
) -> tuple[float, float] | None:
    samples: list[float] = []
    groups = tuple(sorted(rows_by_group))
    for slots in draws:
        values = tuple(_sample_metric(rows_by_group[group], slots) for group in groups)
        if all(value is not None for value in values):
            samples.append(
                sum(value for value in values if value is not None) / len(values)
            )
    if not samples:
        return None
    ordered = sorted(samples)
    alpha = (1.0 - confidence) / 2.0
    lower = min(len(ordered) - 1, max(0, math.floor(alpha * len(ordered))))
    upper = min(len(ordered) - 1, max(0, math.ceil((1.0 - alpha) * len(ordered)) - 1))
    return ordered[lower], ordered[upper]


def _invalid(
    group: ScientificGroupKey, reason: str, count: int = 0
) -> DevelopmentGroupMetrics:
    return DevelopmentGroupMetrics(
        group=group,
        status=DevelopmentStatus.INVALID,
        reason=reason,
        observation_count=count,
        uncensored_count=0,
        touched_count=0,
        reaction_count=0,
        cutoff_count=0,
        touch_brier=float("nan"),
        touch_log_loss=float("nan"),
        reaction_brier=float("nan"),
        reaction_log_loss=float("nan"),
    )


def evaluate_development(
    compiled: CompiledScientificSet,
    forecasts: Sequence[DevelopmentForecast],
    controls: DevelopmentEvaluationControls,
) -> DevelopmentEvaluationReport:
    """Score Package-1 probabilities while preserving all evidence boundaries."""

    if not isinstance(compiled, CompiledScientificSet):
        raise TypeError("compiled must be CompiledScientificSet")
    if not isinstance(controls, DevelopmentEvaluationControls):
        raise TypeError("controls must be DevelopmentEvaluationControls")
    reasons: list[str] = []
    expected = controls.expected_groups
    if compiled.expected_groups != expected:
        reasons.append("controls must cover the exact compiled expected group ontology")
    if compiled.source_manifest_id != controls.source_manifest_id:
        reasons.append("compiled source manifest does not match controls")
    if compiled.source_sha256 != controls.source_sha256:
        reasons.append("compiled source digest does not match controls")
    try:
        forecast_by_id = _forecast_map(forecasts)
    except (TypeError, ValueError) as exc:
        forecast_by_id = {}
        reasons.append(str(exc))
    observation_ids = {
        observation.observation_id for observation in compiled.observations
    }
    if observation_ids != set(forecast_by_id):
        reasons.append(
            "forecast identities differ from compiled observations "
            f"(missing={len(observation_ids - set(forecast_by_id))}, extra={len(set(forecast_by_id) - observation_ids)})"
        )
    by_group: dict[ScientificGroupKey, list[ScientificObservation]] = defaultdict(list)
    for observation in compiled.observations:
        by_group[observation.group].append(observation)
        if (
            observation.source_manifest_id != compiled.source_manifest_id
            or observation.source_sha256 != compiled.source_sha256
        ):
            reasons.append(
                f"observation source identity mismatch for {observation.observation_id}"
            )
    metrics: dict[ScientificGroupKey, DevelopmentGroupMetrics] = {}
    touch_rows: dict[ScientificGroupKey, list[tuple[datetime, float, bool, str]]] = {}
    reaction_rows: dict[
        ScientificGroupKey, list[tuple[datetime, float, bool, str]]
    ] = {}
    for group in expected:
        observations = tuple(
            sorted(by_group.get(group, ()), key=lambda item: item.observation_id)
        )
        if not observations:
            metrics[group] = _invalid(
                group, "expected group has no compiled observations"
            )
            continue
        invalid_reasons: list[str] = []
        touch_values: list[tuple[datetime, float, bool, str]] = []
        reaction_values: list[tuple[datetime, float, bool, str]] = []
        touched_ids: set[str] = set()
        blocks: set[str] = set()
        for observation in observations:
            if (
                not observation.feasible_null.complete
                or observation.feasible_null.zone is None
                or observation.null_target is None
            ):
                invalid_reasons.append(
                    f"required feasible null unavailable for {observation.observation_id}"
                )
            forecast = forecast_by_id.get(observation.observation_id)
            if forecast is None:
                invalid_reasons.append(
                    f"missing forecast for {observation.observation_id}"
                )
                continue
            if forecast.group != observation.group:
                invalid_reasons.append(
                    f"forecast group mismatch for {observation.observation_id}"
                )
            if forecast.issued_at != observation.issued_at:
                invalid_reasons.append(
                    f"forecast issuance mismatch for {observation.observation_id}"
                )
            if (
                forecast.source_manifest_id != observation.source_manifest_id
                or forecast.source_sha256 != observation.source_sha256
            ):
                invalid_reasons.append(
                    f"forecast source identity mismatch for {observation.observation_id}"
                )
            try:
                touch_probability, bounce_probability, _ = _probabilities(forecast)
            except (TypeError, ValueError) as exc:
                invalid_reasons.append(
                    f"malformed probability for {observation.observation_id}: {exc}"
                )
                continue
            label = _block(observation.issued_at, controls)
            blocks.add(label)
            target = observation.target.view
            if target.touch is not None and not target.censored:
                touch_values.append(
                    (
                        observation.issued_at,
                        touch_probability,
                        target.touch is True,
                        label,
                    )
                )
                if target.touch is True:
                    touched_ids.add(observation.observation_id)
            if (
                target.reaction_eligible
                and target.reaction is not None
                and target.touch is True
                and not target.censored
            ):
                reaction_values.append(
                    (
                        observation.issued_at,
                        bounce_probability,
                        target.reaction is ScientificReaction.BOUNCE,
                        label,
                    )
                )
        if invalid_reasons or reasons:
            metrics[group] = _invalid(
                group,
                "; ".join(sorted(set(invalid_reasons + reasons))),
                len(observations),
            )
            continue
        if (
            len(touch_values) < controls.minimum_uncensored_lineages
            or len(touched_ids) < controls.minimum_touched_lineages
        ):
            metrics[group] = DevelopmentGroupMetrics(
                group=group,
                status=DevelopmentStatus.INSUFFICIENT,
                reason=(
                    f"support below controls: uncensored={len(touch_values)}/"
                    f"{controls.minimum_uncensored_lineages}, touched={len(touched_ids)}/"
                    f"{controls.minimum_touched_lineages}"
                ),
                observation_count=len(observations),
                uncensored_count=len(touch_values),
                touched_count=len(touched_ids),
                reaction_count=len(reaction_values),
                cutoff_count=len({row[0] for row in touch_values}),
                touch_brier=float("nan"),
                touch_log_loss=float("nan"),
                reaction_brier=float("nan"),
                reaction_log_loss=float("nan"),
                calendar_blocks=tuple(sorted(blocks)),
            )
            continue
        touch_rows[group] = touch_values
        reaction_rows[group] = reaction_values
        touch_brier, touch_log_loss = _score_rows(
            tuple(
                (at, probability, actual) for at, probability, actual, _ in touch_values
            )
        )
        reaction_brier, reaction_log_loss = _score_rows(
            tuple(
                (at, probability, actual)
                for at, probability, actual, _ in reaction_values
            )
        )
        calibration_bins, ece = _calibration(
            tuple(
                (at, probability, actual) for at, probability, actual, _ in touch_values
            ),
            controls.ece_bins,
        )
        metrics[group] = DevelopmentGroupMetrics(
            group=group,
            status=DevelopmentStatus.INCONCLUSIVE,
            reason="Package-1 development evidence cannot establish promotion",
            observation_count=len(observations),
            uncensored_count=len(touch_values),
            touched_count=len(touched_ids),
            reaction_count=len(reaction_values),
            cutoff_count=len({row[0] for row in touch_values}),
            touch_brier=touch_brier,
            touch_log_loss=touch_log_loss,
            reaction_brier=reaction_brier,
            reaction_log_loss=reaction_log_loss,
            calendar_blocks=tuple(sorted(blocks)),
            calibration_bins=calibration_bins,
            expected_calibration_error=ece,
        )
    all_issued = {
        group: tuple(observation.issued_at for observation in observations)
        for group, observations in by_group.items()
    }
    draws = bootstrap_joint_calendar_blocks(
        all_issued,
        repetitions=controls.bootstrap_repetitions,
        seed=controls.bootstrap_seed,
        block=controls.bootstrap_block,
        epoch=controls.bootstrap_epoch,
    )
    touch_interval_by_group = _intervals(touch_rows, draws, controls.confidence)
    reaction_interval_by_group = _intervals(reaction_rows, draws, controls.confidence)
    for group, metric in tuple(metrics.items()):
        if metric.status is DevelopmentStatus.INCONCLUSIVE:
            metrics[group] = DevelopmentGroupMetrics(
                group=metric.group,
                status=metric.status,
                reason=metric.reason,
                observation_count=metric.observation_count,
                uncensored_count=metric.uncensored_count,
                touched_count=metric.touched_count,
                reaction_count=metric.reaction_count,
                cutoff_count=metric.cutoff_count,
                touch_brier=metric.touch_brier,
                touch_log_loss=metric.touch_log_loss,
                reaction_brier=metric.reaction_brier,
                reaction_log_loss=metric.reaction_log_loss,
                touch_interval=touch_interval_by_group.get(group),
                reaction_interval=reaction_interval_by_group.get(group),
                calendar_blocks=metric.calendar_blocks,
                calibration_bins=metric.calibration_bins,
                expected_calibration_error=metric.expected_calibration_error,
            )
    statuses = tuple(metric.status for metric in metrics.values())
    if reasons or any(status is DevelopmentStatus.INVALID for status in statuses):
        status = DevelopmentStatus.INVALID
    elif any(status is DevelopmentStatus.INSUFFICIENT for status in statuses):
        status = DevelopmentStatus.INSUFFICIENT
    else:
        status = DevelopmentStatus.INCONCLUSIVE
    sound = status is DevelopmentStatus.INCONCLUSIVE
    sound_metrics = tuple(
        metric
        for metric in metrics.values()
        if metric.status is DevelopmentStatus.INCONCLUSIVE
    )
    macro_touch = (
        sum(metric.touch_brier for metric in sound_metrics) / len(sound_metrics)
        if sound
        else float("nan")
    )
    reaction_metrics = tuple(
        metric for metric in sound_metrics if math.isfinite(metric.reaction_brier)
    )
    macro_reaction = (
        sum(metric.reaction_brier for metric in reaction_metrics)
        / len(reaction_metrics)
        if sound and reaction_metrics
        else float("nan")
    )
    macro_touch_interval = (
        _macro_interval(touch_rows, draws, controls.confidence) if sound else None
    )
    macro_reaction_interval = (
        _macro_interval(reaction_rows, draws, controls.confidence)
        if sound
        and reaction_rows
        and all(reaction_rows.get(group) for group in metrics)
        else None
    )
    labels = tuple(
        sorted(
            {
                _block(issued_at, controls)
                for values in all_issued.values()
                for issued_at in values
            }
        )
    )
    metric_reasons = tuple(
        metric.reason
        for metric in metrics.values()
        if metric.status is DevelopmentStatus.INVALID and metric.reason
    )
    report_reasons = tuple(sorted(set(reasons).union(metric_reasons)))
    report_reason = "; ".join(report_reasons) if report_reasons else None
    report_fingerprint = canonical_hash(
        {
            "schema": "sr_v2.development_evaluation@2",
            "status": status.value,
            "source_manifest_id": compiled.source_manifest_id,
            "source_sha256": compiled.source_sha256,
            "groups": expected,
            "observation_ids": tuple(sorted(observation_ids)),
            "forecast_ids": tuple(sorted(forecast_by_id)),
            "controls": controls,
        }
    )
    return DevelopmentEvaluationReport(
        status=status,
        expected_groups=expected,
        metrics_by_group=metrics,
        source_manifest_id=compiled.source_manifest_id,
        source_sha256=compiled.source_sha256,
        reason=report_reason,
        calendar_blocks=labels,
        macro_touch_brier=macro_touch,
        macro_reaction_brier=macro_reaction,
        macro_touch_interval=macro_touch_interval,
        macro_reaction_interval=macro_reaction_interval,
        report_fingerprint=report_fingerprint,
    )


__all__ = [
    "DevelopmentEvaluationControls",
    "DevelopmentEvaluationReport",
    "DevelopmentForecast",
    "DevelopmentGroupMetrics",
    "DevelopmentStatus",
    "bootstrap_joint_calendar_blocks",
    "evaluate_development",
]
