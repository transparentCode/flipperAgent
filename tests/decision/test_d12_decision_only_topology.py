from __future__ import annotations

import copy
import json

from tests.combined import d12_harness
from tests.combined.d12_harness import (
    D11C_SHA256,
    D12B_ARTIFACT_FILE,
    D12B_BASE_SHA,
    D12B_SOURCE_PATHS,
    D12B_SUCCESS_STATUS,
    EXPECTED_ASSETS,
    EXPECTED_ROUTES,
    EXPECTED_SERVICES,
    FORBIDDEN_SERVICE_TOKENS,
    HISTORICAL_D12A_ARTIFACT_FILE,
    HISTORICAL_D12A_EVIDENCE_DIGEST,
    HISTORICAL_D12A_IDENTITY_DIGEST,
    HISTORICAL_D12A_SOURCE_LOCK_COUNT,
    HISTORICAL_D12A_SUCCESS_STATUS,
    _current_base_d12a_status,
    _current_d11c_status,
    _decision_authority_seam_scan,
    _deleted_paths_absent,
    _historical_d12a_archive_status,
    _live_reference_scan,
    _production_decision_routes,
    _production_execution_assets,
    _production_execution_mode,
    _production_risk_routes,
    _retired_harness_import_scan,
    _root_compose_status,
    _surviving_runtime_import_boundary,
    build_artifact,
    derive_gates,
    protected_hashes,
    protected_hashes_valid,
    recompute_evidence_digest,
    recompute_identity_digest,
    source_locks,
    stored_artifact_valid,
)


def _sample() -> dict[str, dict[str, object]]:
    return {
        service: {
            "present": True,
            "memory_usage_bytes": 10,
            "configured_memory_bytes": 512 * 1024 * 1024,
            "cpu_percent": 1.0,
            "oom_killed": False,
            "restart_count": 0,
        }
        for service in EXPECTED_SERVICES
    }


def _evidence() -> dict[str, object]:
    groups = {
        **{
            f"signals:{route}": [{"name": "risk_app_group", "pending": 0, "lag": 0}]
            for route in EXPECTED_ROUTES
        },
        **{
            f"orders:{asset}": [{"name": "execution_app_group", "pending": 0, "lag": 0}]
            for asset in EXPECTED_ASSETS
        },
    }
    return {
        "topology": {
            "services": list(EXPECTED_SERVICES),
            "legacy_services_absent": True,
            "dynamic_ports": True,
            "disposable_project": "d12b-test",
        },
        "configuration": {
            "fixture_decision_routes": list(EXPECTED_ROUTES),
            "production_decision_routes": list(EXPECTED_ROUTES),
            "production_risk_routes": list(EXPECTED_ROUTES),
            "production_execution_assets": list(EXPECTED_ASSETS),
            "execution_mode": _production_execution_mode(),
            "decision_assets_fixture_only": True,
        },
        "startup": {
            "decision_ready": True,
            "ingestion_ready": True,
            "risk_ready": True,
            "execution_ready": True,
            "authority_keys_before": (),
            "authority_keys_after": (),
            "effect_progress_before": (),
            "effect_progress": [
                {"lane_id": route, "last_disposition": None}
                for route in EXPECTED_ROUTES
            ],
            "baseline_signals": (),
            "baseline_legacy_streams": (),
            "startup_history_bars": 544,
        },
        "flow": {
            "signals": {
                "signals:BTCUSDT:1h": {
                    "count": 1,
                    "ids": ["1-0"],
                    "payloads": [{"idempotency_key": "btc-1h-1"}],
                },
                "signals:BTCUSDT:4h": {
                    "count": 1,
                    "ids": ["2-0"],
                    "payloads": [{"idempotency_key": "btc-4h-1"}],
                },
            },
            "signal_count": 2,
            "groups": groups,
            "orders_streams": tuple(f"orders:{asset}" for asset in EXPECTED_ASSETS),
            "fills_streams": ("fills:BTCUSDT",),
            "execution_status": {
                "BTCUSDT": {"mode": "paper", "state": "LIVE", "processed_count": "1"},
                "ETHUSDT": {"mode": "paper", "state": "LIVE", "processed_count": "0"},
            },
            "effect_progress": [
                {"lane_id": route, "last_disposition": "published"}
                for route in EXPECTED_ROUTES
            ],
        },
        "recovery": {
            name: {
                "ready": True,
                "authority_keys_absent": True,
                "effect_progress_restored": True,
                "signals_unchanged": True,
                "groups_restored": True,
                "no_duplicate_signals": True,
                "duplicate_free": True,
            }
            for name in (
                "decision_restart",
                "broker_restart",
                "database_restart",
                "full_topology_restart",
            )
        },
        "final": {
            "signals": {
                "signals:BTCUSDT:1h": {"count": 1, "ids": ["1-0"], "payloads": []},
                "signals:BTCUSDT:4h": {"count": 1, "ids": ["2-0"], "payloads": []},
            },
            "groups": groups,
            "effect_progress": [
                {"lane_id": route, "last_disposition": "published"}
                for route in EXPECTED_ROUTES
            ],
            "authority_keys": (),
            "no_legacy_streams": True,
            "shadow_streams": (),
            "paper_execution_status": {
                "BTCUSDT": {"mode": "paper", "state": "LIVE", "processed_count": "1"},
                "ETHUSDT": {"mode": "paper", "state": "LIVE", "processed_count": "0"},
            },
        },
        "resource_samples": {
            "startup": _sample(),
            "live": _sample(),
            "decision_restart": _sample(),
            "broker_restart": _sample(),
            "database_restart": _sample(),
            "full_restart": _sample(),
        },
        "historical_d12a_archive": _historical_d12a_archive_status(),
        "current_base_d12a_reconciliation": _current_base_d12a_status(),
        "current_d11c_proof": _current_d11c_status(),
        "deleted_paths": _deleted_paths_absent(),
        "root_compose": _root_compose_status(),
        "surviving_runtime_import_boundary": _surviving_runtime_import_boundary(),
        "retired_harness_imports": _retired_harness_import_scan(),
        "decision_authority_seam": _decision_authority_seam_scan(),
        "live_reference_scan": _live_reference_scan(),
        "source_inventory": list(D12B_SOURCE_PATHS),
        "source_locks": source_locks(),
        "protected_hashes": protected_hashes(),
        "source_sha": D12B_BASE_SHA,
        "cleanup": {"clean": True},
    }


