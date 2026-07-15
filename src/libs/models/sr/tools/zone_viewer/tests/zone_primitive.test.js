import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import {
  ZonePrimitive,
  ZoneRenderer,
  zoneDetail,
  zoneVisibleAt,
} from '../src/zone_primitive.js';

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

test('hitTest returns the Lightweight Charts primitive API shape', () => {
  const primitive = new ZonePrimitive({
    zones: [{ ...zone, render_kind: 'LINE' }],
    viewer: { show_terminal_by_default: false },
  });
  primitive.attached({
    chart: {
      timeScale() {
        return {
          timeToCoordinate(value) {
            return value === seconds(zone.visible_from) ? 10 : 200;
          },
          width() { return 640; },
        };
      },
    },
    series: {
      priceToCoordinate(value) {
        return value === zone.center ? 150 : null;
      },
    },
    requestUpdate() {},
  });

  assert.deepEqual(primitive.hitTest(20, 150), {
    externalId: 'zone-1',
    zOrder: 'bottom',
    itemType: 'primitive',
    detail: zoneDetail(zone),
  });
});

function seconds(value) {
  return Math.floor(new Date(value).getTime() / 1000);
}

function rendererFixture(zone) {
  const calls = [];
  const context = {
    globalAlpha: 1,
    lineWidth: 0,
    save() {},
    restore() {},
    beginPath() {},
    moveTo(...args) { calls.push({ name: 'moveTo', args }); },
    lineTo(...args) { calls.push({ name: 'lineTo', args }); },
    fillRect(...args) {
      calls.push({ name: 'fillRect', args, alpha: this.globalAlpha, lineWidth: this.lineWidth });
    },
    strokeRect(...args) {
      calls.push({ name: 'strokeRect', args, alpha: this.globalAlpha, lineWidth: this.lineWidth });
    },
    stroke() {
      calls.push({ name: 'stroke', args: [], alpha: this.globalAlpha, lineWidth: this.lineWidth });
    },
  };
  const source = {
    payload: {
      zones: [zone],
      viewer: {
        support_border_color: '#26a69a',
        support_fill_color: 'rgba(38, 166, 154, 0.18)',
        resistance_border_color: '#ef5350',
        resistance_fill_color: 'rgba(239, 83, 80, 0.18)',
        pending_border_color: '#f2c94c',
        terminal_opacity: 0.35,
        zone_line_width: 2,
      },
    },
    visibleZones() { return this.payload.zones; },
    chart: {
      timeScale() {
        return {
          timeToCoordinate(value) {
            return value === seconds(zone.visible_from) ? 10 : 200;
          },
        };
      },
    },
    series: {
      priceToCoordinate(value) {
        return { 99: 200, 100: 150, 101: 100 }[value] ?? null;
      },
    },
  };
  return {
    calls,
    context,
    target: {
      useMediaCoordinateSpace(callback) {
        callback({ context, mediaSize: { width: 640, height: 300 } });
      },
    },
    renderer: new ZoneRenderer(source),
  };
}

function assertFiniteGeometry(calls) {
  for (const call of calls.filter(({ name }) => (
    ['fillRect', 'strokeRect', 'moveTo', 'lineTo'].includes(name)
  ))) {
    assert.ok(call.args.every(Number.isFinite), `${call.name} has non-finite coordinates`);
  }
}

test('browser entry resolves standalone Lightweight Charts without bare fancy-canvas', async () => {
  const main = await readFile(new URL('../src/main.js', import.meta.url), 'utf8');
  const standalone = await readFile(
    new URL(
      '../node_modules/lightweight-charts/dist/lightweight-charts.standalone.production.mjs',
      import.meta.url,
    ),
    'utf8',
  );
  assert.match(
    main,
    /from ['"]\.\.\/node_modules\/lightweight-charts\/dist\/lightweight-charts\.standalone\.production\.mjs['"]/
  );
  assert.doesNotMatch(main, /lightweight-charts\.production\.mjs/);
  assert.doesNotMatch(main, /(?:from|import)\s*['"]fancy-canvas['"]/);
  assert.doesNotMatch(standalone, /(?:from|import)\s*['"]fancy-canvas['"]/);
});

test('BAND renderer uses direct media coordinates for live zones', () => {
  const fixture = rendererFixture({
    ...zone,
    render_kind: 'BAND',
  });
  fixture.renderer.draw(fixture.target);

  const fill = fixture.calls.find(({ name }) => name === 'fillRect');
  const stroke = fixture.calls.find(({ name }) => name === 'strokeRect');
  assert.deepEqual(fill.args, [10, 100, 630, 100]);
  assert.deepEqual(stroke.args, [10, 100, 630, 100]);
  assert.equal(fill.lineWidth, 2);
  assertFiniteGeometry(fixture.calls);
});

test('LINE renderer uses direct media coordinates and terminal opacity', () => {
  const fixture = rendererFixture({
    ...zone,
    render_kind: 'LINE',
    final_status: 'BROKEN',
    visible_until: '2024-01-04T00:00:00Z',
  });
  fixture.renderer.draw(fixture.target);

  const move = fixture.calls.find(({ name }) => name === 'moveTo');
  const line = fixture.calls.find(({ name }) => name === 'lineTo');
  const stroke = fixture.calls.find(({ name }) => name === 'stroke');
  assert.deepEqual(move.args, [10, 150]);
  assert.deepEqual(line.args, [200, 150]);
  assert.equal(stroke.alpha, 0.35);
  assert.equal(stroke.lineWidth, 2);
  assertFiniteGeometry(fixture.calls);
});
