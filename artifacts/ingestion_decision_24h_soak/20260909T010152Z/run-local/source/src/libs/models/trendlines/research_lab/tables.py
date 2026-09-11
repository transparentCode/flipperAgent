"""Deterministic Pandas tables over validated lab/session contracts."""

from __future__ import annotations

from dataclasses import fields
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .comparison import compare_replay_positions


def _frame(rows: Iterable[dict[str, Any]], columns: tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame.from_records(list(rows), columns=list(columns))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _dataclass_rows(rows: Iterable[Any], columns: tuple[str, ...]) -> pd.DataFrame:
    return _frame((row.to_dict() for row in rows), columns)


def lab_controls_table(session: Any) -> pd.DataFrame:
    columns = (
        "purpose",
        "data_mode",
        "asset",
        "timeframes",
        "primary_timeframe",
        "include_signals",
        "provider_calls_authorized",
        "viewer_lookback_bars",
        "start_inline_viewers",
        "permanent_export",
        "selection_policy",
        "selected_positions",
        "replay_spec",
    )
    controls = session.controls
    return _frame(
        [
            {
                "purpose": controls.purpose.value,
                "data_mode": controls.data_mode.value,
                "asset": controls.asset,
                "timeframes": _json(list(controls.timeframes)),
                "primary_timeframe": controls.primary_timeframe,
                "include_signals": controls.include_signals,
                "provider_calls_authorized": controls.provider_calls_authorized,
                "viewer_lookback_bars": controls.viewer_lookback_bars,
                "start_inline_viewers": controls.start_inline_viewers,
                "permanent_export": controls.permanent_export,
                "selection_policy": controls.selection_policy,
                "selected_positions": _json(dict(controls.selected_positions)),
                "replay_spec": _json(controls.replay_spec.to_dict()),
            }
        ],
        columns,
    )


def lab_identity_table(session: Any) -> pd.DataFrame:
    columns = (
        "timeframe",
        "asset",
        "source_id",
        "availability_id",
        "dataset_id",
        "research_configuration_id",
        "preparation_id",
        "replay_id",
        "selected_position",
        "selection_reason",
        "evidence_bundle_id",
        "viewer_payload_id",
        "viewer_url",
    )
    identity = session.prepared.dataset.identity
    rows = []
    for timeframe in session.controls.timeframes:
        selection = session.selections.get(timeframe)
        rows.append(
            {
                "timeframe": timeframe,
                "asset": session.controls.asset,
                "source_id": identity.source_refs[timeframe].source_id,
                "availability_id": identity.availability_ids[timeframe],
                "dataset_id": session.dataset_id,
                "research_configuration_id": session.research_configuration_id,
                "preparation_id": session.preparation_id,
                "replay_id": session.replay_id,
                "selected_position": selection.position if selection else None,
                "selection_reason": selection.selection_reason if selection else None,
                "evidence_bundle_id": (
                    selection.evidence_bundle.bundle_id if selection else None
                ),
                "viewer_payload_id": (
                    selection.viewer_payload["payload_id"] if selection else None
                ),
                "viewer_url": session.viewer_urls.get(timeframe),
            }
        )
    return _frame(rows, columns)


def lab_source_table(session: Any) -> pd.DataFrame:
    columns = (
        "timeframe",
        "row_count",
        "event_start",
        "event_end",
        "availability_start",
        "availability_end",
        "source_id",
        "availability_id",
        "timestamp_semantics",
        "availability_source",
    )
    identity = session.prepared.dataset.identity
    rows = []
    for timeframe in session.controls.timeframes:
        frame = session.prepared.dataset.frames[timeframe]
        availability = pd.DatetimeIndex(frame["bar_available_at"])
        rows.append(
            {
                "timeframe": timeframe,
                "row_count": len(frame),
                "event_start": frame.index[0].isoformat(),
                "event_end": frame.index[-1].isoformat(),
                "availability_start": availability[0].isoformat(),
                "availability_end": availability[-1].isoformat(),
                "source_id": identity.source_refs[timeframe].source_id,
                "availability_id": identity.availability_ids[timeframe],
                "timestamp_semantics": identity.timestamp_semantics.value,
                "availability_source": identity.availability_sources[timeframe].value,
            }
        )
    return _frame(rows, columns)


def lab_config_table(session: Any) -> pd.DataFrame:
    columns = (
        "timeframe",
        "extractor",
        "extractor_params",
        "fitter",
        "fitter_params",
        "root_configuration_id",
        "search_grid_identity",
        "research_configuration_id",
    )
    configuration = session.prepared.configuration
    rows = []
    for timeframe in session.controls.timeframes:
        config = configuration.pipeline_configs[timeframe]
        rows.append(
            {
                "timeframe": timeframe,
                "extractor": config.extractor,
                "extractor_params": _json(config.extractor_params),
                "fitter": config.fitter,
                "fitter_params": _json(config.fitter_params),
                "root_configuration_id": configuration.root_configuration_id,
                "search_grid_identity": configuration.search_grid_identity,
                "research_configuration_id": configuration.research_configuration_id,
            }
        )
    return _frame(rows, columns)


def lab_replay_summary_table(session: Any) -> pd.DataFrame:
    columns = (
        "timeframe",
        "executed_position_count",
        "warmup_position_count",
        "recorded_position_count",
        "valid_point_count",
        "invalid_point_count",
        "support_line_total",
        "resistance_line_total",
        "support_ray_total",
        "resistance_ray_total",
        "signal_total",
        "first_event_at",
        "last_event_at",
        "first_available_at",
        "last_available_at",
        "selected_position",
        "selection_reason",
    )
    snapshots = session._diagnostics()["snapshot"]
    rows = []
    for timeframe in session.controls.timeframes:
        current = [row for row in snapshots if row.timeframe == timeframe]
        replay = session.replay.timeframes[timeframe]
        selected = session.selections.get(timeframe)
        rows.append(
            {
                "timeframe": timeframe,
                "executed_position_count": replay.executed_position_count,
                "warmup_position_count": replay.warmup_position_count,
                "recorded_position_count": len(current),
                "valid_point_count": sum(row.fit_valid for row in current),
                "invalid_point_count": sum(not row.fit_valid for row in current),
                "support_line_total": sum(row.support_line_count for row in current),
                "resistance_line_total": sum(row.resistance_line_count for row in current),
                "support_ray_total": sum(row.support_ray_count for row in current),
                "resistance_ray_total": sum(row.resistance_ray_count for row in current),
                "signal_total": sum(row.signal_count for row in current),
                "first_event_at": min((row.event_at for row in current), default=None),
                "last_event_at": max((row.event_at for row in current), default=None),
                "first_available_at": min((row.available_at for row in current), default=None),
                "last_available_at": max((row.available_at for row in current), default=None),
                "selected_position": selected.position if selected else None,
                "selection_reason": selected.selection_reason if selected else None,
            }
        )
    return _frame(rows, columns)


def lab_snapshot_timeline(session: Any, timeframe: str) -> pd.DataFrame:
    rows = [row for row in session._diagnostics()["snapshot"] if row.timeframe == timeframe]
    columns = tuple(field.name for field in fields(type(rows[0]))) if rows else (
        "timeframe",
        "position",
        "replay_point_id",
        "content_id",
        "event_at",
        "available_at",
        "source_id",
        "checkpoint_id",
    )
    return _dataclass_rows(rows, columns)


def lab_pivot_count_table(session: Any, timeframe: str) -> pd.DataFrame:
    rows = [row for row in session._diagnostics()["pivot_count"] if row.timeframe == timeframe]
    columns = tuple(field.name for field in fields(type(rows[0]))) if rows else (
        "evidence_id",
        "timeframe",
        "position",
        "n_high_pivots",
        "n_low_pivots",
        "extractor",
        "extractor_finality",
        "replay_point_id",
        "content_id",
        "source_id",
        "checkpoint_id",
    )
    return _dataclass_rows(rows, columns)


def lab_selected_pivot_table(selection: Any) -> pd.DataFrame:
    rows = selection.selected_pivots
    columns = tuple(field.name for field in fields(type(rows[0]))) if rows else (
        "timeframe",
        "position",
        "pivot_role",
        "bar_position",
        "event_at",
        "price",
        "extractor",
        "extractor_finality",
        "source_id",
        "checkpoint_id",
        "boundary_snapshot_id",
        "boundary_revision_id",
        "replay_point_id",
        "content_id",
    )
    return _dataclass_rows(rows, columns)


def lab_line_table(selection: Any) -> pd.DataFrame:
    rows = selection.line_rows
    columns = tuple(field.name for field in fields(type(rows[0]))) if rows else (
        "evidence_id",
        "timeframe",
        "position",
        "role",
        "ordinal",
        "method",
        "start_position",
        "end_position",
        "start_value",
        "end_value",
        "slope",
        "intercept",
        "touch_count",
        "score",
        "replay_point_id",
        "content_id",
        "source_id",
        "checkpoint_id",
        "boundary_snapshot_id",
        "boundary_revision_id",
    )
    return _dataclass_rows(rows, columns)


def lab_ray_table(selection: Any) -> pd.DataFrame:
    rows = selection.ray_rows
    columns = tuple(field.name for field in fields(type(rows[0]))) if rows else (
        "evidence_id",
        "timeframe",
        "position",
        "role",
        "ordinal",
        "start_time",
        "end_time",
        "start_price",
        "end_price",
        "slope",
        "intercept",
        "quality",
        "touch_count",
        "r_squared",
        "replay_point_id",
        "content_id",
        "source_id",
        "checkpoint_id",
        "boundary_snapshot_id",
        "boundary_revision_id",
    )
    return _dataclass_rows(rows, columns)


def lab_signal_table(selection: Any) -> pd.DataFrame:
    rows = selection.signal_rows
    columns = tuple(field.name for field in fields(type(rows[0]))) if rows else (
        "evidence_id",
        "timeframe",
        "position",
        "ordinal",
        "source",
        "name",
        "direction",
        "confidence",
        "metadata",
        "replay_point_id",
        "content_id",
        "source_id",
        "checkpoint_id",
        "signal_snapshot_id",
        "signal_revision_id",
    )
    return _dataclass_rows(rows, columns)


def lab_signal_history_table(selection: Any) -> pd.DataFrame:
    columns = (
        "timeframe",
        "position",
        "history_ordinal",
        "history_snapshot_id",
        "history_revision_id",
        "signal_input_id",
        "signal_query_known_at",
        "signal_available_at",
        "bar_timestamp_semantics",
        "bar_availability_source",
    )
    metadata = dict(selection.point.output.metadata)
    snapshots = list(metadata.get("history_snapshot_ids", []))
    revisions = list(metadata.get("history_revision_ids", []))
    rows = [
        {
            "timeframe": selection.timeframe,
            "position": selection.position,
            "history_ordinal": ordinal,
            "history_snapshot_id": snapshot_id,
            "history_revision_id": revisions[ordinal] if ordinal < len(revisions) else None,
            "signal_input_id": metadata.get("signal_input_id"),
            "signal_query_known_at": metadata.get("signal_query_known_at"),
            "signal_available_at": metadata.get("signal_available_at"),
            "bar_timestamp_semantics": metadata.get("bar_timestamp_semantics"),
            "bar_availability_source": metadata.get("bar_availability_source"),
        }
        for ordinal, snapshot_id in enumerate(snapshots)
    ]
    return _frame(rows, columns)


def lab_position_comparison_table(
    session: Any,
    *,
    timeframe: str,
    left_position: int,
    right_position: int,
) -> pd.DataFrame:
    comparison = compare_replay_positions(
        session,
        timeframe=timeframe,
        left_position=left_position,
        right_position=right_position,
    )
    columns = ("timeframe", "left_position", "right_position", "field", "left", "right")
    return _frame(
        [
            {
                "timeframe": comparison.timeframe,
                "left_position": comparison.left_position,
                "right_position": comparison.right_position,
                "field": field,
                "left": values[0],
                "right": values[1],
            }
            for field, values in comparison.differences.items()
        ],
        columns,
    )


def lab_performance_table(session: Any) -> pd.DataFrame:
    columns = ("scope", "timeframe", "operation", "milliseconds")
    rows = []
    timings = session.timings
    rows.extend(
        [
            {"scope": "session", "timeframe": None, "operation": "preparation", "milliseconds": timings.preparation_ms},
            {"scope": "session", "timeframe": None, "operation": "replay", "milliseconds": timings.replay_ms},
            {"scope": "session", "timeframe": None, "operation": "table_construction", "milliseconds": timings.table_ms},
            {"scope": "session", "timeframe": None, "operation": "total", "milliseconds": timings.total_ms},
        ]
    )
    for timeframe in session.controls.timeframes:
        rows.extend(
            [
                {"scope": "timeframe", "timeframe": timeframe, "operation": "evidence", "milliseconds": timings.evidence_ms_by_timeframe.get(timeframe, 0.0)},
                {"scope": "timeframe", "timeframe": timeframe, "operation": "viewer_payload", "milliseconds": timings.viewer_payload_ms_by_timeframe.get(timeframe, 0.0)},
                {"scope": "timeframe", "timeframe": timeframe, "operation": "viewer_bundle", "milliseconds": timings.viewer_bundle_ms_by_timeframe.get(timeframe, 0.0)},
                {"scope": "timeframe", "timeframe": timeframe, "operation": "viewer_startup", "milliseconds": timings.viewer_startup_ms_by_timeframe.get(timeframe, 0.0)},
            ]
        )
    return _frame(rows, columns)


def lab_export_table(session: Any) -> pd.DataFrame:
    columns = (
        "name",
        "path",
        "classification",
        "exists",
        "byte_length",
        "sha256",
        "preparation_id",
        "dataset_id",
        "replay_id",
        "evidence_bundle_id",
        "viewer_bundle_id",
        "viewer_payload_id",
    )
    rows: list[dict[str, Any]] = []
    for name, root in session.export_paths.items():
        root = Path(root)
        timeframe = name.split(".", 1)[0] if "." in name else None
        selection = session.selections.get(timeframe) if timeframe else None
        evidence_id = (
            selection.evidence_bundle.bundle_id if selection is not None else None
        )
        payload_id = (
            selection.viewer_payload.get("payload_id")
            if selection is not None
            else None
        )
        files = _export_files(root)
        if not files:
            rows.append(
                _export_row(
                    session=session,
                    name=name,
                    path=root,
                    exists=root.exists(),
                    byte_length=None,
                    digest=None,
                    evidence_id=evidence_id,
                    viewer_bundle_id=None,
                    payload_id=payload_id,
                )
            )
            continue
        viewer_bundle_id = _viewer_bundle_id(root)
        for file_path in files:
            logical_name = name
            if root.is_dir():
                logical_name = f"{name}/{file_path.relative_to(root).as_posix()}"
            data = file_path.read_bytes()
            rows.append(
                _export_row(
                    session=session,
                    name=logical_name,
                    path=file_path,
                    exists=True,
                    byte_length=len(data),
                    digest=sha256(data).hexdigest(),
                    evidence_id=evidence_id,
                    viewer_bundle_id=viewer_bundle_id,
                    payload_id=payload_id,
                )
            )
    return _frame(rows, columns)


def _export_files(root: Path) -> list[Path]:
    if root.is_symlink():
        raise ValueError(f"export path must not be a symlink: {root}")
    if root.is_file():
        return [root]
    if not root.is_dir():
        return []
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"export member must not be a symlink: {path}")
        if path.is_file():
            files.append(path)
    return files


