"""Immutable V2.4 source/evaluation publication and semantic validation."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.domain.identity import canonical_json, deterministic_hash
from libs.models.sr.research.artifacts.path_safety import reject_symlink_components, require_regular_file
from libs.models.sr.research.artifacts.publisher import publish_immutable_directory
from libs.models.sr.research.artifacts.validator import load_strict_json

from .config import COHORTS, RelativeSalienceRankConfig
from .contracts import IntervalBar, SourceBundle, SourceMember


def _bytes(value: Any) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _member(name: str, data: bytes) -> dict[str, object]:
    return {"name": name, "sha256": sha256(data).hexdigest(), "byte_length": len(data)}


def _manifest(path: Path, *, expected_members: tuple[str, ...], description: str) -> dict[str, Any]:
    reject_symlink_components(path, description=description)
    if not path.is_dir() or path.is_symlink():
        raise ContractValidationError(f"{description} must be a real directory")
    if {item.name for item in path.iterdir()} != set(expected_members):
        raise ContractValidationError(f"{description} member set mismatch")
    manifest_path = path / "manifest.json"
    require_regular_file(manifest_path, description=f"{description} manifest")
    value = load_strict_json(manifest_path, description=f"{description} manifest")
    if type(value) is not dict or type(value.get("bundle_id_semantic_payload")) is not dict:
        raise ContractValidationError(f"{description} manifest schema mismatch")
    semantic = value["bundle_id_semantic_payload"]
    if value.get("bundle_id") != deterministic_hash(semantic) or path.name != value.get("bundle_id"):
        raise ContractValidationError(f"{description} bundle identity mismatch")
    if set(value) != set(semantic) | {"bundle_id", "bundle_id_semantic_payload"} or any(value.get(key) != item for key, item in semantic.items()):
        raise ContractValidationError(f"{description} manifest fields mismatch")
    metadata = semantic.get("members")
    names = tuple(name for name in expected_members if name != "manifest.json")
    if type(metadata) is not list or tuple(item.get("name") for item in metadata if type(item) is dict) != names:
        raise ContractValidationError(f"{description} member metadata mismatch")
    for item in metadata:
        if type(item) is not dict or set(item) != {"name", "sha256", "byte_length"}:
            raise ContractValidationError(f"{description} member metadata is malformed")
        member_path = path / item["name"]
        require_regular_file(member_path, description=f"{description} member")
        data = member_path.read_bytes()
        if _member(item["name"], data) != item:
            raise ContractValidationError(f"{description} member hash mismatch")
    return value


def publish_source_bundle(bundle: SourceBundle, *, output_root: str | Path) -> tuple[str, Path]:
    if type(bundle) is not SourceBundle:
        raise ContractValidationError("V2.4 source publication requires SourceBundle")
    entries = {f"{member.asset}_{member.timeframe}.json": _bytes(member.to_payload()) for member in bundle.members}
    semantic = bundle.identity_payload()
    if semantic["members"] != [_member(name, entries[name]) for name in entries] or deterministic_hash(semantic) != bundle.bundle_id:
        raise ContractValidationError("V2.4 source artifact identity does not reconcile")
    manifest = {**semantic, "bundle_id": bundle.bundle_id, "bundle_id_semantic_payload": semantic}
    path = Path(output_root) / "source" / bundle.bundle_id
    publish_immutable_directory(path, {"manifest.json": _bytes(manifest), **entries}, description="V2.4 source bundle")
    return bundle.bundle_id, path


def _parse_timestamp(value: Any) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise ContractValidationError("artifact timestamp must use UTC Z notation")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractValidationError("artifact timestamp is invalid") from exc


def _parse_member(payload: Any) -> SourceMember:
    expected = {"asset", "timeframe", "history_bars", "fresh_bars", "provider_calls", "source_kind", "bars_sha256", "grid_sha256"}
    if type(payload) is not dict or set(payload) != expected:
        raise ContractValidationError("V2.4 source member schema mismatch")
    def bars(items: Any) -> tuple[IntervalBar, ...]:
        if type(items) is not list:
            raise ContractValidationError("V2.4 source bars schema mismatch")
        result = []
        for item in items:
            if type(item) is not dict or set(item) != {"open_time", "closed_at", "open", "high", "low", "close", "volume", "bar_id"}:
                raise ContractValidationError("V2.4 source bar schema mismatch")
            result.append(IntervalBar(_parse_timestamp(item["open_time"]), _parse_timestamp(item["closed_at"]), item["open"], item["high"], item["low"], item["close"], item["volume"], item["bar_id"]))
        return tuple(result)
    member = SourceMember(payload["asset"], payload["timeframe"], bars(payload["history_bars"]), bars(payload["fresh_bars"]), payload["provider_calls"], payload["source_kind"])
    if (member.bars_hash, member.grid_hash) != (payload["bars_sha256"], payload["grid_sha256"]):
        raise ContractValidationError("V2.4 source member identity mismatch")
    return member


def load_source_bundle(path: str | Path, *, expected_bundle_id: str | None = None) -> SourceBundle:
    root = Path(path)
    expected = ("manifest.json", *(f"{asset}_{timeframe}.json" for asset, timeframe in COHORTS))
    manifest = _manifest(root, expected_members=expected, description="V2.4 source bundle")
    semantic = manifest["bundle_id_semantic_payload"]
    if semantic.get("stage") != "relative_salience_rank_source" or semantic.get("schema_version") != "1.0":
        raise ContractValidationError("V2.4 source stage/schema mismatch")
    if expected_bundle_id is not None and manifest["bundle_id"] != expected_bundle_id:
        raise ContractValidationError("V2.4 source bundle ID mismatch")
    members = tuple(_parse_member(load_strict_json(root / f"{asset}_{timeframe}.json", description="V2.4 source member")) for asset, timeframe in COHORTS)
    bundle = SourceBundle(semantic["implementation_commit"], semantic["config_hash"], members)
    if bundle.identity_payload() != semantic or manifest["bundle_id"] != bundle.bundle_id:
        raise ContractValidationError("V2.4 source semantic identity mismatch")
    return bundle


def publish_evaluation_bundle(study: Any, *, config: RelativeSalienceRankConfig, output_root: str | Path) -> tuple[str, Path]:
    study_bytes, cases_bytes = _bytes(study.to_payload()), _bytes([case.to_payload() for case in study.cases])
    semantic = {"schema_version": "1.0", "stage": "relative_salience_rank_evaluation", "implementation_commit": study.implementation_commit, "config_hash": config.config_hash, "source_bundle_id": study.source_bundle_id, "study_id": study.study_id, "members": [_member("study.json", study_bytes), _member("cases.json", cases_bytes)]}
    bundle_id = deterministic_hash(semantic)
    manifest = {**semantic, "bundle_id": bundle_id, "bundle_id_semantic_payload": semantic}
    path = Path(output_root) / "evaluation" / bundle_id
    publish_immutable_directory(path, {"manifest.json": _bytes(manifest), "study.json": study_bytes, "cases.json": cases_bytes}, description="V2.4 evaluation bundle")
    return bundle_id, path


def validate_evaluation_bundle(path: str | Path, *, config: RelativeSalienceRankConfig, source_bundle: SourceBundle, implementation_commit: str | None = None) -> Any:
    manifest = _manifest(Path(path), expected_members=("manifest.json", "study.json", "cases.json"), description="V2.4 evaluation bundle")
    semantic = manifest["bundle_id_semantic_payload"]
    if semantic.get("stage") != "relative_salience_rank_evaluation" or semantic.get("config_hash") != config.config_hash or semantic.get("source_bundle_id") != source_bundle.bundle_id:
        raise ContractValidationError("V2.4 evaluation protocol identity mismatch")
    commit = implementation_commit or semantic.get("implementation_commit")
    if semantic.get("implementation_commit") != commit:
        raise ContractValidationError("V2.4 evaluation implementation identity mismatch")
    from .runner import compute_study
    study = compute_study(config, source_bundle=source_bundle, implementation_commit=commit)
    if study.study_id != semantic.get("study_id") or load_strict_json(Path(path) / "study.json", description="V2.4 study") != study.to_payload() or load_strict_json(Path(path) / "cases.json", description="V2.4 cases") != [case.to_payload() for case in study.cases]:
        raise ContractValidationError("V2.4 evaluation semantics do not match recomputation")
    return study


__all__ = ["load_source_bundle", "publish_evaluation_bundle", "publish_source_bundle", "validate_evaluation_bundle"]
