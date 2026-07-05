"""Temporal plan resolution and pipeline specification builders."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.trendlines import TrendlinePipelineConfig
from app.trendlines.registry import get_extractor_search_grid, get_fitter_search_grid
from app.trendlines.workflows.common.contracts import PipelineOptimizationSpec, WorkflowPromotionSpec
from app.trendlines.workflows.common.promotion import TRENDLINE_PIPELINE_PROMOTION_FITNESS_THRESHOLD
from app.trendlines.data import TemporalSplitManifest, TemporalSplitSpec, build_temporal_split_manifest, resolve_trendline_auto_split_spec
from app.trendlines.config import EvaluationConfig

_eval_cfg = EvaluationConfig()


def generate_windows(
    n_bars: int,
    train_bars: int,
    test_bars: int,
    step_bars: Optional[int] = None,
) -> List[Tuple[int, int, int, int]]:
    spec = TemporalSplitSpec(
        split_kind="walk_forward",
        train_bars=train_bars,
        test_bars=test_bars,
        step_bars=step_bars or test_bars,
        purge_bars=0,
        min_train_bars=train_bars,
        policy_name="manual",
        policy_version="v1",
    )
    manifest = build_temporal_split_manifest(n_bars, spec)
    return [
        (fold.train_start, fold.train_end, fold.test_start, fold.test_end)
        for fold in manifest.folds
    ]


def _manifest_windows(manifest: TemporalSplitManifest) -> List[Tuple[int, int, int, int]]:
    return [
        (fold.train_start, fold.train_end, fold.test_start, fold.test_end)
        for fold in manifest.folds
    ]


def resolve_pipeline_temporal_plan(
    n_bars: int,
    timeframe: str,
    *,
    train_bars: Optional[int] = None,
    test_bars: Optional[int] = None,
    step_bars: Optional[int] = None,
    asset_class: str = "crypto",
    purge_bars: int = 0,
    min_train_bars: Optional[int] = None,
) -> Tuple[TemporalSplitSpec, TemporalSplitManifest]:
    if (train_bars is None) != (test_bars is None):
        raise ValueError("train_bars and test_bars must be provided together")

    if train_bars is not None and test_bars is not None:
        spec = TemporalSplitSpec(
            split_kind="walk_forward",
            train_bars=train_bars,
            test_bars=test_bars,
            step_bars=step_bars or test_bars,
            purge_bars=purge_bars,
            min_train_bars=min_train_bars or train_bars,
            timeframe=timeframe,
            asset_class=asset_class,
            policy_name="manual",
            policy_version="v1",
        )
    else:
        spec = resolve_trendline_auto_split_spec(
            timeframe,
            asset_class=asset_class,
            purge_bars=purge_bars,
            step_bars=step_bars,
            min_train_bars=min_train_bars,
        )

    return spec, build_temporal_split_manifest(n_bars, spec)


def _coerce_trendline_component_spec(
    raw: Any,
    *,
    default_name: str,
) -> tuple[str, Dict[str, Any]]:
    if raw is None:
        return default_name, {}
    if isinstance(raw, str):
        normalized = raw.strip()
        return normalized or default_name, {}
    if isinstance(raw, dict):
        name = str(raw.get("name", default_name)).strip() or default_name
        params = dict(raw.get("params", {}))
        return name, params
    raise ValueError(
        "Trendlines workflow component specs must be a string or mapping with 'name' and 'params'."
    )


def resolve_trendlines_workflow_config(
    params: Dict[str, Any],
) -> TrendlinePipelineConfig | None:
    explicit_config = (
        params.get("trendlines_config")
        or params.get("trendline_config")
        or params.get("trendlines")
    )
    if explicit_config is not None:
        if isinstance(explicit_config, TrendlinePipelineConfig):
            return explicit_config
        if isinstance(explicit_config, dict):
            return TrendlinePipelineConfig.from_dict(explicit_config)
        raise ValueError(
            "Trendlines workflow config must be a TrendlinePipelineConfig or mapping payload."
        )

    has_component_overrides = any(
        key in params
        for key in (
            "extractor",
            "fitter",
            "extractor_params",
            "fitter_params",
            "boundary_params",
            "signal_params",
        )
    )
    if not has_component_overrides:
        return None

    extractor_name, extractor_params = _coerce_trendline_component_spec(
        params.get("extractor"),
        default_name="fractal",
    )
    fitter_name, fitter_params = _coerce_trendline_component_spec(
        params.get("fitter"),
        default_name="pathfinding",
    )
    extractor_params = {**extractor_params, **dict(params.get("extractor_params", {}))}
    fitter_params = {**fitter_params, **dict(params.get("fitter_params", {}))}
    return TrendlinePipelineConfig(
        extractor=extractor_name,
        fitter=fitter_name,
        extractor_params=extractor_params,
        fitter_params=fitter_params,
        boundary_params=dict(params.get("boundary_params", {})),
        signal_params=dict(params.get("signal_params", {})),
    )


def _trendline_lookback_grid(train_bars: int) -> List[Dict[str, Any]]:
    lg = _eval_cfg.lookback_grid
    
    candidates = set()
    for frac in lg.fractions:
        candidates.add(max(lg.min_bars, min(train_bars, int(train_bars * frac))))
    candidates.add(max(lg.min_bars, train_bars))
    
    return [{"lookback_bars": bars} for bars in sorted(candidates)]


def build_pipeline_optimization_spec(
    *,
    asset: str,
    timeframe: str,
    extractor_name: str,
    dataset,
    artifact,
    temporal_split: TemporalSplitSpec,
) -> PipelineOptimizationSpec:
    search_space: Dict[str, Any] = {
        "engine": "trendlines",
        "extractor_name": extractor_name,
        "extractor_grid_size": len(get_extractor_search_grid(extractor_name)),
        "fitter_grid_size": len(get_fitter_search_grid()),
        "lookback_grid_size": len(_trendline_lookback_grid(temporal_split.train_bars)),
    }

    return PipelineOptimizationSpec(
        objective="maximize_trendline_line_fitness",
        dataset=dataset,
        artifact=artifact,
        semantics_version=artifact.semantics_version,
        search_space=search_space,
        temporal_split=temporal_split,
        promotion=WorkflowPromotionSpec(
            mode="manual_review",
            criteria={"minimum_best_fitness": TRENDLINE_PIPELINE_PROMOTION_FITNESS_THRESHOLD},
        ),
        metadata={
            "asset": asset,
            "timeframe": timeframe,
            "workflow_stages": [
                "dataset_fetch",
                "temporal_split_resolution",
                "trendlines_pipeline_evaluation",
                "parameter_search",
                "promotion_decision",
                "artifact_persistence",
            ],
            "parameter_stages": ["extractor", "fitter", "lookback"],
            "config_apply_requires_explicit_call": True,
        },
    )


__all__ = [
    "build_pipeline_optimization_spec",
    "generate_windows",
    "resolve_pipeline_temporal_plan",
    "resolve_trendlines_workflow_config",
]
