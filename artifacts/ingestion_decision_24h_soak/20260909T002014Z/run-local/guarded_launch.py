"""Run one fresh soak harness under the committed sleep guard.

This is run-local supervision only.  It owns the persistent launch latch and
lock, imports the frozen ``SleepAssertionGuard`` from the source export, and
keeps a terminal record after any completed or failed attempt.  A malformed,
stale-active, or terminal record is a refusal rather than permission to start
another child.  No Docker or provider operation is performed by this module
unless the explicitly supplied harness command performs it.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import math
import os
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATE_SCHEMA_VERSION = 1
GUARD_MAX_CHECK_GAP_SECONDS = 60.0
GUARD_FAILURE_EXIT = 70
TERMINAL_REFUSAL_EXIT = 0

STATE_FILE_NAME = "GUARDED_LAUNCH_STATE.json"
LOCK_FILE_NAME = ".guarded_launch.lock"
GUARD_EVIDENCE_FILE_NAME = "HOST_SLEEP_GUARD.jsonl"
HARNESS_STATE_FILE_NAME = "RUN_STATE.json"
AUDIT_FILE_NAME = "final_audit.json"

_TERMINAL_STATUS_MARKER = "INGESTION_DECISION_24H_SOAK_INCONCLUSIVE_EVIDENCE"
_PASS_STATUSES = frozenset(
    {
        "INGESTION_DECISION_24H_SOAK_PASSED",
        "INGESTION_DECISION_24H_SOAK_PASSED_WITH_WARNINGS",
    }
)
_CORRECTNESS_FAILURE_STATUS = "INGESTION_DECISION_24H_SOAK_FAILED_CORRECTNESS"


class LaunchFailure(RuntimeError):
    """A bounded failure that must latch the run closed."""

    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class LaunchConfig:
    """Explicit inputs for one guarded launch attempt."""

    run_dir: Path
    guard_script: Path
    command: tuple[str, ...]
    max_check_gap_seconds: float = GUARD_MAX_CHECK_GAP_SECONDS
    probe_interval: float = 5.0
    probe_timeout: float = 2.0
    startup_timeout: float = 8.0
    terminate_grace: float = 2.0

    def __post_init__(self) -> None:
        if not self.command or any(
            not isinstance(item, str) or not item for item in self.command
        ):
            raise ValueError("command must be a non-empty argv")
        if self.max_check_gap_seconds != GUARD_MAX_CHECK_GAP_SECONDS:
            raise ValueError("the approved guard gap is fixed at 60 seconds")
        for name in (
            "max_check_gap_seconds",
            "probe_interval",
            "probe_timeout",
            "startup_timeout",
            "terminate_grace",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a finite positive number")
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite or value <= 0:
                raise ValueError(f"{name} must be a finite positive number")

    @property
    def state_path(self) -> Path:
        return self.run_dir / STATE_FILE_NAME

    @property
    def lock_path(self) -> Path:
        return self.run_dir / LOCK_FILE_NAME

    @property
    def guard_evidence_path(self) -> Path:
        return self.run_dir / GUARD_EVIDENCE_FILE_NAME

    @property
    def harness_state_path(self) -> Path:
        return self.run_dir / HARNESS_STATE_FILE_NAME

    @property
    def audit_path(self) -> Path:
        return self.run_dir / AUDIT_FILE_NAME


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _command_digest(command: Sequence[str]) -> str:
    return hashlib.sha256("\0".join(command).encode("utf-8")).hexdigest()


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _append_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _load_object(path: Path, *, required: bool) -> dict[str, Any] | None:
    if not path.exists():
        if required:
            raise LaunchFailure(f"MISSING_{path.name}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LaunchFailure(f"MALFORMED_{path.name}") from exc
    if not isinstance(value, dict):
        raise LaunchFailure(f"MALFORMED_{path.name}")
    return value


def _validate_latch(state: Mapping[str, Any], run_dir: Path) -> None:
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise LaunchFailure("MALFORMED_GUARDED_LAUNCH_STATE")
    if state.get("run_id") != run_dir.name:
        raise LaunchFailure("GUARDED_LAUNCH_RUN_ID_MISMATCH")
    lifecycle = state.get("lifecycle")
    if lifecycle not in {"ACTIVE", "TERMINAL"}:
        raise LaunchFailure("MALFORMED_GUARDED_LAUNCH_STATE")
    if lifecycle == "ACTIVE":
        if state.get("active") is not True or state.get("terminal") is not False:
            raise LaunchFailure("MALFORMED_ACTIVE_LAUNCH_STATE")
        pid = state.get("pid")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise LaunchFailure("MALFORMED_ACTIVE_LAUNCH_STATE")
        if not isinstance(state.get("started_at"), str) or not state["started_at"]:
            raise LaunchFailure("MALFORMED_ACTIVE_LAUNCH_STATE")
    else:
        if state.get("active") is not False or state.get("terminal") is not True:
            raise LaunchFailure("MALFORMED_TERMINAL_LAUNCH_STATE")
        if (
            not isinstance(state.get("terminal_status"), str)
            or not state["terminal_status"]
        ):
            raise LaunchFailure("MALFORMED_TERMINAL_LAUNCH_STATE")


@contextmanager
def exclusive_lock(path: Path) -> Iterator[bool]:
    """Acquire the run-owned non-blocking lock, if it is available."""

    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+", encoding="utf-8")
    acquired = False
    try:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        if acquired:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def _active_state(config: LaunchConfig) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "run_id": config.run_dir.name,
        "lifecycle": "ACTIVE",
        "active": True,
        "terminal": False,
        "pid": os.getpid(),
        "started_at": _utc_now(),
        "command_sha256": _command_digest(config.command),
        "guard": {
            "max_check_gap_seconds": config.max_check_gap_seconds,
            "probe_interval": config.probe_interval,
            "probe_timeout": config.probe_timeout,
            "startup_timeout": config.startup_timeout,
            "terminate_grace": config.terminate_grace,
        },
        "guard_evidence_path": str(config.guard_evidence_path),
        "harness_state_path": str(config.harness_state_path),
    }


def _terminal_state(
    active: Mapping[str, Any],
    *,
    status: str,
    exit_code: int,
    guard_record: Mapping[str, Any] | None,
    reason_code: str | None = None,
    harness_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = dict(active)
    result.update(
        {
            "lifecycle": "TERMINAL",
            "active": False,
            "terminal": True,
            "terminal_status": status,
            "exit_code": exit_code,
            "finished_at": _utc_now(),
            "guard_record": dict(guard_record) if guard_record else None,
        }
    )
    if reason_code:
        result["reason_code"] = reason_code
    if harness_state is not None:
        result["harness_terminal_status"] = harness_state.get("terminal_status")
        result["harness_phase"] = harness_state.get("phase")
        result["harness_validity"] = harness_state.get("validity")
    return result


def _guard_record(records: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    for record in reversed(records):
        if record.get("event") == "host_sleep_guard":
            return dict(record)
    return None


def _read_audit(path: Path) -> dict[str, Any]:
    audit = _load_object(path, required=True)
    assert audit is not None
    return audit


def _invalidate_audit(
    config: LaunchConfig,
    *,
    reason_code: str,
    guard_record: Mapping[str, Any] | None,
) -> None:
    """Ensure a failed guard cannot leave a previous-looking pass artifact."""

    try:
        audit = _read_audit(config.audit_path) if config.audit_path.exists() else {}
    except LaunchFailure:
        audit = {}
    prior_status = audit.get("terminal_status")
    if not isinstance(prior_status, str) or prior_status in _PASS_STATUSES:
        # A guard failure must remove a prior green result. Preserve an
        # already-detected correctness failure so the guard/environment defect
        # remains separate evidence rather than masking the cause.
        audit["terminal_status"] = _TERMINAL_STATUS_MARKER
    elif prior_status == _CORRECTNESS_FAILURE_STATUS:
        audit["terminal_status"] = prior_status
    audit["error"] = f"guarded launch failed closed: {reason_code}"
    audit["guard_failure"] = {
        "reason_code": reason_code,
        "record": dict(guard_record) if guard_record else None,
    }
    nested_state = audit.get("state")
    if not isinstance(nested_state, dict):
        nested_state = {}
        audit["state"] = nested_state
    nested_state["validity"] = False
    nested_state["guard_failure"] = dict(audit["guard_failure"])
    _atomic_json_write(config.audit_path, audit)

    if config.harness_state_path.exists():
        try:
            harness_state = _load_object(config.harness_state_path, required=True)
        except LaunchFailure:
            harness_state = None
        if harness_state is not None:
            harness_state["validity"] = False
            harness_state["guard_failure"] = dict(audit["guard_failure"])
            if harness_state.get("terminal_status") in _PASS_STATUSES:
                harness_state["terminal_status"] = _TERMINAL_STATUS_MARKER
            _atomic_json_write(config.harness_state_path, harness_state)


def _validate_completion(
    config: LaunchConfig,
    *,
    guard_returncode: int,
    guard_record: Mapping[str, Any] | None,
) -> tuple[str | None, dict[str, Any] | None]:
    if guard_record is None:
        return "GUARD_EVIDENCE_MISSING", None
    if guard_record.get("status") != "COMPLETED":
        return str(guard_record.get("reason_code") or "GUARD_FAILED"), None
    if guard_returncode != 0:
        return "GUARDED_CHILD_FAILED", None
    child_returncode = guard_record.get("child_returncode")
    if child_returncode != 0:
        return "HARNESS_EXITED_NONZERO", None

    try:
        harness_state = _load_object(config.harness_state_path, required=True)
    except LaunchFailure as exc:
        return exc.reason_code, None
    assert harness_state is not None
    if not isinstance(harness_state.get("validity"), bool):
        return "MALFORMED_RUN_STATE", harness_state
    if harness_state["validity"] is not True:
        return "HARNESS_STATE_INVALID", harness_state

    warmup_only = "--warmup-only" in config.command
    if warmup_only:
        if harness_state.get("phase") != "warmup_complete":
            return "WARMUP_COMPLETION_UNVERIFIED", harness_state
        if not isinstance(harness_state.get("warmup_completed_at"), str):
            return "WARMUP_COMPLETION_UNVERIFIED", harness_state
        return None, harness_state

    try:
        audit = _read_audit(config.audit_path)
    except LaunchFailure as exc:
        return exc.reason_code, harness_state
    status = audit.get("terminal_status")
    if status not in _PASS_STATUSES:
        return "AUDIT_NOT_PASSED", harness_state
    return None, harness_state


def _load_guard_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("run_local_host_sleep_guard", path)
    if spec is None or spec.loader is None:
        raise LaunchFailure("GUARD_MODULE_UNLOADABLE")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(spec.name)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if previous is None:
            sys.modules.pop(spec.name, None)
        else:
            sys.modules[spec.name] = previous
        raise
    return module


def _default_guard_runner(
    config: LaunchConfig, evidence_sink: Callable[[Mapping[str, Any]], None]
) -> int:
    guard_module = _load_guard_module(config.guard_script)
    guard_config = guard_module.GuardConfig(
        max_check_gap=config.max_check_gap_seconds,
        probe_interval=config.probe_interval,
        probe_timeout=config.probe_timeout,
        startup_timeout=config.startup_timeout,
        terminate_grace=config.terminate_grace,
    )
    guard = guard_module.SleepAssertionGuard(
        config=guard_config,
        evidence_sink=evidence_sink,
    )
    return int(guard.run(config.command))


def _refuse(reason_code: str) -> int:
    print(f"guarded launch refused: {reason_code}", file=sys.stderr)
    return TERMINAL_REFUSAL_EXIT


def run_once(
    config: LaunchConfig,
    *,
    guard_runner: Callable[[LaunchConfig, Callable[[Mapping[str, Any]], None]], int]
    | None = None,
) -> int:
    """Run one latched attempt; refuse all overlap or restart paths."""

    config.run_dir.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(config.lock_path) as acquired:
        if not acquired:
            return _refuse("LOCK_HELD")

        try:
            previous = _load_object(config.state_path, required=False)
            if previous is not None:
                _validate_latch(previous, config.run_dir)
                if previous["lifecycle"] == "ACTIVE":
                    return _refuse("STALE_OR_ACTIVE_LAUNCH")
                return _refuse("TERMINAL_LAUNCH")
        except LaunchFailure as exc:
            return _refuse(exc.reason_code)

        active = _active_state(config)
        _atomic_json_write(config.state_path, active)
        records: list[dict[str, Any]] = []

        def evidence_sink(record: Mapping[str, Any]) -> None:
            if not isinstance(record, Mapping):
                raise LaunchFailure("MALFORMED_GUARD_EVIDENCE")
            normalized = dict(record)
            records.append(normalized)
            _append_json(config.guard_evidence_path, normalized)

        runner = guard_runner or _default_guard_runner
        guard_returncode = GUARD_FAILURE_EXIT
        guard_record: dict[str, Any] | None = None
        try:
            guard_returncode = int(runner(config, evidence_sink))
            guard_record = _guard_record(records)
            reason_code, harness_state = _validate_completion(
                config,
                guard_returncode=guard_returncode,
                guard_record=guard_record,
            )
            if reason_code is not None:
                _invalidate_audit(
                    config,
                    reason_code=reason_code,
                    guard_record=guard_record,
                )
                final_state = _terminal_state(
                    active,
                    status="FAILED",
                    exit_code=guard_returncode or 1,
                    guard_record=guard_record,
                    reason_code=reason_code,
                    harness_state=harness_state,
                )
                _atomic_json_write(config.state_path, final_state)
                return guard_returncode or 1

            final_state = _terminal_state(
                active,
                status="COMPLETED",
                exit_code=0,
                guard_record=guard_record,
                harness_state=harness_state,
            )
            _atomic_json_write(config.state_path, final_state)
            return 0
        except (KeyboardInterrupt, Exception) as exc:  # noqa: BLE001
            reason_code = (
                exc.reason_code
                if isinstance(exc, LaunchFailure)
                else f"WRAPPER_FAILURE_{type(exc).__name__}"
            )
            try:
                if guard_record is None:
                    guard_record = _guard_record(records)
                _invalidate_audit(
                    config,
                    reason_code=reason_code,
                    guard_record=guard_record,
                )
            finally:
                _atomic_json_write(
                    config.state_path,
                    _terminal_state(
                        active,
                        status="FAILED",
                        exit_code=GUARD_FAILURE_EXIT,
                        guard_record=guard_record,
                        reason_code=reason_code,
                    ),
                )
            return GUARD_FAILURE_EXIT


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one fresh soak harness under the committed sleep guard."
    )
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--guard-script", type=Path)
    parser.add_argument("--probe-interval", type=float, default=5.0)
    parser.add_argument("--probe-timeout", type=float, default=2.0)
    parser.add_argument("--startup-timeout", type=float, default=8.0)
    parser.add_argument("--terminate-grace", type=float, default=2.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        _parser().error("an explicit harness command argv is required after --")
    guard_script = args.guard_script or (
        Path(__file__).resolve().parent / "source" / "scripts" / "host_sleep_guard.py"
    )
    config = LaunchConfig(
        run_dir=args.run_dir.resolve(),
        guard_script=guard_script.resolve(),
        command=tuple(command),
        probe_interval=args.probe_interval,
        probe_timeout=args.probe_timeout,
        startup_timeout=args.startup_timeout,
        terminate_grace=args.terminate_grace,
    )
    return run_once(config)


if __name__ == "__main__":
    raise SystemExit(main())
