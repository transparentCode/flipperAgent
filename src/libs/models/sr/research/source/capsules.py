"""Immutable source-capsule contract shared by SR research studies."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import re
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash, require_utc, utc_isoformat

from .contracts import SourceBar


SCHEMA_VERSION = "1.0"
_HASH_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


class CapsuleStage(str, Enum):
    """The immutable source window represented by a capsule."""

    DEVELOPMENT = "development"
    SEALED_HOLDOUT = "sealed_holdout"


def _string(value: Any, *, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _hash(value: Any, *, field_name: str) -> str:
    value = _string(value, field_name=field_name)
    if _HASH_RE.fullmatch(value) is None:
        raise ContractValidationError(f"{field_name} must be a lowercase SHA-256 hex string")
    return value


def _timestamp(value: Any, *, field_name: str) -> datetime:
    return require_utc(value, field_name=field_name)


def _integer(value: Any, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or type(value) is not int or value < minimum:
        raise ContractValidationError(f"{field_name} must be an integer >= {minimum}")
    return value


def _bar_payload(bar: SourceBar) -> dict[str, Any]:
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


@dataclass(frozen=True)
class SourceCapsule:
    """Content-addressed prefix or sealed source capsule."""

    stage: CapsuleStage
    source_bundle_id: str
    source_bars_sha256: str
    source_row_count: int
    split_boundary: datetime
    implementation_commit: str
    bars: tuple[SourceBar, ...]
    capsule_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.stage) is not CapsuleStage:
            try:
                stage = CapsuleStage(self.stage)
            except (TypeError, ValueError) as exc:
                raise ContractValidationError("invalid source capsule stage") from exc
            object.__setattr__(self, "stage", stage)
        object.__setattr__(self, "source_bundle_id", _hash(self.source_bundle_id, field_name="source_bundle_id"))
        object.__setattr__(self, "source_bars_sha256", _hash(self.source_bars_sha256, field_name="source_bars_sha256"))
        object.__setattr__(self, "source_row_count", _integer(self.source_row_count, field_name="source_row_count", minimum=1))
        split = _timestamp(self.split_boundary, field_name="split_boundary")
        if split.hour or split.minute or split.second or split.microsecond:
            raise ContractValidationError("split_boundary must be a UTC daily boundary")
        object.__setattr__(self, "split_boundary", split)
        commit = _string(self.implementation_commit, field_name="implementation_commit")
        if _COMMIT_RE.fullmatch(commit) is None:
            raise ContractValidationError("implementation_commit must be a git SHA")
        object.__setattr__(self, "implementation_commit", commit)
        if type(self.bars) is not tuple or not self.bars:
            raise ContractValidationError("capsule bars must be a non-empty tuple")
        if any(type(bar) is not SourceBar for bar in self.bars):
            raise ContractValidationError("capsule bars must contain SourceBar values")
        previous: SourceBar | None = None
        ids: set[str] = set()
        for index, bar in enumerate(self.bars):
            if bar.bar_id in ids:
                raise ContractValidationError(f"duplicate source bar_id at index {index}")
            ids.add(bar.bar_id)
            if previous is not None:
                if bar.open_time != previous.open_time + timedelta(days=1):
                    raise ContractValidationError("capsule bars must have exact daily cadence")
                if bar.closed_at <= previous.closed_at:
                    raise ContractValidationError("capsule closed_at values must increase")
            previous = bar
        if self.stage is CapsuleStage.DEVELOPMENT:
            if any(bar.closed_at >= split for bar in self.bars):
                raise ContractValidationError("development capsule contains holdout bars")
        object.__setattr__(self, "capsule_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "stage": self.stage.value,
            "source_bundle_id": self.source_bundle_id,
            "source_bars_sha256": self.source_bars_sha256,
            "source_row_count": self.source_row_count,
            "split_boundary": utc_isoformat(self.split_boundary),
            "implementation_commit": self.implementation_commit,
            "bars": [_bar_payload(bar) for bar in self.bars],
        }


__all__ = ["CapsuleStage", "SourceCapsule"]
