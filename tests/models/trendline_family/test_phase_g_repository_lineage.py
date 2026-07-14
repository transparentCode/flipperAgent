"""Phase-G repository lineage audit coverage for exact multi-rail membership."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from libs.models.trendline_family.contracts import (
    ContractValidationError,
    FamilyRole,
    FamilyTransition,
    FamilyTransitionType,
    TrendlineFamilySnapshot,
    compute_trendline_family_snapshot_id,
    deterministic_id,
)
from libs.models.trendline_family.repository import (
    InMemoryTrendlineFamilyRepository,
    SnapshotVersionError,
    serialize_snapshot,
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


def _growth_history() -> tuple[TrendlineFamilySnapshot, TrendlineFamilySnapshot]:
    config = tracker_config()
    first_time, second_time = timestamp(), timestamp(1)
    seed = candidate(config, first_time, candidate_id="seed", anchor_prefix="seed")
    continued = replace(
        candidate(
            config,
            second_time,
            candidate_id="seed-next",
            anchor_prefix="seed",
        ),
        anchors=seed.anchors,
    )
    added = candidate(
        config,
        second_time,
        candidate_id="added",
        reference_price=100.4,
        anchor_prefix="added",
    )
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(seed), valid_result(continued, added))),
        config=config,
    )
    return (
        tracker.update(tracker_ohlcv(first_time)).snapshot,
        tracker.update(tracker_ohlcv(second_time)).snapshot,
    )


def _fresh_repository(previous: TrendlineFamilySnapshot) -> InMemoryTrendlineFamilyRepository:
    repository = InMemoryTrendlineFamilyRepository()
    repository.save_snapshot(previous)
    return repository


def _resulting_family(
    snapshot: TrendlineFamilySnapshot,
    transition: FamilyTransition,
):
    return next(
        (
            family
            for family in snapshot.active_families + snapshot.dormant_families
            if family.family_id == transition.family_id
        ),
        None,
    )


def _reidentified_transition(
    snapshot: TrendlineFamilySnapshot,
    transition: FamilyTransition,
    **changes: object,
) -> FamilyTransition:
    if "source_group_candidate_ids" in changes:
        # Provenance tests must also replace the typed audit record. All other
        # forged transition tests retain the real snapshot-local source group.
        changes.setdefault("source_group_id", None)
    provisional = replace(transition, **changes)
    payload = provisional.to_dict()
    payload.pop("transition_id")
    family = _resulting_family(snapshot, provisional)
    return replace(
        provisional,
        transition_id=deterministic_id(
            "family-transition",
            {
                "transition": payload,
                "resulting_family_state": None if family is None else family.to_dict(),
            },
        ),
    )


def _unsafe_reidentified_transition(
    snapshot: TrendlineFamilySnapshot,
    transition: FamilyTransition,
    **changes: object,
) -> FamilyTransition:
    """Model corrupt serialized transition fields after local contract creation."""

    forged = replace(transition)
    for name, value in changes.items():
        object.__setattr__(forged, name, value)
    payload = forged.to_dict()
    payload.pop("transition_id")
    family = _resulting_family(snapshot, forged)
    object.__setattr__(
        forged,
        "transition_id",
        deterministic_id(
            "family-transition",
            {
                "transition": payload,
                "resulting_family_state": None if family is None else family.to_dict(),
            },
        ),
    )
    return forged


def _reidentified_snapshot(
    snapshot: TrendlineFamilySnapshot,
    **changes: object,
) -> TrendlineFamilySnapshot:
    identity_fields = (
        "asset",
        "timeframe",
        "timestamp",
        "previous_snapshot_id",
        "model_version",
        "config_version",
        "resolved_config_hash",
        "active_families",
        "dormant_families",
        "transitions",
        "source_group_audits",
        "corridors",
        "observations",
        "interaction_events",
        "interaction_event_transitions",
        "diagnostics",
    )
    identity_inputs = {
        field: changes.get(field, getattr(snapshot, field))
        for field in identity_fields
    }
    return replace(
        snapshot,
        snapshot_id=compute_trendline_family_snapshot_id(**identity_inputs),
        **changes,
    )


def _assert_save_rejected_without_head_change(
    repository: InMemoryTrendlineFamilyRepository,
    snapshot: TrendlineFamilySnapshot,
    *,
    match: str,
) -> None:
    before = repository.latest_snapshot(snapshot.asset, snapshot.timeframe)
    assert before is not None
    with pytest.raises(SnapshotVersionError, match=match):
        repository.save_snapshot(snapshot)
    after = repository.latest_snapshot(snapshot.asset, snapshot.timeframe)
    assert after is not None
    assert serialize_snapshot(after) == serialize_snapshot(before)


def test_phase_g_snapshot_rejects_missing_or_duplicate_current_family_transition() -> None:
    _, grown = _growth_history()
    transition = grown.transitions[0]

    with pytest.raises(ContractValidationError, match="current family transition"):
        replace(grown, transitions=())
    with pytest.raises(ContractValidationError, match="at most one transition per family"):
        replace(
            grown,
            transitions=(
                transition,
                replace(transition, transition_id="duplicate-family-transition"),
            ),
        )


def test_repository_rejects_forged_member_partition_and_preserves_head() -> None:
    previous, grown = _growth_history()
    repository = _fresh_repository(previous)
    transition = grown.transitions[0]
    current_member_ids = tuple(
        sorted(member.member_id for member in grown.active_families[0].members)
    )
    forged = _reidentified_transition(
        grown,
        transition,
        added_member_ids=current_member_ids,
        continued_member_ids=(),
        removed_member_ids=("fabricated-old-member",),
        previous_rail_count=1,
        current_rail_count=2,
    )

    _assert_save_rejected_without_head_change(
        repository,
        _reidentified_snapshot(grown, transitions=(forged,)),
        match="added_member_ids",
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        (
            {
                "previous_representative_member_id": "fabricated-previous-representative",
                "representative_changed": True,
            },
            "previous representative",
        ),
        (
            {"matched_candidate_ids": ("fabricated-candidate",)},
            "matched transition candidates",
        ),
    ),
)
def test_repository_rejects_forged_transition_audit_facts(
    changes: dict[str, object],
    message: str,
) -> None:
    previous, grown = _growth_history()
    repository = _fresh_repository(previous)
    forged = _reidentified_transition(grown, grown.transitions[0], **changes)

    _assert_save_rejected_without_head_change(
        repository,
        _reidentified_snapshot(grown, transitions=(forged,)),
        match=message,
    )


def test_repository_rejects_false_rail_counts_across_lineage() -> None:
    previous, grown = _growth_history()
    repository = _fresh_repository(previous)
    forged = _unsafe_reidentified_transition(
        grown,
        grown.transitions[0],
        previous_rail_count=0,
    )

    _assert_save_rejected_without_head_change(
        repository,
        _reidentified_snapshot(grown, transitions=(forged,)),
        match="previous_rail_count",
    )


def test_repository_rejects_phase_g_diagnostic_downgrade_and_preserves_head() -> None:
    previous, grown = _growth_history()
    repository = _fresh_repository(previous)
    downgraded_diagnostics = dict(grown.diagnostics)
    downgraded_diagnostics.pop("rail_grouping_enabled")
    downgraded = replace(grown)
    object.__setattr__(downgraded, "transitions", ())
    object.__setattr__(downgraded, "source_group_audits", ())
    object.__setattr__(downgraded, "diagnostics", downgraded_diagnostics)

    _assert_save_rejected_without_head_change(
        repository,
        downgraded,
        match="Phase-G evidence requires",
    )


def _dormancy_and_reactivation_history() -> tuple[TrendlineFamilySnapshot, ...]:
    config = tracker_config(
        lifecycle={
            "active_grace_bars": 0,
            "dormant_after_bars": 1,
            "expire_after_bars": 3,
            "confidence_decay_per_unmatched_bar": 0.10,
            "reactivation_min_score": 0.70,
        }
    )
    first_time, dormant_time, reactivated_time = timestamp(), timestamp(1), timestamp(2)
    seed = candidate(config, first_time, candidate_id="seed", anchor_prefix="seed")
    reactivated = replace(
        candidate(
            config,
            reactivated_time,
            candidate_id="seed-reactivated",
            anchor_prefix="seed",
        ),
        anchors=seed.anchors,
    )
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider(
            (valid_result(seed), abstention(), valid_result(reactivated))
        ),
        config=config,
    )
    return (
        tracker.update(tracker_ohlcv(first_time)).snapshot,
        tracker.update(tracker_ohlcv(dormant_time)).snapshot,
        tracker.update(tracker_ohlcv(reactivated_time)).snapshot,
    )


@pytest.mark.parametrize(
    ("history_index", "replacement_type", "message"),
    (
        (1, FamilyTransitionType.CONTINUE, "ACTIVE to DORMANT"),
        (2, FamilyTransitionType.CONTINUE, "DORMANT to ACTIVE"),
    ),
)
def test_repository_rejects_false_lifecycle_transition_labels(
    history_index: int,
    replacement_type: FamilyTransitionType,
    message: str,
) -> None:
    snapshots = _dormancy_and_reactivation_history()
    repository = InMemoryTrendlineFamilyRepository()
    for prior in snapshots[:history_index]:
        repository.save_snapshot(prior)
    current = snapshots[history_index]
    forged = _reidentified_transition(
        current,
        current.transitions[0],
        transition_type=replacement_type,
    )

    _assert_save_rejected_without_head_change(
        repository,
        _reidentified_snapshot(current, transitions=(forged,)),
        match=message,
    )


def test_repository_rejects_false_reactivate_on_active_continuation() -> None:
    previous, grown = _growth_history()
    repository = _fresh_repository(previous)
    forged = _reidentified_transition(
        grown,
        grown.transitions[0],
        transition_type=FamilyTransitionType.REACTIVATE,
    )

    _assert_save_rejected_without_head_change(
        repository,
        _reidentified_snapshot(grown, transitions=(forged,)),
        match="matched ACTIVE transition",
    )


def test_repository_requires_expiry_transition_for_removed_phase_g_family() -> None:
    config = tracker_config()
    times = tuple(timestamp(index) for index in range(6))
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider(
            (valid_result(candidate(config, times[0])),)
            + tuple(abstention() for _ in times[1:])
        ),
        config=config,
    )
    snapshots = [tracker.update(tracker_ohlcv(current)).snapshot for current in times]
    expiry = snapshots[-1]
    repository = InMemoryTrendlineFamilyRepository()
    for prior in snapshots[:-1]:
        repository.save_snapshot(prior)

    _assert_save_rejected_without_head_change(
        repository,
        _reidentified_snapshot(expiry, transitions=()),
        match="complete family transition coverage",
    )


def test_repository_requires_birth_transition_for_first_phase_g_snapshot() -> None:
    first, _ = _growth_history()
    with pytest.raises(ContractValidationError, match="current family transition"):
        replace(first, transitions=())


def _role_reversal_history() -> tuple[TrendlineFamilySnapshot, ...]:
    config = tracker_config()
    times = tuple(timestamp(index) for index in range(5))
    provider = SequenceProvider(
        tuple(
            valid_result(
                candidate(
                    config,
                    observed,
                    candidate_id=f"candidate-{index}",
                    role=(
                        FamilyRole.RESISTANCE
                        if index == len(times) - 1
                        else FamilyRole.SUPPORT
                    ),
                    reference_price=100.2 if index == len(times) - 1 else 100.0,
                )
            )
            for index, observed in enumerate(times)
        )
    )
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=provider,
        config=config,
    )
    candles = (
        (99.4, 100.0, 98.8, 99.0),
        (99.4, 100.0, 98.8, 99.0),
        (99.6, 100.2, 99.4, 99.9),
        (99.4, 100.0, 98.8, 99.0),
        (100.0, 100.2, 99.8, 100.0),
    )
    snapshots = []
    for observed, candle in zip(times, candles, strict=True):
        frame = tracker_ohlcv(observed)
        frame.iloc[-1] = candle
        snapshots.append(tracker.update(frame).snapshot)
    return tuple(snapshots)


def test_repository_rejects_role_reversal_membership_drift() -> None:
    snapshots = _role_reversal_history()
    previous, reversed_snapshot = snapshots[-2:]
    repository = InMemoryTrendlineFamilyRepository()
    for prior in snapshots[:-1]:
        repository.save_snapshot(prior)
    transition = reversed_snapshot.transitions[0]
    family = reversed_snapshot.active_families[0]
    member_ids = tuple(member.member_id for member in family.members)
    forged = _reidentified_transition(
        reversed_snapshot,
        transition,
        added_member_ids=member_ids,
        continued_member_ids=(),
        removed_member_ids=("fabricated-prior-member",),
        previous_rail_count=len(member_ids),
        current_rail_count=len(member_ids),
    )

    _assert_save_rejected_without_head_change(
        repository,
        _reidentified_snapshot(reversed_snapshot, transitions=(forged,)),
        match="added_member_ids",
    )


@pytest.mark.parametrize(
    "transition_type",
    (
        FamilyTransitionType.CONTINUE,
        FamilyTransitionType.STRENGTHEN,
        FamilyTransitionType.WEAKEN,
    ),
)
def test_repository_rejects_role_change_without_role_reversed_transition(
    transition_type: FamilyTransitionType,
) -> None:
    snapshots = _role_reversal_history()
    repository = InMemoryTrendlineFamilyRepository()
    for prior in snapshots[:-1]:
        repository.save_snapshot(prior)
    reversed_snapshot = snapshots[-1]
    forged = _reidentified_transition(
        reversed_snapshot,
        reversed_snapshot.transitions[0],
        transition_type=transition_type,
    )

    _assert_save_rejected_without_head_change(
        repository,
        _reidentified_snapshot(reversed_snapshot, transitions=(forged,)),
        match="role change requires ROLE_REVERSED",
    )


def test_repository_rejects_role_reversed_without_role_change() -> None:
    previous, grown = _growth_history()
    repository = _fresh_repository(previous)
    forged = _reidentified_transition(
        grown,
        grown.transitions[0],
        transition_type=FamilyTransitionType.ROLE_REVERSED,
    )

    _assert_save_rejected_without_head_change(
        repository,
        _reidentified_snapshot(grown, transitions=(forged,)),
        match="requires a family role change",
    )


@pytest.mark.parametrize(
    ("transition_timestamp", "message"),
    (
        (lambda previous, _: previous.timestamp, "timestamp must match snapshot"),
        (
            lambda _, current: current.timestamp + timedelta(hours=1),
            "timestamp cannot exceed snapshot",
        ),
    ),
)
def test_phase_g_snapshot_rejects_non_current_transition_timestamp(
    transition_timestamp,
    message: str,
) -> None:
    previous, grown = _growth_history()
    forged = _reidentified_transition(
        grown,
        grown.transitions[0],
        timestamp=transition_timestamp(previous, grown),
    )

    with pytest.raises(ContractValidationError, match=message):
        replace(grown, transitions=(forged,))


def test_phase_g_snapshot_rejects_missing_or_mismatched_source_group_evidence() -> None:
    snapshots = _role_reversal_history()
    reversed_snapshot = snapshots[-1]
    transition = reversed_snapshot.transitions[0]

    with pytest.raises(ContractValidationError, match="exactly cover transition provenance"):
        replace(reversed_snapshot, source_group_audits=())
    forged = _reidentified_transition(
        reversed_snapshot,
        transition,
        source_group_id=transition.source_group_id,
        source_group_candidate_ids=("fabricated-reversal-source",),
    )
    with pytest.raises(ContractValidationError, match="candidates must match transition provenance"):
        replace(reversed_snapshot, transitions=(forged,))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("role", FamilyRole.SUPPORT, "identity must match snapshot and family"),
        ("observed_at", timestamp(1), "identity must match snapshot and family"),
        ("model_version", "incompatible-model", "identity must match snapshot and family"),
        ("candidate_ids", ("fabricated-reversal-source",), "candidates must match transition provenance"),
    ),
)
def test_phase_g_snapshot_rejects_source_group_cross_field_mismatch(
    field: str,
    value: object,
    message: str,
) -> None:
    reversed_snapshot = _role_reversal_history()[-1]
    audit = replace(reversed_snapshot.source_group_audits[0])
    object.__setattr__(audit, field, value)

    with pytest.raises(ContractValidationError, match=message):
        replace(reversed_snapshot, source_group_audits=(audit,))


def test_legacy_phase_f_repository_lineage_remains_accepted(snapshot) -> None:
    repository = InMemoryTrendlineFamilyRepository()
    repository.save_snapshot(snapshot)
    family = snapshot.active_families[0]
    next_timestamp = snapshot.timestamp + timedelta(hours=4)
    continued = FamilyTransition(
        transition_id="legacy-transition-2",
        family_id=family.family_id,
        timestamp=next_timestamp,
        transition_type=FamilyTransitionType.CONTINUE,
        previous_version=1,
        new_version=2,
        matched_candidate_ids=(),
        association_score=None,
        reason_codes=("legacy",),
        metrics={},
        model_version=snapshot.model_version,
        config_version=snapshot.config_version,
        resolved_config_hash=snapshot.resolved_config_hash,
    )
    legacy_next = replace(
        snapshot,
        snapshot_id="legacy-snapshot-2",
        timestamp=next_timestamp,
        previous_snapshot_id=snapshot.snapshot_id,
        active_families=(
            replace(
                family,
                updated_at=next_timestamp,
                last_confirmed_at=next_timestamp,
                age_bars=family.age_bars + 1,
                version=2,
            ),
        ),
        transitions=(continued,),
    )

    repository.save_snapshot(legacy_next)
    assert repository.latest_snapshot(snapshot.asset, snapshot.timeframe) == legacy_next
