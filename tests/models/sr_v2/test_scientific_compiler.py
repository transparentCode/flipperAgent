from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from libs.models.sr_v2.domain.state import create_initial_state
from libs.models.sr_v2.features.time import grid_for
from libs.models.sr_v2.forecast.targets import resolve_target_spec
from libs.models.sr_v2.lifecycle.transitions import TransitionType
from libs.models.sr_v2.research_lab.config import SRV2ResearchNotebookConfigResolver
from libs.models.sr_v2.research_lab.replay import SRV2ResearchReplay
from libs.models.sr_v2.research_lab.scientific_compiler import (
    ScientificObservationCompiler,
)
from libs.models.sr_v2.structural import SRModel, SRStepRequest


def _target_specs(config):
    return {
        timeframe: resolve_target_spec(
            source_timeframe=timeframe,
            source_horizon_bars=1,
            reference_lookback=2,
            barrier_multiplier=Decimal("0.5"),
            observation_timeframe=config.trigger_timeframe,
            observation_duration=config.trigger_duration,
        )
        for timeframe in config.ladder
    }


def _compiler(config, bars):
    return ScientificObservationCompiler(
        {"BTCUSDT": bars},
        model_config=config,
        target_specs=_target_specs(config),
        null_seed="compiler-test-seed",
    )


def _first_result(config, bars, cutoff):
    state = create_initial_state(
        config_fingerprint=config.config_fingerprint,
        venue="binance_usdm",
        instrument_id="BTCUSDT",
        asset="BTCUSDT",
    )
    return SRModel(config).step(
        SRStepRequest(
            venue="binance_usdm",
            instrument_id="BTCUSDT",
            asset="BTCUSDT",
            market_as_of=cutoff,
            state=state,
            windows=bars,
        )
    )


def test_compiler_derives_exact_ontology_and_direct_source_identity(
    sr_v2_config, sr_v2_bars, sr_v2_now
):
    compiler = _compiler(sr_v2_config, sr_v2_bars)
    expected = {
        ("BTCUSDT", timeframe, kernel.kernel_id, kernel.kernel_version)
        for timeframe in sr_v2_config.ladder
        for kernel in sr_v2_config.kernels
    }
    assert {
        (group.asset, group.timeframe, group.kernel_id, group.kernel_version)
        for group in compiler.expected_groups
    } == expected
    assert compiler.source_manifest_id
    assert len(compiler.source_sha256) == 64

    changed = dict(sr_v2_bars)
    last = changed["15m"][-1]
    changed["15m"] = (
        *changed["15m"][:-1],
        replace(last, close=last.close + Decimal("0.1")),
    )
    with pytest.raises(ValueError, match="source_sha256"):
        ScientificObservationCompiler(
            {"BTCUSDT": changed},
            model_config=sr_v2_config,
            target_specs=_target_specs(sr_v2_config),
            null_seed="compiler-test-seed",
            source_sha256=compiler.source_sha256,
        )


def test_compiler_requires_nested_asset_lanes_and_exact_resolved_ladder(
    sr_v2_config, sr_v2_bars
):
    with pytest.raises(TypeError, match="nested"):
        ScientificObservationCompiler(
            sr_v2_bars,
            model_config=sr_v2_config,
            target_specs=_target_specs(sr_v2_config),
            null_seed="compiler-test-seed",
        )

    missing = dict(sr_v2_bars)
    missing.pop("1h")
    with pytest.raises(ValueError, match="exact resolved ladder"):
        _compiler(sr_v2_config, missing)

    extra = dict(sr_v2_bars)
    extra["2h"] = sr_v2_bars["1h"]
    with pytest.raises(ValueError, match="unsupported"):
        _compiler(sr_v2_config, extra)


