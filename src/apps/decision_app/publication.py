"""Pure downstream compatibility envelopes for the future D9 publisher."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from typing import Literal

from apps.decision_app.identity import (
    compute_decision_execution_revision,
    sha256_fingerprint,
)
from apps.decision_app.model_runtime import PreparedLaneExecution
from apps.decision_app.planner import ResolvedLanePlan
from apps.decision_app.policy import DecisionPolicyEvaluation
from apps.decision_app.view import LaneMarketView
from libs.contracts.signal import TradeSignal

PublicationOutcome = Literal["PUBLISHED", "ALREADY_IDENTICAL", "CONFLICT", "FAILED"]


class PublicationCompatibilityError(ValueError):
    """Raised when a downstream compatibility envelope or acknowledgement is invalid."""


def _require_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _finite_positive(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not isfinite(result) or result <= 0:
        raise ValueError(f"{field_name} must be finite and positive")
    return result


def _finite_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


@dataclass(frozen=True, slots=True, kw_only=True)
class SignalPublicationEnvelope:
    """One deterministic signal payload handed to the future D9 publisher."""

    decision_id: str
    stream_key: str
    stream_entry_id: str
    signal: TradeSignal
    payload_fingerprint: str

    def __post_init__(self) -> None:
        for field_name in ("decision_id", "stream_key", "stream_entry_id"):
            _require_text(getattr(self, field_name), field_name=field_name)
        if not isinstance(self.signal, TradeSignal):
            raise TypeError("signal must be TradeSignal")
        _require_text(self.payload_fingerprint, field_name="payload_fingerprint")
        expected = signal_payload_fingerprint(self.signal)
        if expected != self.payload_fingerprint:
            raise ValueError("payload_fingerprint does not match signal payload")
        if self.signal.idempotency_key != signal_idempotency_key(self.decision_id):
            raise ValueError("signal idempotency_key does not match decision_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class SignalPublicationAck:
    """Pure acknowledgement supplied by D9 after its transport operation."""

    decision_id: str
    stream_key: str
    stream_entry_id: str
    payload_fingerprint: str
    outcome: PublicationOutcome
    reason: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "decision_id",
            "stream_key",
            "stream_entry_id",
            "payload_fingerprint",
        ):
            _require_text(getattr(self, field_name), field_name=field_name)
        if self.outcome not in {
            "PUBLISHED",
            "ALREADY_IDENTICAL",
            "CONFLICT",
            "FAILED",
        }:
            raise ValueError("publication outcome is not supported")
        if self.reason is not None:
            _require_text(self.reason, field_name="publication reason")

    def validate_against(self, envelope: SignalPublicationEnvelope) -> None:
        if not isinstance(envelope, SignalPublicationEnvelope):
            raise TypeError("envelope must be SignalPublicationEnvelope")
        if (
            self.decision_id != envelope.decision_id
            or self.stream_key != envelope.stream_key
            or self.stream_entry_id != envelope.stream_entry_id
            or self.payload_fingerprint != envelope.payload_fingerprint
        ):
            raise PublicationCompatibilityError(
                "publication acknowledgement does not match envelope"
            )


def signal_idempotency_key(decision_id: str) -> str:
    """Derive the D8 signal idempotency identity from the final decision ID."""

    _require_text(decision_id, field_name="decision_id")
    return sha256_fingerprint(
        {"identity": "decision-signal", "version": "1", "decision_id": decision_id}
    )


def signal_payload_fingerprint(signal: TradeSignal) -> str:
    if not isinstance(signal, TradeSignal):
        raise TypeError("signal must be TradeSignal")
    return sha256_fingerprint(signal.model_dump(mode="python"))


def build_signal_envelope(
    lane: ResolvedLanePlan,
    prepared: PreparedLaneExecution,
    evaluation: DecisionPolicyEvaluation,
    lane_market_view: LaneMarketView,
) -> SignalPublicationEnvelope:
    """Build a pure legacy TradeSignal envelope for one authoritative SIGNAL."""

    if not isinstance(lane, ResolvedLanePlan):
        raise TypeError("lane must be ResolvedLanePlan")
    if not isinstance(prepared, PreparedLaneExecution):
        raise TypeError("prepared must be PreparedLaneExecution")
    if not isinstance(evaluation, DecisionPolicyEvaluation):
        raise TypeError("evaluation must be DecisionPolicyEvaluation")
    if not isinstance(lane_market_view, LaneMarketView):
        raise TypeError("lane_market_view must be LaneMarketView")
    if lane.authority != "authoritative":
        raise PublicationCompatibilityError(
            "only authoritative lanes may create signal envelopes"
        )
    if evaluation.status != "SIGNAL" or evaluation.result is None:
        raise PublicationCompatibilityError("signal envelope requires policy SIGNAL")
    result = evaluation.result
    decision = result.decision
    selected_id = evaluation.selected_binding_id
    if decision is None or selected_id is None:
        raise PublicationCompatibilityError("SIGNAL must identify a selected decision")
    if result.lane_id != lane.lane_id or prepared.identity.lane_id != lane.lane_id:
        raise PublicationCompatibilityError("policy/prepared lane identity mismatch")
    if prepared.identity.effective_lane_revision != lane.effective_lane_revision:
        raise PublicationCompatibilityError(
            "prepared base revision does not match lane"
        )
    if set(prepared.binding_results) != {
        binding.binding_id for binding in lane.bindings.values()
    }:
        raise PublicationCompatibilityError(
            "prepared binding results do not match resolved lane"
        )
    if result.market_as_of != prepared.market_as_of:
        raise PublicationCompatibilityError(
            "policy cutoff does not match prepared cutoff"
        )
    if not prepared.state_commit_eligible:
        raise PublicationCompatibilityError(
            "signal prepared state is not commit eligible"
        )
    if result.effective_lane_revision != lane.effective_lane_revision:
        raise PublicationCompatibilityError("policy base revision does not match lane")
    if result.base_lane_revision != lane.effective_lane_revision:
        raise PublicationCompatibilityError(
            "policy base lane revision does not match lane"
        )
    if result.feature_plan_fingerprint != prepared.identity.feature_plan_fingerprint:
        raise PublicationCompatibilityError("policy feature fingerprint does not match")
    if result.data_plan_fingerprint != prepared.identity.data_plan_fingerprint:
        raise PublicationCompatibilityError("policy data fingerprint does not match")
    if (
        result.policy_name != lane.policy_name
        or result.policy_version != lane.policy_version
    ):
        raise PublicationCompatibilityError("policy identity does not match lane")
    if result.policy_parameters != lane.policy_parameters:
        raise PublicationCompatibilityError("policy parameters do not match lane")
    expected_revision = compute_decision_execution_revision(
        lane_id=lane.lane_id,
        base_lane_revision=lane.effective_lane_revision,
        feature_plan_fingerprint=prepared.identity.feature_plan_fingerprint,
        data_plan_fingerprint=prepared.identity.data_plan_fingerprint,
        policy_name=lane.policy_name,
        policy_version=lane.policy_version,
        policy_parameters=lane.policy_parameters,
    )
    if result.decision_execution_revision != expected_revision:
        raise PublicationCompatibilityError("policy execution revision is stale")
    expected_fingerprints = {
        slot: binding.binding_config_fingerprint
        for slot, binding in lane.bindings.items()
    }
    if dict(result.binding_config_fingerprints) != expected_fingerprints:
        raise PublicationCompatibilityError(
            "policy binding fingerprints are incomplete"
        )
    if result.risk_profile_key != lane.risk_profile_key:
        raise PublicationCompatibilityError("policy risk profile does not match lane")
    if lane_market_view.lane_id != lane.lane_id:
        raise PublicationCompatibilityError("market view lane does not match lane")
    if lane_market_view.market_as_of != result.market_as_of:
        raise PublicationCompatibilityError(
            "market view cutoff does not match decision"
        )
    if lane_market_view.decision_timeframe != lane.decision_timeframe:
        raise PublicationCompatibilityError("market view timeframe does not match lane")
    binding = next(
        (
            candidate
            for candidate in lane.bindings.values()
            if candidate.binding_id == selected_id
        ),
        None,
    )
    if binding is None:
        raise PublicationCompatibilityError("selected binding is not in resolved lane")
    binding_result = prepared.binding_results.get(selected_id)
    if binding_result is None or binding_result.status != "EXECUTED":
        raise PublicationCompatibilityError("selected binding was not executed")
    if binding_result.outcome is None or binding_result.outcome.decision != decision:
        raise PublicationCompatibilityError(
            "selected decision is not the executed outcome"
        )
    if (
        decision.binding_id != selected_id
        or decision.market_as_of != result.market_as_of
    ):
        raise PublicationCompatibilityError("selected decision identity mismatch")
    if decision.direction_hint not in {-1, 1}:
        raise PublicationCompatibilityError("SIGNAL direction must be -1 or 1")
    if decision.conviction is None:
        raise PublicationCompatibilityError(
            "selected decision conviction is required for publication"
        )
    if lane.risk_profile_key is None:
        raise PublicationCompatibilityError(
            "authoritative lane requires risk_profile_key"
        )
    contributing_bindings = []
    for contributing_id in evaluation.contributing_binding_ids:
        if contributing_id not in prepared.binding_results:
            raise PublicationCompatibilityError(
                "contributing binding is not in prepared results"
            )
        contributing_binding = next(
            (
                candidate
                for candidate in lane.bindings.values()
                if candidate.binding_id == contributing_id
            ),
            None,
        )
        if contributing_binding is None:
            raise PublicationCompatibilityError(
                "contributing binding is not in resolved lane"
            )
        contributing_bindings.append(contributing_binding)

    price = _finite_number(
        lane_market_view.decision_bar.close, field_name="decision price"
    )
    bar_high = _finite_number(lane_market_view.decision_bar.high, field_name="bar high")
    bar_low = _finite_number(lane_market_view.decision_bar.low, field_name="bar low")
    metadata: dict[str, object] = {
        "timestamp_unit": "seconds",
        "market_as_of_utc": result.market_as_of.isoformat().replace("+00:00", "Z"),
        "decision_id": result.decision_id,
        "decision_execution_revision": result.decision_execution_revision,
        "base_lane_revision": result.base_lane_revision,
        "feature_plan_fingerprint": result.feature_plan_fingerprint,
        "data_plan_fingerprint": result.data_plan_fingerprint,
        "risk_profile_key": lane.risk_profile_key,
        "policy_name": lane.policy_name,
        "policy_version": lane.policy_version,
        "selected_binding_id": selected_id,
        "selected_slot": binding.slot_name,
        "selected_plugin_name": binding.plugin_name,
        "selected_plugin_version": binding.plugin_version,
        "contributing_binding_ids": evaluation.contributing_binding_ids,
        "contributing_plugin_names": tuple(
            candidate.plugin_name for candidate in contributing_bindings
        ),
        "bar_high": bar_high,
        "bar_low": bar_low,
    }
    feature_binding = prepared.feature_resolution.bindings.get(selected_id)
    if feature_binding is not None and "ATR" in feature_binding.features:
        metadata["ATR"] = _finite_positive(
            feature_binding.features["ATR"].value,
            field_name="ATR feature",
        )

    signal = TradeSignal(
        asset=lane.asset,
        timeframe=lane.decision_timeframe,
        timestamp=result.market_as_of.timestamp(),
        direction=decision.direction_hint,
        conviction=_finite_number(decision.conviction, field_name="conviction"),
        price=price,
        idempotency_key=signal_idempotency_key(result.decision_id),
        model_name=lane.risk_profile_key,
        metadata=metadata,
    )
    stream_key = f"signals:{lane.asset}:{lane.decision_timeframe}"
    stream_entry_id = f"{int(result.market_as_of.timestamp() * 1000)}-0"
    return SignalPublicationEnvelope(
        decision_id=result.decision_id,
        stream_key=stream_key,
        stream_entry_id=stream_entry_id,
        signal=signal,
        payload_fingerprint=signal_payload_fingerprint(signal),
    )


def validate_signal_envelope_against(
    lane: ResolvedLanePlan,
    prepared: PreparedLaneExecution,
    evaluation: DecisionPolicyEvaluation,
    lane_market_view: LaneMarketView,
    envelope: SignalPublicationEnvelope,
) -> None:
    """Require an envelope to equal the canonical D8-derived envelope."""

    if not isinstance(envelope, SignalPublicationEnvelope):
        raise TypeError("envelope must be SignalPublicationEnvelope")
    expected = build_signal_envelope(
        lane,
        prepared,
        evaluation,
        lane_market_view,
    )
    if envelope != expected:
        raise PublicationCompatibilityError(
            "publication envelope does not match canonical decision output"
        )


__all__ = [
    "PublicationCompatibilityError",
    "PublicationOutcome",
    "SignalPublicationAck",
    "SignalPublicationEnvelope",
    "build_signal_envelope",
    "signal_idempotency_key",
    "signal_payload_fingerprint",
    "validate_signal_envelope_against",
]
