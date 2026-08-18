from __future__ import annotations

import copy
import os

import pytest

from tests.combined.c3b2_harness import (
    C3B2_SUCCESS_STATUS,
    EXPECTED_PROTECTED_HASHES,
    evaluate_c3b2_gates,
    evidence_payload,
    identity_payload,
    load_artifact,
    protected_hashes,
    run_certification,
    sha256_fingerprint,
    write_artifact,
)


def test_c3b2_artifact_has_expected_routes_and_protected_hashes() -> None:
    evidence = load_artifact()
    assert evidence["routes"] == ["BTCUSDT/1h", "BTCUSDT/4h", "ETHUSDT/4h"]
    assert evidence["protected_hashes"] == EXPECTED_PROTECTED_HASHES
    assert set(evidence["protected_hashes"]) == set(EXPECTED_PROTECTED_HASHES)
    assert protected_hashes() == EXPECTED_PROTECTED_HASHES
    assert evidence["public_provider_calls"] == 0


def test_c3b2_gates_recompute_from_raw_evidence() -> None:
    evidence = load_artifact()
    assert all(evaluate_c3b2_gates(evidence).values())
    mutations = (
        (
            "c2_hash",
            lambda value: value["protected_hashes"].update(c2="forged"),
            "protected_hashes",
        ),
        (
            "c3a_hash",
            lambda value: value["protected_hashes"].update(c3a="forged"),
            "protected_hashes",
        ),
        (
            "c3b1_hash",
            lambda value: value["protected_hashes"].update(c3b1="forged"),
            "protected_hashes",
        ),
        (
            "provider_order",
            lambda value: value["recovery_config"].update(
                provider_order=["ccxt_binance", "binance_native"]
            ),
            "recovery_config_contract",
        ),
        (
            "primary_attempts",
            lambda value: value["trials"][0]["A"]["provider_call_counts"].update(
                binance_native=1
            ),
            "primary_failure_fallback_converges",
        ),
        (
            "fallback_after_conflict",
            lambda value: value["trials"][0]["D"]["provider_call_counts"].update(
                ccxt_binance=1
            ),
            "primary_conflict_stops_without_fallback",
        ),
        (
            "overlap_outbox",
            lambda value: value["trials"][0]["B"]["recovery_outbox"].update(
                published=5
            ),
            "partial_primary_overlap_fallback_converges",
        ),
        (
            "disagreement_row",
            lambda value: value["trials"][0]["E"]["missing_rows"].update({"100": None}),
            "fallback_content_disagreement_fail_closed",
        ),
        (
            "transport_duplicate",
            lambda value: value["trials"][0]["F"]["statuses"].__setitem__(
                1, "INSERTED"
            ),
            "ws_rest_disagreement_canonical_first_write_fail_closed",
        ),
        (
            "btc_drift",
            lambda value: value["trials"][0]["A"]["btc_after"].update(
                {"BTCUSDT:momentum_1h": {"drift": True}}
            ),
            "no_cross_route_or_base_series_contamination",
        ),
        (
            "semantic_drift",
            lambda value: value["trials"][0]["A"]["semantic"].update({"rsi": 0.0}),
            "primary_failure_fallback_converges",
        ),
        (
            "canonical_first_write_drift",
            lambda value: value["trials"][0]["F"]["first_canonical"].update(
                {"close": "999"}
            ),
            "ws_rest_disagreement_canonical_first_write_fail_closed",
        ),
        (
            "trial_b",
            lambda value: value["trials"][1]["A"].update(semantic_parity=False),
            "matrix_determinism",
        ),
    )
    for _name, mutate, gate_name in mutations:
        tampered = copy.deepcopy(evidence)
        mutate(tampered)
        assert evaluate_c3b2_gates(tampered)[gate_name] is False


def test_c3b2_identity_and_evidence_digest_scopes_are_distinct() -> None:
    evidence = load_artifact()
    identity_digest = sha256_fingerprint(identity_payload(evidence))
    evidence_digest = sha256_fingerprint(evidence_payload(evidence))
    tampered = copy.deepcopy(evidence)
    tampered["trials"][0]["A"]["semantic_parity"] = False
    assert sha256_fingerprint(identity_payload(tampered)) == identity_digest
    assert sha256_fingerprint(evidence_payload(tampered)) != evidence_digest
    assert identity_digest != evidence_digest


def test_c3b2_artifact_terminal_status_is_recomputed() -> None:
    evidence = load_artifact()
    assert evidence["terminal_status"] == C3B2_SUCCESS_STATUS
    assert all(evaluate_c3b2_gates(evidence).values())
    tampered = copy.deepcopy(evidence)
    tampered["trials"][0]["C"]["derived_count"] = 1
    assert evaluate_c3b2_gates(tampered)["provider_exhaustion_fail_closed"] is False


@pytest.mark.asyncio
async def test_real_c3b2_six_scenario_matrix() -> None:
    if os.getenv("INGESTION_DECISION_RUN_C3B2_PROVIDER_RECOVERY") != "1":
        pytest.skip(
            "set INGESTION_DECISION_RUN_C3B2_PROVIDER_RECOVERY=1 to run disposable C3B2"
        )
    evidence = await run_certification()
    write_artifact(evidence)
    assert evidence["terminal_status"] == C3B2_SUCCESS_STATUS
    assert all(evidence["gates"].values())
