import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { validatePayload } from '../dist/payload.js';

const HASH = 'a'.repeat(64);

function candidate(role, id) {
  const first = {
    anchor_id: 'b'.repeat(64),
    pivot_time: 1704070800,
    confirmation_time: 1704074400,
    price: role === 'support' ? 10 : 20,
  };
  const second = {
    anchor_id: 'c'.repeat(64),
    pivot_time: 1704078000,
    confirmation_time: 1704081600,
    price: role === 'support' ? 12 : 18,
  };
  return {
    candidate_id: id,
    role,
    start_time: first.pivot_time,
    end_time: second.pivot_time,
    start_price: first.price,
    end_price: second.price,
    anchors: [first, second],
    evidence: {
      candidate_id: id,
      extrema_kind: role === 'support' ? 'low' : 'high',
      anchor_source_positions: [1, 3],
      confirmation_positions: [2, 4],
      validated_intermediate_count: 1,
      body_violation_count: 0,
      coordinate_system_version: 'elapsed_utc_seconds_v1',
      plateau_policy_version: 'leftmost_strict_left_nonstrict_right_v1',
      schema_version: 'v1',
      evidence_id: `${id}`.padEnd(64, 'd'),
    },
  };
}

function payload(overrides = {}) {
  const support = candidate('support', '1'.repeat(64));
  const resistance = candidate('resistance', '2'.repeat(64));
  return {
    schema_version: 'trendline_v2_viewer_payload_v1',
    payload_id: HASH,
    asset: 'BTCUSDT',
    timeframe: '4h',
    observed_at: 1704081600,
    confirmed_through: 1704081600,
    request_identity: HASH,
    input_identity: HASH,
    config_identity: HASH,
    provider_identity: HASH,
    provider_contract_identity: HASH,
    snapshot_id: HASH,
    status: 'success',
    reason: null,
    candles: [
      { time: 1704067200, open: 10, high: 20, low: 9, close: 12, volume: 1 },
      { time: 1704070800, open: 12, high: 20, low: 10, close: 15, volume: 1 },
      { time: 1704074400, open: 15, high: 21, low: 11, close: 17, volume: 1 },
      { time: 1704078000, open: 16, high: 18, low: 12, close: 17, volume: 1 },
      { time: 1704081600, open: 17, high: 23, low: 13, close: 19, volume: 1 },
    ],
    candidates: [support, resistance],
    ...overrides,
  };
}

test('accepts valid payload and both roles', () => {
  const result = validatePayload(payload());
  assert.deepEqual(result.candidates.map((item) => item.role), ['support', 'resistance']);
});

test('rejects non-whole-second candles and malformed evidence association', () => {
  assert.throws(() => validatePayload(payload({ candles: [{ ...payload().candles[0], time: 1704067200.5 }] })), /integer UNIX second/);
  const invalid = payload();
  invalid.candidates[1] = { ...invalid.candidates[1], evidence: { ...invalid.candidates[1].evidence, candidate_id: HASH } };
  assert.throws(() => validatePayload(invalid), /evidence candidate ID mismatch/);
});

test('status-only payload is accepted without fabricated candidates', () => {
  const result = validatePayload(payload({
    status: 'abstained',
    reason: 'no_candidates',
    candidates: [],
  }));
  assert.equal(result.status, 'abstained');
  assert.deepEqual(result.candidates, []);
});

test('rejects impossible status and reason combinations', () => {
  assert.throws(
    () => validatePayload(payload({ status: 'failed', reason: 'no_candidates', candidates: [] })),
    /status\/reason combination/,
  );
  assert.throws(
    () => validatePayload(payload({ status: 'abstained', reason: 'provider_failure', candidates: [] })),
    /status\/reason combination/,
  );
});

test('rejects evidence positions outside candles and unrelated source rows', () => {
  const outOfRange = payload();
  outOfRange.candidates[0].evidence.confirmation_positions = [2, 5];
  assert.throws(() => validatePayload(outOfRange), /outside candle array/);

  const unrelated = payload();
  unrelated.candidates[0].evidence.anchor_source_positions = [0, 3];
  unrelated.candidates[0].evidence.confirmation_positions = [1, 4];
  assert.throws(() => validatePayload(unrelated), /source time/);
});

test('rejects evidence price and anchor timestamp mismatches', () => {
  const priceMismatch = payload();
  priceMismatch.candidates[0].anchors[0].price += 0.25;
  priceMismatch.candidates[0].start_price = priceMismatch.candidates[0].anchors[0].price;
  assert.throws(() => validatePayload(priceMismatch), /source price/);

  const timeMismatch = payload();
  timeMismatch.candidates[0].anchors[0].pivot_time = timeMismatch.candles[0].time;
  timeMismatch.candidates[0].start_time = timeMismatch.candles[0].time;
  assert.throws(() => validatePayload(timeMismatch), /source time/);
});

test('rejects inconsistent evidence counts and successful body violations', () => {
  const countMismatch = payload();
  countMismatch.candidates[0].evidence.validated_intermediate_count = 0;
  assert.throws(() => validatePayload(countMismatch), /intermediate count/);

  const bodyViolation = payload();
  bodyViolation.candidates[0].evidence.body_violation_count = 1;
  assert.throws(() => validatePayload(bodyViolation), /body violations/);
});

test('requires exact provider evidence semantics', () => {
  const invalid = payload();
  invalid.candidates[0].evidence.coordinate_system_version = 'epoch_ns_v1';
  assert.throws(() => validatePayload(invalid), /coordinate system/);
});

test('package versions are exact and pinned', async () => {
  const packageJson = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));
  assert.equal(packageJson.dependencies['lightweight-charts'], '5.2.0');
  assert.equal(packageJson.devDependencies.typescript, '6.0.3');
});
