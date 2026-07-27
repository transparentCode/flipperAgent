import {
  CandlestickSeries,
  createChart,
  type CandlestickData,
  type UTCTimestamp,
  type WhitespaceData,
} from 'lightweight-charts';
import {
  PAYLOAD_SCHEMA_VERSION,
  isDiagnosticPayload,
  type DiagnosticLine,
  type DiagnosticViewerPayload,
  type ViewerCandle,
} from './contracts.js';
import { loadPayload } from './payload.js';
import { candidateDetail, TrendlinePrimitive, type RenderCandidate } from './trendline_primitive.js';
import {
  DEFAULT_FOCUS_SETTINGS,
  displayCounts,
  selectDisplayCandidates,
  type FocusSettings,
} from './candidate_filter.js';

function element<T extends HTMLElement>(selector: string): T {
  const value = document.querySelector<T>(selector);
  if (value === null) throw new Error(`missing viewer element: ${selector}`);
  return value;
}

export function diagnosticCandidates(payload: DiagnosticViewerPayload): RenderCandidate[] {
  return payload.lines.map((line) => ({
    candidate_id: line.selection_id,
    role: 'support',
    diagnosticSide: line.side,
    start_time: line.anchors[0].time,
    end_time: line.projection_time,
    start_price: line.anchors[0].price,
    end_price: line.projection_price,
    anchors: [
      {
        anchor_id: line.lineage_id,
        pivot_time: line.anchors[0].time,
        confirmation_time: line.anchors[0].time,
        price: line.anchors[0].price,
      },
      {
        anchor_id: line.selection_id,
        pivot_time: line.anchors[1].time,
        confirmation_time: line.anchors[1].time,
        price: line.anchors[1].price,
      },
    ],
    evidence: {
      candidate_id: line.selection_id,
      extrema_kind: 'low',
      anchor_source_positions: [0, 1],
      confirmation_positions: [0, 1],
      validated_intermediate_count: 0,
      body_violation_count: 0,
      coordinate_system_version: 'diagnostic_geometry_v1',
      plateau_policy_version: 'diagnostic_geometry_v1',
      schema_version: 'diagnostic_v1',
      evidence_id: line.selection_id,
    },
  }));
}

function candleData(candle: ViewerCandle): CandlestickData<UTCTimestamp> {
  return {
    time: candle.time as UTCTimestamp,
    open: candle.open,
    high: candle.high,
    low: candle.low,
    close: candle.close,
  };
}

export function diagnosticSeriesData(
  payload: DiagnosticViewerPayload,
): Array<CandlestickData<UTCTimestamp> | WhitespaceData<UTCTimestamp>> {
  if (payload.candles.length < 2) throw new Error('diagnostic payload needs two candles for interval inference');
  const realCandles = payload.candles.map(candleData);
  const previous = payload.candles[payload.candles.length - 2].time;
  const last = payload.candles[payload.candles.length - 1].time;
  const interval = last - previous;
  if (!Number.isSafeInteger(interval) || interval <= 0) throw new Error('diagnostic candle interval is invalid');
  const maxProjectionTime = Math.max(...payload.lines.map((line) => line.projection_time));
  const whitespace: WhitespaceData<UTCTimestamp>[] = [];
  for (let time = last + interval; time <= maxProjectionTime; time += interval) {
    whitespace.push({ time: time as UTCTimestamp });
  }
  return [...realCandles, ...whitespace];
}

function diagnosticLineDetail(line: DiagnosticLine): string {
  const side = line.side === 'contender' ? 'Contender' : 'Control';
  const reachability = line.reachable_at_96h ? 'reachable' : 'not reachable';
  return [
    `${side} — ${reachability} — ${line.geometry_projected_distance_atr_96h.toFixed(3)} ATR`,
    `${line.role} · ${line.lineage_id}`,
    `selection ${line.selection_id}`,
    `anchors ${line.anchors[0].time} @ ${line.anchors[0].price} → ${line.anchors[1].time} @ ${line.anchors[1].price}`,
    `projection ${line.projection_time} @ ${line.projection_price}`,
    `initial ${line.initial_distance_atr.toFixed(4)} ATR · 96h ${line.geometry_projected_distance_atr_96h.toFixed(4)} ATR`,
    `reachable at 96h ${line.reachable_at_96h}`,
    `R5 ${line.attribution_class} · ${line.cross_budget_class}`,
  ].join(' · ');
}

