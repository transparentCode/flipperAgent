from __future__ import annotations

import asyncio
import copy
import threading
from datetime import UTC, datetime, timedelta

import pytest

from apps.ingestion_app.api.app import create_app
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.observability import IngestionObservability
from apps.ingestion_app.planning import (
    IngestionPlan,
    compile_ingestion_plan,
)
from apps.ingestion_app.providers.base import TransportDeadlineExceeded
from apps.ingestion_app.providers.binance_native import (
    BinanceNativeHistoricalProvider,
)
from apps.ingestion_app.providers.factory import (
    wait_until_historical_providers_idle,
)
from apps.ingestion_app.runtime.controller import (
    RuntimeControlConflictError,
    RuntimeController,
)
from apps.ingestion_app.runtime.state import (
    DesiredRuntimeState,
    RuntimeState,
    SupervisorSnapshot,
)
from apps.ingestion_app.settings import IngestionSettings
from tests.ingestion._asgi import request
from tests.ingestion.runtime.test_supervisor import LANE, _settings


def _plan_factory(settings: IngestionSettings) -> IngestionPlan:
    return compile_ingestion_plan(
        settings,
        live_provider_ids={"binance_native"},
        historical_provider_ids={"binance_native", "ccxt_binance"},
    )


class _FakeSupervisor:
    def __init__(self, *, fail_run: bool = False) -> None:
        self._fail_run = fail_run
        self._stop_event = asyncio.Event()
        self.run_started = asyncio.Event()
        self.run_stopped = asyncio.Event()
        self.run_calls = 0
        self.stop_calls = 0
        self._snapshot = SupervisorSnapshot(
            state=RuntimeState.STOPPED,
            last_error=None,
        )
        self.recovery_requests: list[RecoveryRequest] = []

    async def run(self) -> None:
        self.run_calls += 1
        self.run_started.set()
        if self._fail_run:
            self._snapshot = SupervisorSnapshot(
                state=RuntimeState.ERROR,
                last_error="synthetic supervisor failure",
            )
            raise RuntimeError("synthetic supervisor failure")
        self._snapshot = SupervisorSnapshot(
            state=RuntimeState.LIVE,
            last_error=None,
        )
        await self._stop_event.wait()
        self._snapshot = SupervisorSnapshot(
            state=RuntimeState.STOPPED,
            last_error=None,
        )
        self.run_stopped.set()

    def stop(self) -> None:
        self.stop_calls += 1
        self._stop_event.set()

    def snapshot(self) -> SupervisorSnapshot:
        return self._snapshot

    async def execute_recovery(self, request: RecoveryRequest) -> None:
        self.recovery_requests.append(request)


class _TraceSupervisor(_FakeSupervisor):
    def __init__(self, trace: list[str]) -> None:
        super().__init__()
        self.trace = trace

    def stop(self) -> None:
        self.trace.append("stop")
        super().stop()

    async def run(self) -> None:
        self.trace.append("run-start")
        try:
            await super().run()
        finally:
            self.trace.append("run-stop")


class _TraceRecoverySupervisor(_TraceSupervisor):
    async def execute_recovery(self, request: RecoveryRequest) -> None:
        self.trace.append("recovery")
        await super().execute_recovery(request)


class _BlockingQuiescence:
    def __init__(self, trace: list[str] | None = None) -> None:
        self.trace = trace
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.block = False

    async def __call__(self) -> None:
        self.calls += 1
        if self.trace is not None:
            self.trace.append("barrier")
        if self.block:
            self.entered.set()
            await self.release.wait()


class _DeadlineAfterCancellationQuiescence:
    def __init__(self) -> None:
        self.calls = 0
        self.entered = asyncio.Event()

    async def __call__(self) -> None:
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            await asyncio.Event().wait()
        raise TransportDeadlineExceeded(
            provider_id="binance_native",
            operation="historical provider quiescence",
            timeout_seconds=1,
        )


class _RecoveryCancellationQuiescence:
    def __init__(self) -> None:
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self) -> None:
        self.calls += 1
        if self.calls == 2:
            self.entered.set()
            await self.release.wait()


class _HeldNativeClient:
    def __init__(self) -> None:
        self.klines_started = threading.Event()
        self.release_klines = threading.Event()
        self._count_lock = threading.Lock()
        self.klines_call_count = 0
        self.session = _HeldNativeSession()

    def klines(self, *args: object, **kwargs: object) -> list[object]:
        del args, kwargs
        with self._count_lock:
            self.klines_call_count += 1
        self.klines_started.set()
        self.release_klines.wait(5)
        return []


class _HeldNativeSession:
    def close(self) -> None:
        return None


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
        self._snapshot = SupervisorSnapshot(
            state=RuntimeState.LIVE,
            last_error=None,
        )
        try:
            await self._stop_event.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            self.run_stopped.set()
            raise
        self._snapshot = SupervisorSnapshot(
            state=RuntimeState.STOPPED,
            last_error=None,
        )
        self.run_stopped.set()


