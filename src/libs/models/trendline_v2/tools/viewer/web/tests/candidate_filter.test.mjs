import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import {
  DEFAULT_FOCUS_SETTINGS,
  displayCounts,
  selectDisplayCandidates,
  selectFocusCandidates,
} from '../dist/candidate_filter.js';

function candidate({
  id,
  role = 'support',
  secondAnchor = `${id}-second`,
  source = [10, 40],
  confirmation = [12, 45],
  intermediate = source[1] - source[0] - 1,
} = {}) {
  return {
    candidate_id: id,
    role,
    start_time: source[0],
    end_time: source[1],
    start_price: 10,
    end_price: 20,
    anchors: [
      { anchor_id: `${id}-first`, pivot_time: source[0], confirmation_time: confirmation[0], price: 10 },
      { anchor_id: secondAnchor, pivot_time: source[1], confirmation_time: confirmation[1], price: 20 },
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

test('focus defaults are exact', () => {
  assert.deepEqual(DEFAULT_FOCUS_SETTINGS, {
    recentBars: 100,
    minAnchorSpan: 25,
    onePerSecondAnchor: true,
    maxPerRole: 12,
  });
});

test('availability age uses confirmation position, not pivot timestamp', () => {
  const recent = candidate({ id: 'recent', source: [1, 20], confirmation: [2, 89] });
  const old = candidate({ id: 'old', source: [80, 90], confirmation: [81, 70] });
  const selected = selectFocusCandidates([recent, old], 99, {
    recentBars: 10,
    minAnchorSpan: 0,
    onePerSecondAnchor: false,
    maxPerRole: null,
  });
  assert.deepEqual(selected.map((item) => item.candidate_id), ['recent']);
});

test('anchor span uses source positions', () => {
  const long = candidate({ id: 'long', source: [10, 35] });
  const short = candidate({ id: 'short', source: [20, 44] });
  const selected = selectFocusCandidates([long, short], 99, {
    recentBars: null,
    minAnchorSpan: 25,
    onePerSecondAnchor: false,
    maxPerRole: null,
  });
  assert.deepEqual(selected.map((item) => item.candidate_id), ['long']);
});

test('one-per-second-anchor groups by anchor ID, not time or price', () => {
  const first = candidate({ id: 'first', secondAnchor: 'shared', intermediate: 1 });
  const stronger = candidate({ id: 'stronger', secondAnchor: 'shared', intermediate: 4 });
  const samePoint = candidate({ id: 'same-point', secondAnchor: 'different-id', intermediate: 2 });
  const selected = selectFocusCandidates([first, stronger, samePoint], 99, {
    recentBars: null,
    minAnchorSpan: 0,
    onePerSecondAnchor: true,
    maxPerRole: null,
  });
  assert.deepEqual(selected.map((item) => item.candidate_id), ['stronger', 'same-point']);
});

test('representative tie-breaking is intermediate, span, then candidate ID', () => {
  const shorter = candidate({ id: 'shorter', secondAnchor: 'group', source: [20, 40], intermediate: 2 });
  const longer = candidate({ id: 'longer', secondAnchor: 'group', source: [10, 40], intermediate: 2 });
  const lexicallyFirst = candidate({ id: 'a', secondAnchor: 'lexical', source: [10, 40], intermediate: 2 });
  const lexicallySecond = candidate({ id: 'b', secondAnchor: 'lexical', source: [10, 40], intermediate: 2 });
  const selected = selectFocusCandidates([shorter, longer, lexicallySecond, lexicallyFirst], 99, {
    recentBars: null,
    minAnchorSpan: 0,
    onePerSecondAnchor: true,
    maxPerRole: null,
  });
  assert.deepEqual(selected.map((item) => item.candidate_id), ['a', 'longer']);
});

test('ordering and caps apply independently by role', () => {
  const candidates = [
    candidate({ id: 'support-old', confirmation: [1, 80] }),
    candidate({ id: 'support-new', confirmation: [1, 95] }),
    candidate({ id: 'support-mid', confirmation: [1, 90] }),
    candidate({ id: 'resistance-old', role: 'resistance', confirmation: [1, 80] }),
    candidate({ id: 'resistance-new', role: 'resistance', confirmation: [1, 95] }),
  ];
  const selected = selectFocusCandidates(candidates, 99, {
    recentBars: null,
    minAnchorSpan: 0,
    onePerSecondAnchor: false,
    maxPerRole: 2,
  });
  assert.deepEqual(selected.map((item) => item.candidate_id), [
    'support-new', 'support-mid', 'resistance-new', 'resistance-old',
  ]);
});

test('All raw returns original array and focus does not mutate source order', () => {
  const source = [candidate({ id: 'b' }), candidate({ id: 'a' })];
  const original = [...source];
  const allRaw = selectDisplayCandidates('all', source, 99);
  assert.strictEqual(allRaw, source);
  assert.deepEqual(source, original);
  selectDisplayCandidates('focus', source, 99, {
    recentBars: null,
    minAnchorSpan: 0,
    onePerSecondAnchor: false,
    maxPerRole: null,
  });
  assert.deepEqual(source, original);
});

test('changing settings changes counts and reset values restore defaults', () => {
  const source = [
    candidate({ id: 'wide', source: [1, 40], confirmation: [2, 95] }),
    candidate({ id: 'narrow', source: [1, 10], confirmation: [2, 95] }),
  ];
  const focused = selectFocusCandidates(source, 99, DEFAULT_FOCUS_SETTINGS);
  const relaxed = selectFocusCandidates(source, 99, {
    recentBars: null,
    minAnchorSpan: 0,
    onePerSecondAnchor: false,
    maxPerRole: null,
  });
  assert.deepEqual(displayCounts(focused), { total: 1, support: 1, resistance: 0 });
  assert.deepEqual(displayCounts(relaxed), { total: 2, support: 2, resistance: 0 });
  assert.deepEqual(DEFAULT_FOCUS_SETTINGS, {
    recentBars: 100,
    minAnchorSpan: 25,
    onePerSecondAnchor: true,
    maxPerRole: 12,
  });
});

test('viewer controls remain labelled and keyboard-addressable', async () => {
  const source = await readFile(new URL('../index.html', import.meta.url), 'utf8');
  for (const id of ['display-mode', 'recent-age', 'min-span', 'max-role', 'unique-anchor', 'reset-focus']) {
    assert.match(source, new RegExp(`id="${id}"`));
  }
  assert.match(source, /for="display-mode"/);
  assert.match(source, /for="unique-anchor"/);
});

test('filter module stays display-only and imports no model or runner code', async () => {
  const source = await readFile(new URL('../src/candidate_filter.ts', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /runner|provider_result|payload\.py|trendline_v2\/(?:api|discovery)/i);
});
