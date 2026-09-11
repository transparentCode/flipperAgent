import type {
  CanvasRenderingTarget2D,
} from 'fancy-canvas';
import type {
  AutoscaleInfo,
  Coordinate,
  IChartApiBase,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  Logical,
  PrimitiveHoveredItem,
  SeriesAttachedParameter,
  SeriesType,
  Time,
  UTCTimestamp,
} from 'lightweight-charts';
import type { CandidateRole, ViewerCandidate, ViewerPayload } from './contracts.js';

export type Visibility = { support: boolean; resistance: boolean; anchors: boolean };
export type SegmentCoordinates = { x1: number; y1: number; x2: number; y2: number };
export type DiagnosticSide = 'contender' | 'control';
export type RenderCandidate = ViewerCandidate & { diagnosticSide?: DiagnosticSide };

export function candidateIsVisible(candidate: RenderCandidate, visibility: Visibility): boolean {
  return candidate.role === 'support' ? visibility.support : visibility.resistance;
}

export function candidateStrokeStyle(candidate: RenderCandidate): string {
  if (candidate.diagnosticSide === 'contender') return '#f2b86b';
  if (candidate.diagnosticSide === 'control') return '#66c7ff';
  return candidate.role === 'support' ? '#65d6a5' : '#e8a36f';
}

export function candidateLineDash(candidate: RenderCandidate): number[] {
  return candidate.diagnosticSide === 'control' ? [7, 5] : [];
}

export function finiteSegmentCoordinates(
  candidate: ViewerCandidate,
  timeToCoordinate: (time: Time) => Coordinate | null,
  priceToCoordinate: (price: number) => Coordinate | null,
): SegmentCoordinates | null {
  const x1 = timeToCoordinate(candidate.start_time as UTCTimestamp);
  const x2 = timeToCoordinate(candidate.end_time as UTCTimestamp);
  const y1 = priceToCoordinate(candidate.start_price);
  const y2 = priceToCoordinate(candidate.end_price);
  if (x1 === null || x2 === null || y1 === null || y2 === null) return null;
  if (![x1, x2, y1, y2].every(Number.isFinite)) return null;
  return { x1, y1, x2, y2 };
}

function distanceToSegment(x: number, y: number, segment: SegmentCoordinates): number {
  const dx = segment.x2 - segment.x1;
  const dy = segment.y2 - segment.y1;
  if (dx === 0 && dy === 0) return Math.hypot(x - segment.x1, y - segment.y1);
  const t = Math.max(0, Math.min(1, ((x - segment.x1) * dx + (y - segment.y1) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(x - (segment.x1 + t * dx), y - (segment.y1 + t * dy));
}

export function hitTestCandidates(
  candidates: readonly RenderCandidate[],
  x: number,
  y: number,
  timeToCoordinate: (time: Time) => Coordinate | null,
  priceToCoordinate: (price: number) => Coordinate | null,
  visibility: Visibility,
  tolerance = 8,
): ViewerCandidate | null {
  let closest: ViewerCandidate | null = null;
  let closestDistance = tolerance;
  for (const candidate of candidates) {
    if (!candidateIsVisible(candidate, visibility)) continue;
    const segment = finiteSegmentCoordinates(candidate, timeToCoordinate, priceToCoordinate);
    if (segment === null) continue;
    const distance = distanceToSegment(x, y, segment);
    if (distance <= closestDistance) {
      closest = candidate;
      closestDistance = distance;
    }
  }
  return closest;
}

export function candidateDetail(
  candidate: ViewerCandidate,
  payload?: Pick<ViewerPayload, 'provider_identity' | 'request_identity'>,
): string {
  const [first, second] = candidate.anchors;
  const evidence = candidate.evidence;
  return [
    `${candidate.candidate_id} · ${candidate.role}`,
    `anchors ${first.pivot_time} @ ${first.price} → ${second.pivot_time} @ ${second.price}`,
    `confirmed ${first.confirmation_time}, ${second.confirmation_time}`,
    `source positions ${evidence.anchor_source_positions.join(', ')}`,
    `validated intermediate ${evidence.validated_intermediate_count}`,
    `provider evidence ${evidence.evidence_id}`,
    ...(payload === undefined ? [] : [
      `provider ${payload.provider_identity}`,
      `request ${payload.request_identity}`,
    ]),
  ].join(' · ');
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
      for (const candidate of this.source.visibleCandidates()) {
        const segment = finiteSegmentCoordinates(
          candidate,
          (time) => timeScale.timeToCoordinate(time),
          (price) => series.priceToCoordinate(price),
        );
        if (segment === null) continue;
        if ((segment.x1 < 0 && segment.x2 < 0) || (segment.x1 > mediaSize.width && segment.x2 > mediaSize.width)) continue;
        const selected = candidate.candidate_id === this.source.selectedCandidateId;
        context.strokeStyle = candidateStrokeStyle(candidate);
        context.setLineDash(candidateLineDash(candidate));
        context.lineWidth = selected ? 3 : 1.5;
        context.globalAlpha = selected ? 1 : 0.8;
        context.beginPath();
        context.moveTo(segment.x1, segment.y1);
        context.lineTo(segment.x2, segment.y2);
        context.stroke();
        if (this.source.visibility.anchors) {
          context.fillStyle = context.strokeStyle;
          for (const anchor of candidate.anchors) {
            const x = timeScale.timeToCoordinate(anchor.pivot_time as UTCTimestamp);
            const y = series.priceToCoordinate(anchor.price);
            if (x === null || y === null || !Number.isFinite(x) || !Number.isFinite(y)) continue;
            context.beginPath();
            context.arc(x, y, selected ? 4 : 3, 0, Math.PI * 2);
            context.fill();
          }
        }
      }
      context.restore();
    });
  }
}

