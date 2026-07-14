"""Read-only density study over approved candidate-rejection diagnosis evidence."""

# ruff: noqa: E402

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from hashlib import sha256
import json
import math
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

from libs.models.trendline_family.contracts import ContractValidationError
from libs.models.trendline_family.optimization.contracts import canonical_json, semantic_id
from scripts.diagnose_trendline_family_candidate_rejection import (
    OUTPUT_ROOT as DIAGNOSIS_ROOT,
    validate_diagnosis_bundle,
)


STUDY_SCHEMA_VERSION = "trendline_family_candidate_density_study_v1"
TRIAL_NAME = "btcusdt_4h_20250801_20251201_candidate_geometry_v2"
V1_TRIAL_NAME = "btcusdt_4h_20250801_20251201_candidate_geometry_v1"
OUTPUT_ROOT = PROJECT_ROOT / "artifacts" / "trendline_family_candidate_density_studies" / TRIAL_NAME
V1_TRIAL_ROOT = PROJECT_ROOT / "artifacts" / "trendline_family_candidate_trials" / V1_TRIAL_NAME
V2_TRIAL_ROOT = PROJECT_ROOT / "artifacts" / "trendline_family_candidate_trials" / TRIAL_NAME
REPORT_ROOT = PROJECT_ROOT / "artifacts" / "trendline_family_candidate_reports" / TRIAL_NAME
CONFIG_PATH = PROJECT_ROOT / "configs" / "trendline_family.yaml"

