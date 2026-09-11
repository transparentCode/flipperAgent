import {
  CandlestickSeries,
  HistogramSeries,
  createChart,
  createSeriesMarkers,
} from '/vendor/lightweight-charts.mjs';
import {
  aggregateCandidateMarkers,
  applyInspectionResult,
  bandPriceRange,
  bandHitExternalId,
  bandHitMemberIds,
  candleRows,
  chartTime,
  createRequestGate,
  filterKernelRows,
  historyLineageCounts,
  latestDisplayedCutoff,
  labelRectanglesForDisplay,
  lineageLabelCandidates,
  overlappingBandMemberIds,
  pixelBandsFromProjected,
  pixelHistoryBands,
  projectBands,
  selectLineageLabels,
  transitionMarkers,
  validateSelectedPayload,
  visiblePriceRegions,
  volumeRows,
} from './payload_utils.js';

const $ = (selector) => document.querySelector(selector);

function text(value) {
  return value === null || value === undefined || value === '' ? '—' : String(value);
}

function compactNumber(value, digits = 4) {
  if (value === null || value === undefined || value === '') return '—';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(numeric);
}

function formatUtc(value, withTime = true) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, {
    timeZone: 'UTC',
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    ...(withTime ? { hour: '2-digit', minute: '2-digit', hour12: false } : {}),
  }).format(date) + (withTime ? ' UTC' : '');
}

function candleCutoffForTime(pane, seconds) {
  return (pane.inspection.available_cutoffs || []).find((value) => chartTime(value, 'available_cutoff') === seconds) || null;
}

function createElement(tag, className, value = null) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (value !== null) element.textContent = value;
  return element;
}

class ZoneBandsPrimitive {
  constructor(onError, onGeometryChange) {
    this.onError = onError;
    this.onGeometryChange = onGeometryChange;
    this.chart = null;
    this.series = null;
    this.requestUpdate = null;
    this.state = {
      zones: [],
      intervals: [],
      candles: [],
      cutoff: null,
      visible: true,
      history: null,
      enabledKernelIds: new Set(),
      configuredKernelIds: new Set(),
      selectedZoneId: null,
    };
    this.projectedBands = [];
    this.candleTimes = [];
    this.projectionError = null;
    this.lastError = null;
    this.view = {
      zOrder: () => 'bottom',
      renderer: () => ({
        draw: () => {},
        drawBackground: (target) => this.draw(target),
      }),
    };
  }

  attached({ chart, series, requestUpdate }) {
    this.chart = chart;
    this.series = series;
    this.requestUpdate = requestUpdate;
  }

  detached() {
    this.chart = null;
    this.series = null;
    this.requestUpdate = null;
  }

  update(state) {
    this.state = state;
    this.candleTimes = Array.isArray(state.candles) ? state.candles.map((candle) => candle?.time) : [];
    this.projectionError = null;
    try {
      const displayZones = filterKernelRows(
        state.zones,
        state.enabledKernelIds,
        state.configuredKernelIds,
      );
      this.projectedBands = state.visible
        ? projectBands(displayZones, state.intervals, state.candles, state.cutoff)
        : [];
    } catch (error) {
      this.projectedBands = [];
      this.projectionError = error?.message || 'invalid zone geometry';
    }
    this.lastError = null;
    this.requestUpdate?.();
  }

  updateAllViews() {
    this.requestUpdate?.();
  }

  paneViews() {
    return [this.view];
  }

  activeRectangles() {
    if (!this.state.visible || !this.chart || !this.series) return [];
    if (this.projectionError) {
      if (this.lastError !== this.projectionError) {
        this.lastError = this.projectionError;
        this.onError?.('Zone bands unavailable');
      }
      return [];
    }
    try {
      return pixelBandsFromProjected(
        this.projectedBands,
        this.state.candles,
        this.chart.timeScale(),
        this.series,
      );
    } catch (error) {
      if (this.lastError !== error?.message) {
        this.lastError = error?.message || 'invalid zone geometry';
        this.onError?.('Zone bands unavailable');
      }
      return [];
    }
  }

  historyRectangles() {
    if (!this.state.visible || !this.chart || !this.series || !this.state.history) return [];
    try {
      const activeIds = new Set(this.projectedBands.map((zone) => zone?.zone_id));
      return pixelHistoryBands(
        this.state.history,
        this.state.candles,
        this.chart.timeScale(),
        this.series,
        {
          enabledKernelIds: this.state.enabledKernelIds,
          configuredKernelIds: this.state.configuredKernelIds,
        },
      ).filter((rectangle) => !(
        rectangle.historical === false
        && activeIds.has(rectangle.zone_id)
        && (!Array.isArray(rectangle.intervals) || rectangle.intervals.length <= 1)
      ));
    } catch {
      return [];
    }
  }

  rectangles() {
    const history = this.historyRectangles();
    return [
      ...history.filter((rectangle) => rectangle.historical === true),
      ...history.filter((rectangle) => rectangle.historical !== true),
      ...this.activeRectangles(),
    ];
  }

  autoscaleInfo(startTimePoint, endTimePoint) {
    if (!this.state.visible) return null;
    const priceRange = bandPriceRange(
      this.projectedBands,
      this.candleTimes,
      startTimePoint,
      endTimePoint,
    );
    return priceRange ? { priceRange } : null;
  }

