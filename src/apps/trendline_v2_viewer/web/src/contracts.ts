export const PAYLOAD_SCHEMA_VERSION = 'trendline_v2_viewer_payload_v1' as const;

export type ProviderStatus = 'success' | 'abstained' | 'failed';
export type ProviderReason =
  | 'insufficient_input'
  | 'no_candidates'
  | 'invalid_input'
  | 'configuration_error'
  | 'provider_failure'
  | 'hypothesis_limit_exceeded'
  | 'output_limit_exceeded';
export type CandidateRole = 'support' | 'resistance';

export interface ViewerCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ViewerAnchor {
  anchor_id: string;
  pivot_time: number;
  confirmation_time: number;
  price: number;
}

export interface ViewerEvidence {
  candidate_id: string;
  extrema_kind: 'high' | 'low';
  anchor_source_positions: [number, number];
  confirmation_positions: [number, number];
  validated_intermediate_count: number;
  body_violation_count: number;
  coordinate_system_version: string;
  plateau_policy_version: string;
  schema_version: string;
  evidence_id: string;
}

export interface ViewerCandidate {
  candidate_id: string;
  role: CandidateRole;
  start_time: number;
  end_time: number;
  start_price: number;
  end_price: number;
  anchors: [ViewerAnchor, ViewerAnchor];
  evidence: ViewerEvidence;
}

export interface ViewerPayload {
  schema_version: typeof PAYLOAD_SCHEMA_VERSION;
  payload_id: string;
  asset: string;
  timeframe: string;
  observed_at: number;
  confirmed_through: number;
  request_identity: string;
  input_identity: string;
  config_identity: string;
  provider_identity: string;
  provider_contract_identity: string;
  snapshot_id: string;
  status: ProviderStatus;
  reason: ProviderReason | null;
  candles: ViewerCandle[];
  candidates: ViewerCandidate[];
}

const REASONS = new Set<ProviderReason>([
  'insufficient_input',
  'no_candidates',
  'invalid_input',
  'configuration_error',
  'provider_failure',
  'hypothesis_limit_exceeded',
  'output_limit_exceeded',
]);
const STATUSES = new Set<ProviderStatus>(['success', 'abstained', 'failed']);
const HASH_PATTERN = /^[0-9a-f]{64}$/;
const ALLOWED_REASONS_BY_STATUS: Record<ProviderStatus, ReadonlySet<ProviderReason | null>> = {
  success: new Set([null]),
  abstained: new Set<ProviderReason | null>([
    'insufficient_input',
    'no_candidates',
    'invalid_input',
    'configuration_error',
    'hypothesis_limit_exceeded',
    'output_limit_exceeded',
  ]),
  failed: new Set<ProviderReason | null>(['provider_failure']),
};
const EVIDENCE_COORDINATE_SYSTEM = 'elapsed_utc_seconds_v1';
const EVIDENCE_PLATEAU_POLICY = 'leftmost_strict_left_nonstrict_right_v1';
const EVIDENCE_SCHEMA_VERSION = 'v1';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const required = [...expected].sort();
  return actual.length === required.length && actual.every((key, index) => key === required[index]);
}

function hash(value: unknown, field: string): asserts value is string {
  if (typeof value !== 'string' || !HASH_PATTERN.test(value)) throw new Error(`${field} must be a SHA-256 hash`);
}

function integerSeconds(value: unknown, field: string): asserts value is number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value)) {
    throw new Error(`${field} must be an integer UNIX second`);
  }
}

function finite(value: unknown, field: string): asserts value is number {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`${field} must be finite`);
}

function nonEmptyString(value: unknown, field: string): asserts value is string {
  if (typeof value !== 'string' || value.length === 0) throw new Error(`${field} must be non-empty`);
}

function validateCandle(value: unknown, index: number): ViewerCandle {
  if (!isRecord(value) || !exactKeys(value, ['close', 'high', 'low', 'open', 'time', 'volume'])) {
    throw new Error(`candle ${index} keys are invalid`);
  }
  integerSeconds(value.time, `candle ${index}.time`);
  const names = ['open', 'high', 'low', 'close', 'volume'] as const;
  for (const name of names) finite(value[name], `candle ${index}.${name}`);
  const open = value.open as number;
  const high = value.high as number;
  const low = value.low as number;
  const close = value.close as number;
  const volume = value.volume as number;
  if (
    high < low
    || high < open
    || high < close
    || low > open
    || low > close
    || volume < 0
  ) throw new Error(`candle ${index} violates OHLCV bounds`);
  return value as unknown as ViewerCandle;
}

