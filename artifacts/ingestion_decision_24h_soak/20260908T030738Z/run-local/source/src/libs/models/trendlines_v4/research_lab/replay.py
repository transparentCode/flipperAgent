"""Causal prefix replay and inline notebook controls."""

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
from IPython.display import HTML, display

from .data import analyze_frame, normalize_native_frame
from .tvlc import TVLC_CDN_URL, TVLC_VERSION, _new_dom_id, build_tvlc_payload


def build_causal_replay_payload(
    frame: pd.DataFrame,
    *,
    timeframe: str = "",
    end_positions: Sequence[int] | None = None,
    start_offset: int = 120,
    step_size: int = 6,
    steps: int = 30,
) -> tuple[dict[str, Any], ...]:
    """Analyze only prefixes and return bounded JSON-safe viewer steps."""

    normalized = normalize_native_frame(frame)
    total = len(normalized)
    if total == 0:
        return ()
    if end_positions is None:
        if start_offset < 1 or step_size < 1 or steps < 1:
            raise ValueError("replay offsets, step size, and steps must be positive")
        first = min(start_offset, total)
        positions = tuple(
            dict.fromkeys(
                min(first + index * step_size, total) for index in range(steps)
            )
        )
    else:
        positions = tuple(end_positions)
        if any(position < 1 or position > total for position in positions):
            raise ValueError("replay end positions must be within the frame")
    replay: list[dict[str, Any]] = []
    for ordinal, end_position in enumerate(positions):
        prefix = normalized.iloc[:end_position].copy()
        snapshot = analyze_frame(prefix)
        payload = build_tvlc_payload(prefix, snapshot, timeframe=timeframe)
        payload["step"] = ordinal
        payload["visible_bar_count"] = end_position
        replay.append(payload)
    return tuple(replay)


def build_causal_scrolling_html(
    replay_steps: Sequence[Mapping[str, Any]], *, title: str = "Causal replay"
) -> str:
    if not replay_steps:
        raise ValueError("replay_steps must not be empty")
    steps_json = json.dumps(list(replay_steps), separators=(",", ":"), allow_nan=False)
    root_id = _new_dom_id("trendlines-v4-replay")
    chart_id = f"{root_id}-plot"
    heading = html.escape(title)
    return f"""
<div id="{root_id}" class="trendlines-v4-inline-replay">
  <div class="trendlines-v4-replay-heading">{heading}</div>
  <div class="trendlines-v4-replay-controls">
    <button type="button" data-action="prev">Prev</button>
    <button type="button" data-action="next">Next</button>
    <button type="button" data-action="play">Play</button>
    <button type="button" data-action="stop">Stop</button>
    <input data-role="slider" type="range" min="0" max="{len(replay_steps) - 1}" value="0" step="1" />
    <span data-role="label"></span>
  </div>
  <div id="{chart_id}" class="trendlines-v4-replay-plot"></div>
</div>
<style>
  #{root_id} {{ border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px; }}
  #{root_id} .trendlines-v4-replay-controls {{ display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin: 6px 0; }}
  #{root_id} .trendlines-v4-replay-plot {{ height: 420px; }}
  #{root_id} .trendlines-v4-replay-error {{ color: #b91c1c; padding: 12px; }}
</style>
<script>
(() => {{
  const root = document.getElementById({json.dumps(root_id)});
  const plot = document.getElementById({json.dumps(chart_id)});
  const steps = {steps_json};
  const showError = (message) => {{
    if (root) root.insertAdjacentHTML("beforeend", `<div class="trendlines-v4-replay-error">${{message}}</div>`);
  }};
  const initialize = () => {{
    if (!root || !plot || !window.LightweightCharts) {{
      showError("Lightweight Charts could not be loaded in this cell.");
      return;
    }}
    const chart = LightweightCharts.createChart(plot, {{ height: 420 }});
    const candles = chart.addSeries(LightweightCharts.CandlestickSeries, {{
      upColor: "#16a34a", downColor: "#dc2626", borderVisible: false,
      wickUpColor: "#16a34a", wickDownColor: "#dc2626"
    }});
    const volume = chart.addSeries(LightweightCharts.HistogramSeries, {{
      priceFormat: {{ type: "volume" }}, priceScaleId: "",
    }});
    volume.priceScale().applyOptions({{ scaleMargins: {{ top: 0.82, bottom: 0 }} }});
    const lineSeries = [];
    const slider = root.querySelector('[data-role="slider"]');
    const label = root.querySelector('[data-role="label"]');
    let current = 0;
    let timer = null;
    const stop = () => {{ if (timer !== null) {{ clearInterval(timer); timer = null; }} }};
    const draw = (index) => {{
      current = Math.max(0, Math.min(index, steps.length - 1));
      const step = steps[current];
      candles.setData(step.candles);
      volume.setData(step.volume);
      while (lineSeries.length > step.lines.length) chart.removeSeries(lineSeries.pop());
      step.lines.forEach((line, lineIndex) => {{
        const lineStyle = line.line_style === "dashed"
          ? LightweightCharts.LineStyle.Dashed
          : (line.line_style === "dotted" ? LightweightCharts.LineStyle.Dotted : LightweightCharts.LineStyle.Solid);
        if (!lineSeries[lineIndex]) lineSeries[lineIndex] = chart.addSeries(LightweightCharts.LineSeries, {{
          color: line.color, lineWidth: line.line_width, lineStyle,
          lastValueVisible: false, priceLineVisible: false,
        }});
        lineSeries[lineIndex].applyOptions({{ color: line.color, lineWidth: line.line_width, lineStyle }});
        lineSeries[lineIndex].setData(line.points);
      }});
      slider.value = String(current);
      label.textContent = `${{step.market_as_of}} · ${{step.visible_bar_count}} bars`;
      chart.timeScale().fitContent();
    }};
    root.querySelector('[data-action="prev"]').addEventListener("click", () => draw(current - 1));
    root.querySelector('[data-action="next"]').addEventListener("click", () => draw(current + 1));
    root.querySelector('[data-action="stop"]').addEventListener("click", stop);
    root.querySelector('[data-action="play"]').addEventListener("click", () => {{
      stop(); timer = setInterval(() => {{ if (current >= steps.length - 1) stop(); else draw(current + 1); }}, 700);
    }});
    slider.addEventListener("input", (event) => draw(Number(event.target.value)));
    draw(0);
  }};
  const load = () => initialize();
  if (window.LightweightCharts) load();
  else {{
    const script = document.createElement("script");
    script.src = {json.dumps(TVLC_CDN_URL)};
    script.onload = load;
    script.onerror = () => showError("Pinned Lightweight Charts {TVLC_VERSION} failed to load.");
    root.appendChild(script);
  }}
}})();
</script>
"""


def render_causal_scrolling_replay(
    frame: pd.DataFrame,
    *,
    timeframe: str = "",
    start_offset: int = 120,
    step_size: int = 6,
    steps: int = 30,
    title: str = "Trendlines V4 causal replay",
) -> str:
    replay = build_causal_replay_payload(
        frame,
        timeframe=timeframe,
        start_offset=start_offset,
        step_size=step_size,
        steps=steps,
    )
    html_output = build_causal_scrolling_html(replay, title=title)
    display(HTML(html_output))
    return html_output


render_causal_replay_viewer = render_causal_scrolling_replay


__all__ = [
    "build_causal_replay_payload",
    "build_causal_scrolling_html",
    "render_causal_replay_viewer",
    "render_causal_scrolling_replay",
]
