"""Canonical immutable V2.3 source/evaluation bundles and validators."""

from __future__ import annotations

from hashlib import sha256
import math
import json
from pathlib import Path
import os
import stat
import tempfile
from typing import Any

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.domain.identity import canonical_json, deterministic_hash
from libs.models.sr.research.artifacts.path_safety import reject_symlink_components
from libs.models.sr.research.source.contracts import SourceBar

from .config import AdaptiveContextCalibrationConfig
from .contracts import (
    CANONICAL_COHORTS,
    IntervalBar,
    V23SourceBundle,
    V23SourceMember,
)


def canonical_json_bytes(payload: Any) -> bytes:
    return (canonical_json(payload) + "\n").encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return sha256(data).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: Any, *, path: str = "json") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractValidationError(f"non-finite artifact value at {path}")
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_nonfinite(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_nonfinite(item, path=f"{path}[{index}]")


def load_json(path: str | Path) -> Any:
    try:
        payload = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ContractValidationError(f"invalid JSON artifact: {path}") from exc
    _reject_nonfinite(payload)
    return payload


def _member(name: str, data: bytes) -> dict[str, Any]:
    return {"name": name, "sha256": sha256_hex(data), "byte_length": len(data)}


def _ensure_safe_dir(path: Path, *, description: str) -> None:
    reject_symlink_components(path, description=description)
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ContractValidationError(f"{description} cannot be inspected") from exc
    if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
        raise ContractValidationError(f"{description} must be a non-symlink directory")


def _atomic_publish(path: Path, files: dict[str, bytes]) -> None:
    _ensure_safe_dir(path.parent, description="artifact parent")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _ensure_safe_dir(path, description="artifact output")
        names = {item.name for item in path.iterdir()}
        if names != set(files):
            raise ContractValidationError("artifact output path has unexpected members")
        for name, expected in files.items():
            member_path = path / name
            reject_symlink_components(member_path, description=f"artifact member {name}")
            if not member_path.is_file() or member_path.is_symlink() or member_path.read_bytes() != expected:
                raise ContractValidationError(f"existing artifact bytes are not deterministic: {name}")
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


def publish_source_bundle(bundle: V23SourceBundle, *, output_root: str | Path) -> tuple[str, Path]:
    if type(bundle) is not V23SourceBundle:
        raise ContractValidationError("source publication requires V23SourceBundle")
    first_members = {f"{item.asset}_{item.timeframe}.json": canonical_json_bytes(item.to_payload()) for item in bundle.assets}
    second_members = {f"{item.asset}_{item.timeframe}.json": canonical_json_bytes(item.to_payload()) for item in bundle.assets}
    if first_members != second_members:
        raise ContractValidationError("source bundle bytes are not deterministic")
    semantic = bundle.identity_payload()
    members = tuple(_member(name, first_members[name]) for name in sorted(first_members, key=lambda value: CANONICAL_COHORTS.index(tuple(value.removesuffix(".json").split("_")))))
    if semantic["members"] != list(members) or deterministic_hash(semantic) != bundle.bundle_id:
        raise ContractValidationError("source bundle member identity does not reconcile")
    manifest = {**semantic, "bundle_id": bundle.bundle_id, "bundle_id_semantic_payload": semantic}
    manifest_bytes = canonical_json_bytes(manifest)
    if manifest_bytes != canonical_json_bytes({**semantic, "bundle_id": bundle.bundle_id, "bundle_id_semantic_payload": semantic}):
        raise ContractValidationError("source manifest bytes are not deterministic")
    files = {"manifest.json": manifest_bytes, **first_members}
    path = Path(output_root) / "source" / bundle.bundle_id
    _atomic_publish(path, files)
    return bundle.bundle_id, path


def _parse_timestamp(value: Any, *, path: str):
    from datetime import datetime

    if type(value) is not str or not value.endswith("Z"):
        raise ContractValidationError(f"{path} must use UTC Z notation")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractValidationError(f"{path} is not a valid timestamp") from exc


def _parse_source_member(payload: Any) -> V23SourceMember:
    if type(payload) is not dict:
        raise ContractValidationError("source member must be a mapping")
    expected = {
        "schema_version", "asset", "venue", "timeframe", "source_id", "source_bundle_id", "bars_sha256", "grid_sha256",
        "row_count", "first_open_time", "last_closed_at", "requested_since", "requested_until", "provider_calls",
        "provider_request_since_ms", "provider_request_until_ms", "adapter_limit", "source_kind", "implementation_commit", "bars", "capsule_id",
    }
    if set(payload) != expected or payload["schema_version"] != "1.0" or type(payload["bars"]) is not list:
        raise ContractValidationError("source member schema mismatch")
    bars = []
    for index, raw in enumerate(payload["bars"]):
        if type(raw) is not dict or set(raw) != {"open_time", "closed_at", "open", "high", "low", "close", "volume", "bar_id"}:
            raise ContractValidationError(f"source bar {index} schema mismatch")
        values = dict(
            open_time=_parse_timestamp(raw["open_time"], path=f"bars[{index}].open_time"),
            closed_at=_parse_timestamp(raw["closed_at"], path=f"bars[{index}].closed_at"),
            open=raw["open"], high=raw["high"], low=raw["low"], close=raw["close"], volume=raw["volume"], bar_id=raw["bar_id"],
        )
        try:
            bars.append(IntervalBar(**values) if payload["timeframe"] == "12h" else SourceBar(**values))
        except (ContractValidationError, TypeError, ValueError, OverflowError) as exc:
            raise ContractValidationError(f"source bar {index} is invalid") from exc
    member = V23SourceMember(
        asset=payload["asset"], venue=payload["venue"], timeframe=payload["timeframe"], source_id=payload["source_id"], source_bundle_id=payload["source_bundle_id"],
        bars_sha256=payload["bars_sha256"], grid_sha256=payload["grid_sha256"], row_count=payload["row_count"], first_open_time=_parse_timestamp(payload["first_open_time"], path="first_open_time"), last_closed_at=_parse_timestamp(payload["last_closed_at"], path="last_closed_at"), requested_since=_parse_timestamp(payload["requested_since"], path="requested_since"), requested_until=_parse_timestamp(payload["requested_until"], path="requested_until"), provider_calls=payload["provider_calls"], provider_request_since_ms=payload["provider_request_since_ms"], provider_request_until_ms=payload["provider_request_until_ms"], adapter_limit=payload["adapter_limit"], source_kind=payload["source_kind"], implementation_commit=payload["implementation_commit"], bars=tuple(bars),
    )
    if payload["capsule_id"] != member.capsule_id:
        raise ContractValidationError("source member capsule identity mismatch")
    return member


def _validated_manifest(path: Path, expected_members: set[str]) -> dict[str, Any]:
    _ensure_safe_dir(path, description="artifact bundle")
    if {item.name for item in path.iterdir()} != expected_members:
        raise ContractValidationError("artifact member set mismatch")
    manifest = load_json(path / "manifest.json")
    if type(manifest) is not dict:
        raise ContractValidationError("artifact manifest must be a mapping")
    semantic = manifest.get("bundle_id_semantic_payload")
    bundle_id = manifest.get("bundle_id")
    if type(semantic) is not dict or type(bundle_id) is not str or deterministic_hash(semantic) != bundle_id or path.name != bundle_id:
        raise ContractValidationError("artifact bundle identity mismatch")
    members = semantic.get("members")
    expected_member_names = expected_members - {"manifest.json"}
    if (
        type(members) is not list
        or len(members) != len(expected_member_names)
        or {item.get("name") for item in members if type(item) is dict} != expected_member_names
    ):
        raise ContractValidationError("artifact manifest member metadata mismatch")
    for item in members:
        if type(item) is not dict or set(item) != {"name", "sha256", "byte_length"}:
            raise ContractValidationError("malformed artifact member metadata")
        name = item["name"]
        if type(name) is not str or name == "manifest.json" or "/" in name or "\\" in name or ".." in Path(name).parts:
            raise ContractValidationError("unsafe artifact member name")
        member_path = path / name
        if member_path.is_symlink() or not member_path.is_file() or sha256_hex(member_path.read_bytes()) != item["sha256"] or len(member_path.read_bytes()) != item["byte_length"]:
            raise ContractValidationError(f"artifact member hash mismatch: {name}")
    if set(manifest) != set(semantic) | {"bundle_id", "bundle_id_semantic_payload"}:
        raise ContractValidationError("artifact manifest schema mismatch")
    for key, value in semantic.items():
        if manifest.get(key) != value:
            raise ContractValidationError(f"artifact manifest field mismatch: {key}")
    return manifest


def load_source_bundle(path: str | Path, *, expected_bundle_id: str | None = None) -> V23SourceBundle:
    bundle_path = Path(path)
    manifest = _validated_manifest(bundle_path, {"manifest.json", "TAOUSDT_1d.json", "ETHUSDT_1d.json", "SOLUSDT_1d.json", "TAOUSDT_12h.json", "ETHUSDT_12h.json", "SOLUSDT_12h.json"})
    semantic = manifest["bundle_id_semantic_payload"]
    if semantic.get("schema_version") != "1.0" or semantic.get("stage") != "development":
        raise ContractValidationError("source artifact stage/schema mismatch")
    if expected_bundle_id is not None and manifest["bundle_id"] != expected_bundle_id:
        raise ContractValidationError("source artifact bundle ID mismatch")
    assets = tuple(
        _parse_source_member(load_json(bundle_path / f"{asset}_{timeframe}.json"))
        for asset, timeframe in CANONICAL_COHORTS
    )
    bundle = V23SourceBundle(implementation_commit=semantic["implementation_commit"], config_hash=semantic["config_hash"], assets=assets)
    if bundle.bundle_id != manifest["bundle_id"] or bundle.identity_payload() != semantic:
        raise ContractValidationError("source artifact semantics do not match recomputed bundle")
    return bundle


def publish_evaluation_bundle(
    study: Any,
    *,
    config: AdaptiveContextCalibrationConfig,
    output_root: str | Path,
) -> tuple[str, Path]:
    from .contracts import StudyResult

    if type(study) is not StudyResult or type(config) is not AdaptiveContextCalibrationConfig:
        raise ContractValidationError("evaluation publication requires typed study/config")
    study_bytes = canonical_json_bytes(study.to_payload())
    cases_bytes = canonical_json_bytes([item.to_payload() for item in study.cases])
    predictions_bytes = canonical_json_bytes([item.to_payload() for item in study.predictions])
    files = {"study.json": study_bytes, "cases.json": cases_bytes, "predictions.json": predictions_bytes}
    semantic = {
        "schema_version": "1.0",
        "stage": "adaptive_context_calibration_development_evaluation",
        "implementation_commit": study.implementation_commit,
        "config_hash": config.config_hash,
        "source_bundle_id": study.source_bundle_id,
        "study_id": study.study_id,
        "members": [_member(name, files[name]) for name in ("study.json", "cases.json", "predictions.json")],
    }
    bundle_id = deterministic_hash(semantic)
    manifest = {**semantic, "bundle_id": bundle_id, "bundle_id_semantic_payload": semantic}
    manifest_bytes = canonical_json_bytes(manifest)
    path = Path(output_root) / "evaluation" / bundle_id
    _atomic_publish(path, {"manifest.json": manifest_bytes, **files})
    return bundle_id, path


def validate_evaluation_bundle(
    path: str | Path,
    *,
    config: AdaptiveContextCalibrationConfig,
    source_bundle: V23SourceBundle,
    implementation_commit: str | None = None,
    expected_bundle_id: str | None = None,
) -> Any:
    """Recompute the frozen evaluation and reject semantic or byte tampering."""

    manifest = _validated_manifest(Path(path), {"manifest.json", "study.json", "cases.json", "predictions.json"})
    semantic = manifest["bundle_id_semantic_payload"]
    if semantic.get("schema_version") != "1.0" or semantic.get("stage") != "adaptive_context_calibration_development_evaluation":
        raise ContractValidationError("evaluation artifact stage/schema mismatch")
    if expected_bundle_id is not None and manifest["bundle_id"] != expected_bundle_id:
        raise ContractValidationError("evaluation bundle ID mismatch")
    if semantic.get("config_hash") != config.config_hash or semantic.get("source_bundle_id") != source_bundle.bundle_id:
        raise ContractValidationError("evaluation protocol identity mismatch")
    from .runner import compute_study

    commit = implementation_commit or semantic.get("implementation_commit")
    recomputed = compute_study(config, source_bundle=source_bundle, implementation_commit=commit)
    if load_json(Path(path) / "study.json") != recomputed.to_payload() or load_json(Path(path) / "cases.json") != [item.to_payload() for item in recomputed.cases] or load_json(Path(path) / "predictions.json") != [item.to_payload() for item in recomputed.predictions]:
        raise ContractValidationError("evaluation artifact semantics do not match recomputation")
    if semantic.get("study_id") != recomputed.study_id or manifest.get("implementation_commit") != recomputed.implementation_commit:
        raise ContractValidationError("evaluation artifact identity does not match recomputation")
    return recomputed


__all__ = [
    "canonical_json_bytes",
    "load_json",
    "load_source_bundle",
    "publish_evaluation_bundle",
    "publish_source_bundle",
    "sha256_hex",
    "validate_evaluation_bundle",
]