class _SlowStopSupervisor(_FakeSupervisor):
    """Model a generation whose stop signal starts, but does not finish cleanup."""

    def __init__(self) -> None:
        super().__init__()
        self.stop_called = asyncio.Event()
        self.cleanup_release = asyncio.Event()

    def stop(self) -> None:
        self.stop_calls += 1
        self.stop_called.set()

    async def run(self) -> None:
        self.run_calls += 1
        self.run_started.set()
        self._snapshot = SupervisorSnapshot(
            state=RuntimeState.LIVE,
            last_error=None,
        )
        await self.cleanup_release.wait()
        self._snapshot = SupervisorSnapshot(
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


class _FailingRecoverySupervisor(_FakeSupervisor):
    async def execute_recovery(self, request: RecoveryRequest) -> None:
        del request
        raise RuntimeError("synthetic manual recovery failure")


class _ObservabilitySupervisor(_FakeSupervisor):
    active_lanes = (LANE,)


class _QuarantinedSupervisor(_FakeSupervisor):
    quarantined = True

    def __init__(self) -> None:
        super().__init__()
        self._snapshot = SupervisorSnapshot(
            state=RuntimeState.ERROR,
            last_error="lifecycle cleanup failed; lifecycle quarantined",
        )


class _QuarantinesAfterStopSupervisor(_FakeSupervisor):
    def __init__(self) -> None:
        super().__init__()
        self.quarantined = False

    async def run(self) -> None:
        try:
            await super().run()
        finally:
            self.quarantined = True


class _RetainedStatusSupervisor(_FakeSupervisor):
    def __init__(self) -> None:
        super().__init__()
        self.quarantined = False


class _FailsOnReplacementInstallObservability(IngestionObservability):
    def __init__(self) -> None:
        super().__init__()
        self.install_calls = 0

    def install_active_lanes(self, lanes) -> None:  # type: ignore[no-untyped-def]
        self.install_calls += 1
        if self.install_calls == 2:
            raise RuntimeError("synthetic replacement install failure")
        super().install_active_lanes(lanes)


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

    controller = RuntimeController(
        settings=settings,
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )

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

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
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
    assert created == []

    await controller.start()
    assert controller.is_started is True
    await created[0].run_started.wait()
    assert created[0].run_calls == 1
    await controller.close()
    assert controller.is_started is False


def test_validate_settings_is_pure_while_observability_is_live() -> None:
    observability = IngestionObservability()
    observability.set_runtime_live(True)
    supervisor_factory_calls = 0

    def factory(plan: IngestionPlan) -> _FakeSupervisor:
        nonlocal supervisor_factory_calls
        del plan
        supervisor_factory_calls += 1
        return _FakeSupervisor()

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
        observability=observability,
    )

    controller.validate_settings(_settings(target_timeframes=("1h",)))

    assert observability._runtime_live is True
    assert supervisor_factory_calls == 0
    assert controller.is_started is False
    assert controller.settings == _settings()


@pytest.mark.asyncio
async def test_pause_and_resume_preserve_controller_desired_state() -> None:
    created: list[_FakeSupervisor] = []

    def factory(candidate: IngestionSettings) -> _FakeSupervisor:
        del candidate
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
    await controller.start()
    await asyncio.sleep(0)

    paused = await controller.pause()
    assert paused.desired_state is DesiredRuntimeState.PAUSED
    assert created[0].stop_calls == 1

    resumed = await controller.resume()
    assert resumed.desired_state is DesiredRuntimeState.RUNNING
    assert len(created) == 2
    await created[1].run_started.wait()
    assert created[1].run_calls == 1

    await controller.close()


@pytest.mark.asyncio
async def test_resume_replaces_completed_running_generation() -> None:
    created: list[_FakeSupervisor] = []

    def factory(_plan: IngestionPlan) -> _FakeSupervisor:
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
    await controller.start()
    await created[0].run_started.wait()

    # Model an unexpected but clean one-generation termination while the
    # controller still desires RUNNING.  Resume must install a new generation
    # instead of silently leaving the controller stopped.
    created[0].stop()
    await created[0].run_stopped.wait()
    await asyncio.sleep(0)

    resumed = await controller.resume()

    assert resumed.desired_state is DesiredRuntimeState.RUNNING
    assert len(created) == 2
    await created[1].run_started.wait()
    assert created[1].run_calls == 1
    await controller.close()


@pytest.mark.asyncio
async def test_repeated_pause_resume_keeps_one_active_generation() -> None:
    created: list[_FakeSupervisor] = []

    def factory(_plan: IngestionPlan) -> _FakeSupervisor:
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
    await controller.start()
    await created[0].run_started.wait()

    for _ in range(3):
        paused = await controller.pause()
        assert paused.desired_state is DesiredRuntimeState.PAUSED
        resumed = await controller.resume()
        assert resumed.desired_state is DesiredRuntimeState.RUNNING
        await created[-1].run_started.wait()
        assert (
            len(
                [
                    task
                    for task in asyncio.all_tasks()
                    if task.get_name() == "ingestion-supervisor" and not task.done()
                ]
            )
            == 1
        )

    assert len(created) == 4
    await controller.close()


@pytest.mark.asyncio
async def test_initial_start_and_pause_do_not_wait_for_provider_quiescence() -> None:
    barrier = _BlockingQuiescence()
    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=lambda _plan: _FakeSupervisor(),
        historical_provider_quiescence=barrier,
    )

    await controller.start()
    await asyncio.sleep(0)
    await controller.pause()

    assert barrier.calls == 0
    await controller.close()


