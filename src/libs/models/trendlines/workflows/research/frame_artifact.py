"""Strict, byte-preserving persistence for prepared research frames."""

from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from libs.models.trendlines.contracts.identity import (
    canonical_hash,
    resolve_source_ref,
)
from libs.models.trendlines.signals.context import (
    BarAvailabilitySource,
    BarTimestampSemantics,
)
from libs.models.trendlines.workflows.research.contracts import (
    TrendlineResearchDataMode,
    TrendlineResearchDataSpec,
    build_research_availability_id,
)


FRAME_ARTIFACT_SCHEMA_VERSION = "trendlines.research-frame-artifact.v1"
FRAME_ARTIFACT_SEMANTICS_VERSION = "trendlines.research-frame-artifact-id.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DATETIME_UNITS = frozenset({"s", "ms", "us", "ns"})
_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "semantics_version",
        "asset",
        "timeframe",
        "data_spec",
        "index",
        "column_order",
        "columns",
        "availability",
        "attributes",
        "source_id",
        "availability_id",
        "dataset_id",
        "artifact_id",
    }
)


class TrendlineFrameArtifactError(ValueError):
    """Raised when a research-frame artifact is incomplete or tampered."""


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise TrendlineFrameArtifactError(f"{field} must be a lowercase SHA-256 identity")
    return value


def _exact_keys(value: Any, expected: set[str] | frozenset[str], field: str) -> None:
    if not isinstance(value, dict):
        raise TrendlineFrameArtifactError(f"{field} must be an object")
    actual = set(value)
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        extra = sorted(actual - set(expected))
        raise TrendlineFrameArtifactError(
            f"{field} keys mismatch; missing={missing}, extra={extra}"
        )