function validateAnchor(value: unknown, candidateIndex: number, index: number): ViewerAnchor {
  if (!isRecord(value) || !exactKeys(value, ['anchor_id', 'confirmation_time', 'pivot_time', 'price'])) {
    throw new Error(`candidate ${candidateIndex} anchor ${index} keys are invalid`);
  }
  hash(value.anchor_id, 'anchor_id');
  integerSeconds(value.pivot_time, 'anchor.pivot_time');
  integerSeconds(value.confirmation_time, 'anchor.confirmation_time');
  finite(value.price, 'anchor.price');
  if (value.confirmation_time < value.pivot_time) throw new Error('anchor confirmation precedes pivot');
  return value as unknown as ViewerAnchor;
}

function validateEvidence(
  value: unknown,
  candidateId: string,
  role: CandidateRole,
  anchors: [ViewerAnchor, ViewerAnchor],
  candles: ViewerCandle[],
  successful: boolean,
): ViewerEvidence {
  const expected = [
    'anchor_source_positions',
    'body_violation_count',
    'candidate_id',
    'confirmation_positions',
    'coordinate_system_version',
    'evidence_id',
    'extrema_kind',
    'plateau_policy_version',
    'schema_version',
    'validated_intermediate_count',
  ] as const;
  if (!isRecord(value) || !exactKeys(value, expected)) throw new Error('evidence keys are invalid');
  if (value.candidate_id !== candidateId) throw new Error('evidence candidate ID mismatch');
  hash(value.evidence_id, 'evidence_id');
  if (value.extrema_kind !== 'high' && value.extrema_kind !== 'low') throw new Error('evidence extrema kind is invalid');
  if (value.coordinate_system_version !== EVIDENCE_COORDINATE_SYSTEM) throw new Error('evidence coordinate system is invalid');
  if (value.plateau_policy_version !== EVIDENCE_PLATEAU_POLICY) throw new Error('evidence plateau policy is invalid');
  if (value.schema_version !== EVIDENCE_SCHEMA_VERSION) throw new Error('evidence schema version is invalid');
  const expectedKind = role === 'support' ? 'low' : 'high';
  if (value.extrema_kind !== expectedKind) throw new Error('evidence role association is invalid');
  for (const name of ['anchor_source_positions', 'confirmation_positions'] as const) {
    const positions = value[name];
    if (!Array.isArray(positions) || positions.length !== 2 || !positions.every((item) => typeof item === 'number' && Number.isSafeInteger(item) && item >= 0)) {
      throw new Error(`evidence.${name} is invalid`);
    }
    if (positions[0] >= positions[1]) throw new Error(`evidence.${name} is not ordered`);
  }
  const sourcePositions = value.anchor_source_positions as number[];
  const confirmationPositions = value.confirmation_positions as number[];
  for (const position of [...sourcePositions, ...confirmationPositions]) {
    if (position >= candles.length) throw new Error('evidence position is outside candle array');
  }
  if (confirmationPositions.some((item, index) => item <= sourcePositions[index])) {
    throw new Error('evidence confirmation position precedes source position');
  }
  for (const name of ['validated_intermediate_count', 'body_violation_count'] as const) {
    if (typeof value[name] !== 'number' || !Number.isSafeInteger(value[name]) || value[name] < 0) throw new Error(`evidence.${name} is invalid`);
  }
  for (let index = 0; index < 2; index += 1) {
    const source = candles[sourcePositions[index]];
    const confirmation = candles[confirmationPositions[index]];
    if (source.time !== anchors[index].pivot_time) throw new Error('evidence source time does not match anchor');
    if (confirmation.time !== anchors[index].confirmation_time) throw new Error('evidence confirmation time does not match anchor');
    const expectedPrice = value.extrema_kind === 'low' ? source.low : source.high;
    if (expectedPrice !== anchors[index].price) throw new Error('evidence source price does not match anchor');
  }
  if (value.validated_intermediate_count !== sourcePositions[1] - sourcePositions[0] - 1) {
    throw new Error('evidence intermediate count does not match source positions');
  }
  if (successful && value.body_violation_count !== 0) throw new Error('successful evidence contains body violations');
  return value as unknown as ViewerEvidence;
}

