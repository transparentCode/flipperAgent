"""Adversarial Phase-H checks for causal MTF composition contracts."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import timedelta
from typing import Any

import pytest

from libs.models.regime_v2.adapters.trendline_family_feature_producer import (
    summarize_trendline_family_shadow_artifacts,
)
from libs.models.trendline_family.contracts import (
    ContractValidationError,
    FamilyRole,
    TrendlineFamilySnapshot,
    canonical_json,
    compute_trendline_family_snapshot_id,
    deterministic_id,
)
from libs.models.trendline_family.mtf import (
    LatestMTFSnapshotStore,
    MTFCluster,
    MTFGeometrySnapshot,
    MTFPolicyAudit,
    MTFRelation,
    MTFSourceSnapshotAudit,
    ProjectedMTFFamily,
    ProjectedMTFMember,
    build_mtf_shadow_features,
    compose_mtf_snapshot,
    compute_mtf_snapshot_id,
    deserialize_mtf_snapshot,
)
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository
from libs.models.trendline_family.tracker import TrendlineFamilyTracker

from .test_mtf import _context, _mtf_config, _source_snapshot
from .tracker_support import (
    SequenceProvider,
    candidate,
    timestamp,
    tracker_config,
    tracker_ohlcv,
    valid_result,
)


def _member_with(member: ProjectedMTFMember, **changes: Any) -> ProjectedMTFMember:
    def value(name: str) -> Any:
        return changes.get(name, getattr(member, name))

    payload = {
        "projected_family_id": value("projected_family_id"),
        "source_snapshot_id": value("source_snapshot_id"),
        "source_timeframe": value("source_timeframe"),
        "source_family_id": value("source_family_id"),
        "source_member_id": value("source_member_id"),
        "source_candidate_id": value("source_candidate_id"),
        "source_geometry": value("source_geometry").to_dict(),
        "source_geometry_hash": value("source_geometry_hash"),
        "projected_price": value("projected_price"),
        "projected_offset_from_representative": value("projected_offset_from_representative"),
        "source_order_index": value("source_order_index"),
        "projection_timestamp": value("projection_timestamp"),
    }
    return replace(
        member,
        projected_member_id=deterministic_id("mtf-projected-member", payload),
        **changes,
    )


def _family_with(family: ProjectedMTFFamily, **changes: Any) -> ProjectedMTFFamily:
    payload = family.identity_payload()
    payload.update(changes)
    return replace(
        family,
        projected_family_id=deterministic_id("mtf-projected-family", payload),
        **changes,
    )


def _relation_with(relation: MTFRelation, **changes: Any) -> MTFRelation:
    payload = relation.identity_payload()
    payload.update(changes)
    return replace(
        relation,
        relation_id=deterministic_id("mtf-relation", payload),
        **changes,
    )


def _cluster_with(cluster: MTFCluster, **changes: Any) -> MTFCluster:
    payload = cluster.identity_payload()
    payload.update(changes)
    return replace(
        cluster,
        cluster_id=deterministic_id("mtf-cluster", payload),
        **changes,
    )


def _reidentified_payload(
    snapshot: MTFGeometrySnapshot,
    **changes: Any,
) -> dict[str, Any]:
    """Create a serialized payload whose aggregate ID matches the forged content."""

    forged = object.__new__(MTFGeometrySnapshot)
    for descriptor in fields(MTFGeometrySnapshot):
        object.__setattr__(
            forged,
            descriptor.name,
            changes.get(descriptor.name, getattr(snapshot, descriptor.name)),
        )
    object.__setattr__(forged, "mtf_snapshot_id", compute_mtf_snapshot_id(forged))
    return forged.to_dict()


def _one_source_snapshot() -> MTFGeometrySnapshot:
    observed = timestamp()
    return compose_mtf_snapshot(
        source_snapshots={
            "1h": _source_snapshot(
                timeframe="1h", observed_at=observed, reference_price=100.0
            )
        },
        decision_timestamp=observed,
        normalization_context=_context(),
        config=_mtf_config(timeframes=("1h",)),
    )


def _two_source_snapshot(*, opposite_roles: bool = False) -> MTFGeometrySnapshot:
    observed = timestamp()
    return compose_mtf_snapshot(
        source_snapshots={
            "1h": _source_snapshot(
                timeframe="1h", observed_at=observed, reference_price=100.0
            ),
            "4h": _source_snapshot(
                timeframe="4h",
                observed_at=observed,
                reference_price=100.2,
                role=FamilyRole.RESISTANCE if opposite_roles else FamilyRole.SUPPORT,
            ),
        },
        decision_timestamp=observed,
        normalization_context=_context(),
        config=_mtf_config(),
    )


def _phase_g_snapshot_with_config(config, *, observed_at):
    line = candidate(config, observed_at, candidate_id="stable-source")
    return TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(line),)),
        config=config,
    ).update(tracker_ohlcv(observed_at)).snapshot


def _incomplete_snapshot(source: TrendlineFamilySnapshot) -> TrendlineFamilySnapshot:
    diagnostics = dict(source.diagnostics)
    diagnostics["confirmed_bar"] = False
    snapshot_id = compute_trendline_family_snapshot_id(
        asset=source.asset,
        timeframe=source.timeframe,
        timestamp=source.timestamp,
        previous_snapshot_id=source.previous_snapshot_id,
        model_version=source.model_version,
        config_version=source.config_version,
        resolved_config_hash=source.resolved_config_hash,
        active_families=source.active_families,
        dormant_families=source.dormant_families,
        transitions=source.transitions,
        source_group_audits=source.source_group_audits,
        corridors=source.corridors,
        observations=source.observations,
        interaction_events=source.interaction_events,
        interaction_event_transitions=source.interaction_event_transitions,
        diagnostics=diagnostics,
    )
    return replace(source, snapshot_id=snapshot_id, diagnostics=diagnostics)


def test_mtf_policy_identity_does_not_change_phase_g_source_identity() -> None:
    observed = timestamp()
    strict = _mtf_config(max_level_distance_atr=0.5)
    relaxed = _mtf_config(max_level_distance_atr=0.7)

    strict_source = _phase_g_snapshot_with_config(strict, observed_at=observed)
    relaxed_source = _phase_g_snapshot_with_config(relaxed, observed_at=observed)

    assert strict.resolved_config_hash == relaxed.resolved_config_hash
    assert strict.mtf_config_hash != relaxed.mtf_config_hash
    assert strict_source.to_dict() == relaxed_source.to_dict()

    strict_mtf = compose_mtf_snapshot(
        source_snapshots={"1h": strict_source},
        decision_timestamp=observed,
        normalization_context=_context(),
        config=strict,
    )
    relaxed_mtf = compose_mtf_snapshot(
        source_snapshots={"1h": relaxed_source},
        decision_timestamp=observed,
        normalization_context=_context(),
        config=relaxed,
    )
    assert strict_mtf.mtf_snapshot_id != relaxed_mtf.mtf_snapshot_id
    assert strict_mtf.policy_audit.mtf_config_hash == strict.mtf_config_hash
    assert relaxed_mtf.policy_audit.mtf_config_hash == relaxed.mtf_config_hash


def test_mtf_deserialization_rejects_reidentified_false_projection_values() -> None:
    snapshot = _one_source_snapshot()
    member = snapshot.projected_members[0]
    false_member = _member_with(member, projected_price=member.projected_price + 10.0)
    false_offset = _member_with(
        member,
        projected_offset_from_representative=member.projected_offset_from_representative + 1.0,
    )

    for forged_member in (false_member, false_offset):
        payload = _reidentified_payload(snapshot, projected_members=(forged_member,))
        assert payload["mtf_snapshot_id"] != snapshot.mtf_snapshot_id
        with pytest.raises(
            ContractValidationError,
            match="projected family corridor|projected MTF members",
        ):
            deserialize_mtf_snapshot(serialize_mtf_snapshot_payload(payload))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("projected_representative_price", 110.0),
        ("projected_representative_slope_per_second", 0.1),
        ("normalized_slope_atr_per_hour", 1.0),
        ("projected_corridor_width_atr", 0.5),
    ),
)
def test_mtf_deserialization_rejects_reidentified_false_family_geometry(
    field: str,
    value: float,
) -> None:
    snapshot = _one_source_snapshot()
    original = snapshot.projected_families[0]
    changes: dict[str, Any] = {field: value}
    if field == "projected_representative_price":
        changes.update(
            projected_corridor_lower_price=value,
            projected_corridor_upper_price=value,
            projected_corridor_width_atr=0.0,
        )
    false_family = _family_with(original, **changes)
    member_changes: dict[str, Any] = {
        "projected_family_id": false_family.projected_family_id,
    }
    if field == "projected_representative_price":
        member_changes["projected_price"] = value
    false_member = _member_with(snapshot.projected_members[0], **member_changes)
    cluster_changes: dict[str, Any] = {
        "projected_family_ids": (false_family.projected_family_id,),
        "reference_projected_family_id": false_family.projected_family_id,
    }
    if field == "projected_representative_price":
        cluster_changes.update(
            minimum_projected_price=value,
            maximum_projected_price=value,
            span_atr=0.0,
        )
    false_cluster = _cluster_with(snapshot.clusters[0], **cluster_changes)
    payload = _reidentified_payload(
        snapshot,
        projected_families=(false_family,),
        projected_members=(false_member,),
        clusters=(false_cluster,),
    )
    with pytest.raises(ContractValidationError, match="projected MTF families"):
        deserialize_mtf_snapshot(serialize_mtf_snapshot_payload(payload))


def test_mtf_deserialization_rejects_false_source_freshness_and_status_audits() -> None:
    snapshot = _one_source_snapshot()
    false_reference = replace(
        snapshot.source_snapshots[0],
        source_age_seconds=1.0,
        source_age_bars=1.0 / 3600.0,
    )
    false_status = replace(snapshot.source_statuses[0], reason_codes=("forged",))

    for changes in (
        {"source_snapshots": (false_reference,)},
        {"source_statuses": (false_status,)},
    ):
        payload = _reidentified_payload(snapshot, **changes)
        with pytest.raises(ContractValidationError, match="source references|source statuses"):
            deserialize_mtf_snapshot(serialize_mtf_snapshot_payload(payload))


def test_mtf_persists_one_canonical_source_audit_and_derives_every_projection() -> None:
    snapshot = _two_source_snapshot()
    audits = snapshot.source_snapshot_audits

    assert tuple(audit.source_snapshot.timeframe for audit in audits) == ("1h", "4h")
    assert len({audit.audit_id for audit in audits}) == len(audits)
    assert tuple(audit.source_snapshot.snapshot_id for audit in audits) == tuple(
        reference.source_snapshot_id for reference in snapshot.source_snapshots
    )
    assert all(audit.source_snapshot.to_dict() for audit in audits)

    for family in snapshot.projected_families:
        source = next(
            audit.source_snapshot
            for audit in audits
            if audit.source_snapshot.snapshot_id == family.source_snapshot_id
        )
        source_family = next(item for item in source.active_families if item.family_id == family.source_family_id)
        source_corridor = next(item for item in source.corridors if item.family_id == family.source_family_id)
        source_member = next(
            item for item in source_family.members if item.member_id == family.source_representative_member_id
        )
        assert family.source_family_role is source_family.current_role
        assert family.source_family_lifecycle is source_family.lifecycle_state
        assert family.source_confidence == source_family.confidence
        assert family.source_ordered_member_ids == source_corridor.ordered_member_ids
        assert family.projected_representative_price == pytest.approx(
            source_member.geometry.value_at(snapshot.decision_timestamp)
        )


def test_mtf_rejects_fabricated_or_rewritten_canonical_source_audit() -> None:
    snapshot = _one_source_snapshot()
    source = snapshot.source_snapshot_audits[0].source_snapshot

    with pytest.raises(ContractValidationError, match="snapshot_id"):
        MTFSourceSnapshotAudit.from_snapshot(replace(source, snapshot_id="fabricated-source-id"))

    alternate = _source_snapshot(
        timeframe="1h",
        observed_at=timestamp(),
        reference_price=110.0,
    )
    rewritten_audit = MTFSourceSnapshotAudit.from_snapshot(alternate)
    payload = _reidentified_payload(
        snapshot,
        source_snapshot_audits=(rewritten_audit,),
    )
    with pytest.raises(ContractValidationError, match="source references"):
        deserialize_mtf_snapshot(serialize_mtf_snapshot_payload(payload))


def test_mtf_snapshot_and_cluster_identity_must_equal_policy_audit() -> None:
    snapshot = _two_source_snapshot()
    policy_model_payload = _reidentified_payload(snapshot, model_version="forged-model")
    with pytest.raises(ContractValidationError, match="policy audit"):
        deserialize_mtf_snapshot(serialize_mtf_snapshot_payload(policy_model_payload))

    forged_cluster = _cluster_with(snapshot.clusters[0], model_version="forged-model")
    cluster_payload = _reidentified_payload(snapshot, clusters=(forged_cluster,))
    with pytest.raises(ContractValidationError, match="cluster model/config identity"):
        deserialize_mtf_snapshot(serialize_mtf_snapshot_payload(cluster_payload))


def test_mtf_rejects_reidentified_audit_timeframe_outside_policy_allowlist() -> None:
    snapshot = _two_source_snapshot()
    restricted_config = _mtf_config(timeframes=("1h",))
    restricted_policy = MTFPolicyAudit.from_config(
        config=restricted_config,
        decision_timeframe="1h",
    )
    reidentified_clusters = tuple(
        _cluster_with(cluster, resolved_config_hash=restricted_policy.mtf_config_hash)
        for cluster in snapshot.clusters
    )
    payload = _reidentified_payload(
        snapshot,
        policy_audit=restricted_policy,
        clusters=reidentified_clusters,
        resolved_config_hash=restricted_policy.mtf_config_hash,
    )

    with pytest.raises(ContractValidationError, match="not configured for MTF"):
        deserialize_mtf_snapshot(serialize_mtf_snapshot_payload(payload))


def test_mtf_policy_rejects_empty_and_alias_allowlists_independently() -> None:
    snapshot = _one_source_snapshot()
    with pytest.raises(ContractValidationError, match="must not be empty"):
        replace(snapshot.policy_audit, source_timeframes=())

    for aliases in (("1h", "60m"), ("1d", "24h"), ("1w", "7d")):
        with pytest.raises(ContractValidationError, match="equivalent-duration"):
            replace(snapshot.policy_audit, source_timeframes=aliases)


def test_mtf_empty_source_mapping_yields_missing_statuses_and_distinct_replay() -> None:
    observed = timestamp()
    config = _mtf_config(timeframes=("1h", "4h", "1d"))
    empty = compose_mtf_snapshot(
        source_snapshots={},
        decision_timestamp=observed,
        normalization_context=_context(),
        config=config,
    )
    assert tuple(status.source_timeframe for status in empty.source_statuses) == ("1h", "4h", "1d")
    assert all(status.freshness_state.value == "MISSING" for status in empty.source_statuses)

    sources = {
        "1h": _source_snapshot(timeframe="1h", observed_at=observed, reference_price=100.0),
        "4h": _source_snapshot(timeframe="4h", observed_at=observed, reference_price=100.2),
        "1d": _source_snapshot(timeframe="1d", observed_at=observed, reference_price=100.4),
    }
    forward = compose_mtf_snapshot(
        source_snapshots=sources,
        decision_timestamp=observed,
        normalization_context=_context(),
        config=config,
    )
    reverse = compose_mtf_snapshot(
        source_snapshots=dict(reversed(tuple(sources.items()))),
        decision_timestamp=observed,
        normalization_context=_context(),
        config=config,
    )
    assert forward.to_dict() == reverse.to_dict()


@pytest.mark.parametrize("relation_type", ("AGREEMENT", "CONFLUENCE", "NESTED"))
def test_mtf_deserialization_rejects_reidentified_conflict_relabels(relation_type: str) -> None:
    snapshot = _two_source_snapshot(opposite_roles=True)
    relation = snapshot.relations[0]
    assert relation.relation_type.value == "CONFLICT"
    forged = _relation_with(relation, relation_type=relation_type)
    payload = _reidentified_payload(snapshot, relations=(forged,))
    with pytest.raises(ContractValidationError, match="relations do not match"):
        deserialize_mtf_snapshot(serialize_mtf_snapshot_payload(payload))


def test_mtf_deserialization_rejects_missing_duplicate_and_false_cluster_evidence() -> None:
    snapshot = _two_source_snapshot()
    relation = snapshot.relations[0]
    false_cluster = _cluster_with(
        snapshot.clusters[0],
        is_confluence=False,
        confluence_strength=None,
        reason_codes=("complete_linkage_v1", "singleton_or_subthreshold"),
    )
    bad_payloads = (
        _reidentified_payload(snapshot, relations=()),
        _reidentified_payload(snapshot, relations=(relation, relation)),
        _reidentified_payload(snapshot, clusters=(false_cluster,)),
    )
    for payload in bad_payloads:
        with pytest.raises(ContractValidationError, match="relations require|relations do not match|clusters do not match"):
            deserialize_mtf_snapshot(serialize_mtf_snapshot_payload(payload))


def test_mtf_complete_linkage_does_not_chain_overmerge() -> None:
    observed = timestamp()
    snapshot = compose_mtf_snapshot(
        source_snapshots={
            "1h": _source_snapshot(timeframe="1h", observed_at=observed, reference_price=100.0),
            "4h": _source_snapshot(timeframe="4h", observed_at=observed, reference_price=101.5),
            "1d": _source_snapshot(timeframe="1d", observed_at=observed, reference_price=103.0),
        },
        decision_timestamp=observed,
        normalization_context=_context(),
        config=_mtf_config(timeframes=("1h", "4h", "1d"), max_level_distance_atr=1.0),
    )
    assert max(cluster.family_count for cluster in snapshot.clusters) == 2
    assert len(snapshot.clusters) == 2


def test_latest_mtf_store_rejects_independent_branch_and_incomplete_source_atomically() -> None:
    observed = timestamp()
    first = _source_snapshot(timeframe="1h", observed_at=observed, reference_price=100.0)
    branch = _source_snapshot(
        timeframe="1h", observed_at=observed + timedelta(hours=1), reference_price=101.0
    )
    store = LatestMTFSnapshotStore(asset="BTCUSDT")
    assert store.update(first) is True
    head_before = store.latest_sources()["1h"].to_dict()

    with pytest.raises(ContractValidationError, match="continue the stored source lineage"):
        store.update(branch)
    assert store.latest_sources()["1h"].to_dict() == head_before

    incomplete = _incomplete_snapshot(first)
    with pytest.raises(ContractValidationError, match="incomplete source snapshot"):
        store.update(incomplete)
    with pytest.raises(ContractValidationError, match="incomplete source snapshot"):
        compose_mtf_snapshot(
            source_snapshots={"1h": incomplete},
            decision_timestamp=observed,
            normalization_context=_context(),
            config=_mtf_config(timeframes=("1h",)),
        )
    assert store.latest_sources()["1h"].to_dict() == head_before


def test_latest_mtf_store_accepts_only_continuous_asynchronous_source_heads() -> None:
    observed = timestamp()
    config = tracker_config()
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider(
            (
                valid_result(candidate(config, observed, candidate_id="first")),
                valid_result(
                    candidate(
                        config,
                        observed + timedelta(hours=1),
                        candidate_id="second",
                    )
                ),
            )
        ),
        config=config,
    )
    first = tracker.update(tracker_ohlcv(observed)).snapshot
    second = tracker.update(tracker_ohlcv(observed + timedelta(hours=1))).snapshot
    assert second.previous_snapshot_id == first.snapshot_id

    store = LatestMTFSnapshotStore(asset="BTCUSDT")
    assert store.update(first) is True
    assert store.update(first) is False
    assert store.update(second) is True
    assert store.latest_sources()["1h"].snapshot_id == second.snapshot_id


def test_mtf_source_arrival_order_is_semantically_invariant() -> None:
    observed = timestamp()
    sources = {
        "1h": _source_snapshot(timeframe="1h", observed_at=observed, reference_price=100.0),
        "4h": _source_snapshot(timeframe="4h", observed_at=observed, reference_price=100.2),
    }
    first = LatestMTFSnapshotStore(asset="BTCUSDT")
    second = LatestMTFSnapshotStore(asset="BTCUSDT")
    for timeframe in ("1h", "4h"):
        assert first.update(sources[timeframe]) is True
    for timeframe in ("4h", "1h"):
        assert second.update(sources[timeframe]) is True
    assert first.compose(
        decision_timestamp=observed,
        normalization_context=_context(),
        config=_mtf_config(),
    ).to_dict() == second.compose(
        decision_timestamp=observed,
        normalization_context=_context(),
        config=_mtf_config(),
    ).to_dict()


def _two_rail_source(*, crossing: bool, suffix: int = 0):
    observed = timestamp()
    config = tracker_config(
        matching={"max_slope_delta_atr_per_hour": 1.0},
        rails={"max_group_slope_delta_atr_per_hour": 1.0},
    )
    if crossing:
        candidates = (
            candidate(
                config,
                observed,
                candidate_id="lower-steep",
                reference_price=99.4,
                slope_per_hour=0.2,
            ),
            candidate(
                config,
                observed,
                candidate_id="upper-shallow",
                reference_price=101.0,
                slope_per_hour=-0.1,
            ),
        )
        decision = observed + timedelta(hours=3)
    else:
        candidates = (
            candidate(config, observed, candidate_id=f"higher-{suffix}", reference_price=100.4),
            candidate(config, observed, candidate_id=f"lower-{suffix}", reference_price=100.0),
        )
        decision = observed
    source = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(*candidates),)),
        config=config,
    ).update(tracker_ohlcv(observed)).snapshot
    return source, decision


def test_mtf_projected_order_uses_source_corridor_order_and_detects_real_crossing() -> None:
    for suffix in range(32):
        stable_source, stable_decision = _two_rail_source(crossing=False, suffix=suffix)
        if (
            tuple(member.member_id for member in stable_source.active_families[0].members)
            != stable_source.corridors[0].ordered_member_ids
        ):
            break
    else:  # pragma: no cover - deterministic UUID fixtures should always provide one pair.
        pytest.fail("could not construct lexical member order distinct from source corridor order")
    stable = compose_mtf_snapshot(
        source_snapshots={"1h": stable_source},
        decision_timestamp=stable_decision,
        normalization_context=_context(),
        config=_mtf_config(timeframes=("1h",)),
    )
    stable_family = stable.projected_families[0]
    corridor = stable_source.corridors[0]
    source_family = stable_source.active_families[0]
    assert tuple(member.member_id for member in source_family.members) != corridor.ordered_member_ids
    assert stable_family.source_ordered_member_ids == corridor.ordered_member_ids
    assert stable_family.projected_order_changed is False

    crossing_source, crossing_decision = _two_rail_source(crossing=True)
    crossing = compose_mtf_snapshot(
        source_snapshots={"1h": crossing_source},
        decision_timestamp=crossing_decision,
        normalization_context=_context(),
        config=_mtf_config(timeframes=("1h",)),
    )
    assert crossing.projected_families[0].projected_order_changed is True
    assert {
        member.source_member_id for member in crossing.projected_members
    } == set(crossing_source.corridors[0].ordered_member_ids)


def test_mtf_intersection_and_artifacts_preserve_orthogonal_facts() -> None:
    observed = timestamp()
    snapshot = compose_mtf_snapshot(
        source_snapshots={
            "1h": _source_snapshot(
                timeframe="1h", observed_at=observed, reference_price=100.0, slope_per_hour=0.5
            ),
            "4h": _source_snapshot(
                timeframe="4h",
                observed_at=observed,
                reference_price=105.0,
                slope_per_hour=-0.5,
                role=FamilyRole.RESISTANCE,
            ),
        },
        decision_timestamp=observed,
        normalization_context=_context(),
        config=_mtf_config(max_level_distance_atr=2.0),
    )
    relation = snapshot.relations[0]
    assert relation.relation_type.value == "CONFLICT"
    assert relation.intersection_horizon_eligible is True

    features = build_mtf_shadow_features(snapshot)
    artifacts = summarize_trendline_family_shadow_artifacts(
        ({"trendline_family_shadow": {"trendline_family_shadow_enabled": True, "mtf": features}},)
    )["distributions"]
    assert features["intersection_relation_count"] == 1
    assert artifacts["mtf_intersection_relation_count"] == {"1": 1}
    assert artifacts["mtf_intersection_seconds_from_decision"]
    assert artifacts["mtf_intersection_horizon_seconds"] == {"86400": 1}


def test_mtf_artifacts_use_persisted_cluster_sequences() -> None:
    snapshot = _two_source_snapshot()
    features = build_mtf_shadow_features(snapshot)
    distributions = summarize_trendline_family_shadow_artifacts(
        ({"trendline_family_shadow": {"trendline_family_shadow_enabled": True, "mtf": features}},)
    )["distributions"]

    assert distributions["mtf_cluster_size"] == {"2": 1}
    assert distributions["mtf_cluster_distinct_timeframe_count"] == {"2": 1}
    for key in (
        "mtf_source_timeframe_coverage",
        "mtf_source_age_bars",
        "mtf_confluence_strength",
        "mtf_normalized_slope_dispersion",
        "mtf_corridor_overlap_ratio",
        "mtf_exclusion_reason",
    ):
        assert key in distributions


def serialize_mtf_snapshot_payload(payload: dict[str, Any]) -> str:
    """Keep adversarial tests on the public JSON deserialization boundary."""

    return canonical_json(payload)
