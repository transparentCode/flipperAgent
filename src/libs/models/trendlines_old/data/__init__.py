"""Trendlines-owned data selection and manifest contracts."""

from app.trendlines.data.contracts import (
    TrendlineArtifactRef,
    TrendlineDataRequest,
    TrendlineDatasetManifest,
    normalize_timeframes,
)
from app.trendlines.data.fetchers import (
    TrendlineDatasetLoader,
    build_dataset_manifest,
    load_dataset,
)
from app.trendlines.data.artifacts import (
    artifact_path,
    read_dataset_manifest,
    read_temporal_split_manifest,
    write_dataset_manifest,
    write_temporal_split_manifest,
)
from app.trendlines.data.temporal import (
    TRENDLINE_AUTO_SPLIT_POLICY,
    TRENDLINE_AUTO_SPLIT_POLICY_VERSION,
    TemporalSplitManifest,
    TemporalSplitSpec,
    WalkForwardSplit,
    WalkForwardValidator,
    build_temporal_split_manifest,
    resolve_trendline_auto_split_spec,
)

__all__ = [
    "TrendlineDatasetLoader",
    "TRENDLINE_AUTO_SPLIT_POLICY",
    "TRENDLINE_AUTO_SPLIT_POLICY_VERSION",
    "TemporalSplitManifest",
    "TemporalSplitSpec",
    "TrendlineArtifactRef",
    "TrendlineDataRequest",
    "TrendlineDatasetManifest",
    "WalkForwardSplit",
    "WalkForwardValidator",
    "artifact_path",
    "build_dataset_manifest",
    "build_temporal_split_manifest",
    "normalize_timeframes",
    "load_dataset",
    "read_dataset_manifest",
    "read_temporal_split_manifest",
    "resolve_trendline_auto_split_spec",
    "write_dataset_manifest",
    "write_temporal_split_manifest",
]