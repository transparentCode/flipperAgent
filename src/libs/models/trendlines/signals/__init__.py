"""Trendlines-native signal contracts, extractors, and orchestration."""

from libs.models.trendlines.signals.base import AlphaSignal, BaseAlphaExtractor
from libs.models.trendlines.signals.fakeout import FakeoutAlphaExtractor
from libs.models.trendlines.signals.orchestrator import TrendlineSignalOrchestrator
from libs.models.trendlines.signals.patterns import PatternAlphaExtractor
from libs.models.trendlines.signals.structural import StructuralAlphaExtractor
from libs.models.trendlines.signals.temporal import TemporalAlphaExtractor

__all__ = [
    "AlphaSignal",
    "BaseAlphaExtractor",
    "FakeoutAlphaExtractor",
    "PatternAlphaExtractor",
    "StructuralAlphaExtractor",
    "TemporalAlphaExtractor",
    "TrendlineSignalOrchestrator",
]