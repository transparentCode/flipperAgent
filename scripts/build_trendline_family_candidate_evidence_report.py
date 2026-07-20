"""Build immutable reviewer evidence from verified candidate Phase-I artifacts."""

# ruff: noqa: E402

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Mapping

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from libs.models.trendline.contracts import ContractValidationError
from libs.models.trendline.optimization.contracts import (
    OptimizationStage,
    PromotionDecision,
    TrialResult,
    canonical_json,
    primitive,
    semantic_id,
)
from libs.models.trendline.optimization.folds import ImmutableHistoricalFrame
from libs.models.trendline.research_lab.artifacts import (
    PhaseIArtifactBrowser,
    load_verified_phase_i_artifacts,
)


REPORT_SCHEMA_VERSION = "trendline_family_candidate_evidence_report_v1"
TRIAL_NAME = "btcusdt_4h_20250801_20251201_candidate_geometry_v2"
V1_TRIAL_NAME = "btcusdt_4h_20250801_20251201_candidate_geometry_v1"
TRIAL_ROOT_BASE = PROJECT_ROOT / "artifacts" / "trendline_family_candidate_trials"
V1_TRIAL_ROOT = TRIAL_ROOT_BASE / V1_TRIAL_NAME
V2_TRIAL_ROOT = TRIAL_ROOT_BASE / TRIAL_NAME
REPORT_ROOT = (
    PROJECT_ROOT
    / "artifacts"
    / "trendline_family_candidate_reports"
    / TRIAL_NAME
)

