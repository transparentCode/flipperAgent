from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

import pytest

import apps.ingestion_app.transport.ownership as ownership_module
from apps.ingestion_app.transport.ownership import (
    OwnedAsyncCall,
    OwnedBlockingCall,
    OwnedCallTimeout,
    OwnedOperationTracker,
    OwnershipAccountingError,
    wait_for_owned_call,
)


class _TrackerCall:
    def __init__(self) -> None:
        self.finished = False


async def _wait_until(predicate: Callable[[], bool], timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            pytest.fail("condition did not become true")
        await asyncio.sleep(min(0.01, remaining))


@pytest.mark.asyncio
async def test_owned_blocking_call_success_and_failure_callback_once() -> None:
    callback_calls: list[OwnedBlockingCall] = []
    success = OwnedBlockingCall(
        loop=asyncio.get_running_loop(),
        operation=lambda: "ok",
        name="test-owned-blocking-success",
        finished_callback=callback_calls.append,
    )
    success.start()
    assert await success.wait(1) == "ok"
    assert success.adopt() is True
    await _wait_until(lambda: success.finished)
    assert callback_calls == [success]

    error = ValueError("expected failure")
    failure = OwnedBlockingCall(
        loop=asyncio.get_running_loop(),
        operation=lambda: (_ for _ in ()).throw(error),
        name="test-owned-blocking-failure",
        finished_callback=callback_calls.append,
    )
    failure.start()
    with pytest.raises(ValueError, match="expected failure"):
        await failure.wait(1)
    assert failure.adopt() is True
    await _wait_until(lambda: failure.finished)
    assert callback_calls == [success, failure]


@pytest.mark.asyncio
async def test_owned_async_call_success_and_failure_callback_once() -> None:
    callback_calls: list[OwnedAsyncCall] = []

    async def success_operation() -> str:
        return "ok"

    success = OwnedAsyncCall(
        loop=asyncio.get_running_loop(),
        operation=success_operation,
        name="test-owned-async-success",
        finished_callback=callback_calls.append,
    )
    success.start()
    assert await success.wait(1) == "ok"
    assert success.adopt() is True
    await _wait_until(lambda: success.finished)

    error = ValueError("expected async failure")

    async def failure_operation() -> object:
        raise error

    failure = OwnedAsyncCall(
        loop=asyncio.get_running_loop(),
        operation=failure_operation,
        name="test-owned-async-failure",
        finished_callback=callback_calls.append,
    )
    failure.start()
    with pytest.raises(ValueError, match="expected async failure"):
        await failure.wait(1)
    assert failure.adopt() is True
    await _wait_until(lambda: failure.finished)
    assert callback_calls == [success, failure]


@pytest.mark.asyncio
async def test_owned_blocking_timeout_retains_operation_until_real_completion() -> None:
    started = threading.Event()
    release = threading.Event()
    cleaned: list[object] = []
    callback_calls: list[OwnedBlockingCall] = []

    def operation() -> str:
        started.set()
        release.wait(1)
        return "late-result"

    call = OwnedBlockingCall(
        loop=asyncio.get_running_loop(),
        operation=operation,
        name="test-owned-blocking-timeout",
        abandoned_cleanup=cleaned.append,
        finished_callback=callback_calls.append,
    )
    call.start()
    assert await asyncio.to_thread(started.wait, 1)
    with pytest.raises(OwnedCallTimeout):
        await call.wait(0.01)
    assert call.operation_finished is False
    assert call.finished is False

    call.abandon()
    release.set()
    await _wait_until(lambda: call.finished)
    assert cleaned == ["late-result"]
    assert callback_calls == [call]


@pytest.mark.asyncio
async def test_owned_blocking_wait_cancellation_does_not_cancel_sdk_operation() -> None:
    started = threading.Event()
    release = threading.Event()

    def operation() -> str:
        started.set()
        release.wait(1)
        return "completed"

    call = OwnedBlockingCall(
        loop=asyncio.get_running_loop(),
        operation=operation,
        name="test-owned-blocking-cancel",
    )
    call.start()
    assert await asyncio.to_thread(started.wait, 1)
    waiter = asyncio.create_task(call.wait(1))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert call.finished is False

    call.abandon()
    release.set()
    await _wait_until(lambda: call.finished)


@pytest.mark.asyncio
async def test_wait_for_owned_call_adopts_completed_at_deadline() -> None:
    class _CompletedCall:
        operation_finished = True
        operation_finished_at = 10.0

        def __init__(self) -> None:
            self.adopted = False
            self.abandoned = False

        async def wait(self, _timeout: float) -> object:
            raise OwnedCallTimeout(deadline=10.0)

        def result_or_raise(self) -> object:
            return "completed"

        def adopt(self) -> bool:
            self.adopted = True
            return True

        def abandon(self) -> None:
            self.abandoned = True

    call = _CompletedCall()
    result = await wait_for_owned_call(
        call,  # type: ignore[arg-type]
        timeout_seconds=1,
        timeout_error=lambda _exc: AssertionError("must not timeout"),
    )
    assert result == "completed"
    assert call.adopted is True
    assert call.abandoned is False


@pytest.mark.asyncio
async def test_wait_for_owned_call_abandons_unresolved_timeout() -> None:
    class _UnresolvedCall:
        operation_finished = False
        operation_finished_at = None

        def __init__(self) -> None:
            self.abandoned = False

        async def wait(self, _timeout: float) -> object:
            raise OwnedCallTimeout(deadline=10.0)

        def abandon(self) -> None:
            self.abandoned = True

        def adopt(self) -> bool:
            return False

    call = _UnresolvedCall()
    with pytest.raises(RuntimeError, match="deadline"):
        await wait_for_owned_call(
            call,  # type: ignore[arg-type]
            timeout_seconds=1,
            timeout_error=lambda _exc: RuntimeError("deadline"),
        )
    assert call.abandoned is True


@pytest.mark.asyncio
@pytest.mark.parametrize("finished", [False, True])
async def test_wait_for_owned_call_cancellation_preserves_completion_ownership(
    finished: bool,
) -> None:
    class _CancelledCall:
        operation_finished = finished
        operation_finished_at = 1.0 if finished else None

        def __init__(self) -> None:
            self.adopted = False
            self.abandoned = False

        async def wait(self, _timeout: float) -> object:
            raise asyncio.CancelledError

        def adopt(self) -> bool:
            self.adopted = True
            return True

        def abandon(self) -> None:
            self.abandoned = True

    call = _CancelledCall()
    with pytest.raises(asyncio.CancelledError):
        await wait_for_owned_call(
            call,  # type: ignore[arg-type]
            timeout_seconds=1,
            timeout_error=lambda _exc: AssertionError("must not timeout"),
        )
    assert call.adopted is finished
    assert call.abandoned is not finished


@pytest.mark.asyncio
async def test_owned_call_adopt_and_abandon_race_releases_worker() -> None:
    started = threading.Event()
    release = threading.Event()

    def operation() -> str:
        started.set()
        release.wait(1)
        return "result"

    call = OwnedBlockingCall(
        loop=asyncio.get_running_loop(),
        operation=operation,
        name="test-owned-adopt-abandon-race",
    )
    call.start()
    assert await asyncio.to_thread(started.wait, 1)
    release.set()
    await asyncio.wait_for(call.future, 1)

    barrier = threading.Barrier(3)

    def adopt() -> bool:
        barrier.wait()
        return call.adopt()

    def abandon() -> None:
        barrier.wait()
        call.abandon()

    adopt_task = asyncio.create_task(asyncio.to_thread(adopt))
    abandon_task = asyncio.create_task(asyncio.to_thread(abandon))
    await asyncio.to_thread(barrier.wait)
    adopted = await adopt_task
    await abandon_task
    assert call.adopted is adopted
    await _wait_until(lambda: call.finished)


def test_tracker_fail_fast_capacity_and_atomic_idempotent_release() -> None:
    tracker = OwnedOperationTracker(2)
    first = _TrackerCall()
    second = _TrackerCall()
    third = _TrackerCall()

    assert tracker.admit(first) is True
    assert tracker.admit(second) is True
    assert tracker.admit(third) is False
    assert tracker.admit(_TrackerCall(), exclusive=True) is False
    assert tracker.active_count == 2
    assert tracker.retained_count == 2

    first.finished = True
    assert tracker.retained_count == 1
    assert tracker.is_idle() is False
    assert tracker.release(first) is True
    assert tracker.release(first) is False
    assert tracker.active_count == 1
    assert tracker.release(second) is True
    assert tracker.is_idle() is True
    assert tracker.active_count == 0


def test_tracker_concurrent_admission_and_release_stay_within_capacity() -> None:
    tracker = OwnedOperationTracker(4)
    calls = [_TrackerCall() for _ in range(32)]
    admission_barrier = threading.Barrier(len(calls) + 1)
    admitted: list[_TrackerCall] = []
    admission_errors: list[RuntimeError] = []
    admitted_lock = threading.Lock()

    def admit(call: _TrackerCall) -> None:
        try:
            admission_barrier.wait()
            if tracker.admit(call):
                with admitted_lock:
                    admitted.append(call)
        except RuntimeError as exc:  # pragma: no cover - assertion below reports it
            with admitted_lock:
                admission_errors.append(exc)

    threads = [threading.Thread(target=admit, args=(call,)) for call in calls]
    for thread in threads:
        thread.start()
    admission_barrier.wait()
    for thread in threads:
        thread.join(1)

    assert admission_errors == []
    assert all(not thread.is_alive() for thread in threads)
    assert len(admitted) == 4
    assert tracker.active_count == 4

    release_barrier = threading.Barrier(len(admitted) + 1)
    release_results: list[bool] = []

    def release(call: _TrackerCall) -> None:
        release_barrier.wait()
        with admitted_lock:
            release_results.append(tracker.release(call))

    release_threads = [
        threading.Thread(target=release, args=(call,)) for call in admitted
    ]
    for thread in release_threads:
        thread.start()
    release_barrier.wait()
    for thread in release_threads:
        thread.join(1)

    assert sorted(release_results) == [True] * 4
    assert all(not thread.is_alive() for thread in release_threads)
    assert tracker.active_count == 0
    assert tracker.is_idle() is True


@pytest.mark.asyncio
async def test_tracker_idle_wait_rechecks_exact_deadline_before_quarantine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = OwnedOperationTracker(1)
    call = _TrackerCall()
    assert tracker.admit(call) is True

    class _Clock:
        values = iter((0.0, 1.0))

        @classmethod
        def monotonic(cls) -> float:
            return next(cls.values)

    monkeypatch.setattr(ownership_module, "time", _Clock)
    checks = iter((False, True))
    actual_is_idle = tracker.is_idle

    def idle_after_release() -> bool:
        if next(checks) is False:
            return False
        tracker.release(call)
        return actual_is_idle()

    monkeypatch.setattr(tracker, "is_idle", idle_after_release)
    await tracker.wait_until_idle(
        timeout_seconds=1,
        timeout_error=lambda: RuntimeError("must not timeout"),
    )
    assert tracker.quarantined is False


@pytest.mark.asyncio
async def test_tracker_idle_deadline_quarantines_and_cancellation_is_non_mutating() -> (
    None
):
    tracker = OwnedOperationTracker(1)
    call = _TrackerCall()
    assert tracker.admit(call) is True

    wait_task = asyncio.create_task(
        tracker.wait_until_idle(
            timeout_seconds=1,
            timeout_error=lambda: RuntimeError("deadline"),
        )
    )
    await asyncio.sleep(0)
    wait_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await wait_task
    assert tracker.quarantined is False
    assert tracker.active_count == 1

    with pytest.raises(RuntimeError, match="deadline"):
        await tracker.wait_until_idle(
            timeout_seconds=0.01,
            timeout_error=lambda: RuntimeError("deadline"),
        )
    assert tracker.quarantined is True
    assert tracker.release(call) is True
    assert tracker.is_idle() is True
    assert tracker.admit(_TrackerCall()) is False


def test_tracker_start_failure_releases_admission_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = OwnedOperationTracker(1)

    def fail_start(_thread: threading.Thread) -> None:
        raise RuntimeError("thread start failed")

    monkeypatch.setattr(ownership_module.Thread, "start", fail_start)
    call = OwnedBlockingCall(
        loop=asyncio.new_event_loop(),
        operation=lambda: None,
        name="test-owned-start-failure",
        finished_callback=tracker.release,
    )
    try:
        assert tracker.admit(call) is True
        with pytest.raises(RuntimeError, match="thread start failed"):
            call.start()
        assert tracker.active_count == 0
        assert tracker.retained_count == 0
        assert tracker.release(call) is False
    finally:
        call._loop.close()


def test_tracker_duplicate_admission_fails_closed() -> None:
    tracker = OwnedOperationTracker(1)
    call = _TrackerCall()
    assert tracker.admit(call) is True

    with pytest.raises(OwnershipAccountingError):
        tracker.admit(call)
    assert tracker.quarantined is True
    assert tracker.active_count == 1
    assert tracker.release(call) is True
    assert tracker.release(call) is False