@pytest.mark.asyncio
async def test_paused_resume_waits_before_reopening_supervisor_admission() -> None:
    created: list[_SlowStopSupervisor] = []
    barrier = _BlockingQuiescence()
    barrier.block = True

    def factory(_plan: IngestionPlan) -> _SlowStopSupervisor:
        supervisor = _SlowStopSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
        historical_provider_quiescence=barrier,
    )
    await controller.start()
    await created[0].run_started.wait()
    paused = await controller.pause()
    assert paused.desired_state is DesiredRuntimeState.PAUSED
    assert paused.state is RuntimeState.LIVE
    assert created[0].stop_called.is_set()
    assert barrier.calls == 0

    resume = asyncio.create_task(controller.resume())
    await asyncio.sleep(0.05)
    assert not resume.done()
    assert controller.snapshot().desired_state is DesiredRuntimeState.PAUSED
    assert len(created) == 1
    assert barrier.calls == 0

    created[0].cleanup_release.set()
    await asyncio.wait_for(barrier.entered.wait(), 1)
    assert not resume.done()
    assert len(created) == 1
    assert controller.snapshot().state is RuntimeState.STOPPED

    barrier.release.set()
    resumed = await asyncio.wait_for(resume, 1)
    assert resumed.desired_state is DesiredRuntimeState.RUNNING
    assert len(created) == 2
    assert created[1].run_calls == 1
    created[1].cleanup_release.set()
    await controller.close()


@pytest.mark.asyncio
async def test_resume_quiescence_deadline_latches_fatal_without_new_generation() -> (
    None
):
    created: list[_FakeSupervisor] = []

    async def fail_quiescence() -> None:
        raise TransportDeadlineExceeded(
            provider_id="binance_native",
            operation="historical provider quiescence",
            timeout_seconds=1,
        )

    def factory(_plan: IngestionPlan) -> _FakeSupervisor:
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
        historical_provider_quiescence=fail_quiescence,
    )
    await controller.start()
    await created[0].run_started.wait()
    await controller.pause()

    with pytest.raises(TransportDeadlineExceeded):
        await controller.resume()

    assert controller.quarantined is True
    assert controller.snapshot().state is RuntimeState.ERROR
    assert controller.snapshot().desired_state is DesiredRuntimeState.PAUSED
    assert len(created) == 1
    await controller.close()


@pytest.mark.asyncio
async def test_real_native_provider_quiescence_fences_immediate_resume() -> None:
    client = _HeldNativeClient()
    provider = BinanceNativeHistoricalProvider(
        client,
        attempt_timeout_seconds=1,
        max_concurrency=2,
    )

    async def fetch() -> tuple[object, ...]:
        return await provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTCUSDT",
            timeframe_duration=timedelta(minutes=1),
            since=datetime(2026, 8, 9, 9, 0, tzinfo=UTC),
            until=datetime(2026, 8, 9, 10, 0, tzinfo=UTC),
            limit=10,
        )

    predecessor_calls = [asyncio.create_task(fetch()) for _ in range(2)]
    try:
        await asyncio.wait_for(
            asyncio.to_thread(client.klines_started.wait, 1),
            1,
        )
        deadline = asyncio.get_running_loop().time() + 1
        while client.klines_call_count < 2:
            if asyncio.get_running_loop().time() >= deadline:
                pytest.fail("both native provider slots were not occupied")
            await asyncio.sleep(0.01)

        for task in predecessor_calls:
            task.cancel()
        results = await asyncio.gather(*predecessor_calls, return_exceptions=True)
        assert all(isinstance(result, asyncio.CancelledError) for result in results)
        assert provider.retained_worker_count == 2

        controller = RuntimeController(
            settings=_settings(),
            plan_factory=_plan_factory,
            supervisor_factory=lambda _plan: _FakeSupervisor(),
            historical_provider_quiescence=lambda: wait_until_historical_providers_idle(
                {"binance_native": provider}
            ),
        )
        await controller.start()
        await asyncio.sleep(0)
        await controller.pause()

        resume = asyncio.create_task(controller.resume())
        await asyncio.sleep(0.05)
        assert not resume.done()
        assert client.klines_call_count == 2
        snapshot = controller.snapshot()
        assert snapshot.state is not RuntimeState.ERROR
        assert snapshot.last_error is None

        client.release_klines.set()
        resumed = await asyncio.wait_for(resume, 1)
        assert resumed.desired_state is DesiredRuntimeState.RUNNING
        assert client.klines_call_count == 2
        await asyncio.wait_for(provider.wait_until_idle(), 1)
        assert provider.retained_worker_count == 0
        await controller.close()
    finally:
        client.release_klines.set()
        await asyncio.gather(*predecessor_calls, return_exceptions=True)
        if provider.retained_worker_count:
            await asyncio.wait_for(provider.wait_until_idle(), 1)
        await provider.close()


@pytest.mark.asyncio
async def test_paused_settings_replacement_resumes_new_supervisor() -> None:
    created: list[_FakeSupervisor] = []

    def factory(candidate: IngestionSettings) -> _FakeSupervisor:
        del candidate
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
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

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
    await controller.start()
    await asyncio.sleep(0)
    await controller.reconnect()
    await asyncio.sleep(0)
    assert len(created) == 2

    paused = await controller.pause()
    assert paused.desired_state is DesiredRuntimeState.PAUSED
    with pytest.raises(RuntimeControlConflictError):
        await controller.reconnect()
    assert len(created) == 2
    await controller.close()


