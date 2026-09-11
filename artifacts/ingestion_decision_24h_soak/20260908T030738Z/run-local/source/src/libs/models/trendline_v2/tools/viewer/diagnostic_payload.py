"""Strict R4/R5 diagnostic payload and two-file bundle contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Mapping

from libs.models.trendline_v2.domain.identity import deterministic_hash


DIAGNOSTIC_PAYLOAD_SCHEMA_VERSION = "trendline_v2_r5_diagnostic_viewer_payload_v1"
DIAGNOSTIC_BUNDLE_SCHEMA_VERSION = "trendline_v2_r5_diagnostic_viewer_bundle_v1"
DIAGNOSTIC_BUNDLE_MEMBER_NAME = "chart_payload.json"
DIAGNOSTIC_RAW_CANDLE_PATH = "datasets/btcusdt_4h/provider_result.json"
DIAGNOSTIC_RAW_CANDLE_SHA256 = (
    "0fb88993e8ceed7b3812ec8fed895164b4fd00d1d392f5018f81aeea66dd4fe3"
)
R4_DIAGNOSTIC_ID = (
    "f4a95e118d52eec9ae60b447f08ca11a756908d7861772978b8f0393b0bbd2e2"
)
R4_MANIFEST_ID = (
    "965b4741ec0f7305b8217dbc90d5c2bb31a6185e09b42c519bc404548c290a7e"
)
R4_INVENTORY = (
    "7fbd19fd1b828c09881df6236d2c3b8bdf7ae4bdfd4cd4b03d770c401ecd413c"
)
R5_ATTRIBUTION_ID = (
    "b918a2102f82670da9fbd365daa9b35d7ec86d5bfb043db149b412f57b25f083"
)
R5_MANIFEST_ID = (
    "f5569cca5cafe8f4b598a8e4a9e1609fcefc70f89cc90078d21c8f5c0dabc917"
)
R5_INVENTORY = (
    "7fcde0786d367adb0dafbe9fe54349005e69d6cc33f14407477bee534a38d31e"
)
CHECKPOINT_INDEX = 5
CHECKPOINT_OBSERVED_AT = "2026-06-09T00:00:00Z"
ASSET = "BTCUSDT"
TIMEFRAME = "4h"
ROLE = "support"
BUDGET = 1
CONTENDER_POLICY = "joint_incumbent_near_v1"
CONTROL_POLICY = "joint_nearest_projection_control_v1"
CONTENDER_LINEAGE = (
    "2a7613b64b8d70a79171f8599d0a2d744164d6da8d9e05551a7c1d120041d385"
)
CONTROL_LINEAGE = (
    "a268b19fed5c2624f25612c5e9975c35b6177215872609e47f25781a309dea95"
)
TARGET_CELL_IDENTITY = [
    CONTENDER_POLICY,
    BUDGET,
    CONTROL_POLICY,
    "btcusdt_4h",
    CHECKPOINT_INDEX,
    ROLE,
    96,
]
TARGET_ATTRIBUTION_CLASS = "FULL_LINEAGE_SUBSTITUTION"
TARGET_CROSS_BUDGET_CLASS = "PERSISTENT_THROUGH_BUDGET_3"
TARGET_DIRECTION = "control_only"
_HORIZON = timedelta(hours=96)
_CANDLE_INTERVAL_SECONDS = 14_400
_MAX_CAUSAL_CANDLES = 160
_PAYLOAD_KEYS = {
    "schema_version",
    "payload_id",
    "asset",
    "timeframe",
    "checkpoint_index",
    "checkpoint_observed_at",
    "as_of",
    "candles",
    "lines",
    "r4_diagnostic_id",
    "r4_manifest_id",
    "r4_inventory",
    "r5_attribution_id",
    "r5_manifest_id",
    "r5_inventory",
    "raw_candle_path",
    "raw_candle_sha256",
    "cell_attribution",
}
_LINE_KEYS = {
    "lineage_id",
    "selection_id",
    "side",
    "role",
    "policy_id",
    "control_policy_id_or_null",
    "fixed_geometry",
    "anchors",
    "projection_time",
    "projection_price",
    "initial_distance_atr",
    "geometry_projected_distance_atr_96h",
    "reachable_at_96h",
    "attribution_class",
    "cross_budget_class",
}
_GEOMETRY_KEYS = {"start_time", "end_time", "start_price", "end_price"}
_ANCHOR_KEYS = {"time", "price"}
_CANDLE_KEYS = {"time", "open", "high", "low", "close", "volume"}
_CELL_KEYS = {
    "cell_identity",
    "one_sided_direction",
    "attribution_class",
    "cross_budget_class",
}


class DiagnosticViewerError(ValueError):
    """Expected diagnostic payload, source, or publication failure."""


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DiagnosticViewerError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise DiagnosticViewerError(f"{field_name} must be finite")
    return result


def _iso_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise DiagnosticViewerError(f"{field_name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DiagnosticViewerError(f"{field_name} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DiagnosticViewerError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _epoch_seconds(value: object, field_name: str) -> int:
    parsed = _iso_datetime(value, field_name)
    timestamp = parsed.timestamp()
    if not timestamp.is_integer():
        raise DiagnosticViewerError(f"{field_name} must be whole-second aligned")
    return int(timestamp)


def _require_hash(value: object, field_name: str) -> str:
    if not _is_sha256(value):
        raise DiagnosticViewerError(f"{field_name} must be lowercase SHA-256")
    return value


def _payload_identity(payload: Mapping[str, object]) -> dict[str, object]:
    semantic = dict(payload)
    semantic.pop("payload_id", None)
    return semantic


def _bundle_identity(manifest: Mapping[str, object]) -> str:
    return deterministic_hash(DIAGNOSTIC_BUNDLE_SCHEMA_VERSION, dict(manifest))


def _decimal(value: object, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DiagnosticViewerError(f"{field_name} is not decimal") from exc
    if not result.is_finite():
        raise DiagnosticViewerError(f"{field_name} must be finite")
    return result


def _project_price(geometry: Mapping[str, object], projection_time: int) -> float:
    start_time = _epoch_seconds(geometry["start_time"], "geometry.start_time")
    end_time = _epoch_seconds(geometry["end_time"], "geometry.end_time")
    if end_time <= start_time:
        raise DiagnosticViewerError("geometry timestamps must be ordered")
    start_price = _decimal(geometry["start_price"], "geometry.start_price")
    end_price = _decimal(geometry["end_price"], "geometry.end_price")
    projected = start_price + (end_price - start_price) * Decimal(
        projection_time - start_time
    ) / Decimal(end_time - start_time)
    return float(projected)


def _require_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DiagnosticViewerError(f"{field_name} must be an object")
    return value


def _target_row(
    r4_diagnostic: Mapping[str, object],
    *,
    side: str,
    lineage_id: str,
) -> Mapping[str, object]:
    rows = r4_diagnostic.get("feature_rows")
    if not isinstance(rows, list):
        raise DiagnosticViewerError("R4 feature_rows are missing")
    expected_namespace = (
        [CONTENDER_POLICY, BUDGET, "contender", None, "btcusdt_4h"]
        if side == "contender"
        else [CONTENDER_POLICY, BUDGET, "matched_control", CONTROL_POLICY, "btcusdt_4h"]
    )
    matches = [
        row
        for row in rows
        if isinstance(row, Mapping)
        and row.get("dataset_id") == "btcusdt_4h"
        and row.get("checkpoint_index") == CHECKPOINT_INDEX
        and row.get("budget_per_role") == BUDGET
        and row.get("semantic_role_at_selection") == ROLE
        and row.get("lineage_id") == lineage_id
        and row.get("population_namespace") == expected_namespace
    ]
    if len(matches) != 1:
        raise DiagnosticViewerError(
            f"expected one R4 {side} feature row, found {len(matches)}"
        )
    return matches[0]


def _target_cell(r5_attribution: Mapping[str, object]) -> Mapping[str, object]:
    cells = r5_attribution.get("cells")
    if not isinstance(cells, list):
        raise DiagnosticViewerError("R5 cells are missing")
    matches = [
        cell
        for cell in cells
        if isinstance(cell, Mapping) and cell.get("cell_identity") == TARGET_CELL_IDENTITY
    ]
    if len(matches) != 1:
        raise DiagnosticViewerError(f"expected one R5 target cell, found {len(matches)}")
    cell = matches[0]
    if (
        cell.get("one_sided_direction") != TARGET_DIRECTION
        or cell.get("attribution_class") != TARGET_ATTRIBUTION_CLASS
        or cell.get("cross_budget_class") != TARGET_CROSS_BUDGET_CLASS
    ):
        raise DiagnosticViewerError("R5 target cell labels do not match frozen evidence")
    return cell


def _raw_input(raw_payload: Mapping[str, object]) -> Mapping[str, object]:
    provider_result = _require_mapping(raw_payload.get("provider_result"), "provider_result")
    request = _require_mapping(provider_result.get("request"), "provider_result.request")
    return _require_mapping(request.get("input_data"), "provider_result.request.input_data")


def _causal_candles(raw_input: Mapping[str, object]) -> list[dict[str, object]]:
    names = ("timestamps", "open", "high", "low", "close", "volume")
    arrays = [raw_input.get(name) for name in names]
    if any(not isinstance(values, list) for values in arrays):
        raise DiagnosticViewerError("raw provider input arrays are invalid")
    timestamps, opens, highs, lows, closes, volumes = arrays
    if not timestamps:
        raise DiagnosticViewerError("raw provider input is empty")
    if len({len(values) for values in arrays}) != 1:
        raise DiagnosticViewerError("raw provider input arrays have different lengths")
    checkpoint = _epoch_seconds(CHECKPOINT_OBSERVED_AT, "checkpoint_observed_at")
    candles: list[dict[str, object]] = []
    for index, timestamp_ns in enumerate(timestamps):
        if type(timestamp_ns) is not int or timestamp_ns % 1_000_000_000:
            raise DiagnosticViewerError("raw candle timestamp is not whole-second aligned")
        timestamp = timestamp_ns // 1_000_000_000
        if timestamp >= checkpoint:
            continue
        values = {
            "time": timestamp,
            "open": _finite(opens[index], f"candle {index}.open"),
            "high": _finite(highs[index], f"candle {index}.high"),
            "low": _finite(lows[index], f"candle {index}.low"),
            "close": _finite(closes[index], f"candle {index}.close"),
            "volume": _finite(volumes[index], f"candle {index}.volume"),
        }
        if (
            values["high"] < values["low"]
            or values["high"] < values["open"]
            or values["high"] < values["close"]
            or values["low"] > values["open"]
            or values["low"] > values["close"]
            or values["volume"] < 0
        ):
            raise DiagnosticViewerError(f"candle {index} violates OHLCV bounds")
        candles.append(values)
    candles = candles[-_MAX_CAUSAL_CANDLES:]
    if not candles:
        raise DiagnosticViewerError("no causal candles precede checkpoint")
    for previous, current in zip(candles, candles[1:]):
        if current["time"] - previous["time"] != _CANDLE_INTERVAL_SECONDS:
            raise DiagnosticViewerError("causal candle timestamps are not contiguous")
    return candles


def _line_payload(
    row: Mapping[str, object],
    *,
    side: str,
    cell: Mapping[str, object],
) -> dict[str, object]:
    geometry = dict(_require_mapping(row.get("fixed_geometry"), "fixed_geometry"))
    if set(geometry) != _GEOMETRY_KEYS:
        raise DiagnosticViewerError("R4 fixed geometry keys are invalid")
    projection_time = _epoch_seconds(CHECKPOINT_OBSERVED_AT, "checkpoint_observed_at") + int(
        _HORIZON.total_seconds()
    )
    projection_price = _project_price(geometry, projection_time)
    expected_lineage = CONTENDER_LINEAGE if side == "contender" else CONTROL_LINEAGE
    if row.get("lineage_id") != expected_lineage:
        raise DiagnosticViewerError(f"R4 {side} lineage mismatch")
    selection_id = _require_hash(row.get("selection_id"), f"{side}.selection_id")
    lineage_id = _require_hash(row.get("lineage_id"), f"{side}.lineage_id")
    if row.get("semantic_role_at_selection") != ROLE:
        raise DiagnosticViewerError(f"R4 {side} role mismatch")
    start_time = _epoch_seconds(geometry["start_time"], f"{side}.geometry.start_time")
    end_time = _epoch_seconds(geometry["end_time"], f"{side}.geometry.end_time")
    if end_time >= projection_time:
        raise DiagnosticViewerError(f"R4 {side} geometry reaches projection boundary")
    return {
        "lineage_id": lineage_id,
        "selection_id": selection_id,
        "side": side,
        "role": ROLE,
        "policy_id": row.get("contender_policy_id"),
        "control_policy_id_or_null": row.get("control_policy_id_or_null"),
        "fixed_geometry": geometry,
        "anchors": [
            {"time": start_time, "price": _finite(geometry["start_price"], f"{side}.start_price")},
            {"time": end_time, "price": _finite(geometry["end_price"], f"{side}.end_price")},
        ],
        "projection_time": projection_time,
        "projection_price": projection_price,
        "initial_distance_atr": _finite(row.get("initial_distance_atr"), f"{side}.initial_distance_atr"),
        "geometry_projected_distance_atr_96h": _finite(
            row.get("geometry_projected_distance_atr_96h"),
            f"{side}.geometry_projected_distance_atr_96h",
        ),
        "reachable_at_96h": (
            [
                "btcusdt_4h",
                CHECKPOINT_INDEX,
                ROLE,
                lineage_id,
            ]
            in cell.get("contender_reachable", [])
            if side == "contender"
            else [
                "btcusdt_4h",
                CHECKPOINT_INDEX,
                ROLE,
                lineage_id,
            ]
            in cell.get("control_reachable", [])
        ),
        "attribution_class": cell["attribution_class"],
        "cross_budget_class": cell["cross_budget_class"],
    }


def build_diagnostic_payload(
    r4_diagnostic: Mapping[str, object],
    r5_attribution: Mapping[str, object],
    raw_payload: Mapping[str, object],
    *,
    raw_bytes: bytes,
) -> dict[str, object]:
    """Derive exactly two source-backed lines without consuming outcomes."""

    if r4_diagnostic.get("diagnostic_id") != R4_DIAGNOSTIC_ID:
        raise DiagnosticViewerError("R4 diagnostic identity mismatch")
    if r5_attribution.get("attribution_id") != R5_ATTRIBUTION_ID:
        raise DiagnosticViewerError("R5 attribution identity mismatch")
    cell = _target_cell(r5_attribution)
    raw_input = _raw_input(raw_payload)
    if raw_input.get("asset") != ASSET or raw_input.get("timeframe") != TIMEFRAME:
        raise DiagnosticViewerError("raw candle asset/timeframe mismatch")
    candles = _causal_candles(raw_input)
    lines = [
        _line_payload(
            _target_row(r4_diagnostic, side="contender", lineage_id=CONTENDER_LINEAGE),
            side="contender",
            cell=cell,
        ),
        _line_payload(
            _target_row(r4_diagnostic, side="control", lineage_id=CONTROL_LINEAGE),
            side="control",
            cell=cell,
        ),
    ]
    payload_without_id: dict[str, object] = {
        "schema_version": DIAGNOSTIC_PAYLOAD_SCHEMA_VERSION,
        "asset": ASSET,
        "timeframe": TIMEFRAME,
        "checkpoint_index": CHECKPOINT_INDEX,
        "checkpoint_observed_at": CHECKPOINT_OBSERVED_AT,
        "as_of": CHECKPOINT_OBSERVED_AT,
        "candles": candles,
        "lines": lines,
        "r4_diagnostic_id": R4_DIAGNOSTIC_ID,
        "r4_manifest_id": R4_MANIFEST_ID,
        "r4_inventory": R4_INVENTORY,
        "r5_attribution_id": R5_ATTRIBUTION_ID,
        "r5_manifest_id": R5_MANIFEST_ID,
        "r5_inventory": R5_INVENTORY,
        "raw_candle_path": DIAGNOSTIC_RAW_CANDLE_PATH,
        "raw_candle_sha256": _sha256(raw_bytes),
        "cell_attribution": {
            "cell_identity": list(cell["cell_identity"]),
            "one_sided_direction": cell["one_sided_direction"],
            "attribution_class": cell["attribution_class"],
            "cross_budget_class": cell["cross_budget_class"],
        },
    }
    return validate_diagnostic_payload(
        {
            **payload_without_id,
            "payload_id": deterministic_hash(
                DIAGNOSTIC_PAYLOAD_SCHEMA_VERSION,
                payload_without_id,
            ),
        }
    )


def validate_diagnostic_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Fail closed on diagnostic identity, geometry, source and causal invariants."""

    if not isinstance(payload, Mapping) or set(payload) != _PAYLOAD_KEYS:
        raise DiagnosticViewerError("diagnostic payload keys mismatch")
    if payload["schema_version"] != DIAGNOSTIC_PAYLOAD_SCHEMA_VERSION:
        raise DiagnosticViewerError("unsupported diagnostic payload schema")
    _require_hash(payload["payload_id"], "payload_id")
    for name, expected in (
        ("r4_diagnostic_id", R4_DIAGNOSTIC_ID),
        ("r4_manifest_id", R4_MANIFEST_ID),
        ("r4_inventory", R4_INVENTORY),
        ("r5_attribution_id", R5_ATTRIBUTION_ID),
        ("r5_manifest_id", R5_MANIFEST_ID),
        ("r5_inventory", R5_INVENTORY),
        ("raw_candle_sha256", DIAGNOSTIC_RAW_CANDLE_SHA256),
    ):
        if payload[name] != expected:
            raise DiagnosticViewerError(f"{name} does not match frozen source")
    if payload["asset"] != ASSET or payload["timeframe"] != TIMEFRAME:
        raise DiagnosticViewerError("diagnostic market identity mismatch")
    if payload["checkpoint_index"] != CHECKPOINT_INDEX:
        raise DiagnosticViewerError("diagnostic checkpoint mismatch")
    checkpoint = _epoch_seconds(payload["checkpoint_observed_at"], "checkpoint_observed_at")
    if payload["as_of"] != payload["checkpoint_observed_at"]:
        raise DiagnosticViewerError("diagnostic as_of is not checkpoint-bound")
    candles = payload["candles"]
    if not isinstance(candles, list) or not candles:
        raise DiagnosticViewerError("diagnostic candles must be non-empty")
    previous_time: int | None = None
    for index, candle in enumerate(candles):
        if not isinstance(candle, Mapping) or set(candle) != _CANDLE_KEYS:
            raise DiagnosticViewerError(f"diagnostic candle {index} keys mismatch")
        timestamp = candle["time"]
        if type(timestamp) is not int or timestamp >= checkpoint:
            raise DiagnosticViewerError("diagnostic candles include post-checkpoint data")
        if previous_time is not None and timestamp - previous_time != _CANDLE_INTERVAL_SECONDS:
            raise DiagnosticViewerError("diagnostic candle timestamps are not contiguous")
        previous_time = timestamp
        values = {name: _finite(candle[name], f"candle {index}.{name}") for name in ("open", "high", "low", "close", "volume")}
        if values["high"] < values["low"] or values["high"] < values["open"] or values["high"] < values["close"] or values["low"] > values["open"] or values["low"] > values["close"] or values["volume"] < 0:
            raise DiagnosticViewerError(f"diagnostic candle {index} violates OHLCV bounds")
    cell = payload["cell_attribution"]
    if not isinstance(cell, Mapping) or set(cell) != _CELL_KEYS:
        raise DiagnosticViewerError("diagnostic cell attribution keys mismatch")
    if cell["cell_identity"] != TARGET_CELL_IDENTITY or cell["one_sided_direction"] != TARGET_DIRECTION or cell["attribution_class"] != TARGET_ATTRIBUTION_CLASS or cell["cross_budget_class"] != TARGET_CROSS_BUDGET_CLASS:
        raise DiagnosticViewerError("diagnostic cell attribution does not match frozen R5")
    lines = payload["lines"]
    if not isinstance(lines, list) or len(lines) != 2:
        raise DiagnosticViewerError("diagnostic payload requires exactly two lines")
    sides: set[str] = set()
    for index, line in enumerate(lines):
        if not isinstance(line, Mapping) or set(line) != _LINE_KEYS:
            raise DiagnosticViewerError(f"diagnostic line {index} keys mismatch")
        side = line["side"]
        if side not in {"contender", "control"} or side in sides:
            raise DiagnosticViewerError("diagnostic line sides must be unique contender/control")
        sides.add(side)
        expected_lineage = CONTENDER_LINEAGE if side == "contender" else CONTROL_LINEAGE
        if line["lineage_id"] != expected_lineage:
            raise DiagnosticViewerError("diagnostic line lineage does not match side")
        expected_control_policy = None if side == "contender" else CONTROL_POLICY
        if line["policy_id"] != CONTENDER_POLICY or line["control_policy_id_or_null"] != expected_control_policy:
            raise DiagnosticViewerError("diagnostic line policy does not match side")
        if line["role"] != ROLE or line["attribution_class"] != cell["attribution_class"] or line["cross_budget_class"] != cell["cross_budget_class"]:
            raise DiagnosticViewerError("diagnostic line labels do not match cell")
        _require_hash(line["lineage_id"], f"line {index}.lineage_id")
        _require_hash(line["selection_id"], f"line {index}.selection_id")
        if not isinstance(line["policy_id"], str) or not line["policy_id"]:
            raise DiagnosticViewerError("diagnostic line policy is invalid")
        if line["control_policy_id_or_null"] is not None and (not isinstance(line["control_policy_id_or_null"], str) or not line["control_policy_id_or_null"]):
            raise DiagnosticViewerError("diagnostic line control policy is invalid")
        geometry = line["fixed_geometry"]
        if not isinstance(geometry, Mapping) or set(geometry) != _GEOMETRY_KEYS:
            raise DiagnosticViewerError("diagnostic fixed geometry keys mismatch")
        start = _epoch_seconds(geometry["start_time"], f"line {index}.start_time")
        end = _epoch_seconds(geometry["end_time"], f"line {index}.end_time")
        projection_time = line["projection_time"]
        if type(projection_time) is not int or projection_time != checkpoint + int(_HORIZON.total_seconds()) or projection_time <= end:
            raise DiagnosticViewerError("diagnostic projection time is invalid")
        expected_price = _project_price(geometry, projection_time)
        if abs(_finite(line["projection_price"], f"line {index}.projection_price") - expected_price) > 1e-9:
            raise DiagnosticViewerError("diagnostic projection price does not match geometry")
        anchors = line["anchors"]
        if not isinstance(anchors, list) or len(anchors) != 2 or any(not isinstance(anchor, Mapping) or set(anchor) != _ANCHOR_KEYS for anchor in anchors):
            raise DiagnosticViewerError("diagnostic anchors are invalid")
        if anchors != [
            {"time": start, "price": _finite(geometry["start_price"], "start_price")},
            {"time": end, "price": _finite(geometry["end_price"], "end_price")},
        ]:
            raise DiagnosticViewerError("diagnostic anchors do not match fixed geometry")
        _finite(line["initial_distance_atr"], f"line {index}.initial_distance_atr")
        _finite(line["geometry_projected_distance_atr_96h"], f"line {index}.geometry_projected_distance_atr_96h")
        if not isinstance(line["reachable_at_96h"], bool):
            raise DiagnosticViewerError("diagnostic reachability flag is invalid")
    if sides != {"contender", "control"}:
        raise DiagnosticViewerError("diagnostic payload must contain contender and control")
    expected_id = deterministic_hash(
        DIAGNOSTIC_PAYLOAD_SCHEMA_VERSION,
        _payload_identity(payload),
    )
    if payload["payload_id"] != expected_id:
        raise DiagnosticViewerError("diagnostic payload identity mismatch")
    return dict(payload)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DiagnosticViewerError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_canonical_json(path: Path) -> tuple[dict[str, object], bytes]:
    try:
        data = path.read_bytes()
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                DiagnosticViewerError(f"non-finite JSON constant: {value}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, DiagnosticViewerError) as exc:
        raise DiagnosticViewerError(f"invalid JSON file: {path}") from exc
    if not isinstance(value, dict) or data != _canonical_json_bytes(value):
        raise DiagnosticViewerError(f"JSON file is not canonical: {path}")
    return value, data


def validate_diagnostic_bundle(bundle_path: str | Path) -> dict[str, object]:
    """Validate exact two-file diagnostic bundle without source rederivation."""

    bundle = Path(bundle_path)
    if bundle.is_symlink() or not bundle.is_dir():
        raise DiagnosticViewerError("diagnostic bundle must be a real directory")
    if {item.name for item in bundle.iterdir()} != {"manifest.json", DIAGNOSTIC_BUNDLE_MEMBER_NAME}:
        raise DiagnosticViewerError("diagnostic bundle members are not exact")
    manifest, manifest_bytes = _load_canonical_json(bundle / "manifest.json")
    payload, payload_bytes = _load_canonical_json(bundle / DIAGNOSTIC_BUNDLE_MEMBER_NAME)
    if set(manifest) != {"schema_version", "bundle_id", "payload_id", "members"}:
        raise DiagnosticViewerError("diagnostic manifest keys mismatch")
    if manifest["schema_version"] != DIAGNOSTIC_BUNDLE_SCHEMA_VERSION:
        raise DiagnosticViewerError("unsupported diagnostic bundle schema")
    _require_hash(manifest["bundle_id"], "bundle_id")
    _require_hash(manifest["payload_id"], "manifest.payload_id")
    members = manifest["members"]
    expected_member = {
        "name": DIAGNOSTIC_BUNDLE_MEMBER_NAME,
        "sha256": _sha256(payload_bytes),
        "byte_length": len(payload_bytes),
    }
    if members != [expected_member]:
        raise DiagnosticViewerError("diagnostic manifest member mismatch")
    validate_diagnostic_payload(payload)
    if manifest["payload_id"] != payload["payload_id"]:
        raise DiagnosticViewerError("diagnostic manifest payload identity mismatch")
    semantic_manifest = {
        "schema_version": manifest["schema_version"],
        "payload_id": manifest["payload_id"],
        "members": members,
    }
    if manifest["bundle_id"] != _bundle_identity(semantic_manifest):
        raise DiagnosticViewerError("diagnostic bundle identity mismatch")
    return dict(manifest)


def write_diagnostic_bundle(
    payload: Mapping[str, object],
    output_directory: str | Path,
) -> Path:
    """Atomically write exactly manifest.json and chart_payload.json."""

    validated = validate_diagnostic_payload(payload)
    output = Path(output_directory)
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise DiagnosticViewerError("diagnostic output must be a real directory")
    if output.exists() and any(output.iterdir()):
        raise DiagnosticViewerError("diagnostic output must be absent or empty")
    output.parent.mkdir(parents=True, exist_ok=True)
    payload_bytes = _canonical_json_bytes(validated)
    member = {
        "name": DIAGNOSTIC_BUNDLE_MEMBER_NAME,
        "sha256": _sha256(payload_bytes),
        "byte_length": len(payload_bytes),
    }
    manifest_semantics = {
        "schema_version": DIAGNOSTIC_BUNDLE_SCHEMA_VERSION,
        "payload_id": validated["payload_id"],
        "members": [member],
    }
    manifest = {
        **manifest_semantics,
        "bundle_id": _bundle_identity(manifest_semantics),
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        for name, data in (
            (DIAGNOSTIC_BUNDLE_MEMBER_NAME, payload_bytes),
            ("manifest.json", manifest_bytes),
        ):
            temporary = staging / f".{name}.tmp"
            with temporary.open("wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, staging / name)
        if output.exists():
            output.rmdir()
        os.replace(staging, output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return output


__all__ = [
    "ASSET",
    "CHECKPOINT_INDEX",
    "CHECKPOINT_OBSERVED_AT",
    "CONTROL_LINEAGE",
    "CONTROL_POLICY",
    "DIAGNOSTIC_BUNDLE_SCHEMA_VERSION",
    "DIAGNOSTIC_PAYLOAD_SCHEMA_VERSION",
    "DIAGNOSTIC_RAW_CANDLE_PATH",
    "DIAGNOSTIC_RAW_CANDLE_SHA256",
    "DiagnosticViewerError",
    "R4_DIAGNOSTIC_ID",
    "R4_INVENTORY",
    "R4_MANIFEST_ID",
    "R5_ATTRIBUTION_ID",
    "R5_INVENTORY",
    "R5_MANIFEST_ID",
    "TARGET_ATTRIBUTION_CLASS",
    "TARGET_CELL_IDENTITY",
    "TARGET_CROSS_BUDGET_CLASS",
    "build_diagnostic_payload",
    "validate_diagnostic_bundle",
    "validate_diagnostic_payload",
    "write_diagnostic_bundle",
    "_canonical_json_bytes",
    "_sha256",
]