  draw(target) {
    const history = this.historyRectangles();
    const historicalRectangles = history.filter((rectangle) => rectangle.historical === true);
    const currentRectangles = this.activeRectangles();
    const activeRectangles = [
      ...history.filter((rectangle) => rectangle.historical !== true),
      ...currentRectangles,
    ];
    const rectangles = [...historicalRectangles, ...activeRectangles];
    this.onGeometryChange?.();
    if (!rectangles.length) return;
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      context.save();
      context.beginPath();
      context.rect(0, 0, mediaSize.width, mediaSize.height);
      context.clip();
      const drawableRectangle = (rectangle) => (
        rectangle
        && [rectangle.x1, rectangle.x2, rectangle.top, rectangle.bottom].every(Number.isFinite)
        && rectangle.x2 >= rectangle.x1
        && rectangle.bottom >= rectangle.top
      );
      const drawableHistoricalRectangles = historicalRectangles.filter(drawableRectangle);
      const paintHistoricalCoverage = (side, fillStyle) => {
        const support = side === 'SUPPORT';
        const sideRectangles = drawableHistoricalRectangles.filter((rectangle) => (
          (rectangle.side === 'SUPPORT') === support
        ));
        if (!sideRectangles.length) return;
        context.beginPath();
        for (const rectangle of sideRectangles) {
          context.rect(
            rectangle.x1,
            rectangle.top,
            Math.max(1, rectangle.x2 - rectangle.x1),
            Math.max(1, rectangle.bottom - rectangle.top),
          );
        }
        context.fillStyle = fillStyle;
        context.fill();
      };
      paintHistoricalCoverage('SUPPORT', 'rgba(79, 190, 151, .11)');
      paintHistoricalCoverage('RESISTANCE', 'rgba(232, 108, 120, .10)');
      const strokeHistoricalCaps = (side, strokeStyle) => {
        const support = side === 'SUPPORT';
        const sideRectangles = drawableHistoricalRectangles.filter((rectangle) => (
          (rectangle.side === 'SUPPORT') === support
        ));
        if (!sideRectangles.length) return;
        context.beginPath();
        for (const rectangle of sideRectangles) {
          context.moveTo(rectangle.x2, rectangle.top);
          context.lineTo(rectangle.x2, rectangle.bottom);
        }
        context.strokeStyle = strokeStyle;
        context.lineWidth = 1;
        context.setLineDash([]);
        context.stroke();
      };
      strokeHistoricalCaps('SUPPORT', 'rgba(89, 202, 161, .48)');
      strokeHistoricalCaps('RESISTANCE', 'rgba(237, 125, 136, .44)');
      for (const rectangle of activeRectangles) {
        if (!drawableRectangle(rectangle)) continue;
        const width = Math.max(1, rectangle.x2 - rectangle.x1);
        const height = Math.max(1, rectangle.bottom - rectangle.top);
        const support = rectangle.side === 'SUPPORT';
        context.fillStyle = support ? 'rgba(79, 190, 151, .16)' : 'rgba(232, 108, 120, .14)';
        context.fillRect(rectangle.x1, rectangle.top, width, height);
        context.strokeStyle = support ? 'rgba(89, 202, 161, .66)' : 'rgba(237, 125, 136, .62)';
        context.lineWidth = rectangle.lifecycle === 'TOUCHED' ? 1.5 : 1;
        context.setLineDash(
          rectangle.lifecycle === 'BREAK_PENDING' ? [5, 4] : rectangle.lifecycle === 'ACTIVE' ? [2, 4] : [],
        );
        context.strokeRect(rectangle.x1 + .5, rectangle.top + .5, Math.max(0, width - 1), Math.max(0, height - 1));
      }
      const selectedRectangles = rectangles.filter((rectangle) => (
        this.state.selectedZoneId && rectangle.zone_id === this.state.selectedZoneId
      ));
      context.setLineDash([]);
      context.strokeStyle = 'rgba(232, 239, 250, .92)';
      context.lineWidth = 2;
      for (const rectangle of selectedRectangles) {
        if (!drawableRectangle(rectangle)) continue;
        context.strokeRect(rectangle.x1 + 1, rectangle.top + 1, Math.max(0, rectangle.x2 - rectangle.x1 - 2), Math.max(0, rectangle.bottom - rectangle.top - 2));
        if (Array.isArray(rectangle.boundary_xs)) {
          context.beginPath();
          for (const boundaryX of rectangle.boundary_xs) {
            if (boundaryX < rectangle.x1 || boundaryX > rectangle.x2) continue;
            context.moveTo(boundaryX, rectangle.top);
            context.lineTo(boundaryX, Math.min(rectangle.bottom, rectangle.top + 5));
          }
          context.stroke();
        }
      }
      context.font = '10px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
      const currentLabelRectangles = currentRectangles;
      const labelRectangles = labelRectanglesForDisplay(
        currentLabelRectangles,
        history,
        this.state.selectedZoneId,
      );
      const labelCandidates = lineageLabelCandidates(labelRectangles, this.state.selectedZoneId);
      const labels = selectLineageLabels(labelCandidates, {
        width: mediaSize.width,
        height: mediaSize.height,
        measureText: (value) => context.measureText(value).width,
      });
      context.textBaseline = 'top';
      for (const label of labels) {
        context.fillStyle = 'rgba(14, 17, 23, .86)';
        context.fillRect(label.x, label.y, label.width, label.height);
        context.fillStyle = label.candidate.selected ? '#f1f5fb' : '#c7d2e2';
        context.fillText(label.text, label.x + 4, label.y + 9);
      }
      context.restore();
    });
  }

  hitTest(x, y) {
    const memberIds = overlappingBandMemberIds(this.rectangles(), x, y);
    if (!memberIds.length) return null;
    return {
      externalId: bandHitExternalId(memberIds),
      member_ids: memberIds,
      zOrder: 'bottom',
      itemType: 'primitive',
      isBackground: true,
      hitTestPriority: 0,
      cursorStyle: 'pointer',
    };
  }

  memberIdsForHit(externalId) {
    return bandHitMemberIds(externalId);
  }
}

