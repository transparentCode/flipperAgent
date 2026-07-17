---
goal: Implement SR-V1.8 as a frozen-source, development-only sensitivity study of the existing detection-geometry parameter family, selecting at most one global challenger without holdout access or production changes.
stage: orchestrator-to-coder
date_created: 2026-07-16
last_updated: 2026-07-16
owner: Quant Orchestrator
status: Approved
tags: [handoff, quant, sr, geometry-sensitivity, parameter-study, multi-asset, evidence, leakage-control]
source_agent: Quant Orchestrator
target_agent: Coder Agent
base_commit: 625878b26faa1cccb330af0e1c7062e3e3f4b1b6
source_branch: feature/sr-v1.7-cohort-readiness
target_branch: feature/sr-v1.8-geometry-sensitivity
---

# Orchestrator To Coder: SR-V1.8 Detection-Geometry Sensitivity v1

## Objective

SR-V1.7 is approved after remediation. Its validated development evaluation is
READY_FOR_PARAMETER_SENSITIVITY across TAOUSDT, BTCUSDT, ETHUSDT, and SOLUSDT
on Binance USD-M 1d data. V1.7 establishes sample and structural readiness
only; it does not establish profitability or authorize broad optimization.

Implement one bounded, development-only study answering:

> Is the current global detection geometry, pivot_span_bars=5 and
> zone_half_width_atr=0.25, located in a stable response region across the
> approved four-asset cohort, or does one nearby global geometry challenger
> improve first-touch reaction quality robustly enough to freeze for a later,
> separately approved fresh forward holdout?

V1.8 changes only the two existing detection parameters inside an immutable
research candidate grid. It must not add features, tune the other six SR
parameters, create asset/timeframe overrides, open holdout data, or mutate
production configuration.

The study may return exactly one disposition:

- SELECT_GLOBAL_CHALLENGER;
- RETAIN_BASELINE_GEOMETRY;
- INSUFFICIENT_EVIDENCE.

SELECT_GLOBAL_CHALLENGER freezes one exact global pair for a later holdout plan.
It does not promote the pair into configs/sr.yaml and does not authorize runtime
integration.

## Scope Boundaries

### Phase 0: mandatory V1.7 documentation correction

The exact starting point is commit
625878b26faa1cccb330af0e1c7062e3e3f4b1b6 on
feature/sr-v1.7-cohort-readiness.

Before creating the V1.8 branch or changing V1.8 code:

1. Change only plans/coder-to-review-sr-v1.7-cohort-readiness-v1.md lines
   313-316.
2. Replace the stale statement that the three failed fold diagnostics prevent
   parameter sensitivity with a statement that:
   - the three fold failures are diagnostic only;
   - every aggregate readiness gate passes;
   - READY_FOR_PARAMETER_SENSITIVITY authorizes V1.8 planning;
   - any future holdout still requires a separate approved protocol.
3. Commit this documentation-only correction on
   feature/sr-v1.7-cohort-readiness.
4. Record the correction commit in the V1.8 coder handoff.
5. Create feature/sr-v1.8-geometry-sensitivity from that correction commit.

Do not change code, evidence, bundle IDs, metrics, or the V1.7 disposition in
this preflight commit. If the exact starting commit or handoff contents do not
match, stop and return Blocked.

Do not merge either branch.

### Protected working tree

Preserve all pre-existing modified .codebase-memory entries and unrelated
untracked plan drafts. Do not stage, delete, restore, rewrite, or include them.

Generated research artifacts must remain untracked.

### Frozen evidence inputs

V1.8 must use these exact validated inputs:

- V1.7 source bundle ID:
  6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9
- Source path:
  research/tmp_sr_v1_7/source/6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9
- Source preparation commit:
  be6459a8e06ec95b634b2cfb2b91a08cd31d9ba2
- V1.7 evaluation bundle ID:
  824e9265a63073ba792762a891adf52deec9677d791c40641dc0107c1f2b840d
- Evaluation path:
  research/tmp_sr_v1_7/evaluation/824e9265a63073ba792762a891adf52deec9677d791c40641dc0107c1f2b840d
