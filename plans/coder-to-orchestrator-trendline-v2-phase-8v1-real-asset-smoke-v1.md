# Coder to Orchestrator: Trendline V2 Phase 8V.1 Real-Asset Smoke

## State

```text
READY_FOR_ORCHESTRATOR_REVIEW
```

Branch: `research/trendline-v2-phase-8v1-real-asset-smoke-v1`

Base commit: `508ad0dfba3dee4305a6b5068c0958b126d45d5e`

No commit, merge, push, or new worktree was performed for Phase 8V.1.

## Changed Files

```text
scripts/run_trendline_v2_real_asset_smoke.py
tests/scripts/test_trendline_v2_real_asset_smoke.py
plans/coder-to-orchestrator-trendline-v2-phase-8v1-real-asset-smoke-v1.md
```

No model, provider, viewer, configuration, runtime, Regime, tracking,
storage, MTF, or legacy trendline file changed.

## Fixed Request

```text
Adapter: apps.ingestion_app.adapters.binance_native.BinanceNativeAdapter
Market: Binance USD-M Futures
Asset: BTCUSDT
Timeframe: 4h
since: 1754006400000
until: 1764547200000
limit: 1000
network request count: 1
```

One request executed. No retry, pagination, alternate adapter, market, or
window used.

## Normalization

```text
raw rows: 733
normalized confirmed rows: 732
first timestamp: 2025-08-01T00:00:00Z
last timestamp: 2025-11-30T20:00:00Z
last bar close: 2025-12-01T00:00:00Z
```

Runner required integer millisecond timestamps, UTC conversion, float64 finite
OHLCV, valid OHLCV bounds, ordered unique timestamps, exact four-hour spacing,
fixed boundaries, and exact 732-row output. One terminal incomplete bar was
excluded. Extra adapter fields were ignored.

## Provider Execution

Foundation config remained explicit:

```json
{"model":{"name":"trendline_v2","schema_version":1,"version":"foundation_v1"}}
```

Smoke-only provider config:

```text
lookback_duration_seconds = 10540800.0
left_confirmation_bars = 1
right_confirmation_bars = 1
min_extrema_per_role = 2
max_hypotheses = 100000
max_output_candidates = 10000
```

Classification: `SMOKE_ONLY / UNRESOLVED / NOT_PROMOTED / NOT_CANONICAL`.

Primary result:

```text
status: success
reason: null
candidate count: 2697
support count: 1501
resistance count: 1196
fallback used: false
```

No ranking, filtering, scoring, tuning, or parameter comparison performed.

## Identities

```text
frame_input_identity: 9bb5706ea5c217c1d449042f7561d47db4eba92388959b04c0089448639a38f0
provider_input_identity: b413ae38dd59c085c38774148b641e253e06df4591ed36f2357109ac1ea39371
config_identity: 7c5c9a8e9513588548145afb085a40d16b7a39738a6a670e0af2613a4bf1d636
request_identity: 6ef0c5926c960ba6bd11596c30c8cbe507447319d6a5b4231de15408618c36e0
provider_identity: b1721806600f5486f244cc987644918f6af061777803512c46eca92ace8794f8
provider_contract_identity: e14dc28f77805a0c7474e3fc8b141036171f6c2789a6b1a1ffcb97fb9461d0e4
snapshot_id: 13bec863774047756a71a083f1dba0619d2d04756195d6ec8dba048241901db7
```

## Artifacts

```text
/tmp/trendline_v2_real_asset_smoke/btcusdt_4h_20250801_20251201/run_report.json
/tmp/trendline_v2_real_asset_smoke/btcusdt_4h_20250801_20251201/provider_result.json
/tmp/trendline_v2_real_asset_smoke/btcusdt_4h_20250801_20251201/viewer_bundle/
```

Provider-result SHA-256:

```text
6f15a2fc192e61a47c365509fa824cb11834161d6ee9b1c5a352f6ca816d5175
```

Viewer payload ID: `9c1c42bf89eaa85c33af4a4787beabd5f1ce3e0c26fe02babe0bb82ab4cc2e51`

Viewer bundle ID: `d56fc53daa4e6c69b189c5ebb72c46f87f67f23056238765106e21c3a3bc41c3`

Bundle contains exactly `manifest.json` and `chart_payload.json`. Independent
reload verified canonical provider JSON, hash, report identity bindings,
payload ID, bundle ID, and exact membership.

## Browserless HTTP Smoke

Existing loopback server returned:

```text
/                              200
/styles.css                    200
/dist/main.js                  200
/vendor/lightweight-charts.mjs 200
/bundle/chart_payload.json     200
/node_modules/lightweight-charts/package.json 404
/manifest.json                 404
/bundle/../manifest.json       404
```

No browser, popup, Chromium, Playwright, Selenium, Puppeteer, or automatic
launcher used.

Manual viewing:

```bash
cd /Users/aloobhujia/flipperAgent/src/apps/trendline_v2_viewer/web
npm ci
npm run build
cd /Users/aloobhujia/flipperAgent
PYTHONPATH=src .venv/bin/python -m apps.trendline_v2_viewer.server \
  --bundle /tmp/trendline_v2_real_asset_smoke/btcusdt_4h_20250801_20251201/viewer_bundle \
  --port 8765
```

Open manually: `http://127.0.0.1:8765`

## Validation

```text
Focused smoke tests: 19 passed
Viewer + Trendline V2: 135 passed
Protected Trendline Family: 399 passed
Phase 7A benchmark: 4 passed
Node/TypeScript viewer: 13 passed
npm ci: 0 vulnerabilities
Ruff: passed
TypeScript build: passed
compileall: passed
git diff --check: passed
```

## Codebase State

Final codebase-memory state:

```text
flipperAgent-src:     22,634 nodes / 117,331 edges
flipperAgent-tests:    5,434 nodes / 22,810 edges
flipperAgent-scripts:    781 nodes / 3,383 edges
flipperAgent-plans:    5,145 nodes / 5,139 edges
status: indexed
```

GitNexus rebuilt with `47,451` nodes / `78,450` edges. Its split-project
metadata reports no commit SHA; CBM indexes are current. Generated `/tmp`
artifacts are outside Git and must not be committed.

## Residual Risks

- Engineering and qualitative smoke only.
- Provider config is not canonical and is not promoted.
- No parameter, trading, predictive, production, or cross-asset claim.
- No visual-browser inspection; browserless HTTP and payload validation passed.
- 2,697 candidate segments may require manual density observation; no parameter
  change is authorized from that fact.

```text
PHASE_8V1_FIXED_REAL_ASSET_SMOKE: READY_FOR_ORCHESTRATOR_REVIEW
PARAMETER_RESEARCH: NOT_AUTHORIZED
CONFIG_PROMOTION: NOT_AUTHORIZED
TRACKING_AND_LIFECYCLE: NOT_AUTHORIZED
MERGE: NOT_AUTHORIZED
PUSH: NOT_AUTHORIZED
COMMIT: NOT_YET_AUTHORIZED
```
