---
goal: Deliver hardened SR-V1.5 baseline evidence and browser viewer
stage: coder-to-review
date_created: 2026-07-15
last_updated: 2026-07-15
owner: Codex Coder
status: Needs Revision
tags: [handoff, quant, sr, baseline-trial, evidence, viewer]
source_agent: Codex Coder
target_agent: Quant Review
---

# Coder To Review: SR-V1.5 Baseline Trial v1

## Scope Executed

Applied four blocker remediations to approved V1.5:

1. Browser-resolvable package-local Lightweight Charts import.
2. Direct media-coordinate LINE/BAND rendering without pixel-ratio fields.
3. Causal ATR provenance timestamp at first model-bar close.
4. Fail-closed bundle identity, chart binding, semantic consistency, and
   duplicate-JSON-key validation in both validators.

Approved half-open window remains unchanged:

```text
requested_since = 2024-01-01T00:00:00.000Z
requested_until = 2026-07-01T00:00:00.000Z
open_time >= requested_since
open_time < requested_until
closed_at = open_time + 1 day
closed_at <= requested_until
Binance startTime = 1704067200000
Binance endTime   = 1782863999999
```

Lineage:

```text
branch:       feature/sr-v1.5-baseline-trial
base:         6ed2951a036c5d3dad040f182305fb5ed68e5277
implementation: 98446634374dcdf7d38a00c1c3e555734d6ed479
window fix:   842ffa24afc7f6ba64fa5dfb5d09c1d0e6f740e9
hardening:    afeaf434297884b9049bd88853343446af59ce0e
```

No merge performed.

## Changes Made

- `main.js` imports
  `../node_modules/lightweight-charts/dist/lightweight-charts.production.mjs`;
  no CDN or bare browser specifier remains.
- `ZoneRenderer` uses `mediaSize.width`, direct `timeToCoordinate` values,
  direct `priceToCoordinate` values, and configured line width. Added actual
  LINE/BAND live/terminal renderer tests asserting finite geometry and opacity.
- `build_model_bars()` records `first_valid_at` as the first model
  `ClosedBar.closed_at`. `TrialResult` and `EvidenceManifest` enforce this
  causal relation.
- Artifact and viewer validators now reject duplicate JSON keys, recompute
  `bundle_id` from `bundle_id_semantic_payload`, compare top-level semantic
  fields and member metadata, verify chart bundle binding and chart identity,
  and verify manifest/model ATR provenance agreement.
- Added adversarial tampering tests for nested identity, top-level semantics,
  chart binding, chart identity, duplicate keys, and direct ATR chronology.

## Blast Radius Considered

Changes stay inside baseline-trial integration, package-local viewer, and
their tests. SR domain/config/detection/association/lifecycle/replay/evaluation,
ATR implementation, BinanceNativeAdapter, `configs/sr.yaml`, and public SR
exports remain unchanged.

Viewer dependency flow is now browser-safe:

```text
index.html -> /src/main.js -> /node_modules/lightweight-charts/...mjs
                         -> /bundle/chart_payload.json
```

Both Python validators remain independent of provider/model execution. Viewer
server identity hashing uses local canonical JSON logic; no SR core import was
added to server.py.

## Validation Performed

Python:

- Baseline trial + viewer tests: **59 passed**.
- Full SR suite after hardening: **354 passed**.
- Trendline import boundaries: **2 passed**.
- Ruff, compile, import isolation, and `git diff --check`: passed.
- Both `artifacts.validate_bundle()` and `zone_viewer.server.validate_bundle()`
  accepted corrected live bundle.
- Both validators rejected tampered identity/semantic/chart cases and duplicate
  manifest keys.

JavaScript/static serving:

- Package-local Node tests: **6 passed**.
- Renderer tests cover BAND/live and LINE/terminal direct coordinates; no NaN
  or null geometry.
- `npm ci`: 3 packages audited, 0 vulnerabilities.
- Node syntax checks passed.
- Corrected local server routes: index 200, main.js 200, package module 200,
  chart payload 200, traversal 404.

Mandatory browser smoke status: **not completed**. Browser runtime reported
`No browser is available`; `agent.browsers.list()` returned no instances.
Static route and Node checks pass, but no real-browser claim is made.

Live trial ran twice from hardening commit `afeaf43`; both runs returned the
same bundle ID, trace ID, diagnostics ID, and row counts:

```text
bundle_id:       31a562bd31a7d55216d04f3177aa4d066963a61d952455e4402d094f6a907e05
output_path:     research/tmp_sr_v1_5/31a562bd31a7d55216d04f3177aa4d066963a61d952455e4402d094f6a907e05
raw rows:        811
ATR warmup:      14
model rows:      797
trace_id:        228aac84c81d53f5ffba3dc063f09248e22f315160bd7cad67bcc8e6c54ab943
diagnostics_id:  96b445bd81688a900f44cec0850f894e23c4d5843864934a2e53d11cf4a43e24
```

Evidence bounds and identity:

```text
requested:       2024-01-01T00:00:00Z .. 2026-07-01T00:00:00Z
actual:          2024-04-11T00:00:00Z .. 2026-07-01T00:00:00Z
last open_time:  2026-06-30T00:00:00Z
last closed_at:  2026-07-01T00:00:00Z
first ATR:       2024-04-26T00:00:00Z
source hash:     b99e4c7281b23f6b13e6ce4148a8ef01a5da86c371463c095fcbfe586e4d0535
SR config hash:  cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299
input hash:      5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d
window_policy:   half_open_utc_daily
```

Trace/diagnostics:

```text
snapshots: 797 | zone observations: 26463 | events: 451
zones: 64 (34 support, 30 resistance)
created/touched: 64/277 | breach/false/break: 38/11/27 | expired: 34
max/final live zones: 5/3 | right-censored: 3
```

Bundle member hashes and byte lengths:

```text
source_bars.json   b99e4c7281b23f6b13e6ce4148a8ef01a5da86c371463c095fcbfe586e4d0535  159514
model_bars.json    fc00d4698196cb54d9e74908a9841a226cc3421191694d182825dea556dca18a  139741
trace.json         662ff1ff146713505a194aba372809f4dd2e608f0577fb729605db9aefb4e67b  20841771
diagnostics.json   bf84552c7e807ded22db3f09e8ea3be3ae773ebdd592de017280a3045780d633  213313
chart_payload.json b2e1970022d130117904a82d1ee13517a2e222bb4819d1dd1bf285d3bbd3512d  400716
```

All-six-file deterministic digest, including manifest:

```text
e3b7c7f906f8ad25f0d65e9e7f00338b23105edb99872e28e26049f9d6adcb8d
```

## Not Changed

- No merge.
- No generated market data/evidence committed.
- No Binance adapter, ATR implementation, SR core, config surface, tuning, or
  trading-readiness work.
- Pre-existing `.codebase-memory` artifacts and unrelated untracked drafts
  remain untouched.

## Risks or Follow-up Items

- Real browser smoke is mandatory and remains environment-blocked. Reviewer
  must run browser smoke or provide browser backend before approval.
- This baseline remains observation/engineering evidence, not predictive,
  profitability, or trading-readiness evidence.

Package is ready for rereview after browser smoke. No merge requested.
