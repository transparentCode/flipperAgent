---
goal: Implement SR-V1.5 as a bounded TAOUSDT 1d real-market baseline trial with causal ATR provenance, deterministic evidence, and a package-local Lightweight Charts zone viewer.
stage: orchestrator-to-coder
date_created: 2026-07-15
last_updated: 2026-07-15
owner: Quant Orchestrator
status: Approved for implementation
tags: [handoff, quant, sr, baseline-trial, taousdt, atr, evidence, visualization]
source_agent: Quant Orchestrator
target_agent: Coder Agent
base_commit: 6ed2951a036c5d3dad040f182305fb5ed68e5277
source_branch: feature/sr-v1.4-observation-evaluation
target_branch: feature/sr-v1.5-baseline-trial
---

# Orchestrator To Coder: SR-V1.5 Baseline Trial v1

## Objective

SR-V1.0 foundation/configuration, SR-V1.1 lifecycle, SR-V1.2 causal
detection/association, SR-V1.3 checkpoint/replay, and SR-V1.4 causal observation
and descriptive evaluation are approved.

Implement one bounded real-market baseline trial for Binance USD-M perpetual
`TAOUSDT` on `1d` bars. The phase must:

1. fetch the approved fixed historical window through the existing native
   Binance adapter;
2. validate the dataset without silent repair;
3. compute causal Wilder/RMA ATR(14) through the existing ATR implementation;
4. replay the approved SR model with the existing eight SR configuration paths;
5. build the approved V1.4 evaluation trace and diagnostics;
6. persist a deterministic, content-addressed evidence bundle; and
7. render the same evidence as candlesticks plus LINE/BAND zones in a
   package-local TradingView Lightweight Charts viewer.

This is an observation and engineering-integrity phase. It does not optimize
parameters or establish predictive quality, profitability, or trading
readiness.

Stop after implementation, validation, one live baseline run, commits, and a
coder-to-review handoff. Do not merge.

## Branch And Working-Tree Safety

1. Verify HEAD is exactly:

   `6ed2951a036c5d3dad040f182305fb5ed68e5277`

2. Create:

   `feature/sr-v1.5-baseline-trial`

   directly from that commit.

3. Do not merge V1.4 or V1.5.
4. Do not stage, edit, delete, regenerate, or commit the pre-existing
   `.codebase-memory` artifacts or unrelated untracked plan drafts.
5. If any dirty path overlaps an in-scope path below, stop and report the
   blocker.
6. Keep implementation and coder handoff in separate commits.
7. Commit no live market-data or generated evidence bundle. Generated evidence
   remains under the configured ignored research scratch path.
8. Record the implementation commit, not the later handoff commit, in the live
   evidence manifest. If production code changes after the live run, rerun and
   replace the evidence reference in the coder handoff.

## Scope Boundaries

### Approved production and configuration scope

Add:

```text
configs/sr_inputs.yaml
configs/sr_trials/taousdt_1d_baseline.yaml

src/libs/models/sr/scripts/
├── __init__.py
└── baseline_trial/
    ├── __init__.py
    ├── cli.py
    ├── config.py
    ├── contracts.py
    ├── dataset.py
    ├── runner.py
    └── artifacts.py

src/libs/models/sr/tools/
├── __init__.py
└── zone_viewer/
    ├── __init__.py
    ├── payload.py
    ├── server.py
    ├── package.json
    ├── package-lock.json
    ├── index.html
    └── src/
        ├── main.js
        ├── zone_primitive.js
        └── styles.css
```

Modify only as narrowly required:

```text
.gitignore
tests/models/sr/test_import_boundaries.py
tests/models/sr/adapters/test_import_boundaries.py
```

The `.gitignore` change is limited to allowing exactly:

```text
!src/libs/models/sr/tools/zone_viewer/package-lock.json
```

after the repository-wide `package-lock.json` ignore. Do not unignore other
lockfiles.