class TrendlinePaneView implements IPrimitivePaneView {
  public constructor(private readonly source: TrendlinePrimitive) {}
  public renderer(): IPrimitivePaneRenderer { return new TrendlineRenderer(this.source); }
  public zOrder(): 'normal' { return 'normal'; }
}

export class TrendlinePrimitive implements ISeriesPrimitive<Time> {
  public chart: IChartApiBase<Time> | null = null;
  public series: ISeriesApi<SeriesType, Time> | null = null;
  public selectedCandidateId: string | null = null;
  public visibility: Visibility = { support: true, resistance: true, anchors: false };
  private requestUpdate: (() => void) | null = null;

  private candidates: readonly RenderCandidate[];

  public constructor(payload: ViewerPayload | readonly ViewerCandidate[]) {
    if (Array.isArray(payload)) {
      this.candidates = payload as readonly RenderCandidate[];
    } else {
      this.candidates = (payload as ViewerPayload).candidates;
    }
  }

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

  public setCandidates(candidates: readonly RenderCandidate[]): void {
    this.candidates = candidates;
    if (
      this.selectedCandidateId !== null
      && !candidates.some((candidate) => candidate.candidate_id === this.selectedCandidateId)
    ) {
      this.selectedCandidateId = null;
    }
    this.requestUpdate?.();
  }

  public visibleCandidates(): RenderCandidate[] {
    return this.candidates.filter((candidate) => candidateIsVisible(candidate, this.visibility));
  }

  public autoscaleInfo(_startTimePoint: Logical, _endTimePoint: Logical): AutoscaleInfo | null {
    const prices = this.visibleCandidates().flatMap((candidate) => [
      candidate.start_price,
      candidate.end_price,
      ...candidate.anchors.map((anchor) => anchor.price),
    ]).filter(Number.isFinite);
    if (prices.length === 0) return null;
    return {
      priceRange: {
        minValue: Math.min(...prices),
        maxValue: Math.max(...prices),
      },
    };
  }

  public setVisibility(visibility: Visibility): void {
    this.visibility = { ...visibility };
    this.requestUpdate?.();
  }

  public select(candidateId: string | null): void {
    this.selectedCandidateId = candidateId;
    this.requestUpdate?.();
  }

  public hitTest(x: number, y: number): PrimitiveHoveredItem | null {
    if (this.chart === null || this.series === null) return null;
    const candidate = hitTestCandidates(
      this.visibleCandidates(),
      x,
      y,
      (time) => this.chart?.timeScale().timeToCoordinate(time) ?? null,
      (price) => this.series?.priceToCoordinate(price) ?? null,
      this.visibility,
    );
    if (candidate === null) return null;
    return {
      externalId: candidate.candidate_id,
      zOrder: 'normal',
      itemType: 'primitive',
      hitTestPriority: 1,
    };
  }
}

export type { CandidateRole };
