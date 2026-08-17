from __future__ import annotations

import copy
import json

import pytest

from apps.decision_app.domain.market_state import MarketSeriesKey
from apps.decision_app.transport.ingestion import (
    CanonicalIngestionEventError,
    parse_canonical_ingestion_event,
)
from scripts.certify_ingestion_decision_momentum_c1 import ARTIFACT, _serialized
from tests.combined.c1_harness import (
    _ROUTE_NAMES,
    _sha256,
    c1_evidence_payload,
    c1_identity_payload,
    evaluate_c1_gates,
    load_fixture_config,
    run_c1_certification,
    run_cross_route_isolation,
    run_live_transition,
    run_outbox_retry,
    run_recovery_flow,
    run_restart_parity,
    terminal_status_for_gates,
)


@pytest.mark.asyncio
async def test_real_producer_to_consumer_live_stitch_has_three_isolated_routes() -> (
    None
):
    evidence = await run_live_transition()

    assert evidence["startup_status"] == "STARTUP_READY"
    assert evidence["producer_consumer_stream_key_parity"] is True
    assert evidence["parsed_event_count"] == 6
    assert evidence["derived_entry_counts"] == {
        "BTCUSDT/1h": 4,
        "BTCUSDT/4h": 1,
        "ETHUSDT/4h": 1,
    }
    assert evidence["expected_derived_entry_counts"] == evidence["derived_entry_counts"]
    assert evidence["producer_derived_stream_keys"] == evidence["expected_stream_keys"]
    assert evidence["parsed_event_contract_valid"] is True
    assert evidence["parsed_derived_provenance_summary"] == {
        route: [
            {
                "source_type": "derived",
                "source_provider": None,
                "source_timeframe": "1m",
            }
        ]
        for route in ("BTCUSDT/1h", "BTCUSDT/4h", "ETHUSDT/4h")
    }
    assert len(evidence["input_dispositions"]) == 6
    assert {item["disposition"] for item in evidence["input_dispositions"]} == {
        "INSERTED"
    }
    assert set(evidence["routes"]) == set(_ROUTE_NAMES)
    assert evidence["no_base_signal"] is True
    assert evidence["signal_entry_count"] >= 1
    assert all(
        item["finalization_status"] == "COMMITTED"
        for item in evidence["lane_results"].values()
    )


@pytest.mark.asyncio
async def test_producer_payload_mutation_fails_canonical_decision_parser() -> None:
    evidence = await run_live_transition()
    config = load_fixture_config()

    # The success path above parses the exact OutboxPublisher fields.  This
    # negative check deliberately mutates one field after producer creation.
    assert evidence["parsed_event_count"] > 0

    key = MarketSeriesKey(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        timeframe="1h",
    )
    stream = f"stream:ohlcv:ingestion:{key.venue}:{key.instrument_id}:{key.timeframe}"
    fields = {
        "event_id": "c1-negative",
        "event_type": "not-candle",
        "schema_version": "1",
        "producer": "ingestion",
        "occurred_at": "2026-01-01T00:00:00Z",
        "payload": json.dumps({"venue": key.venue}),
    }
    with pytest.raises(CanonicalIngestionEventError):
        parse_canonical_ingestion_event(
            stream_key=stream,
            stream_id="1-0",
            fields=fields,
            expected_series=key,
            timeframe_grid=config.timeframe_grid,
        )


@pytest.mark.asyncio
async def test_outbox_at_least_once_retry_has_one_decision_effect() -> None:
    evidence = await run_outbox_retry()

    assert evidence["event_id_present"] is True
    assert evidence["retry_same_event_id"] is True
    assert len(evidence["producer_stream_ids"]) == 2
    assert evidence["input_dispositions"] == ["INSERTED", "DUPLICATE"]
    assert evidence["transaction_count"] == 1
    assert evidence["signal_count"] == 1


@pytest.mark.asyncio
async def test_recovery_blocks_htf_then_converges_before_decision_advances() -> None:
    evidence = await run_recovery_flow()

    assert evidence["request_count"] == 1
    assert evidence["request_reason"] == "htf_incomplete:4h"
    assert evidence["premature_derived_count"] == 0
    assert evidence["provider_calls"] == 1
    assert evidence["recovered_base_count"] == 1
    assert evidence["follow_ups"] == 0
    assert evidence["derived_identity"]["source_type"] == "derived"
    assert evidence["derived_identity"]["source_timeframe"] == "1m"
    assert evidence["derived_identity"]["close"] == "178.3"
    assert evidence["uninterrupted_reference_equal"] is True
    assert evidence["recovered"] == evidence["uninterrupted_reference"]
    assert any(
        result["finalization_status"] == "COMMITTED"
        for result in evidence["decision_lane_results"].values()
    )


