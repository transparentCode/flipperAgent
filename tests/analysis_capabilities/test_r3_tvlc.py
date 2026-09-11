from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC

import pytest

from libs.models.trendlines_v4.research_lab.tvlc import (
    build_tvlc_payload as build_base_tvlc_payload,
)
from research.analysis_capabilities.r3_requests import execute_r3_vertical_slice
from research.analysis_capabilities.r3_tvlc import (
    R3ViewerError,
    build_canonical_frame,
    build_tvlc_html,
    build_tvlc_payload,
)
from tests.analysis_capabilities.test_r3_canonical_source import make_source_slice
from tests.analysis_capabilities.test_r3_vertical_slice import _arguments


def _bundle():
    source = make_source_slice()
    return source, execute_r3_vertical_slice(source, **_arguments(source))


def test_canonical_frame_preserves_native_close_times_and_values() -> None:
    source, bundle = _bundle()
    frame = build_canonical_frame(source)

    assert list(frame.columns) == [
        "closed_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    assert len(frame) == len(source.records) == 300
    assert tuple(frame["closed_at"]) == tuple(
        record.bar.bar_close_at for record in source.records
    )
    assert frame.iloc[-1].closed_at.to_pydatetime() == source.market_as_of
    assert bundle.source_slice.source_slice_sha256 == source.source_slice_sha256


def test_r3_payload_preserves_base_tvlc_and_appends_factual_overlays() -> None:
    source, bundle = _bundle()
    frame = build_canonical_frame(source)
    base = build_base_tvlc_payload(
        frame,
        bundle.trendlines.result,
        timeframe="4h",
    )
    payload = build_tvlc_payload(
        frame,
        bundle.trendlines,
        timeframe="4h",
        source_slice=source,
        swing_result=bundle.swing_anchors,
        vwap_result=bundle.vwap,
        traditional_result=bundle.traditional_pivot,
        fibonacci_result=bundle.fibonacci,
    )

    for key in (
        "timeframe",
        "market_as_of",
        "history_bar_count",
        "visible_bar_count",
        "visible_start_at",
        "candles",
        "volume",
    ):
        assert payload[key] == base[key]
    assert payload["source_slice_sha256"] == source.source_slice_sha256
    assert len(payload["analysis_provenance"]) == 5
    assert {
        "capability_id",
        "method_version",
        "parameter_fingerprint",
        "state_fingerprint",
        "source_slice_sha256",
        "market_as_of",
    } == set(payload["analysis_provenance"][0])
    assert len(payload["swing_anchors"]) > 0

    appended = payload["lines"][len(base["lines"]) :]
    assert (
        sum(line["label"] == "final explicit-range HLC3 VWAP" for line in appended) == 1
    )
    assert (
        sum(line["family"] == "ta.traditional_pivot_geometry" for line in appended) == 7
    )
    assert sum(line["family"] == "ta.fibonacci_geometry" for line in appended) == 3
    assert all(
        point["time"] <= int(source.market_as_of.timestamp())
        for line in payload["lines"]
        for point in line["points"]
    )
    assert json.dumps(payload, allow_nan=False).find("score") == -1


@pytest.mark.parametrize("timeframe", ("1h", "", "4H", "4-hour"))
def test_r3_viewer_rejects_timeframe_not_equal_to_authenticated_source(
    timeframe: str,
) -> None:
    source, bundle = _bundle()
    with pytest.raises(R3ViewerError, match="timeframe"):
        build_tvlc_payload(
            source,
            bundle.trendlines,
            timeframe=timeframe,
            source_slice=source,
        )
    with pytest.raises(R3ViewerError, match="timeframe"):
        build_tvlc_html(
            source,
            bundle.trendlines,
            timeframe=timeframe,
            source_slice=source,
        )


def test_r3_viewer_uses_authenticated_timeframe_for_payload_and_default_html_title() -> (
    None
):
    source, bundle = _bundle()
    payload = build_tvlc_payload(source, bundle.trendlines, source_slice=source)
    html = build_tvlc_html(
        source,
        bundle.trendlines,
        source_slice=source,
        element_id="analysis-capabilities-r3-timeframe",
    )

    assert payload["timeframe"] == source.source.series.timeframe == "4h"
    assert "Analysis capabilities R3 · 4h" in html


def test_r3_fixture_payload_and_html_are_byte_deterministic() -> None:
    source, bundle = _bundle()
    frame = build_canonical_frame(source)

    def build_values():
        payload = build_tvlc_payload(
            frame,
            bundle.trendlines,
            source_slice=source,
            swing_result=bundle.swing_anchors,
            vwap_result=bundle.vwap,
            traditional_result=bundle.traditional_pivot,
            fibonacci_result=bundle.fibonacci,
        )
        html = build_tvlc_html(
            frame,
            bundle.trendlines,
            source_slice=source,
            swing_result=bundle.swing_anchors,
            vwap_result=bundle.vwap,
            traditional_result=bundle.traditional_pivot,
            fibonacci_result=bundle.fibonacci,
            element_id="analysis-capabilities-r3-fixture",
        )
        return payload, html

    first_payload, first_html = build_values()
    second_payload, second_html = build_values()
    assert first_payload == second_payload
    assert first_html == second_html

    payload_bytes = json.dumps(
        first_payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    assert hashlib.sha256(payload_bytes).hexdigest()
    assert hashlib.sha256(first_html.encode("utf-8")).hexdigest()


def test_fibonacci_lines_begin_at_the_later_anchor_availability() -> None:
    source, bundle = _bundle()
    payload = build_tvlc_payload(
        source,
        bundle.trendlines,
        source_slice=source,
        fibonacci_result=bundle.fibonacci,
    )
    fibonacci = [
        line
        for line in payload["lines"]
        if line.get("family") == "ta.fibonacci_geometry"
    ]
    snapshot = bundle.fibonacci.result
    starts_at = max(
        snapshot.start_anchor.available_at,
        snapshot.end_anchor.available_at,
    )
    expected_time = int(starts_at.astimezone(UTC).timestamp())
    assert fibonacci
    assert all(line["points"][0]["time"] == expected_time for line in fibonacci)


def test_viewer_requires_the_hashed_canonical_frame() -> None:
    source, bundle = _bundle()
    frame = build_canonical_frame(source)
    tampered = frame.copy()
    tampered.loc[0, "close"] += 1.0
    with pytest.raises(ValueError, match="hashed canonical"):
        build_tvlc_payload(
            tampered,
            bundle.trendlines,
            source_slice=source,
        )


def test_html_uses_one_pinned_v5_series_api_and_unique_inline_ids() -> None:
    source, bundle = _bundle()
    first = build_tvlc_html(
        source,
        bundle.trendlines,
        source_slice=source,
        vwap_result=bundle.vwap,
    )
    second = build_tvlc_html(
        source,
        bundle.trendlines,
        source_slice=source,
        vwap_result=bundle.vwap,
    )

    assert (
        "lightweight-charts@5.2.1/dist/lightweight-charts.standalone.production.js"
        in first
    )
    assert first.count("lightweight-charts@5.2.1") == 1
    assert "chart.addSeries(LightweightCharts.CandlestickSeries" in first
    assert "chart.addSeries(LightweightCharts.HistogramSeries" in first
    assert "chart.addSeries(LightweightCharts.LineSeries" in first
    assert "window.open" not in first
    assert "localhost" not in first
    assert "IFrame" not in first
    assert "file://" not in first
    first_root = re.search(
        r'<div id="([^"]+)" class="trendlines-v4-inline-chart">', first
    )
    second_root = re.search(
        r'<div id="([^"]+)" class="trendlines-v4-inline-chart">', second
    )
    assert first_root and second_root
    assert first_root.group(1) != second_root.group(1)