### Approved test scope

Add a mirrored descriptive hierarchy:

```text
tests/models/sr/scripts/
├── __init__.py
└── baseline_trial/
    ├── __init__.py
    ├── test_config.py
    ├── test_contracts.py
    ├── test_dataset.py
    ├── test_atr_causality.py
    ├── test_runner.py
    └── test_artifacts.py

tests/models/sr/tools/
├── __init__.py
└── zone_viewer/
    ├── __init__.py
    ├── test_payload.py
    └── test_server.py
```

JavaScript tests remain package-local:

```text
src/libs/models/sr/tools/zone_viewer/tests/
└── zone_primitive.test.js
```

Do not add top-level `scripts/sr_v1_5`, `tools/sr_zone_viewer`, a new web
application, or a second SR model tree.

## Dependency Direction And Blast Radius

The approved dependency direction is:

```text
configs/sr.yaml
  -> existing SRConfigResolver
  -> existing eight-parameter ResolvedSRConfig

configs/sr_inputs.yaml
  -> baseline_trial.config
  -> resolved ATR input specification and provenance

configs/sr_trials/taousdt_1d_baseline.yaml
  -> baseline_trial.config
  -> immutable trial specification

baseline_trial.dataset
  -> BinanceNativeAdapter
  -> existing ATR
  -> ClosedBar contracts

baseline_trial.runner
  -> create_initial_state
  -> replay_bars
  -> build_evaluation_trace
  -> compute_diagnostics

baseline_trial.artifacts
  -> explicit canonical serializers
  -> content-addressed evidence directory

zone_viewer.payload
  -> source bars
  -> SREvaluationTrace
  -> SRDiagnostics
  -> deterministic chart payload

zone_viewer JavaScript
  -> chart_payload.json only
  -> lightweight-charts 5.2.0
```

Architectural rules:

- Core SR packages never import `scripts` or `tools`.
- `libs.models.sr.__init__` does not export either package.
- `scripts/__init__.py`, `baseline_trial/__init__.py`, `tools/__init__.py`,
  and `zone_viewer/__init__.py` perform no I/O, configuration loading, data
  fetching, Node execution, server startup, or model replay.
- The integration boundary may import pandas, PyYAML, the Binance ingestion
  adapter, and the existing ATR feature. Those dependencies remain prohibited
  from SR core, config, domain, detection, association, lifecycle, replay,
  serialization, and evaluation.
- The viewer consumes exported evidence. It must never call the engine, replay,
  lifecycle, detection, association, Binance, ATR, or YAML directly.
- The Python model and evidence output cannot depend on whether the viewer is
  installed, started, or rendered.
- Do not modify `BinanceNativeAdapter`,
  `fetch_binance_native_ohlcv`, or the ATR implementation.
- Do not import the RegimeV2 normalization helper. It sorts and drops invalid
  rows for its own research use; V1.5 requires fail-closed ordering and missing
  value semantics.

Expected blast radius is restricted to the new leaf integration/viewer
packages, two dedicated YAML documents, narrow import-boundary allowlisting,
and the exact package-lock exception. The existing SR behavior and public root
surface must remain byte-for-byte unchanged against the base.

## Configuration Contracts

No semantic value may be embedded in Python or JavaScript when it belongs to
the input, trial, or viewer configuration. Software schema versions, enum
values, field names, and hashing domain separators are protocol constants, not
hyperparameters.

Use the existing recursive duplicate-key-safe `load_sr_config` YAML parsing
boundary to load mappings, then validate the separate schemas in
`baseline_trial.config`. Do not weaken or modify the existing SRConfig schema.

### SR input configuration

Create `configs/sr_inputs.yaml` with this exact initial content:

```yaml
version: "1"

defaults:
  atr:
    method: wilder_rma
    period: 14
    seed: sma

timeframes: {}

assets: {}
```

The typed resolver must support exactly:

```text
defaults
-> timeframe override
-> exact asset/timeframe override
```

