"""Immutable contracts for the SR-V1.9 baseline/null adequacy study."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
import re
from types import MappingProxyType
from typing import Any

from libs.models.sr.domain.contracts import (
    ContractValidationError,
    ZoneSide,
    ZoneStatus,
)
from libs.models.sr.domain.identity import deterministic_hash, require_utc, utc_isoformat
from libs.models.sr.scripts.atr_calibration.metrics import FirstTouchOutcome
from libs.models.sr.scripts.cohort_readiness.contracts import CohortFold


SCHEMA_VERSION = "1.0"
CONFIG_VERSION = "1"
TRIAL_NAME = "sr-v1.9-taousdt-1d-baseline-adequacy"
APPROVED_ASSET = "TAOUSDT"
APPROVED_VENUE = "binance_usdm"
APPROVED_TIMEFRAME = "1d"
APPROVED_SOURCE_ROWS = 629
APPROVED_SOURCE_START = datetime(2024, 4, 11, tzinfo=timezone.utc)
APPROVED_SOURCE_END = datetime(2025, 12, 31, tzinfo=timezone.utc)
APPROVED_GRID_POLICY = "exact_utc_daily_grid_from_taousdt_development_capsule"

V17_CONFIG_HASH = "370d2b66e8e3031b0df8547e8b52c61288e14c5d1b858612ce9fae712e1690a7"
V17_SOURCE_BUNDLE_ID = "6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9"
V17_SOURCE_IMPLEMENTATION_COMMIT = "be6459a8e06ec95b634b2cfb2b91a08cd31d9ba2"
V17_EVALUATION_BUNDLE_ID = "824e9265a63073ba792762a891adf52deec9677d791c40641dc0107c1f2b840d"
V17_EVALUATION_ID = "49a895360774ec0c46349eae2d1ec6f56e7262e5f1411ab992f9886d9040fa8d"
V17_EVALUATION_IMPLEMENTATION_COMMIT = "4cb069af6142dbd7dadf7a5ebef49d2da0ba26a7"

V18_CONFIG_HASH = "86137d2c5b5e12802a5731298ab548822f23c4937d635bae5f21b77a8e7c0da7"
V18_STUDY_BUNDLE_ID = "b0ea33decc9c8c40dab98bdbb90635652dc199031fc50b27d3a71a6711378941"
V18_STUDY_ID = "2a324d3a203642bf9030aede611a8d874fcb051c5b394fcb4758582d6cfbc954"
V18_IMPLEMENTATION_COMMIT = "fa819418aa35b7f325c7a6bf2a51a387aa97f60f"
V18_BASELINE_CANDIDATE_ID = "37769b33cc663e4baf5488001252a996b9cb2ec67d0182400f12cb928015709c"

FROZEN_SR_CONFIG_HASH = "cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299"
FROZEN_INPUT_HASH = "5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d"
FROZEN_ATR_METHOD = "wilder_rma"
FROZEN_ATR_PERIOD = 14
FROZEN_ATR_SEED = "sma"
FROZEN_COMMON_START_PERIOD = 28
FROZEN_OUTCOME_OFFSET = 1
FROZEN_OUTCOME_HORIZON = 10
WINDOW_POLICY = "half_open_utc_daily"
ENTRY_VISIBLE_STATES = (ZoneStatus.ACTIVE, ZoneStatus.BREACH_PENDING)
CONTROL_SIDE_ORDER = (ZoneSide.SUPPORT, ZoneSide.RESISTANCE)
CONTROLS_PER_ANCHOR = 2
INTERSECTION_POLICY = "inclusive_ohlc_against_visible_zone_band"
PREVIOUS_SNAPSHOT_POLICY = "previous_aligned_model_snapshot_only"
CONTROL_ID_SCHEMA_VERSION = "1.0"

APPROVED_ADEQUACY_THRESHOLDS = MappingProxyType(
    {
        "minimum_completed_real_outcomes": 24,
        "minimum_comparable_folds": 4,
        "minimum_real_outcomes_per_comparable_fold": 4,
        "minimum_controls_per_side_per_comparable_fold": 4,
        "minimum_pooled_median_excess_quality_atr": 0.10,
        "minimum_positive_comparable_fold_fraction": 0.60,
        "minimum_worst_comparable_fold_excess_atr": -0.10,
    }
)

REJECTION_REASON_PRECEDENCE = (
    "NO_PREVIOUS_MODEL_SNAPSHOT",
    "OUTSIDE_FOLD_OR_WARMUP",
    "ATR_UNAVAILABLE_OR_INVALID",
    "ENTRY_VISIBLE_ZONE_INTERSECTION",
    "INCOMPLETE_SAME_FOLD_HORIZON",
)

DISPOSITION_VALUES = (
    "BASELINE_BEATS_NAIVE_NULL",
    "BASELINE_NOT_BETTER_THAN_NAIVE_NULL",
    "INSUFFICIENT_EVIDENCE",
)

_HASH_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")


def _string(value: Any, *, path: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContractValidationError(f"{path} must be a non-empty string")
    return value


def _hash(value: Any, *, path: str) -> str:
    value = _string(value, path=path)
    if _HASH_RE.fullmatch(value) is None:
        raise ContractValidationError(f"{path} must be a lowercase SHA-256 hex string")
    return value


def _commit(value: Any, *, path: str) -> str:
    value = _string(value, path=path)
    if _COMMIT_RE.fullmatch(value) is None:
        raise ContractValidationError(f"{path} must be a git SHA")
    return value


def _integer(value: Any, *, path: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or type(value) is not int or value < minimum:
        raise ContractValidationError(f"{path} must be an integer >= {minimum}")
    return value


def _number(value: Any, *, path: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{path} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{path} must be finite") from exc
    if not math.isfinite(result):
        raise ContractValidationError(f"{path} must be finite")
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{path} must be >= {minimum}")
    return 0.0 if result == 0.0 else result


def _timestamp(value: Any, *, path: str) -> datetime:
    try:
        return require_utc(value, field_name=path)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"{path} must be UTC-aware") from exc


def _enum(value: Any, enum_type: type[Enum], *, path: str) -> Enum:
    if type(value) is not enum_type:
        raise ContractValidationError(f"{path} must be exactly {enum_type.__name__}")
    return value


def _tuple(value: Any, *, path: str) -> tuple[Any, ...]:
    if type(value) is not tuple:
        raise ContractValidationError(f"{path} must be exactly a tuple")
    return value


class ControlEligibilityReason(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    NO_PREVIOUS_MODEL_SNAPSHOT = "NO_PREVIOUS_MODEL_SNAPSHOT"
    OUTSIDE_FOLD_OR_WARMUP = "OUTSIDE_FOLD_OR_WARMUP"
    ATR_UNAVAILABLE_OR_INVALID = "ATR_UNAVAILABLE_OR_INVALID"
    ENTRY_VISIBLE_ZONE_INTERSECTION = "ENTRY_VISIBLE_ZONE_INTERSECTION"
    INCOMPLETE_SAME_FOLD_HORIZON = "INCOMPLETE_SAME_FOLD_HORIZON"


class BaselineAdequacyDisposition(str, Enum):
    BASELINE_BEATS_NAIVE_NULL = "BASELINE_BEATS_NAIVE_NULL"
    BASELINE_NOT_BETTER_THAN_NAIVE_NULL = "BASELINE_NOT_BETTER_THAN_NAIVE_NULL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class AdequacyThresholds:
    minimum_completed_real_outcomes: int
    minimum_comparable_folds: int
    minimum_real_outcomes_per_comparable_fold: int
    minimum_controls_per_side_per_comparable_fold: int
    minimum_pooled_median_excess_quality_atr: float
    minimum_positive_comparable_fold_fraction: float
    minimum_worst_comparable_fold_excess_atr: float

    def __post_init__(self) -> None:
        for name in (
            "minimum_completed_real_outcomes",
            "minimum_comparable_folds",
            "minimum_real_outcomes_per_comparable_fold",
            "minimum_controls_per_side_per_comparable_fold",
        ):
            object.__setattr__(self, name, _integer(getattr(self, name), path=f"gates.{name}", minimum=1))
        for name in (
            "minimum_pooled_median_excess_quality_atr",
            "minimum_positive_comparable_fold_fraction",
            "minimum_worst_comparable_fold_excess_atr",
        ):
            object.__setattr__(self, name, _number(getattr(self, name), path=f"gates.{name}"))
        if not 0.0 <= self.minimum_positive_comparable_fold_fraction <= 1.0:
            raise ContractValidationError("gates.minimum_positive_comparable_fold_fraction must be in [0, 1]")
        if self.to_payload() != dict(APPROVED_ADEQUACY_THRESHOLDS):
            raise ContractValidationError("V1.9 adequacy thresholds are not the approved immutable payload")

    def to_payload(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class BaselineAdequacyConfig:
    version: str
    trial_name: str
    venue: str
    asset: str
    timeframe: str
    v17_config_path: str
    v17_config_hash: str
    source_bundle_path: str
    source_bundle_id: str
    source_implementation_commit: str
    v17_evaluation_bundle_path: str
    v17_evaluation_bundle_id: str
    v17_evaluation_id: str
    v17_evaluation_implementation_commit: str
    v18_config_path: str
    v18_study_bundle_path: str
    v18_study_bundle_id: str
    v18_study_id: str
    v18_config_hash: str
    v18_implementation_commit: str
    sr_config_path: str
    input_config_path: str
    frozen_sr_config_hash: str
    frozen_input_hash: str
    source_row_count: int
    source_start: datetime
    source_end: datetime
    grid_policy: str
    pivot_span_bars: int
    zone_half_width_atr: float
    merge_distance_atr: float
    touch_tolerance_atr: float
    break_buffer_atr: float
    break_confirm_closes: int
    max_age_bars: int
    max_active_zones: int
    atr_method: str
    atr_period: int
    atr_seed: str
    common_start_period: int
    outcome_start_offset_bars: int
    outcome_horizon_bars: int
    window_policy: str
    folds: tuple[CohortFold, ...]
    entry_visible_states: tuple[ZoneStatus, ...]
    intersection_policy: str
    previous_snapshot_policy: str
    control_side_order: tuple[ZoneSide, ...]
    controls_per_anchor: int
    control_id_schema_version: str
    rejection_reason_precedence: tuple[ControlEligibilityReason, ...]
    gates: AdequacyThresholds
    dispositions: tuple[BaselineAdequacyDisposition, ...]
    output_root: str
    config_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if _string(self.version, path="version") != CONFIG_VERSION:
            raise ContractValidationError("unsupported V1.9 config version")
        if _string(self.trial_name, path="trial.trial_name") != TRIAL_NAME:
            raise ContractValidationError("trial name does not match V1.9")
        if (_string(self.venue, path="trial.venue"), _string(self.asset, path="trial.asset"), _string(self.timeframe, path="trial.timeframe")) != (APPROVED_VENUE, APPROVED_ASSET, APPROVED_TIMEFRAME):
            raise ContractValidationError("trial scope is outside approved TAOUSDT/1d study")

        for name in (
            "v17_config_hash", "source_bundle_id", "v17_evaluation_bundle_id", "v17_evaluation_id",
            "v18_study_bundle_id", "v18_study_id", "v18_config_hash", "frozen_sr_config_hash", "frozen_input_hash",
        ):
            object.__setattr__(self, name, _hash(getattr(self, name), path=f"inputs.{name}"))
        if self.v17_config_hash != V17_CONFIG_HASH or self.source_bundle_id != V17_SOURCE_BUNDLE_ID or self.v17_evaluation_bundle_id != V17_EVALUATION_BUNDLE_ID or self.v17_evaluation_id != V17_EVALUATION_ID:
            raise ContractValidationError("V1.7 identities are not approved")
        if self.v18_study_bundle_id != V18_STUDY_BUNDLE_ID or self.v18_study_id != V18_STUDY_ID or self.v18_config_hash != V18_CONFIG_HASH:
            raise ContractValidationError("V1.8 identities are not approved")
        if self.frozen_sr_config_hash != FROZEN_SR_CONFIG_HASH or self.frozen_input_hash != FROZEN_INPUT_HASH:
            raise ContractValidationError("frozen production config identities are not approved")
        for name in (
            "source_implementation_commit", "v17_evaluation_implementation_commit",
            "v18_implementation_commit",
        ):
            object.__setattr__(self, name, _commit(getattr(self, name), path=f"inputs.{name}"))
        if self.source_implementation_commit != V17_SOURCE_IMPLEMENTATION_COMMIT or self.v17_evaluation_implementation_commit != V17_EVALUATION_IMPLEMENTATION_COMMIT or self.v18_implementation_commit != V18_IMPLEMENTATION_COMMIT:
            raise ContractValidationError("upstream implementation identities are not approved")
        for name in (
            "v17_config_path", "source_bundle_path", "v17_evaluation_bundle_path", "v18_config_path", "v18_study_bundle_path",
            "sr_config_path", "input_config_path", "output_root",
        ):
            path = _string(getattr(self, name), path=f"inputs.{name}" if name not in {"output_root"} else "output.root")
            normalized = path.replace("\\", "/")
            if path.startswith("/") or ".." in normalized.split("/"):
                raise ContractValidationError(f"{name} must be a safe relative path")
            object.__setattr__(self, name, path)

        object.__setattr__(self, "source_row_count", _integer(self.source_row_count, path="source.row_count", minimum=1))
        if self.source_row_count != APPROVED_SOURCE_ROWS:
            raise ContractValidationError("source.row_count must be 629")
        source_start = _timestamp(self.source_start, path="source.start")
        source_end = _timestamp(self.source_end, path="source.end")
        if source_start != APPROVED_SOURCE_START or source_end != APPROVED_SOURCE_END:
            raise ContractValidationError("source bounds do not match frozen TAOUSDT grid")
        object.__setattr__(self, "source_start", source_start)
        object.__setattr__(self, "source_end", source_end)
        if _string(self.grid_policy, path="source.grid_policy") != APPROVED_GRID_POLICY:
            raise ContractValidationError("unsupported source grid policy")

        integer_fields = (
            ("pivot_span_bars", 1), ("break_confirm_closes", 1), ("max_age_bars", 1),
            ("max_active_zones", 1), ("atr_period", 1), ("common_start_period", 1),
            ("outcome_start_offset_bars", 1), ("outcome_horizon_bars", 1), ("controls_per_anchor", 1),
        )
        for name, minimum in integer_fields:
            object.__setattr__(self, name, _integer(getattr(self, name), path=f"baseline.{name}", minimum=minimum))
        if (self.pivot_span_bars, self.break_confirm_closes, self.max_age_bars, self.max_active_zones, self.atr_period, self.common_start_period, self.outcome_start_offset_bars, self.outcome_horizon_bars) != (5, 2, 50, 8, 14, 28, 1, 10):
            raise ContractValidationError("baseline integer/ATR/outcome values are not frozen")
        for name in ("zone_half_width_atr", "merge_distance_atr", "touch_tolerance_atr", "break_buffer_atr"):
            object.__setattr__(self, name, _number(getattr(self, name), path=f"baseline.{name}", minimum=0.0))
        if (self.zone_half_width_atr, self.merge_distance_atr, self.touch_tolerance_atr, self.break_buffer_atr) != (0.25, 0.50, 0.25, 0.25):
            raise ContractValidationError("baseline geometry/lifecycle values are not frozen")
        if (_string(self.atr_method, path="baseline.atr_method"), _string(self.atr_seed, path="baseline.atr_seed")) != (FROZEN_ATR_METHOD, FROZEN_ATR_SEED):
            raise ContractValidationError("ATR method/seed are not frozen")
        if _string(self.window_policy, path="protocol.outcome.window_policy") != WINDOW_POLICY:
            raise ContractValidationError("unsupported outcome window policy")

        if type(self.folds) is not tuple or len(self.folds) != 6 or tuple(fold.name for fold in self.folds) != ("2024_q3", "2024_q4", "2025_q1", "2025_q2", "2025_q3", "2025_q4"):
            raise ContractValidationError("exactly six canonical folds are required")
        expected_bounds = (
            (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2024, 10, 1, tzinfo=timezone.utc)),
            (datetime(2024, 10, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
            (datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 4, 1, tzinfo=timezone.utc)),
            (datetime(2025, 4, 1, tzinfo=timezone.utc), datetime(2025, 7, 1, tzinfo=timezone.utc)),
            (datetime(2025, 7, 1, tzinfo=timezone.utc), datetime(2025, 10, 1, tzinfo=timezone.utc)),
            (datetime(2025, 10, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        if tuple((fold.start, fold.end) for fold in self.folds) != expected_bounds:
            raise ContractValidationError("fold boundaries do not match frozen protocol")

        if type(self.entry_visible_states) is not tuple or self.entry_visible_states != ENTRY_VISIBLE_STATES:
            raise ContractValidationError("entry-visible states must be ACTIVE/BREACH_PENDING")
        if _string(self.intersection_policy, path="protocol.visibility.intersection_policy") != INTERSECTION_POLICY or _string(self.previous_snapshot_policy, path="protocol.visibility.previous_snapshot_policy") != PREVIOUS_SNAPSHOT_POLICY:
            raise ContractValidationError("visibility/intersection semantics are not frozen")
        if type(self.control_side_order) is not tuple or self.control_side_order != CONTROL_SIDE_ORDER or self.controls_per_anchor != CONTROLS_PER_ANCHOR:
            raise ContractValidationError("control side/order contract is not frozen")
        if _string(self.control_id_schema_version, path="controls.control_id_schema_version") != CONTROL_ID_SCHEMA_VERSION:
            raise ContractValidationError("unsupported control ID schema")
        if type(self.rejection_reason_precedence) is not tuple or tuple(item.value for item in self.rejection_reason_precedence) != REJECTION_REASON_PRECEDENCE:
            raise ContractValidationError("control rejection precedence is not frozen")
        if type(self.gates) is not AdequacyThresholds:
            raise ContractValidationError("gates must be AdequacyThresholds")
        if type(self.dispositions) is not tuple or tuple(item.value for item in self.dispositions) != DISPOSITION_VALUES:
            raise ContractValidationError("dispositions are not the exact approved set")
        object.__setattr__(self, "config_hash", deterministic_hash(self.to_payload()))

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "trial": {"trial_name": self.trial_name, "venue": self.venue, "asset": self.asset, "timeframe": self.timeframe},
            "inputs": {
                "v17_config_path": self.v17_config_path,
                "v17_config_hash": self.v17_config_hash,
                "source_bundle_path": self.source_bundle_path,
                "source_bundle_id": self.source_bundle_id,
                "source_implementation_commit": self.source_implementation_commit,
                "v17_evaluation_bundle_path": self.v17_evaluation_bundle_path,
                "v17_evaluation_bundle_id": self.v17_evaluation_bundle_id,
                "v17_evaluation_id": self.v17_evaluation_id,
                "v17_evaluation_implementation_commit": self.v17_evaluation_implementation_commit,
                "v18_config_path": self.v18_config_path,
                "v18_study_bundle_path": self.v18_study_bundle_path,
                "v18_study_bundle_id": self.v18_study_bundle_id,
                "v18_study_id": self.v18_study_id,
                "v18_config_hash": self.v18_config_hash,
                "v18_implementation_commit": self.v18_implementation_commit,
                "sr_config_path": self.sr_config_path,
                "input_config_path": self.input_config_path,
                "frozen_sr_config_hash": self.frozen_sr_config_hash,
                "frozen_input_hash": self.frozen_input_hash,
            },
            "source": {"row_count": self.source_row_count, "start": utc_isoformat(self.source_start), "end": utc_isoformat(self.source_end), "grid_policy": self.grid_policy},
            "baseline": {
                "pivot_span_bars": self.pivot_span_bars,
                "zone_half_width_atr": self.zone_half_width_atr,
                "merge_distance_atr": self.merge_distance_atr,
                "touch_tolerance_atr": self.touch_tolerance_atr,
                "break_buffer_atr": self.break_buffer_atr,
                "break_confirm_closes": self.break_confirm_closes,
                "max_age_bars": self.max_age_bars,
                "max_active_zones": self.max_active_zones,
                "atr_method": self.atr_method,
                "atr_period": self.atr_period,
                "atr_seed": self.atr_seed,
                "common_start_period": self.common_start_period,
            },
            "protocol": {
                "outcome": {"start_offset_bars": self.outcome_start_offset_bars, "horizon_bars": self.outcome_horizon_bars, "window_policy": self.window_policy},
                "folds": [fold.to_payload() for fold in self.folds],
                "visibility": {"entry_visible_states": [state.value for state in self.entry_visible_states], "intersection_policy": self.intersection_policy, "previous_snapshot_policy": self.previous_snapshot_policy},
            },
            "controls": {"side_order": [side.value for side in self.control_side_order], "controls_per_anchor": self.controls_per_anchor, "control_id_schema_version": self.control_id_schema_version, "rejection_reason_precedence": list(REJECTION_REASON_PRECEDENCE)},
            "gates": self.gates.to_payload(),
            "dispositions": [item.value for item in self.dispositions],
            "output": {"root": self.output_root},
        }


@dataclass(frozen=True)
class ControlAnchor:
    asset: str
    timeframe: str
    fold: str | None
    bar_id: str
    anchor_at: datetime
    model_index: int
    anchor_open: float
    anchor_high: float
    anchor_low: float
    anchor_close: float
    reference_atr_14: float | None
    eligible: bool
    reason: ControlEligibilityReason
    config_hash: str
    anchor_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", _string(self.asset, path="control.asset"))
        object.__setattr__(self, "timeframe", _string(self.timeframe, path="control.timeframe"))
        if self.fold is not None:
            object.__setattr__(self, "fold", _string(self.fold, path="control.fold"))
        object.__setattr__(self, "bar_id", _string(self.bar_id, path="control.bar_id"))
        object.__setattr__(self, "anchor_at", _timestamp(self.anchor_at, path="control.anchor_at"))
        object.__setattr__(self, "model_index", _integer(self.model_index, path="control.model_index"))
        for name in ("anchor_open", "anchor_high", "anchor_low", "anchor_close"):
            object.__setattr__(self, name, _number(getattr(self, name), path=f"control.{name}", minimum=0.0))
        if min(self.anchor_open, self.anchor_high, self.anchor_low, self.anchor_close) <= 0 or self.anchor_low > self.anchor_high or not self.anchor_low <= self.anchor_open <= self.anchor_high or not self.anchor_low <= self.anchor_close <= self.anchor_high:
            raise ContractValidationError("control anchor OHLC geometry is invalid")
        if self.reference_atr_14 is not None:
            atr = _number(self.reference_atr_14, path="control.reference_atr_14", minimum=0.0)
            if atr <= 0:
                raise ContractValidationError("control reference ATR must be positive")
            object.__setattr__(self, "reference_atr_14", atr)
        if type(self.eligible) is not bool:
            raise ContractValidationError("control.eligible must be boolean")
        object.__setattr__(self, "reason", _enum(self.reason, ControlEligibilityReason, path="control.reason"))
        object.__setattr__(self, "config_hash", _hash(self.config_hash, path="control.config_hash"))
        if self.eligible != (self.reason is ControlEligibilityReason.ELIGIBLE):
            raise ContractValidationError("control eligibility and reason do not reconcile")
        if self.eligible and self.fold is None:
            raise ContractValidationError("eligible control must belong to a fold")
        if self.eligible and self.reference_atr_14 is None:
            raise ContractValidationError("eligible control requires reference ATR")
        object.__setattr__(self, "anchor_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "fold": self.fold,
            "bar_id": self.bar_id,
            "anchor_at": utc_isoformat(self.anchor_at),
            "model_index": self.model_index,
            "anchor_open": self.anchor_open,
            "anchor_high": self.anchor_high,
            "anchor_low": self.anchor_low,
            "anchor_close": self.anchor_close,
            "reference_atr_14": self.reference_atr_14,
            "eligible": self.eligible,
            "reason": self.reason.value,
            "config_hash": self.config_hash,
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "anchor_id": self.anchor_id}


@dataclass(frozen=True)
class ControlOutcome:
    anchor_id: str
    asset: str
    timeframe: str
    fold: str
    bar_id: str
    anchor_at: datetime
    side: ZoneSide
    anchor_close: float
    reference_atr_14: float
    outcome_start_offset_bars: int
    outcome_horizon_bars: int
    tenth_outcome_bar_closed_at: datetime
    favorable_reference_atr: float
    adverse_reference_atr: float
    quality_reference_atr: float
    config_hash: str
    control_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "anchor_id", _hash(self.anchor_id, path="control_outcome.anchor_id"))
        object.__setattr__(self, "asset", _string(self.asset, path="control_outcome.asset"))
        object.__setattr__(self, "timeframe", _string(self.timeframe, path="control_outcome.timeframe"))
        object.__setattr__(self, "fold", _string(self.fold, path="control_outcome.fold"))
        object.__setattr__(self, "bar_id", _string(self.bar_id, path="control_outcome.bar_id"))
        object.__setattr__(self, "anchor_at", _timestamp(self.anchor_at, path="control_outcome.anchor_at"))
        object.__setattr__(self, "side", _enum(self.side, ZoneSide, path="control_outcome.side"))
        object.__setattr__(self, "anchor_close", _number(self.anchor_close, path="control_outcome.anchor_close", minimum=0.0))
        object.__setattr__(self, "reference_atr_14", _number(self.reference_atr_14, path="control_outcome.reference_atr_14", minimum=0.0))
        if self.anchor_close <= 0 or self.reference_atr_14 <= 0:
            raise ContractValidationError("control outcome anchor/reference values must be positive")
        object.__setattr__(self, "outcome_start_offset_bars", _integer(self.outcome_start_offset_bars, path="control_outcome.outcome_start_offset_bars", minimum=1))
        object.__setattr__(self, "outcome_horizon_bars", _integer(self.outcome_horizon_bars, path="control_outcome.outcome_horizon_bars", minimum=1))
        object.__setattr__(self, "tenth_outcome_bar_closed_at", _timestamp(self.tenth_outcome_bar_closed_at, path="control_outcome.tenth_outcome_bar_closed_at"))
        for name in ("favorable_reference_atr", "adverse_reference_atr", "quality_reference_atr"):
            object.__setattr__(self, name, _number(getattr(self, name), path=f"control_outcome.{name}"))
        if self.favorable_reference_atr < 0 or self.adverse_reference_atr < 0 or abs(self.quality_reference_atr - (self.favorable_reference_atr - self.adverse_reference_atr)) > 1e-12:
            raise ContractValidationError("control outcome quality formula mismatch")
        object.__setattr__(self, "config_hash", _hash(self.config_hash, path="control_outcome.config_hash"))
        object.__setattr__(self, "control_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "anchor_id": self.anchor_id,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "fold": self.fold,
            "bar_id": self.bar_id,
            "anchor_at": utc_isoformat(self.anchor_at),
            "side": self.side.value,
            "anchor_close": self.anchor_close,
            "reference_atr_14": self.reference_atr_14,
            "outcome_start_offset_bars": self.outcome_start_offset_bars,
            "outcome_horizon_bars": self.outcome_horizon_bars,
            "tenth_outcome_bar_closed_at": utc_isoformat(self.tenth_outcome_bar_closed_at),
            "favorable_reference_atr": self.favorable_reference_atr,
            "adverse_reference_atr": self.adverse_reference_atr,
            "quality_reference_atr": self.quality_reference_atr,
            "config_hash": self.config_hash,
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "control_id": self.control_id}


@dataclass(frozen=True)
class FoldControlAccounting:
    fold: str | None
    considered: int
    eligible: int
    rejected: tuple[tuple[ControlEligibilityReason, int], ...]

    def __post_init__(self) -> None:
        if self.fold is not None:
            object.__setattr__(self, "fold", _string(self.fold, path="control_accounting.fold"))
        object.__setattr__(self, "considered", _integer(self.considered, path="control_accounting.considered"))
        object.__setattr__(self, "eligible", _integer(self.eligible, path="control_accounting.eligible"))
        if type(self.rejected) is not tuple:
            raise ContractValidationError("control accounting rejected must be a tuple")
        seen: set[ControlEligibilityReason] = set()
        total_rejected = 0
        for reason, count in self.rejected:
            object.__setattr__(self, "rejected", self.rejected)
            _enum(reason, ControlEligibilityReason, path="control_accounting.reason")
            if reason is ControlEligibilityReason.ELIGIBLE or reason in seen:
                raise ContractValidationError("control accounting reasons are invalid")
            seen.add(reason)
            total_rejected += _integer(count, path="control_accounting.rejected_count")
        if self.considered != self.eligible + total_rejected:
            raise ContractValidationError("control accounting does not reconcile")

    def to_payload(self) -> dict[str, Any]:
        return {"fold": self.fold, "considered": self.considered, "eligible": self.eligible, "rejected": [[reason.value, count] for reason, count in self.rejected]}


@dataclass(frozen=True)
class ControlAccounting:
    total_considered: int
    total_eligible: int
    rejected: tuple[tuple[ControlEligibilityReason, int], ...]
    folds: tuple[FoldControlAccounting, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "total_considered", _integer(self.total_considered, path="control_accounting.total_considered"))
        object.__setattr__(self, "total_eligible", _integer(self.total_eligible, path="control_accounting.total_eligible"))
        if type(self.rejected) is not tuple or type(self.folds) is not tuple or any(type(item) is not FoldControlAccounting for item in self.folds):
            raise ContractValidationError("control accounting types are invalid")
        total_rejected = 0
        for reason, count in self.rejected:
            _enum(reason, ControlEligibilityReason, path="control_accounting.reason")
            if reason is ControlEligibilityReason.ELIGIBLE:
                raise ContractValidationError("eligible is not a rejection reason")
            total_rejected += _integer(count, path="control_accounting.rejected_count")
        if self.total_considered != self.total_eligible + total_rejected or sum(item.considered for item in self.folds) != self.total_considered or sum(item.eligible for item in self.folds) != self.total_eligible:
            raise ContractValidationError("total control accounting does not reconcile")

    def to_payload(self) -> dict[str, Any]:
        return {"total_considered": self.total_considered, "total_eligible": self.total_eligible, "rejected": [[reason.value, count] for reason, count in self.rejected], "folds": [item.to_payload() for item in self.folds]}


@dataclass(frozen=True)
class ControlBuildResult:
    anchors: tuple[ControlAnchor, ...]
    outcomes: tuple[ControlOutcome, ...]
    accounting: ControlAccounting

    def __post_init__(self) -> None:
        if type(self.anchors) is not tuple or type(self.outcomes) is not tuple or type(self.accounting) is not ControlAccounting:
            raise ContractValidationError("control build result types are invalid")
        if any(type(item) is not ControlAnchor for item in self.anchors) or any(type(item) is not ControlOutcome for item in self.outcomes):
            raise ContractValidationError("control build result members are invalid")
        anchor_ids = [item.anchor_id for item in self.anchors]
        if len(set(anchor_ids)) != len(anchor_ids) or anchor_ids != sorted(anchor_ids, key=lambda value: next(item.model_index for item in self.anchors if item.anchor_id == value)):
            raise ContractValidationError("control anchors must be unique and canonical")
        outcome_ids = [item.control_id for item in self.outcomes]
        if len(set(outcome_ids)) != len(outcome_ids):
            raise ContractValidationError("control outcome IDs must be unique")
        eligible = [item for item in self.anchors if item.eligible]
        if len(self.outcomes) != len(eligible) * CONTROLS_PER_ANCHOR:
            raise ContractValidationError("control outcome count does not reconcile")
        expected: list[tuple[str, ZoneSide]] = []
        for anchor in eligible:
            expected.extend((anchor.anchor_id, side) for side in CONTROL_SIDE_ORDER)
        if tuple((item.anchor_id, item.side) for item in self.outcomes) != tuple(expected):
            raise ContractValidationError("control outcomes must be SUPPORT then RESISTANCE per anchor")
        if any(item.config_hash != eligible[0].config_hash for item in self.outcomes) if eligible else False:
            raise ContractValidationError("control outcome config identity mismatch")

    def to_payload(self) -> dict[str, Any]:
        return {"anchors": [item.to_payload() for item in self.anchors], "outcomes": [item.to_payload() for item in self.outcomes], "accounting": self.accounting.to_payload()}


@dataclass(frozen=True)
class RealOutcomeRecord:
    fold: str
    outcome: FirstTouchOutcome
    record_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "fold", _string(self.fold, path="real_outcome.fold"))
        if type(self.outcome) is not FirstTouchOutcome:
            raise ContractValidationError("real_outcome.outcome must be FirstTouchOutcome")
        object.__setattr__(self, "record_id", deterministic_hash({"schema_version": SCHEMA_VERSION, "fold": self.fold, "outcome": self.outcome.to_payload()}))

    def to_payload(self) -> dict[str, Any]:
        return {"fold": self.fold, "record_id": self.record_id, "outcome": self.outcome.to_payload()}


@dataclass(frozen=True)
class FoldSideNull:
    fold: str
    side: ZoneSide
    control_count: int
    median_quality: float | None
    control_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "fold", _string(self.fold, path="fold_side_null.fold"))
        object.__setattr__(self, "side", _enum(self.side, ZoneSide, path="fold_side_null.side"))
        object.__setattr__(self, "control_count", _integer(self.control_count, path="fold_side_null.control_count"))
        if self.median_quality is not None:
            object.__setattr__(self, "median_quality", _number(self.median_quality, path="fold_side_null.median_quality"))
        if type(self.control_ids) is not tuple or any(type(item) is not str for item in self.control_ids) or len(self.control_ids) != self.control_count or len(set(self.control_ids)) != len(self.control_ids):
            raise ContractValidationError("fold-side null control IDs do not reconcile")
        if self.control_count == 0 and self.median_quality is not None:
            raise ContractValidationError("empty null side cannot have a median")
        if self.control_count > 0 and self.median_quality is None:
            raise ContractValidationError("non-empty null side requires a median")

    def to_payload(self) -> dict[str, Any]:
        return {"fold": self.fold, "side": self.side.value, "control_count": self.control_count, "median_quality": self.median_quality, "control_ids": list(self.control_ids)}


@dataclass(frozen=True)
class RealOutcomeComparison:
    real_outcome_id: str
    fold: str
    side: ZoneSide
    real_quality: float
    null_median: float
    excess_quality: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "real_outcome_id", _hash(self.real_outcome_id, path="comparison.real_outcome_id"))
        object.__setattr__(self, "fold", _string(self.fold, path="comparison.fold"))
        object.__setattr__(self, "side", _enum(self.side, ZoneSide, path="comparison.side"))
        for name in ("real_quality", "null_median", "excess_quality"):
            object.__setattr__(self, name, _number(getattr(self, name), path=f"comparison.{name}"))
        if abs(self.excess_quality - (self.real_quality - self.null_median)) > 1e-12:
            raise ContractValidationError("comparison excess quality formula mismatch")

    def to_payload(self) -> dict[str, Any]:
        return {"real_outcome_id": self.real_outcome_id, "fold": self.fold, "side": self.side.value, "real_quality": self.real_quality, "null_median": self.null_median, "excess_quality": self.excess_quality}


@dataclass(frozen=True)
class FoldAdequacyMetrics:
    fold: str
    completed_real_count: int
    support_completed_count: int
    resistance_completed_count: int
    support_control_count: int
    resistance_control_count: int
    support_null_median: float | None
    resistance_null_median: float | None
    comparable: bool
    fold_median_excess: float | None
    support_median_excess: float | None
    resistance_median_excess: float | None
    comparisons: tuple[RealOutcomeComparison, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "fold", _string(self.fold, path="fold_metrics.fold"))
        for name in ("completed_real_count", "support_completed_count", "resistance_completed_count", "support_control_count", "resistance_control_count"):
            object.__setattr__(self, name, _integer(getattr(self, name), path=f"fold_metrics.{name}"))
        if self.support_completed_count + self.resistance_completed_count != self.completed_real_count:
            raise ContractValidationError("fold real side counts do not reconcile")
        for name in ("support_null_median", "resistance_null_median", "fold_median_excess", "support_median_excess", "resistance_median_excess"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _number(value, path=f"fold_metrics.{name}"))
        if type(self.comparable) is not bool or type(self.comparisons) is not tuple or any(type(item) is not RealOutcomeComparison for item in self.comparisons):
            raise ContractValidationError("fold adequacy metric types are invalid")
        if self.comparable:
            if self.completed_real_count < 4 or self.support_control_count < 4 or self.resistance_control_count < 4:
                raise ContractValidationError("comparable fold violates minimum counts")
            if self.support_completed_count and self.support_null_median is None or self.resistance_completed_count and self.resistance_null_median is None:
                raise ContractValidationError("comparable fold lacks required null median")
            if len(self.comparisons) != self.completed_real_count or self.fold_median_excess is None:
                raise ContractValidationError("comparable fold comparisons do not reconcile")
        elif self.comparisons or self.fold_median_excess is not None:
            raise ContractValidationError("non-comparable fold cannot carry comparisons")

    def to_payload(self) -> dict[str, Any]:
        return {"fold": self.fold, "completed_real_count": self.completed_real_count, "support_completed_count": self.support_completed_count, "resistance_completed_count": self.resistance_completed_count, "support_control_count": self.support_control_count, "resistance_control_count": self.resistance_control_count, "support_null_median": self.support_null_median, "resistance_null_median": self.resistance_null_median, "comparable": self.comparable, "fold_median_excess": self.fold_median_excess, "support_median_excess": self.support_median_excess, "resistance_median_excess": self.resistance_median_excess, "comparisons": [item.to_payload() for item in self.comparisons]}


@dataclass(frozen=True)
class AdequacyAggregateMetrics:
    total_real_outcomes: int
    total_completed_real_outcomes: int
    total_right_censored_real_outcomes: int
    completed_real_count: int
    comparable_fold_count: int
    pooled_median_excess_quality: float | None
    positive_comparable_fold_fraction: float | None
    worst_comparable_fold_excess: float | None
    pooled_real_baseline_median_quality: float | None
    pooled_control_support_median_quality: float | None
    pooled_control_resistance_median_quality: float | None

    def __post_init__(self) -> None:
        for name in ("total_real_outcomes", "total_completed_real_outcomes", "total_right_censored_real_outcomes", "completed_real_count", "comparable_fold_count"):
            object.__setattr__(self, name, _integer(getattr(self, name), path=f"aggregate.{name}"))
        if self.total_completed_real_outcomes + self.total_right_censored_real_outcomes != self.total_real_outcomes:
            raise ContractValidationError("aggregate real outcome counts do not reconcile")
        for name in ("pooled_median_excess_quality", "positive_comparable_fold_fraction", "worst_comparable_fold_excess", "pooled_real_baseline_median_quality", "pooled_control_support_median_quality", "pooled_control_resistance_median_quality"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _number(value, path=f"aggregate.{name}"))
        if self.comparable_fold_count == 0 and (self.completed_real_count != 0 or self.pooled_median_excess_quality is not None or self.positive_comparable_fold_fraction is not None or self.worst_comparable_fold_excess is not None):
            raise ContractValidationError("undefined comparable aggregate was populated")
        if self.comparable_fold_count > 0 and (self.positive_comparable_fold_fraction is None or self.worst_comparable_fold_excess is None):
            raise ContractValidationError("comparable aggregate lacks required metrics")
        if self.positive_comparable_fold_fraction is not None and not 0.0 <= self.positive_comparable_fold_fraction <= 1.0:
            raise ContractValidationError("positive fold fraction must be in [0, 1]")

    def to_payload(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


_GATE_CATEGORIES = frozenset({"sample", "comparability", "quality", "diagnostic"})


@dataclass(frozen=True)
class AdequacyGateResult:
    name: str
    category: str
    passed: bool
    value: float | int | None
    threshold: float | int | None
    operator: str
    reason: str
    fold: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _string(self.name, path="gate.name"))
        object.__setattr__(self, "category", _string(self.category, path="gate.category"))
        if self.category not in _GATE_CATEGORIES:
            raise ContractValidationError("unknown adequacy gate category")
        if type(self.passed) is not bool or self.operator not in {">=", ">", "<=", "=="} or type(self.reason) is not str or not self.reason:
            raise ContractValidationError("adequacy gate fields are invalid")
        if self.value is not None:
            object.__setattr__(self, "value", _number(self.value, path="gate.value"))
        if self.threshold is not None:
            object.__setattr__(self, "threshold", _number(self.threshold, path="gate.threshold"))
        if self.fold is not None:
            object.__setattr__(self, "fold", _string(self.fold, path="gate.fold"))
        if self.value is None and self.passed:
            raise ContractValidationError("undefined gate value cannot pass")

    def to_payload(self) -> dict[str, Any]:
        return {"name": self.name, "category": self.category, "passed": self.passed, "value": self.value, "threshold": self.threshold, "operator": self.operator, "reason": self.reason, "fold": self.fold}


@dataclass(frozen=True)
class BaselineAdequacyDecision:
    disposition: BaselineAdequacyDisposition
    gates: tuple[AdequacyGateResult, ...]
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "disposition", _enum(self.disposition, BaselineAdequacyDisposition, path="decision.disposition"))
        if type(self.gates) is not tuple or any(type(item) is not AdequacyGateResult for item in self.gates):
            raise ContractValidationError("decision gates are invalid")
        if len({item.name for item in self.gates}) != len(self.gates):
            raise ContractValidationError("decision gate names must be unique")
        if type(self.reason) is not str or not self.reason:
            raise ContractValidationError("decision reason must be non-empty")
        authoritative = [item for item in self.gates if item.category in {"sample", "comparability"}]
        quality = [item for item in self.gates if item.category == "quality"]
        if not authoritative or any(not item.passed for item in authoritative):
            expected = BaselineAdequacyDisposition.INSUFFICIENT_EVIDENCE
        elif len(quality) != 3:
            expected = BaselineAdequacyDisposition.INSUFFICIENT_EVIDENCE
        elif all(item.passed for item in quality):
            expected = BaselineAdequacyDisposition.BASELINE_BEATS_NAIVE_NULL
        else:
            expected = BaselineAdequacyDisposition.BASELINE_NOT_BETTER_THAN_NAIVE_NULL
        if self.disposition is not expected:
            raise ContractValidationError("decision disposition does not match exact gate precedence")

    def to_payload(self) -> dict[str, Any]:
        return {"disposition": self.disposition.value, "gates": [item.to_payload() for item in self.gates], "reason": self.reason}


@dataclass(frozen=True)
class BaselineParity:
    passed: bool
    checks: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.passed) is not bool or type(self.checks) is not tuple or not self.checks or any(type(item) is not str or not item for item in self.checks):
            raise ContractValidationError("baseline parity record is invalid")
        if not self.passed:
            raise ContractValidationError("failed baseline parity cannot enter study")

    def to_payload(self) -> dict[str, Any]:
        return {"passed": self.passed, "checks": list(self.checks)}


@dataclass(frozen=True)
class AdequacyResult:
    fold_side_nulls: tuple[FoldSideNull, ...]
    comparisons: tuple[RealOutcomeComparison, ...]
    fold_metrics: tuple[FoldAdequacyMetrics, ...]
    aggregate: AdequacyAggregateMetrics
    decision: BaselineAdequacyDecision

    def __post_init__(self) -> None:
        if type(self.fold_side_nulls) is not tuple or type(self.comparisons) is not tuple or type(self.fold_metrics) is not tuple or type(self.aggregate) is not AdequacyAggregateMetrics or type(self.decision) is not BaselineAdequacyDecision:
            raise ContractValidationError("adequacy result types are invalid")
        if any(type(item) is not FoldSideNull for item in self.fold_side_nulls) or any(type(item) is not RealOutcomeComparison for item in self.comparisons) or any(type(item) is not FoldAdequacyMetrics for item in self.fold_metrics):
            raise ContractValidationError("adequacy result members are invalid")

    def to_payload(self) -> dict[str, Any]:
        return {"fold_side_nulls": [item.to_payload() for item in self.fold_side_nulls], "comparisons": [item.to_payload() for item in self.comparisons], "fold_metrics": [item.to_payload() for item in self.fold_metrics], "aggregate": self.aggregate.to_payload(), "decision": self.decision.to_payload()}


@dataclass(frozen=True)
class BaselineAdequacyStudy:
    implementation_commit: str
    config_hash: str
    source_bundle_id: str
    source_id: str
    v17_config_hash: str
    v17_evaluation_bundle_id: str
    v17_evaluation_id: str
    v18_config_hash: str
    v18_study_bundle_id: str
    v18_study_id: str
    frozen_sr_config_hash: str
    frozen_input_hash: str
    baseline_candidate_id: str
    baseline_parity: BaselineParity
    real_outcomes: tuple[RealOutcomeRecord, ...]
    control_anchors: tuple[ControlAnchor, ...]
    control_outcomes: tuple[ControlOutcome, ...]
    control_accounting: ControlAccounting
    fold_side_nulls: tuple[FoldSideNull, ...]
    comparisons: tuple[RealOutcomeComparison, ...]
    fold_metrics: tuple[FoldAdequacyMetrics, ...]
    aggregate: AdequacyAggregateMetrics
    decision: BaselineAdequacyDecision
    study_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "implementation_commit", _commit(self.implementation_commit, path="study.implementation_commit"))
        for name in ("config_hash", "source_bundle_id", "source_id", "v17_config_hash", "v17_evaluation_bundle_id", "v17_evaluation_id", "v18_config_hash", "v18_study_bundle_id", "v18_study_id", "frozen_sr_config_hash", "frozen_input_hash", "baseline_candidate_id"):
            object.__setattr__(self, name, _hash(getattr(self, name), path=f"study.{name}"))
        if self.source_bundle_id != V17_SOURCE_BUNDLE_ID or self.v17_config_hash != V17_CONFIG_HASH or self.v17_evaluation_bundle_id != V17_EVALUATION_BUNDLE_ID or self.v17_evaluation_id != V17_EVALUATION_ID or self.v18_config_hash != V18_CONFIG_HASH or self.v18_study_bundle_id != V18_STUDY_BUNDLE_ID or self.v18_study_id != V18_STUDY_ID or self.baseline_candidate_id != V18_BASELINE_CANDIDATE_ID:
            raise ContractValidationError("study upstream identity is not approved")
        if type(self.baseline_parity) is not BaselineParity or not self.baseline_parity.passed:
            raise ContractValidationError("study requires passed baseline parity")
        if type(self.real_outcomes) is not tuple or any(type(item) is not RealOutcomeRecord for item in self.real_outcomes) or len({item.record_id for item in self.real_outcomes}) != len(self.real_outcomes):
            raise ContractValidationError("study real outcomes are invalid or duplicated")
        if type(self.control_anchors) is not tuple or any(type(item) is not ControlAnchor for item in self.control_anchors) or type(self.control_outcomes) is not tuple or any(type(item) is not ControlOutcome for item in self.control_outcomes) or type(self.control_accounting) is not ControlAccounting:
            raise ContractValidationError("study controls are invalid")
        if type(self.fold_side_nulls) is not tuple or any(type(item) is not FoldSideNull for item in self.fold_side_nulls) or type(self.comparisons) is not tuple or any(type(item) is not RealOutcomeComparison for item in self.comparisons) or type(self.fold_metrics) is not tuple or any(type(item) is not FoldAdequacyMetrics for item in self.fold_metrics):
            raise ContractValidationError("study adequacy metrics are invalid")
        if type(self.aggregate) is not AdequacyAggregateMetrics or type(self.decision) is not BaselineAdequacyDecision:
            raise ContractValidationError("study aggregate/decision are invalid")
        if self.aggregate.total_real_outcomes != len(self.real_outcomes) or self.aggregate.total_completed_real_outcomes != sum(item.outcome.completed for item in self.real_outcomes) or self.aggregate.total_right_censored_real_outcomes != sum(item.outcome.right_censored for item in self.real_outcomes):
            raise ContractValidationError("study real outcome accounting does not reconcile")
        if tuple(item.fold for item in self.fold_metrics) != tuple(item.fold for item in self.control_accounting.folds if item.fold is not None):
            raise ContractValidationError("study fold accounting ordering mismatch")
        object.__setattr__(self, "study_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "implementation_commit": self.implementation_commit,
            "config_hash": self.config_hash,
            "source_bundle_id": self.source_bundle_id,
            "source_id": self.source_id,
            "v17_config_hash": self.v17_config_hash,
            "v17_evaluation_bundle_id": self.v17_evaluation_bundle_id,
            "v17_evaluation_id": self.v17_evaluation_id,
            "v18_config_hash": self.v18_config_hash,
            "v18_study_bundle_id": self.v18_study_bundle_id,
            "v18_study_id": self.v18_study_id,
            "frozen_sr_config_hash": self.frozen_sr_config_hash,
            "frozen_input_hash": self.frozen_input_hash,
            "baseline_candidate_id": self.baseline_candidate_id,
            "baseline_parity": self.baseline_parity.to_payload(),
            "real_outcomes": [item.to_payload() for item in self.real_outcomes],
            "control_anchors": [item.to_payload() for item in self.control_anchors],
            "control_outcomes": [item.to_payload() for item in self.control_outcomes],
            "control_accounting": self.control_accounting.to_payload(),
            "fold_side_nulls": [item.to_payload() for item in self.fold_side_nulls],
            "comparisons": [item.to_payload() for item in self.comparisons],
            "fold_metrics": [item.to_payload() for item in self.fold_metrics],
            "aggregate": self.aggregate.to_payload(),
            "decision": self.decision.to_payload(),
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "study_id": self.study_id}


@dataclass(frozen=True)
class StudyRunResult:
    bundle_id: str
    path: str
    study_id: str
    disposition: BaselineAdequacyDisposition

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_id", _hash(self.bundle_id, path="run.bundle_id"))
        object.__setattr__(self, "study_id", _hash(self.study_id, path="run.study_id"))
        object.__setattr__(self, "path", _string(self.path, path="run.path"))
        object.__setattr__(self, "disposition", _enum(self.disposition, BaselineAdequacyDisposition, path="run.disposition"))

    def to_payload(self) -> dict[str, Any]:
        return {"bundle_id": self.bundle_id, "path": self.path, "study_id": self.study_id, "disposition": self.disposition.value}


__all__ = [
    "APPROVED_ASSET", "APPROVED_ADEQUACY_THRESHOLDS", "APPROVED_GRID_POLICY", "APPROVED_SOURCE_END", "APPROVED_SOURCE_ROWS", "APPROVED_SOURCE_START", "APPROVED_TIMEFRAME", "APPROVED_VENUE",
    "AdequacyAggregateMetrics", "AdequacyGateResult", "AdequacyResult", "AdequacyThresholds", "BaselineAdequacyConfig", "BaselineAdequacyDecision", "BaselineAdequacyDisposition", "BaselineAdequacyStudy", "BaselineParity",
    "CONFIG_VERSION", "CONTROL_ID_SCHEMA_VERSION", "CONTROL_SIDE_ORDER", "CONTROLS_PER_ANCHOR", "ControlAccounting", "ControlAnchor", "ControlBuildResult", "ControlEligibilityReason", "ControlOutcome", "DISPOSITION_VALUES", "ENTRY_VISIBLE_STATES", "FROZEN_ATR_METHOD", "FROZEN_ATR_PERIOD", "FROZEN_ATR_SEED", "FROZEN_COMMON_START_PERIOD", "FROZEN_INPUT_HASH", "FROZEN_OUTCOME_HORIZON", "FROZEN_OUTCOME_OFFSET", "FoldAdequacyMetrics", "FoldControlAccounting", "FoldSideNull", "FROZEN_SR_CONFIG_HASH", "INTERSECTION_POLICY", "PREVIOUS_SNAPSHOT_POLICY", "REJECTION_REASON_PRECEDENCE", "RealOutcomeComparison", "RealOutcomeRecord", "SCHEMA_VERSION", "StudyRunResult", "TRIAL_NAME", "V17_CONFIG_HASH", "V17_EVALUATION_BUNDLE_ID", "V17_EVALUATION_ID", "V17_EVALUATION_IMPLEMENTATION_COMMIT", "V17_SOURCE_BUNDLE_ID", "V17_SOURCE_IMPLEMENTATION_COMMIT", "V18_BASELINE_CANDIDATE_ID", "V18_CONFIG_HASH", "V18_IMPLEMENTATION_COMMIT", "V18_STUDY_BUNDLE_ID", "V18_STUDY_ID", "WINDOW_POLICY",
]
