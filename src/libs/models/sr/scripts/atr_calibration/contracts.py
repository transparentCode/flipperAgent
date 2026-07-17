"""Immutable source and replay contracts for SR-V1.6."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import math
from pathlib import Path, PurePath
import re
from typing import Any

from libs.models.sr.domain.contracts import (
    ClosedBar,
    ContractValidationError,
    SRSnapshot,
    SRState,
)
from libs.models.sr.domain.identity import deterministic_hash, require_utc, utc_isoformat
from libs.models.sr.evaluation.contracts import SREvaluationTrace
from libs.models.sr.evaluation.diagnostics import SRDiagnostics
from libs.models.sr.research.source.contracts import SourceBar


SCHEMA_VERSION = "1.0"
ATR_IMPLEMENTATION = "libs.features.indicators.volatility.atr.ATR"
ATR_IMPLEMENTATION_CONTRACT = "true_range_sma_seed_then_wilder_recursion_v1"
_HASH_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")


class CapsuleStage(str, Enum):
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


def _number(value: Any, *, field_name: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{field_name} must be finite") from exc
    if not math.isfinite(result):
        raise ContractValidationError(f"{field_name} must be finite")
    if result == 0.0:
        result = 0.0
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{field_name} must be >= {minimum}")
    return result


def _relative_path(value: Any, *, field_name: str) -> str:
    value = _string(value, field_name=field_name)
    normalized = value.replace("\\", "/")
    if Path(value).is_absolute() or normalized.startswith("/") or ".." in PurePath(normalized).parts:
        raise ContractValidationError(f"{field_name} must be a safe relative path")
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
        payload = self.identity_payload()
        object.__setattr__(self, "capsule_id", deterministic_hash(payload))

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


@dataclass(frozen=True)
class CandidateReplay:
    """One full causal SR replay for one ATR candidate."""

    period: int
    reference_period: int
    common_start_index: int
    model_bars: tuple[ClosedBar, ...]
    reference_atr: tuple[float, ...]
    initial_state: SRState
    final_state: SRState
    snapshots: tuple[SRSnapshot, ...]
    trace: SREvaluationTrace
    diagnostics: SRDiagnostics

    def __post_init__(self) -> None:
        object.__setattr__(self, "period", _integer(self.period, field_name="period", minimum=1))
        object.__setattr__(self, "reference_period", _integer(self.reference_period, field_name="reference_period", minimum=1))
        object.__setattr__(self, "common_start_index", _integer(self.common_start_index, field_name="common_start_index", minimum=0))
        if type(self.model_bars) is not tuple or not self.model_bars:
            raise ContractValidationError("model_bars must be a non-empty tuple")
        if any(type(bar) is not ClosedBar for bar in self.model_bars):
            raise ContractValidationError("model_bars must contain ClosedBar values")
        if type(self.reference_atr) is not tuple or len(self.reference_atr) != len(self.model_bars):
            raise ContractValidationError("reference_atr must align to model_bars")
        if any(_number(value, field_name="reference_atr", minimum=0.0) <= 0 for value in self.reference_atr):
            raise ContractValidationError("reference_atr values must be positive")
        for field_name, expected_type in (("initial_state", SRState), ("final_state", SRState), ("trace", SREvaluationTrace), ("diagnostics", SRDiagnostics)):
            if type(getattr(self, field_name)) is not expected_type:
                raise ContractValidationError(f"{field_name} has invalid type")
        if type(self.snapshots) is not tuple or any(type(item) is not SRSnapshot for item in self.snapshots):
            raise ContractValidationError("snapshots must contain SRSnapshot values")
        if len(self.snapshots) != len(self.model_bars):
            raise ContractValidationError("snapshots must align to model_bars")
        if self.initial_state.state_key != self.model_bars[0].state_key:
            raise ContractValidationError("initial state does not own model bars")
        if self.final_state.state_key != self.initial_state.state_key:
            raise ContractValidationError("final state key changed during replay")
        if self.trace.state_key != self.initial_state.state_key:
            raise ContractValidationError("trace state key does not reconcile")


__all__ = [
    "ATR_IMPLEMENTATION",
    "ATR_IMPLEMENTATION_CONTRACT",
    "CandidateReplay",
    "CapsuleStage",
    "SCHEMA_VERSION",
    "SourceBar",
    "SourceCapsule",
]
