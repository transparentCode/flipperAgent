---
goal: Implement SR-V1.9 as a deterministic, development-only TAOUSDT baseline-adequacy study that compares approved causal first-touch outcomes with a pre-registered non-zone null benchmark.
stage: orchestrator-to-coder
date_created: 2026-07-16
last_updated: 2026-07-16
owner: Quant Orchestrator
status: Approved
tags: [handoff, quant, sr, v1.9, baseline-adequacy, null-benchmark, taousdt, evidence, leakage-control]
source_agent: Quant Orchestrator
target_agent: Coder Agent
base_commit: 0fc43a19ab696811e8c7e214c56f5351e50c4e1f
source_branch: feature/sr-v1.8-geometry-sensitivity
target_branch: feature/sr-v1.9-baseline-adequacy
---

# Orchestrator To Coder: SR-V1.9 Baseline Adequacy / Null Benchmark v1

## Objective

SR-V1.8 is approved with disposition RETAIN_BASELINE_GEOMETRY. It establishes
that none of the eight nearby geometry challengers passed the frozen selection
protocol against the existing global geometry:

- pivot_span_bars: 5;
- zone_half_width_atr: 0.25;
- ATR: Wilder RMA 14 with SMA seed.

V1.8 does **not** establish that the retained zones identify better reaction
locations than ordinary, causally available non-zone locations. It only says no
tested nearby geometry was robustly superior to the baseline.

Implement one bounded, development-only adequacy study answering:

> On TAOUSDT Binance USD-M 1d, do completed first touches of the retained
> baseline zones produce materially better 10-bar ATR-normalized reaction
> quality than deterministic non-zone control anchors evaluated under the same
> causal timing and outcome semantics?

This is a null-benchmark study, not another parameter search. It must add no
feature, score, rank, confidence model, optimizer, random sampler, asset/timeframe
override, production behavior, holdout access, or runtime dependency.

The study may return exactly one disposition:

- BASELINE_BEATS_NAIVE_NULL;
- BASELINE_NOT_BETTER_THAN_NAIVE_NULL;
- INSUFFICIENT_EVIDENCE.

BASELINE_BEATS_NAIVE_NULL is evidence that the retained TAOUSDT/1d baseline has
location value against this exact naive null on the existing development
window. It is not profitability evidence, production promotion, or
authorization to open a holdout.

## Scope Boundaries

### Exact start and branch workflow

Start from exact approved V1.8 HEAD:

- branch: feature/sr-v1.8-geometry-sensitivity;
- commit: 0fc43a19ab696811e8c7e214c56f5351e50c4e1f;
- implementation commit:
  fa819418aa35b7f325c7a6bf2a51a387aa97f60f.

Before implementation:

1. Confirm current branch and HEAD exactly match the values above.
2. Confirm the V1.8 handoff has status Ready and the validated final evidence
   below.
3. Create feature/sr-v1.9-baseline-adequacy from exact commit 0fc43a19.
4. Commit this approved handoff as the first V1.9 branch commit.
5. Implement only after that handoff commit exists.
6. Do not modify or recommit V1.8 evidence or handoff documents.
7. Do not merge any branch.

If the branch, HEAD, handoff, evidence identities, or frozen inputs do not
match, stop and return Blocked.

### Protected working tree

The source worktree already contains unrelated user-owned changes and historical
untracked plan drafts, including:

- modified .codebase-memory/artifact.json;
- deleted .codebase-memory/graph.db.zst;
- pre-existing untracked plans.

Preserve them exactly. Do not stage, delete, restore, rewrite, move, or include
them in any V1.9 commit. Generated V1.9 research evidence must remain untracked.

### Frozen evidence inputs

V1.9 must consume these exact validated inputs:

#### V1.7 source and baseline evaluation

- source bundle ID:
  6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9;
- source path:
  research/tmp_sr_v1_7/source/6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9;
- source preparation commit:
  be6459a8e06ec95b634b2cfb2b91a08cd31d9ba2;
- V1.7 evaluation bundle ID:
  824e9265a63073ba792762a891adf52deec9677d791c40641dc0107c1f2b840d;
