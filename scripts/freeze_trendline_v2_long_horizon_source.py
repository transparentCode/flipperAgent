"""Freeze one long-horizon Trendline V2 source without executing the model.

This boundary combines two already frozen CSV components into one causal
``ProviderInput``. It deliberately has no provider, evaluator, network,
selection, tracking, or runtime dependency.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Mapping, Sequence

from libs.models.trendline_v2.domain.identity import canonical_json, deterministic_hash
from libs.models.trendline_v2.domain.provider_input import ProviderInput
from libs.models.trendline_v2.domain.validation import ContractValidationError


UTC = timezone.utc
NANOSECONDS = 1_000_000_000

SOURCE_CONTRACT_NAMESPACE = "trendline_v2_phase_10c1_long_horizon_source_contract"
SOURCE_CONTRACT_SCHEMA = (
    "trendline_v2_phase_10c1_long_horizon_source_v1_contract"
)
PROVIDER_INPUT_SCHEMA = "trendline_v2_phase_10c1_long_horizon_provider_input_v1"
SOURCE_AUDIT_SCHEMA = "trendline_v2_phase_10c1_long_horizon_source_audit_v1"
QUARANTINE_SCHEMA = "trendline_v2_phase_10c1_long_horizon_quarantine_v1"
DECISION_SCHEMA = "trendline_v2_phase_10c1_long_horizon_decision_v1"
MANIFEST_SCHEMA = "trendline_v2_phase_10c1_long_horizon_manifest_v1"
DECISION_NAMESPACE = "trendline_v2_phase_10c1_long_horizon_decision"
MANIFEST_NAMESPACE = "trendline_v2_phase_10c1_long_horizon_manifest"
FREEZE_ENV = "TRENDLINE_V2_ALLOW_PHASE10C1_SOURCE_FREEZE"
OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_phase10c1_long_horizon_source/20250801_20260401"
)

ASSET = "BTCUSDT"
TIMEFRAME = "4h"
INTERVAL_SECONDS = 14_400
SOURCE_START = datetime(2025, 8, 1, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 4, 1, tzinfo=UTC)
CONFIRMED_THROUGH = OBSERVED_AT
EXPECTED_ROWS = 1_458
PROVIDER_LOOKBACK_DAYS = 122
EXPECTED_CONTRACT_ID = (
    "136215cc9d14b471eac40439dad143987e1738ae4b7365307bc87a2f0c752eae"
)

REQUIRED_COLUMNS = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "taker_buy_base",
    "complete",
)
TYPED_INPUT_COLUMNS = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
)

COMPONENT_ONE_PATH = Path(
    "artifacts/trendline_family_candidate_trials/"
    "btcusdt_4h_20250801_20251201_candidate_geometry_v2/"
    "input/normalized_ohlcv.csv"
)
COMPONENT_TWO_PATH = Path(
    "artifacts/trendline_family_saturating_quality_trials/"
    "btcusdt_4h_20251201_20260401_saturating_quality_v1/"
    "input/normalized_ohlcv.csv"
)
COMPONENT_ONE_SHA256 = (
    "b8590c34400042fe8e38c23ac0d01b8d26916f2b0d5a6bed4f4b51d208d0a150"
)
COMPONENT_TWO_SHA256 = (
    "2be2f31fafef8188cf936326a43cbcc926ac4320a72658ed9977c403a98c1c42"
)
QUARANTINE_TEXT = (
    "The December 2025–April 2026 normalized CSV is reused only as byte-bound "
    "raw source material. No validation, holdout, frozen-finalist, metric or "
    "REJECT_HOLDOUT_GATE conclusion from its original trial is admitted into "
    "Trendline V2 evidence."
)


class FreezeError(RuntimeError):
    """Expected bounded source-freeze or verification failure."""


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    component_id: str
    source_path: Path
    output_name: str
    expected_sha256: str
    expected_rows: int
    expected_first: datetime
    expected_last: datetime
    usage_status: str


@dataclass(frozen=True, slots=True)
class ParsedRow:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    taker_buy_base: float
    raw: Mapping[str, str]


COMPONENTS = (
    ComponentSpec(
        component_id="btcusdt_4h_20250801_20251201_candidate_geometry_v2",
        source_path=COMPONENT_ONE_PATH,
        output_name="btcusdt_4h_20250801_20251201.csv",
        expected_sha256=COMPONENT_ONE_SHA256,
        expected_rows=732,
        expected_first=datetime(2025, 8, 1, tzinfo=UTC),
        expected_last=datetime(2025, 11, 30, 20, tzinfo=UTC),
        usage_status="verified_raw_source_component",
    ),
    ComponentSpec(
        component_id="btcusdt_4h_20251201_20260401_saturating_quality_v1",
        source_path=COMPONENT_TWO_PATH,
        output_name="btcusdt_4h_20251201_20260401.csv",
        expected_sha256=COMPONENT_TWO_SHA256,
        expected_rows=726,
        expected_first=datetime(2025, 12, 1, tzinfo=UTC),
        expected_last=datetime(2026, 3, 31, 20, tzinfo=UTC),
        usage_status="raw_csv_bytes_only_downstream_trial_quarantined",
    ),
)


def _canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _epoch_ns(value: datetime) -> int:
    return int(value.timestamp()) * NANOSECONDS


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
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise FreezeError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FreezeError(f"JSON object required: {path}")
    if raw != _canonical_bytes(value):
        raise FreezeError(f"non-canonical JSON: {path}")
    return value


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def _write_json(path: Path, value: object) -> None:
    _write_bytes(path, _canonical_bytes(value))


def _inventory(root: Path, *, exclude: set[str] | None = None) -> list[dict[str, Any]]:
    excluded = set() if exclude is None else exclude
    values: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        values.append(
            {
                "path": relative,
                "byte_length": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return values


def _inventory_digest(inventory: Sequence[Mapping[str, Any]]) -> str:
    return _sha256_bytes(_canonical_bytes(list(inventory)))


def _parse_timestamp(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise FreezeError(f"invalid {field_name} timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise FreezeError(f"{field_name} must be UTC")
    parsed = parsed.astimezone(UTC)
    if parsed.microsecond:
        raise FreezeError(f"{field_name} must be whole-second aligned")
    return parsed


def _decimal_float(value: str, *, field_name: str, line_number: int) -> float:
    try:
        decimal_value = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise FreezeError(f"line {line_number}: invalid decimal {field_name}") from exc
    if not decimal_value.is_finite():
        raise FreezeError(f"line {line_number}: non-finite decimal {field_name}")
    converted = float(decimal_value)
    if not math.isfinite(converted):
        raise FreezeError(f"line {line_number}: non-finite float {field_name}")
    return converted


def _parse_row(row: Mapping[str, str | None], *, line_number: int) -> ParsedRow:
    if set(row) != set(REQUIRED_COLUMNS) or any(
        value is None for value in row.values()
    ):
        raise FreezeError(f"line {line_number}: malformed row")
    raw = {key: str(value) for key, value in row.items()}
    timestamp = _parse_timestamp(raw["timestamp"], field_name="timestamp")
    values = {
        field: _decimal_float(raw[field], field_name=field, line_number=line_number)
        for field in ("open", "high", "low", "close", "volume", "taker_buy_base")
    }
    if raw["complete"] != "True":
        raise FreezeError(f"line {line_number}: incomplete row")
    if values["high"] < values["low"]:
        raise FreezeError(f"line {line_number}: high below low")
    if not values["low"] <= values["open"] <= values["high"]:
        raise FreezeError(f"line {line_number}: open outside candle bounds")
    if not values["low"] <= values["close"] <= values["high"]:
        raise FreezeError(f"line {line_number}: close outside candle bounds")
    if values["volume"] < 0:
        raise FreezeError(f"line {line_number}: negative volume")
    if values["taker_buy_base"] < 0:
        raise FreezeError(f"line {line_number}: negative taker_buy_base")
    return ParsedRow(timestamp=timestamp, raw=raw, **values)


def _validate_spacing(rows: Sequence[ParsedRow], *, label: str) -> None:
    if not rows:
        raise FreezeError(f"{label}: empty component")
    for previous, current in zip(rows, rows[1:]):
        delta = current.timestamp - previous.timestamp
        if delta == timedelta(0):
            raise FreezeError(f"{label}: duplicate timestamp")
        if delta != timedelta(seconds=INTERVAL_SECONDS):
            raise FreezeError(f"{label}: timestamp gap or out-of-order row")


def _parse_component(path: Path, spec: ComponentSpec) -> tuple[ParsedRow, ...]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != REQUIRED_COLUMNS:
                raise FreezeError(f"{spec.component_id}: exact header required")
            rows = tuple(
                _parse_row(row, line_number=reader.line_num)
                for row in reader
            )
    except OSError as exc:
        raise FreezeError(f"cannot read source component: {path}") from exc
    if len(rows) != spec.expected_rows:
        raise FreezeError(f"{spec.component_id}: row count mismatch")
    _validate_spacing(rows, label=spec.component_id)
    if rows[0].timestamp != spec.expected_first:
        raise FreezeError(f"{spec.component_id}: first timestamp mismatch")
    if rows[-1].timestamp != spec.expected_last:
        raise FreezeError(f"{spec.component_id}: last timestamp mismatch")
    if rows[-1].timestamp >= OBSERVED_AT:
        raise FreezeError(f"{spec.component_id}: future row present")
    return rows


def _validate_combined(rows: Sequence[ParsedRow]) -> None:
    if len(rows) != EXPECTED_ROWS:
        raise FreezeError("combined row count mismatch")
    _validate_spacing(rows, label="combined source")
    if rows[0].timestamp != SOURCE_START:
        raise FreezeError("combined source start mismatch")
    if rows[-1].timestamp != COMPONENTS[-1].expected_last:
        raise FreezeError("combined source end mismatch")
    if any(row.timestamp >= OBSERVED_AT for row in rows):
        raise FreezeError("combined source contains future row")


def _contract_payload() -> dict[str, Any]:
    return {
        "schema_version": SOURCE_CONTRACT_SCHEMA,
        "asset": ASSET,
        "timeframe": TIMEFRAME,
        "source_start": _iso(SOURCE_START),
        "observed_at": _iso(OBSERVED_AT),
        "confirmed_through": _iso(CONFIRMED_THROUGH),
        "expected_row_count": EXPECTED_ROWS,
        "interval_seconds": INTERVAL_SECONDS,
        "component_sources": [
            {
                "component_id": spec.component_id,
                "repo_path": spec.source_path.as_posix(),
                "sha256": spec.expected_sha256,
                "first_timestamp": _iso(spec.expected_first),
                "last_timestamp": _iso(spec.expected_last),
                "row_count": spec.expected_rows,
                "usage_status": spec.usage_status,
            }
            for spec in COMPONENTS
        ],
        "required_columns": list(REQUIRED_COLUMNS),
        "typed_input_columns": list(TYPED_INPUT_COLUMNS),
        "parse_policy": "csv_decimal_text_to_decimal_to_float_once",
        "continuity_policy": "strict_4h_no_gap_no_duplicate",
        "complete_policy": "all_rows_true",
        "downstream_trial_artifacts": "forbidden",
    }


def _source_contract_id(payload: Mapping[str, Any] | None = None) -> str:
    identity_payload = _contract_payload() if payload is None else dict(payload)
    identity = deterministic_hash(SOURCE_CONTRACT_NAMESPACE, identity_payload)
    if payload is None and identity != EXPECTED_CONTRACT_ID:
        raise FreezeError("source contract identity drift")
    return identity


def _source_contract_document() -> dict[str, Any]:
    payload = _contract_payload()
    return {
        "schema_version": SOURCE_CONTRACT_SCHEMA,
        "namespace": SOURCE_CONTRACT_NAMESPACE,
        "source_contract_id": _source_contract_id(payload),
        "identity_payload": payload,
    }


def _provider_input(rows: Sequence[ParsedRow]) -> ProviderInput:
    return ProviderInput(
        asset=ASSET,
        timeframe=TIMEFRAME,
        observed_at=OBSERVED_AT,
        confirmed_through=CONFIRMED_THROUGH,
        timestamps=tuple(_epoch_ns(row.timestamp) for row in rows),
        open=tuple(row.open for row in rows),
        high=tuple(row.high for row in rows),
        low=tuple(row.low for row in rows),
        close=tuple(row.close for row in rows),
        volume=tuple(row.volume for row in rows),
    )


def _provider_input_artifact(value: ProviderInput) -> dict[str, Any]:
    return {
        "schema_version": PROVIDER_INPUT_SCHEMA,
        "row_count": value.row_count,
        **value.to_dict(),
    }


def _parse_provider_timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise FreezeError(f"invalid ProviderInput {field_name}")
    return _parse_timestamp(value, field_name=field_name)


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
        value = ProviderInput(
            asset=payload["asset"],
            timeframe=payload["timeframe"],
            observed_at=_parse_provider_timestamp(
                payload["observed_at"], field_name="observed_at"
            ),
            confirmed_through=_parse_provider_timestamp(
                payload["confirmed_through"], field_name="confirmed_through"
            ),
            timestamps=tuple(payload["timestamps"]),
            open=tuple(payload["open"]),
            high=tuple(payload["high"]),
            low=tuple(payload["low"]),
            close=tuple(payload["close"]),
            volume=tuple(payload["volume"]),
        )
    except (KeyError, TypeError, ValueError, ContractValidationError) as exc:
        raise FreezeError("invalid ProviderInput artifact") from exc
    if row_count != value.row_count:
        raise FreezeError("ProviderInput row_count mismatch")
    if payload.get("input_identity") != value.input_identity:
        raise FreezeError("ProviderInput identity mismatch")
    if _provider_input_artifact(value) != dict(payload):
        raise FreezeError("ProviderInput semantic round-trip mismatch")
    return value


def _component_summary(spec: ComponentSpec, source_size: int) -> dict[str, Any]:
    return {
        "component_id": spec.component_id,
        "repo_path": spec.source_path.as_posix(),
        "sha256": spec.expected_sha256,
        "byte_length": source_size,
        "row_count": spec.expected_rows,
        "first_timestamp": _iso(spec.expected_first),
        "last_timestamp": _iso(spec.expected_last),
        "usage_status": spec.usage_status,
    }


SUMMARY_COLUMNS = (
    "component_id",
    "repo_path",
    "sha256",
    "byte_length",
    "row_count",
    "first_timestamp",
    "last_timestamp",
    "usage_status",
)


def _source_summary_bytes(components: Sequence[Mapping[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=SUMMARY_COLUMNS,
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    writer.writerows(components)
    return stream.getvalue().encode("utf-8")


def _quarantine_notice() -> dict[str, Any]:
    return {
        "schema_version": QUARANTINE_SCHEMA,
        "status": "QUARANTINED",
        "component_id": COMPONENTS[1].component_id,
        "usage": "raw_csv_bytes_only",
        "downstream_trial_artifacts": "forbidden",
        "notice": QUARANTINE_TEXT,
    }


def _source_audit(
    *,
    components: Sequence[Mapping[str, Any]],
    provider_input: ProviderInput,
) -> dict[str, Any]:
    audited_components = [
        {
            **dict(component),
            "copied_sha256": component["sha256"],
            "copied_byte_length": component["byte_length"],
            "byte_identical": True,
        }
        for component in components
    ]
    return {
        "schema_version": SOURCE_AUDIT_SCHEMA,
        "source_contract_id": _source_contract_id(),
        "asset": ASSET,
        "timeframe": TIMEFRAME,
        "components": audited_components,
        "combined_input_identity": provider_input.input_identity,
        "source_immutability_verified": True,
        "provider_execution_count": 0,
        "network_request_count": 0,
        "downstream_trial_artifacts": "forbidden",
    }


def _decision(
    *,
    components: Sequence[Mapping[str, Any]],
    provider_input: ProviderInput,
) -> dict[str, Any]:
    payload = {
        "schema_version": DECISION_SCHEMA,
        "study_status": "LONG_HORIZON_SOURCE_READY_FOR_EVICTION_REPLAY",
        "source_contract_id": _source_contract_id(),
        "asset": ASSET,
        "timeframe": TIMEFRAME,
        "component_count": len(components),
        "row_count": provider_input.row_count,
        "interval_seconds": INTERVAL_SECONDS,
        "gap_count": 0,
        "duplicate_timestamp_count": 0,
        "incomplete_row_count": 0,
        "source_start": _iso(SOURCE_START),
        "observed_at": _iso(OBSERVED_AT),
        "confirmed_through": _iso(CONFIRMED_THROUGH),
        "source_duration_days": (OBSERVED_AT - SOURCE_START).days,
        "provider_lookback_days": PROVIDER_LOOKBACK_DAYS,
        "lookback_eviction_observable": True,
        "component_ids": [component["component_id"] for component in components],
        "component_row_counts": {
            component["component_id"]: component["row_count"]
            for component in components
        },
        "input_identity": provider_input.input_identity,
        "quarantine_status": "downstream_component_quarantined",
        "downstream_trial_artifacts": "forbidden",
        "provider_execution_count": 0,
        "network_request_count": 0,
    }
    return {
        **payload,
        "decision_id": deterministic_hash(DECISION_NAMESPACE, payload),
    }


def _manifest(
    *,
    members: Sequence[Mapping[str, Any]],
    source_contract_id: str,
    decision_id: str,
    input_identity: str,
) -> dict[str, Any]:
    payload = {
        "schema_version": MANIFEST_SCHEMA,
        "source_contract_id": source_contract_id,
        "decision_id": decision_id,
        "input_identity": input_identity,
        "member_count": len(members),
        "member_inventory_sha256": _inventory_digest(members),
        "members": list(members),
    }
    return {
        **payload,
        "manifest_id": deterministic_hash(MANIFEST_NAMESPACE, payload),
    }


def _full_output_inventory(root: Path) -> list[dict[str, Any]]:
    return _inventory(root)


def _source_fingerprints() -> tuple[tuple[str, int, str], ...]:
    result = []
    for spec in COMPONENTS:
        if not spec.source_path.is_file():
            raise FreezeError(f"missing source component: {spec.source_path}")
        raw = spec.source_path.read_bytes()
        digest = _sha256_bytes(raw)
        if digest != spec.expected_sha256:
            raise FreezeError(f"source component hash mismatch: {spec.component_id}")
        result.append((spec.source_path.as_posix(), len(raw), digest))
    return tuple(result)


def _build_source_data() -> tuple[list[ParsedRow], ProviderInput, list[dict[str, Any]]]:
    parsed_components = [
        _parse_component(spec.source_path, spec)
        for spec in COMPONENTS
    ]
    combined = [row for rows in parsed_components for row in rows]
    _validate_combined(combined)
    provider_input = _provider_input(combined)
    summaries = [
        _component_summary(spec, spec.source_path.stat().st_size)
        for spec in COMPONENTS
    ]
    return combined, provider_input, summaries


def _write_bundle_files(
    *,
    staging_root: Path,
    provider_input: ProviderInput,
    summaries: Sequence[Mapping[str, Any]],
    source_fingerprints: Sequence[tuple[str, int, str]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    components_root = staging_root / "components"
    for spec, fingerprint in zip(COMPONENTS, source_fingerprints):
        destination = components_root / spec.output_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(spec.source_path, destination)
        if destination.read_bytes() != spec.source_path.read_bytes():
            raise FreezeError(f"component copy mismatch: {spec.component_id}")
        if _sha256_file(destination) != fingerprint[2]:
            raise FreezeError(f"component copy hash mismatch: {spec.component_id}")

    _write_json(staging_root / "provider_input.json", _provider_input_artifact(provider_input))
    contract = _source_contract_document()
    _write_json(staging_root / "source_contract.json", contract)
    audit = _source_audit(components=summaries, provider_input=provider_input)
    _write_json(staging_root / "source_audit.json", audit)
    _write_bytes(staging_root / "source_summary.csv", _source_summary_bytes(summaries))
    quarantine = _quarantine_notice()
    _write_json(staging_root / "quarantine_notice.json", quarantine)
    decision = _decision(components=summaries, provider_input=provider_input)
    _write_json(staging_root / "decision.json", decision)
    members = _inventory(staging_root)
    if len(members) != 8:
        raise FreezeError("expected eight manifest members")
    manifest = _manifest(
        members=members,
        source_contract_id=contract["source_contract_id"],
        decision_id=decision["decision_id"],
        input_identity=provider_input.input_identity,
    )
    _write_json(staging_root / "manifest.json", manifest)
    return contract, decision, manifest


def _expected_bundle_members(root: Path) -> list[dict[str, Any]]:
    members = _inventory(root, exclude={"manifest.json"})
    if len(members) != 8:
        raise FreezeError("bundle must contain exactly eight manifest members")
    expected_paths = {
        "components/btcusdt_4h_20250801_20251201.csv",
        "components/btcusdt_4h_20251201_20260401.csv",
        "provider_input.json",
        "source_contract.json",
        "source_audit.json",
        "source_summary.csv",
        "quarantine_notice.json",
        "decision.json",
    }
    if {item["path"] for item in members} != expected_paths:
        raise FreezeError("bundle member paths mismatch")
    return members


def _verify_bundle(root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    root = Path(root)
    if not root.is_dir():
        raise FreezeError(f"missing source bundle: {root}")
    all_files = _full_output_inventory(root)
    if len(all_files) != 9:
        raise FreezeError("bundle must contain exactly nine files")
    members = _expected_bundle_members(root)
    contract = _load_json(root / "source_contract.json")
    expected_contract = _source_contract_document()
    if contract != expected_contract:
        raise FreezeError("source contract mismatch")

    parsed_components = []
    summaries = []
    for spec in COMPONENTS:
        source_bytes = spec.source_path.read_bytes()
        if _sha256_bytes(source_bytes) != spec.expected_sha256:
            raise FreezeError(f"repository source changed: {spec.component_id}")
        copied = root / "components" / spec.output_name
        if copied.read_bytes() != source_bytes:
            raise FreezeError(f"component bytes mismatch: {spec.component_id}")
        rows = _parse_component(copied, spec)
        parsed_components.append(rows)
        summaries.append(_component_summary(spec, len(source_bytes)))

    combined = [row for rows in parsed_components for row in rows]
    _validate_combined(combined)
    provider_input = _provider_input(combined)
    provider_payload = _load_json(root / "provider_input.json")
    if _provider_input_from_dict(provider_payload) != provider_input:
        raise FreezeError("persisted ProviderInput differs from source")
    if provider_payload != _provider_input_artifact(provider_input):
        raise FreezeError("persisted ProviderInput payload mismatch")

    expected_audit = _source_audit(components=summaries, provider_input=provider_input)
    if _load_json(root / "source_audit.json") != expected_audit:
        raise FreezeError("source audit mismatch")
    if (root / "source_summary.csv").read_bytes() != _source_summary_bytes(summaries):
        raise FreezeError("source summary mismatch")
    if _load_json(root / "quarantine_notice.json") != _quarantine_notice():
        raise FreezeError("quarantine notice mismatch")
    expected_decision = _decision(components=summaries, provider_input=provider_input)
    if _load_json(root / "decision.json") != expected_decision:
        raise FreezeError("decision mismatch")
    manifest = _load_json(root / "manifest.json")
    expected_manifest = _manifest(
        members=members,
        source_contract_id=expected_contract["source_contract_id"],
        decision_id=expected_decision["decision_id"],
        input_identity=provider_input.input_identity,
    )
    if manifest != expected_manifest:
        raise FreezeError("manifest mismatch")
    if manifest["members"] != members:
        raise FreezeError("manifest member hashes mismatch")
    if expected_decision["provider_execution_count"] != 0:
        raise FreezeError("provider execution is outside source-freeze scope")
    if expected_decision["network_request_count"] != 0:
        raise FreezeError("network request is outside source-freeze scope")
    return {
        "study_status": expected_decision["study_status"],
        "source_contract_id": expected_contract["source_contract_id"],
        "provider_input_identity": provider_input.input_identity,
        "decision_id": expected_decision["decision_id"],
        "manifest_id": expected_manifest["manifest_id"],
        "output_inventory_sha256": _inventory_digest(all_files),
        "member_count": len(members),
        "component_count": len(COMPONENTS),
        "row_count": provider_input.row_count,
        "provider_execution_count": 0,
        "network_request_count": 0,
    }


def _require_freeze_gate(cli_flag: bool) -> None:
    if not cli_flag or os.environ.get(FREEZE_ENV) != "1":
        raise FreezeError(f"freeze requires --freeze-source and {FREEZE_ENV}=1")


def freeze_source(
    *,
    output_root: str | Path = OUTPUT_ROOT,
    cli_flag: bool = False,
) -> dict[str, Any]:
    """Parse, combine, audit and atomically publish approved source bytes."""

    output_path = Path(output_root)
    if output_path.exists():
        raise FileExistsError(f"refusing existing output root: {output_path}")
    _require_freeze_gate(cli_flag)
    fingerprints = _source_fingerprints()
    _, provider_input, summaries = _build_source_data()
    if tuple(fingerprints) != _source_fingerprints():
        raise FreezeError("source files changed during parsing")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output_path.name}.freeze-", dir=output_path.parent)
    )
    try:
        _write_bundle_files(
            staging_root=staging,
            provider_input=provider_input,
            summaries=summaries,
            source_fingerprints=fingerprints,
        )
        if tuple(fingerprints) != _source_fingerprints():
            raise FreezeError("source files changed before publication")
        _verify_bundle(staging)
        if output_path.exists():
            raise FileExistsError(f"refusing existing output root: {output_path}")
        os.replace(staging, output_path)
        staging = Path()
        return _verify_bundle(output_path)
    except Exception:
        if staging != Path():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def verify_bundle(*, output_root: str | Path = OUTPUT_ROOT) -> dict[str, Any]:
    """Verify existing bundle and repository sources without writing."""

    return _verify_bundle(Path(output_root))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--freeze-source", action="store_true")
    modes.add_argument("--verify", action="store_true")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.freeze_source:
        result = freeze_source(output_root=args.output_root, cli_flag=True)
    else:
        result = verify_bundle(output_root=args.output_root)
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
