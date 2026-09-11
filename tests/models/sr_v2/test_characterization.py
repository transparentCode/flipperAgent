"""Characterization locks for the approved structural-only SR v2 surface."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import timedelta

from libs.models.sr_v2.domain.state import SRState, create_initial_state
from libs.models.sr_v2.research_lab.config import SRV2ResearchNotebookConfigResolver
from libs.models.sr_v2.research_lab.replay import SRV2ResearchReplay
from libs.models.sr_v2.structural import SRModel, SRStepRequest
from tests.models.sr_v2.test_research_lab import _replay_bars, _research_mapping


def test_structural_characterization_has_no_forecast_or_selection_state(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    result = SRModel(sr_v2_config).step(SRStepRequest(
        venue="binance_usdm",
        instrument_id="BTCUSDT",
        asset="BTCUSDT",
        market_as_of=sr_v2_now,
        state=create_initial_state(
            config_fingerprint=sr_v2_config.config_fingerprint,
            venue="binance_usdm",
            instrument_id="BTCUSDT",
            asset="BTCUSDT",
        ),
        windows=sr_v2_bars,
    ))
    assert tuple(item.name for item in fields(SRState)) == (
        "schema_version",
        "config_fingerprint",
        "generation",
        "venue",
        "instrument_id",
        "asset",
        "last_trigger_at",
        "source_cutoffs",
        "source_fingerprints",
        "source_fingerprint_sequences",
        "active_lineages",
        "terminal_tombstones",
    )
    assert not hasattr(result.state, "forecast_issuances")
    assert not hasattr(result.state, "lifecycle_events")
    assert not hasattr(result.state, "lane_id")
    assert not hasattr(result.state, "binding_id")


def test_research_replay_has_one_final_snapshot_and_same_structural_path(sr_v2_config):
    model = replace(sr_v2_config, expiry=timedelta(days=1))
    research = SRV2ResearchNotebookConfigResolver(_research_mapping()).resolve()
    replay = SRV2ResearchReplay(model, research)
    trace = replay.run(
        _replay_bars(model, research.analysis_start, research.knowledge_cutoff),
        analysis_start=research.analysis_start,
        knowledge_cutoff=research.knowledge_cutoff,
    )
    assert len(trace.snapshots) == 1
    assert trace.snapshots[0].cutoff == research.knowledge_cutoff
    assert trace.metadata["snapshot_scope"].startswith("FINAL_ACTIVE_LINEAGES_ONLY")
    assert trace.configured_timeframes == model.ladder
    assert set(trace.bars_by_timeframe) == set(model.ladder)