- V1.7 evaluation ID:
  49a895360774ec0c46349eae2d1ec6f56e7262e5f1411ab992f9886d9040fa8d
- V1.7 evaluation implementation commit:
  4cb069af6142dbd7dadf7a5ebef49d2da0ba26a7
- V1.7 protocol config hash:
  370d2b66e8e3031b0df8547e8b52c61288e14c5d1b858612ce9fae712e1690a7
- Frozen production SR config hash:
  cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299
- Frozen input config hash:
  5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d

Load and semantically validate both V1.7 bundles before evaluating a candidate.
Provider construction, adapter imports, network calls, pagination, source
preparation, bar repair, and new market-data persistence are forbidden.

The canonical asset order is:

1. TAOUSDT
2. BTCUSDT
3. ETHUSDT
4. SOLUSDT

All four sources contain exactly 629 daily bars on the same exact UTC grid from
2024-04-11T00:00:00Z through causal close 2025-12-31T00:00:00Z.

### Frozen model behavior

The following remain fixed for every candidate:

- venue: binance_usdm;
- timeframe: 1d;
- ATR method: wilder_rma;
- ATR period: 14;
- ATR seed: sma;
- common causal start: period 28;
- merge_distance_atr: 0.50;
- touch_tolerance_atr: 0.25;
- break_buffer_atr: 0.25;
- break_confirm_closes: 2;
- max_age_bars: 50;
- max_active_zones: 8;
- first-touch outcome start offset: 1 bar;
- first-touch horizon: 10 bars;
- support/resistance semantics;
- association, lifecycle, replay, checkpoint, evaluation, and censoring behavior;
- half-open fold boundaries;
- all source, config, and artifact identity rules.

Do not modify configs/sr.yaml or configs/sr_inputs.yaml.

### Approved candidate grid

The exact canonical axes are:

- pivot_span_bars: [3, 5, 7]
- zone_half_width_atr: [0.15, 0.25, 0.35]

Evaluate the nine Cartesian-product candidates in this canonical order:

1. (3, 0.15)
2. (3, 0.25)
3. (3, 0.35)
4. (5, 0.15)
5. (5, 0.25) — baseline
6. (5, 0.35)
7. (7, 0.15)
8. (7, 0.25)
9. (7, 0.35)

No candidate may be added, removed, reordered, widened, narrowed, or rerun under
changed gates after any candidate result is observed.

Define candidate_id as a deterministic hash of the exact schema version,
parameter-family name, pivot_span_bars, and zone_half_width_atr. The baseline
flag is true only for (5, 0.25).

The period-28 common start dominates the largest 15-bar pivot window, so all
candidates use the same eligible model-bar window. Do not create
candidate-specific date windows.

### Candidate configuration construction

Keep the implementation additive. Do not modify the production resolver or
ResolvedSRConfig contract merely to represent research candidates.

Create an immutable study-owned candidate specification that binds:

- candidate_id;
- baseline flag;
- the two approved detection values;
- the inherited V1.7 resolved config hash for each asset;
- the complete effective resolved config hash for each asset;
- an explicit trial-override record for the two detection fields;
- confirmation that the other six parameter values and ATR inputs equal the
  frozen baseline.

Build effective candidate ResolvedSRConfig values through existing typed
constructors. The candidate specification is the authoritative experiment
provenance for the two changed fields. Do not falsify or invent an
asset/timeframe production override.

### Frozen folds

Use the same six half-open folds:

- 2024_q3: [2024-07-01T00:00:00Z, 2024-10-01T00:00:00Z)
- 2024_q4: [2024-10-01T00:00:00Z, 2025-01-01T00:00:00Z)
- 2025_q1: [2025-01-01T00:00:00Z, 2025-04-01T00:00:00Z)
- 2025_q2: [2025-04-01T00:00:00Z, 2025-07-01T00:00:00Z)
- 2025_q3: [2025-07-01T00:00:00Z, 2025-10-01T00:00:00Z)
- 2025_q4: [2025-10-01T00:00:00Z, 2026-01-01T00:00:00Z)

