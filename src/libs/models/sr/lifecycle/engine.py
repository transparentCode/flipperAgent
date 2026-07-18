"""Deterministic lifecycle-step orchestration."""

from __future__ import annotations

from libs.models.sr.association import match_candidate
from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.detection import detect_confirmed_pivots
from libs.models.sr.domain.bars import ClosedBar
from libs.models.sr.domain.events import SREvent, SREventType
from libs.models.sr.domain.snapshots import SRSnapshot
from libs.models.sr.domain.state import SRState
from libs.models.sr.domain.zones import (
    ZoneDefinition,
    ZoneRecord,
    ZoneRuntimeState,
    ZoneStatus,
)

from .transitions import TERMINAL_STATUSES, advance_existing_zones
from .validation import validate_step_inputs


class SREngine:
    """Apply one closed bar to an immutable SR aggregate."""

    def step(
        self,
        previous_state: SRState,
        closed_bar: ClosedBar,
        resolved_config: ResolvedSRConfig,
    ) -> tuple[SRState, SRSnapshot, tuple[SREvent, ...]]:
        """Return next state, audit snapshot, and canonical events."""
        max_recent_bars, start_association_ids = validate_step_inputs(
            previous_state,
            closed_bar,
            resolved_config,
        )
        next_zones, raw_events = advance_existing_zones(
            previous_state.zones,
            closed_bar,
            resolved_config.lifecycle,
        )
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
                record.runtime.status not in TERMINAL_STATUSES
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

        next_zones = next_zones + tuple(created_zones)
        recent_bars = (previous_state.recent_bars + (closed_bar,))[
            -max_recent_bars:
        ]
        next_state = SRState(
            schema_version=previous_state.schema_version,
            state_key=previous_state.state_key,
            config_hash=previous_state.config_hash,
            last_processed_bar=closed_bar.bar_id,
            zones=next_zones,
            recent_bars=recent_bars,
        )
        snapshot = SRSnapshot(
            schema_version=next_state.schema_version,
            state_key=next_state.state_key,
            config_hash=next_state.config_hash,
            as_of=closed_bar.closed_at,
            zones=next_state.zones,
            events=raw_events + tuple(created_events),
        )
        return next_state, snapshot, snapshot.events


__all__ = ["SREngine"]
