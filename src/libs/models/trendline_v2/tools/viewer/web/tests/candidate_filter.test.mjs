import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import {
  DEFAULT_FOCUS_SETTINGS,
  DEFAULT_NEAREST_SETTINGS,
  currentRoleAwareDistance,
  displayCounts,
  projectedLinePriceAt,
  selectDisplayCandidates,
  selectFocusCandidates,
  selectNearestCandidates,
} from '../dist/candidate_filter.js';

function candidate({
  id,
  role = 'support',
  secondAnchor = `${id}-second`,
  source = [10, 40],
  confirmation = [12, 45],
  startPrice = 10,
  endPrice = 20,
  intermediate = source[1] - source[0] - 1,
} = {}) {
  return {
    candidate_id: id,
    role,
    start_time: source[0],
    end_time: source[1],
    start_price: startPrice,
    end_price: endPrice,
    anchors: [
      { anchor_id: `${id}-first`, pivot_time: source[0], confirmation_time: confirmation[0], price: startPrice },
      { anchor_id: secondAnchor, pivot_time: source[1], confirmation_time: confirmation[1], price: endPrice },
    ],
    evidence: {
      candidate_id: id,
      extrema_kind: role === 'support' ? 'low' : 'high',
      anchor_source_positions: source,
      confirmation_positions: confirmation,
      validated_intermediate_count: intermediate,
      body_violation_count: 0,
      coordinate_system_version: 'epoch_ns_v1',
      plateau_policy_version: 'left_strict_right_nonstrict_v1',
      schema_version: 'confirmed_extrema_pair_evidence_v1',
      evidence_id: `${id}-evidence`,
    },
  };
}

function candle({ time = 50, low = 30, high = 40, close = 35 } = {}) {
  return { time, open: close, high, low, close, volume: 1 };
}

function ids(items) {
  return items.map((item) => item.candidate_id);
}

function displayInput(mode, candidates, overrides = {}) {
  return {
    mode,
    candidates,
    lastCandle: candle(),
    lastCandlePosition: 99,
    ...overrides,
  };
}

test('nearest defaults are exact', () => {
  assert.deepEqual(DEFAULT_NEAREST_SETTINGS, { maxPerRole: 5 });
});

test('projection at second anchor equals end price', () => {
  const item = candidate({ id: 'end', startPrice: 12, endPrice: 27 });
  assert.equal(projectedLinePriceAt(item, item.end_time), 27);
});

test('projection beyond second anchor extrapolates linearly', () => {
  const item = candidate({ id: 'extrapolate', source: [10, 30], startPrice: 10, endPrice: 20 });
  assert.equal(projectedLinePriceAt(item, 40), 25);
});

test('support range distance uses low minus projected price', () => {
  const item = candidate({ id: 'support-distance', startPrice: 10, endPrice: 20 });
  assert.deepEqual(currentRoleAwareDistance(item, candle({ low: 30, high: 40, close: 35 })), {
    projectedLinePrice: 23.333333333333332,
    rangeDistance: 6.666666666666668,
    closeDistance: 11.666666666666668,
  });
});

test('resistance range distance uses projected price minus high', () => {
  const item = candidate({ id: 'resistance-distance', role: 'resistance', startPrice: 30, endPrice: 50 });
  assert.deepEqual(currentRoleAwareDistance(item, candle({ low: 30, high: 40, close: 35 })), {
    projectedLinePrice: 56.666666666666664,
    rangeDistance: 16.666666666666664,
    closeDistance: 21.666666666666664,
  });
});

test('wick intersection yields zero range distance for both roles', () => {
  const support = candidate({ id: 'support-wick', startPrice: 20, endPrice: 30 });
  const resistance = candidate({ id: 'resistance-wick', role: 'resistance', startPrice: 30, endPrice: 35 });
  assert.equal(currentRoleAwareDistance(support, candle({ low: 30, high: 40 })).rangeDistance, 0);
  assert.equal(currentRoleAwareDistance(resistance, candle({ low: 30, high: 40 })).rangeDistance, 0);
});

test('close distance breaks zero-range ties', () => {
  const nearer = candidate({ id: 'close-nearer', startPrice: 10, endPrice: 28 });
  const farther = candidate({ id: 'close-farther', startPrice: 10, endPrice: 25 });
  const selected = selectNearestCandidates([farther, nearer], candle({ low: 30, high: 40, close: 34 }), { maxPerRole: 5 });
  assert.deepEqual(ids(selected), ['close-nearer', 'close-farther']);
});

