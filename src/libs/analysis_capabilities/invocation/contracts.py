"""Immutable source, timing, and provenance contracts for R2 invocation."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from ..invocation_spec import get_analysis_invocation_spec

_SHA256 = re.compile(r"[0-9a-f]{64}")


def _nonempty(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _optional_nonempty(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _nonempty(value, field_name=field_name)


def _utc(value: object, *, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise TypeError(f"{field_name} must be a timezone-aware UTC datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")
    return value.astimezone(UTC)


def _sha256(value: object, *, field_name: str) -> str:
    normalized = _nonempty(value, field_name=field_name)
    if _SHA256.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256 hex")
    return normalized


class AnalysisBindingError(ValueError):
    """Invocation/source/native-result facts do not reconcile."""


@dataclass(frozen=True, slots=True, kw_only=True)
class AnalysisSeriesIdentity:
    """Exact market-series identity supplied by the caller/source boundary."""

    asset: str
    venue: str
    instrument_id: str
    timeframe: str

    def __post_init__(self) -> None:
        for field_name in ("asset", "venue", "instrument_id", "timeframe"):
            _nonempty(getattr(self, field_name), field_name=field_name)


SourceType = Literal["provider", "derived", "fixture"]


@dataclass(frozen=True, slots=True, kw_only=True)
class AnalysisSourceAttestation:
    """Host-attested source identity and availability facts."""

    series: AnalysisSeriesIdentity
    source_type: SourceType
    source_provider: str | None
    source_timeframe: str | None
    source_revision: str
    source_slice_sha256: str
    source_available_at: datetime
    volume_unit: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.series, AnalysisSeriesIdentity):
            raise TypeError("series must be AnalysisSeriesIdentity")
        if self.source_type not in ("provider", "derived", "fixture"):
            raise ValueError("source_type must be provider, derived, or fixture")
        source_provider = _optional_nonempty(
            self.source_provider,
            field_name="source_provider",
        )
        source_timeframe = _optional_nonempty(
            self.source_timeframe,
            field_name="source_timeframe",
        )
        if self.source_type == "provider":
            if source_provider is None or source_timeframe is not None:
                raise ValueError(
                    "provider sources require source_provider and forbid "
                    "source_timeframe"
                )
        elif self.source_type == "derived":
            if source_provider is not None or source_timeframe is None:
                raise ValueError(
                    "derived sources require source_timeframe and forbid "
                    "source_provider"
                )
        elif source_provider is not None or source_timeframe is not None:
            raise ValueError("fixture sources forbid provider and source timeframe")
        object.__setattr__(self, "source_provider", source_provider)
        object.__setattr__(self, "source_timeframe", source_timeframe)
        object.__setattr__(
            self,
            "source_revision",
            _nonempty(self.source_revision, field_name="source_revision"),
        )
        object.__setattr__(
            self,
            "source_slice_sha256",
            _sha256(self.source_slice_sha256, field_name="source_slice_sha256"),
        )
        object.__setattr__(
            self,
            "source_available_at",
            _utc(self.source_available_at, field_name="source_available_at"),
        )
        object.__setattr__(
            self,
            "volume_unit",
            _optional_nonempty(self.volume_unit, field_name="volume_unit"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AnalysisInvocationContext:
    """Point-in-time context in which a bound request is evaluated."""

    source: AnalysisSourceAttestation
    market_as_of: datetime
    request_available_at: datetime
    evaluation_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.source, AnalysisSourceAttestation):
            raise TypeError("source must be AnalysisSourceAttestation")
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        request_available_at = _utc(
            self.request_available_at,
            field_name="request_available_at",
        )
        evaluation_at = _utc(self.evaluation_at, field_name="evaluation_at")
        if self.source.source_available_at > request_available_at:
            raise ValueError("source_available_at must be <= request_available_at")
        if request_available_at > evaluation_at:
            raise ValueError("request_available_at must be <= evaluation_at")
        if market_as_of > evaluation_at:
            raise ValueError("market_as_of must be <= evaluation_at")
        object.__setattr__(self, "market_as_of", market_as_of)
        object.__setattr__(self, "request_available_at", request_available_at)
        object.__setattr__(self, "evaluation_at", evaluation_at)


def _parameter_identity(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, tuple):
        raise TypeError("parameter_identity must be a tuple of pairs")
    normalized: list[tuple[str, str]] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise TypeError(f"parameter_identity[{index}] must be a pair")
        name, parameter_value = entry
        normalized.append(
            (
                _nonempty(name, field_name=f"parameter_identity[{index}].name"),
                _nonempty(
                    parameter_value,
                    field_name=f"parameter_identity[{index}].value",
                ),
            )
        )
    names = tuple(name for name, _ in normalized)
    if len(set(names)) != len(names):
        raise ValueError("parameter_identity names must be unique")
    if names != tuple(sorted(names)):
        raise ValueError("parameter_identity must be sorted by name")
    return tuple(normalized)


def _parameter_fingerprint(
    method_version: str,
    parameter_identity: tuple[tuple[str, str], ...],
) -> str:
    payload = {
        "method_version": method_version,
        "parameters": [list(entry) for entry in parameter_identity],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class AnalysisInvocationResult:
    """Native result retained with its checked invocation provenance."""

    capability_id: str
    method_version: str
    source: AnalysisSourceAttestation
    market_as_of: datetime
    request_available_at: datetime
    evaluation_at: datetime
    parameter_identity: tuple[tuple[str, str], ...]
    parameter_fingerprint: str
    result: object
    state_fingerprint: str | None = None

    def __post_init__(self) -> None:
        spec = get_analysis_invocation_spec(self.capability_id)
        if self.method_version != spec.method_version:
            raise ValueError("method_version does not match capability specification")
        context = AnalysisInvocationContext(
            source=self.source,
            market_as_of=self.market_as_of,
            request_available_at=self.request_available_at,
            evaluation_at=self.evaluation_at,
        )
        for field_name in spec.required_source_fields:
            if getattr(context.source, field_name) is None:
                raise AnalysisBindingError(
                    f"source.{field_name} is required for {self.capability_id}"
                )
        if spec.state_mode == "stateless":
            if self.state_fingerprint is not None:
                raise ValueError(
                    "stateless invocation results must not carry state_fingerprint"
                )
        else:
            state_fingerprint = _sha256(
                self.state_fingerprint,
                field_name="state_fingerprint",
            )
            object.__setattr__(self, "state_fingerprint", state_fingerprint)
        identity = _parameter_identity(self.parameter_identity)
        actual_names = tuple(name for name, _ in identity)
        expected_names = tuple(sorted(spec.parameter_fields))
        if actual_names != expected_names:
            raise ValueError(
                "parameter_identity fields do not match capability specification"
            )
        fingerprint = _sha256(
            self.parameter_fingerprint,
            field_name="parameter_fingerprint",
        )
        if fingerprint != _parameter_fingerprint(self.method_version, identity):
            raise ValueError("parameter_fingerprint does not match identity")
        object.__setattr__(self, "source", context.source)
        object.__setattr__(self, "market_as_of", context.market_as_of)
        object.__setattr__(self, "request_available_at", context.request_available_at)
        object.__setattr__(self, "evaluation_at", context.evaluation_at)
        object.__setattr__(self, "parameter_identity", identity)
        object.__setattr__(self, "parameter_fingerprint", fingerprint)


__all__ = (
    "AnalysisBindingError",
    "AnalysisInvocationContext",
    "AnalysisInvocationResult",
    "AnalysisSeriesIdentity",
    "AnalysisSourceAttestation",
)
