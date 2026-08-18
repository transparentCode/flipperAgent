from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest
import yaml

from tests.combined.c3a_harness import (
    C2_ARTIFACT_SHA,
    C2_COMPOSE_FILE,
    C3A_REMEDIATION_STATUS,
    _evidence_payload,
    _production_identity,
    evaluate_c3a_gates,
    run_c3a_certification,
    sha256_fingerprint,
    synthetic_c3a_evidence,
)

ROOT = Path(__file__).resolve().parents[3]


def test_c3a_reuses_isolated_two_service_c2_fixture() -> None:
    fixture = yaml.safe_load(C2_COMPOSE_FILE.read_text(encoding="utf-8"))
    production = yaml.safe_load(
        (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    )
    assert set(fixture["services"]) == {"db", "broker"}
    assert fixture["services"]["db"]["image"] == production["services"]["db"]["image"]
    assert (
        fixture["services"]["broker"]["image"]
        == production["services"]["broker"]["image"]
    )
    assert all("env_file" not in service for service in fixture["services"].values())
    assert "${C2_DB_PORT" in fixture["services"]["db"]["ports"][0]
    assert "${C2_BROKER_PORT" in fixture["services"]["broker"]["ports"][0]


def test_c3a_synthetic_evidence_passes_and_recomputes_every_gate() -> None:
    evidence = synthetic_c3a_evidence()
    assert all(evaluate_c3a_gates(evidence).values())

    mutations = (
        (
            "broker_pending",
            lambda value: value["scenarios"]["broker_outage"].update(
                pending_after_failure=0
            ),
            "broker_outage_backlog_recovery",
        ),
        (
            "broker_semantics",
            lambda value: value["scenarios"]["broker_outage"]["eth_semantics"][
                "macd"
            ].update(line=999),
            "broker_outage_backlog_recovery",
        ),
        (
            "broker_lane_result",
            lambda value: value["scenarios"]["broker_outage"]["eth_lane_result"].update(
                finalization_status="ABORTED"
            ),
            "broker_outage_backlog_recovery",
        ),
        (
            "db_partial_row",
            lambda value: value["scenarios"]["db_outage"].update(
                failed_row_count_after_restore=1
            ),
            "db_outage_fail_closed_recovery",
        ),
        (
            "db_partial_outbox",
            lambda value: value["scenarios"]["db_outage"].update(
                failed_outbox_count_after_restore=1
            ),
            "db_outage_fail_closed_recovery",
        ),
        (
            "db_disposition",
            lambda value: value["scenarios"]["db_outage"].update(
                input_dispositions=["DUPLICATE"]
            ),
            "db_outage_fail_closed_recovery",
        ),
        (
            "db_semantics",
            lambda value: value["scenarios"]["db_outage"]["eth_semantics"][
                "macd"
            ].update(histogram=999),
            "db_outage_fail_closed_recovery",
        ),
        (
            "db_failed_stream",
            lambda value: value["scenarios"]["db_outage"].update(
                failed_stream_unchanged=False
            ),
            "db_outage_fail_closed_recovery",
        ),
        (
            "db_failed_signal",
            lambda value: value["scenarios"]["db_outage"].update(
                failed_signal_count_after=1
            ),
            "db_outage_fail_closed_recovery",
        ),
        (
            "db_startup_ready",
            lambda value: value["scenarios"]["db_outage"].update(
                failed_startup_class=None
            ),
            "db_outage_fail_closed_recovery",
        ),
        (
            "split_event_identity",
            lambda value: value["scenarios"]["xadd_mark_split"].update(
                same_event_id=False
            ),
            "xadd_mark_split_exactly_once",
        ),
        (
            "split_signal_idempotency",
            lambda value: value["scenarios"]["xadd_mark_split"]["signal_contract"][
                "entries"
            ][0].update(idempotency_key="forged"),
            "signal_idempotency",
        ),
        (
            "restart_cursor",
            lambda value: value["scenarios"]["decision_backlog_restart"]["fresh"][
                "cursors"
            ].update(forged="cursor"),
            "decision_backlog_restart_reconstruction",
        ),
        (
            "restart_semantics",
            lambda value: value["scenarios"]["decision_backlog_restart"]["fresh"][
                "semantics"
            ]["ETHUSDT:momentum_4h"].update(parity=False),
            "decision_backlog_restart_reconstruction",
        ),
        (
            "restart_watermark",
            lambda value: value["scenarios"]["decision_backlog_restart"]["fresh"][
                "watermarks"
            ].update(forged="watermark"),
            "decision_backlog_restart_reconstruction",
        ),
        (
            "baseline_lane",
            lambda value: value["scenarios"]["broker_outage"]["baseline"][
                "lanes"
            ].update({"BTCUSDT:momentum_1h": "DEGRADED"}),
            "baseline_startup_exact",
        ),
        (
            "baseline_signal",
            lambda value: value["scenarios"]["broker_outage"]["baseline"].update(
                signal_count=1
            ),
            "baseline_startup_exact",
        ),
        (
            "baseline_schema",
            lambda value: value["scenarios"]["broker_outage"]["baseline"][
                "schema"
            ].update(candles_hypertable=False),
            "baseline_schema_contract",
        ),
        (
            "baseline_valkey_policy",
            lambda value: value["scenarios"]["broker_outage"]["baseline"][
                "infrastructure"
            ].update(valkey_noeviction=False),
            "infrastructure_contract",
        ),
        (
            "btc_isolation",
            lambda value: value["scenarios"]["xadd_mark_split"]["btc_after"][
                "semantics"
            ]["BTCUSDT:momentum_1h"].update(parity=False),
            "no_cross_route_contamination",
        ),
        (
            "btc_cursor_isolation",
            lambda value: value["scenarios"]["db_outage"]["btc_after"][
                "cursors"
            ].update(forged="cursor"),
            "no_cross_route_contamination",
        ),
        (
            "cleanup",
            lambda value: value["scenarios"]["db_outage"]["baseline"].update(
                cleanup={"clean": False}
            ),
            "cleanup_all_scenarios",
        ),
        (
            "trial_b_evidence",
            lambda value: value["trials"]["trial_b"]["scenarios"]["db_outage"].update(
                failed_outbox_count_after_restore=9
            ),
            "matrix_determinism",
        ),
        (
            "trial_b_cleanup",
            lambda value: value["trials"]["trial_b"]["scenarios"]["xadd_mark_split"][
                "baseline"
            ].update(
                cleanup={
                    "clean": False,
                    "compose_down_exit_code": 0,
                    "owned_resources": {
                        "containers": "container",
                        "volumes": "",
                        "networks": "",
                    },
                }
            ),
            "cleanup_all_scenarios",
        ),
        (
            "protected_hash_value",
            lambda value: value["protected_hashes"].update(c2="forged"),
            "protected_hashes",
        ),
        (
            "matrix",
            lambda value: value["trials"].update(normalized_equal=False),
            "matrix_determinism",
        ),
    )
    for name, mutate, gate in mutations:
        tampered = copy.deepcopy(evidence)
        mutate(tampered)
        assert evaluate_c3a_gates(tampered)[gate] is False, name


def test_c3a_protected_c2_hash_is_explicit() -> None:
    evidence = synthetic_c3a_evidence()
    assert evidence["protected_hashes"]["c2"] == C2_ARTIFACT_SHA


def test_c3a_identity_and_evidence_scopes_are_distinct() -> None:
    evidence = synthetic_c3a_evidence()
    identity = {
        "source_sha": evidence["source_sha"],
        "protected_hashes": evidence["protected_hashes"],
        "routes": ["BTCUSDT/1h", "BTCUSDT/4h", "ETHUSDT/4h"],
    }
    evidence_payload = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
    identity_payload = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    assert identity_payload != evidence_payload
    changed = copy.deepcopy(evidence)
    changed["scenarios"]["broker_outage"]["pending_after_failure"] = 1
    assert (
        json.dumps(identity, sort_keys=True, separators=(",", ":")) == identity_payload
    )
    assert (
        json.dumps(changed, sort_keys=True, separators=(",", ":")) != evidence_payload
    )


def test_c3a_evidence_digest_covers_measurements_and_terminal_gates() -> None:
    evidence = synthetic_c3a_evidence()
    evidence["gates"] = evaluate_c3a_gates(evidence)
    evidence["terminal_status"] = C3A_REMEDIATION_STATUS
    evidence["identity_digest"] = sha256_fingerprint(_production_identity(evidence))
    evidence["evidence_digest"] = sha256_fingerprint(_evidence_payload(evidence))
    identity_digest = evidence["identity_digest"]
    evidence_digest = evidence["evidence_digest"]

    tampered = copy.deepcopy(evidence)
    tampered["scenarios"]["broker_outage"]["pending_after_failure"] = 1
    tampered["gates"] = evaluate_c3a_gates(tampered)
    tampered["evidence_digest"] = sha256_fingerprint(_evidence_payload(tampered))

    assert tampered["identity_digest"] == identity_digest
    assert tampered["evidence_digest"] != evidence_digest


@pytest.mark.asyncio
async def test_real_c3a_four_scenario_matrix() -> None:
    if os.getenv("INGESTION_DECISION_RUN_C3A_RESILIENCE") != "1":
        pytest.skip("set INGESTION_DECISION_RUN_C3A_RESILIENCE=1 to run disposable C3A")
    evidence = await run_c3a_certification()
    assert evidence["terminal_status"] == C3A_REMEDIATION_STATUS
    assert all(evidence["gates"].values())
