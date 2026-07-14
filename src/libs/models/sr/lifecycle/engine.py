"""Deterministic SR-V1.1 lifecycle state transitions."""

from __future__ import annotations

from libs.models.sr.association import match_candidate
from libs.models.sr.config.models import LifecycleConfig, ResolvedSRConfig
from libs.models.sr.detection import detect_confirmed_pivots
from libs.models.sr.domain.contracts import (
    ClosedBar,
    ContractValidationError,
    SREvent,
    SREventType,
    SRState,
    SRSnapshot,
    ZoneRecord,
    ZoneDefinition,
    ZoneRuntimeState,
    ZoneStatus,
)

from .rules import breaches_zone, touches_zone


_TERMINAL_STATUSES = frozenset({ZoneStatus.BROKEN, ZoneStatus.EXPIRED})


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


def _advance_zone(
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
        status not in _TERMINAL_STATUSES
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


class SREngine:
    """Apply one closed bar to an immutable SR aggregate."""

    def step(
        self,
        previous_state: SRState,
        closed_bar: ClosedBar,
        resolved_config: ResolvedSRConfig,
    ) -> tuple[SRState, SRSnapshot, tuple[SREvent, ...]]:
        """Return the next state, an audit snapshot, and its canonical events."""
        if type(previous_state) is not SRState:
            raise ContractValidationError("previous_state must be SRState")
        if type(closed_bar) is not ClosedBar:
            raise ContractValidationError("closed_bar must be ClosedBar")
        if type(resolved_config) is not ResolvedSRConfig:
            raise ContractValidationError(
                "resolved_config must be ResolvedSRConfig"
            )
        if closed_bar.state_key != previous_state.state_key:
            raise ContractValidationError(
                "closed_bar.state_key must match previous_state.state_key"
            )
        if (
            previous_state.state_key.symbol != resolved_config.asset
            or previous_state.state_key.timeframe != resolved_config.timeframe
        ):
            raise ContractValidationError(
                "state symbol/timeframe must match resolved configuration"
            )
        if previous_state.config_hash != resolved_config.resolved_config_hash:
            raise ContractValidationError(
                "state.config_hash must match resolved configuration hash"
            )

        max_recent_bars = 2 * resolved_config.detection.pivot_span_bars
        if len(previous_state.recent_bars) > max_recent_bars:
            raise ContractValidationError(
                "previous_state.recent_bars exceeds the configured detection buffer"
            )
        if previous_state.recent_bars:
            if (
                previous_state.recent_bars[-1].bar_id
                != previous_state.last_processed_bar
            ):
                raise ContractValidationError(
                    "recent_bars final bar_id must match last_processed_bar"
                )
            if closed_bar.bar_id in {
                bar.bar_id for bar in previous_state.recent_bars
            }:
                raise ContractValidationError(
                    "closed_bar.bar_id duplicates a recent bar"
                )
            if (
                closed_bar.closed_at
                <= previous_state.recent_bars[-1].closed_at
            ):
                raise ContractValidationError(
                    "closed_bar.closed_at must be later than recent bars"
                )

        non_terminal_count = sum(
            record.runtime.status not in _TERMINAL_STATUSES
            for record in previous_state.zones
        )
        if non_terminal_count > resolved_config.runtime.max_active_zones:
            raise ContractValidationError(
                "previous state exceeds max_active_zones"
            )

        start_association_ids = {
            record.definition.zone_id
            for record in previous_state.zones
            if record.runtime.status not in _TERMINAL_STATUSES
        }
        if closed_bar.bar_id == previous_state.last_processed_bar:
            raise ContractValidationError(
                "closed_bar.bar_id duplicates previous_state.last_processed_bar"
            )
        for record in previous_state.zones:
            if closed_bar.closed_at < record.runtime.updated_at:
                raise ContractValidationError(
                    "closed_bar.closed_at must not precede zone runtime.updated_at"
                )
            if record.runtime.status in _TERMINAL_STATUSES:
                continue
            if (
                record.runtime.age_bars
                >= resolved_config.lifecycle.max_age_bars
            ):
                raise ContractValidationError(
                    "non-terminal zone age_bars must be below max_age_bars"
                )
            if (
                record.runtime.status is ZoneStatus.BREACH_PENDING
                and record.runtime.pending_breach_count
                >= resolved_config.lifecycle.break_confirm_closes
            ):
                raise ContractValidationError(
                    "pending_breach_count must be below break_confirm_closes"
                )

        next_zones: list[ZoneRecord] = []
        raw_events: list[SREvent] = []
        for record in previous_state.zones:
            if record.runtime.status in _TERMINAL_STATUSES:
                next_zones.append(record)
                continue
            if closed_bar.closed_at <= record.definition.available_at:
                next_zones.append(record)
                continue

            next_record, events = _advance_zone(
                record,
                closed_bar,
                resolved_config.lifecycle,
            )
            next_zones.append(next_record)
            raw_events.extend(events)

        association_pool = tuple(
            record
            for record in next_zones
            if record.definition.zone_id in start_association_ids
        )
        detection_bars = previous_state.recent_bars + (closed_bar,)
        candidates = tuple(
            sorted(
                detect_confirmed_pivots(
                    detection_bars,
                    resolved_config.detection,
                ),
                key=lambda candidate: (
                    candidate.formed_at,
                    candidate.available_at,
                    candidate.candidate_id,
                ),
            )
        )
        created_zones: list[ZoneRecord] = []
        created_events: list[SREvent] = []
        for candidate in candidates:
            match_pool = association_pool + tuple(created_zones)
            if (
                match_candidate(
                    candidate,
                    match_pool,
                    resolved_config.association,
                )
                is not None
            ):
                continue

            active_count = sum(
                record.runtime.status not in _TERMINAL_STATUSES
                for record in next_zones
            ) + len(created_zones)
            if active_count >= resolved_config.runtime.max_active_zones:
                continue

            definition = ZoneDefinition(
                state_key=candidate.state_key,
                side=candidate.side,
                geometry=candidate.geometry,
                source=candidate.source,
                created_at=candidate.formed_at,
                available_at=candidate.available_at,
                atr_at_creation=candidate.atr_at_creation,
                config_hash=resolved_config.resolved_config_hash,
            )
            runtime = ZoneRuntimeState(
                zone_id=definition.zone_id,
                status=ZoneStatus.ACTIVE,
                touch_count=0,
                fakeout_count=0,
                pending_breach_count=0,
                age_bars=0,
                last_interaction_at=None,
                updated_at=definition.available_at,
            )
            record = ZoneRecord(definition=definition, runtime=runtime)
            created_zones.append(record)
            created_events.append(
                SREvent(
                    zone_id=definition.zone_id,
                    event_type=SREventType.CREATED,
                    timestamp=definition.available_at,
                    price=definition.geometry.center,
                    bar_id=closed_bar.bar_id,
                )
            )

        next_zones.extend(created_zones)
        recent_bars = (previous_state.recent_bars + (closed_bar,))[
            -max_recent_bars:
        ]

        next_state = SRState(
            schema_version=previous_state.schema_version,
            state_key=previous_state.state_key,
            config_hash=previous_state.config_hash,
            last_processed_bar=closed_bar.bar_id,
            zones=tuple(next_zones),
            recent_bars=recent_bars,
        )
        snapshot = SRSnapshot(
            schema_version=next_state.schema_version,
            state_key=next_state.state_key,
            config_hash=next_state.config_hash,
            as_of=closed_bar.closed_at,
            zones=next_state.zones,
            events=tuple(raw_events + created_events),
        )
        return next_state, snapshot, snapshot.events


__all__ = ["SREngine"]
