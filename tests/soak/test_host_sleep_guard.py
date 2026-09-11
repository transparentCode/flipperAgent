from __future__ import annotations

import math
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from scripts.host_sleep_guard import (
    GUARD_FAILURE_EXIT,
    REQUIRED_ASSERTION_TYPES,
    GuardConfig,
    GuardDependencies,
    GuardFailure,
    HostProbe,
    ProbeKind,
    ProbePhase,
    ProbeTimingStatus,
    SleepAssertionGuard,
    ToolPaths,
    _parser,
    parse_assertion_rows,
    parse_lid_open,
)

TOOLS = ToolPaths(
    caffeinate="/usr/bin/caffeinate",
    pmset="/usr/bin/pmset",
    ioreg="/usr/sbin/ioreg",
)
OPEN_LID = '"AppleClamshellState" = No\n'
CLOSED_LID = '"AppleClamshellState" = Yes\n'
OWNED_ASSERTIONS = """
Assertion status system-wide:
   PreventUserIdleSystemSleep 1
Listed by owning process:
   pid 24974(caffeinate): [0x0000000000000001] 00:00:00 PreventUserIdleSystemSleep named: "caffeinate command-line tool"
"""


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, duration: float) -> None:
        self.value += duration


class _FakeProcess:
    def __init__(
        self,
        pid: int,
        *,
        returncode: int | None = None,
        poll_values: list[int | None] | None = None,
        on_wait=None,
    ) -> None:
        self.pid = pid
        self.returncode = returncode
        self.poll_values = list(poll_values or [])
        self.on_wait = on_wait
        self.wait_calls = 0

    def poll(self) -> int | None:
        if self.poll_values:
            value = self.poll_values.pop(0)
            if value is not None:
                self.returncode = value
            return value
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        if self.on_wait is not None:
            self.on_wait(self)
            self.on_wait = None
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake-child", timeout)
        return self.returncode


class _FinalPollErrorProcess(_FakeProcess):
    def __init__(self, pid: int, *, returncode: int | None = None) -> None:
        super().__init__(pid, returncode=returncode)
        self.poll_count = 0

    def poll(self) -> int | None:
        self.poll_count += 1
        if self.poll_count >= 4:
            raise OSError("status detail must remain redacted")
        return super().poll()


class _PopenFactory:
    def __init__(self, assertion: _FakeProcess, child: _FakeProcess) -> None:
        self.assertion = assertion
        self.child = child
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, argv, **kwargs):
        command = list(argv)
        self.calls.append((command, dict(kwargs)))
        if command[0].endswith("caffeinate"):
            return self.assertion
        return self.child


class _GuardProbe:
    def __init__(
        self,
        *,
        environment_failure: str | None = None,
        fail_environment_after: int | None = None,
        assertion_missing: bool = False,
    ) -> None:
        self.environment_failure = environment_failure
        self.fail_environment_after = fail_environment_after
        self.assertion_missing = assertion_missing
        self.environment_calls = 0
        self.assertion_calls = 0

    def resolve_tools(self) -> ToolPaths:
        return TOOLS

    def verify_environment(
        self, tools: ToolPaths, *, runtime: bool = False, timeout=None
    ) -> None:
        del tools, runtime
        self.environment_calls += 1
        if self.fail_environment_after is not None and (
            self.environment_calls > self.fail_environment_after
        ):
            raise GuardFailure(self.environment_failure or "LID_CLOSED")
        if self.fail_environment_after is None and self.environment_failure is not None:
            raise GuardFailure(self.environment_failure)

    def verify_assertion(
        self, tools: ToolPaths, owner_pid: int, *, timeout=None
    ) -> None:
        del tools, owner_pid
        self.assertion_calls += 1
        if self.assertion_missing:
            raise GuardFailure("ASSERTION_MISSING")


def _guard(
    probe: _GuardProbe,
    factory: _PopenFactory,
    *,
    clock: _Clock | None = None,
    now=None,
    config: GuardConfig | None = None,
    stop_event: Event | None = None,
    evidence: list[dict] | None = None,
    kill_calls: list[tuple[int, int]] | None = None,
) -> SleepAssertionGuard:
    clock = clock or _Clock()
    if kill_calls is None:
        kill_calls = []
    processes = {
        factory.assertion.pid: factory.assertion,
        factory.child.pid: factory.child,
    }

    def killpg(pid: int, signum: int) -> None:
        kill_calls.append((pid, signum))
        process = processes[pid]
        process.returncode = -signum

    deps = GuardDependencies(
        popen=factory,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        now=now or (lambda: datetime(2026, 9, 6, tzinfo=UTC)),
        killpg=killpg,
        group_exists=lambda pid: processes[pid].returncode is None,
    )
    return SleepAssertionGuard(
        config=config
        or GuardConfig(
            max_check_gap=60.0,
            probe_interval=1.0,
            probe_timeout=0.1,
            startup_timeout=2.0,
            terminate_grace=0.1,
        ),
        probe=probe,
        dependencies=deps,
        evidence_sink=(evidence.append if evidence is not None else None),
        stop_event=stop_event,
        install_signal_handlers=False,
    )