let payload;
let pane;
let chart;
let candleSeries;
let volumeSeries;
let markerPlugin;
let bandPrimitive;
let currentMode = null;
let overlayInspection = null;
let currentInspection = null;
let currentDetail = null;
let selectedZoneId = null;
let bandMembers = [];
let zonesVisible = null;
let candidatesVisible = null;
let inspectionVisible = null;
let volumePaneFraction;
let minVolumePaneHeight;
let chartResizeObserver;
let enabledKernelIds = new Set();
let configuredKernelIds = new Set();
let requestedCutoff = null;
let hoverRequestId = null;
let historyVisible = null;
let historyPayload = null;
let historyCacheKey = null;
let historyError = null;
const inspectionRequests = createRequestGate();
const detailRequests = createRequestGate();
const historyRequests = createRequestGate();

function activeChartRows() {
  return currentMode === 'formation' ? pane.formation.candles : pane.lifecycle.candles;
}

function activeChartCandleRows() {
  return candleRows(activeChartRows(), `${pane.source_timeframe}.${currentMode}.candles`);
}

function latestDisplayedInspectionCutoff() {
  return latestDisplayedCutoff(activeChartRows(), pane.inspection.as_of);
}

function cancelHoverInspection() {
  if (hoverRequestId === null) return;
  inspectionRequests.cancel();
  hoverRequestId = null;
}

function clearDetailSelection() {
  const hadSelection = currentDetail !== null || selectedZoneId !== null;
  currentDetail = null;
  selectedZoneId = null;
  bandMembers = [];
  if (hadSelection) {
    updateMarkers();
    if (pane && bandPrimitive) updateBands();
  }
}

function restoreOverlayInspection() {
  detailRequests.cancel();
  const detailAtOverlay = currentDetail && currentDetail.cutoff === overlayInspection?.cutoff;
  if ((currentDetail && !detailAtOverlay) || (!currentDetail && selectedZoneId !== null)) {
    clearDetailSelection();
  }
  currentInspection = overlayInspection;
  requestedCutoff = currentInspection?.cutoff || null;
  updateAsOfLabel();
  renderInspector();
}

function closeInspector() {
  cancelHoverInspection();
  detailRequests.cancel();
  inspectionVisible = false;
  clearDetailSelection();
  restoreOverlayInspection();
  updateToolbar();
}

function initializeKernelFilters() {
  configuredKernelIds = new Set((pane.formation.kernel_ids || []).filter((kernelId) => typeof kernelId === 'string' && kernelId));
  enabledKernelIds = new Set(configuredKernelIds);
}

function initializeDisplayPolicy() {
  const display = payload.display;
  const required = [
    'initial_mode',
    'show_zones',
    'show_history',
    'show_candidates',
    'show_inspector',
    'volume_pane_fraction',
    'volume_pane_min_height',
  ];
  if (!display || required.some((name) => !(name in display))) {
    throw new Error('viewer display policy is unavailable');
  }
  if (display.initial_mode !== 'formation' && display.initial_mode !== 'lifecycle') {
    throw new Error('viewer display mode is invalid');
  }
  if (!['show_zones', 'show_history', 'show_candidates', 'show_inspector'].every((name) => typeof display[name] === 'boolean')) {
    throw new Error('viewer visibility policy is invalid');
  }
  if (![display.volume_pane_fraction, display.volume_pane_min_height].every((value) => Number.isFinite(Number(value)))) {
    throw new Error('viewer volume display policy is invalid');
  }
  currentMode = display.initial_mode;
  zonesVisible = display.show_zones;
  historyVisible = display.show_history;
  candidatesVisible = display.show_candidates;
  inspectionVisible = display.show_inspector;
  volumePaneFraction = Number(display.volume_pane_fraction);
  minVolumePaneHeight = Number(display.volume_pane_min_height);
}

function visibleKernelRows(rows) {
  return filterKernelRows(rows, enabledKernelIds, configuredKernelIds);
}

function compactIdentifier(value) {
  const identifier = text(value);
  return identifier.length > 18 ? `${identifier.slice(0, 8)}…${identifier.slice(-7)}` : identifier;
}

function copyIdentifierButton(identifier) {
  const button = createElement('button', 'inspector-link', compactIdentifier(identifier));
  button.type = 'button';
  button.title = `Copy full zone ID ${identifier}`;
  button.setAttribute('aria-label', `Copy full zone ID ${identifier}`);
  button.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(identifier);
      button.textContent = 'Copied';
    } catch {
      button.textContent = compactIdentifier(identifier);
    }
  });
  return button;
}

