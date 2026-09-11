export const PAYLOAD_SCHEMA_VERSION = 'trendline_v2_viewer_payload_v1' as const;
export const DIAGNOSTIC_PAYLOAD_SCHEMA_VERSION = 'trendline_v2_r5_diagnostic_viewer_payload_v1' as const;
export const DIAGNOSTIC_RAW_CANDLE_PATH = 'datasets/btcusdt_4h/provider_result.json' as const;
export const DIAGNOSTIC_RAW_CANDLE_SHA256 = '0fb88993e8ceed7b3812ec8fed895164b4fd00d1d392f5018f81aeea66dd4fe3' as const;
export const R4_DIAGNOSTIC_ID = 'f4a95e118d52eec9ae60b447f08ca11a756908d7861772978b8f0393b0bbd2e2' as const;
export const R4_MANIFEST_ID = '965b4741ec0f7305b8217dbc90d5c2bb31a6185e09b42c519bc404548c290a7e' as const;
export const R4_INVENTORY = '7fbd19fd1b828c09881df6236d2c3b8bdf7ae4bdfd4cd4b03d770c401ecd413c' as const;
export const R5_ATTRIBUTION_ID = 'b918a2102f82670da9fbd365daa9b35d7ec86d5bfb043db149b412f57b25f083' as const;
export const R5_MANIFEST_ID = 'f5569cca5cafe8f4b598a8e4a9e1609fcefc70f89cc90078d21c8f5c0dabc917' as const;
export const R5_INVENTORY = '7fcde0786d367adb0dafbe9fe54349005e69d6cc33f14407477bee534a38d31e' as const;
export const CONTENDER_LINEAGE = '2a7613b64b8d70a79171f8599d0a2d744164d6da8d9e05551a7c1d120041d385' as const;
export const CONTROL_LINEAGE = 'a268b19fed5c2624f25612c5e9975c35b6177215872609e47f25781a309dea95' as const;

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

export interface DiagnosticGeometry {
  start_time: string;
  end_time: string;
  start_price: number;
  end_price: number;
}

export interface DiagnosticAnchor {
  time: number;
  price: number;
}

export interface DiagnosticLine {
  lineage_id: string;
  selection_id: string;
  side: 'contender' | 'control';
  role: 'support';
  policy_id: string;
  control_policy_id_or_null: string | null;
  fixed_geometry: DiagnosticGeometry;
  anchors: [DiagnosticAnchor, DiagnosticAnchor];
  projection_time: number;
  projection_price: number;
  initial_distance_atr: number;
  geometry_projected_distance_atr_96h: number;
  reachable_at_96h: boolean;
  attribution_class: 'FULL_LINEAGE_SUBSTITUTION';
  cross_budget_class: 'PERSISTENT_THROUGH_BUDGET_3';
}

export interface DiagnosticCellAttribution {
  cell_identity: [string, 1, string, string, 5, 'support', 96];
  one_sided_direction: 'control_only';
  attribution_class: 'FULL_LINEAGE_SUBSTITUTION';
  cross_budget_class: 'PERSISTENT_THROUGH_BUDGET_3';
}

export interface DiagnosticViewerPayload {
  schema_version: typeof DIAGNOSTIC_PAYLOAD_SCHEMA_VERSION;
  payload_id: string;
  asset: 'BTCUSDT';
  timeframe: '4h';
  checkpoint_index: 5;
  checkpoint_observed_at: string;
  as_of: string;
  candles: ViewerCandle[];
  lines: [DiagnosticLine, DiagnosticLine];
  r4_diagnostic_id: typeof R4_DIAGNOSTIC_ID;
  r4_manifest_id: typeof R4_MANIFEST_ID;
  r4_inventory: typeof R4_INVENTORY;
  r5_attribution_id: typeof R5_ATTRIBUTION_ID;
  r5_manifest_id: typeof R5_MANIFEST_ID;
  r5_inventory: typeof R5_INVENTORY;
  raw_candle_path: typeof DIAGNOSTIC_RAW_CANDLE_PATH;
  raw_candle_sha256: typeof DIAGNOSTIC_RAW_CANDLE_SHA256;
  cell_attribution: DiagnosticCellAttribution;
}

export type ViewerAnyPayload = ViewerPayload | DiagnosticViewerPayload;

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