function validateCandidate(value: unknown, index: number, candles: ViewerCandle[], successful: boolean): ViewerCandidate {
  const expected = ['anchors', 'candidate_id', 'end_price', 'end_time', 'evidence', 'role', 'start_price', 'start_time'] as const;
  if (!isRecord(value) || !exactKeys(value, expected)) throw new Error(`candidate ${index} keys are invalid`);
  hash(value.candidate_id, 'candidate_id');
  if (value.role !== 'support' && value.role !== 'resistance') throw new Error(`candidate ${index} role is invalid`);
  integerSeconds(value.start_time, 'candidate.start_time');
  integerSeconds(value.end_time, 'candidate.end_time');
  if (value.end_time <= value.start_time) throw new Error('candidate geometry is not ordered');
  finite(value.start_price, 'candidate.start_price');
  finite(value.end_price, 'candidate.end_price');
  if (!Array.isArray(value.anchors) || value.anchors.length !== 2) throw new Error('candidate requires two anchors');
  const anchors = [validateAnchor(value.anchors[0], index, 0), validateAnchor(value.anchors[1], index, 1)] as [ViewerAnchor, ViewerAnchor];
  if (anchors[0].anchor_id === anchors[1].anchor_id) throw new Error('candidate anchor IDs are not unique');
  if (value.start_time !== anchors[0].pivot_time || value.start_price !== anchors[0].price || value.end_time !== anchors[1].pivot_time || value.end_price !== anchors[1].price) {
    throw new Error('candidate geometry must equal finite anchor segment');
  }
  const evidence = validateEvidence(value.evidence, value.candidate_id, value.role, anchors, candles, successful);
  const expectedKind = value.role === 'support' ? 'low' : 'high';
  if (evidence.extrema_kind !== expectedKind) throw new Error('evidence role association is invalid');
  return { ...(value as unknown as ViewerCandidate), anchors, evidence };
}

export function validatePayload(value: unknown): ViewerPayload {
  const expected = [
    'asset', 'candles', 'candidates', 'confirmed_through', 'config_identity',
    'input_identity', 'observed_at', 'payload_id', 'provider_contract_identity',
    'provider_identity', 'reason', 'request_identity', 'schema_version',
    'snapshot_id', 'status', 'timeframe',
  ] as const;
  if (!isRecord(value) || !exactKeys(value, expected)) throw new Error('viewer payload keys are invalid');
  if (value.schema_version !== PAYLOAD_SCHEMA_VERSION) throw new Error('unsupported viewer payload schema');
  hash(value.payload_id, 'payload_id');
  for (const name of ['request_identity', 'input_identity', 'config_identity', 'provider_identity', 'provider_contract_identity', 'snapshot_id'] as const) hash(value[name], name);
  nonEmptyString(value.asset, 'asset');
  nonEmptyString(value.timeframe, 'timeframe');
  integerSeconds(value.observed_at, 'observed_at');
  integerSeconds(value.confirmed_through, 'confirmed_through');
  if (value.confirmed_through > value.observed_at) throw new Error('confirmed_through is after observed_at');
  if (typeof value.status !== 'string' || !STATUSES.has(value.status as ProviderStatus)) throw new Error('invalid provider status');
  if (value.reason !== null && (typeof value.reason !== 'string' || !REASONS.has(value.reason as ProviderReason))) throw new Error('invalid provider reason');
  const status = value.status as ProviderStatus;
  const reason = value.reason as ProviderReason | null;
  if (!ALLOWED_REASONS_BY_STATUS[status].has(reason)) throw new Error('provider status/reason combination is invalid');
  if (!Array.isArray(value.candles) || value.candles.length === 0) throw new Error('candles must be non-empty');
  const candles = value.candles.map(validateCandle);
  for (let index = 1; index < candles.length; index += 1) if (candles[index].time <= candles[index - 1].time) throw new Error('candle times are not strictly increasing');
  if (!Array.isArray(value.candidates)) throw new Error('candidates must be an array');
  const candidates = value.candidates.map((candidate, index) => validateCandidate(candidate, index, candles, status === 'success'));
  const candidateIds = new Set(candidates.map((candidate) => candidate.candidate_id));
  const evidenceIds = new Set(candidates.map((candidate) => candidate.evidence.evidence_id));
  if (candidateIds.size !== candidates.length) throw new Error('candidate IDs are not unique');
  if (evidenceIds.size !== candidates.length) throw new Error('evidence IDs are not unique');
  if (status === 'success' && candidates.length === 0) throw new Error('successful payload has invalid outcome');
  if (status !== 'success' && candidates.length !== 0) throw new Error('non-success payload has invalid outcome');
  return { ...(value as unknown as ViewerPayload), candles, candidates };
}
