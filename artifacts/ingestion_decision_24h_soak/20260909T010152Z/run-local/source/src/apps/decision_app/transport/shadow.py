"""Non-authoritative, exact-ID shadow observation publication."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from apps.decision_app.domain.identity import sha256_fingerprint
from apps.decision_app.planning.planner import ResolvedLanePlan
from apps.decision_app.runtime.models import PreparedLaneExecution
from apps.decision_app.runtime.policy import DecisionPolicyEvaluation
from apps.decision_app.transport.live_input import (
    compare_stream_ids,
    normalize_stream_id,
)
from libs.contracts.decision import require_utc
from libs.contracts.serialization import valkey_decode, valkey_encode

ShadowPolicyStatus = Literal["SIGNAL", "NO_SIGNAL"]
ShadowPublicationOutcome = Literal[
    "PUBLISHED", "ALREADY_IDENTICAL", "CONFLICT", "FAILED"
]


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _required_identity(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"shadow D8 identity field {field_name} is required")
    return value


def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


class ShadowDecisionObservation(BaseModel):
    """Strict bounded evidence written only to a shadow stream."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["decision.shadow.v1"] = "decision.shadow.v1"
    lane_id: str
    asset: str
    decision_timeframe: str
    trigger_timeframe: str
    market_as_of: datetime
    decision_ready_at: datetime
    decision_id: str
    policy_status: ShadowPolicyStatus
    selected_binding_id: str | None = None
    direction_hint: int | None = None
    score: float | None = None
    conviction: float | None = None
    base_lane_revision: str
    decision_execution_revision: str
    feature_plan_fingerprint: str
    data_plan_fingerprint: str
    policy_name: str
    policy_version: str

    @field_validator(
        "lane_id",
        "asset",
        "decision_timeframe",
        "trigger_timeframe",
        "decision_id",
        "base_lane_revision",
        "decision_execution_revision",
        "feature_plan_fingerprint",
        "data_plan_fingerprint",
        "policy_name",
        "policy_version",
    )
    @classmethod
    def validate_text(cls, value: object, info: Any) -> str:
        return _text(value, info.field_name)

    @field_validator("market_as_of", "decision_ready_at")
    @classmethod
    def validate_utc(cls, value: datetime, info: Any) -> datetime:
        return require_utc(value, field_name=info.field_name)

    @field_validator("score")
    @classmethod
    def validate_score(cls, value: float | None) -> float | None:
        return None if value is None else _finite(value, "score")

    @field_validator("conviction")
    @classmethod
    def validate_conviction(cls, value: float | None) -> float | None:
        if value is None:
            return None
        result = _finite(value, "conviction")
        if not 0.0 <= result <= 1.0:
            raise ValueError("conviction must be between zero and one")
        return result

    @model_validator(mode="after")
    def validate_semantics(self) -> ShadowDecisionObservation:
        if self.decision_ready_at < self.market_as_of:
            raise ValueError("decision_ready_at must be at or after market_as_of")
        if self.direction_hint not in {-1, 0, 1, None}:
            raise ValueError("direction_hint must be -1, 0, 1, or None")
        if self.policy_status == "SIGNAL" and self.selected_binding_id is None:
            raise ValueError("SIGNAL shadow observation requires selected_binding_id")
        if self.policy_status == "NO_SIGNAL" and self.direction_hint is not None:
            raise ValueError("NO_SIGNAL shadow observation cannot carry direction")
        return self