def _raises_reason(exc_info, reason_code: str) -> None:
    assert isinstance(exc_info.value, GuardFailure)
    assert exc_info.value.reason_code == reason_code


def test_parse_owned_assertions_requires_exact_caffeinate_pid() -> None:
    rows = parse_assertion_rows(OWNED_ASSERTIONS)
    assert {row.assertion_type for row in rows} == REQUIRED_ASSERTION_TYPES
    assert all(row.pid == 24974 for row in rows)
    assert all(row.process_name == "caffeinate" for row in rows)


def test_wrong_owner_and_missing_assertion_do_not_pass() -> None:
    wrong_owner = OWNED_ASSERTIONS.replace("24974", "24973")
    rows = parse_assertion_rows(wrong_owner)
    owned = {row.assertion_type for row in rows if row.pid == 24974}
    assert not owned

    missing = OWNED_ASSERTIONS.replace(
        "PreventUserIdleSystemSleep", "PreventDiskIdleSystemSleep"
    )
    rows = parse_assertion_rows(missing)
    assert {row.assertion_type for row in rows} != REQUIRED_ASSERTION_TYPES


def test_malformed_and_timeout_probes_fail_closed() -> None:
    with pytest.raises(GuardFailure) as malformed:
        parse_assertion_rows("pid not-a-row")
    _raises_reason(malformed, "ASSERTION_UNVERIFIABLE")

    def timeout_runner(argv, timeout):
        del argv, timeout
        raise subprocess.TimeoutExpired("ioreg", 0.1)

    probe = HostProbe(
        run_probe=timeout_runner,
        executable_lookup=lambda name: f"/usr/bin/{name}",
        probe_timeout=0.1,
    )
    with pytest.raises(GuardFailure) as timed_out:
        probe.verify_environment(TOOLS)
    _raises_reason(timed_out, "PROBE_TIMEOUT")


@pytest.mark.parametrize(
    ("target", "probe_kind", "operation"),
    [
        (
            (TOOLS.ioreg, "-r", "-k", "AppleClamshellState", "-d", "1"),
            ProbeKind.LID_STATE,
            "environment",
        ),
        ((TOOLS.pmset, "-g", "assertions"), ProbeKind.ASSERTIONS, "assertion"),
    ],
)
def test_timeout_diagnostics_identify_each_host_probe(
    target: tuple[str, ...], probe_kind: ProbeKind, operation: str
) -> None:
    clock = _Clock()
    secret = "SENSITIVE_PROBE_OUTPUT"

    def runner(argv, timeout):
        clock.sleep(0.25)
        if tuple(argv) == target:
            raise subprocess.TimeoutExpired(
                [argv[0], secret], timeout, output=secret, stderr=secret
            )
        if argv[0] == TOOLS.ioreg:
            output = OPEN_LID
        else:
            output = OWNED_ASSERTIONS
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

    probe = HostProbe(
        run_probe=runner,
        executable_lookup=lambda name: getattr(TOOLS, name),
        probe_timeout=0.1,
        monotonic=clock.monotonic,
    )
    tools = probe.resolve_tools()

    with pytest.raises(GuardFailure) as failure:
        if operation == "environment":
            probe.verify_environment(tools)
        else:
            probe.verify_assertion(tools, 24974)

    assert failure.value.reason_code == "PROBE_TIMEOUT"
    metadata = failure.value.probe_metadata
    assert metadata is not None
    assert metadata.kind is probe_kind
    assert metadata.phase is ProbePhase.INITIAL
    assert metadata.timing_status is ProbeTimingStatus.AVAILABLE
    assert metadata.elapsed_monotonic_seconds is not None
    assert math.isfinite(metadata.elapsed_monotonic_seconds)
    assert metadata.requested_timeout_seconds == 0.1
    record = metadata.as_record(None)
    assert set(record) == {
        "probe_kind",
        "phase",
        "requested_timeout_seconds",
        "elapsed_monotonic_seconds",
        "timing_status",
        "last_successful_full_verification_at",
    }
    assert "pmset" not in str(record)
    assert "ioreg" not in str(record)
    assert secret not in str(record)
    assert secret not in str(failure.value)


