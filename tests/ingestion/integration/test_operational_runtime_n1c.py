"""Opt-in Compose operational certification for ingestion."""

from __future__ import annotations

import os

import pytest

from scripts.certify_ingestion_operations_n1c import run_certification

pytestmark = pytest.mark.skipif(
    os.getenv("INGESTION_RUN_N1C_OPERATIONS") != "1",
    reason="set INGESTION_RUN_N1C_OPERATIONS=1 for the real Compose certification",
)


def test_ingestion_operational_runtime_certification() -> None:
    result = run_certification(execute=True)

    assert result["status"] == "READY_FOR_REVIEW"
    assert result["BTC_LEGACY_MANIFEST_DEPENDENCY_TEMPORARY"] is True
    assert result["AUTOMATIC_PUBLISHED_OUTBOX_REPLAY"] == "ABSENT"
    assert result["N1_PUBLISHED_OUTBOX_CLEANUP"] == "DISABLED"
    assert result["BTC_N1_AUTOMATIC_ROLLBACK_TO_LEGACY"] is False

    for timeframe in ("1h", "4h"):
        start_group = result["signal_start"]["groups"][timeframe]
        assert start_group["consumer_fresh"] is True
        assert start_group["consumer_idle_ms"] <= start_group["consumer_idle_limit_ms"]

    graceful_shutdown = result["signal_graceful_shutdown"]
    assert graceful_shutdown["exit_codes"] == [0]
    assert graceful_shutdown["oom_killed"] is False
    assert (
        graceful_shutdown["elapsed_seconds"]
        < graceful_shutdown["hard_boundary_seconds"]
    )

    for timeframe in ("1h", "4h"):
        restarted_group = result["signal_after_graceful_restart"]["groups"][timeframe]
        assert restarted_group["consumer_fresh"] is True

    restored_signal = result["service_restoration"]["signal-worker"]
    assert restored_signal["running"] is False
    assert [int(item["exit_code"]) for item in restored_signal["containers"]] == [0]
    assert all(item["oom_killed"] is False for item in restored_signal["containers"])
