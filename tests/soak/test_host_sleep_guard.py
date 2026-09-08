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
    SleepAssertionGuard,
    ToolPaths,
    _parser,
    parse_ac_power,
    parse_assertion_rows,
    parse_lid_open,
)

TOOLS = ToolPaths(
    caffeinate="/usr/bin/caffeinate",
    pmset="/usr/bin/pmset",
    ioreg="/usr/sbin/ioreg",
)
AC_POWER = "Now drawing from 'AC Power'\n"
OPEN_LID = '"AppleClamshellState" = No\n'
CLOSED_LID = '"AppleClamshellState" = Yes\n'
OWNED_ASSERTIONS = """
Assertion status system-wide:
   PreventUserIdleSystemSleep 1
Listed by owning process:
   pid 24974(caffeinate): [0x0000000000000001] 00:00:00 PreventUserIdleSystemSleep named: "caffeinate command-line tool"
   pid 24974(caffeinate): [0x0000000000000002] 00:00:00 PreventSystemSleep named: "caffeinate command-line tool"
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
            raise GuardFailure(self.environment_failure or "AC_LOST")
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
        "PreventSystemSleep", "PreventDiskIdleSystemSleep"
    )
    rows = parse_assertion_rows(missing)
    assert {row.assertion_type for row in rows} != REQUIRED_ASSERTION_TYPES


def test_malformed_and_timeout_probes_fail_closed() -> None:
    with pytest.raises(GuardFailure) as malformed:
        parse_assertion_rows("pid not-a-row")
    _raises_reason(malformed, "ASSERTION_UNVERIFIABLE")

    def timeout_runner(argv, timeout):
        del argv, timeout
        raise subprocess.TimeoutExpired("pmset", 0.1)

    probe = HostProbe(
        run_probe=timeout_runner,
        executable_lookup=lambda name: f"/usr/bin/{name}",
        probe_timeout=0.1,
    )
    with pytest.raises(GuardFailure) as timed_out:
        probe.verify_environment(TOOLS)
    _raises_reason(timed_out, "PROBE_TIMEOUT")


def test_power_and_lid_parsers_require_positive_host_state() -> None:
    assert parse_ac_power(AC_POWER) is True
    with pytest.raises(GuardFailure) as battery:
        parse_ac_power("Now drawing from 'Battery Power'\n")
    _raises_reason(battery, "ON_BATTERY")
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
        if argv[-1] == "batt":
            return subprocess.CompletedProcess(argv, 0, stdout=AC_POWER, stderr="")
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


@pytest.mark.parametrize(
    ("failure", "reason"),
    [("AC_LOST", "AC_LOST"), ("LID_CLOSED", "LID_CLOSED")],
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
    assert (100, signal.SIGTERM) in kill_calls
    assert (100, signal.SIGKILL) in kill_calls


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
        output = AC_POWER if argv[-1] == "batt" else OPEN_LID
        if argv[-1] == "assertions":
            output = OWNED_ASSERTIONS
        return subprocess.CompletedProcess(argv, 0, stdout=output)

    probe = HostProbe(run_probe=runner, probe_timeout=10)
    guard = SleepAssertionGuard(
        config=GuardConfig(max_check_gap=60, startup_timeout=2, probe_timeout=10),
        probe=probe,
        dependencies=GuardDependencies(monotonic=clock.monotonic),
        install_signal_handlers=False,
    )
    with pytest.raises(GuardFailure, match="ASSERTION_STARTUP_TIMEOUT"):
        guard._wait_for_assertion(_FakeProcess(24974), TOOLS)
    assert budgets == [2, 1.25, 0.5]


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
    assert guard._terminate_group(_FakeProcess(200, returncode=0))
    assert signals == [(200, signal.SIGTERM, 0), (200, signal.SIGKILL, 0.1)]


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
    assert not guard._terminate_group(_FakeProcess(200, returncode=0))
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
            assert cleaned is False
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)
