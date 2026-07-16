import test from 'node:test';
import assert from 'node:assert/strict';
import {
  casebookMetrics,
  casebookNoticeText,
  casebookOutcomeRange,
  casebookState,
  eventMarkers,
  filterCasebookCases,
  selectCasebookCase,
} from '../src/casebook.js';

const viewer = {
  pending_border_color: '#f2c94c',
  text_color: '#d1d4dc',
};

function caseView(overrides = {}) {
  return {
    case_id: 'case-1',
    fold: '2024_q3',
    side: 'SUPPORT',
    close_location: 'INSIDE_BAND',
    first_touch_at: '2024-07-03T00:00:00Z',
    creation_event: { timestamp: '2024-06-24T00:00:00Z' },
    outcome_window: {
      start: '2024-07-04T00:00:00Z',
      end: '2024-07-14T00:00:00Z',
    },
    zone: { zone_id: 'zone-1' },
    events: [{ time: 1720051200, event_type: 'TOUCHED' }],
    pooled_outcome: {
      quality_reference_atr: 0.5,
    },
    fold_local_outcome: {
      completed: true,
      right_censored: false,
      quality_reference_atr: 0.25,
    },
    comparison: {
      excess_quality: 0.1,
    },
    horizon_lifecycle_class: 'NO_TERMINAL_OR_FAKEOUT_EVENT',
    ...overrides,
  };
}

function casebook(cases) {
  return {
    cases,
    case_count: cases.length,
    notice: 'Diagnostic-only context audit; V1.9 negative disposition is unchanged.',
    disposition: 'BASELINE_NOT_BETTER_THAN_NAIVE_NULL',
  };
}

test('markers sort by time and preserve stable same-bar source order', () => {
  const markers = eventMarkers([
    { time: 30, event_type: 'TOUCHED' },
    { time: 20, event_type: 'BREAK_CONFIRMED' },
    { time: 20, event_type: 'TOUCHED' },
  ], {
    outcome_window: {
      start: '1970-01-01T00:00:20Z',
      end: '1970-01-01T00:00:40Z',
    },
  }, viewer);

  assert.deepEqual(
    markers.map(({ time, text }) => [time, text]),
    [
      [20, 'BREAK_CONFIRMED'],
      [20, 'TOUCHED'],
      [20, 'OUTCOME_START'],
      [30, 'TOUCHED'],
      [40, 'OUTCOME_END'],
    ],
  );
});

test('all case IDs remain selectable and selection preserves payload inputs', () => {
  const cases = Array.from({ length: 36 }, (_, index) => caseView({
    case_id: `case-${index}`,
    zone: { zone_id: `zone-${index}` },
  }));
  const original = JSON.stringify(cases);
  const book = casebook(cases);

  for (const item of cases) {
    const result = selectCasebookCase(book, {}, item.case_id);
    assert.equal(result.selected.case_id, item.case_id);
  }
  assert.equal(JSON.stringify(cases), original);
});

test('filters limit visible selection and do not mutate casebook', () => {
  const cases = [
    caseView({ case_id: 'support-complete', zone: { zone_id: 'zone-support-complete' } }),
    caseView({
      case_id: 'resistance-complete',
      zone: { zone_id: 'zone-resistance-complete' },
      side: 'RESISTANCE',
      close_location: 'ABOVE_BAND',
    }),
    caseView({
      case_id: 'support-censored',
      zone: { zone_id: 'zone-support-censored' },
      fold: '2024_q4',
      fold_local_outcome: { completed: false, right_censored: true, quality_reference_atr: null },
      comparison: null,
    }),
  ];
  const book = casebook(cases);
  const original = JSON.stringify(book);
  const result = filterCasebookCases(cases, { fold: '2024_q3', side: 'SUPPORT' });
  const censored = filterCasebookCases(cases, { completion: 'RIGHT_CENSORED' });

  assert.deepEqual(result.map((item) => item.case_id), ['support-complete']);
  assert.deepEqual(censored.map((item) => item.case_id), ['support-censored']);
  assert.equal(JSON.stringify(book), original);
});

test('changing selected case updates zone, events, metrics, and visible range', () => {
  const selected = caseView({
    case_id: 'resistance-selected',
    zone: { zone_id: 'zone-resistance-selected' },
    side: 'RESISTANCE',
  });
  const state = casebookState(casebook([selected]), {}, '', viewer);

  assert.equal(state.selectedCaseId, 'resistance-selected');
  assert.deepEqual(state.zones, [selected.zone]);
  assert.deepEqual(state.events, selected.events);
  assert.equal(state.metrics.pooledQuality, 0.5);
  assert.deepEqual(state.visibleRange, { from: 1719187200, to: 1720915200 });
});

test('outcome range and metrics use exact selected-case values', () => {
  const selected = caseView();
  assert.deepEqual(casebookOutcomeRange(selected), {
    from: 1719187200,
    to: 1720915200,
  });
  assert.deepEqual(casebookMetrics(selected), {
    pooledQuality: 0.5,
    foldLocalQuality: 0.25,
    excessQuality: 0.1,
    text: 'case-1 · 2024_q3 · SUPPORT · pooled 0.5 · fold-local 0.25 · excess 0.1',
  });
});

test('non-comparable selected case exposes no excess metric', () => {
  const metrics = casebookMetrics(caseView({ comparison: null }));
  assert.equal(metrics.excessQuality, null);
  assert.match(metrics.text, /no persisted comparison$/);
});

test('empty filters clear all casebook state, including stale metrics and selection', () => {
  const selected = caseView();
  const state = casebookState(
    casebook([selected]),
    { fold: '2024_q3', side: 'SUPPORT', completion: 'RIGHT_CENSORED' },
    selected.case_id,
    viewer,
  );

  assert.deepEqual(state.available, []);
  assert.equal(state.selected, null);
  assert.equal(state.selectedCaseId, null);
  assert.deepEqual(state.zones, []);
  assert.deepEqual(state.events, []);
  assert.deepEqual(state.markers, []);
  assert.equal(state.metrics, null);
  assert.equal(state.visibleRange, null);
});

test('permanent casebook notice renders exact V1.9 disposition', () => {
  const text = casebookNoticeText(casebook([caseView()]));
  assert.match(text, /Disposition: BASELINE_NOT_BETTER_THAN_NAIVE_NULL\./);
});
