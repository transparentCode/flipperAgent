"""Phase-H causal composition over immutable, confirmed Phase-G snapshots."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from libs.models.trendline_family.config import MTFConfig
from libs.models.trendline_family.config_resolver import TrendlineFamilyConfigResolver
from libs.models.trendline_family.contracts import ContractValidationError, FamilyRole
from libs.models.trendline_family.mtf import (
    LatestMTFSnapshotStore,
    MTFFreshnessState,
    MTFNormalizationContext,
    MTFRelationType,
    build_mtf_shadow_features,
    compose_mtf_snapshot,
    deserialize_mtf_snapshot,
    serialize_mtf_snapshot,
)
from libs.models.regime_v2.adapters.trendline_family_feature_producer import (
    TrendlineFamilyFeatureProducer,
    TrendlineFamilyShadowConfig,
    summarize_trendline_family_shadow_artifacts,
)
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository
from libs.models.trendline_family.tracker import TrendlineFamilyTracker

from .tracker_support import (
    SequenceProvider,
    candidate,
    timestamp,
    tracker_config,
    tracker_ohlcv,
    valid_result,
)


def _source_snapshot(
    *,
    timeframe: str,
    observed_at,
    reference_price: float,
    slope_per_hour: float = 0.0,
    role: FamilyRole = FamilyRole.SUPPORT,
):
    config = tracker_config(timeframe=timeframe)
    line = candidate(
        config,
        observed_at,
        candidate_id=f"{timeframe}-{role.value.lower()}-{reference_price}",
        anchor_prefix=f"{timeframe}-{role.value.lower()}",
        reference_price=reference_price,
        slope_per_hour=slope_per_hour,
        role=role,
    )
    return TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(line),)),
        config=config,
    ).update(tracker_ohlcv(observed_at)).snapshot


def _mtf_config(*, timeframes: tuple[str, ...] = ("1h", "4h"), **overrides):
    defaults = {
        "enabled": True,
        "source_timeframes": list(timeframes),
        "minimum_confluence_timeframes": 2,
        "max_source_age_bars": 4.0,
        "stale_include_age_bars": 1.0,
        "max_level_distance_atr": 1.0,
        "max_corridor_separation_atr": 1.0,
        "max_slope_delta_atr_per_hour": 1.0,
        "intersection_horizon_bars": 24,
        "normalization_policy": "decision_timeframe_atr",
    }
    defaults.update(overrides)
    return TrendlineFamilyConfigResolver(
        {"version": "phase-h", "defaults": {"mtf": defaults}}
    ).resolve(asset="BTCUSDT", timeframe="1h")


def _context(*, price: float | None = 100.0) -> MTFNormalizationContext:
    return MTFNormalizationContext(
        asset="BTCUSDT",
        decision_timeframe="1h",
        atr=2.0,
        decision_price=price,
    )


def test_mtf_projection_is_exact_deterministic_and_round_trips() -> None:
    observed = timestamp()
    sources = {
        "1h": _source_snapshot(timeframe="1h", observed_at=observed, reference_price=100.0),
        "4h": _source_snapshot(timeframe="4h", observed_at=observed, reference_price=100.2),
    }
    decision = observed + timedelta(hours=1)
    config = _mtf_config()

    forward = compose_mtf_snapshot(
        source_snapshots=sources,
        decision_timestamp=decision,
        normalization_context=_context(),
        config=config,
    )
    reverse = compose_mtf_snapshot(
        source_snapshots=dict(reversed(tuple(sources.items()))),
        decision_timestamp=decision,
        normalization_context=_context(),
        config=config,
    )

    assert forward.to_dict() == reverse.to_dict()
    assert deserialize_mtf_snapshot(serialize_mtf_snapshot(forward)) == forward
    assert len(forward.projected_families) == 2
    assert len(forward.projected_members) == 2
    for family in forward.projected_families:
        source = sources[family.source_timeframe]
        source_family = source.active_families[0]
        assert family.projected_representative_price == pytest.approx(
            source_family.representative.value_at(decision)
        )
        assert family.projected_corridor_lower_price == family.projected_corridor_upper_price
    assert any(
        relation.relation_type in {MTFRelationType.AGREEMENT, MTFRelationType.CONFLUENCE}
        for relation in forward.relations
    )
    assert forward.clusters[0].is_confluence is True


def test_mtf_causality_staleness_and_missing_sources_are_explicit() -> None:
    observed = timestamp()
    source = _source_snapshot(timeframe="4h", observed_at=observed, reference_price=100.0)
    decision = observed + timedelta(hours=8)
    snapshot = compose_mtf_snapshot(
        source_snapshots={"4h": source},
        decision_timestamp=decision,
        normalization_context=_context(),
        config=_mtf_config(max_source_age_bars=3.0, stale_include_age_bars=1.0),
    )

    assert snapshot.source_snapshots[0].freshness_state is MTFFreshnessState.STALE_INCLUDED
    assert snapshot.source_statuses[0].source_timeframe == "1h"
    assert snapshot.source_statuses[0].freshness_state is MTFFreshnessState.MISSING
    features = build_mtf_shadow_features(snapshot)
    assert features["stale_included_source_count"] == 1
    assert features["source_timeframe_count"] == 1
    assert features["nearest_support_mtf_cluster_id"] is None

    stale = compose_mtf_snapshot(
        source_snapshots={"4h": source},
        decision_timestamp=observed + timedelta(hours=20),
        normalization_context=_context(),
        config=_mtf_config(max_source_age_bars=3.0, stale_include_age_bars=1.0),
    )
    assert stale.source_snapshots[0].freshness_state is MTFFreshnessState.STALE_EXCLUDED
    assert stale.clusters == ()


def test_mtf_rejects_future_and_preserves_source_snapshot() -> None:
    observed = timestamp()
    source = _source_snapshot(timeframe="1h", observed_at=observed, reference_price=100.0)
    original = source.to_dict()
    config = _mtf_config(timeframes=("1h",))

    with pytest.raises(ContractValidationError, match="future source snapshot"):
        compose_mtf_snapshot(
            source_snapshots={"1h": source},
            decision_timestamp=observed - timedelta(seconds=1),
            normalization_context=_context(),
            config=config,
        )
    assert source.to_dict() == original


def test_latest_store_is_idempotent_and_refuses_older_source() -> None:
    observed = timestamp()
    source = _source_snapshot(timeframe="1h", observed_at=observed, reference_price=100.0)
    store = LatestMTFSnapshotStore(asset="BTCUSDT")

    assert store.update(source) is True
    assert store.update(source) is False
    conflicting = _source_snapshot(timeframe="1h", observed_at=observed, reference_price=101.0)
    with pytest.raises(ContractValidationError, match="older or conflicting"):
        store.update(conflicting)


def test_mtf_config_is_strict_and_part_of_the_resolved_hash() -> None:
    with pytest.raises(ContractValidationError, match="cannot be below"):
        MTFConfig(max_source_age_bars=0.5, stale_include_age_bars=1.0)
    with pytest.raises(ContractValidationError, match="duplicates"):
        MTFConfig(source_timeframes=("1h", "1h"))

    first = _mtf_config(max_level_distance_atr=0.5)
    second = _mtf_config(max_level_distance_atr=0.7)
    assert first.resolved_config_hash == second.resolved_config_hash
    assert first.mtf_config_hash != second.mtf_config_hash
    assert first.mtf.max_level_distance_atr == 0.5
    assert second.mtf.max_level_distance_atr == 0.7


def test_mtf_snapshot_identity_rejects_stale_payload() -> None:
    observed = timestamp()
    source = _source_snapshot(timeframe="1h", observed_at=observed, reference_price=100.0)
    snapshot = compose_mtf_snapshot(
        source_snapshots={"1h": source},
        decision_timestamp=observed,
        normalization_context=_context(),
        config=_mtf_config(timeframes=("1h",)),
    )
    with pytest.raises(ContractValidationError, match="mtf_snapshot_id"):
        replace(snapshot, mtf_snapshot_id="forged")


def test_mtf_conflicts_intersections_and_shadow_artifacts_remain_additive() -> None:
    observed = timestamp()
    conflict = compose_mtf_snapshot(
        source_snapshots={
            "1h": _source_snapshot(timeframe="1h", observed_at=observed, reference_price=100.0),
            "4h": _source_snapshot(
                timeframe="4h",
                observed_at=observed,
                reference_price=100.1,
                role=FamilyRole.RESISTANCE,
            ),
        },
        decision_timestamp=observed,
        normalization_context=_context(),
        config=_mtf_config(),
    )
    assert any(item.relation_type is MTFRelationType.CONFLICT for item in conflict.relations)

    intersection = compose_mtf_snapshot(
        source_snapshots={
            "1h": _source_snapshot(
                timeframe="1h",
                observed_at=observed,
                reference_price=100.0,
                slope_per_hour=0.5,
            ),
            "4h": _source_snapshot(
                timeframe="4h",
                observed_at=observed,
                reference_price=105.0,
                slope_per_hour=-0.5,
            ),
        },
        decision_timestamp=observed,
        normalization_context=_context(),
        config=_mtf_config(max_level_distance_atr=0.1, max_slope_delta_atr_per_hour=1.0),
    )
    assert any(item.relation_type is MTFRelationType.INTERSECTION for item in intersection.relations)

    features = build_mtf_shadow_features(conflict)
    report = summarize_trendline_family_shadow_artifacts(
        ({"trendline_family_shadow": {"trendline_family_shadow_enabled": True, "mtf": features}},)
    )
    assert features["conflict_relation_count"] == 1
    assert report["distributions"]["mtf_conflict_relation_count"] == {"1": 1}


def test_shadow_adapter_reads_precomposed_mtf_evidence_without_composition() -> None:
    observed = timestamp()
    source = _source_snapshot(timeframe="1h", observed_at=observed, reference_price=100.0)
    mtf_snapshot = compose_mtf_snapshot(
        source_snapshots={"1h": source},
        decision_timestamp=observed,
        normalization_context=_context(),
        config=_mtf_config(timeframes=("1h",)),
    )
    config = tracker_config()
    provider = SequenceProvider((valid_result(candidate(config, observed)),))
    shadow = TrendlineFamilyFeatureProducer(
        "BTCUSDT",
        "1h",
        shadow_config=TrendlineFamilyShadowConfig(enabled=True),
        repository=InMemoryTrendlineFamilyRepository(),
        resolved_config=config,
        provider=provider,
        mtf_snapshot_provider=lambda: mtf_snapshot,
    )

    features = shadow.analyze(tracker_ohlcv(observed))
    assert features["mtf"]["mtf_snapshot_id"] == mtf_snapshot.mtf_snapshot_id
    assert features["mtf"] == build_mtf_shadow_features(mtf_snapshot)


def test_shadow_adapter_soft_disables_mismatched_mtf_context_without_head_mutation() -> None:
    observed = timestamp()
    source = _source_snapshot(timeframe="1h", observed_at=observed, reference_price=100.0)
    mismatched_mtf = compose_mtf_snapshot(
        source_snapshots={"1h": source},
        decision_timestamp=observed + timedelta(hours=1),
        normalization_context=_context(),
        config=_mtf_config(timeframes=("1h",)),
    )
    config = tracker_config()
    repository = InMemoryTrendlineFamilyRepository()
    shadow = TrendlineFamilyFeatureProducer(
        "BTCUSDT",
        "1h",
        shadow_config=TrendlineFamilyShadowConfig(enabled=True),
        repository=repository,
        resolved_config=config,
        provider=SequenceProvider((valid_result(candidate(config, observed)),)),
        mtf_snapshot_provider=lambda: mismatched_mtf,
    )

    features = shadow.analyze(tracker_ohlcv(observed))
    head = repository.latest_snapshot("BTCUSDT", "1h")

    assert features["mtf"]["enabled"] is False
    assert features["mtf"]["mtf_snapshot_id"] is None
    assert head is not None
    assert head.snapshot_id == features["trendline_family_repository_head_after"]