@dataclass(frozen=True, slots=True, kw_only=True)
class ShadowPublicationEnvelope:
    """Canonical shadow observation plus its explicit transport identity."""

    decision_id: str
    stream_key: str
    stream_entry_id: str
    observation: ShadowDecisionObservation
    payload_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_id", _text(self.decision_id, "decision_id"))
        object.__setattr__(self, "stream_key", _text(self.stream_key, "stream_key"))
        object.__setattr__(
            self, "stream_entry_id", normalize_stream_id(self.stream_entry_id)
        )
        if not isinstance(self.observation, ShadowDecisionObservation):
            raise TypeError("observation must be ShadowDecisionObservation")
        object.__setattr__(
            self,
            "payload_fingerprint",
            _text(self.payload_fingerprint, "payload_fingerprint"),
        )
        if self.decision_id != self.observation.decision_id:
            raise ValueError("envelope decision_id must match observation")
        if self.stream_key != shadow_stream_key(self.observation.lane_id):
            raise ValueError("shadow stream key does not match lane")
        if self.stream_entry_id != shadow_stream_entry_id(
            self.observation.market_as_of
        ):
            raise ValueError("shadow stream entry ID does not match market_as_of")
        if self.payload_fingerprint != shadow_payload_fingerprint(self.observation):
            raise ValueError("payload_fingerprint does not match observation")


@dataclass(frozen=True, slots=True, kw_only=True)
class ShadowPublicationAck:
    """Transport acknowledgement for one shadow envelope."""

    decision_id: str
    stream_key: str
    stream_entry_id: str
    payload_fingerprint: str
    outcome: ShadowPublicationOutcome
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_id", _text(self.decision_id, "decision_id"))
        object.__setattr__(self, "stream_key", _text(self.stream_key, "stream_key"))
        object.__setattr__(
            self, "stream_entry_id", normalize_stream_id(self.stream_entry_id)
        )
        object.__setattr__(
            self,
            "payload_fingerprint",
            _text(self.payload_fingerprint, "payload_fingerprint"),
        )
        if self.outcome not in {"PUBLISHED", "ALREADY_IDENTICAL", "CONFLICT", "FAILED"}:
            raise ValueError("shadow publication outcome is not supported")
        if self.reason is not None:
            object.__setattr__(
                self, "reason", _text(self.reason, "shadow publication reason")
            )

    def validate_against(self, envelope: ShadowPublicationEnvelope) -> None:
        if not isinstance(envelope, ShadowPublicationEnvelope):
            raise TypeError("envelope must be ShadowPublicationEnvelope")
        if (
            self.decision_id,
            self.stream_key,
            self.stream_entry_id,
            self.payload_fingerprint,
        ) != (
            envelope.decision_id,
            envelope.stream_key,
            envelope.stream_entry_id,
            envelope.payload_fingerprint,
        ):
            raise ValueError("shadow acknowledgement does not match envelope")


def shadow_stream_key(lane_id: str) -> str:
    return f"decision:shadow:{_text(lane_id, 'lane_id')}"


def shadow_stream_entry_id(market_as_of: datetime) -> str:
    require_utc(market_as_of, field_name="market_as_of")
    return f"{int(market_as_of.timestamp() * 1000)}-0"


def shadow_payload_fingerprint(observation: ShadowDecisionObservation) -> str:
    if not isinstance(observation, ShadowDecisionObservation):
        raise TypeError("observation must be ShadowDecisionObservation")
    return sha256_fingerprint(observation.model_dump(mode="python"))


