"""Descriptive replay-position and completed-session comparisons."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .contracts import TrendlineResearchLabContractError


@dataclass(frozen=True)
class TrendlineReplayPositionComparison:
    """Exact field differences; deliberately makes no quality judgement."""

    timeframe: str
    left_position: int
    right_position: int
    differences: dict[str, tuple[Any, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "left_position": self.left_position,
            "right_position": self.right_position,
            "differences": {
                key: [values[0], values[1]]
                for key, values in self.differences.items()
            },
        }


@dataclass(frozen=True)
class TrendlineLabSessionComparison:
    """Compatibility audit for already completed sessions."""

    compatible: bool
    mismatches: tuple[dict[str, Any], ...]
    sessions_compared: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "compatible": self.compatible,
            "mismatches": [dict(value) for value in self.mismatches],
            "sessions_compared": self.sessions_compared,
        }


def _snapshot(session: Any, timeframe: str, position: int) -> Any:
    rows = [
        row
        for row in session._diagnostics()["snapshot"]
        if row.timeframe == timeframe and row.position == position
    ]
    if len(rows) != 1:
        raise TrendlineResearchLabContractError(
            f"expected one snapshot row at {timeframe}/{position}"
        )
    return rows[0]


def _pivot_count(session: Any, timeframe: str, position: int) -> Any:
    rows = [
        row
        for row in session._diagnostics()["pivot_count"]
        if row.timeframe == timeframe and row.position == position
    ]
    if len(rows) != 1:
        raise TrendlineResearchLabContractError(
            f"expected one pivot-count row at {timeframe}/{position}"
        )
    return rows[0]


def compare_replay_positions(
    session: Any,
    *,
    timeframe: str,
    left_position: int,
    right_position: int,
) -> TrendlineReplayPositionComparison:
    """Return exact differences between two recorded positions."""

    left = _snapshot(session, timeframe, left_position)
    right = _snapshot(session, timeframe, right_position)
    left_pivots = _pivot_count(session, timeframe, left_position)
    right_pivots = _pivot_count(session, timeframe, right_position)
    fields = {
        "event_at": (left.event_at, right.event_at),
        "available_at": (left.available_at, right.available_at),
        "source_id": (left.source_id, right.source_id),
        "checkpoint_id": (left.checkpoint_id, right.checkpoint_id),
        "content_id": (left.content_id, right.content_id),
        "replay_point_id": (left.replay_point_id, right.replay_point_id),
        "fit_snapshot_id": (left.fit_snapshot_id, right.fit_snapshot_id),
        "fit_revision_id": (left.fit_revision_id, right.fit_revision_id),
        "boundary_snapshot_id": (left.boundary_snapshot_id, right.boundary_snapshot_id),
        "boundary_revision_id": (left.boundary_revision_id, right.boundary_revision_id),
        "signal_snapshot_id": (left.signal_snapshot_id, right.signal_snapshot_id),
        "signal_revision_id": (left.signal_revision_id, right.signal_revision_id),
        "fit_valid": (left.fit_valid, right.fit_valid),
        "finality": (left.finality, right.finality),
        "structure_state": (left.structure_state, right.structure_state),
        "interaction": (left.interaction, right.interaction),
        "market_position_state": (left.market_position_state, right.market_position_state),
        "support_line_count": (left.support_line_count, right.support_line_count),
        "resistance_line_count": (left.resistance_line_count, right.resistance_line_count),
        "support_ray_count": (left.support_ray_count, right.support_ray_count),
        "resistance_ray_count": (left.resistance_ray_count, right.resistance_ray_count),
        "n_high_pivots": (left_pivots.n_high_pivots, right_pivots.n_high_pivots),
        "n_low_pivots": (left_pivots.n_low_pivots, right_pivots.n_low_pivots),
        "mean_quality": (left.mean_quality, right.mean_quality),
        "signal_count": (left.signal_count, right.signal_count),
        "composite_direction": (left.composite_direction, right.composite_direction),
        "composite_confidence": (left.composite_confidence, right.composite_confidence),
    }
    return TrendlineReplayPositionComparison(
        timeframe=timeframe,
        left_position=left_position,
        right_position=right_position,
        differences={key: value for key, value in fields.items() if value[0] != value[1]},
    )


def compare_lab_sessions(
    sessions: Iterable[Any],
    *,
    require_same_timeframes: bool = True,
    require_same_replay_policy: bool = True,
) -> TrendlineLabSessionComparison:
    """Audit comparability of caller-supplied completed sessions."""

    values = tuple(sessions)
    if not values:
        raise TrendlineResearchLabContractError("at least one session is required")
    first = values[0]
    mismatches: list[dict[str, Any]] = []
    for index, session in enumerate(values[1:], start=1):
        if require_same_timeframes and tuple(session.controls.timeframes) != tuple(first.controls.timeframes):
            mismatches.append(
                {"session": index, "field": "timeframes", "expected": first.controls.timeframes, "actual": session.controls.timeframes}
            )
        if require_same_replay_policy and session.controls.replay_spec.to_dict() != first.controls.replay_spec.to_dict():
            mismatches.append(
                {"session": index, "field": "replay_spec", "expected": first.controls.replay_spec.to_dict(), "actual": session.controls.replay_spec.to_dict()}
            )
        checks = (
            ("research_configuration_id", first.research_configuration_id, session.research_configuration_id),
            ("include_signals", first.controls.include_signals, session.controls.include_signals),
            ("timestamp_semantics", first.prepared.dataset.identity.timestamp_semantics.value, session.prepared.dataset.identity.timestamp_semantics.value),
            ("availability_sources", dict(first.prepared.dataset.identity.availability_sources), dict(session.prepared.dataset.identity.availability_sources)),
        )
        for field, expected, actual in checks:
            if expected != actual:
                mismatches.append(
                    {"session": index, "field": field, "expected": expected, "actual": actual}
                )
    return TrendlineLabSessionComparison(
        compatible=not mismatches,
        mismatches=tuple(mismatches),
        sessions_compared=len(values),
    )


__all__ = [
    "TrendlineLabSessionComparison",
    "TrendlineReplayPositionComparison",
    "compare_lab_sessions",
    "compare_replay_positions",
]
