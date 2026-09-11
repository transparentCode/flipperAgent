"""Canonical contracts for the trendlines package."""

from libs.models.trendlines.contracts.contracts import PivotSet, Trendline, TrendlineFitResult
from libs.models.trendlines.contracts.identity import (
    PivotFinality,
    SourceIdentityKind,
    TrendlineCheckpoint,
    TrendlineExecutionMode,
    TrendlineIdentityProvider,
    TrendlineSnapshotFinality,
    TrendlineSnapshotIdentity,
    TrendlineSnapshotStage,
    TrendlineSourceRef,
    UnsupportedIdentityValueError,
)

__all__ = [
    "PivotFinality",
    "PivotSet",
    "SourceIdentityKind",
    "Trendline",
    "TrendlineCheckpoint",
    "TrendlineExecutionMode",
    "TrendlineFitResult",
    "TrendlineIdentityProvider",
    "TrendlineSnapshotFinality",
    "TrendlineSnapshotIdentity",
    "TrendlineSnapshotStage",
    "TrendlineSourceRef",
    "UnsupportedIdentityValueError",
]
