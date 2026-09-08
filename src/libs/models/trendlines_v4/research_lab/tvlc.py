"""Inline TradingView Lightweight Charts presentation helpers."""

from __future__ import annotations

import html
import json
import uuid
from typing import Any

import pandas as pd
from IPython.display import HTML, display

from libs.models.trendlines_v4.contracts import TrendlineSnapshotV2
from libs.models.trendlines_v4.core_v2 import TrendlineBar
from libs.models.trendlines_v4.engine.types import TrendlineGeometry

from .data import _timestamp_text, normalize_native_frame

TVLC_VERSION = "5.2.1"
TVLC_CDN_URL = (
    "https://unpkg.com/lightweight-charts@5.2.1/"
    "dist/lightweight-charts.standalone.production.js"
)

_ROLE_STYLES: dict[str, tuple[str, int]] = {
    "structural": ("solid", 3),
    "current_valid": ("dashed", 2),
    "secondary": ("dotted", 1),
}


def _bar_index(bars: tuple[TrendlineBar, ...]) -> dict[Any, int]:
    return {bar.closed_at: index for index, bar in enumerate(bars)}


def _validate_view_bars(view_bars: int | None) -> None:
    if view_bars is None:
        return
    if isinstance(view_bars, bool) or not isinstance(view_bars, int):
        raise TypeError("view_bars must be a positive int or None")
    if view_bars < 1:
        raise ValueError("view_bars must be positive")


def _display_frame(
    frame: pd.DataFrame,
    snapshot: TrendlineSnapshotV2,
    view_bars: int | None,
) -> tuple[
    tuple[TrendlineBar, ...],
    pd.DataFrame,
    tuple[TrendlineBar, ...],
]:
    """Return visible bars plus the complete cutoff history for line ordinals."""

    _validate_view_bars(view_bars)
    normalized = normalize_native_frame(frame)
    cutoff = pd.Timestamp(snapshot.market_as_of)
    cutoff_frame = normalized.loc[normalized["closed_at"] <= cutoff].reset_index(
        drop=True
    )
    if cutoff_frame.empty:
        raise ValueError("frame has no candle at or before snapshot cutoff")
    if cutoff_frame.iloc[-1]["closed_at"] != cutoff:
        raise ValueError("frame and snapshot do not share the same cutoff")

    visible_frame = (
        cutoff_frame if view_bars is None else cutoff_frame.tail(view_bars)
    ).reset_index(drop=True)
    visible_bars = tuple(
        TrendlineBar(
            closed_at=row.closed_at.to_pydatetime(),
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
        )
        for row in visible_frame.itertuples(index=False)
    )
    cutoff_bars = tuple(
        TrendlineBar(
            closed_at=row.closed_at.to_pydatetime(),
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
        )
        for row in cutoff_frame.itertuples(index=False)
    )
    if not visible_bars or visible_bars[-1].closed_at != snapshot.market_as_of:
        raise ValueError("visible frame must end at snapshot cutoff")
    return visible_bars, visible_frame, cutoff_bars


def _line_points(
    bars: tuple[TrendlineBar, ...],
    line: TrendlineGeometry,
    *,
    reference_bars: tuple[TrendlineBar, ...],
    market_as_of: Any,
) -> list[dict[str, Any]]:
    positions = _bar_index(reference_bars)
    try:
        start_index = positions[line.start_anchor_at]
        end_index = positions[line.end_anchor_at]
    except KeyError as exc:
        raise ValueError("line anchors are not in the snapshot history") from exc
    if end_index <= start_index:
        raise ValueError("line anchors must be ordered")
    points = []
    for bar in bars:
        try:
            index = positions[bar.closed_at]
        except KeyError as exc:
            raise ValueError("visible bar is not in the cutoff history") from exc
        if index < start_index:
            continue
        if bar.closed_at == market_as_of:
            value = line.projected_price_at_market_as_of
        elif index == end_index:
            value = line.end_anchor_price
        else:
            value = line.start_anchor_price + line.slope_per_bar * (index - start_index)
        points.append({"time": int(bar.closed_at.timestamp()), "value": value})
    if not points:
        raise ValueError("visible frame does not intersect the line")
    return points


def _display_line_entries(
    snapshot: TrendlineSnapshotV2,
) -> tuple[tuple[str, str, TrendlineGeometry], ...]:
    entries: list[tuple[str, str, TrendlineGeometry]] = []
    for side_name in ("support", "resistance"):
        side = getattr(snapshot, side_name)
        if side.same_geometry and side.structural is not None:
            entries.append((side_name, "structural + current_valid", side.structural))
        else:
            if side.structural is not None:
                entries.append((side_name, "structural", side.structural))
            if side.current_valid is not None:
                entries.append((side_name, "current_valid", side.current_valid))
        if side.secondary is not None and side.secondary not in {
            line for _, _, line in entries
        }:
            entries.append((side_name, "secondary", side.secondary))
    return tuple(entries)


