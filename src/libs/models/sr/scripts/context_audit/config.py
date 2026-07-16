"""Strict, immutable configuration for the SR-V1.10 context audit."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePath
import re
from typing import Any

from libs.models.sr.adapters.yaml_config import load_sr_config
from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash, require_utc, utc_isoformat
from libs.models.sr.scripts.baseline_trial.contracts import ViewerConfig
from libs.models.sr.scripts.cohort_readiness.contracts import CohortFold


CONFIG_VERSION = "1"
SCHEMA_VERSION = "1.0"
TRIAL_NAME = "sr-v1.10-taousdt-1d-context-audit"
APPROVED_VENUE = "binance_usdm"
APPROVED_ASSET = "TAOUSDT"
APPROVED_TIMEFRAME = "1d"
APPROVED_PURPOSE = "diagnostic_only"
APPROVED_AUDIT_STATUS = "COMPLETE"
APPROVED_SOURCE_ROWS = 629
APPROVED_SOURCE_START = datetime(2024, 4, 11, tzinfo=timezone.utc)
APPROVED_SOURCE_END = datetime(2025, 12, 31, tzinfo=timezone.utc)
APPROVED_GRID_POLICY = "exact_utc_daily_grid_from_taousdt_development_capsule"
APPROVED_ATR_METHOD = "wilder_rma"
APPROVED_ATR_PERIOD = 14
APPROVED_ATR_SEED = "sma"
APPROVED_PIVOT_SPAN = 5
APPROVED_ZONE_HALF_WIDTH = 0.25
APPROVED_MERGE_DISTANCE = 0.50
APPROVED_TOUCH_TOLERANCE = 0.25
APPROVED_BREAK_BUFFER = 0.25
APPROVED_BREAK_CONFIRM_CLOSES = 2
APPROVED_MAX_AGE = 50
APPROVED_MAX_ACTIVE_ZONES = 8
APPROVED_OUTCOME_OFFSET = 1
APPROVED_OUTCOME_HORIZON = 10
APPROVED_WINDOW_POLICY = "half_open_utc_daily"
APPROVED_CASE_ORDER = ("first_touch_at", "zone_id")
APPROVED_FOLD_NAMES = (
    "2024_q3",
    "2024_q4",
    "2025_q1",
    "2025_q2",
    "2025_q3",
    "2025_q4",
)
APPROVED_FOLD_BOUNDS = (
    (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2024, 10, 1, tzinfo=timezone.utc)),
    (datetime(2024, 10, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
    (datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 4, 1, tzinfo=timezone.utc)),
    (datetime(2025, 4, 1, tzinfo=timezone.utc), datetime(2025, 7, 1, tzinfo=timezone.utc)),
    (datetime(2025, 7, 1, tzinfo=timezone.utc), datetime(2025, 10, 1, tzinfo=timezone.utc)),
    (datetime(2025, 10, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
)

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

V17_CONFIG_HASH = "370d2b66e8e3031b0df8547e8b52c61288e14c5d1b858612ce9fae712e1690a7"
V17_SOURCE_BUNDLE_ID = "6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9"
V17_SOURCE_MEMBER_ID = "fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120"
V17_EVALUATION_BUNDLE_ID = "824e9265a63073ba792762a891adf52deec9677d791c40641dc0107c1f2b840d"
V17_EVALUATION_ID = "49a895360774ec0c46349eae2d1ec6f56e7262e5f1411ab992f9886d9040fa8d"
V18_CONFIG_HASH = "86137d2c5b5e12802a5731298ab548822f23c4937d635bae5f21b77a8e7c0da7"
V18_STUDY_BUNDLE_ID = "b0ea33decc9c8c40dab98bdbb90635652dc199031fc50b27d3a71a6711378941"
V18_STUDY_ID = "2a324d3a203642bf9030aede611a8d874fcb051c5b394fcb4758582d6cfbc954"
V18_BASELINE_CANDIDATE_ID = "37769b33cc663e4baf5488001252a996b9cb2ec67d0182400f12cb928015709c"
FROZEN_SR_CONFIG_HASH = "cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299"
FROZEN_INPUT_HASH = "5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d"

_HASH_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")
_IDENTITY_NAMES = {
    "v19_config_hash": V19_CONFIG_HASH,
    "v19_bundle_id": V19_BUNDLE_ID,
    "v19_study_id": V19_STUDY_ID,
    "v17_config_hash": V17_CONFIG_HASH,
    "v17_source_bundle_id": V17_SOURCE_BUNDLE_ID,
    "v17_source_member_id": V17_SOURCE_MEMBER_ID,
    "v17_evaluation_bundle_id": V17_EVALUATION_BUNDLE_ID,
    "v17_evaluation_id": V17_EVALUATION_ID,
    "v18_config_hash": V18_CONFIG_HASH,
    "v18_study_bundle_id": V18_STUDY_BUNDLE_ID,
    "v18_study_id": V18_STUDY_ID,
    "v18_baseline_candidate_id": V18_BASELINE_CANDIDATE_ID,
    "production_sr_config_hash": FROZEN_SR_CONFIG_HASH,
    "frozen_input_hash": FROZEN_INPUT_HASH,
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
    if result != result or result in (float("inf"), float("-inf")):
        raise ContractValidationError(f"{path} must be finite")
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{path} must be >= {minimum}")
    return 0.0 if result == 0.0 else result


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


def _path(value: Any, *, path: str) -> str:
    value = _string(value, path=path)
    pure = PurePath(value.replace("\\", "/"))
    if Path(value).is_absolute() or value.startswith("/") or ".." in pure.parts:
        raise ContractValidationError(f"{path} must be a safe relative path")
    return value


def _reject_aliases(path: str | Path) -> None:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContractValidationError(f"cannot read context audit config: {path}") from exc
    for line in text.splitlines():
        if re.match(r"^\s*<<\s*:", line) or re.search(
            r"(?:^|[\s\[,])(?:&|\*)[A-Za-z_][A-Za-z0-9_.-]*", line
        ):
            raise ContractValidationError("YAML aliases and merge keys are forbidden")


@dataclass(frozen=True)
class ContextAuditConfig:
    version: str
    trial_name: str
    venue: str
    asset: str
    timeframe: str
    purpose: str
    v19_config_path: str
    v19_config_hash: str
    v19_bundle_path: str
    v19_bundle_id: str
    v19_study_id: str
    v19_implementation_commit: str
    v19_disposition: str
    v17_config_hash: str
    v17_source_bundle_id: str
    v17_source_member_id: str
    v17_evaluation_bundle_id: str
    v17_evaluation_id: str
    v18_config_hash: str
    v18_study_bundle_id: str
    v18_study_id: str
    v18_baseline_candidate_id: str
    production_sr_config_hash: str
    frozen_input_hash: str
    source_row_count: int
    source_start: datetime
    source_end: datetime
    grid_policy: str
    atr_method: str
    atr_period: int
    atr_seed: str
    pivot_span_bars: int
    zone_half_width_atr: float
    merge_distance_atr: float
    touch_tolerance_atr: float
    break_buffer_atr: float
    break_confirm_closes: int
    max_age_bars: int
    max_active_zones: int
    outcome_start_offset_bars: int
    outcome_horizon_bars: int
    window_policy: str
    folds: tuple[CohortFold, ...]
    case_order: tuple[str, ...]
    viewer: ViewerConfig
    output_root: str
    audit_status: str = APPROVED_AUDIT_STATUS
    config_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if _string(self.version, path="version") != CONFIG_VERSION:
            raise ContractValidationError("unsupported V1.10 config version")
        if _string(self.trial_name, path="trial.trial_name") != TRIAL_NAME:
            raise ContractValidationError("trial name does not match V1.10")
        if (_string(self.venue, path="trial.venue"), _string(self.asset, path="trial.asset"), _string(self.timeframe, path="trial.timeframe")) != (APPROVED_VENUE, APPROVED_ASSET, APPROVED_TIMEFRAME):
            raise ContractValidationError("trial scope is outside approved TAOUSDT/1d audit")
        if _string(self.purpose, path="trial.purpose") != APPROVED_PURPOSE:
            raise ContractValidationError("V1.10 purpose must be diagnostic_only")
        for name in ("v19_config_hash", "v19_bundle_id", "v19_study_id", "v17_config_hash", "v17_source_bundle_id", "v17_source_member_id", "v17_evaluation_bundle_id", "v17_evaluation_id", "v18_config_hash", "v18_study_bundle_id", "v18_study_id", "v18_baseline_candidate_id", "production_sr_config_hash", "frozen_input_hash"):
            object.__setattr__(self, name, _hash(getattr(self, name), path=f"inputs.{name}"))
            if getattr(self, name) != _IDENTITY_NAMES[name]:
                raise ContractValidationError(f"inputs.{name} is not the approved frozen identity")
        object.__setattr__(self, "v19_implementation_commit", _commit(self.v19_implementation_commit, path="inputs.v19_implementation_commit"))
        if self.v19_implementation_commit != V19_IMPLEMENTATION_COMMIT:
            raise ContractValidationError("V1.9 implementation identity is not approved")
        if _string(self.v19_disposition, path="inputs.v19_disposition") != V19_DISPOSITION:
            raise ContractValidationError("V1.9 disposition is not the approved negative result")
        for name in ("v19_config_path", "v19_bundle_path", "output_root"):
            object.__setattr__(self, name, _path(getattr(self, name), path=f"inputs.{name}" if name != "output_root" else "output.root"))
        if self.v19_config_path != V19_CONFIG_PATH or self.v19_bundle_path != V19_BUNDLE_PATH:
            raise ContractValidationError("V1.9 paths are not the approved frozen paths")
        object.__setattr__(self, "source_row_count", _integer(self.source_row_count, path="protocol.source.row_count", minimum=1))
        if self.source_row_count != APPROVED_SOURCE_ROWS:
            raise ContractValidationError("protocol.source.row_count must be 629")
        start = _utc(utc_isoformat(self.source_start), path="protocol.source.start") if isinstance(self.source_start, datetime) else _utc(self.source_start, path="protocol.source.start")
        end = _utc(utc_isoformat(self.source_end), path="protocol.source.end") if isinstance(self.source_end, datetime) else _utc(self.source_end, path="protocol.source.end")
        if (start, end) != (APPROVED_SOURCE_START, APPROVED_SOURCE_END):
            raise ContractValidationError("protocol source bounds are not frozen")
        object.__setattr__(self, "source_start", start)
        object.__setattr__(self, "source_end", end)
        if _string(self.grid_policy, path="protocol.source.grid_policy") != APPROVED_GRID_POLICY:
            raise ContractValidationError("unsupported source grid policy")
        if _string(self.atr_method, path="protocol.model.atr_method") != APPROVED_ATR_METHOD or _integer(self.atr_period, path="protocol.model.atr_period", minimum=1) != APPROVED_ATR_PERIOD or _string(self.atr_seed, path="protocol.model.atr_seed") != APPROVED_ATR_SEED:
            raise ContractValidationError("ATR contract is not frozen Wilder RMA(14)/SMA")
        integer_expected = {
            "pivot_span_bars": APPROVED_PIVOT_SPAN,
            "break_confirm_closes": APPROVED_BREAK_CONFIRM_CLOSES,
            "max_age_bars": APPROVED_MAX_AGE,
            "max_active_zones": APPROVED_MAX_ACTIVE_ZONES,
            "outcome_start_offset_bars": APPROVED_OUTCOME_OFFSET,
            "outcome_horizon_bars": APPROVED_OUTCOME_HORIZON,
        }
        for name, expected in integer_expected.items():
            object.__setattr__(self, name, _integer(getattr(self, name), path=f"protocol.{name}", minimum=1))
            if getattr(self, name) != expected:
                raise ContractValidationError(f"protocol.{name} is not frozen")
        number_expected = {
            "zone_half_width_atr": APPROVED_ZONE_HALF_WIDTH,
            "merge_distance_atr": APPROVED_MERGE_DISTANCE,
            "touch_tolerance_atr": APPROVED_TOUCH_TOLERANCE,
            "break_buffer_atr": APPROVED_BREAK_BUFFER,
        }
        for name, expected in number_expected.items():
            value = _number(getattr(self, name), path=f"protocol.{name}", minimum=0.0)
            if value != expected:
                raise ContractValidationError(f"protocol.{name} is not frozen")
            object.__setattr__(self, name, value)
        if _string(self.window_policy, path="protocol.outcome.window_policy") != APPROVED_WINDOW_POLICY:
            raise ContractValidationError("unsupported outcome window policy")
        if type(self.folds) is not tuple or len(self.folds) != 6 or tuple(item.name for item in self.folds) != APPROVED_FOLD_NAMES or tuple((item.start, item.end) for item in self.folds) != APPROVED_FOLD_BOUNDS:
            raise ContractValidationError("folds do not match the frozen six-fold protocol")
        if type(self.case_order) is not tuple or self.case_order != APPROVED_CASE_ORDER:
            raise ContractValidationError("case ordering is not the approved deterministic order")
        if type(self.viewer) is not ViewerConfig or not self.viewer.attribution_logo or self.viewer.library != "lightweight-charts" or self.viewer.library_version != "5.2.0":
            raise ContractValidationError("viewer contract is not the approved pinned viewer")
        if _string(self.audit_status, path="audit_status") != APPROVED_AUDIT_STATUS:
            raise ContractValidationError("audit_status must be COMPLETE")
        object.__setattr__(self, "config_hash", deterministic_hash(self.to_payload()))

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "trial": {"trial_name": self.trial_name, "venue": self.venue, "asset": self.asset, "timeframe": self.timeframe, "purpose": self.purpose},
            "inputs": {
                "v19_config_path": self.v19_config_path,
                "v19_config_hash": self.v19_config_hash,
                "v19_bundle_path": self.v19_bundle_path,
                "v19_bundle_id": self.v19_bundle_id,
                "v19_study_id": self.v19_study_id,
                "v19_implementation_commit": self.v19_implementation_commit,
                "v19_disposition": self.v19_disposition,
                "v17_config_hash": self.v17_config_hash,
                "v17_source_bundle_id": self.v17_source_bundle_id,
                "v17_source_member_id": self.v17_source_member_id,
                "v17_evaluation_bundle_id": self.v17_evaluation_bundle_id,
                "v17_evaluation_id": self.v17_evaluation_id,
                "v18_config_hash": self.v18_config_hash,
                "v18_study_bundle_id": self.v18_study_bundle_id,
                "v18_study_id": self.v18_study_id,
                "v18_baseline_candidate_id": self.v18_baseline_candidate_id,
                "production_sr_config_hash": self.production_sr_config_hash,
                "frozen_input_hash": self.frozen_input_hash,
            },
            "protocol": {
                "source": {"row_count": self.source_row_count, "start": utc_isoformat(self.source_start), "end": utc_isoformat(self.source_end), "grid_policy": self.grid_policy},
                "model": {"atr_method": self.atr_method, "atr_period": self.atr_period, "atr_seed": self.atr_seed, "pivot_span_bars": self.pivot_span_bars, "zone_half_width_atr": self.zone_half_width_atr, "merge_distance_atr": self.merge_distance_atr, "touch_tolerance_atr": self.touch_tolerance_atr, "break_buffer_atr": self.break_buffer_atr, "break_confirm_closes": self.break_confirm_closes, "max_age_bars": self.max_age_bars, "max_active_zones": self.max_active_zones},
                "outcome": {"start_offset_bars": self.outcome_start_offset_bars, "horizon_bars": self.outcome_horizon_bars, "window_policy": self.window_policy},
                "folds": [item.to_payload() for item in self.folds],
                "case_order": list(self.case_order),
            },
            "viewer": self.viewer.to_payload(),
            "output": {"root": self.output_root},
            "audit_status": self.audit_status,
        }


def _parse_folds(raw: Any) -> tuple[CohortFold, ...]:
    if type(raw) is not list:
        raise ContractValidationError("protocol.folds must be a list")
    result: list[CohortFold] = []
    for index, item in enumerate(raw):
        mapping = _mapping(item, path=f"protocol.folds[{index}]")
        _exact(mapping, {"name", "start", "end"}, path=f"protocol.folds[{index}]")
        result.append(CohortFold(name=_string(mapping["name"], path=f"protocol.folds[{index}].name"), start=_utc(mapping["start"], path=f"protocol.folds[{index}].start"), end=_utc(mapping["end"], path=f"protocol.folds[{index}].end")))
    return tuple(result)


def _parse_viewer(raw: Any) -> ViewerConfig:
    mapping = _mapping(raw, path="viewer")
    expected = {"library", "library_version", "attribution_logo", "live_zone_extent", "show_terminal_by_default", "show_events_by_default", "background_color", "text_color", "grid_color", "support_border_color", "support_fill_color", "resistance_border_color", "resistance_fill_color", "pending_border_color", "terminal_opacity", "zone_line_width"}
    _exact(mapping, expected, path="viewer")
    return ViewerConfig(**dict(mapping))


def _parse_document(raw: Any) -> ContextAuditConfig:
    root = _mapping(raw, path="context audit config")
    _exact(root, {"version", "trial", "inputs", "protocol", "viewer", "output", "audit_status"}, path="context audit config")
    trial = _mapping(root["trial"], path="trial")
    _exact(trial, {"trial_name", "venue", "asset", "timeframe", "purpose"}, path="trial")
    inputs = _mapping(root["inputs"], path="inputs")
    _exact(inputs, {"v19", "upstream", "frozen"}, path="inputs")
    v19 = _mapping(inputs["v19"], path="inputs.v19")
    _exact(v19, {"config_path", "config_hash", "bundle_path", "bundle_id", "study_id", "implementation_commit", "disposition"}, path="inputs.v19")
    upstream = _mapping(inputs["upstream"], path="inputs.upstream")
    _exact(upstream, {"v17_config_hash", "v17_source_bundle_id", "v17_source_member_id", "v17_evaluation_bundle_id", "v17_evaluation_id", "v18_config_hash", "v18_study_bundle_id", "v18_study_id", "v18_baseline_candidate_id"}, path="inputs.upstream")
    frozen = _mapping(inputs["frozen"], path="inputs.frozen")
    _exact(frozen, {"production_sr_config_hash", "frozen_input_hash"}, path="inputs.frozen")
    protocol = _mapping(root["protocol"], path="protocol")
    _exact(protocol, {"source", "model", "outcome", "folds", "case_order"}, path="protocol")
    source = _mapping(protocol["source"], path="protocol.source")
    _exact(source, {"row_count", "start", "end", "grid_policy"}, path="protocol.source")
    model = _mapping(protocol["model"], path="protocol.model")
    _exact(model, {"atr_method", "atr_period", "atr_seed", "pivot_span_bars", "zone_half_width_atr", "merge_distance_atr", "touch_tolerance_atr", "break_buffer_atr", "break_confirm_closes", "max_age_bars", "max_active_zones"}, path="protocol.model")
    outcome = _mapping(protocol["outcome"], path="protocol.outcome")
    _exact(outcome, {"start_offset_bars", "horizon_bars", "window_policy"}, path="protocol.outcome")
    case_order = protocol["case_order"]
    if type(case_order) is not list:
        raise ContractValidationError("protocol.case_order must be a list")
    output = _mapping(root["output"], path="output")
    _exact(output, {"root"}, path="output")
    return ContextAuditConfig(
        version=root["version"], trial_name=trial["trial_name"], venue=trial["venue"], asset=trial["asset"], timeframe=trial["timeframe"], purpose=trial["purpose"],
        v19_config_path=v19["config_path"], v19_config_hash=v19["config_hash"], v19_bundle_path=v19["bundle_path"], v19_bundle_id=v19["bundle_id"], v19_study_id=v19["study_id"], v19_implementation_commit=v19["implementation_commit"], v19_disposition=v19["disposition"],
        v17_config_hash=upstream["v17_config_hash"], v17_source_bundle_id=upstream["v17_source_bundle_id"], v17_source_member_id=upstream["v17_source_member_id"], v17_evaluation_bundle_id=upstream["v17_evaluation_bundle_id"], v17_evaluation_id=upstream["v17_evaluation_id"], v18_config_hash=upstream["v18_config_hash"], v18_study_bundle_id=upstream["v18_study_bundle_id"], v18_study_id=upstream["v18_study_id"], v18_baseline_candidate_id=upstream["v18_baseline_candidate_id"], production_sr_config_hash=frozen["production_sr_config_hash"], frozen_input_hash=frozen["frozen_input_hash"],
        source_row_count=source["row_count"], source_start=_utc(source["start"], path="protocol.source.start"), source_end=_utc(source["end"], path="protocol.source.end"), grid_policy=source["grid_policy"],
        atr_method=model["atr_method"], atr_period=model["atr_period"], atr_seed=model["atr_seed"], pivot_span_bars=model["pivot_span_bars"], zone_half_width_atr=model["zone_half_width_atr"], merge_distance_atr=model["merge_distance_atr"], touch_tolerance_atr=model["touch_tolerance_atr"], break_buffer_atr=model["break_buffer_atr"], break_confirm_closes=model["break_confirm_closes"], max_age_bars=model["max_age_bars"], max_active_zones=model["max_active_zones"], outcome_start_offset_bars=outcome["start_offset_bars"], outcome_horizon_bars=outcome["horizon_bars"], window_policy=outcome["window_policy"], folds=_parse_folds(protocol["folds"]), case_order=tuple(case_order), viewer=_parse_viewer(root["viewer"]), output_root=output["root"], audit_status=root["audit_status"],
    )


def parse_context_audit_config(raw: Mapping[str, Any]) -> ContextAuditConfig:
    return _parse_document(raw)


def load_context_audit_config(path: str | Path) -> ContextAuditConfig:
    _reject_aliases(path)
    return _parse_document(load_sr_config(path))


load_config = load_context_audit_config


__all__ = ["ContextAuditConfig", "load_config", "load_context_audit_config", "parse_context_audit_config"]
