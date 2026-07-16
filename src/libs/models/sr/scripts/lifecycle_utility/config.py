"""Fail-closed configuration for the SR-V1.11 lifecycle utility."""

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
from libs.models.sr.domain.identity import deterministic_hash, require_utc, utc_isoformat
from libs.models.sr.scripts.cohort_readiness.contracts import CohortFold


CONFIG_VERSION = "1"
SCHEMA_VERSION = "1.0"
TRIAL_NAME = "sr-v1.11-taousdt-1d-lifecycle-utility"
APPROVED_VENUE = "binance_usdm"
APPROVED_ASSET = "TAOUSDT"
APPROVED_TIMEFRAME = "1d"

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
V10_TRACE_ID = "5e58eeb1e3aef84a096d348779d92d76268da619ad4445dee397d56fe688047f"
V10_MANIFEST_SHA256 = "482dc10c3a5eaa1142b1b8b7967eea39464f9975ceef14b3aaddb04c66588baf"
V10_MANIFEST_BYTES = 9854
V10_AUDIT_SHA256 = "27afe6242cc68e0222c7f93ef212b9ad87faaaf53c1b21e6edcbc5a8e2eaceb1"
V10_AUDIT_BYTES = 266791
V10_CHART_SHA256 = "621df3d8cbd6191567c00b31bed54848acf4a91d0f1f920d7fc1ea2f70cf0714"
V10_CHART_BYTES = 605404

FROZEN_SOURCE_BUNDLE_ID = "d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925"
V10_UPSTREAM_SOURCE_BUNDLE_ID = "6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9"
FROZEN_SOURCE_ID = "fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120"
FROZEN_BARS_SHA256 = "703367048f4ed7dc432ca9dfe0ad4afdc5a56eb2a508597ef00bdc3de8b81163"
FROZEN_SR_CONFIG_HASH = "cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299"
FROZEN_INPUT_HASH = "5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d"
FROZEN_SOURCE_ROWS = 629
FROZEN_SOURCE_START = datetime(2024, 4, 11, tzinfo=timezone.utc)
FROZEN_SOURCE_END = datetime(2025, 12, 31, tzinfo=timezone.utc)
FROZEN_GRID_POLICY = "exact_utc_daily_grid_from_taousdt_development_capsule"