function setHeader() {
  const identity = payload.market_identity;
  $('#market-identity').textContent = identity.asset;
  $('#venue-label').textContent = identity.venue;
  $('#timeframe-label').textContent = pane.source_timeframe;
  const lifecycleTimeframe = pane.lifecycle.timeframe;
  $('#mode-label').textContent = currentMode === 'formation' ? `Formation ${pane.source_timeframe}` : `Lifecycle ${lifecycleTimeframe}`;
  $('#pipeline-label').textContent = currentMode === 'formation'
    ? `source formation → ${lifecycleTimeframe} lifecycle`
    : `${pane.source_timeframe} zones → exact ${lifecycleTimeframe} lifecycle`;
  $('#identity-label').textContent = `${payload.identity_mode} · ${payload.trace_id.slice(0, 12)}…`;
}

function updateAsOfLabel() {
  const inspectionCutoff = currentInspection?.cutoff || requestedCutoff || pane.inspection.as_of;
  const bandsCutoff = overlayInspection?.cutoff;
  $('#as-of-label').textContent = currentInspection?.cutoff && bandsCutoff && currentInspection.cutoff !== bandsCutoff
    ? `UTC inspect ${formatUtc(inspectionCutoff)} · bands ${formatUtc(bandsCutoff)}`
    : `UTC as-of ${formatUtc(inspectionCutoff)}`;
}

function updateToolbar() {
  $('#formation-button').classList.toggle('active', currentMode === 'formation');
  $('#formation-button').setAttribute('aria-pressed', String(currentMode === 'formation'));
  $('#lifecycle-button').classList.toggle('active', currentMode === 'lifecycle');
  $('#lifecycle-button').setAttribute('aria-pressed', String(currentMode === 'lifecycle'));
  $('#zones-button').classList.toggle('active', zonesVisible);
  $('#zones-button').setAttribute('aria-pressed', String(zonesVisible));
  $('#history-button').classList.toggle('active', historyVisible);
  $('#history-button').setAttribute('aria-pressed', String(historyVisible));
  $('#candidates-button').classList.toggle('active', candidatesVisible);
  $('#candidates-button').setAttribute('aria-pressed', String(candidatesVisible));
  $('#inspector-button').classList.toggle('active', inspectionVisible);
  $('#inspector-button').setAttribute('aria-pressed', String(inspectionVisible));
  $('#inspector-button').setAttribute('aria-expanded', String(inspectionVisible));
  $('#inspector').hidden = !inspectionVisible;
  const kernelCount = $('#kernel-count');
  if (kernelCount) kernelCount.textContent = `${[...configuredKernelIds].filter((kernelId) => enabledKernelIds.has(kernelId)).length}/${configuredKernelIds.size}`;
  const kernelButton = $('#kernels-button');
  if (kernelButton) {
    kernelButton.setAttribute('aria-label', `Kernels ${[...configuredKernelIds].filter((kernelId) => enabledKernelIds.has(kernelId)).length} of ${configuredKernelIds.size} enabled`);
  }
  $('#candle-count').textContent = pane ? `${activeChartRows().length} candles` : '';
}

function updateMarkers() {
  if (!markerPlugin) return;
  if (currentMode === 'formation' && candidatesVisible) {
    markerPlugin.setMarkers(aggregateCandidateMarkers(visibleKernelRows(pane.formation.candidates)));
    return;
  }
  if (currentMode === 'lifecycle' && currentDetail?.transitions) {
    const zones = new Map([[selectedZoneId, currentDetail.zone]]);
    markerPlugin.setMarkers(transitionMarkers(currentDetail.transitions, zones));
    return;
  }
  markerPlugin.setMarkers([]);
}

function updateLineageStatus() {
  const status = $('#lineage-status');
  if (!status) return;
  const activeZones = overlayInspection?.active_zones || [];
  const renderedRectangles = zonesVisible ? bandPrimitive?.rectangles?.() || [] : [];
  const activeZoneIds = new Set(activeZones
    .map((zone) => zone?.zone_id)
    .filter((zoneId) => typeof zoneId === 'string' && zoneId));
  const rectangles = renderedRectangles.filter((rectangle) => (
    rectangle?.historical !== true && activeZoneIds.has(rectangle?.zone_id)
  ));
  const shown = zonesVisible ? visibleKernelRows(activeZones).length : 0;
  const visibleWindow = chart?.timeScale?.().width?.() ?? 0;
  const regions = zonesVisible
    ? visiblePriceRegions(rectangles, { left: 0, right: visibleWindow })
    : 0;
  const regionLabel = regions === 0
    ? '0 visible price regions in window'
    : `${regions} visible price regions`;
  let label = `${activeZones.length} active lineages · ${shown} shown · ${regionLabel}`;
  if (historyVisible && historyPayload) {
    const historicalZones = Array.isArray(historyPayload.zones) ? historyPayload.zones : [];
    const historyCounts = historyLineageCounts(
      historicalZones,
      renderedRectangles,
      {
        enabledKernelIds,
        configuredKernelIds,
        visible: zonesVisible,
        visibleWindow: { left: 0, right: visibleWindow },
      },
    );
    label += ` · ${historyCounts.total} historical lineages · ${historyCounts.enabled} enabled · ${historyCounts.inWindow} in window`;
  }
  if (historyError) label += ' · History unavailable';
  status.textContent = label;
  status.title = 'Open the active lineage ledger';
}

function clearHistoryState(message = null) {
  historyRequests.cancel();
  historyPayload = null;
  historyCacheKey = null;
  historyError = message;
  updateBands();
}

function validateHistoryResult(result, sourceTimeframe, cutoff) {
  if (!result || result.schema_version !== 2
      || result.source_timeframe !== sourceTimeframe
      || result.cutoff !== cutoff
      || typeof result.lifecycle_timeframe !== 'string'
      || !Array.isArray(result.zones)
      || !Array.isArray(result.lifecycle_intervals)) {
    throw new Error('lineage history projection is invalid');
  }
  if (typeof result.response_id !== 'string' || !result.response_id) {
    throw new Error('lineage history identity is unavailable');
  }
  return result;
}