Asset-wide overrides are not a layer and must be rejected, matching the current
SR configuration policy.

Approved ATR fields:

- `method`: exact non-empty string; V1.5 accepts only `wilder_rma`;
- `period`: exact integer >= 1;
- `seed`: exact non-empty string; V1.5 accepts only `sma`.

The resolved input contract must include:

```text
version
asset
timeframe
atr_method
atr_period
atr_seed
field_provenance
resolved_input_hash
```

Provenance sources are exactly:

```text
defaults
timeframe:<timeframe>
asset_timeframe:<asset>:<timeframe>
```

The hash covers the schema version, asset, timeframe, all resolved values, and
canonical field provenance. No call-time semantic override layer is allowed.

This new input configuration is upstream evidence identity. It does not alter
the exact eight paths or hash semantics owned by `ResolvedSRConfig`.

### Baseline trial configuration

Create `configs/sr_trials/taousdt_1d_baseline.yaml` with one immutable trial:

```yaml
version: "1"

trial:
  trial_name: sr-v1.5-taousdt-1d-baseline
  venue: binance_usdm
  symbol: TAOUSDT
  timeframe: 1d
  requested_since: "2024-01-01T00:00:00Z"
  requested_until: "2026-06-30T23:59:59.999Z"
  adapter_limit: 1500
  gap_policy: reject
  sr_config_path: configs/sr.yaml
  input_config_path: configs/sr_inputs.yaml
  output_root: research/tmp_sr_v1_5

viewer:
  library: lightweight-charts
  library_version: 5.2.0
  attribution_logo: true
  live_zone_extent: viewport_right_edge
  show_terminal_by_default: false
  show_events_by_default: true
  background_color: "#131722"
  text_color: "#d1d4dc"
  grid_color: "#2a2e39"
  support_border_color: "#26a69a"
  support_fill_color: "rgba(38, 166, 154, 0.18)"
  resistance_border_color: "#ef5350"
  resistance_fill_color: "rgba(239, 83, 80, 0.18)"
  pending_border_color: "#f2c94c"
  terminal_opacity: 0.35
  zone_line_width: 2
```

Reject unknown, missing, duplicate, wrong-type, non-UTC, contradictory, or
empty values. Validate that:

- symbol and timeframe match the resolved SR and input configurations;
- requested timestamps are strict UTC and since < until;
- `adapter_limit` is an exact positive integer and <= the adapter's approved
  one-call limit;
- gap policy is exactly `reject`;
- output root is a non-empty relative repository path with no parent traversal;
- viewer library and version match the pinned package;
- opacity is finite in [0, 1];
- line width is a positive exact integer;
- color strings are non-empty;
- no CLI value changes any semantic trial field.

The CLI accepts only the trial-config path. It must not expose symbol,
timeframe, date, ATR, SR parameter, gap policy, viewer style, or output path
overrides.

## Data Contract

### Provider boundary

Use:

`apps.ingestion_app.adapters.binance_native.BinanceNativeAdapter`

The trial calls `get_historical_ohlcv` once with:

- `TAOUSDT`;
- `1d`;
- the approved since/until values as epoch milliseconds; and
- `limit=1500`.

This approved window is below the one-call limit. General pagination is not
part of V1.5.

Do not fetch data during import or unit tests. Unit tests inject a fake exact
adapter boundary. Only the explicit live-trial command contacts Binance.

### Raw bar validation

The adapter result must contain at least:

```text
timestamp
open
high
low
close
volume
```

Validate in caller order, before any conversion:

- exact DataFrame boundary;
- non-empty result;
- required columns present;
- numeric values convertible without loss-producing coercion;
- every numeric value finite;
- timestamps are exact integer milliseconds;
- timestamps strictly increase and are unique;
- exact 1d cadence between every adjacent returned bar;
- OHLC values positive;
- low <= open/close <= high;
- volume finite and >= 0;
- first timestamp >= requested_since;
- every bar open and close lies inside the fixed historical cutoff;
- result length is below the configured adapter limit, so truncation cannot be
  mistaken for a complete dataset.

