"""Config resolution: merge optimizable defaults → asset/TF overrides → derived params.

This is the single resolution seam that produces a fully-resolved config for one
(asset, timeframe) pipeline execution. Called at the facade entrypoint.

Resolution order:
1. Start with OptimizableDefaults from TrendlinesConfig
2. Override with per-asset/TF values if present in assets[asset].timeframes[tf]
3. Compute AssetProfile from DataFrame
4. Compute derived params from AssetProfile
5. Build state transition table
6. Assemble ResolvedConfig (frozen, ready for pipeline)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

import pandas as pd

from .asset_profile import AssetProfile
from .boundary_config import BoundaryAdapterConfig
from .derive import compute_all_derived
from .evaluation_config import EvaluationConfig
from .search_grid_config import GridSearchConfig
from .state_transitions import build_state_transition_table

if TYPE_CHECKING:
    from .base_config import TrendlinesConfig


@dataclass(frozen=True)
class ResolvedSignalConfig:
    """Fully resolved signal params for a single pipeline execution.

    Combines optimizable (from config) and derived (from AssetProfile) params.
    Hardcoded constants are NOT here — they live in the signal extractor modules.
    """

    # Optimizable — from defaults or per-asset/TF overrides
    asymmetry_threshold: float = 0.3
    squeeze_threshold: float = 3.0
    convergence_rate_threshold: float = 0.2
    wick_rejection_ratio: float = 0.5

    # Derived — from AssetProfile
    min_history: int = 3
    slope_match_tol: float = 0.05
    slope_accel_threshold: float = 0.01
    hold_bars: int = 3
    volume_lookback: int = 20
    parallel_tol: float = 0.02
    flat_tol: float = 0.01
    full_confidence_touches_structural: float = 5.0
    full_confidence_touches_pattern: float = 8.0

    # Derived — state transition table
    state_transitions: Dict[Tuple[str, str], Tuple[float, float]] = field(
        default_factory=dict
    )

    # Signal weights
    default_weight: float = 1.0
    weights: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedConfig:
    """Fully resolved config for a single (asset, timeframe) pipeline execution.

    This is the canonical config object passed through the pipeline after
    resolution. It combines:
    - Pipeline choice (extractor, fitter)
    - Resolved signal params (optimizable + derived)
    - Resolved boundary params (optimizable + derived)
    - Protocol (frozen research methodology)
    - Search grids (for optimization workflow)
    - AssetProfile (for downstream introspection)
    - Asset metadata
    """

    extractor: str = "fractal"
    fitter: str = "pathfinding"
    signals: ResolvedSignalConfig = field(default_factory=ResolvedSignalConfig)
    boundary: BoundaryAdapterConfig = field(default_factory=BoundaryAdapterConfig)
    protocol: EvaluationConfig = field(default_factory=EvaluationConfig)
    search_grids: GridSearchConfig = field(default_factory=GridSearchConfig)
    profile: Optional[AssetProfile] = None
    asset: str = ""
    timeframe: str = ""
    asset_metadata: Dict[str, Any] = field(default_factory=dict)


def resolve_pipeline_config(
    config: "TrendlinesConfig",
    asset: str,
    timeframe: str,
    *,
    execution_mode: Any,
):
    """Resolve one fully explicit extractor/fitter pipeline configuration.

    Research preparation uses this seam so component defaults cannot silently
    become part of a study. The registry validates names and execution policy
    before the typed config is returned.
    """

    from .base_config import TrendlinePipelineConfig, TrendlinesConfig
    from libs.models.trendlines.pivots.capabilities import normalize_execution_mode
    from libs.models.trendlines.registry import (
        DEPRECATED_FITTER_ALIASES,
        build_extractor,
        build_fitter,
        canonical_extractor_name,
    )

    if not isinstance(config, TrendlinesConfig):
        raise TypeError("config must be a TrendlinesConfig")
    asset_name = str(asset).strip().upper()
    timeframe_name = str(timeframe).strip()
    if not asset_name or not timeframe_name:
        raise ValueError("asset and timeframe are required")
    mode = normalize_execution_mode(execution_mode)

    extractor = canonical_extractor_name(config.extractor)
    fitter_raw = str(config.fitter).strip().lower()
    fitter = DEPRECATED_FITTER_ALIASES.get(fitter_raw, fitter_raw)
    extractor_params = dict(config.extractor_params)
    fitter_params = dict(config.fitter_params)

    asset_cfg = config.assets.get(asset_name) or config.assets.get(str(asset).strip())
    tf_cfg = asset_cfg.timeframes.get(timeframe_name) if asset_cfg else None
    if tf_cfg is not None:
        if tf_cfg.extractor is not None:
            overridden_extractor = canonical_extractor_name(tf_cfg.extractor)
            if overridden_extractor != extractor:
                extractor_params = {}
            extractor = overridden_extractor
        if tf_cfg.fitter is not None:
            fitter_raw = str(tf_cfg.fitter).strip().lower()
            overridden_fitter = DEPRECATED_FITTER_ALIASES.get(fitter_raw, fitter_raw)
            if overridden_fitter != fitter:
                fitter_params = {}
            fitter = overridden_fitter
        if tf_cfg.extractor_params is not None:
            extractor_params.update(dict(tf_cfg.extractor_params))
        if tf_cfg.fitter_params is not None:
            fitter_params.update(dict(tf_cfg.fitter_params))

    if not extractor_params:
        raise ValueError(f"No explicit extractor parameters resolved for '{extractor}'")
    if not fitter_params:
        raise ValueError(f"No explicit fitter parameters resolved for '{fitter}'")

    # Construction is validation only; research preparation never executes a model.
    build_extractor(extractor, execution_mode=mode, **extractor_params)
    build_fitter(fitter, **fitter_params)
    return TrendlinePipelineConfig(
        extractor=extractor,
        fitter=fitter,
        extractor_params=extractor_params,
        fitter_params=fitter_params,
        trendlines_config=config,
    )


def resolve_asset_config(
    root: "TrendlinesConfig",
    asset: str,
    timeframe: str,
    df: pd.DataFrame,
    *,
    fit_result: Any | None = None,
) -> ResolvedConfig:
    """Resolve a fully concrete config for one (asset, timeframe) call.

    This is the single entrypoint for config resolution. It:
    1. Reads optimizable defaults
    2. Overlays per-asset/TF overrides
    3. Builds AssetProfile from df
    4. Computes derived params
    5. Builds state transition table
    6. Returns a frozen ResolvedConfig
    """
    # ── 1. Optimizable defaults ──
    opt = root.defaults
    params: Dict[str, Any] = {
        "interaction_tolerance_atr": opt.interaction_tolerance_atr,
        "asymmetry_threshold": opt.asymmetry_threshold,
        "convergence_rate_threshold": opt.convergence_rate_threshold,
        "wick_rejection_ratio": opt.wick_rejection_ratio,
        "squeeze_threshold": opt.squeeze_threshold,
    }

    # ── 2. Per-asset/TF overrides ──
    asset_cfg = root.assets.get(asset)
    if asset_cfg is not None:
        tf_cfg = asset_cfg.timeframes.get(timeframe)
        if tf_cfg is not None:
            for key in params:
                val = getattr(tf_cfg, key, None)
                if val is not None:
                    params[key] = val

    # ── 3. Build AssetProfile ──
    profile = AssetProfile.from_dataframe(df, timeframe, fit_result=fit_result)

    # ── 4. Compute derived params ──
    derived = compute_all_derived(profile)

    # ── 5. State transition table ──
    transitions = build_state_transition_table()

    # ── 6. Assemble resolved config ──
    signal_weights: Dict[str, float] = {}
    if root.signal_weights:
        signal_weights = dict(root.signal_weights)

    signals = ResolvedSignalConfig(
        asymmetry_threshold=float(params["asymmetry_threshold"]),
        squeeze_threshold=float(params["squeeze_threshold"]),
        convergence_rate_threshold=float(params["convergence_rate_threshold"]),
        wick_rejection_ratio=float(params["wick_rejection_ratio"]),
        min_history=int(derived["min_history"]),
        slope_match_tol=float(derived["slope_match_tol"]),
        slope_accel_threshold=float(derived["slope_accel_threshold"]),
        hold_bars=int(derived["hold_bars"]),
        volume_lookback=int(derived["volume_lookback"]),
        parallel_tol=float(derived["parallel_tol"]),
        flat_tol=float(derived["flat_tol"]),
        full_confidence_touches_structural=float(derived["full_confidence_touches_structural"]),
        full_confidence_touches_pattern=float(derived["full_confidence_touches_pattern"]),
        state_transitions=transitions,
        default_weight=root.signal_default_weight,
        weights=signal_weights,
    )

    boundary = BoundaryAdapterConfig(
        interaction_tolerance_atr=float(params["interaction_tolerance_atr"]),
        atr_window=int(derived["atr_window"]),
    )

    asset_metadata: Dict[str, Any] = {}
    if asset_cfg is not None:
        asset_metadata = dict(asset_cfg.metadata)

    return ResolvedConfig(
        extractor=root.extractor,
        fitter=root.fitter,
        signals=signals,
        boundary=boundary,
        protocol=root.protocol,
        search_grids=root.search_grids,
        profile=profile,
        asset=asset,
        timeframe=timeframe,
        asset_metadata=asset_metadata,
    )


# ── Oscillator config resolution ──────────────────────────────────────────


@dataclass(frozen=True)
class ResolvedOscillatorConfig:
    """Fully resolved config for one oscillator-space pipeline execution.

    Merges: oscillator_defaults → per-oscillator overrides → TF-derived params.
    Does NOT compute price-ratio derived params.
    """

    extractor: str = "fractal"
    fitter: str = "least_squares"
    extractor_params: Dict[str, Any] = field(default_factory=dict)
    fitter_params: Dict[str, Any] = field(default_factory=dict)
    lookback_bars: int = 80
    interaction_tolerance_atr: float = 1.0
    atr_window: int = 14
    oscillator_type: str = "rsi"
    is_bounded: bool = False
    value_range: Optional[tuple] = None


def resolve_oscillator_config(
    root: "TrendlinesConfig",
    oscillator_type: str,
    timeframe: str,
    df: pd.DataFrame,
) -> ResolvedOscillatorConfig:
    """Resolve oscillator-space config for one pipeline execution.

    Resolution order:
    1. Start with oscillator_defaults from TrendlinesConfig
    2. Override with per-oscillator values (oscillator_overrides[type])
    3. Compute TF-derived params (hold_bars, atr_window) — safe for oscillator space
    4. Return frozen ResolvedOscillatorConfig
    """
    from .derive import compute_oscillator_derived
    from .oscillator_profile import OscillatorProfile

    osc_def = root.oscillator_defaults
    osc_ov = root.oscillator_overrides.get(oscillator_type.lower())

    # ── 1. Base from oscillator_defaults ──
    extractor = osc_def.extractor
    fitter = osc_def.fitter
    extractor_params = dict(osc_def.extractor_params)
    fitter_params = dict(osc_def.fitter_params)
    lookback_bars = osc_def.lookback_bars
    interaction_tolerance_atr = osc_def.interaction_tolerance_atr
    atr_window = osc_def.atr_window
    is_bounded = False
    value_range = None

    # ── 2. Per-oscillator overrides ──
    if osc_ov is not None:
        is_bounded = osc_ov.is_bounded
        if osc_ov.value_range_lo is not None and osc_ov.value_range_hi is not None:
            value_range = (osc_ov.value_range_lo, osc_ov.value_range_hi)
        if osc_ov.extractor is not None:
            extractor = osc_ov.extractor
        if osc_ov.fitter is not None:
            fitter = osc_ov.fitter
        if osc_ov.extractor_params is not None:
            extractor_params = dict(osc_ov.extractor_params)
        if osc_ov.fitter_params is not None:
            fitter_params = dict(osc_ov.fitter_params)
        if osc_ov.lookback_bars is not None:
            lookback_bars = osc_ov.lookback_bars
        if osc_ov.interaction_tolerance_atr is not None:
            interaction_tolerance_atr = osc_ov.interaction_tolerance_atr
        if osc_ov.atr_window is not None:
            atr_window = osc_ov.atr_window

    # ── 3. TF-derived params (safe for oscillators) ──
    profile = OscillatorProfile.from_dataframe(
        df, timeframe, oscillator_type,
        is_bounded=is_bounded,
        value_range=value_range,
    )
    derived = compute_oscillator_derived(profile.tf_minutes, profile.bar_duration_hours)
    atr_window = int(derived["atr_window"])

    return ResolvedOscillatorConfig(
        extractor=extractor,
        fitter=fitter,
        extractor_params=extractor_params,
        fitter_params=fitter_params,
        lookback_bars=lookback_bars,
        interaction_tolerance_atr=interaction_tolerance_atr,
        atr_window=atr_window,
        oscillator_type=oscillator_type.lower(),
        is_bounded=is_bounded,
        value_range=value_range,
    )


__all__ = [
    "ResolvedConfig",
    "ResolvedOscillatorConfig",
    "ResolvedSignalConfig",
    "resolve_asset_config",
    "resolve_pipeline_config",
    "resolve_oscillator_config",
]
