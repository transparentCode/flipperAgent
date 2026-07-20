"""Self-owned deterministic pathfinding fitter for causal pivot candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Mapping

import pandas as pd

from .configuration.contracts import CandidateConfig, ResolvedTrendlineFamilyConfig
from .contracts import ContractValidationError, FamilyRole, LineGeometry, require_utc
from .pivots import (
    ConfirmedPivot,
    PivotExtractionResult,
    confirmed_ohlcv_window,
    freeze_result_metadata,
)


FITTER_NAME = "pathfinding"
QUALITY_METHOD = "anchor_span_coverage_v1"
_GEOMETRY_TOLERANCE = 1e-9


class PathfindingFitStatus(str, Enum):
    VALID = "valid"
    INSUFFICIENT_PIVOTS = "insufficient_pivots"
    NO_VALID_FITTED_PATHS = "no_valid_fitted_paths"


@dataclass(frozen=True)
class FittedPath:
    """A pathfinding result with exact geometry defined by its final two anchors."""

    role: FamilyRole | str
    geometry: LineGeometry
    anchor_pivots: tuple[ConfirmedPivot, ConfirmedPivot]
    path_pivots: tuple[ConfirmedPivot, ...]
    coverage: float
    quality: float
    quality_method: str = QUALITY_METHOD
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            role = FamilyRole(self.role)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(f"invalid fitted path role: {self.role!r}") from exc
        if role not in {FamilyRole.SUPPORT, FamilyRole.RESISTANCE}:
            raise ContractValidationError("fitted path role must be SUPPORT or RESISTANCE")
        object.__setattr__(self, "role", role)
        if not isinstance(self.geometry, LineGeometry):
            raise ContractValidationError("fitted path geometry must be LineGeometry")

        anchors = tuple(self.anchor_pivots)
        if len(anchors) != 2 or any(not isinstance(pivot, ConfirmedPivot) for pivot in anchors):
            raise ContractValidationError("fitted path requires exactly two canonical anchor pivots")
        if anchors[0].pivot_id == anchors[1].pivot_id:
            raise ContractValidationError("fitted path anchor pivot IDs must be unique")
        path = tuple(self.path_pivots)
        if len(path) < 2 or any(not isinstance(pivot, ConfirmedPivot) for pivot in path):
            raise ContractValidationError("fitted path requires at least two canonical path pivots")
        if len({pivot.pivot_id for pivot in path}) != len(path):
            raise ContractValidationError("fitted path pivot IDs must be unique")
        if tuple(path[-2:]) != anchors:
            raise ContractValidationError("fitted path anchors must be the final two path pivots")
        expected_kind = "low" if role is FamilyRole.SUPPORT else "high"
        if any(pivot.kind != expected_kind for pivot in path):
            raise ContractValidationError("fitted path pivot kind conflicts with role")
        if any(
            current.index <= previous.index
            or current.timestamp <= previous.timestamp
            or current.confirmation_index <= previous.confirmation_index
            or current.confirmation_time <= previous.confirmation_time
            for previous, current in zip(path, path[1:])
        ):
            raise ContractValidationError("fitted path pivots must be strictly time-ordered")
        if any(
            not math.isclose(
                self.geometry.value_at(anchor.timestamp),
                anchor.price,
                rel_tol=1e-12,
                abs_tol=_GEOMETRY_TOLERANCE,
            )
            for anchor in anchors
        ):
            raise ContractValidationError("fitted path geometry must pass through declared anchors")
        for field_name in ("coverage", "quality"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ContractValidationError(f"fitted path {field_name} must be numeric")
            value = float(value)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ContractValidationError(f"fitted path {field_name} must be in [0, 1]")
            object.__setattr__(self, field_name, value)
        if not math.isclose(self.coverage, self.quality, rel_tol=0.0, abs_tol=1e-12):
            raise ContractValidationError("initial fitted path quality must equal anchor-span coverage")
        if not isinstance(self.quality_method, str) or not self.quality_method:
            raise ContractValidationError("fitted path quality_method must be a non-empty string")
        object.__setattr__(self, "anchor_pivots", anchors)
        object.__setattr__(self, "path_pivots", path)
        object.__setattr__(
            self,
            "metadata",
            freeze_result_metadata(self.metadata, field_name="fitted path metadata"),
        )


@dataclass(frozen=True)
class PathfindingFitResult:
    """Immutable result boundary for one pathfinding fitter invocation."""

    status: PathfindingFitStatus | str
    lines: tuple[FittedPath, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            status = PathfindingFitStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(f"invalid pathfinding fit status: {self.status!r}") from exc
        lines = tuple(self.lines)
        if any(not isinstance(line, FittedPath) for line in lines):
            raise ContractValidationError("pathfinding lines must contain only FittedPath values")
        fingerprints = {(line.role.value, tuple(pivot.pivot_id for pivot in line.anchor_pivots)) for line in lines}
        if len(fingerprints) != len(lines):
            raise ContractValidationError("pathfinding lines must have unique role and anchor IDs")
        if status is PathfindingFitStatus.VALID and not lines:
            raise ContractValidationError("valid pathfinding result requires fitted lines")
        if status is not PathfindingFitStatus.VALID and lines:
            raise ContractValidationError("empty pathfinding status cannot contain fitted lines")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "lines", lines)
        object.__setattr__(
            self,
            "metadata",
            freeze_result_metadata(self.metadata, field_name="pathfinding result metadata"),
        )


class PathfindingLineFitter:
    """Find non-crossing support and resistance paths from confirmed pivots."""

    def fit(
        self,
        ohlcv: pd.DataFrame,
        pivots: PivotExtractionResult,
        *,
        config: ResolvedTrendlineFamilyConfig,
    ) -> PathfindingFitResult:
        if not isinstance(config, ResolvedTrendlineFamilyConfig):
            raise ContractValidationError("pathfinding fitter requires ResolvedTrendlineFamilyConfig")
        if not isinstance(pivots, PivotExtractionResult):
            raise ContractValidationError("pathfinding fitter requires PivotExtractionResult")
        frame = self._validated_frame(ohlcv, pivots)
        candidate_config = config.candidate
        support = self._fit_role(
            frame,
            pivots.low_pivots,
            role=FamilyRole.SUPPORT,
            config=candidate_config,
        )
        resistance = self._fit_role(
            frame,
            pivots.high_pivots,
            role=FamilyRole.RESISTANCE,
            config=candidate_config,
        )
        lines = tuple((*support, *resistance))
        metadata = {
            "available_support_pivots": len(pivots.low_pivots),
            "available_resistance_pivots": len(pivots.high_pivots),
            "min_pivots_per_side": candidate_config.min_pivots_per_side,
        }
        if lines:
            return PathfindingFitResult(
                status=PathfindingFitStatus.VALID,
                lines=lines,
                metadata=metadata,
            )
        if (
            len(pivots.low_pivots) < candidate_config.min_pivots_per_side
            and len(pivots.high_pivots) < candidate_config.min_pivots_per_side
        ):
            return PathfindingFitResult(
                status=PathfindingFitStatus.INSUFFICIENT_PIVOTS,
                lines=(),
                metadata=metadata,
            )
        return PathfindingFitResult(
            status=PathfindingFitStatus.NO_VALID_FITTED_PATHS,
            lines=(),
            metadata=metadata,
        )

    @staticmethod
    def _validated_frame(ohlcv: pd.DataFrame, pivots: PivotExtractionResult) -> pd.DataFrame:
        if not isinstance(ohlcv, pd.DataFrame) or ohlcv.empty:
            raise ContractValidationError("pathfinding fitter requires a non-empty OHLCV DataFrame")
        observed_at = require_utc(ohlcv.index[-1].to_pydatetime(), field_name="OHLCV final timestamp")
        frame = confirmed_ohlcv_window(
            ohlcv,
            observed_at=observed_at,
            required_columns=frozenset({"open", "high", "low", "close"}),
        )
        if len(frame) != len(ohlcv) or pivots.confirmed_bars != len(frame):
            raise ContractValidationError("pivot result must align with the supplied confirmed OHLCV frame")
        for pivot in pivots.pivots:
            if pivot.confirmation_index >= len(frame):
                raise ContractValidationError("pivot confirmation index exceeds supplied frame")
            timestamp = require_utc(
                frame.index[pivot.index].to_pydatetime(),
                field_name="frame pivot timestamp",
            )
            confirmation_time = require_utc(
                frame.index[pivot.confirmation_index].to_pydatetime(),
                field_name="frame pivot confirmation timestamp",
            )
            if timestamp != pivot.timestamp or confirmation_time != pivot.confirmation_time:
                raise ContractValidationError("pivot index/timestamp alignment does not match supplied frame")
        return frame

    def _fit_role(
        self,
        ohlcv: pd.DataFrame,
        pivots: tuple[ConfirmedPivot, ...],
        *,
        role: FamilyRole,
        config: CandidateConfig,
    ) -> tuple[FittedPath, ...]:
        if len(pivots) < config.min_pivots_per_side:
            return ()
        path = self._best_path(ohlcv, tuple(sorted(pivots, key=lambda pivot: pivot.index)), role=role)
        if len(path) < 2:
            return ()
        first_anchor, second_anchor = path[-2:]
        geometry = self._geometry_between(first_anchor, second_anchor)
        coverage = self._anchor_span_coverage(ohlcv, first_anchor, second_anchor)
        return (
            FittedPath(
                role=role,
                geometry=geometry,
                anchor_pivots=(first_anchor, second_anchor),
                path_pivots=tuple(path),
                coverage=coverage,
                quality=coverage,
                quality_method=QUALITY_METHOD,
                metadata={"path_score_coordinate": "elapsed_seconds"},
            ),
        )

    def _best_path(
        self,
        ohlcv: pd.DataFrame,
        pivots: tuple[ConfirmedPivot, ...],
        *,
        role: FamilyRole,
    ) -> list[ConfirmedPivot]:
        scores = [0.0] * len(pivots)
        evidence_counts = [1] * len(pivots)
        parents: list[int | None] = [None] * len(pivots)
        for current_position, current in enumerate(pivots):
            for previous_position in range(current_position):
                previous = pivots[previous_position]
                if not self._segment_is_valid(ohlcv, previous, current, role=role):
                    continue
                score = scores[previous_position] + (current.timestamp - previous.timestamp).total_seconds()
                evidence_count = evidence_counts[previous_position] + 1
                existing_parent = parents[current_position]
                is_better = score > scores[current_position]
                is_equal_score = math.isclose(score, scores[current_position], rel_tol=0.0, abs_tol=1e-12)
                if is_equal_score and evidence_count > evidence_counts[current_position]:
                    is_better = True
                if (
                    is_equal_score
                    and evidence_count == evidence_counts[current_position]
                    and existing_parent is not None
                    and previous_position < existing_parent
                ):
                    is_better = True
                if is_better:
                    scores[current_position] = score
                    evidence_counts[current_position] = evidence_count
                    parents[current_position] = previous_position

        best_end = max(range(len(pivots)), key=lambda index: (scores[index], evidence_counts[index]))
        if parents[best_end] is None:
            return []
        path: list[ConfirmedPivot] = []
        cursor: int | None = best_end
        while cursor is not None:
            path.append(pivots[cursor])
            cursor = parents[cursor]
        path.reverse()
        return path

    def _segment_is_valid(
        self,
        ohlcv: pd.DataFrame,
        previous: ConfirmedPivot,
        current: ConfirmedPivot,
        *,
        role: FamilyRole,
    ) -> bool:
        geometry = self._geometry_between(previous, current)
        body_top = ohlcv[["open", "close"]].max(axis=1).astype(float).to_list()
        body_bottom = ohlcv[["open", "close"]].min(axis=1).astype(float).to_list()
        for index in range(previous.index + 1, current.index):
            timestamp = require_utc(
                ohlcv.index[index].to_pydatetime(),
                field_name="intermediate candle timestamp",
            )
            line_value = geometry.value_at(timestamp)
            if role is FamilyRole.SUPPORT and line_value > body_bottom[index]:
                return False
            if role is FamilyRole.RESISTANCE and line_value < body_top[index]:
                return False
        return True

    @staticmethod
    def _geometry_between(first: ConfirmedPivot, second: ConfirmedPivot) -> LineGeometry:
        elapsed_seconds = (second.timestamp - first.timestamp).total_seconds()
        if elapsed_seconds <= 0:
            raise ContractValidationError("fitted pivot timestamps must be strictly increasing")
        return LineGeometry(
            reference_time=first.timestamp,
            reference_price=first.price,
            slope_per_second=(second.price - first.price) / elapsed_seconds,
        )

    @staticmethod
    def _anchor_span_coverage(
        ohlcv: pd.DataFrame,
        first: ConfirmedPivot,
        second: ConfirmedPivot,
    ) -> float:
        start = require_utc(ohlcv.index[0].to_pydatetime(), field_name="OHLCV start timestamp")
        end = require_utc(ohlcv.index[-1].to_pydatetime(), field_name="OHLCV end timestamp")
        total_seconds = (end - start).total_seconds()
        if total_seconds <= 0:
            return 0.0
        span_seconds = (second.timestamp - first.timestamp).total_seconds()
        return min(max(span_seconds / total_seconds, 0.0), 1.0)
