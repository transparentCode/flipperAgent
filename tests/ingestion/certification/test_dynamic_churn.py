from __future__ import annotations

import asyncio
import gc
import weakref
from datetime import UTC, datetime, timedelta

import pytest

from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.runtime.controller import RuntimeController
from apps.ingestion_app.services.recovery import RecoveryEngine
from apps.ingestion_app.storage.repository import CandleCommitStatus

from .conftest import (
    BASE_DURATION,
    ActiveMeter,
    ControlledRepository,
    FakeHistoricalProvider,
    FakeSupervisor,
    RecordingHTF,
    RecordingIngestion,
    canonical,
    observation,
    synthetic_lanes,
    synthetic_settings,
    yield_control,
)

RECOVERY_START = datetime(2026, 1, 1, tzinfo=UTC)


class _RecoveryIngestion(RecordingIngestion):
    def __init__(self, repository: ControlledRepository) -> None:
        super().__init__()
        self.repository = repository

    async def commit_observation(self, observed):
        status = await super().commit_observation(observed)
        if status is CandleCommitStatus.INSERTED:
            self.repository.rows[(observed.lane, observed.open_time)] = canonical(
                observed
            )
        return status


def _recovery_request(lane, offset: int = 0) -> RecoveryRequest:
    since = RECOVERY_START + offset * BASE_DURATION
    return RecoveryRequest(
        lane=lane,
        since=since,
        until=since + BASE_DURATION,
        reason="certification_dynamic_state",
    )


def _active_supervisor_tasks() -> list[asyncio.Task[object]]:
    return [
        task
        for task in asyncio.all_tasks()
        if task.get_name() == "ingestion-supervisor" and not task.done()
    ]


@pytest.mark.asyncio
async def test_five_500_lane_settings_generations_replace_without_active_leaks() -> (
    None
):
    created_refs: list[weakref.ReferenceType[FakeSupervisor]] = []
    constructed_supervisors = 0
    constructed_external_resources = 0

    def factory(settings):
        nonlocal constructed_supervisors
        constructed_supervisors += 1
        supervisor = FakeSupervisor(settings, [])
        created_refs.append(weakref.ref(supervisor))
        return supervisor

    controller = RuntimeController(
        settings=synthetic_settings(500, generation=0),
        supervisor_factory=factory,
    )
    await controller.start()
    assert controller.is_started
    await asyncio.wait_for(created_refs[0]().started.wait(), timeout=1)  # type: ignore[union-attr]

    observed_generations: list[int] = []
    for generation in range(1, 6):
        previous = created_refs[-1]()
        candidate = synthetic_settings(500, generation=generation)
        await controller.replace_settings(candidate)
        current = created_refs[-1]()
        assert previous is not None
        assert previous.closed
        assert current is not None
        await asyncio.wait_for(current.started.wait(), timeout=1)
        assert controller.settings is candidate
        assert controller.enabled_asset_count == 500
        assert len(_active_supervisor_tasks()) == 1
        observed_generations.append(generation)
        assert constructed_external_resources == 0

    assert observed_generations == [1, 2, 3, 4, 5]
    assert constructed_supervisors == 6

    await controller.close()
    assert not _active_supervisor_tasks()
    del previous, current
    await yield_control()
    await yield_control()
    gc.collect()
    assert all(reference() is None for reference in created_refs[:-1])
    assert created_refs[-1]() is None