async function loadHistoryForOverlay() {
  if (!historyVisible || !overlayInspection) {
    clearHistoryState();
    return;
  }
  const cutoff = overlayInspection.cutoff;
  const key = `${pane.source_timeframe}|${cutoff}`;
  if (historyPayload && historyCacheKey === key) {
    updateLineageStatus();
    return;
  }
  const request = historyRequests.begin();
  historyPayload = null;
  historyCacheKey = null;
  historyError = null;
  updateBands();
  try {
    const query = new URLSearchParams({ source_timeframe: pane.source_timeframe, cutoff });
    const result = await fetchJson(`/bundle/lineage_history.json?${query}`, request.signal);
    if (!historyRequests.isCurrent(request.id)) return;
    historyPayload = validateHistoryResult(result, pane.source_timeframe, cutoff);
    historyCacheKey = key;
    historyError = null;
    updateBands();
  } catch (error) {
    if (error?.name !== 'AbortError' && historyRequests.isCurrent(request.id)) {
      historyPayload = null;
      historyCacheKey = null;
      historyError = 'History unavailable';
      updateBands();
    }
  } finally {
    historyRequests.finish(request.id);
  }
}

function updateBands() {
  const activeZones = overlayInspection?.active_zones || [];
  const intervals = activeZones.map((zone) => ({
    zone_id: zone.zone_id,
    lifecycle: zone.lifecycle,
    entered_at: zone.entered_at || zone.available_at,
    exited_at: zone.exited_at || null,
  }));
  bandPrimitive?.update({
    zones: activeZones,
    intervals,
    candles: activeChartCandleRows(),
    cutoff: overlayInspection?.cutoff || pane.inspection.as_of,
    visible: zonesVisible,
    history: historyPayload,
    enabledKernelIds,
    configuredKernelIds,
    selectedZoneId,
  });
  updateLineageStatus();
}

function setChartMode() {
  const candles = activeChartCandleRows();
  candleSeries.setData(candles);
  volumeSeries.setData(volumeRows(candles));
  chart.timeScale().fitContent();
  currentDetail = null;
  selectedZoneId = null;
  bandMembers = [];
  updateToolbar();
  updateMarkers();
  updateBands();
  renderInspector();
}

function metric(label, value) {
  const item = createElement('div', 'metric');
  item.append(createElement('span', 'metric-label', label), createElement('span', 'metric-value', value));
  return item;
}

function section(title, count = null) {
  const item = createElement('section', 'inspector-section');
  const heading = createElement('div', 'section-heading');
  heading.append(createElement('span', null, title));
  if (count !== null) heading.append(createElement('span', 'section-count', count));
  item.append(heading);
  return item;
}

function renderKernelControls() {
  const kernelIds = [...new Set(pane?.formation?.kernel_ids || [])]
    .filter((kernelId) => typeof kernelId === 'string' && kernelId);
  const enabledCount = kernelIds.filter((kernelId) => enabledKernelIds.has(kernelId)).length;
  const sectionItem = section('Kernel filters', `${enabledCount}/${kernelIds.length} enabled`);
  const fieldset = createElement('fieldset', 'kernel-controls');
  fieldset.id = 'kernel-controls';
  fieldset.append(createElement('legend', 'kernel-legend', 'Enabled kernels'));
  if (!kernelIds.length) {
    fieldset.append(createElement('div', 'empty-state', 'No configured kernels.'));
  }
  for (const kernelId of kernelIds) {
    const label = createElement('label', 'kernel-toggle');
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = enabledKernelIds.has(kernelId);
    input.setAttribute('aria-label', `Filter ${kernelId} kernel evidence`);
    input.addEventListener('change', () => {
      if (input.checked) enabledKernelIds.add(kernelId);
      else enabledKernelIds.delete(kernelId);
      updateToolbar();
      updateMarkers();
      updateBands();
      renderInspector();
    });
    label.append(input, createElement('span', null, kernelId));
    fieldset.append(label);
  }
  const summaryText = !kernelIds.length
    ? 'No configured kernels.'
    : enabledCount === kernelIds.length
      ? 'All configured kernels enabled.'
      : `${enabledCount} of ${kernelIds.length} configured kernels enabled.`;
  const summary = createElement('div', 'kernel-summary', summaryText);
  summary.setAttribute('role', 'status');
  summary.setAttribute('aria-live', 'polite');
  sectionItem.append(fieldset, summary);
  return sectionItem;
}

function bandMemberCard(memberId) {
  const card = createElement('button', 'evidence-card zone-card', memberId);
  card.type = 'button';
  card.title = `Open zone detail ${memberId}`;
  card.setAttribute('aria-label', `Open zone detail ${memberId}`);
  card.addEventListener('click', () => {
    bandMembers = [];
    loadZoneDetail(memberId, overlayInspection?.cutoff);
  });
  return card;
}

function touchCard(episode, index) {
  const card = createElement('div', 'evidence-card');
  const line = createElement('div', 'card-line');
  line.append(
    createElement('span', null, `Episode ${episode.episode_number ?? index + 1}`),
    copyIdentifierButton(episode.zone_id),
  );
  card.append(line, createElement('div', 'card-subline', `Started ${formatUtc(episode.started_at)}`));
  return card;
}

