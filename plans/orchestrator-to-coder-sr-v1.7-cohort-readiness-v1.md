---
goal: Implement SR-V1.7 as a frozen-config multi-asset 1d cohort-readiness trial without parameter tuning, feature expansion, production configuration changes, or runtime integration.
stage: orchestrator-to-coder
date_created: 2026-07-16
last_updated: 2026-07-16
owner: Quant Orchestrator
status: Approved
tags: [handoff, quant, sr, cohort-readiness, multi-asset, baseline, evidence, leakage-control]
source_agent: Quant Orchestrator
target_agent: Coder Agent
base_commit: 72072d2076af379d807cdbd390bb73ff82fe5f8c
source_branch: feature/sr-v1.6-atr-calibration
target_branch: feature/sr-v1.7-cohort-readiness
---

# Orchestrator To Coder: SR-V1.7 Cohort Readiness v1

## Objective

SR-V1.6 is approved and closed. It retained global Wilder/RMA ATR(14), selected
no challenger, made no production override, and produced only 36 completed
TAOUSDT/1d baseline first-touch outcomes across the six development folds.
That evidence is sufficient to reject an ATR override, but it is not sufficient
to tune the remaining eight SR parameters without material overfitting risk.

Implement one bounded, development-only cohort trial answering:

> With global Wilder/RMA ATR(14) and all eight SR parameters frozen, does the
> current SR model produce causal, deterministic, non-degenerate, and adequately
> sampled zone behavior across a predeclared liquid 1d asset cohort, so that a
> later one-family parameter-sensitivity study would be statistically and
> operationally defensible?

The approved cohort, in canonical order, is:

1. `TAOUSDT` — anchor and exact V1.6 parity control;
2. `BTCUSDT`;
3. `ETHUSDT`;
4. `SOLUSDT`.

All assets use Binance USD-M and timeframe `1d`. Do not add another asset or
timeframe after observing results. Do not interpret this phase as profitability,
alpha, parameter-selection, or trading-readiness evidence.

V1.7 may return only one research disposition:

- `READY_FOR_PARAMETER_SENSITIVITY`;
- `INSUFFICIENT_EVIDENCE`; or
- `STRUCTURAL_ANOMALY`.

No disposition authorizes a production config edit, runtime integration, V1.8,
or merge.

## Scope Boundaries

### Exact base and branch

- Start from exact commit
  `72072d2076af379d807cdbd390bb73ff82fe5f8c` on
  `feature/sr-v1.6-atr-calibration`.
- Create `feature/sr-v1.7-cohort-readiness`.
- Do not merge.
- Preserve the pre-existing modified `.codebase-memory` artifacts and unrelated
  untracked plan drafts. Do not stage, rewrite, delete, or include them.
- Before editing existing symbols, use repository code intelligence and record
  the affected callers/flows. Keep the implementation additive wherever
  possible.

### Frozen model and protocol

The following are immutable throughout V1.7:

- `configs/sr.yaml` and all eight current SR parameter values:
  - `pivot_span_bars = 5`;
  - `zone_half_width_atr = 0.25`;
  - `merge_distance_atr = 0.50`;
  - `touch_tolerance_atr = 0.25`;
  - `break_buffer_atr = 0.25`;
  - `break_confirm_closes = 2`;
  - `max_age_bars = 50`;
  - `max_active_zones = 8`.
- `configs/sr_inputs.yaml`:
  - method `wilder_rma`;
  - period `14`;
  - seed `sma`;
  - no timeframe or asset/timeframe override.
- All detection, association, lifecycle, replay, serialization, and evaluation
  behavior.
- Outcome start offset `1` and horizon `10`.
- ATR(14) as the model input and evaluation denominator.
- The V1.6 common-start policy. Preserve the period-28 common causal start used
  by the approved V1.6 comparison so the TAOUSDT ATR(14) replay can reproduce
  exactly.
