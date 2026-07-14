from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import perf_counter

import pytest
import pandas as pd

from libs.models.trendline_family.contracts import ContractValidationError, deterministic_hash
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository
from libs.models.trendline_family.config_resolver import TrendlineFamilyConfigResolver
from libs.models.trendline_family.mtf import MTFNormalizationContext
from libs.models.trendline_family.research_lab import (
    CrossAssetComparabilityPolicy,
    audit_cross_asset_comparability,
    build_cross_asset_comparison,
    build_price_figure,
    build_mtf_projection_figure,
    build_smoke_config,
    build_smoke_ohlcv,
    candidate_rows,
    candidate_status_rows,
    corridor_rows,
    event_rows,
    family_lineage_rows,
    immutable_research_frame,
    interaction_zone_rows,
    load_local_ohlcv,
    member_rail_rows,
    normalize_binance_ohlcv,
    observation_rows,
    parameter_policy_hash,
    provider_audit_rows,
    replay_prefix_is_causal,
    run_canonical_replay,
    transition_rows,
    validate_research_config,
    mtf_cluster_rows,
    mtf_projected_family_rows,
    mtf_projected_member_rows,
    mtf_relation_rows,
    mtf_source_rows,
)
from libs.models.trendline_family.tracker import TrendlineFamilyTracker
from libs.models.trendline_family import compose_trendline_family_mtf

from ..tracker_support import SequenceProvider, candidate, timestamp, tracker_config, tracker_ohlcv, valid_result


def _replay():
    config = build_smoke_config()
    dataset = immutable_research_frame(frame=build_smoke_ohlcv(), asset="BTCUSDT", timeframe="1h")
    return run_canonical_replay(dataset=dataset, config=config), config


def test_canonical_replay_is_deterministic_causal_and_compact() -> None:
    started = perf_counter()
    first, config = _replay()
    second, _ = _replay()
    assert first.context.research_run_id == second.context.research_run_id
    assert [item.snapshot.snapshot_id for item in first.outputs] == [item.snapshot.snapshot_id for item in second.outputs]
    assert replay_prefix_is_causal(first, position=20, config=config)
    assert perf_counter() - started < 10.0
    assert first.runtime_diagnostics["bars_per_second"] > 0.0
    assert len(candidate_status_rows(first)) == first.dataset.row_count
    assert candidate_rows(first)


def test_non_smoke_research_rejects_smoke_fixture_config() -> None:
    with pytest.raises(Exception, match="smoke fixture config"):
        validate_research_config(
            build_smoke_config(),
            asset="BTCUSDT",
            timeframe="1h",
        )


def test_cross_asset_policy_is_content_addressed_and_metric_bound() -> None:
    policy = CrossAssetComparabilityPolicy()
    assert policy.policy_id == deterministic_hash(policy.identity_payload())
    assert set(policy.metric_definitions) == {
        "candidate_count",
        "eligible_bar_count",
        "family_snapshot_count",
        "unique_family_count",
    }
    with pytest.raises(ContractValidationError, match="policy_id"):
        CrossAssetComparabilityPolicy(policy_id="arbitrary-label")
    with pytest.raises(ContractValidationError, match="sample_definition"):
        CrossAssetComparabilityPolicy(sample_definition="display-only text")
    with pytest.raises(ContractValidationError, match="metric_definitions"):
        CrossAssetComparabilityPolicy(
            metric_definitions={"candidate_count": "unbound_metric"}
        )


def test_parameter_policy_hash_preserves_timeframe_semantics() -> None:
    one_hour = build_smoke_config(timeframe="1h")
    four_hour = build_smoke_config(timeframe="4h")
    assert parameter_policy_hash(one_hour) != parameter_policy_hash(four_hour)


def test_cross_asset_comparability_audits_parameter_and_sample_semantics() -> None:
    btc_dataset = immutable_research_frame(
        frame=build_smoke_ohlcv(),
        asset="BTCUSDT",
        timeframe="1h",
    )
    eth_dataset = immutable_research_frame(
        frame=build_smoke_ohlcv(),
        asset="ETHUSDT",
        timeframe="1h",
    )
    btc = run_canonical_replay(dataset=btc_dataset, config=build_smoke_config(asset="BTCUSDT"))
    eth = run_canonical_replay(dataset=eth_dataset, config=build_smoke_config(asset="ETHUSDT"))
    policy = CrossAssetComparabilityPolicy()
    comparison = build_cross_asset_comparison((eth, btc), policy=policy)
    assert comparison.audit.comparable
    assert comparison.audit.policy_id == policy.policy_id
    assert dict(comparison.audit.policy_identity) == dict(policy.identity_payload())
    assert tuple(row.asset for row in comparison.rows) == ("BTCUSDT", "ETHUSDT")
    assert btc.context.resolved_config_hash != eth.context.resolved_config_hash
    assert btc.context.parameter_policy_hash == eth.context.parameter_policy_hash

    shorter_eth = run_canonical_replay(
        dataset=immutable_research_frame(
            frame=build_smoke_ohlcv(rows=32),
            asset="ETHUSDT",
            timeframe="1h",
        ),
        config=build_smoke_config(asset="ETHUSDT"),
    )
    sample_audit = audit_cross_asset_comparability((btc, shorter_eth), policy=policy)
    assert not sample_audit.comparable
    assert "sample_window_mismatch" in sample_audit.reason_codes
    assert "sample_row_count_mismatch" in sample_audit.reason_codes

    different_policy_eth = run_canonical_replay(
        dataset=eth_dataset,
        config=tracker_config(
            asset="ETHUSDT",
            timeframe="1h",
            config_version="research_smoke_v1",
            candidate={"lookback_bars": 24},
        ),
    )
    parameter_audit = audit_cross_asset_comparability((btc, different_policy_eth), policy=policy)
    assert not parameter_audit.comparable
    assert "parameter_policy_mismatch" in parameter_audit.reason_codes


