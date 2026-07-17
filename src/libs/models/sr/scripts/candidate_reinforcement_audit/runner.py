"""Network-free orchestration for the SR-V1.12 candidate audit."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.research.provenance.repository import (
    repository_commit as _repository_commit,
    resolve_repository_path,
)
from libs.models.sr.scripts.baseline_trial.config import (
    load_and_resolve_input_config,
    load_resolved_sr_config,
)
from libs.models.sr.scripts.baseline_adequacy.config import (
    load_baseline_adequacy_config,
)
from libs.models.sr.scripts.lifecycle_utility.artifacts import (
    validate_lifecycle_bundle,
)
from libs.models.sr.scripts.lifecycle_utility.config import (
    load_lifecycle_utility_config,
)
from libs.models.sr.scripts.lifecycle_utility.extraction import (
    ValidatedInputs,
    load_validated_inputs,
)

from .artifacts import publish_audit_bundle
from .audit import build_audit
from .config import (
    APPROVED_ASSET,
    APPROVED_TIMEFRAME,
    ATR_METHOD,
    ATR_PERIOD,
    ATR_SEED,
    BARS_SHA256,
    BREAK_BUFFER_ATR,
    BREAK_CONFIRM_CLOSES,
    INPUT_CONFIG_HASH,
    MAX_ACTIVE_ZONES,
    MAX_AGE_BARS,
    MERGE_DISTANCE_ATR,
    PIVOT_SPAN_BARS,
    SOURCE_ROWS,
    SR_CONFIG_HASH,
    TOUCH_TOLERANCE_ATR,
    V11_CONFIG_HASH,
    V19_CONFIG_HASH,
    CandidateAuditConfig,
    load_candidate_audit_config,
)


def repository_commit(repo_root: str | Path) -> str:
    try:
        return _repository_commit(repo_root)
    except ContractValidationError as exc:
        raise ContractValidationError("cannot determine V1.12 implementation commit") from exc


def _root_path(repo_root: str | Path, relative: str, *, field_name: str) -> Path:
    return resolve_repository_path(repo_root, relative, field_name=field_name)


def _file_identity(path: Path, *, expected_sha256: str, expected_bytes: int, field_name: str) -> None:
    try:
        data = path.read_bytes()
    except (OSError, UnicodeError) as exc:
        raise ContractValidationError(f"cannot read frozen {field_name}: {path}") from exc
    if len(data) != expected_bytes or sha256(data).hexdigest() != expected_sha256:
        raise ContractValidationError(f"frozen {field_name} identity mismatch")


@dataclass(frozen=True)
class FrozenAuditInputs:
    validated_v11: ValidatedInputs
    resolved_sr: ResolvedSRConfig

    @property
    def model_bars(self) -> tuple[Any, ...]:
        replay = self.validated_v11.frozen_context.baseline.replay
        return tuple(replay.model_bars)

    @property
    def canonical_replay(self) -> Any:
        return self.validated_v11.frozen_context.baseline.replay


def _assert_frozen_sr(config: CandidateAuditConfig, resolved: ResolvedSRConfig) -> None:
    if (
        type(resolved) is not ResolvedSRConfig
        or resolved.asset != config.asset
        or resolved.timeframe != config.timeframe
        or resolved.resolved_config_hash != config.source.sr_config_hash
        or resolved.resolved_config_hash != SR_CONFIG_HASH
    ):
        raise ContractValidationError("resolved SR configuration identity is not frozen")
    if len(resolved.field_provenance) != 8 or any(source != "defaults" for _, source in resolved.field_provenance):
        raise ContractValidationError("V1.12 SR provenance is not global defaults")
    expected = (
        ("detection", "pivot_span_bars", PIVOT_SPAN_BARS),
        ("detection", "zone_half_width_atr", 0.25),
        ("association", "merge_distance_atr", MERGE_DISTANCE_ATR),
        ("lifecycle", "touch_tolerance_atr", TOUCH_TOLERANCE_ATR),
        ("lifecycle", "break_buffer_atr", BREAK_BUFFER_ATR),
        ("lifecycle", "break_confirm_closes", BREAK_CONFIRM_CLOSES),
        ("lifecycle", "max_age_bars", MAX_AGE_BARS),
        ("runtime", "max_active_zones", MAX_ACTIVE_ZONES),
    )
    for section, name, value in expected:
        if getattr(getattr(resolved, section), name) != value:
            raise ContractValidationError(f"frozen SR parameter changed: {section}.{name}")


def _assert_frozen_input(config: CandidateAuditConfig, resolved: Any) -> None:
    if (
        getattr(resolved, "asset", None) != config.asset
        or getattr(resolved, "timeframe", None) != config.timeframe
        or getattr(resolved, "resolved_input_hash", None) != config.source.input_config_hash
        or resolved.resolved_input_hash != INPUT_CONFIG_HASH
    ):
        raise ContractValidationError("resolved ATR input identity is not frozen")
    if (resolved.atr_method, resolved.atr_period, resolved.atr_seed) != (ATR_METHOD, ATR_PERIOD, ATR_SEED):
        raise ContractValidationError("ATR input is not frozen Wilder RMA(14)/SMA")
    if len(resolved.field_provenance) != 3 or any(source != "defaults" for _, source in resolved.field_provenance):
        raise ContractValidationError("V1.12 ATR provenance is not global defaults")


def _validate_upstream_v11(config: CandidateAuditConfig, *, root: Path) -> None:
    manifest = _root_path(root, config.v11.bundle_path, field_name="inputs.v11.bundle_path") / "manifest.json"
    study = _root_path(root, config.v11.bundle_path, field_name="inputs.v11.bundle_path") / "study.json"
    _file_identity(manifest, expected_sha256=config.v11.manifest_sha256, expected_bytes=config.v11.manifest_bytes, field_name="V1.11 manifest")
    _file_identity(study, expected_sha256=config.v11.study_sha256, expected_bytes=config.v11.study_bytes, field_name="V1.11 study")


def _validate_inputs(config: CandidateAuditConfig, *, repo_root: str | Path, implementation_commit: str) -> FrozenAuditInputs:
    root = Path(repo_root).resolve()
    v11_path = _root_path(root, config.v11.config_path, field_name="inputs.v11.config_path")
    v11_config = load_lifecycle_utility_config(v11_path)
    if v11_config.config_hash != config.v11.config_hash or v11_config.config_hash != V11_CONFIG_HASH:
        raise ContractValidationError("V1.11 configuration identity mismatch")
    _validate_upstream_v11(config, root=root)
    v11_bundle = _root_path(root, config.v11.bundle_path, field_name="inputs.v11.bundle_path")
    validated_study = validate_lifecycle_bundle(
        v11_bundle,
        config=v11_config,
        repo_root=root,
        implementation_commit=config.v11.implementation_commit,
        expected_bundle_id=config.v11.bundle_id,
    )
    if validated_study.study_id != config.v11.study_id or validated_study.decision.disposition.value != "LIFECYCLE_CONTEXT_NOT_SUPPORTED":
        raise ContractValidationError("V1.11 study identity or disposition mismatch")

    validated = load_validated_inputs(
        v11_config,
        repo_root=root,
        implementation_commit=implementation_commit,
    )
    source = validated.frozen_context.tao_source
    if (
        source.source_bundle_id != config.source.source_bundle_id
        or source.source_id != config.source.source_id
        or source.row_count != config.source.row_count
        or source.first_open_time != config.source.start
        or source.last_closed_at != config.source.end
        or source.bars_sha256 != config.source.bars_sha256
        or source.provider_calls != 0
        or source.source_kind != "frozen_v1_6"
        or source.asset != APPROVED_ASSET
        or source.timeframe != APPROVED_TIMEFRAME
    ):
        raise ContractValidationError("V1.12 source is not the approved frozen TAOUSDT prefix")
    if len(source.bars) != SOURCE_ROWS or source.bars_sha256 != BARS_SHA256:
        raise ContractValidationError("V1.12 source bars identity mismatch")

    v19_path = _root_path(root, config.v19.config_path, field_name="inputs.v19.config_path")
    v19_config = load_baseline_adequacy_config(v19_path)
    if v19_config.config_hash != config.v19.config_hash or v19_config.config_hash != V19_CONFIG_HASH:
        raise ContractValidationError("V1.9 configuration identity mismatch")
    if v19_config.asset != config.asset or v19_config.timeframe != config.timeframe:
        raise ContractValidationError("V1.9 configuration scope mismatch")
    replay = validated.frozen_context.baseline.replay
    if replay.common_start_index != config.replay.common_start_index or replay.common_start_index != v19_config.common_start_period:
        raise ContractValidationError("canonical replay common-start boundary is not frozen")
    if replay.period != config.replay.atr_period or replay.reference_period != config.replay.atr_period:
        raise ContractValidationError("canonical replay ATR protocol is not frozen")
    resolved_sr = load_resolved_sr_config(_root_path(root, config.source.sr_config_path, field_name="inputs.frozen.sr_config_path"), asset=config.asset, timeframe=config.timeframe)
    resolved_input = load_and_resolve_input_config(_root_path(root, config.source.input_config_path, field_name="inputs.frozen.input_config_path"), asset=config.asset, timeframe=config.timeframe)
    _assert_frozen_sr(config, resolved_sr)
    _assert_frozen_input(config, resolved_input)
    return FrozenAuditInputs(validated_v11=validated, resolved_sr=resolved_sr)


def compute_audit(
    config: CandidateAuditConfig,
    *,
    repo_root: str | Path,
    implementation_commit: str,
):
    if type(config) is not CandidateAuditConfig:
        raise ContractValidationError("V1.12 requires CandidateAuditConfig")
    frozen = _validate_inputs(config, repo_root=repo_root, implementation_commit=implementation_commit)
    return build_audit(
        frozen.model_bars,
        frozen.resolved_sr,
        config=config,
        source_case_count=len(frozen.validated_v11.v10_audit.cases),
        canonical_replay=frozen.canonical_replay,
        implementation_commit=implementation_commit,
    )


def run_audit(
    config_path: str | Path,
    *,
    repo_root: str | Path,
    implementation_commit: str | None = None,
    output_root: str | Path | None = None,
) -> tuple[str, Path, Any]:
    config = load_candidate_audit_config(config_path)
    commit = implementation_commit or repository_commit(repo_root)
    audit = compute_audit(config, repo_root=repo_root, implementation_commit=commit)
    destination = Path(output_root) if output_root is not None else _root_path(repo_root, config.artifact.output_root, field_name="artifact.output_root")
    bundle_id, path = publish_audit_bundle(audit, config=config, output_root=destination)
    return bundle_id, path, audit


__all__ = ["FrozenAuditInputs", "compute_audit", "repository_commit", "run_audit"]
