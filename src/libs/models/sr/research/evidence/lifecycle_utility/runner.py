"""Network-free SR-V1.11 lifecycle utility orchestration."""

from __future__ import annotations

from pathlib import Path
import subprocess

from libs.models.sr.domain import ContractValidationError

from .artifacts import publish_lifecycle_bundle
from .config import LifecycleUtilityConfig, load_lifecycle_utility_config
from .contracts import EventAccounting, LifecycleUtilityStudy
from .extraction import (
    extract_first_resolution_events,
    load_validated_inputs,
    null_cell_for_event,
)
from .metrics import evaluate_metrics
from .outcomes import build_resolution_outcome, compute_wilder_atr_by_bar


def repository_commit(repo_root: str | Path) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(Path(repo_root).resolve()), "rev-parse", "HEAD"], text=True, stderr=subprocess.STDOUT).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContractValidationError("cannot determine V1.11 implementation commit") from exc


def compute_study(
    config: LifecycleUtilityConfig,
    *,
    repo_root: str | Path,
    implementation_commit: str,
) -> LifecycleUtilityStudy:
    if type(config) is not LifecycleUtilityConfig:
        raise ContractValidationError("V1.11 requires LifecycleUtilityConfig")
    inputs = load_validated_inputs(config, repo_root=repo_root, implementation_commit=implementation_commit)
    events = extract_first_resolution_events(inputs.v10_audit, inputs.source_bars, config=config)
    atr_values = compute_wilder_atr_by_bar(inputs.source_bars, period=config.atr_period)
    outcomes = tuple(
        build_resolution_outcome(
            event,
            inputs.source_bars,
            config=config,
            null_cell=null_cell_for_event(event, inputs.null_cells),
            atr_values=atr_values,
        )
        for event in events
    )
    metrics = evaluate_metrics(outcomes, config=config, contract_valid=True)
    accounting = EventAccounting(
        source_case_count=len(inputs.v10_audit.cases),
        resolution_event_count=len(events),
        unique_resolution_zone_count=len({item.zone_id for item in events}),
        false_breakout_count=sum(item.event_class == "FALSE_BREAKOUT" for item in events),
        break_confirmed_count=sum(item.event_class == "BREAK_CONFIRMED" for item in events),
        completed_count=sum(item.completed for item in outcomes),
        right_censored_count=sum(item.right_censored for item in outcomes),
    )
    return LifecycleUtilityStudy(
        implementation_commit=implementation_commit,
        config_hash=config.config_hash,
        v19_bundle_id=config.v19_bundle_id,
        v19_study_id=config.v19_study_id,
        v10_bundle_id=config.v10_bundle_id,
        v10_audit_id=config.v10_audit_id,
        source_bundle_id=config.source_bundle_id,
        source_id=config.source_id,
        bars_sha256=config.bars_sha256,
        null_cells=inputs.null_cells,
        resolutions=events,
        outcomes=outcomes,
        fold_metrics=metrics.fold_metrics,
        aggregate=metrics.aggregate,
        event_accounting=accounting,
        decision=metrics.decision,
    )


def run_study(
    config_path: str | Path,
    *,
    repo_root: str | Path,
    implementation_commit: str | None = None,
    output_root: str | Path | None = None,
) -> tuple[str, Path, LifecycleUtilityStudy]:
    config = load_lifecycle_utility_config(config_path)
    commit = implementation_commit or repository_commit(repo_root)
    study = compute_study(config, repo_root=repo_root, implementation_commit=commit)
    bundle_id, path = publish_lifecycle_bundle(study, config=config, output_root=output_root or (Path(repo_root).resolve() / config.output_root))
    return bundle_id, path, study


__all__ = ["compute_study", "repository_commit", "run_study"]