Do not sort, drop, fill, interpolate, deduplicate, round, resample, or repair
the adapter result. Reject the whole run on the first structural failure.

A later-than-requested first bar is allowed only as the provider's first
available listing bar. Record both requested and actual bounds. Once the first
bar exists, every 1d interval through the actual final bar must be present.

The fixed `requested_until` is historical. No current/open-candle heuristic or
wall-clock decision is needed. A returned bar whose derived close exceeds the
cutoff is rejected.

### ClosedBar mapping

For each validated raw bar:

- open time is the Binance `timestamp`;
- `closed_at = open_time + 1 day`;
- `bar_id = binance_usdm:TAOUSDT:1d:<open_timestamp_ms>`;
- OHLC values are copied without rounding;
- volume remains in source/chart evidence but is not added to `ClosedBar`;
- state key is exactly `SRStateKey("binance_usdm", "TAOUSDT", "1d")`.

## ATR Contract

Use the existing:

`libs.features.indicators.volatility.atr.ATR`

with the resolved period 14. Its approved identity for this trial is:

```text
method: wilder_rma
period: 14
seed: sma
implementation: libs.features.indicators.volatility.atr.ATR
implementation_contract: true_range_sma_seed_then_wilder_recursion_v1
```

Rules:

- compute true range only from the current and preceding confirmed bar;
- use the existing batch implementation without modifying or duplicating its
  formula;
- the first 14 returned ATR entries are warmup/unavailable under the existing
  implementation;
- construct model `ClosedBar` records beginning at the first finite,
  strictly-positive ATR value;
- reject any missing, non-finite, or non-positive ATR after the first valid ATR;
- record raw bar count, ATR warmup count, first ATR timestamp, model bar count,
  resolved input hash, and input provenance;
- no fallback ATR, rolling standard deviation, simple moving ATR alternative,
  period inference, or chart-side ATR calculation.

Required causal test: for every tested non-empty prefix long enough to contain
a valid ATR, ATR values for that prefix equal the corresponding full-run prefix
exactly.

ATR(14) is a fixed global baseline. Do not determine, test, promote, or write a
TAOUSDT/1d override in V1.5.

## Trial Execution

The only live command is:

```bash
PYTHONPATH=src .venv/bin/python -m \
  libs.models.sr.scripts.baseline_trial.cli \
  --config configs/sr_trials/taousdt_1d_baseline.yaml
```

Execution order:

1. load and validate the trial YAML;
2. load `configs/sr.yaml` through the existing loader and resolve
   `TAOUSDT/1d`;
3. load and resolve `configs/sr_inputs.yaml` for `TAOUSDT/1d`;
4. fetch and strictly validate the frozen raw dataset;
5. compute causal ATR and create exact `ClosedBar` records;
6. call `create_initial_state`;
7. call `replay_bars` once over the complete model-bar tuple;
8. call `build_evaluation_trace` with all snapshots and the resolved SR
   configuration;
9. call `compute_diagnostics`;
10. build the deterministic chart payload from the same source bars, trace, and
    diagnostics;
11. write one content-addressed evidence bundle;
12. print only a concise JSON summary containing trial name, bundle ID, output
    path, row counts, trace ID, and diagnostics ID.

No model method may observe a future bar. No later snapshot may revise an
earlier snapshot, observation, event, ATR value, or identity.

## Evidence Contracts And Artifacts

Define one trial protocol constant:

`SR_BASELINE_TRIAL_SCHEMA_VERSION = "1.0"`

This is not YAML configuration or a hyperparameter.

Use frozen exact-type Python contracts for:

- validated source dataset metadata;
- resolved input configuration;
- trial specification;
- ATR provenance;
- trial result;
- bundle member metadata;
- evidence manifest.