def test_probe_failure_diagnostics_redact_returned_streams() -> None:
    stdout_secret = "SENSITIVE_STDOUT"
    stderr_secret = "SENSITIVE_STDERR"

    def runner(argv, timeout):
        del timeout
        return subprocess.CompletedProcess(
            argv, 1, stdout=stdout_secret, stderr=stderr_secret
        )

    probe = HostProbe(
        run_probe=runner,
        executable_lookup=lambda name: getattr(TOOLS, name),
        probe_timeout=0.1,
    )

    with pytest.raises(GuardFailure) as failure:
        probe.verify_environment(TOOLS)

    assert failure.value.reason_code == "PROBE_FAILED"
    metadata = failure.value.probe_metadata
    assert metadata is not None
    record = metadata.as_record(None)
    assert stdout_secret not in str(record)
    assert stderr_secret not in str(record)
    assert stdout_secret not in str(failure.value)
    assert stderr_secret not in str(failure.value)


def test_host_probe_keeps_only_latest_metadata_after_many_successes() -> None:
    clock = _Clock()
    probe_calls = 0

    def runner(argv, timeout):
        nonlocal probe_calls
        del timeout
        probe_calls += 1
        clock.sleep(0.001)
        return subprocess.CompletedProcess(argv, 0, stdout=OWNED_ASSERTIONS, stderr="")

    probe = HostProbe(
        run_probe=runner,
        executable_lookup=lambda name: getattr(TOOLS, name),
        probe_timeout=0.1,
        monotonic=clock.monotonic,
    )
    tools = probe.resolve_tools()

    probe.verify_assertion(tools, 24974)
    first = probe._last_probe_metadata
    for _ in range(999):
        probe.verify_assertion(tools, 24974)

    latest = probe._last_probe_metadata
    assert probe_calls == 1000
    assert first is not None
    assert latest is not None
    assert latest is not first
    assert latest.kind is ProbeKind.ASSERTIONS
    assert latest.timing_status is ProbeTimingStatus.AVAILABLE
    assert latest.elapsed_monotonic_seconds is not None
    assert math.isclose(latest.elapsed_monotonic_seconds, 0.001)
    record = latest.as_record(None)
    assert set(record) == {
        "probe_kind",
        "phase",
        "requested_timeout_seconds",
        "elapsed_monotonic_seconds",
        "timing_status",
        "last_successful_full_verification_at",
    }
    assert len(record) == 6
    assert not any("history" in name for name in vars(probe))
    assert not any(
        isinstance(value, (list, dict, set, tuple))
        for name, value in vars(probe).items()
        if "probe" in name.lower()
    )


@pytest.mark.parametrize(
    "readings",
    [
        (1.0, math.nan),
        (1.0, math.inf),
        (2.0, 1.0),
        (-1.0, 0.0),
    ],
)
def test_invalid_monotonic_probe_timing_is_null_and_explicit(
    readings: tuple[float, float],
) -> None:
    clock = iter(readings)

    def runner(argv, timeout):
        raise subprocess.TimeoutExpired(argv[0], timeout)

    probe = HostProbe(
        run_probe=runner,
        executable_lookup=lambda name: getattr(TOOLS, name),
        probe_timeout=0.1,
        monotonic=lambda: next(clock),
    )

    with pytest.raises(GuardFailure) as failure:
        probe.verify_environment(TOOLS)

    assert failure.value.reason_code == "PROBE_TIMEOUT"
    metadata = failure.value.probe_metadata
    assert metadata is not None
    assert metadata.elapsed_monotonic_seconds is None
    assert metadata.timing_status is ProbeTimingStatus.UNAVAILABLE
    record = metadata.as_record(None)
    assert record["elapsed_monotonic_seconds"] is None
    assert record["timing_status"] == "UNAVAILABLE"


def test_initial_monotonic_failure_preserves_original_probe_reason() -> None:
    def broken_monotonic() -> float:
        raise RuntimeError("clock details must not escape")

    def timeout_runner(argv, timeout):
        raise subprocess.TimeoutExpired(argv[0], timeout)

    probe = HostProbe(
        run_probe=timeout_runner,
        executable_lookup=lambda name: getattr(TOOLS, name),
        probe_timeout=0.1,
        monotonic=broken_monotonic,
    )
    with pytest.raises(GuardFailure) as failure:
        probe.verify_environment(TOOLS)

    assert failure.value.reason_code == "PROBE_TIMEOUT"
    assert failure.value.probe_metadata is not None
    assert failure.value.probe_metadata.timing_status is ProbeTimingStatus.UNAVAILABLE


