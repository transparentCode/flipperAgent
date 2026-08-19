from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.combined.d11a_harness import (
    D11A_ARTIFACT,
    D11A_BLOCKED_STATUS,
    D11A_SUCCESS_STATUS,
    EXPECTED_LANES,
    current_fixture_hashes,
    current_source_hashes,
    evaluate_artifact,
    load_d11a_config,
    m4_route_identity,
    protected_hashes,
)

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = {
    "physical_table": "decision.shadow_progress",
    "dispositions": [None, "shadow", "published", "no_signal"],
    "identity_fields": [
        "lane_id",
        "effective_lane_revision",
        "feature_plan_fingerprint",
        "data_plan_fingerprint",
    ],
}

SCHEMA_UPGRADE = {
    "c4b_table_created": True,
    "historical_rows_before": [
        {"lane_id": "d11a-schema-null", "last_disposition": None},
        {"lane_id": "d11a-schema-shadow", "last_disposition": "shadow"},
    ],
    "historical_rows_after": [
        {"lane_id": "d11a-schema-null", "last_disposition": None},
        {"lane_id": "d11a-schema-shadow", "last_disposition": "shadow"},
        {"lane_id": "d11a-schema-published", "last_disposition": "published"},
        {"lane_id": "d11a-schema-no-signal", "last_disposition": "no_signal"},
    ],
    "historical_rows_preserved": True,
    "old_constraint_definition": [
        {
            "name": "shadow_progress_last_disposition_check",
            "definition": (
                "CHECK (((last_disposition IS NULL) OR "
                "(last_disposition = 'shadow'::text)))"
            ),
        }
    ],
    "migrated_constraint_definition": [
        {
            "name": "shadow_progress_last_disposition_check",
            "definition": (
                "CHECK ((last_disposition IS NULL) OR "
                "(last_disposition = ANY (ARRAY['shadow'::text, "
                "'published'::text, 'no_signal'::text])))"
            ),
        }
    ],
    "published_repository_roundtrip": True,
    "no_signal_repository_roundtrip": True,
    "invalid_disposition_rejected": True,
    "second_bootstrap_succeeded": True,
    "check_constraint_count": 1,
    "second_constraint_definition": [
        {
            "name": "shadow_progress_last_disposition_check",
            "definition": (
                "CHECK ((last_disposition IS NULL) OR "
                "(last_disposition = ANY (ARRAY['shadow'::text, "
                "'published'::text, 'no_signal'::text])))"
            ),
        }
    ],
    "idempotent": True,
}


def _passing_trial() -> dict[str, object]:
    signal_crash_entry = {
        "stream": "signals:BTCUSDT:1h",
        "entry_id": "5000-0",
        "model_name": "m4-btc-1h",
        "market_as_of": "1972-10-01T05:00:00+00:00",
    }
    progress = [
        {"lane_id": lane, "last_disposition": "no_signal"} for lane in EXPECTED_LANES
    ]
    signals = [
        {
            "stream": "signals:BTCUSDT:1h",
            "entry_id": entry_id,
            "model_name": "m4-btc-1h",
        }
        for entry_id in ("2000-0", "3000-0", "4000-0")
    ] + [
        {
            "stream": stream,
            "entry_id": "4000-0",
            "model_name": model_name,
        }
        for stream, model_name in (
            ("signals:BTCUSDT:4h", "m4-btc-4h"),
            ("signals:ETHUSDT:4h", "m4-eth-4h"),
        )
    ]
    return {
        "schema_upgrade": SCHEMA_UPGRADE,
        "startup": {
            "no_historical_signals": True,
            "signals": [],
            "progress": [
                {"lane_id": lane, "last_disposition": None} for lane in EXPECTED_LANES
            ],
            "ready": True,
            "active_lane_count": 3,
        },
        "live": {
            "signals": signals,
            "progress": progress,
            "shadow_keys": [],
            "no_signal_window": {
                "progress": [
                    {
                        "lane_id": "BTCUSDT:momentum_1h",
                        "last_disposition": "no_signal",
                    }
                ],
                "signals": [],
                "btc_1h": {"at_or_after": True},
            },
            "oracle_policy_statuses": {
                "BTCUSDT:momentum_1h": [
                    "NO_SIGNAL",
                    "SIGNAL",
                    "SIGNAL",
                    "SIGNAL",
                ],
                "BTCUSDT:momentum_4h": ["SIGNAL"],
                "ETHUSDT:momentum_4h": ["SIGNAL"],
            },
        },
        "restart": {
            "signals": signals,
            "progress": progress,
            "catchup_before_new_input": True,
        },
        "crash_windows": {
            "signal": {
                "expected_cutoff": "1972-10-01T05:00:00+00:00",
                "failed_progress": [
                    {
                        "lane_id": "BTCUSDT:momentum_1h",
                        "market_as_of": "1972-10-01T04:00:00+00:00",
                        "last_disposition": "published",
                    }
                ],
                "failed_signals": [signal_crash_entry],
                "recovered_progress": [
                    {
                        "lane_id": "BTCUSDT:momentum_1h",
                        "market_as_of": "1972-10-01T05:00:00+00:00",
                        "last_disposition": "published",
                    }
                ],
                "recovered_signals": [signal_crash_entry],
            },
            "no_signal": {
                "expected_cutoff": "1972-10-01T01:00:00+00:00",
                "failed_progress": [
                    {
                        "lane_id": "BTCUSDT:momentum_1h",
                        "market_as_of": "1972-10-01T00:00:00+00:00",
                        "last_disposition": None,
                    }
                ],
                "failed_signals": [],
                "recovered_progress": [
                    {
                        "lane_id": "BTCUSDT:momentum_1h",
                        "market_as_of": "1972-10-01T01:00:00+00:00",
                        "last_disposition": "no_signal",
                    }
                ],
                "recovered_signals": [],
            },
            "cleanup": {"clean": True},
        },
        "unsupported_backlog": {
            "stateful": "unit_tested_fail_closed",
            "external_data": "unit_tested_fail_closed",
        },
        "cleanup": {"clean": True},
    }