test('later confirmation breaks equal-distance ties', () => {
  const late = candidate({ id: 'late', confirmation: [12, 60], startPrice: 10, endPrice: 20 });
  const early = candidate({ id: 'early', confirmation: [12, 50], startPrice: 10, endPrice: 20 });
  assert.deepEqual(ids(selectNearestCandidates([early, late], candle(), { maxPerRole: 5 })), ['late', 'early']);
});

test('intermediate count breaks the next tie', () => {
  const more = candidate({ id: 'more', intermediate: 8 });
  const less = candidate({ id: 'less', intermediate: 3 });
  assert.deepEqual(ids(selectNearestCandidates([less, more], candle(), { maxPerRole: 5 })), ['more', 'less']);
});

test('anchor span breaks the next tie', () => {
  const longer = candidate({ id: 'longer', source: [1, 40], confirmation: [12, 45], intermediate: 3 });
  const shorter = candidate({ id: 'shorter', source: [10, 40], confirmation: [12, 45], intermediate: 3 });
  assert.deepEqual(ids(selectNearestCandidates([shorter, longer], candle({ time: 40 }), { maxPerRole: 5 })), ['longer', 'shorter']);
});

test('candidate ID is final tie-break', () => {
  const b = candidate({ id: 'b' });
  const a = candidate({ id: 'a' });
  assert.deepEqual(ids(selectNearestCandidates([b, a], candle(), { maxPerRole: 5 })), ['a', 'b']);
});

test('one candidate per exact second-anchor ID', () => {
  const weaker = candidate({ id: 'weaker', secondAnchor: 'shared', intermediate: 1 });
  const stronger = candidate({ id: 'stronger', secondAnchor: 'shared', intermediate: 4 });
  assert.deepEqual(ids(selectNearestCandidates([weaker, stronger], candle(), { maxPerRole: 5 })), ['stronger']);
});

test('equal anchor time and price with different IDs remain separate', () => {
  const first = candidate({ id: 'first', secondAnchor: 'anchor-a' });
  const second = candidate({ id: 'second', secondAnchor: 'anchor-b' });
  assert.deepEqual(ids(selectNearestCandidates([first, second], candle(), { maxPerRole: 5 })), ['first', 'second']);
});

test('support and resistance caps are independent', () => {
  const source = [
    candidate({ id: 's1' }), candidate({ id: 's2', endPrice: 21 }), candidate({ id: 's3', endPrice: 22 }),
    candidate({ id: 'r1', role: 'resistance', startPrice: 40, endPrice: 45 }),
    candidate({ id: 'r2', role: 'resistance', startPrice: 41, endPrice: 46 }),
    candidate({ id: 'r3', role: 'resistance', startPrice: 42, endPrice: 47 }),
  ];
  const selected = selectNearestCandidates(source, candle(), { maxPerRole: 5 });
  assert.equal(selected.filter((item) => item.role === 'support').length, 3);
  assert.equal(selected.filter((item) => item.role === 'resistance').length, 3);
});

test('default returns at most five per role', () => {
  const source = Array.from({ length: 8 }, (_, index) => candidate({ id: `s-${index}`, endPrice: 20 + index }));
  const selected = selectNearestCandidates(source, candle(), DEFAULT_NEAREST_SETTINGS);
  assert.equal(selected.length, 5);
});

test('budget ten returns at most ten per role', () => {
  const source = Array.from({ length: 12 }, (_, index) => candidate({ id: `s-${index}`, endPrice: 20 + index }));
  assert.equal(selectNearestCandidates(source, candle(), { maxPerRole: 10 }).length, 10);
});

test('fewer than budget returns all available representatives', () => {
  const source = [candidate({ id: 'one' }), candidate({ id: 'two', secondAnchor: 'two-anchor' })];
  assert.equal(selectNearestCandidates(source, candle(), { maxPerRole: 10 }).length, 2);
});

test('input ordering does not affect ordered output', () => {
  const source = [candidate({ id: 'b' }), candidate({ id: 'a' }), candidate({ id: 'c' })];
  assert.deepEqual(ids(selectNearestCandidates(source, candle(), { maxPerRole: 5 })), ids(selectNearestCandidates([...source].reverse(), candle(), { maxPerRole: 5 })));
});