def test_startup_probe_timeout_records_startup_phase_and_cleans_assertion() -> None:
    clock = _Clock()
    lid_calls = 0

    def runner(argv, timeout):
        nonlocal lid_calls
        clock.sleep(0.01)
        if argv[0] == TOOLS.ioreg:
            lid_calls += 1
            if lid_calls == 2:
                raise subprocess.TimeoutExpired(argv[0], timeout)
            return subprocess.CompletedProcess(argv, 0, stdout=OPEN_LID, stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout=OWNED_ASSERTIONS, stderr="")

    probe = HostProbe(
        run_probe=runner,
        executable_lookup=lambda name: getattr(TOOLS, name),
        probe_timeout=0.1,
        monotonic=clock.monotonic,
    )
    evidence: list[dict] = []
    kill_calls: list[tuple[int, int]] = []
    assertion = _FakeProcess(100)
    child = _FakeProcess(200)
    factory = _PopenFactory(assertion, child)
    guard = _guard(
        probe,
        factory,
        clock=clock,
        evidence=evidence,
        kill_calls=kill_calls,
    )

    result = guard.run(("python", "-c", "secret"))

    assert result == GUARD_FAILURE_EXIT
    assert evidence[0]["reason_code"] == "PROBE_TIMEOUT"
    diagnostic = evidence[0]["probe_diagnostic"]
    assert diagnostic["probe_kind"] == "LID"
    assert diagnostic["phase"] == "STARTUP"
    assert diagnostic["timing_status"] == "AVAILABLE"
    assert math.isfinite(diagnostic["elapsed_monotonic_seconds"])
    assert len(factory.calls) == 1
    assert (100, signal.SIGTERM) in kill_calls
    assert "secret" not in str(evidence[0])


def test_runtime_probe_timeout_preserves_last_successful_full_timestamp() -> None:
    clock = _Clock()
    assertion_calls = 0
    owned_assertions = OWNED_ASSERTIONS.replace("24974", "100")

    def runner(argv, timeout):
        nonlocal assertion_calls
        clock.sleep(0.01)
        if argv[0] == TOOLS.ioreg:
            return subprocess.CompletedProcess(argv, 0, stdout=OPEN_LID, stderr="")
        assertion_calls += 1
        if assertion_calls == 2:
            raise subprocess.TimeoutExpired(argv[0], timeout)
        return subprocess.CompletedProcess(argv, 0, stdout=owned_assertions, stderr="")

    probe = HostProbe(
        run_probe=runner,
        executable_lookup=lambda name: getattr(TOOLS, name),
        probe_timeout=0.1,
        monotonic=clock.monotonic,
    )
    evidence: list[dict] = []
    kill_calls: list[tuple[int, int]] = []
    assertion = _FakeProcess(100)
    child = _FakeProcess(200)
    factory = _PopenFactory(assertion, child)
    guard = _guard(
        probe,
        factory,
        clock=clock,
        evidence=evidence,
        kill_calls=kill_calls,
    )

    result = guard.run(("python", "-c", "secret"))

    assert result == GUARD_FAILURE_EXIT
    assert evidence[0]["reason_code"] == "PROBE_TIMEOUT"
    diagnostic = evidence[0]["probe_diagnostic"]
    assert diagnostic["probe_kind"] == "ASSERTIONS"
    assert diagnostic["phase"] == "RUNTIME"
    assert diagnostic["last_successful_full_verification_at"] == (
        "2026-09-06T00:00:00Z"
    )
    assert evidence[0]["last_successful_full_verification_at"] == (
        "2026-09-06T00:00:00Z"
    )
    assert (200, signal.SIGTERM) in kill_calls
    assert (100, signal.SIGTERM) in kill_calls


def test_lid_parser_requires_positive_host_state() -> None:
    assert parse_lid_open(OPEN_LID) is True
    assert parse_lid_open(CLOSED_LID) is False


def test_signal_handler_signature_and_cli_defaults_are_concrete() -> None:
    stop_event = Event()
    guard = SleepAssertionGuard(
        config=GuardConfig(max_check_gap=60.0),
        probe=_GuardProbe(),
        stop_event=stop_event,
        install_signal_handlers=False,
    )
    guard.request_stop(signal.SIGTERM, None)
    assert stop_event.is_set()

    args = _parser().parse_args(["--max-check-gap", "60", "--", "python"])
    assert args.max_check_gap == 60.0
    assert args.probe_interval == 5.0
    assert args.probe_timeout == 2.0
    assert args.startup_timeout == 8.0
    assert args.terminate_grace == 2.0


@pytest.mark.parametrize(
    "field_name",
    (
        "max_check_gap",
        "probe_interval",
        "probe_timeout",
        "startup_timeout",
        "terminate_grace",
    ),
)
@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf))
def test_guard_rejects_nonfinite_timing(field_name: str, value: float) -> None:
    values = {"max_check_gap": 60.0}
    values[field_name] = value
    with pytest.raises(ValueError):
        GuardConfig(**values)


def test_probe_rejects_nonfinite_timeout() -> None:
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            HostProbe(probe_timeout=value)


def test_host_probe_verifies_required_owner_rows() -> None:
    def runner(argv, timeout):
        del timeout
        if argv[-1] == "assertions":
            return subprocess.CompletedProcess(
                argv, 0, stdout=OWNED_ASSERTIONS, stderr=""
            )
        return subprocess.CompletedProcess(argv, 0, stdout=OPEN_LID, stderr="")

    probe = HostProbe(
        run_probe=runner,
        executable_lookup=lambda name: f"/usr/bin/{name}",
        probe_timeout=0.1,
    )
    tools = probe.resolve_tools()
    probe.verify_environment(tools)
    probe.verify_assertion(tools, 24974)

    with pytest.raises(GuardFailure) as wrong_owner:
        probe.verify_assertion(tools, 24973)
    _raises_reason(wrong_owner, "ASSERTION_MISSING")


