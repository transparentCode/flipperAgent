#!/usr/bin/env python3
"""Focused run #3 harness semantics tests; no Docker or network access."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

HARNESS_PATH = Path(__file__).with_name("soak_harness.py")
SPEC = importlib.util.spec_from_file_location("run3_harness", HARNESS_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load run #3 harness")
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


class Run3HarnessSemanticsTests(unittest.TestCase):
    def test_transient_converged_within_window(self) -> None:
        observations = [
            {
                "probe_status": "VALID",
                "detected_elapsed_seconds": 0,
                "input_lag": 1,
                "watermark_lag": 1,
            },
            {
                "probe_status": "VALID",
                "detected_elapsed_seconds": 20,
                "input_lag": 0,
                "watermark_lag": 0,
            },
        ]
        self.assertEqual(
            HARNESS.classify_boundary_observations(observations),
            HARNESS.TRANSIENT_CONVERGED,
        )

    def test_growing_lag_is_unresolved(self) -> None:
        observations = [
            {
                "probe_status": "VALID",
                "detected_elapsed_seconds": 0,
                "input_lag": 1,
                "watermark_lag": 1,
            },
            {
                "probe_status": "VALID",
                "detected_elapsed_seconds": 15,
                "input_lag": 2,
                "watermark_lag": 1,
            },
        ]
        self.assertEqual(
            HARNESS.classify_boundary_observations(observations), HARNESS.UNRESOLVED
        )

    def test_probe_gap_is_indeterminate(self) -> None:
        observations = [{"probe_status": HARNESS.PROBE_INDETERMINATE}]
        self.assertEqual(
            HARNESS.classify_boundary_observations(observations),
            HARNESS.PROBE_INDETERMINATE,
        )

    def test_blocked_input_is_unresolved(self) -> None:
        observations = [
            {
                "probe_status": "VALID",
                "detected_elapsed_seconds": 0,
                "input_lag": 1,
                "watermark_lag": 1,
                "blocked": True,
            },
        ]
        self.assertEqual(
            HARNESS.classify_boundary_observations(observations), HARNESS.UNRESOLVED
        )

    def test_probe_payload_rejects_bad_status_and_shape(self) -> None:
        payload, status = HARNESS._probe_payload(
            {"status_code": 503, "payload": {}}, ("state",)
        )
        self.assertIsNone(payload)
        self.assertEqual(status, HARNESS.PROBE_INDETERMINATE)

    def test_incomplete_nested_runtime_payload_is_indeterminate(self) -> None:
        errors = HARNESS._runtime_payload_errors(
            ingestion={"state": "live"},
            decision={"service_state": "RUNNING"},
            lanes={
                "lanes": {
                    "BTCUSDT:momentum_1h": {
                        "watermark": {"latest_market_as_of": "2026-08-24T14:00:00Z"}
                    }
                }
            },
            inputs={
                "inputs": {
                    "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h": {
                        "latest_market_as_of": "2026-08-24T14:00:00Z"
                    }
                }
            },
            history={"required_series": {}},
        )
        self.assertIn("input:stream:ohlcv:ingestion:binance:BTC-USDT-PERP:4h", errors)
        self.assertIn("lane:BTC-USDT-PERP:4h", errors)
        self.assertEqual(
            errors["input:stream:ohlcv:ingestion:binance:BTC-USDT-PERP:4h"],
            HARNESS.PROBE_INDETERMINATE,
        )
        payload, status = HARNESS._probe_payload(
            {"status_code": 200, "payload": []}, ("state",)
        )
        self.assertIsNone(payload)
        self.assertEqual(status, HARNESS.PROBE_INDETERMINATE)

    def test_interval_lag_is_boundary_based(self) -> None:
        expected = HARNESS.datetime(2026, 8, 24, 15, 0, tzinfo=HARNESS.UTC)
        observed = HARNESS.datetime(2026, 8, 24, 14, 0, tzinfo=HARNESS.UTC)
        self.assertEqual(
            HARNESS._interval_lag(observed, expected, HARNESS.timedelta(hours=1)), 1
        )

    def test_only_actual_history_advance_starts_boundary_scope(self) -> None:
        previous = datetime(2026, 8, 24, 14, 0, tzinfo=UTC)
        self.assertFalse(HARNESS.boundary_advanced(None, previous))
        self.assertFalse(HARNESS.boundary_advanced(previous, previous))
        self.assertTrue(
            HARNESS.boundary_advanced(
                previous, datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
            )
        )

    def test_outbox_pulse_drains_without_zero_every_sample_gate(self) -> None:
        soak = HARNESS.Soak.__new__(HARNESS.Soak)
        soak.outbox_episode = None
        soak.outbox_episodes = []
        now = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
        pending = soak._outbox_state(
            {"outbox_pending": 2, "outbox_oldest_age_seconds": 1.5}, now
        )
        self.assertEqual(pending["status"], "PENDING_DRAINING")
        drained = soak._outbox_state(
            {"outbox_pending": 0, "outbox_oldest_age_seconds": 0.0}, now
        )
        self.assertEqual(drained["status"], "DRAINED")
        self.assertEqual(len(soak.outbox_episodes), 1)

    def test_outbox_persistent_growth_is_distinguished_from_a_pulse(self) -> None:
        soak = HARNESS.Soak.__new__(HARNESS.Soak)
        soak.outbox_episode = None
        soak.outbox_episodes = []
        now = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
        statuses = [
            soak._outbox_state(
                {"outbox_pending": pending, "outbox_oldest_age_seconds": age},
                now,
            )["status"]
            for pending, age in ((1, 1.0), (2, 2.0), (3, 3.0), (4, 4.0), (5, 5.0))
        ]
        self.assertEqual(statuses[-1], "PERSISTENT_GROWTH")


class LifecycleTests(unittest.TestCase):
    def bare(self):
        soak = HARNESS.Soak.__new__(HARNESS.Soak)
        soak.state = {"validity": True}
        soak.stop_event = threading.Event()
        soak.hard_failure = soak.correctness_failure = False
        soak.measurement_started_monotonic = None
        soak.event = Mock()
        return soak

    def test_run_rejects_resume_before_operations(self):
        soak = self.bare()
        soak.state["measurement_start_at"] = "2026-09-08T00:00:00Z"
        soak.start_status_server = Mock()
        self.assertEqual(soak.run(), 2)
        soak.start_status_server.assert_not_called()

    def test_begin_rejects_invalid_and_stopped_attempt(self):
        for stopped in (False, True):
            soak = self.bare()
            soak.state["validity"] = stopped
            if stopped:
                soak.stop_event.set()
            with self.assertRaises(RuntimeError):
                soak.begin_measurement()

    def test_begin_rejects_existing_clock(self):
        soak = self.bare()
        soak.measurement_started_monotonic = 1.0
        with self.assertRaises(RuntimeError):
            soak.begin_measurement()

    def test_incomplete_interval_never_recovers(self):
        soak = self.bare()
        soak.args = SimpleNamespace(measurement_seconds=86400, warmup_only=False)
        soak.state["sut_container_baseline"] = {}
        soak.start_status_server = Mock()
        soak.preflight = Mock()
        soak.warmup = Mock()
        soak._write_state = Mock()
        soak.start_load = Mock()
        soak.load = Mock()
        soak.measure = Mock()
        soak.measurement_completed = False
        soak.recovery = Mock()
        soak.final_audit = Mock()
        soak.cleanup = Mock()
        self.assertEqual(soak.run(), 1)
        soak.recovery.assert_not_called()

    def test_only_exact_pass_statuses_exit_zero(self):
        for status, expected in (
            ("INGESTION_DECISION_24H_SOAK_PASSED", 0),
            ("INGESTION_DECISION_24H_SOAK_PASSED_WITH_WARNINGS", 0),
            ("NOT_PASSED", 2),
        ):
            soak = self.bare()
            soak.args = SimpleNamespace(measurement_seconds=86400, warmup_only=False)
            soak.state["sut_container_baseline"] = {}
            for name in (
                "start_status_server",
                "preflight",
                "warmup",
                "_write_state",
                "start_load",
                "measure",
                "drain",
                "recovery",
            ):
                setattr(soak, name, Mock())
            soak.status_server = None
            soak.load = Mock()
            soak.measurement_completed = True
            soak._measurement_gap_summary = Mock(
                return_value={"exceeds_threshold": False}
            )
            soak._measurement_probe_gap_summary = Mock(
                return_value={"exceeds_threshold": False}
            )
            soak.final_audit = Mock(return_value={"terminal_status": status})
            self.assertEqual(soak.run(), expected)
            soak.drain.assert_called_once()
            soak.recovery.assert_called_once()

    def test_missing_and_edge_gaps_fail(self):
        soak = self.bare()
        soak.samples = Path("/unused")
        soak.state.update(
            measurement_start_at="2026-09-08T00:00:00Z",
            measurement_end_at="2026-09-08T00:03:00Z",
        )
        for stamps, expected in (
            ([], True),
            (["00:01:01", "00:02:00"], True),
            (["00:00:00", "00:00:59"], True),
            (["00:00:00", "00:01:00", "00:02:00", "00:03:00"], False),
        ):
            soak._jsonl_records = Mock(
                return_value=[{"timestamp": f"2026-09-08T{stamp}Z"} for stamp in stamps]
            )
            self.assertEqual(
                soak._measurement_gap_summary("api_load.jsonl")["exceeds_threshold"],
                expected,
            )

    def test_missing_service_fails_coverage(self):
        soak = self.bare()
        soak.samples = Path("/unused")
        soak.state.update(
            measurement_start_at="2026-09-08T00:00:00Z",
            measurement_end_at="2026-09-08T00:00:30Z",
        )
        soak._jsonl_records = Mock(
            return_value=[{"timestamp": "2026-09-08T00:00:15Z", "run": {}}]
        )
        self.assertTrue(
            soak._measurement_gap_summary("resource_samples.jsonl")["exceeds_threshold"]
        )

    def test_storage_uses_declared_scheduled_policy(self):
        soak = self.bare()
        soak.samples = Path("/unused")
        soak.state.update(
            measurement_start_at="2026-09-08T00:00:00Z",
            measurement_end_at="2026-09-08T00:20:00Z",
        )
        soak._jsonl_records = Mock(return_value=[{"timestamp": "2026-09-08T00:10:00Z"}])
        summary = soak._measurement_gap_summary("storage_growth.jsonl")
        self.assertEqual(summary["threshold_seconds"], 1200)
        self.assertFalse(summary["exceeds_threshold"])

    def test_actual_storage_writer_is_measurement_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            soak = self.bare()
            soak.samples = Path(directory)
            soak.phase = "measurement"
            soak.args = SimpleNamespace(project="test-only")
            soak.docker = Mock(return_value=(0, '{"Type":"Images"}', ""))
            soak.state.update(measurement_start_at=HARNESS.legacy.utc_now())
            soak.storage_sample()
            soak.state["measurement_end_at"] = HARNESS.legacy.utc_now()
            records = soak._jsonl_records(soak.samples / "storage_growth.jsonl")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["phase"], "measurement")
            self.assertEqual(records[0]["docker_system_df"], [{"Type": "Images"}])

    def test_cleanup_does_not_spawn_docker(self):
        soak = self.bare()
        soak.status_server = None
        soak.compose = Mock()
        soak.cleanup()
        soak.compose.assert_not_called()

    def test_raw_logs_stream_seven_services_and_fail_closed(self):
        for returncode in (0, 124):
            with tempfile.TemporaryDirectory() as directory:
                soak = self.bare()
                soak.run_dir = soak.root = Path(directory)
                soak.samples = Path(directory) / "samples"
                soak.samples.mkdir()
                soak.phase = "measurement"
                soak.args = SimpleNamespace(
                    project="test-only", override_file="compose.yml"
                )

                def fake_run(command, result_code=returncode, **kwargs):
                    self.assertNotIn("capture_output", kwargs)
                    self.assertEqual(kwargs["timeout"], 42)
                    self.assertIn("--max-file-bytes", command)
                    kwargs["stdout"].write(b"raw retained log\n")
                    return SimpleNamespace(returncode=result_code)

                with patch.object(
                    HARNESS.subprocess, "run", side_effect=fake_run
                ) as execute:
                    soak.log_sample()
                self.assertEqual(execute.call_count, 7)
                self.assertEqual(
                    {call.args[0][-1] for call in execute.call_args_list},
                    set(HARNESS.SERVICES),
                )
                self.assertEqual(
                    len(list((soak.run_dir / "raw-docker-logs").glob("*.log"))), 7
                )
                records = soak._jsonl_records(soak.samples / "raw_logs_manifest.jsonl")
                self.assertEqual(records[0]["complete"], returncode == 0)
                self.assertEqual(soak.state["validity"], returncode == 0)


class ShellRecoveryValidationTests(unittest.TestCase):
    script = HARNESS_PATH.parent.joinpath("launchd/start-run3.sh").read_text()

    def shell(self, body: str, payload: str, **variables: str) -> int:
        definitions = []
        for name in ("validate_recovery_response", "validate_live_runtime"):
            match = re.search(
                rf"^{name}\(\) \{{\n.*?^\}}", self.script, re.MULTILINE | re.DOTALL
            )
            self.assertIsNotNone(match)
            definitions.append(match.group())
        result = subprocess.run(
            [
                "/bin/zsh",
                "-f",
                "-c",
                f"RUN3_PYTHON={shlex.quote(sys.executable)}\n"
                + "\n".join(definitions)
                + "\n"
                + body,
            ],
            input=payload,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **variables},
        )
        return result.returncode

    def payload(self, **updates) -> str:
        return json.dumps(
            {
                "state": "stopped",
                "desired_state": "running",
                "last_error": None,
                "enabled_asset_count": 2,
                **updates,
            }
        )

    def test_async_stopped_ack_does_not_pass_live_gate(self):
        self.assertEqual(self.shell("validate_recovery_response", self.payload()), 0)
        self.assertNotEqual(self.shell("validate_live_runtime", self.payload()), 0)
        self.assertEqual(
            self.shell("validate_live_runtime", self.payload(state="live")), 0
        )

    def test_ack_rejects_malformed_error_disabled_and_invalid_state(self):
        missing_error = json.loads(self.payload())
        del missing_error["last_error"]
        payloads = [
            json.dumps(missing_error),
            "{",
            "null",
            "[]",
            "{}",
            self.payload(last_error="failed"),
            self.payload(enabled_asset_count=0),
            self.payload(enabled_asset_count=False),
            self.payload(enabled_asset_count="2"),
            self.payload(state="invalid"),
            self.payload(desired_state="stopped"),
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertNotEqual(
                    self.shell("validate_recovery_response", payload), 0
                )

    def test_actual_request_condition_rejects_http_failure_body(self):
        start = self.script.index('    if RUN3_RECOVERY_RESPONSE="$(curl')
        end = self.script.index("; then", start) + len("; then")
        condition = self.script[start:end]
        # Stub only transport; execute the real assignment/HTTP-status chain
        # and real shell validator without sourcing operational startup.
        body = (
            'curl() { print -r -- "$TEST_BODY"; return "$TEST_CURL_STATUS"; }\n'
            + condition
            + "\nexit 0\nelse\nexit 1\nfi"
        )
        for status in ("0", "22", "28"):
            with self.subTest(curl_status=status):
                self.assertEqual(
                    self.shell(
                        body, "", TEST_BODY=self.payload(), TEST_CURL_STATUS=status
                    ),
                    0 if status == "0" else 1,
                )


if __name__ == "__main__":
    unittest.main()