def build_tvlc_payload(
    frame: pd.DataFrame,
    snapshot: TrendlineSnapshotV2,
    *,
    timeframe: str = "",
    view_bars: int | None = None,
) -> dict[str, Any]:
    """Build JSON-safe candle/line data ending exactly at snapshot cutoff."""

    bars, normalized, cutoff_bars = _display_frame(frame, snapshot, view_bars)
    candles = [
        {
            "time": int(bar.closed_at.timestamp()),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
        }
        for bar in bars
    ]
    volume = []
    for bar, raw_volume in zip(bars, normalized["volume"], strict=True):
        if pd.notna(raw_volume):
            volume.append(
                {
                    "time": int(bar.closed_at.timestamp()),
                    "value": float(raw_volume),
                    "color": "#16a34a" if bar.close >= bar.open else "#dc2626",
                }
            )
    lines = []
    for side, role, line in _display_line_entries(snapshot):
        style_role = (
            "structural"
            if role in {"structural", "structural + current_valid"}
            else "secondary"
            if role == "secondary"
            else "current_valid"
        )
        style_name, width = _ROLE_STYLES[style_role]
        lines.append(
            {
                "side": side,
                "role": role,
                "color": "#16a34a" if side == "support" else "#dc2626",
                "line_style": style_name,
                "line_width": width,
                "points": _line_points(
                    bars,
                    line,
                    reference_bars=cutoff_bars,
                    market_as_of=snapshot.market_as_of,
                ),
            }
        )
    return {
        "timeframe": timeframe,
        "market_as_of": _timestamp_text(snapshot.market_as_of),
        "history_bar_count": snapshot.history_bar_count,
        "visible_bar_count": len(bars),
        "visible_start_at": _timestamp_text(bars[0].closed_at),
        "candles": candles,
        "volume": volume,
        "lines": lines,
    }


def _new_dom_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def build_tvlc_html(
    frame: pd.DataFrame,
    snapshot: TrendlineSnapshotV2,
    *,
    timeframe: str = "",
    title: str | None = None,
    element_id: str | None = None,
    view_bars: int | None = None,
) -> str:
    payload = json.dumps(
        build_tvlc_payload(frame, snapshot, timeframe=timeframe, view_bars=view_bars),
        separators=(",", ":"),
        allow_nan=False,
    )
    root_id = element_id or _new_dom_id("trendlines-v4-chart")
    chart_id = f"{root_id}-plot"
    heading = html.escape(title or f"Trendlines V4 · {timeframe}")
    return f"""
<div id="{root_id}" class="trendlines-v4-inline-chart">
  <div class="trendlines-v4-chart-heading">{heading}</div>
  <div id="{chart_id}" class="trendlines-v4-chart-plot"></div>
</div>
<style>
  #{root_id} {{ border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px; }}
  #{root_id} .trendlines-v4-chart-plot {{ height: 420px; }}
  #{root_id} .trendlines-v4-chart-heading {{ font: 600 14px sans-serif; margin: 4px 0 8px; }}
  #{root_id} .trendlines-v4-chart-error {{ color: #b91c1c; font: 13px sans-serif; padding: 12px; }}
</style>
<script>
(() => {{
  const root = document.getElementById({json.dumps(root_id)});
  const plot = document.getElementById({json.dumps(chart_id)});
  const payload = {payload};
  const showError = (message) => {{
    if (root) root.insertAdjacentHTML("beforeend", `<div class="trendlines-v4-chart-error">${{message}}</div>`);
  }};
  const draw = () => {{
    if (!root || !plot || !window.LightweightCharts) {{
      showError("Lightweight Charts could not be loaded in this cell.");
      return;
    }}
    const chart = LightweightCharts.createChart(plot, {{
      height: 420,
      layout: {{ background: {{ color: "#ffffff" }}, textColor: "#334155" }},
      grid: {{ vertLines: {{ color: "#e2e8f0" }}, horzLines: {{ color: "#e2e8f0" }} }},
    }});
    const candles = chart.addSeries(LightweightCharts.CandlestickSeries, {{
      upColor: "#16a34a", downColor: "#dc2626", borderVisible: false,
      wickUpColor: "#16a34a", wickDownColor: "#dc2626"
    }});
    candles.setData(payload.candles);
    const volume = chart.addSeries(LightweightCharts.HistogramSeries, {{
      priceFormat: {{ type: "volume" }}, priceScaleId: "",
    }});
    volume.priceScale().applyOptions({{ scaleMargins: {{ top: 0.82, bottom: 0 }} }});
    volume.setData(payload.volume);
    for (const line of payload.lines) {{
      const lineStyle = line.line_style === "dashed"
        ? LightweightCharts.LineStyle.Dashed
        : (line.line_style === "dotted" ? LightweightCharts.LineStyle.Dotted : LightweightCharts.LineStyle.Solid);
      const series = chart.addSeries(LightweightCharts.LineSeries, {{
        color: line.color, lineWidth: line.line_width, lineStyle,
        lastValueVisible: false, priceLineVisible: false,
      }});
      series.setData(line.points);
    }}
    chart.timeScale().fitContent();
  }};
  const load = () => draw();
  if (window.LightweightCharts) {{
    load();
  }} else {{
    const script = document.createElement("script");
    script.src = {json.dumps(TVLC_CDN_URL)};
    script.onload = load;
    script.onerror = () => showError("Pinned Lightweight Charts {TVLC_VERSION} failed to load.");
    root.appendChild(script);
  }}
}})();
</script>
"""


def render_tvlc_chart(
    frame: pd.DataFrame,
    snapshot: TrendlineSnapshotV2,
    *,
    timeframe: str = "",
    title: str | None = None,
    view_bars: int | None = None,
) -> str:
    html_output = build_tvlc_html(
        frame,
        snapshot,
        timeframe=timeframe,
        title=title,
        view_bars=view_bars,
    )
    display(HTML(html_output))
    return html_output


__all__ = [
    "TVLC_CDN_URL",
    "TVLC_VERSION",
    "build_tvlc_html",
    "build_tvlc_payload",
    "render_tvlc_chart",
]
