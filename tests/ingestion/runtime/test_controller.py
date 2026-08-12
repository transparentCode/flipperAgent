from __future__ import annotations

import asyncio
import copy
from datetime import UTC, datetime

import pytest

from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.runtime.controller import (
    RuntimeControlConflictError,
    RuntimeController,
)
from apps.ingestion_app.runtime.supervisor import (
    DesiredRuntimeState,
    RuntimeSnapshot,
    RuntimeState,
)
from apps.ingestion_app.settings import IngestionSettings
from tests.ingestion.runtime.test_supervisor import LANE, _settings


class _FakeSupervisor:
    def __init__(self, *, fail_run: bool = False) -> None:
        self._fail_run = fail_run
        self._stop_event = asyncio.Event()
        self.run_started = asyncio.Event()
        self.run_stopped = asyncio.Event()
        self.run_calls = 0
        self._snapshot = RuntimeSnapshot(
            desired_state=DesiredRuntimeState.RUNNING,
            state=RuntimeState.STOPPED,
            last_error=None,
        )
        self.recovery_requests: list[RecoveryRequest] = []

    async def run(self) -> None:
        self.run_calls += 1
        self.run_started.set()
        if self._fail_run:
            self._snapshot = RuntimeSnapshot(
                desired_state=DesiredRuntimeState.RUNNING,
                state=RuntimeState.ERROR,
                last_error="synthetic supervisor failure",
            )
            raise RuntimeError("synthetic supervisor failure")
        self._snapshot = RuntimeSnapshot(
            desired_state=self._snapshot.desired_state,
            state=RuntimeState.LIVE,
            last_error=None,
        )
        await self._stop_event.wait()
        self._snapshot = RuntimeSnapshot(
            desired_state=self._snapshot.desired_state,
            state=RuntimeState.STOPPED,
            last_error=None,
        )
        self.run_stopped.set()

    def stop(self) -> None:
        self._stop_event.set()

    def pause(self) -> None:
        self._snapshot = RuntimeSnapshot(
            desired_state=DesiredRuntimeState.PAUSED,
            state=RuntimeState.STOPPED,
            last_error=None,
        )

    def resume(self) -> None:
        self._snapshot = RuntimeSnapshot(
            desired_state=DesiredRuntimeState.RUNNING,
            state=self._snapshot.state,
            last_error=self._snapshot.last_error,
        )

    def snapshot(self) -> RuntimeSnapshot:
        return self._snapshot

    async def execute_recovery(self, request: RecoveryRequest) -> None:
        self.recovery_requests.append(request)


class _HeldStopSupervisor(_FakeSupervisor):
    def __init__(self, *, hold_stop: bool) -> None:
        super().__init__()
        self.hold_stop = hold_stop
        self.stop_called = asyncio.Event()
        self.cancelled = asyncio.Event()

    def stop(self) -> None:
        self.stop_called.set()
        if not self.hold_stop:
            self._stop_event.set()

    async def run(self) -> None:
        self.run_calls += 1
        self.run_started.set()
        self._snapshot = RuntimeSnapshot(
            desired_state=self._snapshot.desired_state,
            state=RuntimeState.LIVE,
            last_error=None,
        )
        try:
            await self._stop_event.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            self.run_stopped.set()
            raise
        self._snapshot = RuntimeSnapshot(
            desired_state=self._snapshot.desired_state,
            state=RuntimeState.STOPPED,
            last_error=None,
        )
        self.run_stopped.set()


class _BlockingRecoverySupervisor(_FakeSupervisor):
    def __init__(self, recovery_started: asyncio.Event) -> None:
        super().__init__()
        self.recovery_started = recovery_started

    async def execute_recovery(self, request: RecoveryRequest) -> None:
        del request
        self.recovery_started.set()
        await asyncio.Event().wait()


def _disabled_settings(settings: IngestionSettings) -> IngestionSettings:
    raw = copy.deepcopy(settings.model_dump())
    raw["assets"]["BTC"]["enabled"] = False
    return IngestionSettings.model_validate(raw)


