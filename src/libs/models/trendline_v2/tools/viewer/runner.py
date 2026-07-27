"""Generic, offline-first Trendline V2 viewer runner."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from threading import Thread
from typing import Any

import pandas as pd

from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter
from libs.models.trendline_v2 import discover_trendlines
from libs.models.trendline_v2.configuration import (
    ConfirmedExtremaPairConfig,
    ResolvedTrendlineV2Config,
    resolve_trendline_v2_config,
)
from libs.models.trendline_v2.discovery import (
    ProviderDiagnostics,
    ProviderInput,
    ProviderRequest,
    ProviderResult,
    ProviderStatus,
)
from libs.models.trendline_v2.discovery.provider_evidence import (
    ConfirmedExtremaPairEvidence,
)
from libs.models.trendline_v2.domain.candidates import LineCandidate
from libs.models.trendline_v2.domain.identity import deterministic_hash
from libs.models.trendline_v2.domain.validation import (
    ContractValidationError,
    parse_utc_isoformat,
)
from libs.models.trendline_v2.input import ConfirmedOHLCVFrame
from libs.models.trendline_v2.tools.viewer.payload import write_viewer_bundle
from libs.models.trendline_v2.tools.viewer.server import make_server, validate_bundle


UTC = timezone.utc
SOURCE_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
MODEL_COLUMNS = SOURCE_COLUMNS[1:]
VIEWER_RUN_SCHEMA_VERSION = "trendline_v2_generic_viewer_run_v1"
SOURCE_BINDING_SCHEMA_VERSION = "trendline_v2_generic_viewer_source_binding_v1"
PROVIDER_PROFILE_NAME = "confirmed_extrema_pair_viewer_v1"
BINANCE_PAGE_LIMIT = 1_000
MAX_BINANCE_PAGES = 100
FETCH_ENVIRONMENT_VARIABLE = "TRENDLINE_V2_ALLOW_VIEWER_FETCH"
_TIMESTAMP_INTEGER = re.compile(r"^[+-]?\d+$")
_TIMEFRAME = re.compile(r"^(0|[1-9]\d*)([mhd])$")
_ALLOWED_ASSETS = frozenset({"BTCUSDT", "ETHUSDT", "SUIUSDT", "SOLUSDT"})
_OUTPUT_MEMBERS = frozenset(
    {"source_binding.json", "provider_result.json", "run_report.json", "viewer_bundle"}
)
_BUNDLE_MEMBERS = frozenset({"chart_payload.json", "manifest.json"})
_PROVIDER_RESULT_KEYS = frozenset(
    {
        "provider_name",
        "provider_version",
        "provider_identity",
        "provider_contract_identity",
        "request",
        "status",
        "candidates",
        "evidence",
        "diagnostics",
        "reason",
        "detail",
    }
)

FOUNDATION_CONFIG_INPUT = {
    "model": {
        "name": "trendline_v2",
        "version": "foundation_v1",
        "schema_version": 1,
    }
}
VIEWER_PROVIDER_CONFIG_VALUES = {
    "lookback_duration_seconds": 10_540_800.0,
    "left_confirmation_bars": 1,
    "right_confirmation_bars": 1,
    "min_extrema_per_role": 2,
    "max_hypotheses": 100_000,
    "max_output_candidates": 10_000,
}


class ViewerRunnerError(ValueError):
    """Expected fail-closed runner error."""


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
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


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: datetime | str, *, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ViewerRunnerError(f"{field_name} must be ISO-8601 UTC") from exc
    else:
        raise ViewerRunnerError(f"{field_name} must be ISO-8601 UTC")
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ViewerRunnerError(f"{field_name} must be timezone-aware UTC")
    parsed = parsed.astimezone(UTC)
    if parsed.microsecond:
        raise ViewerRunnerError(f"{field_name} must be aligned to whole UTC seconds")
    return parsed


def validate_asset(asset: str) -> str:
    if not isinstance(asset, str) or asset not in _ALLOWED_ASSETS:
        raise ViewerRunnerError(
            "asset must be one of BTCUSDT, ETHUSDT, SUIUSDT or SOLUSDT in canonical uppercase"
        )
    return asset


def timeframe_interval_seconds(timeframe: str) -> int:
    if not isinstance(timeframe, str):
        raise ViewerRunnerError("timeframe must use <number>m, <number>h or <number>d")
    match = _TIMEFRAME.fullmatch(timeframe)
    if match is None:
        raise ViewerRunnerError("timeframe must use <number>m, <number>h or <number>d")
    quantity = int(match.group(1))
    if quantity <= 0:
        raise ViewerRunnerError("timeframe quantity must be positive")
    multiplier = {"m": 60, "h": 3_600, "d": 86_400}[match.group(2)]
    return quantity * multiplier


def foundation_config() -> ResolvedTrendlineV2Config:
    return resolve_trendline_v2_config(FOUNDATION_CONFIG_INPUT)


def viewer_provider_config() -> ConfirmedExtremaPairConfig:
    return ConfirmedExtremaPairConfig(**VIEWER_PROVIDER_CONFIG_VALUES)


def _finite_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool):
        raise ViewerRunnerError(f"{field_name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ViewerRunnerError(f"{field_name} must be numeric") from exc
    if not math.isfinite(result):
        raise ViewerRunnerError(f"{field_name} must be finite")
    return result


def _timestamp_values(values: pd.Series) -> pd.DatetimeIndex:
    raw = tuple(values.tolist())
    if not raw:
        raise ViewerRunnerError("CSV timestamp column must be non-empty")
    numeric_flags = []
    for value in raw:
        if isinstance(value, bool):
            numeric_flags.append(False)
        elif isinstance(value, int):
            numeric_flags.append(True)
        elif isinstance(value, str) and _TIMESTAMP_INTEGER.fullmatch(value.strip()):
            numeric_flags.append(True)
        else:
            numeric_flags.append(False)
    if all(numeric_flags):
        try:
            millis = [int(value) for value in raw]
            parsed = pd.to_datetime(millis, unit="ms", utc=True, errors="raise")
        except (TypeError, ValueError, OverflowError) as exc:
            raise ViewerRunnerError("CSV epoch-millisecond timestamps are invalid") from exc
        return pd.DatetimeIndex(parsed).tz_convert("UTC")
    if any(numeric_flags):
        raise ViewerRunnerError("CSV timestamp formats must not be mixed")

    parsed_values: list[datetime] = []
    for value in raw:
        if not isinstance(value, str):
            raise ViewerRunnerError("CSV timestamps must be epoch milliseconds or ISO-8601 UTC")
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ViewerRunnerError("CSV ISO timestamps are invalid") from exc
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ViewerRunnerError("CSV ISO timestamps must be timezone-aware UTC")
        parsed_values.append(parsed.astimezone(UTC))
    return pd.DatetimeIndex(parsed_values).tz_convert("UTC")


def _validate_cadence(
    timestamps: pd.DatetimeIndex,
    *,
    interval_seconds: int,
) -> None:
    if timestamps.empty:
        raise ViewerRunnerError("no complete candles remain at as-of boundary")
    interval = pd.Timedelta(seconds=interval_seconds)
    epoch_nanoseconds = (
        timestamps.tz_convert("UTC")
        .tz_localize(None)
        .astype("datetime64[ns]")
        .view("int64")
    )
    epoch_seconds = epoch_nanoseconds // 1_000_000_000
    if any(int(value) % interval_seconds for value in epoch_seconds):
        raise ViewerRunnerError("candle timestamps are not aligned to declared timeframe")
    if not timestamps.is_monotonic_increasing:
        raise ViewerRunnerError("candle timestamps are not strictly increasing")
    if not timestamps.is_unique:
        raise ViewerRunnerError("candle timestamps are duplicated")
    if len(timestamps) > 1 and not (timestamps.to_series().diff().dropna() == interval).all():
        raise ViewerRunnerError("candle timestamps contain a missing interval")


def _validate_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = pd.DataFrame(index=frame.index.copy())
    for column in MODEL_COLUMNS:
        converted = pd.to_numeric(frame[column], errors="coerce")
        if converted.isna().any():
            raise ViewerRunnerError(f"CSV column {column} contains non-numeric values")
        values = converted.to_numpy(dtype="float64", copy=True)
        if not all(math.isfinite(float(value)) for value in values):
            raise ViewerRunnerError(f"CSV column {column} contains non-finite values")
        normalized[column] = values
    high = normalized["high"].to_numpy(dtype="float64")
    low = normalized["low"].to_numpy(dtype="float64")
    open_values = normalized["open"].to_numpy(dtype="float64")
    close = normalized["close"].to_numpy(dtype="float64")
    volume = normalized["volume"].to_numpy(dtype="float64")
    if (high < low).any() or (high < open_values).any() or (high < close).any():
        raise ViewerRunnerError("CSV OHLC values violate high bounds")
    if (low > open_values).any() or (low > close).any():
        raise ViewerRunnerError("CSV OHLC values violate low bounds")
    if (volume < 0).any():
        raise ViewerRunnerError("CSV volume cannot be negative")
    return normalized


def _causal_frame_from_raw(
    raw: pd.DataFrame,
    *,
    timestamps: pd.DatetimeIndex,
    asset: str,
    timeframe: str,
    interval_seconds: int,
    start: datetime | None,
    as_of: datetime,
    close_times: pd.DatetimeIndex,
    exchange_close_time: bool = False,
) -> tuple[pd.DataFrame, datetime]:
    if len(raw) != len(timestamps) or len(raw) != len(close_times):
        raise ViewerRunnerError("source timestamp and candle arrays have different lengths")
    interval = pd.Timedelta(seconds=interval_seconds)
    if not (close_times > timestamps).all():
        raise ViewerRunnerError("source close times must follow candle opens")
    complete = close_times <= pd.Timestamp(as_of)
    if start is not None:
        complete &= timestamps >= pd.Timestamp(start)
    if not complete.any():
        raise ViewerRunnerError("no complete candles remain at requested boundaries")
    selected_timestamps = timestamps[complete]
    _validate_cadence(selected_timestamps, interval_seconds=interval_seconds)
    selected = raw.loc[complete, list(MODEL_COLUMNS)].copy()
    normalized = _validate_ohlcv(selected)
    normalized.index = selected_timestamps
    normalized.index.name = None
    last_close = close_times[complete][-1].to_pydatetime().astimezone(UTC)
    minimum_close = normalized.index[-1].to_pydatetime().astimezone(UTC) + interval
    if exchange_close_time:
        minimum_close -= timedelta(milliseconds=1)
    if last_close < minimum_close:
        raise ViewerRunnerError("last candle close precedes its declared interval")
    return normalized.astype("float64"), last_close


def _load_csv(
    input_csv: Path,
    *,
    asset: str,
    timeframe: str,
    interval_seconds: int,
    start: datetime | None,
    as_of: datetime,
) -> tuple[ConfirmedOHLCVFrame, dict[str, Any]]:
    if input_csv.is_symlink() or not input_csv.is_file():
        raise ViewerRunnerError("input CSV must be a regular file")
    try:
        raw = pd.read_csv(input_csv)
    except (OSError, ValueError) as exc:
        raise ViewerRunnerError(f"cannot read input CSV: {input_csv}") from exc
    missing = [column for column in SOURCE_COLUMNS if column not in raw.columns]
    if missing:
        raise ViewerRunnerError(f"CSV missing required columns: {missing}")
    timestamps = _timestamp_values(raw["timestamp"])
    interval = pd.Timedelta(seconds=interval_seconds)
    close_times = timestamps + interval
    normalized, last_close = _causal_frame_from_raw(
        raw,
        timestamps=timestamps,
        asset=asset,
        timeframe=timeframe,
        interval_seconds=interval_seconds,
        start=start,
        as_of=as_of,
        close_times=close_times,
    )
    frame = ConfirmedOHLCVFrame.from_frame(
        normalized,
        asset=asset,
        timeframe=timeframe,
        observed_at=as_of,
        confirmed_through=as_of,
    )
    return frame, {
        "source_type": "csv",
        "source_file_sha256": None,
        "binance_request_identity": None,
        "page_count": 0,
        "request_pages": [],
        "display_path": str(input_csv.resolve()),
        "last_candle_close": last_close,
    }


def _page_integer(page: pd.DataFrame, *, column: str) -> pd.Series:
    if column not in page.columns:
        raise ViewerRunnerError(f"Binance page missing {column}")
    converted = pd.to_numeric(page[column], errors="coerce")
    if converted.isna().any():
        raise ViewerRunnerError(f"Binance page {column} contains invalid values")
    values: list[int] = []
    for value in converted.tolist():
        numeric = float(value)
        if not math.isfinite(numeric) or not numeric.is_integer():
            raise ViewerRunnerError(f"Binance page {column} must contain finite integers")
        integer = int(numeric)
        if not -(2**63) <= integer <= 2**63 - 1:
            raise ViewerRunnerError(f"Binance page {column} is outside integer range")
        values.append(integer)
    return pd.Series(values, index=page.index, dtype="int64")


async def _load_binance(
    *,
    asset: str,
    timeframe: str,
    interval_seconds: int,
    start: datetime,
    as_of: datetime,
    adapter_factory: Callable[[], Any],
) -> tuple[ConfirmedOHLCVFrame, dict[str, Any]]:
    adapter = adapter_factory()
    interval_ms = interval_seconds * 1_000
    current_start_ms = int(start.timestamp() * 1_000)
    as_of_ms = int(as_of.timestamp() * 1_000)
    pages: list[pd.DataFrame] = []
    page_requests: list[dict[str, Any]] = []
    previous_last_open: int | None = None
    for page_number in range(1, MAX_BINANCE_PAGES + 1):
        if current_start_ms > as_of_ms:
            break
        page_requests.append(
            {
                "since": current_start_ms,
                "until": as_of_ms,
                "limit": BINANCE_PAGE_LIMIT,
            }
        )
        try:
            page = await adapter.get_historical_ohlcv(
                asset,
                timeframe,
                since=current_start_ms,
                until=as_of_ms,
                limit=BINANCE_PAGE_LIMIT,
                include_close_time=True,
            )
        except Exception as exc:
            raise ViewerRunnerError("Binance page failed; no retry performed") from exc
        if not isinstance(page, pd.DataFrame) or page.empty:
            break
        page = page.copy(deep=True)
        if len(page) > BINANCE_PAGE_LIMIT:
            raise ViewerRunnerError("Binance page exceeds requested limit")
        opens = _page_integer(page, column="timestamp").to_numpy(dtype="int64")
        closes = _page_integer(page, column="close_time").to_numpy(dtype="int64")
        if len(opens) == 0:
            break
        if int(opens[0]) != current_start_ms:
            raise ViewerRunnerError("Binance page starts at unexpected timestamp")
        page_timestamps = pd.to_datetime(opens, unit="ms", utc=True, errors="raise")
        if not page_timestamps.is_monotonic_increasing or not page_timestamps.is_unique:
            raise ViewerRunnerError("Binance page timestamps are not strictly increasing")
        if any(int(open_time) % interval_ms for open_time in opens):
            raise ViewerRunnerError("Binance page timestamps are not timeframe aligned")
        if len(opens) > 1 and any(
            int(next_open) - int(open_time) != interval_ms
            for open_time, next_open in zip(opens, opens[1:])
        ):
            raise ViewerRunnerError("Binance page timestamps contain a gap or duplicate")
        if any(
            int(close_time) != int(open_time) + interval_ms - 1
            for open_time, close_time in zip(opens, closes)
        ):
            raise ViewerRunnerError("Binance close times are not exact")
        if int(opens[-1]) > as_of_ms:
            raise ViewerRunnerError("Binance page exceeds requested until boundary")
        if previous_last_open is not None and opens[0] != previous_last_open + interval_ms:
            raise ViewerRunnerError("Binance pages overlap or contain a gap")
        page["timestamp"] = opens
        page["close_time"] = closes
        pages.append(page)
        previous_last_open = int(opens[-1])
        current_start_ms = previous_last_open + interval_ms
        if len(page) < BINANCE_PAGE_LIMIT:
            break
    else:
        raise ViewerRunnerError("Binance pagination exceeded maximum page count")
    if not pages:
        raise ViewerRunnerError("Binance returned no candles")
    combined = pd.concat(pages, ignore_index=True)
    combined_timestamps = pd.to_datetime(combined["timestamp"], unit="ms", utc=True)
    combined_close_times = pd.to_datetime(combined["close_time"], unit="ms", utc=True)
    normalized, last_close = _causal_frame_from_raw(
        combined,
        timestamps=pd.DatetimeIndex(combined_timestamps),
        asset=asset,
        timeframe=timeframe,
        interval_seconds=interval_seconds,
        start=start,
        as_of=as_of,
        close_times=pd.DatetimeIndex(combined_close_times),
        exchange_close_time=True,
    )
    frame = ConfirmedOHLCVFrame.from_frame(
        normalized,
        asset=asset,
        timeframe=timeframe,
        observed_at=as_of,
        confirmed_through=as_of,
    )
    request_identity = _binance_request_identity(
        asset=asset,
        timeframe=timeframe,
        start=start,
        as_of=as_of,
        pages=page_requests,
    )
    return frame, {
        "source_type": "binance",
        "source_file_sha256": None,
        "binance_request_identity": request_identity,
        "page_count": len(page_requests),
        "request_pages": page_requests,
        "display_path": None,
        "last_candle_close": last_close,
    }


def _normalized_input_payload(input_data: ProviderInput) -> dict[str, Any]:
    payload = input_data.to_dict()
    payload.pop("input_identity", None)
    return payload


def _binance_request_identity(
    *,
    asset: str,
    timeframe: str,
    start: datetime,
    as_of: datetime,
    pages: list[dict[str, Any]],
) -> str:
    return deterministic_hash(
        "trendline_v2_generic_viewer_binance_request",
        {
            "asset": asset,
            "timeframe": timeframe,
            "start": _iso(start),
            "as_of": _iso(as_of),
            "page_limit": BINANCE_PAGE_LIMIT,
            "pages": pages,
        },
    )


def _causal_source_sha256(input_data: ProviderInput) -> str:
    rows = [
        {
            "timestamp": timestamp,
            "open": open_value,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
        for timestamp, open_value, high, low, close, volume in zip(
            input_data.timestamps,
            input_data.open,
            input_data.high,
            input_data.low,
            input_data.close,
            input_data.volume,
        )
    ]
    return _sha256(_canonical_json_bytes({"columns": SOURCE_COLUMNS, "rows": rows}))


def _source_binding(
    input_data: ProviderInput,
    *,
    asset: str,
    timeframe: str,
    interval_seconds: int,
    start: datetime | None,
    as_of: datetime,
    source_info: Mapping[str, Any],
) -> dict[str, Any]:
    first_open = datetime.fromtimestamp(input_data.timestamps[0] / 1_000_000_000, tz=UTC)
    last_open = datetime.fromtimestamp(input_data.timestamps[-1] / 1_000_000_000, tz=UTC)
    semantic: dict[str, Any] = {
        "schema_version": SOURCE_BINDING_SCHEMA_VERSION,
        "source_type": source_info["source_type"],
        "asset": asset,
        "timeframe": timeframe,
        "interval_seconds": interval_seconds,
        "start": _iso(start) if start is not None else None,
        "as_of": _iso(as_of),
        "source_file_sha256": (
            _causal_source_sha256(input_data)
            if source_info["source_type"] == "csv"
            else None
        ),
        "binance_request_identity": source_info["binance_request_identity"],
        "page_count": source_info["page_count"],
        "request_pages": source_info["request_pages"],
        "normalized_input_sha256": _sha256(
            _canonical_json_bytes(_normalized_input_payload(input_data))
        ),
        "row_count": input_data.row_count,
        "first_candle_open": _iso(first_open),
        "last_candle_open": _iso(last_open),
        "last_candle_close": _iso(source_info["last_candle_close"]),
        "frame_input_identity": input_data.input_identity,
    }
    return {
        **semantic,
        "source_binding_id": deterministic_hash(
            SOURCE_BINDING_SCHEMA_VERSION,
            semantic,
        ),
    }


def _provider_result_id(result_dict: Mapping[str, Any]) -> str:
    return deterministic_hash("trendline_v2_generic_viewer_provider_result", dict(result_dict))


def _run_id(report_payload: Mapping[str, Any]) -> str:
    semantic = {
        key: report_payload[key]
        for key in (
            "schema_version",
            "source_binding_id",
            "provider_result_id",
            "provider_status",
            "provider_reason",
            "input_identity",
            "request_identity",
            "config_identity",
            "viewer_payload_id",
            "viewer_bundle_id",
            "candidate_count",
        )
    }
    return deterministic_hash(VIEWER_RUN_SCHEMA_VERSION, semantic)


def _git_identity() -> tuple[str, str]:
    try:
        commit = subprocess.check_output(
            ("git", "rev-parse", "HEAD"), text=True, stderr=subprocess.DEVNULL
        ).strip()
        branch = subprocess.check_output(
            ("git", "branch", "--show-current"), text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ViewerRunnerError("cannot determine git commit and branch") from exc
    return commit, branch


def _write_json(path: Path, value: object) -> None:
    data = _canonical_json_bytes(value)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _prepare_staging(output: Path) -> Path:
    if output.is_symlink():
        raise ViewerRunnerError("output must not be a symlink")
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise ViewerRunnerError("output must be absent or empty")
        output.rmdir()
    output.parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))


def _status_value(value: object) -> str | None:
    return value.value if hasattr(value, "value") else value  # type: ignore[return-value]


def _http_smoke(bundle_path: Path) -> dict[str, int]:
    server = make_server(bundle_path, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    expected_paths = {
        "/bundle/chart_payload.json": 200,
        "/manifest.json": 404,
    }
    actual: dict[str, int] = {}
    try:
        for path, expected in expected_paths.items():
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                actual[path] = response.status
                response.read()
            finally:
                connection.close()
            if actual[path] != expected:
                raise ViewerRunnerError(f"HTTP smoke mismatch for {path}")
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()
    return actual


def _manual_serve_command(bundle_path: Path) -> str:
    return (
        "PYTHONPATH=src .venv/bin/python -m "
        "libs.models.trendline_v2.tools.viewer.server "
        f"--bundle {bundle_path} --port 8765"
    )


def _build_report(
    *,
    source_binding: Mapping[str, Any],
    source_info: Mapping[str, Any],
    source_display_path: str | None,
    result: ProviderResult,
    provider_result_dict: Mapping[str, Any],
    provider_result_sha256: str,
    viewer_payload: Mapping[str, Any],
    viewer_payload_sha256: str,
    viewer_manifest: Mapping[str, Any],
    viewer_manifest_sha256: str,
    http_smoke: Mapping[str, int],
    viewer_bundle_path: Path,
) -> dict[str, Any]:
    candidate_count = len(result.candidates)
    report: dict[str, Any] = {
        "schema_version": VIEWER_RUN_SCHEMA_VERSION,
        "source_binding_id": source_binding["source_binding_id"],
        "source_type": source_info["source_type"],
        "source_display_path": source_display_path,
        "asset": result.request.asset,
        "timeframe": result.request.timeframe,
        "interval_seconds": source_binding["interval_seconds"],
        "start": source_binding["start"],
        "as_of": source_binding["as_of"],
        "page_count": source_info["page_count"],
        "request_pages": source_info["request_pages"],
        "git_commit": _git_identity()[0],
        "git_branch": _git_identity()[1],
        "provider_status": result.status.value,
        "provider_reason": _status_value(result.reason),
        "provider_result_id": _provider_result_id(provider_result_dict),
        "provider_result_sha256": provider_result_sha256,
        "candidate_count": candidate_count,
        "support_count": sum(candidate.role.value == "support" for candidate in result.candidates),
        "resistance_count": sum(
            candidate.role.value == "resistance" for candidate in result.candidates
        ),
        "viewer_status": (
            "VIEWER_READY_WITH_LINES" if result.status is ProviderStatus.SUCCESS else "VIEWER_READY_NO_LINES"
        ),
        "provider_configuration": result.request.provider_config.to_dict(),
        "provider_config_identity": result.request.provider_config_identity,
        "foundation_config": result.request.config.to_dict(),
        "foundation_config_identity": result.request.config.semantic_hash,
        "config_identity": result.request.config_identity,
        "input_identity": result.request.input_identity,
        "request_identity": result.request.request_identity,
        "provider_identity": result.provider_identity,
        "provider_contract_identity": result.provider_contract_identity,
        "viewer_payload_id": viewer_payload["payload_id"],
        "viewer_payload_sha256": viewer_payload_sha256,
        "viewer_bundle_id": viewer_manifest["bundle_id"],
        "viewer_manifest_sha256": viewer_manifest_sha256,
        "source_binding_sha256": _sha256(
            _canonical_json_bytes(source_binding)
        ),
        "member_hashes": {
            "source_binding.json": _sha256(_canonical_json_bytes(source_binding)),
            "provider_result.json": provider_result_sha256,
            "viewer_bundle/chart_payload.json": viewer_payload_sha256,
            "viewer_bundle/manifest.json": viewer_manifest_sha256,
        },
        "http_smoke": dict(http_smoke),
        "manual_serve_command": _manual_serve_command(viewer_bundle_path),
    }
    report["run_id"] = _run_id(report)
    return report


def _load_json(path: Path) -> tuple[dict[str, Any], bytes]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ViewerRunnerError(f"duplicate JSON key in {path.name}: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ViewerRunnerError(f"non-finite JSON constant in {path.name}: {value}")

    try:
        data = path.read_bytes()
        parsed = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ViewerRunnerError(f"invalid JSON file: {path}") from exc
    if not isinstance(parsed, dict):
        raise ViewerRunnerError(f"JSON file must contain an object: {path.name}")
    if data != _canonical_json_bytes(parsed):
        raise ViewerRunnerError(f"{path.name} is not canonical JSON")
    return parsed, data


def _expect_keys(value: Mapping[str, Any], expected: set[str], *, name: str) -> None:
    if set(value) != expected:
        raise ViewerRunnerError(f"{name} keys mismatch")


def _provider_result_from_dict(value: Mapping[str, Any]) -> ProviderResult:
    _expect_keys(value, set(_PROVIDER_RESULT_KEYS), name="provider_result")
    request_payload = value["request"]
    if not isinstance(request_payload, Mapping):
        raise ViewerRunnerError("provider_result.request is invalid")
    request_keys = {
        "input_data",
        "config",
        "input_identity",
        "config_identity",
        "provider_config",
        "provider_config_identity",
        "request_identity",
    }
    _expect_keys(request_payload, request_keys, name="provider_result.request")
    input_payload = request_payload["input_data"]
    if not isinstance(input_payload, Mapping):
        raise ViewerRunnerError("provider_result input_data is invalid")
    input_keys = {
        "asset",
        "timeframe",
        "observed_at",
        "confirmed_through",
        "timestamps",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "input_identity",
    }
    _expect_keys(input_payload, input_keys, name="provider_result.input_data")
    try:
        input_data = ProviderInput(
            asset=input_payload["asset"],
            timeframe=input_payload["timeframe"],
            observed_at=parse_utc_isoformat(input_payload["observed_at"]),
            confirmed_through=parse_utc_isoformat(input_payload["confirmed_through"]),
            timestamps=tuple(input_payload["timestamps"]),
            open=tuple(input_payload["open"]),
            high=tuple(input_payload["high"]),
            low=tuple(input_payload["low"]),
            close=tuple(input_payload["close"]),
            volume=tuple(input_payload["volume"]),
        )
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise ViewerRunnerError("provider_result input_data is invalid") from exc
    if input_data.input_identity != input_payload["input_identity"]:
        raise ViewerRunnerError("provider_result input identity mismatch")

    config_payload = request_payload["config"]
    provider_config_payload = request_payload["provider_config"]
    if not isinstance(config_payload, Mapping) or not isinstance(provider_config_payload, Mapping):
        raise ViewerRunnerError("provider_result configuration is invalid")
    try:
        model = config_payload["model"]
        foundation = ResolvedTrendlineV2Config(
            model_name=model["name"],
            model_version=model["version"],
            schema_version=model["schema_version"],
            provenance=config_payload["provenance"],
        )
        provider_config = ConfirmedExtremaPairConfig(
            **provider_config_payload["active_config"]
        )
    except (KeyError, TypeError, ContractValidationError) as exc:
        raise ViewerRunnerError("provider_result configuration is invalid") from exc
    if foundation.to_dict() != dict(config_payload):
        raise ViewerRunnerError("provider_result foundation configuration mismatch")
    if provider_config.to_dict() != dict(provider_config_payload):
        raise ViewerRunnerError("provider_result provider configuration mismatch")
    try:
        request = ProviderRequest(
            input_data=input_data,
            config=foundation,
            provider_config=provider_config,
        )
    except ContractValidationError as exc:
        raise ViewerRunnerError("provider_result request is invalid") from exc
    if request.to_dict() != dict(request_payload):
        raise ViewerRunnerError("provider_result request identity mismatch")

    candidates_payload = value["candidates"]
    evidence_payload = value["evidence"]
    diagnostics_payload = value["diagnostics"]
    if not isinstance(candidates_payload, list) or not isinstance(evidence_payload, list):
        raise ViewerRunnerError("provider_result candidates/evidence are invalid")
    if not isinstance(diagnostics_payload, Mapping):
        raise ViewerRunnerError("provider_result diagnostics are invalid")
    try:
        result = ProviderResult(
            provider_name=value["provider_name"],
            provider_version=value["provider_version"],
            request=request,
            status=value["status"],
            candidates=tuple(LineCandidate.from_dict(item) for item in candidates_payload),
            evidence=tuple(
                ConfirmedExtremaPairEvidence.from_dict(item) for item in evidence_payload
            ),
            diagnostics=ProviderDiagnostics(**diagnostics_payload),
            reason=value["reason"],
            detail=value["detail"],
        )
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise ViewerRunnerError("provider_result contract is invalid") from exc
    if _canonical_json_bytes(result.to_dict()) != _canonical_json_bytes(value):
        raise ViewerRunnerError("provider_result semantic content mismatch")
    if value["provider_identity"] != result.provider_identity:
        raise ViewerRunnerError("provider identity mismatch")
    if value["provider_contract_identity"] != result.provider_contract_identity:
        raise ViewerRunnerError("provider contract identity mismatch")
    return result


def _validate_source_binding(
    binding: Mapping[str, Any],
    *,
    result: ProviderResult,
    interval_seconds: int,
) -> None:
    expected_keys = {
        "schema_version",
        "source_binding_id",
        "source_type",
        "asset",
        "timeframe",
        "interval_seconds",
        "start",
        "as_of",
        "source_file_sha256",
        "binance_request_identity",
        "page_count",
        "request_pages",
        "normalized_input_sha256",
        "row_count",
        "first_candle_open",
        "last_candle_open",
        "last_candle_close",
        "frame_input_identity",
    }
    _expect_keys(binding, expected_keys, name="source_binding")
    if binding["schema_version"] != SOURCE_BINDING_SCHEMA_VERSION:
        raise ViewerRunnerError("unsupported source binding schema")
    if not isinstance(binding["source_type"], str) or binding["source_type"] not in {
        "csv",
        "binance",
    }:
        raise ViewerRunnerError("invalid source type")
    if binding["asset"] != result.request.asset or binding["timeframe"] != result.request.timeframe:
        raise ViewerRunnerError("source binding market identity mismatch")
    if type(binding["interval_seconds"]) is not int or binding["interval_seconds"] != interval_seconds:
        raise ViewerRunnerError("source binding timeframe cadence mismatch")
    binding_as_of = _parse_datetime(binding["as_of"], field_name="source binding as-of")
    if binding_as_of != result.request.observed_at:
        raise ViewerRunnerError("source binding as-of mismatch")
    start = (
        None
        if binding["start"] is None
        else _parse_datetime(binding["start"], field_name="source binding start")
    )
    if binding["frame_input_identity"] != result.request.input_identity:
        raise ViewerRunnerError("source binding input identity mismatch")
    if type(binding["row_count"]) is not int or binding["row_count"] <= 0:
        raise ViewerRunnerError("source binding row count is invalid")
    if binding["row_count"] != result.request.input_data.row_count:
        raise ViewerRunnerError("source binding row count mismatch")
    if not _is_sha256(binding["normalized_input_sha256"]):
        raise ViewerRunnerError("source binding normalized input hash is invalid")
    expected_normalized_hash = _sha256(
        _canonical_json_bytes(_normalized_input_payload(result.request.input_data))
    )
    if binding["normalized_input_sha256"] != expected_normalized_hash:
        raise ViewerRunnerError("source binding normalized input hash mismatch")
    if binding["source_type"] == "csv":
        if not _is_sha256(binding["source_file_sha256"]):
            raise ViewerRunnerError("source binding CSV hash is invalid")
        if binding["source_file_sha256"] != _causal_source_sha256(result.request.input_data):
            raise ViewerRunnerError("source binding CSV hash mismatch")
        if binding["binance_request_identity"] is not None:
            raise ViewerRunnerError("CSV source cannot carry Binance identity")
        if binding["page_count"] != 0 or binding["request_pages"] != []:
            raise ViewerRunnerError("CSV source cannot carry Binance pages")
    else:
        if not _is_sha256(binding["binance_request_identity"]):
            raise ViewerRunnerError("Binance request identity is invalid")
        if binding["source_file_sha256"] is not None:
            raise ViewerRunnerError("Binance source cannot carry CSV hash")
        if start is None:
            raise ViewerRunnerError("Binance source requires a start boundary")
    if type(binding["page_count"]) is not int or binding["page_count"] < 0:
        raise ViewerRunnerError("source binding page count is invalid")
    if not isinstance(binding["request_pages"], list):
        raise ViewerRunnerError("source binding request pages are invalid")
    if len(binding["request_pages"]) != binding["page_count"]:
        raise ViewerRunnerError("source binding page count mismatch")
    timestamps = result.request.input_data.timestamps
    first_open = datetime.fromtimestamp(timestamps[0] / 1_000_000_000, tz=UTC)
    last_open = datetime.fromtimestamp(timestamps[-1] / 1_000_000_000, tz=UTC)
    if start is not None and first_open < start:
        raise ViewerRunnerError("source binding start precedes first candle")
    if binding["first_candle_open"] != _iso(first_open):
        raise ViewerRunnerError("source binding first candle mismatch")
    if binding["last_candle_open"] != _iso(last_open):
        raise ViewerRunnerError("source binding last candle mismatch")
    expected_last_close = last_open + timedelta(seconds=interval_seconds)
    if binding["source_type"] == "binance":
        expected_last_close -= timedelta(milliseconds=1)
        pages = binding["request_pages"]
        if not pages:
            raise ViewerRunnerError("Binance source requires request pages")
        if binding["page_count"] > MAX_BINANCE_PAGES:
            raise ViewerRunnerError("Binance request page count exceeds maximum")
        minimum_rows = (binding["page_count"] - 1) * BINANCE_PAGE_LIMIT
        maximum_rows = binding["page_count"] * BINANCE_PAGE_LIMIT
        if not minimum_rows <= binding["row_count"] <= maximum_rows:
            raise ViewerRunnerError("Binance row count does not match page count")
        start_ms = int(start.timestamp() * 1_000)
        interval_ms = interval_seconds * 1_000
        until_ms = int(binding_as_of.timestamp() * 1_000)
        for page_index, page in enumerate(pages):
            if not isinstance(page, Mapping):
                raise ViewerRunnerError("Binance request page is invalid")
            _expect_keys(page, {"since", "until", "limit"}, name="Binance request page")
            if any(type(page[key]) is not int for key in ("since", "until", "limit")):
                raise ViewerRunnerError("Binance request page values are invalid")
            if page["limit"] != BINANCE_PAGE_LIMIT:
                raise ViewerRunnerError("Binance request page limit mismatch")
            if page["until"] != int(binding_as_of.timestamp() * 1_000):
                raise ViewerRunnerError("Binance request page boundary mismatch")
            expected_since = start_ms + page_index * BINANCE_PAGE_LIMIT * interval_ms
            if page["since"] != expected_since:
                raise ViewerRunnerError("Binance request page sequence mismatch")
            if page["since"] > until_ms:
                raise ViewerRunnerError("Binance request page starts after until")
            if page["since"] % interval_ms:
                raise ViewerRunnerError("Binance request page alignment mismatch")
        if pages[0]["since"] != int(start.timestamp() * 1_000):
            raise ViewerRunnerError("Binance request start mismatch")
        expected_request_identity = _binance_request_identity(
            asset=result.request.asset,
            timeframe=result.request.timeframe,
            start=start,
            as_of=binding_as_of,
            pages=[dict(page) for page in pages],
        )
        if binding["binance_request_identity"] != expected_request_identity:
            raise ViewerRunnerError("Binance request identity mismatch")
    if binding["last_candle_close"] != _iso(expected_last_close):
        raise ViewerRunnerError("source binding last candle close mismatch")
    if expected_last_close > binding_as_of:
        raise ViewerRunnerError("source binding last candle exceeds as-of")
    if not _is_sha256(binding["source_binding_id"]):
        raise ViewerRunnerError("source binding ID is invalid")
    semantic = dict(binding)
    semantic.pop("source_binding_id")
    if deterministic_hash(SOURCE_BINDING_SCHEMA_VERSION, semantic) != binding["source_binding_id"]:
        raise ViewerRunnerError("source binding ID mismatch")


def _verify_report(
    report: Mapping[str, Any],
    *,
    source_binding: Mapping[str, Any],
    source_binding_sha256: str,
    provider_result: ProviderResult,
    provider_result_sha256: str,
    payload: Mapping[str, Any],
    payload_sha256: str,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    output: Path,
) -> None:
    required = {
        "schema_version",
        "run_id",
        "source_binding_id",
        "source_type",
        "source_display_path",
        "asset",
        "timeframe",
        "interval_seconds",
        "start",
        "as_of",
        "page_count",
        "request_pages",
        "git_commit",
        "git_branch",
        "provider_status",
        "provider_reason",
        "provider_result_id",
        "provider_result_sha256",
        "candidate_count",
        "support_count",
        "resistance_count",
        "viewer_status",
        "provider_configuration",
        "provider_config_identity",
        "foundation_config",
        "foundation_config_identity",
        "config_identity",
        "input_identity",
        "request_identity",
        "provider_identity",
        "provider_contract_identity",
        "viewer_payload_id",
        "viewer_payload_sha256",
        "viewer_bundle_id",
        "viewer_manifest_sha256",
        "source_binding_sha256",
        "member_hashes",
        "http_smoke",
        "manual_serve_command",
    }
    _expect_keys(report, required, name="run_report")
    if report["schema_version"] != VIEWER_RUN_SCHEMA_VERSION:
        raise ViewerRunnerError("unsupported run report schema")
    if report["source_binding_id"] != source_binding["source_binding_id"]:
        raise ViewerRunnerError("run report source binding mismatch")
    if report["source_binding_sha256"] != source_binding_sha256:
        raise ViewerRunnerError("run report source binding hash mismatch")
    for field_name in (
        "source_type",
        "interval_seconds",
        "start",
        "as_of",
        "page_count",
        "request_pages",
    ):
        if report[field_name] != source_binding[field_name]:
            raise ViewerRunnerError(f"run report {field_name} mismatch")
    if report["source_type"] == "csv" and not isinstance(report["source_display_path"], str):
        raise ViewerRunnerError("CSV run report display path is invalid")
    if report["source_type"] == "binance" and report["source_display_path"] is not None:
        raise ViewerRunnerError("Binance run report display path is invalid")
    if report["provider_result_sha256"] != provider_result_sha256:
        raise ViewerRunnerError("run report provider result hash mismatch")
    if report["provider_result_id"] != _provider_result_id(provider_result.to_dict()):
        raise ViewerRunnerError("run report provider result ID mismatch")
    if report["asset"] != provider_result.request.asset or report["timeframe"] != provider_result.request.timeframe:
        raise ViewerRunnerError("run report market identity mismatch")
    if report["provider_status"] != provider_result.status.value:
        raise ViewerRunnerError("run report provider status mismatch")
    if report["provider_reason"] != _status_value(provider_result.reason):
        raise ViewerRunnerError("run report provider reason mismatch")
    if report["candidate_count"] != len(provider_result.candidates):
        raise ViewerRunnerError("run report candidate count mismatch")
    if report["support_count"] != sum(c.role.value == "support" for c in provider_result.candidates):
        raise ViewerRunnerError("run report support count mismatch")
    if report["resistance_count"] != sum(c.role.value == "resistance" for c in provider_result.candidates):
        raise ViewerRunnerError("run report resistance count mismatch")
    if report["input_identity"] != provider_result.request.input_identity:
        raise ViewerRunnerError("run report input identity mismatch")
    if report["request_identity"] != provider_result.request.request_identity:
        raise ViewerRunnerError("run report request identity mismatch")
    if report["config_identity"] != provider_result.request.config_identity:
        raise ViewerRunnerError("run report config identity mismatch")
    if report["provider_identity"] != provider_result.provider_identity:
        raise ViewerRunnerError("run report provider identity mismatch")
    if report["provider_contract_identity"] != provider_result.provider_contract_identity:
        raise ViewerRunnerError("run report provider contract identity mismatch")
    if report["provider_configuration"] != provider_result.request.provider_config.to_dict():
        raise ViewerRunnerError("run report provider configuration mismatch")
    if report["provider_config_identity"] != provider_result.request.provider_config_identity:
        raise ViewerRunnerError("run report provider configuration identity mismatch")
    if report["foundation_config"] != provider_result.request.config.to_dict():
        raise ViewerRunnerError("run report foundation configuration mismatch")
    if report["foundation_config_identity"] != provider_result.request.config.semantic_hash:
        raise ViewerRunnerError("run report foundation configuration identity mismatch")
    if report["viewer_payload_id"] != payload["payload_id"]:
        raise ViewerRunnerError("run report viewer payload mismatch")
    if report["viewer_payload_sha256"] != payload_sha256:
        raise ViewerRunnerError("run report viewer payload hash mismatch")
    if report["viewer_bundle_id"] != manifest["bundle_id"]:
        raise ViewerRunnerError("run report viewer bundle mismatch")
    if report["viewer_manifest_sha256"] != manifest_sha256:
        raise ViewerRunnerError("run report viewer manifest hash mismatch")
    member_hashes = report["member_hashes"]
    expected_members = {
        "source_binding.json": source_binding_sha256,
        "provider_result.json": provider_result_sha256,
        "viewer_bundle/chart_payload.json": payload_sha256,
        "viewer_bundle/manifest.json": manifest_sha256,
    }
    if member_hashes != expected_members:
        raise ViewerRunnerError("run report member hashes mismatch")
    if report["http_smoke"] != {
        "/bundle/chart_payload.json": 200,
        "/manifest.json": 404,
    }:
        raise ViewerRunnerError("run report HTTP smoke mismatch")
    if report["viewer_status"] != (
        "VIEWER_READY_WITH_LINES"
        if provider_result.status is ProviderStatus.SUCCESS
        else "VIEWER_READY_NO_LINES"
    ):
        raise ViewerRunnerError("run report viewer status mismatch")
    if _run_id(report) != report["run_id"]:
        raise ViewerRunnerError("run report ID mismatch")
    if (
        not isinstance(report["manual_serve_command"], str)
        or "viewer.server" not in report["manual_serve_command"]
        or "--port 8765" not in report["manual_serve_command"]
    ):
        raise ViewerRunnerError("run report serve command is invalid")


def verify_output(output: str | Path) -> dict[str, Any]:
    """Verify one published five-file runner output without source access."""

    root = Path(output)
    if root.is_symlink() or not root.is_dir():
        raise ViewerRunnerError("output must be a real directory")
    names = {entry.name for entry in root.iterdir()}
    if names != _OUTPUT_MEMBERS:
        raise ViewerRunnerError("output contains unexpected files")
    bundle = root / "viewer_bundle"
    if bundle.is_symlink() or not bundle.is_dir() or {p.name for p in bundle.iterdir()} != _BUNDLE_MEMBERS:
        raise ViewerRunnerError("viewer bundle members mismatch")
    source_binding, source_bytes = _load_json(root / "source_binding.json")
    provider_dict, provider_bytes = _load_json(root / "provider_result.json")
    report, _ = _load_json(root / "run_report.json")
    try:
        result = _provider_result_from_dict(provider_dict)
    except ViewerRunnerError:
        raise
    interval = timeframe_interval_seconds(result.request.timeframe)
    _validate_source_binding(source_binding, result=result, interval_seconds=interval)
    if _sha256(provider_bytes) != report.get("provider_result_sha256"):
        raise ViewerRunnerError("provider result file hash mismatch")
    manifest = validate_bundle(bundle)
    payload, payload_bytes = _load_json(bundle / "chart_payload.json")
    manifest_dict, manifest_bytes = _load_json(bundle / "manifest.json")
    if manifest != manifest_dict:
        raise ViewerRunnerError("viewer manifest reload mismatch")
    if _sha256(payload_bytes) != report.get("viewer_payload_sha256"):
        raise ViewerRunnerError("viewer payload file hash mismatch")
    if _sha256(manifest_bytes) != report.get("viewer_manifest_sha256"):
        raise ViewerRunnerError("viewer manifest file hash mismatch")
    for field_name, expected in (
        ("asset", result.request.asset),
        ("timeframe", result.request.timeframe),
        ("input_identity", result.request.input_identity),
        ("request_identity", result.request.request_identity),
        ("config_identity", result.request.config_identity),
        ("provider_identity", result.provider_identity),
        ("provider_contract_identity", result.provider_contract_identity),
    ):
        if payload.get(field_name) != expected:
            raise ViewerRunnerError(f"viewer payload {field_name} mismatch")
    source_hash = _sha256(source_bytes)
    _verify_report(
        report,
        source_binding=source_binding,
        source_binding_sha256=source_hash,
        provider_result=result,
        provider_result_sha256=_sha256(provider_bytes),
        payload=payload,
        payload_sha256=_sha256(payload_bytes),
        manifest=manifest,
        manifest_sha256=_sha256(manifest_bytes),
        output=root,
    )
    return report


async def run_viewer(
    *,
    asset: str,
    timeframe: str,
    as_of: datetime | str,
    output: str | Path,
    input_csv: str | Path | None = None,
    source: str = "csv",
    start: datetime | str | None = None,
    adapter_factory: Callable[[], Any] = BinanceNativeAdapter,
) -> dict[str, Any]:
    """Generate one generic viewer output; network mode remains explicitly guarded."""

    asset = validate_asset(asset)
    interval_seconds = timeframe_interval_seconds(timeframe)
    as_of_value = _parse_datetime(as_of, field_name="as_of")
    start_value = (
        _parse_datetime(start, field_name="start") if start is not None else None
    )
    if start_value is not None and start_value > as_of_value:
        raise ViewerRunnerError("start cannot be after as_of")
    if source not in {"csv", "binance"}:
        raise ViewerRunnerError("source must be csv or binance")
    if source == "csv" and input_csv is None:
        raise ViewerRunnerError("--input-csv is required for CSV source")
    if source == "binance":
        if input_csv is not None:
            raise ViewerRunnerError("--input-csv cannot be used with Binance source")
        if start_value is None:
            raise ViewerRunnerError("start is required for Binance source")
        if os.environ.get(FETCH_ENVIRONMENT_VARIABLE) != "1":
            raise ViewerRunnerError(
                f"Binance source requires {FETCH_ENVIRONMENT_VARIABLE}=1"
            )
    destination = Path(output)
    staging = _prepare_staging(destination)
    try:
        if source == "csv":
            frame, source_info = _load_csv(
                Path(input_csv),
                asset=asset,
                timeframe=timeframe,
                interval_seconds=interval_seconds,
                start=start_value,
                as_of=as_of_value,
            )
        else:
            frame, source_info = await _load_binance(
                asset=asset,
                timeframe=timeframe,
                interval_seconds=interval_seconds,
                start=start_value,
                as_of=as_of_value,
                adapter_factory=adapter_factory,
            )
        foundation = foundation_config()
        provider_config = viewer_provider_config()
        result = discover_trendlines(
            frame,
            config=foundation,
            provider_config=provider_config,
        )
        provider_dict = result.to_dict()
        provider_bytes = _canonical_json_bytes(provider_dict)
        _write_json(staging / "provider_result.json", provider_dict)
        source_info = dict(source_info)
        source_info["source_file_sha256"] = (
            _causal_source_sha256(result.request.input_data)
            if source == "csv"
            else None
        )
        binding = _source_binding(
            result.request.input_data,
            asset=asset,
            timeframe=timeframe,
            interval_seconds=interval_seconds,
            start=start_value,
            as_of=as_of_value,
            source_info=source_info,
        )
        _write_json(staging / "source_binding.json", binding)
        viewer_path = staging / "viewer_bundle"
        write_viewer_bundle(result, viewer_path)
        validate_bundle(viewer_path)
        payload, payload_bytes = _load_json(viewer_path / "chart_payload.json")
        manifest, manifest_bytes = _load_json(viewer_path / "manifest.json")
        http_smoke = _http_smoke(viewer_path)
        report = _build_report(
            source_binding=binding,
            source_info=source_info,
            source_display_path=source_info["display_path"],
            result=result,
            provider_result_dict=provider_dict,
            provider_result_sha256=_sha256(provider_bytes),
            viewer_payload=payload,
            viewer_payload_sha256=_sha256(payload_bytes),
            viewer_manifest=manifest,
            viewer_manifest_sha256=_sha256(manifest_bytes),
            http_smoke=http_smoke,
            viewer_bundle_path=destination / "viewer_bundle",
        )
        _write_json(staging / "run_report.json", report)
        verify_output(staging)
        if destination.exists():
            if any(destination.iterdir()):
                raise ViewerRunnerError("output became non-empty during publication")
            destination.rmdir()
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return verify_output(destination)


def serve_viewer(output: str | Path, *, port: int = 8765) -> None:
    """Serve one verified output on fixed loopback host."""

    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
        raise ViewerRunnerError("port must be between 1 and 65535")
    bundle = Path(output) / "viewer_bundle"
    server = make_server(bundle, host="127.0.0.1", port=port)
    print(f"http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a generic Trendline V2 viewer")
    parser.add_argument("--asset")
    parser.add_argument("--timeframe")
    parser.add_argument("--input-csv", type=Path)
    parser.add_argument("--source", choices=("csv", "binance"), default=None)
    parser.add_argument("--start")
    parser.add_argument("--as-of")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--verify-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.verify_output is not None:
            if any(
                value is not None
                for value in (args.asset, args.timeframe, args.input_csv, args.start, args.as_of, args.output)
            ) or args.serve or args.source is not None or args.port is not None:
                raise ViewerRunnerError("--verify-output cannot be combined with run options")
            report = verify_output(args.verify_output)
            print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
            return 0
        if args.port is not None and not args.serve:
            raise ViewerRunnerError("--port requires --serve")
        if args.asset is None or args.timeframe is None or args.as_of is None or args.output is None:
            raise ViewerRunnerError("--asset, --timeframe, --as-of and --output are required")
        source = args.source or "csv"
        port = args.port if args.port is not None else 8765
        report = asyncio.run(
            run_viewer(
                asset=args.asset,
                timeframe=args.timeframe,
                input_csv=args.input_csv,
                source=source,
                start=args.start,
                as_of=args.as_of,
                output=args.output,
            )
        )
        print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
        if args.serve:
            serve_viewer(args.output, port=port)
        return 0
    except (ViewerRunnerError, OSError, ContractValidationError) as exc:
        print(f"ERROR: {exc}")
        return 2


__all__ = [
    "BINANCE_PAGE_LIMIT",
    "FETCH_ENVIRONMENT_VARIABLE",
    "FOUNDATION_CONFIG_INPUT",
    "MAX_BINANCE_PAGES",
    "PROVIDER_PROFILE_NAME",
    "SOURCE_BINDING_SCHEMA_VERSION",
    "VIEWER_PROVIDER_CONFIG_VALUES",
    "ViewerRunnerError",
    "build_parser",
    "foundation_config",
    "main",
    "run_viewer",
    "serve_viewer",
    "timeframe_interval_seconds",
    "validate_asset",
    "verify_output",
    "viewer_provider_config",
]
