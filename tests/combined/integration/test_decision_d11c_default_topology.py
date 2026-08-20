"""D11C cutback evidence and guarded real-certification tests."""

from __future__ import annotations

import copy
import json
import os

import pytest

from scripts.decision_d11b_authority_cutover import (
    cutback_fast_forward_boundary,
    market_bar_identity_fingerprint,
)
from tests.combined.d11c_harness import (
    ARTIFACT_PATH,
    SUCCESS_STATUS,
    _bootstrap_duplicate_gate,
    _cutback_duplicate_gates,
    evaluate_raw,
)

TARGET_ROUTES = ("BTCUSDT:1h", "BTCUSDT:4h", "ETHUSDT:4h")


def _route_fixture(route: str) -> tuple[str, int]:
    return (
        ("1h", 1_700_000_000_000)
        if route.endswith("1h")
        else (
            "4h",
            1_700_000_000_000,
        )
    )


def _entry(route: str, entry_id: str, cutoff_ms: int, close: float = 100.0):
    timeframe, _ = _route_fixture(route)
    value = {
        "id": entry_id,
        "timestamp_ms": cutoff_ms - (3_600_000 if timeframe == "1h" else 14_400_000),
        "close_cutoff_ms": cutoff_ms,
        "asset": route.split(":", 1)[0],
        "timeframe": timeframe,
        "bar_data": {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 10.0,
        },
    }
    value["bar_identity_fingerprint"] = market_bar_identity_fingerprint(value)
    return value


def _measured_duplicate_trial() -> dict[str, object]:
    progress: dict[str, int] = {}
    groups: dict[str, object] = {}
    preflight: dict[str, object] = {}
    before: dict[str, object] = {}
    after: dict[str, object] = {}
    for route in TARGET_ROUTES:
        timeframe, base = _route_fixture(route)
        duration = 3_600_000 if timeframe == "1h" else 14_400_000
        entries = [
            _entry(route, "1-0", base),
            _entry(route, "2-0", base),
            _entry(route, "3-0", base + duration),
        ]
        selected = cutback_fast_forward_boundary(
            entries,
            progress_cutoff_ms=base,
            timeframe=timeframe,
        )
        selected.update(
            {
                "entries": entries,
                "setid": "2-0",
                "anchor_id": "1-0",
                "anchor_retained": True,
            }
        )
        progress[route] = base
        groups[route] = selected
        preflight[route] = {
            "entries": entries,
            "logical_analysis": cutback_fast_forward_boundary(
                entries,
                progress_cutoff_ms=base,
                timeframe=timeframe,
            ),
        }
        before[route] = {"entries": [entries[0]]}
        after[route] = {"entries": entries[:2]}
    preflight["logical_analysis"] = {
        route: value["logical_analysis"]
        for route, value in preflight.items()
        if route in TARGET_ROUTES
    }
    return {
        "evidence_origin": "measured_disposable",
        "pre_cold_restart_feature_streams": before,
        "cold_restart": {"feature_streams": after},
        "cutback_preflight": preflight,
        "cutback": {"effect_progress": progress, "groups": groups},
    }


def test_d11c_duplicate_evidence_is_recomputed_and_fail_closed() -> None:
    trial = _measured_duplicate_trial()
    assert _bootstrap_duplicate_gate(trial)
    assert all(_cutback_duplicate_gates(trial).values())

    raw = {
        "evidence_origin": "measured_disposable",
        "trials": [trial, copy.deepcopy(trial)],
        "trial_semantic_parity": {"matches": True},
    }
    gates = evaluate_raw(raw)
    assert gates["cold_restart_bootstrap_duplicate_observed"]
    assert gates["decision_owned_duplicate_runs_collapsed"]

    tampered = copy.deepcopy(raw)
    tampered["trials"][0]["cutback"]["groups"]["BTCUSDT:1h"]["setid"] = "1-0"
    assert (
        evaluate_raw(tampered)["trial_1_decision_owned_duplicate_runs_collapsed"]
        is False
    )

    tampered = copy.deepcopy(raw)
    entry = tampered["trials"][0]["cutback"]["groups"]["BTCUSDT:1h"]["entries"][1]
    entry["bar_data"]["close"] = 999.0
    assert (
        evaluate_raw(tampered)["trial_1_market_bar_duplicate_identity_consistent"]
        is False
    )

    tampered = copy.deepcopy(raw)
    group = tampered["trials"][0]["cutback"]["groups"]["BTCUSDT:1h"]
    group["entries"].append(copy.deepcopy(group["entries"][2]))
    assert evaluate_raw(tampered)["trial_1_post_progress_duplicates_absent"] is False

    tampered = copy.deepcopy(raw)
    tampered["trials"][0]["cutback"]["effect_progress"].pop("BTCUSDT:1h")
    assert evaluate_raw(tampered)["trial_1_logical_cutoff_continuity"] is False


def test_d11c_guarded_artifact_requires_all_duplicate_gates() -> None:
    if os.environ.get("INGESTION_DECISION_RUN_D11C") != "1":
        pytest.skip("set INGESTION_DECISION_RUN_D11C=1 for the disposable D11C proof")
    artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    assert artifact["terminal_status"] == SUCCESS_STATUS
    assert all(artifact["gates"].values())
    for name in (
        "cold_restart_bootstrap_duplicate_observed",
        "logical_cutoff_continuity",
        "bootstrap_duplicates_decision_owned",
        "decision_owned_duplicate_runs_collapsed",
        "cutback_setid_after_last_decision_owned_replay",
        "post_progress_duplicates_absent",
        "market_bar_duplicate_identity_consistent",
        "retention_anchor_preserved",
    ):
        assert artifact["gates"][name] is True
