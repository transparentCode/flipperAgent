from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

import pytest

from libs.models.sr_v2.features.time import grid_for
from libs.models.sr_v2.research_lab import (
    SRV2ResearchNotebookConfigResolver,
    SRV2ResearchReplay,
    build_research_source_set_manifest,
    compose_research_sync,
    source_bounds,
)
from libs.models.sr_v2.research_lab.data import BinanceUSDMResearchLoader
from libs.models.sr_v2.research_lab.trace import LifecycleInterval
from libs.models.sr_v2.research_viewer import (
    SRV2ResearchViewerSession,
    build_viewer_payload,
    create_owned_viewer_workspace,
    validate_viewer_bundle,
    write_viewer_bundle,
)
from libs.models.sr_v2.research_viewer.bundle import MAX_BUNDLE_BYTES, _project_zone_ids
from libs.models.sr_v2.research_viewer.projection import (
    ProjectionIndex,
)
from libs.models.sr_v2.runtime.offline import OfflineCompute
from tests.models.sr_v2.test_research_lab import _replay_bars, _research_mapping


def _display(*, candle_limit: int = 100) -> dict[str, object]:
    return {
        "iframe_height": 720,
        "candle_limit": candle_limit,
        "initial_mode": "formation",
        "show_zones": True,
        "show_candidates": False,
        "show_inspector": False,
        "show_history": False,
        "volume_pane_fraction": 0.2,
        "volume_pane_min_height": 120,
    }


def _research_config(*, cache_root: Path, source_mode: str = "CACHE_ONLY"):
    raw = _research_mapping()
    raw["research"] = {
        **raw["research"],
        "cache_root": str(cache_root),
        "source_mode": source_mode,
    }
    return SRV2ResearchNotebookConfigResolver(raw).resolve()


@pytest.fixture
def trace(sr_v2_config):
    model = replace(sr_v2_config, expiry=timedelta(days=1))
    research = SRV2ResearchNotebookConfigResolver(_research_mapping()).resolve()
    start = datetime(2024, 1, 2, tzinfo=UTC)
    end = start + timedelta(minutes=30)
    return SRV2ResearchReplay(model, research).run(
        _replay_bars(model, start, end),
        analysis_start=start,
        knowledge_cutoff=end,
    )


def test_trace_ladder_and_viewer_boundary_keep_all_kernel_rows(trace, tmp_path):
    payload = build_viewer_payload(
        trace,
        display=_display(candle_limit=1),
        market_identity={
            "venue": "binance_usdm",
            "instrument_id": "BTCUSDT",
            "asset": "BTCUSDT",
        },
    )
    assert tuple(payload["configured_timeframes"]) == trace.configured_timeframes
    assert set(payload["panes"]) == set(trace.configured_timeframes)
    for timeframe in trace.configured_timeframes:
        pane = payload["panes"][timeframe]
        assert len(pane["formation"]["candles"]) <= 1
        assert "features" not in pane["formation"]
        assert "zones" not in pane["lifecycle"]
        assert "intervals" not in pane["lifecycle"]
        assert "transitions" not in pane["lifecycle"]
        assert "touch_episodes" not in pane["lifecycle"]
        assert "markers" not in pane["lifecycle"]
        assert "zone_bands" not in pane["lifecycle"]
        assert isinstance(pane["formation"]["kernel_ids"], list)
        assert all(
            set(item) == {"available_at", "side", "kernel_id", "count"}
            for item in pane["formation"]["candidates"]
        )
        assert len(
            {row["bar_close_at"] for row in pane["formation"]["candles"]}
        ) == len(pane["formation"]["candles"])
    bundle = write_viewer_bundle(
        trace,
        tmp_path / "bundle",
        display=_display(candle_limit=1),
        market_identity={
            "venue": "binance_usdm",
            "instrument_id": "BTCUSDT",
            "asset": "BTCUSDT",
        },
    )
    raw = (bundle / "chart_payload.json").read_text(encoding="utf-8")
    assert "__decimal__" not in raw
    assert "__datetime__" not in raw
    evidence = json.loads((bundle / "evidence_index.json").read_text(encoding="utf-8"))
    assert evidence["payload_id"] == json.loads(raw)["payload_id"]
    assert evidence["panes"]
    assert validate_viewer_bundle(bundle)["configured_timeframes"] == list(
        trace.configured_timeframes
    )


def test_evidence_sidecar_uses_only_bounded_display_projection(trace, tmp_path):
    bundle = write_viewer_bundle(
        trace,
        tmp_path / "bundle",
        display=_display(candle_limit=1),
        market_identity={
            "venue": "binance_usdm",
            "instrument_id": "BTCUSDT",
            "asset": "BTCUSDT",
        },
    )
    payload = json.loads((bundle / "chart_payload.json").read_text(encoding="utf-8"))
    evidence_path = bundle / "evidence_index.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    for timeframe in trace.configured_timeframes:
        chart_pane = payload["panes"][timeframe]
        sidecar_pane = evidence["panes"][timeframe]
        assert "candles" not in sidecar_pane["formation"]
        assert "candles" not in sidecar_pane["lifecycle"]
        formation_closes = {
            row["bar_close_at"] for row in chart_pane["formation"]["candles"]
        }
        lifecycle_closes = {
            row["bar_close_at"] for row in chart_pane["lifecycle"]["candles"]
        }
        assert all(
            row["bar_close_at"] in formation_closes
            for row in sidecar_pane["formation"]["features"]
        )
        assert all(
            row["cutoff"] <= evidence["knowledge_cutoff"]
            for row in sidecar_pane["formation"]["candidates"]
        )
        window_start = datetime.fromisoformat(
            sidecar_pane["lifecycle"]["inspection"]["window_start"]
        )
        assert all(
            window_start <= datetime.fromisoformat(row["bar_close_at"])
            for row in sidecar_pane["formation"]["features"]
        )
        assert all(
            window_start <= datetime.fromisoformat(row["cutoff"])
            for row in sidecar_pane["formation"]["candidates"]
        )
        assert all(
            window_start
            <= datetime.fromisoformat(row["event_at"])
            <= datetime.fromisoformat(evidence["knowledge_cutoff"])
            for row in sidecar_pane["lifecycle"]["transitions"]
        )
        expected_zone_ids = _project_zone_ids(
            trace,
            timeframe,
            window_start=window_start,
            window_end=trace.knowledge_cutoff,
        )
        assert {
            zone["zone_id"] for zone in sidecar_pane["lifecycle"]["zones"]
        } == expected_zone_ids
        assert formation_closes or lifecycle_closes

    assert evidence_path.stat().st_size < MAX_BUNDLE_BYTES


