"""Bounded macOS sleep-assertion guard for a future pre-soak wrapper.

This module intentionally does not start a scheduler, launchd job, container,
or soak.  It owns one ``caffeinate`` process and one explicitly supplied child
process.  The assertion is verified by owner PID before the child starts and
periodically while the child runs.  Any failure is reported as one bounded,
machine-readable JSON record without command arguments or environment data.

Example (future wiring only)::

    .venv/bin/python scripts/host_sleep_guard.py \
        --max-check-gap 60 --probe-interval 10 -- \
        python -c 'print("harmless smoke")'

``-s`` is effective only on AC power.  A closed lid, forced sleep, power loss,
or power removal can still interrupt a run; this guard reports an evidence gap
and never treats an interrupted interval as valid.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from threading import Event
from typing import Any, TextIO

REQUIRED_ASSERTION_TYPES = frozenset(
    {"PreventUserIdleSystemSleep", "PreventSystemSleep"}
)
GUARD_FAILURE_EXIT = 70


class ProbeKind(str, Enum):
    """Redacted names for the bounded host probes."""

    AC_POWER = "AC"
    LID_STATE = "LID"
    ASSERTIONS = "ASSERTIONS"


class ProbePhase(str, Enum):
    """Guard phase in which a host probe was attempted."""

    INITIAL = "INITIAL"
    STARTUP = "STARTUP"
    RUNTIME = "RUNTIME"


class ProbeTimingStatus(str, Enum):
    """Whether monotonic elapsed time was available for a host probe."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ProbeMetadata:
    """Constant-size, redaction-safe metadata for one host probe."""

    kind: ProbeKind
    phase: ProbePhase
    requested_timeout_seconds: float
    elapsed_monotonic_seconds: float | None
    timing_status: ProbeTimingStatus

    def as_record(
        self, last_successful_full_verification_at: str | None
    ) -> dict[str, Any]:
        return {
            "probe_kind": self.kind.value,
            "phase": self.phase.value,
            "requested_timeout_seconds": self.requested_timeout_seconds,
            "elapsed_monotonic_seconds": self.elapsed_monotonic_seconds,
            "timing_status": self.timing_status.value,
            "last_successful_full_verification_at": last_successful_full_verification_at,
        }


