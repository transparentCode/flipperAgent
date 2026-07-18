"""Network-free V1.8 study orchestration over the validated V1.7 source."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
import subprocess
from typing import Any

from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.domain import ContractValidationError
from libs.models.sr.research.cohort.artifacts import (
    load_source_bundle,
    validate_evaluation_bundle,
)
from libs.models.sr.research.cohort.config import load_cohort_config
from libs.models.sr.research.cohort.contracts import (
    APPROVED_ASSETS,
    AssetEvaluation,
    CohortEvaluation,
    SourceBundle,
)
from libs.models.sr.research.cohort.metrics import (
    aggregate,
    created_side_counts,
    replay_asset,
)
from libs.models.sr.research.config.input_resolution import (
    load_and_resolve_input_config,
)
from libs.models.sr.research.config.resolution import (
    load_resolved_sr_config,
)

from .candidate_grid import (
    build_candidate_grid,
    build_effective_config,
    trial_overrides,
)
from .config import GeometrySensitivityConfig, load_geometry_config
from .contracts import (
    CandidateAssetResult,
    CandidateEvaluation,
    GeometryCandidate,
    GeometrySensitivityStudy,
    StudyGate,
)
from .selection import select_candidates


@dataclass(frozen=True)
class FrozenInputs:
    v17_config: Any
    source_bundle: SourceBundle
    v17_evaluation: CohortEvaluation
    resolved_configs: dict[str, ResolvedSRConfig]
    resolved_inputs: dict[str, Any]


def repository_commit(repo_root: str | Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(Path(repo_root).resolve()), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContractValidationError("cannot determine implementation commit") from exc


def _root_path(repo_root: str | Path, relative: str, *, field_name: str) -> Path:
    root = Path(repo_root).resolve()
    path = (root / relative).resolve()
    if root not in path.parents and path != root:
        raise ContractValidationError(f"{field_name} escaped repository root")
    return path


def resolve_frozen_configs(
    config: GeometrySensitivityConfig,
    *,
    repo_root: str | Path,
) -> tuple[dict[str, ResolvedSRConfig], dict[str, Any]]:
    """Resolve the production SR/ATR configs without touching any provider path."""
    root = Path(repo_root).resolve()
    sr_path = _root_path(root, config.sr_config_path, field_name="sr_config_path")
    input_path = _root_path(root, config.input_config_path, field_name="input_config_path")
    sr_configs: dict[str, ResolvedSRConfig] = {}
    input_configs: dict[str, Any] = {}
    for asset in APPROVED_ASSETS:
        sr = load_resolved_sr_config(sr_path, asset=asset, timeframe=config.timeframe)
        resolved_input = load_and_resolve_input_config(input_path, asset=asset, timeframe=config.timeframe)
        _assert_frozen_sr(config, sr)
        _assert_frozen_input(config, resolved_input)
        sr_configs[asset] = sr
        input_configs[asset] = resolved_input
    return sr_configs, input_configs


def _assert_frozen_sr(config: GeometrySensitivityConfig, resolved: ResolvedSRConfig) -> None:
    if resolved.asset not in APPROVED_ASSETS or resolved.timeframe != config.timeframe:
        raise ContractValidationError("resolved SR configuration ownership mismatch")
    if resolved.asset == "TAOUSDT" and resolved.resolved_config_hash != config.frozen_sr_config_hash:
        raise ContractValidationError("TAOUSDT SR config hash is not the frozen V1.6 value")
    if tuple((path, "defaults") for path, _ in resolved.field_provenance) != resolved.field_provenance:
        raise ContractValidationError("V1.8 forbids production SR override provenance")
    expected = (
        ("detection", "pivot_span_bars", 5),
        ("detection", "zone_half_width_atr", 0.25),
        ("association", "merge_distance_atr", 0.50),
        ("lifecycle", "touch_tolerance_atr", 0.25),
        ("lifecycle", "break_buffer_atr", 0.25),
        ("lifecycle", "break_confirm_closes", 2),
        ("lifecycle", "max_age_bars", 50),
        ("runtime", "max_active_zones", 8),
    )
    for section, name, value in expected:
        if getattr(getattr(resolved, section), name) != value:
            raise ContractValidationError(f"frozen SR parameter changed: {section}.{name}")


def _assert_frozen_input(config: GeometrySensitivityConfig, resolved: Any) -> None:
    if getattr(resolved, "asset", None) not in APPROVED_ASSETS or getattr(resolved, "timeframe", None) != config.timeframe:
        raise ContractValidationError("resolved ATR configuration ownership mismatch")
    if resolved.asset == "TAOUSDT" and resolved.resolved_input_hash != config.frozen_input_hash:
        raise ContractValidationError("TAOUSDT input config hash is not the frozen V1.6 value")
    if (resolved.atr_method, resolved.atr_period, resolved.atr_seed) != (config.atr_method, config.atr_period, config.atr_seed):
        raise ContractValidationError("ATR input contract is not frozen Wilder RMA(14)/SMA")
    if tuple((path, "defaults") for path, _ in resolved.field_provenance) != resolved.field_provenance:
        raise ContractValidationError("V1.8 forbids production input override provenance")


def load_frozen_inputs(config: GeometrySensitivityConfig, *, repo_root: str | Path) -> FrozenInputs:
    root = Path(repo_root).resolve()
    v17_config = load_cohort_config(_root_path(root, config.v17_config_path, field_name="v17_config_path"))
    # The V1.7 loader is still run here so all protocol fields and
    # duplicated-key checks are exercised before replay.
    if v17_config.config_hash != config.v17_config_hash:
        raise ContractValidationError("loaded V1.7 config is not the approved protocol")
    sr_configs, input_configs = resolve_frozen_configs(config, repo_root=root)
    source_path = _root_path(root, config.source_bundle_path, field_name="source_bundle_path")
    source_bundle = load_source_bundle(
        source_path,
        config=v17_config,
        implementation_commit=config.source_implementation_commit,
        expected_bundle_id=config.source_bundle_id,
    )
    if source_bundle.implementation_commit != config.source_implementation_commit:
        raise ContractValidationError("source bundle implementation identity mismatch")
    for source in source_bundle.assets:
        if source.resolved_sr_config_hash != sr_configs[source.asset].resolved_config_hash or source.resolved_input_hash != input_configs[source.asset].resolved_input_hash:
            raise ContractValidationError("source and frozen resolved configuration hashes do not reconcile")
    evaluation_path = _root_path(root, config.evaluation_bundle_path, field_name="evaluation_bundle_path")
    v17_evaluation = validate_evaluation_bundle(
        evaluation_path,
        config=v17_config,
        source_bundle=source_bundle,
        resolved_configs=sr_configs,
        resolved_inputs=input_configs,
        implementation_commit=config.evaluation_implementation_commit,
    )
    if v17_evaluation.evaluation_id != config.evaluation_id or v17_evaluation.implementation_commit != config.evaluation_implementation_commit:
        raise ContractValidationError("V1.7 evaluation identity mismatch")
    return FrozenInputs(v17_config=v17_config, source_bundle=source_bundle, v17_evaluation=v17_evaluation, resolved_configs=sr_configs, resolved_inputs=input_configs)


def _replay_semantics_equal(control: AssetEvaluation, study: AssetEvaluation) -> None:
    if control.asset != study.asset or control.source_id != study.source_id or control.resolved_sr_config_hash != study.resolved_sr_config_hash or control.resolved_input_hash != study.resolved_input_hash:
        raise ContractValidationError("baseline parity asset identity mismatch")
    if control.metrics.to_payload() != study.metrics.to_payload():
        raise ContractValidationError("baseline parity metric mismatch")
    if control.replay.model_bars != study.replay.model_bars or control.replay.reference_atr != study.replay.reference_atr:
        raise ContractValidationError("baseline parity bars or ATR mismatch")
    if control.replay.initial_state != study.replay.initial_state or control.replay.final_state != study.replay.final_state:
        raise ContractValidationError("baseline parity state mismatch")
    if control.replay.snapshots != study.replay.snapshots or control.replay.trace.snapshots != study.replay.trace.snapshots or control.replay.trace.zone_observations != study.replay.trace.zone_observations or control.replay.trace.events != study.replay.trace.events:
        raise ContractValidationError("baseline parity snapshots, observations, or events mismatch")


def validate_baseline_parity(
    config: GeometrySensitivityConfig,
    frozen: FrozenInputs,
    baseline: GeometryCandidate,
    *,
    implementation_commit: str,
) -> tuple[AssetEvaluation, ...]:
    effective = {
        asset: build_effective_config(frozen.resolved_configs[asset], baseline)
        for asset in APPROVED_ASSETS
    }
    control_results: list[AssetEvaluation] = []
    baseline_results: list[AssetEvaluation] = []
    for source, control in zip(frozen.source_bundle.assets, frozen.v17_evaluation.assets):
        control_replay = replay_asset(frozen.v17_config, source, frozen.resolved_configs[source.asset], implementation_commit=config.evaluation_implementation_commit)
        if control_replay.to_payload() != control.to_payload():
            raise ContractValidationError("V1.7 control replay does not equal persisted evaluation asset")
        baseline_replay = replay_asset(frozen.v17_config, source, effective[source.asset], implementation_commit=implementation_commit)
        _replay_semantics_equal(control_replay, baseline_replay)
        control_results.append(control_replay)
        baseline_results.append(baseline_replay)
    control_micro, control_macro = aggregate(tuple(control_results))
    baseline_micro, baseline_macro = aggregate(tuple(baseline_results))
    if control_micro.to_payload() != baseline_micro.to_payload() or control_macro.to_payload() != baseline_macro.to_payload():
        raise ContractValidationError("V1.7/V1.8 baseline aggregate parity mismatch")
    return tuple(baseline_results)


def _source_for_effective_config(source: Any, resolved: ResolvedSRConfig) -> Any:
    """Adapt only the ownership hash for the study-owned replay boundary.

    The source bars and source identity remain unchanged.  The V1.7 replay
    helper deliberately requires its source hash to equal the effective SR
    hash; a frozen dataclass replacement lets V1.8 reuse that helper without
    changing the approved V1.7 module or the persisted source bundle.
    """
    if resolved.resolved_config_hash == source.resolved_sr_config_hash:
        return source
    return replace(source, resolved_sr_config_hash=resolved.resolved_config_hash)


def _structural_gates(evaluation: AssetEvaluation) -> tuple[StudyGate, ...]:
    support, resistance = created_side_counts(evaluation)
    metric = evaluation.metrics.pooled
    values = (
        ("structural.created_support_zones", support),
        ("structural.created_resistance_zones", resistance),
        ("structural.first_touch_outcomes", metric.total_first_touch_outcomes),
        ("structural.terminal_cohort_events", metric.cohort_terminal_count),
    )
    return tuple(
        StudyGate(
            name=name,
            asset=evaluation.asset,
            passed=value > 0,
            value=value,
            threshold=1,
            reason="non-zero structural cohort" if value > 0 else "zero structural cohort",
        )
        for name, value in values
    )


def _eligibility_gates(config: GeometrySensitivityConfig, evaluation: AssetEvaluation) -> tuple[StudyGate, ...]:
    metric = evaluation.metrics.pooled
    minimum_fold = config.readiness_gates.minimum_completed_first_touches_per_fold
    eligible_folds = sum(fold.completed_first_touch_outcomes >= minimum_fold for fold in evaluation.metrics.folds)
    structural = _structural_gates(evaluation)
    sample = (
        StudyGate("sample.eligible_development_folds", eligible_folds >= config.readiness_gates.minimum_eligible_development_folds, eligible_folds, config.readiness_gates.minimum_eligible_development_folds, "enough eligible folds" if eligible_folds >= config.readiness_gates.minimum_eligible_development_folds else "too few eligible folds", asset=evaluation.asset),
        StudyGate("sample.development_completed_first_touches", metric.completed_first_touch_outcomes >= config.readiness_gates.minimum_development_completed_first_touches, metric.completed_first_touch_outcomes, config.readiness_gates.minimum_development_completed_first_touches, "development coverage is sufficient" if metric.completed_first_touch_outcomes >= config.readiness_gates.minimum_development_completed_first_touches else "development coverage is insufficient", asset=evaluation.asset),
    )
    fold_diagnostics = tuple(
        StudyGate("diagnostic.completed_first_touches_per_fold", fold.completed_first_touch_outcomes >= minimum_fold, fold.completed_first_touch_outcomes, minimum_fold, "fold sample diagnostic", asset=evaluation.asset, fold=fold.name)
        for fold in evaluation.metrics.folds
    )
    return structural + sample + fold_diagnostics


def _asset_guardrails(candidate: CandidateEvaluation, baseline: CandidateEvaluation) -> tuple[StudyGate, ...]:
    records: list[StudyGate] = []
    for candidate_asset, baseline_asset in zip(candidate.assets, baseline.assets):
        cm = candidate_asset.metrics.pooled
        bm = baseline_asset.metrics.pooled
        checks = (
            ("invalidation_rate_delta", None if cm.invalidation_rate is None or bm.invalidation_rate is None else cm.invalidation_rate - bm.invalidation_rate, 0.05, lambda value: value is not None and value <= 0.05),
            ("zone_creation_density_ratio", None if cm.zone_creation_density_per_100_bars is None or bm.zone_creation_density_per_100_bars is None or bm.zone_creation_density_per_100_bars <= 0 else cm.zone_creation_density_per_100_bars / bm.zone_creation_density_per_100_bars, [0.50, 2.00], lambda value: value is not None and 0.50 <= value <= 2.00),
            ("churn_rate_delta", None if cm.churn_rate is None or bm.churn_rate is None else cm.churn_rate - bm.churn_rate, 0.10, lambda value: value is not None and value <= 0.10),
            ("right_censoring_rate_delta", None if cm.right_censoring_rate is None or bm.right_censoring_rate is None else cm.right_censoring_rate - bm.right_censoring_rate, 0.10, lambda value: value is not None and value <= 0.10),
        )
        records.extend(StudyGate(f"asset_guardrail.{candidate_asset.asset}.{name}", predicate(value), value, threshold, "per-asset guardrail diagnostic") for name, value, threshold, predicate in checks)
    return tuple(records)


def _build_candidate_evaluation(
    config: GeometrySensitivityConfig,
    candidate: GeometryCandidate,
    evaluations: tuple[AssetEvaluation, ...],
    inherited_configs: dict[str, ResolvedSRConfig],
    effective_configs: dict[str, ResolvedSRConfig],
    baseline: CandidateEvaluation | None,
) -> CandidateEvaluation:
    micro, macro = aggregate(evaluations)
    results = tuple(
        CandidateAssetResult(
            asset=evaluation.asset,
            source_id=evaluation.source_id,
            inherited_resolved_config_hash=inherited_configs[evaluation.asset].resolved_config_hash,
            effective_resolved_config_hash=effective_configs[evaluation.asset].resolved_config_hash,
            effective_field_provenance=inherited_configs[evaluation.asset].field_provenance,
            trial_overrides=trial_overrides(candidate),
            evaluation=evaluation,
            structural_gates=_structural_gates(evaluation),
        )
        for evaluation in evaluations
    )
    eligibility = tuple(gate for result in results for gate in _eligibility_gates(config, result.evaluation))
    if baseline is None:
        pooled_deltas = tuple((asset, 0.0) for asset in APPROVED_ASSETS)
        fold_deltas: tuple[tuple[str, str, float | None], ...] = tuple((asset, fold.name, 0.0) for asset in APPROVED_ASSETS for fold in evaluations[0].metrics.folds)
        guardrails: tuple[StudyGate, ...] = ()
    else:
        pooled_deltas = tuple(
            (asset, None if result.metrics.pooled.median_quality_reference_atr is None or base_result.metrics.pooled.median_quality_reference_atr is None else result.metrics.pooled.median_quality_reference_atr - base_result.metrics.pooled.median_quality_reference_atr)
            for asset, result, base_result in zip(APPROVED_ASSETS, results, baseline.assets)
        )
        fold_values: list[tuple[str, str, float | None]] = []
        for asset, result, base_result in zip(APPROVED_ASSETS, results, baseline.assets):
            for fold, base_fold in zip(result.metrics.folds, base_result.metrics.folds):
                comparable = fold.completed_first_touch_outcomes >= config.selection.minimum_completed_first_touches_per_fold and base_fold.completed_first_touch_outcomes >= config.selection.minimum_completed_first_touches_per_fold and fold.median_quality_reference_atr is not None and base_fold.median_quality_reference_atr is not None
                value = None if not comparable else fold.median_quality_reference_atr - base_fold.median_quality_reference_atr
                fold_values.append((asset, fold.name, value))
        fold_deltas = tuple(fold_values)
        provisional = CandidateEvaluation(candidate, results, micro, macro, pooled_deltas, fold_deltas, eligibility, ())
        guardrails = _asset_guardrails(provisional, baseline)
    return CandidateEvaluation(candidate, results, micro, macro, pooled_deltas, fold_deltas, eligibility, guardrails)


def compute_study(
    config: GeometrySensitivityConfig,
    *,
    repo_root: str | Path,
    implementation_commit: str,
) -> GeometrySensitivityStudy:
    """Validate both V1.7 artifacts, establish parity, then replay all nine candidates."""
    frozen = load_frozen_inputs(config, repo_root=repo_root)
    candidates = build_candidate_grid(config)
    baseline = next(item for item in candidates if item.baseline)
    baseline_assets = validate_baseline_parity(config, frozen, baseline, implementation_commit=implementation_commit)
    raw_by_id: dict[str, tuple[AssetEvaluation, ...]] = {baseline.candidate_id: baseline_assets}
    for candidate in candidates:
        if candidate.baseline:
            continue
        effective = {asset: build_effective_config(frozen.resolved_configs[asset], candidate) for asset in APPROVED_ASSETS}
        raw_by_id[candidate.candidate_id] = tuple(
            replay_asset(frozen.v17_config, _source_for_effective_config(source, effective[source.asset]), effective[source.asset], implementation_commit=implementation_commit)
            for source in frozen.source_bundle.assets
        )
    built_by_id: dict[str, CandidateEvaluation] = {}
    baseline_eval: CandidateEvaluation | None = None
    ordered_for_build = (baseline,) + tuple(item for item in candidates if not item.baseline)
    for candidate in ordered_for_build:
        if candidate.baseline:
            effective = {asset: build_effective_config(frozen.resolved_configs[asset], candidate) for asset in APPROVED_ASSETS}
            current = _build_candidate_evaluation(config, candidate, raw_by_id[candidate.candidate_id], frozen.resolved_configs, effective, None)
            baseline_eval = current
        else:
            if baseline_eval is None:
                raise ContractValidationError("baseline must be built before challengers")
            effective = {asset: build_effective_config(frozen.resolved_configs[asset], candidate) for asset in APPROVED_ASSETS}
            current = _build_candidate_evaluation(config, candidate, raw_by_id[candidate.candidate_id], frozen.resolved_configs, effective, baseline_eval)
        built_by_id[candidate.candidate_id] = current
    if baseline_eval is None:
        raise ContractValidationError("study baseline is missing")
    baseline_v17 = frozen.v17_evaluation
    if baseline_eval.micro.to_payload() != baseline_v17.micro.to_payload() or baseline_eval.macro.to_payload() != baseline_v17.macro.to_payload():
        raise ContractValidationError("baseline cohort semantics do not match V1.7 evaluation")
    if baseline_v17.disposition.value != "READY_FOR_PARAMETER_SENSITIVITY" or not baseline_eval.fully_evaluable:
        raise ContractValidationError("V1.7 baseline readiness semantics do not match the approved study precondition")
    built = tuple(built_by_id[item.candidate_id] for item in candidates)
    decisions, selected, disposition = select_candidates(built, config=config)
    return GeometrySensitivityStudy(
        implementation_commit=implementation_commit,
        config_hash=config.config_hash,
        v17_config_hash=baseline_v17.config_hash,
        source_bundle_id=frozen.source_bundle.bundle_id,
        v17_evaluation_bundle_id=config.evaluation_bundle_id,
        v17_evaluation_id=baseline_v17.evaluation_id,
        frozen_sr_config_hash=config.frozen_sr_config_hash,
        frozen_input_hash=config.frozen_input_hash,
        candidates=candidates,
        baseline_candidate_id=baseline.candidate_id,
        evaluations=tuple(built),
        decisions=decisions,
        selected_candidate_id=selected,
        disposition=disposition,
    )


def run_study(
    config_path: str | Path,
    *,
    repo_root: str | Path,
    implementation_commit: str | None = None,
) -> dict[str, Any]:
    config = load_geometry_config(config_path)
    commit = implementation_commit or repository_commit(repo_root)
    study = compute_study(config, repo_root=repo_root, implementation_commit=commit)
    from .artifacts import publish_evaluation_bundle

    bundle_id, path = publish_evaluation_bundle(study, output_root=_root_path(repo_root, config.output_root, field_name="output_root"), config=config)
    return {"bundle_id": bundle_id, "path": str(path), "study_id": study.study_id, "disposition": study.disposition.value, "selected_candidate_id": study.selected_candidate_id}


evaluate_stage = run_study


__all__ = [
    "FrozenInputs", "compute_study", "evaluate_stage", "load_frozen_inputs", "repository_commit", "resolve_frozen_configs", "run_study", "validate_baseline_parity",
]
