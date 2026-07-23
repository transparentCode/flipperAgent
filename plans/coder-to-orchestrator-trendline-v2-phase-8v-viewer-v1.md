# Coder to Orchestrator: Trendline V2 Phase 8V Viewer

## 1. State

```text
REMEDIATION_READY_FOR_ORCHESTRATOR_REVIEW
```

Branch:

```text
feature/trendline-v2-phase-8v-tvlc-viewer-v1
```

Base and current implementation base:

```text
4c01526d9bf61ad98c2c9f08c36ad19e82b77341
feat(trendline-v2): add minimal discovery api
```

The Phase 8V changes are uncommitted. No merge, push, or new worktree was
performed.

## 2. Files

Implemented viewer application:

```text
src/apps/trendline_v2_viewer/__init__.py
src/apps/trendline_v2_viewer/payload.py
src/apps/trendline_v2_viewer/server.py
src/apps/trendline_v2_viewer/web/index.html
src/apps/trendline_v2_viewer/web/styles.css
src/apps/trendline_v2_viewer/web/package.json
src/apps/trendline_v2_viewer/web/package-lock.json
src/apps/trendline_v2_viewer/web/tsconfig.json
src/apps/trendline_v2_viewer/web/src/contracts.ts
src/apps/trendline_v2_viewer/web/src/payload.ts
src/apps/trendline_v2_viewer/web/src/trendline_primitive.ts
src/apps/trendline_v2_viewer/web/src/main.ts
src/apps/trendline_v2_viewer/web/tests/payload.test.mjs
src/apps/trendline_v2_viewer/web/tests/trendline_primitive.test.mjs
```

Tests:

```text
tests/apps/trendline_v2_viewer/__init__.py
tests/apps/trendline_v2_viewer/test_payload.py
tests/apps/trendline_v2_viewer/test_server.py
```

Support change:

```text
.gitignore
```

The support change narrowly unignores the approved viewer `package-lock.json`.
`node_modules/`, compiled `web/dist/`, and generated bundles remain ignored.

No Trendline V2 model file, provider, configuration, runtime, RegimeV2,
tracking, storage, research, MTF, or legacy trendline file was changed.

## 3. Dependency evidence

Runtime/tool versions:

```text
node v26.5.0
npm 11.17.0
```

Exact package pins in `package.json` and `package-lock.json`:

```text
lightweight-charts 5.2.0
typescript 6.0.3
fancy-canvas 2.1.0 (pinned transitive dependency)
```

`npm ci` completed successfully. No CDN or market-data/network request was
used. The generated lockfile is tracked by the narrow `.gitignore` exception;
`node_modules` and compiled output are not tracked.

## 4. Payload contract

`build_chart_payload(result)` accepts only a validated `ProviderResult`.
It carries the complete request, input, configuration, provider, provider
contract, snapshot, status/reason, causal candles, candidates, and complete
`ConfirmedExtremaPairEvidence.to_dict()` records.

Schema:

```text
trendline_v2_viewer_payload_v1
```

`payload_id` is a deterministic content hash of every semantic payload field
except `payload_id`. `ProviderResult.detail` is omitted. Candidate order and
evidence order must match; every candidate has exactly one evidence item, with
matching candidate ID and role/extrema kind. Snapshot ID is rederived from
`result.to_snapshot()`.

Only finite geometry from the first anchor to the second anchor is emitted.
The builder rejects geometry that is not the exact provider segment, and never
adds rays, extensions, forecasts, ranking, or score fields.

All candle, candidate, and anchor times are integer Unix seconds. Conversion is
performed only after exact epoch-nanosecond divisibility by
`1_000_000_000`; sub-second input fails closed rather than rounding, flooring,
or passing through JavaScript `Date`.

## 5. Bundle contract and integrity

`write_viewer_bundle` accepts an absent or empty destination only and writes
exactly:

```text
manifest.json
chart_payload.json
```

The manifest contains `schema_version`, `bundle_id`, `payload_id`, and one
member descriptor for `chart_payload.json`. The manifest itself is not a member
because self-hashing it would be recursive. `bundle_id` is rederived from the
canonical semantic manifest payload. Payload byte length, SHA-256, canonical
JSON, payload identity, status schema, evidence associations, OHLCV validity,
and bundle identity are all validated before serving.

Phase 8V remediation closes the two review integrity gaps. Python and
TypeScript now enforce the exact ProviderResult status/reason table. Python
rebuilds every served evidence record through
`ConfirmedExtremaPairEvidence.from_dict(...)`, requires the provider-owned
coordinate, plateau, and schema constants, and cross-checks source and
confirmation positions against candle timestamps, role-specific source
prices, exact intermediate counts, and zero body violations for successful
payloads. TypeScript mirrors the same outcome, position, timestamp, price,
count, body, and fixed-semantics checks.

Writes use staged temporary files, fsync, and atomic directory replacement.
Known non-empty destinations, symlink destinations/members, extra files,
duplicate JSON keys, non-finite JSON, payload tampering, and manifest tampering
are rejected. Generated smoke bundles were written only under `/tmp` and are
not repository evidence.

