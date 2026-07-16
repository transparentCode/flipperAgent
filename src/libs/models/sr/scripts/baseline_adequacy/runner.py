"""Network-free V1.9 orchestration over frozen V1.7/V1.8 evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Any

from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.scripts.baseline_trial.config import load_and_resolve_input_config, load_resolved_sr_config
from libs.models.sr.scripts.cohort_readiness.artifacts import load_source_bundle, validate_evaluation_bundle as validate_v17_evaluation
from libs.models.sr.scripts.cohort_readiness.config import load_cohort_config
from libs.models.sr.scripts.cohort_readiness.contracts import APPROVED_ASSETS, AssetEvaluation, CohortEvaluation, SourceBundle
from libs.models.sr.scripts.cohort_readiness.metrics import replay_asset
from libs.models.sr.scripts.geometry_sensitivity.artifacts import validate_evaluation_bundle as validate_v18_study
from libs.models.sr.scripts.geometry_sensitivity.config import load_geometry_config

from .config import load_baseline_adequacy_config
from .contracts import (
    BaselineAdequacyConfig,
    BaselineAdequacyStudy,
    BaselineParity,
    ControlBuildResult,
    RealOutcomeRecord,
    StudyRunResult,
    V18_BASELINE_CANDIDATE_ID,
)
from .controls import build_controls
from .metrics import evaluate_adequacy


@dataclass(frozen=True)
class FrozenInputs:
    v17_config: Any
    source_bundle: SourceBundle
    v17_evaluation: CohortEvaluation
    v18_config: Any
    v18_study: Any
    resolved_configs: dict[str, ResolvedSRConfig]
    resolved_inputs: dict[str, Any]

    @property
    def tao_source(self):
        sources = tuple(source for source in self.source_bundle.assets if source.asset == "TAOUSDT")
        if len(sources) != 1:
            raise ContractValidationError("frozen source bundle must contain one TAOUSDT source")
        return sources[0]


def repository_commit(repo_root: str | Path) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(Path(repo_root).resolve()), "rev-parse", "HEAD"], text=True, stderr=subprocess.STDOUT).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContractValidationError("cannot determine implementation commit") from exc


def _root_path(repo_root: str | Path, relative: str, *, field_name: str) -> Path:
    root = Path(repo_root).resolve()
    path = (root / relative).resolve()
    if root not in path.parents and path != root:
        raise ContractValidationError(f"{field_name} escaped repository root")
    return path


def _assert_frozen_sr(config: BaselineAdequacyConfig, resolved: ResolvedSRConfig) -> None:
    if resolved.asset not in APPROVED_ASSETS or resolved.timeframe != config.timeframe:
        raise ContractValidationError("resolved SR configuration ownership mismatch")
    if resolved.asset == config.asset and resolved.resolved_config_hash != config.frozen_sr_config_hash:
        raise ContractValidationError("TAOUSDT resolved SR hash does not match frozen identity")
    if len(resolved.field_provenance) != 8 or any(source != "defaults" for _, source in resolved.field_provenance):
        raise ContractValidationError("V1.9 forbids SR override provenance")
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


def _assert_frozen_input(config: BaselineAdequacyConfig, resolved: Any) -> None:
    if getattr(resolved, "asset", None) not in APPROVED_ASSETS or getattr(resolved, "timeframe", None) != config.timeframe:
        raise ContractValidationError("resolved input configuration ownership mismatch")
    if resolved.asset == config.asset and resolved.resolved_input_hash != config.frozen_input_hash:
        raise ContractValidationError("TAOUSDT resolved input hash does not match frozen identity")
    if (resolved.atr_method, resolved.atr_period, resolved.atr_seed) != (config.atr_method, config.atr_period, config.atr_seed):
        raise ContractValidationError("ATR input is not frozen Wilder RMA(14)/SMA")
    if len(resolved.field_provenance) != 3 or any(source != "defaults" for _, source in resolved.field_provenance):
        raise ContractValidationError("V1.9 forbids input override provenance")


def resolve_frozen_configs(config: BaselineAdequacyConfig, *, repo_root: str | Path) -> tuple[dict[str, ResolvedSRConfig], dict[str, Any]]:
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


def load_frozen_inputs(config: BaselineAdequacyConfig, *, repo_root: str | Path) -> FrozenInputs:
    root = Path(repo_root).resolve()
    v17_config = load_cohort_config(_root_path(root, config.v17_config_path, field_name="v17_config_path"))
    if v17_config.config_hash != config.v17_config_hash:
        raise ContractValidationError("loaded V1.7 config identity mismatch")
    v18_config = load_geometry_config(_root_path(root, config.v18_config_path, field_name="v18_config_path"))
    if v18_config.config_hash != config.v18_config_hash:
        raise ContractValidationError("loaded V1.8 config identity mismatch")
    sr_configs, input_configs = resolve_frozen_configs(config, repo_root=root)
    source_bundle = load_source_bundle(
        _root_path(root, config.source_bundle_path, field_name="source_bundle_path"),
        config=v17_config,
        expected_bundle_id=config.source_bundle_id,
        implementation_commit=config.source_implementation_commit,
    )
    if source_bundle.bundle_id != config.source_bundle_id or source_bundle.implementation_commit != config.source_implementation_commit:
        raise ContractValidationError("V1.7 source bundle identity mismatch")
    for source in source_bundle.assets:
        if source.resolved_sr_config_hash != sr_configs[source.asset].resolved_config_hash or source.resolved_input_hash != input_configs[source.asset].resolved_input_hash:
            raise ContractValidationError("source/frozen config hashes do not reconcile")
    tao = tuple(source for source in source_bundle.assets if source.asset == config.asset)
    if len(tao) != 1 or tao[0].row_count != config.source_row_count or tao[0].first_open_time != config.source_start or tao[0].last_closed_at != config.source_end or tao[0].provider_calls != 0:
        raise ContractValidationError("TAOUSDT source does not match frozen development grid")
    v17_evaluation = validate_v17_evaluation(
        _root_path(root, config.v17_evaluation_bundle_path, field_name="v17_evaluation_bundle_path"),
        config=v17_config,
        source_bundle=source_bundle,
        resolved_configs=sr_configs,
        resolved_inputs=input_configs,
        implementation_commit=config.v17_evaluation_implementation_commit,
    )
    if v17_evaluation.evaluation_id != config.v17_evaluation_id or v17_evaluation.implementation_commit != config.v17_evaluation_implementation_commit:
        raise ContractValidationError("V1.7 evaluation identity mismatch")
    v18_study = validate_v18_study(
        _root_path(root, config.v18_study_bundle_path, field_name="v18_study_bundle_path"),
        config=v18_config,
        repo_root=root,
        implementation_commit=config.v18_implementation_commit,
        expected_bundle_id=config.v18_study_bundle_id,
    )
    if v18_study.study_id != config.v18_study_id or v18_study.disposition.value != "RETAIN_BASELINE_GEOMETRY" or v18_study.selected_candidate_id is not None or v18_study.baseline_candidate_id != V18_BASELINE_CANDIDATE_ID:
        raise ContractValidationError("V1.8 study is not the approved retained baseline")
    return FrozenInputs(v17_config=v17_config, source_bundle=source_bundle, v17_evaluation=v17_evaluation, v18_config=v18_config, v18_study=v18_study, resolved_configs=sr_configs, resolved_inputs=input_configs)


def _replay_semantics_equal(control: AssetEvaluation, study: AssetEvaluation) -> None:
    if control.asset != study.asset or control.source_id != study.source_id or control.resolved_sr_config_hash != study.resolved_sr_config_hash or control.resolved_input_hash != study.resolved_input_hash:
        raise ContractValidationError("baseline parity asset identity mismatch")
    if control.metrics.to_payload() != study.metrics.to_payload() or control.to_payload() != study.to_payload():
        raise ContractValidationError("baseline parity metric/outcome mismatch")
    if control.replay.model_bars != study.replay.model_bars or control.replay.reference_atr != study.replay.reference_atr:
        raise ContractValidationError("baseline parity bars or ATR mismatch")
    if control.replay.initial_state != study.replay.initial_state or control.replay.final_state != study.replay.final_state:
        raise ContractValidationError("baseline parity state mismatch")
    if control.replay.snapshots != study.replay.snapshots or control.replay.trace.snapshots != study.replay.trace.snapshots or control.replay.trace.zone_observations != study.replay.trace.zone_observations or control.replay.trace.events != study.replay.trace.events:
        raise ContractValidationError("baseline parity snapshots, visibility, or events mismatch")
    if control.replay.diagnostics != study.replay.diagnostics or control.event_accounting != study.event_accounting or control.fold_event_accounting() != study.fold_event_accounting():
        raise ContractValidationError("baseline parity diagnostics/accounting mismatch")


def validate_baseline_parity(config: BaselineAdequacyConfig, frozen: FrozenInputs, *, implementation_commit: str) -> tuple[AssetEvaluation, BaselineParity]:
    approved = tuple(item for item in frozen.v17_evaluation.assets if item.asset == config.asset)
    if len(approved) != 1:
        raise ContractValidationError("approved V1.7 evaluation lacks TAOUSDT asset")
    source = frozen.tao_source
    control = replay_asset(frozen.v17_config, source, frozen.resolved_configs[config.asset], implementation_commit=config.v17_evaluation_implementation_commit)
    _replay_semantics_equal(approved[0], control)
    baseline = replay_asset(frozen.v17_config, source, frozen.resolved_configs[config.asset], implementation_commit=implementation_commit)
    _replay_semantics_equal(control, baseline)
    checks = (
        "source_and_config_identities", "aligned_model_bars", "reference_atr_values", "initial_and_terminal_state", "lifecycle_snapshots", "trace_snapshots_and_visibility", "events_and_event_accounting", "fold_and_pooled_real_outcomes", "economic_outcome_values_and_aggregates",
    )
    return baseline, BaselineParity(passed=True, checks=checks)


def _real_outcomes(evaluation: AssetEvaluation, config: BaselineAdequacyConfig) -> tuple[RealOutcomeRecord, ...]:
    records: list[RealOutcomeRecord] = []
    for fold in config.folds:
        metric = next((item for item in evaluation.metrics.folds if item.name == fold.name), None)
        if metric is None:
            raise ContractValidationError("baseline replay lacks required fold")
        records.extend(RealOutcomeRecord(fold=fold.name, outcome=outcome) for outcome in metric.outcomes)
    if len(records) != evaluation.metrics.pooled.total_first_touch_outcomes:
        raise ContractValidationError("fold and pooled real outcome counts do not reconcile")
    return tuple(records)


def compute_study(config: BaselineAdequacyConfig, *, repo_root: str | Path, implementation_commit: str) -> BaselineAdequacyStudy:
    frozen = load_frozen_inputs(config, repo_root=repo_root)
    baseline, parity = validate_baseline_parity(config, frozen, implementation_commit=implementation_commit)
    controls: ControlBuildResult = build_controls(baseline.replay, config=config)
    real_outcomes = _real_outcomes(baseline, config)
    adequacy = evaluate_adequacy(
        real_outcomes,
        controls,
        config=config,
        approved_pooled_outcomes=baseline.metrics.pooled.outcomes,
    )
    return BaselineAdequacyStudy(
        implementation_commit=implementation_commit,
        config_hash=config.config_hash,
        source_bundle_id=frozen.source_bundle.bundle_id,
        source_id=frozen.tao_source.source_id,
        v17_config_hash=frozen.v17_config.config_hash,
        v17_evaluation_bundle_id=config.v17_evaluation_bundle_id,
        v17_evaluation_id=frozen.v17_evaluation.evaluation_id,
        v18_config_hash=frozen.v18_config.config_hash,
        v18_study_bundle_id=config.v18_study_bundle_id,
        v18_study_id=frozen.v18_study.study_id,
        frozen_sr_config_hash=config.frozen_sr_config_hash,
        frozen_input_hash=config.frozen_input_hash,
        baseline_candidate_id=V18_BASELINE_CANDIDATE_ID,
        baseline_parity=parity,
        real_outcomes=real_outcomes,
        control_anchors=controls.anchors,
        control_outcomes=controls.outcomes,
        control_accounting=controls.accounting,
        fold_side_nulls=adequacy.fold_side_nulls,
        comparisons=adequacy.comparisons,
        fold_metrics=adequacy.fold_metrics,
        aggregate=adequacy.aggregate,
        decision=adequacy.decision,
    )


def run_study(config_path: str | Path, *, repo_root: str | Path, implementation_commit: str | None = None) -> StudyRunResult:
    config = load_baseline_adequacy_config(config_path)
    commit = implementation_commit or repository_commit(repo_root)
    study = compute_study(config, repo_root=repo_root, implementation_commit=commit)
    from .artifacts import publish_evaluation_bundle

    bundle_id, path = publish_evaluation_bundle(study, output_root=_root_path(repo_root, config.output_root, field_name="output_root"), config=config)
    return StudyRunResult(bundle_id=bundle_id, path=str(path), study_id=study.study_id, disposition=study.decision.disposition)


evaluate_stage = run_study


__all__ = ["FrozenInputs", "compute_study", "evaluate_stage", "load_frozen_inputs", "repository_commit", "resolve_frozen_configs", "run_study", "validate_baseline_parity"]
