"""Deterministic evidence bundles for prepared trendline replays."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import pandas as pd

from libs.models.trendlines.data.contracts import TrendlineArtifactRef
from libs.models.trendlines.contracts.identity import canonical_hash
from libs.models.trendlines.workflows.research.diagnostics import (
    LineEvidenceRow,
    PivotCountRow,
    RayEvidenceRow,
    ReplayPivotRow,
    SignalEvidenceRow,
    SnapshotSummaryRow,
    TrendlineReplaySummary,
    _line_rows_from_points,
    _inspect_replay_pivots_from_point,
    _pivot_count_rows_from_points,
    _ray_rows_from_points,
    _signal_rows_from_points,
    _snapshot_rows_from_points,
    _summary_from_rows,
    build_line_evidence_id,
    build_pivot_count_evidence_id,
    build_ray_evidence_id,
    build_signal_evidence_id,
)
from libs.models.trendlines.workflows.research.replay import (
    PreparedTrendlineResearchReplay,
    TrendlineResearchReplaySpec,
    validated_replay_points,
)


RESEARCH_EVIDENCE_BUNDLE_SEMANTICS_VERSION = (
    "trendlines.research-evidence-bundle.v1"
)


class TrendlineEvidenceContractError(ValueError):
    """Raised when evidence selection or persistence is invalid."""


@dataclass(frozen=True)
class TrendlineEvidenceSelection:
    """Selection by replay coordinate only."""

    timeframe: str
    position: int

    def __post_init__(self) -> None:
        if not str(self.timeframe).strip():
            raise TrendlineEvidenceContractError("evidence timeframe is required")
        if isinstance(self.position, bool) or not isinstance(self.position, int):
            raise TrendlineEvidenceContractError("evidence position must be an integer")
        if self.position < 0:
            raise TrendlineEvidenceContractError("evidence position must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {"timeframe": self.timeframe, "position": self.position}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TrendlineEvidenceSelection":
        return cls(timeframe=payload["timeframe"], position=payload["position"])


RowT = TypeVar("RowT")


def _row_from_dict(row_type: type[RowT], payload: dict[str, Any]) -> RowT:
    return row_type(**payload)


@dataclass(frozen=True)
class TrendlineResearchEvidenceBundle:
    """Content-addressed replay diagnostics without full OHLCV frames."""

    bundle_id: str
    preparation_id: str
    dataset_id: str
    research_configuration_id: str
    replay_id: str
    replay_spec: TrendlineResearchReplaySpec
    summary: TrendlineReplaySummary
    snapshot_rows: tuple[SnapshotSummaryRow, ...]
    pivot_count_rows: tuple[PivotCountRow, ...]
    line_rows: tuple[LineEvidenceRow, ...]
    ray_rows: tuple[RayEvidenceRow, ...]
    signal_rows: tuple[SignalEvidenceRow, ...]
    selection: TrendlineEvidenceSelection
    selected_binding: dict[str, Any]
    selected_pivots: tuple[ReplayPivotRow, ...]
    evidence_semantics_version: str = RESEARCH_EVIDENCE_BUNDLE_SEMANTICS_VERSION

    def _payload_without_id(self) -> dict[str, Any]:
        return {
            "preparation_id": self.preparation_id,
            "dataset_id": self.dataset_id,
            "research_configuration_id": self.research_configuration_id,
            "replay_id": self.replay_id,
            "replay_spec": self.replay_spec.to_dict(),
            "summary": self.summary.to_dict(),
            "snapshot_rows": [row.to_dict() for row in self.snapshot_rows],
            "pivot_count_rows": [row.to_dict() for row in self.pivot_count_rows],
            "line_rows": [row.to_dict() for row in self.line_rows],
            "ray_rows": [row.to_dict() for row in self.ray_rows],
            "signal_rows": [row.to_dict() for row in self.signal_rows],
            "selection": self.selection.to_dict(),
            "selected_binding": dict(self.selected_binding),
            "selected_pivots": [row.to_dict() for row in self.selected_pivots],
            "evidence_semantics_version": self.evidence_semantics_version,
        }

    def computed_bundle_id(self) -> str:
        return canonical_hash(
            self._payload_without_id(),
            semantics_version=RESEARCH_EVIDENCE_BUNDLE_SEMANTICS_VERSION,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"bundle_id": self.bundle_id, **self._payload_without_id()}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TrendlineResearchEvidenceBundle":
        raw = dict(payload)
        return cls(
            bundle_id=str(raw["bundle_id"]),
            preparation_id=str(raw["preparation_id"]),
            dataset_id=str(raw["dataset_id"]),
            research_configuration_id=str(raw["research_configuration_id"]),
            replay_id=str(raw["replay_id"]),
            replay_spec=TrendlineResearchReplaySpec.from_dict(raw["replay_spec"]),
            summary=TrendlineReplaySummary(**dict(raw["summary"])),
            snapshot_rows=tuple(
                _row_from_dict(SnapshotSummaryRow, row)
                for row in raw.get("snapshot_rows", [])
            ),
            pivot_count_rows=tuple(
                _row_from_dict(PivotCountRow, row)
                for row in raw.get("pivot_count_rows", [])
            ),
            line_rows=tuple(
                _row_from_dict(LineEvidenceRow, row)
                for row in raw.get("line_rows", [])
            ),
            ray_rows=tuple(
                _row_from_dict(RayEvidenceRow, row)
                for row in raw.get("ray_rows", [])
            ),
            signal_rows=tuple(
                _row_from_dict(SignalEvidenceRow, row)
                for row in raw.get("signal_rows", [])
            ),
            selection=TrendlineEvidenceSelection.from_dict(raw["selection"]),
            selected_binding=dict(raw["selected_binding"]),
            selected_pivots=tuple(
                _row_from_dict(ReplayPivotRow, row)
                for row in raw.get("selected_pivots", [])
            ),
            evidence_semantics_version=str(
                raw.get(
                    "evidence_semantics_version",
                    RESEARCH_EVIDENCE_BUNDLE_SEMANTICS_VERSION,
                )
            ),
        )


def _require_binding_fields(binding: Mapping[str, Any], fields: tuple[str, ...]) -> None:
    missing = [field for field in fields if field not in binding]
    if missing:
        raise TrendlineEvidenceContractError(
            f"selected binding is missing fields: {', '.join(missing)}"
        )


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_sha256(value: Any, field: str) -> None:
    if not _is_sha256(value):
        raise TrendlineEvidenceContractError(
            f"{field} must be a lowercase SHA-256 identity"
        )


def _expected_recorded_coordinates(
    replay_spec: TrendlineResearchReplaySpec,
) -> set[tuple[str, int]]:
    coordinates: set[tuple[str, int]] = set()
    for timeframe, window in replay_spec.windows.items():
        coordinates.update(
            (timeframe, position)
            for position in range(
                window.record_start_position,
                window.end_position + 1,
                window.record_every,
            )
        )
    return coordinates


def validate_evidence_bundle(
    bundle: TrendlineResearchEvidenceBundle,
) -> None:
    """Validate cross-table evidence semantics after content-address checks."""

    if not isinstance(bundle, TrendlineResearchEvidenceBundle):
        raise TypeError("bundle must be a TrendlineResearchEvidenceBundle")
    binding_fields = (
        "timeframe",
        "position",
        "event_at",
        "available_at",
        "source_id",
        "checkpoint_id",
        "fit_snapshot_id",
        "fit_revision_id",
        "boundary_snapshot_id",
        "boundary_revision_id",
        "signal_snapshot_id",
        "signal_revision_id",
        "content_id",
        "replay_point_id",
    )
    _require_binding_fields(bundle.selected_binding, binding_fields)
    _require_sha256(bundle.selected_binding["content_id"], "selected content_id")
    _require_sha256(
        bundle.selected_binding["replay_point_id"],
        "selected replay_point_id",
    )
    if bundle.selection.timeframe != bundle.selected_binding["timeframe"]:
        raise TrendlineEvidenceContractError(
            "selection timeframe differs from selected binding timeframe"
        )
    if bundle.selection.position != bundle.selected_binding["position"]:
        raise TrendlineEvidenceContractError(
            "selection position differs from selected binding position"
        )

    selected_rows = [
        row
        for row in bundle.snapshot_rows
        if row.timeframe == bundle.selection.timeframe
        and row.position == bundle.selection.position
    ]
    if len(selected_rows) != 1:
        raise TrendlineEvidenceContractError(
            "selection must match exactly one snapshot row"
        )
    selected_row = selected_rows[0]
    row_binding_fields = (
        "timeframe",
        "position",
        "event_at",
        "available_at",
        "source_id",
        "checkpoint_id",
        "fit_snapshot_id",
        "fit_revision_id",
        "boundary_snapshot_id",
        "boundary_revision_id",
        "signal_snapshot_id",
        "signal_revision_id",
        "content_id",
        "replay_point_id",
    )
    for field in row_binding_fields:
        if getattr(selected_row, field) != bundle.selected_binding[field]:
            raise TrendlineEvidenceContractError(
                f"selected binding differs from snapshot row: {field}"
            )
    for pivot in bundle.selected_pivots:
        for field in (
            "timeframe",
            "position",
            "source_id",
            "checkpoint_id",
            "boundary_snapshot_id",
            "boundary_revision_id",
            "content_id",
            "replay_point_id",
        ):
            if field in {"timeframe", "position"}:
                expected = getattr(bundle.selection, field)
            else:
                expected = bundle.selected_binding[field]
            if getattr(pivot, field) != expected:
                raise TrendlineEvidenceContractError(
                    f"selected pivot differs from selected binding: {field}"
                )

    coordinates = [(row.timeframe, row.position) for row in bundle.snapshot_rows]
    if len(coordinates) != len(set(coordinates)):
        raise TrendlineEvidenceContractError(
            "snapshot rows contain duplicate timeframe/position coordinates"
        )
    snapshot_by_coordinate = {
        (row.timeframe, row.position): row for row in bundle.snapshot_rows
    }
    expected_coordinates = _expected_recorded_coordinates(bundle.replay_spec)
    actual_coordinates = set(snapshot_by_coordinate)
    if actual_coordinates != expected_coordinates:
        raise TrendlineEvidenceContractError(
            "snapshot coordinates do not match replay-spec recording positions"
        )
    for row in bundle.snapshot_rows:
        _require_sha256(row.replay_point_id, "snapshot replay_point_id")
        _require_sha256(row.content_id, "snapshot content_id")

    expected_finality = dict(
        sorted(Counter(row.finality for row in bundle.snapshot_rows).items())
    )
    expected_structure = dict(
        sorted(Counter(row.structure_state for row in bundle.snapshot_rows).items())
    )
    expected_interaction = dict(
        sorted(Counter(row.interaction for row in bundle.snapshot_rows).items())
    )
    summary = bundle.summary
    summary_fields = {
        "timeframe_count": (
            summary.timeframe_count,
            len(bundle.replay_spec.windows),
        ),
        "executed_point_count": (
            summary.executed_point_count,
            sum(
                window.end_position - window.warmup_start_position + 1
                for window in bundle.replay_spec.windows.values()
            ),
        ),
        "recorded_snapshot_count": (
            summary.recorded_snapshot_count,
            len(bundle.snapshot_rows),
        ),
        "unique_recorded_position_count": (
            summary.unique_recorded_position_count,
            len(actual_coordinates),
        ),
        "valid_point_count": (
            summary.valid_point_count,
            sum(row.fit_valid for row in bundle.snapshot_rows),
        ),
        "invalid_point_count": (
            summary.invalid_point_count,
            sum(not row.fit_valid for row in bundle.snapshot_rows),
        ),
        "support_line_total": (
            summary.support_line_total,
            sum(row.support_line_count for row in bundle.snapshot_rows),
        ),
        "resistance_line_total": (
            summary.resistance_line_total,
            sum(row.resistance_line_count for row in bundle.snapshot_rows),
        ),
        "support_ray_total": (
            summary.support_ray_total,
            sum(row.support_ray_count for row in bundle.snapshot_rows),
        ),
        "resistance_ray_total": (
            summary.resistance_ray_total,
            sum(row.resistance_ray_count for row in bundle.snapshot_rows),
        ),
        "signal_total": (summary.signal_total, len(bundle.signal_rows)),
        "finality_distribution": (summary.finality_distribution, expected_finality),
        "structure_state_distribution": (
            summary.structure_state_distribution,
            expected_structure,
        ),
        "interaction_distribution": (
            summary.interaction_distribution,
            expected_interaction,
        ),
    }
    for field, (actual, expected) in summary_fields.items():
        if actual != expected:
            raise TrendlineEvidenceContractError(
                f"summary does not match evidence rows: {field}"
            )

    expected_first_event = (
        min(bundle.snapshot_rows, key=lambda row: pd.Timestamp(row.event_at)).event_at
        if bundle.snapshot_rows
        else None
    )
    expected_last_event = (
        max(bundle.snapshot_rows, key=lambda row: pd.Timestamp(row.event_at)).event_at
        if bundle.snapshot_rows
        else None
    )
    expected_first_available = (
        min(bundle.snapshot_rows, key=lambda row: pd.Timestamp(row.available_at)).available_at
        if bundle.snapshot_rows
        else None
    )
    expected_last_available = (
        max(bundle.snapshot_rows, key=lambda row: pd.Timestamp(row.available_at)).available_at
        if bundle.snapshot_rows
        else None
    )
    bounds = {
        "first_event_at": (summary.first_event_at, expected_first_event),
        "last_event_at": (summary.last_event_at, expected_last_event),
        "first_available_at": (summary.first_available_at, expected_first_available),
        "last_available_at": (summary.last_available_at, expected_last_available),
    }
    for field, (actual, expected) in bounds.items():
        if actual != expected:
            raise TrendlineEvidenceContractError(
                f"summary does not contain global temporal extrema: {field}"
            )

    evidence_ids: set[str] = set()

    def validate_evidence_id(
        row: Any,
        builder: Any,
    ) -> None:
        _require_sha256(row.evidence_id, "diagnostic evidence_id")
        if row.evidence_id in evidence_ids:
            raise TrendlineEvidenceContractError(
                f"duplicate diagnostic evidence_id: {row.evidence_id}"
            )
        expected_id = builder(vars(row))
        if row.evidence_id != expected_id:
            raise TrendlineEvidenceContractError(
                "diagnostic evidence_id does not match row content"
            )
        evidence_ids.add(row.evidence_id)

    def require_point_binding(
        row: Any,
        snapshot: SnapshotSummaryRow,
        fields: tuple[str, ...],
    ) -> None:
        for field in fields:
            if getattr(row, field) != getattr(snapshot, field):
                raise TrendlineEvidenceContractError(
                    f"diagnostic row differs from snapshot row: {field}"
                )

    pivot_by_coordinate: dict[tuple[str, int], PivotCountRow] = {}
    line_by_coordinate: dict[tuple[str, int], list[LineEvidenceRow]] = {}
    ray_by_coordinate: dict[tuple[str, int], list[RayEvidenceRow]] = {}
    signal_by_coordinate: dict[tuple[str, int], list[SignalEvidenceRow]] = {}

    for row in bundle.pivot_count_rows:
        coordinate = (row.timeframe, row.position)
        snapshot = snapshot_by_coordinate.get(coordinate)
        if snapshot is None:
            raise TrendlineEvidenceContractError(
                "pivot-count row references unknown snapshot coordinate"
            )
        if coordinate in pivot_by_coordinate:
            raise TrendlineEvidenceContractError(
                "multiple pivot-count rows reference one coordinate"
            )
        require_point_binding(
            row,
            snapshot,
            (
                "timeframe",
                "position",
                "event_at",
                "available_at",
                "replay_point_id",
                "content_id",
                "source_id",
                "checkpoint_id",
            ),
        )
        validate_evidence_id(row, build_pivot_count_evidence_id)
        pivot_by_coordinate[coordinate] = row

    for row in bundle.line_rows:
        coordinate = (row.timeframe, row.position)
        snapshot = snapshot_by_coordinate.get(coordinate)
        if snapshot is None:
            raise TrendlineEvidenceContractError(
                "line row references unknown snapshot coordinate"
            )
        require_point_binding(
            row,
            snapshot,
            (
                "timeframe",
                "position",
                "replay_point_id",
                "content_id",
                "source_id",
                "checkpoint_id",
                "boundary_snapshot_id",
                "boundary_revision_id",
            ),
        )
        if row.role not in {"support", "resistance"}:
            raise TrendlineEvidenceContractError("line row has unknown role")
        validate_evidence_id(row, build_line_evidence_id)
        line_by_coordinate.setdefault(coordinate, []).append(row)

    for row in bundle.ray_rows:
        coordinate = (row.timeframe, row.position)
        snapshot = snapshot_by_coordinate.get(coordinate)
        if snapshot is None:
            raise TrendlineEvidenceContractError(
                "ray row references unknown snapshot coordinate"
            )
        require_point_binding(
            row,
            snapshot,
            (
                "timeframe",
                "position",
                "replay_point_id",
                "content_id",
                "source_id",
                "checkpoint_id",
                "boundary_snapshot_id",
                "boundary_revision_id",
            ),
        )
        if row.role not in {"support", "resistance"}:
            raise TrendlineEvidenceContractError("ray row has unknown role")
        validate_evidence_id(row, build_ray_evidence_id)
        ray_by_coordinate.setdefault(coordinate, []).append(row)

    for row in bundle.signal_rows:
        coordinate = (row.timeframe, row.position)
        snapshot = snapshot_by_coordinate.get(coordinate)
        if snapshot is None:
            raise TrendlineEvidenceContractError(
                "signal row references unknown snapshot coordinate"
            )
        require_point_binding(
            row,
            snapshot,
            (
                "timeframe",
                "position",
                "replay_point_id",
                "content_id",
                "source_id",
                "checkpoint_id",
                "signal_snapshot_id",
                "signal_revision_id",
            ),
        )
        validate_evidence_id(row, build_signal_evidence_id)
        signal_by_coordinate.setdefault(coordinate, []).append(row)

    def validate_ordinals(
        rows: list[Any],
        role: str | None = None,
    ) -> None:
        selected = [row for row in rows if role is None or row.role == role]
        ordinals = sorted(row.ordinal for row in selected)
        if ordinals != list(range(len(ordinals))):
            raise TrendlineEvidenceContractError(
                "diagnostic ordinals are not continuous per coordinate and role"
            )

    for coordinate, snapshot in snapshot_by_coordinate.items():
        pivot = pivot_by_coordinate.get(coordinate)
        if pivot is None:
            raise TrendlineEvidenceContractError(
                "every snapshot coordinate requires one pivot-count row"
            )
        lines = line_by_coordinate.get(coordinate, [])
        rays = ray_by_coordinate.get(coordinate, [])
        signals = signal_by_coordinate.get(coordinate, [])
        if sum(row.role == "support" for row in lines) != snapshot.support_line_count:
            raise TrendlineEvidenceContractError("support line count differs from snapshot")
        if sum(row.role == "resistance" for row in lines) != snapshot.resistance_line_count:
            raise TrendlineEvidenceContractError("resistance line count differs from snapshot")
        if sum(row.role == "support" for row in rays) != snapshot.support_ray_count:
            raise TrendlineEvidenceContractError("support ray count differs from snapshot")
        if sum(row.role == "resistance" for row in rays) != snapshot.resistance_ray_count:
            raise TrendlineEvidenceContractError("resistance ray count differs from snapshot")
        if len(signals) != snapshot.signal_count:
            raise TrendlineEvidenceContractError("signal count differs from snapshot")
        validate_ordinals(lines, "support")
        validate_ordinals(lines, "resistance")
        validate_ordinals(rays, "support")
        validate_ordinals(rays, "resistance")
        validate_ordinals(signals)

    if len(bundle.line_rows) != summary.support_line_total + summary.resistance_line_total:
        raise TrendlineEvidenceContractError("line rows do not match summary totals")
    if len(bundle.ray_rows) != summary.support_ray_total + summary.resistance_ray_total:
        raise TrendlineEvidenceContractError("ray rows do not match summary totals")
    if len(bundle.pivot_count_rows) != len(bundle.snapshot_rows):
        raise TrendlineEvidenceContractError("pivot-count rows must cover every snapshot row")

def _selected_binding(point: Any) -> dict[str, Any]:
    boundary = point.boundary_identity
    signal = point.signal_identity
    return {
        "timeframe": point.timeframe,
        "position": point.position,
        "event_at": point.event_at.isoformat(),
        "available_at": point.available_at.isoformat(),
        "source_id": point.prefix_source_ref.source_id,
        "checkpoint_id": boundary.checkpoint.checkpoint_id,
        "fit_snapshot_id": point.fit_snapshot_id,
        "fit_revision_id": point.fit_revision_id,
        "boundary_snapshot_id": boundary.snapshot_id,
        "boundary_revision_id": boundary.revision_id,
        "signal_snapshot_id": signal.snapshot_id if signal else None,
        "signal_revision_id": signal.revision_id if signal else None,
        "content_id": point.content_id,
        "replay_point_id": point.replay_point_id,
    }


def build_research_evidence_bundle(
    prepared: Any,
    replay: PreparedTrendlineResearchReplay,
    *,
    selection: TrendlineEvidenceSelection,
) -> TrendlineResearchEvidenceBundle:
    """Build all evidence from one selected replay coordinate."""

    if replay.prepared is not prepared:
        raise TrendlineEvidenceContractError("prepared run does not belong to replay")
    points = validated_replay_points(replay)
    point = next(
        (
            candidate
            for candidate in points
            if candidate.timeframe == selection.timeframe
            and candidate.position == selection.position
        ),
        None,
    )
    if point is None:
        raise TrendlineEvidenceContractError(
            "selection must identify a recorded replay point"
        )
    snapshot_rows = _snapshot_rows_from_points(replay, points)
    pivot_count_rows = _pivot_count_rows_from_points(replay, points)
    line_rows = _line_rows_from_points(replay, points)
    ray_rows = _ray_rows_from_points(replay, points)
    signal_rows = _signal_rows_from_points(replay, points)
    selected_pivots = _inspect_replay_pivots_from_point(
        prepared,
        replay,
        point,
        timeframe=selection.timeframe,
        position=selection.position,
    )
    summary = _summary_from_rows(replay, snapshot_rows)
    bundle = TrendlineResearchEvidenceBundle(
        bundle_id="pending",
        preparation_id=prepared.preparation_id,
        dataset_id=prepared.dataset.dataset_id,
        research_configuration_id=prepared.configuration.research_configuration_id,
        replay_id=replay.replay_id,
        replay_spec=replay.replay_spec,
        summary=summary,
        snapshot_rows=snapshot_rows,
        pivot_count_rows=pivot_count_rows,
        line_rows=line_rows,
        ray_rows=ray_rows,
        signal_rows=signal_rows,
        selection=selection,
        selected_binding=_selected_binding(point),
        selected_pivots=selected_pivots,
    )
    result = TrendlineResearchEvidenceBundle(
        bundle_id=bundle.computed_bundle_id(),
        preparation_id=bundle.preparation_id,
        dataset_id=bundle.dataset_id,
        research_configuration_id=bundle.research_configuration_id,
        replay_id=bundle.replay_id,
        replay_spec=bundle.replay_spec,
        summary=bundle.summary,
        snapshot_rows=bundle.snapshot_rows,
        pivot_count_rows=bundle.pivot_count_rows,
        line_rows=bundle.line_rows,
        ray_rows=bundle.ray_rows,
        signal_rows=bundle.signal_rows,
        selection=bundle.selection,
        selected_binding=bundle.selected_binding,
        selected_pivots=bundle.selected_pivots,
        evidence_semantics_version=bundle.evidence_semantics_version,
    )
    validate_evidence_bundle(result)
    return result


def _artifact_file(artifact: TrendlineArtifactRef) -> Path:
    if not isinstance(artifact, TrendlineArtifactRef):
        raise TypeError("artifact must be a TrendlineArtifactRef")
    root = Path(artifact.artifact_root)
    if artifact.relative_path:
        return root / artifact.relative_path
    if root.suffix:
        return root
    return root / (artifact.label or "trendline_research_evidence.json")


def write_research_evidence_bundle(
    bundle: TrendlineResearchEvidenceBundle,
    artifact: TrendlineArtifactRef,
) -> Path:
    """Persist one bundle only when explicitly requested."""

    if not isinstance(bundle, TrendlineResearchEvidenceBundle):
        raise TypeError("bundle must be a TrendlineResearchEvidenceBundle")
    validate_evidence_bundle(bundle)
    if bundle.computed_bundle_id() != bundle.bundle_id:
        raise TrendlineEvidenceContractError("bundle_id does not match bundle content")
    path = _artifact_file(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        bundle.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    path.write_text(encoded, encoding="utf-8")
    return path


def read_research_evidence_bundle(
    path_or_artifact: str | Path | TrendlineArtifactRef,
) -> TrendlineResearchEvidenceBundle:
    """Read and verify one deterministic evidence bundle."""

    if isinstance(path_or_artifact, TrendlineArtifactRef):
        path = _artifact_file(path_or_artifact)
    else:
        path = Path(path_or_artifact)
    raw = json.loads(path.read_text(encoding="utf-8"))
    bundle = TrendlineResearchEvidenceBundle.from_dict(raw)
    if bundle.computed_bundle_id() != bundle.bundle_id:
        raise TrendlineEvidenceContractError("evidence bundle content-address check failed")
    validate_evidence_bundle(bundle)
    return bundle


build_evidence_bundle = build_research_evidence_bundle


__all__ = [
    "RESEARCH_EVIDENCE_BUNDLE_SEMANTICS_VERSION",
    "TrendlineEvidenceContractError",
    "TrendlineEvidenceSelection",
    "TrendlineResearchEvidenceBundle",
    "build_evidence_bundle",
    "build_research_evidence_bundle",
    "read_research_evidence_bundle",
    "validate_evidence_bundle",
    "write_research_evidence_bundle",
]
