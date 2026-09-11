import test from 'node:test';
import assert from 'node:assert/strict';
import { validatePayload } from '../dist/contracts.js';

const HASH = 'a'.repeat(64);

function payload(overrides = {}) {
  const summary = {
    timeframe: '1h', position: 3, event_at: 1_000, available_at: 1_060,
    fit_valid: true, finality: 'confirmed_as_of', structure_state: 'neutral',
    interaction: 'none', market_position_state: 'neutral', hull_width_atr: 1,
    mean_quality: 0.5, signal_count: 0, composite_direction: 0,
    composite_confidence: 0, replay_point_id: HASH, content_id: HASH,
  };
  return {
    schema_version: 'trendlines_research_viewer_payload_v1', payload_id: HASH,
    asset: 'BTCUSDT', timeframe: '1h', selected_position: 3,
    event_at: 1_000, available_at: 1_060, finality: 'confirmed_as_of',
    dataset_id: HASH, research_configuration_id: HASH, replay_id: HASH,
    evidence_bundle_id: HASH, source_id: HASH, checkpoint_id: HASH,
    content_id: HASH, replay_point_id: HASH, fit_snapshot_id: null,
    fit_revision_id: null, boundary_snapshot_id: HASH, boundary_revision_id: HASH,
    signal_snapshot_id: null, signal_revision_id: null,
    display_start_position: 2, display_end_position: 3, display_window_id: HASH,
    candles: [
      { time: 940, open: 1, high: 2, low: 0.5, close: 1.5, volume: 4 },
      { time: 1_000, open: 1.5, high: 2.2, low: 1, close: 2, volume: 5 },
    ],
    pivots: [], lines: [], rays: [], signals: [], selected_summary: summary,
    replay_timeline: [{ ...summary, timeframe: undefined }].map(({ timeframe, ...row }) => row),
    ...overrides,
  };
}

function canonicalSignal(overrides = {}) {
  return {
    evidence_id: HASH,
    ordinal: 0,
    source: 'pattern',
    name: 'pattern_broadening',
    direction: 0,
    confidence: 0.4026,
    metadata: {},
    replay_point_id: HASH,
    content_id: HASH,
    source_id: HASH,
    checkpoint_id: HASH,
    signal_snapshot_id: null,
    signal_revision_id: null,
    ...overrides,
  };
}

test('accepts exact payload shape', () => {
  assert.equal(validatePayload(payload()).asset, 'BTCUSDT');
});

test('rejects extra top-level keys', () => {
  assert.throws(() => validatePayload({ ...payload(), extra: true }), /keys mismatch/);
});

test('rejects future display position', () => {
  assert.throws(() => validatePayload({ ...payload(), display_end_position: 4 }), /display positions/);
});

test('rejects malformed identity', () => {
  assert.throws(() => validatePayload({ ...payload(), replay_id: 'not-a-hash' }), /SHA-256/);
});

test('rejects non-finite candle values', () => {
  assert.throws(() => validatePayload({ ...payload(), candles: [{ ...payload().candles[0], close: Infinity }] }), /finite/);
});

test('allows timeline rows for other recorded points', () => {
  const value = payload();
  value.replay_timeline[0].replay_point_id = 'b'.repeat(64);
  value.replay_timeline[0].content_id = 'c'.repeat(64);
  assert.equal(validatePayload(value).replay_timeline[0].position, 3);
});

test('accepts a non-empty canonical pivot without evidence_id', () => {
  const value = payload();
  value.pivots = [{
    pivot_role: 'high',
    bar_position: 2,
    event_at: 940,
    price: 2,
    extractor: 'fractal',
    extractor_finality: 'confirmed_append_only',
    source_id: HASH,
    checkpoint_id: HASH,
    boundary_snapshot_id: HASH,
    boundary_revision_id: HASH,
    replay_point_id: HASH,
    content_id: HASH,
  }];

  assert.equal(validatePayload(value).pivots.length, 1);
});