def test_large_historical_rows_do_not_expand_bounded_sidecar(trace, tmp_path):
    source_rows = sorted(
        (row for row in trace.feature_rows if row.get("timeframe") == "15m"),
        key=lambda row: row["bar_close_at"],
    )
    assert len(source_rows) >= 2
    old_row, latest_row = source_rows[0], source_rows[-1]
    old_close = old_row["bar_close_at"]
    latest_close = latest_row["bar_close_at"]
    old_close_text = old_close.isoformat(timespec="microseconds")
    old_candidate = {
        "timeframe": "15m",
        "cutoff": old_close,
        "available_at": old_close,
        "candidate_key": "synthetic-old",
        "source_evidence_id": "synthetic-old-evidence",
        "side": "SUPPORT",
        "kernel_id": "synthetic",
    }
    latest_candidate = {
        **old_candidate,
        "cutoff": latest_close,
        "available_at": latest_close,
        "candidate_key": "synthetic-latest",
        "source_evidence_id": "synthetic-latest-evidence",
    }
    large_trace = replace(
        trace,
        feature_rows=tuple([dict(old_row)] * 20_000 + [dict(latest_row)]),
        candidate_rows=tuple([old_candidate] * 20_000 + [latest_candidate]),
    )

    bundle = write_viewer_bundle(
        large_trace,
        tmp_path / "large-bundle",
        display=_display(candle_limit=1),
        market_identity={
            "venue": "binance_usdm",
            "instrument_id": "BTCUSDT",
            "asset": "BTCUSDT",
        },
    )
    payload = json.loads((bundle / "chart_payload.json").read_text(encoding="utf-8"))
    evidence_path = bundle / "evidence_index.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence_path.stat().st_size < MAX_BUNDLE_BYTES
    pane = evidence["panes"]["15m"]
    assert all(
        row["bar_close_at"] != old_close_text for row in pane["formation"]["features"]
    )
    assert all(
        row["cutoff"] != old_close_text for row in pane["formation"]["candidates"]
    )
    assert len(payload["panes"]["15m"]["formation"]["candles"]) == 1


def test_server_projection_index_matches_causal_projection(trace, tmp_path):
    bundle = write_viewer_bundle(
        trace,
        tmp_path / "bundle",
        display=_display(candle_limit=2),
        market_identity={
            "venue": "binance_usdm",
            "instrument_id": "BTCUSDT",
            "asset": "BTCUSDT",
        },
    )
    payload = json.loads((bundle / "chart_payload.json").read_text(encoding="utf-8"))
    evidence = json.loads((bundle / "evidence_index.json").read_text(encoding="utf-8"))
    index = ProjectionIndex(evidence, payload)

    for timeframe in trace.configured_timeframes:
        for cutoff in payload["panes"][timeframe]["inspection"]["available_cutoffs"]:
            inspection = index.project_inspection(timeframe, cutoff)
            assert inspection["cutoff"] == cutoff
            assert all(row["event_at"] <= cutoff for row in inspection["transitions"])

    session = SRV2ResearchViewerSession(bundle)
    try:
        indexed = session._server.projection_index
        assert indexed is not None
        assert session._server.projection_index is indexed
    finally:
        session.close()


def test_viewer_projection_excludes_terminal_and_transitive_burn_in_context():
    reconstruction_start = datetime(2024, 1, 1, tzinfo=UTC)
    analysis_start = datetime(2024, 1, 10, tzinfo=UTC)
    window_end = datetime(2024, 1, 11, tzinfo=UTC)

    def zone(
        zone_id, *, formed_at, predecessor_id=None, evidence_id=None, candidate_key=None
    ):
        return SimpleNamespace(
            lineage=SimpleNamespace(
                zone_id=zone_id,
                source_timeframe="1h",
                formed_at=formed_at,
                predecessor_id=predecessor_id,
                source_evidence_id=evidence_id or f"evidence-{zone_id}",
                source_candidate_key=candidate_key or f"candidate-{zone_id}",
            )
        )

    active_id = "boundary-active"
    one_hop_id = "one-hop"
    ancestor_id = "transitive-ancestor"
    terminal_id = "terminal-pre-window"
    candidate_id = "candidate-only"
    transition_id = "transition-only"
    records = {
        active_id: zone(
            active_id, formed_at=reconstruction_start, predecessor_id=one_hop_id
        ),
        one_hop_id: zone(
            one_hop_id,
            formed_at=reconstruction_start + timedelta(days=1),
            predecessor_id=ancestor_id,
        ),
        ancestor_id: zone(ancestor_id, formed_at=reconstruction_start),
        terminal_id: zone(terminal_id, formed_at=reconstruction_start),
        candidate_id: zone(
            candidate_id,
            formed_at=analysis_start,
            evidence_id="candidate-evidence",
            candidate_key="candidate-key",
        ),
        transition_id: zone(transition_id, formed_at=analysis_start),
    }
    trace = SimpleNamespace(
        lineage_records=records,
        lifecycle_intervals=(
            LifecycleInterval(
                zone_id=active_id,
                source_timeframe="1h",
                lifecycle="ACTIVE",
                entered_at=reconstruction_start,
                exited_at=None,
            ),
            LifecycleInterval(
                zone_id=terminal_id,
                source_timeframe="1h",
                lifecycle="BROKEN",
                entered_at=reconstruction_start,
                exited_at=None,
            ),
        ),
        transitions=(
            SimpleNamespace(
                zone_id=transition_id,
                event_at=analysis_start,
                predecessor_id=None,
                successor_id=None,
            ),
            SimpleNamespace(
                zone_id=active_id,
                event_at=reconstruction_start,
                predecessor_id=one_hop_id,
                successor_id=None,
            ),
        ),
        candidate_rows=(
            {
                "timeframe": "1h",
                "cutoff": analysis_start,
                "candidate_key": "candidate-key",
                "source_evidence_id": "candidate-evidence",
            },
        ),
        analysis_start=analysis_start,
        reconstruction_start=reconstruction_start,
    )

    projected = _project_zone_ids(
        trace,
        "1h",
        window_start=analysis_start,
        window_end=window_end,
    )

    assert projected == {active_id, one_hop_id, candidate_id, transition_id}
    assert terminal_id not in projected
    assert ancestor_id not in projected


