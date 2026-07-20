"""Tracker-only replay over one immutable candidate stream."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Mapping

from ..configuration.contracts import ResolvedTrendlineFamilyConfig
from ..contracts import ContractValidationError, FamilyTransitionType, LineCandidate, TrendlineFamilySnapshot
from ..provider import CandidateGenerationResult, CandidateGenerationStatus, LineCandidateProvider, NativeDeterministicLineProvider
from ..repository import InMemoryTrendlineFamilyRepository
from ..tracker import TrendlineFamilyTracker
from .contracts import MetricRecord, StageEvaluationSpec, TrackerEvaluationSpec, TrialConfig, WindowResult, semantic_id
from .evaluator import run_stage_grid
from .folds import HoldoutPlan, ImmutableHistoricalFrame, WalkForwardFold
from .metrics import mean_metric, ratio_metric


@dataclass(frozen=True)
class FrozenCandidateRecord:
    timestamp: datetime
    result: CandidateGenerationResult

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime) or self.timestamp.tzinfo is None or self.timestamp.utcoffset().total_seconds() != 0:
            raise ContractValidationError("frozen candidate timestamp must be UTC")
        if not isinstance(self.result, CandidateGenerationResult):
            raise ContractValidationError("frozen candidate record requires CandidateGenerationResult")


@dataclass(frozen=True)
class FrozenCandidateStream:
    asset: str
    timeframe: str
    dataset_hash: str
    source_candidate_config_hash: str
    records: tuple[FrozenCandidateRecord, ...]
    stream_id: str | None = None

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.asset, self.timeframe, self.dataset_hash, self.source_candidate_config_hash)):
            raise ContractValidationError("frozen candidate stream identity fields must be non-empty")
        records = tuple(self.records)
        if not records or any(not isinstance(record, FrozenCandidateRecord) for record in records):
            raise ContractValidationError("frozen candidate stream requires records")
        if tuple(sorted(record.timestamp for record in records)) != tuple(record.timestamp for record in records):
            raise ContractValidationError("frozen candidate stream records must be ordered")
        if len({record.timestamp for record in records}) != len(records):
            raise ContractValidationError("frozen candidate stream timestamps must be unique")
        object.__setattr__(self, "records", records)
        expected = semantic_id("trendline-family-frozen-candidate-stream", self.identity_payload())
        if self.stream_id is not None and self.stream_id != expected:
            raise ContractValidationError("frozen candidate stream ID does not match source content")
        object.__setattr__(self, "stream_id", expected)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "dataset_hash": self.dataset_hash,
            "source_candidate_config_hash": self.source_candidate_config_hash,
            "records": [
                {
                    "timestamp": record.timestamp,
                    "status": record.result.status.value,
                    "candidate_payloads": [candidate.to_dict() for candidate in record.result.candidates],
                    "reason_codes": record.result.reason_codes,
                }
                for record in self.records
            ],
        }

    def record_at(self, timestamp: datetime) -> FrozenCandidateRecord:
        for record in self.records:
            if record.timestamp == timestamp:
                return record
        raise ContractValidationError("frozen candidate stream has no record for observed_at")


def build_frozen_candidate_stream(
    *,
    dataset: ImmutableHistoricalFrame,
    config: ResolvedTrendlineFamilyConfig,
    provider: LineCandidateProvider | None = None,
) -> FrozenCandidateStream:
    """Create one candidate artifact before tracker trials; no tracker config can alter it."""

    if dataset.asset != config.asset or dataset.timeframe != config.timeframe:
        raise ContractValidationError("candidate stream dataset/config identity mismatch")
    active_provider = provider or NativeDeterministicLineProvider()
    records = tuple(
        FrozenCandidateRecord(
            timestamp=timestamp,
            result=active_provider.generate(
                dataset.prefix(position),
                asset=config.asset,
                timeframe=config.timeframe,
                observed_at=timestamp,
                config=config,
            ),
        )
        for position, timestamp in enumerate(dataset.timestamps)
    )
    return FrozenCandidateStream(
        asset=dataset.asset,
        timeframe=dataset.timeframe,
        dataset_hash=dataset.dataset_hash,
        source_candidate_config_hash=config.resolved_config_hash,
        records=records,
    )


class _FrozenCandidateProvider:
    """Re-tag immutable candidate geometry for a tracker trial's config identity only."""

    def __init__(self, stream: FrozenCandidateStream) -> None:
        self.stream = stream

    def generate(
        self,
        _ohlcv,
        *,
        asset: str,
        timeframe: str,
        observed_at: datetime,
        config: ResolvedTrendlineFamilyConfig,
        context: Mapping[str, Any] | None = None,
    ) -> CandidateGenerationResult:
        del context
        if asset != self.stream.asset or timeframe != self.stream.timeframe:
            return CandidateGenerationResult(
                status=CandidateGenerationStatus.PROVIDER_CONFIG_ERROR,
                candidates=(),
                reason_codes=("frozen_stream_identity_mismatch",),
            )
        record = self.stream.record_at(observed_at)
        if record.result.status is not CandidateGenerationStatus.VALID:
            return record.result
        return CandidateGenerationResult(
            status=CandidateGenerationStatus.VALID,
            candidates=tuple(_retag_candidate(candidate, config=config) for candidate in record.result.candidates),
            reason_codes=(),
            metadata={"frozen_candidate_stream_id": self.stream.stream_id},
        )


