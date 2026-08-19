from __future__ import annotations

import copy
import json
import os

import pytest

from tests.combined.c4a_harness import (
    ARTIFACT_FILE,
    C4_SUCCESS_STATUS,
    _redeliver_canonical_event,
    evaluate_c4a_gates,
    evidence_payload,
    protected_hashes_valid,
    run_c4a_certification,
    sha256_fingerprint,
)


def test_c4a_protected_evidence_is_current() -> None:
    assert protected_hashes_valid()


def test_c4a_gates_fail_closed_when_raw_evidence_is_tampered() -> None:
    evidence = json.loads(ARTIFACT_FILE.read_text(encoding="utf-8"))
    assert all(evaluate_c4a_gates(evidence).values())

    mutations = (
        ("shadow_count", lambda value: value["live"].update(shadow_counts={})),
        (
            "shadow_semantics",
            lambda value: value["live"]["semantics"]["ETHUSDT:momentum_4h"].update(
                parity=False
            ),
        ),
        (
            "duplicate_watermark",
            lambda value: value["duplicate"].update(watermarks_unchanged=False),
        ),
        ("trial_determinism", lambda value: value.update(trials_equal=False)),
        (
            "startup_baseline",
            lambda value: value["schema_and_seed"]["baseline"].update(
                signals=["signals:X"]
            ),
        ),
        (
            "empty_watermarks",
            lambda value: value["live"].update(watermarks={}),
        ),
        (
            "single_lane_disposition",
            lambda value: value["live"]["watermarks"]["BTCUSDT:momentum_1h"].update(
                last_disposition="published"
            ),
        ),
        (
            "forged_duplicate_map",
            lambda value: value["duplicate"]["watermarks_after"].update(
                {"BTCUSDT:momentum_1h": {"last_disposition": "shadow"}}
            ),
        ),
        (
            "trial_b_semantic_drift",
            lambda value: value["trial_b"]["live"].update(observations=[]),
        ),
        (
            "restart_count_hidden",
            lambda value: value["restart"].update(shadow_count_before=5),
        ),
        (
            "restart_observations_erased",
            lambda value: value["restart"].update(observations_after_restart=[]),
        ),
        (
            "control_shadow_drift",
            lambda value: value["controls"].update(shadow_count_after_resume=7),
        ),
        (
            "authoritative_signal",
            lambda value: value["controls"].update(
                signals_after_reconnect=["signals:X"]
            ),
        ),
        (
            "trial_b_cleanup",
            lambda value: value["trial_b"]["cleanup"].update(clean=False),
        ),
        (
            "production_asset",
            lambda value: value["production_scope"].update(
                decision_assets=["configs/decision/assets/btc.yaml"]
            ),
        ),
        (
            "root_compose_contract",
            lambda value: value["production_scope"].update(root_compose_rendered=False),
        ),
        (
            "source_hash",
            lambda value: value["source_contract"].update(decision_global_sha="0" * 64),
        ),
        (
            "resource_sample",
            lambda value: value["resource_samples"]["trial_a"]["live"].update(
                memory_usage_bytes=512 * 1024 * 1024
            ),
        ),
        (
            "image_id",
            lambda value: value["resource"].update(image_id=""),
        ),
        (
            "protected_hash",
            lambda value: value["protected_hashes"].update(m3="0" * 64),
        ),
    )
    for name, mutate in mutations:
        tampered = copy.deepcopy(evidence)
        mutate(tampered)
        assert not all(evaluate_c4a_gates(tampered).values()), name


def test_c4a_evaluator_is_pure_and_recomputes_trial_equality(monkeypatch) -> None:
    evidence = json.loads(ARTIFACT_FILE.read_text(encoding="utf-8"))

    def _filesystem_call_forbidden() -> bool:
        raise AssertionError("pure evaluator accessed the filesystem")

    monkeypatch.setattr(
        "tests.combined.c4a_harness.protected_hashes_valid",
        _filesystem_call_forbidden,
    )
    assert all(evaluate_c4a_gates(evidence).values())

    tampered = copy.deepcopy(evidence)
    tampered["trial_b"]["live"]["observations"] = []
    assert not evaluate_c4a_gates(tampered)["two_trial_determinism"]


@pytest.mark.asyncio
async def test_c4a_redelivery_allocates_a_strictly_forward_stream_id() -> None:
    class Broker:
        def __init__(self) -> None:
            self.added: tuple[str, dict[str, str], str] | None = None

        def scan_iter(self, *, match: str):
            assert match == "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h"

            async def _scan():
                yield "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h"

            return _scan()

        async def xrange(
            self, stream: str, start: str, end: str, *, count: int
        ) -> list[tuple[str, dict[str, str]]]:
            assert (start, end, count) == ("-", "+", 1)
            return [("100-0", {"payload": "canonical"})]

        async def xrevrange(
            self, stream: str, maximum: str, minimum: str, *, count: int
        ) -> list[tuple[str, dict[str, str]]]:
            assert (maximum, minimum, count) == ("+", "-", 1)
            return [("200-3", {"payload": "tail"})]

        async def xadd(self, stream: str, fields: dict[str, str], *, id: str) -> str:
            self.added = (stream, fields, id)
            return id

    broker = Broker()
    result = await _redeliver_canonical_event(broker)

    assert result["original_id"] == "100-0"
    assert result["redelivery_id"] == "201-3"
    assert broker.added is not None
    assert broker.added[2] == "201-3"


def test_c4a_raw_cursor_ids_are_volatile_but_still_gate_checked() -> None:
    evidence = json.loads(ARTIFACT_FILE.read_text(encoding="utf-8"))
    original_digest = sha256_fingerprint(evidence_payload(evidence))
    tampered = copy.deepcopy(evidence)
    tampered["raw_input_cursor_evidence"]["trial_a"]["after_stream_id"] = "0-0"

    assert sha256_fingerprint(evidence_payload(tampered)) == original_digest
    assert not evaluate_c4a_gates(tampered)["duplicate_idempotency"]


@pytest.mark.asyncio
async def test_real_c4a_two_trial_certification() -> None:
    if os.getenv("INGESTION_DECISION_RUN_C4A") != "1":
        pytest.skip("set INGESTION_DECISION_RUN_C4A=1 to run disposable C4A")
    evidence = await run_c4a_certification()
    assert evidence["terminal_status"] == C4_SUCCESS_STATUS
    assert all(evidence["gates"].values())
