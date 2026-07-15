---
goal: Deliver the SR-V1.5 baseline trial with the approved half-open UTC daily window
stage: coder-to-review
date_created: 2026-07-15
last_updated: 2026-07-15
owner: Codex Coder
status: Ready
tags: [handoff, quant, sr, baseline-trial, window-correction, evidence]
source_agent: Codex Coder
target_agent: Quant Review
---

# Coder To Review: SR-V1.5 Baseline Trial v1

## Scope Executed

Implemented the issued correction on top of the approved SR-V1.5 implementation.
The model window is now:

```text
requested_since = 2024-01-01T00:00:00.000Z
requested_until = 2026-07-01T00:00:00.000Z
open_time >= requested_since
open_time < requested_until
closed_at = open_time + 1 day
closed_at <= requested_until
```

The Binance request uses the equivalent inclusive provider boundary:

```text
startTime = 1704067200000
endTime   = 1782863999999
```

The June 30 candle is retained and has `closed_at` exactly at July 1 midnight.
A July 1 opening candle and any provider overrun are rejected as a whole; no
returned row is silently filtered.

Branch and lineage:

```text
branch: feature/sr-v1.5-baseline-trial
base: 6ed2951a036c5d3dad040f182305fb5ed68e5277
implementation: 98446634374dcdf7d38a00c1c3e555734d6ed479
correction: 842ffa24afc7f6ba64fa5dfb5d09c1d0e6f740e9
```

The branch remains unmerged.

## Changes Made

- Updated `configs/sr_trials/taousdt_1d_baseline.yaml` to the approved UTC
  daily half-open model window.
- Added strict UTC daily-boundary validation to `TrialSpec`.
- Added canonical epoch-millisecond/provider-bound helpers. The dataset path
  now calls the provider with `requested_until_ms - 1` while retaining the
  model cutoff at `requested_until`.
- Added explicit `open_time < requested_until` validation and retained
  `closed_at <= requested_until` validation.
- Added `window_policy` and effective Binance `provider_request` bounds to the
  manifest semantic identity before bundle hashing.
- Added regressions for daily-boundary rejection, June 30 acceptance and
  closure, July 1/provider-overrun rejection, provider `endTime`, and manifest
  identity.

Only these eight files changed in the correction commit:

```text
configs/sr_trials/taousdt_1d_baseline.yaml
src/libs/models/sr/scripts/baseline_trial/artifacts.py
src/libs/models/sr/scripts/baseline_trial/contracts.py
src/libs/models/sr/scripts/baseline_trial/dataset.py
tests/models/sr/scripts/baseline_trial/test_artifacts.py
tests/models/sr/scripts/baseline_trial/test_config.py
tests/models/sr/scripts/baseline_trial/test_dataset.py
tests/models/sr/scripts/baseline_trial/test_runner.py
```

## Blast Radius Considered

The affected flow is limited to trial YAML -> `TrialSpec` -> validated dataset
fetch -> bundle manifest identity. Existing SR domain, detection, association,
lifecycle, replay, evaluation, ATR, and Binance adapter implementations are
unchanged. `configs/sr.yaml` and the exact eight SR parameters are unchanged.

The manifest’s provider-bound and window-policy fields participate in the
bundle semantic payload, so changing the window contract deterministically
changes the bundle identity. The viewer continues to consume only the
published evidence payload.

The codebase-memory MCP was unavailable and its local index did not return the
new leaf symbols; impact was checked from the approved dependency graph in the
handoff, direct call sites, and the exact commit diff. No high-risk shared
symbol was modified.

## Validation Performed

Python and boundary validation:

- Baseline-trial tests: **47 passed**.
- Full SR suite after the correction commit: **347 passed**.
- Trendline import boundaries: **2 passed**.
- Ruff: passed.
- Python compilation and package imports: passed.
- `git diff --check`: passed.

Viewer and serving validation:

