"""Immutable source and replay contracts for SR-V1.6."""

from __future__ import annotations

from libs.models.sr.research.replay.candidates import CandidateReplay
from libs.models.sr.research.source.capsules import CapsuleStage, SourceCapsule
from libs.models.sr.research.source.contracts import SourceBar


SCHEMA_VERSION = "1.0"
ATR_IMPLEMENTATION = "libs.features.indicators.volatility.atr.ATR"
ATR_IMPLEMENTATION_CONTRACT = "true_range_sma_seed_then_wilder_recursion_v1"
__all__ = [
    "ATR_IMPLEMENTATION",
    "ATR_IMPLEMENTATION_CONTRACT",
    "CandidateReplay",
    "CapsuleStage",
    "SCHEMA_VERSION",
    "SourceBar",
    "SourceCapsule",
]
