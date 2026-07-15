"""Ordered V1.6 stage orchestration with explicit holdout sealing."""

from __future__ import annotations

from pathlib import Path
import subprocess

from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.domain.contracts import ContractValidationError

from libs.models.sr.scripts.baseline_trial.config import (
    load_and_resolve_input_config,
    load_resolved_sr_config,
)

from .artifacts import find_development_bundle, publish_development, publish_holdout
from .candidates import replay_candidates
from .config import CalibrationConfig, load_calibration_config
from .contracts import CapsuleStage
from .metrics import compute_candidate_metrics, compute_window_metrics
from .selection import evaluate_holdout_metrics, select_development
from .source import (
    build_source_capsules,
    load_capsule,
    load_frozen_source,
    publish_source_capsule,
)


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
    if root not in path.parents:
        raise ContractValidationError(f"{field_name} escaped repository root")
    return path


def _load_config(config_path: str | Path, repo_root: str | Path) -> CalibrationConfig:
    path = Path(config_path)
    if not path.is_absolute():
        path = Path(repo_root).resolve() / path
    return load_calibration_config(path)


def resolve_frozen_sr_config(config: CalibrationConfig, *, repo_root: str | Path) -> ResolvedSRConfig:
    """Resolve the approved production SR config and verify both frozen hashes."""
    root = Path(repo_root).resolve()
    sr_config = load_resolved_sr_config(
        _root_path(root, config.sr_config_path, field_name="sr_config_path"),
        asset=config.symbol,
        timeframe=config.timeframe,
    )
    resolved_input = load_and_resolve_input_config(
        _root_path(root, config.input_config_path, field_name="input_config_path"),
        asset=config.symbol,
        timeframe=config.timeframe,
    )
    if sr_config.resolved_config_hash != config.expected_sr_config_hash:
        raise ContractValidationError("resolved SR config hash does not match V1.5 identity")
    if resolved_input.resolved_input_hash != config.expected_input_hash:
        raise ContractValidationError("resolved input config hash does not match V1.5 identity")
    if resolved_input.atr_method != config.atr_method or resolved_input.atr_seed != config.atr_seed or resolved_input.atr_period != config.baseline_period:
        raise ContractValidationError("resolved input ATR contract is not frozen baseline ATR(14)")
    return sr_config


def prepare_source_stage(config_path: str | Path, *, repo_root: str | Path, implementation_commit: str | None = None) -> dict[str, object]:
    config = _load_config(config_path, repo_root)
    commit = implementation_commit or repository_commit(repo_root)
    development, sealed = build_source_capsules(config, repo_root=repo_root, implementation_commit=commit)
    output_root = _root_path(repo_root, config.output_root, field_name="output_root")
    development_path = publish_source_capsule(development, output_root=output_root)
    sealed_path = publish_source_capsule(sealed, output_root=output_root)
    return {
        "development_source_id": development.capsule_id,
        "development_path": str(development_path),
        "development_row_count": len(development.bars),
        "sealed_source_id": sealed.capsule_id,
        "sealed_path": str(sealed_path),
        "sealed_row_count": len(sealed.bars),
    }


def _load_development_capsule(config: CalibrationConfig, *, repo_root: str | Path, implementation_commit: str):
    development, _ = build_source_capsules(config, repo_root=repo_root, implementation_commit=implementation_commit)
    path = _root_path(repo_root, config.output_root, field_name="output_root") / "source" / CapsuleStage.DEVELOPMENT.value / development.capsule_id
    return load_capsule(path, expected_stage=CapsuleStage.DEVELOPMENT, expected_source=config, expected_implementation_commit=implementation_commit)


