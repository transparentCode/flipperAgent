---
goal: Test whether causally confirmed pivot rejection-wick bands outperform matched prior-close naive bands on the frozen TAOUSDT 1d development cohort.
stage: architect-to-coder
date_created: 2026-07-19
last_updated: 2026-07-19
owner: Quant Orchestrator
status: Ready
tags: [handoff, quant, sr, v2.1, pivot, rejection-wick, adequacy, kiss]
approved_by: user
approval_date: 2026-07-19
source_agent: Quant Orchestrator
target_agent: Codex quant-coder
source_base: 83428720308f7cce8a3ba5823911b23638792d96
depends_on: plans/approval-decision-sr-v2.0-displacement-origin-adequacy-v1.md
---

# SR-V2.1 — Causal Pivot-Rejection Band Adequacy

## Objective

Implement and evaluate one locked price-structure hypothesis:

> For the existing strict, causally confirmed pivot rule, the pivot candle's
> directional rejection-wick band produces better first-revisit reaction
> quality than a same-width band centered on the immediately preceding close.

This is not a new claim that pivots/fractals exist in the model. V1 already
uses strict confirmed pivots. V2.1 changes only the candidate zone
representation from a synthetic ATR envelope around the pivot extreme to the
observed rejection-wick range.

The hypothesis is fixed before evidence:

- pivot confirmation span: 5 bars left and 5 bars right;
- RESISTANCE geometry: `[max(open, close), high]` of the pivot candle;
- SUPPORT geometry: `[low, min(open, close)]` of the pivot candle;
- no smoothing, ZigZag, volume, score, trend, indicator, feature ensemble, or
  learned component;
- comparison: matched prior-close naive band with identical width;
- primary metric: paired real quality minus same-side naive quality;
- frozen TAOUSDT 1d development source and V2.0 gates.

This document combines the research hypothesis lock and implementation handoff
to reduce agent round trips. User approval was recorded on 2026-07-19; it now
authorizes one implementation/evidence pass.

## Scope Boundaries

Create branch `feature/sr-v2.1-pivot-rejection-adequacy` from approved
research-only commit
`83428720308f7cce8a3ba5823911b23638792d96`.

The source branch remains unmerged. Creating V2.1 from this commit is a stacked
research branch, not permission to merge V2.0 or V2.1 into `main`.

Remain inside:

- active `src/libs/models/sr`;
- strict V2.1 trial YAML;
- focused SR tests;
- ignored V2.1 evidence output;
- one coder-to-review handoff.

Use only the existing frozen TAOUSDT Binance USD-M 1d development source:

- outer cohort bundle:
  `6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9`;
- canonical source capsule:
  `d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925`;
- source ID:
  `fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120`;
- 629 rows through 2025-12-31;
- point-in-time Wilder ATR(14), SMA seed, common start index 28;
- the same six quarterly development folds used by V2.0.

Do not call a provider, refresh data, open holdout, change folds, add rows,
lower gates, or tune after observing results.

The legacy `src/libs/sr` pivot/fractal kernels may be read as historical
reference only. Do not import, copy, adapt, register, or revive them. Their EMA
smoothing, volume/dominance scoring, asymmetric windows, channel modes, and
defaults are outside this hypothesis.

## Affected Symbols, Modules, and Flows

Expected new or narrowly changed surfaces:

- `src/libs/models/sr/detection/pivot_rejection.py`;
- `src/libs/models/sr/detection/__init__.py`, only if a public pure-function
  export is needed;
- detector-neutral first-revisit band services under
  `src/libs/models/sr/research/metrics/`;
- canonical study, including its CLI:
  `src/libs/models/sr/research/studies/pivot_rejection_adequacy/`;
- `configs/sr_trials/sr_v2_1_taousdt_1d_pivot_rejection_adequacy.yaml`;
- focused tests mirroring those surfaces;
- `plans/coder-to-review-sr-v2.1-pivot-rejection-adequacy-v1.md`.

The detector must remain unregistered and must not be wired into `SREngine`.

The execution flow is:

1. Load and validate the exact frozen source and strict V2.1 config.
2. Compute point-in-time Wilder ATR(14).
3. Detect strict pivots using only bars available through confirmation.
4. Convert each eligible pivot's rejection wick to one real band.
5. Build exact prior-close controls for every in-fold real candidate.
6. Evaluate real and control bands independently.
7. Pair completed real outcomes only with their same-side controls.
8. Compute frozen readiness/utility gates and disposition.
9. Publish and semantically reconstruct a deterministic evidence bundle.

Before changing an existing symbol, run the repository's codebase-memory impact
workflow. If unavailable, record that limitation and inspect imports, callers,
tests, and diffs explicitly. Warn before any HIGH or CRITICAL blast radius.

## Data Contracts and Interfaces

