import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
} from '../node_modules/lightweight-charts/dist/lightweight-charts.standalone.production.mjs';
import {
  casebookDetailText,
  casebookMarkers,
  casebookNoticeText,
  casebookState,
  defaultTerminalVisibility,
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
const caseOverview = document.querySelector('#case-overview');
const caseSelect = document.querySelector('#case-select');
const caseFilters = {
  fold: document.querySelector('#case-fold-filter'),
  side: document.querySelector('#case-side-filter'),
  completion: document.querySelector('#case-completion-filter'),
  lifecycle: document.querySelector('#case-lifecycle-filter'),
  close: document.querySelector('#case-close-filter'),
};

summary.textContent = `${payload.trial_name} · ${payload.candles.length} source bars · bundle ${payload.bundle_id}`;
terminalToggle.checked = defaultTerminalVisibility(casebook, viewer.show_terminal_by_default);
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
let casebookMode = casebook ? 'overview' : null;
let markers = casebook ? [] : eventMarkers(payload.events, null, viewer);
let focusMetricsText = '';

function visibleMarkers() {
  if (casebook) return casebookMarkers({ mode: casebookMode, markers }, eventsToggle.checked);
  return eventsToggle.checked ? markers : [];
}

const markerSeries = createSeriesMarkers(series, visibleMarkers());

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

function restoreCasebookDetail() {
  detail.textContent = focusMetricsText;
}

function updateCasebook() {
  if (!casebook) return;
  const previous = caseSelect.value || selectedCaseId;
  const filters = Object.fromEntries(
    Object.entries(caseFilters).map(([key, select]) => [key, select.value]),
  );
  const state = casebookState(casebook, filters, previous, viewer, casebookMode);
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
    viewer: { ...payload.viewer, show_terminal_by_default: terminalToggle.checked },
    zones: state.zones,
    events: state.events,
  };
  markers = state.markers;
  markerSeries.setMarkers(visibleMarkers());
  focusMetricsText = casebookDetailText(state);
  if (state.selected) {
    chart.timeScale().setVisibleRange(state.visibleRange);
    restoreCasebookDetail();
  } else {
    restoreCasebookDetail();
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
  caseOverview.addEventListener('click', () => {
    casebookMode = 'overview';
    selectedCaseId = null;
    updateCasebook();
  });
  caseSelect.addEventListener('change', () => {
    casebookMode = caseSelect.value ? 'focus' : 'overview';
    updateCasebook();
  });
  updateCasebook();
}

function updateVisibility() {
  primitive.payload = {
    ...primitive.payload,
    viewer: { ...primitive.payload.viewer, show_terminal_by_default: terminalToggle.checked },
  };
  primitive.requestUpdate?.();
  markerSeries.setMarkers(visibleMarkers());
}

terminalToggle.addEventListener('change', updateVisibility);
eventsToggle.addEventListener('change', updateVisibility);
if (!casebook) chart.timeScale().fitContent();

chart.subscribeCrosshairMove((param) => {
  if (!param.point) {
    restoreCasebookDetail();
    return;
  }
  const hit = primitive.hitTest(param.point.x, param.point.y);
  if (!hit?.detail) {
    restoreCasebookDetail();
    return;
  }
  const selected = hit.detail;
  detail.innerHTML = `<strong>${selected.zone_id}</strong> · ${selected.side} · ${selected.final_status} · bounds ${selected.lower_bound}–${selected.upper_bound} · visible ${selected.visible_from} → ${selected.visible_until ?? 'viewport'} · touches ${selected.touch_count} · fakeouts ${selected.fakeout_count} · pending ${selected.pending_count}`;
});

const resizeObserver = new ResizeObserver(() => {
  chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
});
resizeObserver.observe(container);
