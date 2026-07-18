"""Candidate detection, association, capacity, and zone construction."""

from __future__ import annotations

from libs.models.sr.association import match_candidate
from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.domain.bars import ClosedBar
from libs.models.sr.domain.candidates import CandidateLevel
from libs.models.sr.domain.events import SREvent, SREventType
from libs.models.sr.domain.zones import (
    ZoneDefinition,
    ZoneRecord,
    ZoneRuntimeState,
    ZoneStatus,
)

from .transitions import TERMINAL_STATUSES


def create_candidate_zones(
    candidates: tuple[CandidateLevel, ...],
    transitioned_zones: tuple[ZoneRecord, ...],
    start_association_ids: frozenset[str],
    closed_bar: ClosedBar,
    resolved_config: ResolvedSRConfig,
) -> tuple[tuple[ZoneRecord, ...], tuple[SREvent, ...]]:
    """Create unmatched candidates in historical detection and batch order."""
    association_pool = tuple(
        record
        for record in transitioned_zones
        if record.definition.zone_id in start_association_ids
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
            record.runtime.status not in TERMINAL_STATUSES
            for record in transitioned_zones
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
    return tuple(created_zones), tuple(created_events)


__all__ = ["create_candidate_zones"]
