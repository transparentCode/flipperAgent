from __future__ import annotations

import ast
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from libs.models.trendline.domain import TrendlineContext, trendline_context_from_snapshot
from libs.models.trendline.storage.memory import InMemoryTrendlineRepository
from libs.models.trendline.storage.repository import SnapshotVersionError, TrendlineRepository
from libs.models.trendline_family.contracts import (
    FamilyInteractionEvent,
    FamilyRole,
    InteractionEventState,
)
from libs.models.trendline_family.repository import (
    InMemoryTrendlineFamilyRepository,
    TrendlineFamilyRepository,
)
from libs.models.trendline_family.tracker import TrendlineFamilyTracker

from .tracker_support import (
    SequenceProvider,
    abstention,
    candidate,
    timestamp,
    tracker_config,
    tracker_ohlcv,
    valid_result,
)


_STORAGE_ROOT = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline" / "storage"
_FORBIDDEN_STORAGE_IMPORTS = (
    "libs.models.trendline.research",
    "libs.models.trendline.research_lab",
    "libs.models.trendline.visualization",
    "libs.models.trendline.tvlc",
    "libs.models.trendline_family",
    "libs.trendlines",
    "app.trendlines",
)


def _far_event(*, event_id: str, known_at, asset: str = "BTCUSDT", timeframe: str = "1h") -> FamilyInteractionEvent:
    return FamilyInteractionEvent(
        event_id=event_id,
        family_id="family-support",
        asset=asset,
        timeframe=timeframe,
        state=InteractionEventState.FAR,
        started_at=known_at,
        updated_at=known_at,
        starting_role=FamilyRole.SUPPORT,
        current_event_role=FamilyRole.SUPPORT,
        previous_state=None,
        last_observation_id=f"observation-{event_id}",
        age_bars=1,
        bars_in_state=1,
        pressure_bars=None,
        rejection_bars=None,
        close_beyond_streak=None,
        retest_age_bars=None,
        retest_contact_seen=False,
        retest_confirmation_streak=None,
        retest_window_expired=False,
        role_reversal_applied=False,
        max_wick_penetration_atr=0.0,
        max_body_penetration_atr=0.0,
        max_close_penetration_atr=0.0,
        break_pending_at=None,
        break_confirmed_at=None,
        retest_started_at=None,
        retest_succeeded_at=None,
        failed_break_at=None,
        pending_role_reversal=False,
        required_close_confirmation_bars=2,
        required_retest_confirmation_bars=1,
        model_version="trendline_family_v1",
        config_version="1",
        resolved_config_hash="a" * 64,
    )


def _run_sequence(*, repository: InMemoryTrendlineRepository, count: int) -> tuple:
    config = tracker_config()
    times = tuple(timestamp(offset) for offset in range(4))
    results = (
        valid_result(candidate(config, times[0], candidate_id="storage-first")),
        valid_result(candidate(config, times[1], candidate_id="storage-second", quality=0.85)),
        abstention(),
        abstention(),
    )
    tracker = TrendlineFamilyTracker(
        repository=repository,
        provider=SequenceProvider(results[:count]),
        config=config,
    )
    return tuple(tracker.update(tracker_ohlcv(observed), observed_at=observed).snapshot for observed in times[:count])


def _run_break_sequence(*, repository: InMemoryTrendlineRepository, count: int) -> tuple:
    config = tracker_config()
    times = (timestamp(), timestamp(1))
    tracker = TrendlineFamilyTracker(
        repository=repository,
        provider=SequenceProvider(
            (
                valid_result(candidate(config, times[0], candidate_id="break-first")),
                valid_result(candidate(config, times[1], candidate_id="break-second")),
            )[:count]
        ),
        config=config,
    )
    snapshots = []
    for observed in times[:count]:
        frame = tracker_ohlcv(observed)
        frame.iloc[-1] = (99.4, 100.0, 98.8, 99.0)
        snapshots.append(tracker.update(frame, observed_at=observed).snapshot)
    return tuple(snapshots)