function zoneCard(zone) {
  const card = createElement('button', 'evidence-card zone-card');
  card.type = 'button';
  card.dataset.zoneId = zone.zone_id;
  card.title = `Open zone detail ${zone.zone_id}`;
  card.setAttribute('aria-label', `Open zone detail ${zone.zone_id}`);
  const line = createElement('span', 'card-line');
  line.append(
    createElement('span', 'zone-id', compactIdentifier(zone.zone_id)),
    createElement('span', zone.side === 'SUPPORT' ? 'side-support' : 'side-resistance', zone.side),
    createElement('span', 'state-badge', zone.lifecycle),
  );
  const subline = createElement('span', 'card-subline', `${compactNumber(zone.lower)} — ${compactNumber(zone.upper)} · ${zone.touch_count || 0} touches`);
  card.append(line, subline);
  card.addEventListener('click', () => loadZoneDetail(zone.zone_id, currentInspection?.cutoff));
  return card;
}

function renderDetail(detail, parent) {
  const block = createElement('div', 'detail-block');
  const heading = createElement('div', 'section-heading', 'SELECTED ZONE DETAIL');
  block.append(heading);
  const geometry = detail.zone || {};
  const grid = createElement('div', 'metric-grid');
  grid.append(
    metric('Side', geometry.side),
    metric('Lifecycle', detail.state?.lifecycle || 'not active'),
    metric('Lower', compactNumber(geometry.lower)),
    metric('Upper', compactNumber(geometry.upper)),
    metric('Transitions', detail.transitions?.length || 0),
    metric('Touches', detail.touch_episodes?.length || 0),
  );
  block.append(grid);
  block.append(copyIdentifierButton(geometry.zone_id || 'unknown zone'));
  const pre = createElement('pre', 'detail-pre', JSON.stringify({
    cutoff: detail.cutoff,
    source_evidence_id: geometry.source_evidence_id,
    predecessor_id: detail.navigation?.predecessor_id,
    successor_id: detail.navigation?.successor_id,
    lifecycle_intervals: detail.lifecycle_intervals,
    touch_episodes: detail.touch_episodes,
    transitions: detail.transitions,
  }, null, 2));
  block.append(pre);
  parent.append(block);
}

function renderInspector() {
  const body = $('#inspector-body');
  body.textContent = '';
  body.append(renderKernelControls());
  if (!currentInspection) {
    body.append(createElement('div', 'empty-state', 'Move the crosshair to inspect a closed candle.'));
    return;
  }
  const featuresForDisplay = visibleKernelRows(currentInspection.features);
  const candidatesForDisplay = visibleKernelRows(currentInspection.new_candidates);
  const candle = currentInspection.candle;
  const candleSection = section('Candle', formatUtc(currentInspection.cutoff));
  const metrics = createElement('div', 'metric-grid');
  metrics.append(
    metric('Open', compactNumber(candle?.open)),
    metric('High', compactNumber(candle?.high)),
    metric('Low', compactNumber(candle?.low)),
    metric('Close', compactNumber(candle?.close)),
    metric('Volume', compactNumber(candle?.volume, 2)),
    metric('Features', featuresForDisplay.length),
  );
  candleSection.append(metrics);
  body.append(candleSection);

  const features = section('Kernel evidence', featuresForDisplay.length);
  const featureList = createElement('div', 'evidence-list');
  for (const feature of featuresForDisplay) {
    const item = createElement('div', 'evidence-card');
    const line = createElement('div', 'card-line');
    line.append(createElement('span', null, feature.kernel_id || 'kernel'), createElement('span', 'state-badge', `ATR ${text(feature.atr_period)}`));
    item.append(line, createElement('div', 'card-subline', `close ${compactNumber(feature.close)} · range ${compactNumber(feature.true_range)} · ATR ${compactNumber(feature.atr)}`));
    featureList.append(item);
  }
  if (!featureList.children.length) featureList.append(createElement('div', 'empty-state', 'No kernel row is available at this cutoff.'));
  features.append(featureList);
  body.append(features);

  const candidates = section('New candidates', candidatesForDisplay.length);
  const candidateList = createElement('div', 'evidence-list');
  for (const candidate of candidatesForDisplay) {
    candidateList.append(createElement('div', 'evidence-card', `${candidate.side} · ${candidate.kernel_id} · ${compactNumber(candidate.center)}`));
  }
  candidates.append(candidateList);
  body.append(candidates);

  const zones = section('Active zones', currentInspection.active_zones?.length || 0);
  const zoneList = createElement('div', 'evidence-list');
  zoneList.id = 'active-zone-ledger';
  zoneList.tabIndex = -1;
  for (const zone of currentInspection.active_zones || []) zoneList.append(zoneCard(zone));
  if (!zoneList.children.length) zoneList.append(createElement('div', 'empty-state', 'No zone is active at this cutoff.'));
  zones.append(zoneList);
  body.append(zones);

  if (bandMembers.length) {
    const members = section('Band members', bandMembers.length);
    const memberList = createElement('div', 'evidence-list');
    for (const memberId of bandMembers) memberList.append(bandMemberCard(memberId));
    members.append(memberList);
    body.append(members);
  }

  const touches = section('Active touches', currentInspection.touch_episodes?.length || 0);
  const touchList = createElement('div', 'evidence-list');
  for (const [index, episode] of (currentInspection.touch_episodes || []).entries()) {
    touchList.append(touchCard(episode, index));
  }
  if (!touchList.children.length) touchList.append(createElement('div', 'empty-state', 'No active touch episode at this cutoff.'));
  touches.append(touchList);
  body.append(touches);

  const transitions = section('Exact-time transitions', currentInspection.transitions?.length || 0);
  const transitionList = createElement('div', 'evidence-list');
  for (const transition of currentInspection.transitions || []) {
    transitionList.append(createElement('div', 'evidence-card', `${transition.event} · ${transition.zone_id}`));
  }
  transitions.append(transitionList);
  body.append(transitions);
  if (currentDetail) renderDetail(currentDetail, body);
}

