"""Run and verify the bounded Phase 11S.1 structural-selection study.

This module is an offline research boundary.  It consumes only the verified
Phase 9C.2 and Phase 10C.2 bundles, never calls a provider, and never changes
runtime selection behavior.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import tempfile
from typing import Any, Mapping, Sequence

from libs.models.trendline_v2.domain.identity import canonical_json, deterministic_hash
from libs.models.trendline_v2.domain.validation import ContractValidationError
from scripts import analyze_trendline_v2_fresh_scope_family_validation as phase9c2
from scripts import replay_trendline_v2_lookback_eviction as phase10c2


UTC = timezone.utc
NANOSECONDS = 1_000_000_000
DAY_SECONDS = 86_400

SOURCE_ROOT = Path(
    "/tmp/trendline_v2_phase9c2_fresh_scope_family_validation/20260522_20260701"
)
TEMPORAL_ROOT = Path(
    "/tmp/trendline_v2_phase10c2_lookback_eviction/20251201_20260401"
)
OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_phase11s1_structural_selection/"
    "20260522_20260701__20250801_20260401"
)
PINNED_OUTPUT_INVENTORY = (
    "3731fd6d35472002eae4ae81cc9eb0d87bfcdfbc8552e44209ba1ede46b2c4b3"
)

STUDY_SCHEMA = "trendline_v2_phase_11s1_structural_selection_study_v1"
CONTRACT_SCHEMA = (
    "trendline_v2_phase_11s1_structural_selection_study_v1_contract"
)
CONTRACT_NAMESPACE = "trendline_v2_phase_11s1_structural_selection_study_contract"
CONTRACT_ID = "41c6054577193d64e4bf2ff985d40571e9f75427bfbf47508e3b673ee9e32b54"
LOCK_NAMESPACE = "trendline_v2_phase_11s1_validation_lock"
DECISION_NAMESPACE = "trendline_v2_phase_11s1_decision"
MANIFEST_NAMESPACE = "trendline_v2_phase_11s1_manifest"
RESULT_NAMESPACE = "trendline_v2_phase_11s1_selector_result"

PHASE9C2_DECISION_ID = (
    "4b734cbf99e1453bccdedb95f397f4b34e020f29e3d18808a131456647f78f7c"
)
PHASE9C2_MANIFEST_ID = (
    "beab5b9acb2bfc3c25ba9cb5cb31c33c1a31e6069c1d7906f3ed5e1c2d798c81"
)
PHASE9C2_OUTPUT_INVENTORY = (
    "ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532"
)
PHASE9C1_SOURCE_INVENTORY = (
    "631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be"
)
PHASE10C2_REPLAY_CONTRACT_ID = (
    "166b156a471f06dcc2d4fbf09196df95c4648e4b60cac52d1d315f7e7794af96"
)
PHASE10C2_DECISION_ID = (
    "ac26d26534e65472bc18c072eee1121ce5c7420b8c541264139bf1614b95c6b6"
)
PHASE10C2_MANIFEST_ID = (
    "4daff316405662de15a328bafd503740d38c7343cfe4616bb8096976d0466ef5"
)
PHASE10C2_OUTPUT_INVENTORY = (
    "64e9477e48a3d546dc39b5ac8d0fa6328d4dddd10b1c055ae3616bd1de2bf35c"
)
PHASE10C1_SOURCE_INVENTORY = (
    "872bffa5aa232bfbeac2788c4575a8e73b344476c75cfedb67b8014bc82b550f"
)

VALIDATION_DATASETS = ("btcusdt_1h", "btcusdt_4h", "ethusdt_1h", "ethusdt_4h")
HOLDOUT_DATASETS = ("suiusdt_1h", "suiusdt_4h")
ROLES = ("support", "resistance")
HORIZONS = ("24h", "48h", "96h")
HORIZON_HOURS = {"24h": 24, "48h": 48, "96h": 96}
INTERVAL_SECONDS = {"1h": 3_600, "4h": 14_400}
CONTENDERS = (
    "span_prominence_clearance_v1",
    "prominence_span_clearance_v1",
    "contact_span_prominence_v1",
    "multiswing_balanced_v1",
)
CONTROLS = (
    "hash_order_matched_budget_v1",
    "nearest_projection_matched_budget_v1",
)
BUDGETS = (4, 6, 8)


class StudyError(RuntimeError):
    """Expected bounded study or artifact failure."""


@dataclass(frozen=True, slots=True)
class ResearchCandidate:
    candidate: Any
    evidence: Any
    fields: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ScopeCheckpoint:
    dataset_id: str
    checkpoint_index: int
    checkpoint: datetime
    data: Any
    result: Any
    prefix_last_position: int
    source_provider_result_id: str


@dataclass(frozen=True, slots=True)
class ScopeDataset:
    dataset_id: str
    asset: str
    timeframe: str
    data: Any
    checkpoints: tuple[ScopeCheckpoint, ...]
    input_identity: str


def _canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _datetime_from_ns(value: int) -> datetime:
    seconds, remainder = divmod(int(value), NANOSECONDS)
    return datetime.fromtimestamp(seconds, tz=UTC) + timedelta(
        microseconds=remainder // 1_000
    )


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
        raise StudyError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict) or raw != _canonical_bytes(value):
        raise StudyError(f"non-canonical JSON artifact: {path}")
    return value


def _inventory(root: Path) -> tuple[dict[str, Any], ...]:
    if not root.is_dir() or root.is_symlink():
        raise StudyError(f"source/output root missing: {root}")
    result = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise StudyError(f"symlink is not allowed: {path}")
        result.append(
            {
                "path": path.relative_to(root).as_posix(),
                "byte_length": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return tuple(result)


def _inventory_sha256(inventory: Sequence[Mapping[str, Any]]) -> str:
    return _sha256_bytes(_canonical_bytes(list(inventory)))


def _write_atomic(path: Path, data: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"refusing existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
    )
    temporary = Path(handle.name)
    try:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        if path.exists():
            raise FileExistsError(f"refusing existing output: {path}")
        os.replace(temporary, path)
    except Exception:
        handle.close()
        temporary.unlink(missing_ok=True)
        raise


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _write_atomic(path, _canonical_bytes(value))


def _csv_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        raise StudyError("empty CSV payload")
    fields = tuple(rows[0])
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows({field: row[field] for field in fields} for row in rows)
    return buffer.getvalue().encode("utf-8")


def _finite(value: object, *, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise StudyError(f"{field} is not numeric") from exc
    if not math.isfinite(result):
        raise StudyError(f"{field} is not finite")
    return result


def _bps(delta: float, base: float, *, field: str) -> float:
    denominator = _finite(base, field=f"{field}.base")
    if denominator == 0:
        raise StudyError(f"{field} base is zero")
    return _finite(delta / abs(denominator) * 10_000, field=field)


def _median(values: Sequence[float | int]) -> float | None:
    return float(statistics.median(values)) if values else None


def _percentile95(values: Sequence[float | int]) -> float | int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _stats(values: Sequence[float | int]) -> dict[str, Any]:
    return {
        "minimum": min(values) if values else None,
        "median": _median(values),
        "p95": _percentile95(values),
        "maximum": max(values) if values else None,
    }


def _contract_payload() -> dict[str, Any]:
    return json.loads(
        r'''{"base_commit":"fad0ffc0f51953cd83fc6cb08af63751f36140f5","budgets_per_role":[4,6,8],"checkpoint_policy":{"cadence_hours":24,"candidate_availability_rule":"candidate_available_at <= checkpoint","evaluation_horizons_hours":[24,48,96],"evaluation_start_rule":"first_bar_strictly_after_checkpoint","holdout_lock_rule":"persist_and_hash_validation_lock_before_holdout_membership","last_checkpoint_rule":"checkpoint_plus_96h_must_be_within_source","warmup_hours":336},"contenders":{"contact_span_prominence_v1":["negative_historical_exact_contact_count","negative_anchor_span_seconds","negative_minimum_anchor_prominence_bps","negative_minimum_body_clearance_bps","historical_last_contact_age_bars","current_absolute_distance_bps","candidate_structure_id","candidate_id"],"multiswing_balanced_v1":["negative_same_role_extrema_skip_count","negative_historical_exact_contact_count","negative_minimum_anchor_prominence_bps","negative_anchor_span_seconds","negative_minimum_body_clearance_bps","current_absolute_distance_bps","candidate_structure_id","candidate_id"],"prominence_span_clearance_v1":["negative_minimum_anchor_prominence_bps","negative_anchor_span_seconds","negative_minimum_body_clearance_bps","negative_historical_exact_contact_count","current_absolute_distance_bps","candidate_structure_id","candidate_id"],"span_prominence_clearance_v1":["negative_anchor_span_seconds","negative_minimum_anchor_prominence_bps","negative_minimum_body_clearance_bps","negative_historical_exact_contact_count","current_absolute_distance_bps","candidate_structure_id","candidate_id"]},"controls":{"hash_order_matched_budget_v1":["candidate_structure_id","candidate_id"],"latest_valid_predecessor_v1":"dense_diagnostic_only","nearest_projection_matched_budget_v1":["current_absolute_distance_bps","negative_anchor_span_seconds","candidate_structure_id","candidate_id"]},"decision_statuses":["STRUCTURAL_SELECTION_PROMOTION_CANDIDATE","NO_STRUCTURAL_SELECTION_FINALIST","STRUCTURAL_SELECTION_HOLDOUT_REJECTED","STRUCTURAL_SELECTION_TEMPORAL_REJECTED"],"eligibility":{"current_validity_window":"availability_position_plus_one_through_checkpoint_inclusive","equality_rule":"not_a_violation","feature_visibility_rule":"bars_at_or_before_checkpoint_only","historical_contact_rule":"low <= line_price <= high","minimum_anchor_span_hours":96,"resistance_body_violation_rule":"line_price < max(open, close)","support_body_violation_rule":"line_price > min(open, close)"},"holdout_gates":{"both_datasets_structural_gates":true,"median_adjacent_jaccard_min":0.35,"pooled_96h_contact_and_survival_delta_vs_hash_min":-0.02,"pooled_96h_survival_delta_vs_hash_min":0.0,"worst_dataset_96h_survival_delta_vs_hash_min":-0.05},"redundancy":{"application":"greedy_in_canonical_rank_order","projection_distance_bps":25,"rule":"shared_anchor_or_projection_and_slope_both_within_threshold","scope":"same_role_only","shared_anchor_suppression":true,"slope_distance_bps_per_day":10},"schema_version":"trendline_v2_phase_11s1_structural_selection_study_v1_contract","sources":{"phase10c2":{"decision_id":"ac26d26534e65472bc18c072eee1121ce5c7420b8c541264139bf1614b95c6b6","manifest_id":"4daff316405662de15a328bafd503740d38c7343cfe4616bb8096976d0466ef5","output_inventory_sha256":"64e9477e48a3d546dc39b5ac8d0fa6328d4dddd10b1c055ae3616bd1de2bf35c","replay_contract_id":"166b156a471f06dcc2d4fbf09196df95c4648e4b60cac52d1d315f7e7794af96","source_inventory_sha256":"872bffa5aa232bfbeac2788c4575a8e73b344476c75cfedb67b8014bc82b550f","temporal_checkpoints":[1,2,3,4,5]},"phase9c2":{"decision_id":"4b734cbf99e1453bccdedb95f397f4b34e020f29e3d18808a131456647f78f7c","holdout_datasets":["suiusdt_1h","suiusdt_4h"],"manifest_id":"beab5b9acb2bfc3c25ba9cb5cb31c33c1a31e6069c1d7906f3ed5e1c2d798c81","output_inventory_sha256":"ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532","source_inventory_sha256":"631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be","validation_datasets":["btcusdt_1h","btcusdt_4h","ethusdt_1h","ethusdt_4h"]}},"temporal_audit_gates":{"checkpoint_count":5,"current_validity_rate":1.0,"final_total_selected_max":16,"median_adjacent_jaccard_min":0.25,"median_anchor_span_hours_min_each_checkpoint":168,"redundancy_violation_count":0,"selected_per_role_max":8,"selected_per_role_min":2},"validation_gates":{"checkpoint_role_coverage_ratio_min":0.9,"current_validity_rate":1.0,"median_adjacent_jaccard_min":0.4,"median_anchor_span_hours_min":168,"pooled_48h_survival_delta_vs_hash_min":0.0,"pooled_96h_contact_and_survival_delta_vs_hash_min":-0.02,"pooled_96h_survival_delta_vs_hash_min":0.0,"redundancy_violation_count":0,"selected_per_role_max":8,"selected_per_role_min":2,"worst_dataset_96h_survival_delta_vs_hash_min":-0.05},"validation_ranking":["worst_dataset_96h_survival_delta_vs_hash_desc","worst_dataset_96h_contact_and_survival_delta_vs_hash_desc","median_adjacent_jaccard_desc","median_anchor_span_hours_desc","budget_per_role_asc","contender_id_asc"]}'''
    )


def replay_contract_id(payload: Mapping[str, Any]) -> str:
    return deterministic_hash(CONTRACT_NAMESPACE, payload)


def _validated_contract() -> tuple[dict[str, Any], str]:
    payload = _contract_payload()
    identity = replay_contract_id(payload)
    if identity != CONTRACT_ID:
        raise StudyError("structural-selection contract identity drift")
    return payload, identity


def _checkpoint_schedule(data: Any) -> tuple[tuple[int, datetime, int], ...]:
    if data.row_count <= 0:
        raise StudyError("empty source input")
    interval = INTERVAL_SECONDS[data.timeframe]
    first = _datetime_from_ns(data.timestamps[0])
    confirmed = data.confirmed_through.astimezone(UTC)
    first_checkpoint = first + timedelta(hours=336)
    last_checkpoint = confirmed - timedelta(hours=96)
    result: list[tuple[int, datetime, int]] = []
    checkpoint = first_checkpoint
    index = 1
    while checkpoint <= last_checkpoint:
        cutoff = int(checkpoint.timestamp() * NANOSECONDS)
        positions = [
            position
            for position, timestamp in enumerate(data.timestamps)
            if timestamp < cutoff
        ]
        if not positions:
            raise StudyError("checkpoint has no causal prefix")
        if data.timestamps[positions[-1]] != cutoff - interval * NANOSECONDS:
            raise StudyError("checkpoint is not aligned to a completed bar")
        result.append((index, checkpoint, positions[-1]))
        index += 1
        checkpoint += timedelta(hours=24)
    if not result:
        raise StudyError("source cannot form a warmup checkpoint")
    return tuple(result)


def _value(data: Any, name: str, position: int) -> float:
    return _finite(getattr(data, name)[position], field=f"{name}[{position}]")


def _current_features(
    candidate: Any,
    evidence: Any,
    data: Any,
    *,
    checkpoint: datetime,
    prefix_last_position: int,
) -> ResearchCandidate | None:
    source_positions = tuple(evidence.anchor_source_positions)
    confirmation_positions = tuple(evidence.confirmation_positions)
    if len(source_positions) != 2 or len(confirmation_positions) != 2:
        raise StudyError("provider evidence must have two ordered positions")
    if any(
        position < 0 or position >= data.row_count
        for position in (*source_positions, *confirmation_positions)
    ):
        raise StudyError("provider evidence position outside source")
    if source_positions[1] <= source_positions[0] or confirmation_positions[1] <= confirmation_positions[0]:
        raise StudyError("provider evidence positions are not ordered")
    availability_position = max(confirmation_positions) + 1
    available_at = _datetime_from_ns(
        data.timestamps[max(confirmation_positions)]
    ) + timedelta(seconds=INTERVAL_SECONDS[data.timeframe])
    if available_at > checkpoint or max(source_positions + confirmation_positions) > prefix_last_position:
        return None
    try:
        birth = phase9c2._birth_features(
            candidate,
            evidence,
            data,
            phase9c2._extrema_by_role(data),
            availability_position=availability_position,
        )
    except (StudyError, phase9c2.StudyArtifactError, ContractValidationError) as exc:
        raise StudyError("causal candidate feature derivation failed") from exc
    start = availability_position + 1
    violations = 0
    contacts = 0
    last_contact: int | None = None
    for position in range(start, prefix_last_position + 1):
        line_price = _finite(
            candidate.geometry.value_at(_datetime_from_ns(data.timestamps[position])),
            field="current projected line",
        )
        floor = min(_value(data, "open", position), _value(data, "close", position))
        ceiling = max(_value(data, "open", position), _value(data, "close", position))
        violation = (
            line_price > floor
            if candidate.role.value == "support"
            else line_price < ceiling
        )
        if violation:
            violations += 1
        if _value(data, "low", position) <= line_price <= _value(data, "high", position):
            contacts += 1
            last_contact = position
    checkpoint_close = _value(data, "close", prefix_last_position)
    if checkpoint_close <= 0:
        raise StudyError("checkpoint close must be positive")
    current_line = _finite(
        candidate.geometry.value_at(_datetime_from_ns(data.timestamps[prefix_last_position])),
        field="checkpoint projected line",
    )
    fields = {
        "candidate_id": candidate.candidate_id,
        "candidate_structure_id": phase9c2._structure_id(candidate),
        "role": candidate.role.value,
        "first_anchor_id": candidate.anchors[0].anchor_id,
        "second_anchor_id": candidate.anchors[1].anchor_id,
        "first_anchor_time": _iso(candidate.anchors[0].pivot_time),
        "second_anchor_time": _iso(candidate.anchors[1].pivot_time),
        "anchor_source_positions": list(source_positions),
        "confirmation_positions": list(confirmation_positions),
        "availability_position": availability_position,
        "candidate_available_at": _iso(available_at),
        "anchor_span_bars": source_positions[1] - source_positions[0],
        "anchor_span_seconds": birth["anchor_span_seconds"],
        "anchor_span_hours": birth["anchor_span_seconds"] / 3_600,
        "same_role_extrema_skip_count": birth["same_role_extrema_skip_count"],
        "minimum_anchor_prominence_bps": birth["minimum_anchor_prominence_bps"],
        "minimum_body_clearance_bps": birth["minimum_body_clearance_bps"],
        "historical_exact_contact_count": contacts,
        "historical_last_contact_age_bars": (
            prefix_last_position - last_contact
            if last_contact is not None
            else prefix_last_position + 1
        ),
        "current_projected_line_price": current_line,
        "current_absolute_distance_bps": _bps(
            abs(checkpoint_close - current_line),
            checkpoint_close,
            field="current distance",
        ),
        "current_body_violation_count": violations,
        "current_exact_side_valid": violations == 0,
        "structurally_eligible": (
            birth["anchor_span_seconds"] >= 96 * 3_600 and violations == 0
        ),
        "slope_bps_per_day": birth["slope_bps_per_day"],
        "absolute_slope_bps_per_day": birth["absolute_slope_bps_per_day"],
    }
    return ResearchCandidate(candidate=candidate, evidence=evidence, fields=fields)


def _records_for_checkpoint(
    result: Any,
    data: Any,
    *,
    checkpoint: datetime,
    prefix_last_position: int,
) -> tuple[ResearchCandidate, ...]:
    if len(result.candidates) != len(result.evidence):
        raise StudyError("provider candidate/evidence collections are not one-to-one")
    records: list[ResearchCandidate] = []
    seen: set[str] = set()
    for candidate, evidence in zip(result.candidates, result.evidence):
        if evidence.candidate_id != candidate.candidate_id or candidate.candidate_id in seen:
            raise StudyError("candidate/evidence identity mismatch")
        seen.add(candidate.candidate_id)
        record = _current_features(
            candidate,
            evidence,
            data,
            checkpoint=checkpoint,
            prefix_last_position=prefix_last_position,
        )
        if record is not None:
            records.append(record)
    return tuple(sorted(records, key=lambda item: _record_sort_key(item.fields)))


def _record_sort_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        record["role"],
        record["second_anchor_time"],
        record["first_anchor_time"],
        record["candidate_structure_id"],
        record["candidate_id"],
    )


def _rank_key(record: Mapping[str, Any], selector: str) -> tuple[Any, ...]:
    if selector == "hash_order_matched_budget_v1":
        return (record["candidate_structure_id"], record["candidate_id"])
    if selector == "nearest_projection_matched_budget_v1":
        return (
            record["current_absolute_distance_bps"],
            -record["anchor_span_seconds"],
            record["candidate_structure_id"],
            record["candidate_id"],
        )
    if selector == "span_prominence_clearance_v1":
        return (
            -record["anchor_span_seconds"],
            -record["minimum_anchor_prominence_bps"],
            -record["minimum_body_clearance_bps"],
            -record["historical_exact_contact_count"],
            record["current_absolute_distance_bps"],
            record["candidate_structure_id"],
            record["candidate_id"],
        )
    if selector == "prominence_span_clearance_v1":
        return (
            -record["minimum_anchor_prominence_bps"],
            -record["anchor_span_seconds"],
            -record["minimum_body_clearance_bps"],
            -record["historical_exact_contact_count"],
            record["current_absolute_distance_bps"],
            record["candidate_structure_id"],
            record["candidate_id"],
        )
    if selector == "contact_span_prominence_v1":
        return (
            -record["historical_exact_contact_count"],
            -record["anchor_span_seconds"],
            -record["minimum_anchor_prominence_bps"],
            -record["minimum_body_clearance_bps"],
            record["historical_last_contact_age_bars"],
            record["current_absolute_distance_bps"],
            record["candidate_structure_id"],
            record["candidate_id"],
        )
    if selector == "multiswing_balanced_v1":
        return (
            -record["same_role_extrema_skip_count"],
            -record["historical_exact_contact_count"],
            -record["minimum_anchor_prominence_bps"],
            -record["anchor_span_seconds"],
            -record["minimum_body_clearance_bps"],
            record["current_absolute_distance_bps"],
            record["candidate_structure_id"],
            record["candidate_id"],
        )
    raise StudyError(f"unknown selector: {selector}")


def _projection_distance_bps(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    denominator = (abs(left["current_projected_line_price"]) + abs(right["current_projected_line_price"])) / 2
    if denominator == 0:
        raise StudyError("projection price cannot be zero")
    return abs(
        left["current_projected_line_price"] - right["current_projected_line_price"]
    ) / denominator * 10_000


def _is_redundant(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    shared = {
        left["first_anchor_id"],
        left["second_anchor_id"],
    } & {right["first_anchor_id"], right["second_anchor_id"]}
    near_geometry = (
        _projection_distance_bps(left, right) <= 25
        and abs(left["slope_bps_per_day"] - right["slope_bps_per_day"]) <= 10
    )
    return bool(shared) or near_geometry


def _latest_predecessor(records: Sequence[ResearchCandidate]) -> tuple[ResearchCandidate, ...]:
    groups: dict[tuple[str, str], list[ResearchCandidate]] = {}
    for record in records:
        groups.setdefault(
            (record.fields["role"], record.fields["second_anchor_id"]), []
        ).append(record)
    selected: list[ResearchCandidate] = []
    for group in groups.values():
        latest = max(item.fields["first_anchor_time"] for item in group)
        selected.append(
            min(
                (item for item in group if item.fields["first_anchor_time"] == latest),
                key=lambda item: (
                    item.fields["candidate_structure_id"],
                    item.fields["candidate_id"],
                ),
            )
        )
    return tuple(sorted(selected, key=lambda item: _record_sort_key(item.fields)))


def select_records(
    records: Sequence[ResearchCandidate],
    *,
    selector: str,
    budget_per_role: int | None,
) -> tuple[ResearchCandidate, ...]:
    if selector == "latest_valid_predecessor_v1":
        return _latest_predecessor(records)
    if selector not in CONTENDERS + CONTROLS:
        raise StudyError(f"unknown selector: {selector}")
    if budget_per_role not in BUDGETS:
        raise StudyError("budget must be one of 4, 6 or 8")
    retained: list[ResearchCandidate] = []
    for role in ROLES:
        ranked = sorted(
            (
                item
                for item in records
                if item.fields["role"] == role
                and item.fields["structurally_eligible"]
            ),
            key=lambda item: _rank_key(item.fields, selector),
        )
        for record in ranked:
            if any(_is_redundant(record.fields, old.fields) for old in retained if old.fields["role"] == role):
                continue
            retained.append(record)
            if sum(item.fields["role"] == role for item in retained) >= budget_per_role:
                break
    return tuple(sorted(retained, key=lambda item: _record_sort_key(item.fields)))


def _body_violation(role: str, line_price: float, open_price: float, close_price: float) -> bool:
    floor = min(open_price, close_price)
    ceiling = max(open_price, close_price)
    return line_price > floor if role == "support" else line_price < ceiling


def _future_evaluation(
    record: ResearchCandidate,
    data: Any,
    *,
    checkpoint: datetime,
    horizon: str,
) -> dict[str, Any]:
    interval = INTERVAL_SECONDS[data.timeframe]
    horizon_bars = HORIZON_HOURS[horizon] * 3_600 // interval
    cutoff_ns = int(checkpoint.timestamp() * NANOSECONDS)
    end_ns = int((checkpoint + timedelta(hours=HORIZON_HOURS[horizon])).timestamp() * NANOSECONDS)
    positions = [
        position
        for position, timestamp in enumerate(data.timestamps)
        if cutoff_ns < timestamp <= end_ns
    ]
    if len(positions) != horizon_bars:
        return {
            "evaluation_available": False,
            "horizon": horizon,
            "horizon_bars": horizon_bars,
            "future_contact_count": None,
            "future_body_violation_count": None,
            "has_exact_contact": None,
            "survives_exact_side": None,
            "contact_and_survives_exact_side": None,
            "first_contact_offset_bars": None,
            "first_body_violation_offset_bars": None,
        }
    contacts = violations = 0
    first_contact: int | None = None
    first_violation: int | None = None
    for offset, position in enumerate(positions):
        line_price = _finite(
            record.candidate.geometry.value_at(_datetime_from_ns(data.timestamps[position])),
            field="future projected line",
        )
        contact = _value(data, "low", position) <= line_price <= _value(data, "high", position)
        violation = _body_violation(
            record.fields["role"],
            line_price,
            _value(data, "open", position),
            _value(data, "close", position),
        )
        if contact:
            contacts += 1
            first_contact = offset if first_contact is None else first_contact
        if violation:
            violations += 1
            first_violation = offset if first_violation is None else first_violation
    return {
        "evaluation_available": True,
        "horizon": horizon,
        "horizon_bars": horizon_bars,
        "future_contact_count": contacts,
        "future_body_violation_count": violations,
        "has_exact_contact": contacts > 0,
        "survives_exact_side": violations == 0,
        "contact_and_survives_exact_side": contacts > 0 and violations == 0,
        "first_contact_offset_bars": first_contact,
        "first_body_violation_offset_bars": first_violation,
    }


def _outcome_summary(evaluations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    available = [item for item in evaluations if item["evaluation_available"]]
    if not available:
        return {
            "evaluation_available_count": 0,
            "contact_rate": None,
            "survival_rate": None,
            "contact_and_survival_rate": None,
            "future_contact_count_median": None,
            "future_body_violation_count_median": None,
        }
    return {
        "evaluation_available_count": len(available),
        "contact_count": sum(item["has_exact_contact"] for item in available),
        "survival_count": sum(item["survives_exact_side"] for item in available),
        "contact_and_survival_count": sum(
            item["contact_and_survives_exact_side"] for item in available
        ),
        "contact_rate": statistics.mean(item["has_exact_contact"] for item in available),
        "survival_rate": statistics.mean(item["survives_exact_side"] for item in available),
        "contact_and_survival_rate": statistics.mean(
            item["contact_and_survives_exact_side"] for item in available
        ),
        "future_contact_count_median": statistics.median(
            item["future_contact_count"] for item in available
        ),
        "future_body_violation_count_median": statistics.median(
            item["future_body_violation_count"] for item in available
        ),
    }


def _delta(left: object, right: object) -> float | None:
    if left is None or right is None:
        return None
    return float(left) - float(right)


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def _checkpoint_selection_payload(
    checkpoint: ScopeCheckpoint,
    selector: str,
    budget: int | None,
    selected: Sequence[ResearchCandidate],
    *,
    source_candidate_count: int,
    eligible_candidate_count: int,
) -> dict[str, Any]:
    return {
        "selector_id": selector,
        "budget_per_role": budget,
        "source_candidate_count": source_candidate_count,
        "eligible_candidate_count": eligible_candidate_count,
        "selected_candidate_count": len(selected),
        "support_count": sum(item.fields["role"] == "support" for item in selected),
        "resistance_count": sum(item.fields["role"] == "resistance" for item in selected),
        "selected_candidates": [
            {
                "candidate_id": item.fields["candidate_id"],
                "candidate_structure_id": item.fields["candidate_structure_id"],
                "role": item.fields["role"],
                "first_anchor_id": item.fields["first_anchor_id"],
                "second_anchor_id": item.fields["second_anchor_id"],
                "first_anchor_time": item.fields["first_anchor_time"],
                "second_anchor_time": item.fields["second_anchor_time"],
                "anchor_span_seconds": item.fields["anchor_span_seconds"],
                "candidate_available_at": item.fields["candidate_available_at"],
            }
            for item in selected
        ],
        "checkpoint_index": checkpoint.checkpoint_index,
        "checkpoint": _iso(checkpoint.checkpoint),
    }


def _variant_analysis(
    dataset: ScopeDataset,
    checkpoint_rows: Sequence[tuple[ScopeCheckpoint, Sequence[ResearchCandidate], Mapping[str, Any]]],
    *,
    selector: str,
    budget: int | None,
    control_rows: Sequence[tuple[ScopeCheckpoint, Sequence[ResearchCandidate], Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    selected_by_checkpoint: list[tuple[ScopeCheckpoint, tuple[ResearchCandidate, ...]]] = []
    checkpoint_metrics: list[dict[str, Any]] = []
    all_evaluations = {horizon: [] for horizon in HORIZONS}
    role_evaluations = {role: {horizon: [] for horizon in HORIZONS} for role in ROLES}
    for checkpoint, selected, membership in checkpoint_rows:
        selected_tuple = tuple(selected)
        selected_by_checkpoint.append((checkpoint, selected_tuple))
        evaluations_by_horizon = {
            horizon: [
                _future_evaluation(item, dataset.data, checkpoint=checkpoint.checkpoint, horizon=horizon)
                for item in selected_tuple
            ]
            for horizon in HORIZONS
        }
        for horizon in HORIZONS:
            all_evaluations[horizon].extend(evaluations_by_horizon[horizon])
            for role in ROLES:
                role_evaluations[role][horizon].extend(
                    evaluation
                    for item, evaluation in zip(selected_tuple, evaluations_by_horizon[horizon])
                    if item.fields["role"] == role
                )
        checkpoint_metrics.append(
            {
                "checkpoint_index": checkpoint.checkpoint_index,
                "checkpoint": _iso(checkpoint.checkpoint),
                "selected_candidate_count": len(selected_tuple),
                "support_count": sum(item.fields["role"] == "support" for item in selected_tuple),
                "resistance_count": sum(item.fields["role"] == "resistance" for item in selected_tuple),
                "median_anchor_span_hours": _median(
                    [item.fields["anchor_span_hours"] for item in selected_tuple]
                ),
                "current_validity_rate": (
                    statistics.mean(item.fields["current_exact_side_valid"] for item in selected_tuple)
                    if selected_tuple
                    else None
                ),
                "redundancy_violation_count": _redundancy_violation_count(selected_tuple),
                "outcomes": {
                    horizon: _outcome_summary(evaluations_by_horizon[horizon])
                    for horizon in HORIZONS
                },
            }
        )
    stability_rows = []
    for (_, left), (right_checkpoint, right) in zip(
        selected_by_checkpoint,
        selected_by_checkpoint[1:],
    ):
        for role in ROLES:
            left_ids = {
                item.fields["candidate_structure_id"] for item in left if item.fields["role"] == role
            }
            right_ids = {
                item.fields["candidate_structure_id"] for item in right if item.fields["role"] == role
            }
            stability_rows.append(
                {
                    "role": role,
                    "checkpoint_index": right_checkpoint.checkpoint_index,
                    "support_identity_jaccard" if role == "support" else "resistance_identity_jaccard": _jaccard(left_ids, right_ids),
                    "birth_count": len(right_ids - left_ids),
                    "retained_count": len(left_ids & right_ids),
                    "removed_count": len(left_ids - right_ids),
                }
            )
        left_ids = {item.fields["candidate_structure_id"] for item in left}
        right_ids = {item.fields["candidate_structure_id"] for item in right}
        stability_rows.append(
            {
                "role": "combined",
                "checkpoint_index": right_checkpoint.checkpoint_index,
                "combined_identity_jaccard": _jaccard(left_ids, right_ids),
                "birth_count": len(right_ids - left_ids),
                "retained_count": len(left_ids & right_ids),
                "removed_count": len(left_ids - right_ids),
            }
        )
    stability_by_role = {
        role: [
            row.get("support_identity_jaccard" if role == "support" else "resistance_identity_jaccard")
            for row in stability_rows
            if row["role"] == role
        ]
        for role in ROLES
    }
    combined_jaccards = [
        row["combined_identity_jaccard"] for row in stability_rows if row["role"] == "combined"
    ]
    outcomes = {
        horizon: {
            "candidate_weighted": _outcome_summary(all_evaluations[horizon]),
            "checkpoint_weighted": _checkpoint_weighted(
                [row["outcomes"][horizon] for row in checkpoint_metrics]
            ),
            "role_separated": {
                role: _outcome_summary(role_evaluations[role][horizon])
                for role in ROLES
            },
        }
        for horizon in HORIZONS
    }
    structural = _structural_metrics(checkpoint_metrics, selected_by_checkpoint, budget)
    result = {
        "selector_id": selector,
        "budget_per_role": budget,
        "selector_result_id": None,
        "structural": structural,
        "outcomes": outcomes,
        "stability": {
            "rows": stability_rows,
            "support_identity_jaccard_median": _median(stability_by_role["support"]),
            "resistance_identity_jaccard_median": _median(stability_by_role["resistance"]),
            "combined_identity_jaccard_median": _median(combined_jaccards),
        },
        "checkpoint_metrics": checkpoint_metrics,
    }
    if control_rows is not None:
        result["comparison_to_hash_control"] = {
            horizon: {
                "survival_delta": _delta(
                    outcomes[horizon]["candidate_weighted"]["survival_rate"],
                    _aggregate_rows_outcome(control_rows, dataset, horizon, "survival_rate"),
                ),
                "contact_and_survival_delta": _delta(
                    outcomes[horizon]["candidate_weighted"]["contact_and_survival_rate"],
                    _aggregate_rows_outcome(control_rows, dataset, horizon, "contact_and_survival_rate"),
                ),
            }
            for horizon in HORIZONS
        }
    else:
        result["comparison_to_hash_control"] = {
            horizon: {"survival_delta": None, "contact_and_survival_delta": None}
            for horizon in HORIZONS
        }
    result["selector_result_id"] = deterministic_hash(
        RESULT_NAMESPACE,
        {key: value for key, value in result.items() if key != "selector_result_id"},
    )
    return result


def _checkpoint_weighted(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    keys = ("contact_rate", "survival_rate", "contact_and_survival_rate")
    return {
        "checkpoint_count": len(rows),
        **{
            key: statistics.mean(
                row[key] for row in rows if row.get(key) is not None
            )
            if any(row.get(key) is not None for row in rows)
            else None
            for key in keys
        },
    }


def _aggregate_rows_outcome(
    rows: Sequence[tuple[ScopeCheckpoint, Sequence[ResearchCandidate], Mapping[str, Any]]],
    dataset: ScopeDataset,
    horizon: str,
    field: str,
) -> float | None:
    evaluations = []
    for checkpoint, selected, _ in rows:
        evaluations.extend(
            _future_evaluation(item, dataset.data, checkpoint=checkpoint.checkpoint, horizon=horizon)
            for item in selected
        )
    return _outcome_summary(evaluations)[field]


def _redundancy_violation_count(selected: Sequence[ResearchCandidate]) -> int:
    count = 0
    for index, left in enumerate(selected):
        for right in selected[index + 1 :]:
            if left.fields["role"] == right.fields["role"] and _is_redundant(left.fields, right.fields):
                count += 1
    return count


def _structural_metrics(
    checkpoint_metrics: Sequence[Mapping[str, Any]],
    selected_by_checkpoint: Sequence[tuple[ScopeCheckpoint, Sequence[ResearchCandidate]]],
    budget: int | None,
) -> dict[str, Any]:
    role_coverage = {}
    role_valid_counts = {}
    for role in ROLES:
        counts = [
            sum(item.fields["role"] == role for item in selected)
            for _, selected in selected_by_checkpoint
        ]
        role_coverage[role] = (
            sum(count >= 2 for count in counts) / len(counts) if counts else 0.0
        )
        role_valid_counts[role] = all(2 <= count <= 8 for count in counts)
    spans = [
        item.fields["anchor_span_hours"]
        for _, selected in selected_by_checkpoint
        for item in selected
    ]
    validities = [
        item.fields["current_exact_side_valid"]
        for _, selected in selected_by_checkpoint
        for item in selected
    ]
    return {
        "budget_per_role": budget,
        "role_coverage_ratio": role_coverage,
        "role_counts_within_gate": role_valid_counts,
        "median_anchor_span_hours": _median(spans),
        "current_validity_rate": statistics.mean(validities) if validities else None,
        "redundancy_violation_count": sum(
            row["redundancy_violation_count"] for row in checkpoint_metrics
        ),
        "checkpoint_count": len(checkpoint_metrics),
        "selected_count": sum(
            row["selected_candidate_count"] for row in checkpoint_metrics
        ),
    }


def _selector_variants(*, include_latest: bool = True) -> tuple[tuple[str, int | None], ...]:
    values: list[tuple[str, int | None]] = []
    if include_latest:
        values.append(("latest_valid_predecessor_v1", None))
    for selector in CONTROLS + CONTENDERS:
        values.extend((selector, budget) for budget in BUDGETS)
    return tuple(values)


def _source_bindings() -> dict[str, Any]:
    phase9c2_before = _inventory(SOURCE_ROOT)
    if len(phase9c2_before) != 38 or _inventory_sha256(phase9c2_before) != PHASE9C2_OUTPUT_INVENTORY:
        raise StudyError("Phase 9C.2 source inventory drift")
    phase9c1_before = _inventory(phase9c2.SOURCE_ROOT)
    if _inventory_sha256(phase9c1_before) != PHASE9C1_SOURCE_INVENTORY:
        raise StudyError("Phase 9C.1 source inventory drift")
    _verify_frozen_bundle_identity(
        SOURCE_ROOT,
        expected_manifest_id=PHASE9C2_MANIFEST_ID,
        expected_inventory=PHASE9C2_OUTPUT_INVENTORY,
        expected_member_count=37,
        expected_decision_id=PHASE9C2_DECISION_ID,
        expected_contract_key=None,
    )
    phase10c2_before = _inventory(TEMPORAL_ROOT)
    if len(phase10c2_before) != 12 or _inventory_sha256(phase10c2_before) != PHASE10C2_OUTPUT_INVENTORY:
        raise StudyError("Phase 10C.2 source inventory drift")
    phase10c1_before = _inventory(phase10c2.SOURCE_ROOT)
    if _inventory_sha256(phase10c1_before) != PHASE10C1_SOURCE_INVENTORY:
        raise StudyError("Phase 10C.1 source inventory drift")
    _verify_frozen_bundle_identity(
        TEMPORAL_ROOT,
        expected_manifest_id=PHASE10C2_MANIFEST_ID,
        expected_inventory=PHASE10C2_OUTPUT_INVENTORY,
        expected_member_count=11,
        expected_decision_id=PHASE10C2_DECISION_ID,
        expected_contract_key="eviction_replay_contract_id",
    )
    return {
        "phase9c2": {
            "decision_id": PHASE9C2_DECISION_ID,
            "manifest_id": PHASE9C2_MANIFEST_ID,
            "output_inventory_sha256": PHASE9C2_OUTPUT_INVENTORY,
            "source_inventory_sha256": PHASE9C1_SOURCE_INVENTORY,
            "pre_run_inventory": list(phase9c2_before),
            "source_pre_run_inventory": list(phase9c1_before),
            "post_run_inventory": list(phase9c2_before),
            "source_post_run_inventory": list(phase9c1_before),
        },
        "phase10c2": {
            "replay_contract_id": PHASE10C2_REPLAY_CONTRACT_ID,
            "decision_id": PHASE10C2_DECISION_ID,
            "manifest_id": PHASE10C2_MANIFEST_ID,
            "output_inventory_sha256": PHASE10C2_OUTPUT_INVENTORY,
            "source_inventory_sha256": PHASE10C1_SOURCE_INVENTORY,
            "pre_run_inventory": list(phase10c2_before),
            "source_pre_run_inventory": list(phase10c1_before),
            "post_run_inventory": list(phase10c2_before),
            "source_post_run_inventory": list(phase10c1_before),
        },
    }


def _verify_frozen_bundle_identity(
    root: Path,
    *,
    expected_manifest_id: str,
    expected_inventory: str,
    expected_member_count: int,
    expected_decision_id: str,
    expected_contract_key: str | None,
) -> None:
    inventory = _inventory(root)
    members = tuple(item for item in inventory if item["path"] != "manifest.json")
    if _inventory_sha256(inventory) != expected_inventory or len(members) != expected_member_count:
        raise StudyError(f"frozen bundle inventory drift: {root}")
    manifest = _load_json(root / "manifest.json")
    manifest_id = manifest.pop("manifest_id", None)
    if manifest_id != expected_manifest_id:
        raise StudyError(f"frozen bundle manifest ID drift: {root}")
    if manifest.get("member_count") != expected_member_count or manifest.get("members") != list(members):
        raise StudyError(f"frozen bundle manifest membership drift: {root}")
    if deterministic_hash(
        phase10c2.MANIFEST_NAMESPACE if expected_contract_key else phase9c2.MANIFEST_NAMESPACE,
        manifest,
    ) != expected_manifest_id:
        raise StudyError(f"frozen bundle manifest hash drift: {root}")
    decision = _load_json(root / "decision.json")
    if decision.get("decision_id") != expected_decision_id:
        raise StudyError(f"frozen bundle decision ID drift: {root}")
    if expected_contract_key is not None:
        contract = _load_json(root / "study_contract.json")
        if contract.get("replay_contract", {}).get("contract_id") != PHASE10C2_REPLAY_CONTRACT_ID:
            raise StudyError("Phase 10C.2 replay contract drift")
        if manifest.get(expected_contract_key) != PHASE10C2_REPLAY_CONTRACT_ID:
            raise StudyError("Phase 10C.2 manifest contract binding drift")


def _assert_source_unchanged(bindings: Mapping[str, Any]) -> None:
    checks = (
        (SOURCE_ROOT, bindings["phase9c2"]["pre_run_inventory"], PHASE9C2_OUTPUT_INVENTORY),
        (phase9c2.SOURCE_ROOT, bindings["phase9c2"]["source_pre_run_inventory"], PHASE9C1_SOURCE_INVENTORY),
        (TEMPORAL_ROOT, bindings["phase10c2"]["pre_run_inventory"], PHASE10C2_OUTPUT_INVENTORY),
        (phase10c2.SOURCE_ROOT, bindings["phase10c2"]["source_pre_run_inventory"], PHASE10C1_SOURCE_INVENTORY),
    )
    for root, before, expected in checks:
        after = _inventory(root)
        if tuple(before) != after or _inventory_sha256(after) != expected:
            raise StudyError(f"protected source changed: {root}")


def _load_validation_scope(bindings: Mapping[str, Any]) -> tuple[ScopeDataset, ...]:
    del bindings
    context = phase9c2._load_cohort()
    config = phase9c2._foundation_config()
    provider_config = phase9c2._provider_config()
    by_id = {dataset.dataset_id: dataset for dataset in context.datasets}
    result: list[ScopeDataset] = []
    for dataset_id in VALIDATION_DATASETS:
        dataset = by_id[dataset_id]
        provider_result = phase9c2._load_persisted_provider_result(
            SOURCE_ROOT, dataset, config, provider_config
        )
        schedule = _checkpoint_schedule(dataset.input_data)
        checkpoints = tuple(
            ScopeCheckpoint(
                dataset_id=dataset_id,
                checkpoint_index=index,
                checkpoint=checkpoint,
                data=dataset.input_data,
                result=provider_result,
                prefix_last_position=prefix_last,
                source_provider_result_id=phase9c2._provider_result_id(provider_result),
            )
            for index, checkpoint, prefix_last in schedule
        )
        result.append(
            ScopeDataset(
                dataset_id=dataset_id,
                asset=dataset.asset,
                timeframe=dataset.timeframe,
                data=dataset.input_data,
                checkpoints=checkpoints,
                input_identity=dataset.input_data.input_identity,
            )
        )
    return tuple(result)


def _load_temporal_scope() -> ScopeDataset:
    _, full_input = phase10c2._verify_source()
    checkpoints: list[ScopeCheckpoint] = []
    for spec in phase10c2.CHECKPOINTS:
        path = TEMPORAL_ROOT / "datasets" / "btcusdt_4h" / (
            f"checkpoint_{spec.index:02d}_{spec.observed_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        payload = phase10c2._load_json(path)
        result = phase10c2._typed_provider_result(payload["provider_result"])
        prefix_last = result.request.input_data.row_count - 1
        if (
            result.request.input_data.input_identity != payload["prefix_input_identity"]
            or result.request.input_data.row_count != payload["prefix_row_count"]
            or result.request.asset != "BTCUSDT"
            or result.request.timeframe != "4h"
        ):
            raise StudyError("temporal checkpoint provider binding drift")
        checkpoints.append(
            ScopeCheckpoint(
                dataset_id="btcusdt_4h",
                checkpoint_index=spec.index,
                checkpoint=spec.observed_at,
                data=full_input,
                result=result,
                prefix_last_position=prefix_last,
                source_provider_result_id=phase10c2._provider_result_id(result),
            )
        )
    return ScopeDataset(
        dataset_id="btcusdt_4h",
        asset="BTCUSDT",
        timeframe="4h",
        data=full_input,
        checkpoints=tuple(checkpoints),
        input_identity=full_input.input_identity,
    )


def _analyze_dataset(
    dataset: ScopeDataset,
    *,
    variants: Sequence[tuple[str, int | None]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    rows_by_variant: dict[tuple[str, int | None], list[tuple[ScopeCheckpoint, Sequence[ResearchCandidate], Mapping[str, Any]]] ] = {
        variant: [] for variant in variants
    }
    membership_checkpoints: list[dict[str, Any]] = []
    for checkpoint in dataset.checkpoints:
        records = _records_for_checkpoint(
            checkpoint.result,
            checkpoint.data,
            checkpoint=checkpoint.checkpoint,
            prefix_last_position=checkpoint.prefix_last_position,
        )
        selector_payloads = []
        for selector, budget in variants:
            selected = select_records(
                records,
                selector=selector,
                budget_per_role=budget,
            )
            membership = _checkpoint_selection_payload(
                checkpoint,
                selector,
                budget,
                selected,
                source_candidate_count=len(checkpoint.result.candidates),
                eligible_candidate_count=sum(
                    item.fields["structurally_eligible"] for item in records
                ),
            )
            rows_by_variant[(selector, budget)].append((checkpoint, selected, membership))
            selector_payloads.append(membership)
        membership_checkpoints.append(
            {
                "checkpoint_index": checkpoint.checkpoint_index,
                "checkpoint": _iso(checkpoint.checkpoint),
                "source_provider_result_id": checkpoint.source_provider_result_id,
                "source_candidate_count": len(checkpoint.result.candidates),
                "eligible_candidate_count": sum(
                    item.fields["structurally_eligible"] for item in records
                ),
                "selectors": selector_payloads,
            }
        )
    results: list[dict[str, Any]] = []
    for selector, budget in variants:
        control_rows = rows_by_variant.get(("hash_order_matched_budget_v1", budget))
        analysis = _variant_analysis(
            dataset,
            rows_by_variant[(selector, budget)],
            selector=selector,
            budget=budget,
            control_rows=control_rows if selector not in ("hash_order_matched_budget_v1",) else None,
        )
        results.append(analysis)
    metrics = {
        "schema_version": f"{STUDY_SCHEMA}_selector_metrics",
        "dataset_id": dataset.dataset_id,
        "asset": dataset.asset,
        "timeframe": dataset.timeframe,
        "source_input_identity": dataset.input_identity,
        "checkpoints": len(dataset.checkpoints),
        "selectors": results,
    }
    metrics["dataset_result_id"] = deterministic_hash(
        RESULT_NAMESPACE,
        {key: value for key, value in metrics.items() if key != "dataset_result_id"},
    )
    membership = {
        "schema_version": f"{STUDY_SCHEMA}_checkpoint_membership",
        "dataset_id": dataset.dataset_id,
        "asset": dataset.asset,
        "timeframe": dataset.timeframe,
        "source_input_identity": dataset.input_identity,
        "checkpoint_count": len(dataset.checkpoints),
        "checkpoints": membership_checkpoints,
    }
    return membership, metrics


def _validation_gate(
    datasets: Mapping[str, Mapping[str, Any]],
    selector: str,
    budget: int,
) -> dict[str, Any]:
    reasons: list[str] = []
    selected = [
        next(
            item
            for item in datasets[dataset_id]["selectors"]
            if item["selector_id"] == selector and item["budget_per_role"] == budget
        )
        for dataset_id in VALIDATION_DATASETS
    ]
    for item in selected:
        structural = item["structural"]
        if any(value < 0.9 for value in structural["role_coverage_ratio"].values()):
            reasons.append(f"{item['selector_id']}:{structural['role_coverage_ratio']}")
        if not all(structural["role_counts_within_gate"].values()):
            reasons.append(f"{item['selector_id']}:role_counts")
        if (structural["median_anchor_span_hours"] or 0) < 168:
            reasons.append(f"{item['selector_id']}:median_span")
        if structural["current_validity_rate"] != 1.0:
            reasons.append(f"{item['selector_id']}:current_validity")
        if structural["redundancy_violation_count"] != 0:
            reasons.append(f"{item['selector_id']}:redundancy")
        if (item["stability"]["combined_identity_jaccard_median"] or 0) < 0.4:
            reasons.append(f"{item['selector_id']}:stability")
    comparison_96 = [
        item["comparison_to_hash_control"]["96h"]["survival_delta"]
        for item in selected
    ]
    contact_96 = [
        item["comparison_to_hash_control"]["96h"]["contact_and_survival_delta"]
        for item in selected
    ]
    pooled_48 = _pooled_delta(
        datasets,
        selector=selector,
        budget=budget,
        horizon="48h",
        field="survival_rate",
    )
    pooled_96 = _pooled_delta(
        datasets,
        selector=selector,
        budget=budget,
        horizon="96h",
        field="survival_rate",
    )
    pooled_contact_96 = _pooled_delta(
        datasets,
        selector=selector,
        budget=budget,
        horizon="96h",
        field="contact_and_survival_rate",
    )
    if pooled_48 is None or pooled_48 < 0:
        reasons.append("pooled_48h_survival_delta")
    if pooled_96 is None or pooled_96 < 0:
        reasons.append("pooled_96h_survival_delta")
    if min(value for value in comparison_96 if value is not None) < -0.05:
        reasons.append("worst_dataset_96h_survival_delta")
    if pooled_contact_96 is None or pooled_contact_96 < -0.02:
        reasons.append("pooled_96h_contact_and_survival_delta")
    return {
        "eligible": not reasons,
        "rejection_reasons": reasons,
        "dataset_ids": list(VALIDATION_DATASETS),
        "worst_dataset_96h_survival_delta_vs_hash": min(
            value for value in comparison_96 if value is not None
        ),
        "worst_dataset_96h_contact_and_survival_delta_vs_hash": min(
            value for value in contact_96 if value is not None
        ),
        "median_adjacent_jaccard": _median(
            [item["stability"]["combined_identity_jaccard_median"] for item in selected]
        ),
        "median_anchor_span_hours": _median(
            [item["structural"]["median_anchor_span_hours"] for item in selected if item["structural"]["median_anchor_span_hours"] is not None]
        ),
        "pooled_48h_survival_delta_vs_hash": pooled_48,
        "pooled_96h_survival_delta_vs_hash": pooled_96,
        "pooled_96h_contact_and_survival_delta_vs_hash": pooled_contact_96,
    }


def _pooled_delta(
    datasets: Mapping[str, Mapping[str, Any]],
    *,
    selector: str,
    budget: int,
    horizon: str,
    field: str,
) -> float | None:
    count_field = {
        "survival_rate": "survival_count",
        "contact_and_survival_rate": "contact_and_survival_count",
    }.get(field)
    if count_field is None:
        raise StudyError(f"unsupported pooled outcome field: {field}")

    def pooled_rate(selector_id: str) -> float | None:
        numerator = 0
        denominator = 0
        for metrics in datasets.values():
            item = next(
                candidate
                for candidate in metrics["selectors"]
                if candidate["selector_id"] == selector_id
                and candidate["budget_per_role"] == budget
            )
            outcome = item["outcomes"][horizon]["candidate_weighted"]
            numerator += int(outcome[count_field])
            denominator += int(outcome["evaluation_available_count"])
        return numerator / denominator if denominator else None

    left = pooled_rate(selector)
    right = pooled_rate("hash_order_matched_budget_v1")
    return _delta(left, right)


def _ranking_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    gate = item["gate"]
    return (
        -(gate["worst_dataset_96h_survival_delta_vs_hash"]),
        -(gate["worst_dataset_96h_contact_and_survival_delta_vs_hash"]),
        -(gate["median_adjacent_jaccard"] or -1),
        -(gate["median_anchor_span_hours"] or -1),
        item["budget_per_role"],
        item["selector_id"],
    )


def _validation_result(metrics_by_dataset: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    variants = [(selector, budget) for selector in CONTENDERS for budget in BUDGETS]
    results = []
    for selector, budget in variants:
        gate = _validation_gate(metrics_by_dataset, selector, budget)
        results.append(
            {
                "selector_id": selector,
                "budget_per_role": budget,
                "gate": gate,
                "ranking_key": list(_ranking_key({"selector_id": selector, "budget_per_role": budget, "gate": gate})),
            }
        )
    eligible = sorted((item for item in results if item["gate"]["eligible"]), key=_ranking_key)
    return {
        "status": "VALIDATION_FINALIST_FROZEN" if eligible else "NO_STRUCTURAL_SELECTION_FINALIST",
        "eligible_variants": eligible,
        "all_variants": results,
        "winner": eligible[0] if eligible else None,
    }


def _validation_lock(
    validation: Mapping[str, Any],
    *,
    bindings: Mapping[str, Any],
    metrics_by_dataset: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    winner = validation["winner"]
    payload = {
        "schema_version": f"{STUDY_SCHEMA}_validation_lock",
        "study_contract_id": CONTRACT_ID,
        "locked_finalist": (
            {
                "selector_id": winner["selector_id"],
                "budget_per_role": winner["budget_per_role"],
                "ranking_key": winner["ranking_key"],
            }
            if winner
            else None
        ),
        "status": validation["status"],
        "validation_dataset_result_ids": {
            dataset_id: metrics_by_dataset[dataset_id]["dataset_result_id"]
            for dataset_id in VALIDATION_DATASETS
        },
        "source_identities": {
            "phase9c2_decision_id": PHASE9C2_DECISION_ID,
            "phase9c2_manifest_id": PHASE9C2_MANIFEST_ID,
            "phase9c2_output_inventory_sha256": PHASE9C2_OUTPUT_INVENTORY,
            "phase9c1_source_inventory_sha256": PHASE9C1_SOURCE_INVENTORY,
            "phase10c2_decision_id": PHASE10C2_DECISION_ID,
            "phase10c2_manifest_id": PHASE10C2_MANIFEST_ID,
            "phase10c2_output_inventory_sha256": PHASE10C2_OUTPUT_INVENTORY,
            "phase10c1_source_inventory_sha256": PHASE10C1_SOURCE_INVENTORY,
        },
        "source_binding_digest": _sha256_bytes(_canonical_bytes(bindings)),
    }
    return {
        **payload,
        "validation_lock_id": deterministic_hash(LOCK_NAMESPACE, payload),
    }


def _not_opened(schema_suffix: str, dataset_id: str, status: str) -> dict[str, Any]:
    return {
        "schema_version": f"{STUDY_SCHEMA}_{schema_suffix}",
        "dataset_id": dataset_id,
        "status": status,
        "selector_outputs": [],
    }


def _decision(
    validation: Mapping[str, Any],
    lock: Mapping[str, Any],
    holdout: Mapping[str, Any],
    temporal: Mapping[str, Any],
    dense_diagnostic: Mapping[str, Any],
) -> dict[str, Any]:
    if validation["status"] == "NO_STRUCTURAL_SELECTION_FINALIST":
        status = "NO_STRUCTURAL_SELECTION_FINALIST"
    elif holdout["status"] != "STRUCTURAL_SELECTION_HOLDOUT_PASSED":
        status = "STRUCTURAL_SELECTION_HOLDOUT_REJECTED"
    elif temporal["status"] != "STRUCTURAL_SELECTION_TEMPORAL_PASSED":
        status = "STRUCTURAL_SELECTION_TEMPORAL_REJECTED"
    else:
        status = "STRUCTURAL_SELECTION_PROMOTION_CANDIDATE"
    payload = {
        "schema_version": f"{STUDY_SCHEMA}_decision",
        "study_status": status,
        "contract_id": CONTRACT_ID,
        "validation_lock_id": lock["validation_lock_id"],
        "validation_status": validation["status"],
        "validation_winner": validation["winner"],
        "validation_gate_results": validation["all_variants"],
        "validation_eligible_variants": validation["eligible_variants"],
        "holdout_status": holdout["status"],
        "holdout_result_id": holdout.get("result_id"),
        "temporal_status": temporal["status"],
        "temporal_result_id": temporal.get("result_id"),
        "dense_diagnostic_baseline": dense_diagnostic,
        "execution": {
            "provider_execution_count": 0,
            "network_request_count": 0,
            "configuration_variant_count": 0,
            "parallel_execution_count": 0,
        },
        "sources": _contract_payload()["sources"],
    }
    return {**payload, "decision_id": deterministic_hash(DECISION_NAMESPACE, payload)}


def _dense_diagnostic_baseline() -> dict[str, Any]:
    """Reproduce Phase 10C.2 checkpoint-1 dense baseline without a provider call."""

    _, full_input = phase10c2._verify_source()
    checkpoint = phase10c2.CHECKPOINTS[0]
    path = TEMPORAL_ROOT / "datasets" / "btcusdt_4h" / (
        f"checkpoint_{checkpoint.index:02d}_"
        f"{checkpoint.observed_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    payload = phase10c2._load_json(path)
    result = phase10c2._typed_provider_result(payload["provider_result"])
    if (
        result.request.input_data.input_identity != payload["prefix_input_identity"]
        or result.request.input_data.row_count != payload["prefix_row_count"]
        or result.request.asset != "BTCUSDT"
        or result.request.timeframe != "4h"
    ):
        raise StudyError("dense baseline provider binding drift")
    records = _records_for_checkpoint(
        result,
        full_input,
        checkpoint=checkpoint.observed_at,
        prefix_last_position=result.request.input_data.row_count - 1,
    )
    selected = _latest_predecessor(records)
    spans = [int(item.fields["anchor_span_bars"]) for item in selected]
    if not spans:
        raise StudyError("dense baseline has no selected records")
    prefix_row_count = result.request.input_data.row_count
    active_counts = [
        sum(
            int(item.fields["anchor_source_positions"][0]) <= position <= int(
                item.fields["anchor_source_positions"][1]
            )
            for item in selected
        )
        for position in range(prefix_row_count)
    ]
    role_counts = {
        role: sum(item.fields["role"] == role for item in selected)
        for role in ROLES
    }
    span_distribution: dict[str, int] = {}
    for span in sorted(spans):
        key = str(span)
        span_distribution[key] = span_distribution.get(key, 0) + 1
    summary = {
        "selector_id": "latest_valid_predecessor_v1",
        "dense_diagnostic_only": True,
        "checkpoint_index": checkpoint.index,
        "checkpoint": _iso(checkpoint.observed_at),
        "raw_candidate_count": len(result.candidates),
        "available_candidate_count": len(records),
        "selected_candidate_count": len(selected),
        "role_counts": role_counts,
        "anchor_span_bars": {
            "min": min(spans),
            "median": statistics.median(spans),
            "max": max(spans),
            "count_le_4": sum(span <= 4 for span in spans),
            "count_le_8": sum(span <= 8 for span in spans),
            "count_ge_24": sum(span >= 24 for span in spans),
            "distribution": span_distribution,
        },
        "crowding": {
            "source_row_count": prefix_row_count,
            "raw_candidates_per_bar": len(result.candidates) / prefix_row_count,
            "selected_candidates_per_bar": len(selected) / prefix_row_count,
            "active_segments_per_bar": {
                "min": min(active_counts),
                "median": statistics.median(active_counts),
                "max": max(active_counts),
                "p95": statistics.quantiles(active_counts, n=20, method="inclusive")[18],
            },
        },
    }
    summary["baseline_id"] = deterministic_hash(
        RESULT_NAMESPACE,
        {key: value for key, value in summary.items() if key != "baseline_id"},
    )
    return summary


def _manifest(root: Path, decision: Mapping[str, Any]) -> dict[str, Any]:
    members = tuple(item for item in _inventory(root) if item["path"] != "manifest.json")
    if len(members) != 20:
        raise StudyError(f"expected 20 manifest members, got {len(members)}")
    payload = {
        "schema_version": f"{STUDY_SCHEMA}_manifest",
        "contract_id": CONTRACT_ID,
        "decision_id": decision["decision_id"],
        "member_count": len(members),
        "members": list(members),
        "source_inventories": {
            "phase9c1": PHASE9C1_SOURCE_INVENTORY,
            "phase9c2": PHASE9C2_OUTPUT_INVENTORY,
            "phase10c1": PHASE10C1_SOURCE_INVENTORY,
            "phase10c2": PHASE10C2_OUTPUT_INVENTORY,
        },
    }
    return {**payload, "manifest_id": deterministic_hash(MANIFEST_NAMESPACE, payload)}


def _source_audit(bindings: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": f"{STUDY_SCHEMA}_source_audit",
        "bindings": bindings,
        "source_immutability_verified": True,
        "provider_execution_count": 0,
        "network_request_count": 0,
        "replay_execution_count": 0,
        "configuration_variant_count": 0,
    }


def _summary_rows(metrics_by_dataset: Mapping[str, Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    rows = []
    for dataset_id in sorted(metrics_by_dataset):
        for selector in metrics_by_dataset[dataset_id]["selectors"]:
            gate = selector["comparison_to_hash_control"]
            rows.append(
                {
                    "dataset_id": dataset_id,
                    "selector_id": selector["selector_id"],
                    "budget_per_role": selector["budget_per_role"],
                    "dataset_result_id": metrics_by_dataset[dataset_id]["dataset_result_id"],
                    "selected_count": selector["structural"]["selected_count"],
                    "median_anchor_span_hours": selector["structural"]["median_anchor_span_hours"],
                    "current_validity_rate": selector["structural"]["current_validity_rate"],
                    "combined_identity_jaccard_median": selector["stability"]["combined_identity_jaccard_median"],
                    "survival_delta_48h_vs_hash": gate["48h"]["survival_delta"],
                    "survival_delta_96h_vs_hash": gate["96h"]["survival_delta"],
                    "contact_and_survival_delta_96h_vs_hash": gate["96h"]["contact_and_survival_delta"],
                }
            )
    return tuple(rows)


def _temporal_summary_rows(temporal: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    if temporal["status"] != "STRUCTURAL_SELECTION_TEMPORAL_PASSED":
        return (
            {
                "status": temporal["status"],
                "checkpoint_index": None,
                "selector_id": None,
                "budget_per_role": None,
                "selected_count": None,
                "support_count": None,
                "resistance_count": None,
                "combined_identity_jaccard": None,
            },
        )
    return tuple(temporal["summary_rows"])


def _build_scope_results(
    datasets: Sequence[ScopeDataset],
    *,
    variants: Sequence[tuple[str, int | None]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    memberships: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    for dataset in datasets:
        membership, result = _analyze_dataset(dataset, variants=variants)
        memberships[dataset.dataset_id] = membership
        metrics[dataset.dataset_id] = result
    return memberships, metrics


def _holdout_result(
    validation: Mapping[str, Any],
    *,
    bindings: Mapping[str, Any],
    holdout_datasets: Sequence[ScopeDataset] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    winner = validation["winner"]
    if winner is None:
        result = {
            "schema_version": f"{STUDY_SCHEMA}_holdout",
            "status": "NOT_OPENED_BEFORE_VALIDATION_LOCK",
            "winner": None,
        }
        return result, {
            dataset_id: _not_opened(
                "checkpoint_membership",
                dataset_id,
                "NOT_OPENED_BEFORE_VALIDATION_LOCK",
            )
            for dataset_id in HOLDOUT_DATASETS
        }
    if holdout_datasets is None:
        raise StudyError("holdout datasets required after validation lock")
    variants = (
        ("hash_order_matched_budget_v1", winner["budget_per_role"]),
        (winner["selector_id"], winner["budget_per_role"]),
    )
    memberships, metrics = _build_scope_results(holdout_datasets, variants=variants)
    selected = [metrics[dataset_id]["selectors"][1] for dataset_id in HOLDOUT_DATASETS]
    reasons = []
    for item in selected:
        structural = item["structural"]
        if any(value < 0.9 for value in structural["role_coverage_ratio"].values()):
            reasons.append("role_coverage")
        if not all(structural["role_counts_within_gate"].values()):
            reasons.append("role_counts")
        if (structural["median_anchor_span_hours"] or 0) < 168:
            reasons.append("median_span")
        if structural["current_validity_rate"] != 1.0:
            reasons.append("current_validity")
        if structural["redundancy_violation_count"] != 0:
            reasons.append("redundancy")
        if (item["stability"]["combined_identity_jaccard_median"] or 0) < 0.35:
            reasons.append("stability")
    pooled_survival = _pooled_delta(
        metrics,
        selector=winner["selector_id"],
        budget=winner["budget_per_role"],
        horizon="96h",
        field="survival_rate",
    )
    pooled_contact_survival = _pooled_delta(
        metrics,
        selector=winner["selector_id"],
        budget=winner["budget_per_role"],
        horizon="96h",
        field="contact_and_survival_rate",
    )
    if pooled_survival is None or pooled_survival < 0:
        reasons.append("pooled_96h_survival")
    if pooled_contact_survival is None or pooled_contact_survival < -0.02:
        reasons.append("pooled_96h_contact_and_survival")
    payload = {
        "schema_version": f"{STUDY_SCHEMA}_holdout",
        "status": "STRUCTURAL_SELECTION_HOLDOUT_PASSED" if not reasons else "STRUCTURAL_SELECTION_HOLDOUT_REJECTED",
        "winner": winner,
        "rejection_reasons": sorted(set(reasons)),
        "dataset_result_ids": {
            dataset_id: metrics[dataset_id]["dataset_result_id"] for dataset_id in HOLDOUT_DATASETS
        },
        "source_binding_digest": _sha256_bytes(_canonical_bytes(bindings)),
    }
    payload["result_id"] = deterministic_hash(RESULT_NAMESPACE, payload)
    return payload, memberships


def _temporal_result(
    validation: Mapping[str, Any],
    holdout: Mapping[str, Any],
    *,
    bindings: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    winner = validation["winner"]
    if winner is None or holdout["status"] != "STRUCTURAL_SELECTION_HOLDOUT_PASSED":
        status = (
            "NOT_OPENED_BEFORE_VALIDATION_LOCK"
            if winner is None
            else "NOT_OPENED_AFTER_HOLDOUT_GATE"
        )
        result = {
            "schema_version": f"{STUDY_SCHEMA}_temporal",
            "status": status,
            "winner": winner,
        }
        return (
            result,
            {
                "schema_version": f"{STUDY_SCHEMA}_temporal_checkpoint_membership",
                "dataset_id": "btcusdt_4h",
                "status": status,
                "selector_outputs": [],
            },
            {
                "schema_version": f"{STUDY_SCHEMA}_temporal_selector_metrics",
                "dataset_id": "btcusdt_4h",
                "status": status,
                "selector_outputs": [],
            },
        )
    dataset = _load_temporal_scope()
    variants = (
        ("hash_order_matched_budget_v1", winner["budget_per_role"]),
        (winner["selector_id"], winner["budget_per_role"]),
    )
    membership, metrics = _build_scope_results((dataset,), variants=variants)
    finalist = metrics["btcusdt_4h"]["selectors"][1]
    reasons = []
    structural = finalist["structural"]
    if not all(structural["role_counts_within_gate"].values()):
        reasons.append("role_counts")
    if (structural["median_anchor_span_hours"] or 0) < 168:
        reasons.append("median_span")
    if structural["current_validity_rate"] != 1.0:
        reasons.append("current_validity")
    if structural["redundancy_violation_count"] != 0:
        reasons.append("redundancy")
    if (finalist["stability"]["combined_identity_jaccard_median"] or 0) < 0.25:
        reasons.append("stability")
    final_counts = finalist["checkpoint_metrics"][-1]["selected_candidate_count"]
    if final_counts > 16:
        reasons.append("final_selected_count")
    payload = {
        "schema_version": f"{STUDY_SCHEMA}_temporal",
        "status": "STRUCTURAL_SELECTION_TEMPORAL_PASSED" if not reasons else "STRUCTURAL_SELECTION_TEMPORAL_REJECTED",
        "winner": winner,
        "rejection_reasons": sorted(set(reasons)),
        "selector_result_id": finalist["selector_result_id"],
        "source_binding_digest": _sha256_bytes(_canonical_bytes(bindings)),
    }
    payload["result_id"] = deterministic_hash(RESULT_NAMESPACE, payload)
    summary_rows = []
    for row in finalist["checkpoint_metrics"]:
        summary_rows.append(
            {
                "status": payload["status"],
                "checkpoint_index": row["checkpoint_index"],
                "selector_id": winner["selector_id"],
                "budget_per_role": winner["budget_per_role"],
                "selected_count": row["selected_candidate_count"],
                "support_count": row["support_count"],
                "resistance_count": row["resistance_count"],
                "combined_identity_jaccard": next(
                    (
                        item["combined_identity_jaccard"]
                        for item in finalist["stability"]["rows"]
                        if item["role"] == "combined"
                        and item["checkpoint_index"] == row["checkpoint_index"]
                    ),
                    None,
                ),
            }
        )
    payload["summary_rows"] = summary_rows
    return payload, membership["btcusdt_4h"], metrics["btcusdt_4h"]


def _prepare_staging(output_root: Path) -> Path:
    if output_root.exists():
        raise FileExistsError(f"refusing existing output root: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    return Path(
        tempfile.mkdtemp(
            prefix=f".{output_root.name}.",
            dir=output_root.parent,
        )
    )


def _persist_and_verify_validation_lock(
    staging: Path,
    lock: Mapping[str, Any],
    *,
    validation: Mapping[str, Any],
    bindings: Mapping[str, Any],
    metrics_by_dataset: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    path = staging / "validation_lock.json"
    _write_json(path, lock)
    persisted = _load_json(path)
    expected = _validation_lock(
        validation,
        bindings=bindings,
        metrics_by_dataset=metrics_by_dataset,
    )
    if persisted != expected:
        raise StudyError("persisted validation lock mismatch")
    payload = {
        key: value for key, value in persisted.items() if key != "validation_lock_id"
    }
    if persisted["validation_lock_id"] != deterministic_hash(LOCK_NAMESPACE, payload):
        raise StudyError("persisted validation lock ID mismatch")
    if path.read_bytes() != _canonical_bytes(persisted):
        raise StudyError("persisted validation lock bytes are not canonical")
    return persisted


def _build_bundle(
    *,
    output_root: Path,
    staging: Path,
    bindings: Mapping[str, Any],
    validation_memberships: Mapping[str, Mapping[str, Any]],
    validation_metrics: Mapping[str, Mapping[str, Any]],
    validation: Mapping[str, Any],
    lock: Mapping[str, Any],
    holdout: Mapping[str, Any],
    holdout_memberships: Mapping[str, Mapping[str, Any]],
    temporal: Mapping[str, Any],
    temporal_membership: Mapping[str, Mapping[str, Any]],
    temporal_metrics: Mapping[str, Mapping[str, Any]],
    dense_diagnostic: Mapping[str, Any],
) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(f"refusing existing output root: {output_root}")
    if not staging.is_dir():
        raise StudyError(f"publication staging directory missing: {staging}")
    try:
        contract_payload, contract_identity = _validated_contract()
        _write_json(
            staging / "study_contract.json",
            {
                "schema_version": CONTRACT_SCHEMA,
                "contract_id": contract_identity,
                "contract_payload": contract_payload,
            },
        )
        _write_json(staging / "source_audit.json", _source_audit(bindings))
        lock_path = staging / "validation_lock.json"
        if lock_path.exists():
            if _load_json(lock_path) != lock:
                raise StudyError("publication validation lock mismatch")
        else:
            _write_json(lock_path, lock)
        for dataset_id, membership in validation_memberships.items():
            _write_json(staging / "datasets" / dataset_id / "checkpoint_membership.json", membership)
            _write_json(staging / "datasets" / dataset_id / "selector_metrics.json", validation_metrics[dataset_id])
        for dataset_id in HOLDOUT_DATASETS:
            membership = holdout_memberships.get(dataset_id) or _not_opened(
                "checkpoint_membership", dataset_id, holdout["status"]
            )
            metrics = (
                holdout_memberships.get(f"{dataset_id}__metrics")
                or _not_opened("selector_metrics", dataset_id, holdout["status"])
            )
            _write_json(staging / "datasets" / dataset_id / "checkpoint_membership.json", membership)
            _write_json(staging / "datasets" / dataset_id / "selector_metrics.json", metrics)
        _write_json(staging / "temporal" / "btcusdt_4h" / "checkpoint_membership.json", temporal_membership)
        _write_json(staging / "temporal" / "btcusdt_4h" / "selector_metrics.json", temporal_metrics)
        _write_atomic(staging / "cross_scope_summary.csv", _csv_bytes(_summary_rows(validation_metrics)))
        _write_atomic(staging / "temporal_summary.csv", _csv_bytes(_temporal_summary_rows(temporal)))
        decision = _decision(
            validation,
            lock,
            holdout,
            temporal,
            dense_diagnostic,
        )
        _write_json(staging / "decision.json", decision)
        manifest = _manifest(staging, decision)
        _write_json(staging / "manifest.json", manifest)
        if output_root.exists():
            raise FileExistsError(f"refusing existing output root: {output_root}")
        os.replace(staging, output_root)
        return {
            "output_root": str(output_root),
            "study_status": decision["study_status"],
            "decision_id": decision["decision_id"],
            "manifest_id": manifest["manifest_id"],
            "output_inventory_sha256": _inventory_sha256(_inventory(output_root)),
        }
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _run_analysis(*, output_root: Path) -> dict[str, Any]:
    try:
        staging = _prepare_staging(output_root)
        _validated_contract()
        bindings = _source_bindings()
        validation_datasets = _load_validation_scope(bindings)
        variants = _selector_variants()
        validation_memberships, validation_metrics = _build_scope_results(
            validation_datasets,
            variants=variants,
        )
        validation = _validation_result(validation_metrics)
        lock = _persist_and_verify_validation_lock(
            staging,
            _validation_lock(
                validation,
                bindings=bindings,
                metrics_by_dataset=validation_metrics,
            ),
            validation=validation,
            bindings=bindings,
            metrics_by_dataset=validation_metrics,
        )
        holdout_datasets = None
        holdout_memberships: dict[str, Mapping[str, Any]] = {}
        holdout = {
            "schema_version": f"{STUDY_SCHEMA}_holdout",
            "status": "NOT_OPENED_BEFORE_VALIDATION_LOCK",
            "winner": None,
        }
        if validation["winner"] is not None:
            context = phase9c2._load_cohort()
            config = phase9c2._foundation_config()
            provider_config = phase9c2._provider_config()
            by_id = {dataset.dataset_id: dataset for dataset in context.datasets}
            holdout_list = []
            for dataset_id in HOLDOUT_DATASETS:
                dataset = by_id[dataset_id]
                provider_result = phase9c2._load_persisted_provider_result(
                    SOURCE_ROOT, dataset, config, provider_config
                )
                schedule = _checkpoint_schedule(dataset.input_data)
                holdout_list.append(
                    ScopeDataset(
                        dataset_id=dataset_id,
                        asset=dataset.asset,
                        timeframe=dataset.timeframe,
                        data=dataset.input_data,
                        input_identity=dataset.input_data.input_identity,
                        checkpoints=tuple(
                            ScopeCheckpoint(
                                dataset_id=dataset_id,
                                checkpoint_index=index,
                                checkpoint=checkpoint,
                                data=dataset.input_data,
                                result=provider_result,
                                prefix_last_position=prefix_last,
                                source_provider_result_id=phase9c2._provider_result_id(provider_result),
                            )
                            for index, checkpoint, prefix_last in schedule
                        ),
                    )
                )
            holdout_datasets = tuple(holdout_list)
            holdout, holdout_memberships = _holdout_result(
                validation,
                bindings=bindings,
                holdout_datasets=holdout_datasets,
            )
        temporal, temporal_membership, temporal_metrics = _temporal_result(
            validation,
            holdout,
            bindings=bindings,
        )
        dense_diagnostic = _dense_diagnostic_baseline()
        _assert_source_unchanged(bindings)
        result = _build_bundle(
            output_root=output_root,
            staging=staging,
            bindings=bindings,
            validation_memberships=validation_memberships,
            validation_metrics=validation_metrics,
            validation=validation,
            lock=lock,
            holdout=holdout,
            holdout_memberships=holdout_memberships,
            temporal=temporal,
            temporal_membership=temporal_membership,
            temporal_metrics=temporal_metrics,
            dense_diagnostic=dense_diagnostic,
        )
        generation_flag = os.environ.pop("TRENDLINE_V2_ALLOW_PHASE11S1_STUDY", None)
        try:
            verified = verify_bundle(output_root=output_root)
        finally:
            if generation_flag is not None:
                os.environ["TRENDLINE_V2_ALLOW_PHASE11S1_STUDY"] = generation_flag
        if verified["decision_id"] != result["decision_id"]:
            raise StudyError("post-publication decision mismatch")
        return result
    except Exception:
        if "staging" in locals():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def verify_bundle(*, output_root: str | Path = OUTPUT_ROOT) -> dict[str, Any]:
    """Reconstruct every derived member with zero provider/network calls."""

    if os.environ.get("TRENDLINE_V2_ALLOW_PHASE11S1_STUDY") == "1":
        raise StudyError("verification cannot run with generation environment enabled")
    root = Path(output_root)
    expected_paths = {
        "study_contract.json",
        "source_audit.json",
        "validation_lock.json",
        "cross_scope_summary.csv",
        "temporal_summary.csv",
        "decision.json",
        "manifest.json",
        *(f"datasets/{dataset}/{name}.json" for dataset in VALIDATION_DATASETS + HOLDOUT_DATASETS for name in ("checkpoint_membership", "selector_metrics")),
        "temporal/btcusdt_4h/checkpoint_membership.json",
        "temporal/btcusdt_4h/selector_metrics.json",
    }
    actual_inventory = _inventory(root)
    if {item["path"] for item in actual_inventory} != expected_paths or len(actual_inventory) != 21:
        raise StudyError("study output must contain exact 21-file inventory")
    if _inventory_sha256(actual_inventory) != PINNED_OUTPUT_INVENTORY:
        raise StudyError("study output inventory drift")
    contract_payload, contract_id = _validated_contract()
    contract = _load_json(root / "study_contract.json")
    if contract != {
        "schema_version": CONTRACT_SCHEMA,
        "contract_id": contract_id,
        "contract_payload": contract_payload,
    }:
        raise StudyError("study contract mismatch")
    bindings = _source_bindings()
    source_audit = _load_json(root / "source_audit.json")
    if source_audit != _source_audit(bindings):
        raise StudyError("source audit mismatch")
    validation_datasets = _load_validation_scope(bindings)
    variants = _selector_variants()
    validation_memberships, validation_metrics = _build_scope_results(
        validation_datasets,
        variants=variants,
    )
    validation = _validation_result(validation_metrics)
    lock = _load_json(root / "validation_lock.json")
    if lock != _validation_lock(validation, bindings=bindings, metrics_by_dataset=validation_metrics):
        raise StudyError("validation lock mismatch")
    for dataset_id in VALIDATION_DATASETS:
        if _load_json(root / "datasets" / dataset_id / "checkpoint_membership.json") != validation_memberships[dataset_id]:
            raise StudyError(f"validation membership mismatch: {dataset_id}")
        if _load_json(root / "datasets" / dataset_id / "selector_metrics.json") != validation_metrics[dataset_id]:
            raise StudyError(f"validation metrics mismatch: {dataset_id}")
    holdout: dict[str, Any]
    if validation["winner"] is None:
        holdout = {
            "schema_version": f"{STUDY_SCHEMA}_holdout",
            "status": "NOT_OPENED_BEFORE_VALIDATION_LOCK",
            "winner": None,
        }
        for dataset_id in HOLDOUT_DATASETS:
            expected = _not_opened("checkpoint_membership", dataset_id, holdout["status"])
            if _load_json(root / "datasets" / dataset_id / "checkpoint_membership.json") != expected:
                raise StudyError(f"holdout membership was opened: {dataset_id}")
            expected_metrics = _not_opened("selector_metrics", dataset_id, holdout["status"])
            if _load_json(root / "datasets" / dataset_id / "selector_metrics.json") != expected_metrics:
                raise StudyError(f"holdout metrics was opened: {dataset_id}")
    else:
        raise StudyError("reconstruction with finalist requires explicit locked holdout path")
    temporal, expected_temporal_membership, expected_temporal_metrics = _temporal_result(
        validation,
        holdout,
        bindings=bindings,
    )
    if _load_json(root / "temporal" / "btcusdt_4h" / "checkpoint_membership.json") != expected_temporal_membership:
        raise StudyError("temporal membership mismatch")
    if _load_json(root / "temporal" / "btcusdt_4h" / "selector_metrics.json") != expected_temporal_metrics:
        raise StudyError("temporal metrics mismatch")
    if (root / "cross_scope_summary.csv").read_bytes() != _csv_bytes(_summary_rows(validation_metrics)):
        raise StudyError("cross-scope summary mismatch")
    if (root / "temporal_summary.csv").read_bytes() != _csv_bytes(_temporal_summary_rows(temporal)):
        raise StudyError("temporal summary mismatch")
    dense_diagnostic = _dense_diagnostic_baseline()
    decision = _load_json(root / "decision.json")
    expected_decision = _decision(
        validation,
        lock,
        holdout,
        temporal,
        dense_diagnostic,
    )
    if decision != expected_decision:
        raise StudyError("decision mismatch")
    manifest = _load_json(root / "manifest.json")
    expected_manifest = _manifest(root, decision)
    if manifest != expected_manifest:
        raise StudyError("manifest mismatch")
    if _inventory_sha256(_inventory(root)) != _inventory_sha256(actual_inventory):
        raise StudyError("output inventory changed during verification")
    _assert_source_unchanged(bindings)
    return {
        "study_status": decision["study_status"],
        "decision_id": decision["decision_id"],
        "manifest_id": manifest["manifest_id"],
        "output_inventory_sha256": _inventory_sha256(actual_inventory),
        "provider_execution_count": 0,
        "network_request_count": 0,
    }


def run_study(*, output_root: str | Path = OUTPUT_ROOT) -> dict[str, Any]:
    root = Path(output_root)
    if root.exists():
        raise FileExistsError(f"refusing existing output root: {root}")
    if os.environ.get("TRENDLINE_V2_ALLOW_PHASE11S1_STUDY") != "1":
        raise StudyError("real study requires TRENDLINE_V2_ALLOW_PHASE11S1_STUDY=1")
    return _run_analysis(output_root=root)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-study", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    if args.execute_study == args.verify:
        parser.error("choose exactly one of --execute-study or --verify")
    try:
        result = (
            run_study(output_root=args.output_root)
            if args.execute_study
            else verify_bundle(output_root=args.output_root)
        )
    except (FileExistsError, OSError, StudyError, ContractValidationError) as exc:
        print(str(exc))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
