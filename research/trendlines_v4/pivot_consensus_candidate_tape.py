"""Research-only pivot-consensus candidate tape for Trendlines V4.

This module deliberately describes a candidate universe.  It does not select,
rank, score, or promote a line.  Pivot confirmation and the 300-bar preparation
boundary are delegated to the canonical V4 engine so this family cannot grow a
second pivot implementation by accident.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Literal

from libs.models.trendlines_v4.engine import analyzer, pivots
from libs.models.trendlines_v4.engine.types import (
    HISTORY_CAPACITY_BARS,
    PIVOT_WINDOW,
    Side,
    TrendlineBar,
)

AnchorSource = Literal["wick", "close"]
AnchorMode = Literal[
    "wick->wick",
    "wick->close",
    "close->wick",
    "close->close",
]

SIDES: tuple[Side, ...] = ("support", "resistance")
ANCHOR_SOURCES: tuple[AnchorSource, ...] = ("wick", "close")
ANCHOR_MODES: tuple[AnchorMode, ...] = (
    "wick->wick",
    "wick->close",
    "close->wick",
    "close->close",
)
SCHEMA_VERSION = "trendlines_v4_f1a_pivot_consensus_candidate_tape_v1"
FAMILY_NAME = "pivot_consensus"
G6_MANIFEST_PATH = Path(__file__).parents[2] / (
    "artifacts/trendlines_v4/g6_frozen_utility_benchmark_v1/manifest.json"
)
F1A_ARTIFACT_PATH = Path(__file__).parents[2] / (
    "artifacts/trendlines_v4/f1a_pivot_consensus_candidate_tape_v1"
)
G6_MANIFEST_SHA256 = "318f3e5b533ce45227452a12a3a84f9ae5bf03a90261371ed97c6ae0ef0bcd6b"


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _g6_digest(value: object) -> str:
    """Match the existing G6 manifest identity serialization exactly."""

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _timestamp(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _float_text(value: float) -> str:
    return repr(float(value))


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a real number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _interaction_bar_count(evaluated_bar_count: int, start_index: int) -> int:
    if isinstance(evaluated_bar_count, bool) or not isinstance(
        evaluated_bar_count, int
    ):
        raise TypeError("evaluated_bar_count must be an integer")
    if isinstance(start_index, bool) or not isinstance(start_index, int):
        raise TypeError("start_index must be an integer")
    count = evaluated_bar_count - start_index
    if evaluated_bar_count <= 0 or start_index < 0 or count <= 0:
        raise ValueError("interaction interval must be a non-empty history suffix")
    return count


def _line_price_at(
    index: int,
    start_pivot: ConfirmedPivot,
    end_pivot: ConfirmedPivot,
    start_price: float,
    end_price: float,
    slope: float,
    intercept: float,
) -> float:
    """Evaluate a candidate line with exact defining-anchor semantics."""

    if index == start_pivot.index:
        return start_price
    if index == end_pivot.index:
        return end_price
    return _finite(slope * index + intercept, "line price")


def _basis_points(observed: float, line: float) -> float:
    """Return absolute residual in bps, preserving exact float arithmetic."""

    if line == 0.0:
        raise ValueError("line price cannot be zero for a bps residual")
    return abs(observed - line) / abs(line) * 10_000.0


@dataclass(frozen=True, slots=True)
class ConfirmedPivot:
    """One canonical V4 same-side pivot and its two allowed observations."""

    index: int
    at: datetime
    wick_price: float
    close_price: float

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int):
            raise TypeError("pivot index must be an integer")
        if self.index < 0:
            raise ValueError("pivot index must be non-negative")
        if not isinstance(self.at, datetime) or self.at.tzinfo is None:
            raise TypeError("pivot timestamp must be timezone-aware")
        if self.at.utcoffset() is None or self.at.utcoffset().total_seconds() != 0:
            raise ValueError("pivot timestamp must be UTC")
        object.__setattr__(self, "at", self.at.astimezone(UTC))
        for name in ("wick_price", "close_price"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")

    def price(self, source: AnchorSource) -> float:
        if source == "wick":
            return self.wick_price
        if source == "close":
            return self.close_price
        raise ValueError(f"unknown anchor source: {source}")

    def as_payload(self) -> dict[str, object]:
        return {
            "index": self.index,
            "at": _timestamp(self.at),
            "wick_price": self.wick_price,
            "close_price": self.close_price,
        }


@dataclass(frozen=True, slots=True)
class PivotResidualObservation:
    """Continuous evidence for one confirmed pivot against one candidate line."""

    pivot_index: int
    pivot_at: datetime
    line_price: float
    wick_price: float
    close_price: float
    wick_residual_bps: float
    close_residual_bps: float
    nearest_residual_bps: float
    nearest_source: Literal["wick", "close", "both"]

    def as_payload(self) -> dict[str, object]:
        return {
            "pivot_index": self.pivot_index,
            "pivot_at": _timestamp(self.pivot_at),
            "line_price": self.line_price,
            "wick_price": self.wick_price,
            "close_price": self.close_price,
            "wick_residual_bps": self.wick_residual_bps,
            "close_residual_bps": self.close_residual_bps,
            "nearest_residual_bps": self.nearest_residual_bps,
            "nearest_source": self.nearest_source,
        }


@dataclass(frozen=True, slots=True)
class PivotConsensusCandidate:
    """One provenance-preserving ordered pivot-pair line."""

    side: Side
    start_pivot: ConfirmedPivot
    end_pivot: ConfirmedPivot
    start_source: AnchorSource
    end_source: AnchorSource
    start_price: float
    end_price: float
    slope_per_bar: float
    intercept: float
    projected_price_at_market_as_of: float
    pivot_evidence: tuple[PivotResidualObservation, ...]
    body_intersection_count: int
    full_range_intersection_count: int
    anchor_body_intersection_count: int
    anchor_full_range_intersection_count: int
    non_anchor_body_intersection_count: int
    non_anchor_full_range_intersection_count: int
    evaluated_bar_count: int
    observable_from_at: datetime
    candidate_id: str
    geometry_id: str

    def __post_init__(self) -> None:
        if self.anchor_full_range_intersection_count != 2:
            raise ValueError("both defining anchors must contact the full candle range")
        if self.body_intersection_count != (
            self.anchor_body_intersection_count
            + self.non_anchor_body_intersection_count
        ):
            raise ValueError("body contact decomposition mismatch")
        if self.full_range_intersection_count != (
            self.anchor_full_range_intersection_count
            + self.non_anchor_full_range_intersection_count
        ):
            raise ValueError("full-range contact decomposition mismatch")
        if not (
            0
            <= self.body_intersection_count
            <= self.full_range_intersection_count
            <= self.interaction_bar_count
        ):
            raise ValueError("candidate interaction counts are out of bounds")
        if not isinstance(self.observable_from_at, datetime) or (
            self.observable_from_at.tzinfo is None
        ):
            raise TypeError("observable_from_at must be timezone-aware")
        if (
            self.observable_from_at.utcoffset() is None
            or self.observable_from_at.utcoffset().total_seconds() != 0
        ):
            raise ValueError("observable_from_at must be UTC")
        object.__setattr__(
            self, "observable_from_at", self.observable_from_at.astimezone(UTC)
        )

    @property
    def anchor_mode(self) -> AnchorMode:
        return f"{self.start_source}->{self.end_source}"  # type: ignore[return-value]

    @property
    def anchor_span_bars(self) -> int:
        return self.end_pivot.index - self.start_pivot.index

    @property
    def age_bars(self) -> int:
        return self.evaluated_bar_count - 1 - self.end_pivot.index

    @property
    def interaction_bar_count(self) -> int:
        """Number of candles actually inspected for interaction evidence."""

        return _interaction_bar_count(self.evaluated_bar_count, self.start_pivot.index)

    @property
    def observable_from_index(self) -> int:
        return self.end_pivot.index + PIVOT_WINDOW

    @property
    def wick_intersection_count(self) -> int:
        """Deprecated internal alias for full-range candle contacts."""

        return self.full_range_intersection_count

    @property
    def projection_positive(self) -> bool:
        return self.projected_price_at_market_as_of > 0

    @property
    def non_anchor_evidence(self) -> tuple[PivotResidualObservation, ...]:
        return tuple(
            item
            for item in self.pivot_evidence
            if item.pivot_index not in (self.start_pivot.index, self.end_pivot.index)
        )

    @property
    def best_non_anchor_nearest_residual_bps(self) -> float | None:
        values = [item.nearest_residual_bps for item in self.non_anchor_evidence]
        return min(values) if values else None

    @property
    def median_non_anchor_nearest_residual_bps(self) -> float | None:
        values = [item.nearest_residual_bps for item in self.non_anchor_evidence]
        return float(median(values)) if values else None

    def line_price_at(self, index: int) -> float:
        return _line_price_at(
            index,
            self.start_pivot,
            self.end_pivot,
            self.start_price,
            self.end_price,
            self.slope_per_bar,
            self.intercept,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "family": FAMILY_NAME,
            "side": self.side,
            "start_anchor_at": _timestamp(self.start_pivot.at),
            "start_source": self.start_source,
            "start_price": _float_text(self.start_price),
            "end_anchor_at": _timestamp(self.end_pivot.at),
            "end_source": self.end_source,
            "end_price": _float_text(self.end_price),
        }

    def as_payload(self, *, include_evidence: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "candidate_id": self.candidate_id,
            "geometry_id": self.geometry_id,
            "side": self.side,
            "anchor_mode": self.anchor_mode,
            "start_pivot": self.start_pivot.as_payload(),
            "end_pivot": self.end_pivot.as_payload(),
            "start_source": self.start_source,
            "end_source": self.end_source,
            "start_price": self.start_price,
            "end_price": self.end_price,
            "slope_per_bar": self.slope_per_bar,
            "intercept": self.intercept,
            "projected_price_at_market_as_of": self.projected_price_at_market_as_of,
            "projection_positive": self.projection_positive,
            "anchor_span_bars": self.anchor_span_bars,
            "age_bars": self.age_bars,
            "evaluated_bar_count": self.evaluated_bar_count,
            "interaction_bar_count": self.interaction_bar_count,
            "observable_from_index": self.observable_from_index,
            "observable_from_at": _timestamp(self.observable_from_at),
            "evaluated_pivot_count": len(self.pivot_evidence),
            "non_anchor_pivot_count": len(self.non_anchor_evidence),
            "best_non_anchor_nearest_residual_bps": self.best_non_anchor_nearest_residual_bps,
            "median_non_anchor_nearest_residual_bps": self.median_non_anchor_nearest_residual_bps,
            "body_intersection_count": self.body_intersection_count,
            "full_range_intersection_count": self.full_range_intersection_count,
            "anchor_body_intersection_count": self.anchor_body_intersection_count,
            "anchor_full_range_intersection_count": self.anchor_full_range_intersection_count,
            "non_anchor_body_intersection_count": self.non_anchor_body_intersection_count,
            "non_anchor_full_range_intersection_count": self.non_anchor_full_range_intersection_count,
        }
        if include_evidence:
            payload["pivot_evidence"] = [
                item.as_payload() for item in self.pivot_evidence
            ]
        return payload


@dataclass(frozen=True, slots=True)
class PivotConsensusTape:
    """All F1A candidates for one causally closed, prepared V4 history."""

    bars: tuple[TrendlineBar, ...]
    market_as_of: datetime
    support_pivots: tuple[ConfirmedPivot, ...]
    resistance_pivots: tuple[ConfirmedPivot, ...]
    candidates: tuple[PivotConsensusCandidate, ...]
    tape_id: str

    @property
    def history_bar_count(self) -> int:
        return len(self.bars)

    def candidates_for_side(self, side: Side) -> tuple[PivotConsensusCandidate, ...]:
        if side not in SIDES:
            raise ValueError(f"unknown side: {side}")
        return tuple(
            candidate for candidate in self.candidates if candidate.side == side
        )

    def pivots_for_side(self, side: Side) -> tuple[ConfirmedPivot, ...]:
        if side == "support":
            return self.support_pivots
        if side == "resistance":
            return self.resistance_pivots
        raise ValueError(f"unknown side: {side}")

    def geometry_duplicate_count(self) -> int:
        return len(self.candidates) - len(
            {item.geometry_id for item in self.candidates}
        )

    def as_payload(self, *, include_evidence: bool = True) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "family": FAMILY_NAME,
            "pivot_window": PIVOT_WINDOW,
            "history_capacity_bars": HISTORY_CAPACITY_BARS,
            "tape_id": self.tape_id,
            "history_bar_count": self.history_bar_count,
            "market_as_of": _timestamp(self.market_as_of),
            "support_pivots": [item.as_payload() for item in self.support_pivots],
            "resistance_pivots": [item.as_payload() for item in self.resistance_pivots],
            "candidate_count": len(self.candidates),
            "geometry_duplicate_count": self.geometry_duplicate_count(),
            "candidates": [
                item.as_payload(include_evidence=include_evidence)
                for item in self.candidates
            ],
        }


def _validated_history(history: Sequence[TrendlineBar]) -> tuple[TrendlineBar, ...]:
    return analyzer._prepare(history)


def _confirmed_pivots(
    bars: Sequence[TrendlineBar], side: Side
) -> tuple[ConfirmedPivot, ...]:
    return tuple(
        ConfirmedPivot(
            index=index,
            at=bars[index].closed_at,
            wick_price=price,
            close_price=bars[index].close,
        )
        for index, price in pivots._pivots(bars, side)
    )


def _nearest_source(wick: float, close: float) -> Literal["wick", "close", "both"]:
    if wick == close:
        return "both"
    return "wick" if wick < close else "close"


def _iter_pivot_evidence(
    bars: Sequence[TrendlineBar],
    same_side_pivots: Sequence[ConfirmedPivot],
    start_pivot: ConfirmedPivot,
    end_pivot: ConfirmedPivot,
    start_price: float,
    end_price: float,
    slope: float,
    intercept: float,
) -> Iterator[PivotResidualObservation]:
    for pivot in same_side_pivots:
        if pivot.index < start_pivot.index:
            continue
        line = _line_price_at(
            pivot.index,
            start_pivot,
            end_pivot,
            start_price,
            end_price,
            slope,
            intercept,
        )
        wick_residual = _basis_points(pivot.wick_price, line)
        close_residual = _basis_points(pivot.close_price, line)
        yield PivotResidualObservation(
            pivot_index=pivot.index,
            pivot_at=pivot.at,
            line_price=line,
            wick_price=pivot.wick_price,
            close_price=pivot.close_price,
            wick_residual_bps=wick_residual,
            close_residual_bps=close_residual,
            nearest_residual_bps=min(wick_residual, close_residual),
            nearest_source=_nearest_source(wick_residual, close_residual),
        )


def _pivot_evidence(
    bars: Sequence[TrendlineBar],
    same_side_pivots: Sequence[ConfirmedPivot],
    start_pivot: ConfirmedPivot,
    end_pivot: ConfirmedPivot,
    start_price: float,
    end_price: float,
    slope: float,
    intercept: float,
) -> tuple[PivotResidualObservation, ...]:
    return tuple(
        _iter_pivot_evidence(
            bars,
            same_side_pivots,
            start_pivot,
            end_pivot,
            start_price,
            end_price,
            slope,
            intercept,
        )
    )


def _pivot_evidence_summary(
    bars: Sequence[TrendlineBar],
    same_side_pivots: Sequence[ConfirmedPivot],
    start_pivot: ConfirmedPivot,
    end_pivot: ConfirmedPivot,
    start_price: float,
    end_price: float,
    slope: float,
    intercept: float,
) -> tuple[float | None, float | None, int, Counter[str]]:
    nearest_values: list[float] = []
    nearest_source_counts: Counter[str] = Counter()
    for observation in _iter_pivot_evidence(
        bars,
        same_side_pivots,
        start_pivot,
        end_pivot,
        start_price,
        end_price,
        slope,
        intercept,
    ):
        if observation.pivot_index in (start_pivot.index, end_pivot.index):
            continue
        nearest_values.append(observation.nearest_residual_bps)
        nearest_source_counts[observation.nearest_source] += 1
    if not nearest_values:
        return None, None, 0, nearest_source_counts
    return (
        min(nearest_values),
        float(median(nearest_values)),
        len(nearest_values),
        nearest_source_counts,
    )


def _interaction_counts(
    bars: Sequence[TrendlineBar],
    start_pivot: ConfirmedPivot,
    end_pivot: ConfirmedPivot,
    start_price: float,
    end_price: float,
    slope: float,
    intercept: float,
) -> tuple[int, int, int, int, int, int]:
    body_count = 0
    full_range_count = 0
    anchor_body_count = 0
    anchor_full_range_count = 0
    non_anchor_body_count = 0
    non_anchor_full_range_count = 0
    for index in range(start_pivot.index, len(bars)):
        line = _line_price_at(
            index,
            start_pivot,
            end_pivot,
            start_price,
            end_price,
            slope,
            intercept,
        )
        bar = bars[index]
        body_contact = min(bar.open, bar.close) <= line <= max(bar.open, bar.close)
        full_range_contact = bar.low <= line <= bar.high
        if body_contact:
            body_count += 1
        if full_range_contact:
            full_range_count += 1
        if index in (start_pivot.index, end_pivot.index):
            if body_contact:
                anchor_body_count += 1
            if full_range_contact:
                anchor_full_range_count += 1
        else:
            if body_contact:
                non_anchor_body_count += 1
            if full_range_contact:
                non_anchor_full_range_count += 1
    return (
        body_count,
        full_range_count,
        anchor_body_count,
        anchor_full_range_count,
        non_anchor_body_count,
        non_anchor_full_range_count,
    )


def _build_candidate(
    bars: Sequence[TrendlineBar],
    side: Side,
    start: ConfirmedPivot,
    end: ConfirmedPivot,
    start_source: AnchorSource,
    end_source: AnchorSource,
    same_side_pivots: Sequence[ConfirmedPivot],
    *,
    include_evidence: bool = True,
) -> PivotConsensusCandidate:
    if start.index >= end.index:
        raise ValueError("candidate anchors must be strictly ordered")
    start_price = start.price(start_source)
    end_price = end.price(end_source)
    slope = (end_price - start_price) / (end.index - start.index)
    intercept = start_price - slope * start.index
    projected = slope * (len(bars) - 1) + intercept
    if not all(math.isfinite(value) for value in (slope, intercept, projected)):
        raise ValueError("candidate line state must be finite")
    observable_from_index = end.index + PIVOT_WINDOW
    if observable_from_index >= len(bars):
        raise ValueError("candidate second pivot lacks confirmation bars")
    evidence = (
        _pivot_evidence(
            bars,
            same_side_pivots,
            start,
            end,
            start_price,
            end_price,
            slope,
            intercept,
        )
        if include_evidence
        else ()
    )
    (
        body_count,
        full_range_count,
        anchor_body_count,
        anchor_full_range_count,
        non_anchor_body_count,
        non_anchor_full_range_count,
    ) = _interaction_counts(
        bars,
        start,
        end,
        start_price,
        end_price,
        slope,
        intercept,
    )
    identity_payload = {
        "family": FAMILY_NAME,
        "side": side,
        "start_anchor_at": _timestamp(start.at),
        "start_source": start_source,
        "start_price": _float_text(start_price),
        "end_anchor_at": _timestamp(end.at),
        "end_source": end_source,
        "end_price": _float_text(end_price),
    }
    geometry_payload = {
        "family": FAMILY_NAME,
        "side": side,
        "start_index": start.index,
        "end_index": end.index,
        "start_price": _float_text(start_price),
        "end_price": _float_text(end_price),
        "slope_per_bar": _float_text(slope),
        "intercept": _float_text(intercept),
    }
    return PivotConsensusCandidate(
        side=side,
        start_pivot=start,
        end_pivot=end,
        start_source=start_source,
        end_source=end_source,
        start_price=start_price,
        end_price=end_price,
        slope_per_bar=slope,
        intercept=intercept,
        projected_price_at_market_as_of=projected,
        pivot_evidence=evidence,
        body_intersection_count=body_count,
        full_range_intersection_count=full_range_count,
        anchor_body_intersection_count=anchor_body_count,
        anchor_full_range_intersection_count=anchor_full_range_count,
        non_anchor_body_intersection_count=non_anchor_body_count,
        non_anchor_full_range_intersection_count=non_anchor_full_range_count,
        evaluated_bar_count=len(bars),
        observable_from_at=bars[observable_from_index].closed_at,
        candidate_id=_digest(identity_payload),
        geometry_id=_digest(geometry_payload),
    )


def _iter_candidate_objects(
    bars: Sequence[TrendlineBar],
    by_side: dict[Side, tuple[ConfirmedPivot, ...]],
    *,
    include_evidence: bool = True,
) -> Iterator[PivotConsensusCandidate]:
    for side in SIDES:
        same_side_pivots = by_side[side]
        for start_position, start in enumerate(same_side_pivots):
            for end in same_side_pivots[start_position + 1 :]:
                for start_source in ANCHOR_SOURCES:
                    for end_source in ANCHOR_SOURCES:
                        yield _build_candidate(
                            bars,
                            side,
                            start,
                            end,
                            start_source,
                            end_source,
                            same_side_pivots,
                            include_evidence=include_evidence,
                        )


def _candidate_identity(candidate: PivotConsensusCandidate) -> dict[str, str]:
    return {
        "candidate_id": candidate.candidate_id,
        "geometry_id": candidate.geometry_id,
    }


def _tape_id(
    bars: Sequence[TrendlineBar],
    by_side: dict[Side, tuple[ConfirmedPivot, ...]],
    candidate_identity: Sequence[dict[str, str]],
) -> str:
    return _digest(
        {
            "schema_version": SCHEMA_VERSION,
            "family": FAMILY_NAME,
            "market_as_of": _timestamp(bars[-1].closed_at),
            "history_bar_count": len(bars),
            "support_pivots": [item.as_payload() for item in by_side["support"]],
            "resistance_pivots": [item.as_payload() for item in by_side["resistance"]],
            "candidates": list(candidate_identity),
        }
    )


def build_candidate_tape(
    history: Sequence[TrendlineBar],
) -> PivotConsensusTape:
    """Build every F1A candidate from the canonical prepared V4 history."""

    bars = _validated_history(history)
    by_side: dict[Side, tuple[ConfirmedPivot, ...]] = {
        side: _confirmed_pivots(bars, side) for side in SIDES
    }
    candidates = tuple(_iter_candidate_objects(bars, by_side))
    candidate_identity = [_candidate_identity(item) for item in candidates]
    return PivotConsensusTape(
        bars=bars,
        market_as_of=bars[-1].closed_at,
        support_pivots=by_side["support"],
        resistance_pivots=by_side["resistance"],
        candidates=candidates,
        tape_id=_tape_id(bars, by_side, candidate_identity),
    )


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("source timestamp must be UTC")
    return parsed.astimezone(UTC)


def _source_bar_to_trendline_bar(source_bar: object) -> TrendlineBar:
    return TrendlineBar(
        closed_at=_parse_utc(str(source_bar.close_time)),
        open=_finite(source_bar.open, "open"),
        high=_finite(source_bar.high, "high"),
        low=_finite(source_bar.low, "low"),
        close=_finite(source_bar.close, "close"),
    )


def authenticate_g6_sources() -> dict[str, object]:
    """Authenticate the already-frozen local G6 manifest and all 15 windows."""

    if not G6_MANIFEST_PATH.is_file():
        raise ValueError(f"missing frozen G6 manifest: {G6_MANIFEST_PATH}")
    if hashlib.sha256(G6_MANIFEST_PATH.read_bytes()).hexdigest() != G6_MANIFEST_SHA256:
        raise ValueError("frozen G6 manifest hash mismatch")
    manifest = json.loads(G6_MANIFEST_PATH.read_text())
    body = {key: value for key, value in manifest.items() if key != "manifest_id"}
    if manifest.get("manifest_id") != _g6_digest(body):
        raise ValueError("frozen G6 manifest identity mismatch")
    if manifest.get("window_count") != 15 or manifest.get("row_count") != 4500:
        raise ValueError("frozen G6 manifest inventory mismatch")
    expected_assets = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "HYPEUSDT")
    if tuple(source.get("asset") for source in manifest["sources"]) != expected_assets:
        raise ValueError("frozen G6 asset order mismatch")
    for source in manifest["sources"]:
        path = Path(source["path"])
        if not path.is_file():
            raise ValueError(f"missing frozen G6 source: {path}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError(f"frozen G6 source hash mismatch: {source['asset']}")
        raw_rows = tuple(path.read_bytes().splitlines())[1:]
        if len(raw_rows) != source["data_row_count"]:
            raise ValueError(f"frozen G6 row count mismatch: {source['asset']}")
        for window in source["windows"]:
            start = window["start_index"]
            end = window["end_index_exclusive"]
            if (
                hashlib.sha256(b"\n".join(raw_rows[start:end])).hexdigest()
                != window["ohlc_input_sha256"]
            ):
                raise ValueError(
                    f"frozen G6 window hash mismatch: {source['asset']}:{window['window']}"
                )
    if sum(len(source["windows"]) for source in manifest["sources"]) != 15:
        raise ValueError("frozen G6 window inventory is not 15 windows")
    return manifest


def _distribution(values: Iterable[float | int]) -> dict[str, object]:
    numeric = [float(value) for value in values]
    if not numeric:
        return {
            "count": 0,
            "minimum": None,
            "median": None,
            "mean": None,
            "maximum": None,
        }
    return {
        "count": len(numeric),
        "minimum": min(numeric),
        "median": float(median(numeric)),
        "mean": math.fsum(numeric) / len(numeric),
        "maximum": max(numeric),
    }


def candidate_cardinality_preflight(
    support_pivot_count: int, resistance_pivot_count: int
) -> dict[str, int]:
    """Calculate exact F1A candidate and evidence cardinalities."""

    counts = {
        "support_pivot_count": support_pivot_count,
        "resistance_pivot_count": resistance_pivot_count,
    }
    for name, count in counts.items():
        if isinstance(count, bool) or not isinstance(count, int):
            raise TypeError(f"{name} must be a non-negative integer")
        if count < 0:
            raise ValueError(f"{name} must be a non-negative integer")

    def _candidate_count(pivot_count: int) -> int:
        return 2 * pivot_count * (pivot_count - 1)

    def _evidence_count(pivot_count: int) -> int:
        return 4 * pivot_count * (pivot_count + 1) * (pivot_count - 1) // 3

    result = {
        **counts,
        "support_candidate_count": _candidate_count(support_pivot_count),
        "resistance_candidate_count": _candidate_count(resistance_pivot_count),
        "support_potential_pivot_evidence_rows": _evidence_count(support_pivot_count),
        "resistance_potential_pivot_evidence_rows": _evidence_count(
            resistance_pivot_count
        ),
    }
    result["total_candidate_count"] = (
        result["support_candidate_count"] + result["resistance_candidate_count"]
    )
    result["total_potential_pivot_evidence_rows"] = (
        result["support_potential_pivot_evidence_rows"]
        + result["resistance_potential_pivot_evidence_rows"]
    )
    return result


class _AuditAccumulator:
    """Retain scalar descriptive values, never candidate/evidence objects."""

    __slots__ = (
        "anchor_body_counts",
        "anchor_full_range_counts",
        "anchor_spans",
        "best_residuals",
        "body_counts",
        "body_rates",
        "candidate_count",
        "full_range_counts",
        "full_range_rates",
        "geometry_ids",
        "median_residuals",
        "mode_counts",
        "nearest_source_counts",
        "non_anchor_body_counts",
        "non_anchor_counts",
        "non_anchor_full_range_counts",
    )

    def __init__(self) -> None:
        self.candidate_count = 0
        self.mode_counts: Counter[str] = Counter()
        self.geometry_ids: set[str] = set()
        self.anchor_spans: list[int] = []
        self.body_counts: list[int] = []
        self.body_rates: list[float] = []
        self.full_range_counts: list[int] = []
        self.full_range_rates: list[float] = []
        self.anchor_body_counts: list[int] = []
        self.anchor_full_range_counts: list[int] = []
        self.non_anchor_body_counts: list[int] = []
        self.non_anchor_full_range_counts: list[int] = []
        self.best_residuals: list[float] = []
        self.median_residuals: list[float] = []
        self.non_anchor_counts: list[int] = []
        self.nearest_source_counts: Counter[str] = Counter()

    def add(
        self,
        candidate: PivotConsensusCandidate,
        *,
        evidence_summary: tuple[float | None, float | None, int, Counter[str]]
        | None = None,
    ) -> None:
        self.candidate_count += 1
        self.mode_counts[candidate.anchor_mode] += 1
        self.geometry_ids.add(candidate.geometry_id)
        self.anchor_spans.append(candidate.anchor_span_bars)
        self.body_counts.append(candidate.body_intersection_count)
        self.body_rates.append(
            candidate.body_intersection_count / candidate.interaction_bar_count
        )
        self.full_range_counts.append(candidate.full_range_intersection_count)
        self.full_range_rates.append(
            candidate.full_range_intersection_count / candidate.interaction_bar_count
        )
        self.anchor_body_counts.append(candidate.anchor_body_intersection_count)
        self.anchor_full_range_counts.append(
            candidate.anchor_full_range_intersection_count
        )
        self.non_anchor_body_counts.append(candidate.non_anchor_body_intersection_count)
        self.non_anchor_full_range_counts.append(
            candidate.non_anchor_full_range_intersection_count
        )
        if evidence_summary is None:
            best_residual = candidate.best_non_anchor_nearest_residual_bps
            median_residual = candidate.median_non_anchor_nearest_residual_bps
            non_anchor_count = len(candidate.non_anchor_evidence)
            nearest_source_counts = Counter(
                observation.nearest_source
                for observation in candidate.non_anchor_evidence
            )
        else:
            (
                best_residual,
                median_residual,
                non_anchor_count,
                nearest_source_counts,
            ) = evidence_summary
        if best_residual is not None:
            self.best_residuals.append(best_residual)
        if median_residual is not None:
            self.median_residuals.append(median_residual)
        self.non_anchor_counts.append(non_anchor_count)
        self.nearest_source_counts.update(nearest_source_counts)

    def as_report(self) -> dict[str, object]:
        count = self.candidate_count
        return {
            "candidate_count": count,
            "candidate_count_by_anchor_mode": {
                mode: self.mode_counts.get(mode, 0) for mode in ANCHOR_MODES
            },
            "exact_geometry_duplicate_count": count - len(self.geometry_ids),
            "anchor_span_bars": _distribution(self.anchor_spans),
            "body_intersection_count": _distribution(self.body_counts),
            "body_intersection_rate": _distribution(self.body_rates),
            "full_range_intersection_count": _distribution(self.full_range_counts),
            "full_range_intersection_rate": _distribution(self.full_range_rates),
            "anchor_body_intersection_count": _distribution(self.anchor_body_counts),
            "anchor_full_range_intersection_count": _distribution(
                self.anchor_full_range_counts
            ),
            "non_anchor_body_intersection_count": _distribution(
                self.non_anchor_body_counts
            ),
            "non_anchor_full_range_intersection_count": _distribution(
                self.non_anchor_full_range_counts
            ),
            "best_non_anchor_nearest_residual_bps": _distribution(self.best_residuals),
            "median_non_anchor_nearest_residual_bps": _distribution(
                self.median_residuals
            ),
            "non_anchor_pivot_evidence": {
                "zero": self.non_anchor_counts.count(0) / count if count else None,
                "one": self.non_anchor_counts.count(1) / count if count else None,
                "multiple": (
                    sum(value > 1 for value in self.non_anchor_counts) / count
                    if count
                    else None
                ),
            },
            "nearest_source_counts": {
                source: self.nearest_source_counts.get(source, 0)
                for source in ("wick", "close", "both")
            },
        }


def _audit_rows(candidates: Sequence[PivotConsensusCandidate]) -> dict[str, object]:
    accumulator = _AuditAccumulator()
    for candidate in candidates:
        accumulator.add(candidate)
    return accumulator.as_report()


def _window_bars_from_manifest(
    source: dict[str, object], window: dict[str, object]
) -> tuple[TrendlineBar, ...]:
    path = Path(source["path"])
    with path.open(newline="", encoding="utf-8") as handle:
        rows = tuple(csv.DictReader(handle))
    start = int(window["start_index"])
    end = int(window["end_index_exclusive"])
    return tuple(
        TrendlineBar(
            closed_at=_parse_utc(row["close_time"]),
            open=_finite(float(row["open"]), "open"),
            high=_finite(float(row["high"]), "high"),
            low=_finite(float(row["low"]), "low"),
            close=_finite(float(row["close"]), "close"),
        )
        for row in rows[start:end]
    )


def audit_frozen_g6_sources() -> tuple[dict[str, object], dict[str, object]]:
    """Run the descriptive F1A audit with one candidate resident at a time."""

    manifest = authenticate_g6_sources()
    window_reports: list[dict[str, object]] = []
    global_accumulator = _AuditAccumulator()
    mode_accumulators = {mode: _AuditAccumulator() for mode in ANCHOR_MODES}
    asset_side_accumulators: dict[tuple[str, Side], _AuditAccumulator] = {}
    asset_side_mode_accumulators: dict[
        tuple[str, Side, AnchorMode], _AuditAccumulator
    ] = {}

    for source in manifest["sources"]:
        for window in source["windows"]:
            bars = _window_bars_from_manifest(source, window)
            by_side: dict[Side, tuple[ConfirmedPivot, ...]] = {
                side: _confirmed_pivots(bars, side) for side in SIDES
            }
            cardinality = candidate_cardinality_preflight(
                len(by_side["support"]), len(by_side["resistance"])
            )
            side_accumulators = {side: _AuditAccumulator() for side in SIDES}
            window_mode_accumulators = {
                mode: _AuditAccumulator() for mode in ANCHOR_MODES
            }
            candidate_identity: list[dict[str, str]] = []
            actual_candidate_count = 0
            for candidate in _iter_candidate_objects(
                bars, by_side, include_evidence=False
            ):
                actual_candidate_count += 1
                candidate_identity.append(_candidate_identity(candidate))
                evidence_summary = _pivot_evidence_summary(
                    bars,
                    by_side[candidate.side],
                    candidate.start_pivot,
                    candidate.end_pivot,
                    candidate.start_price,
                    candidate.end_price,
                    candidate.slope_per_bar,
                    candidate.intercept,
                )
                global_accumulator.add(candidate, evidence_summary=evidence_summary)
                mode_accumulators[candidate.anchor_mode].add(
                    candidate, evidence_summary=evidence_summary
                )
                side_accumulators[candidate.side].add(
                    candidate, evidence_summary=evidence_summary
                )
                window_mode_accumulators[candidate.anchor_mode].add(
                    candidate, evidence_summary=evidence_summary
                )
                asset_side_key = (source["asset"], candidate.side)
                asset_side_accumulator = asset_side_accumulators.setdefault(
                    asset_side_key, _AuditAccumulator()
                )
                asset_side_accumulator.add(candidate, evidence_summary=evidence_summary)
                asset_side_mode_key = (
                    source["asset"],
                    candidate.side,
                    candidate.anchor_mode,
                )
                asset_side_mode_accumulators.setdefault(
                    asset_side_mode_key, _AuditAccumulator()
                ).add(candidate, evidence_summary=evidence_summary)
            if actual_candidate_count != cardinality["total_candidate_count"]:
                raise ValueError("F1A cardinality preflight did not match iteration")
            window_key = f"{source['asset']}:{window['window']}"
            window_reports.append(
                {
                    "window": window_key,
                    "asset": source["asset"],
                    "timeframe": source["timeframe"],
                    "rows": len(bars),
                    "first_open_time": window["first_open_time"],
                    "last_close_time": window["last_close_time"],
                    "tape_id": _tape_id(bars, by_side, candidate_identity),
                    "cardinality_preflight": cardinality,
                    "by_side": {
                        side: {
                            "confirmed_pivot_count": len(by_side[side]),
                            **side_accumulators[side].as_report(),
                        }
                        for side in SIDES
                    },
                    "by_anchor_mode": {
                        mode: window_mode_accumulators[mode].as_report()
                        for mode in ANCHOR_MODES
                    },
                }
            )
    by_asset_side = {}
    for (asset, side), accumulator in asset_side_accumulators.items():
        by_asset_side[f"{asset}:{side}"] = {
            "asset": asset,
            "side": side,
            **accumulator.as_report(),
            "by_anchor_mode": {
                mode: asset_side_mode_accumulators[(asset, side, mode)].as_report()
                for mode in ANCHOR_MODES
            },
        }
    body = {
        "schema_version": SCHEMA_VERSION,
        "family": FAMILY_NAME,
        "pivot_window": PIVOT_WINDOW,
        "history_capacity_bars": HISTORY_CAPACITY_BARS,
        "g6_manifest_id": manifest["manifest_id"],
        "g6_manifest_sha256": G6_MANIFEST_SHA256,
        "window_count": len(window_reports),
        "row_count": sum(item["rows"] for item in window_reports),
        "window_inventory": window_reports,
        "by_asset_side": by_asset_side,
        "by_anchor_mode": {
            mode: mode_accumulators[mode].as_report() for mode in ANCHOR_MODES
        },
        "global": global_accumulator.as_report(),
        "selection": None,
        "conclusion": "DESCRIPTIVE_CANDIDATE_UNIVERSE_ONLY",
    }
    report = {**body, "report_id": _digest(body)}
    audit_manifest = {
        "schema_version": SCHEMA_VERSION,
        "family": FAMILY_NAME,
        "g6_manifest_id": manifest["manifest_id"],
        "g6_manifest_sha256": G6_MANIFEST_SHA256,
        "source_count": len(manifest["sources"]),
        "window_count": len(window_reports),
        "row_count": sum(item["rows"] for item in window_reports),
        "source_inventory": [
            {
                "asset": source["asset"],
                "timeframe": source["timeframe"],
                "path": source["path"],
                "sha256": source["sha256"],
                "data_row_count": source["data_row_count"],
                "windows": source["windows"],
            }
            for source in manifest["sources"]
        ],
        "implementation_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "report_id": report["report_id"],
    }
    return {**audit_manifest, "manifest_id": _digest(audit_manifest)}, report


def write_frozen_g6_audit(
    output_dir: str | Path = F1A_ARTIFACT_PATH,
) -> tuple[dict[str, object], dict[str, object]]:
    """Run and publish the two compact F1A audit artifacts exactly once."""

    directory = Path(output_dir)
    if directory.exists():
        raise ValueError(f"F1A output directory already exists: {directory}")
    manifest, report = audit_frozen_g6_sources()
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_bytes(_canonical_bytes(manifest))
    (directory / "report.json").write_bytes(_canonical_bytes(report))
    return manifest, report


__all__ = [
    "ANCHOR_MODES",
    "ANCHOR_SOURCES",
    "F1A_ARTIFACT_PATH",
    "FAMILY_NAME",
    "G6_MANIFEST_PATH",
    "SCHEMA_VERSION",
    "SIDES",
    "ConfirmedPivot",
    "PivotConsensusCandidate",
    "PivotConsensusTape",
    "PivotResidualObservation",
    "audit_frozen_g6_sources",
    "authenticate_g6_sources",
    "build_candidate_tape",
    "candidate_cardinality_preflight",
    "write_frozen_g6_audit",
]
