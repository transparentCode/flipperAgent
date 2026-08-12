"""Strict immutable configuration for SR-V2.3 adaptive calibration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash, utc_isoformat
from libs.models.sr.research.config import (
    require_exact_keys,
    require_git_commit,
    require_integer,
    require_mapping,
    require_nonempty_string,
    require_safe_relative_path,
    require_sha256,
    require_utc_timestamp,
)
from libs.models.sr.research.config.strict_yaml import load_strict_research_yaml
from libs.models.sr.research.windows import CohortFold


CONFIG_VERSION = "1"
TRIAL_NAME = "sr-v2.3-adaptive-context-calibration"
VENUE = "binance_usdm"
ASSETS = ("TAOUSDT", "ETHUSDT", "SOLUSDT")
TIMEFRAMES = ("1d", "12h")
CANONICAL_COHORTS = tuple((asset, timeframe) for timeframe in TIMEFRAMES for asset in ASSETS)

FROZEN_1D_OUTER_BUNDLE_PATH = "research/tmp_sr_v1_7/source/6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9"
FROZEN_1D_OUTER_BUNDLE_ID = "6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9"
FROZEN_1D_IMPLEMENTATION_COMMIT = "be6459a8e06ec95b634b2cfb2b91a08cd31d9ba2"
FROZEN_1D_START = datetime(2024, 4, 11, tzinfo=timezone.utc)
FROZEN_1D_END = datetime(2025, 12, 31, tzinfo=timezone.utc)
FROZEN_1D_ROWS = 629
FROZEN_1D_GRID_POLICY = "exact_utc_daily_grid_from_verified_v1_7_member"
FROZEN_1D_MEMBERS = {
    "TAOUSDT": {
        "source_id": "fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120",
        "source_bundle_id": "d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925",
        "bars_sha256": "703367048f4ed7dc432ca9dfe0ad4afdc5a56eb2a508597ef00bdc3de8b81163",
        "grid_sha256": "d1f60173bc59a1301d08c8521b9f78fa0831daad3fd8b58edae392237d1e54e8",
    },
    "ETHUSDT": {
        "source_id": "3c525aca69ebba5931f7f6da2648ae79d2ce35315edab47ba7bea97f1cd32837",
        "source_bundle_id": "3c525aca69ebba5931f7f6da2648ae79d2ce35315edab47ba7bea97f1cd32837",
        "bars_sha256": "4f6a898a74cc0ea1c10f6f5d166c6a2c9d3990458af5cf0b876af6419c3f6231",
        "grid_sha256": "d1f60173bc59a1301d08c8521b9f78fa0831daad3fd8b58edae392237d1e54e8",
    },
    "SOLUSDT": {
        "source_id": "2fc22c565f84fbdac4f8607ba7ea43432f5e6cd4c5073e8f29a320513d404685",
        "source_bundle_id": "2fc22c565f84fbdac4f8607ba7ea43432f5e6cd4c5073e8f29a320513d404685",
        "bars_sha256": "810b973c78b632b839e992002649c5e73865e75b8750701cf058336997c8ba82",
        "grid_sha256": "d1f60173bc59a1301d08c8521b9f78fa0831daad3fd8b58edae392237d1e54e8",
    },
}

PROVIDER_12H_START = datetime(2024, 8, 19, tzinfo=timezone.utc)
PROVIDER_12H_END = datetime(2026, 1, 1, tzinfo=timezone.utc)
PROVIDER_12H_ROWS = 1000
PROVIDER_12H_INTERVAL = timedelta(hours=12)
PROVIDER_ADAPTER = "libs.market_data.binance_native.BinanceNativeAdapter"
PROVIDER_LIMIT = 1000
PROVIDER_CALLS_PER_ASSET = 1

ATR_PAYLOAD = {"method": "wilder_rma", "period": 14, "seed": "sma", "common_start_index": 28}
NORMALIZATION_DAYS = 365
BUCKETS = ("Q1", "Q2", "Q3", "Q4")
CALIBRATION_PAYLOAD = {
    "prior_alpha": 0.5,
    "prior_beta": 0.5,
    "external_precision": "sqrt_successes_plus_failures",
    "history_days": 365,
}
OUTCOME_PAYLOAD = {
    "first_touch_offset_bars": 1,
    "touch_search_bars": 50,
    "horizon_bars": 10,
    "control_side_order": ["SUPPORT", "RESISTANCE"],
    "label_rule": "paired_excess_quality_atr_strictly_greater_than_zero",
    "label_availability_rule": "last_closed_outcome_bar_strictly_before_prediction",
}
FOLD_BOUNDS = (
    ("2025_q1", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 4, 1, tzinfo=timezone.utc)),
    ("2025_q2", datetime(2025, 4, 1, tzinfo=timezone.utc), datetime(2025, 7, 1, tzinfo=timezone.utc)),
    ("2025_q3", datetime(2025, 7, 1, tzinfo=timezone.utc), datetime(2025, 10, 1, tzinfo=timezone.utc)),
    ("2025_q4", datetime(2025, 10, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
)
BOOTSTRAP_PAYLOAD = {
    "draws": 10000,
    "generator": "numpy.random.Generator",
    "bit_generator": "PCG64",
    "seed": 2303,
    "resampling": "cohort_fold_cells_then_cases_within_selected_cells",
    "interval": "central_90_percent",
}
DISPOSITIONS = (
    "ADAPTIVE_CONTEXT_SUPPORTED_FOR_SHADOW",
    "ADAPTIVE_CONTEXT_NOT_SUPPORTED",
    "INSUFFICIENT_CALIBRATION_EVIDENCE",
)
SOURCE_MEMBERS = ("manifest.json", "TAOUSDT_1d.json", "ETHUSDT_1d.json", "SOLUSDT_1d.json", "TAOUSDT_12h.json", "ETHUSDT_12h.json", "SOLUSDT_12h.json")
EVALUATION_MEMBERS = ("manifest.json", "study.json", "cases.json", "predictions.json")


def _mapping(value: Any, *, path: str) -> Mapping[str, Any]:
    return require_mapping(value, path=path)


def _string(value: Any, *, path: str) -> str:
    return require_nonempty_string(value, path=path)


def _path(value: Any, *, path: str) -> str:
    return require_safe_relative_path(value, path=path)


def _timestamp(value: Any, *, path: str) -> datetime:
    return require_utc_timestamp(value, path=path, require_daily_boundary=False)


@dataclass(frozen=True)
class FrozenDailyMember:
    asset: str
    source_id: str
    source_bundle_id: str
    bars_sha256: str
    grid_sha256: str
    row_count: int
    start: datetime
    end: datetime
    provider_calls: int

    def __post_init__(self) -> None:
        if self.asset not in ASSETS:
            raise ContractValidationError("frozen 1d member asset is outside V2.3 scope")
        for name in ("source_id", "source_bundle_id", "bars_sha256", "grid_sha256"):
            object.__setattr__(self, name, require_sha256(getattr(self, name), path=f"sources.frozen_1d.members.{self.asset}.{name}"))
        object.__setattr__(self, "row_count", require_integer(self.row_count, path=f"sources.frozen_1d.members.{self.asset}.row_count", minimum=1))
        start = _timestamp(self.start, path=f"sources.frozen_1d.members.{self.asset}.start")
        end = _timestamp(self.end, path=f"sources.frozen_1d.members.{self.asset}.end")
        if (start, end, self.row_count) != (FROZEN_1D_START, FROZEN_1D_END, FROZEN_1D_ROWS):
            raise ContractValidationError("frozen 1d member window is not the approved V1.7 window")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "provider_calls", require_integer(self.provider_calls, path=f"sources.frozen_1d.members.{self.asset}.provider_calls"))
        if self.provider_calls != 0:
            raise ContractValidationError("V2.3 frozen 1d members must have zero V2.3 provider calls")

    def to_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "source_id": self.source_id,
            "source_bundle_id": self.source_bundle_id,
            "bars_sha256": self.bars_sha256,
            "grid_sha256": self.grid_sha256,
            "row_count": self.row_count,
            "start": utc_isoformat(self.start),
            "end": utc_isoformat(self.end),
            "provider_calls": self.provider_calls,
        }


@dataclass(frozen=True)
class FrozenDailyProtocol:
    bundle_path: str
    outer_bundle_id: str
    implementation_commit: str
    venue: str
    timeframe: str
    grid_policy: str
    members: tuple[FrozenDailyMember, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_path", _path(self.bundle_path, path="sources.frozen_1d.bundle_path"))
        object.__setattr__(self, "outer_bundle_id", require_sha256(self.outer_bundle_id, path="sources.frozen_1d.outer_bundle_id"))
        object.__setattr__(self, "implementation_commit", require_git_commit(self.implementation_commit, path="sources.frozen_1d.implementation_commit"))
        object.__setattr__(self, "venue", _string(self.venue, path="sources.frozen_1d.venue"))
        object.__setattr__(self, "timeframe", _string(self.timeframe, path="sources.frozen_1d.timeframe"))
        object.__setattr__(self, "grid_policy", _string(self.grid_policy, path="sources.frozen_1d.grid_policy"))
        if (self.bundle_path, self.outer_bundle_id, self.implementation_commit, self.venue, self.timeframe, self.grid_policy) != (
            FROZEN_1D_OUTER_BUNDLE_PATH,
            FROZEN_1D_OUTER_BUNDLE_ID,
            FROZEN_1D_IMPLEMENTATION_COMMIT,
            VENUE,
            "1d",
            FROZEN_1D_GRID_POLICY,
        ):
            raise ContractValidationError("frozen 1d source protocol is not approved")
        if type(self.members) is not tuple or tuple(item.asset for item in self.members) != ASSETS:
            raise ContractValidationError("frozen 1d members must use TAO/ETH/SOL order")

    def to_payload(self) -> dict[str, Any]:
        return {
            "bundle_path": self.bundle_path,
            "outer_bundle_id": self.outer_bundle_id,
            "implementation_commit": self.implementation_commit,
            "venue": self.venue,
            "timeframe": self.timeframe,
            "grid_policy": self.grid_policy,
            "members": [item.to_payload() for item in self.members],
        }


@dataclass(frozen=True)
class Provider12hProtocol:
    adapter: str
    venue: str
    timeframe: str
    start: datetime
    end: datetime
    expected_rows: int
    open_time_spacing_hours: int
    request_since_inclusive: bool
    request_until_exclusive: bool
    adapter_limit: int
    max_calls_per_asset: int

    def __post_init__(self) -> None:
        values = (
            _string(self.adapter, path="sources.provider_12h.adapter"),
            _string(self.venue, path="sources.provider_12h.venue"),
            _string(self.timeframe, path="sources.provider_12h.timeframe"),
        )
        object.__setattr__(self, "adapter", values[0])
        object.__setattr__(self, "venue", values[1])
        object.__setattr__(self, "timeframe", values[2])
        start = _timestamp(self.start, path="sources.provider_12h.start")
        end = _timestamp(self.end, path="sources.provider_12h.end")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        for name in ("expected_rows", "open_time_spacing_hours", "adapter_limit", "max_calls_per_asset"):
            object.__setattr__(self, name, require_integer(getattr(self, name), path=f"sources.provider_12h.{name}", minimum=1))
        if (
            self.adapter,
            self.venue,
            self.timeframe,
            self.start,
            self.end,
            self.expected_rows,
            self.open_time_spacing_hours,
            self.request_since_inclusive,
            self.request_until_exclusive,
            self.adapter_limit,
            self.max_calls_per_asset,
        ) != (
            PROVIDER_ADAPTER,
            VENUE,
            "12h",
            PROVIDER_12H_START,
            PROVIDER_12H_END,
            PROVIDER_12H_ROWS,
            12,
            True,
            True,
            PROVIDER_LIMIT,
            PROVIDER_CALLS_PER_ASSET,
        ):
            raise ContractValidationError("12h provider protocol is not approved")

    def to_payload(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "venue": self.venue,
            "timeframe": self.timeframe,
            "start": utc_isoformat(self.start),
            "end": utc_isoformat(self.end),
            "expected_rows": self.expected_rows,
            "open_time_spacing_hours": self.open_time_spacing_hours,
            "request_since_inclusive": self.request_since_inclusive,
            "request_until_exclusive": self.request_until_exclusive,
            "adapter_limit": self.adapter_limit,
            "max_calls_per_asset": self.max_calls_per_asset,
        }


@dataclass(frozen=True)
class FrozenSection:
    name: str
    payload: dict[str, Any]
    expected: dict[str, Any]

    def __post_init__(self) -> None:
        if type(self.payload) is not dict or self.payload != self.expected:
            raise ContractValidationError(f"{self.name} is not the approved immutable V2.3 payload")

    def to_payload(self) -> dict[str, Any]:
        return dict(self.payload)


@dataclass(frozen=True)
class ArtifactProtocol:
    output_root: str
    source_members: tuple[str, ...]
    evaluation_members: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_root", _path(self.output_root, path="artifact.output_root"))
        if self.source_members != SOURCE_MEMBERS or self.evaluation_members != EVALUATION_MEMBERS:
            raise ContractValidationError("artifact members are not the exact V2.3 protocol")

    def to_payload(self) -> dict[str, Any]:
        return {"output_root": self.output_root, "source_members": list(self.source_members), "evaluation_members": list(self.evaluation_members)}


@dataclass(frozen=True)
class AdaptiveContextCalibrationConfig:
    version: str
    trial_name: str
    venue: str
    assets: tuple[str, ...]
    timeframes: tuple[str, ...]
    frozen_1d: FrozenDailyProtocol
    provider_12h: Provider12hProtocol
    atr: FrozenSection
    normalization: FrozenSection
    calibration: FrozenSection
    outcome: FrozenSection
    folds: tuple[CohortFold, ...]
    bootstrap: FrozenSection
    dispositions: tuple[str, ...]
    artifact: ArtifactProtocol
    config_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.version != CONFIG_VERSION or self.trial_name != TRIAL_NAME or self.venue != VENUE or self.assets != ASSETS or self.timeframes != TIMEFRAMES:
            raise ContractValidationError("trial scope is outside the approved V2.3 study")
        if any(type(item) is not FrozenSection for item in (self.atr, self.normalization, self.calibration, self.outcome, self.bootstrap)):
            raise ContractValidationError("V2.3 protocol sections have invalid types")
        if self.atr.name != "atr" or self.atr.expected != ATR_PAYLOAD:
            raise ContractValidationError("ATR protocol is not approved")
        if self.normalization.name != "normalization" or self.normalization.expected != {"history_days": NORMALIZATION_DAYS, "buckets": list(BUCKETS), "rank": "deterministic_midrank"}:
            raise ContractValidationError("normalization protocol is not approved")
        if self.calibration.name != "calibration" or self.calibration.expected != CALIBRATION_PAYLOAD:
            raise ContractValidationError("calibration protocol is not approved")
        if self.outcome.name != "outcome" or self.outcome.expected != OUTCOME_PAYLOAD:
            raise ContractValidationError("outcome protocol is not approved")
        if self.bootstrap.name != "bootstrap" or self.bootstrap.expected != BOOTSTRAP_PAYLOAD:
            raise ContractValidationError("bootstrap protocol is not approved")
        if type(self.folds) is not tuple or tuple((fold.name, fold.start, fold.end) for fold in self.folds) != FOLD_BOUNDS:
            raise ContractValidationError("folds are not the exact V2.3 development folds")
        if self.dispositions != DISPOSITIONS:
            raise ContractValidationError("dispositions are not the exact V2.3 set")
        if type(self.artifact) is not ArtifactProtocol:
            raise ContractValidationError("artifact protocol has invalid type")
        object.__setattr__(self, "config_hash", deterministic_hash(self.to_payload()))

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "trial": {"trial_name": self.trial_name, "venue": self.venue, "assets": list(self.assets), "timeframes": list(self.timeframes)},
            "sources": {"frozen_1d": self.frozen_1d.to_payload(), "provider_12h": self.provider_12h.to_payload()},
            "atr": self.atr.to_payload(),
            "normalization": self.normalization.to_payload(),
            "calibration": self.calibration.to_payload(),
            "outcome": self.outcome.to_payload(),
            "folds": [fold.to_payload() for fold in self.folds],
            "bootstrap": self.bootstrap.to_payload(),
            "dispositions": list(self.dispositions),
            "artifact": self.artifact.to_payload(),
        }


def _parse_folds(raw: Any) -> tuple[CohortFold, ...]:
    if type(raw) is not list:
        raise ContractValidationError("folds must be a list")
    result = []
    for index, item in enumerate(raw):
        mapping = _mapping(item, path=f"folds[{index}]")
        require_exact_keys(mapping, {"name", "start", "end"}, path=f"folds[{index}]")
        result.append(CohortFold(_string(mapping["name"], path=f"folds[{index}].name"), _timestamp(mapping["start"], path=f"folds[{index}].start"), _timestamp(mapping["end"], path=f"folds[{index}].end")))
    return tuple(result)


def load_adaptive_context_calibration_config(path: str) -> AdaptiveContextCalibrationConfig:
    raw = _mapping(load_strict_research_yaml(path, description="V2.3 adaptive context calibration configuration"), path="config")
    require_exact_keys(raw, {"version", "trial", "sources", "atr", "normalization", "calibration", "outcome", "folds", "bootstrap", "dispositions", "artifact"}, path="config")
    trial = _mapping(raw["trial"], path="trial")
    require_exact_keys(trial, {"trial_name", "venue", "assets", "timeframes"}, path="trial")
    sources = _mapping(raw["sources"], path="sources")
    require_exact_keys(sources, {"frozen_1d", "provider_12h"}, path="sources")
    frozen = _mapping(sources["frozen_1d"], path="sources.frozen_1d")
    require_exact_keys(frozen, {"bundle_path", "outer_bundle_id", "implementation_commit", "venue", "timeframe", "grid_policy", "members"}, path="sources.frozen_1d")
    members = frozen["members"]
    if type(members) is not list:
        raise ContractValidationError("sources.frozen_1d.members must be a list")
    frozen_members = []
    for index, item in enumerate(members):
        mapping = _mapping(item, path=f"sources.frozen_1d.members[{index}]")
        require_exact_keys(mapping, {"asset", "source_id", "source_bundle_id", "bars_sha256", "grid_sha256", "row_count", "start", "end", "provider_calls"}, path=f"sources.frozen_1d.members[{index}]")
        frozen_members.append(FrozenDailyMember(asset=_string(mapping["asset"], path=f"sources.frozen_1d.members[{index}].asset"), source_id=mapping["source_id"], source_bundle_id=mapping["source_bundle_id"], bars_sha256=mapping["bars_sha256"], grid_sha256=mapping["grid_sha256"], row_count=mapping["row_count"], start=mapping["start"], end=mapping["end"], provider_calls=mapping["provider_calls"]))
    provider = _mapping(sources["provider_12h"], path="sources.provider_12h")
    require_exact_keys(provider, {"adapter", "venue", "timeframe", "start", "end", "expected_rows", "open_time_spacing_hours", "request_since_inclusive", "request_until_exclusive", "adapter_limit", "max_calls_per_asset"}, path="sources.provider_12h")
    section_values = {}
    for name, expected_keys in (("atr", set(ATR_PAYLOAD)), ("normalization", {"history_days", "buckets", "rank"}), ("calibration", set(CALIBRATION_PAYLOAD)), ("outcome", set(OUTCOME_PAYLOAD)), ("bootstrap", set(BOOTSTRAP_PAYLOAD))):
        mapping = dict(_mapping(raw[name], path=name))
        require_exact_keys(mapping, expected_keys, path=name)
        section_values[name] = mapping
    if type(raw["dispositions"]) is not list or type(trial["assets"]) is not list or type(trial["timeframes"]) is not list:
        raise ContractValidationError("trial assets/timeframes and dispositions must be lists")
    artifact = _mapping(raw["artifact"], path="artifact")
    require_exact_keys(artifact, {"output_root", "source_members", "evaluation_members"}, path="artifact")
    if type(artifact["source_members"]) is not list or type(artifact["evaluation_members"]) is not list:
        raise ContractValidationError("artifact member fields must be lists")
    return AdaptiveContextCalibrationConfig(
        version=_string(raw["version"], path="version"),
        trial_name=_string(trial["trial_name"], path="trial.trial_name"),
        venue=_string(trial["venue"], path="trial.venue"),
        assets=tuple(_string(value, path=f"trial.assets[{index}]") for index, value in enumerate(trial["assets"])),
        timeframes=tuple(_string(value, path=f"trial.timeframes[{index}]") for index, value in enumerate(trial["timeframes"])),
        frozen_1d=FrozenDailyProtocol(bundle_path=frozen["bundle_path"], outer_bundle_id=frozen["outer_bundle_id"], implementation_commit=frozen["implementation_commit"], venue=frozen["venue"], timeframe=frozen["timeframe"], grid_policy=frozen["grid_policy"], members=tuple(frozen_members)),
        provider_12h=Provider12hProtocol(**dict(provider)),
        atr=FrozenSection("atr", section_values["atr"], ATR_PAYLOAD),
        normalization=FrozenSection("normalization", section_values["normalization"], {"history_days": NORMALIZATION_DAYS, "buckets": list(BUCKETS), "rank": "deterministic_midrank"}),
        calibration=FrozenSection("calibration", section_values["calibration"], CALIBRATION_PAYLOAD),
        outcome=FrozenSection("outcome", section_values["outcome"], OUTCOME_PAYLOAD),
        folds=_parse_folds(raw["folds"]),
        bootstrap=FrozenSection("bootstrap", section_values["bootstrap"], BOOTSTRAP_PAYLOAD),
        dispositions=tuple(_string(value, path=f"dispositions[{index}]") for index, value in enumerate(raw["dispositions"])),
        artifact=ArtifactProtocol(output_root=artifact["output_root"], source_members=tuple(_string(value, path=f"artifact.source_members[{index}]") for index, value in enumerate(artifact["source_members"])), evaluation_members=tuple(_string(value, path=f"artifact.evaluation_members[{index}]") for index, value in enumerate(artifact["evaluation_members"]))),
    )


__all__ = [
    "AdaptiveContextCalibrationConfig",
    "ArtifactProtocol",
    "BUCKETS",
    "CALIBRATION_PAYLOAD",
    "CANONICAL_COHORTS",
    "FROZEN_1D_MEMBERS",
    "FrozenDailyMember",
    "FrozenDailyProtocol",
    "FrozenSection",
    "OUTCOME_PAYLOAD",
    "Provider12hProtocol",
    "load_adaptive_context_calibration_config",
]