function isoSeconds(value: unknown, field: string): number {
  nonEmptyString(value, field);
  const milliseconds = Date.parse(value);
  if (!Number.isFinite(milliseconds) || milliseconds % 1000 !== 0) throw new Error(`${field} must be a whole-second ISO timestamp`);
  return milliseconds / 1000;
}

function validateDiagnosticLine(value: unknown, index: number, checkpoint: number, cell: DiagnosticCellAttribution): DiagnosticLine {
  const expected = [
    'anchors', 'attribution_class', 'control_policy_id_or_null', 'cross_budget_class',
    'fixed_geometry', 'geometry_projected_distance_atr_96h', 'initial_distance_atr',
    'lineage_id', 'policy_id', 'projection_price', 'projection_time', 'reachable_at_96h',
    'role', 'selection_id', 'side',
  ] as const;
  if (!isRecord(value) || !exactKeys(value, expected)) throw new Error(`diagnostic line ${index} keys are invalid`);
  hash(value.lineage_id, `diagnostic line ${index}.lineage_id`);
  hash(value.selection_id, `diagnostic line ${index}.selection_id`);
  if (value.side !== 'contender' && value.side !== 'control') throw new Error('diagnostic line side is invalid');
  if (value.lineage_id !== (value.side === 'contender' ? CONTENDER_LINEAGE : CONTROL_LINEAGE)) throw new Error('diagnostic line lineage is invalid');
  if (value.role !== 'support' || value.attribution_class !== cell.attribution_class || value.cross_budget_class !== cell.cross_budget_class) throw new Error('diagnostic line labels are invalid');
  nonEmptyString(value.policy_id, 'diagnostic policy_id');
  if (value.control_policy_id_or_null !== null) nonEmptyString(value.control_policy_id_or_null, 'diagnostic control policy');
  if (value.policy_id !== 'joint_incumbent_near_v1' || value.control_policy_id_or_null !== (value.side === 'contender' ? null : 'joint_nearest_projection_control_v1')) throw new Error('diagnostic line policy is invalid');
  const geometry = value.fixed_geometry;
  if (!isRecord(geometry) || !exactKeys(geometry, ['end_price', 'end_time', 'start_price', 'start_time'])) throw new Error('diagnostic geometry keys are invalid');
  const start = isoSeconds(geometry.start_time, 'diagnostic geometry.start_time');
  const end = isoSeconds(geometry.end_time, 'diagnostic geometry.end_time');
  finite(geometry.start_price, 'diagnostic geometry.start_price');
  finite(geometry.end_price, 'diagnostic geometry.end_price');
  if (end <= start) throw new Error('diagnostic geometry is not ordered');
  integerSeconds(value.projection_time, 'diagnostic projection_time');
  if (value.projection_time !== checkpoint + 96 * 3600 || value.projection_time <= end) throw new Error('diagnostic projection time is invalid');
  const expectedPrice = (geometry.start_price as number) + ((geometry.end_price as number) - (geometry.start_price as number)) * (value.projection_time - start) / (end - start);
  finite(value.projection_price, 'diagnostic projection_price');
  if (Math.abs((value.projection_price as number) - expectedPrice) > 1e-9) throw new Error('diagnostic projection price is invalid');
  const anchors = value.anchors;
  if (!Array.isArray(anchors) || anchors.length !== 2 || !anchors.every(isRecord)) throw new Error('diagnostic anchors are invalid');
  for (const anchor of anchors) {
    if (!exactKeys(anchor, ['price', 'time'])) throw new Error('diagnostic anchor keys are invalid');
    integerSeconds(anchor.time, 'diagnostic anchor.time');
    finite(anchor.price, 'diagnostic anchor.price');
  }
  if (anchors[0].time !== start || anchors[1].time !== end || anchors[0].price !== geometry.start_price || anchors[1].price !== geometry.end_price) throw new Error('diagnostic anchors do not match geometry');
  finite(value.initial_distance_atr, 'diagnostic initial distance');
  finite(value.geometry_projected_distance_atr_96h, 'diagnostic projected distance');
  if (typeof value.reachable_at_96h !== 'boolean') throw new Error('diagnostic reachability is invalid');
  if (value.side === 'contender' && value.reachable_at_96h) throw new Error('diagnostic contender reachability is invalid');
  if (value.side === 'control' && !value.reachable_at_96h) throw new Error('diagnostic control reachability is invalid');
  return value as unknown as DiagnosticLine;
}