State must continue across fold boundaries. Folds partition observations and
outcomes; they do not reset the SR engine.

## Research Hypothesis and Metric Semantics

pivot_span_bars controls structural selectivity and confirmation delay:

- 3 should create earlier and more frequent local-pivot zones;
- 7 should create later and more selective zones;
- 5 is the current placeholder baseline.

zone_half_width_atr controls only rectangular zone geometry:

- 0.15 is a narrower local band;
- 0.35 is a wider local band;
- 0.25 is the current baseline.

The primary outcome remains completed first-touch reaction quality in ATR(14)
units:

quality = favorable_excursion_reference_atr - adverse_excursion_reference_atr

Use the existing causal V1.7 outcome builder and aggregation. Do not redefine
touches, invalidation, favorable/adverse excursion, censoring, or terminal
events.

For every candidate report:

- each asset and fold;
- each asset pooled;
- cohort micro;
- cohort macro;
- support/resistance counts;
- completed and right-censored outcomes;
- invalidation rate;
- zone creation density per 100 eligible bars;
- churn rate;
- median favorable, adverse, and quality ATR;
- complete event accounting.

Do not add PnL or trading metrics.

### Baseline parity

Before interpreting challengers:

1. Validate the exact V1.7 evaluation bundle.
2. Recompute a control baseline using the V1.7 implementation identity and
   require exact V1.7 payload equality.
3. Recompute the study baseline using the V1.8 implementation commit.
4. Require exact equality of all economic and behavioral semantics between the
   V1.7 control and V1.8 baseline:
   - bars and timestamps;
   - candidate/zone geometry;
   - ordered state transitions and event types;
   - statuses and lifecycle counts;
   - fold and pooled metrics;
   - micro and macro aggregates;
   - readiness gates and disposition.

Only commit-derived provenance and the deterministic IDs that directly include
that provenance may differ. Enumerate every excluded identity field explicitly
in code and tests. Any unexplained semantic difference is Blocked, not a
candidate result.

## Eligibility, Quality Gates, and Guardrails

All comparisons use unrounded values. Rounding is presentation-only.

### Candidate sample eligibility

For a candidate to be fully evaluable, every asset must have:

- at least 4 completed first touches in an eligible fold;
- at least 4 eligible folds;
- at least 24 completed first touches across development;
- non-zero created support zones;
- non-zero created resistance zones;
- non-zero first touches;
- non-zero terminal cohort events.

A comparable asset-fold unit requires both baseline and candidate to have at
least 4 completed outcomes and defined median quality in the same fold.

A fully evaluable challenger must have at least 4 comparable folds for every
asset and at least 16 comparable asset-fold units across the cohort.

Fold failures remain recorded diagnostics. Candidate-level eligibility is
determined by the aggregate asset rules above.

### Quality deltas

For each asset:

asset_pooled_delta =
candidate asset pooled median quality ATR
minus baseline asset pooled median quality ATR

Define:

- median_asset_delta: median of the four asset_pooled_delta values;
- micro_delta: candidate cohort micro median quality ATR minus baseline cohort
  micro median quality ATR;
- positive_asset_count: number of assets with asset_pooled_delta strictly > 0;
- worst_asset_delta: minimum of the four asset_pooled_delta values;
- asset_fold_win_fraction: strict positive quality deltas divided by the number
  of comparable asset-fold units. Zero deltas are not wins.

A selectable challenger must pass all of:

- median_asset_delta >= 0.10 ATR;
- micro_delta >= 0.10 ATR;
- positive_asset_count >= 3 of 4;
- worst_asset_delta >= -0.10 ATR;
- asset_fold_win_fraction >= 0.60.

### Cohort guardrails

Evaluate these on cohort micro aggregates against the baseline:

- invalidation_rate_delta <= 0.05;
- zone_creation_density_ratio in [0.50, 2.00];
- churn_rate_delta <= 0.10;
- right_censoring_rate_delta <= 0.10.

