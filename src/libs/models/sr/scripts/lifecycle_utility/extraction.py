"""Validated V1.9/V1.10 input loading and first-resolution extraction."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import require_utc
from libs.models.sr.scripts.baseline_trial.contracts import SourceBar
from libs.models.sr.scripts.context_audit.artifacts import validate_audit_bundle
from libs.models.sr.scripts.context_audit.config import (
    ContextAuditConfig,
    load_context_audit_config,
)
from libs.models.sr.scripts.context_audit.contracts import AuditResult
from libs.models.sr.scripts.context_audit.runner import (
    FrozenContext,
    load_frozen_context,
)

from .config import (
    FROZEN_BARS_SHA256,
    FROZEN_FOLD_NAMES,
    FROZEN_GRID_POLICY,
    FROZEN_SOURCE_BUNDLE_ID,
    FROZEN_SOURCE_END,
    FROZEN_SOURCE_ID,
    FROZEN_SOURCE_ROWS,
    FROZEN_SOURCE_START,
    V10_AUDIT_BYTES,
    V10_AUDIT_ID,
    V10_AUDIT_SHA256,
    V10_CHART_BYTES,
    V10_CHART_SHA256,
    V10_CONFIG_HASH,
    V10_MANIFEST_BYTES,
    V10_MANIFEST_SHA256,
    V10_TRACE_ID,
    V10_UPSTREAM_SOURCE_BUNDLE_ID,
    V19_BUNDLE_ID,
    V19_CONFIG_HASH,
    V19_MANIFEST_BYTES,
    V19_MANIFEST_SHA256,
    V19_STUDY_BYTES,
    V19_STUDY_ID,
    V19_STUDY_SHA256,
    LifecycleUtilityConfig,
)
from .contracts import NullCell, ResolutionEvent, effective_side_for_event
from .outcomes import compute_wilder_atr_by_bar


@dataclass(frozen=True)
class ValidatedInputs:
    config: LifecycleUtilityConfig
    v10_config: ContextAuditConfig
    v10_audit: AuditResult
    frozen_context: FrozenContext
    source_bars: tuple[SourceBar, ...]
    null_cells: tuple[NullCell, ...]


def _root_path(repo_root: str | Path, relative: str, *, field_name: str) -> Path:
    root = Path(repo_root).resolve()
    path = (root / relative).resolve()
    if root not in path.parents and path != root:
        raise ContractValidationError(f"{field_name} escaped repository root")
    return path


def _file_identity(path: Path, *, expected_sha256: str, expected_bytes: int, field_name: str) -> None:
    try:
        data = path.read_bytes()
    except (OSError, UnicodeError) as exc:
        raise ContractValidationError(f"cannot read frozen {field_name}: {path}") from exc
    if len(data) != expected_bytes or sha256(data).hexdigest() != expected_sha256:
        raise ContractValidationError(f"frozen {field_name} identity mismatch")


def _validate_v10_config(config: LifecycleUtilityConfig, *, repo_root: Path) -> ContextAuditConfig:
    path = _root_path(repo_root, config.v10_config_path, field_name="inputs.v10.config_path")
    loaded = load_context_audit_config(path)
    if loaded.config_hash != config.v10_config_hash or loaded.config_hash != V10_CONFIG_HASH:
        raise ContractValidationError("V1.10 configuration identity mismatch")
    if loaded.v19_config_hash != V19_CONFIG_HASH or loaded.v19_bundle_id != V19_BUNDLE_ID or loaded.v19_study_id != V19_STUDY_ID:
        raise ContractValidationError("V1.10 upstream V1.9 identity mismatch")
    if loaded.v17_source_bundle_id != V10_UPSTREAM_SOURCE_BUNDLE_ID or loaded.v17_source_member_id != FROZEN_SOURCE_ID:
        raise ContractValidationError("V1.10 source identity mismatch")
    return loaded


def _validate_upstream_artifact_files(config: LifecycleUtilityConfig, *, repo_root: Path) -> None:
    v19_path = _root_path(repo_root, config.v19_bundle_path, field_name="inputs.v19.bundle_path")
    v10_path = _root_path(repo_root, config.v10_bundle_path, field_name="inputs.v10.bundle_path")
    _file_identity(v19_path / "manifest.json", expected_sha256=V19_MANIFEST_SHA256, expected_bytes=V19_MANIFEST_BYTES, field_name="V1.9 manifest")
    _file_identity(v19_path / "study.json", expected_sha256=V19_STUDY_SHA256, expected_bytes=V19_STUDY_BYTES, field_name="V1.9 study")
    _file_identity(v10_path / "manifest.json", expected_sha256=V10_MANIFEST_SHA256, expected_bytes=V10_MANIFEST_BYTES, field_name="V1.10 manifest")
    _file_identity(v10_path / "audit.json", expected_sha256=V10_AUDIT_SHA256, expected_bytes=V10_AUDIT_BYTES, field_name="V1.10 audit")
    _file_identity(v10_path / "chart_payload.json", expected_sha256=V10_CHART_SHA256, expected_bytes=V10_CHART_BYTES, field_name="V1.10 chart payload")


def _validate_source(config: LifecycleUtilityConfig, frozen: FrozenContext) -> tuple[SourceBar, ...]:
    source = frozen.tao_source
    if (
        source.source_bundle_id != config.source_bundle_id
        or source.source_bundle_id != FROZEN_SOURCE_BUNDLE_ID
        or source.source_id != config.source_id
        or source.source_id != FROZEN_SOURCE_ID
        or source.row_count != config.source_row_count
        or source.row_count != FROZEN_SOURCE_ROWS
        or source.first_open_time != config.source_start
        or source.first_open_time != FROZEN_SOURCE_START
        or source.last_closed_at != config.source_end
        or source.last_closed_at != FROZEN_SOURCE_END
        or source.source_kind != "frozen_v1_6"
        or source.provider_calls != 0
        or source.bars_sha256 != config.bars_sha256
        or source.bars_sha256 != FROZEN_BARS_SHA256
        or source.timeframe != "1d"
        or source.asset != "TAOUSDT"
        or source.venue != "binance_usdm"
    ):
        raise ContractValidationError("V1.11 source is not the approved frozen TAOUSDT prefix")
    if source.requested_since != FROZEN_SOURCE_START or source.requested_until != FROZEN_SOURCE_END:
        raise ContractValidationError("V1.11 source requested window is not frozen")
    if source.grid_sha256 == "" or FROZEN_GRID_POLICY != config.source_grid_policy:
        raise ContractValidationError("V1.11 source grid identity is incomplete")
    bars = source.bars
    if type(bars) is not tuple or any(type(bar) is not SourceBar for bar in bars):
        raise ContractValidationError("V1.11 source bars are not typed SourceBar values")
    return bars


def _null_cells(frozen: FrozenContext, config: LifecycleUtilityConfig) -> tuple[NullCell, ...]:
    cells: list[NullCell] = []
    for item in frozen.v19_study.fold_side_nulls:
        cells.append(NullCell(fold=item.fold, effective_side=item.side, control_count=item.control_count, median_quality_atr=item.median_quality, control_ids=item.control_ids))
    cells.sort(key=lambda item: (FROZEN_FOLD_NAMES.index(item.fold), item.effective_side.value))
    expected = {(fold, side) for fold in FROZEN_FOLD_NAMES for side in ("SUPPORT", "RESISTANCE")}
    actual = {(item.fold, item.effective_side.value) for item in cells}
    if actual != expected:
        raise ContractValidationError("V1.9 null controls do not cover every frozen fold/side cell")
    if any(item.control_count < config.readiness.minimum_null_controls_per_compared_cell for item in cells):
        raise ContractValidationError("V1.9 null controls do not meet the V1.11 minimum")
    return tuple(cells)


def load_validated_inputs(
    config: LifecycleUtilityConfig,
    *,
    repo_root: str | Path,
    implementation_commit: str,
) -> ValidatedInputs:
    """Validate existing evidence and frozen source before any utility replay."""
    if type(config) is not LifecycleUtilityConfig:
        raise ContractValidationError("V1.11 requires LifecycleUtilityConfig")
    root = Path(repo_root).resolve()
    _validate_upstream_artifact_files(config, repo_root=root)
    v10_config = _validate_v10_config(config, repo_root=root)
    v10_bundle = _root_path(root, config.v10_bundle_path, field_name="inputs.v10.bundle_path")
    v10_audit = validate_audit_bundle(
        v10_bundle,
        config=v10_config,
        repo_root=root,
        implementation_commit=config.v10_implementation_commit,
        expected_bundle_id=config.v10_bundle_id,
    )
    if v10_audit.audit_id != config.v10_audit_id or v10_audit.audit_id != V10_AUDIT_ID or v10_audit.trace_id != config.v10_trace_id or v10_audit.trace_id != V10_TRACE_ID:
        raise ContractValidationError("V1.10 audit identity mismatch")
    if v10_audit.source_bundle_id != V10_UPSTREAM_SOURCE_BUNDLE_ID or v10_audit.source_id != FROZEN_SOURCE_ID:
        raise ContractValidationError("V1.10 audit source identity mismatch")
    frozen = load_frozen_context(v10_config, repo_root=root, implementation_commit=implementation_commit)
    bars = _validate_source(config, frozen)
    null_cells = _null_cells(frozen, config)
    return ValidatedInputs(config=config, v10_config=v10_config, v10_audit=v10_audit, frozen_context=frozen, source_bars=bars, null_cells=null_cells)


def _fold_for_timestamp(timestamp: Any, config: LifecycleUtilityConfig) -> str:
    timestamp = require_utc(timestamp, field_name="resolution.timestamp")
    for fold in config.folds:
        if fold.start <= timestamp < fold.end:
            return fold.name
    raise ContractValidationError("resolution event lies outside the frozen fold protocol")


def extract_first_resolution_events(
    audit: AuditResult,
    bars: tuple[SourceBar, ...],
    *,
    config: LifecycleUtilityConfig,
) -> tuple[ResolutionEvent, ...]:
    """Select the first approved resolution episode for each unique zone."""
    if type(audit) is not AuditResult:
        raise ContractValidationError("resolution extraction requires a validated AuditResult")
    if type(bars) is not tuple or any(type(bar) is not SourceBar for bar in bars):
        raise ContractValidationError("resolution extraction requires frozen SourceBar values")
    bars_by_id = {bar.bar_id: (index, bar) for index, bar in enumerate(bars)}
    atr_values = compute_wilder_atr_by_bar(bars, period=config.atr_period)
    events: list[ResolutionEvent] = []
    seen_zones: set[str] = set()
    seen_events: set[str] = set()
    for case in audit.cases:
        candidates = sorted(
            (event for event in case.lifecycle_events if event.event_type.value in config.event_classes),
            key=lambda event: (event.timestamp, event.event_id),
        )
        if not candidates:
            continue
        event = candidates[0]
        if case.zone_id in seen_zones or event.event_id in seen_events:
            raise ContractValidationError("resolution events are not unique by zone/event")
        seen_zones.add(case.zone_id)
        seen_events.add(event.event_id)
        if event.zone_id != case.zone_id or event.timestamp < case.zone.available_at:
            raise ContractValidationError("resolution event causality does not reconcile with its zone")
        if event.bar_id not in bars_by_id:
            raise ContractValidationError("resolution event references an unknown frozen bar")
        index, bar = bars_by_id[event.bar_id]
        if event.timestamp != bar.closed_at or index >= len(atr_values) or atr_values[index] is None:
            raise ContractValidationError("resolution event timestamp/bar/ATR alignment is invalid")
        event_fold = _fold_for_timestamp(event.timestamp, config)
        effective_side = effective_side_for_event(event.event_type.value, case.side)
        events.append(
            ResolutionEvent(
                case_id=case.case_id,
                zone_id=case.zone_id,
                event_id=event.event_id,
                event_class=event.event_type.value,
                event_at=event.timestamp,
                event_bar_id=event.bar_id,
                event_fold=event_fold,
                original_side=case.side,
                effective_side=effective_side,
                anchor_close=bar.close,
                atr_at_event=atr_values[index],
                atr_at_creation=case.zone.atr_at_creation,
                center=case.zone.center,
                lower_bound=case.zone.lower_bound,
                upper_bound=case.zone.upper_bound,
            )
        )
    events.sort(key=lambda item: (item.event_at, item.zone_id, item.event_id))
    if len({item.zone_id for item in events}) != len(events):
        raise ContractValidationError("resolution extraction produced duplicate zones")
    return tuple(events)


def null_cell_for_event(event: ResolutionEvent, null_cells: tuple[NullCell, ...]) -> NullCell | None:
    matches = tuple(item for item in null_cells if item.fold == event.event_fold and item.effective_side is event.effective_side)
    if len(matches) > 1:
        raise ContractValidationError("duplicate null cell for resolution event")
    return matches[0] if matches else None


__all__ = [
    "ValidatedInputs", "extract_first_resolution_events", "load_validated_inputs",
    "null_cell_for_event",
]
