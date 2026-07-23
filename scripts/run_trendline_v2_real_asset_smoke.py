"""Run the fixed Trendline V2 real-asset viewer smoke test."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from typing import Any, Callable

import pandas as pd

from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter
from apps.trendline_v2_viewer import write_viewer_bundle
from apps.trendline_v2_viewer.server import make_server, validate_bundle
from libs.models.trendline_v2 import discover_trendlines
from libs.models.trendline_v2.configuration import (
    ConfirmedExtremaPairConfig,
    resolve_trendline_v2_config,
)
from libs.models.trendline_v2.discovery import ProviderReason, ProviderResult, ProviderStatus
from libs.models.trendline_v2.input import ConfirmedOHLCVFrame


UTC = timezone.utc
ASSET = "BTCUSDT"
TIMEFRAME = "4h"
BAR_INTERVAL = timedelta(hours=4)
START_UTC = datetime(2025, 8, 1, tzinfo=UTC)
END_UTC = datetime(2025, 12, 1, tzinfo=UTC)
SUFFIX_START_UTC = datetime(2025, 10, 1, tzinfo=UTC)
REQUEST_LIMIT = 1000
EXPECTED_PRIMARY_ROWS = 732
EXPECTED_SUFFIX_ROWS = 366
DEFAULT_OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_real_asset_smoke/btcusdt_4h_20250801_20251201"
)
SOURCE_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
MODEL_COLUMNS = SOURCE_COLUMNS[1:]
FOUNDATION_CONFIG_INPUT = {
    "model": {
        "name": "trendline_v2",
        "version": "foundation_v1",
        "schema_version": 1,
    }
}
SMOKE_CONFIG_CLASSIFICATION = "SMOKE_ONLY / UNRESOLVED / NOT_PROMOTED / NOT_CANONICAL"
WORKLOAD_REASONS = frozenset(
    {
        ProviderReason.HYPOTHESIS_LIMIT_EXCEEDED,
        ProviderReason.OUTPUT_LIMIT_EXCEEDED,
    }
)


class SmokeBlocked(RuntimeError):
    """Fixed-scope run stopped without widening inputs or retries."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _epoch_milliseconds(value: datetime) -> int:
    return int(value.timestamp() * 1_000)


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


def _atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _canonical_json_bytes(value)
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _git_identity() -> tuple[str, str]:
    def run(*args: str) -> str:
        return subprocess.check_output(("git", *args), text=True).strip()

    return run("rev-parse", "HEAD"), run("branch", "--show-current")


def _validate_output_root(output_root: Path) -> None:
    if output_root.is_symlink():
        raise SmokeBlocked("BLOCKED_SOURCE_PREFLIGHT", "output root must not be a symlink")
    if output_root.exists():
        if not output_root.is_dir() or any(output_root.iterdir()):
            raise SmokeBlocked(
                "BLOCKED_SOURCE_PREFLIGHT",
                "output root must be absent or empty",
            )
    else:
        output_root.mkdir(parents=True)