- The six half-open development folds:
  - `2024_q3: [2024-07-01T00:00:00Z, 2024-10-01T00:00:00Z)`;
  - `2024_q4: [2024-10-01T00:00:00Z, 2025-01-01T00:00:00Z)`;
  - `2025_q1: [2025-01-01T00:00:00Z, 2025-04-01T00:00:00Z)`;
  - `2025_q2: [2025-04-01T00:00:00Z, 2025-07-01T00:00:00Z)`;
  - `2025_q3: [2025-07-01T00:00:00Z, 2025-10-01T00:00:00Z)`;
  - `2025_q4: [2025-10-01T00:00:00Z, 2026-01-01T00:00:00Z)`.
- No state reset at fold boundaries. Each asset starts from an independent empty
  model state; state must never cross asset boundaries.

### Evidence classification

This is development-only readiness evidence:

- no candidate parameter values exist;
- no selection or ranking occurs;
- no sealed or holdout source is created;
- no holdout data is read or inferred;
- no production recommendation is made;
- outcome quality is descriptive and is not a readiness pass/fail gate.

Do not reuse any contaminated V1.6 sealed or holdout artifact. The earlier
`9892862e…`, `d484c2f…`, `d797af79…`, `483fcbb4…`, and `5b1b5b32…` evidence
remains permanently excluded.

### Source policy

TAOUSDT is not fetched. Validate and reuse only the approved V1.6 development
capsule:

- source ID:
  `fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120`;
- path:
  `research/tmp_sr_v1_6/source/development/fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120/`;
- rows: `629`;
- bars SHA-256:
  `703367048f4ed7dc432ca9dfe0ad4afdc5a56eb2a508597ef00bdc3de8b81163`;
- first open: `2024-04-11T00:00:00Z`;
- last causal close: `2025-12-31T00:00:00Z`.

If the exact TAOUSDT capsule is absent or fails the current V1.6 validator, stop
as `Blocked`. Do not rebuild it from the contaminated 811-row parent and do not
contact Binance for TAOUSDT.

For BTCUSDT, ETHUSDT, and SOLUSDT:

- use the existing
  `apps.ingestion_app.adapters.binance_native.BinanceNativeAdapter`;
- fetch each asset exactly once after the implementation commit exists;
- use one bounded request per asset with adapter limit `1000`;
- use the same venue, `1d` interval, and exact UTC timestamp grid as the
  validated TAOUSDT development capsule;
- require every returned bar timestamp to match that grid exactly;
- require strict increasing order, unique bars, finite positive OHLC, nonnegative
  volume, valid OHLC relationships, UTC, exact asset/venue/timeframe identity,
  closed bars only, and no missing or extra interval;
- reject rather than sort, drop, fill, interpolate, deduplicate, resample,
  round, or repair;
- reject a result whose derived `closed_at` exceeds the fixed source boundary;
- publish a deterministic content-addressed source capsule for each asset.

A source failure for any predeclared asset blocks the cohort. Do not silently
exclude it or publish a reduced cohort.

After the three provider calls, all further runs and validations must be local.
Do not fetch twice to demonstrate determinism. Demonstrate determinism by
loading and validating the frozen capsules repeatedly and producing identical
evaluation bundles from them.

## Affected Symbols, Modules, and Execution Flows

### Additive package

Create the descriptive package:

`src/libs/models/sr/scripts/cohort_readiness/`

Expected modules:

- `__init__.py` — empty or side-effect-free;
- `config.py` — strict YAML parsing and locked approved protocol;
- `contracts.py` — immutable asset, source, metric, cohort, and disposition
  contracts;
- `source.py` — TAOUSDT capsule validation plus bounded new-asset acquisition
  and source-cohort publication;
- `metrics.py` — readiness accounting and cross-asset aggregation;
- `artifacts.py` — canonical serialization, member hashes, content IDs, atomic
  publication, loading, and semantic recomputation;
- `runner.py` — source preparation and network-free cohort evaluation;
- `cli.py` — explicit command entry point with concise JSON output and no
  import-time work.

Create the mirrored tests:

`tests/models/sr/scripts/cohort_readiness/`

Expected test modules should mirror the implementation concerns rather than
forcing an arbitrary file count.