- V1.7 evaluation path:
  research/tmp_sr_v1_7/evaluation/824e9265a63073ba792762a891adf52deec9677d791c40641dc0107c1f2b840d;
- V1.7 evaluation ID:
  49a895360774ec0c46349eae2d1ec6f56e7262e5f1411ab992f9886d9040fa8d;
- V1.7 evaluation implementation commit:
  4cb069af6142dbd7dadf7a5ebef49d2da0ba26a7;
- V1.7 protocol config hash:
  370d2b66e8e3031b0df8547e8b52c61288e14c5d1b858612ce9fae712e1690a7.

#### V1.8 geometry study

- V1.8 evaluation bundle ID:
  b0ea33decc9c8c40dab98bdbb90635652dc199031fc50b27d3a71a6711378941;
- V1.8 study ID:
  2a324d3a203642bf9030aede611a8d874fcb051c5b394fcb4758582d6cfbc954;
- V1.8 evaluation path:
  research/tmp_sr_v1_8/evaluation/b0ea33decc9c8c40dab98bdbb90635652dc199031fc50b27d3a71a6711378941;
- V1.8 implementation commit:
  fa819418aa35b7f325c7a6bf2a51a387aa97f60f;
- V1.8 config hash:
  86137d2c5b5e12802a5731298ab548822f23c4937d635bae5f21b77a8e7c0da7;
- V1.8 disposition: RETAIN_BASELINE_GEOMETRY;
- selected challenger: none;
- baseline candidate ID:
  37769b33cc663e4baf5488001252a996b9cb2ec67d0182400f12cb928015709c.

#### Frozen configuration identities

- production SR config hash:
  cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299;
- frozen input config hash:
  5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d.

Validate all referenced bundles and semantic identities before computing
controls. Provider construction, Binance adapter imports, network access,
pagination, data preparation, bar repair, source mutation, and new source
persistence are forbidden.

### Asset and model scope

Use only:

- venue: binance_usdm;
- asset: TAOUSDT;
- timeframe: 1d;
- source: the TAOUSDT member of the frozen V1.7 source bundle;
- source length: 629 bars;
- UTC grid: 2024-04-11T00:00:00Z through 2025-12-31T00:00:00Z.

The exact baseline model remains frozen:

- pivot_span_bars: 5;
- zone_half_width_atr: 0.25;
- merge_distance_atr: 0.50;
- touch_tolerance_atr: 0.25;
- break_buffer_atr: 0.25;
- break_confirm_closes: 2;
- max_age_bars: 50;
- max_active_zones: 8;
- ATR method: wilder_rma;
- ATR period: 14;
- ATR seed: sma;
- common causal start: period 28;
- outcome start offset: 1 bar;
- outcome horizon: 10 bars.

Do not modify configs/sr.yaml or configs/sr_inputs.yaml.

### Frozen development folds

Use the same six half-open folds:

- 2024_q3: [2024-07-01T00:00:00Z, 2024-10-01T00:00:00Z);
- 2024_q4: [2024-10-01T00:00:00Z, 2025-01-01T00:00:00Z);
- 2025_q1: [2025-01-01T00:00:00Z, 2025-04-01T00:00:00Z);
- 2025_q2: [2025-04-01T00:00:00Z, 2025-07-01T00:00:00Z);
- 2025_q3: [2025-07-01T00:00:00Z, 2025-10-01T00:00:00Z);
- 2025_q4: [2025-10-01T00:00:00Z, 2026-01-01T00:00:00Z).

State continues across folds. Folds partition anchors and outcome windows; they
must not reset the SR engine.

## Research Contract

### Hypothesis

The retained baseline has location value if its completed first-touch outcomes
are consistently better than deterministic non-zone anchors drawn from the
same asset, fold, bar grid, ATR regime, and outcome horizon.

The null is intentionally simple:

- it asks whether zones beat ordinary non-zone locations;
- it does not attempt regime matching, volatility bucketing, propensity
  matching, bootstrapping, permutation testing, or trade simulation;