def test_compiler_consumes_only_created_linked_candidates_and_finalizes_pending(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    result = _first_result(sr_v2_config, sr_v2_bars, sr_v2_now)
    compiler = _compiler(sr_v2_config, sr_v2_bars)
    trigger_bar = sr_v2_bars[sr_v2_config.trigger_timeframe][-1]
    compiler.consume(result, trigger_bar)
    compiled = compiler.finalize(knowledge_cutoff=sr_v2_now)

    assert compiled.observations
    assert compiled.knowledge_cutoff == sr_v2_now
    assert compiled.finalized_incomplete_count == len(compiled.observations)
    assert not hasattr(compiled, "metadata")
    assert all(
        item.observation_id == item.zone.zone_id for item in compiled.observations
    )
    assert all(
        item.target.target_reference_volatility.issuance_cutoff == item.issued_at
        for item in compiled.observations
    )

    no_created = replace(
        result,
        transitions=tuple(
            transition
            for transition in result.transitions
            if transition.transition_type is not TransitionType.CREATED
        ),
    )
    empty = _compiler(sr_v2_config, sr_v2_bars)
    empty.consume(no_created, trigger_bar)
    assert empty.finalize(knowledge_cutoff=sr_v2_now).observations == ()


def test_compiler_rejects_created_transition_without_exact_current_candidate(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    result = _first_result(sr_v2_config, sr_v2_bars, sr_v2_now)
    candidates = {key: () for key in result.candidates_by_timeframe}
    compiler = _compiler(sr_v2_config, sr_v2_bars)
    with pytest.raises(ValueError, match="exact current-step kernel candidate"):
        compiler.consume(
            replace(result, candidates_by_timeframe=candidates), sr_v2_bars["15m"][-1]
        )


def test_compiler_validates_latest_consumed_cutoff(sr_v2_config, sr_v2_bars, sr_v2_now):
    result = _first_result(sr_v2_config, sr_v2_bars, sr_v2_now)
    compiler = _compiler(sr_v2_config, sr_v2_bars)
    compiler.consume(result, sr_v2_bars["15m"][-1])
    with pytest.raises(ValueError, match="latest consumed"):
        compiler.finalize(knowledge_cutoff=sr_v2_now - timedelta(minutes=15))


def test_compiler_replay_end_to_end_keeps_warmup_out_of_callback_window(
    sr_v2_config,
    sr_v2_bars,
):
    analysis_start = sr_v2_bars["15m"][19].bar_close_at
    knowledge_cutoff = analysis_start + timedelta(minutes=15)
    model = replace(sr_v2_config, expiry=timedelta(minutes=15))
    first_hour = sr_v2_bars["1h"][0]
    prepended_hour = replace(
        first_hour,
        bar_open_at=first_hour.bar_open_at - timedelta(hours=1),
        bar_close_at=first_hour.bar_close_at - timedelta(hours=1),
        market_as_of=first_hour.market_as_of - timedelta(hours=1),
    )
    source_bars = dict(sr_v2_bars)
    first_trigger = sr_v2_bars["15m"][0]
    source_bars["15m"] = (
        replace(
            first_trigger,
            bar_open_at=first_trigger.bar_open_at - timedelta(minutes=30),
            bar_close_at=first_trigger.bar_close_at - timedelta(minutes=30),
            market_as_of=first_trigger.market_as_of - timedelta(minutes=30),
        ),
        replace(
            first_trigger,
            bar_open_at=first_trigger.bar_open_at - timedelta(minutes=15),
            bar_close_at=first_trigger.bar_close_at - timedelta(minutes=15),
            market_as_of=first_trigger.market_as_of - timedelta(minutes=15),
        ),
        *sr_v2_bars["15m"],
    )
    source_bars["1h"] = (prepended_hour, *sr_v2_bars["1h"])
    first_half_hour = sr_v2_bars["30m"][0]
    source_bars["30m"] = (
        replace(
            first_half_hour,
            bar_open_at=first_half_hour.bar_open_at - timedelta(minutes=30),
            bar_close_at=first_half_hour.bar_close_at - timedelta(minutes=30),
            market_as_of=first_half_hour.market_as_of - timedelta(minutes=30),
        ),
        *sr_v2_bars["30m"],
    )
    research = SRV2ResearchNotebookConfigResolver(
        {
            "version": 2,
            "research": {
                "venue": "binance_usdm",
                "instrument_id": "BTCUSDT",
                "asset": "BTCUSDT",
                "analysis_start": analysis_start.isoformat(),
                "knowledge_cutoff": knowledge_cutoff.isoformat(),
                "source_mode": "CACHE_ONLY",
                "cache_root": ".cache/test",
                "max_replay_steps": 1000,
                "replay_identity_mode": "WINDOW_RELATIVE",
            },
            "display": {
                "iframe_height": 720,
                "candle_limit": 100,
                "initial_mode": "formation",
                "show_zones": True,
                "show_candidates": False,
                "show_inspector": False,
                "show_history": False,
                "volume_pane_fraction": 0.2,
                "volume_pane_min_height": 120,
            },
        }
    ).resolve()
    compiled = _compiler(model, source_bars).compile(
        SRV2ResearchReplay(model, research),
        analysis_start=analysis_start,
        knowledge_cutoff=knowledge_cutoff,
    )
    assert compiled.observations
    assert compiled.knowledge_cutoff == knowledge_cutoff
    assert compiled.finalized_incomplete_count >= 0


def test_compiler_preserves_open_observations_when_runtime_tombstones_are_pruned(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    first_cutoff = sr_v2_now - timedelta(minutes=15)
    first_trigger = sr_v2_bars["15m"][0]
    prepended_trigger = replace(
        first_trigger,
        bar_open_at=first_trigger.bar_open_at - timedelta(minutes=15),
        bar_close_at=first_trigger.bar_close_at - timedelta(minutes=15),
        market_as_of=first_trigger.market_as_of - timedelta(minutes=15),
    )
    all_bars = dict(sr_v2_bars)
    all_bars["15m"] = (prepended_trigger, *sr_v2_bars["15m"])
    first_bars = {
        timeframe: tuple(
            bar
            for bar in all_bars[timeframe]
            if bar.bar_close_at
            <= grid_for(timeframe).expected_closed_cutoff(first_cutoff)
        )
        for timeframe in all_bars
    }
    first = _first_result(sr_v2_config, first_bars, first_cutoff)
    created_ids = {
        transition.zone_id
        for transition in first.transitions
        if transition.transition_type is TransitionType.CREATED
    }
    compiler = _compiler(sr_v2_config, all_bars)
    compiler.consume(first, all_bars["15m"][-2])

    second = SRModel(sr_v2_config).step(
        SRStepRequest(
            venue="binance_usdm",
            instrument_id="BTCUSDT",
            asset="BTCUSDT",
            market_as_of=sr_v2_now,
            state=first.state,
            windows={"15m": all_bars["15m"]},
        )
    )
    pruned = replace(
        second,
        transitions=tuple(
            transition
            for transition in second.transitions
            if transition.transition_type is not TransitionType.CREATED
        ),
        state=replace(second.state, active_lineages=(), terminal_tombstones=()),
        lineage_registry={},
    )
    compiler.consume(pruned, all_bars["15m"][-1])
    compiled = compiler.finalize(knowledge_cutoff=sr_v2_now)
    assert created_ids.issubset({item.observation_id for item in compiled.observations})