Add one committed trial config:

`configs/sr_trials/sr_v1_7_1d_cohort_readiness.yaml`

Generated source and evaluation evidence belongs under:

`research/tmp_sr_v1_7/`

Generated evidence must remain untracked and uncommitted.

### Dependency direction

The allowed execution flow is:

`cohort config`
→ `strict source preparation`
→ `validated per-asset source capsules`
→ `existing SR config/input resolution`
→ `existing causal replay and trace construction`
→ `locked first-touch accounting`
→ `per-asset readiness metrics`
→ `micro/macro cohort summary`
→ `content-addressed evidence bundle`.

Constraints:

- SR core packages must not import `scripts` or `tools`.
- The new package may import stable SR domain, config, replay, evaluation, and
  serialization APIs.
- Keep `BinanceNativeAdapter` behind a lazy runtime boundary. Importing the SR
  package or cohort package must not import provider/network clients.
- Do not modify the ingestion adapter.
- Do not refactor or move V1.5/V1.6 research symbols merely to share code.
- Prefer read-only reuse of the already-tested V1.6 first-touch calculation.
  If its type surface cannot be consumed cleanly, add a thin adapter in the new
  package and prove exact TAOUSDT parity. Do not copy and independently alter
  the metric formula.
- Do not change SR root exports.

### Blast radius

Expected code blast radius is limited to:

- the new `cohort_readiness` package;
- its mirrored tests;
- the new V1.7 trial YAML;
- optionally a minimal additive export within
  `src/libs/models/sr/scripts/cohort_readiness/__init__.py`.

Protected paths include:

- `configs/sr.yaml`;
- `configs/sr_inputs.yaml`;
- `src/libs/models/sr/domain/`;
- `src/libs/models/sr/config/`;
- `src/libs/models/sr/detection/`;
- `src/libs/models/sr/association/`;
- `src/libs/models/sr/lifecycle/`;
- `src/libs/models/sr/replay/`;
- `src/libs/models/sr/serialization/`;
- `src/libs/models/sr/evaluation/`;
- `src/libs/models/sr/scripts/baseline_trial/`;
- `src/libs/models/sr/scripts/atr_calibration/`;
- `src/libs/models/sr/tools/zone_viewer/`;
- `src/apps/ingestion_app/adapters/binance_native.py`;
- all approved V1.5/V1.6 handoffs and generated evidence.

Any required change to a protected path is a scope exception. Stop and return
to the Quant Orchestrator with the exact reason and impact analysis instead of
expanding the implementation.

## Data Contracts and Interfaces

### Trial YAML

The YAML must be fail-closed and contain exact, explicit sections for:

- version and trial name;
- venue, timeframe, and canonical asset order;
- TAOUSDT approved source ID/path/hash/row count/time bounds;
- provider adapter identity and limit for the other three assets;
- exact common timestamp-grid policy;
- SR and input config paths plus expected hashes;
- ATR method/period/seed and period-28 common-start policy;
- outcome offset/horizon/metric definition;
- the six folds;
- readiness sample gates;
- output root.

Reject:

- unknown or missing keys;
- YAML aliases or unsupported implicit types if existing loader policy rejects
  them;
- recursive duplicate keys;
- asset additions, removals, duplicates, or order changes;
- any venue/timeframe other than the approved values;
- any ATR or SR parameter value outside the frozen protocol;
- any fold, horizon, offset, source, hash, or path mutation.

### Source-cohort artifact

Publish a source-cohort bundle only after all four sources validate. It must
bind:

- implementation commit;
- V1.7 config hash;
- exact resolved SR/input hashes and field provenance per asset;
- canonical asset order;
- provider and request metadata;
- per-asset source ID, member hash, bars hash, row count, timestamp bounds, and
  timestamp-grid hash;
- the exact TAOUSDT V1.6 source identity;
- confirmation that TAOUSDT used zero provider calls;
- confirmation that the other three assets used exactly one provider call each.

Do not store credentials, headers, tokens, environment values, or request
secrets.

