import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import {
  aggregateCandidateMarkers,
  applyInspectionResult,
  asOfInspection,
  bandHitExternalId,
  bandHitMemberIds,
  bandPriceRange,
  candleRows,
  chartTime,
  coordinateForLoadedTime,
  createRequestGate,
  filterKernelRows,
  finiteNumber,
  historyLineageCounts,
  intervalData,
  kernelMatchesConfiguration,
  latestDisplayedCutoff,
  labelRectanglesForDisplay,
  lineageLabelCandidates,
  navigationState,
  overlappingBandMemberIds,
  pixelBandsFromProjected,
  pixelHistoryBands,
  projectBands,
  projectHistoryLifetimes,
  selectLineageLabels,
  touchHighlight,
  transitionMarkers,
  validateSelectedPayload,
  visiblePriceRegions,
} from '../dist/payload_utils.js';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

test('viewer is pinned to lightweight-charts 5.2.1 and uses local assets', async () => {
  const packageJson = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
  assert.equal(packageJson.dependencies['lightweight-charts'], '5.2.1');
  const html = await readFile(join(root, 'index.html'), 'utf8');
  const js = await readFile(join(root, 'dist/main.js'), 'utf8');
  assert.doesNotMatch(html + js, /https?:\/\/(?!www\.tradingview\.com)/);
  assert.match(js, /\/vendor\/lightweight-charts\.mjs/);
  assert.match(
    html,
    /<a href="https:\/\/www\.tradingview\.com\/" rel="noopener noreferrer" target="_blank">TradingView Lightweight Charts<\/a>/,
  );
});

