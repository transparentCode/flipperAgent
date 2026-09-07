"""Focused contracts for the Trendlines V4 notebook research surface."""

from __future__ import annotations

import ast
import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from libs.models.trendlines_v4 import research_lab as support
from libs.models.trendlines_v4.contracts import (
    SideGeometryV2,
    TrendlineSnapshotV2,
)
from libs.models.trendlines_v4.core_v2 import analyze_trendlines_v2
from libs.models.trendlines_v4.engine.types import TrendlineGeometry
from libs.models.trendlines_v4.research_lab import data as data_support
from libs.models.trendlines_v4.research_lab import replay as replay_support
from libs.models.trendlines_v4.research_lab import tvlc as tvlc_support

ROOT = Path(__file__).resolve().parents[3]
NOTEBOOK = (
    ROOT / "src/libs/models/trendlines_v4/research_lab/trendlines_v4_research_lab.ipynb"
)


def _frame(count: int = 36) -> pd.DataFrame:
    start = datetime(2026, 6, 1, tzinfo=UTC)
    rows = []
    for index in range(count):
        open_at = start + timedelta(hours=index)
        base = 100.0 + (index % 7) * 0.7 + index * 0.03
        open_price = base
        close_price = base + (0.4 if index % 3 else -0.25)
        high = max(open_price, close_price) + 1.0
        low = min(open_price, close_price) - 1.0
        rows.append(
            {
                "timestamp": int(open_at.timestamp() * 1000),
                "close_time": int((open_at + timedelta(minutes=59)).timestamp() * 1000),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close_price,
                "volume": 10.0 + index,
            }
        )
    return pd.DataFrame(rows)


def _manual_snapshot(frame: pd.DataFrame) -> TrendlineSnapshotV2:
    bars = support.frame_to_trendline_bars(frame)
    start = bars[2].closed_at
    end = bars[-1].closed_at
    structural = TrendlineGeometry(
        side="support",
        start_anchor_at=start,
        start_anchor_price=99.0,
        end_anchor_at=end,
        end_anchor_price=100.0,
        slope_per_bar=1.0 / (len(bars) - 3),
        projected_price_at_market_as_of=100.0,
        post_anchor_body_crossed=False,
        post_anchor_body_cross_count=0,
        projection_positive=True,
    )
    secondary = TrendlineGeometry(
        side="support",
        start_anchor_at=bars[1].closed_at,
        start_anchor_price=98.0,
        end_anchor_at=end,
        end_anchor_price=99.0,
        slope_per_bar=1.0 / (len(bars) - 2),
        projected_price_at_market_as_of=99.0,
        post_anchor_body_crossed=False,
        post_anchor_body_cross_count=0,
        projection_positive=True,
    )
    return TrendlineSnapshotV2(
        schema_version="trendlines.geometry.v2",
        history_bar_count=len(bars),
        history_capacity_bars=300,
        pivot_window=3,
        history_start_at=bars[0].closed_at,
        market_as_of=bars[-1].closed_at,
        support=SideGeometryV2(structural, structural, secondary, True),
        resistance=SideGeometryV2(None, None, None, False),
    )


def test_notebook_is_valid_and_contains_the_required_sections() -> None:
    document = json.loads(NOTEBOOK.read_text())
    assert document["nbformat"] == 4
    source = "\n".join("".join(cell.get("source", [])) for cell in document["cells"])
    for heading in (
        "Trendlines V4 Geometry Research Lab",
        "Environment / imports",
        "User Controls",
        "Data Loading",
        "Run V4 Geometry",
        "Snapshot Summary Table",
        "Interactive TVLC Charts",
        "Geometry Diagnostics",
        "Pivot Diagnostics",
        "Causal Scrolling Replay",
        "Role Transition Diagnostics",
        "Independent Multi-Timeframe Context",
        "Multi-Asset Comparison",
        "Export Current Snapshot",
    ):
        assert heading in source
    assert "ALLOW_PROVIDER_FETCH = False" in source


def test_notebook_uses_support_surface_and_avoids_forbidden_research_paths() -> None:
    document = json.loads(NOTEBOOK.read_text())
    source = "\n".join("".join(cell.get("source", [])) for cell in document["cells"])
    assert "libs.models.trendlines_v4.research_lab" in source
    assert "solver" not in source
    assert "optuna" not in source.lower()
    assert "yaml" not in source.lower()
    assert "oscillator" not in source.lower()
    assert "ransac" not in source.lower()
    assert "pnl" not in source.lower()