### Per-asset metrics

For each asset and each fold, report at least:

- eligible model bars;
- created zones;
- support and resistance counts;
- total, completed, and right-censored first touches;
- support/resistance completed counts;
- median favorable, adverse, and quality excursion in reference ATR(14);
- invalidated completed outcomes and invalidation rate;
- zone-creation density per 100 eligible bars;
- terminal cohort count and churn rate;
- fakeout, break-started, break-confirmed, touch, expired, and created event
  counts;
- complete event-accounting reconciliation.

Also report the pooled six-fold metrics per asset. Never reset state to compute
a fold.

### Cohort aggregation

Report both views:

1. micro: concatenate completed ATR-normalized outcome observations across
   assets, sum count denominators, compute rates from summed numerators and
   denominators, and compute medians from the concatenated outcome values;
2. macro: report the unweighted median, minimum, and maximum of the four
   per-asset pooled metrics.

Do not use an average of per-asset medians as the pooled primary result. Do not
pool raw prices. Preserve complete per-asset tables so no aggregate can hide an
asset failure.

### Readiness gates

An asset is sample-eligible only when:

- at least `4` completed first touches exist in a fold;
- at least `4` of the six folds are eligible; and
- at least `24` completed first touches exist across development.

These gates match V1.6's development coverage contract and are not quality
thresholds.

Disposition rules, in this exact order:

1. `STRUCTURAL_ANOMALY` when all sources/contracts are valid but any asset has
   zero created zones, zero support zones, zero resistance zones, zero first
   touches, or zero terminal cohort events across the complete development
   window. Record every anomaly reason; do not stop after the first.
2. `INSUFFICIENT_EVIDENCE` when no structural anomaly exists but one or more
   assets fail any sample-eligibility gate. Record every failed asset/fold/gate.
3. `READY_FOR_PARAMETER_SENSITIVITY` only when all four assets have no
   structural anomaly and all four satisfy every sample gate.

Positive or negative reaction quality, cross-asset dispersion, fakeout rate,
and lifecycle rate are descriptive. They must not be added as hidden readiness
gates after results are known.

### Evaluation artifact

The final cohort evidence bundle must bind:

- exact source-cohort bundle ID;
- implementation commit and all config/source hashes;
- locked protocol payload;
- per-asset replay/trace identities;
- per-fold and pooled per-asset metrics;
- micro and macro cohort aggregates;
- readiness gate results and exact reasons;
- final disposition;
- member hashes and top-level bundle content ID.

Validation must rebuild all replays and metrics from the validated source
capsules and require exact semantic payload equality. Recomputing only hashes is
insufficient.

## Implementation Order

1. Verify exact base commit, branch, and dirty-worktree inventory.
2. Run code-intelligence impact checks for any existing symbol considered for
   reuse or modification.
3. Create `feature/sr-v1.7-cohort-readiness` from the exact base.
4. Add the locked V1.7 YAML, package contracts/config, and unit tests.
5. Add source validation/publication with fake adapters; prove provider call
   counts and fail-closed data behavior.
6. Add per-asset replay/metrics with exact TAOUSDT V1.6 parity tests.
7. Add micro/macro aggregation and ordered disposition logic.
8. Add deterministic artifact publication/loading and semantic recomputation.
9. Add the runner and CLI with lazy provider import and network-free evaluation.
10. Run targeted tests, full SR tests, boundaries, Ruff, compile, and diff
    checks.
11. Commit implementation, tests, and trial YAML only.
12. Verify the exact TAOUSDT development capsule. If unavailable or invalid,
    stop as `Blocked`.
13. Run source preparation once: zero TAOUSDT provider calls and exactly one
    provider call for each of BTCUSDT, ETHUSDT, and SOLUSDT.
14. Validate and reload the frozen source-cohort bundle twice without network.
15. Run cohort evaluation twice from the same source bundle and require
    identical bundle IDs and byte-identical members.
16. Run positive and adversarial independent probes.
17. Create
    `plans/coder-to-review-sr-v1.7-cohort-readiness-v1.md`.