- it introduces no seed, sampling count, search axis, or researcher-selected
  control subset.

A failure against this null is a stop signal. It is not permission to add
features or expand tuning.

### Real first-touch outcomes

Use the exact approved V1.7/V1.8 baseline first-touch outcomes. The economic
outcome is anchored at the first-touch bar close, uses ATR(14) at that touch,
starts on the next bar, and spans exactly 10 bars.

For support:

    favorable = max(max(horizon.high) - anchor_close, 0) / reference_atr_14
    adverse   = max(anchor_close - min(horizon.low), 0) / reference_atr_14

For resistance:

    favorable = max(anchor_close - min(horizon.low), 0) / reference_atr_14
    adverse   = max(max(horizon.high) - anchor_close, 0) / reference_atr_14

For both:

    quality = favorable - adverse

Use only completed real outcomes in adequacy comparisons. Preserve and report
right-censored real outcomes, but do not impute or include them in medians.

Do not redefine touches, first-touch selection, invalidation, support/resistance
semantics, ATR reference timing, horizon timing, or censoring.

### Deterministic non-zone controls

A control anchor is a closed model bar satisfying every rule below.

#### Entry-visible zone rule

For candidate control bar i, determine zone visibility from the model snapshot
after bar i-1. That snapshot is the information set entering bar i.

An entry-visible zone is a zone in state ACTIVE or BREACH_PENDING in that
previous snapshot. Terminal states are not entry-visible. A zone first created
when bar i closes was not visible while bar i traded and therefore is not used
to exclude bar i.

If bar i has no immediately preceding aligned model snapshot, it is ineligible.

#### Non-zone intersection rule

Reject bar i if its inclusive OHLC range intersects the inclusive band geometry
of any entry-visible zone:

    intersects = bar.high >= zone.lower AND bar.low <= zone.upper

The comparison is side-independent. Support and resistance zones both exclude
the bar. Touch tolerances and break buffers do not widen the exclusion band;
use the exact visible zone geometry.

This previous-snapshot rule is mandatory. Do not use a final snapshot, a
post-bar state, terminal history, future observations, or hindsight event
labels to decide control eligibility.

#### Remaining eligibility rules

A control anchor must also:

- lie inside one frozen fold;
- be at or after the common model start;
- have a finite, positive Wilder ATR(14) reference on the anchor bar;
- have all 10 outcome bars available;
- have every outcome bar close strictly before the same fold end;
- use outcome bars i+1 through i+10 exactly;
- not be filtered by any future outcome, event, return, state transition, or
  realized quality.

A bar failing one or more rules is rejected once with a deterministic primary
reason selected by this precedence:

1. NO_PREVIOUS_MODEL_SNAPSHOT;
2. OUTSIDE_FOLD_OR_WARMUP;
3. ATR_UNAVAILABLE_OR_INVALID;
4. ENTRY_VISIBLE_ZONE_INTERSECTION;
5. INCOMPLETE_SAME_FOLD_HORIZON.

Persist total considered, eligible, and rejected counts and each rejection
reason by fold. The accounting must reconcile exactly.

#### Two directional controls per eligible bar

Every eligible bar creates exactly two control outcomes in this canonical order:

1. pseudo-support;
2. pseudo-resistance.

Both use:

- the same anchor bar close;
- the same anchor-bar ATR(14);
- the same bars i+1 through i+10;
- the exact formulas used by real support and resistance outcomes above.

This avoids an arbitrary side assignment. Do not randomly assign sides, sample
one side, balance counts, deduplicate symmetric outcomes, or weight a control
based on later price action.

Define deterministic control IDs from a schema-versioned canonical payload
containing at least asset, timeframe, fold, anchor bar ID, anchor timestamp,
side, outcome offset, outcome horizon, and frozen config identity.

### Fold-side nulls

For each fold and side separately:

    null_median(fold, side) =
        median(quality of completed eligible controls in that fold and side)

Every eligible control is complete by construction. Any implementation path
that produces a right-censored accepted control is a contract failure.

