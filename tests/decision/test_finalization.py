from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from apps.decision_app.runtime.finalization import (
    FinalizationError,
    FinalizationReceipt,
    LaneFinalizer,
)
from apps.decision_app.runtime.models import RewarmStep, StateTransactionError
from apps.decision_app.runtime.policy import (
    PASSTHROUGH_V1,
    DecisionPolicy,
    DecisionPolicyCatalog,
)
from apps.decision_app.transport.publication import (
    SignalPublicationAck,
    build_signal_envelope,
    signal_payload_fingerprint,
)
from apps.decision_app.transport.shadow import (
    ShadowPublicationAck,
    build_shadow_envelope,
)
from tests.decision.test_publication_compat import _prepared_signal
from tests.decision.test_real_sr_plugin import (
    SR_ATR_HISTORY_BARS,
    _lane_and_runtime,
    _view,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ("PUBLISHED", "ALREADY_IDENTICAL"))
async def test_successful_publication_ack_commits_then_advances_watermark(
    outcome: str,
) -> None:
    bundle, view, prepared, evaluation = await _prepared_signal()
    envelope = build_signal_envelope(bundle.lane, prepared, evaluation, view)
    acknowledgement = SignalPublicationAck(
        decision_id=envelope.decision_id,
        stream_key=envelope.stream_key,
        stream_entry_id=envelope.stream_entry_id,
        payload_fingerprint=envelope.payload_fingerprint,
        outcome=outcome,
    )

    finalizer = LaneFinalizer(bundle.lane, bundle.runtime)
    receipt = finalizer.finalize_signal(
        prepared,
        evaluation,
        envelope,
        acknowledgement,
        lane_market_view=view,
    )

    assert receipt.status == "COMMITTED"
    assert receipt.disposition == "published"
    assert receipt.watermark.latest_market_as_of == view.market_as_of
    assert receipt.watermark.last_disposition == "published"
    assert finalizer.watermark == receipt.watermark


@pytest.mark.asyncio
async def test_shadow_no_signal_requires_shadow_evidence_and_commits_shadow() -> None:
    bundle, _view, prepared, evaluation = await _prepared_signal(
        direction=None,
        conviction=None,
        authority="shadow",
        risk_profile_key=None,
    )
    assert evaluation.status == "NO_SIGNAL"
    envelope = build_shadow_envelope(bundle.lane, prepared, evaluation)
    acknowledgement = ShadowPublicationAck(
        decision_id=envelope.decision_id,
        stream_key=envelope.stream_key,
        stream_entry_id=envelope.stream_entry_id,
        payload_fingerprint=envelope.payload_fingerprint,
        outcome="PUBLISHED",
    )
    finalizer = LaneFinalizer(bundle.lane, bundle.runtime)

    receipt = finalizer.finalize_shadow(
        prepared,
        evaluation,
        envelope,
        acknowledgement,
    )

    assert receipt.status == "COMMITTED"
    assert receipt.disposition == "shadow"
    assert receipt.watermark.last_disposition == "shadow"


@pytest.mark.asyncio
async def test_shadow_lane_cannot_use_authoritative_no_signal_finalizer() -> None:
    bundle, _view, prepared, evaluation = await _prepared_signal(
        direction=None,
        conviction=None,
        authority="shadow",
        risk_profile_key=None,
    )
    finalizer = LaneFinalizer(bundle.lane, bundle.runtime)
    records_before = bundle.runtime.state_store.records

    with pytest.raises(FinalizationError, match="authoritative"):
        finalizer.finalize_no_signal(prepared, evaluation)

    assert finalizer.watermark.latest_market_as_of is None
    assert bundle.runtime.state_store.records == records_before


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ("FAILED", "CONFLICT"))
async def test_shadow_publication_failure_aborts_without_commit(
    outcome: str,
) -> None:
    bundle, _view, prepared, evaluation = await _prepared_signal(
        authority="shadow",
        risk_profile_key=None,
    )
    envelope = build_shadow_envelope(bundle.lane, prepared, evaluation)
    acknowledgement = ShadowPublicationAck(
        decision_id=envelope.decision_id,
        stream_key=envelope.stream_key,
        stream_entry_id=envelope.stream_entry_id,
        payload_fingerprint=envelope.payload_fingerprint,
        outcome=outcome,
        reason="shadow transport test",
    )
    finalizer = LaneFinalizer(bundle.lane, bundle.runtime)

    receipt = finalizer.finalize_shadow(
        prepared,
        evaluation,
        envelope,
        acknowledgement,
    )

    assert receipt.status == "ABORTED"
    assert finalizer.watermark.latest_market_as_of is None


@pytest.mark.asyncio
async def test_authoritative_lane_cannot_finalize_shadow_evidence() -> None:
    bundle, _view, prepared, evaluation = await _prepared_signal()
    with pytest.raises(ValueError, match="shadow lanes"):
        build_shadow_envelope(bundle.lane, prepared, evaluation)


