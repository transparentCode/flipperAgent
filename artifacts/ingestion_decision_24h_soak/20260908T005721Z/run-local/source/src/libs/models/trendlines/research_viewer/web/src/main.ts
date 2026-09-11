import {
  CandlestickSeries,
  createChart,
  type UTCTimestamp,
} from 'lightweight-charts';
import { loadPayload } from './payload.js';
import { TrendlinePrimitive } from './trendline_primitive.js';

function element<T extends HTMLElement>(selector: string): T {
  const result = document.querySelector<T>(selector);
  if (result === null) throw new Error(`missing viewer element: ${selector}`);
  return result;
}

async function bootstrap(): Promise<void> {
  const payload = await loadPayload();
  element<HTMLElement>('#title').textContent = `${payload.asset} · ${payload.timeframe} · position ${payload.selected_position}`;
  const warning = element<HTMLElement>('#finality-warning');
  warning.textContent = payload.finality === 'retrospective_revising'
    ? 'RETROSPECTIVE / RESEARCH ONLY — earlier geometry may revise.'
    : 'CONFIRMED / APPEND-ONLY — confirmed as of selected availability.';
  const identity = element<HTMLElement>('#identity-audit');
  identity.textContent = `dataset ${payload.dataset_id} · replay ${payload.replay_id} · point ${payload.replay_point_id} · content ${payload.content_id}`;
  element<HTMLElement>('#selected-summary').textContent = JSON.stringify(payload.selected_summary, null, 2);
  element<HTMLElement>('#geometry-details').textContent = JSON.stringify({
    lines: payload.lines,
    rays: payload.rays,
    pivots: payload.pivots,
    signals: payload.signals,
  }, null, 2);
  const timelineElement = element<HTMLElement>('#replay-timeline');
  for (const row of payload.replay_timeline) {
    const item = document.createElement('div');
    item.className = `timeline-row${row.position === payload.selected_position ? ' selected' : ''}`;
    item.innerHTML = `<span>${row.position}</span><span>${row.event_at}</span><span>${row.available_at}</span><span>${row.fit_valid ? 'valid' : 'invalid'}</span>`;
    timelineElement.appendChild(item);
  }

  const chart = createChart(element<HTMLElement>('#chart'), {
    autoSize: true,
    layout: { background: { color: '#101719' }, textColor: '#c8d9d2', attributionLogo: true },
    grid: { vertLines: { color: '#20332f' }, horzLines: { color: '#20332f' } },
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

  const visibility = {
    support: element<HTMLInputElement>('#show-support'),
    resistance: element<HTMLInputElement>('#show-resistance'),
    lines: element<HTMLInputElement>('#show-lines'),
    rays: element<HTMLInputElement>('#show-rays'),
    pivots: element<HTMLInputElement>('#show-pivots'),
    signals: element<HTMLInputElement>('#show-signals'),
  };
  const update = (): void => primitive.setVisibility({
    support: visibility.support.checked,
    resistance: visibility.resistance.checked,
    lines: visibility.lines.checked,
    rays: visibility.rays.checked,
    pivots: visibility.pivots.checked,
    signals: visibility.signals.checked,
  });
  Object.values(visibility).forEach((control) => control.addEventListener('change', update));
  element<HTMLButtonElement>('#fit-content').addEventListener('click', () => chart.timeScale().fitContent());
}

void bootstrap().catch((error: unknown) => {
  const warning = document.querySelector<HTMLElement>('#finality-warning');
  if (warning !== null) warning.textContent = `viewer failed closed: ${error instanceof Error ? error.message : String(error)}`;
});