def test_protected_hashes_are_current() -> None:
    assert protected_hashes_valid()


def test_historical_d12a_archive_remains_exact() -> None:
    status = _historical_d12a_archive_status()
    assert status["valid"] is True
    artifact = json.loads(HISTORICAL_D12A_ARTIFACT_FILE.read_text(encoding="utf-8"))
    assert artifact["identity_digest"] == HISTORICAL_D12A_IDENTITY_DIGEST
    assert artifact["evidence_digest"] == HISTORICAL_D12A_EVIDENCE_DIGEST
    assert artifact["terminal_status"] == HISTORICAL_D12A_SUCCESS_STATUS
    assert len(artifact["source_locks"]) == HISTORICAL_D12A_SOURCE_LOCK_COUNT


def test_current_base_d12a_archive_and_d11c_binding_are_current() -> None:
    assert _current_base_d12a_status()["valid"] is True
    assert _current_d11c_status()["valid"] is True
    assert D11C_SHA256 == protected_hashes()["d11c"]


def test_production_route_and_asset_contract_is_exact() -> None:
    assert _production_decision_routes() == EXPECTED_ROUTES
    assert _production_risk_routes() == EXPECTED_ROUTES
    assert _production_execution_assets() == EXPECTED_ASSETS


def test_root_compose_excludes_legacy_services() -> None:
    compose = _root_compose_status()
    assert compose["legacy_services_absent"] is True
    assert set(compose["services"]).issuperset(EXPECTED_SERVICES)
    assert all(token not in compose["services"] for token in FORBIDDEN_SERVICE_TOKENS)


def test_deleted_paths_and_live_reference_scan_are_clean() -> None:
    assert all(_deleted_paths_absent().values())
    assert _surviving_runtime_import_boundary()["clean"] is True
    assert _retired_harness_import_scan()["clean"] is True
    assert _decision_authority_seam_scan()["clean"] is True
    assert _live_reference_scan()["clean"] is True


def test_legacy_service_tamper_fails_closed() -> None:
    evidence = _evidence()
    evidence["topology"]["services"].append(next(iter(FORBIDDEN_SERVICE_TOKENS)))
    gates = derive_gates(evidence)
    assert gates["topology_exact"] is False
    assert gates["legacy_services_absent"] is False


def test_route_asset_authority_and_scan_tamper_fail_closed() -> None:
    evidence = _evidence()
    evidence["configuration"]["production_risk_routes"] = ["BTCUSDT:1h"]
    gates = derive_gates(evidence)
    assert gates["production_risk_routes_exact"] is False
    assert gates["decision_risk_route_agreement"] is False

    authority = _evidence()
    authority["startup"]["authority_keys_after"] = ("unexpected",)
    assert derive_gates(authority)["no_authority_keys_after_startup"] is False

    scan = _evidence()
    scan["live_reference_scan"] = {"clean": False, "matches": [{"path": "x"}]}
    assert derive_gates(scan)["live_reference_scan_clean"] is False


