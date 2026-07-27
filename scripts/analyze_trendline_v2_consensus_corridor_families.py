"""Measure causal consensus-corridor formation from frozen candidate evidence.

This study clusters valid same-role candidate structures only. It does not
evaluate future outcomes, load holdout or temporal evidence, call a provider,
access the network, or change production selection.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import tempfile
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage

from libs.models.trendline_v2.domain.identity import canonical_json, deterministic_hash
from scripts import analyze_trendline_v2_quality_signal_feasibility as source_loader


STUDY_SCHEMA = "trendline_v2_phase_13h1_consensus_corridor_families_v1"
CONTRACT_NAMESPACE = f"{STUDY_SCHEMA}_contract"
SOURCE_NAMESPACE = f"{STUDY_SCHEMA}_source_binding"
SNAPSHOT_NAMESPACE = f"{STUDY_SCHEMA}_source_snapshot"
FAMILY_NAMESPACE = f"{STUDY_SCHEMA}_family"
LOCK_NAMESPACE = f"{STUDY_SCHEMA}_validation_lock"
DECISION_NAMESPACE = f"{STUDY_SCHEMA}_decision"
INVENTORY_NAMESPACE = f"{STUDY_SCHEMA}_output_inventory"
MANIFEST_NAMESPACE = f"{STUDY_SCHEMA}_manifest"

SOURCE_ROOT = Path(
    "/tmp/trendline_v2_phase9c2_fresh_scope_family_validation/"
    "20260522_20260701"
)
OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_phase13h1_consensus_corridor_families/"
    "20260522_20260701"
)

SOURCE_DECISION_ID = "4b734cbf99e1453bccdedb95f397f4b34e020f29e3d18808a131456647f78f7c"
SOURCE_MANIFEST_ID = "beab5b9acb2bfc3c25ba9cb5cb31c33c1a31e6069c1d7906f3ed5e1c2d798c81"
SOURCE_INVENTORY_SHA256 = "ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532"
UNDERLYING_SOURCE_INVENTORY_SHA256 = "631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be"
SOURCE_MANIFEST_SHA256 = "4db6402a4fdd911cbe8a1b4b30f8ee27431e2f2c751a572d1fec92f0b7d25121"

VALIDATION_DATASETS = ("btcusdt_1h", "btcusdt_4h", "ethusdt_1h", "ethusdt_4h")
HOLDOUT_DATASETS = ("suiusdt_1h", "suiusdt_4h")
ROLES = ("support", "resistance")
WARMUP_HOURS = 336
CHECKPOINT_CADENCE_HOURS = 24
FOCUS_RECENT_BARS = 100
FOCUS_MIN_ANCHOR_SPAN = 25
FOCUS_MAX_PER_ROLE = 12
VARIANTS = (
    {"variant_id": "consensus_narrow_v1", "max_complete_link_distance_atr": 0.25},
    {"variant_id": "consensus_balanced_v1", "max_complete_link_distance_atr": 0.50},
    {"variant_id": "consensus_wide_v1", "max_complete_link_distance_atr": 1.00},
)

ARTIFACT_NAMES = (
    "study_contract.json",
    "source_binding.json",
    "checkpoint_schedule.json",
    "active_candidate_rows.json",
    "family_membership.json",
    "family_geometry.json",
    "temporal_family_links.json",
    "compression_metrics.json",
    "control_comparison.json",
    "validation_lock.json",
    "decision.json",
    "output_inventory.json",
    "manifest.json",
)
MEMBER_NAMES = ARTIFACT_NAMES[:-1]


class StudyError(RuntimeError):
    """Raised when frozen source or study evidence fails closed."""


def _canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise StudyError(f"cannot read file: {path}") from exc


def _identity(namespace: str, payload: Mapping[str, Any]) -> str:
    return deterministic_hash(namespace, payload)


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
    except (OSError, UnicodeError, ValueError) as exc:
        raise StudyError("invalid JSON") from exc
    if not isinstance(value, dict):
        raise StudyError("JSON object required")
    if raw != _canonical_bytes(value):
        raise StudyError("non-canonical JSON")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise StudyError(f"cannot read JSON: {path}") from exc
    try:
        return _load_json_bytes(raw)
    except StudyError as exc:
        raise StudyError(f"invalid JSON: {path}") from exc


def _iso(ns: int) -> str:
    value = datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


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


def _source_snapshot(root: Path = SOURCE_ROOT) -> dict[str, Any]:
    if not root.is_dir() or root.is_symlink():
        raise StudyError("source root missing or symlinked")
    member_hashes = {
        relative: _sha256_file(root / "datasets" / relative)
        for relative in sorted(source_loader.EXPECTED_MEMBER_HASHES)
    }
    payload = {
        "schema_version": f"{STUDY_SCHEMA}_source_snapshot_v1",
        "source_manifest_sha256": _sha256_file(root / "manifest.json"),
        "member_hashes": member_hashes,
    }
    return {**payload, "snapshot_id": _identity(SNAPSHOT_NAMESPACE, payload)}


def _validate_source(root: Path = SOURCE_ROOT) -> dict[str, Any]:
    if root != SOURCE_ROOT:
        raise StudyError("alternate source root is not authorized")
    source_loader._load_source_manifest(root)
    snapshot = _source_snapshot(root)
    if snapshot["source_manifest_sha256"] != SOURCE_MANIFEST_SHA256:
        raise StudyError("source manifest file hash mismatch")
    return snapshot


def _load_datasets(root: Path = SOURCE_ROOT) -> tuple[Any, ...]:
    _validate_source(root)
    datasets = tuple(source_loader._load_dataset(dataset_id, root) for dataset_id in VALIDATION_DATASETS)
    if any(dataset.dataset_id not in VALIDATION_DATASETS for dataset in datasets):
        raise StudyError("dataset allowlist violation")
    return datasets


def _checkpoint_schedule(dataset: Any) -> list[dict[str, Any]]:
    interval_ns = dataset.interval_seconds * 1_000_000_000
    cadence_ns = CHECKPOINT_CADENCE_HOURS * 3_600 * 1_000_000_000
    warmup_ns = WARMUP_HOURS * 3_600 * 1_000_000_000
    checkpoint = dataset.timestamps[0] + warmup_ns
    final_boundary = dataset.timestamps[-1] + interval_ns
    rows: list[dict[str, Any]] = []
    index = 1
    while checkpoint <= final_boundary:
        prefix_position = bisect_left(dataset.timestamps, checkpoint)
        if prefix_position < 15 or prefix_position > len(dataset.timestamps):
            raise StudyError(f"invalid checkpoint prefix: {dataset.dataset_id}")
        atr = dataset.atr[prefix_position - 1]
        if atr is None or not math.isfinite(float(atr)) or float(atr) <= 0:
            raise StudyError(f"checkpoint ATR unavailable: {dataset.dataset_id}")
        rows.append(
            {
                "checkpoint_index": index,
                "checkpoint": _iso(checkpoint),
                "checkpoint_ns": checkpoint,
                "checkpoint_position": prefix_position,
                "prefix_row_count": prefix_position,
                "last_known_bar": _iso(dataset.timestamps[prefix_position - 1]),
                "checkpoint_close": dataset.closes[prefix_position - 1],
                "checkpoint_atr_14": float(atr),
            }
        )
        checkpoint += cadence_ns
        index += 1
    if len(rows) < 10:
        raise StudyError(f"insufficient checkpoints: {dataset.dataset_id}")
    return rows


def _line_price(dataset: Any, candidate: Mapping[str, Any], timestamp_ns: int) -> float:
    first, second = candidate["source_positions"]
    first_ns = dataset.timestamps[first]
    second_ns = dataset.timestamps[second]
    duration = second_ns - first_ns
    if duration <= 0:
        raise StudyError("candidate anchors are not ordered")
    fraction = (timestamp_ns - first_ns) / duration
    return float(candidate["start_price"]) + (
        float(candidate["end_price"]) - float(candidate["start_price"])
    ) * fraction


def _first_invalid_position(dataset: Any, candidate: Mapping[str, Any]) -> int | None:
    start = max(int(candidate["availability_position"]), int(candidate["confirmation_positions"][1]) + 1)
    for position in range(start, len(dataset.timestamps)):
        line = _line_price(dataset, candidate, dataset.timestamps[position])
        if candidate["role"] == "support":
            valid = line <= min(dataset.opens[position], dataset.closes[position])
        elif candidate["role"] == "resistance":
            valid = line >= max(dataset.opens[position], dataset.closes[position])
        else:
            raise StudyError(f"unsupported candidate role: {candidate['role']}")
        if not valid:
            return position
    return None


def _candidate_span(candidate: Mapping[str, Any]) -> int:
    return int(candidate["record"]["anchor_span_bars"])


def _candidate_ready_row(dataset: Any, candidate: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(candidate)
    row["first_invalid_position"] = _first_invalid_position(dataset, candidate)
    return row


def _representative_key(row: Mapping[str, Any]) -> tuple[int, str]:
    return (int(row["availability_position"]), str(row["candidate_id"]))


def _active_snapshot(
    dataset: Any,
    checkpoint: Mapping[str, Any],
    prepared_candidates: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
    prefix_position = int(checkpoint["checkpoint_position"])
    observations: list[dict[str, Any]] = []
    for candidate in prepared_candidates:
        if int(candidate["availability_position"]) > prefix_position:
            continue
        if max(int(value) for value in candidate["confirmation_positions"]) >= prefix_position:
            continue
        invalid = candidate["first_invalid_position"]
        if invalid is not None and int(invalid) < prefix_position:
            continue
        atr = float(checkpoint["checkpoint_atr_14"])
        close = float(checkpoint["checkpoint_close"])
        timestamp_ns = int(checkpoint["checkpoint_ns"])
        values = tuple(
            (_line_price(dataset, candidate, timestamp_ns + offset) - close) / atr
            for offset in (0, 24 * 3_600 * 1_000_000_000, 96 * 3_600 * 1_000_000_000)
        )
        observations.append(
            {
                "dataset_id": dataset.dataset_id,
                "asset": dataset.asset,
                "timeframe": dataset.timeframe,
                "checkpoint_index": checkpoint["checkpoint_index"],
                "checkpoint": checkpoint["checkpoint"],
                "checkpoint_position": prefix_position,
                "role": candidate["role"],
                "candidate_id": candidate["candidate_id"],
                "candidate_structure_id": candidate["candidate_structure_id"],
                "first_anchor_id": candidate["first_anchor_id"],
                "second_anchor_id": candidate["second_anchor_id"],
                "anchor_source_positions": list(candidate["source_positions"]),
                "confirmation_positions": list(candidate["confirmation_positions"]),
                "candidate_available_at": _iso(
                    dataset.timestamps[min(int(candidate["availability_position"]), len(dataset.timestamps) - 1)]
                ),
                "availability_position": int(candidate["availability_position"]),
                "anchor_span_bars": _candidate_span(candidate),
                "g0": values[0],
                "g24": values[1],
                "g96": values[2],
            }
        )
    by_structure: dict[tuple[str, str], dict[str, Any]] = {}
    for row in observations:
        key = (str(row["role"]), str(row["candidate_structure_id"]))
        current = by_structure.get(key)
        if current is None or _representative_key(row) < _representative_key(current):
            by_structure[key] = row
    role_counts = {
        role: sum(1 for row in observations if row["role"] == role)
        for role in ROLES
    }
    return sorted(by_structure.values(), key=_active_row_sort_key), len(observations), role_counts


def _active_row_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row["role"],
        float(row["g0"]),
        float(row["g24"]),
        float(row["g96"]),
        row["candidate_structure_id"],
        row["candidate_id"],
    )


def _focus_ids(rows: Sequence[Mapping[str, Any]], last_position: int) -> tuple[str, ...]:
    result: list[str] = []
    for role in ROLES:
        eligible = [
            row
            for row in rows
            if row["role"] == role
            and last_position - int(row["confirmation_positions"][1]) <= FOCUS_RECENT_BARS
            and int(row["anchor_span_bars"]) >= FOCUS_MIN_ANCHOR_SPAN
        ]
        representatives: dict[str, Mapping[str, Any]] = {}
        for row in eligible:
            key = str(row["second_anchor_id"])
            current = representatives.get(key)
            row_key = (-max(0, int(row["anchor_span_bars"]) - 1), -int(row["anchor_span_bars"]), row["candidate_id"])
            current_key = (
                (-max(0, int(current["anchor_span_bars"]) - 1), -int(current["anchor_span_bars"]), current["candidate_id"])
                if current is not None
                else None
            )
            if current is None or row_key < current_key:
                representatives[key] = row
        result.extend(
            row["candidate_id"]
            for row in sorted(
                representatives.values(),
                key=lambda item: (item["confirmation_positions"][1], item["candidate_id"]),
            )[:FOCUS_MAX_PER_ROLE]
        )
    return tuple(sorted(result))


def _one_per_second_anchor_ids(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    selected: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        key = str(row["second_anchor_id"])
        current = selected.get(key)
        if current is None or _representative_key(row) < _representative_key(current):
            selected[key] = row
    return tuple(sorted(row["candidate_id"] for row in selected.values()))


def _geometry_vector(row: Mapping[str, Any]) -> tuple[float, float, float]:
    return (float(row["g0"]), float(row["g24"]), float(row["g96"]))


def _distance(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    return max(abs(a - b) for a, b in zip(_geometry_vector(left), _geometry_vector(right)))


def _family_id(
    dataset_id: str,
    timeframe: str,
    role: str,
    checkpoint: str,
    variant_id: str,
    structure_ids: Sequence[str],
) -> str:
    payload = {
        "dataset_id": dataset_id,
        "timeframe": timeframe,
        "role": role,
        "checkpoint": checkpoint,
        "variant_id": variant_id,
        "candidate_structure_ids": sorted(structure_ids),
    }
    return _identity(FAMILY_NAMESPACE, payload)


def _family_classification(member_rows: Sequence[Mapping[str, Any]]) -> str:
    if len(member_rows) == 1:
        return "singleton"
    if len(member_rows) == 2:
        return "pair_consensus"
    anchors = {str(row["first_anchor_id"]) for row in member_rows} | {
        str(row["second_anchor_id"]) for row in member_rows
    }
    return "multi_anchor_consensus" if len(anchors) > 2 else "multi_member_single_anchor"


def _medoid(member_rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    scored: list[tuple[float, float, str, str, Mapping[str, Any]]] = []
    for candidate in member_rows:
        distances = [_distance(candidate, other) for other in member_rows]
        scored.append(
            (max(distances), sum(distances), str(candidate["candidate_structure_id"]), str(candidate["candidate_id"]), candidate)
        )
    return min(scored, key=lambda value: value[:4])[-1]


def _cluster_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    variant_id: str,
    max_distance: float,
) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=_active_row_sort_key)
    if not ordered:
        return []
    if len(ordered) == 1:
        labels = [1]
    else:
        matrix = np.asarray([_geometry_vector(row) for row in ordered], dtype=float)
        tree = linkage(matrix, method="complete", metric="chebyshev")
        labels = fcluster(tree, t=max_distance, criterion="distance").tolist()
    grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for label, row in zip(labels, ordered):
        grouped[int(label)].append(row)
    families: list[dict[str, Any]] = []
    for members in grouped.values():
        member_rows = sorted(members, key=lambda row: (row["candidate_structure_id"], row["candidate_id"]))
        role = str(member_rows[0]["role"])
        if any(str(row["role"]) != role for row in member_rows):
            raise StudyError("family role purity violation")
        structure_ids = [str(row["candidate_structure_id"]) for row in member_rows]
        medoid = _medoid(member_rows)
        vectors = [_geometry_vector(row) for row in member_rows]
        family = {
            "family_id": _family_id(
                str(member_rows[0]["dataset_id"]),
                str(member_rows[0]["timeframe"]),
                role,
                str(member_rows[0]["checkpoint"]),
                variant_id,
                structure_ids,
            ),
            "variant_id": variant_id,
            "dataset_id": member_rows[0]["dataset_id"],
            "timeframe": member_rows[0]["timeframe"],
            "role": role,
            "checkpoint_index": member_rows[0]["checkpoint_index"],
            "checkpoint": member_rows[0]["checkpoint"],
            "member_structure_ids": sorted(structure_ids),
            "member_candidate_ids": sorted(str(row["candidate_id"]) for row in member_rows),
            "member_count": len(member_rows),
            "unique_first_anchor_count": len({row["first_anchor_id"] for row in member_rows}),
            "unique_second_anchor_count": len({row["second_anchor_id"] for row in member_rows}),
            "member_anchor_span_bars": sorted(int(row["anchor_span_bars"]) for row in member_rows),
            "classification": _family_classification(member_rows),
            "medoid_candidate_id": medoid["candidate_id"],
            "medoid_structure_id": medoid["candidate_structure_id"],
            "g0_median": statistics.median(vector[0] for vector in vectors),
            "g24_median": statistics.median(vector[1] for vector in vectors),
            "g96_median": statistics.median(vector[2] for vector in vectors),
            "g0_minimum": min(vector[0] for vector in vectors),
            "g24_minimum": min(vector[1] for vector in vectors),
            "g96_minimum": min(vector[2] for vector in vectors),
            "g0_maximum": max(vector[0] for vector in vectors),
            "g24_maximum": max(vector[1] for vector in vectors),
            "g96_maximum": max(vector[2] for vector in vectors),
            "envelope_width_t0": max(vector[0] for vector in vectors) - min(vector[0] for vector in vectors),
            "envelope_width_t24": max(vector[1] for vector in vectors) - min(vector[1] for vector in vectors),
            "envelope_width_t96": max(vector[2] for vector in vectors) - min(vector[2] for vector in vectors),
        }
        families.append(family)
    return sorted(families, key=lambda family: family["family_id"])


def _jaccard(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    a = set(left["member_structure_ids"])
    b = set(right["member_structure_ids"])
    return len(a & b) / len(a | b) if a | b else 1.0


def _envelope_overlap(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    overlaps: list[float] = []
    for offset in (0, 24, 96):
        left_min = float(left[f"g{offset}_minimum"])
        left_max = float(left[f"g{offset}_maximum"])
        right_min = float(right[f"g{offset}_minimum"])
        right_max = float(right[f"g{offset}_maximum"])
        overlap = max(0.0, min(left_max, right_max) - max(left_min, right_min))
        width = max(left_max - left_min, right_max - right_min)
        overlaps.append(1.0 if width == 0 and left_min == right_min else overlap / width if width else 0.0)
    return min(overlaps)


def _family_pair_metrics(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    jaccard = _jaccard(left, right)
    overlap = _envelope_overlap(left, right)
    medoid_distance = max(
        abs(float(left[f"g{offset}_median"]) - float(right[f"g{offset}_median"]))
        for offset in (0, 24, 96)
    )
    return {
        "member_jaccard": jaccard,
        "envelope_overlap": overlap,
        "medoid_distance": medoid_distance,
        "admissible": jaccard >= 0.25 or (overlap >= 0.50 and medoid_distance <= 0.50),
    }


def _match_family_snapshots(
    previous: Sequence[Mapping[str, Any]],
    current: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    pairs: list[tuple[tuple[Any, ...], Mapping[str, Any], Mapping[str, Any], dict[str, Any]]] = []
    for old in previous:
        for new in current:
            if old["role"] != new["role"]:
                continue
            metrics = _family_pair_metrics(old, new)
            if metrics["admissible"]:
                key = (
                    -metrics["member_jaccard"],
                    -metrics["envelope_overlap"],
                    metrics["medoid_distance"],
                    old["family_id"],
                    new["family_id"],
                )
                pairs.append((key, old, new, metrics))
    pairs.sort(key=lambda item: item[0])
    old_to_new: dict[str, str] = {}
    new_to_old: dict[str, str] = {}
    chosen: dict[tuple[str, str], dict[str, Any]] = {}
    for _, old, new, metrics in pairs:
        if old["family_id"] in old_to_new or new["family_id"] in new_to_old:
            continue
        old_to_new[old["family_id"]] = new["family_id"]
        new_to_old[new["family_id"]] = old["family_id"]
        chosen[(old["family_id"], new["family_id"])] = metrics
    admissible_old: dict[str, list[str]] = defaultdict(list)
    admissible_new: dict[str, list[str]] = defaultdict(list)
    metric_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for _, old, new, metrics in pairs:
        admissible_old[old["family_id"]].append(new["family_id"])
        admissible_new[new["family_id"]].append(old["family_id"])
        metric_by_pair[(old["family_id"], new["family_id"])] = metrics
    events: list[dict[str, Any]] = []
    for old in previous:
        old_id = old["family_id"]
        new_id = old_to_new.get(old_id)
        if new_id is not None:
            metrics = chosen[(old_id, new_id)]
            events.append({"event_type": "continuation", "old_family_id": old_id, "new_family_id": new_id, **metrics})
            if len(admissible_old.get(old_id, [])) > 1:
                events.append({"event_type": "split", "old_family_id": old_id, "new_family_id": None, "related_family_ids": sorted(admissible_old[old_id]), **metrics})
        elif len(admissible_old.get(old_id, [])) > 1:
            events.append({"event_type": "split", "old_family_id": old_id, "new_family_id": None, "related_family_ids": sorted(admissible_old[old_id]), **metric_by_pair[(old_id, admissible_old[old_id][0])]})
        elif not admissible_old.get(old_id):
            events.append({"event_type": "death", "old_family_id": old_id, "new_family_id": None, "member_jaccard": 0.0, "envelope_overlap": 0.0, "medoid_distance": None})
        else:
            events.append({"event_type": "unmatched", "old_family_id": old_id, "new_family_id": None, **metric_by_pair[(old_id, admissible_old[old_id][0])]})
    for new in current:
        new_id = new["family_id"]
        old_id = new_to_old.get(new_id)
        if old_id is not None:
            if len(admissible_new.get(new_id, [])) > 1:
                events.append({"event_type": "merge", "old_family_id": None, "new_family_id": new_id, "related_family_ids": sorted(admissible_new[new_id]), **chosen[(old_id, new_id)]})
            continue
        if len(admissible_new.get(new_id, [])) > 1:
            events.append({"event_type": "merge", "old_family_id": None, "new_family_id": new_id, "related_family_ids": sorted(admissible_new[new_id]), **metric_by_pair[(admissible_new[new_id][0], new_id)]})
        elif not admissible_new.get(new_id):
            events.append({"event_type": "birth", "old_family_id": None, "new_family_id": new_id, "member_jaccard": 0.0, "envelope_overlap": 0.0, "medoid_distance": None})
        else:
            events.append({"event_type": "unmatched", "old_family_id": None, "new_family_id": new_id, **metric_by_pair[(admissible_new[new_id][0], new_id)]})
    continuation = [event for event in events if event["event_type"] == "continuation"]
    current_count = len(current)
    summary = {
        "continuation_coverage": len(continuation) / current_count if current_count else 0.0,
        "continued_family_member_jaccard_median": statistics.median(event["member_jaccard"] for event in continuation) if continuation else 0.0,
        "family_count_churn": abs(len(current) - len(previous)) / max(len(previous), 1),
    }
    return sorted(events, key=lambda event: (event["event_type"], event.get("old_family_id") or "", event.get("new_family_id") or "")), summary


def _controls(rows: Sequence[Mapping[str, Any]], latest_ids: set[str], last_position: int) -> dict[str, Any]:
    return {
        "raw_currently_valid_structure_count": len(rows),
        "one_per_second_anchor_count": len(_one_per_second_anchor_ids(rows)),
        "current_focus_count": len(_focus_ids(rows, last_position)),
        "current_focus_membership": list(_focus_ids(rows, last_position)),
        "current_focus_settings": {
            "recent_confirmation_bars": FOCUS_RECENT_BARS,
            "minimum_anchor_span_bars": FOCUS_MIN_ANCHOR_SPAN,
            "unique_second_anchor": True,
            "maximum_per_role": FOCUS_MAX_PER_ROLE,
        },
        "latest_valid_predecessor_count": len({row["candidate_id"] for row in rows} & latest_ids),
    }


def _derive_snapshots(datasets: Sequence[Any]) -> dict[str, Any]:
    schedules: dict[str, list[dict[str, Any]]] = {}
    active_rows: list[dict[str, Any]] = []
    control_rows: list[dict[str, Any]] = []
    family_geometry: list[dict[str, Any]] = []
    family_membership: list[dict[str, Any]] = []
    snapshot_families: dict[tuple[str, str, str, int], list[dict[str, Any]]] = {}
    lane_inputs: list[dict[str, Any]] = []
    integrity_issues: list[dict[str, Any]] = []
    for dataset in datasets:
        schedule = _checkpoint_schedule(dataset)
        schedules[dataset.dataset_id] = schedule
        prepared = tuple(_candidate_ready_row(dataset, candidate) for candidate in dataset.candidates)
        latest_ids = set(dataset.family_membership.get("latest_valid_predecessor_v1", frozenset()))
        for checkpoint in schedule:
            rows, _, observation_counts = _active_snapshot(dataset, checkpoint, prepared)
            active_rows.extend(rows)
            for role in ROLES:
                role_rows = [row for row in rows if row["role"] == role]
                control = _controls(role_rows, latest_ids, int(checkpoint["checkpoint_position"]))
                control_rows.append({
                    "dataset_id": dataset.dataset_id,
                    "timeframe": dataset.timeframe,
                    "role": role,
                    "checkpoint_index": checkpoint["checkpoint_index"],
                    "checkpoint": checkpoint["checkpoint"],
                    "observation_count_before_structure_deduplication": observation_counts[role],
                    "active_structure_count": len(role_rows),
                    **control,
                })
                lane_inputs.append({
                    "dataset_id": dataset.dataset_id,
                    "timeframe": dataset.timeframe,
                    "role": role,
                    "checkpoint_index": checkpoint["checkpoint_index"],
                    "checkpoint": checkpoint["checkpoint"],
                    "raw_observation_count": observation_counts[role],
                    "active_structure_count": len(role_rows),
                })
                for variant in VARIANTS:
                    variant_id = variant["variant_id"]
                    families = _cluster_rows(
                        role_rows,
                        variant_id=variant_id,
                        max_distance=float(variant["max_complete_link_distance_atr"]),
                    )
                    snapshot_families[(dataset.dataset_id, variant_id, role, checkpoint["checkpoint_index"])] = families
                    expected_structures = {
                        str(row["candidate_structure_id"]) for row in role_rows
                    }
                    assigned_structures = [
                        structure_id
                        for family in families
                        for structure_id in family["member_structure_ids"]
                    ]
                    if (
                        len(assigned_structures) != len(expected_structures)
                        or len(set(assigned_structures)) != len(assigned_structures)
                        or set(assigned_structures) != expected_structures
                    ):
                        integrity_issues.append({
                            "dataset_id": dataset.dataset_id,
                            "role": role,
                            "variant_id": variant_id,
                            "checkpoint_index": checkpoint["checkpoint_index"],
                            "expected_structure_count": len(expected_structures),
                            "assigned_structure_count": len(assigned_structures),
                        })
                    for family in families:
                        family_geometry.append(family)
                        family_membership.append({
                            "dataset_id": dataset.dataset_id,
                            "timeframe": dataset.timeframe,
                            "role": role,
                            "checkpoint_index": checkpoint["checkpoint_index"],
                            "checkpoint": checkpoint["checkpoint"],
                            "variant_id": variant_id,
                            "family_id": family["family_id"],
                            "member_structure_ids": family["member_structure_ids"],
                            "member_candidate_ids": family["member_candidate_ids"],
                        })
    return {
        "schedules": schedules,
        "active_rows": sorted(active_rows, key=lambda row: (row["dataset_id"], row["checkpoint_index"], _active_row_sort_key(row))),
        "control_rows": sorted(control_rows, key=lambda row: (row["dataset_id"], row["checkpoint_index"], row["role"])),
        "family_geometry": sorted(family_geometry, key=lambda row: (row["dataset_id"], row["variant_id"], row["checkpoint_index"], row["role"], row["family_id"])),
        "family_membership": sorted(family_membership, key=lambda row: (row["dataset_id"], row["variant_id"], row["checkpoint_index"], row["role"], row["family_id"])),
        "snapshot_families": snapshot_families,
        "lane_inputs": lane_inputs,
        "integrity_issues": sorted(
            integrity_issues,
            key=lambda row: (
                row["dataset_id"], row["variant_id"], row["role"], row["checkpoint_index"]
            ),
        ),
    }


def _derive_temporal(snapshot_data: Mapping[str, Any], datasets: Sequence[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    links: list[dict[str, Any]] = []
    stability: list[dict[str, Any]] = []
    schedules = snapshot_data["schedules"]
    for dataset in datasets:
        for variant in VARIANTS:
            variant_id = variant["variant_id"]
            for role in ROLES:
                schedule = schedules[dataset.dataset_id]
                for previous, current in zip(schedule, schedule[1:]):
                    old = snapshot_data["snapshot_families"].get((dataset.dataset_id, variant_id, role, previous["checkpoint_index"]), [])
                    new = snapshot_data["snapshot_families"].get((dataset.dataset_id, variant_id, role, current["checkpoint_index"]), [])
                    events, summary = _match_family_snapshots(old, new)
                    for event in events:
                        links.append({
                            "dataset_id": dataset.dataset_id,
                            "timeframe": dataset.timeframe,
                            "role": role,
                            "variant_id": variant_id,
                            "previous_checkpoint_index": previous["checkpoint_index"],
                            "previous_checkpoint": previous["checkpoint"],
                            "current_checkpoint_index": current["checkpoint_index"],
                            "current_checkpoint": current["checkpoint"],
                            **event,
                        })
                    stability.append({
                        "dataset_id": dataset.dataset_id,
                        "timeframe": dataset.timeframe,
                        "role": role,
                        "variant_id": variant_id,
                        "previous_checkpoint_index": previous["checkpoint_index"],
                        "current_checkpoint_index": current["checkpoint_index"],
                        **summary,
                    })
    return sorted(links, key=lambda row: (row["dataset_id"], row["variant_id"], row["role"], row["current_checkpoint_index"], row["event_type"], row.get("old_family_id") or "", row.get("new_family_id") or "")), stability


def _compression_metrics(
    snapshot_data: Mapping[str, Any],
    stability: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    geometry = snapshot_data["family_geometry"]
    lane_inputs = snapshot_data["lane_inputs"]
    family_by_key: dict[tuple[str, str, str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for family in geometry:
        family_by_key[(family["dataset_id"], family["variant_id"], family["role"], family["checkpoint_index"])].append(family)
    lane_metrics: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for lane in lane_inputs:
        for variant in VARIANTS:
            families = family_by_key[(lane["dataset_id"], variant["variant_id"], lane["role"], lane["checkpoint_index"])]
            family_count = len(families)
            member_count = sum(int(family["member_count"]) for family in families)
            singleton_members = sum(int(family["member_count"]) for family in families if family["classification"] == "singleton")
            multi_anchor_members = sum(int(family["member_count"]) for family in families if family["classification"] == "multi_anchor_consensus")
            lane_metrics[(variant["variant_id"], lane["dataset_id"], lane["role"])].append({
                "checkpoint_index": lane["checkpoint_index"],
                "raw_observation_count": lane["raw_observation_count"],
                "raw_structure_count": lane["active_structure_count"],
                "family_count": family_count,
                "compression_ratio": lane["active_structure_count"] / family_count if family_count else None,
                "non_singleton_structure_fraction": (member_count - singleton_members) / member_count if member_count else 0.0,
                "multi_anchor_consensus_structure_fraction": multi_anchor_members / member_count if member_count else 0.0,
            })
    variant_results: list[dict[str, Any]] = []
    for variant in VARIANTS:
        variant_id = variant["variant_id"]
        lane_records = [records for key, records in lane_metrics.items() if key[0] == variant_id]
        all_records = [record for records in lane_records for record in records]
        all_families = [family for family in geometry if family["variant_id"] == variant_id]
        lane_summaries: list[dict[str, Any]] = []
        for key, records in sorted(lane_metrics.items()):
            if key[0] != variant_id:
                continue
            lane_summaries.append({
                "dataset_id": key[1],
                "role": key[2],
                "checkpoint_count": len(records),
                "median_compression_ratio": statistics.median(record["compression_ratio"] for record in records if record["compression_ratio"] is not None),
                "p90_family_count": _percentile([float(record["family_count"]) for record in records], 0.90),
                "median_family_count": statistics.median(record["family_count"] for record in records),
                "median_non_singleton_structure_fraction": statistics.median(record["non_singleton_structure_fraction"] for record in records),
                "median_multi_anchor_consensus_structure_fraction": statistics.median(record["multi_anchor_consensus_structure_fraction"] for record in records),
            })
        continuity = [row for row in stability if row["variant_id"] == variant_id]
        widths_t0 = [float(family["envelope_width_t0"]) for family in all_families]
        widths_t96 = [float(family["envelope_width_t96"]) for family in all_families]
        gates = {
            "integrity": True,
            "population": all(summary["checkpoint_count"] >= 10 for summary in lane_summaries),
            "pooled_median_compression_at_least_5": bool(all_records) and statistics.median(record["compression_ratio"] for record in all_records if record["compression_ratio"] is not None) >= 5.0,
            "worst_lane_median_compression_at_least_3": bool(lane_summaries) and min(summary["median_compression_ratio"] for summary in lane_summaries) >= 3.0,
            "pooled_median_family_count_per_role_between_4_and_12": bool(all_records) and 4.0 <= statistics.median(record["family_count"] for record in all_records) <= 12.0,
            "worst_lane_p90_family_count_at_most_20": max(float(summary["p90_family_count"]) for summary in lane_summaries) <= 20.0,
            "median_non_singleton_coverage_at_least_0_60": statistics.median(record["non_singleton_structure_fraction"] for record in all_records) >= 0.60,
            "median_multi_anchor_coverage_at_least_0_30": statistics.median(record["multi_anchor_consensus_structure_fraction"] for record in all_records) >= 0.30,
            "median_t0_width_at_most_0_50": statistics.median(widths_t0) <= 0.50 if widths_t0 else False,
            "p90_t0_width_at_most_1_00": float(_percentile(widths_t0, 0.90) or math.inf) <= 1.00,
            "p90_t96_width_at_most_1_50": float(_percentile(widths_t96, 0.90) or math.inf) <= 1.50,
            "median_continuation_coverage_at_least_0_60": statistics.median(row["continuation_coverage"] for row in continuity) >= 0.60 if continuity else False,
            "median_continued_jaccard_at_least_0_30": statistics.median(row["continued_family_member_jaccard_median"] for row in continuity) >= 0.30 if continuity else False,
            "median_family_count_churn_at_most_0_40": statistics.median(row["family_count_churn"] for row in continuity) <= 0.40 if continuity else False,
        }
        variant_results.append({
            "variant_id": variant_id,
            "max_complete_link_distance_atr": variant["max_complete_link_distance_atr"],
            "lane_summaries": lane_summaries,
            "family_count": len(all_families),
            "family_widths_t0": widths_t0,
            "family_widths_t24": [float(family["envelope_width_t24"]) for family in all_families],
            "family_widths_t96": widths_t96,
            "gates": gates,
            "passes": all(gates.values()),
        })
    return {
        "schema_version": f"{STUDY_SCHEMA}_compression_metrics_v1",
        "variant_results": variant_results,
        "continuity_row_count": len(stability),
    }


def _contract(schedule: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    payload = {
        "schema_version": f"{STUDY_SCHEMA}_contract_v1",
        "source_decision_id": SOURCE_DECISION_ID,
        "source_manifest_id": SOURCE_MANIFEST_ID,
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "underlying_source_inventory_sha256": UNDERLYING_SOURCE_INVENTORY_SHA256,
        "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "validation_datasets": list(VALIDATION_DATASETS),
        "holdout_datasets": list(HOLDOUT_DATASETS),
        "checkpoint_policy": {
            "warmup_hours": WARMUP_HOURS,
            "cadence_hours": CHECKPOINT_CADENCE_HOURS,
            "prefix_rule": "bar_open < checkpoint",
            "availability_rule": "candidate_available_at <= checkpoint",
            "checkpoint_counts": {dataset_id: len(rows) for dataset_id, rows in sorted(schedule.items())},
        },
        "candidate_policy": {
            "roles": list(ROLES),
            "exact_side_support": "line_price <= min(open, close)",
            "exact_side_resistance": "line_price >= max(open, close)",
            "observation_deduplication": ["dataset", "role", "candidate_structure_id"],
            "representative_tiebreak": ["earliest_causal_availability", "lexicographically_smaller_candidate_id"],
            "minimum_anchor_span_filter": None,
        },
        "geometry": {
            "coordinates": ["t0", "t24", "t96"],
            "normalization": "(projected_line_price - checkpoint_close) / checkpoint_atr_14",
            "distance": "maximum_absolute_coordinate_difference",
        },
        "variants": [dict(variant) for variant in VARIANTS],
        "clustering": {
            "algorithm": "complete_linkage",
            "metric": "chebyshev",
            "input_order": ["role", "g0", "g24", "g96", "candidate_structure_id", "candidate_id"],
            "support_resistance_shared_family": False,
        },
        "family_matching": {
            "primary_score": ["member_jaccard_desc", "envelope_overlap_desc", "medoid_distance_asc", "family_id_asc"],
            "admissibility": "member_jaccard >= 0.25 OR (envelope_overlap >= 0.50 AND medoid_distance <= 0.50)",
            "scope": "adjacent_causal_checkpoint_snapshots_only",
        },
        "controls": {
            "raw_currently_valid_structures": True,
            "one_per_second_anchor": True,
            "current_focus": {
                "recent_confirmation_bars": FOCUS_RECENT_BARS,
                "minimum_anchor_span_bars": FOCUS_MIN_ANCHOR_SPAN,
                "unique_second_anchor": True,
                "maximum_per_role": FOCUS_MAX_PER_ROLE,
            },
            "latest_valid_predecessor": "diagnostic_when_reconstructable",
        },
        "gates": {
            "minimum_checkpoints_per_lane": 10,
            "pooled_median_compression": 5.0,
            "worst_lane_median_compression": 3.0,
            "pooled_median_family_count_per_role": [4, 12],
            "worst_lane_p90_family_count": 20,
            "median_non_singleton_coverage": 0.60,
            "median_multi_anchor_coverage": 0.30,
            "median_t0_width_atr": 0.50,
            "p90_t0_width_atr": 1.00,
            "p90_t96_width_atr": 1.50,
            "median_continuation_coverage": 0.60,
            "median_continued_jaccard": 0.30,
            "median_family_count_churn": 0.40,
        },
        "execution": {"provider_execution_count": 0, "network_request_count": 0, "legacy_execution_count": 0},
        "future_utility": "not_evaluated_in_phase_13h1",
    }
    return {**payload, "contract_id": _identity(CONTRACT_NAMESPACE, payload)}


def _source_binding(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": f"{STUDY_SCHEMA}_source_binding_v1",
        "source_root": str(SOURCE_ROOT),
        "source_decision_id": SOURCE_DECISION_ID,
        "source_manifest_id": SOURCE_MANIFEST_ID,
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "underlying_source_inventory_sha256": UNDERLYING_SOURCE_INVENTORY_SHA256,
        "validation_datasets": list(VALIDATION_DATASETS),
        "holdout_datasets": list(HOLDOUT_DATASETS),
        "source_before": before,
        "source_after": after,
        "source_immutability_verified": before == after,
    }
    if before != after:
        raise StudyError("source changed during study")
    return {**payload, "source_binding_id": _identity(SOURCE_NAMESPACE, payload)}


def _validation_lock(contract: Mapping[str, Any], source_binding: Mapping[str, Any], decision_status: str) -> dict[str, Any]:
    payload = {
        "schema_version": f"{STUDY_SCHEMA}_validation_lock_v1",
        "source_binding_id": source_binding["source_binding_id"],
        "contract_id": contract["contract_id"],
        "validation_datasets": list(VALIDATION_DATASETS),
        "holdout_datasets": list(HOLDOUT_DATASETS),
        "checkpoint_counts": contract["checkpoint_policy"]["checkpoint_counts"],
        "decision_status": decision_status,
        "future_utility_evaluation": "not_authorized",
    }
    return {**payload, "validation_lock_id": _identity(LOCK_NAMESPACE, payload)}


def _decision(
    compression: Mapping[str, Any],
    active_rows: Sequence[Mapping[str, Any]],
    family_geometry: Sequence[Mapping[str, Any]],
    integrity_issues: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    variant_results = compression["variant_results"]
    integrity = bool(variant_results) and not integrity_issues and all(
        result["gates"]["integrity"] for result in variant_results
    )
    population = all(
        all(summary["checkpoint_count"] >= 10 for summary in result["lane_summaries"])
        for result in variant_results
    )
    if not active_rows or not family_geometry:
        status = "INSUFFICIENT_ACTIVE_STRUCTURE"
    elif not integrity or not population:
        status = "CONSENSUS_CORRIDOR_EVIDENCE_INCOMPLETE"
    elif any(result["passes"] for result in variant_results):
        status = "CONSENSUS_CORRIDOR_FORMATION_FEASIBLE"
    else:
        status = "NO_STABLE_CONSENSUS_CORRIDOR_COMPRESSION"
    payload = {
        "schema_version": f"{STUDY_SCHEMA}_decision_v1",
        "status": status,
        "finalist": None,
        "passing_variants": [result["variant_id"] for result in variant_results if result["passes"]],
        "variant_gate_results": [
            {"variant_id": result["variant_id"], "gates": result["gates"], "passes": result["passes"]}
            for result in variant_results
        ],
        "active_candidate_row_count": len(active_rows),
        "family_geometry_row_count": len(family_geometry),
        "unresolved_evidence_count": 0,
        "reconciliation_count": 0,
        "integrity_issue_count": len(integrity_issues),
        "future_utility_evaluated": False,
        "interpretation": "formation_and_density_compression_only",
    }
    return {**payload, "decision_id": _identity(DECISION_NAMESPACE, payload)}


def _derive_evidence() -> dict[str, dict[str, Any]]:
    before = _validate_source()
    datasets = _load_datasets()
    snapshot_data = _derive_snapshots(datasets)
    temporal_links, stability = _derive_temporal(snapshot_data, datasets)
    compression = _compression_metrics(snapshot_data, stability)
    schedule = snapshot_data["schedules"]
    contract = _contract(schedule)
    decision = _decision(
        compression,
        snapshot_data["active_rows"],
        snapshot_data["family_geometry"],
        snapshot_data["integrity_issues"],
    )
    binding = _source_binding(before, _source_snapshot())
    lock = _validation_lock(contract, binding, decision["status"])
    schedule_payload = {
        "schema_version": f"{STUDY_SCHEMA}_checkpoint_schedule_v1",
        "datasets": {
            dataset_id: [
                {key: value for key, value in row.items() if key != "checkpoint_ns"}
                for row in rows
            ]
            for dataset_id, rows in sorted(schedule.items())
        },
    }
    control_payload = {
        "schema_version": f"{STUDY_SCHEMA}_control_comparison_v1",
        "rows": snapshot_data["control_rows"],
    }
    membership_payload = {
        "schema_version": f"{STUDY_SCHEMA}_family_membership_v1",
        "rows": snapshot_data["family_membership"],
        "active_structure_assignment_count": sum(
            int(family["member_count"]) for family in snapshot_data["family_geometry"]
        ),
        "integrity_issues": snapshot_data["integrity_issues"],
    }
    geometry_payload = {
        "schema_version": f"{STUDY_SCHEMA}_family_geometry_v1",
        "rows": snapshot_data["family_geometry"],
    }
    temporal_payload = {
        "schema_version": f"{STUDY_SCHEMA}_temporal_family_links_v1",
        "rows": temporal_links,
        "continuity_summary_rows": stability,
    }
    active_payload = {
        "schema_version": f"{STUDY_SCHEMA}_active_candidate_rows_v1",
        "rows": snapshot_data["active_rows"],
    }
    return {
        "study_contract.json": contract,
        "source_binding.json": binding,
        "checkpoint_schedule.json": schedule_payload,
        "active_candidate_rows.json": active_payload,
        "family_membership.json": membership_payload,
        "family_geometry.json": geometry_payload,
        "temporal_family_links.json": temporal_payload,
        "compression_metrics.json": compression,
        "control_comparison.json": control_payload,
        "validation_lock.json": lock,
        "decision.json": decision,
    }


def _inventory(rendered: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    members = [
        {"path": name, "size": len(_canonical_bytes(rendered[name])), "sha256": _sha256_bytes(_canonical_bytes(rendered[name]))}
        for name in MEMBER_NAMES[:-1]
    ]
    payload = {"schema_version": f"{STUDY_SCHEMA}_output_inventory_v1", "members": sorted(members, key=lambda item: item["path"])}
    return {**payload, "inventory_id": _identity(INVENTORY_NAMESPACE, payload)}


def _manifest(rendered: Mapping[str, Mapping[str, Any]], inventory: Mapping[str, Any]) -> dict[str, Any]:
    members = list(inventory["members"])
    inventory_bytes = _canonical_bytes(inventory)
    members.append({"path": "output_inventory.json", "size": len(inventory_bytes), "sha256": _sha256_bytes(inventory_bytes)})
    payload = {
        "schema_version": f"{STUDY_SCHEMA}_manifest_v1",
        "study_contract_id": rendered["study_contract.json"]["contract_id"],
        "source_binding_id": rendered["source_binding.json"]["source_binding_id"],
        "validation_lock_id": rendered["validation_lock.json"]["validation_lock_id"],
        "decision_id": rendered["decision.json"]["decision_id"],
        "study_status": rendered["decision.json"]["status"],
        "output_inventory_id": inventory["inventory_id"],
        "output_inventory_sha256": _sha256_bytes(inventory_bytes),
        "member_count": len(members),
        "members": sorted(members, key=lambda item: item["path"]),
    }
    return {**payload, "manifest_id": _identity(MANIFEST_NAMESPACE, payload)}


def _render_bytes(rendered: Mapping[str, Mapping[str, Any]]) -> dict[str, bytes]:
    inventory = _inventory(rendered)
    with_inventory = {**rendered, "output_inventory.json": inventory}
    manifest = _manifest(with_inventory, inventory)
    with_inventory["manifest.json"] = manifest
    return {name: _canonical_bytes(with_inventory[name]) for name in ARTIFACT_NAMES}


def _validate_bundle_files(root: Path, expected: Mapping[str, bytes]) -> None:
    if sorted(path.name for path in root.iterdir() if path.is_file()) != sorted(ARTIFACT_NAMES):
        raise StudyError("output file set mismatch")
    for name, expected_bytes in expected.items():
        actual = (root / name).read_bytes()
        if actual != expected_bytes:
            raise StudyError(f"output bytes mismatch: {name}")
        if actual != _canonical_bytes(_load_json(root / name)):
            raise StudyError(f"output is not canonical JSON: {name}")
    inventory = _load_json(root / "output_inventory.json")
    if inventory.get("inventory_id") != _identity(INVENTORY_NAMESPACE, {key: value for key, value in inventory.items() if key != "inventory_id"}):
        raise StudyError("output inventory identity mismatch")
    manifest = _load_json(root / "manifest.json")
    if manifest.get("manifest_id") != _identity(MANIFEST_NAMESPACE, {key: value for key, value in manifest.items() if key != "manifest_id"}):
        raise StudyError("manifest identity mismatch")
    listed = {item["path"]: item for item in manifest["members"]}
    if set(listed) != set(ARTIFACT_NAMES[:-1]):
        raise StudyError("manifest member set mismatch")
    for path, item in listed.items():
        actual = (root / path).read_bytes()
        if item["size"] != len(actual) or item["sha256"] != _sha256_bytes(actual):
            raise StudyError(f"manifest member mismatch: {path}")


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


def _publish(root: Path, rendered: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    staging = _prepare_staging(root)
    try:
        expected = _render_bytes(rendered)
        for name, data in expected.items():
            (staging / name).write_bytes(data)
        _validate_bundle_files(staging, expected)
        os.replace(staging, root)
        manifest = _load_json(root / "manifest.json")
        return {
            "status": manifest["study_status"],
            "decision_id": manifest["decision_id"],
            "manifest_id": manifest["manifest_id"],
            "output_inventory_sha256": manifest["output_inventory_sha256"],
            "member_count": manifest["member_count"] + 1,
            "provider_execution_count": 0,
            "network_request_count": 0,
        }
    except Exception:
        _cleanup(staging)
        raise


def execute_study(output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    if os.environ.get("TRENDLINE_V2_ALLOW_PHASE13H1_STUDY") != "1":
        raise StudyError("set TRENDLINE_V2_ALLOW_PHASE13H1_STUDY=1")
    staging = _prepare_staging(output_root)
    try:
        before = _validate_source()
        rendered = _derive_evidence()
        after = _validate_source()
        if before != after:
            raise StudyError("source changed between preflight and publication")
        expected = _render_bytes(rendered)
        for name, data in expected.items():
            (staging / name).write_bytes(data)
        _validate_bundle_files(staging, expected)
        os.replace(staging, output_root)
        manifest = _load_json(output_root / "manifest.json")
        return {
            "status": manifest["study_status"],
            "decision_id": manifest["decision_id"],
            "manifest_id": manifest["manifest_id"],
            "output_inventory_sha256": manifest["output_inventory_sha256"],
            "member_count": len(ARTIFACT_NAMES),
            "provider_execution_count": 0,
            "network_request_count": 0,
        }
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
    _validate_bundle_files(root, expected)
    manifest = _load_json(root / "manifest.json")
    return {
        "status": manifest["study_status"],
        "decision_id": manifest["decision_id"],
        "manifest_id": manifest["manifest_id"],
        "output_inventory_sha256": manifest["output_inventory_sha256"],
        "member_count": len(ARTIFACT_NAMES),
        "provider_execution_count": 0,
        "network_request_count": 0,
    }


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