def test_start_and_runtime_ignore_power_source_changes_without_batt_query() -> None:
    power_sources = iter(("Battery Power", "AC Power", "Battery Power"))
    observed_sources: list[str] = []
    commands: list[tuple[str, ...]] = []
    owned_assertions = OWNED_ASSERTIONS.replace("24974", "100")

    def runner(argv, timeout):
        del timeout
        command = tuple(argv)
        commands.append(command)
        if argv[0] == TOOLS.ioreg:
            observed_sources.append(next(power_sources))
            return subprocess.CompletedProcess(argv, 0, stdout=OPEN_LID, stderr="")
        assert argv[-1] == "assertions"
        return subprocess.CompletedProcess(argv, 0, stdout=owned_assertions, stderr="")

    probe = HostProbe(
        run_probe=runner,
        executable_lookup=lambda name: getattr(TOOLS, name),
        probe_timeout=0.1,
    )
    assertion = _FakeProcess(100)
    child = _FakeProcess(200, returncode=0)
    factory = _PopenFactory(assertion, child)
    evidence: list[dict] = []
    guard = _guard(probe, factory, evidence=evidence)

    assert guard.run(("python", "-c", "harmless")) == 0
    assert evidence[0]["status"] == "COMPLETED"
    assert observed_sources == ["Battery Power", "AC Power", "Battery Power"]
    assert len(commands) == 5
    assert all(command[0] in {TOOLS.ioreg, TOOLS.pmset} for command in commands)
    assert all("batt" not in command for command in commands)
    assert all(command[-1] != "batt" for command in commands)


def test_missing_tool_emits_failure_without_starting_any_process() -> None:
    evidence: list[dict] = []
    assertion = _FakeProcess(100)
    child = _FakeProcess(200, returncode=0)
    factory = _PopenFactory(assertion, child)
    probe = HostProbe(executable_lookup=lambda name: None)
    guard = SleepAssertionGuard(
        config=GuardConfig(max_check_gap=60.0),
        probe=probe,
        evidence_sink=evidence.append,
        install_signal_handlers=False,
    )

    result = guard.run(("python", "-c", "secret"))

    assert result == GUARD_FAILURE_EXIT
    assert evidence[0]["reason_code"] == "MISSING_TOOL"
    assert not factory.calls


def test_no_child_starts_before_assertion_is_verified() -> None:
    evidence: list[dict] = []
    clock = _Clock()
    assertion = _FakeProcess(100)
    child = _FakeProcess(200, returncode=0)
    factory = _PopenFactory(assertion, child)
    guard = _guard(
        _GuardProbe(assertion_missing=True),
        factory,
        clock=clock,
        config=GuardConfig(
            max_check_gap=60.0,
            probe_interval=1.0,
            probe_timeout=0.1,
            startup_timeout=2.0,
            terminate_grace=0.1,
        ),
        evidence=evidence,
    )

    result = guard.run(("python", "-c", "secret"))

    assert result == GUARD_FAILURE_EXIT
    assert evidence[0]["reason_code"] == "ASSERTION_STARTUP_TIMEOUT"
    assert len(factory.calls) == 1
    assert factory.calls[0][0][0].endswith("caffeinate")
    assert factory.calls[0][0][1:3] == ["-i", "-w"]


def test_child_exit_preserves_code_and_cleans_only_owned_assertion() -> None:
    evidence: list[dict] = []
    kill_calls: list[tuple[int, int]] = []
    assertion = _FakeProcess(100)
    child = _FakeProcess(200, returncode=23)
    factory = _PopenFactory(assertion, child)
    guard = _guard(
        _GuardProbe(),
        factory,
        evidence=evidence,
        kill_calls=kill_calls,
    )

    result = guard.run(("python", "-c", "secret"))

    assert result == 23
    assert evidence[0]["status"] == "COMPLETED"
    assert evidence[0]["child_returncode"] == 23
    assert kill_calls == [(100, signal.SIGTERM)]
    assert "secret" not in str(evidence[0])
    assert factory.calls[1][1]["shell"] is False


