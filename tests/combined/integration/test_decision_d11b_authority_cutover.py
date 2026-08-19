"""Guarded D11B real-infrastructure certification entrypoint."""

from __future__ import annotations

import json
import os
import urllib.request

import asyncpg
import pytest
import valkey.asyncio as valkey

from libs.common.signal_authority import TARGET_SIGNAL_ROUTES, SignalAuthorityStore
from libs.contracts.serialization import valkey_decode
from libs.contracts.signal import TradeSignal
from tests.combined.d11b_harness import (
    ARTIFACT_PATH,
    SUCCESS_STATUS,
    evaluate_artifact,
)


def test_guarded_d11b_authority_cutover_artifact() -> None:
    if os.environ.get("INGESTION_DECISION_RUN_D11B") != "1":
        pytest.skip("set INGESTION_DECISION_RUN_D11B=1 for the disposable D11B proof")
    artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    gates, status = evaluate_artifact(artifact)
    assert status == SUCCESS_STATUS
    assert all(gates.values())


@pytest.mark.asyncio
async def test_real_d11b_decision_and_risk_cutover_evidence() -> None:
    if os.environ.get("INGESTION_DECISION_RUN_D11B") != "1":
        pytest.skip("set INGESTION_DECISION_RUN_D11B=1 for the disposable D11B proof")
    postgres_uri = os.environ.get("D11B_POSTGRES_URI")
    valkey_uri = os.environ.get("D11B_VALKEY_URI")
    decision_url = os.environ.get("D11B_DECISION_URL")
    if not postgres_uri or not valkey_uri or not decision_url:
        pytest.fail(
            "D11B guarded proof requires D11B_POSTGRES_URI, D11B_VALKEY_URI, "
            "and D11B_DECISION_URL"
        )
    pool = await asyncpg.create_pool(postgres_uri, min_size=1, max_size=2)
    broker = valkey.Valkey.from_url(valkey_uri, decode_responses=True)
    try:
        authority = SignalAuthorityStore(broker)
        records = [await authority.read(route) for route in TARGET_SIGNAL_ROUTES]
        assert all(
            record is not None and record.owner == "decision" for record in records
        )
        assert all(record.epoch == 1 for record in records if record is not None)

        progress_count = await pool.fetchval(
            "SELECT COUNT(*) FROM decision.shadow_progress "
            "WHERE last_disposition IN ('published', 'no_signal')"
        )
        assert int(progress_count) == 3

        def runtime_payload() -> dict[str, object]:
            with urllib.request.urlopen(
                decision_url + "/runtime", timeout=10
            ) as response:
                return json.loads(response.read())

        runtime = await __import__("asyncio").to_thread(runtime_payload)
        assert runtime["service_state"] == "RUNNING"
        assert runtime["blocked_stream_count"] == 0
        assert set(runtime["lanes"]) == {
            "BTCUSDT:momentum_1h",
            "BTCUSDT:momentum_4h",
            "ETHUSDT:momentum_4h",
        }

        expected_models = {
            "signals:BTCUSDT:1h": "m4-btc-1h",
            "signals:BTCUSDT:4h": "m4-btc-4h",
            "signals:ETHUSDT:4h": "m4-eth-4h",
        }
        for stream, model_name in expected_models.items():
            entries = await broker.xrange(stream, "-", "+")
            assert entries
            signals = [
                valkey_decode(dict(fields), TradeSignal) for _, fields in entries
            ]
            assert {signal.model_name for signal in signals} == {model_name}
            groups = await broker.xinfo_groups(stream)
            group = next(item for item in groups if item["name"] == "risk_app_group")
            assert group["pending"] == 0
            assert group["lag"] == 0
        shadow_keys = [key async for key in broker.scan_iter(match="decision:shadow:*")]
        assert shadow_keys == []
    finally:
        await broker.aclose()
        await pool.close()
