"""Trendlines-owned dataset, artifact, and replay contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable


def _stable_hash(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_timeframes(raw: str | Iterable[str]) -> tuple[str, ...]:
    values = raw.split(",") if isinstance(raw, str) else raw
    normalized: list[str] = []
    seen: set[str] = set()

    for value in values:
        timeframe = str(value).strip()
        if not timeframe or timeframe in seen:
            continue
        normalized.append(timeframe)
        seen.add(timeframe)

    if not normalized:
        raise ValueError("At least one timeframe is required")
    return tuple(normalized)


def _normalize_names(raw: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in raw:
        name = str(value).strip()
        if not name or name in seen:
            continue
        normalized.append(name)
        seen.add(name)
    if not normalized:
        raise ValueError("At least one field is required")
    return tuple(normalized)


@dataclass(frozen=True)
class TrendlineArtifactRef:
    """Reference to a persisted trendlines dataset or workflow artifact."""

    artifact_root: str
    relative_path: str | None = None
    label: str | None = None
    content_type: str | None = None
    semantics_version: str = "v1"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_root": self.artifact_root,
            "relative_path": self.relative_path,
            "label": self.label,
            "content_type": self.content_type,
            "semantics_version": self.semantics_version,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "TrendlineArtifactRef":
        raw = dict(payload or {})
        return cls(
            artifact_root=str(raw.get("artifact_root", "")),
            relative_path=raw.get("relative_path"),
            label=raw.get("label"),
            content_type=raw.get("content_type"),
            semantics_version=str(raw.get("semantics_version", "v1")),
            metadata=dict(raw.get("metadata", {})),
        )


@dataclass(frozen=True)
class TrendlineDataRequest:
    """Serializable dataset selection contract for trendlines-first runs."""

    asset: str
    timeframes: tuple[str, ...]
    source: str = "binance"
    start_date: str | None = None
    end_date: str | None = None
    lookback_days: int | None = None
    price_fields: tuple[str, ...] = ("open", "high", "low", "close")
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        asset = str(self.asset).strip()
        if not asset:
            raise ValueError("asset is required")
        if self.lookback_days is not None and int(self.lookback_days) <= 0:
            raise ValueError("lookback_days must be positive when provided")
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "timeframes", normalize_timeframes(self.timeframes))
        object.__setattr__(self, "price_fields", _normalize_names(self.price_fields))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframes": list(self.timeframes),
            "source": self.source,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "lookback_days": self.lookback_days,
            "price_fields": list(self.price_fields),
            "metadata": dict(self.metadata),
        }

    @property
    def request_hash(self) -> str:
        return _stable_hash(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "TrendlineDataRequest":
        raw = dict(payload or {})
        return cls(
            asset=str(raw.get("asset", "")),
            timeframes=raw.get("timeframes", ("1h",)),
            source=str(raw.get("source", "binance")),
            start_date=raw.get("start_date"),
            end_date=raw.get("end_date"),
            lookback_days=raw.get("lookback_days"),
            price_fields=tuple(raw.get("price_fields", ("open", "high", "low", "close"))),
            metadata=dict(raw.get("metadata", {})),
        )


@dataclass(frozen=True)
class TrendlineDatasetManifest:
    """Resolved dataset identity for deterministic replay and study outputs."""

    request: TrendlineDataRequest
    bar_counts: Dict[str, int]
    columns: tuple[str, ...] = ("open", "high", "low", "close")
    artifact: TrendlineArtifactRef | None = None
    start_ts: str | None = None
    end_ts: str | None = None
    manifest_version: str = "v1"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_counts: Dict[str, int] = {}
        raw_counts = dict(self.bar_counts)
        extra_timeframes = set(raw_counts) - set(self.request.timeframes)
        if extra_timeframes:
            raise ValueError("bar_counts contains timeframes outside the request")

        for timeframe in self.request.timeframes:
            if timeframe not in raw_counts:
                raise ValueError(f"Missing bar count for timeframe: {timeframe}")
            count = int(raw_counts[timeframe])
            if count < 0:
                raise ValueError("bar_counts must be >= 0")
            normalized_counts[timeframe] = count

        object.__setattr__(self, "bar_counts", normalized_counts)
        object.__setattr__(self, "columns", _normalize_names(self.columns))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "bar_counts": dict(self.bar_counts),
            "columns": list(self.columns),
            "artifact": self.artifact.to_dict() if self.artifact else None,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "manifest_version": self.manifest_version,
            "metadata": dict(self.metadata),
        }

    @property
    def manifest_hash(self) -> str:
        return _stable_hash(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "TrendlineDatasetManifest":
        raw = dict(payload or {})
        artifact_payload = raw.get("artifact")
        return cls(
            request=TrendlineDataRequest.from_dict(raw.get("request")),
            bar_counts={str(key): int(value) for key, value in dict(raw.get("bar_counts", {})).items()},
            columns=tuple(raw.get("columns", ("open", "high", "low", "close"))),
            artifact=TrendlineArtifactRef.from_dict(artifact_payload) if artifact_payload else None,
            start_ts=raw.get("start_ts"),
            end_ts=raw.get("end_ts"),
            manifest_version=str(raw.get("manifest_version", "v1")),
            metadata=dict(raw.get("metadata", {})),
        )


__all__ = [
    "TrendlineArtifactRef",
    "TrendlineDataRequest",
    "TrendlineDatasetManifest",
    "normalize_timeframes",
]