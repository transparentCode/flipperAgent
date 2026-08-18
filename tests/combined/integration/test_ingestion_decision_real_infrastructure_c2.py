from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest
import yaml

from tests.combined.c2_harness import (
    C2_COMPOSE_FILE,
    C2_SUCCESS_STATUS,
    evaluate_c2_gates,
    protected_hashes_valid,
    run_c2_certification,
)

ROOT = Path(__file__).resolve().parents[3]


def test_c2_compose_is_two_services_and_uses_production_images() -> None:
    fixture = yaml.safe_load(C2_COMPOSE_FILE.read_text(encoding="utf-8"))
    root = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert set(fixture["services"]) == {"db", "broker"}
    assert fixture["services"]["db"]["image"] == root["services"]["db"]["image"]
    assert fixture["services"]["broker"]["image"] == root["services"]["broker"]["image"]
    assert "env_file" not in fixture["services"]["db"]
    assert "env_file" not in fixture["services"]["broker"]
    assert "${C2_DB_PORT" in fixture["services"]["db"]["ports"][0]
    assert "${C2_BROKER_PORT" in fixture["services"]["broker"]["ports"][0]


def test_c2_protected_evidence_is_current() -> None:
    assert protected_hashes_valid()


def test_c2_gates_fail_closed_when_measured_evidence_is_tampered() -> None:
    artifact_path = (
        ROOT
        / "artifacts"
        / "combined_c2"
        / "c2_ingestion_decision_real_infrastructure_certification.json"
    )
    evidence = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert all(evaluate_c2_gates(evidence).values())

    mutations = (
        (
            "infrastructure_noeviction",
            "infrastructure_contract",
            lambda value: value["infrastructure"].update(valkey_noeviction=False),
        ),
        (
            "infrastructure_empty",
            "infrastructure_contract",
            lambda value: value["infrastructure"].update(before_empty=False),
        ),
        (
            "pending_outbox",
            "live_producer_counts",
            lambda value: value["live"]["db_counts_after_live"].update(
                outbox_pending=1
            ),
        ),
        (
            "live_cutoff",
            "route_parity",
            lambda value: value["live"]["route_parity"]["ETHUSDT:momentum_4h"].update(
                market_as_of="wrong"
            ),
        ),
        (
            "parity_record",
            "db_stream_decision_parity",
            lambda value: value["parity"]["records"][0].update(db_equals_stream=False),
        ),
        (
            "recovery_macd",
            "healthy_recovery",
            lambda value: value["recovery"]["semantic_actual"]["macd"].update(line=0),
        ),
        (
            "recovery_lane",
            "healthy_recovery",
            lambda value: value["recovery"]["lane_result_actual"].update(
                finalization_status="ABORTED"
            ),
        ),
        (
            "restart_cursor",
            "restart_reconstruction",
            lambda value: value["restart"]["fresh_input_cursors"].__setitem__(
                next(iter(value["restart"]["fresh_input_cursors"])), "wrong"
            ),
        ),
        (
            "restart_semantic",
            "restart_reconstruction",
            lambda value: value["restart"]["fresh_semantics"]["ETHUSDT:momentum_4h"][
                "macd"
            ].update(line=0),
        ),
        (
            "signal_stream_id",
            "signal_contract",
            lambda value: value["signals"]["entries"][0].update(stream_id="999-0"),
        ),
        (
            "signal_idempotency",
            "signal_contract",
            lambda value: value["signals"]["entries"][0].update(
                idempotency_key="wrong"
            ),
        ),
        (
            "trial_equality",
            "two_trial_determinism",
            lambda value: value["trials"].update(normalized_equal=False),
        ),
        ("cleanup", "cleanup", lambda value: value["cleanup"].update(trial_b=False)),
    )
    for name, gate, mutate in mutations:
        tampered = copy.deepcopy(evidence)
        mutate(tampered)
        assert evaluate_c2_gates(tampered)[gate] is False, name


@pytest.mark.asyncio
async def test_real_c2_two_trial_certification() -> None:
    if os.getenv("INGESTION_DECISION_RUN_C2_INFRASTRUCTURE") != "1":
        pytest.skip(
            "set INGESTION_DECISION_RUN_C2_INFRASTRUCTURE=1 to run disposable C2"
        )
    evidence = await run_c2_certification()
    assert evidence["terminal_status"] == C2_SUCCESS_STATUS
    assert all(evidence["gates"].values())
