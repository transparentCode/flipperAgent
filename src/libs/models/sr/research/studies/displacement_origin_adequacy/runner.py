"""Network-free orchestration for the frozen SR-V2.0 experiment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.research.cohort.artifacts import load_source_bundle
from libs.models.sr.research.provenance.repository import (
    repository_commit as _repository_commit,
    resolve_repository_path,
)
from libs.models.sr.research.source.capsules import CapsuleStage, SourceCapsule

from .config import DisplacementOriginAdequacyConfig, load_displacement_origin_adequacy_config
from .contracts import DisplacementOriginStudy
from .metrics import build_study
from .outcomes import build_matched_controls, build_model_bars, evaluate_candidates


@dataclass(frozen=True)
class FrozenInputs:
    capsule: SourceCapsule
    model_bars: tuple


def repository_commit(repo_root: str | Path) -> str:
    try:
        return _repository_commit(repo_root)
    except ContractValidationError as exc:
        raise ContractValidationError("cannot determine V2.0 implementation commit") from exc


def load_frozen_inputs(
    config: DisplacementOriginAdequacyConfig,
    *,
    repo_root: str | Path,
) -> FrozenInputs:
    """Load and validate the published development source without providers."""
    if type(config) is not DisplacementOriginAdequacyConfig:
        raise ContractValidationError("V2.0 requires typed configuration")
    source_path = resolve_repository_path(
        repo_root,
        config.source.bundle_path,
        field_name="source.bundle_path",
    )
    bundle = load_source_bundle(
        source_path,
        implementation_commit=config.source.implementation_commit,
        expected_bundle_id=config.source.bundle_id,
    )
    sources = tuple(item for item in bundle.assets if item.asset == config.asset)
    if len(sources) != 1:
        raise ContractValidationError("frozen source bundle does not contain exactly TAOUSDT")
    source = sources[0]
    if (
        source.source_id != config.source.source_id
        or source.source_bundle_id != config.source.source_bundle_id
        or source.bars_sha256 != config.source.bars_sha256
        or source.grid_sha256 != config.source.grid_sha256
        or source.row_count != config.source.row_count
        or source.first_open_time != config.source.start
        or source.last_closed_at != config.source.end
        or source.venue != config.venue
        or source.timeframe != config.timeframe
        or source.provider_calls != 0
        or source.source_kind != "frozen_v1_6"
    ):
        raise ContractValidationError("frozen TAOUSDT source identity does not match V2.0 configuration")
    capsule = SourceCapsule(
        stage=CapsuleStage.DEVELOPMENT,
        source_bundle_id=config.source.bundle_id,
        source_bars_sha256=source.bars_sha256,
        source_row_count=source.row_count,
        split_boundary=datetime(2026, 1, 1, tzinfo=timezone.utc),
        implementation_commit=config.source.implementation_commit,
        bars=source.bars,
    )
    model_bars = build_model_bars(capsule, config=config)
    return FrozenInputs(capsule=capsule, model_bars=model_bars)


def compute_displacement_origin_study(
    config: DisplacementOriginAdequacyConfig,
    *,
    repo_root: str | Path,
    implementation_commit: str,
) -> DisplacementOriginStudy:
    if type(config) is not DisplacementOriginAdequacyConfig:
        raise ContractValidationError("V2.0 requires typed configuration")
    frozen = load_frozen_inputs(config, repo_root=repo_root)
    cases = evaluate_candidates(frozen.model_bars, config=config)
    controls = build_matched_controls(cases, frozen.model_bars, config=config)
    return build_study(
        cases,
        controls,
        config=config,
        implementation_commit=implementation_commit,
    )


def run_study(
    config_path: str | Path,
    *,
    repo_root: str | Path,
    implementation_commit: str | None = None,
):
    """Compute and publish V2.0 evidence using the configured destination."""
    from .artifacts import publish_study_bundle

    config = load_displacement_origin_adequacy_config(str(config_path))
    commit = implementation_commit or repository_commit(repo_root)
    study = compute_displacement_origin_study(
        config,
        repo_root=repo_root,
        implementation_commit=commit,
    )
    output_root = resolve_repository_path(
        repo_root,
        config.artifact.output_root,
        field_name="artifact.output_root",
    )
    bundle_id, path = publish_study_bundle(study, config=config, output_root=output_root)
    return bundle_id, path, study


__all__ = [
    "FrozenInputs",
    "compute_displacement_origin_study",
    "load_frozen_inputs",
    "repository_commit",
    "run_study",
]
