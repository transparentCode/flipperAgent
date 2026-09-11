import test from 'node:test';
import assert from 'node:assert/strict';
import {
  TrendlinePrimitive,
  clipSegmentToHorizontalViewport,
  finiteSegmentCoordinates,
  roleVisible,
} from '../dist/trendline_primitive.js';

const HASH = 'a'.repeat(64);
const visibility = { support: true, resistance: false, lines: true, rays: true, pivots: true, signals: true };
const allVisible = { support: true, resistance: true, lines: true, rays: true, pivots: true, signals: true };

test('support visibility follows role', () => {
  assert.equal(roleVisible('support', visibility), true);
  assert.equal(roleVisible('resistance', visibility), false);
});

test('finite geometry maps both endpoints', () => {
  assert.deepEqual(
    finiteSegmentCoordinates(10, 20, 100, 110, (time) => time, (price) => price),
    [10, 100, 20, 110],
  );
});

test('finite geometry rejects unavailable coordinates', () => {
  assert.equal(finiteSegmentCoordinates(10, 20, 100, 110, () => null, (price) => price), null);
});

test('negative logical start clips to visible coordinates', () => {
  assert.deepEqual(
    finiteSegmentCoordinates(-10, 20, 100, 110, (logical) => logical, (price) => price, 0, 100),
    [0, 103.33333333333333, 20, 110],
  );
});

test('segment wholly before display is skipped', () => {
  assert.equal(
    finiteSegmentCoordinates(-20, -5, 100, 110, (logical) => logical, (price) => price, 0, 100),
    null,
  );
});

test('segment crossing left boundary is clipped by interpolation', () => {
  assert.deepEqual(
    clipSegmentToHorizontalViewport(-10, 100, 10, 120, 0, 100),
    [0, 110, 10, 120],
  );
});

test('primitive starts with all layers visible', () => {
  const primitive = new TrendlinePrimitive({ lines: [], rays: [], pivots: [], signals: [] });
  assert.deepEqual(primitive.visibility, allVisible);
});

test('primitive visibility toggles request redraw', () => {
  const primitive = new TrendlinePrimitive({ lines: [], rays: [], pivots: [], signals: [] });
  primitive.setVisibility({ ...visibility, lines: false });
  assert.equal(primitive.visibility.lines, false);
});

test('fitted-line and ray visibility remain independent', () => {
  const primitive = new TrendlinePrimitive({ lines: [], rays: [], pivots: [], signals: [] });
  primitive.setVisibility({ ...allVisible, lines: false, rays: true });
  assert.equal(primitive.visibility.lines, false);
  assert.equal(primitive.visibility.rays, true);
  primitive.setVisibility({ ...primitive.visibility, lines: true, rays: false });
  assert.equal(primitive.visibility.lines, true);
  assert.equal(primitive.visibility.rays, false);
});

test('primitive retains payload identity for audit layers', () => {
  const primitive = new TrendlinePrimitive({ replay_point_id: HASH, content_id: HASH, lines: [], rays: [], pivots: [], signals: [] });
  assert.equal(primitive.payload.replay_point_id, HASH);
});