EXPECTED_INPUT_IDENTITY = {
    "asset": "BTCUSDT",
    "market": "Binance USD-M Futures",
    "timeframe": "4h",
    "start": "2025-08-01T00:00:00Z",
    "end": "2025-12-01T00:00:00Z",
    "row_count": 732,
    "first_timestamp": "2025-08-01T00:00:00Z",
    "last_timestamp": "2025-11-30T20:00:00Z",
    "dataset_hash": "trendline-family-dataset_ccaf20405ffc4b84ea98f79e97053e3ee6be4b0c571999dcbf5fc0e0bca1ad53",
    "normalized_input_sha256": "b8590c34400042fe8e38c23ac0d01b8d26916f2b0d5a6bed4f4b51d208d0a150",
    "resolved_config_hash": "da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f",
    "resolved_config_version": "1",
    "execution_attempt": 2,
    "authorization_id": "trendline_family_candidate_geometry_retry_v2",
}
EXPECTED_REQUEST = {
    "symbol": "BTCUSDT",
    "timeframe": "4h",
    "since": 1_754_006_400_000,
    "until": 1_764_547_200_000,
    "limit": 1000,
}
EXPECTED_RECOMMENDATION_ID = (
    "trendline-family-promotion-recommendation_"
    "fdcf8d4b39ffda53b3f09b26ff28bec40056677ce18cc90eb2292b310005ccbc"
)
EXPECTED_SOURCE_TRIAL_NAMES = {
    "v1": V1_TRIAL_NAME,
    "v2": TRIAL_NAME,
}
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class EvidenceReportError(ContractValidationError):
    """Source identity, report integrity, or immutable output failure."""


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _read_json(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise EvidenceReportError(f"required evidence file is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceReportError(f"invalid JSON evidence: {path}") from exc
    if not isinstance(value, Mapping):
        raise EvidenceReportError(f"JSON evidence must be a mapping: {path}")
    return value


def _iso(value: Any) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None or timestamp.utcoffset().total_seconds() != 0:
        raise EvidenceReportError("timestamp must be timezone-aware UTC")
    return timestamp.tz_convert("UTC").isoformat().replace("+00:00", "Z")


def source_inventory(root: Path, *, source_name: str) -> Mapping[str, Any]:
    if not root.is_dir():
        raise EvidenceReportError(f"source trial root is missing: {root}")
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
        raise EvidenceReportError(f"source trial root has no files: {root}")
    semantic = {"source_name": source_name, "trial_name": root.name, "files": files}
    return {
        **semantic,
        "inventory_sha256": _sha256_bytes(canonical_json(semantic).encode("utf-8")),
    }


def capture_source_inventories(*, v1_root: Path, v2_root: Path) -> Mapping[str, Any]:
    inventories = {
        "v1": source_inventory(v1_root, source_name="v1"),
        "v2": source_inventory(v2_root, source_name="v2"),
    }
    semantic = {"report_schema_version": REPORT_SCHEMA_VERSION, "sources": inventories}
    return {
        **semantic,
        "source_inventory_id": semantic_id("trendline-family-candidate-source-inventory", semantic),
    }


def _require_sha256(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise EvidenceReportError(f"{field_name} must be a lowercase 64-character SHA-256")
    return value


def _validate_inventory_relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise EvidenceReportError("source inventory relative_path must be a non-empty string")
    if value.startswith("/") or "\\" in value:
        raise EvidenceReportError("source inventory relative_path must be canonical POSIX relative path")
    segments = value.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise EvidenceReportError("source inventory relative_path contains unsafe path segment")
    return value


def validate_source_inventory_payload(source: Mapping[str, Any]) -> Mapping[str, str]:
    """Validate and rederive external source-inventory semantic bindings."""

    expected_top_level = {"report_schema_version", "sources", "source_inventory_id"}
    if set(source) != expected_top_level:
        raise EvidenceReportError("source inventory top-level fields are invalid")
    if source.get("report_schema_version") != REPORT_SCHEMA_VERSION:
        raise EvidenceReportError("source inventory schema version mismatch")
    raw_sources = source.get("sources")
    if not isinstance(raw_sources, Mapping) or set(raw_sources) != set(EXPECTED_SOURCE_TRIAL_NAMES):
        raise EvidenceReportError("source inventory sources must contain exactly v1 and v2")

    validated_sources: dict[str, Mapping[str, Any]] = {}
    derived_hashes: dict[str, str] = {}
    for source_key in ("v1", "v2"):
        raw_entry = raw_sources[source_key]
        if not isinstance(raw_entry, Mapping):
            raise EvidenceReportError(f"source inventory {source_key} entry must be a mapping")
        expected_entry_fields = {"source_name", "trial_name", "files", "inventory_sha256"}
        if set(raw_entry) != expected_entry_fields:
            raise EvidenceReportError(f"source inventory {source_key} fields are invalid")
        source_name = raw_entry.get("source_name")
        trial_name = raw_entry.get("trial_name")
        if source_name != source_key:
            raise EvidenceReportError(f"source inventory {source_key} source_name mismatch")
        if trial_name != EXPECTED_SOURCE_TRIAL_NAMES[source_key]:
            raise EvidenceReportError(f"source inventory {source_key} trial_name mismatch")

        raw_files = raw_entry.get("files")
        if not isinstance(raw_files, (list, tuple)) or not raw_files:
            raise EvidenceReportError(f"source inventory {source_key} files must be a non-empty sequence")
        canonical_files: list[Mapping[str, Any]] = []
        paths: list[str] = []
        for index, raw_file in enumerate(raw_files):
            if not isinstance(raw_file, Mapping) or set(raw_file) != {"relative_path", "size_bytes", "sha256"}:
                raise EvidenceReportError(f"source inventory {source_key} file record {index} fields are invalid")
            relative_path = _validate_inventory_relative_path(raw_file.get("relative_path"))
            size_bytes = raw_file.get("size_bytes")
            if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
                raise EvidenceReportError(f"source inventory {source_key} file record {index} size_bytes is invalid")
            file_sha256 = _require_sha256(
                raw_file.get("sha256"),
                field_name=f"source inventory {source_key} file record {index} sha256",
            )
            paths.append(relative_path)
            canonical_files.append(
                {
                    "relative_path": relative_path,
                    "size_bytes": size_bytes,
                    "sha256": file_sha256,
                }
            )
        if len(set(paths)) != len(paths):
            raise EvidenceReportError(f"source inventory {source_key} file paths must be unique")
        if paths != sorted(paths):
            raise EvidenceReportError(f"source inventory {source_key} file paths must be strictly sorted")

        semantic = {
            "source_name": source_name,
            "trial_name": trial_name,
            "files": tuple(canonical_files),
        }
        derived_hash = _sha256_bytes(canonical_json(semantic).encode("utf-8"))
        persisted_hash = _require_sha256(
            raw_entry.get("inventory_sha256"),
            field_name=f"source inventory {source_key} inventory_sha256",
        )
        if persisted_hash != derived_hash:
            raise EvidenceReportError(f"source inventory {source_key} inventory_sha256 mismatch")
        validated_sources[source_key] = {
            **semantic,
            "inventory_sha256": derived_hash,
        }
        derived_hashes[source_key] = derived_hash

    semantic_inventory = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "sources": validated_sources,
    }
    derived_inventory_id = semantic_id("trendline-family-candidate-source-inventory", semantic_inventory)
    if source.get("source_inventory_id") != derived_inventory_id:
        raise EvidenceReportError("source inventory ID mismatch")
    return derived_hashes


def _require_mapping_value(mapping: Mapping[str, Any], key: str, expected: Any) -> None:
    if mapping.get(key) != expected:
        raise EvidenceReportError(f"source identity mismatch for {key}")


def _load_normalized_frame(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise EvidenceReportError("normalized input CSV is missing")
    try:
        # The trial writer persisted IEEE-754 values with 17 significant digits.
        # Round-trip parsing is required to rebuild its audited dataset hash.
        raw = pd.read_csv(path, float_precision="round_trip")
    except (OSError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise EvidenceReportError("normalized input CSV is unreadable") from exc
    if "timestamp" not in raw.columns:
        raise EvidenceReportError("normalized input CSV lacks timestamp")
    try:
        timestamps = pd.to_datetime(raw.pop("timestamp"), errors="raise")
    except (TypeError, ValueError) as exc:
        raise EvidenceReportError("normalized input contains invalid timestamps") from exc
    index = pd.DatetimeIndex(timestamps)
    if index.tz is None or str(index.tz) not in {"UTC", "UTC+00:00"}:
        raise EvidenceReportError("normalized input timestamps must be timezone-aware UTC")
    raw.index = index
    for column in ("open", "high", "low", "close", "volume"):
        if column not in raw.columns:
            raise EvidenceReportError(f"normalized input lacks {column}")
        converted = pd.to_numeric(raw[column], errors="coerce")
        if converted.isna().any() or not converted.map(math.isfinite).all():
            raise EvidenceReportError(f"normalized input {column} must be finite numeric")
        raw[column] = converted.astype(float)
    if "complete" not in raw.columns:
        raise EvidenceReportError("normalized input lacks complete flag")
    complete = raw["complete"]
    if complete.dtype != bool:
        converted_complete = complete.map({"True": True, "False": False, True: True, False: False})
        if converted_complete.isna().any():
            raise EvidenceReportError("normalized input complete flag must be boolean")
        complete = converted_complete.astype(bool)
    raw["complete"] = complete
    return raw


def verify_input_evidence(*, v2_root: Path) -> tuple[Mapping[str, Any], Mapping[str, Any], ImmutableHistoricalFrame]:
    input_root = v2_root / "input"
    scope = _read_json(v2_root / "execution_scope.json")
    manifest_path = input_root / "input_manifest.json"
    manifest = _read_json(manifest_path)
    raw_manifest = _read_json(input_root / "raw_fetch_manifest.json")
    for key, expected in EXPECTED_INPUT_IDENTITY.items():
        if key in {"execution_attempt", "authorization_id"}:
            _require_mapping_value(scope, key, expected)
        else:
            _require_mapping_value(manifest, key, expected)
    _require_mapping_value(manifest, "request", EXPECTED_REQUEST)
    _require_mapping_value(raw_manifest, "request", EXPECTED_REQUEST)
    normalized_path = input_root / str(manifest.get("normalized_input_file", ""))
    normalized_bytes = normalized_path.read_bytes() if normalized_path.is_file() else b""
    if _sha256_bytes(normalized_bytes) != manifest.get("normalized_input_sha256"):
        raise EvidenceReportError("normalized input SHA-256 does not match manifest")
    raw_path = input_root / str(raw_manifest.get("raw_response_file", ""))
    raw_bytes = raw_path.read_bytes() if raw_path.is_file() else b""
    if _sha256_bytes(raw_bytes) != raw_manifest.get("raw_response_sha256"):
        raise EvidenceReportError("raw response SHA-256 does not match manifest")
    frame = _load_normalized_frame(normalized_path)
    if len(frame) != EXPECTED_INPUT_IDENTITY["row_count"]:
        raise EvidenceReportError("normalized input row count does not match fixed evidence")
    if _iso(frame.index[0]) != EXPECTED_INPUT_IDENTITY["first_timestamp"] or _iso(frame.index[-1]) != EXPECTED_INPUT_IDENTITY["last_timestamp"]:
        raise EvidenceReportError("normalized input timestamp boundary mismatch")
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise EvidenceReportError("normalized input timestamps must be strictly ordered and unique")
    if not (frame.index.to_series().diff().dropna() == pd.Timedelta(hours=4)).all():
        raise EvidenceReportError("normalized input contains non-four-hour gaps")
    if (frame[["open", "high", "low", "close"]] <= 0.0).any().any() or (frame["volume"] < 0.0).any():
        raise EvidenceReportError("normalized input violates OHLCV positivity")
    if (frame["high"] < frame[["open", "close"]].max(axis=1)).any() or (
        frame["low"] > frame[["open", "close"]].min(axis=1)
    ).any():
        raise EvidenceReportError("normalized input violates OHLC envelopes")
    if not frame["complete"].eq(True).all():
        raise EvidenceReportError("normalized input contains incomplete bars")
    try:
        dataset = ImmutableHistoricalFrame(
            asset=str(manifest["asset"]),
            timeframe=str(manifest["timeframe"]),
            _frame=frame,
        )
    except ContractValidationError as exc:
        raise EvidenceReportError(f"immutable historical frame rejected normalized input: {exc}") from exc
    if dataset.dataset_hash != manifest.get("dataset_hash"):
        raise EvidenceReportError("rebuilt dataset hash does not match input manifest")
    input_evidence = {
        "input_manifest": dict(manifest),
        "input_manifest_sha256": _sha256_bytes(manifest_path.read_bytes()),
        "raw_fetch_manifest": dict(raw_manifest),
        "raw_fetch_manifest_sha256": _sha256_bytes((input_root / "raw_fetch_manifest.json").read_bytes()),
        "normalized_input_sha256": _sha256_bytes(normalized_bytes),
        "raw_response_sha256": _sha256_bytes(raw_bytes),
        "raw_row_count": raw_manifest.get("raw_row_count"),
        "gap_and_completeness_audit": {
            "strictly_increasing_unique_timestamps": True,
            "spacing": "4h",
            "all_complete": True,
            "ohlcv_envelopes_valid": True,
        },
    }
    return input_evidence, scope, dataset


def verify_phase_i_evidence(
    *,
    v2_root: Path,
    dataset: ImmutableHistoricalFrame,
) -> PhaseIArtifactBrowser:
    try:
        browser = load_verified_phase_i_artifacts(v2_root / "phase_i")
    except ContractValidationError as exc:
        raise EvidenceReportError(f"Phase-I artifact verification failed: {exc}") from exc
    bundle = browser.bundle
    manifest = browser.manifest
    scope = f"{dataset.asset}:{dataset.timeframe}"
    if manifest.run_id != bundle.completion_index.run_id:
        raise EvidenceReportError("Phase-I run identity does not match completion index")
    if manifest.requested_stages != (OptimizationStage.CANDIDATE_GEOMETRY,):
        raise EvidenceReportError("Phase-I bundle does not contain only candidate geometry stage")
    if manifest.dataset_hashes.get(scope) != dataset.dataset_hash or bundle.fold_plan.data_hash != dataset.dataset_hash:
        raise EvidenceReportError("Phase-I dataset identity does not match normalized input")
    if manifest.baseline_config_hashes.get(scope) != EXPECTED_INPUT_IDENTITY["resolved_config_hash"]:
        raise EvidenceReportError("Phase-I config identity does not match input evidence")
    recommendation = browser.recommendation
    if bundle.finalist_freeze is not None or recommendation.finalist_result_id is not None:
        raise EvidenceReportError("verified source bundle unexpectedly declares a finalist")
    if bundle.baseline_holdout is not None or bundle.finalist_holdout is not None or bundle.holdout_open_audits:
        raise EvidenceReportError("verified source bundle unexpectedly declares holdout evidence")
    if recommendation.decision is not PromotionDecision.REJECT:
        raise EvidenceReportError("verified recommendation decision is not REJECT")
    if recommendation.rationale != ("no_validation_trial_passed_stage_owned_gates",):
        raise EvidenceReportError("verified recommendation rationale mismatch")
    if recommendation.recommendation_id != EXPECTED_RECOMMENDATION_ID:
        raise EvidenceReportError("verified recommendation identity mismatch")
    primary_ids = tuple(sorted(trial.trial.trial_id for trial in browser.trials))
    if len(primary_ids) != 6 or primary_ids != manifest.expected_primary_trial_ids:
        raise EvidenceReportError("verified primary trial membership mismatch")
    if any(trial.trial.trial_kind != "primary" for trial in browser.trials):
        raise EvidenceReportError("verified primary evidence includes non-primary trial")
    return browser


def _metric_payload(result: TrialResult) -> Mapping[str, Any]:
    aggregate = {name: metric.to_dict() for name, metric in sorted(result.aggregate_metrics.items())}
    provider_statuses: Counter[str] = Counter()
    excluded: Counter[str] = Counter()
    for window in result.window_results:
        statuses = window.diagnostics.get("provider_status_counts", {})
        if isinstance(statuses, Mapping):
            for name, count in statuses.items():
                if isinstance(name, str) and isinstance(count, int) and not isinstance(count, bool):
                    provider_statuses[name] += count
        excluded.update(window.excluded_reasons)
    candidate_names = (
        "candidate_count",
        "candidate_coverage_ratio",
        "candidates_per_bar",
        "provider_failure_rate",
        "support_balance",
        "resistance_balance",
    )
    outcome_names = (
        "exact_line_future_touch_rate",
        "geometry_survival_rate",
        "reaction_quality",
        "normalized_penetration",
    )
    return {
        "trial": result.trial.to_dict(),
        "result_id": result.result_id,
        "status": result.status.value,
        "failure_code": None if result.failure_code is None else result.failure_code.value,
        "failure_reason": result.failure_reason,
        "per_fold": [window.to_dict() for window in result.window_results],
        "aggregate_metrics": aggregate,
        "worst_window_metrics": {
            name: value for name, value in aggregate.items() if name.endswith("__worst")
        },
        "objective_gate": None if result.objective_gate is None else result.objective_gate.to_dict(),
        "provider_status_counts": dict(sorted(provider_statuses.items())),
        "candidate_density_and_balance": {
            name: aggregate.get(name) for name in candidate_names
        },
        "touch_survival_reaction_penetration": {
            name: aggregate.get(name) for name in outcome_names
        },
        "excluded_outcome_counts": dict(sorted(excluded.items())),
        "evaluated_rows": sum(window.evaluated_bar_count for window in result.window_results),
        "runtime_diagnostics": primitive(result.runtime_diagnostics),
        "parameter_effect_audits": [audit.to_dict() for audit in result.parameter_effect_audits],
        "counterfactual_result_ids": [
            counterfactual.result_id for counterfactual in result.counterfactual_results
        ],
    }


def _counterfactual_payload(result: TrialResult) -> Mapping[str, Any]:
    evidence = dict(_metric_payload(result))
    evidence.pop("counterfactual_result_ids", None)
    evidence.pop("parameter_effect_audits", None)
    return evidence


def _markdown_report(payload: Mapping[str, Any]) -> str:
    sections = (
        ("Report Identity", payload["report_identity"]),
        ("Dataset And Request Provenance", payload["dataset_and_request_provenance"]),
        ("Configuration Identity", payload["configuration_identity"]),
        ("Outcome Policy Identity", payload["outcome_policy_identity"]),
        ("Fold And Holdout Plan", payload["fold_and_holdout_plan"]),
        ("Search Request Set", payload["search_request_set"]),
        ("Objective Identity", payload["objective_identity"]),
        ("Baseline Validation Evidence", payload["baseline_validation_evidence"]),
        ("Primary Trial Evidence", payload["primary_trial_evidence"]),
        ("Counterfactual And Parameter Effect Evidence", payload["counterfactual_and_parameter_effect_evidence"]),
        ("Finalist And Holdout Evidence", payload["finalist_and_holdout_evidence"]),
        ("Recommendation", payload["recommendation"]),
        ("Bounded Reviewer Interpretation", payload["bounded_reviewer_interpretation"]),
    )
    chunks = ["# Trendline-Family Candidate Evidence Report v1\n"]
    for heading, section in sections:
        chunks.append(f"## {heading}\n")
        chunks.append("```json\n")
        chunks.append(json.dumps(section, indent=2, sort_keys=True, ensure_ascii=True))
        chunks.append("\n```\n")
    return "\n".join(chunks)


def _report_id_from_evidence(evidence: Mapping[str, Any]) -> str:
    """Reconstruct the content-addressed identity from the published payload."""

    identity = evidence.get("report_identity")
    if not isinstance(identity, Mapping):
        raise EvidenceReportError("evidence report identity must be a mapping")
    required_sections = (
        "dataset_and_request_provenance",
        "configuration_identity",
        "outcome_policy_identity",
        "fold_and_holdout_plan",
        "search_request_set",
        "objective_identity",
        "baseline_validation_evidence",
        "primary_trial_evidence",
        "counterfactual_and_parameter_effect_evidence",
        "finalist_and_holdout_evidence",
        "recommendation",
        "bounded_reviewer_interpretation",
    )
    if any(section not in evidence for section in required_sections):
        raise EvidenceReportError("evidence report is missing a required semantic section")
    semantic_payload = {
        "report_schema_version": identity.get("report_schema_version"),
        "source_trial_name": identity.get("source_trial_name"),
        "source_execution_attempt": identity.get("source_execution_attempt"),
        "source_dataset_hash": identity.get("source_dataset_hash"),
        "phase_i_run_id": identity.get("phase_i_run_id"),
        "recommendation_id": identity.get("recommendation_id"),
        "source_inventory_hashes": identity.get("source_inventory_hashes"),
        "verified_source_artifact_hashes": identity.get("verified_source_artifact_hashes"),
        **{section: evidence[section] for section in required_sections},
    }
    return semantic_id("trendline-family-candidate-evidence-report", semantic_payload)


def build_evidence_payload(
    *,
    source_inventories: Mapping[str, Any],
    input_evidence: Mapping[str, Any],
    execution_scope: Mapping[str, Any],
    dataset: ImmutableHistoricalFrame,
    browser: PhaseIArtifactBrowser,
) -> Mapping[str, Any]:
    bundle = browser.bundle
    manifest = browser.manifest
    stage = OptimizationStage.CANDIDATE_GEOMETRY.value
    sorted_trials = tuple(
        sorted(
            browser.trials,
            key=lambda trial: (
                canonical_json(trial.trial.parameter_overrides),
                trial.trial.trial_id,
            ),
        )
    )
    actual_primary_ids = tuple(trial.trial.trial_id for trial in sorted_trials)
    expected_primary_ids = manifest.expected_primary_trial_ids
    if tuple(sorted(actual_primary_ids)) != expected_primary_ids:
        raise EvidenceReportError("primary trial IDs do not match verified request set")
    counterfactuals = tuple(
        counterfactual
        for trial in sorted_trials
        for counterfactual in trial.counterfactual_results
    )
    audits = tuple(
        {
            "primary_trial_id": trial.trial.trial_id,
            "primary_result_id": trial.result_id,
            "audit": audit.to_dict(),
        }
        for trial in sorted_trials
        for audit in trial.parameter_effect_audits
    )
    scope = f"{dataset.asset}:{dataset.timeframe}"
    semantic_payload = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "source_trial_name": TRIAL_NAME,
        "source_execution_attempt": execution_scope["execution_attempt"],
        "source_dataset_hash": dataset.dataset_hash,
        "phase_i_run_id": manifest.run_id,
        "recommendation_id": browser.recommendation.recommendation_id,
        "source_inventory_hashes": {
            name: inventory["inventory_sha256"]
            for name, inventory in source_inventories["sources"].items()
        },
        "verified_source_artifact_hashes": dict(browser.verification_artifact_hashes),
        "dataset_and_request_provenance": input_evidence,
        "configuration_identity": {
            "config_version": manifest.config_version,
            "model_version": manifest.model_version,
            "resolved_config_hash": manifest.baseline_config_hashes[scope],
            "baseline_candidate_parameter_values": primitive(
                manifest.stage_baseline_parameter_values[stage]
            ),
            "yaml_changed": False,
        },
        "outcome_policy_identity": primitive(
            manifest.stage_evaluation_specs[stage].semantic_inputs["outcome_policy"]
        ),
        "fold_and_holdout_plan": {
            "fold_plan": bundle.fold_plan.to_dict(),
            "planned_holdout": bundle.fold_plan.holdout.to_dict(),
            "verified_holdout_status": {
                "validation_finalist": None,
                "finalist_freeze": "absent",
                "holdout_open_audits": "absent",
                "baseline_holdout_result": "absent",
                "finalist_holdout_result": "absent",
            },
        },
        "search_request_set": {
            "search_space": primitive(manifest.search_spaces[stage]),
            "maximum_trial_count": manifest.maximum_trial_count,
            "seed": manifest.seeds[stage],
            "expected_primary_trial_ids": expected_primary_ids,
            "actual_verified_primary_trial_ids": actual_primary_ids,
            "completion_status": manifest.completion_status,
            "missing_primary_trial_ids": [],
            "extra_primary_trial_ids": [],
        },
        "objective_identity": manifest.objective_specs[stage].to_dict(),
        "baseline_validation_evidence": _metric_payload(bundle.baseline_validation),
        "primary_trial_evidence": [_metric_payload(trial) for trial in sorted_trials],
        "counterfactual_and_parameter_effect_evidence": {
            "counterfactual_results": [_counterfactual_payload(item) for item in counterfactuals],
            "parameter_effect_audits": audits,
        },
        "finalist_and_holdout_evidence": {
            "validation_finalist": None,
            "finalist_freeze": "absent",
            "holdout_open_audits": "absent",
            "baseline_holdout_result": "absent",
            "finalist_holdout_result": "absent",
        },
        "recommendation": browser.recommendation.to_dict(),
        "bounded_reviewer_interpretation": {
            "verified_bundle": True,
            "observation": "No validation trial passed stage-owned objective gates.",
            "finalist_and_holdout_absent": True,
            "promotion_or_runtime_action_supported": False,
            "pnl_or_live_trading_utility_established": False,
            "next_step": "Separate research planning decision required before any new evaluation.",
        },
    }
    evidence_payload = {
        "report_identity": {
            "report_schema_version": semantic_payload["report_schema_version"],
            "report_id": "pending",
            "source_trial_name": TRIAL_NAME,
            "source_execution_attempt": execution_scope["execution_attempt"],
            "source_dataset_hash": dataset.dataset_hash,
            "phase_i_run_id": manifest.run_id,
            "recommendation_id": browser.recommendation.recommendation_id,
            "source_inventory_hashes": semantic_payload["source_inventory_hashes"],
            "verified_source_artifact_hashes": semantic_payload["verified_source_artifact_hashes"],
        },
        "dataset_and_request_provenance": semantic_payload["dataset_and_request_provenance"],
        "configuration_identity": semantic_payload["configuration_identity"],
        "outcome_policy_identity": semantic_payload["outcome_policy_identity"],
        "fold_and_holdout_plan": semantic_payload["fold_and_holdout_plan"],
        "search_request_set": semantic_payload["search_request_set"],
        "objective_identity": semantic_payload["objective_identity"],
        "baseline_validation_evidence": semantic_payload["baseline_validation_evidence"],
        "primary_trial_evidence": semantic_payload["primary_trial_evidence"],
        "counterfactual_and_parameter_effect_evidence": semantic_payload[
            "counterfactual_and_parameter_effect_evidence"
        ],
        "finalist_and_holdout_evidence": semantic_payload["finalist_and_holdout_evidence"],
        "recommendation": semantic_payload["recommendation"],
        "bounded_reviewer_interpretation": semantic_payload["bounded_reviewer_interpretation"],
    }
    report_id = _report_id_from_evidence(evidence_payload)
    return {
        **evidence_payload,
        "report_identity": {
            **evidence_payload["report_identity"],
            "report_id": report_id,
        },
    }


def _atomic_write_if_identical(path: Path, payload: bytes) -> Path:
    if path.exists():
        if path.read_bytes() != payload:
            raise EvidenceReportError(f"refusing non-identical report overwrite: {path}")
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


def write_report_bundle(
    *,
    output_root: Path,
    source_inventories: Mapping[str, Any],
    evidence_payload: Mapping[str, Any],
) -> Mapping[str, Path]:
    source_bytes = canonical_json(source_inventories).encode("utf-8") + b"\n"
    evidence_bytes = canonical_json(evidence_payload).encode("utf-8") + b"\n"
    markdown_bytes = _markdown_report(evidence_payload).encode("utf-8")
    report_identity = evidence_payload["report_identity"]
    manifest = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "report_id": report_identity["report_id"],
        "source_trial_name": report_identity["source_trial_name"],
        "source_execution_attempt": report_identity["source_execution_attempt"],
        "source_inventory_hashes": report_identity["source_inventory_hashes"],
        "source_inventory_sha256": _sha256_bytes(source_bytes),
        "normalized_input_sha256": evidence_payload["dataset_and_request_provenance"]["normalized_input_sha256"],
        "dataset_hash": report_identity["source_dataset_hash"],
        "phase_i_run_id": report_identity["phase_i_run_id"],
        "verified_source_artifact_hashes": report_identity["verified_source_artifact_hashes"],
        "recommendation_id": report_identity["recommendation_id"],
        "evidence_report_json_sha256": _sha256_bytes(evidence_bytes),
        "evidence_report_markdown_sha256": _sha256_bytes(markdown_bytes),
    }
    manifest_bytes = canonical_json(manifest).encode("utf-8") + b"\n"
    payloads = {
        "source_inventory": (output_root / "source_inventory.json", source_bytes),
        "evidence_report": (output_root / "evidence_report.json", evidence_bytes),
        "evidence_markdown": (output_root / "evidence_report.md", markdown_bytes),
        "report_manifest": (output_root / "report_manifest.json", manifest_bytes),
    }
    # Check the whole immutable bundle before creating any individual file.
    for path, payload in payloads.values():
        if path.exists() and path.read_bytes() != payload:
            raise EvidenceReportError(f"refusing non-identical report overwrite: {path}")
    paths = {
        name: _atomic_write_if_identical(path, payload)
        for name, (path, payload) in payloads.items()
    }
    return dict(sorted(paths.items()))


def validate_report_bundle(*, output_root: Path) -> Mapping[str, Any]:
    source_path = output_root / "source_inventory.json"
    evidence_path = output_root / "evidence_report.json"
    markdown_path = output_root / "evidence_report.md"
    manifest_path = output_root / "report_manifest.json"
    source = _read_json(source_path)
    evidence = _read_json(evidence_path)
    manifest = _read_json(manifest_path)
    if manifest.get("report_schema_version") != REPORT_SCHEMA_VERSION:
        raise EvidenceReportError("report manifest schema version mismatch")
    identity = evidence.get("report_identity")
    if not isinstance(identity, Mapping) or identity.get("report_id") != manifest.get("report_id"):
        raise EvidenceReportError("report manifest identity binding mismatch")
    if identity.get("report_id") != _report_id_from_evidence(evidence):
        raise EvidenceReportError("evidence report content-addressed identity mismatch")
    if _sha256_bytes(source_path.read_bytes()) != manifest.get("source_inventory_sha256"):
        raise EvidenceReportError("report manifest source inventory hash mismatch")
    if _sha256_bytes(evidence_path.read_bytes()) != manifest.get("evidence_report_json_sha256"):
        raise EvidenceReportError("report manifest JSON hash mismatch")
    if _sha256_bytes(markdown_path.read_bytes()) != manifest.get("evidence_report_markdown_sha256"):
        raise EvidenceReportError("report manifest Markdown hash mismatch")
    derived_source_hashes = validate_source_inventory_payload(source)
    if derived_source_hashes != identity.get("source_inventory_hashes"):
        raise EvidenceReportError("validated source inventories do not match evidence report")
    if derived_source_hashes != manifest.get("source_inventory_hashes"):
        raise EvidenceReportError("validated source inventories do not match report manifest")
    if identity.get("source_inventory_hashes") != manifest.get("source_inventory_hashes"):
        raise EvidenceReportError("report manifest source root binding mismatch")
    if identity.get("recommendation_id") != manifest.get("recommendation_id"):
        raise EvidenceReportError("report manifest recommendation binding mismatch")
    if identity.get("source_dataset_hash") != manifest.get("dataset_hash"):
        raise EvidenceReportError("report manifest dataset binding mismatch")
    if identity.get("phase_i_run_id") != manifest.get("phase_i_run_id"):
        raise EvidenceReportError("report manifest Phase-I run binding mismatch")
    if identity.get("verified_source_artifact_hashes") != manifest.get("verified_source_artifact_hashes"):
        raise EvidenceReportError("report manifest verified artifact binding mismatch")
    if evidence.get("dataset_and_request_provenance", {}).get("normalized_input_sha256") != manifest.get(
        "normalized_input_sha256"
    ):
        raise EvidenceReportError("report manifest normalized input binding mismatch")
    return {"source_inventory": source, "evidence_report": evidence, "report_manifest": manifest}


def build_candidate_evidence_report(
    *,
    v1_root: Path = V1_TRIAL_ROOT,
    v2_root: Path = V2_TRIAL_ROOT,
    output_root: Path = REPORT_ROOT,
) -> Mapping[str, Path]:
    """Verify immutable evidence, build canonical payload, write external report only."""

    before = capture_source_inventories(v1_root=v1_root, v2_root=v2_root)
    input_evidence, scope, dataset = verify_input_evidence(v2_root=v2_root)
    browser = verify_phase_i_evidence(v2_root=v2_root, dataset=dataset)
    payload = build_evidence_payload(
        source_inventories=before,
        input_evidence=input_evidence,
        execution_scope=scope,
        dataset=dataset,
        browser=browser,
    )
    paths = write_report_bundle(
        output_root=output_root,
        source_inventories=before,
        evidence_payload=payload,
    )
    validate_report_bundle(output_root=output_root)
    after = capture_source_inventories(v1_root=v1_root, v2_root=v2_root)
    if canonical_json(before) != canonical_json(after):
        raise EvidenceReportError("source trial roots changed during report generation")
    return paths


def main() -> None:
    paths = build_candidate_evidence_report()
    print(json.dumps({name: str(path) for name, path in paths.items()}, sort_keys=True))


if __name__ == "__main__":
    main()
