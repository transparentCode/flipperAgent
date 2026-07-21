from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from libs.models.trendline.tracking.service import TrendlineFamilyTracker
from libs.models.trendline_family.repository import (
    InMemoryTrendlineFamilyRepository,
    serialize_snapshot,
)

from .tracker_support import (
    SequenceProvider,
    candidate,
    timestamp,
    tracker_config,
    tracker_ohlcv,
    valid_result,
)


def _phase_update(tracker: TrendlineFamilyTracker, frame, observed_at):
    prepared = tracker._prepare_update_phase(  # noqa: SLF001
        frame,
        observed_at=observed_at,
        tick_size=None,
    )
    prior = tracker._load_prior_state_phase(  # noqa: SLF001
        timestamp=prepared.timestamp,
    )
    candidate_phase = tracker._generate_candidate_phase(  # noqa: SLF001
        frame=prepared.frame,
        timestamp=prepared.timestamp,
    )
    association = tracker._associate_rails_phase(  # noqa: SLF001
        frame=prepared.frame,
        timestamp=prepared.timestamp,
        candidates=candidate_phase.candidates,
        prior=prior,
    )
    lifecycle = tracker._advance_family_lifecycle_phase(  # noqa: SLF001
        timestamp=prepared.timestamp,
        current_price=candidate_phase.current_price,
        candidates=candidate_phase.candidates,
        previous_families=prior.previous_families,
        association=association,
        scheduled_role_reversals=prior.scheduled_role_reversals,
        applied_role_reversals=prior.applied_role_reversals,
    )
    interaction = tracker._advance_interaction_phase(  # noqa: SLF001
        lifecycle=lifecycle,
        frame=prepared.frame,
        timestamp=prepared.timestamp,
        tick_size=prepared.tick_size,
        previous_events=prior.previous_events,
        atr=association.atr,
    )
    snapshot = tracker._build_snapshot_phase(  # noqa: SLF001
        timestamp=prepared.timestamp,
        prior=prior,
        candidate_phase=candidate_phase,
        association=association,
        lifecycle=lifecycle,
        interaction=interaction,
    )
    repository_head = tracker.repository.latest_snapshot(
        tracker.config.asset,
        tracker.config.timeframe,
    )
    if prior.previous_snapshot is None:
        assert repository_head is None
    else:
        assert repository_head is not None
        assert serialize_snapshot(repository_head) == serialize_snapshot(
            prior.previous_snapshot
        )
    tracker._persist_snapshot_phase(snapshot)  # noqa: SLF001
    output = tracker._build_output_phase(  # noqa: SLF001
        snapshot,
        current_price=candidate_phase.current_price,
        atr=association.atr,
    )
    return prepared, output


def test_explicit_tracker_phases_replay_public_update_byte_for_byte() -> None:
    config = tracker_config()
    times = (timestamp(), timestamp(1))
    results = (
        valid_result(candidate(config, times[0], candidate_id="birth", quality=0.70)),
        valid_result(
            candidate(
                config,
                times[1],
                candidate_id="continuation",
                reference_price=100.2,
                quality=0.80,
            )
        ),
    )
    public_repository = InMemoryTrendlineFamilyRepository()
    phase_repository = InMemoryTrendlineFamilyRepository()
    public_tracker = TrendlineFamilyTracker(
        repository=public_repository,
        provider=SequenceProvider(results),
        config=config,
    )
    phase_tracker = TrendlineFamilyTracker(
        repository=phase_repository,
        provider=SequenceProvider(results),
        config=config,
    )

    for observed_at in times:
        frame = tracker_ohlcv(observed_at)
        public_output = public_tracker.update(frame, observed_at=observed_at)
        prepared, phase_output = _phase_update(phase_tracker, frame, observed_at)

        assert serialize_snapshot(phase_output.snapshot) == serialize_snapshot(
            public_output.snapshot
        )
        assert phase_output.snapshot.snapshot_id == public_output.snapshot.snapshot_id
        assert phase_output.snapshot.transitions == public_output.snapshot.transitions
        assert phase_output.snapshot.interaction_events == public_output.snapshot.interaction_events
        assert phase_output.features == public_output.features
        stored = phase_repository.latest_snapshot(config.asset, config.timeframe)
        assert stored is not None
        assert serialize_snapshot(stored) == serialize_snapshot(public_output.snapshot)
        with pytest.raises(FrozenInstanceError):
            prepared.timestamp = timestamp(3)  # type: ignore[misc]