def test_final_child_status_read_failure_emits_redacted_cleanup_record() -> None:
    evidence: list[dict] = []
    assertion = _FakeProcess(100)
    child = _FinalPollErrorProcess(200)
    factory = _PopenFactory(assertion, child)
    guard = _guard(
        _GuardProbe(fail_environment_after=2, environment_failure="LID_CLOSED"),
        factory,
        evidence=evidence,
    )

    result = guard.run(("python", "-c", "secret"))

    assert result == GUARD_FAILURE_EXIT
    record = evidence[0]
    assert record["status"] == "FAILED"
    assert record["reason_code"] == "CLEANUP_FAILED"
    assert record["primary_reason_code"] == "LID_CLOSED"
    assert record["child_returncode"] is None
    child_cleanup = record["cleanup_results"]["child"]
    assert child_cleanup["success"] is False
    assert child_cleanup["failure_code"] == "CHILD_STATUS_UNVERIFIED"
    assert "status detail must remain redacted" not in str(record)


def test_successful_probe_cycles_emit_one_bounded_terminal_event() -> None:
    evidence: list[dict] = []
    assertion = _FakeProcess(100)
    child = _FakeProcess(200, poll_values=[None, None, None, None, 0])
    factory = _PopenFactory(assertion, child)
    probe = _GuardProbe()
    guard = _guard(probe, factory, evidence=evidence)

    result = guard.run(("python", "-c", "harmless"))

    assert result == 0
    assert probe.environment_calls == 5
    assert probe.assertion_calls == 4
    assert len(evidence) == 1
    record = evidence[0]
    expected_fields = {
        "event",
        "status",
        "reason_code",
        "primary_reason_code",
        "assertion_pid",
        "child_pid",
        "child_returncode",
        "max_check_gap_seconds",
        "started_at",
        "finished_at",
        "last_successful_full_verification_at",
        "probe_diagnostic",
        "cleanup_results",
    }
    assert set(record) == expected_fields
    assert len(record) == len(expected_fields)
    assert record["status"] == "COMPLETED"
    assert record["reason_code"] == "CHILD_EXITED"
    assert record["primary_reason_code"] == "CHILD_EXITED"
    assert record["probe_diagnostic"] is None
    assert set(record["cleanup_results"]) == {"child", "assertion"}
    assert record["cleanup_results"]["child"]["success"] is True
    assert record["cleanup_results"]["assertion"]["success"] is True


@pytest.mark.parametrize(
    ("failure", "reason"),
    [("LID_CLOSED", "LID_CLOSED")],
)
def test_host_failure_during_child_terminates_only_child_group(
    failure: str, reason: str
) -> None:
    evidence: list[dict] = []
    kill_calls: list[tuple[int, int]] = []
    assertion = _FakeProcess(100)
    child = _FakeProcess(200)
    factory = _PopenFactory(assertion, child)
    guard = _guard(
        _GuardProbe(fail_environment_after=2, environment_failure=failure),
        factory,
        evidence=evidence,
        kill_calls=kill_calls,
    )

    result = guard.run(("python", "-c", "secret"))

    assert result == GUARD_FAILURE_EXIT
    assert evidence[0]["reason_code"] == reason
    assert (200, signal.SIGTERM) in kill_calls
    assert (100, signal.SIGTERM) in kill_calls


def test_assertion_exit_fails_child_run() -> None:
    evidence: list[dict] = []
    assertion = _FakeProcess(100, poll_values=[None, 9])
    child = _FakeProcess(200)
    factory = _PopenFactory(assertion, child)
    kill_calls: list[tuple[int, int]] = []
    guard = _guard(
        _GuardProbe(),
        factory,
        evidence=evidence,
        kill_calls=kill_calls,
    )

    result = guard.run(("python", "-c", "secret"))

    assert result == GUARD_FAILURE_EXIT
    assert evidence[0]["reason_code"] == "ASSERTION_EXITED"
    assert (200, signal.SIGTERM) in kill_calls


def test_sigterm_request_reaps_owned_child_and_assertion() -> None:
    evidence: list[dict] = []
    kill_calls: list[tuple[int, int]] = []
    holder: dict[str, SleepAssertionGuard] = {}
    assertion = _FakeProcess(100)

    def request_stop(_process) -> None:
        holder["guard"].request_stop(signal.SIGTERM)

    child = _FakeProcess(200, on_wait=request_stop)
    factory = _PopenFactory(assertion, child)
    guard = _guard(
        _GuardProbe(),
        factory,
        evidence=evidence,
        kill_calls=kill_calls,
    )
    holder["guard"] = guard

    result = guard.run(("python", "-c", "secret"))

    assert result == 128 + signal.SIGTERM
    assert evidence[0]["reason_code"] == "GUARD_SIGNAL"
    assert (200, signal.SIGTERM) in kill_calls
    assert (100, signal.SIGTERM) in kill_calls
    assert child.poll() is not None
    assert assertion.poll() is not None


