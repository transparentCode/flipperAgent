"""Ordered V1.6 development-only stage orchestration."""

from __future__ import annotations

from pathlib import Path
import subprocess

from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.domain.contracts import ContractValidationError

from libs.models.sr.research.studies.baseline_trial.config import (
    load_and_resolve_input_config,
    load_resolved_sr_config,
)

from .artifacts import publish_development
from .candidates import replay_candidates
from .config import CalibrationConfig, load_calibration_config
from .metrics import compute_candidate_metrics
from .selection import select_development
from . import source as source_module


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
    development = source_module.build_development_capsule(config, repo_root=repo_root, implementation_commit=commit)
    output_root = _root_path(repo_root, config.output_root, field_name="output_root")
    development_path = source_module.publish_source_capsule(development, output_root=output_root)
    return {
        "development_source_id": development.capsule_id,
        "development_path": str(development_path),
        "development_row_count": len(development.bars),
    }


def _load_development_capsule(config: CalibrationConfig, *, repo_root: str | Path, implementation_commit: str):
    output_root = _root_path(repo_root, config.output_root, field_name="output_root")
    return source_module.load_published_development_capsule(
        config,
        output_root=output_root,
        implementation_commit=implementation_commit,
    )


def _find_sealed_capsule(config: CalibrationConfig, *, repo_root: str | Path, implementation_commit: str):
    raise ContractValidationError("V1.6 sealed holdout consumption is retired; use a fresh forward-holdout protocol")


def select_development_stage(config_path: str | Path, *, repo_root: str | Path, implementation_commit: str | None = None) -> dict[str, object]:
    config = _load_config(config_path, repo_root)
    commit = implementation_commit or repository_commit(repo_root)
    sr_config = resolve_frozen_sr_config(config, repo_root=repo_root)
    development = _load_development_capsule(config, repo_root=repo_root, implementation_commit=commit)
    replays = replay_candidates(development, config.candidate_periods, config=config, resolved_config=sr_config)
    metrics = tuple(compute_candidate_metrics(replay, development, config=config) for replay in replays)
    selection = select_development(metrics, config=config, development_source_id=development.capsule_id, implementation_commit=commit)
    output_root = _root_path(repo_root, config.output_root, field_name="output_root")
    bundle_id, path = publish_development(
        selection,
        config,
        implementation_commit=commit,
        development_source_id=development.capsule_id,
        output_root=output_root,
        resolved_sr_config_hash=sr_config.resolved_config_hash,
        resolved_input_hash=config.expected_input_hash,
    )
    return {
        "selection_id": selection.selection_id,
        "path": str(path),
        "selected_period": selection.selected_period,
        "development_disposition": selection.disposition.value,
        "bundle_id": bundle_id,
    }


def evaluate_holdout_stage(config_path: str | Path, *, repo_root: str | Path, implementation_commit: str | None = None) -> dict[str, object]:
    raise ContractValidationError("V1.6 holdout evaluation is retired; use a fresh forward-holdout protocol")


__all__ = [
    "evaluate_holdout_stage",
    "prepare_source_stage",
    "repository_commit",
    "resolve_frozen_sr_config",
    "select_development_stage",
]
