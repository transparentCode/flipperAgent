from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import ClassVar

import pytest

from apps.decision_app.domain.contracts import InputReadCursor, LaneCommitWatermark
from apps.decision_app.domain.market_state import MarketSeriesKey
from apps.decision_app.observability import DecisionObservability
from apps.decision_app.runtime.lifecycle import LifecycleReadResult
from apps.decision_app.runtime.live import (
    DecisionPollResult,
    LanePollResult,
    LiveDecisionRuntime,
)
from apps.decision_app.runtime.service import DecisionRuntimeGeneration, DecisionService
from apps.decision_app.storage.checkpoints import InMemoryCheckpointRepository
from apps.decision_app.storage.market_history import (
    InMemoryCanonicalMarketHistoryRepository,
)
from apps.decision_app.transport.live_input import (
    InputRecordResult,
    InputTransportError,
)
from apps.decision_app.transport.signals import ValkeySignalPublisher
from tests.decision.test_d9b_live_runtime import (
    SIGNAL_GRID,
    SIGNAL_SERIES,
    SR_GRID,
    SR_SERIES,
    _IsolatedSignalClient,
    _LiveInputClient,
    _signal_bar,
    _signal_coordinator,
    _signal_fields,
    _sr_coordinator,
    sr_bar,
    sr_stream_fields,
)
from tests.decision.test_observability import _Meter

NOW = datetime(2026, 8, 14, tzinfo=UTC)


class _Input:
    cursors: ClassVar[dict] = {}
    blocked_streams: ClassVar[dict] = {}


class _Runtime:
    def __init__(self, *, gate: asyncio.Event | None = None, errors=()) -> None:
        self.input = _Input()
        self.lanes = {}
        self.gate = gate
        self.errors = list(errors)
        self.calls = 0
        self.evaluate_flags: list[bool] = []
        self.started = asyncio.Event()

    async def poll_once(self, *, evaluate_lanes: bool = True) -> DecisionPollResult:
        self.calls += 1
        self.evaluate_flags.append(evaluate_lanes)
        self.started.set()
        if self.errors:
            error = self.errors.pop(0)
            raise error
        if self.gate is not None:
            await self.gate.wait()
        return DecisionPollResult(input_results=(), lane_results={}, cursors={})