@pytest.mark.asyncio
async def test_recovery_engine_lane_lock_state_is_reclaimed_across_generations() -> (
    None
):
    """Certify that completed historical lane entries are reclaimed."""
    settings = synthetic_settings(500)
    repository = ControlledRepository()
    ingestion = _RecoveryIngestion(repository)
    htf = RecordingHTF()
    provider = FakeHistoricalProvider(
        "binance_native",
        lambda lane, since, until: (observation(lane, since),),
    )
    recovery_engine = RecoveryEngine(
        providers={"binance_native": provider},
        repository=repository,  # type: ignore[arg-type]
        ingestion_service=ingestion,  # type: ignore[arg-type]
        htf_service=htf,  # type: ignore[arg-type]
        max_concurrency=settings.recovery.max_concurrency,
        page_limit=settings.recovery.page_limit,
        max_attempts_per_provider=settings.recovery.max_attempts_per_provider,
        retry_backoff_seconds=settings.recovery.retry_backoff_seconds,
        rest_finalization_grace_seconds=settings.recovery.rest_finalization_grace_seconds,
        now_fn=lambda: RECOVERY_START + timedelta(hours=1),
    )

    retained_counts: list[int] = []
    total_completed = 0
    observed_concurrency: list[int] = []
    for generation in range(5):
        generation_settings = synthetic_settings(500, generation=generation)
        lanes = synthetic_lanes(generation_settings)
        gate = asyncio.Event()
        meter = ActiveMeter(target=settings.recovery.max_concurrency, gate=gate)
        provider.meter = meter
        requests = [_recovery_request(lane) for lane in lanes]
        tasks = [
            asyncio.create_task(
                recovery_engine.recover(
                    request,
                    base_timeframe=generation_settings.base_timeframe,
                    base_duration=BASE_DURATION,
                    provider_order=("binance_native",),
                    provider_symbols={"binance_native": "SYNTHETIC"},
                    target_durations={},
                    alignment_origin=generation_settings.calendar.alignment_origin,
                )
            )
            for request in requests
        ]
        await asyncio.wait_for(meter.ready.wait(), timeout=1)
        assert meter.maximum == settings.recovery.max_concurrency
        meter.gate.set()
        await asyncio.gather(*tasks)
        # Exercise same-lane serialization without adding another lane key.
        first_lane = lanes[0]
        await asyncio.gather(
            *(
                recovery_engine.recover(
                    _recovery_request(first_lane, offset),
                    base_timeframe=generation_settings.base_timeframe,
                    base_duration=BASE_DURATION,
                    provider_order=("binance_native",),
                    provider_symbols={"binance_native": "SYNTHETIC"},
                    target_durations={},
                    alignment_origin=generation_settings.calendar.alignment_origin,
                )
                for offset in (1, 2)
            )
        )
        total_completed += 502
        retained_counts.append(len(recovery_engine._lane_locks))
        observed_concurrency.append(meter.maximum)

    assert total_completed == 5 * 502
    assert len(provider.calls) == total_completed
    assert len(ingestion.observations) == total_completed
    assert len(repository.rows) == total_completed
    assert retained_counts == [0, 0, 0, 0, 0]
    assert observed_concurrency == [settings.recovery.max_concurrency] * 5
    assert provider.max_active_by_lane[synthetic_lanes(settings)[0]] == 1


@pytest.mark.asyncio
async def test_dynamic_generation_replacement_preserves_desired_paused_state() -> None:
    created: list[FakeSupervisor] = []

    def factory(settings):
        return FakeSupervisor(settings, created)

    controller = RuntimeController(
        settings=synthetic_settings(500, generation=0),
        supervisor_factory=factory,
    )
    await controller.start()
    await asyncio.wait_for(created[-1].started.wait(), timeout=1)
    await controller.pause()
    candidate = synthetic_settings(500, generation=1)
    await controller.replace_settings(candidate)

    assert controller.snapshot().desired_state.value == "paused"
    assert controller.snapshot().state.value == "stopped"
    assert len(_active_supervisor_tasks()) == 0

    await controller.resume()
    await asyncio.wait_for(created[-1].started.wait(), timeout=1)
    assert len(_active_supervisor_tasks()) == 1
    await controller.close()
    assert not _active_supervisor_tasks()


@pytest.mark.asyncio
async def test_task_audit_excludes_current_test_task_and_has_no_v2_orphans() -> None:
    baseline = {
        task
        for task in asyncio.all_tasks()
        if task.get_name().startswith("ingestion-") and not task.done()
    }
    created: list[FakeSupervisor] = []

    def factory(settings):
        return FakeSupervisor(settings, created)

    controller = RuntimeController(
        settings=synthetic_settings(500),
        supervisor_factory=factory,
    )
    await controller.start()
    await asyncio.wait_for(created[-1].started.wait(), timeout=1)
    await controller.close()
    end = {
        task
        for task in asyncio.all_tasks()
        if task.get_name().startswith("ingestion-")
        and not task.done()
        and task not in baseline
    }
    assert not end