def test_provider_audit_reads_canonical_metadata() -> None:
    replay, _ = _replay()
    audits = provider_audit_rows(replay)
    assert audits[-1].confirmed_bar_count == replay.dataset.row_count
    assert audits[-1].confirmed_pivot_count is not None
    assert audits[-1].fitted_path_count is not None


def test_chart_rows_keep_exact_member_geometry_and_stable_ordering() -> None:
    replay, _ = _replay()
    snapshot = replay.outputs[-1].snapshot
    rails = member_rail_rows(snapshot)
    assert rails == tuple(sorted(rails, key=lambda row: (row.role, row.family_id, row.member_id)))
    for rail in rails:
        family = next(item for item in snapshot.active_families + snapshot.dormant_families if item.family_id == rail.family_id)
        member = next(item for item in family.members if item.member_id == rail.member_id)
        assert rail.projected_price == pytest.approx(member.geometry.value_at(snapshot.timestamp))
    figure = build_price_figure(
        frame=replay.dataset.to_frame().tail(24),
        rails=rails,
        corridors=corridor_rows(snapshot),
        zones=interaction_zone_rows(snapshot),
        events=event_rows(snapshot),
        include_volume=True,
    )
    assert figure.data[0].type == "candlestick"
    assert any("anchor" in str(trace.name) for trace in figure.data)
    for corridor in corridor_rows(snapshot):
        rendered = next(trace for trace in figure.data if trace.name == f"corridor {corridor.corridor_id}")
        members = [rail for rail in rails if rail.member_id in corridor.ordered_member_ids]
        if any(member.slope_per_second != 0.0 for member in members):
            assert len(set(rendered.y)) > 1
    for zone in interaction_zone_rows(snapshot):
        rendered = next(trace for trace in figure.data if trace.name == f"zone {zone.observation_id}")
        assert len(rendered.x) == 2


def test_multi_rail_rows_keep_distinct_exact_members_and_separate_corridor_zone() -> None:
    config = tracker_config(
        rails={"minimum_spacing_atr": 0.01, "max_adjacent_gap_atr": 0.50, "max_corridor_width_atr": 1.00}
    )
    observed = timestamp()
    left = candidate(config, observed, candidate_id="left", reference_price=100.0, anchor_prefix="left")
    right = candidate(config, observed, candidate_id="right", reference_price=100.4, anchor_prefix="right")
    snapshot = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(left, right),)),
        config=config,
    ).update(tracker_ohlcv(observed)).snapshot
    rails = member_rail_rows(snapshot)
    corridors = corridor_rows(snapshot)
    zones = interaction_zone_rows(snapshot)
    assert len(rails) == 2
    assert len({row.member_id for row in rails}) == 2
    assert len(corridors) == 1
    assert corridors[0].ordered_member_ids == tuple(row.member_id for row in rails)
    assert zones and zones[0].family_id == corridors[0].family_id
    assert zones[0].exact_line_price == pytest.approx(
        next(row.projected_price for row in rails if row.representative)
    )


def test_lineage_observation_and_event_tables_only_read_persisted_ids() -> None:
    replay, _ = _replay()
    snapshot = replay.outputs[-1].snapshot
    families = snapshot.active_families + snapshot.dormant_families
    lineage = family_lineage_rows(replay, family_id=families[0].family_id)
    assert all(row.family_id == families[0].family_id for row in lineage)
    assert {row.transition_id for row in transition_rows(snapshot)} == {item.transition_id for item in snapshot.transitions}
    assert {row.observation_id for row in observation_rows(snapshot)} == {item.observation_id for item in snapshot.observations}
    assert {row.event_id for row in event_rows(snapshot)} == {item.event_id for item in snapshot.interaction_events}


