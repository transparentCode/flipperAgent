"""Evaluate a causal actionable-interaction shortlist from frozen evidence.

This is offline research only. It reads verified Phase 13H.1 active rows and
the pinned Phase 9C.2 candles, evaluates predeclared interaction policies and
matched controls, and publishes a source-bound diagnostic bundle. It never
calls a provider, network, holdout or temporal source.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import statistics
import tempfile
from typing import Any, Mapping, Sequence

from libs.models.trendline_v2.domain.identity import canonical_json, deterministic_hash
from scripts import analyze_trendline_v2_consensus_corridor_families as h1
from scripts import analyze_trendline_v2_quality_signal_feasibility as source_loader


STUDY_SCHEMA = "trendline_v2_phase_14a1r1_actionable_interaction_shortlist_v1"
CONTRACT_NAMESPACE = f"{STUDY_SCHEMA}_contract"
SOURCE_NAMESPACE = f"{STUDY_SCHEMA}_source_binding"
FEATURE_NAMESPACE = f"{STUDY_SCHEMA}_feature"
OUTCOME_NAMESPACE = f"{STUDY_SCHEMA}_outcome"
BOOTSTRAP_NAMESPACE = f"{STUDY_SCHEMA}_bootstrap"
LOCK_NAMESPACE = f"{STUDY_SCHEMA}_validation_lock"
DECISION_NAMESPACE = f"{STUDY_SCHEMA}_decision"
INVENTORY_NAMESPACE = f"{STUDY_SCHEMA}_output_inventory"
MANIFEST_NAMESPACE = f"{STUDY_SCHEMA}_manifest"

H1_ROOT = Path(
    "/tmp/trendline_v2_phase13h1_consensus_corridor_families/20260522_20260701"
)
SOURCE_ROOT = Path(
    "/tmp/trendline_v2_phase9c2_fresh_scope_family_validation/20260522_20260701"
)
OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_phase14a1r1_actionable_interaction_shortlist/"
    "20260522_20260701"
)

H1_COMMIT = "f59523c9cb8353575d79003a96e4c5f9c09aca00"
H1_DECISION_ID = "2cf8dcb50c4efa903108dc71b420347e0ab6187e1e86c0f151b6732e1bb8263c"
H1_MANIFEST_ID = "1cff9a2dab15feeec7cae52a8507eb25625b63294b7acf6a82bf161396463471"
H1_INVENTORY_SHA256 = "b232ab323f7bb100eefc34f0c255180f73232e1bc52910b285ea23d26ee23da8"

SOURCE_DECISION_ID = "4b734cbf99e1453bccdedb95f397f4b34e020f29e3d18808a131456647f78f7c"
SOURCE_MANIFEST_ID = "beab5b9acb2bfc3c25ba9cb5cb31c33c1a31e6069c1d7906f3ed5e1c2d798c81"
SOURCE_INVENTORY_SHA256 = "ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532"
UNDERLYING_SOURCE_INVENTORY_SHA256 = "631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be"
SOURCE_MANIFEST_SHA256 = "4db6402a4fdd911cbe8a1b4b30f8ee27431e2f2c751a572d1fec92f0b7d25121"

DATASETS = ("btcusdt_1h", "btcusdt_4h", "ethusdt_1h", "ethusdt_4h")
HOLDOUT_DATASETS = ("suiusdt_1h", "suiusdt_4h")
ROLES = ("support", "resistance")
ACTIONABLE_STATES = ("CONTACTING", "NEAR", "APPROACHING")
ALL_STATES = (*ACTIONABLE_STATES, "DORMANT")
BUDGETS = (5, 10)
BOOTSTRAP_REPLICATES = 1_000
BOOTSTRAP_MIN_VALID = 950
BOOTSTRAP_CONFIDENCE = 0.95
HORIZON_HOURS = (24, 48, 96)
FOCUS_RECENT_BARS = 100
FOCUS_MIN_ANCHOR_SPAN = 25
FOCUS_MAX_PER_ROLE = 12

POLICIES = (
    {
        "policy_id": "actionable_immediate_v1",
        "lookback_hours": 24,
        "near_threshold_atr": 0.50,
        "maximum_projected_contact_hours": 24,
        "minimum_approach_consistency": 0.60,
        "minimum_net_closure_atr": 0.50,
    },
    {
        "policy_id": "actionable_balanced_v1",
        "lookback_hours": 48,
        "near_threshold_atr": 1.00,
        "maximum_projected_contact_hours": 48,
        "minimum_approach_consistency": 0.60,
        "minimum_net_closure_atr": 0.50,
    },
    {
        "policy_id": "actionable_broad_v1",
        "lookback_hours": 96,
        "near_threshold_atr": 2.00,
        "maximum_projected_contact_hours": 96,
        "minimum_approach_consistency": 0.60,
        "minimum_net_closure_atr": 0.50,
    },
)

ARTIFACT_NAMES = (
    "study_contract.json",
    "source_binding.json",
    "checkpoint_population.json",
    "actionability_feature_rows.json",
    "state_membership.json",
    "shortlist_membership.json",
    "future_interaction_outcomes.json",
    "policy_metrics.json",
    "control_metrics.json",
    "validation_lock.json",
    "decision.json",
    "output_inventory.json",
    "manifest.json",
)
MEMBER_NAMES = ARTIFACT_NAMES[:-1]


class StudyError(RuntimeError):
    """Raised when frozen evidence or study contracts fail closed."""


def _identity(namespace: str, payload: Mapping[str, Any]) -> str:
    return deterministic_hash(namespace, payload)


def _canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise StudyError(f"cannot read file: {path}") from exc


def _load_verified_phase9_manifest() -> dict[str, Any]:
    try:
        return source_loader._load_source_manifest(SOURCE_ROOT)
    except source_loader.StudyError as exc:
        raise StudyError(str(exc)) from exc


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StudyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise StudyError(f"non-finite JSON constant: {value}")


def _load_json_bytes(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError) as exc:
        raise StudyError("invalid JSON") from exc
    if not isinstance(value, dict):
        raise StudyError("JSON object required")
    if raw != _canonical_bytes(value):
        raise StudyError("non-canonical JSON")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return _load_json_bytes(path.read_bytes())
    except OSError as exc:
        raise StudyError(f"cannot read JSON: {path}") from exc


def _parse_ns(value: str) -> int:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StudyError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise StudyError("timestamp must be timezone-aware")
    return int(parsed.timestamp() * 1_000_000_000)


def _iso(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _finite(value: object, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise StudyError(f"{field} is not numeric") from exc
    if not math.isfinite(result):
        raise StudyError(f"{field} is not finite")
    return result


def _percentile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _source_snapshot() -> dict[str, Any]:
    if not SOURCE_ROOT.is_dir() or SOURCE_ROOT.is_symlink():
        raise StudyError("Phase 9C.2 source root missing or symlinked")
    _load_verified_phase9_manifest()
    member_hashes = {
        relative: _sha256_file(SOURCE_ROOT / "datasets" / relative)
        for relative in sorted(source_loader.EXPECTED_MEMBER_HASHES)
    }
    manifest_sha256 = _sha256_file(SOURCE_ROOT / "manifest.json")
    if manifest_sha256 != SOURCE_MANIFEST_SHA256:
        raise StudyError("Phase 9C.2 manifest hash mismatch")
    payload = {
        "schema_version": f"{STUDY_SCHEMA}_source_snapshot_v1",
        "source_manifest_sha256": manifest_sha256,
        "member_hashes": member_hashes,
    }
    return {**payload, "snapshot_id": _identity(f"{STUDY_SCHEMA}_source_snapshot", payload)}


def _validate_phase9_source() -> dict[str, Any]:
    manifest = _load_verified_phase9_manifest()
    if manifest.get("source_decision_id") != SOURCE_DECISION_ID:
        raise StudyError("Phase 9C.2 source decision mismatch")
    if manifest.get("source_manifest_id") != SOURCE_MANIFEST_ID:
        raise StudyError("Phase 9C.2 source manifest identity mismatch")
    if manifest.get("source_inventory_sha256") != SOURCE_INVENTORY_SHA256:
        raise StudyError("Phase 9C.2 output inventory mismatch")
    if manifest.get("underlying_source_inventory_sha256") != UNDERLYING_SOURCE_INVENTORY_SHA256:
        raise StudyError("Phase 9C.2 underlying inventory mismatch")
    return _source_snapshot()


def _load_phase9_datasets() -> tuple[Any, ...]:
    try:
        datasets = tuple(source_loader._load_dataset(dataset_id, SOURCE_ROOT) for dataset_id in DATASETS)
    except source_loader.StudyError as exc:
        raise StudyError(str(exc)) from exc
    if tuple(dataset.dataset_id for dataset in datasets) != DATASETS:
        raise StudyError("dataset allowlist mismatch")
    return datasets


def _verify_h1_bundle() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    result = h1.verify_bundle(H1_ROOT)
    if result.get("decision_id") != H1_DECISION_ID:
        raise StudyError("Phase 13H.1 decision mismatch")
    if result.get("manifest_id") != H1_MANIFEST_ID:
        raise StudyError("Phase 13H.1 manifest mismatch")
    if result.get("output_inventory_sha256") != H1_INVENTORY_SHA256:
        raise StudyError("Phase 13H.1 inventory mismatch")
    manifest = _load_json(H1_ROOT / "manifest.json")
    if manifest.get("manifest_id") != H1_MANIFEST_ID or manifest.get("member_count") != 12:
        raise StudyError("Phase 13H.1 manifest contract mismatch")
    source_binding = _load_json(H1_ROOT / "source_binding.json")
    schedule = _load_json(H1_ROOT / "checkpoint_schedule.json")
    active = _load_json(H1_ROOT / "active_candidate_rows.json")
    if source_binding.get("source_decision_id") != SOURCE_DECISION_ID:
        raise StudyError("H.1 source decision binding mismatch")
    if source_binding.get("source_inventory_sha256") != SOURCE_INVENTORY_SHA256:
        raise StudyError("H.1 source inventory binding mismatch")
    if source_binding.get("source_immutability_verified") is not True:
        raise StudyError("H.1 source immutability not verified")
    if not isinstance(schedule.get("datasets"), dict) or not isinstance(active.get("rows"), list):
        raise StudyError("H.1 population schema mismatch")
    return manifest, source_binding, schedule, active


def _line_price(dataset: Any, candidate: Mapping[str, Any], position: int) -> float:
    return float(source_loader._line_price(candidate, position))


def _range_distance(dataset: Any, candidate: Mapping[str, Any], position: int) -> float:
    line = _line_price(dataset, candidate, position)
    atr = dataset.atr[position]
    if atr is None or float(atr) <= 0:
        raise StudyError("ATR unavailable for interaction feature")
    if candidate["role"] == "support":
        return max(0.0, float(dataset.lows[position]) - line) / float(atr)
    if candidate["role"] == "resistance":
        return max(0.0, line - float(dataset.highs[position])) / float(atr)
    raise StudyError(f"unsupported role: {candidate['role']}")


def _close_distance(dataset: Any, candidate: Mapping[str, Any], position: int) -> float:
    line = _line_price(dataset, candidate, position)
    atr = dataset.atr[position]
    if atr is None or float(atr) <= 0:
        raise StudyError("ATR unavailable for close feature")
    if candidate["role"] == "support":
        return (float(dataset.closes[position]) - line) / float(atr)
    return (line - float(dataset.closes[position])) / float(atr)


def _wick_contact(dataset: Any, candidate: Mapping[str, Any], position: int) -> bool:
    line = _line_price(dataset, candidate, position)
    return float(dataset.lows[position]) <= line <= float(dataset.highs[position])


def _body_intersection(dataset: Any, candidate: Mapping[str, Any], position: int) -> bool:
    line = _line_price(dataset, candidate, position)
    body_low = min(float(dataset.opens[position]), float(dataset.closes[position]))
    body_high = max(float(dataset.opens[position]), float(dataset.closes[position]))
    return body_low <= line <= body_high


def _policy_bars(dataset: Any, policy: Mapping[str, Any]) -> int:
    seconds = int(policy["lookback_hours"]) * 3_600
    if seconds % int(dataset.interval_seconds):
        raise StudyError("policy lookback is not representable in owner-timeframe bars")
    return seconds // int(dataset.interval_seconds)


def _horizon_bar_count(dataset: Any, horizon_hours: int) -> int:
    seconds = int(horizon_hours) * 3_600
    if seconds % int(dataset.interval_seconds):
        raise StudyError("horizon is not representable in owner-timeframe bars")
    return seconds // int(dataset.interval_seconds)


def _classify_state(
    *,
    contacting: bool,
    current_distance: float,
    median_delta: float,
    consistency: float,
    net_closure: float,
    projected_hours: float | None,
    policy: Mapping[str, Any],
) -> str:
    if contacting:
        return "CONTACTING"
    if current_distance <= float(policy["near_threshold_atr"]):
        return "NEAR"
    if (
        median_delta < 0
        and consistency >= float(policy["minimum_approach_consistency"])
        and net_closure >= float(policy["minimum_net_closure_atr"])
        and projected_hours is not None
        and projected_hours <= float(policy["maximum_projected_contact_hours"])
    ):
        return "APPROACHING"
    return "DORMANT"


def _feature_row(dataset: Any, checkpoint: Mapping[str, Any], candidate: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    prefix = int(checkpoint["checkpoint_position"])
    lookback_bars = _policy_bars(dataset, policy)
    start = max(0, prefix - lookback_bars)
    positions = list(range(start, prefix))
    if not positions:
        raise StudyError("empty causal interaction history")
    distances = [_range_distance(dataset, candidate, position) for position in positions]
    close_distances = [_close_distance(dataset, candidate, position) for position in positions]
    deltas = [right - left for left, right in zip(distances, distances[1:])]
    median_delta = statistics.median(deltas) if deltas else 0.0
    negative_deltas = [delta for delta in deltas if delta < 0]
    median_negative_delta = statistics.median(negative_deltas) if negative_deltas else None
    consistency = sum(delta < 0 for delta in deltas) / len(deltas) if deltas else 0.0
    current_distance = distances[-1]
    projected_bars = (
        current_distance / abs(float(median_negative_delta))
        if median_delta < 0 and median_negative_delta is not None and median_negative_delta < 0
        else None
    )
    projected_hours = projected_bars * float(dataset.interval_seconds) / 3_600 if projected_bars is not None else None
    contacts = [position for position in positions if _wick_contact(dataset, candidate, position)]
    current_position = positions[-1]
    state = _classify_state(
        contacting=_wick_contact(dataset, candidate, current_position),
        current_distance=current_distance,
        median_delta=median_delta,
        consistency=consistency,
        net_closure=distances[0] - current_distance,
        projected_hours=projected_hours,
        policy=policy,
    )
    features = {
        "current_range_distance_atr": current_distance,
        "current_close_distance_atr": close_distances[-1],
        "exact_wick_contact_now": _wick_contact(dataset, candidate, current_position),
        "body_intersection_now": _body_intersection(dataset, candidate, current_position),
        "starting_range_distance_atr": distances[0],
        "net_closure_atr": distances[0] - current_distance,
        "median_distance_delta_atr_per_bar": median_delta,
        "median_negative_distance_delta_atr_per_bar": median_negative_delta,
        "approach_consistency": consistency,
        "recent_minimum_distance_atr": min(distances),
        "last_exact_contact_age_bars": current_position - contacts[-1] if contacts else None,
        "projected_contact_bars": projected_bars,
        "projected_contact_hours": projected_hours,
        "lookback_bars": lookback_bars,
        "history_start_position": start,
        "history_end_position": current_position,
        "historical_positions": positions,
        "historical_range_distances_atr": distances,
        "historical_close_distances_atr": close_distances,
    }
    identity_payload = {
        "dataset_id": dataset.dataset_id,
        "checkpoint_index": checkpoint["checkpoint_index"],
        "role": candidate["role"],
        "candidate_id": candidate["candidate_id"],
        "candidate_structure_id": candidate["candidate_structure_id"],
        "first_anchor_id": candidate["first_anchor_id"],
        "second_anchor_id": candidate["second_anchor_id"],
        "source_positions": list(candidate["source_positions"]),
        "confirmation_positions": list(candidate["confirmation_positions"]),
        "policy_id": policy["policy_id"],
        "state": state,
        "features": features,
    }
    return {
        "feature_row_id": _identity(FEATURE_NAMESPACE, identity_payload),
        "dataset_id": dataset.dataset_id,
        "asset": dataset.asset,
        "timeframe": dataset.timeframe,
        "checkpoint_index": checkpoint["checkpoint_index"],
        "checkpoint": checkpoint["checkpoint"],
        "checkpoint_position": prefix,
        "role": candidate["role"],
        "candidate_id": candidate["candidate_id"],
        "candidate_structure_id": candidate["candidate_structure_id"],
        "first_anchor_id": candidate["first_anchor_id"],
        "second_anchor_id": candidate["second_anchor_id"],
        "anchor_source_positions": list(candidate["source_positions"]),
        "confirmation_positions": list(candidate["confirmation_positions"]),
        "anchor_span_bars": int(candidate["record"]["anchor_span_bars"]),
        "record_anchor_span_bars": int(candidate["record"]["anchor_span_bars"]),
        "policy_id": policy["policy_id"],
        "state": state,
        "actionable": state != "DORMANT",
        "features": features,
    }


def _selection_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    projected = row["features"]["projected_contact_hours"]
    return (
        {"CONTACTING": 0, "NEAR": 1, "APPROACHING": 2}[row["state"]],
        float(row["features"]["current_range_distance_atr"]),
        float(projected) if projected is not None else math.inf,
        -float(row["features"]["approach_consistency"]),
        -float(row["features"]["net_closure_atr"]),
        -int(row["confirmation_positions"][1]),
        str(row["candidate_structure_id"]),
        str(row["candidate_id"]),
    )


def _nearest_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (float(row["features"]["current_range_distance_atr"]), str(row["candidate_structure_id"]), str(row["candidate_id"]))


def _hash_key(row: Mapping[str, Any], cell_key: tuple[Any, ...]) -> tuple[str, str, str]:
    digest = _identity(f"{STUDY_SCHEMA}_hash_control", {"cell": list(cell_key), "structure": row["candidate_structure_id"]})
    return digest, str(row["candidate_structure_id"]), str(row["candidate_id"])


def _one_per_anchor(rows: Sequence[Mapping[str, Any]], key_fn: Any) -> list[Mapping[str, Any]]:
    selected: dict[str, Mapping[str, Any]] = {}
    ordered_rows = sorted(
        rows,
        key=lambda row: (
            str(row["second_anchor_id"]),
            str(row["candidate_structure_id"]),
            str(row["candidate_id"]),
        ),
    )
    for row in ordered_rows:
        anchor = str(row["second_anchor_id"])
        current = selected.get(anchor)
        if current is None or key_fn(row) < key_fn(current):
            selected[anchor] = row
    return [selected[anchor] for anchor in sorted(selected)]


def _focus_ids(
    rows: Sequence[Mapping[str, Any]],
    last_candle_position: int,
) -> tuple[str, ...]:
    result: list[str] = []
    for role in ROLES:
        eligible = [
            row for row in rows
            if row["role"] == role
            and last_candle_position - int(row["confirmation_positions"][1]) <= FOCUS_RECENT_BARS
            and int(row["record_anchor_span_bars"]) >= FOCUS_MIN_ANCHOR_SPAN
        ]
        representatives: dict[str, Mapping[str, Any]] = {}
        for row in eligible:
            anchor = str(row["second_anchor_id"])
            current = representatives.get(anchor)
            key = (-max(0, int(row["record_anchor_span_bars"]) - 1), -int(row["record_anchor_span_bars"]), row["candidate_id"])
            current_key = (
                (-max(0, int(current["record_anchor_span_bars"]) - 1), -int(current["record_anchor_span_bars"]), current["candidate_id"])
                if current is not None else None
            )
            if current is None or key < current_key:
                representatives[anchor] = row
        result.extend(
            row["candidate_structure_id"]
            for row in sorted(
                representatives.values(),
                key=lambda item: (
                    -int(item["confirmation_positions"][1]),
                    -max(0, int(item["record_anchor_span_bars"]) - 1),
                    -int(item["record_anchor_span_bars"]),
                    str(item["candidate_id"]),
                ),
            )[:FOCUS_MAX_PER_ROLE]
        )
    return tuple(result)


def _validate_active_population(
    active_payload: Mapping[str, Any],
    schedule_payload: Mapping[str, Any],
    datasets: Sequence[Any],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    dataset_map = {dataset.dataset_id: dataset for dataset in datasets}
    schedules = schedule_payload["datasets"]
    if set(schedules) != set(DATASETS):
        raise StudyError("H.1 schedule dataset set mismatch")
    schedule_map: dict[str, list[dict[str, Any]]] = {}
    for dataset_id in DATASETS:
        dataset = dataset_map[dataset_id]
        rows = schedules[dataset_id]
        if not isinstance(rows, list) or len(rows) != 27:
            raise StudyError(f"H.1 checkpoint count mismatch: {dataset_id}")
        if [int(row["checkpoint_index"]) for row in rows] != list(range(1, 28)):
            raise StudyError(f"H.1 checkpoint ordering mismatch: {dataset_id}")
        normalized: list[dict[str, Any]] = []
        for row in rows:
            checkpoint_ns = _parse_ns(row["checkpoint"])
            position = int(row["checkpoint_position"])
            expected = bisect_left(dataset.timestamps, checkpoint_ns)
            if expected != position or position < 1:
                raise StudyError(f"H.1 checkpoint prefix mismatch: {dataset_id}")
            if int(row["prefix_row_count"]) != position:
                raise StudyError(f"H.1 prefix row count mismatch: {dataset_id}")
            if position > 0 and dataset.timestamps[position - 1] >= checkpoint_ns:
                raise StudyError("checkpoint prefix includes future bar")
            if position < len(dataset.timestamps) and dataset.timestamps[position] < checkpoint_ns:
                raise StudyError("checkpoint prefix omits known bar")
            atr = dataset.atr[position - 1]
            if atr is None or float(atr) <= 0 or abs(float(atr) - float(row["checkpoint_atr_14"])) > 1e-12:
                raise StudyError("H.1 checkpoint ATR mismatch")
            if abs(float(dataset.closes[position - 1]) - float(row["checkpoint_close"])) > 1e-12:
                raise StudyError("H.1 checkpoint close mismatch")
            normalized.append({**row, "checkpoint_ns": checkpoint_ns})
        schedule_map[dataset_id] = normalized
    candidate_maps = {
        dataset_id: {candidate["candidate_id"]: candidate for candidate in dataset_map[dataset_id].candidates}
        for dataset_id in DATASETS
    }
    active_rows = active_payload["rows"]
    if len(active_rows) != 39_139:
        raise StudyError("H.1 active population count mismatch")
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[Any, ...]] = set()
    for row in active_rows:
        dataset_id = row.get("dataset_id")
        if dataset_id not in DATASETS:
            raise StudyError("H.1 active row dataset outside allowlist")
        dataset = dataset_map[dataset_id]
        identity = (dataset_id, int(row["checkpoint_index"]), row["role"], row["candidate_structure_id"])
        if identity in seen:
            raise StudyError("duplicate H.1 active structure identity")
        seen.add(identity)
        checkpoint = schedule_map[dataset_id][int(row["checkpoint_index"]) - 1]
        if not 1 <= int(row["checkpoint_index"]) <= 27:
            raise StudyError("H.1 active checkpoint outside schedule")
        if row["checkpoint"] != checkpoint["checkpoint"] or int(row["checkpoint_position"]) != int(checkpoint["checkpoint_position"]):
            raise StudyError("H.1 active row checkpoint mismatch")
        candidate = candidate_maps[dataset_id].get(row.get("candidate_id"))
        if candidate is None:
            raise StudyError("H.1 candidate ID missing from Phase 9C.2 source")
        for field in ("role", "candidate_structure_id", "first_anchor_id", "second_anchor_id"):
            expected = candidate[field]
            if row[field] != expected:
                raise StudyError(f"H.1 active row {field} mismatch")
        if list(candidate["source_positions"]) != list(row["anchor_source_positions"]):
            raise StudyError("H.1 source positions mismatch")
        if list(candidate["confirmation_positions"]) != list(row["confirmation_positions"]):
            raise StudyError("H.1 confirmation positions mismatch")
        if int(candidate["availability_position"]) != int(row["availability_position"]):
            raise StudyError("H.1 availability mismatch")
        if any(int(position) >= int(row["checkpoint_position"]) for position in row["anchor_source_positions"] + row["confirmation_positions"]):
            raise StudyError("H.1 active row includes future anchor evidence")
        if int(row["availability_position"]) > int(row["checkpoint_position"]):
            raise StudyError("H.1 active row is unavailable at checkpoint")
        if int(candidate["record"]["anchor_span_bars"]) != int(row["anchor_span_bars"]):
            raise StudyError("H.1 anchor span mismatch")
        for offset, key in ((0, "g0"), (24, "g24"), (96, "g96")):
            expected = (
                h1._line_price(dataset, candidate, int(checkpoint["checkpoint_ns"]) + offset * 3_600 * 1_000_000_000)
                - float(checkpoint["checkpoint_close"])
            ) / float(checkpoint["checkpoint_atr_14"])
            if abs(float(row[key]) - expected) > 1e-9:
                raise StudyError(f"H.1 geometry mismatch: {key}")
        result[dataset_id].append({
            **row,
            "candidate": candidate,
            "record_anchor_span_bars": int(candidate["record"]["anchor_span_bars"]),
        })
    if len(seen) != len(active_rows):
        raise StudyError("H.1 active identity reconciliation mismatch")
    return dict(result), {dataset_id: schedule_map[dataset_id] for dataset_id in DATASETS}


def _derive_features(
    active_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    schedules: Mapping[str, Sequence[Mapping[str, Any]]],
    datasets: Sequence[Any],
) -> list[dict[str, Any]]:
    dataset_map = {dataset.dataset_id: dataset for dataset in datasets}
    features: list[dict[str, Any]] = []
    for dataset_id in DATASETS:
        dataset = dataset_map[dataset_id]
        checkpoints = {int(row["checkpoint_index"]): row for row in schedules[dataset_id]}
        for active in active_by_dataset[dataset_id]:
            checkpoint = checkpoints[int(active["checkpoint_index"])]
            for policy in POLICIES:
                features.append(_feature_row(dataset, checkpoint, active["candidate"], policy))
    return sorted(features, key=lambda row: (row["dataset_id"], row["checkpoint_index"], row["role"], row["policy_id"], row["candidate_structure_id"], row["candidate_id"]))


def _selection_records(
    features: Sequence[Mapping[str, Any]],
    active_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[tuple[Any, ...], dict[str, set[str]]], list[dict[str, Any]], dict[str, Any]]:
    by_cell: dict[tuple[str, int, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in features:
        by_cell[(row["policy_id"], row["dataset_id"], int(row["checkpoint_index"]), row["role"])].append(row)
    membership: list[dict[str, Any]] = []
    selected: dict[tuple[Any, ...], dict[str, set[str]]] = {}
    control_rows: list[dict[str, Any]] = []
    state_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for cell_key, rows in sorted(by_cell.items()):
        policy_id, dataset_id, checkpoint_index, role = cell_key
        actionable = [row for row in rows if row["actionable"]]
        representatives = {row["second_anchor_id"]: row for row in _one_per_anchor(actionable, _selection_key)}
        representative_ids = {row["candidate_structure_id"] for row in representatives.values()}
        ordered = sorted(representatives.values(), key=_selection_key)
        state_counts[policy_id].update(row["state"] for row in rows)
        for budget in BUDGETS:
            contender = ordered[:budget]
            contender_ids = {row["candidate_structure_id"] for row in contender}
            nearest_pool = _one_per_anchor(rows, _nearest_key)
            nearest = sorted(nearest_pool, key=_nearest_key)[: len(contender)]
            hash_pool = _one_per_anchor(rows, lambda row: _hash_key(row, cell_key))
            hashed = sorted(hash_pool, key=lambda row: _hash_key(row, cell_key))[: len(contender)]
            key = (policy_id, dataset_id, checkpoint_index, role, budget)
            selected[key] = {
                "contender": contender_ids,
                "nearest_distance_control": {row["candidate_structure_id"] for row in nearest},
                "hash_order_control": {row["candidate_structure_id"] for row in hashed},
            }
            if len(contender) != len(nearest) or len(contender) != len(hashed):
                raise StudyError("control count matching failure")
            for row in rows:
                if not row["actionable"]:
                    reason = "NOT_ACTIONABLE"
                elif row["candidate_structure_id"] not in representative_ids:
                    reason = "DUPLICATE_SECOND_ANCHOR"
                elif row["candidate_structure_id"] in contender_ids:
                    reason = "SELECTED"
                else:
                    reason = "OUTSIDE_BUDGET"
                membership.append({
                    "policy_id": policy_id,
                    "budget": budget,
                    "dataset_id": dataset_id,
                    "checkpoint_index": checkpoint_index,
                    "role": role,
                    "source_kind": "contender",
                    "candidate_structure_id": row["candidate_structure_id"],
                    "candidate_id": row["candidate_id"],
                    "second_anchor_id": row["second_anchor_id"],
                    "state": row["state"],
                    "selection_status": reason,
                    "reason": reason,
                })
            for source_kind, selected_rows in (
                ("nearest_distance_control", nearest),
                ("hash_order_control", hashed),
            ):
                for row in selected_rows:
                    control_rows.append({
                        "policy_id": policy_id,
                        "budget": budget,
                        "dataset_id": dataset_id,
                        "checkpoint_index": checkpoint_index,
                        "role": role,
                        "source_kind": source_kind,
                        "candidate_structure_id": row["candidate_structure_id"],
                        "candidate_id": row["candidate_id"],
                        "state": row["state"],
                    })
        all_rows = list(rows)
        focus_ids = (
            set(_focus_ids(all_rows, int(rows[0]["checkpoint_position"]) - 1))
            if rows
            else set()
        )
        for row in sorted(all_rows, key=lambda item: (item["candidate_structure_id"], item["candidate_id"])):
            control_rows.append({
                "policy_id": policy_id,
                "budget": 0,
                "dataset_id": dataset_id,
                "checkpoint_index": checkpoint_index,
                "role": role,
                "source_kind": "all_valid",
                "candidate_structure_id": row["candidate_structure_id"],
                "candidate_id": row["candidate_id"],
                "state": row["state"],
            })
        for structure_id in sorted(focus_ids):
            row = next(item for item in rows if item["candidate_structure_id"] == structure_id)
            control_rows.append({
                "policy_id": policy_id,
                "budget": 0,
                "dataset_id": dataset_id,
                "checkpoint_index": checkpoint_index,
                "role": role,
                "source_kind": "current_focus",
                "candidate_structure_id": structure_id,
                "candidate_id": row["candidate_id"],
                "state": row["state"],
            })
    return (
        sorted(membership, key=lambda row: (row["policy_id"], row["dataset_id"], row["checkpoint_index"], row["role"], row["budget"], row["candidate_structure_id"])),
        selected,
        sorted(control_rows, key=lambda row: (row["policy_id"], row["dataset_id"], row["checkpoint_index"], row["role"], row["budget"], row["source_kind"], row["candidate_structure_id"])),
        {policy_id: dict(counts) for policy_id, counts in sorted(state_counts.items())},
    )


def _shortlist_stability(
    selected: Mapping[tuple[Any, ...], dict[str, set[str]]],
    schedules: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for policy in POLICIES:
        policy_id = policy["policy_id"]
        for budget in BUDGETS:
            for dataset_id in DATASETS:
                checkpoint_indices = [
                    int(row["checkpoint_index"])
                    for row in schedules[dataset_id]
                ]
                for role in ROLES:
                    lane_rows: list[dict[str, Any]] = []
                    for previous_index, current_index in zip(
                        checkpoint_indices,
                        checkpoint_indices[1:],
                    ):
                        previous = set(
                            selected.get(
                                (policy_id, dataset_id, previous_index, role, budget),
                                {},
                            ).get("contender", set())
                        )
                        current = set(
                            selected.get(
                                (policy_id, dataset_id, current_index, role, budget),
                                {},
                            ).get("contender", set())
                        )
                        intersection_count = len(previous & current)
                        union_count = len(previous | current)
                        both_empty = not previous and not current
                        one_empty = bool(previous) != bool(current)
                        full_replacement = bool(previous) and bool(current) and intersection_count == 0
                        lane_rows.append(
                            {
                                "policy_id": policy_id,
                                "budget": budget,
                                "dataset_id": dataset_id,
                                "role": role,
                                "previous_checkpoint_index": previous_index,
                                "current_checkpoint_index": current_index,
                                "previous_selected_count": len(previous),
                                "current_selected_count": len(current),
                                "intersection_count": intersection_count,
                                "union_count": union_count,
                                "adjacent_jaccard": 1.0 if both_empty else intersection_count / union_count,
                                "both_empty": both_empty,
                                "one_empty": one_empty,
                                "full_replacement": full_replacement,
                            }
                        )
                    rows.extend(lane_rows)
                    jaccards = [row["adjacent_jaccard"] for row in lane_rows]
                    full_replacement_count = sum(row["full_replacement"] for row in lane_rows)
                    summaries.append(
                        {
                            "policy_id": policy_id,
                            "budget": budget,
                            "dataset_id": dataset_id,
                            "role": role,
                            "adjacent_pair_count": len(lane_rows),
                            "median_adjacent_jaccard": statistics.median(jaccards) if jaccards else None,
                            "full_replacement_count": full_replacement_count,
                            "full_replacement_rate": full_replacement_count / len(lane_rows) if lane_rows else 0.0,
                            "one_empty_transition_count": sum(row["one_empty"] for row in lane_rows),
                        }
                    )
    rows.sort(
        key=lambda row: (
            row["policy_id"],
            int(row["budget"]),
            row["dataset_id"],
            row["role"],
            int(row["previous_checkpoint_index"]),
            int(row["current_checkpoint_index"]),
        )
    )
    summaries.sort(
        key=lambda row: (
            row["policy_id"],
            int(row["budget"]),
            row["dataset_id"],
            row["role"],
        )
    )
    return rows, summaries


def _future_outcome(dataset: Any, candidate: Mapping[str, Any], checkpoint: Mapping[str, Any], state: str, policy_id: str, budget: int, source_kind: str) -> dict[str, Any]:
    prefix = int(checkpoint["checkpoint_position"])
    horizon_rows: dict[int, list[int]] = {}
    for horizon_hours in HORIZON_HOURS:
        bars = _horizon_bar_count(dataset, horizon_hours)
        horizon_rows[horizon_hours] = list(range(prefix, min(len(dataset.timestamps), prefix + bars)))
    outcomes: dict[str, Any] = {}
    for horizon_hours, positions in horizon_rows.items():
        horizon_bar_count = _horizon_bar_count(dataset, horizon_hours)
        exact_positions: list[int] = []
        zone_positions: list[int] = []
        breach_positions: list[int] = []
        consecutive = 0
        for position in positions:
            line = _line_price(dataset, candidate, position)
            atr = dataset.atr[position]
            if atr is None or float(atr) <= 0:
                consecutive = 0
                continue
            exact = float(dataset.lows[position]) <= line <= float(dataset.highs[position])
            zone = float(dataset.lows[position]) <= line + 0.35 * float(atr) and float(dataset.highs[position]) >= line - 0.35 * float(atr)
            if exact:
                exact_positions.append(position)
            if zone:
                zone_positions.append(position)
            if candidate["role"] == "support":
                breached = float(dataset.closes[position]) < line - 0.50 * float(atr)
            else:
                breached = float(dataset.closes[position]) > line + 0.50 * float(atr)
            consecutive = consecutive + 1 if breached else 0
            if consecutive >= 2:
                breach_positions.append(position)
                break
        first_zone = zone_positions[0] if zone_positions else None
        first_exact = exact_positions[0] if exact_positions else None
        first_breach = breach_positions[0] if breach_positions else None
        reaction = False
        if first_zone is not None:
            contact_line = _line_price(dataset, candidate, first_zone)
            contact_atr = dataset.atr[first_zone]
            if contact_atr is not None and float(contact_atr) > 0:
                for position in positions:
                    if position <= first_zone or (first_breach is not None and position >= first_breach):
                        continue
                    if candidate["role"] == "support":
                        reaction = float(dataset.highs[position]) - contact_line >= float(contact_atr)
                    else:
                        reaction = contact_line - float(dataset.lows[position]) >= float(contact_atr)
                    if reaction:
                        break
        future_zone = first_zone is not None
        future_exact = first_exact is not None
        survived = future_zone and (first_breach is None or first_breach > first_zone)
        current_zone = state == "CONTACTING"
        outcomes[str(horizon_hours)] = {
            "horizon_hours": horizon_hours,
            "horizon_bar_count": horizon_bar_count,
            "future_start_position": prefix,
            "future_end_exclusive_position": prefix + horizon_bar_count,
            "evaluable": len(positions) == horizon_bar_count,
            "exact_contact": future_exact,
            "zone_contact": current_zone or future_zone,
            "current_or_future_zone_contact": current_zone or future_zone,
            "future_exact_contact": future_exact,
            "future_zone_contact": future_zone,
            "first_exact_contact_offset_bars": first_exact - prefix if first_exact is not None else None,
            "first_zone_contact_offset_bars": first_zone - prefix if first_zone is not None else None,
            "sustained_breach": first_breach is not None,
            "first_sustained_breach_offset_bars": first_breach - prefix if first_breach is not None else None,
            "zone_contact_and_survival": survived,
            "post_contact_reaction": reaction,
        }
    payload = {
        "dataset_id": dataset.dataset_id,
        "checkpoint_index": checkpoint["checkpoint_index"],
        "checkpoint_position": prefix,
        "role": candidate["role"],
        "state": state,
        "candidate_id": candidate["candidate_id"],
        "candidate_structure_id": candidate["candidate_structure_id"],
        "first_anchor_id": candidate["first_anchor_id"],
        "second_anchor_id": candidate["second_anchor_id"],
        "source_positions": list(candidate["source_positions"]),
        "confirmation_positions": list(candidate["confirmation_positions"]),
        "policy_id": policy_id,
        "budget": budget,
        "source_kind": source_kind,
        "outcomes": outcomes,
    }
    return {
        **payload,
        "outcome_id": _identity(OUTCOME_NAMESPACE, payload),
    }


def _cell_metric(outcome_rows: Sequence[Mapping[str, Any]], horizon_hours: int) -> dict[str, Any]:
    rows = [row for row in outcome_rows if row["outcomes"][str(horizon_hours)]["evaluable"]]
    if not rows:
        return {"evaluable_count": 0, "selected_count": 0, "zone_contact_precision": None, "future_exact_contact_precision": None, "zone_contact_and_survival_rate": None, "sustained_breach_rate": None, "post_contact_reaction_rate": None, "cell_hit": False, "cell_hit_rate": None, "median_time_to_contact": None}
    outcome = [row["outcomes"][str(horizon_hours)] for row in rows]
    times = [item["first_zone_contact_offset_bars"] for item in outcome if item["first_zone_contact_offset_bars"] is not None]
    return {
        "evaluable_count": len(rows),
        "selected_count": len(rows),
        "zone_contact_precision": sum(item["current_or_future_zone_contact"] for item in outcome) / len(outcome),
        "future_exact_contact_precision": sum(item["future_exact_contact"] for item in outcome) / len(outcome),
        "zone_contact_and_survival_rate": sum(item["zone_contact_and_survival"] for item in outcome) / len(outcome),
        "sustained_breach_rate": sum(item["sustained_breach"] for item in outcome) / len(outcome),
        "post_contact_reaction_rate": sum(item["post_contact_reaction"] for item in outcome) / len(outcome),
        "cell_hit": any(item["current_or_future_zone_contact"] for item in outcome),
        "cell_hit_rate": 1.0 if any(item["current_or_future_zone_contact"] for item in outcome) else 0.0,
        "median_time_to_contact": statistics.median(times) if times else None,
    }


def _paired_bootstrap(cells: Sequence[Mapping[str, Any]], metric: str, seed_payload: Mapping[str, Any]) -> dict[str, Any]:
    if not cells:
        return {"point_delta": None, "lower": None, "upper": None, "valid_replicates": 0, "invalid_replicates": BOOTSTRAP_REPLICATES}
    seed = int(hashlib.sha256(_canonical_bytes(seed_payload)).hexdigest()[:16], 16)
    rng = random.Random(seed)
    deltas = [float(cell["contender"][metric]) - float(cell["control"][metric]) for cell in cells]
    point = statistics.mean(deltas)
    samples: list[float] = []
    invalid = 0
    for _ in range(BOOTSTRAP_REPLICATES):
        try:
            sample = [deltas[rng.randrange(len(deltas))] for _ in deltas]
            value = statistics.mean(sample)
            if not math.isfinite(value):
                raise ValueError("non-finite bootstrap result")
            samples.append(value)
        except (IndexError, ValueError, statistics.StatisticsError):
            invalid += 1
    lower = _percentile(samples, (1 - BOOTSTRAP_CONFIDENCE) / 2)
    upper = _percentile(samples, 1 - (1 - BOOTSTRAP_CONFIDENCE) / 2)
    return {
        "point_delta": point,
        "lower": lower,
        "upper": upper,
        "valid_replicates": len(samples),
        "invalid_replicates": invalid,
        "seed": seed,
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


COMPARISON_METRICS = (
    "zone_contact_precision",
    "future_exact_contact_precision",
    "zone_contact_and_survival_rate",
    "sustained_breach_rate",
    "cell_hit_rate",
    "post_contact_reaction_rate",
)


def _aggregate_horizon(metric_cells: Sequence[Mapping[str, Any]], horizon_hours: int) -> dict[str, Any]:
    valid = [
        cell[str(horizon_hours)]
        for cell in metric_cells
        if int(cell[str(horizon_hours)]["evaluable_count"]) > 0
    ]
    times = [
        float(item["median_time_to_contact"])
        for item in valid
        if item["median_time_to_contact"] is not None
    ]
    return {
        "evaluable_cell_count": len(valid),
        "evaluable_observation_count": sum(int(item["evaluable_count"]) for item in valid),
        "zone_contact_precision": statistics.mean(item["zone_contact_precision"] for item in valid) if valid else None,
        "future_exact_contact_precision": statistics.mean(item["future_exact_contact_precision"] for item in valid) if valid else None,
        "zone_contact_and_survival_rate": statistics.mean(item["zone_contact_and_survival_rate"] for item in valid) if valid else None,
        "sustained_breach_rate": statistics.mean(item["sustained_breach_rate"] for item in valid) if valid else None,
        "post_contact_reaction_rate": statistics.mean(item["post_contact_reaction_rate"] for item in valid) if valid else None,
        "cell_hit_rate": statistics.mean(bool(item["cell_hit"]) for item in valid) if valid else None,
        "median_time_to_contact": statistics.median(times) if times else None,
    }


def _validated_outcome_state(row: Mapping[str, Any]) -> str:
    state = row.get("state")
    if state not in ALL_STATES:
        raise StudyError("outcome state missing or invalid")
    return str(state)


def _outcome_state_audit(
    outcomes: Sequence[Mapping[str, Any]],
    features: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    feature_states = {
        (
            row.get("policy_id"),
            row.get("dataset_id"),
            int(row.get("checkpoint_index", -1)),
            row.get("role"),
            row.get("candidate_structure_id"),
        ): row.get("state")
        for row in features
    }
    missing = 0
    invalid = 0
    mismatch = 0
    for row in outcomes:
        state = row.get("state")
        if state is None:
            missing += 1
            continue
        if state not in ALL_STATES:
            invalid += 1
            continue
        identity = (
            row.get("policy_id"),
            row.get("dataset_id"),
            int(row.get("checkpoint_index", -1)),
            row.get("role"),
            row.get("candidate_structure_id"),
        )
        if feature_states.get(identity) != state:
            mismatch += 1
    return {
        "missing_outcome_state_count": missing,
        "invalid_outcome_state_count": invalid,
        "outcome_state_feature_mismatch_count": mismatch,
    }


def _state_stratified_utility(
    outcomes: Sequence[Mapping[str, Any]],
    schedules: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    by_cell_state: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in outcomes:
        state = _validated_outcome_state(row)
        if row["source_kind"] != "contender":
            continue
        by_cell_state[
            (
                row["policy_id"],
                int(row["budget"]),
                row["dataset_id"],
                int(row["checkpoint_index"]),
                row["role"],
                state,
            )
        ].append(row)

    result: list[dict[str, Any]] = []
    for policy in POLICIES:
        policy_id = policy["policy_id"]
        for budget in BUDGETS:
            for dataset_id in DATASETS:
                checkpoint_indices = [
                    int(row["checkpoint_index"])
                    for row in schedules[dataset_id]
                ]
                for role in ROLES:
                    for state in ACTIONABLE_STATES:
                        state_rows = [
                            by_cell_state.get(
                                (policy_id, budget, dataset_id, checkpoint_index, role, state),
                                [],
                            )
                            for checkpoint_index in checkpoint_indices
                        ]
                        nonempty_cell_count = sum(bool(rows) for rows in state_rows)
                        selected_observation_count = sum(len(rows) for rows in state_rows)
                        metric_cells = [
                            {
                                str(horizon_hours): _cell_metric(rows, horizon_hours)
                                for horizon_hours in HORIZON_HOURS
                            }
                            for rows in state_rows
                            if rows
                        ]
                        for horizon_hours in HORIZON_HOURS:
                            aggregate = _aggregate_horizon(metric_cells, horizon_hours)
                            result.append(
                                {
                                    "policy_id": policy_id,
                                    "budget": budget,
                                    "dataset_id": dataset_id,
                                    "role": role,
                                    "state": state,
                                    "horizon_hours": horizon_hours,
                                    "selected_observation_count": selected_observation_count,
                                    "evaluable_observation_count": sum(
                                        int(cell[str(horizon_hours)]["evaluable_count"])
                                        for cell in metric_cells
                                    ),
                                    "nonempty_checkpoint_cell_count": nonempty_cell_count,
                                    "current_or_future_zone_contact_precision": aggregate["zone_contact_precision"],
                                    "future_exact_contact_precision": aggregate["future_exact_contact_precision"],
                                    "zone_contact_and_survival_rate": aggregate["zone_contact_and_survival_rate"],
                                    "sustained_breach_rate": aggregate["sustained_breach_rate"],
                                    "post_contact_reaction_rate": aggregate["post_contact_reaction_rate"],
                                    "cell_hit_rate": aggregate["cell_hit_rate"],
                                    "median_time_to_contact": aggregate["median_time_to_contact"],
                                }
                            )
    return result


def _integrity_audit(
    *,
    active_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    expected_active_structure_rows: int,
    features: Sequence[Mapping[str, Any]],
    selected: Mapping[tuple[Any, ...], dict[str, set[str]]],
    membership: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
    schedules: Mapping[str, Sequence[Mapping[str, Any]]],
    expected_feature_rows: int | None = None,
) -> dict[str, Any]:
    actual_active_structure_rows = sum(len(rows) for rows in active_by_dataset.values())
    expected_feature_rows = (
        expected_active_structure_rows * len(POLICIES)
        if expected_feature_rows is None
        else expected_feature_rows
    )
    feature_ids = [str(row["feature_row_id"]) for row in features]
    feature_id_counts = Counter(feature_ids)
    duplicate_feature_row_ids = sum(
        count - 1 for count in feature_id_counts.values() if count > 1
    )

    feature_by_identity = {
        (
            row["policy_id"],
            row["dataset_id"],
            int(row["checkpoint_index"]),
            row["role"],
            row["candidate_structure_id"],
        ): row
        for row in features
    }
    feature_roles: dict[tuple[Any, ...], set[str]] = defaultdict(set)
    for row in features:
        feature_roles[
            (
                row["policy_id"],
                row["dataset_id"],
                int(row["checkpoint_index"]),
                row["candidate_structure_id"],
            )
        ].add(str(row["role"]))

    selected_membership_keys = [
        (
            row["policy_id"],
            int(row["budget"]),
            row["dataset_id"],
            int(row["checkpoint_index"]),
            row["role"],
            row["candidate_structure_id"],
        )
        for row in membership
        if row.get("selection_status") == "SELECTED"
    ]
    membership_counts = Counter(selected_membership_keys)
    duplicate_selected_memberships = sum(
        count - 1 for count in membership_counts.values() if count > 1
    )

    role_violation_count = 0
    second_anchor_suppression_violations = 0
    budget_violation_count = 0
    matched_control_count_failures = 0
    expected_outcome_keys: set[tuple[Any, ...]] = set()
    for key, source_sets in selected.items():
        policy_id, dataset_id, checkpoint_index, role, budget = key
        contender_count = len(source_sets.get("contender", set()))
        for source_kind, structure_ids in source_sets.items():
            expected_outcome_keys.update(
                (
                    policy_id,
                    int(budget),
                    dataset_id,
                    int(checkpoint_index),
                    role,
                    source_kind,
                    structure_id,
                )
                for structure_id in structure_ids
            )
            if len(structure_ids) > int(budget):
                budget_violation_count += 1
            anchors: list[str] = []
            for structure_id in structure_ids:
                feature = feature_by_identity.get(
                    (policy_id, dataset_id, int(checkpoint_index), role, structure_id)
                )
                if feature is None:
                    if role not in feature_roles.get(
                        (policy_id, dataset_id, int(checkpoint_index), structure_id),
                        set(),
                    ):
                        role_violation_count += 1
                    continue
                anchors.append(str(feature["second_anchor_id"]))
            second_anchor_suppression_violations += len(anchors) - len(set(anchors))
        if (
            len(source_sets.get("nearest_distance_control", set())) != contender_count
            or len(source_sets.get("hash_order_control", set())) != contender_count
        ):
            matched_control_count_failures += 1

    outcome_keys = {
        (
            row.get("policy_id"),
            int(row.get("budget", -1)),
            row.get("dataset_id"),
            int(row.get("checkpoint_index", -1)),
            row.get("role"),
            row.get("source_kind"),
            row.get("candidate_structure_id"),
        )
        for row in outcomes
    }
    outcome_id_counts = Counter(str(row.get("outcome_id")) for row in outcomes)
    duplicate_outcome_ids = sum(
        count - 1 for count in outcome_id_counts.values() if count > 1
    )
    missing_selected_outcomes = len(expected_outcome_keys - outcome_keys)
    unexpected_outcomes = len(outcome_keys - expected_outcome_keys)

    feature_history_future_leakage_rows = 0
    for row in features:
        checkpoint_position = int(row["checkpoint_position"])
        feature_payload = row.get("features", {})
        historical_positions = feature_payload.get("historical_positions", [])
        if (
            any(int(position) >= checkpoint_position for position in historical_positions)
            or int(feature_payload.get("history_end_position", checkpoint_position - 1)) >= checkpoint_position
        ):
            feature_history_future_leakage_rows += 1

    outcome_future_boundary_violations = 0
    for row in outcomes:
        checkpoint_position = int(row.get("checkpoint_position", -1))
        for horizon_hours in HORIZON_HOURS:
            item = row.get("outcomes", {}).get(str(horizon_hours))
            if not isinstance(item, Mapping):
                outcome_future_boundary_violations += 1
                continue
            horizon_bar_count = item.get("horizon_bar_count")
            if (
                item.get("horizon_hours") != horizon_hours
                or item.get("future_start_position") != checkpoint_position
                or not isinstance(horizon_bar_count, int)
                or item.get("future_end_exclusive_position") != checkpoint_position + horizon_bar_count
                or checkpoint_position < 0
            ):
                outcome_future_boundary_violations += 1

    outcome_state_audit = _outcome_state_audit(outcomes, features)
    outcome_state_failure_count = sum(outcome_state_audit.values())

    active_structure_reconciliation_failures = int(
        actual_active_structure_rows != expected_active_structure_rows
    )
    feature_row_reconciliation_failures = int(
        len(features) != expected_feature_rows
    )
    expected_outcome_rows = len(expected_outcome_keys)
    actual_outcome_rows = len(outcomes)
    outcome_row_reconciliation_failures = int(actual_outcome_rows != expected_outcome_rows)
    unresolved_evidence_count = (
        duplicate_outcome_ids
        + missing_selected_outcomes
        + unexpected_outcomes
        + feature_history_future_leakage_rows
        + outcome_future_boundary_violations
        + outcome_state_failure_count
    )
    reconciliation_count = (
        active_structure_reconciliation_failures
        + feature_row_reconciliation_failures
        + duplicate_feature_row_ids
        + duplicate_selected_memberships
        + role_violation_count
        + second_anchor_suppression_violations
        + budget_violation_count
        + matched_control_count_failures
        + outcome_row_reconciliation_failures
        + outcome_state_failure_count
    )
    audit = {
        "expected_active_structure_rows": expected_active_structure_rows,
        "actual_active_structure_rows": actual_active_structure_rows,
        "active_structure_reconciliation_failures": active_structure_reconciliation_failures,
        "expected_feature_rows": expected_feature_rows,
        "actual_feature_rows": len(features),
        "feature_row_reconciliation_failures": feature_row_reconciliation_failures,
        "duplicate_feature_row_ids": duplicate_feature_row_ids,
        "duplicate_selected_memberships": duplicate_selected_memberships,
        "role_violation_count": role_violation_count,
        "second_anchor_suppression_violations": second_anchor_suppression_violations,
        "budget_violation_count": budget_violation_count,
        "matched_control_count_failures": matched_control_count_failures,
        "expected_outcome_rows": expected_outcome_rows,
        "actual_outcome_rows": actual_outcome_rows,
        "outcome_row_reconciliation_failures": outcome_row_reconciliation_failures,
        "duplicate_outcome_ids": duplicate_outcome_ids,
        "missing_selected_outcomes": missing_selected_outcomes,
        "unexpected_outcomes": unexpected_outcomes,
        "feature_history_future_leakage_rows": feature_history_future_leakage_rows,
        "outcome_future_boundary_violations": outcome_future_boundary_violations,
        **outcome_state_audit,
        "unresolved_evidence_count": unresolved_evidence_count,
        "reconciliation_count": reconciliation_count,
    }
    failure_fields = (
        "active_structure_reconciliation_failures",
        "feature_row_reconciliation_failures",
        "duplicate_feature_row_ids",
        "duplicate_selected_memberships",
        "role_violation_count",
        "second_anchor_suppression_violations",
        "budget_violation_count",
        "matched_control_count_failures",
        "outcome_row_reconciliation_failures",
        "duplicate_outcome_ids",
        "missing_selected_outcomes",
        "unexpected_outcomes",
        "feature_history_future_leakage_rows",
        "outcome_future_boundary_violations",
        "missing_outcome_state_count",
        "invalid_outcome_state_count",
        "outcome_state_feature_mismatch_count",
    )
    audit["integrity_failure_count"] = sum(int(audit[field]) for field in failure_fields)
    audit["integrity"] = audit["integrity_failure_count"] == 0
    return audit


def _aggregate_selection_cells(
    metric_cells: Sequence[Mapping[str, Any]],
    *,
    policy_id: str,
    budget: int,
    dataset_id: str,
    role: str,
    source_kind: str,
    eligible_counts: Sequence[int],
    state_distribution: Mapping[str, int],
) -> dict[str, Any]:
    selected_counts = [int(cell["selected_count"]) for cell in metric_cells]
    cell_count = len(metric_cells)
    return {
        "policy_id": policy_id,
        "budget": budget,
        "dataset_id": dataset_id,
        "role": role,
        "source_kind": source_kind,
        "checkpoint_count": cell_count,
        "selected_count_total": sum(selected_counts),
        "median_selected_count": statistics.median(selected_counts) if selected_counts else 0,
        "nonempty_cell_coverage": sum(count > 0 for count in selected_counts) / cell_count if cell_count else 0.0,
        "state_distribution": dict(sorted(state_distribution.items())) if source_kind == "contender" else {},
        "actionable_eligible_median": statistics.median(eligible_counts) if eligible_counts else 0,
        "actionable_eligible_p90": _percentile(eligible_counts, 0.90) or 0.0,
        "periods": {
            "early": {
                "checkpoint_count": sum(int(cell["checkpoint_index"]) <= 13 for cell in metric_cells),
                "selected_count_total": sum(int(cell["selected_count"]) for cell in metric_cells if int(cell["checkpoint_index"]) <= 13),
            },
            "late": {
                "checkpoint_count": sum(int(cell["checkpoint_index"]) >= 14 for cell in metric_cells),
                "selected_count_total": sum(int(cell["selected_count"]) for cell in metric_cells if int(cell["checkpoint_index"]) >= 14),
            },
        },
        **{f"{horizon_hours}h": _aggregate_horizon(metric_cells, horizon_hours) for horizon_hours in HORIZON_HOURS},
    }


def _paired_comparison(
    pairs: Sequence[Mapping[str, Any]],
    *,
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    periods = {
        "pooled": lambda _: True,
        "early": lambda cell: int(cell["checkpoint_index"]) <= 13,
        "late": lambda cell: int(cell["checkpoint_index"]) >= 14,
    }
    period_payload: dict[str, Any] = {}
    for period, include in periods.items():
        period_pairs = [pair for pair in pairs if include(pair)]
        metrics: dict[str, Any] = {}
        for metric_name in COMPARISON_METRICS:
            paired_cells = [
                {
                    "contender": {metric_name: pair["contender"][metric_name]},
                    "control": {metric_name: pair["control"][metric_name]},
                }
                for pair in period_pairs
                if pair["contender"][metric_name] is not None
                and pair["control"][metric_name] is not None
            ]
            metrics[metric_name] = _paired_bootstrap(
                paired_cells,
                metric_name,
                {**identity, "period": period, "metric": metric_name},
            )
        period_payload[period] = {
            "matched_cell_count": len(period_pairs),
            "paired_cell_count": max(
                (
                    sum(
                        pair["contender"][metric_name] is not None
                        and pair["control"][metric_name] is not None
                        for pair in period_pairs
                    )
                    for metric_name in COMPARISON_METRICS
                ),
                default=0,
            ),
            "metrics": metrics,
        }
    pooled_metrics = period_payload["pooled"]["metrics"]
    return {
        **identity,
        "matched_cell_count": period_payload["pooled"]["matched_cell_count"],
        "metrics": pooled_metrics,
        "periods": period_payload,
    }


def _selection_metrics(
    selected: Mapping[tuple[Any, ...], dict[str, set[str]]],
    membership: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
    features: Sequence[Mapping[str, Any]],
    control_selections: Sequence[Mapping[str, Any]] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    feature_by_key = {
        (
            row["policy_id"],
            row["dataset_id"],
            int(row["checkpoint_index"]),
            row["role"],
            row["candidate_structure_id"],
        ): row
        for row in features
    }
    features_by_cell: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in features:
        features_by_cell[
            (row["policy_id"], row["dataset_id"], int(row["checkpoint_index"]), row["role"])
        ].append(row)
    outcome_by_key: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in outcomes:
        outcome_by_key[
            (
                row["policy_id"],
                int(row["budget"]),
                row["dataset_id"],
                int(row["checkpoint_index"]),
                row["role"],
                row["source_kind"],
            )
        ].append(row)
    control_rows_by_cell: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in control_selections:
        control_rows_by_cell[
            (
                row["policy_id"],
                int(row["budget"]),
                row["dataset_id"],
                int(row["checkpoint_index"]),
                row["role"],
                row["source_kind"],
            )
        ].append(row)

    policy_rows: list[dict[str, Any]] = []
    control_rows: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    pooled_comparisons: list[dict[str, Any]] = []
    dataset_comparisons: list[dict[str, Any]] = []

    for policy in POLICIES:
        policy_id = policy["policy_id"]
        for budget in BUDGETS:
            lane_cells: dict[tuple[str, str], list[tuple[Any, ...]]] = defaultdict(list)
            for key in selected:
                if key[0] == policy_id and int(key[4]) == budget:
                    lane_cells[(key[1], key[3])].append(key)
            all_pairs: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
            pairs_by_dataset: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
            for (dataset_id, role), cells in sorted(lane_cells.items()):
                cells.sort(key=lambda key: int(key[2]))
                eligible_counts = [
                    sum(bool(row["actionable"]) for row in features_by_cell[(policy_id, dataset_id, int(cell[2]), role)])
                    for cell in cells
                ]
                selected_state_counts: Counter[str] = Counter()
                contender_metric_cells: list[dict[str, Any]] = []
                source_metric_cells: dict[str, list[dict[str, Any]]] = defaultdict(list)
                for cell, eligible_count in zip(cells, eligible_counts):
                    for structure in selected[cell]["contender"]:
                        selected_state_counts[feature_by_key[(policy_id, dataset_id, int(cell[2]), role, structure)]["state"]] += 1
                    for source_kind in ("contender", "nearest_distance_control", "hash_order_control"):
                        selected_outcomes = outcome_by_key.get(
                            (policy_id, budget, dataset_id, int(cell[2]), role, source_kind),
                            [],
                        )
                        source_metric_cells[source_kind].append(
                            {
                                "checkpoint_index": int(cell[2]),
                                "selected_count": len(selected[cell][source_kind]),
                                **{
                                    str(horizon_hours): _cell_metric(selected_outcomes, horizon_hours)
                                    for horizon_hours in HORIZON_HOURS
                                },
                                "eligible_count": eligible_count,
                            }
                        )
                    contender_metric_cells = source_metric_cells["contender"]

                policy_rows.append(
                    _aggregate_selection_cells(
                        contender_metric_cells,
                        policy_id=policy_id,
                        budget=budget,
                        dataset_id=dataset_id,
                        role=role,
                        source_kind="contender",
                        eligible_counts=eligible_counts,
                        state_distribution=selected_state_counts,
                    )
                )
                for source_kind in ("nearest_distance_control", "hash_order_control"):
                    control_rows.append(
                        _aggregate_selection_cells(
                            source_metric_cells[source_kind],
                            policy_id=policy_id,
                            budget=budget,
                            dataset_id=dataset_id,
                            role=role,
                            source_kind=source_kind,
                            eligible_counts=eligible_counts,
                            state_distribution={},
                        )
                    )
                for control_kind in ("nearest_distance_control", "hash_order_control"):
                    for horizon_hours in HORIZON_HOURS:
                        pairs: list[dict[str, Any]] = []
                        for index in range(len(cells)):
                            contender = source_metric_cells["contender"][index][str(horizon_hours)]
                            control = source_metric_cells[control_kind][index][str(horizon_hours)]
                            pair = {
                                "checkpoint_index": int(cells[index][2]),
                                **{
                                    metric: {
                                        "contender": contender[metric],
                                        "control": control[metric],
                                    }
                                    for metric in COMPARISON_METRICS
                                },
                            }
                            pairs.append({
                                "checkpoint_index": pair["checkpoint_index"],
                                "contender": {metric: pair[metric]["contender"] for metric in COMPARISON_METRICS},
                                "control": {metric: pair[metric]["control"] for metric in COMPARISON_METRICS},
                            })
                        identity = {
                            "policy_id": policy_id,
                            "budget": budget,
                            "dataset_id": dataset_id,
                            "role": role,
                            "control_kind": control_kind,
                            "horizon_hours": horizon_hours,
                        }
                        record = _paired_comparison(pairs, identity=identity)
                        comparisons.append(record)
                        all_pairs[(control_kind, horizon_hours)].extend(pairs)
                        pairs_by_dataset[(dataset_id, control_kind, horizon_hours)].extend(pairs)

            for control_kind in ("nearest_distance_control", "hash_order_control"):
                for horizon_hours in HORIZON_HOURS:
                    pooled_comparisons.append(
                        _paired_comparison(
                            all_pairs[(control_kind, horizon_hours)],
                            identity={
                                "policy_id": policy_id,
                                "budget": budget,
                                "dataset_id": "__pooled__",
                                "role": "__all__",
                                "control_kind": control_kind,
                                "horizon_hours": horizon_hours,
                            },
                        )
                    )
                    for dataset_id in DATASETS:
                        dataset_comparisons.append(
                            _paired_comparison(
                                pairs_by_dataset[(dataset_id, control_kind, horizon_hours)],
                                identity={
                                    "policy_id": policy_id,
                                    "budget": budget,
                                    "dataset_id": dataset_id,
                                    "role": "__all__",
                                    "control_kind": control_kind,
                                    "horizon_hours": horizon_hours,
                                },
                            )
                        )

            if budget != BUDGETS[0]:
                continue
            for source_kind in ("current_focus", "all_valid"):
                for dataset_id in DATASETS:
                    for role in ROLES:
                        for control_budget in (0,):
                            rows_by_cell: list[dict[str, Any]] = []
                            eligible_counts: list[int] = []
                            for checkpoint_index in range(1, 28):
                                selected_rows = control_rows_by_cell.get(
                                    (policy_id, control_budget, dataset_id, checkpoint_index, role, source_kind),
                                    [],
                                )
                                cell_features = features_by_cell[(policy_id, dataset_id, checkpoint_index, role)]
                                rows_by_cell.append(
                                    {
                                        "checkpoint_index": checkpoint_index,
                                        "selected_count": len(selected_rows),
                                        **{
                                            str(horizon_hours): _cell_metric([], horizon_hours)
                                            for horizon_hours in HORIZON_HOURS
                                        },
                                    }
                                )
                                eligible_counts.append(sum(bool(row["actionable"]) for row in cell_features))
                            control_rows.append(
                                _aggregate_selection_cells(
                                    rows_by_cell,
                                    policy_id=policy_id,
                                    budget=control_budget,
                                    dataset_id=dataset_id,
                                    role=role,
                                    source_kind=source_kind,
                                    eligible_counts=eligible_counts,
                                    state_distribution={},
                                )
                            )

    policy_rows.sort(key=lambda row: (row["policy_id"], int(row["budget"]), row["dataset_id"], row["role"], row["source_kind"]))
    control_rows.sort(key=lambda row: (row["policy_id"], int(row["budget"]), row["dataset_id"], row["role"], row["source_kind"]))
    comparisons.sort(key=lambda row: (row["policy_id"], int(row["budget"]), row["dataset_id"], row["role"], row["control_kind"], int(row["horizon_hours"])))
    pooled_comparisons.sort(key=lambda row: (row["policy_id"], int(row["budget"]), row["control_kind"], int(row["horizon_hours"])))
    dataset_comparisons.sort(key=lambda row: (row["policy_id"], int(row["budget"]), row["dataset_id"], row["control_kind"], int(row["horizon_hours"])))
    return policy_rows, control_rows, {
        "comparisons": comparisons,
        "pooled_comparisons": pooled_comparisons,
        "dataset_comparisons": dataset_comparisons,
        "membership_count": len(membership),
    }


def _contract(schedule: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    payload = {
        "schema_version": f"{STUDY_SCHEMA}_contract_v1",
        "h1_commit": H1_COMMIT,
        "h1_decision_id": H1_DECISION_ID,
        "h1_manifest_id": H1_MANIFEST_ID,
        "h1_inventory_sha256": H1_INVENTORY_SHA256,
        "source_decision_id": SOURCE_DECISION_ID,
        "source_manifest_id": SOURCE_MANIFEST_ID,
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "underlying_source_inventory_sha256": UNDERLYING_SOURCE_INVENTORY_SHA256,
        "validation_datasets": list(DATASETS),
        "holdout_datasets": list(HOLDOUT_DATASETS),
        "checkpoint_policy": {"counts": {dataset_id: len(rows) for dataset_id, rows in sorted(schedule.items())}, "prefix": "bar_open < checkpoint", "availability": "candidate_available_at <= checkpoint"},
        "feature_policy": {"distance_support": "max(0, candle_low - line_price) / ATR", "distance_resistance": "max(0, line_price - candle_high) / ATR", "close_support": "(close - line_price) / ATR", "close_resistance": "(line_price - close) / ATR", "atr": "causal Wilder ATR-14"},
        "policies": [dict(policy) for policy in POLICIES],
        "budgets": list(BUDGETS),
        "states": ["CONTACTING", "NEAR", "APPROACHING", "DORMANT"],
        "controls": ["nearest_distance_control", "hash_order_control", "current_focus", "all_valid"],
        "outcome_policy": {"horizons_hours": list(HORIZON_HOURS), "zone_tolerance_atr": 0.35, "sustained_breach_closes": 2, "sustained_breach_atr": 0.50, "reaction_atr": 1.0, "contact_bar_is_reaction": False},
        "bootstrap": {"replicates": BOOTSTRAP_REPLICATES, "confidence": BOOTSTRAP_CONFIDENCE, "sampling_unit": "checkpoint-role cell", "minimum_valid": BOOTSTRAP_MIN_VALID},
        "gates": {"coverage_pooled": 0.80, "coverage_worst_lane": 0.65, "median_selected_min": 2, "median_actionable_max": 30, "worst_actionable_p90_max": 60, "near_or_approaching_share": 0.20, "zone_precision_delta_48h": 0.02, "bootstrap_lower_gt": 0.0, "worst_dataset_delta_48h": -0.02, "cell_hit_delta_48h": 0.0, "survival_delta_96h": 0.0, "breach_increase_96h": 0.02, "exact_precision_delta": 0.0, "late_zone_delta": 0.0, "worst_late_delta": -0.03},
        "execution": {"provider_execution_count": 0, "network_request_count": 0, "legacy_execution_count": 0, "holdout_access": False, "temporal_access": False},
        "interpretation": "actionability_shortlist_not_quality_ranking",
    }
    return {**payload, "contract_id": _identity(CONTRACT_NAMESPACE, payload)}


def _source_binding(h1_binding: Mapping[str, Any], before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    if before != after:
        raise StudyError("source changed during study")
    payload = {
        "schema_version": f"{STUDY_SCHEMA}_source_binding_v1",
        "h1_commit": H1_COMMIT,
        "h1_source_binding_id": h1_binding["source_binding_id"],
        "h1_decision_id": H1_DECISION_ID,
        "h1_manifest_id": H1_MANIFEST_ID,
        "h1_inventory_sha256": H1_INVENTORY_SHA256,
        "source_decision_id": SOURCE_DECISION_ID,
        "source_manifest_id": SOURCE_MANIFEST_ID,
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "underlying_source_inventory_sha256": UNDERLYING_SOURCE_INVENTORY_SHA256,
        "source_before": before,
        "source_after": after,
        "source_immutability_verified": True,
        "validation_datasets": list(DATASETS),
        "holdout_datasets": list(HOLDOUT_DATASETS),
    }
    return {**payload, "source_binding_id": _identity(SOURCE_NAMESPACE, payload)}


def _validation_lock(contract: Mapping[str, Any], binding: Mapping[str, Any], status: str, *, phase: str) -> dict[str, Any]:
    payload = {"schema_version": f"{STUDY_SCHEMA}_validation_lock_v1", "contract_id": contract["contract_id"], "source_binding_id": binding["source_binding_id"], "status": status, "phase": phase, "validation_datasets": list(DATASETS), "holdout_access": False, "temporal_access": False, "provider_execution_count": 0, "network_request_count": 0}
    return {**payload, "validation_lock_id": _identity(LOCK_NAMESPACE, payload)}


def _checkpoint_population(active_by_dataset: Mapping[str, Sequence[Mapping[str, Any]]], schedules: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    rows = []
    for dataset_id in DATASETS:
        active = active_by_dataset[dataset_id]
        for checkpoint in schedules[dataset_id]:
            checkpoint_index = int(checkpoint["checkpoint_index"])
            subset = [row for row in active if int(row["checkpoint_index"]) == checkpoint_index]
            rows.append({"dataset_id": dataset_id, "checkpoint_index": checkpoint_index, "checkpoint": checkpoint["checkpoint"], "prefix_row_count": checkpoint["prefix_row_count"], "active_structure_count": len(subset), "support_count": sum(row["role"] == "support" for row in subset), "resistance_count": sum(row["role"] == "resistance" for row in subset)})
    return {"schema_version": f"{STUDY_SCHEMA}_checkpoint_population_v1", "rows": rows}


def _derive_evidence(
    pre_evaluation_callback: Any | None = None,
) -> dict[str, dict[str, Any]]:
    h1_manifest, h1_binding, schedule_payload, active_payload = _verify_h1_bundle()
    before = _validate_phase9_source()
    datasets = _load_phase9_datasets()
    active_by_dataset, schedules = _validate_active_population(active_payload, schedule_payload, datasets)
    contract = _contract(schedules)
    pre_evaluation_binding = _source_binding(h1_binding, before, before)
    if pre_evaluation_callback is not None:
        pre_evaluation_callback(contract, pre_evaluation_binding)
    features = _derive_features(active_by_dataset, schedules, datasets)
    membership, selected, control_selections, state_counts = _selection_records(features, active_by_dataset)
    dataset_map = {dataset.dataset_id: dataset for dataset in datasets}
    checkpoints = {(dataset_id, int(row["checkpoint_index"])): row for dataset_id, rows in schedules.items() for row in rows}
    feature_map = {(row["policy_id"], row["dataset_id"], int(row["checkpoint_index"]), row["role"], row["candidate_structure_id"]): row for row in features}
    outcome_rows: list[dict[str, Any]] = []
    # Attach candidate mappings to feature rows after feature IDs are stable.
    candidate_by_key = {(dataset_id, int(row["checkpoint_index"]), row["role"], row["candidate_structure_id"]): row["candidate"] for dataset_id, rows in active_by_dataset.items() for row in rows}
    for row in features:
        row["candidate"] = candidate_by_key[(row["dataset_id"], int(row["checkpoint_index"]), row["role"], row["candidate_structure_id"])]
    # Rebuild outcomes with exact checkpoint-local candidate binding.
    outcome_rows = []
    for key, sources in sorted(selected.items()):
        policy_id, dataset_id, checkpoint_index, role, budget = key
        checkpoint = checkpoints[(dataset_id, checkpoint_index)]
        for source_kind, structure_ids in sources.items():
            for structure_id in sorted(structure_ids):
                feature = feature_map[(policy_id, dataset_id, checkpoint_index, role, structure_id)]
                candidate = candidate_by_key[(dataset_id, checkpoint_index, role, structure_id)]
                outcome_rows.append(_future_outcome(dataset_map[dataset_id], candidate, checkpoint, feature["state"], policy_id, budget, source_kind))
    policy_rows, control_rows, comparison_payload = _selection_metrics(
        selected,
        membership,
        outcome_rows,
        features,
        control_selections,
    )
    shortlist_stability_rows, shortlist_stability_summary = _shortlist_stability(selected, schedules)
    integrity_audit = _integrity_audit(
        active_by_dataset=active_by_dataset,
        expected_active_structure_rows=len(active_payload["rows"]),
        features=features,
        selected=selected,
        membership=membership,
        outcomes=outcome_rows,
        schedules=schedules,
    )
    state_validation = _outcome_state_audit(outcome_rows, features)
    if any(state_validation.values()):
        state_stratified_utility = []
    else:
        state_stratified_utility = _state_stratified_utility(outcome_rows, schedules)
    source_after = _validate_phase9_source()
    final_binding = _source_binding(h1_binding, before, source_after)
    state_rows = [{key: row[key] for key in ("feature_row_id", "dataset_id", "checkpoint_index", "role", "candidate_structure_id", "second_anchor_id", "policy_id", "state", "actionable")} for row in features]
    policy_metrics = {
        "schema_version": f"{STUDY_SCHEMA}_policy_metrics_v1",
        "rows": policy_rows,
        "bootstrap_comparisons": comparison_payload["comparisons"],
        "pooled_bootstrap_comparisons": comparison_payload["pooled_comparisons"],
        "dataset_bootstrap_comparisons": comparison_payload["dataset_comparisons"],
        "state_counts": state_counts,
        "shortlist_stability_rows": shortlist_stability_rows,
        "shortlist_stability_summary": shortlist_stability_summary,
        "state_stratified_utility": state_stratified_utility,
        "integrity_audit": integrity_audit,
    }
    controls = {"schema_version": f"{STUDY_SCHEMA}_control_metrics_v1", "rows": control_rows, "selection_rows": control_selections}
    decision = _make_decision(policy_rows, comparison_payload, membership, integrity_audit)
    lock = _validation_lock(contract, final_binding, decision["status"], phase="COMPLETE")
    source_payload = {"schema_version": f"{STUDY_SCHEMA}_source_binding_v1", **final_binding}
    return {
        "study_contract.json": contract,
        "source_binding.json": source_payload,
        "checkpoint_population.json": _checkpoint_population(active_by_dataset, schedules),
        "actionability_feature_rows.json": {"schema_version": f"{STUDY_SCHEMA}_feature_rows_v1", "rows": [{key: value for key, value in row.items() if key != "candidate"} for row in features]},
        "state_membership.json": {"schema_version": f"{STUDY_SCHEMA}_state_membership_v1", "rows": state_rows},
        "shortlist_membership.json": {"schema_version": f"{STUDY_SCHEMA}_shortlist_membership_v1", "rows": membership},
        "future_interaction_outcomes.json": {"schema_version": f"{STUDY_SCHEMA}_future_interaction_outcomes_v1", "rows": sorted(outcome_rows, key=lambda row: (row["policy_id"], row["dataset_id"], row["checkpoint_index"], row["role"], row["budget"], row["source_kind"], row["candidate_structure_id"]))},
        "policy_metrics.json": policy_metrics,
        "control_metrics.json": controls,
        "validation_lock.json": lock,
        "decision.json": decision,
    }


def _make_decision(
    policy_rows: Sequence[Mapping[str, Any]],
    comparison_payload: Mapping[str, Any],
    membership: Sequence[Mapping[str, Any]],
    integrity_audit: Mapping[str, Any],
) -> dict[str, Any]:
    pooled_rows = comparison_payload["pooled_comparisons"]
    dataset_rows = comparison_payload["dataset_comparisons"]
    all_rows = comparison_payload["comparisons"]

    def find_row(
        rows: Sequence[Mapping[str, Any]],
        *,
        policy_id: str,
        budget: int,
        dataset_id: str,
        horizon_hours: int,
    ) -> Mapping[str, Any] | None:
        return next(
            (
                row
                for row in rows
                if row["policy_id"] == policy_id
                and int(row["budget"]) == budget
                and row["dataset_id"] == dataset_id
                and int(row["horizon_hours"]) == horizon_hours
                and row["control_kind"] == "nearest_distance_control"
            ),
            None,
        )

    def point(
        row: Mapping[str, Any] | None,
        metric_name: str,
        period: str = "pooled",
    ) -> float | None:
        if row is None:
            return None
        metric = row.get("periods", {}).get(period, {}).get("metrics", {}).get(metric_name)
        if not isinstance(metric, Mapping):
            metric = row.get("metrics", {}).get(metric_name)
        value = metric.get("point_delta") if isinstance(metric, Mapping) else None
        return float(value) if value is not None else None

    def lower(row: Mapping[str, Any] | None, metric_name: str) -> float | None:
        if row is None:
            return None
        metric = row.get("periods", {}).get("pooled", {}).get("metrics", {}).get(metric_name)
        if not isinstance(metric, Mapping):
            metric = row.get("metrics", {}).get(metric_name)
        value = metric.get("lower") if isinstance(metric, Mapping) else None
        return float(value) if value is not None else None

    gate_results: list[dict[str, Any]] = []
    integrity_ok = bool(integrity_audit["integrity"])
    for policy in POLICIES:
        policy_id = policy["policy_id"]
        for budget in BUDGETS:
            lane_rows = [
                row
                for row in policy_rows
                if row["policy_id"] == policy_id and int(row["budget"]) == budget
            ]
            coverage = statistics.mean(
                (float(row["nonempty_cell_coverage"]) for row in lane_rows),
            ) if lane_rows else 0.0
            worst_coverage = min(
                (float(row["nonempty_cell_coverage"]) for row in lane_rows),
                default=0.0,
            )
            median_selected = statistics.median(
                (float(row["median_selected_count"]) for row in lane_rows),
            ) if lane_rows else 0.0
            median_eligible = statistics.median(
                (float(row["actionable_eligible_median"]) for row in lane_rows),
            ) if lane_rows else math.inf
            worst_p90 = max(
                (float(row["actionable_eligible_p90"]) for row in lane_rows),
                default=math.inf,
            )
            selected_total = sum(int(row["selected_count_total"]) for row in lane_rows)
            near_approach = (
                sum(
                    sum(
                        int(value)
                        for key, value in row["state_distribution"].items()
                        if key in {"NEAR", "APPROACHING"}
                    )
                    for row in lane_rows
                ) / selected_total
                if selected_total
                else 0.0
            )

            pooled_zone = find_row(
                pooled_rows,
                policy_id=policy_id,
                budget=budget,
                dataset_id="__pooled__",
                horizon_hours=48,
            )
            pooled_survival = find_row(
                pooled_rows,
                policy_id=policy_id,
                budget=budget,
                dataset_id="__pooled__",
                horizon_hours=96,
            )
            dataset_zone = [
                find_row(
                    dataset_rows,
                    policy_id=policy_id,
                    budget=budget,
                    dataset_id=dataset_id,
                    horizon_hours=48,
                )
                for dataset_id in DATASETS
            ]
            dataset_zone = [row for row in dataset_zone if row is not None]
            dataset_breach = [
                find_row(
                    dataset_rows,
                    policy_id=policy_id,
                    budget=budget,
                    dataset_id=dataset_id,
                    horizon_hours=96,
                )
                for dataset_id in DATASETS
            ]
            dataset_breach = [row for row in dataset_breach if row is not None]
            pooled_zone_delta = point(pooled_zone, "zone_contact_precision")
            pooled_hit_delta = point(pooled_zone, "cell_hit_rate")
            pooled_survival_delta = point(pooled_survival, "zone_contact_and_survival_rate")
            pooled_breach_increase = point(pooled_survival, "sustained_breach_rate")
            pooled_exact_delta = point(pooled_zone, "future_exact_contact_precision")
            worst_dataset_zone_delta = min(
                (
                    value
                    for value in (
                        point(row, "zone_contact_precision") for row in dataset_zone
                    )
                    if value is not None
                ),
                default=None,
            )
            worst_dataset_breach_increase = max(
                (
                    value
                    for value in (
                        point(row, "sustained_breach_rate") for row in dataset_breach
                    )
                    if value is not None
                ),
                default=None,
            )
            late_zone_delta = point(pooled_zone, "zone_contact_precision", "late")
            worst_late_delta = min(
                (
                    value
                    for value in (
                        point(row, "zone_contact_precision", "late")
                        for row in dataset_zone
                    )
                    if value is not None
                ),
                default=None,
            )
            required_rows = [
                row
                for row in (*all_rows, *pooled_rows, *dataset_rows)
                if row["policy_id"] == policy_id and int(row["budget"]) == budget
            ]
            bootstrap_sufficient = bool(required_rows) and all(
                metric["valid_replicates"] >= BOOTSTRAP_MIN_VALID
                for row in required_rows
                for period in row.get("periods", {}).values()
                for metric in period.get("metrics", {}).values()
            )
            gates = {
                "integrity": integrity_ok,
                "pooled_nonempty_coverage_at_least_0_80": coverage >= 0.80,
                "worst_lane_nonempty_coverage_at_least_0_65": worst_coverage >= 0.65,
                "median_selected_count_at_least_2": median_selected >= 2,
                "median_selected_count_at_most_budget": median_selected <= budget,
                "median_actionable_eligible_at_most_30": median_eligible <= 30,
                "worst_lane_actionable_p90_at_most_60": worst_p90 <= 60,
                "pooled_48h_zone_precision_delta_at_least_0_02": pooled_zone_delta is not None and pooled_zone_delta >= 0.02,
                "pooled_48h_zone_precision_bootstrap_lower_gt_0": (lower(pooled_zone, "zone_contact_precision") or -math.inf) > 0,
                "worst_dataset_48h_zone_precision_delta_at_least_minus_0_02": worst_dataset_zone_delta is not None and worst_dataset_zone_delta >= -0.02,
                "pooled_48h_cell_hit_delta_nonnegative": pooled_hit_delta is not None and pooled_hit_delta >= 0,
                "pooled_96h_survival_delta_nonnegative": pooled_survival_delta is not None and pooled_survival_delta >= 0,
                "worst_dataset_96h_breach_increase_at_most_0_02": worst_dataset_breach_increase is not None and worst_dataset_breach_increase <= 0.02,
                "pooled_exact_precision_delta_nonnegative": pooled_exact_delta is not None and pooled_exact_delta >= 0,
                "late_pooled_48h_zone_precision_delta_nonnegative": late_zone_delta is not None and late_zone_delta >= 0,
                "worst_dataset_late_48h_zone_precision_delta_at_least_minus_0_03": worst_late_delta is not None and worst_late_delta >= -0.03,
                "near_or_approaching_share_at_least_0_20": near_approach >= 0.20,
                "bootstrap_inference_sufficient": bootstrap_sufficient,
            }
            gate_results.append(
                {
                    "policy_id": policy_id,
                    "budget": budget,
                    "gates": gates,
                    "passes": all(gates.values()),
                    "summary": {
                        "pooled_48h_zone_precision_delta": pooled_zone_delta,
                        "pooled_48h_zone_precision_bootstrap_lower": lower(pooled_zone, "zone_contact_precision"),
                        "worst_dataset_48h_zone_precision_delta": worst_dataset_zone_delta,
                        "pooled_48h_cell_hit_delta": pooled_hit_delta,
                        "pooled_96h_survival_delta": pooled_survival_delta,
                        "pooled_96h_breach_increase": pooled_breach_increase,
                        "worst_dataset_96h_breach_increase": worst_dataset_breach_increase,
                        "pooled_48h_exact_precision_delta": pooled_exact_delta,
                        "late_pooled_48h_zone_precision_delta": late_zone_delta,
                        "worst_dataset_late_48h_zone_precision_delta": worst_late_delta,
                        "median_selected_count": median_selected,
                        "median_actionable_eligible": median_eligible,
                        "worst_actionable_p90": worst_p90,
                        "near_or_approaching_share": near_approach,
                    },
                }
            )

    passing = [row for row in gate_results if row["passes"]]
    any_selected = any(
        float(row["summary"]["median_selected_count"]) > 0
        for row in gate_results
    )
    if not integrity_ok:
        status = "ACTIONABILITY_EVIDENCE_INCOMPLETE"
    elif not any_selected:
        status = "INSUFFICIENT_ACTIONABLE_POPULATION"
    elif passing:
        status = "ACTIONABLE_INTERACTION_SHORTLIST_FEASIBLE"
    else:
        status = "NO_ACTIONABLE_INTERACTION_SHORTLIST_FINALIST"
    ranked = sorted(
        passing,
        key=lambda row: (
            -float(row["summary"]["worst_dataset_48h_zone_precision_delta"] or 0),
            -float(row["summary"]["pooled_48h_zone_precision_delta"] or 0),
            -float(row["summary"]["pooled_48h_cell_hit_delta"] or 0),
            float(row["summary"]["median_selected_count"]),
            int(row["budget"]),
            row["policy_id"],
        ),
    )
    finalist = (
        {"policy_id": ranked[0]["policy_id"], "budget": ranked[0]["budget"]}
        if ranked
        else None
    )
    payload = {
        "schema_version": f"{STUDY_SCHEMA}_decision_v1",
        "status": status,
        "finalist": finalist,
        "policy_budget_gate_results": gate_results,
        "integrity": integrity_ok,
        "unresolved_evidence_count": int(integrity_audit["unresolved_evidence_count"]),
        "reconciliation_count": int(integrity_audit["reconciliation_count"]),
        "future_utility_evaluated": True,
        "interpretation": "actionability_shortlist_not_quality_ranking",
    }
    return {**payload, "decision_id": _identity(DECISION_NAMESPACE, payload)}


def _inventory(rendered: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    members = [{"path": name, "size": len(_canonical_bytes(rendered[name])), "sha256": _sha256_bytes(_canonical_bytes(rendered[name]))} for name in MEMBER_NAMES[:-1]]
    payload = {"schema_version": f"{STUDY_SCHEMA}_output_inventory_v1", "members": sorted(members, key=lambda item: item["path"])}
    return {**payload, "inventory_id": _identity(INVENTORY_NAMESPACE, payload)}


def _manifest(rendered: Mapping[str, Mapping[str, Any]], inventory: Mapping[str, Any]) -> dict[str, Any]:
    inventory_bytes = _canonical_bytes(inventory)
    members = list(inventory["members"]) + [{"path": "output_inventory.json", "size": len(inventory_bytes), "sha256": _sha256_bytes(inventory_bytes)}]
    payload = {"schema_version": f"{STUDY_SCHEMA}_manifest_v1", "contract_id": rendered["study_contract.json"]["contract_id"], "source_binding_id": rendered["source_binding.json"]["source_binding_id"], "validation_lock_id": rendered["validation_lock.json"]["validation_lock_id"], "decision_id": rendered["decision.json"]["decision_id"], "study_status": rendered["decision.json"]["status"], "output_inventory_id": inventory["inventory_id"], "output_inventory_sha256": _sha256_bytes(inventory_bytes), "member_count": len(members), "members": sorted(members, key=lambda item: item["path"])}
    return {**payload, "manifest_id": _identity(MANIFEST_NAMESPACE, payload)}


def _render_bytes(rendered: Mapping[str, Mapping[str, Any]]) -> dict[str, bytes]:
    inventory = _inventory(rendered)
    with_inventory = {**rendered, "output_inventory.json": inventory}
    with_inventory["manifest.json"] = _manifest(with_inventory, inventory)
    return {name: _canonical_bytes(with_inventory[name]) for name in ARTIFACT_NAMES}


def _validate_bundle(root: Path, expected: Mapping[str, bytes]) -> None:
    entries = list(root.iterdir())
    if (
        sorted(path.name for path in entries) != sorted(ARTIFACT_NAMES)
        or any(not path.is_file() for path in entries)
    ):
        raise StudyError("output file set mismatch")
    for name, expected_bytes in expected.items():
        actual = (root / name).read_bytes()
        if actual != expected_bytes:
            raise StudyError(f"output bytes mismatch: {name}")
        _load_json_bytes(actual)
    inventory = _load_json(root / "output_inventory.json")
    if inventory["inventory_id"] != _identity(INVENTORY_NAMESPACE, {key: value for key, value in inventory.items() if key != "inventory_id"}):
        raise StudyError("inventory identity mismatch")
    manifest = _load_json(root / "manifest.json")
    if manifest["manifest_id"] != _identity(MANIFEST_NAMESPACE, {key: value for key, value in manifest.items() if key != "manifest_id"}):
        raise StudyError("manifest identity mismatch")
    if manifest["member_count"] != 12 or set(item["path"] for item in manifest["members"]) != set(ARTIFACT_NAMES[:-1]):
        raise StudyError("manifest member mismatch")
    for member in manifest["members"]:
        path = root / member["path"]
        if member["size"] != path.stat().st_size or member["sha256"] != _sha256_file(path):
            raise StudyError(f"manifest hash mismatch: {member['path']}")


def _prepare_staging(root: Path) -> Path:
    if root.exists():
        raise StudyError("output root already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f".{root.name}.", dir=root.parent))


def _cleanup(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_dir():
            _cleanup(child)
        else:
            child.unlink()
    path.rmdir()


def execute_study(output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    if os.environ.get("TRENDLINE_V2_ALLOW_PHASE14A1R1_STUDY") != "1":
        raise StudyError("set TRENDLINE_V2_ALLOW_PHASE14A1R1_STUDY=1")
    staging = _prepare_staging(output_root)
    try:
        def persist_pre_evaluation(contract: Mapping[str, Any], binding: Mapping[str, Any]) -> None:
            pre_lock = _validation_lock(contract, binding, "EVALUATION_NOT_STARTED", phase="PRE_EVALUATION")
            (staging / "validation_lock.json").write_bytes(_canonical_bytes(pre_lock))

        rendered = _derive_evidence(persist_pre_evaluation)
        expected = _render_bytes(rendered)
        for name, data in expected.items():
            (staging / name).write_bytes(data)
        _validate_bundle(staging, expected)
        os.replace(staging, output_root)
        manifest = _load_json(output_root / "manifest.json")
        return {"status": manifest["study_status"], "decision_id": manifest["decision_id"], "manifest_id": manifest["manifest_id"], "output_inventory_sha256": manifest["output_inventory_sha256"], "member_count": len(ARTIFACT_NAMES), "provider_execution_count": 0, "network_request_count": 0}
    except Exception:
        _cleanup(staging)
        raise


def verify_bundle(root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    if root != OUTPUT_ROOT:
        raise StudyError("alternate output root is not authorized")
    if not root.is_dir():
        raise StudyError("output root missing")
    rendered = _derive_evidence()
    expected = _render_bytes(rendered)
    _validate_bundle(root, expected)
    manifest = _load_json(root / "manifest.json")
    return {"status": manifest["study_status"], "decision_id": manifest["decision_id"], "manifest_id": manifest["manifest_id"], "output_inventory_sha256": manifest["output_inventory_sha256"], "member_count": len(ARTIFACT_NAMES), "provider_execution_count": 0, "network_request_count": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-study", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.execute_study == args.verify:
        parser.error("choose exactly one of --execute-study or --verify")
    try:
        result = execute_study() if args.execute_study else verify_bundle()
    except StudyError as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