The bundle contains exactly:

```text
<output_root>/<bundle_id>/
├── manifest.json
├── source_bars.json
├── model_bars.json
├── trace.json
├── diagnostics.json
└── chart_payload.json
```

All JSON files:

- are UTF-8;
- use explicit primitive payload construction;
- use canonical key ordering and separators;
- represent UTC timestamps with the existing canonical UTC convention;
- preserve semantic tuple/list order;
- contain finite JSON numbers only;
- end with exactly one newline;
- are written without generic `repr`, pickle, `__dict__`, or reflection-based
  dataclass serialization.

The manifest records at least:

- trial schema and trial name;
- venue, provider adapter, symbol, timeframe;
- requested and actual data bounds;
- raw, warmup, and model row counts;
- gap and closed-bar policies;
- source-bars SHA-256;
- resolved SR config hash and exact field provenance;
- resolved input hash and exact field provenance;
- ATR method, period, seed, implementation identity, and first valid timestamp;
- repository implementation commit;
- SR/evaluation schema versions;
- trace ID and diagnostics ID;
- Lightweight Charts package name/version;
- chart payload schema version;
- every payload member's SHA-256 and byte length.

Bundle algorithm:

1. construct every non-manifest payload explicitly;
2. canonical-serialize each payload and compute its SHA-256;
3. construct the manifest semantic payload including ordered member hashes;
4. derive `bundle_id` from the manifest semantic payload excluding
   `bundle_id` itself;
5. insert the derived ID and write `manifest.json`;
6. write into a temporary sibling directory and atomically publish the final
   `<bundle_id>` directory;
7. never overwrite a different existing bundle;
8. if the same bundle already exists, rehash every file and accept it only when
   all bytes match.

A byte-identical rerun from the same implementation commit, input/configuration,
and source response must produce the same bundle ID and identical member bytes.

Generated bundles remain uncommitted. The coder handoff reports the exact local
bundle path and hashes needed for review.

## Chart Payload Contract

Define one software protocol constant:

`SR_ZONE_VIEWER_PAYLOAD_SCHEMA_VERSION = "1.0"`

`zone_viewer.payload` builds one deterministic JSON-safe payload containing:

- schema version;
- trial/bundle/config/input/trace/diagnostics identities;
- viewer configuration copied from validated YAML;
- candles in source order with open time and OHLC;
- one consolidated render record per unique zone;
- authoritative V1.4 events in trace order.

Zone consolidation rules:

- order by first observation position, then zone ID only as an explicit
  tie-breaker;
- immutable side, source, geometry, created_at, available_at, visible_from, and
  ATR-at-creation must agree across observations;
- `render_kind` is copied from V1.4;
- `visible_from` is copied exactly and is never backdated to `created_at`;
- terminal `visible_until` is the frozen V1.4 value;
- live `visible_until` remains JSON null;
- final status/counters come from the final authoritative observation;
- no geometry, lifecycle state, event, timestamp, score, or rank is inferred in
  JavaScript.

The viewer is a consumer of this payload, not a second model.

## Lightweight Charts Viewer

Pin exactly:

`"lightweight-charts": "5.2.0"`

in the package-local `package.json` and commit its package-local lockfile.
Do not use `latest`, a caret, tilde, CDN, master build, or floating URL.

Version 5.2.0 is the approved latest release as of 2026-07-15. If it cannot be
installed exactly, stop and report the blocker rather than substituting a
different release.

Use plain HTML, CSS, JavaScript ES modules, and Node's built-in test runner.
Do not add React, Vue, Vite, Webpack, Rollup, TypeScript, a frontend application,
or a JavaScript test framework.

Viewer requirements:

- candlesticks use the v5 `chart.addSeries(CandlestickSeries, ...)` API;
- attach one custom series primitive to the candlestick series for all zones;
- do not attach one primitive per zone;
- use the series primitive pane view/renderer APIs and series/time-scale
  coordinate conversions;
