"""Native-panel resource preflight and append-only semantic receipts.

The preflight boundary receives authenticated native source records and an
injected evaluator.  It intentionally has no provider or replay dependency;
callers decide how a single asset is evaluated and return a typed measurement.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..contracts import ZoneSide
from ..domain.identity import canonical_hash
from ..research.source import SourceBarRecord
from ..research_lab.data import ResearchSourceSetManifest
from ..research_lab.scientific_compiler import ScientificGroupKey
from .development import ResolvedGlobalGeometryConfig
from .optimizer import ResolvedOptimizerConfig

PREFLIGHT_RECEIPT_SCHEMA = "sr_v2.native_panel_preflight_receipt@2"
EPISODE_ARTIFACT_SCHEMA = "sr_v2.episode_artifact@2"
PREFLIGHT_CODE_POLICY_ID = "sr_v2.native_panel_preflight@2"
_ASSET_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_MEASUREMENT_KEYS = {
    "asset",
    "instrument_id",
    "source_manifest_id",
    "source_sha256",
    "source_slice_fingerprint",
    "episode_artifact_id",
    "episode_artifact_schema",
    "artifact_bytes",
    "provider_call_count",
    "model_fingerprint",
    "baseline_structural_yaml_sha256",
    "target_fingerprint",
    "compiler_fingerprint",
    "family_fingerprint",
    "code_policy_id",
    "steps",
    "candidates",
    "transitions",
    "compiled_observations",
    "expected_groups",
    "present_groups",
    "wall_duration_seconds",
    "peak_rss_bytes",
    "peak_active_lineages",
    "peak_terminal_tombstones",
    "serialized_state_bytes",
    "status",
    "reason",
}


def _nonempty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")
    return value.strip()


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{name} must be SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be hexadecimal SHA-256") from exc
    return value.lower()


class PreflightStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True, kw_only=True)
class PreflightAssetInput:
    """One authenticated native asset panel pinned to a worker."""

    asset: str
    instrument_id: str
    source_manifest: ResearchSourceSetManifest
    bars_by_timeframe: Mapping[str, tuple[SourceBarRecord, ...]]
    source_slice_fingerprint: str
    episode_artifact_id: str
    model_fingerprint: str
    baseline_structural_yaml_sha256: str
    target_fingerprint: str
    compiler_fingerprint: str
    family_fingerprint: str
    code_policy_id: str = PREFLIGHT_CODE_POLICY_ID

    def __post_init__(self) -> None:
        asset = _nonempty(self.asset, "preflight asset")
        instrument = _nonempty(self.instrument_id, "preflight instrument_id")
        if not isinstance(self.source_manifest, ResearchSourceSetManifest):
            raise TypeError("source_manifest must be ResearchSourceSetManifest")
        if (
            not isinstance(self.bars_by_timeframe, Mapping)
            or not self.bars_by_timeframe
        ):
            raise ValueError("bars_by_timeframe must be a non-empty mapping")
        for timeframe, records in self.bars_by_timeframe.items():
            if not isinstance(timeframe, str) or not timeframe.strip():
                raise ValueError("bars_by_timeframe keys must be non-empty strings")
            if (
                not isinstance(records, tuple)
                or not records
                or any(not isinstance(item, SourceBarRecord) for item in records)
            ):
                raise TypeError(
                    "bars_by_timeframe values must be non-empty SourceBarRecord tuples"
                )
        for name in (
            "model_fingerprint",
            "target_fingerprint",
            "compiler_fingerprint",
            "family_fingerprint",
        ):
            _nonempty(getattr(self, name), f"preflight {name}")
        source_slice = _sha256(
            self.source_slice_fingerprint,
            "preflight source_slice_fingerprint",
        )
        artifact_id = _sha256(self.episode_artifact_id, "preflight episode_artifact_id")
        baseline_sha = _sha256(
            self.baseline_structural_yaml_sha256,
            "preflight baseline_structural_yaml_sha256",
        )
        if (
            _nonempty(self.code_policy_id, "preflight code_policy_id")
            != PREFLIGHT_CODE_POLICY_ID
        ):
            raise ValueError("unsupported preflight code policy")
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "instrument_id", instrument)
        object.__setattr__(self, "source_slice_fingerprint", source_slice)
        object.__setattr__(self, "episode_artifact_id", artifact_id)
        object.__setattr__(self, "baseline_structural_yaml_sha256", baseline_sha)
        object.__setattr__(
            self,
            "bars_by_timeframe",
            MappingProxyType(
                {key: tuple(value) for key, value in self.bars_by_timeframe.items()}
            ),
        )
        object.__setattr__(self, "code_policy_id", PREFLIGHT_CODE_POLICY_ID)

    def __getstate__(self) -> Mapping[str, Any]:
        """Keep the immutable boundary pickleable for process workers."""

        return {
            "asset": self.asset,
            "instrument_id": self.instrument_id,
            "source_manifest": self.source_manifest,
            "bars_by_timeframe": dict(self.bars_by_timeframe),
            "source_slice_fingerprint": self.source_slice_fingerprint,
            "episode_artifact_id": self.episode_artifact_id,
            "model_fingerprint": self.model_fingerprint,
            "baseline_structural_yaml_sha256": self.baseline_structural_yaml_sha256,
            "target_fingerprint": self.target_fingerprint,
            "compiler_fingerprint": self.compiler_fingerprint,
            "family_fingerprint": self.family_fingerprint,
            "code_policy_id": self.code_policy_id,
        }

    def __setstate__(self, state: Mapping[str, Any]) -> None:
        for name, value in state.items():
            object.__setattr__(self, name, value)
        object.__setattr__(
            self,
            "bars_by_timeframe",
            MappingProxyType(dict(state["bars_by_timeframe"])),
        )

    @property
    def source_manifest_id(self) -> str:
        return self.source_manifest.manifest_id

    @property
    def source_sha256(self) -> str:
        return self.source_manifest.source_sha256


@dataclass(frozen=True, slots=True, kw_only=True)
class PreflightMeasurement:
    """Typed result returned by one injected single-asset evaluator."""

    asset: str
    instrument_id: str
    source_manifest_id: str
    source_sha256: str
    source_slice_fingerprint: str
    episode_artifact_id: str
    model_fingerprint: str
    baseline_structural_yaml_sha256: str
    target_fingerprint: str
    compiler_fingerprint: str
    family_fingerprint: str
    code_policy_id: str
    steps: int
    candidates: int
    transitions: int
    compiled_observations: int
    expected_groups: tuple[ScientificGroupKey, ...]
    present_groups: tuple[ScientificGroupKey, ...]
    wall_duration_seconds: float
    peak_rss_bytes: int
    artifact_bytes: int
    provider_call_count: int
    peak_active_lineages: int
    peak_terminal_tombstones: int
    serialized_state_bytes: int
    status: PreflightStatus
    reason: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "asset",
            "instrument_id",
            "source_manifest_id",
            "source_sha256",
            "source_slice_fingerprint",
            "episode_artifact_id",
            "model_fingerprint",
            "baseline_structural_yaml_sha256",
            "target_fingerprint",
            "compiler_fingerprint",
            "family_fingerprint",
            "code_policy_id",
        ):
            _nonempty(getattr(self, name), f"measurement {name}")
        _sha256(
            self.baseline_structural_yaml_sha256,
            "measurement baseline_structural_yaml_sha256",
        )
        source_slice = _sha256(
            self.source_slice_fingerprint,
            "measurement source_slice_fingerprint",
        )
        artifact_id = _sha256(
            self.episode_artifact_id, "measurement episode_artifact_id"
        )
        for name in (
            "steps",
            "candidates",
            "transitions",
            "compiled_observations",
            "artifact_bytes",
            "provider_call_count",
            "peak_rss_bytes",
            "peak_active_lineages",
            "peak_terminal_tombstones",
            "serialized_state_bytes",
        ):
            _nonnegative_int(getattr(self, name), f"measurement {name}")
        if (
            isinstance(self.wall_duration_seconds, bool)
            or not isinstance(self.wall_duration_seconds, (int, float))
            or self.wall_duration_seconds < 0
        ):
            raise ValueError("measurement wall_duration_seconds must be non-negative")
        if self.provider_call_count != 0:
            raise ValueError("preflight provider_call_count must be zero")
        if not isinstance(self.status, PreflightStatus):
            raise TypeError("measurement status must be PreflightStatus")
        expected = tuple(self.expected_groups)
        present = tuple(self.present_groups)
        if any(
            not isinstance(group, ScientificGroupKey) for group in expected + present
        ):
            raise TypeError("measurement groups must contain ScientificGroupKey values")
        if len(set(expected)) != len(expected) or len(set(present)) != len(present):
            raise ValueError("measurement groups must be unique")
        if not set(present) <= set(expected):
            raise ValueError("present groups must be a subset of expected groups")
        if self.status is PreflightStatus.FAILED and not self.reason:
            raise ValueError("failed preflight measurement requires a reason")
        if self.code_policy_id != PREFLIGHT_CODE_POLICY_ID:
            raise ValueError(
                "measurement code policy does not match canonical preflight policy"
            )
        object.__setattr__(
            self,
            "baseline_structural_yaml_sha256",
            _sha256(
                self.baseline_structural_yaml_sha256,
                "measurement baseline_structural_yaml_sha256",
            ),
        )
        object.__setattr__(self, "source_slice_fingerprint", source_slice)
        object.__setattr__(self, "episode_artifact_id", artifact_id)
        object.__setattr__(self, "expected_groups", tuple(sorted(expected)))
        object.__setattr__(self, "present_groups", tuple(sorted(present)))

    @property
    def semantic_mapping(self) -> Mapping[str, Any]:
        """Return semantic identity, excluding resource-only measurements."""

        return {
            "asset": self.asset,
            "instrument_id": self.instrument_id,
            "source_manifest_id": self.source_manifest_id,
            "source_sha256": self.source_sha256,
            "source_slice_fingerprint": self.source_slice_fingerprint,
            "episode_artifact_id": self.episode_artifact_id,
            "episode_artifact_schema": EPISODE_ARTIFACT_SCHEMA,
            "model_fingerprint": self.model_fingerprint,
            "baseline_structural_yaml_sha256": self.baseline_structural_yaml_sha256,
            "target_fingerprint": self.target_fingerprint,
            "compiler_fingerprint": self.compiler_fingerprint,
            "family_fingerprint": self.family_fingerprint,
            "code_policy_id": self.code_policy_id,
            "steps": self.steps,
            "candidates": self.candidates,
            "transitions": self.transitions,
            "compiled_observations": self.compiled_observations,
            "expected_groups": self.expected_groups,
            "present_groups": self.present_groups,
            "provider_call_count": self.provider_call_count,
            "peak_active_lineages": self.peak_active_lineages,
            "peak_terminal_tombstones": self.peak_terminal_tombstones,
            "serialized_state_bytes": self.serialized_state_bytes,
            "status": self.status.value,
            "reason": self.reason,
        }

    @property
    def semantic_hash(self) -> str:
        return canonical_hash(self.semantic_mapping)


@dataclass(frozen=True, slots=True, kw_only=True)
class PreflightReceipt:
    measurement: PreflightMeasurement
    semantic_hash: str
    repeat_measurement: PreflightMeasurement | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.measurement, PreflightMeasurement):
            raise TypeError("receipt measurement must be PreflightMeasurement")
        repeat = (
            self.measurement
            if self.repeat_measurement is None
            else self.repeat_measurement
        )
        if not isinstance(repeat, PreflightMeasurement):
            raise TypeError("receipt repeat_measurement must be PreflightMeasurement")
        if repeat.semantic_hash != self.measurement.semantic_hash:
            raise ValueError("preflight comparator measurements differ semantically")
        if self.semantic_hash != self.measurement.semantic_hash:
            raise ValueError("preflight semantic hash does not match measurement")
        object.__setattr__(self, "repeat_measurement", repeat)

    @property
    def asset(self) -> str:
        return self.measurement.asset

    def to_mapping(self) -> Mapping[str, Any]:
        return {
            "schema": PREFLIGHT_RECEIPT_SCHEMA,
            "semantic_hash": self.semantic_hash,
            "measurement": _measurement_mapping(self.measurement),
            "repeat_measurement": _measurement_mapping(self.repeat_measurement),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PreflightRunResult:
    receipts: tuple[PreflightReceipt, ...]
    resumed_assets: tuple[str, ...]

    def __post_init__(self) -> None:
        receipts = tuple(sorted(self.receipts, key=lambda item: item.asset))
        if any(not isinstance(item, PreflightReceipt) for item in receipts):
            raise TypeError("preflight receipts must contain PreflightReceipt values")
        if len({item.asset for item in receipts}) != len(receipts):
            raise ValueError("preflight receipt assets must be unique")
        resumed = tuple(sorted(self.resumed_assets))
        if not set(resumed) <= {item.asset for item in receipts}:
            raise ValueError("resumed assets must be receipt assets")
        object.__setattr__(self, "receipts", receipts)
        object.__setattr__(self, "resumed_assets", resumed)


def validate_global_geometry_resource_preflight(
    config: ResolvedGlobalGeometryConfig,
    result: PreflightRunResult,
) -> None:
    """Validate authenticated primary/repeat resource receipts before execution."""

    if not isinstance(config, ResolvedGlobalGeometryConfig):
        raise TypeError("config must be ResolvedGlobalGeometryConfig")
    if not isinstance(result, PreflightRunResult):
        raise TypeError("result must be PreflightRunResult")
    configured_assets = set(config.source.assets)
    receipts = tuple(result.receipts)
    if any(not isinstance(receipt, PreflightReceipt) for receipt in receipts):
        raise TypeError(
            "global resource preflight receipts must be PreflightReceipt values"
        )
    receipt_assets = tuple(receipt.asset for receipt in receipts)
    if (
        len(receipts) != len(configured_assets)
        or set(receipt_assets) != configured_assets
    ):
        raise ValueError("global resource preflight receipts must cover exact assets")
    if len(set(receipt_assets)) != len(receipt_assets):
        raise ValueError("global resource preflight receipts must have unique assets")
    baseline_fingerprint = config.target_freeze.baseline_model_fingerprint
    retained: dict[tuple[str, str], int] = {}
    for receipt in receipts:
        primary = receipt.measurement
        repeat = receipt.repeat_measurement
        if not isinstance(primary, PreflightMeasurement) or not isinstance(
            repeat, PreflightMeasurement
        ):
            raise TypeError("global resource preflight measurements must be typed")
        if primary.model_fingerprint != baseline_fingerprint:
            raise ValueError("global resource preflight primary is not the baseline")
        if repeat.model_fingerprint != baseline_fingerprint:
            raise ValueError("global resource preflight repeat is not the baseline")
        for measurement in (primary, repeat):
            config.resources.validate_completed_run(
                peak_rss_bytes=measurement.peak_rss_bytes,
                artifact_bytes=measurement.artifact_bytes,
                wall_seconds=measurement.wall_duration_seconds,
            )
        retained[(baseline_fingerprint, receipt.asset)] = primary.artifact_bytes
    config.resources.validate_retained_artifacts(retained)


def _group_mapping(group: ScientificGroupKey) -> Mapping[str, str]:
    return {
        "asset": group.asset,
        "timeframe": group.timeframe,
        "kernel_id": group.kernel_id,
        "kernel_version": group.kernel_version,
        "side": group.side.value,
    }


def _measurement_mapping(measurement: PreflightMeasurement) -> Mapping[str, Any]:
    return {
        "asset": measurement.asset,
        "instrument_id": measurement.instrument_id,
        "source_manifest_id": measurement.source_manifest_id,
        "source_sha256": measurement.source_sha256,
        "source_slice_fingerprint": measurement.source_slice_fingerprint,
        "episode_artifact_id": measurement.episode_artifact_id,
        "episode_artifact_schema": EPISODE_ARTIFACT_SCHEMA,
        "model_fingerprint": measurement.model_fingerprint,
        "baseline_structural_yaml_sha256": measurement.baseline_structural_yaml_sha256,
        "target_fingerprint": measurement.target_fingerprint,
        "compiler_fingerprint": measurement.compiler_fingerprint,
        "family_fingerprint": measurement.family_fingerprint,
        "code_policy_id": measurement.code_policy_id,
        "steps": measurement.steps,
        "candidates": measurement.candidates,
        "transitions": measurement.transitions,
        "compiled_observations": measurement.compiled_observations,
        "expected_groups": [
            _group_mapping(item) for item in measurement.expected_groups
        ],
        "present_groups": [_group_mapping(item) for item in measurement.present_groups],
        "wall_duration_seconds": measurement.wall_duration_seconds,
        "peak_rss_bytes": measurement.peak_rss_bytes,
        "artifact_bytes": measurement.artifact_bytes,
        "provider_call_count": measurement.provider_call_count,
        "peak_active_lineages": measurement.peak_active_lineages,
        "peak_terminal_tombstones": measurement.peak_terminal_tombstones,
        "serialized_state_bytes": measurement.serialized_state_bytes,
        "status": measurement.status.value,
        "reason": measurement.reason,
    }


def _validate_native_panel(
    config: ResolvedOptimizerConfig, asset_input: PreflightAssetInput
) -> None:
    if asset_input.asset not in config.source.assets:
        raise ValueError("preflight asset is outside resolved source assets")
    if config.source.assets[asset_input.asset] != asset_input.instrument_id:
        raise ValueError("preflight instrument does not match resolved source mapping")
    if asset_input.model_fingerprint != config.baseline_config.config_fingerprint:
        raise ValueError("preflight model fingerprint differs from resolved baseline")
    if tuple(asset_input.bars_by_timeframe) != config.source.ladder:
        raise ValueError("preflight sources must cover the exact ordered native ladder")
    bounds = {
        timeframe: (config.source.start, config.source.end)
        for timeframe in config.source.ladder
    }
    asset_input.source_manifest.verify(
        ladder=config.source.ladder,
        venue=config.source.venue,
        instrument_id=asset_input.instrument_id,
        asset=asset_input.asset,
        bounds=bounds,
    )
    for timeframe in config.source.ladder:
        expected = asset_input.source_manifest.source_results[
            config.source.ladder.index(timeframe)
        ].records
        actual = asset_input.bars_by_timeframe[timeframe]
        if actual != expected:
            raise ValueError(
                f"preflight bars do not match authenticated native records for {timeframe}"
            )


def _measurement_from_evaluator(value: object) -> PreflightMeasurement:
    if not isinstance(value, PreflightMeasurement):
        raise TypeError("preflight evaluator must return PreflightMeasurement")
    return value


def _process_evaluate(
    evaluator: Callable[[PreflightAssetInput], PreflightMeasurement],
    asset_input: PreflightAssetInput,
) -> PreflightMeasurement:
    return _measurement_from_evaluator(evaluator(asset_input))


def _measurement_from_mapping(payload: Mapping[str, Any]) -> PreflightMeasurement:
    def group(item: object) -> ScientificGroupKey:
        if not isinstance(item, Mapping) or set(item) != {
            "asset",
            "timeframe",
            "kernel_id",
            "kernel_version",
            "side",
        }:
            raise ValueError("malformed preflight group")
        return ScientificGroupKey(
            asset=item["asset"],
            timeframe=item["timeframe"],
            kernel_id=item["kernel_id"],
            kernel_version=item["kernel_version"],
            side=ZoneSide(item["side"]),
        )

    try:
        if payload.get("episode_artifact_schema") != EPISODE_ARTIFACT_SCHEMA:
            raise ValueError("unsupported episode artifact schema")
        return PreflightMeasurement(
            asset=payload["asset"],
            instrument_id=payload["instrument_id"],
            source_manifest_id=payload["source_manifest_id"],
            source_sha256=payload["source_sha256"],
            source_slice_fingerprint=payload["source_slice_fingerprint"],
            episode_artifact_id=payload["episode_artifact_id"],
            model_fingerprint=payload["model_fingerprint"],
            baseline_structural_yaml_sha256=payload["baseline_structural_yaml_sha256"],
            target_fingerprint=payload["target_fingerprint"],
            compiler_fingerprint=payload["compiler_fingerprint"],
            family_fingerprint=payload["family_fingerprint"],
            code_policy_id=payload["code_policy_id"],
            steps=payload["steps"],
            candidates=payload["candidates"],
            transitions=payload["transitions"],
            compiled_observations=payload["compiled_observations"],
            expected_groups=tuple(group(item) for item in payload["expected_groups"]),
            present_groups=tuple(group(item) for item in payload["present_groups"]),
            wall_duration_seconds=payload["wall_duration_seconds"],
            peak_rss_bytes=payload["peak_rss_bytes"],
            artifact_bytes=payload["artifact_bytes"],
            provider_call_count=payload["provider_call_count"],
            peak_active_lineages=payload["peak_active_lineages"],
            peak_terminal_tombstones=payload["peak_terminal_tombstones"],
            serialized_state_bytes=payload["serialized_state_bytes"],
            status=PreflightStatus(payload["status"]),
            reason=payload["reason"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("malformed preflight measurement") from exc


def _read_existing(path: Path) -> PreflightReceipt:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, Mapping)
            or set(payload)
            != {"schema", "semantic_hash", "measurement", "repeat_measurement"}
            or payload["schema"] != PREFLIGHT_RECEIPT_SCHEMA
        ):
            raise ValueError
        measurements = []
        for name in ("measurement", "repeat_measurement"):
            value = payload[name]
            if not isinstance(value, Mapping) or set(value) != _MEASUREMENT_KEYS:
                raise ValueError
            measurements.append(_measurement_from_mapping(value))
        return PreflightReceipt(
            measurement=measurements[0],
            repeat_measurement=measurements[1],
            semantic_hash=payload["semantic_hash"],
        )
    except Exception as exc:
        raise ValueError(f"malformed preflight receipt: {path}") from exc


def _write_append_only(path: Path, receipt: PreflightReceipt) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("preflight receipt path must not be a symlink")
    encoded = json.dumps(
        receipt.to_mapping(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            temporary.unlink(missing_ok=True)
            raise FileExistsError(f"preflight receipt already exists: {path}")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _verify_measurement(
    config: ResolvedOptimizerConfig,
    asset_input: PreflightAssetInput,
    measurement: PreflightMeasurement,
) -> None:
    expected_groups = tuple(
        sorted(
            ScientificGroupKey(
                asset=asset_input.asset,
                timeframe=timeframe,
                kernel_id=kernel.kernel_id,
                kernel_version=kernel.kernel_version,
                side=side,
            )
            for timeframe in config.source.ladder
            for kernel in config.baseline_config.kernels
            if kernel.enabled_for(timeframe)
            for side in ZoneSide
        )
    )
    if (
        measurement.asset != asset_input.asset
        or measurement.instrument_id != asset_input.instrument_id
    ):
        raise ValueError("preflight measurement asset identity mismatch")
    for name in (
        "source_manifest_id",
        "source_sha256",
        "source_slice_fingerprint",
        "episode_artifact_id",
        "model_fingerprint",
        "baseline_structural_yaml_sha256",
        "target_fingerprint",
        "compiler_fingerprint",
        "family_fingerprint",
    ):
        expected = (
            asset_input.source_manifest_id
            if name == "source_manifest_id"
            else asset_input.source_sha256
            if name == "source_sha256"
            else getattr(asset_input, name)
        )
        if getattr(measurement, name) != expected:
            raise ValueError(f"preflight measurement {name} mismatch")
    if measurement.code_policy_id != asset_input.code_policy_id:
        raise ValueError("preflight measurement code policy mismatch")
    if measurement.expected_groups != expected_groups:
        raise ValueError("preflight measurement expected group ontology mismatch")
    if measurement.present_groups != expected_groups:
        raise ValueError("preflight measurement does not have complete group results")
    if measurement.status is not PreflightStatus.COMPLETED:
        raise ValueError("preflight measurement did not complete")
    if measurement.peak_active_lineages > config.baseline_config.max_active_lineages:
        raise ValueError("preflight active-lineage bound exceeded")
    if (
        measurement.peak_terminal_tombstones
        > config.baseline_config.max_terminal_tombstones
    ):
        raise ValueError("preflight terminal-tombstone bound exceeded")


def run_native_panel_preflight(
    config: ResolvedOptimizerConfig,
    assets: Mapping[str, PreflightAssetInput],
    evaluator: Callable[[PreflightAssetInput], PreflightMeasurement],
    *,
    serial: bool = False,
) -> PreflightRunResult:
    """Run the deterministic repeated comparator and persist per-asset receipts."""

    if not isinstance(config, ResolvedOptimizerConfig):
        raise TypeError("config must be ResolvedOptimizerConfig")
    if not isinstance(assets, Mapping) or set(assets) != set(config.source.assets):
        raise ValueError("preflight assets must cover the exact configured asset set")
    if not callable(evaluator):
        raise TypeError("preflight evaluator must be callable")
    values = tuple(assets[name] for name in sorted(assets))
    for item in values:
        if not isinstance(item, PreflightAssetInput):
            raise TypeError("preflight assets must contain PreflightAssetInput values")
        if item.asset not in assets or assets[item.asset] is not item:
            raise ValueError("preflight asset mapping key differs from asset identity")
        _validate_native_panel(config, item)
    receipt_dir = Path(config.resources.receipt_dir)
    if receipt_dir.is_symlink():
        raise ValueError("preflight receipt directory must not be a symlink")
    existing: dict[str, PreflightReceipt] = {}
    resumed: set[str] = set()
    pending: list[PreflightAssetInput] = []
    for item in values:
        if not _ASSET_FILENAME.fullmatch(item.asset):
            raise ValueError("asset identity is not safe for a receipt filename")
        path = receipt_dir / f"{item.asset}.json"
        if path.exists():
            receipt = _read_existing(path)
            _verify_measurement(config, item, receipt.measurement)
            _verify_measurement(config, item, receipt.repeat_measurement)
            existing[item.asset] = receipt
            resumed.add(item.asset)
        else:
            pending.append(item)
    if not pending:
        return PreflightRunResult(
            receipts=tuple(existing.values()), resumed_assets=tuple(existing)
        )

    # Validate before dispatch so a process cannot begin with a mismatched
    # source or model identity.  No loader or provider is called here.
    first: list[PreflightMeasurement]
    second: list[PreflightMeasurement]
    if serial:
        first = [_measurement_from_evaluator(evaluator(item)) for item in pending]
        second = [_measurement_from_evaluator(evaluator(item)) for item in pending]
    else:
        with ProcessPoolExecutor(max_workers=config.resources.max_workers) as pool:
            first = list(
                pool.map(
                    _process_evaluate,
                    itertools.repeat(evaluator, len(pending)),
                    pending,
                )
            )
        with ProcessPoolExecutor(max_workers=config.resources.max_workers) as pool:
            second = list(
                pool.map(
                    _process_evaluate,
                    itertools.repeat(evaluator, len(pending)),
                    pending,
                )
            )
    if len(first) != len(second):
        raise RuntimeError("preflight comparator runs returned different asset counts")
    for item, left, right in zip(pending, first, second, strict=True):
        _verify_measurement(config, item, left)
        _verify_measurement(config, item, right)
        if left.semantic_hash != right.semantic_hash:
            raise ValueError(f"preflight comparator semantic mismatch for {item.asset}")
    for item, measurement, repeat_measurement in zip(
        pending, first, second, strict=True
    ):
        path = receipt_dir / f"{item.asset}.json"
        receipt = PreflightReceipt(
            measurement=measurement,
            repeat_measurement=repeat_measurement,
            semantic_hash=measurement.semantic_hash,
        )
        if path.exists():
            on_disk = _read_existing(path)
            _verify_measurement(config, item, on_disk.measurement)
            _verify_measurement(config, item, on_disk.repeat_measurement)
            if on_disk.semantic_hash != receipt.semantic_hash:
                raise ValueError(f"preflight receipt identity conflict: {path}")
            existing[item.asset] = on_disk
            resumed.add(item.asset)
        else:
            try:
                _write_append_only(path, receipt)
            except FileExistsError:
                on_disk = _read_existing(path)
                _verify_measurement(config, item, on_disk.measurement)
                _verify_measurement(config, item, on_disk.repeat_measurement)
                if on_disk.semantic_hash != receipt.semantic_hash:
                    raise ValueError(f"preflight receipt identity conflict: {path}")
                existing[item.asset] = on_disk
                resumed.add(item.asset)
            else:
                existing[item.asset] = receipt
    return PreflightRunResult(
        receipts=tuple(existing.values()),
        resumed_assets=tuple(resumed),
    )


__all__ = [
    "EPISODE_ARTIFACT_SCHEMA",
    "PREFLIGHT_CODE_POLICY_ID",
    "PREFLIGHT_RECEIPT_SCHEMA",
    "PreflightAssetInput",
    "PreflightMeasurement",
    "PreflightReceipt",
    "PreflightRunResult",
    "PreflightStatus",
    "run_native_panel_preflight",
    "validate_global_geometry_resource_preflight",
]
