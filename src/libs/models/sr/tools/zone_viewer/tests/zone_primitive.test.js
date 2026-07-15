import test from 'node:test';
import assert from 'node:assert/strict';
import { zoneDetail, zoneVisibleAt } from '../src/zone_primitive.js';

const zone = {
  zone_id: 'zone-1',
  side: 'SUPPORT',
  final_status: 'ACTIVE',
  lower_bound: 99,
  center: 100,
  upper_bound: 101,
  visible_from: '2024-01-03T00:00:00Z',
  visible_until: null,
  touch_count: 2,
  fakeout_count: 1,
  pending_breach_count: 0,
};

test('live zones begin at visible_from and extend through the viewport', () => {
  assert.equal(zoneVisibleAt(zone, '2024-01-02T23:59:59Z'), false);
  assert.equal(zoneVisibleAt(zone, '2024-01-03T00:00:00Z'), true);
  assert.equal(zoneVisibleAt(zone, '2025-01-01T00:00:00Z'), true);
});

test('terminal zones stop at their frozen visible_until', () => {
  const terminal = {
    ...zone,
    final_status: 'BROKEN',
    visible_until: '2024-01-04T00:00:00Z',
  };
  assert.equal(zoneVisibleAt(terminal, '2024-01-04T00:00:00Z'), true);
  assert.equal(zoneVisibleAt(terminal, '2024-01-04T00:00:01Z'), false);
});

test('hover detail contains only payload fields', () => {
  assert.deepEqual(zoneDetail(zone), {
    zone_id: 'zone-1',
    side: 'SUPPORT',
    final_status: 'ACTIVE',
    lower_bound: 99,
    center: 100,
    upper_bound: 101,
    visible_from: '2024-01-03T00:00:00Z',
    visible_until: null,
    touch_count: 2,
    fakeout_count: 1,
    pending_count: 0,
  });
});
