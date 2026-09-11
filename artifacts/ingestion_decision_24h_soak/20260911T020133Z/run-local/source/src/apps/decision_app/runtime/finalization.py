"""No-I/O D8 state, publication-ack, and lane-watermark finalization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from apps.decision_app.domain.contracts import (
    CommitDisposition,
    DecisionPolicyResult,
    LaneCommitWatermark,
)
from apps.decision_app.domain.identity import compute_decision_execution_revision
from apps.decision_app.domain.state import StateCommitReceipt
from apps.decision_app.domain.view import LaneMarketView
from apps.decision_app.planning.planner import ResolvedLanePlan
from apps.decision_app.runtime.models import (
    ModelRuntime,
    PreparedLaneExecution,
    StateTransactionError,
)
from apps.decision_app.runtime.policy import DecisionPolicyEvaluation
from apps.decision_app.transport.publication import (
    PublicationCompatibilityError,
    SignalPublicationAck,
    SignalPublicationEnvelope,
    validate_signal_envelope_against,
)
from apps.decision_app.transport.shadow import (
    ShadowPublicationAck,
    ShadowPublicationEnvelope,
    validate_shadow_envelope_against,
)
from libs.contracts.decision import require_utc

FinalizationStatus = Literal["COMMITTED", "ABORTED"]


class FinalizationError(ValueError):
    """Raised when a D8 disposition cannot be finalized safely."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FinalizationReceipt:
    """Evidence of a committed disposition or an aborted publication attempt."""

    status: FinalizationStatus
    lane_id: str
    market_as_of: datetime
    watermark: LaneCommitWatermark
    disposition: CommitDisposition | None = None
    state_commit_receipt: StateCommitReceipt | None = None
    envelope: SignalPublicationEnvelope | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        require_utc(self.market_as_of, field_name="market_as_of")
        if not isinstance(self.watermark, LaneCommitWatermark):
            raise TypeError("watermark must be LaneCommitWatermark")
        if self.status not in {"COMMITTED", "ABORTED"}:
            raise ValueError("finalization status is not supported")
        if self.watermark.lane_id != self.lane_id:
            raise ValueError("finalization watermark lane does not match")
        if self.status == "COMMITTED":
            if self.disposition not in {"published", "no_signal", "shadow"}:
                raise ValueError("committed finalization requires disposition")
            if not isinstance(self.state_commit_receipt, StateCommitReceipt):
                raise ValueError("committed finalization requires state receipt")
            if self.state_commit_receipt.identity.lane_id != self.lane_id:
                raise ValueError("state receipt lane does not match finalization")
            if self.state_commit_receipt.market_as_of != self.market_as_of:
                raise ValueError("state receipt cutoff does not match finalization")
            if self.state_commit_receipt.disposition != self.disposition:
                raise ValueError(
                    "state receipt disposition does not match finalization"
                )
            if self.watermark.latest_market_as_of != self.market_as_of:
                raise ValueError("watermark cutoff does not match finalization")
            if self.watermark.last_disposition != self.disposition:
                raise ValueError("watermark disposition does not match finalization")
            if self.disposition == "published" and not isinstance(
                self.envelope, SignalPublicationEnvelope
            ):
                raise ValueError("published finalization requires envelope")
            if (
                self.disposition in {"no_signal", "shadow"}
                and self.envelope is not None
            ):
                raise ValueError("no-signal finalization cannot have envelope")
        else:
            if self.disposition is not None:
                raise ValueError("aborted finalization cannot have disposition")
            if self.state_commit_receipt is not None:
                raise ValueError("aborted finalization cannot have state receipt")
            if self.watermark.latest_market_as_of is None:
                if self.watermark.last_disposition is not None:
                    raise ValueError("empty watermark cannot have disposition")
            elif self.watermark.latest_market_as_of >= self.market_as_of:
                raise ValueError(
                    "aborted finalization watermark claims attempted cutoff"
                )
        if self.reason is not None:
            if not isinstance(self.reason, str):
                raise TypeError("finalization reason must be a string")
            if not self.reason.strip():
                raise ValueError("finalization reason must be non-empty")


