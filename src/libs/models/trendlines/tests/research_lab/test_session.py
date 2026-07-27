from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from tempfile import TemporaryDirectory

import pytest

from libs.models.trendlines.research_lab import (
    TrendlineResearchLabContractError,
    TrendlineReplayWindow,
    binance_lab_controls,
    injected_lab_controls,
    lab_export_table,
    resolve_provider_call_count,
    run_research_lab,
)

from . import session_for


def test_injected_mode_requires_supplied_frames_or_loader() -> None:
    controls = injected_lab_controls(
        asset="BTCUSDT",
        timeframes=("1h",),
        primary_timeframe="1h",
        replay_windows={"1h": TrendlineReplayWindow(19, 20, 31, 1)},
        start_inline_viewers=False,
    )
    with pytest.raises(Exception, match="loader|mapping|frame|timeframe"):
        asyncio.run(run_research_lab(controls))


def test_binance_guard_and_production_provider_accounting() -> None:
    controls = binance_lab_controls(
        asset="BTCUSDT",
        timeframes=("1h",),
        primary_timeframe="1h",
        event_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        knowledge_cutoff=datetime(2025, 1, 2, tzinfo=timezone.utc),
        replay_windows={"1h": TrendlineReplayWindow(19, 20, 31, 1)},
        provider_calls_authorized=False,
        start_inline_viewers=False,
    )

    class Loader:
        calls = 0

        async def load(self, spec):
            self.calls += 1
            raise AssertionError("loader must not be called")

    loader = Loader()
    with pytest.raises(Exception, match="authorization"):
        asyncio.run(run_research_lab(controls, loader=loader))
    assert loader.calls == 0
    production_loader = type("ProductionLoader", (), {"provider_calls": 3})()
    assert resolve_provider_call_count(production_loader, controls.data_mode) == 3
    malformed_loader = type("MalformedLoader", (), {"provider_calls": True})()
    with pytest.raises(TrendlineResearchLabContractError, match="non-negative integer"):
        resolve_provider_call_count(malformed_loader, controls.data_mode)


def test_one_preparation_and_replay_execution_produces_session_ids() -> None:
    session = session_for(("1h", "4h"))
    assert session.preparation_id
    assert session.replay_id
    assert tuple(session.replay.timeframes) == ("1h", "4h")
    assert session.provider_calls_made == 0
    assert lab_export_table(session).empty
    with TemporaryDirectory() as export_root:
        export_controls = replace(session.controls, permanent_export=True)
        exported = asyncio.run(
            run_research_lab(export_controls, export_root=export_root)
        )
        inventory = lab_export_table(exported)
        assert len(inventory) == 7
        assert inventory["exists"].all()
        assert (inventory["byte_length"] > 0).all()
        assert inventory["sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
        assert {
            "1h.evidence_bundle",
            "1h.viewer_bundle/manifest.json",
            "1h.viewer_bundle/chart_payload.json",
            "4h.evidence_bundle",
            "4h.viewer_bundle/manifest.json",
            "4h.viewer_bundle/chart_payload.json",
            "lab_session_manifest",
        } == set(inventory["name"])


def test_viewer_sessions_open_and_close_per_timeframe() -> None:
    session = session_for(("1h", "4h"))
    url = session.open_viewer("1h", session.replay.timeframes["1h"].recorded_positions[-1])
    assert url.startswith("http://127.0.0.1:")
    assert "1h" in session.viewer_urls
    temporary_root = session.viewer_bundle_paths["1h"].parent
    session.close()
    assert not session.viewer_sessions
    assert not session.viewer_bundle_paths
    assert not temporary_root.exists()
    with pytest.raises(TrendlineResearchLabContractError, match="closed"):
        session.open_viewer("1h", session.replay.timeframes["1h"].recorded_positions[-1])
    with pytest.raises(TrendlineResearchLabContractError, match="closed"):
        session.select("1h", session.replay.timeframes["1h"].recorded_positions[-1])
    with pytest.raises(TrendlineResearchLabContractError, match="closed"):
        session.latest_selection("1h")
    assert not session.viewer_sessions
    assert not session.viewer_bundle_paths
    session.close()
