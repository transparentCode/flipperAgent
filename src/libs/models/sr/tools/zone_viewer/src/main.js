import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
} from '../node_modules/lightweight-charts/dist/lightweight-charts.standalone.production.mjs';
import {
  casebookNoticeText,
  casebookState,
  eventMarkers,
} from './casebook.js';
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
const casebook = payload.casebook ?? null;
const casebookControls = document.querySelector('#casebook-controls');
const casebookNotice = document.querySelector('#casebook-notice');
const caseSelect = document.querySelector('#case-select');
const caseFilters = {
  fold: document.querySelector('#case-fold-filter'),
  side: document.querySelector('#case-side-filter'),
  completion: document.querySelector('#case-completion-filter'),
  lifecycle: document.querySelector('#case-lifecycle-filter'),
  close: document.querySelector('#case-close-filter'),
};

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

let selectedCaseId = null;
let markers = eventMarkers(payload.events, null, viewer);
const markerSeries = createSeriesMarkers(series, eventsToggle.checked ? markers : []);

function uniqueSorted(values) {
  return [...new Set(values)].sort();
}

function setOptions(select, values) {
  for (const value of values) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = value;
    select.append(option);
  }
}

function updateCasebook() {
  if (!casebook) return;
  const previous = caseSelect.value || selectedCaseId;
  const filters = Object.fromEntries(
    Object.entries(caseFilters).map(([key, select]) => [key, select.value]),
  );
  const state = casebookState(casebook, filters, previous, viewer);
  caseSelect.replaceChildren();
  for (const item of state.available) {
    const option = document.createElement('option');
    option.value = item.case_id;
    option.textContent = `${item.case_id.slice(0, 8)} · ${item.fold} · ${item.side} · ${item.first_touch_at.slice(0, 10)}`;
    caseSelect.append(option);
  }
  selectedCaseId = state.selectedCaseId;
  if (selectedCaseId) caseSelect.value = selectedCaseId;
  else caseSelect.value = '';
  primitive.payload = {
    ...payload,
    zones: state.zones,
    events: state.events,
  };
  markers = state.markers;
  markerSeries.setMarkers(eventsToggle.checked ? markers : []);
  if (state.selected) {
    chart.timeScale().setVisibleRange(state.visibleRange);
    detail.textContent = state.metrics.text;
  } else {
    detail.textContent = '';
    chart.timeScale().fitContent();
  }
  primitive.requestUpdate?.();
}

if (casebook) {
  casebookControls.hidden = false;
  casebookNotice.hidden = false;
  casebookNotice.textContent = casebookNoticeText(casebook);
  setOptions(caseFilters.fold, uniqueSorted(casebook.cases.map((item) => item.fold)));
  setOptions(caseFilters.side, uniqueSorted(casebook.cases.map((item) => item.side)));
  setOptions(caseFilters.lifecycle, uniqueSorted(casebook.cases.map((item) => item.horizon_lifecycle_class)));
  setOptions(caseFilters.close, uniqueSorted(casebook.cases.map((item) => item.close_location)));
  for (const select of Object.values(caseFilters)) select.addEventListener('change', updateCasebook);
  caseSelect.addEventListener('change', updateCasebook);
  updateCasebook();
}

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
if (!casebook) chart.timeScale().fitContent();

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