@pytest.mark.asyncio
async def test_reconnect_builds_before_stop_and_starts_after_old_generation_stops() -> (
    None
):
    trace: list[str] = []
    created: list[_TraceSupervisor] = []
    barrier = _BlockingQuiescence(trace)

    def factory(candidate: IngestionSettings) -> _TraceSupervisor:
        del candidate
        trace.append("build")
        supervisor = _TraceSupervisor(trace)
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
        historical_provider_quiescence=barrier,
    )
    await controller.start()
    await created[0].run_started.wait()
    trace.clear()

    await controller.reconnect()
    await created[1].run_started.wait()

    assert trace == ["build", "stop", "run-stop", "barrier", "run-start"]
    await controller.close()


@pytest.mark.asyncio
async def test_settings_replacement_waits_for_quiescence_before_install() -> None:
    trace: list[str] = []
    created: list[_TraceSupervisor] = []
    barrier = _BlockingQuiescence(trace)

    def factory(_plan: IngestionPlan) -> _TraceSupervisor:
        trace.append("build")
        supervisor = _TraceSupervisor(trace)
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
        historical_provider_quiescence=barrier,
    )
    await controller.start()
    await created[0].run_started.wait()
    trace.clear()

    await controller.replace_settings(_settings(target_timeframes=("1h",)))
    await created[1].run_started.wait()

    assert trace == ["build", "stop", "run-stop", "barrier", "run-start"]
    await controller.close()


@pytest.mark.asyncio
async def test_reconnect_install_failure_does_not_restore_old_generation() -> None:
    created: list[_ObservabilitySupervisor] = []

    def factory(candidate: IngestionSettings) -> _ObservabilitySupervisor:
        del candidate
        supervisor = _ObservabilitySupervisor()
        created.append(supervisor)
        return supervisor

    observability = _FailsOnReplacementInstallObservability()
    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
        observability=observability,
    )
    await controller.start()
    await created[0].run_started.wait()

    with pytest.raises(RuntimeError, match="replacement install failure"):
        await controller.reconnect()

    assert created[0].run_stopped.is_set()
    assert created[1].run_calls == 0
    assert controller.is_started is True
    assert controller._supervisor is None
    assert controller._supervisor_task is None
    assert controller.snapshot().state is RuntimeState.ERROR
    assert controller.snapshot().last_error == "synthetic replacement install failure"
    ready = await request(
        create_app(runtime_controller=controller),
        "GET",
        "/health/ready",
    )
    assert ready.status_code == 503

    await controller.reconnect()
    await created[2].run_started.wait()
    assert controller.snapshot().state is RuntimeState.LIVE
    assert controller.snapshot().last_error is None
    assert controller._terminal_error is None
    await controller.close()


@pytest.mark.asyncio
async def test_manual_recovery_failure_is_terminal_and_reconnect_recovers() -> None:
    created: list[_FakeSupervisor] = []

    def factory(_plan: IngestionPlan) -> _FakeSupervisor:
        supervisor: _FakeSupervisor
        if len(created) == 1:
            supervisor = _FailingRecoverySupervisor()
        else:
            supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
    await controller.start()
    await created[0].run_started.wait()

    with pytest.raises(RuntimeError, match="manual recovery failure"):
        await controller.recover(_request())

    assert controller.is_started is True
    assert controller._supervisor is None
    assert controller._supervisor_task is None
    assert controller.snapshot().state is RuntimeState.ERROR
    assert controller.snapshot().last_error == "synthetic manual recovery failure"
    ready = await request(
        create_app(runtime_controller=controller),
        "GET",
        "/health/ready",
    )
    assert ready.status_code == 503

    paused = await controller.pause()
    assert paused.desired_state is DesiredRuntimeState.PAUSED

    await controller.reconnect()
    await created[2].run_started.wait()
    assert controller.snapshot().state is RuntimeState.LIVE
    assert controller.snapshot().last_error is None
    assert controller._terminal_error is None
    await controller.close()


@pytest.mark.asyncio
async def test_paused_manual_recovery_failure_reconnects_to_running() -> None:
    created: list[_FakeSupervisor] = []

    def factory(_plan: IngestionPlan) -> _FakeSupervisor:
        if len(created) == 1:
            supervisor = _FailingRecoverySupervisor()
        else:
            supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
    await controller.start()
    await created[0].run_started.wait()
    paused = await controller.pause()
    assert paused.desired_state is DesiredRuntimeState.PAUSED
    await created[0].run_stopped.wait()

    with pytest.raises(RuntimeError, match="manual recovery failure"):
        await controller.recover(_request())

    failed = controller.snapshot()
    assert failed.desired_state is DesiredRuntimeState.PAUSED
    assert failed.state is RuntimeState.ERROR
    assert failed.last_error == "synthetic manual recovery failure"
    ready = await request(
        create_app(runtime_controller=controller),
        "GET",
        "/health/ready",
    )
    assert ready.status_code == 503

    recovered = await controller.reconnect()
    await created[2].run_started.wait()
    assert recovered.desired_state is DesiredRuntimeState.RUNNING
    live = controller.snapshot()
    assert live.state is RuntimeState.LIVE
    assert live.last_error is None
    assert controller._terminal_error is None
    assert len(created) == 3
    await controller.close()