def normalize_binance_ohlcv(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize one Binance response without filling, resampling, or deduping."""

    if not isinstance(raw, pd.DataFrame):
        raise SmokeBlocked("BLOCKED_SOURCE_PREFLIGHT", "adapter response must be a DataFrame")
    missing = [column for column in SOURCE_COLUMNS if column not in raw.columns]
    if missing:
        raise SmokeBlocked(
            "BLOCKED_SOURCE_PREFLIGHT",
            f"adapter response missing columns: {missing}",
        )
    timestamp_series = raw["timestamp"]
    if not pd.api.types.is_integer_dtype(timestamp_series):
        raise SmokeBlocked(
            "BLOCKED_SOURCE_PREFLIGHT",
            "adapter timestamps must use integer milliseconds",
        )
    try:
        timestamps = pd.to_datetime(
            timestamp_series.to_numpy(copy=True),
            unit="ms",
            utc=True,
            errors="raise",
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise SmokeBlocked(
            "BLOCKED_SOURCE_PREFLIGHT", "adapter timestamps are invalid"
        ) from exc
    if timestamps.isna().any():
        raise SmokeBlocked("BLOCKED_SOURCE_PREFLIGHT", "adapter timestamps contain NaT")
    if not timestamps.is_monotonic_increasing:
        raise SmokeBlocked("BLOCKED_SOURCE_PREFLIGHT", "adapter timestamps are not ordered")
    if not timestamps.is_unique:
        raise SmokeBlocked("BLOCKED_SOURCE_PREFLIGHT", "adapter timestamps are duplicated")

    normalized = pd.DataFrame(index=pd.DatetimeIndex(timestamps).tz_convert("UTC"))
    for column in MODEL_COLUMNS:
        converted = pd.to_numeric(raw[column], errors="coerce")
        if converted.isna().any():
            raise SmokeBlocked(
                "BLOCKED_SOURCE_PREFLIGHT",
                f"adapter column {column} contains missing/non-numeric values",
            )
        values = converted.to_numpy(dtype="float64", copy=True)
        if not all(math.isfinite(float(value)) for value in values):
            raise SmokeBlocked(
                "BLOCKED_SOURCE_PREFLIGHT",
                f"adapter column {column} contains non-finite values",
            )
        normalized[column] = values

    high = normalized["high"].to_numpy(dtype="float64")
    low = normalized["low"].to_numpy(dtype="float64")
    open_values = normalized["open"].to_numpy(dtype="float64")
    close = normalized["close"].to_numpy(dtype="float64")
    volume = normalized["volume"].to_numpy(dtype="float64")
    if (high < low).any() or (high < open_values).any() or (high < close).any():
        raise SmokeBlocked("BLOCKED_SOURCE_PREFLIGHT", "adapter response violates high bounds")
    if (low > open_values).any() or (low > close).any():
        raise SmokeBlocked("BLOCKED_SOURCE_PREFLIGHT", "adapter response violates low bounds")
    if (volume < 0).any():
        raise SmokeBlocked("BLOCKED_SOURCE_PREFLIGHT", "adapter response has negative volume")

    close_times = timestamps + pd.Timedelta(BAR_INTERVAL)
    confirmed = close_times <= pd.Timestamp(END_UTC)
    normalized = normalized.loc[confirmed].copy(deep=True)
    if normalized.empty:
        raise SmokeBlocked("BLOCKED_SOURCE_PREFLIGHT", "no closed bars in fixed window")
    if not normalized.index.is_monotonic_increasing or not normalized.index.is_unique:
        raise SmokeBlocked("BLOCKED_SOURCE_PREFLIGHT", "normalized timestamps are invalid")
    if len(normalized) != EXPECTED_PRIMARY_ROWS:
        raise SmokeBlocked(
            "BLOCKED_SOURCE_PREFLIGHT",
            f"expected {EXPECTED_PRIMARY_ROWS} confirmed rows, got {len(normalized)}",
        )
    expected_first = pd.Timestamp(START_UTC)
    expected_last = pd.Timestamp(END_UTC - BAR_INTERVAL)
    if normalized.index[0] != expected_first or normalized.index[-1] != expected_last:
        raise SmokeBlocked("BLOCKED_SOURCE_PREFLIGHT", "normalized boundaries are invalid")
    if not (normalized.index.to_series().diff().dropna() == pd.Timedelta(BAR_INTERVAL)).all():
        raise SmokeBlocked("BLOCKED_SOURCE_PREFLIGHT", "normalized timestamps contain a gap")
    return normalized.loc[:, MODEL_COLUMNS].astype("float64")


def build_confirmed_frame(normalized: pd.DataFrame, *, start: datetime = START_UTC) -> ConfirmedOHLCVFrame:
    """Build fixed-boundary model input from already normalized candles."""

    if start == START_UTC:
        expected_rows = EXPECTED_PRIMARY_ROWS
    elif start == SUFFIX_START_UTC:
        expected_rows = EXPECTED_SUFFIX_ROWS
    else:
        raise SmokeBlocked("BLOCKED_SOURCE_PREFLIGHT", "unsupported smoke window")
    if len(normalized) != expected_rows:
        raise SmokeBlocked(
            "BLOCKED_SOURCE_PREFLIGHT",
            f"expected {expected_rows} rows for smoke frame, got {len(normalized)}",
        )
    return ConfirmedOHLCVFrame.from_frame(
        normalized,
        asset=ASSET,
        timeframe=TIMEFRAME,
        observed_at=END_UTC,
        confirmed_through=END_UTC,
    )


def smoke_provider_config() -> ConfirmedExtremaPairConfig:
    return ConfirmedExtremaPairConfig(
        lookback_duration_seconds=10_540_800.0,
        left_confirmation_bars=1,
        right_confirmation_bars=1,
        min_extrema_per_role=2,
        max_hypotheses=100_000,
        max_output_candidates=10_000,
    )


def foundation_config():
    return resolve_trendline_v2_config(FOUNDATION_CONFIG_INPUT)


def _window_metadata(start: datetime, frame: ConfirmedOHLCVFrame) -> dict[str, object]:
    return {
        "start": _iso(start),
        "end": _iso(END_UTC),
        "row_count": frame.row_count,
        "observed_at": _iso(frame.observed_at),
        "confirmed_through": _iso(frame.confirmed_through),
    }


def _status_value(result: ProviderResult | None, field: str) -> object:
    if result is None:
        return None
    value = getattr(result, field)
    return value.value if hasattr(value, "value") else value


def _result_summary(result: ProviderResult | None) -> dict[str, object]:
    if result is None:
        return {
            "status": None,
            "reason": None,
            "candidate_count": None,
            "support_count": None,
            "resistance_count": None,
        }
    return {
        "status": _status_value(result, "status"),
        "reason": _status_value(result, "reason"),
        "candidate_count": len(result.candidates),
        "support_count": sum(candidate.role.value == "support" for candidate in result.candidates),
        "resistance_count": sum(
            candidate.role.value == "resistance" for candidate in result.candidates
        ),
    }


def should_use_workload_fallback(result: ProviderResult) -> bool:
    return result.status is ProviderStatus.ABSTAINED and result.reason in WORKLOAD_REASONS


def _http_smoke(bundle_path: Path, *, web_root: str | Path | None = None) -> dict[str, int]:
    server = make_server(bundle_path, host="127.0.0.1", port=0, web_root=web_root)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    expected = {
        "/": 200,
        "/styles.css": 200,
        "/dist/main.js": 200,
        "/vendor/lightweight-charts.mjs": 200,
        "/bundle/chart_payload.json": 200,
        "/node_modules/lightweight-charts/package.json": 404,
        "/manifest.json": 404,
        "/bundle/../manifest.json": 404,
    }
    actual: dict[str, int] = {}
    try:
        for path, expected_status in expected.items():
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                actual[path] = response.status
                response.read()
            finally:
                connection.close()
            if actual[path] != expected_status:
                raise SmokeBlocked(
                    "BLOCKED_REAL_ASSET_GEOMETRY",
                    f"HTTP smoke mismatch for {path}: {actual[path]} != {expected_status}",
                )
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()
    return actual


def _report(
    *,
    base_commit: str,
    branch: str,
    adapter: object,
    raw_row_count: int,
    normalized: pd.DataFrame,
    primary_frame: ConfirmedOHLCVFrame,
    primary: ProviderResult,
    primary_window: dict[str, object],
    fallback_frame: ConfirmedOHLCVFrame | None,
    fallback: ProviderResult | None,
    selected_frame: ConfirmedOHLCVFrame,
    selected: ProviderResult,
    viewer_bundle_path: Path,
    provider_result_sha256: str,
    viewer_payload: dict[str, object],
    viewer_manifest: dict[str, object],
    http_statuses: dict[str, int],
) -> dict[str, object]:
    selected_summary = _result_summary(selected)
    fallback_window = (
        _window_metadata(SUFFIX_START_UTC, fallback_frame)
        if fallback_frame is not None
        else None
    )
    return {
        "schema_version": "trendline_v2_real_asset_smoke_v1",
        "run_state": (
            "BLOCKED_REAL_ASSET_GEOMETRY"
            if fallback is not None
            and fallback.status is ProviderStatus.ABSTAINED
            and fallback.reason in WORKLOAD_REASONS
            else "READY_FOR_ORCHESTRATOR_REVIEW"
        ),
        "base_commit": base_commit,
        "branch": branch,
        "market": "binance_usd_m_futures",
        "adapter_identity": f"{type(adapter).__module__}.{type(adapter).__qualname__}",
        "asset": ASSET,
        "timeframe": TIMEFRAME,
        "request_start": _iso(START_UTC),
        "request_end": _iso(END_UTC),
        "request_limit": REQUEST_LIMIT,
        "network_request_count": 1,
        "raw_row_count": raw_row_count,
        "normalized_row_count": len(normalized),
        "normalized_first_timestamp": _iso(normalized.index[0].to_pydatetime()),
        "normalized_last_timestamp": _iso(normalized.index[-1].to_pydatetime()),
        "primary_window": primary_window,
        "primary_status": _status_value(primary, "status"),
        "primary_reason": _status_value(primary, "reason"),
        "primary_candidate_count": len(primary.candidates),
        "fallback_used": fallback is not None,
        "fallback_window": fallback_window,
        "fallback_status": _status_value(fallback, "status"),
        "fallback_reason": _status_value(fallback, "reason"),
        "fallback_candidate_count": len(fallback.candidates) if fallback else None,
        "selected_window": _window_metadata(
            SUFFIX_START_UTC if fallback is not None else START_UTC,
            selected_frame,
        ),
        "smoke_only_provider_config": smoke_provider_config().to_dict(),
        "provider_config_classification": SMOKE_CONFIG_CLASSIFICATION,
        "frame_input_identity": selected_frame.input_identity,
        "provider_input_identity": selected.request.input_identity,
        "config_identity": selected.request.config_identity,
        "request_identity": selected.request.request_identity,
        "provider_identity": selected.provider_identity,
        "provider_contract_identity": selected.provider_contract_identity,
        "snapshot_id": selected.to_snapshot().snapshot_id,
        "provider_result_sha256": provider_result_sha256,
        "viewer_payload_id": viewer_payload["payload_id"],
        "viewer_bundle_id": viewer_manifest["bundle_id"],
        "viewer_bundle_path": str(viewer_bundle_path),
        "chart_has_candidates": bool(selected.candidates),
        "support_candidate_count": selected_summary["support_count"],
        "resistance_candidate_count": selected_summary["resistance_count"],
        "http_statuses": http_statuses,
        "limitations": [
            "engineering and qualitative smoke only",
            "provider configuration is smoke-only and not canonical",
            "no parameter, trading, predictive, production, or cross-asset claim",
        ],
        "primary_frame_input_identity": primary_frame.input_identity,
    }


async def run_smoke(
    *,
    adapter: Any | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    adapter_factory: Callable[[], Any] = BinanceNativeAdapter,
) -> dict[str, object]:
    """Execute fixed smoke path once; test seams inject adapter/output only."""

    output = Path(output_root)
    _validate_output_root(output)
    adapter_instance = adapter if adapter is not None else adapter_factory()
    try:
        raw = await adapter_instance.get_historical_ohlcv(
            ASSET,
            TIMEFRAME,
            since=_epoch_milliseconds(START_UTC),
            until=_epoch_milliseconds(END_UTC),
            limit=REQUEST_LIMIT,
        )
    except Exception as exc:
        raise SmokeBlocked("BLOCKED_BINANCE_FETCH", str(exc)) from exc

    normalized = normalize_binance_ohlcv(raw)
    primary_frame = build_confirmed_frame(normalized)
    if primary_frame.row_count != EXPECTED_PRIMARY_ROWS:
        raise SmokeBlocked("BLOCKED_SOURCE_PREFLIGHT", "primary frame row count mismatch")
    foundation = foundation_config()
    provider_config = smoke_provider_config()
    primary = discover_trendlines(
        primary_frame,
        config=foundation,
        provider_config=provider_config,
    )
    primary_window = _window_metadata(START_UTC, primary_frame)
    fallback_frame: ConfirmedOHLCVFrame | None = None
    fallback: ProviderResult | None = None
    selected_frame = primary_frame
    selected = primary
    if should_use_workload_fallback(primary):
        suffix = normalized.loc[normalized.index >= pd.Timestamp(SUFFIX_START_UTC)].copy(deep=True)
        if len(suffix) != EXPECTED_SUFFIX_ROWS:
            raise SmokeBlocked("BLOCKED_SOURCE_PREFLIGHT", "fallback suffix row count mismatch")
        fallback_frame = build_confirmed_frame(suffix, start=SUFFIX_START_UTC)
        fallback = discover_trendlines(
            fallback_frame,
            config=foundation,
            provider_config=provider_config,
        )
        selected_frame = fallback_frame
        selected = fallback

    provider_bytes = _canonical_json_bytes(selected.to_dict())
    provider_path = output / "provider_result.json"
    _atomic_write_json(provider_path, selected.to_dict())
    provider_result_sha256 = _sha256(provider_bytes)
    viewer_path = output / "viewer_bundle"
    write_viewer_bundle(selected, viewer_path)
    validate_bundle(viewer_path)
    viewer_payload = json.loads((viewer_path / "chart_payload.json").read_text(encoding="utf-8"))
    viewer_manifest = json.loads((viewer_path / "manifest.json").read_text(encoding="utf-8"))
    http_statuses = _http_smoke(viewer_path)
    base_commit, branch = _git_identity()
    report = _report(
        base_commit=base_commit,
        branch=branch,
        adapter=adapter_instance,
        raw_row_count=len(raw),
        normalized=normalized,
        primary_frame=primary_frame,
        primary=primary,
        primary_window=primary_window,
        fallback_frame=fallback_frame,
        fallback=fallback,
        selected_frame=selected_frame,
        selected=selected,
        viewer_bundle_path=viewer_path,
        provider_result_sha256=provider_result_sha256,
        viewer_payload=viewer_payload,
        viewer_manifest=viewer_manifest,
        http_statuses=http_statuses,
    )
    _atomic_write_json(output / "run_report.json", report)
    print(
        "Manual serve:\n"
        "cd /Users/aloobhujia/flipperAgent/src/apps/trendline_v2_viewer/web\n"
        "npm ci\n"
        "npm run build\n\n"
        "cd /Users/aloobhujia/flipperAgent\n"
        "PYTHONPATH=src .venv/bin/python -m apps.trendline_v2_viewer.server "
        f"--bundle {viewer_path} --port 8765\n\n"
        "Open manually:\nhttp://127.0.0.1:8765"
    )
    return report


def main() -> int:
    try:
        report = asyncio.run(run_smoke())
    except SmokeBlocked as exc:
        print(str(exc))
        return 1
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
    return 1 if report["run_state"] != "READY_FOR_ORCHESTRATOR_REVIEW" else 0


if __name__ == "__main__":
    raise SystemExit(main())
