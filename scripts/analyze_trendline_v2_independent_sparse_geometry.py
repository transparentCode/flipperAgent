"""Phase 11R.1 independent sparse geometry feasibility study.

This module is deliberately an offline research runner.  It reads only the
typed OHLCV payload nested under persisted provider requests and owns all
pivot, line, validity, stability, and future-observation calculations here.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import combinations
from pathlib import Path
import shutil
import statistics
import tempfile
from typing import Any, Iterable, Mapping, Sequence

from libs.models.trendline_v2.domain.geometry import LineGeometry
from libs.models.trendline_v2.domain.identity import canonical_json, deterministic_hash
from libs.models.trendline_v2.domain.provider_input import ProviderInput
from libs.models.trendline_v2.domain.validation import ContractValidationError


NANOSECONDS = 1_000_000_000
INTERVAL_SECONDS = {"1h": 3_600, "4h": 14_400}
HORIZONS_HOURS = (24, 48, 96)
SCALES_HOURS = (12, 24, 48)
OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_phase11r1_independent_sparse_geometry/"
    "20260522_20260701__20250801_20260401"
)
VALIDATION_ROOT = Path(
    "/tmp/trendline_v2_phase9c2_fresh_scope_family_validation/20260522_20260701"
)
TEMPORAL_ROOT = Path("/tmp/trendline_v2_phase10c2_lookback_eviction/20251201_20260401")
VALIDATION_DATASETS = ("btcusdt_1h", "btcusdt_4h", "ethusdt_1h", "ethusdt_4h")
HOLDOUT_DATASETS = ("suiusdt_1h", "suiusdt_4h")
ALL_DATASETS = VALIDATION_DATASETS + HOLDOUT_DATASETS
TEMPORAL_DATASET = "btcusdt_4h"
CHECKPOINTS_PER_DATASET = 22
VALIDATION_CHECKPOINT_COUNT = len(VALIDATION_DATASETS) * CHECKPOINTS_PER_DATASET
HOLDOUT_CHECKPOINT_COUNT = len(HOLDOUT_DATASETS) * CHECKPOINTS_PER_DATASET
MAX_PAIR_SEEDS = 20_000
BREACH_ATR = 0.5
TOUCH_ATR = 0.35
MAX_DISTANCE_ATR = 8.0
REACTION_ATR = 1.0

CONTRACT_NAMESPACE = (
    "trendline_v2_phase_11r1_independent_sparse_geometry_feasibility_contract"
)
SEED_NAMESPACE = "trendline_v2_phase_11r1_sparse_seed"
LINE_NAMESPACE = "trendline_v2_phase_11r1_sparse_line"
PIVOT_NAMESPACE = "trendline_v2_phase_11r1_sparse_pivot"
MANIFEST_NAMESPACE = "trendline_v2_phase_11r1_sparse_manifest"
DECISION_NAMESPACE = "trendline_v2_phase_11r1_sparse_decision"
LOCK_NAMESPACE = "trendline_v2_phase_11r1_sparse_validation_lock"
SOURCE_AUDIT_NAMESPACE = "trendline_v2_phase_11r1_sparse_source_audit"

# This identity is pinned by the architecture handoff. Generation must fail
# closed until its canonical payload preimage is available and matches.
CONTRACT_ID = "3bcad03fdd5df8b3af6754bdb38b0436cc93528964298607dd1169950cc312d3"
CONTRACT_JSON_SHA256 = "deab0f575d7c9461cadc3d3925558b517ad41443c860133a9817f281ba08ae91"
CONTRACT_JSON_BYTE_LENGTH = 14905
PHASE9C2_DECISION_ID = "4b734cbf99e1453bccdedb95f397f4b34e020f29e3d18808a131456647f78f7c"
PHASE9C2_MANIFEST_ID = "beab5b9acb2bfc3c25ba9cb5cb31c33c1a31e6069c1d7906f3ed5e1c2d798c81"
PHASE9C2_OUTPUT_INVENTORY = "ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532"
PHASE9C2_SOURCE_INVENTORY = "631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be"
PHASE10C2_REPLAY_CONTRACT_ID = "166b156a471f06dcc2d4fbf09196df95c4648e4b60cac52d1d315f7e7794af96"
PHASE10C2_DECISION_ID = "ac26d26534e65472bc18c072eee1121ce5c7420b8c541264139bf1614b95c6b6"
PHASE10C2_MANIFEST_ID = "4daff316405662de15a328bafd503740d38c7343cfe4616bb8096976d0466ef5"
PHASE10C2_OUTPUT_INVENTORY = "64e9477e48a3d546dc39b5ac8d0fa6328d4dddd10b1c055ae3616bd1de2bf35c"
PHASE10C2_SOURCE_INVENTORY = "872bffa5aa232bfbeac2788c4575a8e73b344476c75cfedb67b8014bc82b550f"
PHASE11S1_CONTRACT_ID = "41c6054577193d64e4bf2ff985d40571e9f75427bfbf47508e3b673ee9e32b54"
PHASE11S1_DECISION_ID = "44ffc590402b49d25b44a327522411e2f5ffadce13607fe0ed957e5db02e3b9d"
PHASE11S1_MANIFEST_ID = "3c0f999220b4397bcfc208475c876fb79af1ec1df0bfc558d245bc56e3850930"
PHASE11S1_INVENTORY = "3731fd6d35472002eae4ae81cc9eb0d87bfcdfbc8552e44209ba1ede46b2c4b3"

DECISION_STATUSES = (
    "INDEPENDENT_SPARSE_PROVIDER_PROMOTION_CANDIDATE",
    "NO_INDEPENDENT_SPARSE_PROVIDER_FINALIST",
    "INDEPENDENT_SPARSE_PROVIDER_HOLDOUT_REJECTED",
    "INDEPENDENT_SPARSE_PROVIDER_TEMPORAL_REJECTED",
    "INDEPENDENT_SPARSE_PROVIDER_BLOCKED",
)
PRIMARY_PROVIDERS = (
    "hierarchical_multitouch_pair_v1",
    "deterministic_theil_sen_multitouch_v1",
)
CONTROL_PROVIDERS = (
    "latest_wide_pair_control_v1",
    "hash_wide_pair_control_v1",
)
VALIDATION_METHODS = PRIMARY_PROVIDERS + CONTROL_PROVIDERS
LOCKED_WINNER_METHOD = "<locked_validation_winner>"
HOLDOUT_METHODS = (LOCKED_WINNER_METHOD, CONTROL_PROVIDERS[0])
TEMPORAL_METHODS = (LOCKED_WINNER_METHOD,)
ROLES = ("support", "resistance")


class StudyError(RuntimeError):
    """Expected bounded study or evidence failure."""


class StudyBlocked(StudyError):
    """Study cannot continue without relaxing an approved boundary."""


@dataclass(frozen=True, slots=True)
class Pivot:
    pivot_id: str
    asset: str
    timeframe: str
    role: str
    source_position: int
    pivot_time: datetime
    confirmation_time: datetime
    available_at: datetime
    price: float
    scale_hours: int
    source_input_identity: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pivot_id": self.pivot_id,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "role": self.role,
            "source_position": self.source_position,
            "pivot_time": _iso(self.pivot_time),
            "confirmation_time": _iso(self.confirmation_time),
            "available_at": _iso(self.available_at),
            "price": self.price,
            "scale_hours": self.scale_hours,
            "source_input_identity": self.source_input_identity,
        }


@dataclass(frozen=True, slots=True)
class Seed:
    seed_id: str
    role: str
    first: Pivot
    second: Pivot
    touches: tuple[Pivot, ...]
    geometry: LineGeometry
    current_valid: bool
    current_distance_atr: float
    checkpoint_close: float
    checkpoint_atr: float


@dataclass(frozen=True, slots=True)
class ScopeCheckpoint:
    dataset_id: str
    checkpoint_index: int
    checkpoint: datetime
    data: ProviderInput
    prefix_last_position: int


@dataclass(frozen=True, slots=True)
class ScopeDataset:
    dataset_id: str
    data: ProviderInput
    checkpoints: tuple[ScopeCheckpoint, ...]


def _canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise StudyError(f"{field} must be an ISO string")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StudyError(f"invalid {field}") from exc
    if result.tzinfo is None:
        raise StudyError(f"{field} must be UTC")
    return result.astimezone(UTC)


def _datetime_from_ns(value: int) -> datetime:
    seconds, remainder = divmod(int(value), NANOSECONDS)
    return datetime.fromtimestamp(seconds, tz=UTC) + timedelta(
        microseconds=remainder // 1_000
    )


def _datetime_to_ns(value: datetime) -> int:
    value = value.astimezone(UTC)
    return int(value.timestamp()) * NANOSECONDS + value.microsecond * 1_000


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
    result: list[dict[str, Any]] = []
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


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_bytes(_canonical_bytes(value))


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


def _median(values: Sequence[float | int]) -> float | None:
    return float(statistics.median(values)) if values else None


def _stats(values: Sequence[float | int]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "minimum": ordered[0] if ordered else None,
        "median": _median(ordered),
        "maximum": ordered[-1] if ordered else None,
    }


def _value_or(value: Any, fallback: Any) -> Any:
    """Use fallback only for missing values; preserve valid zeroes."""
    return fallback if value is None else value


def _contract_payload() -> dict[str, Any]:
    """Return one explicit, immutable contract preimage for Phase 11R.1."""
    return {
        "schema_version": "trendline_v2_phase_11r1_independent_sparse_geometry_feasibility_contract",
        "base_commit": "2e12b9e2dbed8c7e761714adb80ee788bbf01d78",
        "prior_evidence": {
            "phase11s1": {
                "contract_id": PHASE11S1_CONTRACT_ID,
                "decision_id": PHASE11S1_DECISION_ID,
                "manifest_id": PHASE11S1_MANIFEST_ID,
                "inventory_sha256": PHASE11S1_INVENTORY,
                "membership_use": "bind_only_never_candidate_membership",
            },
            "phase9c2": {
                "decision_id": PHASE9C2_DECISION_ID,
                "manifest_id": PHASE9C2_MANIFEST_ID,
                "output_inventory_sha256": PHASE9C2_OUTPUT_INVENTORY,
                "source_inventory_sha256": PHASE9C2_SOURCE_INVENTORY,
            },
            "phase10c2": {
                "replay_contract_id": PHASE10C2_REPLAY_CONTRACT_ID,
                "decision_id": PHASE10C2_DECISION_ID,
                "manifest_id": PHASE10C2_MANIFEST_ID,
                "output_inventory_sha256": PHASE10C2_OUTPUT_INVENTORY,
                "source_inventory_sha256": PHASE10C2_SOURCE_INVENTORY,
            },
        },
        "independence": {
            "forbidden_imports": [
                "app.trendlines",
                "libs.trendlines",
                "libs.models.trendlines_old",
                "libs.models.trendline",
                "libs.models.trendline_family",
            ],
            "forbidden_execution": [
                "old_trendlines",
                "confirmed_extrema_pair_v1",
                "latest_valid_predecessor_v1",
                "phase11s1_selector",
                "trendline_v2_provider",
                "network",
            ],
            "raw_input_path": "provider_result.request.input_data",
            "forbidden_payload_fields": [
                "provider_result.candidates",
                "provider_result.evidence",
                "selection_snapshot",
                "tracking_snapshot",
            ],
            "runtime_source_modifications": False,
        },
        "scopes": {
            "validation": {
                "root": str(VALIDATION_ROOT),
                "datasets": list(VALIDATION_DATASETS),
                "checkpoint_count_per_dataset": CHECKPOINTS_PER_DATASET,
                "decision_id": PHASE9C2_DECISION_ID,
                "manifest_id": PHASE9C2_MANIFEST_ID,
                "output_inventory_sha256": PHASE9C2_OUTPUT_INVENTORY,
                "source_inventory_sha256": PHASE9C2_SOURCE_INVENTORY,
            },
            "holdout": {
                "root": str(VALIDATION_ROOT),
                "datasets": list(HOLDOUT_DATASETS),
                "checkpoint_count_per_dataset": CHECKPOINTS_PER_DATASET,
                "locked_after_validation": True,
            },
            "temporal": {
                "root": str(TEMPORAL_ROOT),
                "dataset": TEMPORAL_DATASET,
                "checkpoint_count": 5,
                "locked_after_holdout": True,
                "replay_contract_id": PHASE10C2_REPLAY_CONTRACT_ID,
                "decision_id": PHASE10C2_DECISION_ID,
                "manifest_id": PHASE10C2_MANIFEST_ID,
                "output_inventory_sha256": PHASE10C2_OUTPUT_INVENTORY,
                "source_inventory_sha256": PHASE10C2_SOURCE_INVENTORY,
            },
        },
        "checkpoint_policy": {
            "warmup_hours": 336,
            "cadence_hours": 24,
            "future_horizons_hours": list(HORIZONS_HOURS),
            "prefix_rule": "timestamp < checkpoint",
            "availability_rule": "available_at <= checkpoint",
            "future_rule": "timestamp strictly after checkpoint",
            "last_checkpoint_rule": "checkpoint_plus_96h_timestamp_must_exist_in_source",
            "confirmed_through_semantics": "exclusive_completion_boundary_not_candle_timestamp",
            "natural_source_end_policy": "exclude_checkpoint_without_complete_max_horizon",
            "interior_gap_policy": "BLOCK",
            "bar_horizons": {"1h": [24, 48, 96], "4h": [6, 12, 24]},
            "validation_checkpoint_count": VALIDATION_CHECKPOINT_COUNT,
            "holdout_checkpoint_count": HOLDOUT_CHECKPOINT_COUNT,
            "temporal_checkpoint_count": 5,
            "execution_order": "validation_then_lock_then_holdout_then_temporal",
        },
        "atr": {
            "method": "wilder_atr_14_seed_first_true_range_v1",
            "seed": "true_range[0]",
            "period": 14,
            "formula": "tr=max(high-low,abs(high-prev_close),abs(low-prev_close)); atr=(13*prev+tr)/14",
            "denominator_rule": "finite_positive_only",
        },
        "hierarchical_pivots": {
            "physical_scales_hours": list(SCALES_HOURS),
            "radius_bars": {"1h": [12, 24, 48], "4h": [3, 6, 12]},
            "support_rule": "low equals local window minimum",
            "resistance_rule": "high equals local window maximum",
            "confirmation_rule": "position plus radius; available after confirmation bar interval",
            "plateau_rule": "consecutive equal extrema retain middle position",
            "merge_rule": "same role and source position keeps maximum qualifying scale",
            "identity_fields": [
                "asset", "timeframe", "role", "source_position", "pivot_time",
                "confirmation_time", "price", "scale_hours", "source_input_identity",
            ],
            "confirmed_only": True,
            "plateau_grouping": "consecutive_equal_price_extrema_only",
            "representative": "middle_position_of_equal_price_group",
        },
        "owner_timeframe_validity": {
            "owner": "timeframe",
            "projection_instant": "checkpoint",
            "checkpoint_close_source": "final_completed_prefix_bar",
            "checkpoint_atr_source": "final_completed_prefix_bar",
            "line_at_checkpoint_formula": "geometry.value_at(checkpoint)",
            "current_distance_formula": "abs(checkpoint_close-line_at_checkpoint)/checkpoint_atr",
            "positive_projection_required": True,
            "maximum_current_distance_atr": MAX_DISTANCE_ATR,
            "wick_crossing": "never_invalidates",
            "close_breach_atr": BREACH_ATR,
            "sustained_breach_bars": 2,
            "hierarchical_validity_start": "second_seed_anchor_plus_one",
            "theil_sen_validity_start": "final_inlier_anchor_plus_one",
        },
        "seed_pool": {
            "same_role_chronological_pairs": True,
            "minimum_span_hours": 96,
            "minimum_touches": 3,
            "current_sustained_breach_rejected": True,
            "positive_finite_projection": True,
            "maximum_pair_seeds_per_role_checkpoint": MAX_PAIR_SEEDS,
            "overflow_action": "BLOCK_NO_TRUNCATION_NO_SAMPLING",
            "identity_namespace": SEED_NAMESPACE,
            "uses_checkpoint_projection": True,
            "no_truncation": True,
            "no_sampling": True,
        },
        "methods": {
            "primary": {
                "hierarchical_multitouch_pair_v1": {
                    "geometry": "exact_seed_pair_timestamp_space",
                    "ranking_order": [
                        "negative_scale_48_touch_count",
                        "negative_touch_count",
                        "negative_touch_scale_hours",
                        "negative_anchor_span_hours",
                        "last_touch_age_bars",
                        "current_distance_atr",
                        "seed_id",
                    ],
                    "initial_touch_population": "all_confirmed_pivots_from_first_seed_anchor_through_checkpoint",
                    "include_both_seed_anchors": True,
                    "touch_tolerance_atr": TOUCH_ATR,
                    "max_per_role": 1,
                },
                "deterministic_theil_sen_multitouch_v1": {
                    "initial_tolerance_atr": TOUCH_ATR,
                    "residual_tolerance_atr": 0.5,
                    "slope": "median_unique_touch_pair_slopes",
                    "intercept": "median_pivot_price_minus_slope_epoch_seconds",
                    "refit_passes": 1,
                    "minimum_inliers": 3,
                    "ranking_order": [
                        "negative_scale_48_touch_or_inlier_count",
                        "negative_touch_or_inlier_count",
                        "negative_structural_span_hours",
                        "median_abs_inlier_residual_atr",
                        "last_touch_or_inlier_age_bars",
                        "current_distance_atr",
                        "refit_id",
                    ],
                    "dedupe": "equal_sorted_inlier_ids_keep_lowest_seed_id",
                    "initial_touch_population": "all_confirmed_pivots_from_first_seed_anchor_through_checkpoint",
                    "include_both_seed_anchors": True,
                    "touch_tolerance_atr": TOUCH_ATR,
                    "inlier_tolerance_atr": 0.5,
                    "max_per_role": 1,
                },
            },
            "controls": {
                "latest_wide_pair_control_v1": {
                    "ranking_order": [
                        "second_anchor_time_desc", "first_anchor_time_desc", "seed_id_asc",
                    ],
                    "same_seed_pool_and_cardinality": True,
                },
                "hash_wide_pair_control_v1": {
                    "ranking_order": ["seed_id_asc"],
                    "same_seed_pool_and_cardinality": True,
                },
            },
            "validation_method_order": list(VALIDATION_METHODS),
        },
        "scope_method_sets": {
            "validation": list(VALIDATION_METHODS),
            "holdout": list(HOLDOUT_METHODS),
            "temporal": list(TEMPORAL_METHODS),
        },
        "research_line_contract": {
            "identity_namespace": LINE_NAMESPACE,
            "cardinality": "zero_or_one_per_role_per_method_checkpoint",
            "available_at_equals_checkpoint": True,
            "channel_inversion": "support_projection > resistance_projection",
            "price_bracket": "support <= checkpoint_close <= resistance",
            "evidence": "all_touch_or_inlier_pivots_persisted",
            "current_projection_instant": "checkpoint",
            "anchors": {
                "hierarchical": "seed_first_and_seed_second",
                "theil_sen": "first_final_inlier_and_final_final_inlier",
            },
            "initial_touch_population": "all_confirmed_pivots_from_first_seed_anchor_through_checkpoint",
            "include_both_seed_anchors": True,
            "touch_tolerance_atr": TOUCH_ATR,
            "theil_inlier_tolerance_atr": 0.5,
        },
        "stability": {
            "anchor_jaccard_min": 0.5,
            "projection_distance_atr_max": 0.75,
            "slope_distance_bps_per_day_max": 20,
            "states": ["birth", "continuation", "replacement", "absence"],
            "research_only": True,
            "continuation_rule": "anchor_jaccard >= 0.5 or (projection_distance_atr <= 0.75 and slope_distance_bps_per_day <= 20)",
            "continuation_rate_denominator": "continuation_plus_replacement_states",
            "component_measurements_persisted": True,
        },
        "future_evaluation": {
            "horizons_hours": list(HORIZONS_HOURS),
            "expected_bar_counts": {"1h": {"24": 24, "48": 48, "96": 96}, "4h": {"24": 6, "48": 12, "96": 24}},
            "timestamp_sequence": "checkpoint_plus_interval_through_horizon_endpoint_exactly",
            "survival": "no_two_consecutive_close_breaches",
            "zone_formula": "low <= line + 0.35ATR and high >= line - 0.35ATR",
            "reaction": "before_first_sustained_breach_using_first_contact_atr",
            "reaction_start_rule": "first_bar_strictly_after_first_contact_bar",
            "same_contact_bar_reaction": False,
            "intrabar_order_assumption": "none",
            "reaction_atr_source": "ATR_at_first_contact_bar",
            "support_reaction": "future_high_minus_contact_line >= 1ATR",
            "resistance_reaction": "contact_line_minus_future_low >= 1ATR",
            "persisted_fields": [
                "survives_tolerant_owner_tf", "has_zone_contact", "zone_contact_and_survives",
                "has_role_consistent_reaction", "first_contact_offset_bars",
                "first_sustained_breach_offset_bars",
            ],
            "temporal_policy": "not_evaluated_prefix_only_source",
        },
        "matched_control_semantics": {
            "sample_key": ["checkpoint_index", "role"],
            "utility_control": "latest_wide_pair_control_v1",
            "primary_and_control_sample_keys_must_match": True,
            "primary_and_control_cardinality_must_match": True,
            "missing_matched_control_action": "BLOCK",
            "hash_control_use": "descriptive_only",
        },
        "validation": {
            "structural_gates": {
                "support_coverage_min": 0.70,
                "resistance_coverage_min": 0.70,
                "both_coverage_min": 0.60,
                "median_touch_min": 3,
                "median_span_hours_min": 168,
                "channel_inversion_rate_max": 0.0,
                "current_validity_rate_min": 1.0,
                "median_distance_atr_max": 6.0,
                "median_continuation_min": 0.50,
            },
            "utility_gates": {
                "pooled_48_survival_delta_min": 0.0,
                "pooled_96_survival_delta_min": 0.0,
                "pooled_96_zone_survival_delta_min": 0.0,
                "pooled_96_reaction_delta_min": -0.02,
                "worst_dataset_96_survival_delta_min": -0.05,
            },
            "eligibility": "all_four_datasets_structural_gates_then_pooled_utility_gates",
                "pooled_rate_formula": "sum_success_counts/sum_evaluable_counts",
                "pooled_delta_formula": "pooled_provider_rate-pooled_latest_control_rate",
                "ranking_order": [
                    "gate_passed_desc",
                    "worst_dataset_96_zone_survival_delta_desc",
                "pooled_96_zone_survival_delta_desc",
                "pooled_96_reaction_delta_desc",
                "median_continuation_desc",
                "median_touch_desc",
                "median_span_desc",
                "provider_id_asc",
            ],
            "lock_contents": [
                "source_identities", "validation_dataset_ids", "validation_result_ids",
                "dataset_result_ids", "validation_method_ids",
                "validation_method_derivation_count", "ordered_ranking",
                "winner_provider_id", "holdout_access",
            ],
            "lock_canonical_bytes_required": True,
        },
        "holdout": {
            "structural_gates": {
                "support_coverage_min": 0.70,
                "resistance_coverage_min": 0.70,
                "both_coverage_min": 0.60,
                "median_touch_min": 3,
                "median_span_hours_min": 168,
                "channel_inversion_rate_max": 0.0,
                "current_validity_rate_min": 1.0,
                "median_distance_atr_max": 6.0,
                "adjacent_continuation_min": 0.40,
            },
            "utility_gates": {
                "pooled_96_survival_delta_min": 0.0,
                "pooled_96_zone_survival_delta_min": 0.0,
                "pooled_96_reaction_delta_min": -0.02,
                "worst_dataset_96_survival_delta_min": -0.05,
                "median_continuation_min": 0.40,
            },
            "method_set": list(HOLDOUT_METHODS),
            "both_datasets_required": True,
        },
        "temporal_audit": {
            "gates": {
                "checkpoint_count": 5,
                "support_present_min": 4,
                "resistance_present_min": 4,
                "both_present_min": 3,
                "inversion_count_max": 0,
                "current_validity_rate_min": 1.0,
                "median_span_hours_min": 168,
                "median_continuation_min": 0.40,
            },
            "method_set": list(TEMPORAL_METHODS),
            "promotion_requires_all_gates": True,
            "failure_status": "INDEPENDENT_SPARSE_PROVIDER_TEMPORAL_REJECTED",
            "touch_and_distance_gates": False,
        },
        "execution_accounting": {
            "network_requests": 0,
            "legacy_executions": 0,
            "confirmed_extrema_pair_executions": 0,
            "v2_provider_executions": 0,
            "runtime_source_modifications": 0,
            "parallel_executions": 0,
            "derivation_repeats": 2,
            "validation_method_derivations": 704,
            "holdout_method_derivations_max": 176,
            "temporal_method_derivations_max": 10,
            "maximum_method_derivations": 890,
        },
        "decision_statuses": list(DECISION_STATUSES),
        "artifacts": {
            "output_root": str(OUTPUT_ROOT),
            "exact_paths": [
                "study_contract.json", "source_audit.json", "validation_lock.json",
                "cross_scope_summary.csv", "temporal_summary.csv", "decision.json", "manifest.json",
                *[f"datasets/{dataset}/{member}" for dataset in ALL_DATASETS for member in ("checkpoint_membership.json", "provider_metrics.json")],
                f"temporal/{TEMPORAL_DATASET}/checkpoint_membership.json",
                f"temporal/{TEMPORAL_DATASET}/provider_metrics.json",
            ],
            "top_level": [
                "study_contract.json", "source_audit.json", "validation_lock.json",
                "cross_scope_summary.csv", "temporal_summary.csv", "decision.json", "manifest.json",
            ],
            "dataset_members": ["checkpoint_membership.json", "provider_metrics.json"],
            "temporal_members": ["checkpoint_membership.json", "provider_metrics.json"],
            "manifest_member_count": 20,
            "total_file_count": 21,
            "atomic_publication": True,
        },
        "study_controls": {
            "canonical_json_required": True,
            "contract_identity_rule": "namespaced_sha256_of_canonical_json_payload",
            "fresh_run_required": True,
            "previous_bundle_forensic_only": True,
            "validation_lock_before_holdout": True,
            "temporal_after_holdout_pass_only": True,
            "timing_excluded_from_identity": True,
            "no_parameter_changes_after_results": True,
            "cli_guard": "exactly_one_of_execute_study_or_verify",
            "environment_guard": "TRENDLINE_V2_ALLOW_PHASE11R1_STUDY=1",
            "existing_root_refusal_before_source_access": True,
            "atomic_publication": "single_directory_replace",
            "no_study_run_during_contract_freeze": True,
        },
    }


def replay_contract_id(payload: Mapping[str, Any]) -> str:
    return deterministic_hash(CONTRACT_NAMESPACE, payload)


def _validated_contract() -> tuple[dict[str, Any], str]:
    payload = _contract_payload()
    canonical_payload = canonical_json(payload).encode("utf-8")
    canonical_length = len(canonical_payload)
    canonical_sha256 = _sha256_bytes(canonical_payload)
    if (
        canonical_length != CONTRACT_JSON_BYTE_LENGTH
        or canonical_sha256 != CONTRACT_JSON_SHA256
    ):
        raise StudyBlocked(
            "contract canonical preimage mismatch: "
            f"expected length={CONTRACT_JSON_BYTE_LENGTH}, sha256={CONTRACT_JSON_SHA256}; "
            f"derived length={canonical_length}, sha256={canonical_sha256}"
        )
    identity = replay_contract_id(payload)
    if identity != CONTRACT_ID:
        raise StudyBlocked(
            "contract identity mismatch: "
            f"expected {CONTRACT_ID}, derived {identity}"
        )
    return payload, identity


def _raw_provider_input(payload: Mapping[str, Any]) -> ProviderInput:
    """Decode only request.input_data; never inspect provider output fields."""
    try:
        provider_payload = payload["provider_result"]
        request = provider_payload["request"]
        raw = request["input_data"]
        expected_identity = raw["input_identity"]
        data = ProviderInput(
            asset=raw["asset"],
            timeframe=raw["timeframe"],
            observed_at=_parse_iso(raw["observed_at"], field="observed_at"),
            confirmed_through=_parse_iso(
                raw["confirmed_through"], field="confirmed_through"
            ),
            timestamps=tuple(raw["timestamps"]),
            open=tuple(raw["open"]),
            high=tuple(raw["high"]),
            low=tuple(raw["low"]),
            close=tuple(raw["close"]),
            volume=tuple(raw["volume"]),
        )
    except (KeyError, TypeError, ValueError, ContractValidationError) as exc:
        raise StudyError("invalid raw ProviderInput artifact") from exc
    if expected_identity != data.input_identity or request.get("input_identity") != data.input_identity:
        raise StudyError("raw ProviderInput identity mismatch")
    return data


def _validate_manifest(root: Path, *, expected_manifest: str, expected_inventory: str) -> tuple[dict[str, Any], ...]:
    manifest = _load_json(root / "manifest.json")
    if manifest.get("manifest_id") != expected_manifest:
        raise StudyError(f"manifest identity mismatch: {root}")
    members = manifest.get("members")
    if not isinstance(members, list) or manifest.get("member_count") != len(members):
        raise StudyError("invalid source manifest members")
    actual = _inventory(root)
    actual_members = tuple(item for item in actual if item["path"] != "manifest.json")
    if tuple(members) != actual_members:
        raise StudyError(f"source manifest member mismatch: {root}")
    if _inventory_sha256(actual) != expected_inventory:
        raise StudyError(f"source inventory mismatch: {root}")
    return actual


def _expected_future_timestamps(
    *, timeframe: str, checkpoint: datetime, horizon_hours: int
) -> tuple[int, ...]:
    interval = INTERVAL_SECONDS.get(timeframe)
    if interval is None:
        raise StudyError(f"unsupported timeframe: {timeframe}")
    horizon_seconds = horizon_hours * 3_600
    if horizon_seconds <= 0 or horizon_seconds % interval:
        raise StudyError("future horizon is not aligned to timeframe")
    count = horizon_seconds // interval
    return tuple(
        _datetime_to_ns(checkpoint + timedelta(seconds=interval * offset))
        for offset in range(1, count + 1)
    )


def _future_window_positions(
    data: ProviderInput, *, checkpoint: datetime, horizon_hours: int
) -> tuple[int, ...]:
    expected = _expected_future_timestamps(
        timeframe=data.timeframe,
        checkpoint=checkpoint,
        horizon_hours=horizon_hours,
    )
    timestamps = tuple(data.timestamps)
    if any(left >= right for left, right in zip(timestamps, timestamps[1:])):
        raise StudyError("future source timestamps are not strictly ordered")
    expected_set = set(expected)
    positions = tuple(
        position
        for position, timestamp in enumerate(timestamps)
        if timestamp in expected_set
    )
    actual = tuple(timestamps[position] for position in positions)
    if (
        len(positions) != len(expected)
        or actual != expected
        or (positions and positions[-1] - positions[0] + 1 != len(expected))
    ):
        raise StudyError(
            f"future horizon {horizon_hours}h is missing, duplicated, or misaligned"
        )
    return positions


def _checkpoint_schedule(data: ProviderInput) -> tuple[tuple[int, datetime, int], ...]:
    interval = INTERVAL_SECONDS.get(data.timeframe)
    if interval is None:
        raise StudyError(f"unsupported timeframe: {data.timeframe}")
    if not data.timestamps:
        raise StudyError("source has no timestamps")
    first = _datetime_from_ns(data.timestamps[0])
    last_source_timestamp = _datetime_from_ns(data.timestamps[-1])
    checkpoint = first + timedelta(hours=336)
    last = last_source_timestamp - timedelta(hours=96)
    result: list[tuple[int, datetime, int]] = []
    index = 1
    while checkpoint <= last:
        cutoff = _datetime_to_ns(checkpoint)
        positions = [
            p for p, timestamp in enumerate(data.timestamps) if timestamp < cutoff
        ]
        if (
            not positions
            or data.timestamps[positions[-1]]
            != cutoff - interval * NANOSECONDS
        ):
            raise StudyError("checkpoint prefix is not aligned to completed bars")
        _future_window_positions(
            data,
            checkpoint=checkpoint,
            horizon_hours=max(HORIZONS_HOURS),
        )
        result.append((index, checkpoint, positions[-1]))
        checkpoint += timedelta(hours=24)
        index += 1
    if len(result) != CHECKPOINTS_PER_DATASET:
        raise StudyError(
            f"expected {CHECKPOINTS_PER_DATASET} checkpoints, got {len(result)}"
        )
    return tuple(result)


def _load_scope_dataset(root: Path, dataset_id: str) -> ScopeDataset:
    path = root / "datasets" / dataset_id / "provider_result.json"
    data = _raw_provider_input(_load_json(path))
    if dataset_id != f"{data.asset.lower()}_{data.timeframe}":
        raise StudyError(f"dataset identity mismatch: {dataset_id}")
    checkpoints = tuple(
        ScopeCheckpoint(dataset_id, index, checkpoint, data, last_position)
        for index, checkpoint, last_position in _checkpoint_schedule(data)
    )
    return ScopeDataset(dataset_id, data, checkpoints)


def _load_validation_scope() -> tuple[ScopeDataset, ...]:
    _validate_manifest(
        VALIDATION_ROOT,
        expected_manifest=PHASE9C2_MANIFEST_ID,
        expected_inventory=PHASE9C2_OUTPUT_INVENTORY,
    )
    return tuple(_load_scope_dataset(VALIDATION_ROOT, dataset) for dataset in VALIDATION_DATASETS)


def _load_holdout_scope() -> tuple[ScopeDataset, ...]:
    # Called only after validation lock and a finalist exist.
    _validate_manifest(
        VALIDATION_ROOT,
        expected_manifest=PHASE9C2_MANIFEST_ID,
        expected_inventory=PHASE9C2_OUTPUT_INVENTORY,
    )
    return tuple(_load_scope_dataset(VALIDATION_ROOT, dataset) for dataset in HOLDOUT_DATASETS)


def _load_temporal_scope() -> ScopeDataset:
    _validate_manifest(
        TEMPORAL_ROOT,
        expected_manifest=PHASE10C2_MANIFEST_ID,
        expected_inventory=PHASE10C2_OUTPUT_INVENTORY,
    )
    checkpoints: list[ScopeCheckpoint] = []
    for index in range(1, 6):
        # Explicit names are safer than deriving calendar arithmetic across leap boundaries.
        names = (
            "checkpoint_01_20251201T000000Z.json",
            "checkpoint_02_20260101T000000Z.json",
            "checkpoint_03_20260201T000000Z.json",
            "checkpoint_04_20260301T000000Z.json",
            "checkpoint_05_20260401T000000Z.json",
        )
        payload = _load_json(TEMPORAL_ROOT / "datasets" / TEMPORAL_DATASET / names[index - 1])
        data = _raw_provider_input(payload)
        checkpoint = _parse_iso(payload["observed_at"], field="temporal.observed_at")
        if payload.get("checkpoint_index") != index:
            raise StudyError("temporal checkpoint index mismatch")
        last = data.row_count - 1
        if data.timestamps[last] >= int(checkpoint.timestamp() * NANOSECONDS):
            raise StudyError("temporal input contains checkpoint/future bar")
        checkpoints.append(ScopeCheckpoint(TEMPORAL_DATASET, index, checkpoint, data, last))
    data = checkpoints[-1].data
    return ScopeDataset(TEMPORAL_DATASET, data, tuple(checkpoints))


def _interval(data: ProviderInput) -> int:
    try:
        return INTERVAL_SECONDS[data.timeframe]
    except KeyError as exc:
        raise StudyError(f"unsupported timeframe: {data.timeframe}") from exc


def _causal_input(
    data: ProviderInput, *, prefix_last_position: int, checkpoint: datetime
) -> ProviderInput:
    """Build identity and arrays for exactly information visible at checkpoint."""
    end = prefix_last_position + 1
    return ProviderInput(
        asset=data.asset,
        timeframe=data.timeframe,
        observed_at=checkpoint,
        confirmed_through=checkpoint,
        timestamps=data.timestamps[:end],
        open=data.open[:end],
        high=data.high[:end],
        low=data.low[:end],
        close=data.close[:end],
        volume=data.volume[:end],
    )


def _atr(data: ProviderInput) -> tuple[float, ...]:
    values: list[float] = []
    for i in range(data.row_count):
        high = _finite(data.high[i], field=f"high[{i}]")
        low = _finite(data.low[i], field=f"low[{i}]")
        if i == 0:
            true_range = high - low
        else:
            previous_close = _finite(data.close[i - 1], field=f"close[{i - 1}]")
            true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))
        if not math.isfinite(true_range) or true_range <= 0:
            raise StudyError("ATR true range must be finite and positive")
        previous = values[-1] if values else true_range
        current = true_range if not values else (13.0 * previous + true_range) / 14.0
        if not math.isfinite(current) or current <= 0:
            raise StudyError("ATR must be finite and positive")
        values.append(current)
    return tuple(values)


def _scale_radii(timeframe: str) -> tuple[tuple[int, int], ...]:
    if timeframe == "1h":
        return ((12, 12), (24, 24), (48, 48))
    if timeframe == "4h":
        return ((12, 3), (24, 6), (48, 12))
    raise StudyError(f"unsupported timeframe: {timeframe}")


def _make_pivot(
    data: ProviderInput,
    atr: Sequence[float],
    role: str,
    position: int,
    radius: int,
    scale_hours: int,
    checkpoint: datetime,
) -> Pivot | None:
    interval = _interval(data)
    confirmation_position = position + radius
    confirmation_time = _datetime_from_ns(data.timestamps[confirmation_position])
    available_at = confirmation_time + timedelta(seconds=interval)
    if available_at > checkpoint:
        return None
    price = data.low[position] if role == "support" else data.high[position]
    payload = {
        "asset": data.asset,
        "timeframe": data.timeframe,
        "role": role,
        "source_position": position,
        "pivot_time": _iso(_datetime_from_ns(data.timestamps[position])),
        "confirmation_time": _iso(confirmation_time),
        "price": price,
        "scale_hours": scale_hours,
        "source_input_identity": data.input_identity,
    }
    pivot_id = deterministic_hash(PIVOT_NAMESPACE, payload)
    return Pivot(
        pivot_id=pivot_id,
        asset=data.asset,
        timeframe=data.timeframe,
        role=role,
        source_position=position,
        pivot_time=_datetime_from_ns(data.timestamps[position]),
        confirmation_time=confirmation_time,
        available_at=available_at,
        price=_finite(price, field="pivot.price"),
        scale_hours=scale_hours,
        source_input_identity=data.input_identity,
    )


def _plateau_groups(
    positions: Sequence[int], *, price_at: Any
) -> tuple[tuple[int, ...], ...]:
    """Group only adjacent equal-price extrema; keep midpoint representative."""
    groups: list[list[int]] = []
    for position in positions:
        same_plateau = (
            bool(groups)
            and position == groups[-1][-1] + 1
            and price_at(position) == price_at(groups[-1][0])
        )
        if same_plateau:
            groups[-1].append(position)
        else:
            groups.append([position])
    return tuple(tuple(group) for group in groups)


def _hierarchical_pivots(
    data: ProviderInput, *, prefix_last_position: int, checkpoint: datetime
) -> tuple[Pivot, ...]:
    atr = _atr(data)
    merged: dict[tuple[str, int], Pivot] = {}
    for scale_hours, radius in _scale_radii(data.timeframe):
        candidates: dict[str, list[int]] = {role: [] for role in ROLES}
        end = min(prefix_last_position - radius, data.row_count - radius - 1)
        for position in range(radius, end + 1):
            window_low = min(data.low[position - radius : position + radius + 1])
            window_high = max(data.high[position - radius : position + radius + 1])
            if data.low[position] == window_low:
                candidates["support"].append(position)
            if data.high[position] == window_high:
                candidates["resistance"].append(position)
        for role, positions in candidates.items():
            groups = _plateau_groups(
                positions,
                price_at=lambda position: (
                    data.low[position] if role == "support" else data.high[position]
                ),
            )
            for group in groups:
                position = group[len(group) // 2]
                pivot = _make_pivot(data, atr, role, position, radius, scale_hours, checkpoint)
                if pivot is None:
                    continue
                key = (role, position)
                previous = merged.get(key)
                if previous is None or pivot.scale_hours > previous.scale_hours:
                    merged[key] = pivot
    return tuple(sorted(merged.values(), key=lambda pivot: (pivot.role, pivot.source_position, pivot.pivot_id)))


def _line_value(geometry: LineGeometry, timestamp: datetime) -> float:
    return _finite(geometry.value_at(timestamp), field="line projection")


def _geometry(first: Pivot, second: Pivot) -> LineGeometry:
    return LineGeometry(
        start_time=first.pivot_time,
        end_time=second.pivot_time,
        start_price=first.price,
        end_price=second.price,
    )


def _sustained_breach(
    data: ProviderInput,
    atr: Sequence[float],
    geometry: LineGeometry,
    role: str,
    start_position: int,
    end_position: int,
) -> tuple[bool, int | None]:
    consecutive = 0
    first_sustained: int | None = None
    for position in range(start_position, end_position + 1):
        timestamp = _datetime_from_ns(data.timestamps[position])
        line = _line_value(geometry, timestamp)
        threshold = BREACH_ATR * atr[position]
        close = _finite(data.close[position], field=f"close[{position}]")
        breach = close < line - threshold if role == "support" else close > line + threshold
        consecutive = consecutive + 1 if breach else 0
        if consecutive >= 2:
            first_sustained = position
            return True, first_sustained
    return False, first_sustained


def _seed_pool(
    data: ProviderInput,
    *,
    prefix_last_position: int,
    checkpoint: datetime,
) -> dict[str, tuple[Seed, ...]]:
    atr = _atr(data)
    pivots = _hierarchical_pivots(
        data, prefix_last_position=prefix_last_position, checkpoint=checkpoint
    )
    grouped = {
        role: tuple(pivot for pivot in pivots if pivot.role == role) for role in ROLES
    }
    result: dict[str, tuple[Seed, ...]] = {}
    for role in ROLES:
        seeds: list[Seed] = []
        role_pivots = grouped[role]
        for first, second in combinations(role_pivots, 2):
            if first.source_position >= second.source_position:
                continue
            span_hours = (
                second.pivot_time - first.pivot_time
            ).total_seconds() / 3_600
            if span_hours < 96:
                continue
            geometry = _geometry(first, second)
            touches = tuple(
                pivot
                for pivot in role_pivots
                if first.source_position <= pivot.source_position <= prefix_last_position
                and abs(pivot.price - _line_value(geometry, pivot.pivot_time))
                <= TOUCH_ATR * atr[pivot.source_position]
            )
            if len(touches) < 3:
                continue
            breached, _ = _sustained_breach(
                data,
                atr,
                geometry,
                role,
                second.source_position + 1,
                prefix_last_position,
            )
            if breached:
                continue
            checkpoint_close = _finite(data.close[prefix_last_position], field="checkpoint.close")
            checkpoint_line = _line_value(geometry, checkpoint)
            checkpoint_atr = atr[prefix_last_position]
            distance = abs(checkpoint_close - checkpoint_line) / checkpoint_atr
            if distance > MAX_DISTANCE_ATR or checkpoint_line <= 0:
                continue
            seed_payload = {
                "asset": data.asset,
                "timeframe": data.timeframe,
                "role": role,
                "first_pivot_id": first.pivot_id,
                "second_pivot_id": second.pivot_id,
                "touch_pivot_ids": [pivot.pivot_id for pivot in touches],
                "source_input_identity": data.input_identity,
                "checkpoint": _iso(checkpoint),
            }
            seed = Seed(
                seed_id=deterministic_hash(SEED_NAMESPACE, seed_payload),
                role=role,
                first=first,
                second=second,
                touches=touches,
                geometry=geometry,
                current_valid=True,
                current_distance_atr=distance,
                checkpoint_close=checkpoint_close,
                checkpoint_atr=checkpoint_atr,
            )
            seeds.append(seed)
            if len(seeds) > MAX_PAIR_SEEDS:
                raise StudyBlocked("pair-seed hypothesis cap exceeded; no truncation allowed")
        result[role] = tuple(sorted(seeds, key=lambda seed: seed.seed_id))
    return result


def _pivot_payloads(pivots: Iterable[Pivot]) -> list[dict[str, Any]]:
    return [pivot.to_dict() for pivot in pivots]


def _line_record(
    *,
    provider_id: str,
    seed: Seed,
    geometry: LineGeometry,
    pivots: Sequence[Pivot],
    checkpoint: datetime,
    data: ProviderInput,
    prefix_last_position: int,
    provider_evidence: Mapping[str, Any],
    anchor_pivots: Sequence[Pivot] | None = None,
) -> dict[str, Any]:
    atr = _atr(data)
    line_at_checkpoint = _line_value(geometry, checkpoint)
    checkpoint_close = _finite(data.close[prefix_last_position], field="checkpoint.close")
    current_atr = atr[prefix_last_position]
    ordered = tuple(sorted(pivots, key=lambda pivot: pivot.source_position))
    anchor_pivots = tuple(anchor_pivots or (ordered[0], ordered[-1]))
    identity_payload = {
        "provider_id": provider_id,
        "role": seed.role,
        "checkpoint": _iso(checkpoint),
        "source_input_identity": data.input_identity,
        "geometry": geometry.to_dict(),
        "anchor_pivot_ids": [pivot.pivot_id for pivot in anchor_pivots],
        "touch_or_inlier_ids": [pivot.pivot_id for pivot in ordered],
        "provider_evidence": dict(provider_evidence),
    }
    line_id = deterministic_hash(LINE_NAMESPACE, identity_payload)
    return {
        "line_id": line_id,
        "provider_id": provider_id,
        "role": seed.role,
        "checkpoint": _iso(checkpoint),
        "source_input_identity": data.input_identity,
        "available_at": _iso(checkpoint),
        "geometry": geometry.to_dict(),
        "anchor_pivots": _pivot_payloads(anchor_pivots),
        "touch_or_inlier_pivots": _pivot_payloads(ordered),
        "touch_or_inlier_count": len(ordered),
        "scale_48h_touch_or_inlier_count": sum(
            pivot.scale_hours == 48 for pivot in ordered
        ),
        "structural_span_hours": (
            ordered[-1].pivot_time - ordered[0].pivot_time
        ).total_seconds() / 3_600,
        "current_distance_atr": abs(checkpoint_close - line_at_checkpoint) / current_atr,
        "current_valid": seed.current_valid,
        "last_touch_or_inlier_age_bars": prefix_last_position - ordered[-1].source_position,
        "slope_per_second": geometry.slope_per_second,
        "projected_price_at_checkpoint": line_at_checkpoint,
        "provider_evidence": dict(provider_evidence),
    }


def _rank_hierarchical(seed: Seed, prefix_last_position: int) -> tuple[Any, ...]:
    return (
        -sum(pivot.scale_hours == 48 for pivot in seed.touches),
        -len(seed.touches),
        -sum(pivot.scale_hours for pivot in seed.touches),
        -(
            seed.second.pivot_time - seed.first.pivot_time
        ).total_seconds(),
        prefix_last_position - seed.touches[-1].source_position,
        seed.current_distance_atr,
        seed.seed_id,
    )


def _hierarchical_provider(
    seeds: Mapping[str, Sequence[Seed]],
    *,
    data: ProviderInput,
    checkpoint: datetime,
    prefix_last_position: int,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    provider_id = PRIMARY_PROVIDERS[0]
    for role in ROLES:
        candidates = sorted(seeds[role], key=lambda seed: _rank_hierarchical(seed, prefix_last_position))
        if candidates:
            seed = candidates[0]
            output.append(
                _line_record(
                    provider_id=provider_id,
                    seed=seed,
                    geometry=seed.geometry,
                    pivots=seed.touches,
                    checkpoint=checkpoint,
                    data=data,
                    prefix_last_position=prefix_last_position,
                    provider_evidence={
                        "method": provider_id,
                        "seed_id": seed.seed_id,
                        "rank": list(_rank_hierarchical(seed, prefix_last_position)),
                    },
                    anchor_pivots=(seed.first, seed.second),
                )
            )
    return output


def _median_sen_geometry(pivots: Sequence[Pivot]) -> tuple[float, float]:
    slopes = [
        (second.price - first.price)
        / (second.pivot_time.timestamp() - first.pivot_time.timestamp())
        for first, second in combinations(pivots, 2)
        if second.pivot_time > first.pivot_time
    ]
    if not slopes:
        raise StudyError("Theil-Sen requires at least two unique touch times")
    slope = float(statistics.median(slopes))
    intercept = float(
        statistics.median(
            pivot.price - slope * pivot.pivot_time.timestamp() for pivot in pivots
        )
    )
    return slope, intercept


def _geometry_from_slope(pivots: Sequence[Pivot], slope: float, intercept: float) -> LineGeometry:
    first, last = sorted(pivots, key=lambda pivot: pivot.source_position)[:: len(pivots) - 1 or 1]
    del first, last
    ordered = sorted(pivots, key=lambda pivot: pivot.source_position)
    first = ordered[0]
    last = ordered[-1]
    return LineGeometry(
        start_time=first.pivot_time,
        end_time=last.pivot_time,
        start_price=slope * first.pivot_time.timestamp() + intercept,
        end_price=slope * last.pivot_time.timestamp() + intercept,
    )


def _theil_sen_candidate(seed: Seed, *, data: ProviderInput, atr: Sequence[float], checkpoint: datetime, prefix_last_position: int) -> dict[str, Any] | None:
    if len(seed.touches) < 3:
        return None
    initial_slope, initial_intercept = _median_sen_geometry(seed.touches)
    initial_inliers = tuple(
        pivot
        for pivot in seed.touches
        if abs(
            pivot.price
            - (initial_slope * pivot.pivot_time.timestamp() + initial_intercept)
        )
        <= 0.5 * atr[pivot.source_position]
    )
    if len(initial_inliers) < 3:
        return None
    refit_slope, refit_intercept = _median_sen_geometry(initial_inliers)
    final_inliers = tuple(
        pivot
        for pivot in seed.touches
        if abs(
            pivot.price
            - (refit_slope * pivot.pivot_time.timestamp() + refit_intercept)
        )
        <= 0.5 * atr[pivot.source_position]
    )
    if len(final_inliers) < 3:
        return None
    ordered = tuple(sorted(final_inliers, key=lambda pivot: pivot.source_position))
    if (ordered[-1].pivot_time - ordered[0].pivot_time).total_seconds() < 96 * 3_600:
        return None
    geometry = _geometry_from_slope(ordered, refit_slope, refit_intercept)
    breached, _ = _sustained_breach(
        data, atr, geometry, seed.role, ordered[-1].source_position + 1, prefix_last_position
    )
    if breached:
        return None
    checkpoint_close = _finite(data.close[prefix_last_position], field="checkpoint.close")
    checkpoint_atr = atr[prefix_last_position]
    line_at_checkpoint = _line_value(geometry, checkpoint)
    distance = abs(checkpoint_close - line_at_checkpoint) / checkpoint_atr
    if line_at_checkpoint <= 0 or distance > MAX_DISTANCE_ATR:
        return None
    residuals = [
        abs(pivot.price - _line_value(geometry, pivot.pivot_time)) / atr[pivot.source_position]
        for pivot in ordered
    ]
    refit_id = deterministic_hash(
        SEED_NAMESPACE,
        {"seed_id": seed.seed_id, "inlier_ids": [pivot.pivot_id for pivot in ordered]},
    )
    rank = [
        -sum(pivot.scale_hours == 48 for pivot in ordered),
        -len(ordered),
        -(ordered[-1].pivot_time - ordered[0].pivot_time).total_seconds() / 3_600,
        float(statistics.median(residuals)),
        prefix_last_position - ordered[-1].source_position,
        distance,
        refit_id,
    ]
    record = _line_record(
        provider_id=PRIMARY_PROVIDERS[1],
        seed=seed,
        geometry=geometry,
        pivots=ordered,
        checkpoint=checkpoint,
        data=data,
        prefix_last_position=prefix_last_position,
        provider_evidence={
            "method": PRIMARY_PROVIDERS[1],
            "seed_id": seed.seed_id,
            "refit_id": refit_id,
            "initial_inlier_count": len(initial_inliers),
            "final_inlier_count": len(ordered),
            "median_abs_inlier_residual_atr": float(statistics.median(residuals)),
            "rank": rank,
        },
        anchor_pivots=(ordered[0], ordered[-1]),
    )
    return record


def _theil_sen_provider(
    seeds: Mapping[str, Sequence[Seed]],
    *,
    data: ProviderInput,
    checkpoint: datetime,
    prefix_last_position: int,
) -> list[dict[str, Any]]:
    atr = _atr(data)
    deduped: dict[str, dict[str, Any]] = {}
    for role in ROLES:
        for seed in seeds[role]:
            record = _theil_sen_candidate(
                seed,
                data=data,
                atr=atr,
                checkpoint=checkpoint,
                prefix_last_position=prefix_last_position,
            )
            if record is None:
                continue
            key = canonical_json(
                [pivot["pivot_id"] for pivot in record["touch_or_inlier_pivots"]]
            )
            previous = deduped.get(key)
            if previous is None or record["provider_evidence"]["seed_id"] < previous["provider_evidence"]["seed_id"]:
                deduped[key] = record
    output: list[dict[str, Any]] = []
    for role in ROLES:
        candidates = [record for record in deduped.values() if record["role"] == role]
        candidates.sort(key=lambda record: tuple(record["provider_evidence"]["rank"]))
        if candidates:
            output.append(candidates[0])
    return output


def _control_provider(
    seeds: Mapping[str, Sequence[Seed]],
    *,
    provider_id: str,
    data: ProviderInput,
    checkpoint: datetime,
    prefix_last_position: int,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for role in ROLES:
        if provider_id == CONTROL_PROVIDERS[0]:
            ranked = sorted(
                seeds[role],
                key=lambda seed: (-seed.second.source_position, -seed.first.source_position, seed.seed_id),
            )
        else:
            ranked = sorted(seeds[role], key=lambda seed: seed.seed_id)
        if ranked:
            seed = ranked[0]
            output.append(
                _line_record(
                    provider_id=provider_id,
                    seed=seed,
                    geometry=seed.geometry,
                    pivots=seed.touches,
                    checkpoint=checkpoint,
                    data=data,
                    prefix_last_position=prefix_last_position,
                    provider_evidence={
                        "method": provider_id,
                        "seed_id": seed.seed_id,
                    },
                    anchor_pivots=(seed.first, seed.second),
                )
            )
    return output


def _line_projection(line: Mapping[str, Any], timestamp: datetime) -> float:
    geometry = LineGeometry.from_dict(line["geometry"])
    return _line_value(geometry, timestamp)


def _future_evaluation(
    line: Mapping[str, Any],
    *,
    data: ProviderInput,
    prefix_last_position: int,
    checkpoint: datetime,
) -> dict[str, Any]:
    interval = _interval(data)
    atr = _atr(data)
    role = line["role"]
    geometry = LineGeometry.from_dict(line["geometry"])
    result: dict[str, Any] = {}
    for horizon_hours in HORIZONS_HOURS:
        positions = _future_window_positions(
            data,
            checkpoint=checkpoint,
            horizon_hours=horizon_hours,
        )
        breach_run = 0
        first_breach: int | None = None
        first_contact: int | None = None
        first_contact_position: int | None = None
        reaction = False
        contact_line = None
        contact_atr = None
        for position in positions:
            timestamp = _datetime_from_ns(data.timestamps[position])
            line_price = _line_value(geometry, timestamp)
            threshold = BREACH_ATR * atr[position]
            close = _finite(data.close[position], field=f"future.close[{position}]")
            breached = close < line_price - threshold if role == "support" else close > line_price + threshold
            breach_run = breach_run + 1 if breached else 0
            offset = int(round((timestamp - checkpoint).total_seconds() / interval))
            if breach_run >= 2 and first_breach is None:
                first_breach = offset
            if first_contact is None:
                touched = (
                    data.low[position] <= line_price + TOUCH_ATR * atr[position]
                    and data.high[position] >= line_price - TOUCH_ATR * atr[position]
                )
                if touched:
                    first_contact = offset
                    first_contact_position = position
                    contact_line = line_price
                    contact_atr = atr[position]
            if (
                first_contact_position is not None
                and position > first_contact_position
                and first_breach is None
                and contact_line is not None
                and contact_atr is not None
            ):
                reaction = reaction or (
                    data.high[position] - contact_line >= REACTION_ATR * contact_atr
                    if role == "support"
                    else contact_line - data.low[position] >= REACTION_ATR * contact_atr
                )
        survives = first_breach is None
        result[str(horizon_hours)] = {
            "survives_tolerant_owner_tf": survives,
            "has_zone_contact": first_contact is not None,
            "zone_contact_and_survives": first_contact is not None and survives,
            "has_role_consistent_reaction": reaction,
            "first_contact_offset_bars": first_contact,
            "first_sustained_breach_offset_bars": first_breach,
        }
    return result


def _output_identity(outputs: Mapping[str, Any]) -> str:
    return deterministic_hash("trendline_v2_phase_11r1_derivation", outputs)


def _run_checkpoint(
    cp: ScopeCheckpoint,
    *,
    method_ids: Sequence[str] = VALIDATION_METHODS,
    evaluate_future: bool = True,
) -> dict[str, Any]:
    method_ids = tuple(method_ids)
    unknown = set(method_ids) - set(VALIDATION_METHODS)
    if unknown or not method_ids or len(set(method_ids)) != len(method_ids):
        raise StudyError(f"invalid study methods: {list(method_ids)}")
    confirmed_pivots = _hierarchical_pivots(
        cp.data, prefix_last_position=cp.prefix_last_position, checkpoint=cp.checkpoint
    )
    seeds = _seed_pool(
        cp.data,
        prefix_last_position=cp.prefix_last_position,
        checkpoint=cp.checkpoint,
    )
    outputs: dict[str, list[dict[str, Any]]] = {}
    for method_id in method_ids:
        if method_id == PRIMARY_PROVIDERS[0]:
            lines = _hierarchical_provider(
                seeds,
                data=cp.data,
                checkpoint=cp.checkpoint,
                prefix_last_position=cp.prefix_last_position,
            )
        elif method_id == PRIMARY_PROVIDERS[1]:
            lines = _theil_sen_provider(
                seeds,
                data=cp.data,
                checkpoint=cp.checkpoint,
                prefix_last_position=cp.prefix_last_position,
            )
        else:
            lines = _control_provider(
                seeds,
                provider_id=method_id,
                data=cp.data,
                checkpoint=cp.checkpoint,
                prefix_last_position=cp.prefix_last_position,
            )
        outputs[method_id] = lines
    for lines in outputs.values():
        for line in lines:
            line["future_evaluation"] = (
                _future_evaluation(
                    line,
                    data=cp.data,
                    prefix_last_position=cp.prefix_last_position,
                    checkpoint=cp.checkpoint,
                )
                if evaluate_future
                else {}
            )
        lines.sort(key=lambda line: (line["role"], line["line_id"]))
    return {
        "dataset_id": cp.dataset_id,
        "checkpoint_index": cp.checkpoint_index,
        "checkpoint": _iso(cp.checkpoint),
        "source_input_identity": cp.data.input_identity,
        "prefix_last_position": cp.prefix_last_position,
        "confirmed_pivot_counts_by_scale_role": {
            str(scale): {
                role: sum(
                    pivot.scale_hours == scale and pivot.role == role
                    for pivot in confirmed_pivots
                )
                for role in ROLES
            }
            for scale in SCALES_HOURS
        },
        "seed_pool_counts": {role: len(seeds[role]) for role in ROLES},
        "outputs": outputs,
        "derivation_identity": _output_identity(outputs),
    }


def _stability(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any],
    *,
    data: ProviderInput,
    provider_id: str = PRIMARY_PROVIDERS[0],
) -> list[dict[str, Any]]:
    current_by_role = {line["role"]: line for line in current["outputs"][provider_id]}
    previous_by_role = (
        {line["role"]: line for line in previous["outputs"][provider_id]}
        if previous is not None
        else {}
    )
    events: list[dict[str, Any]] = []
    for role in ROLES:
        old = previous_by_role.get(role)
        new = current_by_role.get(role)
        if old is None and new is None:
            events.append({"role": role, "state": "absence"})
            continue
        if old is None:
            events.append({"role": role, "state": "birth", "line_id": new["line_id"]})
            continue
        if new is None:
            events.append({"role": role, "state": "absence", "previous_line_id": old["line_id"]})
            continue
        old_ids = {pivot["pivot_id"] for pivot in old["anchor_pivots"]}
        new_ids = {pivot["pivot_id"] for pivot in new["anchor_pivots"]}
        union = old_ids | new_ids
        jaccard = len(old_ids & new_ids) / len(union) if union else 1.0
        checkpoint = _parse_iso(current["checkpoint"], field="checkpoint")
        atr = _atr(data)[current["prefix_last_position"]]
        projection = abs(
            _line_projection(old, checkpoint) - _line_projection(new, checkpoint)
        ) / atr
        slope_bps = (
            abs(old["slope_per_second"] - new["slope_per_second"])
            * 86_400
            / data.close[current["prefix_last_position"]]
            * 10_000
        )
        continuation = jaccard >= 0.5 or (projection <= 0.75 and slope_bps <= 20)
        events.append(
            {
                "role": role,
                "state": "continuation" if continuation else "replacement",
                "previous_line_id": old["line_id"],
                "line_id": new["line_id"],
                "anchor_jaccard": jaccard,
                "projection_distance_atr": projection,
                "slope_distance_bps_per_day": slope_bps,
            }
        )
    return events


def _attach_stability(
    scope: ScopeDataset,
    runs: Sequence[Mapping[str, Any]],
    *,
    method_ids: Sequence[str] = VALIDATION_METHODS,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    previous = None
    data_by_checkpoint = {
        checkpoint.checkpoint_index: checkpoint.data
        for checkpoint in scope.checkpoints
    }
    for run in runs:
        copy = dict(run)
        data = data_by_checkpoint.get(
            run.get("checkpoint_index"), scope.data
        )
        primary = next(
            (method for method in method_ids if method in PRIMARY_PROVIDERS),
            None,
        )
        copy["stability"] = (
            _stability(previous, run, data=data, provider_id=primary)
            if primary is not None
            else []
        )
        copy["provider_stability"] = {
            provider_id: _stability(previous, run, data=data, provider_id=provider_id)
            for provider_id in method_ids
        }
        result.append(copy)
        previous = run
    return result


def _collect_lines(runs: Sequence[Mapping[str, Any]], provider_id: str) -> list[Mapping[str, Any]]:
    return [line for run in runs for line in run["outputs"][provider_id]]


def _outcome_rates(lines: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for horizon in HORIZONS_HOURS:
        rows = [
            line.get("future_evaluation", {}).get(str(horizon))
            for line in lines
        ]
        rows = [row for row in rows if row is not None]
        def rate(field: str) -> float | None:
            return sum(bool(row.get(field)) for row in rows) / len(rows) if rows else None
        def count(field: str) -> int:
            return sum(bool(row.get(field)) for row in rows)
        result[str(horizon)] = {
            "sample_count": len(rows),
            "evaluable_count": len(rows),
            "survival_rate": rate("survives_tolerant_owner_tf"),
            "survival_success_count": count("survives_tolerant_owner_tf"),
            "zone_contact_and_survival_rate": rate("zone_contact_and_survives"),
            "zone_contact_and_survival_success_count": count("zone_contact_and_survives"),
            "reaction_rate": rate("has_role_consistent_reaction"),
            "reaction_success_count": count("has_role_consistent_reaction"),
            "contact_rate": rate("has_zone_contact"),
            "contact_success_count": count("has_zone_contact"),
        }
    return result


def _continuation_rates(
    runs: Sequence[Mapping[str, Any]], provider_id: str
) -> list[float]:
    values = [
        event["anchor_jaccard"]
        for run in runs
        for event in run.get("provider_stability", {}).get(provider_id, run.get("stability", []))
        if event["state"] in {"continuation", "replacement"} and "anchor_jaccard" in event
    ]
    return values


def _continuation_state_counts(
    runs: Sequence[Mapping[str, Any]], provider_id: str
) -> tuple[int, int]:
    events = [
        event
        for run in runs
        for event in run.get("provider_stability", {}).get(provider_id, [])
    ]
    return (
        sum(event.get("state") == "continuation" for event in events),
        sum(event.get("state") == "replacement" for event in events),
    )


def _matched_control_lines(
    runs: Sequence[Mapping[str, Any]],
    *,
    primary_provider_id: str,
    control_provider_id: str,
) -> tuple[
    tuple[Mapping[str, Any], ...],
    tuple[Mapping[str, Any], ...],
    tuple[tuple[int, str], ...],
]:
    """Return exact checkpoint-role samples shared by primary and control."""
    primary_by_key: dict[tuple[int, str], Mapping[str, Any]] = {}
    control_by_key: dict[tuple[int, str], Mapping[str, Any]] = {}
    for run in runs:
        checkpoint_index = run.get("checkpoint_index")
        if isinstance(checkpoint_index, bool) or not isinstance(checkpoint_index, int):
            raise StudyError("matched control checkpoint index is invalid")
        for provider_id, destination in (
            (primary_provider_id, primary_by_key),
            (control_provider_id, control_by_key),
        ):
            for line in run.get("outputs", {}).get(provider_id, ()):
                role = line.get("role")
                if role not in ROLES:
                    raise StudyError("matched control line role is invalid")
                key = (checkpoint_index, role)
                if key in destination:
                    raise StudyError(
                        "matched control requires one line per checkpoint-role key"
                    )
                destination[key] = line
    primary_keys = tuple(sorted(primary_by_key))
    control_keys = tuple(sorted(control_by_key))
    missing = tuple(key for key in primary_keys if key not in control_by_key)
    if missing:
        raise StudyError(
            "matched latest-wide control missing checkpoint-role keys: "
            f"{list(missing)}"
        )
    matched_control_keys = tuple(key for key in control_keys if key in primary_by_key)
    if matched_control_keys != primary_keys:
        raise StudyError("matched latest-wide control sample keys do not match")
    return (
        tuple(primary_by_key[key] for key in primary_keys),
        tuple(control_by_key[key] for key in primary_keys),
        primary_keys,
    )


def _method_metrics(
    dataset_id: str,
    runs: Sequence[Mapping[str, Any]],
    provider_id: str,
    control_metrics: Mapping[str, Any] | None,
) -> dict[str, Any]:
    lines = _collect_lines(runs, provider_id)
    support_count = sum(any(line["role"] == "support" for line in run["outputs"][provider_id]) for run in runs)
    resistance_count = sum(any(line["role"] == "resistance" for line in run["outputs"][provider_id]) for run in runs)
    both_count = sum(
        {line["role"] for line in run["outputs"][provider_id]} == set(ROLES)
        for run in runs
    )
    continuation = _continuation_rates(runs, provider_id)
    continuation_state_count, replacement_state_count = _continuation_state_counts(
        runs, provider_id
    )
    matched_latest_wide_outcomes: dict[str, Any] | None = None
    matched_latest_wide_sample_keys: tuple[tuple[int, str], ...] = ()
    if provider_id in PRIMARY_PROVIDERS and control_metrics is not None:
        _, matched_control_lines, matched_latest_wide_sample_keys = _matched_control_lines(
            runs,
            primary_provider_id=provider_id,
            control_provider_id=CONTROL_PROVIDERS[0],
        )
        matched_latest_wide_outcomes = _outcome_rates(matched_control_lines)
    inversion = 0
    paired = 0
    for run in runs:
        by_role = {line["role"]: line for line in run["outputs"][provider_id]}
        if set(by_role) == set(ROLES):
            paired += 1
            timestamp = _parse_iso(run["checkpoint"], field="checkpoint")
            if _line_projection(by_role["support"], timestamp) > _line_projection(by_role["resistance"], timestamp):
                inversion += 1
    spans = [line["structural_span_hours"] for line in lines]
    touches = [line["touch_or_inlier_count"] for line in lines]
    distances = [line["current_distance_atr"] for line in lines]
    outcomes = _outcome_rates(lines)
    deltas: dict[str, Any] = {}
    if control_metrics is not None:
        if matched_latest_wide_outcomes is None:
            raise StudyError("primary utility metrics require matched control outcomes")
        for horizon in HORIZONS_HOURS:
            key = str(horizon)
            current = outcomes[key]
            control = matched_latest_wide_outcomes[key]
            for metric, count_field in (
                ("survival_delta", "survival_success_count"),
                ("zone_contact_and_survival_delta", "zone_contact_and_survival_success_count"),
                ("reaction_delta", "reaction_success_count"),
            ):
                left_denominator = current["evaluable_count"]
                right_denominator = control["evaluable_count"]
                left = current[count_field] / left_denominator if left_denominator else None
                right = control[count_field] / right_denominator if right_denominator else None
                deltas.setdefault(key, {})[metric] = (
                    left - right if left is not None and right is not None else None
                )
    result = {
        "dataset_id": dataset_id,
        "provider_id": provider_id,
        "checkpoint_count": len(runs),
        "support_present_count": support_count,
        "resistance_present_count": resistance_count,
        "both_present_count": both_count,
        "coverage": {
            "support": support_count / len(runs) if runs else 0.0,
            "resistance": resistance_count / len(runs) if runs else 0.0,
            "both": both_count / len(runs) if runs else 0.0,
        },
        "touch_count": _stats(touches),
        "structural_span_hours": _stats(spans),
        "channel_inversion_count": inversion,
        "paired_count": paired,
        "current_distance_atr": _stats(distances),
        "channel_inversion_rate": inversion / paired if paired else 0.0,
        "current_validity_rate": sum(line["current_valid"] for line in lines) / len(lines) if lines else 0.0,
        "continuation_state_count": continuation_state_count,
        "replacement_state_count": replacement_state_count,
        "adjacent_continuation_rate": (
            continuation_state_count / (continuation_state_count + replacement_state_count)
            if continuation_state_count + replacement_state_count
            else 0.0
        ),
        "adjacent_continuation_values": continuation,
        "outcomes": outcomes,
        "deltas_vs_latest_wide": deltas,
        "seed_pool_counts": {
            role: sum(run["seed_pool_counts"][role] for run in runs) for role in ROLES
        },
    }
    if provider_id in PRIMARY_PROVIDERS and control_metrics is not None:
        result.update(
            {
                "matched_latest_wide_sample_keys": [
                    [checkpoint_index, role]
                    for checkpoint_index, role in matched_latest_wide_sample_keys
                ],
                "matched_latest_wide_sample_count": len(matched_latest_wide_sample_keys),
                "matched_latest_wide_outcomes": matched_latest_wide_outcomes,
                "matched_latest_wide_control_id": CONTROL_PROVIDERS[0],
            }
        )
    return result


def _structural_gate(
    metrics: Mapping[str, Any], *, phase: str
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if phase == "temporal" and metrics.get("checkpoint_count") != 5:
        reasons.append("temporal_checkpoint_count_not_5")
    coverage = metrics.get("coverage", {})
    if phase == "temporal":
        if metrics.get("support_present_count", 0) < 4:
            reasons.append("temporal_support_present_below_4")
        if metrics.get("resistance_present_count", 0) < 4:
            reasons.append("temporal_resistance_present_below_4")
        if metrics.get("both_present_count", 0) < 3:
            reasons.append("temporal_both_present_below_3")
        if metrics.get("channel_inversion_count") != 0:
            reasons.append("temporal_channel_inversion")
        if _value_or(metrics.get("current_validity_rate"), -math.inf) < 1.0:
            reasons.append("temporal_current_validity_below_1")
        if _value_or(metrics.get("structural_span_hours", {}).get("median"), -math.inf) < 168:
            reasons.append("temporal_median_span_below_168h")
        if _value_or(metrics.get("adjacent_continuation_rate"), -math.inf) < 0.40:
            reasons.append("temporal_adjacent_continuation_below_0.40")
        return not reasons, reasons
    if _value_or(coverage.get("support"), -math.inf) < 0.70:
        reasons.append("support_coverage_below_0.70")
    if _value_or(coverage.get("resistance"), -math.inf) < 0.70:
        reasons.append("resistance_coverage_below_0.70")
    if _value_or(coverage.get("both"), -math.inf) < 0.60:
        reasons.append("both_coverage_below_0.60")
    if _value_or(metrics.get("touch_count", {}).get("median"), -math.inf) < 3:
        reasons.append("median_touch_below_3")
    if _value_or(metrics.get("structural_span_hours", {}).get("median"), -math.inf) < 168:
        reasons.append("median_span_below_168h")
    if _value_or(metrics.get("channel_inversion_count"), math.inf) > 0:
        reasons.append("channel_inversion")
    if _value_or(metrics.get("current_validity_rate"), -math.inf) < 1.0:
        reasons.append("current_validity_below_1")
    if _value_or(metrics.get("current_distance_atr", {}).get("median"), math.inf) > 6:
        reasons.append("median_distance_above_6atr")
    continuation_min = 0.40 if phase == "holdout" else 0.50
    if _value_or(metrics.get("adjacent_continuation_rate"), -math.inf) < continuation_min:
        reasons.append(f"adjacent_continuation_below_{continuation_min:.2f}")
    return not reasons, reasons


def _utility_gate(
    metrics: Mapping[str, Any], *, phase: str
) -> tuple[bool, list[str]]:
    if phase not in {"validation", "holdout"}:
        return True, []
    reasons: list[str] = []
    gates = (
        (
            (48, "survival_delta", 0.0),
            (96, "survival_delta", 0.0),
            (96, "zone_contact_and_survival_delta", 0.0),
            (96, "reaction_delta", -0.02),
        )
        if phase == "validation"
        else (
            (96, "survival_delta", 0.0),
            (96, "zone_contact_and_survival_delta", 0.0),
            (96, "reaction_delta", -0.02),
        )
    )
    for horizon, field, minimum in gates:
        value = metrics["deltas_vs_latest_wide"].get(str(horizon), {}).get(field)
        if value is None or value < minimum:
            reasons.append(f"{field}_{horizon}h_below_{minimum}")
    return not reasons, reasons


def _gate(metrics: Mapping[str, Any], *, phase: str) -> tuple[bool, list[str]]:
    structural_passed, structural_reasons = _structural_gate(metrics, phase=phase)
    utility_passed, utility_reasons = _utility_gate(metrics, phase=phase)
    return (
        structural_passed and utility_passed,
        [*structural_reasons, *utility_reasons],
    )


def _analyze_scope(
    scope: ScopeDataset,
    *,
    method_ids: Sequence[str] = VALIDATION_METHODS,
    phase: str = "validation",
) -> tuple[dict[str, Any], dict[str, Any]]:
    method_ids = tuple(method_ids)
    if (
        not method_ids
        or len(set(method_ids)) != len(method_ids)
        or set(method_ids) - set(VALIDATION_METHODS)
    ):
        raise StudyError(f"invalid scope method set: {list(method_ids)}")
    evaluate_future = phase != "temporal"
    first = [
        _run_checkpoint(
            cp, method_ids=method_ids, evaluate_future=evaluate_future
        )
        for cp in scope.checkpoints
    ]
    second = [
        _run_checkpoint(
            cp, method_ids=method_ids, evaluate_future=evaluate_future
        )
        for cp in scope.checkpoints
    ]
    for left, right in zip(first, second):
        if left["derivation_identity"] != right["derivation_identity"]:
            raise StudyError(f"non-deterministic derivation: {scope.dataset_id}")
    runs = _attach_stability(scope, first, method_ids=method_ids)
    control = (
        _method_metrics(scope.dataset_id, runs, CONTROL_PROVIDERS[0], None)
        if CONTROL_PROVIDERS[0] in method_ids
        else None
    )
    metrics: dict[str, Any] = {
        provider_id: _method_metrics(
            scope.dataset_id,
            runs,
            provider_id,
            control if provider_id in PRIMARY_PROVIDERS else None,
        )
        for provider_id in method_ids
    }
    for provider_id, values in metrics.items():
        if provider_id in PRIMARY_PROVIDERS:
            values["structural_gate_passed"], values["structural_rejection_reasons"] = _structural_gate(
                values, phase=phase
            )
            values["gate_passed"], values["rejection_reasons"] = _gate(values, phase=phase)
        else:
            values["structural_gate_passed"], values["structural_rejection_reasons"] = (
                _structural_gate(values, phase=phase)
            )
            values["gate_passed"] = False
            values["rejection_reasons"] = ["control_only"]
    membership = {
        "dataset_id": scope.dataset_id,
        "checkpoint_count": len(scope.checkpoints),
        "checkpoints": runs,
        "input_identity": scope.data.input_identity,
        "method_ids": list(method_ids),
        "derivation_repeats": 2,
        "method_derivation_count": len(scope.checkpoints) * len(method_ids) * 2,
    }
    return {
        **membership,
        "membership_id": deterministic_hash("phase11r1_membership", membership),
    }, {
        **metrics,
        "metrics_id": deterministic_hash("phase11r1_metrics", metrics),
    }


def _aggregate_metrics(
    dataset_metrics: Mapping[str, Mapping[str, Any]],
    provider_id: str,
    *,
    phase: str,
) -> dict[str, Any]:
    values = {
        dataset_id: metrics[provider_id]
        for dataset_id, metrics in dataset_metrics.items()
    }

    def pooled_counts(horizon: int, field: str) -> tuple[int, int]:
        successes = 0
        evaluable = 0
        for metric in values.values():
            outcome = metric.get("outcomes", {}).get(str(horizon), {})
            try:
                successes += int(_value_or(outcome.get(field), 0))
                evaluable += int(_value_or(outcome.get("evaluable_count"), 0))
            except (TypeError, ValueError):
                return 0, 0
        return successes, evaluable

    def pooled_rate(horizon: int, field: str) -> float | None:
        successes, evaluable = pooled_counts(horizon, field)
        return successes / evaluable if evaluable else None

    def pooled_delta(horizon: int, field: str) -> float | None:
        provider_field = {
            "survival_delta": "survival_success_count",
            "zone_contact_and_survival_delta": "zone_contact_and_survival_success_count",
            "reaction_delta": "reaction_success_count",
        }[field]
        provider_successes = 0
        control_successes = 0
        provider_evaluable = 0
        control_evaluable = 0
        for dataset_id, metric in values.items():
            provider_outcome = metric.get("outcomes", {}).get(str(horizon), {})
            matched_control_outcomes = metric.get("matched_latest_wide_outcomes")
            if not isinstance(matched_control_outcomes, Mapping):
                return None
            control_outcome = matched_control_outcomes.get(str(horizon), {})
            try:
                provider_successes += int(_value_or(provider_outcome.get(provider_field), 0))
                provider_evaluable += int(_value_or(provider_outcome.get("evaluable_count"), 0))
                control_successes += int(_value_or(control_outcome.get(provider_field), 0))
                control_evaluable += int(_value_or(control_outcome.get("evaluable_count"), 0))
            except (TypeError, ValueError):
                return None
        if not provider_evaluable or not control_evaluable:
            return None
        return provider_successes / provider_evaluable - control_successes / control_evaluable

    structural = {
        dataset_id: {
            "passed": bool(metric.get("structural_gate_passed", False)),
            "rejection_reasons": list(metric.get("structural_rejection_reasons", [])),
        }
        for dataset_id, metric in values.items()
    }
    survival_deltas = [
        metric.get("deltas_vs_latest_wide", {})
        .get("96", {})
        .get("survival_delta")
        for metric in values.values()
    ]
    zone_survival_deltas = [
        metric.get("deltas_vs_latest_wide", {})
        .get("96", {})
        .get("zone_contact_and_survival_delta")
        for metric in values.values()
    ]
    result = {
        "provider_id": provider_id,
        "dataset_count": len(values),
        "per_dataset_structural_gates": structural,
        "all_dataset_structural_gates_passed": all(
            row["passed"] for row in structural.values()
        ),
        "coverage": {
            role: min(
                (
                    metric.get("coverage", {}).get(role)
                    for metric in values.values()
                    if metric.get("coverage", {}).get(role) is not None
                ),
                default=0.0,
            )
            for role in (*ROLES, "both")
        },
        "touch_count_median": _median(
            [
                metric.get("touch_count", {}).get("median")
                for metric in values.values()
                if metric.get("touch_count", {}).get("median") is not None
            ]
        ),
        "structural_span_hours_median": _median(
            [
                metric.get("structural_span_hours", {}).get("median")
                for metric in values.values()
                if metric.get("structural_span_hours", {}).get("median") is not None
            ]
        ),
        "channel_inversion_rate": max(
            (
                metric.get("channel_inversion_rate")
                for metric in values.values()
                if metric.get("channel_inversion_rate") is not None
            ),
            default=1.0,
        ),
        "current_validity_rate": min(
            (
                metric.get("current_validity_rate")
                for metric in values.values()
                if metric.get("current_validity_rate") is not None
            ),
            default=0.0,
        ),
        "median_distance_atr": _median(
            [
                metric.get("current_distance_atr", {}).get("median")
                for metric in values.values()
                if metric.get("current_distance_atr", {}).get("median") is not None
            ]
        ),
        "median_continuation_rate": _median(
            [
                metric.get("adjacent_continuation_rate")
                for metric in values.values()
                if metric.get("adjacent_continuation_rate") is not None
            ]
        ),
        "matched_latest_wide_sample_count": sum(
            int(_value_or(metric.get("matched_latest_wide_sample_count"), 0))
            for metric in values.values()
        ),
        "matched_latest_wide_control_id": CONTROL_PROVIDERS[0],
        "outcomes": {},
        "worst_dataset_96_survival_delta": min(
            (value for value in survival_deltas if value is not None),
            default=None,
        ),
        "worst_dataset_96_zone_survival_delta": min(
            (value for value in zone_survival_deltas if value is not None),
            default=None,
        ),
        "pooled_48_survival_delta": pooled_delta(48, "survival_delta"),
        "pooled_96_survival_delta": pooled_delta(96, "survival_delta"),
        "pooled_96_zone_survival_delta": pooled_delta(96, "zone_contact_and_survival_delta"),
        "pooled_96_reaction_delta": pooled_delta(96, "reaction_delta"),
    }
    for horizon in HORIZONS_HOURS:
        outcome = {
            "evaluable_count": sum(
                int(_value_or(metric.get("outcomes", {}).get(str(horizon), {}).get("evaluable_count"), 0))
                for metric in values.values()
            ),
        }
        for rate_field, count_field in (
            ("survival_rate", "survival_success_count"),
            ("zone_contact_and_survival_rate", "zone_contact_and_survival_success_count"),
            ("reaction_rate", "reaction_success_count"),
        ):
            successes = sum(
                int(_value_or(metric.get("outcomes", {}).get(str(horizon), {}).get(count_field), 0))
                for metric in values.values()
            )
            outcome[count_field] = successes
            outcome[rate_field] = (
                successes / outcome["evaluable_count"]
                if outcome["evaluable_count"]
                else None
            )
        result["outcomes"][str(horizon)] = outcome

    missing_survival_delta = any(value is None for value in survival_deltas)
    missing_zone_delta = any(value is None for value in zone_survival_deltas)
    if missing_survival_delta:
        result["worst_dataset_96_survival_delta"] = None
    if missing_zone_delta:
        result["worst_dataset_96_zone_survival_delta"] = None
    reasons: list[str] = []
    for dataset_id, row in structural.items():
        if not row["passed"]:
            reasons.extend(f"{dataset_id}:{reason}" for reason in row["rejection_reasons"])
    utility_gates = (
        (
            ("pooled_48_survival_delta", result["pooled_48_survival_delta"], 0.0),
            ("pooled_96_survival_delta", result["pooled_96_survival_delta"], 0.0),
            ("pooled_96_zone_survival_delta", result["pooled_96_zone_survival_delta"], 0.0),
            ("pooled_96_reaction_delta", result["pooled_96_reaction_delta"], -0.02),
        )
        if phase == "validation"
        else (
            ("pooled_96_survival_delta", result["pooled_96_survival_delta"], 0.0),
            ("pooled_96_zone_survival_delta", result["pooled_96_zone_survival_delta"], 0.0),
            ("pooled_96_reaction_delta", result["pooled_96_reaction_delta"], -0.02),
        )
    )
    for name, value, minimum in (*utility_gates, ("worst_dataset_96_survival_delta", result["worst_dataset_96_survival_delta"], -0.05)):
        if value is None or value < minimum:
            reasons.append(f"{name}_below_{minimum}")
    if missing_zone_delta and "worst_dataset_96_zone_survival_delta_below_-0.05" not in reasons:
        reasons.append("worst_dataset_96_zone_survival_delta_below_-0.05")
    result["gate_passed"] = result["all_dataset_structural_gates_passed"] and not any(
        reason.startswith(("pooled_", "worst_dataset_")) for reason in reasons
    )
    result["rejection_reasons"] = reasons
    return result


def _validation_lock(
    *,
    contract_id: str,
    dataset_metrics: Mapping[str, Mapping[str, Any]],
    ranking: Sequence[Mapping[str, Any]],
    winner: str | None,
) -> dict[str, Any]:
    validation_result_ids = {
        dataset_id: deterministic_hash("phase11r1_validation_dataset", metrics)
        for dataset_id, metrics in sorted(dataset_metrics.items())
    }
    payload = {
        "schema_version": "trendline_v2_phase_11r1_validation_lock_v1",
        "study_contract_id": contract_id,
        "source_identities": {
            "phase9c2_decision_id": PHASE9C2_DECISION_ID,
            "phase9c2_manifest_id": PHASE9C2_MANIFEST_ID,
            "phase9c2_output_inventory_sha256": PHASE9C2_OUTPUT_INVENTORY,
            "phase9c2_source_inventory_sha256": PHASE9C2_SOURCE_INVENTORY,
            "phase10c2_replay_contract_id": PHASE10C2_REPLAY_CONTRACT_ID,
            "phase10c2_decision_id": PHASE10C2_DECISION_ID,
            "phase10c2_manifest_id": PHASE10C2_MANIFEST_ID,
            "phase10c2_output_inventory_sha256": PHASE10C2_OUTPUT_INVENTORY,
            "phase10c2_source_inventory_sha256": PHASE10C2_SOURCE_INVENTORY,
            "phase11s1_contract_id": PHASE11S1_CONTRACT_ID,
            "phase11s1_decision_id": PHASE11S1_DECISION_ID,
            "phase11s1_manifest_id": PHASE11S1_MANIFEST_ID,
            "phase11s1_inventory_sha256": PHASE11S1_INVENTORY,
        },
        "validation_dataset_ids": list(VALIDATION_DATASETS),
        "validation_result_ids": validation_result_ids,
        "dataset_result_ids": validation_result_ids,
        "validation_method_ids": list(VALIDATION_METHODS),
        "validation_method_derivation_count": VALIDATION_CHECKPOINT_COUNT * len(VALIDATION_METHODS) * 2,
        "ordered_ranking": list(ranking),
        "winner_provider_id": winner,
        "holdout_access": False,
    }
    return {**payload, "validation_lock_id": deterministic_hash(LOCK_NAMESPACE, payload)}


def _rank_validation(aggregate: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    def descending(value: Any) -> float:
        return -(_value_or(value, -math.inf))

    rows = []
    for provider_id, metrics in aggregate.items():
        rows.append(
            {
                "provider_id": provider_id,
                "worst_dataset_96_zone_survival_delta": metrics["worst_dataset_96_zone_survival_delta"],
                "pooled_96_zone_survival_delta": metrics["pooled_96_zone_survival_delta"],
                "pooled_96_reaction_delta": metrics["pooled_96_reaction_delta"],
                "median_continuation_rate": metrics["median_continuation_rate"],
                "touch_count_median": metrics["touch_count_median"],
                "structural_span_hours_median": metrics["structural_span_hours_median"],
                "gate_passed": metrics["gate_passed"],
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            not row["gate_passed"],
            descending(row["worst_dataset_96_zone_survival_delta"]),
            descending(row["pooled_96_zone_survival_delta"]),
            descending(row["pooled_96_reaction_delta"]),
            descending(row["median_continuation_rate"]),
            descending(row["touch_count_median"]),
            descending(row["structural_span_hours_median"]),
            row["provider_id"],
        ),
    )


def _unopened_dataset(dataset_id: str, *, reason: str) -> tuple[dict[str, Any], dict[str, Any]]:
    membership = {
            "dataset_id": dataset_id,
            "status": "UNOPENED",
            "reason": reason,
            "checkpoint_memberships": [],
        }
    metrics = {
            "dataset_id": dataset_id,
            "status": "UNOPENED",
            "reason": reason,
            "providers": {},
        }
    return (
        {**membership, "membership_id": deterministic_hash("phase11r1_membership", membership)},
        {**metrics, "metrics_id": deterministic_hash("phase11r1_metrics", metrics)},
    )


def _source_audit(
    validation_members: Sequence[Mapping[str, Any]],
    *,
    holdout_accessed: bool,
    temporal_accessed: bool,
    method_derivation_counts: Mapping[str, int],
    scope_method_ids: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    payload = {
        "schema_version": "trendline_v2_phase_11r1_source_audit_v1",
        "source_audit_id": None,
        "phase9c2": {
            "root": str(VALIDATION_ROOT),
            "manifest_id": PHASE9C2_MANIFEST_ID,
            "output_inventory_sha256": PHASE9C2_OUTPUT_INVENTORY,
            "source_inventory_sha256": PHASE9C2_SOURCE_INVENTORY,
            "pre_run_inventory_sha256": _inventory_sha256(validation_members),
            "post_run_inventory_sha256": _inventory_sha256(_inventory(VALIDATION_ROOT)),
        },
        "phase10c2": {
            "root": str(TEMPORAL_ROOT),
            "manifest_id": PHASE10C2_MANIFEST_ID,
            "output_inventory_sha256": PHASE10C2_OUTPUT_INVENTORY,
            "source_inventory_sha256": PHASE10C2_SOURCE_INVENTORY,
        },
        "phase11s1": {
            "contract_id": PHASE11S1_CONTRACT_ID,
            "decision_id": PHASE11S1_DECISION_ID,
            "manifest_id": PHASE11S1_MANIFEST_ID,
            "inventory_sha256": PHASE11S1_INVENTORY,
        },
        "loaded_dataset_ids": list(VALIDATION_DATASETS)
        + (list(HOLDOUT_DATASETS) if holdout_accessed else [])
        + ([TEMPORAL_DATASET] if temporal_accessed else []),
        "holdout_accessed": holdout_accessed,
        "temporal_accessed": temporal_accessed,
        "network_request_count": 0,
        "legacy_execution_count": 0,
        "v2_provider_execution_count": 0,
        "method_derivation_counts": dict(method_derivation_counts),
        "scope_method_ids": {
            scope: list(methods) for scope, methods in scope_method_ids.items()
        },
    }
    payload["source_audit_id"] = deterministic_hash(
        SOURCE_AUDIT_NAMESPACE, {key: value for key, value in payload.items() if key != "source_audit_id"}
    )
    return payload


def _decision_payload(
    *,
    status: str,
    contract_id: str,
    validation: Mapping[str, Any],
    lock: Mapping[str, Any],
    holdout_status: str,
    temporal_status: str,
    method_derivation_counts: Mapping[str, int],
    scope_method_ids: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    payload = {
        "schema_version": "trendline_v2_phase_11r1_decision_v1",
        "study_status": status,
        "study_contract_id": contract_id,
        "validation_lock_id": lock["validation_lock_id"],
        "validation": validation,
        "holdout_status": holdout_status,
        "temporal_status": temporal_status,
        "method_derivation_counts": dict(method_derivation_counts),
        "method_derivation_count": sum(method_derivation_counts.values()),
        "maximum_method_derivations": 890,
        "scope_method_ids": {
            scope: list(methods) for scope, methods in scope_method_ids.items()
        },
        "provider_execution_count": 0,
        "network_request_count": 0,
        "legacy_execution_count": 0,
        "v2_provider_execution_count": 0,
        "parallel_execution_count": 0,
        "runtime_source_modifications": 0,
    }
    return {**payload, "decision_id": deterministic_hash(DECISION_NAMESPACE, payload)}


def _manifest(staging: Path, *, decision: Mapping[str, Any], contract_id: str) -> dict[str, Any]:
    members = tuple(item for item in _inventory(staging) if item["path"] != "manifest.json")
    expected_members = tuple(
        item for item in _expected_artifact_paths() if item != "manifest.json"
    )
    if tuple(item["path"] for item in members) != expected_members:
        raise StudyError("bundle artifact paths mismatch")
    payload = {
        "schema_version": "trendline_v2_phase_11r1_manifest_v1",
        "study_contract_id": contract_id,
        "decision_id": decision["decision_id"],
        "member_count": len(members),
        "members": list(members),
        "output_inventory_sha256": _inventory_sha256(members),
    }
    return {**payload, "manifest_id": deterministic_hash(MANIFEST_NAMESPACE, payload)}


def _without_id(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != field}


def _expected_artifact_paths() -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                "study_contract.json",
                "source_audit.json",
                "validation_lock.json",
                "cross_scope_summary.csv",
                "temporal_summary.csv",
                "decision.json",
                "manifest.json",
                *{
                    f"datasets/{dataset_id}/{member}"
                    for dataset_id in ALL_DATASETS
                    for member in ("checkpoint_membership.json", "provider_metrics.json")
                },
                f"temporal/{TEMPORAL_DATASET}/checkpoint_membership.json",
                f"temporal/{TEMPORAL_DATASET}/provider_metrics.json",
            }
        )
    )


def _verify_lock_bytes(path: Path, lock: Mapping[str, Any]) -> None:
    raw = path.read_bytes()
    if _load_json(path) != lock or raw != _canonical_bytes(lock):
        raise StudyError("validation lock canonical bytes mismatch")
    if deterministic_hash(LOCK_NAMESPACE, _without_id(lock, "validation_lock_id")) != lock.get(
        "validation_lock_id"
    ):
        raise StudyError("validation lock identity mismatch")


def _validate_pivot_record(
    pivot: Mapping[str, Any], *, data: ProviderInput
) -> None:
    required = {
        "pivot_id", "asset", "timeframe", "role", "source_position", "pivot_time",
        "confirmation_time", "available_at", "price", "scale_hours", "source_input_identity",
    }
    if set(pivot) != required:
        raise StudyError("pivot schema drift")
    role = pivot["role"]
    if role not in ROLES or pivot["asset"] != data.asset or pivot["timeframe"] != data.timeframe:
        raise StudyError("pivot source binding mismatch")
    position = pivot["source_position"]
    scale_hours = pivot["scale_hours"]
    if isinstance(position, bool) or not isinstance(position, int) or position < 0 or position >= data.row_count:
        raise StudyError("pivot source position invalid")
    radius_by_scale = dict(_scale_radii(data.timeframe))
    if scale_hours not in radius_by_scale:
        raise StudyError("pivot scale invalid")
    radius = radius_by_scale[scale_hours]
    confirmation_position = position + radius
    if confirmation_position >= data.row_count:
        raise StudyError("pivot confirmation position outside source")
    pivot_time = _datetime_from_ns(data.timestamps[position])
    confirmation_time = _datetime_from_ns(data.timestamps[confirmation_position])
    available_at = confirmation_time + timedelta(seconds=_interval(data))
    price = data.low[position] if role == "support" else data.high[position]
    if (
        pivot["pivot_time"] != _iso(pivot_time)
        or pivot["confirmation_time"] != _iso(confirmation_time)
        or pivot["available_at"] != _iso(available_at)
        or pivot["source_input_identity"] != data.input_identity
        or pivot["price"] != price
    ):
        raise StudyError("pivot raw OHLCV binding mismatch")
    identity_payload = {
        "asset": data.asset,
        "timeframe": data.timeframe,
        "role": role,
        "source_position": position,
        "pivot_time": _iso(pivot_time),
        "confirmation_time": _iso(confirmation_time),
        "price": price,
        "scale_hours": scale_hours,
        "source_input_identity": data.input_identity,
    }
    if pivot["pivot_id"] != deterministic_hash(PIVOT_NAMESPACE, identity_payload):
        raise StudyError("pivot identity mismatch")


def _validate_line_record(
    line: Mapping[str, Any],
    *,
    data: ProviderInput,
    checkpoint: datetime,
    prefix_last_position: int,
    allowed_provider_ids: Sequence[str] = VALIDATION_METHODS,
    evaluate_future: bool = True,
) -> None:
    if line.get("provider_id") not in tuple(allowed_provider_ids):
        raise StudyError("unknown research provider")
    if line.get("role") not in ROLES or line.get("available_at") != _iso(checkpoint):
        raise StudyError("line role or availability mismatch")
    if line.get("checkpoint") != _iso(checkpoint) or line.get("source_input_identity") != data.input_identity:
        raise StudyError("line checkpoint/source binding mismatch")
    geometry = LineGeometry.from_dict(line.get("geometry"))
    anchors = line.get("anchor_pivots")
    pivots = line.get("touch_or_inlier_pivots")
    if not isinstance(anchors, list) or not isinstance(pivots, list) or len(anchors) != 2 or len(pivots) < 3:
        raise StudyError("line pivot cardinality invalid")
    for pivot in pivots:
        _validate_pivot_record(pivot, data=data)
    pivot_ids = [pivot["pivot_id"] for pivot in pivots]
    if len(set(pivot_ids)) != len(pivot_ids):
        raise StudyError("line pivot IDs are not unique")
    ordered = sorted(pivots, key=lambda pivot: pivot["source_position"])
    pivot_id_set = {pivot["pivot_id"] for pivot in pivots}
    if any(anchor["pivot_id"] not in pivot_id_set for anchor in anchors):
        raise StudyError("line anchors do not bind touch/inlier population")
    if line["provider_id"] == PRIMARY_PROVIDERS[1] and anchors != [ordered[0], ordered[-1]]:
        raise StudyError("Theil-Sen anchors do not bind fitted endpoints")
    if line["touch_or_inlier_count"] != len(pivots):
        raise StudyError("line touch/inlier count mismatch")
    if line["scale_48h_touch_or_inlier_count"] != sum(pivot["scale_hours"] == 48 for pivot in pivots):
        raise StudyError("line scale count mismatch")
    span = (
        _parse_iso(ordered[-1]["pivot_time"], field="line.last_pivot")
        - _parse_iso(ordered[0]["pivot_time"], field="line.first_pivot")
    ).total_seconds() / 3_600
    if line["structural_span_hours"] != span:
        raise StudyError("line structural span mismatch")
    if geometry.start_time != _parse_iso(anchors[0]["pivot_time"], field="anchor.start") or geometry.end_time != _parse_iso(anchors[1]["pivot_time"], field="anchor.end"):
        raise StudyError("line geometry endpoint time mismatch")
    if line["provider_id"] != PRIMARY_PROVIDERS[1]:
        if geometry.start_price != anchors[0]["price"] or geometry.end_price != anchors[1]["price"]:
            raise StudyError("exact-pair geometry does not pass anchors")
    identity_payload = {
        "provider_id": line["provider_id"],
        "role": line["role"],
        "checkpoint": line["checkpoint"],
        "source_input_identity": line["source_input_identity"],
        "geometry": line["geometry"],
        "anchor_pivot_ids": [pivot["pivot_id"] for pivot in anchors],
        "touch_or_inlier_ids": pivot_ids,
        "provider_evidence": line["provider_evidence"],
    }
    if line["line_id"] != deterministic_hash(LINE_NAMESPACE, identity_payload):
        raise StudyError("line identity mismatch")
    atr = _atr(data)[prefix_last_position]
    checkpoint_line = _line_value(geometry, checkpoint)
    expected_distance = abs(data.close[prefix_last_position] - checkpoint_line) / atr
    if line["projected_price_at_checkpoint"] != checkpoint_line or line["current_distance_atr"] != expected_distance:
        raise StudyError("line current projection mismatch")
    expected_future = (
        _future_evaluation(
            line,
            data=data,
            prefix_last_position=prefix_last_position,
            checkpoint=checkpoint,
        )
        if evaluate_future
        else {}
    )
    if line.get("future_evaluation") != expected_future:
        raise StudyError("line future evidence mismatch")


def _validate_membership(
    membership: Mapping[str, Any],
    *,
    metrics: Mapping[str, Any],
    scope: ScopeDataset,
    expected_method_ids: Sequence[str] | None = None,
    phase: str = "validation",
) -> None:
    if membership.get("dataset_id") != scope.dataset_id or membership.get("input_identity") != scope.data.input_identity:
        raise StudyError("membership dataset/input binding mismatch")
    expected_method_ids = tuple(expected_method_ids or VALIDATION_METHODS)
    expected_checkpoint_count = len(scope.checkpoints)
    if membership.get("checkpoint_count") != expected_checkpoint_count or len(membership.get("checkpoints", [])) != expected_checkpoint_count:
        raise StudyError("membership checkpoint count mismatch")
    if tuple(membership.get("method_ids", ())) != expected_method_ids:
        raise StudyError("membership method set mismatch")
    expected_derivations = expected_checkpoint_count * len(expected_method_ids) * 2
    if (
        membership.get("derivation_repeats") != 2
        or membership.get("method_derivation_count") != expected_derivations
    ):
        raise StudyError("membership derivation accounting mismatch")
    if membership.get("membership_id") != deterministic_hash(
        "phase11r1_membership", _without_id(membership, "membership_id")
    ):
        raise StudyError("membership identity mismatch")
    expected_schedule = tuple(
        (checkpoint.checkpoint_index, checkpoint.checkpoint, checkpoint.prefix_last_position)
        for checkpoint in scope.checkpoints
    )
    evaluate_future = phase != "temporal"
    expected_runs = _attach_stability(
        scope,
        [
            _run_checkpoint(
                checkpoint,
                method_ids=expected_method_ids,
                evaluate_future=evaluate_future,
            )
            for checkpoint in scope.checkpoints
        ],
        method_ids=expected_method_ids,
    )
    for position, (run, (index, checkpoint, prefix_last), scope_checkpoint) in enumerate(
        zip(membership["checkpoints"], expected_schedule, scope.checkpoints)
    ):
        expected_run = expected_runs[position]
        if run != expected_run:
            raise StudyError("membership checkpoint replay mismatch")
        if run.get("checkpoint_index") != index or run.get("checkpoint") != _iso(checkpoint) or run.get("prefix_last_position") != prefix_last:
            raise StudyError("membership checkpoint boundary mismatch")
        if run.get("source_input_identity") != scope_checkpoint.data.input_identity:
            raise StudyError("membership source identity mismatch")
        if run.get("seed_pool_counts", {}).keys() != set(ROLES):
            raise StudyError("membership seed-pool role mismatch")
        expected_outputs = set(expected_method_ids)
        if set(run.get("outputs", {})) != expected_outputs:
            raise StudyError("membership provider output set mismatch")
        for lines in run["outputs"].values():
            for line in lines:
                _validate_line_record(
                    line,
                    data=scope_checkpoint.data,
                    checkpoint=checkpoint,
                    prefix_last_position=prefix_last,
                    allowed_provider_ids=expected_method_ids,
                    evaluate_future=evaluate_future,
                )
    if metrics.get("metrics_id") != deterministic_hash("phase11r1_metrics", _without_id(metrics, "metrics_id")):
        raise StudyError("provider metrics identity mismatch")
    control = (
        _method_metrics(
            scope.dataset_id,
            membership["checkpoints"],
            CONTROL_PROVIDERS[0],
            None,
        )
        if CONTROL_PROVIDERS[0] in expected_method_ids
        else None
    )
    expected_metrics = {}
    for provider_id in expected_method_ids:
        expected_metrics[provider_id] = _method_metrics(
            scope.dataset_id,
            membership["checkpoints"],
            provider_id,
            control if provider_id in PRIMARY_PROVIDERS else None,
        )
        if provider_id in PRIMARY_PROVIDERS:
            expected_metrics[provider_id]["structural_gate_passed"], expected_metrics[provider_id]["structural_rejection_reasons"] = _structural_gate(
                expected_metrics[provider_id], phase=phase
            )
            expected_metrics[provider_id]["gate_passed"], expected_metrics[provider_id]["rejection_reasons"] = _gate(
                expected_metrics[provider_id], phase=phase
            )
        else:
            expected_metrics[provider_id]["structural_gate_passed"], expected_metrics[provider_id]["structural_rejection_reasons"] = _structural_gate(
                expected_metrics[provider_id], phase=phase
            )
            expected_metrics[provider_id]["gate_passed"] = False
            expected_metrics[provider_id]["rejection_reasons"] = ["control_only"]
    if _without_id(metrics, "metrics_id") != expected_metrics:
        raise StudyError("provider metrics semantic mismatch")


def _cross_scope_summary_rows(
    validation_metrics: Mapping[str, Mapping[str, Any]],
    holdout_metrics: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    rows = []
    for dataset_id in ALL_DATASETS:
        metrics = (
            validation_metrics.get(dataset_id)
            or holdout_metrics.get(dataset_id)
            or {"status": "UNOPENED"}
        )
        rows.append(
            {
                "dataset_id": dataset_id,
                "scope": "validation" if dataset_id in VALIDATION_DATASETS else "holdout",
                "status": metrics.get("status", "ANALYZED"),
                "support_coverage": metrics.get(
                    PRIMARY_PROVIDERS[0], {}
                ).get("coverage", {}).get("support", ""),
                "resistance_coverage": metrics.get(
                    PRIMARY_PROVIDERS[0], {}
                ).get("coverage", {}).get("resistance", ""),
                "theil_sen_gate": metrics.get(
                    PRIMARY_PROVIDERS[1], {}
                ).get("gate_passed", ""),
            }
        )
    return tuple(rows)


def _temporal_summary_rows(temporal_membership: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    return (
        {
            "dataset_id": TEMPORAL_DATASET,
            "status": temporal_membership.get("status", "UNOPENED"),
            "reason": temporal_membership.get("reason", ""),
        },
    )


def _write_bundle(
    staging: Path,
    *,
    contract: Mapping[str, Any],
    contract_id: str,
    source_audit: Mapping[str, Any],
    lock: Mapping[str, Any],
    validation_memberships: Mapping[str, Mapping[str, Any]],
    validation_metrics: Mapping[str, Mapping[str, Any]],
    holdout_memberships: Mapping[str, Mapping[str, Any]],
    holdout_metrics: Mapping[str, Mapping[str, Any]],
    temporal_membership: Mapping[str, Any],
    temporal_metrics: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    _write_json(staging / "study_contract.json", {"contract_id": contract_id, "payload": contract})
    _write_json(staging / "source_audit.json", source_audit)
    _write_json(staging / "validation_lock.json", lock)
    (staging / "cross_scope_summary.csv").write_bytes(
        _csv_bytes(_cross_scope_summary_rows(validation_metrics, holdout_metrics))
    )
    (staging / "temporal_summary.csv").write_bytes(
        _csv_bytes(_temporal_summary_rows(temporal_membership))
    )
    for dataset_id in ALL_DATASETS:
        directory = staging / "datasets" / dataset_id
        directory.mkdir(parents=True, exist_ok=True)
        membership = validation_memberships.get(dataset_id) or holdout_memberships.get(dataset_id)
        metrics = validation_metrics.get(dataset_id) or holdout_metrics.get(dataset_id)
        if membership is None or metrics is None:
            membership, metrics = _unopened_dataset(dataset_id, reason="NO_VALIDATION_FINALIST")
        _write_json(directory / "checkpoint_membership.json", membership)
        _write_json(directory / "provider_metrics.json", metrics)
    temporal_directory = staging / "temporal" / TEMPORAL_DATASET
    temporal_directory.mkdir(parents=True, exist_ok=True)
    _write_json(temporal_directory / "checkpoint_membership.json", temporal_membership)
    _write_json(temporal_directory / "provider_metrics.json", temporal_metrics)
    _write_json(staging / "decision.json", decision)
    manifest = _manifest(staging, decision=decision, contract_id=contract_id)
    _write_json(staging / "manifest.json", manifest)
    return manifest


def _prepare_staging(output_root: Path) -> Path:
    if output_root.exists():
        raise FileExistsError(f"refusing existing output root: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f".{output_root.name}.", dir=output_root.parent))


def _publish(output_root: Path, staging: Path) -> None:
    if output_root.exists():
        raise FileExistsError(f"refusing existing output root: {output_root}")
    os.replace(staging, output_root)


def _run_analysis(output_root: Path) -> dict[str, Any]:
    staging = _prepare_staging(output_root)
    try:
        contract, contract_id = _validated_contract()
        source_members = _validate_manifest(
            VALIDATION_ROOT,
            expected_manifest=PHASE9C2_MANIFEST_ID,
            expected_inventory=PHASE9C2_OUTPUT_INVENTORY,
        )
        validation_scope = tuple(_load_scope_dataset(VALIDATION_ROOT, dataset) for dataset in VALIDATION_DATASETS)
        validation_memberships: dict[str, Mapping[str, Any]] = {}
        validation_metrics: dict[str, Mapping[str, Any]] = {}
        for scope in validation_scope:
            membership, metrics = _analyze_scope(
                scope, method_ids=VALIDATION_METHODS, phase="validation"
            )
            validation_memberships[scope.dataset_id] = membership
            validation_metrics[scope.dataset_id] = metrics
        aggregate = {
            provider_id: _aggregate_metrics(validation_metrics, provider_id, phase="validation")
            for provider_id in PRIMARY_PROVIDERS
        }
        ranking = _rank_validation(aggregate)
        winner = next((row["provider_id"] for row in ranking if row["gate_passed"]), None)
        lock = _validation_lock(
            contract_id=contract_id,
            dataset_metrics=validation_metrics,
            ranking=ranking,
            winner=winner,
        )
        _write_json(staging / "validation_lock.json", lock)
        _verify_lock_bytes(staging / "validation_lock.json", lock)
        holdout_memberships: dict[str, Mapping[str, Any]] = {}
        holdout_metrics: dict[str, Mapping[str, Any]] = {}
        temporal_membership: Mapping[str, Any] = {"status": "UNOPENED", "reason": "NO_VALIDATION_FINALIST", "checkpoint_memberships": []}
        temporal_metrics: Mapping[str, Any] = {"status": "UNOPENED", "reason": "NO_VALIDATION_FINALIST", "providers": {}}
        holdout_status = "UNOPENED_NO_VALIDATION_FINALIST"
        temporal_status = "UNOPENED_NO_HOLDOUT_PASS"
        status = "NO_INDEPENDENT_SPARSE_PROVIDER_FINALIST"
        method_derivation_counts = {
            "validation": VALIDATION_CHECKPOINT_COUNT * len(VALIDATION_METHODS) * 2,
            "holdout": 0,
            "temporal": 0,
        }
        scope_method_ids: dict[str, Sequence[str]] = {
            "validation": VALIDATION_METHODS,
            "holdout": (),
            "temporal": (),
        }
        if winner is not None:
            temporal_membership = {
                "status": "UNOPENED",
                "reason": "NO_HOLDOUT_PASS",
                "checkpoint_memberships": [],
            }
            temporal_metrics = {
                "status": "UNOPENED",
                "reason": "NO_HOLDOUT_PASS",
                "providers": {},
            }
            holdout_scope = _load_holdout_scope()
            for scope in holdout_scope:
                membership, metrics = _analyze_scope(
                    scope,
                    method_ids=(winner, CONTROL_PROVIDERS[0]),
                    phase="holdout",
                )
                holdout_memberships[scope.dataset_id] = membership
                holdout_metrics[scope.dataset_id] = metrics
            method_derivation_counts["holdout"] = (
                sum(len(scope.checkpoints) for scope in holdout_scope)
                * len((winner, CONTROL_PROVIDERS[0]))
                * 2
            )
            scope_method_ids["holdout"] = (winner, CONTROL_PROVIDERS[0])
            holdout_aggregate = _aggregate_metrics(
                holdout_metrics, winner, phase="holdout"
            )
            if not holdout_aggregate["gate_passed"]:
                status = "INDEPENDENT_SPARSE_PROVIDER_HOLDOUT_REJECTED"
                holdout_status = "REJECTED"
            else:
                holdout_status = "PASSED"
                temporal_scope = _load_temporal_scope()
                temporal_membership_raw, temporal_provider_metrics = _analyze_scope(
                    temporal_scope,
                    method_ids=(winner,),
                    phase="temporal",
                )
                temporal_metric = temporal_provider_metrics[winner]
                temporal_passed, temporal_reasons = _gate(
                    temporal_metric, phase="temporal"
                )
                temporal_metric["gate_passed"] = temporal_passed
                temporal_metric["rejection_reasons"] = temporal_reasons
                temporal_membership = {
                    **{
                        key: value
                        for key, value in temporal_membership_raw.items()
                        if key != "membership_id"
                    },
                    "status": "ANALYZED",
                }
                temporal_membership["membership_id"] = deterministic_hash(
                    "phase11r1_membership", _without_id(temporal_membership, "membership_id")
                )
                temporal_metrics = {
                    "dataset_id": TEMPORAL_DATASET,
                    "status": "ANALYZED",
                    "method_ids": [winner],
                    "providers": {winner: temporal_metric},
                }
                temporal_metrics["metrics_id"] = deterministic_hash(
                    "phase11r1_metrics", _without_id(temporal_metrics, "metrics_id")
                )
                method_derivation_counts["temporal"] = (
                    len(temporal_scope.checkpoints) * 1 * 2
                )
                scope_method_ids["temporal"] = (winner,)
                if temporal_passed:
                    temporal_status = "PASSED"
                    status = "INDEPENDENT_SPARSE_PROVIDER_PROMOTION_CANDIDATE"
                else:
                    temporal_status = "REJECTED"
                    status = "INDEPENDENT_SPARSE_PROVIDER_TEMPORAL_REJECTED"
        source_audit = _source_audit(
            source_members,
            holdout_accessed=bool(holdout_memberships),
            temporal_accessed=temporal_membership.get("status") == "ANALYZED",
            method_derivation_counts=method_derivation_counts,
            scope_method_ids=scope_method_ids,
        )
        decision = _decision_payload(
            status=status,
            contract_id=contract_id,
            validation={"aggregate": aggregate, "ranking": ranking, "winner_provider_id": winner},
            lock=lock,
            holdout_status=holdout_status,
            temporal_status=temporal_status,
            method_derivation_counts=method_derivation_counts,
            scope_method_ids=scope_method_ids,
        )
        manifest = _write_bundle(
            staging,
            contract=contract,
            contract_id=contract_id,
            source_audit=source_audit,
            lock=lock,
            validation_memberships=validation_memberships,
            validation_metrics=validation_metrics,
            holdout_memberships=holdout_memberships,
            holdout_metrics=holdout_metrics,
            temporal_membership=temporal_membership,
            temporal_metrics=temporal_metrics,
            decision=decision,
        )
        _publish(output_root, staging)
        return {
            "study_status": status,
            "decision_id": decision["decision_id"],
            "manifest_id": manifest["manifest_id"],
            "output_inventory_sha256": _inventory_sha256(
                tuple(item for item in _inventory(output_root) if item["path"] != "manifest.json")
            ),
            "validation_lock_id": lock["validation_lock_id"],
            "winner_provider_id": winner,
            "network_request_count": 0,
            "legacy_execution_count": 0,
            "v2_provider_execution_count": 0,
        }
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _verify_unopened_dataset(output_root: Path, dataset_id: str) -> None:
    membership = _load_json(
        output_root / "datasets" / dataset_id / "checkpoint_membership.json"
    )
    metrics = _load_json(output_root / "datasets" / dataset_id / "provider_metrics.json")
    expected_membership, expected_metrics = _unopened_dataset(
        dataset_id, reason="NO_VALIDATION_FINALIST"
    )
    if membership != expected_membership or metrics != expected_metrics:
        raise StudyError("unopened scope evidence mismatch")


def _verify_temporal_scope(
    output_root: Path,
    *,
    winner: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    scope = _load_temporal_scope()
    membership = _load_json(
        output_root / "temporal" / TEMPORAL_DATASET / "checkpoint_membership.json"
    )
    wrapper = _load_json(
        output_root / "temporal" / TEMPORAL_DATASET / "provider_metrics.json"
    )
    if membership.get("status") != "ANALYZED" or membership.get("method_ids") != [winner]:
        raise StudyError("temporal scope method/status mismatch")
    if (
        wrapper.get("status") != "ANALYZED"
        or wrapper.get("method_ids") != [winner]
        or set(wrapper.get("providers", {})) != {winner}
        or wrapper.get("metrics_id")
        != deterministic_hash("phase11r1_metrics", _without_id(wrapper, "metrics_id"))
    ):
        raise StudyError("temporal metrics wrapper mismatch")
    base_membership = {
        key: value for key, value in membership.items() if key not in {"status", "membership_id"}
    }
    base_membership["membership_id"] = deterministic_hash(
        "phase11r1_membership", base_membership
    )
    raw_metrics = {winner: wrapper["providers"][winner]}
    raw_metrics["metrics_id"] = deterministic_hash("phase11r1_metrics", raw_metrics)
    _validate_membership(
        base_membership,
        metrics=raw_metrics,
        scope=scope,
        expected_method_ids=(winner,),
        phase="temporal",
    )
    return membership, wrapper


def _verify_bundle(output_root: Path) -> dict[str, Any]:
    if not output_root.is_dir():
        raise StudyError(f"output bundle missing: {output_root}")
    contract_file = output_root / "study_contract.json"
    contract = _load_json(contract_file)
    expected_contract, expected_contract_id = _validated_contract()
    if contract_file.read_bytes() != _canonical_bytes(contract):
        raise StudyError("study contract is not canonical")
    if contract.get("contract_id") != expected_contract_id or contract.get("payload") != expected_contract:
        raise StudyError("study contract identity mismatch")

    source_audit = _load_json(output_root / "source_audit.json")
    if source_audit.get("source_audit_id") != deterministic_hash(
        SOURCE_AUDIT_NAMESPACE, _without_id(source_audit, "source_audit_id")
    ):
        raise StudyError("source audit identity mismatch")
    lock = _load_json(output_root / "validation_lock.json")
    _verify_lock_bytes(output_root / "validation_lock.json", lock)
    decision = _load_json(output_root / "decision.json")
    if decision.get("decision_id") != deterministic_hash(
        DECISION_NAMESPACE, _without_id(decision, "decision_id")
    ):
        raise StudyError("decision identity mismatch")
    if (
        decision.get("study_contract_id") != CONTRACT_ID
        or decision.get("validation_lock_id") != lock["validation_lock_id"]
    ):
        raise StudyError("decision contract/lock binding mismatch")
    if decision.get("study_status") not in DECISION_STATUSES:
        raise StudyError("invalid decision status")
    if any(
        decision.get(field) != 0
        for field in (
            "provider_execution_count",
            "network_request_count",
            "legacy_execution_count",
            "v2_provider_execution_count",
            "parallel_execution_count",
            "runtime_source_modifications",
        )
    ):
        raise StudyError("execution accounting mismatch")

    manifest = _load_json(output_root / "manifest.json")
    all_members = _inventory(output_root)
    if tuple(item["path"] for item in all_members) != _expected_artifact_paths():
        raise StudyError("bundle contains unexpected or missing artifact paths")
    members = tuple(item for item in all_members if item["path"] != "manifest.json")
    if tuple(manifest.get("members", ())) != members or manifest.get("member_count") != 20:
        raise StudyError("bundle manifest members mismatch")
    if manifest.get("output_inventory_sha256") != _inventory_sha256(members):
        raise StudyError("bundle inventory mismatch")
    if manifest.get("manifest_id") != deterministic_hash(
        MANIFEST_NAMESPACE, _without_id(manifest, "manifest_id")
    ):
        raise StudyError("manifest identity mismatch")
    if (
        manifest.get("study_contract_id") != CONTRACT_ID
        or manifest.get("decision_id") != decision["decision_id"]
    ):
        raise StudyError("manifest binding mismatch")

    source_members = _validate_manifest(
        VALIDATION_ROOT,
        expected_manifest=PHASE9C2_MANIFEST_ID,
        expected_inventory=PHASE9C2_OUTPUT_INVENTORY,
    )
    validation_scope = _load_validation_scope()
    validation_metrics: dict[str, Mapping[str, Any]] = {}
    for scope in validation_scope:
        membership = _load_json(
            output_root / "datasets" / scope.dataset_id / "checkpoint_membership.json"
        )
        metrics = _load_json(output_root / "datasets" / scope.dataset_id / "provider_metrics.json")
        _validate_membership(
            membership,
            metrics=metrics,
            scope=scope,
            expected_method_ids=VALIDATION_METHODS,
            phase="validation",
        )
        validation_metrics[scope.dataset_id] = metrics
    aggregate = {
        provider_id: _aggregate_metrics(validation_metrics, provider_id, phase="validation")
        for provider_id in PRIMARY_PROVIDERS
    }
    ranking = _rank_validation(aggregate)
    winner = next((row["provider_id"] for row in ranking if row["gate_passed"]), None)
    expected_validation = {
        "aggregate": aggregate,
        "ranking": ranking,
        "winner_provider_id": winner,
    }
    if decision.get("validation") != expected_validation:
        raise StudyError("decision validation evidence mismatch")
    expected_lock = _validation_lock(
        contract_id=CONTRACT_ID,
        dataset_metrics=validation_metrics,
        ranking=ranking,
        winner=winner,
    )
    if lock != expected_lock:
        raise StudyError("validation lock semantic mismatch")

    holdout_metrics: dict[str, Mapping[str, Any]] = {}
    holdout_status = "UNOPENED_NO_VALIDATION_FINALIST"
    temporal_status = "UNOPENED_NO_HOLDOUT_PASS"
    holdout_count = 0
    temporal_count = 0
    scope_method_ids: dict[str, Sequence[str]] = {
        "validation": VALIDATION_METHODS,
        "holdout": (),
        "temporal": (),
    }
    if winner is None:
        for dataset_id in HOLDOUT_DATASETS:
            _verify_unopened_dataset(output_root, dataset_id)
        temporal = _load_json(
            output_root / "temporal" / TEMPORAL_DATASET / "checkpoint_membership.json"
        )
        if temporal != {"status": "UNOPENED", "reason": "NO_VALIDATION_FINALIST", "checkpoint_memberships": []}:
            raise StudyError("temporal audit opened on no-finalist path")
        expected_status = "NO_INDEPENDENT_SPARSE_PROVIDER_FINALIST"
    else:
        holdout_methods = (winner, CONTROL_PROVIDERS[0])
        scope_method_ids["holdout"] = holdout_methods
        for dataset_id in HOLDOUT_DATASETS:
            scope = _load_scope_dataset(VALIDATION_ROOT, dataset_id)
            membership = _load_json(
                output_root / "datasets" / dataset_id / "checkpoint_membership.json"
            )
            metrics = _load_json(
                output_root / "datasets" / dataset_id / "provider_metrics.json"
            )
            _validate_membership(
                membership,
                metrics=metrics,
                scope=scope,
                expected_method_ids=holdout_methods,
                phase="holdout",
            )
            holdout_metrics[dataset_id] = metrics
        holdout_count = HOLDOUT_CHECKPOINT_COUNT * len(holdout_methods) * 2
        holdout_aggregate = _aggregate_metrics(holdout_metrics, winner, phase="holdout")
        if not holdout_aggregate["gate_passed"]:
            holdout_status = "REJECTED"
            temporal = _load_json(
                output_root / "temporal" / TEMPORAL_DATASET / "checkpoint_membership.json"
            )
            if temporal != {"status": "UNOPENED", "reason": "NO_HOLDOUT_PASS", "checkpoint_memberships": []}:
                raise StudyError("temporal audit opened after holdout rejection")
            expected_status = "INDEPENDENT_SPARSE_PROVIDER_HOLDOUT_REJECTED"
        else:
            holdout_status = "PASSED"
            scope_method_ids["temporal"] = (winner,)
            _temporal_membership, temporal_wrapper = _verify_temporal_scope(
                output_root, winner=winner
            )
            temporal_metric = temporal_wrapper["providers"][winner]
            temporal_passed, temporal_reasons = _gate(temporal_metric, phase="temporal")
            if temporal_metric.get("gate_passed") != temporal_passed or temporal_metric.get(
                "rejection_reasons"
            ) != temporal_reasons:
                raise StudyError("temporal gate evidence mismatch")
            temporal_status = "PASSED" if temporal_passed else "REJECTED"
            temporal_count = 5 * 2
            expected_status = (
                "INDEPENDENT_SPARSE_PROVIDER_PROMOTION_CANDIDATE"
                if temporal_passed
                else "INDEPENDENT_SPARSE_PROVIDER_TEMPORAL_REJECTED"
            )

    method_derivation_counts = {
        "validation": VALIDATION_CHECKPOINT_COUNT * len(VALIDATION_METHODS) * 2,
        "holdout": holdout_count,
        "temporal": temporal_count,
    }
    expected_decision = _decision_payload(
        status=expected_status,
        contract_id=CONTRACT_ID,
        validation=expected_validation,
        lock=lock,
        holdout_status=holdout_status,
        temporal_status=temporal_status,
        method_derivation_counts=method_derivation_counts,
        scope_method_ids=scope_method_ids,
    )
    if decision != expected_decision:
        raise StudyError("decision branch evidence mismatch")
    expected_audit = _source_audit(
        source_members,
        holdout_accessed=winner is not None,
        temporal_accessed=temporal_count > 0,
        method_derivation_counts=method_derivation_counts,
        scope_method_ids=scope_method_ids,
    )
    if source_audit != expected_audit:
        raise StudyError("source audit branch evidence mismatch")
    expected_cross_scope = _csv_bytes(
        _cross_scope_summary_rows(validation_metrics, holdout_metrics)
    )
    if (output_root / "cross_scope_summary.csv").read_bytes() != expected_cross_scope:
        raise StudyError("cross-scope summary CSV mismatch")
    expected_temporal_summary = _csv_bytes(
        _temporal_summary_rows(
            _load_json(
                output_root
                / "temporal"
                / TEMPORAL_DATASET
                / "checkpoint_membership.json"
            )
        )
    )
    if (output_root / "temporal_summary.csv").read_bytes() != expected_temporal_summary:
        raise StudyError("temporal summary CSV mismatch")
    return {
        "study_status": decision["study_status"],
        "decision_id": decision["decision_id"],
        "manifest_id": manifest["manifest_id"],
        "output_inventory_sha256": manifest["output_inventory_sha256"],
        "network_request_count": 0,
        "legacy_execution_count": 0,
        "v2_provider_execution_count": 0,
    }


def run_study(*, output_root: str | Path = OUTPUT_ROOT) -> dict[str, Any]:
    root = Path(output_root)
    if root.exists():
        raise FileExistsError(f"refusing existing output root: {root}")
    if os.environ.get("TRENDLINE_V2_ALLOW_PHASE11R1_STUDY") != "1":
        raise StudyError("real study requires TRENDLINE_V2_ALLOW_PHASE11R1_STUDY=1")
    return _run_analysis(root)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-study", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    if args.execute_study == args.verify:
        parser.error("choose exactly one of --execute-study or --verify")
    try:
        result = run_study(output_root=args.output_root) if args.execute_study else _verify_bundle(args.output_root)
    except (FileExistsError, OSError, StudyError, ContractValidationError) as exc:
        print(str(exc))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