@pytest.mark.asyncio
async def test_settings_replacement_install_failure_is_terminal_and_rollbackable() -> (
    None
):
    created: list[_ObservabilitySupervisor] = []

    def factory(_plan: IngestionPlan) -> _ObservabilitySupervisor:
        supervisor = _ObservabilitySupervisor()
        created.append(supervisor)
        return supervisor

    original_settings = _settings()
    candidate_settings = _settings(target_timeframes=("1h",))
    observability = _FailsOnReplacementInstallObservability()
    controller = RuntimeController(
        settings=original_settings,
        plan_factory=_plan_factory,
        supervisor_factory=factory,
        observability=observability,
    )
    await controller.start()
    await created[0].run_started.wait()

    with pytest.raises(RuntimeError, match="replacement install failure"):
        await controller.replace_settings(candidate_settings)

    assert controller.settings is candidate_settings
    assert controller._supervisor is None
    assert controller.snapshot().state is RuntimeState.ERROR
    ready = await request(
        create_app(runtime_controller=controller),
        "GET",
        "/health/ready",
    )
    assert ready.status_code == 503

    await controller.replace_settings(original_settings)
    await created[2].run_started.wait()
    assert controller.settings is original_settings
    assert controller.snapshot().state is RuntimeState.LIVE
    assert controller.snapshot().last_error is None
    assert controller._terminal_error is None
    await controller.close()


@pytest.mark.asyncio
async def test_terminal_error_zero_lane_replacement_clears_to_stopped() -> None:
    created: list[_ObservabilitySupervisor] = []

    def factory(_plan: IngestionPlan) -> _ObservabilitySupervisor:
        supervisor = _ObservabilitySupervisor()
        created.append(supervisor)
        return supervisor

    settings = _settings()
    observability = _FailsOnReplacementInstallObservability()
    controller = RuntimeController(
        settings=settings,
        plan_factory=_plan_factory,
        supervisor_factory=factory,
        observability=observability,
    )
    await controller.start()
    await created[0].run_started.wait()

    with pytest.raises(RuntimeError, match="replacement install failure"):
        await controller.reconnect()
    assert controller.snapshot().state is RuntimeState.ERROR

    accepted = await controller.replace_settings(_disabled_settings(settings))

    assert accepted.desired_state is DesiredRuntimeState.RUNNING
    assert accepted.state is RuntimeState.STOPPED
    assert accepted.last_error is None
    assert controller.is_started is True
    assert controller._supervisor is None
    assert controller._terminal_error is None
    assert controller._status_supervisor is created[0]
    await controller.close()


@pytest.mark.asyncio
async def test_terminal_error_paused_replacement_clears_to_stopped() -> None:
    created: list[_ObservabilitySupervisor] = []

    def factory(_plan: IngestionPlan) -> _ObservabilitySupervisor:
        supervisor = _ObservabilitySupervisor()
        created.append(supervisor)
        return supervisor

    settings = _settings()
    observability = _FailsOnReplacementInstallObservability()
    controller = RuntimeController(
        settings=settings,
        plan_factory=_plan_factory,
        supervisor_factory=factory,
        observability=observability,
    )
    await controller.start()
    await created[0].run_started.wait()

    with pytest.raises(RuntimeError, match="replacement install failure"):
        await controller.reconnect()
    paused = await controller.pause()
    assert paused.desired_state is DesiredRuntimeState.PAUSED
    assert paused.state is RuntimeState.ERROR

    replacement = _settings(target_timeframes=("1h",))
    accepted = await controller.replace_settings(replacement)

    assert accepted.desired_state is DesiredRuntimeState.PAUSED
    assert accepted.state is RuntimeState.STOPPED
    assert accepted.last_error is None
    assert controller.settings is replacement
    assert controller._supervisor is None
    assert controller._terminal_error is None
    await controller.close()


@pytest.mark.asyncio
async def test_retired_status_ordinary_error_is_ignored_but_late_quarantine_wins() -> (
    None
):
    created: list[_RetainedStatusSupervisor] = []

    def factory(_plan: IngestionPlan) -> _RetainedStatusSupervisor:
        supervisor = _RetainedStatusSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
    await controller.start()
    await created[0].run_started.wait()
    await controller.pause()
    await created[0].run_stopped.wait()

    created[0]._snapshot = SupervisorSnapshot(
        state=RuntimeState.ERROR,
        last_error="stale retired ordinary error",
    )
    accepted = await controller.replace_settings(_settings(target_timeframes=("1h",)))

    assert accepted.state is RuntimeState.STOPPED
    assert accepted.last_error is None
    assert controller._status_supervisor is created[0]
    assert controller._terminal_error is None

    created[0]._snapshot = SupervisorSnapshot(
        state=RuntimeState.ERROR,
        last_error="late lifecycle quarantine",
    )
    created[0].quarantined = True

    late = controller.snapshot()
    assert late.state is RuntimeState.ERROR
    assert late.last_error == "late lifecycle quarantine"
    assert controller.quarantined is True
    await controller.close()