def _viewer_bundle_id(root: Path) -> str | None:
    manifest = root / "manifest.json"
    if not manifest.is_file() or manifest.is_symlink():
        return None
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    bundle_id = value.get("bundle_id") if isinstance(value, dict) else None
    return bundle_id if isinstance(bundle_id, str) else None


def _export_row(
    *,
    session: Any,
    name: str,
    path: Path,
    exists: bool,
    byte_length: int | None,
    digest: str | None,
    evidence_id: str | None,
    viewer_bundle_id: str | None,
    payload_id: str | None,
) -> dict[str, Any]:
    return {
        "name": name,
        "path": str(path),
        "classification": "file" if path.is_file() else "directory",
        "exists": exists,
        "byte_length": byte_length,
        "sha256": digest,
        "preparation_id": session.preparation_id,
        "dataset_id": session.dataset_id,
        "replay_id": session.replay_id,
        "evidence_bundle_id": evidence_id,
        "viewer_bundle_id": viewer_bundle_id,
        "viewer_payload_id": payload_id,
    }


def lab_study_registry_table(session: Any) -> pd.DataFrame:
    columns = ("status", "study")
    registry = session.study_registry.to_dict()
    return _frame(
        [
            {"status": status, "study": study}
            for status, studies in registry.items()
            for study in studies
        ],
        columns,
    )


__all__ = [
    "lab_config_table",
    "lab_controls_table",
    "lab_export_table",
    "lab_identity_table",
    "lab_line_table",
    "lab_performance_table",
    "lab_pivot_count_table",
    "lab_position_comparison_table",
    "lab_ray_table",
    "lab_replay_summary_table",
    "lab_selected_pivot_table",
    "lab_signal_history_table",
    "lab_signal_table",
    "lab_snapshot_timeline",
    "lab_source_table",
    "lab_study_registry_table",
]