## 6. Server boundary

Run:

```bash
PYTHONPATH=src .venv/bin/python -m apps.trendline_v2_viewer.server \
  --bundle /tmp/trendline-v2-viewer-bundle --port 8765
```

The server defaults to `127.0.0.1` and accepts loopback hosts only. It serves
only `/`, `/styles.css`, the four compiled `/dist/*.js` files, the exact pinned
`/vendor/lightweight-charts.mjs` standalone production module, and
`/bundle/chart_payload.json`. It rejects traversal, unknown paths,
`node_modules` exposure, arbitrary filesystem paths, symlinks, and invalid
bundles before binding.

## 7. Frontend behavior

The TypeScript client targets ES2020 ES modules with strict type checking and
no CommonJS. Runtime payload validation runs before chart construction.

The chart uses one `CandlestickSeries` and one batched `TrendlinePrimitive`.
Candles are not resampled, aggregated, or reordered. The primitive maps only
finite anchor-to-anchor segments through `timeToCoordinate` and
`priceToCoordinate`, skips unavailable/out-of-viewport segments, and supports
anchor visibility, support/resistance visibility, fit-content, finite-segment
hit testing, selected emphasis, and evidence detail.

Hover/click details include candidate ID, role, anchor pivot/price,
confirmation timestamps, source positions, validated intermediate count,
provider identity, request identity, and evidence identity. Abstained/failed
payloads display candles and typed status/reason with no trendlines.

No frontend framework, WebSocket, REST layer, manual drawing, feedback path,
score, ranking, persistence, tracking, or model mutation exists.

## 8. Validation

```text
Focused/full Python viewer suite: 23 passed
Node/TypeScript viewer suite: 13 passed
Trendline V2 suite: 112 passed
Protected Trendline Family suite: 399 passed
Phase 7A benchmark harness: 4 passed
Ruff: all checks passed
compileall: passed
npm ci: passed
npm run build: passed
git diff --check: passed for tracked changes
```

The tests cover deterministic payloads and IDs, complete candles,
support/resistance, abstained/failed status-only payloads, evidence identity,
detail exclusion, sub-second rejection, no mutation, exact bundle membership,
atomic destination behavior, duplicate/non-finite JSON, tampering, symlinks,
loopback security, route allowlisting, HEAD, import boundaries, runtime
payload validation, impossible outcome pairs, forged/rebound evidence IDs,
out-of-range and unrelated positions, source price and timestamp mismatches,
intermediate-count and body-violation tampering, exact evidence semantics,
primitive visibility, finite geometry, hit testing, and
single-primitive/no-extension behavior.

## 9. Smoke evidence

The real vertical path was executed with a deterministic
`ConfirmedOHLCVFrame`, `discover_trendlines`, and `write_viewer_bundle`. The
bundle contained exactly the two expected files. With the server running on
`127.0.0.1`, equivalent Python HTTP `HEAD` checks returned:

```text
/                              200  text/html; charset=utf-8
/vendor/lightweight-charts.mjs 200  text/javascript; charset=utf-8
/bundle/chart_payload.json     200  application/json; charset=utf-8
```

The environment has no `curl` executable, so the required HTTP checks used
Python `http.client` without changing the server path. No local Chromium,
Chromium Browser, or Google Chrome executable was available; real-browser
smoke was therefore unavailable and no browser was installed.

## 10. Index and residual risk

Codebase-memory reindex completed successfully:

```text
flipperAgent-src:     22,634 nodes / 117,331 edges
flipperAgent-tests:    5,434 nodes / 22,810 edges
flipperAgent-plans:    5,131 nodes / 5,126 edges
status: indexed
```

GitNexus also rebuilt successfully with `47,365` nodes and `78,300` edges;
its branch metadata still reports the prior committed Phase 8 branch because
the viewer remains uncommitted. This is optional graph evidence, not a code
validation result.

Residual risks:

- Browser rendering was not exercised because Chromium is unavailable.
- `dist/` and `node_modules/` must be recreated with `npm ci` before serving
  the packaged web assets from a fresh checkout.
- The viewer intentionally supports only whole-second timestamps, while the
  model/provider retains higher precision.
- The bundle manifest uses a non-recursive payload member list and does not
  self-hash `manifest.json`.
- No production-readiness, live-data, runtime integration, ranking, or trading
  claim is made.

## 11. Scope decision

```text
PHASE_8V_TVLC_VIEWER: REMEDIATION_READY_FOR_ORCHESTRATOR_REVIEW
PHASE_8V_SEMANTIC_BUNDLE_VALIDATION: HARDENED
PHASE_9_PARAMETER_SENSITIVITY: NOT_AUTHORIZED
TRACKING_AND_LIFECYCLE: NOT_AUTHORIZED
MERGE: NOT_AUTHORIZED
PUSH: NOT_AUTHORIZED
```