@pytest.mark.parametrize(
    ("wall_delta", "reason"),
    [
        (timedelta(seconds=61), "CHECK_GAP_EXCEEDED"),
        (timedelta(seconds=-1), "CLOCK_BACKWARDS"),
    ],
)
def test_utc_continuity_rejects_gap_or_backward_clock(
    wall_delta: timedelta, reason: str
) -> None:
    evidence: list[dict] = []
    wall_clock = [datetime(2026, 9, 6, tzinfo=UTC)]
    assertion = _FakeProcess(100)

    def advance_wall_clock(_process) -> None:
        wall_clock[0] += wall_delta

    child = _FakeProcess(200, on_wait=advance_wall_clock)
    factory = _PopenFactory(assertion, child)
    guard = _guard(
        _GuardProbe(),
        factory,
        now=lambda: wall_clock[0],
        evidence=evidence,
    )

    result = guard.run(("python", "-c", "secret"))

    assert result == GUARD_FAILURE_EXIT
    assert evidence[0]["reason_code"] == reason
    assert evidence[0]["status"] == "FAILED"


def test_naive_injected_clock_is_not_treated_as_utc() -> None:
    evidence: list[dict] = []
    assertion = _FakeProcess(100)
    child = _FakeProcess(200, returncode=0)
    factory = _PopenFactory(assertion, child)
    guard = _guard(
        _GuardProbe(),
        factory,
        now=lambda: datetime(2026, 9, 6),  # noqa: DTZ001
        evidence=evidence,
    )

    result = guard.run(("python", "-c", "secret"))

    assert result == GUARD_FAILURE_EXIT
    assert evidence[0]["reason_code"] == "CLOCK_UNVERIFIABLE"
    assert not factory.calls


def test_unreaped_owned_process_is_cleanup_failure_not_completed() -> None:
    evidence: list[dict] = []
    kill_calls: list[tuple[int, int]] = []
    assertion = _FakeProcess(100)
    child = _FakeProcess(200, returncode=0)
    factory = _PopenFactory(assertion, child)
    clock = _Clock()

    def failed_killpg(pid: int, signum: int) -> None:
        kill_calls.append((pid, signum))

    dependencies = GuardDependencies(
        popen=factory,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        now=lambda: datetime(2026, 9, 6, tzinfo=UTC),
        killpg=failed_killpg,
        group_exists=lambda pid: pid == assertion.pid,
    )
    guard = SleepAssertionGuard(
        config=GuardConfig(max_check_gap=60.0, terminate_grace=0.1),
        probe=_GuardProbe(),
        dependencies=dependencies,
        evidence_sink=evidence.append,
        install_signal_handlers=False,
    )

    result = guard.run(("python", "-c", "secret"))

    assert result == GUARD_FAILURE_EXIT
    assert evidence[0]["status"] == "FAILED"
    assert evidence[0]["reason_code"] == "CLEANUP_FAILED"
    assert evidence[0]["primary_reason_code"] == "CHILD_EXITED"
    assert evidence[0]["cleanup_results"]["child"]["success"] is True
    assertion_cleanup = evidence[0]["cleanup_results"]["assertion"]
    assert assertion_cleanup["success"] is False
    assert assertion_cleanup["group_state"] == "STILL_ADDRESSABLE"
    assert assertion_cleanup["failure_code"] == "STILL_ADDRESSABLE"
    assert evidence[0]["last_successful_full_verification_at"] == (
        "2026-09-06T00:00:00Z"
    )
    assert (100, signal.SIGTERM) in kill_calls
    assert (100, signal.SIGKILL) in kill_calls


def test_cleanup_failure_preserves_primary_reason_and_each_target_result() -> None:
    evidence: list[dict] = []
    assertion = _FakeProcess(100)
    child = _FakeProcess(200)
    factory = _PopenFactory(assertion, child)
    clock = _Clock()
    dependencies = GuardDependencies(
        popen=factory,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        now=lambda: datetime(2026, 9, 6, tzinfo=UTC),
        killpg=lambda _pid, _signum: None,
        group_exists=lambda _pid: True,
    )
    guard = SleepAssertionGuard(
        config=GuardConfig(max_check_gap=60.0, terminate_grace=0.1),
        probe=_GuardProbe(
            fail_environment_after=2,
            environment_failure="LID_CLOSED",
        ),
        dependencies=dependencies,
        evidence_sink=evidence.append,
        install_signal_handlers=False,
    )

    result = guard.run(("python", "-c", "secret"))

    assert result == GUARD_FAILURE_EXIT
    record = evidence[0]
    assert record["reason_code"] == "CLEANUP_FAILED"
    assert record["primary_reason_code"] == "LID_CLOSED"
    for target in ("child", "assertion"):
        cleanup = record["cleanup_results"][target]
        assert cleanup["success"] is False
        assert cleanup["leader_reaped"] is False
        assert cleanup["group_state"] == "STILL_ADDRESSABLE"
        assert cleanup["failure_code"] == "STILL_ADDRESSABLE"
    assert "secret" not in str(record)


