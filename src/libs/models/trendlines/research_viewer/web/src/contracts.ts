export const PAYLOAD_SCHEMA_VERSION = 'trendlines_research_viewer_payload_v1' as const;

export type Finality = 'confirmed_as_of' | 'retrospective_revising' | string;

export interface ViewerCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ViewerPivot {
  pivot_role: string;
  bar_position: number;
  event_at: number;
  price: number;
  extractor: string;
  extractor_finality: string;
  source_id: string;
  checkpoint_id: string;
  boundary_snapshot_id: string;
  boundary_revision_id: string;
  replay_point_id: string;
  content_id: string;
}

export interface ViewerLine {
  evidence_id: string;
  role: string;
  ordinal: number;
  method: string;
  start_position: number;
  end_position: number;
  start_time: number;
  end_time: number;
  start_price: number;
  end_price: number;
  slope: number;
  intercept: number;
  touch_count: number;
  score: number;
  replay_point_id: string;
  content_id: string;
  source_id: string;
  checkpoint_id: string;
  boundary_snapshot_id: string;
  boundary_revision_id: string;
}

export interface ViewerRay {
  evidence_id: string;
  role: string;
  ordinal: number;
  start_position: number;
  end_position: number;
  start_time: number;
  end_time: number;
  start_price: number;
  end_price: number;
  slope: number;
  intercept: number;
  quality: number;
  touch_count: number;
  r_squared: number;
  replay_point_id: string;
  content_id: string;
  source_id: string;
  checkpoint_id: string;
  boundary_snapshot_id: string;
  boundary_revision_id: string;
}

export interface ViewerSignal {
  evidence_id: string;
  ordinal: number;
  source: string;
  name: string;
  direction: number;
  confidence: number;
  metadata: Record<string, unknown>;
  replay_point_id: string;
  content_id: string;
  source_id: string;
  checkpoint_id: string;
  signal_snapshot_id: string | null;
  signal_revision_id: string | null;
}

export interface ViewerSummary {
  timeframe: string;
  position: number;
  event_at: number;
  available_at: number;
  fit_valid: boolean;
  finality: string;
  structure_state: string;
  interaction: string;
  market_position_state: string;
  hull_width_atr: number;
  mean_quality: number;
  signal_count: number;
  composite_direction: number;
  composite_confidence: number;
  replay_point_id: string;
  content_id: string;
}

export type ViewerTimelineRow = Omit<ViewerSummary, 'timeframe'>;

export interface ViewerPayload {
  schema_version: typeof PAYLOAD_SCHEMA_VERSION;
  payload_id: string;
  asset: string;
  timeframe: string;
  selected_position: number;
  event_at: number;
  available_at: number;
  finality: Finality;
  dataset_id: string;
  research_configuration_id: string;
  replay_id: string;
  evidence_bundle_id: string;
  source_id: string;
  checkpoint_id: string;
  content_id: string;
  replay_point_id: string;
  fit_snapshot_id: string | null;
  fit_revision_id: string | null;
  boundary_snapshot_id: string;
  boundary_revision_id: string;
  signal_snapshot_id: string | null;
  signal_revision_id: string | null;
  display_start_position: number;
  display_end_position: number;
  display_window_id: string;
  candles: ViewerCandle[];
  pivots: ViewerPivot[];
  lines: ViewerLine[];
  rays: ViewerRay[];
  signals: ViewerSignal[];
  selected_summary: ViewerSummary;
  replay_timeline: ViewerTimelineRow[];
}

