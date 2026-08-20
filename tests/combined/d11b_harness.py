"""Fail-closed D11B authority-cutover evidence and evaluator."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apps.decision_app.settings import load_decision_config
from libs.common.config import ConfigManager
from libs.common.signal_authority import TARGET_SIGNAL_ROUTES
from scripts.decision_d11b_authority_cutover import (
    cutback_fast_forward_boundary,
    feature_close_cutoff_ms,
    signal_head_preflight,
    validate_group_quiescence,
)

ROOT = Path(__file__).resolve().parents[2]
D11B_BASE_SHA = "8dc3a21178419e3de46ae93e1be708f1350f5737"
D11A_INTEGRATION_COMMIT = D11B_BASE_SHA
SUCCESS_STATUS = (
    "DECISION_D11B_OPERATIONAL_BOUNDARY_STAGING_REMEDIATION_READY_FOR_REVIEW"
)
BLOCKED_STATUS = "DECISION_D11B_AUTHORITY_CUTOVER_EVIDENCE_INSUFFICIENT"
EXPECTED_LANES = (
    "BTCUSDT:momentum_1h",
    "BTCUSDT:momentum_4h",
    "ETHUSDT:momentum_4h",
)
EXPECTED_PROTECTED_HASHES = {
    "d11a": "31114ecaae17f52e1d9bdd042e5c2b4ce174c1cabb114eb89894c8f7f4f415e1",
    "c4b": "2d047346ced14a72843cc22ea9a2f5eebd9929c4d02edab6f8cadb6d19582af7",
    "c4a": "c2adb97f2504ce541a0b4aa41f186a4a86c0c209dd96229e6bc4b7d121399334",
    "m3": "6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c",
    "m4_functional": "3d1339be919e8d176dcd1053cb1c42f46bf6a2dc5f62647114b805faea1e4792",
    "m4_resource": "e11ae8aee717764a3cca9dbfaa0f58d6b4308387ac6b5b264fb4bdf8e5f570c4",
    "d10": "2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459",
    "c1": "386b9eb33ed38128decade737bb7977cb2861a21b39e3d8cc061838635248ad4",
    "c2": "9745c9631a198d44e081a5916e89d8182c40c09db6fd72ed8d8f237399792f67",
    "c3a": "34c0b0eaa85fffacbd5c99d346bdcf2829dd12c8c6769e18c63711d0a342622b",
    "c3b1": "bfb335bf5ab27b790c91be13ad878531b7a85a957901c86f7a6ec462f566fb63",
    "c3b2p": "0981b3bd1962089932da5dc7669c936537ddaaf1d5c17adae71d2f7e798347f0",
}
PROTECTED_ARTIFACTS = {
    "d11a": ROOT
    / "artifacts/decision_d11a/d11a_authority_handoff_foundation_certification.json",
    "c4b": ROOT
    / "artifacts/combined_c4b/c4b_decision_shadow_soak_resource_certification.json",
    "c4a": ROOT
    / "artifacts/combined_c4a/c4a_decision_shadow_container_foundation_certification.json",
    "m3": ROOT
    / "artifacts/decision_m3/m3_momentum_feature_semantics_certification.json",
    "m4_functional": ROOT
    / "artifacts/decision_m4/m4_momentum_decision_integration_certification.json",
    "m4_resource": ROOT
    / "artifacts/decision_m4/m4_momentum_resource_certification.json",
    "d10": ROOT / "artifacts/decision_d10/d10_resource_capacity_certification.json",
    "c1": ROOT
    / "artifacts/combined_c1/c1_ingestion_decision_momentum_certification.json",
    "c2": ROOT
    / "artifacts/combined_c2/c2_ingestion_decision_real_infrastructure_certification.json",
    "c3a": ROOT
    / "artifacts/combined_c3a/c3a_ingestion_decision_infrastructure_resilience_certification.json",
    "c3b1": ROOT
    / "artifacts/combined_c3b1/c3b1_ingestion_decision_canonical_integrity_certification.json",
    "c3b2p": ROOT
    / "artifacts/combined_c3b2/c3b2_ingestion_decision_provider_recovery_disagreement_certification.json",
}
SOURCE_PATHS = (
    "src/libs/common/signal_authority.py",
    "src/apps/decision_app/bootstrap.py",
    "src/apps/decision_app/domain/identity.py",
    "src/apps/decision_app/runtime/live.py",
    "src/apps/decision_app/runtime/startup.py",
    "src/apps/decision_app/storage/schema.sql",
    "src/apps/decision_app/transport/signals.py",
    "src/apps/decision_app/storage/shadow_progress.py",
    "src/apps/strategy_app/publishing/signals.py",
    "src/apps/strategy_app/runtime/worker.py",
    "src/apps/strategy_app/strategy_worker.py",
    "src/apps/strategy_app/runtime_pairs.py",
    "src/apps/strategy_app/settings.py",
    "scripts/decision_d11b_authority_cutover.py",
    "scripts/certify_decision_d11b_authority_cutover.py",
    "tests/combined/fixtures/d11b/docker-compose.yml",
    "tests/combined/d11b_harness.py",
    "tests/combined/d11b_real.py",
    "tests/combined/integration/test_decision_d11b_authority_cutover.py",
    "tests/decision/test_d11b_authority_cutover.py",
    "tests/decision/test_d11b_certification.py",
    "tests/decision/test_d9a_settings_and_history.py",
    "configs/decision/global.yaml",
    "configs/models.yaml",
    "configs/decision/assets/BTC.yaml",
    "configs/decision/assets/ETH.yaml",
    "docker-compose.yml",
)
HISTORICAL_D11B_SOURCE_MAP_DIGEST = (
    "adac68a739799eb6c29a188ddcf0586b69d4b972c51b639beb51cf5d4f0ddd3a"
)
HISTORICAL_D11B_SOURCE_PATHS = (
    "configs/decision/assets/BTC.yaml",
    "configs/decision/assets/ETH.yaml",
    "configs/decision/global.yaml",
    "configs/models.yaml",
    "docker-compose.yml",
    "scripts/certify_decision_d11b_authority_cutover.py",
    "scripts/decision_d11b_authority_cutover.py",
    "src/apps/decision_app/bootstrap.py",
    "src/apps/decision_app/domain/identity.py",
    "src/apps/decision_app/runtime/live.py",
    "src/apps/decision_app/runtime/startup.py",
    "src/apps/decision_app/storage/schema.sql",
    "src/apps/decision_app/storage/shadow_progress.py",
    "src/apps/decision_app/transport/signals.py",
    "src/apps/strategy_app/publishing/signals.py",
    "src/apps/strategy_app/runtime/worker.py",
    "src/apps/strategy_app/runtime_pairs.py",
    "src/apps/strategy_app/settings.py",
    "src/apps/strategy_app/strategy_worker.py",
    "src/libs/common/signal_authority.py",
    "tests/combined/d11b_harness.py",
    "tests/combined/d11b_real.py",
    "tests/combined/fixtures/d11b/docker-compose.yml",
    "tests/combined/integration/test_decision_d11b_authority_cutover.py",
    "tests/decision/test_d11b_authority_cutover.py",
    "tests/decision/test_d11b_certification.py",
    "tests/decision/test_d9a_settings_and_history.py",
)
HISTORICAL_D11B_PRODUCTION_CONFIG_HASHES = {
    "configs/decision/assets/BTC.yaml": "adbd011928ce80ee028cf72db5116f55dd758f7976244469defa329be7e76cdd",
    "configs/decision/assets/ETH.yaml": "a4220a9297e93ab96642e0fda6472349efeda867266a0850a326fc8adc7ca5b3",
    "configs/decision/global.yaml": "d313584b082de513fcc652e0307df9d5b0e119c178331f5ef6be73d6e047ca75",
    "configs/execution.yaml": "52962515e2582aa735a1f2c58337feedbde096ce22ec012d364b1c2a298b20ee",
    "configs/models.yaml": "cc27b2958b97ccedb1c9b4cc357b0068015ca090cd6c3f811b16a22249ef7802",
    "configs/risk.yaml": "b70044e2a2282326d28e2b24c2b4492423847f4d8bb7de2c18e703ab92e8dc24",
    "docker-compose.yml": "b24d6823e4a128e1a9e716772c83c50871fc89b3f3f81830b2365cebdc412df1",
}
ARTIFACT_PATH = (
    ROOT / "artifacts/decision_d11b/d11b_authority_cutover_certification.json"
)


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return value


def canonical_json(value: object) -> str:
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"))


def sha256_fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_hashes() -> dict[str, str]:
    return {name: file_sha256(path) for name, path in PROTECTED_ARTIFACTS.items()}


def current_source_hashes() -> dict[str, str]:
    return {path: file_sha256(ROOT / path) for path in SOURCE_PATHS}


def historical_source_lock(source_hashes: object) -> bool:
    """Validate frozen D11B source evidence, not evolved checkout bytes."""

    return (
        isinstance(source_hashes, Mapping)
        and set(source_hashes) == set(HISTORICAL_D11B_SOURCE_PATHS)
        and sha256_fingerprint(source_hashes) == HISTORICAL_D11B_SOURCE_MAP_DIGEST
    )


def historical_production_config_lock(config_hashes: object) -> bool:
    return config_hashes == HISTORICAL_D11B_PRODUCTION_CONFIG_HASHES


def production_config_hashes() -> dict[str, str]:
    paths = (
        "configs/decision/global.yaml",
        "configs/decision/assets/BTC.yaml",
        "configs/decision/assets/ETH.yaml",
        "configs/models.yaml",
        "configs/execution.yaml",
        "configs/risk.yaml",
        "docker-compose.yml",
    )
    return {path: file_sha256(ROOT / path) for path in paths}


def execution_mode_is_paper() -> bool:
    import yaml

    payload = yaml.safe_load((ROOT / "configs/execution.yaml").read_text())
    return (
        isinstance(payload, Mapping)
        and isinstance(payload.get("execution"), Mapping)
        and payload["execution"].get("mode") == "paper"
    )


def _load_config(path_root: Path | None = None):
    root = ROOT if path_root is None else path_root
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(ROOT / "configs"))
    try:
        return load_decision_config(
            manager,
            global_file=root / "global.yaml",
            assets_directory=root / "assets",
        )
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()


def route_identity(config: Any) -> dict[str, object]:
    return {
        lane.lane_id: {
            "asset": lane.asset,
            "decision_timeframe": lane.decision_timeframe,
            "trigger_timeframe": lane.trigger_timeframe,
            "authority": lane.authority,
            "risk_profile_key": lane.risk_profile_key,
            "parameters": {
                binding.slot_name: _plain(binding.parameters)
                for binding in lane.bindings
            },
        }
        for lane in config.lane_specs()
    }


def m4_route_identity() -> dict[str, object]:
    current = route_identity(_load_config(ROOT / "configs/decision"))
    certified = route_identity(
        _load_config(ROOT / "tests/decision/fixtures/momentum_m4")
    )
    return {"current": current, "certified": certified, "matches": current == certified}


def _authority(
    route: str, owner: str, epoch: int, boundary_ms: int
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "route": route,
        "owner": owner,
        "epoch": epoch,
        "boundary_ms": boundary_ms,
    }


def _route_boundaries() -> dict[str, int]:
    base = 1_800_000_000_000
    return {
        "BTCUSDT:1h": base + 3_600_000,
        "BTCUSDT:4h": base + 14_400_000,
        "ETHUSDT:4h": base + 14_400_000,
    }


def build_raw_evidence() -> dict[str, object]:
    boundaries = _route_boundaries()
    initial = {
        route: _authority(route, "strategy", 0, 0) for route in TARGET_SIGNAL_ROUTES
    }
    decision = {
        route: _authority(route, "decision", 1, boundary)
        for route, boundary in boundaries.items()
    }
    strategy_after_cutback = {
        route: _authority(route, "strategy", 2, boundary)
        for route, boundary in boundaries.items()
    }
    legacy_boundaries = [
        {
            "route": route,
            "feature_timestamp_ms": boundary - 3_600_000
            if route == "BTCUSDT:1h"
            else boundary - 14_400_000,
            "timeframe": "1h" if route == "BTCUSDT:1h" else "4h",
            "close_cutoff_ms": boundary,
            "strategy_group": {
                "exists": True,
                "pel": 0,
                "lag": 0,
                "last_delivered": f"{boundary}-0",
            },
        }
        for route, boundary in boundaries.items()
    ]
    progress_seed = [
        {
            "route": route,
            "lane_id": EXPECTED_LANES[index],
            "market_as_of_ms": boundary,
            "last_disposition": None,
        }
        for index, (route, boundary) in enumerate(boundaries.items())
    ]
    publication_attempts = [
        {
            "route": "BTCUSDT:1h",
            "owner": "strategy",
            "expected_owner": "strategy",
            "xadd_count": 1,
            "result": "PUBLISHED",
        },
        {
            "route": "BTCUSDT:1h",
            "owner": "decision",
            "expected_owner": "strategy",
            "xadd_count": 0,
            "result": "DENIED",
        },
        {
            "route": "BTCUSDT:1h",
            "owner": "decision",
            "expected_owner": "decision",
            "xadd_count": 1,
            "result": "PUBLISHED",
        },
        {
            "route": "BTCUSDT:1h",
            "owner": "strategy",
            "expected_owner": "decision",
            "xadd_count": 0,
            "result": "DENIED",
        },
    ]
    cutoff_by_route = {
        route: [
            boundary + (index + 1) * (3_600_000 if route.endswith("1h") else 14_400_000)
        ]
        for index, (route, boundary) in enumerate(boundaries.items())
    }
    signal_ids = {
        route: [f"{cutoff}-0" for cutoff in cutoffs]
        for route, cutoffs in cutoff_by_route.items()
    }
    cutback_entries = {
        route: [
            {
                "id": f"{boundary}-0",
                "timestamp_ms": boundary
                - (3_600_000 if route.endswith("1h") else 14_400_000),
            },
            {
                "id": f"{boundary + (3_600_000 if route.endswith('1h') else 14_400_000)}-0",
                "timestamp_ms": boundary,
            },
            {
                "id": f"{boundary + 2 * (3_600_000 if route.endswith('1h') else 14_400_000)}-0",
                "timestamp_ms": boundary
                + (3_600_000 if route.endswith("1h") else 14_400_000),
            },
        ]
        for route, boundary in boundaries.items()
    }
    return {
        "evidence_origin": "synthetic_unit_fixture",
        "measured_trials": [],
        "execution": {
            "mode": "disposable_d11b_authority_and_process_contract",
            "services": [
                "db",
                "broker",
                "signal-worker",
                "strategy-worker",
                "decision",
                "risk-worker",
            ],
            "dynamic_ports": True,
            "normal_root_state_used": False,
            "real_disposable_stack": True,
            "compose_rendered": True,
            "repository_dockerfile_built": True,
            "decision_container": {
                "healthy": True,
                "ready_status_code": 200,
                "memory_limit": "512M",
                "cpu_limit": "0.5",
                "read_only": True,
                "no_new_privileges": True,
            },
            "initial_owner_startup": {
                "owner": "strategy",
                "decision_ready": False,
                "startup_failed_closed": True,
                "signals_written": 0,
            },
        },
        "authority": {
            "routes": list(TARGET_SIGNAL_ROUTES),
            "initial": initial,
            "after_cutover": decision,
            "after_cutback": strategy_after_cutback,
            "partial_handoff_before": initial,
            "partial_handoff_after": initial,
            "owner_timeline": [
                {"route": route, "owner": owner}
                for owner in ("strategy", "decision", "strategy", "decision")
                for route in TARGET_SIGNAL_ROUTES
            ],
            "cutover_epochs": {route: [0, 1] for route in TARGET_SIGNAL_ROUTES},
            "cutback_epochs": {route: [1, 2] for route in TARGET_SIGNAL_ROUTES},
        },
        "publication_guard": {"attempts": publication_attempts},
        "legacy": {
            "boundaries": legacy_boundaries,
            "signal_head_preflight": [
                {"route": route, "head_id": "100-0", "next_id": f"{boundary + 1}-0"}
                for route, boundary in boundaries.items()
            ],
        },
        "risk": {
            "pre_cutover_groups": {
                route: {"exists": True, "pel": 0, "lag": 0}
                for route in TARGET_SIGNAL_ROUTES
            },
            "post_cutover": {
                "acked_model_names": ["m4-btc-1h", "m4-btc-4h", "m4-eth-4h"],
                "acked_streams": [
                    "signals:BTCUSDT:1h",
                    "signals:BTCUSDT:4h",
                    "signals:ETHUSDT:4h",
                ],
                "runtime_healthy": True,
                "pel": 0,
                "lag": 0,
            },
            "post_cutback": {"pel": 0, "lag": 0},
        },
        "progress": {
            "seed": progress_seed,
            "post_cutover": [
                {
                    "route": route,
                    "cutoff_ms": cutoff_by_route[route][-1],
                    "disposition": "published" if index != 1 else "no_signal",
                }
                for index, route in enumerate(TARGET_SIGNAL_ROUTES)
            ],
            "restart": {
                "expected_cutoffs": cutoff_by_route,
                "observed_cutoffs": cutoff_by_route,
                "duplicate_count": 0,
            },
        },
        "decision": {
            "startup": {
                "ready": True,
                "status_code": 200,
                "service_state": "RUNNING",
                "owner_records": decision,
                "active_lanes": list(EXPECTED_LANES),
                "blocked_streams": 0,
                "historical_signals": 0,
            },
            "post_cutover_events": [
                {
                    "route": route,
                    "market_as_of_ms": cutoff_by_route[route][0],
                    "policy_status": "SIGNAL" if index != 1 else "NO_SIGNAL",
                    "publication_outcome": "PUBLISHED" if index != 1 else None,
                    "progress_disposition": "published" if index != 1 else "no_signal",
                }
                for index, route in enumerate(TARGET_SIGNAL_ROUTES)
            ],
            "restart": {
                "catchup_before_new_input": True,
                "exact_ids": signal_ids,
                "no_duplicate_ids": True,
            },
            "broker_restart": {
                "before": decision,
                "after": decision,
                "named_volume_preserved": True,
                "decision_ready_after_restart": True,
            },
        },
        "strategy": {
            "catalog_before": [
                "BNBUSDT:30m",
                "BTCUSDT:1h",
                "BTCUSDT:4h",
                "DOGEUSDT:4h",
                "ETHUSDT:4h",
                "SOLUSDT:1h",
                "XRPUSDT:1h",
            ],
            "catalog_after": ["BNBUSDT:30m", "DOGEUSDT:4h", "SOLUSDT:1h", "XRPUSDT:1h"],
            "target_workers_after": [],
            "unrelated_routes": [
                "BNBUSDT:30m",
                "DOGEUSDT:4h",
                "SOLUSDT:1h",
                "XRPUSDT:1h",
            ],
            "rollback_backlog_preserved": True,
            "rollback_consumed_cutoffs": {
                route: [boundary + (3_600_000 if route.endswith("1h") else 14_400_000)]
                for route, boundary in boundaries.items()
            },
        },
        "cutback": {
            "progress_cutoff_ms": boundaries,
            "entries": cutback_entries,
            "selected": {
                route: {
                    "last_id_through_progress": f"{boundary}-0",
                    "next_unread_id": f"{boundary + (3_600_000 if route.endswith('1h') else 14_400_000)}-0",
                    "no_legacy_cutoff_skipped": True,
                }
                for route, boundary in boundaries.items()
            },
            "strategy_groups": {
                route: {"exists": True, "pel": 0, "lag": 0}
                for route in TARGET_SIGNAL_ROUTES
            },
            "stale_decision": {"xadd_count": 0, "result": "DENIED"},
        },
        "emergency_rollback": {
            "decision_progress_ms": boundaries,
            "legacy_preserved_newer_cutoffs": {
                route: [boundary + (3_600_000 if route.endswith("1h") else 14_400_000)]
                for route, boundary in boundaries.items()
            },
            "legacy_processed_newer_cutoffs": {
                route: [boundary + (3_600_000 if route.endswith("1h") else 14_400_000)]
                for route, boundary in boundaries.items()
            },
            "dropped_cutoffs": [],
        },
        "final": {
            "owners": decision,
            "decision_ready": True,
            "active_authoritative_lanes": list(EXPECTED_LANES),
            "risk_runtime_healthy": True,
            "risk_pel": 0,
            "risk_lag": 0,
            "signals_have_decision_identity": True,
            "decision_shadow_keys": [],
        },
        "cleanup": {
            "docker_leftovers": [],
            "cache_leftovers": [],
            "unreconciled_notifications": 0,
            "clean": True,
        },
    }


def _records_exact(records: object, owner: str, epoch: int | None = None) -> bool:
    if not isinstance(records, Mapping) or set(records) != set(TARGET_SIGNAL_ROUTES):
        return False
    for route, value in records.items():
        if not isinstance(value, Mapping):
            return False
        if set(value) != {"schema_version", "route", "owner", "epoch", "boundary_ms"}:
            return False
        if (
            value["route"] != route
            or value["schema_version"] != 1
            or value["owner"] != owner
        ):
            return False
        if epoch is not None and value["epoch"] != epoch:
            return False
        if not isinstance(value["boundary_ms"], int) or value["boundary_ms"] < 0:
            return False
    return True


def _cutback_gate(raw: Mapping[str, object]) -> bool:
    progress = raw.get("progress_cutoff_ms")
    entries = raw.get("entries")
    selected = raw.get("selected")
    groups = raw.get("strategy_groups")
    if (
        not isinstance(progress, Mapping)
        or not isinstance(entries, Mapping)
        or not isinstance(selected, Mapping)
        or not isinstance(groups, Mapping)
        or set(groups) != set(TARGET_SIGNAL_ROUTES)
    ):
        return False
    if not all(
        isinstance(value, Mapping)
        and value.get("exists") is True
        and value.get("pel", value.get("pending")) == 0
        and isinstance(value.get("lag"), int)
        and value.get("lag") >= 0
        for value in groups.values()
    ):
        return False
    for route in TARGET_SIGNAL_ROUTES:
        if route not in progress or route not in entries or route not in selected:
            return False
        result = cutback_fast_forward_boundary(
            entries[route],
            progress_cutoff_ms=progress[route],
            timeframe="1h" if route.endswith("1h") else "4h",
        )
        selected_item = selected[route]
        if not isinstance(selected_item, Mapping):
            return False
        if any(
            key in selected_item and selected_item[key] != value
            for key, value in result.items()
        ):
            return False
    return True


def _progress_by_route(rows: object) -> dict[str, Mapping[str, object]]:
    if not isinstance(rows, list):
        return {}
    route_by_lane = dict(zip(EXPECTED_LANES, TARGET_SIGNAL_ROUTES, strict=True))
    result: dict[str, Mapping[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            return {}
        route = route_by_lane.get(row.get("lane_id"))
        if route is None:
            return {}
        result[route] = row
    return result


def _signal_keys(entries: object) -> set[tuple[object, object, object]]:
    if not isinstance(entries, list):
        return set()
    return {
        (item.get("stream"), item.get("entry_id"), item.get("idempotency_key"))
        for item in entries
        if isinstance(item, Mapping)
    }


def _authority_sequence_gate(authority: object) -> bool:
    if not isinstance(authority, Mapping):
        return False
    if authority.get("owner_timeline") != [
        "strategy@0",
        "decision@1",
        "strategy@2",
        "decision@3",
    ]:
        return False
    stages = (
        ("initial", "strategy", 0),
        ("after_cutover", "decision", 1),
        ("after_cutback", "strategy", 2),
        ("after_recutover", "decision", 3),
    )
    records: list[Mapping[str, object]] = []
    for name, owner, epoch in stages:
        value = authority.get(name)
        if not _records_exact(value, owner, epoch):
            return False
        records.append(value)  # type: ignore[arg-type]
    for route in TARGET_SIGNAL_ROUTES:
        boundaries = [int(stage[route]["boundary_ms"]) for stage in records]
        if boundaries != sorted(boundaries) or len(set(boundaries)) != 4:
            return False
    final = authority.get("broker_after_restart")
    if not isinstance(final, Mapping):
        return False
    return all(
        isinstance(final.get(route), Mapping)
        and final[route].get("owner") == "decision"
        and final[route].get("epoch") == 3
        and final[route].get("boundary_ms")
        == authority["after_recutover"][route]["boundary_ms"]
        for route in TARGET_SIGNAL_ROUTES
    )


def _publication_guard_gate(raw: Mapping[str, object]) -> bool:
    publication = raw.get("publication_guard")
    attempts = publication.get("attempts") if isinstance(publication, Mapping) else None
    if not isinstance(attempts, list):
        return False
    by_label = {
        item.get("label"): item for item in attempts if isinstance(item, Mapping)
    }
    expected = {
        "strategy-epoch-0-allowed": ("strategy", 0, 1, "PUBLISHED"),
        "decision-epoch-1-allowed": ("decision", 1, 1, "PUBLISHED"),
        "decision-boundary-equal-denied": (
            "decision",
            1,
            0,
            "DENIED",
        ),
        "stale-strategy-epoch-0-denied": ("strategy", 0, 0, "DENIED"),
        "stale-decision-exact-id-denied-after-cutback": (
            "decision",
            1,
            0,
            "DENIED",
        ),
        "stale-decision-epoch-1-denied-after-cutback": (
            "decision",
            1,
            0,
            "DENIED",
        ),
        "strategy-epoch-2-allowed": ("strategy", 2, 1, "PUBLISHED"),
        "stale-decision-epoch-1-denied-before-recutover": (
            "decision",
            1,
            0,
            "DENIED",
        ),
        "decision-epoch-3-allowed": ("decision", 3, 1, "PUBLISHED"),
        "stale-strategy-epoch-2-denied-after-recutover": (
            "strategy",
            2,
            0,
            "DENIED",
        ),
    }
    for label, (owner, epoch, count, result) in expected.items():
        item = by_label.get(label)
        if not isinstance(item, Mapping):
            return False
        if (
            item.get("owner") != owner
            or item.get("expected_epoch") != epoch
            or item.get("xadd_count") != count
            or item.get("result") != result
        ):
            return False
    return len(by_label) == len(expected)


def _concurrent_race_gate(trial: object) -> bool:
    if not isinstance(trial, Mapping):
        return False
    race = trial.get("concurrent_race")
    if (
        not isinstance(race, Mapping)
        or race.get("synchronization") != "asyncio.Barrier(2)"
    ):
        return False
    attempts = race.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != 2:
        return False
    by_label = {
        item.get("label"): item for item in attempts if isinstance(item, Mapping)
    }
    expected = {
        "concurrent-stale-strategy-epoch-0-denied-at-epoch-2": (
            0,
            0,
            "DENIED",
        ),
        "concurrent-strategy-epoch-2-allowed": (2, 1, "PUBLISHED"),
    }
    if set(by_label) != set(expected):
        return False
    return all(
        item.get("expected_epoch") == expected_epoch
        and item.get("xadd_count") == xadd_count
        and item.get("result") == result
        and item.get("owner") == "strategy"
        for label, (expected_epoch, xadd_count, result) in expected.items()
        for item in (by_label[label],)
    )


def _post_stop_boundary_gate(trial: object) -> bool:
    if not isinstance(trial, Mapping):
        return False
    legacy = trial.get("legacy")
    if not isinstance(legacy, Mapping):
        return False
    preliminary = legacy.get("preliminary_boundaries")
    final = legacy.get("boundaries")
    post_stop = legacy.get("post_stop_boundary")
    restored = legacy.get("restored_boundary_after_stop")
    restored_final = legacy.get("legacy_boundary_after_restore_stop")
    return not (
        not isinstance(preliminary, list)
        or not isinstance(final, list)
        or preliminary == final
        or not isinstance(post_stop, Mapping)
        or post_stop.get("stable") is not True
        or post_stop.get("first") != post_stop.get("second")
        or post_stop.get("final")
        != {
            item.get("route"): item
            for item in final
            if isinstance(item, Mapping) and item.get("route") is not None
        }
        or not isinstance(restored, Mapping)
        or restored.get("stable") is not True
        or restored.get("first") != restored.get("second")
        or restored.get("final")
        != {
            item.get("route"): item
            for item in restored_final or []
            if isinstance(item, Mapping) and item.get("route") is not None
        }
        or legacy.get("legacy_boundary_stable_before_recutover") is not True
    )


def _post_stop_progress_gate(trial: object) -> bool:
    if not isinstance(trial, Mapping):
        return False
    progress = trial.get("progress")
    if not isinstance(progress, Mapping):
        return False
    after_stop = progress.get("decision_progress_after_stop")
    stable = progress.get("decision_progress_stable")
    return (
        isinstance(after_stop, list)
        and isinstance(stable, Mapping)
        and stable.get("stable") is True
        and stable.get("first") == stable.get("second")
        and stable.get("final") == after_stop
    )


def _measured_trial_gate(trial: object) -> bool:
    if not isinstance(trial, Mapping):
        return False
    if trial.get("evidence_origin") != "measured_disposable":
        return False
    if trial.get("real_disposable_stack") is not True:
        return False
    if not _authority_sequence_gate(trial.get("authority")):
        return False
    if not _publication_guard_gate(trial):
        return False
    if not _concurrent_race_gate(trial):
        return False
    legacy = trial.get("legacy")
    if not isinstance(legacy, Mapping):
        return False
    pre = legacy.get("strategy_active_before")
    post = legacy.get("target_workers_after")
    restored = legacy.get("restored_strategy_catalog")
    if not all(isinstance(item, Mapping) for item in (pre, post, restored)):
        return False
    if pre.get("discovered_pair_count") != 3 or set(pre.get("routes", [])) != {
        "BTCUSDT:1h",
        "BTCUSDT:4h",
        "ETHUSDT:4h",
    }:
        return False
    if post.get("discovered_pair_count") != 4 or set(post.get("routes", [])) != {
        "BNBUSDT:30m",
        "DOGEUSDT:4h",
        "SOLUSDT:1h",
        "XRPUSDT:1h",
    }:
        return False
    if restored.get("discovered_pair_count") != 3 or set(
        restored.get("routes", [])
    ) != {
        "BTCUSDT:1h",
        "BTCUSDT:4h",
        "ETHUSDT:4h",
    }:
        return False
    preliminary_boundaries = legacy.get("preliminary_boundaries")
    final_boundaries = legacy.get("boundaries")
    post_stop = legacy.get("post_stop_boundary")
    restored_preliminary = legacy.get("restored_boundaries_preliminary")
    restored_after_stop = legacy.get("restored_boundary_after_stop")
    final_by_route = (
        {
            item.get("route"): item
            for item in final_boundaries
            if isinstance(item, Mapping) and item.get("route") is not None
        }
        if isinstance(final_boundaries, list)
        else {}
    )
    restored_final_by_route = {
        item.get("route"): item
        for item in legacy.get("legacy_boundary_after_restore_stop", [])
        if isinstance(item, Mapping) and item.get("route") is not None
    }
    if (
        not isinstance(preliminary_boundaries, list)
        or not isinstance(final_boundaries, list)
        or not isinstance(post_stop, Mapping)
        or post_stop.get("stable") is not True
        or post_stop.get("first") != post_stop.get("second")
        or post_stop.get("final") != final_by_route
        or preliminary_boundaries == final_boundaries
        or not isinstance(restored_preliminary, list)
        or not isinstance(restored_after_stop, Mapping)
        or restored_after_stop.get("stable") is not True
        or restored_after_stop.get("first") != restored_after_stop.get("second")
        or restored_after_stop.get("final") != restored_final_by_route
        or legacy.get("legacy_boundary_stable_before_recutover") is not True
    ):
        return False
    risk = trial.get("risk")
    if not isinstance(risk, Mapping):
        return False
    for key in ("pre_cutover_groups", "post_cutover", "final_groups"):
        value = risk.get(key)
        if key == "post_cutover":
            value = value.get("groups") if isinstance(value, Mapping) else None
        if not isinstance(value, Mapping) or set(value) != set(TARGET_SIGNAL_ROUTES):
            return False
        if not all(
            isinstance(group, Mapping)
            and group.get("exists") is True
            and group.get("pending") == 0
            and group.get("lag") == 0
            for group in value.values()
        ):
            return False
    for key in ("after_strategy_stop", "after_decision_stop", "before_recutover"):
        value = risk.get(key)
        if (
            not isinstance(value, Mapping)
            or set(value) != set(TARGET_SIGNAL_ROUTES)
            or not all(
                isinstance(group, Mapping)
                and group.get("exists") is True
                and group.get("pending") == 0
                and group.get("lag") == 0
                for group in value.values()
            )
        ):
            return False
    progress = trial.get("progress")
    if not isinstance(progress, Mapping):
        return False
    seed = _progress_by_route(progress.get("seed"))
    live = _progress_by_route(progress.get("live"))
    restart = _progress_by_route(progress.get("restart"))
    recovery = _progress_by_route(progress.get("recovery"))
    final = _progress_by_route(progress.get("final"))
    if set(seed) != set(TARGET_SIGNAL_ROUTES) or set(live) != set(seed):
        return False
    if (
        set(restart) != set(seed)
        or set(recovery) != set(seed)
        or set(final) != set(seed)
    ):
        return False
    if any(seed[route].get("last_disposition") is not None for route in seed):
        return False
    if any(
        live[route].get("last_disposition") not in {"published", "no_signal"}
        or int(_iso_ms(live[route].get("market_as_of")))
        <= int(seed[route].get("market_as_of_ms", -1))
        for route in seed
    ):
        return False
    if any(
        restart[route] != live[route]
        or int(_iso_ms(recovery[route].get("market_as_of")))
        < int(_iso_ms(restart[route].get("market_as_of")))
        for route in seed
    ):
        return False
    progress_after_stop = progress.get("decision_progress_after_stop")
    progress_stable = progress.get("decision_progress_stable")
    if (
        not isinstance(progress_after_stop, list)
        or not isinstance(progress_stable, Mapping)
        or progress_stable.get("stable") is not True
        or progress_stable.get("first") != progress_stable.get("second")
        or progress_stable.get("final") != progress_after_stop
    ):
        return False
    cutback = trial.get("cutback")
    if not isinstance(cutback, Mapping) or not _cutback_gate(cutback):
        return False
    if any(
        final[route].get("last_disposition") is not None
        or int(_iso_ms(final[route].get("market_as_of")))
        != int(trial["authority"]["after_recutover"][route]["boundary_ms"])
        for route in seed
    ):
        return False
    decision = trial.get("decision")
    if not isinstance(decision, Mapping):
        return False
    for key in (
        "startup",
        "restart_ready",
        "recovery_ready",
        "final_ready",
        "broker_ready",
    ):
        if key == "startup":
            if decision.get(key, {}).get("status") != "ready":
                return False
        elif (
            not isinstance(decision.get(key), Mapping)
            or decision[key].get("status") != "ready"
        ):
            return False
    events = decision.get("post_cutover_events")
    if not isinstance(events, list) or {item.get("route") for item in events} != set(
        TARGET_SIGNAL_ROUTES
    ):
        return False
    statuses = {item.get("policy_status") for item in events}
    if not {"SIGNAL", "NO_SIGNAL"}.issubset(statuses):
        return False
    signals = decision.get("post_cutover_signals")
    if not isinstance(signals, list):
        return False
    if any(
        item.get("model_name") not in {"m4-btc-1h", "m4-btc-4h", "m4-eth-4h"}
        for item in signals
    ):
        return False
    if decision.get("no_authoritative_shadow") is not True:
        return False
    if _signal_keys(decision.get("restart_signals")) != _signal_keys(
        decision.get("live_signals")
    ):
        return False
    if not _signal_keys(decision.get("recovery_signals")).issuperset(
        _signal_keys(decision.get("restart_signals"))
    ):
        return False
    final_signals = decision.get("final_signals")
    return isinstance(final_signals, list) and len(
        {(item.get("stream"), item.get("entry_id")) for item in final_signals}
    ) == len(final_signals)


def _iso_ms(value: object) -> int:
    if not isinstance(value, str):
        raise TypeError("measured progress cutoff is not ISO text")
    return int(datetime.fromisoformat(value).timestamp() * 1000)


def _identity_payload(artifact: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": artifact.get("schema_version"),
        "D11B_BASE_SHA": artifact.get("D11B_BASE_SHA"),
        "d11a_integration_commit": artifact.get("d11a_integration_commit"),
        "protected_hashes": artifact.get("protected_hashes"),
        "production_config_hashes": artifact.get("production_config_hashes"),
        "m4_route_identity": artifact.get("m4_route_identity"),
        "authoritative_routes": artifact.get("authoritative_routes"),
    }


def _evidence_payload(
    artifact: Mapping[str, object], gates: Mapping[str, bool]
) -> dict[str, object]:
    return {
        "raw_evidence": artifact.get("raw_evidence"),
        "gates": gates,
        "source_hashes": artifact.get("source_hashes"),
    }


def evaluate_artifact(
    artifact: Mapping[str, object], *, verify_digests: bool = True
) -> tuple[dict[str, bool], str]:
    protected = artifact.get("protected_hashes")
    sources = artifact.get("source_hashes")
    configs = artifact.get("production_config_hashes")
    raw = artifact.get("raw_evidence")
    if not isinstance(raw, Mapping):
        raw = {}
    authority = raw.get("authority", {})
    legacy = raw.get("legacy", {})
    risk = raw.get("risk", {})
    decision = raw.get("decision", {})
    strategy = raw.get("strategy", legacy)
    progress = raw.get("progress", {})
    cutback = raw.get("cutback", {})
    emergency = raw.get("emergency_rollback", {})
    final = raw.get("final", {})
    gates = {
        "measured_evidence_origin": _measured_evidence_origin(raw),
        "protected_evidence": protected == EXPECTED_PROTECTED_HASHES
        and protected_hashes() == EXPECTED_PROTECTED_HASHES,
        "source_lock": historical_source_lock(sources),
        "production_config_lock": historical_production_config_lock(configs)
        and set(Path(ROOT / "configs/decision/assets").glob("*.yaml"))
        == {
            ROOT / "configs/decision/assets/BTC.yaml",
            ROOT / "configs/decision/assets/ETH.yaml",
        },
        "execution_mode_paper": execution_mode_is_paper(),
        "m4_route_identity": isinstance(artifact.get("m4_route_identity"), Mapping)
        and artifact["m4_route_identity"].get("current")
        == artifact["m4_route_identity"].get("certified"),
        "authority_contract": authority.get("routes") == list(TARGET_SIGNAL_ROUTES)
        and _records_exact(authority.get("initial"), "strategy", 0)
        and _records_exact(authority.get("after_cutover"), "decision", 1),
        "authority_fence_sequence": _authority_sequence_gate(authority),
        "initial_strategy_owner": _records_exact(
            authority.get("initial"), "strategy", 0
        ),
        "atomic_three_route_cutover": _records_exact(
            authority.get("after_cutover"), "decision", 1
        )
        and authority.get("partial_cutover_rejected") is True
        and authority.get("partial_cutover_before")
        == authority.get("partial_cutover_after"),
        "no_dual_authority_write": (
            _publication_guard_gate(raw)
            or all(
                (
                    item.get("xadd_count")
                    == (1 if item.get("owner") == item.get("expected_owner") else 0)
                )
                and (
                    item.get("result")
                    == (
                        "PUBLISHED"
                        if item.get("owner") == item.get("expected_owner")
                        else "DENIED"
                    )
                )
                for item in (
                    raw.get("publication_guard", {}).get("attempts", [])
                    if isinstance(raw.get("publication_guard"), Mapping)
                    else []
                )
            )
        ),
        "no_zero_owner_record": all(
            item.get("owner") in {"strategy", "decision"}
            for item in authority.get("owner_timeline", [])
            if isinstance(item, Mapping)
        )
        and bool(authority.get("owner_timeline")),
        "legacy_boundary_exact": len(legacy.get("boundaries", [])) == 3
        and {
            item.get("route")
            for item in legacy.get("boundaries", [])
            if isinstance(item, Mapping)
        }
        == set(TARGET_SIGNAL_ROUTES)
        and all(
            item.get("close_cutoff_ms")
            == feature_close_cutoff_ms(
                item.get("feature_timestamp_ms"), item.get("timeframe")
            )
            and item.get("strategy_group", {}).get("exists") is True
            and item.get("strategy_group", {}).get("pending") == 0
            and isinstance(item.get("strategy_group", {}).get("lag"), int)
            and item.get("strategy_group", {}).get("lag") >= 0
            for item in legacy.get("boundaries", [])
            if isinstance(item, Mapping)
        ),
        "post_stop_legacy_boundary": all(
            _post_stop_boundary_gate(trial) for trial in raw.get("measured_trials", [])
        ),
        "risk_pre_cutover_quiescent": all(
            validate_group_quiescence(
                pel_count=value.get("pel", value.get("pending")),
                lag=value.get("lag"),
            )
            for value in risk.get("pre_cutover_groups", {}).values()
            if isinstance(value, Mapping)
        )
        and set(risk.get("pre_cutover_groups", {})) == set(TARGET_SIGNAL_ROUTES),
        "effect_progress_seed_exact": all(
            item.get("last_disposition") is None
            and item.get("market_as_of_ms")
            == raw.get("legacy", {}).get("boundaries", [])[index].get("close_cutoff_ms")
            for index, item in enumerate(progress.get("seed", []))
            if isinstance(item, Mapping)
        )
        and len(progress.get("seed", [])) == 3,
        "signal_head_preflight": len(legacy.get("signal_head_preflight", [])) == 3
        and all(
            signal_head_preflight(
                item.get("head_id"),
                boundary_ms=next(
                    value
                    for value in raw["legacy"]["boundaries"]
                    if value["route"] == item["route"]
                )["close_cutoff_ms"],
                trigger_timeframe="1h" if item["route"].endswith("1h") else "4h",
            )
            for item in legacy.get("signal_head_preflight", [])
            if isinstance(item, Mapping)
        ),
        "decision_startup_owner_preflight": (
            decision.get("startup", {}).get("ready") is True
            or decision.get("startup", {}).get("status") == "ready"
        )
        and _records_exact(
            decision.get("startup", {}).get("owner_records"), "decision", 1
        )
        and set(decision.get("startup", {}).get("active_lanes", []))
        == set(EXPECTED_LANES),
        "post_cutover_authoritative_flow": len(decision.get("post_cutover_events", []))
        == 3
        and {
            item.get("route")
            for item in decision.get("post_cutover_events", [])
            if isinstance(item, Mapping)
        }
        == set(TARGET_SIGNAL_ROUTES)
        and all(
            item.get("progress_disposition") in {"published", "no_signal"}
            and (
                item.get("publication_outcome") == "PUBLISHED"
                if item.get("progress_disposition") == "published"
                else item.get("publication_outcome") is None
            )
            for item in decision.get("post_cutover_events", [])
            if isinstance(item, Mapping)
        ),
        "post_cutover_risk_continuity": (
            (
                set(risk.get("post_cutover", {}).get("groups", {}))
                == set(TARGET_SIGNAL_ROUTES)
                and all(
                    isinstance(group, Mapping)
                    and group.get("exists") is True
                    and validate_group_quiescence(
                        pel_count=group.get("pending"), lag=group.get("lag")
                    )
                    for group in risk.get("post_cutover", {}).get("groups", {}).values()
                )
            )
            if "groups" in risk.get("post_cutover", {})
            else risk.get("post_cutover", {}).get("acked_model_names")
            == ["m4-btc-1h", "m4-btc-4h", "m4-eth-4h"]
            and validate_group_quiescence(
                pel_count=risk.get("post_cutover", {}).get("pel"),
                lag=risk.get("post_cutover", {}).get("lag"),
            )
        ),
        "restart_catchup_exact": (
            (
                progress.get("restart", {}).get("expected_cutoffs")
                == progress.get("restart", {}).get("observed_cutoffs")
                and progress.get("restart", {}).get("duplicate_count") == 0
                and decision.get("restart", {}).get("catchup_before_new_input") is True
                and decision.get("restart", {}).get("no_duplicate_ids") is True
            )
            if isinstance(progress.get("restart"), Mapping)
            and "expected_cutoffs" in progress.get("restart", {})
            else progress.get("restart") == progress.get("live")
            and isinstance(decision.get("restart_signals"), list)
            and _signal_keys(decision.get("restart_signals"))
            == _signal_keys(decision.get("live_signals"))
            and isinstance(decision.get("recovery_signals"), list)
            and len(_signal_keys(decision.get("recovery_signals")))
            >= len(_signal_keys(decision.get("restart_signals")))
            and progress.get("catchup_before_new_input") is True
        ),
        "decision_progress_stable_after_stop": all(
            _post_stop_progress_gate(trial) for trial in raw.get("measured_trials", [])
        ),
        "broker_authority_persistence": decision.get("broker_restart", {}).get(
            "named_volume_preserved"
        )
        is True
        and decision.get("broker_restart", {}).get("before")
        == decision.get("broker_restart", {}).get("after")
        and _records_exact(
            decision.get("broker_restart", {}).get("after"), "decision", 3
        ),
        "legacy_target_workers_relinquished": (
            (
                isinstance(strategy.get("target_workers_after"), Mapping)
                and strategy["target_workers_after"].get("discovered_pair_count") == 4
                and set(strategy["target_workers_after"].get("routes", []))
                == {"BNBUSDT:30m", "DOGEUSDT:4h", "SOLUSDT:1h", "XRPUSDT:1h"}
            )
            or (
                strategy.get("target_workers_after") == []
                and set(strategy.get("catalog_after", []))
                == {"BNBUSDT:30m", "DOGEUSDT:4h", "SOLUSDT:1h", "XRPUSDT:1h"}
            )
        ),
        "unrelated_legacy_routes_preserved": (
            set(strategy.get("unrelated_routes", []))
            == {"BNBUSDT:30m", "DOGEUSDT:4h", "SOLUSDT:1h", "XRPUSDT:1h"}
            if "unrelated_routes" in strategy
            else legacy.get("unrelated_routes_preserved") is True
        ),
        "stale_strategy_denied": _publication_guard_gate(raw)
        or any(
            item.get("expected_owner") == "strategy"
            and item.get("owner") == "decision"
            and item.get("xadd_count") == 0
            for item in raw.get("publication_guard", {}).get("attempts", [])
        ),
        "cutback_fast_forward_exact": _cutback_gate(cutback),
        "atomic_three_route_cutback": _records_exact(
            authority.get("after_cutback"), "strategy", 2
        )
        and authority.get("cutback_epochs")
        == {route: [1, 2] for route in TARGET_SIGNAL_ROUTES}
        and authority.get("partial_cutback_rejected") is True
        and authority.get("partial_cutback_before")
        == authority.get("partial_cutback_after"),
        "stale_decision_denied": cutback.get("stale_decision", {}).get("xadd_count")
        == 0
        and cutback.get("stale_decision", {}).get("result") == "DENIED",
        "emergency_rollback_no_loss": emergency.get("dropped_cutoffs") == []
        and emergency.get("legacy_preserved_newer_cutoffs")
        == emergency.get("legacy_processed_newer_cutoffs"),
        "final_steady_state": _records_exact(final.get("owners"), "decision", 3)
        and final.get("decision_ready") is True
        and set(final.get("active_authoritative_lanes", [])) == set(EXPECTED_LANES)
        and final.get("risk_pel") == 0
        and final.get("risk_lag") == 0
        and final.get("signals_have_decision_identity") is True,
        "cleanup": (
            raw.get("cleanup", {}).get("clean") is True
            and all(
                trial.get("clean") is True
                and not any(trial.get("leftovers", {}).values())
                for trial in (
                    raw.get("cleanup", {}).get("trial_a", {}),
                    raw.get("cleanup", {}).get("trial_b", {}),
                )
            )
            if "trial_a" in raw.get("cleanup", {})
            else raw.get("cleanup", {}).get("clean") is True
            and raw.get("cleanup", {}).get("docker_leftovers") == []
            and raw.get("cleanup", {}).get("cache_leftovers") == []
            and raw.get("cleanup", {}).get("unreconciled_notifications") == 0
        ),
    }
    execution = raw.get("execution", {})
    decision_container = (
        execution.get("decision_container", {})
        if isinstance(execution, Mapping)
        else {}
    )
    initial_owner_startup = (
        execution.get("initial_owner_startup", {})
        if isinstance(execution, Mapping)
        else {}
    )
    gates["real_disposable_topology"] = (
        isinstance(execution, Mapping)
        and _measured_evidence_origin(raw)
        and all(_measured_trial_gate(trial) for trial in raw.get("measured_trials", []))
        and execution.get("real_disposable_stack") is True
        and set(execution.get("services", []))
        == {
            "db",
            "broker",
            "signal-worker",
            "strategy-worker",
            "decision",
            "risk-worker",
        }
        and execution.get("dynamic_ports") is True
        and execution.get("normal_root_state_used") is False
        and execution.get("compose_rendered") is True
        and execution.get("repository_dockerfile_built") is True
        and isinstance(decision_container, Mapping)
        and decision_container.get("healthy") is True
        and isinstance(initial_owner_startup, Mapping)
        and initial_owner_startup.get("startup_failed_closed") is True
    )
    measured_trials = raw.get("measured_trials", [])
    gates["strategy_authority_activation"] = (
        isinstance(measured_trials, list)
        and len(measured_trials) == 2
        and all(
            isinstance(trial, Mapping)
            and isinstance(trial.get("execution"), Mapping)
            and trial["execution"].get("strategy_authority_enforced") is True
            for trial in measured_trials
        )
    )
    trials = raw.get("measured_trials", [])
    trial_parity = raw.get("trial_parity", {})
    gates["measured_trial_sequence"] = (
        isinstance(trials, list)
        and len(trials) == 2
        and all(_measured_trial_gate(trial) for trial in trials)
    )
    gates["concurrent_authority_race"] = (
        isinstance(trials, list)
        and len(trials) == 2
        and all(_concurrent_race_gate(trial) for trial in trials)
    )
    gates["measured_trial_parity"] = (
        isinstance(trial_parity, Mapping)
        and trial_parity.get("matches") is True
        and trial_parity.get("trial_a_digest") == trial_parity.get("trial_b_digest")
    )
    gates["measured_cleanup"] = (
        isinstance(raw.get("cleanup"), Mapping)
        and raw["cleanup"].get("clean") is True
        and raw["cleanup"].get("trial_a", {}).get("clean") is True
        and raw["cleanup"].get("trial_b", {}).get("clean") is True
    )
    if verify_digests:
        base_gates = gates.copy()
        gates["identity_digest_integrity"] = artifact.get(
            "identity_digest"
        ) == sha256_fingerprint(_identity_payload(artifact))
        gates["evidence_digest_integrity"] = artifact.get(
            "evidence_digest"
        ) == sha256_fingerprint(_evidence_payload(artifact, base_gates))
    status = SUCCESS_STATUS if all(gates.values()) else BLOCKED_STATUS
    return gates, status


def build_artifact() -> dict[str, object]:
    return build_artifact_from_raw(build_raw_evidence())


def build_artifact_from_raw(raw: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(raw, Mapping):
        raise TypeError("raw D11B evidence must be a mapping")
    raw = dict(raw)
    artifact: dict[str, object] = {
        "schema_version": "decision.d11b.authority_cutover.v1",
        "D11B_BASE_SHA": D11B_BASE_SHA,
        "d11a_integration_commit": D11A_INTEGRATION_COMMIT,
        "protected_hashes": protected_hashes(),
        "source_hashes": current_source_hashes(),
        "production_config_hashes": production_config_hashes(),
        "m4_route_identity": m4_route_identity(),
        "authoritative_routes": list(TARGET_SIGNAL_ROUTES),
        "authoritative_lanes": list(EXPECTED_LANES),
        "raw_evidence": raw,
    }
    identity_payload = {
        "schema_version": artifact["schema_version"],
        "D11B_BASE_SHA": D11B_BASE_SHA,
        "d11a_integration_commit": D11A_INTEGRATION_COMMIT,
        "protected_hashes": artifact["protected_hashes"],
        "production_config_hashes": artifact["production_config_hashes"],
        "m4_route_identity": artifact["m4_route_identity"],
        "authoritative_routes": artifact["authoritative_routes"],
    }
    gates, _status = evaluate_artifact(artifact, verify_digests=False)
    evidence_payload = _evidence_payload(artifact, gates)
    artifact["identity_digest"] = sha256_fingerprint(identity_payload)
    artifact["evidence_digest"] = sha256_fingerprint(evidence_payload)
    final_gates, final_status = evaluate_artifact(artifact)
    artifact["gates"] = final_gates
    artifact["terminal_status"] = final_status
    return artifact


def build_artifact_from_measured(raw: Mapping[str, object]) -> dict[str, object]:
    """Build an artifact only from a real disposable-trial evidence payload."""

    if (
        not isinstance(raw, Mapping)
        or raw.get("evidence_origin") != "measured_disposable"
    ):
        raise ValueError("D11B artifact requires measured disposable evidence")
    trials = raw.get("measured_trials")
    if not isinstance(trials, list) or len(trials) != 2:
        raise ValueError("D11B artifact requires exactly two measured trials")
    return build_artifact_from_raw(raw)


def _measured_evidence_origin(raw: Mapping[str, object]) -> bool:
    trials = raw.get("measured_trials")
    if raw.get("evidence_origin") != "measured_disposable":
        return False
    if not isinstance(trials, list) or len(trials) != 2:
        return False
    return all(
        isinstance(trial, Mapping)
        and trial.get("evidence_origin") == "measured_disposable"
        and trial.get("real_disposable_stack") is True
        for trial in trials
    )


__all__ = [
    "ARTIFACT_PATH",
    "BLOCKED_STATUS",
    "D11A_INTEGRATION_COMMIT",
    "D11B_BASE_SHA",
    "EXPECTED_LANES",
    "EXPECTED_PROTECTED_HASHES",
    "PROTECTED_ARTIFACTS",
    "ROOT",
    "SOURCE_PATHS",
    "SUCCESS_STATUS",
    "build_artifact",
    "build_artifact_from_measured",
    "build_artifact_from_raw",
    "build_raw_evidence",
    "canonical_json",
    "current_source_hashes",
    "evaluate_artifact",
    "file_sha256",
    "m4_route_identity",
    "production_config_hashes",
    "protected_hashes",
    "route_identity",
    "sha256_fingerprint",
]
