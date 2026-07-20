"""Interaction/event-only replay over immutable source family snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..configuration.contracts import ResolvedTrendlineFamilyConfig
from ..contracts import ContractValidationError, InteractionEventState, TrendlineFamilySnapshot
from ..event_lifecycle import advance_interaction_events
from ..interactions import calculate_interaction_atr, evaluate_family_interaction
from ..repository import InMemoryTrendlineFamilyRepository
from ..tracker import TrendlineFamilyTracker
from .contracts import InteractionEvaluationSpec, MetricRecord, StageEvaluationSpec, TrialConfig, WindowResult, semantic_id
from .evaluator import run_stage_grid
from .folds import HoldoutPlan, ImmutableHistoricalFrame, WalkForwardFold
from .metrics import binary_classification_metrics, ratio_metric
from .tracker_optimizer import FrozenCandidateStream, _FrozenCandidateProvider


@dataclass(frozen=True)
class FrozenFamilySnapshotRecord:
    timestamp: datetime
    snapshot: TrendlineFamilySnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime) or self.timestamp.tzinfo is None or self.timestamp.utcoffset().total_seconds() != 0:
            raise ContractValidationError("frozen source snapshot timestamp must be UTC")
        if not isinstance(self.snapshot, TrendlineFamilySnapshot) or self.snapshot.timestamp != self.timestamp:
            raise ContractValidationError("frozen source snapshot must bind its timestamp")


@dataclass(frozen=True)
class FrozenFamilySnapshotStream:
    asset: str
    timeframe: str
    dataset_hash: str
    candidate_stream_id: str
    records: tuple[FrozenFamilySnapshotRecord, ...]
    stream_id: str | None = None

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.asset, self.timeframe, self.dataset_hash, self.candidate_stream_id)):
            raise ContractValidationError("frozen source stream identity fields must be non-empty")
        records = tuple(self.records)
        if not records or any(not isinstance(record, FrozenFamilySnapshotRecord) for record in records):
            raise ContractValidationError("frozen source stream requires snapshot records")
        if tuple(record.timestamp for record in records) != tuple(sorted(record.timestamp for record in records)):
            raise ContractValidationError("frozen source stream requires ordered timestamps")
        object.__setattr__(self, "records", records)
        expected = semantic_id("trendline-family-frozen-source-snapshots", self.identity_payload())
        if self.stream_id is not None and self.stream_id != expected:
            raise ContractValidationError("frozen source stream ID does not match snapshots")
        object.__setattr__(self, "stream_id", expected)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "dataset_hash": self.dataset_hash,
            "candidate_stream_id": self.candidate_stream_id,
            "snapshot_ids": [(record.timestamp, record.snapshot.snapshot_id) for record in self.records],
        }

    def snapshot_at(self, timestamp: datetime) -> TrendlineFamilySnapshot:
        for record in self.records:
            if record.timestamp == timestamp:
                return record.snapshot
        raise ContractValidationError("frozen source stream has no snapshot for timestamp")


def build_frozen_family_snapshot_stream(
    *,
    dataset: ImmutableHistoricalFrame,
    config: ResolvedTrendlineFamilyConfig,
    candidate_stream: FrozenCandidateStream,
) -> FrozenFamilySnapshotStream:
    """Persist Phase-G-style source snapshots once; interaction trials never rerun matching."""

    if dataset.dataset_hash != candidate_stream.dataset_hash or dataset.asset != config.asset or dataset.timeframe != config.timeframe:
        raise ContractValidationError("frozen source construction identity mismatch")
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=_FrozenCandidateProvider(candidate_stream),
        config=config,
    )
    records = tuple(
        FrozenFamilySnapshotRecord(
            timestamp=timestamp,
            snapshot=tracker.update(dataset.prefix(position), observed_at=timestamp).snapshot,
        )
        for position, timestamp in enumerate(dataset.timestamps)
    )
    return FrozenFamilySnapshotStream(
        asset=dataset.asset,
        timeframe=dataset.timeframe,
        dataset_hash=dataset.dataset_hash,
        candidate_stream_id=candidate_stream.stream_id,
        records=records,
    )


@dataclass(frozen=True)
class InteractionOutcomePolicy:
    """Typed caller-supplied labels for event classification evaluation only."""

    label_column: str
    target_event_state: InteractionEventState = InteractionEventState.BREAK_CONFIRMED
    policy_version: str = "interaction_label_policy_v1"

    def __post_init__(self) -> None:
        if not isinstance(self.label_column, str) or not self.label_column:
            raise ContractValidationError("interaction label_column must be non-empty")
        if not isinstance(self.target_event_state, InteractionEventState):
            object.__setattr__(self, "target_event_state", InteractionEventState(self.target_event_state))
        if not isinstance(self.policy_version, str) or not self.policy_version:
            raise ContractValidationError("interaction policy_version must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "label_column": self.label_column,
            "target_event_state": self.target_event_state.value,
            "policy_version": self.policy_version,
        }


class InteractionEvaluator:
    """Evaluate event parameters from fixed upstream geometry and lifecycle source state."""

    def __init__(
        self,
        *,
        dataset: ImmutableHistoricalFrame,
        source_snapshots: FrozenFamilySnapshotStream,
        outcome_policy: InteractionOutcomePolicy | None = None,
        tick_size: float | None = None,
    ) -> None:
        if dataset.dataset_hash != source_snapshots.dataset_hash:
            raise ContractValidationError("interaction dataset/source snapshot hash mismatch")
        if outcome_policy is not None and outcome_policy.label_column not in dataset.to_frame().columns:
            raise ContractValidationError("interaction label column is absent from immutable dataset")
        self.dataset = dataset
        self.source_snapshots = source_snapshots
        self.outcome_policy = outcome_policy
        self.tick_size = tick_size

    def evaluation_spec(self) -> StageEvaluationSpec:
        return InteractionEvaluationSpec(
            frozen_source_snapshot_stream_id=self.source_snapshots.stream_id,
            outcome_policy=None if self.outcome_policy is None else self.outcome_policy.to_dict(),
            tick_size=self.tick_size,
        ).to_stage_spec()

    def __call__(
        self,
        trial: TrialConfig,
        config: ResolvedTrendlineFamilyConfig,
        window: WalkForwardFold | HoldoutPlan,
        window_kind: str,
    ) -> WindowResult:
        if trial.stage.value != "interaction":
            raise ContractValidationError("interaction evaluator only accepts interaction trials")
        bounds = window.validation if isinstance(window, WalkForwardFold) else window.window
        replay_start = window.warmup.start_position
        frame = self.dataset.to_frame()
        prior_events = ()
        observations = []
        events = []
        labels: list[bool] = []
        predictions: list[bool] = []
        role_reset_count = 0
        for position in range(replay_start, bounds.end_position + 1):
            timestamp = self.dataset.timestamps[position]
            source = self.source_snapshots.snapshot_at(timestamp)
            families = source.active_families + source.dormant_families
            family_ids = {family.family_id for family in families}
            prior_count = len(prior_events)
            prior_events = tuple(
                event
                for event in prior_events
                if event.family_id in family_ids
                and next(family for family in families if family.family_id == event.family_id).current_role is event.current_event_role
            )
            if position >= bounds.start_position:
                role_reset_count += prior_count - len(prior_events)
            atr = calculate_interaction_atr(self.dataset.prefix(position), window=config.interaction.atr_window)
            row = frame.iloc[position]
            current_observations = tuple(
                evaluate_family_interaction(
                    family,
                    timestamp=timestamp,
                    open_price=float(row["open"]),
                    high_price=float(row["high"]),
                    low_price=float(row["low"]),
                    close_price=float(row["close"]),
                    interaction_atr=atr,
                    config=config,
                    tick_size=self.tick_size,
                ).observation
                for family in families
            )
            lifecycle = advance_interaction_events(
                previous_events=prior_events,
                observations=current_observations,
                families=families,
                timestamp=timestamp,
                config=config,
            )
            prior_events = lifecycle.events
            if position < bounds.start_position:
                continue
            observations.extend(current_observations)
            events.extend(lifecycle.events)
            if self.outcome_policy is not None:
                label = bool(row[self.outcome_policy.label_column])
                for event in lifecycle.events:
                    labels.append(label)
                    predictions.append(event.state is self.outcome_policy.target_event_state)
        metrics = _interaction_metrics(
            observations=observations,
            events=events,
            labels=labels,
            predictions=predictions,
            outcome_policy=self.outcome_policy,
            role_reset_count=role_reset_count,
            bar_count=bounds.bar_count,
        )
        return WindowResult(
            trial_id=trial.trial_id,
            fold_id=window.fold_id if isinstance(window, WalkForwardFold) else window.holdout_plan_id,
            window_kind=window_kind,
            metrics=metrics,
            evaluated_bar_count=bounds.bar_count,
            diagnostics={
                "stage_output_fingerprint": semantic_id(
                    "interaction-stage-output",
                    [
                        (event.family_id, event.state, event.pressure_bars, event.close_beyond_streak, event.retest_age_bars)
                        for event in events
                    ],
                ),
                "forbidden_output_fingerprint": self.source_snapshots.stream_id,
                "frozen_source_snapshot_stream_id": self.source_snapshots.stream_id,
                "replay_start_position": replay_start,
                "scored_start_position": bounds.start_position,
                "source_snapshot_ids": tuple(
                    self.source_snapshots.snapshot_at(self.dataset.timestamps[position]).snapshot_id
                    for position in range(bounds.start_position, bounds.end_position + 1)
                ),
                "label_policy_version": None if self.outcome_policy is None else self.outcome_policy.policy_version,
                "evaluated_index_hash": semantic_id(
                    "interaction-evaluated-index", tuple(self.dataset.timestamps[bounds.start_position : bounds.end_position + 1])
                ),
            },
        )


def _interaction_metrics(
    *,
    observations,
    events,
    labels: list[bool],
    predictions: list[bool],
    outcome_policy: InteractionOutcomePolicy | None,
    role_reset_count: int,
    bar_count: int,
) -> tuple[MetricRecord, ...]:
    observation_count = len(observations)
    contact_count = sum(observation.state.value not in {"FAR", "APPROACHING"} for observation in observations)
    break_count = sum(event.state is InteractionEventState.BREAK_CONFIRMED for event in events)
    retest_count = sum(event.state is InteractionEventState.RETEST_SUCCESS for event in events)
    failed_count = sum(event.state is InteractionEventState.FAILED_BREAK for event in events)
    metrics: list[MetricRecord] = [
        ratio_metric("interaction_contact_rate", numerator=contact_count, denominator=observation_count, sample_count=observation_count),
        ratio_metric("break_confirmed_rate", numerator=break_count, denominator=max(len(events), 1), sample_count=len(events)),
        ratio_metric("retest_success_rate", numerator=retest_count, denominator=max(len(events), 1), sample_count=len(events)),
        ratio_metric("failed_break_rate", numerator=failed_count, denominator=max(len(events), 1), sample_count=len(events)),
        ratio_metric("event_reset_rate", numerator=role_reset_count, denominator=max(bar_count, 1), sample_count=bar_count),
        MetricRecord("event_evidence_brier", value=None, undefined_reason="deterministic_event_evidence_not_calibrated_probability"),
        MetricRecord("event_evidence_log_loss", value=None, undefined_reason="deterministic_event_evidence_not_calibrated_probability"),
    ]
    if outcome_policy is None:
        metrics.extend(
            MetricRecord(name, value=None, undefined_reason="typed_event_label_policy_not_supplied")
            for name in ("event_precision", "event_recall", "event_specificity", "event_false_early_rate", "event_missed_event_rate")
        )
    else:
        metrics.extend(binary_classification_metrics(labels=labels, predictions=predictions, metric_prefix="event_"))
    return tuple(metrics)


def run_interaction_optimization(**kwargs: Any):
    """Bounded public convenience API around the generic validation-only grid runner."""

    return run_stage_grid(**kwargs)


__all__ = [
    "FrozenFamilySnapshotRecord",
    "FrozenFamilySnapshotStream",
    "InteractionEvaluator",
    "InteractionOutcomePolicy",
    "build_frozen_family_snapshot_stream",
    "run_interaction_optimization",
]