18. Commit the coder-to-review handoff separately.
19. Stop. Do not edit config, merge, or begin V1.8.

## Acceptance Criteria

V1.7 is review-ready only when:

- exact base lineage and protected dirty paths are preserved;
- the implementation stays inside the approved additive scope;
- TAOUSDT uses the exact approved 629-row V1.6 development capsule and makes no
  provider call;
- BTCUSDT, ETHUSDT, and SOLUSDT each make exactly one bounded provider call;
- all four assets share the exact validated daily timestamp grid;
- ATR(14), all eight SR parameters, lifecycle behavior, common-start policy,
  folds, and outcome protocol remain frozen;
- TAOUSDT replay, trace accounting, and every fold/pooled ATR(14) metric match
  the approved V1.6 baseline exactly;
- each asset's state is continuous across folds and isolated from other assets;
- source, trace, checkpoint, and metric identities are causal and deterministic;
- per-asset, micro, and macro metrics reconcile exactly;
- disposition follows the predeclared ordered rules;
- validators reject syntactic, identity, member, hash, source, protocol, metric,
  disposition, and duplicate-key tampering;
- repeated evaluation produces identical IDs and byte-identical members;
- no generated source/evidence is committed;
- production config and every protected path remain unchanged;
- all targeted and full validations pass;
- branch remains unmerged.

The research result may legitimately be any of the three approved
dispositions. A losing, mixed, or under-sampled result does not invalidate a
correct implementation.

## Validation Checklist

### Required automated coverage

Cover at least:

- exact trial schema and approved constant lock;
- asset order/addition/removal/duplicate rejection;
- recursive duplicate-key rejection;
- TAOUSDT exact source identity and zero-fetch enforcement;
- exactly one fetch for each new asset;
- missing, duplicated, reordered, extra, open, late, malformed, nonfinite, or
  identity-mismatched bars;
- timestamp-grid equality across all assets;
- provider failure and atomic source publication;
- no network path reachable during evaluation;
- ATR prefix causality and period-28 common-start parity;
- independent state per asset and no state reset at fold boundaries;
- half-open fold boundary behavior;
- exact TAOUSDT V1.6 replay/metric parity;
- complete event-count reconciliation;
- micro outcome-level pooling and denominator-weighted rates;
- macro unweighted median/min/max aggregation;
- all three dispositions and ordering when multiple conditions fail;
- deterministic canonical asset order and artifact identity;
- byte-identical repeated evaluation;
- syntactic rehash, semantic rehash, member swap, asset swap, source mutation,
  metric mutation, disposition mutation, protocol mutation, and duplicate-key
  tamper rejection;
- import boundary and no import-time provider/network work;
- protected-path diff assertions.

### Required commands

Run from repository root using the project environment:

~~~bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/models/sr/scripts/cohort_readiness
PYTHONPATH=src .venv/bin/python -m pytest -q tests/models/sr
PYTHONPATH=src .venv/bin/python -m pytest -q tests/models/sr/test_import_boundaries.py tests/models/sr/adapters/test_import_boundaries.py
.venv/bin/ruff check src/libs/models/sr tests/models/sr
.venv/bin/python -m compileall -q src/libs/models/sr tests/models/sr
git diff --check
~~~

If Ruff is unavailable inside the virtualenv, use the already-established
system Ruff and record that fact. Do not install a dependency merely for this
phase.

Before committing, run repository change detection and verify that only the
new package, mirrored tests, and V1.7 trial YAML are in the implementation
commit.

### Independent probes

Run and record at least:

1. exact TAOUSDT V1.6 baseline parity;
2. prefix mutation proving no later bar can change an earlier trace/metric;
3. checkpoint split/reload parity for every asset;
4. provider spies proving `0/1/1/1` calls in canonical asset order;
5. network denial during both evaluation runs;
6. cross-asset state-isolation under asset execution-order permutation;
7. micro aggregation recomputed directly from outcome rows;
8. a fully rehashed source-bar mutation rejected semantically;
9. a fully rehashed metric/disposition mutation rejected by recomputation;
10. byte-identical repeated evaluation.