- BAND draws a filled rectangle from lower to upper bound;
- LINE draws a horizontal segment at center;
- x-start is exactly `visible_from`;
- terminal x-end is exactly `visible_until`;
- live zones with null `visible_until` draw to the current viewport right edge
  without changing their payload;
- support, resistance, pending, and terminal appearance comes only from the
  validated viewer configuration in the payload;
- default terminal/event visibility follows the YAML;
- authoritative events render as markers, including
  CREATED, TOUCHED, BREACH_STARTED, FALSE_BREAKOUT, BREAK_CONFIRMED, and EXPIRED;
- custom primitive hit testing provides a small hover detail surface containing
  zone ID, side, final status, bounds, visibility window, touch count, fakeout
  count, and pending count;
- no score, confidence, strength, quality, ranking, return, or PnL is displayed;
- preserve TradingView's required creator attribution and user-visible link by
  enabling the supported attribution logo and retaining required notice/license
  material.

`server.py` is a local standard-library-only static server for the package
viewer and one selected bundle. It must:

- validate the bundle manifest and all member hashes before serving;
- bind to loopback by default;
- never fetch market data or mutate evidence;
- reject paths outside the viewer and selected bundle roots;
- set correct JSON/HTML/JS/CSS content types;
- perform no action on import.

## Implementation Order

1. Reproduce the approved 294-test SR baseline and boundary checks.
2. Create the branch from the exact base while preserving unrelated dirty
   artifacts/drafts.
3. Add `sr_inputs.yaml`, the fixed trial YAML, typed contracts, and fail-closed
   configuration resolution tests.
4. Add strict adapter-result validation and exact ClosedBar mapping using a fake
   adapter in tests.
5. Bind the existing Wilder ATR implementation and add prefix-causality/warmup
   tests.
6. Add the pure runner around existing state creation, replay, trace, and
   diagnostics APIs.
7. Add explicit canonical artifact serializers and content-addressed bundle
   publication.
8. Add the deterministic chart-payload builder.
9. Add the package-local Lightweight Charts 5.2.0 viewer, lockfile exception,
   primitive, server, and Node tests.
10. Narrowly update import-boundary tests without weakening core restrictions.
11. Commit implementation.
12. Run the fixed live TAOUSDT/1d trial from that implementation commit twice
    and prove bundle byte identity.
13. Start the local viewer against the verified bundle and perform the required
    visual smoke checks.
14. Run all acceptance commands and independent probes.
15. Write and separately commit the coder-to-review handoff.

## Acceptance Criteria

### Configuration

- Both YAML documents reject recursive duplicate keys.
- Unknown and malformed keys fail closed.
- Input precedence is exactly defaults -> timeframe -> exact asset/timeframe.
- Asset-wide and call-time overrides are rejected.
- ATR resolves to global Wilder/RMA SMA-seeded period 14 for TAOUSDT/1d with
  exact provenance.
- Existing `configs/sr.yaml`, its eight paths, values, precedence, config hash
  rules, and provenance behavior are unchanged.

### Data and causality

- Invalid/missing/duplicate/out-of-order/gapped/non-finite bars reject the run.
- No sorting, dropping, coercive repair, filling, or resampling occurs.
- Closed timestamps and bar IDs are deterministic.
- The current/open bar cannot enter the fixed historical trial.
- ATR warmup and first valid timestamp are explicit.
- ATR prefixes equal full-run prefixes exactly.
- Extending the input cannot change earlier ClosedBars, snapshots,
  observations, events, ATR values, or identities.
- Existing checkpoint/replay parity remains green.

### Evidence

- All member files rehash to the manifest.
- Bundle identity changes when any source row, SR config identity, input config
  identity, ATR identity, trial field, viewer field, chart payload, code commit,
  or ordered evidence record changes.
