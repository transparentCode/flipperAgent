from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest
import yaml

from tests.combined.c3b1_harness import (
    C2_COMPOSE_FILE,
    SUCCESS_STATUS,
    _evidence_payload,
    _hash,
    _identity_payload,
    evaluate_c3b1_gates,
    run_c3b1_certification,
    synthetic_c3b1_evidence,
)

ROOT = Path(__file__).resolve().parents[3]


def test_c3b1_reuses_healthy_two_service_fixture() -> None:
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


def test_c3b1_synthetic_evidence_passes_all_gates() -> None:
    evidence = synthetic_c3b1_evidence()
    assert all(evaluate_c3b1_gates(evidence).values())


def test_c3b1_gates_recompute_from_raw_evidence() -> None:
    mutations = (
        (
            "protected",
            lambda value: value["protected_hashes"].update(c3a="forged"),
            "protected_hashes",
        ),
        (
            "startup_removed_row",
            lambda value: value["scenarios"]["startup_history_gap"].update(
                removed_row_count=0
            ),
            "startup_history_gap_fail_closed",
        ),
        (
            "startup_lane",
            lambda value: value["scenarios"]["startup_history_gap"]["lane_evidence"][
                "ETHUSDT:momentum_4h"
            ].update(status="STARTUP_READY"),
            "startup_history_gap_fail_closed",
        ),
        (
            "startup_signal",
            lambda value: value["scenarios"]["startup_history_gap"].update(
                signals_after=1
            ),
            "startup_history_gap_fail_closed",
        ),
        (
            "forward_disposition",
            lambda value: value["scenarios"]["forward_gap"].update(
                dispositions=["INSERTED"]
            ),
            "forward_gap_fail_closed",
        ),
        (
            "forward_cursor",
            lambda value: value["scenarios"]["forward_gap"].update(
                cursor_unchanged=False
            ),
            "forward_gap_fail_closed",
        ),
        (
            "forward_signal",
            lambda value: value["scenarios"]["forward_gap"].update(
                signal_count_after=1
            ),
            "forward_gap_fail_closed",
        ),
        (
            "conflict_db",
            lambda value: value["scenarios"]["conflicting_event"].update(
                durable_row_after={"close": "999"}
            ),
            "conflicting_event_fail_closed",
        ),
        (
            "conflict_cursor",
            lambda value: value["scenarios"]["conflicting_event"].update(
                cursor_unchanged=False
            ),
            "conflicting_event_fail_closed",
        ),
        (
            "conflict_signal",
            lambda value: value["scenarios"]["conflicting_event"].update(
                signal_count_after_conflict=2
            ),
            "conflicting_event_fail_closed",
        ),
        (
            "malformed_order",
            lambda value: value["scenarios"]["malformed_prefix_suffix"].update(
                ordered_dispositions=["MALFORMED", "INSERTED"]
            ),
            "malformed_suffix_fail_closed",
        ),
        (
            "malformed_cursor",
            lambda value: value["scenarios"]["malformed_prefix_suffix"].update(
                cursor_not_suffix=False
            ),
            "malformed_suffix_fail_closed",
        ),
        (
            "malformed_signal",
            lambda value: value["scenarios"]["malformed_prefix_suffix"].update(
                signal_count_after_second_poll=2
            ),
            "malformed_suffix_fail_closed",
        ),
        (
            "duplicate_disposition",
            lambda value: value["scenarios"]["duplicate_storm"][
                "duplicate_dispositions"
            ].__setitem__(0, "INSERTED"),
            "duplicate_storm_idempotent",
        ),
        (
            "duplicate_signal",
            lambda value: value["scenarios"]["duplicate_storm"].update(
                signal_count_after=2
            ),
            "duplicate_storm_idempotent",
        ),
        (
            "duplicate_semantics",
            lambda value: value["scenarios"]["duplicate_storm"].update(
                semantic_unchanged=False
            ),
            "duplicate_storm_idempotent",
        ),
        (
            "duplicate_event_identity",
            lambda value: value["scenarios"]["duplicate_storm"].update(
                duplicate_event_ids_consistent=False
            ),
            "duplicate_storm_idempotent",
        ),
        (
            "btc_isolation",
            lambda value: value["scenarios"]["forward_gap"].update(btc_unchanged=False),
            "no_cross_route_contamination",
        ),
        (
            "trial_evidence",
            lambda value: value["trials"]["trial_b"]["scenarios"]["forward_gap"].update(
                reason="wrong"
            ),
            "matrix_determinism",
        ),
        (
            "trial_cleanup",
            lambda value: value["trials"]["trial_b"]["scenarios"]["duplicate_storm"][
                "baseline"
            ].update(cleanup={"clean": False}),
            "cleanup_all_scenarios",
        ),
        (
            "production_scope",
            lambda value: value["production_scope"].update(decision_assets_empty=False),
            "production_scope",
        ),
    )
    for name, mutate, gate in mutations:
        tampered = copy.deepcopy(synthetic_c3b1_evidence())
        mutate(tampered)
        assert evaluate_c3b1_gates(tampered)[gate] is False, name


def test_c3b1_identity_and_evidence_digest_scopes_are_distinct() -> None:
    evidence = synthetic_c3b1_evidence()
    identity_digest = _hash(_identity_payload(evidence))
    evidence_digest = _hash(_evidence_payload(evidence))
    tampered = copy.deepcopy(evidence)
    tampered["scenarios"]["duplicate_storm"].update(signal_count_after=2)
    assert _hash(_identity_payload(tampered)) == identity_digest
    assert _hash(_evidence_payload(tampered)) != evidence_digest


def test_c3b1_artifact_shape_has_separate_digests_and_routes() -> None:
    evidence = synthetic_c3b1_evidence()
    artifact = dict(evidence)
    artifact["identity_digest"] = _hash(_identity_payload(evidence))
    artifact["evidence_digest"] = _hash(_evidence_payload(evidence))
    assert set(artifact["routes"]) == {"BTCUSDT/1h", "BTCUSDT/4h", "ETHUSDT/4h"}
    assert artifact["identity_digest"] != artifact["evidence_digest"]


@pytest.mark.asyncio
async def test_real_c3b1_five_scenario_matrix() -> None:
    if os.getenv("INGESTION_DECISION_RUN_C3B1_INTEGRITY") != "1":
        pytest.skip(
            "set INGESTION_DECISION_RUN_C3B1_INTEGRITY=1 to run disposable C3B1"
        )
    evidence = await run_c3b1_certification()
    assert evidence["terminal_status"] == SUCCESS_STATUS
    assert all(evidence["gates"].values())
    assert evidence["gates"]["startup_history_gap_fail_closed"] is True