def _run_lifecycle_sequence(*, repository: InMemoryTrendlineRepository, count: int) -> tuple:
    config = tracker_config()
    times = tuple(timestamp(offset) for offset in range(6))
    tracker = TrendlineFamilyTracker(
        repository=repository,
        provider=SequenceProvider(
            (valid_result(candidate(config, times[0], candidate_id="lifecycle-first")),) + (abstention(),) * 5
        ),
        config=config,
    )
    return tuple(tracker.update(tracker_ohlcv(observed), observed_at=observed).snapshot for observed in times[:count])


def _storage_imports() -> set[str]:
    imports: set[str] = set()
    for path in _STORAGE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports


def test_storage_protocol_and_compatibility_import_identity() -> None:
    assert TrendlineFamilyRepository is TrendlineRepository
    assert InMemoryTrendlineFamilyRepository is InMemoryTrendlineRepository
    repository = InMemoryTrendlineRepository()
    for method in ("latest_snapshot", "save_snapshot", "save_family", "save_event", "get_family", "get_state_at"):
        assert callable(getattr(repository, method))


def test_existing_head_semantics_and_aggregate_snapshot_history() -> None:
    repository = InMemoryTrendlineRepository()
    snapshots = _run_sequence(repository=repository, count=4)

    assert repository.latest_snapshot("BTCUSDT", "1h") == snapshots[-1]
    assert repository.get_state_at(asset="BTCUSDT", timeframe="1h", as_of=snapshots[0].timestamp) == trendline_context_from_snapshot(snapshots[0])
    assert repository.get_state_at(asset="BTCUSDT", timeframe="1h", as_of=snapshots[-1].timestamp) == trendline_context_from_snapshot(snapshots[-1])

    before = repository.get_state_at(
        asset="BTCUSDT",
        timeframe="1h",
        as_of=snapshots[0].timestamp - timedelta(microseconds=1),
    )
    assert before == TrendlineContext(asset="BTCUSDT", timeframe="1h", as_of=before.as_of, families=())


def test_historical_context_is_stable_after_future_snapshots_and_is_partitioned() -> None:
    repository = InMemoryTrendlineRepository()
    snapshots = _run_sequence(repository=repository, count=4)
    first = repository.get_state_at(asset="BTCUSDT", timeframe="1h", as_of=snapshots[0].timestamp)

    assert repository.get_state_at(asset="BTCUSDT", timeframe="1h", as_of=snapshots[0].timestamp) == first
    assert repository.get_state_at(asset="BTCUSDT", timeframe="4h", as_of=snapshots[-1].timestamp).families == ()
    assert repository.get_state_at(asset="ETHUSDT", timeframe="1h", as_of=snapshots[-1].timestamp).families == ()
    assert first.families[0].touch_count <= snapshots[-1].active_families[0].touch_count


def test_event_history_uses_causal_updated_time_exact_boundary_and_deterministic_order() -> None:
    repository = InMemoryTrendlineRepository()
    first_time = timestamp()
    later_time = timestamp(1)
    event_b = _far_event(event_id="event-b", known_at=first_time)
    event_a = _far_event(event_id="event-a", known_at=first_time)
    repository.save_event(event_b)
    repository.save_event(event_a)

    before = repository.get_state_at(
        asset="BTCUSDT",
        timeframe="1h",
        as_of=first_time - timedelta(microseconds=1),
    )
    at_boundary = repository.get_state_at(asset="BTCUSDT", timeframe="1h", as_of=first_time)
    assert before.events == ()
    assert tuple(event.event_id for event in at_boundary.events) == ("event-a", "event-b")

    revision = replace(event_a, updated_at=later_time, last_observation_id="observation-event-a-later", age_bars=2, bars_in_state=2)
    repository.save_event(revision)
    assert repository.get_state_at(asset="BTCUSDT", timeframe="1h", as_of=first_time).events[0] == event_a
    assert repository.get_state_at(asset="BTCUSDT", timeframe="1h", as_of=later_time).events[1] == revision