const HASH_PATTERN = /^[0-9a-f]{64}$/;
const TOP_LEVEL_KEYS = [
  'schema_version', 'payload_id', 'asset', 'timeframe', 'selected_position', 'event_at', 'available_at', 'finality',
  'dataset_id', 'research_configuration_id', 'replay_id', 'evidence_bundle_id', 'source_id', 'checkpoint_id',
  'content_id', 'replay_point_id', 'fit_snapshot_id', 'fit_revision_id', 'boundary_snapshot_id', 'boundary_revision_id',
  'signal_snapshot_id', 'signal_revision_id', 'display_start_position', 'display_end_position', 'display_window_id',
  'candles', 'pivots', 'lines', 'rays', 'signals', 'selected_summary', 'replay_timeline',
] as const;
const CANDLE_KEYS = ['time', 'open', 'high', 'low', 'close', 'volume'] as const;
const PIVOT_KEYS = ['pivot_role', 'bar_position', 'event_at', 'price', 'extractor', 'extractor_finality', 'source_id', 'checkpoint_id', 'boundary_snapshot_id', 'boundary_revision_id', 'replay_point_id', 'content_id'] as const;
const LINE_KEYS = ['evidence_id', 'role', 'ordinal', 'method', 'start_position', 'end_position', 'start_time', 'end_time', 'start_price', 'end_price', 'slope', 'intercept', 'touch_count', 'score', 'replay_point_id', 'content_id', 'source_id', 'checkpoint_id', 'boundary_snapshot_id', 'boundary_revision_id'] as const;
const RAY_KEYS = ['evidence_id', 'role', 'ordinal', 'start_position', 'end_position', 'start_time', 'end_time', 'start_price', 'end_price', 'slope', 'intercept', 'quality', 'touch_count', 'r_squared', 'replay_point_id', 'content_id', 'source_id', 'checkpoint_id', 'boundary_snapshot_id', 'boundary_revision_id'] as const;
const SIGNAL_KEYS = ['evidence_id', 'ordinal', 'source', 'name', 'direction', 'confidence', 'metadata', 'replay_point_id', 'content_id', 'source_id', 'checkpoint_id', 'signal_snapshot_id', 'signal_revision_id'] as const;
const SUMMARY_KEYS = ['timeframe', 'position', 'event_at', 'available_at', 'fit_valid', 'finality', 'structure_state', 'interaction', 'market_position_state', 'hull_width_atr', 'mean_quality', 'signal_count', 'composite_direction', 'composite_confidence', 'replay_point_id', 'content_id'] as const;
const TIMELINE_KEYS = ['position', 'event_at', 'available_at', 'fit_valid', 'finality', 'structure_state', 'interaction', 'market_position_state', 'hull_width_atr', 'mean_quality', 'signal_count', 'composite_direction', 'composite_confidence', 'replay_point_id', 'content_id'] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function exactKeys(value: unknown, expected: readonly string[], field: string): asserts value is Record<string, unknown> {
  if (!isRecord(value)) throw new Error(`${field} must be an object`);
  const actual = Object.keys(value).sort();
  const required = [...expected].sort();
  if (actual.length !== required.length || actual.some((key, index) => key !== required[index])) {
    throw new Error(`${field} keys mismatch`);
  }
}

function hash(value: unknown, field: string, nullable = false): asserts value is string | null {
  if (nullable && value === null) return;
  if (typeof value !== 'string' || !HASH_PATTERN.test(value)) throw new Error(`${field} must be a SHA-256 identity`);
}

function integer(value: unknown, field: string): asserts value is number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value)) throw new Error(`${field} must be an integer`);
}

function finite(value: unknown, field: string): asserts value is number {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`${field} must be finite`);
}

function pointBinding(value: Record<string, unknown>, field: string, payload: ViewerPayload, compare: boolean): void {
  for (const key of ['replay_point_id', 'content_id'] as const) {
    hash(value[key], `${field}.${key}`);
    if (compare && value[key] !== payload[key]) throw new Error(`${field}.${key} differs from selected point`);
  }
}