### 1. Detector configuration

Introduce one immutable detector-specific config contract:

- `pivot_span_bars`: exact positive integer supplied by YAML; V2.1 requires 5.

No Python numeric default, call-time override, parameter grid, asset/timeframe
override, or hidden fallback is allowed.

The source label is exactly `pivot_rejection_v2_1`.

### 2. Causal pivot rule

For a candidate center bar `p` and span `s = 5`:

- require exactly `2s + 1` ordered, unique, same-state closed bars;
- confirmation bar is `p + s`;
- RESISTANCE requires `high[p]` strictly greater than every other high in
  the window;
- SUPPORT requires `low[p]` strictly less than every other low in the
  window;
- equality/ties do not qualify;
- `formed_at = pivot.closed_at`;
- `available_at = confirmation.closed_at`;
- `atr_at_creation = ATR[p+s]`;
- emit nothing before the confirmation bar closes;
- prefix replay and full replay must produce identical candidates for the same
  available timestamp.

A single outside pivot candle may qualify as both strict high and strict low.
Emit both sides when each has positive rejection-wick geometry. Order
deterministically as RESISTANCE then SUPPORT, then by causal identity.

Do not require pivot candle direction. The wick boundary already uses its
observed body.

### 3. Rejection-wick geometry

For RESISTANCE:

- `lower_bound = max(pivot.open, pivot.close)`;
- `upper_bound = pivot.high`.

For SUPPORT:

- `lower_bound = pivot.low`;
- `upper_bound = min(pivot.open, pivot.close)`.

Represent each rectangle through the existing `ZoneGeometry` contract:

- `center = (lower_bound + upper_bound) / 2`;
- `half_width = (upper_bound - lower_bound) / 2`.

Bounds and derived geometry must be finite and exact. A zero or negative wick
width is ineligible and emits no candidate for that side. Do not substitute an
ATR minimum width, candle range, epsilon, tick size, or fallback band.

ATR is normalization/provenance only; it does not set V2.1 geometry.

### 4. Candidate and causal identity

Every candidate must bind state key, side, source, formed/available timestamps,
confirmation-bar ATR, and exact geometry through the existing
`CandidateLevel` identity.

Do not assume one candidate per confirmation bar. Control and case identity
must bind the real candidate's causal identity, not confirmation timestamp
alone. Two sides from one outside bar require distinct real-case/control
topologies.

Future touch or outcome fields must never enter candidate, real-case, control,
or pairing identity. Mutating post-confirmation bars must not change those
identities.

### 5. Shared detector-neutral band services

V2.0 contains the first implementation of independent real/control band
evaluation. V2.1 is the second exact consumer, so extract only the genuinely
shared pure primitives into neutral modules under `research/metrics/`:

- inclusive OHLC/band intersection;
- first-revisit search after availability;
- fold-end censoring;
- fixed reaction-horizon outcome calculation;
- prior-close matched control geometry;
- detector-neutral paired excess/fold summary if it can be extracted without
  changing public artifact contracts.

Keep study-specific config, gates, dispositions, case/control identities,
serialization, and semantic reconstruction inside each canonical study.

Do not build a detector registry, plugin framework, generic experiment engine,
or inheritance hierarchy.

Adapt V2.0 to the shared primitive only where exact behavior is preserved.
Existing V2.0 public contracts and immutable bundle semantics must remain
valid. If safe extraction would alter V2.0 serialization or evidence identity,
leave that part in V2.0 and use a new neutral primitive for V2.1; document the
remaining duplication instead of widening the refactor.

Canonical studies must not import sibling studies. Follow the V2.0 precedent:
keep the V2.1 CLI in its canonical study package and do not add a historical
`scripts/<study>` facade.

### 6. Naive control contract

For every real candidate whose availability is inside a configured fold,
construct exactly two controls in the configured stable order: SUPPORT then
RESISTANCE.

Each control uses only confirmation-time information:

- `center = close[t-1]`, where `t` is the real candidate's confirmation
  index;
- `half_width = real_candidate.geometry.half_width`;
- `formed_at = bars[t-1].closed_at`;
- `available_at = real_candidate.available_at`;
- `atr_at_creation = real_candidate.atr_at_creation`;
- source `prior_close_naive_v2_1`;
- same state key and width as the real candidate.

Build both controls before learning any real outcome. Each control finds its
own touch and outcome. It must not inherit the real candidate's touch,
reference ATR, anchor close, horizon, or quality.

Every in-fold real candidate must have exact ordered two-control topology.
Reject missing, extra, duplicate, reordered, wrong-width, wrong-center,
wrong-side, and cross-candidate controls.

### 7. Outcome contract

Use the V2.0 causal outcome semantics unchanged:

- search starts at confirmation index plus 1;
- inclusive OHLC/band intersection;
- at most 50 search bars;
- search stops at fold end;
- first touch only;
- 10 bars after the touch form the reaction horizon;
- every horizon bar must close strictly before fold end;
- incomplete horizons are right-censored;
- statuses explicitly account for completed, no-touch, right-censored, and
  outside-fold candidates;
- reference ATR is point-in-time ATR at that band's own touch.

For SUPPORT:

- favorable excursion = `max(horizon.high) - touch.close`;
- adverse excursion = `touch.close - min(horizon.low)`.

For RESISTANCE:

- favorable excursion = `touch.close - min(horizon.low)`;
- adverse excursion = `max(horizon.high) - touch.close`.

Clamp raw favorable/adverse excursion at zero, normalize each by touch ATR, and
set `quality = favorable - adverse`.

### 8. Pairing and metrics

A primary pair exists only when:

- real and same-side control outcomes are both completed;
- the control binds the exact real candidate causal identity;
- fold, state key, confirmation bar/index, availability, creation ATR, side,
  and half-width match;
- real/control geometry identities differ.

For each pair:

`paired_excess_quality_atr = real_quality_atr - naive_quality_atr`

Opposite-side controls are diagnostics only.

Compute and serialize:

- candidate and in-fold candidate counts;
- status counts for real and controls;
- control counts by fold and side;
- unpaired reason counts;
- completed same-side pair count;
- per-fold counts and median paired excess;
- comparable-fold count;
- pooled median paired excess across comparable pairs;
- positive comparable-fold fraction;
- worst comparable-fold median.

### 9. Frozen gates and disposition

Use the V2.0 thresholds without change.

Readiness:

- completed same-side pairs >= 24;
- comparable folds >= 4;
- pairs per comparable fold >= 4;
- completed controls per side per comparable fold >= 4.

Utility, only after every readiness gate passes:

- pooled median paired excess >= 0.10 ATR;
- positive comparable-fold fraction >= 0.60;
- worst comparable-fold median >= -0.10 ATR.

Disposition is exactly one of:

- `PIVOT_REJECTION_BEATS_NAIVE_NULL`;
- `PIVOT_REJECTION_NOT_BETTER_THAN_NAIVE_NULL`;
- `INSUFFICIENT_EVIDENCE`.

Unknown gate names/categories/operators fail closed. Diagnostic utility cannot
override failed readiness. A passing result remains development research and
does not authorize holdout, runtime integration, trading, or deployment.

### 10. Strict configuration and provenance

The V2.1 YAML must bind the exact:

- experiment/study identity;
- asset, venue, timeframe, source paths and hashes;
- cutoff, row count and bar-grid identity;
- ATR protocol;
- pivot span and geometry identity;
- control rule and stable side order;
- outcome window;
- six folds;
- readiness and utility thresholds;
- output root and artifact schema version.

Reject missing, unknown, duplicate, mistyped, non-finite, and out-of-contract
values recursively. Do not read production `configs/sr.yaml` as a fallback.

Represent the outer cohort bundle and underlying source capsule as distinct
validated identities, as in corrected V2.0.

### 11. Artifact contract

Publish an immutable content-addressed bundle with:

- `manifest.json`;
- `study.json`;
- `cases.json`.

The manifest must bind source, config hash, implementation commit, schema,
member hashes/lengths, and study identity.

The casebook must contain enough pivot window, rejection geometry, real/control
topology, independent outcomes, pairing, accounting, and fold data for full
semantic recomputation from frozen source plus YAML.

Validation must fail closed on:

- bundle/member symlinks or non-regular files;
- unsafe or symlinked parents;
- missing/extra members;
- hash/length/config/source/commit mismatch;
- rehashed semantic tampering;
- candidate geometry/timing/source changes;
- future-dependent identity changes;
- control topology/center/width/touch changes;
- pair/metric/gate/disposition changes.

Generated evidence stays ignored. Do not mutate V1.12 or V2.0 evidence.

## Implementation Order

1. Create the V2.1 branch from `8342872`; confirm only known plan drafts are
   untracked.
2. Run codebase-memory impact analysis for active pivot detection, V2.0 band
   evaluation, research metrics, artifacts, facades, and imports.
3. Add controlled detector tests first, then implement the pure unregistered
   pivot-rejection detector.
4. Extract the smallest neutral band-evaluation/control primitive justified by
   the second consumer; prove V2.0 parity and protected-evidence validation.
5. Add the strict V2.1 config and canonical study contracts.
6. Implement independent real/control outcomes, exact topology, paired
   metrics, gates, runner, artifacts, semantic validator, and CLI facade.
7. Add causality, prefix parity, fold boundary, identity, topology, metric,
   determinism, tamper, path-safety, and import-boundary tests.
8. Run focused tests, V2.0 regression/semantic validation, protected V1.12
   validation, Ruff, compile/import, and diff checks.