def _request() -> RecoveryRequest:
    return RecoveryRequest(
        lane=LANE,
        since=datetime(2026, 8, 9, 9, 0, tzinfo=UTC),
        until=datetime(2026, 8, 9, 10, 0, tzinfo=UTC),
        reason="manual_api",
    )


@pytest.mark.asyncio
async def test_start_zero_assets_is_valid_and_resume_stays_stopped() -> None:
    settings = _disabled_settings(_settings())
    created: list[_FakeSupervisor] = []

    def factory(candidate: IngestionSettings) -> _FakeSupervisor:
        del candidate
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(settings=settings, supervisor_factory=factory)

    await controller.start()
    assert controller.is_started is True
    assert created == []
    assert controller.snapshot().state is RuntimeState.STOPPED
    resumed = await controller.resume()

    assert resumed.desired_state is DesiredRuntimeState.RUNNING
    assert resumed.state is RuntimeState.STOPPED
    assert created == []

    await controller.close()
    assert controller.is_started is False


@pytest.mark.asyncio
async def test_pre_start_controls_conflict_and_replace_does_not_start_runtime() -> None:
    created: list[_FakeSupervisor] = []

    def factory(candidate: IngestionSettings) -> _FakeSupervisor:
        del candidate
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(settings=_settings(), supervisor_factory=factory)
    assert controller.is_started is False
    for operation in (
        controller.pause,
        controller.resume,
        controller.reconnect,
        lambda: controller.recover(_request()),
    ):
        with pytest.raises(RuntimeControlConflictError, match="not started"):
            await operation()

    await controller.replace_settings(_settings())
    assert controller.is_started is False
    assert created[0].run_calls == 0

    await controller.start()
    assert controller.is_started is True
    await created[1].run_started.wait()
    assert created[1].run_calls == 1
    await controller.close()
    assert controller.is_started is False


@pytest.mark.asyncio
async def test_pause_and_resume_preserve_controller_desired_state() -> None:
    created: list[_FakeSupervisor] = []

    def factory(candidate: IngestionSettings) -> _FakeSupervisor:
        del candidate
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(settings=_settings(), supervisor_factory=factory)
    await controller.start()
    await asyncio.sleep(0)

    paused = await controller.pause()
    assert paused.desired_state is DesiredRuntimeState.PAUSED

    resumed = await controller.resume()
    assert resumed.desired_state is DesiredRuntimeState.RUNNING
    assert len(created) == 1

    await controller.close()


@pytest.mark.asyncio
async def test_paused_settings_replacement_resumes_new_supervisor() -> None:
    created: list[_FakeSupervisor] = []

    def factory(candidate: IngestionSettings) -> _FakeSupervisor:
        del candidate
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(settings=_settings(), supervisor_factory=factory)
    await controller.start()
    await asyncio.sleep(0)
    await controller.pause()
    await controller.replace_settings(_settings())

    paused = controller.snapshot()
    assert paused.desired_state is DesiredRuntimeState.PAUSED
    assert paused.state is RuntimeState.STOPPED

    await controller.resume()
    await asyncio.sleep(0)
    assert controller.snapshot().desired_state is DesiredRuntimeState.RUNNING
    assert len(created) == 2
    await controller.close()


@pytest.mark.asyncio
async def test_reconnect_replaces_supervisor_and_rejects_paused_runtime() -> None:
    created: list[_FakeSupervisor] = []

    def factory(candidate: IngestionSettings) -> _FakeSupervisor:
        del candidate
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(settings=_settings(), supervisor_factory=factory)
    await controller.start()
    await asyncio.sleep(0)
    await controller.reconnect()
    await asyncio.sleep(0)
    assert len(created) == 2

    await controller.pause()
    with pytest.raises(RuntimeControlConflictError):
        await controller.reconnect()
    await controller.close()