- Repeated equal runs are byte-identical.
- Existing bundle collision/mismatch fails closed.
- No committed live data or generated bundle is introduced.

### Visualization

- Candles match `source_bars.json`.
- LINE and BAND geometry match the V1.4 observations exactly.
- No zone appears before `available_at/visible_from`.
- Terminal zones stop at their frozen terminal close.
- Live zones extend only visually to the viewport edge.
- FALSE_BREAKOUT is visually distinguishable from BREAK_CONFIRMED and does not
  terminate or resize its zone.
- Support and resistance render distinctly.
- Hover content is sourced from the payload only.
- TradingView attribution is visible.
- Viewer absence or failure cannot affect any Python evidence identity except
  the explicitly versioned/configured chart-payload member.

### Boundaries and regressions

- Importing `libs.models.sr` remains side-effect free and does not import
  scripts, tools, pandas, PyYAML, Binance, Node, or the viewer.
- Importing empty scripts/tools package boundaries performs no work.
- The new integration allowlist applies only beneath
  `libs.models.sr.scripts.baseline_trial`.
- Existing core prohibited-import scans remain unchanged.
- Existing 294 SR tests remain green.
- Existing lifecycle, evaluation, replay, serialization, YAML, trendline-family
  boundary, Ruff, compile, and diff checks remain green.
- No existing SR production behavior or public root export changes.

## Validation Checklist

Run the approved baseline before implementation, then report final results for:

```bash
.venv/bin/python -m pytest tests/models/sr/scripts/baseline_trial -q
.venv/bin/python -m pytest tests/models/sr/tools/zone_viewer -q
.venv/bin/python -m pytest \
  tests/models/sr/domain \
  tests/models/sr/replay \
  tests/models/sr/evaluation \
  tests/models/sr/scripts \
  tests/models/sr/tools -q
.venv/bin/python -m pytest tests/models/sr/lifecycle -q
.venv/bin/python -m pytest tests/models/sr -q
.venv/bin/python -m pytest \
  tests/models/trendline_family/test_import_boundaries.py -q
ruff check src/libs/models/sr tests/models/sr
.venv/bin/python -m compileall -q src/libs/models/sr
PYTHONPATH=src .venv/bin/python -c \
  "import sys; import libs.models.sr; assert not any(name.startswith('libs.models.sr.scripts') or name.startswith('libs.models.sr.tools') for name in sys.modules); print('ok')"
git diff --quiet 6ed2951 -- \
  configs/sr.yaml \
  src/apps/ingestion_app/adapters/binance_native.py \
  src/libs/features/indicators/volatility/atr.py \
  src/libs/models/sr/domain \
  src/libs/models/sr/config \
  src/libs/models/sr/adapters \
  src/libs/models/sr/detection \
  src/libs/models/sr/association \
  src/libs/models/sr/lifecycle \
  src/libs/models/sr/replay \
  src/libs/models/sr/serialization \
  src/libs/models/sr/evaluation
git diff --check
```

From `src/libs/models/sr/tools/zone_viewer` run:

```bash
npm ci
npm test
node --check src/main.js
node --check src/zone_primitive.js
```

Run the live trial twice from the implementation commit:

```bash
PYTHONPATH=src .venv/bin/python -m \
  libs.models.sr.scripts.baseline_trial.cli \
  --config configs/sr_trials/taousdt_1d_baseline.yaml
```

Required independent probes:

1. recursive duplicate-key rejection in both new YAML schemas;
2. global/timeframe/exact asset-timeframe ATR precedence and provenance;
3. wrong asset/timeframe and call-time semantic override rejection;
4. invalid, duplicate, out-of-order, gapped, truncated, and open-bar data
   rejection;