@pytest.mark.asyncio
async def test_shadow_and_authoritative_commit_dispositions_are_guarded() -> None:
    shadow_bundle, _view, shadow_prepared, _evaluation = await _prepared_signal(
        direction=None,
        conviction=None,
        authority="shadow",
        risk_profile_key=None,
    )
    with pytest.raises(StateTransactionError, match="shadow lane"):
        shadow_bundle.runtime.commit_prepared(shadow_prepared, "no_signal")

    (
        authoritative_bundle,
        _view,
        authoritative_prepared,
        _evaluation,
    ) = await _prepared_signal()
    with pytest.raises(StateTransactionError, match="authoritative lane"):
        authoritative_bundle.runtime.commit_prepared(
            authoritative_prepared,
            "shadow",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ("CONFLICT", "FAILED"))
async def test_failed_publication_aborts_and_leaves_watermark_unchanged(
    outcome: str,
) -> None:
    bundle, view, prepared, evaluation = await _prepared_signal()
    envelope = build_signal_envelope(bundle.lane, prepared, evaluation, view)
    acknowledgement = SignalPublicationAck(
        decision_id=envelope.decision_id,
        stream_key=envelope.stream_key,
        stream_entry_id=envelope.stream_entry_id,
        payload_fingerprint=envelope.payload_fingerprint,
        outcome=outcome,
        reason="publisher boundary test",
    )

    finalizer = LaneFinalizer(bundle.lane, bundle.runtime)
    receipt = finalizer.finalize_signal(
        prepared,
        evaluation,
        envelope,
        acknowledgement,
        lane_market_view=view,
    )

    assert receipt.status == "ABORTED"
    assert receipt.watermark.latest_market_as_of is None
    assert finalizer.watermark.latest_market_as_of is None


@pytest.mark.asyncio
async def test_ack_mismatch_fails_before_commit_or_watermark_advance() -> None:
    bundle, view, prepared, evaluation = await _prepared_signal()
    envelope = build_signal_envelope(bundle.lane, prepared, evaluation, view)
    acknowledgement = SignalPublicationAck(
        decision_id=envelope.decision_id,
        stream_key=envelope.stream_key,
        stream_entry_id=envelope.stream_entry_id,
        payload_fingerprint="0" * 64,
        outcome="PUBLISHED",
    )
    finalizer = LaneFinalizer(bundle.lane, bundle.runtime)

    with pytest.raises(FinalizationError, match="does not match"):
        finalizer.finalize_signal(
            prepared,
            evaluation,
            envelope,
            acknowledgement,
            lane_market_view=view,
        )
    assert finalizer.watermark.latest_market_as_of is None


@pytest.mark.asyncio
async def test_real_sr_analytical_no_signal_commits_encoded_state_and_watermark() -> (
    None
):
    runtime, lane, view_builder, store, bars = _lane_and_runtime(
        policy_name="passthrough",
        policy_parameters={"source_slot": "sr_primary"},
    )
    key = store.series_keys[0]
    replay_bars = bars[SR_ATR_HISTORY_BARS - 1 : SR_ATR_HISTORY_BARS + 4]
    steps = []
    for bar in replay_bars:
        if store.latest_cutoff(key) != bar.market_as_of:
            store.append(key, bar)
        steps.append(
            RewarmStep(
                lane_market_view=_view(view_builder, lane, bar),
                resolver_knowledge_cutoff=bar.market_as_of,
            )
        )
    await runtime.rewarm(tuple(steps))

    binding_id = next(iter(lane.bindings.values())).binding_id
    previous = runtime.state_store.get(binding_id)
    next_bar = bars[SR_ATR_HISTORY_BARS + 4]
    store.append(key, next_bar)
    view = _view(view_builder, lane, next_bar)
    prepared = await runtime.prepare_live(
        view,
        resolver_knowledge_cutoff=next_bar.market_as_of,
    )
    evaluation = DecisionPolicy(DecisionPolicyCatalog([PASSTHROUGH_V1])).evaluate(
        lane,
        prepared,
        decision_ready_at=next_bar.market_as_of,
    )
    assert evaluation.status == "NO_SIGNAL"
    assert evaluation.result is not None
    assert evaluation.result.decision is None

    receipt = LaneFinalizer(lane, runtime).finalize_no_signal(
        prepared,
        evaluation,
    )
    current = runtime.state_store.get(binding_id)
    assert receipt.status == "COMMITTED"
    assert receipt.envelope is None
    assert receipt.watermark.last_disposition == "no_signal"
    assert receipt.watermark.latest_market_as_of == next_bar.market_as_of
    assert current.committed_market_as_of == next_bar.market_as_of
    assert current.committed_state != previous.committed_state


