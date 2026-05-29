"""V2-native re-exports for backward compatibility.

All consumers have migrated to ``app.regression.api`` directly.
This module remains as a convenience re-export layer — no v1 dependencies.

Preferred imports (use these directly)::

    from app.regression.api import compute_single_tf, compute_single_tf_series
    from app.regression.config.resolver import ConfigResolver
    from app.regression.contracts.context import RegimeSnapshot
"""
from __future__ import annotations

from .api import (
    compute_single_tf,
    compute_single_tf_series,
    compute_mtf,
)
from .config.resolver import ConfigResolver
from .config.schema import (
    PluginConfig,
    ResolvedPipelineConfig,
)
from .contracts.context import (
    CascadeContext,
    PipelineRequest,
    RegimeSnapshot,
)
from .contracts.result import MTFOutput, RegressionResult
from .pipeline import RegressionPipeline
from .state import NullStateManager, StateManager

# Try importing optimize_regression from V2-backed api facade
try:
    from .api import optimize_regression
except ImportError:
    pass


__all__ = [
    "compute_single_tf",
    "compute_single_tf_series",
    "compute_mtf",
    "optimize_regression",
    "ConfigResolver",
    "PluginConfig",
    "ResolvedPipelineConfig",
    "RegimeSnapshot",
    "CascadeContext",
    "PipelineRequest",
    "RegressionResult",
    "MTFOutput",
    "RegressionPipeline",
    "StateManager",
    "NullStateManager",
]



