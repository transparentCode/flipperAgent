"""Strict, immutable V1.9 trial configuration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
import re
from typing import Any

from libs.models.sr.adapters.yaml_config import load_sr_config
from libs.models.sr.domain.contracts import ContractValidationError, ZoneSide, ZoneStatus
from libs.models.sr.domain.identity import require_utc
from libs.models.sr.research.windows.folds import CohortFold

from .contracts import (
    AdequacyThresholds,
    BaselineAdequacyConfig,
    BaselineAdequacyDisposition,
    ControlEligibilityReason,
)


_ROOT_KEYS = {"version", "trial", "inputs", "source", "baseline", "protocol", "controls", "gates", "dispositions", "output"}
_TRIAL_KEYS = {"trial_name", "venue", "asset", "timeframe"}
_INPUT_KEYS = {
    "v17_config_path", "v17_config_hash", "source_bundle_path", "source_bundle_id", "source_implementation_commit",
    "v17_evaluation_bundle_path", "v17_evaluation_bundle_id", "v17_evaluation_id", "v17_evaluation_implementation_commit",
    "v18_config_path", "v18_study_bundle_path", "v18_study_bundle_id", "v18_study_id", "v18_config_hash", "v18_implementation_commit",
    "sr_config_path", "input_config_path", "frozen_sr_config_hash", "frozen_input_hash",
}
_SOURCE_KEYS = {"row_count", "start", "end", "grid_policy"}
_BASELINE_KEYS = {
    "pivot_span_bars", "zone_half_width_atr", "merge_distance_atr", "touch_tolerance_atr", "break_buffer_atr",
    "break_confirm_closes", "max_age_bars", "max_active_zones", "atr_method", "atr_period", "atr_seed", "common_start_period",
}
_PROTOCOL_KEYS = {"outcome", "folds", "visibility"}
_OUTCOME_KEYS = {"start_offset_bars", "horizon_bars", "window_policy"}
_VISIBILITY_KEYS = {"entry_visible_states", "intersection_policy", "previous_snapshot_policy"}
_CONTROL_KEYS = {"side_order", "controls_per_anchor", "control_id_schema_version", "rejection_reason_precedence"}
_GATE_KEYS = set(AdequacyThresholds.__dataclass_fields__)
_HASH_OR_COMMIT = re.compile(r"[0-9a-f]{40,64}")


def _mapping(value: Any, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ContractValidationError(f"{path} must be a mapping with string keys")
    return value


def _exact(value: Mapping[str, Any], expected: set[str], *, path: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ContractValidationError(f"{path} keys mismatch; missing={sorted(expected - actual)} unknown={sorted(actual - expected)}")


def _string(value: Any, *, path: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContractValidationError(f"{path} must be a non-empty string")
    return value


def _integer(value: Any, *, path: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or type(value) is not int or value < minimum:
        raise ContractValidationError(f"{path} must be an integer >= {minimum}")
    return value


def _utc(value: Any, *, path: str, daily: bool = True) -> datetime:
    value = _string(value, path=path)
    if not value.endswith("Z"):
        raise ContractValidationError(f"{path} must use strict UTC Z notation")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        parsed = require_utc(parsed, field_name=path)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"{path} must be a valid UTC timestamp") from exc
    if daily and (parsed.hour or parsed.minute or parsed.second or parsed.microsecond):
        raise ContractValidationError(f"{path} must align to a UTC daily boundary")
    return parsed


def _reject_aliases(path: str | Path) -> None:
    """Reject YAML anchors, aliases, and merge keys before adapter loading.

    V1.9 config contains no scalar values requiring ``&`` or ``*``.  Rejecting
    these tokens at the boundary keeps merge/alias expansion from becoming an
    implicit configuration layer while leaving YAML parsing isolated in the
    shared adapter.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContractValidationError(f"cannot read V1.9 config: {path}") from exc
    for line in text.splitlines():
        if re.match(r"^\s*<<\s*:", line) or re.search(r"(?:^|[\s\[,])(?:&|\*)[A-Za-z_][A-Za-z0-9_.-]*", line):
            raise ContractValidationError("V1.9 YAML aliases and merge keys are forbidden")


def _parse_folds(raw: Any) -> tuple[CohortFold, ...]:
    if type(raw) is not list:
        raise ContractValidationError("protocol.folds must be a list")
    folds: list[CohortFold] = []
    for index, item in enumerate(raw):
        mapping = _mapping(item, path=f"protocol.folds[{index}]")
        if set(mapping) != {"name", "start", "end"}:
            raise ContractValidationError(f"protocol.folds[{index}] keys mismatch")
        folds.append(CohortFold(name=_string(mapping["name"], path=f"protocol.folds[{index}].name"), start=_utc(mapping["start"], path=f"protocol.folds[{index}].start"), end=_utc(mapping["end"], path=f"protocol.folds[{index}].end")))
    return tuple(folds)