function openLineageLedger() {
  if (!pane) return;
  cancelHoverInspection();
  restoreOverlayInspection();
  inspectionVisible = true;
  updateToolbar();
  renderInspector();
  const ledger = $('#active-zone-ledger');
  ledger?.scrollIntoView?.({ block: 'nearest' });
  ledger?.focus?.({ preventScroll: true });
}

function openKernelControls() {
  if (!pane) return;
  cancelHoverInspection();
  if (!overlayInspection) {
    inspectionVisible = true;
    updateToolbar();
    void loadInspection(latestDisplayedInspectionCutoff(), { open: true }).then(focusKernelControls);
    return;
  }
  restoreOverlayInspection();
  inspectionVisible = true;
  updateToolbar();
  renderInspector();
  focusKernelControls();
}

function focusKernelControls() {
  const controls = $('#kernel-controls');
  controls?.scrollIntoView?.({ block: 'nearest' });
  controls?.querySelector?.('input')?.focus?.({ preventScroll: true });
}

async function fetchJson(path, signal) {
  const response = await fetch(path, { cache: 'no-store', signal });
  if (!response.ok) throw new Error(`request failed: ${response.status}`);
  return response.json();
}

async function loadInspection(cutoff, { open = false, passive = false } = {}) {
  if (passive && !inspectionVisible) return;
  const request = inspectionRequests.begin();
  if (passive) hoverRequestId = request.id;
  else hoverRequestId = null;
  requestedCutoff = cutoff;
  detailRequests.cancel();
  clearDetailSelection();
  updateAsOfLabel();
  if (open) {
    inspectionVisible = true;
    updateToolbar();
  }
  try {
    const query = new URLSearchParams({ source_timeframe: pane.source_timeframe, cutoff });
    const result = await fetchJson(`/bundle/inspection.json?${query}`, request.signal);
    if (!inspectionRequests.isCurrent(request.id)) return;
    const nextState = applyInspectionResult(
      overlayInspection,
      result,
      { passive, inspectorOpen: inspectionVisible },
    );
    overlayInspection = nextState.overlayInspection;
    currentInspection = nextState.currentInspection;
    updateAsOfLabel();
    if (!passive) {
      updateBands();
      if (historyVisible) void loadHistoryForOverlay();
    }
    updateMarkers();
    renderInspector();
  } catch (error) {
    if (error?.name !== 'AbortError' && inspectionRequests.isCurrent(request.id)) {
      updateLineageStatus();
    }
  } finally {
    if (hoverRequestId === request.id) hoverRequestId = null;
    inspectionRequests.finish(request.id);
  }
}

async function loadZoneDetail(zoneId, cutoff) {
  cancelHoverInspection();
  if (!cutoff) return;
  clearDetailSelection();
  selectedZoneId = zoneId;
  const request = detailRequests.begin();
  inspectionVisible = true;
  updateToolbar();
  const body = $('#inspector-body');
  body.textContent = 'Loading selected zone evidence…';
  try {
    const query = new URLSearchParams({ source_timeframe: pane.source_timeframe, zone_id: zoneId, cutoff });
    const result = await fetchJson(`/bundle/zone_detail.json?${query}`, request.signal);
    if (!detailRequests.isCurrent(request.id)) return;
    currentDetail = result;
    updateBands();
    updateMarkers();
    renderInspector();
  } catch (error) {
    if (error?.name !== 'AbortError' && detailRequests.isCurrent(request.id)) body.textContent = 'Selected zone detail is unavailable at this cutoff.';
  } finally {
    detailRequests.finish(request.id);
  }
}

function switchMode(mode) {
  if (!pane || currentMode === mode) return;
  inspectionRequests.cancel();
  hoverRequestId = null;
  currentMode = mode;
  overlayInspection = null;
  currentInspection = null;
  historyRequests.cancel();
  historyPayload = null;
  historyCacheKey = null;
  historyError = null;
  detailRequests.cancel();
  clearDetailSelection();
  setHeader();
  setChartMode();
  loadInspection(latestDisplayedInspectionCutoff());
}

function resizeChartToHost(host) {
  if (!chart) return;
  const width = Math.max(1, host.clientWidth);
  const height = Math.max(1, host.clientHeight);
  const volumePane = chart.panes()[1];
  if (volumePane) volumePane.setHeight(Math.max(minVolumePaneHeight, Math.round(height * volumePaneFraction)));
  chart.resize(width, height, true);
  bandPrimitive?.updateAllViews();
  updateLineageStatus();
}