Map each completed real first-touch outcome to the null median with the same
fold and side:

    excess_quality(real) =
        real.quality_reference_atr - null_median(real.fold, real.side)

A fold is comparable only if:

- it has at least 4 completed real first-touch outcomes in total;
- it has at least 4 eligible pseudo-support controls;
- it has at least 4 eligible pseudo-resistance controls;
- the null median is finite for every real outcome side present in that fold;
- every real completed outcome maps to exactly one fold-side null.

Because each eligible control bar emits both sides, the two control counts
should be equal. Unequal fold-side control counts are a contract failure.

For a comparable fold:

    fold_median_excess =
        median(excess_quality of all completed real outcomes in the fold)

Support-only and resistance-only real-outcome counts and median excesses are
required diagnostics. They are not independent promotion gates in V1.9.

### Aggregate adequacy metrics

Across comparable folds only:

- completed_real_count: number of mapped real completed outcomes;
- comparable_fold_count: number of comparable folds;
- pooled_median_excess_quality: median of every mapped real outcome's
  excess_quality, not a difference between two separately pooled medians;
- positive_comparable_fold_fraction:
  count(fold_median_excess > 0) / comparable_fold_count;
- worst_comparable_fold_excess:
  minimum fold_median_excess.

A zero fold median is not positive.

Report, but do not gate independently:

- each fold/side null median;
- each fold median real quality;
- each fold median excess;
- support and resistance completed counts;
- support and resistance median excess;
- pooled real baseline median quality;
- pooled control support/resistance median quality;
- real invalidation and censoring diagnostics;
- full control eligibility accounting.

Do not add PnL, hit rate, Sharpe, drawdown, trade entries, stops, targets, fees,
position sizing, statistical p-values, confidence intervals, or significance
language.

## Frozen Decision Gates

Lock the following exact threshold payload in the V1.9 YAML and reject any
mutation on load or artifact validation:

- minimum_completed_real_outcomes: 24;
- minimum_comparable_folds: 4;
- minimum_real_outcomes_per_comparable_fold: 4;
- minimum_controls_per_side_per_comparable_fold: 4;
- minimum_pooled_median_excess_quality_atr: 0.10;
- minimum_positive_comparable_fold_fraction: 0.60;
- minimum_worst_comparable_fold_excess_atr: -0.10.

Apply inclusive comparisons except the definition of a positive fold:

- completed_real_count >= 24;
- comparable_fold_count >= 4;
- pooled_median_excess_quality >= 0.10;
- positive_comparable_fold_fraction >= 0.60;
- worst_comparable_fold_excess >= -0.10;
- fold is positive only when fold_median_excess > 0.

Unknown gate names or categories fail closed. Missing, null, non-finite,
wrong-type, or denominator-zero metrics fail closed.

Disposition precedence is exact:

1. If sample/comparability gates cannot be computed or fail:
   INSUFFICIENT_EVIDENCE.
2. Else if all three adequacy gates pass:
   BASELINE_BEATS_NAIVE_NULL.
3. Else:
   BASELINE_NOT_BETTER_THAN_NAIVE_NULL.

Do not change thresholds after observing results. Do not add a secondary
selection rule, tie-break, exception, or qualitative override.

## Baseline Parity and Causality Requirements

Before constructing controls:

1. Validate the exact V1.7 source bundle.
2. Validate the exact V1.7 evaluation bundle.
3. Validate the exact V1.8 study bundle and its RETAIN_BASELINE_GEOMETRY
   disposition.
4. Extract the TAOUSDT baseline candidate with candidate ID 37769b33....
5. Recompute the baseline on the frozen source under the V1.9 implementation.
6. Require exact semantic equality with the approved baseline for:
   - source and config identities;
   - aligned source/model bars;
   - ATR references;
   - initial and terminal state;
   - lifecycle snapshots;
   - trace snapshots;
   - zone observations and visibility;
   - events and event accounting;
   - fold and pooled real first-touch outcomes;
   - completed/right-censored counts;
   - economic first-touch values and aggregate metrics.
7. Permit differences only in V1.9 study/evidence identities that explicitly
   bind the V1.9 implementation and protocol.