All per-asset guardrail values must also be reported as diagnostics, but they
are not hidden selection gates.

A missing denominator or undefined required metric fails the relevant gate.

### Local stability gate

A selectable challenger must have at least one orthogonally adjacent
non-baseline challenger in the approved 3x3 grid.

Orthogonal adjacency means exactly one grid step on one axis:

- pivot_span_bars changes by 2 while width is equal; or
- zone_half_width_atr changes by 0.10 while span is equal.

Diagonal candidates are not adjacent. The baseline cannot satisfy neighbor
support because its quality delta is zero.

The supporting neighbor must:

- be fully evaluable;
- have median_asset_delta > 0;
- have micro_delta > 0;
- pass all cohort guardrails.

It need not pass the 0.10 quality thresholds or the 0.60 fold-win gate. This
gate prevents selection of an isolated response spike.

### Deterministic selection

Among challengers passing every eligibility, quality, guardrail, and stability
gate, select exactly one by:

1. greater median_asset_delta;
2. greater micro_delta;
3. greater asset_fold_win_fraction;
4. smaller Manhattan grid-step distance from baseline;
5. smaller pivot_span_bars;
6. smaller zone_half_width_atr;
7. candidate_id lexical order.

Define Manhattan distance as:

abs(pivot_span_bars - 5) / 2
plus
abs(zone_half_width_atr - 0.25) / 0.10

Do not introduce weighted composite scores.

### Disposition rules

Apply in this order:

1. INSUFFICIENT_EVIDENCE when the validated V1.7 baseline is valid but no
   non-baseline challenger is fully evaluable.
2. SELECT_GLOBAL_CHALLENGER when at least one challenger passes every gate;
   bind the deterministic winner.
3. RETAIN_BASELINE_GEOMETRY when at least one non-baseline challenger is fully
   evaluable but none passes every gate.

Baseline parity failure, artifact invalidity, source mismatch, config mismatch,
or causal/deterministic failure raises a contract error and produces a Blocked
handoff. It must not be converted into a research disposition.

Negative or mixed results are legitimate. Do not relax gates or change the grid
to manufacture a challenger.

## Affected Symbols, Modules, and Execution Flows

### Additive production-tree files

Add:

- configs/sr_trials/sr_v1_8_1d_geometry_sensitivity.yaml
- src/libs/models/sr/scripts/geometry_sensitivity/__init__.py
- src/libs/models/sr/scripts/geometry_sensitivity/config.py
- src/libs/models/sr/scripts/geometry_sensitivity/contracts.py
- src/libs/models/sr/scripts/geometry_sensitivity/candidate_grid.py
- src/libs/models/sr/scripts/geometry_sensitivity/selection.py
- src/libs/models/sr/scripts/geometry_sensitivity/artifacts.py
- src/libs/models/sr/scripts/geometry_sensitivity/runner.py
- src/libs/models/sr/scripts/geometry_sensitivity/cli.py

Add mirrored tests under:

- tests/models/sr/scripts/geometry_sensitivity/

The final coder handoff must be:

- plans/coder-to-review-sr-v1.8-geometry-sensitivity-v1.md

### Reuse without modification

Reuse:

- V1.7 strict config and source-bundle validation;
- V1.7 replay_asset and aggregation behavior;
- V1.7 first-touch metrics and event accounting;
- ResolvedSRConfig.create and the existing typed config groups;
- deterministic identity helpers;
- existing checkpoint/replay/evaluation contracts.

Do not copy V1.7 metrics or source logic into the V1.8 package.

### Dependency direction

Allowed:

geometry_sensitivity
  -> cohort_readiness
  -> baseline_trial / atr_calibration
  -> SR core

Forbidden:

- SR core importing geometry_sensitivity;
- production applications importing geometry_sensitivity;
- geometry_sensitivity importing Binance or any provider adapter;
- geometry_sensitivity importing viewer/frontend code;
- V1.7 importing V1.8.

Add or extend import-boundary tests to enforce these rules through the approved
allowlist style.

### Runtime flow

The only approved execution flow is:

1. load exact V1.8 YAML;
2. load and validate exact V1.7 config, source bundle, and evaluation bundle;
3. resolve and verify frozen production SR and ATR configs;
4. establish exact baseline parity;
5. build the canonical nine-candidate matrix;
6. create fresh independent replay state for each candidate and asset;
7. evaluate the same six folds and outcomes;
8. aggregate per-asset, micro, and macro results;
9. apply frozen eligibility, quality, guardrail, and stability gates;
10. select at most one global challenger;
11. publish a deterministic development-only evidence bundle;
12. validate it through full semantic recomputation.

No step may construct a provider or contact a network.

## Data Contracts and Artifacts

Use frozen exact-type contracts with fail-closed validation. At minimum define:

### GeometryCandidate

Bind:

- schema version;
- candidate_id;
- baseline flag;
- pivot_span_bars;
- zone_half_width_atr;
- canonical grid position;
- Manhattan distance from baseline.

### CandidateAssetResult

Bind:

- asset;
- source ID;
- baseline and effective resolved config hashes;
- trial override provenance;
- replay/trace identities;
- fold metrics;
- pooled metrics;
- event accounting;
- structural and sample diagnostics.

### CandidateEvaluation

Bind:

- candidate;
- canonical four-asset results;
- micro and macro aggregates;
- per-asset deltas;
- comparable asset-fold deltas;
- all eligibility and guardrail diagnostics.

### CandidateDecision

Bind:

- fully_evaluable;
- every named gate with value, threshold, pass/fail, and reason;
- median_asset_delta;
- micro_delta;
- positive_asset_count;
- worst_asset_delta;
- comparable fold count and win fraction;
- neighbor-support candidate IDs;
- selection rank fields.

### GeometrySensitivityStudy

Bind:

- implementation commit;
- V1.8 config hash;
- V1.7 config/source/evaluation identities;
- frozen production config hashes;
- exact candidate order;
- baseline reference;
- all candidate evaluations and decisions;
- selected candidate or null;
- exact disposition;
- deterministic study ID.

Reject duplicate, missing, reordered, unknown, nonfinite, malformed, or
identity-inconsistent fields.

### Evidence bundle

Publish under:

research/tmp_sr_v1_8/evaluation/<bundle_id>/

Use canonical JSON with recursive duplicate-key rejection, member SHA-256
hashes, a semantic manifest, and a top-level content-addressed bundle ID.

The bundle must include enough information for the validator to reconstruct all
nine candidate replays and the final decision from the frozen V1.7 source.
Stored hashes alone are insufficient.

Generated evidence is untracked and must not be committed.

### Implementation provenance

The final evidence must bind the V1.8 implementation commit, not the later
handoff documentation commit.

Required execution order:

1. finish code and tests;
2. commit the implementation;
3. run the final evaluation twice from that exact implementation commit;
4. verify identical bundle IDs and byte-identical members;
5. validate the final bundle;
6. write and commit the coder-to-review handoff without rerunning evidence.

If code changes after evidence generation, the old V1.8 evidence is invalid.
Rerun from the unchanged frozen source under the new implementation commit.
No provider request is needed or allowed.

## Implementation Order

1. Perform and commit the V1.7 documentation-only correction.
2. Create feature/sr-v1.8-geometry-sensitivity from that correction commit.
3. Record repository search/blast-radius results before editing.
4. Add the exact fail-closed V1.8 YAML and loader.
5. Add immutable candidate and study contracts with deterministic identities.
6. Add candidate-grid construction and effective config building.
7. Add baseline parity validation.
8. Add candidate replay and aggregation by reusing V1.7 logic.
9. Add explicit eligibility, quality, guardrail, neighbor, selection, and
   disposition logic.
10. Add deterministic artifact publication and semantic validation.
11. Add CLI entry points for evaluate and validate only. There is no
    prepare-source command.
12. Add narrow tests, then full SR and boundary tests.
13. Commit implementation.
14. Run final network-denied evaluation twice and validate byte equality.
15. Write and commit the coder-to-review handoff.
16. Stop. Do not merge or start a holdout/viewer/runtime task.

