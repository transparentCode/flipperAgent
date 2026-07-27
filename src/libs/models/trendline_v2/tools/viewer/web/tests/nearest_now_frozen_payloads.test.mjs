import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { validatePayload } from '../dist/contracts.js';
import {
  DEFAULT_FOCUS_SETTINGS,
  DEFAULT_NEAREST_SETTINGS,
  selectDisplayCandidates,
  selectFocusCandidates,
  selectNearestCandidates,
} from '../dist/candidate_filter.js';

const VERIFY = process.env.TRENDLINE_V2_VERIFY_NEAREST_VIEWER_EVIDENCE === '1';

const CASES = [
  {
    name: 'btcusdt_4h',
    path: '/tmp/trendline_v2_phase11v3_binance_viewer_acceptance/20260726/btcusdt_4h/viewer_bundle/chart_payload.json',
    payloadId: '7a8ab2cb09b2bb13350fbe8ac9a74d297e3509612c02d7ab716bd70354a9f476',
    fileSha256: '1c3411c15bd82621e5d9465ab7ec761c549647bffd46229e8bfd4cc15d047380',
    rawCandidates: 3077,
    supportAnchors: 163,
    resistanceAnchors: 173,
    focus: [10, 12],
    digests: {
      5: 'be17e3f7972d4fd78a992540c450ee477b57c546fadc95d017cfb4f547c0a7c2',
      10: '19f844d84414a54b359fac37b14d4ee0a64b54405262a74e78511b79b89e5b13',
    },
  },
  {
    name: 'ethusdt_1h',
    path: '/tmp/trendline_v2_phase11v3_binance_viewer_acceptance/20260726/ethusdt_1h/viewer_bundle/chart_payload.json',
    payloadId: '6ac982e0e72a7642496480f41b0d808dff79688011bad94c127a862815cfcf00',
    fileSha256: 'f4e85f7592ca47352441e819e972b6bd0f073c5cf60a0ac937c1743863d8bd84',
    rawCandidates: 2991,
    supportAnchors: 172,
    resistanceAnchors: 177,
    focus: [12, 9],
    digests: {
      5: 'e1e9c73933cc67505048530de81d39e433f4094f61d15be8a8081f35ca0b8046',
      10: '806f564106aeb55ac042cc43b39536e75883ed05a6f99b41e6d240e2fbf67c36',
    },
  },
  {
    name: 'suiusdt_30m',
    path: '/tmp/trendline_v2_phase11v3_binance_viewer_acceptance/20260726/suiusdt_30m/viewer_bundle/chart_payload.json',
    payloadId: '29e3773c81ff0d76835fddaac860875b957009f0cca62b64f3a2c1b4c7defccf',
    fileSha256: '3fef0042f55cf3e4d5d262d920f3e3fdba8ff95f1468ea3459d887beed42769f',
    rawCandidates: 2496,
    supportAnchors: 153,
    resistanceAnchors: 138,
    focus: [12, 12],
    digests: {
      5: 'f67d8eba580d179462ca5a380857c91cb0600e79c57b960de9b956c582e56860',
      10: 'd2d8f9e655333b7c1a8b4563c144aea19f7308e0aed40d7fecba4e6dd8cc1148',
    },
  },
  {
    name: 'solusdt_1d',
    path: '/tmp/trendline_v2_phase11v3_binance_viewer_acceptance/20260726/solusdt_1d/viewer_bundle/chart_payload.json',
    payloadId: 'ad7bd16ca7a2fc7bd41ea12cb4cf483da6e2a1b94658067dda44da292bb56902',
    fileSha256: '79a12086373a31d64133f2dbf2e3153ecf6514138f555439d1824c81c1b4f6dd',
    rawCandidates: 198,
    supportAnchors: 23,
    resistanceAnchors: 24,
    focus: [9, 8],
    digests: {
      5: '783011aae86e2f74dede9f09dc1a25326b6a560f7fd3fcdcb0c2fa6dfb16d267',
      10: '08c4a59cb61480900d7e13c1c0463141d9034939be708dd8efe56b50e1408502',
    },
  },
];