class LaneFinalizer:
    """Own one in-memory lane watermark after D6 commit authorization."""

    __slots__ = ("_lane", "_runtime", "_watermark")

    def __init__(
        self,
        lane: ResolvedLanePlan,
        runtime: ModelRuntime,
        watermark: LaneCommitWatermark | None = None,
    ) -> None:
        if not isinstance(lane, ResolvedLanePlan):
            raise TypeError("lane must be ResolvedLanePlan")
        if not isinstance(runtime, ModelRuntime):
            raise TypeError("runtime must be ModelRuntime")
        if runtime.lane.lane_id != lane.lane_id:
            raise ValueError("runtime lane does not match finalizer lane")
        if watermark is None:
            watermark = LaneCommitWatermark(lane_id=lane.lane_id)
        if not isinstance(watermark, LaneCommitWatermark):
            raise TypeError("watermark must be LaneCommitWatermark")
        if watermark.lane_id != lane.lane_id:
            raise ValueError("watermark lane does not match finalizer lane")
        self._lane = lane
        self._runtime = runtime
        self._watermark = watermark

    @property
    def watermark(self) -> LaneCommitWatermark:
        return self._watermark

    def preflight_signal(
        self,
        prepared: PreparedLaneExecution,
        evaluation: DecisionPolicyEvaluation,
        envelope: SignalPublicationEnvelope,
        *,
        lane_market_view: LaneMarketView,
    ) -> None:
        """Validate all pure state/envelope checks before D9 publication."""

        if not isinstance(evaluation, DecisionPolicyEvaluation):
            raise TypeError("evaluation must be DecisionPolicyEvaluation")
        if self._lane.authority != "authoritative":
            raise FinalizationError("signal preflight requires an authoritative lane")
        self._preflight(prepared, evaluation.result)
        if evaluation.status != "SIGNAL":
            raise FinalizationError("signal preflight requires policy SIGNAL")
        if not isinstance(envelope, SignalPublicationEnvelope):
            raise TypeError("envelope must be SignalPublicationEnvelope")
        if not isinstance(lane_market_view, LaneMarketView):
            raise TypeError("lane_market_view must be LaneMarketView")
        try:
            validate_signal_envelope_against(
                self._lane,
                prepared,
                evaluation,
                lane_market_view,
                envelope,
            )
        except (PublicationCompatibilityError, TypeError, ValueError) as exc:
            raise FinalizationError(str(exc)) from exc

    def finalize_no_signal(
        self,
        prepared: PreparedLaneExecution,
        evaluation: DecisionPolicyEvaluation,
    ) -> FinalizationReceipt:
        if not isinstance(evaluation, DecisionPolicyEvaluation):
            raise TypeError("evaluation must be DecisionPolicyEvaluation")
        if self._lane.authority != "authoritative":
            raise FinalizationError(
                "no-signal finalization requires an authoritative lane"
            )
        if evaluation.status != "NO_SIGNAL" or evaluation.result is None:
            raise FinalizationError("no-signal finalization requires policy NO_SIGNAL")
        self._preflight(prepared, evaluation.result)
        try:
            receipt = self._runtime.commit_prepared(prepared, "no_signal")
        except (StateTransactionError, TypeError, ValueError) as exc:
            raise FinalizationError(f"no-signal state commit failed: {exc}") from exc
        self._advance_watermark(prepared.market_as_of, "no_signal")
        return FinalizationReceipt(
            status="COMMITTED",
            lane_id=self._lane.lane_id,
            market_as_of=prepared.market_as_of,
            watermark=self._watermark,
            disposition="no_signal",
            state_commit_receipt=receipt,
        )

    def preflight_shadow(
        self,
        prepared: PreparedLaneExecution,
        evaluation: DecisionPolicyEvaluation,
        envelope: ShadowPublicationEnvelope,
    ) -> None:
        """Validate shadow identity and state before durable publication."""

        if not isinstance(evaluation, DecisionPolicyEvaluation):
            raise TypeError("evaluation must be DecisionPolicyEvaluation")
        if self._lane.authority != "shadow":
            raise FinalizationError("shadow preflight requires a shadow lane")
        if evaluation.status not in {"SIGNAL", "NO_SIGNAL"}:
            raise FinalizationError("shadow preflight requires SIGNAL or NO_SIGNAL")
        if not isinstance(envelope, ShadowPublicationEnvelope):
            raise TypeError("envelope must be ShadowPublicationEnvelope")
        self._preflight(prepared, evaluation.result)
        try:
            validate_shadow_envelope_against(
                self._lane,
                prepared,
                evaluation,
                envelope,
            )
        except (TypeError, ValueError) as exc:
            raise FinalizationError(str(exc)) from exc

    def finalize_signal(
        self,
        prepared: PreparedLaneExecution,
        evaluation: DecisionPolicyEvaluation,
        envelope: SignalPublicationEnvelope,
        acknowledgement: SignalPublicationAck,
        *,
        lane_market_view: LaneMarketView,
    ) -> FinalizationReceipt:
        if not isinstance(evaluation, DecisionPolicyEvaluation):
            raise TypeError("evaluation must be DecisionPolicyEvaluation")
        if evaluation.status != "SIGNAL" or evaluation.result is None:
            raise FinalizationError("signal finalization requires policy SIGNAL")
        if not isinstance(acknowledgement, SignalPublicationAck):
            raise TypeError("acknowledgement must be SignalPublicationAck")
        self.preflight_signal(
            prepared,
            evaluation,
            envelope,
            lane_market_view=lane_market_view,
        )
        try:
            acknowledgement.validate_against(envelope)
        except (PublicationCompatibilityError, TypeError, ValueError) as exc:
            raise FinalizationError(str(exc)) from exc
        if acknowledgement.outcome in {"CONFLICT", "FAILED"}:
            reason = acknowledgement.reason or acknowledgement.outcome.lower()
            try:
                self._runtime.abort_prepared(prepared, reason)
            except (StateTransactionError, TypeError, ValueError) as exc:
                raise FinalizationError(
                    f"publication failure abort failed: {exc}"
                ) from exc
            return FinalizationReceipt(
                status="ABORTED",
                lane_id=self._lane.lane_id,
                market_as_of=prepared.market_as_of,
                watermark=self._watermark,
                envelope=envelope,
                reason=reason,
            )
        try:
            receipt = self._runtime.commit_prepared(prepared, "published")
        except (StateTransactionError, TypeError, ValueError) as exc:
            raise FinalizationError(
                f"publication succeeded but state commit failed: {exc}"
            ) from exc
        self._advance_watermark(prepared.market_as_of, "published")
        return FinalizationReceipt(
            status="COMMITTED",
            lane_id=self._lane.lane_id,
            market_as_of=prepared.market_as_of,
            watermark=self._watermark,
            disposition="published",
            state_commit_receipt=receipt,
            envelope=envelope,
        )

    def finalize_shadow(
        self,
        prepared: PreparedLaneExecution,
        evaluation: DecisionPolicyEvaluation,
        envelope: ShadowPublicationEnvelope,
        acknowledgement: ShadowPublicationAck,
    ) -> FinalizationReceipt:
        """Finalize a non-authoritative observation after durable publication."""

        if not isinstance(evaluation, DecisionPolicyEvaluation):
            raise TypeError("evaluation must be DecisionPolicyEvaluation")
        if evaluation.status not in {"SIGNAL", "NO_SIGNAL"}:
            raise FinalizationError("shadow finalization requires SIGNAL or NO_SIGNAL")
        if not isinstance(acknowledgement, ShadowPublicationAck):
            raise TypeError("acknowledgement must be ShadowPublicationAck")
        if not isinstance(envelope, ShadowPublicationEnvelope):
            raise TypeError("envelope must be ShadowPublicationEnvelope")
        self.preflight_shadow(prepared, evaluation, envelope)
        try:
            acknowledgement.validate_against(envelope)
        except (TypeError, ValueError) as exc:
            raise FinalizationError(str(exc)) from exc
        if acknowledgement.outcome in {"CONFLICT", "FAILED"}:
            reason = acknowledgement.reason or acknowledgement.outcome.lower()
            try:
                self._runtime.abort_prepared(prepared, reason)
            except (StateTransactionError, TypeError, ValueError) as exc:
                raise FinalizationError(
                    f"shadow publication failure abort failed: {exc}"
                ) from exc
            return FinalizationReceipt(
                status="ABORTED",
                lane_id=self._lane.lane_id,
                market_as_of=prepared.market_as_of,
                watermark=self._watermark,
                reason=reason,
            )
        try:
            receipt = self._runtime.commit_prepared(prepared, "shadow")
        except (StateTransactionError, TypeError, ValueError) as exc:
            raise FinalizationError(
                f"shadow publication succeeded but state commit failed: {exc}"
            ) from exc
        self._advance_watermark(prepared.market_as_of, "shadow")
        return FinalizationReceipt(
            status="COMMITTED",
            lane_id=self._lane.lane_id,
            market_as_of=prepared.market_as_of,
            watermark=self._watermark,
            disposition="shadow",
            state_commit_receipt=receipt,
        )

    def abort_policy_failure(
        self,
        prepared: PreparedLaneExecution,
        evaluation: DecisionPolicyEvaluation,
    ) -> FinalizationReceipt:
        if not isinstance(evaluation, DecisionPolicyEvaluation):
            raise TypeError("evaluation must be DecisionPolicyEvaluation")
        if evaluation.status not in {"BLOCKED", "INVALID"}:
            raise FinalizationError("abort_policy_failure requires BLOCKED or INVALID")
        reason = evaluation.reason or evaluation.status.lower()
        try:
            self._runtime.abort_prepared(prepared, reason)
        except (StateTransactionError, TypeError, ValueError) as exc:
            raise FinalizationError(f"policy failure abort failed: {exc}") from exc
        return FinalizationReceipt(
            status="ABORTED",
            lane_id=self._lane.lane_id,
            market_as_of=prepared.market_as_of,
            watermark=self._watermark,
            reason=reason,
        )

    def _preflight(
        self,
        prepared: PreparedLaneExecution,
        result: DecisionPolicyResult | None,
    ) -> None:
        if not isinstance(prepared, PreparedLaneExecution):
            raise TypeError("prepared must be PreparedLaneExecution")
        if result is None:
            raise FinalizationError("finalization requires a policy result")
        if result.lane_id != self._lane.lane_id:
            raise FinalizationError("policy result lane does not match finalizer")
        if result.market_as_of != prepared.market_as_of:
            raise FinalizationError("policy result cutoff does not match prepared")
        if prepared.identity.effective_lane_revision != (
            self._lane.effective_lane_revision
        ):
            raise FinalizationError("prepared base revision does not match lane")
        if result.effective_lane_revision != self._lane.effective_lane_revision:
            raise FinalizationError("policy result base revision does not match lane")
        if result.base_lane_revision != self._lane.effective_lane_revision:
            raise FinalizationError("policy result base lane revision does not match")
        if (
            result.feature_plan_fingerprint
            != prepared.identity.feature_plan_fingerprint
        ):
            raise FinalizationError(
                "policy feature fingerprint does not match prepared"
            )
        if result.data_plan_fingerprint != prepared.identity.data_plan_fingerprint:
            raise FinalizationError("policy data fingerprint does not match prepared")
        if result.policy_name != self._lane.policy_name:
            raise FinalizationError("policy result name does not match lane")
        if result.policy_version != self._lane.policy_version:
            raise FinalizationError("policy result version does not match lane")
        if result.policy_parameters != self._lane.policy_parameters:
            raise FinalizationError("policy result parameters do not match lane")
        expected_fingerprints = {
            slot: binding.binding_config_fingerprint
            for slot, binding in self._lane.bindings.items()
        }
        if set(prepared.binding_results) != {
            binding.binding_id for binding in self._lane.bindings.values()
        }:
            raise FinalizationError(
                "prepared binding results do not match resolved lane"
            )
        if dict(result.binding_config_fingerprints) != expected_fingerprints:
            raise FinalizationError(
                "policy result binding fingerprints do not cover the lane"
            )
        expected_revision = compute_decision_execution_revision(
            lane_id=self._lane.lane_id,
            base_lane_revision=self._lane.effective_lane_revision,
            feature_plan_fingerprint=prepared.identity.feature_plan_fingerprint,
            data_plan_fingerprint=prepared.identity.data_plan_fingerprint,
            policy_name=self._lane.policy_name,
            policy_version=self._lane.policy_version,
            policy_parameters=self._lane.policy_parameters,
        )
        if result.decision_execution_revision != expected_revision:
            raise FinalizationError("policy result execution revision is stale")
        if self._watermark.latest_market_as_of is not None and (
            prepared.market_as_of <= self._watermark.latest_market_as_of
        ):
            raise FinalizationError("finalization cutoff does not advance watermark")
        try:
            self._runtime.validate_prepared_commit(prepared)
        except (StateTransactionError, TypeError, ValueError) as exc:
            raise FinalizationError(f"prepared commit preflight failed: {exc}") from exc

    def _advance_watermark(
        self,
        market_as_of: datetime,
        disposition: CommitDisposition,
    ) -> None:
        self._watermark = LaneCommitWatermark(
            lane_id=self._lane.lane_id,
            latest_market_as_of=market_as_of,
            last_disposition=disposition,
        )


__all__ = [
    "FinalizationError",
    "FinalizationReceipt",
    "LaneFinalizer",
]