def test_viewer_bundle_rejects_tagged_or_non_utc_chart_values(trace, tmp_path):
    bundle = write_viewer_bundle(
        trace,
        tmp_path / "bundle",
        display=_display(),
        market_identity={
            "venue": "binance_usdm",
            "instrument_id": "BTCUSDT",
            "asset": "BTCUSDT",
        },
    )
    path = bundle / "chart_payload.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    timeframe = payload["configured_timeframes"][0]
    payload["panes"][timeframe]["formation"]["candles"][0]["open"] = {
        "__decimal__": "100"
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="payload ID"):
        validate_viewer_bundle(bundle)


def test_source_bounds_use_one_trigger_preflight_and_exact_trailing_count(
    sr_v2_config, tmp_path
):
    model = replace(sr_v2_config, expiry=timedelta(days=1))
    research = _research_config(cache_root=tmp_path)
    bounds = source_bounds(model, research)
    requirements = dict(model.history_requirements())
    reconstruction_start = research.analysis_start - model.expiry
    for timeframe in model.ladder:
        expected_start = (
            grid_for(timeframe).expected_closed_cutoff(reconstruction_start)
            - grid_for(timeframe).duration * requirements[timeframe]
        )
        assert bounds[timeframe][0] == expected_start


def test_research_replay_delegates_one_close_index_build_to_offline(
    sr_v2_config, monkeypatch
):
    model = replace(sr_v2_config, expiry=timedelta(days=1))
    research = SRV2ResearchNotebookConfigResolver(_research_mapping()).resolve()
    start = datetime(2024, 1, 2, tzinfo=UTC)
    end = start + timedelta(minutes=30)
    bars = _replay_bars(model, start, end)
    replay = SRV2ResearchReplay(model, research)
    original = OfflineCompute._build_close_indexes
    calls = 0

    def counted(values):
        nonlocal calls
        calls += 1
        return original(values)

    monkeypatch.setattr(OfflineCompute, "_build_close_indexes", staticmethod(counted))
    replay.run(bars, analysis_start=start, knowledge_cutoff=end)
    assert calls == 1


