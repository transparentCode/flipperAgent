"""Verified Phase-I artifact browsing and deterministic research exports."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from ..contracts import ContractValidationError, TrendlineFamilySnapshot
from ..mtf import MTFGeometrySnapshot, serialize_mtf_snapshot
from ..optimization.artifacts import CompletionArtifactIndex, RunManifest, VerifiedRunBundle, load_artifact_envelope, verify_artifact_bundle
from ..optimization.contracts import FinalistFreeze, HoldoutOpenAudit, PromotionRecommendation, TrialResult
from ..optimization.folds import FoldPlan
from .contracts import ResearchExportManifest, ResearchRunContext, record_to_dict
from .replay import ResearchReplay, dataset_summary as canonical_dataset_summary


@dataclass(frozen=True)
class PhaseIArtifactBrowser:
    manifest: RunManifest
    baseline_validation: TrialResult
    trials: tuple[TrialResult, ...]
    recommendation: PromotionRecommendation
    artifact_paths: Mapping[str, Path]
    verification_artifact_hashes: Mapping[str, str]
    bundle: VerifiedRunBundle


def discover_phase_i_artifact_paths(root: str | Path) -> dict[str, Path]:
    """Rebuild canonical artifact paths from persisted manifest/index evidence."""

    root_path = Path(root)
    manifest_path = root_path / "run_manifest.json"
    index_path = root_path / "completion_index.json"
    if not manifest_path.is_file() or not index_path.is_file():
        raise ContractValidationError("Phase-I artifact root requires manifest and completion index")
    manifest = RunManifest.from_dict(load_artifact_envelope(manifest_path).payload)
    index = load_artifact_envelope(index_path).payload
    stage = manifest.requested_stages[0].value
    primary = tuple(index.get("primary_trial_results", ()))
    counterfactuals = tuple(index.get("counterfactual_trial_results", ()))
    paths: dict[str, Path] = {
        "manifest": manifest_path,
        "fold_plan": root_path / "fold_plan.json",
        "baseline": root_path / "baseline" / f"{index.get('baseline_validation_result_id')}.json",
        "summary": root_path / stage / "summary.json",
        "recommendation": root_path / stage / "recommendation.json",
        "completion_index": index_path,
        "report": root_path / "final_report.md",
    }
    for trial_id, _ in primary:
        paths[f"trial:{trial_id}"] = root_path / stage / "trials" / f"{trial_id}.json"
    for trial_id, _ in counterfactuals:
        paths[f"counterfactual:{trial_id}"] = root_path / stage / "trials" / "counterfactuals" / f"{trial_id}.json"
    if index.get("finalist_freeze_id") is not None:
        paths["finalist_freeze"] = root_path / stage / "holdout" / "finalist_freeze.json"
    if index.get("baseline_holdout_result_id") is not None:
        paths["baseline_holdout"] = root_path / stage / "holdout" / "baseline.json"
    if index.get("finalist_holdout_result_id") is not None:
        paths["finalist_holdout"] = root_path / stage / "holdout" / "finalist.json"
    if index.get("holdout_open_audit_ids"):
        paths["holdout_audit:baseline"] = root_path / stage / "holdout" / "baseline_open_audit.json"
        paths["holdout_audit:finalist"] = root_path / stage / "holdout" / "finalist_open_audit.json"
    if any(not path.is_file() for path in paths.values()):
        raise ContractValidationError("Phase-I artifact root is incomplete")
    return dict(sorted(paths.items()))


def load_verified_phase_i_artifacts(root: str | Path) -> PhaseIArtifactBrowser:
    paths = discover_phase_i_artifact_paths(root)
    verify_artifact_bundle(paths)
    manifest = RunManifest.from_dict(load_artifact_envelope(paths["manifest"]).payload)
    baseline = TrialResult.from_dict(load_artifact_envelope(paths["baseline"]).payload)
    trials = tuple(
        TrialResult.from_dict(load_artifact_envelope(path).payload)
        for key, path in paths.items()
        if key.startswith("trial:")
    )
    recommendation = PromotionRecommendation.from_dict(load_artifact_envelope(paths["recommendation"]).payload)
    completion_index = CompletionArtifactIndex.from_dict(load_artifact_envelope(paths["completion_index"]).payload)
    bundle = VerifiedRunBundle(
        manifest=manifest,
        fold_plan=FoldPlan.from_dict(load_artifact_envelope(paths["fold_plan"]).payload),
        baseline_validation=baseline,
        trials=tuple(sorted(trials, key=lambda trial: trial.trial.trial_id)),
        recommendation=recommendation,
        completion_index=completion_index,
        baseline_holdout=None if "baseline_holdout" not in paths else TrialResult.from_dict(load_artifact_envelope(paths["baseline_holdout"]).payload),
        finalist_holdout=None if "finalist_holdout" not in paths else TrialResult.from_dict(load_artifact_envelope(paths["finalist_holdout"]).payload),
        finalist_freeze=None if "finalist_freeze" not in paths else FinalistFreeze.from_dict(load_artifact_envelope(paths["finalist_freeze"]).payload),
        holdout_open_audits=tuple(
            HoldoutOpenAudit.from_dict(load_artifact_envelope(path).payload)
            for key, path in sorted(paths.items())
            if key.startswith("holdout_audit:")
        ),
    )
    return PhaseIArtifactBrowser(
        manifest=manifest,
        baseline_validation=baseline,
        trials=bundle.trials,
        recommendation=recommendation,
        artifact_paths=paths,
        verification_artifact_hashes=_artifact_bundle_hashes(paths),
        bundle=bundle,
    )


def export_research_artifacts(
    *,
    output_root: str | Path,
    replay: ResearchReplay,
    selected_position: int,
    tables: Mapping[str, Sequence[Any]],
    dataset_summary_payload: Mapping[str, Any] | None = None,
    mtf_snapshot: MTFGeometrySnapshot | None = None,
    phase_i_browser: PhaseIArtifactBrowser | None = None,
) -> Mapping[str, Path]:
    """Export research evidence only. Runtime config and repository state untouched."""

    selected_output = replay.output_at(selected_position)
    selected_snapshot = selected_output.snapshot
    summary = canonical_dataset_summary(replay.dataset)
    if dataset_summary_payload is not None and record_to_dict(dataset_summary_payload) != record_to_dict(summary):
        raise ContractValidationError("dataset summary does not match replay dataset")
    _validate_export_identity(context=replay.context, snapshot=selected_snapshot, mtf_snapshot=mtf_snapshot)
    table_payloads = {
        name: [record_to_dict(row) for row in values]
        for name, values in sorted(tables.items())
    }
    phase_i_hashes = {} if phase_i_browser is None else _artifact_bundle_hashes(phase_i_browser.artifact_paths)
    export_manifest = ResearchExportManifest(
        research_run_id=replay.context.research_run_id,
        selected_snapshot_id=selected_snapshot.snapshot_id,
        selected_snapshot_timestamp=selected_snapshot.timestamp,
        selected_position=selected_position,
        dataset_summary_hash=deterministic_payload_hash(summary),
        replay_config_version=replay.context.config_version,
        replay_resolved_config_hash=replay.context.resolved_config_hash,
        replay_mtf_config_hash=replay.context.mtf_config_hash,
        table_hashes={name: deterministic_payload_hash(payload) for name, payload in table_payloads.items()},
        mtf_snapshot_id=None if mtf_snapshot is None else mtf_snapshot.mtf_snapshot_id,
        mtf_config_version=None if mtf_snapshot is None else mtf_snapshot.config_version,
        mtf_config_hash=None if mtf_snapshot is None else mtf_snapshot.policy_audit.mtf_config_hash,
        phase_i_run_id=None if phase_i_browser is None else phase_i_browser.manifest.run_id,
        phase_i_artifact_hashes=phase_i_hashes,
    )
    root = Path(output_root) / export_manifest.export_bundle_id
    paths: dict[str, Path] = {}
    paths["research_manifest"] = _atomic_write_json(root / "research_manifest.json", replay.context.to_dict())
    paths["export_manifest"] = _atomic_write_json(root / "export_manifest.json", export_manifest.to_dict())
    paths["dataset_summary"] = _atomic_write_json(root / "dataset_summary.json", record_to_dict(summary))
    paths["selected_snapshot"] = _atomic_write_json(root / "selected_snapshot.json", selected_snapshot.to_dict())
    paths["tables"] = _atomic_write_json(
        root / "chart_ready_records.json",
        table_payloads,
    )
    paths["phase_i_artifacts"] = _atomic_write_json(
        root / "phase_i_artifact_ids.json",
        {
            "run_id": None if phase_i_browser is None else phase_i_browser.manifest.run_id,
            "verification_artifact_hashes": {} if phase_i_browser is None else phase_i_browser.verification_artifact_hashes,
            "artifact_hashes": phase_i_hashes,
        },
    )
    if mtf_snapshot is not None:
        target = root / "mtf_snapshot.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(target, serialize_mtf_snapshot(mtf_snapshot))
        paths["mtf_snapshot"] = target
    return dict(sorted(paths.items()))


def _validate_export_identity(
    *,
    context: ResearchRunContext,
    snapshot: TrendlineFamilySnapshot,
    mtf_snapshot: MTFGeometrySnapshot | None,
) -> None:
    if (
        snapshot.asset != context.asset
        or snapshot.timeframe != context.timeframe
        or snapshot.model_version != context.model_version
        or snapshot.config_version != context.config_version
        or snapshot.resolved_config_hash != context.resolved_config_hash
    ):
        raise ContractValidationError("selected snapshot identity does not match research context")
    if mtf_snapshot is not None and (
        mtf_snapshot.asset != context.asset
        or mtf_snapshot.normalization_context.decision_timeframe != context.timeframe
        or mtf_snapshot.model_version != context.model_version
        or mtf_snapshot.decision_timestamp != snapshot.timestamp
    ):
        raise ContractValidationError("MTF snapshot identity does not match selected replay evidence")


def deterministic_payload_hash(payload: Any) -> str:
    return sha256(json.dumps(record_to_dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


def _artifact_bundle_hashes(paths: Mapping[str, Path]) -> dict[str, str]:
    return {
        key: sha256(path.read_bytes()).hexdigest()
        for key, path in sorted(paths.items())
    }


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    return _atomic_write_text(path, json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


def _atomic_write_text(path: Path, payload: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return path


__all__ = [
    "PhaseIArtifactBrowser",
    "discover_phase_i_artifact_paths",
    "export_research_artifacts",
    "load_verified_phase_i_artifacts",
]
