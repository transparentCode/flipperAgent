import test from 'node:test';
import assert from 'node:assert/strict';
import { validateDiagnosticPayload } from '../dist/contracts.js';

const HASH = 'a'.repeat(64);
const R4 = 'f4a95e118d52eec9ae60b447f08ca11a756908d7861772978b8f0393b0bbd2e2';
const R4_MANIFEST = '965b4741ec0f7305b8217dbc90d5c2bb31a6185e09b42c519bc404548c290a7e';
const R4_INVENTORY = '7fbd19fd1b828c09881df6236d2c3b8bdf7ae4bdfd4cd4b03d770c401ecd413c';
const R5 = 'b918a2102f82670da9fbd365daa9b35d7ec86d5bfb043db149b412f57b25f083';
const R5_MANIFEST = 'f5569cca5cafe8f4b598a8e4a9e1609fcefc70f89cc90078d21c8f5c0dabc917';
const R5_INVENTORY = '7fcde0786d367adb0dafbe9fe54349005e69d6cc33f14407477bee534a38d31e';
const RAW_SHA = '0fb88993e8ceed7b3812ec8fed895164b4fd00d1d392f5018f81aeea66dd4fe3';

function line(side, lineage, selection, reachable) {
  const geometry = {
    start_time: '2026-05-23T04:00:00Z',
    end_time: side === 'contender' ? '2026-06-04T00:00:00Z' : '2026-06-07T16:00:00Z',
    start_price: 74203.6,
    end_price: side === 'contender' ? 61344.8 : 61150.2,
  };
  const start = Date.parse(geometry.start_time) / 1000;
  const end = Date.parse(geometry.end_time) / 1000;
  const projection = 1780963200 + 96 * 3600;
  const projectionPrice = geometry.start_price + (geometry.end_price - geometry.start_price) * (projection - start) / (end - start);
  return {
    lineage_id: lineage,
    selection_id: selection,
    side,
    role: 'support',
    policy_id: 'joint_incumbent_near_v1',
    control_policy_id_or_null: side === 'contender' ? null : 'joint_nearest_projection_control_v1',
    fixed_geometry: geometry,
    anchors: [
      { time: start, price: geometry.start_price },
      { time: end, price: geometry.end_price },
    ],
    projection_time: projection,
    projection_price: projectionPrice,
    initial_distance_atr: side === 'contender' ? 5.6184 : 2.3826,
    geometry_projected_distance_atr_96h: side === 'contender' ? 9.0357 : 5.0310,
    reachable_at_96h: reachable,
    attribution_class: 'FULL_LINEAGE_SUBSTITUTION',
    cross_budget_class: 'PERSISTENT_THROUGH_BUDGET_3',
  };
}

function payload(overrides = {}) {
  const checkpoint = 1780963200;
  return {
    schema_version: 'trendline_v2_r5_diagnostic_viewer_payload_v1',
    payload_id: HASH,
    asset: 'BTCUSDT',
    timeframe: '4h',
    checkpoint_index: 5,
    checkpoint_observed_at: '2026-06-09T00:00:00Z',
    as_of: '2026-06-09T00:00:00Z',
    candles: [0, 1, 2].map((index) => ({
      time: checkpoint - (3 - index) * 14400,
      open: 63000,
      high: 63500,
      low: 62500,
      close: 63200,
      volume: 1,
    })),
    lines: [
      line('contender', '2a7613b64b8d70a79171f8599d0a2d744164d6da8d9e05551a7c1d120041d385', 'b'.repeat(64), false),
      line('control', 'a268b19fed5c2624f25612c5e9975c35b6177215872609e47f25781a309dea95', 'c'.repeat(64), true),
    ],
    r4_diagnostic_id: R4,
    r4_manifest_id: R4_MANIFEST,
    r4_inventory: R4_INVENTORY,
    r5_attribution_id: R5,
    r5_manifest_id: R5_MANIFEST,
    r5_inventory: R5_INVENTORY,
    raw_candle_path: 'datasets/btcusdt_4h/provider_result.json',
    raw_candle_sha256: RAW_SHA,
    cell_attribution: {
      cell_identity: ['joint_incumbent_near_v1', 1, 'joint_nearest_projection_control_v1', 'btcusdt_4h', 5, 'support', 96],
      one_sided_direction: 'control_only',
      attribution_class: 'FULL_LINEAGE_SUBSTITUTION',
      cross_budget_class: 'PERSISTENT_THROUGH_BUDGET_3',
    },
    ...overrides,
  };
}

test('accepts frozen diagnostic payload with two lines', () => {
  const result = validateDiagnosticPayload(payload());
  assert.deepEqual(result.lines.map((item) => item.side), ['contender', 'control']);
});

test('rejects wrong source identity, cell, lineage and post-checkpoint candle', () => {
  assert.throws(() => validateDiagnosticPayload(payload({ r4_diagnostic_id: HASH })), /source binding/);
  const wrongCell = payload();
  wrongCell.cell_attribution.one_sided_direction = 'contender_only';
  assert.throws(() => validateDiagnosticPayload(wrongCell), /cell identity/);
  const wrongLine = payload();
  wrongLine.lines[0].lineage_id = HASH;
  assert.throws(() => validateDiagnosticPayload(wrongLine), /lineage/);
  const future = payload();
  future.candles.push({ time: 1780963200, open: 63000, high: 63500, low: 62500, close: 63200, volume: 1 });
  assert.throws(() => validateDiagnosticPayload(future), /after checkpoint/);
});
