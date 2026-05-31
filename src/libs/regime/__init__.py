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
    from app.regime import RegimeOrchestrator

    orch = RegimeOrchestrator.create("BTCUSDT", "1h")
    features = orch.analyze(df)
    # features.regime, features.p_trending, features.position_scale, ...
"""

from app.regime.models import ChangePointSignal, HMMState, RegimeFeatures, VolState
from app.regime.change_detector import ChangeDetector, ChangeDetectorConfig
from app.regime.hmm_classifier import HMMClassifier, HMMConfig
from app.regime.vol_overlay import VolOverlay, VolConfig
from app.regime.orchestrator import RegimeOrchestrator
from app.regime.aggregation.rule_based import FeatureAggregator, AggregatorConfig
from app.regime.aggregation.base import BaseAggregator

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