@pytest.mark.asyncio
async def test_paused_resume_failure_after_stop_is_terminal_and_not_ready() -> None:
    created: list[_FakeSupervisor] = []

    def factory(_plan: IngestionPlan) -> _FakeSupervisor:
        if created:
            raise RuntimeError("synthetic resume replacement failure")
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
    await controller.start()
    await created[0].run_started.wait()
    await controller.pause()

    with pytest.raises(RuntimeError, match="resume replacement failure"):
        await controller.resume()

    assert controller.is_started is True
    assert controller._supervisor is None
    assert controller.snapshot().desired_state is DesiredRuntimeState.RUNNING
    assert controller.snapshot().state is RuntimeState.ERROR
    ready = await request(
        create_app(runtime_controller=controller),
        "GET",
        "/health/ready",
    )
    assert ready.status_code == 503
    await controller.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["reconnect", "replace"])
async def test_pre_stop_replacement_build_failure_preserves_live_predecessor(
    operation: str,
) -> None:
    created: list[_FakeSupervisor] = []

    def factory(_plan: IngestionPlan) -> _FakeSupervisor:
        if created:
            raise RuntimeError("synthetic pre-stop build failure")
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
    await controller.start()
    await created[0].run_started.wait()

    if operation == "reconnect":
        control = controller.reconnect()
    else:
        control = controller.replace_settings(_settings(target_timeframes=("1h",)))
    with pytest.raises(RuntimeError, match="pre-stop build failure"):
        await control

    assert created[0].stop_calls == 0
    assert controller.snapshot().state is RuntimeState.LIVE
    assert controller.snapshot().last_error is None
    assert controller._terminal_error is None
    await controller.close()


@pytest.mark.asyncio
async def test_supervisor_task_exception_is_consumed_into_snapshot() -> None:
    created: list[_FakeSupervisor] = []

    def factory(candidate: IngestionSettings) -> _FakeSupervisor:
        del candidate
        supervisor = _FakeSupervisor(fail_run=True)
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
    await controller.start()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    snapshot = controller.snapshot()
    assert snapshot.state is RuntimeState.ERROR
    assert snapshot.last_error == "synthetic supervisor failure"
    assert controller._supervisor is None
    assert controller._supervisor_task is None

    created[0]._snapshot = SupervisorSnapshot(
        state=RuntimeState.LIVE,
        last_error="stale diagnostic",
    )
    sticky = controller.snapshot()
    assert sticky.state is RuntimeState.ERROR
    assert sticky.last_error == "synthetic supervisor failure"
    await controller.close()


@pytest.mark.asyncio
async def test_recovering_diagnostic_is_non_terminal_and_clears_when_live() -> None:
    created: list[_FakeSupervisor] = []

    def factory(candidate: IngestionSettings) -> _FakeSupervisor:
        del candidate
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
    await controller.start()
    await created[0].run_started.wait()

    created[0]._snapshot = SupervisorSnapshot(
        state=RuntimeState.RECOVERING,
        last_error="recovery exhausted; retrying",
    )
    recovering = controller.snapshot()
    assert recovering.state is RuntimeState.RECOVERING
    assert recovering.last_error == "recovery exhausted; retrying"

    created[0]._snapshot = SupervisorSnapshot(
        state=RuntimeState.LIVE,
        last_error="stale diagnostic",
    )
    live = controller.snapshot()
    assert live.state is RuntimeState.LIVE
    assert live.last_error is None
    await controller.close()


@pytest.mark.asyncio
async def test_quarantine_is_latched_before_control_gates_without_snapshot() -> None:
    created: list[_QuarantinedSupervisor] = []

    def factory(candidate: IngestionSettings) -> _QuarantinedSupervisor:
        del candidate
        supervisor = _QuarantinedSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
    await controller.start()

    paused = await controller.pause()
    assert paused.state is RuntimeState.ERROR

    for operation in (
        controller.resume,
        controller.reconnect,
        lambda: controller.replace_settings(_settings()),
        lambda: controller.recover(_request()),
        controller.start,
    ):
        with pytest.raises(RuntimeControlConflictError, match="quarantined"):
            await operation()

    await controller.close()
    assert len(created) == 1
    assert controller.snapshot().state is RuntimeState.ERROR
    assert controller.snapshot().last_error is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["reconnect", "replace", "recover"])
async def test_quarantine_discovered_during_stop_blocks_new_supervisor(
    operation: str,
) -> None:
    created: list[_QuarantinesAfterStopSupervisor] = []

    def factory(candidate: IngestionSettings) -> _QuarantinesAfterStopSupervisor:
        del candidate
        supervisor = _QuarantinesAfterStopSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
    await controller.start()
    await created[0].run_started.wait()

    if operation == "reconnect":
        control = controller.reconnect()
    elif operation == "replace":
        control = controller.replace_settings(_settings())
    else:
        control = controller.recover(_request())

    with pytest.raises(RuntimeControlConflictError, match="quarantined"):
        await control

    assert created[0].run_calls == 1
    if operation == "recover":
        assert len(created) == 1
    else:
        assert len(created) == 2
        assert created[1].run_calls == 0
    assert controller.snapshot().state is RuntimeState.ERROR
    await controller.close()


