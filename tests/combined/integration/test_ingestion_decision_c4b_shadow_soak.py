"""Pure C4B evaluator and transport-contract regressions.

The guarded real-infrastructure test is opt-in with
``INGESTION_DECISION_RUN_C4B=1``; ordinary test collection never starts Docker.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.decision_app.transport.shadow import ShadowDecisionObservation
from tests.combined.c4b_harness import (
    ARTIFACT_FILE,
    C4B_SUCCESS_STATUS,
    EXPECTED_PROTECTED_HASHES,
    RESOURCE_LIMITS,
    evaluate_c4b_gates,
    normalize_trial,
    observation_ledger,
    protected_hashes,
    remediation_source_hashes,
    run_c4b_certification,
    stable_artifact,
)


def _resource_samples() -> list[dict[str, object]]:
    return [
        {
            "phase": "startup",
            "services": {
                service: {
                    "container_present": True,
                    "stats_available": True,
                    "memory_usage_bytes": 1,
                    "configured_memory_bytes": limits["memory"],
                    "configured_cpu_nano": limits["cpu"],
                    "expected_memory_bytes": limits["memory"],
                    "cpu_percent": "1.0%",
                    "oom_killed": False,
                    "restart_count": 0,
                }
                for service, limits in RESOURCE_LIMITS.items()
            },
        }
    ]


def _trial() -> dict[str, object]:
    lanes = {
        "BTCUSDT:momentum_1h": [
            "2026-01-01T01:00:00+00:00",
            "2026-01-01T02:00:00+00:00",
            "2026-01-01T03:00:00+00:00",
            "2026-01-01T04:00:00+00:00",
        ],
        "BTCUSDT:momentum_4h": ["2026-01-01T04:00:00+00:00"],
        "ETHUSDT:momentum_4h": ["2026-01-01T04:00:00+00:00"],
    }
    observed = {
        lane: {
            cutoff: {
                "market_as_of": cutoff,
                "payload_fingerprint": f"fp-{lane}",
            }
            for cutoff in cutoffs
        }
        for lane, cutoffs in lanes.items()
    }
    return {
        "shadow_progress": [
            {
                "lane_id": lane,
                "market_as_of": cutoffs[-1],
                "last_disposition": "shadow",
            }
            for lane, cutoffs in lanes.items()
        ],
        "shadow_ledger": {
            "expected_cutoffs": lanes,
            "observed": {"by_lane": observed, "contradictions": []},
        },
        "authority": {"decision_identity_violations": []},
        "faults": {
            "F1_decision_down": {
                "passed": True,
                "effect_progress_recovered": True,
                "expected_missing_cutoffs": lanes,
                "observed_missing_cutoffs": copy.deepcopy(lanes),
            },
            "F2_broker_interruption": {"passed": True},
            "F3_db_down_decision_restart": {"passed": True},
            "F4_lifecycle_churn": {"passed": True},
        },
        "legacy": {"groups_present": True, "pel_total": 0},
        "retention": {"passed": True},
        "resource_samples": _resource_samples(),
        "resource_summary": {
            "samples_within_limits": True,
            "oom_killed": False,
            "unexpected_restart": False,
            "max_aggregate_rss_bytes": 1,
            "max_aggregate_cpu_cores": 1.0,
        },
        "queue_evidence": {
            "outbox_pending": 0,
            "input_lag": 0,
            "blocked_streams": 0,
            "cursor_tail_match": True,
            "unreconciled_lifecycle": 0,
        },
        "final_restart": {
            "ready": {"status": "ready"},
            "no_new_shadow_without_input": True,
            "after": {"outbox_pending": 0},
        },
        "cleanup": {"clean": True, "down_returncode": 0},
    }


def _evidence() -> dict[str, object]:
    trial = _trial()
    return {
        "schema_version": 1,
        "source_sha": "4295c4297f49d0a895974ad6afc8b4f660ad44c3",
        "source_contract": {
            "source_sha": "4295c4297f49d0a895974ad6afc8b4f660ad44c3",
            "c4a_manifest_sha": "bf33c23d413b8cef35bbd0202953d8b13a2170f49ba4fe2304166e4477e41b6a",
            "c4a_artifact_sha": "c2adb97f2504ce541a0b4aa41f186a4a86c0c209dd96229e6bc4b7d121399334",
            "r4c_manifest_sha": "fabc31f04ab40361c9d28b298d85fc0b26858d40d778db3d7bad1746796c50f0",
            "restart_backlog_source_hashes": remediation_source_hashes(),
        },
        "protected_hashes": dict(EXPECTED_PROTECTED_HASHES),
        "expected_protected_hashes": dict(EXPECTED_PROTECTED_HASHES),
        "fixture_hashes": {"c4b_overlay": "fixture"},
        "production_scope": {
            "decision_assets": [],
            "observer_active": False,
            "root_compose_unchanged": True,
        },
        "workload": {
            "total_base_observations": 10800,
            "per_asset": {"BTC": 5400, "ETH": 5400},
        },
        "decision_task_sites": 2,
        "trial_a": trial,
        "trial_b": copy.deepcopy(trial),
        "normalized_trial_a": copy.deepcopy(trial),
        "normalized_trial_b": copy.deepcopy(trial),
    }


def test_c4b_pure_evaluator_accepts_complete_raw_evidence() -> None:
    gates = evaluate_c4b_gates(_evidence())
    assert all(gates.values()), gates


def test_shadow_ledger_excludes_operational_ready_timestamp() -> None:
    market_as_of = datetime(2026, 1, 1, tzinfo=UTC)
    common = {
        "lane_id": "BTCUSDT:momentum_1h",
        "asset": "BTCUSDT",
        "decision_timeframe": "1h",
        "trigger_timeframe": "1h",
        "market_as_of": market_as_of,
        "decision_id": "decision-1",
        "policy_status": "NO_SIGNAL",
        "base_lane_revision": "lane-revision",
        "decision_execution_revision": "execution-revision",
        "feature_plan_fingerprint": "feature-plan",
        "data_plan_fingerprint": "data-plan",
        "policy_name": "passthrough",
        "policy_version": "1",
    }
    first = ShadowDecisionObservation(
        **common,
        decision_ready_at=market_as_of + timedelta(seconds=1),
    )
    second = ShadowDecisionObservation(
        **common,
        decision_ready_at=market_as_of + timedelta(seconds=2),
    )

    first_ledger = observation_ledger((first,))
    second_ledger = observation_ledger((second,))

    first_payload = first_ledger["by_lane"][first.lane_id]["1767225600000-0"]
    second_payload = second_ledger["by_lane"][second.lane_id]["1767225600000-0"]
    assert first_payload["payload_fingerprint"] == second_payload["payload_fingerprint"]
    assert first_ledger["contradictions"] == []
    assert second_ledger["contradictions"] == []


def test_normalized_trial_excludes_transport_only_diagnostics() -> None:
    raw = {
        "stderr": "trial-specific compose output",
        "stdout": "trial-specific build output",
        "start_stderr": "trial-specific restart output",
        "error": "Timeout reading from dynamic port",
        "unconfigured_event_id": "dynamic-id",
        "last_lifecycle_evidence": {"cursor": "dynamic-id"},
        "semantic": {"status": "passed"},
    }
    assert normalize_trial(raw) == {"semantic": {"status": "passed"}}


@pytest.mark.parametrize(
    ("path", "gate"),
    [
        ("protected_hashes", "protected_artifacts"),
        (
            "trial_a.shadow_ledger.observed.by_lane.BTCUSDT:momentum_1h",
            "shadow_ledger_complete",
        ),
        ("trial_a.shadow_ledger.observed.contradictions", "shadow_ledger_complete"),
        (
            "trial_a.authority.decision_identity_violations",
            "shadow_authority_isolation",
        ),
        ("trial_a.queue_evidence.input_lag", "cursor_lag_zero"),
        ("trial_a.queue_evidence.outbox_pending", "steady_state_queues"),
        (
            "trial_a.shadow_progress",
            "shadow_effect_progress",
        ),
        (
            "trial_a.faults.F1_decision_down.expected_missing_cutoffs",
            "shadow_effect_progress",
        ),
        (
            "source_contract.restart_backlog_source_hashes",
            "source_contract",
        ),
        ("trial_a.legacy.pel_total", "legacy_pel_drained"),
        ("trial_a.retention.passed", "retention_bounded"),
        ("trial_a.resource_summary.max_aggregate_rss_bytes", "aggregate_memory_normal"),
        ("trial_a.resource_summary.max_aggregate_cpu_cores", "aggregate_cpu"),
        ("trial_a.resource_summary.oom_killed", "no_oom_or_restart"),
        ("trial_a.final_restart.no_new_shadow_without_input", "final_restart"),
        ("trial_a.cleanup.clean", "cleanup"),
        ("normalized_trial_b", "two_trial_semantic_determinism"),
    ],
)
def test_c4b_tampered_raw_evidence_fails_closed(path: str, gate: str) -> None:
    evidence = _evidence()
    target: object = evidence
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]  # type: ignore[index]
    leaf = parts[-1]
    if path.endswith("observed.by_lane.BTCUSDT:momentum_1h"):
        target.pop(leaf, None)  # type: ignore[union-attr]
    elif path.endswith("shadow_progress"):
        target.clear()  # type: ignore[union-attr]
    elif path.endswith("expected_missing_cutoffs"):
        target[leaf]["BTCUSDT:momentum_1h"] = []  # type: ignore[index]
    elif leaf in {
        "clean",
        "passed",
        "cursor_tail_match",
        "no_new_shadow_without_input",
    }:
        target[leaf] = False  # type: ignore[index]
    elif leaf == "oom_killed":
        target[leaf] = True  # type: ignore[index]
    elif leaf in {
        "input_lag",
        "outbox_pending",
        "pel_total",
        "max_aggregate_rss_bytes",
        "max_aggregate_cpu_cores",
    }:
        target[leaf] = 10**12  # type: ignore[index]
    elif leaf == "decision_identity_violations":
        target[leaf] = ["signals:BTCUSDT:1h:1-0"]  # type: ignore[index]
    elif leaf == "contradictions":
        target[leaf] = ["BTCUSDT:momentum_1h:1-0"]  # type: ignore[index]
    elif leaf == "protected_hashes":
        evidence[leaf] = {"c4a": "tampered"}
    elif leaf == "restart_backlog_source_hashes":
        target[leaf] = {"tampered": "source"}  # type: ignore[index]
    elif leaf == "normalized_trial_b":
        evidence[leaf] = {"semantic": "drift"}
    gates = evaluate_c4b_gates(evidence)
    assert gates[gate] is False, (path, gate, gates)


def test_protected_hashes_are_exact() -> None:
    assert protected_hashes() == EXPECTED_PROTECTED_HASHES


def test_stored_artifact_locks_final_remediation_sources() -> None:
    stored = json.loads(ARTIFACT_FILE.read_text(encoding="utf-8"))
    source_contract = stored["source_contract"]
    assert (
        source_contract["restart_backlog_source_hashes"] == remediation_source_hashes()
    )
    gates = evaluate_c4b_gates(stored)
    assert len(gates) == 24
    assert gates["source_contract"] is True
    assert all(gates.values()), gates


@pytest.mark.skipif(
    os.getenv("INGESTION_DECISION_RUN_C4B") != "1",
    reason="real C4B infrastructure is opt-in",
)
@pytest.mark.asyncio
async def test_real_c4b_two_trial_soak() -> None:
    evidence = await run_c4b_certification()
    assert evidence["terminal_status"] == C4B_SUCCESS_STATUS
    assert all(evidence["gates"].values())


def test_c4b_artifact_serialization_is_canonical(tmp_path: Path) -> None:
    artifact = stable_artifact(_evidence())
    first = json.dumps(artifact, sort_keys=True, separators=(",", ":"))
    second = json.dumps(json.loads(first), sort_keys=True, separators=(",", ":"))
    assert first == second
