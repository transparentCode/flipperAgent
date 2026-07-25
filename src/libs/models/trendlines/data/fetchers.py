"""Injected dataset-loader helpers for trendlines-first runs."""

from __future__ import annotations

from typing import Mapping, Protocol

import pandas as pd

from app.trendlines.data.contracts import TrendlineArtifactRef, TrendlineDataRequest, TrendlineDatasetManifest


class TrendlineDatasetLoader(Protocol):
    """Callable adapter that resolves a typed request into timeframe frames."""

    def __call__(self, request: TrendlineDataRequest) -> Mapping[str, pd.DataFrame]:
        ...


def _normalize_columns(frames: Mapping[str, pd.DataFrame]) -> tuple[str, ...]:
    ordered_columns: list[str] = []
    seen: set[str] = set()
    for frame in frames.values():
        for column in frame.columns:
            name = str(column)
            if name in seen:
                continue
            seen.add(name)
            ordered_columns.append(name)
    return tuple(ordered_columns)


def _normalize_frame_map(
    request: TrendlineDataRequest,
    frames: Mapping[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    raw_frames = {str(key): value for key, value in dict(frames).items()}
    missing = [timeframe for timeframe in request.timeframes if timeframe not in raw_frames]
    extra = [timeframe for timeframe in raw_frames if timeframe not in request.timeframes]

    if missing:
        raise ValueError(f"Loader result is missing requested timeframes: {missing}")
    if extra:
        raise ValueError(f"Loader result contains unexpected timeframes: {extra}")

    normalized: dict[str, pd.DataFrame] = {}
    for timeframe in request.timeframes:
        frame = raw_frames[timeframe]
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"Loader result for {timeframe} must be a pandas DataFrame")
        normalized[timeframe] = frame.copy()
    return normalized


def build_dataset_manifest(
    request: TrendlineDataRequest,
    frames: Mapping[str, pd.DataFrame],
    *,
    artifact: TrendlineArtifactRef | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
    metadata: dict[str, object] | None = None,
) -> TrendlineDatasetManifest:
    normalized = _normalize_frame_map(request, frames)
    bar_counts = {timeframe: len(frame) for timeframe, frame in normalized.items()}

    return TrendlineDatasetManifest(
        request=request,
        bar_counts=bar_counts,
        columns=_normalize_columns(normalized) or request.price_fields,
        artifact=artifact,
        start_ts=start_ts,
        end_ts=end_ts,
        metadata=dict(metadata or {}),
    )


def load_dataset(
    request: TrendlineDataRequest,
    loader: TrendlineDatasetLoader,
    *,
    artifact: TrendlineArtifactRef | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
    metadata: dict[str, object] | None = None,
) -> tuple[dict[str, pd.DataFrame], TrendlineDatasetManifest]:
    frames = _normalize_frame_map(request, loader(request))
    manifest = build_dataset_manifest(
        request,
        frames,
        artifact=artifact,
        start_ts=start_ts,
        end_ts=end_ts,
        metadata=metadata,
    )
    return frames, manifest


__all__ = [
    "TrendlineDatasetLoader",
    "build_dataset_manifest",
    "load_dataset",
]