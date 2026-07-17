"""Network-free orchestration for the SR-V1.10 context semantics audit."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.scripts.baseline_adequacy.artifacts import (
    validate_evaluation_bundle as validate_v19_evaluation,
)
from libs.models.sr.scripts.baseline_adequacy.config import (
    load_baseline_adequacy_config,
)
from libs.models.sr.scripts.baseline_adequacy.runner import (
    FrozenInputs as V19FrozenInputs,
    load_frozen_inputs,
    validate_baseline_parity,
)
from libs.models.sr.scripts.cohort_readiness.contracts import (
    AssetSource,
    AssetEvaluation,
    bars_sha256,
)

from .audit import build_audit
from .config import ContextAuditConfig, load_context_audit_config
from .contracts import AuditResult


@dataclass(frozen=True)
class FrozenContext:
    config: ContextAuditConfig
    v19_config: object
    v19_study: object
    v19_inputs: V19FrozenInputs
    baseline: AssetEvaluation

    @property
    def tao_source(self) -> AssetSource:
        source = self.v19_inputs.tao_source
        if type(source) is not AssetSource:
            raise ContractValidationError("V1.10 source is not an AssetSource")
        return source


def repository_commit(repo_root: str | Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(Path(repo_root).resolve()), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContractValidationError("cannot determine V1.10 implementation commit") from exc


def _root_path(repo_root: str | Path, relative: str, *, field_name: str) -> Path:
    root = Path(repo_root).resolve()
    path = (root / relative).resolve()
    if root not in path.parents and path != root:
        raise ContractValidationError(f"{field_name} escaped repository root")
    return path


def _validate_source(
    config: ContextAuditConfig,
    source: AssetSource,
    *,
    expected_source_bundle_id: str,
) -> None:
    if (
        source.asset != config.asset
        or source.venue != config.venue
        or source.timeframe != config.timeframe
        or source.source_bundle_id != expected_source_bundle_id
        or source.source_id != config.v17_source_member_id
        or source.row_count != config.source_row_count
        or source.first_open_time != config.source_start
        or source.last_closed_at != config.source_end
        or source.provider_calls != 0
        or source.source_kind != "frozen_v1_6"
        or bars_sha256(source.bars) != "703367048f4ed7dc432ca9dfe0ad4afdc5a56eb2a508597ef00bdc3de8b81163"
    ):
        raise ContractValidationError("V1.10 source does not match the approved frozen TAOUSDT prefix")


def load_frozen_context(
    config: ContextAuditConfig,
    *,
    repo_root: str | Path,
    implementation_commit: str,
) -> FrozenContext:
    """Load and revalidate existing V1.9/V1.7/V1.8 evidence without preparation or provider calls."""
    if type(config) is not ContextAuditConfig:
        raise ContractValidationError("V1.10 requires ContextAuditConfig")
    root = Path(repo_root).resolve()
    v19_config = load_baseline_adequacy_config(
        _root_path(root, config.v19_config_path, field_name="inputs.v19.config_path")
    )
    if v19_config.config_hash != config.v19_config_hash:
        raise ContractValidationError("loaded V1.9 configuration identity mismatch")
    v19_path = _root_path(root, config.v19_bundle_path, field_name="inputs.v19.bundle_path")
    v19_study = validate_v19_evaluation(
        v19_path,
        config=v19_config,
        repo_root=root,
        implementation_commit=config.v19_implementation_commit,
        expected_bundle_id=config.v19_bundle_id,
    )
    if (
        v19_study.study_id != config.v19_study_id
        or v19_study.implementation_commit != config.v19_implementation_commit
        or v19_study.decision.disposition.value != config.v19_disposition
    ):
        raise ContractValidationError("loaded V1.9 study identity or disposition mismatch")
    v19_inputs = load_frozen_inputs(v19_config, repo_root=root)
    _validate_source(
        config,
        v19_inputs.tao_source,
        expected_source_bundle_id=v19_inputs.v17_config.tao_source_bundle_id,
    )
    baseline, parity = validate_baseline_parity(
        v19_config,
        v19_inputs,
        implementation_commit=implementation_commit,
    )
    if not parity.passed:
        raise ContractValidationError("V1.10 baseline parity failed")
    return FrozenContext(
        config=config,
        v19_config=v19_config,
        v19_study=v19_study,
        v19_inputs=v19_inputs,
        baseline=baseline,
    )


def compute_audit(
    config: ContextAuditConfig,
    *,
    repo_root: str | Path,
    implementation_commit: str,
) -> tuple[AuditResult, dict[str, object]]:
    frozen = load_frozen_context(
        config,
        repo_root=repo_root,
        implementation_commit=implementation_commit,
    )
    audit = build_audit(
        config,
        study=frozen.v19_study,
        baseline=frozen.baseline,
        source_bars=frozen.tao_source.bars,
        implementation_commit=implementation_commit,
    )
    from .audit import build_chart_payload

    return audit, build_chart_payload(config, audit, frozen.tao_source.bars)


def run_audit(
    config_path: str | Path,
    *,
    repo_root: str | Path,
    implementation_commit: str | None = None,
    output_root: str | Path | None = None,
) -> tuple[str, Path, AuditResult]:
    config = load_context_audit_config(config_path)
    commit = implementation_commit or repository_commit(repo_root)
    audit, chart = compute_audit(
        config,
        repo_root=repo_root,
        implementation_commit=commit,
    )
    from .artifacts import publish_audit_bundle

    bundle_id, path = publish_audit_bundle(
        audit,
        chart,
        config=config,
        output_root=(
            Path(output_root)
            if output_root is not None
            else _root_path(repo_root, config.output_root, field_name="output.root")
        ),
    )
    return bundle_id, path, audit


__all__ = [
    "FrozenContext",
    "compute_audit",
    "load_frozen_context",
    "repository_commit",
    "run_audit",
]