test('rejects an unexpected evidence_id on a pivot', () => {
  const value = payload();
  value.pivots = [{
    pivot_role: 'high',
    bar_position: 2,
    event_at: 940,
    price: 2,
    extractor: 'fractal',
    extractor_finality: 'confirmed_append_only',
    source_id: HASH,
    checkpoint_id: HASH,
    boundary_snapshot_id: HASH,
    boundary_revision_id: HASH,
    replay_point_id: HASH,
    content_id: HASH,
    evidence_id: HASH,
  }];

  assert.throws(() => validatePayload(value), /keys mismatch/);
});

test('validates line and ray logical positions', () => {
  const value = payload();
  value.lines = [{
    evidence_id: HASH,
    role: 'support',
    ordinal: 0,
    method: 'endpoint',
    start_position: 1,
    end_position: 3,
    start_time: 940,
    end_time: 1_000,
    start_price: 1,
    end_price: 2,
    slope: 0.5,
    intercept: 0.5,
    touch_count: 2,
    score: 0.8,
    replay_point_id: HASH,
    content_id: HASH,
    source_id: HASH,
    checkpoint_id: HASH,
    boundary_snapshot_id: HASH,
    boundary_revision_id: HASH,
  }];
  value.rays = [{
    evidence_id: HASH,
    role: 'support',
    ordinal: 0,
    start_position: 1,
    end_position: 3,
    start_time: 940,
    end_time: 1_000,
    start_price: 1,
    end_price: 2,
    slope: 0.5,
    intercept: 0.5,
    quality: 0.8,
    touch_count: 2,
    r_squared: 0.9,
    replay_point_id: HASH,
    content_id: HASH,
    source_id: HASH,
    checkpoint_id: HASH,
    boundary_snapshot_id: HASH,
    boundary_revision_id: HASH,
  }];

  const validated = validatePayload(value);
  assert.equal(validated.lines[0].start_position, 1);
  assert.equal(validated.rays[0].end_position, 3);
});

test('accepts a non-empty canonical signal without geometry fields', () => {
  const value = payload({ signals: [canonicalSignal()] });

  assert.equal(validatePayload(value).signals[0].name, 'pattern_broadening');
});

test('rejects geometry fields on a signal', () => {
  const value = payload({
    signals: [canonicalSignal({ start_position: 1, end_position: 3 })],
  });

  assert.throws(() => validatePayload(value), /keys mismatch/);
});

test('rejects malformed signal identity', () => {
  const value = payload({ signals: [canonicalSignal({ source_id: 'not-a-hash' })] });

  assert.throws(() => validatePayload(value), /signals\[0\]\.source_id.*SHA-256/);
});

test('accepts a fully populated mixed payload', () => {
  const value = payload({
    pivots: [{
      pivot_role: 'high',
      bar_position: 2,
      event_at: 940,
      price: 2,
      extractor: 'fractal',
      extractor_finality: 'confirmed_append_only',
      source_id: HASH,
      checkpoint_id: HASH,
      boundary_snapshot_id: HASH,
      boundary_revision_id: HASH,
      replay_point_id: HASH,
      content_id: HASH,
    }],
    lines: [{
      evidence_id: HASH,
      role: 'support',
      ordinal: 0,
      method: 'endpoint',
      start_position: 1,
      end_position: 3,
      start_time: 940,
      end_time: 1_000,
      start_price: 1,
      end_price: 2,
      slope: 0.5,
      intercept: 0.5,
      touch_count: 2,
      score: 0.8,
      replay_point_id: HASH,
      content_id: HASH,
      source_id: HASH,
      checkpoint_id: HASH,
      boundary_snapshot_id: HASH,
      boundary_revision_id: HASH,
    }],
    rays: [{
      evidence_id: HASH,
      role: 'support',
      ordinal: 0,
      start_position: 1,
      end_position: 3,
      start_time: 940,
      end_time: 1_000,
      start_price: 1,
      end_price: 2,
      slope: 0.5,
      intercept: 0.5,
      quality: 0.8,
      touch_count: 2,
      r_squared: 0.9,
      replay_point_id: HASH,
      content_id: HASH,
      source_id: HASH,
      checkpoint_id: HASH,
      boundary_snapshot_id: HASH,
      boundary_revision_id: HASH,
    }],
    signals: [canonicalSignal()],
  });

  assert.equal(validatePayload(value).signals.length, 1);
});
