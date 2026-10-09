"""Scheduler with a fake clock: slots, catch-up, isolation, retry bounds, late bars."""

from __future__ import annotations

import pytest
from scraper_v2_support import FakeClock, make_spec, schedule_settings, tv_settings, utc

from apps.scraper_app.domain.bars import expected_latest_closed_bar_open
from apps.scraper_app.domain.datasets import Shape
from apps.scraper_app.runtime.collector import CollectOutcome
from apps.scraper_app.runtime.scheduler import (
    Scheduler,
    next_slot_after,
    slot_at_or_before,
)
from apps.scraper_app.runtime.status import RuntimeState


class _Stop(Exception):
    pass


class FakeCollector:
    def __init__(self, clock: FakeClock, *, late: bool = False) -> None:
        self.clock = clock
        self.calls: list[tuple[str, str, object]] = []
        self.fail: set[str] = set()
        self.crash: set[str] = set()
        self.late = late

    async def collect(self, spec, trigger):
        self.calls.append((spec.id, trigger, self.clock.now))
        if spec.id in self.crash:
            raise RuntimeError("boom")
        if spec.id in self.fail:
            return CollectOutcome(spec.id, ok=False, error_code="timeout")
        expected = expected_latest_closed_bar_open(
            self.clock.now, spec.interval_seconds
        )
        covered = expected.replace(year=2000) if self.late else expected
        return CollectOutcome(
            spec.id, ok=True, provider_time=self.clock.now, covered_to=covered
        )


def _scheduler(
    clock,
    collector,
    specs,
    *,
    stop_at=None,
    can_write=lambda: True,
    sleeper=None,
    tv=None,
):
    async def sleep(seconds: float) -> None:
        if stop_at is not None and clock.now >= stop_at:
            raise _Stop
        await (sleeper or clock.sleep)(seconds)

    state = RuntimeState()
    sched = Scheduler(
        specs=specs,
        collector=collector,
        tradingview=tv or tv_settings(),
        schedule=schedule_settings(),
        state=state,
        clock=clock,
        sleep=sleep,
        can_write=can_write,
    )
    return sched, state


def test_slot_arithmetic() -> None:
    t = utc(2026, 10, 9, 10, 15)
    assert slot_at_or_before(t, [0], 30) == utc(2026, 10, 9, 10, 0, 30)
    assert slot_at_or_before(utc(2026, 10, 9, 10, 0, 29), [0], 30) == utc(
        2026, 10, 9, 9, 0, 30
    )
    assert next_slot_after(t, [0], 30) == utc(2026, 10, 9, 11, 0, 30)
    assert next_slot_after(utc(2026, 10, 9, 10, 0, 30), [0], 30) == utc(
        2026, 10, 9, 11, 0, 30
    )
    assert slot_at_or_before(t, [0, 30], 30) == utc(2026, 10, 9, 10, 0, 30)
    assert next_slot_after(t, [0, 30], 30) == utc(2026, 10, 9, 10, 30, 30)
    assert next_slot_after(utc(2026, 10, 9, 23, 45), [0], 30) == utc(
        2026, 10, 10, 0, 0, 30
    )


@pytest.mark.asyncio
async def test_startup_catchup_then_slots_without_drift() -> None:
    clock = FakeClock(utc(2026, 10, 9, 10, 0, 10))
    collector = FakeCollector(clock)
    spec = make_spec()
    sched, state = _scheduler(clock, collector, [spec], stop_at=utc(2026, 10, 9, 13, 0))
    with pytest.raises(_Stop):
        await sched.run()

    assert state.startup_catchup_done
    triggers = [(c[1], c[2]) for c in collector.calls]
    assert triggers[0] == ("catchup", utc(2026, 10, 9, 10, 0, 10))
    schedule_times = [t for trig, t in triggers if trig == "schedule"]
    assert schedule_times[:2] == [
        utc(2026, 10, 9, 10, 0, 30),
        utc(2026, 10, 9, 11, 0, 30),
    ]
    assert all(s <= 30 for s in clock.sleeps)  # wakes at least every wake_check_seconds