async function bootstrap(): Promise<void> {
  const container = element<HTMLElement>('#chart');
  const summary = element<HTMLElement>('#trial-summary');
  const statusBanner = element<HTMLElement>('#status-banner');
  const displayDisclaimer = element<HTMLElement>('#display-disclaimer');
  const displaySummary = element<HTMLElement>('#display-summary');
  const detail = element<HTMLElement>('#hover-detail');
  const densityControls = element<HTMLElement>('#density-controls');
  const displayMode = element<HTMLSelectElement>('#display-mode');
  const recentAge = element<HTMLSelectElement>('#recent-age');
  const minimumSpan = element<HTMLSelectElement>('#min-span');
  const maximumPerRole = element<HTMLSelectElement>('#max-role');
  const uniqueAnchor = element<HTMLInputElement>('#unique-anchor');
  const resetFocus = element<HTMLButtonElement>('#reset-focus');
  const supportToggle = element<HTMLInputElement>('#show-support');
  const resistanceToggle = element<HTMLInputElement>('#show-resistance');
  const anchorsToggle = element<HTMLInputElement>('#show-anchors');
  const fitButton = element<HTMLButtonElement>('#fit-content');
  const payload = await loadPayload();
  const diagnostic = isDiagnosticPayload(payload) ? payload : null;
  const providerPayload = payload.schema_version === PAYLOAD_SCHEMA_VERSION ? payload : null;
  const rawCandidates: RenderCandidate[] = diagnostic !== null
    ? diagnosticCandidates(diagnostic)
    : providerPayload!.candidates;
  const rawCounts = displayCounts(rawCandidates);
  summary.textContent = diagnostic
    ? `${diagnostic.asset} · ${diagnostic.timeframe} · checkpoint ${diagnostic.checkpoint_index} · ${diagnostic.lines.length} selected lines`
    : `${payload.asset} · ${payload.timeframe} · ${providerPayload!.candles.length} bars · ${providerPayload!.candidates.length} candidates`;
  displayDisclaimer.textContent = 'Display-only filtering — provider output unchanged';
  densityControls.hidden = diagnostic !== null;
  statusBanner.dataset.status = diagnostic ? 'diagnostic' : providerPayload!.status;
  statusBanner.textContent = diagnostic
    ? 'Diagnostic view — not a promoted production selector'
    : providerPayload!.reason === null ? `provider status: ${providerPayload!.status}` : `provider status: ${providerPayload!.status} · reason: ${providerPayload!.reason}`;

  const chart = createChart(container, {
  autoSize: true,
  layout: {
    background: { color: '#131e20' },
    textColor: '#c8d9d2',
    attributionLogo: true,
  },
  grid: {
    vertLines: { color: '#20332f' },
    horzLines: { color: '#20332f' },
  },
  timeScale: { borderColor: '#365149', timeVisible: true },
  rightPriceScale: { borderColor: '#365149' },
  });
  const series = chart.addSeries(CandlestickSeries, {
  upColor: '#65d6a5',
  downColor: '#e8a36f',
  borderVisible: false,
  wickUpColor: '#65d6a5',
  wickDownColor: '#e8a36f',
  });
  series.setData(diagnostic === null ? payload.candles.map(candleData) : diagnosticSeriesData(diagnostic));

  const primitive = new TrendlinePrimitive(rawCandidates);
  series.attachPrimitive(primitive);

  function readFocusSettings(): FocusSettings {
    const recentBars = recentAge.value === 'all' ? null : Number(recentAge.value);
    const maxPerRole = maximumPerRole.value === 'all' ? null : Number(maximumPerRole.value);
    return {
      recentBars,
      minAnchorSpan: Number(minimumSpan.value),
      onePerSecondAnchor: uniqueAnchor.checked,
      maxPerRole,
    };
  }

  function displayedCandidates(): readonly RenderCandidate[] {
    if (diagnostic !== null) return rawCandidates;
    return selectDisplayCandidates(
      displayMode.value === 'all' ? 'all' : 'focus',
      rawCandidates,
      payload.candles.length - 1,
      readFocusSettings(),
    );
  }

  function updateDisplaySummary(candidates: readonly RenderCandidate[]): void {
    const counts = displayCounts(candidates);
    if (diagnostic !== null) {
      displaySummary.textContent = `Showing ${counts.total} of ${rawCounts.total} diagnostic lines — density controls unavailable`;
      return;
    }
    if (displayMode.value === 'all') {
      displaySummary.textContent = [
        `Showing all ${rawCounts.total} raw provider candidates`,
        'High visual density expected',
        `Support ${counts.support} of ${rawCounts.support}`,
        `Resistance ${counts.resistance} of ${rawCounts.resistance}`,
      ].join(' · ');
      return;
    }
    const settings = readFocusSettings();
    const recentText = settings.recentBars === null ? 'all' : `${settings.recentBars}`;
    const roleCapText = settings.maxPerRole === null ? 'all' : `${settings.maxPerRole}`;
    displaySummary.textContent = [
      `Showing ${counts.total} of ${rawCounts.total} candidates`,
      `Support ${counts.support} of ${rawCounts.support}`,
      `Resistance ${counts.resistance} of ${rawCounts.resistance}`,
      `Focus: confirmation age ≤${recentText} bars · span ≥${settings.minAnchorSpan} bars · ${settings.onePerSecondAnchor ? 'unique second anchor' : 'all second anchors'} · max ${roleCapText}/role`,
    ].join(' · ');
  }

  function updateDisplay(): void {
    const candidates = displayedCandidates();
    primitive.setCandidates(candidates);
    updateDisplaySummary(candidates);
  }

  updateDisplay();
  chart.timeScale().fitContent();

  function updateVisibility(): void {
    primitive.setVisibility({
      support: supportToggle.checked,
      resistance: resistanceToggle.checked,
      anchors: anchorsToggle.checked,
    });
  }

  for (const control of [displayMode, recentAge, minimumSpan, maximumPerRole, uniqueAnchor]) {
    control.addEventListener('change', updateDisplay);
  }
  resetFocus.addEventListener('click', () => {
    displayMode.value = 'focus';
    recentAge.value = `${DEFAULT_FOCUS_SETTINGS.recentBars}`;
    minimumSpan.value = `${DEFAULT_FOCUS_SETTINGS.minAnchorSpan}`;
    maximumPerRole.value = `${DEFAULT_FOCUS_SETTINGS.maxPerRole}`;
    uniqueAnchor.checked = DEFAULT_FOCUS_SETTINGS.onePerSecondAnchor;
    updateDisplay();
  });

  function selectedFromEvent(param: { point?: { x: number; y: number } | null }): void {
    if (param.point == null) {
      detail.textContent = 'Hover a finite candidate segment for evidence.';
      return;
    }
    const hit = primitive.hitTest(param.point.x, param.point.y);
    const candidate = hit === null ? null : rawCandidates.find((item) => item.candidate_id === hit.externalId) ?? null;
    if (candidate === null) {
      detail.textContent = 'Hover a finite candidate segment for evidence.';
      return;
    }
    if (diagnostic !== null) {
      const line = diagnostic.lines.find((item) => item.selection_id === candidate.candidate_id);
      detail.textContent = line === undefined ? 'Diagnostic line not found.' : diagnosticLineDetail(line);
      return;
    }
    detail.textContent = candidateDetail(candidate, providerPayload!);
  }

  supportToggle.addEventListener('change', updateVisibility);
  resistanceToggle.addEventListener('change', updateVisibility);
  anchorsToggle.addEventListener('change', updateVisibility);
  fitButton.addEventListener('click', () => chart.timeScale().fitContent());
  chart.subscribeCrosshairMove(selectedFromEvent);
  chart.subscribeClick((param) => {
    if (param.point == null) return;
    const hit = primitive.hitTest(param.point.x, param.point.y);
    primitive.select(hit?.externalId ?? null);
    selectedFromEvent(param);
  });
}

if (typeof document !== 'undefined') {
  void bootstrap().catch((error: unknown) => {
    const statusBanner = document.querySelector<HTMLElement>('#status-banner');
    if (statusBanner === null) return;
    statusBanner.dataset.status = 'failed';
    statusBanner.textContent = `viewer failed closed: ${error instanceof Error ? error.message : String(error)}`;
  });
}