@pytest.mark.asyncio
async def test_state_commit_ineligible_blocks_policy_and_cannot_finalize() -> None:
    runtime, lane, view_builder, _store, bars = _lane_and_runtime(
        policy_name="passthrough",
        policy_parameters={"source_slot": "sr_primary"},
    )
    first_live_bar = bars[SR_ATR_HISTORY_BARS - 1]
    view = _view(view_builder, lane, first_live_bar)
    prepared = await runtime.prepare_live(
        view,
        resolver_knowledge_cutoff=first_live_bar.market_as_of,
    )
    assert prepared.state_commit_eligible is False
    evaluation = DecisionPolicy(DecisionPolicyCatalog([PASSTHROUGH_V1])).evaluate(
        lane,
        prepared,
        decision_ready_at=first_live_bar.market_as_of,
    )
    assert evaluation.status == "BLOCKED"
    finalizer = LaneFinalizer(lane, runtime)
    receipt = finalizer.abort_policy_failure(prepared, evaluation)
    assert receipt.status == "ABORTED"
    assert finalizer.watermark.latest_market_as_of is None


@pytest.mark.asyncio
async def test_finalizer_rejects_a_cutoff_that_does_not_advance_watermark() -> None:
    bundle, view, prepared, evaluation = await _prepared_signal()
    envelope = build_signal_envelope(bundle.lane, prepared, evaluation, view)
    acknowledgement = SignalPublicationAck(
        decision_id=envelope.decision_id,
        stream_key=envelope.stream_key,
        stream_entry_id=envelope.stream_entry_id,
        payload_fingerprint=envelope.payload_fingerprint,
        outcome="PUBLISHED",
    )
    finalizer = LaneFinalizer(bundle.lane, bundle.runtime)
    finalizer.finalize_signal(
        prepared,
        evaluation,
        envelope,
        acknowledgement,
        lane_market_view=view,
    )

    with pytest.raises(FinalizationError):
        finalizer.finalize_signal(
            prepared,
            evaluation,
            envelope,
            acknowledgement,
            lane_market_view=view,
        )


@pytest.mark.asyncio
async def test_forged_self_consistent_envelope_cannot_commit_or_advance_watermark() -> (
    None
):
    bundle, view, prepared, evaluation = await _prepared_signal()
    state_before = bundle.runtime.state_store.records
    canonical = build_signal_envelope(bundle.lane, prepared, evaluation, view)
    forged_signal = canonical.signal.model_copy(
        update={"asset": "ETHUSDT", "timeframe": "4h"}
    )
    forged = replace(
        canonical,
        stream_key="signals:ETHUSDT:4h",
        signal=forged_signal,
        payload_fingerprint=signal_payload_fingerprint(forged_signal),
    )
    acknowledgement = SignalPublicationAck(
        decision_id=forged.decision_id,
        stream_key=forged.stream_key,
        stream_entry_id=forged.stream_entry_id,
        payload_fingerprint=forged.payload_fingerprint,
        outcome="PUBLISHED",
    )
    finalizer = LaneFinalizer(bundle.lane, bundle.runtime)

    with pytest.raises(FinalizationError, match="canonical"):
        finalizer.finalize_signal(
            prepared,
            evaluation,
            forged,
            acknowledgement,
            lane_market_view=view,
        )

    assert finalizer.watermark.latest_market_as_of is None
    assert bundle.runtime.state_store.records == state_before


@pytest.mark.asyncio
async def test_finalization_receipt_rejects_contradictory_committed_evidence() -> None:
    bundle, view, prepared, evaluation = await _prepared_signal()
    envelope = build_signal_envelope(bundle.lane, prepared, evaluation, view)
    acknowledgement = SignalPublicationAck(
        decision_id=envelope.decision_id,
        stream_key=envelope.stream_key,
        stream_entry_id=envelope.stream_entry_id,
        payload_fingerprint=envelope.payload_fingerprint,
        outcome="PUBLISHED",
    )
    finalizer = LaneFinalizer(bundle.lane, bundle.runtime)
    receipt = finalizer.finalize_signal(
        prepared,
        evaluation,
        envelope,
        acknowledgement,
        lane_market_view=view,
    )

    with pytest.raises(ValueError, match="state receipt cutoff"):
        FinalizationReceipt(
            status="COMMITTED",
            lane_id=receipt.lane_id,
            market_as_of=view.market_as_of + timedelta(hours=1),
            watermark=receipt.watermark,
            disposition=receipt.disposition,
            state_commit_receipt=receipt.state_commit_receipt,
            envelope=receipt.envelope,
        )

    with pytest.raises(ValueError, match="watermark disposition"):
        FinalizationReceipt(
            status="COMMITTED",
            lane_id=receipt.lane_id,
            market_as_of=receipt.market_as_of,
            watermark=replace(receipt.watermark, last_disposition="no_signal"),
            disposition=receipt.disposition,
            state_commit_receipt=receipt.state_commit_receipt,
            envelope=receipt.envelope,
        )