def _parse_document(raw: Any) -> BaselineAdequacyConfig:
    root = _mapping(raw, path="baseline adequacy config")
    _exact(root, _ROOT_KEYS, path="baseline adequacy config")
    trial = _mapping(root["trial"], path="trial")
    _exact(trial, _TRIAL_KEYS, path="trial")
    inputs = _mapping(root["inputs"], path="inputs")
    _exact(inputs, _INPUT_KEYS, path="inputs")
    source = _mapping(root["source"], path="source")
    _exact(source, _SOURCE_KEYS, path="source")
    baseline = _mapping(root["baseline"], path="baseline")
    _exact(baseline, _BASELINE_KEYS, path="baseline")
    protocol = _mapping(root["protocol"], path="protocol")
    _exact(protocol, _PROTOCOL_KEYS, path="protocol")
    outcome = _mapping(protocol["outcome"], path="protocol.outcome")
    _exact(outcome, _OUTCOME_KEYS, path="protocol.outcome")
    visibility = _mapping(protocol["visibility"], path="protocol.visibility")
    _exact(visibility, _VISIBILITY_KEYS, path="protocol.visibility")
    controls = _mapping(root["controls"], path="controls")
    _exact(controls, _CONTROL_KEYS, path="controls")
    gates = _mapping(root["gates"], path="gates")
    _exact(gates, _GATE_KEYS, path="gates")
    dispositions = root["dispositions"]
    if type(dispositions) is not list:
        raise ContractValidationError("dispositions must be a list")
    output = _mapping(root["output"], path="output")
    _exact(output, {"root"}, path="output")

    states = visibility["entry_visible_states"]
    sides = controls["side_order"]
    reasons = controls["rejection_reason_precedence"]
    if type(states) is not list or type(sides) is not list or type(reasons) is not list:
        raise ContractValidationError("visibility/control enum fields must be lists")
    try:
        parsed_states = tuple(ZoneStatus(_string(item, path="protocol.visibility.entry_visible_states[]")) for item in states)
        parsed_sides = tuple(ZoneSide(_string(item, path="controls.side_order[]")) for item in sides)
        parsed_reasons = tuple(ControlEligibilityReason(_string(item, path="controls.rejection_reason_precedence[]")) for item in reasons)
        parsed_dispositions = tuple(BaselineAdequacyDisposition(_string(item, path="dispositions[]")) for item in dispositions)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError("unsupported V1.9 enum value") from exc

    return BaselineAdequacyConfig(
        version=root["version"], trial_name=trial["trial_name"], venue=trial["venue"], asset=trial["asset"], timeframe=trial["timeframe"],
        v17_config_path=inputs["v17_config_path"], v17_config_hash=inputs["v17_config_hash"], source_bundle_path=inputs["source_bundle_path"], source_bundle_id=inputs["source_bundle_id"], source_implementation_commit=inputs["source_implementation_commit"],
        v17_evaluation_bundle_path=inputs["v17_evaluation_bundle_path"], v17_evaluation_bundle_id=inputs["v17_evaluation_bundle_id"], v17_evaluation_id=inputs["v17_evaluation_id"], v17_evaluation_implementation_commit=inputs["v17_evaluation_implementation_commit"],
        v18_config_path=inputs["v18_config_path"], v18_study_bundle_path=inputs["v18_study_bundle_path"], v18_study_bundle_id=inputs["v18_study_bundle_id"], v18_study_id=inputs["v18_study_id"], v18_config_hash=inputs["v18_config_hash"], v18_implementation_commit=inputs["v18_implementation_commit"],
        sr_config_path=inputs["sr_config_path"], input_config_path=inputs["input_config_path"], frozen_sr_config_hash=inputs["frozen_sr_config_hash"], frozen_input_hash=inputs["frozen_input_hash"],
        source_row_count=source["row_count"], source_start=_utc(source["start"], path="source.start"), source_end=_utc(source["end"], path="source.end"), grid_policy=source["grid_policy"],
        pivot_span_bars=baseline["pivot_span_bars"], zone_half_width_atr=baseline["zone_half_width_atr"], merge_distance_atr=baseline["merge_distance_atr"], touch_tolerance_atr=baseline["touch_tolerance_atr"], break_buffer_atr=baseline["break_buffer_atr"], break_confirm_closes=baseline["break_confirm_closes"], max_age_bars=baseline["max_age_bars"], max_active_zones=baseline["max_active_zones"], atr_method=baseline["atr_method"], atr_period=baseline["atr_period"], atr_seed=baseline["atr_seed"], common_start_period=baseline["common_start_period"],
        outcome_start_offset_bars=outcome["start_offset_bars"], outcome_horizon_bars=outcome["horizon_bars"], window_policy=outcome["window_policy"], folds=_parse_folds(protocol["folds"]), entry_visible_states=parsed_states, intersection_policy=visibility["intersection_policy"], previous_snapshot_policy=visibility["previous_snapshot_policy"], control_side_order=parsed_sides, controls_per_anchor=controls["controls_per_anchor"], control_id_schema_version=controls["control_id_schema_version"], rejection_reason_precedence=parsed_reasons, gates=AdequacyThresholds(**dict(gates)), dispositions=parsed_dispositions, output_root=output["root"],
    )


def parse_baseline_adequacy_config(raw: Mapping[str, Any]) -> BaselineAdequacyConfig:
    return _parse_document(raw)


def load_baseline_adequacy_config(path: str | Path) -> BaselineAdequacyConfig:
    _reject_aliases(path)
    return _parse_document(load_sr_config(path))


load_config = load_baseline_adequacy_config


__all__ = ["load_baseline_adequacy_config", "load_config", "parse_baseline_adequacy_config"]
