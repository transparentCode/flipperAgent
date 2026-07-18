"""Strict frozen configuration for the SR-V2.0 displacement-origin study."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from libs.models.sr.detection.displacement_origin import DisplacementOriginConfig
from libs.models.sr.domain import ContractValidationError, ZoneSide
from libs.models.sr.domain.identity import deterministic_hash, utc_isoformat
from libs.models.sr.research.config import (
    require_exact_keys,
    require_finite_number,
    require_git_commit,
    require_integer,
    require_mapping,
    require_nonempty_string,
    require_safe_relative_path,
    require_sha256,
    require_utc_timestamp,
)
from libs.models.sr.research.config.strict_yaml import load_strict_research_yaml
from libs.models.sr.research.windows.folds import CohortFold


CONFIG_VERSION = "1"
TRIAL_NAME = "sr-v2.0-taousdt-1d-displacement-origin-adequacy"
VENUE = "binance_usdm"
ASSET = "TAOUSDT"
TIMEFRAME = "1d"
SOURCE_BUNDLE_ID = "6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9"
SOURCE_IMPLEMENTATION_COMMIT = "be6459a8e06ec95b634b2cfb2b91a08cd31d9ba2"
SOURCE_ID = "fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120"
SOURCE_CAPSULE_BUNDLE_ID = "d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925"
SOURCE_BARS_SHA256 = "703367048f4ed7dc432ca9dfe0ad4afdc5a56eb2a508597ef00bdc3de8b81163"
SOURCE_GRID_SHA256 = "d1f60173bc59a1301d08c8521b9f78fa0831daad3fd8b58edae392237d1e54e8"
SOURCE_ROWS = 629
SOURCE_START = datetime(2024, 4, 11, tzinfo=timezone.utc)
SOURCE_END = datetime(2025, 12, 31, tzinfo=timezone.utc)
SOURCE_GRID_POLICY = "exact_utc_daily_grid_from_taousdt_development_capsule"
ATR_METHOD = "wilder_rma"
ATR_PERIOD = 14
ATR_SEED = "sma"
COMMON_START_INDEX = 28
OUTCOME_OFFSET = 1
TOUCH_SEARCH_BARS = 50
OUTCOME_HORIZON = 10
WINDOW_POLICY = "half_open_utc_daily"
CONTROL_SIDE_ORDER = (ZoneSide.SUPPORT, ZoneSide.RESISTANCE)
CONTROLS_PER_REAL_CANDIDATE = 2
STAGE = "displacement_origin_adequacy_development"
ARTIFACT_MEMBERS = ("manifest.json", "study.json", "cases.json")
FOLD_BOUNDS = (
    ("2024_q3", datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2024, 10, 1, tzinfo=timezone.utc)),
    ("2024_q4", datetime(2024, 10, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
    ("2025_q1", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 4, 1, tzinfo=timezone.utc)),
    ("2025_q2", datetime(2025, 4, 1, tzinfo=timezone.utc), datetime(2025, 7, 1, tzinfo=timezone.utc)),
    ("2025_q3", datetime(2025, 7, 1, tzinfo=timezone.utc), datetime(2025, 10, 1, tzinfo=timezone.utc)),
    ("2025_q4", datetime(2025, 10, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
)
APPROVED_DETECTOR = {
    "displacement_atr": 1.0,
    "minimum_body_fraction": 0.60,
    "structure_lookback_bars": 5,
    "base_search_bars": 3,
}
APPROVED_GATES = {
    "minimum_completed_pairs": 24,
    "minimum_comparable_folds": 4,
    "minimum_pairs_per_comparable_fold": 4,
    "minimum_completed_naive_controls_per_side_per_comparable_fold": 4,
    "minimum_pooled_median_excess_quality_atr": 0.10,
    "minimum_positive_comparable_fold_fraction": 0.60,
    "minimum_worst_comparable_fold_excess_atr": -0.10,
}
DISPOSITION_VALUES = (
    "DISPLACEMENT_ORIGIN_BEATS_NAIVE_NULL",
    "DISPLACEMENT_ORIGIN_NOT_BETTER_THAN_NAIVE_NULL",
    "INSUFFICIENT_EVIDENCE",
)


def _mapping(value: Any, *, path: str) -> Mapping[str, Any]:
    return require_mapping(value, path=path)


def _exact(value: Mapping[str, Any], expected: set[str], *, path: str) -> None:
    require_exact_keys(value, expected, path=path)


def _string(value: Any, *, path: str) -> str:
    return require_nonempty_string(value, path=path)


def _path(value: Any, *, path: str) -> str:
    return require_safe_relative_path(value, path=path)


def _timestamp(value: Any, *, path: str) -> datetime:
    return require_utc_timestamp(value, path=path, require_daily_boundary=True)


@dataclass(frozen=True)
class FrozenSource:
    bundle_path: str
    bundle_id: str
    implementation_commit: str
    source_id: str
    source_bundle_id: str
    bars_sha256: str
    grid_sha256: str
    row_count: int
    start: datetime
    end: datetime
    grid_policy: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_path", _path(self.bundle_path, path="source.bundle_path"))
        for name in ("bundle_id", "source_id", "source_bundle_id", "bars_sha256", "grid_sha256"):
            object.__setattr__(self, name, require_sha256(getattr(self, name), path=f"source.{name}"))
        object.__setattr__(self, "implementation_commit", require_git_commit(self.implementation_commit, path="source.implementation_commit"))
        object.__setattr__(self, "row_count", require_integer(self.row_count, path="source.row_count", minimum=1))
        object.__setattr__(self, "start", _require_datetime(self.start, path="source.start"))
        object.__setattr__(self, "end", _require_datetime(self.end, path="source.end"))
        object.__setattr__(self, "grid_policy", _string(self.grid_policy, path="source.grid_policy"))
        if self.to_payload() != {
            "bundle_path": "research/tmp_sr_v1_7/source/6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9",
            "bundle_id": SOURCE_BUNDLE_ID,
            "implementation_commit": SOURCE_IMPLEMENTATION_COMMIT,
            "source_id": SOURCE_ID,
            "source_bundle_id": SOURCE_CAPSULE_BUNDLE_ID,
            "bars_sha256": SOURCE_BARS_SHA256,
            "grid_sha256": SOURCE_GRID_SHA256,
            "row_count": SOURCE_ROWS,
            "start": utc_isoformat(SOURCE_START),
            "end": utc_isoformat(SOURCE_END),
            "grid_policy": SOURCE_GRID_POLICY,
        }:
            raise ContractValidationError("source is not the approved frozen TAOUSDT development identity")

    def to_payload(self) -> dict[str, object]:
        return {
            "bundle_path": self.bundle_path,
            "bundle_id": self.bundle_id,
            "implementation_commit": self.implementation_commit,
            "source_id": self.source_id,
            "source_bundle_id": self.source_bundle_id,
            "bars_sha256": self.bars_sha256,
            "grid_sha256": self.grid_sha256,
            "row_count": self.row_count,
            "start": utc_isoformat(self.start),
            "end": utc_isoformat(self.end),
            "grid_policy": self.grid_policy,
        }


@dataclass(frozen=True)
class AtrProtocol:
    method: str
    period: int
    seed: str
    common_start_index: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "method", _string(self.method, path="atr.method"))
        object.__setattr__(self, "period", require_integer(self.period, path="atr.period", minimum=1))
        object.__setattr__(self, "seed", _string(self.seed, path="atr.seed"))
        object.__setattr__(self, "common_start_index", require_integer(self.common_start_index, path="atr.common_start_index", minimum=1))
        if self.to_payload() != {"method": ATR_METHOD, "period": ATR_PERIOD, "seed": ATR_SEED, "common_start_index": COMMON_START_INDEX}:
            raise ContractValidationError("ATR protocol is not frozen Wilder ATR(14)/common-start 28")

    def to_payload(self) -> dict[str, object]:
        return {"method": self.method, "period": self.period, "seed": self.seed, "common_start_index": self.common_start_index}


@dataclass(frozen=True)
class OutcomeProtocol:
    first_touch_offset_bars: int
    touch_search_bars: int
    horizon_bars: int
    window_policy: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "first_touch_offset_bars", require_integer(self.first_touch_offset_bars, path="outcome.first_touch_offset_bars", minimum=1))
        object.__setattr__(self, "touch_search_bars", require_integer(self.touch_search_bars, path="outcome.touch_search_bars", minimum=1))
        object.__setattr__(self, "horizon_bars", require_integer(self.horizon_bars, path="outcome.horizon_bars", minimum=1))
        object.__setattr__(self, "window_policy", _string(self.window_policy, path="outcome.window_policy"))
        if self.to_payload() != {"first_touch_offset_bars": OUTCOME_OFFSET, "touch_search_bars": TOUCH_SEARCH_BARS, "horizon_bars": OUTCOME_HORIZON, "window_policy": WINDOW_POLICY}:
            raise ContractValidationError("outcome protocol is not the approved V2.0 payload")

    def to_payload(self) -> dict[str, object]:
        return {"first_touch_offset_bars": self.first_touch_offset_bars, "touch_search_bars": self.touch_search_bars, "horizon_bars": self.horizon_bars, "window_policy": self.window_policy}


@dataclass(frozen=True)
class AdequacyGates:
    minimum_completed_pairs: int
    minimum_comparable_folds: int
    minimum_pairs_per_comparable_fold: int
    minimum_completed_naive_controls_per_side_per_comparable_fold: int
    minimum_pooled_median_excess_quality_atr: float
    minimum_positive_comparable_fold_fraction: float
    minimum_worst_comparable_fold_excess_atr: float

    def __post_init__(self) -> None:
        for name in (
            "minimum_completed_pairs",
            "minimum_comparable_folds",
            "minimum_pairs_per_comparable_fold",
            "minimum_completed_naive_controls_per_side_per_comparable_fold",
        ):
            object.__setattr__(self, name, require_integer(getattr(self, name), path=f"gates.{name}", minimum=1))
        for name in (
            "minimum_pooled_median_excess_quality_atr",
            "minimum_positive_comparable_fold_fraction",
            "minimum_worst_comparable_fold_excess_atr",
        ):
            object.__setattr__(self, name, require_finite_number(getattr(self, name), path=f"gates.{name}"))
        if not 0.0 <= self.minimum_positive_comparable_fold_fraction <= 1.0:
            raise ContractValidationError("gates.minimum_positive_comparable_fold_fraction must be in [0, 1]")
        if self.to_payload() != APPROVED_GATES:
            raise ContractValidationError("adequacy gates are not the approved immutable V2.0 payload")

    def to_payload(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class ArtifactProtocol:
    output_root: str
    stage: str
    members: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_root", _path(self.output_root, path="artifact.output_root"))
        object.__setattr__(self, "stage", _string(self.stage, path="artifact.stage"))
        if type(self.members) is not tuple or any(type(item) is not str for item in self.members):
            raise ContractValidationError("artifact.members must be a tuple of strings")
        if self.stage != STAGE or self.members != ARTIFACT_MEMBERS:
            raise ContractValidationError("artifact protocol must use the exact V2.0 stage and members")

    def to_payload(self) -> dict[str, object]:
        return {"output_root": self.output_root, "stage": self.stage, "members": list(self.members)}


def _require_datetime(value: object, *, path: str) -> datetime:
    if type(value) is not datetime:
        raise ContractValidationError(f"{path} must be a UTC datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContractValidationError(f"{path} must be a UTC datetime")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise ContractValidationError(f"{path} must be UTC")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class DisplacementOriginAdequacyConfig:
    version: str
    trial_name: str
    venue: str
    asset: str
    timeframe: str
    source: FrozenSource
    atr: AtrProtocol
    detector: DisplacementOriginConfig
    outcome: OutcomeProtocol
    folds: tuple[CohortFold, ...]
    controls_per_real_candidate: int
    control_side_order: tuple[ZoneSide, ...]
    gates: AdequacyGates
    dispositions: tuple[str, ...]
    artifact: ArtifactProtocol
    config_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if _string(self.version, path="version") != CONFIG_VERSION:
            raise ContractValidationError("unsupported V2.0 config version")
        if (self.trial_name, self.venue, self.asset, self.timeframe) != (TRIAL_NAME, VENUE, ASSET, TIMEFRAME):
            raise ContractValidationError("trial scope is outside the approved V2.0 TAOUSDT/1d study")
        if type(self.source) is not FrozenSource or type(self.atr) is not AtrProtocol or type(self.detector) is not DisplacementOriginConfig or type(self.outcome) is not OutcomeProtocol or type(self.gates) is not AdequacyGates or type(self.artifact) is not ArtifactProtocol:
            raise ContractValidationError("V2.0 configuration sections have invalid types")
        if self.detector.to_payload() != APPROVED_DETECTOR:
            raise ContractValidationError("detector parameters are not the approved immutable V2.0 payload")
        if type(self.folds) is not tuple or tuple((fold.name, fold.start, fold.end) for fold in self.folds) != FOLD_BOUNDS:
            raise ContractValidationError("V2.0 requires the exact six development folds")
        if type(self.controls_per_real_candidate) is not int or self.controls_per_real_candidate != CONTROLS_PER_REAL_CANDIDATE:
            raise ContractValidationError("V2.0 requires exactly two controls per in-fold real candidate")
        if type(self.control_side_order) is not tuple or self.control_side_order != CONTROL_SIDE_ORDER:
            raise ContractValidationError("V2.0 control side order is not frozen")
        if type(self.dispositions) is not tuple or self.dispositions != DISPOSITION_VALUES:
            raise ContractValidationError("V2.0 disposition set is not frozen")
        object.__setattr__(self, "config_hash", deterministic_hash(self.to_payload()))

    def to_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "trial": {"trial_name": self.trial_name, "venue": self.venue, "asset": self.asset, "timeframe": self.timeframe},
            "source": self.source.to_payload(),
            "atr": self.atr.to_payload(),
            "detector": self.detector.to_payload(),
            "outcome": self.outcome.to_payload(),
            "folds": [fold.to_payload() for fold in self.folds],
            "controls": {"per_real_candidate": self.controls_per_real_candidate, "side_order": [side.value for side in self.control_side_order]},
            "gates": self.gates.to_payload(),
            "dispositions": list(self.dispositions),
            "artifact": self.artifact.to_payload(),
        }


def _folds(raw: object) -> tuple[CohortFold, ...]:
    if type(raw) is not list:
        raise ContractValidationError("folds must be a list")
    folds: list[CohortFold] = []
    for index, item in enumerate(raw):
        mapping = _mapping(item, path=f"folds[{index}]")
        _exact(mapping, {"name", "start", "end"}, path=f"folds[{index}]")
        folds.append(CohortFold(name=_string(mapping["name"], path=f"folds[{index}].name"), start=_timestamp(mapping["start"], path=f"folds[{index}].start"), end=_timestamp(mapping["end"], path=f"folds[{index}].end")))
    return tuple(folds)


def load_displacement_origin_adequacy_config(path: str) -> DisplacementOriginAdequacyConfig:
    raw = _mapping(load_strict_research_yaml(path, description="V2.0 displacement-origin configuration"), path="config")
    _exact(raw, {"version", "trial", "source", "atr", "detector", "outcome", "folds", "controls", "gates", "dispositions", "artifact"}, path="config")
    trial = _mapping(raw["trial"], path="trial")
    _exact(trial, {"trial_name", "venue", "asset", "timeframe"}, path="trial")
    source = _mapping(raw["source"], path="source")
    _exact(source, {"bundle_path", "bundle_id", "implementation_commit", "source_id", "source_bundle_id", "bars_sha256", "grid_sha256", "row_count", "start", "end", "grid_policy"}, path="source")
    atr = _mapping(raw["atr"], path="atr")
    _exact(atr, {"method", "period", "seed", "common_start_index"}, path="atr")
    detector = _mapping(raw["detector"], path="detector")
    _exact(detector, set(APPROVED_DETECTOR), path="detector")
    outcome = _mapping(raw["outcome"], path="outcome")
    _exact(outcome, {"first_touch_offset_bars", "touch_search_bars", "horizon_bars", "window_policy"}, path="outcome")
    controls = _mapping(raw["controls"], path="controls")
    _exact(controls, {"per_real_candidate", "side_order"}, path="controls")
    if type(controls["side_order"]) is not list:
        raise ContractValidationError("controls.side_order must be a list")
    try:
        control_sides = tuple(ZoneSide(item) for item in controls["side_order"])
    except (TypeError, ValueError) as exc:
        raise ContractValidationError("controls.side_order contains an invalid zone side") from exc
    gates = _mapping(raw["gates"], path="gates")
    _exact(gates, set(APPROVED_GATES), path="gates")
    artifact = _mapping(raw["artifact"], path="artifact")
    _exact(artifact, {"output_root", "stage", "members"}, path="artifact")
    if type(artifact["members"]) is not list:
        raise ContractValidationError("artifact.members must be a list")
    if type(raw["dispositions"]) is not list:
        raise ContractValidationError("dispositions must be a list")
    return DisplacementOriginAdequacyConfig(
        version=_string(raw["version"], path="version"),
        trial_name=_string(trial["trial_name"], path="trial.trial_name"),
        venue=_string(trial["venue"], path="trial.venue"),
        asset=_string(trial["asset"], path="trial.asset"),
        timeframe=_string(trial["timeframe"], path="trial.timeframe"),
        source=FrozenSource(
            bundle_path=_path(source["bundle_path"], path="source.bundle_path"),
            bundle_id=require_sha256(source["bundle_id"], path="source.bundle_id"),
            implementation_commit=require_git_commit(source["implementation_commit"], path="source.implementation_commit"),
            source_id=require_sha256(source["source_id"], path="source.source_id"),
            source_bundle_id=require_sha256(source["source_bundle_id"], path="source.source_bundle_id"),
            bars_sha256=require_sha256(source["bars_sha256"], path="source.bars_sha256"),
            grid_sha256=require_sha256(source["grid_sha256"], path="source.grid_sha256"),
            row_count=require_integer(source["row_count"], path="source.row_count", minimum=1),
            start=_timestamp(source["start"], path="source.start"),
            end=_timestamp(source["end"], path="source.end"),
            grid_policy=_string(source["grid_policy"], path="source.grid_policy"),
        ),
        atr=AtrProtocol(
            method=_string(atr["method"], path="atr.method"),
            period=require_integer(atr["period"], path="atr.period", minimum=1),
            seed=_string(atr["seed"], path="atr.seed"),
            common_start_index=require_integer(atr["common_start_index"], path="atr.common_start_index", minimum=1),
        ),
        detector=DisplacementOriginConfig(
            displacement_atr=require_finite_number(detector["displacement_atr"], path="detector.displacement_atr", minimum=0.0),
            minimum_body_fraction=require_finite_number(detector["minimum_body_fraction"], path="detector.minimum_body_fraction", minimum=0.0, maximum=1.0),
            structure_lookback_bars=require_integer(detector["structure_lookback_bars"], path="detector.structure_lookback_bars", minimum=1),
            base_search_bars=require_integer(detector["base_search_bars"], path="detector.base_search_bars", minimum=1),
        ),
        outcome=OutcomeProtocol(
            first_touch_offset_bars=require_integer(outcome["first_touch_offset_bars"], path="outcome.first_touch_offset_bars", minimum=1),
            touch_search_bars=require_integer(outcome["touch_search_bars"], path="outcome.touch_search_bars", minimum=1),
            horizon_bars=require_integer(outcome["horizon_bars"], path="outcome.horizon_bars", minimum=1),
            window_policy=_string(outcome["window_policy"], path="outcome.window_policy"),
        ),
        folds=_folds(raw["folds"]),
        controls_per_real_candidate=require_integer(controls["per_real_candidate"], path="controls.per_real_candidate", minimum=1),
        control_side_order=control_sides,
        gates=AdequacyGates(**{name: gates[name] for name in APPROVED_GATES}),
        dispositions=tuple(_string(item, path=f"dispositions[{index}]") for index, item in enumerate(raw["dispositions"])),
        artifact=ArtifactProtocol(
            output_root=_path(artifact["output_root"], path="artifact.output_root"),
            stage=_string(artifact["stage"], path="artifact.stage"),
            members=tuple(_string(item, path=f"artifact.members[{index}]") for index, item in enumerate(artifact["members"])),
        ),
    )


__all__ = [
    "AdequacyGates",
    "ArtifactProtocol",
    "AtrProtocol",
    "DisplacementOriginAdequacyConfig",
    "FrozenSource",
    "OutcomeProtocol",
    "load_displacement_origin_adequacy_config",
]