function makeChart() {
  const host = $('#chart');
  const initialWidth = Math.max(1, host.clientWidth);
  const initialHeight = Math.max(1, host.clientHeight);
  chart = createChart(host, {
    width: initialWidth,
    height: initialHeight,
    autoSize: false,
    layout: {
      background: { color: '#11161e' },
      textColor: '#aeb9ca',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      fontSize: 11,
    },
    grid: {
      vertLines: { color: 'rgba(148, 163, 184, .08)' },
      horzLines: { color: 'rgba(148, 163, 184, .08)' },
    },
    crosshair: {
      vertLine: { color: 'rgba(173, 189, 214, .5)', width: 1, style: 3, labelBackgroundColor: '#4e6687' },
      horzLine: { color: 'rgba(173, 189, 214, .5)', width: 1, style: 3, labelBackgroundColor: '#4e6687' },
    },
    rightPriceScale: { borderColor: 'rgba(148, 163, 184, .18)', scaleMargins: { top: .08, bottom: .16 } },
    timeScale: { borderColor: 'rgba(148, 163, 184, .18)', timeVisible: true, secondsVisible: false, rightOffset: 8, barSpacing: 8, minBarSpacing: 2 },
    handleScale: { axisPressedMouseMove: { time: true, price: true } },
    handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
  });
  candleSeries = chart.addSeries(CandlestickSeries, {
    upColor: '#3eb291', downColor: '#e46e7a', borderUpColor: '#3eb291', borderDownColor: '#e46e7a', wickUpColor: '#54c5a1', wickDownColor: '#ee7d88',
    priceLineVisible: true, lastValueVisible: true,
  });
  volumeSeries = chart.addSeries(HistogramSeries, {
    priceFormat: { type: 'volume' }, priceScaleId: 'volume', color: 'rgba(82, 145, 158, .34)', priceLineVisible: false, lastValueVisible: false,
  }, 1);
  volumeSeries.priceScale().applyOptions({ scaleMargins: { top: .08, bottom: .05 } });
  resizeChartToHost(host);
  if (typeof ResizeObserver === 'function') {
    chartResizeObserver = new ResizeObserver(() => resizeChartToHost(host));
    chartResizeObserver.observe(host);
  }
  markerPlugin = createSeriesMarkers(candleSeries, []);
  try {
    bandPrimitive = new ZoneBandsPrimitive((message) => {
      if (message === 'Zone bands unavailable') updateLineageStatus();
    }, updateLineageStatus);
    candleSeries.attachPrimitive(bandPrimitive);
  } catch {
    bandPrimitive = null;
    updateLineageStatus();
  }
  chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
    bandPrimitive?.updateAllViews();
    updateLineageStatus();
  });
  chart.subscribeCrosshairMove((param) => {
    if (param?.time === undefined || param?.time === null) {
      cancelHoverInspection();
      restoreOverlayInspection();
      return;
    }
    if (!inspectionVisible || !overlayInspection) return;
    const cutoff = candleCutoffForTime(pane, Number(param.time));
    if (!cutoff || cutoff === currentInspection?.cutoff) return;
    loadInspection(cutoff, { passive: true });
  });
  chart.subscribeClick((param) => {
    const id = param?.hoveredObjectId;
    if (typeof id !== 'string' || !id) return;
    cancelHoverInspection();
    clearDetailSelection();
    restoreOverlayInspection();
    const memberIds = bandPrimitive?.memberIdsForHit(id) || [id];
    if (memberIds.length > 1) {
      bandMembers = memberIds;
      inspectionVisible = true;
      updateToolbar();
      renderInspector();
      return;
    }
    loadZoneDetail(memberIds[0], overlayInspection?.cutoff);
  });
  setChartMode();
}

function setError(error) {
  $('#loading-state').hidden = true;
  const target = $('#error-state');
  target.hidden = false;
  target.textContent = error?.message || 'Viewer failed to load';
}

async function init() {
  try {
    const response = await fetch(`/bundle/chart_payload.json${window.location.search}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`chart projection request failed: ${response.status}`);
    payload = validateSelectedPayload(await response.json());
    pane = payload.panes[payload.configured_timeframes[0]];
    initializeDisplayPolicy();
    initializeKernelFilters();
    setHeader();
    makeChart();
    $('#loading-state').hidden = true;
    await loadInspection(latestDisplayedInspectionCutoff(), { open: false });
    updateAsOfLabel();
  } catch (error) {
    setError(error);
  }
}

$('#formation-button').addEventListener('click', () => switchMode('formation'));
$('#lifecycle-button').addEventListener('click', () => switchMode('lifecycle'));
$('#zones-button').addEventListener('click', () => { if (pane) { zonesVisible = !zonesVisible; updateToolbar(); updateBands(); } });
$('#history-button').addEventListener('click', () => {
  if (!pane) return;
  historyVisible = !historyVisible;
  updateToolbar();
  if (historyVisible && !overlayInspection) {
    void loadInspection(latestDisplayedInspectionCutoff());
  } else {
    void loadHistoryForOverlay();
  }
});
$('#candidates-button').addEventListener('click', () => { if (pane) { candidatesVisible = !candidatesVisible; updateToolbar(); updateMarkers(); } });
$('#kernels-button').addEventListener('click', openKernelControls);
$('#lineage-status').addEventListener('click', openLineageLedger);
$('#inspector-button').addEventListener('click', () => {
  if (!pane) return;
  if (inspectionVisible) {
    closeInspector();
    return;
  }
  inspectionVisible = true;
  updateToolbar();
  if (overlayInspection) {
    restoreOverlayInspection();
  } else {
    loadInspection(latestDisplayedInspectionCutoff(), { open: true });
  }
});
$('#close-inspector').addEventListener('click', () => { if (pane) closeInspector(); });
document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && inspectionVisible) closeInspector(); });

init();