@pytest.mark.parametrize("elapsed", [2.0, 2.1])
def test_successful_assertion_at_or_after_deadline_never_starts_child(elapsed):
    clock = _Clock()

    class SlowProbe(_GuardProbe):
        def verify_assertion(self, tools, owner_pid, *, timeout=None):
            clock.sleep(elapsed)

    factory = _PopenFactory(_FakeProcess(100), _FakeProcess(200))
    evidence = []
    guard = _guard(SlowProbe(), factory, clock=clock, evidence=evidence)
    assert guard.run(("unused",)) == GUARD_FAILURE_EXIT
    assert len(factory.calls) == 1
    assert evidence[0]["reason_code"] == "ASSERTION_STARTUP_TIMEOUT"


def test_each_host_subprocess_receives_remaining_startup_budget():
    clock = _Clock()
    budgets = []

    def runner(argv, timeout):
        budgets.append(timeout)
        clock.sleep(0.75)
        output = OWNED_ASSERTIONS if argv[-1] == "assertions" else OPEN_LID
        return subprocess.CompletedProcess(argv, 0, stdout=output)

    probe = HostProbe(run_probe=runner, probe_timeout=10)
    guard = SleepAssertionGuard(
        config=GuardConfig(max_check_gap=60, startup_timeout=2, probe_timeout=10),
        probe=probe,
        dependencies=GuardDependencies(monotonic=clock.monotonic),
        install_signal_handlers=False,
    )
    guard._wait_for_assertion(_FakeProcess(24974), TOOLS)
    assert budgets == [2, 1.25]


def test_exited_leader_still_gets_full_group_graces():
    clock = _Clock()
    signals = []
    alive = [True]

    def kill(pgid, signum):
        signals.append((pgid, signum, clock.value))
        if signum == signal.SIGKILL:
            alive[0] = False

    guard = SleepAssertionGuard(
        config=GuardConfig(max_check_gap=60, terminate_grace=0.1),
        dependencies=GuardDependencies(
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            killpg=kill,
            group_exists=lambda pid: alive[0],
        ),
        install_signal_handlers=False,
    )
    result = guard._terminate_group(_FakeProcess(200, returncode=0))
    assert result.success is True
    assert result.leader_reaped is True
    assert result.group_state == "ABSENT"
    assert signals == [(200, signal.SIGTERM, 0), (200, signal.SIGKILL, 0.1)]


def test_absent_group_without_reaped_leader_is_cleanup_failure():
    clock = _Clock()
    guard = SleepAssertionGuard(
        config=GuardConfig(max_check_gap=60, terminate_grace=0.1),
        dependencies=GuardDependencies(
            monotonic=clock.monotonic,
            group_exists=lambda _pid: False,
        ),
        install_signal_handlers=False,
    )

    result = guard._terminate_group(_FakeProcess(200))

    assert result.success is False
    assert result.leader_reaped is False
    assert result.group_state == "ABSENT"
    assert result.failure_code == "LEADER_UNREAPED"


@pytest.mark.parametrize("state", [None, "unknown"])
def test_uncertain_group_probe_never_signals(state):
    signals = []

    def probe(pid):
        if state is None:
            raise PermissionError()
        return state

    guard = SleepAssertionGuard(
        config=GuardConfig(max_check_gap=60),
        dependencies=GuardDependencies(
            group_exists=probe, killpg=lambda *args: signals.append(args)
        ),
        install_signal_handlers=False,
    )
    result = guard._terminate_group(_FakeProcess(200, returncode=0))
    assert result.success is False
    assert result.group_state == "UNKNOWN"
    assert result.failure_code == "UNKNOWN_GROUP_STATE"
    assert signals == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")
@pytest.mark.parametrize("leader_exits", [True, False])
def test_real_group_cleanup_kills_term_ignoring_descendant(tmp_path, leader_exits):
    ready = tmp_path / "ready"
    code = """
import os, signal, sys, time
pid = os.fork()
if pid == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with open(sys.argv[1], 'w') as f:
        f.write(str(os.getpid()))
    while True: time.sleep(1)
while not os.path.exists(sys.argv[1]): time.sleep(.01)
if sys.argv[2] == 'True': sys.exit(0)
while True: time.sleep(1)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(ready), str(leader_exits)],
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        if leader_exits:
            process.wait(timeout=3)
        guard = SleepAssertionGuard(
            config=GuardConfig(max_check_gap=60, terminate_grace=0.5),
            install_signal_handlers=False,
        )
        cleaned = guard._terminate_group(process)
        assert process.poll() is not None
        # Orphan zombies may remain addressable until the host reaps them;
        # in that case cleanup must report failure, never fabricated reaping.
        child_pid = int(ready.read_text())
        result = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(child_pid)],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        assert not result.stdout.strip() or result.stdout.strip().startswith("Z")
        if result.stdout.strip():
            assert cleaned.success is False
            assert cleaned.group_state == "STILL_ADDRESSABLE"
        else:
            assert cleaned.success is True
            assert cleaned.leader_reaped is True
            assert cleaned.group_state == "ABSENT"
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)