def test_signal_execution_and_resource_tamper_fail_closed() -> None:
    duplicate = _evidence()
    duplicate["flow"]["signals"]["signals:BTCUSDT:1h"]["ids"] = ["1-0", "1-0"]
    assert derive_gates(duplicate)["decision_signal_ids_unique"] is False

    execution = _evidence()
    execution["configuration"]["execution_mode"] = "live"
    assert derive_gates(execution)["execution_mode_paper"] is False

    resource = _evidence()
    resource["resource_samples"]["live"]["decision"]["memory_usage_bytes"] = (
        600 * 1024 * 1024
    )
    assert derive_gates(resource)["service_rss_within_limits"] is False


def test_source_lock_digest_and_protected_hash_tamper_fail_closed() -> None:
    artifact = build_artifact(_evidence())

    source_map = copy.deepcopy(artifact)
    first_path = next(iter(source_map["source_locks"]))
    source_map["source_locks"][first_path] = "0" * 64
    assert derive_gates(source_map)["source_locks_exact"] is False

    protected = copy.deepcopy(artifact)
    protected["protected_hashes"]["d11c"] = "0" * 64
    assert derive_gates(protected)["protected_artifacts_exact"] is False

    source_sha = copy.deepcopy(artifact)
    source_sha["source_sha"] = "0" * 40
    assert derive_gates(source_sha)["source_sha_exact"] is False

    identity = copy.deepcopy(artifact)
    identity["identity_digest"] = "0" * 64
    assert derive_gates(identity)["identity_digest_integrity"] is False

    evidence = copy.deepcopy(artifact)
    evidence["evidence_digest"] = "0" * 64
    assert derive_gates(evidence)["evidence_digest_integrity"] is False


def test_current_state_recomputation_counterexamples_fail_closed(monkeypatch) -> None:
    artifact = build_artifact(_evidence())

    monkeypatch.setattr(
        d12_harness,
        "_deleted_paths_absent",
        lambda: {"src/apps/signal_app": False},
    )
    assert derive_gates(artifact)["current_deleted_paths_match"] is False

    monkeypatch.setattr(
        d12_harness,
        "_root_compose_status",
        lambda: {
            "services": [next(iter(FORBIDDEN_SERVICE_TOKENS))],
            "legacy_services_absent": False,
        },
    )
    assert derive_gates(artifact)["current_root_compose_match"] is False

    monkeypatch.setattr(
        d12_harness,
        "_production_risk_routes",
        lambda: ("BTCUSDT:1h",),
    )
    assert derive_gates(artifact)["current_risk_routes_match"] is False

    monkeypatch.setattr(
        d12_harness,
        "_production_execution_assets",
        lambda: ("BTCUSDT",),
    )
    assert derive_gates(artifact)["current_execution_assets_match"] is False

    monkeypatch.setattr(
        d12_harness,
        "_live_reference_scan",
        lambda: {"clean": False, "matches": [{"path": "drift.py"}]},
    )
    assert derive_gates(artifact)["current_live_reference_scan_match"] is False

    monkeypatch.setattr(
        d12_harness,
        "_surviving_runtime_import_boundary",
        lambda: {"clean": False, "matches": [{"path": "legacy.py"}]},
    )
    assert derive_gates(artifact)["current_survivor_import_boundary_match"] is False

    monkeypatch.setattr(
        d12_harness,
        "source_locks",
        lambda: {D12B_SOURCE_PATHS[0]: "0" * 64},
    )
    assert derive_gates(artifact)["current_source_locks_match"] is False


def test_stored_gate_and_terminal_tamper_cannot_certify_ready() -> None:
    artifact = build_artifact(_evidence())

    tampered_gate = copy.deepcopy(artifact)
    tampered_gate["gates"]["topology_exact"] = False
    assert stored_artifact_valid(tampered_gate) is False

    tampered_status = copy.deepcopy(artifact)
    tampered_status["terminal_status"] = (
        "DECISION_D12B_COMPLETE_LEGACY_RETIREMENT_BLOCKED"
    )
    assert stored_artifact_valid(tampered_status) is False


def test_build_artifact_recomputes_final_integrity_contracts() -> None:
    artifact = build_artifact(_evidence())
    derived = derive_gates(artifact)
    assert artifact["gates"] == derived
    assert all(derived.values())
    assert artifact["identity_digest"] == recompute_identity_digest(artifact)
    assert artifact["evidence_digest"] == recompute_evidence_digest(artifact)
    assert artifact["terminal_status"] == D12B_SUCCESS_STATUS
    assert stored_artifact_valid(artifact) is True


def test_stored_artifact_recomputes_when_present() -> None:
    if not D12B_ARTIFACT_FILE.exists():
        return
    artifact = json.loads(D12B_ARTIFACT_FILE.read_text(encoding="utf-8"))
    assert stored_artifact_valid(artifact) is True
    assert artifact["identity_digest"] == recompute_identity_digest(artifact)
    assert artifact["evidence_digest"] == recompute_evidence_digest(artifact)
    assert artifact["terminal_status"] == D12B_SUCCESS_STATUS