def test_loader_enforces_real_cursor_limit_and_rejects_gap_duplicate_or_stall(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    duration = timedelta(hours=1)
    rows = [
        {
            "timestamp": int((start + duration * index).timestamp() * 1000),
            "open": "100",
            "high": "101",
            "low": "99",
            "close": "100",
            "volume": "2",
            "close_time": int(
                (start + duration * (index + 1) - timedelta(milliseconds=1)).timestamp()
                * 1000
            ),
        }
        for index in range(1501)
    ]

    class Paged:
        def __init__(self, values, *, mode="normal"):
            self.values = values
            self.mode = mode
            self.calls = 0

        async def get_historical_ohlcv(self, _symbol, _timeframe, **kwargs):
            self.calls += 1
            if self.mode == "stall":
                return self.values[:1]
            start_ms = kwargs["since"]
            end_ms = kwargs["until"]
            selected = [
                row for row in self.values if start_ms <= row["timestamp"] < end_ms
            ]
            if self.mode == "duplicate" and self.calls == 2:
                selected.insert(0, self.values[1499])
            return selected[: kwargs["limit"]]

    end = start + duration * len(rows)
    adapter = Paged(rows)
    paged_loader = BinanceUSDMResearchLoader(
        adapter, cache_root=tmp_path, venue="binance_usdm"
    )
    result = asyncio.run(
        paged_loader.load(
            instrument_id="BTCUSDT",
            asset="BTCUSDT",
            timeframe="1h",
            start=start,
            end=end,
            source_mode="BINANCE_USDM",
            provider_calls_authorized=True,
        )
    )
    assert len(result.records) == 1501
    assert result.provider_calls == adapter.calls == 2
    assert result.total_provider_calls == 2
    repeated = asyncio.run(
        paged_loader.load(
            instrument_id="BTCUSDT",
            asset="BTCUSDT",
            timeframe="1h",
            start=start,
            end=end,
            source_mode="BINANCE_USDM",
            provider_calls_authorized=True,
        )
    )
    assert repeated.provider_calls == 2
    assert repeated.total_provider_calls == 4

    gap_rows = rows[:1000] + rows[1001:]
    with pytest.raises(ValueError, match="gap|contiguous|cover"):
        asyncio.run(
            BinanceUSDMResearchLoader(
                Paged(gap_rows), cache_root=tmp_path / "gap", venue="binance_usdm"
            ).load(
                instrument_id="BTCUSDT",
                asset="BTCUSDT",
                timeframe="1h",
                start=start,
                end=end,
                source_mode="BINANCE_USDM",
                provider_calls_authorized=True,
            )
        )
    with pytest.raises(ValueError, match="duplicate"):
        asyncio.run(
            BinanceUSDMResearchLoader(
                Paged(rows, mode="duplicate"),
                cache_root=tmp_path / "duplicate",
                venue="binance_usdm",
            ).load(
                instrument_id="BTCUSDT",
                asset="BTCUSDT",
                timeframe="1h",
                start=start,
                end=end,
                source_mode="BINANCE_USDM",
                provider_calls_authorized=True,
            )
        )
    with pytest.raises(ValueError, match="progress|duplicate"):
        asyncio.run(
            BinanceUSDMResearchLoader(
                Paged(rows, mode="stall"),
                cache_root=tmp_path / "stall",
                venue="binance_usdm",
            ).load(
                instrument_id="BTCUSDT",
                asset="BTCUSDT",
                timeframe="1h",
                start=start,
                end=end,
                source_mode="BINANCE_USDM",
                provider_calls_authorized=True,
            )
        )


def test_loader_captures_one_cutoff_before_pages_and_rejects_unclosed_requested_end(
    tmp_path,
):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    duration = timedelta(minutes=15)
    rows = [
        {
            "timestamp": int((start + duration * index).timestamp() * 1000),
            "open": "100",
            "high": "101",
            "low": "99",
            "close": "100",
            "volume": "2",
            "close_time": int(
                (start + duration * (index + 1) - timedelta(milliseconds=1)).timestamp()
                * 1000
            ),
        }
        for index in range(1501)
    ]
    end = start + duration * len(rows)

    class Paged:
        def __init__(self):
            self.calls = 0

        async def get_historical_ohlcv(self, _symbol, _timeframe, **kwargs):
            self.calls += 1
            lower = kwargs["since"]
            upper = kwargs["until"]
            return [row for row in rows if lower <= row["timestamp"] < upper][
                : kwargs["limit"]
            ]

    clock_calls = []
    adapter = Paged()
    loader = BinanceUSDMResearchLoader(
        adapter,
        cache_root=tmp_path / "paged",
        venue="binance_usdm",
        clock=lambda: clock_calls.append(True) or end + timedelta(hours=1),
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
    assert len(result.records) == len(rows)
    assert adapter.calls == 2
    assert len(clock_calls) == 1
    assert result.acquisition_cutoff == end + timedelta(hours=1)

    future_adapter = Paged()
    future_loader = BinanceUSDMResearchLoader(
        future_adapter,
        cache_root=tmp_path / "future-end",
        venue="binance_usdm",
        clock=lambda: end - timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="latest closed|acquisition cutoff"):
        asyncio.run(
            future_loader.load(
                instrument_id="BTCUSDT",
                asset="BTCUSDT",
                timeframe="15m",
                start=start,
                end=end,
                source_mode="BINANCE_USDM",
                provider_calls_authorized=True,
            )
        )
    assert future_adapter.calls == 0


def test_loader_rejects_bad_bounds_identity_close_evidence_and_symlink_manifest(
    tmp_path,
):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)

    def row(*, close_time=None, timestamp=start):
        value = {
            "timestamp": int(timestamp.timestamp() * 1000),
            "open": "100",
            "high": "101",
            "low": "99",
            "close": "100",
            "volume": "2",
        }
        if close_time is not None:
            value["close_time"] = int(close_time.timestamp() * 1000)
        return value

    class Adapter:
        def __init__(self, values):
            self.values = values

        async def get_historical_ohlcv(self, _symbol, _timeframe, **_kwargs):
            return self.values

    valid = row(close_time=end - timedelta(milliseconds=1))
    loader = BinanceUSDMResearchLoader(
        Adapter([valid]), cache_root=tmp_path, venue="binance_usdm"
    )
    result = asyncio.run(
        loader.load(
            instrument_id="BTCUSDT",
            asset="BTCUSDT",
            timeframe="1h",
            start=start,
            end=end,
            source_mode="BINANCE_USDM",
            provider_calls_authorized=True,
        )
    )
    assert result.records[-1].bar.bar_close_at == end
    future = row(
        timestamp=end,
        close_time=end + timedelta(hours=1) - timedelta(milliseconds=1),
    )
    filtered = asyncio.run(
        BinanceUSDMResearchLoader(
            Adapter([valid, future]),
            cache_root=tmp_path / "future-row",
            venue="binance_usdm",
        ).load(
            instrument_id="BTCUSDT",
            asset="BTCUSDT",
            timeframe="1h",
            start=start,
            end=end,
            source_mode="BINANCE_USDM",
            provider_calls_authorized=True,
        )
    )
    assert len(filtered.records) == 1 and filtered.records[0].bar.bar_close_at == end

    with pytest.raises(ValueError, match="UTC"):
        asyncio.run(
            loader.load(
                instrument_id="BTCUSDT",
                asset="BTCUSDT",
                timeframe="1h",
                start=start.replace(tzinfo=None),
                end=end,
                source_mode="CACHE_ONLY",
            )
        )
    with pytest.raises(ValueError, match="grid|aligned"):
        asyncio.run(
            loader.load(
                instrument_id="BTCUSDT",
                asset="BTCUSDT",
                timeframe="1h",
                start=start + timedelta(minutes=15),
                end=end + timedelta(minutes=15),
                source_mode="CACHE_ONLY",
            )
        )
    with pytest.raises(ValueError, match="close evidence"):
        asyncio.run(
            BinanceUSDMResearchLoader(
                Adapter([row()]),
                cache_root=tmp_path / "missing-close",
                venue="binance_usdm",
            ).load(
                instrument_id="BTCUSDT",
                asset="BTCUSDT",
                timeframe="1h",
                start=start,
                end=end,
                source_mode="BINANCE_USDM",
                provider_calls_authorized=True,
            )
        )
    with pytest.raises(ValueError, match="interval"):
        asyncio.run(
            BinanceUSDMResearchLoader(
                Adapter([row(close_time=end + timedelta(milliseconds=1))]),
                cache_root=tmp_path / "future-close",
                venue="binance_usdm",
            ).load(
                instrument_id="BTCUSDT",
                asset="BTCUSDT",
                timeframe="1h",
                start=start,
                end=end,
                source_mode="BINANCE_USDM",
                provider_calls_authorized=True,
            )
        )

    with pytest.raises(ValueError, match="identity|mismatch"):
        asyncio.run(
            loader.load(
                instrument_id="ETHUSDT",
                asset="ETHUSDT",
                timeframe="1h",
                start=start,
                end=end,
                source_mode="CACHE_ONLY",
                cache_path=result.cache_path,
            )
        )
    cache_link = tmp_path / "cache-link.jsonl"
    cache_link.symlink_to(result.cache_path)
    with pytest.raises(FileNotFoundError):
        asyncio.run(
            loader.load(
                instrument_id="BTCUSDT",
                asset="BTCUSDT",
                timeframe="1h",
                start=start,
                end=end,
                source_mode="CACHE_ONLY",
                cache_path=cache_link,
            )
        )
    assert result.manifest_path is not None
    manifest_backup = tmp_path / "manifest-copy.json"
    manifest_backup.write_bytes(result.manifest_path.read_bytes())
    result.manifest_path.unlink()
    result.manifest_path.symlink_to(manifest_backup)
    with pytest.raises(ValueError, match="manifest"):
        asyncio.run(
            loader.load(
                instrument_id="BTCUSDT",
                asset="BTCUSDT",
                timeframe="1h",
                start=start,
                end=end,
                source_mode="CACHE_ONLY",
            )
        )


def test_owned_viewer_cleanup_rejects_broad_paths(trace, tmp_path):
    bundle = write_viewer_bundle(
        trace,
        tmp_path / "bundle",
        display=_display(),
        market_identity={
            "venue": "binance_usdm",
            "instrument_id": "BTCUSDT",
            "asset": "BTCUSDT",
        },
    )
    with pytest.raises(ValueError, match="owned|sentinel|exact"):
        SRV2ResearchViewerSession(bundle, cleanup_directory=tmp_path)
    workspace, owned_bundle = create_owned_viewer_workspace(tmp_path)
    write_viewer_bundle(
        trace,
        owned_bundle,
        display=_display(),
        market_identity={
            "venue": "binance_usdm",
            "instrument_id": "BTCUSDT",
            "asset": "BTCUSDT",
        },
    )
    session = SRV2ResearchViewerSession(owned_bundle, cleanup_directory=workspace)
    session.close()
    session.close()
    assert not workspace.exists()


def test_source_set_manifest_is_ordered_and_binds_authenticated_results(
    sr_v2_config, tmp_path
):
    model = replace(sr_v2_config, expiry=timedelta(days=1))
    research = _research_config(cache_root=tmp_path, source_mode="BINANCE_USDM")
    bounds = source_bounds(model, research)

    class Adapter:
        async def get_historical_ohlcv(self, _symbol, timeframe, **kwargs):
            start = datetime.fromtimestamp(kwargs["since"] / 1000, tz=UTC)
            end = datetime.fromtimestamp(kwargs["until"] / 1000, tz=UTC)
            duration = {
                "15m": timedelta(minutes=15),
                "30m": timedelta(minutes=30),
                "1h": timedelta(hours=1),
                "4h": timedelta(hours=4),
                "6h": timedelta(hours=6),
                "1d": timedelta(days=1),
            }[timeframe]
            rows = []
            opened = start
            while opened < end:
                rows.append(
                    {
                        "timestamp": int(opened.timestamp() * 1000),
                        "open": "100",
                        "high": "101",
                        "low": "99",
                        "close": "100",
                        "volume": "2",
                        "taker_buy_base": "1",
                        "close_time": int(
                            (opened + duration - timedelta(milliseconds=1)).timestamp()
                            * 1000
                        ),
                    }
                )
                opened += duration
            return rows

    loader = BinanceUSDMResearchLoader(
        Adapter(), cache_root=tmp_path, venue="binance_usdm"
    )
    results = {
        timeframe: asyncio.run(
            loader.load(
                instrument_id=research.instrument_id,
                asset=research.asset,
                timeframe=timeframe,
                start=start,
                end=end,
                source_mode="BINANCE_USDM",
                provider_calls_authorized=True,
            )
        )
        for timeframe, (start, end) in bounds.items()
    }
    aggregate = build_research_source_set_manifest(
        results,
        ladder=model.ladder,
        venue=research.venue,
        instrument_id=research.instrument_id,
        asset=research.asset,
        bounds=bounds,
    )
    assert aggregate.timeframes == model.ladder
    aggregate.verify(
        ladder=model.ladder,
        venue=research.venue,
        instrument_id=research.instrument_id,
        asset=research.asset,
        bounds=bounds,
    )
    with pytest.raises(ValueError, match="exact resolved ladder|ordered|timeframe"):
        build_research_source_set_manifest(
            {**results, "2h": results["1h"]},
            ladder=(*model.ladder, "2h"),
            venue=research.venue,
            instrument_id=research.instrument_id,
            asset=research.asset,
            bounds={**bounds, "2h": bounds["1h"]},
        )


def test_notebook_composition_provider_then_cache_only_reuses_exact_source_set(
    sr_v2_config, tmp_path
):
    model = replace(sr_v2_config, expiry=timedelta(days=1))
    provider_config = _research_config(cache_root=tmp_path, source_mode="BINANCE_USDM")

    class Adapter:
        def __init__(self):
            self.calls = []

        async def get_historical_ohlcv(self, _symbol, timeframe, **kwargs):
            self.calls.append((timeframe, kwargs))
            start = datetime.fromtimestamp(kwargs["since"] / 1000, tz=UTC)
            end = datetime.fromtimestamp(kwargs["until"] / 1000, tz=UTC)
            duration = {
                "15m": timedelta(minutes=15),
                "30m": timedelta(minutes=30),
                "1h": timedelta(hours=1),
                "4h": timedelta(hours=4),
                "6h": timedelta(hours=6),
                "1d": timedelta(days=1),
            }[timeframe]
            rows = []
            opened = start
            while opened < end:
                rows.append(
                    {
                        "timestamp": int(opened.timestamp() * 1000),
                        "open": "100",
                        "high": "101",
                        "low": "99",
                        "close": "100",
                        "volume": "2",
                        "taker_buy_base": "1",
                        "close_time": int(
                            (opened + duration - timedelta(milliseconds=1)).timestamp()
                            * 1000
                        ),
                    }
                )
                opened += duration
            return rows

    adapter = Adapter()

    class ChangingClock:
        def __init__(self):
            self.calls = 0

        def __call__(self):
            self.calls += 1
            return datetime(2024, 1, 10, tzinfo=UTC) + timedelta(seconds=self.calls)

    clock = ChangingClock()
    first = compose_research_sync(
        model,
        provider_config,
        adapter=adapter,
        allow_provider_fetch=True,
        clock=clock,
    )
    try:
        assert adapter.calls
        assert clock.calls == 1
        assert (
            len({result.acquisition_cutoff for result in first.source_results.values()})
            == 1
        )
        assert first.trace.source_manifest_id != "unbound-source"
        first_id = first.source_manifest.manifest_id
    finally:
        first.close()

    cache_config = replace(provider_config, source_mode="CACHE_ONLY")
    offline = Adapter()
    second = compose_research_sync(model, cache_config, adapter=offline)
    try:
        assert offline.calls == []
        assert second.source_manifest.manifest_id == first_id
        assert second.trace.source_manifest_id == first_id
    finally:
        second.close()


def test_notebook_is_cleared_composition_only_and_keeps_cleanup_manual():
    path = Path("src/libs/models/sr_v2/research_lab/sr_v2_research_lab.ipynb")
    notebook = json.loads(path.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    assert all(
        not cell.get("outputs")
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )
    source = "\n".join("".join(cell["source"]) for cell in notebook["cells"])
    assert "await compose_research" in source
    assert "IFrame" in source and "display(" in source
    assert "CLOSE_VIEWER_NOW = False" in source
    assert "from libs.market_data import BinanceNativeAdapter" in source
    assert "get_historical_ohlcv" not in source


def test_research_viewer_and_notebook_semantic_locks():
    roots = (
        Path("src/libs/models/sr_v2/research_lab"),
        Path("src/libs/models/sr_v2/research_viewer"),
        Path("src/libs/models/sr_v2/research_lab/sr_v2_research_lab.ipynb"),
    )
    forbidden = (
        "select_top_down",
        "selected_references",
        "selection_reasons",
        "decision_app",
        "libs.models.sr import",
        "playwright",
        "selenium",
        "browser.launch",
        "https://cdn.",
    )
    files = [root for root in roots if root.is_file()]
    for root in roots:
        if root.is_dir():
            files.extend(root.rglob("*.py"))
            files.extend(root.rglob("*.js"))
    text = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert not [needle for needle in forbidden if needle in text]


@pytest.mark.skipif(
    not (
        Path("src/libs/models/sr_v2/research_viewer/web/node_modules")
        / "lightweight-charts/dist/lightweight-charts.standalone.production.mjs"
    ).is_file(),
    reason="viewer dependencies are installed by the package validation gate",
)
def test_server_is_request_local_and_query_isolated(trace, tmp_path):
    bundle = write_viewer_bundle(
        trace,
        tmp_path / "bundle",
        display=_display(),
        market_identity={
            "venue": "binance_usdm",
            "instrument_id": "BTCUSDT",
            "asset": "BTCUSDT",
        },
    )
    session = SRV2ResearchViewerSession(bundle)
    try:
        with pytest.raises(HTTPError):
            urlopen(session.url, timeout=3)
        for timeframe in ("1d", "4h"):
            with urlopen(
                f"{session.url}bundle/chart_payload.json?source_timeframe={timeframe}",
                timeout=3,
            ) as response:
                selected = json.load(response)
                assert response.headers["Cache-Control"] == "no-store"
            assert selected["configured_timeframes"] == [timeframe]
            assert set(selected["panes"]) == {timeframe}
            assert selected["schema_version"] == 2
            assert "features" not in selected["panes"][timeframe]["formation"]
            assert "transitions" not in selected["panes"][timeframe]["lifecycle"]
            cutoff = selected["panes"][timeframe]["inspection"]["available_cutoffs"][-1]
            with urlopen(
                f"{session.url}bundle/inspection.json?source_timeframe={timeframe}&cutoff={quote(cutoff, safe='')}",
                timeout=3,
            ) as response:
                inspection = json.load(response)
                assert response.headers["Cache-Control"] == "no-store"
            assert inspection["cutoff"] == cutoff
            assert "response_id" in inspection
            cache_size = len(session._server._response_cache)
            with urlopen(
                f"{session.url}bundle/lineage_history.json?source_timeframe={timeframe}&cutoff={quote(cutoff, safe='')}",
                timeout=3,
            ) as response:
                history = json.load(response)
                assert response.headers["Cache-Control"] == "no-store"
            assert history["cutoff"] == cutoff
            assert history["source_timeframe"] == timeframe
            assert "response_id" in history
            assert all(
                set(row)
                == {
                    "zone_id",
                    "source_timeframe",
                    "lifecycle",
                    "entered_at",
                    "exited_at",
                }
                for row in history["lifecycle_intervals"]
            )
            assert not {"transitions", "touch_episodes", "candidates"}.intersection(
                history
            )
            assert len(session._server._response_cache) == cache_size
            with urlopen(
                f"{session.url}bundle/lineage_history.json?source_timeframe={timeframe}&cutoff={quote(cutoff, safe='')}",
                timeout=3,
            ):
                pass
            assert len(session._server._response_cache) == cache_size

        def fetch_selected(timeframe):
            with urlopen(
                f"{session.url}bundle/chart_payload.json?source_timeframe={timeframe}",
                timeout=3,
            ) as response:
                return json.load(response)

        with ThreadPoolExecutor(max_workers=2) as executor:
            concurrent = tuple(executor.map(fetch_selected, ("1d", "4h")))
        assert [item["configured_timeframes"] for item in concurrent] == [
            ["1d"],
            ["4h"],
        ]
        with urlopen(f"{session.url}dist/payload_utils.js", timeout=3) as response:
            assert response.status == 200
        with pytest.raises(HTTPError):
            urlopen(f"{session.url}styles.css?source_timeframe=1d", timeout=3)
        with pytest.raises(HTTPError):
            urlopen(
                f"{session.url}bundle/inspection.json?source_timeframe=1d&cutoff=not-utc",
                timeout=3,
            )
        with pytest.raises(HTTPError):
            urlopen(
                f"{session.url}bundle/inspection.json?source_timeframe=1d&source_timeframe=4h&cutoff=2024-01-02T00:15:00.000000+00:00",
                timeout=3,
            )
        with pytest.raises(HTTPError):
            urlopen(
                f"{session.url}bundle/lineage_history.json?source_timeframe=1d&cutoff={quote(cutoff, safe='')}&extra=1",
                timeout=3,
            )
        with pytest.raises(HTTPError):
            urlopen(
                f"{session.url}bundle/lineage_history.json?source_timeframe=1d&source_timeframe=4h&cutoff={quote(cutoff, safe='')}",
                timeout=3,
            )
        with pytest.raises(HTTPError):
            urlopen(
                f"{session.url}bundle/lineage_history.json?source_timeframe=1d",
                timeout=3,
            )
        with pytest.raises(HTTPError):
            urlopen(
                f"{session.url}bundle/lineage_history.json?source_timeframe=1d&cutoff=not-utc",
                timeout=3,
            )
        with pytest.raises(HTTPError):
            urlopen(
                f"{session.url}bundle/zone_detail.json?source_timeframe=1d&zone_id=not-in-pane&cutoff=2024-01-02T00:15:00.000000+00:00",
                timeout=3,
            )
    finally:
        session.close()


def test_projection_applies_exit_before_entry_and_censors_future_mutable_fields():
    base = {
        "schema_version": 2,
        "trace_id": "trace",
        "as_of": "1970-01-01T00:00:30.000000+00:00",
        "identity_mode": "WINDOW_RELATIVE",
        "forecast_status": {
            "status": "UNAVAILABLE",
            "reason": "CALIBRATION_NOT_CONFIGURED",
            "forecasts": [],
        },
        "configured_timeframes": ["1h"],
        "panes": {
            "1h": {
                "source_timeframe": "1h",
                "formation": {
                    "timeframe": "1h",
                    "candles": [
                        {
                            "bar_close_at": "1970-01-01T00:00:10.000000+00:00",
                            "open": "100",
                            "high": "101",
                            "low": "99",
                            "close": "100",
                        },
                        {
                            "bar_close_at": "1970-01-01T00:00:20.000000+00:00",
                            "open": "100",
                            "high": "102",
                            "low": "98",
                            "close": "101",
                        },
                        {
                            "bar_close_at": "1970-01-01T00:00:30.000000+00:00",
                            "open": "101",
                            "high": "103",
                            "low": "99",
                            "close": "102",
                        },
                    ],
                    "features": [
                        {
                            "bar_close_at": "1970-01-01T00:00:20.000000+00:00",
                            "kernel_id": "k",
                            "timeframe": "1h",
                            "open": "100",
                            "high": "102",
                            "low": "98",
                            "close": "101",
                        }
                    ],
                    "candidates": [
                        {
                            "candidate_key": "c",
                            "source_evidence_id": "e",
                            "available_at": "1970-01-01T00:00:10.000000+00:00",
                        }
                    ],
                },
                "lifecycle": {
                    "timeframe": "15m",
                    "candles": [],
                    "zones": [
                        {
                            "zone_id": "z",
                            "source_timeframe": "1h",
                            "side": "SUPPORT",
                            "center": "100",
                            "lower": "99",
                            "upper": "101",
                            "geometry": {
                                "center": "100",
                                "lower": "99",
                                "upper": "101",
                            },
                            "formed_at": "1970-01-01T00:00:10.000000+00:00",
                            "available_at": "1970-01-01T00:00:10.000000+00:00",
                            "source_evidence_id": "e",
                            "kernel_id": "k",
                            "kernel_version": "1",
                            "predecessor_id": None,
                            "source_candidate_key": "c",
                        },
                        {
                            "zone_id": "future",
                            "source_timeframe": "1h",
                            "side": "SUPPORT",
                            "center": "90",
                            "lower": "89",
                            "upper": "91",
                            "geometry": {"center": "90", "lower": "89", "upper": "91"},
                            "formed_at": "1970-01-01T00:00:00.000000+00:00",
                            "available_at": "1970-01-01T00:00:30.000000+00:00",
                            "source_evidence_id": "future-e",
                            "kernel_id": "k",
                            "kernel_version": "1",
                            "predecessor_id": "z",
                            "source_candidate_key": "future-c",
                        },
                    ],
                    "intervals": [
                        {
                            "zone_id": "z",
                            "source_timeframe": "1h",
                            "lifecycle": "ACTIVE",
                            "entered_at": "1970-01-01T00:00:10.000000+00:00",
                            "exited_at": "1970-01-01T00:00:20.000000+00:00",
                        },
                        {
                            "zone_id": "z",
                            "source_timeframe": "1h",
                            "lifecycle": "TOUCHED",
                            "entered_at": "1970-01-01T00:00:20.000000+00:00",
                            "exited_at": "1970-01-01T00:00:30.000000+00:00",
                        },
                    ],
                    "touch_episodes": [
                        {
                            "zone_id": "z",
                            "source_timeframe": "1h",
                            "episode_number": 1,
                            "started_at": "1970-01-01T00:00:20.000000+00:00",
                            "ended_at": "1970-01-01T00:00:30.000000+00:00",
                            "close_reason": "OVERLAP_EXIT",
                        }
                    ],
                    "transitions": [
                        {
                            "zone_id": "z",
                            "ordinal": 0,
                            "event": "CREATED",
                            "event_at": "1970-01-01T00:00:10.000000+00:00",
                            "after_lifecycle": "ACTIVE",
                            "after_touch_count": 0,
                            "after_break_pending_count": 0,
                            "after_overlapping": False,
                            "predecessor_id": None,
                            "successor_id": "future",
                        },
                        {
                            "zone_id": "z",
                            "ordinal": 1,
                            "event": "TOUCH_STARTED",
                            "event_at": "1970-01-01T00:00:20.000000+00:00",
                            "after_lifecycle": "TOUCHED",
                            "after_touch_count": 1,
                            "after_break_pending_count": 0,
                            "after_overlapping": True,
                            "predecessor_id": None,
                            "successor_id": "future",
                        },
                    ],
                    "inspection": {},
                },
            },
        },
    }
    index = ProjectionIndex(base)
    at_entry = index.project_inspection("1h", "1970-01-01T00:00:20.000000+00:00")
    assert at_entry["active_zones"][0]["lifecycle"] == "TOUCHED"
    assert at_entry["active_zones"][0]["successor_id"] is None
    assert at_entry["active_zones"][0]["exited_at"] is None
    assert at_entry["touch_episodes"][0]["ended_at"] is None
    assert at_entry["touch_episodes"][0]["close_reason"] is None
    detail = index.project_zone_detail("1h", "z", "1970-01-01T00:00:20.000000+00:00")
    assert detail["zone"]["successor_id"] is None
    assert detail["lifecycle_intervals"][-1]["exited_at"] is None
    assert detail["touch_episodes"][0]["ended_at"] is None
    with pytest.raises(ValueError, match="exposed|cutoff"):
        index.project_inspection("1h", "1970-01-01T00:00:25.000000+00:00")


def test_lineage_history_is_causally_censored_and_terminal_bounded():
    base = {
        "schema_version": 2,
        "trace_id": "history-trace",
        "as_of": "1970-01-01T00:00:40.000000+00:00",
        "identity_mode": "WINDOW_RELATIVE",
        "configured_timeframes": ["1h"],
        "panes": {
            "1h": {
                "source_timeframe": "1h",
                "formation": {
                    "timeframe": "1h",
                    "candles": [
                        {"bar_close_at": f"1970-01-01T00:00:{second:02d}.000000+00:00"}
                        for second in (10, 20, 30, 40)
                    ],
                    "features": [],
                    "candidates": [],
                },
                "lifecycle": {
                    "timeframe": "15m",
                    "candles": [],
                    "zones": [
                        {
                            "zone_id": zone_id,
                            "source_timeframe": "1h",
                            "side": "SUPPORT",
                            "center": "100",
                            "lower": "99",
                            "upper": "101",
                            "geometry": {
                                "center": "100",
                                "lower": "99",
                                "upper": "101",
                            },
                            "formed_at": "1970-01-01T00:00:00.000000+00:00",
                            "available_at": available,
                            "source_evidence_id": f"e-{zone_id}",
                            "kernel_id": "k",
                            "kernel_version": "1",
                            "predecessor_id": "z2" if zone_id == "z1" else None,
                            "source_candidate_key": f"c-{zone_id}",
                        }
                        for zone_id, available in (
                            ("z1", "1970-01-01T00:00:10.000000+00:00"),
                            ("z3", "1970-01-01T00:00:10.000000+00:00"),
                            ("z4", "1970-01-01T00:00:10.000000+00:00"),
                            ("z2", "1970-01-01T00:00:30.000000+00:00"),
                        )
                    ],
                    "intervals": [
                        {
                            "zone_id": "z1",
                            "source_timeframe": "1h",
                            "lifecycle": "ACTIVE",
                            "entered_at": "1970-01-01T00:00:05.000000+00:00",
                            "exited_at": "1970-01-01T00:00:45.000000+00:00",
                        },
                        {
                            "zone_id": "z1",
                            "source_timeframe": "1h",
                            "lifecycle": "TOUCHED",
                            "entered_at": "1970-01-01T00:00:40.000000+00:00",
                            "exited_at": None,
                        },
                        {
                            "zone_id": "z2",
                            "source_timeframe": "1h",
                            "lifecycle": "ACTIVE",
                            "entered_at": "1970-01-01T00:00:10.000000+00:00",
                            "exited_at": None,
                        },
                        {
                            "zone_id": "z3",
                            "source_timeframe": "1h",
                            "lifecycle": "ACTIVE",
                            "entered_at": "1970-01-01T00:00:10.000000+00:00",
                            "exited_at": "1970-01-01T00:00:20.000000+00:00",
                        },
                        {
                            "zone_id": "z4",
                            "source_timeframe": "1h",
                            "lifecycle": "ACTIVE",
                            "entered_at": "1970-01-01T00:00:10.000000+00:00",
                            "exited_at": "1970-01-01T00:00:50.000000+00:00",
                        },
                        {
                            "zone_id": "z4",
                            "source_timeframe": "1h",
                            "lifecycle": "BREAK_PENDING",
                            "entered_at": "1970-01-01T00:00:35.000000+00:00",
                            "exited_at": None,
                        },
                    ],
                    "touch_episodes": [],
                    "transitions": [
                        {
                            "zone_id": "z1",
                            "event": "CREATED",
                            "event_at": "1970-01-01T00:00:10.000000+00:00",
                            "successor_id": "z2",
                        },
                        {
                            "zone_id": "z4",
                            "event": "BROKEN",
                            "after_lifecycle": "BROKEN",
                            "event_at": "1970-01-01T00:00:30.000000+00:00",
                        },
                    ],
                    "inspection": {
                        "window_start": "1970-01-01T00:00:10.000000+00:00",
                    },
                },
            }
        },
    }
    index = ProjectionIndex(base)
    at_twenty = index.project_lineage_history("1h", "1970-01-01T00:00:20.000000+00:00")
    assert [row["zone_id"] for row in at_twenty["zones"]] == ["z1", "z3", "z4"]
    assert at_twenty["zones"][0]["predecessor_id"] is None
    assert len(at_twenty["lifecycle_intervals"]) == 3
    assert set(at_twenty["lifecycle_intervals"][0]) == {
        "zone_id",
        "source_timeframe",
        "lifecycle",
        "entered_at",
        "exited_at",
    }
    assert at_twenty["lifecycle_intervals"][0]["entered_at"].endswith("05.000000+00:00")
    assert at_twenty["lifecycle_intervals"][0]["exited_at"] is None
    assert at_twenty["lifecycle_intervals"][1]["zone_id"] == "z3"
    assert at_twenty["lifecycle_intervals"][1]["exited_at"].endswith("20.000000+00:00")
    assert at_twenty["lifecycle_intervals"][2]["zone_id"] == "z4"

    at_thirty = index.project_lineage_history("1h", "1970-01-01T00:00:30.000000+00:00")
    assert {row["zone_id"] for row in at_thirty["zones"]} == {"z1", "z2", "z3", "z4"}
    assert {
        row["zone_id"]: row["exited_at"] for row in at_thirty["lifecycle_intervals"]
    } == {
        "z1": None,
        "z3": "1970-01-01T00:00:20.000000+00:00",
        "z4": "1970-01-01T00:00:30.000000+00:00",
        "z2": None,
    }

    at_forty = index.project_lineage_history("1h", "1970-01-01T00:00:40.000000+00:00")
    assert [row["zone_id"] for row in at_forty["zones"]] == ["z1", "z3", "z4", "z2"]
    assert [
        (row["zone_id"], row["exited_at"]) for row in at_forty["lifecycle_intervals"]
    ] == [
        ("z1", None),
        ("z2", None),
        ("z3", "1970-01-01T00:00:20.000000+00:00"),
        ("z4", "1970-01-01T00:00:30.000000+00:00"),
        ("z1", None),
    ]
    assert all(
        row["lifecycle"] != "BREAK_PENDING" for row in at_forty["lifecycle_intervals"]
    )

    at_thirty_future_changed = json.loads(json.dumps(base))
    at_thirty_future_changed["panes"]["1h"]["lifecycle"]["intervals"][0][
        "exited_at"
    ] = "1970-01-01T00:09:00.000000+00:00"
    at_thirty_future_changed["panes"]["1h"]["lifecycle"]["transitions"].append(
        {
            "zone_id": "z1",
            "event": "BROKEN",
            "after_lifecycle": "BROKEN",
            "event_at": "1970-01-01T00:00:39.000000+00:00",
        }
    )
    assert (
        ProjectionIndex(at_thirty_future_changed).project_lineage_history(
            "1h", "1970-01-01T00:00:30.000000+00:00"
        )
        == at_thirty
    )
