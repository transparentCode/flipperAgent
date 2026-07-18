"""Canonical source/evaluation artifacts with semantic recomputation."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import os
import tempfile
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import canonical_json, deterministic_hash
from libs.models.sr.research.source.contracts import SourceBar

from .contracts import (
    APPROVED_ASSETS,
    AssetSource,
    CohortEvaluation,
    SourceBundle,
)


_MEMBER_NAMES = tuple(f"{asset}.json" for asset in APPROVED_ASSETS)


def _bytes(payload: Any) -> bytes:
    return (canonical_json(payload) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _finite(value: Any, *, path: str = "json") -> None:
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ContractValidationError(f"non-finite artifact value at {path}")
    if isinstance(value, dict):
        for key, item in value.items():
            _finite(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _finite(item, path=f"{path}[{index}]")


def load_json(path: str | Path) -> Any:
    try:
        payload = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ContractValidationError(f"invalid JSON artifact: {path}") from exc
    _finite(payload)
    return payload


def _member(name: str, data: bytes) -> dict[str, Any]:
    return {"name": name, "sha256": _sha(data), "byte_length": len(data)}


def _atomic_publish(path: Path, files: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_dir() or path.is_symlink() or {item.name for item in path.iterdir()} != set(files):
            raise ContractValidationError("artifact output path has unexpected existing members")
        for name, data in files.items():
            if (path / name).read_bytes() != data:
                raise ContractValidationError("existing artifact bytes are not deterministic")
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


def _parse_timestamp(value: Any, *, path: str):
    from datetime import datetime

    if type(value) is not str or not value.endswith("Z"):
        raise ContractValidationError(f"{path} must use UTC Z notation")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractValidationError(f"{path} is not a valid timestamp") from exc


def _parse_source(payload: Any) -> AssetSource:
    if type(payload) is not dict:
        raise ContractValidationError("source member must be a mapping")
    expected = {
        "schema_version", "asset", "venue", "timeframe", "source_id", "source_bundle_id",
        "bars_sha256", "row_count", "first_open_time", "last_closed_at", "grid_sha256",
        "requested_since", "requested_until", "provider_calls", "provider_request_since_ms",
        "provider_request_until_ms", "adapter_limit", "source_kind", "resolved_sr_config_hash",
        "resolved_input_hash", "bars", "capsule_id",
    }
    if set(payload) != expected or payload["schema_version"] != "1.0":
        raise ContractValidationError("source member schema mismatch")
    raw_bars = payload["bars"]
    if type(raw_bars) is not list:
        raise ContractValidationError("source member bars must be a list")
    bars = []
    for index, raw in enumerate(raw_bars):
        if type(raw) is not dict or set(raw) != {"open_time", "closed_at", "open", "high", "low", "close", "volume", "bar_id"}:
            raise ContractValidationError(f"source bar {index} schema mismatch")
        try:
            bars.append(SourceBar(
                open_time=_parse_timestamp(raw["open_time"], path=f"bars[{index}].open_time"),
                closed_at=_parse_timestamp(raw["closed_at"], path=f"bars[{index}].closed_at"),
                open=raw["open"], high=raw["high"], low=raw["low"], close=raw["close"], volume=raw["volume"], bar_id=raw["bar_id"],
            ))
        except ContractValidationError:
            raise
        except (TypeError, ValueError, OverflowError) as exc:
            raise ContractValidationError(f"source bar {index} is invalid") from exc
    source = AssetSource(
        asset=payload["asset"], venue=payload["venue"], timeframe=payload["timeframe"], source_id=payload["source_id"], source_bundle_id=payload["source_bundle_id"], bars_sha256=payload["bars_sha256"], row_count=payload["row_count"], first_open_time=_parse_timestamp(payload["first_open_time"], path="first_open_time"), last_closed_at=_parse_timestamp(payload["last_closed_at"], path="last_closed_at"), grid_sha256=payload["grid_sha256"], requested_since=_parse_timestamp(payload["requested_since"], path="requested_since"), requested_until=_parse_timestamp(payload["requested_until"], path="requested_until"), provider_calls=payload["provider_calls"], provider_request_since_ms=payload["provider_request_since_ms"], provider_request_until_ms=payload["provider_request_until_ms"], adapter_limit=payload["adapter_limit"], source_kind=payload["source_kind"], resolved_sr_config_hash=payload["resolved_sr_config_hash"], resolved_input_hash=payload["resolved_input_hash"], bars=tuple(bars),
    )
    if payload["capsule_id"] != source.capsule_id:
        raise ContractValidationError("source capsule_id does not match content")
    return source


def publish_source_bundle(bundle: SourceBundle, *, output_root: str | Path) -> tuple[str, Path]:
    files = {f"{source.asset}.json": _bytes(source.to_payload()) for source in bundle.assets}
    members = tuple(_member(f"{asset}.json", files[f"{asset}.json"]) for asset in APPROVED_ASSETS)
    semantic = {**bundle.identity_payload()}
    if tuple(semantic.get("members", ())) != members:
        raise ContractValidationError("source bundle member identity mismatch")
    manifest = {
        **semantic,
        "bundle_id": bundle.bundle_id,
        "bundle_id_semantic_payload": semantic,
    }
    if deterministic_hash(semantic) != bundle.bundle_id:
        raise ContractValidationError("source bundle identity does not bind its members")
    files = {"manifest.json": _bytes(manifest), **files}
    path = Path(output_root) / "source" / bundle.bundle_id
    _atomic_publish(path, files)
    return bundle.bundle_id, path


def _validate_manifest(path: Path, expected_members: set[str]) -> dict[str, Any]:
    if not path.is_dir() or path.is_symlink() or {item.name for item in path.iterdir()} != expected_members:
        raise ContractValidationError("artifact member set mismatch")
    manifest = load_json(path / "manifest.json")
    if type(manifest) is not dict:
        raise ContractValidationError("artifact manifest must be a mapping")
    semantic = manifest.get("bundle_id_semantic_payload")
    bundle_id = manifest.get("bundle_id")
    if type(semantic) is not dict or type(bundle_id) is not str or deterministic_hash(semantic) != bundle_id or path.name != bundle_id:
        raise ContractValidationError("artifact bundle identity mismatch")
    members = semantic.get("members")
    if type(members) is not list or len(members) != len(expected_members) - 1 or {item.get("name") for item in members if type(item) is dict} != expected_members - {"manifest.json"}:
        raise ContractValidationError("artifact manifest member metadata mismatch")
    for item in members:
        if type(item) is not dict or set(item) != {"name", "sha256", "byte_length"}:
            raise ContractValidationError("malformed artifact member metadata")
        name = item["name"]
        if name == "manifest.json" or type(name) is not str or "/" in name or "\\" in name or ".." in Path(name).parts:
            raise ContractValidationError("unsafe artifact member name")
        member_path = path / name
        if member_path.is_symlink():
            raise ContractValidationError("artifact members must not be symlinks")
        data = member_path.read_bytes()
        if _sha(data) != item["sha256"] or len(data) != item["byte_length"]:
            raise ContractValidationError(f"artifact member hash mismatch: {name}")
    if set(manifest) != set(semantic) | {"bundle_id", "bundle_id_semantic_payload"}:
        raise ContractValidationError("artifact manifest schema mismatch")
    for key, value in semantic.items():
        if manifest.get(key) != value:
            raise ContractValidationError(f"artifact top-level field does not match semantic payload: {key}")
    return manifest


def load_source_bundle(
    path: str | Path,
    *,
    config: Any | None = None,
    implementation_commit: str | None = None,
    expected_bundle_id: str | None = None,
) -> SourceBundle:
    bundle_path = Path(path)
    manifest = _validate_manifest(bundle_path, {"manifest.json", *_MEMBER_NAMES})
    semantic = manifest["bundle_id_semantic_payload"]
    if semantic.get("stage") != "development" or semantic.get("schema_version") != "1.0":
        raise ContractValidationError("source artifact stage/schema mismatch")
    if config is not None and semantic.get("config_hash") != config.config_hash:
        raise ContractValidationError("source artifact config mismatch")
    if implementation_commit is not None and semantic.get("implementation_commit") != implementation_commit:
        raise ContractValidationError("source artifact implementation mismatch")
    sources = tuple(_parse_source(load_json(bundle_path / f"{asset}.json")) for asset in APPROVED_ASSETS)
    if expected_bundle_id is not None and manifest["bundle_id"] != expected_bundle_id:
        raise ContractValidationError("source artifact bundle ID does not match the requested source")
    if config is not None:
        tao = sources[0]
        if (
            tao.asset != "TAOUSDT"
            or tao.source_id != config.tao_source_id
            or tao.source_bundle_id != config.tao_source_bundle_id
            or tao.bars_sha256 != config.tao_bars_sha256
            or tao.row_count != config.source_row_count
            or tao.source_kind != "frozen_v1_6"
            or tao.provider_calls != 0
            or tao.first_open_time != config.source_since
            or tao.last_closed_at != config.source_until
        ):
            raise ContractValidationError("source artifact does not preserve the approved TAOUSDT capsule")
    try:
        bundle = SourceBundle(
            implementation_commit=semantic["implementation_commit"],
            config_hash=semantic["config_hash"],
                assets=sources,
                resolved_sr_config_hashes=tuple(tuple(item) for item in semantic["resolved_sr_config_hashes"]),
                resolved_input_hashes=tuple(tuple(item) for item in semantic["resolved_input_hashes"]),
                resolved_sr_field_provenance=tuple(
                    (asset, tuple(tuple(pair) for pair in entries))
                    for asset, entries in semantic["resolved_sr_field_provenance"]
                ),
                resolved_input_field_provenance=tuple(
                    (asset, tuple(tuple(pair) for pair in entries))
                    for asset, entries in semantic["resolved_input_field_provenance"]
                ),
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractValidationError("source artifact semantic payload is malformed") from exc
    if manifest["bundle_id"] != bundle.bundle_id or semantic != bundle.identity_payload():
        raise ContractValidationError("source artifact semantic payload does not match recomputed source bundle")
    return bundle


def validate_source_bundle(*args: Any, **kwargs: Any) -> SourceBundle:
    return load_source_bundle(*args, **kwargs)


def publish_evaluation_bundle(
    evaluation: CohortEvaluation,
    *,
    output_root: str | Path,
    config: Any | None = None,
    source_bundle: SourceBundle | None = None,
) -> tuple[str, Path]:
    payload = evaluation.to_payload()
    evaluation_bytes = _bytes(payload)
    members = (_member("evaluation.json", evaluation_bytes),)
    semantic = {
        "schema_version": "1.0",
        "stage": "development_evaluation",
        "implementation_commit": evaluation.implementation_commit,
        "config_hash": evaluation.config_hash,
        "source_bundle_id": evaluation.source_bundle_id,
        "evaluation_id": evaluation.evaluation_id,
        "members": list(members),
    }
    if config is not None:
        if source_bundle is None or source_bundle.bundle_id != evaluation.source_bundle_id:
            raise ContractValidationError("evaluation publication source bundle does not match evaluation")
        semantic["protocol"] = {
            "config": config.to_payload(),
            "config_hash": config.config_hash,
            "resolved_sr_config_hashes": [list(item) for item in source_bundle.resolved_sr_config_hashes],
            "resolved_input_hashes": [list(item) for item in source_bundle.resolved_input_hashes],
            "resolved_sr_field_provenance": [
                [asset, [list(pair) for pair in entries]]
                for asset, entries in source_bundle.resolved_sr_field_provenance
            ],
            "resolved_input_field_provenance": [
                [asset, [list(pair) for pair in entries]]
                for asset, entries in source_bundle.resolved_input_field_provenance
            ],
            "atr": {"method": config.atr_method, "period": config.atr_period, "seed": config.atr_seed, "common_start_period": config.common_start_period},
            "outcome": {"start_offset_bars": config.outcome_start_offset_bars, "horizon_bars": config.outcome_horizon_bars, "window_policy": "half_open_utc_daily"},
            "folds": [fold.to_payload() for fold in config.folds],
            "readiness": config.readiness_gates.to_payload(),
        }
    bundle_id = deterministic_hash(semantic)
    manifest = {**semantic, "bundle_id": bundle_id, "bundle_id_semantic_payload": semantic}
    path = Path(output_root) / "evaluation" / bundle_id
    _atomic_publish(path, {"manifest.json": _bytes(manifest), "evaluation.json": evaluation_bytes})
    return bundle_id, path


def validate_evaluation_bundle(
    path: str | Path,
    *,
    config: Any,
    source_bundle: SourceBundle,
    resolved_configs: dict[str, Any],
    resolved_inputs: dict[str, Any] | None = None,
    implementation_commit: str | None = None,
) -> CohortEvaluation:
    bundle_path = Path(path)
    manifest = _validate_manifest(bundle_path, {"manifest.json", "evaluation.json"})
    semantic = manifest["bundle_id_semantic_payload"]
    if semantic.get("stage") != "development_evaluation" or semantic.get("source_bundle_id") != source_bundle.bundle_id or semantic.get("config_hash") != config.config_hash:
        raise ContractValidationError("evaluation artifact context mismatch")
    from .metrics import evaluate_cohort

    evaluation_commit = semantic.get("implementation_commit") if implementation_commit is None else implementation_commit
    if semantic.get("implementation_commit") != evaluation_commit:
        raise ContractValidationError("evaluation implementation identity mismatch")
    recomputed = evaluate_cohort(
        config,
        source_bundle,
        resolved_configs,
        resolved_inputs,
        implementation_commit=evaluation_commit,
    )
    expected_protocol = {
        "config": config.to_payload(),
        "config_hash": config.config_hash,
        "resolved_sr_config_hashes": [list(item) for item in source_bundle.resolved_sr_config_hashes],
        "resolved_input_hashes": [list(item) for item in source_bundle.resolved_input_hashes],
        "resolved_sr_field_provenance": [
            [asset, [list(pair) for pair in entries]]
            for asset, entries in source_bundle.resolved_sr_field_provenance
        ],
        "resolved_input_field_provenance": [
            [asset, [list(pair) for pair in entries]]
            for asset, entries in source_bundle.resolved_input_field_provenance
        ],
        "atr": {"method": config.atr_method, "period": config.atr_period, "seed": config.atr_seed, "common_start_period": config.common_start_period},
        "outcome": {"start_offset_bars": config.outcome_start_offset_bars, "horizon_bars": config.outcome_horizon_bars, "window_policy": "half_open_utc_daily"},
        "folds": [fold.to_payload() for fold in config.folds],
        "readiness": config.readiness_gates.to_payload(),
    }
    if semantic.get("protocol") != expected_protocol:
        raise ContractValidationError("evaluation manifest protocol binding mismatch")
    payload = load_json(bundle_path / "evaluation.json")
    if payload != recomputed.to_payload():
        raise ContractValidationError("evaluation artifact semantics do not match recomputed cohort")
    if semantic.get("evaluation_id") != recomputed.evaluation_id or manifest.get("implementation_commit") != recomputed.implementation_commit:
        raise ContractValidationError("evaluation artifact identity does not match recomputed cohort")
    return recomputed


def load_evaluation_bundle(*args: Any, **kwargs: Any) -> CohortEvaluation:
    return validate_evaluation_bundle(*args, **kwargs)


__all__ = [
    "load_evaluation_bundle", "load_json", "load_source_bundle", "publish_evaluation_bundle",
    "publish_source_bundle", "validate_evaluation_bundle", "validate_source_bundle",
]
