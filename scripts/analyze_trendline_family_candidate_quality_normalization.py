"""Read-only quality-normalization architecture study over approved evidence."""

# ruff: noqa: E402

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import statistics
import sys
import tempfile
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for import_root in (PROJECT_ROOT, SRC_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from libs.models.trendline.contracts import ContractValidationError
from libs.models.trendline.optimization.contracts import canonical_json, semantic_id
from scripts.analyze_trendline_family_candidate_density import (
    OUTPUT_ROOT as DENSITY_ROOT,
    validate_density_study_bundle,
)
from scripts.diagnose_trendline_family_candidate_rejection import (
    OUTPUT_ROOT as DIAGNOSIS_ROOT,
    validate_diagnosis_bundle,
)


QUALITY_STUDY_SCHEMA_VERSION = "trendline_family_candidate_quality_normalization_study_v1"
TRIAL_NAME = "btcusdt_4h_20250801_20251201_candidate_geometry_v2"
V1_TRIAL_NAME = "btcusdt_4h_20250801_20251201_candidate_geometry_v1"
OUTPUT_ROOT = PROJECT_ROOT / "artifacts" / "trendline_family_candidate_quality_normalization_studies" / TRIAL_NAME
V1_TRIAL_ROOT = PROJECT_ROOT / "artifacts" / "trendline_family_candidate_trials" / V1_TRIAL_NAME
V2_TRIAL_ROOT = PROJECT_ROOT / "artifacts" / "trendline_family_candidate_trials" / TRIAL_NAME
REPORT_ROOT = PROJECT_ROOT / "artifacts" / "trendline_family_candidate_reports" / TRIAL_NAME
CONFIG_PATH = PROJECT_ROOT / "configs" / "trendline_family.yaml"

EXPECTED_ASSET = "BTCUSDT"
EXPECTED_TIMEFRAME = "4h"
TIMEFRAME_SECONDS = 14_400
EXPECTED_ROW_COUNT = 732
EXPECTED_DATASET_HASH = "trendline-family-dataset_ccaf20405ffc4b84ea98f79e97053e3ee6be4b0c571999dcbf5fc0e0bca1ad53"
EXPECTED_CONFIG_HASH = "da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f"
EXPECTED_PHASE_I_RUN_ID = "trendline-family-phase-i-run_6393c4d86edb7558045b96e5c5be39fd915d8a8dde29b44e66515fdbf44b37e7"
EXPECTED_REPORT_ID = "trendline-family-candidate-evidence-report_5e01522b2ac82f67e6a722372e6deba4ea77c7fe9ea47b5415ef7d65bc3d2d41"
EXPECTED_RECOMMENDATION_ID = "trendline-family-promotion-recommendation_fdcf8d4b39ffda53b3f09b26ff28bec40056677ce18cc90eb2292b310005ccbc"
EXPECTED_DIAGNOSIS_ID = "trendline-family-candidate-rejection-diagnosis_d45c7463e1e8410a4fb9004ee7ad83b26d3c994d3a44ce781f7ff38a5025ecbf"
EXPECTED_DIAGNOSIS_SOURCE_BINDING_ID = "trendline-family-candidate-rejection-source-binding_06a563f43accc93acd9e3df59ff8d78174b861debe483446073b4c7b42e6500a"
EXPECTED_DENSITY_STUDY_ID = "trendline-family-candidate-density-study_a1160637adbf58bc9a3b8a40cd4b79aa817f2749235ca883c799e03b1b429941"
EXPECTED_DENSITY_SOURCE_BINDING_ID = "trendline-family-candidate-density-study-source-binding_f433b8b24b2fd251fa3fea28d764e72a58c60382d5c834b607466ca893aad5c6"
EXPECTED_CONFIG_SHA256 = "7a7fbc156a0ed3e01ac5b3d7502a76e834d6b34668daa8a569f32b4e63a887d8"
EXPECTED_VALIDATION_WINDOWS = ((0, 252, 347), (1, 360, 455), (2, 468, 563))
PLANNED_HOLDOUT_START = 636
LOOKBACKS = (120, 180, 240)
ROLES = ("SUPPORT", "RESISTANCE")
HORIZONS = (12, 24, 48, 96)
QUALITY_METHOD = "anchor_span_coverage_v1"
THRESHOLD_BPS = tuple(range(0, 10_001, 100))
CURRENT_TOLERANCE = Decimal("1e-12")
EXPECTED_DIAGNOSIS_FILES = (
    "diagnosis_manifest.json",
    "rejection_diagnosis.json",
    "rejection_diagnosis.md",
    "source_binding.json",
)
EXPECTED_DENSITY_FILES = (
    "candidate_density_study.json",
    "candidate_density_study.md",
    "source_binding.json",
    "study_manifest.json",
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class QualityNormalizationStudyError(ContractValidationError):
    """Raised when fixed study sources, population, or provenance is invalid."""


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _read_json(path: Path, *, label: str) -> Mapping[str, Any]:
    if not path.is_file():
        raise QualityNormalizationStudyError(f"required {label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualityNormalizationStudyError(f"invalid {label} JSON: {path}") from exc
    if not isinstance(value, Mapping):
        raise QualityNormalizationStudyError(f"{label} JSON must be a mapping: {path}")
    return value


def _require_sha256(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise QualityNormalizationStudyError(f"{field_name} must be a lowercase 64-character SHA-256")
    return value


def _validate_relative_path(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise QualityNormalizationStudyError(f"{field_name} must be a non-empty string")
    if value.startswith("/") or "\\" in value or any(part in {"", ".", ".."} for part in value.split("/")):
        raise QualityNormalizationStudyError(f"{field_name} must be a safe canonical POSIX relative path")
    return value


def _validate_files(
    value: Any,
    *,
    field_name: str,
    expected_paths: Sequence[str],
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise QualityNormalizationStudyError(f"{field_name} must be a non-empty sequence")
    files: list[Mapping[str, Any]] = []
    paths: list[str] = []
    for index, record in enumerate(value):
        if not isinstance(record, Mapping) or set(record) != {"relative_path", "size_bytes", "sha256"}:
            raise QualityNormalizationStudyError(f"{field_name} record {index} fields are invalid")
        relative_path = _validate_relative_path(record.get("relative_path"), field_name=f"{field_name} record {index} relative_path")
        size_bytes = record.get("size_bytes")
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
            raise QualityNormalizationStudyError(f"{field_name} record {index} size_bytes is invalid")
        files.append(
            {
                "relative_path": relative_path,
                "size_bytes": size_bytes,
                "sha256": _require_sha256(record.get("sha256"), field_name=f"{field_name} record {index} sha256"),
            }
        )
        paths.append(relative_path)
    if len(paths) != len(set(paths)):
        raise QualityNormalizationStudyError(f"{field_name} paths must be unique")
    if paths != sorted(paths):
        raise QualityNormalizationStudyError(f"{field_name} paths must be strictly sorted")
    if tuple(paths) != tuple(expected_paths):
        raise QualityNormalizationStudyError(f"{field_name} differs from approved file set")
    return tuple(files)


def _inventory(root: Path, *, source_name: str, expected_paths: Sequence[str]) -> Mapping[str, Any]:
    if not root.is_dir():
        raise QualityNormalizationStudyError(f"source root is missing: {root}")
    files = tuple(
        {
            "relative_path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_bytes(path.read_bytes()),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )
    if tuple(item["relative_path"] for item in files) != tuple(expected_paths):
        raise QualityNormalizationStudyError(f"source root file set drift: {source_name}")
    semantic = {"source_name": source_name, "root_name": root.name, "files": files}
    return {**semantic, "inventory_sha256": _sha256_bytes(canonical_json(semantic).encode("utf-8"))}


def _generic_inventory(root: Path, *, source_name: str) -> Mapping[str, Any]:
    if not root.is_dir():
        raise QualityNormalizationStudyError(f"source root is missing: {root}")
    files = tuple(
        {
            "relative_path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_bytes(path.read_bytes()),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )
    semantic = {"source_name": source_name, "root_name": root.name, "files": files}
    return {**semantic, "inventory_sha256": _sha256_bytes(canonical_json(semantic).encode("utf-8"))}


def capture_protected_source_inventories() -> Mapping[str, Any]:
    inventories = {
        "v1_trial": _generic_inventory(V1_TRIAL_ROOT, source_name="v1_trial"),
        "v2_trial": _generic_inventory(V2_TRIAL_ROOT, source_name="v2_trial"),
        "approved_report": _generic_inventory(REPORT_ROOT, source_name="approved_report"),
        "approved_diagnosis": _inventory(DIAGNOSIS_ROOT, source_name="approved_diagnosis", expected_paths=EXPECTED_DIAGNOSIS_FILES),
        "approved_density": _inventory(DENSITY_ROOT, source_name="approved_density", expected_paths=EXPECTED_DENSITY_FILES),
    }
    expected_counts = {
        "v1_trial": 1,
        "v2_trial": 30,
        "approved_report": 4,
        "approved_diagnosis": 4,
        "approved_density": 4,
    }
    if {key: len(value["files"]) for key, value in inventories.items()} != expected_counts:
        raise QualityNormalizationStudyError("protected source inventory count drift")
    if not CONFIG_PATH.is_file():
        raise QualityNormalizationStudyError("approved config is missing")
    config_bytes = CONFIG_PATH.read_bytes()
    config = {"relative_path": "configs/trendline_family.yaml", "size_bytes": len(config_bytes), "sha256": _sha256_bytes(config_bytes)}
    if config["sha256"] != EXPECTED_CONFIG_SHA256:
        raise QualityNormalizationStudyError("approved config SHA-256 drift")
    return {**inventories, "config": config}


def _require_identity_sources(diagnosis_bundle: Mapping[str, Any], density_bundle: Mapping[str, Any]) -> None:
    diagnosis = diagnosis_bundle.get("rejection_diagnosis")
    density = density_bundle.get("candidate_density_study")
    if not isinstance(diagnosis, Mapping) or not isinstance(density, Mapping):
        raise QualityNormalizationStudyError("validated source bundle payload is malformed")
    diagnosis_identity = diagnosis.get("diagnosis_identity")
    density_identity = density.get("study_identity")
    density_source_identity = density.get("source_and_bias_identity")
    diagnosis_bounds = diagnosis.get("dataset_and_fold_boundaries")
    if not isinstance(diagnosis_identity, Mapping) or not isinstance(density_identity, Mapping) or not isinstance(density_source_identity, Mapping) or not isinstance(diagnosis_bounds, Mapping):
        raise QualityNormalizationStudyError("source identity sections are malformed")
    diagnosis_expected = {
        "diagnosis_id": EXPECTED_DIAGNOSIS_ID,
        "source_binding_id": EXPECTED_DIAGNOSIS_SOURCE_BINDING_ID,
        "dataset_hash": EXPECTED_DATASET_HASH,
        "resolved_config_hash": EXPECTED_CONFIG_HASH,
        "phase_i_run_id": EXPECTED_PHASE_I_RUN_ID,
        "report_id": EXPECTED_REPORT_ID,
        "recommendation_id": EXPECTED_RECOMMENDATION_ID,
    }
    if any(diagnosis_identity.get(key) != value for key, value in diagnosis_expected.items()):
        raise QualityNormalizationStudyError("diagnosis fixed identity drift")
    density_expected = {
        "study_id": EXPECTED_DENSITY_STUDY_ID,
        "study_source_binding_id": EXPECTED_DENSITY_SOURCE_BINDING_ID,
        "diagnosis_id": EXPECTED_DIAGNOSIS_ID,
        "diagnosis_source_binding_id": EXPECTED_DIAGNOSIS_SOURCE_BINDING_ID,
    }
    if any(density_identity.get(key) != value for key, value in density_expected.items()):
        raise QualityNormalizationStudyError("density fixed identity drift")
    if any(density_source_identity.get(key) != value for key, value in diagnosis_expected.items() if key != "source_binding_id"):
        raise QualityNormalizationStudyError("density source identity drift")
    if diagnosis_bounds.get("asset") != EXPECTED_ASSET or diagnosis_bounds.get("timeframe") != EXPECTED_TIMEFRAME or diagnosis_bounds.get("row_count") != EXPECTED_ROW_COUNT:
        raise QualityNormalizationStudyError("diagnosis population identity drift")
    if density_source_identity.get("holdout_accessed") is not False or density_source_identity.get("planned_holdout_start_position") != PLANNED_HOLDOUT_START:
        raise QualityNormalizationStudyError("density holdout boundary drift")


def capture_quality_source_binding(*, diagnosis_root: Path, density_root: Path) -> Mapping[str, Any]:
    diagnosis_bundle = validate_diagnosis_bundle(output_root=diagnosis_root)
    density_bundle = validate_density_study_bundle(output_root=density_root, diagnosis_root=diagnosis_root)
    _require_identity_sources(diagnosis_bundle, density_bundle)
    diagnosis_inventory = _inventory(diagnosis_root, source_name="approved_diagnosis_bundle", expected_paths=EXPECTED_DIAGNOSIS_FILES)
    density_inventory = _inventory(density_root, source_name="approved_density_study_bundle", expected_paths=EXPECTED_DENSITY_FILES)
    semantic = {
        "quality_study_schema_version": QUALITY_STUDY_SCHEMA_VERSION,
        "diagnosis_bundle": {
            "diagnosis_id": EXPECTED_DIAGNOSIS_ID,
            "source_binding_id": EXPECTED_DIAGNOSIS_SOURCE_BINDING_ID,
            "inventory": diagnosis_inventory,
        },
        "density_bundle": {
            "study_id": EXPECTED_DENSITY_STUDY_ID,
            "source_binding_id": EXPECTED_DENSITY_SOURCE_BINDING_ID,
            "inventory": density_inventory,
        },
    }
    return {**semantic, "quality_source_binding_id": semantic_id("trendline-family-candidate-quality-normalization-source-binding", semantic)}


def _validate_source_entry(value: Any, *, label: str, expected_id: str, expected_binding_id: str, expected_name: str, expected_paths: Sequence[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"diagnosis_id" if label == "diagnosis" else "study_id", "source_binding_id", "inventory"}:
        raise QualityNormalizationStudyError(f"quality source binding {label} fields are invalid")
    id_field = "diagnosis_id" if label == "diagnosis" else "study_id"
    if value.get(id_field) != expected_id or value.get("source_binding_id") != expected_binding_id:
        raise QualityNormalizationStudyError(f"quality source binding {label} identity mismatch")
    raw_inventory = value.get("inventory")
    if not isinstance(raw_inventory, Mapping) or set(raw_inventory) != {"source_name", "root_name", "files", "inventory_sha256"}:
        raise QualityNormalizationStudyError(f"quality source binding {label} inventory fields are invalid")
    if raw_inventory.get("source_name") != expected_name or raw_inventory.get("root_name") != TRIAL_NAME:
        raise QualityNormalizationStudyError(f"quality source binding {label} inventory identity mismatch")
    files = _validate_files(raw_inventory.get("files"), field_name=f"quality source binding {label} files", expected_paths=expected_paths)
    semantic_inventory = {"source_name": expected_name, "root_name": TRIAL_NAME, "files": files}
    inventory_hash = _sha256_bytes(canonical_json(semantic_inventory).encode("utf-8"))
    if _require_sha256(raw_inventory.get("inventory_sha256"), field_name=f"quality source binding {label} inventory sha256") != inventory_hash:
        raise QualityNormalizationStudyError(f"quality source binding {label} inventory_sha256 mismatch")
    return {id_field: expected_id, "source_binding_id": expected_binding_id, "inventory": {**semantic_inventory, "inventory_sha256": inventory_hash}}


def validate_quality_source_binding_payload(value: Mapping[str, Any]) -> Mapping[str, Any]:
    expected_fields = {"quality_study_schema_version", "diagnosis_bundle", "density_bundle", "quality_source_binding_id"}
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise QualityNormalizationStudyError("quality source binding top-level fields are invalid")
    if value.get("quality_study_schema_version") != QUALITY_STUDY_SCHEMA_VERSION:
        raise QualityNormalizationStudyError("quality source binding schema version mismatch")
    semantic = {
        "quality_study_schema_version": QUALITY_STUDY_SCHEMA_VERSION,
        "diagnosis_bundle": _validate_source_entry(
            value.get("diagnosis_bundle"),
            label="diagnosis",
            expected_id=EXPECTED_DIAGNOSIS_ID,
            expected_binding_id=EXPECTED_DIAGNOSIS_SOURCE_BINDING_ID,
            expected_name="approved_diagnosis_bundle",
            expected_paths=EXPECTED_DIAGNOSIS_FILES,
        ),
        "density_bundle": _validate_source_entry(
            value.get("density_bundle"),
            label="density",
            expected_id=EXPECTED_DENSITY_STUDY_ID,
            expected_binding_id=EXPECTED_DENSITY_SOURCE_BINDING_ID,
            expected_name="approved_density_study_bundle",
            expected_paths=EXPECTED_DENSITY_FILES,
        ),
    }
    derived_id = semantic_id("trendline-family-candidate-quality-normalization-source-binding", semantic)
    if value.get("quality_source_binding_id") != derived_id:
        raise QualityNormalizationStudyError("quality source binding ID mismatch")
    return {**semantic, "quality_source_binding_id": derived_id}


def _decimal(value: Any, *, field_name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float, str)):
        raise QualityNormalizationStudyError(f"{field_name} must be numeric")
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise QualityNormalizationStudyError(f"{field_name} must be a decimal") from exc
    if not result.is_finite():
        raise QualityNormalizationStudyError(f"{field_name} must be finite")
    return result


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _threshold(threshold_bps: int) -> Decimal:
    if isinstance(threshold_bps, bool) or not isinstance(threshold_bps, int) or threshold_bps not in THRESHOLD_BPS:
        raise QualityNormalizationStudyError("threshold basis points are outside approved grid")
    return Decimal(threshold_bps) / Decimal(10_000)


def _threshold_text(threshold_bps: int) -> str:
    return f"{threshold_bps // 10_000}.{(threshold_bps % 10_000) // 100:02d}"


def _summary(values: Sequence[Decimal]) -> Mapping[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "median": None, "quantiles": {}}
    ordered = sorted(values)

    def quantile(level: Decimal) -> Decimal:
        index = Decimal(len(ordered) - 1) * level
        lower = int(index.to_integral_value(rounding=ROUND_FLOOR))
        upper = int(index.to_integral_value(rounding=ROUND_CEILING))
        if lower == upper:
            return ordered[lower]
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)

    with localcontext() as context:
        context.prec = 50
        mean = sum(ordered, Decimal(0)) / Decimal(len(ordered))
    return {
        "count": len(ordered),
        "min": _decimal_text(ordered[0]),
        "max": _decimal_text(ordered[-1]),
        "mean": _decimal_text(mean),
        "median": _decimal_text(statistics.median(ordered)),
        "quantiles": {str(level): _decimal_text(quantile(level)) for level in (Decimal("0.10"), Decimal("0.25"), Decimal("0.50"), Decimal("0.75"), Decimal("0.90"))},
        "quantile_method": "linear_interpolation_decimal_v1",
    }


def _candidate_key(record: Mapping[str, Any], candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    anchor_ids = candidate.get("anchor_ids")
    anchor_timestamps = candidate.get("anchor_timestamps")
    if not isinstance(anchor_ids, list) or not isinstance(anchor_timestamps, list) or len(anchor_ids) != 2 or len(anchor_timestamps) != 2:
        raise QualityNormalizationStudyError("candidate anchors are invalid")
    return (
        record.get("fold_id"),
        record.get("position"),
        record.get("observed_at"),
        candidate.get("role"),
        candidate.get("candidate_id"),
        tuple(anchor_ids),
        tuple(anchor_timestamps),
        _decimal(candidate.get("anchor_span_seconds"), field_name="candidate anchor span seconds"),
    )


def _parse_utc(value: Any, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise QualityNormalizationStudyError(f"{field_name} must be UTC ISO timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise QualityNormalizationStudyError(f"{field_name} is invalid") from exc


def _records_for_quality_population(diagnosis: Mapping[str, Any]) -> Mapping[int, tuple[tuple[Mapping[str, Any], Mapping[str, Any]], ...]]:
    raw_configs = diagnosis.get("configuration_matrix")
    raw_records = diagnosis.get("diagnostic_records")
    if not isinstance(raw_configs, list) or not isinstance(raw_records, list):
        raise QualityNormalizationStudyError("diagnosis population sections are malformed")
    labels: dict[int, str] = {}
    for item in raw_configs:
        if not isinstance(item, Mapping) or not isinstance(item.get("candidate_config"), Mapping):
            raise QualityNormalizationStudyError("diagnosis configuration is malformed")
        config = item["candidate_config"]
        lookback = config.get("lookback_bars")
        if lookback in LOOKBACKS and _decimal(config.get("min_candidate_quality"), field_name="candidate min quality") == Decimal("0.4"):
            if item.get("label") != item.get("trial_id") or lookback in labels:
                raise QualityNormalizationStudyError("diagnosis 0.40 configuration identity drift")
            labels[lookback] = item["label"]
    if set(labels) != set(LOOKBACKS):
        raise QualityNormalizationStudyError("diagnosis omits approved 0.40 configurations")
    expected_positions = {
        position
        for _, start, end in EXPECTED_VALIDATION_WINDOWS
        for position in range(start, end + 1)
    }
    output: dict[int, tuple[tuple[Mapping[str, Any], Mapping[str, Any]], ...]] = {}
    for lookback, label in labels.items():
        records = [record for record in raw_records if record.get("configuration_label") == label]
        if len(records) != 288 or {record.get("position") for record in records} != expected_positions:
            raise QualityNormalizationStudyError("diagnosis 0.40 validation universe drift")
        rows: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
        for record in records:
            if record.get("position") >= PLANNED_HOLDOUT_START or record.get("provider_status") != "rejected_low_quality_candidates":
                raise QualityNormalizationStudyError("diagnosis 0.40 record overlaps holdout or is not rejected")
            shadow = record.get("shadow")
            if not isinstance(shadow, Mapping) or shadow.get("delta") != {"candidate.min_candidate_quality": 0.0} or shadow.get("candidate_count") != 2:
                raise QualityNormalizationStudyError("diagnosis 0.40 shadow exposure drift")
            candidates = shadow.get("candidates")
            if not isinstance(candidates, list) or len(candidates) != 2:
                raise QualityNormalizationStudyError("diagnosis 0.40 candidate exposure drift")
            if {candidate.get("role") for candidate in candidates} != set(ROLES):
                raise QualityNormalizationStudyError("diagnosis 0.40 role balance drift")
            rows.extend((record, candidate) for candidate in candidates)
        if len(rows) != 576:
            raise QualityNormalizationStudyError("diagnosis 0.40 candidate count drift")
        output[lookback] = tuple(sorted(rows, key=lambda item: _candidate_key(*item)))
    return output


def reconstruct_matched_triplets(*, diagnosis_bundle: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    diagnosis = diagnosis_bundle.get("rejection_diagnosis")
    if not isinstance(diagnosis, Mapping):
        raise QualityNormalizationStudyError("validated diagnosis bundle lacks payload")
    records = _records_for_quality_population(diagnosis)
    by_lookback = {
        lookback: {_candidate_key(record, candidate): (record, candidate) for record, candidate in rows}
        for lookback, rows in records.items()
    }
    if any(len(values) != 576 for values in by_lookback.values()):
        raise QualityNormalizationStudyError("matched population has duplicate structural keys")
    keys = set(by_lookback[120])
    if any(set(by_lookback[lookback]) != keys for lookback in LOOKBACKS[1:]):
        raise QualityNormalizationStudyError("matched population structural keys differ across lookbacks")
    triplets: list[Mapping[str, Any]] = []
    for key in sorted(keys):
        fold_id, position, observed_at, role, candidate_id, anchor_ids, anchor_timestamps, span_seconds = key
        span_bars = span_seconds / Decimal(TIMEFRAME_SECONDS)
        if span_bars <= 0 or span_bars != span_bars.to_integral_value():
            raise QualityNormalizationStudyError("anchor span does not equal exact positive 4h bars")
        observed = _parse_utc(observed_at, field_name="candidate observed_at")
        last_anchor = _parse_utc(anchor_timestamps[-1], field_name="candidate last anchor timestamp")
        age_bars = Decimal((observed - last_anchor).total_seconds()) / Decimal(TIMEFRAME_SECONDS)
        if age_bars < 0 or age_bars != age_bars.to_integral_value():
            raise QualityNormalizationStudyError("last anchor age is not exact non-negative 4h bars")
        current_scores: dict[str, str] = {}
        current_coverage: dict[str, str] = {}
        current_errors: dict[str, str] = {}
        path_lengths: dict[str, int] = {}
        for lookback in LOOKBACKS:
            _, candidate = by_lookback[lookback][key]
            quality = _decimal(candidate.get("normalized_quality"), field_name="persisted normalized quality")
            coverage = _decimal(candidate.get("coverage"), field_name="persisted coverage")
            expected = current_score(anchor_span_bars=int(span_bars), lookback_bars=lookback)
            error = abs(quality - expected)
            if error > CURRENT_TOLERANCE or abs(coverage - expected) > CURRENT_TOLERANCE:
                raise QualityNormalizationStudyError("persisted current quality does not match lookback-relative formula")
            if candidate.get("quality_method") != QUALITY_METHOD:
                raise QualityNormalizationStudyError("candidate quality method drift")
            path_length = candidate.get("path_length")
            if isinstance(path_length, bool) or not isinstance(path_length, int) or path_length < 2:
                raise QualityNormalizationStudyError("candidate path length is invalid")
            current_scores[str(lookback)] = _decimal_text(quality)
            current_coverage[str(lookback)] = _decimal_text(coverage)
            current_errors[str(lookback)] = _decimal_text(error)
            path_lengths[str(lookback)] = path_length
        triplet_semantic = {
            "fold_id": fold_id,
            "position": position,
            "observed_at": observed_at,
            "role": role,
            "candidate_id": candidate_id,
            "anchor_ids": list(anchor_ids),
            "anchor_timestamps": list(anchor_timestamps),
            "anchor_span_seconds": _decimal_text(span_seconds),
        }
        triplets.append(
            {
                "triplet_id": semantic_id("trendline-family-candidate-quality-triplet", triplet_semantic),
                **triplet_semantic,
                "anchor_span_bars": int(span_bars),
                "last_anchor_age_bars": int(age_bars),
                "path_lengths_by_lookback": path_lengths,
                "path_length_deltas": {
                    "180_minus_120": path_lengths["180"] - path_lengths["120"],
                    "240_minus_120": path_lengths["240"] - path_lengths["120"],
                    "240_minus_180": path_lengths["240"] - path_lengths["180"],
                },
                "persisted_current_scores": current_scores,
                "persisted_current_coverage": current_coverage,
                "current_formula_absolute_errors": current_errors,
            }
        )
    if len(triplets) != 576:
        raise QualityNormalizationStudyError("matched triplet count drift")
    if Counter(item["role"] for item in triplets) != Counter({"SUPPORT": 288, "RESISTANCE": 288}):
        raise QualityNormalizationStudyError("matched triplet role count drift")
    return tuple(sorted(triplets, key=lambda item: item["triplet_id"]))


def current_score(*, anchor_span_bars: int, lookback_bars: int) -> Decimal:
    if anchor_span_bars <= 0 or lookback_bars not in LOOKBACKS:
        raise QualityNormalizationStudyError("current formula inputs are invalid")
    with localcontext() as context:
        context.prec = 50
        return Decimal(anchor_span_bars) / Decimal(lookback_bars - 1)


def fixed_linear_score(*, anchor_span_bars: int, horizon_bars: int) -> Decimal:
    if anchor_span_bars <= 0 or horizon_bars not in HORIZONS:
        raise QualityNormalizationStudyError("fixed linear formula inputs are invalid")
    with localcontext() as context:
        context.prec = 50
        return min(Decimal(anchor_span_bars) / Decimal(horizon_bars), Decimal(1))


def fixed_saturating_score(*, anchor_span_bars: int, horizon_bars: int) -> Decimal:
    if anchor_span_bars <= 0 or horizon_bars not in HORIZONS:
        raise QualityNormalizationStudyError("fixed saturating formula inputs are invalid")
    with localcontext() as context:
        context.prec = 50
        return Decimal(anchor_span_bars) / (Decimal(anchor_span_bars) + Decimal(horizon_bars))


def formula_catalog() -> tuple[Mapping[str, Any], ...]:
    catalog: list[Mapping[str, Any]] = [
        {
            "formula_id": "lookback_relative_anchor_span_coverage_v1",
            "family": "current_control",
            "version": "v1",
            "horizon_bars": None,
            "equation": "anchor_span_bars / (lookback_bars - 1)",
            "input_fields": ["anchor_span_bars", "lookback_bars"],
            "depends_on_lookback": True,
            "depends_on_empirical_distribution": False,
            "uses_path_length": False,
            "uses_role": False,
            "uses_fold": False,
            "uses_recency": False,
            "uses_outcomes": False,
            "bounded_expected": True,
            "monotonic_non_decreasing_in_anchor_span": True,
        }
    ]
    for horizon in HORIZONS:
        catalog.append(
            {
                "formula_id": f"fixed_horizon_linear_v1_h{horizon}",
                "family": "fixed_horizon_linear_v1",
                "version": "v1",
                "horizon_bars": horizon,
                "equation": "min(anchor_span_bars / H, 1)",
                "input_fields": ["anchor_span_bars", "H"],
                "depends_on_lookback": False,
                "depends_on_empirical_distribution": False,
                "uses_path_length": False,
                "uses_role": False,
                "uses_fold": False,
                "uses_recency": False,
                "uses_outcomes": False,
                "bounded_expected": True,
                "monotonic_non_decreasing_in_anchor_span": True,
            }
        )
    for horizon in HORIZONS:
        catalog.append(
            {
                "formula_id": f"fixed_horizon_saturating_v1_h{horizon}",
                "family": "fixed_horizon_saturating_v1",
                "version": "v1",
                "horizon_bars": horizon,
                "equation": "anchor_span_bars / (anchor_span_bars + H)",
                "input_fields": ["anchor_span_bars", "H"],
                "depends_on_lookback": False,
                "depends_on_empirical_distribution": False,
                "uses_path_length": False,
                "uses_role": False,
                "uses_fold": False,
                "uses_recency": False,
                "uses_outcomes": False,
                "bounded_expected": True,
                "monotonic_non_decreasing_in_anchor_span": True,
            }
        )
    return tuple(catalog)


def _formula_scores(formula: Mapping[str, Any], triplets: Sequence[Mapping[str, Any]]) -> Mapping[str, Mapping[str, Decimal]]:
    output: dict[str, Mapping[str, Decimal]] = {}
    for triplet in triplets:
        span = triplet["anchor_span_bars"]
        formula_id = formula["formula_id"]
        if formula_id == "lookback_relative_anchor_span_coverage_v1":
            scores = {str(lookback): current_score(anchor_span_bars=span, lookback_bars=lookback) for lookback in LOOKBACKS}
        elif formula["family"] == "fixed_horizon_linear_v1":
            score = fixed_linear_score(anchor_span_bars=span, horizon_bars=formula["horizon_bars"])
            scores = {str(lookback): score for lookback in LOOKBACKS}
        elif formula["family"] == "fixed_horizon_saturating_v1":
            score = fixed_saturating_score(anchor_span_bars=span, horizon_bars=formula["horizon_bars"])
            scores = {str(lookback): score for lookback in LOOKBACKS}
        else:
            raise QualityNormalizationStudyError("formula catalog contains unsupported family")
        if any(score < 0 or score > 1 for score in scores.values()):
            raise QualityNormalizationStudyError("formula score is outside [0, 1]")
        output[triplet["triplet_id"]] = scores
    return output


def _ranking_equal(left: Mapping[str, Decimal], right: Mapping[str, Decimal]) -> bool:
    return sorted(left, key=lambda key: (left[key], key)) == sorted(right, key=lambda key: (right[key], key))


def _scope_triplets(triplets: Sequence[Mapping[str, Any]], *, fold_index: int | None = None, role: str | None = None) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        item
        for item in triplets
        if (fold_index is None or item["fold_id"] in _fold_ids_by_index(triplets)[fold_index]) and (role is None or item["role"] == role)
    )


def _fold_ids_by_index(triplets: Sequence[Mapping[str, Any]]) -> Mapping[int, set[str]]:
    groups: dict[int, set[str]] = defaultdict(set)
    expected = {0: range(252, 348), 1: range(360, 456), 2: range(468, 564)}
    for triplet in triplets:
        position = triplet["position"]
        fold_index = next((index for index, positions in expected.items() if position in positions), None)
        if fold_index is None:
            raise QualityNormalizationStudyError("triplet enters non-validation position")
        groups[fold_index].add(triplet["fold_id"])
    if set(groups) != {0, 1, 2} or any(len(ids) != 1 for ids in groups.values()):
        raise QualityNormalizationStudyError("triplet fold identity is invalid")
    return groups


def build_current_method_audit(*, triplets: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    scores = {
        str(lookback): {triplet["triplet_id"]: current_score(anchor_span_bars=triplet["anchor_span_bars"], lookback_bars=lookback) for triplet in triplets}
        for lookback in LOOKBACKS
    }
    with localcontext() as context:
        context.prec = 50
        ratios = (
            (120, 180, Decimal(179) / Decimal(119)),
            (120, 240, Decimal(239) / Decimal(119)),
            (180, 240, Decimal(239) / Decimal(179)),
        )
    pair_audits = []
    for left, right, expected_ratio in ratios:
        with localcontext() as context:
            context.prec = 50
            observed = [scores[str(left)][triplet_id] / scores[str(right)][triplet_id] for triplet_id in scores[str(left)]]
        differences = [abs(scores[str(left)][triplet_id] - scores[str(right)][triplet_id]) for triplet_id in scores[str(left)]]
        pair_audits.append(
            {
                "left_lookback_bars": left,
                "right_lookback_bars": right,
                "expected_score_ratio": _decimal_text(expected_ratio),
                "observed_score_ratio": _summary(observed),
                "maximum_absolute_score_difference": _decimal_text(max(differences)),
                "rank_order_equal": _ranking_equal(scores[str(left)], scores[str(right)]),
            }
        )
    persisted_errors = [
        _decimal(value, field_name="persisted current formula error")
        for triplet in triplets
        for value in triplet["current_formula_absolute_errors"].values()
    ]
    threshold_support = []
    for threshold_bps in (3000, 3500, 4000):
        counts = {
            str(lookback): sum(
                score >= _threshold(threshold_bps)
                for score in scores[str(lookback)].values()
            )
            for lookback in LOOKBACKS
        }
        threshold_support.append(
            {
                "threshold_bps": threshold_bps,
                "threshold": _threshold_text(threshold_bps),
                "accepted_candidate_counts_by_lookback": counts,
                "absolute_score_scaling_only": True,
            }
        )
    return {
        "formula_id": "lookback_relative_anchor_span_coverage_v1",
        "denominators": {str(lookback): lookback - 1 for lookback in LOOKBACKS},
        "persisted_score_instance_count": len(persisted_errors),
        "reconstructed_vs_persisted_absolute_error": _summary(persisted_errors),
        "all_errors_within_1e-12": all(error <= CURRENT_TOLERANCE for error in persisted_errors),
        "cross_lookback_score_ratios": pair_audits,
        "threshold_support_differences_inherited_from_score_scaling": threshold_support,
        "matched_geometry_identical_absolute_scores_lookback_relative": True,
    }


def build_invariance_audit(*, catalog: Sequence[Mapping[str, Any]], triplets: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any], ...]:
    fold_ids = _fold_ids_by_index(triplets)
    output: list[Mapping[str, Any]] = []
    for formula in catalog:
        scores = _formula_scores(formula, triplets)
        per_triplet_differences = [max(values.values()) - min(values.values()) for values in scores.values()]
        per_role = {}
        for role in ROLES:
            keys = [triplet["triplet_id"] for triplet in triplets if triplet["role"] == role]
            differences = [max(scores[key].values()) - min(scores[key].values()) for key in keys]
            per_role[role] = {"triplet_count": len(keys), "unequal_score_triplet_count": sum(value != 0 for value in differences), "exact_equality": all(value == 0 for value in differences)}
        per_fold = {}
        for fold_index, ids in fold_ids.items():
            keys = [triplet["triplet_id"] for triplet in triplets if triplet["fold_id"] in ids]
            differences = [max(scores[key].values()) - min(scores[key].values()) for key in keys]
            per_fold[str(fold_index)] = {"triplet_count": len(keys), "unequal_score_triplet_count": sum(value != 0 for value in differences), "exact_equality": all(value == 0 for value in differences)}
        output.append(
            {
                "formula_id": formula["formula_id"],
                "maximum_absolute_score_difference_across_lookbacks": _decimal_text(max(per_triplet_differences)),
                "unequal_score_triplet_count": sum(value != 0 for value in per_triplet_differences),
                "exact_lookback_invariance": all(value == 0 for value in per_triplet_differences),
                "rank_order_equality": {
                    "120_vs_180": _ranking_equal({key: values["120"] for key, values in scores.items()}, {key: values["180"] for key, values in scores.items()}),
                    "120_vs_240": _ranking_equal({key: values["120"] for key, values in scores.items()}, {key: values["240"] for key, values in scores.items()}),
                    "180_vs_240": _ranking_equal({key: values["180"] for key, values in scores.items()}, {key: values["240"] for key, values in scores.items()}),
                },
                "per_role": per_role,
                "per_fold": per_fold,
            }
        )
    return tuple(output)


def _score_distribution(values: Sequence[Decimal]) -> Mapping[str, Any]:
    summary = _summary(values)
    groups = Counter(values)
    q25 = _decimal(summary["quantiles"]["0.25"], field_name="q25")
    q75 = _decimal(summary["quantiles"]["0.75"], field_name="q75")
    return {
        **summary,
        "unique_score_count": len(groups),
        "largest_tie_group_count": max(groups.values()),
        "largest_tie_group_share": _decimal_text(Decimal(max(groups.values())) / Decimal(len(values))),
        "zero_score_fraction": _decimal_text(Decimal(sum(value == 0 for value in values)) / Decimal(len(values))),
        "one_score_saturation_fraction": _decimal_text(Decimal(sum(value == 1 for value in values)) / Decimal(len(values))),
        "score_range": _decimal_text(max(values) - min(values)),
        "interquartile_range": _decimal_text(q75 - q25),
    }


def build_score_distributions(*, catalog: Sequence[Mapping[str, Any]], triplets: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    fold_ids = _fold_ids_by_index(triplets)
    output: dict[str, Any] = {}
    scopes = [("aggregate", None, None)] + [(f"fold_{index}", ids, None) for index, ids in fold_ids.items()] + [(f"role_{role}", None, role) for role in ROLES]
    for formula in catalog:
        scores = _formula_scores(formula, triplets)
        per_lookback = {}
        for lookback in LOOKBACKS:
            rows = []
            for scope, ids, role in scopes:
                scoped = [triplet for triplet in triplets if (ids is None or triplet["fold_id"] in ids) and (role is None or triplet["role"] == role)]
                rows.append({"scope": scope, "score_distribution": _score_distribution([scores[triplet["triplet_id"]][str(lookback)] for triplet in scoped])})
            per_lookback[str(lookback)] = rows
        output[formula["formula_id"]] = per_lookback
    return output


def _curve_scope(
    triplets: Sequence[Mapping[str, Any]],
    scores: Mapping[str, Mapping[str, Decimal]],
    *,
    lookback: int,
    threshold_bps: int,
    fold_ids: set[str] | None,
    role: str | None = None,
) -> Mapping[str, Any]:
    scoped = [
        triplet
        for triplet in triplets
        if (fold_ids is None or triplet["fold_id"] in fold_ids)
        and (role is None or triplet["role"] == role)
    ]
    if not scoped:
        raise QualityNormalizationStudyError("support curve scope is empty")
    threshold = _threshold(threshold_bps)
    accepted = [triplet for triplet in scoped if scores[triplet["triplet_id"]][str(lookback)] >= threshold]
    by_position: dict[tuple[str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for triplet in accepted:
        by_position[(triplet["fold_id"], triplet["position"])].append(triplet)
    role_counts = Counter(item["role"] for item in accepted)
    fold_counts = Counter(item["fold_id"] for item in accepted)
    roles_by_bar = Counter(
        "both_role" if len({item["role"] for item in values}) == 2 else f"{values[0]['role'].lower()}_only"
        for values in by_position.values()
    )
    fold_values = [fold_counts[fold_id] for fold_id in sorted({item["fold_id"] for item in scoped})]
    return {
        "threshold_bps": threshold_bps,
        "threshold": _threshold_text(threshold_bps),
        "accepted_candidate_count": len(accepted),
        "producing_bar_count": len(by_position),
        "support_candidate_count": role_counts["SUPPORT"],
        "resistance_candidate_count": role_counts["RESISTANCE"],
        "both_role_bar_count": roles_by_bar["both_role"],
        "no_role_bar_count": len({(item["fold_id"], item["position"]) for item in scoped}) - len(by_position),
        "smallest_fold_accepted_candidate_count": min(fold_values),
        "largest_fold_accepted_candidate_count": max(fold_values),
        "largest_fold_concentration": None if not accepted else _decimal_text(Decimal(max(fold_values)) / Decimal(len(accepted))),
    }


def build_support_curves(*, catalog: Sequence[Mapping[str, Any]], triplets: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    fold_ids = _fold_ids_by_index(triplets)
    output: dict[str, Any] = {}
    for formula in catalog:
        scores = _formula_scores(formula, triplets)
        per_lookback = {}
        for lookback in LOOKBACKS:
            rows = []
            for bps in THRESHOLD_BPS:
                aggregate = _curve_scope(triplets, scores, lookback=lookback, threshold_bps=bps, fold_ids=None)
                folds = [
                    {"fold_index": fold_index, **_curve_scope(triplets, scores, lookback=lookback, threshold_bps=bps, fold_ids=ids)}
                    for fold_index, ids in sorted(fold_ids.items())
                ]
                roles = [
                    {"role": role, **_curve_scope(triplets, scores, lookback=lookback, threshold_bps=bps, fold_ids=None, role=role)}
                    for role in ROLES
                ]
                fold_roles = [
                    {
                        "fold_index": fold_index,
                        "role": role,
                        **_curve_scope(triplets, scores, lookback=lookback, threshold_bps=bps, fold_ids=ids, role=role),
                    }
                    for fold_index, ids in sorted(fold_ids.items())
                    for role in ROLES
                ]
                rows.append(
                    {
                        "threshold_bps": bps,
                        "threshold": _threshold_text(bps),
                        "aggregate": aggregate,
                        "folds": folds,
                        "roles": roles,
                        "fold_roles": fold_roles,
                    }
                )
            counts = [row["aggregate"]["accepted_candidate_count"] for row in rows]
            producing = [row["aggregate"]["producing_bar_count"] for row in rows]
            if counts != sorted(counts, reverse=True) or producing != sorted(producing, reverse=True):
                raise QualityNormalizationStudyError("formula support curve is not monotonic")
            supported = [row for row in rows if row["aggregate"]["accepted_candidate_count"] >= 100]
            highest = None if not supported else max(supported, key=lambda row: row["threshold_bps"])
            per_lookback[str(lookback)] = {
                "curve": rows,
                "descriptive_highest_threshold_with_at_least_100_candidates_bps": None if highest is None else highest["threshold_bps"],
                "every_fold_non_empty_at_highest_threshold": None if highest is None else all(
                    fold["accepted_candidate_count"] > 0 for fold in highest["folds"]
                ),
            }
        output[formula["formula_id"]] = per_lookback
    return output


def build_eligibility_table(*, catalog: Sequence[Mapping[str, Any]], invariance: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any], ...]:
    by_formula = {item["formula_id"]: item for item in invariance}
    output: list[Mapping[str, Any]] = []
    for formula in catalog:
        inv = by_formula[formula["formula_id"]]
        gates = {
            "deterministic_from_persisted_causal_structural_fields": True,
            "bounded_in_0_1": formula["bounded_expected"],
            "monotonic_non_decreasing_in_anchor_span": formula["monotonic_non_decreasing_in_anchor_span"],
            "exact_lookback_invariance_for_matched_geometry": inv["exact_lookback_invariance"],
            "no_role_or_fold_specific_behavior": not formula["uses_role"] and not formula["uses_fold"],
            "no_empirical_distribution_fitting": not formula["depends_on_empirical_distribution"],
            "no_future_outcomes": not formula["uses_outcomes"],
            "no_recency_or_path_length_mixing": not formula["uses_recency"] and not formula["uses_path_length"],
            "no_runtime_or_yaml_implication": True,
        }
        output.append(
            {
                "formula_id": formula["formula_id"],
                "architecture_gates": gates,
                "eligible_for_fresh_unseen_research": all(gates.values()),
                "failed_architecture_gates": [name for name, passed in gates.items() if not passed],
                "classification_scope": "architecture_only_not_selection_or_promotion",
            }
        )
    return tuple(output)


def _triplet_audit(triplets: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    fold_ids = _fold_ids_by_index(triplets)
    per_fold = {
        str(fold_index): {
            "fold_ids": sorted(ids),
            "triplet_count": sum(item["fold_id"] in ids for item in triplets),
            "support_triplet_count": sum(item["fold_id"] in ids and item["role"] == "SUPPORT" for item in triplets),
            "resistance_triplet_count": sum(item["fold_id"] in ids and item["role"] == "RESISTANCE" for item in triplets),
        }
        for fold_index, ids in sorted(fold_ids.items())
    }
    per_lookback = {
        str(lookback): {
            "validation_bar_count": 288,
            "candidate_count": 576,
            "support_candidate_count": 288,
            "resistance_candidate_count": 288,
            "per_fold": per_fold,
        }
        for lookback in LOOKBACKS
    }
    return {
        "triplet_count": len(triplets),
        "support_triplet_count": sum(item["role"] == "SUPPORT" for item in triplets),
        "resistance_triplet_count": sum(item["role"] == "RESISTANCE" for item in triplets),
        "missing_structural_key_count": 0,
        "duplicate_structural_key_count": 0,
        "mismatched_structural_key_count": 0,
        "cross_lookback_id_anchor_timestamp_span_role_equality": True,
        "candidate_counts_by_lookback_fold_role": per_lookback,
        "anchor_span_bars": _summary([Decimal(item["anchor_span_bars"]) for item in triplets]),
        "last_anchor_age_bars": _summary([Decimal(item["last_anchor_age_bars"]) for item in triplets]),
        "path_length_delta_distributions": {
            name: _summary([Decimal(item["path_length_deltas"][name]) for item in triplets])
            for name in ("180_minus_120", "240_minus_120", "240_minus_180")
        },
        "triplet_audit_id": semantic_id("trendline-family-candidate-quality-triplet-audit", list(triplets)),
        "triplets": list(triplets),
    }


def _score_audit(catalog: Sequence[Mapping[str, Any]], triplets: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    output: dict[str, Any] = {}
    for formula in catalog:
        scores = _formula_scores(formula, triplets)
        output[formula["formula_id"]] = [
            {"triplet_id": triplet_id, "scores_by_lookback": {lookback: _decimal_text(score) for lookback, score in sorted(values.items())}}
            for triplet_id, values in sorted(scores.items())
        ]
    return output


def _quality_study_id(payload: Mapping[str, Any]) -> str:
    identity = payload.get("study_identity")
    if not isinstance(identity, Mapping):
        raise QualityNormalizationStudyError("quality study identity is malformed")
    semantic = {**payload, "study_identity": {key: value for key, value in identity.items() if key != "study_id"}}
    return semantic_id("trendline-family-candidate-quality-normalization-study", semantic)


def build_quality_normalization_payload(*, diagnosis_bundle: Mapping[str, Any], density_bundle: Mapping[str, Any], source_binding: Mapping[str, Any]) -> Mapping[str, Any]:
    _require_identity_sources(diagnosis_bundle, density_bundle)
    triplets = reconstruct_matched_triplets(diagnosis_bundle=diagnosis_bundle)
    catalog = formula_catalog()
    invariance = build_invariance_audit(catalog=catalog, triplets=triplets)
    eligibility = build_eligibility_table(catalog=catalog, invariance=invariance)
    identity = {
        "quality_study_schema_version": QUALITY_STUDY_SCHEMA_VERSION,
        "quality_source_binding_id": source_binding["quality_source_binding_id"],
        "diagnosis_id": EXPECTED_DIAGNOSIS_ID,
        "diagnosis_source_binding_id": EXPECTED_DIAGNOSIS_SOURCE_BINDING_ID,
        "density_study_id": EXPECTED_DENSITY_STUDY_ID,
        "density_source_binding_id": EXPECTED_DENSITY_SOURCE_BINDING_ID,
    }
    payload: dict[str, Any] = {
        "study_identity": identity,
        "source_and_bias_identity": {
            **identity,
            "asset": EXPECTED_ASSET,
            "timeframe": EXPECTED_TIMEFRAME,
            "timeframe_seconds": TIMEFRAME_SECONDS,
            "confirmed_rows": EXPECTED_ROW_COUNT,
            "dataset_hash": EXPECTED_DATASET_HASH,
            "resolved_config_hash": EXPECTED_CONFIG_HASH,
            "phase_i_run_id": EXPECTED_PHASE_I_RUN_ID,
            "report_id": EXPECTED_REPORT_ID,
            "recommendation_id": EXPECTED_RECOMMENDATION_ID,
            "source_binding": source_binding,
            "validation_windows": [
                {"fold_index": index, "start_position": start, "end_position": end, "bar_count": end - start + 1}
                for index, start, end in EXPECTED_VALIDATION_WINDOWS
            ],
            "planned_holdout_start_position": PLANNED_HOLDOUT_START,
            "holdout_accessed": False,
            "provider_calls": 0,
            "evaluator_calls": 0,
            "study_status": "exploratory_post_diagnostic_architecture_study_not_promotional",
            "fresh_unseen_confirmation_required": True,
        },
        "matched_population_audit": _triplet_audit(triplets),
        "current_method_decomposition": build_current_method_audit(triplets=triplets),
        "formula_catalog": list(catalog),
        "formula_score_audit": _score_audit(catalog, triplets),
        "invariance_audit": list(invariance),
        "score_distributions": build_score_distributions(catalog=catalog, triplets=triplets),
        "descriptive_support_curves": build_support_curves(catalog=catalog, triplets=triplets),
        "structural_eligibility": list(eligibility),
        "observations": [
            "All evidence derives from persisted threshold-zero diagnosis candidates and validated density-study provenance.",
            "Raw anchor span remains identical across matched lookback triplets while path length remains audit-only evidence.",
            "Current scores are lookback-relative rescalings of identical raw anchor spans.",
            "Support curves and eligibility are descriptive architecture evidence, not formula, horizon, threshold, or runtime selection.",
        ],
        "research_hypotheses": [
            "Can a bounded subset of structurally eligible fixed-policy formulas be compared on a separately approved fresh unseen window?",
            "Does raw anchor span retain stable structural meaning across a fresh candidate population?",
            "Should relevance/recency remain separate downstream evidence in a future architecture review?",
        ],
        "architecture_implications": [
            "Raw anchor span should remain explicit structural evidence.",
            "Bounded normalization should use an explicit fixed policy scale independent of provider lookback.",
            "Current relevance and recency remain downstream from candidate structural quality.",
        ],
    }
    payload["study_identity"] = {**identity, "study_id": _quality_study_id(payload)}
    return payload


def _markdown(payload: Mapping[str, Any]) -> str:
    sections = (
        ("Source And Bias Identity", payload["source_and_bias_identity"]),
        ("Matched Population Audit", {key: value for key, value in payload["matched_population_audit"].items() if key != "triplets"}),
        ("Current Method Decomposition", payload["current_method_decomposition"]),
        ("Formula Catalog", payload["formula_catalog"]),
        ("Invariance Audit", payload["invariance_audit"]),
        ("Structural Eligibility", payload["structural_eligibility"]),
        ("Observations", payload["observations"]),
        ("Research Hypotheses", payload["research_hypotheses"]),
        ("Architecture Implications", payload["architecture_implications"]),
    )
    chunks = [
        "# Trendline-Family Candidate Quality Normalization Study v1\n",
        "> Exploratory post-diagnostic architecture evidence only. No formula, horizon, threshold, lookback, runtime, promotion, or holdout claim.\n",
    ]
    for heading, value in sections:
        chunks.append(f"## {heading}\n\n```json\n{json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True)}\n```\n")
    return "\n".join(chunks)


def _atomic_write_if_identical(path: Path, payload: bytes) -> Path:
    if path.exists():
        if path.read_bytes() != payload:
            raise QualityNormalizationStudyError(f"refusing non-identical quality-study overwrite: {path}")
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


def write_quality_study_bundle(*, output_root: Path, source_binding: Mapping[str, Any], payload: Mapping[str, Any]) -> Mapping[str, Path]:
    source_bytes = canonical_json(source_binding).encode("utf-8") + b"\n"
    study_bytes = canonical_json(payload).encode("utf-8") + b"\n"
    markdown_bytes = _markdown(payload).encode("utf-8")
    identity = payload["study_identity"]
    manifest = {
        "quality_study_schema_version": QUALITY_STUDY_SCHEMA_VERSION,
        "study_id": identity["study_id"],
        "quality_source_binding_id": source_binding["quality_source_binding_id"],
        "diagnosis_id": identity["diagnosis_id"],
        "diagnosis_source_binding_id": identity["diagnosis_source_binding_id"],
        "density_study_id": identity["density_study_id"],
        "density_source_binding_id": identity["density_source_binding_id"],
        "dataset_hash": payload["source_and_bias_identity"]["dataset_hash"],
        "resolved_config_hash": payload["source_and_bias_identity"]["resolved_config_hash"],
        "phase_i_run_id": payload["source_and_bias_identity"]["phase_i_run_id"],
        "report_id": payload["source_and_bias_identity"]["report_id"],
        "recommendation_id": payload["source_and_bias_identity"]["recommendation_id"],
        "source_binding_sha256": _sha256_bytes(source_bytes),
        "quality_normalization_study_json_sha256": _sha256_bytes(study_bytes),
        "quality_normalization_study_markdown_sha256": _sha256_bytes(markdown_bytes),
    }
    manifest_bytes = canonical_json(manifest).encode("utf-8") + b"\n"
    targets = {
        "source_binding": (output_root / "source_binding.json", source_bytes),
        "quality_normalization_study": (output_root / "quality_normalization_study.json", study_bytes),
        "quality_normalization_markdown": (output_root / "quality_normalization_study.md", markdown_bytes),
        "study_manifest": (output_root / "study_manifest.json", manifest_bytes),
    }
    for path, content in targets.values():
        if path.exists() and path.read_bytes() != content:
            raise QualityNormalizationStudyError(f"refusing non-identical quality-study overwrite: {path}")
    return {name: _atomic_write_if_identical(path, content) for name, (path, content) in sorted(targets.items())}


def validate_quality_study_bundle(*, output_root: Path, diagnosis_root: Path = DIAGNOSIS_ROOT, density_root: Path = DENSITY_ROOT) -> Mapping[str, Any]:
    source_path = output_root / "source_binding.json"
    study_path = output_root / "quality_normalization_study.json"
    markdown_path = output_root / "quality_normalization_study.md"
    manifest_path = output_root / "study_manifest.json"
    source_binding = _read_json(source_path, label="quality source binding")
    study = _read_json(study_path, label="quality normalization study")
    manifest = _read_json(manifest_path, label="quality study manifest")
    validated_binding = validate_quality_source_binding_payload(source_binding)
    diagnosis_bundle = validate_diagnosis_bundle(output_root=diagnosis_root)
    density_bundle = validate_density_study_bundle(output_root=density_root, diagnosis_root=diagnosis_root)
    actual_binding = capture_quality_source_binding(diagnosis_root=diagnosis_root, density_root=density_root)
    if canonical_json(validated_binding) != canonical_json(actual_binding):
        raise QualityNormalizationStudyError("quality source binding differs from approved live source bytes")
    identity = study.get("study_identity")
    source_identity = study.get("source_and_bias_identity")
    if not isinstance(identity, Mapping) or not isinstance(source_identity, Mapping):
        raise QualityNormalizationStudyError("quality study identity sections are malformed")
    if canonical_json(source_identity.get("source_binding")) != canonical_json(validated_binding):
        raise QualityNormalizationStudyError("quality study embedded source binding differs from validated source binding")
    expected_study = build_quality_normalization_payload(
        diagnosis_bundle=diagnosis_bundle,
        density_bundle=density_bundle,
        source_binding=actual_binding,
    )
    if canonical_json(study) != canonical_json(expected_study):
        raise QualityNormalizationStudyError("quality study differs from independently rederived source analysis")
    if identity.get("study_id") != _quality_study_id(study):
        raise QualityNormalizationStudyError("quality study content-addressed identity mismatch")
    expected_identity = {
        "quality_study_schema_version": QUALITY_STUDY_SCHEMA_VERSION,
        "quality_source_binding_id": validated_binding["quality_source_binding_id"],
        "diagnosis_id": EXPECTED_DIAGNOSIS_ID,
        "diagnosis_source_binding_id": EXPECTED_DIAGNOSIS_SOURCE_BINDING_ID,
        "density_study_id": EXPECTED_DENSITY_STUDY_ID,
        "density_source_binding_id": EXPECTED_DENSITY_SOURCE_BINDING_ID,
    }
    if any(identity.get(key) != value for key, value in expected_identity.items()):
        raise QualityNormalizationStudyError("quality study identity claim mismatch")
    if any(source_identity.get(key) != value for key, value in expected_identity.items()):
        raise QualityNormalizationStudyError("quality study source identity claim mismatch")
    if source_identity.get("holdout_accessed") is not False or source_identity.get("provider_calls") != 0 or source_identity.get("evaluator_calls") != 0:
        raise QualityNormalizationStudyError("quality study execution boundary claim mismatch")
    manifest_expected = {
        **expected_identity,
        "study_id": identity["study_id"],
        "dataset_hash": EXPECTED_DATASET_HASH,
        "resolved_config_hash": EXPECTED_CONFIG_HASH,
        "phase_i_run_id": EXPECTED_PHASE_I_RUN_ID,
        "report_id": EXPECTED_REPORT_ID,
        "recommendation_id": EXPECTED_RECOMMENDATION_ID,
    }
    required_manifest = set(manifest_expected) | {
        "source_binding_sha256",
        "quality_normalization_study_json_sha256",
        "quality_normalization_study_markdown_sha256",
    }
    if set(manifest) != required_manifest:
        raise QualityNormalizationStudyError("quality study manifest fields are invalid")
    if any(manifest.get(key) != value for key, value in manifest_expected.items()):
        raise QualityNormalizationStudyError("quality study manifest identity mismatch")
    if _sha256_bytes(source_path.read_bytes()) != _require_sha256(manifest.get("source_binding_sha256"), field_name="quality study manifest source binding sha256"):
        raise QualityNormalizationStudyError("quality study manifest source binding hash mismatch")
    if _sha256_bytes(study_path.read_bytes()) != _require_sha256(manifest.get("quality_normalization_study_json_sha256"), field_name="quality study manifest JSON sha256"):
        raise QualityNormalizationStudyError("quality study manifest JSON hash mismatch")
    markdown_bytes = markdown_path.read_bytes()
    if markdown_bytes != _markdown(study).encode("utf-8"):
        raise QualityNormalizationStudyError("quality study Markdown content does not match study JSON")
    if _sha256_bytes(markdown_bytes) != _require_sha256(manifest.get("quality_normalization_study_markdown_sha256"), field_name="quality study manifest Markdown sha256"):
        raise QualityNormalizationStudyError("quality study manifest Markdown hash mismatch")
    return {"source_binding": validated_binding, "quality_normalization_study": study, "study_manifest": manifest}


def build_candidate_quality_normalization_study(*, diagnosis_root: Path = DIAGNOSIS_ROOT, density_root: Path = DENSITY_ROOT, output_root: Path = OUTPUT_ROOT) -> Mapping[str, Path]:
    before = capture_protected_source_inventories()
    diagnosis_bundle = validate_diagnosis_bundle(output_root=diagnosis_root)
    density_bundle = validate_density_study_bundle(output_root=density_root, diagnosis_root=diagnosis_root)
    source_binding = capture_quality_source_binding(diagnosis_root=diagnosis_root, density_root=density_root)
    payload = build_quality_normalization_payload(diagnosis_bundle=diagnosis_bundle, density_bundle=density_bundle, source_binding=source_binding)
    paths = write_quality_study_bundle(output_root=output_root, source_binding=source_binding, payload=payload)
    validate_quality_study_bundle(output_root=output_root, diagnosis_root=diagnosis_root, density_root=density_root)
    after = capture_protected_source_inventories()
    if canonical_json(before) != canonical_json(after):
        raise QualityNormalizationStudyError("protected source bytes changed during quality study")
    return paths


def main() -> None:
    paths = build_candidate_quality_normalization_study()
    print(json.dumps({name: str(path) for name, path in sorted(paths.items())}, sort_keys=True))


if __name__ == "__main__":
    main()