9. Commit code/tests/config once their behavior is locked.
10. Generate V2.1 evidence twice from that exact implementation commit.
11. Require identical bundle ID and member bytes; validate semantically from
    the implementation commit.
12. Run the full SR suite and final boundary checks.
13. Write one coder-to-review handoff with commits, exact commands/counts,
    hashes, candidate/control/pair counts, fold diagnostics, disposition,
    superseded attempts if any, and worktree state.
14. Commit only that handoff. Do not merge or start V2.2.

If a contract/implementation defect is found before valid evidence, fix it and
rerun tests. Once a semantically valid evidence bundle is observed, do not
change detector rules, parameters, gates, folds, or data in response to the
result.

## Acceptance Criteria

### Detector

- Controlled high/low fixtures prove exact strict span-5 confirmation.
- Candidate is unavailable before the fifth right-hand bar closes.
- Full replay and every eligible prefix produce identical candidate identity.
- Tied highs/lows are rejected.
- Resistance and support bounds equal the exact wick formulas.
- Zero-width side is skipped without fallback geometry.
- Confirmation ATR, not pivot/future ATR, owns `atr_at_creation`.
- An outside bar may emit two deterministic, uniquely identified candidates.
- Malformed type, state, ordering, duplicate ID, time, OHLC, ATR, and finite
  value inputs fail through domain contracts.

### Controls and evaluation

- Every in-fold candidate has exactly two ordered controls even when two real
  candidates share one confirmation bar.
- Each control center is exactly prior close and width exactly matches its real
  band.
- A fixture proves real and control touches may occur on different bars.
- Changing future bars changes outcomes but not causal candidate/control IDs.
- Search-bar 50, fold-end, first-touch, and 10-bar horizon boundaries have
  explicit off-by-one tests.
- Same-side pairing is exact; opposite-side controls cannot enter primary
  utility.
- Readiness takes precedence over diagnostics.
- Unknown gate schema fails closed.

### Architecture and evidence

- Active code imports no `libs.sr`, providers, network, databases, viewer, or
  holdout service.
- Core runtime imports no research code; shared research imports no study.
- V2.0 bundle
  `60d8ac404b4e5a6aaf44eb9325bba7ddf6be154f663aa6a08e7a634bedbe695c`
  still validates semantically and remains byte-unchanged.
- Protected V1.12 bundle and audit remain semantically valid and byte-unchanged.
- Two V2.1 runs from the implementation commit are byte-identical.
- Rehashed semantic tampering and path/symlink attacks are rejected.
- Focused suites, full SR, Ruff, compile/import, CLI validation, and diff checks
  pass.
- The handoff reports the actual disposition without interpretation or rescue
  tuning.

## Validation Checklist

Run at minimum:

- detector-focused tests;
- V2.1 config/contracts/outcomes/metrics/runner/artifact tests;
- research/core import-boundary tests;
- existing V2.0 detector/study tests;
- V2.0 semantic artifact validation;
- protected V1.12 semantic/hash validation;
- full `tests/models/sr` suite;
- Ruff on changed Python;
- `compileall` and package/CLI imports;
- JavaScript tests only if an unexpected viewer file changes;
- `git diff --check`;
- two identical evidence runs;
- independent semantic/tamper/path-safety probes;
- final `git status --short --branch`.

Record exact commands, counts, hashes, elapsed results where material, and any
unavailable tool. Do not claim a check that was not run.

## Explicit Non-Goals

- No V1 pivot detector, lifecycle, association, state, replay, checkpoint, or
  runtime behavior change.
- No detector registry or production config.
- No merge, deployment, trading use, API, DB, service, or live loop.
- No provider call, data refresh, extra row, new asset/timeframe, or holdout.
- No ATR, span, width, gate, fold, horizon, or control tuning.
- No ZigZag, volume POC, fractal channel, FVG, order block, liquidity sweep,
  round number, VWAP, trendline, regime, ML, scoring, or ensemble.
- No legacy `src/libs/sr` import/copy/revival.
- No viewer/UI work or historical `scripts/<study>` compatibility facade.
- No V2.0 rescue and no V2.2 work.

## Required Coder Handoff

Return one review-ready package:

- branch and exact base;
- implementation and docs commits;
- changed-file inventory and blast radius;
- config/source/implementation identities;
- bundle, study, member hashes and byte lengths;
- candidate, control, status, pair, fold, gate, and disposition summary;
- deterministic rerun proof;
- focused/full/static/boundary/semantic validation results;
- protected V1.12 and V2.0 evidence status;
- untracked/ignored worktree state;
- explicit confirmation of no provider, holdout, runtime, production, merge,
  or V2.2 changes.

A negative or insufficient result is a completed V2.1 research outcome, not an
implementation failure.
