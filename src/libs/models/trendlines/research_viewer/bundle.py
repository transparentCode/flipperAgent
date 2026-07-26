"""Canonical two-file bundles for the package-local research viewer."""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from libs.models.trendlines.contracts.identity import canonical_hash

from .contracts import (
    VIEWER_BUNDLE_SCHEMA_VERSION,
    VIEWER_BUNDLE_SEMANTICS_VERSION,
    TrendlineViewerContractError,
    exact_keys,
    require_sha256,
)
from .payload import validate_viewer_payload


_MEMBERS = frozenset({"manifest.json", "chart_payload.json"})


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise TrendlineViewerContractError("bundle contains non-canonical JSON data") from exc
    return (encoded + "\n").encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {value}")


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise TrendlineViewerContractError(
            f"{path.name} must be a regular non-symlink file"
        )
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise TrendlineViewerContractError(f"invalid JSON member {path.name}") from exc
    if not isinstance(value, dict):
        raise TrendlineViewerContractError(f"{path.name} must contain an object")
    return value, raw


def _regular_file(path: Path, field_name: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise TrendlineViewerContractError(
            f"{field_name} must be a regular non-symlink file"
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise TrendlineViewerContractError(f"cannot read {field_name}") from exc


def _bundle_identity(*, payload_id: str, members: list[dict[str, Any]]) -> str:
    return canonical_hash(
        {
            "schema_version": VIEWER_BUNDLE_SCHEMA_VERSION,
            "payload_id": payload_id,
            "members": members,
            "semantics_version": VIEWER_BUNDLE_SEMANTICS_VERSION,
        },
        semantics_version=VIEWER_BUNDLE_SEMANTICS_VERSION,
    )


def validate_viewer_bundle(bundle_path: str | Path) -> dict[str, Any]:
    """Validate exact files, canonical bytes, hashes, and payload semantics."""

    original = Path(bundle_path)
    if original.is_symlink():
        raise TrendlineViewerContractError("viewer bundle path must not be a symlink")
    bundle = original.resolve()
    if not bundle.is_dir():
        raise TrendlineViewerContractError("viewer bundle path must be a directory")
    entries = tuple(bundle.iterdir())
    if {entry.name for entry in entries} != _MEMBERS:
        raise TrendlineViewerContractError("viewer bundle contains unexpected files")
    manifest, manifest_bytes = _read_json(bundle / "manifest.json")
    payload, payload_bytes = _read_json(bundle / "chart_payload.json")
    if manifest_bytes != _canonical_json_bytes(manifest):
        raise TrendlineViewerContractError("manifest is not canonical JSON")
    if payload_bytes != _canonical_json_bytes(payload):
        raise TrendlineViewerContractError("chart_payload.json is not canonical JSON")
    exact_keys(
        manifest,
        {"schema_version", "bundle_id", "payload_id", "members"},
        "viewer manifest",
    )
    if manifest["schema_version"] != VIEWER_BUNDLE_SCHEMA_VERSION:
        raise TrendlineViewerContractError("unsupported viewer bundle schema")
    require_sha256(manifest["bundle_id"], "manifest.bundle_id")
    require_sha256(manifest["payload_id"], "manifest.payload_id")
    members = manifest["members"]
    if not isinstance(members, list) or len(members) != 1:
        raise TrendlineViewerContractError("viewer manifest must contain one payload member")
    member = members[0]
    exact_keys(member, {"name", "sha256", "byte_length"}, "viewer manifest member")
    if member["name"] != "chart_payload.json":
        raise TrendlineViewerContractError("viewer member name is invalid")
    require_sha256(member["sha256"], "manifest member sha256")
    if type(member["byte_length"]) is not int or member["byte_length"] < 0:
        raise TrendlineViewerContractError("manifest member byte_length is invalid")
    if member["byte_length"] != len(payload_bytes):
        raise TrendlineViewerContractError("viewer payload byte length mismatch")
    if member["sha256"] != sha256(payload_bytes).hexdigest():
        raise TrendlineViewerContractError("viewer payload member hash mismatch")
    validated_payload = validate_viewer_payload(payload)
    if manifest["payload_id"] != validated_payload["payload_id"]:
        raise TrendlineViewerContractError("manifest payload_id differs from payload")
    if _bundle_identity(payload_id=manifest["payload_id"], members=members) != manifest["bundle_id"]:
        raise TrendlineViewerContractError("bundle_id does not match manifest content")
    return validated_payload


def write_viewer_bundle(
    payload: Mapping[str, Any],
    output_directory: str | Path,
) -> Path:
    """Write one explicit, exact two-file viewer bundle."""

    validated = validate_viewer_payload(dict(payload))
    destination = Path(output_directory)
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise TrendlineViewerContractError("viewer bundle destination must be a real directory")
        if any(destination.iterdir()):
            raise TrendlineViewerContractError("viewer bundle destination must be empty")
    else:
        destination.mkdir(parents=True, exist_ok=False)
    payload_bytes = _canonical_json_bytes(validated)
    members = [
        {
            "name": "chart_payload.json",
            "sha256": sha256(payload_bytes).hexdigest(),
            "byte_length": len(payload_bytes),
        }
    ]
    manifest = {
        "schema_version": VIEWER_BUNDLE_SCHEMA_VERSION,
        "bundle_id": _bundle_identity(
            payload_id=validated["payload_id"],
            members=members,
        ),
        "payload_id": validated["payload_id"],
        "members": members,
    }
    (destination / "chart_payload.json").write_bytes(payload_bytes)
    (destination / "manifest.json").write_bytes(_canonical_json_bytes(manifest))
    validate_viewer_bundle(destination)
    return destination


def read_viewer_bundle(bundle_path: str | Path) -> dict[str, Any]:
    """Read and validate one viewer bundle, returning its chart payload."""

    return validate_viewer_bundle(bundle_path)


__all__ = [
    "read_viewer_bundle",
    "validate_viewer_bundle",
    "write_viewer_bundle",
]