class _ObservableRuntime:
    def __init__(
        self,
        *,
        lane_id: str,
        asset: str,
        timeframe: str,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.gate = gate
        self.calls = 0
        self.started = asyncio.Event()
        self.configure(lane_id=lane_id, asset=asset, timeframe=timeframe)

    def configure(self, *, lane_id: str, asset: str, timeframe: str) -> None:
        key = MarketSeriesKey(
            asset=asset,
            venue="binance",
            instrument_id=f"{asset}-PERP",
            timeframe=timeframe,
        )
        self.key = key
        cursor = InputReadCursor(
            stream_key=f"stream:{asset}:{timeframe}",
            latest_stream_id="1-0",
            latest_market_as_of=NOW,
        )
        self.input = SimpleNamespace(
            cursors={cursor.stream_key: cursor},
            blocked_streams={},
        )
        self.input.cursor_for = lambda requested: cursor
        self.lanes = {
            lane_id: SimpleNamespace(
                lane=SimpleNamespace(asset=asset, decision_timeframe=timeframe),
                status="LIVE",
                reason=None,
                pending_trigger_cutoff=None,
                finalizer=SimpleNamespace(
                    watermark=LaneCommitWatermark(
                        lane_id=lane_id,
                        latest_market_as_of=NOW,
                        last_disposition="published",
                    )
                ),
            )
        }

    async def poll_once(self, *, evaluate_lanes: bool = True) -> DecisionPollResult:
        del evaluate_lanes
        self.calls += 1
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        return DecisionPollResult(input_results=(), lane_results={}, cursors={})


class _ResultRuntime:
    def __init__(self, results: list[DecisionPollResult]) -> None:
        self.input = _Input()
        self.lanes = {}
        self.results = list(results)
        self.calls = 0
        self.started = asyncio.Event()

    async def poll_once(self, *, evaluate_lanes: bool = True) -> DecisionPollResult:
        self.calls += 1
        self.started.set()
        if self.results:
            return self.results.pop(0)
        await asyncio.sleep(0)
        return DecisionPollResult(input_results=(), lane_results={}, cursors={})


class _IndependentLaneRuntime:
    def __init__(self) -> None:
        self.calls = 0
        self.release = asyncio.Event()
        self.input = SimpleNamespace(
            cursors={
                "series-a": SimpleNamespace(
                    latest_stream_id="1-0", latest_market_as_of=NOW
                ),
                "series-b": SimpleNamespace(
                    latest_stream_id="1-0", latest_market_as_of=NOW
                ),
            },
            blocked_streams={"series-a": "causal gap"},
        )
        self.lanes = {
            "lane-a": SimpleNamespace(
                status="RECONSTRUCTION_REQUIRED",
                reason="causal gap",
                pending_trigger_cutoff=None,
                finalizer=SimpleNamespace(
                    watermark=SimpleNamespace(
                        latest_market_as_of=NOW,
                        last_disposition="COMMITTED",
                    )
                ),
            ),
            "lane-b": SimpleNamespace(
                status="LIVE",
                reason=None,
                pending_trigger_cutoff=None,
                finalizer=SimpleNamespace(
                    watermark=SimpleNamespace(
                        latest_market_as_of=NOW,
                        last_disposition="COMMITTED",
                    )
                ),
            ),
        }

    async def poll_once(self, *, evaluate_lanes: bool = True) -> DecisionPollResult:
        self.calls += 1
        self.input.cursors["series-b"].latest_stream_id = "2-0"
        self.lanes["lane-b"].finalizer.watermark.latest_market_as_of = NOW
        if self.calls >= 2:
            await self.release.wait()
        return DecisionPollResult(
            input_results=(
                InputRecordResult(
                    stream_key="series-a",
                    stream_id="2-0",
                    series_key=None,
                    market_as_of=None,
                    disposition="RECONSTRUCTION_REQUIRED",
                    reason="causal gap",
                ),
            ),
            lane_results={
                "lane-a": LanePollResult(
                    lane_id="lane-a",
                    status="RECONSTRUCTION_REQUIRED",
                    reason="causal gap",
                ),
                "lane-b": LanePollResult(
                    lane_id="lane-b",
                    status="LIVE",
                    trigger_cutoff=NOW,
                    finalization_status="COMMITTED",
                ),
            },
            cursors={},
        )


class _Reader:
    def __init__(self, result: LifecycleReadResult) -> None:
        self.cursor = result.cursor
        self.result = result
        self.reads = 0

    async def read_once(self) -> LifecycleReadResult:
        self.reads += 1
        result, self.result = self.result, LifecycleReadResult(cursor=self.cursor)
        self.cursor = result.cursor
        await asyncio.sleep(0)
        return result


class _FailingReader:
    cursor = "0-0"

    async def read_once(self) -> LifecycleReadResult:
        raise RuntimeError("lifecycle transport unavailable")


def _generation(number: int, runtime: _Runtime) -> DecisionRuntimeGeneration:
    startup = SimpleNamespace(
        snapshot=SimpleNamespace(status="STARTUP_READY", active_manifest_assets=()),
        decision_plan=SimpleNamespace(lanes=()),
    )
    return DecisionRuntimeGeneration(
        generation_id=number,
        created_at=NOW,
        startup=startup,
        live_runtime=runtime,
    )


def _observable_generation(
    number: int,
    runtime: _ObservableRuntime,
) -> DecisionRuntimeGeneration:
    startup = SimpleNamespace(
        snapshot=SimpleNamespace(
            status="STARTUP_READY",
            active_manifest_assets=(runtime.key.asset,),
            series_positions={runtime.key: object()},
        ),
        decision_plan=SimpleNamespace(lanes=(runtime.key,)),
    )
    return DecisionRuntimeGeneration(
        generation_id=number,
        created_at=NOW,
        startup=startup,
        live_runtime=runtime,
    )


async def _wait_until(predicate, *, steps: int = 200) -> None:
    for _ in range(steps):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition was not reached")


@pytest.mark.asyncio
async def test_pause_waits_for_current_poll_and_resume_rebuilds() -> None:
    gate = asyncio.Event()
    runtimes: list[_Runtime] = []

    async def factory(*, reason: str, generation_id: int):
        del reason
        runtime = _Runtime(gate=gate if generation_id == 1 else None)
        runtimes.append(runtime)
        return _generation(generation_id, runtime)

    service = DecisionService(
        generation_factory=factory, block_ms=1, now_fn=lambda: NOW
    )
    await service.start()
    await runtimes[0].started.wait()
    pause_task = asyncio.create_task(service.pause())
    await asyncio.sleep(0)
    assert pause_task.done() is False
    gate.set()
    paused = await pause_task
    assert paused.service_state == "PAUSED"
    assert runtimes[0].calls >= 1
    assert runtimes[0].evaluate_flags[-1] is False

    resumed = await service.resume()
    assert resumed.service_state == "RUNNING"
    assert resumed.generation_id == 2
    assert len(runtimes) == 2
    await _wait_until(lambda: runtimes[1].calls >= 1)
    await service.stop()
    assert service.service_state == "STOPPED"


@pytest.mark.asyncio
async def test_paused_market_loop_continues_bounded_input_without_lane_evaluation() -> (
    None
):
    runtime = _Runtime()

    async def factory(*, reason: str, generation_id: int):
        del reason
        return _generation(generation_id, runtime)

    service = DecisionService(
        generation_factory=factory,
        block_ms=1,
        now_fn=lambda: NOW,
    )
    await service.start()
    await runtime.started.wait()

    paused = await service.pause()
    calls_at_pause = runtime.calls
    await asyncio.sleep(0.08)

    assert paused.service_state == "PAUSED"
    assert runtime.calls > calls_at_pause
    assert runtime.evaluate_flags[-1] is False
    await service.stop()


@pytest.mark.asyncio
async def test_pause_serializes_before_concurrent_reconnect() -> None:
    gate = asyncio.Event()
    runtimes: list[_Runtime] = []

    async def factory(*, reason: str, generation_id: int):
        del reason
        runtime = _Runtime(gate=gate if generation_id == 1 else None)
        runtimes.append(runtime)
        return _generation(generation_id, runtime)

    service = DecisionService(
        generation_factory=factory, block_ms=1, now_fn=lambda: NOW
    )
    await service.start()
    await runtimes[0].started.wait()

    pause_task = asyncio.create_task(service.pause())
    await _wait_until(lambda: service.desired_state == "PAUSED")
    reconnect_task = asyncio.create_task(service.reconnect())
    await asyncio.sleep(0)
    assert reconnect_task.done() is False

    gate.set()
    paused = await pause_task
    assert paused.service_state == "PAUSED"
    assert paused.desired_state == "PAUSED"
    assert paused.generation_id == 1
    paused_calls = runtimes[0].calls
    for _ in range(5):
        await asyncio.sleep(0)
    assert runtimes[0].calls >= paused_calls
    assert runtimes[0].evaluate_flags[-1] is False

    resumed = await reconnect_task
    assert resumed.service_state == "RUNNING"
    assert resumed.desired_state == "RUNNING"
    assert resumed.generation_id == 2
    await service.stop()


@pytest.mark.asyncio
async def test_reconnect_serializes_before_concurrent_pause() -> None:
    gate = asyncio.Event()
    runtimes: list[_Runtime] = []

    async def factory(*, reason: str, generation_id: int):
        del reason
        runtime = _Runtime(gate=gate if generation_id == 1 else None)
        runtimes.append(runtime)
        return _generation(generation_id, runtime)

    service = DecisionService(
        generation_factory=factory, block_ms=1, now_fn=lambda: NOW
    )
    await service.start()
    await runtimes[0].started.wait()

    reconnect_task = asyncio.create_task(service.reconnect())
    await _wait_until(lambda: service.service_state == "REBUILDING")
    pause_task = asyncio.create_task(service.pause())
    await asyncio.sleep(0)
    assert pause_task.done() is False

    gate.set()
    reconnected = await reconnect_task
    assert reconnected.service_state == "RUNNING"
    assert reconnected.desired_state == "RUNNING"
    assert reconnected.generation_id == 2

    paused = await pause_task
    assert paused.service_state == "PAUSED"
    assert paused.desired_state == "PAUSED"
    assert paused.generation_id == 2
    paused_calls = runtimes[1].calls
    for _ in range(5):
        await asyncio.sleep(0)
    assert runtimes[1].calls > paused_calls
    assert runtimes[1].evaluate_flags[-1] is False
    await service.stop()


@pytest.mark.asyncio
async def test_stop_waits_for_current_poll_and_starts_no_next_poll() -> None:
    gate = asyncio.Event()
    runtime = _Runtime(gate=gate)

    async def factory(*, reason: str, generation_id: int):
        del reason
        return _generation(generation_id, runtime)

    service = DecisionService(
        generation_factory=factory, block_ms=1, now_fn=lambda: NOW
    )
    await service.start()
    await runtime.started.wait()

    stop_task = asyncio.create_task(service.stop())
    await asyncio.sleep(0)
    assert stop_task.done() is False
    assert runtime.calls == 1
    gate.set()
    stopped = await stop_task
    assert stopped.service_state == "STOPPED"
    assert runtime.calls == 1


@pytest.mark.asyncio
async def test_service_observability_hooks_record_poll_rebuild_and_generation_replace() -> (
    None
):
    meter = _Meter()
    observability = DecisionObservability(
        meter=meter,
        timeframe_grid=SIGNAL_GRID,
        now_fn=lambda: NOW,
    )
    first_gate = asyncio.Event()
    first = _ObservableRuntime(
        lane_id="BTCUSDT:momentum_1h",
        asset="BTCUSDT",
        timeframe="1h",
        gate=first_gate,
    )
    second = _ObservableRuntime(
        lane_id="ETHUSDT:momentum_1h",
        asset="ETHUSDT",
        timeframe="1h",
    )

    async def factory(*, reason: str, generation_id: int):
        del reason
        assert generation_id == 2
        return _observable_generation(generation_id, second)

    service = DecisionService(
        generation_factory=factory,
        block_ms=1,
        now_fn=lambda: NOW,
        observability=observability,
    )
    await service.start(generation=_observable_generation(1, first))
    await first.started.wait()

    reconnect_task = asyncio.create_task(service.reconnect())
    await asyncio.sleep(0)
    assert reconnect_task.done() is False
    first_gate.set()
    reconnected = await reconnect_task
    assert reconnected.generation_id == 2
    await service.stop()

    assert len(meter.instruments["decision.poll.duration_ms"].records) >= 1
    assert meter.instruments["decision.rebuild.total"].adds == [
        (1, {"outcome": "success"})
    ]
    assert len(meter.instruments["decision.rebuild.duration_ms"].records) == 1
    lane_observations = tuple(
        meter.instruments["decision.lane.state"].callbacks[0](None)
    )
    assert [item.attributes["lane"] for item in lane_observations] == [
        "ETHUSDT:momentum_1h"
    ]


@pytest.mark.asyncio
async def test_service_observability_records_failed_rebuild() -> None:
    meter = _Meter()
    observability = DecisionObservability(
        meter=meter,
        timeframe_grid=SIGNAL_GRID,
        now_fn=lambda: NOW,
    )
    runtime = _ObservableRuntime(
        lane_id="BTCUSDT:momentum_1h",
        asset="BTCUSDT",
        timeframe="1h",
    )

    async def factory(*, reason: str, generation_id: int):
        del reason, generation_id
        raise RuntimeError("rebuild unavailable")

    service = DecisionService(
        generation_factory=factory,
        block_ms=1,
        now_fn=lambda: NOW,
        observability=observability,
    )
    await service.start(generation=_observable_generation(1, runtime))
    failed = await service.reconnect()
    assert failed.service_state == "ERROR"
    await service.stop()

    assert meter.instruments["decision.rebuild.total"].adds == [
        (1, {"outcome": "failure"})
    ]
    assert len(meter.instruments["decision.rebuild.duration_ms"].records) == 1


@pytest.mark.asyncio
async def test_reconnect_during_poll_does_not_start_old_generation_again() -> None:
    gate = asyncio.Event()
    runtimes: list[_Runtime] = []

    async def factory(*, reason: str, generation_id: int):
        del reason
        runtime = _Runtime(gate=gate if generation_id == 1 else None)
        runtimes.append(runtime)
        return _generation(generation_id, runtime)

    service = DecisionService(
        generation_factory=factory, block_ms=1, now_fn=lambda: NOW
    )
    await service.start()
    await runtimes[0].started.wait()
    reconnect_task = asyncio.create_task(service.reconnect())
    await asyncio.sleep(0)
    assert reconnect_task.done() is False
    gate.set()
    result = await reconnect_task
    assert result.generation_id == 2
    assert runtimes[0].calls == 1
    await service.stop()


@pytest.mark.asyncio
async def test_lifecycle_notification_coalesces_to_one_generation_rebuild() -> None:
    reader = _Reader(
        LifecycleReadResult(
            cursor="2-0",
            event_ids=("1-0", "2-0"),
            relevant_events=(object(), object()),  # type: ignore[arg-type]
        )
    )
    runtimes: list[_Runtime] = []

    async def factory(*, reason: str, generation_id: int):
        assert reason
        runtime = _Runtime()
        runtimes.append(runtime)
        return _generation(generation_id, runtime)

    service = DecisionService(
        generation_factory=factory,
        lifecycle_reader=reader,
        block_ms=1,
        now_fn=lambda: NOW,
    )
    await service.start()
    await _wait_until(
        lambda: service.generation is not None and service.generation.generation_id == 2
    )
    assert len(runtimes) == 2
    await service.stop()


@pytest.mark.asyncio
async def test_transport_error_keeps_generation_and_does_not_rebuild() -> None:
    runtime = _Runtime(errors=(InputTransportError("temporary"),))

    async def factory(*, reason: str, generation_id: int):
        del reason
        return _generation(generation_id, runtime)

    service = DecisionService(
        generation_factory=factory, block_ms=1, now_fn=lambda: NOW
    )
    await service.start()
    await _wait_until(lambda: runtime.calls >= 2)
    assert service.generation is not None
    assert service.generation.generation_id == 1
    await service.stop()


@pytest.mark.asyncio
async def test_poll_telemetry_failure_does_not_mask_transport_error() -> None:
    runtime = _Runtime(errors=(InputTransportError("original transport failure"),))
    observability = DecisionObservability(
        meter=_Meter(),
        timeframe_grid=SIGNAL_GRID,
        now_fn=lambda: NOW,
    )

    def fail_telemetry(*_args, **_kwargs) -> None:
        raise RuntimeError("synthetic poll telemetry failure")

    observability.record_poll_duration = fail_telemetry

    async def factory(*, reason: str, generation_id: int):
        del reason
        return _generation(generation_id, runtime)

    service = DecisionService(
        generation_factory=factory,
        block_ms=1,
        now_fn=lambda: NOW,
        observability=observability,
    )
    await service.start()
    await _wait_until(lambda: service.service_state == "DEGRADED")

    snapshot = service.snapshot()
    assert snapshot.last_error == (
        "market input transport failed: original transport failure"
    )
    assert snapshot.generation_id == 1
    await service.stop()


@pytest.mark.asyncio
async def test_service_observability_failures_do_not_change_transitions() -> None:
    first = _ObservableRuntime(
        lane_id="BTCUSDT:momentum_1h",
        asset="BTCUSDT",
        timeframe="1h",
    )
    second = _ObservableRuntime(
        lane_id="ETHUSDT:momentum_1h",
        asset="ETHUSDT",
        timeframe="1h",
    )
    observability = DecisionObservability(
        meter=_Meter(),
        timeframe_grid=SIGNAL_GRID,
        now_fn=lambda: NOW,
    )

    def fail_telemetry(*_args, **_kwargs) -> None:
        raise RuntimeError("synthetic lifecycle telemetry failure")

    for hook in (
        "set_service_state",
        "replace_generation",
        "clear_generation",
        "refresh_runtime",
        "record_rebuild",
    ):
        setattr(observability, hook, fail_telemetry)

    async def factory(*, reason: str, generation_id: int):
        del reason
        return _observable_generation(generation_id, second)

    service = DecisionService(
        generation_factory=factory,
        block_ms=1,
        now_fn=lambda: NOW,
        observability=observability,
    )
    await service.start(generation=_observable_generation(1, first))
    reconnected = await service.reconnect()
    assert reconnected.service_state == "RUNNING"
    assert reconnected.generation_id == 2
    assert service.generation is not None
    assert service.generation.generation_id == 2
    await service.stop()


@pytest.mark.asyncio
async def test_paused_state_dominates_lifecycle_transport_degradation() -> None:
    runtime = _Runtime()

    async def factory(*, reason: str, generation_id: int):
        del reason
        return _generation(generation_id, runtime)

    service = DecisionService(
        generation_factory=factory,
        lifecycle_reader=_FailingReader(),
        block_ms=1,
        now_fn=lambda: NOW,
    )
    await service.start()
    paused = await service.pause()
    assert paused.service_state == "PAUSED"
    assert paused.desired_state == "PAUSED"
    assert paused.ready is False

    await _wait_until(
        lambda: (
            service.snapshot().last_error
            == "lifecycle input failed: lifecycle transport unavailable"
        )
    )
    after_error = service.snapshot()
    assert after_error.service_state == "PAUSED"
    assert after_error.desired_state == "PAUSED"
    assert after_error.ready is False
    await service.stop()


@pytest.mark.asyncio
async def test_control_states_are_not_overwritten_by_completed_poll_results() -> None:
    runtime = _Runtime()

    async def factory(*, reason: str, generation_id: int):
        del reason
        return _generation(generation_id, runtime)

    service = DecisionService(generation_factory=factory, now_fn=lambda: NOW)
    await service.start()
    result = DecisionPollResult(input_results=(), lane_results={}, cursors={})
    for state in ("REBUILDING", "STOPPING", "ERROR"):
        service._service_state = state
        service._classify_poll_result(result)
        assert service.service_state == state
        assert service.snapshot().ready is False
    await service.stop()


@pytest.mark.asyncio
async def test_reconstruction_failure_keeps_generation_and_lifecycle_rebuild_available() -> (
    None
):
    generated: list[str] = []

    async def factory(*, reason: str, generation_id: int):
        generated.append(reason)
        return _generation(generation_id, _Runtime())

    service = DecisionService(generation_factory=factory, now_fn=lambda: NOW)
    await service.start()
    service._classify_poll_result(
        DecisionPollResult(
            input_results=(),
            lane_results={
                "lane": LanePollResult(
                    lane_id="lane",
                    status="RECONSTRUCTION_REQUIRED",
                    reason="causal gap",
                )
            },
            cursors={},
        )
    )
    assert service.generation is not None
    assert service.generation.generation_id == 1
    assert service.service_state == "DEGRADED"
    assert service._rebuild_requested is False

    await service.pause()
    async with service._transition_lock:
        service._rebuild_requested = True
        service._rebuild_reason = "current manifest changed"
        service._rebuild_source = "LIFECYCLE_RECONCILIATION"
        await service._rebuild_locked("current manifest changed")

    assert service.generation is not None
    assert service.generation.generation_id == 2
    assert generated == [
        "initial",
        "current manifest changed",
    ]
    await service.stop()


@pytest.mark.asyncio
async def test_reconstruction_failure_does_not_stop_independent_lane_progress() -> None:
    runtime = _IndependentLaneRuntime()
    generated: list[int] = []

    async def factory(*, reason: str, generation_id: int):
        del reason
        generated.append(generation_id)
        return _generation(generation_id, runtime)

    service = DecisionService(generation_factory=factory, now_fn=lambda: NOW)
    await service.start()
    await _wait_until(lambda: runtime.calls >= 2)

    snapshot = service.snapshot()
    assert generated == [1]
    assert snapshot.generation_id == 1
    assert snapshot.service_state == "DEGRADED"
    assert snapshot.inputs["series-a"]["latest_stream_id"] == "1-0"
    assert snapshot.inputs["series-b"]["latest_stream_id"] == "2-0"
    assert snapshot.lanes["lane-a"]["watermark"]["latest_market_as_of"] == NOW
    assert snapshot.lanes["lane-b"]["watermark"]["last_disposition"] == "COMMITTED"

    runtime.release.set()
    await service.stop()


@pytest.mark.asyncio
async def test_service_real_sr_no_signal_commits_and_caches_checkpoint_evidence() -> (
    None
):
    checkpoints = InMemoryCheckpointRepository()
    history = InMemoryCanonicalMarketHistoryRepository(
        {SR_SERIES: tuple(sr_bar(index) for index in range(50))},
        timeframe_grid=SR_GRID,
    )
    stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=49,
        field_factory=sr_stream_fields,
    )
    stream.pending.append(("50-0", sr_stream_fields(50)))

    async def factory(*, reason: str, generation_id: int):
        del reason
        startup = await _sr_coordinator(history, checkpoints, stream).start()
        runtime = LiveDecisionRuntime(
            startup=startup,
            timeframe_grid=SR_GRID,
            stream_client=stream,
            history_repository=history,
            checkpoint_repository=checkpoints,
            now_fn=lambda: NOW,
        )
        return DecisionRuntimeGeneration(
            generation_id=generation_id,
            created_at=NOW,
            startup=startup,
            live_runtime=runtime,
        )

    service = DecisionService(
        generation_factory=factory, block_ms=1, now_fn=lambda: NOW
    )
    await service.start()

    async def checkpoint_at_live_cutoff() -> bool:
        generation = service.generation
        if generation is None:
            return False
        runtime_identity = next(iter(generation.startup.runtimes.values())).identity
        checkpoint = await checkpoints.load(runtime_identity)
        return (
            checkpoint is not None
            and checkpoint.market_as_of == sr_bar(50).market_as_of
        )

    for _ in range(300):
        if await checkpoint_at_live_cutoff():
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("SR service did not reach the live checkpoint")

    snapshot = service.snapshot()
    transaction = snapshot.lanes["BTCUSDT:main"]["last_transaction"]
    assert transaction["policy_status"] == "NO_SIGNAL"
    assert transaction["finalization_status"] == "COMMITTED"
    assert transaction["checkpoint_result"] == "UPDATED"
    assert snapshot.service_state == "RUNNING"
    await service.stop()


