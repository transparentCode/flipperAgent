from __future__ import annotations

import copy
import json

import pytest

from tests.combined import d11b_harness
from tests.combined.d11b_harness import (
    BLOCKED_STATUS,
    SUCCESS_STATUS,
    build_artifact,
    evaluate_artifact,
)


def test_d11b_artifact_is_derived_from_raw_evidence() -> None:
    artifact = build_artifact()
    gates, status = evaluate_artifact(artifact)
    assert status == BLOCKED_STATUS
    assert gates["measured_evidence_origin"] is False

    mutations = (
        (
            "authority",
            lambda raw: raw["authority"]["after_cutover"].pop("ETHUSDT:4h"),
            "atomic_three_route_cutover",
        ),
        (
            "partial",
            lambda raw: raw["authority"].__setitem__(
                "partial_handoff_after", raw["authority"]["after_cutover"]
            ),
            "atomic_three_route_cutover",
        ),
        (
            "legacy",
            lambda raw: (
                raw["legacy"]["boundaries"]
                .__getitem__(0)
                .__setitem__("close_cutoff_ms", 1)
            ),
            "legacy_boundary_exact",
        ),
        (
            "risk",
            lambda raw: raw["risk"]["pre_cutover_groups"]["BTCUSDT:1h"].__setitem__(
                "pel", 1
            ),
            "risk_pre_cutover_quiescent",
        ),
        (
            "progress",
            lambda raw: raw["progress"]["seed"][0].__setitem__(
                "last_disposition", "published"
            ),
            "effect_progress_seed_exact",
        ),
        (
            "workers",
            lambda raw: raw["strategy"].__setitem__(
                "target_workers_after", ["BTCUSDT:1h"]
            ),
            "legacy_target_workers_relinquished",
        ),
        (
            "rollback",
            lambda raw: raw["cutback"]["selected"]["BTCUSDT:1h"].__setitem__(
                "last_id_through_progress", "wrong-0"
            ),
            "cutback_fast_forward_exact",
        ),
        (
            "cleanup",
            lambda raw: raw["cleanup"].__setitem__("docker_leftovers", ["d11b"]),
            "cleanup",
        ),
    )
    for _name, mutate, gate_name in mutations:
        tampered = copy.deepcopy(artifact)
        mutate(tampered["raw_evidence"])
        tampered_gates, tampered_status = evaluate_artifact(tampered)
        assert tampered_status == BLOCKED_STATUS
        assert tampered_gates[gate_name] is False


def test_d11b_protected_and_source_evidence_are_not_summary_trusted() -> None:
    artifact = build_artifact()
    for field, value in (("protected_hashes", "d11a"), ("source_hashes", "src")):
        tampered = copy.deepcopy(artifact)
        tampered[field][value] = "tampered"
        gates, status = evaluate_artifact(tampered)
        assert status == BLOCKED_STATUS
        assert (
            gates[
                "protected_evidence" if field == "protected_hashes" else "source_lock"
            ]
            is False
        )


def test_d11b_stored_artifact_recomputes_to_ready() -> None:
    from tests.combined.d11b_harness import ARTIFACT_PATH

    artifact = (
        json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        if ARTIFACT_PATH.exists()
        else build_artifact()
    )
    gates, status = evaluate_artifact(artifact)
    assert status == SUCCESS_STATUS
    assert all(gates.values())


