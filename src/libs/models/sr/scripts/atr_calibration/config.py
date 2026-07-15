"""Strict, duplicate-safe configuration for SR-V1.6."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import re
from pathlib import Path, PurePath
from typing import Any
from types import MappingProxyType

from libs.models.sr.adapters.yaml_config import load_sr_config
from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash, require_utc, utc_isoformat


SOURCE_WINDOW_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
SOURCE_WINDOW_END = datetime(2026, 7, 1, tzinfo=timezone.utc)
HOLDOUT_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
EXPECTED_TRIAL_NAME = "sr-v1.6-taousdt-1d-atr-calibration"
EXPECTED_SOURCE_BUNDLE_ID = "d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925"
EXPECTED_SOURCE_IMPLEMENTATION_COMMIT = "2b8306b21a7e69f097218ffa05c34515b607de75"
EXPECTED_SOURCE_BARS_SHA256 = "b99e4c7281b23f6b13e6ce4148a8ef01a5da86c371463c095fcbfe586e4d0535"
EXPECTED_SR_CONFIG_HASH = "cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299"
EXPECTED_INPUT_HASH = "5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d"
EXPECTED_SOURCE_ROWS = 811
FOLD_NAMES = ("2024_q3", "2024_q4", "2025_q1", "2025_q2", "2025_q3", "2025_q4")
APPROVED_FOLD_BOUNDARIES = (
    ("2024_q3", datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2024, 10, 1, tzinfo=timezone.utc)),
    ("2024_q4", datetime(2024, 10, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
    ("2025_q1", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 4, 1, tzinfo=timezone.utc)),
    ("2025_q2", datetime(2025, 4, 1, tzinfo=timezone.utc), datetime(2025, 7, 1, tzinfo=timezone.utc)),
    ("2025_q3", datetime(2025, 7, 1, tzinfo=timezone.utc), datetime(2025, 10, 1, tzinfo=timezone.utc)),
    ("2025_q4", datetime(2025, 10, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
)
APPROVED_SELECTION_GATES = MappingProxyType(
    {
        "minimum_completed_first_touches_per_fold": 4,
        "minimum_eligible_development_folds": 4,
        "minimum_development_completed_first_touches": 24,
        "minimum_holdout_completed_first_touches": 8,
        "minimum_development_fold_win_fraction": 0.75,
        "minimum_development_pooled_delta_reference_atr": 0.10,
        "minimum_holdout_delta_reference_atr": 0.05,
        "maximum_invalidation_rate_delta": 0.05,
        "minimum_zone_creation_density_ratio": 0.50,
        "maximum_zone_creation_density_ratio": 2.00,
        "maximum_churn_rate_delta": 0.10,
        "maximum_right_censoring_rate_delta": 0.10,
    }
)
_HASH_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")


def _mapping(value: Any, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ContractValidationError(f"{path} must be a mapping with string keys")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], *, path: str) -> None:
    keys = set(value)
    missing = expected - keys
    unknown = keys - expected
    if missing or unknown:
        raise ContractValidationError(
            f"{path} keys mismatch; missing={sorted(missing)} unknown={sorted(unknown)}"
        )


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


def _number(value: Any, *, path: str, minimum: float | None = None, maximum: float | None = None) -> float:
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
    if maximum is not None and result > maximum:
        raise ContractValidationError(f"{path} must be <= {maximum}")
    return 0.0 if result == 0.0 else result


def _safe_path(value: Any, *, path: str) -> str:
    value = _string(value, path=path)
    normalized = value.replace("\\", "/")
    if Path(value).is_absolute() or normalized.startswith("/") or ".." in PurePath(normalized).parts:
        raise ContractValidationError(f"{path} must be a safe relative path")
    return value


def _utc(value: Any, *, path: str) -> datetime:
    value = _string(value, path=path)
    if not value.endswith("Z"):
        raise ContractValidationError(f"{path} must use strict UTC Z notation")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractValidationError(f"{path} must be an ISO-8601 timestamp") from exc
    parsed = require_utc(parsed, field_name=path)
    if parsed.hour or parsed.minute or parsed.second or parsed.microsecond:
        raise ContractValidationError(f"{path} must align to a UTC daily boundary")
    return parsed


@dataclass(frozen=True)
class FoldSpec:
    name: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        name = _string(self.name, path="fold.name")
        start = _utc(utc_isoformat(self.start), path="fold.start")
        end = _utc(utc_isoformat(self.end), path="fold.end")
        if start >= end:
            raise ContractValidationError("fold.start must be before fold.end")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    def to_payload(self) -> dict[str, Any]:
        return {"name": self.name, "start": utc_isoformat(self.start), "end": utc_isoformat(self.end)}


@dataclass(frozen=True)
class SelectionGates:
    minimum_completed_first_touches_per_fold: int
    minimum_eligible_development_folds: int
    minimum_development_completed_first_touches: int
    minimum_holdout_completed_first_touches: int
    minimum_development_fold_win_fraction: float
    minimum_development_pooled_delta_reference_atr: float
    minimum_holdout_delta_reference_atr: float
    maximum_invalidation_rate_delta: float
    minimum_zone_creation_density_ratio: float
    maximum_zone_creation_density_ratio: float
    maximum_churn_rate_delta: float
    maximum_right_censoring_rate_delta: float

    def __post_init__(self) -> None:
        integer_fields = (
            "minimum_completed_first_touches_per_fold",
            "minimum_eligible_development_folds",
            "minimum_development_completed_first_touches",
            "minimum_holdout_completed_first_touches",
        )
        for name in integer_fields:
            object.__setattr__(self, name, _integer(getattr(self, name), path=f"selection_gates.{name}", minimum=1))
        fraction = _number(self.minimum_development_fold_win_fraction, path="selection_gates.minimum_development_fold_win_fraction", minimum=0.0, maximum=1.0)
        object.__setattr__(self, "minimum_development_fold_win_fraction", fraction)
        for name in (
            "minimum_development_pooled_delta_reference_atr",
            "minimum_holdout_delta_reference_atr",
            "maximum_invalidation_rate_delta",
            "maximum_churn_rate_delta",
            "maximum_right_censoring_rate_delta",
        ):
            object.__setattr__(self, name, _number(getattr(self, name), path=f"selection_gates.{name}", minimum=0.0))
        minimum_ratio = _number(self.minimum_zone_creation_density_ratio, path="selection_gates.minimum_zone_creation_density_ratio", minimum=0.0)
        maximum_ratio = _number(self.maximum_zone_creation_density_ratio, path="selection_gates.maximum_zone_creation_density_ratio", minimum=minimum_ratio)
        if minimum_ratio == 0.0:
            raise ContractValidationError("minimum zone-creation density ratio must be positive")
        object.__setattr__(self, "minimum_zone_creation_density_ratio", minimum_ratio)
        object.__setattr__(self, "maximum_zone_creation_density_ratio", maximum_ratio)

    def to_payload(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__ if name != "config_hash"}


@dataclass(frozen=True)
class CalibrationConfig:
    version: str
    trial_name: str
    venue: str
    symbol: str
    timeframe: str
    source_bundle_path: str
    source_bundle_id: str
    source_implementation_commit: str
    source_bars_sha256: str
    source_row_count: int
    sr_config_path: str
    input_config_path: str
    expected_sr_config_hash: str
    expected_input_hash: str
    output_root: str
    atr_method: str
    atr_seed: str
    baseline_period: int
    candidate_periods: tuple[int, ...]
    common_start_period: int
    evaluation_reference_period: int
    outcome_start_offset_bars: int
    outcome_horizon_bars: int
    primary_metric: str
    primary_location: str
    development_folds: tuple[FoldSpec, ...]
    holdout_start: datetime
    holdout_end: datetime
    selection_gates: SelectionGates
    config_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if _string(self.version, path="version") != "1":
            raise ContractValidationError("unsupported calibration config version")
        for name, expected in (("trial_name", EXPECTED_TRIAL_NAME), ("venue", "binance_usdm"), ("symbol", "TAOUSDT"), ("timeframe", "1d")):
            if _string(getattr(self, name), path=name) != expected:
                raise ContractValidationError(f"{name} does not match frozen calibration")
        for name in ("source_bundle_id", "source_bars_sha256", "expected_sr_config_hash", "expected_input_hash"):
            object.__setattr__(self, name, _hash(getattr(self, name), path=name))
        object.__setattr__(self, "source_implementation_commit", _commit(self.source_implementation_commit, path="source_implementation_commit"))
        if self.source_bundle_id != EXPECTED_SOURCE_BUNDLE_ID or self.source_implementation_commit != EXPECTED_SOURCE_IMPLEMENTATION_COMMIT or self.source_bars_sha256 != EXPECTED_SOURCE_BARS_SHA256:
            raise ContractValidationError("source identity is not the approved V1.5 source")
        if self.expected_sr_config_hash != EXPECTED_SR_CONFIG_HASH or self.expected_input_hash != EXPECTED_INPUT_HASH:
            raise ContractValidationError("configuration identity is not the approved V1.5 configuration")
        object.__setattr__(self, "source_bundle_path", _safe_path(self.source_bundle_path, path="source_bundle_path"))
        object.__setattr__(self, "sr_config_path", _safe_path(self.sr_config_path, path="sr_config_path"))
        object.__setattr__(self, "input_config_path", _safe_path(self.input_config_path, path="input_config_path"))
        object.__setattr__(self, "output_root", _safe_path(self.output_root, path="output_root"))
        object.__setattr__(self, "source_row_count", _integer(self.source_row_count, path="source_row_count", minimum=1))
        if self.source_row_count != EXPECTED_SOURCE_ROWS:
            raise ContractValidationError("source_row_count does not match approved V1.5 source")
        if _string(self.atr_method, path="atr.method") != "wilder_rma" or _string(self.atr_seed, path="atr.seed") != "sma":
            raise ContractValidationError("ATR method/seed are fixed to wilder_rma/sma")
        object.__setattr__(self, "baseline_period", _integer(self.baseline_period, path="atr.baseline_period", minimum=1))
        if type(self.candidate_periods) is not tuple or not self.candidate_periods:
            raise ContractValidationError("candidate_periods must be a non-empty tuple")
        periods = tuple(_integer(item, path="atr.candidate_periods", minimum=1) for item in self.candidate_periods)
        if periods != tuple(sorted(periods)) or len(set(periods)) != len(periods):
            raise ContractValidationError("candidate_periods must be sorted and unique")
        if periods != (7, 10, 14, 20, 28):
            raise ContractValidationError("candidate_periods do not match the predeclared set")
        object.__setattr__(self, "candidate_periods", periods)
        object.__setattr__(self, "common_start_period", _integer(self.common_start_period, path="atr.common_start_period", minimum=1))
        object.__setattr__(self, "evaluation_reference_period", _integer(self.evaluation_reference_period, path="atr.evaluation_reference_period", minimum=1))
        if self.baseline_period != 14 or self.evaluation_reference_period != 14 or self.common_start_period != 28 or 14 not in periods:
            raise ContractValidationError("baseline/reference/common ATR periods are inconsistent")
        object.__setattr__(self, "outcome_start_offset_bars", _integer(self.outcome_start_offset_bars, path="outcome.start_offset_bars", minimum=1))
        object.__setattr__(self, "outcome_horizon_bars", _integer(self.outcome_horizon_bars, path="outcome.horizon_bars", minimum=1))
        if self.outcome_start_offset_bars != 1 or self.outcome_horizon_bars != 10:
            raise ContractValidationError("outcome offset/horizon do not match the approved protocol")
        if _string(self.primary_metric, path="outcome.primary_metric") != "median_first_touch_quality_reference_atr" or _string(self.primary_location, path="outcome.primary_location") != "median":
            raise ContractValidationError("outcome metric/location do not match the approved protocol")
        if type(self.development_folds) is not tuple or len(self.development_folds) != len(FOLD_NAMES):
            raise ContractValidationError("exactly six development folds are required")
        if tuple(fold.name for fold in self.development_folds) != FOLD_NAMES:
            raise ContractValidationError("development fold names/order do not match protocol")
        if tuple((fold.name, fold.start, fold.end) for fold in self.development_folds) != APPROVED_FOLD_BOUNDARIES:
            raise ContractValidationError("development fold boundaries do not match the approved protocol")
        previous = None
        for fold in self.development_folds:
            if fold.start < SOURCE_WINDOW_START or fold.end > HOLDOUT_START:
                raise ContractValidationError("development fold exceeds source/holdout bounds")
            if previous is not None and fold.start != previous:
                raise ContractValidationError("development folds must be contiguous")
            previous = fold.end
        holdout_start = _utc(utc_isoformat(self.holdout_start), path="holdout.start")
        holdout_end = _utc(utc_isoformat(self.holdout_end), path="holdout.end")
        if holdout_start != HOLDOUT_START or holdout_end != SOURCE_WINDOW_END or holdout_start >= holdout_end:
            raise ContractValidationError("holdout bounds do not match the approved protocol")
        object.__setattr__(self, "holdout_start", holdout_start)
        object.__setattr__(self, "holdout_end", holdout_end)
        if type(self.selection_gates) is not SelectionGates:
            raise ContractValidationError("selection_gates must be exactly SelectionGates")
        if self.selection_gates.to_payload() != dict(APPROVED_SELECTION_GATES):
            raise ContractValidationError("selection gates do not match the approved protocol")
        object.__setattr__(self, "config_hash", deterministic_hash(self.to_payload()))

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "calibration": {
                "trial_name": self.trial_name,
                "venue": self.venue,
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "source_bundle_path": self.source_bundle_path,
                "source_bundle_id": self.source_bundle_id,
                "source_implementation_commit": self.source_implementation_commit,
                "source_bars_sha256": self.source_bars_sha256,
                "source_row_count": self.source_row_count,
                "sr_config_path": self.sr_config_path,
                "input_config_path": self.input_config_path,
                "expected_sr_config_hash": self.expected_sr_config_hash,
                "expected_input_hash": self.expected_input_hash,
                "output_root": self.output_root,
            },
            "atr": {
                "method": self.atr_method,
                "seed": self.atr_seed,
                "baseline_period": self.baseline_period,
                "candidate_periods": list(self.candidate_periods),
                "common_start_period": self.common_start_period,
                "evaluation_reference_period": self.evaluation_reference_period,
            },
            "outcome": {
                "start_offset_bars": self.outcome_start_offset_bars,
                "horizon_bars": self.outcome_horizon_bars,
                "primary_metric": self.primary_metric,
                "primary_location": self.primary_location,
            },
            "development": {"folds": [fold.to_payload() for fold in self.development_folds]},
            "holdout": {"start": utc_isoformat(self.holdout_start), "end": utc_isoformat(self.holdout_end)},
            "selection_gates": self.selection_gates.to_payload(),
        }


def _parse_document(raw: Any) -> CalibrationConfig:
    root = _mapping(raw, path="calibration config")
    _exact_keys(root, {"version", "calibration", "atr", "outcome", "development", "holdout", "selection_gates"}, path="calibration config")
    calibration = _mapping(root["calibration"], path="calibration")
    _exact_keys(calibration, {"trial_name", "venue", "symbol", "timeframe", "source_bundle_path", "source_bundle_id", "source_implementation_commit", "source_bars_sha256", "source_row_count", "sr_config_path", "input_config_path", "expected_sr_config_hash", "expected_input_hash", "output_root"}, path="calibration")
    atr = _mapping(root["atr"], path="atr")
    _exact_keys(atr, {"method", "seed", "baseline_period", "candidate_periods", "common_start_period", "evaluation_reference_period"}, path="atr")
    if type(atr["candidate_periods"]) is not list:
        raise ContractValidationError("atr.candidate_periods must be a list")
    outcome = _mapping(root["outcome"], path="outcome")
    _exact_keys(outcome, {"start_offset_bars", "horizon_bars", "primary_metric", "primary_location"}, path="outcome")
    development = _mapping(root["development"], path="development")
    _exact_keys(development, {"folds"}, path="development")
    folds_raw = development["folds"]
    if type(folds_raw) is not list:
        raise ContractValidationError("development.folds must be a list")
    folds: list[FoldSpec] = []
    for index, raw_fold in enumerate(folds_raw):
        mapping = _mapping(raw_fold, path=f"development.folds[{index}]")
        _exact_keys(mapping, {"name", "start", "end"}, path=f"development.folds[{index}]")
        folds.append(FoldSpec(name=_string(mapping["name"], path=f"development.folds[{index}].name"), start=_utc(mapping["start"], path=f"development.folds[{index}].start"), end=_utc(mapping["end"], path=f"development.folds[{index}].end")))
    holdout = _mapping(root["holdout"], path="holdout")
    _exact_keys(holdout, {"start", "end"}, path="holdout")
    gates = _mapping(root["selection_gates"], path="selection_gates")
    gate_names = set(SelectionGates.__dataclass_fields__)
    _exact_keys(gates, gate_names, path="selection_gates")
    selection_gates = SelectionGates(**{name: gates[name] for name in gate_names})
    return CalibrationConfig(
        version=root["version"],
        trial_name=calibration["trial_name"],
        venue=calibration["venue"],
        symbol=calibration["symbol"],
        timeframe=calibration["timeframe"],
        source_bundle_path=calibration["source_bundle_path"],
        source_bundle_id=calibration["source_bundle_id"],
        source_implementation_commit=calibration["source_implementation_commit"],
        source_bars_sha256=calibration["source_bars_sha256"],
        source_row_count=calibration["source_row_count"],
        sr_config_path=calibration["sr_config_path"],
        input_config_path=calibration["input_config_path"],
        expected_sr_config_hash=calibration["expected_sr_config_hash"],
        expected_input_hash=calibration["expected_input_hash"],
        output_root=calibration["output_root"],
        atr_method=atr["method"],
        atr_seed=atr["seed"],
        baseline_period=atr["baseline_period"],
        candidate_periods=tuple(atr["candidate_periods"]) if type(atr["candidate_periods"]) is list else atr["candidate_periods"],
        common_start_period=atr["common_start_period"],
        evaluation_reference_period=atr["evaluation_reference_period"],
        outcome_start_offset_bars=outcome["start_offset_bars"],
        outcome_horizon_bars=outcome["horizon_bars"],
        primary_metric=outcome["primary_metric"],
        primary_location=outcome["primary_location"],
        development_folds=tuple(folds),
        holdout_start=_utc(holdout["start"], path="holdout.start"),
        holdout_end=_utc(holdout["end"], path="holdout.end"),
        selection_gates=selection_gates,
    )


def load_calibration_config(path: str | Path) -> CalibrationConfig:
    """Load and validate exactly one duplicate-safe calibration YAML document."""
    return _parse_document(load_sr_config(path))


def parse_calibration_config(raw: Mapping[str, Any]) -> CalibrationConfig:
    return _parse_document(raw)


__all__ = [
    "APPROVED_FOLD_BOUNDARIES",
    "APPROVED_SELECTION_GATES",
    "CalibrationConfig",
    "EXPECTED_INPUT_HASH",
    "EXPECTED_SOURCE_BARS_SHA256",
    "EXPECTED_SOURCE_BUNDLE_ID",
    "EXPECTED_SOURCE_IMPLEMENTATION_COMMIT",
    "EXPECTED_SR_CONFIG_HASH",
    "FoldSpec",
    "HOLDOUT_START",
    "SelectionGates",
    "SOURCE_WINDOW_END",
    "SOURCE_WINDOW_START",
    "load_calibration_config",
    "parse_calibration_config",
]
