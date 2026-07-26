import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import {
  candidateIsVisible,
  candidateLineDash,
  candidateStrokeStyle,
  finiteSegmentCoordinates,
  hitTestCandidates,
  TrendlinePrimitive,
} from '../dist/trendline_primitive.js';

function candidate(role = 'support') {
  const id = role === 'support' ? '1'.repeat(64) : '2'.repeat(64);
  return {
    candidate_id: id,
    role,
    start_time: 100,
    end_time: 200,
    start_price: 10,
    end_price: 20,
    anchors: [
      { anchor_id: '3'.repeat(64), pivot_time: 100, confirmation_time: 110, price: 10 },
      { anchor_id: '4'.repeat(64), pivot_time: 200, confirmation_time: 210, price: 20 },
    ],
    evidence: {
      candidate_id: id,
      extrema_kind: role === 'support' ? 'low' : 'high',
      anchor_source_positions: [1, 3],
      confirmation_positions: [2, 4],
      validated_intermediate_count: 1,
      body_violation_count: 0,
      coordinate_system_version: 'epoch_ns_v1',
      plateau_policy_version: 'left_strict_right_nonstrict_v1',
      schema_version: 'confirmed_extrema_pair_evidence_v1',
      evidence_id: '5'.repeat(64),
    },
  };
}

const support = candidate('support');
const resistance = candidate('resistance');
const timeToCoordinate = (time) => time;
const priceToCoordinate = (price) => price * 2;
const diagnosticContender = { ...support, candidate_id: '6'.repeat(64), end_price: 51564.8676, diagnosticSide: 'contender' };
const diagnosticControl = { ...support, candidate_id: '7'.repeat(64), end_price: 56659, diagnosticSide: 'control' };

test('finite geometry uses exactly the two anchor endpoints', () => {
  assert.deepEqual(
    finiteSegmentCoordinates(support, timeToCoordinate, priceToCoordinate),
    { x1: 100, y1: 20, x2: 200, y2: 40 },
  );
});

test('visibility filters roles and hit testing uses finite segment tolerance', () => {
  const visibility = { support: true, resistance: false, anchors: false };
  assert.equal(candidateIsVisible(support, visibility), true);
  assert.equal(candidateIsVisible(resistance, visibility), false);
  assert.equal(
    hitTestCandidates([support, resistance], 150, 30, timeToCoordinate, priceToCoordinate, visibility),
    support,
  );
  assert.equal(
    hitTestCandidates([support], 150, 50, timeToCoordinate, priceToCoordinate, visibility),
    null,
  );
});

test('primitive batches all candidates and toggles anchors without changing geometry', () => {
  const primitive = new TrendlinePrimitive({ candidates: [support, resistance] });
  assert.equal(primitive.visibleCandidates().length, 2);
  primitive.setVisibility({ support: false, resistance: true, anchors: true });
  assert.deepEqual(primitive.visibleCandidates(), [resistance]);
  assert.equal(primitive.visibility.anchors, true);
  primitive.select(resistance.candidate_id);
  assert.equal(primitive.selectedCandidateId, resistance.candidate_id);
});

test('source contains one primitive and no extension/ray implementation', async () => {
  const source = await readFile(new URL('../src/trendline_primitive.ts', import.meta.url), 'utf8');
  assert.equal((source.match(/class TrendlinePrimitive/g) ?? []).length, 1);
  assert.doesNotMatch(source, /\b(extend|ray|forecast)\b/i);
});

test('diagnostic contender and control remain drawable with distinct styles', () => {
  assert.notEqual(candidateStrokeStyle(diagnosticContender), candidateStrokeStyle(diagnosticControl));
  assert.notDeepEqual(candidateLineDash(diagnosticContender), candidateLineDash(diagnosticControl));
  assert.notEqual(
    finiteSegmentCoordinates(diagnosticContender, timeToCoordinate, priceToCoordinate),
    null,
  );
  assert.notEqual(
    finiteSegmentCoordinates(diagnosticControl, timeToCoordinate, priceToCoordinate),
    null,
  );
});

test('diagnostic support visibility hides both lines and autoscale includes projections', () => {
  const primitive = new TrendlinePrimitive({ candidates: [diagnosticContender, diagnosticControl] });
  const autoscale = primitive.autoscaleInfo(0, 100);
  assert.ok(autoscale !== null);
  assert.ok(autoscale.priceRange !== null);
  assert.ok(autoscale.priceRange.minValue <= 51564.8676);
  assert.ok(autoscale.priceRange.maxValue >= 51564.8676);
  assert.equal(primitive.visibleCandidates().length, 2);
  primitive.setVisibility({ support: false, resistance: true, anchors: false });
  assert.deepEqual(primitive.visibleCandidates(), []);
  assert.equal(primitive.autoscaleInfo(0, 100), null);
});

test('non-diagnostic provider styles retain role defaults', () => {
  assert.equal(candidateStrokeStyle(support), '#65d6a5');
  assert.equal(candidateStrokeStyle(resistance), '#e8a36f');
  assert.deepEqual(candidateLineDash(support), []);
  assert.deepEqual(candidateLineDash(resistance), []);
});
