"""Typed configuration contracts for trendline runtime execution."""

from .asset_profile import AssetProfile
from .base_config import (
    AssetConfig,
    AssetTimeframeConfig,
    OptimizableDefaults,
    OscillatorDefaults,
    OscillatorOverride,
    TrendlinePipelineConfig,
    TrendlinesConfig,
)
from .boundary_config import BoundaryAdapterConfig
from .defaults import get_default_config_dict
from .derive import compute_all_derived, compute_oscillator_derived
from .oscillator_profile import OscillatorProfile
from .evaluation_config import (
    DriftMonitorConfig,
    EvaluationConfig,
    FitnessConfig,
    LookbackGridConfig,
    WalkForwardDefaults,
)
from .loader import load_trendlines_config
from .resolve import (
    ResolvedConfig,
    ResolvedOscillatorConfig,
    ResolvedSignalConfig,
    resolve_asset_config,
    resolve_oscillator_config,
)
from .search_grid_config import (
    FractalSearchGrid,
    GridSearchConfig,
    LeastSquaresSearchGrid,
    PathfindingSearchGrid,
    RansacSearchGrid,
    RDPSearchGrid,
)
from .signal_config import (
    FakeoutSignalConfig,
    PatternSignalConfig,
    QualityConfig,
    SignalConfig,
    StateTransitionEntry,
    StateTransitionsConfig,
    StructuralSignalConfig,
    TemporalSignalConfig,
)
from .state_transitions import build_state_transition_table

__all__ = [
    "AssetConfig",
    "AssetProfile",
    "AssetTimeframeConfig",
    "BoundaryAdapterConfig",
    "DriftMonitorConfig",
    "EvaluationConfig",
    "FakeoutSignalConfig",
    "FitnessConfig",
    "FractalSearchGrid",
    "GridSearchConfig",
    "LeastSquaresSearchGrid",
    "LookbackGridConfig",
    "OptimizableDefaults",
    "OscillatorDefaults",
    "OscillatorOverride",
    "OscillatorProfile",
    "PathfindingSearchGrid",
    "PatternSignalConfig",
    "QualityConfig",
    "RDPSearchGrid",
    "RansacSearchGrid",
    "ResolvedConfig",
    "ResolvedOscillatorConfig",
    "ResolvedSignalConfig",
    "SignalConfig",
    "StateTransitionEntry",
    "StateTransitionsConfig",
    "StructuralSignalConfig",
    "TemporalSignalConfig",
    "TrendlinePipelineConfig",
    "TrendlinesConfig",
    "WalkForwardDefaults",
    "build_state_transition_table",
    "compute_all_derived",
    "compute_oscillator_derived",
    "get_default_config_dict",
    "load_trendlines_config",
    "resolve_asset_config",
    "resolve_oscillator_config",
]