def test_provider_is_not_constructed_during_support_import() -> None:
    source = inspect.getsource(data_support)
    assert (
        "BinanceNativeAdapter()"
        not in source.split("def fetch_native_window_async", 1)[0]
    )

    class UnexpectedProvider:
        def __init__(self):
            raise AssertionError("provider construction was not expected")

    original = data_support.BinanceNativeAdapter
    data_support.BinanceNativeAdapter = UnexpectedProvider  # type: ignore[assignment]
    try:
        assert support.TVLC_VERSION == "5.2.1"
    finally:
        data_support.BinanceNativeAdapter = original


def test_close_time_is_the_canonical_cutoff_and_open_time_is_ignored() -> None:
    frame = _frame(3)
    bars = support.frame_to_trendline_bars(frame)
    expected = datetime.fromtimestamp(frame.loc[0, "close_time"] / 1000, tz=UTC)
    opening = datetime.fromtimestamp(frame.loc[0, "timestamp"] / 1000, tz=UTC)
    assert bars[0].closed_at == expected
    assert bars[0].closed_at != opening
    assert list(support.normalize_native_frame(frame).columns) == [
        "closed_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]


@pytest.mark.asyncio
async def test_native_fetch_requests_close_time_and_preserves_native_timeframe() -> (
    None
):
    frame = _frame(4)
    calls = []

    class FakeAdapter:
        async def get_historical_ohlcv(self, *args, **kwargs):
            calls.append((args, kwargs))
            return frame

    result = await support.fetch_native_window_async(
        "BTCUSDT",
        "4h",
        frame.loc[0, "close_time"],
        frame.loc[3, "close_time"],
        adapter=FakeAdapter(),
    )
    assert len(result) == len(frame)
    assert calls[0][0][:2] == ("BTCUSDT", "4h")
    assert calls[0][1]["include_close_time"] is True
    assert calls[0][1]["limit"] > 0
    source = inspect.getsource(support)
    assert ".resample(" not in source


def test_analysis_is_exactly_the_public_v2_engine() -> None:
    frame = _frame()
    assert support.analyze_frame(frame) == analyze_trendlines_v2(
        support.frame_to_trendline_bars(frame)
    )
    assert support.analyze_frames({"1h": frame})["1h"] == support.analyze_frame(frame)


def test_snapshot_projection_is_public_and_contains_no_private_dp_score() -> None:
    frame = _frame()
    snapshot = support.analyze_frame(frame)
    rows = support.geometry_rows(frame, snapshot, timeframe="1h")
    assert all("score" not in row for row in rows)
    assert all("dp" not in row for row in rows)
    payload = support.snapshot_payload(snapshot)
    assert payload["schema_version"] == "trendlines.geometry.v2"
    assert "score" not in json.dumps(payload).lower()


def test_duplicate_roles_render_once_and_secondary_stays_distinct() -> None:
    frame = _frame()
    snapshot = _manual_snapshot(frame)
    payload = support.build_tvlc_payload(frame, snapshot, timeframe="1h")
    support_lines = [line for line in payload["lines"] if line["side"] == "support"]
    assert [line["role"] for line in support_lines] == [
        "structural + current_valid",
        "secondary",
    ]
    assert (
        sum(line["role"] == "structural + current_valid" for line in support_lines) == 1
    )
    combined = next(
        line for line in support_lines if line["role"] == "structural + current_valid"
    )
    assert combined["line_style"] == "solid"
    assert combined["line_width"] == 3
    html = support.build_tvlc_html(frame, snapshot, timeframe="1h")
    assert "structural + current_valid" in html
    assert html.count("secondary") >= 1


def test_tvlc_payload_stops_at_snapshot_cutoff_and_uses_v5_api() -> None:
    frame = _frame()
    snapshot = support.analyze_frame(frame)
    payload = support.build_tvlc_payload(frame, snapshot, timeframe="1h")
    cutoff = int(snapshot.market_as_of.timestamp())
    assert all(candle["time"] <= cutoff for candle in payload["candles"])
    for line in payload["lines"]:
        assert all(point["time"] <= cutoff for point in line["points"])
    html = support.build_tvlc_html(frame, snapshot, timeframe="1h")
    assert support.TVLC_CDN_URL in html
    assert "lightweight-charts@5.2.1" in html
    assert "chart.addSeries(LightweightCharts.CandlestickSeries" in html
    assert "chart.addSeries(LightweightCharts.LineSeries" in html
    assert "chart.addSeries(LightweightCharts.HistogramSeries" in html


def test_inline_render_helpers_display_html(monkeypatch) -> None:
    frame = _frame()
    snapshot = support.analyze_frame(frame)
    displayed = []
    monkeypatch.setattr(tvlc_support, "HTML", lambda value: ("HTML", value))
    monkeypatch.setattr(tvlc_support, "display", displayed.append)
    support.render_tvlc_chart(frame, snapshot, timeframe="1h")
    assert displayed and displayed[0][0] == "HTML"
    displayed.clear()
    monkeypatch.setattr(replay_support, "HTML", lambda value: ("HTML", value))
    monkeypatch.setattr(replay_support, "display", displayed.append)
    support.render_causal_scrolling_replay(
        frame, timeframe="1h", start_offset=8, step_size=6, steps=2
    )
    assert displayed and displayed[0][0] == "HTML"


def test_causal_replay_is_prefix_only_and_has_inline_controls() -> None:
    frame = _frame(24)
    replay = support.build_causal_replay_payload(
        frame, timeframe="1h", end_positions=(8, 14, 20)
    )
    assert [step["visible_bar_count"] for step in replay] == [8, 14, 20]
    assert [len(step["candles"]) for step in replay] == [8, 14, 20]
    for step, end in zip(replay, (8, 14, 20), strict=True):
        cutoff = int(frame.loc[end - 1, "close_time"] / 1000)
        assert max(candle["time"] for candle in step["candles"]) <= cutoff
    viewer = support.build_causal_scrolling_html(replay)
    for control in ("Prev", "Next", "Play", "Stop", 'type="range"'):
        assert control in viewer
    assert "chart.addSeries(LightweightCharts.CandlestickSeries" in viewer
    assert 'document.createElement("script")' in viewer
    source = inspect.getsource(support)
    for forbidden in ("webbrowser", "localhost", "IFrame", "file://"):
        assert forbidden not in source


def test_future_tail_does_not_change_shared_replay_prefix() -> None:
    base = _frame(24)
    tail = _frame(4)
    tail["timestamp"] += 24 * 3600000
    tail["close_time"] += 24 * 3600000
    extended = pd.concat([base, tail], ignore_index=True)
    base_step = support.build_causal_replay_payload(base, end_positions=(12,))[0]
    extended_step = support.build_causal_replay_payload(extended, end_positions=(12,))[
        0
    ]
    assert base_step == extended_step


def test_role_transition_and_asset_comparison_are_descriptive() -> None:
    frame = _frame()
    transitions = support.role_transition_rows(frame, end_positions=(12, 18, 24))
    assert all("geometry_changed" in row for row in transitions)
    compared = support.compare_asset_frames({"BTCUSDT": frame}, timeframe="1h")
    assert compared
    assert all("asset" in row for row in compared)


def test_notebook_source_does_not_contain_external_viewer_or_network_test_paths() -> (
    None
):
    document = json.loads(NOTEBOOK.read_text())
    source = (
        inspect.getsource(support)
        + "\n"
        + "\n".join("".join(cell.get("source", [])) for cell in document["cells"])
    )
    for forbidden in ("webbrowser.open", "localhost", "IFrame", "file://"):
        assert forbidden not in source


def test_notebook_code_cells_parse_as_python() -> None:
    document = json.loads(NOTEBOOK.read_text())
    for cell in document["cells"]:
        if cell["cell_type"] == "code":
            ast.parse("".join(cell["source"]))


def test_research_lab_helpers_have_bounded_responsibilities() -> None:
    package = Path(support.__file__).parent
    data_source = (package / "data.py").read_text()
    diagnostics_source = (package / "diagnostics.py").read_text()
    tvlc_source = (package / "tvlc.py").read_text()
    replay_source = (package / "replay.py").read_text()

    assert "LightweightCharts" not in data_source
    assert "LightweightCharts" not in diagnostics_source
    assert "BinanceNativeAdapter()" not in tvlc_source
    assert "_solve_side" not in "\n".join(
        (package / filename).read_text()
        for filename in ("data.py", "diagnostics.py", "tvlc.py", "replay.py")
    )
    assert "build_causal_replay_payload" in replay_source