@pytest.mark.asyncio
async def test_supervisor_task_exception_is_consumed_into_snapshot() -> None:
    def factory(candidate: IngestionSettings) -> _FakeSupervisor:
        del candidate
        return _FakeSupervisor(fail_run=True)

    controller = RuntimeController(settings=_settings(), supervisor_factory=factory)
    await controller.start()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    snapshot = controller.snapshot()
    assert snapshot.state is RuntimeState.ERROR
    assert snapshot.last_error == "synthetic supervisor failure"
    await controller.close()


@pytest.mark.asyncio
async def test_manual_recovery_runs_offline_then_restores_running_runtime() -> None:
    created: list[_FakeSupervisor] = []

    def factory(candidate: IngestionSettings) -> _FakeSupervisor:
        del candidate
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(settings=_settings(), supervisor_factory=factory)
    await controller.start()
    await asyncio.sleep(0)

    snapshot = await controller.recover(_request())

    assert snapshot.desired_state is DesiredRuntimeState.RUNNING
    assert len(created) == 3
    assert created[1].recovery_requests == [_request()]
    await controller.close()


@pytest.mark.asyncio
async def test_replace_settings_can_remove_final_asset() -> None:
    created: list[_FakeSupervisor] = []

    def factory(candidate: IngestionSettings) -> _FakeSupervisor:
        del candidate
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(settings=_settings(), supervisor_factory=factory)
    await controller.start()
    await asyncio.sleep(0)
    snapshot = await controller.replace_settings(_disabled_settings(_settings()))

    assert snapshot.state is RuntimeState.STOPPED
    assert snapshot.desired_state is DesiredRuntimeState.RUNNING
    assert len(created) == 1
    await controller.close()


@pytest.mark.asyncio
async def test_cancelled_replace_restores_started_runtime() -> None:
    created: list[_HeldStopSupervisor] = []

    def factory(candidate: IngestionSettings) -> _HeldStopSupervisor:
        del candidate
        supervisor = _HeldStopSupervisor(hold_stop=not created)
        created.append(supervisor)
        return supervisor

    original_settings = _settings()
    controller = RuntimeController(
        settings=original_settings,
        supervisor_factory=factory,
    )
    await controller.start()
    await created[0].run_started.wait()

    replacement = asyncio.create_task(
        controller.replace_settings(_settings(target_timeframes=("1h",)))
    )
    await created[0].stop_called.wait()
    replacement.cancel()
    with pytest.raises(asyncio.CancelledError):
        await replacement

    assert controller.is_started is True
    assert controller.settings == original_settings
    assert created[0].cancelled.is_set()
    assert created[1].run_calls == 0
    assert created[2].run_calls == 1

    await controller.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("paused", [False, True])
async def test_cancelled_recovery_restores_previous_runtime(paused: bool) -> None:
    created: list[_FakeSupervisor] = []
    recovery_started = asyncio.Event()

    def factory(candidate: IngestionSettings) -> _FakeSupervisor:
        del candidate
        if len(created) == 1:
            supervisor = _BlockingRecoverySupervisor(recovery_started)
        else:
            supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(settings=_settings(), supervisor_factory=factory)
    await controller.start()
    await created[0].run_started.wait()
    if paused:
        await controller.pause()
        created[0]._stop_event.set()
        await created[0].run_stopped.wait()

    recovery = asyncio.create_task(controller.recover(_request()))
    await recovery_started.wait()
    recovery.cancel()
    with pytest.raises(asyncio.CancelledError):
        await recovery

    assert controller.is_started is True
    assert controller.snapshot().desired_state is (
        DesiredRuntimeState.PAUSED if paused else DesiredRuntimeState.RUNNING
    )
    assert created[1].run_calls == 0
    if paused:
        assert created[2].run_calls == 0
        assert controller.snapshot().state is RuntimeState.STOPPED
    else:
        assert created[2].run_calls == 1

    await controller.close()
