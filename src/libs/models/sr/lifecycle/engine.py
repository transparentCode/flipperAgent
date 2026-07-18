"""Deterministic lifecycle-step orchestration."""

from __future__ import annotations

from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.detection import detect_confirmed_pivots
from libs.models.sr.domain.bars import ClosedBar
from libs.models.sr.domain.events import SREvent
from libs.models.sr.domain.snapshots import SRSnapshot
from libs.models.sr.domain.state import SRState

from .creation import create_candidate_zones
from .transitions import advance_existing_zones
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
        candidates = tuple(
            sorted(
                detect_confirmed_pivots(
                    previous_state.recent_bars + (closed_bar,),
                    resolved_config.detection,
                ),
                key=lambda candidate: (
                    candidate.formed_at,
                    candidate.available_at,
                    candidate.candidate_id,
                ),
            )
        )
        created_zones, created_events = create_candidate_zones(
            candidates,
            next_zones,
            start_association_ids,
            closed_bar,
            resolved_config,
        )
        next_state = SRState(
            schema_version=previous_state.schema_version,
            state_key=previous_state.state_key,
            config_hash=previous_state.config_hash,
            last_processed_bar=closed_bar.bar_id,
            zones=next_zones + created_zones,
            recent_bars=(previous_state.recent_bars + (closed_bar,))[
                -max_recent_bars:
            ],
        )
        snapshot = SRSnapshot(
            schema_version=next_state.schema_version,
            state_key=next_state.state_key,
            config_hash=next_state.config_hash,
            as_of=closed_bar.closed_at,
            zones=next_state.zones,
            events=raw_events + created_events,
        )
        return next_state, snapshot, snapshot.events


__all__ = ["SREngine"]
