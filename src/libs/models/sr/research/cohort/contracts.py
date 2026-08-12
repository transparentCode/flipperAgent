"""Immutable contracts for the SR-V1.7 cohort-readiness trial.

The trial is deliberately descriptive.  These contracts contain no candidate
selection or production recommendation surface; they only bind the four
development sources, their causal replays, and the predeclared readiness
accounting.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
from typing import Any

from libs.models.sr.domain import ContractValidationError, SREventType
from libs.models.sr.domain.identity import (
    canonical_json,
    deterministic_hash,
    require_utc,
    utc_isoformat,
)
from libs.models.sr.research.metrics.first_touch import FirstTouchOutcome
from libs.models.sr.research.metrics.first_touch_windows import CandidateMetrics
from libs.models.sr.research.replay.candidates import CandidateReplay
from libs.models.sr.research.source.capsules import SourceCapsule
from libs.models.sr.research.source.contracts import SourceBar
from libs.models.sr.research.source.frozen import (
    source_bar_payload,
    source_bars_sha256,
    source_grid_sha256,
)
from libs.models.sr.research.windows.folds import CohortFold

SCHEMA_VERSION = "1.0"
APPROVED_ASSETS = ("TAOUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT")
APPROVED_VENUE = "binance_usdm"
APPROVED_TIMEFRAME = "1d"
APPROVED_SOURCE_START = datetime(2024, 4, 11, tzinfo=timezone.utc)
APPROVED_SOURCE_END = datetime(2025, 12, 31, tzinfo=timezone.utc)
APPROVED_SOURCE_ROWS = 629
APPROVED_GRID_POLICY = "exact_utc_daily_grid_from_taousdt_development_capsule"
TAO_SOURCE_ID = "fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120"
TAO_SOURCE_BUNDLE_ID = "d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925"
TAO_BARS_SHA256 = "703367048f4ed7dc432ca9dfe0ad4afdc5a56eb2a508597ef00bdc3de8b81163"
TAO_SOURCE_MEMBER_SHA256 = "b9ed3cf63e87fd3c413843f6bbc88d647eb051131cac6524af079fc1458c2ff3"
TAO_SOURCE_IMPLEMENTATION_COMMIT = "928583c7677255ed5ac8c16e5d04fdfa8927bbd6"
FROZEN_SR_CONFIG_HASH = "cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299"
FROZEN_INPUT_HASH = "5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d"
ATR_IMPLEMENTATION = "libs.features.indicators.volatility.atr.ATR"
ATR_IMPLEMENTATION_CONTRACT = "true_range_sma_seed_then_wilder_recursion_v1"
WINDOW_POLICY = "half_open_utc_daily"
ADAPTER_IDENTITY = "libs.market_data.binance_native.BinanceNativeAdapter"
ADAPTER_LIMIT = 1000
SR_FIELD_PROVENANCE_PATHS = (
    "association.merge_distance_atr",
    "detection.pivot_span_bars",
    "detection.zone_half_width_atr",
    "lifecycle.break_buffer_atr",
    "lifecycle.break_confirm_closes",
    "lifecycle.max_age_bars",
    "lifecycle.touch_tolerance_atr",
    "runtime.max_active_zones",
)
INPUT_FIELD_PROVENANCE_PATHS = ("atr.method", "atr.period", "atr.seed")

_HASH_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")


def _string(value: Any, *, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _hash(value: Any, *, field_name: str) -> str:
    value = _string(value, field_name=field_name)
    if _HASH_RE.fullmatch(value) is None:
        raise ContractValidationError(f"{field_name} must be a lowercase SHA-256 hex string")
    return value


def _commit(value: Any, *, field_name: str) -> str:
    value = _string(value, field_name=field_name)
    if _COMMIT_RE.fullmatch(value) is None:
        raise ContractValidationError(f"{field_name} must be a git SHA")
    return value


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
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{field_name} must be >= {minimum}")
    return 0.0 if result == 0.0 else result


def _provenance_table(
    value: Any,
    *,
    field_name: str,
    expected_paths: tuple[str, ...],
) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    if type(value) is not tuple or len(value) != len(APPROVED_ASSETS):
        raise ContractValidationError(f"{field_name} must cover the canonical assets")
    normalized: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    for index, entry in enumerate(value):
        if type(entry) is not tuple or len(entry) != 2:
            raise ContractValidationError(f"{field_name}[{index}] must be an asset/provenance pair")
        asset, raw_entries = entry
        asset = _string(asset, field_name=f"{field_name}[{index}].asset")
        if type(raw_entries) is not tuple or len(raw_entries) != len(expected_paths):
            raise ContractValidationError(f"{field_name}[{index}] has an invalid entry count")
        entries: list[tuple[str, str]] = []
        for entry_index, provenance in enumerate(raw_entries):
            if type(provenance) is not tuple or len(provenance) != 2:
                raise ContractValidationError(
                    f"{field_name}[{index}][{entry_index}] must be a path/source pair"
                )
            path, source = provenance
            entries.append(
                (
                    _string(path, field_name=f"{field_name}[{index}].path"),
                    _string(source, field_name=f"{field_name}[{index}].source"),
                )
            )
        if tuple(path for path, _ in entries) != expected_paths:
            raise ContractValidationError(f"{field_name}[{index}] paths do not match the frozen protocol")
        if any(source != "defaults" for _, source in entries):
            raise ContractValidationError(f"{field_name}[{index}] contains an override provenance source")
        normalized.append((asset, tuple(entries)))
    if tuple(asset for asset, _ in normalized) != APPROVED_ASSETS:
        raise ContractValidationError(f"{field_name} must use canonical asset order")
    return tuple(normalized)


def _timestamp(value: Any, *, field_name: str) -> datetime:
    try:
        result = require_utc(value, field_name=field_name)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"{field_name} must be a UTC-aware timestamp") from exc
    return result


def _bar_payload(bar: SourceBar) -> dict[str, Any]:
    return source_bar_payload(bar)


def bars_sha256(bars: tuple[SourceBar, ...]) -> str:
    return source_bars_sha256(bars)


def grid_sha256(bars: tuple[SourceBar, ...]) -> str:
    return source_grid_sha256(bars)


class Disposition(str, Enum):
    STRUCTURAL_ANOMALY = "STRUCTURAL_ANOMALY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    READY_FOR_PARAMETER_SENSITIVITY = "READY_FOR_PARAMETER_SENSITIVITY"


@dataclass(frozen=True)
class EventAccounting:
    created: int
    touched: int
    breach_started: int
    false_breakout: int
    break_confirmed: int
    expired: int
    observed_event_count: int

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _integer(getattr(self, name), field_name=f"event_accounting.{name}"))
        if sum(getattr(self, name) for name in ("created", "touched", "breach_started", "false_breakout", "break_confirmed", "expired")) != self.observed_event_count:
            raise ContractValidationError("event accounting does not reconcile to observed event count")

    @classmethod
    def from_events(cls, events: tuple[Any, ...]) -> EventAccounting:
        counts = {
            "created": sum(event.event_type is SREventType.CREATED for event in events),
            "touched": sum(event.event_type is SREventType.TOUCHED for event in events),
            "breach_started": sum(event.event_type is SREventType.BREACH_STARTED for event in events),
            "false_breakout": sum(event.event_type is SREventType.FALSE_BREAKOUT for event in events),
            "break_confirmed": sum(event.event_type is SREventType.BREAK_CONFIRMED for event in events),
            "expired": sum(event.event_type is SREventType.EXPIRED for event in events),
        }
        return cls(**counts, observed_event_count=len(events))

    def to_payload(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class ReadinessGates:
    minimum_completed_first_touches_per_fold: int
    minimum_eligible_development_folds: int
    minimum_development_completed_first_touches: int

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(
                self,
                name,
                _integer(getattr(self, name), field_name=f"gates.{name}", minimum=1),
            )

    def to_payload(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class AssetSource:
    asset: str
    venue: str
    timeframe: str
    source_id: str
    source_bundle_id: str
    bars_sha256: str
    row_count: int
    first_open_time: datetime
    last_closed_at: datetime
    grid_sha256: str
    requested_since: datetime
    requested_until: datetime
    provider_calls: int
    provider_request_since_ms: int | None
    provider_request_until_ms: int | None
    adapter_limit: int
    source_kind: str
    resolved_sr_config_hash: str
    resolved_input_hash: str
    bars: tuple[SourceBar, ...]
    capsule_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", _string(self.asset, field_name="asset"))
        object.__setattr__(self, "venue", _string(self.venue, field_name="venue"))
        object.__setattr__(self, "timeframe", _string(self.timeframe, field_name="timeframe"))
        if self.venue != APPROVED_VENUE or self.timeframe != APPROVED_TIMEFRAME:
            raise ContractValidationError("source venue/timeframe is outside the approved cohort")
        object.__setattr__(self, "source_id", _hash(self.source_id, field_name="source_id"))
        object.__setattr__(self, "source_bundle_id", _hash(self.source_bundle_id, field_name="source_bundle_id"))
        object.__setattr__(self, "bars_sha256", _hash(self.bars_sha256, field_name="bars_sha256"))
        object.__setattr__(self, "grid_sha256", _hash(self.grid_sha256, field_name="grid_sha256"))
        object.__setattr__(self, "resolved_sr_config_hash", _hash(self.resolved_sr_config_hash, field_name="resolved_sr_config_hash"))
        object.__setattr__(self, "resolved_input_hash", _hash(self.resolved_input_hash, field_name="resolved_input_hash"))
        object.__setattr__(self, "row_count", _integer(self.row_count, field_name="row_count", minimum=1))
        object.__setattr__(self, "adapter_limit", _integer(self.adapter_limit, field_name="adapter_limit", minimum=1))
        if self.adapter_limit != ADAPTER_LIMIT:
            raise ContractValidationError("source adapter_limit must be 1000")
        first = _timestamp(self.first_open_time, field_name="first_open_time")
        last = _timestamp(self.last_closed_at, field_name="last_closed_at")
        since = _timestamp(self.requested_since, field_name="requested_since")
        until = _timestamp(self.requested_until, field_name="requested_until")
        if since >= until or since != APPROVED_SOURCE_START or until != APPROVED_SOURCE_END or first != APPROVED_SOURCE_START or last != APPROVED_SOURCE_END:
            raise ContractValidationError("source bounds do not match the frozen cohort grid")
        object.__setattr__(self, "first_open_time", first)
        object.__setattr__(self, "last_closed_at", last)
        object.__setattr__(self, "requested_since", since)
        object.__setattr__(self, "requested_until", until)
        object.__setattr__(self, "provider_calls", _integer(self.provider_calls, field_name="provider_calls", minimum=0))
        if self.provider_calls not in (0, 1):
            raise ContractValidationError("provider_calls must be 0 or 1")
        if self.provider_calls == 0:
            if self.provider_request_since_ms is not None or self.provider_request_until_ms is not None:
                raise ContractValidationError("frozen source must not carry provider request bounds")
        else:
            if type(self.provider_request_since_ms) is not int or type(self.provider_request_until_ms) is not int:
                raise ContractValidationError("provider source must carry integer request bounds")
            expected_since = _epoch_ms(since)
            expected_until = _epoch_ms(until) - 1
            if (self.provider_request_since_ms, self.provider_request_until_ms) != (expected_since, expected_until):
                raise ContractValidationError("provider request bounds do not match the frozen source window")
            if self.provider_request_until_ms <= self.provider_request_since_ms:
                raise ContractValidationError("provider request bounds are invalid")
        source_kind = _string(self.source_kind, field_name="source_kind")
        if source_kind not in {"frozen_v1_6", "provider"}:
            raise ContractValidationError("unsupported source_kind")
        if source_kind == "frozen_v1_6" and self.provider_calls != 0:
            raise ContractValidationError("frozen source must have zero provider calls")
        if source_kind == "provider" and self.provider_calls != 1:
            raise ContractValidationError("provider source must have exactly one provider call")
        object.__setattr__(self, "source_kind", source_kind)
        if type(self.bars) is not tuple or len(self.bars) != self.row_count or not self.bars:
            raise ContractValidationError("source bars do not match row_count")
        if any(type(bar) is not SourceBar for bar in self.bars):
            raise ContractValidationError("source bars must contain SourceBar values")
        expected_open = first
        ids: set[str] = set()
        for index, bar in enumerate(self.bars):
            if bar.open_time != expected_open:
                raise ContractValidationError(f"source bar {index} is not on the frozen UTC daily grid")
            if bar.closed_at > until or bar.open_time < since:
                raise ContractValidationError(f"source bar {index} exceeds the causal source window")
            expected_id = f"{self.venue}:{self.asset}:{self.timeframe}:{_epoch_ms(bar.open_time)}"
            if bar.bar_id != expected_id or bar.bar_id in ids:
                raise ContractValidationError(f"source bar {index} identity is invalid")
            ids.add(bar.bar_id)
            expected_open += timedelta(days=1)
        if self.bars[-1].closed_at != last:
            raise ContractValidationError("source last causal close does not match the frozen boundary")
        if bars_sha256(self.bars) != self.bars_sha256:
            raise ContractValidationError("source bars hash does not match content")
        if grid_sha256(self.bars) != self.grid_sha256:
            raise ContractValidationError("source timestamp-grid hash does not match content")
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
            "row_count": self.row_count,
            "first_open_time": utc_isoformat(self.first_open_time),
            "last_closed_at": utc_isoformat(self.last_closed_at),
            "grid_sha256": self.grid_sha256,
            "requested_since": utc_isoformat(self.requested_since),
            "requested_until": utc_isoformat(self.requested_until),
            "provider_calls": self.provider_calls,
            "provider_request_since_ms": self.provider_request_since_ms,
            "provider_request_until_ms": self.provider_request_until_ms,
            "adapter_limit": self.adapter_limit,
            "source_kind": self.source_kind,
            "resolved_sr_config_hash": self.resolved_sr_config_hash,
            "resolved_input_hash": self.resolved_input_hash,
            "bars": [_bar_payload(bar) for bar in self.bars],
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "capsule_id": self.capsule_id}


@dataclass(frozen=True)
class SourceBundle:
    implementation_commit: str
    config_hash: str
    assets: tuple[AssetSource, ...]
    resolved_sr_config_hashes: tuple[tuple[str, str], ...]
    resolved_input_hashes: tuple[tuple[str, str], ...]
    resolved_sr_field_provenance: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    resolved_input_field_provenance: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    bundle_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "implementation_commit", _commit(self.implementation_commit, field_name="implementation_commit"))
        object.__setattr__(self, "config_hash", _hash(self.config_hash, field_name="config_hash"))
        if type(self.assets) is not tuple or len(self.assets) != len(APPROVED_ASSETS) or any(type(item) is not AssetSource for item in self.assets):
            raise ContractValidationError("source bundle assets have invalid types")
        if tuple(item.asset for item in self.assets) != APPROVED_ASSETS:
            raise ContractValidationError("source assets must use the canonical four-asset order")
        if any(item.source_kind == "frozen_v1_6" and item.asset != "TAOUSDT" for item in self.assets):
            raise ContractValidationError("only TAOUSDT may use the frozen source")
        if self.assets[0].source_kind != "frozen_v1_6" or any(item.source_kind != "provider" for item in self.assets[1:]):
            raise ContractValidationError("source kinds must be frozen TAOUSDT followed by three provider assets")
        for field_name, values in (("resolved_sr_config_hashes", self.resolved_sr_config_hashes), ("resolved_input_hashes", self.resolved_input_hashes)):
            if type(values) is not tuple or any(type(entry) is not tuple or len(entry) != 2 for entry in values):
                raise ContractValidationError(f"{field_name} must contain asset/hash pairs")
            if tuple(entry[0] for entry in values) != APPROVED_ASSETS:
                raise ContractValidationError(f"{field_name} must cover canonical assets")
            for asset, value in values:
                _string(asset, field_name=f"{field_name}.asset")
                _hash(value, field_name=f"{field_name}.{asset}")
        object.__setattr__(
            self,
            "resolved_sr_field_provenance",
            _provenance_table(
                self.resolved_sr_field_provenance,
                field_name="resolved_sr_field_provenance",
                expected_paths=SR_FIELD_PROVENANCE_PATHS,
            ),
        )
        object.__setattr__(
            self,
            "resolved_input_field_provenance",
            _provenance_table(
                self.resolved_input_field_provenance,
                field_name="resolved_input_field_provenance",
                expected_paths=INPUT_FIELD_PROVENANCE_PATHS,
            ),
        )
        sr_hashes = dict(self.resolved_sr_config_hashes)
        input_hashes = dict(self.resolved_input_hashes)
        for source in self.assets:
            if sr_hashes[source.asset] != source.resolved_sr_config_hash or input_hashes[source.asset] != source.resolved_input_hash:
                raise ContractValidationError("source and resolved hash tables do not reconcile")
        object.__setattr__(self, "bundle_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        members = []
        for asset in self.assets:
            data = (canonical_json(asset.to_payload()) + "\n").encode("utf-8")
            members.append({
                "name": f"{asset.asset}.json",
                "sha256": sha256(data).hexdigest(),
                "byte_length": len(data),
            })
        return {
            "schema_version": SCHEMA_VERSION,
            "stage": "development",
            "implementation_commit": self.implementation_commit,
            "config_hash": self.config_hash,
            "assets": [asset.identity_payload() for asset in self.assets],
            "resolved_sr_config_hashes": [list(item) for item in self.resolved_sr_config_hashes],
            "resolved_input_hashes": [list(item) for item in self.resolved_input_hashes],
            "resolved_sr_field_provenance": [
                [asset, [list(pair) for pair in entries]]
                for asset, entries in self.resolved_sr_field_provenance
            ],
            "resolved_input_field_provenance": [
                [asset, [list(pair) for pair in entries]]
                for asset, entries in self.resolved_input_field_provenance
            ],
            "provider_calls": {asset.asset: asset.provider_calls for asset in self.assets},
            "members": members,
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "bundle_id": self.bundle_id, "sources": [asset.to_payload() for asset in self.assets]}


def source_capsule(source: AssetSource, *, implementation_commit: str) -> SourceCapsule:
    """Adapt one V1.7 source to the immutable V1.6 replay contract."""
    return SourceCapsule(
        stage="development",
        source_bundle_id=source.source_bundle_id,
        source_bars_sha256=source.bars_sha256,
        source_row_count=source.row_count,
        # V1.6's development contract expresses the split at the next causal
        # boundary.  The final development bar closes at 2025-12-31; the
        # split is therefore 2026-01-01, not the request's last closed_at.
        split_boundary=source.last_closed_at + timedelta(days=1),
        implementation_commit=implementation_commit,
        bars=source.bars,
    )


@dataclass(frozen=True)
class AssetEvaluation:
    asset: str
    source_id: str
    resolved_sr_config_hash: str
    resolved_input_hash: str
    replay: CandidateReplay
    metrics: CandidateMetrics
    folds: tuple[CohortFold, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", _string(self.asset, field_name="asset"))
        object.__setattr__(self, "source_id", _hash(self.source_id, field_name="source_id"))
        object.__setattr__(self, "resolved_sr_config_hash", _hash(self.resolved_sr_config_hash, field_name="resolved_sr_config_hash"))
        object.__setattr__(self, "resolved_input_hash", _hash(self.resolved_input_hash, field_name="resolved_input_hash"))
        if type(self.replay) is not CandidateReplay or type(self.metrics) is not CandidateMetrics:
            raise ContractValidationError("asset evaluation replay/metrics types are invalid")
        if self.metrics.period != 14 or self.replay.period != 14:
            raise ContractValidationError("cohort evaluation is frozen to ATR(14)")
        if type(self.folds) is not tuple or any(type(fold) is not CohortFold for fold in self.folds):
            raise ContractValidationError("asset evaluation folds have invalid types")

    @property
    def trace_id(self) -> str:
        return self.replay.trace.trace_id

    @property
    def replay_id(self) -> str:
        return deterministic_hash({
            "model_bar_ids": [bar.bar_id for bar in self.replay.model_bars],
            "model_closed_at": [utc_isoformat(bar.closed_at) for bar in self.replay.model_bars],
            "reference_atr": list(self.replay.reference_atr),
            "trace_id": self.trace_id,
        })

    @property
    def event_accounting(self) -> EventAccounting:
        return EventAccounting.from_events(self.replay.trace.events)

    @property
    def created_zone_counts(self) -> tuple[int, int]:
        from libs.models.sr.domain import SREventType, ZoneSide

        sides = {observation.zone_id: observation.side for observation in self.replay.trace.zone_observations}
        created = {event.zone_id for event in self.replay.trace.events if event.event_type is SREventType.CREATED}
        return (
            sum(sides.get(zone_id) is ZoneSide.SUPPORT for zone_id in created),
            sum(sides.get(zone_id) is ZoneSide.RESISTANCE for zone_id in created),
        )

    def fold_event_accounting(self) -> tuple[tuple[str, EventAccounting], ...]:
        return tuple(
            (
                fold.name,
                EventAccounting.from_events(
                    tuple(event for event in self.replay.trace.events if fold.start <= event.timestamp < fold.end)
                ),
            )
            for fold in self.folds
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "source_id": self.source_id,
            "resolved_sr_config_hash": self.resolved_sr_config_hash,
            "resolved_input_hash": self.resolved_input_hash,
            "replay_id": self.replay_id,
            "trace_id": self.trace_id,
            "event_accounting": self.event_accounting.to_payload(),
            "created_support_zone_count": self.created_zone_counts[0],
            "created_resistance_zone_count": self.created_zone_counts[1],
            "fold_event_accounting": {
                name: accounting.to_payload()
                for name, accounting in self.fold_event_accounting()
            },
            "folds": [fold.to_payload() for fold in self.folds],
            "candidate_metrics": self.metrics.to_payload(),
        }


@dataclass(frozen=True)
class CohortAggregate:
    view: str
    total_first_touch_outcomes: int
    completed_first_touch_outcomes: int
    right_censored_first_touch_outcomes: int
    support_completed_count: int
    resistance_completed_count: int
    invalidated_completed_outcomes: int
    created_zone_count: int
    eligible_model_bar_count: int
    cohort_terminal_count: int
    right_censoring_rate: float | None
    invalidation_rate: float | None
    zone_creation_density_per_100_bars: float | None
    churn_rate: float | None
    median_favorable_reference_atr: float | None
    median_adverse_reference_atr: float | None
    median_quality_reference_atr: float | None
    outcomes: tuple[FirstTouchOutcome, ...] = field(default_factory=tuple)
    event_accounting: EventAccounting | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "view", _string(self.view, field_name="aggregate.view"))
        for name in (
            "total_first_touch_outcomes", "completed_first_touch_outcomes",
            "right_censored_first_touch_outcomes", "support_completed_count",
            "resistance_completed_count", "invalidated_completed_outcomes",
            "created_zone_count", "eligible_model_bar_count", "cohort_terminal_count",
        ):
            object.__setattr__(self, name, _integer(getattr(self, name), field_name=f"aggregate.{name}"))
        if self.completed_first_touch_outcomes + self.right_censored_first_touch_outcomes != self.total_first_touch_outcomes:
            raise ContractValidationError("aggregate outcome counts do not reconcile")
        if self.support_completed_count + self.resistance_completed_count != self.completed_first_touch_outcomes:
            raise ContractValidationError("aggregate side counts do not reconcile")
        if self.invalidated_completed_outcomes > self.completed_first_touch_outcomes:
            raise ContractValidationError("aggregate invalidations exceed completed outcomes")
        for name in (
            "right_censoring_rate", "invalidation_rate", "zone_creation_density_per_100_bars",
            "churn_rate", "median_favorable_reference_atr", "median_adverse_reference_atr",
            "median_quality_reference_atr",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _number(value, field_name=f"aggregate.{name}"))
        if type(self.outcomes) is not tuple or any(type(item) is not FirstTouchOutcome for item in self.outcomes):
            raise ContractValidationError("aggregate outcomes have invalid types")
        if len(self.outcomes) != self.total_first_touch_outcomes:
            raise ContractValidationError("aggregate outcomes do not reconcile")
        if self.event_accounting is not None and type(self.event_accounting) is not EventAccounting:
            raise ContractValidationError("aggregate event accounting has invalid type")

    def to_payload(self) -> dict[str, Any]:
        return {
            "view": self.view,
            "total_first_touch_outcomes": self.total_first_touch_outcomes,
            "completed_first_touch_outcomes": self.completed_first_touch_outcomes,
            "right_censored_first_touch_outcomes": self.right_censored_first_touch_outcomes,
            "support_completed_count": self.support_completed_count,
            "resistance_completed_count": self.resistance_completed_count,
            "invalidated_completed_outcomes": self.invalidated_completed_outcomes,
            "created_zone_count": self.created_zone_count,
            "eligible_model_bar_count": self.eligible_model_bar_count,
            "cohort_terminal_count": self.cohort_terminal_count,
            "right_censoring_rate": self.right_censoring_rate,
            "invalidation_rate": self.invalidation_rate,
            "zone_creation_density_per_100_bars": self.zone_creation_density_per_100_bars,
            "churn_rate": self.churn_rate,
            "median_favorable_reference_atr": self.median_favorable_reference_atr,
            "median_adverse_reference_atr": self.median_adverse_reference_atr,
            "median_quality_reference_atr": self.median_quality_reference_atr,
            "outcomes": [outcome.to_payload() for outcome in self.outcomes],
            "event_accounting": None if self.event_accounting is None else self.event_accounting.to_payload(),
        }


@dataclass(frozen=True)
class MacroMetric:
    median: float | None
    minimum: float | None
    maximum: float | None

    def to_payload(self) -> dict[str, float | None]:
        return {"median": self.median, "minimum": self.minimum, "maximum": self.maximum}


@dataclass(frozen=True)
class MacroAggregate:
    metrics: tuple[tuple[str, MacroMetric], ...]

    def __post_init__(self) -> None:
        if type(self.metrics) is not tuple or not self.metrics or any(type(entry) is not tuple or len(entry) != 2 for entry in self.metrics):
            raise ContractValidationError("macro metrics must be a non-empty sorted tuple")
        if tuple(name for name, _ in self.metrics) != tuple(sorted(name for name, _ in self.metrics)):
            raise ContractValidationError("macro metrics must be sorted")
        if any(type(name) is not str or type(metric) is not MacroMetric for name, metric in self.metrics):
            raise ContractValidationError("macro metric entries are invalid")

    def to_payload(self) -> dict[str, Any]:
        return {name: metric.to_payload() for name, metric in self.metrics}


@dataclass(frozen=True)
class GateRecord:
    name: str
    asset: str | None
    fold: str | None
    passed: bool
    value: Any
    threshold: Any
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _string(self.name, field_name="gate.name"))
        if self.asset is not None:
            object.__setattr__(self, "asset", _string(self.asset, field_name="gate.asset"))
        if self.fold is not None:
            object.__setattr__(self, "fold", _string(self.fold, field_name="gate.fold"))
        if type(self.passed) is not bool or type(self.reason) is not str or not self.reason:
            raise ContractValidationError("gate result is invalid")

    def to_payload(self) -> dict[str, Any]:
        return {"name": self.name, "asset": self.asset, "fold": self.fold, "passed": self.passed, "value": self.value, "threshold": self.threshold, "reason": self.reason}


@dataclass(frozen=True)
class CohortEvaluation:
    implementation_commit: str
    config_hash: str
    source_bundle_id: str
    assets: tuple[AssetEvaluation, ...]
    micro: CohortAggregate
    macro: MacroAggregate
    gates: tuple[GateRecord, ...]
    disposition: Disposition
    evaluation_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "implementation_commit", _commit(self.implementation_commit, field_name="implementation_commit"))
        object.__setattr__(self, "config_hash", _hash(self.config_hash, field_name="config_hash"))
        object.__setattr__(self, "source_bundle_id", _hash(self.source_bundle_id, field_name="source_bundle_id"))
        if type(self.assets) is not tuple or any(type(item) is not AssetEvaluation for item in self.assets):
            raise ContractValidationError("evaluation assets have invalid types")
        if tuple(item.asset for item in self.assets) != APPROVED_ASSETS:
            raise ContractValidationError("evaluation assets must use canonical order")
        if type(self.micro) is not CohortAggregate or self.micro.view != "micro":
            raise ContractValidationError("evaluation micro aggregate is invalid")
        if type(self.macro) is not MacroAggregate or type(self.gates) is not tuple:
            raise ContractValidationError("evaluation aggregate/gates are invalid")
        if any(type(item) is not GateRecord for item in self.gates):
            raise ContractValidationError("evaluation gates have invalid types")
        if type(self.disposition) is not Disposition:
            raise ContractValidationError("evaluation disposition is invalid")
        object.__setattr__(self, "evaluation_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "implementation_commit": self.implementation_commit,
            "config_hash": self.config_hash,
            "source_bundle_id": self.source_bundle_id,
            "assets": [item.to_payload() for item in self.assets],
            "micro": self.micro.to_payload(),
            "macro": self.macro.to_payload(),
            "gates": [item.to_payload() for item in self.gates],
            "disposition": self.disposition.value,
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "evaluation_id": self.evaluation_id}


def _epoch_ms(timestamp: datetime) -> int:
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = timestamp - epoch
    return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000


__all__ = [
    "ADAPTER_IDENTITY", "ADAPTER_LIMIT", "APPROVED_ASSETS", "APPROVED_GRID_POLICY",
    "APPROVED_SOURCE_END", "APPROVED_SOURCE_ROWS", "APPROVED_SOURCE_START",
    "APPROVED_TIMEFRAME", "APPROVED_VENUE", "AssetEvaluation", "AssetSource",
    "ATR_IMPLEMENTATION", "ATR_IMPLEMENTATION_CONTRACT", "CohortAggregate",
    "CohortEvaluation", "CohortFold", "Disposition", "EventAccounting", "FROZEN_INPUT_HASH",
    "FROZEN_SR_CONFIG_HASH", "GateRecord", "MacroAggregate", "MacroMetric",
    "ReadinessGates", "SCHEMA_VERSION", "SourceBundle", "SR_FIELD_PROVENANCE_PATHS",
    "INPUT_FIELD_PROVENANCE_PATHS", "TAO_BARS_SHA256",
    "TAO_SOURCE_BUNDLE_ID", "TAO_SOURCE_ID", "TAO_SOURCE_IMPLEMENTATION_COMMIT",
    "TAO_SOURCE_MEMBER_SHA256", "WINDOW_POLICY", "bars_sha256", "grid_sha256",
    "source_capsule",
]
