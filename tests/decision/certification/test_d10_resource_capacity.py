"""Focused offline D10 resource/capacity certification regressions."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

import scripts.certify_decision_runtime_d10 as d10
from scripts.certify_decision_runtime_d10 import (
    HARD_RSS_TARGET_BYTES,
    LIVE_BATCH_SIZE,
    NORMAL_RSS_TARGET_BYTES,
    RETENTION_MAXLEN,
    _risk_timeframes,
    _rss_bytes,
    build_relay_config,
    deterministic_identity_sha256,
    evaluate_resource_gates,
    load_canonical_inventory,
    measurement_payload_sha256,
    run_current_risk_scenario,
    run_full_boundary_scenario,
    run_retention_edge_scenario,
    run_service_scenario,
    run_sr_reference,
    structural_boundedness_scan,
    write_artifact,
)


def test_current_inventory_and_resource_targets_are_derived_from_live_config() -> None:
    inventory = load_canonical_inventory()

    assert inventory.assets == ("BNB", "BTC", "DOGE", "ETH", "SOL", "XRP")
    assert inventory.timeframes == (
        "1m",
        "15m",
        "30m",
        "1h",
        "4h",
        "6h",
        "12h",
        "1d",
        "1w",
    )
    assert inventory.series_count == 54
    assert NORMAL_RSS_TARGET_BYTES == 5 * 1024**3
    assert HARD_RSS_TARGET_BYTES == 8 * 1024**3


def test_relay_only_config_compiles_exactly_one_bounded_series_store_slot() -> None:
    inventory = load_canonical_inventory()
    config = build_relay_config(inventory)

    from apps.decision_app.transport.price_relay import compile_price_relay_plans

    plans = compile_price_relay_plans(config)
    assert len(plans) == 54
    assert config.global_settings.live_input.batch_size == LIVE_BATCH_SIZE
    assert config.global_settings.price_relay.stream_maxlen == RETENTION_MAXLEN
    assert all(not asset.lanes for asset in config.assets.values())


def test_current_risk_routes_follow_risk_app_discovery() -> None:
    from libs.common.config import ConfigManager
    from libs.common.constants import CONFIG_FILE_MODELS
    from libs.common.discovery import discover_asset_timeframes

    inventory = load_canonical_inventory()
    ConfigManager.reset_singleton()
    config_manager = ConfigManager(config_dir="configs")
    try:
        config_manager.register_file(CONFIG_FILE_MODELS)
        discovered = discover_asset_timeframes(config_manager)
    finally:
        config_manager.shutdown()
        ConfigManager.reset_singleton()

    expected = {
        inventory.decision_symbols[manifest]: tuple(
            sorted(timeframes, key=inventory.grid.duration)
        )
        for manifest in inventory.assets
        if (timeframes := discovered.get(inventory.decision_symbols[manifest]))
    }
    actual = {
        inventory.decision_symbols[manifest]: timeframes
        for manifest, timeframes in _risk_timeframes(inventory).items()
        if timeframes
    }
    assert actual == expected


def test_ru_maxrss_normalization_is_platform_explicit() -> None:
    assert _rss_bytes(123, system="Darwin") == 123
    assert _rss_bytes(123, system="Linux") == 123 * 1024


@pytest.mark.asyncio
async def test_current_risk_and_full_canonical_boundaries_are_bounded() -> None:
    inventory = load_canonical_inventory()

    current = await run_current_risk_scenario(inventory)
    full = await run_full_boundary_scenario(inventory)

    assert current["correct"] is True
    assert current["relay_count"] == 7
    assert current["published_count"] == 7
    assert current["max_history_in_flight"] == 1
    assert current["max_xadd_in_flight"] == 1
    assert full["correct"] is True
    assert full["series_count"] == 54
    assert full["published_count"] == 54
    assert full["bar_store_capacity_min"] == 1
    assert full["bar_store_capacity_max"] == 1


@pytest.mark.asyncio
async def test_retention_edge_drains_exactly_10800_bars_in_bounded_passes() -> None:
    evidence = await run_retention_edge_scenario(load_canonical_inventory())

    assert evidence["correct"] is True
    assert evidence["expected_bars"] == 10_800
    assert evidence["reconcile_passes"] == 20
    assert evidence["publications_per_pass_max"] == 540
    assert evidence["publications_per_relay_per_pass_max"] == 10
    assert evidence["total_publications"] == 10_800
    assert evidence["idle_publications"] == 0
    assert evidence["max_stream_entries"] <= 200


@pytest.mark.asyncio
async def test_decision_service_keeps_two_tasks_and_stops_cleanly() -> None:
    evidence = await run_service_scenario(load_canonical_inventory())

    assert evidence["correct"] is True
    assert evidence["generations_built"] == [1, 2, 3]
    assert evidence["task_count_after_start"] == 2
    assert evidence["task_peak"] == 2
    assert evidence["task_count_after_stop"] == 0
    assert evidence["price_publications_while_paused"] == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("observed_task_count", [0, 1, 3])
async def test_service_task_measurement_never_floors_or_inflates(
    monkeypatch: pytest.MonkeyPatch,
    observed_task_count: int,
) -> None:
    monkeypatch.setattr(d10, "_task_count", lambda: observed_task_count)

    evidence = await run_service_scenario(load_canonical_inventory())

    assert evidence["task_count_after_start"] == observed_task_count
    assert evidence["task_peak"] == observed_task_count
    assert evidence["task_count_after_stop"] == observed_task_count
    assert evidence["correct"] is False


def _synthetic_scenarios(*, sr_rss: int) -> list[dict[str, object]]:
    return [
        {
            "id": f"scenario-{index}",
            "measurement": {
                "process_peak_rss_bytes": sr_rss if index == 4 else 100,
                "cpu_core_equivalent": 0.5,
            },
            "evidence": {"correct": True},
        }
        for index in range(5)
    ]


def test_hard_rss_gate_checks_the_sr_reference_scenario() -> None:
    gates = evaluate_resource_gates(
        _synthetic_scenarios(sr_rss=9 * 1024**3),
        structural_correct=True,
    )

    assert gates["hard_rss_below_8_gib_all_scenarios"] is False
    assert gates["status"] == "BLOCKED_RESOURCE_ENVELOPE"


def test_measurement_digest_changes_when_measurement_evidence_is_tampered() -> None:
    artifact = {
        "schema_version": "d10.resource_capacity.v1",
        "status": "APPROVED",
        "resource_target": {
            "normal_working_set_bytes": NORMAL_RSS_TARGET_BYTES,
            "hard_memory_bytes": HARD_RSS_TARGET_BYTES,
            "cpu_cores": 4.0,
        },
        "current_inventory": {"canonical_series_count": 54},
        "scenarios": _synthetic_scenarios(sr_rss=100),
        "structural_boundedness": {"correct": True},
        "static_guards": {"decision_create_task_sites": 2},
        "validation": {"offline_core_gates": {"scenario_correct": True}},
        "limitations": [],
        "carry_forward": ["FINAL_MODEL_MIX_RESOURCE_RECERTIFICATION_REQUIRED"],
    }
    original_measurement_digest = measurement_payload_sha256(artifact)
    original_identity_digest = deterministic_identity_sha256(
        {
            **artifact,
            "scenarios": [{"id": item["id"]} for item in artifact["scenarios"]],
        }
    )
    tampered = deepcopy(artifact)
    tampered["scenarios"][0]["measurement"]["process_peak_rss_bytes"] = 9 * 1024**3

    assert measurement_payload_sha256(tampered) != original_measurement_digest
    assert (
        deterministic_identity_sha256(
            {
                **tampered,
                "scenarios": [{"id": item["id"]} for item in tampered["scenarios"]],
            }
        )
        == original_identity_digest
    )


@pytest.mark.asyncio
async def test_sr_reference_measures_bounded_decision_artifact_projection() -> None:
    evidence = await run_sr_reference(steps=20)

    assert evidence["correct"] is True
    assert (
        evidence["internal_zone_count_max"]
        >= evidence["projected_artifact_zone_count_max"]
    )
    assert (
        evidence["projected_artifact_zone_count_max"]
        <= evidence["configured_max_active_zones"]
    )
    assert evidence["encoded_state_bytes_start"] > 0
    assert evidence["encoded_state_bytes_max"] >= evidence["encoded_state_bytes_end"]


def test_structural_guardrails_find_only_the_two_service_task_sites() -> None:
    evidence = structural_boundedness_scan()

    assert evidence["create_task_sites"] == 2
    assert evidence["forbidden_matches"] == {}
    assert evidence["correct"] is True


def test_artifact_writer_is_atomic_json_and_rejects_non_finite_values(
    tmp_path: Path,
) -> None:
    artifact = {
        "schema_version": "d10.resource_capacity.v1",
        "status": "APPROVED",
        "measurements": {"rss": 123, "cpu": 0.5},
    }
    path = tmp_path / "d10.json"
    digest = write_artifact(artifact, path)

    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed == artifact
    assert len(digest) == 64
    assert not list(tmp_path.glob(".*.d10.json.*"))
    with pytest.raises(ValueError, match="NaN"):
        write_artifact({"value": float("nan")}, tmp_path / "invalid.json")
