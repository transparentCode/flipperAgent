"""Offline tests for the run-local guarded launch latch."""

from __future__ import annotations

import importlib.util
import json
import plistlib
import shutil
import sys
import tempfile
import unittest
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

MODULE_PATH = Path(__file__).with_name("guarded_launch.py")
SPEC = importlib.util.spec_from_file_location("run_local_guarded_launch", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load guarded launcher")
LAUNCH = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LAUNCH
SPEC.loader.exec_module(LAUNCH)


class GuardedLaunchTests(unittest.TestCase):
    def test_plist_path_resolves_required_host_tools(self) -> None:
        plist_path = (
            MODULE_PATH.parent / "launchd" / "ingestion-decision-soak-run3.plist"
        )
        with plist_path.open("rb") as handle:
            configured_path = plistlib.load(handle)["EnvironmentVariables"]["PATH"]
        for tool in ("caffeinate", "pmset", "ioreg", "docker"):
            with self.subTest(tool=tool):
                self.assertIsNotNone(shutil.which(tool, path=configured_path))

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.temp_dir.name) / "20260909T010152Z"
        self.config = LAUNCH.LaunchConfig(
            run_dir=self.run_dir,
            guard_script=self.run_dir / "source/scripts/host_sleep_guard.py",
            command=("python", "soak_harness.py", "--warmup-only"),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _warmup_runner(self, calls: list[tuple[str, ...]]) -> Callable[..., int]:
        def runner(config: Any, sink: Callable[[Mapping[str, Any]], None]) -> int:
            calls.append(config.command)
            config.harness_state_path.write_text(
                json.dumps(
                    {
                        "run_id": config.run_dir.name,
                        "phase": "warmup_complete",
                        "validity": True,
                        "warmup_completed_at": "2026-09-08T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            sink(
                {
                    "event": "host_sleep_guard",
                    "status": "COMPLETED",
                    "reason_code": "CHILD_EXITED",
                    "child_returncode": 0,
                }
            )
            return 0

        return runner

    def test_success_latches_terminal_and_rejects_restart(self) -> None:
        calls: list[tuple[str, ...]] = []
        runner = self._warmup_runner(calls)

        self.assertEqual(LAUNCH.run_once(self.config, guard_runner=runner), 0)
        state = json.loads(self.config.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["lifecycle"], "TERMINAL")
        self.assertEqual(state["terminal_status"], "COMPLETED")
        self.assertEqual(LAUNCH.run_once(self.config, guard_runner=runner), 0)
        self.assertEqual(len(calls), 1)

    def test_stale_active_latch_refuses_without_restarting_child(self) -> None:
        self.run_dir.mkdir(parents=True)
        self.config.state_path.write_text(
            json.dumps(
                {
                    "schema_version": LAUNCH.STATE_SCHEMA_VERSION,
                    "run_id": self.run_dir.name,
                    "lifecycle": "ACTIVE",
                    "active": True,
                    "terminal": False,
                    "pid": 999999,
                    "started_at": "2026-09-08T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        calls: list[tuple[str, ...]] = []
        self.assertEqual(
            LAUNCH.run_once(self.config, guard_runner=self._warmup_runner(calls)), 0
        )
        self.assertEqual(calls, [])

    def test_malformed_latch_fails_closed(self) -> None:
        self.run_dir.mkdir(parents=True)
        self.config.state_path.write_text("{not-json", encoding="utf-8")
        calls: list[tuple[str, ...]] = []
        self.assertEqual(
            LAUNCH.run_once(self.config, guard_runner=self._warmup_runner(calls)), 0
        )
        self.assertEqual(calls, [])

    def test_lock_refusal_does_not_start_child(self) -> None:
        calls: list[tuple[str, ...]] = []
        with LAUNCH.exclusive_lock(self.config.lock_path) as acquired:
            self.assertTrue(acquired)
            self.assertEqual(
                LAUNCH.run_once(self.config, guard_runner=self._warmup_runner(calls)),
                0,
            )
        self.assertEqual(calls, [])

    def test_guard_failure_invalidates_existing_pass_audit(self) -> None:
        self.run_dir.mkdir(parents=True)

        def runner(config: Any, sink: Callable[[Mapping[str, Any]], None]) -> int:
            config.harness_state_path.write_text(
                json.dumps(
                    {
                        "run_id": config.run_dir.name,
                        "phase": "complete",
                        "validity": True,
                        "terminal_status": "INGESTION_DECISION_24H_SOAK_PASSED",
                    }
                ),
                encoding="utf-8",
            )
            config.audit_path.write_text(
                json.dumps(
                    {
                        "terminal_status": "INGESTION_DECISION_24H_SOAK_PASSED",
                        "state": {"validity": True},
                    }
                ),
                encoding="utf-8",
            )
            sink(
                {
                    "event": "host_sleep_guard",
                    "status": "FAILED",
                    "reason_code": "CHECK_GAP_EXCEEDED",
                    "child_returncode": None,
                }
            )
            return LAUNCH.GUARD_FAILURE_EXIT

        self.assertEqual(LAUNCH.run_once(self.config, guard_runner=runner), 70)
        audit = json.loads(self.config.audit_path.read_text(encoding="utf-8"))
        self.assertNotIn("PASSED", audit["terminal_status"])
        self.assertFalse(audit["state"]["validity"])
        state = json.loads(self.config.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["lifecycle"], "TERMINAL")
        self.assertEqual(state["terminal_status"], "FAILED")

    def test_guard_failure_preserves_prior_correctness_failure(self) -> None:
        self.run_dir.mkdir(parents=True)

        def runner(config: Any, sink: Callable[[Mapping[str, Any]], None]) -> int:
            config.harness_state_path.write_text(
                json.dumps(
                    {
                        "run_id": config.run_dir.name,
                        "phase": "complete",
                        "validity": False,
                        "terminal_status": LAUNCH._CORRECTNESS_FAILURE_STATUS,
                    }
                ),
                encoding="utf-8",
            )
            config.audit_path.write_text(
                json.dumps(
                    {
                        "terminal_status": LAUNCH._CORRECTNESS_FAILURE_STATUS,
                        "state": {"validity": False},
                    }
                ),
                encoding="utf-8",
            )
            sink(
                {
                    "event": "host_sleep_guard",
                    "status": "FAILED",
                    "reason_code": "CHECK_GAP_EXCEEDED",
                    "child_returncode": None,
                }
            )
            return LAUNCH.GUARD_FAILURE_EXIT

        self.assertEqual(LAUNCH.run_once(self.config, guard_runner=runner), 70)
        audit = json.loads(self.config.audit_path.read_text(encoding="utf-8"))
        self.assertEqual(audit["terminal_status"], LAUNCH._CORRECTNESS_FAILURE_STATUS)
        self.assertIn("guard_failure", audit)

    def test_completed_guard_requires_harness_state(self) -> None:
        def runner(_config: Any, sink: Callable[[Mapping[str, Any]], None]) -> int:
            sink(
                {
                    "event": "host_sleep_guard",
                    "status": "COMPLETED",
                    "reason_code": "CHILD_EXITED",
                    "child_returncode": 0,
                }
            )
            return 0

        self.assertEqual(LAUNCH.run_once(self.config, guard_runner=runner), 1)
        state = json.loads(self.config.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["reason_code"], "MISSING_RUN_STATE.json")

    def test_launch_config_rejects_non_finite_timings(self) -> None:
        for field in (
            "probe_interval",
            "probe_timeout",
            "startup_timeout",
            "terminate_grace",
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                LAUNCH.LaunchConfig(
                    run_dir=self.run_dir,
                    guard_script=self.config.guard_script,
                    command=self.config.command,
                    **{field: float("nan")},
                )
            with (
                self.subTest(field=field, invalid_type=True),
                self.assertRaises(TypeError),
            ):
                LAUNCH.LaunchConfig(
                    run_dir=self.run_dir,
                    guard_script=self.config.guard_script,
                    command=self.config.command,
                    **{field: "invalid"},
                )

    def test_loads_actual_exported_guard_module(self) -> None:
        guard_path = MODULE_PATH.parent / "source" / "scripts" / "host_sleep_guard.py"
        module = LAUNCH._load_guard_module(guard_path)
        self.assertIs(sys.modules.get(module.__name__), module)
        guard_config = module.GuardConfig(max_check_gap=60.0)
        self.assertEqual(guard_config.max_check_gap, 60.0)

    def test_completion_requires_an_exact_approved_pass_status(self) -> None:
        config = LAUNCH.LaunchConfig(
            run_dir=self.run_dir,
            guard_script=self.config.guard_script,
            command=("python", "soak_harness.py"),
        )
        self.run_dir.mkdir(parents=True)
        config.harness_state_path.write_text(
            json.dumps({"validity": True, "phase": "complete"}),
            encoding="utf-8",
        )
        guard_record = {
            "event": "host_sleep_guard",
            "status": "COMPLETED",
            "child_returncode": 0,
        }
        config.audit_path.write_text(
            json.dumps({"terminal_status": "NOT_PASSED"}),
            encoding="utf-8",
        )
        reason, _ = LAUNCH._validate_completion(
            config, guard_returncode=0, guard_record=guard_record
        )
        self.assertEqual(reason, "AUDIT_NOT_PASSED")
        config.audit_path.write_text(
            json.dumps({"terminal_status": "INGESTION_DECISION_24H_SOAK_PASSED"}),
            encoding="utf-8",
        )
        reason, _ = LAUNCH._validate_completion(
            config, guard_returncode=0, guard_record=guard_record
        )
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
