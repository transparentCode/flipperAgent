"""Source-agnostic research dataset preparation."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

import numpy as np
import pandas as pd

from libs.models.trendlines.config.base_config import TrendlinesConfig
from libs.models.trendlines.contracts.identity import resolve_source_ref
from libs.models.trendlines.contracts.identity import canonical_hash
from libs.models.trendlines.data.contracts import TrendlineDataRequest, TrendlineDatasetManifest
from libs.models.trendlines.signals.context import (
    BarAvailabilitySource,
    BarTimestampSemantics,
)
from libs.models.trendlines.workflows.research.contracts import (
    PreparedTrendlineResearchDataset,
    PreparedTrendlineResearchRun,
    RESEARCH_PREPARATION_SEMANTICS_VERSION,
    TrendlineResearchDataMode,
    TrendlineResearchDatasetIdentity,
    TrendlineResearchSpec,
    build_research_availability_id,
)
from libs.models.trendlines.workflows.research.synthetic import generate_synthetic_frames


class TrendlineResearchLoader(Protocol):
    """Async source bridge consumed by canonical preparation."""

    async def load(self, spec: TrendlineResearchSpec) -> Mapping[str, pd.DataFrame]:
        ...


def _availability_source(value: Any) -> BarAvailabilitySource:
    if isinstance(value, BarAvailabilitySource):
        return value
    try:
        return BarAvailabilitySource(str(value).strip().lower())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Unknown bar availability provenance: {value!r}") from exc


def _timestamp_semantics(value: Any) -> BarTimestampSemantics:
    if value is None:
        raise ValueError("bar_timestamp_semantics metadata is required")
    if isinstance(value, BarTimestampSemantics):
        return value
    try:
        return BarTimestampSemantics(str(value).strip().lower())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Unknown bar timestamp semantics: {value!r}") from exc


def _validate_datetime_index(index: Any, *, name: str) -> pd.DatetimeIndex:
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError(f"{name} must be a timezone-aware DatetimeIndex")
    if index.tz is None:
        raise ValueError(f"{name} must be timezone-aware")
    result = index.tz_convert("UTC")
    if len(result) == 0:
        raise ValueError(f"{name} must be non-empty")
    if not result.is_monotonic_increasing or not result.is_unique:
        raise ValueError(f"{name} must be ordered and unique")
    return result


def validate_research_frame(
    frame: pd.DataFrame,
    timeframe: str,
    *,
    knowledge_cutoff: datetime | None = None,
) -> tuple[pd.DataFrame, BarTimestampSemantics, BarAvailabilitySource]:
    """Validate one prepared frame without sorting or silently repairing it."""

    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"frame for {timeframe} must be a pandas DataFrame")
    if frame.empty:
        raise ValueError(f"frame for {timeframe} must be non-empty")
    if not frame.columns.is_unique:
        raise ValueError(f"frame for {timeframe} must have unique columns")
    event_index = _validate_datetime_index(frame.index, name=f"{timeframe} event index")
    required = ("open", "high", "low", "close", "volume", "bar_available_at")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"frame for {timeframe} is missing columns: {missing}")

    normalized = frame.copy()
    normalized.index = event_index
    try:
        availability_index = pd.DatetimeIndex(normalized["bar_available_at"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bar_available_at for {timeframe} must be datetime-like") from exc
    if availability_index.tz is None:
        raise ValueError(f"bar_available_at for {timeframe} must be timezone-aware")
    availability = _validate_datetime_index(
        availability_index,
        name=f"{timeframe} bar availability",
    )
    if len(availability) != len(event_index):
        raise ValueError(f"bar availability length mismatch for {timeframe}")
    provenance = _availability_source(normalized.attrs.get("bar_availability_source"))
    semantics = _timestamp_semantics(normalized.attrs.get("bar_timestamp_semantics"))
    if (
        provenance is BarAvailabilitySource.CLOSE_TIME_INDEX
        and semantics is not BarTimestampSemantics.CLOSE_TIME
    ):
        raise ValueError("close_time_index provenance requires close_time semantics")
    if semantics is BarTimestampSemantics.OPEN_TIME:
        if not (availability > event_index).all():
            raise ValueError(
                f"open_time bars require availability strictly after event time for {timeframe}"
            )
    elif not (availability == event_index).all():
        raise ValueError(
            f"close_time bars require availability equal to event time for {timeframe}"
        )
    if knowledge_cutoff is not None:
        cutoff = pd.Timestamp(knowledge_cutoff)
        if cutoff.tzinfo is None:
            raise ValueError("knowledge_cutoff must be timezone-aware")
        cutoff = cutoff.tz_convert("UTC")
        if (availability > cutoff).any():
            raise ValueError(f"frame for {timeframe} contains bars unavailable by knowledge_cutoff")
    normalized["bar_available_at"] = availability

    numeric = normalized.loc[:, ["open", "high", "low", "close", "volume"]].apply(
        pd.to_numeric,
        errors="coerce",
    )
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy()).all():
        raise ValueError(f"frame for {timeframe} contains non-finite OHLCV values")
    if (numeric["high"] < numeric[["open", "close"]].max(axis=1)).any():
        raise ValueError(f"invalid high values for {timeframe}")
    if (numeric["low"] > numeric[["open", "close"]].min(axis=1)).any():
        raise ValueError(f"invalid low values for {timeframe}")
    if (numeric["low"] > numeric["high"]).any() or (numeric["volume"] < 0).any():
        raise ValueError(f"invalid OHLCV shape for {timeframe}")
    for column in numeric.columns:
        normalized[column] = numeric[column]

    normalized.attrs = dict(frame.attrs)
    normalized.attrs["bar_availability_source"] = provenance.value
    normalized.attrs["bar_timestamp_semantics"] = semantics.value
    return normalized, semantics, provenance


async def _resolve_loader_frames(
    spec: TrendlineResearchSpec,
    loader: TrendlineResearchLoader | Mapping[str, pd.DataFrame] | Any | None,
) -> Mapping[str, pd.DataFrame]:
    if spec.data.mode is TrendlineResearchDataMode.SYNTHETIC:
        if loader is not None:
            raise ValueError("synthetic preparation does not accept a provider loader")
        return generate_synthetic_frames(spec)
    if loader is None:
        raise ValueError(f"{spec.data.mode.value} preparation requires an injected loader")
    if isinstance(loader, Mapping):
        return loader
    if hasattr(loader, "load"):
        result = loader.load(spec)
    elif callable(loader):
        result = loader(spec)
    else:
        raise TypeError("loader must be a mapping, callable, or async loader")
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, Mapping):
        raise TypeError("research loader must return a timeframe-to-DataFrame mapping")
    return result


async def prepare_research_dataset(
    spec: TrendlineResearchSpec,
    *,
    loader: TrendlineResearchLoader | Mapping[str, pd.DataFrame] | Any | None = None,
) -> PreparedTrendlineResearchDataset:
    """Prepare and identify data; never execute trendline model code."""

    raw_frames = await _resolve_loader_frames(spec, loader)
    raw_keys = tuple(str(key) for key in raw_frames)
    missing = [timeframe for timeframe in spec.timeframes if timeframe not in raw_keys]
    extra = [timeframe for timeframe in raw_keys if timeframe not in spec.timeframes]
    if missing:
        raise ValueError(f"Loader result is missing requested timeframes: {missing}")
    if extra:
        raise ValueError(f"Loader result contains unexpected timeframes: {extra}")

    normalized_frames: dict[str, pd.DataFrame] = {}
    source_refs = {}
    availability_ids: dict[str, str] = {}
    semantics_by_tf: dict[str, BarTimestampSemantics] = {}
    provenance_by_tf: dict[str, BarAvailabilitySource] = {}
    for timeframe in spec.timeframes:
        cutoff = spec.data.knowledge_cutoff if spec.data.mode is TrendlineResearchDataMode.BINANCE else None
        normalized, semantics, provenance = validate_research_frame(
            raw_frames[timeframe],
            timeframe,
            knowledge_cutoff=cutoff,
        )
        normalized_frames[timeframe] = normalized
        semantics_by_tf[timeframe] = semantics
        provenance_by_tf[timeframe] = provenance
        source_refs[timeframe] = resolve_source_ref(normalized)
        availability_ids[timeframe] = build_research_availability_id(
            source_ref=source_refs[timeframe],
            bar_available_at=pd.DatetimeIndex(normalized["bar_available_at"]),
            timestamp_semantics=semantics,
            availability_source=provenance,
        )

    semantics = tuple(semantics_by_tf.values())
    if not semantics or any(value is not semantics[0] for value in semantics[1:]):
        raise ValueError("all prepared timeframes must use one timestamp semantics")
    request = TrendlineDataRequest(
        asset=spec.asset,
        timeframes=spec.timeframes,
        source=spec.data.mode.value,
        start_date=(
            spec.data.event_start.isoformat()
            if spec.data.event_start is not None
            else normalized_frames[spec.timeframes[0]].index[0].isoformat()
        ),
        end_date=(
            spec.data.knowledge_cutoff.isoformat()
            if spec.data.knowledge_cutoff is not None
            else normalized_frames[spec.timeframes[0]].index[-1].isoformat()
        ),
        price_fields=("open", "high", "low", "close", "volume"),
    )
    manifest = TrendlineDatasetManifest(
        request=request,
        bar_counts={timeframe: len(normalized_frames[timeframe]) for timeframe in spec.timeframes},
        columns=("open", "high", "low", "close", "volume", "bar_available_at"),
        start_ts=normalized_frames[spec.timeframes[0]].index[0].isoformat(),
        end_ts=normalized_frames[spec.timeframes[0]].index[-1].isoformat(),
        metadata={
            "research_data_mode": spec.data.mode.value,
            "bar_timestamp_semantics": semantics[0].value,
            "bar_availability_sources": {
                key: value.value for key, value in provenance_by_tf.items()
            },
            "availability_evidence": {
                key: {
                    "availability_id": availability_ids[key],
                    "availability_start": normalized_frames[key]["bar_available_at"].iloc[0].isoformat(),
                    "availability_end": normalized_frames[key]["bar_available_at"].iloc[-1].isoformat(),
                    "availability_source": provenance_by_tf[key].value,
                    "timestamp_semantics": semantics_by_tf[key].value,
                }
                for key in spec.timeframes
            },
        },
    )
    identity = TrendlineResearchDatasetIdentity.from_parts(
        data_spec=spec.data,
        manifest=manifest,
        source_refs=source_refs,
        timestamp_semantics=semantics[0],
        availability_sources=provenance_by_tf,
        availability_ids=availability_ids,
    )
    return PreparedTrendlineResearchDataset(
        frames=normalized_frames,
        manifest=manifest,
        source_refs=source_refs,
        identity=identity,
    )


async def prepare_trendline_research(
    spec: TrendlineResearchSpec,
    *,
    trendlines_config: TrendlinesConfig,
    loader: TrendlineResearchLoader | Mapping[str, pd.DataFrame] | Any | None = None,
) -> PreparedTrendlineResearchRun:
    """Prepare deterministic research data/configuration without model execution."""

    from libs.models.trendlines.workflows.research.config import resolve_research_config

    configuration = resolve_research_config(spec, trendlines_config)
    dataset = await prepare_research_dataset(spec, loader=loader)
    preparation_id = canonical_hash(
        {
            "spec": spec.to_dict(),
            "dataset_id": dataset.dataset_id,
            "research_configuration_id": configuration.research_configuration_id,
        },
        semantics_version=RESEARCH_PREPARATION_SEMANTICS_VERSION,
    )
    return PreparedTrendlineResearchRun(
        spec=spec,
        dataset=dataset,
        configuration=configuration,
        preparation_id=preparation_id,
    )


__all__ = [
    "TrendlineResearchLoader",
    "prepare_research_dataset",
    "prepare_trendline_research",
    "validate_research_frame",
]