def _retag_candidate(candidate: LineCandidate, *, config: ResolvedTrendlineFamilyConfig) -> LineCandidate:
    metadata = dict(candidate.metadata)
    metadata.update(
        {
            "model_version": config.model_version,
            "config_version": config.config_version,
            "resolved_config_hash": config.resolved_config_hash,
        }
    )
    return replace(candidate, metadata=metadata)


class TrackerEvaluator:
    """Rebuild tracker state per fold from fixed precomputed candidates and clean repository heads."""

    def __init__(self, *, dataset: ImmutableHistoricalFrame, candidate_stream: FrozenCandidateStream) -> None:
        if dataset.dataset_hash != candidate_stream.dataset_hash:
            raise ContractValidationError("tracker dataset and frozen candidate stream hash mismatch")
        self.dataset = dataset
        self.candidate_stream = candidate_stream

    def evaluation_spec(self) -> StageEvaluationSpec:
        return TrackerEvaluationSpec(
            frozen_candidate_stream_id=self.candidate_stream.stream_id,
            source_candidate_config_hash=self.candidate_stream.source_candidate_config_hash,
        ).to_stage_spec()

    def __call__(
        self,
        trial: TrialConfig,
        config: ResolvedTrendlineFamilyConfig,
        window: WalkForwardFold | HoldoutPlan,
        window_kind: str,
    ) -> WindowResult:
        if trial.stage.value != "tracker":
            raise ContractValidationError("tracker evaluator only accepts tracker trials")
        bounds = window.validation if isinstance(window, WalkForwardFold) else window.window
        replay_start = window.warmup.start_position
        tracker = TrendlineFamilyTracker(
            repository=InMemoryTrendlineFamilyRepository(),
            provider=_FrozenCandidateProvider(self.candidate_stream),
            config=config,
        )
        snapshots: list[TrendlineFamilySnapshot] = []
        for position in range(replay_start, bounds.end_position + 1):
            timestamp = self.dataset.timestamps[position]
            output = tracker.update(self.dataset.prefix(position), observed_at=timestamp)
            if position >= bounds.start_position:
                snapshots.append(output.snapshot)
        metrics = _tracker_metrics(snapshots)
        return WindowResult(
            trial_id=trial.trial_id,
            fold_id=window.fold_id if isinstance(window, WalkForwardFold) else window.holdout_plan_id,
            window_kind=window_kind,
            metrics=metrics,
            evaluated_bar_count=bounds.bar_count,
            diagnostics={
                "stage_output_fingerprint": _tracker_fingerprint(snapshots),
                "forbidden_output_fingerprint": self.candidate_stream.stream_id,
                "frozen_candidate_stream_id": self.candidate_stream.stream_id,
                "replay_start_position": replay_start,
                "validation_start_position": bounds.start_position,
                "evaluated_index_hash": semantic_id(
                    "tracker-evaluated-index", tuple(self.dataset.timestamps[bounds.start_position : bounds.end_position + 1])
                ),
            },
        )