## Acceptance Criteria

V1.8 is implementation-complete only when:

1. The V1.7 stale authorization sentence is corrected in a separate docs-only
   commit.
2. The branch lineage begins at that correction commit.
3. Production configs and SR core behavior are unchanged.
4. The exact source and V1.7 evaluation bundles validate before candidate work.
5. Zero provider constructors and zero network paths are reachable.
6. The grid is exactly the approved nine candidates in canonical order.
7. Only the two detection parameters vary.
8. Every candidate/asset replay starts from independent empty state.
9. Fold boundaries do not reset state.
10. Baseline economic and behavioral semantics reproduce V1.7 exactly.
11. Candidate metrics reconcile from outcome rows and event records.
12. Eligibility uses aggregate asset gates; fold failures remain diagnostics.
13. All quality, guardrail, stability, and tie-break rules are exact and
    pre-result.
14. At most one global challenger is selected.
15. No asset-specific result can create a production override.
16. Disposition is one of the three approved values.
17. Repeated evaluation is byte-identical.
18. Artifact validation reconstructs replays, metrics, gates, and decision.
19. Tampering and recursive duplicate keys fail closed.
20. No holdout, production mutation, viewer change, or runtime integration
    occurs.
21. The final handoff is sufficient for independent Quant Review without
    guessing.

## Validation Checklist

### Required automated coverage

Cover at least:

- exact YAML root/section/key schema;
- recursive duplicate-key rejection;
- frozen source/evaluation/config identity rejection;
- exact candidate axes, Cartesian product, order, uniqueness, and baseline;
- grid addition/removal/reordering/duplicate rejection;
- only two detection fields may differ;
- effective config hashes and trial-override provenance;
- candidate/asset state isolation;
- candidate execution-order permutation invariance;
- asset execution-order permutation invariance;
- no fold-boundary state reset;
- V1.7 control replay exact parity;
- V1.8 baseline semantic parity with explicit identity exclusions;
- sample eligibility at exactly 4 folds and 24 outcomes;
- 3 eligible folds rejected;
- fewer than 24 outcomes rejected;
- fold failures retained as diagnostics;
- all five quality gates at exact threshold and just below threshold;
- each cohort guardrail at both boundaries and just outside;
- undefined denominator rejection;
- orthogonal neighbor acceptance;
- diagonal-only neighbor rejection;
- baseline-as-neighbor rejection;
- isolated-spike rejection;
- deterministic tie-breaking at every rank field;
- all three dispositions;
- full event and outcome accounting reconciliation;
- candidate matrix canonical serialization;
- duplicate JSON/member/hash/protocol/study/decision tampering rejection;
- fully rehashed result or disposition tampering rejected by recomputation;
- provider constructor replaced with a failing spy throughout evaluation;
- byte-identical repeated evaluation.

### Required commands

Run and report:

PYTHONPATH=src .venv/bin/python -m pytest -q tests/models/sr/scripts/geometry_sensitivity

PYTHONPATH=src .venv/bin/python -m pytest -q tests/models/sr

PYTHONPATH=src .venv/bin/python -m pytest -q tests/models/sr/test_import_boundaries.py tests/models/sr/adapters/test_import_boundaries.py

ruff check src/libs/models/sr/scripts/geometry_sensitivity tests/models/sr/scripts/geometry_sensitivity

PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/sr/scripts/geometry_sensitivity tests/models/sr/scripts/geometry_sensitivity

git diff --check 625878b26faa1cccb330af0e1c7062e3e3f4b1b6..HEAD

The coder handoff must additionally report the actual Phase-0 correction commit
used as the V1.8 branch point.

### Independent probes

Run and record at least:

1. exact V1.7 bundle validation before candidate evaluation;
2. baseline control and V1.8 semantic parity;
3. provider construction denied for both final runs;
4. all nine candidates evaluated in canonical order;
5. candidate-order permutation produces identical per-candidate results;
6. asset-order permutation produces identical asset results;
7. candidate and asset state-isolation checks;
8. direct micro aggregation from persisted outcome rows;
9. direct recomputation of every selection gate and tie-break;
10. a fully rehashed source/result/decision mutation rejected semantically;
11. two final runs produce the same bundle ID and byte-identical members.

