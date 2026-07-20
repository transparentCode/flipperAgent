"""Immutable contracts for the V2.4 causal relative-salience study."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
import math
import re
from typing import Any

from libs.models.sr.domain import CandidateLevel, ContractValidationError, ZoneSide
from libs.models.sr.domain.identity import canonical_json, deterministic_hash, require_utc, utc_isoformat
from libs.models.sr.research.metrics.first_touch import FirstTouchOutcome

from .config import COHORTS


_HASH = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40,64}")


def _text(value: Any, *, field: str) -> str:
    if type(value) is not str or not value:
        raise ContractValidationError(f"{field} must be a non-empty string")
    return value


def _hash(value: Any, *, field: str) -> str:
    value = _text(value, field=field)
    if _HASH.fullmatch(value) is None:
        raise ContractValidationError(f"{field} must be a lowercase SHA-256 hex string")
    return value


def _commit(value: Any, *, field: str) -> str:
    value = _text(value, field=field)
    if _COMMIT.fullmatch(value) is None:
        raise ContractValidationError(f"{field} must be a git SHA")
    return value


def _integer(value: Any, *, field: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ContractValidationError(f"{field} must be an integer >= {minimum}")
    return value


def _number(value: Any, *, field: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{field} must be finite") from exc
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ContractValidationError(f"{field} must be finite")
    return 0.0 if result == 0.0 else result


def _timestamp(value: Any, *, field: str) -> datetime:
    try:
        return require_utc(value, field_name=field)
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise ContractValidationError(f"{field} must be a UTC-aware timestamp") from exc


@dataclass(frozen=True)
class IntervalBar:
    """A study-local immutable source bar supporting 1d and 12h cadence."""

    open_time: datetime
    closed_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_id: str

    def __post_init__(self) -> None:
        open_time = _timestamp(self.open_time, field="interval_bar.open_time")
        closed_at = _timestamp(self.closed_at, field="interval_bar.closed_at")
        if closed_at <= open_time:
            raise ContractValidationError("interval_bar.closed_at must be after open_time")
        values = tuple(
            _number(value, field=f"interval_bar.{name}", minimum=0.0)
            for name, value in (
                ("open", self.open), ("high", self.high), ("low", self.low),
                ("close", self.close), ("volume", self.volume),
            )
        )
        open_value, high, low, close, volume = values
        if min(open_value, high, low, close) <= 0.0:
            raise ContractValidationError("interval_bar OHLC values must be positive")
        if low > high or not low <= open_value <= high or not low <= close <= high:
            raise ContractValidationError("interval_bar OHLC values are incoherent")
        object.__setattr__(self, "open_time", open_time)
        object.__setattr__(self, "closed_at", closed_at)
        for name, value in zip(("open", "high", "low", "close", "volume"), values):
            object.__setattr__(self, name, value)
        object.__setattr__(self, "bar_id", _text(self.bar_id, field="interval_bar.bar_id"))

    def to_payload(self) -> dict[str, object]:
        return {
            "open_time": utc_isoformat(self.open_time), "closed_at": utc_isoformat(self.closed_at),
            "open": self.open, "high": self.high, "low": self.low, "close": self.close,
            "volume": self.volume, "bar_id": self.bar_id,
        }


def bars_sha256(bars: tuple[IntervalBar, ...]) -> str:
    if type(bars) is not tuple or not bars or any(type(bar) is not IntervalBar for bar in bars):
        raise ContractValidationError("interval bars must be a non-empty tuple")
    return sha256(canonical_json([bar.to_payload() for bar in bars]).encode()).hexdigest()


def grid_sha256(bars: tuple[IntervalBar, ...]) -> str:
    if type(bars) is not tuple or not bars or any(type(bar) is not IntervalBar for bar in bars):
        raise ContractValidationError("interval bars must be a non-empty tuple")
    return sha256(canonical_json([utc_isoformat(bar.open_time) for bar in bars]).encode()).hexdigest()


@dataclass(frozen=True)
class SourceMember:
    asset: str
    timeframe: str
    history_bars: tuple[IntervalBar, ...]
    fresh_bars: tuple[IntervalBar, ...]
    provider_calls: int
    source_kind: str
    bars_hash: str = field(init=False)
    grid_hash: str = field(init=False)

    def __post_init__(self) -> None:
        key = (self.asset, self.timeframe)
        if key not in COHORTS:
            raise ContractValidationError("source member is outside V2.4 cohort scope")
        if type(self.history_bars) is not tuple or not self.history_bars or any(type(bar) is not IntervalBar for bar in self.history_bars):
            raise ContractValidationError("source history bars must be a non-empty IntervalBar tuple")
        if type(self.fresh_bars) is not tuple or any(type(bar) is not IntervalBar for bar in self.fresh_bars):
            raise ContractValidationError("source fresh bars must be an IntervalBar tuple")
        if type(self.provider_calls) is not int or self.provider_calls not in (0, 1):
            raise ContractValidationError("source member provider_calls must be zero or one")
        if self.source_kind not in {"frozen_history", "provider", "synthetic"}:
            raise ContractValidationError("source member source_kind is invalid")
        if (self.source_kind == "provider") != (self.provider_calls == 1):
            raise ContractValidationError("source member kind/call count mismatch")
        if self.provider_calls == 1:
            expected_count = 181 if self.timeframe == "1d" else 362
            cadence = timedelta(days=1) if self.timeframe == "1d" else timedelta(hours=12)
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            end = datetime(2026, 7, 1, tzinfo=timezone.utc)
            if len(self.fresh_bars) != expected_count or not self.fresh_bars:
                raise ContractValidationError("provider source member row count is invalid")
            for index, bar in enumerate(self.fresh_bars):
                expected_open = start + index * cadence
                if bar.open_time != expected_open or bar.closed_at != expected_open + cadence:
                    raise ContractValidationError("provider source member grid is invalid")
            if self.fresh_bars[-1].closed_at != end:
                raise ContractValidationError("provider source member cutoff is invalid")
        bars = self.bars
        if any(later.open_time <= earlier.open_time or later.closed_at <= earlier.closed_at for earlier, later in zip(bars, bars[1:])):
            raise ContractValidationError("source member bars must be strictly ordered")
        if len({bar.bar_id for bar in bars}) != len(bars):
            raise ContractValidationError("source member bar IDs must be unique")
        object.__setattr__(self, "bars_hash", bars_sha256(bars))
        object.__setattr__(self, "grid_hash", grid_sha256(bars))

    @property
    def bars(self) -> tuple[IntervalBar, ...]:
        return (*self.history_bars, *self.fresh_bars)

    def to_payload(self) -> dict[str, object]:
        return {
            "asset": self.asset, "timeframe": self.timeframe,
            "history_bars": [bar.to_payload() for bar in self.history_bars],
            "fresh_bars": [bar.to_payload() for bar in self.fresh_bars],
            "provider_calls": self.provider_calls, "source_kind": self.source_kind,
            "bars_sha256": self.bars_hash, "grid_sha256": self.grid_hash,
        }


@dataclass(frozen=True)
class SourceBundle:
    implementation_commit: str
    config_hash: str
    members: tuple[SourceMember, ...]
    bundle_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "implementation_commit", _commit(self.implementation_commit, field="source_bundle.implementation_commit"))
        object.__setattr__(self, "config_hash", _hash(self.config_hash, field="source_bundle.config_hash"))
        if type(self.members) is not tuple or tuple((member.asset, member.timeframe) for member in self.members) != COHORTS:
            raise ContractValidationError("source bundle members must use canonical cohort order")
        if any(type(member) is not SourceMember for member in self.members):
            raise ContractValidationError("source bundle member types are invalid")
        calls = tuple(member.provider_calls for member in self.members)
        if calls not in {tuple(0 for _ in self.members), tuple(1 for _ in self.members)}:
            raise ContractValidationError("source bundle cannot mix partial provider acquisition")
        object.__setattr__(self, "bundle_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, object]:
        entries = {
            f"{member.asset}_{member.timeframe}.json": (canonical_json(member.to_payload()) + "\n").encode("utf-8")
            for member in self.members
        }
        return {"schema_version": "1.0", "stage": "relative_salience_rank_source", "implementation_commit": self.implementation_commit, "config_hash": self.config_hash, "assets": [member.to_payload() for member in self.members], "members": [{"name": name, "sha256": sha256(entries[name]).hexdigest(), "byte_length": len(entries[name])} for name in entries]}

    def to_payload(self) -> dict[str, object]:
        return {**self.identity_payload(), "bundle_id": self.bundle_id}


class CaseStatus(str, Enum):
    NO_TOUCH = "NO_TOUCH"
    RIGHT_CENSORED = "RIGHT_CENSORED"
    COMPLETED = "COMPLETED"


class Quartile(str, Enum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"


class RankDisposition(str, Enum):
    RELATIVE_SALIENCE_SUPPORTED_FOR_SHADOW = "RELATIVE_SALIENCE_SUPPORTED_FOR_SHADOW"
    RELATIVE_SALIENCE_NOT_SUPPORTED = "RELATIVE_SALIENCE_NOT_SUPPORTED"
    INSUFFICIENT_SOURCE_DENSITY = "INSUFFICIENT_SOURCE_DENSITY"
    INSUFFICIENT_RANK_EVIDENCE = "INSUFFICIENT_RANK_EVIDENCE"


def candidate_payload(candidate: CandidateLevel) -> dict[str, object]:
    if type(candidate) is not CandidateLevel:
        raise ContractValidationError("candidate must be exactly CandidateLevel")
    return {"candidate_id": candidate.candidate_id, "state_key": {"venue": candidate.state_key.venue, "symbol": candidate.state_key.symbol, "timeframe": candidate.state_key.timeframe}, "side": candidate.side.value, "geometry": {"center": candidate.geometry.center, "half_width": candidate.geometry.half_width, "lower_bound": candidate.geometry.lower_bound, "upper_bound": candidate.geometry.upper_bound}, "source": candidate.source, "formed_at": utc_isoformat(candidate.formed_at), "available_at": utc_isoformat(candidate.available_at), "atr_at_creation": candidate.atr_at_creation}


def outcome_payload(outcome: FirstTouchOutcome | None) -> dict[str, object] | None:
    if outcome is not None and type(outcome) is not FirstTouchOutcome:
        raise ContractValidationError("outcome must be exactly FirstTouchOutcome")
    return None if outcome is None else outcome.to_payload()


@dataclass(frozen=True)
class ControlRecord:
    """One prior-close naïve band; topology is fixed SUPPORT then RESISTANCE."""

    side: ZoneSide
    candidate: CandidateLevel
    status: CaseStatus
    outcome: FirstTouchOutcome | None

    def __post_init__(self) -> None:
        if type(self.side) is not ZoneSide or type(self.candidate) is not CandidateLevel or self.candidate.side is not self.side or type(self.status) is not CaseStatus:
            raise ContractValidationError("control record identity is invalid")
        if self.status is CaseStatus.NO_TOUCH and self.outcome is not None:
            raise ContractValidationError("no-touch control cannot carry an outcome")
        if self.status is not CaseStatus.NO_TOUCH and type(self.outcome) is not FirstTouchOutcome:
            raise ContractValidationError("resolved control requires first-touch outcome")

    def to_payload(self) -> dict[str, object]:
        return {"side": self.side.value, "candidate": candidate_payload(self.candidate), "status": self.status.value, "outcome": outcome_payload(self.outcome)}


@dataclass(frozen=True)
class RankCase:
    asset: str
    timeframe: str
    confirmation_index: int
    candidate: CandidateLevel
    raw_salience_atr: float
    relative_salience_rank: float
    prior_count: int
    quartile: Quartile
    real_status: CaseStatus
    real_outcome: FirstTouchOutcome | None
    controls: tuple[ControlRecord, ...]
    same_side_control_outcome: FirstTouchOutcome | None
    paired_excess_quality_atr: float | None
    month: str
    case_id: str = field(init=False)

    def __post_init__(self) -> None:
        if (self.asset, self.timeframe) not in COHORTS or type(self.confirmation_index) is not int or self.confirmation_index <= 0:
            raise ContractValidationError("rank case identity is invalid")
        if type(self.candidate) is not CandidateLevel or self.candidate.state_key.symbol != self.asset or self.candidate.state_key.timeframe != self.timeframe:
            raise ContractValidationError("rank case candidate identity is invalid")
        object.__setattr__(self, "raw_salience_atr", _number(self.raw_salience_atr, field="rank_case.raw_salience_atr", minimum=0.0))
        rank = _number(self.relative_salience_rank, field="rank_case.relative_salience_rank", minimum=0.0)
        if rank > 1.0:
            raise ContractValidationError("rank case relative_salience_rank must be in [0, 1]")
        object.__setattr__(self, "relative_salience_rank", rank)
        object.__setattr__(self, "prior_count", _integer(self.prior_count, field="rank_case.prior_count", minimum=1))
        if type(self.quartile) is not Quartile or type(self.real_status) is not CaseStatus:
            raise ContractValidationError("rank case enum fields are invalid")
        if self.real_status is CaseStatus.NO_TOUCH and self.real_outcome is not None:
            raise ContractValidationError("no-touch case cannot carry a real outcome")
        if self.real_status is not CaseStatus.NO_TOUCH and type(self.real_outcome) is not FirstTouchOutcome:
            raise ContractValidationError("resolved case requires real outcome")
        if type(self.controls) is not tuple or tuple(item.side for item in self.controls) != (ZoneSide.SUPPORT, ZoneSide.RESISTANCE) or any(type(item) is not ControlRecord for item in self.controls):
            raise ContractValidationError("rank case requires exactly ordered support/resistance controls")
        same_side = next(item for item in self.controls if item.side is self.candidate.side)
        if same_side.outcome is not self.same_side_control_outcome:
            raise ContractValidationError("same-side control outcome does not match topology")
        if self.real_status is CaseStatus.COMPLETED and self.same_side_control_outcome is not None:
            if not self.same_side_control_outcome.completed or self.paired_excess_quality_atr is None:
                raise ContractValidationError("completed pair requires completed same-side control and pair excess")
            expected = self.real_outcome.quality_reference_atr - self.same_side_control_outcome.quality_reference_atr
            actual = _number(self.paired_excess_quality_atr, field="rank_case.paired_excess_quality_atr")
            if actual != expected:
                raise ContractValidationError("rank case pair excess does not reconcile")
            object.__setattr__(self, "paired_excess_quality_atr", actual)
        elif self.paired_excess_quality_atr is not None:
            raise ContractValidationError("uncompleted rank case cannot carry pair excess")
        if type(self.month) is not str or not re.fullmatch(r"\d{4}-\d{2}", self.month):
            raise ContractValidationError("rank case month is invalid")
        object.__setattr__(self, "case_id", deterministic_hash(self.causal_identity_payload()))

    @property
    def completed(self) -> bool:
        return self.real_status is CaseStatus.COMPLETED and self.same_side_control_outcome is not None and self.same_side_control_outcome.completed and self.paired_excess_quality_atr is not None

    def causal_identity_payload(self) -> dict[str, object]:
        return {"asset": self.asset, "timeframe": self.timeframe, "confirmation_index": self.confirmation_index, "candidate": candidate_payload(self.candidate), "raw_salience_atr": self.raw_salience_atr, "relative_salience_rank": self.relative_salience_rank, "prior_count": self.prior_count, "quartile": self.quartile.value, "month": self.month, "controls": [{"side": item.side.value, "candidate": candidate_payload(item.candidate)} for item in self.controls]}

    def to_payload(self) -> dict[str, object]:
        return {**self.causal_identity_payload(), "case_id": self.case_id, "real_status": self.real_status.value, "real_outcome": outcome_payload(self.real_outcome), "controls": [item.to_payload() for item in self.controls], "same_side_control_outcome": outcome_payload(self.same_side_control_outcome), "paired_excess_quality_atr": self.paired_excess_quality_atr}


@dataclass(frozen=True)
class Gate:
    name: str
    value: float
    lower_90: float | None
    upper_90: float | None
    passed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, field="gate.name"))
        object.__setattr__(self, "value", _number(self.value, field="gate.value"))
        for name in ("lower_90", "upper_90"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _number(value, field=f"gate.{name}"))
        if type(self.passed) is not bool:
            raise ContractValidationError("gate.passed must be boolean")

    def to_payload(self) -> dict[str, object]:
        return {"name": self.name, "value": self.value, "lower_90": self.lower_90, "upper_90": self.upper_90, "passed": self.passed}


@dataclass(frozen=True)
class RankStudy:
    implementation_commit: str
    config_hash: str
    source_bundle_id: str
    cases: tuple[RankCase, ...]
    gates: tuple[Gate, ...]
    disposition: RankDisposition
    metrics: dict[str, object]
    study_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "implementation_commit", _commit(self.implementation_commit, field="study.implementation_commit"))
        object.__setattr__(self, "config_hash", _hash(self.config_hash, field="study.config_hash"))
        object.__setattr__(self, "source_bundle_id", _hash(self.source_bundle_id, field="study.source_bundle_id"))
        if type(self.cases) is not tuple or any(type(case) is not RankCase for case in self.cases):
            raise ContractValidationError("study cases must be RankCase tuple")
        if type(self.gates) is not tuple or any(type(gate) is not Gate for gate in self.gates):
            raise ContractValidationError("study gates must be Gate tuple")
        if type(self.disposition) is not RankDisposition or type(self.metrics) is not dict:
            raise ContractValidationError("study disposition or metrics is invalid")
        object.__setattr__(self, "study_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, object]:
        return {"schema_version": "1.0", "implementation_commit": self.implementation_commit, "config_hash": self.config_hash, "source_bundle_id": self.source_bundle_id, "cases": [case.to_payload() for case in self.cases], "gates": [gate.to_payload() for gate in self.gates], "disposition": self.disposition.value, "metrics": self.metrics}

    def to_payload(self) -> dict[str, object]:
        return {**self.identity_payload(), "study_id": self.study_id}


__all__ = ["CaseStatus", "ControlRecord", "Gate", "IntervalBar", "Quartile", "RankCase", "RankDisposition", "RankStudy", "SourceBundle", "SourceMember", "bars_sha256", "candidate_payload", "grid_sha256", "outcome_payload"]
