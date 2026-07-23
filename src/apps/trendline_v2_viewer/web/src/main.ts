import {
  CandlestickSeries,
  createChart,
  type UTCTimestamp,
} from 'lightweight-charts';
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

async function bootstrap(): Promise<void> {
  const payload = await loadPayload();
  summary.textContent = `${payload.asset} · ${payload.timeframe} · ${payload.candles.length} bars · ${payload.candidates.length} candidates`;
  statusBanner.dataset.status = payload.status;
  statusBanner.textContent = payload.reason === null ? `provider status: ${payload.status}` : `provider status: ${payload.status} · reason: ${payload.reason}`;

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

  const primitive = new TrendlinePrimitive(payload);
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
    const candidate = hit === null ? null : payload.candidates.find((item) => item.candidate_id === hit.externalId) ?? null;
  if (candidate === null) {
      detail.textContent = 'Hover a finite candidate segment for evidence.';
      return;
  }
    detail.textContent = candidateDetail(candidate, payload);
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
