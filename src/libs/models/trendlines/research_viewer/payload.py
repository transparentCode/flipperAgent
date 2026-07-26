"""Strict, read-only chart payloads built from validated research evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from libs.models.trendlines.contracts.identity import canonical_hash
from libs.models.trendlines.workflows.research.diagnostics import (
    LineEvidenceRow,
    RayEvidenceRow,
    ReplayPivotRow,
    SignalEvidenceRow,
    SnapshotSummaryRow,
)
from libs.models.trendlines.workflows.research.evidence import (
    TrendlineResearchEvidenceBundle,
    validate_evidence_bundle,
)
from libs.models.trendlines.workflows.research.replay import (
    PreparedTrendlineResearchReplay,
    TrendlineReplayPoint,
    validate_replay_point_integrity,
)

from .contracts import (
    VIEWER_DISPLAY_WINDOW_SEMANTICS_VERSION,
    VIEWER_PAYLOAD_SCHEMA_VERSION,
    VIEWER_PAYLOAD_SEMANTICS_VERSION,
    TrendlineViewerContractError,
    TrendlineViewerSpec,
    exact_keys,
    finite_number,
    integer_seconds,
    require_sha256,
)


_TOP_LEVEL_KEYS = {
    "schema_version",
    "payload_id",
    "asset",
    "timeframe",
    "selected_position",
    "event_at",
    "available_at",
    "finality",
    "dataset_id",
    "research_configuration_id",
    "replay_id",
    "evidence_bundle_id",
    "source_id",
    "checkpoint_id",
    "content_id",
    "replay_point_id",
    "fit_snapshot_id",
    "fit_revision_id",
    "boundary_snapshot_id",
    "boundary_revision_id",
    "signal_snapshot_id",
    "signal_revision_id",
    "display_start_position",
    "display_end_position",
    "display_window_id",
    "candles",
    "pivots",
    "lines",
    "rays",
    "signals",
    "selected_summary",
    "replay_timeline",
}
_CANDLE_KEYS = {"time", "open", "high", "low", "close", "volume"}
_PIVOT_KEYS = {
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
}
_LINE_KEYS = {
    "evidence_id",
    "role",
    "ordinal",
    "method",
    "start_position",
    "end_position",
    "start_time",
    "end_time",
    "start_price",
    "end_price",
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
}
_RAY_KEYS = {
    "evidence_id",
    "role",
    "ordinal",
    "start_position",
    "end_position",
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
}
_SIGNAL_KEYS = {
    "evidence_id",
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
}
_SUMMARY_KEYS = {
    "timeframe",
    "position",
    "event_at",
    "available_at",
    "fit_valid",
    "finality",
    "structure_state",
    "interaction",
    "market_position_state",
    "hull_width_atr",
    "mean_quality",
    "signal_count",
    "composite_direction",
    "composite_confidence",
    "replay_point_id",
    "content_id",
}
_TIMELINE_KEYS = {
    "position",
    "event_at",
    "available_at",
    "fit_valid",
    "finality",
    "structure_state",
    "interaction",
    "market_position_state",
    "hull_width_atr",
    "mean_quality",
    "signal_count",
    "composite_direction",
    "composite_confidence",
    "replay_point_id",
    "content_id",
}
_IDENTITY_FIELDS = (
    "dataset_id",
    "research_configuration_id",
    "replay_id",
    "evidence_bundle_id",
    "source_id",
    "checkpoint_id",
    "content_id",
    "replay_point_id",
    "boundary_snapshot_id",
    "boundary_revision_id",
)
_OPTIONAL_IDENTITY_FIELDS = (
    "fit_snapshot_id",
    "fit_revision_id",
    "signal_snapshot_id",
    "signal_revision_id",
)


def _whole_seconds(value: Any, field_name: str) -> int:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise TrendlineViewerContractError(f"{field_name} must be timezone-aware")
    timestamp = timestamp.tz_convert("UTC")
    if timestamp.nanosecond:
        raise TrendlineViewerContractError(
            f"{field_name} must align to whole UNIX seconds"
        )
    return int(timestamp.timestamp())


def _clean_datetime(value: Any, field_name: str) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise TrendlineViewerContractError(f"{field_name} must be timezone-aware")
    return timestamp.tz_convert("UTC").isoformat()


def _frame_position_time(frame: pd.DataFrame, position: int, field_name: str) -> int:
    if isinstance(position, bool) or not isinstance(position, int):
        raise TrendlineViewerContractError(f"{field_name} must be an integer")
    if position < 0 or position >= len(frame):
        raise TrendlineViewerContractError(f"{field_name} is outside prepared data")
    return _whole_seconds(frame.index[position], field_name)


def _frame_position_for_timestamp(
    frame: pd.DataFrame,
    value: Any,
    field_name: str,
) -> int:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise TrendlineViewerContractError(f"{field_name} must be timezone-aware")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise TrendlineViewerContractError("prepared frame index must be timezone-aware")
    timestamp = timestamp.tz_convert("UTC")
    positions = frame.index.get_indexer([timestamp])
    if len(positions) != 1 or positions[0] < 0:
        raise TrendlineViewerContractError(
            f"{field_name} does not match a prepared frame timestamp"
        )
    return int(positions[0])


def _display_window_id(
    *,
    replay_point_id: str,
    content_id: str,
    start_position: int,
    end_position: int,
    candles: list[dict[str, Any]],
) -> str:
    return canonical_hash(
        {
            "replay_point_id": replay_point_id,
            "content_id": content_id,
            "display_start_position": start_position,
            "display_end_position": end_position,
            "candles": candles,
            "semantics_version": VIEWER_DISPLAY_WINDOW_SEMANTICS_VERSION,
        },
        semantics_version=VIEWER_DISPLAY_WINDOW_SEMANTICS_VERSION,
    )


def _point_identity(point: TrendlineReplayPoint) -> dict[str, Any]:
    boundary = point.boundary_identity
    signal = point.signal_identity
    return {
        "source_id": point.prefix_source_ref.source_id,
        "checkpoint_id": boundary.checkpoint.checkpoint_id,
        "content_id": point.content_id,
        "replay_point_id": point.replay_point_id,
        "fit_snapshot_id": point.fit_snapshot_id,
        "fit_revision_id": point.fit_revision_id,
        "boundary_snapshot_id": boundary.snapshot_id,
        "boundary_revision_id": boundary.revision_id,
        "signal_snapshot_id": signal.snapshot_id if signal else None,
        "signal_revision_id": signal.revision_id if signal else None,
    }


def _candle_payloads(
    frame: pd.DataFrame,
    start_position: int,
    end_position: int,
) -> list[dict[str, Any]]:
    window = frame.iloc[start_position : end_position + 1]
    timestamp_ns = window.index.to_numpy(dtype="datetime64[ns]").astype("int64")
    if (timestamp_ns % 1_000_000_000 != 0).any():
        raise TrendlineViewerContractError("candle event times must align to whole seconds")
    values = window.loc[:, ["open", "high", "low", "close", "volume"]].to_numpy(
        dtype=float,
    )
    seconds = timestamp_ns // 1_000_000_000
    return [
        {
            "time": int(seconds[index]),
            "open": float(values[index, 0]),
            "high": float(values[index, 1]),
            "low": float(values[index, 2]),
            "close": float(values[index, 3]),
            "volume": float(values[index, 4]),
        }
        for index in range(len(window))
    ]


def _line_payload(row: LineEvidenceRow, frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "evidence_id": row.evidence_id,
        "role": row.role,
        "ordinal": row.ordinal,
        "method": row.method,
        "start_position": row.start_position,
        "end_position": row.end_position,
        "start_time": _frame_position_time(frame, row.start_position, "line start_position"),
        "end_time": _frame_position_time(frame, row.end_position, "line end_position"),
        "start_price": float(row.start_value),
        "end_price": float(row.end_value),
        "slope": float(row.slope),
        "intercept": float(row.intercept),
        "touch_count": row.touch_count,
        "score": float(row.score),
        "replay_point_id": row.replay_point_id,
        "content_id": row.content_id,
        "source_id": row.source_id,
        "checkpoint_id": row.checkpoint_id,
        "boundary_snapshot_id": row.boundary_snapshot_id,
        "boundary_revision_id": row.boundary_revision_id,
    }


def _ray_payload(row: RayEvidenceRow, frame: pd.DataFrame) -> dict[str, Any]:
    start_position = _frame_position_for_timestamp(frame, row.start_time, "ray start_time")
    end_position = _frame_position_for_timestamp(frame, row.end_time, "ray end_time")
    return {
        "evidence_id": row.evidence_id,
        "role": row.role,
        "ordinal": row.ordinal,
        "start_position": start_position,
        "end_position": end_position,
        "start_time": _whole_seconds(row.start_time, "ray start_time"),
        "end_time": _whole_seconds(row.end_time, "ray end_time"),
        "start_price": float(row.start_price),
        "end_price": float(row.end_price),
        "slope": float(row.slope),
        "intercept": float(row.intercept),
        "quality": float(row.quality),
        "touch_count": row.touch_count,
        "r_squared": float(row.r_squared),
        "replay_point_id": row.replay_point_id,
        "content_id": row.content_id,
        "source_id": row.source_id,
        "checkpoint_id": row.checkpoint_id,
        "boundary_snapshot_id": row.boundary_snapshot_id,
        "boundary_revision_id": row.boundary_revision_id,
    }


def _pivot_payload(row: ReplayPivotRow) -> dict[str, Any]:
    return {
        "pivot_role": row.pivot_role,
        "bar_position": row.bar_position,
        "event_at": _whole_seconds(row.event_at, "pivot event_at"),
        "price": float(row.price),
        "extractor": row.extractor,
        "extractor_finality": row.extractor_finality,
        "source_id": row.source_id,
        "checkpoint_id": row.checkpoint_id,
        "boundary_snapshot_id": row.boundary_snapshot_id,
        "boundary_revision_id": row.boundary_revision_id,
        "replay_point_id": row.replay_point_id,
        "content_id": row.content_id,
    }


def _signal_payload(row: SignalEvidenceRow) -> dict[str, Any]:
    return {
        "evidence_id": row.evidence_id,
        "ordinal": row.ordinal,
        "source": row.source,
        "name": row.name,
        "direction": float(row.direction),
        "confidence": float(row.confidence),
        "metadata": dict(row.metadata),
        "replay_point_id": row.replay_point_id,
        "content_id": row.content_id,
        "source_id": row.source_id,
        "checkpoint_id": row.checkpoint_id,
        "signal_snapshot_id": row.signal_snapshot_id,
        "signal_revision_id": row.signal_revision_id,
    }


def _summary_payload(row: SnapshotSummaryRow) -> dict[str, Any]:
    return {
        "timeframe": row.timeframe,
        "position": row.position,
        "event_at": _whole_seconds(row.event_at, "summary event_at"),
        "available_at": _whole_seconds(row.available_at, "summary available_at"),
        "fit_valid": row.fit_valid,
        "finality": row.finality,
        "structure_state": row.structure_state,
        "interaction": row.interaction,
        "market_position_state": row.market_position_state,
        "hull_width_atr": float(row.hull_width_atr),
        "mean_quality": float(row.mean_quality),
        "signal_count": row.signal_count,
        "composite_direction": float(row.composite_direction),
        "composite_confidence": float(row.composite_confidence),
        "replay_point_id": row.replay_point_id,
        "content_id": row.content_id,
    }


def _timeline_payload(row: SnapshotSummaryRow) -> dict[str, Any]:
    payload = _summary_payload(row)
    payload.pop("timeframe")
    return payload


def _payload_without_id(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result.pop("payload_id", None)
    return result


def _validate_identity_fields(payload: Mapping[str, Any]) -> None:
    for field_name in _IDENTITY_FIELDS:
        require_sha256(payload[field_name], field_name)
    for field_name in _OPTIONAL_IDENTITY_FIELDS:
        if payload[field_name] is not None:
            require_sha256(payload[field_name], field_name)


def validate_viewer_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate exact payload shape, finite values, and content identities."""

    if not isinstance(payload, dict):
        raise TrendlineViewerContractError("viewer payload must be a mapping")
    exact_keys(payload, _TOP_LEVEL_KEYS, "viewer payload")
    if payload["schema_version"] != VIEWER_PAYLOAD_SCHEMA_VERSION:
        raise TrendlineViewerContractError("unsupported viewer payload schema")
    if not isinstance(payload["asset"], str) or not payload["asset"].strip():
        raise TrendlineViewerContractError("payload asset must be non-empty")
    if not isinstance(payload["timeframe"], str) or not payload["timeframe"].strip():
        raise TrendlineViewerContractError("payload timeframe must be non-empty")
    for field_name in ("selected_position", "display_start_position", "display_end_position"):
        if isinstance(payload[field_name], bool) or not isinstance(payload[field_name], int):
            raise TrendlineViewerContractError(f"{field_name} must be an integer")
    if payload["selected_position"] < 0:
        raise TrendlineViewerContractError("selected_position must be >= 0")
    if not 0 <= payload["display_start_position"] <= payload["display_end_position"]:
        raise TrendlineViewerContractError("display positions are not ordered")
    if payload["display_end_position"] != payload["selected_position"]:
        raise TrendlineViewerContractError("display window may not contain future positions")
    event_at = integer_seconds(payload["event_at"], "event_at")
    available_at = integer_seconds(payload["available_at"], "available_at")
    if available_at < event_at:
        raise TrendlineViewerContractError("available_at precedes event_at")
    if not isinstance(payload["finality"], str) or not payload["finality"].strip():
        raise TrendlineViewerContractError("finality must be non-empty")
    _validate_identity_fields(payload)

    candles = payload["candles"]
    if not isinstance(candles, list) or not candles:
        raise TrendlineViewerContractError("candles must be a non-empty list")
    expected_time: int | None = None
    for index, candle in enumerate(candles):
        exact_keys(candle, _CANDLE_KEYS, f"candles[{index}]")
        current_time = integer_seconds(candle["time"], f"candles[{index}].time")
        if expected_time is not None and current_time <= expected_time:
            raise TrendlineViewerContractError("candles must be ordered and unique")
        expected_time = current_time
        for field_name in ("open", "high", "low", "close", "volume"):
            finite_number(candle[field_name], f"candles[{index}].{field_name}")

    def validate_point_bound_row(
        row: Mapping[str, Any],
        field_name: str,
        *,
        compare_to_payload: bool = True,
        fields: tuple[str, ...] = (
            "replay_point_id",
            "content_id",
            "source_id",
            "checkpoint_id",
        ),
    ) -> None:
        for identity_field in fields:
            require_sha256(row[identity_field], f"{field_name}.{identity_field}")
            if compare_to_payload and row[identity_field] != payload[identity_field]:
                raise TrendlineViewerContractError(
                    f"{field_name}.{identity_field} differs from selected point"
                )

    pivots = payload["pivots"]
    if not isinstance(pivots, list):
        raise TrendlineViewerContractError("pivots must be a list")
    for index, pivot in enumerate(pivots):
        exact_keys(pivot, _PIVOT_KEYS, f"pivots[{index}]")
        validate_point_bound_row(pivot, f"pivots[{index}]")
        require_sha256(pivot["boundary_snapshot_id"], f"pivots[{index}].boundary_snapshot_id")
        require_sha256(pivot["boundary_revision_id"], f"pivots[{index}].boundary_revision_id")
        integer_seconds(pivot["event_at"], f"pivots[{index}].event_at")
        finite_number(pivot["price"], f"pivots[{index}].price")

    for collection_name, expected_keys in (("lines", _LINE_KEYS), ("rays", _RAY_KEYS)):
        rows = payload[collection_name]
        if not isinstance(rows, list):
            raise TrendlineViewerContractError(f"{collection_name} must be a list")
        for index, row in enumerate(rows):
            exact_keys(row, expected_keys, f"{collection_name}[{index}]")
            validate_point_bound_row(row, f"{collection_name}[{index}]")
            require_sha256(row["evidence_id"], f"{collection_name}[{index}].evidence_id")
            require_sha256(row["boundary_snapshot_id"], f"{collection_name}[{index}].boundary_snapshot_id")
            require_sha256(row["boundary_revision_id"], f"{collection_name}[{index}].boundary_revision_id")
            for position_field in ("start_position", "end_position"):
                position = row[position_field]
                if isinstance(position, bool) or not isinstance(position, int):
                    raise TrendlineViewerContractError(
                        f"{collection_name}[{index}].{position_field} must be an integer"
                    )
            if not 0 <= row["start_position"] < row["end_position"] <= payload["selected_position"]:
                raise TrendlineViewerContractError(
                    f"{collection_name}[{index}] positions are outside selected prefix"
                )
            for time_field in ("start_time", "end_time"):
                integer_seconds(row[time_field], f"{collection_name}[{index}].{time_field}")
            if row["start_time"] > row["end_time"] or row["end_time"] > event_at:
                raise TrendlineViewerContractError(
                    f"{collection_name}[{index}] times are outside selected event"
                )
            for numeric_field in expected_keys - {
                "evidence_id", "role", "ordinal", "method", "start_time", "end_time",
                "replay_point_id", "content_id", "source_id", "checkpoint_id",
                "boundary_snapshot_id", "boundary_revision_id",
            }:
                finite_number(row[numeric_field], f"{collection_name}[{index}].{numeric_field}")

    signals = payload["signals"]
    if not isinstance(signals, list):
        raise TrendlineViewerContractError("signals must be a list")
    for index, row in enumerate(signals):
        exact_keys(row, _SIGNAL_KEYS, f"signals[{index}]")
        validate_point_bound_row(row, f"signals[{index}]")
        require_sha256(row["evidence_id"], f"signals[{index}].evidence_id")
        if row["signal_snapshot_id"] is not None:
            require_sha256(row["signal_snapshot_id"], f"signals[{index}].signal_snapshot_id")
        if row["signal_revision_id"] is not None:
            require_sha256(row["signal_revision_id"], f"signals[{index}].signal_revision_id")
        if not isinstance(row["metadata"], dict):
            raise TrendlineViewerContractError("signal metadata must be a mapping")
        finite_number(row["direction"], f"signals[{index}].direction")
        finite_number(row["confidence"], f"signals[{index}].confidence")

    exact_keys(payload["selected_summary"], _SUMMARY_KEYS, "selected_summary")
    summary = payload["selected_summary"]
    if summary["timeframe"] != payload["timeframe"] or summary["position"] != payload["selected_position"]:
        raise TrendlineViewerContractError("selected summary coordinate differs from payload")
    if summary["event_at"] != event_at or summary["available_at"] != available_at:
        raise TrendlineViewerContractError("selected summary timestamp differs from payload")
    validate_point_bound_row(
        summary,
        "selected_summary",
        fields=("replay_point_id", "content_id"),
    )
    for field_name in ("hull_width_atr", "mean_quality", "composite_direction", "composite_confidence"):
        finite_number(summary[field_name], f"selected_summary.{field_name}")

    timeline = payload["replay_timeline"]
    if not isinstance(timeline, list) or not timeline:
        raise TrendlineViewerContractError("replay_timeline must be a non-empty list")
    for index, row in enumerate(timeline):
        exact_keys(row, _TIMELINE_KEYS, f"replay_timeline[{index}]")
        validate_point_bound_row(
            row,
            f"replay_timeline[{index}]",
            compare_to_payload=False,
            fields=("replay_point_id", "content_id"),
        )
        integer_seconds(row["event_at"], f"replay_timeline[{index}].event_at")
        integer_seconds(row["available_at"], f"replay_timeline[{index}].available_at")
        if row["available_at"] < row["event_at"]:
            raise TrendlineViewerContractError("timeline availability precedes event time")
        for field_name in ("hull_width_atr", "mean_quality", "composite_direction", "composite_confidence"):
            finite_number(row[field_name], f"replay_timeline[{index}].{field_name}")

    expected_window_id = _display_window_id(
        replay_point_id=payload["replay_point_id"],
        content_id=payload["content_id"],
        start_position=payload["display_start_position"],
        end_position=payload["display_end_position"],
        candles=candles,
    )
    if payload["display_window_id"] != expected_window_id:
        raise TrendlineViewerContractError("display_window_id does not match display content")
    require_sha256(payload["display_window_id"], "display_window_id")
    expected_payload_id = canonical_hash(
        _payload_without_id(payload),
        semantics_version=VIEWER_PAYLOAD_SEMANTICS_VERSION,
    )
    if payload["payload_id"] != expected_payload_id:
        raise TrendlineViewerContractError("payload_id does not match payload content")
    require_sha256(payload["payload_id"], "payload_id")
    return dict(payload)


