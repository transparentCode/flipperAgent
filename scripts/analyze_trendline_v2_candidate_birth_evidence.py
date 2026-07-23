"""Study causal candidate birth evidence and exact structural continuation.

This module reads only the verified Phase 8V.1 and Phase 9A artifacts. It never
calls a provider, fetches data, ranks candidates, or writes runtime settings.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import median
import tempfile
from typing import Any, Mapping, Sequence

from libs.models.trendline_v2.domain.candidates import LineCandidate
from libs.models.trendline_v2.domain.identity import canonical_json, deterministic_hash
from libs.models.trendline_v2.domain.provider_input import ProviderInput
from scripts import analyze_trendline_v2_candidate_density as phase9a


ASSET = "BTCUSDT"
TIMEFRAME = "4h"
SOURCE_ROOT = Path(
    "/tmp/trendline_v2_real_asset_smoke/btcusdt_4h_20250801_20251201"
)
PHASE9A_ROOT = Path(
    "/tmp/trendline_v2_phase9a_density/btcusdt_4h_20250801_20251201"
)
OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_phase9b1_birth_evidence/"
    "btcusdt_4h_20250801_20251201"
)
STUDY_SCHEMA_VERSION = "trendline_v2_phase_9b1_birth_evidence_v1"
SOURCE_IDENTITY = (
    "079b7cec1dde131fb91180ee910cdb84499d27bb4ac64cd1ca46eaf355fc0358"
)
PHASE9A_STUDY_ID = (
    "8b8ea045a5e14293224250602024a3234b91e023fbac4f70e0011d6c914f1f46"
)
PHASE9A_MATRIX_ID = (
    "a19a6bbee86f57a5c28bc67db33398d043f161ddc4bbe1403b4898788a8c19f6"
)
PHASE9A_DECISION_ID = (
    "587712c9a36228161f80c63a4fdcb5bc40403ff2de83c7e144eb849839080089"
)
EXPECTED_PROVIDER_RESULT_SHA = (
    "6f15a2fc192e61a47c365509fa824cb11834161d6ee9b1c5a352f6ca816d5175"
)
EXPECTED_VIEWER_PAYLOAD_ID = (
    "9c1c42bf89eaa85c33af4a4787beabd5f1ce3e0c26fe02babe0bb82ab4cc2e51"
)
EXPECTED_VIEWER_BUNDLE_ID = (
    "d56fc53daa4e6c69b189c5ebb72c46f87f67f23056238765106e21c3a3bc41c3"
)
EXPECTED_SOURCE_INVENTORY_SHA256 = (
    "982ea7b1f269e7d0c3a40f4f3b8dd4fa01f8f43a80e081743da1fa37e18c6022"
)
EXPECTED_PHASE9A_INVENTORY_SHA256 = (
    "296eb1770da76189e184eca902c4ff3c3aa979b34fd987786e18333ca4cf7fed"
)
EXPECTED_ROWS = 732
EXPECTED_CANDIDATES = 2697
EXPECTED_SUPPORT = 1501
EXPECTED_RESISTANCE = 1196
BAR_INTERVAL = timedelta(hours=4)
DAY_SECONDS = 86_400
HORIZONS = (6, 12, 24)
ROLES = ("support", "resistance")
SEGMENTS = ("early", "late")
MID_BOUNDARY = datetime(2025, 10, 1, tzinfo=timezone.utc)
CONFIRMATION_POLICY = "leftmost_strict_left_nonstrict_right_v1"
EXTREMA_LEFT = 1
EXTREMA_RIGHT = 1
STRUCTURE_NAMESPACE = "trendline_v2_phase_9a_candidate_structure_v1"
FEATURES = (
    "anchor_span_bars",
    "absolute_slope_bps_per_day",
    "same_role_extrema_skip_count",
    "minimum_body_clearance_bps",
    "median_body_clearance_bps",
    "minimum_anchor_prominence_bps",
    "mean_anchor_prominence_bps",
)
SPAN_BUCKETS = (
    ("2-6", 2, 6),
    ("7-12", 7, 12),
    ("13-24", 13, 24),
    ("25-48", 25, 48),
    ("49-96", 49, 96),
    ("97+", 97, None),
)
SKIP_BUCKETS = (
    ("0", 0, 0),
    ("1", 1, 1),
    ("2-3", 2, 3),
    ("4-7", 4, 7),
    ("8+", 8, None),
)
UTC = timezone.utc
NANOSECONDS = 1_000_000_000


class StudyArtifactError(RuntimeError):
    """Verified local evidence is missing, altered, or semantically invalid."""


@dataclass(frozen=True, slots=True)
class ResearchExtremum:
    kind: str
    source_position: int
    confirmation_position: int
    price: float


@dataclass(frozen=True, slots=True)
class StudyBinding:
    """Immutable identity/count binding for real or synthetic study evidence."""

    source_identity: str
    phase9a_study_id: str
    phase9a_matrix_id: str
    phase9a_decision_id: str
    source_inventory_sha256: str
    phase9a_inventory_sha256: str
    expected_candidate_count: int
    expected_support_count: int
    expected_resistance_count: int


REAL_BINDING = StudyBinding(
    source_identity=SOURCE_IDENTITY,
    phase9a_study_id=PHASE9A_STUDY_ID,
    phase9a_matrix_id=PHASE9A_MATRIX_ID,
    phase9a_decision_id=PHASE9A_DECISION_ID,
    source_inventory_sha256=EXPECTED_SOURCE_INVENTORY_SHA256,
    phase9a_inventory_sha256=EXPECTED_PHASE9A_INVENTORY_SHA256,
    expected_candidate_count=EXPECTED_CANDIDATES,
    expected_support_count=EXPECTED_SUPPORT,
    expected_resistance_count=EXPECTED_RESISTANCE,
)


def _canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise StudyArtifactError(f"artifact cannot be read: {path}") from exc


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
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise StudyArtifactError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise StudyArtifactError(f"artifact must be an object: {path}")
    if path.read_bytes() != _canonical_bytes(value):
        raise StudyArtifactError(f"artifact is not canonical JSON: {path}")
    return value


def _require_equal(actual: object, expected: object, *, field_name: str) -> None:
    if actual != expected:
        raise StudyArtifactError(
            f"{field_name} mismatch: expected {expected!r}, got {actual!r}"
        )


def _require_sha(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise StudyArtifactError(f"{field_name} must be lowercase SHA-256")
    return value


def _parse_utc(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise StudyArtifactError(f"{field_name} must be an ISO UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StudyArtifactError(f"{field_name} is not a timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise StudyArtifactError(f"{field_name} must be UTC")
    return parsed.astimezone(UTC)


def _datetime_from_ns(timestamp_ns: int) -> datetime:
    seconds, remainder = divmod(timestamp_ns, NANOSECONDS)
    return datetime.fromtimestamp(seconds, tz=UTC) + timedelta(
        microseconds=remainder // 1_000
    )


def _iso(timestamp: datetime) -> str:
    return timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _finite(value: float, *, field_name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise StudyArtifactError(f"{field_name} must be finite")
    return value


def _bps(delta: float, base: float, *, field_name: str) -> float:
    base = _finite(base, field_name=f"{field_name}.base")
    if base == 0.0:
        raise StudyArtifactError(f"{field_name} base cannot be zero")
    return _finite(delta / abs(base) * 10_000.0, field_name=field_name)


def _percentile95(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return float(ordered[index])


def _stats(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {
            "eligible_sample_count": 0,
            "unique_value_count": 0,
            "minimum": None,
            "median": None,
            "p95": None,
            "maximum": None,
        }
    ordered = [_finite(value, field_name="feature value") for value in values]
    return {
        "eligible_sample_count": len(ordered),
        "unique_value_count": len(set(ordered)),
        "minimum": min(ordered),
        "median": float(median(ordered)),
        "p95": _percentile95(ordered),
        "maximum": max(ordered),
    }


def _rankdata(values: Sequence[float]) -> tuple[float, ...]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(indexed):
        end = cursor + 1
        while end < len(indexed) and indexed[end][1] == indexed[cursor][1]:
            end += 1
        rank = (cursor + 1 + end) / 2.0
        for index in range(cursor, end):
            ranks[indexed[index][0]] = rank
        cursor = end
    return tuple(ranks)


def _spearman(
    x_values: Sequence[float], y_values: Sequence[int | bool]
) -> tuple[float | None, str | None]:
    if len(x_values) != len(y_values):
        return None, "length_mismatch"
    if len(x_values) < 2:
        return None, "insufficient_evaluation_rows"
    x = tuple(_finite(value, field_name="association feature") for value in x_values)
    y = tuple(float(value) for value in y_values)
    if len(set(x)) <= 1:
        return None, "feature_constant"
    if len(set(y)) <= 1:
        return None, "outcome_constant"
    xr = _rankdata(x)
    yr = _rankdata(y)
    x_mean = sum(xr) / len(xr)
    y_mean = sum(yr) / len(yr)
    numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(xr, yr))
    denominator_x = math.sqrt(sum((a - x_mean) ** 2 for a in xr))
    denominator_y = math.sqrt(sum((b - y_mean) ** 2 for b in yr))
    if denominator_x == 0.0 or denominator_y == 0.0:
        return None, "rank_constant"
    return numerator / (denominator_x * denominator_y), None


def candidate_structure_id(candidate: LineCandidate) -> str:
    """Research-only identity matching Phase 9A structure semantics."""

    return deterministic_hash(
        STRUCTURE_NAMESPACE,
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


def extract_confirmed_extrema(
    values: Sequence[float],
    *,
    positions: Sequence[int] | None = None,
    kind: str,
    left: int = EXTREMA_LEFT,
    right: int = EXTREMA_RIGHT,
) -> tuple[ResearchExtremum, ...]:
    """Independent causal scanner for left-strict/right-nonstrict extrema."""

    if kind not in {"high", "low"}:
        raise StudyArtifactError(f"unsupported extrema kind: {kind}")
    positions = tuple(range(len(values))) if positions is None else tuple(positions)
    if len(positions) != len(values):
        raise StudyArtifactError("extrema positions and values must align")
    extrema: list[ResearchExtremum] = []
    for relative in range(left, len(positions) - right):
        value = float(values[relative])
        left_values = tuple(float(values[index]) for index in range(relative - left, relative))
        right_values = tuple(
            float(values[index])
            for index in range(relative + 1, relative + right + 1)
        )
        if kind == "high":
            valid = all(value > neighbor for neighbor in left_values) and all(
                value >= neighbor for neighbor in right_values
            )
        else:
            valid = all(value < neighbor for neighbor in left_values) and all(
                value <= neighbor for neighbor in right_values
            )
        if valid:
            extrema.append(
                ResearchExtremum(
                    kind=kind,
                    source_position=positions[relative],
                    confirmation_position=positions[relative + right],
                    price=value,
                )
            )
    return tuple(extrema)


def _reconstruct_extrema(input_data: ProviderInput) -> dict[str, tuple[ResearchExtremum, ...]]:
    return {
        "support": extract_confirmed_extrema(
            input_data.low, kind="low"
        ),
        "resistance": extract_confirmed_extrema(
            input_data.high, kind="high"
        ),
    }


def _bucket(value: int, buckets: Sequence[tuple[str, int, int | None]]) -> str:
    for name, lower, upper in buckets:
        if value >= lower and (upper is None or value <= upper):
            return name
    raise StudyArtifactError(f"value has no bucket: {value}")


def _body_clearance(
    candidate: LineCandidate,
    evidence: Any,
    input_data: ProviderInput,
) -> dict[str, float | None]:
    first, second = evidence.anchor_source_positions
    clearances: list[float] = []
    for position in range(first + 1, second):
        projected = _finite(
            candidate.geometry.value_at(_datetime_from_ns(input_data.timestamps[position])),
            field_name="projected line price",
        )
        body_floor = min(input_data.open[position], input_data.close[position])
        body_ceiling = max(input_data.open[position], input_data.close[position])
        clearance = (
            body_floor - projected
            if candidate.role.value == "support"
            else projected - body_ceiling
        )
        if clearance < -1e-9:
            raise StudyArtifactError("persisted candidate has negative body clearance")
        clearances.append(max(0.0, clearance))
    normalized = tuple(
        _bps(
            value,
            candidate.geometry.value_at(
                _datetime_from_ns(input_data.timestamps[first + 1 + offset])
            ),
            field_name="body clearance bps",
        )
        for offset, value in enumerate(clearances)
    )
    return {
        "minimum_body_clearance_bps": min(normalized) if normalized else 0.0,
        "median_body_clearance_bps": float(median(normalized)) if normalized else 0.0,
        "maximum_body_clearance_bps": max(normalized) if normalized else 0.0,
    }


def _prominence(
    candidate: LineCandidate,
    evidence: Any,
    input_data: ProviderInput,
    *,
    availability_position: int,
) -> dict[str, float]:
    values: list[float] = []
    for source_position, anchor in zip(
        evidence.anchor_source_positions, candidate.anchors
    ):
        neighbors = (source_position - 1, source_position + 1)
        if min(neighbors) < 0 or max(neighbors) >= availability_position:
            raise StudyArtifactError("anchor prominence reads beyond birth boundary")
        if candidate.role.value == "support":
            raw = min(input_data.low[position] for position in neighbors) - anchor.price
        else:
            raw = anchor.price - max(input_data.high[position] for position in neighbors)
        values.append(_bps(raw, anchor.price, field_name="anchor prominence"))
    return {
        "first_anchor_prominence_bps": values[0],
        "second_anchor_prominence_bps": values[1],
        "minimum_anchor_prominence_bps": min(values),
        "mean_anchor_prominence_bps": sum(values) / len(values),
    }


def _future_evaluation(
    candidate: LineCandidate,
    input_data: ProviderInput,
    *,
    availability_position: int,
    horizon: int,
) -> dict[str, Any]:
    end = availability_position + horizon
    if end > input_data.row_count:
        return {
            "evaluation_available": False,
            "future_contact_count": None,
            "future_contact_without_body_violation_count": None,
            "future_body_violation_count": None,
            "has_exact_contact": None,
            "survives_exact_side": None,
            "contact_and_survives_exact_side": None,
            "first_contact_offset_bars": None,
            "first_body_violation_offset_bars": None,
        }
    contacts = 0
    contact_without_violation = 0
    violations = 0
    first_contact: int | None = None
    first_violation: int | None = None
    for offset, position in enumerate(range(availability_position, end)):
        projected = _finite(
            candidate.geometry.value_at(_datetime_from_ns(input_data.timestamps[position])),
            field_name="future projected line price",
        )
        contact = input_data.low[position] <= projected <= input_data.high[position]
        body_floor = min(input_data.open[position], input_data.close[position])
        body_ceiling = max(input_data.open[position], input_data.close[position])
        violation = (
            projected > body_floor
            if candidate.role.value == "support"
            else projected < body_ceiling
        )
        if contact:
            contacts += 1
            first_contact = offset if first_contact is None else first_contact
        if violation:
            violations += 1
            first_violation = offset if first_violation is None else first_violation
        if contact and not violation:
            contact_without_violation += 1
    survives = violations == 0
    return {
        "evaluation_available": True,
        "future_contact_count": contacts,
        "future_contact_without_body_violation_count": contact_without_violation,
        "future_body_violation_count": violations,
        "has_exact_contact": contacts > 0,
        "survives_exact_side": survives,
        "contact_and_survives_exact_side": contacts > 0 and survives,
        "first_contact_offset_bars": first_contact,
        "first_body_violation_offset_bars": first_violation,
    }


def build_candidate_record(
    candidate: LineCandidate,
    evidence: Any,
    input_data: ProviderInput,
    extrema_by_role: Mapping[str, Sequence[ResearchExtremum]],
) -> dict[str, Any]:
    if evidence.candidate_id != candidate.candidate_id:
        raise StudyArtifactError("candidate/evidence IDs are not one-to-one")
    source_positions = tuple(evidence.anchor_source_positions)
    confirmation_positions = tuple(evidence.confirmation_positions)
    if len(source_positions) != 2 or len(confirmation_positions) != 2:
        raise StudyArtifactError("candidate requires two source/confirmation pairs")
    if any(position < 0 or position >= input_data.row_count for position in (*source_positions, *confirmation_positions)):
        raise StudyArtifactError("candidate evidence position is outside source")
    last_confirmation_position = max(confirmation_positions)
    availability_position = last_confirmation_position + 1
    if availability_position > input_data.row_count:
        raise StudyArtifactError("candidate availability position is outside source")
    confirmation_bar_open = _datetime_from_ns(
        input_data.timestamps[last_confirmation_position]
    )
    if input_data.timestamps[last_confirmation_position] % NANOSECONDS != 0:
        raise StudyArtifactError("confirmation timestamp is not whole-second UTC")
    candidate_available_at = confirmation_bar_open + BAR_INTERVAL
    if candidate_available_at > input_data.confirmed_through:
        raise StudyArtifactError("candidate available after confirmed boundary")
    if any(position >= availability_position for position in confirmation_positions):
        raise StudyArtifactError("confirmation is not complete before availability")
    first, second = candidate.anchors
    first_position, second_position = source_positions
    span_bars = second_position - first_position
    if span_bars <= 0:
        raise StudyArtifactError("anchor span must be positive")
    if evidence.validated_intermediate_count != span_bars - 1:
        raise StudyArtifactError("intermediate count does not match anchor span")
    span_seconds = (
        input_data.timestamps[second_position] - input_data.timestamps[first_position]
    ) / NANOSECONDS
    price_change_bps = _bps(
        second.price - first.price,
        first.price,
        field_name="anchor price change",
    )
    slope_bps_per_day = _bps(
        second.price - first.price,
        first.price,
        field_name="slope",
    ) / (span_seconds / DAY_SECONDS)
    between = tuple(
        extremum
        for extremum in extrema_by_role[candidate.role.value]
        if (
            first_position < extremum.source_position < second_position
            and extremum.confirmation_position < availability_position
        )
    )
    clearance = _body_clearance(candidate, evidence, input_data)
    prominence = _prominence(
        candidate,
        evidence,
        input_data,
        availability_position=availability_position,
    )
    segment = "early" if candidate_available_at < MID_BOUNDARY else "late"
    record = {
        "candidate_id": candidate.candidate_id,
        "candidate_structure_id": candidate_structure_id(candidate),
        "role": candidate.role.value,
        "first_anchor_id": first.anchor_id,
        "second_anchor_id": second.anchor_id,
        "first_anchor_time": _iso(first.pivot_time),
        "second_anchor_time": _iso(second.pivot_time),
        "anchor_source_positions": list(source_positions),
        "confirmation_positions": list(confirmation_positions),
        "confirmation_bar_open": _iso(confirmation_bar_open),
        "candidate_available_at": _iso(candidate_available_at),
        "availability_position": availability_position,
        "chronological_segment": segment,
        "anchor_span_bars": span_bars,
        "anchor_span_seconds": span_seconds,
        "anchor_price_change_bps": price_change_bps,
        "slope_bps_per_day": slope_bps_per_day,
        "absolute_slope_bps_per_day": abs(slope_bps_per_day),
        "same_role_confirmed_extrema_between_anchors": len(between),
        "same_role_extrema_skip_count": len(between),
        **clearance,
        **prominence,
        "anchor_span_bucket": _bucket(span_bars, SPAN_BUCKETS),
        "same_role_extrema_skip_bucket": _bucket(
            len(between), SKIP_BUCKETS
        ),
        "evaluations": {
            str(horizon): _future_evaluation(
                candidate,
                input_data,
                availability_position=availability_position,
                horizon=horizon,
            )
            for horizon in HORIZONS
        },
    }
    return record


def _validate_phase9a_artifacts(
    phase9a_root: Path,
    source_audit: Mapping[str, Any],
    *,
    binding: StudyBinding = REAL_BINDING,
) -> dict[str, Any]:
    if not phase9a_root.is_dir() or phase9a_root.is_symlink():
        raise StudyArtifactError("BLOCKED_SOURCE_ARTIFACT: Phase 9A root missing")
    _validate_canonical_json_tree(phase9a_root)
    inventory = _artifact_inventory(phase9a_root)
    _require_equal(
        _inventory_digest(inventory),
        binding.phase9a_inventory_sha256,
        field_name="Phase 9A inventory SHA-256",
    )
    matrix = _load_json(phase9a_root / "matrix.json")
    decision = _load_json(phase9a_root / "decision.json")
    saved_source_audit = _load_json(phase9a_root / "source_audit.json")
    _require_equal(saved_source_audit, dict(source_audit), field_name="Phase 9A source audit")
    _require_equal(matrix.get("study_id"), binding.phase9a_study_id, field_name="Phase 9A study_id")
    _require_equal(matrix.get("matrix_id"), binding.phase9a_matrix_id, field_name="Phase 9A matrix_id")
    _require_equal(decision.get("decision_id"), binding.phase9a_decision_id, field_name="Phase 9A decision_id")
    _require_equal(decision.get("PARAMETER_PROMOTION"), "NOT_AUTHORIZED", field_name="Phase 9A promotion")
    _require_equal(matrix.get("window_boundary_policy"), phase9a.WINDOW_BOUNDARY_POLICY, field_name="Phase 9A boundary policy")
    if "candidate_id_persistence_ratio" in canonical_json(matrix):
        raise StudyArtifactError("obsolete Phase 9A candidate ID persistence field present")
    matrix_without_id = dict(matrix)
    matrix_without_id.pop("matrix_id", None)
    _require_equal(
        deterministic_hash("trendline_v2_phase_9a_density_matrix", matrix_without_id),
        matrix["matrix_id"],
        field_name="Phase 9A matrix hash",
    )
    study_keys = (
        "schema_version",
        "source_identity",
        "asset",
        "timeframe",
        "window_boundary_policy",
        "baseline",
        "configurations",
        "windows",
        "semantic_execution_count",
        "deterministic_repeat_count",
    )
    study_semantics = {key: matrix[key] for key in study_keys}
    _require_equal(
        deterministic_hash("trendline_v2_phase_9a_density_study", study_semantics),
        matrix["study_id"],
        field_name="Phase 9A study hash",
    )
    decision_without_id = dict(decision)
    decision_without_id.pop("decision_id", None)
    _require_equal(
        deterministic_hash(
            "trendline_v2_phase_9a_density_decision", decision_without_id
        ),
        decision["decision_id"],
        field_name="Phase 9A decision hash",
    )
    run_entries = matrix.get("runs")
    if not isinstance(run_entries, list) or len(run_entries) != 28:
        raise StudyArtifactError("Phase 9A must contain exactly 28 run entries")
    run_records: list[dict[str, Any]] = []
    for entry in run_entries:
        run_id = entry.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise StudyArtifactError("Phase 9A run ID is invalid")
        record = _load_json(phase9a_root / "runs" / f"{run_id}.json")
        _require_equal(record.get("run_id"), run_id, field_name="Phase 9A run ID")
        lookback = float(record["configuration"]["lookback_duration_seconds"])
        expected_history = {
            1_382_400.0: 96,
            2_764_800.0: 192,
            5_270_400.0: 366,
            10_540_800.0: 732,
        }[lookback]
        expected_history = min(expected_history, int(record["window"]["row_count"]))
        _require_equal(record.get("history_row_count"), expected_history, field_name="Phase 9A history_row_count")
        if "candidate_id_persistence_ratio" in canonical_json(record):
            raise StudyArtifactError("obsolete candidate ID persistence field present")
        run_records.append(record)
    expected_members = {
        "source_audit.json",
        "matrix.json",
        "summary.csv",
        "decision.json",
        *(f"runs/{record['run_id']}.json" for record in run_records),
    }
    actual_members = {
        str(path.relative_to(phase9a_root))
        for path in phase9a_root.rglob("*")
        if path.is_file()
    }
    if actual_members != expected_members:
        raise StudyArtifactError("Phase 9A member set mismatch")
    files = tuple(
        {
            "path": name,
            "byte_length": (phase9a_root / name).stat().st_size,
            "sha256": _require_sha(
                _sha256_file(phase9a_root / name),
                field_name=f"Phase 9A file {name}",
            ),
        }
        for name in sorted(actual_members)
    )
    return {
        "study_id": binding.phase9a_study_id,
        "matrix_id": binding.phase9a_matrix_id,
        "decision_id": binding.phase9a_decision_id,
        "files": list(files),
        "inventory_sha256": _inventory_digest(inventory),
        "run_records": run_records,
    }


def _load_context(
    *,
    source_root: Path = SOURCE_ROOT,
    phase9a_root: Path = PHASE9A_ROOT,
    binding: StudyBinding = REAL_BINDING,
) -> tuple[dict[str, Any], ProviderInput, tuple[LineCandidate, ...], tuple[Any, ...]]:
    try:
        _validate_canonical_json_tree(source_root)
        source_inventory = _artifact_inventory(source_root)
        _require_equal(
            _inventory_digest(source_inventory),
            binding.source_inventory_sha256,
            field_name="source inventory SHA-256",
        )
        source_audit = phase9a._validate_source_bundle(source_root)
    except Exception as exc:
        raise StudyArtifactError("Phase 8V.1 source validation failed") from exc
    _require_equal(source_audit["source_identity"], binding.source_identity, field_name="source identity")
    _require_equal(
        source_audit["run_report"]["viewer_payload_id"],
        EXPECTED_VIEWER_PAYLOAD_ID,
        field_name="viewer payload ID",
    )
    _require_equal(
        source_audit["run_report"]["viewer_bundle_id"],
        EXPECTED_VIEWER_BUNDLE_ID,
        field_name="viewer bundle ID",
    )
    source_payload = phase9a._load_json(source_root / "provider_result.json")
    result = phase9a._typed_source_result(source_payload)
    _require_equal(
        _sha256_file(source_root / "provider_result.json"),
        EXPECTED_PROVIDER_RESULT_SHA,
        field_name="provider result SHA",
    )
    _require_equal(result.request.asset, ASSET, field_name="source asset")
    _require_equal(result.request.timeframe, TIMEFRAME, field_name="source timeframe")
    _require_equal(result.request.input_data.row_count, EXPECTED_ROWS, field_name="source row count")
    _require_equal(
        len(result.candidates),
        binding.expected_candidate_count,
        field_name="candidate count",
    )
    _require_equal(
        len(result.evidence),
        binding.expected_candidate_count,
        field_name="evidence count",
    )
    _require_equal(
        sum(candidate.role.value == "support" for candidate in result.candidates),
        binding.expected_support_count,
        field_name="support count",
    )
    _require_equal(
        sum(candidate.role.value == "resistance" for candidate in result.candidates),
        binding.expected_resistance_count,
        field_name="resistance count",
    )
    phase9a_audit = _validate_phase9a_artifacts(
        phase9a_root,
        source_audit,
        binding=binding,
    )
    return (
        {
            "source_audit": source_audit,
            "phase9a": phase9a_audit,
            "viewer_payload_id": EXPECTED_VIEWER_PAYLOAD_ID,
            "viewer_bundle_id": EXPECTED_VIEWER_BUNDLE_ID,
        },
        result.request.input_data,
        tuple(result.candidates),
        tuple(result.evidence),
    )


def _cohort_metrics(records: Sequence[Mapping[str, Any]], horizon: int) -> dict[str, Any]:
    if not records:
        return {
            "candidate_count": 0,
            "unique_structure_count": 0,
            "unique_anchor_count": 0,
            "contact_rate": None,
            "exact_side_survival_rate": None,
            "contact_and_survival_rate": None,
            "median_body_clearance_bps": None,
            "median_anchor_prominence_bps": None,
            "median_anchor_span_bars": None,
        }
    evaluations = [record["evaluations"][str(horizon)] for record in records]
    count = len(records)
    return {
        "candidate_count": count,
        "unique_structure_count": len(
            {record["candidate_structure_id"] for record in records}
        ),
        "unique_anchor_count": len(
            {
                anchor_id
                for record in records
                for anchor_id in (record["first_anchor_id"], record["second_anchor_id"])
            }
        ),
        "contact_rate": sum(item["has_exact_contact"] for item in evaluations) / count,
        "exact_side_survival_rate": sum(
            item["survives_exact_side"] for item in evaluations
        ) / count,
        "contact_and_survival_rate": sum(
            item["contact_and_survives_exact_side"] for item in evaluations
        ) / count,
        "median_body_clearance_bps": float(
            median(record["median_body_clearance_bps"] for record in records)
        ),
        "median_anchor_prominence_bps": float(
            median(record["mean_anchor_prominence_bps"] for record in records)
        ),
        "median_anchor_span_bars": float(
            median(record["anchor_span_bars"] for record in records)
        ),
    }


def build_cohort_rows(records: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for role in ROLES:
        for segment in SEGMENTS:
            for horizon in HORIZONS:
                eligible = [
                    record
                    for record in records
                    if record["role"] == role
                    and record["chronological_segment"] == segment
                    and record["evaluations"][str(horizon)]["evaluation_available"]
                ]
                rows.append(
                    {
                        "cohort_kind": "role",
                        "cohort_value": role,
                        "role": role,
                        "chronological_segment": segment,
                        "horizon_bars": horizon,
                        **_cohort_metrics(eligible, horizon),
                    }
                )
                for bucket_name, _, _ in SPAN_BUCKETS:
                    bucket_records = [
                        record for record in eligible if record["anchor_span_bucket"] == bucket_name
                    ]
                    rows.append(
                        {
                            "cohort_kind": "anchor_span_bucket",
                            "cohort_value": bucket_name,
                            "role": role,
                            "chronological_segment": segment,
                            "horizon_bars": horizon,
                            **_cohort_metrics(bucket_records, horizon),
                        }
                    )
                for bucket_name, _, _ in SKIP_BUCKETS:
                    bucket_records = [
                        record
                        for record in eligible
                        if record["same_role_extrema_skip_bucket"] == bucket_name
                    ]
                    rows.append(
                        {
                            "cohort_kind": "same_role_extrema_skip_bucket",
                            "cohort_value": bucket_name,
                            "role": role,
                            "chronological_segment": segment,
                            "horizon_bars": horizon,
                            **_cohort_metrics(bucket_records, horizon),
                        }
                    )
    return tuple(rows)


def build_feature_associations(
    records: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    classifications: dict[str, Any] = {}
    associations: dict[str, Any] = {}
    for feature in FEATURES:
        all_values = [float(record[feature]) for record in records]
        global_stats = _stats(all_values)
        unique_count = global_stats["unique_value_count"]
        classifications[feature] = {
            "classification": (
                "CAUSAL_NONDEGENERATE" if unique_count > 1 else "CAUSAL_DEGENERATE_ON_SOURCE"
            ),
            "reason": (
                "birth descriptor varies on verified source"
                if unique_count > 1
                else "birth descriptor has one unique value on verified source"
            ),
            "global_stats": global_stats,
        }
        by_group: dict[str, Any] = {}
        for role in ROLES:
            for segment in SEGMENTS:
                for horizon in HORIZONS:
                    eligible = [
                        record
                        for record in records
                        if record["role"] == role
                        and record["chronological_segment"] == segment
                        and record["evaluations"][str(horizon)]["evaluation_available"]
                    ]
                    key = f"{role}|{segment}|{horizon}"
                    values = [float(record[feature]) for record in eligible]
                    outcomes = {
                        outcome: [
                            int(record["evaluations"][str(horizon)][outcome])
                            for record in eligible
                        ]
                        for outcome in (
                            "survives_exact_side",
                            "contact_and_survives_exact_side",
                        )
                    }
                    correlations: dict[str, Any] = {}
                    undefined: dict[str, str] = {}
                    for outcome, outcome_values in outcomes.items():
                        value, reason = _spearman(values, outcome_values)
                        correlations[outcome] = value
                        if reason is not None:
                            undefined[outcome] = reason
                    by_group[key] = {
                        **_stats(values),
                        "spearman": correlations,
                        "undefined_reasons": undefined,
                    }
        associations[feature] = by_group
    return classifications, associations


def _write_atomic(path: Path, data: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"refusing existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
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


def _write_json(path: Path, value: object) -> None:
    _write_atomic(path, _canonical_bytes(value))


def _write_cohort_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = (
        "cohort_kind",
        "cohort_value",
        "role",
        "chronological_segment",
        "horizon_bars",
        "candidate_count",
        "unique_structure_count",
        "unique_anchor_count",
        "contact_rate",
        "exact_side_survival_rate",
        "contact_and_survival_rate",
        "median_body_clearance_bps",
        "median_anchor_prominence_bps",
        "median_anchor_span_bars",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
        newline="",
        encoding="utf-8",
    ) as handle:
        temporary = Path(handle.name)
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames, lineterminator="\n", extrasaction="raise"
        )
        writer.writeheader()
        writer.writerows({field: row[field] for field in fieldnames} for row in rows)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        if path.exists():
            raise FileExistsError(f"refusing output overwrite: {path}")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _artifact_inventory(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir() or root.is_symlink():
        raise StudyArtifactError(f"artifact root is missing or symlinked: {root}")
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if any(path.is_symlink() for path in root.rglob("*")):
        raise StudyArtifactError(f"artifact tree contains a symlink: {root}")
    return [
        {
            "path": str(path.relative_to(root)),
            "byte_length": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for path in files
    ]


def _inventory_digest(inventory: Sequence[Mapping[str, Any]]) -> str:
    return _sha256_bytes(_canonical_bytes(list(inventory)))


def _validate_canonical_json_tree(root: Path) -> None:
    for path in sorted(root.rglob("*.json")):
        _load_json(path)


def run_study(
    *,
    source_root: str | Path = SOURCE_ROOT,
    phase9a_root: str | Path = PHASE9A_ROOT,
    output_root: str | Path = OUTPUT_ROOT,
    _binding: StudyBinding | None = None,
    _context_override: tuple[
        dict[str, Any],
        ProviderInput,
        tuple[LineCandidate, ...],
        tuple[Any, ...],
    ] | None = None,
) -> dict[str, Path]:
    """Build one verified birth-evidence bundle without provider execution."""

    binding = REAL_BINDING if _binding is None else _binding
    source_root = Path(source_root)
    phase9a_root = Path(phase9a_root)
    output_root = Path(output_root)
    if output_root.exists():
        raise FileExistsError(f"refusing existing output root: {output_root}")
    _validate_canonical_json_tree(source_root)
    source_inventory_before = _artifact_inventory(source_root)
    source_inventory_sha256 = _inventory_digest(source_inventory_before)
    _require_equal(
        source_inventory_sha256,
        binding.source_inventory_sha256,
        field_name="source inventory SHA-256",
    )
    _validate_canonical_json_tree(phase9a_root)
    phase9a_inventory_before = _artifact_inventory(phase9a_root)
    phase9a_inventory_sha256 = _inventory_digest(phase9a_inventory_before)
    _require_equal(
        phase9a_inventory_sha256,
        binding.phase9a_inventory_sha256,
        field_name="Phase 9A inventory SHA-256",
    )
    if _context_override is None:
        context, input_data, candidates, evidence = _load_context(
            source_root=source_root,
            phase9a_root=phase9a_root,
            binding=binding,
        )
    else:
        context, input_data, candidates, evidence = _context_override
    _require_equal(
        context["source_audit"]["source_identity"],
        binding.source_identity,
        field_name="source identity",
    )
    _require_equal(
        context["phase9a"]["study_id"],
        binding.phase9a_study_id,
        field_name="Phase 9A study ID",
    )
    extrema_by_role = _reconstruct_extrema(input_data)
    records = [
        build_candidate_record(candidate, item, input_data, extrema_by_role)
        for candidate, item in zip(candidates, evidence)
    ]
    records.sort(
        key=lambda record: (
            record["role"],
            record["first_anchor_time"],
            record["second_anchor_time"],
            record["candidate_structure_id"],
            record["candidate_id"],
        )
    )
    if len(records) != binding.expected_candidate_count:
        raise StudyArtifactError("birth record count does not match binding")
    cohort_rows = build_cohort_rows(records)
    classifications, associations = build_feature_associations(records)
    feature_contract = {
        "schema_version": "trendline_v2_phase_9b1_feature_contract_v1",
        "causal_boundary": "candidate_available_at=confirmation_bar_close_v1",
        "provider_execution_count": 0,
        "structure_identity": {
            "namespace": STRUCTURE_NAMESPACE,
            "classification": "RESEARCH_ONLY / NOT_MODEL_IDENTITY / NOT_TRACKING_IDENTITY / NOT_RUNTIME_IDENTITY",
        },
        "extrema": {
            "policy": CONFIRMATION_POLICY,
            "left_confirmation_bars": EXTREMA_LEFT,
            "right_confirmation_bars": EXTREMA_RIGHT,
            "implementation": "independent_research_scanner_v1",
        },
        "birth_descriptors": {
            feature: {
                "unit": "bars" if feature in {"anchor_span_bars", "same_role_extrema_skip_count"} else "basis_points",
                "future_positions_allowed": False,
            }
            for feature in FEATURES
        },
        "forward_horizons_bars": list(HORIZONS),
        "future_labels": [
            "future_contact_count",
            "future_contact_without_body_violation_count",
            "future_body_violation_count",
            "has_exact_contact",
            "survives_exact_side",
            "contact_and_survives_exact_side",
            "first_contact_offset_bars",
            "first_body_violation_offset_bars",
        ],
        "forbidden_semantics": [
            "ATR",
            "tolerance_band",
            "bounce",
            "rejection",
            "breakout",
            "breakdown",
            "retest",
            "role_reversal",
        ],
    }
    evaluation_support = {
        str(horizon): {
            "evaluated_candidate_count": sum(
                record["evaluations"][str(horizon)]["evaluation_available"]
                for record in records
            ),
            "unevaluated_candidate_count": sum(
                not record["evaluations"][str(horizon)]["evaluation_available"]
                for record in records
            ),
            "by_segment": {
                segment: sum(
                    record["chronological_segment"] == segment
                    and record["evaluations"][str(horizon)]["evaluation_available"]
                    for record in records
                )
                for segment in SEGMENTS
            },
        }
        for horizon in HORIZONS
    }
    cohort_support = {
        "row_count": len(cohort_rows),
        "nonempty_row_count": sum(row["candidate_count"] > 0 for row in cohort_rows),
        "empty_row_count": sum(row["candidate_count"] == 0 for row in cohort_rows),
    }
    decision_semantics = {
        "schema_version": STUDY_SCHEMA_VERSION,
        "source_identity": context["source_audit"]["source_identity"],
        "phase9a_study_id": context["phase9a"]["study_id"],
        "candidate_count": len(records),
        "support_count": sum(record["role"] == "support" for record in records),
        "resistance_count": sum(record["role"] == "resistance" for record in records),
        "birth_feature_contract_status": "PASSED",
        "causal_separation_status": "PASSED",
        "evaluation_support_by_horizon": evaluation_support,
        "cohort_support": cohort_support,
        "feature_architecture_classification": classifications,
        "feature_associations": associations,
        "limitations": [
            "one verified BTCUSDT 4h source window",
            "descriptive exact-side continuation only",
            "no score, threshold, eligibility rule, or parameter selection",
            "structure fingerprints are not model or tracking identities",
            "chronological segments are descriptive and are not validation splits",
            "Candidate records share anchors and overlapping geometry. Cohort rates and Spearman associations are candidate-weighted descriptive evidence, not independent-sample or inferential evidence.",
        ],
        "QUALITY_SCORE_SELECTION": "NOT_AUTHORIZED",
        "ELIGIBILITY_RULE_SELECTION": "NOT_AUTHORIZED",
        "PARAMETER_PROMOTION": "NOT_AUTHORIZED",
        "TRACKER_START": "NOT_AUTHORIZED",
    }
    decision = {
        **decision_semantics,
        "study_status": "DESCRIPTIVE_EVIDENCE_ONLY",
        "study_id": deterministic_hash(
            "trendline_v2_phase_9b1_birth_evidence", decision_semantics
        ),
    }
    source_audit = {
        "schema_version": "trendline_v2_phase_9b1_source_audit_v1",
        "source_identity": context["source_audit"]["source_identity"],
        "source_files": source_inventory_before,
        "phase9a_study_id": context["phase9a"]["study_id"],
        "phase9a_matrix_id": context["phase9a"]["matrix_id"],
        "phase9a_decision_id": context["phase9a"]["decision_id"],
        "phase9a_files": phase9a_inventory_before,
        "source_inventory_sha256": source_inventory_sha256,
        "phase9a_inventory_sha256": phase9a_inventory_sha256,
        "post_run_source_inventory_sha256": None,
        "post_run_phase9a_inventory_sha256": None,
        "source_immutability_verified": False,
        "candidate_count": len(records),
        "provider_execution_count": 0,
        "network_request_count": 0,
    }
    records_payload = {
        "schema_version": "trendline_v2_phase_9b1_candidate_records_v1",
        "source_identity": source_audit["source_identity"],
        "phase9a_study_id": binding.phase9a_study_id,
        "candidate_count": len(records),
        "records": records,
    }
    output_members = tuple(
        sorted(
            (
                "source_audit.json",
                "feature_contract.json",
                "candidate_records.json",
                "cohort_summary.csv",
                "feature_associations.json",
                "decision.json",
            )
        )
    )
    study_id = decision["study_id"]
    manifest_semantics = {
        "schema_version": "trendline_v2_phase_9b1_manifest_v1",
        "study_id": study_id,
        "source_identity": source_audit["source_identity"],
        "phase9a_study_id": binding.phase9a_study_id,
        "phase9a_matrix_id": binding.phase9a_matrix_id,
        "phase9a_decision_id": binding.phase9a_decision_id,
        "source_inventory_sha256": source_inventory_sha256,
        "phase9a_inventory_sha256": phase9a_inventory_sha256,
        "candidate_count": len(records),
        "provider_execution_count": 0,
        "network_request_count": 0,
        "members": list(output_members),
    }
    # Write data first; source audit and manifest bind final source inventories.
    _write_json(output_root / "feature_contract.json", feature_contract)
    _write_json(output_root / "candidate_records.json", records_payload)
    _write_cohort_csv(output_root / "cohort_summary.csv", cohort_rows)
    _write_json(output_root / "feature_associations.json", {
        "schema_version": "trendline_v2_phase_9b1_feature_associations_v1",
        "source_identity": source_audit["source_identity"],
        "classifications": classifications,
        "associations": associations,
    })
    _write_json(output_root / "decision.json", decision)
    post_source_inventory = _artifact_inventory(source_root)
    post_phase9a_inventory = _artifact_inventory(phase9a_root)
    if post_source_inventory != source_inventory_before:
        raise StudyArtifactError("Phase 8V.1 source changed during study")
    if post_phase9a_inventory != phase9a_inventory_before:
        raise StudyArtifactError("Phase 9A source changed during study")
    source_audit["post_run_source_inventory_sha256"] = _inventory_digest(
        post_source_inventory
    )
    source_audit["post_run_phase9a_inventory_sha256"] = _inventory_digest(
        post_phase9a_inventory
    )
    source_audit["source_immutability_verified"] = True
    _write_json(output_root / "source_audit.json", source_audit)
    manifest = {
        **manifest_semantics,
        "members": [
            {
                "path": name,
                "byte_length": (output_root / name).stat().st_size,
                "sha256": _sha256_file(output_root / name),
            }
            for name in output_members
        ],
    }
    manifest["manifest_id"] = deterministic_hash(
        "trendline_v2_phase_9b1_manifest", manifest
    )
    _write_json(output_root / "manifest.json", manifest)
    if _artifact_inventory(source_root) != source_inventory_before:
        raise StudyArtifactError("Phase 8V.1 source changed after artifact write")
    if _artifact_inventory(phase9a_root) != phase9a_inventory_before:
        raise StudyArtifactError("Phase 9A source changed after artifact write")
    return {
        name.removesuffix(".json").removesuffix(".csv"): output_root / name
        for name in (*output_members, "manifest.json")
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--phase9a-root", type=Path, default=PHASE9A_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    try:
        paths = run_study(
            source_root=args.source_root,
            phase9a_root=args.phase9a_root,
            output_root=args.output_root,
        )
    except (StudyArtifactError, FileExistsError) as exc:
        print(str(exc))
        return 2
    print(json.dumps({name: str(path) for name, path in paths.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
