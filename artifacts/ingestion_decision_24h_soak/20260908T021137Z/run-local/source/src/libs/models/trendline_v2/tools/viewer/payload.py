"""Deterministic, read-only chart payloads for Trendline V2 audit output."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Mapping

from libs.models.trendline_v2.discovery.contracts import (
    ProviderReason,
    ProviderResult,
    ProviderStatus,
)
from libs.models.trendline_v2.discovery.provider_evidence import (
    ConfirmedExtremaPairEvidence,
)
from libs.models.trendline_v2.domain.candidates import LineCandidate
from libs.models.trendline_v2.domain.identity import deterministic_hash
from libs.models.trendline_v2.domain.validation import ContractValidationError


PAYLOAD_SCHEMA_VERSION = "trendline_v2_viewer_payload_v1"
BUNDLE_SCHEMA_VERSION = "trendline_v2_viewer_bundle_v1"
_BUNDLE_MEMBER_NAME = "chart_payload.json"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_NANOSECONDS_PER_SECOND = 1_000_000_000
_TOP_LEVEL_KEYS = {
    "schema_version",
    "payload_id",
    "asset",
    "timeframe",
    "observed_at",
    "confirmed_through",
    "request_identity",
    "input_identity",
    "config_identity",
    "provider_identity",
    "provider_contract_identity",
    "snapshot_id",
    "status",
    "reason",
    "candles",
    "candidates",
}
_CANDLE_KEYS = {"time", "open", "high", "low", "close", "volume"}
_CANDIDATE_KEYS = {
    "candidate_id",
    "role",
    "start_time",
    "end_time",
    "start_price",
    "end_price",
    "anchors",
    "evidence",
}
_ANCHOR_KEYS = {"anchor_id", "pivot_time", "confirmation_time", "price"}
_EVIDENCE_KEYS = {
    "candidate_id",
    "extrema_kind",
    "anchor_source_positions",
    "confirmation_positions",
    "validated_intermediate_count",
    "body_violation_count",
    "coordinate_system_version",
    "plateau_policy_version",
    "schema_version",
    "evidence_id",
}
_STATUS_REASONS = {reason.value for reason in ProviderReason}
_STATUSES = {status.value for status in ProviderStatus}
_ALLOWED_REASONS_BY_STATUS = {
    ProviderStatus.SUCCESS.value: frozenset({None}),
    ProviderStatus.ABSTAINED.value: frozenset(
        reason.value
        for reason in ProviderReason
        if reason is not ProviderReason.PROVIDER_FAILURE
    ),
    ProviderStatus.FAILED.value: frozenset({ProviderReason.PROVIDER_FAILURE.value}),
}


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


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _datetime_epoch_ns(value: datetime, *, field_name: str) -> int:
    if not isinstance(value, datetime):
        raise ContractValidationError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContractValidationError(f"{field_name} must be timezone-aware")
    value = value.astimezone(timezone.utc)
    delta = value - _EPOCH
    return (
        (delta.days * 86_400 + delta.seconds) * _NANOSECONDS_PER_SECOND
        + delta.microseconds * 1_000
    )


def _whole_seconds(value: datetime, *, field_name: str) -> int:
    timestamp_ns = _datetime_epoch_ns(value, field_name=field_name)
    if timestamp_ns % _NANOSECONDS_PER_SECOND:
        raise ContractValidationError(
            f"{field_name} must be aligned to whole UNIX seconds for the viewer"
        )
    return timestamp_ns // _NANOSECONDS_PER_SECOND


def _finite_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be numeric")
    result = float(value)
    if not result == result or result in (float("inf"), float("-inf")):
        raise ContractValidationError(f"{field_name} must be finite")
    return result


def _payload_identity(payload: Mapping[str, object]) -> dict[str, object]:
    semantic = dict(payload)
    semantic.pop("payload_id", None)
    return semantic


def _candidate_payload(candidate: LineCandidate, evidence: object) -> dict[str, object]:
    if len(candidate.anchors) != 2:
        raise ContractValidationError("viewer candidates require exactly two anchors")
    first, second = candidate.anchors
    if (
        candidate.geometry.start_time != first.pivot_time
        or candidate.geometry.end_time != second.pivot_time
        or candidate.geometry.start_price != first.price
        or candidate.geometry.end_price != second.price
    ):
        raise ContractValidationError(
            "viewer geometry must be the finite segment between the two anchors"
        )
    if not hasattr(evidence, "candidate_id") or evidence.candidate_id != candidate.candidate_id:
        raise ContractValidationError("viewer evidence must match candidate identity")
    anchors = [
        {
            "anchor_id": anchor.anchor_id,
            "pivot_time": _whole_seconds(anchor.pivot_time, field_name="anchor.pivot_time"),
            "confirmation_time": _whole_seconds(
                anchor.confirmation_time, field_name="anchor.confirmation_time"
            ),
            "price": _finite_number(anchor.price, field_name="anchor.price"),
        }
        for anchor in candidate.anchors
    ]
    return {
        "candidate_id": candidate.candidate_id,
        "role": candidate.role.value,
        "start_time": _whole_seconds(
            candidate.geometry.start_time, field_name="geometry.start_time"
        ),
        "end_time": _whole_seconds(
            candidate.geometry.end_time, field_name="geometry.end_time"
        ),
        "start_price": _finite_number(
            candidate.geometry.start_price, field_name="geometry.start_price"
        ),
        "end_price": _finite_number(
            candidate.geometry.end_price, field_name="geometry.end_price"
        ),
        "anchors": anchors,
        "evidence": evidence.to_dict(),
    }


def _validate_evidence_against_payload(
    candidate: Mapping[str, object],
    evidence: Mapping[str, object],
    candles: list[Mapping[str, object]],
    *,
    status: str,
) -> ConfirmedExtremaPairEvidence:
    """Rebuild typed evidence and bind it to the served candle/anchor facts."""

    try:
        typed = ConfirmedExtremaPairEvidence.from_dict(evidence)
    except ContractValidationError as exc:
        raise ContractValidationError("viewer evidence content is invalid") from exc

    anchors = candidate["anchors"]
    if not isinstance(anchors, list) or len(anchors) != 2:
        raise ContractValidationError("viewer evidence requires two candidate anchors")
    source_positions = typed.anchor_source_positions
    confirmation_positions = typed.confirmation_positions
    for field_name, positions in (
        ("anchor_source_positions", source_positions),
        ("confirmation_positions", confirmation_positions),
    ):
        if any(position >= len(candles) for position in positions):
            raise ContractValidationError(
                f"viewer evidence {field_name} is outside the candle array"
            )

    expected_kind = "low" if candidate["role"] == "support" else "high"
    if typed.extrema_kind.value != expected_kind:
        raise ContractValidationError("viewer evidence role association is invalid")
    for index, (anchor, source_position, confirmation_position) in enumerate(
        zip(anchors, source_positions, confirmation_positions)
    ):
        if not isinstance(anchor, Mapping):
            raise ContractValidationError("viewer evidence anchor is invalid")
        source_candle = candles[source_position]
        confirmation_candle = candles[confirmation_position]
        if source_candle["time"] != anchor["pivot_time"]:
            raise ContractValidationError(
                f"viewer evidence source position does not match anchor {index} time"
            )
        if confirmation_candle["time"] != anchor["confirmation_time"]:
            raise ContractValidationError(
                f"viewer evidence confirmation position does not match anchor {index} time"
            )
        price_field = "low" if typed.extrema_kind.value == "low" else "high"
        if _finite_number(source_candle[price_field], field_name=f"candle {source_position}.{price_field}") != _finite_number(
            anchor["price"], field_name=f"anchor {index}.price"
        ):
            raise ContractValidationError(
                f"viewer evidence source position does not match anchor {index} price"
            )

    expected_intermediate_count = source_positions[1] - source_positions[0] - 1
    if typed.validated_intermediate_count != expected_intermediate_count:
        raise ContractValidationError(
            "viewer evidence intermediate count does not match source positions"
        )
    if status == ProviderStatus.SUCCESS.value and typed.body_violation_count != 0:
        raise ContractValidationError(
            "successful viewer evidence cannot contain body violations"
        )
    return typed


def _validate_payload(payload: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(payload, Mapping) or set(payload) != _TOP_LEVEL_KEYS:
        raise ContractValidationError("viewer payload keys mismatch")
    if payload["schema_version"] != PAYLOAD_SCHEMA_VERSION:
        raise ContractValidationError("unsupported viewer payload schema")
    if not _is_sha256(payload["payload_id"]):
        raise ContractValidationError("viewer payload_id must be lowercase SHA-256")
    for field_name in (
        "request_identity",
        "input_identity",
        "config_identity",
        "provider_identity",
        "provider_contract_identity",
        "snapshot_id",
    ):
        if not _is_sha256(payload[field_name]):
            raise ContractValidationError(f"{field_name} must be lowercase SHA-256")
    for field_name in ("asset", "timeframe"):
        if not isinstance(payload[field_name], str) or not payload[field_name]:
            raise ContractValidationError(f"{field_name} must be a non-empty string")
    for field_name in ("observed_at", "confirmed_through"):
        value = payload[field_name]
        if type(value) is not int:
            raise ContractValidationError(f"{field_name} must be an integer UNIX second")
    if payload["confirmed_through"] > payload["observed_at"]:
        raise ContractValidationError("confirmed_through cannot be after observed_at")
    status = payload["status"]
    reason = payload["reason"]
    if not isinstance(status, str) or status not in _STATUSES:
        raise ContractValidationError("invalid viewer provider status")
    if reason is not None and (
        not isinstance(reason, str) or reason not in _STATUS_REASONS
    ):
        raise ContractValidationError("invalid viewer provider reason")
    if reason not in _ALLOWED_REASONS_BY_STATUS[status]:
        raise ContractValidationError("viewer provider status/reason combination is invalid")
    candles = payload["candles"]
    if not isinstance(candles, list) or not candles:
        raise ContractValidationError("viewer candles must be non-empty")
    previous_time: int | None = None
    for index, candle in enumerate(candles):
        if not isinstance(candle, Mapping) or set(candle) != _CANDLE_KEYS:
            raise ContractValidationError(f"candle {index} keys are invalid")
        timestamp = candle["time"]
        if type(timestamp) is not int:
            raise ContractValidationError(f"candle {index} time is invalid")
        if previous_time is not None and timestamp <= previous_time:
            raise ContractValidationError("viewer candle times must be increasing")
        previous_time = timestamp
        values = {
            name: _finite_number(candle[name], field_name=f"candle {index}.{name}")
            for name in ("open", "high", "low", "close", "volume")
        }
        if (
            values["high"] < values["low"]
            or values["high"] < values["open"]
            or values["high"] < values["close"]
            or values["low"] > values["open"]
            or values["low"] > values["close"]
            or values["volume"] < 0.0
        ):
            raise ContractValidationError(f"candle {index} violates OHLCV bounds")
    candidates = payload["candidates"]
    if not isinstance(candidates, list):
        raise ContractValidationError("viewer candidates must be a list")
    candidate_ids: list[str] = []
    evidence_ids: list[str] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping) or set(candidate) != _CANDIDATE_KEYS:
            raise ContractValidationError(f"candidate {index} keys are invalid")
        candidate_id = candidate["candidate_id"]
        if not _is_sha256(candidate_id) or candidate_id in candidate_ids:
            raise ContractValidationError("viewer candidate IDs must be unique hashes")
        candidate_ids.append(candidate_id)
        if candidate["role"] not in {"support", "resistance"}:
            raise ContractValidationError(f"candidate {index} role is invalid")
        for field_name in ("start_time", "end_time"):
            if type(candidate[field_name]) is not int:
                raise ContractValidationError(f"candidate {index}.{field_name} is invalid")
        if candidate["end_time"] <= candidate["start_time"]:
            raise ContractValidationError("candidate geometry must be time ordered")
        for field_name in ("start_price", "end_price"):
            _finite_number(candidate[field_name], field_name=f"candidate {index}.{field_name}")
        anchors = candidate["anchors"]
        if not isinstance(anchors, list) or len(anchors) != 2:
            raise ContractValidationError("viewer candidates require two anchors")
        if not all(isinstance(anchor, Mapping) for anchor in anchors):
            raise ContractValidationError("viewer anchors must be mappings")
        if anchors[0].get("anchor_id") == anchors[1].get("anchor_id"):
            raise ContractValidationError("viewer candidate anchor IDs must be unique")
        for anchor_index, anchor in enumerate(anchors):
            if not isinstance(anchor, Mapping) or set(anchor) != _ANCHOR_KEYS:
                raise ContractValidationError("viewer anchor keys are invalid")
            if not _is_sha256(anchor["anchor_id"]):
                raise ContractValidationError("viewer anchor ID is invalid")
            if type(anchor["pivot_time"]) is not int or type(anchor["confirmation_time"]) is not int:
                raise ContractValidationError("viewer anchor times must be integer seconds")
            if anchor["confirmation_time"] < anchor["pivot_time"]:
                raise ContractValidationError("viewer anchor confirmation precedes pivot")
            _finite_number(anchor["price"], field_name="viewer anchor price")
            if anchor_index == 0 and (
                candidate["start_time"] != anchor["pivot_time"]
                or candidate["start_price"] != anchor["price"]
            ):
                raise ContractValidationError("viewer start geometry is not the first anchor")
            if anchor_index == 1 and (
                candidate["end_time"] != anchor["pivot_time"]
                or candidate["end_price"] != anchor["price"]
            ):
                raise ContractValidationError("viewer end geometry is not the second anchor")
        evidence = candidate["evidence"]
        if not isinstance(evidence, Mapping) or set(evidence) != _EVIDENCE_KEYS:
            raise ContractValidationError("viewer evidence keys are invalid")
        if evidence.get("candidate_id") != candidate_id:
            raise ContractValidationError("viewer evidence candidate ID mismatch")
        expected_kind = "low" if candidate["role"] == "support" else "high"
        if evidence.get("extrema_kind") != expected_kind:
            raise ContractValidationError("viewer evidence role association is invalid")
        if evidence.get("extrema_kind") not in {"low", "high"}:
            raise ContractValidationError("viewer evidence extrema kind is invalid")
        if not _is_sha256(evidence.get("evidence_id")):
            raise ContractValidationError("viewer evidence ID is invalid")
        for field_name in (
            "coordinate_system_version",
            "plateau_policy_version",
            "schema_version",
        ):
            if not isinstance(evidence.get(field_name), str) or not evidence[field_name]:
                raise ContractValidationError(f"viewer evidence {field_name} is invalid")
        positions = {}
        for field_name in ("anchor_source_positions", "confirmation_positions"):
            values = evidence.get(field_name)
            if (
                not isinstance(values, (list, tuple))
                or len(values) != 2
                or any(type(value) is not int or value < 0 for value in values)
                or values[0] >= values[1]
            ):
                raise ContractValidationError(f"viewer evidence {field_name} is invalid")
            positions[field_name] = values
        if any(
            confirmation <= source
            for source, confirmation in zip(
                positions["anchor_source_positions"], positions["confirmation_positions"]
            )
        ):
            raise ContractValidationError("viewer evidence confirmation position is invalid")
        for field_name in ("validated_intermediate_count", "body_violation_count"):
            if type(evidence.get(field_name)) is not int or evidence[field_name] < 0:
                raise ContractValidationError(f"viewer evidence {field_name} is invalid")
        evidence_id = evidence.get("evidence_id")
        if not _is_sha256(evidence_id) or evidence_id in evidence_ids:
            raise ContractValidationError("viewer evidence IDs must be unique hashes")
        evidence_ids.append(evidence_id)
        _validate_evidence_against_payload(
            candidate,
            evidence,
            candles,
            status=status,
        )
    if status == ProviderStatus.SUCCESS.value:
        if not candidates:
            raise ContractValidationError("successful viewer payload has invalid outcome")
    elif candidates:
        raise ContractValidationError("non-success viewer payload has invalid outcome")
    semantic = _payload_identity(payload)
    if deterministic_hash(PAYLOAD_SCHEMA_VERSION, semantic) != payload["payload_id"]:
        raise ContractValidationError("viewer payload_id does not match semantic content")
    return dict(payload)


def build_chart_payload(result: ProviderResult) -> dict[str, object]:
    """Build one deterministic viewer payload from one validated provider result."""

    if not isinstance(result, ProviderResult):
        raise ContractValidationError("build_chart_payload requires ProviderResult")
    input_data = result.request.input_data
    timestamps = tuple(input_data.timestamps)
    seconds = []
    for index, timestamp_ns in enumerate(timestamps):
        if type(timestamp_ns) is not int or timestamp_ns % _NANOSECONDS_PER_SECOND:
            raise ContractValidationError(
                f"input timestamp at position {index} is not whole-second aligned"
            )
        seconds.append(timestamp_ns // _NANOSECONDS_PER_SECOND)
    snapshot = result.to_snapshot()
    evidence_by_id = {item.candidate_id: item for item in result.evidence}
    if len(evidence_by_id) != len(result.evidence) or len(result.evidence) != len(result.candidates):
        raise ContractValidationError("viewer requires one evidence record per candidate")
    if tuple(item.candidate_id for item in result.evidence) != tuple(
        candidate.candidate_id for candidate in result.candidates
    ):
        raise ContractValidationError("viewer evidence order must match candidate order")
    candles = [
        {
            "time": timestamp,
            "open": float(open_value),
            "high": float(high),
            "low": float(low),
            "close": float(close),
            "volume": float(volume),
        }
        for timestamp, open_value, high, low, close, volume in zip(
            seconds,
            input_data.open,
            input_data.high,
            input_data.low,
            input_data.close,
            input_data.volume,
        )
    ]
    candidate_payloads = [
        _candidate_payload(candidate, evidence_by_id[candidate.candidate_id])
        for candidate in result.candidates
    ]
    payload_without_id: dict[str, object] = {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "asset": result.request.asset,
        "timeframe": result.request.timeframe,
        "observed_at": _whole_seconds(result.request.observed_at, field_name="observed_at"),
        "confirmed_through": _whole_seconds(
            result.request.confirmed_through, field_name="confirmed_through"
        ),
        "request_identity": result.request.request_identity,
        "input_identity": result.request.input_identity,
        "config_identity": result.request.config_identity,
        "provider_identity": result.provider_identity,
        "provider_contract_identity": result.provider_contract_identity,
        "snapshot_id": snapshot.snapshot_id,
        "status": result.status.value,
        "reason": result.reason.value if result.reason is not None else None,
        "candles": candles,
        "candidates": candidate_payloads,
    }
    payload = {
        **payload_without_id,
        "payload_id": deterministic_hash(PAYLOAD_SCHEMA_VERSION, payload_without_id),
    }
    return _validate_payload(payload)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bundle_identity(manifest_without_bundle_id: Mapping[str, object]) -> str:
    return deterministic_hash(BUNDLE_SCHEMA_VERSION, dict(manifest_without_bundle_id))


def write_viewer_bundle(
    result: ProviderResult,
    output_directory: str | Path,
) -> Path:
    """Atomically write exactly one manifest and one chart payload."""

    payload = build_chart_payload(result)
    output = Path(output_directory)
    if output.is_symlink():
        raise ValueError("viewer bundle destination must not be a symlink")
    if output.exists():
        if output.is_symlink() or not output.is_dir():
            raise ValueError("viewer bundle destination must be a real directory")
        if any(output.iterdir()):
            raise ValueError("viewer bundle destination must be absent or empty")
    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    payload_bytes = _canonical_json_bytes(payload)
    member = {
        "name": _BUNDLE_MEMBER_NAME,
        "sha256": _sha256(payload_bytes),
        "byte_length": len(payload_bytes),
    }
    manifest_semantics = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "payload_id": payload["payload_id"],
        "members": [member],
    }
    manifest = {
        **manifest_semantics,
        "bundle_id": _bundle_identity(manifest_semantics),
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=parent))
    try:
        for name, data in (
            ("chart_payload.json", payload_bytes),
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


__all__ = ["build_chart_payload", "write_viewer_bundle"]
