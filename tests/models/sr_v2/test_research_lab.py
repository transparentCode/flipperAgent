from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from libs.market_data import BINANCE_KLINE_PAGE_LIMIT
from libs.models.sr_v2.config import SRV2ConfigError
from libs.models.sr_v2.domain.bars import SRBar
from libs.models.sr_v2.domain.identity import canonical_hash
from libs.models.sr_v2.domain.state import create_initial_state
from libs.models.sr_v2.features.time import grid_for
from libs.models.sr_v2.research.source import SourceBarRecord, load_source_jsonl
from libs.models.sr_v2.research_lab.config import SRV2ResearchNotebookConfigResolver
from libs.models.sr_v2.research_lab.data import (
    RESEARCH_CACHE_SCHEMA_VERSION,
    BinanceUSDMResearchLoader,
)
from libs.models.sr_v2.research_lab.replay import SRV2ResearchReplay
from libs.models.sr_v2.research_lab.trace import SnapshotZoneState
from libs.models.sr_v2.runtime.offline import OfflineCompute
from libs.models.sr_v2.structural import SRModel, SRStepRequest


def _research_mapping() -> dict[str, object]:
    return {
        "version": 2,
        "research": {
            "venue": "binance_usdm",
            "instrument_id": "BTCUSDT",
            "asset": "BTCUSDT",
            "analysis_start": "2024-01-02T00:00:00+00:00",
            "knowledge_cutoff": "2024-01-02T00:30:00+00:00",
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


def test_research_config_is_strict_and_model_parameters_are_not_accepted():
    resolver = SRV2ResearchNotebookConfigResolver(_research_mapping())
    assert resolver.resolve().asset == "BTCUSDT"
    bad_version = _research_mapping()
    bad_version["version"] = True
    with pytest.raises(SRV2ConfigError, match="version"):
        SRV2ResearchNotebookConfigResolver(bad_version).resolve()
    bad_asset = _research_mapping()
    bad_asset["research"] = {**bad_asset["research"], "asset": 12}
    with pytest.raises(SRV2ConfigError, match="asset"):
        SRV2ResearchNotebookConfigResolver(bad_asset).resolve()
    unknown = _research_mapping()
    unknown["research"] = {**unknown["research"], "expiry": "1d"}
    with pytest.raises(SRV2ConfigError, match="unknown"):
        SRV2ResearchNotebookConfigResolver(unknown).resolve()


class _FakeAdapter:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def get_historical_ohlcv(self, symbol, timeframe, **kwargs):
        self.calls.append((symbol, timeframe, kwargs))
        start = kwargs["since"]
        return [row for row in self.rows if row["timestamp"] >= start]


def _rows(start: datetime, count: int = 4):
    return [
        {
            "timestamp": int(
                (start + timedelta(minutes=15 * index)).timestamp() * 1000
            ),
            "open": "100",
            "high": "101",
            "low": "99",
            "close": "100",
            "volume": "2",
            "taker_buy_base": "1",
            "close_time": int(
                (
                    (start + timedelta(minutes=15 * (index + 1)))
                    - timedelta(milliseconds=1)
                ).timestamp()
                * 1000
            ),
        }
        for index in range(count)
    ]


def test_data_loader_paginates_with_market_limit_cache_zero_calls_and_tamper_detection(
    tmp_path,
):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    adapter = _FakeAdapter(_rows(start))
    loader = BinanceUSDMResearchLoader(
        adapter, cache_root=tmp_path, venue="binance_usdm"
    )
    result = asyncio.run(
        loader.load(
            instrument_id="BTCUSDT",
            asset="BTCUSDT",
            timeframe="15m",
            start=start,
            end=end,
            source_mode="BINANCE_USDM",
            provider_calls_authorized=True,
        )
    )
    assert result.provider_calls == len(adapter.calls) == 1
    assert adapter.calls[0][2]["limit"] == BINANCE_KLINE_PAGE_LIMIT
    assert result.records[0].exchange_close_at == start + timedelta(
        minutes=15
    ) - timedelta(milliseconds=1)
    assert result.manifest_path is not None and result.manifest_path.is_file()

    offline_adapter = _FakeAdapter([])
    offline = BinanceUSDMResearchLoader(
        offline_adapter, cache_root=tmp_path, venue="binance_usdm"
    )
    cached = asyncio.run(
        offline.load(
            instrument_id="BTCUSDT",
            asset="BTCUSDT",
            timeframe="15m",
            start=start,
            end=end,
            source_mode="CACHE_ONLY",
        )
    )
    assert cached.provider_calls == 0
    assert offline_adapter.calls == []
    result.cache_path.write_text(
        result.cache_path.read_text().replace('"close":"100"', '"close":"101"', 1)
    )
    with pytest.raises(ValueError, match="manifest|authenticate"):
        asyncio.run(
            offline.load(
                instrument_id="BTCUSDT",
                asset="BTCUSDT",
                timeframe="15m",
                start=start,
                end=end,
                source_mode="CACHE_ONLY",
            )
        )
    with pytest.raises(ValueError, match="invariant"):
        BinanceUSDMResearchLoader(
            cache_root=tmp_path,
            venue="binance_usdm",
            page_limit=BINANCE_KLINE_PAGE_LIMIT - 1,
        )


def test_versioned_cache_identity_keeps_legacy_sidecar_coexisting(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    adapter = _FakeAdapter(_rows(start))
    loader = BinanceUSDMResearchLoader(
        adapter, cache_root=tmp_path, venue="binance_usdm"
    )
    result = asyncio.run(
        loader.load(
            instrument_id="BTCUSDT",
            asset="BTCUSDT",
            timeframe="15m",
            start=start,
            end=end,
            source_mode="BINANCE_USDM",
            provider_calls_authorized=True,
        )
    )

    assert RESEARCH_CACHE_SCHEMA_VERSION == 2
    assert "_v2_" in result.cache_path.name
    legacy_identity = canonical_hash(
        {
            "venue": "binance_usdm",
            "instrument_id": "BTCUSDT",
            "asset": "BTCUSDT",
            "timeframe": "15m",
            "start": start,
            "end": end,
        }
    )
    legacy_path = tmp_path / f"BTCUSDT_15m_{legacy_identity[:24]}.jsonl"
    assert legacy_path != result.cache_path
    shutil.copyfile(result.cache_path, legacy_path)
    legacy_manifest, _ = load_source_jsonl(legacy_path)
    legacy_manifest_path = legacy_path.with_suffix(
        legacy_path.suffix + ".manifest.json"
    )
    legacy_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "manifest_id": legacy_manifest.manifest_id,
                "source_sha256": legacy_manifest.source_sha256,
                "records": legacy_manifest.records,
                "venue": legacy_manifest.venue,
                "instrument_ids": list(legacy_manifest.instrument_ids),
                "timeframes": list(legacy_manifest.timeframes),
                "assets": list(legacy_manifest.assets),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    legacy_bytes = legacy_path.read_bytes()
    legacy_sidecar_bytes = legacy_manifest_path.read_bytes()

    cached = asyncio.run(
        BinanceUSDMResearchLoader(cache_root=tmp_path, venue="binance_usdm").load(
            instrument_id="BTCUSDT",
            asset="BTCUSDT",
            timeframe="15m",
            start=start,
            end=end,
            source_mode="CACHE_ONLY",
        )
    )
    assert cached.cache_path == result.cache_path
    assert legacy_path.read_bytes() == legacy_bytes
    assert legacy_manifest_path.read_bytes() == legacy_sidecar_bytes
    with pytest.raises(ValueError, match="authenticate|unsupported|acquisition"):
        asyncio.run(
            BinanceUSDMResearchLoader(cache_root=tmp_path, venue="binance_usdm").load(
                instrument_id="BTCUSDT",
                asset="BTCUSDT",
                timeframe="15m",
                start=start,
                end=end,
                source_mode="CACHE_ONLY",
                cache_path=legacy_path,
            )
        )


def _bar(timeframe: str, opened: datetime, duration: timedelta, index: int) -> SRBar:
    base = Decimal(100) + Decimal(index) / Decimal(100)
    return SRBar(
        timeframe=timeframe,
        bar_open_at=opened,
        bar_close_at=opened + duration,
        market_as_of=opened + duration,
        open=base,
        high=base + Decimal(1),
        low=base - Decimal(1),
        close=base + Decimal(".2"),
        volume=Decimal(10),
        taker_buy_base=Decimal(5),
    )


def _replay_bars(config, start: datetime, end: datetime):
    reconstruction_start = start - config.expiry
    result = {}
    for timeframe in config.ladder:
        duration = grid_for(timeframe).duration
        first_cutoff = grid_for(timeframe).expected_closed_cutoff(reconstruction_start)
        last_cutoff = grid_for(timeframe).expected_closed_cutoff(end)
        opened = first_cutoff - duration * 25
        values = []
        index = 0
        while opened < last_cutoff:
            values.append(_bar(timeframe, opened, duration, index))
            opened += duration
            index += 1
        result[timeframe] = tuple(values)
    return result


def test_replay_reconstructs_before_analysis_and_is_future_invariant(sr_v2_config):
    start = datetime(2024, 1, 2, tzinfo=UTC)
    end = datetime(2024, 1, 2, 0, 30, tzinfo=UTC)
    model = replace(sr_v2_config, expiry=timedelta(days=1))
    research = SRV2ResearchNotebookConfigResolver(_research_mapping()).resolve()
    bars = _replay_bars(model, start, end)
    replay = SRV2ResearchReplay(model, research)
    assert (
        replay.preflight_replay_steps(analysis_start=start, knowledge_cutoff=end)
        <= 1000
    )
    trace = replay.run(bars, analysis_start=start, knowledge_cutoff=end)
    assert trace.reconstruction_start == start - timedelta(days=1)
    assert trace.identity_mode == "WINDOW_RELATIVE"
    assert trace.snapshots[-1].cutoff == end
    assert trace.transitions
    assert any(item.event_at < start for item in trace.transitions)
    assert [item.ordinal for item in trace.transitions] == list(
        range(len(trace.transitions))
    )
    assert trace.lineage_records
    assert trace.metadata["snapshot_scope"].startswith("FINAL_ACTIVE_LINEAGES_ONLY")
    assert all(
        sum(len(values) for values in snapshot.zones_by_timeframe.values())
        <= trace.metadata["peak_active_lineages"]
        for snapshot in trace.snapshots
    )
    snapshot_states = [
        state
        for snapshot in trace.snapshots
        for values in snapshot.zones_by_timeframe.values()
        for state in values
    ]
    assert snapshot_states
    assert all(isinstance(state, SnapshotZoneState) for state in snapshot_states)
    assert all(not hasattr(state, "lineage") for state in snapshot_states)
    assert len({id(state) for state in snapshot_states}) == len(snapshot_states)
    assert all("volume_zscore" not in row for row in trace.feature_rows)
    assert {row["kernel_id"] for row in trace.feature_rows} == {
        kernel.kernel_id for kernel in model.kernels
    }
    assert len(
        {
            (row["cutoff"], row["timeframe"], row["kernel_id"])
            for row in trace.feature_rows
        }
    ) == len(trace.feature_rows)

    mutated = dict(bars)
    future = list(mutated["15m"])
    future[-1] = _bar("15m", future[-1].bar_open_at, timedelta(minutes=15), 999)
    mutated["15m"] = tuple(future)
    mutated_trace = replay.run(mutated, analysis_start=start, knowledge_cutoff=end)
    assert (
        trace.snapshots[0].replay_point_id == mutated_trace.snapshots[0].replay_point_id
    )


def test_research_callback_excludes_warmup_cutoffs_but_internal_replay_runs(
    sr_v2_config,
):
    start = datetime(2024, 1, 2, tzinfo=UTC)
    end = datetime(2024, 1, 2, 0, 30, tzinfo=UTC)
    model = replace(sr_v2_config, expiry=timedelta(days=1))
    research = SRV2ResearchNotebookConfigResolver(_research_mapping()).resolve()
    bars = _replay_bars(model, start, end)
    callbacks = []
    trace = SRV2ResearchReplay(model, research).run(
        bars,
        analysis_start=start,
        knowledge_cutoff=end,
        research_callback=lambda result, trigger: callbacks.append((result, trigger)),
    )

    assert callbacks
    assert all(result.market_as_of >= start for result, _ in callbacks)
    assert all(
        trigger.bar_close_at == result.market_as_of for result, trigger in callbacks
    )
    assert any(transition.event_at < start for transition in trace.transitions)


def test_replay_prerequisite_modes_fail_closed(sr_v2_config):
    start = datetime(2024, 1, 2, tzinfo=UTC)
    end = datetime(2024, 1, 2, 0, 30, tzinfo=UTC)
    model = replace(sr_v2_config, expiry=timedelta(days=1))
    research = SRV2ResearchNotebookConfigResolver(_research_mapping()).resolve()
    replay = SRV2ResearchReplay(model, research)
    bars = _replay_bars(model, start, end)
    with pytest.raises((TypeError, ValueError), match="EXACT_CHECKPOINT"):
        replay.run(
            bars,
            analysis_start=start,
            knowledge_cutoff=end,
            identity_mode="EXACT_CHECKPOINT",
        )
    with pytest.raises(ValueError, match="FULL_SOURCE|unsupported"):
        replay.run(
            bars,
            analysis_start=start,
            knowledge_cutoff=end,
            identity_mode="FULL_SOURCE",
        )

    reconstruction_start = start - model.expiry
    checkpoint_cutoff = reconstruction_start - timedelta(minutes=15)
    normalized = replay._normalize_source(bars)
    checkpoint_windows = OfflineCompute(model).windows_for(
        {
            timeframe: tuple(
                item.bar if isinstance(item, SourceBarRecord) else item
                for item in values
            )
            for timeframe, values in normalized.items()
        },
        checkpoint_cutoff,
    )
    checkpoint_bars = {
        timeframe: tuple(
            item.bar if isinstance(item, SourceBarRecord) else item for item in values
        )
        for timeframe, values in checkpoint_windows.items()
    }
    checkpoint = (
        SRModel(model)
        .step(
            SRStepRequest(
                venue=research.venue,
                instrument_id=research.instrument_id,
                asset=research.asset,
                market_as_of=checkpoint_cutoff,
                state=create_initial_state(
                    config_fingerprint=model.config_fingerprint,
                    venue=research.venue,
                    instrument_id=research.instrument_id,
                    asset=research.asset,
                ),
                windows=checkpoint_bars,
            )
        )
        .state
    )
    with pytest.raises(ValueError, match="WINDOW_RELATIVE"):
        replay.run(
            bars,
            analysis_start=start,
            knowledge_cutoff=end,
            initial_state=checkpoint,
        )
    exact = replay.run(
        bars,
        analysis_start=start,
        knowledge_cutoff=end,
        identity_mode="EXACT_CHECKPOINT",
        initial_state=checkpoint,
    )
    assert exact.identity_mode == "EXACT_CHECKPOINT"
    bad_checkpoint = replace(
        checkpoint, last_trigger_at=checkpoint_cutoff - timedelta(minutes=15)
    )
    with pytest.raises(ValueError, match="checkpoint"):
        replay.run(
            bars,
            analysis_start=start,
            knowledge_cutoff=end,
            identity_mode="EXACT_CHECKPOINT",
            initial_state=bad_checkpoint,
        )


def test_replay_requires_observed_declared_end(sr_v2_config):
    start = datetime(2024, 1, 2, tzinfo=UTC)
    end = datetime(2024, 1, 2, 0, 30, tzinfo=UTC)
    model = replace(sr_v2_config, expiry=timedelta(days=1))
    research = SRV2ResearchNotebookConfigResolver(_research_mapping()).resolve()
    bars = _replay_bars(model, start, end)
    truncated = dict(bars)
    truncated["15m"] = tuple(bars["15m"][:-1])
    with pytest.raises(ValueError, match="knowledge_cutoff"):
        SRV2ResearchReplay(model, research).run(
            truncated,
            analysis_start=start,
            knowledge_cutoff=end,
        )
