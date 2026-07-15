"""Frozen V1.5 source validation and sealed capsule publication."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import os
import tempfile
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import canonical_json, utc_isoformat
from libs.models.sr.scripts.baseline_trial.artifacts import validate_bundle
from libs.models.sr.scripts.baseline_trial.contracts import SourceBar

from .config import (
    CalibrationConfig,
    HOLDOUT_START,
    SOURCE_WINDOW_END,
    SOURCE_WINDOW_START,
)
from .contracts import CapsuleStage, SCHEMA_VERSION, SourceCapsule


_SOURCE_KEYS = {
    "schema_version",
    "trial_name",
    "requested_since",
    "requested_until",
    "actual_since",
    "actual_until",
    "raw_row_count",
    "adapter_limit",
    "gap_policy",
    "bars",
}
_BAR_KEYS = {"open_time", "closed_at", "open", "high", "low", "close", "volume", "bar_id"}
_CAPSULE_MEMBER_NAMES = ("manifest.json", "source_bars.json")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json_load(path: Path) -> Any:
    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON constant: {value}")

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ContractValidationError(f"invalid JSON source member: {path}") from exc


def _bytes(payload: Any) -> bytes:
    if not isinstance(payload, dict):
        raise ContractValidationError("source payload must be a mapping")
    return canonical_json(payload).encode("utf-8") + b"\n"


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _resolve_under(root: Path, relative: str, *, field_name: str) -> Path:
    root = root.resolve()
    path = (root / relative).resolve()
    if root not in path.parents:
        raise ContractValidationError(f"{field_name} escaped repository root")
    return path


def _timestamp(value: Any, *, field_name: str):
    if type(value) is not str or not value.endswith("Z"):
        raise ContractValidationError(f"{field_name} must use strict UTC Z notation")
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractValidationError(f"{field_name} must be an ISO timestamp") from exc
    from libs.models.sr.domain.identity import require_utc

    return require_utc(parsed, field_name=field_name)


def _epoch_ms(timestamp) -> int:
    from datetime import datetime, timezone

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = timestamp - epoch
    return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000


def _parse_source_bars(payload: Any, *, config: CalibrationConfig) -> tuple[SourceBar, ...]:
    if type(payload) is not dict or set(payload) != _SOURCE_KEYS:
        raise ContractValidationError("V1.5 source_bars.json schema mismatch")
    if payload["schema_version"] != "1.0" or payload["trial_name"] != "sr-v1.5-taousdt-1d-baseline":
        raise ContractValidationError("V1.5 source payload identity mismatch")
    requested_since = _timestamp(payload["requested_since"], field_name="requested_since")
    requested_until = _timestamp(payload["requested_until"], field_name="requested_until")
    if requested_since != SOURCE_WINDOW_START or requested_until != SOURCE_WINDOW_END:
        raise ContractValidationError("V1.5 source window mismatch")
    if payload["adapter_limit"] != 1500 or payload["gap_policy"] != "reject":
        raise ContractValidationError("V1.5 source protocol mismatch")
    raw_bars = payload["bars"]
    if type(raw_bars) is not list or len(raw_bars) != config.source_row_count:
        raise ContractValidationError("V1.5 source row count mismatch")
    bars: list[SourceBar] = []
    previous_open = None
    previous_bar_id = None
    for index, raw in enumerate(raw_bars):
        if type(raw) is not dict or set(raw) != _BAR_KEYS:
            raise ContractValidationError(f"source bar {index} schema mismatch")
        open_time = _timestamp(raw["open_time"], field_name=f"bars[{index}].open_time")
        closed_at = _timestamp(raw["closed_at"], field_name=f"bars[{index}].closed_at")
        if open_time < requested_since or open_time >= requested_until:
            raise ContractValidationError(f"source bar {index} is outside the requested window")
        if closed_at > requested_until or closed_at <= open_time:
            raise ContractValidationError(f"source bar {index} has an invalid causal close")
        expected_id = f"{config.venue}:{config.symbol}:{config.timeframe}:{_epoch_ms(open_time)}"
        if raw["bar_id"] != expected_id:
            raise ContractValidationError(f"source bar {index} bar_id mismatch")
        if previous_open is not None and open_time != previous_open + __import__("datetime").timedelta(days=1):
            raise ContractValidationError("V1.5 source bars are not daily and contiguous")
        if previous_bar_id == raw["bar_id"]:
            raise ContractValidationError("V1.5 source bar IDs are not unique")
        try:
            bar = SourceBar(
                open_time=open_time,
                closed_at=closed_at,
                open=raw["open"],
                high=raw["high"],
                low=raw["low"],
                close=raw["close"],
                volume=raw["volume"],
                bar_id=raw["bar_id"],
            )
        except (ContractValidationError, TypeError, ValueError) as exc:
            raise ContractValidationError(f"invalid V1.5 source bar {index}") from exc
        bars.append(bar)
        previous_open = open_time
        previous_bar_id = bar.bar_id
    if not bars or bars[-1].closed_at != _timestamp(payload["actual_until"], field_name="actual_until"):
        raise ContractValidationError("V1.5 source actual bounds mismatch")
    if bars[0].open_time != _timestamp(payload["actual_since"], field_name="actual_since"):
        raise ContractValidationError("V1.5 source actual start mismatch")
    return tuple(bars)


def load_frozen_source(config: CalibrationConfig, *, repo_root: str | Path) -> tuple[SourceBar, ...]:
    """Validate the exact approved V1.5 bundle and return its source bars."""
    root = Path(repo_root).resolve()
    bundle = _resolve_under(root, config.source_bundle_path, field_name="source_bundle_path")
    if not bundle.is_dir() or bundle.is_symlink():
        raise ContractValidationError("approved V1.5 bundle is missing or is a symlink")
    try:
        manifest = validate_bundle(bundle)
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        raise ContractValidationError("approved V1.5 bundle failed validation") from exc
    if manifest.get("bundle_id") != config.source_bundle_id:
        raise ContractValidationError("V1.5 bundle ID does not match calibration config")
    semantic = manifest.get("bundle_id_semantic_payload")
    if type(semantic) is not dict or semantic.get("source_bars_sha256") != config.source_bars_sha256:
        raise ContractValidationError("V1.5 source identity payload mismatch")
    if semantic.get("implementation_commit") != config.source_implementation_commit:
        raise ContractValidationError("V1.5 implementation identity mismatch")
    source_path = bundle / "source_bars.json"
    if source_path.is_symlink():
        raise ContractValidationError("V1.5 source member must not be a symlink")
    source_bytes = source_path.read_bytes()
    if _sha(source_bytes) != config.source_bars_sha256:
        raise ContractValidationError("V1.5 source member hash mismatch")
    return _parse_source_bars(_json_load(source_path), config=config)


def _source_payload(capsule: SourceCapsule) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "stage": capsule.stage.value,
        "source_bundle_id": capsule.source_bundle_id,
        "source_bars_sha256": capsule.source_bars_sha256,
        "source_row_count": capsule.source_row_count,
        "split_boundary": utc_isoformat(capsule.split_boundary),
        "implementation_commit": capsule.implementation_commit,
        "bars": [
            {
                "open_time": utc_isoformat(bar.open_time),
                "closed_at": utc_isoformat(bar.closed_at),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "bar_id": bar.bar_id,
            }
            for bar in capsule.bars
        ],
    }


def _manifest_payload(capsule: SourceCapsule, source_sha256: str, source_length: int) -> dict[str, Any]:
    semantic = {
        "schema_version": SCHEMA_VERSION,
        "stage": capsule.stage.value,
        "capsule_id": capsule.capsule_id,
        "source_bundle_id": capsule.source_bundle_id,
        "source_bars_sha256": capsule.source_bars_sha256,
        "source_row_count": capsule.source_row_count,
        "row_count": len(capsule.bars),
        "first_open_time": utc_isoformat(capsule.bars[0].open_time),
        "last_closed_at": utc_isoformat(capsule.bars[-1].closed_at),
        "split_boundary": utc_isoformat(capsule.split_boundary),
        "implementation_commit": capsule.implementation_commit,
        "member": {"name": "source_bars.json", "sha256": source_sha256, "byte_length": source_length},
    }
    return {
        **semantic,
        "capsule_id_semantic_payload": semantic,
        "capsule_id_recomputed_from": capsule.identity_payload(),
    }


def _atomic_publish(path: Path, files: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_dir() or path.is_symlink():
            raise ContractValidationError("capsule output path is not a directory")
        expected = set(files)
        if {item.name for item in path.iterdir()} != expected:
            raise ContractValidationError("existing capsule contains unexpected members")
        for name, data in files.items():
            if (path / name).read_bytes() != data:
                raise ContractValidationError("existing capsule bytes are not deterministic")
        return
    temporary = Path(tempfile.mkdtemp(prefix=f".{path.name}.", dir=path.parent))
    try:
        for name, data in files.items():
            (temporary / name).write_bytes(data)
        os.replace(temporary, path)
    except OSError as exc:
        raise ContractValidationError("atomic capsule publication failed") from exc
    finally:
        if temporary.exists():
            for item in temporary.iterdir():
                item.unlink()
            temporary.rmdir()


def publish_source_capsule(capsule: SourceCapsule, *, output_root: Path) -> Path:
    source_bytes = _bytes(_source_payload(capsule))
    manifest = _manifest_payload(capsule, _sha(source_bytes), len(source_bytes))
    manifest_bytes = _bytes(manifest)
    path = output_root / "source" / capsule.stage.value / capsule.capsule_id
    _atomic_publish(path, {"manifest.json": manifest_bytes, "source_bars.json": source_bytes})
    return path


def build_source_capsules(config: CalibrationConfig, *, repo_root: str | Path, implementation_commit: str) -> tuple[SourceCapsule, SourceCapsule]:
    bars = load_frozen_source(config, repo_root=repo_root)
    development_bars = tuple(bar for bar in bars if bar.closed_at < HOLDOUT_START)
    if not development_bars or len(development_bars) >= len(bars):
        raise ContractValidationError("source does not contain a strict development/holdout split")
    development = SourceCapsule(
        stage=CapsuleStage.DEVELOPMENT,
        source_bundle_id=config.source_bundle_id,
        source_bars_sha256=config.source_bars_sha256,
        source_row_count=config.source_row_count,
        split_boundary=HOLDOUT_START,
        implementation_commit=implementation_commit,
        bars=development_bars,
    )
    sealed = SourceCapsule(
        stage=CapsuleStage.SEALED_HOLDOUT,
        source_bundle_id=config.source_bundle_id,
        source_bars_sha256=config.source_bars_sha256,
        source_row_count=config.source_row_count,
        split_boundary=HOLDOUT_START,
        implementation_commit=implementation_commit,
        bars=bars,
    )
    return development, sealed


def load_capsule(path: str | Path, *, expected_stage: CapsuleStage, expected_source: CalibrationConfig, expected_implementation_commit: str | None = None) -> SourceCapsule:
    capsule_path = Path(path)
    if not capsule_path.is_dir() or capsule_path.is_symlink():
        raise ContractValidationError("source capsule path is missing or is a symlink")
    if {item.name for item in capsule_path.iterdir()} != set(_CAPSULE_MEMBER_NAMES):
        raise ContractValidationError("source capsule member set mismatch")
    manifest = _json_load(capsule_path / "manifest.json")
    source_payload = _json_load(capsule_path / "source_bars.json")
    if type(manifest) is not dict or type(source_payload) is not dict:
        raise ContractValidationError("source capsule members must be mappings")
    expected_source_keys = {
        "schema_version",
        "stage",
        "source_bundle_id",
        "source_bars_sha256",
        "source_row_count",
        "split_boundary",
        "implementation_commit",
        "bars",
    }
    if set(source_payload) != expected_source_keys:
        raise ContractValidationError("source capsule source member schema mismatch")
    expected_manifest_keys = {
        "schema_version",
        "stage",
        "capsule_id",
        "source_bundle_id",
        "source_bars_sha256",
        "source_row_count",
        "row_count",
        "first_open_time",
        "last_closed_at",
        "split_boundary",
        "implementation_commit",
        "member",
        "capsule_id_semantic_payload",
        "capsule_id_recomputed_from",
    }
    if set(manifest) != expected_manifest_keys:
        raise ContractValidationError("source capsule manifest schema mismatch")
    source_bytes = (capsule_path / "source_bars.json").read_bytes()
    if type(manifest.get("member")) is not dict or manifest["member"].get("sha256") != _sha(source_bytes) or manifest["member"].get("byte_length") != len(source_bytes):
        raise ContractValidationError("source capsule member hash/length mismatch")
    if source_payload.get("stage") != expected_stage.value or manifest.get("stage") != expected_stage.value:
        raise ContractValidationError("source capsule stage mismatch")
    if source_payload.get("source_bundle_id") != expected_source.source_bundle_id or source_payload.get("source_bars_sha256") != expected_source.source_bars_sha256:
        raise ContractValidationError("source capsule parent mismatch")
    bars_raw = source_payload.get("bars")
    if type(bars_raw) is not list:
        raise ContractValidationError("source capsule bars must be a list")
    # Reuse the strict source-bar parser by constructing the same field shape.
    bars: list[SourceBar] = []
    previous = None
    for index, raw in enumerate(bars_raw):
        if type(raw) is not dict or set(raw) != _BAR_KEYS:
            raise ContractValidationError(f"source capsule bar {index} schema mismatch")
        try:
            bar = SourceBar(
                open_time=_timestamp(raw["open_time"], field_name=f"capsule.bars[{index}].open_time"),
                closed_at=_timestamp(raw["closed_at"], field_name=f"capsule.bars[{index}].closed_at"),
                open=raw["open"], high=raw["high"], low=raw["low"], close=raw["close"], volume=raw["volume"], bar_id=raw["bar_id"],
            )
        except (ContractValidationError, TypeError, ValueError) as exc:
            raise ContractValidationError(f"invalid source capsule bar {index}") from exc
        if previous is not None and bar.open_time != previous.open_time + __import__("datetime").timedelta(days=1):
            raise ContractValidationError("source capsule cadence mismatch")
        bars.append(bar)
        previous = bar
    split = _timestamp(source_payload.get("split_boundary"), field_name="split_boundary")
    commit = source_payload.get("implementation_commit")
    if expected_implementation_commit is not None and commit != expected_implementation_commit:
        raise ContractValidationError("source capsule implementation commit mismatch")
    capsule = SourceCapsule(
        stage=expected_stage,
        source_bundle_id=expected_source.source_bundle_id,
        source_bars_sha256=expected_source.source_bars_sha256,
        source_row_count=source_payload.get("source_row_count"),
        split_boundary=split,
        implementation_commit=commit,
        bars=tuple(bars),
    )
    if expected_stage is CapsuleStage.SEALED_HOLDOUT:
        if len(capsule.bars) != expected_source.source_row_count:
            raise ContractValidationError("sealed source capsule is incomplete")
        if capsule.bars[-1].closed_at != SOURCE_WINDOW_END:
            raise ContractValidationError("sealed source capsule does not reach the requested end")
    elif len(capsule.bars) >= expected_source.source_row_count:
        raise ContractValidationError("development source capsule contains the full sealed source")
    if capsule.capsule_id != capsule_path.name or manifest.get("capsule_id") != capsule.capsule_id:
        raise ContractValidationError("source capsule identity mismatch")
    expected_manifest = _manifest_payload(capsule, _sha(source_bytes), len(source_bytes))
    if manifest != expected_manifest:
        raise ContractValidationError("source capsule manifest semantic mismatch")
    return capsule


__all__ = [
    "build_source_capsules",
    "load_capsule",
    "load_frozen_source",
    "publish_source_capsule",
]