## Explicit Non-Goals

Do not implement:

- any holdout window, holdout source, sealed capsule, holdout registry, or
  holdout decision;
- any Binance/provider call or new market-data request;
- changes to configs/sr.yaml or configs/sr_inputs.yaml;
- asset, timeframe, or asset/timeframe SR overrides;
- tuning of association, lifecycle, runtime, or ATR parameters;
- a larger/adaptive/random/Bayesian grid;
- new parameters, scores, confidence, strength, probability, features, or
  composite context;
- volume, order book, funding, open interest, regime, trendline, regression,
  clustering, ML, or multi-timeframe behavior;
- 4h, 1h, or any non-1d timeframe;
- PnL, trades, win rate, expected return, Sharpe, drawdown, fees, slippage,
  sizing, or trading-readiness claims;
- production runtime, API, scheduler, worker, database, cache, Turso, cloud, or
  deployment integration;
- viewer/frontend changes, visual candidate approval, event-label UX polish, or
  browser smoke;
- changes to checkpoint schema, lifecycle state machine, terminal pruning, or
  event persistence;
- changes to SR root exports;
- merge, V1.9, or any later family study.

Do not use visual judgment to change the candidate grid or selection result.
Visual comparison is a separately reviewed follow-up after automatic V1.8
decision.

## Blocking Issues and Follow-Ups

### Blocking conditions

Return Blocked without producing research evidence if:

- Phase 0 cannot be completed exactly;
- either frozen V1.7 bundle is absent or fails semantic validation;
- production config hashes differ;
- baseline parity fails;
- any provider/network path is reached;
- candidate grid or gates differ from this handoff;
- deterministic semantic recomputation cannot be demonstrated;
- protected core/config paths must change;
- final artifact identity cannot bind the exact implementation commit.

Do not work around a blocker by changing inputs, dropping an asset, reducing
coverage gates, or expanding the grid.

### Non-blocking future work

Excluded from V1.8:

- If SELECT_GLOBAL_CHALLENGER: a deterministic baseline-versus-challenger
  development visualization may be planned next. Visual review may reject an
  implementation anomaly but cannot promote or retune the challenger.
- A fresh forward holdout may be designed only after the challenger and all
  gates are frozen and separately approved.
- If RETAIN_BASELINE_GEOMETRY: keep the baseline; do not immediately search
  another parameter family merely to obtain a winner.
- Shorter timeframes require a separate pagination and window protocol.
- Feature additions require an explicit hypothesis, ablation, and overfitting
  review before implementation.

## Mandatory Coder-To-Reviewer Handoff

Return:

plans/coder-to-review-sr-v1.8-geometry-sensitivity-v1.md

Include:

- exact Phase-0 docs correction commit;
- exact base, branch, implementation commit, and handoff commit;
- file inventory and repository search/blast-radius result;
- protected-path diff proof;
- exact V1.8 config and config hash;
- exact V1.7 source/evaluation/config identities;
- confirmation of zero provider construction and calls;
- exact candidate IDs and effective config hashes for all assets;
- baseline parity table and explicit allowed identity differences;
- complete 9-candidate per-asset/fold/micro/macro matrix;
- every candidate eligibility and structural diagnostic;
- all quality deltas, guardrails, neighbor support, and tie-break fields;
- selected candidate or null;
- exact disposition and its reason;
- study/evidence bundle IDs, member hashes, and paths;
- two-run byte-identical determinism evidence;
- semantic/tamper/causality/state-isolation probes;
- targeted, full SR, boundary, Ruff, compile, and diff-check results;
- confirmation that production configs, core SR, viewer, provider, holdout,
  runtime, and unrelated worktree entries were not changed;
- blockers and non-blocking follow-ups;
- explicit no-merge and no-V1.9 statement.

The package is complete enough for the Coder Agent to execute without guessing.