def test_d11b_all_cutover_boundaries_fail_closed_when_tampered() -> None:
    cases = (
        (
            "authority_owner_missing",
            lambda raw: raw["authority"]["after_cutover"].pop("ETHUSDT:4h"),
            "authority_contract",
        ),
        (
            "wrong_epoch",
            lambda raw: raw["authority"]["after_cutover"]["BTCUSDT:1h"].__setitem__(
                "epoch", 2
            ),
            "authority_contract",
        ),
        (
            "legacy_after_decision",
            lambda raw: raw["publication_guard"]["attempts"][0].__setitem__(
                "owner", "decision"
            ),
            "no_dual_authority_write",
        ),
        (
            "decision_before_owner",
            lambda raw: raw["publication_guard"]["attempts"][1].__setitem__(
                "xadd_count", 1
            ),
            "no_dual_authority_write",
        ),
        (
            "effect_after_boundary",
            lambda raw: raw["progress"]["seed"][0].__setitem__("market_as_of_ms", 1),
            "effect_progress_seed_exact",
        ),
        (
            "risk_pel_before_cutover",
            lambda raw: raw["risk"]["pre_cutover_groups"]["BTCUSDT:1h"].__setitem__(
                "pel", 1
            ),
            "risk_pre_cutover_quiescent",
        ),
        (
            "risk_lag_before_cutover",
            lambda raw: raw["risk"]["pre_cutover_groups"]["BTCUSDT:4h"].__setitem__(
                "lag", 1
            ),
            "risk_pre_cutover_quiescent",
        ),
        (
            "signal_head_past_boundary",
            lambda raw: raw["legacy"]["signal_head_preflight"][0].__setitem__(
                "head_id", "1800007200000-0"
            ),
            "signal_head_preflight",
        ),
        (
            "startup_strategy_owner",
            lambda raw: raw["decision"]["startup"]["owner_records"][
                "BTCUSDT:1h"
            ].__setitem__("owner", "strategy"),
            "decision_startup_owner_preflight",
        ),
        (
            "broker_authority_loss",
            lambda raw: raw["decision"]["broker_restart"]["after"].pop("BTCUSDT:1h"),
            "broker_authority_persistence",
        ),
        (
            "strategy_worker_remains",
            lambda raw: raw["strategy"].__setitem__(
                "target_workers_after", ["BTCUSDT:1h"]
            ),
            "legacy_target_workers_relinquished",
        ),
        (
            "unrelated_route_disappears",
            lambda raw: raw["strategy"]["unrelated_routes"].remove("XRPUSDT:1h"),
            "unrelated_legacy_routes_preserved",
        ),
        (
            "strategy_pel_at_cutback",
            lambda raw: raw["cutback"]["strategy_groups"]["BTCUSDT:1h"].__setitem__(
                "pel", 1
            ),
            "cutback_fast_forward_exact",
        ),
        (
            "unread_decision_backlog",
            lambda raw: raw["cutback"]["selected"]["BTCUSDT:1h"].__setitem__(
                "next_unread_id", None
            ),
            "cutback_fast_forward_exact",
        ),
        (
            "stale_decision_after_cutback",
            lambda raw: raw["cutback"]["stale_decision"].__setitem__("xadd_count", 1),
            "stale_decision_denied",
        ),
        (
            "emergency_cutoff_dropped",
            lambda raw: raw["emergency_rollback"]["dropped_cutoffs"].append(
                "BTCUSDT:1h"
            ),
            "emergency_rollback_no_loss",
        ),
        (
            "cleanup_failure",
            lambda raw: raw["cleanup"].__setitem__("clean", False),
            "cleanup",
        ),
    )
    for _name, mutate, gate_name in cases:
        tampered = copy.deepcopy(build_artifact())
        mutate(tampered["raw_evidence"])
        gates, status = evaluate_artifact(tampered)
        assert status == BLOCKED_STATUS
        assert gates[gate_name] is False


def test_d11b_measurement_evidence_changes_evidence_digest() -> None:
    artifact = build_artifact()
    tampered = copy.deepcopy(artifact)
    tampered["raw_evidence"]["decision"]["post_cutover_events"][0][
        "market_as_of_ms"
    ] += 1
    gates, status = evaluate_artifact(tampered)
    assert status == BLOCKED_STATUS
    assert gates["evidence_digest_integrity"] is False


def test_d11b_synthetic_fixture_cannot_claim_measured_readiness() -> None:
    artifact = build_artifact()

    assert artifact["raw_evidence"]["evidence_origin"] == "synthetic_unit_fixture"
    assert artifact["raw_evidence"]["measured_trials"] == []
    assert artifact["terminal_status"] == BLOCKED_STATUS
    assert artifact["gates"]["measured_evidence_origin"] is False


def test_d11b_execution_mode_gate_recomputes_from_current_paper_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = build_artifact()
    monkeypatch.setattr(d11b_harness, "execution_mode_is_paper", lambda: False)

    gates, status = evaluate_artifact(artifact, verify_digests=False)

    assert status == BLOCKED_STATUS
    assert gates["execution_mode_paper"] is False


def test_d11b_operational_boundary_evidence_is_not_summary_trusted() -> None:
    from tests.combined.d11b_harness import ARTIFACT_PATH

    if not ARTIFACT_PATH.exists():
        pytest.skip("requires the regenerated measured D11B artifact")
    artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    cases = (
        (
            "post_stop_boundary",
            lambda trial: trial["legacy"]["post_stop_boundary"].__setitem__(
                "stable", False
            ),
            "post_stop_legacy_boundary",
        ),
        (
            "progress_stability",
            lambda trial: trial["progress"]["decision_progress_stable"].__setitem__(
                "stable", False
            ),
            "decision_progress_stable_after_stop",
        ),
        (
            "authority_activation",
            lambda trial: trial["execution"].__setitem__(
                "strategy_authority_enforced", False
            ),
            "strategy_authority_activation",
        ),
    )
    for _name, mutate, gate_name in cases:
        tampered = copy.deepcopy(artifact)
        mutate(tampered["raw_evidence"]["measured_trials"][0])
        gates, status = evaluate_artifact(tampered)
        assert status == BLOCKED_STATUS
        assert gates[gate_name] is False


def test_d11b_measured_builder_rejects_synthetic_evidence() -> None:
    with pytest.raises(ValueError, match="measured disposable evidence"):
        d11b_harness.build_artifact_from_measured(d11b_harness.build_raw_evidence())
