import type { CanvasRenderingTarget2D } from 'fancy-canvas';
import type {
  Coordinate,
  IChartApiBase,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  Logical,
  SeriesAttachedParameter,
  SeriesType,
  Time,
  UTCTimestamp,
} from 'lightweight-charts';
import type { ViewerLine, ViewerPayload, ViewerRay } from './contracts.js';

export type Visibility = {
  support: boolean;
  resistance: boolean;
  lines: boolean;
  rays: boolean;
  pivots: boolean;
  signals: boolean;
};

export function roleVisible(role: string, visibility: Visibility): boolean {
  return role === 'support' ? visibility.support : visibility.resistance;
}

export function finiteSegmentCoordinates(
  startLogical: number,
  endLogical: number,
  startPrice: number,
  endPrice: number,
  logicalToCoordinate: (logical: Logical) => Coordinate | null,
  priceToCoordinate: (price: number) => Coordinate | null,
  minX = 0,
  maxX = Number.MAX_VALUE,
): [number, number, number, number] | null {
  const x1 = logicalToCoordinate(startLogical as Logical);
  const x2 = logicalToCoordinate(endLogical as Logical);
  const y1 = priceToCoordinate(startPrice);
  const y2 = priceToCoordinate(endPrice);
  if (x1 === null || x2 === null || y1 === null || y2 === null) return null;
  if (![x1, x2, y1, y2].every(Number.isFinite)) return null;
  return clipSegmentToHorizontalViewport(x1, y1, x2, y2, minX, maxX);
}

export function clipSegmentToHorizontalViewport(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  minX: number,
  maxX: number,
): [number, number, number, number] | null {
  if (![x1, y1, x2, y2, minX, maxX].every(Number.isFinite) || minX > maxX) return null;
  if (Math.max(x1, x2) < minX || Math.min(x1, x2) > maxX) return null;
  if (x1 === x2) return [x1, y1, x2, y2];

  const yAt = (x: number): number => y1 + ((y2 - y1) * (x - x1)) / (x2 - x1);
  let clippedX1 = x1;
  let clippedY1 = y1;
  let clippedX2 = x2;
  let clippedY2 = y2;
  if (clippedX1 < minX) {
    clippedX1 = minX;
    clippedY1 = yAt(minX);
  } else if (clippedX1 > maxX) {
    clippedX1 = maxX;
    clippedY1 = yAt(maxX);
  }
  if (clippedX2 < minX) {
    clippedX2 = minX;
    clippedY2 = yAt(minX);
  } else if (clippedX2 > maxX) {
    clippedX2 = maxX;
    clippedY2 = yAt(maxX);
  }
  if (![clippedX1, clippedY1, clippedX2, clippedY2].every(Number.isFinite)) return null;
  return [clippedX1, clippedY1, clippedX2, clippedY2];
}

function drawSegment(
  context: CanvasRenderingContext2D,
  row: ViewerLine | ViewerRay,
  logicalToCoordinate: (logical: Logical) => Coordinate | null,
  priceToCoordinate: (price: number) => Coordinate | null,
  color: string,
  width: number,
  displayStartPosition: number,
  viewportWidth: number,
  dashed: boolean,
): void {
  const coordinates = finiteSegmentCoordinates(
    row.start_position - displayStartPosition,
    row.end_position - displayStartPosition,
    row.start_price,
    row.end_price,
    logicalToCoordinate,
    priceToCoordinate,
    0,
    viewportWidth,
  );
  if (coordinates === null) return;
  const [x1, y1, x2, y2] = coordinates;
  context.strokeStyle = color;
  context.lineWidth = width;
  context.setLineDash(dashed ? [6, 4] : []);
  context.beginPath();
  context.moveTo(x1, y1);
  context.lineTo(x2, y2);
  context.stroke();
  context.setLineDash([]);
}

class TrendlineRenderer implements IPrimitivePaneRenderer {
  public constructor(private readonly source: TrendlinePrimitive) {}