def _selected_row(
    rows: tuple[SnapshotSummaryRow, ...],
    spec: TrendlineViewerSpec,
) -> SnapshotSummaryRow:
    selected = [row for row in rows if row.timeframe == spec.timeframe and row.position == spec.position]
    if len(selected) != 1:
        raise TrendlineViewerContractError("viewer selection must match one snapshot row")
    return selected[0]


def build_trendlines_viewer_payload(
    prepared: Any,
    replay: PreparedTrendlineResearchReplay,
    evidence_bundle: TrendlineResearchEvidenceBundle,
    viewer_spec: TrendlineViewerSpec,
) -> dict[str, Any]:
    """Build one bounded chart payload from validated replay evidence."""

    if not isinstance(viewer_spec, TrendlineViewerSpec):
        raise TypeError("viewer_spec must be a TrendlineViewerSpec")
    if replay.prepared is not prepared:
        raise TrendlineViewerContractError("prepared run does not belong to replay")
    validate_evidence_bundle(evidence_bundle)
    if evidence_bundle.preparation_id != prepared.preparation_id:
        raise TrendlineViewerContractError("evidence preparation identity differs")
    if evidence_bundle.dataset_id != prepared.dataset.dataset_id:
        raise TrendlineViewerContractError("evidence dataset identity differs")
    if evidence_bundle.research_configuration_id != prepared.configuration.research_configuration_id:
        raise TrendlineViewerContractError("evidence configuration identity differs")
    if evidence_bundle.replay_id != replay.replay_id:
        raise TrendlineViewerContractError("evidence replay identity differs")
    if evidence_bundle.selection.timeframe != viewer_spec.timeframe or evidence_bundle.selection.position != viewer_spec.position:
        raise TrendlineViewerContractError("viewer selection differs from evidence selection")
    point = replay.output_at(viewer_spec.timeframe, viewer_spec.position)
    validate_replay_point_integrity(point)
    rows = evidence_bundle.snapshot_rows
    selected_row = _selected_row(rows, viewer_spec)
    identity = _point_identity(point)
    for field_name, expected in identity.items():
        if getattr(selected_row, field_name, None) != expected:
            raise TrendlineViewerContractError(f"selected snapshot row differs: {field_name}")

    frame = prepared.dataset.frames[viewer_spec.timeframe]
    if viewer_spec.position >= len(frame):
        raise TrendlineViewerContractError("viewer position exceeds prepared data")
    display_start = max(0, viewer_spec.position - viewer_spec.display_lookback_bars + 1)
    display_end = viewer_spec.position
    candles = _candle_payloads(frame, display_start, display_end)
    line_rows = tuple(
        row
        for row in evidence_bundle.line_rows
        if (row.timeframe, row.position) == (viewer_spec.timeframe, viewer_spec.position)
    )
    ray_rows = tuple(
        row
        for row in evidence_bundle.ray_rows
        if (row.timeframe, row.position) == (viewer_spec.timeframe, viewer_spec.position)
    )
    signal_rows = tuple(
        row
        for row in evidence_bundle.signal_rows
        if (row.timeframe, row.position) == (viewer_spec.timeframe, viewer_spec.position)
    )
    pivots = tuple(row for row in evidence_bundle.selected_pivots if (row.timeframe, row.position) == (viewer_spec.timeframe, viewer_spec.position))
    payload: dict[str, Any] = {
        "schema_version": VIEWER_PAYLOAD_SCHEMA_VERSION,
        "payload_id": "pending",
        "asset": prepared.spec.asset,
        "timeframe": viewer_spec.timeframe,
        "selected_position": viewer_spec.position,
        "event_at": _whole_seconds(point.event_at, "event_at"),
        "available_at": _whole_seconds(point.available_at, "available_at"),
        "finality": selected_row.finality,
        "dataset_id": prepared.dataset.dataset_id,
        "research_configuration_id": prepared.configuration.research_configuration_id,
        "replay_id": replay.replay_id,
        "evidence_bundle_id": evidence_bundle.bundle_id,
        **identity,
        "display_start_position": display_start,
        "display_end_position": display_end,
        "display_window_id": _display_window_id(
            replay_point_id=point.replay_point_id,
            content_id=point.content_id,
            start_position=display_start,
            end_position=display_end,
            candles=candles,
        ),
        "candles": candles,
        "pivots": [_pivot_payload(row) for row in pivots],
        "lines": [_line_payload(row, frame) for row in line_rows],
        "rays": [_ray_payload(row, frame) for row in ray_rows],
        "signals": [_signal_payload(row) for row in signal_rows],
        "selected_summary": _summary_payload(selected_row),
        "replay_timeline": [
            _timeline_payload(row)
            for row in rows
            if row.timeframe == viewer_spec.timeframe
        ],
    }
    payload["payload_id"] = canonical_hash(
        _payload_without_id(payload),
        semantics_version=VIEWER_PAYLOAD_SEMANTICS_VERSION,
    )
    return validate_viewer_payload(payload)


__all__ = [
    "build_trendlines_viewer_payload",
    "validate_viewer_payload",
]
