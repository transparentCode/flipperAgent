"""Read-only validation-window diagnosis for the rejected candidate trial."""

# ruff: noqa: E402

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for import_root in (PROJECT_ROOT, SRC_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from libs.models.trendline_family.config import ResolvedTrendlineFamilyConfig
from libs.models.trendline_family.config_resolver import TrendlineFamilyConfigResolver
from libs.models.trendline_family.contracts import ContractValidationError, LineCandidate
from libs.models.trendline_family.optimization.contracts import (
    OptimizationStage,
    TrialResult,
    canonical_json,
    primitive,
    semantic_id,
)
from libs.models.trendline_family.optimization.evaluator import apply_stage_overrides
from libs.models.trendline_family.optimization.folds import ImmutableHistoricalFrame, WalkForwardFold
from libs.models.trendline_family.provider import (
    CandidateGenerationStatus,
    NativeDeterministicLineProvider,
)
from libs.models.trendline_family.research_lab.artifacts import PhaseIArtifactBrowser
from scripts import build_trendline_family_candidate_evidence_report as evidence_report


DIAGNOSIS_SCHEMA_VERSION = "trendline_family_candidate_rejection_diagnosis_v1"
TRIAL_NAME = "btcusdt_4h_20250801_20251201_candidate_geometry_v2"
V1_TRIAL_NAME = "btcusdt_4h_20250801_20251201_candidate_geometry_v1"
TRIAL_ROOT_BASE = PROJECT_ROOT / "artifacts" / "trendline_family_candidate_trials"
V1_TRIAL_ROOT = TRIAL_ROOT_BASE / V1_TRIAL_NAME
V2_TRIAL_ROOT = TRIAL_ROOT_BASE / TRIAL_NAME
REPORT_ROOT = PROJECT_ROOT / "artifacts" / "trendline_family_candidate_reports" / TRIAL_NAME
OUTPUT_ROOT = PROJECT_ROOT / "artifacts" / "trendline_family_candidate_diagnostics" / TRIAL_NAME
CONFIG_PATH = PROJECT_ROOT / "configs" / "trendline_family.yaml"

EXPECTED_DATASET_HASH = "trendline-family-dataset_ccaf20405ffc4b84ea98f79e97053e3ee6be4b0c571999dcbf5fc0e0bca1ad53"
EXPECTED_CONFIG_HASH = "da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f"
EXPECTED_PHASE_I_RUN_ID = "trendline-family-phase-i-run_6393c4d86edb7558045b96e5c5be39fd915d8a8dde29b44e66515fdbf44b37e7"
EXPECTED_REPORT_ID = "trendline-family-candidate-evidence-report_5e01522b2ac82f67e6a722372e6deba4ea77c7fe9ea47b5415ef7d65bc3d2d41"
EXPECTED_RECOMMENDATION_ID = "trendline-family-promotion-recommendation_fdcf8d4b39ffda53b3f09b26ff28bec40056677ce18cc90eb2292b310005ccbc"
APPROVED_CONFIG_SHA256 = "7a7fbc156a0ed3e01ac5b3d7502a76e834d6b34668daa8a569f32b4e63a887d8"
EXPECTED_CONFIG_RELATIVE_PATH = "configs/trendline_family.yaml"
EXPECTED_REPORT_FILES = (
    "evidence_report.json",
    "evidence_report.md",
    "report_manifest.json",
    "source_inventory.json",
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
EXPECTED_GRID = frozenset(
    canonical_json({"candidate.lookback_bars": lookback, "candidate.min_candidate_quality": quality})
    for lookback in (120, 180, 240)
    for quality in (0.30, 0.40)
)
STATUS_NAMES = tuple(status.value for status in CandidateGenerationStatus)


class RejectionDiagnosisError(ContractValidationError):
    """Raised when immutable evidence or a diagnostic invariant is invalid."""


@dataclass(frozen=True)
class ConfigurationReplay:
    label: str
    trial_id: str
    result_id: str
    overrides: Mapping[str, Any]
    config: ResolvedTrendlineFamilyConfig
    result: TrialResult


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _read_json(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise RejectionDiagnosisError(f"required diagnosis file is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RejectionDiagnosisError(f"invalid diagnosis JSON: {path}") from exc
    if not isinstance(payload, Mapping):
        raise RejectionDiagnosisError(f"diagnosis JSON must be a mapping: {path}")
    return payload


def _iso(value: Any) -> str:
    timestamp = value.isoformat()
    return timestamp.replace("+00:00", "Z")


def _file_inventory(root: Path, *, source_name: str, expected_files: Sequence[str] | None = None) -> Mapping[str, Any]:
    if not root.is_dir():
        raise RejectionDiagnosisError(f"source root is missing: {root}")
    files = tuple(
        {
            "relative_path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_bytes(path.read_bytes()),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )
    if not files:
        raise RejectionDiagnosisError(f"source root has no files: {root}")
    if expected_files is not None and tuple(item["relative_path"] for item in files) != tuple(expected_files):
        raise RejectionDiagnosisError(f"source files differ from approved set: {source_name}")
    semantic = {"source_name": source_name, "root_name": root.name, "files": files}
    return {**semantic, "inventory_sha256": _sha256_bytes(canonical_json(semantic).encode("utf-8"))}


def capture_source_binding(*, v1_root: Path, v2_root: Path, report_root: Path, config_path: Path) -> Mapping[str, Any]:
    """Capture raw source bytes before and after diagnostic execution."""

    trial_inventories = evidence_report.capture_source_inventories(v1_root=v1_root, v2_root=v2_root)
    report_inventory = _file_inventory(
        report_root,
        source_name="approved_report_bundle",
        expected_files=("evidence_report.json", "evidence_report.md", "report_manifest.json", "source_inventory.json"),
    )
    if not config_path.is_file():
        raise RejectionDiagnosisError("approved trendline-family config is missing")
    config_bytes = config_path.read_bytes()
    try:
        config_relative_path = config_path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        # Tests use a copied approved YAML outside the repository tree.
        config_relative_path = config_path.name
    config_inventory = {
        "relative_path": config_relative_path,
        "size_bytes": len(config_bytes),
        "sha256": _sha256_bytes(config_bytes),
    }
    semantic = {
        "diagnosis_schema_version": DIAGNOSIS_SCHEMA_VERSION,
        "trial_inventories": trial_inventories,
        "approved_report_inventory": report_inventory,
        "config_inventory": config_inventory,
    }
    return {
        **semantic,
        "source_binding_id": semantic_id("trendline-family-candidate-rejection-source-binding", semantic),
    }


def _require_sha256(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise RejectionDiagnosisError(f"{field_name} must be a lowercase 64-character SHA-256")
    return value


def _validate_relative_path(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RejectionDiagnosisError(f"{field_name} must be a non-empty string")
    if value.startswith("/") or "\\" in value:
        raise RejectionDiagnosisError(f"{field_name} must be a canonical POSIX relative path")
    if any(segment in {"", ".", ".."} for segment in value.split("/")):
        raise RejectionDiagnosisError(f"{field_name} contains an unsafe path segment")
    return value


def _validate_inventory_files(
    value: Any,
    *,
    field_name: str,
    expected_paths: Sequence[str] | None = None,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise RejectionDiagnosisError(f"{field_name} must be a non-empty sequence")
    files: list[Mapping[str, Any]] = []
    paths: list[str] = []
    for index, raw_file in enumerate(value):
        if not isinstance(raw_file, Mapping) or set(raw_file) != {"relative_path", "size_bytes", "sha256"}:
            raise RejectionDiagnosisError(f"{field_name} record {index} fields are invalid")
        relative_path = _validate_relative_path(raw_file.get("relative_path"), field_name=f"{field_name} record {index} relative_path")
        size_bytes = raw_file.get("size_bytes")
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
            raise RejectionDiagnosisError(f"{field_name} record {index} size_bytes is invalid")
        files.append(
            {
                "relative_path": relative_path,
                "size_bytes": size_bytes,
                "sha256": _require_sha256(raw_file.get("sha256"), field_name=f"{field_name} record {index} sha256"),
            }
        )
        paths.append(relative_path)
    if len(set(paths)) != len(paths):
        raise RejectionDiagnosisError(f"{field_name} paths must be unique")
    if paths != sorted(paths):
        raise RejectionDiagnosisError(f"{field_name} paths must be strictly sorted")
    if expected_paths is not None and tuple(paths) != tuple(expected_paths):
        raise RejectionDiagnosisError(f"{field_name} differs from the approved file set")
    return tuple(files)


def _validated_trial_inventories(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RejectionDiagnosisError("trial inventories must be a mapping")
    try:
        evidence_report.validate_source_inventory_payload(value)
    except evidence_report.EvidenceReportError as exc:
        raise RejectionDiagnosisError(f"trial inventories are invalid: {exc}") from exc

    raw_sources = value["sources"]
    sources: dict[str, Mapping[str, Any]] = {}
    for source_name in ("v1", "v2"):
        raw_source = raw_sources[source_name]
        files = _validate_inventory_files(raw_source["files"], field_name=f"trial inventory {source_name} files")
        sources[source_name] = {
            "source_name": raw_source["source_name"],
            "trial_name": raw_source["trial_name"],
            "files": files,
            "inventory_sha256": raw_source["inventory_sha256"],
        }
    semantic = {
        "report_schema_version": evidence_report.REPORT_SCHEMA_VERSION,
        "sources": sources,
    }
    return {
        **semantic,
        "source_inventory_id": semantic_id("trendline-family-candidate-source-inventory", semantic),
    }


def _validated_report_inventory(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"source_name", "root_name", "files", "inventory_sha256"}:
        raise RejectionDiagnosisError("approved report inventory fields are invalid")
    if value.get("source_name") != "approved_report_bundle":
        raise RejectionDiagnosisError("approved report inventory source_name mismatch")
    if value.get("root_name") != TRIAL_NAME:
        raise RejectionDiagnosisError("approved report inventory root_name mismatch")
    files = _validate_inventory_files(
        value.get("files"),
        field_name="approved report inventory files",
        expected_paths=EXPECTED_REPORT_FILES,
    )
    semantic = {
        "source_name": "approved_report_bundle",
        "root_name": TRIAL_NAME,
        "files": files,
    }
    derived_hash = _sha256_bytes(canonical_json(semantic).encode("utf-8"))
    if _require_sha256(value.get("inventory_sha256"), field_name="approved report inventory inventory_sha256") != derived_hash:
        raise RejectionDiagnosisError("approved report inventory_sha256 mismatch")
    return {**semantic, "inventory_sha256": derived_hash}


def _validated_config_inventory(value: Any, *, expected_relative_path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"relative_path", "size_bytes", "sha256"}:
        raise RejectionDiagnosisError("config inventory fields are invalid")
    relative_path = _validate_relative_path(value.get("relative_path"), field_name="config inventory relative_path")
    if relative_path != expected_relative_path:
        raise RejectionDiagnosisError("config inventory relative_path differs from the approved config")
    size_bytes = value.get("size_bytes")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
        raise RejectionDiagnosisError("config inventory size_bytes is invalid")
    config_sha256 = _require_sha256(value.get("sha256"), field_name="config inventory sha256")
    if config_sha256 != APPROVED_CONFIG_SHA256:
        raise RejectionDiagnosisError("config inventory sha256 differs from the approved YAML")
    return {"relative_path": relative_path, "size_bytes": size_bytes, "sha256": config_sha256}


def validate_source_binding_payload(
    value: Mapping[str, Any],
    *,
    expected_config_relative_path: str = EXPECTED_CONFIG_RELATIVE_PATH,
) -> Mapping[str, Any]:
    """Purely validate and canonicalize the rejection-diagnosis provenance binding."""

    expected_fields = {
        "diagnosis_schema_version",
        "trial_inventories",
        "approved_report_inventory",
        "config_inventory",
        "source_binding_id",
    }
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise RejectionDiagnosisError("source binding top-level fields are invalid")
    if value.get("diagnosis_schema_version") != DIAGNOSIS_SCHEMA_VERSION:
        raise RejectionDiagnosisError("source binding schema version mismatch")

    semantic = {
        "diagnosis_schema_version": DIAGNOSIS_SCHEMA_VERSION,
        "trial_inventories": _validated_trial_inventories(value.get("trial_inventories")),
        "approved_report_inventory": _validated_report_inventory(value.get("approved_report_inventory")),
        "config_inventory": _validated_config_inventory(
            value.get("config_inventory"),
            expected_relative_path=expected_config_relative_path,
        ),
    }
    derived_id = semantic_id("trendline-family-candidate-rejection-source-binding", semantic)
    if value.get("source_binding_id") != derived_id:
        raise RejectionDiagnosisError("source binding ID mismatch")
    return {**semantic, "source_binding_id": derived_id}


def _validate_source_binding_against_report(
    *, source_binding: Mapping[str, Any], verified_report: Mapping[str, Any]
) -> None:
    report_source = verified_report.get("source_inventory")
    trial_inventories = source_binding.get("trial_inventories")
    if not isinstance(report_source, Mapping) or not isinstance(trial_inventories, Mapping):
        raise RejectionDiagnosisError("source/report inventory payload is malformed")
    if canonical_json(report_source.get("sources")) != canonical_json(trial_inventories.get("sources")):
        raise RejectionDiagnosisError("approved report source inventory differs from source trial roots")


def _validate_fold_plan(*, browser: PhaseIArtifactBrowser, dataset: ImmutableHistoricalFrame) -> tuple[WalkForwardFold, ...]:
    fold_plan = browser.bundle.fold_plan
    if fold_plan.data_hash != EXPECTED_DATASET_HASH or fold_plan.data_hash != dataset.dataset_hash:
        raise RejectionDiagnosisError("fold-plan dataset identity mismatch")
    folds = tuple(sorted(fold_plan.folds, key=lambda item: item.fold_index))
    if len(folds) != 3 or tuple(fold.fold_index for fold in folds) != (0, 1, 2):
        raise RejectionDiagnosisError("diagnosis requires exactly three ordered validation folds")
    if fold_plan.label_horizon_bars != 12 or fold_plan.holdout.window.bar_count != 96:
        raise RejectionDiagnosisError("fold plan label horizon or planned holdout differs from approved trial")
    for fold in folds:
        if fold.validation.bar_count != 96 or fold.purge_bars != 12 or fold.embargo_bars != 0:
            raise RejectionDiagnosisError("validation fold does not match approved replay boundaries")
        if fold.validation.end_position >= fold_plan.holdout.window.start_position:
            raise RejectionDiagnosisError("validation replay would enter planned holdout")
        if fold.asset != dataset.asset or fold.timeframe != dataset.timeframe:
            raise RejectionDiagnosisError("validation fold asset/timeframe identity mismatch")
    if sum(fold.validation.bar_count for fold in folds) != 288:
        raise RejectionDiagnosisError("validation replay position count must equal 288")
    return folds


def _configuration_matrix(
    *, baseline_config: ResolvedTrendlineFamilyConfig, browser: PhaseIArtifactBrowser
) -> tuple[ConfigurationReplay, ...]:
    baseline = browser.baseline_validation
    if dict(baseline.trial.parameter_overrides):
        raise RejectionDiagnosisError("baseline validation unexpectedly has overrides")
    if baseline.trial.baseline_config_hash != baseline_config.resolved_config_hash:
        raise RejectionDiagnosisError("baseline trial config hash differs from resolved config")
    primary = tuple(sorted(browser.trials, key=lambda item: (canonical_json(item.trial.parameter_overrides), item.trial.trial_id)))
    if len(primary) != 6 or {canonical_json(item.trial.parameter_overrides) for item in primary} != EXPECTED_GRID:
        raise RejectionDiagnosisError("primary trial overrides do not equal approved six-trial grid")
    if any(item.trial.stage is not OptimizationStage.CANDIDATE_GEOMETRY for item in primary):
        raise RejectionDiagnosisError("diagnosis source includes a non-candidate primary trial")
    entries = [
        ConfigurationReplay(
            label="baseline",
            trial_id=baseline.trial.trial_id,
            result_id=baseline.result_id,
            overrides={},
            config=baseline_config,
            result=baseline,
        )
    ]
    for result in primary:
        config = apply_stage_overrides(
            baseline_config,
            stage=OptimizationStage.CANDIDATE_GEOMETRY,
            overrides=result.trial.parameter_overrides,
        )
        if result.trial.baseline_config_hash != baseline_config.resolved_config_hash:
            raise RejectionDiagnosisError("primary trial baseline config identity mismatch")
        entries.append(
            ConfigurationReplay(
                label=result.trial.trial_id,
                trial_id=result.trial.trial_id,
                result_id=result.result_id,
                overrides=dict(result.trial.parameter_overrides),
                config=config,
                result=result,
            )
        )
    return tuple(sorted(entries, key=lambda item: (canonical_json(item.overrides), item.trial_id)))


def load_diagnosis_sources(
    *,
    v1_root: Path = V1_TRIAL_ROOT,
    v2_root: Path = V2_TRIAL_ROOT,
    report_root: Path = REPORT_ROOT,
    config_path: Path = CONFIG_PATH,
) -> tuple[Mapping[str, Any], Mapping[str, Any], ImmutableHistoricalFrame, PhaseIArtifactBrowser, tuple[WalkForwardFold, ...], tuple[ConfigurationReplay, ...]]:
    """Verify every immutable source before a provider call is permitted."""

    source_binding = capture_source_binding(
        v1_root=v1_root, v2_root=v2_root, report_root=report_root, config_path=config_path
    )
    try:
        verified_report = evidence_report.validate_report_bundle(output_root=report_root)
        input_evidence, _, dataset = evidence_report.verify_input_evidence(v2_root=v2_root)
        browser = evidence_report.verify_phase_i_evidence(v2_root=v2_root, dataset=dataset)
    except ContractValidationError as exc:
        raise RejectionDiagnosisError(f"approved source validation failed: {exc}") from exc
    _validate_source_binding_against_report(source_binding=source_binding, verified_report=verified_report)
    report_identity = verified_report["evidence_report"].get("report_identity", {})
    if report_identity.get("report_id") != EXPECTED_REPORT_ID:
        raise RejectionDiagnosisError("approved report identity mismatch")
    if browser.manifest.run_id != EXPECTED_PHASE_I_RUN_ID or browser.recommendation.recommendation_id != EXPECTED_RECOMMENDATION_ID:
        raise RejectionDiagnosisError("Phase-I run or recommendation identity mismatch")
    if dataset.row_count != 732 or dataset.dataset_hash != EXPECTED_DATASET_HASH:
        raise RejectionDiagnosisError("normalized source dataset identity mismatch")
    resolver = TrendlineFamilyConfigResolver.from_path(config_path)
    baseline_config = resolver.resolve(asset="BTCUSDT", timeframe="4h")
    if baseline_config.resolved_config_hash != EXPECTED_CONFIG_HASH:
        raise RejectionDiagnosisError("current YAML resolved config drifted from approved trial")
    folds = _validate_fold_plan(browser=browser, dataset=dataset)
    configurations = _configuration_matrix(baseline_config=baseline_config, browser=browser)
    return source_binding, input_evidence, dataset, browser, folds, configurations


def _flatten(value: Mapping[str, Any], *, prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(item, Mapping):
            flattened.update(_flatten(item, prefix=path))
        else:
            flattened[path] = item
    return flattened


def _candidate_record(candidate: LineCandidate, *, threshold: float) -> Mapping[str, Any]:
    anchors = tuple(sorted(candidate.anchors, key=lambda item: (item.timestamp, item.anchor_id)))
    path_length = candidate.metadata.get("path_length")
    quality_method = candidate.metadata.get("quality_method")
    if isinstance(path_length, bool) or not isinstance(path_length, int) or path_length < 2:
        raise RejectionDiagnosisError("candidate path provenance is invalid")
    if not isinstance(quality_method, str) or not quality_method:
        raise RejectionDiagnosisError("candidate quality method provenance is invalid")
    return {
        "candidate_id": candidate.candidate_id,
        "role": candidate.role.value,
        "normalized_quality": candidate.diagnostics.normalized_quality,
        "coverage": candidate.diagnostics.coverage,
        "acceptance_threshold": threshold,
        "threshold_gap": threshold - candidate.diagnostics.normalized_quality,
        "path_length": path_length,
        "anchor_ids": [anchor.anchor_id for anchor in anchors],
        "anchor_timestamps": [_iso(anchor.timestamp) for anchor in anchors],
        "anchor_span_seconds": (anchors[-1].timestamp - anchors[0].timestamp).total_seconds(),
        "source_line_index": candidate.source_line_index,
        "quality_method": quality_method,
    }


def _shadow_config(config: ResolvedTrendlineFamilyConfig) -> ResolvedTrendlineFamilyConfig:
    shadow = apply_stage_overrides(
        config,
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        overrides={"candidate.min_candidate_quality": 0.0},
    )
    actual = _flatten(config.to_dict())
    changed = {
        key: {"source": actual[key], "shadow": value}
        for key, value in _flatten(shadow.to_dict()).items()
        if actual.get(key) != value
    }
    expected = {"candidate.min_candidate_quality": {"source": config.candidate.min_candidate_quality, "shadow": 0.0}}
    if changed != expected:
        raise RejectionDiagnosisError("diagnostic shadow config changed fields outside minimum candidate quality")
    return shadow


def _persisted_status_counts(result: TrialResult, fold_id: str) -> Mapping[str, int]:
    window = next((item for item in result.window_results if item.fold_id == fold_id), None)
    if window is None:
        raise RejectionDiagnosisError("persisted trial omits a validation fold")
    raw = window.diagnostics.get("provider_status_counts")
    if not isinstance(raw, Mapping):
        raise RejectionDiagnosisError("persisted validation window omits provider status counts")
    counts = {name: raw.get(name, 0) for name in STATUS_NAMES}
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts.values()):
        raise RejectionDiagnosisError("persisted provider status counts are invalid")
    if sum(counts.values()) != window.evaluated_bar_count:
        raise RejectionDiagnosisError("persisted provider status counts do not cover validation window")
    return counts


def replay_validation_provider(
    *,
    dataset: ImmutableHistoricalFrame,
    folds: Sequence[WalkForwardFold],
    configurations: Sequence[ConfigurationReplay],
    planned_holdout_start_position: int,
    provider_factory: Callable[[], NativeDeterministicLineProvider] = NativeDeterministicLineProvider,
) -> Mapping[str, Any]:
    """Run canonical provider calls over validation positions only; never score outcomes."""

    if len(configurations) != 7 or sum(fold.validation.bar_count for fold in folds) != 288:
        raise RejectionDiagnosisError("replay requires seven configurations and 288 validation positions")
    if isinstance(planned_holdout_start_position, bool) or not isinstance(planned_holdout_start_position, int):
        raise RejectionDiagnosisError("planned holdout start position must be an integer")
    if planned_holdout_start_position <= max(fold.validation.end_position for fold in folds):
        raise RejectionDiagnosisError("planned holdout start does not exclude every validation position")
    all_records: list[Mapping[str, Any]] = []
    actual_call_count = 0
    shadow_call_count = 0
    for entry in configurations:
        actual_provider = provider_factory()
        shadow_provider = provider_factory()
        shadow_config = _shadow_config(entry.config)
        for fold in folds:
            expected = _persisted_status_counts(entry.result, fold.fold_id)
            actual_counts: Counter[str] = Counter()
            for position in range(fold.validation.start_position, fold.validation.end_position + 1):
                if position >= planned_holdout_start_position:
                    raise RejectionDiagnosisError("provider replay position overlaps planned holdout")
                observed_at = dataset.timestamps[position]
                result = actual_provider.generate(
                    dataset.prefix(position),
                    asset=dataset.asset,
                    timeframe=dataset.timeframe,
                    observed_at=observed_at,
                    config=entry.config,
                )
                actual_call_count += 1
                status = result.status.value
                actual_counts[status] += 1
                accepted = [_candidate_record(candidate, threshold=entry.config.candidate.min_candidate_quality) for candidate in result.candidates]
                record: dict[str, Any] = {
                    "configuration_label": entry.label,
                    "trial_id": entry.trial_id,
                    "fold_id": fold.fold_id,
                    "fold_index": fold.fold_index,
                    "position": position,
                    "observed_at": _iso(observed_at),
                    "provider_status": status,
                    "reason_codes": list(result.reason_codes),
                    "provider_metadata": primitive(result.metadata),
                    "accepted_candidate_count": len(accepted),
                    "accepted_candidates": accepted,
                    "maximum_exposed_quality": max((item["normalized_quality"] for item in accepted), default=None),
                    "shadow": None,
                }
                if result.status is CandidateGenerationStatus.REJECTED_LOW_QUALITY:
                    shadow_result = shadow_provider.generate(
                        dataset.prefix(position),
                        asset=dataset.asset,
                        timeframe=dataset.timeframe,
                        observed_at=observed_at,
                        config=shadow_config,
                    )
                    shadow_call_count += 1
                    fitted_paths = result.metadata.get("fitted_paths")
                    if isinstance(fitted_paths, bool) or not isinstance(fitted_paths, int) or fitted_paths < 1:
                        raise RejectionDiagnosisError("low-quality result omits valid fitted path count")
                    if shadow_result.status is not CandidateGenerationStatus.VALID:
                        raise RejectionDiagnosisError("low-quality shadow provider did not expose valid candidates")
                    if len(shadow_result.candidates) != fitted_paths:
                        raise RejectionDiagnosisError("shadow candidate count differs from actual fitted path count")
                    shadow_candidates = [
                        _candidate_record(candidate, threshold=entry.config.candidate.min_candidate_quality)
                        for candidate in shadow_result.candidates
                    ]
                    if any(item["normalized_quality"] >= entry.config.candidate.min_candidate_quality for item in shadow_candidates):
                        raise RejectionDiagnosisError("shadow candidate violates actual low-quality threshold invariant")
                    record["maximum_exposed_quality"] = max(item["normalized_quality"] for item in shadow_candidates)
                    record["shadow"] = {
                        "source_resolved_config_hash": entry.config.resolved_config_hash,
                        "shadow_resolved_config_hash": shadow_config.resolved_config_hash,
                        "delta": {"candidate.min_candidate_quality": 0.0},
                        "candidate_count": len(shadow_candidates),
                        "candidates": shadow_candidates,
                    }
                all_records.append(record)
            if dict(sorted(actual_counts.items())) != {name: count for name, count in expected.items() if count}:
                raise RejectionDiagnosisError(
                    f"actual provider status counts do not reconcile for {entry.label} {fold.fold_id}"
                )
    if actual_call_count != 2016:
        raise RejectionDiagnosisError("actual provider call count must equal 2016")
    return {
        "actual_provider_call_count": actual_call_count,
        "shadow_provider_call_count": shadow_call_count,
        "planned_holdout_start_position": planned_holdout_start_position,
        "records": tuple(sorted(all_records, key=lambda item: (item["configuration_label"], item["fold_index"], item["position"]))),
    }


def _summary(values: Sequence[float]) -> Mapping[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "median": None, "quantiles": {}}
    ordered = sorted(float(value) for value in values)

    def quantile(level: float) -> float:
        index = (len(ordered) - 1) * level
        lower = math.floor(index)
        upper = math.ceil(index)
        if lower == upper:
            return ordered[lower]
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)

    return {
        "count": len(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "mean": statistics.fmean(ordered),
        "median": statistics.median(ordered),
        "quantiles": {str(level): quantile(level) for level in (0.10, 0.25, 0.50, 0.75, 0.90)},
        "quantile_method": "linear_interpolation_v1",
    }


def _records_for(records: Sequence[Mapping[str, Any]], entry: ConfigurationReplay, fold: WalkForwardFold) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        item
        for item in records
        if item["configuration_label"] == entry.label and item["fold_id"] == fold.fold_id
    )


def _status_funnel(records: Sequence[Mapping[str, Any]], configurations: Sequence[ConfigurationReplay], folds: Sequence[WalkForwardFold]) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for entry in configurations:
        per_fold: list[Mapping[str, Any]] = []
        for fold in folds:
            group = _records_for(records, entry, fold)
            categories: dict[str, Any] = {}
            for status in STATUS_NAMES:
                status_rows = [item for item in group if item["provider_status"] == status]
                categories[status] = {
                    "count": len(status_rows),
                    "ratio": len(status_rows) / len(group),
                    "first_observed_at": None if not status_rows else status_rows[0]["observed_at"],
                    "last_observed_at": None if not status_rows else status_rows[-1]["observed_at"],
                }
            persisted = _persisted_status_counts(entry.result, fold.fold_id)
            actual = {status: categories[status]["count"] for status in STATUS_NAMES}
            if actual != persisted:
                raise RejectionDiagnosisError("aggregate status reconciliation failed")
            per_fold.append({"fold_id": fold.fold_id, "fold_index": fold.fold_index, "statuses": categories, "reconciled": True})
        rows.append({"configuration_label": entry.label, "trial_id": entry.trial_id, "folds": per_fold})
    return rows


def _low_quality_decomposition(records: Sequence[Mapping[str, Any]], configurations: Sequence[ConfigurationReplay], folds: Sequence[WalkForwardFold]) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for entry in configurations:
        per_fold: list[Mapping[str, Any]] = []
        for fold in folds:
            rejected = [
                item for item in _records_for(records, entry, fold)
                if item["provider_status"] == CandidateGenerationStatus.REJECTED_LOW_QUALITY.value
            ]
            candidates = [candidate for item in rejected for candidate in item["shadow"]["candidates"]]
            qualities = [candidate["normalized_quality"] for candidate in candidates]
            gaps = [candidate["threshold_gap"] for candidate in candidates]
            roles = Counter(candidate["role"] for candidate in candidates)
            lengths = [float(candidate["path_length"]) for candidate in candidates]
            spans = [candidate["anchor_span_seconds"] for candidate in candidates]
            methods = Counter(candidate["quality_method"] for candidate in candidates)
            per_fold.append(
                {
                    "fold_id": fold.fold_id,
                    "fold_index": fold.fold_index,
                    "low_quality_rejected_bar_count": len(rejected),
                    "fitted_path_count": sum(item["provider_metadata"]["fitted_paths"] for item in rejected),
                    "shadow_candidate_count": len(candidates),
                    "role_counts": dict(sorted(roles.items())),
                    "quality_summary": _summary(qualities),
                    "threshold_gap_summary": _summary(gaps),
                    "near_miss_counts": {
                        str(distance): sum(gap <= distance for gap in gaps)
                        for distance in (0.01, 0.02, 0.05, 0.10)
                    },
                    "path_length_summary": _summary(lengths),
                    "anchor_span_seconds_summary": _summary(spans),
                    "quality_methods": dict(sorted(methods.items())),
                }
            )
        rows.append({"configuration_label": entry.label, "trial_id": entry.trial_id, "folds": per_fold})
    return rows


def _compare_records(left: ConfigurationReplay, right: ConfigurationReplay, records: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    by_position = {(item["fold_id"], item["position"]): item for item in records if item["configuration_label"] == left.label}
    right_by_position = {(item["fold_id"], item["position"]): item for item in records if item["configuration_label"] == right.label}
    if set(by_position) != set(right_by_position):
        raise RejectionDiagnosisError("parameter contrast configurations do not share validation positions")
    pairs = [(by_position[key], right_by_position[key]) for key in sorted(by_position)]
    comparable_deltas = [
        right_record["maximum_exposed_quality"] - left_record["maximum_exposed_quality"]
        for left_record, right_record in pairs
        if left_record["maximum_exposed_quality"] is not None and right_record["maximum_exposed_quality"] is not None
    ]
    return {
        "left": {"label": left.label, "overrides": dict(left.overrides)},
        "right": {"label": right.label, "overrides": dict(right.overrides)},
        "bars_with_status_change": sum(left_record["provider_status"] != right_record["provider_status"] for left_record, right_record in pairs),
        "valid_to_rejected_low_quality": sum(
            left_record["provider_status"] == CandidateGenerationStatus.VALID.value
            and right_record["provider_status"] == CandidateGenerationStatus.REJECTED_LOW_QUALITY.value
            for left_record, right_record in pairs
        ),
        "rejected_low_quality_to_valid": sum(
            left_record["provider_status"] == CandidateGenerationStatus.REJECTED_LOW_QUALITY.value
            and right_record["provider_status"] == CandidateGenerationStatus.VALID.value
            for left_record, right_record in pairs
        ),
        "accepted_candidate_count_delta_right_minus_left": sum(
            right_record["accepted_candidate_count"] - left_record["accepted_candidate_count"]
            for left_record, right_record in pairs
        ),
        "maximum_pre_threshold_quality_delta_right_minus_left": _summary(comparable_deltas),
    }


def _parameter_contrasts(configurations: Sequence[ConfigurationReplay], records: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    primary = {
        (entry.config.candidate.lookback_bars, entry.config.candidate.min_candidate_quality): entry
        for entry in configurations
        if entry.label != "baseline"
    }
    baseline = next(entry for entry in configurations if entry.label == "baseline")
    threshold = [_compare_records(primary[(lookback, 0.30)], primary[(lookback, 0.40)], records) for lookback in (120, 180, 240)]
    lookback = [
        _compare_records(primary[(120, quality)], primary[(other, quality)], records)
        for quality in (0.30, 0.40)
        for other in (180, 240)
    ]
    baseline_neighbors = [_compare_records(baseline, primary[(180, quality)], records) for quality in (0.30, 0.40)]
    return {"threshold_0_30_vs_0_40": threshold, "lookback_120_vs_180_or_240": lookback, "baseline_180_0_35_neighbors": baseline_neighbors}


def _productive_trial_gate_deficit(configurations: Sequence[ConfigurationReplay], records: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    productive = [entry for entry in configurations if entry.label != "baseline" and (entry.result.metric("reaction_quality") or None) is not None and entry.result.metric("reaction_quality").value is not None]
    if len(productive) != 1:
        raise RejectionDiagnosisError("diagnosis expected exactly one primary trial with reaction-quality evidence")
    entry = productive[0]
    gate = entry.result.objective_gate
    metric = entry.result.metric("reaction_quality")
    if gate is None or metric is None:
        raise RejectionDiagnosisError("productive trial omits persisted objective evidence")
    per_fold = []
    outcome_exclusions = 0
    for window in entry.result.window_results:
        reaction = window.metric("reaction_quality")
        if reaction is None:
            raise RejectionDiagnosisError("productive trial window omits reaction-quality evidence")
        outcome_exclusions += window.excluded_reasons.get("outcome_horizon_unavailable", 0)
        per_fold.append({"fold_id": window.fold_id, "reaction_quality": reaction.to_dict(), "excluded_reasons": primitive(window.excluded_reasons)})
    actual = [record for record in records if record["configuration_label"] == entry.label]
    return {
        "trial_id": entry.trial_id,
        "result_id": entry.result_id,
        "overrides": dict(entry.overrides),
        "aggregate_reaction_quality": metric.to_dict(),
        "per_fold_reaction_quality": sorted(per_fold, key=lambda item: item["fold_id"]),
        "sample_count": metric.sample_count,
        "required_minimum_sample_count": gate.objective.minimum_sample_count,
        "sample_deficit": max(0, gate.objective.minimum_sample_count - metric.sample_count),
        "defined_primary_fold_count": gate.defined_primary_fold_count,
        "required_fold_count": gate.required_fold_count,
        "fold_coverage_ratio": gate.fold_coverage_ratio,
        "failure_rate": gate.failure_rate,
        "outcome_horizon_exclusions": outcome_exclusions,
        "objective_gate_rejection_reasons": list(gate.rejection_reasons),
        "accepted_producing_bar_count": sum(record["provider_status"] == CandidateGenerationStatus.VALID.value for record in actual),
        "accepted_candidate_count": sum(record["accepted_candidate_count"] for record in actual),
    }


def build_diagnosis_payload(
    *,
    source_binding: Mapping[str, Any],
    input_evidence: Mapping[str, Any],
    dataset: ImmutableHistoricalFrame,
    browser: PhaseIArtifactBrowser,
    folds: Sequence[WalkForwardFold],
    configurations: Sequence[ConfigurationReplay],
    replay: Mapping[str, Any],
) -> Mapping[str, Any]:
    records = replay["records"]
    status_funnel = _status_funnel(records, configurations, folds)
    decomposition = _low_quality_decomposition(records, configurations, folds)
    configuration_payload = [
        {
            "label": entry.label,
            "trial_id": entry.trial_id,
            "result_id": entry.result_id,
            "parameter_overrides": dict(entry.overrides),
            "resolved_config_hash": entry.config.resolved_config_hash,
            "candidate_config": {
                "lookback_bars": entry.config.candidate.lookback_bars,
                "min_bars": entry.config.candidate.min_bars,
                "fractal_left_bars": entry.config.candidate.fractal_left_bars,
                "fractal_right_bars": entry.config.candidate.fractal_right_bars,
                "min_pivots_per_side": entry.config.candidate.min_pivots_per_side,
                "min_candidate_quality": entry.config.candidate.min_candidate_quality,
            },
            "objective_gate_id": None if entry.result.objective_gate is None else semantic_id("trendline-family-objective-gate", entry.result.objective_gate.to_dict()),
        }
        for entry in configurations
    ]
    identity = {
        "diagnosis_schema_version": DIAGNOSIS_SCHEMA_VERSION,
        "source_binding_id": source_binding["source_binding_id"],
        "dataset_hash": dataset.dataset_hash,
        "resolved_config_hash": EXPECTED_CONFIG_HASH,
        "phase_i_run_id": browser.manifest.run_id,
        "report_id": EXPECTED_REPORT_ID,
        "recommendation_id": browser.recommendation.recommendation_id,
    }
    payload: dict[str, Any] = {
        "diagnosis_identity": identity,
        "source_and_execution_identity": {
            **identity,
            "source_inventories": source_binding,
            "input_manifest_sha256": input_evidence["input_manifest_sha256"],
            "normalized_input_sha256": input_evidence["normalized_input_sha256"],
            "actual_provider_call_count": replay["actual_provider_call_count"],
            "shadow_provider_call_count": replay["shadow_provider_call_count"],
            "planned_holdout_exclusion": {
                "planned_holdout_start_position": replay["planned_holdout_start_position"],
                "maximum_replayed_position": max(record["position"] for record in records),
                "all_replayed_positions_before_holdout": all(record["position"] < replay["planned_holdout_start_position"] for record in records),
            },
        },
        "dataset_and_fold_boundaries": {
            "asset": dataset.asset,
            "timeframe": dataset.timeframe,
            "row_count": dataset.row_count,
            "dataset_hash": dataset.dataset_hash,
            "fold_plan_id": browser.bundle.fold_plan.fold_plan_id,
            "purge_bars": 12,
            "label_horizon_bars": 12,
            "validation_position_count": 288,
            "validation_windows": [
                {
                    "fold_id": fold.fold_id,
                    "fold_index": fold.fold_index,
                    "start_position": fold.validation.start_position,
                    "end_position": fold.validation.end_position,
                    "start": _iso(fold.validation.start),
                    "end": _iso(fold.validation.end),
                    "bar_count": fold.validation.bar_count,
                }
                for fold in folds
            ],
        },
        "configuration_matrix": configuration_payload,
        "status_funnel": status_funnel,
        "low_quality_rejection_decomposition": decomposition,
        "parameter_contrasts": _parameter_contrasts(configurations, records),
        "productive_trial_gate_deficit": _productive_trial_gate_deficit(configurations, records),
        "observations": [
            "All status and quality summaries are validation-only provider replay evidence.",
            "Candidate scarcity is separated by canonical provider status before the diagnostic shadow path.",
            "The sole defined reaction-quality result is reported from verified persisted evidence, not recomputed.",
        ],
        "research_hypotheses": [
            "Does anchor_span_coverage_v1 remain restrictive for this fixed 4h validation window?",
            "Is the observed pre-threshold quality distribution misaligned with the approved quality grid?",
            "Would a separately approved longer validation dataset change the minimum-sample-gate evidence?",
            "Would a separately approved structural-density study isolate lookback and pivot availability?",
        ],
        "diagnostic_records": records,
    }
    semantic = {key: value for key, value in payload.items() if key != "diagnosis_identity"}
    diagnosis_id = semantic_id("trendline-family-candidate-rejection-diagnosis", semantic)
    payload["diagnosis_identity"] = {**identity, "diagnosis_id": diagnosis_id}
    return payload


def _markdown(payload: Mapping[str, Any]) -> str:
    sections = (
        ("Source And Execution Identity", payload["source_and_execution_identity"]),
        ("Dataset And Fold Boundaries", payload["dataset_and_fold_boundaries"]),
        ("Configuration Matrix", payload["configuration_matrix"]),
        ("Status Funnel", payload["status_funnel"]),
        ("Low Quality Rejection Decomposition", payload["low_quality_rejection_decomposition"]),
        ("Parameter Contrasts", payload["parameter_contrasts"]),
        ("Productive Trial Gate Deficit", payload["productive_trial_gate_deficit"]),
        ("Evidence Based Observations", payload["observations"]),
        ("Research Hypotheses", payload["research_hypotheses"]),
    )
    chunks = ["# Trendline-Family Candidate Rejection Diagnosis v1\n"]
    for heading, section in sections:
        chunks.append(f"## {heading}\n\n```json\n{json.dumps(section, indent=2, sort_keys=True, ensure_ascii=True)}\n```\n")
    return "\n".join(chunks)


def _diagnosis_id(payload: Mapping[str, Any]) -> str:
    identity = payload.get("diagnosis_identity")
    if not isinstance(identity, Mapping):
        raise RejectionDiagnosisError("diagnosis identity is malformed")
    required = {
        "source_and_execution_identity", "dataset_and_fold_boundaries", "configuration_matrix", "status_funnel",
        "low_quality_rejection_decomposition", "parameter_contrasts", "productive_trial_gate_deficit", "observations",
        "research_hypotheses", "diagnostic_records",
    }
    if not required.issubset(payload):
        raise RejectionDiagnosisError("diagnosis payload is incomplete")
    semantic = {key: payload[key] for key in sorted(required)}
    return semantic_id("trendline-family-candidate-rejection-diagnosis", semantic)


def _atomic_write_if_identical(path: Path, payload: bytes) -> Path:
    if path.exists():
        if path.read_bytes() != payload:
            raise RejectionDiagnosisError(f"refusing non-identical diagnosis overwrite: {path}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
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


def write_diagnosis_bundle(*, output_root: Path, source_binding: Mapping[str, Any], payload: Mapping[str, Any]) -> Mapping[str, Path]:
    source_bytes = canonical_json(source_binding).encode("utf-8") + b"\n"
    diagnosis_bytes = canonical_json(payload).encode("utf-8") + b"\n"
    markdown_bytes = _markdown(payload).encode("utf-8")
    manifest = {
        "diagnosis_schema_version": DIAGNOSIS_SCHEMA_VERSION,
        "diagnosis_id": payload["diagnosis_identity"]["diagnosis_id"],
        "source_binding_id": source_binding["source_binding_id"],
        "source_binding_sha256": _sha256_bytes(source_bytes),
        "dataset_hash": payload["diagnosis_identity"]["dataset_hash"],
        "resolved_config_hash": payload["diagnosis_identity"]["resolved_config_hash"],
        "phase_i_run_id": payload["diagnosis_identity"]["phase_i_run_id"],
        "report_id": payload["diagnosis_identity"]["report_id"],
        "recommendation_id": payload["diagnosis_identity"]["recommendation_id"],
        "rejection_diagnosis_json_sha256": _sha256_bytes(diagnosis_bytes),
        "rejection_diagnosis_markdown_sha256": _sha256_bytes(markdown_bytes),
    }
    manifest_bytes = canonical_json(manifest).encode("utf-8") + b"\n"
    targets = {
        "source_binding": (output_root / "source_binding.json", source_bytes),
        "rejection_diagnosis": (output_root / "rejection_diagnosis.json", diagnosis_bytes),
        "rejection_markdown": (output_root / "rejection_diagnosis.md", markdown_bytes),
        "diagnosis_manifest": (output_root / "diagnosis_manifest.json", manifest_bytes),
    }
    for path, content in targets.values():
        if path.exists() and path.read_bytes() != content:
            raise RejectionDiagnosisError(f"refusing non-identical diagnosis overwrite: {path}")
    return {name: _atomic_write_if_identical(path, content) for name, (path, content) in sorted(targets.items())}


def validate_diagnosis_bundle(*, output_root: Path) -> Mapping[str, Any]:
    source_binding_path = output_root / "source_binding.json"
    diagnosis_path = output_root / "rejection_diagnosis.json"
    markdown_path = output_root / "rejection_diagnosis.md"
    manifest_path = output_root / "diagnosis_manifest.json"
    source_binding = _read_json(source_binding_path)
    diagnosis = _read_json(diagnosis_path)
    manifest = _read_json(manifest_path)
    identity = diagnosis.get("diagnosis_identity")
    if not isinstance(identity, Mapping) or identity.get("diagnosis_id") != _diagnosis_id(diagnosis):
        raise RejectionDiagnosisError("diagnosis content-addressed identity mismatch")
    if manifest.get("diagnosis_schema_version") != DIAGNOSIS_SCHEMA_VERSION or manifest.get("diagnosis_id") != identity.get("diagnosis_id"):
        raise RejectionDiagnosisError("diagnosis manifest identity mismatch")
    if _sha256_bytes(source_binding_path.read_bytes()) != manifest.get("source_binding_sha256"):
        raise RejectionDiagnosisError("diagnosis source binding hash mismatch")
    if _sha256_bytes(diagnosis_path.read_bytes()) != manifest.get("rejection_diagnosis_json_sha256"):
        raise RejectionDiagnosisError("diagnosis JSON hash mismatch")
    if _sha256_bytes(markdown_path.read_bytes()) != manifest.get("rejection_diagnosis_markdown_sha256"):
        raise RejectionDiagnosisError("diagnosis Markdown hash mismatch")
    validated_source_binding = validate_source_binding_payload(source_binding)
    source_binding_id = validated_source_binding["source_binding_id"]
    execution_identity = diagnosis.get("source_and_execution_identity")
    if not isinstance(execution_identity, Mapping):
        raise RejectionDiagnosisError("diagnosis source and execution identity is malformed")
    for location, claim in (
        ("diagnosis manifest", manifest.get("source_binding_id")),
        ("diagnosis identity", identity.get("source_binding_id")),
        ("diagnosis source and execution identity", execution_identity.get("source_binding_id")),
    ):
        if claim != source_binding_id:
            raise RejectionDiagnosisError(f"{location} source binding mismatch")
    if canonical_json(execution_identity.get("source_inventories")) != canonical_json(validated_source_binding):
        raise RejectionDiagnosisError("diagnosis embedded source inventories differ from validated source binding")
    expected_identity = {
        "dataset_hash": EXPECTED_DATASET_HASH,
        "resolved_config_hash": EXPECTED_CONFIG_HASH,
        "phase_i_run_id": EXPECTED_PHASE_I_RUN_ID,
        "report_id": EXPECTED_REPORT_ID,
        "recommendation_id": EXPECTED_RECOMMENDATION_ID,
    }
    if any(identity.get(key) != expected for key, expected in expected_identity.items()):
        raise RejectionDiagnosisError("diagnosis source identity mismatch")
    if any(manifest.get(key) != expected for key, expected in expected_identity.items()):
        raise RejectionDiagnosisError("diagnosis manifest source identity mismatch")
    if any(execution_identity.get(key) != expected for key, expected in expected_identity.items()):
        raise RejectionDiagnosisError("diagnosis execution source identity mismatch")
    return {
        "source_binding": validated_source_binding,
        "rejection_diagnosis": diagnosis,
        "diagnosis_manifest": manifest,
    }


def build_rejection_diagnosis(
    *,
    v1_root: Path = V1_TRIAL_ROOT,
    v2_root: Path = V2_TRIAL_ROOT,
    report_root: Path = REPORT_ROOT,
    config_path: Path = CONFIG_PATH,
    output_root: Path = OUTPUT_ROOT,
    provider_factory: Callable[[], NativeDeterministicLineProvider] = NativeDeterministicLineProvider,
) -> Mapping[str, Path]:
    """Build one external diagnosis without changing trial or report evidence."""

    before, input_evidence, dataset, browser, folds, configurations = load_diagnosis_sources(
        v1_root=v1_root, v2_root=v2_root, report_root=report_root, config_path=config_path
    )
    replay = replay_validation_provider(
        dataset=dataset,
        folds=folds,
        configurations=configurations,
        planned_holdout_start_position=browser.bundle.fold_plan.holdout.window.start_position,
        provider_factory=provider_factory,
    )
    payload = build_diagnosis_payload(
        source_binding=before,
        input_evidence=input_evidence,
        dataset=dataset,
        browser=browser,
        folds=folds,
        configurations=configurations,
        replay=replay,
    )
    paths = write_diagnosis_bundle(output_root=output_root, source_binding=before, payload=payload)
    validate_diagnosis_bundle(output_root=output_root)
    after = capture_source_binding(v1_root=v1_root, v2_root=v2_root, report_root=report_root, config_path=config_path)
    if canonical_json(before) != canonical_json(after):
        raise RejectionDiagnosisError("source trial, report, or YAML bytes changed during diagnosis")
    return paths


def main() -> None:
    paths = build_rejection_diagnosis()
    print(json.dumps({name: str(path) for name, path in paths.items()}, sort_keys=True))


if __name__ == "__main__":
    main()