5. exact raw-to-ClosedBar timestamp and ID conversion;
6. ATR(14) SMA seed, warmup boundary, positive values, and prefix causality;
7. complete replay -> trace -> diagnostics identity binding;
8. unchanged replay prefix and checkpoint parity;
9. bundle member rehash, collision rejection, and byte-identical rerun;
10. chart payload LINE/BAND and live/terminal visibility mapping;
11. fakeout marker without zone termination or geometry change;
12. local server traversal rejection and manifest validation;
13. root import isolation and empty package side-effect checks;
14. manual visual smoke: candles, support/resistance, LINE/BAND, terminal cutoff,
    live extension, fakeout/break distinction, hover data, and attribution.

Classify any text matches from denylist tests; do not claim zero matches when
the test source itself contains prohibited names.

## Explicit Non-Goals

Do not implement:

- ATR-period optimization, sensitivity search, grid search, Optuna, Bayesian
  optimization, walk-forward selection, holdout selection, or promotion;
- any TAOUSDT/1d ATR override;
- tuning or changing any of the eight SR parameters;
- future-return, reaction-quality, excursion, PnL, win-rate, Sharpe, drawdown,
  cost, confidence, score, rank, or trading-readiness metrics;
- new features, volume-based model behavior, order book, funding, open interest,
  regime, trendline, clustering, regression, ML, or multi-timeframe inputs;
- alternate pivot, association, lifecycle, fakeout, break, expiry, or capacity
  rules;
- live streaming, websocket, scheduler, worker, database, cache, cloud storage,
  API, signal, strategy, risk, execution, or portfolio integration;
- Binance adapter redesign, RegimeV2 helper changes, generalized provider
  abstraction, pagination, data repair, or TradingView market-data fetching;
- React, Vue, TypeScript, bundlers, a frontend app, chart editing/drawing tools,
  user-created zones, or a hosted/public viewer;
- checkpoint schema changes, terminal pruning, event-history persistence, or
  legacy SR integration;
- changes to SR root exports or existing core package behavior;
- V1.6 calibration work.

## Blocking Issues And Follow-Ups

There are no known blockers to begin V1.5 from the exact base.

Non-blocking future work, excluded from implementation:

- V1.6 will define an approved out-of-sample objective before testing ATR
  candidates.
- ATR candidates will be predeclared and tested with the eight SR parameters
  frozen first.
- An exact asset/timeframe override will be promoted only after stable
  walk-forward and untouched-holdout evidence; otherwise global ATR(14)
  remains authoritative.
- Broader asset/timeframe cohorts and shorter timeframes may require a separately
  approved pagination/data-window extension.

This handoff is complete enough for the coding worker to act without guessing.

## Mandatory Coder Handoff

Return:

`plans/coder-to-review-sr-v1.5-baseline-trial-v1.md`

containing:

- exact base, target branch, implementation commit, and separate handoff commit;
- exact added/modified files;
- dependency and import-boundary graph;
- new YAML schemas, precedence, provenance, and hashes;
- Binance adapter call and strict dataset validation behavior;
- raw/model row counts, actual time bounds, source hash, ATR warmup, and first
  valid ATR timestamp from the live run;
- proof that the eight existing SR paths and core behavior are unchanged;
- replay, trace, diagnostics, prefix-causality, and checkpoint-parity evidence;
- evidence-bundle contract, bundle ID, exact local path, member hashes, and
  byte-identical rerun proof;
- Lightweight Charts exact version/lockfile, primitive design, payload identity,
  server behavior, attribution, and manual visual smoke results;
- baseline and final Python tests, Node tests, Ruff, compile, imports,
  boundaries, diff checks, and independent probes;
- confirmation that generated live data/evidence was not committed;
- confirmation that no tuning, feature, score, label, strategy/runtime
  integration, V1.6 work, or merge was performed;
- known risks and deliberately deferred work.

## Stop Condition

Stop after V1.5 implementation, live bounded trial, validation, commits, and
coder-to-review handoff.

Do not merge. Do not begin ATR calibration, parameter optimization, feature
work, broader asset/timeframe trials, runtime integration, or V1.6 without
explicit Quant Review approval and a new approved handoff.
