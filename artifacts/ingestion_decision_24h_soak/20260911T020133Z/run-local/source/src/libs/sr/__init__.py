"""
S/R Module
==========
Kernel-ensemble Support/Resistance detection pipeline.

Primary API:
    - ``SRv2Pipeline``: Main pipeline orchestrator
    - ``LevelType``, ``CandidateLevel``, ``ScoredLevel``: Core models
    - ``ZoneLifecycleManager``: Zone state management
    - ``UniverseSRRouter``: Multi-asset/multi-timeframe routing
    - ``UniverseSROptimizer``: Hyperparameter optimization
"""

from app.sr.models import (
    LevelType,
    ZoneStatus,
    CandidateLevel,
    ScoredLevel,
    LevelFeatureVector,
    AssetMetadata,
    AssetCharacteristics,
    RuleDerivedParams,
    ZoneLifecycleEvent,
)
from app.sr.optimization import (
    CrossAssetBenchmark,
    CrossAssetBenchmarkResult,
    UniverseOptimizationConfig,
    UniverseOptimizationResult,
    UniverseSROptimizer,
    UniverseTrialResult,
)
from app.sr.pipeline import SRv2Pipeline
from app.sr.universe.router import UniverseSRRouter

__all__ = [
    # Enums
    "LevelType",
    "ZoneStatus",

    # Core models
    "CandidateLevel",
    "ScoredLevel",
    "LevelFeatureVector",
    "AssetMetadata",
    "AssetCharacteristics",
    "RuleDerivedParams",
    "ZoneLifecycleEvent",

    # Pipeline
    "SRv2Pipeline",

    # Universe
    "UniverseSRRouter",

    # Optimization
    "UniverseOptimizationConfig",
    "UniverseTrialResult",
    "UniverseOptimizationResult",
    "UniverseSROptimizer",
    "CrossAssetBenchmark",
    "CrossAssetBenchmarkResult",
]