test('hidden overlays stay closed and volume is created in the native lower pane', async () => {
  const html = await readFile(join(root, 'index.html'), 'utf8');
  const styles = await readFile(join(root, 'styles.css'), 'utf8');
  const js = await readFile(join(root, 'dist/main.js'), 'utf8');

  assert.match(styles, /^\[hidden\]\s*\{\s*display:\s*none\s*!important;\s*\}/m);
  assert.match(html, /<aside id="inspector"[^>]*\shidden>/);
  assert.match(js, /let inspectionVisible = null;/);
  assert.doesNotMatch(js, /Unbound market|local evidence/);
  assert.match(js, /const initialWidth = Math\.max\(1, host\.clientWidth\);/);
  assert.match(js, /const initialHeight = Math\.max\(1, host\.clientHeight\);/);
  assert.match(js, /width: initialWidth,\s*height: initialHeight,\s*autoSize: false/);
  assert.doesNotMatch(js, /autoSize:\s*true/);
  assert.match(js, /function initializeDisplayPolicy\(\)/);
  assert.match(js, /currentMode = display\.initial_mode;/);
  assert.match(js, /zonesVisible = display\.show_zones;/);
  assert.match(js, /historyVisible = display\.show_history;/);
  assert.match(js, /inspectionVisible = display\.show_inspector;/);
  assert.match(js, /volumePaneFraction = Number\(display\.volume_pane_fraction\);/);
  assert.equal((js.match(/new ResizeObserver\s*\(/g) || []).length, 1);
  assert.match(js, /chart\.resize\(width, height, true\)/);
  assert.match(js, /const volumePane = chart\.panes\(\)\[1\];/);
  assert.match(js, /volumePane\.setHeight\(Math\.max\(minVolumePaneHeight, Math\.round\(height \* volumePaneFraction\)\)\)/);
  assert.ok(
    js.indexOf('chart.resize(width, height, true)') > js.indexOf('volumePane.setHeight('),
    'final forced resize must follow volume pane sizing',
  );
  assert.match(js, /renderer: \(\) => \(\{\s*draw: \(\) => \{\},\s*drawBackground:/);
  assert.match(js, /isBackground: true/);
  assert.match(js, /volumeSeries\s*=\s*chart\.addSeries\(HistogramSeries,[\s\S]*?\}, 1\);/);
  assert.match(js, /volumeSeries\.priceScale\(\)\.applyOptions\(\{ scaleMargins: \{ top: \.08, bottom: \.05 \} \}\)/);
  assert.doesNotMatch(js, /volumeSeries\.moveToPane\s*\(/);
});

test('mode-local inspection and inspector controls stay bounded to display evidence', async () => {
  const html = await readFile(join(root, 'index.html'), 'utf8');
  const js = await readFile(join(root, 'dist/main.js'), 'utf8');
  const utils = await readFile(join(root, 'dist/payload_utils.js'), 'utf8');
  const styles = await readFile(join(root, 'styles.css'), 'utf8');

  assert.match(js, /function latestDisplayedInspectionCutoff\(\)/);
  assert.match(js, /return latestDisplayedCutoff\(activeChartRows\(\), pane\.inspection\.as_of\)/);
  assert.match(js, /let overlayInspection = null;/);
  assert.match(js, /const activeZones = overlayInspection\?\.active_zones/);
  assert.match(js, /currentInspection = overlayInspection;/);
  assert.match(js, /const inspectionCutoff = currentInspection\?\.cutoff \|\| requestedCutoff \|\| pane\.inspection\.as_of;/);
  assert.match(js, /const bandsCutoff = overlayInspection\?\.cutoff;/);
  assert.match(js, /currentInspection\?\.cutoff && bandsCutoff && currentInspection\.cutoff !== bandsCutoff/);
  assert.match(js, /UTC inspect \$\{formatUtc\(inspectionCutoff\)\} · bands \$\{formatUtc\(bandsCutoff\)\}/);
  assert.match(js, /UTC as-of \$\{formatUtc\(inspectionCutoff\)\}/);
  assert.match(js, /if \(!inspectionVisible \|\| !overlayInspection\) return;/);
  assert.match(js, /loadInspection\(cutoff, \{ passive: true \}\)/);
  assert.match(js, /function clearDetailSelection\(\)[\s\S]*?currentDetail = null;[\s\S]*?updateMarkers\(\)/);
  assert.match(js, /function closeInspector\(\)[\s\S]*?cancelHoverInspection\(\)[\s\S]*?clearDetailSelection\(\)[\s\S]*?restoreOverlayInspection\(\)/);
  assert.match(js, /\$\('#close-inspector'\)\.addEventListener\('click',[\s\S]*?closeInspector\(\)/);
  assert.match(js, /event\.key === 'Escape'[\s\S]*?closeInspector\(\)/);
  assert.match(js, /autoscaleInfo\(startTimePoint, endTimePoint\)\s*\{/);
  assert.match(js, /autoscaleInfo\(startTimePoint, endTimePoint\)\s*\{[\s\S]*?if \(!this\.state\.visible\) return null;/);
  assert.match(js, /bandPriceRange\(\s*this\.projectedBands,\s*this\.candleTimes/);
  assert.match(js, /overlappingBandMemberIds\(this\.rectangles\(\), x, y\)/);
  assert.match(js, /function updateLineageStatus\(\)/);
  assert.match(js, /const regionLabel = regions === 0/);
  assert.match(js, /0 visible price regions in window/);
  assert.match(js, /\$\{regions\} visible price regions/);
  assert.match(js, /\$\{activeZones\.length\} active lineages · \$\{shown\} shown/);
  assert.match(js, /historyRequests/);
  assert.match(js, /lineage_history\.json/);
  assert.match(js, /historyRequests\.isCurrent\(request\.id\)/);
  assert.match(js, /historyError = 'History unavailable'/);
  assert.match(js, /historyPayload = null;/);
  assert.match(js, /void loadHistoryForOverlay\(\)/);
  assert.match(js, /historyRequests\.cancel\(\)/);
  assert.match(js, /openLineageLedger/);
  assert.match(js, /\$\('#lineage-status'\)\.addEventListener\('click', openLineageLedger\)/);
  assert.match(js, /zoneList\.id = 'active-zone-ledger'/);
  assert.match(js, /compactIdentifier\(zone\.zone_id\)/);
  assert.match(js, /subscribeVisibleLogicalRangeChange/);
  assert.match(js, /const historicalZones = Array\.isArray\(historyPayload\.zones\) \? historyPayload\.zones : \[\];/);
  assert.match(js, /const renderedRectangles = zonesVisible \? bandPrimitive\?\.rectangles\?\.\(\) \|\| \[\] : \[\];/);
  assert.match(js, /const historyCounts = historyLineageCounts\([\s\S]*renderedRectangles,[\s\S]*configuredKernelIds,[\s\S]*visible: zonesVisible/);
  assert.match(js, /\$\{historyCounts\.total\} historical lineages · \$\{historyCounts\.enabled\} enabled · \$\{historyCounts\.inWindow\} in window/);
  assert.doesNotMatch(js, /historyPayload\.lifecycle_intervals\.length/);
  assert.match(js, /if \(!historyVisible \|\| !overlayInspection\)/);
  assert.match(html, /id="history-button"/);
  assert.match(html, /id="kernels-button"/);
  assert.match(html, /id="lineage-status"[^>]*type="button"/);
  assert.doesNotMatch(html, /id="band-status"/);
  assert.doesNotMatch(html, /Display grouping/);
  assert.match(html, /Exact lineage geometry · overlap is not consolidation · no strength\/probability implied/);
  assert.match(styles, /\.history-swatch \{ border: 1px solid/);
  assert.match(utils, /display_open: true/);
  assert.match(utils, /return bands\s*\.map\(\(zone\) => toPixelBand/);
  assert.doesNotMatch(utils, /aggregateBandRectangles/);
  assert.match(js, /chart\.resize\(width, height, true\);\s*bandPrimitive\?\.updateAllViews\(\);/);
  assert.match(js, /loadInspection\(latestDisplayedInspectionCutoff\(\), \{ open: false \}\)/);
  assert.match(js, /loadInspection\(latestDisplayedInspectionCutoff\(\), \{ open: true \}\)/);
  assert.match(js, /function switchMode\(mode\)/);
  assert.match(js, /currentInspection = null;/);
  assert.match(js, /initializeKernelFilters\(\)/);
  assert.match(js, /function renderKernelControls\(\)/);
  assert.match(js, /filterKernelRows\(rows, enabledKernelIds, configuredKernelIds\)/);
  assert.match(js, /input\.addEventListener\('change',[\s\S]*?updateToolbar\(\)[\s\S]*?updateMarkers\(\)/);
  assert.match(js, /currentInspection\.touch_episodes/);
  assert.match(js, /section\('Active touches'/);
  assert.match(utils, /projectHistoryLifetimes/);
  assert.match(utils, /export function kernelMatchesConfiguration/);
  assert.match(utils, /filterKernelRows\([\s\S]*kernelMatchesConfiguration/);
  assert.match(utils, /pixelHistoryBands\([\s\S]*kernelMatchesConfiguration/);
  assert.match(utils, /export function historyLineageCounts/);
  assert.match(utils, /historyLineageCounts\([\s\S]*filterKernelRows\(/);
  assert.match(utils, /export function coordinateForLoadedTime/);
  assert.doesNotMatch(utils, /logicalIndexForTime|logicalToCoordinate/);
  assert.match(utils, /if \(times\.some\(\(time\) => !Number\.isFinite\(time\)\)\) return \[\];/);
  const coordinateHelperStart = utils.indexOf('export function coordinateForLoadedTime');
  const historyProjectorStart = utils.indexOf('export function pixelHistoryBands', coordinateHelperStart);
  assert.doesNotMatch(utils.slice(coordinateHelperStart, historyProjectorStart), /\.every\(/, 'coordinate lookup stays logarithmic per boundary');
  const drawStart = js.indexOf('draw(target) {');
  const hitTestStart = js.indexOf('hitTest(', drawStart);
  assert.ok(drawStart >= 0 && hitTestStart > drawStart);
  const drawSource = js.slice(drawStart, hitTestStart);
  assert.equal((drawSource.match(/context\.fill\(\);/g) || []).length, 1, 'coverage helper fills once per side invocation');
  assert.equal((drawSource.match(/paintHistoricalCoverage\('/g) || []).length, 2, 'coverage helper is invoked for both sides');
  assert.match(drawSource, /paintHistoricalCoverage\('SUPPORT'/);
  assert.match(drawSource, /paintHistoricalCoverage\('RESISTANCE'/);
  assert.match(drawSource, /strokeHistoricalCaps\('SUPPORT'/);
  assert.match(drawSource, /strokeHistoricalCaps\('RESISTANCE'/);
  assert.match(js, /lineageLabelCandidates/);
  assert.match(js, /const currentRectangles = this\.activeRectangles\(\);/);
  assert.match(js, /const currentLabelRectangles = currentRectangles;/);
  assert.match(js, /labelRectanglesForDisplay\(\s*currentLabelRectangles,\s*history,\s*this\.state\.selectedZoneId,\s*\)/);
  assert.match(js, /lineageLabelCandidates\(labelRectangles, this\.state\.selectedZoneId\)/);
  assert.doesNotMatch(js, /lineageLabelCandidates\(rectangles, this\.state\.selectedZoneId\)/);
  assert.match(js, /selectLineageLabels/);
  assert.match(js, /const history = this\.historyRectangles\(\);[\s\S]*const historicalRectangles = history\.filter\(\(rectangle\) => rectangle\.historical === true\);[\s\S]*this\.activeRectangles\(\)/);
  assert.match(js, /rectangle\.intervals\.length <= 1/);
  assert.match(js, /context\.moveTo\(rectangle\.x2, rectangle\.top\)/);
  assert.match(js, /context\.lineWidth = 2/);
  assert.match(js, /currentDetail = result;\s*updateBands\(\);\s*updateMarkers\(\)/);
  assert.match(js, /filterKernelRows\(\s*state\.zones,\s*state\.enabledKernelIds,\s*state\.configuredKernelIds,\s*\)/);
  assert.match(js, /id = 'kernel-controls'/);
  assert.match(js, /kernels-button/);
  assert.match(js, /function bandMemberCard\(memberId\)/);
  assert.match(js, /section\('Band members'/);
  assert.match(js, /loadZoneDetail\(memberId, overlayInspection\?\.cutoff\)/);
  assert.match(js, /loadZoneDetail\(zone\.zone_id, currentInspection\?\.cutoff\)/);
  assert.match(js, /async function loadZoneDetail\(zoneId, cutoff\)/);
  assert.match(js, /currentDetail = result;\s*updateBands\(\);\s*updateMarkers\(\)/);
  assert.match(js, /memberIdsForHit\(externalId\)/);
  assert.match(utils, /size: \.6/);
});

test('viewer boundary accepts plain decimal/UTC values and volume data', () => {
  assert.equal(finiteNumber('100.25', 'open'), 100.25);
  assert.equal(chartTime('2024-01-01T00:15:00.000000+00:00', 'close'), 1704068100);
  assert.deepEqual(candleRows([{
    bar_close_at: '2024-01-01T00:15:00.000000+00:00',
    open: '100', high: '101', low: '99', close: '100.5', volume: '12',
  }], 'formation'), [{
    time: 1704068100, open: 100, high: 101, low: 99, close: 100.5, volume: 12,
  }]);
  assert.throws(() => finiteNumber('NaN', 'close'), /not finite/);
  assert.throws(() => chartTime('not-a-time', 'close'), /valid UTC time/);
  assert.throws(() => chartTime('2024-01-01T00:15:00.000000+05:30', 'close'), /valid UTC time/);
});

test('band hit identities round-trip every sorted member and keep marker dots compact', () => {
  const memberIds = ['z1', 'z2'];
  assert.deepEqual(bandHitMemberIds(bandHitExternalId(memberIds)), memberIds);
  assert.deepEqual(bandHitMemberIds(bandHitExternalId(['z1'])), ['z1']);
  const marker = aggregateCandidateMarkers([{
    available_at: '1970-01-01T00:00:20.000000+00:00', side: 'SUPPORT', kernel_id: 'k', count: 1,
  }])[0];
  assert.equal(marker.size, .6);
});

test('individual bands stay separate, open final-candle zones reach the pane edge, and hits keep overlaps', () => {
  const candles = [{ time: 10 }, { time: 20 }];
  const timeScale = {
    timeToCoordinate: (time) => time - 10,
    width: () => 100,
  };
  const series = { priceToCoordinate: (price) => price };
  const projected = [
    { zone_id: 'z2', side: 'SUPPORT', lifecycle: 'ACTIVE', start_time: 20, end_time: 20, display_open: true, lower: 90, upper: 100 },
    { zone_id: 'z1', side: 'SUPPORT', lifecycle: 'ACTIVE', start_time: 10, end_time: 20, display_open: true, lower: 95, upper: 105 },
  ];
  const rectangles = pixelBandsFromProjected(projected, candles, timeScale, series);
  assert.equal(rectangles.length, 2);
  assert.deepEqual(rectangles.map((rectangle) => rectangle.zone_id), ['z2', 'z1']);
  assert.deepEqual(rectangles.map((rectangle) => rectangle.x2), [100, 100]);
  assert.deepEqual(overlappingBandMemberIds(rectangles, 50, 95), ['z1', 'z2']);
  assert.deepEqual(overlappingBandMemberIds(rectangles, 50, 102), ['z1']);
  assert.deepEqual(overlappingBandMemberIds(rectangles, 150, 95), []);
  assert.deepEqual(pixelBandsFromProjected(
    [projected[0]],
    candles,
    { timeToCoordinate: (time) => time - 10, width: () => 0 },
    series,
  ), []);
  assert.deepEqual(pixelBandsFromProjected(
    [projected[0]],
    candles,
    { timeToCoordinate: (time) => time + 100, width: () => 100 },
    series,
  ), []);
  assert.deepEqual(pixelBandsFromProjected(
    [{ ...projected[0], lower: 110, upper: 90 }],
    candles,
    timeScale,
    series,
  ), []);
});

test('historical bands interpolate exact between-candle lifetime boundaries', () => {
  const candles = [{ time: 10 }, { time: 20 }, { time: 30 }];
  const history = {
    zones: [
      { zone_id: 'z', side: 'SUPPORT', lower: 90, upper: 100 },
      {
        zone_id: 'late', side: 'RESISTANCE', lower: 110, upper: 120,
        available_at: '1970-01-01T00:00:20.000000+00:00',
      },
    ],
    lifecycle_intervals: [
      {
        zone_id: 'z', lifecycle: 'TOUCHED',
        entered_at: '1970-01-01T00:00:15.000000+00:00',
        exited_at: '1970-01-01T00:00:25.000000+00:00',
      },
      {
        zone_id: 'z', lifecycle: 'ACTIVE',
        entered_at: '1970-01-01T00:00:20.000000+00:00',
        exited_at: null,
      },
      {
        zone_id: 'late', lifecycle: 'ACTIVE',
        entered_at: '1970-01-01T00:00:15.000000+00:00',
        exited_at: null,
      },
    ],
  };
  const timeScale = {
    timeToCoordinate: (time) => time * 3 + 7,
    width: () => 100,
  };
  const series = { priceToCoordinate: (price) => price };
  const rectangles = pixelHistoryBands(history, candles, timeScale, series);
  assert.equal(rectangles.length, 3);
  assert.deepEqual([rectangles[0].x1, rectangles[0].x2], [52, 82]);
  assert.equal(rectangles[0].historical, true);
  assert.deepEqual([rectangles[1].x1, rectangles[1].x2], [67, 100]);
  assert.equal(rectangles[1].historical, false);
  const lateRectangle = rectangles.find((rectangle) => rectangle.zone_id === 'late');
  assert.ok(lateRectangle);
  assert.equal(lateRectangle.x1, 67, 'availability must clip the drawable start');
});

test('history boundaries use real candle coordinates, clip the domain, and fail closed on missing coordinates', () => {
  const candles = [{ time: 10 }, { time: 20 }, { time: 35 }];
  const timeScale = {
    timeToCoordinate: (time) => 100 + time * 2,
    logicalToCoordinate: () => { throw new Error('logical coordinates are not a valid history domain'); },
    width: () => 300,
  };
  assert.equal(coordinateForLoadedTime(candles.map((candle) => candle.time), timeScale, 10), 120);
  assert.equal(coordinateForLoadedTime(candles.map((candle) => candle.time), timeScale, 35), 170);
  assert.equal(coordinateForLoadedTime(candles.map((candle) => candle.time), timeScale, 15), 130);
  assert.equal(coordinateForLoadedTime(candles.map((candle) => candle.time), timeScale, 30), 160);
  assert.equal(coordinateForLoadedTime(candles.map((candle) => candle.time), timeScale, 5), null);
  assert.equal(coordinateForLoadedTime(candles.map((candle) => candle.time), timeScale, 40), null);
  assert.equal(coordinateForLoadedTime([10, Number.NaN, 35], timeScale, 15), null, 'malformed bracket time fails closed');
  assert.equal(coordinateForLoadedTime([100, 200, 300], { timeToCoordinate: (time) => time + 5 }, 150), 155);

  const at = (seconds) => `1970-01-01T00:00:${String(seconds).padStart(2, '0')}.000000+00:00`;
  const project = (entered, exited, scale = timeScale, sourceCandles = candles) => pixelHistoryBands(
    {
      zones: [{ zone_id: 'z', source_timeframe: '1d', available_at: at(0), side: 'SUPPORT', kernel_id: 'k', lower: 90, upper: 100 }],
      lifecycle_intervals: [{ zone_id: 'z', lifecycle: 'ACTIVE', entered_at: at(entered), exited_at: exited === null ? null : at(exited) }],
    },
    sourceCandles,
    scale,
    { priceToCoordinate: (price) => price },
  );
  assert.deepEqual([project(15, 30)[0].x1, project(15, 30)[0].x2], [130, 160]);
  assert.deepEqual([project(5, 15)[0].x1, project(5, 15)[0].x2], [120, 130], 'pre-domain starts clip to the first candle coordinate');
  assert.deepEqual([project(20, 40)[0].x1, project(20, 40)[0].x2], [140, 170], 'post-domain closed exits clip to the last candle coordinate');
  assert.equal(project(40, 50).length, 0, 'wholly out-of-domain closed lifetimes are omitted');
  assert.deepEqual([project(20, null)[0].x1, project(20, null)[0].x2], [140, 300], 'open lifetimes retain the pane-right horizon');
  const shifted = project(15, 30, { timeToCoordinate: (time) => 200 + time * 2, width: () => 400 });
  assert.deepEqual([shifted[0].x1, shifted[0].x2], [230, 260], 'coordinates recompute after a time-scale shift');
  const missingBracket = project(15, 30, {
    timeToCoordinate: (time) => time === 20 ? null : 100 + time * 2,
    width: () => 300,
  });
  assert.equal(missingBracket.length, 0, 'a missing bracketing coordinate fails closed');
  const nonFiniteBracket = project(15, 30, {
    timeToCoordinate: (time) => time === 20 ? Number.NaN : 100 + time * 2,
    width: () => 300,
  });
  assert.equal(nonFiniteBracket.length, 0, 'a non-finite bracketing coordinate fails closed');
  assert.equal(
    project(15, 30, timeScale, [{ time: 10 }, { time: Number.NaN }, { time: 35 }]).length,
    0,
    'a malformed candle domain fails closed before boundary lookup',
  );
});

test('history lifetime projection coalesces exact per-zone adjacency and diagnoses chronology', () => {
  const zones = ['z1', 'z2', 'z3', 'z4', 'z5'].map((zone_id) => ({
    zone_id,
    available_at: '1970-01-01T00:00:05.000000+00:00',
    source_timeframe: '1d',
    side: 'SUPPORT',
    kernel_id: 'k',
    center: '100',
    lower: '99',
    upper: '101',
  }));
  const at = (seconds) => `1970-01-01T00:00:${String(seconds).padStart(2, '0')}.000000+00:00`;
  const history = {
    zones,
    lifecycle_intervals: [
      { zone_id: 'z1', lifecycle: 'ACTIVE', entered_at: at(10), exited_at: at(20) },
      { zone_id: 'z1', lifecycle: 'TOUCHED', entered_at: at(20), exited_at: at(30) },
      { zone_id: 'z1', lifecycle: 'BREAK_PENDING', entered_at: at(35), exited_at: null },
      { zone_id: 'z2', lifecycle: 'ACTIVE', entered_at: at(10), exited_at: at(30) },
      { zone_id: 'z3', lifecycle: 'ACTIVE', entered_at: at(10), exited_at: at(25) },
      { zone_id: 'z3', lifecycle: 'TOUCHED', entered_at: at(20), exited_at: at(30) },
      { zone_id: 'z4', lifecycle: 'ACTIVE', entered_at: at(10), exited_at: null },
      { zone_id: 'z4', lifecycle: 'TOUCHED', entered_at: at(20), exited_at: at(30) },
      { zone_id: 'z4', lifecycle: 'BROKEN', entered_at: at(30), exited_at: null },
      { zone_id: 'z5', lifecycle: 'ACTIVE', entered_at: at(30), exited_at: at(20) },
    ],
  };
  const lifetimes = projectHistoryLifetimes(history);
  const z1 = lifetimes.filter((lifetime) => lifetime.zone_id === 'z1');
  assert.equal(z1.length, 2);
  assert.deepEqual([z1[0].start_time, z1[0].end_time], [10, 30]);
  assert.deepEqual(z1[0].boundary_times, [20]);
  assert.deepEqual(z1[0].intervals.map((interval) => interval.lifecycle), ['ACTIVE', 'TOUCHED']);
  assert.deepEqual([z1[1].start_time, z1[1].end_time], [35, null]);
  assert.equal(lifetimes.filter((lifetime) => lifetime.zone_id === 'z2').length, 1);
  assert.equal(lifetimes.filter((lifetime) => lifetime.zone_id === 'z3').length, 2);
  assert.ok(lifetimes.filter((lifetime) => lifetime.zone_id === 'z3').every((lifetime) => lifetime.diagnostics.includes('overlapping_intervals')));
  assert.equal(lifetimes.filter((lifetime) => lifetime.zone_id === 'z4').length, 2);
  assert.ok(lifetimes.filter((lifetime) => lifetime.zone_id === 'z4').every((lifetime) => lifetime.diagnostics.includes('open_interval_precedes_later_interval')));
  assert.equal(lifetimes.filter((lifetime) => lifetime.zone_id === 'z5').length, 1);
  assert.deepEqual(lifetimes.find((lifetime) => lifetime.zone_id === 'z5').diagnostics, ['invalid_interval']);
  assert.ok(lifetimes.every((lifetime) => lifetime.zone_id !== 'z4' || !lifetime.intervals.some((interval) => interval.lifecycle === 'BROKEN')));
});

test('history lifetime geometry keeps availability, open horizons, and configured kernel filters causal', () => {
  const history = {
    zones: [
      { zone_id: 'known', available_at: '1970-01-01T00:00:20.000000+00:00', source_timeframe: '1d', side: 'SUPPORT', kernel_id: 'known', center: 100, lower: 99, upper: 101 },
      { zone_id: 'unknown', available_at: '1970-01-01T00:00:10.000000+00:00', source_timeframe: '1d', side: 'RESISTANCE', kernel_id: 'new_kernel', center: 110, lower: 109, upper: 111 },
    ],
    lifecycle_intervals: [
      { zone_id: 'known', lifecycle: 'ACTIVE', entered_at: '1970-01-01T00:00:10.000000+00:00', exited_at: null },
      { zone_id: 'unknown', lifecycle: 'ACTIVE', entered_at: '1970-01-01T00:00:10.000000+00:00', exited_at: null },
    ],
  };
  const candles = [{ time: 10 }, { time: 20 }, { time: 30 }];
  const timeScale = { timeToCoordinate: (time) => time * 3 + 7, width: () => 100 };
  const series = { priceToCoordinate: (price) => price };
  const rectangles = pixelHistoryBands(history, candles, timeScale, series, {
    enabledKernelIds: new Set(),
    configuredKernelIds: new Set(['known']),
  });
  assert.deepEqual(rectangles.map((rectangle) => rectangle.zone_id), ['unknown']);
  assert.equal(rectangles[0].x1, 37);
  const knownLifetimes = projectHistoryLifetimes(history).find((lifetime) => lifetime.zone_id === 'known');
  assert.equal(knownLifetimes.start_time, 20, 'lifetime starts no earlier than availability');
  assert.equal(knownLifetimes.end_time, null, 'open history retains no invented exit');
});

test('history lifetime projection never coalesces the same ID across source timeframes', () => {
  const zone = (source_timeframe) => ({
    zone_id: 'shared-id', source_timeframe, available_at: '1970-01-01T00:00:10.000000+00:00',
    side: 'SUPPORT', kernel_id: 'k', center: 100, lower: 99, upper: 101,
  });
  const history = {
    zones: [zone('1d'), zone('4h')],
    lifecycle_intervals: [
      { zone_id: 'shared-id', source_timeframe: '1d', lifecycle: 'ACTIVE', entered_at: '1970-01-01T00:00:10.000000+00:00', exited_at: '1970-01-01T00:00:20.000000+00:00' },
      { zone_id: 'shared-id', source_timeframe: '4h', lifecycle: 'TOUCHED', entered_at: '1970-01-01T00:00:20.000000+00:00', exited_at: '1970-01-01T00:00:30.000000+00:00' },
    ],
  };
  const lifetimes = projectHistoryLifetimes(history);
  assert.equal(lifetimes.length, 2);
  assert.deepEqual(lifetimes.map((lifetime) => lifetime.source_timeframe), ['1d', '4h']);
});

test('lineage labels use owned facts, neutral overlap counts, deterministic order, and collision LOD', () => {
  const rectangles = [
    { zone_id: 'z2', source_timeframe: '1d', side: 'RESISTANCE', kernel_id: 'plateau_sweep_reclaim', center: 120, lower: 119, upper: 121, x1: 10, x2: 80, top: 20, bottom: 30, historical: true },
    { zone_id: 'z1', source_timeframe: '1d', side: 'SUPPORT', kernel_id: 'previous_period_anchor', center: 100, lower: 99, upper: 101, x1: 0, x2: 60, top: 10, bottom: 25, historical: true },
    { zone_id: 'z3', source_timeframe: '1d', side: 'SUPPORT', kernel_id: 'previous_period_anchor', center: 90, lower: 89, upper: 91, x1: 120, x2: 160, top: 50, bottom: 60, historical: false },
  ];
  const neutral = lineageLabelCandidates(rectangles);
  assert.equal(neutral[0].full_text, '2 lineages');
  assert.equal(neutral[0].compact_text, '2 lineages');
  assert.equal(neutral[0].member_ids.join(','), 'z1,z2');
  assert.match(neutral[1].full_text, /1d · S · previous period anchor · 90/);
  const selected = lineageLabelCandidates(rectangles, 'z1');
  assert.equal(selected[0].selected, true);
  assert.match(selected[0].full_text, /1d · S · previous period anchor · 99-101 · z1/);
  const mixedTimeframe = lineageLabelCandidates([
    { ...rectangles[0], source_timeframe: '4h' },
    { ...rectangles[1], source_timeframe: '1d' },
  ]);
  assert.equal(mixedTimeframe.length, 2, 'label components remain source-timeframe isolated');
  const accepted = selectLineageLabels([
    { selected: true, full_text: 'selected label', compact_text: 'selected', x: 0, x2: 80, y: 20 },
    { selected: false, full_text: 'overlapping label', compact_text: 'overlap', x: 5, x2: 20, y: 20 },
    { selected: false, full_text: 'fits', compact_text: 'fit', x: 90, x2: 120, y: 55 },
  ], { width: 130, height: 80, measureText: (value) => value.length });
  assert.deepEqual(accepted.map((label) => label.text), ['selected label', 'fits']);
  assert.ok(accepted.every((label, index) => accepted.every((other, otherIndex) => index === otherIndex || label.x >= other.x + other.width || other.x >= label.x + label.width || label.y >= other.y + other.height || other.y >= label.y + label.height)));
});

test('lineage labels use active geometry and only append selected historical geometry', () => {
  const current = [
    { zone_id: 'active', source_timeframe: '1d', side: 'SUPPORT', kernel_id: 'k', center: 100, lower: 99, upper: 101, x1: 0, x2: 40, top: 10, bottom: 20 },
  ];
  const history = [
    { zone_id: 'old-a', source_timeframe: '1d', side: 'SUPPORT', kernel_id: 'k', center: 90, lower: 89, upper: 91, x1: 0, x2: 200, top: 20, bottom: 30, historical: true },
    { zone_id: 'selected', source_timeframe: '1d', side: 'RESISTANCE', kernel_id: 'k', center: 120, lower: 119, upper: 121, x1: 50, x2: 100, top: 40, bottom: 50, historical: true },
    { zone_id: 'selected', source_timeframe: '1d', side: 'RESISTANCE', kernel_id: 'k', center: 120, lower: 119, upper: 121, x1: 100, x2: 140, top: 40, bottom: 50, historical: false },
  ];
  assert.deepEqual(
    labelRectanglesForDisplay(current, history).map((rectangle) => rectangle.zone_id),
    ['active'],
    'unselected history cannot create labels',
  );
  assert.deepEqual(
    labelRectanglesForDisplay(current, history, 'selected').map((rectangle) => rectangle.zone_id),
    ['active', 'selected', 'selected'],
    'selected history remains available for its owned label',
  );
  assert.deepEqual(
    labelRectanglesForDisplay([...current, { ...current[0], zone_id: 'selected' }], history, 'selected')
      .map((rectangle) => rectangle.zone_id),
    ['active', 'selected'],
    'active representation prevents duplicate historical label input',
  );
  const labels = lineageLabelCandidates(labelRectanglesForDisplay(current, history, 'selected'), 'selected');
  assert.ok(labels.some((candidate) => candidate.selected && candidate.member_ids.includes('selected')));
  assert.ok(!labels.some((candidate) => candidate.member_ids.includes('old-a')));
});

test('visible price regions follow painted pixel adjacency and the current window', () => {
  const rectangles = [
    { zone_id: 'z2', x1: 1, x2: 9, top: 10.2, bottom: 12.1 },
    { zone_id: 'z1', x1: 2, x2: 9, top: 13.1, bottom: 14.2 },
    { zone_id: 'offscreen', x1: 101, x2: 110, top: 0, bottom: 5 },
    { zone_id: 'hidden', x1: 1, x2: 9, top: 100, bottom: 110, hidden: true },
  ];
  assert.equal(visiblePriceRegions(rectangles, { left: 0, right: 10 }), 1);
  assert.equal(visiblePriceRegions(rectangles, { left: 100, right: 120 }), 1);
  assert.equal(visiblePriceRegions(rectangles, { left: 20, right: 30 }), 0);
});

test('mode-local cutoff and kernel filtering do not mutate payload evidence', () => {
  const formationCandles = [
    { bar_close_at: '1970-01-01T00:00:10.000000+00:00' },
    { bar_close_at: '1970-01-01T00:00:20.000000+00:00' },
  ];
  const lifecycleCandles = [
    ...formationCandles,
    { bar_close_at: '1970-01-01T00:00:30.000000+00:00' },
  ];
  assert.equal(latestDisplayedCutoff(formationCandles), formationCandles[1].bar_close_at);
  assert.equal(latestDisplayedCutoff(lifecycleCandles), lifecycleCandles[2].bar_close_at);
  assert.equal(latestDisplayedCutoff([], 'fallback'), 'fallback');

  const rows = [
    { kernel_id: 'previous_period_anchor', value: 1 },
    { kernel_id: 'plateau_sweep_reclaim', value: 2 },
  ];
  const original = structuredClone(rows);
  assert.deepEqual(filterKernelRows(rows, new Set(['plateau_sweep_reclaim'])), [rows[1]]);
  assert.deepEqual(rows, original);
  assert.notEqual(rows, filterKernelRows(rows, new Set(['plateau_sweep_reclaim'])));
  assert.deepEqual(
    filterKernelRows(
      [...rows, { kernel_id: 'future_kernel', value: 3 }],
      new Set(['plateau_sweep_reclaim']),
      new Set(['previous_period_anchor', 'plateau_sweep_reclaim']),
    ),
    [rows[1], { kernel_id: 'future_kernel', value: 3 }],
    'kernel IDs absent from the configured catalog fail open for chart display',
  );
});

test('kernel filters canonicalize versioned features, versioned zones, and base-only candidates', () => {
  const configured = new Set(['plateau_sweep_reclaim@1', 'previous_period_anchor@1']);
  const enabled = new Set(configured);
  const featureRows = [
    { kernel_id: 'previous_period_anchor@1', value: 'feature' },
    { kernel_id: 'plateau_sweep_reclaim@1', value: 'feature' },
  ];
  const zoneRows = [
    { kernel_id: 'previous_period_anchor', kernel_version: '1', value: 'zone' },
    { kernel_id: 'plateau_sweep_reclaim', kernel_version: '1', value: 'zone' },
  ];
  const candidateRows = [
    { kernel_id: 'previous_period_anchor', value: 'candidate' },
    { kernel_id: 'plateau_sweep_reclaim', value: 'candidate' },
  ];
  assert.equal(filterKernelRows(featureRows, enabled, configured).length, 2);
  assert.equal(filterKernelRows(zoneRows, enabled, configured).length, 2);
  assert.equal(filterKernelRows(candidateRows, enabled, configured).length, 2);

  enabled.delete('previous_period_anchor@1');
  assert.deepEqual(filterKernelRows(featureRows, enabled, configured), [featureRows[1]]);
  assert.deepEqual(filterKernelRows(zoneRows, enabled, configured), [zoneRows[1]]);
  assert.deepEqual(filterKernelRows(candidateRows, enabled, configured), [candidateRows[1]]);
  assert.equal(
    kernelMatchesConfiguration({ kernel_id: 'future_kernel' }, enabled, configured),
    true,
    'an unknown base remains fail-open',
  );
  assert.equal(
    kernelMatchesConfiguration({ kernel_id: 'previous_period_anchor', kernel_version: '1' }, enabled, configured),
    false,
  );
  assert.equal(
    kernelMatchesConfiguration({ kernel_id: 'plateau_sweep_reclaim' }, new Set(), new Set(['plateau_sweep_reclaim@1', 'plateau_sweep_reclaim@2'])),
    false,
    'a base-only row hides when every configured version is disabled',
  );
  assert.equal(
    kernelMatchesConfiguration({ kernel_id: 'plateau_sweep_reclaim' }, new Set(['plateau_sweep_reclaim@2']), new Set(['plateau_sweep_reclaim@1', 'plateau_sweep_reclaim@2'])),
    true,
    'a base-only row shows when any configured version is enabled',
  );

  const time = (seconds) => `1970-01-01T00:00:${String(seconds).padStart(2, '0')}.000000+00:00`;
  const history = {
    zones: [
      { zone_id: 'zone-prev', source_timeframe: '1d', available_at: time(10), side: 'SUPPORT', kernel_id: 'previous_period_anchor', kernel_version: '1', center: 100, lower: 99, upper: 101 },
      { zone_id: 'zone-plateau', source_timeframe: '1d', available_at: time(10), side: 'RESISTANCE', kernel_id: 'plateau_sweep_reclaim', kernel_version: '1', center: 110, lower: 109, upper: 111 },
    ],
    lifecycle_intervals: [
      { zone_id: 'zone-prev', source_timeframe: '1d', lifecycle: 'ACTIVE', entered_at: time(10), exited_at: time(30) },
      { zone_id: 'zone-plateau', source_timeframe: '1d', lifecycle: 'ACTIVE', entered_at: time(10), exited_at: time(30) },
    ],
  };
  const rectangles = pixelHistoryBands(
    history,
    [{ time: 10 }, { time: 20 }, { time: 30 }],
    { timeToCoordinate: (time) => time * 2 + 5 },
    { priceToCoordinate: (price) => price },
    { enabledKernelIds: enabled, configuredKernelIds: configured },
  );
  assert.deepEqual(rectangles.map((rectangle) => rectangle.zone_id), ['zone-plateau']);
  assert.equal(filterKernelRows(history.zones, enabled, configured).length, 1);
  const renderedHistory = [
    { zone_id: 'zone-prev', historical: true, x1: 0, x2: 40 },
    { zone_id: 'zone-prev', historical: false, x1: 20, x2: 60 },
    { zone_id: 'zone-plateau', historical: false, x1: 101, x2: 120 },
  ];
  assert.deepEqual(
    historyLineageCounts(history.zones, renderedHistory, {
      enabledKernelIds: new Set(configured),
      configuredKernelIds: configured,
      visibleWindow: { left: 0, right: 100 },
    }),
    { total: 2, enabled: 2, inWindow: 1 },
    'history status counts unique rendered IDs, including an active-band representation',
  );
  assert.deepEqual(
    historyLineageCounts(history.zones, renderedHistory, {
      enabledKernelIds: enabled,
      configuredKernelIds: configured,
      visibleWindow: { left: 0, right: 100 },
    }),
    { total: 2, enabled: 1, inWindow: 0 },
    'disabled history IDs cannot appear in the in-window count',
  );
  assert.deepEqual(
    historyLineageCounts(history.zones, renderedHistory, {
      enabledKernelIds: new Set(configured),
      configuredKernelIds: configured,
      visible: false,
      visibleWindow: { left: 0, right: 100 },
    }),
    { total: 2, enabled: 2, inWindow: 0 },
    'hidden zones report no rendered history in the pane',
  );
});

test('passive inspection stays separate from the overlay and restores locally', () => {
  const overlay = { cutoff: '1970-01-01T00:00:10.000000+00:00', active_zones: ['z-overlay'] };
  const hover = { cutoff: '1970-01-01T00:00:20.000000+00:00', active_zones: ['z-hover'] };
  assert.deepEqual(
    applyInspectionResult(overlay, hover, { passive: true, inspectorOpen: true }),
    { overlayInspection: overlay, currentInspection: hover },
  );
  assert.deepEqual(
    applyInspectionResult(overlay, hover, { passive: true, inspectorOpen: false }),
    { overlayInspection: overlay, currentInspection: overlay },
  );
  assert.deepEqual(
    applyInspectionResult(overlay, hover),
    { overlayInspection: hover, currentInspection: hover },
  );
});

test('band price range follows visible logical candles and ignores off-screen geometry', () => {
  const bands = [
    { start_time: 10, end_time: 20, lower: 90, upper: 110 },
    { start_time: 30, end_time: 40, lower: 190, upper: 210 },
    { start_time: 10, end_time: 20, lower: 'bad', upper: 999 },
  ];
  const candles = [10, 20, 30, 40];
  assert.deepEqual(bandPriceRange(bands, candles, 0, 1), { minValue: 90, maxValue: 110 });
  assert.deepEqual(bandPriceRange(bands, candles, 2, 3), { minValue: 190, maxValue: 210 });
  assert.equal(bandPriceRange(bands, candles, -2, -1), null);
  assert.equal(bandPriceRange(bands, candles, 4, 5), null);
  assert.equal(bandPriceRange([], candles, 0, 1), null);
  assert.equal(bandPriceRange([{ start_time: 10, end_time: 20, lower: null, upper: true }], candles, 0, 1), null);
  assert.equal(bandPriceRange([{ start_time: null, end_time: 20, lower: 90, upper: 110 }], candles, 0, 1), null);
});

test('open band autoscale includes the final candle but excludes later starts', () => {
  const bands = [
    { start_time: 20, end_time: 20, display_open: true, lower: 190, upper: 210 },
    { start_time: 30, end_time: 30, display_open: true, lower: 290, upper: 310 },
    { start_time: 20, end_time: 15, display_open: true, lower: 390, upper: 410 },
  ];
  const candles = [10, 20];
  assert.deepEqual(bandPriceRange(bands, candles, 0, 1), { minValue: 190, maxValue: 210 });
  assert.equal(bandPriceRange(bands, candles, 0, 0), null);
});

test('causal projection rejects a source close after the selected cutoff', () => {
  const candles = [{ time: 10 }, { time: 20 }, { time: 30 }];
  const zones = [{
    zone_id: 'future', side: 'SUPPORT', lifecycle: 'ACTIVE',
    available_at: '1970-01-01T00:00:30.000000+00:00', lower: 90, upper: 100,
  }];
  const intervals = [{
    zone_id: 'future', lifecycle: 'ACTIVE',
    entered_at: '1970-01-01T00:00:10.000000+00:00',
    exited_at: '1970-01-01T00:01:00.000000+00:00',
  }];
  assert.deepEqual(projectBands(zones, intervals, candles, 20), []);
});

test('open projection uses a cutoff-local display horizon without mutating exits', () => {
  const candles = [{ time: 10 }, { time: 20 }, { time: 30 }, { time: 40 }, { time: 50 }];
  const zones = [{
    zone_id: 'z', side: 'SUPPORT', lifecycle: 'ACTIVE',
    available_at: '1970-01-01T00:00:10.000000+00:00', lower: 99, upper: 101,
  }];
  const intervals = [{
    zone_id: 'z', lifecycle: 'ACTIVE',
    entered_at: '1970-01-01T00:00:10.000000+00:00',
    exited_at: '1970-01-01T00:00:40.000000+00:00',
  }];
  const projected = projectBands(zones, intervals, candles, 20);
  assert.equal(projected.length, 1);
  assert.equal(projected[0].end_time, 20);
  assert.equal(projected[0].display_open, true);
  assert.equal(intervals[0].exited_at, '1970-01-01T00:00:40.000000+00:00');
});

test('formation bands use ceiling source closes and half-open lifecycle intervals', () => {
  const candles = [{ time: 10 }, { time: 20 }, { time: 30 }];
  const zones = [{ zone_id: 'z', side: 'SUPPORT', lifecycle: 'ACTIVE', available_at: '1970-01-01T00:00:15.000000+00:00', lower: '99', upper: '101' }];
  const intervals = [{ zone_id: 'z', lifecycle: 'ACTIVE', lower: '99', entered_at: '1970-01-01T00:00:15.000000+00:00', exited_at: '1970-01-01T00:00:30.000000+00:00' }];
  const bands = projectBands(zones, intervals, candles, 20);
  assert.equal(bands[0].start_time, 20);
  assert.equal(bands[0].end_time, 20);
  assert.equal(bands[0].display_open, true);
  assert.deepEqual(intervalData(candles, intervals[0], 'lower'), [{ time: 20, value: 99 }]);
  const episode = { started_at: '1970-01-01T00:00:10.000000+00:00', ended_at: '1970-01-01T00:00:30.000000+00:00' };
  assert.deepEqual(touchHighlight(candles, episode, { center: '100' }), [{ time: 10, value: 100 }, { time: 20, value: 100 }]);
});

test('candidate and selected-zone markers stay sparse and unlabeled', () => {
  const candidates = aggregateCandidateMarkers([{ available_at: '1970-01-01T00:00:20.000000+00:00', side: 'SUPPORT', kernel_id: 'k', count: 4 }]);
  assert.equal(candidates.length, 1);
  assert.equal(candidates[0].candidate_count, 4);
  assert.equal(candidates[0].text, '');
  const transitions = ['CREATED', 'TOUCH_STARTED', 'BROKEN'].map((event, index) => ({
    event,
    event_at: `1970-01-01T00:00:${String(index + 1).padStart(2, '0')}.000000+00:00`,
    zone_id: 'z',
  }));
  const markers = transitionMarkers(transitions, new Map([['z', { side: 'SUPPORT' }]]));
  assert.equal(markers.length, 3);
  assert.deepEqual(markers.map((marker) => marker.text), ['', '', '']);
  assert.equal(markers[0].position, 'belowBar');
});

test('navigation and request gate preserve trace boundaries and ignore stale work', () => {
  const zone = { zone_id: 'z', predecessor_id: null, successor_id: 'next' };
  assert.equal(navigationState(zone, new Set(['z', 'next']), 'WINDOW_RELATIVE').successor, true);
  assert.equal(navigationState({ ...zone, successor_id: 'outside' }, new Set(['z']), 'WINDOW_RELATIVE').successor, false);
  assert.equal(navigationState(
    { ...zone, successor_id: 'old' },
    new Map([['z', zone], ['old', { formed_at: '1969-12-31T23:59:00.000000+00:00' }]]),
    'WINDOW_RELATIVE',
    '1970-01-01T00:00:00.000000+00:00',
  ).successor, false);
  const gate = createRequestGate();
  const first = gate.begin();
  const second = gate.begin();
  assert.equal(gate.isCurrent(first.id), false);
  assert.equal(gate.isCurrent(second.id), true);
  assert.equal(first.signal.aborted, true);
  gate.finish(second.id);
});

test('selected payload is compact and rejects raw evidence aliases', () => {
  const pane = {
    source_timeframe: '1d',
    formation: { timeframe: '1d', candles: [], candidates: [], kernel_ids: [] },
    lifecycle: { timeframe: '5m', candles: [], kernel_ids: [] },
    inspection: {
      as_of: '1970-01-01T00:00:30.000000+00:00',
      analysis_start: '1970-01-01T00:00:10.000000+00:00',
      window_start: '1970-01-01T00:00:10.000000+00:00',
      available_cutoffs: [], identity_mode: 'WINDOW_RELATIVE', reconstruction_start: '1970-01-01T00:00:00.000000+00:00',
    },
  };
  const payload = validateSelectedPayload({ schema_version: 2, configured_timeframes: ['1d'], panes: { '1d': pane } });
  assert.equal(payload.panes['1d'].lifecycle.timeframe, '5m');
  assert.throws(() => validateSelectedPayload({ schema_version: 1, configured_timeframes: ['1d'], panes: { '1d': pane } }), /schema-v2/);
  assert.throws(() => validateSelectedPayload({ schema_version: 2, configured_timeframes: ['1d'], panes: { '1d': { ...pane, lifecycle: { ...pane.lifecycle, transitions: [] } } } }), /projection/);
});

test('historical as-of inspection is cutoff-local and uses half-open state', () => {
  const pane = {
    formation: {
      candidates: [
        { candidate_key: 'early', available_at: '1970-01-01T00:00:10.000000+00:00' },
        { candidate_key: 'late', available_at: '1970-01-01T00:00:30.000000+00:00' },
      ],
    },
    lifecycle: {
      zones: [{ zone_id: 'z', geometry: { center: '100', lower: '99', upper: '101' } }],
      intervals: [
        { zone_id: 'z', lifecycle: 'ACTIVE', entered_at: '1970-01-01T00:00:10.000000+00:00', exited_at: '1970-01-01T00:00:30.000000+00:00' },
        { zone_id: 'z', lifecycle: 'TOUCHED', entered_at: '1970-01-01T00:00:30.000000+00:00', exited_at: null },
      ],
      touch_episodes: [{ zone_id: 'z', started_at: '1970-01-01T00:00:15.000000+00:00', ended_at: '1970-01-01T00:00:25.000000+00:00' }],
      transitions: [
        { event: 'CREATED', event_at: '1970-01-01T00:00:10.000000+00:00' },
        { event: 'TOUCH_STARTED', event_at: '1970-01-01T00:00:20.000000+00:00' },
      ],
    },
  };
  const atTwenty = asOfInspection(pane, 20);
  assert.equal(atTwenty.cutoff, 20);
  assert.deepEqual(atTwenty.candidates.map((item) => item.candidate_key), ['early']);
  assert.deepEqual(atTwenty.zoneStates.map((item) => item.lifecycle), ['ACTIVE']);
  assert.equal(atTwenty.touchEpisodes.length, 1);
  assert.deepEqual(atTwenty.transitions.map((item) => item.event), ['TOUCH_STARTED']);
  const atThirty = asOfInspection(pane, 30);
  assert.deepEqual(atThirty.zoneStates.map((item) => item.lifecycle), ['TOUCHED']);
  assert.equal(atThirty.touchEpisodes.length, 0);
});