@pytest.mark.asyncio
async def test_multi_hour_sleep_triggers_a_catchup_pass_before_the_next_slot() -> None:
    clock = FakeClock(utc(2026, 10, 9, 10, 5))
    collector = FakeCollector(clock)
    jumped = False

    async def sleeper(seconds: float) -> None:
        nonlocal jumped
        if not jumped and collector.calls:
            jumped = True
            clock.now = utc(2026, 10, 9, 15, 20)  # laptop slept for five hours
            return
        await clock.sleep(seconds)

    sched, _ = _scheduler(
        clock,
        collector,
        [make_spec()],
        stop_at=utc(2026, 10, 9, 15, 25),
        sleeper=sleeper,
    )
    with pytest.raises(_Stop):
        await sched.run()

    assert [c[1] for c in collector.calls[:2]] == ["catchup", "catchup"]
    assert collector.calls[1][2] == utc(2026, 10, 9, 15, 20)


@pytest.mark.asyncio
async def test_one_failing_or_crashing_dataset_does_not_stop_the_others() -> None:
    clock = FakeClock(utc(2026, 10, 9, 10, 0, 10))
    collector = FakeCollector(clock)
    specs = [make_spec(id=f"d{i}") for i in range(3)]
    collector.crash.add("d0")
    collector.fail.add("d1")
    sched, _ = _scheduler(clock, collector, specs)
    await sched.run_pass("catchup")
    assert {c[0] for c in collector.calls} == {"d0", "d1", "d2"}
    assert [c for c in collector.calls if c[0] == "d2"]


@pytest.mark.asyncio
async def test_retries_are_bounded_and_spaced_by_the_backoff() -> None:
    clock = FakeClock(utc(2026, 10, 9, 10, 0, 10))
    collector = FakeCollector(clock)
    collector.fail.add("d0")
    sched, _ = _scheduler(clock, collector, [make_spec(id="d0")])
    await sched.run_pass("schedule")
    assert len(collector.calls) == 3  # max_attempts_per_slot
    assert clock.sleeps == [5, 20]


@pytest.mark.asyncio
async def test_requests_are_spaced_between_datasets() -> None:
    clock = FakeClock(utc(2026, 10, 9, 10, 0, 10))
    collector = FakeCollector(clock)
    sched, _ = _scheduler(clock, collector, [make_spec(id="a"), make_spec(id="b")])
    await sched.run_pass("schedule")
    assert clock.sleeps == [1.0]


@pytest.mark.asyncio
async def test_late_bar_retries_only_for_contiguous_datasets() -> None:
    clock = FakeClock(utc(2026, 10, 9, 10, 0, 30))
    collector = FakeCollector(clock, late=True)
    funding = make_spec(id="fr", shape=Shape.OHLC, contiguous=False, non_negative=False)
    sched, _ = _scheduler(clock, collector, [make_spec(id="idx"), funding])
    await sched.run_pass("schedule")

    idx = [c[1] for c in collector.calls if c[0] == "idx"]
    assert idx == ["schedule", "late_bar", "late_bar", "late_bar"]
    assert [c[1] for c in collector.calls if c[0] == "fr"] == ["schedule"]
    assert clock.sleeps.count(20) == 3


@pytest.mark.asyncio
async def test_no_late_bar_retry_when_the_latest_bar_is_covered() -> None:
    clock = FakeClock(utc(2026, 10, 9, 10, 0, 30))
    collector = FakeCollector(clock)
    sched, _ = _scheduler(clock, collector, [make_spec()])
    await sched.run_pass("schedule")
    assert len(collector.calls) == 1


@pytest.mark.asyncio
async def test_nothing_is_collected_while_the_lock_is_not_held() -> None:
    clock = FakeClock(utc(2026, 10, 9, 10, 0, 10))
    collector = FakeCollector(clock)
    sched, state = _scheduler(
        clock,
        collector,
        [make_spec()],
        stop_at=utc(2026, 10, 9, 10, 5),
        can_write=lambda: False,
    )
    with pytest.raises(_Stop):
        await sched.run()
    assert collector.calls == []
    assert not state.startup_catchup_done