def _tracker_metrics(snapshots: list[TrendlineFamilySnapshot]) -> tuple[MetricRecord, ...]:
    if not snapshots:
        raise ContractValidationError("tracker evaluator produced no snapshots")
    transitions = [transition for snapshot in snapshots for transition in snapshot.transitions]
    family_sets = [
        {family.family_id for family in snapshot.active_families + snapshot.dormant_families}
        for snapshot in snapshots
    ]
    continuation: list[float] = []
    for previous, current in zip(family_sets, family_sets[1:], strict=False):
        if previous:
            continuation.append(len(previous & current) / len(previous))
    lifetimes = [family.age_bars for snapshot in snapshots for family in snapshot.active_families + snapshot.dormant_families]
    confidence = [family.confidence for snapshot in snapshots for family in snapshot.active_families + snapshot.dormant_families]
    active_counts = [len(snapshot.active_families) for snapshot in snapshots]
    bars = len(snapshots)
    births = sum(transition.transition_type is FamilyTransitionType.BIRTH for transition in transitions)
    expiries = sum(transition.transition_type is FamilyTransitionType.EXPIRE for transition in transitions)
    dormant = sum(transition.transition_type is FamilyTransitionType.DORMANT for transition in transitions)
    reactivations = sum(transition.transition_type is FamilyTransitionType.REACTIVATE for transition in transitions)
    unmatched = sum(int(snapshot.diagnostics.get("unmatched_active_count", 0)) for snapshot in snapshots)
    return (
        mean_metric("family_continuation_rate", continuation, sample_count=max(len(snapshots) - 1, 0)),
        mean_metric("average_family_lifetime", lifetimes, sample_count=len(lifetimes)),
        mean_metric("mean_family_confidence", confidence, sample_count=len(confidence)),
        mean_metric("active_family_count", active_counts, sample_count=bars),
        ratio_metric("births_per_eligible_bar", numerator=births, denominator=bars, sample_count=bars),
        ratio_metric("expiries_per_eligible_bar", numerator=expiries, denominator=bars, sample_count=bars),
        ratio_metric("dormant_reactivation_rate", numerator=reactivations, denominator=max(dormant, 1), sample_count=bars),
        ratio_metric("unmatched_candidate_pressure", numerator=unmatched, denominator=bars, sample_count=bars),
        MetricRecord(
            "future_structural_utility",
            value=None,
            sample_count=0,
            valid_row_count=0,
            undefined_reason="typed_future_outcome_policy_not_supplied",
        ),
    )


def _tracker_fingerprint(snapshots: list[TrendlineFamilySnapshot]) -> str:
    return semantic_id(
        "tracker-stage-output",
        [
            {
                "timestamp": snapshot.timestamp,
                "families": [
                    {
                        "family_id": family.family_id,
                        "version": family.version,
                        "role": family.current_role,
                        "lifecycle": family.lifecycle_state,
                        "confidence": family.confidence,
                        "representative_member_id": family.representative_member_id,
                        "member_ids": tuple(member.member_id for member in family.members),
                    }
                    for family in snapshot.active_families + snapshot.dormant_families
                ],
                "transitions": [
                    (transition.family_id, transition.transition_type, transition.previous_version, transition.new_version)
                    for transition in snapshot.transitions
                ],
            }
            for snapshot in snapshots
        ],
    )


def run_tracker_optimization(**kwargs: Any):
    """Bounded public convenience API around the generic validation-only grid runner."""

    return run_stage_grid(**kwargs)


__all__ = [
    "FrozenCandidateRecord",
    "FrozenCandidateStream",
    "TrackerEvaluator",
    "build_frozen_candidate_stream",
    "run_tracker_optimization",
]
