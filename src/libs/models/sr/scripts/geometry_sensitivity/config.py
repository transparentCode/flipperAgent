"""Fail-closed configuration for the SR-V1.8 geometry study."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from pathlib import Path, PurePath
import re
from typing import Any

from libs.models.sr.adapters.yaml_config import load_sr_config
from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash, require_utc
from libs.models.sr.scripts.cohort_readiness.contracts import (
    APPROVED_ASSETS,
    APPROVED_TIMEFRAME,
    APPROVED_VENUE,
    CohortFold,
    ReadinessGates,
)


CONFIG_VERSION = "1"
TRIAL_NAME = "sr-v1.8-1d-geometry-sensitivity"
APPROVED_PIVOT_SPANS = (3, 5, 7)
APPROVED_ZONE_HALF_WIDTHS = (0.15, 0.25, 0.35)
BASELINE_PIVOT_SPAN = 5
BASELINE_ZONE_HALF_WIDTH = 0.25
V17_CONFIG_HASH = "370d2b66e8e3031b0df8547e8b52c61288e14c5d1b858612ce9fae712e1690a7"
V17_SOURCE_BUNDLE_ID = "6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9"
V17_SOURCE_IMPLEMENTATION_COMMIT = "be6459a8e06ec95b634b2cfb2b91a08cd31d9ba2"
V17_EVALUATION_BUNDLE_ID = "824e9265a63073ba792762a891adf52deec9677d791c40641dc0107c1f2b840d"
V17_EVALUATION_ID = "49a895360774ec0c46349eae2d1ec6f56e7262e5f1411ab992f9886d9040fa8d"
V17_EVALUATION_IMPLEMENTATION_COMMIT = "4cb069af6142dbd7dadf7a5ebef49d2da0ba26a7"
FROZEN_SR_CONFIG_HASH = "cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299"
FROZEN_INPUT_HASH = "5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d"
FROZEN_ATR_METHOD = "wilder_rma"
FROZEN_ATR_PERIOD = 14
FROZEN_ATR_SEED = "sma"
FROZEN_COMMON_START_PERIOD = 28
FROZEN_OUTCOME_OFFSET = 1
FROZEN_OUTCOME_HORIZON = 10
WINDOW_POLICY = "half_open_utc_daily"

_HASH_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")


def _mapping(value: Any, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ContractValidationError(f"{path} must be a mapping with string keys")
    return value


def _exact(value: Mapping[str, Any], expected: set[str], *, path: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ContractValidationError(
            f"{path} keys mismatch; missing={sorted(expected - actual)} "
            f"unknown={sorted(actual - expected)}"
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


def _path(value: Any, *, path: str) -> str:
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
class SelectionThresholds:
    """All V1.8 gates, frozen before any candidate is evaluated."""

    minimum_completed_first_touches_per_fold: int
    minimum_eligible_development_folds: int
    minimum_development_completed_first_touches: int
    minimum_comparable_folds_per_asset: int
    minimum_comparable_asset_fold_units: int
    minimum_median_asset_delta: float
    minimum_micro_delta: float
    minimum_positive_asset_count: int
    minimum_worst_asset_delta: float
    minimum_asset_fold_win_fraction: float
    maximum_invalidation_rate_delta: float
    minimum_zone_creation_density_ratio: float
    maximum_zone_creation_density_ratio: float
    maximum_churn_rate_delta: float
    maximum_right_censoring_rate_delta: float

    def __post_init__(self) -> None:
        for name in (
            "minimum_completed_first_touches_per_fold",
            "minimum_eligible_development_folds",
            "minimum_development_completed_first_touches",
            "minimum_comparable_folds_per_asset",
            "minimum_comparable_asset_fold_units",
            "minimum_positive_asset_count",
        ):
            object.__setattr__(self, name, _integer(getattr(self, name), path=f"selection.{name}", minimum=1))
        for name in (
            "minimum_median_asset_delta",
            "minimum_micro_delta",
            "minimum_worst_asset_delta",
            "maximum_invalidation_rate_delta",
            "maximum_churn_rate_delta",
            "maximum_right_censoring_rate_delta",
        ):
            object.__setattr__(self, name, _number(getattr(self, name), path=f"selection.{name}"))
        object.__setattr__(self, "minimum_asset_fold_win_fraction", _number(self.minimum_asset_fold_win_fraction, path="selection.minimum_asset_fold_win_fraction", minimum=0.0, maximum=1.0))
        minimum_ratio = _number(self.minimum_zone_creation_density_ratio, path="selection.minimum_zone_creation_density_ratio", minimum=0.0)
        maximum_ratio = _number(self.maximum_zone_creation_density_ratio, path="selection.maximum_zone_creation_density_ratio", minimum=minimum_ratio)
        if minimum_ratio <= 0:
            raise ContractValidationError("selection.minimum_zone_creation_density_ratio must be positive")
        object.__setattr__(self, "minimum_zone_creation_density_ratio", minimum_ratio)
        object.__setattr__(self, "maximum_zone_creation_density_ratio", maximum_ratio)

    def to_payload(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class GeometrySensitivityConfig:
    version: str
    trial_name: str
    venue: str
    timeframe: str
    assets: tuple[str, ...]
    v17_config_path: str
    v17_config_hash: str
    source_bundle_path: str
    source_bundle_id: str
    source_implementation_commit: str
    evaluation_bundle_path: str
    evaluation_bundle_id: str
    evaluation_id: str
    evaluation_implementation_commit: str
    sr_config_path: str
    input_config_path: str
    frozen_sr_config_hash: str
    frozen_input_hash: str
    atr_method: str
    atr_period: int
    atr_seed: str
    common_start_period: int
    outcome_start_offset_bars: int
    outcome_horizon_bars: int
    window_policy: str
    folds: tuple[CohortFold, ...]
    readiness_gates: ReadinessGates
    pivot_span_bars: tuple[int, ...]
    zone_half_width_atr: tuple[float, ...]
    selection: SelectionThresholds
    output_root: str
    config_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if _string(self.version, path="version") != CONFIG_VERSION:
            raise ContractValidationError("unsupported V1.8 config version")
        if _string(self.trial_name, path="trial.trial_name") != TRIAL_NAME:
            raise ContractValidationError("trial name does not match V1.8")
        if _string(self.venue, path="trial.venue") != APPROVED_VENUE or _string(self.timeframe, path="trial.timeframe") != APPROVED_TIMEFRAME:
            raise ContractValidationError("venue/timeframe are outside V1.8")
        if type(self.assets) is not tuple or self.assets != APPROVED_ASSETS:
            raise ContractValidationError("assets must use the canonical V1.7 order")
        object.__setattr__(self, "assets", tuple(_string(asset, path="trial.assets[]") for asset in self.assets))
        for name in ("v17_config_hash", "source_bundle_id", "evaluation_bundle_id", "evaluation_id", "frozen_sr_config_hash", "frozen_input_hash"):
            object.__setattr__(self, name, _hash(getattr(self, name), path=f"inputs.{name}"))
        if self.v17_config_hash != V17_CONFIG_HASH or self.source_bundle_id != V17_SOURCE_BUNDLE_ID or self.evaluation_bundle_id != V17_EVALUATION_BUNDLE_ID or self.evaluation_id != V17_EVALUATION_ID:
            raise ContractValidationError("V1.7 source/evaluation identity is not approved")
        if self.frozen_sr_config_hash != FROZEN_SR_CONFIG_HASH or self.frozen_input_hash != FROZEN_INPUT_HASH:
            raise ContractValidationError("frozen production configuration identity is not approved")
        for name in ("source_implementation_commit", "evaluation_implementation_commit"):
            object.__setattr__(self, name, _commit(getattr(self, name), path=f"inputs.{name}"))
        if self.source_implementation_commit != V17_SOURCE_IMPLEMENTATION_COMMIT or self.evaluation_implementation_commit != V17_EVALUATION_IMPLEMENTATION_COMMIT:
            raise ContractValidationError("V1.7 implementation identities are not approved")
        for name in ("v17_config_path", "source_bundle_path", "evaluation_bundle_path", "sr_config_path", "input_config_path", "output_root"):
            object.__setattr__(self, name, _path(getattr(self, name), path=f"{name}"))
        if _string(self.atr_method, path="protocol.atr.method") != FROZEN_ATR_METHOD or _string(self.atr_seed, path="protocol.atr.seed") != FROZEN_ATR_SEED:
            raise ContractValidationError("ATR method/seed are not frozen Wilder/SMA")
        object.__setattr__(self, "atr_period", _integer(self.atr_period, path="protocol.atr.period", minimum=1))
        object.__setattr__(self, "common_start_period", _integer(self.common_start_period, path="protocol.atr.common_start_period", minimum=1))
        if (self.atr_period, self.common_start_period) != (FROZEN_ATR_PERIOD, FROZEN_COMMON_START_PERIOD):
            raise ContractValidationError("ATR period/common start are not frozen to 14/28")
        object.__setattr__(self, "outcome_start_offset_bars", _integer(self.outcome_start_offset_bars, path="protocol.outcome.start_offset_bars", minimum=1))
        object.__setattr__(self, "outcome_horizon_bars", _integer(self.outcome_horizon_bars, path="protocol.outcome.horizon_bars", minimum=1))
        if (self.outcome_start_offset_bars, self.outcome_horizon_bars) != (FROZEN_OUTCOME_OFFSET, FROZEN_OUTCOME_HORIZON):
            raise ContractValidationError("outcome offset/horizon are not frozen to 1/10")
        if _string(self.window_policy, path="protocol.outcome.window_policy") != WINDOW_POLICY:
            raise ContractValidationError("unsupported window policy")
        if type(self.folds) is not tuple or len(self.folds) != 6:
            raise ContractValidationError("exactly six V1.7 folds are required")
        expected = (
            ("2024_q3", datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2024, 10, 1, tzinfo=timezone.utc)),
            ("2024_q4", datetime(2024, 10, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
            ("2025_q1", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 4, 1, tzinfo=timezone.utc)),
            ("2025_q2", datetime(2025, 4, 1, tzinfo=timezone.utc), datetime(2025, 7, 1, tzinfo=timezone.utc)),
            ("2025_q3", datetime(2025, 7, 1, tzinfo=timezone.utc), datetime(2025, 10, 1, tzinfo=timezone.utc)),
            ("2025_q4", datetime(2025, 10, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        if tuple((fold.name, fold.start, fold.end) for fold in self.folds) != expected:
            raise ContractValidationError("fold names/boundaries do not match V1.7")
        if type(self.readiness_gates) is not ReadinessGates or self.readiness_gates.to_payload() != {
            "minimum_completed_first_touches_per_fold": 4,
            "minimum_eligible_development_folds": 4,
            "minimum_development_completed_first_touches": 24,
        }:
            raise ContractValidationError("readiness gates do not match V1.7")
        if type(self.pivot_span_bars) is not tuple or self.pivot_span_bars != APPROVED_PIVOT_SPANS:
            raise ContractValidationError("pivot_span_bars axis is not the exact approved axis")
        widths = tuple(_number(value, path="candidate_grid.zone_half_width_atr", minimum=0.0) for value in self.zone_half_width_atr)
        if widths != APPROVED_ZONE_HALF_WIDTHS:
            raise ContractValidationError("zone_half_width_atr axis is not the exact approved axis")
        object.__setattr__(self, "zone_half_width_atr", widths)
        object.__setattr__(self, "config_hash", deterministic_hash(self.to_payload()))

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "trial": {"trial_name": self.trial_name, "venue": self.venue, "timeframe": self.timeframe, "assets": list(self.assets)},
            "inputs": {
                "v17_config_path": self.v17_config_path,
                "v17_config_hash": self.v17_config_hash,
                "source_bundle_path": self.source_bundle_path,
                "source_bundle_id": self.source_bundle_id,
                "source_implementation_commit": self.source_implementation_commit,
                "evaluation_bundle_path": self.evaluation_bundle_path,
                "evaluation_bundle_id": self.evaluation_bundle_id,
                "evaluation_id": self.evaluation_id,
                "evaluation_implementation_commit": self.evaluation_implementation_commit,
                "sr_config_path": self.sr_config_path,
                "input_config_path": self.input_config_path,
                "frozen_sr_config_hash": self.frozen_sr_config_hash,
                "frozen_input_hash": self.frozen_input_hash,
            },
            "protocol": {
                "atr": {"method": self.atr_method, "period": self.atr_period, "seed": self.atr_seed, "common_start_period": self.common_start_period},
                "outcome": {"start_offset_bars": self.outcome_start_offset_bars, "horizon_bars": self.outcome_horizon_bars, "window_policy": self.window_policy},
                "folds": [fold.to_payload() for fold in self.folds],
                "readiness": self.readiness_gates.to_payload(),
            },
            "candidate_grid": {"pivot_span_bars": list(self.pivot_span_bars), "zone_half_width_atr": list(self.zone_half_width_atr)},
            "selection": self.selection.to_payload(),
            "output": {"root": self.output_root},
        }


def _parse_folds(raw: Any) -> tuple[CohortFold, ...]:
    if type(raw) is not list:
        raise ContractValidationError("protocol.folds must be a list")
    folds: list[CohortFold] = []
    for index, item in enumerate(raw):
        mapping = _mapping(item, path=f"protocol.folds[{index}]")
        _exact(mapping, {"name", "start", "end"}, path=f"protocol.folds[{index}]")
        folds.append(CohortFold(name=mapping["name"], start=_utc(mapping["start"], path=f"protocol.folds[{index}].start"), end=_utc(mapping["end"], path=f"protocol.folds[{index}].end")))
    return tuple(folds)


def _parse_document(raw: Any) -> GeometrySensitivityConfig:
    root = _mapping(raw, path="geometry sensitivity config")
    _exact(root, {"version", "trial", "inputs", "protocol", "candidate_grid", "selection", "output"}, path="geometry sensitivity config")
    trial = _mapping(root["trial"], path="trial")
    _exact(trial, {"trial_name", "venue", "timeframe", "assets"}, path="trial")
    assets = trial["assets"]
    if type(assets) is not list:
        raise ContractValidationError("trial.assets must be a list")
    inputs = _mapping(root["inputs"], path="inputs")
    _exact(inputs, {"v17_config_path", "v17_config_hash", "source_bundle_path", "source_bundle_id", "source_implementation_commit", "evaluation_bundle_path", "evaluation_bundle_id", "evaluation_id", "evaluation_implementation_commit", "sr_config_path", "input_config_path", "frozen_sr_config_hash", "frozen_input_hash"}, path="inputs")
    protocol = _mapping(root["protocol"], path="protocol")
    _exact(protocol, {"atr", "outcome", "folds", "readiness"}, path="protocol")
    atr = _mapping(protocol["atr"], path="protocol.atr")
    _exact(atr, {"method", "period", "seed", "common_start_period"}, path="protocol.atr")
    outcome = _mapping(protocol["outcome"], path="protocol.outcome")
    _exact(outcome, {"start_offset_bars", "horizon_bars", "window_policy"}, path="protocol.outcome")
    readiness = _mapping(protocol["readiness"], path="protocol.readiness")
    _exact(readiness, {"minimum_completed_first_touches_per_fold", "minimum_eligible_development_folds", "minimum_development_completed_first_touches"}, path="protocol.readiness")
    grid = _mapping(root["candidate_grid"], path="candidate_grid")
    _exact(grid, {"pivot_span_bars", "zone_half_width_atr"}, path="candidate_grid")
    if type(grid["pivot_span_bars"]) is not list or type(grid["zone_half_width_atr"]) is not list:
        raise ContractValidationError("candidate axes must be lists")
    selection = _mapping(root["selection"], path="selection")
    _exact(selection, set(SelectionThresholds.__dataclass_fields__), path="selection")
    output = _mapping(root["output"], path="output")
    _exact(output, {"root"}, path="output")
    return GeometrySensitivityConfig(
        version=root["version"], trial_name=trial["trial_name"], venue=trial["venue"], timeframe=trial["timeframe"], assets=tuple(assets),
        v17_config_path=inputs["v17_config_path"], v17_config_hash=inputs["v17_config_hash"], source_bundle_path=inputs["source_bundle_path"], source_bundle_id=inputs["source_bundle_id"], source_implementation_commit=inputs["source_implementation_commit"], evaluation_bundle_path=inputs["evaluation_bundle_path"], evaluation_bundle_id=inputs["evaluation_bundle_id"], evaluation_id=inputs["evaluation_id"], evaluation_implementation_commit=inputs["evaluation_implementation_commit"], sr_config_path=inputs["sr_config_path"], input_config_path=inputs["input_config_path"], frozen_sr_config_hash=inputs["frozen_sr_config_hash"], frozen_input_hash=inputs["frozen_input_hash"],
        atr_method=atr["method"], atr_period=atr["period"], atr_seed=atr["seed"], common_start_period=atr["common_start_period"], outcome_start_offset_bars=outcome["start_offset_bars"], outcome_horizon_bars=outcome["horizon_bars"], window_policy=outcome["window_policy"], folds=_parse_folds(protocol["folds"]), readiness_gates=ReadinessGates(**dict(readiness)), pivot_span_bars=tuple(grid["pivot_span_bars"]), zone_half_width_atr=tuple(grid["zone_half_width_atr"]), selection=SelectionThresholds(**dict(selection)), output_root=output["root"],
    )


def parse_geometry_config(raw: Mapping[str, Any]) -> GeometrySensitivityConfig:
    return _parse_document(raw)


def load_geometry_config(path: str | Path) -> GeometrySensitivityConfig:
    return _parse_document(load_sr_config(path))


load_config = load_geometry_config


__all__ = [
    "APPROVED_PIVOT_SPANS", "APPROVED_ZONE_HALF_WIDTHS", "BASELINE_PIVOT_SPAN", "BASELINE_ZONE_HALF_WIDTH",
    "CONFIG_VERSION", "FROZEN_INPUT_HASH", "FROZEN_SR_CONFIG_HASH", "GeometrySensitivityConfig", "SelectionThresholds",
    "TRIAL_NAME", "V17_CONFIG_HASH", "V17_EVALUATION_BUNDLE_ID", "V17_EVALUATION_ID", "V17_EVALUATION_IMPLEMENTATION_COMMIT",
    "V17_SOURCE_BUNDLE_ID", "V17_SOURCE_IMPLEMENTATION_COMMIT", "load_config", "load_geometry_config", "parse_geometry_config",
]
