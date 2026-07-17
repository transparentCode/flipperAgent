"""Fail-closed configuration for the SR-V1.12 reinforcement audit."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash, require_utc, utc_isoformat
from libs.models.sr.research.config.primitives import (
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


CONFIG_VERSION = "1"
SCHEMA_VERSION = "1.0"
TRIAL_NAME = "sr-v1.12-taousdt-1d-candidate-reinforcement-audit"
APPROVED_VENUE = "binance_usdm"
APPROVED_ASSET = "TAOUSDT"
APPROVED_TIMEFRAME = "1d"
APPROVED_STAGE = "candidate_reinforcement_audit_development"

V11_CONFIG_PATH = "configs/sr_trials/sr_v1_11_taousdt_1d_lifecycle_utility.yaml"
V11_CONFIG_HASH = "ba2bde0651902e18cf3f9e4835ea087a1d7c0280dd6bc929683c6769b92d8b59"
V11_BUNDLE_PATH = "research/tmp_sr_v1_11/lifecycle_utility/evaluation/d771135ca9caded7cfaff578501836c541f279d51280175588de6545aff2d3eb"
V11_BUNDLE_ID = "d771135ca9caded7cfaff578501836c541f279d51280175588de6545aff2d3eb"
V11_STUDY_ID = "8d6770dbba05963db93ebe1271e63a37ba369d2d4e8f5a05f6149fbf85f147b9"
V11_IMPLEMENTATION_COMMIT = "4d525ef3e50933330af0fd89c4082d550a538eee"
V11_MANIFEST_SHA256 = "0709340ce6d647b777604a6e4f4b5aa54f60c606de85c18faee3dd806a4a117a"
V11_MANIFEST_BYTES = 9830
V11_STUDY_SHA256 = "429ca0665a5b26808ff29bc988e47f46ce53777a9e343cc64761d23bc8e8be00"
V11_STUDY_BYTES = 81750

V19_CONFIG_PATH = "configs/sr_trials/sr_v1_9_taousdt_1d_baseline_adequacy.yaml"
V19_CONFIG_HASH = "ae8b290674f8c9feb3ce630910753f44dcff87a64795428f614735b0cc2dc9a9"
V19_BUNDLE_PATH = "research/tmp_sr_v1_9/evaluation/12af91cecc3582606da7c41c0c1beaf0320aa17eef8c52edf615214cf0a34df6"
V19_BUNDLE_ID = "12af91cecc3582606da7c41c0c1beaf0320aa17eef8c52edf615214cf0a34df6"
V19_STUDY_ID = "ed19698fec505e2e8cf1057c41336da7c0720bcf412530244139e5c523f12c9f"
V19_IMPLEMENTATION_COMMIT = "542faeb0991617ec38a3f7cc13551a26c0f567f0"
V19_DISPOSITION = "BASELINE_NOT_BETTER_THAN_NAIVE_NULL"
V19_MANIFEST_SHA256 = "5e0942b7c47d1cb31aae93a1b676abf1eafb46592453ccb357801fa59ad1c9d3"
V19_MANIFEST_BYTES = 10528
V19_STUDY_SHA256 = "fe80a2933b7f0ef266bbc43756e9a043515f153d6af64b50660ebe832b9c8abf"
V19_STUDY_BYTES = 857146

V10_CONFIG_PATH = "configs/sr_trials/sr_v1_10_taousdt_1d_context_audit.yaml"
V10_CONFIG_HASH = "1ae6cdf31951e20540a9625a85e593e9bfbb9520364b68d6e783f05ab477207f"
V10_BUNDLE_PATH = "research/tmp_sr_v1_10/audit/a592276b9fed7c24949ad33b503a7b65474e10f4e3088fe734282401ac058a56"
V10_BUNDLE_ID = "a592276b9fed7c24949ad33b503a7b65474e10f4e3088fe734282401ac058a56"
V10_AUDIT_ID = "147df6b76fea1a2d8cf5f77840f4e82af6e7d7e8207410e2c43249442ea81c07"
V10_IMPLEMENTATION_COMMIT = "e52e96eb779ccc9ada0b4bef6b1082177091ebc8"
V10_MANIFEST_SHA256 = "482dc10c3a5eaa1142b1b8b7967eea39464f9975ceef14b3aaddb04c66588baf"
V10_MANIFEST_BYTES = 9854
V10_AUDIT_SHA256 = "27afe6242cc68e0222c7f93ef212b9ad87faaaf53c1b21e6edcbc5a8e2eaceb1"
V10_AUDIT_BYTES = 266791
V10_CHART_SHA256 = "621df3d8cbd6191567c00b31bed54848acf4a91d0f1f920d7fc1ea2f70cf0714"
V10_CHART_BYTES = 605404

SOURCE_BUNDLE_ID = "d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925"
UPSTREAM_SOURCE_BUNDLE_ID = "6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9"
SOURCE_ID = "fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120"
BARS_SHA256 = "703367048f4ed7dc432ca9dfe0ad4afdc5a56eb2a508597ef00bdc3de8b81163"
SOURCE_ROWS = 629
SOURCE_START = datetime(2024, 4, 11, tzinfo=timezone.utc)
SOURCE_END = datetime(2025, 12, 31, tzinfo=timezone.utc)
SOURCE_GRID_POLICY = "exact_utc_daily_grid_from_taousdt_development_capsule"
SR_CONFIG_HASH = "cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299"
INPUT_CONFIG_HASH = "5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d"
SR_CONFIG_PATH = "configs/sr.yaml"
INPUT_CONFIG_PATH = "configs/sr_inputs.yaml"

PIVOT_SPAN_BARS = 5
ZONE_HALF_WIDTH_ATR = 0.25
MERGE_DISTANCE_ATR = 0.50
TOUCH_TOLERANCE_ATR = 0.25
BREAK_BUFFER_ATR = 0.25
BREAK_CONFIRM_CLOSES = 2
MAX_AGE_BARS = 50
MAX_ACTIVE_ZONES = 8
ATR_METHOD = "wilder_rma"
ATR_PERIOD = 14
ATR_SEED = "sma"
COMMON_START_INDEX = 28

FOLD_NAMES = ("2024_q3", "2024_q4", "2025_q1", "2025_q2", "2025_q3", "2025_q4")
FOLD_BOUNDS = (
    (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2024, 10, 1, tzinfo=timezone.utc)),
    (datetime(2024, 10, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
    (datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 4, 1, tzinfo=timezone.utc)),
    (datetime(2025, 4, 1, tzinfo=timezone.utc), datetime(2025, 7, 1, tzinfo=timezone.utc)),
    (datetime(2025, 7, 1, tzinfo=timezone.utc), datetime(2025, 10, 1, tzinfo=timezone.utc)),
    (datetime(2025, 10, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
)
DECISION_CATEGORIES = (
    "CREATED_ZONE",
    "MATCHED_START_ZONE_SUPPRESSED",
    "MATCHED_SAME_BATCH_ZONE_SUPPRESSED",
    "CAPACITY_SUPPRESSED",
)
READINESS_THRESHOLDS = {
    "unique_reinforced_zones": 16,
    "comparable_folds": 4,
    "minimum_reinforced_zones_per_comparable_fold": 2,
}

def _mapping(value: Any, *, path: str) -> Mapping[str, Any]:
    return require_mapping(value, path=path)


def _exact(value: Mapping[str, Any], expected: set[str], *, path: str) -> None:
    require_exact_keys(value, expected, path=path)


def _string(value: Any, *, path: str) -> str:
    return require_nonempty_string(value, path=path)


def _hash(value: Any, *, path: str) -> str:
    return require_sha256(value, path=path)


def _commit(value: Any, *, path: str) -> str:
    return require_git_commit(value, path=path)


def _integer(value: Any, *, path: str, minimum: int = 0) -> int:
    return require_integer(value, path=path, minimum=minimum)


def _number(value: Any, *, path: str, minimum: float | None = None) -> float:
    return require_finite_number(value, path=path, minimum=minimum)


def _utc(value: Any, *, path: str) -> datetime:
    return require_utc_timestamp(value, path=path, require_daily_boundary=True)


def _path(value: Any, *, path: str) -> str:
    return require_safe_relative_path(value, path=path)


@dataclass(frozen=True)
class FoldSpec:
    name: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        name = _string(self.name, path="fold.name")
        start = self.start if isinstance(self.start, datetime) else _utc(self.start, path="fold.start")
        end = self.end if isinstance(self.end, datetime) else _utc(self.end, path="fold.end")
        start = require_utc(start, field_name="fold.start")
        end = require_utc(end, field_name="fold.end")
        if start >= end:
            raise ContractValidationError("fold.start must be before fold.end")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    def to_payload(self) -> dict[str, str]:
        return {"name": self.name, "start": utc_isoformat(self.start), "end": utc_isoformat(self.end)}


@dataclass(frozen=True)
class UpstreamV11:
    config_path: str
    config_hash: str
    bundle_path: str
    bundle_id: str
    study_id: str
    implementation_commit: str
    manifest_sha256: str
    manifest_bytes: int
    study_sha256: str
    study_bytes: int

    def to_payload(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class UpstreamV19:
    config_path: str
    config_hash: str
    bundle_path: str
    bundle_id: str
    study_id: str
    implementation_commit: str
    disposition: str
    manifest_sha256: str
    manifest_bytes: int
    study_sha256: str
    study_bytes: int

    def to_payload(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class UpstreamV10:
    config_path: str
    config_hash: str
    bundle_path: str
    bundle_id: str
    audit_id: str
    implementation_commit: str
    manifest_sha256: str
    manifest_bytes: int
    audit_sha256: str
    audit_bytes: int
    chart_sha256: str
    chart_bytes: int

    def to_payload(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class FrozenSource:
    source_bundle_id: str
    upstream_source_bundle_id: str
    source_id: str
    bars_sha256: str
    row_count: int
    start: datetime
    end: datetime
    grid_policy: str
    sr_config_path: str
    sr_config_hash: str
    input_config_path: str
    input_config_hash: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_bundle_id": self.source_bundle_id,
            "upstream_source_bundle_id": self.upstream_source_bundle_id,
            "source_id": self.source_id,
            "bars_sha256": self.bars_sha256,
            "row_count": self.row_count,
            "start": utc_isoformat(self.start),
            "end": utc_isoformat(self.end),
            "grid_policy": self.grid_policy,
            "sr_config_path": self.sr_config_path,
            "sr_config_hash": self.sr_config_hash,
            "input_config_path": self.input_config_path,
            "input_config_hash": self.input_config_hash,
        }


@dataclass(frozen=True)
class ReplayProtocol:
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
    common_start_index: int
    folds: tuple[FoldSpec, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "sr": {
                "detection": {"pivot_span_bars": self.pivot_span_bars, "zone_half_width_atr": self.zone_half_width_atr},
                "association": {"merge_distance_atr": self.merge_distance_atr},
                "lifecycle": {
                    "touch_tolerance_atr": self.touch_tolerance_atr,
                    "break_buffer_atr": self.break_buffer_atr,
                    "break_confirm_closes": self.break_confirm_closes,
                    "max_age_bars": self.max_age_bars,
                },
                "runtime": {"max_active_zones": self.max_active_zones},
            },
            "atr": {"method": self.atr_method, "period": self.atr_period, "seed": self.atr_seed},
            "common_start_index": self.common_start_index,
            "folds": [fold.to_payload() for fold in self.folds],
        }


@dataclass(frozen=True)
class ReadinessGates:
    unique_reinforced_zones: int
    comparable_folds: int
    minimum_reinforced_zones_per_comparable_fold: int

    def to_payload(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class ArtifactSpec:
    schema_version: str
    stage: str
    output_root: str

    def to_payload(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class CandidateAuditConfig:
    version: str
    trial_name: str
    venue: str
    asset: str
    timeframe: str
    v11: UpstreamV11
    v19: UpstreamV19
    v10: UpstreamV10
    source: FrozenSource
    replay: ReplayProtocol
    decision_categories: tuple[str, ...]
    readiness: ReadinessGates
    artifact: ArtifactSpec
    config_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if _string(self.version, path="version") != CONFIG_VERSION:
            raise ContractValidationError("unsupported V1.12 config version")
        if _string(self.trial_name, path="trial.trial_name") != TRIAL_NAME:
            raise ContractValidationError("trial name does not match V1.12")
        if (_string(self.venue, path="trial.venue"), _string(self.asset, path="trial.asset"), _string(self.timeframe, path="trial.timeframe")) != (APPROVED_VENUE, APPROVED_ASSET, APPROVED_TIMEFRAME):
            raise ContractValidationError("trial scope is outside approved TAOUSDT/1d audit")
        expected_v11 = UpstreamV11(V11_CONFIG_PATH, V11_CONFIG_HASH, V11_BUNDLE_PATH, V11_BUNDLE_ID, V11_STUDY_ID, V11_IMPLEMENTATION_COMMIT, V11_MANIFEST_SHA256, V11_MANIFEST_BYTES, V11_STUDY_SHA256, V11_STUDY_BYTES)
        expected_v19 = UpstreamV19(V19_CONFIG_PATH, V19_CONFIG_HASH, V19_BUNDLE_PATH, V19_BUNDLE_ID, V19_STUDY_ID, V19_IMPLEMENTATION_COMMIT, V19_DISPOSITION, V19_MANIFEST_SHA256, V19_MANIFEST_BYTES, V19_STUDY_SHA256, V19_STUDY_BYTES)
        expected_v10 = UpstreamV10(V10_CONFIG_PATH, V10_CONFIG_HASH, V10_BUNDLE_PATH, V10_BUNDLE_ID, V10_AUDIT_ID, V10_IMPLEMENTATION_COMMIT, V10_MANIFEST_SHA256, V10_MANIFEST_BYTES, V10_AUDIT_SHA256, V10_AUDIT_BYTES, V10_CHART_SHA256, V10_CHART_BYTES)
        expected_source = FrozenSource(SOURCE_BUNDLE_ID, UPSTREAM_SOURCE_BUNDLE_ID, SOURCE_ID, BARS_SHA256, SOURCE_ROWS, SOURCE_START, SOURCE_END, SOURCE_GRID_POLICY, SR_CONFIG_PATH, SR_CONFIG_HASH, INPUT_CONFIG_PATH, INPUT_CONFIG_HASH)
        if self.v11 != expected_v11 or self.v19 != expected_v19 or self.v10 != expected_v10 or self.source != expected_source:
            raise ContractValidationError("V1.12 upstream/source identity is not approved")
        if self.replay != ReplayProtocol(PIVOT_SPAN_BARS, ZONE_HALF_WIDTH_ATR, MERGE_DISTANCE_ATR, TOUCH_TOLERANCE_ATR, BREAK_BUFFER_ATR, BREAK_CONFIRM_CLOSES, MAX_AGE_BARS, MAX_ACTIVE_ZONES, ATR_METHOD, ATR_PERIOD, ATR_SEED, COMMON_START_INDEX, tuple(FoldSpec(name, start, end) for name, (start, end) in zip(FOLD_NAMES, FOLD_BOUNDS))):
            raise ContractValidationError("V1.12 replay protocol is not frozen")
        if self.decision_categories != DECISION_CATEGORIES:
            raise ContractValidationError("V1.12 decision categories are not exact")
        expected_gates = ReadinessGates(**READINESS_THRESHOLDS)
        if self.readiness != expected_gates:
            raise ContractValidationError("V1.12 readiness gates are not frozen")
        if self.artifact != ArtifactSpec(SCHEMA_VERSION, APPROVED_STAGE, "research/tmp_sr_v1_12/candidate_reinforcement_audit"):
            raise ContractValidationError("V1.12 artifact contract is not approved")
        object.__setattr__(self, "config_hash", deterministic_hash(self.to_payload()))

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "trial": {"trial_name": self.trial_name, "venue": self.venue, "asset": self.asset, "timeframe": self.timeframe},
            "inputs": {"v11": self.v11.to_payload(), "v19": self.v19.to_payload(), "v10": self.v10.to_payload(), "frozen": self.source.to_payload()},
            "protocol": self.replay.to_payload(),
            "decisions": {"categories": list(self.decision_categories)},
            "gates": {"readiness": self.readiness.to_payload()},
            "artifact": self.artifact.to_payload(),
        }


def _parse_upstream(raw: Any, *, path: str, cls: type[Any], keys: set[str]) -> Any:
    mapping = _mapping(raw, path=path)
    _exact(mapping, keys, path=path)
    values: dict[str, Any] = {}
    for name in keys:
        value = mapping[name]
        if name.endswith("_path") or name == "disposition":
            values[name] = _path(value, path=f"{path}.{name}") if name.endswith("_path") else _string(value, path=f"{path}.{name}")
        elif name.endswith("_bytes"):
            values[name] = _integer(value, path=f"{path}.{name}", minimum=1)
        elif name.endswith("_commit"):
            values[name] = _commit(value, path=f"{path}.{name}")
        else:
            values[name] = _hash(value, path=f"{path}.{name}")
    return cls(**values)


def _parse_config(raw: Any) -> CandidateAuditConfig:
    root = _mapping(raw, path="V1.12 config")
    _exact(root, {"version", "trial", "inputs", "protocol", "decisions", "gates", "artifact"}, path="V1.12 config")
    trial = _mapping(root["trial"], path="trial")
    _exact(trial, {"trial_name", "venue", "asset", "timeframe"}, path="trial")
    inputs = _mapping(root["inputs"], path="inputs")
    _exact(inputs, {"v11", "v19", "v10", "frozen"}, path="inputs")
    v11 = _parse_upstream(inputs["v11"], path="inputs.v11", cls=UpstreamV11, keys=set(UpstreamV11.__dataclass_fields__))
    v19 = _parse_upstream(inputs["v19"], path="inputs.v19", cls=UpstreamV19, keys=set(UpstreamV19.__dataclass_fields__))
    v10 = _parse_upstream(inputs["v10"], path="inputs.v10", cls=UpstreamV10, keys=set(UpstreamV10.__dataclass_fields__))
    frozen_raw = _mapping(inputs["frozen"], path="inputs.frozen")
    _exact(frozen_raw, set(FrozenSource.__dataclass_fields__), path="inputs.frozen")
    frozen = FrozenSource(
        source_bundle_id=_hash(frozen_raw["source_bundle_id"], path="inputs.frozen.source_bundle_id"),
        upstream_source_bundle_id=_hash(frozen_raw["upstream_source_bundle_id"], path="inputs.frozen.upstream_source_bundle_id"),
        source_id=_hash(frozen_raw["source_id"], path="inputs.frozen.source_id"),
        bars_sha256=_hash(frozen_raw["bars_sha256"], path="inputs.frozen.bars_sha256"),
        row_count=_integer(frozen_raw["row_count"], path="inputs.frozen.row_count", minimum=1),
        start=_utc(frozen_raw["start"], path="inputs.frozen.start"),
        end=_utc(frozen_raw["end"], path="inputs.frozen.end"),
        grid_policy=_string(frozen_raw["grid_policy"], path="inputs.frozen.grid_policy"),
        sr_config_path=_path(frozen_raw["sr_config_path"], path="inputs.frozen.sr_config_path"),
        sr_config_hash=_hash(frozen_raw["sr_config_hash"], path="inputs.frozen.sr_config_hash"),
        input_config_path=_path(frozen_raw["input_config_path"], path="inputs.frozen.input_config_path"),
        input_config_hash=_hash(frozen_raw["input_config_hash"], path="inputs.frozen.input_config_hash"),
    )
    protocol = _mapping(root["protocol"], path="protocol")
    _exact(protocol, {"sr", "atr", "common_start_index", "folds"}, path="protocol")
    sr = _mapping(protocol["sr"], path="protocol.sr")
    _exact(sr, {"detection", "association", "lifecycle", "runtime"}, path="protocol.sr")
    detection = _mapping(sr["detection"], path="protocol.sr.detection")
    _exact(detection, {"pivot_span_bars", "zone_half_width_atr"}, path="protocol.sr.detection")
    association = _mapping(sr["association"], path="protocol.sr.association")
    _exact(association, {"merge_distance_atr"}, path="protocol.sr.association")
    lifecycle = _mapping(sr["lifecycle"], path="protocol.sr.lifecycle")
    _exact(lifecycle, {"touch_tolerance_atr", "break_buffer_atr", "break_confirm_closes", "max_age_bars"}, path="protocol.sr.lifecycle")
    runtime = _mapping(sr["runtime"], path="protocol.sr.runtime")
    _exact(runtime, {"max_active_zones"}, path="protocol.sr.runtime")
    atr = _mapping(protocol["atr"], path="protocol.atr")
    _exact(atr, {"method", "period", "seed"}, path="protocol.atr")
    raw_folds = protocol["folds"]
    if type(raw_folds) is not list:
        raise ContractValidationError("protocol.folds must be a list")
    folds: list[FoldSpec] = []
    for index, item in enumerate(raw_folds):
        fold = _mapping(item, path=f"protocol.folds[{index}]")
        _exact(fold, {"name", "start", "end"}, path=f"protocol.folds[{index}]")
        folds.append(FoldSpec(_string(fold["name"], path=f"protocol.folds[{index}].name"), _utc(fold["start"], path=f"protocol.folds[{index}].start"), _utc(fold["end"], path=f"protocol.folds[{index}].end")))
    decisions = _mapping(root["decisions"], path="decisions")
    _exact(decisions, {"categories"}, path="decisions")
    categories = decisions["categories"]
    if type(categories) is not list or any(type(item) is not str for item in categories):
        raise ContractValidationError("decisions.categories must be a string list")
    gates = _mapping(root["gates"], path="gates")
    _exact(gates, {"readiness"}, path="gates")
    readiness_raw = _mapping(gates["readiness"], path="gates.readiness")
    _exact(readiness_raw, set(ReadinessGates.__dataclass_fields__), path="gates.readiness")
    readiness = ReadinessGates(**{name: _integer(readiness_raw[name], path=f"gates.readiness.{name}", minimum=1) for name in ReadinessGates.__dataclass_fields__})
    artifact_raw = _mapping(root["artifact"], path="artifact")
    _exact(artifact_raw, set(ArtifactSpec.__dataclass_fields__), path="artifact")
    artifact = ArtifactSpec(_string(artifact_raw["schema_version"], path="artifact.schema_version"), _string(artifact_raw["stage"], path="artifact.stage"), _path(artifact_raw["output_root"], path="artifact.output_root"))
    replay = ReplayProtocol(
        pivot_span_bars=_integer(detection["pivot_span_bars"], path="protocol.sr.detection.pivot_span_bars", minimum=1),
        zone_half_width_atr=_number(detection["zone_half_width_atr"], path="protocol.sr.detection.zone_half_width_atr", minimum=0.0),
        merge_distance_atr=_number(association["merge_distance_atr"], path="protocol.sr.association.merge_distance_atr", minimum=0.0),
        touch_tolerance_atr=_number(lifecycle["touch_tolerance_atr"], path="protocol.sr.lifecycle.touch_tolerance_atr", minimum=0.0),
        break_buffer_atr=_number(lifecycle["break_buffer_atr"], path="protocol.sr.lifecycle.break_buffer_atr", minimum=0.0),
        break_confirm_closes=_integer(lifecycle["break_confirm_closes"], path="protocol.sr.lifecycle.break_confirm_closes", minimum=1),
        max_age_bars=_integer(lifecycle["max_age_bars"], path="protocol.sr.lifecycle.max_age_bars", minimum=1),
        max_active_zones=_integer(runtime["max_active_zones"], path="protocol.sr.runtime.max_active_zones", minimum=1),
        atr_method=_string(atr["method"], path="protocol.atr.method"),
        atr_period=_integer(atr["period"], path="protocol.atr.period", minimum=1),
        atr_seed=_string(atr["seed"], path="protocol.atr.seed"),
        common_start_index=_integer(protocol["common_start_index"], path="protocol.common_start_index", minimum=0),
        folds=tuple(folds),
    )
    return CandidateAuditConfig(
        version=_string(root["version"], path="version"),
        trial_name=_string(trial["trial_name"], path="trial.trial_name"),
        venue=_string(trial["venue"], path="trial.venue"),
        asset=_string(trial["asset"], path="trial.asset"),
        timeframe=_string(trial["timeframe"], path="trial.timeframe"),
        v11=v11,
        v19=v19,
        v10=v10,
        source=frozen,
        replay=replay,
        decision_categories=tuple(categories),
        readiness=readiness,
        artifact=artifact,
    )


def load_candidate_audit_config(path: str | Path) -> CandidateAuditConfig:
    try:
        raw = load_strict_research_yaml(path, description="V1.12 config")
        return _parse_config(raw)
    except ContractValidationError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise ContractValidationError(f"invalid V1.12 configuration: {path}") from exc


__all__ = [
    "APPROVED_ASSET", "APPROVED_STAGE", "APPROVED_TIMEFRAME", "APPROVED_VENUE",
    "BARS_SHA256", "CandidateAuditConfig", "COMMON_START_INDEX", "DECISION_CATEGORIES",
    "FOLD_BOUNDS", "FOLD_NAMES", "FoldSpec", "INPUT_CONFIG_HASH", "MAX_ACTIVE_ZONES",
    "READINESS_THRESHOLDS", "SOURCE_BUNDLE_ID", "SOURCE_ID", "SR_CONFIG_HASH",
    "TRIAL_NAME", "UPSTREAM_SOURCE_BUNDLE_ID", "V10_AUDIT_ID", "V10_BUNDLE_ID",
    "V11_BUNDLE_ID", "V11_STUDY_ID", "V19_BUNDLE_ID", "V19_STUDY_ID",
    "load_candidate_audit_config",
]