Abort before control scoring if parity fails.

Causality probes must demonstrate:

- changing any bar after an anchor cannot change that anchor's eligibility;
- changing any snapshot after an anchor cannot change eligibility;
- a zone created on the anchor bar does not exclude that anchor;
- an ACTIVE/BREACH_PENDING zone visible in the previous snapshot does exclude
  an intersecting anchor bar;
- a terminal-only previous snapshot zone does not exclude;
- future outcome bars affect outcome values but not eligibility;
- fold-end bars cannot borrow outcome observations from the next fold;
- replay/checkpoint restoration produces identical eligibility and controls.

## Data Contracts and Interfaces

### Required additive package

Create:

    src/libs/models/sr/scripts/baseline_adequacy/
    ├── __init__.py
    ├── config.py
    ├── contracts.py
    ├── controls.py
    ├── metrics.py
    ├── runner.py
    ├── artifacts.py
    └── cli.py

Create matching tests:

    tests/models/sr/scripts/baseline_adequacy/
    ├── __init__.py
    ├── conftest.py
    ├── test_config.py
    ├── test_contracts.py
    ├── test_controls.py
    ├── test_metrics.py
    ├── test_runner.py
    ├── test_artifacts.py
    └── test_import_boundaries.py

Create exactly one trial config:

    configs/sr_trials/sr_v1_9_taousdt_1d_baseline_adequacy.yaml

A different internal split is acceptable only if the public responsibilities
remain this clear and no flat catch-all module is introduced.

### Package responsibilities

#### config.py

- duplicate-safe YAML loading at every mapping depth;
- exact immutable V1.9 payload validation;
- exact frozen identity, asset, timeframe, fold, baseline, control, outcome, and
  gate validation;
- rejection of unknown keys;
- no hidden defaults or environment-driven overrides;
- no call-time runtime_override layer.

#### contracts.py

Use immutable typed records for at least:

- BaselineAdequacyConfig;
- ControlEligibilityReason;
- ControlAnchor;
- ControlOutcome;
- FoldSideNull;
- RealOutcomeComparison;
- FoldAdequacyMetrics;
- AdequacyGateResult;
- BaselineAdequacyDecision;
- BaselineAdequacyStudy.

All constructors must validate finite numeric values, UTC timestamps,
cross-field consistency, canonical ordering, unique IDs, count reconciliation,
and allowed enum values.

#### controls.py

- build previous-snapshot entry-visible zone sets;
- perform inclusive band intersection;
- apply eligibility precedence deterministically;
- create exactly two side controls per eligible anchor;
- compute control outcomes under the frozen formula;
- return complete eligibility accounting;
- never inspect future data during eligibility.

#### metrics.py

- compute fold-side null medians;
- map real outcomes to same-fold/same-side nulls;
- compute fold and aggregate excess metrics;
- evaluate the exact gates and disposition precedence;
- keep support/resistance breakdowns diagnostic;
- reject undefined and non-finite economic values.

Reuse an already-approved exported pure outcome primitive if one exists and its
contract matches exactly. Otherwise implement a package-private control outcome
function and prove formula parity with synthetic fixtures against the approved
FirstTouchOutcome semantics. Do not refactor or modify the protected V1.7/V1.8
metrics path merely to share code in this version.

#### runner.py

- load and validate frozen inputs;
- execute baseline parity before controls;
- run one causal baseline replay continuously across all folds;
- build controls and adequacy metrics;
- construct the deterministic study;
- contain no provider/network/source-preparation path;
- accept an explicit implementation commit for evidence identity;
- return no unvalidated plain dictionaries across package boundaries.

#### artifacts.py

- emit deterministic canonical JSON;
- reject duplicate keys recursively;
- recompute and validate member hashes, study ID, and bundle ID;
- perform semantic validation, not hash-only validation;
- bind all frozen source/evaluation/study/config/commit identities;
- validate all outcomes, controls, comparisons, gates, counts, and disposition;
- reject recomputed-hash tampering;
- reject identity substitution, event/control deletion, reordering,
  duplication, and threshold mutation.