def test_event_and_family_duplicate_conflict_and_defensive_copy_rules() -> None:
    repository = InMemoryTrendlineRepository()
    event = _far_event(event_id="event-1", known_at=timestamp())
    repository.save_event(event)
    repository.save_event(event)
    with pytest.raises(SnapshotVersionError, match="conflict"):
        repository.save_event(replace(event, metadata={"conflict": True}))

    snapshot = _run_sequence(repository=repository, count=1)[0]
    family = snapshot.active_families[0]
    assert repository.get_family(family.family_id) == family
    with pytest.raises(AttributeError):
        repository.get_family(family.family_id).confidence = 0.0  # type: ignore[union-attr,misc]
    with pytest.raises(SnapshotVersionError, match="previous_snapshot_id"):
        repository.save_snapshot(snapshot)


def test_full_history_point_in_time_matches_causal_prefix_execution() -> None:
    full_repository = InMemoryTrendlineRepository()
    full_snapshots = _run_sequence(repository=full_repository, count=4)

    for checkpoint, full_snapshot in enumerate(full_snapshots, start=1):
        prefix_repository = InMemoryTrendlineRepository()
        prefix_snapshots = _run_sequence(repository=prefix_repository, count=checkpoint)
        expected = trendline_context_from_snapshot(prefix_snapshots[-1])
        actual = full_repository.get_state_at(
            asset="BTCUSDT",
            timeframe="1h",
            as_of=full_snapshot.timestamp,
        )
        assert actual == expected


def test_break_and_lifecycle_states_match_causal_prefixes_without_future_leakage() -> None:
    full_break_repository = InMemoryTrendlineRepository()
    full_break_snapshots = _run_break_sequence(repository=full_break_repository, count=2)
    assert tuple(event.state.value for event in full_break_snapshots[0].interaction_events) == ("BREAK_PENDING",)
    assert tuple(event.state.value for event in full_break_snapshots[1].interaction_events) == ("BREAK_CONFIRMED",)
    for checkpoint, snapshot in enumerate(full_break_snapshots, start=1):
        prefix_repository = InMemoryTrendlineRepository()
        expected = trendline_context_from_snapshot(_run_break_sequence(repository=prefix_repository, count=checkpoint)[-1])
        assert full_break_repository.get_state_at(
            asset="BTCUSDT", timeframe="1h", as_of=snapshot.timestamp
        ) == expected

    full_lifecycle_repository = InMemoryTrendlineRepository()
    full_lifecycle_snapshots = _run_lifecycle_sequence(repository=full_lifecycle_repository, count=6)
    assert full_lifecycle_snapshots[0].active_families[0].lifecycle_state.value == "ACTIVE"
    assert full_lifecycle_snapshots[3].dormant_families[0].lifecycle_state.value == "DORMANT"
    for checkpoint, snapshot in enumerate(full_lifecycle_snapshots, start=1):
        prefix_repository = InMemoryTrendlineRepository()
        prefix_snapshot = _run_lifecycle_sequence(
            repository=prefix_repository,
            count=checkpoint,
        )[-1]
        expected = prefix_repository.get_state_at(
            asset="BTCUSDT",
            timeframe="1h",
            as_of=prefix_snapshot.timestamp,
        )
        assert full_lifecycle_repository.get_state_at(
            asset="BTCUSDT", timeframe="1h", as_of=snapshot.timestamp
        ) == expected
    first_context = full_lifecycle_repository.get_state_at(
        asset="BTCUSDT", timeframe="1h", as_of=full_lifecycle_snapshots[0].timestamp
    )
    assert first_context.families[0].lifecycle_state.value == "ACTIVE"


def test_storage_boundaries_exclude_research_visualization_compatibility_and_legacy() -> None:
    imports = _storage_imports()
    assert not {value for value in imports if value.startswith(_FORBIDDEN_STORAGE_IMPORTS)}
    source = "\n".join(path.read_text(encoding="utf-8") for path in _STORAGE_ROOT.rglob("*.py"))
    assert "sqlite" not in source.lower()
