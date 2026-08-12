"""Freeze one bounded six-dataset Trendline V2 OHLCV source cohort.

This module intentionally stops at normalized ``ProviderInput`` artifacts.
It does not import or execute any Trendline provider, evaluator, viewer, or
selection code.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import json
import math
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from libs.models.trendline_v2.domain.identity import canonical_json, deterministic_hash
from libs.models.trendline_v2.domain.provider_input import ProviderInput
from libs.models.trendline_v2.domain.validation import (
    ContractValidationError,
    parse_utc_isoformat,
)

UTC = timezone.utc
MARKET = "binance_usd_m_futures"
START_UTC = datetime(2026, 5, 22, tzinfo=UTC)
END_UTC = datetime(2026, 7, 1, tzinfo=UTC)
REQUEST_LIMIT = 1000
NETWORK_ENV = "TRENDLINE_V2_ALLOW_PHASE9C1_NETWORK"
OUTPUT_ROOT = Path("/tmp/trendline_v2_phase9c1_fresh_scope_sources/20260522_20260701")

SCHEMA_PREFIX = "trendline_v2_phase_9c1"
PROVIDER_INPUT_SCHEMA = f"{SCHEMA_PREFIX}_provider_input_v1"
SUPERSEDED_SOURCE_INVENTORY_SHA256 = (
    "e4c153f5f88a6a1f8e8d001d0270bfee4b3d4ac1672fe1a651e975b25f7d2562"
)
PRE_ROW_COUNT_SOURCE_INVENTORY_SHA256 = (
    "333a3beef4980952390d066cff8da44f14404e1f49e7dd842a34a84cce1bb3f1"
)
REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
ASSETS = ("BTCUSDT", "ETHUSDT", "SUIUSDT")
TIMEFRAMES = ("1h", "4h")
COHORT_ORDER = (
    ("BTCUSDT", "1h"),
    ("BTCUSDT", "4h"),
    ("ETHUSDT", "1h"),
    ("ETHUSDT", "4h"),
    ("SUIUSDT", "1h"),
    ("SUIUSDT", "4h"),
)
INTERVAL_SECONDS = {"1h": 3_600, "4h": 14_400}
EXPECTED_ADAPTER_ROWS = {"1h": 961, "4h": 241}
EXPECTED_CONFIRMED_ROWS = {"1h": 960, "4h": 240}

NORMALIZATION_POLICY = {
    "timestamp_unit": "integer_milliseconds",
    "timestamp_alignment": "whole_second_only",
    "numeric_policy": "finite_numeric_values_only",
    "ohlc_policy": "high_ge_open_close_low_and_low_le_open_close",
    "volume_policy": "finite_non_negative",
    "ordering_policy": "strict_timestamp_order_no_duplicates",
    "gap_policy": "exact_timeframe_spacing_required",
    "mutation_policy": "no_resample_fill_deduplicate_interpolate_timezone_shift_or_rounding",
}
CLOSED_BAR_POLICY = {
    "bar_close": "bar_open_plus_timeframe_interval",
    "retention": "bar_close_less_than_or_equal_to_confirmed_through",
    "confirmed_through": "2026-07-01T00:00:00Z",
}


class FreezeError(RuntimeError):
    """Expected bounded source-freeze failure."""


class NetworkGateError(FreezeError):
    """Network execution was not explicitly authorized."""


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    request_order: int
    asset: str
    timeframe: str

    @property
    def dataset_id(self) -> str:
        return f"{self.asset.lower()}_{self.timeframe}"

    @property
    def interval_seconds(self) -> int:
        return INTERVAL_SECONDS[self.timeframe]

    @property
    def expected_adapter_rows(self) -> int:
        return EXPECTED_ADAPTER_ROWS[self.timeframe]

    @property
    def expected_confirmed_rows(self) -> int:
        return EXPECTED_CONFIRMED_ROWS[self.timeframe]


DATASETS = tuple(
    DatasetSpec(index, asset, timeframe)
    for index, (asset, timeframe) in enumerate(COHORT_ORDER, start=1)
)


AdapterFactory = Callable[[], Any]
BeforePromoteHook = Callable[[Path, Path], None]


def _canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise FreezeError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise FreezeError(f"JSON artifact must be an object: {path}")
    if raw != _canonical_bytes(value):
        raise FreezeError(f"JSON artifact is not canonical: {path}")
    return value


def _write_atomic(path: Path, data: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"refusing existing output file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        if path.exists():
            raise FileExistsError(f"refusing existing output file: {path}")
        os.replace(temporary, path)
    except Exception:
        handle.close()
        temporary.unlink(missing_ok=True)
        raise


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _write_atomic(path, _canonical_bytes(value))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    _write_atomic(path, _canonical_csv_bytes(rows))


def _canonical_csv_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        raise FreezeError("cannot serialize empty CSV")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=tuple(rows[0]),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _epoch_ms(value: datetime) -> int:
    return int(value.timestamp() * 1_000)


def _epoch_ns(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000_000)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _timestamp_iso(timestamp_ms: int) -> str:
    return _iso(datetime.fromtimestamp(timestamp_ms / 1_000, tz=UTC))


def _dataset_spec(asset: str, timeframe: str) -> DatasetSpec:
    for spec in DATASETS:
        if spec.asset == asset and spec.timeframe == timeframe:
            return spec
    raise FreezeError(f"unexpected dataset: {asset}/{timeframe}")


def _cohort_contract_without_id() -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_PREFIX}_cohort_contract_v1",
        "market": MARKET,
        "fixed_start": _iso(START_UTC),
        "fixed_end_confirmed_through": _iso(END_UTC),
        "asset_list": list(ASSETS),
        "timeframe_list": list(TIMEFRAMES),
        "request_order": [spec.dataset_id for spec in DATASETS],
        "request_limit": REQUEST_LIMIT,
        "dataset_contract": [
            {
                "request_order": spec.request_order,
                "dataset_id": spec.dataset_id,
                "asset": spec.asset,
                "timeframe": spec.timeframe,
                "expected_adapter_rows": spec.expected_adapter_rows,
                "expected_confirmed_rows": spec.expected_confirmed_rows,
                "bar_interval_seconds": spec.interval_seconds,
            }
            for spec in DATASETS
        ],
        "normalization_policy": NORMALIZATION_POLICY,
        "closed_bar_policy": CLOSED_BAR_POLICY,
        "network_maximum": 6,
        "retry_policy": "zero_retries",
        "fallback_policy": "no_network_fallback",
        "provider_execution_policy": "zero_provider_executions",
    }


def _cohort_contract() -> dict[str, Any]:
    without_id = _cohort_contract_without_id()
    return {
        **without_id,
        "cohort_contract_id": deterministic_hash(
            f"{SCHEMA_PREFIX}_cohort_contract_v1", without_id
        ),
    }


def _require_frame(frame: object, spec: DatasetSpec) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise FreezeError(f"{spec.dataset_id}: adapter result is not a pandas DataFrame")
    if frame.columns.duplicated().any():
        raise FreezeError(f"{spec.dataset_id}: duplicate DataFrame columns")
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise FreezeError(f"{spec.dataset_id}: missing columns {missing}")
    if len(frame) != spec.expected_adapter_rows:
        raise FreezeError(
            f"{spec.dataset_id}: expected {spec.expected_adapter_rows} adapter rows, got {len(frame)}"
        )
    return frame.loc[:, REQUIRED_COLUMNS].copy()


def _numeric_values(series: pd.Series, *, dataset_id: str, field: str) -> tuple[float, ...]:
    if not pd.api.types.is_numeric_dtype(series.dtype) or pd.api.types.is_bool_dtype(series.dtype):
        raise FreezeError(f"{dataset_id}: {field} must have numeric dtype")
    values: list[float] = []
    for index, value in enumerate(series.tolist()):
        if isinstance(value, bool):
            raise FreezeError(f"{dataset_id}: {field}[{index}] is boolean")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise FreezeError(f"{dataset_id}: {field}[{index}] is non-numeric") from exc
        if not math.isfinite(number):
            raise FreezeError(f"{dataset_id}: {field}[{index}] is non-finite")
        values.append(number)
    return tuple(values)


def _timestamp_values(series: pd.Series, *, dataset_id: str) -> tuple[int, ...]:
    if not pd.api.types.is_integer_dtype(series.dtype) or pd.api.types.is_bool_dtype(series.dtype):
        raise FreezeError(f"{dataset_id}: timestamp must have integer dtype")
    timestamps: list[int] = []
    for index, value in enumerate(series.tolist()):
        if isinstance(value, bool):
            raise FreezeError(f"{dataset_id}: timestamp[{index}] is boolean")
        try:
            timestamp = int(value)
        except (TypeError, ValueError) as exc:
            raise FreezeError(f"{dataset_id}: timestamp[{index}] is invalid") from exc
        if timestamp % 1_000 != 0:
            raise FreezeError(f"{dataset_id}: timestamp[{index}] is not whole-second aligned")
        timestamps.append(timestamp)
    return tuple(timestamps)


def _normalize_frame(frame: object, spec: DatasetSpec) -> tuple[list[dict[str, Any]], ProviderInput]:
    normalized = _require_frame(frame, spec)
    timestamps = _timestamp_values(normalized["timestamp"], dataset_id=spec.dataset_id)
    opens = _numeric_values(normalized["open"], dataset_id=spec.dataset_id, field="open")
    highs = _numeric_values(normalized["high"], dataset_id=spec.dataset_id, field="high")
    lows = _numeric_values(normalized["low"], dataset_id=spec.dataset_id, field="low")
    closes = _numeric_values(normalized["close"], dataset_id=spec.dataset_id, field="close")
    volumes = _numeric_values(normalized["volume"], dataset_id=spec.dataset_id, field="volume")
    start_ms = _epoch_ms(START_UTC)
    end_ms = _epoch_ms(END_UTC)
    interval_ms = spec.interval_seconds * 1_000
    if timestamps[0] != start_ms or timestamps[-1] != end_ms:
        raise FreezeError(
            f"{spec.dataset_id}: boundaries must be {_timestamp_iso(start_ms)} through {_timestamp_iso(end_ms)}"
        )
    if any(
        current <= previous or current - previous != interval_ms
        for previous, current in zip(timestamps, timestamps[1:])
    ):
        raise FreezeError(f"{spec.dataset_id}: timestamp gap, duplicate or out-of-order row")
    if any(
        high < low or high < open_value or high < close or low > open_value or low > close
        for open_value, high, low, close in zip(opens, highs, lows, closes)
    ):
        raise FreezeError(f"{spec.dataset_id}: invalid OHLC relationship")
    if any(volume < 0.0 for volume in volumes):
        raise FreezeError(f"{spec.dataset_id}: negative volume")

    raw_rows = [
        {
            "timestamp": timestamp,
            "open": open_value,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
        for timestamp, open_value, high, low, close, volume in zip(
            timestamps, opens, highs, lows, closes, volumes
        )
    ]
    confirmed_rows = [
        row for row in raw_rows if row["timestamp"] + interval_ms <= end_ms
    ]
    if len(confirmed_rows) != spec.expected_confirmed_rows:
        raise FreezeError(
            f"{spec.dataset_id}: expected {spec.expected_confirmed_rows} confirmed rows, got {len(confirmed_rows)}"
        )
    if confirmed_rows[0]["timestamp"] != start_ms:
        raise FreezeError(f"{spec.dataset_id}: first confirmed boundary mismatch")
    if confirmed_rows[-1]["timestamp"] + interval_ms != end_ms:
        raise FreezeError(f"{spec.dataset_id}: last confirmed boundary mismatch")

    provider_input = ProviderInput(
        asset=spec.asset,
        timeframe=spec.timeframe,
        observed_at=END_UTC,
        confirmed_through=END_UTC,
        timestamps=tuple(row["timestamp"] * 1_000_000 for row in confirmed_rows),
        open=tuple(row["open"] for row in confirmed_rows),
        high=tuple(row["high"] for row in confirmed_rows),
        low=tuple(row["low"] for row in confirmed_rows),
        close=tuple(row["close"] for row in confirmed_rows),
        volume=tuple(row["volume"] for row in confirmed_rows),
    )
    if provider_input.timestamps[-1] + spec.interval_seconds * 1_000_000_000 != _epoch_ns(END_UTC):
        raise FreezeError(f"{spec.dataset_id}: ProviderInput end boundary mismatch")
    return raw_rows, provider_input


def _adapter_rows_artifact(spec: DatasetSpec, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    without_id = {
        "schema_version": f"{SCHEMA_PREFIX}_adapter_rows_v1",
        "asset": spec.asset,
        "timeframe": spec.timeframe,
        "request_start": _iso(START_UTC),
        "request_end": _iso(END_UTC),
        "row_count": len(rows),
        "rows": list(rows),
    }
    return {
        **without_id,
        "adapter_rows_identity": deterministic_hash(
            f"{SCHEMA_PREFIX}_adapter_rows_v1", without_id
        ),
    }


def _provider_input_artifact(provider_input: ProviderInput) -> dict[str, Any]:
    return {
        "schema_version": PROVIDER_INPUT_SCHEMA,
        "row_count": provider_input.row_count,
        **provider_input.to_dict(),
    }


def _provider_input_from_dict(payload: Mapping[str, Any]) -> ProviderInput:
    expected_keys = {
        "schema_version",
        "row_count",
        "asset",
        "timeframe",
        "input_identity",
        "observed_at",
        "confirmed_through",
        "timestamps",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    if set(payload) != expected_keys or payload.get("schema_version") != PROVIDER_INPUT_SCHEMA:
        raise FreezeError("invalid ProviderInput artifact schema")
    row_count = payload["row_count"]
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count <= 0:
        raise FreezeError("invalid ProviderInput row_count")
    try:
        input_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"schema_version", "row_count"}
        }
        input_value = ProviderInput(
            asset=input_payload["asset"],
            timeframe=input_payload["timeframe"],
            observed_at=parse_utc_isoformat(
                input_payload["observed_at"], field_name="observed_at"
            ),
            confirmed_through=parse_utc_isoformat(
                input_payload["confirmed_through"], field_name="confirmed_through"
            ),
            timestamps=tuple(input_payload["timestamps"]),
            open=tuple(input_payload["open"]),
            high=tuple(input_payload["high"]),
            low=tuple(input_payload["low"]),
            close=tuple(input_payload["close"]),
            volume=tuple(input_payload["volume"]),
        )
    except (KeyError, TypeError, ValueError, ContractValidationError) as exc:
        raise FreezeError("invalid ProviderInput artifact") from exc
    if payload.get("input_identity") != input_value.input_identity:
        raise FreezeError("ProviderInput identity mismatch")
    if row_count != input_value.row_count:
        raise FreezeError("ProviderInput row_count mismatch")
    if _provider_input_artifact(input_value) != dict(payload):
        raise FreezeError("ProviderInput semantic round-trip mismatch")
    return input_value


def _dataset_source_identity(
    spec: DatasetSpec,
    *,
    adapter_rows_identity: str,
    input_identity: str,
    adapter_row_count: int,
    confirmed_row_count: int,
) -> str:
    payload = {
        "schema_version": f"{SCHEMA_PREFIX}_dataset_source_identity_v1",
        "dataset_id": spec.dataset_id,
        "request_order": spec.request_order,
        "asset": spec.asset,
        "timeframe": spec.timeframe,
        "market": MARKET,
        "request": {
            "since_ms": _epoch_ms(START_UTC),
            "until_ms": _epoch_ms(END_UTC),
            "limit": REQUEST_LIMIT,
        },
        "adapter_rows_identity": adapter_rows_identity,
        "provider_input_identity": input_identity,
        "adapter_row_count": adapter_row_count,
        "confirmed_row_count": confirmed_row_count,
        "first_adapter_timestamp": _timestamp_iso(_epoch_ms(START_UTC)),
        "last_adapter_timestamp": _timestamp_iso(_epoch_ms(END_UTC)),
        "first_confirmed_timestamp": _timestamp_iso(_epoch_ms(START_UTC)),
        "last_confirmed_timestamp": _timestamp_iso(
            _epoch_ms(END_UTC) - spec.interval_seconds * 1_000
        ),
        "bar_interval_seconds": spec.interval_seconds,
        "normalization_policy": NORMALIZATION_POLICY,
        "closed_bar_policy": CLOSED_BAR_POLICY,
    }
    return deterministic_hash(f"{SCHEMA_PREFIX}_dataset_source_identity_v1", payload)


def _dataset_artifacts(
    spec: DatasetSpec,
    *,
    rows: Sequence[Mapping[str, Any]],
    provider_input: ProviderInput,
) -> dict[str, dict[str, Any]]:
    adapter_rows = _adapter_rows_artifact(spec, rows)
    run_report_without_id = {
        "schema_version": f"{SCHEMA_PREFIX}_run_report_v1",
        "dataset_id": spec.dataset_id,
        "asset": spec.asset,
        "timeframe": spec.timeframe,
        "market": MARKET,
        "request_order": spec.request_order,
        "request_limit": REQUEST_LIMIT,
        "request_start": _iso(START_UTC),
        "request_end": _iso(END_UTC),
        "network_request_count": 1,
        "retry_count": 0,
        "fallback_used": False,
        "adapter_row_count": len(rows),
        "confirmed_row_count": provider_input.row_count,
        "dropped_unclosed_row_count": len(rows) - provider_input.row_count,
        "first_adapter_timestamp": _timestamp_iso(rows[0]["timestamp"]),
        "last_adapter_timestamp": _timestamp_iso(rows[-1]["timestamp"]),
        "first_confirmed_timestamp": _timestamp_iso(
            provider_input.timestamps[0] // 1_000_000
        ),
        "last_confirmed_timestamp": _timestamp_iso(
            provider_input.timestamps[-1] // 1_000_000
        ),
        "bar_interval_seconds": spec.interval_seconds,
        "input_identity": provider_input.input_identity,
        "adapter_rows_identity": adapter_rows["adapter_rows_identity"],
        "dataset_source_identity": _dataset_source_identity(
            spec,
            adapter_rows_identity=adapter_rows["adapter_rows_identity"],
            input_identity=provider_input.input_identity,
            adapter_row_count=len(rows),
            confirmed_row_count=provider_input.row_count,
        ),
        "provider_execution_count": 0,
        "candidate_generation_status": "NOT_EXECUTED",
    }
    return {
        "adapter_rows": adapter_rows,
        "provider_input": _provider_input_artifact(provider_input),
        "run_report": run_report_without_id,
    }


def _inventory(root: Path, *, exclude: set[str] | None = None) -> list[dict[str, Any]]:
    excluded = set() if exclude is None else exclude
    result: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        result.append(
            {
                "path": relative,
                "byte_length": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return result


def _inventory_digest(inventory: Sequence[Mapping[str, Any]]) -> str:
    return _sha256_bytes(_canonical_bytes(list(inventory)))


def _source_summary_rows(reports: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "request_order": report["request_order"],
            "dataset_id": report["dataset_id"],
            "asset": report["asset"],
            "timeframe": report["timeframe"],
            "adapter_row_count": report["adapter_row_count"],
            "confirmed_row_count": report["confirmed_row_count"],
            "first_confirmed_timestamp": report["first_confirmed_timestamp"],
            "last_confirmed_timestamp": report["last_confirmed_timestamp"],
            "adapter_rows_identity": report["adapter_rows_identity"],
            "input_identity": report["input_identity"],
            "dataset_source_identity": report["dataset_source_identity"],
        }
        for report in reports
    )


def _network_audit(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    requests = [
        {
            "request_order": report["request_order"],
            "dataset_id": report["dataset_id"],
            "asset": report["asset"],
            "timeframe": report["timeframe"],
            "since_ms": _epoch_ms(START_UTC),
            "until_ms": _epoch_ms(END_UTC),
            "limit": REQUEST_LIMIT,
            "result_status": "success",
            "adapter_row_count": report["adapter_row_count"],
        }
        for report in reports
    ]
    return {
        "schema_version": f"{SCHEMA_PREFIX}_network_audit_v1",
        "network_request_count": len(requests),
        "retry_count": 0,
        "fallback_count": 0,
        "all_requests_match_contract": len(requests) == len(DATASETS),
        "requests": requests,
    }


def _decision(
    *,
    cohort_contract_id: str,
    cohort_source_identity: str,
    reports: Sequence[Mapping[str, Any]],
    remediation_source_inventory_sha256: str | None = None,
    remediation_network_request_count: int | None = None,
) -> dict[str, Any]:
    without_id = {
        "schema_version": f"{SCHEMA_PREFIX}_decision_v1",
        "study_status": "FRESH_SOURCE_FREEZE_COMPLETE",
        "cohort_contract_id": cohort_contract_id,
        "cohort_source_identity": cohort_source_identity,
        "dataset_count": len(reports),
        "successful_source_count": sum(
            report["candidate_generation_status"] == "NOT_EXECUTED" for report in reports
        ),
        "network_request_count": len(reports),
        "historical_acquisition_request_count": len(reports),
        "provider_execution_count": 0,
        "dataset_source_identities": [
            report["dataset_source_identity"] for report in reports
        ],
        "dataset_row_counts": {
            report["dataset_id"]: {
                "adapter": report["adapter_row_count"],
                "confirmed": report["confirmed_row_count"],
            }
            for report in reports
        },
        "dataset_boundaries": {
            report["dataset_id"]: {
                "first_confirmed": report["first_confirmed_timestamp"],
                "last_confirmed": report["last_confirmed_timestamp"],
                "confirmed_through": report["request_end"],
            }
            for report in reports
        },
        "limitations": [
            "The bundle freezes six fresh OHLCV inputs only. It contains no candidate, continuation, eligibility-family, predictive, trading, tracking, or MTF evidence.",
            "No provider, evaluator, family selection or parameter promotion was executed.",
        ],
        "PROVIDER_EXECUTION": "NOT_AUTHORIZED",
        "CANDIDATE_EVALUATION": "NOT_AUTHORIZED",
        "ELIGIBILITY_FAMILY_SELECTION": "NOT_AUTHORIZED",
        "PARAMETER_PROMOTION": "NOT_AUTHORIZED",
        "CANONICAL_CONFIG_CHANGE": "NOT_AUTHORIZED",
        "TRACKER_START": "NOT_AUTHORIZED",
        "PHASE_9C2_START": "NOT_AUTHORIZED",
        "MTF": "NOT_AUTHORIZED",
    }
    if remediation_source_inventory_sha256 is not None:
        without_id["remediation_source_inventory_sha256"] = (
            remediation_source_inventory_sha256
        )
    if remediation_network_request_count is not None:
        without_id["remediation_network_request_count"] = remediation_network_request_count
    return {
        **without_id,
        "decision_id": deterministic_hash(f"{SCHEMA_PREFIX}_decision_v1", without_id),
    }


def _default_adapter_factory() -> Any:
    from libs.market_data.binance_native import BinanceNativeAdapter

    return BinanceNativeAdapter()


def _require_network_gate(execute_network: bool) -> None:
    if not execute_network or os.environ.get(NETWORK_ENV) != "1":
        raise NetworkGateError(
            f"network gate requires --execute-network and {NETWORK_ENV}=1"
        )


async def _fetch_sources(
    *,
    adapter: Any,
    staging_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reports: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for spec in DATASETS:
        dataset_root = staging_root / "datasets" / spec.dataset_id
        dataset_root.mkdir(parents=True, exist_ok=False)
        since_ms = _epoch_ms(START_UTC)
        until_ms = _epoch_ms(END_UTC)
        try:
            frame = await adapter.get_historical_ohlcv(
                symbol=spec.asset,
                timeframe=spec.timeframe,
                since=since_ms,
                until=until_ms,
                limit=REQUEST_LIMIT,
            )
            rows, provider_input = _normalize_frame(frame, spec)
            artifacts = _dataset_artifacts(
                spec,
                rows=rows,
                provider_input=provider_input,
            )
        except Exception as exc:
            raise FreezeError(
                f"dataset={spec.dataset_id} consumed_requests={spec.request_order} "
                f"exception={type(exc).__name__} failure_boundary=fetch_or_normalize: {exc}"
            ) from exc
        _write_json(dataset_root / "adapter_rows.json", artifacts["adapter_rows"])
        _write_json(dataset_root / "provider_input.json", artifacts["provider_input"])
        _write_json(dataset_root / "run_report.json", artifacts["run_report"])
        reports.append(artifacts["run_report"])
        audits.append(
            {
                "request_order": spec.request_order,
                "dataset_id": spec.dataset_id,
                "asset": spec.asset,
                "timeframe": spec.timeframe,
                "since_ms": since_ms,
                "until_ms": until_ms,
                "limit": REQUEST_LIMIT,
                "result_status": "success",
                "adapter_row_count": len(rows),
            }
        )
    return reports, audits


def _finalize_staging(
    *,
    staging_root: Path,
    output_root: Path,
    reports: Sequence[Mapping[str, Any]],
    remediation_source_inventory_sha256: str | None = None,
    remediation_network_request_count: int | None = None,
    before_promote: BeforePromoteHook | None = None,
) -> dict[str, Any]:
    if len(reports) != len(DATASETS):
        raise FreezeError("successful source count does not equal fixed cohort size")
    contract = _cohort_contract()
    cohort_source_identity = deterministic_hash(
        f"{SCHEMA_PREFIX}_cohort_source_v1",
        {
            "cohort_contract_id": contract["cohort_contract_id"],
            "request_order": [
                {
                    "dataset_id": report["dataset_id"],
                    "dataset_source_identity": report["dataset_source_identity"],
                }
                for report in reports
            ],
        },
    )
    _write_json(staging_root / "cohort_contract.json", contract)
    _write_json(staging_root / "network_audit.json", _network_audit(reports))
    _write_csv(staging_root / "source_summary.csv", _source_summary_rows(reports))
    decision = _decision(
        cohort_contract_id=contract["cohort_contract_id"],
        cohort_source_identity=cohort_source_identity,
        reports=reports,
        remediation_source_inventory_sha256=remediation_source_inventory_sha256,
        remediation_network_request_count=remediation_network_request_count,
    )
    _write_json(staging_root / "decision.json", decision)
    members = _inventory(staging_root)
    expected_member_count = len(DATASETS) * 3 + 4
    if len(members) != expected_member_count:
        raise FreezeError(
            f"expected {expected_member_count} data files before manifest, got {len(members)}"
        )
    manifest_without_id: dict[str, Any] = {
        "schema_version": f"{SCHEMA_PREFIX}_manifest_v1",
        "study_status": "FRESH_SOURCE_FREEZE_COMPLETE",
        "cohort_contract_id": contract["cohort_contract_id"],
        "cohort_source_identity": cohort_source_identity,
        "dataset_source_identities": [
            report["dataset_source_identity"] for report in reports
        ],
        "network_request_count": len(reports),
        "historical_acquisition_request_count": len(reports),
        "provider_execution_count": 0,
        "members": members,
    }
    if remediation_source_inventory_sha256 is not None:
        manifest_without_id["remediation_source_inventory_sha256"] = (
            remediation_source_inventory_sha256
        )
    if remediation_network_request_count is not None:
        manifest_without_id["remediation_network_request_count"] = (
            remediation_network_request_count
        )
    manifest = {
        **manifest_without_id,
        "manifest_id": deterministic_hash(
            f"{SCHEMA_PREFIX}_manifest_v1", manifest_without_id
        ),
    }
    _write_json(staging_root / "manifest.json", manifest)
    if _inventory(staging_root, exclude={"manifest.json"}) != members:
        raise FreezeError("data member inventory changed before promotion")
    if before_promote is not None:
        before_promote(staging_root, output_root)
    if output_root.exists():
        raise FileExistsError(f"refusing existing canonical output root: {output_root}")
    os.replace(staging_root, output_root)
    return {
        "output_root": str(output_root),
        "cohort_contract_id": contract["cohort_contract_id"],
        "cohort_source_identity": cohort_source_identity,
        "decision_id": decision["decision_id"],
        "manifest_id": manifest["manifest_id"],
        "dataset_reports": list(reports),
        "network_audit": _network_audit(reports),
        "historical_acquisition_request_count": len(reports),
        "remediation_network_request_count": remediation_network_request_count or 0,
    }


def run_freeze(
    *,
    output_root: str | Path = OUTPUT_ROOT,
    adapter_factory: AdapterFactory | None = None,
    execute_network: bool = False,
    _before_promote: BeforePromoteHook | None = None,
) -> dict[str, Any]:
    """Acquire, normalize and atomically publish the fixed six-source cohort."""

    output_root = Path(output_root)
    if output_root.exists():
        raise FileExistsError(f"refusing existing canonical output root: {output_root}")
    _require_network_gate(execute_network)
    factory = _default_adapter_factory if adapter_factory is None else adapter_factory
    adapter = factory()
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=".phase9c1-", dir=output_root.parent))
    try:
        reports, _ = asyncio.run(_fetch_sources(adapter=adapter, staging_root=staging_root))
        result = _finalize_staging(
            staging_root=staging_root,
            output_root=output_root,
            reports=reports,
            before_promote=_before_promote,
        )
        staging_root = Path()
        return result
    except Exception:
        if staging_root != Path():
            shutil.rmtree(staging_root, ignore_errors=True)
        raise


def regenerate_offline(
    *,
    source_root: str | Path,
    output_root: str | Path = OUTPUT_ROOT,
    before_promote: BeforePromoteHook | None = None,
) -> dict[str, Any]:
    """Regenerate the corrected bundle from preserved raw adapter artifacts.

    This path deliberately has no adapter factory, network gate, provider call,
    or evaluator dependency. It accepts only the immutable historical source
    root and derives every typed input again from its persisted raw rows.
    """

    source_root = Path(source_root)
    output_root = Path(output_root)
    if not source_root.is_dir():
        raise FreezeError(f"missing remediation source root: {source_root}")
    if output_root.exists():
        raise FileExistsError(f"refusing existing canonical output root: {output_root}")
    source_before = _inventory(source_root)
    source_digest = _inventory_digest(source_before)
    if source_digest != SUPERSEDED_SOURCE_INVENTORY_SHA256:
        raise FreezeError("remediation source inventory identity mismatch")

    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=".phase9c1-offline-", dir=output_root.parent))
    try:
        reports: list[dict[str, Any]] = []
        for spec in DATASETS:
            source_dataset_root = source_root / "datasets" / spec.dataset_id
            dataset_root = staging_root / "datasets" / spec.dataset_id
            dataset_root.mkdir(parents=True, exist_ok=False)
            adapter_rows = _load_json(source_dataset_root / "adapter_rows.json")
            rows = adapter_rows.get("rows")
            if not isinstance(rows, list):
                raise FreezeError(f"invalid adapter rows: {spec.dataset_id}")
            derived_rows, provider_input = _normalize_frame(pd.DataFrame(rows), spec)
            if derived_rows != rows:
                raise FreezeError(f"adapter-row normalization mismatch: {spec.dataset_id}")
            expected_adapter = _adapter_rows_artifact(spec, derived_rows)
            if adapter_rows != expected_adapter:
                raise FreezeError(f"adapter rows identity mismatch: {spec.dataset_id}")
            artifacts = _dataset_artifacts(
                spec,
                rows=derived_rows,
                provider_input=provider_input,
            )
            _write_json(dataset_root / "adapter_rows.json", artifacts["adapter_rows"])
            _write_json(dataset_root / "provider_input.json", artifacts["provider_input"])
            _write_json(dataset_root / "run_report.json", artifacts["run_report"])
            reports.append(artifacts["run_report"])

        if _inventory(source_root) != source_before:
            raise FreezeError("remediation source changed before publication")
        result = _finalize_staging(
            staging_root=staging_root,
            output_root=output_root,
            reports=reports,
            remediation_source_inventory_sha256=source_digest,
            remediation_network_request_count=0,
            before_promote=before_promote,
        )
        staging_root = Path()
        if _inventory(source_root) != source_before:
            raise FreezeError("remediation source changed after publication")
        return result
    except Exception:
        if staging_root != Path():
            shutil.rmtree(staging_root, ignore_errors=True)
        raise


def _verify_dataset(root: Path, spec: DatasetSpec) -> dict[str, Any]:
    dataset_root = root / "datasets" / spec.dataset_id
    if not dataset_root.is_dir():
        raise FreezeError(f"missing dataset directory: {spec.dataset_id}")
    adapter_rows = _load_json(dataset_root / "adapter_rows.json")
    provider_payload = _load_json(dataset_root / "provider_input.json")
    _provider_input_from_dict(provider_payload)
    report = _load_json(dataset_root / "run_report.json")
    rows = adapter_rows.get("rows")
    if not isinstance(rows, list):
        raise FreezeError(f"invalid adapter rows: {spec.dataset_id}")
    expected_adapter = _adapter_rows_artifact(spec, rows)
    if adapter_rows != expected_adapter:
        raise FreezeError(f"adapter rows identity mismatch: {spec.dataset_id}")
    try:
        raw_frame = pd.DataFrame(rows)
        derived_rows, derived_input = _normalize_frame(raw_frame, spec)
    except (FreezeError, ContractValidationError, TypeError, ValueError) as exc:
        raise FreezeError(f"adapter-row normalization failed: {spec.dataset_id}") from exc
    if derived_rows != rows:
        raise FreezeError(f"adapter-row normalization mismatch: {spec.dataset_id}")
    expected_provider_artifact = _provider_input_artifact(derived_input)
    if provider_payload != expected_provider_artifact:
        raise FreezeError(f"ProviderInput is not derived from adapter rows: {spec.dataset_id}")
    expected_artifacts = _dataset_artifacts(
        spec,
        rows=derived_rows,
        provider_input=derived_input,
    )
    if report != expected_artifacts["run_report"]:
        raise FreezeError(f"run report semantic mismatch: {spec.dataset_id}")
    return report


def verify_bundle(output_root: str | Path = OUTPUT_ROOT) -> dict[str, Any]:
    """Verify completed source bundle without network or regeneration."""

    root = Path(output_root)
    if not root.is_dir():
        raise FreezeError(f"missing source-freeze output root: {root}")
    contract = _load_json(root / "cohort_contract.json")
    contract_without_id = {
        key: value for key, value in contract.items() if key != "cohort_contract_id"
    }
    if contract_without_id != _cohort_contract_without_id():
        raise FreezeError("cohort contract drift")
    expected_contract_id = deterministic_hash(
        f"{SCHEMA_PREFIX}_cohort_contract_v1", contract_without_id
    )
    if contract.get("cohort_contract_id") != expected_contract_id:
        raise FreezeError("cohort contract identity mismatch")
    reports = [_verify_dataset(root, spec) for spec in DATASETS]
    if [report["dataset_id"] for report in reports] != [spec.dataset_id for spec in DATASETS]:
        raise FreezeError("dataset order mismatch")
    expected_cohort_source_identity = deterministic_hash(
        f"{SCHEMA_PREFIX}_cohort_source_v1",
        {
            "cohort_contract_id": expected_contract_id,
            "request_order": [
                {
                    "dataset_id": report["dataset_id"],
                    "dataset_source_identity": report["dataset_source_identity"],
                }
                for report in reports
            ],
        },
    )
    network_audit = _load_json(root / "network_audit.json")
    expected_audit = _network_audit(reports)
    if network_audit != expected_audit:
        raise FreezeError("network audit mismatch")
    source_summary = root / "source_summary.csv"
    if not source_summary.is_file():
        raise FreezeError("missing source summary")
    expected_summary_bytes = _canonical_csv_bytes(_source_summary_rows(reports))
    if source_summary.read_bytes() != expected_summary_bytes:
        raise FreezeError("source summary semantic mismatch")
    decision = _load_json(root / "decision.json")
    remediation_source_inventory_sha256 = decision.get(
        "remediation_source_inventory_sha256"
    )
    remediation_network_request_count = decision.get("remediation_network_request_count")
    if (remediation_source_inventory_sha256 is None) != (
        remediation_network_request_count is None
    ):
        raise FreezeError("incomplete remediation lineage")
    if remediation_source_inventory_sha256 is not None and (
        remediation_source_inventory_sha256 != SUPERSEDED_SOURCE_INVENTORY_SHA256
        or remediation_network_request_count != 0
    ):
        raise FreezeError("remediation lineage identity mismatch")
    expected_decision = _decision(
        cohort_contract_id=expected_contract_id,
        cohort_source_identity=expected_cohort_source_identity,
        reports=reports,
        remediation_source_inventory_sha256=remediation_source_inventory_sha256,
        remediation_network_request_count=remediation_network_request_count,
    )
    if decision != expected_decision:
        raise FreezeError("decision semantic mismatch")
    manifest = _load_json(root / "manifest.json")
    manifest_without_id = {key: value for key, value in manifest.items() if key != "manifest_id"}
    expected_members = _inventory(root, exclude={"manifest.json"})
    expected_manifest_without_id = {
        "schema_version": f"{SCHEMA_PREFIX}_manifest_v1",
        "study_status": "FRESH_SOURCE_FREEZE_COMPLETE",
        "cohort_contract_id": expected_contract_id,
        "cohort_source_identity": expected_cohort_source_identity,
        "dataset_source_identities": [
            report["dataset_source_identity"] for report in reports
        ],
        "network_request_count": 6,
        "historical_acquisition_request_count": 6,
        "provider_execution_count": 0,
        "members": expected_members,
    }
    manifest_lineage = {
        key: manifest.get(key)
        for key in (
            "remediation_source_inventory_sha256",
            "remediation_network_request_count",
        )
        if key in manifest
    }
    decision_lineage = {
        key: decision.get(key)
        for key in (
            "remediation_source_inventory_sha256",
            "remediation_network_request_count",
        )
        if key in decision
    }
    if manifest_lineage != decision_lineage:
        raise FreezeError("decision and manifest remediation lineage mismatch")
    expected_manifest_without_id.update(manifest_lineage)
    if manifest_without_id != expected_manifest_without_id:
        raise FreezeError("manifest semantic mismatch")
    expected_manifest_id = deterministic_hash(
        f"{SCHEMA_PREFIX}_manifest_v1", manifest_without_id
    )
    if manifest.get("manifest_id") != expected_manifest_id:
        raise FreezeError("manifest identity mismatch")
    if len(expected_members) != len(DATASETS) * 3 + 4:
        raise FreezeError("unexpected output member count")
    for member in expected_members:
        path = root / member["path"]
        if path.stat().st_size != member["byte_length"] or _sha256_file(path) != member["sha256"]:
            raise FreezeError(f"manifest member hash mismatch: {member['path']}")
    return {
        "output_root": str(root),
        "cohort_contract_id": expected_contract_id,
        "cohort_source_identity": expected_cohort_source_identity,
        "decision_id": decision["decision_id"],
        "decision_sha256": _sha256_file(root / "decision.json"),
        "manifest_id": manifest["manifest_id"],
        "manifest_sha256": _sha256_file(root / "manifest.json"),
        "inventory": expected_members,
        "inventory_sha256": _inventory_digest(_inventory(root)),
        "dataset_reports": reports,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    try:
        result = run_freeze(
            output_root=args.output_root,
            execute_network=args.execute_network,
        )
    except (FreezeError, FileExistsError) as exc:
        print(f"BLOCKED_FRESH_SOURCE_FREEZE: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