function ids(candidates) {
  return candidates.map((candidate) => candidate.candidate_id);
}

function digest(name, budget, support, resistance) {
  return createHash('sha256')
    .update(JSON.stringify({ case: name, budget, support, resistance }))
    .digest('hex');
}

async function verifyFrozenCase(frozen) {
  const bytes = await readFile(frozen.path);
  assert.equal(createHash('sha256').update(bytes).digest('hex'), frozen.fileSha256);
  const payload = validatePayload(JSON.parse(bytes));
  assert.equal(payload.payload_id, frozen.payloadId);
  assert.equal(payload.candidates.length, frozen.rawCandidates);

  const rawCandidates = payload.candidates;
  const rawIds = new Set(ids(rawCandidates));
  const rawSnapshot = JSON.stringify(rawCandidates);
  const lastCandle = payload.candles[payload.candles.length - 1];
  const supportAnchors = new Set(rawCandidates.filter((item) => item.role === 'support').map((item) => item.anchors[1].anchor_id));
  const resistanceAnchors = new Set(rawCandidates.filter((item) => item.role === 'resistance').map((item) => item.anchors[1].anchor_id));
  assert.equal(supportAnchors.size, frozen.supportAnchors);
  assert.equal(resistanceAnchors.size, frozen.resistanceAnchors);

  for (const budget of [5, 10]) {
    const selected = selectNearestCandidates(rawCandidates, lastCandle, { maxPerRole: budget });
    const support = selected.filter((item) => item.role === 'support');
    const resistance = selected.filter((item) => item.role === 'resistance');
    assert.equal(support.length, budget);
    assert.equal(resistance.length, budget);
    assert.ok(support.every((item) => rawIds.has(item.candidate_id) && item.role === 'support'));
    assert.ok(resistance.every((item) => rawIds.has(item.candidate_id) && item.role === 'resistance'));
    assert.equal(new Set(support.map((item) => item.anchors[1].anchor_id)).size, support.length);
    assert.equal(new Set(resistance.map((item) => item.anchors[1].anchor_id)).size, resistance.length);
    assert.equal(digest(frozen.name, budget, ids(support), ids(resistance)), frozen.digests[budget]);
    assert.deepEqual(
      ids(selected),
      ids(selectNearestCandidates([...rawCandidates].reverse(), lastCandle, { maxPerRole: budget })),
    );
    assert.deepEqual(ids(selected), ids(selectNearestCandidates(rawCandidates, lastCandle, { maxPerRole: budget })));
  }

  const focus = selectFocusCandidates(rawCandidates, payload.candles.length - 1, DEFAULT_FOCUS_SETTINGS);
  assert.deepEqual(
    [focus.filter((item) => item.role === 'support').length, focus.filter((item) => item.role === 'resistance').length],
    frozen.focus,
  );
  assert.deepEqual(
    ids(selectDisplayCandidates({
      mode: 'nearest',
      candidates: rawCandidates,
      lastCandle,
      lastCandlePosition: payload.candles.length - 1,
      nearestSettings: DEFAULT_NEAREST_SETTINGS,
    })),
    ids(selectNearestCandidates(rawCandidates, lastCandle, DEFAULT_NEAREST_SETTINGS)),
  );
  assert.strictEqual(selectDisplayCandidates({
    mode: 'all',
    candidates: rawCandidates,
    lastCandle,
    lastCandlePosition: payload.candles.length - 1,
  }), rawCandidates);
  assert.equal(JSON.stringify(rawCandidates), rawSnapshot);
}

for (const frozen of CASES) {
  test(`frozen nearest-now payload: ${frozen.name}`, { skip: !VERIFY }, async () => {
    await verifyFrozenCase(frozen);
  });
}
