"""Wall-clock slots and the lane-agnostic slot loop.

Slots are recomputed from the clock on every loop and sleeps never accumulate,
so a laptop sleep or a slow pass cannot shift the schedule.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from typing import Protocol

Clock = Callable[[], datetime]
Sleep = Callable[[float], Awaitable[None]]


class SlotConfig(Protocol):
    @property
    def slot_minutes(self) -> Sequence[int]: ...

    @property
    def slot_second(self) -> int: ...

    @property
    def wake_check_seconds(self) -> float: ...


def _slot_in_hour(hour: datetime, minute: int, second: int) -> datetime:
    return hour.replace(minute=minute, second=second, microsecond=0)


def slot_at_or_before(
    moment: datetime, minutes: Sequence[int], second: int
) -> datetime:
    """The latest slot time not after ``moment``."""
    hour = moment.replace(minute=0, second=0, microsecond=0)
    candidates = [
        slot
        for base in (hour, hour - timedelta(hours=1))
        for minute in minutes
        if (slot := _slot_in_hour(base, minute, second)) <= moment
    ]
    return max(candidates)


def next_slot_after(moment: datetime, minutes: Sequence[int], second: int) -> datetime:
    """The earliest slot time strictly after ``moment``."""
    hour = moment.replace(minute=0, second=0, microsecond=0)
    candidates = [
        slot
        for base in (hour, hour + timedelta(hours=1))
        for minute in minutes
        if (slot := _slot_in_hour(base, minute, second)) > moment
    ]
    return min(candidates)


async def run_slot_loop(
    *,
    slots: SlotConfig,
    clock: Clock,
    sleep: Sleep,
    can_write: Callable[[], bool],
    run_pass: Callable[[str], Awaitable[None]],
    on_first_pass: Callable[[], None] = lambda: None,
) -> None:
    """Run ``run_pass("catchup")`` at start, then once per due slot, forever."""
    wake = slots.wake_check_seconds
    minutes, second = slots.slot_minutes, slots.slot_second
    last_slot: datetime | None = None
    while True:
        if not can_write():
            # Lock not held: do not schedule and do not write.
            await sleep(wake)
            continue
        now = clock()
        due = slot_at_or_before(now, minutes, second)
        if last_slot is None:
            # Startup: catch up over every dataset before waiting for a slot.
            await run_pass("catchup")
            on_first_pass()
            last_slot = due
        elif due > last_slot:
            missed = (
                next_slot_after(last_slot, minutes, second) < due
                or (now - due).total_seconds() > wake
            )
            await run_pass("catchup" if missed else "schedule")
            last_slot = due
        else:
            remaining = (next_slot_after(now, minutes, second) - now).total_seconds()
            await sleep(max(min(wake, remaining), 0.0))


__all__ = [
    "Clock",
    "Sleep",
    "SlotConfig",
    "next_slot_after",
    "run_slot_loop",
    "slot_at_or_before",
]
