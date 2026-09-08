from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

from scripts.certify_momentum_decision_m4 import (
    _digest,
    _source_sha,
    build_functional_artifact,
    evaluate_functional_gates,
)

ROOT = Path(__file__).resolve().parents[3]
M3_ARTIFACT = (
    ROOT
    / "artifacts"
    / "decision_m3"
    / ("m3_momentum_feature_semantics_certification.json")
)
D10_ARTIFACT = (
    ROOT / "artifacts" / "decision_d10" / ("d10_resource_capacity_certification.json")
)
M4_ARTIFACT = (
    ROOT
    / "artifacts"
    / "decision_m4"
    / ("m4_momentum_decision_integration_certification.json")
)
M4_RESOURCE_ARTIFACT = (
    ROOT / "artifacts" / "decision_m4" / ("m4_momentum_resource_certification.json")
)
HISTORICAL_M4_SOURCE_SHA = "e7bce3d5ca2ea46772447cdf003c989124ea1847"
HISTORICAL_M4_COMPOSITION = {
    "features": ["ATR@1", "MACD@1", "RSI@1"],
    "lane_count": 3,
    "plugins": ["momentum@1", "sr@1"],
    "runtime_plugins": ["momentum@1", "sr@1"],
}
CURRENT_M4_COMPOSITION = {
    "features": ["ATR@1", "MACD@1", "RSI@1"],
    "lane_count": 3,
    "plugins": ["momentum@1", "sr@1", "trendlines@1"],
    "runtime_plugins": ["momentum@1", "sr@1", "trendlines@1"],
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_protected_artifacts_remain_unchanged() -> None:
    assert _sha256(M3_ARTIFACT) == (
        "6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c"
    )
    assert _sha256(D10_ARTIFACT) == (
        "2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459"
    )
    assert _sha256(M4_ARTIFACT) == (
        "3d1339be919e8d176dcd1053cb1c42f46bf6a2dc5f62647114b805faea1e4792"
    )
    assert _sha256(M4_RESOURCE_ARTIFACT) == (
        "e11ae8aee717764a3cca9dbfaa0f58d6b4308387ac6b5b264fb4bdf8e5f570c4"
    )
    assert json.loads(M4_ARTIFACT.read_text())["source_sha"] == HISTORICAL_M4_SOURCE_SHA
    assert (
        json.loads(M4_RESOURCE_ARTIFACT.read_text())["source_sha"]
        == HISTORICAL_M4_SOURCE_SHA
    )


def test_m4_functional_artifact_is_deterministic_and_complete() -> None:
    stored = json.loads(M4_ARTIFACT.read_text())
    assert stored["source_sha"] == HISTORICAL_M4_SOURCE_SHA
    assert stored["composition"] == HISTORICAL_M4_COMPOSITION
    stored_measurement_payload = copy.deepcopy(stored)
    stored_measurement_payload.pop("deterministic_identity_sha256")
    stored_measurement_payload.pop("measurement_payload_sha256")
    assert _digest(stored_measurement_payload) == stored["measurement_payload_sha256"]

    current_source_sha = _source_sha()
    assert current_source_sha != HISTORICAL_M4_SOURCE_SHA
    first = build_functional_artifact()
    second = build_functional_artifact()
    assert first == second
    assert first["source_sha"] == current_source_sha
    assert first["composition"] == CURRENT_M4_COMPOSITION
    assert first["source_sha"]
    assert first["m3_artifact_sha256"] == (
        "6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c"
    )
    assert first["compiled_capacities"] == {
        "BTCUSDT/1h": 544,
        "BTCUSDT/4h": 544,
        "ETHUSDT/4h": 544,
    }
    assert first["compiled_feature_histories"] == {"MACD": 544, "RSI": 208}
    assert first["startup"]["status"] == "STARTUP_READY"
    assert first["startup"]["stateful_binding_count"] == 0
    assert first["functional_status"] == "PASS"
    assert first["terminal_status"] == (
        "MOMENTUM_M4_DECISION_INTEGRATION_REMEDIATION_READY_FOR_REVIEW"
    )
    assert all(first["functional_gates"].values())
    assert len(first["historical_reconstruction_parity"]["routes"]) == 3
    assert all(
        route["status"] == "PASS"
        and route["features_equal"]
        and route["outcome_equal"]
        and route["publication_count_during_reconstruction"] == 0
        for route in first["historical_reconstruction_parity"]["routes"]
    )
    assert first["duplicate_path"] == {
        "disposition": "DUPLICATE",
        "reason": "exact retained canonical duplicate",
        "lane_status": "LIVE",
        "trigger_cutoff": None,
        "policy_status": None,
        "publication_outcome": None,
        "finalization_status": None,
        "no_second_transaction": True,
        "publication_count": 1,
        "envelope_count": 1,
        "publisher_retry_outcome": "ALREADY_IDENTICAL",
    }
    assert first["publication_failure_path"] == {
        "lane_status": "RECONSTRUCTION_REQUIRED",
        "publication_outcome": "FAILED",
        "finalization_status": "ABORTED",
        "publication_count": 0,
    }
    assert first["retention_coverage"]["status"] == "PASS"
    assert first["resource_structure"]["startup_fetch_limits"] == {
        "BTCUSDT/1h": [544],
        "BTCUSDT/4h": [544],
        "ETHUSDT/4h": [544],
    }
    assert first["live_path"] == {
        "lane_status": "LIVE",
        "policy_status": "SIGNAL",
        "publication_outcome": "PUBLISHED",
        "finalization_status": "COMMITTED",
        "signal_stream": "signals:ETHUSDT:4h",
        "signal": first["live_path"]["signal"],
    }
    assert first["deterministic_identity_sha256"]
    assert first["measurement_payload_sha256"]
    assert first["deterministic_identity_sha256"] != first["measurement_payload_sha256"]


def test_default_m4_source_resolution_uses_current_checkout() -> None:
    expected = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert _source_sha() == expected


def test_functional_gates_fail_closed_and_measurement_digest_covers_evidence() -> None:
    evidence = json.loads(M4_ARTIFACT.read_text())
    assert all(evidence["functional_gates"].values())

    tampered = copy.deepcopy(evidence)
    tampered["historical_reconstruction_parity"]["routes"][0]["features_equal"] = False
    tampered_gates = evaluate_functional_gates(tampered)
    assert tampered_gates["historical_reconstruction"] is False

    payload = copy.deepcopy(evidence)
    original_digest = payload.pop("measurement_payload_sha256")
    payload.pop("deterministic_identity_sha256")
    payload["duplicate_path"]["publication_count"] = 2
    assert _digest(payload) != original_digest


def test_resource_artifact_has_graph_decomposition_and_real_leak_gates() -> None:
    resource = json.loads(M4_RESOURCE_ARTIFACT.read_text())
    assert resource["status"] == "PASS"
    assert resource["capacity_decomposition"]["base_d3_capacities"] == {
        "BTCUSDT/1h": 1,
        "BTCUSDT/4h": 1,
        "ETHUSDT/4h": 1,
    }
    assert resource["capacity_decomposition"]["feature_merged_capacities"] == {
        "BTCUSDT/1h": 544,
        "BTCUSDT/4h": 544,
        "ETHUSDT/4h": 544,
    }
    assert resource["capacity_decomposition"]["startup_fetch_limits"] == {
        "BTCUSDT/1h": [544],
        "BTCUSDT/4h": [544],
        "ETHUSDT/4h": [544],
    }
    assert resource["thread_leak_gate"] is True
    assert resource["task_leak_gate"] is True
    assert resource["threads_after"] <= resource["threads_before"]
    assert resource["tasks_after"] <= resource["tasks_before"]