export function validatePayload(value: unknown): ViewerPayload {
  exactKeys(value, TOP_LEVEL_KEYS, 'viewer payload');
  if (value.schema_version !== PAYLOAD_SCHEMA_VERSION) throw new Error('unsupported viewer payload schema');
  if (typeof value.asset !== 'string' || value.asset.length === 0 || typeof value.timeframe !== 'string' || value.timeframe.length === 0) throw new Error('asset/timeframe must be non-empty');
  for (const key of ['selected_position', 'event_at', 'available_at', 'display_start_position', 'display_end_position'] as const) integer(value[key], key);
  const selectedPosition = value.selected_position as number;
  const displayStart = value.display_start_position as number;
  const displayEnd = value.display_end_position as number;
  const eventAt = value.event_at as number;
  const availableAt = value.available_at as number;
  if (selectedPosition < 0 || displayStart < 0 || displayEnd !== selectedPosition || displayStart > displayEnd) throw new Error('invalid display positions');
  if (availableAt < eventAt) throw new Error('availability precedes event time');
  for (const key of ['payload_id', 'dataset_id', 'research_configuration_id', 'replay_id', 'evidence_bundle_id', 'source_id', 'checkpoint_id', 'content_id', 'replay_point_id', 'boundary_snapshot_id', 'boundary_revision_id', 'display_window_id'] as const) hash(value[key], key);
  for (const key of ['fit_snapshot_id', 'fit_revision_id', 'signal_snapshot_id', 'signal_revision_id'] as const) hash(value[key], key, true);
  if (!Array.isArray(value.candles) || value.candles.length === 0) throw new Error('candles must be non-empty');
  let previousTime: number | null = null;
  value.candles.forEach((candle, index) => {
    exactKeys(candle, CANDLE_KEYS, `candles[${index}]`);
    integer(candle.time, `candles[${index}].time`);
    if (previousTime !== null && candle.time <= previousTime) throw new Error('candles must be ordered');
    previousTime = candle.time;
    for (const key of ['open', 'high', 'low', 'close', 'volume'] as const) finite(candle[key], `candles[${index}].${key}`);
  });
  if (!Array.isArray(value.pivots)) throw new Error('pivots must be an array');
  value.pivots.forEach((pivot, index) => {
    const field = `pivots[${index}]`;
    exactKeys(pivot, PIVOT_KEYS, field);
    pointBinding(pivot, field, value as unknown as ViewerPayload, true);
    integer(pivot.bar_position, `${field}.bar_position`);
    integer(pivot.event_at, `${field}.event_at`);
    finite(pivot.price, `${field}.price`);
    hash(pivot.source_id, `${field}.source_id`);
    hash(pivot.checkpoint_id, `${field}.checkpoint_id`);
    hash(pivot.boundary_snapshot_id, `${field}.boundary_snapshot_id`);
    hash(pivot.boundary_revision_id, `${field}.boundary_revision_id`);
    if (pivot.source_id !== value.source_id) throw new Error(`${field}.source_id differs from selected point`);
    if (pivot.checkpoint_id !== value.checkpoint_id) throw new Error(`${field}.checkpoint_id differs from selected point`);
    if (pivot.boundary_snapshot_id !== value.boundary_snapshot_id) throw new Error(`${field}.boundary_snapshot_id differs from selected point`);
    if (pivot.boundary_revision_id !== value.boundary_revision_id) throw new Error(`${field}.boundary_revision_id differs from selected point`);
    if (pivot.bar_position < 0 || pivot.bar_position > selectedPosition) throw new Error(`${field}.bar_position is outside selected prefix`);
    if (pivot.event_at > eventAt) throw new Error(`${field}.event_at is after selected event`);
  });
  for (const [name, keys, rows] of [['lines', LINE_KEYS, value.lines], ['rays', RAY_KEYS, value.rays]] as const) {
    if (!Array.isArray(rows)) throw new Error(`${name} must be an array`);
    rows.forEach((row, index) => {
      const field = `${name}[${index}]`;
      exactKeys(row, keys, field);
      pointBinding(row, field, value as unknown as ViewerPayload, true);
      hash(row.evidence_id, `${field}.evidence_id`);
      hash(row.source_id, `${field}.source_id`);
      hash(row.checkpoint_id, `${field}.checkpoint_id`);
      hash(row.boundary_snapshot_id, `${field}.boundary_snapshot_id`);
      hash(row.boundary_revision_id, `${field}.boundary_revision_id`);
      integer(row.ordinal, `${field}.ordinal`);
      integer(row.start_position, `${field}.start_position`);
      integer(row.end_position, `${field}.end_position`);
      integer(row.start_time, `${field}.start_time`);
      integer(row.end_time, `${field}.end_time`);
      if (row.start_position < 0 || row.start_position >= row.end_position || row.end_position > selectedPosition) {
        throw new Error(`${field} positions are outside selected prefix`);
      }
      if (row.start_time > row.end_time || row.end_time > eventAt) {
        throw new Error(`${field} times are outside selected event`);
      }
      const numericFields = name === 'lines'
        ? ['start_price', 'end_price', 'slope', 'intercept', 'touch_count', 'score']
        : ['start_price', 'end_price', 'slope', 'intercept', 'quality', 'touch_count', 'r_squared'];
      for (const numericField of numericFields) {
        finite(row[numericField], `${field}.${numericField}`);
      }
      if (
        row.source_id !== value.source_id ||
        row.checkpoint_id !== value.checkpoint_id ||
        row.boundary_snapshot_id !== value.boundary_snapshot_id ||
        row.boundary_revision_id !== value.boundary_revision_id
      ) {
        throw new Error(`${field} differs from selected boundary point`);
      }
    });
  }
  if (!Array.isArray(value.signals)) {
    throw new Error('signals must be an array');
  }
  value.signals.forEach((signal, index) => {
    const field = `signals[${index}]`;
    exactKeys(signal, SIGNAL_KEYS, field);
    pointBinding(signal, field, value as unknown as ViewerPayload, true);
    hash(signal.evidence_id, `${field}.evidence_id`);
    hash(signal.source_id, `${field}.source_id`);
    hash(signal.checkpoint_id, `${field}.checkpoint_id`);
    hash(signal.signal_snapshot_id, `${field}.signal_snapshot_id`, true);
    hash(signal.signal_revision_id, `${field}.signal_revision_id`, true);
    integer(signal.ordinal, `${field}.ordinal`);
    finite(signal.direction, `${field}.direction`);
    finite(signal.confidence, `${field}.confidence`);
    if (typeof signal.source !== 'string' || signal.source.length === 0) {
      throw new Error(`${field}.source must be non-empty`);
    }
    if (typeof signal.name !== 'string' || signal.name.length === 0) {
      throw new Error(`${field}.name must be non-empty`);
    }
    if (!isRecord(signal.metadata)) {
      throw new Error(`${field}.metadata must be an object`);
    }
    if (
      signal.source_id !== value.source_id ||
      signal.checkpoint_id !== value.checkpoint_id ||
      signal.signal_snapshot_id !== value.signal_snapshot_id ||
      signal.signal_revision_id !== value.signal_revision_id
    ) {
      throw new Error(`${field} differs from selected signal point`);
    }
  });
  exactKeys(value.selected_summary, SUMMARY_KEYS, 'selected_summary');
  if (value.selected_summary.timeframe !== value.timeframe || value.selected_summary.position !== value.selected_position || value.selected_summary.event_at !== value.event_at || value.selected_summary.available_at !== value.available_at) throw new Error('selected summary coordinate mismatch');
  pointBinding(value.selected_summary, 'selected_summary', value as unknown as ViewerPayload, true);
  if (!Array.isArray(value.replay_timeline) || value.replay_timeline.length === 0) throw new Error('replay timeline must be non-empty');
  value.replay_timeline.forEach((row, index) => {
    exactKeys(row, TIMELINE_KEYS, `replay_timeline[${index}]`);
    pointBinding(row, `replay_timeline[${index}]`, value as unknown as ViewerPayload, false);
    integer(row.event_at, `replay_timeline[${index}].event_at`);
    integer(row.available_at, `replay_timeline[${index}].available_at`);
    if (row.available_at < row.event_at) throw new Error('timeline availability precedes event');
  });
  return value as unknown as ViewerPayload;
}

export function isSha256(value: unknown): value is string {
  return typeof value === 'string' && HASH_PATTERN.test(value);
}