def build_shadow_envelope(
    lane: ResolvedLanePlan,
    prepared: PreparedLaneExecution,
    evaluation: DecisionPolicyEvaluation,
) -> ShadowPublicationEnvelope:
    if not isinstance(lane, ResolvedLanePlan):
        raise TypeError("lane must be ResolvedLanePlan")
    if not isinstance(prepared, PreparedLaneExecution):
        raise TypeError("prepared must be PreparedLaneExecution")
    if not isinstance(evaluation, DecisionPolicyEvaluation):
        raise TypeError("evaluation must be DecisionPolicyEvaluation")
    if lane.authority != "shadow":
        raise ValueError("only shadow lanes may build shadow observations")
    if evaluation.status not in {"SIGNAL", "NO_SIGNAL"} or evaluation.result is None:
        raise ValueError("shadow observation requires SIGNAL or NO_SIGNAL result")
    result = evaluation.result
    if result.lane_id != lane.lane_id or prepared.identity.lane_id != lane.lane_id:
        raise ValueError("shadow identity lane does not match")
    if result.market_as_of != prepared.market_as_of:
        raise ValueError("shadow cutoff does not match prepared execution")
    if not prepared.state_commit_eligible:
        raise ValueError("shadow prepared state is not commit eligible")
    decision = result.decision
    selected_id = (
        evaluation.selected_binding_id if evaluation.status == "SIGNAL" else None
    )
    if evaluation.status == "SIGNAL":
        if decision is None or selected_id is None:
            raise ValueError("shadow SIGNAL requires a selected decision")
        if decision.binding_id != selected_id:
            raise ValueError("shadow selected decision identity mismatch")
        if (
            decision.asset != lane.asset
            or decision.decision_timeframe != lane.decision_timeframe
        ):
            raise ValueError("shadow decision identity does not match lane")
        if decision.trigger_timeframe != lane.trigger_timeframe:
            raise ValueError("shadow decision trigger timeframe does not match lane")
    elif decision is not None or selected_id is not None:
        raise ValueError("shadow NO_SIGNAL cannot contain a decision")
    observation = ShadowDecisionObservation(
        lane_id=lane.lane_id,
        asset=lane.asset,
        decision_timeframe=lane.decision_timeframe,
        trigger_timeframe=lane.trigger_timeframe,
        market_as_of=result.market_as_of,
        decision_ready_at=result.decision_ready_at,
        decision_id=result.decision_id,
        policy_status=evaluation.status,
        selected_binding_id=selected_id,
        direction_hint=None if decision is None else decision.direction_hint,
        score=None if decision is None else decision.score,
        conviction=None if decision is None else decision.conviction,
        base_lane_revision=_required_identity(
            result.base_lane_revision, "base_lane_revision"
        ),
        decision_execution_revision=_required_identity(
            result.decision_execution_revision, "decision_execution_revision"
        ),
        feature_plan_fingerprint=_required_identity(
            result.feature_plan_fingerprint, "feature_plan_fingerprint"
        ),
        data_plan_fingerprint=_required_identity(
            result.data_plan_fingerprint, "data_plan_fingerprint"
        ),
        policy_name=_required_identity(result.policy_name, "policy_name"),
        policy_version=result.policy_version,
    )
    return ShadowPublicationEnvelope(
        decision_id=observation.decision_id,
        stream_key=shadow_stream_key(lane.lane_id),
        stream_entry_id=shadow_stream_entry_id(observation.market_as_of),
        observation=observation,
        payload_fingerprint=shadow_payload_fingerprint(observation),
    )


def validate_shadow_envelope_against(
    lane: ResolvedLanePlan,
    prepared: PreparedLaneExecution,
    evaluation: DecisionPolicyEvaluation,
    envelope: ShadowPublicationEnvelope,
) -> None:
    expected = build_shadow_envelope(lane, prepared, evaluation)
    if envelope != expected:
        raise ValueError("shadow envelope does not match canonical policy output")


class ShadowPublicationError(ValueError):
    """Raised when shadow transport evidence cannot be trusted."""


def _entry_parts(entry: object) -> tuple[str, Mapping[object, object]]:
    if not isinstance(entry, Sequence) or len(entry) != 2:
        raise ShadowPublicationError("Valkey stream entry must be an ID/fields pair")
    try:
        entry_id = normalize_stream_id(entry[0])
    except (TypeError, ValueError) as exc:
        raise ShadowPublicationError(f"invalid shadow stream entry ID: {exc}") from exc
    fields = entry[1]
    if not isinstance(fields, Mapping):
        raise ShadowPublicationError("shadow stream fields must be a mapping")
    return entry_id, fields


