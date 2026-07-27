"""Measure causal trendline quality signals without changing production selection.

This study consumes only the frozen Phase 9C.2 BTC/ETH validation artifacts. It
does not import a provider, load SUI holdout data, open temporal checkpoints,
access the network, or write runtime configuration.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
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
from scipy.stats import spearmanr


STUDY_SCHEMA = "trendline_v2_phase_12q1_quality_signal_feasibility_v2"
CONTRACT_NAMESPACE = f"{STUDY_SCHEMA}_contract"
SOURCE_NAMESPACE = f"{STUDY_SCHEMA}_source_binding"
ROW_NAMESPACE = f"{STUDY_SCHEMA}_row"
GROUP_NAMESPACE = f"{STUDY_SCHEMA}_analysis_group"
LOCK_NAMESPACE = f"{STUDY_SCHEMA}_validation_lock"
DECISION_NAMESPACE = f"{STUDY_SCHEMA}_decision"
MANIFEST_NAMESPACE = f"{STUDY_SCHEMA}_manifest"
INVENTORY_NAMESPACE = f"{STUDY_SCHEMA}_output_inventory"

SOURCE_ROOT = Path(
    "/tmp/trendline_v2_phase9c2_fresh_scope_family_validation/"
    "20260522_20260701"
)
OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_phase12q1_quality_signal_feasibility/"
    "20260522_20260701_r2"
)
R1_OUTPUT_ROOT = OUTPUT_ROOT.parent / "20260522_20260701"
TEMPORAL_ROOT = Path(
    "/tmp/trendline_v2_phase10c2_lookback_eviction/20251201_20260401"
)

SOURCE_DECISION_ID = "4b734cbf99e1453bccdedb95f397f4b34e020f29e3d18808a131456647f78f7c"
SOURCE_MANIFEST_ID = "beab5b9acb2bfc3c25ba9cb5cb31c33c1a31e6069c1d7906f3ed5e1c2d798c81"
SOURCE_INVENTORY_SHA256 = "ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532"
UNDERLYING_SOURCE_INVENTORY_SHA256 = "631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be"

VALIDATION_DATASETS = ("btcusdt_1h", "btcusdt_4h", "ethusdt_1h", "ethusdt_4h")
HOLDOUT_DATASETS = ("suiusdt_1h", "suiusdt_4h")
CHECKPOINT_AGES = (0, 6, 12, 24)
HORIZONS = (6, 12, 24)
ROLES = ("support", "resistance")
PRIMARY_SEPARATION_BARS = 2
PRIMARY_SEPARATION_ATR = 0.5
SENSITIVITY_DEFINITIONS = (
    {"id": "one_bar_quarter_atr_v1", "separation_bars": 1, "separation_atr": 0.25},
    {"id": "three_bars_one_atr_v1", "separation_bars": 3, "separation_atr": 1.0},
)
MAX_HORIZON = max(HORIZONS)
BOOTSTRAP_REPLICATES = 1_000
BOOTSTRAP_CONFIDENCE_LEVEL = 0.95
BOOTSTRAP_MIN_VALID = int(BOOTSTRAP_REPLICATES * BOOTSTRAP_CONFIDENCE_LEVEL)
FOCUS_RECENT_BARS = 100
FOCUS_MIN_ANCHOR_SPAN = 25
FOCUS_MAX_PER_ROLE = 12
INTRINSIC_QUALITY_FAMILIES = (
    "interaction_reaction_v1",
    "combined_quality_v1",
)
DIAGNOSTIC_FAMILIES = (
    "relevance_only_v1",
    "combined_quality_plus_relevance_v1",
)

EXPECTED_MEMBER_HASHES = {
    "btcusdt_1h/candidate_records.json": "9a7204f7a383d02c00be2b1c87a3a5e145872714c7e3f70de3f064693c1cfa56",
    "btcusdt_1h/family_membership.json": "f1507434596135edc393bc1070b167ae7faf76e79450417666f3dab00f5b9d9b",
    "btcusdt_1h/provider_result.json": "39589107f6512af36bf69987a3580668851e3781d4990fd1d7d4ac6f912ff012",
    "btcusdt_4h/candidate_records.json": "a70c606ad949a5f58d25dd505d21589a9f983ffc092dd5f0228cf958cc7d0d4b",
    "btcusdt_4h/family_membership.json": "edb6b0f90f5ab7c09d6343729832ba2f256349b8e21ea12cde25b5005981e7e9",
    "btcusdt_4h/provider_result.json": "0fb88993e8ceed7b3812ec8fed895164b4fd00d1d392f5018f81aeea66dd4fe3",
    "ethusdt_1h/candidate_records.json": "9532c1191e54c4a842dfedeff25b5c6d67ff90d085a38f89359f0c937d095dd7",
    "ethusdt_1h/family_membership.json": "e20a1d4cba0c26ab66216c83381f6d45668768abaab5bfc5f2563690a38efb42",
    "ethusdt_1h/provider_result.json": "547b1818f2df0e1b95190355120960f55ca8379808fa94ce8f3f2ad0b3c5ab35",
    "ethusdt_4h/candidate_records.json": "02bf60af9bcd0d78004fa25f2f6ead878983cd7f45cbcaeb7bea81a513a82121",
    "ethusdt_4h/family_membership.json": "478efab6b0574c6ebcb614df66df7bff5a3789466a90337d0d9d748ef58cefac",
    "ethusdt_4h/provider_result.json": "2b3ccd8316d3119cbf3459d1eb98034124a90e0b20cad661955b1b1bf627087a",
}

ARTIFACT_NAMES = (
    "study_contract.json",
    "source_binding.json",
    "candidate_checkpoint_rows.json",
    "contact_episode_rows.json",
    "future_reaction_rows.json",
    "feature_associations.json",
    "model_validation.json",
    "feature_ablation.json",
    "validation_lock.json",
    "temporal_audit.json",
    "decision.json",
    "output_inventory.json",
    "manifest.json",
)


class StudyError(RuntimeError):
    """Raised when frozen evidence or study semantics fail closed."""


@dataclass(frozen=True, slots=True)
class Dataset:
    dataset_id: str
    asset: str
    timeframe: str
    interval_seconds: int
    timestamps: tuple[int, ...]
    opens: tuple[float, ...]
    highs: tuple[float, ...]
    lows: tuple[float, ...]
    closes: tuple[float, ...]
    volumes: tuple[float, ...]
    atr: tuple[float | None, ...]
    candidates: tuple[Mapping[str, Any], ...]
    records: Mapping[str, Mapping[str, Any]]
    family_membership: Mapping[str, frozenset[str]]
    source_hashes: Mapping[str, str]
    input_identity: str
    focus_membership: frozenset[str] = frozenset()


def _canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise StudyError(f"cannot read source file: {path}") from exc


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StudyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise StudyError(f"non-finite JSON constant: {value}")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise StudyError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise StudyError(f"JSON object required: {path}")
    if raw != _canonical_bytes(value):
        raise StudyError(f"non-canonical JSON: {path}")
    return value


def _finite(value: object, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise StudyError(f"{field} is not numeric") from exc
    if not math.isfinite(result):
        raise StudyError(f"{field} is not finite")
    return result


def _identity(namespace: str, payload: Mapping[str, Any]) -> str:
    return deterministic_hash(namespace, payload)


def _interval_seconds(timeframe: str) -> int:
    if timeframe.endswith("h"):
        return int(timeframe[:-1]) * 3_600
    raise StudyError(f"unsupported source timeframe: {timeframe}")


def _iso_to_ns(value: object) -> int:
    if not isinstance(value, str):
        raise StudyError("timestamp must be an ISO string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StudyError("invalid ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise StudyError("timestamp must be UTC")
    return int(parsed.timestamp() * 1_000_000_000)


def _atr14(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> tuple[float | None, ...]:
    if not (len(highs) == len(lows) == len(closes)):
        raise StudyError("OHLC arrays have different lengths")
    tr: list[float | None] = [None] * len(closes)
    for index in range(1, len(closes)):
        tr[index] = max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        )
    result: list[float | None] = [None] * len(closes)
    if len(closes) < 15:
        return tuple(result)
    seed = [value for value in tr[1:15] if value is not None]
    result[14] = sum(seed) / len(seed)
    for index in range(15, len(closes)):
        assert tr[index] is not None and result[index - 1] is not None
        result[index] = ((result[index - 1] * 13.0) + tr[index]) / 14.0
    return tuple(result)


def _load_source_manifest(root: Path = SOURCE_ROOT) -> dict[str, Any]:
    if not root.is_dir() or root.is_symlink():
        raise StudyError("source root missing or symlinked")
    manifest = _load_json(root / "manifest.json")
    if manifest.get("decision_id") != SOURCE_DECISION_ID:
        raise StudyError("source decision identity mismatch")
    if manifest.get("manifest_id") != SOURCE_MANIFEST_ID:
        raise StudyError("source manifest identity mismatch")
    if manifest.get("source_inventory_sha256") != UNDERLYING_SOURCE_INVENTORY_SHA256:
        raise StudyError("underlying source inventory mismatch")
    if manifest.get("member_count") != 37:
        raise StudyError("source member count mismatch")
    members = {item.get("path"): item.get("sha256") for item in manifest.get("members", [])}
    if any(not isinstance(path, str) or not isinstance(value, str) for path, value in members.items()):
        raise StudyError("invalid source manifest members")
    for relative, expected in EXPECTED_MEMBER_HASHES.items():
        path = root / "datasets" / relative
        # relative values are dataset-local in the constant map.
        if relative.count("/") == 1:
            path = root / "datasets" / relative
        else:
            path = root / "datasets" / relative
        manifest_path = relative if relative.startswith("datasets/") else f"datasets/{relative}"
        if manifest_path not in members or members[manifest_path] != expected:
            raise StudyError(f"source manifest hash binding missing: {manifest_path}")
        if _sha256_file(path) != expected:
            raise StudyError(f"source member hash mismatch: {manifest_path}")
    return {
        "schema_version": STUDY_SCHEMA + "_source_binding_v1",
        "source_root": str(root),
        "source_decision_id": SOURCE_DECISION_ID,
        "source_manifest_id": SOURCE_MANIFEST_ID,
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "underlying_source_inventory_sha256": UNDERLYING_SOURCE_INVENTORY_SHA256,
        "source_manifest_member_count": manifest["member_count"],
        "validation_datasets": list(VALIDATION_DATASETS),
        "holdout_datasets": list(HOLDOUT_DATASETS),
        "loaded_members": sorted(EXPECTED_MEMBER_HASHES),
    }


def _parse_input(input_data: Mapping[str, Any], dataset_id: str) -> tuple[str, str, int, tuple[int, ...], tuple[float, ...], tuple[float, ...], tuple[float, ...], tuple[float, ...], tuple[float, ...], str]:
    required = {"asset", "timeframe", "timestamps", "open", "high", "low", "close", "volume", "input_identity"}
    if set(input_data) != required | {"confirmed_through", "observed_at"}:
        raise StudyError(f"{dataset_id} input schema mismatch")
    asset = input_data["asset"]
    timeframe = input_data["timeframe"]
    if not isinstance(asset, str) or not isinstance(timeframe, str):
        raise StudyError("input identity fields must be strings")
    timestamps = tuple(int(value) for value in input_data["timestamps"])
    opens = tuple(_finite(value, "open") for value in input_data["open"])
    highs = tuple(_finite(value, "high") for value in input_data["high"])
    lows = tuple(_finite(value, "low") for value in input_data["low"])
    closes = tuple(_finite(value, "close") for value in input_data["close"])
    volumes = tuple(_finite(value, "volume") for value in input_data["volume"])
    arrays = (timestamps, opens, highs, lows, closes, volumes)
    if len({len(values) for values in arrays}) != 1 or not timestamps:
        raise StudyError(f"{dataset_id} input row lengths mismatch")
    interval = _interval_seconds(timeframe)
    expected_delta = interval * 1_000_000_000
    if any(right - left != expected_delta for left, right in zip(timestamps, timestamps[1:])):
        raise StudyError(f"{dataset_id} input timestamps are not contiguous")
    for index, (open_value, high_value, low_value, close_value, volume) in enumerate(
        zip(opens, highs, lows, closes, volumes)
    ):
        if high_value < max(open_value, close_value) or low_value > min(open_value, close_value):
            raise StudyError(f"{dataset_id} invalid OHLC at {index}")
        if volume < 0:
            raise StudyError(f"{dataset_id} negative volume at {index}")
    input_identity = input_data["input_identity"]
    if not isinstance(input_identity, str) or len(input_identity) != 64:
        raise StudyError(f"{dataset_id} invalid input identity")
    return asset, timeframe, interval, timestamps, opens, highs, lows, closes, volumes, input_identity


def _load_dataset(dataset_id: str, root: Path = SOURCE_ROOT) -> Dataset:
    if dataset_id not in VALIDATION_DATASETS:
        raise StudyError(f"dataset is outside Q1 validation allowlist: {dataset_id}")
    folder = root / "datasets" / dataset_id
    provider_path = folder / "provider_result.json"
    records_path = folder / "candidate_records.json"
    membership_path = folder / "family_membership.json"
    provider = _load_json(provider_path)
    records_payload = _load_json(records_path)
    membership_payload = _load_json(membership_path)
    provider_result = provider.get("provider_result")
    if not isinstance(provider_result, dict):
        raise StudyError(f"{dataset_id} provider result missing")
    input_data = provider_result.get("request", {}).get("input_data")
    if not isinstance(input_data, dict):
        raise StudyError(f"{dataset_id} provider input missing")
    asset, timeframe, interval, timestamps, opens, highs, lows, closes, volumes, input_identity = _parse_input(input_data, dataset_id)
    records = records_payload.get("records")
    if not isinstance(records, list):
        raise StudyError(f"{dataset_id} candidate records missing")
    record_map = {record.get("candidate_id"): record for record in records if isinstance(record, dict)}
    candidates = provider_result.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != len(record_map):
        raise StudyError(f"{dataset_id} candidate population mismatch")
    if len(record_map) != len(records) or any(not isinstance(key, str) for key in record_map):
        raise StudyError(f"{dataset_id} duplicate or malformed candidate records")
    by_time = {timestamp: index for index, timestamp in enumerate(timestamps)}
    normalized_candidates: list[Mapping[str, Any]] = []
    for candidate in candidates:
        candidate_id = candidate.get("candidate_id")
        record = record_map.get(candidate_id)
        if record is None:
            raise StudyError(f"{dataset_id} candidate record binding mismatch")
        anchors = candidate.get("anchors")
        if not isinstance(anchors, list) or len(anchors) != 2:
            raise StudyError(f"{dataset_id} candidate anchor schema mismatch")
        try:
            source_positions = tuple(by_time[_iso_to_ns(anchor["pivot_time"])] for anchor in anchors)
        except (KeyError, TypeError, ValueError) as exc:
            raise StudyError(f"{dataset_id} candidate anchor time mismatch") from exc
        confirmations = tuple(int(value) for value in record["confirmation_positions"])
        if len(confirmations) != 2:
            raise StudyError(f"{dataset_id} confirmation schema mismatch")
        normalized_candidates.append(
            {
                "candidate_id": candidate_id,
                "candidate_structure_id": record["candidate_structure_id"],
                "role": candidate["role"],
                "first_anchor_id": record["first_anchor_id"],
                "second_anchor_id": record["second_anchor_id"],
                "source_positions": source_positions,
                "confirmation_positions": confirmations,
                "availability_position": int(record["availability_position"]),
                "record": record,
                "start_price": float(candidate["geometry"]["start_price"]),
                "end_price": float(candidate["geometry"]["end_price"]),
            }
        )
    family_membership: dict[str, frozenset[str]] = {}
    families = membership_payload.get("families", {})
    if not isinstance(families, dict):
        raise StudyError(f"{dataset_id} family membership missing")
    for family_id, entries in families.items():
        if not isinstance(entries, list):
            raise StudyError(f"{dataset_id} malformed family membership")
        family_membership[family_id] = frozenset(entry["candidate_id"] for entry in entries)
    source_hashes = {
        name: _sha256_file(folder / name)
        for name in ("provider_result.json", "candidate_records.json", "family_membership.json")
    }
    focus_membership = frozenset(
        _focus_selected_ids(normalized_candidates, len(closes) - 1)
    )
    return Dataset(
        dataset_id=dataset_id,
        asset=asset,
        timeframe=timeframe,
        interval_seconds=interval,
        timestamps=timestamps,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=volumes,
        atr=_atr14(highs, lows, closes),
        candidates=tuple(sorted(normalized_candidates, key=lambda item: item["candidate_id"])),
        records=record_map,
        family_membership=family_membership,
        source_hashes=source_hashes,
        input_identity=input_identity,
        focus_membership=focus_membership,
    )


def _source_snapshot(root: Path = SOURCE_ROOT) -> dict[str, Any]:
    return {
        relative: _sha256_file(root / "datasets" / relative)
        for relative in EXPECTED_MEMBER_HASHES
    }


def _focus_representative_sort_key(candidate: Mapping[str, Any]) -> tuple[int, int, str]:
    span = int(candidate["record"]["anchor_span_bars"])
    intermediate = max(0, span - 1)
    return (-intermediate, -span, str(candidate["candidate_id"]))


def _focus_selected_ids(
    candidates: Sequence[Mapping[str, Any]],
    last_candle_position: int,
) -> tuple[str, ...]:
    selected: list[str] = []
    for role in ROLES:
        eligible = [
            candidate
            for candidate in candidates
            if candidate["role"] == role
            and last_candle_position - int(candidate["confirmation_positions"][1]) <= FOCUS_RECENT_BARS
            and int(candidate["record"]["anchor_span_bars"]) >= FOCUS_MIN_ANCHOR_SPAN
        ]
        representatives: dict[str, Mapping[str, Any]] = {}
        for candidate in eligible:
            anchor_id = str(candidate["second_anchor_id"])
            current = representatives.get(anchor_id)
            if current is None or _focus_representative_sort_key(candidate) < _focus_representative_sort_key(current):
                representatives[anchor_id] = candidate
        ordered = sorted(
            representatives.values(),
            key=lambda candidate: (
                -int(candidate["confirmation_positions"][1]),
                *_focus_representative_sort_key(candidate),
            ),
        )
        selected.extend(str(candidate["candidate_id"]) for candidate in ordered[:FOCUS_MAX_PER_ROLE])
    return tuple(selected)


def _line_price(candidate: Mapping[str, Any], position: int) -> float:
    first, second = candidate["source_positions"]
    if second <= first:
        raise StudyError("candidate source positions are not increasing")
    fraction = (position - first) / (second - first)
    return candidate["start_price"] + fraction * (candidate["end_price"] - candidate["start_price"])


def _directional_distance(role: str, price: float, line: float) -> float:
    return price - line if role == "support" else line - price


def _body_breach(dataset: Dataset, candidate: Mapping[str, Any], position: int) -> bool:
    line = _line_price(candidate, position)
    body_low = min(dataset.opens[position], dataset.closes[position])
    body_high = max(dataset.opens[position], dataset.closes[position])
    return body_low < line if candidate["role"] == "support" else body_high > line


def _contact(dataset: Dataset, candidate: Mapping[str, Any], position: int) -> bool:
    line = _line_price(candidate, position)
    return dataset.lows[position] <= line <= dataset.highs[position]


def _episode_ranges(
    dataset: Dataset,
    candidate: Mapping[str, Any],
    contact_positions: Sequence[int],
    *,
    separation_bars: int = PRIMARY_SEPARATION_BARS,
    separation_atr: float = PRIMARY_SEPARATION_ATR,
) -> list[tuple[int, ...]]:
    if not contact_positions:
        return []
    episodes: list[list[int]] = [[contact_positions[0]]]
    for position in contact_positions[1:]:
        previous = episodes[-1][-1]
        gap = position - previous - 1
        moved = False
        for gap_position in range(previous + 1, position):
            atr = dataset.atr[gap_position]
            if atr is not None and atr > 0:
                distance = _directional_distance(
                    candidate["role"], dataset.closes[gap_position], _line_price(candidate, gap_position)
                ) / atr
                if distance >= separation_atr:
                    moved = True
                    break
        if gap >= separation_bars and moved:
            episodes.append([position])
        else:
            episodes[-1].append(position)
    return [tuple(episode) for episode in episodes]


def _reaction_summary(
    dataset: Dataset,
    candidate: Mapping[str, Any],
    first_contact: int,
    end_position: int,
) -> dict[str, Any]:
    favorable: list[float] = []
    adverse: list[float] = []
    first_breach: int | None = None
    favorable_position: int | None = None
    max_favorable = 0.0
    max_adverse = 0.0
    for position in range(first_contact + 1, end_position + 1):
        atr = dataset.atr[position]
        if atr is None or atr <= 0:
            continue
        line = _line_price(candidate, position)
        favorable_value = (
            (dataset.highs[position] - line) / atr
            if candidate["role"] == "support"
            else (line - dataset.lows[position]) / atr
        )
        adverse_value = (
            (line - dataset.lows[position]) / atr
            if candidate["role"] == "support"
            else (dataset.highs[position] - line) / atr
        )
        max_favorable = max(max_favorable, favorable_value)
        max_adverse = max(max_adverse, adverse_value)
        if first_breach is None and _body_breach(dataset, candidate, position):
            first_breach = position
        if favorable_position is None and max_favorable >= 1.0:
            favorable_position = position
        favorable.append(favorable_value)
        adverse.append(adverse_value)
    body_breach_before_favorable = (
        first_breach is not None
        and (favorable_position is None or first_breach <= favorable_position)
    )
    return {
        "maximum_favourable_excursion_atr": max_favorable,
        "maximum_adverse_penetration_atr": max_adverse,
        "first_body_breach_position": first_breach,
        "first_favourable_position": favorable_position,
        "body_breach_before_favourable": body_breach_before_favorable,
        "clean_reaction": max_favorable >= 1.0 and max_adverse <= 0.5 and not body_breach_before_favorable,
        "reaction_to_penetration_ratio": (
            max_favorable / max_adverse if max_adverse > 0 else None
        ),
    }


def _historical_interaction(
    dataset: Dataset,
    candidate: Mapping[str, Any],
    checkpoint_position: int,
    *,
    separation_bars: int = PRIMARY_SEPARATION_BARS,
    separation_atr: float = PRIMARY_SEPARATION_ATR,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    start = candidate["confirmation_positions"][1] + 1
    contacts = [position for position in range(start, checkpoint_position + 1) if _contact(dataset, candidate, position)]
    episodes = _episode_ranges(
        dataset,
        candidate,
        contacts,
        separation_bars=separation_bars,
        separation_atr=separation_atr,
    )
    episode_rows: list[dict[str, Any]] = []
    reactions: list[float] = []
    penetrations: list[float] = []
    clean_positions: list[int] = []
    for index, episode in enumerate(episodes):
        end = checkpoint_position
        if index + 1 < len(episodes):
            end = min(end, episodes[index + 1][0] - 1)
        reaction = _reaction_summary(dataset, candidate, episode[0], end)
        if reaction["maximum_favourable_excursion_atr"] > 0:
            reactions.append(reaction["maximum_favourable_excursion_atr"])
        penetrations.append(reaction["maximum_adverse_penetration_atr"])
        if reaction["clean_reaction"]:
            clean_positions.append(episode[0])
        episode_rows.append(
            {
                "dataset_id": dataset.dataset_id,
                "candidate_structure_id": candidate["candidate_structure_id"],
                "second_anchor_id": candidate["second_anchor_id"],
                "role": candidate["role"],
                "checkpoint_position": checkpoint_position,
                "first_contact_position": episode[0],
                "last_contact_position": episode[-1],
                "contact_bar_count": len(episode),
                "separation_policy": {
                    "separation_bars": separation_bars,
                    "separation_atr": separation_atr,
                },
                **reaction,
            }
        )
    history = {
        "independent_contact_episode_count": len(episodes),
        "clean_contact_episode_count": len(clean_positions),
        "median_prior_reaction_mfe_atr": statistics.median(reactions) if reactions else None,
        "median_prior_penetration_mae_atr": statistics.median(penetrations) if penetrations else None,
        "body_breach_episode_count": sum(row["first_body_breach_position"] is not None for row in episode_rows),
        "recovery_after_breach_count": sum(
            row["first_body_breach_position"] is not None
            and row["maximum_favourable_excursion_atr"] >= 1.0
            and not row["body_breach_before_favourable"]
            for row in episode_rows
        ),
        "time_since_last_clean_reaction_bars": (
            checkpoint_position - clean_positions[-1] if clean_positions else None
        ),
        "first_to_last_reaction_degradation_atr": (
            reactions[0] - reactions[-1] if len(reactions) >= 2 else None
        ),
    }
    return history, episode_rows


def _feature_row(
    dataset: Dataset,
    candidate: Mapping[str, Any],
    checkpoint_age: int,
    *,
    separation_bars: int = PRIMARY_SEPARATION_BARS,
    separation_atr: float = PRIMARY_SEPARATION_ATR,
    contact_policy_id: str = "primary_v1",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    checkpoint_position = candidate["availability_position"] + checkpoint_age
    if checkpoint_position >= len(dataset.closes) - MAX_HORIZON:
        raise StudyError("ineligible checkpoint requested")
    if any(_body_breach(dataset, candidate, position) for position in range(candidate["availability_position"] + 1, checkpoint_position + 1)):
        raise StudyError("feature row requested after exact-side invalidation")
    atr = dataset.atr[checkpoint_position]
    if atr is None or atr <= 0:
        raise StudyError("ATR unavailable at checkpoint")
    record = candidate["record"]
    line = _line_price(candidate, checkpoint_position)
    history, episodes = _historical_interaction(
        dataset,
        candidate,
        checkpoint_position,
        separation_bars=separation_bars,
        separation_atr=separation_atr,
    )
    last_contact_age = (
        checkpoint_position - episodes[-1]["last_contact_position"] if episodes else None
    )
    features = {
        "anchor_span_bars": record["anchor_span_bars"],
        "anchor_span_seconds": record["anchor_span_seconds"],
        "absolute_slope_bps_per_day": abs(record["absolute_slope_bps_per_day"]),
        "anchor_price_change_bps": abs(record["anchor_price_change_bps"]),
        "minimum_anchor_prominence_bps": record["minimum_anchor_prominence_bps"],
        "mean_anchor_prominence_bps": record["mean_anchor_prominence_bps"],
        "minimum_body_clearance_bps": record["minimum_body_clearance_bps"],
        "median_body_clearance_bps": record["median_body_clearance_bps"],
        "same_role_extrema_skip_count": record["same_role_extrema_skip_count"],
        "anchor_prominence_balance_bps": abs(record["first_anchor_prominence_bps"] - record["second_anchor_prominence_bps"]),
        "atr_normalised_slope": abs(record["slope_bps_per_day"]) / max(atr, 1e-12),
        "independent_contact_episode_count": history["independent_contact_episode_count"],
        "clean_contact_episode_count": history["clean_contact_episode_count"],
        "median_prior_reaction_mfe_atr": history["median_prior_reaction_mfe_atr"] or 0.0,
        "median_prior_penetration_mae_atr": history["median_prior_penetration_mae_atr"] or 0.0,
        "body_breach_episode_count": history["body_breach_episode_count"],
        "recovery_after_breach_count": history["recovery_after_breach_count"],
        "time_since_last_clean_reaction_bars": history["time_since_last_clean_reaction_bars"] or checkpoint_age + 1,
        "first_to_last_reaction_degradation_atr": history["first_to_last_reaction_degradation_atr"] or 0.0,
        "current_projected_distance_atr": abs(dataset.closes[checkpoint_position] - line) / atr,
        "correct_side_of_current_price": _directional_distance(candidate["role"], dataset.closes[checkpoint_position], line) >= 0,
        "availability_age_bars": checkpoint_position - candidate["availability_position"],
        "last_contact_age_bars": last_contact_age,
    }
    feature_row = {
        "feature_row_id": _identity(
            ROW_NAMESPACE,
            {
                "dataset_id": dataset.dataset_id,
                "candidate_structure_id": candidate["candidate_structure_id"],
                "second_anchor_id": candidate["second_anchor_id"],
                "checkpoint_position": checkpoint_position,
                "checkpoint_age": checkpoint_age,
                "contact_policy_id": contact_policy_id,
            },
        ),
        "dataset_id": dataset.dataset_id,
        "asset": dataset.asset,
        "timeframe": dataset.timeframe,
        "candidate_id": candidate["candidate_id"],
        "candidate_structure_id": candidate["candidate_structure_id"],
        "second_anchor_id": candidate["second_anchor_id"],
        "role": candidate["role"],
        "checkpoint_age_bars": checkpoint_age,
        "contact_policy_id": contact_policy_id,
        "checkpoint_position": checkpoint_position,
        "checkpoint_timestamp_ns": dataset.timestamps[checkpoint_position],
        "future_start_position": checkpoint_position + 1,
        "future_end_position": checkpoint_position + MAX_HORIZON,
        "features": features,
        "history": history,
        "control_flags": {
            "prior_adjacent_extrema": candidate["candidate_id"] in dataset.family_membership.get("adjacent_extrema_only_v1", frozenset()),
            "prior_latest_predecessor": candidate["candidate_id"] in dataset.family_membership.get("latest_valid_predecessor_v1", frozenset()),
            "prior_contact_span_prominence": candidate["candidate_id"] in dataset.family_membership.get("max_minimum_anchor_prominence_v1", frozenset()),
            "current_focus_selected": candidate["candidate_id"] in dataset.focus_membership,
        },
        "persistence": {
            "exact_temporal_source_opened": False,
            "lineage_persistence_available": False,
        },
    }
    return feature_row, episodes


def _future_reaction(
    dataset: Dataset,
    candidate: Mapping[str, Any],
    row: Mapping[str, Any],
    horizon: int,
    *,
    separation_bars: int = PRIMARY_SEPARATION_BARS,
    separation_atr: float = PRIMARY_SEPARATION_ATR,
) -> dict[str, Any]:
    checkpoint = int(row["checkpoint_position"])
    end = checkpoint + horizon
    positions = list(range(checkpoint + 1, end + 1))
    contacts = [position for position in positions if _contact(dataset, candidate, position)]
    episodes = _episode_ranges(
        dataset,
        candidate,
        contacts,
        separation_bars=separation_bars,
        separation_atr=separation_atr,
    )
    first = episodes[0][0] if episodes else None
    reaction = _reaction_summary(dataset, candidate, first, end) if first is not None else {
        "maximum_favourable_excursion_atr": None,
        "maximum_adverse_penetration_atr": None,
        "first_body_breach_position": None,
        "first_favourable_position": None,
        "body_breach_before_favourable": None,
        "clean_reaction": False,
        "reaction_to_penetration_ratio": None,
    }
    return {
        "future_reaction_id": _identity(
            ROW_NAMESPACE,
            {"feature_row_id": row["feature_row_id"], "horizon_bars": horizon},
        ),
        "feature_row_id": row["feature_row_id"],
        "contact_policy_id": row["contact_policy_id"],
        "dataset_id": dataset.dataset_id,
        "candidate_structure_id": row["candidate_structure_id"],
        "second_anchor_id": row["second_anchor_id"],
        "role": row["role"],
        "checkpoint_position": checkpoint,
        "horizon_bars": horizon,
        "future_start_position": checkpoint + 1,
        "future_end_position": end,
        "first_contact_position": first,
        "first_contact_offset_bars": first - checkpoint if first is not None else None,
        "second_independent_contact_exists": len(episodes) >= 2,
        "contact_episode_count": len(episodes),
        "reachability": first is not None,
        **reaction,
    }


def _rank(values: Sequence[float]) -> list[float]:
    ordered = sorted((value, index) for index, value in enumerate(values))
    result = [0.0] * len(values)
    position = 0
    while position < len(ordered):
        end = position + 1
        while end < len(ordered) and ordered[end][0] == ordered[position][0]:
            end += 1
        rank = (position + end - 1) / 2.0 + 1.0
        for _, index in ordered[position:end]:
            result[index] = rank
        position = end
    return result


def _spearman(values: Sequence[float], labels: Sequence[float]) -> tuple[float | None, float | None]:
    if len(values) != len(labels) or len(values) < 3 or len(set(values)) < 2 or len(set(labels)) < 2:
        return None, None
    result = spearmanr(values, labels)
    rho = float(result.statistic)
    p_value = float(result.pvalue)
    if not math.isfinite(rho) or not math.isfinite(p_value):
        return None, None
    return rho, p_value


def _benjamini_hochberg(values: Sequence[float | None]) -> list[float | None]:
    indexed = sorted(
        (
            index,
            value,
        )
        for index, value in enumerate(values)
        if value is not None
    )
    indexed.sort(key=lambda item: (item[1], item[0]))
    adjusted: list[float | None] = [None] * len(values)
    running = 1.0
    total = len(indexed)
    for position in range(total - 1, -1, -1):
        original_index, value = indexed[position]
        rank = position + 1
        running = min(running, float(value) * total / rank)
        adjusted[original_index] = min(1.0, running)
    return adjusted


def _average_precision(labels: Sequence[bool], scores: Sequence[float]) -> float | None:
    if not labels or sum(labels) == 0:
        return None
    order = sorted(range(len(labels)), key=lambda index: (-scores[index], index))
    positives = 0
    total = 0.0
    for rank, index in enumerate(order, 1):
        if labels[index]:
            positives += 1
            total += positives / rank
    return total / positives


def _logistic_weights(rows: Sequence[Mapping[str, Any]], feature_names: Sequence[str], labels: Sequence[bool]) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    if not rows:
        return {}, {}, {}
    means = {name: statistics.mean(float(row["features"].get(name, 0.0) or 0.0) for row in rows) for name in feature_names}
    scales = {
        name: max(
            statistics.pstdev(float(row["features"].get(name, 0.0) or 0.0) for row in rows),
            1e-9,
        )
        for name in feature_names
    }
    weights = {name: 0.0 for name in feature_names}
    intercept = 0.0
    for _ in range(60):
        gradient = {name: 0.0 for name in feature_names}
        intercept_gradient = 0.0
        for row, label in zip(rows, labels):
            vector = {
                name: (float(row["features"].get(name, 0.0) or 0.0) - means[name]) / scales[name]
                for name in feature_names
            }
            raw = intercept + sum(weights[name] * vector[name] for name in feature_names)
            probability = 1.0 / (1.0 + math.exp(max(-50.0, min(50.0, -raw))))
            error = probability - float(label)
            intercept_gradient += error
            for name in feature_names:
                gradient[name] += error * vector[name]
        intercept -= 0.08 * intercept_gradient / len(rows)
        for name in feature_names:
            gradient[name] = gradient[name] / len(rows) + 1.0 * weights[name]
            weights[name] -= 0.08 * gradient[name]
    weights["__intercept__"] = intercept
    return weights, means, scales


def _score(row: Mapping[str, Any], weights: Mapping[str, float], means: Mapping[str, float], scales: Mapping[str, float], feature_names: Sequence[str]) -> float:
    score = weights.get("__intercept__", 0.0)
    for name in feature_names:
        score += weights.get(name, 0.0) * (
            float(row["features"].get(name, 0.0) or 0.0) - means.get(name, 0.0)
        ) / scales.get(name, 1.0)
    return score


def _source_rows(
    datasets: Sequence[Dataset],
    *,
    separation_bars: int = PRIMARY_SEPARATION_BARS,
    separation_atr: float = PRIMARY_SEPARATION_ATR,
    contact_policy_id: str = "primary_v1",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    feature_rows: list[dict[str, Any]] = []
    episode_rows: list[dict[str, Any]] = []
    outcome_rows: list[dict[str, Any]] = []
    for dataset in datasets:
        for candidate in dataset.candidates:
            for age in CHECKPOINT_AGES:
                checkpoint = candidate["availability_position"] + age
                if checkpoint >= len(dataset.closes) - MAX_HORIZON:
                    continue
                if dataset.atr[checkpoint] is None or dataset.atr[checkpoint] <= 0:
                    continue
                try:
                    row, episodes = _feature_row(
                        dataset,
                        candidate,
                        age,
                        separation_bars=separation_bars,
                        separation_atr=separation_atr,
                        contact_policy_id=contact_policy_id,
                    )
                except StudyError:
                    continue
                feature_rows.append(row)
                episode_rows.extend(episodes)
                for horizon in HORIZONS:
                    outcome_rows.append(
                        _future_reaction(
                            dataset,
                            candidate,
                            row,
                            horizon,
                            separation_bars=separation_bars,
                            separation_atr=separation_atr,
                        )
                    )
    feature_rows.sort(key=lambda row: (row["dataset_id"], row["checkpoint_position"], row["role"], row["candidate_structure_id"], row["second_anchor_id"]))
    episode_rows.sort(key=lambda row: (row["dataset_id"], row["checkpoint_position"], row["role"], row["candidate_structure_id"], row["first_contact_position"]))
    outcome_rows.sort(key=lambda row: (row["dataset_id"], row["checkpoint_position"], row["horizon_bars"], row["role"], row["candidate_structure_id"]))
    return feature_rows, episode_rows, outcome_rows


FEATURE_FAMILIES = {
    "birth_structure_v1": (
        "anchor_span_bars", "anchor_span_seconds", "absolute_slope_bps_per_day",
        "anchor_price_change_bps", "minimum_anchor_prominence_bps", "mean_anchor_prominence_bps",
        "minimum_body_clearance_bps", "median_body_clearance_bps", "same_role_extrema_skip_count",
        "anchor_prominence_balance_bps", "atr_normalised_slope",
    ),
    "interaction_reaction_v1": (
        "independent_contact_episode_count", "clean_contact_episode_count",
        "median_prior_reaction_mfe_atr", "median_prior_penetration_mae_atr",
        "body_breach_episode_count", "recovery_after_breach_count",
        "time_since_last_clean_reaction_bars", "first_to_last_reaction_degradation_atr",
    ),
    "combined_quality_v1": (
        "anchor_span_bars", "absolute_slope_bps_per_day", "minimum_anchor_prominence_bps",
        "minimum_body_clearance_bps", "same_role_extrema_skip_count",
        "independent_contact_episode_count", "clean_contact_episode_count",
        "median_prior_reaction_mfe_atr", "median_prior_penetration_mae_atr",
        "body_breach_episode_count", "recovery_after_breach_count",
        "first_to_last_reaction_degradation_atr",
    ),
    "relevance_only_v1": (
        "current_projected_distance_atr", "correct_side_of_current_price",
        "availability_age_bars", "last_contact_age_bars",
    ),
    "combined_quality_plus_relevance_v1": (
        "anchor_span_bars", "absolute_slope_bps_per_day", "minimum_anchor_prominence_bps",
        "minimum_body_clearance_bps", "same_role_extrema_skip_count",
        "independent_contact_episode_count", "clean_contact_episode_count",
        "median_prior_reaction_mfe_atr", "median_prior_penetration_mae_atr",
        "body_breach_episode_count", "recovery_after_breach_count",
        "first_to_last_reaction_degradation_atr", "current_projected_distance_atr",
        "correct_side_of_current_price", "availability_age_bars", "last_contact_age_bars",
    ),
}


def _analysis_group_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row["dataset_id"]),
        str(row["role"]),
        str(row["candidate_structure_id"]),
        str(row["second_anchor_id"]),
    )


def _analysis_group_id(row: Mapping[str, Any]) -> str:
    dataset_id, role, structure_id, second_anchor_id = _analysis_group_key(row)
    return _identity(
        GROUP_NAMESPACE,
        {
            "dataset_id": dataset_id,
            "role": role,
            "candidate_structure_id": structure_id,
            "second_anchor_id": second_anchor_id,
        },
    )


def _select_analysis_rows(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_analysis_group_key(row)].append(row)
    selected: list[Mapping[str, Any]] = []
    for group_key, group_rows in grouped.items():
        chosen = sorted(
            group_rows,
            key=lambda row: (
                -int(row["checkpoint_age_bars"]),
                -int(row["checkpoint_position"]),
                str(row["feature_row_id"]),
            ),
        )[0]
        selected.append(
            {
                **chosen,
                "analysis_group_id": _analysis_group_id(chosen),
            }
        )
    return sorted(selected, key=lambda row: _analysis_group_key(row) + (row["feature_row_id"],))


def _group_rows(
    rows: Sequence[Mapping[str, Any]],
    outcomes: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[list[Mapping[str, Any]], list[bool]]:
    """Select one row per analysis group before optional label inspection."""
    selected = _select_analysis_rows(rows)
    if outcomes is None:
        return selected, []
    reachable = [
        row
        for row in selected
        if row["feature_row_id"] in outcomes and outcomes[row["feature_row_id"]]["reachability"]
    ]
    labels = [bool(outcomes[row["feature_row_id"]]["clean_reaction"]) for row in reachable]
    return reachable, labels


def _control_score(row: Mapping[str, Any], control: str) -> float:
    if control == "hash_order_control_v1":
        return -int(row["candidate_id"][:16], 16)
    if control == "nearest_current_price_control_v1":
        return -float(row["features"]["current_projected_distance_atr"])
    if control == "current_focus_policy_control_v1":
        return 1.0 if row["control_flags"]["current_focus_selected"] else 0.0
    if control == "prior_structural_selection_control_v1":
        return 1.0 if row["control_flags"]["prior_latest_predecessor"] else 0.0
    if control == "prior_contact_span_prominence_control_v1":
        return 1.0 if row["control_flags"]["prior_contact_span_prominence"] else 0.0
    raise StudyError(f"unknown control: {control}")


CONTROLS = (
    "hash_order_control_v1",
    "nearest_current_price_control_v1",
    "current_focus_policy_control_v1",
    "prior_structural_selection_control_v1",
    "prior_contact_span_prominence_control_v1",
)


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _bootstrap_seed(family_id: str, dataset_id: str) -> int:
    seed_id = _identity(
        f"{STUDY_SCHEMA}_bootstrap_seed",
        {"family_id": family_id, "dataset_id": dataset_id},
    )
    return int(seed_id[:16], 16)


def _bootstrap_samples(
    labels: Sequence[bool],
    scores: Sequence[float],
    seed: int,
) -> tuple[list[float | None], int, int]:
    if len(labels) != len(scores) or not labels:
        return [None] * BOOTSTRAP_REPLICATES, 0, BOOTSTRAP_REPLICATES
    order = sorted(range(len(labels)), key=lambda index: (-scores[index], index))
    counts = [0] * len(labels)
    rng = random.Random(seed)
    samples: list[float | None] = []
    invalid = 0
    for _ in range(BOOTSTRAP_REPLICATES):
        touched: list[int] = []
        positive_count = 0
        for _ in range(len(labels)):
            index = rng.randrange(len(labels))
            if counts[index] == 0:
                touched.append(index)
            counts[index] += 1
            positive_count += int(labels[index])
        if positive_count == 0 or positive_count == len(labels):
            samples.append(None)
            invalid += 1
        else:
            cumulative = 0
            positives = 0
            precision_sum = 0.0
            for index in order:
                repetitions = counts[index]
                if repetitions == 0:
                    continue
                if labels[index]:
                    for _ in range(repetitions):
                        cumulative += 1
                        positives += 1
                        precision_sum += positives / cumulative
                else:
                    cumulative += repetitions
            samples.append(precision_sum / positive_count)
        for index in touched:
            counts[index] = 0
    return samples, BOOTSTRAP_REPLICATES - invalid, invalid


def _bootstrap_summary(
    labels: Sequence[bool],
    scores: Sequence[float],
    seed: int,
) -> dict[str, Any]:
    samples, valid, invalid = _bootstrap_samples(labels, scores, seed)
    valid_values = [value for value in samples if value is not None]
    return {
        "point_estimate": _average_precision(labels, scores),
        "interval_95": [
            _percentile(valid_values, (1.0 - BOOTSTRAP_CONFIDENCE_LEVEL) / 2.0),
            _percentile(valid_values, 1.0 - (1.0 - BOOTSTRAP_CONFIDENCE_LEVEL) / 2.0),
        ] if valid_values else None,
        "valid_replicates": valid,
        "invalid_replicates": invalid,
        "inference_sufficient": valid >= BOOTSTRAP_MIN_VALID,
        "seed": seed,
        "samples": samples,
    }


def _paired_bootstrap_summary(
    labels: Sequence[bool],
    scores: Sequence[float],
    baseline_scores: Sequence[float],
    seed: int,
) -> dict[str, Any]:
    family_samples, valid, invalid = _bootstrap_samples(labels, scores, seed)
    baseline_samples, baseline_valid, baseline_invalid = _bootstrap_samples(
        labels,
        baseline_scores,
        seed,
    )
    deltas = [
        family - baseline if family is not None and baseline is not None else None
        for family, baseline in zip(family_samples, baseline_samples)
    ]
    valid_deltas = [value for value in deltas if value is not None]
    family_values = [value for value in family_samples if value is not None]
    valid_replicates = len(valid_deltas)
    return {
        "point_estimate": _average_precision(labels, scores),
        "interval_95": [
            _percentile(family_values, 0.025),
            _percentile(family_values, 0.975),
        ] if family_values else None,
        "delta_point_estimate": (
            _average_precision(labels, scores) - _average_precision(labels, baseline_scores)
            if _average_precision(labels, scores) is not None and _average_precision(labels, baseline_scores) is not None
            else None
        ),
        "delta_interval_95": [
            _percentile(valid_deltas, (1.0 - BOOTSTRAP_CONFIDENCE_LEVEL) / 2.0),
            _percentile(valid_deltas, 1.0 - (1.0 - BOOTSTRAP_CONFIDENCE_LEVEL) / 2.0),
        ] if valid_deltas else None,
        "valid_replicates": valid_replicates,
        "invalid_replicates": BOOTSTRAP_REPLICATES - valid_replicates,
        "inference_sufficient": valid_replicates >= BOOTSTRAP_MIN_VALID,
        "seed": seed,
        "delta_samples": deltas,
    }


def _pooled_delta_summary(
    delta_samples_by_dataset: Mapping[str, Sequence[float | None]],
    delta_points_by_dataset: Mapping[str, float | None],
) -> dict[str, Any]:
    pooled_samples: list[float | None] = []
    for replicate in range(BOOTSTRAP_REPLICATES):
        values = [
            delta_samples_by_dataset[dataset_id][replicate]
            for dataset_id in VALIDATION_DATASETS
        ]
        pooled_samples.append(
            statistics.mean(values) if all(value is not None for value in values) else None
        )
    valid_values = [value for value in pooled_samples if value is not None]
    valid = len(valid_values)
    return {
        "point_estimate": statistics.mean(
            delta_points_by_dataset[dataset_id]
            for dataset_id in VALIDATION_DATASETS
            if delta_points_by_dataset[dataset_id] is not None
        ),
        "interval_95": [
            _percentile(valid_values, 0.025),
            _percentile(valid_values, 0.975),
        ] if valid_values else None,
        "valid_replicates": valid,
        "invalid_replicates": BOOTSTRAP_REPLICATES - valid,
        "inference_sufficient": valid >= BOOTSTRAP_MIN_VALID,
        "samples": pooled_samples,
    }


def _analysis_summary(feature_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    selected = _select_analysis_rows(feature_rows)
    age_counts: dict[str, int] = defaultdict(int)
    for row in selected:
        age_counts[str(row["checkpoint_age_bars"])] += 1
    return {
        "source_checkpoint_rows": len(feature_rows),
        "analysis_group_count": len(selected),
        "selected_analysis_rows": len(selected),
        "discarded_repeated_row_count": len(feature_rows) - len(selected),
        "selected_checkpoint_age_distribution": dict(sorted(age_counts.items())),
        "selected_rows": [
            {
                "analysis_group_id": row["analysis_group_id"],
                "dataset_id": row["dataset_id"],
                "role": row["role"],
                "candidate_structure_id": row["candidate_structure_id"],
                "second_anchor_id": row["second_anchor_id"],
                "candidate_id": row["candidate_id"],
                "feature_row_id": row["feature_row_id"],
                "checkpoint_age_bars": row["checkpoint_age_bars"],
                "checkpoint_position": row["checkpoint_position"],
            }
            for row in selected
        ],
    }


def _evaluate_models(
    feature_rows: Sequence[Mapping[str, Any]],
    outcome_rows: Sequence[Mapping[str, Any]],
    datasets: Sequence[Dataset],
) -> dict[str, Any]:
    primary_outcomes = {
        row["feature_row_id"]: row
        for row in outcome_rows
        if row["horizon_bars"] == 24
    }
    analysis_rows = _select_analysis_rows(feature_rows)
    analysis_by_dataset = {
        dataset_id: [row for row in analysis_rows if row["dataset_id"] == dataset_id]
        for dataset_id in VALIDATION_DATASETS
    }
    validation: list[dict[str, Any]] = []
    fold_inputs: dict[tuple[str, str], tuple[list[bool], list[float], list[Mapping[str, Any]]]] = {}
    for family_id, feature_names in FEATURE_FAMILIES.items():
        for target_dataset in VALIDATION_DATASETS:
            train_rows = [row for row in analysis_rows if row["dataset_id"] != target_dataset]
            test_rows = analysis_by_dataset[target_dataset]
            grouped_train, grouped_labels = _group_rows(train_rows, primary_outcomes)
            weights, means, scales = _logistic_weights(grouped_train, feature_names, grouped_labels)
            reached = [
                row
                for row in test_rows
                if primary_outcomes.get(row["feature_row_id"], {}).get("reachability")
            ]
            labels = [bool(primary_outcomes[row["feature_row_id"]]["clean_reaction"]) for row in reached]
            scores = [_score(row, weights, means, scales, feature_names) for row in reached]
            ap = _average_precision(labels, scores)
            top_count = max(1, math.ceil(len(reached) * 0.2)) if reached else 0
            ranked = sorted(range(len(reached)), key=lambda index: (-scores[index], index))
            top_indices = ranked[:top_count]
            top_breach = (
                sum(
                    bool(primary_outcomes[reached[index]["feature_row_id"]]["body_breach_before_favourable"])
                    for index in top_indices
                ) / len(top_indices)
                if top_indices else None
            )
            fold_inputs[(family_id, target_dataset)] = (labels, scores, reached)
            validation.append({
                "family_id": family_id,
                "target_dataset": target_dataset,
                "timeframe": target_dataset.split("_", 1)[1],
                "analysis_group_count": len(test_rows),
                "evaluated_reached_contact_rows": len(reached),
                "positive_clean_reaction_rows": sum(labels),
                "conditional_reaction_average_precision": ap,
                "top_quality_quantile": 0.2,
                "top_quality_body_breach_rate": top_breach,
                "fixed_model": "grouped_logistic_l2_v1",
                "feature_names": list(feature_names),
            })
    baseline_scores_by_dataset = {
        dataset_id: fold_inputs[("birth_structure_v1", dataset_id)][1]
        for dataset_id in VALIDATION_DATASETS
    }
    bootstrap_by_family_dataset: dict[tuple[str, str], dict[str, Any]] = {}
    for item in validation:
        family_id = item["family_id"]
        dataset_id = item["target_dataset"]
        labels, scores, _ = fold_inputs[(family_id, dataset_id)]
        if family_id == "birth_structure_v1":
            bootstrap = _bootstrap_summary(labels, scores, _bootstrap_seed(family_id, dataset_id))
            item.update({
                "ap_point_estimate": bootstrap["point_estimate"],
                "ap_95_interval": bootstrap["interval_95"],
                "ap_delta_vs_birth_structure": 0.0,
                "ap_delta_95_interval": [0.0, 0.0],
                "bootstrap_valid_replicates": bootstrap["valid_replicates"],
                "bootstrap_invalid_replicates": bootstrap["invalid_replicates"],
                "bootstrap_inference_sufficient": bootstrap["inference_sufficient"],
                "bootstrap_seed": bootstrap["seed"],
            })
        else:
            baseline_scores = baseline_scores_by_dataset[dataset_id]
            bootstrap = _paired_bootstrap_summary(
                labels,
                scores,
                baseline_scores,
                _bootstrap_seed(family_id, dataset_id),
            )
            item.update({
                "ap_point_estimate": bootstrap["point_estimate"],
                "ap_95_interval": bootstrap["interval_95"],
                "ap_delta_vs_birth_structure": bootstrap["delta_point_estimate"],
                "ap_delta_95_interval": bootstrap["delta_interval_95"],
                "bootstrap_valid_replicates": bootstrap["valid_replicates"],
                "bootstrap_invalid_replicates": bootstrap["invalid_replicates"],
                "bootstrap_inference_sufficient": bootstrap["inference_sufficient"],
                "bootstrap_seed": bootstrap["seed"],
            })
        bootstrap_by_family_dataset[(family_id, dataset_id)] = bootstrap
    pooled: list[dict[str, Any]] = []
    for family_id in FEATURE_FAMILIES:
        if family_id == "birth_structure_v1":
            pooled.append({
                "family_id": family_id,
                "pooled_ap_point_estimate": statistics.mean(
                    _average_precision(*fold_inputs[(family_id, dataset_id)][:2])
                    for dataset_id in VALIDATION_DATASETS
                ),
                "pooled_ap_delta_vs_birth_structure": 0.0,
                "pooled_ap_delta_95_interval": [0.0, 0.0],
                "bootstrap_valid_replicates": BOOTSTRAP_REPLICATES,
                "bootstrap_invalid_replicates": 0,
                "bootstrap_inference_sufficient": True,
            })
            continue
        summary = _pooled_delta_summary(
            {
                dataset_id: bootstrap_by_family_dataset[(family_id, dataset_id)]["delta_samples"]
                for dataset_id in VALIDATION_DATASETS
            },
            {
                dataset_id: bootstrap_by_family_dataset[(family_id, dataset_id)]["delta_point_estimate"]
                for dataset_id in VALIDATION_DATASETS
            },
        )
        pooled.append({
            "family_id": family_id,
            "pooled_ap_point_estimate": statistics.mean(
                fold_inputs[(family_id, dataset_id)][0] and _average_precision(
                    fold_inputs[(family_id, dataset_id)][0], fold_inputs[(family_id, dataset_id)][1]
                ) or 0.0
                for dataset_id in VALIDATION_DATASETS
            ),
            "pooled_ap_delta_vs_birth_structure": summary["point_estimate"],
            "pooled_ap_delta_95_interval": summary["interval_95"],
            "bootstrap_valid_replicates": summary["valid_replicates"],
            "bootstrap_invalid_replicates": summary["invalid_replicates"],
            "bootstrap_inference_sufficient": summary["inference_sufficient"] and all(
                item["bootstrap_inference_sufficient"]
                for item in validation
                if item["family_id"] == family_id
            ),
        })
    controls: list[dict[str, Any]] = []
    focus_audit: list[dict[str, Any]] = []
    datasets_by_id = {dataset.dataset_id: dataset for dataset in datasets}
    for dataset_id in VALIDATION_DATASETS:
        selected_ids = sorted(datasets_by_id[dataset_id].focus_membership)
        focus_audit.append({
            "dataset_id": dataset_id,
            "settings": {
                "recentBars": FOCUS_RECENT_BARS,
                "minAnchorSpan": FOCUS_MIN_ANCHOR_SPAN,
                "onePerSecondAnchor": True,
                "maxPerRole": FOCUS_MAX_PER_ROLE,
            },
            "selected_count": len(selected_ids),
            "selected_candidate_ids": selected_ids,
            "membership_hash": _identity(
                f"{STUDY_SCHEMA}_focus_membership",
                {"dataset_id": dataset_id, "candidate_ids": selected_ids},
            ),
        })
        for control in CONTROLS:
            reached = [
                row
                for row in analysis_by_dataset[dataset_id]
                if primary_outcomes.get(row["feature_row_id"], {}).get("reachability")
            ]
            labels = [bool(primary_outcomes[row["feature_row_id"]]["clean_reaction"]) for row in reached]
            scores = [_control_score(row, control) for row in reached]
            controls.append({
                "control_id": control,
                "target_dataset": dataset_id,
                "analysis_group_count": len(analysis_by_dataset[dataset_id]),
                "evaluated_reached_contact_rows": len(reached),
                "positive_clean_reaction_rows": sum(labels),
                "conditional_reaction_average_precision": _average_precision(labels, scores),
                "focus_membership_hash": next(
                    item["membership_hash"] for item in focus_audit if item["dataset_id"] == dataset_id
                ),
            })
    chronological: list[dict[str, Any]] = []
    for family_id, feature_names in FEATURE_FAMILIES.items():
        for dataset_id in VALIDATION_DATASETS:
            rows = analysis_by_dataset[dataset_id]
            if not rows:
                continue
            midpoint = statistics.median(row["checkpoint_position"] for row in rows)
            train_rows = [row for row in rows if row["checkpoint_position"] <= midpoint]
            test_rows = [row for row in rows if row["checkpoint_position"] > midpoint]
            train_ids = {row["analysis_group_id"] for row in train_rows}
            test_ids = {row["analysis_group_id"] for row in test_rows}
            overlap = sorted(train_ids & test_ids)
            if overlap:
                raise StudyError("chronological analysis groups overlap")
            grouped_train, grouped_labels = _group_rows(train_rows, primary_outcomes)
            weights, means, scales = _logistic_weights(grouped_train, feature_names, grouped_labels)
            reached = [
                row
                for row in test_rows
                if primary_outcomes.get(row["feature_row_id"], {}).get("reachability")
            ]
            labels = [bool(primary_outcomes[row["feature_row_id"]]["clean_reaction"]) for row in reached]
            scores = [_score(row, weights, means, scales, feature_names) for row in reached]
            chronological.append({
                "family_id": family_id,
                "dataset_id": dataset_id,
                "early_train_rows": len(train_rows),
                "late_test_rows": len(test_rows),
                "late_test_reached_contact_rows": len(reached),
                "late_conditional_reaction_average_precision": _average_precision(labels, scores),
                "train_group_ids": sorted(train_ids),
                "test_group_ids": sorted(test_ids),
                "group_overlap_count": len(overlap),
            })
    chrono_baseline = {
        item["dataset_id"]: item["late_conditional_reaction_average_precision"]
        for item in chronological
        if item["family_id"] == "birth_structure_v1"
    }
    for item in chronological:
        baseline_ap = chrono_baseline.get(item["dataset_id"])
        item["late_ap_improvement_vs_birth_structure"] = (
            item["late_conditional_reaction_average_precision"] - baseline_ap
            if item["family_id"] != "birth_structure_v1"
            and item["late_conditional_reaction_average_precision"] is not None
            and baseline_ap is not None
            else 0.0 if item["family_id"] == "birth_structure_v1" else None
        )
    return {
        "schema_version": STUDY_SCHEMA + "_model_validation_v2",
        "primary_horizon_bars": 24,
        "target": "clean_reaction",
        "validation_method": "leave_one_dataset_out_and_chronological_early_to_late_v2",
        "grouping": "dataset + role + candidate_structure_id + second_anchor_id",
        "bootstrap": {
            "replicates": BOOTSTRAP_REPLICATES,
            "confidence_level": BOOTSTRAP_CONFIDENCE_LEVEL,
            "sampling_unit": "analysis_group",
            "sampling": "paired_within_target_dataset",
            "minimum_valid_replicates": BOOTSTRAP_MIN_VALID,
        },
        "analysis": _analysis_summary(feature_rows),
        "families": validation,
        "pooled": pooled,
        "controls": controls,
        "current_focus_membership_audit": focus_audit,
        "chronological": chronological,
    }


def _feature_associations(feature_rows: Sequence[Mapping[str, Any]], outcome_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_id = {row["feature_row_id"]: row for row in outcome_rows if row["horizon_bars"] == 24 and row["reachability"]}
    analysis_rows = _select_analysis_rows(feature_rows)
    associations: list[dict[str, Any]] = []
    for family_id, feature_names in FEATURE_FAMILIES.items():
        for dataset_id in VALIDATION_DATASETS:
            rows = [
                row
                for row in analysis_rows
                if row["dataset_id"] == dataset_id and row["feature_row_id"] in by_id
            ]
            labels = [float(bool(by_id[row["feature_row_id"]]["clean_reaction"])) for row in rows]
            for feature_name in feature_names:
                values = [float(row["features"].get(feature_name, 0.0) or 0.0) for row in rows]
                correlation, p_value = _spearman(values, labels)
                associations.append({
                    "family_id": family_id,
                    "dataset_id": dataset_id,
                    "feature": feature_name,
                    "sample_count": len(values),
                    "spearman_rho": correlation,
                    "raw_p_value": p_value,
                })
    adjusted = _benjamini_hochberg([item["raw_p_value"] for item in associations])
    for item, value in zip(associations, adjusted):
        item["bh_adjusted_p_value"] = value
    return {
        "schema_version": STUDY_SCHEMA + "_feature_associations_v1",
        "correction": "benjamini_hochberg_v1",
        "rows": sorted(associations, key=lambda item: (item["family_id"], item["dataset_id"], item["feature"])),
    }


def _feature_ablation(model_validation: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in model_validation["families"]:
        if item["family_id"] in {"combined_quality_v1", "combined_quality_plus_relevance_v1", "birth_structure_v1"}:
            rows.append({
                "family_id": item["family_id"],
                "target_dataset": item["target_dataset"],
                "conditional_reaction_average_precision": item["conditional_reaction_average_precision"],
                "relevance_removed": item["family_id"] == "combined_quality_v1",
                "interaction_removed": item["family_id"] == "birth_structure_v1",
            })
    return {
        "schema_version": STUDY_SCHEMA + "_feature_ablation_v1",
        "interpretation": "diagnostic_only; relevance cannot establish intrinsic quality",
        "rows": rows,
    }


def _model_family_summaries(model_validation: Mapping[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for family_id in FEATURE_FAMILIES:
        family_rows = [item for item in model_validation["families"] if item["family_id"] == family_id]
        chrono_rows = [item for item in model_validation["chronological"] if item["family_id"] == family_id]
        summaries.append({
            "family_id": family_id,
            "per_dataset_ap": {
                item["target_dataset"]: item["conditional_reaction_average_precision"]
                for item in family_rows
            },
            "per_dataset_ap_delta_vs_birth_structure": {
                item["target_dataset"]: item.get("ap_delta_vs_birth_structure")
                for item in family_rows
            },
            "pooled_ap_delta_vs_birth_structure": next(
                item["pooled_ap_delta_vs_birth_structure"]
                for item in model_validation["pooled"]
                if item["family_id"] == family_id
            ),
            "pooled_ap_delta_95_interval": next(
                item["pooled_ap_delta_95_interval"]
                for item in model_validation["pooled"]
                if item["family_id"] == family_id
            ),
            "chronological_ap_delta_vs_birth_structure": {
                item["dataset_id"]: item.get("late_ap_improvement_vs_birth_structure")
                for item in chrono_rows
            },
        })
    return summaries


def _sensitivity_summary(
    datasets: Sequence[Dataset],
    primary_feature_rows: Sequence[Mapping[str, Any]],
    primary_model_validation: Mapping[str, Any],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    definitions = (
        {
            "id": "primary_v1",
            "separation_bars": PRIMARY_SEPARATION_BARS,
            "separation_atr": PRIMARY_SEPARATION_ATR,
        },
        *SENSITIVITY_DEFINITIONS,
    )
    for definition in definitions:
        if definition["id"] == "primary_v1":
            feature_rows = primary_feature_rows
            model_validation = primary_model_validation
        else:
            feature_rows, _, outcome_rows = _source_rows(
                datasets,
                separation_bars=definition["separation_bars"],
                separation_atr=definition["separation_atr"],
                contact_policy_id=definition["id"],
            )
            model_validation = _evaluate_models(feature_rows, outcome_rows, datasets)
        episode_count = sum(
            int(row["history"]["independent_contact_episode_count"])
            for row in feature_rows
            if row["checkpoint_age_bars"] == 24
        )
        clean_count = sum(
            int(row["history"]["clean_contact_episode_count"])
            for row in feature_rows
            if row["checkpoint_age_bars"] == 24
        )
        rows.append({
            "definition_id": definition["id"],
            "separation_bars": definition["separation_bars"],
            "separation_atr": definition["separation_atr"],
            "contact_episode_count": episode_count,
            "clean_contact_episode_count": clean_count,
            "clean_rate": clean_count / episode_count if episode_count else None,
            "model_family_results": _model_family_summaries(model_validation),
        })
    return {
        "schema_version": STUDY_SCHEMA + "_contact_sensitivity_v2",
        "primary_definition_id": "primary_v1",
        "rows": rows,
    }


def _validation_lock(source_binding: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": STUDY_SCHEMA + "_validation_lock_v1",
        "status": "LOCKED_VALIDATION_ONLY",
        "source_binding_id": source_binding["source_binding_id"],
        "validation_datasets": list(VALIDATION_DATASETS),
        "holdout_datasets": list(HOLDOUT_DATASETS),
        "temporal_status": "NOT_OPENED_BEFORE_VALIDATION_LOCK",
        "locked_feature_families": list(FEATURE_FAMILIES),
        "analysis_group_identity": [
            "dataset_id",
            "role",
            "candidate_structure_id",
            "second_anchor_id",
        ],
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "bootstrap_min_valid_replicates": BOOTSTRAP_MIN_VALID,
        "checkpoint_ages": list(CHECKPOINT_AGES),
        "horizons": list(HORIZONS),
    }
    return {**payload, "validation_lock_id": _identity(LOCK_NAMESPACE, payload)}


def _decision(
    model_validation: Mapping[str, Any],
    source_binding: Mapping[str, Any],
    sensitivity: Mapping[str, Any],
    feature_rows: Sequence[Mapping[str, Any]],
    outcome_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    baseline = {
        item["target_dataset"]: item
        for item in model_validation["families"]
        if item["family_id"] == "birth_structure_v1"
    }
    reached_by_lane: dict[tuple[str, str], int] = defaultdict(int)
    analysis_rows = _select_analysis_rows(feature_rows)
    primary_outcomes = {
        row["feature_row_id"]: row
        for row in outcome_rows
        if row["horizon_bars"] == 24
    }
    for row in analysis_rows:
        outcome = primary_outcomes.get(row["feature_row_id"])
        if outcome is not None and outcome["reachability"]:
            reached_by_lane[(row["dataset_id"], row["role"])] += 1
    source_reconciliation_zero = True
    chronological_overlap_zero = all(
        item["group_overlap_count"] == 0 for item in model_validation["chronological"]
    )
    family_results: list[dict[str, Any]] = []
    feasible = False
    inference_insufficient = False
    for family_id in FEATURE_FAMILIES:
        rows = [item for item in model_validation["families"] if item["family_id"] == family_id]
        family_summary = next(item for item in model_validation["pooled"] if item["family_id"] == family_id)
        improvements = {
            item["target_dataset"]: item.get("ap_delta_vs_birth_structure")
            for item in rows
        }
        bootstrap_sufficient = bool(family_summary["bootstrap_inference_sufficient"]) and all(
            item["bootstrap_inference_sufficient"] for item in rows
        )
        if family_id in INTRINSIC_QUALITY_FAMILIES:
            inference_insufficient = inference_insufficient or not bootstrap_sufficient
        pooled_delta = family_summary["pooled_ap_delta_vs_birth_structure"]
        pooled_interval = family_summary["pooled_ap_delta_95_interval"]
        point_ap_gate = pooled_delta is not None and pooled_delta >= 0.03
        lower_bound_gate = pooled_interval is not None and pooled_interval[0] > 0
        dataset_gate = all(value is not None and value >= 0 for value in improvements.values())
        breach_increases = {
            item["target_dataset"]: (
                item["top_quality_body_breach_rate"]
                - baseline[item["target_dataset"]]["top_quality_body_breach_rate"]
                if item["top_quality_body_breach_rate"] is not None
                and baseline[item["target_dataset"]]["top_quality_body_breach_rate"] is not None
                else None
            )
            for item in rows
        }
        breach_values = [value for value in breach_increases.values() if value is not None]
        breach_gate = bool(breach_values) and max(breach_values) <= 0.02
        timeframe_values: dict[str, list[float]] = defaultdict(list)
        for item in rows:
            value = improvements.get(item["target_dataset"])
            if value is not None:
                timeframe_values[item["timeframe"]].append(value)
        timeframe_gate = all(
            timeframe in timeframe_values and statistics.mean(values) >= 0
            for timeframe in ("1h", "4h")
            for values in [timeframe_values.get(timeframe, [])]
        )
        chrono_rows = [item for item in model_validation["chronological"] if item["family_id"] == family_id]
        chrono_improvements = {
            item["dataset_id"]: item.get("late_ap_improvement_vs_birth_structure")
            for item in chrono_rows
        }
        chrono_gate = all(value is not None and value >= 0 for value in chrono_improvements.values())
        sensitivity_improvements = {
            item["definition_id"]: next(
                family["pooled_ap_delta_vs_birth_structure"]
                for family in item["model_family_results"]
                if family["family_id"] == family_id
            )
            for item in sensitivity["rows"]
            if item["definition_id"] != "primary_v1"
        }
        sensitivity_gate = all(
            value is not None and value >= 0 for value in sensitivity_improvements.values()
        )
        relevance_free_gate = family_id in INTRINSIC_QUALITY_FAMILIES
        gate_values = {
            "bootstrap_inference_sufficient": bootstrap_sufficient,
            "pooled_ap_improvement_at_least_0_03": point_ap_gate,
            "pooled_paired_ap_lower_bound_positive": lower_bound_gate,
            "all_dataset_ap_improvements_nonnegative": dataset_gate,
            "worst_dataset_top_quantile_breach_increase_at_most_0_02": breach_gate,
            "mean_improvement_nonnegative_by_timeframe": timeframe_gate,
            "chronological_improvement_nonnegative_every_dataset": chrono_gate,
            "sensitivity_pooled_improvement_nonnegative": sensitivity_gate,
            "relevance_free_quality_family": relevance_free_gate,
            "source_and_reconciliation_zero": source_reconciliation_zero,
            "chronological_group_overlap_zero": chronological_overlap_zero,
        }
        passes = relevance_free_gate and all(gate_values.values())
        feasible = feasible or passes
        family_results.append({
            "family_id": family_id,
            "eligible_for_feasibility": relevance_free_gate,
            "diagnostic_only": family_id in DIAGNOSTIC_FAMILIES,
            "pooled_ap_improvement_vs_birth_structure": pooled_delta,
            "pooled_ap_delta_95_interval": pooled_interval,
            "per_dataset_ap_improvements": improvements,
            "top_quantile_breach_increases": breach_increases,
            "chronological_ap_improvements": chrono_improvements,
            "sensitivity_pooled_ap_improvements": sensitivity_improvements,
            "gate_results": gate_values,
            "passes_feasibility": passes,
        })
    if not source_reconciliation_zero or not chronological_overlap_zero:
        status = "QUALITY_EVIDENCE_INCOMPLETE"
    elif inference_insufficient or not all(reached_by_lane.get((dataset_id, role), 0) > 0 for dataset_id in VALIDATION_DATASETS for role in ROLES):
        status = "INSUFFICIENT_REACTION_EVENTS"
    else:
        status = "QUALITY_SIGNAL_FEASIBLE" if feasible else "NO_ROBUST_QUALITY_SIGNAL"
    payload = {
        "schema_version": STUDY_SCHEMA + "_decision_v2",
        "status": status,
        "finalist": None,
        "interpretation": "research_evidence_only; no production selector, viewer default, YAML or runtime implication",
        "source_binding_id": source_binding["source_binding_id"],
        "family_results": family_results,
        "sensitivity": sensitivity,
        "analysis_group_count": len(analysis_rows),
        "chronological_group_overlap_count": sum(
            item["group_overlap_count"] for item in model_validation["chronological"]
        ),
        "reached_contact_counts_by_dataset_role": {
            f"{dataset_id}:{role}": reached_by_lane.get((dataset_id, role), 0)
            for dataset_id in VALIDATION_DATASETS
            for role in ROLES
        },
        "temporal_status": "NOT_OPENED_BEFORE_VALIDATION_LOCK",
        "holdout_status": "UNOPENED_PHASE_12Q2",
        "unresolved_reconciliation_count": 0,
    }
    return {**payload, "decision_id": _identity(DECISION_NAMESPACE, payload)}


def _source_binding(manifest: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return _source_binding_for_root(manifest, snapshot, SOURCE_ROOT)


def _source_binding_for_root(manifest: Mapping[str, Any], snapshot: Mapping[str, Any], root: Path) -> dict[str, Any]:
    member_count = manifest.get("member_count", manifest.get("source_manifest_member_count"))
    if member_count != 37:
        raise StudyError("source manifest member count binding mismatch")
    payload = {
        "schema_version": STUDY_SCHEMA + "_source_binding_v1",
        "source_root": str(root),
        "source_decision_id": SOURCE_DECISION_ID,
        "source_manifest_id": SOURCE_MANIFEST_ID,
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "underlying_source_inventory_sha256": UNDERLYING_SOURCE_INVENTORY_SHA256,
        "validation_datasets": list(VALIDATION_DATASETS),
        "holdout_datasets": list(HOLDOUT_DATASETS),
        "member_hashes": dict(sorted(snapshot.items())),
        "source_manifest_member_count": member_count,
    }
    return {**payload, "source_binding_id": _identity(SOURCE_NAMESPACE, payload)}


def _contract() -> dict[str, Any]:
    payload = {
        "schema_version": STUDY_SCHEMA + "_contract",
        "source_decision_id": SOURCE_DECISION_ID,
        "source_manifest_id": SOURCE_MANIFEST_ID,
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "underlying_source_inventory_sha256": UNDERLYING_SOURCE_INVENTORY_SHA256,
        "validation_datasets": list(VALIDATION_DATASETS),
        "holdout_datasets": list(HOLDOUT_DATASETS),
        "checkpoint_ages": list(CHECKPOINT_AGES),
        "horizons": list(HORIZONS),
        "contact_episode_policy": {
            "contact": "low <= projected line <= high",
            "consecutive_contact_candles_one_episode": True,
            "separation_bars": PRIMARY_SEPARATION_BARS,
            "separation_atr": PRIMARY_SEPARATION_ATR,
            "sensitivity": list(SENSITIVITY_DEFINITIONS),
        },
        "atr_policy": "causal_wilder_atr_14_v1",
        "future_label_policy": "strictly_after_checkpoint_v1",
        "feature_families": {key: list(value) for key, value in FEATURE_FAMILIES.items()},
        "controls": list(CONTROLS),
        "model": "fixed_grouped_logistic_l2_v1",
        "analysis_group_identity": [
            "dataset_id",
            "role",
            "candidate_structure_id",
            "second_anchor_id",
        ],
        "bootstrap": {
            "replicates": BOOTSTRAP_REPLICATES,
            "confidence_level": BOOTSTRAP_CONFIDENCE_LEVEL,
            "sampling_unit": "analysis_group",
            "sampling": "paired_within_target_dataset",
            "minimum_valid_replicates": BOOTSTRAP_MIN_VALID,
        },
        "focus_control": {
            "recentBars": FOCUS_RECENT_BARS,
            "minAnchorSpan": FOCUS_MIN_ANCHOR_SPAN,
            "onePerSecondAnchor": True,
            "maxPerRole": FOCUS_MAX_PER_ROLE,
        },
        "gates": {
            "minimum_ap_improvement": 0.03,
            "pooled_paired_ap_lower_bound_positive": True,
            "maximum_top_quantile_body_breach_increase": 0.02,
            "direction_stable_timeframes": ["1h", "4h"],
            "chronological_improvement_nonnegative": True,
            "sensitivity_pooled_improvement_nonnegative": True,
            "intrinsic_quality_families_only": list(INTRINSIC_QUALITY_FAMILIES),
        },
        "temporal_access": "conditional_only_after_validation_quality_lock",
        "provider_execution_count": 0,
        "network_request_count": 0,
    }
    return {**payload, "contract_id": _identity(CONTRACT_NAMESPACE, payload)}


def _derive_evidence(source_root: Path = SOURCE_ROOT) -> dict[str, Any]:
    manifest = _load_source_manifest(source_root)
    snapshot_before = _source_snapshot(source_root)
    datasets = tuple(_load_dataset(dataset_id, source_root) for dataset_id in VALIDATION_DATASETS)
    source_binding = _source_binding_for_root(manifest, snapshot_before, source_root)
    lock = _validation_lock(source_binding)
    feature_rows, episode_rows, outcome_rows = _source_rows(datasets)
    model_validation = _evaluate_models(feature_rows, outcome_rows, datasets)
    feature_associations = _feature_associations(feature_rows, outcome_rows)
    ablation = _feature_ablation(model_validation)
    sensitivity = _sensitivity_summary(datasets, feature_rows, model_validation)
    decision = _decision(model_validation, source_binding, sensitivity, feature_rows, outcome_rows)
    snapshot_after = _source_snapshot(source_root)
    if snapshot_before != snapshot_after:
        raise StudyError("source changed during validation derivation")
    temporal_audit = {
        "schema_version": STUDY_SCHEMA + "_temporal_audit_v1",
        "status": "NOT_OPENED_BEFORE_VALIDATION_LOCK",
        "accessed": False,
        "root": str(TEMPORAL_ROOT),
        "reason": "no quality family lock was available during validation derivation",
    }
    contract = _contract()
    rows_payload = {
        "schema_version": STUDY_SCHEMA + "_candidate_checkpoint_rows_v1",
        "row_count": len(feature_rows),
        "rows": feature_rows,
    }
    episodes_payload = {
        "schema_version": STUDY_SCHEMA + "_contact_episode_rows_v1",
        "row_count": len(episode_rows),
        "rows": episode_rows,
    }
    outcomes_payload = {
        "schema_version": STUDY_SCHEMA + "_future_reaction_rows_v1",
        "row_count": len(outcome_rows),
        "rows": outcome_rows,
    }
    return {
        "study_contract": contract,
        "source_binding": source_binding,
        "candidate_checkpoint_rows": rows_payload,
        "contact_episode_rows": episodes_payload,
        "future_reaction_rows": outcomes_payload,
        "feature_associations": feature_associations,
        "model_validation": model_validation,
        "feature_ablation": ablation,
        "validation_lock": lock,
        "temporal_audit": temporal_audit,
        "decision": decision,
        "source_snapshot_before": snapshot_before,
        "source_snapshot_after": snapshot_after,
    }


def _render_bundle(evidence: Mapping[str, Any]) -> dict[str, bytes]:
    payloads = {
        "study_contract.json": evidence["study_contract"],
        "source_binding.json": evidence["source_binding"],
        "candidate_checkpoint_rows.json": evidence["candidate_checkpoint_rows"],
        "contact_episode_rows.json": evidence["contact_episode_rows"],
        "future_reaction_rows.json": evidence["future_reaction_rows"],
        "feature_associations.json": evidence["feature_associations"],
        "model_validation.json": evidence["model_validation"],
        "feature_ablation.json": evidence["feature_ablation"],
        "validation_lock.json": evidence["validation_lock"],
        "temporal_audit.json": evidence["temporal_audit"],
        "decision.json": evidence["decision"],
    }
    member_items = [
        {"path": name, "size": len(_canonical_bytes(payload)), "sha256": _sha256_bytes(_canonical_bytes(payload))}
        for name, payload in sorted(payloads.items())
    ]
    inventory_payload = {
        "schema_version": STUDY_SCHEMA + "_output_inventory_v1",
        "members": member_items,
    }
    inventory = {**inventory_payload, "inventory_id": _identity(INVENTORY_NAMESPACE, inventory_payload)}
    inventory_bytes = _canonical_bytes(inventory)
    all_members = [
        *member_items,
        {"path": "output_inventory.json", "size": len(inventory_bytes), "sha256": _sha256_bytes(inventory_bytes)},
    ]
    manifest_payload = {
        "schema_version": STUDY_SCHEMA + "_manifest_v1",
        "study_contract_id": evidence["study_contract"]["contract_id"],
        "source_binding_id": evidence["source_binding"]["source_binding_id"],
        "validation_lock_id": evidence["validation_lock"]["validation_lock_id"],
        "decision_id": evidence["decision"]["decision_id"],
        "member_count": len(all_members),
        "members": all_members,
        "output_inventory_id": inventory["inventory_id"],
        "output_inventory_sha256": _sha256_bytes(inventory_bytes),
        "study_status": evidence["decision"]["status"],
    }
    manifest = {**manifest_payload, "manifest_id": _identity(MANIFEST_NAMESPACE, manifest_payload)}
    payloads["output_inventory.json"] = inventory
    payloads["manifest.json"] = manifest
    return {name: _canonical_bytes(payload) for name, payload in payloads.items()}


def _validate_rendered(root: Path, expected: Mapping[str, bytes]) -> dict[str, Any]:
    actual_names = {path.name for path in root.iterdir() if path.is_file()}
    if actual_names != set(expected):
        raise StudyError("published member set mismatch")
    for name, expected_bytes in expected.items():
        if (root / name).read_bytes() != expected_bytes:
            raise StudyError(f"published artifact mismatch: {name}")
    return _load_json(root / "manifest.json")


def _publish(root: Path, rendered: Mapping[str, bytes]) -> None:
    if root.exists():
        raise StudyError("canonical output already exists; rerun prohibited")
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{root.name}.", dir=root.parent))
    try:
        for name, payload in rendered.items():
            (staging / name).write_bytes(payload)
        _validate_rendered(staging, rendered)
        os.replace(staging, root)
    except Exception:
        if staging.exists():
            for path in staging.iterdir():
                path.unlink()
            staging.rmdir()
        raise


def _prepare_staging(root: Path, lock: Mapping[str, Any]) -> Path:
    if root.exists():
        raise StudyError("canonical output already exists; rerun prohibited")
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{root.name}.", dir=root.parent))
    try:
        lock_bytes = _canonical_bytes(lock)
        (staging / "validation_lock.json").write_bytes(lock_bytes)
        if (staging / "validation_lock.json").read_bytes() != lock_bytes:
            raise StudyError("validation lock persistence mismatch")
        return staging
    except Exception:
        if staging.exists():
            staging.rmdir()
        raise


def verify_bundle(root: Path = OUTPUT_ROOT, *, source_root: Path = SOURCE_ROOT) -> dict[str, Any]:
    expected_evidence = _derive_evidence(source_root)
    expected = _render_bundle(expected_evidence)
    if not root.is_dir():
        raise StudyError("output bundle missing")
    manifest = _validate_rendered(root, expected)
    return {
        "status": manifest["study_status"],
        "contract_id": expected_evidence["study_contract"]["contract_id"],
        "decision_id": manifest["decision_id"],
        "validation_lock_id": manifest["validation_lock_id"],
        "manifest_id": manifest["manifest_id"],
        "member_count": manifest["member_count"],
        "output_inventory_sha256": manifest["output_inventory_sha256"],
        "provider_execution_count": 0,
        "network_request_count": 0,
    }


def execute_study(*, source_root: Path = SOURCE_ROOT, output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    if os.environ.get("TRENDLINE_V2_ALLOW_PHASE12Q1_STUDY") != "1":
        raise StudyError("Phase 12Q.1 execution requires explicit environment guard")
    if output_root.exists():
        raise StudyError("canonical output exists; second run prohibited")
    # Validation lock is derived and persisted in staging before dataset loading.
    manifest = _load_source_manifest(source_root)
    source_binding = _source_binding_for_root(manifest, _source_snapshot(source_root), source_root)
    lock = _validation_lock(source_binding)
    staging = _prepare_staging(output_root, lock)
    try:
        evidence = _derive_evidence(source_root)
        if evidence["validation_lock"] != lock:
            raise StudyError("validation lock drift")
        rendered = _render_bundle(evidence)
        for name, payload in rendered.items():
            (staging / name).write_bytes(payload)
        _validate_rendered(staging, rendered)
        os.replace(staging, output_root)
    except Exception:
        if staging.exists():
            for path in staging.iterdir():
                path.unlink()
            staging.rmdir()
        raise
    return verify_bundle(output_root, source_root=source_root)


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
        parser.exit(1, f"{exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
