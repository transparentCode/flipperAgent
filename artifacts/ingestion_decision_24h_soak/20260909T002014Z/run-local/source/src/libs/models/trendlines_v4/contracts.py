"""Versioned public geometry contracts projected from the shared engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .engine.types import (
    HISTORY_CAPACITY_BARS,
    PIVOT_WINDOW,
    SideAnalysis,
    TrendlineAnalysis,
    TrendlineBar,
    TrendlineGeometry,
    _utc,
)

GEOMETRY_SCHEMA_VERSION = "trendlines.geometry.v1"
GEOMETRY_SCHEMA_VERSION_V2 = "trendlines.geometry.v2"


@dataclass(frozen=True, slots=True)
class SideGeometry:
    """Structural and current-valid roles for one side."""

    structural: TrendlineGeometry | None
    current_valid: TrendlineGeometry | None
    same_geometry: bool

    def __post_init__(self) -> None:
        if self.structural is not None and not isinstance(
            self.structural, TrendlineGeometry
        ):
            raise TypeError("structural must be TrendlineGeometry or None")
        if self.current_valid is not None and not isinstance(
            self.current_valid, TrendlineGeometry
        ):
            raise TypeError("current_valid must be TrendlineGeometry or None")
        if not isinstance(self.same_geometry, bool):
            raise TypeError("same_geometry must be bool")
        expected = self.structural is not None and self.structural == self.current_valid
        if self.same_geometry != expected:
            raise ValueError("same_geometry disagrees with the two roles")


@dataclass(frozen=True, slots=True)
class TrendlineSnapshot:
    """One bounded analytical geometry snapshot at a closed-bar cutoff."""

    schema_version: Literal["trendlines.geometry.v1"]
    history_bar_count: int
    history_capacity_bars: int
    pivot_window: int
    history_start_at: datetime
    market_as_of: datetime
    support: SideGeometry
    resistance: SideGeometry

    def __post_init__(self) -> None:
        if self.schema_version != GEOMETRY_SCHEMA_VERSION:
            raise ValueError("unsupported geometry schema_version")
        if (
            isinstance(self.history_bar_count, bool)
            or not isinstance(self.history_bar_count, int)
            or self.history_bar_count < 1
        ):
            raise ValueError("history_bar_count must be positive")
        if self.history_capacity_bars != HISTORY_CAPACITY_BARS:
            raise ValueError("history_capacity_bars must be 300")
        if self.pivot_window != PIVOT_WINDOW:
            raise ValueError("pivot_window must be 3")
        start = _utc(self.history_start_at, "history_start_at")
        market = _utc(self.market_as_of, "market_as_of")
        if market < start:
            raise ValueError("market_as_of must not precede history_start_at")
        object.__setattr__(self, "history_start_at", start)
        object.__setattr__(self, "market_as_of", market)
        if not isinstance(self.support, SideGeometry) or not isinstance(
            self.resistance, SideGeometry
        ):
            raise TypeError("support and resistance must be SideGeometry")


@dataclass(frozen=True, slots=True)
class SideGeometryV2:
    """Three factual role slots for one side of a V2 snapshot."""

    structural: TrendlineGeometry | None
    current_valid: TrendlineGeometry | None
    secondary: TrendlineGeometry | None
    same_geometry: bool

    def __post_init__(self) -> None:
        roles = (self.structural, self.current_valid, self.secondary)
        if any(
            line is not None and not isinstance(line, TrendlineGeometry)
            for line in roles
        ):
            raise TypeError("side roles must be TrendlineGeometry or None")
        if not isinstance(self.same_geometry, bool):
            raise TypeError("same_geometry must be bool")
        expected = self.structural is not None and self.structural == self.current_valid
        if self.same_geometry != expected:
            raise ValueError("same_geometry disagrees with structural/current_valid")
        side = next((line.side for line in roles if line is not None), None)
        if side is not None and any(
            line is not None and line.side != side for line in roles
        ):
            raise ValueError("side roles must use one side")


@dataclass(frozen=True, slots=True)
class TrendlineSnapshotV2:
    """One bounded V2 analytical geometry snapshot at a closed-bar cutoff."""

    schema_version: Literal["trendlines.geometry.v2"]
    history_bar_count: int
    history_capacity_bars: int
    pivot_window: int
    history_start_at: datetime
    market_as_of: datetime
    support: SideGeometryV2
    resistance: SideGeometryV2

    def __post_init__(self) -> None:
        if self.schema_version != GEOMETRY_SCHEMA_VERSION_V2:
            raise ValueError("unsupported geometry schema_version")
        if (
            isinstance(self.history_bar_count, bool)
            or not isinstance(self.history_bar_count, int)
            or self.history_bar_count < 1
        ):
            raise ValueError("history_bar_count must be positive")
        if self.history_capacity_bars != HISTORY_CAPACITY_BARS:
            raise ValueError("history_capacity_bars must be 300")
        if self.pivot_window != PIVOT_WINDOW:
            raise ValueError("pivot_window must be 3")
        start = _utc(self.history_start_at, "history_start_at")
        market = _utc(self.market_as_of, "market_as_of")
        if market < start:
            raise ValueError("market_as_of must not precede history_start_at")
        object.__setattr__(self, "history_start_at", start)
        object.__setattr__(self, "market_as_of", market)
        if not isinstance(self.support, SideGeometryV2) or not isinstance(
            self.resistance, SideGeometryV2
        ):
            raise TypeError("support and resistance must be SideGeometryV2")


def _v1_side(side: SideAnalysis) -> SideGeometry:
    return SideGeometry(side.structural, side.current_valid, side.same_geometry)


def _v2_side(side: SideAnalysis) -> SideGeometryV2:
    return SideGeometryV2(
        side.structural, side.current_valid, side.secondary, side.same_geometry
    )


def to_v1_snapshot(analysis: TrendlineAnalysis) -> TrendlineSnapshot:
    return TrendlineSnapshot(
        schema_version=GEOMETRY_SCHEMA_VERSION,
        history_bar_count=analysis.history_bar_count,
        history_capacity_bars=HISTORY_CAPACITY_BARS,
        pivot_window=PIVOT_WINDOW,
        history_start_at=analysis.history_start_at,
        market_as_of=analysis.market_as_of,
        support=_v1_side(analysis.support),
        resistance=_v1_side(analysis.resistance),
    )


def to_v2_snapshot(analysis: TrendlineAnalysis) -> TrendlineSnapshotV2:
    return TrendlineSnapshotV2(
        schema_version=GEOMETRY_SCHEMA_VERSION_V2,
        history_bar_count=analysis.history_bar_count,
        history_capacity_bars=HISTORY_CAPACITY_BARS,
        pivot_window=PIVOT_WINDOW,
        history_start_at=analysis.history_start_at,
        market_as_of=analysis.market_as_of,
        support=_v2_side(analysis.support),
        resistance=_v2_side(analysis.resistance),
    )


__all__ = [
    "GEOMETRY_SCHEMA_VERSION",
    "GEOMETRY_SCHEMA_VERSION_V2",
    "SideGeometry",
    "SideGeometryV2",
    "TrendlineBar",
    "TrendlineGeometry",
    "TrendlineSnapshot",
    "TrendlineSnapshotV2",
    "to_v1_snapshot",
    "to_v2_snapshot",
]