def test_research_timestamp_loaders_reject_ambiguous_data_and_bind_binance_milliseconds(tmp_path) -> None:
    naive = tmp_path / "naive.csv"
    naive.write_text(
        "timestamp,open,high,low,close,volume\n2024-01-01T00:00:00,100,101,99,100,1\n",
        encoding="utf-8",
    )
    with pytest.raises(Exception, match="timezone-aware UTC"):
        load_local_ohlcv(str(naive))

    frame = build_smoke_ohlcv(rows=16).iloc[:3].reset_index(names="timestamp")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True).map(lambda value: int(value.timestamp() * 1_000))
    normalized = normalize_binance_ohlcv(
        frame,
        timeframe="1h",
        closed_before=datetime(2024, 1, 1, 3, tzinfo=timezone.utc),
    )
    assert normalized.index[0] == pd.Timestamp("2024-01-01T00:00:00Z")
    assert len(normalized) == 3
    assert "timestamp" not in normalized.columns
    assert normalized["complete"].all()
    with pytest.raises(Exception, match="strictly ordered and unique"):
        normalize_binance_ohlcv(
            frame.iloc[[1, 0, 2]],
            timeframe="1h",
            closed_before=datetime(2024, 1, 1, 3, tzinfo=timezone.utc),
        )


def test_mtf_rows_only_adapt_approved_geometry_and_keep_missing_sources_visible() -> None:
    observed = timestamp()

    def source_snapshot(timeframe: str, price: float):
        config = tracker_config(timeframe=timeframe)
        line = candidate(config, observed, candidate_id=f"{timeframe}-{price}", reference_price=price, anchor_prefix=timeframe)
        return TrendlineFamilyTracker(
            repository=InMemoryTrendlineFamilyRepository(),
            provider=SequenceProvider((valid_result(line),)),
            config=config,
        ).update(tracker_ohlcv(observed)).snapshot

    config = TrendlineFamilyConfigResolver(
        {
            "version": "research-mtf-v1",
            "defaults": {
                "mtf": {
                    "enabled": True,
                    "source_timeframes": ["1h", "4h"],
                    "minimum_confluence_timeframes": 2,
                    "max_source_age_bars": 4.0,
                    "stale_include_age_bars": 1.0,
                    "max_level_distance_atr": 1.0,
                    "max_corridor_separation_atr": 1.0,
                    "max_slope_delta_atr_per_hour": 1.0,
                    "intersection_horizon_bars": 24,
                    "normalization_policy": "decision_timeframe_atr",
                }
            },
        }
    ).resolve(asset="BTCUSDT", timeframe="1h")
    snapshot = compose_trendline_family_mtf(
        source_snapshots={"4h": source_snapshot("4h", 100.0)},
        decision_timestamp=observed + timedelta(hours=8),
        normalization_context=MTFNormalizationContext(
            asset="BTCUSDT", decision_timeframe="1h", atr=2.0, decision_price=100.0
        ),
        config=config,
    )
    source_rows = mtf_source_rows(snapshot)
    assert {row.source_timeframe for row in source_rows} == {"1h", "4h"}
    assert next(row for row in source_rows if row.source_timeframe == "1h").freshness_state == "MISSING"
    projected_families = mtf_projected_family_rows(snapshot)
    projected_members = mtf_projected_member_rows(snapshot)
    assert projected_families == tuple(
        sorted(projected_families, key=lambda row: (row.source_timeframe, row.role, row.projected_family_id))
    )
    assert projected_members == tuple(
        sorted(
            projected_members,
            key=lambda row: (row.source_timeframe, row.projected_family_id, row.source_order_index, row.projected_member_id),
        )
    )
    assert len(projected_families) == len(snapshot.projected_families)
    assert len(projected_members) == len(snapshot.projected_members)
    for row in projected_members:
        member = next(item for item in snapshot.projected_members if item.projected_member_id == row.projected_member_id)
        assert row.reference_time == member.source_geometry.reference_time
        assert row.reference_price == pytest.approx(member.source_geometry.reference_price)
        assert row.slope_per_second == pytest.approx(member.source_geometry.slope_per_second)
        assert row.projected_price == pytest.approx(member.projected_price)
    mtf_figure = build_mtf_projection_figure(members=projected_members)
    assert len(mtf_figure.data) == len(projected_members)
    assert all(trace.mode == "markers" for trace in mtf_figure.data)
    assert mtf_relation_rows(snapshot) == tuple(sorted(mtf_relation_rows(snapshot), key=lambda row: row.relation_id))
    assert mtf_cluster_rows(snapshot) == tuple(sorted(mtf_cluster_rows(snapshot), key=lambda row: row.cluster_id))
    stale_config = TrendlineFamilyConfigResolver(
        {
            "version": "research-mtf-stale-v1",
            "defaults": {"mtf": {**config.mtf.__dict__, "max_source_age_bars": 1.0, "stale_include_age_bars": 0.5}},
        }
    ).resolve(asset="BTCUSDT", timeframe="1h")
    stale_snapshot = compose_trendline_family_mtf(
        source_snapshots={"4h": source_snapshot("4h", 100.0)},
        decision_timestamp=observed + timedelta(hours=8),
        normalization_context=MTFNormalizationContext(
            asset="BTCUSDT", decision_timeframe="1h", atr=2.0, decision_price=100.0
        ),
        config=stale_config,
    )
    assert next(row for row in mtf_source_rows(stale_snapshot) if row.source_timeframe == "4h").freshness_state == "STALE_EXCLUDED"
