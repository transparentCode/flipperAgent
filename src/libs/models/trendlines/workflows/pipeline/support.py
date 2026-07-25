"""Core support helpers for the trendlines pipeline workflow."""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

import pandas as pd

from app.trendlines.data import TrendlineArtifactRef, TrendlineDataRequest, TemporalSplitManifest, TemporalSplitSpec, normalize_timeframes
from app.trendlines.workflows.common.contracts import PIPELINE_WORKFLOW_SEMANTICS_VERSION
from app.trendlines.workflows.common.promotion import TRENDLINE_PIPELINE_PROMOTION_FITNESS_THRESHOLD

PIPELINE_PROMOTION_FITNESS_THRESHOLD = TRENDLINE_PIPELINE_PROMOTION_FITNESS_THRESHOLD


def _index_to_date_str(index_value: Any) -> Optional[str]:
    try:
        return pd.Timestamp(index_value).strftime("%Y-%m-%d")
    except Exception:
        return None


def build_pipeline_data_request(
    asset: str,
    timeframes: str | List[str] | tuple[str, ...],
    *,
    lookback_days: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    source: str = "provided_dataset",
    metadata: Optional[Dict[str, Any]] = None,
) -> TrendlineDataRequest:
    return TrendlineDataRequest(
        asset=asset,
        timeframes=normalize_timeframes(timeframes),
        source=source,
        start_date=start_date,
        end_date=end_date,
        lookback_days=lookback_days,
        metadata=dict(metadata or {}),
    )


def build_pipeline_artifact_ref(
    asset: str,
    timeframe: str,
    spec: TemporalSplitSpec,
) -> TrendlineArtifactRef:
    return TrendlineArtifactRef(
        artifact_root="app/trendlines/results",
        relative_path=f"pipeline/{asset}_{timeframe}_optimization.json",
        label="trendlines_pipeline_optimization_result",
        content_type="application/json",
        semantics_version=PIPELINE_WORKFLOW_SEMANTICS_VERSION,
        metadata={
            "asset": asset,
            "timeframe": timeframe,
            "objective": "maximize_trendline_line_fitness",
            "spec_hash": spec.spec_hash,
        },
    )


def build_pipeline_split_manifest_ref(
    asset: str,
    timeframe: str,
    manifest: TemporalSplitManifest,
) -> TrendlineArtifactRef:
    return TrendlineArtifactRef(
        artifact_root="app/trendlines/results",
        relative_path=f"pipeline/{asset}_{timeframe}_split_manifest.json",
        label="trendlines_pipeline_split_manifest",
        content_type="application/json",
        semantics_version=PIPELINE_WORKFLOW_SEMANTICS_VERSION,
        metadata={
            "asset": asset,
            "timeframe": timeframe,
            "n_bars": manifest.n_bars,
            "n_folds": len(manifest.folds),
            "spec_hash": manifest.spec.spec_hash,
            "split_policy_version": manifest.spec.policy_version,
        },
    )


def _merge_param_dicts(*dicts: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-merge multiple param override dicts left-to-right."""

    result: Dict[str, Any] = {}
    for payload in dicts:
        _deep_merge(result, copy.deepcopy(payload))
    return result


def _deep_merge(base: dict, override: dict) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


__all__ = [
    "PIPELINE_PROMOTION_FITNESS_THRESHOLD",
    "build_pipeline_artifact_ref",
    "build_pipeline_data_request",
    "build_pipeline_split_manifest_ref",
]