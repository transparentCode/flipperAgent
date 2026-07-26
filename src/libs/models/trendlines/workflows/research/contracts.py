"""Source-agnostic contracts for deterministic trendline research preparation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import pandas as pd

from libs.models.trendlines.config.base_config import TrendlinePipelineConfig
from libs.models.trendlines.data.contracts import TrendlineDatasetManifest
from libs.models.trendlines.contracts.identity import (
    TrendlineSourceRef,
    canonical_hash,
)
from libs.models.trendlines.signals.context import (
    BarAvailabilitySource,
    BarTimestampSemantics,
)


RESEARCH_DATA_SEMANTICS_VERSION = "trendlines.research-data.v1"
RESEARCH_AVAILABILITY_ID_SEMANTICS_VERSION = (
    "trendlines.research-availability-id.v1"
)
SYNTHETIC_GENERATOR_SEMANTICS_VERSION = "trendlines.synthetic-generator.v1"
RESEARCH_CONFIG_SEMANTICS_VERSION = "trendlines.research-config.v1"
RESEARCH_PREPARATION_SEMANTICS_VERSION = "trendlines.research-preparation.v1"


class TrendlineResearchPurpose(str, Enum):
    """Reason for preparing a research dataset."""

    SMOKE = "smoke"
    RESEARCH = "research"


class TrendlineResearchDataMode(str, Enum):
    """Data source selected for research preparation."""

    SYNTHETIC = "synthetic"
    INJECTED = "injected"
    BINANCE = "binance"


def build_research_availability_id(
    *,
    source_ref: TrendlineSourceRef,
    bar_available_at: pd.DatetimeIndex,
    timestamp_semantics: BarTimestampSemantics,
    availability_source: BarAvailabilitySource,
) -> str:
    """Hash one exact, UTC-normalized bar-availability schedule."""

    if not isinstance(source_ref, TrendlineSourceRef):
        raise TypeError("source_ref must be a TrendlineSourceRef")
    if not isinstance(timestamp_semantics, BarTimestampSemantics):
        raise TypeError("timestamp_semantics must be a BarTimestampSemantics")
    if not isinstance(availability_source, BarAvailabilitySource):
        raise TypeError("availability_source must be a BarAvailabilitySource")
    if not isinstance(bar_available_at, pd.DatetimeIndex):
        raise TypeError("bar_available_at must be a DatetimeIndex")
    if bar_available_at.tz is None:
        raise ValueError("bar_available_at must be timezone-aware")
    availability = bar_available_at.tz_convert("UTC")
    if len(availability) == 0:
        raise ValueError("bar_available_at must be non-empty")
    if not availability.is_monotonic_increasing or not availability.is_unique:
        raise ValueError("bar_available_at must be ordered and unique")
    return canonical_hash(
        {
            "source_id": source_ref.source_id,
            "bar_available_at_utc_ns": availability.asi8,
            "timestamp_semantics": timestamp_semantics.value,
            "availability_source": availability_source.value,
            "semantics_version": RESEARCH_AVAILABILITY_ID_SEMANTICS_VERSION,
        },
        semantics_version=RESEARCH_AVAILABILITY_ID_SEMANTICS_VERSION,
    )


def _utc_datetime(value: Any, *, name: str) -> datetime:
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be datetime-like")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware UTC")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class TrendlineResearchDataSpec:
    """Explicit, bounded source request for one research preparation."""

    mode: TrendlineResearchDataMode
    seed: int | None = None
    start_time: datetime | None = None
    bar_counts: Mapping[str, int] = field(default_factory=dict)
    event_start: datetime | None = None
    knowledge_cutoff: datetime | None = None

    def __post_init__(self) -> None:
        mode = self.mode
        if not isinstance(mode, TrendlineResearchDataMode):
            try:
                mode = TrendlineResearchDataMode(str(mode).strip().lower())
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Unknown research data mode: {self.mode!r}") from exc
        raw_counts = dict(self.bar_counts)
        if mode is TrendlineResearchDataMode.BINANCE and raw_counts:
            raise ValueError("bar_counts is incompatible with binance mode")
        if mode is TrendlineResearchDataMode.INJECTED and raw_counts:
            raise ValueError("bar_counts is incompatible with injected mode")
        counts: dict[str, int] = {}
        for key, raw_value in raw_counts.items():
            if isinstance(raw_value, bool) or not isinstance(raw_value, int):
                raise ValueError("bar_counts must contain positive integers")
            counts[str(key).strip()] = raw_value
        if any(not key for key in counts):
            raise ValueError("bar_counts contains an empty timeframe")
        seed = self.seed
        if mode is TrendlineResearchDataMode.SYNTHETIC:
            if self.event_start is not None:
                raise ValueError("event_start is incompatible with synthetic mode")
            if self.knowledge_cutoff is not None:
                raise ValueError("knowledge_cutoff is incompatible with synthetic mode")
            if seed is None or isinstance(seed, bool) or not isinstance(seed, int):
                raise ValueError("synthetic mode requires an integer seed")
            if self.start_time is None:
                raise ValueError("synthetic mode requires a UTC start_time")
            start_time = _utc_datetime(self.start_time, name="start_time")
            if not counts:
                raise ValueError("synthetic mode requires bar_counts")
            if any(value <= 0 for value in counts.values()):
                raise ValueError("synthetic bar counts must be positive integers")
            object.__setattr__(self, "start_time", start_time)
        elif mode is TrendlineResearchDataMode.BINANCE:
            if seed is not None:
                raise ValueError("seed is incompatible with binance mode")
            if self.start_time is not None:
                raise ValueError("start_time is incompatible with binance mode")
            if self.event_start is None or self.knowledge_cutoff is None:
                raise ValueError("binance mode requires event_start and knowledge_cutoff")
            event_start = _utc_datetime(self.event_start, name="event_start")
            knowledge_cutoff = _utc_datetime(
                self.knowledge_cutoff,
                name="knowledge_cutoff",
            )
            if knowledge_cutoff < event_start:
                raise ValueError("knowledge_cutoff must be >= event_start")
            object.__setattr__(self, "event_start", event_start)
            object.__setattr__(self, "knowledge_cutoff", knowledge_cutoff)
        else:
            for name, value in (
                ("seed", seed),
                ("start_time", self.start_time),
                ("bar_counts", counts),
                ("event_start", self.event_start),
                ("knowledge_cutoff", self.knowledge_cutoff),
            ):
                incompatible = bool(value) if name == "bar_counts" else value is not None
                if incompatible:
                    raise ValueError(f"{name} is incompatible with injected mode")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "bar_counts", counts)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"mode": self.mode.value}
        if self.mode is TrendlineResearchDataMode.SYNTHETIC:
            payload.update(
                {
                    "seed": self.seed,
                    "start_time": self.start_time.isoformat(),
                    "bar_counts": dict(self.bar_counts),
                }
            )
        elif self.mode is TrendlineResearchDataMode.BINANCE:
            payload.update(
                {
                    "event_start": self.event_start.isoformat(),
                    "knowledge_cutoff": self.knowledge_cutoff.isoformat(),
                }
            )
        return payload


@dataclass(frozen=True)
class TrendlineResearchSpec:
    """Validated purpose, scope, and explicit data request."""

    purpose: TrendlineResearchPurpose
    data: TrendlineResearchDataSpec
    asset: str
    timeframes: tuple[str, ...]
    primary_timeframe: str

    def __post_init__(self) -> None:
        purpose = self.purpose
        if not isinstance(purpose, TrendlineResearchPurpose):
            try:
                purpose = TrendlineResearchPurpose(str(purpose).strip().lower())
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Unknown research purpose: {self.purpose!r}") from exc
        if not isinstance(self.data, TrendlineResearchDataSpec):
            raise TypeError("data must be a TrendlineResearchDataSpec")
        asset = str(self.asset).strip().upper()
        if not asset:
            raise ValueError("asset is required")
        timeframes = tuple(str(value).strip() for value in self.timeframes)
        if not timeframes or any(not value for value in timeframes):
            raise ValueError("at least one non-empty timeframe is required")
        if len(set(timeframes)) != len(timeframes):
            raise ValueError("timeframes must be unique and ordered")
        primary = str(self.primary_timeframe).strip()
        if primary not in timeframes:
            raise ValueError("primary_timeframe must be present in timeframes")
        if purpose is TrendlineResearchPurpose.SMOKE and self.data.mode is TrendlineResearchDataMode.BINANCE:
            raise ValueError("SMOKE purpose cannot use BINANCE data")
        if self.data.mode is TrendlineResearchDataMode.SYNTHETIC:
            missing = set(timeframes) - set(self.data.bar_counts)
            extra = set(self.data.bar_counts) - set(timeframes)
            if missing or extra:
                raise ValueError(
                    f"synthetic bar_counts must match requested timeframes; missing={sorted(missing)}, extra={sorted(extra)}"
                )
        object.__setattr__(self, "purpose", purpose)
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "timeframes", timeframes)
        object.__setattr__(self, "primary_timeframe", primary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose.value,
            "data": self.data.to_dict(),
            "asset": self.asset,
            "timeframes": list(self.timeframes),
            "primary_timeframe": self.primary_timeframe,
        }


@dataclass(frozen=True)
class TrendlineResearchDatasetIdentity:
    """Content identity for prepared frames without embedding frame values."""

    dataset_id: str
    manifest: TrendlineDatasetManifest
    source_refs: Mapping[str, TrendlineSourceRef]
    timestamp_semantics: BarTimestampSemantics
    availability_sources: Mapping[str, BarAvailabilitySource]
    availability_ids: Mapping[str, str]
    semantics_version: str = RESEARCH_DATA_SEMANTICS_VERSION

    def __post_init__(self) -> None:
        if not str(self.dataset_id).strip():
            raise ValueError("dataset_id must be non-empty")
        if not isinstance(self.manifest, TrendlineDatasetManifest):
            raise TypeError("manifest must be a TrendlineDatasetManifest")
        if not isinstance(self.timestamp_semantics, BarTimestampSemantics):
            raise TypeError("timestamp_semantics must be BarTimestampSemantics")
        source_refs = dict(self.source_refs)
        availability_sources = dict(self.availability_sources)
        availability_ids = dict(self.availability_ids)
        if set(source_refs) != set(self.manifest.request.timeframes):
            raise ValueError("source_refs must cover every requested timeframe")
        if set(availability_sources) != set(source_refs):
            raise ValueError("availability_sources must cover every source ref")
        if set(availability_ids) != set(source_refs):
            raise ValueError("availability_ids must cover every source ref")
        if not all(isinstance(value, TrendlineSourceRef) for value in source_refs.values()):
            raise TypeError("source_refs must contain TrendlineSourceRef values")
        if not all(isinstance(value, BarAvailabilitySource) for value in availability_sources.values()):
            raise TypeError("availability_sources must contain BarAvailabilitySource values")
        if not all(isinstance(value, str) and value.strip() for value in availability_ids.values()):
            raise ValueError("availability_ids must contain non-empty strings")
        object.__setattr__(self, "source_refs", source_refs)
        object.__setattr__(self, "availability_sources", availability_sources)
        object.__setattr__(self, "availability_ids", availability_ids)

    @classmethod
    def from_parts(
        cls,
        *,
        data_spec: TrendlineResearchDataSpec,
        manifest: TrendlineDatasetManifest,
        source_refs: Mapping[str, TrendlineSourceRef],
        timestamp_semantics: BarTimestampSemantics,
        availability_sources: Mapping[str, BarAvailabilitySource],
        availability_ids: Mapping[str, str],
    ) -> "TrendlineResearchDatasetIdentity":
        payload = {
            "data_spec": data_spec.to_dict(),
            "manifest": manifest.to_dict(),
            "source_refs": {
                key: value.to_dict() for key, value in sorted(source_refs.items())
            },
            "timestamp_semantics": timestamp_semantics.value,
            "availability_sources": {
                key: value.value for key, value in sorted(availability_sources.items())
            },
            "availability_ids": dict(sorted(availability_ids.items())),
            "semantics_version": RESEARCH_DATA_SEMANTICS_VERSION,
        }
        return cls(
            dataset_id=canonical_hash(
                payload,
                semantics_version=RESEARCH_DATA_SEMANTICS_VERSION,
            ),
            manifest=manifest,
            source_refs=source_refs,
            timestamp_semantics=timestamp_semantics,
            availability_sources=availability_sources,
            availability_ids=availability_ids,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "manifest": self.manifest.to_dict(),
            "source_refs": {
                key: value.to_dict() for key, value in sorted(self.source_refs.items())
            },
            "timestamp_semantics": self.timestamp_semantics.value,
            "availability_sources": {
                key: value.value for key, value in sorted(self.availability_sources.items())
            },
            "availability_ids": dict(sorted(self.availability_ids.items())),
            "semantics_version": self.semantics_version,
        }


@dataclass(frozen=True)
class PreparedTrendlineResearchDataset:
    """Validated multi-timeframe data and its deterministic identity."""

    frames: Mapping[str, pd.DataFrame]
    manifest: TrendlineDatasetManifest
    source_refs: Mapping[str, TrendlineSourceRef]
    identity: TrendlineResearchDatasetIdentity

    def __post_init__(self) -> None:
        frames = dict(self.frames)
        if tuple(frames) != self.manifest.request.timeframes:
            raise ValueError("frames must preserve requested timeframe order")
        object.__setattr__(self, "frames", frames)
        object.__setattr__(self, "source_refs", dict(self.source_refs))

    @property
    def dataset_id(self) -> str:
        return self.identity.dataset_id


@dataclass(frozen=True)
class PreparedTrendlineResearchConfig:
    """Fully resolved, deterministic model configuration for one study."""

    asset: str
    timeframes: tuple[str, ...]
    primary_timeframe: str
    pipeline_configs: Mapping[str, TrendlinePipelineConfig]
    root_configuration_id: str
    search_grid_identity: str
    research_configuration_id: str

    def __post_init__(self) -> None:
        configs = dict(self.pipeline_configs)
        if tuple(configs) != self.timeframes:
            raise ValueError("pipeline_configs must cover timeframes in order")
        object.__setattr__(self, "pipeline_configs", configs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframes": list(self.timeframes),
            "primary_timeframe": self.primary_timeframe,
            "pipeline_configs": {
                key: value.to_dict() for key, value in self.pipeline_configs.items()
            },
            "root_configuration_id": self.root_configuration_id,
            "search_grid_identity": self.search_grid_identity,
            "research_configuration_id": self.research_configuration_id,
        }


@dataclass(frozen=True)
class PreparedTrendlineResearchRun:
    """Preparation-only result; no model execution has occurred."""

    spec: TrendlineResearchSpec
    dataset: PreparedTrendlineResearchDataset
    configuration: PreparedTrendlineResearchConfig
    preparation_id: str

    def __post_init__(self) -> None:
        if not str(self.preparation_id).strip():
            raise ValueError("preparation_id must be non-empty")


__all__ = [
    "BarAvailabilitySource",
    "BarTimestampSemantics",
    "PreparedTrendlineResearchConfig",
    "PreparedTrendlineResearchDataset",
    "PreparedTrendlineResearchRun",
    "RESEARCH_AVAILABILITY_ID_SEMANTICS_VERSION",
    "RESEARCH_CONFIG_SEMANTICS_VERSION",
    "RESEARCH_DATA_SEMANTICS_VERSION",
    "RESEARCH_PREPARATION_SEMANTICS_VERSION",
    "SYNTHETIC_GENERATOR_SEMANTICS_VERSION",
    "TrendlineResearchDataMode",
    "TrendlineResearchDataSpec",
    "TrendlineResearchDatasetIdentity",
    "TrendlineResearchPurpose",
    "TrendlineResearchSpec",
    "build_research_availability_id",
]
