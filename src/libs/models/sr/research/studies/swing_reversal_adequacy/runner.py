"""Network-free orchestration for frozen SR-V2.2 evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from libs.models.sr.domain import ClosedBar, ContractValidationError
from libs.models.sr.research.cohort.artifacts import load_source_bundle
from libs.models.sr.research.cohort.contracts import source_capsule
from libs.models.sr.research.provenance.repository import (
    repository_commit as _repository_commit,
    resolve_repository_path,
)
from libs.models.sr.research.source.capsules import SourceCapsule

from .config import SwingReversalAdequacyConfig, load_swing_reversal_adequacy_config
from .contracts import SwingReversalStudy
from .metrics import build_study
from .outcomes import build_model_bars, build_naive_controls, evaluate_candidates


@dataclass(frozen=True)
class FrozenInputs:
    capsule: SourceCapsule
    model_bars: tuple[ClosedBar, ...]


def repository_commit(repo_root: str | Path) -> str:
    try:
        return _repository_commit(repo_root)
    except ContractValidationError as exc:
        raise ContractValidationError(
            "cannot determine V2.2 implementation commit"
        ) from exc


def load_frozen_inputs(
    config: SwingReversalAdequacyConfig, *, repo_root: str | Path
) -> FrozenInputs:
    if type(config) is not SwingReversalAdequacyConfig:
        raise ContractValidationError("V2.2 requires typed configuration")
    bundle = load_source_bundle(
        resolve_repository_path(
            repo_root, config.source.bundle_path, field_name="source.bundle_path"
        ),
        implementation_commit=config.source.implementation_commit,
        expected_bundle_id=config.source.bundle_id,
    )
    sources = tuple(item for item in bundle.assets if item.asset == config.asset)
    if len(sources) != 1:
        raise ContractValidationError(
            "frozen source bundle does not contain exactly TAOUSDT"
        )
    source = sources[0]
    if (
        source.source_id,
        source.source_bundle_id,
        source.bars_sha256,
        source.grid_sha256,
        source.row_count,
        source.first_open_time,
        source.last_closed_at,
        source.venue,
        source.timeframe,
        source.provider_calls,
        source.source_kind,
    ) != (
        config.source.source_id,
        config.source.source_bundle_id,
        config.source.bars_sha256,
        config.source.grid_sha256,
        config.source.row_count,
        config.source.start,
        config.source.end,
        config.venue,
        config.timeframe,
        0,
        "frozen_v1_6",
    ):
        raise ContractValidationError(
            "frozen TAOUSDT source identity does not match V2.2 configuration"
        )
    capsule = source_capsule(
        source, implementation_commit=config.source.implementation_commit
    )
    if capsule.source_bundle_id != config.source.source_bundle_id:
        raise ContractValidationError(
            "canonical source capsule identity does not match V2.2 source"
        )
    return FrozenInputs(capsule, build_model_bars(capsule, config=config))


def compute_swing_reversal_study(
    config: SwingReversalAdequacyConfig,
    *,
    repo_root: str | Path,
    implementation_commit: str,
) -> SwingReversalStudy:
    frozen = load_frozen_inputs(config, repo_root=repo_root)
    swings, cases = evaluate_candidates(frozen.model_bars, config=config)
    return build_study(
        swings,
        cases,
        build_naive_controls(cases, frozen.model_bars, config=config),
        config=config,
        implementation_commit=implementation_commit,
    )


def run_study(
    config_path: str | Path,
    *,
    repo_root: str | Path,
    implementation_commit: str | None = None,
):
    from .artifacts import publish_study_bundle

    config = load_swing_reversal_adequacy_config(str(config_path))
    commit = implementation_commit or repository_commit(repo_root)
    study = compute_swing_reversal_study(
        config, repo_root=repo_root, implementation_commit=commit
    )
    output_root = resolve_repository_path(
        repo_root, config.artifact.output_root, field_name="artifact.output_root"
    )
    bundle_id, path = publish_study_bundle(
        study, config=config, output_root=output_root
    )
    return bundle_id, path, study


__all__ = [
    "FrozenInputs",
    "compute_swing_reversal_study",
    "load_frozen_inputs",
    "repository_commit",
    "run_study",
]
