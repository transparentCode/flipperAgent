"""Small deterministic lane-local decision policies for D8.

Policies select existing model decisions.  They do not execute models, resolve
features/data, compare unrelated scores, publish, or mutate D6 state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from types import MappingProxyType
from typing import Literal

from apps.decision_app.domain.contracts import DecisionPolicyResult
from apps.decision_app.domain.identity import (
    compute_decision_execution_revision,
    decision_id,
)
from apps.decision_app.planning.planner import ResolvedLanePlan
from apps.decision_app.runtime.models import PreparedLaneExecution
from libs.contracts.decision import ModelDecision, require_utc

PolicyStatus = Literal["SIGNAL", "NO_SIGNAL", "BLOCKED", "INVALID"]
PolicyKind = Literal["passthrough", "priority"]


class DecisionPolicyError(ValueError):
    """Raised when policy configuration or evaluation evidence is invalid."""


def _require_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _ordered_unique(values: Sequence[str], *, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} must be a sequence of strings")
    normalized = tuple(_require_text(value, field_name=field_name) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicates")
    return normalized


def _conviction_threshold(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a numeric value")
    threshold = float(value)
    if not isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ValueError(f"{field_name} must be finite and between zero and one")
    return threshold


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionPolicyDefinition:
    """One explicit policy registration; no discovery or callable identity."""

    name: str
    version: str
    kind: PolicyKind

    def __post_init__(self) -> None:
        _require_text(self.name, field_name="policy name")
        _require_text(self.version, field_name="policy version")
        if self.kind not in {"passthrough", "priority"}:
            raise ValueError("policy kind is not supported")


class DecisionPolicyCatalog:
    """Exact deterministic catalog for approved policy definitions."""

    __slots__ = ("_definitions",)

    def __init__(self, definitions: Sequence[DecisionPolicyDefinition]) -> None:
        if isinstance(definitions, (str, bytes)):
            raise TypeError("policy definitions must be a sequence")
        normalized: dict[tuple[str, str], DecisionPolicyDefinition] = {}
        for definition in definitions:
            if not isinstance(definition, DecisionPolicyDefinition):
                raise TypeError("policy catalog requires policy definitions")
            key = (definition.name, definition.version)
            if key in normalized:
                raise ValueError(f"duplicate policy registration: {key}")
            normalized[key] = definition
        object.__setattr__(
            self,
            "_definitions",
            MappingProxyType(dict(sorted(normalized.items()))),
        )

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("DecisionPolicyCatalog is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("DecisionPolicyCatalog is immutable")

    def resolve(self, name: str, version: str) -> DecisionPolicyDefinition:
        key = (
            _require_text(name, field_name="policy name"),
            _require_text(version, field_name="policy version"),
        )
        try:
            return self._definitions[key]
        except KeyError as exc:
            raise DecisionPolicyError(
                f"unknown decision policy {key[0]}@{key[1]}"
            ) from exc


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionPolicyEvaluation:
    """Distinguish final no-signal from policy blockage or invalidity."""

    status: PolicyStatus
    result: DecisionPolicyResult | None = None
    selected_binding_id: str | None = None
    contributing_binding_ids: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"SIGNAL", "NO_SIGNAL", "BLOCKED", "INVALID"}:
            raise ValueError("policy evaluation status is not supported")
        if self.selected_binding_id is not None:
            _require_text(self.selected_binding_id, field_name="selected_binding_id")
        contributing = _ordered_unique(
            self.contributing_binding_ids,
            field_name="contributing_binding_ids",
        )
        object.__setattr__(self, "contributing_binding_ids", contributing)
        if self.reason is not None:
            _require_text(self.reason, field_name="policy reason")
        if self.status in {"BLOCKED", "INVALID"}:
            if self.result is not None:
                raise ValueError("blocked/invalid policy evaluation has no result")
        elif not isinstance(self.result, DecisionPolicyResult):
            raise ValueError("signal/no-signal evaluation requires a result")
        if (
            self.status == "SIGNAL"
            and self.result is not None
            and self.result.decision is None
        ):
            raise ValueError("SIGNAL evaluation requires a decision")
        if (
            self.status == "NO_SIGNAL"
            and self.result is not None
            and self.result.decision is not None
        ):
            raise ValueError("NO_SIGNAL evaluation must have no decision")


def _binding_by_slot(lane: ResolvedLanePlan, slot_name: str):
    try:
        return lane.bindings[slot_name]
    except KeyError as exc:
        raise DecisionPolicyError(f"unknown policy source slot: {slot_name}") from exc


def _result_for(
    lane: ResolvedLanePlan,
    prepared: PreparedLaneExecution,
    *,
    decision_ready_at: datetime,
    decision: ModelDecision | None,
    selected_binding_id: str | None,
    reason: str,
) -> DecisionPolicyResult:
    fingerprints = {
        slot_name: binding.binding_config_fingerprint
        for slot_name, binding in lane.bindings.items()
    }
    execution_revision = compute_decision_execution_revision(
        lane_id=lane.lane_id,
        base_lane_revision=lane.effective_lane_revision,
        feature_plan_fingerprint=prepared.identity.feature_plan_fingerprint,
        data_plan_fingerprint=prepared.identity.data_plan_fingerprint,
        policy_name=lane.policy_name,
        policy_version=lane.policy_version,
        policy_parameters=lane.policy_parameters,
    )
    return DecisionPolicyResult(
        lane_id=lane.lane_id,
        effective_lane_revision=lane.effective_lane_revision,
        base_lane_revision=lane.effective_lane_revision,
        decision_execution_revision=execution_revision,
        feature_plan_fingerprint=prepared.identity.feature_plan_fingerprint,
        data_plan_fingerprint=prepared.identity.data_plan_fingerprint,
        policy_name=lane.policy_name,
        policy_parameters=lane.policy_parameters,
        risk_profile_key=lane.risk_profile_key,
        decision_id=decision_id(
            lane_id=lane.lane_id,
            lane_revision=execution_revision,
            market_as_of=prepared.market_as_of,
        ),
        policy_version=lane.policy_version,
        market_as_of=prepared.market_as_of,
        decision_ready_at=decision_ready_at,
        decision=decision,
        binding_config_fingerprints=fingerprints,
        metadata={
            "selected_binding_id": selected_binding_id,
            "policy_reason": reason,
        },
    )


class DecisionPolicy:
    """Evaluate one resolved lane's already-prepared model outcomes."""

    def __init__(self, catalog: DecisionPolicyCatalog) -> None:
        if not isinstance(catalog, DecisionPolicyCatalog):
            raise TypeError("catalog must be DecisionPolicyCatalog")
        self._catalog = catalog

    def evaluate(
        self,
        lane: ResolvedLanePlan,
        prepared: PreparedLaneExecution,
        *,
        decision_ready_at: datetime,
    ) -> DecisionPolicyEvaluation:
        if not isinstance(lane, ResolvedLanePlan):
            raise TypeError("lane must be ResolvedLanePlan")
        if not isinstance(prepared, PreparedLaneExecution):
            raise TypeError("prepared must be PreparedLaneExecution")
        require_utc(decision_ready_at, field_name="decision_ready_at")
        if decision_ready_at < prepared.market_as_of:
            raise ValueError("decision_ready_at must be at or after market_as_of")
        if prepared.identity.lane_id != lane.lane_id:
            raise DecisionPolicyError("prepared lane identity does not match lane")
        if prepared.identity.effective_lane_revision != lane.effective_lane_revision:
            raise DecisionPolicyError("prepared base lane revision does not match lane")
        lane_binding_ids = {binding.binding_id for binding in lane.bindings.values()}
        if set(prepared.binding_results) != lane_binding_ids:
            raise DecisionPolicyError(
                "prepared binding results do not match resolved lane"
            )
        if not prepared.state_commit_eligible:
            return DecisionPolicyEvaluation(
                status="BLOCKED",
                reason="state_commit_not_eligible",
            )
        definition = self._catalog.resolve(lane.policy_name, lane.policy_version)
        try:
            if definition.kind == "passthrough":
                return self._evaluate_passthrough(
                    lane,
                    prepared,
                    decision_ready_at=decision_ready_at,
                )
            return self._evaluate_priority(
                lane,
                prepared,
                decision_ready_at=decision_ready_at,
            )
        except (DecisionPolicyError, TypeError, ValueError) as exc:
            return DecisionPolicyEvaluation(status="INVALID", reason=str(exc))

    def _evaluate_passthrough(
        self,
        lane: ResolvedLanePlan,
        prepared: PreparedLaneExecution,
        *,
        decision_ready_at: datetime,
    ) -> DecisionPolicyEvaluation:
        parameters = lane.policy_parameters
        source_slot = parameters.get("source_slot")
        if not isinstance(source_slot, str) or not source_slot.strip():
            raise DecisionPolicyError("passthrough requires source_slot")
        binding = _binding_by_slot(lane, source_slot)
        result = prepared.binding_results[binding.binding_id]
        if result.status == "INVALID":
            return DecisionPolicyEvaluation(status="INVALID", reason="source_invalid")
        if result.status != "EXECUTED":
            return DecisionPolicyEvaluation(
                status="BLOCKED",
                reason="source_unavailable",
            )
        assert result.outcome is not None
        decision = result.outcome.decision
        if decision is None or decision.direction_hint not in {-1, 1}:
            policy_result = _result_for(
                lane,
                prepared,
                decision_ready_at=decision_ready_at,
                decision=None,
                selected_binding_id=binding.binding_id,
                reason="no_tradable_decision",
            )
            return DecisionPolicyEvaluation(
                status="NO_SIGNAL",
                result=policy_result,
                selected_binding_id=binding.binding_id,
                contributing_binding_ids=(binding.binding_id,),
                reason="no_tradable_decision",
            )
        policy_result = _result_for(
            lane,
            prepared,
            decision_ready_at=decision_ready_at,
            decision=decision,
            selected_binding_id=binding.binding_id,
            reason="passthrough",
        )
        return DecisionPolicyEvaluation(
            status="SIGNAL",
            result=policy_result,
            selected_binding_id=binding.binding_id,
            contributing_binding_ids=(binding.binding_id,),
            reason="passthrough",
        )

    def _evaluate_priority(
        self,
        lane: ResolvedLanePlan,
        prepared: PreparedLaneExecution,
        *,
        decision_ready_at: datetime,
    ) -> DecisionPolicyEvaluation:
        parameters = lane.policy_parameters
        slots = _ordered_unique(
            parameters.get("source_slots", ()),
            field_name="priority source_slots",
        )
        if not slots:
            raise DecisionPolicyError("priority requires source_slots")
        global_threshold = parameters.get("min_conviction")
        if global_threshold is not None:
            global_threshold = _conviction_threshold(
                global_threshold,
                field_name="min_conviction",
            )
        per_slot = parameters.get("min_conviction_by_slot", {})
        if not isinstance(per_slot, Mapping):
            raise TypeError("min_conviction_by_slot must be a mapping")
        thresholds = {
            slot: _conviction_threshold(
                value, field_name=f"min_conviction_by_slot[{slot}]"
            )
            for slot, value in per_slot.items()
        }
        if not set(thresholds) <= set(slots):
            raise DecisionPolicyError(
                "min_conviction_by_slot contains a slot outside source_slots"
            )
        allow_unavailable = parameters.get("allow_unavailable_sources", False)
        if not isinstance(allow_unavailable, bool):
            raise TypeError("allow_unavailable_sources must be a bool")
        contributing: list[str] = []
        for slot in slots:
            binding = _binding_by_slot(lane, slot)
            result = prepared.binding_results[binding.binding_id]
            if result.status == "INVALID":
                return DecisionPolicyEvaluation(
                    status="INVALID",
                    reason=f"invalid_source:{slot}",
                )
            if result.status != "EXECUTED":
                if allow_unavailable:
                    continue
                return DecisionPolicyEvaluation(
                    status="BLOCKED",
                    reason=f"unavailable_source:{slot}",
                )
            assert result.outcome is not None
            decision = result.outcome.decision
            if decision is None:
                continue
            contributing.append(binding.binding_id)
            threshold = thresholds.get(slot, global_threshold)
            if threshold is not None and (
                decision.conviction is None or decision.conviction < threshold
            ):
                continue
            if decision.direction_hint not in {-1, 1}:
                continue
            policy_result = _result_for(
                lane,
                prepared,
                decision_ready_at=decision_ready_at,
                decision=decision,
                selected_binding_id=binding.binding_id,
                reason="priority",
            )
            return DecisionPolicyEvaluation(
                status="SIGNAL",
                result=policy_result,
                selected_binding_id=binding.binding_id,
                contributing_binding_ids=tuple(contributing),
                reason="priority",
            )
        policy_result = _result_for(
            lane,
            prepared,
            decision_ready_at=decision_ready_at,
            decision=None,
            selected_binding_id=None,
            reason="no_candidate",
        )
        return DecisionPolicyEvaluation(
            status="NO_SIGNAL",
            result=policy_result,
            contributing_binding_ids=tuple(contributing),
            reason="no_candidate",
        )


PASSTHROUGH_V1 = DecisionPolicyDefinition(
    name="passthrough",
    version="1",
    kind="passthrough",
)
PRIORITY_V1 = DecisionPolicyDefinition(
    name="priority",
    version="1",
    kind="priority",
)


__all__ = [
    "PASSTHROUGH_V1",
    "PRIORITY_V1",
    "DecisionPolicy",
    "DecisionPolicyCatalog",
    "DecisionPolicyDefinition",
    "DecisionPolicyError",
    "DecisionPolicyEvaluation",
]
