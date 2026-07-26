import {
  CandlestickSeries,
  createChart,
  type UTCTimestamp,
} from 'lightweight-charts';
import {
  PAYLOAD_SCHEMA_VERSION,
  isDiagnosticPayload,
  type DiagnosticLine,
  type DiagnosticViewerPayload,
  type ViewerCandidate,
} from './contracts.js';
import { loadPayload } from './payload.js';
import { candidateDetail, TrendlinePrimitive } from './trendline_primitive.js';

function element<T extends HTMLElement>(selector: string): T {
  const value = document.querySelector<T>(selector);
  if (value === null) throw new Error(`missing viewer element: ${selector}`);
  return value;
}

const container = element<HTMLElement>('#chart');
const summary = element<HTMLElement>('#trial-summary');
const statusBanner = element<HTMLElement>('#status-banner');
const detail = element<HTMLElement>('#hover-detail');
const supportToggle = element<HTMLInputElement>('#show-support');
const resistanceToggle = element<HTMLInputElement>('#show-resistance');
const anchorsToggle = element<HTMLInputElement>('#show-anchors');
const fitButton = element<HTMLButtonElement>('#fit-content');

function diagnosticCandidates(payload: DiagnosticViewerPayload): ViewerCandidate[] {
  return payload.lines.map((line) => ({
    candidate_id: line.selection_id,
    role: 'support',
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

function diagnosticLineDetail(line: DiagnosticLine): string {
  return [
    `${line.side} · ${line.role} · ${line.lineage_id}`,
    `selection ${line.selection_id}`,
    `anchors ${line.anchors[0].time} @ ${line.anchors[0].price} → ${line.anchors[1].time} @ ${line.anchors[1].price}`,
    `projection ${line.projection_time} @ ${line.projection_price}`,
    `initial ${line.initial_distance_atr.toFixed(4)} ATR · 96h ${line.geometry_projected_distance_atr_96h.toFixed(4)} ATR`,
    `reachable at 96h ${line.reachable_at_96h}`,
    `R5 ${line.attribution_class} · ${line.cross_budget_class}`,
  ].join(' · ');
}

async function bootstrap(): Promise<void> {
  const payload = await loadPayload();
  const diagnostic = isDiagnosticPayload(payload) ? payload : null;
  const providerPayload = payload.schema_version === PAYLOAD_SCHEMA_VERSION ? payload : null;
  const renderCandidates = diagnostic !== null ? diagnosticCandidates(diagnostic) : providerPayload!.candidates;
  summary.textContent = diagnostic
    ? `${diagnostic.asset} · ${diagnostic.timeframe} · checkpoint ${diagnostic.checkpoint_index} · ${diagnostic.lines.length} selected lines`
    : `${payload.asset} · ${payload.timeframe} · ${providerPayload!.candles.length} bars · ${providerPayload!.candidates.length} candidates`;
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
  series.setData(payload.candles.map((candle) => ({
  time: candle.time as UTCTimestamp,
  open: candle.open,
  high: candle.high,
  low: candle.low,
  close: candle.close,
  })));

  const primitive = new TrendlinePrimitive(renderCandidates);
  series.attachPrimitive(primitive);
  chart.timeScale().fitContent();

  function updateVisibility(): void {
    primitive.setVisibility({
      support: supportToggle.checked,
      resistance: resistanceToggle.checked,
      anchors: anchorsToggle.checked,
    });
  }

  function selectedFromEvent(param: { point?: { x: number; y: number } | null }): void {
    if (param.point == null) {
      detail.textContent = 'Hover a finite candidate segment for evidence.';
      return;
    }
    const hit = primitive.hitTest(param.point.x, param.point.y);
    const candidate = hit === null ? null : renderCandidates.find((item) => item.candidate_id === hit.externalId) ?? null;
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

void bootstrap().catch((error: unknown) => {
  statusBanner.dataset.status = 'failed';
  statusBanner.textContent = `viewer failed closed: ${error instanceof Error ? error.message : String(error)}`;
});