class ValkeyShadowPublisher:
    """Publish one shadow observation using deterministic exact-ID semantics."""

    def __init__(
        self, client: Any, *, stream_maxlen: int = 1000, stream_approximate: bool = True
    ) -> None:
        if client is None:
            raise TypeError("client is required")
        for name in ("xrange", "xrevrange", "xadd"):
            if not callable(getattr(client, name, None)):
                raise TypeError(f"client must provide {name}()")
        if (
            isinstance(stream_maxlen, bool)
            or not isinstance(stream_maxlen, int)
            or stream_maxlen <= 0
        ):
            raise ValueError("stream_maxlen must be a positive integer")
        if not isinstance(stream_approximate, bool):
            raise TypeError("stream_approximate must be bool")
        self._client = client
        self._stream_maxlen = stream_maxlen
        self._stream_approximate = stream_approximate

    async def publish(
        self, envelope: ShadowPublicationEnvelope
    ) -> ShadowPublicationAck:
        if not isinstance(envelope, ShadowPublicationEnvelope):
            raise TypeError("envelope must be ShadowPublicationEnvelope")
        required_id = envelope.stream_entry_id
        existing = await self._exact_entry(envelope.stream_key, required_id)
        if existing is not None:
            return self._ack_existing(envelope, existing)
        head = await self._stream_head(envelope.stream_key)
        if head is not None and compare_stream_ids(head, required_id) > 0:
            return self._ack(
                envelope, "CONFLICT", "shadow stream head advanced past required ID"
            )
        try:
            returned = await self._client.xadd(
                envelope.stream_key,
                valkey_encode(envelope.observation, inject_trace=False),
                id=required_id,
                maxlen=self._stream_maxlen,
                approximate=self._stream_approximate,
            )
            if normalize_stream_id(returned) != required_id:
                return self._ack(
                    envelope, "CONFLICT", "Valkey returned a different shadow ID"
                )
            return self._ack(envelope, "PUBLISHED", None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            existing = await self._exact_entry(envelope.stream_key, required_id)
            if existing is not None:
                return self._ack_existing(envelope, existing)
            head = await self._stream_head(envelope.stream_key)
            if head is not None and compare_stream_ids(head, required_id) > 0:
                return self._ack(
                    envelope, "CONFLICT", "shadow stream head advanced past required ID"
                )
            return self._ack(
                envelope, "FAILED", f"ambiguous shadow XADD failure: {exc}"
            )

    async def _exact_entry(
        self, stream_key: str, required_id: str
    ) -> tuple[str, Mapping[object, object]] | None:
        raw = await self._client.xrange(stream_key, required_id, required_id)
        if not raw:
            return None
        if not isinstance(raw, Sequence):
            raise ShadowPublicationError("XRANGE result must be a sequence")
        for entry in raw:
            entry_id, fields = _entry_parts(entry)
            if entry_id == required_id:
                return entry_id, fields
        return None

    async def _stream_head(self, stream_key: str) -> str | None:
        raw = await self._client.xrevrange(stream_key, "+", "-", count=1)
        if not raw:
            return None
        if not isinstance(raw, Sequence):
            raise ShadowPublicationError("XREVRANGE result must be a sequence")
        return _entry_parts(raw[0])[0]

    def _ack_existing(
        self,
        envelope: ShadowPublicationEnvelope,
        entry: tuple[str, Mapping[object, object]],
    ) -> ShadowPublicationAck:
        entry_id, fields = entry
        try:
            observation = valkey_decode(dict(fields), ShadowDecisionObservation)
            identical = (
                shadow_payload_fingerprint(observation) == envelope.payload_fingerprint
            )
        except Exception:  # noqa: BLE001
            identical = False
        return self._ack(
            envelope,
            "ALREADY_IDENTICAL" if identical else "CONFLICT",
            None
            if identical
            else f"existing entry {entry_id} differs or is undecodable",
        )

    @staticmethod
    def _ack(
        envelope: ShadowPublicationEnvelope,
        outcome: ShadowPublicationOutcome,
        reason: str | None,
    ) -> ShadowPublicationAck:
        return ShadowPublicationAck(
            decision_id=envelope.decision_id,
            stream_key=envelope.stream_key,
            stream_entry_id=envelope.stream_entry_id,
            payload_fingerprint=envelope.payload_fingerprint,
            outcome=outcome,
            reason=reason,
        )


__all__ = [
    "ShadowDecisionObservation",
    "ShadowPublicationAck",
    "ShadowPublicationEnvelope",
    "ShadowPublicationError",
    "ShadowPublicationOutcome",
    "ValkeyShadowPublisher",
    "build_shadow_envelope",
    "shadow_payload_fingerprint",
    "shadow_stream_entry_id",
    "shadow_stream_key",
    "validate_shadow_envelope_against",
]
