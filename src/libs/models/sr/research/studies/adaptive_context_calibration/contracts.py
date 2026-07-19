"""Immutable local contracts for SR-V2.3 source and evaluation evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from hashlib import sha256
import math
import re
from typing import Any

from libs.models.sr.domain import CandidateLevel, ContractValidationError, ZoneSide
from libs.models.sr.domain.identity import canonical_json, deterministic_hash, require_utc, utc_isoformat
from libs.models.sr.research.metrics.first_touch import FirstTouchOutcome
from libs.models.sr.research.source.contracts import SourceBar
from libs.models.sr.research.source.frozen import source_bar_payload


SCHEMA_VERSION = "1.0"
INTERVAL = timedelta(hours=12)
_HASH_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")


def _string(value: Any, *, path: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContractValidationError(f"{path} must be a non-empty string")
    return value


def _hash(value: Any, *, path: str) -> str:
    value = _string(value, path=path)
    if _HASH_RE.fullmatch(value) is None:
        raise ContractValidationError(f"{path} must be a lowercase SHA-256 hex string")
    return value


def _commit(value: Any, *, path: str) -> str:
    value = _string(value, path=path)
    if _COMMIT_RE.fullmatch(value) is None:
        raise ContractValidationError(f"{path} must be a git SHA")
    return value


def _integer(value: Any, *, path: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or type(value) is not int or value < minimum:
        raise ContractValidationError(f"{path} must be an integer >= {minimum}")
    return value


def _finite(value: Any, *, path: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{path} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{path} must be finite") from exc
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ContractValidationError(
            f"{path} must be finite"
            if minimum is None
            else f"{path} must be finite and >= {minimum}"
        )
    return 0.0 if result == 0.0 else result


def _timestamp(value: Any, *, path: str) -> datetime:
    try:
        return require_utc(value, field_name=path)
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise ContractValidationError(f"{path} must be a UTC-aware timestamp") from exc


def _bar_values(
    *, open_value: Any, high: Any, low: Any, close: Any, volume: Any, path: str
) -> tuple[float, float, float, float, float]:
    values = tuple(
        _finite(value, path=f"{path}.{name}", minimum=0.0)
        for name, value in (
            ("open", open_value),
            ("high", high),
            ("low", low),
            ("close", close),
            ("volume", volume),
        )
    )
    open_value, high, low, close, volume = values
    if min(open_value, high, low, close) <= 0.0:
        raise ContractValidationError(f"{path} OHLC values must be positive")
    if low > high or not low <= open_value <= high or not low <= close <= high:
        raise ContractValidationError(f"{path} OHLC values are incoherent")
    return values


@dataclass(frozen=True)
class IntervalBar:
    """Study-local interval bar; unlike SourceBar it has no daily cadence."""

    open_time: datetime
    closed_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_id: str

    def __post_init__(self) -> None:
        open_time = _timestamp(self.open_time, path="interval_bar.open_time")
        closed_at = _timestamp(self.closed_at, path="interval_bar.closed_at")
        if closed_at <= open_time:
            raise ContractValidationError("interval_bar.closed_at must be after open_time")
        values = _bar_values(
            open_value=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            path="interval_bar",
        )
        object.__setattr__(self, "open_time", open_time)
        object.__setattr__(self, "closed_at", closed_at)
        for name, value in zip(("open", "high", "low", "close", "volume"), values):
            object.__setattr__(self, name, value)
        object.__setattr__(self, "bar_id", _string(self.bar_id, path="interval_bar.bar_id"))

    def to_payload(self) -> dict[str, Any]:
        return {
            "open_time": utc_isoformat(self.open_time),
            "closed_at": utc_isoformat(self.closed_at),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "bar_id": self.bar_id,
        }


def interval_bars_sha256(bars: tuple[IntervalBar, ...]) -> str:
    if type(bars) is not tuple or not bars or any(type(bar) is not IntervalBar for bar in bars):
        raise ContractValidationError("interval bars must be a non-empty tuple")
    return sha256(canonical_json([bar.to_payload() for bar in bars]).encode("utf-8")).hexdigest()


def interval_grid_sha256(bars: tuple[IntervalBar, ...]) -> str:
    if type(bars) is not tuple or not bars or any(type(bar) is not IntervalBar for bar in bars):
        raise ContractValidationError("interval bars must be a non-empty tuple")
    return sha256(
        canonical_json([utc_isoformat(bar.open_time) for bar in bars]).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class IntervalCapsule:
    """Content-addressed 12h source capsule isolated from daily SourceCapsule."""

    asset: str
    venue: str
    timeframe: str
    source_id: str
    source_bundle_id: str
    source_bars_sha256: str
    source_grid_sha256: str
    requested_since: datetime
    requested_until: datetime
    provider_calls: int
    provider_request_since_ms: int | None
    provider_request_until_ms: int | None
    adapter_limit: int
    source_kind: str
    implementation_commit: str
    bars: tuple[IntervalBar, ...]
    capsule_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", _string(self.asset, path="interval_capsule.asset"))
        object.__setattr__(self, "venue", _string(self.venue, path="interval_capsule.venue"))
        if self.timeframe != "12h":
            raise ContractValidationError("interval capsule timeframe must be 12h")
        object.__setattr__(self, "timeframe", _string(self.timeframe, path="interval_capsule.timeframe"))
        for name in ("source_id", "source_bundle_id", "source_bars_sha256", "source_grid_sha256"):
            object.__setattr__(self, name, _hash(getattr(self, name), path=f"interval_capsule.{name}"))
        object.__setattr__(self, "implementation_commit", _commit(self.implementation_commit, path="interval_capsule.implementation_commit"))
        since = _timestamp(self.requested_since, path="interval_capsule.requested_since")
        until = _timestamp(self.requested_until, path="interval_capsule.requested_until")
        if since >= until:
            raise ContractValidationError("interval capsule request bounds are invalid")
        object.__setattr__(self, "requested_since", since)
        object.__setattr__(self, "requested_until", until)
        object.__setattr__(self, "provider_calls", _integer(self.provider_calls, path="interval_capsule.provider_calls"))
        if self.provider_calls not in (0, 1):
            raise ContractValidationError("interval capsule provider_calls must be 0 or 1")
        expected_since = int(since.timestamp() * 1000)
        expected_until = int(until.timestamp() * 1000) - 1
        if self.provider_calls == 1:
            if (self.provider_request_since_ms, self.provider_request_until_ms) != (expected_since, expected_until):
                raise ContractValidationError("interval capsule request identity is invalid")
        elif self.provider_request_since_ms is not None or self.provider_request_until_ms is not None:
            raise ContractValidationError("zero-call interval capsule must not carry request bounds")
        object.__setattr__(self, "adapter_limit", _integer(self.adapter_limit, path="interval_capsule.adapter_limit", minimum=1))
        if self.adapter_limit != 1000:
            raise ContractValidationError("interval capsule adapter_limit must be 1000")
        source_kind = _string(self.source_kind, path="interval_capsule.source_kind")
        if source_kind not in {"provider", "synthetic"}:
            raise ContractValidationError("unsupported interval capsule source_kind")
        if (source_kind == "provider") != (self.provider_calls == 1):
            raise ContractValidationError("interval capsule source kind/call count mismatch")
        object.__setattr__(self, "source_kind", source_kind)
        if type(self.bars) is not tuple or not self.bars:
            raise ContractValidationError("interval capsule bars must be a non-empty tuple")
        if any(type(bar) is not IntervalBar for bar in self.bars):
            raise ContractValidationError("interval capsule bars must contain IntervalBar values")
        expected_open = since
        ids: set[str] = set()
        for index, bar in enumerate(self.bars):
            if bar.open_time != expected_open or bar.closed_at != expected_open + INTERVAL:
                raise ContractValidationError(f"interval bar {index} is not on the exact 12h grid")
            expected_id = f"{self.venue}:{self.asset}:{self.timeframe}:{int(expected_open.timestamp() * 1000)}"
            if bar.bar_id != expected_id or bar.bar_id in ids:
                raise ContractValidationError(f"interval bar {index} identity is invalid")
            ids.add(bar.bar_id)
            expected_open += INTERVAL
        if expected_open != until or self.bars[-1].closed_at != until:
            raise ContractValidationError("interval capsule bars do not close at requested_until")
        if interval_bars_sha256(self.bars) != self.source_bars_sha256:
            raise ContractValidationError("interval capsule bars hash does not match content")
        if interval_grid_sha256(self.bars) != self.source_grid_sha256:
            raise ContractValidationError("interval capsule grid hash does not match content")
        object.__setattr__(self, "capsule_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "asset": self.asset,
            "venue": self.venue,
            "timeframe": self.timeframe,
            "source_id": self.source_id,
            "source_bundle_id": self.source_bundle_id,
            "source_bars_sha256": self.source_bars_sha256,
            "source_grid_sha256": self.source_grid_sha256,
            "requested_since": utc_isoformat(self.requested_since),
            "requested_until": utc_isoformat(self.requested_until),
            "provider_calls": self.provider_calls,
            "provider_request_since_ms": self.provider_request_since_ms,
            "provider_request_until_ms": self.provider_request_until_ms,
            "adapter_limit": self.adapter_limit,
            "source_kind": self.source_kind,
            "implementation_commit": self.implementation_commit,
            "bars": [bar.to_payload() for bar in self.bars],
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "capsule_id": self.capsule_id}


def _member_bar_payload(bar: SourceBar | IntervalBar) -> dict[str, Any]:
    if type(bar) is SourceBar:
        return source_bar_payload(bar)
    if type(bar) is IntervalBar:
        return bar.to_payload()
    raise ContractValidationError("source member contains an unsupported bar type")


def _member_bars_sha256(bars: tuple[SourceBar | IntervalBar, ...]) -> str:
    if type(bars) is not tuple or not bars:
        raise ContractValidationError("source member bars must be a non-empty tuple")
    return sha256(canonical_json([_member_bar_payload(bar) for bar in bars]).encode("utf-8")).hexdigest()


def _member_grid_sha256(bars: tuple[SourceBar | IntervalBar, ...]) -> str:
    if type(bars) is not tuple or not bars:
        raise ContractValidationError("source member bars must be a non-empty tuple")
    return sha256(canonical_json([utc_isoformat(bar.open_time) for bar in bars]).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class V23SourceMember:
    """One canonical V2.3 source member for either 1d reuse or 12h fetch."""

    asset: str
    venue: str
    timeframe: str
    source_id: str
    source_bundle_id: str
    bars_sha256: str
    grid_sha256: str
    row_count: int
    first_open_time: datetime
    last_closed_at: datetime
    requested_since: datetime
    requested_until: datetime
    provider_calls: int
    provider_request_since_ms: int | None
    provider_request_until_ms: int | None
    adapter_limit: int
    source_kind: str
    implementation_commit: str
    bars: tuple[SourceBar | IntervalBar, ...]
    capsule_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", _string(self.asset, path="source.asset"))
        object.__setattr__(self, "venue", _string(self.venue, path="source.venue"))
        if self.timeframe not in {"1d", "12h"}:
            raise ContractValidationError("source timeframe must be 1d or 12h")
        object.__setattr__(self, "timeframe", _string(self.timeframe, path="source.timeframe"))
        for name in ("source_id", "source_bundle_id", "bars_sha256", "grid_sha256"):
            object.__setattr__(self, name, _hash(getattr(self, name), path=f"source.{name}"))
        object.__setattr__(self, "implementation_commit", _commit(self.implementation_commit, path="source.implementation_commit"))
        object.__setattr__(self, "row_count", _integer(self.row_count, path="source.row_count", minimum=1))
        first = _timestamp(self.first_open_time, path="source.first_open_time")
        last = _timestamp(self.last_closed_at, path="source.last_closed_at")
        since = _timestamp(self.requested_since, path="source.requested_since")
        until = _timestamp(self.requested_until, path="source.requested_until")
        if (first, last, since, until) != (since, until, since, until) or since >= until:
            raise ContractValidationError("source bounds do not reconcile")
        object.__setattr__(self, "first_open_time", first)
        object.__setattr__(self, "last_closed_at", last)
        object.__setattr__(self, "requested_since", since)
        object.__setattr__(self, "requested_until", until)
        object.__setattr__(self, "provider_calls", _integer(self.provider_calls, path="source.provider_calls"))
        if self.provider_calls not in (0, 1):
            raise ContractValidationError("source provider_calls must be 0 or 1")
        expected_since = int(since.timestamp() * 1000)
        expected_until = int(until.timestamp() * 1000) - 1
        if self.provider_calls == 0:
            if self.provider_request_since_ms is not None or self.provider_request_until_ms is not None:
                raise ContractValidationError("zero-call source must not carry request bounds")
        elif (self.provider_request_since_ms, self.provider_request_until_ms) != (expected_since, expected_until):
            raise ContractValidationError("source provider request identity is invalid")
        object.__setattr__(self, "adapter_limit", _integer(self.adapter_limit, path="source.adapter_limit", minimum=1))
        if self.adapter_limit != 1000:
            raise ContractValidationError("source adapter_limit must be 1000")
        source_kind = _string(self.source_kind, path="source.source_kind")
        if self.timeframe == "1d":
            if source_kind != "frozen_v1_7" or self.provider_calls != 0:
                raise ContractValidationError("1d source must be an immutable zero-call frozen member")
            if type(self.bars) is not tuple or not self.bars or any(type(bar) is not SourceBar for bar in self.bars):
                raise ContractValidationError("1d source must contain SourceBar values")
            cadence = timedelta(days=1)
        else:
            if source_kind not in {"provider", "synthetic"} or (source_kind == "provider") != (self.provider_calls == 1):
                raise ContractValidationError("12h source kind/call count mismatch")
            if type(self.bars) is not tuple or not self.bars or any(type(bar) is not IntervalBar for bar in self.bars):
                raise ContractValidationError("12h source must contain IntervalBar values")
            cadence = INTERVAL
        object.__setattr__(self, "source_kind", source_kind)
        if len(self.bars) != self.row_count:
            raise ContractValidationError("source row_count does not match bars")
        ids: set[str] = set()
        expected_open = since
        for index, bar in enumerate(self.bars):
            if bar.open_time != expected_open or bar.closed_at != expected_open + cadence:
                raise ContractValidationError(f"source bar {index} is not on the exact grid")
            expected_id = f"{self.venue}:{self.asset}:{self.timeframe}:{int(expected_open.timestamp() * 1000)}"
            if bar.bar_id != expected_id or bar.bar_id in ids:
                raise ContractValidationError(f"source bar {index} identity is invalid")
            ids.add(bar.bar_id)
            expected_open += cadence
        if expected_open != until or self.bars[-1].closed_at != until:
            raise ContractValidationError("source bars do not end at requested_until")
        if _member_bars_sha256(self.bars) != self.bars_sha256:
            raise ContractValidationError("source bars hash does not match content")
        if _member_grid_sha256(self.bars) != self.grid_sha256:
            raise ContractValidationError("source grid hash does not match content")
        object.__setattr__(self, "capsule_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "asset": self.asset,
            "venue": self.venue,
            "timeframe": self.timeframe,
            "source_id": self.source_id,
            "source_bundle_id": self.source_bundle_id,
            "bars_sha256": self.bars_sha256,
            "grid_sha256": self.grid_sha256,
            "row_count": self.row_count,
            "first_open_time": utc_isoformat(self.first_open_time),
            "last_closed_at": utc_isoformat(self.last_closed_at),
            "requested_since": utc_isoformat(self.requested_since),
            "requested_until": utc_isoformat(self.requested_until),
            "provider_calls": self.provider_calls,
            "provider_request_since_ms": self.provider_request_since_ms,
            "provider_request_until_ms": self.provider_request_until_ms,
            "adapter_limit": self.adapter_limit,
            "source_kind": self.source_kind,
            "implementation_commit": self.implementation_commit,
            "bars": [_member_bar_payload(bar) for bar in self.bars],
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "capsule_id": self.capsule_id}


CANONICAL_COHORTS = (
    ("TAOUSDT", "1d"),
    ("ETHUSDT", "1d"),
    ("SOLUSDT", "1d"),
    ("TAOUSDT", "12h"),
    ("ETHUSDT", "12h"),
    ("SOLUSDT", "12h"),
)


@dataclass(frozen=True)
class V23SourceBundle:
    implementation_commit: str
    config_hash: str
    assets: tuple[V23SourceMember, ...]
    bundle_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "implementation_commit", _commit(self.implementation_commit, path="source_bundle.implementation_commit"))
        object.__setattr__(self, "config_hash", _hash(self.config_hash, path="source_bundle.config_hash"))
        if type(self.assets) is not tuple or tuple((item.asset, item.timeframe) for item in self.assets) != CANONICAL_COHORTS:
            raise ContractValidationError("source bundle assets must use canonical order")
        if any(type(item) is not V23SourceMember for item in self.assets):
            raise ContractValidationError("source bundle members have invalid types")
        object.__setattr__(self, "bundle_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        members = []
        for item in self.assets:
            data = (canonical_json(item.to_payload()) + "\n").encode("utf-8")
            members.append({"name": f"{item.asset}_{item.timeframe}.json", "sha256": sha256(data).hexdigest(), "byte_length": len(data)})
        return {
            "schema_version": SCHEMA_VERSION,
            "stage": "development",
            "implementation_commit": self.implementation_commit,
            "config_hash": self.config_hash,
            "assets": [item.identity_payload() for item in self.assets],
            "provider_calls": {f"{item.asset}/{item.timeframe}": item.provider_calls for item in self.assets},
            "members": members,
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "bundle_id": self.bundle_id}


class OutcomeStatus(str, Enum):
    OUTSIDE_FOLDS = "OUTSIDE_FOLDS"
    NORMALIZATION_WARMUP = "NORMALIZATION_WARMUP"
    NO_TOUCH = "NO_TOUCH"
    RIGHT_CENSORED = "RIGHT_CENSORED"
    COMPLETED = "COMPLETED"


class NormalizationStatus(str, Enum):
    READY = "READY"
    NORMALIZATION_WARMUP = "NORMALIZATION_WARMUP"


class SalienceBucket(str, Enum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"


class AdaptiveDisposition(str, Enum):
    ADAPTIVE_CONTEXT_SUPPORTED_FOR_SHADOW = "ADAPTIVE_CONTEXT_SUPPORTED_FOR_SHADOW"
    ADAPTIVE_CONTEXT_NOT_SUPPORTED = "ADAPTIVE_CONTEXT_NOT_SUPPORTED"
    INSUFFICIENT_CALIBRATION_EVIDENCE = "INSUFFICIENT_CALIBRATION_EVIDENCE"


def candidate_payload(candidate: CandidateLevel) -> dict[str, Any]:
    if type(candidate) is not CandidateLevel:
        raise ContractValidationError("candidate must be exactly CandidateLevel")
    return {
        "candidate_id": candidate.candidate_id,
        "state_key": {
            "venue": candidate.state_key.venue,
            "symbol": candidate.state_key.symbol,
            "timeframe": candidate.state_key.timeframe,
        },
        "side": candidate.side.value,
        "geometry": {
            "center": candidate.geometry.center,
            "half_width": candidate.geometry.half_width,
            "lower_bound": candidate.geometry.lower_bound,
            "upper_bound": candidate.geometry.upper_bound,
        },
        "source": candidate.source,
        "formed_at": utc_isoformat(candidate.formed_at),
        "available_at": utc_isoformat(candidate.available_at),
        "atr_at_creation": candidate.atr_at_creation,
    }


def outcome_payload(outcome: FirstTouchOutcome | None) -> dict[str, Any] | None:
    if outcome is not None and type(outcome) is not FirstTouchOutcome:
        raise ContractValidationError("outcome must be exactly FirstTouchOutcome")
    return None if outcome is None else outcome.to_payload()


@dataclass(frozen=True)
class SwingObservation:
    asset: str
    timeframe: str
    side: ZoneSide
    extreme_bar_id: str
    confirmation_bar_id: str
    extreme_index: int
    confirmation_index: int
    extreme_atr: float
    raw_salience_atr: float
    state_before: str
    state_after: str
    candidate: CandidateLevel | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", _string(self.asset, path="swing.asset"))
        object.__setattr__(self, "timeframe", _string(self.timeframe, path="swing.timeframe"))
        if type(self.side) is not ZoneSide:
            raise ContractValidationError("swing side must be exactly ZoneSide")
        for name in ("extreme_bar_id", "confirmation_bar_id", "state_before", "state_after"):
            object.__setattr__(self, name, _string(getattr(self, name), path=f"swing.{name}"))
        for name in ("extreme_index", "confirmation_index"):
            object.__setattr__(self, name, _integer(getattr(self, name), path=f"swing.{name}"))
        if self.extreme_index >= self.confirmation_index:
            raise ContractValidationError("swing extreme must precede confirmation")
        object.__setattr__(self, "extreme_atr", _finite(self.extreme_atr, path="swing.extreme_atr", minimum=0.0))
        object.__setattr__(self, "raw_salience_atr", _finite(self.raw_salience_atr, path="swing.raw_salience_atr", minimum=0.0))
        if self.extreme_atr <= 0.0:
            raise ContractValidationError("swing extreme_atr must be positive")
        if self.candidate is not None and type(self.candidate) is not CandidateLevel:
            raise ContractValidationError("swing candidate must be CandidateLevel or None")

    def to_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "side": self.side.value,
            "extreme_bar_id": self.extreme_bar_id,
            "confirmation_bar_id": self.confirmation_bar_id,
            "extreme_index": self.extreme_index,
            "confirmation_index": self.confirmation_index,
            "extreme_atr": self.extreme_atr,
            "raw_salience_atr": self.raw_salience_atr,
            "state_before": self.state_before,
            "state_after": self.state_after,
            "candidate": None if self.candidate is None else candidate_payload(self.candidate),
        }


@dataclass(frozen=True)
class ControlRecord:
    side: ZoneSide
    candidate: CandidateLevel
    status: OutcomeStatus
    outcome: FirstTouchOutcome | None
    zone_width_atr: float

    def __post_init__(self) -> None:
        if type(self.side) is not ZoneSide or type(self.candidate) is not CandidateLevel:
            raise ContractValidationError("control side/candidate types are invalid")
        if self.candidate.side is not self.side:
            raise ContractValidationError("control side does not match candidate")
        if self.candidate.source != "prior_close_naive_v2_3":
            raise ContractValidationError("control source is not the V2.3 prior-close control")
        if self.status is OutcomeStatus.OUTSIDE_FOLDS:
            raise ContractValidationError("in-fold control cannot be outside folds")
        object.__setattr__(self, "zone_width_atr", _finite(self.zone_width_atr, path="control.zone_width_atr", minimum=0.0))
        if self.zone_width_atr <= 0.0:
            raise ContractValidationError("control zone width must be positive")
        if self.status is OutcomeStatus.COMPLETED and (self.outcome is None or not self.outcome.completed):
            raise ContractValidationError("completed control status requires completed outcome")
        if self.status is OutcomeStatus.RIGHT_CENSORED and (self.outcome is None or not self.outcome.right_censored):
            raise ContractValidationError("censored control status requires censored outcome")
        if self.status is OutcomeStatus.NO_TOUCH and self.outcome is not None:
            raise ContractValidationError("no-touch control cannot contain outcome")

    @property
    def control_id(self) -> str:
        return deterministic_hash(self.causal_identity_payload())

    def causal_identity_payload(self) -> dict[str, Any]:
        return {"side": self.side.value, "candidate": candidate_payload(self.candidate), "zone_width_atr": self.zone_width_atr}

    def to_payload(self) -> dict[str, Any]:
        return {
            **self.causal_identity_payload(),
            "control_id": self.control_id,
            "status": self.status.value,
            "outcome": outcome_payload(self.outcome),
        }


@dataclass(frozen=True)
class CandidateCase:
    asset: str
    timeframe: str
    fold: str
    confirmation_bar_id: str
    confirmation_index: int
    extreme_bar_id: str
    extreme_index: int
    candidate: CandidateLevel
    raw_salience_atr: float
    percentile: float | None
    bucket: SalienceBucket | None
    normalization_status: NormalizationStatus
    real_status: OutcomeStatus
    real_outcome: FirstTouchOutcome | None
    controls: tuple[ControlRecord, ...]
    paired_excess_quality_atr: float | None
    label: int | None
    label_available_at: datetime | None
    zone_width_atr: float
    case_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", _string(self.asset, path="case.asset"))
        object.__setattr__(self, "timeframe", _string(self.timeframe, path="case.timeframe"))
        object.__setattr__(self, "fold", _string(self.fold, path="case.fold"))
        for name in ("confirmation_bar_id", "extreme_bar_id"):
            object.__setattr__(self, name, _string(getattr(self, name), path=f"case.{name}"))
        for name in ("confirmation_index", "extreme_index"):
            object.__setattr__(self, name, _integer(getattr(self, name), path=f"case.{name}"))
        if self.extreme_index >= self.confirmation_index:
            raise ContractValidationError("case extreme must precede confirmation")
        if type(self.candidate) is not CandidateLevel or self.candidate.source != "causal_swing_salience_v2_3":
            raise ContractValidationError("case candidate is not the V2.3 causal candidate")
        object.__setattr__(self, "raw_salience_atr", _finite(self.raw_salience_atr, path="case.raw_salience_atr", minimum=0.0))
        object.__setattr__(self, "zone_width_atr", _finite(self.zone_width_atr, path="case.zone_width_atr", minimum=0.0))
        if self.zone_width_atr <= 0.0:
            raise ContractValidationError("case zone width must be positive")
        if type(self.normalization_status) is not NormalizationStatus:
            raise ContractValidationError("case normalization status is invalid")
        if self.normalization_status is NormalizationStatus.READY:
            if self.percentile is None or self.bucket is None:
                raise ContractValidationError("ready case requires percentile and bucket")
            object.__setattr__(self, "percentile", _finite(self.percentile, path="case.percentile"))
            if not 0.0 <= self.percentile <= 1.0 or type(self.bucket) is not SalienceBucket:
                raise ContractValidationError("case percentile/bucket is invalid")
        elif self.percentile is not None or self.bucket is not None:
            raise ContractValidationError("warmup case cannot contain percentile/bucket")
        if type(self.real_status) is not OutcomeStatus or self.real_status is OutcomeStatus.OUTSIDE_FOLDS:
            raise ContractValidationError("case real status is invalid")
        if self.real_status is OutcomeStatus.COMPLETED and (self.real_outcome is None or not self.real_outcome.completed):
            raise ContractValidationError("completed case requires completed outcome")
        if self.real_status is OutcomeStatus.RIGHT_CENSORED and (self.real_outcome is None or not self.real_outcome.right_censored):
            raise ContractValidationError("censored case requires censored outcome")
        if self.real_status is OutcomeStatus.NO_TOUCH and self.real_outcome is not None:
            raise ContractValidationError("no-touch case cannot contain outcome")
        if type(self.controls) is not tuple or len(self.controls) != 2 or any(type(item) is not ControlRecord for item in self.controls):
            raise ContractValidationError("case must contain exactly two controls")
        if tuple(item.side for item in self.controls) != (ZoneSide.SUPPORT, ZoneSide.RESISTANCE):
            raise ContractValidationError("controls must be ordered SUPPORT then RESISTANCE")
        for control in self.controls:
            if control.candidate.available_at != self.candidate.available_at or control.candidate.atr_at_creation != self.candidate.atr_at_creation:
                raise ContractValidationError("control availability/creation ATR does not match real candidate")
            if control.zone_width_atr != self.zone_width_atr:
                raise ContractValidationError("control width does not match real candidate")
        if self.paired_excess_quality_atr is not None:
            object.__setattr__(self, "paired_excess_quality_atr", _finite(self.paired_excess_quality_atr, path="case.paired_excess_quality_atr"))
        if self.label is not None and self.label not in (0, 1):
            raise ContractValidationError("case label must be 0 or 1")
        if (self.label is None) != (self.label_available_at is None):
            raise ContractValidationError("case label and availability must be paired")
        if self.label is not None:
            if self.paired_excess_quality_atr is None:
                raise ContractValidationError("labeled case requires paired excess quality")
            object.__setattr__(self, "label_available_at", _timestamp(self.label_available_at, path="case.label_available_at"))
            if self.label_available_at <= self.candidate.available_at:
                raise ContractValidationError("label availability must be after prediction time")
        object.__setattr__(self, "case_id", deterministic_hash(self.causal_identity_payload()))

    def causal_identity_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "fold": self.fold,
            "confirmation_bar_id": self.confirmation_bar_id,
            "confirmation_index": self.confirmation_index,
            "extreme_bar_id": self.extreme_bar_id,
            "extreme_index": self.extreme_index,
            "candidate": candidate_payload(self.candidate),
            "raw_salience_atr": self.raw_salience_atr,
            "percentile": self.percentile,
            "bucket": None if self.bucket is None else self.bucket.value,
            "normalization_status": self.normalization_status.value,
            "zone_width_atr": self.zone_width_atr,
            "controls": [item.causal_identity_payload() for item in self.controls],
        }

    def to_payload(self) -> dict[str, Any]:
        return {
            **self.causal_identity_payload(),
            "case_id": self.case_id,
            "real_status": self.real_status.value,
            "real_outcome": outcome_payload(self.real_outcome),
            "controls": [item.to_payload() for item in self.controls],
            "paired_excess_quality_atr": self.paired_excess_quality_atr,
            "label": self.label,
            "label_available_at": None if self.label_available_at is None else utc_isoformat(self.label_available_at),
        }


@dataclass(frozen=True)
class PosteriorState:
    successes: int
    failures: int
    alpha: float
    beta: float
    probability: float
    lower_90: float
    upper_90: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "successes", _integer(self.successes, path="posterior.successes"))
        object.__setattr__(self, "failures", _integer(self.failures, path="posterior.failures"))
        for name in ("alpha", "beta", "probability", "lower_90", "upper_90"):
            object.__setattr__(self, name, _finite(getattr(self, name), path=f"posterior.{name}"))
        if self.alpha <= 0.0 or self.beta <= 0.0 or not 0.0 < self.probability < 1.0 or not 0.0 <= self.lower_90 <= self.probability <= self.upper_90 <= 1.0:
            raise ContractValidationError("posterior state is invalid")

    def to_payload(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class PredictionRecord:
    case_id: str
    asset: str
    timeframe: str
    fold: str
    prediction_at: datetime
    bucket: SalienceBucket
    adaptive_global: PosteriorState
    adaptive_asset: PosteriorState
    adaptive_final: PosteriorState
    null: PosteriorState
    label: int | None
    label_available_at: datetime | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _string(self.case_id, path="prediction.case_id"))
        object.__setattr__(self, "asset", _string(self.asset, path="prediction.asset"))
        object.__setattr__(self, "timeframe", _string(self.timeframe, path="prediction.timeframe"))
        object.__setattr__(self, "fold", _string(self.fold, path="prediction.fold"))
        object.__setattr__(self, "prediction_at", _timestamp(self.prediction_at, path="prediction.prediction_at"))
        if type(self.bucket) is not SalienceBucket or any(type(item) is not PosteriorState for item in (self.adaptive_global, self.adaptive_asset, self.adaptive_final, self.null)):
            raise ContractValidationError("prediction posterior types are invalid")
        if self.label is not None and self.label not in (0, 1):
            raise ContractValidationError("prediction label must be 0 or 1")
        if (self.label is None) != (self.label_available_at is None):
            raise ContractValidationError("prediction label and availability must be paired")
        if self.label_available_at is not None:
            object.__setattr__(self, "label_available_at", _timestamp(self.label_available_at, path="prediction.label_available_at"))

    @property
    def prediction_id(self) -> str:
        return deterministic_hash(self.identity_payload())

    @property
    def adaptive_brier_loss(self) -> float | None:
        if self.label is None:
            return None
        return (self.adaptive_final.probability - self.label) ** 2

    @property
    def null_brier_loss(self) -> float | None:
        if self.label is None:
            return None
        return (self.null.probability - self.label) ** 2

    @property
    def adaptive_log_loss(self) -> float | None:
        if self.label is None:
            return None
        return -math.log(self.adaptive_final.probability if self.label else 1.0 - self.adaptive_final.probability)

    @property
    def null_log_loss(self) -> float | None:
        if self.label is None:
            return None
        return -math.log(self.null.probability if self.label else 1.0 - self.null.probability)

    def identity_payload(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "prediction_at": utc_isoformat(self.prediction_at), "bucket": self.bucket.value}

    def to_payload(self) -> dict[str, Any]:
        return {
            **self.identity_payload(),
            "prediction_id": self.prediction_id,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "fold": self.fold,
            "adaptive_global": self.adaptive_global.to_payload(),
            "adaptive_asset": self.adaptive_asset.to_payload(),
            "adaptive_final": self.adaptive_final.to_payload(),
            "null": self.null.to_payload(),
            "label": self.label,
            "label_available_at": None if self.label_available_at is None else utc_isoformat(self.label_available_at),
            "adaptive_brier_loss": self.adaptive_brier_loss,
            "null_brier_loss": self.null_brier_loss,
            "adaptive_log_loss": self.adaptive_log_loss,
            "null_log_loss": self.null_log_loss,
        }


@dataclass(frozen=True)
class StudyResult:
    implementation_commit: str
    config_hash: str
    source_bundle_id: str
    swings: tuple[SwingObservation, ...]
    cases: tuple[CandidateCase, ...]
    predictions: tuple[PredictionRecord, ...]
    metrics: dict[str, Any]
    bootstrap: dict[str, Any]
    disposition: AdaptiveDisposition
    study_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "implementation_commit", _commit(self.implementation_commit, path="study.implementation_commit"))
        object.__setattr__(self, "config_hash", _hash(self.config_hash, path="study.config_hash"))
        object.__setattr__(self, "source_bundle_id", _hash(self.source_bundle_id, path="study.source_bundle_id"))
        if type(self.swings) is not tuple or any(type(item) is not SwingObservation for item in self.swings):
            raise ContractValidationError("study swings have invalid types")
        if type(self.cases) is not tuple or any(type(item) is not CandidateCase for item in self.cases):
            raise ContractValidationError("study cases have invalid types")
        if type(self.predictions) is not tuple or any(type(item) is not PredictionRecord for item in self.predictions):
            raise ContractValidationError("study predictions have invalid types")
        if type(self.metrics) is not dict or type(self.bootstrap) is not dict or type(self.disposition) is not AdaptiveDisposition:
            raise ContractValidationError("study result summary types are invalid")
        if len({item.case_id for item in self.cases}) != len(self.cases) or len({item.prediction_id for item in self.predictions}) != len(self.predictions):
            raise ContractValidationError("study case/prediction IDs must be unique")
        object.__setattr__(self, "study_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "implementation_commit": self.implementation_commit,
            "config_hash": self.config_hash,
            "source_bundle_id": self.source_bundle_id,
            "swings": [item.to_payload() for item in self.swings],
            "swing_ids": [deterministic_hash(item.to_payload()) for item in self.swings],
            "case_ids": [item.case_id for item in self.cases],
            "prediction_ids": [item.prediction_id for item in self.predictions],
            "metrics": self.metrics,
            "bootstrap": self.bootstrap,
            "disposition": self.disposition.value,
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "study_id": self.study_id}


__all__ = [
    "AdaptiveDisposition",
    "CANONICAL_COHORTS",
    "CandidateCase",
    "ControlRecord",
    "IntervalBar",
    "IntervalCapsule",
    "NormalizationStatus",
    "OutcomeStatus",
    "PosteriorState",
    "PredictionRecord",
    "SalienceBucket",
    "SCHEMA_VERSION",
    "StudyResult",
    "SwingObservation",
    "V23SourceBundle",
    "V23SourceMember",
    "candidate_payload",
    "interval_bars_sha256",
    "interval_grid_sha256",
    "outcome_payload",
]