@pytest.mark.asyncio
async def test_manual_recovery_runs_offline_then_restores_running_runtime() -> None:
    created: list[_FakeSupervisor] = []

    def factory(candidate: IngestionSettings) -> _FakeSupervisor:
        del candidate
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
    await controller.start()
    await asyncio.sleep(0)

    snapshot = await controller.recover(_request())

    assert snapshot.desired_state is DesiredRuntimeState.RUNNING
    assert len(created) == 3
    assert created[1].recovery_requests == [_request()]
    await controller.close()


@pytest.mark.asyncio
async def test_manual_recovery_fences_offline_and_fresh_live_generations() -> None:
    trace: list[str] = []
    created: list[_TraceRecoverySupervisor] = []
    barrier = _BlockingQuiescence(trace)

    def factory(_plan: IngestionPlan) -> _TraceRecoverySupervisor:
        trace.append("build")
        supervisor = _TraceRecoverySupervisor(trace)
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
        historical_provider_quiescence=barrier,
    )
    await controller.start()
    await created[0].run_started.wait()
    trace.clear()

    await controller.recover(_request())
    await created[2].run_started.wait()

    assert trace == [
        "stop",
        "run-stop",
        "barrier",
        "build",
        "recovery",
        "barrier",
        "build",
        "run-start",
    ]
    assert barrier.calls == 2
    await controller.close()


@pytest.mark.asyncio
async def test_replace_settings_can_remove_final_asset() -> None:
    created: list[_FakeSupervisor] = []

    def factory(candidate: IngestionSettings) -> _FakeSupervisor:
        del candidate
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
    await controller.start()
    await asyncio.sleep(0)
    snapshot = await controller.replace_settings(_disabled_settings(_settings()))

    assert snapshot.state is RuntimeState.STOPPED
    assert snapshot.desired_state is DesiredRuntimeState.RUNNING
    assert len(created) == 1
    await controller.close()


@pytest.mark.asyncio
async def test_disabling_all_assets_prunes_observability_and_blocks_retired_lane() -> (
    None
):
    observability = IngestionObservability()
    created: list[_ObservabilitySupervisor] = []

    def factory(candidate: IngestionSettings) -> _ObservabilitySupervisor:
        del candidate
        supervisor = _ObservabilitySupervisor()
        created.append(supervisor)
        return supervisor

    settings = _settings()
    controller = RuntimeController(
        settings=settings,
        plan_factory=_plan_factory,
        supervisor_factory=factory,
        observability=observability,
    )
    await controller.start()
    await asyncio.sleep(0)

    observed_close = datetime(2026, 8, 9, 10, 1, tzinfo=UTC)
    observability.record_base_last_close(LANE, observed_close)
    assert observability._base_last_close

    await controller.replace_settings(_disabled_settings(settings))

    assert observability._base_last_close == {}
    observability.record_base_last_close(LANE, observed_close + timedelta(minutes=1))
    assert observability._base_last_close == {}
    assert len(created) == 1
    await controller.close()


@pytest.mark.asyncio
async def test_cancelled_settings_replacement_waits_for_quiescence_before_rollback() -> (
    None
):
    created: list[_FakeSupervisor] = []
    barrier = _BlockingQuiescence()
    barrier.block = True

    def factory(_plan: IngestionPlan) -> _FakeSupervisor:
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    original_settings = _settings()
    controller = RuntimeController(
        settings=original_settings,
        plan_factory=_plan_factory,
        supervisor_factory=factory,
        historical_provider_quiescence=barrier,
    )
    original_plan = controller.plan
    await controller.start()
    await created[0].run_started.wait()

    replacement = asyncio.create_task(
        controller.replace_settings(_settings(target_timeframes=("1h",)))
    )
    await asyncio.wait_for(barrier.entered.wait(), 1)
    assert len(created) == 2
    assert created[1].run_calls == 0

    replacement.cancel()
    deadline = asyncio.get_running_loop().time() + 1
    while barrier.calls < 2:
        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail("rollback did not await a second quiescence barrier")
        await asyncio.sleep(0)
    assert len(created) == 2

    # A second cancellation must not interrupt checkpoint restoration.
    replacement.cancel()
    assert not replacement.done()
    barrier.release.set()
    with pytest.raises(asyncio.CancelledError):
        await replacement

    assert controller.settings == original_settings
    assert controller.plan is original_plan
    assert len(created) == 3
    assert created[2].run_calls == 1
    await controller.close()


