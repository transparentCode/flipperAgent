"""Measure confirmed-extrema candidate density on one frozen local source bundle.

This study is intentionally read-only with respect to the model and source
artifacts. It calls the existing public discovery API over fixed causal
prefixes; it never fetches data, ranks candidates, or writes runtime config.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import median
import tempfile
import time
from typing import Any, Mapping, Sequence

import pandas as pd

from apps.trendline_v2_viewer.server import validate_bundle
from libs.models.trendline_v2.api import discover_trendlines
from libs.models.trendline_v2.configuration import (
    ConfirmedExtremaPairConfig,
    ResolvedTrendlineV2Config,
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
from libs.models.trendline_v2.domain.identity import canonical_json, deterministic_hash
from libs.models.trendline_v2.domain.validation import ContractValidationError
from libs.models.trendline_v2.input import ConfirmedOHLCVFrame


ASSET = "BTCUSDT"
TIMEFRAME = "4h"
SOURCE_START = datetime(2025, 8, 1, tzinfo=timezone.utc)
SOURCE_END = datetime(2025, 12, 1, tzinfo=timezone.utc)
SOURCE_LAST = datetime(2025, 11, 30, 20, tzinfo=timezone.utc)
BAR_INTERVAL = timedelta(hours=4)
EXPECTED_ROWS = 732
EXPECTED_MID_ROWS = 366
EXPECTED_REQUEST_NETWORK_CALLS = 1
STUDY_SCHEMA_VERSION = "trendline_v2_phase_9a_density_effects_v1"
SOURCE_SCHEMA_VERSION = "trendline_v2_real_asset_smoke_v1"
SOURCE_ROOT = Path("/tmp/trendline_v2_real_asset_smoke/btcusdt_4h_20250801_20251201")
OUTPUT_ROOT = Path("/tmp/trendline_v2_phase9a_density/btcusdt_4h_20250801_20251201")

BASELINE_VALUES: dict[str, int | float] = {
    "lookback_duration_seconds": 10_540_800.0,
    "left_confirmation_bars": 1,
    "right_confirmation_bars": 1,
    "min_extrema_per_role": 2,
    "max_hypotheses": 100_000,
    "max_output_candidates": 10_000,
}
LOOKBACK_VALUES = (1_382_400.0, 2_764_800.0, 5_270_400.0, 10_540_800.0)
CONFIRMATION_VALUES = (1, 2, 4, 8)
MIN_EXTREMA_VALUES = (2, 4, 8, 16)
TESTED_FIELDS = (
    "lookback_duration_seconds",
    "left_confirmation_bars",
    "right_confirmation_bars",
    "min_extrema_per_role",
)
WINDOW_BOUNDARY_POLICY = "confirmed_through_is_close_boundary_v1"
WINDOWS = (
    {
        "name": "mid",
        "confirmed_through": "2025-10-01T00:00:00Z",
        "row_count": EXPECTED_MID_ROWS,
        "boundary_policy": WINDOW_BOUNDARY_POLICY,
    },
    {
        "name": "full",
        "confirmed_through": "2025-12-01T00:00:00Z",
        "row_count": EXPECTED_ROWS,
        "boundary_policy": WINDOW_BOUNDARY_POLICY,
    },
)
WORKLOAD_FIELDS = frozenset({"hypothesis_limit_exceeded", "output_limit_exceeded"})
_UTC = timezone.utc
_NANOSECONDS_PER_SECOND = 1_000_000_000


class SourceArtifactError(RuntimeError):
    """Frozen source bundle is missing or fails integrity checks."""


def _canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise SourceArtifactError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise SourceArtifactError(f"artifact must contain a JSON object: {path}")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _parse_utc(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise SourceArtifactError(f"{field_name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceArtifactError(f"{field_name} is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise SourceArtifactError(f"{field_name} must be UTC")
    return parsed.astimezone(_UTC)


def _require_equal(actual: object, expected: object, *, field_name: str) -> None:
    if actual != expected:
        raise SourceArtifactError(
            f"{field_name} mismatch: expected {expected!r}, got {actual!r}"
        )


def _require_sha(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SourceArtifactError(f"{field_name} must be lowercase SHA-256")
    return value


def _typed_source_result(payload: Mapping[str, Any]) -> ProviderResult:
    try:
        request_payload = payload["request"]
        input_payload = request_payload["input_data"]
        config_payload = request_payload["config"]
        model_payload = config_payload["model"]
        provider_payload = request_payload["provider_config"]["active_config"]
        config = ResolvedTrendlineV2Config(
            model_name=model_payload["name"],
            model_version=model_payload["version"],
            schema_version=model_payload["schema_version"],
            provenance=config_payload["provenance"],
        )
        provider_config = ConfirmedExtremaPairConfig(**dict(provider_payload))
        input_data = ProviderInput(
            asset=input_payload["asset"],
            timeframe=input_payload["timeframe"],
            observed_at=_parse_utc(input_payload["observed_at"], field_name="observed_at"),
            confirmed_through=_parse_utc(
                input_payload["confirmed_through"], field_name="confirmed_through"
            ),
            timestamps=tuple(input_payload["timestamps"]),
            open=tuple(input_payload["open"]),
            high=tuple(input_payload["high"]),
            low=tuple(input_payload["low"]),
            close=tuple(input_payload["close"]),
            volume=tuple(input_payload["volume"]),
        )
        request = ProviderRequest(
            input_data=input_data,
            config=config,
            provider_config=provider_config,
        )
        result = ProviderResult(
            provider_name=payload["provider_name"],
            provider_version=payload["provider_version"],
            request=request,
            status=payload["status"],
            candidates=tuple(LineCandidate.from_dict(item) for item in payload["candidates"]),
            evidence=tuple(
                ConfirmedExtremaPairEvidence.from_dict(item)
                for item in payload["evidence"]
            ),
            diagnostics=ProviderDiagnostics(**dict(payload["diagnostics"])),
            reason=payload["reason"],
            detail=payload["detail"],
        )
    except (ContractValidationError, KeyError, TypeError, ValueError) as exc:
        raise SourceArtifactError("provider-result typed validation failed") from exc
    if canonical_json(result.to_dict()) != canonical_json(payload):
        raise SourceArtifactError("provider-result semantic payload mismatch")
    return result


def _validate_source_bundle(source_root: Path) -> dict[str, Any]:
    if not source_root.is_dir() or source_root.is_symlink():
        raise SourceArtifactError("BLOCKED_SOURCE_ARTIFACT: source root is missing")
    required = {
        "run_report.json",
        "provider_result.json",
        "viewer_bundle/manifest.json",
        "viewer_bundle/chart_payload.json",
    }
    actual = {
        str(path.relative_to(source_root))
        for path in source_root.rglob("*")
        if path.is_file()
    }
    if actual != required:
        raise SourceArtifactError(
            f"BLOCKED_SOURCE_ARTIFACT: source members mismatch: {sorted(actual)!r}"
        )
    run_report = _load_json(source_root / "run_report.json")
    if run_report.get("schema_version") != SOURCE_SCHEMA_VERSION:
        raise SourceArtifactError("source run-report schema mismatch")
    _require_equal(run_report.get("asset"), ASSET, field_name="run_report.asset")
    _require_equal(run_report.get("timeframe"), TIMEFRAME, field_name="run_report.timeframe")
    _require_equal(
        run_report.get("market"),
        "binance_usd_m_futures",
        field_name="run_report.market",
    )
    _require_equal(run_report.get("network_request_count"), EXPECTED_REQUEST_NETWORK_CALLS, field_name="network_request_count")
    _require_equal(run_report.get("fallback_used"), False, field_name="fallback_used")
    _require_equal(
        run_report.get("provider_config_classification"),
        "SMOKE_ONLY / UNRESOLVED / NOT_PROMOTED / NOT_CANONICAL",
        field_name="provider_config_classification",
    )
    _require_equal(run_report.get("normalized_row_count"), EXPECTED_ROWS, field_name="normalized_row_count")
    _require_equal(run_report.get("raw_row_count"), EXPECTED_ROWS + 1, field_name="raw_row_count")
    _require_equal(run_report.get("request_limit"), 1000, field_name="request_limit")
    _require_equal(run_report.get("normalized_first_timestamp"), "2025-08-01T00:00:00Z", field_name="normalized_first_timestamp")
    _require_equal(run_report.get("normalized_last_timestamp"), "2025-11-30T20:00:00Z", field_name="normalized_last_timestamp")
    _require_equal(run_report.get("request_start"), "2025-08-01T00:00:00Z", field_name="request_start")
    _require_equal(run_report.get("request_end"), "2025-12-01T00:00:00Z", field_name="request_end")

    provider_path = source_root / "provider_result.json"
    provider_payload = _load_json(provider_path)
    provider_sha = _sha256_file(provider_path)
    _require_equal(run_report.get("provider_result_sha256"), provider_sha, field_name="provider_result_sha256")
    result = _typed_source_result(provider_payload)
    if result.status is not ProviderStatus.SUCCESS:
        raise SourceArtifactError("source provider result must be successful")
    _require_equal(result.request.asset, ASSET, field_name="provider input asset")
    _require_equal(result.request.timeframe, TIMEFRAME, field_name="provider input timeframe")
    _require_equal(result.request.input_data.row_count, EXPECTED_ROWS, field_name="provider input row_count")
    _require_equal(
        result.request.provider_config.to_dict()["active_config"],
        _config_payload(BASELINE_VALUES),
        field_name="source baseline provider config",
    )
    _require_equal(run_report.get("provider_identity"), result.provider_identity, field_name="provider_identity")
    _require_equal(run_report.get("provider_contract_identity"), result.provider_contract_identity, field_name="provider_contract_identity")
    _require_equal(run_report.get("request_identity"), result.request.request_identity, field_name="request_identity")
    _require_equal(run_report.get("config_identity"), result.request.config_identity, field_name="config_identity")
    _require_equal(run_report.get("provider_input_identity"), result.request.input_identity, field_name="provider_input_identity")
    _require_equal(run_report.get("primary_candidate_count"), len(result.candidates), field_name="primary_candidate_count")
    _require_equal(run_report.get("support_candidate_count"), sum(candidate.role.value == "support" for candidate in result.candidates), field_name="support_candidate_count")
    _require_equal(run_report.get("resistance_candidate_count"), sum(candidate.role.value == "resistance" for candidate in result.candidates), field_name="resistance_candidate_count")

    bundle_path = source_root / "viewer_bundle"
    try:
        manifest = validate_bundle(bundle_path)
    except (ContractValidationError, OSError, ValueError) as exc:
        raise SourceArtifactError("viewer bundle validation failed") from exc
    payload = _load_json(bundle_path / "chart_payload.json")
    _require_equal(run_report.get("viewer_bundle_id"), manifest["bundle_id"], field_name="viewer_bundle_id")
    _require_equal(run_report.get("viewer_payload_id"), payload.get("payload_id"), field_name="viewer_payload_id")
    _require_equal(payload.get("asset"), ASSET, field_name="viewer payload asset")
    _require_equal(payload.get("timeframe"), TIMEFRAME, field_name="viewer payload timeframe")
    _require_equal(payload.get("input_identity"), result.request.input_identity, field_name="viewer payload input_identity")
    _require_equal(payload.get("request_identity"), result.request.request_identity, field_name="viewer payload request_identity")
    _require_equal(payload.get("config_identity"), result.request.config_identity, field_name="viewer payload config_identity")
    _require_equal(payload.get("provider_identity"), result.provider_identity, field_name="viewer payload provider_identity")
    _require_equal(payload.get("provider_contract_identity"), result.provider_contract_identity, field_name="viewer payload provider_contract_identity")
    _require_equal(payload.get("snapshot_id"), result.to_snapshot().snapshot_id, field_name="viewer payload snapshot_id")
    _require_equal(len(payload.get("candles", ())), EXPECTED_ROWS, field_name="viewer candle count")
    _require_equal(len(payload.get("candidates", ())), len(result.candidates), field_name="viewer candidate count")
    _validate_source_candles(payload["candles"], result.request.input_data)
    _validate_source_candidates(payload["candidates"], result)

    timestamps = result.request.input_data.timestamps
    _require_equal(timestamps[0], int(SOURCE_START.timestamp() * _NANOSECONDS_PER_SECOND), field_name="source first timestamp")
    _require_equal(timestamps[-1], int(SOURCE_LAST.timestamp() * _NANOSECONDS_PER_SECOND), field_name="source last timestamp")
    if any(second - first != int(BAR_INTERVAL.total_seconds() * _NANOSECONDS_PER_SECOND) for first, second in zip(timestamps, timestamps[1:])):
        raise SourceArtifactError("source timestamps are not exact four-hour spacing")
    source_files = tuple(
        {
            "path": name,
            "byte_length": (source_root / name).stat().st_size,
            "sha256": _sha256_file(source_root / name),
        }
        for name in sorted(required)
    )
    source_semantics = {
        "schema_version": STUDY_SCHEMA_VERSION,
        "asset": ASSET,
        "timeframe": TIMEFRAME,
        "source_schema_version": SOURCE_SCHEMA_VERSION,
        "source_files": source_files,
        "provider_result_sha256": provider_sha,
        "viewer_payload_id": payload["payload_id"],
        "viewer_bundle_id": manifest["bundle_id"],
        "input_identity": result.request.input_identity,
        "request_identity": result.request.request_identity,
        "config_identity": result.request.config_identity,
        "provider_identity": result.provider_identity,
        "provider_contract_identity": result.provider_contract_identity,
    }
    source_identity = deterministic_hash("trendline_v2_phase_9a_source", source_semantics)
    return {
        "schema_version": STUDY_SCHEMA_VERSION,
        "source_identity": source_identity,
        "source_root_label": "trendline_v2_real_asset_smoke/btcusdt_4h_20250801_20251201",
        "asset": ASSET,
        "timeframe": TIMEFRAME,
        "source_schema_version": SOURCE_SCHEMA_VERSION,
        "source_files": list(source_files),
        "run_report": {
            "base_commit": run_report.get("base_commit"),
            "branch": run_report.get("branch"),
            "network_request_count": run_report["network_request_count"],
            "normalized_row_count": run_report["normalized_row_count"],
            "normalized_first_timestamp": run_report["normalized_first_timestamp"],
            "normalized_last_timestamp": run_report["normalized_last_timestamp"],
            "provider_result_sha256": provider_sha,
            "viewer_payload_id": payload["payload_id"],
            "viewer_bundle_id": manifest["bundle_id"],
        },
        "input": {
            "asset": result.request.asset,
            "timeframe": result.request.timeframe,
            "row_count": result.request.input_data.row_count,
            "first_timestamp": _iso_ns(timestamps[0]),
            "last_timestamp": _iso_ns(timestamps[-1]),
            "input_identity": result.request.input_identity,
            "request_identity": result.request.request_identity,
        },
        "provider": {
            "provider_identity": result.provider_identity,
            "provider_contract_identity": result.provider_contract_identity,
            "config_identity": result.request.config_identity,
            "provider_config_identity": result.request.provider_config_identity,
            "candidate_count": len(result.candidates),
            "evidence_count": len(result.evidence),
        },
    }


def _validate_source_candles(candles: Sequence[Mapping[str, Any]], input_data: ProviderInput) -> None:
    if len(candles) != input_data.row_count:
        raise SourceArtifactError("viewer candle count does not match provider input")
    for index, (candle, timestamp, open_value, high, low, close, volume) in enumerate(
        zip(candles, input_data.timestamps, input_data.open, input_data.high, input_data.low, input_data.close, input_data.volume)
    ):
        if candle.get("time") != timestamp // _NANOSECONDS_PER_SECOND:
            raise SourceArtifactError(f"viewer candle time mismatch at {index}")
        for field_name, expected in (("open", open_value), ("high", high), ("low", low), ("close", close), ("volume", volume)):
            if float(candle.get(field_name)) != float(expected):
                raise SourceArtifactError(f"viewer candle {field_name} mismatch at {index}")


def _validate_source_candidates(candidates: Sequence[Mapping[str, Any]], result: ProviderResult) -> None:
    if tuple(item.get("candidate_id") for item in candidates) != tuple(item.candidate_id for item in result.candidates):
        raise SourceArtifactError("viewer candidate ordering does not match provider result")
    evidence_by_id = {item.candidate_id: item for item in result.evidence}
    for payload, candidate in zip(candidates, result.candidates):
        first, second = candidate.anchors
        _require_equal(payload.get("role"), candidate.role.value, field_name="viewer candidate role")
        _require_equal(payload.get("start_time"), int(first.pivot_time.timestamp()), field_name="viewer candidate start_time")
        _require_equal(payload.get("end_time"), int(second.pivot_time.timestamp()), field_name="viewer candidate end_time")
        _require_equal(payload.get("start_price"), first.price, field_name="viewer candidate start_price")
        _require_equal(payload.get("end_price"), second.price, field_name="viewer candidate end_price")
        if canonical_json(payload.get("evidence")) != canonical_json(
            evidence_by_id[candidate.candidate_id].to_dict()
        ):
            raise SourceArtifactError("viewer candidate evidence mismatch")


def _iso_ns(timestamp_ns: int) -> str:
    return datetime.fromtimestamp(timestamp_ns / _NANOSECONDS_PER_SECOND, tz=_UTC).isoformat().replace("+00:00", "Z")


def _config_payload(values: Mapping[str, int | float]) -> dict[str, int | float]:
    return {name: values[name] for name in BASELINE_VALUES}


def _provider_config(values: Mapping[str, int | float]) -> ConfirmedExtremaPairConfig:
    return ConfirmedExtremaPairConfig(**dict(_config_payload(values)))


def candidate_structure_id(candidate: LineCandidate) -> str:
    """Return research-only structure identity without observation binding."""

    return deterministic_hash(
        "trendline_v2_phase_9a_candidate_structure_v1",
        {
            "asset": candidate.asset,
            "timeframe": candidate.timeframe,
            "role": candidate.role.value,
            "geometry": candidate.geometry.to_dict(),
            "anchors": [anchor.to_dict() for anchor in candidate.anchors],
            "evidence": candidate.evidence.to_dict(),
            "provider_name": candidate.provider_name,
            "provider_version": candidate.provider_version,
        },
    )


def build_configuration_matrix() -> tuple[dict[str, Any], ...]:
    """Return exact one-at-a-time matrix in stable declaration order."""

    specs: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(values: Mapping[str, int | float], *, changed_field: str | None, changed_value: int | float | None, label: str) -> None:
        config = _provider_config(values)
        config_id = config.semantic_hash
        if config_id in seen:
            return
        seen.add(config_id)
        specs.append(
            {
                "configuration_id": config_id,
                "label": label,
                "changed_field": changed_field,
                "changed_value": changed_value,
                "values": _config_payload(values),
                "provider_config_identity": config.semantic_hash,
            }
        )

    add(BASELINE_VALUES, changed_field=None, changed_value=None, label="baseline")
    for value in LOOKBACK_VALUES:
        values = dict(BASELINE_VALUES)
        values["lookback_duration_seconds"] = value
        add(values, changed_field="lookback_duration_seconds", changed_value=value, label=f"lookback_duration_seconds={value:g}")
    for value in CONFIRMATION_VALUES:
        values = dict(BASELINE_VALUES)
        values["left_confirmation_bars"] = value
        add(values, changed_field="left_confirmation_bars", changed_value=value, label=f"left_confirmation_bars={value}")
    for value in CONFIRMATION_VALUES:
        values = dict(BASELINE_VALUES)
        values["right_confirmation_bars"] = value
        add(values, changed_field="right_confirmation_bars", changed_value=value, label=f"right_confirmation_bars={value}")
    for value in MIN_EXTREMA_VALUES:
        values = dict(BASELINE_VALUES)
        values["min_extrema_per_role"] = value
        add(values, changed_field="min_extrema_per_role", changed_value=value, label=f"min_extrema_per_role={value}")
    if len(specs) != 13:
        raise RuntimeError(f"fixed Phase 9A matrix must contain 13 configurations, got {len(specs)}")
    return tuple(specs)


def _window_frame(input_data: ProviderInput, window: Mapping[str, Any]) -> ConfirmedOHLCVFrame:
    row_count = int(window["row_count"])
    if row_count not in {EXPECTED_MID_ROWS, EXPECTED_ROWS}:
        raise RuntimeError("unsupported fixed window row count")
    timestamps = input_data.timestamps[:row_count]
    index = pd.to_datetime(timestamps, unit="ns", utc=True)
    frame = pd.DataFrame(
        {
            "open": input_data.open[:row_count],
            "high": input_data.high[:row_count],
            "low": input_data.low[:row_count],
            "close": input_data.close[:row_count],
            "volume": input_data.volume[:row_count],
        },
        index=index,
    )
    boundary = _parse_utc(
        window["confirmed_through"], field_name="window.confirmed_through"
    )
    _require_equal(
        window.get("boundary_policy"),
        WINDOW_BOUNDARY_POLICY,
        field_name=f"{window['name']} boundary_policy",
    )
    expected_last_open = boundary - BAR_INTERVAL
    _require_equal(
        frame.index[-1].to_pydatetime(),
        expected_last_open,
        field_name=f"{window['name']} last candle",
    )
    return ConfirmedOHLCVFrame.from_frame(
        frame,
        asset=ASSET,
        timeframe=TIMEFRAME,
        observed_at=boundary,
        confirmed_through=boundary,
    )


def _epoch_nanoseconds(timestamp: datetime) -> int:
    timestamp = timestamp.astimezone(_UTC)
    epoch = datetime(1970, 1, 1, tzinfo=_UTC)
    elapsed = timestamp - epoch
    return (
        (elapsed.days * 86_400 + elapsed.seconds) * _NANOSECONDS_PER_SECOND
        + elapsed.microseconds * 1_000
    )


def _history_row_count(
    timestamps: Sequence[int],
    *,
    confirmed_through: datetime,
    lookback_duration_seconds: float,
) -> int:
    boundary_ns = _epoch_nanoseconds(confirmed_through)
    lookback_ns = int(lookback_duration_seconds * _NANOSECONDS_PER_SECOND)
    history_start_ns = boundary_ns - lookback_ns
    return sum(
        history_start_ns <= timestamp <= boundary_ns for timestamp in timestamps
    )


def _nearest_rank(values: Sequence[int | float]) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil(0.95 * len(ordered)))
    return ordered[rank - 1]


def _median(values: Sequence[int | float]) -> float | None:
    return None if not values else float(median(values))


def _active_counts(*, spans: Sequence[tuple[int, int]], row_count: int) -> list[int]:
    delta = [0] * (row_count + 1)
    for first, second in spans:
        if first < 0 or second >= row_count or first >= second:
            raise RuntimeError("candidate span is outside finite source interval")
        delta[first] += 1
        delta[second + 1] -= 1
    active: list[int] = []
    current = 0
    for index in range(row_count):
        current += delta[index]
        active.append(current)
    return active


def _set_hash(values: Sequence[str]) -> str:
    return _sha256_bytes(_canonical_bytes(list(values)))


def _run_metrics(result: ProviderResult, *, row_count: int, elapsed_seconds: float) -> dict[str, Any]:
    candidates = tuple(result.candidates)
    evidence = tuple(result.evidence)
    support = tuple(candidate for candidate in candidates if candidate.role.value == "support")
    resistance = tuple(candidate for candidate in candidates if candidate.role.value == "resistance")
    anchors = tuple(anchor for candidate in candidates for anchor in candidate.anchors)
    anchor_reuse = Counter(anchor.anchor_id for anchor in anchors)
    spans = tuple(
        (item.anchor_source_positions[0], item.anchor_source_positions[1])
        for item in evidence
    )
    span_bars = tuple(second - first for first, second in spans)
    active = _active_counts(spans=spans, row_count=row_count)
    candidate_ids = tuple(candidate.candidate_id for candidate in candidates)
    evidence_ids = tuple(item.evidence_id for item in evidence)
    structure_ids = tuple(candidate_structure_id(candidate) for candidate in candidates)
    return {
        "status": result.status.value,
        "reason": None if result.reason is None else result.reason.value,
        "row_count": row_count,
        "history_row_count": _history_row_count(
            result.request.input_data.timestamps,
            confirmed_through=result.request.confirmed_through,
            lookback_duration_seconds=(
                result.request.provider_config.lookback_duration_seconds
            ),
        ),
        "total_candidate_count": len(candidates),
        "support_candidate_count": len(support),
        "resistance_candidate_count": len(resistance),
        "candidate_count_per_bar": len(candidates) / row_count,
        "unique_anchor_count": len(anchor_reuse),
        "unique_support_anchor_count": len({anchor.anchor_id for candidate in support for anchor in candidate.anchors}),
        "unique_resistance_anchor_count": len({anchor.anchor_id for candidate in resistance for anchor in candidate.anchors}),
        "anchor_reuse_median": _median(tuple(anchor_reuse.values())),
        "anchor_reuse_p95": _nearest_rank(tuple(anchor_reuse.values())),
        "anchor_reuse_max": max(anchor_reuse.values(), default=None),
        "segment_span_bars_median": _median(span_bars),
        "segment_span_bars_p95": _nearest_rank(span_bars),
        "segment_span_bars_max": max(span_bars, default=None),
        "simultaneously_active_min": min(active, default=None),
        "simultaneously_active_median": _median(active),
        "simultaneously_active_p95": _nearest_rank(active),
        "simultaneously_active_max": max(active, default=None),
        "candidate_set_hash": _set_hash(candidate_ids),
        "evidence_set_hash": _set_hash(evidence_ids),
        "snapshot_id": result.to_snapshot().snapshot_id,
        "request_identity": result.request.request_identity,
        "config_identity": result.request.config_identity,
        "provider_identity": result.provider_identity,
        "provider_contract_identity": result.provider_contract_identity,
        "elapsed_seconds": round(elapsed_seconds, 6),
        "_candidate_ids": candidate_ids,
        "_evidence_ids": evidence_ids,
        "_candidate_structure_ids": structure_ids,
    }


def _run_one(
    *,
    frame: ConfirmedOHLCVFrame,
    config: ResolvedTrendlineV2Config,
    provider_config: ConfirmedExtremaPairConfig,
    config_spec: Mapping[str, Any],
    window: Mapping[str, Any],
    execution_kind: str,
    execution_index: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = discover_trendlines(
        frame,
        config=config,
        provider_config=provider_config,
    )
    elapsed = time.perf_counter() - started
    run_id = deterministic_hash(
        "trendline_v2_phase_9a_run",
        {
            "study_schema_version": STUDY_SCHEMA_VERSION,
            "configuration_id": config_spec["configuration_id"],
            "window": window,
            "execution_kind": execution_kind,
            "execution_index": execution_index,
        },
    )
    return {
        "run_id": run_id,
        "configuration_id": config_spec["configuration_id"],
        "configuration_label": config_spec["label"],
        "changed_field": config_spec["changed_field"],
        "changed_value": config_spec["changed_value"],
        "configuration": config_spec["values"],
        "window": dict(window),
        "execution_kind": execution_kind,
        "execution_index": execution_index,
        **_run_metrics(result, row_count=int(window["row_count"]), elapsed_seconds=elapsed),
    }


def _semantic_signature(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        record["status"],
        record["reason"],
        record["candidate_set_hash"],
        record["evidence_set_hash"],
        record["total_candidate_count"],
        record["support_candidate_count"],
        record["resistance_candidate_count"],
        record["unique_anchor_count"],
        record["simultaneously_active_min"],
        record["simultaneously_active_median"],
        record["simultaneously_active_p95"],
        record["simultaneously_active_max"],
    )


def _effect_classification(record: Mapping[str, Any], baseline: Mapping[str, Any]) -> str:
    if record["status"] == "failed":
        return "INVALID_OR_FAILED"
    if record["status"] == "abstained":
        if record["reason"] in WORKLOAD_FIELDS:
            return "WORKLOAD_LIMIT_EFFECT"
        return "ABSTENTION_EFFECT"
    if _semantic_signature(record) == _semantic_signature(baseline):
        return "NO_OUTPUT_EFFECT_IN_TESTED_RANGE"
    return "OUTPUT_EFFECT_OBSERVED"


def _cross_window(config_records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_window = {record["window"]["name"]: record for record in config_records}
    mid = by_window["mid"]
    full = by_window["full"]
    mid_structures = set(mid["_candidate_structure_ids"])
    full_structures = set(full["_candidate_structure_ids"])
    persistence = (
        None
        if not mid_structures
        else len(mid_structures & full_structures) / len(mid_structures)
    )
    mid_support = mid["support_candidate_count"] / max(1, mid["total_candidate_count"])
    full_support = full["support_candidate_count"] / max(1, full["total_candidate_count"])
    return {
        "candidate_count_change_366_to_732": full["total_candidate_count"] - mid["total_candidate_count"],
        "active_density_change_366_to_732": full["candidate_count_per_bar"] - mid["candidate_count_per_bar"],
        "anchor_count_change_366_to_732": full["unique_anchor_count"] - mid["unique_anchor_count"],
        "role_mix_change_366_to_732": {
            "support_fraction": full_support - mid_support,
            "resistance_fraction": (1.0 - full_support) - (1.0 - mid_support),
        },
        "candidate_structure_persistence_ratio": persistence,
        "persistence_definition": (
            "candidate_structure_id_overlap_v1; canonical candidate IDs are "
            "observation-bound; descriptive cross-window comparison only, not "
            "model identity or tracking identity"
        ),
    }


def _summary_rows(records: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    columns = (
        "run_id", "configuration_id", "configuration_label", "changed_field", "changed_value",
        "window", "execution_kind", "status", "reason", "row_count", "history_row_count",
        "total_candidate_count",
        "support_candidate_count", "resistance_candidate_count", "candidate_count_per_bar",
        "unique_anchor_count", "unique_support_anchor_count", "unique_resistance_anchor_count",
        "anchor_reuse_median", "anchor_reuse_p95", "anchor_reuse_max", "segment_span_bars_median",
        "segment_span_bars_p95", "segment_span_bars_max", "simultaneously_active_min",
        "simultaneously_active_median", "simultaneously_active_p95", "simultaneously_active_max",
        "candidate_set_hash", "evidence_set_hash", "snapshot_id", "request_identity", "config_identity",
        "provider_identity", "provider_contract_identity", "elapsed_seconds",
    )
    return tuple(
        {column: record[column] for column in columns}
        for record in sorted(records, key=lambda item: (item["configuration_id"], item["window"]["name"], item["execution_kind"], item["execution_index"]))
    )


def _public_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not key.startswith("_")}


def _write_atomic(path: Path, data: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"refusing non-identical or repeated output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        if path.exists():
            raise FileExistsError(f"refusing output overwrite: {path}")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _write_atomic(path, _canonical_bytes(payload))


def _write_csv(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    rows = _summary_rows(records)
    if not rows:
        raise RuntimeError("summary requires run rows")
    fieldnames = tuple(rows[0])
    buffer = tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=f".{path.name}.", delete=False, newline="", encoding="utf-8")
    temporary = Path(buffer.name)
    try:
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        buffer.flush()
        os.fsync(buffer.fileno())
        buffer.close()
        if path.exists():
            raise FileExistsError(f"refusing output overwrite: {path}")
        os.replace(temporary, path)
    except Exception:
        buffer.close()
        temporary.unlink(missing_ok=True)
        raise


def run_study(*, source_root: str | Path = SOURCE_ROOT, output_root: str | Path = OUTPUT_ROOT) -> dict[str, Path]:
    """Execute fixed Phase 9A matrix once and persist verified study artifacts."""

    source_root = Path(source_root)
    output_root = Path(output_root)
    if output_root.exists():
        raise FileExistsError(f"refusing existing output root: {output_root}")
    source_audit = _validate_source_bundle(source_root)
    provider_payload = _load_json(source_root / "provider_result.json")
    source_result = _typed_source_result(provider_payload)
    matrix = build_configuration_matrix()
    windows = tuple(WINDOWS)
    frames = {
        window["name"]: _window_frame(source_result.request.input_data, window)
        for window in windows
    }
    records: list[dict[str, Any]] = []
    execution_index = 0
    semantic_records: list[dict[str, Any]] = []
    for config_spec in matrix:
        for window in windows:
            record = _run_one(
                frame=frames[window["name"]],
                config=source_result.request.config,
                provider_config=_provider_config(config_spec["values"]),
                config_spec=config_spec,
                window=window,
                execution_kind="semantic",
                execution_index=execution_index,
            )
            records.append(record)
            semantic_records.append(record)
            execution_index += 1
    baseline = matrix[0]
    for window in windows:
        records.append(
            _run_one(
                frame=frames[window["name"]],
                config=source_result.request.config,
                provider_config=_provider_config(baseline["values"]),
                config_spec=baseline,
                window=window,
                execution_kind="deterministic_repeat",
                execution_index=execution_index,
            )
        )
        execution_index += 1
    if len(semantic_records) != 26 or len(records) != 28:
        raise RuntimeError("fixed Phase 9A execution count invariant failed")

    baseline_records = {
        record["window"]["name"]: record
        for record in semantic_records
        if record["configuration_id"] == baseline["configuration_id"]
    }
    classifications: dict[str, dict[str, dict[str, str]]] = {field: {} for field in TESTED_FIELDS}
    for record in semantic_records:
        field = record["changed_field"]
        if field is None:
            continue
        window_name = record["window"]["name"]
        classifications.setdefault(field, {}).setdefault(window_name, {})[record["configuration_label"]] = _effect_classification(record, baseline_records[window_name])

    by_config: dict[str, list[dict[str, Any]]] = {}
    for record in semantic_records:
        by_config.setdefault(record["configuration_id"], []).append(record)
    cross_window = {
        config_id: _cross_window(config_records)
        for config_id, config_records in sorted(by_config.items())
    }
    workload_outcomes = [
        {
            "configuration_id": record["configuration_id"],
            "configuration_label": record["configuration_label"],
            "window": record["window"]["name"],
            "status": record["status"],
            "reason": record["reason"],
        }
        for record in semantic_records
        if record["reason"] in WORKLOAD_FIELDS
    ]
    lowest_density: dict[str, Any] = {}
    for field in TESTED_FIELDS:
        field_records = [
            record for record in semantic_records
            if record["changed_field"] == field and record["status"] == "success"
        ]
        if field_records:
            minimum = min(record["candidate_count_per_bar"] for record in field_records)
            lowest_density[field] = {
                "minimum_candidate_count_per_bar": minimum,
                "configuration_ids": sorted({record["configuration_id"] for record in field_records if record["candidate_count_per_bar"] == minimum}),
                "windows": sorted({record["window"]["name"] for record in field_records if record["candidate_count_per_bar"] == minimum}),
            }
        else:
            lowest_density[field] = None
    repeats = {
        record["window"]["name"]: record
        for record in records
        if record["execution_kind"] == "deterministic_repeat"
    }
    repeat_matches = {
        window["name"]: _semantic_signature(repeats[window["name"]]) == _semantic_signature(baseline_records[window["name"]])
        and repeats[window["name"]]["request_identity"] == baseline_records[window["name"]]["request_identity"]
        and repeats[window["name"]]["snapshot_id"] == baseline_records[window["name"]]["snapshot_id"]
        for window in windows
    }
    study_semantics = {
        "schema_version": STUDY_SCHEMA_VERSION,
        "source_identity": source_audit["source_identity"],
        "asset": ASSET,
        "timeframe": TIMEFRAME,
        "window_boundary_policy": WINDOW_BOUNDARY_POLICY,
        "baseline": BASELINE_VALUES,
        "configurations": matrix,
        "windows": windows,
        "semantic_execution_count": 26,
        "deterministic_repeat_count": 2,
    }
    study_id = deterministic_hash("trendline_v2_phase_9a_density_study", study_semantics)
    matrix_payload = {
        **study_semantics,
        "study_id": study_id,
        "source_identity": source_audit["source_identity"],
        "runs": [
            {
                "run_id": record["run_id"],
                "configuration_id": record["configuration_id"],
                "window": record["window"],
                "execution_kind": record["execution_kind"],
                "execution_index": record["execution_index"],
            }
            for record in records
        ],
        "cross_window_evidence": cross_window,
    }
    matrix_payload["matrix_id"] = deterministic_hash("trendline_v2_phase_9a_density_matrix", matrix_payload)
    decision_without_id = {
        "schema_version": STUDY_SCHEMA_VERSION,
        "study_id": study_id,
        "matrix_id": matrix_payload["matrix_id"],
        "study_status": "DESCRIPTIVE_EVIDENCE_ONLY",
        "tested_fields": list(TESTED_FIELDS),
        "tested_values": {
            "lookback_duration_seconds": list(LOOKBACK_VALUES),
            "left_confirmation_bars": list(CONFIRMATION_VALUES),
            "right_confirmation_bars": list(CONFIRMATION_VALUES),
            "min_extrema_per_role": list(MIN_EXTREMA_VALUES),
        },
        "effect_classification_by_field": classifications,
        "baseline_density": {
            name: _public_record(baseline_records[name])
            for name in sorted(baseline_records)
        },
        "lowest_observed_density_by_field": lowest_density,
        "workload_outcomes": workload_outcomes,
        "determinism_status": {
            "baseline_repeat_matches": repeat_matches,
            "all_baseline_repeats_match": all(repeat_matches.values()),
            "semantic_execution_count": len(semantic_records),
            "total_provider_executions": len(records),
        },
        "source_identity": source_audit["source_identity"],
        "limitations": [
            "one BTCUSDT 4h frozen source window",
            "two causal prefixes only",
            "canonical candidate IDs are observation-bound; structure fingerprints are descriptive cross-window evidence only",
            "window confirmed_through values are close boundaries; last candle open is four hours earlier",
            "workload limits remain fixed and are not density controls",
            "no parameter scope or promotion claim",
        ],
        "PARAMETER_PROMOTION": "NOT_AUTHORIZED",
    }
    decision_payload = {
        **decision_without_id,
        "decision_id": deterministic_hash("trendline_v2_phase_9a_density_decision", decision_without_id),
    }

    runs_dir = output_root / "runs"
    _write_json(output_root / "source_audit.json", source_audit)
    for record in sorted(records, key=lambda item: item["run_id"]):
        _write_json(
            runs_dir / f"{record['run_id']}.json",
            {key: value for key, value in record.items() if not key.startswith("_")},
        )
    _write_json(output_root / "matrix.json", matrix_payload)
    _write_csv(output_root / "summary.csv", records)
    _write_json(output_root / "decision.json", decision_payload)
    return {
        "source_audit": output_root / "source_audit.json",
        "matrix": output_root / "matrix.json",
        "summary": output_root / "summary.csv",
        "decision": output_root / "decision.json",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    try:
        paths = run_study(source_root=args.source_root, output_root=args.output_root)
    except SourceArtifactError as exc:
        print(str(exc))
        return 2
    print(json.dumps({name: str(path) for name, path in paths.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
