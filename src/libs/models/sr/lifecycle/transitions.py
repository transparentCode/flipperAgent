"""Pure existing-zone lifecycle transitions."""

from __future__ import annotations

from libs.models.sr.config.models import LifecycleConfig
from libs.models.sr.domain.bars import ClosedBar
from libs.models.sr.domain.events import SREvent, SREventType
from libs.models.sr.domain.zones import (
    ZoneRecord,
    ZoneRuntimeState,
    ZoneStatus,
)

from .rules import breaches_zone, touches_zone


TERMINAL_STATUSES = frozenset({ZoneStatus.BROKEN, ZoneStatus.EXPIRED})


def _event(
    record: ZoneRecord,
    event_type: SREventType,
    bar: ClosedBar,
) -> SREvent:
    return SREvent(
        zone_id=record.definition.zone_id,
        event_type=event_type,
        timestamp=bar.closed_at,
        price=bar.close,
        bar_id=bar.bar_id,
    )


def advance_zone(
    record: ZoneRecord,
    bar: ClosedBar,
    lifecycle_config: LifecycleConfig,
) -> tuple[ZoneRecord, tuple[SREvent, ...]]:
    """Apply one eligible bar to one non-terminal zone."""
    runtime = record.runtime
    status = runtime.status
    pending_breach_count = runtime.pending_breach_count
    touch_count = runtime.touch_count
    fakeout_count = runtime.fakeout_count
    last_interaction_at = runtime.last_interaction_at
    events: list[SREvent] = []

    age_bars = runtime.age_bars + 1
    updated_at = bar.closed_at

    if status is ZoneStatus.ACTIVE:
        if breaches_zone(record.definition, bar, lifecycle_config):
            events.append(_event(record, SREventType.BREACH_STARTED, bar))
            last_interaction_at = bar.closed_at
            if lifecycle_config.break_confirm_closes == 1:
                status = ZoneStatus.BROKEN
                pending_breach_count = 0
                events.append(_event(record, SREventType.BREAK_CONFIRMED, bar))
            else:
                status = ZoneStatus.BREACH_PENDING
                pending_breach_count = 1
        elif touches_zone(record.definition, bar, lifecycle_config):
            status = ZoneStatus.ACTIVE
            touch_count += 1
            last_interaction_at = bar.closed_at
            events.append(_event(record, SREventType.TOUCHED, bar))

    elif status is ZoneStatus.BREACH_PENDING:
        if breaches_zone(record.definition, bar, lifecycle_config):
            pending_breach_count += 1
            if pending_breach_count >= lifecycle_config.break_confirm_closes:
                status = ZoneStatus.BROKEN
                pending_breach_count = 0
                last_interaction_at = bar.closed_at
                events.append(_event(record, SREventType.BREAK_CONFIRMED, bar))
        else:
            status = ZoneStatus.ACTIVE
            pending_breach_count = 0
            fakeout_count += 1
            last_interaction_at = bar.closed_at
            events.append(_event(record, SREventType.FALSE_BREAKOUT, bar))

    if (
        status not in TERMINAL_STATUSES
        and age_bars >= lifecycle_config.max_age_bars
    ):
        status = ZoneStatus.EXPIRED
        pending_breach_count = 0
        events.append(_event(record, SREventType.EXPIRED, bar))

    new_runtime = ZoneRuntimeState(
        zone_id=record.definition.zone_id,
        status=status,
        touch_count=touch_count,
        fakeout_count=fakeout_count,
        pending_breach_count=pending_breach_count,
        age_bars=age_bars,
        last_interaction_at=last_interaction_at,
        updated_at=updated_at,
    )
    return ZoneRecord(definition=record.definition, runtime=new_runtime), tuple(events)


def advance_existing_zones(
    records: tuple[ZoneRecord, ...],
    bar: ClosedBar,
    lifecycle_config: LifecycleConfig,
) -> tuple[tuple[ZoneRecord, ...], tuple[SREvent, ...]]:
    """Advance existing zones in stored order, retaining terminal/ineligible ones."""
    next_zones: list[ZoneRecord] = []
    raw_events: list[SREvent] = []
    for record in records:
        if record.runtime.status in TERMINAL_STATUSES:
            next_zones.append(record)
            continue
        if bar.closed_at <= record.definition.available_at:
            next_zones.append(record)
            continue

        next_record, events = advance_zone(record, bar, lifecycle_config)
        next_zones.append(next_record)
        raw_events.extend(events)
    return tuple(next_zones), tuple(raw_events)


__all__ = ["TERMINAL_STATUSES", "advance_existing_zones", "advance_zone"]