EXPECTED_ASSET = "BTCUSDT"
EXPECTED_TIMEFRAME = "4h"
EXPECTED_ROW_COUNT = 732
EXPECTED_DATASET_HASH = "trendline-family-dataset_ccaf20405ffc4b84ea98f79e97053e3ee6be4b0c571999dcbf5fc0e0bca1ad53"
EXPECTED_CONFIG_HASH = "da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f"
EXPECTED_PHASE_I_RUN_ID = "trendline-family-phase-i-run_6393c4d86edb7558045b96e5c5be39fd915d8a8dde29b44e66515fdbf44b37e7"
EXPECTED_REPORT_ID = "trendline-family-candidate-evidence-report_5e01522b2ac82f67e6a722372e6deba4ea77c7fe9ea47b5415ef7d65bc3d2d41"
EXPECTED_RECOMMENDATION_ID = "trendline-family-promotion-recommendation_fdcf8d4b39ffda53b3f09b26ff28bec40056677ce18cc90eb2292b310005ccbc"
EXPECTED_DIAGNOSIS_ID = "trendline-family-candidate-rejection-diagnosis_d45c7463e1e8410a4fb9004ee7ad83b26d3c994d3a44ce781f7ff38a5025ecbf"
EXPECTED_DIAGNOSIS_SOURCE_BINDING_ID = "trendline-family-candidate-rejection-source-binding_06a563f43accc93acd9e3df59ff8d78174b861debe483446073b4c7b42e6500a"
EXPECTED_CONFIG_SHA256 = "7a7fbc156a0ed3e01ac5b3d7502a76e834d6b34668daa8a569f32b4e63a887d8"
EXPECTED_VALIDATION_WINDOWS = ((0, 252, 347), (1, 360, 455), (2, 468, 563))
PLANNED_HOLDOUT_START = 636
VALIDATION_BAR_COUNT = 288
EXPOSED_CANDIDATE_COUNT = 576
MINIMUM_SAMPLE_COUNT = 100
LOOKBACKS = (120, 180, 240)
ROLES = ("SUPPORT", "RESISTANCE")
QUALITY_METHOD = "anchor_span_coverage_v1"
THRESHOLD_BPS = tuple(range(0, 4001, 100))
RECONCILIATION_BPS = (3000, 3500, 4000)
EXPECTED_ACCEPTED_COUNTS = {
    (120, 3000): 47,
    (120, 4000): 0,
    (180, 3000): 0,
    (180, 3500): 0,
    (180, 4000): 0,
    (240, 3000): 0,
    (240, 4000): 0,
}
EXPECTED_DIAGNOSIS_FILES = (
    "diagnosis_manifest.json",
    "rejection_diagnosis.json",
    "rejection_diagnosis.md",
    "source_binding.json",
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class CandidateDensityStudyError(ContractValidationError):
    """Raised when approved diagnosis evidence or study provenance is invalid."""


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _read_json(path: Path, *, label: str) -> Mapping[str, Any]:
    if not path.is_file():
        raise CandidateDensityStudyError(f"required {label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateDensityStudyError(f"invalid {label} JSON: {path}") from exc
    if not isinstance(value, Mapping):
        raise CandidateDensityStudyError(f"{label} JSON must be a mapping: {path}")
    return value


def _require_sha256(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise CandidateDensityStudyError(f"{field_name} must be a lowercase 64-character SHA-256")
    return value


def _validate_relative_path(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CandidateDensityStudyError(f"{field_name} must be a non-empty string")
    if value.startswith("/") or "\\" in value or any(part in {"", ".", ".."} for part in value.split("/")):
        raise CandidateDensityStudyError(f"{field_name} must be a safe canonical POSIX relative path")
    return value


def _validate_file_records(
    value: Any,
    *,
    field_name: str,
    expected_paths: Sequence[str] | None = None,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise CandidateDensityStudyError(f"{field_name} must be a non-empty sequence")
    files: list[Mapping[str, Any]] = []
    paths: list[str] = []
    for index, record in enumerate(value):
        if not isinstance(record, Mapping) or set(record) != {"relative_path", "size_bytes", "sha256"}:
            raise CandidateDensityStudyError(f"{field_name} record {index} fields are invalid")
        relative_path = _validate_relative_path(record.get("relative_path"), field_name=f"{field_name} record {index} relative_path")
        size_bytes = record.get("size_bytes")
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
            raise CandidateDensityStudyError(f"{field_name} record {index} size_bytes is invalid")
        files.append(
            {
                "relative_path": relative_path,
                "size_bytes": size_bytes,
                "sha256": _require_sha256(record.get("sha256"), field_name=f"{field_name} record {index} sha256"),
            }
        )
        paths.append(relative_path)
    if len(paths) != len(set(paths)):
        raise CandidateDensityStudyError(f"{field_name} paths must be unique")
    if paths != sorted(paths):
        raise CandidateDensityStudyError(f"{field_name} paths must be strictly sorted")
    if expected_paths is not None and tuple(paths) != tuple(expected_paths):
        raise CandidateDensityStudyError(f"{field_name} differs from approved file set")
    return tuple(files)


def _file_inventory(root: Path, *, source_name: str, expected_paths: Sequence[str] | None = None) -> Mapping[str, Any]:
    if not root.is_dir():
        raise CandidateDensityStudyError(f"source root is missing: {root}")
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
        raise CandidateDensityStudyError(f"source root has no files: {root}")
    if expected_paths is not None and tuple(item["relative_path"] for item in files) != tuple(expected_paths):
        raise CandidateDensityStudyError(f"source root file set differs: {source_name}")
    semantic = {"source_name": source_name, "root_name": root.name, "files": files}
    return {**semantic, "inventory_sha256": _sha256_bytes(canonical_json(semantic).encode("utf-8"))}


def capture_protected_source_inventories() -> Mapping[str, Any]:
    """Read protected roots only; fail if approved inventory shape has drifted."""

    inventories = {
        "v1_trial": _file_inventory(V1_TRIAL_ROOT, source_name="v1_trial"),
        "v2_trial": _file_inventory(V2_TRIAL_ROOT, source_name="v2_trial"),
        "approved_report": _file_inventory(REPORT_ROOT, source_name="approved_report"),
        "approved_diagnosis": _file_inventory(DIAGNOSIS_ROOT, source_name="approved_diagnosis"),
    }
    expected_counts = {"v1_trial": 1, "v2_trial": 30, "approved_report": 4, "approved_diagnosis": 4}
    if {key: len(value["files"]) for key, value in inventories.items()} != expected_counts:
        raise CandidateDensityStudyError("protected source inventory count drift")
    config_bytes = CONFIG_PATH.read_bytes() if CONFIG_PATH.is_file() else None
    if config_bytes is None:
        raise CandidateDensityStudyError("approved config is missing")
    config = {
        "relative_path": "configs/trendline_family.yaml",
        "size_bytes": len(config_bytes),
        "sha256": _sha256_bytes(config_bytes),
    }
    if config["sha256"] != EXPECTED_CONFIG_SHA256:
        raise CandidateDensityStudyError("approved config SHA-256 drift")
    return {**inventories, "config": config}


def capture_study_source_binding(*, diagnosis_root: Path) -> Mapping[str, Any]:
    """Capture only four immutable diagnosis files after diagnosis validation."""

    verified = validate_diagnosis_bundle(output_root=diagnosis_root)
    diagnosis = verified["rejection_diagnosis"]
    identity = diagnosis.get("diagnosis_identity")
    if not isinstance(identity, Mapping):
        raise CandidateDensityStudyError("approved diagnosis identity is malformed")
    if identity.get("diagnosis_id") != EXPECTED_DIAGNOSIS_ID:
        raise CandidateDensityStudyError("approved diagnosis ID drift")
    if identity.get("source_binding_id") != EXPECTED_DIAGNOSIS_SOURCE_BINDING_ID:
        raise CandidateDensityStudyError("approved diagnosis source-binding ID drift")
    inventory = _file_inventory(
        diagnosis_root,
        source_name="approved_diagnosis_bundle",
        expected_paths=EXPECTED_DIAGNOSIS_FILES,
    )
    semantic = {
        "study_schema_version": STUDY_SCHEMA_VERSION,
        "diagnosis_id": identity["diagnosis_id"],
        "diagnosis_source_binding_id": identity["source_binding_id"],
        "diagnosis_inventory": inventory,
    }
    return {
        **semantic,
        "study_source_binding_id": semantic_id("trendline-family-candidate-density-study-source-binding", semantic),
    }


def validate_study_source_binding_payload(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Purely validate persisted study-source provenance and rederive its ID."""

    expected_fields = {
        "study_schema_version",
        "diagnosis_id",
        "diagnosis_source_binding_id",
        "diagnosis_inventory",
        "study_source_binding_id",
    }
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise CandidateDensityStudyError("study source binding top-level fields are invalid")
    if value.get("study_schema_version") != STUDY_SCHEMA_VERSION:
        raise CandidateDensityStudyError("study source binding schema version mismatch")
    if value.get("diagnosis_id") != EXPECTED_DIAGNOSIS_ID:
        raise CandidateDensityStudyError("study source binding diagnosis ID mismatch")
    if value.get("diagnosis_source_binding_id") != EXPECTED_DIAGNOSIS_SOURCE_BINDING_ID:
        raise CandidateDensityStudyError("study source binding diagnosis source-binding ID mismatch")
    raw_inventory = value.get("diagnosis_inventory")
    if not isinstance(raw_inventory, Mapping) or set(raw_inventory) != {"source_name", "root_name", "files", "inventory_sha256"}:
        raise CandidateDensityStudyError("study diagnosis inventory fields are invalid")
    if raw_inventory.get("source_name") != "approved_diagnosis_bundle":
        raise CandidateDensityStudyError("study diagnosis inventory source_name mismatch")
    if raw_inventory.get("root_name") != TRIAL_NAME:
        raise CandidateDensityStudyError("study diagnosis inventory root_name mismatch")
    files = _validate_file_records(
        raw_inventory.get("files"),
        field_name="study diagnosis inventory files",
        expected_paths=EXPECTED_DIAGNOSIS_FILES,
    )
    inventory_semantic = {
        "source_name": "approved_diagnosis_bundle",
        "root_name": TRIAL_NAME,
        "files": files,
    }
    inventory_hash = _sha256_bytes(canonical_json(inventory_semantic).encode("utf-8"))
    if _require_sha256(raw_inventory.get("inventory_sha256"), field_name="study diagnosis inventory inventory_sha256") != inventory_hash:
        raise CandidateDensityStudyError("study diagnosis inventory_sha256 mismatch")
    semantic = {
        "study_schema_version": STUDY_SCHEMA_VERSION,
        "diagnosis_id": EXPECTED_DIAGNOSIS_ID,
        "diagnosis_source_binding_id": EXPECTED_DIAGNOSIS_SOURCE_BINDING_ID,
        "diagnosis_inventory": {**inventory_semantic, "inventory_sha256": inventory_hash},
    }
    derived_id = semantic_id("trendline-family-candidate-density-study-source-binding", semantic)
    if value.get("study_source_binding_id") != derived_id:
        raise CandidateDensityStudyError("study source binding ID mismatch")
    return {**semantic, "study_source_binding_id": derived_id}


def _decimal(value: Any, *, field_name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float, str)):
        raise CandidateDensityStudyError(f"{field_name} must be numeric")
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise CandidateDensityStudyError(f"{field_name} must be a decimal") from exc
    if not result.is_finite():
        raise CandidateDensityStudyError(f"{field_name} must be finite")
    return result


def _threshold_decimal(threshold_bps: int) -> Decimal:
    if isinstance(threshold_bps, bool) or not isinstance(threshold_bps, int) or threshold_bps not in THRESHOLD_BPS:
        raise CandidateDensityStudyError("threshold basis points are outside approved grid")
    return Decimal(threshold_bps) / Decimal(10_000)


def _threshold_text(threshold_bps: int) -> str:
    return f"{threshold_bps // 10000}.{(threshold_bps % 10000) // 100:02d}"


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


def _fixed_identity(diagnosis: Mapping[str, Any]) -> Mapping[str, Any]:
    identity = diagnosis.get("diagnosis_identity")
    execution = diagnosis.get("source_and_execution_identity")
    boundaries = diagnosis.get("dataset_and_fold_boundaries")
    if not isinstance(identity, Mapping) or not isinstance(execution, Mapping) or not isinstance(boundaries, Mapping):
        raise CandidateDensityStudyError("approved diagnosis identity sections are malformed")
    expected = {
        "diagnosis_id": EXPECTED_DIAGNOSIS_ID,
        "source_binding_id": EXPECTED_DIAGNOSIS_SOURCE_BINDING_ID,
        "dataset_hash": EXPECTED_DATASET_HASH,
        "resolved_config_hash": EXPECTED_CONFIG_HASH,
        "phase_i_run_id": EXPECTED_PHASE_I_RUN_ID,
        "report_id": EXPECTED_REPORT_ID,
        "recommendation_id": EXPECTED_RECOMMENDATION_ID,
    }
    if any(identity.get(key) != value for key, value in expected.items()):
        raise CandidateDensityStudyError("approved diagnosis fixed identity drift")
    if boundaries.get("asset") != EXPECTED_ASSET or boundaries.get("timeframe") != EXPECTED_TIMEFRAME:
        raise CandidateDensityStudyError("approved diagnosis asset/timeframe drift")
    if boundaries.get("row_count") != EXPECTED_ROW_COUNT or boundaries.get("dataset_hash") != EXPECTED_DATASET_HASH:
        raise CandidateDensityStudyError("approved diagnosis dataset identity drift")
    if execution.get("actual_provider_call_count") != 2016 or execution.get("shadow_provider_call_count") != 1969:
        raise CandidateDensityStudyError("approved diagnosis call-count drift")
    holdout = execution.get("planned_holdout_exclusion")
    if not isinstance(holdout, Mapping) or holdout.get("planned_holdout_start_position") != PLANNED_HOLDOUT_START:
        raise CandidateDensityStudyError("approved diagnosis holdout boundary drift")
    if holdout.get("maximum_replayed_position") != 563 or holdout.get("all_replayed_positions_before_holdout") is not True:
        raise CandidateDensityStudyError("approved diagnosis validation replay boundary drift")
    return {**expected, "asset": EXPECTED_ASSET, "timeframe": EXPECTED_TIMEFRAME, "confirmed_rows": EXPECTED_ROW_COUNT}


def _folds(diagnosis: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    boundaries = diagnosis.get("dataset_and_fold_boundaries")
    if not isinstance(boundaries, Mapping) or not isinstance(boundaries.get("validation_windows"), list):
        raise CandidateDensityStudyError("diagnosis validation windows are malformed")
    folds = tuple(sorted(boundaries["validation_windows"], key=lambda item: item.get("fold_index", -1)))
    actual = tuple((item.get("fold_index"), item.get("start_position"), item.get("end_position")) for item in folds)
    if actual != EXPECTED_VALIDATION_WINDOWS:
        raise CandidateDensityStudyError("diagnosis validation windows drift")
    if any(item.get("bar_count") != 96 or not isinstance(item.get("fold_id"), str) for item in folds):
        raise CandidateDensityStudyError("diagnosis validation fold shape is invalid")
    return folds


def _configuration_index(diagnosis: Mapping[str, Any]) -> Mapping[tuple[int, int], Mapping[str, Any]]:
    raw = diagnosis.get("configuration_matrix")
    if not isinstance(raw, list) or len(raw) != 7:
        raise CandidateDensityStudyError("diagnosis configuration matrix must contain seven entries")
    result: dict[tuple[int, int], Mapping[str, Any]] = {}
    baseline: Mapping[str, Any] | None = None
    for item in raw:
        if not isinstance(item, Mapping) or not isinstance(item.get("candidate_config"), Mapping):
            raise CandidateDensityStudyError("diagnosis configuration entry is malformed")
        config = item["candidate_config"]
        lookback = config.get("lookback_bars")
        quality_bps = int(_decimal(config.get("min_candidate_quality"), field_name="candidate min quality") * 10_000)
        if lookback == 180 and quality_bps == 3500 and item.get("label") == "baseline":
            baseline = item
            continue
        if isinstance(lookback, bool) or not isinstance(lookback, int) or (lookback, quality_bps) not in EXPECTED_ACCEPTED_COUNTS:
            raise CandidateDensityStudyError("diagnosis primary configuration drift")
        if item.get("label") != item.get("trial_id") or not isinstance(item.get("trial_id"), str):
            raise CandidateDensityStudyError("diagnosis primary configuration label drift")
        if (lookback, quality_bps) in result:
            raise CandidateDensityStudyError("diagnosis primary configuration is duplicated")
        result[(lookback, quality_bps)] = item
    if baseline is None:
        raise CandidateDensityStudyError("diagnosis baseline configuration is missing")
    result[(180, 3500)] = baseline
    if set(result) != set(EXPECTED_ACCEPTED_COUNTS):
        raise CandidateDensityStudyError("diagnosis configuration matrix does not match approved grid")
    return result


def _record_key(record: Mapping[str, Any]) -> tuple[str, int]:
    fold_id = record.get("fold_id")
    position = record.get("position")
    if not isinstance(fold_id, str) or isinstance(position, bool) or not isinstance(position, int):
        raise CandidateDensityStudyError("diagnostic record fold/position is invalid")
    return fold_id, position


def _records_by_configuration(
    diagnosis: Mapping[str, Any],
    *,
    configurations: Mapping[tuple[int, int], Mapping[str, Any]],
    folds: Sequence[Mapping[str, Any]],
) -> Mapping[tuple[int, int], tuple[Mapping[str, Any], ...]]:
    raw = diagnosis.get("diagnostic_records")
    if not isinstance(raw, list) or len(raw) != 2016:
        raise CandidateDensityStudyError("diagnosis record count drift")
    expected_universe = {
        (fold["fold_id"], position)
        for fold in folds
        for position in range(fold["start_position"], fold["end_position"] + 1)
    }
    labels = {key: value["label"] for key, value in configurations.items()}
    result: dict[tuple[int, int], tuple[Mapping[str, Any], ...]] = {}
    for key, label in labels.items():
        records = tuple(sorted((record for record in raw if record.get("configuration_label") == label), key=lambda item: (item["fold_index"], item["position"])))
        if len(records) != VALIDATION_BAR_COUNT:
            raise CandidateDensityStudyError("diagnosis configuration does not have 288 validation records")
        if {_record_key(record) for record in records} != expected_universe:
            raise CandidateDensityStudyError("diagnosis configurations do not share approved validation universe")
        if any(record.get("position", PLANNED_HOLDOUT_START) >= PLANNED_HOLDOUT_START for record in records):
            raise CandidateDensityStudyError("diagnosis records overlap planned holdout")
        if any(record.get("trial_id") != configurations[key].get("trial_id") for record in records):
            raise CandidateDensityStudyError("diagnosis record trial identity drift")
        result[key] = records
    return result


def _candidate_identity(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        candidate.get("candidate_id"),
        candidate.get("role"),
        tuple(candidate.get("anchor_ids", ())),
        _decimal(candidate.get("quality", candidate.get("normalized_quality")), field_name="candidate normalized_quality"),
        _decimal(candidate.get("coverage"), field_name="candidate coverage"),
        candidate.get("path_length"),
        _decimal(candidate.get("anchor_span_seconds"), field_name="candidate anchor_span_seconds"),
        candidate.get("quality_method"),
    )


def _canonical_candidate(record: Mapping[str, Any], candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    role = candidate.get("role")
    anchor_ids = candidate.get("anchor_ids")
    quality = _decimal(candidate.get("normalized_quality"), field_name="candidate normalized_quality")
    coverage = _decimal(candidate.get("coverage"), field_name="candidate coverage")
    path_length = candidate.get("path_length")
    span_seconds = _decimal(candidate.get("anchor_span_seconds"), field_name="candidate anchor_span_seconds")
    if role not in ROLES or not isinstance(anchor_ids, list) or len(anchor_ids) != 2 or len(set(anchor_ids)) != 2:
        raise CandidateDensityStudyError("exposed candidate role or anchors are invalid")
    if any(not isinstance(anchor_id, str) or not anchor_id for anchor_id in anchor_ids):
        raise CandidateDensityStudyError("exposed candidate anchor IDs are invalid")
    if isinstance(path_length, bool) or not isinstance(path_length, int) or path_length < 2:
        raise CandidateDensityStudyError("exposed candidate path length is invalid")
    if quality < 0 or quality > 1 or span_seconds <= 0:
        raise CandidateDensityStudyError("exposed candidate quality/span is invalid")
    if quality != coverage:
        raise CandidateDensityStudyError("anchor_span_coverage_v1 requires equal quality and coverage")
    if candidate.get("quality_method") != QUALITY_METHOD:
        raise CandidateDensityStudyError("exposed candidate quality method drift")
    fold_index = record.get("fold_index")
    position = record.get("position")
    if isinstance(fold_index, bool) or not isinstance(fold_index, int) or isinstance(position, bool) or not isinstance(position, int):
        raise CandidateDensityStudyError("exposed candidate record position is invalid")
    return {
        "candidate_id": candidate.get("candidate_id"),
        "role": role,
        "anchor_ids": tuple(anchor_ids),
        "quality": quality,
        "coverage": coverage,
        "path_length": path_length,
        "anchor_span_seconds": span_seconds,
        "fold_id": record["fold_id"],
        "fold_index": fold_index,
        "position": position,
        "observed_at": record.get("observed_at"),
        "quality_method": QUALITY_METHOD,
    }


def reconstruct_canonical_exposure(
    *,
    records_by_configuration: Mapping[tuple[int, int], tuple[Mapping[str, Any], ...]],
    folds: Sequence[Mapping[str, Any]],
) -> Mapping[int, tuple[Mapping[str, Any], ...]]:
    """Recover threshold-zero candidates only from persisted 0.40 shadow records."""

    expected_fold_positions = {
        fold["fold_id"]: set(range(fold["start_position"], fold["end_position"] + 1)) for fold in folds
    }
    exposures: dict[int, tuple[Mapping[str, Any], ...]] = {}
    for lookback in LOOKBACKS:
        records = records_by_configuration[(lookback, 4000)]
        candidates: list[Mapping[str, Any]] = []
        for record in records:
            if record.get("provider_status") != "rejected_low_quality_candidates" or record.get("accepted_candidate_count") != 0:
                raise CandidateDensityStudyError("0.40 source record must be a low-quality rejection")
            shadow = record.get("shadow")
            if not isinstance(shadow, Mapping) or shadow.get("delta") != {"candidate.min_candidate_quality": 0.0}:
                raise CandidateDensityStudyError("0.40 source record omits canonical threshold-zero shadow")
            if shadow.get("candidate_count") != 2 or not isinstance(shadow.get("candidates"), list) or len(shadow["candidates"]) != 2:
                raise CandidateDensityStudyError("0.40 source record must expose exactly two candidates")
            row = tuple(_canonical_candidate(record, item) for item in shadow["candidates"])
            if {item["role"] for item in row} != set(ROLES):
                raise CandidateDensityStudyError("0.40 exposure must contain one support and one resistance candidate")
            if any(item["quality"] >= Decimal("0.40") for item in row):
                raise CandidateDensityStudyError("0.40 exposure candidate violates low-quality threshold")
            candidates.extend(row)
        if len(candidates) != EXPOSED_CANDIDATE_COUNT:
            raise CandidateDensityStudyError("canonical exposure candidate count drift")
        if Counter(item["role"] for item in candidates) != Counter({"SUPPORT": 288, "RESISTANCE": 288}):
            raise CandidateDensityStudyError("canonical exposure role balance drift")
        positions = {(item["fold_id"], item["position"]) for item in candidates}
        expected_positions = {(fold_id, position) for fold_id, values in expected_fold_positions.items() for position in values}
        if positions != expected_positions:
            raise CandidateDensityStudyError("canonical exposure position universe drift")
        exposures[lookback] = tuple(sorted(candidates, key=lambda item: (item["fold_index"], item["position"], item["role"], item["candidate_id"])))
    return exposures


def _accepted_exposure(exposure: Sequence[Mapping[str, Any]], threshold_bps: int) -> tuple[Mapping[str, Any], ...]:
    threshold = _threshold_decimal(threshold_bps)
    return tuple(item for item in exposure if item["quality"] >= threshold)


def _curve_scope(
    *,
    candidates: Sequence[Mapping[str, Any]],
    scope_folds: Sequence[Mapping[str, Any]],
    threshold_bps: int,
    aggregate: bool,
) -> Mapping[str, Any]:
    positions = {
        (fold["fold_id"], position)
        for fold in scope_folds
        for position in range(fold["start_position"], fold["end_position"] + 1)
    }
    scoped = tuple(item for item in candidates if (item["fold_id"], item["position"]) in positions)
    accepted = _accepted_exposure(scoped, threshold_bps)
    accepted_by_position: dict[tuple[str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for item in accepted:
        accepted_by_position[(item["fold_id"], item["position"])].append(item)
    role_counts = Counter(item["role"] for item in accepted)
    bar_roles = Counter(
        "both_role" if len({item["role"] for item in values}) == 2 else f"{values[0]['role'].lower()}_only"
        for values in accepted_by_position.values()
    )
    final_positions = {
        (fold["fold_id"], position)
        for fold in scope_folds
        for position in range(fold["end_position"] - 11, fold["end_position"] + 1)
    }
    per_fold_counts = [sum(item["fold_id"] == fold["fold_id"] for item in accepted) for fold in scope_folds]
    total = len(accepted)
    support = role_counts["SUPPORT"]
    resistance = role_counts["RESISTANCE"]
    return {
        "scope": "aggregate" if aggregate else f"fold_{scope_folds[0]['fold_index']}",
        "fold_ids": [fold["fold_id"] for fold in scope_folds],
        "threshold_bps": threshold_bps,
        "threshold": _threshold_text(threshold_bps),
        "validation_bar_count": len(positions),
        "exposed_candidate_count": len(scoped),
        "accepted_candidate_count": total,
        "producing_bar_count": len(accepted_by_position),
        "no_candidate_bar_count": len(positions) - len(accepted_by_position),
        "support_candidate_count": support,
        "resistance_candidate_count": resistance,
        "support_only_bar_count": bar_roles["support_only"],
        "resistance_only_bar_count": bar_roles["resistance_only"],
        "both_role_bar_count": bar_roles["both_role"],
        "no_role_bar_count": len(positions) - len(accepted_by_position),
        "candidates_per_validation_bar": total / len(positions),
        "producing_bar_ratio": len(accepted_by_position) / len(positions),
        "final_12_bar_candidate_count": sum((item["fold_id"], item["position"]) in final_positions for item in accepted),
        "horizon_eligible_candidate_count": sum((item["fold_id"], item["position"]) not in final_positions for item in accepted),
        "smallest_fold_accepted_candidate_count": min(per_fold_counts),
        "largest_fold_accepted_candidate_count": max(per_fold_counts),
        "largest_fold_share_of_total_candidates": None if total == 0 else max(per_fold_counts) / total,
        "role_balance_ratio": None if support == 0 or resistance == 0 else min(support, resistance) / max(support, resistance),
    }


def build_threshold_support_curves(
    *,
    exposures: Mapping[int, Sequence[Mapping[str, Any]]],
    folds: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    curves: dict[str, Any] = {}
    for lookback in LOOKBACKS:
        entries: list[Mapping[str, Any]] = []
        for threshold_bps in THRESHOLD_BPS:
            fold_entries = [
                _curve_scope(candidates=exposures[lookback], scope_folds=(fold,), threshold_bps=threshold_bps, aggregate=False)
                for fold in folds
            ]
            aggregate = _curve_scope(candidates=exposures[lookback], scope_folds=folds, threshold_bps=threshold_bps, aggregate=True)
            entries.append({"threshold_bps": threshold_bps, "threshold": _threshold_text(threshold_bps), "folds": fold_entries, "aggregate": aggregate})
        aggregate_counts = [entry["aggregate"]["accepted_candidate_count"] for entry in entries]
        aggregate_bars = [entry["aggregate"]["producing_bar_count"] for entry in entries]
        if aggregate_counts != sorted(aggregate_counts, reverse=True) or aggregate_bars != sorted(aggregate_bars, reverse=True):
            raise CandidateDensityStudyError("threshold support curve is not monotonic")
        curves[str(lookback)] = entries
    return curves


def _candidate_lookup(candidates: Sequence[Mapping[str, Any]]) -> Mapping[tuple[str, int, tuple[Any, ...]], Mapping[str, Any]]:
    lookup: dict[tuple[str, int, tuple[Any, ...]], Mapping[str, Any]] = {}
    for candidate in candidates:
        key = (candidate["fold_id"], candidate["position"], _candidate_identity(candidate))
        if key in lookup:
            raise CandidateDensityStudyError("canonical exposure candidate identity is duplicated")
        lookup[key] = candidate
    return lookup


def reconcile_existing_thresholds(
    *,
    exposures: Mapping[int, Sequence[Mapping[str, Any]]],
    records_by_configuration: Mapping[tuple[int, int], Sequence[Mapping[str, Any]]],
    folds: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for lookback, threshold_bps in sorted(EXPECTED_ACCEPTED_COUNTS):
        actual_records = records_by_configuration[(lookback, threshold_bps)]
        expected = _accepted_exposure(exposures[lookback], threshold_bps)
        actual_candidates = tuple(candidate for record in actual_records for candidate in record.get("accepted_candidates", ()))
        expected_lookup = _candidate_lookup(expected)
        actual_keys = {
            (record["fold_id"], record["position"], _candidate_identity(candidate))
            for record in actual_records
            for candidate in record.get("accepted_candidates", ())
        }
        if set(expected_lookup) != actual_keys:
            raise CandidateDensityStudyError("canonical exposure does not reconcile accepted diagnosis candidates")
        actual_by_fold = Counter(record["fold_id"] for record in actual_records for _ in record.get("accepted_candidates", ()))
        expected_by_fold = Counter(candidate["fold_id"] for candidate in expected)
        actual_producing = sum(record.get("accepted_candidate_count") > 0 for record in actual_records)
        expected_producing = len({(candidate["fold_id"], candidate["position"]) for candidate in expected})
        if len(actual_candidates) != len(expected) or actual_producing != expected_producing:
            raise CandidateDensityStudyError("canonical exposure count reconciliation failed")
        if actual_by_fold != expected_by_fold:
            raise CandidateDensityStudyError("canonical exposure fold reconciliation failed")
        if len(expected) != EXPECTED_ACCEPTED_COUNTS[(lookback, threshold_bps)]:
            raise CandidateDensityStudyError("approved accepted-candidate count drift")
        rows.append(
            {
                "lookback_bars": lookback,
                "threshold_bps": threshold_bps,
                "threshold": _threshold_text(threshold_bps),
                "accepted_candidate_count": len(expected),
                "producing_bar_count": expected_producing,
                "support_candidate_count": sum(item["role"] == "SUPPORT" for item in expected),
                "resistance_candidate_count": sum(item["role"] == "RESISTANCE" for item in expected),
                "per_fold_accepted_candidate_count": [
                    {"fold_id": fold["fold_id"], "count": expected_by_fold[fold["fold_id"]]} for fold in folds
                ],
                "reconciled": True,
            }
        )
    return rows


def _curve_entry(curves: Mapping[str, Any], lookback: int, threshold_bps: int) -> Mapping[str, Any]:
    entries = curves.get(str(lookback))
    if not isinstance(entries, list):
        raise CandidateDensityStudyError("threshold curves omit lookback")
    entry = next((item for item in entries if item.get("threshold_bps") == threshold_bps), None)
    if not isinstance(entry, Mapping):
        raise CandidateDensityStudyError("threshold curves omit threshold")
    return entry


def _curve_scope_entry(entry: Mapping[str, Any], scope: str) -> Mapping[str, Any]:
    if scope == "aggregate":
        aggregate = entry.get("aggregate")
        if isinstance(aggregate, Mapping):
            return aggregate
    else:
        scoped = next((item for item in entry.get("folds", ()) if item.get("scope") == scope), None)
        if isinstance(scoped, Mapping):
            return scoped
    raise CandidateDensityStudyError("threshold curve scope is missing")


def build_support_frontiers(*, curves: Mapping[str, Any]) -> Mapping[str, Any]:
    frontiers: dict[str, Any] = {}
    for lookback in LOOKBACKS:
        entries = curves[str(lookback)]
        supported = [item for item in entries if item["aggregate"]["accepted_candidate_count"] >= MINIMUM_SAMPLE_COUNT]
        highest = None if not supported else max(supported, key=lambda item: item["threshold_bps"])
        crossings = [
            item["threshold_bps"]
            for previous, item in zip(entries, entries[1:])
            if previous["aggregate"]["accepted_candidate_count"] >= MINIMUM_SAMPLE_COUNT
            and item["aggregate"]["accepted_candidate_count"] < MINIMUM_SAMPLE_COUNT
        ]
        current_deficits = {}
        for threshold_bps in RECONCILIATION_BPS:
            aggregate = _curve_entry(curves, lookback, threshold_bps)["aggregate"]
            current_deficits[str(threshold_bps)] = {
                "threshold": _threshold_text(threshold_bps),
                "aggregate_deficit_to_100": max(0, MINIMUM_SAMPLE_COUNT - aggregate["accepted_candidate_count"]),
                "per_fold_deficit_to_100": [
                    max(0, MINIMUM_SAMPLE_COUNT - fold["accepted_candidate_count"])
                    for fold in _curve_entry(curves, lookback, threshold_bps)["folds"]
                ],
                "per_fold_non_empty_deficit": [
                    int(fold["accepted_candidate_count"] == 0)
                    for fold in _curve_entry(curves, lookback, threshold_bps)["folds"]
                ],
            }
        frontiers[str(lookback)] = {
            "minimum_sample_count": MINIMUM_SAMPLE_COUNT,
            "descriptive_only": True,
            "thresholds_with_aggregate_support_at_least_100_bps": [item["threshold_bps"] for item in supported],
            "highest_grid_threshold_with_aggregate_support_at_least_100_bps": None if highest is None else highest["threshold_bps"],
            "highest_grid_threshold_with_aggregate_support_at_least_100": None if highest is None else highest["threshold"],
            "every_fold_non_empty_at_highest_support": None if highest is None else all(
                item["accepted_candidate_count"] > 0 for item in highest["folds"]
            ),
            "accepted_candidate_count_per_fold_at_highest_support": None if highest is None else [
                {"fold_id": item["fold_ids"][0], "count": item["accepted_candidate_count"]} for item in highest["folds"]
            ],
            "thresholds_where_aggregate_support_crosses_below_100_bps": crossings,
            "current_threshold_deficits": current_deficits,
        }
    return frontiers


def build_distributions(*, exposures: Mapping[int, Sequence[Mapping[str, Any]]], folds: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    output: dict[str, Any] = {}
    scopes = [("aggregate", tuple(folds))] + [(f"fold_{fold['fold_index']}", (fold,)) for fold in folds]
    for lookback in LOOKBACKS:
        rows: list[Mapping[str, Any]] = []
        for scope, scope_folds in scopes:
            fold_ids = {fold["fold_id"] for fold in scope_folds}
            for role in ROLES:
                candidates = [item for item in exposures[lookback] if item["fold_id"] in fold_ids and item["role"] == role]
                quality = [float(item["quality"]) for item in candidates]
                coverage = [float(item["coverage"]) for item in candidates]
                if any(_decimal(item["quality"], field_name="quality") != _decimal(item["coverage"], field_name="coverage") for item in candidates):
                    raise CandidateDensityStudyError("quality/coverage distribution contract drift")
                rows.append(
                    {
                        "scope": scope,
                        "fold_ids": sorted(fold_ids),
                        "role": role,
                        "quality_method": QUALITY_METHOD,
                        "normalized_quality": _summary(quality),
                        "coverage": _summary(coverage),
                        "path_length": _summary([float(item["path_length"]) for item in candidates]),
                        "anchor_span_seconds": _summary([float(item["anchor_span_seconds"]) for item in candidates]),
                        "anchor_span_4h_bars": _summary([float(item["anchor_span_seconds"] / Decimal(14_400)) for item in candidates]),
                        "threshold_gaps": {
                            _threshold_text(bps): _summary([float(_threshold_decimal(bps) - item["quality"]) for item in candidates])
                            for bps in RECONCILIATION_BPS
                        },
                    }
                )
        output[str(lookback)] = rows
    return output


def _consecutive_runs(positions: Sequence[int]) -> tuple[int, ...]:
    if not positions:
        return ()
    runs: list[int] = []
    start = previous = positions[0]
    for position in positions[1:]:
        if position != previous + 1:
            runs.append(previous - start + 1)
            start = position
        previous = position
    runs.append(previous - start + 1)
    return tuple(runs)


def build_anchor_pair_persistence(*, exposures: Mapping[int, Sequence[Mapping[str, Any]]]) -> Mapping[str, Any]:
    output: dict[str, Any] = {}
    for lookback in LOOKBACKS:
        per_role: list[Mapping[str, Any]] = []
        for role in ROLES:
            candidates = [item for item in exposures[lookback] if item["role"] == role]
            grouped: dict[tuple[str, tuple[str, ...]], list[Mapping[str, Any]]] = defaultdict(list)
            for item in candidates:
                grouped[(role, item["anchor_ids"])].append(item)
            descriptors: list[Mapping[str, Any]] = []
            all_runs: list[int] = []
            repeated_bars = 0
            for (key_role, anchor_ids), values in grouped.items():
                ordered = sorted(values, key=lambda item: (item["fold_index"], item["position"]))
                runs: list[int] = []
                for fold_index in sorted({item["fold_index"] for item in ordered}):
                    runs.extend(_consecutive_runs([item["position"] for item in ordered if item["fold_index"] == fold_index]))
                all_runs.extend(runs)
                if len(ordered) > 1:
                    repeated_bars += len(ordered)
                descriptors.append(
                    {
                        "role": key_role,
                        "anchor_ids": list(anchor_ids),
                        "bar_count": len(ordered),
                        "first_position": ordered[0]["position"],
                        "last_position": ordered[-1]["position"],
                        "lifetime_positions": ordered[-1]["position"] - ordered[0]["position"] + 1,
                        "maximum_consecutive_run_length": max(runs),
                        "median_consecutive_run_length": statistics.median(runs),
                    }
                )
            top = sorted(descriptors, key=lambda item: (-item["bar_count"], item["anchor_ids"], item["role"]))[:20]
            per_role.append(
                {
                    "role": role,
                    "distinct_structural_key_count": len(grouped),
                    "bars_covered_by_repeated_keys": repeated_bars,
                    "fraction_of_bars_with_repeated_key": repeated_bars / len(candidates),
                    "maximum_consecutive_run_length": max(all_runs),
                    "median_consecutive_run_length": statistics.median(all_runs),
                    "top_repeated_keys": top,
                }
            )
        output[str(lookback)] = per_role
    return output


def _summary_delta(left: Mapping[str, Any], right: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "mean_right_minus_left": None if left["mean"] is None or right["mean"] is None else right["mean"] - left["mean"],
        "median_right_minus_left": None if left["median"] is None or right["median"] is None else right["median"] - left["median"],
    }


def build_lookback_contrasts(
    *,
    curves: Mapping[str, Any],
    distributions: Mapping[str, Any],
    frontiers: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    contrasts: list[Mapping[str, Any]] = []
    for left, right in ((120, 180), (120, 240), (180, 240)):
        scopes: list[Mapping[str, Any]] = []
        for scope in ("aggregate", "fold_0", "fold_1", "fold_2"):
            left_distributions = {item["role"]: item for item in distributions[str(left)] if item["scope"] == scope}
            right_distributions = {item["role"]: item for item in distributions[str(right)] if item["scope"] == scope}
            scopes.append(
                {
                    "scope": scope,
                    "quality_distribution_deltas": {
                        role: _summary_delta(left_distributions[role]["normalized_quality"], right_distributions[role]["normalized_quality"])
                        for role in ROLES
                    },
                    "anchor_span_distribution_deltas": {
                        role: _summary_delta(left_distributions[role]["anchor_span_seconds"], right_distributions[role]["anchor_span_seconds"])
                        for role in ROLES
                    },
                    "path_length_distribution_deltas": {
                        role: _summary_delta(left_distributions[role]["path_length"], right_distributions[role]["path_length"])
                        for role in ROLES
                    },
                    "threshold_deltas": [
                        {
                            "threshold_bps": bps,
                            "accepted_candidate_count_right_minus_left": _curve_scope_entry(
                                _curve_entry(curves, right, bps), scope
                            )["accepted_candidate_count"]
                            - _curve_scope_entry(_curve_entry(curves, left, bps), scope)["accepted_candidate_count"],
                            "producing_bar_count_right_minus_left": _curve_scope_entry(
                                _curve_entry(curves, right, bps), scope
                            )["producing_bar_count"]
                            - _curve_scope_entry(_curve_entry(curves, left, bps), scope)["producing_bar_count"],
                            "role_balance_ratio_right_minus_left": _nullable_difference(
                                _curve_scope_entry(_curve_entry(curves, left, bps), scope)["role_balance_ratio"],
                                _curve_scope_entry(_curve_entry(curves, right, bps), scope)["role_balance_ratio"],
                            ),
                        }
                        for bps in THRESHOLD_BPS
                    ],
                }
            )
        contrasts.append(
            {
                "left_lookback_bars": left,
                "right_lookback_bars": right,
                "support_frontier_highest_bps_right_minus_left": _nullable_difference(
                    frontiers[str(left)]["highest_grid_threshold_with_aggregate_support_at_least_100_bps"],
                    frontiers[str(right)]["highest_grid_threshold_with_aggregate_support_at_least_100_bps"],
                ),
                "scopes": scopes,
            }
        )
    return contrasts


def _nullable_difference(left: float | int | None, right: float | int | None) -> float | int | None:
    return None if left is None or right is None else right - left


def _canonical_exposure_summary(exposures: Mapping[int, Sequence[Mapping[str, Any]]]) -> Mapping[str, Any]:
    return {
        str(lookback): {
            "validation_bar_count": VALIDATION_BAR_COUNT,
            "exposed_candidate_count": len(exposures[lookback]),
            "support_candidate_count": sum(item["role"] == "SUPPORT" for item in exposures[lookback]),
            "resistance_candidate_count": sum(item["role"] == "RESISTANCE" for item in exposures[lookback]),
            "quality_method": QUALITY_METHOD,
            "source_threshold_bps": 4000,
            "source_threshold": "0.40",
        }
        for lookback in LOOKBACKS
    }


def _study_id(payload: Mapping[str, Any]) -> str:
    identity = payload.get("study_identity")
    if not isinstance(identity, Mapping):
        raise CandidateDensityStudyError("study identity is malformed")
    semantic = {
        **payload,
        "study_identity": {key: value for key, value in identity.items() if key != "study_id"},
    }
    return semantic_id("trendline-family-candidate-density-study", semantic)


def build_density_study_payload(*, diagnosis_bundle: Mapping[str, Any], source_binding: Mapping[str, Any]) -> Mapping[str, Any]:
    """Build deterministic descriptive study from diagnosis records only."""

    diagnosis = diagnosis_bundle.get("rejection_diagnosis")
    if not isinstance(diagnosis, Mapping):
        raise CandidateDensityStudyError("validated diagnosis bundle lacks diagnosis payload")
    fixed_identity = _fixed_identity(diagnosis)
    folds = _folds(diagnosis)
    configurations = _configuration_index(diagnosis)
    records = _records_by_configuration(diagnosis, configurations=configurations, folds=folds)
    exposures = reconstruct_canonical_exposure(records_by_configuration=records, folds=folds)
    curves = build_threshold_support_curves(exposures=exposures, folds=folds)
    reconciliation = reconcile_existing_thresholds(exposures=exposures, records_by_configuration=records, folds=folds)
    distributions = build_distributions(exposures=exposures, folds=folds)
    frontiers = build_support_frontiers(curves=curves)
    persistence = build_anchor_pair_persistence(exposures=exposures)
    contrasts = build_lookback_contrasts(curves=curves, distributions=distributions, frontiers=frontiers)
    identity = {
        "study_schema_version": STUDY_SCHEMA_VERSION,
        "study_source_binding_id": source_binding["study_source_binding_id"],
        "diagnosis_id": fixed_identity["diagnosis_id"],
        "diagnosis_source_binding_id": fixed_identity["source_binding_id"],
    }
    payload: dict[str, Any] = {
        "study_identity": identity,
        "source_and_bias_identity": {
            **fixed_identity,
            "study_schema_version": STUDY_SCHEMA_VERSION,
            "study_source_binding_id": source_binding["study_source_binding_id"],
            "diagnosis_source_binding_id": fixed_identity["source_binding_id"],
            "source_binding": source_binding,
            "validation_windows": [
                {
                    "fold_id": fold["fold_id"],
                    "fold_index": fold["fold_index"],
                    "start_position": fold["start_position"],
                    "end_position": fold["end_position"],
                    "bar_count": fold["bar_count"],
                }
                for fold in folds
            ],
            "planned_holdout_start_position": PLANNED_HOLDOUT_START,
            "holdout_accessed": False,
            "study_status": "exploratory_post_diagnostic_not_promotional",
            "fresh_unseen_window_required_for_follow_up": True,
        },
        "canonical_exposure": _canonical_exposure_summary(exposures),
        "threshold_support_curves": curves,
        "existing_threshold_reconciliation": reconciliation,
        "minimum_sample_support_frontier": frontiers,
        "quality_and_structure_distributions": distributions,
        "anchor_pair_persistence": persistence,
        "lookback_contrasts": contrasts,
        "observations": [
            "All values derive only from persisted validation diagnostic_records in the approved diagnosis bundle.",
            "Each 0.40 configuration supplies 288 validation bars and 576 threshold-zero exposed candidates with balanced roles.",
            "Existing 0.30, baseline 0.35, and 0.40 diagnosis records reconcile exactly against canonical exposure.",
            "Support frontiers are descriptive post-diagnostic summaries, not parameter selection or runtime evidence.",
        ],
        "research_hypotheses": [
            "Does anchor_span_coverage_v1 remain above observed density support on a separately approved fresh unseen window?",
            "Do shorter lookbacks alter exposed quality through anchor-span coverage on fresh data?",
            "Is observed candidate support concentrated by fold on a fresh validation window?",
            "Does a separately approved quality-definition architecture study merit investigation?",
        ],
    }
    payload["study_identity"] = {**identity, "study_id": _study_id(payload)}
    return payload


def _markdown(payload: Mapping[str, Any]) -> str:
    sections = (
        ("Source And Bias Identity", payload["source_and_bias_identity"]),
        ("Canonical Exposure", payload["canonical_exposure"]),
        ("Existing Threshold Reconciliation", payload["existing_threshold_reconciliation"]),
        ("Minimum Sample Support Frontier", payload["minimum_sample_support_frontier"]),
        ("Observations", payload["observations"]),
        ("Research Hypotheses", payload["research_hypotheses"]),
    )
    chunks = [
        "# Trendline-Family Candidate Density Study v1\n",
        "> Exploratory post-diagnostic evidence only. No threshold/lookback selection, runtime use, promotion, or holdout access.\n",
    ]
    for heading, value in sections:
        chunks.append(f"## {heading}\n\n```json\n{json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True)}\n```\n")
    return "\n".join(chunks)


def _atomic_write_if_identical(path: Path, payload: bytes) -> Path:
    if path.exists():
        if path.read_bytes() != payload:
            raise CandidateDensityStudyError(f"refusing non-identical study overwrite: {path}")
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


def write_density_study_bundle(
    *,
    output_root: Path,
    source_binding: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> Mapping[str, Path]:
    source_bytes = canonical_json(source_binding).encode("utf-8") + b"\n"
    study_bytes = canonical_json(payload).encode("utf-8") + b"\n"
    markdown_bytes = _markdown(payload).encode("utf-8")
    identity = payload["study_identity"]
    manifest = {
        "study_schema_version": STUDY_SCHEMA_VERSION,
        "study_id": identity["study_id"],
        "study_source_binding_id": source_binding["study_source_binding_id"],
        "diagnosis_id": identity["diagnosis_id"],
        "diagnosis_source_binding_id": identity["diagnosis_source_binding_id"],
        "dataset_hash": payload["source_and_bias_identity"]["dataset_hash"],
        "resolved_config_hash": payload["source_and_bias_identity"]["resolved_config_hash"],
        "phase_i_run_id": payload["source_and_bias_identity"]["phase_i_run_id"],
        "report_id": payload["source_and_bias_identity"]["report_id"],
        "recommendation_id": payload["source_and_bias_identity"]["recommendation_id"],
        "source_binding_sha256": _sha256_bytes(source_bytes),
        "candidate_density_study_json_sha256": _sha256_bytes(study_bytes),
        "candidate_density_study_markdown_sha256": _sha256_bytes(markdown_bytes),
    }
    manifest_bytes = canonical_json(manifest).encode("utf-8") + b"\n"
    targets = {
        "source_binding": (output_root / "source_binding.json", source_bytes),
        "candidate_density_study": (output_root / "candidate_density_study.json", study_bytes),
        "candidate_density_markdown": (output_root / "candidate_density_study.md", markdown_bytes),
        "study_manifest": (output_root / "study_manifest.json", manifest_bytes),
    }
    for path, content in targets.values():
        if path.exists() and path.read_bytes() != content:
            raise CandidateDensityStudyError(f"refusing non-identical study overwrite: {path}")
    return {name: _atomic_write_if_identical(path, content) for name, (path, content) in sorted(targets.items())}


def validate_density_study_bundle(*, output_root: Path, diagnosis_root: Path = DIAGNOSIS_ROOT) -> Mapping[str, Any]:
    """Validate external study provenance, content IDs, and copied source claims."""

    source_path = output_root / "source_binding.json"
    study_path = output_root / "candidate_density_study.json"
    markdown_path = output_root / "candidate_density_study.md"
    manifest_path = output_root / "study_manifest.json"
    source_binding = _read_json(source_path, label="study source binding")
    study = _read_json(study_path, label="candidate density study")
    manifest = _read_json(manifest_path, label="study manifest")
    validated_binding = validate_study_source_binding_payload(source_binding)
    actual_binding = capture_study_source_binding(diagnosis_root=diagnosis_root)
    if canonical_json(validated_binding) != canonical_json(actual_binding):
        raise CandidateDensityStudyError("study source binding differs from approved diagnosis source bytes")
    identity = study.get("study_identity")
    source_identity = study.get("source_and_bias_identity")
    if not isinstance(identity, Mapping) or not isinstance(source_identity, Mapping):
        raise CandidateDensityStudyError("study identity sections are malformed")
    if identity.get("study_id") != _study_id(study):
        raise CandidateDensityStudyError("study content-addressed identity mismatch")
    if canonical_json(source_identity.get("source_binding")) != canonical_json(validated_binding):
        raise CandidateDensityStudyError("study embedded source binding differs from validated source binding")
    expected_identity = {
        "study_schema_version": STUDY_SCHEMA_VERSION,
        "study_source_binding_id": validated_binding["study_source_binding_id"],
        "diagnosis_id": EXPECTED_DIAGNOSIS_ID,
        "diagnosis_source_binding_id": EXPECTED_DIAGNOSIS_SOURCE_BINDING_ID,
    }
    if any(identity.get(key) != value for key, value in expected_identity.items()):
        raise CandidateDensityStudyError("study identity claim mismatch")
    if any(source_identity.get(key) != value for key, value in expected_identity.items()):
        raise CandidateDensityStudyError("study source identity claim mismatch")
    if source_identity.get("holdout_accessed") is not False or source_identity.get("planned_holdout_start_position") != PLANNED_HOLDOUT_START:
        raise CandidateDensityStudyError("study holdout boundary claim mismatch")
    expected_manifest = {
        **expected_identity,
        "study_id": identity["study_id"],
        "dataset_hash": EXPECTED_DATASET_HASH,
        "resolved_config_hash": EXPECTED_CONFIG_HASH,
        "phase_i_run_id": EXPECTED_PHASE_I_RUN_ID,
        "report_id": EXPECTED_REPORT_ID,
        "recommendation_id": EXPECTED_RECOMMENDATION_ID,
    }
    required_manifest_fields = set(expected_manifest) | {
        "source_binding_sha256",
        "candidate_density_study_json_sha256",
        "candidate_density_study_markdown_sha256",
    }
    if set(manifest) != required_manifest_fields:
        raise CandidateDensityStudyError("study manifest fields are invalid")
    if any(manifest.get(key) != value for key, value in expected_manifest.items()):
        raise CandidateDensityStudyError("study manifest identity mismatch")
    if _sha256_bytes(source_path.read_bytes()) != _require_sha256(manifest.get("source_binding_sha256"), field_name="study manifest source binding sha256"):
        raise CandidateDensityStudyError("study manifest source binding hash mismatch")
    if _sha256_bytes(study_path.read_bytes()) != _require_sha256(manifest.get("candidate_density_study_json_sha256"), field_name="study manifest JSON sha256"):
        raise CandidateDensityStudyError("study manifest JSON hash mismatch")
    markdown_bytes = markdown_path.read_bytes()
    if markdown_bytes != _markdown(study).encode("utf-8"):
        raise CandidateDensityStudyError("study Markdown content does not match study JSON")
    if _sha256_bytes(markdown_bytes) != _require_sha256(manifest.get("candidate_density_study_markdown_sha256"), field_name="study manifest Markdown sha256"):
        raise CandidateDensityStudyError("study manifest Markdown hash mismatch")
    return {"source_binding": validated_binding, "candidate_density_study": study, "study_manifest": manifest}


def build_candidate_density_study(
    *,
    diagnosis_root: Path = DIAGNOSIS_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> Mapping[str, Path]:
    """Build study from validated diagnosis records while preserving all protected bytes."""

    before = capture_protected_source_inventories()
    diagnosis_bundle = validate_diagnosis_bundle(output_root=diagnosis_root)
    source_binding = capture_study_source_binding(diagnosis_root=diagnosis_root)
    payload = build_density_study_payload(diagnosis_bundle=diagnosis_bundle, source_binding=source_binding)
    paths = write_density_study_bundle(output_root=output_root, source_binding=source_binding, payload=payload)
    validate_density_study_bundle(output_root=output_root, diagnosis_root=diagnosis_root)
    after = capture_protected_source_inventories()
    if canonical_json(before) != canonical_json(after):
        raise CandidateDensityStudyError("protected source bytes changed during density study")
    return paths


def main() -> None:
    paths = build_candidate_density_study()
    print(json.dumps({name: str(path) for name, path in sorted(paths.items())}, sort_keys=True))


if __name__ == "__main__":
    main()