#### cli.py

Expose only:

- evaluate;
- validate.

No fetch, prepare-source, rerun-provider, promote, deploy, serve, or DB command
belongs in V1.9.

### Import boundaries

The new package may import:

- Python standard library;
- approved SR domain/config/replay/evaluation contracts;
- V1.7 cohort-readiness loaders/replay helpers where they are pure and
  source-reuse-only;
- V1.8 geometry artifact validation/extraction helpers where they do not invoke
  providers;
- sibling baseline_adequacy modules.

It must not import:

- Binance/provider adapters;
- HTTP/network clients;
- source-preparation or live-trial entry points;
- browser/viewer code;
- database clients;
- production strategy/execution code;
- holdout preparation/scoring modules.

Relative and absolute import scans must use the repository's approved allowlist
logic and fail on unresolved or unknown imports.

### Trial YAML

The YAML is the only V1.9 research configuration. It must explicitly contain
and lock:

- schema and protocol versions;
- exact source, V1.7 evaluation, V1.8 bundle/study, config, and commit
  identities;
- exact TAOUSDT/binance_usdm/1d scope;
- the complete baseline SR and ATR values;
- all six folds;
- outcome offset and horizon;
- entry-visible states [ACTIVE, BREACH_PENDING];
- inclusive intersection semantics;
- previous-snapshot visibility rule;
- exactly two controls per eligible bar in [SUPPORT, RESISTANCE] order;
- eligibility-reason precedence;
- every frozen gate and disposition;
- output root research/tmp_sr_v1_9/evaluation.

Reject aliases, merge keys, duplicate keys, unknown keys, implicit fallback
values, and altered immutable content.

## Deterministic Evidence Contract

Write the final evidence to:

    research/tmp_sr_v1_9/evaluation/<bundle_id>/
    ├── manifest.json
    └── study.json

Do not create a database. Do not commit generated evidence.

Canonical serialization must:

- use UTF-8;
- sort mapping keys;
- use compact stable separators;
- use explicit UTC timestamp strings;
- reject NaN and infinity;
- preserve canonical sequence ordering;
- terminate files consistently;
- exclude filesystem paths, current wall-clock time, hostnames, usernames,
  process IDs, and other machine-local data from identities.

### study.json minimum content

Persist at least:

- schema/protocol version;
- implementation commit;
- frozen input identities;
- TAOUSDT source identity and bar count/grid;
- exact resolved baseline config and hash;
- baseline parity result;
- fold definitions;
- real completed and censored outcomes;
- every considered control anchor with eligibility result and primary reason;
- every accepted support/resistance control outcome;
- fold-side null medians;
- every real-to-null comparison;
- fold metrics;
- aggregate metrics;
- gate records including category, observed value, threshold, operator, pass;
- exact disposition;
- complete accounting and invariant checks.

If persisting every rejected anchor duplicates excessive payload, the study may
persist canonical rejected-anchor IDs plus reason and essential identity rather
than full OHLC, but it must remain independently semantically validatable
against the frozen source.

### manifest.json minimum content

Persist:

- schema version;
- study ID;
- bundle ID;
- implementation commit;
- config hash;
- all upstream bundle/study/evaluation IDs;
- member filename, byte length, and SHA-256;
- disposition;
- created_by protocol identity without wall-clock time.

The bundle ID must be derived from the canonical manifest identity payload and
member identities with no self-referential ambiguity.

Run the final evaluation twice from clean generated-output state. Both runs must
produce identical:

- study ID;
- bundle ID;
- filenames;
- bytes;
- member hashes;
- metrics;
- gates;
- disposition.

## Implementation Order

### Phase 0: authorize and isolate

1. Verify exact base branch/HEAD and dirty-worktree exclusions.
2. Verify V1.8 handoff and evidence identities.
3. Create feature/sr-v1.9-baseline-adequacy.
4. Commit this approved handoff only.
5. Record the handoff commit for the coder-to-review document.

### Phase 1: freeze configuration and contracts

