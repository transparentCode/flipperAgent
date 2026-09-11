"""
Regime Analysis Module
======================
4-layer market regime detection pipeline.

Layers:
  BCPD ChangeDetector  — structural breaks (Bayesian Online CPD)
  HMMClassifier        — TRENDING / NON_TRENDING / CRISIS (N-state GaussianHMM with BIC selection)
  VolOverlay           — LOW_VOL / HIGH_VOL (rolling vol percentile)
  HilbertCycle         — dominant period + confidence (Ehlers Homodyne Discriminator)

9-label taxonomy with direction:
  CLEAN_TREND_UP | CLEAN_TREND_DOWN | VOLATILE_TREND_UP | VOLATILE_TREND_DOWN
  QUIET_MR_UP | QUIET_MR_DOWN | CHOPPY_UP | CHOPPY_DOWN | CRISIS

Usage
-----
    from libs.regime import RegimeOrchestrator

    orch = RegimeOrchestrator.create("BTCUSDT", "1h")
    features = orch.analyze(df)
    # features.regime, features.p_trending, features.position_scale, ...
"""

from .aggregation.base import BaseAggregator
from .aggregation.rule_based import AggregatorConfig, FeatureAggregator
from .change_detector import ChangeDetector, ChangeDetectorConfig
from .hmm_classifier import HMMClassifier, HMMConfig
from .models import ChangePointSignal, HMMState, RegimeFeatures, VolState
from .orchestrator import RegimeOrchestrator
from .vol_overlay import VolConfig, VolOverlay

__all__ = [
    # Data contracts
    "ChangePointSignal",
    "HMMState",
    "VolState",
    "RegimeFeatures",
    # Components
    "ChangeDetector",
    "ChangeDetectorConfig",
    "HMMClassifier",
    "HMMConfig",
    "VolOverlay",
    "VolConfig",
    "FeatureAggregator",
    "AggregatorConfig",
    "BaseAggregator",
    # Top-level entry point
    "RegimeOrchestrator",
]
