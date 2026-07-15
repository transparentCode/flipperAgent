"""Canonical, duplicate-safe publication and validation for V1.6 evidence."""

from __future__ import annotations

from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError, ZoneSide
from libs.models.sr.domain.identity import canonical_json, deterministic_hash

from .config import CalibrationConfig
from .metrics import CandidateMetrics, FirstTouchOutcome, WindowMetrics
from .selection import (
    CandidateDecision,
    DevelopmentDisposition,
    GateResult,
    HoldoutEvaluation,
    SelectionArtifact,
)


def _bytes(payload: Any) -> bytes:
    return canonical_json(payload).encode("utf-8") + b"\n"


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _assert_finite(value: Any, *, path: str = "json") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractValidationError(f"non-finite value at {path}")
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_finite(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_finite(item, path=f"{path}[{index}]")


def load_json(path: str | Path) -> Any:
    try:
        value = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ContractValidationError(f"invalid JSON artifact: {path}") from exc
    _assert_finite(value)
    return value


def _atomic_publish(path: Path, files: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_dir() or path.is_symlink():
            raise ContractValidationError("artifact output path is not a directory")
        if {item.name for item in path.iterdir()} != set(files):
            raise ContractValidationError("existing artifact has unexpected members")
        for name, data in files.items():
            if (path / name).read_bytes() != data:
                raise ContractValidationError("existing artifact bytes differ")
        return
    temporary = Path(tempfile.mkdtemp(prefix=f".{path.name}.", dir=path.parent))
    try:
        for name, data in files.items():
            (temporary / name).write_bytes(data)
        os.replace(temporary, path)
    except OSError as exc:
        raise ContractValidationError("atomic artifact publication failed") from exc
    finally:
        if temporary.exists():
            for item in temporary.iterdir():
                item.unlink()
            temporary.rmdir()


def _member_payload(name: str, data: bytes) -> dict[str, Any]:
    return {"name": name, "sha256": _sha(data), "byte_length": len(data)}


def _manifest(semantic: dict[str, Any], members: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    payload = {**semantic, "members": list(members)}
    return {
        **payload,
        "bundle_id": deterministic_hash(payload),
        "bundle_id_semantic_payload": payload,
    }


def _validate_bundle(path: Path, *, expected_stage: str, expected_context: dict[str, Any], expected_members: set[str]) -> dict[str, Any]:
    if not path.is_dir() or path.is_symlink():
        raise ContractValidationError("artifact bundle path is missing or symlinked")
    if {item.name for item in path.iterdir()} != expected_members:
        raise ContractValidationError("artifact bundle member set mismatch")
    manifest = load_json(path / "manifest.json")
    if type(manifest) is not dict:
        raise ContractValidationError("artifact manifest must be a mapping")
    semantic = manifest.get("bundle_id_semantic_payload")
    bundle_id = manifest.get("bundle_id")
    if type(semantic) is not dict or type(bundle_id) is not str or deterministic_hash(semantic) != bundle_id or path.name != bundle_id:
        raise ContractValidationError("artifact bundle identity mismatch")
    if manifest.get("stage") != expected_stage:
        raise ContractValidationError("artifact stage mismatch")
    expected_semantic_keys = (
        {"schema_version", "stage", "implementation_commit", "config_hash", "development_source_id", "selection_id", "members"}
        if expected_stage == "development"
        else {"schema_version", "stage", "implementation_commit", "config_hash", "selection_id", "development_bundle_id", "sealed_source_id", "recommendation", "members"}
    )
    expected_manifest_keys = expected_semantic_keys | {"bundle_id", "bundle_id_semantic_payload"}
    if set(semantic) != expected_semantic_keys or set(manifest) != expected_manifest_keys:
        raise ContractValidationError("artifact manifest schema mismatch")
    for key, value in expected_context.items():
        if semantic.get(key) != value or manifest.get(key) != value:
            raise ContractValidationError(f"artifact context mismatch: {key}")
    members = semantic.get("members")
    if type(members) is not list or len(members) != len(expected_members) - 1 or {item.get("name") for item in members if type(item) is dict} != expected_members - {"manifest.json"}:
        raise ContractValidationError("artifact manifest member metadata mismatch")
    for member in members:
        if type(member) is not dict or set(member) != {"name", "sha256", "byte_length"}:
            raise ContractValidationError("malformed artifact member metadata")
        name = member["name"]
        if name == "manifest.json" or type(name) is not str or "/" in name or "\\" in name or ".." in Path(name).parts:
            raise ContractValidationError("unsafe artifact member name")
        data = (path / name).read_bytes()
        if _sha(data) != member["sha256"] or len(data) != member["byte_length"]:
            raise ContractValidationError(f"artifact member hash mismatch: {name}")
    return manifest


def _parse_outcome(payload: Any) -> FirstTouchOutcome:
    if type(payload) is not dict:
        raise ContractValidationError("outcome must be a mapping")
    if set(payload) != {
        "zone_id", "side", "first_touch_at", "touch_bar_id", "anchor_close", "reference_atr_14",
        "completed", "right_censored", "tenth_outcome_bar_closed_at", "favorable_reference_atr",
        "adverse_reference_atr", "quality_reference_atr", "invalidated",
    }:
        raise ContractValidationError("outcome schema mismatch")
    from datetime import datetime

    def timestamp(value: Any):
        if value is None:
            return None
        if type(value) is not str or not value.endswith("Z"):
            raise ContractValidationError("artifact timestamp must use UTC Z notation")
        return datetime.fromisoformat(value[:-1] + "+00:00")

    return FirstTouchOutcome(
        zone_id=payload["zone_id"],
        side=ZoneSide(payload["side"]),
        first_touch_at=timestamp(payload["first_touch_at"]),
        touch_bar_id=payload["touch_bar_id"],
        anchor_close=payload["anchor_close"],
        reference_atr_14=payload["reference_atr_14"],
        completed=payload["completed"],
        right_censored=payload["right_censored"],
        tenth_outcome_bar_closed_at=timestamp(payload["tenth_outcome_bar_closed_at"]),
        favorable_reference_atr=payload["favorable_reference_atr"],
        adverse_reference_atr=payload["adverse_reference_atr"],
        quality_reference_atr=payload["quality_reference_atr"],
        invalidated=payload["invalidated"],
    )


def _parse_window(payload: Any) -> WindowMetrics:
    if type(payload) is not dict:
        raise ContractValidationError("window metric must be a mapping")
    if set(payload) != {
        "name", "start", "end", "total_first_touch_outcomes", "completed_first_touch_outcomes",
        "right_censored_first_touch_outcomes", "right_censoring_rate", "support_completed_count",
        "resistance_completed_count", "median_favorable_reference_atr", "median_adverse_reference_atr",
        "median_quality_reference_atr", "invalidated_completed_outcomes", "invalidation_rate",
        "created_zone_count", "eligible_model_bar_count", "zone_creation_density_per_100_bars",
        "cohort_terminal_count", "churn_rate", "outcomes",
    }:
        raise ContractValidationError("window metric schema mismatch")
    from datetime import datetime

    def timestamp(value: Any):
        if type(value) is not str or not value.endswith("Z"):
            raise ContractValidationError("window timestamp must use UTC Z notation")
        return datetime.fromisoformat(value[:-1] + "+00:00")

    return WindowMetrics(
        name=payload["name"], start=timestamp(payload["start"]), end=timestamp(payload["end"]),
        total_first_touch_outcomes=payload["total_first_touch_outcomes"], completed_first_touch_outcomes=payload["completed_first_touch_outcomes"], right_censored_first_touch_outcomes=payload["right_censored_first_touch_outcomes"], right_censoring_rate=payload["right_censoring_rate"], support_completed_count=payload["support_completed_count"], resistance_completed_count=payload["resistance_completed_count"], median_favorable_reference_atr=payload["median_favorable_reference_atr"], median_adverse_reference_atr=payload["median_adverse_reference_atr"], median_quality_reference_atr=payload["median_quality_reference_atr"], invalidated_completed_outcomes=payload["invalidated_completed_outcomes"], invalidation_rate=payload["invalidation_rate"], created_zone_count=payload["created_zone_count"], eligible_model_bar_count=payload["eligible_model_bar_count"], zone_creation_density_per_100_bars=payload["zone_creation_density_per_100_bars"], cohort_terminal_count=payload["cohort_terminal_count"], churn_rate=payload["churn_rate"], outcomes=tuple(_parse_outcome(item) for item in payload.get("outcomes", [])),
    )


def _parse_metrics(payload: Any) -> CandidateMetrics:
    if type(payload) is not dict:
        raise ContractValidationError("candidate metrics must be a mapping")
    if set(payload) != {"period", "folds", "pooled"}:
        raise ContractValidationError("candidate metrics schema mismatch")
    return CandidateMetrics(period=payload["period"], folds=tuple(_parse_window(item) for item in payload["folds"]), pooled=_parse_window(payload["pooled"]))


def _parse_gate(payload: Any) -> GateResult:
    if type(payload) is not dict:
        raise ContractValidationError("gate must be a mapping")
    if set(payload) != {"name", "passed", "value", "threshold", "reason"}:
        raise ContractValidationError("gate schema mismatch")
    return GateResult(name=payload["name"], passed=payload["passed"], value=payload["value"], threshold=payload["threshold"], reason=payload["reason"])


def _parse_decision(payload: Any) -> CandidateDecision:
    if type(payload) is not dict:
        raise ContractValidationError("decision must be a mapping")
    if set(payload) != {
        "period", "is_baseline", "eligible", "fully_evaluable", "gates", "eligible_fold_count",
        "fold_win_count", "fold_win_fraction", "median_eligible_fold_delta", "pooled_quality_delta",
        "median_absolute_deviation",
    }:
        raise ContractValidationError("decision schema mismatch")
    return CandidateDecision(period=payload["period"], is_baseline=payload["is_baseline"], eligible=payload["eligible"], fully_evaluable=payload["fully_evaluable"], gates=tuple(_parse_gate(item) for item in payload["gates"]), eligible_fold_count=payload["eligible_fold_count"], fold_win_count=payload["fold_win_count"], fold_win_fraction=payload["fold_win_fraction"], median_eligible_fold_delta=payload["median_eligible_fold_delta"], pooled_quality_delta=payload["pooled_quality_delta"], median_absolute_deviation=payload["median_absolute_deviation"])


def selection_from_payload(payload: Any) -> SelectionArtifact:
    if type(payload) is not dict:
        raise ContractValidationError("selection payload must be a mapping")
    expected_keys = {
        "schema_version",
        "implementation_commit",
        "config_hash",
        "development_source_id",
        "baseline_period",
        "candidate_periods",
        "candidate_metrics",
        "decisions",
        "selected_period",
        "disposition",
        "selection_id",
    }
    if set(payload) != expected_keys or payload.get("schema_version") != "1.0":
        raise ContractValidationError("selection payload schema mismatch")
    selection = SelectionArtifact(
        implementation_commit=payload["implementation_commit"],
        config_hash=payload["config_hash"],
        development_source_id=payload["development_source_id"],
        baseline_period=payload["baseline_period"],
        candidate_periods=tuple(payload["candidate_periods"]),
        candidate_metrics=tuple(_parse_metrics(item) for item in payload["candidate_metrics"]),
        decisions=tuple(_parse_decision(item) for item in payload["decisions"]),
        selected_period=payload["selected_period"],
        disposition=DevelopmentDisposition(payload["disposition"]),
    )
    if payload.get("selection_id") not in {None, selection.selection_id}:
        raise ContractValidationError("selection content ID mismatch")
    return selection


def publish_development(selection: SelectionArtifact, config: CalibrationConfig, *, implementation_commit: str, development_source_id: str, output_root: Path) -> tuple[str, Path]:
    if selection.implementation_commit != implementation_commit or selection.config_hash != config.config_hash or selection.development_source_id != development_source_id:
        raise ContractValidationError("selection identity does not match development publication")
    protocol = {"schema_version": "1.0", "stage": "development", "config": config.to_payload(), "config_hash": config.config_hash, "implementation_commit": implementation_commit, "development_source_id": development_source_id}
    metrics = {"schema_version": "1.0", "stage": "development", "candidate_metrics": [metric.to_payload() for metric in selection.candidate_metrics]}
    selection_payload = selection.to_payload()
    raw_files = {"protocol.json": _bytes(protocol), "development_metrics.json": _bytes(metrics), "selection.json": _bytes(selection_payload)}
    members = tuple(_member_payload(name, raw_files[name]) for name in sorted(raw_files))
    semantic = {"schema_version": "1.0", "stage": "development", "implementation_commit": implementation_commit, "config_hash": config.config_hash, "development_source_id": development_source_id, "selection_id": selection.selection_id}
    manifest = _manifest(semantic, members)
    manifest_bytes = _bytes(manifest)
    bundle_id = manifest["bundle_id"]
    path = output_root / "development" / bundle_id
    _atomic_publish(path, {"manifest.json": manifest_bytes, **raw_files})
    return bundle_id, path


def find_development_bundle(config: CalibrationConfig, *, output_root: Path, development_source_id: str, implementation_commit: str) -> tuple[SelectionArtifact, str, Path]:
    root = output_root / "development"
    if not root.is_dir():
        raise ContractValidationError("development selection artifact is missing")
    matches: list[tuple[SelectionArtifact, str, Path]] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if not path.is_dir() or path.is_symlink():
            continue
        manifest = _validate_bundle(path, expected_stage="development", expected_context={"implementation_commit": implementation_commit, "config_hash": config.config_hash, "development_source_id": development_source_id}, expected_members={"manifest.json", "protocol.json", "development_metrics.json", "selection.json"})
        selection = selection_from_payload(load_json(path / "selection.json"))
        if selection.selection_id != manifest.get("selection_id") or selection.implementation_commit != implementation_commit:
            raise ContractValidationError("development selection reference mismatch")
        protocol = load_json(path / "protocol.json")
        if type(protocol) is not dict or set(protocol) != {"schema_version", "stage", "config", "config_hash", "implementation_commit", "development_source_id"} or protocol["stage"] != "development" or protocol["config"] != config.to_payload() or protocol["config_hash"] != config.config_hash or protocol["implementation_commit"] != implementation_commit or protocol["development_source_id"] != development_source_id:
            raise ContractValidationError("development protocol member mismatch")
        metrics_payload = load_json(path / "development_metrics.json")
        expected_metrics = {"schema_version": "1.0", "stage": "development", "candidate_metrics": [metric.to_payload() for metric in selection.candidate_metrics]}
        if metrics_payload != expected_metrics:
            raise ContractValidationError("development metrics member mismatch")
        matches.append((selection, manifest["bundle_id"], path))
    if len(matches) != 1:
        raise ContractValidationError("expected exactly one matching development selection artifact")
    return matches[0]


def publish_holdout(selection: SelectionArtifact, evaluation: HoldoutEvaluation, config: CalibrationConfig, *, implementation_commit: str, sealed_source_id: str, development_bundle_id: str, output_root: Path) -> tuple[str, Path]:
    if selection.implementation_commit != implementation_commit or selection.config_hash != config.config_hash:
        raise ContractValidationError("holdout selection identity mismatch")
    reference = {"schema_version": "1.0", "stage": "holdout", "selection_id": selection.selection_id, "development_bundle_id": development_bundle_id, "sealed_source_id": sealed_source_id, "implementation_commit": implementation_commit, "config_hash": config.config_hash}
    metrics = {"schema_version": "1.0", "stage": "holdout", "selected_period": evaluation.selected_period, "baseline": None if evaluation.baseline_metrics is None else evaluation.baseline_metrics.to_payload(), "challenger": None if evaluation.challenger_metrics is None else evaluation.challenger_metrics.to_payload()}
    recommendation = {"schema_version": "1.0", "stage": "holdout", "selected_period": evaluation.selected_period, "recommendation": evaluation.recommendation.value, "gates": [gate.to_payload() for gate in evaluation.gates], "holdout_id": evaluation.holdout_id}
    raw_files = {"selection_reference.json": _bytes(reference), "holdout_metrics.json": _bytes(metrics), "recommendation.json": _bytes(recommendation)}
    members = tuple(_member_payload(name, raw_files[name]) for name in sorted(raw_files))
    semantic = {"schema_version": "1.0", "stage": "holdout", "implementation_commit": implementation_commit, "config_hash": config.config_hash, "selection_id": selection.selection_id, "development_bundle_id": development_bundle_id, "sealed_source_id": sealed_source_id, "recommendation": evaluation.recommendation.value}
    manifest = _manifest(semantic, members)
    manifest_bytes = _bytes(manifest)
    bundle_id = manifest["bundle_id"]
    path = output_root / "holdout" / bundle_id
    _atomic_publish(path, {"manifest.json": manifest_bytes, **raw_files})
    return bundle_id, path


__all__ = [
    "find_development_bundle",
    "load_json",
    "publish_development",
    "publish_holdout",
    "selection_from_payload",
]