export function validateDiagnosticPayload(value: unknown): DiagnosticViewerPayload {
  const expected = [
    'as_of', 'asset', 'candles', 'cell_attribution', 'checkpoint_index', 'checkpoint_observed_at',
    'lines', 'payload_id', 'r4_diagnostic_id', 'r4_inventory', 'r4_manifest_id', 'r5_attribution_id',
    'r5_inventory', 'r5_manifest_id', 'raw_candle_path', 'raw_candle_sha256', 'schema_version', 'timeframe',
  ] as const;
  if (!isRecord(value) || !exactKeys(value, expected)) throw new Error('diagnostic payload keys are invalid');
  if (value.schema_version !== DIAGNOSTIC_PAYLOAD_SCHEMA_VERSION) throw new Error('unsupported diagnostic payload schema');
  hash(value.payload_id, 'diagnostic payload_id');
  if (value.asset !== 'BTCUSDT' || value.timeframe !== '4h' || value.checkpoint_index !== 5) throw new Error('diagnostic market/checkpoint identity is invalid');
  if (value.as_of !== value.checkpoint_observed_at) throw new Error('diagnostic as_of is invalid');
  const checkpoint = isoSeconds(value.checkpoint_observed_at, 'diagnostic checkpoint_observed_at');
  if (value.r4_diagnostic_id !== R4_DIAGNOSTIC_ID || value.r4_manifest_id !== R4_MANIFEST_ID || value.r4_inventory !== R4_INVENTORY || value.r5_attribution_id !== R5_ATTRIBUTION_ID || value.r5_manifest_id !== R5_MANIFEST_ID || value.r5_inventory !== R5_INVENTORY || value.raw_candle_path !== DIAGNOSTIC_RAW_CANDLE_PATH || value.raw_candle_sha256 !== DIAGNOSTIC_RAW_CANDLE_SHA256) throw new Error('diagnostic source binding is invalid');
  const candles = value.candles;
  if (!Array.isArray(candles) || candles.length === 0) throw new Error('diagnostic candles are empty');
  for (let index = 0; index < candles.length; index += 1) {
    const candle = validateCandle(candles[index], index);
    if (candle.time >= checkpoint) throw new Error('diagnostic candle is after checkpoint');
    if (index > 0 && candle.time - candles[index - 1].time !== 14_400) throw new Error('diagnostic candle spacing is invalid');
  }
  const cell = value.cell_attribution;
  if (!isRecord(cell) || !exactKeys(cell, ['attribution_class', 'cell_identity', 'cross_budget_class', 'one_sided_direction'])) throw new Error('diagnostic cell keys are invalid');
  if (!Array.isArray(cell.cell_identity) || cell.cell_identity.length !== 7 || cell.cell_identity[0] !== 'joint_incumbent_near_v1' || cell.cell_identity[1] !== 1 || cell.cell_identity[2] !== 'joint_nearest_projection_control_v1' || cell.cell_identity[3] !== 'btcusdt_4h' || cell.cell_identity[4] !== 5 || cell.cell_identity[5] !== 'support' || cell.cell_identity[6] !== 96 || cell.one_sided_direction !== 'control_only' || cell.attribution_class !== 'FULL_LINEAGE_SUBSTITUTION' || cell.cross_budget_class !== 'PERSISTENT_THROUGH_BUDGET_3') throw new Error('diagnostic cell identity is invalid');
  if (!Array.isArray(value.lines) || value.lines.length !== 2) throw new Error('diagnostic payload requires two lines');
  const lines = value.lines.map((line, index) => validateDiagnosticLine(line, index, checkpoint, cell as unknown as DiagnosticCellAttribution));
  if (new Set(lines.map((line) => line.side)).size !== 2) throw new Error('diagnostic line sides are not contender/control');
  return { ...(value as unknown as DiagnosticViewerPayload), candles, lines: lines as [DiagnosticLine, DiagnosticLine] };
}

export function validateAnyPayload(value: unknown): ViewerAnyPayload {
  if (isRecord(value) && value.schema_version === DIAGNOSTIC_PAYLOAD_SCHEMA_VERSION) return validateDiagnosticPayload(value);
  return validatePayload(value);
}

export function isDiagnosticPayload(value: ViewerAnyPayload): value is DiagnosticViewerPayload {
  return value.schema_version === DIAGNOSTIC_PAYLOAD_SCHEMA_VERSION;
}