@pytest.mark.asyncio
async def test_service_isolated_signal_publishes_and_commits() -> None:
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))},
        timeframe_grid=SIGNAL_GRID,
    )
    stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=2,
        field_factory=_signal_fields,
    )
    stream.pending.append(("3-0", _signal_fields(3)))
    publisher_client = _IsolatedSignalClient()

    async def factory(*, reason: str, generation_id: int):
        del reason
        startup = await _signal_coordinator(history, stream).start()
        runtime = LiveDecisionRuntime(
            startup=startup,
            timeframe_grid=SIGNAL_GRID,
            stream_client=stream,
            history_repository=history,
            signal_publisher=ValkeySignalPublisher(publisher_client),
            now_fn=lambda: NOW,
        )
        return DecisionRuntimeGeneration(
            generation_id=generation_id,
            created_at=NOW,
            startup=startup,
            live_runtime=runtime,
        )

    service = DecisionService(
        generation_factory=factory, block_ms=1, now_fn=lambda: NOW
    )
    await service.start()
    await _wait_until(lambda: bool(publisher_client.entries))

    transaction = service.snapshot().lanes["BTCUSDT:main"]["last_transaction"]
    assert transaction["publication_outcome"] == "PUBLISHED"
    assert transaction["finalization_status"] == "COMMITTED"
    assert tuple(publisher_client.entries["signals:BTCUSDT:1h"]) == (
        f"{int(_signal_bar(3).market_as_of.timestamp() * 1000)}-0",
    )
    await service.stop()