- `npm ci`: completed; 3 packages audited, 0 vulnerabilities.
- Package-local JavaScript tests: **3 passed**.
- `node --check src/main.js src/zone_primitive.js`: passed.
- Real-bundle server smoke: `/` returned 200, `/bundle/chart_payload.json`
  returned 200, encoded traversal returned 404.
- In-app browser visual inspection was unavailable because this environment
  exposed no browser instances. Static, payload, JavaScript, and server checks
  passed.

Live trial was run twice from correction commit `842ffa2`; both runs returned:

```text
bundle_id:       af2bd66e0d08bb753b2d8522ab7b0c20a5af3bcc940519d333b3047fe1287e85
output_path:     research/tmp_sr_v1_5/af2bd66e0d08bb753b2d8522ab7b0c20a5af3bcc940519d333b3047fe1287e85
raw rows:        811
ATR warmup:      14
model rows:      797
trace_id:        228aac84c81d53f5ffba3dc063f09248e22f315160bd7cad67bcc8e6c54ab943
diagnostics_id:  96b445bd81688a900f44cec0850f894e23c4d5843864934a2e53d11cf4a43e24
```

The second publication exercised the existing-bundle collision path, which
compared all expected member bytes. Independent manifest rehashing also
passed. The source bounds and ATR evidence are:

```text
requested:       2024-01-01T00:00:00Z .. 2026-07-01T00:00:00Z
actual:          2024-04-11T00:00:00Z .. 2026-07-01T00:00:00Z
last open_time:  2026-06-30T00:00:00Z
last closed_at:  2026-07-01T00:00:00Z
first ATR:       2024-04-25T00:00:00Z
source hash:     b99e4c7281b23f6b13e6ce4148a8ef01a5da86c371463c095fcbfe586e4d0535
SR config hash:  cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299
input hash:      5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d
```

The manifest records `window_policy: half_open_utc_daily` and the effective
provider bounds above. Input provenance is defaults for all three ATR fields;
SR provenance is defaults for all eight approved fields.

Trace and diagnostics evidence:

```text
snapshots:              797
zone observations:      26463
events:                 451
zones:                  64 (34 support, 30 resistance)
created/touched:        64 / 277
breach/false/break:     38 / 11 / 27
expired:                34
max/final live zones:   5 / 3
right-censored zones:   3
```

Bundle member hashes and byte lengths:

```text
source_bars.json   b99e4c7281b23f6b13e6ce4148a8ef01a5da86c371463c095fcbfe586e4d0535  159514
model_bars.json    2860ed695c6d7dc6c66217d195506f1ad39abb393deee0251cd2b1956691d9ca  139741
trace.json         662ff1ff146713505a194aba372809f4dd2e608f0577fb729605db9aefb4e67b  20841771
diagnostics.json   bf84552c7e807ded22db3f09e8ea3be3ae773ebdd592de017280a3045780d633  213313
chart_payload.json 8ef4968ec683b0029f93a577bf4264158c65e68abb40ed3f5046fffe55e132d3  400716
```

Deterministic digest over all six bundle files, including the manifest:

```text
9e0b5b3622686c1ab31121ae0e748a4bd983edb7a1f37ccc211accb6fadbabe5
```

## Not Changed

- No merge to `master` or another branch.
- No changes to `BinanceNativeAdapter`, ATR, SR core behavior, SR configs, or
  public package exports.
- No parameter tuning, detection/lifecycle feature work, trading-readiness
  claims, or V1.6 work.
- No live market data or generated evidence bundle was committed.
- Pre-existing `.codebase-memory` artifacts and unrelated untracked plan drafts
  were not staged or modified by the correction commit.

## Risks or Follow-up Items

- Quant review should independently inspect the manifest’s half-open policy and
  confirm the provider-bound naming/identity fields meet the evidence standard.
- Manual visual browser inspection remains pending solely because no browser
  backend was available in this environment; the local server and static
  viewer contract are validated.
- This is an observation/engineering-integrity baseline. It is not evidence of
  predictive quality, profitability, or trading readiness.

This package is complete enough for review without guessing. No merge is
requested from the coder stage.