1. Add the immutable trial YAML.
2. Implement strict duplicate-safe loading and exact-payload checks.
3. Implement immutable contracts and invariants.
4. Add config mutation and contract tests before the runner.

### Phase 2: implement causal controls

1. Reuse the frozen TAOUSDT source and baseline replay.
2. Establish aligned bar-to-previous-snapshot mapping.
3. Implement entry-visible ACTIVE/BREACH_PENDING extraction.
4. Implement inclusive geometry intersection.
5. Implement deterministic eligibility precedence and accounting.
6. Emit two directional controls per eligible bar.
7. Add causality, fold-boundary, and formula-parity tests.

### Phase 3: implement metrics and decisions

1. Compute fold-side null medians.
2. Map every completed real outcome by fold and side.
3. Compute fold median excess and aggregate adequacy metrics.
4. Apply frozen gates with exact boundary tests.
5. Apply disposition precedence and fail-closed behavior.
6. Add synthetic PASS, FAIL, and INSUFFICIENT_EVIDENCE fixtures.

### Phase 4: runner and artifacts

1. Validate all frozen evidence.
2. Require exact baseline semantic parity.
3. Run the controls and decision.
4. Serialize canonical study and manifest.
5. Implement independent artifact validation and adversarial tamper tests.
6. Add provider/network and import-boundary spies.

### Phase 5: evidence and handoff

1. Run targeted tests.
2. Run the complete SR suite.
3. Run boundary, Ruff, compile, import, and protected-diff checks.
4. Generate the V1.9 evaluation twice and verify byte identity.
5. Validate the final artifact through the CLI.
6. Write plans/coder-to-review-sr-v1.9-baseline-adequacy-v1.md.
7. Commit code/tests and the handoff in reviewable commits.
8. Leave generated evidence untracked and branch unmerged.

## Acceptance Criteria

V1.9 is review-ready only when all conditions below hold.

### Scope and lineage

- branch is feature/sr-v1.9-baseline-adequacy;
- branch descends from exact 0fc43a19;
- approved handoff was committed before implementation;
- only additive V1.9 package, tests, YAML, and handoff changes are committed;
- protected configs/core/provider/viewer/holdout paths are unchanged;
- unrelated dirty files and plan drafts are untouched;
- no merge occurred.

### Frozen-input integrity

- exact V1.7 source and evaluation bundles validate;
- exact V1.8 study validates with RETAIN_BASELINE_GEOMETRY and no challenger;
- TAOUSDT source identity, bar grid, and hashes match;
- production SR/input config hashes match;
- no provider, network, or source-preparation path is reachable.

### Baseline parity

- V1.9 baseline replay is semantically identical to approved TAOUSDT baseline;
- all 36 completed and 0 right-censored pooled TAOUSDT baseline outcomes are
  preserved;
- pooled TAOUSDT baseline median quality remains approximately -0.014 only as a
  human-readable diagnostic; validation uses exact persisted values;
- fold completed counts remain 7, 8, 6, 6, 3, 4 in canonical order;
- any exact economic or lifecycle parity mismatch aborts the study.

### Control correctness

- eligibility uses the immediately previous aligned snapshot;
- only ACTIVE and BREACH_PENDING are entry-visible;
- intersection uses exact inclusive band geometry;
- eligibility cannot depend on current-close-created zones or future data;
- accepted anchors have finite positive ATR and complete same-fold horizons;
- each accepted anchor yields exactly SUPPORT then RESISTANCE controls;
- side counts are equal in every fold;
- formulas match the approved real outcome semantics exactly;
- considered = eligible + all rejection counts;
- IDs and ordering are deterministic and unique.

### Metric and gate correctness

- fold-side nulls use medians of the correct side controls;
- real outcomes map only to same-fold/same-side nulls;
- pooled median excess is a median of per-real excess values;
- comparable-fold rules and counts are exact;
- zero fold excess is not a positive fold;
- all exact gate boundaries have pass/fail tests;
- missing, non-finite, unknown, and zero-denominator conditions fail closed;
- disposition precedence is exact;
- support/resistance findings remain diagnostics only.

### Artifact integrity