def _canonical_json_bytes(value: dict[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise TrendlineFrameArtifactError("artifact contains non-canonical JSON data") from exc
    return (encoded + "\n").encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {value}")


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise TrendlineFrameArtifactError("frame artifact must be a regular file")
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise TrendlineFrameArtifactError("invalid frame artifact JSON") from exc
    if not isinstance(value, dict):
        raise TrendlineFrameArtifactError("frame artifact must contain an object")
    if raw != _canonical_json_bytes(value):
        raise TrendlineFrameArtifactError("frame artifact is not canonical JSON")
    return value, raw


def _utc_datetime(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise TrendlineFrameArtifactError(f"{field} must be an ISO datetime string")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TrendlineFrameArtifactError(f"{field} must be an ISO datetime string") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise TrendlineFrameArtifactError(f"{field} must be timezone-aware")
    return result


def _data_spec_from_dict(value: Any) -> TrendlineResearchDataSpec:
    if not isinstance(value, dict) or "mode" not in value:
        raise TrendlineFrameArtifactError("data_spec must contain mode")
    try:
        mode = TrendlineResearchDataMode(str(value["mode"]).strip().lower())
    except (TypeError, ValueError) as exc:
        raise TrendlineFrameArtifactError("data_spec mode is invalid") from exc

    if mode is TrendlineResearchDataMode.SYNTHETIC:
        _exact_keys(value, {"mode", "seed", "start_time", "bar_counts"}, "data_spec")
        if not isinstance(value["bar_counts"], dict):
            raise TrendlineFrameArtifactError("data_spec.bar_counts must be an object")
        return TrendlineResearchDataSpec(
            mode=mode,
            seed=value["seed"],
            start_time=_utc_datetime(value["start_time"], field="data_spec.start_time"),
            bar_counts=value["bar_counts"],
        )
    if mode is TrendlineResearchDataMode.BINANCE:
        _exact_keys(value, {"mode", "event_start", "knowledge_cutoff"}, "data_spec")
        return TrendlineResearchDataSpec(
            mode=mode,
            event_start=_utc_datetime(value["event_start"], field="data_spec.event_start"),
            knowledge_cutoff=_utc_datetime(
                value["knowledge_cutoff"],
                field="data_spec.knowledge_cutoff",
            ),
        )
    _exact_keys(value, {"mode"}, "data_spec")
    return TrendlineResearchDataSpec(mode=mode)


def _datetime_metadata(index: pd.DatetimeIndex, *, field: str) -> dict[str, Any]:
    if not isinstance(index, pd.DatetimeIndex):
        raise TrendlineFrameArtifactError(f"{field} must be a DatetimeIndex")
    if index.tz is None:
        raise TrendlineFrameArtifactError(f"{field} must be timezone-aware")
    name = index.name
    if not isinstance(name, str) or not name.strip():
        raise TrendlineFrameArtifactError(f"{field}.name is required")
    unit = getattr(index, "unit", None)
    if unit not in _DATETIME_UNITS:
        raise TrendlineFrameArtifactError(f"{field}.unit is unsupported or missing")
    if len(index) == 0 or not index.is_monotonic_increasing or not index.is_unique:
        raise TrendlineFrameArtifactError(f"{field} must be non-empty, ordered and unique")
    return {
        "name": name,
        "timezone": str(index.tz),
        "unit": unit,
        "dtype": str(index.dtype),
        "values": [int(value) for value in index.asi8],
    }


def _datetime_index_from_metadata(value: Any, *, field: str) -> pd.DatetimeIndex:
    _exact_keys(value, {"name", "timezone", "unit", "dtype", "values"}, field)
    name = value["name"]
    timezone = value["timezone"]
    unit = value["unit"]
    dtype = value["dtype"]
    values = value["values"]
    if not isinstance(name, str) or not name.strip():
        raise TrendlineFrameArtifactError(f"{field}.name is required")
    if not isinstance(timezone, str) or not timezone.strip():
        raise TrendlineFrameArtifactError(f"{field}.timezone is required")
    if unit not in _DATETIME_UNITS:
        raise TrendlineFrameArtifactError(f"{field}.unit is unsupported")
    if not isinstance(dtype, str) or dtype != f"datetime64[{unit}, {timezone}]":
        raise TrendlineFrameArtifactError(f"{field}.dtype does not match unit/timezone")
    if (
        not isinstance(values, list)
        or not values
        or any(isinstance(item, bool) or not isinstance(item, int) for item in values)
    ):
        raise TrendlineFrameArtifactError(f"{field}.values must contain exact integer timestamps")
    try:
        result = pd.DatetimeIndex(
            values,
            dtype=f"datetime64[{unit}, {timezone}]",
            name=name,
        )
    except (TypeError, ValueError) as exc:
        raise TrendlineFrameArtifactError(f"{field} values cannot be reconstructed") from exc
    if str(result.dtype) != dtype or result.unit != unit or str(result.tz) != timezone:
        raise TrendlineFrameArtifactError(f"{field} dtype/timezone reconstruction mismatch")
    if not result.is_monotonic_increasing or not result.is_unique:
        raise TrendlineFrameArtifactError(f"{field} must be ordered and unique")
    return result


def _availability_metadata(index: pd.DatetimeIndex) -> dict[str, Any]:
    metadata = _datetime_metadata(index, field="availability")
    metadata["column_name"] = "bar_available_at"
    return {
        "column_name": metadata.pop("column_name"),
        **metadata,
    }


def _column_descriptor(series: pd.Series) -> dict[str, Any]:
    name = series.name
    if not isinstance(name, str) or not name.strip():
        raise TrendlineFrameArtifactError("data column names must be non-empty strings")
    values = series.to_numpy(copy=False)
    if values.ndim != 1 or values.dtype.kind == "O" or not np.issubdtype(values.dtype, np.number):
        raise TrendlineFrameArtifactError(
            f"data column {name} must use a one-dimensional numeric NumPy dtype"
        )
    contiguous = np.ascontiguousarray(values)
    return {
        "name": name,
        "pandas_dtype": str(series.dtype),
        "numpy_dtype": str(contiguous.dtype),
        "shape": list(contiguous.shape),
        "bytes_base64": base64.b64encode(contiguous.tobytes(order="C")).decode("ascii"),
    }


def _column_from_descriptor(
    descriptor: Any,
    *,
    index: pd.DatetimeIndex,
    row_count: int,
) -> pd.Series:
    _exact_keys(
        descriptor,
        {"name", "pandas_dtype", "numpy_dtype", "shape", "bytes_base64"},
        "column descriptor",
    )
    name = descriptor["name"]
    pandas_dtype = descriptor["pandas_dtype"]
    numpy_dtype = descriptor["numpy_dtype"]
    shape = descriptor["shape"]
    encoded = descriptor["bytes_base64"]
    if not isinstance(name, str) or not name.strip():
        raise TrendlineFrameArtifactError("column name must be non-empty")
    if not isinstance(pandas_dtype, str) or not pandas_dtype:
        raise TrendlineFrameArtifactError(f"{name}.pandas_dtype is required")
    try:
        dtype = np.dtype(numpy_dtype)
    except TypeError as exc:
        raise TrendlineFrameArtifactError(f"{name}.numpy_dtype is invalid") from exc
    if dtype.kind == "O" or not np.issubdtype(dtype, np.number):
        raise TrendlineFrameArtifactError(f"{name}.numpy_dtype is unsupported")
    if shape != [row_count]:
        raise TrendlineFrameArtifactError(f"{name}.shape does not match frame row count")
    if not isinstance(encoded, str):
        raise TrendlineFrameArtifactError(f"{name}.bytes_base64 is required")
    try:
        raw = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise TrendlineFrameArtifactError(f"{name}.bytes_base64 is invalid") from exc
    expected_bytes = int(np.prod(shape, dtype=np.int64)) * dtype.itemsize
    if len(raw) != expected_bytes:
        raise TrendlineFrameArtifactError(f"{name}.bytes_base64 length does not match dtype/shape")
    values = np.frombuffer(raw, dtype=dtype).copy().reshape(tuple(shape))
    if str(pd.Series(values).dtype) != pandas_dtype:
        raise TrendlineFrameArtifactError(f"{name}.pandas_dtype does not match encoded values")
    return pd.Series(values, index=index, name=name, dtype=dtype)


def _validate_frame_metadata(
    frame: pd.DataFrame,
) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex, BarTimestampSemantics, BarAvailabilitySource]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise TrendlineFrameArtifactError("frame must be a non-empty DataFrame")
    if not frame.columns.is_unique:
        raise TrendlineFrameArtifactError("frame columns must be unique")
    event_index = frame.index
    _datetime_metadata(event_index, field="index")
    if "bar_available_at" not in frame.columns:
        raise TrendlineFrameArtifactError("bar_available_at column is required")
    availability = pd.DatetimeIndex(frame["bar_available_at"])
    _datetime_metadata(availability, field="availability")
    if len(availability) != len(event_index):
        raise TrendlineFrameArtifactError("availability length must match frame row count")
    try:
        semantics = BarTimestampSemantics(frame.attrs["bar_timestamp_semantics"])
        provenance = BarAvailabilitySource(frame.attrs["bar_availability_source"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TrendlineFrameArtifactError(
            "frame timestamp semantics and availability provenance are required"
        ) from exc
    if semantics is BarTimestampSemantics.OPEN_TIME and not (availability > event_index).all():
        raise TrendlineFrameArtifactError("open_time availability must be strictly after event time")
    if semantics is BarTimestampSemantics.CLOSE_TIME and not (availability == event_index).all():
        raise TrendlineFrameArtifactError("close_time availability must equal event time")
    if (
        provenance is BarAvailabilitySource.CLOSE_TIME_INDEX
        and semantics is not BarTimestampSemantics.CLOSE_TIME
    ):
        raise TrendlineFrameArtifactError("close_time_index provenance requires close_time semantics")
    return event_index, availability, semantics, provenance


def _payload_without_artifact_id(
    frame: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    data_spec: TrendlineResearchDataSpec,
    source_id: str,
    availability_id: str,
    dataset_id: str,
) -> dict[str, Any]:
    event_index, availability, semantics, provenance = _validate_frame_metadata(frame)
    column_order = [str(column) for column in frame.columns]
    if len(set(column_order)) != len(column_order):
        raise TrendlineFrameArtifactError("frame columns must be unique strings")
    if any(not column.strip() for column in column_order):
        raise TrendlineFrameArtifactError("frame columns must be non-empty strings")
    if "bar_available_at" not in column_order:
        raise TrendlineFrameArtifactError("bar_available_at column is required")
    descriptors = [
        _column_descriptor(frame[column])
        for column in column_order
        if column != "bar_available_at"
    ]
    computed_source = resolve_source_ref(frame)
    computed_availability = build_research_availability_id(
        source_ref=computed_source,
        bar_available_at=availability,
        timestamp_semantics=semantics,
        availability_source=provenance,
    )
    _require_sha256(source_id, "source_id")
    _require_sha256(availability_id, "availability_id")
    _require_sha256(dataset_id, "dataset_id")
    if computed_source.source_id != source_id:
        raise TrendlineFrameArtifactError("source_id does not match frame bytes and horizon")
    if computed_availability != availability_id:
        raise TrendlineFrameArtifactError("availability_id does not match frame schedule")
    if not isinstance(asset, str) or not asset.strip():
        raise TrendlineFrameArtifactError("asset is required")
    if not isinstance(timeframe, str) or not timeframe.strip():
        raise TrendlineFrameArtifactError("timeframe is required")
    return {
        "schema_version": FRAME_ARTIFACT_SCHEMA_VERSION,
        "semantics_version": FRAME_ARTIFACT_SEMANTICS_VERSION,
        "asset": asset,
        "timeframe": timeframe,
        "data_spec": data_spec.to_dict(),
        "index": _datetime_metadata(event_index, field="index"),
        "column_order": column_order,
        "columns": descriptors,
        "availability": _availability_metadata(availability),
        "attributes": {
            "bar_timestamp_semantics": semantics.value,
            "bar_availability_source": provenance.value,
        },
        "source_id": source_id,
        "availability_id": availability_id,
        "dataset_id": dataset_id,
    }


def write_research_frame_artifact(
    frame: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    data_spec: TrendlineResearchDataSpec,
    source_id: str,
    availability_id: str,
    dataset_id: str,
    output_path: str | Path,
) -> Path:
    """Write one explicit byte-preserving research-frame artifact."""

    if not isinstance(data_spec, TrendlineResearchDataSpec):
        raise TypeError("data_spec must be a TrendlineResearchDataSpec")
    payload = _payload_without_artifact_id(
        frame,
        asset=asset,
        timeframe=timeframe,
        data_spec=data_spec,
        source_id=source_id,
        availability_id=availability_id,
        dataset_id=dataset_id,
    )
    payload["artifact_id"] = canonical_hash(
        payload,
        semantics_version=FRAME_ARTIFACT_SEMANTICS_VERSION,
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(_canonical_json_bytes(payload))
    read_research_frame_artifact(
        destination,
        expected_asset=asset,
        expected_timeframe=timeframe,
        expected_source_id=source_id,
        expected_availability_id=availability_id,
        expected_dataset_id=dataset_id,
    )
    return destination


def _validate_artifact_payload(payload: dict[str, Any]) -> None:
    _exact_keys(payload, _REQUIRED_KEYS, "frame artifact")
    if payload["schema_version"] != FRAME_ARTIFACT_SCHEMA_VERSION:
        raise TrendlineFrameArtifactError("unsupported frame artifact schema")
    if payload["semantics_version"] != FRAME_ARTIFACT_SEMANTICS_VERSION:
        raise TrendlineFrameArtifactError("unsupported frame artifact semantics")
    _require_sha256(payload["source_id"], "source_id")
    _require_sha256(payload["availability_id"], "availability_id")
    _require_sha256(payload["dataset_id"], "dataset_id")
    _require_sha256(payload["artifact_id"], "artifact_id")
    without_id = dict(payload)
    artifact_id = without_id.pop("artifact_id")
    if canonical_hash(without_id, semantics_version=FRAME_ARTIFACT_SEMANTICS_VERSION) != artifact_id:
        raise TrendlineFrameArtifactError("artifact_id does not match artifact content")
    if not isinstance(payload["asset"], str) or not payload["asset"].strip():
        raise TrendlineFrameArtifactError("asset is required")
    if not isinstance(payload["timeframe"], str) or not payload["timeframe"].strip():
        raise TrendlineFrameArtifactError("timeframe is required")
    _data_spec_from_dict(payload["data_spec"])
    _datetime_index_from_metadata(payload["index"], field="index")
    _exact_keys(
        payload["availability"],
        {"column_name", "name", "timezone", "unit", "dtype", "values"},
        "availability",
    )
    if payload["availability"]["column_name"] != "bar_available_at":
        raise TrendlineFrameArtifactError("availability column_name must be bar_available_at")
    _datetime_index_from_metadata(
        {key: value for key, value in payload["availability"].items() if key != "column_name"},
        field="availability",
    )
    _exact_keys(
        payload["attributes"],
        {"bar_timestamp_semantics", "bar_availability_source"},
        "attributes",
    )
    try:
        BarTimestampSemantics(payload["attributes"]["bar_timestamp_semantics"])
        BarAvailabilitySource(payload["attributes"]["bar_availability_source"])
    except (TypeError, ValueError) as exc:
        raise TrendlineFrameArtifactError("artifact attributes contain unknown semantics") from exc
    order = payload["column_order"]
    descriptors = payload["columns"]
    if (
        not isinstance(order, list)
        or not order
        or any(not isinstance(name, str) or not name.strip() for name in order)
        or len(set(order)) != len(order)
        or "bar_available_at" not in order
    ):
        raise TrendlineFrameArtifactError("column_order is invalid")
    if not isinstance(descriptors, list) or len(descriptors) != len(order) - 1:
        raise TrendlineFrameArtifactError("columns do not cover column_order")
    descriptor_names = [item.get("name") if isinstance(item, dict) else None for item in descriptors]
    if descriptor_names != [name for name in order if name != "bar_available_at"]:
        raise TrendlineFrameArtifactError("column descriptor order does not match column_order")


def read_research_frame_artifact(
    path: str | Path,
    *,
    expected_asset: str | None = None,
    expected_timeframe: str | None = None,
    expected_source_id: str | None = None,
    expected_availability_id: str | None = None,
    expected_dataset_id: str | None = None,
) -> pd.DataFrame:
    """Read and strictly verify one research-frame artifact."""

    payload, _ = _read_json(Path(path))
    _validate_artifact_payload(payload)
    for field, expected in (
        ("asset", expected_asset),
        ("timeframe", expected_timeframe),
        ("source_id", expected_source_id),
        ("availability_id", expected_availability_id),
        ("dataset_id", expected_dataset_id),
    ):
        if expected is not None and payload[field] != expected:
            raise TrendlineFrameArtifactError(f"{field} does not match expected identity")

    index = _datetime_index_from_metadata(payload["index"], field="index")
    availability = _datetime_index_from_metadata(
        {key: value for key, value in payload["availability"].items() if key != "column_name"},
        field="availability",
    )
    if len(index) != len(availability):
        raise TrendlineFrameArtifactError("index and availability lengths differ")
    frame = pd.DataFrame(index=index)
    for descriptor in payload["columns"]:
        series = _column_from_descriptor(
            descriptor,
            index=index,
            row_count=len(index),
        )
        frame[series.name] = series
    frame["bar_available_at"] = pd.Series(
        availability,
        index=index,
        name="bar_available_at",
    )
    frame = frame.loc[:, payload["column_order"]]
    frame.attrs = dict(payload["attributes"])
    _validate_frame_metadata(frame)

    computed_source = resolve_source_ref(frame)
    if computed_source.source_id != payload["source_id"]:
        raise TrendlineFrameArtifactError("reconstructed source_id differs from artifact")
    semantics = BarTimestampSemantics(payload["attributes"]["bar_timestamp_semantics"])
    provenance = BarAvailabilitySource(payload["attributes"]["bar_availability_source"])
    computed_availability = build_research_availability_id(
        source_ref=computed_source,
        bar_available_at=availability,
        timestamp_semantics=semantics,
        availability_source=provenance,
    )
    if computed_availability != payload["availability_id"]:
        raise TrendlineFrameArtifactError("reconstructed availability_id differs from artifact")
    return frame


__all__ = [
    "FRAME_ARTIFACT_SCHEMA_VERSION",
    "FRAME_ARTIFACT_SEMANTICS_VERSION",
    "TrendlineFrameArtifactError",
    "read_research_frame_artifact",
    "write_research_frame_artifact",
]
