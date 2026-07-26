"""Typed config contracts for trendline runtime execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .boundary_config import BoundaryAdapterConfig
from .evaluation_config import EvaluationConfig
from .history_config import SnapshotHistoryOverride, SnapshotHistoryPolicy
from .search_grid_config import GridSearchConfig
from .signal_config import SignalConfig


# ── Per-asset / per-TF config structures ──────────────────────────────────


@dataclass(frozen=True)
class AssetTimeframeConfig:
    """Per-asset per-TF optimized param overrides.

    All fields are Optional — ``None`` means "use the global default".
    Only fields that were explicitly optimized for this (asset, TF) pair
    should be set.
    """

    interaction_tolerance_atr: Optional[float] = None
    asymmetry_threshold: Optional[float] = None
    convergence_rate_threshold: Optional[float] = None
    wick_rejection_ratio: Optional[float] = None
    squeeze_threshold: Optional[float] = None
    history: SnapshotHistoryOverride | None = None


@dataclass(frozen=True)
class AssetConfig:
    """Per-asset block: metadata + per-TF overrides."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    timeframes: Dict[str, AssetTimeframeConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class OptimizableDefaults:
    """Global defaults for the 5 optimizable params.

    These are the universe-level baselines. Per-asset/TF overrides in
    ``AssetConfig.timeframes`` take precedence when present.
    """

    interaction_tolerance_atr: float = 0.25
    asymmetry_threshold: float = 0.3
    convergence_rate_threshold: float = 0.2
    wick_rejection_ratio: float = 0.5
    squeeze_threshold: float = 3.0


# ── Oscillator config ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class OscillatorDefaults:
    """Default pipeline params for oscillator-space trendlines.

    Oscillators bypass ``resolve_asset_config()`` because derived params
    (ATR normalization, slope matching) assume price-scale data. Instead,
    these explicit defaults are used to build ``TrendlinePipelineConfig``
    directly.
    """

    lookback_bars: int = 80
    extractor: str = "fractal"
    fitter: str = "least_squares"
    extractor_params: Dict[str, Any] = field(default_factory=lambda: {"window_left": 5, "window_right": 5})
    fitter_params: Dict[str, Any] = field(default_factory=lambda: {"pivot_window": 2})
    interaction_tolerance_atr: float = 1.0
    atr_window: int = 14


@dataclass(frozen=True)
class OscillatorOverride:
    """Per-oscillator-type overrides (e.g., RSI, MACD).

    Fields set to ``None`` fall back to ``OscillatorDefaults``.
    """

    is_bounded: bool = False
    value_range_lo: Optional[float] = None
    value_range_hi: Optional[float] = None
    lookback_bars: Optional[int] = None
    extractor: Optional[str] = None
    fitter: Optional[str] = None
    extractor_params: Optional[Dict[str, Any]] = None
    fitter_params: Optional[Dict[str, Any]] = None
    interaction_tolerance_atr: Optional[float] = None
    atr_window: Optional[int] = None


# ── Root config ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TrendlinesConfig:
    """Root config. Loaded from trendlines.yaml or defaults.py fallback.

    Structure:
    - ``extractor`` / ``fitter``: pipeline component choices
    - ``defaults``: universe-level optimizable param baselines
    - ``assets``: per-asset metadata + per-TF optimized overrides
    - ``protocol``: frozen research methodology (evaluation, walk-forward, etc.)
    - ``search_grids``: component hyperparameter sweep grids
    - ``signal_default_weight`` / ``signal_weights``: signal aggregation weights

    The old ``signals`` / ``boundary`` / ``evaluation`` top-level fields are
    replaced by the tiered structure (defaults → assets → derived at runtime).
    """

    extractor: str = "fractal"
    fitter: str = "pathfinding"
    defaults: OptimizableDefaults = field(default_factory=OptimizableDefaults)
    assets: Dict[str, AssetConfig] = field(default_factory=dict)
    oscillator_defaults: OscillatorDefaults = field(default_factory=OscillatorDefaults)
    oscillator_overrides: Dict[str, OscillatorOverride] = field(default_factory=dict)
    protocol: EvaluationConfig = field(default_factory=EvaluationConfig)
    search_grids: GridSearchConfig = field(default_factory=GridSearchConfig)
    signal_default_weight: float = 1.0
    signal_weights: Dict[str, float] = field(default_factory=dict)
    history: SnapshotHistoryPolicy | None = None

    # ── Backward-compat shims ──
    # These properties let old code that accessed config.signals.*, config.boundary.*,
    # or config.evaluation.* still compile and run with degraded (default) values.

    @property
    def boundary(self) -> BoundaryAdapterConfig:
        """Legacy accessor. Prefer resolved config for actual pipeline runs."""
        return BoundaryAdapterConfig(
            interaction_tolerance_atr=self.defaults.interaction_tolerance_atr,
            atr_window=14,
        )

    @property
    def evaluation(self) -> EvaluationConfig:
        """Legacy accessor. Returns protocol config."""
        return self.protocol

    @property
    def signals(self) -> SignalConfig:
        """Legacy accessor. Returns default SignalConfig (not per-asset resolved)."""
        return SignalConfig()


# ── Pipeline config shim ──────────────────────────────────────────────────


@dataclass(frozen=True)
class TrendlinePipelineConfig:
    """Backward-compatible shim and workflow orchestrator interface."""

    extractor: str = "fractal"
    fitter: str = "pathfinding"
    extractor_params: Dict[str, Any] = field(default_factory=dict)
    fitter_params: Dict[str, Any] = field(default_factory=dict)
    boundary_params: Dict[str, Any] = field(default_factory=dict)
    signal_params: Dict[str, Any] = field(default_factory=dict)
    trendlines_config: TrendlinesConfig = field(default_factory=TrendlinesConfig)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "extractor": self.extractor,
            "fitter": self.fitter,
            "extractor_params": dict(self.extractor_params),
            "fitter_params": dict(self.fitter_params),
        }
        if self.boundary_params:
            payload["boundary_params"] = dict(self.boundary_params)
        if self.signal_params:
            payload["signal_params"] = dict(self.signal_params)
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "TrendlinePipelineConfig":
        raw = dict(payload or {})
        return cls(
            extractor=str(raw.get("extractor", "fractal")).strip() or "fractal",
            fitter=str(raw.get("fitter", "pathfinding")).strip() or "pathfinding",
            extractor_params=dict(raw.get("extractor_params", {})),
            fitter_params=dict(raw.get("fitter_params", {})),
            boundary_params=dict(raw.get("boundary_params", {})),
            signal_params=dict(raw.get("signal_params", {})),
        )

    @classmethod
    def from_trendlines_config(cls, cfg: TrendlinesConfig) -> "TrendlinePipelineConfig":
        return cls(
            extractor=cfg.extractor,
            fitter=cfg.fitter,
            trendlines_config=cfg,
        )


__all__ = [
    "AssetConfig",
    "AssetTimeframeConfig",
    "OptimizableDefaults",
    "OscillatorDefaults",
    "OscillatorOverride",
    "SnapshotHistoryOverride",
    "SnapshotHistoryPolicy",
    "TrendlinePipelineConfig",
    "TrendlinesConfig",
]
