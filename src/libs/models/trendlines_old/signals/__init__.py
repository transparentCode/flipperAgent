"""Trendlines-native signal contracts, extractors, and orchestration."""

from app.trendlines.signals.base import AlphaSignal, BaseAlphaExtractor
from app.trendlines.signals.fakeout import FakeoutAlphaExtractor
from app.trendlines.signals.orchestrator import TrendlineSignalOrchestrator
from app.trendlines.signals.patterns import PatternAlphaExtractor
from app.trendlines.signals.structural import StructuralAlphaExtractor
from app.trendlines.signals.temporal import TemporalAlphaExtractor

__all__ = [
    "AlphaSignal",
    "BaseAlphaExtractor",
    "FakeoutAlphaExtractor",
    "PatternAlphaExtractor",
    "StructuralAlphaExtractor",
    "TemporalAlphaExtractor",
    "TrendlineSignalOrchestrator",
]