  public draw(target: CanvasRenderingTarget2D): void {
    const chart = this.source.chart;
    const series = this.source.series;
    if (chart === null || series === null) return;
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      const timeScale = chart.timeScale();
      context.save();
      context.lineCap = 'round';
      const timeToCoordinate = (time: Time): Coordinate | null => timeScale.timeToCoordinate(time);
      const logicalToCoordinate = (logical: Logical): Coordinate | null => timeScale.logicalToCoordinate(logical);
      const priceToCoordinate = (price: number): Coordinate | null => series.priceToCoordinate(price);
      if (this.source.visibility.lines) {
        for (const line of this.source.payload.lines) {
          if (!roleVisible(line.role, this.source.visibility)) continue;
          drawSegment(context, line, logicalToCoordinate, priceToCoordinate, line.role === 'support' ? '#62d5a5' : '#f0a16d', 2, this.source.payload.display_start_position, mediaSize.width, false);
        }
      }
      if (this.source.visibility.rays) {
        for (const ray of this.source.payload.rays) {
          if (!roleVisible(ray.role, this.source.visibility)) continue;
          drawSegment(context, ray, logicalToCoordinate, priceToCoordinate, ray.role === 'support' ? '#62a7d5' : '#d78ce0', 1.5, this.source.payload.display_start_position, mediaSize.width, true);
        }
      }
      if (this.source.visibility.pivots) {
        for (const pivot of this.source.payload.pivots) {
          const x = timeToCoordinate(pivot.event_at as UTCTimestamp);
          const y = priceToCoordinate(pivot.price);
          if (x === null || y === null || !Number.isFinite(x) || !Number.isFinite(y)) continue;
          context.fillStyle = pivot.pivot_role === 'high' ? '#f0a16d' : '#62d5a5';
          context.beginPath();
          context.arc(x, y, 4, 0, Math.PI * 2);
          context.fill();
        }
      }
      if (this.source.visibility.signals) {
        const x = timeToCoordinate(this.source.payload.event_at as UTCTimestamp);
        const lastCandle = this.source.payload.candles[this.source.payload.candles.length - 1];
        for (const [index, signal] of this.source.payload.signals.entries()) {
          const signalPrice = signal.direction >= 0 ? lastCandle.high : lastCandle.low;
          const y = priceToCoordinate(signalPrice);
          if (x !== null && y !== null && Number.isFinite(x) && Number.isFinite(y)) {
            const offset = index * 9;
            context.fillStyle = '#f5dc74';
            context.beginPath();
            context.moveTo(x, y - 8 - offset);
            context.lineTo(x - 6, y + 5 - offset);
            context.lineTo(x + 6, y + 5 - offset);
            context.closePath();
            context.fill();
          }
        }
      }
      const selectedX = timeToCoordinate(this.source.payload.event_at as UTCTimestamp);
      if (selectedX !== null && Number.isFinite(selectedX) && selectedX >= 0 && selectedX <= mediaSize.width) {
        context.strokeStyle = '#fff2bd';
        context.globalAlpha = 0.35;
        context.lineWidth = 1;
        context.beginPath();
        context.moveTo(selectedX, 0);
        context.lineTo(selectedX, mediaSize.height);
        context.stroke();
      }
      context.restore();
    });
  }
}

class TrendlinePaneView implements IPrimitivePaneView {
  public constructor(private readonly source: TrendlinePrimitive) {}
  public renderer(): IPrimitivePaneRenderer { return new TrendlineRenderer(this.source); }
  public zOrder(): 'top' { return 'top'; }
}

export class TrendlinePrimitive implements ISeriesPrimitive<Time> {
  public chart: IChartApiBase<Time> | null = null;
  public series: ISeriesApi<SeriesType, Time> | null = null;
  public visibility: Visibility = { support: true, resistance: true, lines: true, rays: true, pivots: true, signals: true };
  private requestUpdate: (() => void) | null = null;

  public constructor(public readonly payload: ViewerPayload) {}

  public attached(parameters: SeriesAttachedParameter<Time>): void {
    this.chart = parameters.chart;
    this.series = parameters.series;
    this.requestUpdate = parameters.requestUpdate;
  }

  public detached(): void {
    this.chart = null;
    this.series = null;
    this.requestUpdate = null;
  }

  public paneViews(): readonly IPrimitivePaneView[] { return [new TrendlinePaneView(this)]; }

  public setVisibility(visibility: Visibility): void {
    this.visibility = { ...visibility };
    this.requestUpdate?.();
  }
}