- artifacts bind all upstream identities and the V1.9 implementation commit;
- member hashes, study ID, and bundle ID recompute correctly;
- duplicate-key, identity, control, comparison, count, ordering, threshold,
  disposition, and recomputed-hash tampering are rejected;
- evaluate run twice produces byte-identical output;
- validate accepts only the final untampered bundle;
- evidence remains untracked.

## Validation Checklist

Run at minimum:

1. All tests under tests/models/sr/scripts/baseline_adequacy.
2. The existing ATR calibration, cohort readiness, geometry sensitivity,
   observation/evaluation, replay, and lifecycle suites touched by reuse.
3. The complete tests/models/sr suite.
4. Import-boundary tests using the approved allowlist.
5. Ruff on all changed Python source and tests.
6. Python compilation/import of every changed module.
7. Strict YAML duplicate-key and immutable-payload mutation matrix.
8. Synthetic control formula parity for support and resistance.
9. Causality probes covering previous/current/future snapshots and bars.
10. Fold-boundary and no-cross-fold-horizon probes.
11. Checkpoint replay equivalence probe.
12. PASS, FAIL, INSUFFICIENT_EVIDENCE, exact-boundary, unknown-gate, and
    undefined-metric decision probes.
13. Provider construction/import/network spy around the full runner.
14. Semantic artifact tamper matrix, including recomputed-hash tampering.
15. Protected diff proving no production config, SR core, provider, viewer,
    database, or holdout change.
16. Two independent evaluation runs with byte comparison.
17. Final CLI validation of the emitted bundle.

The coder-to-review handoff must report exact commands, counts, bundle/study
IDs, hashes, disposition, fold/control accounting, gate matrix, all commits,
dirty-worktree exclusions, and any limitation. Do not report only "passed."

## Stop Conditions

Stop and return Blocked without generating final evidence if:

- exact base or upstream identity differs;
- frozen artifacts fail validation;
- source/provider access would be required;
- baseline parity fails;
- eligibility cannot be established from a previous aligned snapshot;
- accepted controls become right-censored or cross folds;
- outcome formula parity fails;
- a required metric is undefined outside the explicit
  INSUFFICIENT_EVIDENCE path;
- deterministic reruns differ;
- artifact semantic validation fails;
- implementation would require modifying protected SR core/config/provider,
  viewer, database, or holdout code;
- unrelated worktree changes cannot be preserved.

A computed BASELINE_NOT_BETTER_THAN_NAIVE_NULL or INSUFFICIENT_EVIDENCE is a
valid study result, not an implementation blocker.

## Explicit Non-Goals

V1.9 does not:

- tune geometry, ATR, lifecycle, association, or any other parameter;
- add features, scores, ranks, weights, confidence, regime filters, volume
  logic, trendlines, confluence, multi-timeframe logic, or ML;
- add randomness, resampling, matching, bootstrapping, or p-values;
- add an asset/timeframe override;
- expand beyond TAOUSDT/1d;
- fetch or persist new market data;
- open, create, inspect, or score any holdout;
- modify production configs or runtime behavior;
- add a per-model database, Turso, SQLite, or persistence service;
- change the V1.5 chart or address event-label overlap;
- claim trading profitability or readiness;
- merge any branch.

## Post-V1.9 Routing

If disposition is BASELINE_BEATS_NAIVE_NULL:

- next plan: SR-V1.10 deterministic visual casebook and decluttered
  market-context review for representative success, failure, false-breakout,
  and lifecycle cases;
- only after V1.10 review may a separate V1.11 fresh forward shadow/holdout
  protocol be proposed.

If disposition is BASELINE_NOT_BETTER_THAN_NAIVE_NULL:

- stop parameter and feature work;
- return to architecture/research review of the first-touch outcome, zone
  lifecycle meaning, and null definition;
- do not rescue the result with more features or wider searches.

If disposition is INSUFFICIENT_EVIDENCE:

- diagnose only the pre-registered sample/comparability failure;
- do not lower gates or expand data in the same study;
- any new window or cohort requires a separately approved protocol.
