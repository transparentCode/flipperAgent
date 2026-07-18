"""Verified frozen-file and daily-bar identity primitives for SR research."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.domain.identity import canonical_json, utc_isoformat
from libs.models.sr.research.artifacts.path_safety import (
    reject_symlink_components,
    require_regular_file,
)
from libs.models.sr.research.config.identities import ContentIdentity

from .contracts import SourceBar


def _description(value: Any) -> str:
    if type(value) is not str or not value.strip():
        raise ContractValidationError("description must be a non-empty string")
    return value


def read_verified_frozen_file(
    path: str | Path,
    *,
    identity: ContentIdentity,
    description: str,
) -> bytes:
    """Read one immutable regular file after exact identity verification."""

    description = _description(description)
    if type(identity) is not ContentIdentity:
        raise ContractValidationError("identity must be exactly ContentIdentity")
    try:
        member_path = Path(path)
        reject_symlink_components(member_path, description=description)
        require_regular_file(member_path, description=description)
        data = member_path.read_bytes()
    except ContractValidationError:
        raise
    except (OSError, TypeError, UnicodeError, ValueError) as exc:
        raise ContractValidationError(f"{description} cannot be read: {path}") from exc
    if len(data) != identity.byte_length or sha256(data).hexdigest() != identity.sha256:
        raise ContractValidationError(f"{description} identity mismatch")
    return data


def source_bar_payload(bar: SourceBar) -> dict[str, object]:
    """Return one daily source bar's canonical identity payload."""

    if type(bar) is not SourceBar:
        raise ContractValidationError("bar must be exactly SourceBar")
    return {
        "open_time": utc_isoformat(bar.open_time),
        "closed_at": utc_isoformat(bar.closed_at),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "bar_id": bar.bar_id,
    }


def _validated_bars(bars: tuple[SourceBar, ...]) -> tuple[SourceBar, ...]:
    if type(bars) is not tuple or not bars:
        raise ContractValidationError("bars must be a non-empty tuple")
    if any(type(bar) is not SourceBar for bar in bars):
        raise ContractValidationError("bars must contain exact SourceBar values")
    return bars


def source_bars_sha256(bars: tuple[SourceBar, ...]) -> str:
    """Hash ordered canonical payloads for a non-empty frozen daily source."""

    return sha256(
        canonical_json([source_bar_payload(bar) for bar in _validated_bars(bars)]).encode("utf-8")
    ).hexdigest()


def source_grid_sha256(bars: tuple[SourceBar, ...]) -> str:
    """Hash ordered daily open-time UTC strings for a frozen source grid."""

    return sha256(
        canonical_json([utc_isoformat(bar.open_time) for bar in _validated_bars(bars)]).encode(
            "utf-8"
        )
    ).hexdigest()


__all__ = [
    "read_verified_frozen_file",
    "source_bar_payload",
    "source_bars_sha256",
    "source_grid_sha256",
]