def _input_failure(disposition: str) -> DecisionPollResult:
    return DecisionPollResult(
        input_results=(
            InputRecordResult(
                stream_key="stream:ohlcv:ingestion:test:asset:1h",
                stream_id="1-0",
                series_key=None,
                market_as_of=None,
                disposition=disposition,
                reason="synthetic input failure",
            ),
        ),
        lane_results={},
        cursors={},
    )


@pytest.mark.asyncio
async def test_reconstruction_stays_degraded_but_hard_faults_do_not_loop() -> None:
    reconstruction_result = DecisionPollResult(
        input_results=(),
        lane_results={
            "lane": LanePollResult(
                lane_id="lane",
                status="RECONSTRUCTION_REQUIRED",
                reason="synthetic gap",
            )
        },
        cursors={},
    )
    reconstruction_runtime = _ResultRuntime([reconstruction_result] * 10)
    generated: list[_ResultRuntime] = []

    async def rebuild_factory(*, reason: str, generation_id: int):
        del reason
        runtime = reconstruction_runtime
        generated.append(runtime)
        return _generation(generation_id, runtime)

    service = DecisionService(
        generation_factory=rebuild_factory,
        block_ms=1,
        now_fn=lambda: NOW,
    )
    await service.start()
    await _wait_until(lambda: reconstruction_runtime.calls >= 2)
    assert service.generation is not None
    assert service.generation.generation_id == 1
    assert len(generated) == 1
    assert service.service_state == "DEGRADED"
    await service.stop()

    for failure in ("MALFORMED", "CONFLICT"):
        runtime = _ResultRuntime([_input_failure(failure)])
        generated_hard: list[_ResultRuntime] = []

        async def hard_factory(
            *,
            reason: str,
            generation_id: int,
            runtime=runtime,
            generated_hard=generated_hard,
        ):
            del reason
            generated_hard.append(runtime)
            return _generation(generation_id, runtime)

        hard_service = DecisionService(
            generation_factory=hard_factory,
            block_ms=1,
            now_fn=lambda: NOW,
        )
        await hard_service.start()
        await _wait_until(lambda runtime=runtime: runtime.calls >= 2)
        assert len(generated_hard) == 1
        assert hard_service.service_state == "DEGRADED"
        await hard_service.stop()

    halted_runtime = _ResultRuntime(
        [
            DecisionPollResult(
                input_results=(),
                lane_results={
                    "lane": LanePollResult(
                        lane_id="lane",
                        status="HALTED",
                        reason="synthetic publication halt",
                    )
                },
                cursors={},
            )
        ]
    )
    halted_generations: list[_ResultRuntime] = []

    async def halted_factory(*, reason: str, generation_id: int):
        del reason
        halted_generations.append(halted_runtime)
        return _generation(generation_id, halted_runtime)

    halted_service = DecisionService(
        generation_factory=halted_factory,
        block_ms=1,
        now_fn=lambda: NOW,
    )
    await halted_service.start()
    await _wait_until(lambda: halted_runtime.calls >= 2)
    assert len(halted_generations) == 1
    assert halted_service.service_state == "DEGRADED"
    await halted_service.stop()