@pytest.mark.asyncio
async def test_restart_from_same_producer_history_matches_continuous_runtime() -> None:
    evidence = await run_restart_parity()

    assert evidence["first_startup"] == "STARTUP_READY"
    assert evidence["fresh_startup"] == "STARTUP_READY"
    assert evidence["fresh_startup_publication_count"] == 0
    assert evidence["same_lane_results"] is True
    assert evidence["same_input_cutoffs"] is True
    assert evidence["same_feature_momentum_semantics"] is True
    assert evidence["same_signal_identities"] is True


@pytest.mark.asyncio
async def test_eth_only_perturbation_leaves_btc_routes_unchanged() -> None:
    evidence = await run_cross_route_isolation()

    assert evidence["perturbed_route"] == "ETHUSDT/4h"
    assert evidence["unchanged_routes"] == [
        "BTCUSDT:momentum_1h",
        "BTCUSDT:momentum_4h",
    ]
    assert evidence["unchanged"] is True
    assert evidence["btc_transactions_absent"] is True


@pytest.mark.asyncio
async def test_c1_artifact_gates_are_fail_closed_and_deterministic() -> None:
    first = await run_c1_certification()
    second = await run_c1_certification()

    assert first == second
    assert first["terminal_status"] == (
        "INGESTION_DECISION_C1_DETERMINISTIC_STITCH_REMEDIATION_READY_FOR_REVIEW"
    )
    assert all(first["gates"].values())
    assert first["gates"] == evaluate_c1_gates(first)
    assert terminal_status_for_gates(first["gates"]) == first["terminal_status"]
    assert c1_identity_payload(first) != c1_evidence_payload(first)
    assert first["identity_digest"] != first["evidence_digest"]
    assert ARTIFACT.read_bytes() == _serialized(first)

    tampered_count = copy.deepcopy(first)
    tampered_count["live"]["derived_entry_counts"]["BTCUSDT/4h"] = 99
    count_gates = evaluate_c1_gates(tampered_count)
    assert count_gates["htf_materialization_exact"] is False

    tampered_retry = copy.deepcopy(first)
    tampered_retry["at_least_once_retry"]["transaction_count"] = 2
    retry_gates = evaluate_c1_gates(tampered_retry)
    assert retry_gates["outbox_retry_one_logical_effect"] is False

    tampered_recovery = copy.deepcopy(first)
    tampered_recovery["recovery"]["recovered"]["derived_candle"]["close"] = "999"
    recovery_gates = evaluate_c1_gates(tampered_recovery)
    assert recovery_gates["recovery_blocks_then_converges"] is False

    tampered_restart = copy.deepcopy(first)
    tampered_restart["restart"]["fresh_input_cutoffs"]["tampered"] = "future"
    restart_gates = evaluate_c1_gates(tampered_restart)
    assert restart_gates["restart_reconstruction_parity"] is False

    tampered_routes = copy.deepcopy(first)
    tampered_routes["cross_route_isolation"]["after"]["BTCUSDT:momentum_1h"][
        "semantic"
    ]["parity"] = False
    route_gates = evaluate_c1_gates(tampered_routes)
    assert route_gates["cross_route_isolation"] is False

    tampered_signal = copy.deepcopy(first)
    tampered_signal["live"]["signal_entry_count"] = 0
    signal_gates = evaluate_c1_gates(tampered_signal)
    assert signal_gates["real_signal_committed"] is False
    assert terminal_status_for_gates(signal_gates) == (
        "INGESTION_DECISION_C1_EVIDENCE_INSUFFICIENT"
    )

    evidence_digest_before = first["evidence_digest"]
    identity_digest_before = first["identity_digest"]
    assert c1_identity_payload(tampered_count) == c1_identity_payload(first)
    assert c1_evidence_payload(tampered_count) != c1_evidence_payload(first)
    assert _sha256(c1_identity_payload(tampered_count)) == identity_digest_before
    assert _sha256(c1_evidence_payload(tampered_count)) != evidence_digest_before
