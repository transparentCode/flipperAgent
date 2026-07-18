"""Fail-closed configuration for the SR-V1.7 cohort-readiness trial."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePath
import math
import re
from typing import Any

from libs.models.sr.adapters.yaml_config import load_sr_config
from libs.models.sr.domain import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash, require_utc, utc_isoformat

from .contracts import (
    ADAPTER_IDENTITY,
    ADAPTER_LIMIT,
    APPROVED_ASSETS,
    APPROVED_GRID_POLICY,
    APPROVED_SOURCE_END,
    APPROVED_SOURCE_ROWS,
    APPROVED_SOURCE_START,
    APPROVED_TIMEFRAME,
    APPROVED_VENUE,
    FROZEN_INPUT_HASH,
    FROZEN_SR_CONFIG_HASH,
    ReadinessGates,
    TAO_BARS_SHA256,
    TAO_SOURCE_BUNDLE_ID,
    TAO_SOURCE_ID,
    TAO_SOURCE_IMPLEMENTATION_COMMIT,
    TAO_SOURCE_MEMBER_SHA256,
    CohortFold,
)


CONFIG_VERSION = "1"
TRIAL_NAME = "sr-v1.7-1d-cohort-readiness"
_HASH_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")
_ROOT_KEYS = {
    "version", "trial", "sources", "provider", "grid", "configs", "atr",
    "outcome", "folds", "readiness", "output",
}


def _mapping(value: Any, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ContractValidationError(f"{path} must be a mapping with string keys")
    return value


def _exact(value: Mapping[str, Any], expected: set[str], *, path: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ContractValidationError(
            f"{path} keys mismatch; missing={sorted(expected - actual)} unknown={sorted(actual - expected)}"
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
        raise ContractValidationError(f"{path} must be finite") from None
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{path} must be >= {minimum}")
    return 0.0 if result == 0.0 else result


def _path(value: Any, *, path: str) -> str:
    value = _string(value, path=path)
    normalized = value.replace("\\", "/")
    if Path(value).is_absolute() or normalized.startswith("/") or ".." in PurePath(normalized).parts:
        raise ContractValidationError(f"{path} must be a safe relative path")
    return value


def _utc(value: Any, *, path: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise ContractValidationError(f"{path} must use strict UTC Z notation")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractValidationError(f"{path} must be an ISO-8601 timestamp") from exc
    try:
        parsed = require_utc(parsed, field_name=path)
    except ContractValidationError:
        raise
    if parsed.hour or parsed.minute or parsed.second or parsed.microsecond:
        raise ContractValidationError(f"{path} must align to a UTC daily boundary")
    return parsed


@dataclass(frozen=True)
class CohortConfig:
    version: str
    trial_name: str
    venue: str
    timeframe: str
    assets: tuple[str, ...]
    tao_source_path: str
    tao_source_id: str
    tao_source_bundle_id: str
    tao_bars_sha256: str
    tao_source_member_sha256: str
    tao_source_implementation_commit: str
    source_row_count: int
    source_since: datetime
    source_until: datetime
    provider_adapter: str
    provider_limit: int
    grid_policy: str
    sr_config_path: str
    input_config_path: str
    expected_sr_config_hash: str
    expected_input_hash: str
    atr_method: str
    atr_period: int
    atr_seed: str
    common_start_period: int
    outcome_start_offset_bars: int
    outcome_horizon_bars: int
    primary_metric: str
    primary_location: str
    folds: tuple[CohortFold, ...]
    readiness_gates: ReadinessGates
    output_root: str
    config_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if _string(self.version, path="version") != CONFIG_VERSION:
            raise ContractValidationError("unsupported cohort config version")
        if _string(self.trial_name, path="trial_name") != TRIAL_NAME:
            raise ContractValidationError("trial_name does not match the frozen V1.7 protocol")
        if _string(self.venue, path="venue") != APPROVED_VENUE or _string(self.timeframe, path="timeframe") != APPROVED_TIMEFRAME:
            raise ContractValidationError("venue/timeframe are outside the approved V1.7 protocol")
        if type(self.assets) is not tuple or self.assets != APPROVED_ASSETS:
            raise ContractValidationError("assets must be exactly the canonical four-asset tuple")
        object.__setattr__(self, "assets", tuple(_string(asset, path="assets[]") for asset in self.assets))
        for name in ("tao_source_id", "tao_source_bundle_id", "tao_bars_sha256", "tao_source_member_sha256", "expected_sr_config_hash", "expected_input_hash"):
            object.__setattr__(self, name, _hash(getattr(self, name), path=name))
        if self.tao_source_id != TAO_SOURCE_ID or self.tao_source_bundle_id != TAO_SOURCE_BUNDLE_ID or self.tao_bars_sha256 != TAO_BARS_SHA256 or self.tao_source_member_sha256 != TAO_SOURCE_MEMBER_SHA256:
            raise ContractValidationError("TAOUSDT source identity is not the approved V1.6 capsule")
        if self.expected_sr_config_hash != FROZEN_SR_CONFIG_HASH or self.expected_input_hash != FROZEN_INPUT_HASH:
            raise ContractValidationError("frozen SR/input config hashes do not match V1.6")
        commit = _string(self.tao_source_implementation_commit, path="tao_source_implementation_commit")
        if _COMMIT_RE.fullmatch(commit) is None or commit != TAO_SOURCE_IMPLEMENTATION_COMMIT:
            raise ContractValidationError("TAOUSDT source implementation identity is not approved")
        object.__setattr__(self, "tao_source_implementation_commit", commit)
        object.__setattr__(self, "tao_source_path", _path(self.tao_source_path, path="tao_source_path"))
        object.__setattr__(self, "sr_config_path", _path(self.sr_config_path, path="sr_config_path"))
        object.__setattr__(self, "input_config_path", _path(self.input_config_path, path="input_config_path"))
        object.__setattr__(self, "output_root", _path(self.output_root, path="output_root"))
        object.__setattr__(self, "source_row_count", _integer(self.source_row_count, path="source_row_count", minimum=1))
        if self.source_row_count != APPROVED_SOURCE_ROWS:
            raise ContractValidationError("source_row_count must be 629")
        source_since = _utc(utc_isoformat(self.source_since), path="source_since")
        source_until = _utc(utc_isoformat(self.source_until), path="source_until")
        if source_since != APPROVED_SOURCE_START or source_until != APPROVED_SOURCE_END:
            raise ContractValidationError("source window does not match the frozen TAOUSDT development grid")
        object.__setattr__(self, "source_since", source_since)
        object.__setattr__(self, "source_until", source_until)
        if _string(self.provider_adapter, path="provider.adapter") != ADAPTER_IDENTITY:
            raise ContractValidationError("unsupported provider adapter")
        object.__setattr__(self, "provider_limit", _integer(self.provider_limit, path="provider.limit", minimum=1))
        if self.provider_limit != ADAPTER_LIMIT:
            raise ContractValidationError("provider limit must be 1000")
        if _string(self.grid_policy, path="grid.policy") != APPROVED_GRID_POLICY:
            raise ContractValidationError("unsupported timestamp-grid policy")
        if _string(self.atr_method, path="atr.method") != "wilder_rma" or _string(self.atr_seed, path="atr.seed") != "sma":
            raise ContractValidationError("ATR method/seed must be wilder_rma/sma")
        object.__setattr__(self, "atr_period", _integer(self.atr_period, path="atr.period", minimum=1))
        object.__setattr__(self, "common_start_period", _integer(self.common_start_period, path="atr.common_start_period", minimum=1))
        if self.atr_period != 14 or self.common_start_period != 28:
            raise ContractValidationError("ATR period/common start are frozen to 14/28")
        object.__setattr__(self, "outcome_start_offset_bars", _integer(self.outcome_start_offset_bars, path="outcome.start_offset_bars", minimum=1))
        object.__setattr__(self, "outcome_horizon_bars", _integer(self.outcome_horizon_bars, path="outcome.horizon_bars", minimum=1))
        if self.outcome_start_offset_bars != 1 or self.outcome_horizon_bars != 10:
            raise ContractValidationError("outcome offset/horizon are frozen to 1/10")
        if _string(self.primary_metric, path="outcome.primary_metric") != "descriptive_first_touch_quality_reference_atr" or _string(self.primary_location, path="outcome.primary_location") != "per_asset_and_cohort":
            raise ContractValidationError("unsupported outcome metric contract")
        if type(self.folds) is not tuple or len(self.folds) != 6:
            raise ContractValidationError("exactly six folds are required")
        expected_names = ("2024_q3", "2024_q4", "2025_q1", "2025_q2", "2025_q3", "2025_q4")
        expected_bounds = (
            (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2024, 10, 1, tzinfo=timezone.utc)),
            (datetime(2024, 10, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
            (datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 4, 1, tzinfo=timezone.utc)),
            (datetime(2025, 4, 1, tzinfo=timezone.utc), datetime(2025, 7, 1, tzinfo=timezone.utc)),
            (datetime(2025, 7, 1, tzinfo=timezone.utc), datetime(2025, 10, 1, tzinfo=timezone.utc)),
            (datetime(2025, 10, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        if tuple(fold.name for fold in self.folds) != expected_names or tuple((fold.start, fold.end) for fold in self.folds) != expected_bounds:
            raise ContractValidationError("fold names/boundaries do not match the frozen protocol")
        previous = None
        for fold in self.folds:
            if fold.start < self.source_since or fold.end > datetime(2026, 1, 1, tzinfo=timezone.utc):
                raise ContractValidationError("fold exceeds the development source")
            if previous is not None and fold.start != previous:
                raise ContractValidationError("folds must be contiguous")
            previous = fold.end
        if type(self.readiness_gates) is not ReadinessGates or self.readiness_gates.to_payload() != {
            "minimum_completed_first_touches_per_fold": 4,
            "minimum_eligible_development_folds": 4,
            "minimum_development_completed_first_touches": 24,
        }:
            raise ContractValidationError("readiness gates do not match the frozen protocol")
        object.__setattr__(self, "config_hash", deterministic_hash(self.to_payload()))

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "trial": {"trial_name": self.trial_name, "venue": self.venue, "timeframe": self.timeframe, "assets": list(self.assets)},
            "sources": {
                "taousdt": {
                    "path": self.tao_source_path, "source_id": self.tao_source_id, "source_bundle_id": self.tao_source_bundle_id,
                    "bars_sha256": self.tao_bars_sha256, "source_member_sha256": self.tao_source_member_sha256,
                    "implementation_commit": self.tao_source_implementation_commit, "row_count": self.source_row_count,
                },
                "window": {"since": utc_isoformat(self.source_since), "until": utc_isoformat(self.source_until)},
            },
            "provider": {"adapter": self.provider_adapter, "limit": self.provider_limit},
            "grid": {"policy": self.grid_policy},
            "configs": {"sr_path": self.sr_config_path, "input_path": self.input_config_path, "expected_sr_hash": self.expected_sr_config_hash, "expected_input_hash": self.expected_input_hash},
            "atr": {"method": self.atr_method, "period": self.atr_period, "seed": self.atr_seed, "common_start_period": self.common_start_period},
            "outcome": {"start_offset_bars": self.outcome_start_offset_bars, "horizon_bars": self.outcome_horizon_bars, "primary_metric": self.primary_metric, "primary_location": self.primary_location},
            "folds": [fold.to_payload() for fold in self.folds],
            "readiness": self.readiness_gates.to_payload(),
            "output": {"root": self.output_root},
        }


def _parse_document(raw: Any) -> CohortConfig:
    root = _mapping(raw, path="cohort config")
    _exact(root, _ROOT_KEYS, path="cohort config")
    trial = _mapping(root["trial"], path="trial")
    _exact(trial, {"trial_name", "venue", "timeframe", "assets"}, path="trial")
    assets = trial["assets"]
    if type(assets) is not list:
        raise ContractValidationError("trial.assets must be a list")
    if len(assets) != len(APPROVED_ASSETS) or tuple(assets) != APPROVED_ASSETS:
        raise ContractValidationError("trial.assets must be exactly TAO/BTC/ETH/SOL in canonical order")
    sources = _mapping(root["sources"], path="sources")
    _exact(sources, {"taousdt", "window"}, path="sources")
    tao = _mapping(sources["taousdt"], path="sources.taousdt")
    _exact(tao, {"path", "source_id", "source_bundle_id", "bars_sha256", "source_member_sha256", "implementation_commit", "row_count"}, path="sources.taousdt")
    window = _mapping(sources["window"], path="sources.window")
    _exact(window, {"since", "until"}, path="sources.window")
    provider = _mapping(root["provider"], path="provider")
    _exact(provider, {"adapter", "limit"}, path="provider")
    grid = _mapping(root["grid"], path="grid")
    _exact(grid, {"policy"}, path="grid")
    configs = _mapping(root["configs"], path="configs")
    _exact(configs, {"sr_path", "input_path", "expected_sr_hash", "expected_input_hash"}, path="configs")
    atr = _mapping(root["atr"], path="atr")
    _exact(atr, {"method", "period", "seed", "common_start_period"}, path="atr")
    outcome = _mapping(root["outcome"], path="outcome")
    _exact(outcome, {"start_offset_bars", "horizon_bars", "primary_metric", "primary_location"}, path="outcome")
    folds_raw = root["folds"]
    if type(folds_raw) is not list:
        raise ContractValidationError("folds must be a list")
    folds: list[CohortFold] = []
    for index, item in enumerate(folds_raw):
        fold = _mapping(item, path=f"folds[{index}]")
        _exact(fold, {"name", "start", "end"}, path=f"folds[{index}]")
        folds.append(CohortFold(name=fold["name"], start=_utc(fold["start"], path=f"folds[{index}].start"), end=_utc(fold["end"], path=f"folds[{index}].end")))
    readiness = _mapping(root["readiness"], path="readiness")
    _exact(readiness, {"minimum_completed_first_touches_per_fold", "minimum_eligible_development_folds", "minimum_development_completed_first_touches"}, path="readiness")
    output = _mapping(root["output"], path="output")
    _exact(output, {"root"}, path="output")
    return CohortConfig(
        version=root["version"], trial_name=trial["trial_name"], venue=trial["venue"], timeframe=trial["timeframe"], assets=tuple(assets),
        tao_source_path=tao["path"], tao_source_id=tao["source_id"], tao_source_bundle_id=tao["source_bundle_id"], tao_bars_sha256=tao["bars_sha256"], tao_source_member_sha256=tao["source_member_sha256"], tao_source_implementation_commit=tao["implementation_commit"], source_row_count=tao["row_count"], source_since=_utc(window["since"], path="sources.window.since"), source_until=_utc(window["until"], path="sources.window.until"),
        provider_adapter=provider["adapter"], provider_limit=provider["limit"], grid_policy=grid["policy"], sr_config_path=configs["sr_path"], input_config_path=configs["input_path"], expected_sr_config_hash=configs["expected_sr_hash"], expected_input_hash=configs["expected_input_hash"],
        atr_method=atr["method"], atr_period=atr["period"], atr_seed=atr["seed"], common_start_period=atr["common_start_period"], outcome_start_offset_bars=outcome["start_offset_bars"], outcome_horizon_bars=outcome["horizon_bars"], primary_metric=outcome["primary_metric"], primary_location=outcome["primary_location"], folds=tuple(folds), readiness_gates=ReadinessGates(**dict(readiness)), output_root=output["root"],
    )


def parse_cohort_config(raw: Mapping[str, Any]) -> CohortConfig:
    return _parse_document(raw)


def load_cohort_config(path: str | Path) -> CohortConfig:
    return _parse_document(load_sr_config(path))


__all__ = ["CONFIG_VERSION", "CohortConfig", "TRIAL_NAME", "load_cohort_config", "parse_cohort_config"]
