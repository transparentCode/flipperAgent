"""Fail-closed D11C artifact construction and gate evaluation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import yaml

from scripts.decision_d11b_authority_cutover import (
    cutback_fast_forward_boundary,
    market_bar_identity_fingerprint,
)

ROOT = Path(__file__).resolve().parents[2]
D11C_BASE_SHA = "78a88f9e7db0561d49f261404fb0372de073a65d"
SUCCESS_STATUS = "DECISION_D11C_DEFAULT_TOPOLOGY_PROMOTION_READY_FOR_REVIEW"
BLOCKED_STATUS = "DECISION_D11C_DEFAULT_TOPOLOGY_DEFECT_REQUIRES_REMEDIATION"
EXPECTED_STRATEGY_ROUTES = (
    "BNBUSDT:30m",
    "BTCUSDT:1h",
    "BTCUSDT:4h",
    "DOGEUSDT:1h",
    "DOGEUSDT:4h",
    "ETHUSDT:4h",
    "SOLUSDT:1h",
    "XRPUSDT:1h",
)
TARGET_ROUTES = ("BTCUSDT:1h", "BTCUSDT:4h", "ETHUSDT:4h")
UNRELATED_ROUTES = tuple(
    route for route in EXPECTED_STRATEGY_ROUTES if route not in TARGET_ROUTES
)
EXPECTED_PROTECTED_HASHES = {
    "d11b": "9bf16504f114eae000fc4006712731e93f15815c0827cf18af8864aa4f74b05d",
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
    "d11b": ROOT / "artifacts/decision_d11b/d11b_authority_cutover_certification.json",
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
    "src/apps/strategy_app/runtime/runner.py",
    "src/apps/strategy_app/settings.py",
    "configs/models.yaml",
    "docker-compose.yml",
    "tests/decision/test_d11c_default_topology.py",
    "tests/combined/fixtures/d11c/docker-compose.yml",
    "tests/combined/d11c_real.py",
    "tests/combined/d11c_harness.py",
    "tests/combined/integration/test_decision_d11c_default_topology.py",
    "tests/combined/d11b_harness.py",
    "tests/combined/d11b_real.py",
    "tests/combined/d11a_harness.py",
    "tests/combined/c4a_harness.py",
    "tests/decision/test_d11b_authority_cutover.py",
    "tests/decision/test_d11b_certification.py",
    "scripts/decision_d11b_authority_cutover.py",
    "scripts/certify_decision_d11c_default_topology.py",
    "tests/combined/fixtures/d11c/configs/ingestion/global.yaml",
    "tests/combined/fixtures/d11c/configs/ingestion/assets/VOID.yaml",
    "docs/decision_authority_operations.md",
    "docs/docker_topology.md",
)
PRODUCTION_CONFIG_PATHS = (
    "configs/models.yaml",
    "configs/execution.yaml",
    "configs/risk.yaml",
    "configs/features.yaml",
    "configs/decision/global.yaml",
    "configs/decision/assets/BTC.yaml",
    "configs/decision/assets/ETH.yaml",
    "docker-compose.yml",
)
ARTIFACT_PATH = (
    ROOT / "artifacts/decision_d11c/d11c_default_topology_promotion_certification.json"
)

ROUTE_TIMEFRAMES = {
    "BTCUSDT:1h": "1h",
    "BTCUSDT:4h": "4h",
    "ETHUSDT:4h": "4h",
}
EXPECTED_SERVICES = (
    "db",
    "broker",
    "ingestion",
    "signal-worker",
    "strategy-worker",
    "decision",
    "risk-worker",
    "execution-worker",
)
EXPECTED_RESOURCE_PHASES = {
    "resources_strategy_zero": {
        service: service != "decision" for service in EXPECTED_SERVICES
    },
    "resources_decision1": {
        service: service != "strategy-worker" for service in EXPECTED_SERVICES
    },
    "resources_before_cold_restart": {
        service: service != "strategy-worker" for service in EXPECTED_SERVICES
    },
    "resources_cold_restart": {service: True for service in EXPECTED_SERVICES},
    "resources_strategy_two": {
        service: service != "decision" for service in EXPECTED_SERVICES
    },
    "resources_final": {service: True for service in EXPECTED_SERVICES},
}
DUPLICATE_GATE_NAMES = (
    "logical_cutoff_continuity",
    "bootstrap_duplicates_decision_owned",
    "decision_owned_duplicate_runs_collapsed",
    "cutback_setid_after_last_decision_owned_replay",
    "post_progress_duplicates_absent",
    "market_bar_duplicate_identity_consistent",
    "retention_anchor_preserved",
)


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8")
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


def production_config_hashes() -> dict[str, str]:
    return {path: file_sha256(ROOT / path) for path in PRODUCTION_CONFIG_PATHS}


def _stat_mem_bytes(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    value = value.split("/", 1)[0].strip()
    match = re.match(r"^\s*([0-9.]+)\s*([KMGTP]i?B?|B)\s*$", value)
    if match is None:
        return None
    number = float(match.group(1))
    multiplier = {
        "B": 1,
        "K": 1024,
        "M": 1024**2,
        "G": 1024**3,
        "T": 1024**4,
        "P": 1024**5,
        "KB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "KiB": 1024,
        "MiB": 1024**2,
        "GiB": 1024**3,
        "TB": 1000**4,
        "TiB": 1024**4,
    }[match.group(2)]
    return int(number * multiplier)


def _compose_resource_limits() -> dict[str, dict[str, float | int]]:
    document = yaml.safe_load(
        (ROOT / "tests/combined/fixtures/d11c/docker-compose.yml").read_text()
    )
    services = document.get("services") if isinstance(document, Mapping) else None
    if not isinstance(services, Mapping) or set(services) != set(EXPECTED_SERVICES):
        return {}
    limits: dict[str, dict[str, float | int]] = {}
    for service in EXPECTED_SERVICES:
        definition = services.get(service)
        deploy = definition.get("deploy") if isinstance(definition, Mapping) else None
        resources = deploy.get("resources") if isinstance(deploy, Mapping) else None
        values = resources.get("limits") if isinstance(resources, Mapping) else None
        if not isinstance(values, Mapping):
            return {}
        memory = _stat_mem_bytes(values.get("memory"))
        try:
            cpu = float(values["cpus"])
        except (KeyError, TypeError, ValueError):
            return {}
        if memory is None:
            return {}
        limits[service] = {"memory_bytes": memory, "cpus": cpu}
    return limits


def _resource_gate(trials: list[Mapping[str, object]]) -> bool:
    limits = _compose_resource_limits()
    if set(limits) != set(EXPECTED_SERVICES):
        return False
    total_memory = sum(int(item["memory_bytes"]) for item in limits.values())
    total_cpu = sum(float(item["cpus"]) for item in limits.values())
    if total_memory != int(4.25 * 1024**3) or total_cpu != 4.0:
        return False
    trial_snapshots: list[Mapping[str, object]] = []
    for trial in trials:
        for key in EXPECTED_RESOURCE_PHASES:
            value = trial.get(key)
            if not isinstance(value, Mapping):
                return False
            trial_snapshots.append(value)
    if len(trial_snapshots) != len(trials) * len(EXPECTED_RESOURCE_PHASES):
        return False
    for phase_key, expected_states in EXPECTED_RESOURCE_PHASES.items():
        for trial in trials:
            snapshot = trial.get(phase_key)
            if not isinstance(snapshot, Mapping) or set(snapshot) != set(
                EXPECTED_SERVICES
            ):
                return False
            aggregate_rss = 0
            aggregate_cpu = 0.0
            for service, expected_running in expected_states.items():
                sample = snapshot.get(service)
                if (
                    not isinstance(sample, Mapping)
                    or sample.get("running") is not expected_running
                ):
                    return False
                state = sample.get("state")
                if not isinstance(state, Mapping):
                    return False
                if expected_running:
                    if (
                        not sample.get("container_id")
                        or state.get("Running") is not True
                    ):
                        return False
                    if (
                        state.get("OOMKilled") is not False
                        or state.get("Restarting") is not False
                        or sample.get("restart_count") != 0
                    ):
                        return False
                    stats = sample.get("stats")
                    if not isinstance(stats, Mapping):
                        return False
                    rss = _stat_mem_bytes(stats.get("MemUsage"))
                    if rss is None or rss >= int(limits[service]["memory_bytes"]):
                        return False
                    cpu = str(stats.get("CPUPerc", "")).rstrip("%").strip()
                    try:
                        aggregate_cpu += float(cpu) / 100.0
                    except ValueError:
                        return False
                    aggregate_rss += rss
                elif state.get("Running") is True:
                    return False
            if aggregate_rss >= 5 * 1024**3 or aggregate_rss >= 8 * 1024**3:
                return False
            if aggregate_cpu > 4.0:
                return False
    return True


def _false_duplicate_gates() -> dict[str, bool]:
    return {name: False for name in DUPLICATE_GATE_NAMES}


def _valid_authority_stage(rows: object, *, owner: str, epoch: int) -> bool:
    if not isinstance(rows, Mapping) or set(rows) != set(TARGET_ROUTES):
        return False
    for route in TARGET_ROUTES:
        value = rows.get(route)
        if not isinstance(value, Mapping):
            return False
        if set(value) != {"schema_version", "route", "owner", "epoch", "boundary_ms"}:
            return False
        if (
            value.get("schema_version") != 1
            or value.get("route") != route
            or value.get("owner") != owner
            or value.get("epoch") != epoch
            or isinstance(value.get("epoch"), bool)
            or not isinstance(value.get("epoch"), int)
            or isinstance(value.get("boundary_ms"), bool)
            or not isinstance(value.get("boundary_ms"), int)
            or value.get("boundary_ms") < 0
        ):
            return False
    return True


def _decision_ready_gate(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    if (
        value.get("status") != "ready"
        or value.get("service_state") != "RUNNING"
        or value.get("configured_asset_count") != 2
        or value.get("configured_lane_count") != 3
        or value.get("active_lane_count") != 3
        or value.get("blocked_stream_count") != 0
        or value.get("lane_status_counts") != {"LIVE": 3}
    ):
        return False
    lanes = value.get("lanes")
    return isinstance(lanes, Mapping) and set(lanes) == {
        "BTCUSDT:momentum_1h",
        "BTCUSDT:momentum_4h",
        "ETHUSDT:momentum_4h",
    }


def _risk_gate(value: object) -> bool:
    if not isinstance(value, Mapping) or set(value) != set(TARGET_ROUTES):
        return False
    return all(
        isinstance(item, Mapping)
        and item.get("exists") is True
        and item.get("pending") == 0
        and item.get("lag") == 0
        for item in value.values()
    )


def _cleanup_gate(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("down_returncode") == 0
        and value.get("leftovers") == {"containers": "", "networks": "", "volumes": ""}
    )


def _trial_semantic_projection(trial: Mapping[str, object]) -> object:
    from tests.combined.d11c_real import (
        _feature_stream_projection,
        _semantic_projection,
    )

    return _semantic_projection(
        {
            "authority": trial.get("authority"),
            "strategy_admission": trial.get("strategy_admission"),
            "flow": trial.get("flow"),
            "cutback": trial.get("cutback"),
            "cutback_preflight": _feature_stream_projection(
                trial.get("cutback_preflight")
            ),
            "recutover": trial.get("recutover"),
            "cold_restart": trial.get("cold_restart"),
            "pre_cold_restart_feature_streams": _feature_stream_projection(
                trial.get("pre_cold_restart_feature_streams")
            ),
            "post_cold_restart_feature_streams": _feature_stream_projection(
                trial.get("cold_restart", {}).get("feature_streams")
                if isinstance(trial.get("cold_restart"), Mapping)
                else None
            ),
        }
    )


def _recomputed_trial_parity(trials: list[Mapping[str, object]]) -> dict[str, object]:
    projections = [_trial_semantic_projection(trial) for trial in trials]
    return {
        "trial_a": sha256_fingerprint(projections[0]),
        "trial_b": sha256_fingerprint(projections[1]),
        "matches": projections[0] == projections[1],
    }


def _authority_sequence_gate(trial: Mapping[str, object]) -> bool:
    authority = trial.get("authority")
    if not isinstance(authority, Mapping):
        return False
    cutback = trial.get("cutback")
    recutover = trial.get("recutover")
    if not isinstance(cutback, Mapping) or not isinstance(recutover, Mapping):
        return False
    return all(
        (
            _valid_authority_stage(
                authority.get("strategy_epoch_0"), owner="strategy", epoch=0
            ),
            _valid_authority_stage(
                authority.get("decision_epoch_1"), owner="decision", epoch=1
            ),
            _valid_authority_stage(cutback.get("authority"), owner="strategy", epoch=2),
            _valid_authority_stage(
                recutover.get("authority"), owner="decision", epoch=3
            ),
        )
    )


def _route_timeframe(route: str) -> str:
    try:
        return ROUTE_TIMEFRAMES[route]
    except KeyError as exc:
        raise ValueError(f"unknown D11C target route: {route}") from exc


def _snapshot_entries(snapshot: object, route: str) -> list[Mapping[str, object]]:
    if not isinstance(snapshot, Mapping):
        return []
    value = snapshot.get(route)
    if not isinstance(value, Mapping) or not isinstance(value.get("entries"), list):
        return []
    return [item for item in value["entries"] if isinstance(item, Mapping)]


def _latest_cutoff(entries: list[Mapping[str, object]]) -> int | None:
    cutoffs = [item.get("close_cutoff_ms") for item in entries]
    if not cutoffs or not all(isinstance(item, int) for item in cutoffs):
        return None
    return int(cutoffs[-1])


def _bootstrap_duplicate_gate(trial: object) -> bool:
    if not isinstance(trial, Mapping):
        return False
    before = trial.get("pre_cold_restart_feature_streams")
    cold = trial.get("cold_restart")
    after = cold.get("feature_streams") if isinstance(cold, Mapping) else None
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        return False
    for route in TARGET_ROUTES:
        before_entries = _snapshot_entries(before, route)
        after_entries = _snapshot_entries(after, route)
        if (
            not before_entries
            or not after_entries
            or _latest_cutoff(before_entries) != _latest_cutoff(after_entries)
            or len(after_entries) <= len(before_entries)
        ):
            return False
    return True


def _cutback_duplicate_gates(trial: object) -> dict[str, bool]:
    if not isinstance(trial, Mapping):
        return _false_duplicate_gates()
    cutback = trial.get("cutback")
    preflight = trial.get("cutback_preflight")
    if not isinstance(cutback, Mapping) or not isinstance(preflight, Mapping):
        return _false_duplicate_gates()
    progress = cutback.get("effect_progress")
    groups = cutback.get("groups")
    analyses = preflight.get("logical_analysis")
    if (
        not isinstance(progress, Mapping)
        or not isinstance(groups, Mapping)
        or not isinstance(analyses, Mapping)
    ):
        return _false_duplicate_gates()

    logical_continuity = True
    duplicates_owned = True
    runs_collapsed = True
    setid_after_last = True
    post_duplicates_absent = True
    identity_consistent = True
    anchors_preserved = True
    for route in TARGET_ROUTES:
        selected = groups.get(route)
        analysis = analyses.get(route)
        if not isinstance(selected, Mapping) or not isinstance(analysis, Mapping):
            return _false_duplicate_gates()
        R = progress.get(route)
        if not isinstance(R, int):
            return _false_duplicate_gates()
        timeframe = _route_timeframe(route)
        group_entries = selected.get("entries")
        if not isinstance(group_entries, list):
            return _false_duplicate_gates()
        try:
            recomputed = cutback_fast_forward_boundary(
                group_entries,
                progress_cutoff_ms=R,
                timeframe=timeframe,
            )
        except (TypeError, ValueError):
            return _false_duplicate_gates()
        for key, value in recomputed.items():
            if key in selected and selected[key] != value:
                runs_collapsed = False
        logical_continuity &= bool(
            recomputed["logical_cutoff_continuity"]
            and recomputed["no_legacy_cutoff_skipped"]
            and recomputed["progress_cutoff_present"]
        )
        analysis_runs = analysis.get("logical_runs")
        if not isinstance(analysis_runs, list):
            return _false_duplicate_gates()
        for run in analysis_runs:
            if not isinstance(run, Mapping):
                duplicates_owned = False
                identity_consistent = False
                continue
            count = run.get("entry_count")
            cutoff = run.get("cutoff_ms")
            if not isinstance(count, int) or not isinstance(cutoff, int):
                duplicates_owned = False
                continue
            if count > 1 and cutoff > R:
                duplicates_owned = False
            if count > 1 and not isinstance(run.get("bar_identity_fingerprint"), str):
                identity_consistent = False
        for entry in group_entries:
            if not isinstance(entry, Mapping):
                identity_consistent = False
                continue
            if all(key in entry for key in ("asset", "timeframe", "bar_data")):
                try:
                    identity_consistent &= entry.get("bar_identity_fingerprint") == (
                        market_bar_identity_fingerprint(entry)
                    )
                except (TypeError, ValueError):
                    identity_consistent = False
        identity_consistent &= (
            analysis.get("market_bar_duplicate_identity_consistent") is True
        )
        for run in analysis_runs:
            if not isinstance(run, Mapping):
                duplicates_owned = False
                continue
            count = run.get("entry_count", 0)
            cutoff = run.get("cutoff_ms")
            if count > 1 and (not isinstance(cutoff, int) or cutoff > R):
                duplicates_owned = False
        post_duplicates_absent &= (
            recomputed.get("post_progress_duplicate_run_count") == 0
            and recomputed.get("post_progress_duplicate_entry_count") == 0
        )
        runs = recomputed.get("logical_runs")
        at_progress = (
            next(
                (
                    run
                    for run in runs
                    if isinstance(run, Mapping) and run.get("cutoff_ms") == R
                ),
                None,
            )
            if isinstance(runs, list)
            else None
        )
        runs_collapsed &= (
            isinstance(at_progress, Mapping)
            and selected.get("setid") == at_progress.get("last_id")
            and selected.get("setid") == selected.get("last_id_through_progress")
            and selected.get("setid") == recomputed.get("last_id_through_progress")
        )
        setid_after_last &= runs_collapsed
        anchors_preserved &= selected.get("anchor_retained") is True and selected.get(
            "anchor_id"
        ) == group_entries[0].get("id")
    return {
        "logical_cutoff_continuity": logical_continuity,
        "bootstrap_duplicates_decision_owned": duplicates_owned,
        "decision_owned_duplicate_runs_collapsed": runs_collapsed,
        "cutback_setid_after_last_decision_owned_replay": setid_after_last,
        "post_progress_duplicates_absent": post_duplicates_absent,
        "market_bar_duplicate_identity_consistent": identity_consistent,
        "retention_anchor_preserved": anchors_preserved,
    }


def _signal_delta_gate(value: object) -> bool:
    if not isinstance(value, list) or not value:
        return False
    identities: list[tuple[object, object]] = []
    idempotency_keys: list[object] = []
    for signal in value:
        if not isinstance(signal, Mapping):
            return False
        stream = signal.get("stream")
        entry_id = signal.get("entry_id")
        key = signal.get("idempotency_key")
        if (
            not isinstance(stream, str)
            or not stream.startswith("signals:")
            or stream.removeprefix("signals:") not in TARGET_ROUTES
            or not isinstance(entry_id, str)
            or not isinstance(key, str)
        ):
            return False
        identities.append((stream, entry_id))
        idempotency_keys.append(key)
    return len(identities) == len(set(identities)) and len(idempotency_keys) == len(
        set(idempotency_keys)
    )


def _source_and_config_gates(raw: Mapping[str, object]) -> dict[str, bool]:
    return {
        "source_sha": raw.get("source_sha") == D11C_BASE_SHA,
        "source_lock": raw.get("current_source_hashes") == current_source_hashes(),
        "production_config_lock": raw.get("production_config_hashes")
        == production_config_hashes(),
        "protected_hashes": raw.get("protected_hashes") == EXPECTED_PROTECTED_HASHES
        and protected_hashes() == EXPECTED_PROTECTED_HASHES,
    }


def _trial_metadata_gate(trial: Mapping[str, object]) -> bool:
    return (
        trial.get("failed") is not True
        and trial.get("error") in {None, ""}
        and trial.get("real_disposable_stack") is True
        and trial.get("evidence_origin") == "measured_disposable"
    )


def evaluate_raw(raw: Mapping[str, object]) -> dict[str, bool]:
    trials = raw.get("trials")
    if not isinstance(trials, list) or len(trials) != 2:
        return {"two_trials": False}
    typed_trials = [item for item in trials if isinstance(item, Mapping)]
    gates: dict[str, bool] = {
        "measured_disposable": raw.get("evidence_origin") == "measured_disposable"
        and len(typed_trials) == 2
        and all(_trial_metadata_gate(trial) for trial in typed_trials),
        **_source_and_config_gates(raw),
        "two_trials": len(typed_trials) == 2,
    }
    if len(typed_trials) == 2:
        recomputed_parity = _recomputed_trial_parity(typed_trials)
        gates["trial_parity"] = (
            raw.get("trial_semantic_parity") == recomputed_parity
            and recomputed_parity.get("matches") is True
        )
    else:
        gates["trial_parity"] = False
    for index, trial in enumerate(typed_trials):
        prefix = f"trial_{index + 1}"
        unseeded = trial.get("unseeded")
        admission = trial.get("strategy_admission")
        corrupt = trial.get("missing_corrupt_isolation")
        flow = trial.get("flow")
        cold = trial.get("cold_restart")
        restart = trial.get("restart")
        cutback = trial.get("cutback")
        recutover = trial.get("recutover")
        execution = trial.get("execution")
        cleanup = trial.get("cleanup")
        gates[f"{prefix}_measured_trial"] = _trial_metadata_gate(trial)
        authority_records = (
            unseeded.get("authority_records") if isinstance(unseeded, Mapping) else None
        )
        gates[f"{prefix}_no_authority_fail_safe"] = (
            isinstance(unseeded, Mapping)
            and set(unseeded.get("active_routes", ())) == set(UNRELATED_ROUTES)
            and unseeded.get("target_routes_blocked") is True
            and unseeded.get("target_signal_count") == 0
            and isinstance(authority_records, Mapping)
            and set(authority_records) == set(TARGET_ROUTES)
            and all(authority_records[route] is None for route in TARGET_ROUTES)
            and isinstance(unseeded.get("decision_attempt"), Mapping)
            and unseeded["decision_attempt"].get("ready") is False
            and unseeded["decision_attempt"].get("authority_records_after")
            == authority_records
        )
        gates[f"{prefix}_catalog_eight"] = (
            trial.get("configured_strategy_routes") == list(EXPECTED_STRATEGY_ROUTES)
            and isinstance(trial.get("catalog"), Mapping)
            and trial["catalog"].get("discovered_pair_count") == 8
            and trial["catalog"].get("routes") == list(EXPECTED_STRATEGY_ROUTES)
        )
        gates[f"{prefix}_strategy_epoch_zero_eight"] = (
            isinstance(admission, Mapping)
            and admission.get("strategy_epoch_0_active")
            == list(EXPECTED_STRATEGY_ROUTES)
            and admission.get("all_eight_admitted") is True
        )
        gates[f"{prefix}_corrupt_isolation"] = (
            isinstance(corrupt, Mapping)
            and corrupt.get("corrupt_route") in TARGET_ROUTES
            and corrupt.get("corrupt_route_blocked") is True
            and corrupt.get("unrelated_routes_active") is True
            and isinstance(corrupt.get("decision_attempt"), Mapping)
            and corrupt["decision_attempt"].get("ready") is False
            and corrupt.get("authority_repaired") is False
        )
        gates[f"{prefix}_decision_flow"] = (
            isinstance(flow, Mapping)
            and _decision_ready_gate(flow.get("decision_ready"))
            and _risk_gate(flow.get("risk_groups"))
            and _signal_delta_gate(flow.get("decision_signal_delta"))
        )
        controller_cutover = trial.get("controller_cutover")
        gates[f"{prefix}_controller_cutover"] = (
            isinstance(controller_cutover, Mapping)
            and isinstance(controller_cutover.get("legacy_boundaries"), Mapping)
            and controller_cutover["legacy_boundaries"].get("stable") is True
            and _risk_gate(controller_cutover.get("risk_groups"))
            and isinstance(controller_cutover.get("effect_progress"), Mapping)
            and set(controller_cutover["effect_progress"]) == set(TARGET_ROUTES)
            and isinstance(controller_cutover.get("signal_heads"), Mapping)
            and set(controller_cutover["signal_heads"]) == set(TARGET_ROUTES)
        )
        gates[f"{prefix}_cold_restart"] = (
            isinstance(cold, Mapping)
            and _decision_ready_gate(cold.get("ready"))
            and _risk_gate(cold.get("risk_groups"))
            and _valid_authority_stage(cold.get("owners"), owner="decision", epoch=1)
            and cold.get("default_root_start") is True
        )
        gates[f"{prefix}_restart"] = (
            isinstance(restart, Mapping)
            and _decision_ready_gate(restart.get("ready"))
            and isinstance(restart.get("progress"), list)
            and restart.get("signals")
            == len(
                {
                    (item.get("stream"), item.get("entry_id"))
                    for item in flow.get("decision_signal_delta", [])
                    if isinstance(item, Mapping)
                }
            )
            if isinstance(flow, Mapping)
            else False
        )
        gates[f"{prefix}_cutback"] = (
            isinstance(cutback, Mapping)
            and cutback.get("strategy_epoch_2_active") == list(EXPECTED_STRATEGY_ROUTES)
            and isinstance(cutback.get("rollback_groups"), Mapping)
            and isinstance(cutback.get("controller_operation"), Mapping)
            and isinstance(
                cutback["controller_operation"].get("decision_progress"), Mapping
            )
            and cutback["controller_operation"]["decision_progress"].get("stable")
            is True
            and _risk_gate(cutback["controller_operation"].get("risk_groups"))
            and cutback.get("lifecycle_processed") is True
        )
        gates[f"{prefix}_strategy_lifecycle_re_admission"] = (
            isinstance(cutback, Mapping)
            and cutback.get("lifecycle_active_before_stop")
            == list(EXPECTED_STRATEGY_ROUTES)
            and cutback.get("lifecycle_stop_processed") is True
            and cutback.get("lifecycle_active_after_stop")
            == [
                route
                for route in EXPECTED_STRATEGY_ROUTES
                if route not in {"BTCUSDT:1h", "BTCUSDT:4h"}
            ]
            and cutback.get("lifecycle_resume_processed") is True
            and cutback.get("lifecycle_re_admitted_routes")
            == list(EXPECTED_STRATEGY_ROUTES)
        )
        gates[f"{prefix}_recutover"] = (
            isinstance(recutover, Mapping)
            and _decision_ready_gate(recutover.get("ready"))
            and _decision_ready_gate(recutover.get("post_restart_ready"))
            and recutover.get("strategy_active") == list(UNRELATED_ROUTES)
            and recutover.get("lifecycle_processed") is True
            and recutover.get("lifecycle_decision_owned_active")
            == list(UNRELATED_ROUTES)
            and isinstance(recutover.get("controller_operation"), Mapping)
            and isinstance(
                recutover["controller_operation"].get("legacy_boundaries"), Mapping
            )
            and recutover["controller_operation"]["legacy_boundaries"].get("stable")
            is True
            and _risk_gate(recutover["controller_operation"].get("risk_groups"))
            and _valid_authority_stage(
                recutover.get("authority"), owner="decision", epoch=3
            )
        )
        gates[f"{prefix}_authority_sequence"] = _authority_sequence_gate(trial)
        gates[f"{prefix}_execution_paper"] = (
            isinstance(execution, Mapping)
            and execution.get("mode") == "paper"
            and execution.get("mode_source") in {"config", "runtime"}
            and execution.get("container_running") is True
        )
        duplicate_gates = _cutback_duplicate_gates(trial)
        for name in DUPLICATE_GATE_NAMES:
            gates[f"{prefix}_{name}"] = duplicate_gates.get(name) is True
        gates[f"{prefix}_cleanup"] = _cleanup_gate(cleanup)
    gates["resource_envelope"] = _resource_gate(typed_trials)
    gates["cold_restart_bootstrap_duplicate_observed"] = len(typed_trials) == 2 and all(
        _bootstrap_duplicate_gate(trial) for trial in typed_trials
    )
    for name in DUPLICATE_GATE_NAMES:
        gates[name] = len(typed_trials) == 2 and all(
            _cutback_duplicate_gates(trial).get(name) is True for trial in typed_trials
        )
    return gates


def _identity_payload(artifact: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": artifact.get("schema_version"),
        "source_sha": artifact.get("source_sha"),
        "source_paths": SOURCE_PATHS,
        "current_source_hashes": artifact.get("current_source_hashes"),
        "configured_strategy_routes": artifact.get("configured_strategy_routes"),
        "target_routes": artifact.get("target_routes"),
        "protected_hashes": artifact.get("protected_hashes"),
        "production_config_hashes": artifact.get("production_config_hashes"),
    }


def _evidence_payload(
    raw: Mapping[str, object], gates: Mapping[str, bool]
) -> dict[str, object]:
    return {"raw_evidence": raw, "gates": gates}


def evaluate_artifact(artifact: Mapping[str, object]) -> dict[str, bool]:
    raw = artifact.get("raw_evidence")
    if not isinstance(raw, Mapping):
        return {"stored_artifact": False}
    recomputed = evaluate_raw(raw)
    expected_identity = sha256_fingerprint(_identity_payload(artifact))
    expected_evidence = sha256_fingerprint(_evidence_payload(raw, recomputed))
    recomputed_with_digests = dict(recomputed)
    recomputed_with_digests["identity_digest_integrity"] = (
        artifact.get("identity_digest") == expected_identity
    )
    recomputed_with_digests["evidence_digest_integrity"] = (
        artifact.get("evidence_digest") == expected_evidence
    )
    recomputed_with_digests["top_level_source_hashes_match"] = (
        artifact.get("current_source_hashes") == raw.get("current_source_hashes")
        and artifact.get("current_source_hashes") == current_source_hashes()
    )
    return {
        **recomputed_with_digests,
        "stored_gates_match": artifact.get("gates") == recomputed_with_digests,
        "terminal_status_match": artifact.get("terminal_status")
        == (
            SUCCESS_STATUS if all(recomputed_with_digests.values()) else BLOCKED_STATUS
        ),
    }


def build_artifact(raw: Mapping[str, object]) -> dict[str, object]:
    content_gates = evaluate_raw(raw)
    artifact: dict[str, object] = {
        "schema_version": 1,
        "source_sha": raw.get("source_sha"),
        "protected_hashes": raw.get("protected_hashes"),
        "production_config_hashes": raw.get("production_config_hashes"),
        "current_source_hashes": raw.get("current_source_hashes"),
        "configured_strategy_routes": list(EXPECTED_STRATEGY_ROUTES),
        "target_routes": list(TARGET_ROUTES),
        "raw_evidence": raw,
    }
    artifact["identity_digest"] = sha256_fingerprint(_identity_payload(artifact))
    artifact["evidence_digest"] = sha256_fingerprint(
        _evidence_payload(raw, content_gates)
    )
    artifact["gates"] = dict(content_gates)
    artifact["gates"]["identity_digest_integrity"] = True
    artifact["gates"]["evidence_digest_integrity"] = True
    artifact["gates"]["top_level_source_hashes_match"] = True
    artifact["terminal_status"] = (
        SUCCESS_STATUS if all(artifact["gates"].values()) else BLOCKED_STATUS
    )
    return artifact