test('repeated selection is deterministic', () => {
  const source = [candidate({ id: 'b' }), candidate({ id: 'a' }), candidate({ id: 'c' })];
  assert.deepEqual(selectNearestCandidates(source, candle(), { maxPerRole: 5 }), selectNearestCandidates(source, candle(), { maxPerRole: 5 }));
});

test('source candidate order is not mutated', () => {
  const source = [candidate({ id: 'b' }), candidate({ id: 'a' })];
  const before = [...source];
  selectNearestCandidates(source, candle(), { maxPerRole: 5 });
  assert.deepEqual(source, before);
});

test('Focus defaults remain exactly 100/25/true/12', () => {
  assert.deepEqual(DEFAULT_FOCUS_SETTINGS, { recentBars: 100, minAnchorSpan: 25, onePerSecondAnchor: true, maxPerRole: 12 });
});

test('Focus membership and ordering remain unchanged', () => {
  const recent = candidate({ id: 'recent', source: [1, 30], confirmation: [2, 95] });
  const old = candidate({ id: 'old', source: [1, 30], confirmation: [2, -2] });
  const short = candidate({ id: 'short', source: [1, 20], confirmation: [2, 95] });
  assert.deepEqual(ids(selectFocusCandidates([old, short, recent], 99)), ['recent']);
});

test('All raw returns original array by identity', () => {
  const source = [candidate({ id: 'b' }), candidate({ id: 'a' })];
  const raw = selectDisplayCandidates(displayInput('all', source));
  assert.strictEqual(raw, source);
});

test('selectDisplayCandidates dispatches nearest, Focus and All raw', () => {
  const source = [candidate({ id: 'a' }), candidate({ id: 'b', endPrice: 21 })];
  assert.equal(selectDisplayCandidates(displayInput('nearest', source, { nearestSettings: { maxPerRole: 5 } })).length, 2);
  assert.equal(selectDisplayCandidates(displayInput('focus', source, { focusSettings: { recentBars: null, minAnchorSpan: 0, onePerSecondAnchor: false, maxPerRole: null } })).length, 2);
  assert.strictEqual(selectDisplayCandidates(displayInput('all', source)), source);
});

test('invalid zero-duration geometry fails closed', () => {
  const item = candidate({ id: 'zero', source: [10, 10] });
  assert.throws(() => projectedLinePriceAt(item, 10), /non-positive duration/);
});

test('non-finite projected geometry fails closed', () => {
  const item = candidate({ id: 'nan', endPrice: Number.NaN });
  assert.throws(() => projectedLinePriceAt(item, 50), /candidate end price must be finite/);
});

test('viewer defaults to Nearest now with exact budget options', async () => {
  const source = await readFile(new URL('../index.html', import.meta.url), 'utf8');
  assert.match(source, /<option value="nearest" selected>Nearest now<\/option>/);
  const budgetControl = source.match(/<select id="nearest-budget"[\s\S]*?<\/select>/);
  assert.notEqual(budgetControl, null);
  assert.deepEqual([...budgetControl[0].matchAll(/<option value="(5|10)"[^>]*>/g)].map((match) => match[1]), ['5', '10']);
});

test('every new control has a matching label', async () => {
  const source = await readFile(new URL('../index.html', import.meta.url), 'utf8');
  assert.match(source, /id="nearest-budget-control" for="nearest-budget"/);
  assert.match(source, /for="display-mode"/);
});

test('hidden mode controls are disabled by main.ts', async () => {
  const source = await readFile(new URL('../src/main.ts', import.meta.url), 'utf8');
  assert.match(source, /nearestBudget\.disabled = !nearest/);
  assert.match(source, /setFormControlState\(recentAge, focus\)/);
  assert.match(source, /setFormControlState\(resetFocus, focus\)/);
});

test('forbidden quality and actionability wording is absent', async () => {
  const source = await readFile(new URL('../src/main.ts', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /best trendlines|high-quality trendlines|strongest trendlines|actionable trendlines|recommended lines|predictive lines/i);
});

test('candidate filter remains display-only and imports no provider, runner or model implementation', async () => {
  const source = await readFile(new URL('../src/candidate_filter.ts', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /runner|provider_result|payload\.py|trendline_v2\/(?:api|discovery)/i);
});

test('display counts remain role-aware', () => {
  const counts = displayCounts([candidate({ id: 's' }), candidate({ id: 'r', role: 'resistance' })]);
  assert.deepEqual(counts, { total: 2, support: 1, resistance: 1 });
});