def _find_sealed_capsule(config: CalibrationConfig, *, repo_root: str | Path, implementation_commit: str):
    root = _root_path(repo_root, config.output_root, field_name="output_root") / "source" / CapsuleStage.SEALED_HOLDOUT.value
    if not root.is_dir():
        raise ContractValidationError("sealed holdout source capsule is missing")
    matches = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.is_dir() and not path.is_symlink():
            try:
                from .artifacts import load_json

                manifest = load_json(path / "manifest.json")
            except ContractValidationError:
                continue
            if type(manifest) is not dict or manifest.get("stage") != CapsuleStage.SEALED_HOLDOUT.value or manifest.get("implementation_commit") != implementation_commit or manifest.get("source_bundle_id") != config.source_bundle_id:
                continue
            capsule = load_capsule(path, expected_stage=CapsuleStage.SEALED_HOLDOUT, expected_source=config, expected_implementation_commit=implementation_commit)
            matches.append(capsule)
    if len(matches) != 1:
        raise ContractValidationError("expected exactly one matching sealed holdout capsule")
    sealed = matches[0]
    if sealed.bars != load_frozen_source(config, repo_root=repo_root):
        raise ContractValidationError("sealed source capsule does not match the frozen V1.5 source")
    return sealed


def select_development_stage(config_path: str | Path, *, repo_root: str | Path, implementation_commit: str | None = None) -> dict[str, object]:
    config = _load_config(config_path, repo_root)
    commit = implementation_commit or repository_commit(repo_root)
    sr_config = resolve_frozen_sr_config(config, repo_root=repo_root)
    development = _load_development_capsule(config, repo_root=repo_root, implementation_commit=commit)
    replays = replay_candidates(development, config.candidate_periods, config=config, resolved_config=sr_config)
    metrics = tuple(compute_candidate_metrics(replay, development, config=config) for replay in replays)
    selection = select_development(metrics, config=config, development_source_id=development.capsule_id, implementation_commit=commit)
    output_root = _root_path(repo_root, config.output_root, field_name="output_root")
    bundle_id, path = publish_development(selection, config, implementation_commit=commit, development_source_id=development.capsule_id, output_root=output_root)
    return {
        "selection_id": selection.selection_id,
        "path": str(path),
        "selected_period": selection.selected_period,
        "development_disposition": selection.disposition.value,
        "bundle_id": bundle_id,
    }


def evaluate_holdout_stage(config_path: str | Path, *, repo_root: str | Path, implementation_commit: str | None = None) -> dict[str, object]:
    config = _load_config(config_path, repo_root)
    commit = implementation_commit or repository_commit(repo_root)
    sr_config = resolve_frozen_sr_config(config, repo_root=repo_root)
    output_root = _root_path(repo_root, config.output_root, field_name="output_root")
    development = _load_development_capsule(config, repo_root=repo_root, implementation_commit=commit)
    selection, development_bundle_id, _ = find_development_bundle(config, output_root=output_root, development_source_id=development.capsule_id, implementation_commit=commit)
    if selection.selected_period is None:
        evaluation = evaluate_holdout_metrics(selection, {}, config=config)
        sealed_source_id = "not_opened"
    else:
        sealed = _find_sealed_capsule(config, repo_root=repo_root, implementation_commit=commit)
        periods = (config.baseline_period, selection.selected_period)
        replays = replay_candidates(sealed, periods, config=config, resolved_config=sr_config)
        holdout_metrics = {}
        for replay in replays:
            holdout_metrics[replay.period] = compute_window_metrics(replay, sealed, config=config, name="holdout", start=config.holdout_start, end=config.holdout_end)
        evaluation = evaluate_holdout_metrics(selection, holdout_metrics, config=config)
        sealed_source_id = sealed.capsule_id
    bundle_id, path = publish_holdout(selection, evaluation, config, implementation_commit=commit, sealed_source_id=sealed_source_id, development_bundle_id=development_bundle_id, output_root=output_root)
    return {
        "holdout_id": evaluation.holdout_id,
        "path": str(path),
        "selected_period": evaluation.selected_period,
        "recommendation": evaluation.recommendation.value,
        "bundle_id": bundle_id,
    }


__all__ = [
    "evaluate_holdout_stage",
    "prepare_source_stage",
    "repository_commit",
    "resolve_frozen_sr_config",
    "select_development_stage",
]
