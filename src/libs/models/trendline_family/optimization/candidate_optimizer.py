"""Candidate/geometry-only causal evaluator; no tracker or policy outcomes score it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from ..config import ResolvedTrendlineFamilyConfig
from ..contracts import ContractValidationError, FamilyRole, LineCandidate
from ..interactions import calculate_interaction_atr
from ..provider import CandidateGenerationStatus, LineCandidateProvider, NativeDeterministicLineProvider
from .contracts import CandidateEvaluationSpec, MetricRecord, StageEvaluationSpec, TrialConfig, WindowResult, semantic_id
from .evaluator import run_stage_grid
from .folds import HoldoutPlan, ImmutableHistoricalFrame, WalkForwardFold
from .metrics import mean_metric, ratio_metric


@dataclass(frozen=True)
class CandidateOutcomePolicy:
    """Versioned offline-only future structural labels; never passed to the model replay."""

    horizon_bars: int
    atr_window: int = 14
    touch_tolerance_atr: float = 0.25
    survival_penetration_atr: float = 0.75
    reaction_threshold_atr: float = 0.50
    policy_version: str = "candidate_structural_outcome_v1"

    def __post_init__(self) -> None:
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (self.horizon_bars, self.atr_window)):
            raise ContractValidationError("candidate outcome horizons must be positive integers")
        for name in ("touch_tolerance_atr", "survival_penetration_atr", "reaction_threshold_atr"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 0.0:
                raise ContractValidationError(f"{name} must be non-negative numeric")
            object.__setattr__(self, name, float(value))
        if not isinstance(self.policy_version, str) or not self.policy_version:
            raise ContractValidationError("candidate outcome policy_version must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon_bars": self.horizon_bars,
            "atr_window": self.atr_window,
            "touch_tolerance_atr": self.touch_tolerance_atr,
            "survival_penetration_atr": self.survival_penetration_atr,
            "reaction_threshold_atr": self.reaction_threshold_atr,
            "policy_version": self.policy_version,
        }


class CandidateGeometryEvaluator:
    """Replays provider generation at each confirmed bar inside a fold window."""

    def __init__(
        self,
        *,
        dataset: ImmutableHistoricalFrame,
        provider: LineCandidateProvider | None = None,
        outcome_policy: CandidateOutcomePolicy | None = None,
    ) -> None:
        self.dataset = dataset
        self.provider = provider or NativeDeterministicLineProvider()
        self.outcome_policy = outcome_policy

    def evaluation_spec(self) -> StageEvaluationSpec:
        provider_identity = f"{self.provider.__class__.__module__}.{self.provider.__class__.__qualname__}"
        provider_state = getattr(self.provider, "__dict__", {})
        return CandidateEvaluationSpec(
            provider_identity=provider_identity,
            provider_state_hash=semantic_id("candidate-provider-state", provider_state),
            outcome_policy=None if self.outcome_policy is None else self.outcome_policy.to_dict(),
        ).to_stage_spec()

    def __call__(
        self,
        trial: TrialConfig,
        config: ResolvedTrendlineFamilyConfig,
        window: WalkForwardFold | HoldoutPlan,
        window_kind: str,
    ) -> WindowResult:
        if trial.stage.value != "candidate_geometry":
            raise ContractValidationError("candidate evaluator only accepts candidate_geometry trials")
        bounds = window.validation if isinstance(window, WalkForwardFold) else window.window
        frame = self.dataset.to_frame()
        statuses: list[str] = []
        candidate_ids: list[str] = []
        candidate_count = 0
        support_count = 0
        resistance_count = 0
        survival: list[float] = []
        touches: list[float] = []
        reactions: list[float] = []
        penetrations: list[float] = []
        excluded = {"outcome_horizon_unavailable": 0}
        for position in range(bounds.start_position, bounds.end_position + 1):
            observed_at = frame.index[position].to_pydatetime()
            result = self.provider.generate(
                self.dataset.prefix(position),
                asset=config.asset,
                timeframe=config.timeframe,
                observed_at=observed_at,
                config=config,
            )
            statuses.append(result.status.value)
            if result.status is not CandidateGenerationStatus.VALID:
                continue
            candidate_count += len(result.candidates)
            for candidate in result.candidates:
                candidate_ids.append(candidate.candidate_id)
                support_count += int(candidate.role is FamilyRole.SUPPORT)
                resistance_count += int(candidate.role is FamilyRole.RESISTANCE)
                if self.outcome_policy is None:
                    continue
                if position + self.outcome_policy.horizon_bars > bounds.end_position:
                    excluded["outcome_horizon_unavailable"] += 1
                    continue
                outcome = self._candidate_outcome(
                    candidate=candidate,
                    position=position,
                    frame=frame,
                    policy=self.outcome_policy,
                )
                if outcome is None:
                    excluded["outcome_horizon_unavailable"] += 1
                    continue
                survival.append(outcome["survived"])
                touches.append(outcome["touched"])
                reactions.append(outcome["reacted"])
                penetrations.append(outcome["penetration"])
        eligible_bars = bounds.bar_count
        producing_bars = sum(status == CandidateGenerationStatus.VALID.value for status in statuses)
        failures = sum(status == CandidateGenerationStatus.PROVIDER_CONFIG_ERROR.value for status in statuses)
        metrics: list[MetricRecord] = [
            ratio_metric("candidate_coverage_ratio", numerator=producing_bars, denominator=eligible_bars, sample_count=eligible_bars),
            MetricRecord("candidate_count", value=float(candidate_count), sample_count=eligible_bars, valid_row_count=eligible_bars),
            ratio_metric("support_balance", numerator=support_count, denominator=candidate_count, sample_count=candidate_count),
            ratio_metric("resistance_balance", numerator=resistance_count, denominator=candidate_count, sample_count=candidate_count),
            ratio_metric("provider_failure_rate", numerator=failures, denominator=eligible_bars, sample_count=eligible_bars),
            ratio_metric("candidates_per_bar", numerator=candidate_count, denominator=eligible_bars, sample_count=eligible_bars),
            mean_metric("exact_line_future_touch_rate", touches, sample_count=len(touches) + excluded["outcome_horizon_unavailable"], excluded_row_count=excluded["outcome_horizon_unavailable"]),
            mean_metric("geometry_survival_rate", survival, sample_count=len(survival) + excluded["outcome_horizon_unavailable"], excluded_row_count=excluded["outcome_horizon_unavailable"]),
            mean_metric("reaction_quality", reactions, sample_count=len(reactions) + excluded["outcome_horizon_unavailable"], excluded_row_count=excluded["outcome_horizon_unavailable"]),
            mean_metric("normalized_penetration", penetrations, sample_count=len(penetrations) + excluded["outcome_horizon_unavailable"], excluded_row_count=excluded["outcome_horizon_unavailable"]),
        ]
        stage_fingerprint = semantic_id(
            "candidate-stage-output",
            {"statuses": statuses, "candidate_ids": sorted(candidate_ids)},
        )
        return WindowResult(
            trial_id=trial.trial_id,
            fold_id=window.fold_id if isinstance(window, WalkForwardFold) else window.holdout_plan_id,
            window_kind=window_kind,
            metrics=tuple(metrics),
            evaluated_bar_count=eligible_bars,
            excluded_reasons=excluded,
            diagnostics={
                "stage_output_fingerprint": stage_fingerprint,
                "forbidden_output_fingerprint": self.dataset.dataset_hash,
                "provider_status_counts": {status: statuses.count(status) for status in sorted(set(statuses))},
                "outcome_policy_version": None if self.outcome_policy is None else self.outcome_policy.policy_version,
                "evaluated_index_hash": semantic_id(
                    "candidate-evaluated-index", tuple(self.dataset.timestamps[bounds.start_position : bounds.end_position + 1])
                ),
            },
        )

    def _candidate_outcome(
        self,
        *,
        candidate: LineCandidate,
        position: int,
        frame: pd.DataFrame,
        policy: CandidateOutcomePolicy,
    ) -> dict[str, float] | None:
        prefix = frame.iloc[: position + 1]
        try:
            atr = calculate_interaction_atr(prefix, window=policy.atr_window).value
        except ContractValidationError:
            return None
        future = frame.iloc[position + 1 : position + policy.horizon_bars + 1]
        if len(future) != policy.horizon_bars:
            return None
        lines = [candidate.geometry.value_at(timestamp.to_pydatetime()) for timestamp in future.index]
        touch = any(
            float(row.low) <= line + policy.touch_tolerance_atr * atr
            and float(row.high) >= line - policy.touch_tolerance_atr * atr
            for row, line in zip(future.itertuples(), lines, strict=True)
        )
        if candidate.role is FamilyRole.SUPPORT:
            penetration = max(max(line - float(row.close), 0.0) for row, line in zip(future.itertuples(), lines, strict=True)) / atr
            reaction = max(max(float(row.close) - line, 0.0) for row, line in zip(future.itertuples(), lines, strict=True)) / atr
        else:
            penetration = max(max(float(row.close) - line, 0.0) for row, line in zip(future.itertuples(), lines, strict=True)) / atr
            reaction = max(max(line - float(row.close), 0.0) for row, line in zip(future.itertuples(), lines, strict=True)) / atr
        return {
            "touched": float(touch),
            "survived": float(penetration <= policy.survival_penetration_atr),
            "reacted": float(touch and reaction >= policy.reaction_threshold_atr),
            "penetration": penetration,
        }


def run_candidate_geometry_optimization(**kwargs: Any):
    """Bounded public convenience API around the generic validation-only grid runner."""

    return run_stage_grid(**kwargs)


__all__ = ["CandidateGeometryEvaluator", "CandidateOutcomePolicy", "run_candidate_geometry_optimization"]
