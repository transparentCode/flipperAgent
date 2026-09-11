"""Durable, atomic claims for protected research evidence identities."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 2


def _validate_identity(identity: str) -> None:
    if not isinstance(identity, str) or len(identity) != 64:
        raise ValueError("consumption identity must be a 64-character SHA-256")
    try:
        int(identity, 16)
    except ValueError as exc:
        raise ValueError("consumption identity must be hexadecimal") from exc


def _marker(root: Path, identity: str) -> Path:
    return root / f".sr_v2-consumption-{identity}.json"


def _sync_directory(root: Path) -> None:
    try:
        directory_fd = os.open(root, os.O_RDONLY)
    except OSError:
        directory_fd = None
    if directory_fd is not None:
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def _read_marker(marker: Path, identity: str) -> dict[str, Any]:
    try:
        existing = json.loads(marker.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("protected consumption marker exists but is unreadable") from exc
    if existing.get("consumption_identity") != identity:
        raise ValueError("protected consumption marker identity mismatch")
    return existing


def _write_replaced(marker: Path, payload: Mapping[str, Any]) -> None:
    root = marker.parent
    temporary_fd, temporary_name = tempfile.mkstemp(
        prefix=f".{marker.name}.",
        suffix=".tmp",
        dir=root,
    )
    try:
        with os.fdopen(temporary_fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, marker)
        _sync_directory(root)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def claim_consumption(
    evidence_root: str | Path,
    *,
    identity: str,
    metadata: Mapping[str, Any],
) -> Path:
    """Atomically claim an identity, refusing reuse across paths/processes."""

    _validate_identity(identity)
    root = Path(evidence_root)
    root.mkdir(parents=True, exist_ok=True)
    marker = _marker(root, identity)
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "consumption_identity": identity,
        "status": "claimed",
        "metadata": dict(metadata),
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str) + "\n").encode("utf-8")
    try:
        with marker.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        _sync_directory(root)
        return marker
    except FileExistsError:
        _read_marker(marker, identity)
        raise ValueError("protected holdout consumption identity was already evaluated") from None


def verify_consumption_claim(
    evidence_root: str | Path,
    *,
    identity: str,
    claim: str | Path,
) -> Path:
    """Validate the single-use claim token returned by evaluation."""

    _validate_identity(identity)
    root = Path(evidence_root)
    expected = _marker(root, identity)
    supplied = Path(claim)
    try:
        same_path = supplied.resolve() == expected.resolve()
    except OSError:
        same_path = supplied.absolute() == expected.absolute()
    if not same_path:
        raise ValueError("consumption claim does not match protected identity root")
    if not expected.is_file():
        raise ValueError("protected consumption claim is missing")
    payload = _read_marker(expected, identity)
    if payload.get("status") != "claimed":
        raise ValueError("protected holdout consumption identity was already evaluated")
    return expected


def finalize_consumption(
    evidence_root: str | Path,
    *,
    identity: str,
    claim: str | Path,
    artifact_id: str,
    output_path: str | Path,
) -> Path:
    """Atomically transition one claimed holdout to its persisted artifact."""

    marker = verify_consumption_claim(
        evidence_root,
        identity=identity,
        claim=claim,
    )
    payload = _read_marker(marker, identity)
    payload.update(
        {
            "status": "persisted",
            "artifact_id": artifact_id,
            "output_path": str(Path(output_path)),
        }
    )
    _write_replaced(marker, payload)
    return marker


__all__ = ["claim_consumption", "finalize_consumption", "verify_consumption_claim"]