## Explicit Non-Goals

Do not implement:

- tuning, search, optimization, ranking, selection, ablation, or promotion of
  any SR or ATR parameter;
- new SR parameters or a change to the eight-parameter surface;
- any asset or timeframe override in `configs/sr.yaml` or
  `configs/sr_inputs.yaml`;
- any feature, score, confidence, rank, strength, probability, or composite
  context output;
- volume-based behavior, order book, funding, open interest, regime,
  trendlines, regression, clustering, ML, or multi-timeframe inputs;
- 4h, 1h, or any timeframe other than 1d;
- pagination, data repair, generalized provider abstraction, adapter redesign,
  retries that spend a source request twice, or a market-data database;
- PnL, trades, win rate, Sharpe, drawdown, fees, slippage, position sizing, or
  trading-readiness claims;
- signal, strategy, risk, execution, portfolio, scheduler, worker, websocket,
  live-stream, API, database, cache, Turso, cloud, or deployment integration;
- checkpoint schema changes, terminal pruning, event-history persistence, or
  legacy SR migration;
- viewer changes, event-label overlap polish, browser smoke, or frontend work;
- changes to SR root exports or any protected V1.5/V1.6 behavior/evidence;
- V1.8 work or merge.

## Blocking Issues and Follow-Ups

There is no known blocker to implementation from exact base `72072d2`.

Blocking conditions during execution:

- exact TAOUSDT development capsule absent or invalid;
- any protected path must change;
- any approved asset cannot provide the exact source timestamp grid in one
  bounded request;
- source identity cannot be frozen before evaluation;
- provider/network access is unavailable for one of the three new assets;
- deterministic semantic recomputation cannot be demonstrated.

On a blocker, do not reduce the cohort or change the window. Return a
`Blocked` coder handoff with evidence.

Non-blocking future work, excluded here:

- V1.8 may define one low-dimensional parameter-family sensitivity study only
  if V1.7 returns `READY_FOR_PARAMETER_SENSITIVITY` and Quant Review approves.
- Detection geometry is the likely first family
  (`pivot_span_bars` and `zone_half_width_atr`), but its candidates and gates
  are not approved by this handoff.
- Shorter timeframes require a separate pagination/data-window design so asset
  and timeframe effects are not mixed.
- Runtime integration must remain context-only and shadow-first when separately
  approved.
- Feature additions require an explicit hypothesis, ablation, and overfitting
  discussion before implementation.
- Existing viewer event-label overlap remains UX polish only.

## Mandatory Coder-To-Reviewer Handoff

Return:

`plans/coder-to-review-sr-v1.7-cohort-readiness-v1.md`

with:

- exact base, branch, implementation commit, and separate handoff commit;
- file inventory and code-intelligence blast-radius result;
- protected-path diff proof;
- exact trial config and resolved SR/input hashes;
- all four source IDs, hashes, rows, time bounds, and timestamp-grid identity;
- provider call counts and confirmation of no TAOUSDT fetch;
- TAOUSDT V1.6 parity table;
- per-asset fold and pooled metric tables;
- micro and macro cohort tables with aggregation reconciliation;
- every sample/anomaly gate and exact reason;
- final disposition;
- source/evaluation bundle IDs and local paths;
- deterministic rerun IDs and byte-comparison result;
- test counts, Ruff, compile, imports, boundaries, diff checks, and independent
  probe results;
- confirmation that no holdout, tuning, selection, feature, PnL, runtime,
  database, config edit, generated-evidence commit, merge, or V1.8 work occurred;
- confirmation that pre-existing artifacts and drafts remain untouched;
- residual limitations and non-blocking follow-ups.

Use `Review Ready` only if implementation, all four source validations,
evidence generation, deterministic reruns, adversarial probes, and validation
pass. Use `Blocked` for missing source/provider evidence or an approved scope
exception. Use `Needs Revision` for implementation or test defects.

This handoff is complete enough for the coding worker to act without guessing.
