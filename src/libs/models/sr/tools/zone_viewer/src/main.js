import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
} from '../node_modules/lightweight-charts/dist/lightweight-charts.standalone.production.mjs';
import { ZonePrimitive, zoneDetail } from './zone_primitive.js';

const payload = await fetch('/bundle/chart_payload.json').then((response) => {
  if (!response.ok) throw new Error(`chart payload request failed: ${response.status}`);
  return response.json();
});

const viewer = payload.viewer;
const container = document.querySelector('#chart');
const detail = document.querySelector('#hover-detail');
const summary = document.querySelector('#trial-summary');
const terminalToggle = document.querySelector('#show-terminal');
const eventsToggle = document.querySelector('#show-events');

summary.textContent = `${payload.trial_name} · ${payload.candles.length} source bars · bundle ${payload.bundle_id}`;
terminalToggle.checked = viewer.show_terminal_by_default;
eventsToggle.checked = viewer.show_events_by_default;

const chart = createChart(container, {
  layout: {
    background: { color: viewer.background_color },
    textColor: viewer.text_color,
    attributionLogo: viewer.attribution_logo,
  },
  grid: {
    vertLines: { color: viewer.grid_color },
    horzLines: { color: viewer.grid_color },
  },
  rightPriceScale: { borderColor: viewer.grid_color },
  timeScale: { borderColor: viewer.grid_color, timeVisible: true },
});
const series = chart.addSeries(CandlestickSeries, {
  upColor: viewer.support_border_color,
  downColor: viewer.resistance_border_color,
  borderVisible: false,
  wickUpColor: viewer.support_border_color,
  wickDownColor: viewer.resistance_border_color,
});
series.setData(payload.candles.map((candle) => ({
  time: candle.time,
  open: candle.open,
  high: candle.high,
  low: candle.low,
  close: candle.close,
})));

const primitive = new ZonePrimitive(payload);
series.attachPrimitive(primitive);

const markers = payload.events.map((event) => ({
  time: event.time,
  position: event.event_type === 'BREACH_STARTED' || event.event_type === 'BREAK_CONFIRMED'
    ? 'aboveBar'
    : 'belowBar',
  color: event.event_type === 'FALSE_BREAKOUT' ? viewer.pending_border_color : viewer.text_color,
  shape: event.event_type === 'BREAK_CONFIRMED' ? 'arrowUp' : 'circle',
  text: event.event_type,
}));
const markerSeries = createSeriesMarkers(series, eventsToggle.checked ? markers : []);

function updateVisibility() {
  primitive.payload = {
    ...primitive.payload,
    viewer: { ...primitive.payload.viewer, show_terminal_by_default: terminalToggle.checked },
  };
  primitive.requestUpdate?.();
  markerSeries.setMarkers(eventsToggle.checked ? markers : []);
}

terminalToggle.addEventListener('change', updateVisibility);
eventsToggle.addEventListener('change', updateVisibility);
chart.timeScale().fitContent();

chart.subscribeCrosshairMove((param) => {
  if (!param.point) {
    detail.textContent = '';
    return;
  }
  const hit = primitive.hitTest(param.point.x, param.point.y);
  if (!hit?.detail) {
    detail.textContent = '';
    return;
  }
  const selected = hit.detail;
  detail.innerHTML = `<strong>${selected.zone_id}</strong> · ${selected.side} · ${selected.final_status} · bounds ${selected.lower_bound}–${selected.upper_bound} · visible ${selected.visible_from} → ${selected.visible_until ?? 'viewport'} · touches ${selected.touch_count} · fakeouts ${selected.fakeout_count} · pending ${selected.pending_count}`;
});

const resizeObserver = new ResizeObserver(() => {
  chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
});
resizeObserver.observe(container);