def _passing_artifact() -> dict[str, object]:
    config = load_d11a_config()
    routes = [
        {
            "lane_id": lane.lane_id,
            "authority": lane.authority,
            "risk_profile_key": lane.risk_profile_key,
        }
        for lane in config.lane_specs()
    ]
    return {
        "protected_hashes": protected_hashes(),
        "source_hashes": current_source_hashes(),
        "fixture_hashes": current_fixture_hashes(),
        "routes": routes,
        "m4_config_identity": m4_route_identity(config),
        "strategy": {
            "relinquished_routes": ["BTCUSDT:1h", "BTCUSDT:4h", "ETHUSDT:4h"],
            "catalog_before": [
                "BNBUSDT:30m",
                "BTCUSDT:1h",
                "BTCUSDT:4h",
                "DOGEUSDT:4h",
                "ETHUSDT:4h",
                "SOLUSDT:1h",
                "XRPUSDT:1h",
            ],
            "catalog_after": [
                "BNBUSDT:30m",
                "DOGEUSDT:4h",
                "SOLUSDT:1h",
                "XRPUSDT:1h",
            ],
            "excluded_worker_count": 4,
            "unknown_route_rejected": True,
            "no_excluded_feature_read": True,
            "backlog_preserved_during_exclusion": True,
            "rollback_consumed_and_acked": True,
        },
        "effect_progress_contract": CONTRACT,
        "production_scope": {"decision_assets": [], "observer_active": False},
        "trials": [_passing_trial(), _passing_trial()],
    }


def test_d11a_evaluator_recomputes_and_rejects_tampered_evidence() -> None:
    artifact = _passing_artifact()
    gates, status = evaluate_artifact(artifact)
    assert status == D11A_SUCCESS_STATUS
    assert all(gates.values())

    tampered = json.loads(json.dumps(artifact))
    tampered["protected_hashes"]["c4b"] = "tampered"
    tampered_gates, tampered_status = evaluate_artifact(tampered)
    assert tampered_status == D11A_BLOCKED_STATUS
    assert tampered_gates["protected_evidence"] is False

    tampered_trial = json.loads(json.dumps(artifact))
    tampered_trial["trials"][1]["restart"]["catchup_before_new_input"] = False
    trial_gates, trial_status = evaluate_artifact(tampered_trial)
    assert trial_status == D11A_BLOCKED_STATUS
    assert trial_gates["restart_backlog_exact"] is False

    schema_mutations = (
        lambda value: value["historical_rows_after"].__delitem__(0),
        lambda value: value["migrated_constraint_definition"].__setitem__(
            0, value["old_constraint_definition"][0]
        ),
        lambda value: value.__setitem__("published_repository_roundtrip", False),
        lambda value: value.__setitem__("no_signal_repository_roundtrip", False),
        lambda value: value.__setitem__("invalid_disposition_rejected", False),
        lambda value: value["second_constraint_definition"].append(
            value["second_constraint_definition"][0]
        ),
        lambda value: value.__setitem__("second_bootstrap_succeeded", False),
    )
    for mutate in schema_mutations:
        tampered_schema = json.loads(json.dumps(artifact))
        mutate(tampered_schema["trials"][0]["schema_upgrade"])
        schema_gates, schema_status = evaluate_artifact(tampered_schema)
        assert schema_status == D11A_BLOCKED_STATUS
        assert schema_gates["c4b_schema_upgrade"] is False


def test_d11a_fixture_is_authoritative_m4_route_shape_and_production_is_empty() -> None:
    config = load_d11a_config()
    assert tuple(lane.lane_id for lane in config.lane_specs()) == EXPECTED_LANES
    assert all(lane.authority == "authoritative" for lane in config.lane_specs())
    assert {lane.risk_profile_key for lane in config.lane_specs()} == {
        "m4-btc-1h",
        "m4-btc-4h",
        "m4-eth-4h",
    }
    assets_root = ROOT / "configs/decision/assets"
    assert not any(assets_root.rglob("*")) if assets_root.exists() else True


@pytest.mark.skipif(
    os.environ.get("INGESTION_DECISION_RUN_D11A") != "1",
    reason="guarded real D11A infrastructure scenario",
)
def test_guarded_real_d11a_artifact_is_ready() -> None:
    artifact = json.loads(D11A_ARTIFACT.read_text(encoding="utf-8"))
    gates, status = evaluate_artifact(artifact)
    assert status == D11A_SUCCESS_STATUS
    assert all(gates.values())
