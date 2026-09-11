"""Causal lifecycle mutation with one typed transition stream."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import datetime

from ..contracts import LifecycleState, ZoneSide, require_utc
from ..domain.bars import SRBar
from ..domain.candidates import Candidate
from ..domain.zones import ZoneLineage, ZoneRecord, lineage_from_candidate
from .rules import LifecycleRules
from .transitions import LifecycleTransition, TransitionType, make_transition

_TERMINAL = frozenset({LifecycleState.BROKEN, LifecycleState.EXPIRED, LifecycleState.SUPERSEDED})


def _overlaps(zone: ZoneLineage, bar: SRBar) -> bool:
    return bar.high >= zone.lower and bar.low <= zone.upper


def _beyond_break(zone: ZoneLineage, bar: SRBar, rules: LifecycleRules) -> bool:
    threshold = zone.creation_atr * rules.break_buffer_atr
    if zone.side is ZoneSide.RESISTANCE:
        return bar.close > zone.upper + threshold
    return bar.close < zone.lower - threshold


def _transition(
    before: ZoneRecord,
    after: ZoneRecord,
    transition_type: TransitionType,
    *,
    event_at: datetime,
    causal_bar_id: str | None = None,
    retention_state: str,
    successor_id: str | None = None,
) -> LifecycleTransition:
    return make_transition(
        transition_type=transition_type,
        event_at=event_at,
        zone_id=after.lineage.zone_id,
        before_lifecycle=before.lifecycle,
        after_lifecycle=after.lifecycle,
        before_overlapping=before.was_overlapping,
        after_overlapping=after.was_overlapping,
        before_touch_count=before.touch_count,
        after_touch_count=after.touch_count,
        before_break_pending_count=before.break_pending_count,
        after_break_pending_count=after.break_pending_count,
        retention_state=retention_state,
        causal_bar_id=causal_bar_id,
        predecessor_id=after.lineage.predecessor_id,
        successor_id=successor_id,
    )


def advance_zone(
    record: ZoneRecord,
    bar: SRBar,
    *,
    rules: LifecycleRules,
) -> tuple[ZoneRecord, tuple[LifecycleTransition, ...]]:
    """Advance one zone over one newly closed bar."""

    if not isinstance(record, ZoneRecord) or not isinstance(bar, SRBar):
        raise TypeError("record and bar must be ZoneRecord and SRBar")
    if not isinstance(rules, LifecycleRules):
        raise TypeError("rules must be LifecycleRules")
    if bar.bar_close_at <= record.lineage.available_at or record.lifecycle in _TERMINAL:
        return record, ()
    transitions: list[LifecycleTransition] = []
    state = record
    overlap = _overlaps(state.lineage, bar)
    if bar.bar_close_at >= state.lineage.available_at + rules.expiry:
        state = replace(
            state,
            lifecycle=LifecycleState.EXPIRED,
            break_pending_count=0,
            was_overlapping=overlap,
            last_transition_at=bar.bar_close_at,
        )
        transitions.append(
            _transition(
                record,
                state,
                TransitionType.EXPIRED,
                event_at=bar.bar_close_at,
                causal_bar_id=bar.identity,
                retention_state="ACTIVE_TO_TOMBSTONE",
            )
        )
        return state, tuple(transitions)

    if overlap and not state.was_overlapping:
        before = state
        state = replace(
            state,
            lifecycle=LifecycleState.TOUCHED if state.lifecycle is LifecycleState.ACTIVE else state.lifecycle,
            touch_count=state.touch_count + 1,
            was_overlapping=True,
            last_touch_at=bar.bar_close_at,
            last_transition_at=bar.bar_close_at,
        )
        transitions.append(
            _transition(
                before,
                state,
                TransitionType.TOUCH_STARTED,
                event_at=bar.bar_close_at,
                causal_bar_id=bar.identity,
                retention_state="RETAINED",
            )
        )
    elif not overlap and state.was_overlapping:
        before = state
        state = replace(state, was_overlapping=False)
        transitions.append(
            _transition(
                before,
                state,
                TransitionType.TOUCH_ENDED,
                event_at=bar.bar_close_at,
                causal_bar_id=bar.identity,
                retention_state="RETAINED",
            )
        )

    if _beyond_break(state.lineage, bar, rules):
        before = state
        pending = state.break_pending_count + 1
        if pending >= rules.break_confirmation_bars:
            state = replace(
                state,
                lifecycle=LifecycleState.BROKEN,
                break_pending_count=pending,
                was_overlapping=overlap,
                last_transition_at=bar.bar_close_at,
            )
            transition_type = TransitionType.BROKEN
            retention = "ACTIVE_TO_TOMBSTONE"
        else:
            state = replace(
                state,
                lifecycle=LifecycleState.BREAK_PENDING,
                break_pending_count=pending,
                was_overlapping=overlap,
                last_transition_at=bar.bar_close_at,
            )
            transition_type = TransitionType.BREAK_PENDING
            retention = "RETAINED"
        transitions.append(
            _transition(
                before,
                state,
                transition_type,
                event_at=bar.bar_close_at,
                causal_bar_id=bar.identity,
                retention_state=retention,
            )
        )
    elif state.lifecycle is LifecycleState.BREAK_PENDING:
        before = state
        state = replace(
            state,
            lifecycle=LifecycleState.TOUCHED if state.touch_count else LifecycleState.ACTIVE,
            break_pending_count=0,
            was_overlapping=overlap,
            last_transition_at=bar.bar_close_at,
        )
        transitions.append(
            _transition(
                before,
                state,
                TransitionType.BREAK_CLEARED,
                event_at=bar.bar_close_at,
                causal_bar_id=bar.identity,
                retention_state="RETAINED",
            )
        )
    if state.was_overlapping != overlap:
        state = replace(state, was_overlapping=overlap)
    return state, tuple(transitions)


def apply_candidates_with_replacements(
    existing: Sequence[ZoneRecord],
    terminal: Sequence[ZoneRecord],
    candidates: Iterable[Candidate],
    *,
    config_fingerprint: str,
    now: datetime,
    replacement_policy: str,
) -> tuple[tuple[ZoneRecord, ...], tuple[ZoneRecord, ...], tuple[LifecycleTransition, ...]]:
    """Create candidates and apply the policy owned by their KernelSpec."""

    require_utc(now, field_name="now")
    if replacement_policy not in {"singleton_per_timeframe_side", "independent"}:
        raise ValueError("unsupported replacement policy")
    active_by_id = {record.lineage.zone_id: record for record in existing}
    terminal_by_id = {record.lineage.zone_id: record for record in terminal}
    transitions: list[LifecycleTransition] = []
    for candidate in candidates:
        current = tuple(
            record
            for record in active_by_id.values()
            if replacement_policy == "singleton_per_timeframe_side"
            and record.lineage.venue == candidate.venue
            and record.lineage.instrument_id == candidate.instrument_id
            and record.lineage.asset == candidate.asset
            and record.lineage.source_timeframe == candidate.source_timeframe
            and record.lineage.kernel_id == candidate.kernel_id
            and record.lineage.kernel_version == candidate.kernel_version
            and record.lineage.side is candidate.side
        )
        predecessor = max(current, key=lambda item: (item.lineage.available_at, item.lineage.zone_id), default=None)
        if predecessor is not None and predecessor.lineage.available_at >= candidate.available_at:
            continue
        predecessor_id = predecessor.lineage.zone_id if predecessor is not None else None
        lineage = lineage_from_candidate(candidate, config_fingerprint=config_fingerprint, predecessor_id=predecessor_id)
        if lineage.zone_id in active_by_id or lineage.zone_id in terminal_by_id:
            continue
        if predecessor is not None:
            before = predecessor
            superseded = replace(predecessor, lifecycle=LifecycleState.SUPERSEDED, last_transition_at=now)
            active_by_id.pop(predecessor.lineage.zone_id, None)
            terminal_by_id[predecessor.lineage.zone_id] = superseded
            transitions.append(
                _transition(
                    before,
                    superseded,
                    TransitionType.SUPERSEDED,
                    event_at=now,
                    retention_state="ACTIVE_TO_TOMBSTONE",
                    successor_id=lineage.zone_id,
                )
            )
        created = ZoneRecord(lineage=lineage, last_transition_at=now)
        active_by_id[lineage.zone_id] = created
        transitions.append(
            make_transition(
                transition_type=TransitionType.CREATED,
                event_at=now,
                zone_id=lineage.zone_id,
                before_lifecycle=None,
                after_lifecycle=created.lifecycle,
                before_overlapping=False,
                after_overlapping=False,
                before_touch_count=0,
                after_touch_count=0,
                before_break_pending_count=0,
                after_break_pending_count=0,
                retention_state="RETAINED",
                predecessor_id=lineage.predecessor_id,
            )
        )
    return (
        tuple(sorted(active_by_id.values(), key=lambda item: item.lineage.zone_id)),
        tuple(sorted(terminal_by_id.values(), key=lambda item: item.lineage.zone_id)),
        tuple(transitions),
    )


__all__ = ["advance_zone", "apply_candidates_with_replacements"]