@pytest.mark.asyncio
async def test_failed_cancellation_checkpoint_restore_is_terminal_and_not_ready() -> (
    None
):
    created: list[_FakeSupervisor] = []
    barrier = _BlockingQuiescence()
    barrier.block = True

    def factory(_plan: IngestionPlan) -> _FakeSupervisor:
        if len(created) == 2:
            raise RuntimeError("synthetic checkpoint restore build failure")
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    original_settings = _settings()
    controller = RuntimeController(
        settings=original_settings,
        plan_factory=_plan_factory,
        supervisor_factory=factory,
        historical_provider_quiescence=barrier,
    )
    original_plan = controller.plan
    await controller.start()
    await created[0].run_started.wait()

    replacement = asyncio.create_task(
        controller.replace_settings(_settings(target_timeframes=("1h",)))
    )
    await asyncio.wait_for(barrier.entered.wait(), 1)
    assert len(created) == 2

    replacement.cancel()
    deadline = asyncio.get_running_loop().time() + 1
    while barrier.calls < 2:
        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail("rollback did not await a second quiescence barrier")
        await asyncio.sleep(0)

    barrier.release.set()
    with pytest.raises(
        RuntimeError,
        match="cancelled settings replacement could not restore runtime",
    ):
        await replacement

    assert controller.is_started is True
    assert controller.settings is original_settings
    assert controller.plan is original_plan
    assert controller._supervisor is None
    assert controller._supervisor_task is None
    assert controller.snapshot().state is RuntimeState.ERROR
    assert controller.snapshot().last_error == (
        "synthetic checkpoint restore build failure"
    )
    ready = await request(
        create_app(runtime_controller=controller),
        "GET",
        "/health/ready",
    )
    assert ready.status_code == 503
    await controller.close()


@pytest.mark.asyncio
async def test_checkpoint_generation_is_not_reinstalled_before_quiescence() -> None:
    created: list[_FakeSupervisor] = []
    barrier = _BlockingQuiescence()
    barrier.block = True

    def factory(_plan: IngestionPlan) -> _FakeSupervisor:
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    original_settings = _settings()
    controller = RuntimeController(
        settings=original_settings,
        plan_factory=_plan_factory,
        supervisor_factory=factory,
        historical_provider_quiescence=barrier,
    )
    original_plan = controller.plan
    await controller.start()
    await created[0].run_started.wait()
    checkpoint = controller._checkpoint()
    await controller._stop_current_supervisor()

    replacement_settings = _settings(target_timeframes=("1h",))
    replacement_plan = _plan_factory(replacement_settings)
    controller._settings = replacement_settings
    controller._plan = replacement_plan

    restore = asyncio.create_task(controller._restore_runtime_state(checkpoint))
    await asyncio.wait_for(barrier.entered.wait(), 1)
    assert controller.settings is replacement_settings
    assert controller.plan is replacement_plan
    assert len(created) == 1

    barrier.release.set()
    await asyncio.wait_for(restore, 1)
    assert controller.settings is original_settings
    assert controller.plan is original_plan
    assert len(created) == 2
    assert created[1].run_calls == 1
    await controller.close()


@pytest.mark.asyncio
async def test_quiescence_deadline_during_rollback_latches_fatal_without_install() -> (
    None
):
    created: list[_FakeSupervisor] = []
    barrier = _DeadlineAfterCancellationQuiescence()

    def factory(_plan: IngestionPlan) -> _FakeSupervisor:
        supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    original_settings = _settings()
    controller = RuntimeController(
        settings=original_settings,
        plan_factory=_plan_factory,
        supervisor_factory=factory,
        historical_provider_quiescence=barrier,
    )
    original_plan = controller.plan
    await controller.start()
    await created[0].run_started.wait()

    replacement = asyncio.create_task(
        controller.replace_settings(_settings(target_timeframes=("1h",)))
    )
    await asyncio.wait_for(barrier.entered.wait(), 1)
    replacement.cancel()

    with pytest.raises(
        RuntimeError,
        match="cancelled settings replacement could not restore runtime",
    ):
        await replacement

    assert controller.quarantined is True
    assert controller.settings == original_settings
    assert controller.plan is original_plan
    assert len(created) == 2
    assert created[1].run_calls == 0
    assert controller.snapshot().state is RuntimeState.ERROR
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
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
    original_plan = controller.plan
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
    assert controller.plan is original_plan
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

    controller = RuntimeController(
        settings=_settings(),
        plan_factory=_plan_factory,
        supervisor_factory=factory,
    )
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
        assert len(created) == 2
        assert controller.snapshot().state is RuntimeState.STOPPED
    else:
        assert created[2].run_calls == 1

    await controller.close()


@pytest.mark.asyncio
async def test_cancelled_recovery_waits_for_quiescence_before_checkpoint_restore() -> (
    None
):
    created: list[_FakeSupervisor] = []
    recovery_started = asyncio.Event()
    barrier = _RecoveryCancellationQuiescence()

    def factory(_plan: IngestionPlan) -> _FakeSupervisor:
        if len(created) == 1:
            supervisor = _BlockingRecoverySupervisor(recovery_started)
        else:
            supervisor = _FakeSupervisor()
        created.append(supervisor)
        return supervisor

    original_settings = _settings()
    controller = RuntimeController(
        settings=original_settings,
        plan_factory=_plan_factory,
        supervisor_factory=factory,
        historical_provider_quiescence=barrier,
    )
    original_plan = controller.plan
    await controller.start()
    await created[0].run_started.wait()

    recovery = asyncio.create_task(controller.recover(_request()))
    await recovery_started.wait()
    recovery.cancel()
    await asyncio.wait_for(barrier.entered.wait(), 1)

    assert len(created) == 2
    assert created[1].run_calls == 0
    barrier.release.set()
    with pytest.raises(asyncio.CancelledError):
        await recovery

    assert controller.settings == original_settings
    assert controller.plan is original_plan
    assert len(created) == 3
    assert created[2].run_calls == 1
    await controller.close()