FROZEN_ATR_METHOD = "wilder_rma"
FROZEN_ATR_PERIOD = 14
FROZEN_ATR_SEED = "sma"
FROZEN_ATR_CONTRACT = "true_range_sma_seed_then_wilder_recursion_v1"
FROZEN_OUTCOME_OFFSET = 1
FROZEN_OUTCOME_HORIZON = 10
FROZEN_WINDOW_POLICY = "half_open_utc_daily"
FROZEN_ANCHOR_POLICY = "resolution_event_bar_close"
FROZEN_EFFECTIVE_SIDE_POLICY = "false_breakout_retain_original_break_confirmed_flip"
FROZEN_EVENT_CLASSES = ("FALSE_BREAKOUT", "BREAK_CONFIRMED")
FROZEN_FOLD_NAMES = (
    "2024_q3",
    "2024_q4",
    "2025_q1",
    "2025_q2",
    "2025_q3",
    "2025_q4",
)
FROZEN_FOLD_BOUNDS = (
    (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2024, 10, 1, tzinfo=timezone.utc)),
    (datetime(2024, 10, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
    (datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 4, 1, tzinfo=timezone.utc)),
    (datetime(2025, 4, 1, tzinfo=timezone.utc), datetime(2025, 7, 1, tzinfo=timezone.utc)),
    (datetime(2025, 7, 1, tzinfo=timezone.utc), datetime(2025, 10, 1, tzinfo=timezone.utc)),
    (datetime(2025, 10, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
)

APPROVED_READINESS_GATES = {
    "minimum_completed_unique_resolutions": 16,
    "minimum_comparable_folds": 4,
    "minimum_completed_per_comparable_fold": 2,
    "minimum_null_controls_per_compared_cell": 4,
}
APPROVED_QUALITY_GATES = {
    "minimum_pooled_median_excess_quality_atr": 0.10,
    "minimum_positive_comparable_fold_fraction": 0.60,
    "minimum_worst_comparable_fold_median_excess_atr": -0.10,
    "minimum_event_class_comparable_outcomes": 4,
    "minimum_event_class_median_excess_atr": 0.0,
}

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
        parsed = require_utc(parsed, field_name=path)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"{path} must be a valid UTC timestamp") from exc
    if parsed.hour or parsed.minute or parsed.second or parsed.microsecond:
        raise ContractValidationError(f"{path} must align to a UTC daily boundary")
    return parsed


def _reject_aliases(path: str | Path) -> None:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContractValidationError(f"cannot read lifecycle utility config: {path}") from exc
    for line in text.splitlines():
        if re.match(r"^\s*<<\s*:", line) or re.search(r"(?:^|[\s\[,])(?:&|\*)[A-Za-z_][A-Za-z0-9_.-]*", line):
            raise ContractValidationError("YAML aliases and merge keys are forbidden")


@dataclass(frozen=True)
class ReadinessGates:
    minimum_completed_unique_resolutions: int
    minimum_comparable_folds: int
    minimum_completed_per_comparable_fold: int
    minimum_null_controls_per_compared_cell: int

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = _integer(getattr(self, name), path=f"gates.readiness.{name}", minimum=1)
            expected = APPROVED_READINESS_GATES[name]
            if value != expected:
                raise ContractValidationError(f"gates.readiness.{name} is not approved")
            object.__setattr__(self, name, value)

    def to_payload(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class QualityGates:
    minimum_pooled_median_excess_quality_atr: float
    minimum_positive_comparable_fold_fraction: float
    minimum_worst_comparable_fold_median_excess_atr: float
    minimum_event_class_comparable_outcomes: int
    minimum_event_class_median_excess_atr: float

    def __post_init__(self) -> None:
        for name in ("minimum_pooled_median_excess_quality_atr", "minimum_worst_comparable_fold_median_excess_atr", "minimum_event_class_median_excess_atr"):
            value = _number(getattr(self, name), path=f"gates.quality.{name}")
            if value != APPROVED_QUALITY_GATES[name]:
                raise ContractValidationError(f"gates.quality.{name} is not approved")
            object.__setattr__(self, name, value)
        fraction = _number(self.minimum_positive_comparable_fold_fraction, path="gates.quality.minimum_positive_comparable_fold_fraction", minimum=0.0)
        if fraction > 1.0 or fraction != APPROVED_QUALITY_GATES["minimum_positive_comparable_fold_fraction"]:
            raise ContractValidationError("gates.quality.minimum_positive_comparable_fold_fraction is not approved")
        object.__setattr__(self, "minimum_positive_comparable_fold_fraction", fraction)
        count = _integer(self.minimum_event_class_comparable_outcomes, path="gates.quality.minimum_event_class_comparable_outcomes", minimum=1)
        if count != APPROVED_QUALITY_GATES["minimum_event_class_comparable_outcomes"]:
            raise ContractValidationError("gates.quality.minimum_event_class_comparable_outcomes is not approved")
        object.__setattr__(self, "minimum_event_class_comparable_outcomes", count)

    def to_payload(self) -> dict[str, int | float]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class LifecycleUtilityConfig:
    version: str
    trial_name: str
    venue: str
    asset: str
    timeframe: str
    v19_config_path: str
    v19_config_hash: str
    v19_bundle_path: str
    v19_bundle_id: str
    v19_study_id: str
    v19_implementation_commit: str
    v19_disposition: str
    v19_manifest_sha256: str
    v19_manifest_bytes: int
    v19_study_sha256: str
    v19_study_bytes: int
    v10_config_path: str
    v10_config_hash: str
    v10_bundle_path: str
    v10_bundle_id: str
    v10_audit_id: str
    v10_implementation_commit: str
    v10_trace_id: str
    v10_manifest_sha256: str
    v10_manifest_bytes: int
    v10_audit_sha256: str
    v10_audit_bytes: int
    v10_chart_sha256: str
    v10_chart_bytes: int
    source_bundle_id: str
    source_id: str
    bars_sha256: str
    source_row_count: int
    source_start: datetime
    source_end: datetime
    source_grid_policy: str
    frozen_sr_config_hash: str
    frozen_input_hash: str
    atr_method: str
    atr_period: int
    atr_seed: str
    atr_contract: str
    event_classes: tuple[str, ...]
    deduplicate_by_zone: bool
    effective_side_policy: str
    anchor_policy: str
    outcome_start_offset_bars: int
    outcome_horizon_bars: int
    window_policy: str
    folds: tuple[CohortFold, ...]
    readiness: ReadinessGates
    quality: QualityGates
    output_root: str
    config_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if _string(self.version, path="version") != CONFIG_VERSION:
            raise ContractValidationError("unsupported V1.11 config version")
        if _string(self.trial_name, path="trial.trial_name") != TRIAL_NAME:
            raise ContractValidationError("trial name does not match V1.11")
        if (_string(self.venue, path="trial.venue"), _string(self.asset, path="trial.asset"), _string(self.timeframe, path="trial.timeframe")) != (APPROVED_VENUE, APPROVED_ASSET, APPROVED_TIMEFRAME):
            raise ContractValidationError("trial scope is outside approved TAOUSDT/1d utility")

        identity_fields = {
            "v19_config_hash": V19_CONFIG_HASH, "v19_bundle_id": V19_BUNDLE_ID, "v19_study_id": V19_STUDY_ID,
            "v19_manifest_sha256": V19_MANIFEST_SHA256, "v19_study_sha256": V19_STUDY_SHA256,
            "v10_config_hash": V10_CONFIG_HASH, "v10_bundle_id": V10_BUNDLE_ID, "v10_audit_id": V10_AUDIT_ID,
            "v10_trace_id": V10_TRACE_ID, "v10_manifest_sha256": V10_MANIFEST_SHA256, "v10_audit_sha256": V10_AUDIT_SHA256, "v10_chart_sha256": V10_CHART_SHA256,
            "source_bundle_id": FROZEN_SOURCE_BUNDLE_ID, "source_id": FROZEN_SOURCE_ID, "bars_sha256": FROZEN_BARS_SHA256,
            "frozen_sr_config_hash": FROZEN_SR_CONFIG_HASH, "frozen_input_hash": FROZEN_INPUT_HASH,
        }
        for name, expected in identity_fields.items():
            object.__setattr__(self, name, _hash(getattr(self, name), path=f"inputs.{name}"))
            if getattr(self, name) != expected:
                raise ContractValidationError(f"inputs.{name} is not the approved frozen identity")
        for name, expected in (("v19_implementation_commit", V19_IMPLEMENTATION_COMMIT), ("v10_implementation_commit", V10_IMPLEMENTATION_COMMIT)):
            object.__setattr__(self, name, _commit(getattr(self, name), path=f"inputs.{name}"))
            if getattr(self, name) != expected:
                raise ContractValidationError(f"inputs.{name} is not the approved implementation identity")
        for name, expected in (("v19_config_path", V19_CONFIG_PATH), ("v19_bundle_path", V19_BUNDLE_PATH), ("v10_config_path", V10_CONFIG_PATH), ("v10_bundle_path", V10_BUNDLE_PATH)):
            object.__setattr__(self, name, _path(getattr(self, name), path=f"inputs.{name}"))
            if getattr(self, name) != expected:
                raise ContractValidationError(f"inputs.{name} is not the approved frozen path")
        if _string(self.v19_disposition, path="inputs.v19.disposition") != V19_DISPOSITION:
            raise ContractValidationError("V1.9 disposition is not the approved negative result")
        for name, expected in (("v19_manifest_bytes", V19_MANIFEST_BYTES), ("v19_study_bytes", V19_STUDY_BYTES), ("v10_manifest_bytes", V10_MANIFEST_BYTES), ("v10_audit_bytes", V10_AUDIT_BYTES), ("v10_chart_bytes", V10_CHART_BYTES)):
            value = _integer(getattr(self, name), path=f"inputs.{name}", minimum=1)
            if value != expected:
                raise ContractValidationError(f"inputs.{name} is not the approved byte length")
            object.__setattr__(self, name, value)

        object.__setattr__(self, "source_row_count", _integer(self.source_row_count, path="protocol.source.row_count", minimum=1))
        if self.source_row_count != FROZEN_SOURCE_ROWS:
            raise ContractValidationError("protocol.source.row_count is not 629")
        source_start = _utc(utc_isoformat(self.source_start), path="protocol.source.start") if isinstance(self.source_start, datetime) else _utc(self.source_start, path="protocol.source.start")
        source_end = _utc(utc_isoformat(self.source_end), path="protocol.source.end") if isinstance(self.source_end, datetime) else _utc(self.source_end, path="protocol.source.end")
        if (source_start, source_end) != (FROZEN_SOURCE_START, FROZEN_SOURCE_END):
            raise ContractValidationError("protocol.source bounds are not frozen")
        object.__setattr__(self, "source_start", source_start)
        object.__setattr__(self, "source_end", source_end)
        if _string(self.source_grid_policy, path="protocol.source.grid_policy") != FROZEN_GRID_POLICY:
            raise ContractValidationError("protocol.source.grid_policy is not approved")
        if _string(self.atr_method, path="protocol.atr.method") != FROZEN_ATR_METHOD or _integer(self.atr_period, path="protocol.atr.period", minimum=1) != FROZEN_ATR_PERIOD or _string(self.atr_seed, path="protocol.atr.seed") != FROZEN_ATR_SEED or _string(self.atr_contract, path="protocol.atr.contract") != FROZEN_ATR_CONTRACT:
            raise ContractValidationError("ATR contract is not frozen Wilder RMA(14)/SMA")
        object.__setattr__(self, "atr_period", FROZEN_ATR_PERIOD)
        if type(self.event_classes) is not tuple or self.event_classes != FROZEN_EVENT_CLASSES:
            raise ContractValidationError("resolution.event_classes are not the approved ordered pair")
        if type(self.deduplicate_by_zone) is not bool or not self.deduplicate_by_zone:
            raise ContractValidationError("resolution.deduplicate_by_zone must be true")
        if _string(self.effective_side_policy, path="resolution.effective_side_policy") != FROZEN_EFFECTIVE_SIDE_POLICY:
            raise ContractValidationError("resolution.effective_side_policy is not approved")
        if _string(self.anchor_policy, path="protocol.outcome.anchor_policy") != FROZEN_ANCHOR_POLICY:
            raise ContractValidationError("outcome.anchor_policy is not approved")
        if _integer(self.outcome_start_offset_bars, path="protocol.outcome.start_offset_bars", minimum=1) != FROZEN_OUTCOME_OFFSET or _integer(self.outcome_horizon_bars, path="protocol.outcome.horizon_bars", minimum=1) != FROZEN_OUTCOME_HORIZON:
            raise ContractValidationError("outcome offset/horizon are not frozen")
        if _string(self.window_policy, path="protocol.outcome.window_policy") != FROZEN_WINDOW_POLICY:
            raise ContractValidationError("outcome.window_policy is not approved")
        if type(self.folds) is not tuple or tuple((fold.name, fold.start, fold.end) for fold in self.folds) != tuple((name, start, end) for (name, (start, end)) in zip(FROZEN_FOLD_NAMES, FROZEN_FOLD_BOUNDS)):
            raise ContractValidationError("fold names/boundaries do not match the frozen six-fold protocol")
        if type(self.readiness) is not ReadinessGates or type(self.quality) is not QualityGates:
            raise ContractValidationError("gate groups are invalid")
        object.__setattr__(self, "output_root", _path(self.output_root, path="output.root"))
        object.__setattr__(self, "config_hash", deterministic_hash(self.to_payload()))

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "trial": {"trial_name": self.trial_name, "venue": self.venue, "asset": self.asset, "timeframe": self.timeframe},
            "inputs": {
                "v19": {"config_path": self.v19_config_path, "config_hash": self.v19_config_hash, "bundle_path": self.v19_bundle_path, "bundle_id": self.v19_bundle_id, "study_id": self.v19_study_id, "implementation_commit": self.v19_implementation_commit, "disposition": self.v19_disposition, "manifest_sha256": self.v19_manifest_sha256, "manifest_bytes": self.v19_manifest_bytes, "study_sha256": self.v19_study_sha256, "study_bytes": self.v19_study_bytes},
                "v10": {"config_path": self.v10_config_path, "config_hash": self.v10_config_hash, "bundle_path": self.v10_bundle_path, "bundle_id": self.v10_bundle_id, "audit_id": self.v10_audit_id, "implementation_commit": self.v10_implementation_commit, "trace_id": self.v10_trace_id, "manifest_sha256": self.v10_manifest_sha256, "manifest_bytes": self.v10_manifest_bytes, "audit_sha256": self.v10_audit_sha256, "audit_bytes": self.v10_audit_bytes, "chart_sha256": self.v10_chart_sha256, "chart_bytes": self.v10_chart_bytes},
                "frozen": {"source_bundle_id": self.source_bundle_id, "source_id": self.source_id, "bars_sha256": self.bars_sha256, "source_row_count": self.source_row_count, "source_start": utc_isoformat(self.source_start), "source_end": utc_isoformat(self.source_end), "grid_policy": self.source_grid_policy, "frozen_sr_config_hash": self.frozen_sr_config_hash, "frozen_input_hash": self.frozen_input_hash},
            },
            "protocol": {
                "atr": {"method": self.atr_method, "period": self.atr_period, "seed": self.atr_seed, "contract": self.atr_contract},
                "resolution": {"event_classes": list(self.event_classes), "deduplicate_by_zone": self.deduplicate_by_zone, "effective_side_policy": self.effective_side_policy},
                "outcome": {"anchor_policy": self.anchor_policy, "start_offset_bars": self.outcome_start_offset_bars, "horizon_bars": self.outcome_horizon_bars, "window_policy": self.window_policy},
                "folds": [fold.to_payload() for fold in self.folds],
            },
            "gates": {"readiness": self.readiness.to_payload(), "quality": self.quality.to_payload()},
            "output": {"root": self.output_root},
        }


def _parse_folds(raw: Any) -> tuple[CohortFold, ...]:
    if type(raw) is not list:
        raise ContractValidationError("protocol.folds must be a list")
    folds: list[CohortFold] = []
    for index, item in enumerate(raw):
        mapping = _mapping(item, path=f"protocol.folds[{index}]")
        _exact(mapping, {"name", "start", "end"}, path=f"protocol.folds[{index}]")
        folds.append(CohortFold(name=_string(mapping["name"], path=f"protocol.folds[{index}].name"), start=_utc(mapping["start"], path=f"protocol.folds[{index}].start"), end=_utc(mapping["end"], path=f"protocol.folds[{index}].end")))
    return tuple(folds)


def _parse_document(raw: Mapping[str, Any]) -> LifecycleUtilityConfig:
    root = _mapping(raw, path="lifecycle utility config")
    _exact(root, {"version", "trial", "inputs", "protocol", "gates", "output"}, path="lifecycle utility config")
    trial = _mapping(root["trial"], path="trial")
    _exact(trial, {"trial_name", "venue", "asset", "timeframe"}, path="trial")
    inputs = _mapping(root["inputs"], path="inputs")
    _exact(inputs, {"v19", "v10", "frozen"}, path="inputs")
    v19 = _mapping(inputs["v19"], path="inputs.v19")
    _exact(v19, {"config_path", "config_hash", "bundle_path", "bundle_id", "study_id", "implementation_commit", "disposition", "manifest_sha256", "manifest_bytes", "study_sha256", "study_bytes"}, path="inputs.v19")
    v10 = _mapping(inputs["v10"], path="inputs.v10")
    _exact(v10, {"config_path", "config_hash", "bundle_path", "bundle_id", "audit_id", "implementation_commit", "trace_id", "manifest_sha256", "manifest_bytes", "audit_sha256", "audit_bytes", "chart_sha256", "chart_bytes"}, path="inputs.v10")
    frozen = _mapping(inputs["frozen"], path="inputs.frozen")
    _exact(frozen, {"source_bundle_id", "source_id", "bars_sha256", "source_row_count", "source_start", "source_end", "grid_policy", "frozen_sr_config_hash", "frozen_input_hash"}, path="inputs.frozen")
    protocol = _mapping(root["protocol"], path="protocol")
    _exact(protocol, {"atr", "resolution", "outcome", "folds"}, path="protocol")
    atr = _mapping(protocol["atr"], path="protocol.atr")
    _exact(atr, {"method", "period", "seed", "contract"}, path="protocol.atr")
    resolution = _mapping(protocol["resolution"], path="protocol.resolution")
    _exact(resolution, {"event_classes", "deduplicate_by_zone", "effective_side_policy"}, path="protocol.resolution")
    if type(resolution["event_classes"]) is not list:
        raise ContractValidationError("protocol.resolution.event_classes must be a list")
    outcome = _mapping(protocol["outcome"], path="protocol.outcome")
    _exact(outcome, {"anchor_policy", "start_offset_bars", "horizon_bars", "window_policy"}, path="protocol.outcome")
    gates = _mapping(root["gates"], path="gates")
    _exact(gates, {"readiness", "quality"}, path="gates")
    readiness = _mapping(gates["readiness"], path="gates.readiness")
    _exact(readiness, set(ReadinessGates.__dataclass_fields__), path="gates.readiness")
    quality = _mapping(gates["quality"], path="gates.quality")
    _exact(quality, set(QualityGates.__dataclass_fields__), path="gates.quality")
    output = _mapping(root["output"], path="output")
    _exact(output, {"root"}, path="output")
    return LifecycleUtilityConfig(
        version=root["version"], trial_name=trial["trial_name"], venue=trial["venue"], asset=trial["asset"], timeframe=trial["timeframe"],
        v19_config_path=v19["config_path"], v19_config_hash=v19["config_hash"], v19_bundle_path=v19["bundle_path"], v19_bundle_id=v19["bundle_id"], v19_study_id=v19["study_id"], v19_implementation_commit=v19["implementation_commit"], v19_disposition=v19["disposition"], v19_manifest_sha256=v19["manifest_sha256"], v19_manifest_bytes=v19["manifest_bytes"], v19_study_sha256=v19["study_sha256"], v19_study_bytes=v19["study_bytes"],
        v10_config_path=v10["config_path"], v10_config_hash=v10["config_hash"], v10_bundle_path=v10["bundle_path"], v10_bundle_id=v10["bundle_id"], v10_audit_id=v10["audit_id"], v10_implementation_commit=v10["implementation_commit"], v10_trace_id=v10["trace_id"], v10_manifest_sha256=v10["manifest_sha256"], v10_manifest_bytes=v10["manifest_bytes"], v10_audit_sha256=v10["audit_sha256"], v10_audit_bytes=v10["audit_bytes"], v10_chart_sha256=v10["chart_sha256"], v10_chart_bytes=v10["chart_bytes"],
        source_bundle_id=frozen["source_bundle_id"], source_id=frozen["source_id"], bars_sha256=frozen["bars_sha256"], source_row_count=frozen["source_row_count"], source_start=_utc(frozen["source_start"], path="inputs.frozen.source_start"), source_end=_utc(frozen["source_end"], path="inputs.frozen.source_end"), source_grid_policy=frozen["grid_policy"], frozen_sr_config_hash=frozen["frozen_sr_config_hash"], frozen_input_hash=frozen["frozen_input_hash"],
        atr_method=atr["method"], atr_period=atr["period"], atr_seed=atr["seed"], atr_contract=atr["contract"], event_classes=tuple(resolution["event_classes"]), deduplicate_by_zone=resolution["deduplicate_by_zone"], effective_side_policy=resolution["effective_side_policy"], anchor_policy=outcome["anchor_policy"], outcome_start_offset_bars=outcome["start_offset_bars"], outcome_horizon_bars=outcome["horizon_bars"], window_policy=outcome["window_policy"], folds=_parse_folds(protocol["folds"]), readiness=ReadinessGates(**dict(readiness)), quality=QualityGates(**dict(quality)), output_root=output["root"],
    )


def parse_lifecycle_utility_config(raw: Mapping[str, Any]) -> LifecycleUtilityConfig:
    return _parse_document(raw)


def load_lifecycle_utility_config(path: str | Path) -> LifecycleUtilityConfig:
    _reject_aliases(path)
    try:
        payload = load_sr_config(path)
    except ContractValidationError:
        raise
    except Exception as exc:  # pragma: no cover - adapter boundary hardening
        raise ContractValidationError(f"cannot load lifecycle utility config: {path}") from exc
    return _parse_document(payload)


load_config = load_lifecycle_utility_config


__all__ = [
    "LifecycleUtilityConfig", "QualityGates", "ReadinessGates", "load_config",
    "load_lifecycle_utility_config", "parse_lifecycle_utility_config",
]