def _require_positive_finite(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a positive finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value <= 0:
        raise ValueError(f"{field_name} must be a positive finite number")


class GuardFailure(RuntimeError):
    """A bounded, redaction-safe guard failure."""

    def __init__(
        self,
        reason_code: str,
        *,
        signal_number: int | None = None,
        probe_metadata: ProbeMetadata | None = None,
    ):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.signal_number = signal_number
        self.probe_metadata = probe_metadata


@dataclass(frozen=True, slots=True)
class ToolPaths:
    """Resolved host tools used by one guard invocation."""

    caffeinate: str
    pmset: str
    ioreg: str


@dataclass(frozen=True, slots=True)
class AssertionRow:
    """One parsed ``pmset -g assertions`` owner row."""

    pid: int
    process_name: str
    assertion_type: str


@dataclass(frozen=True, slots=True)
class GuardConfig:
    """Finite guard timings; none are a soak or production latency SLO."""

    max_check_gap: float
    probe_interval: float = 5.0
    probe_timeout: float = 2.0
    startup_timeout: float = 8.0
    terminate_grace: float = 2.0

    def __post_init__(self) -> None:
        for field_name in (
            "max_check_gap",
            "probe_interval",
            "probe_timeout",
            "startup_timeout",
            "terminate_grace",
        ):
            value = getattr(self, field_name)
            _require_positive_finite(value, field_name)


@dataclass(frozen=True, slots=True)
class GuardDependencies:
    """Injectable side effects for deterministic parser/process tests."""

    popen: Callable[..., Any] = subprocess.Popen
    run_probe: Callable[..., Any] | None = None
    executable_lookup: Callable[[str], str | None] = shutil.which
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    killpg: Callable[[int, int], None] = os.killpg
    group_exists: Callable[[int], bool] = lambda pgid: _default_group_exists(pgid)


def _default_group_exists(pgid: int) -> bool:
    """Return whether a process group is still addressable by its PGID."""

    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    return True


def _default_run_probe(argv: Sequence[str], timeout: float) -> Any:
    return subprocess.run(
        list(argv),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def parse_ac_power(output: str) -> bool:
    """Return whether ``pmset -g batt`` positively reports AC power."""

    if not isinstance(output, str):
        raise GuardFailure("POWER_UNVERIFIABLE")
    match = re.search(
        r"Now\s+drawing\s+from\s+['\"](?P<source>[^'\"]+)['\"]",
        output,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise GuardFailure("POWER_UNVERIFIABLE")
    source = match.group("source").strip().lower()
    if source == "ac power":
        return True
    if source == "battery power":
        raise GuardFailure("ON_BATTERY")
    raise GuardFailure("POWER_UNVERIFIABLE")


def parse_lid_open(output: str) -> bool:
    """Return the explicit AppleClamshellState value (``No`` means open)."""

    if not isinstance(output, str):
        raise GuardFailure("LID_UNVERIFIABLE")
    match = re.search(
        r"AppleClamshellState[\"']?\s*=\s*[\"']?(?P<state>Yes|No|1|0)",
        output,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise GuardFailure("LID_UNVERIFIABLE")
    state = match.group("state").lower()
    return state in {"no", "0"}


_ASSERTION_LINE = re.compile(
    r"^\s*pid\s+(?P<pid>\d+)\((?P<process>[^)]+)\):(?P<body>.*)$",
    flags=re.IGNORECASE,
)


def parse_assertion_rows(output: str) -> tuple[AssertionRow, ...]:
    """Parse owner rows without treating unrelated global counters as owned."""

    if not isinstance(output, str):
        raise GuardFailure("ASSERTION_UNVERIFIABLE")
    rows: list[AssertionRow] = []
    saw_pid_text = False
    for line in output.splitlines():
        if "pid" in line.lower():
            saw_pid_text = True
        match = _ASSERTION_LINE.match(line)
        if match is None:
            continue
        body = match.group("body")
        assertion_match = re.search(
            r"\b(?P<kind>Prevent[A-Za-z]+)\b",
            body,
        )
        if assertion_match is None:
            continue
        rows.append(
            AssertionRow(
                pid=int(match.group("pid")),
                process_name=match.group("process").strip(),
                assertion_type=assertion_match.group("kind"),
            )
        )
    if not rows and saw_pid_text:
        raise GuardFailure("ASSERTION_UNVERIFIABLE")
    return tuple(rows)


class HostProbe:
    """Read-only, bounded probes for the macOS host contract."""

    def __init__(
        self,
        *,
        run_probe: Callable[..., Any] | None = None,
        executable_lookup: Callable[[str], str | None] = shutil.which,
        probe_timeout: float = 2.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        _require_positive_finite(probe_timeout, "probe_timeout")
        self._run_probe = run_probe or _default_run_probe
        self._lookup = executable_lookup
        self._probe_timeout = float(probe_timeout)
        self._monotonic = monotonic
        self._phase = ProbePhase.INITIAL
        self._last_probe_metadata: ProbeMetadata | None = None

    def _set_phase(self, phase: ProbePhase) -> None:
        self._phase = phase

    def _read_monotonic(self) -> float | None:
        try:
            value = self._monotonic()
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            value = float(value)
        except Exception:  # noqa: BLE001
            return None
        if not math.isfinite(value) or value < 0:
            return None
        return value

    def _finish_probe(
        self,
        kind: ProbeKind,
        requested_timeout_seconds: float,
        started_at: float | None,
    ) -> ProbeMetadata:
        finished_at = self._read_monotonic()
        elapsed: float | None = None
        timing_status = ProbeTimingStatus.UNAVAILABLE
        if started_at is not None and finished_at is not None:
            candidate = finished_at - started_at
            if math.isfinite(candidate) and candidate >= 0:
                elapsed = candidate
                timing_status = ProbeTimingStatus.AVAILABLE
        metadata = ProbeMetadata(
            kind=kind,
            phase=self._phase,
            requested_timeout_seconds=float(requested_timeout_seconds),
            elapsed_monotonic_seconds=elapsed,
            timing_status=timing_status,
        )
        self._last_probe_metadata = metadata
        return metadata

    def resolve_tools(self) -> ToolPaths:
        resolved = {
            name: self._lookup(name) for name in ("caffeinate", "pmset", "ioreg")
        }
        if any(path is None for path in resolved.values()):
            raise GuardFailure("MISSING_TOOL")
        return ToolPaths(
            caffeinate=resolved["caffeinate"],  # type: ignore[arg-type]
            pmset=resolved["pmset"],  # type: ignore[arg-type]
            ioreg=resolved["ioreg"],  # type: ignore[arg-type]
        )

    def _run(
        self,
        argv: Sequence[str],
        *,
        kind: ProbeKind,
        timeout: Callable[[], float] | None = None,
    ) -> str:
        requested_timeout = (
            self._probe_timeout
            if timeout is None
            else min(self._probe_timeout, timeout())
        )
        started_at = self._read_monotonic()
        try:
            result = self._run_probe(argv, requested_timeout)
        except subprocess.TimeoutExpired as exc:
            del exc
            metadata = self._finish_probe(kind, requested_timeout, started_at)
            raise GuardFailure("PROBE_TIMEOUT", probe_metadata=metadata) from None
        except (FileNotFoundError, OSError) as exc:
            del exc
            metadata = self._finish_probe(kind, requested_timeout, started_at)
            raise GuardFailure("MISSING_TOOL", probe_metadata=metadata) from None
        metadata = self._finish_probe(kind, requested_timeout, started_at)
        if getattr(result, "returncode", None) != 0:
            raise GuardFailure("PROBE_FAILED", probe_metadata=metadata)
        output = getattr(result, "stdout", None)
        if not isinstance(output, str):
            raise GuardFailure("PROBE_MALFORMED", probe_metadata=metadata)
        return output

    def verify_environment(
        self,
        tools: ToolPaths,
        *,
        runtime: bool = False,
        timeout: Callable[[], float] | None = None,
    ) -> None:
        power_output = self._run(
            (tools.pmset, "-g", "batt"), kind=ProbeKind.AC_POWER, timeout=timeout
        )
        try:
            on_ac = parse_ac_power(power_output)
        except GuardFailure as exc:
            probe_metadata = self._last_probe_metadata
            if runtime and exc.reason_code == "ON_BATTERY":
                raise GuardFailure("AC_LOST", probe_metadata=probe_metadata) from None
            raise GuardFailure(exc.reason_code, probe_metadata=probe_metadata) from None
        if not on_ac:
            raise GuardFailure("ON_BATTERY", probe_metadata=self._last_probe_metadata)

        lid_output = self._run(
            (tools.ioreg, "-r", "-k", "AppleClamshellState", "-d", "1"),
            kind=ProbeKind.LID_STATE,
            timeout=timeout,
        )
        try:
            lid_open = parse_lid_open(lid_output)
        except GuardFailure as exc:
            raise GuardFailure(
                exc.reason_code, probe_metadata=self._last_probe_metadata
            ) from None
        if not lid_open:
            raise GuardFailure("LID_CLOSED", probe_metadata=self._last_probe_metadata)

    def verify_assertion(
        self,
        tools: ToolPaths,
        owner_pid: int,
        *,
        timeout: Callable[[], float] | None = None,
    ) -> None:
        output = self._run(
            (tools.pmset, "-g", "assertions"),
            kind=ProbeKind.ASSERTIONS,
            timeout=timeout,
        )
        try:
            rows = parse_assertion_rows(output)
        except GuardFailure as exc:
            raise GuardFailure(
                exc.reason_code, probe_metadata=self._last_probe_metadata
            ) from None
        owned = {
            row.assertion_type
            for row in rows
            if row.pid == owner_pid and row.process_name.lower() == "caffeinate"
        }
        if not REQUIRED_ASSERTION_TYPES.issubset(owned):
            raise GuardFailure(
                "ASSERTION_MISSING", probe_metadata=self._last_probe_metadata
            )


class SleepAssertionGuard:
    """Own and supervise one assertion plus one child process group."""

    def __init__(
        self,
        *,
        config: GuardConfig | None = None,
        probe: HostProbe | None = None,
        dependencies: GuardDependencies | None = None,
        evidence_stream: TextIO | None = None,
        evidence_sink: Callable[[Mapping[str, Any]], None] | None = None,
        owner_pid: Callable[[], int] = os.getpid,
        stop_event: Event | None = None,
        install_signal_handlers: bool = True,
    ) -> None:
        if config is None:
            raise TypeError("config with explicit max_check_gap is required")
        self._config = config
        self._dependencies = dependencies or GuardDependencies()
        self._probe = probe or HostProbe(
            run_probe=self._dependencies.run_probe,
            executable_lookup=self._dependencies.executable_lookup,
            probe_timeout=self._config.probe_timeout,
            monotonic=self._dependencies.monotonic,
        )
        self._evidence_stream = evidence_stream or sys.stderr
        self._evidence_sink = evidence_sink
        self._owner_pid = owner_pid
        self._stop_event = stop_event or Event()
        self._stop_signal: int | None = None
        self._install_signal_handlers = install_signal_handlers
        self._last_successful_full_verification_at: str | None = None

    def request_stop(self, signum: int, _frame: Any | None = None) -> None:
        """Request bounded cleanup of only this guard's owned processes."""

        del _frame
        self._stop_signal = signum
        self._stop_event.set()

    def _check_stop(self) -> None:
        if self._stop_event.is_set():
            raise GuardFailure("GUARD_SIGNAL", signal_number=self._stop_signal)

    def _set_probe_phase(self, phase: ProbePhase) -> None:
        set_phase = getattr(self._probe, "_set_phase", None)
        if callable(set_phase):
            set_phase(phase)

    @contextmanager
    def _signal_handlers(self):
        if not self._install_signal_handlers:
            yield
            return
        previous: dict[int, Any] = {}
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, self.request_stop)
        try:
            yield
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)

    def _timestamp(self) -> str:
        value = self._utc_now()
        return value.isoformat().replace("+00:00", "Z")

    def _utc_now(self) -> datetime:
        value = self._dependencies.now()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise GuardFailure("CLOCK_UNVERIFIABLE")
        return value.astimezone(UTC)

    def _emit(self, record: Mapping[str, Any]) -> None:
        if self._evidence_sink is not None:
            self._evidence_sink(record)
            return
        print(json.dumps(dict(record), sort_keys=True), file=self._evidence_stream)
        self._evidence_stream.flush()

    def _start_assertion(self, tools: ToolPaths) -> Any:
        try:
            return self._dependencies.popen(
                [
                    tools.caffeinate,
                    "-i",
                    "-s",
                    "-w",
                    str(self._owner_pid()),
                ],
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            del exc
            raise GuardFailure("ASSERTION_START_FAILED") from None

    def _start_child(self, command: Sequence[str]) -> Any:
        try:
            # Inherit stdout/stderr and close stdin: no pipe is captured, so a
            # long-running child cannot deadlock the guard on a full buffer.
            return self._dependencies.popen(
                list(command),
                shell=False,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            del exc
            raise GuardFailure("CHILD_START_FAILED") from None

    def _wait_for_assertion(self, assertion: Any, tools: ToolPaths) -> datetime:
        deadline = self._dependencies.monotonic() + self._config.startup_timeout
        self._startup_deadline = deadline

        def remaining_budget() -> float:
            self._check_stop()
            remaining = deadline - self._dependencies.monotonic()
            if remaining <= 0:
                raise GuardFailure("ASSERTION_STARTUP_TIMEOUT")
            return min(self._config.probe_timeout, remaining)

        while True:
            self._check_stop()
            if assertion.poll() is not None:
                raise GuardFailure("ASSERTION_EXITED")
            remaining = deadline - self._dependencies.monotonic()
            if remaining <= 0:
                raise GuardFailure("ASSERTION_STARTUP_TIMEOUT")
            self._set_probe_phase(ProbePhase.STARTUP)
            self._probe.verify_environment(
                tools,
                timeout=remaining_budget,
            )
            remaining = deadline - self._dependencies.monotonic()
            if remaining <= 0:
                raise GuardFailure("ASSERTION_STARTUP_TIMEOUT")
            try:
                self._probe.verify_assertion(
                    tools,
                    assertion.pid,
                    timeout=remaining_budget,
                )
            except GuardFailure as exc:
                if (
                    exc.reason_code != "ASSERTION_MISSING"
                    or self._dependencies.monotonic() >= deadline
                ):
                    if exc.reason_code == "ASSERTION_MISSING":
                        raise GuardFailure(
                            "ASSERTION_STARTUP_TIMEOUT",
                            probe_metadata=exc.probe_metadata,
                        ) from None
                    raise
                remaining = max(0.0, deadline - self._dependencies.monotonic())
                if remaining <= 0:
                    raise GuardFailure("ASSERTION_STARTUP_TIMEOUT") from None
                self._dependencies.sleep(min(self._config.probe_interval, remaining))
                continue
            checked_at = self._utc_now()
            remaining_budget()
            return checked_at

    def _verify_runtime(
        self,
        assertion: Any,
        tools: ToolPaths,
        previous_check_at: datetime,
    ) -> datetime:
        if assertion.poll() is not None:
            raise GuardFailure("ASSERTION_EXITED")
        self._set_probe_phase(ProbePhase.RUNTIME)
        self._probe.verify_environment(tools, runtime=True)
        self._probe.verify_assertion(tools, assertion.pid)
        current_check_at = self._utc_now()
        if current_check_at < previous_check_at:
            raise GuardFailure("CLOCK_BACKWARDS")
        if (
            current_check_at - previous_check_at
        ).total_seconds() > self._config.max_check_gap:
            raise GuardFailure("CHECK_GAP_EXCEEDED")
        return current_check_at

    def _terminate_group(self, process: Any) -> bool:
        pid = getattr(process, "pid", None)
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            return False

        def group_state() -> bool | None:
            try:
                state = self._dependencies.group_exists(pid)
                return state if isinstance(state, bool) else None
            except ProcessLookupError:
                return False
            except OSError:
                return None

        def wait_group() -> bool | None:
            deadline = self._dependencies.monotonic() + self._config.terminate_grace
            while True:
                process.poll()
                state = group_state()
                if state is not True:
                    return state
                remaining = deadline - self._dependencies.monotonic()
                if remaining <= 0:
                    return True
                self._dependencies.sleep(min(0.01, remaining))

        state = group_state()
        if state is None:
            return False
        if not state:
            return process.poll() is not None
        try:
            self._dependencies.killpg(pid, signal.SIGTERM)
            state = wait_group()
            if state is None:
                return False
            if not state:
                return process.poll() is not None
            self._dependencies.killpg(pid, signal.SIGKILL)
            state = wait_group()
            if state is None:
                return False
            return not state and process.poll() is not None
        except ProcessLookupError:
            # The group may have exited between the bounded ownership probe
            # and the signal.  It is safe only if the owned leader is reaped
            # and the group is now absent; permission/other probe failures
            # remain a closed failure below.
            state = group_state()
            return state is False and process.poll() is not None
        except OSError:
            return False

    def _monitor(
        self,
        child: Any,
        assertion: Any,
        tools: ToolPaths,
        last_check_at: datetime,
    ) -> int:
        while True:
            self._check_stop()
            returncode = child.poll()
            if returncode is not None:
                # Freeze host evidence while the assertion is still owned.
                checked_at = self._verify_runtime(assertion, tools, last_check_at)
                self._last_successful_full_verification_at = self._format_timestamp(
                    checked_at
                )
                return int(returncode)
            try:
                child.wait(timeout=self._config.probe_interval)
            except subprocess.TimeoutExpired:
                pass
            if child.poll() is None:
                last_check_at = self._verify_runtime(assertion, tools, last_check_at)
                self._last_successful_full_verification_at = self._format_timestamp(
                    last_check_at
                )

    def run(self, command: Sequence[str]) -> int:
        """Run one explicit argv under the verified assertion."""

        if not command or any(
            not isinstance(item, str) or not item for item in command
        ):
            raise ValueError("command must be a non-empty argv")
        started_at: str | None = None
        assertion = None
        child = None
        assertion_pid: int | None = None
        child_pid: int | None = None
        child_returncode: int | None = None
        status = "FAILED"
        reason_code = "INTERNAL_GUARD_ERROR"
        exit_code = GUARD_FAILURE_EXIT
        cleanup_failed = False
        probe_metadata: ProbeMetadata | None = None
        self._last_successful_full_verification_at = None

        with self._signal_handlers():
            try:
                started_at = self._timestamp()
                tools = self._probe.resolve_tools()
                self._set_probe_phase(ProbePhase.INITIAL)
                self._probe.verify_environment(tools)
                self._check_stop()
                assertion = self._start_assertion(tools)
                assertion_pid = assertion.pid
                last_check_at = self._wait_for_assertion(assertion, tools)
                self._last_successful_full_verification_at = self._format_timestamp(
                    last_check_at
                )
                self._check_stop()
                if self._dependencies.monotonic() >= self._startup_deadline:
                    raise GuardFailure("ASSERTION_STARTUP_TIMEOUT")
                child = self._start_child(command)
                child_pid = child.pid
                child_returncode = self._monitor(child, assertion, tools, last_check_at)
                status = "COMPLETED"
                reason_code = "CHILD_EXITED"
                exit_code = child_returncode
            except GuardFailure as exc:
                reason_code = exc.reason_code
                probe_metadata = exc.probe_metadata
                if exc.reason_code == "GUARD_SIGNAL" and exc.signal_number:
                    exit_code = 128 + exc.signal_number
            except Exception as exc:  # noqa: BLE001
                del exc
            finally:
                for process in (child, assertion):
                    if process is None:
                        continue
                    try:
                        if not self._terminate_group(process):
                            cleanup_failed = True
                    except Exception:  # noqa: BLE001
                        cleanup_failed = True
                if child is not None and child_returncode is None:
                    child_returncode = child.poll()
                if cleanup_failed:
                    status = "FAILED"
                    reason_code = "CLEANUP_FAILED"
                    exit_code = GUARD_FAILURE_EXIT
                record = {
                    "event": "host_sleep_guard",
                    "status": status,
                    "reason_code": reason_code,
                    "assertion_pid": assertion_pid,
                    "child_pid": child_pid,
                    "child_returncode": child_returncode,
                    "max_check_gap_seconds": self._config.max_check_gap,
                    "started_at": started_at,
                    "finished_at": self._safe_timestamp(),
                    "last_successful_full_verification_at": (
                        self._last_successful_full_verification_at
                    ),
                    "probe_diagnostic": (
                        probe_metadata.as_record(
                            self._last_successful_full_verification_at
                        )
                        if probe_metadata is not None
                        else None
                    ),
                }
                self._emit(record)
        return exit_code

    def _safe_timestamp(self) -> str | None:
        try:
            return self._timestamp()
        except GuardFailure:
            return None

    @staticmethod
    def _format_timestamp(value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one explicit argv under a verified macOS sleep assertion."
    )
    parser.add_argument(
        "--max-check-gap",
        type=float,
        required=True,
        help="caller-supplied maximum UTC evidence gap in seconds",
    )
    parser.add_argument(
        "--probe-interval",
        type=float,
        default=5.0,
        help="seconds between host/assertion checks while the child runs",
    )
    parser.add_argument(
        "--probe-timeout",
        type=float,
        default=2.0,
        help="timeout for each bounded pmset/ioreg probe",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=8.0,
        help="finite wait for the owned assertion to become visible",
    )
    parser.add_argument(
        "--terminate-grace",
        type=float,
        default=2.0,
        help="bounded grace before SIGKILL to an owned child group",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        _parser().error("an explicit command argv is required after --")
    config = GuardConfig(
        max_check_gap=args.max_check_gap,
        probe_interval=args.probe_interval,
        probe_timeout=args.probe_timeout,
        startup_timeout=args.startup_timeout,
        terminate_grace=args.terminate_grace,
    )
    probe = HostProbe(probe_timeout=config.probe_timeout)
    return SleepAssertionGuard(config=config, probe=probe).run(command)


if __name__ == "__main__":
    raise SystemExit(main())
