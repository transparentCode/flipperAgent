---
goal: Implement SR-V1.10 as a deterministic, development-only TAOUSDT market-context semantics audit and complete visual casebook for the approved negative V1.9 result.
stage: orchestrator-to-coder
date_created: 2026-07-16
last_updated: 2026-07-16
owner: Quant Orchestrator
status: Approved
tags: [handoff, quant, sr, v1.10, context-audit, lifecycle, casebook, taousdt, evidence, leakage-control]
source_agent: Quant Orchestrator
target_agent: Coder Agent
base_commit: 676feeaac0993020355e6da155771e65642eec51
source_branch: feature/sr-v1.9-baseline-adequacy
target_branch: feature/sr-v1.10-context-semantics-audit
---

# Orchestrator To Coder: SR-V1.10 Market-Context Semantics Audit v1

## Objective

SR-V1.9 is implementation-approved with the valid development disposition
BASELINE_NOT_BETTER_THAN_NAIVE_NULL.

The retained TAOUSDT/1d baseline passed every sample and comparability gate but
failed all three quality gates against the pre-registered non-zone null:

- pooled median excess quality: 0.026200435413100243, required at least 0.10;
- positive comparable-fold fraction: 0.4, required at least 0.60;
- worst comparable-fold excess: -1.1546071281136923, required at least -0.10.

This result is authoritative for the V1.9 directional first-touch hypothesis.
It must not be weakened, re-labelled, or rescued by parameter tuning, feature
engineering, another horizon, another null, or a wider search.

The intended role of this SR model is market context. V1.10 therefore performs
one bounded diagnostic audit answering:

> What exact zone geometry, causal lifecycle path, touch-close relationship,
> and favorable/adverse decomposition produced the V1.9 result, and is the
> current unconditional first-touch directional target an adequate description
> of the structural context supplied by the model?

V1.10 is not a replacement hypothesis test. It is a deterministic forensic
ledger and visual casebook. It makes no promotion decision. Architecture and
research review after V1.10 will decide whether a separately pre-registered
context hypothesis is warranted.

## Exact Start and Branch Workflow

Start from the exact approved V1.9 documentation HEAD:

- source branch: feature/sr-v1.9-baseline-adequacy;
- base commit: 676feeaac0993020355e6da155771e65642eec51;
- V1.9 implementation commit:
  542faeb0991617ec38a3f7cc13551a26c0f567f0;
- V1.9 handoff commit:
  676feeaac0993020355e6da155771e65642eec51.

Before implementation:

1. Confirm branch and HEAD exactly.
2. Confirm the V1.9 coder handoff is Ready and the final evidence below
   validates from the documentation HEAD.
3. Create feature/sr-v1.10-context-semantics-audit from exact commit 676feea.
4. Commit this approved handoff as the first V1.10 branch commit.
5. Implement only after that authorization commit exists.
6. Do not rewrite or recommit V1.9 evidence, configuration, or handoff.
7. Do not merge any branch.

If any identity differs, stop and return Blocked.

## Protected Working Tree

The source checkout contains pre-existing user-owned state, including:

- modified .codebase-memory/artifact.json;
- deleted .codebase-memory/graph.db.zst;
- historical untracked plan drafts.

Preserve it exactly. Do not stage, delete, restore, rewrite, move, or include it
in any commit. Generated V1.10 audit evidence must remain untracked.

## Frozen Input Evidence

### V1.9 adequacy evidence

Use and validate exactly:

- configuration:
  configs/sr_trials/sr_v1_9_taousdt_1d_baseline_adequacy.yaml;
- config hash:
  ae8b290674f8c9feb3ce630910753f44dcff87a64795428f614735b0cc2dc9a9;
- bundle path:
  research/tmp_sr_v1_9/evaluation/12af91cecc3582606da7c41c0c1beaf0320aa17eef8c52edf615214cf0a34df6;
- bundle ID:
  12af91cecc3582606da7c41c0c1beaf0320aa17eef8c52edf615214cf0a34df6;
- study ID:
  ed19698fec505e2e8cf1057c41336da7c0720bcf412530244139e5c523f12c9f;
- implementation commit:
  542faeb0991617ec38a3f7cc13551a26c0f567f0;
- disposition:
  BASELINE_NOT_BETTER_THAN_NAIVE_NULL;
- manifest byte length: 10528;
- manifest SHA-256:
  5e0942b7c47d1cb31aae93a1b676abf1eafb46592453ccb357801fa59ad1c9d3;
- study.json byte length: 857146;
- study.json SHA-256:
  fe80a2933b7f0ef266bbc43756e9a043515f153d6af64b50660ebe832b9c8abf.

The V1.9 validator must perform semantic recomputation before the audit uses any
V1.9 record. File hashes alone are insufficient.

### Upstream frozen evidence

The V1.10 audit may reuse only the upstream artifacts already bound by V1.9:

- V1.7 source bundle:
  6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9;
- TAOUSDT source member:
  fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120;
- V1.7 evaluation bundle:
  824e9265a63073ba792762a891adf52deec9677d791c40641dc0107c1f2b840d;
- V1.7 evaluation ID:
  49a895360774ec0c46349eae2d1ec6f56e7262e5f1411ab992f9886d9040fa8d;
- V1.8 study bundle:
  b0ea33decc9c8c40dab98bdbb90635652dc199031fc50b27d3a71a6711378941;
- V1.8 study ID:
  2a324d3a203642bf9030aede611a8d874fcb051c5b394fcb4758582d6cfbc954;
- baseline candidate:
  37769b33cc663e4baf5488001252a996b9cb2ec67d0182400f12cb928015709c;
- production SR config hash:
  cb9b4143921de95c5423899a5655fef0b186cf1f8e9a84c69427bf64df030299;
- frozen input config hash:
  5ece92803341696df06efa0dba5d7a44ee0f5451aa3ce6555d3a4ef6c59fab6d.

No provider construction, Binance import, network call, source refresh, bar
repair, new source capsule, or holdout path is permitted.

## Frozen Model and Data Scope

Use only:

- venue: binance_usdm;
- asset: TAOUSDT;
- timeframe: 1d;
- 629 frozen source bars;
- grid: 2024-04-11T00:00:00Z through 2025-12-31T00:00:00Z;
- Wilder RMA ATR period 14 with SMA seed;
- pivot_span_bars: 5;
- zone_half_width_atr: 0.25;
- merge_distance_atr: 0.50;
- touch_tolerance_atr: 0.25;
- break_buffer_atr: 0.25;
- break_confirm_closes: 2;
- max_age_bars: 50;
- max_active_zones: 8;
- outcome start: next bar;
- outcome horizon: 10 bars;
- the same six V1.9 half-open folds.

State continues across folds. Do not reset the engine at fold boundaries.

## Package and File Scope

Add one trial configuration:

- configs/sr_trials/sr_v1_10_taousdt_1d_context_audit.yaml.

Add one research-only package:

- src/libs/models/sr/scripts/context_audit/__init__.py;
- src/libs/models/sr/scripts/context_audit/config.py;
- src/libs/models/sr/scripts/context_audit/contracts.py;
- src/libs/models/sr/scripts/context_audit/audit.py;
- src/libs/models/sr/scripts/context_audit/artifacts.py;
- src/libs/models/sr/scripts/context_audit/runner.py;
- src/libs/models/sr/scripts/context_audit/cli.py.

Keep modules cohesive. Do not create extra modules unless a concrete separation is
required by size or import boundaries.

Add matching tests under:

- tests/models/sr/scripts/context_audit/.

The existing SR viewer may receive a minimal backward-compatible casebook mode:

- src/libs/models/sr/tools/zone_viewer/payload.py;
- src/libs/models/sr/tools/zone_viewer/index.html;
- src/libs/models/sr/tools/zone_viewer/src/main.js;
- src/libs/models/sr/tools/zone_viewer/src/styles.css;
- existing viewer Python and JavaScript tests.

Do not create a second chart framework or duplicate the viewer. Existing V1.5
chart payloads and server behavior must remain valid byte-for-byte at their
public contract boundary when the optional casebook block is absent.

Use the existing pinned TradingView Lightweight Charts 5.2.0 dependency and
lockfile. Do not contact npm or upgrade dependencies.

## Strict Configuration Contract

The V1.10 YAML must contain all trial choices and frozen identities. No
environment-variable substitution, call-time override, permissive extra keys,
or hidden model default is allowed.

At minimum, bind:

- schema and trial name;
- asset, timeframe, venue;
- exact V1.9 config path/hash;
- exact V1.9 bundle path/ID/study ID/implementation commit/disposition;
- exact upstream source and evaluation identities;
- production SR and input config hashes;
- exact outcome horizon and fold definitions;
- output root: research/tmp_sr_v1_10/audit;
- case ordering: first_touch_at, then zone_id;
- viewer attribution enabled;
- diagnostic-only purpose.

Reuse the repository's duplicate-key-rejecting SafeLoader pattern. Unknown,
missing, duplicate, non-finite, wrong-type, or identity-mismatched values fail
closed.

Do not add asset/timeframe overrides. This configuration is one frozen
TAOUSDT/1d audit, not a general tuning surface.

## Audit Universe and Reconciliation

The case universe is exactly the 36 approved pooled first-touch outcomes from
the validated V1.7/V1.9 baseline.

For each case:

1. Locate the approved pooled outcome in the validated V1.7 evaluation.
2. Map it to the V1.9 fold-local RealOutcomeRecord by exact:
   - zone_id;
   - touch_bar_id;
   - first_touch_at;
   - side.
3. Map a V1.9 RealOutcomeComparison only when V1.9 actually persisted one.
4. Locate the exact zone definition, observations, and events in the validated
   causal replay trace.
5. Locate the exact touch bar and ten pooled outcome bars in the frozen source.

Required reconciliations:

- 36 unique approved pooled cases;
- 36 unique fold-local records;
- approved pooled: 36 completed, 0 right-censored;
- fold-local: 34 completed, 2 right-censored;
- comparable mapped: 31 completed across five comparable folds;
- exactly five fold-local records have no persisted V1.9 comparison;
- all zone, bar, timestamp, side, fold, source, config, and trace identities
  match;
- no record is silently dropped, duplicated, imputed, or reassigned.

Any failure is a blocking contract error. Do not emit a partial final bundle.

## Exact Case Ledger

Persist one immutable record per case, ordered by first_touch_at then zone_id.

### Identity fields

- case_id: deterministic hash of the complete semantic case payload excluding
  case_id itself;
- V1.9 fold-local record_id;
- optional V1.9 comparison real_outcome_id or null;
- zone_id;
- side;
- fold;
- touch_bar_id;
- first_touch_at.

### Zone fields

Use exact replay observations:

- source;
- render kind;
- lower bound;
- center;
- upper bound;
- ATR at creation;
- created_at;
- available_at;
- visible_from;
- visible_until;
- zone age_bars at first touch;
- touch_count and fakeout_count at first touch;
- status entering the touch bar;
- status after the touch bar.

The entering status must come from the immediately preceding aligned snapshot.
Do not infer it from the final snapshot.

### Touch-bar fields

Persist the exact touch-bar:

- open, high, low, close, volume;
- reference ATR(14);
- close location relative to the exact zone band.

Close location has exactly three values:

- BELOW_BAND when close < lower bound;
- INSIDE_BAND when lower bound <= close <= upper bound;
- ABOVE_BAND when close > upper bound.

This is a descriptive close-location label. Do not infer the order of high,
low, touch, rejection, or breach inside a daily OHLC bar. Do not calculate
same-bar post-touch reaction because intrabar sequencing is unavailable.

### Outcome fields

Persist both named outcome views.

Approved pooled view:

- completed;
- right_censored;
- invalidated;
- tenth_outcome_bar_closed_at;
- anchor close;
- reference ATR(14);
- favorable_reference_atr;
- adverse_reference_atr;
- quality_reference_atr.

Fold-local view:

- completed;
- right_censored;
- invalidated;
- tenth_outcome_bar_closed_at or null;
- favorable_reference_atr or null;
- adverse_reference_atr or null;
- quality_reference_atr or null.

Comparison view, only when persisted by V1.9:

- same-fold/same-side null median;
- real quality;
- excess quality.

Do not recompute or invent an excess value for the five non-comparable records.

### Lifecycle window

The descriptive lifecycle window begins with the first-touch event and ends at
the approved pooled tenth outcome bar, inclusive.

Persist the exact ordered event sequence for the selected zone in that window:

- event_id;
- event type;
- timestamp;
- bar_id;
- price;
- snapshot identity and as-of time.

The event vocabulary remains exactly:

- CREATED;
- TOUCHED;
- BREACH_STARTED;
- FALSE_BREAKOUT;
- BREAK_CONFIRMED;
- EXPIRED.

CREATED normally precedes the window. Persist the exact single CREATED event
separately as creation_event and require its zone identity and timestamp to
match the zone definition. Do not synthesize it or insert it into the bounded
lifecycle-window sequence.

Derive one horizon_lifecycle_class using this exact precedence:

1. BREAK_CONFIRMED if any BREAK_CONFIRMED occurs in the window;
2. FALSE_BREAKOUT_NO_CONFIRMED_BREAK if at least one FALSE_BREAKOUT occurs and
   no BREAK_CONFIRMED occurs;
3. EXPIRED_NO_BREAK_OR_FALSE_BREAKOUT if EXPIRED occurs with neither of the
   above;
4. NO_TERMINAL_OR_FAKEOUT_EVENT otherwise.

This label is descriptive and future-known. It must never be represented as an
entry-time feature, filter, signal, or production field.

Persist the exact status after the tenth outcome bar. Validate it against the
corresponding snapshot rather than reconstructing it from only the event list.

## Diagnostic Tables

Generate only fixed descriptive tables. No table is a promotion gate.

### V1.9 parity table

Reproduce byte-for-byte numeric parity for:

- the three named populations;
- six fold metrics;
- 12 fold-side null records;
- 31 comparisons;
- control accounting;
- all 13 gate records;
- the unchanged negative disposition.

### Fold and side decomposition

For each of six folds and both sides, report:

- approved pooled case count;
- fold-local completed and censored counts;
- comparable-mapped count;
- median favorable excursion;
- median adverse excursion;
- median quality;
- median persisted excess when defined.

Undefined medians remain null. No imputation.

### Lifecycle decomposition

For each horizon_lifecycle_class and side, report:

- count;
- fold-local completed and censored counts;
- median approved-pooled favorable excursion;
- median approved-pooled adverse excursion;
- median approved-pooled quality;
- median persisted excess among mapped comparisons.

### Touch-close decomposition

For each close-location value and side, report the same descriptive fields.

### Zone-age summary

For each side, report only:

- count;
- minimum age_bars;
- median age_bars;
- maximum age_bars.

Do not introduce age bins, thresholds, ranks, scores, correlations, p-values,
confidence intervals, bootstrap samples, regime labels, or leave-one-fold-out
selection.

The report may describe concentration and heterogeneity. It must not claim that
a small subgroup is validated or promotable.

## Visual Casebook Contract

Extend the existing viewer through an optional casebook block bound to the
audit bundle.

The casebook must:

- expose all 36 cases;
- order them by first_touch_at then zone_id;
- render exactly one selected case by default;
- offer filters for fold, side, fold-local completion status,
  horizon_lifecycle_class, and touch close location;
- never remove a case from the underlying payload;
- show the selected zone only;
- show only the selected zone's events;
- mark creation, touch, breach start, false breakout, confirmed break, and
  expiry when present;
- visually identify the fixed next-10-bar outcome window;
- show the full source candles and focus the time scale from zone creation
  through the tenth outcome bar; users may pan or zoom outside it;
- display zone geometry only for its approved visibility interval;
- display the approved pooled and fold-local outcomes separately;
- display null/excess only when the V1.9 comparison exists;
- display a permanent diagnostic-only notice and the unchanged V1.9 negative
  disposition;
- preserve TradingView attribution.

Single-case rendering is the required event-label decluttering mechanism.
Do not add marker stacking, label collision engines, canvas text heuristics, or
another chart library.

When no casebook block is present, the V1.5 viewer must retain its existing
behavior.

## Artifact Contract

Write final evidence only beneath:

research/tmp_sr_v1_10/audit/<bundle_id>/

The final bundle contains exactly:

- manifest.json;
- audit.json;
- chart_payload.json.

No timestamps, host paths, temporary-directory names, git-dirty flags, random
values, or nondeterministic ordering may enter semantic payloads.

The manifest must bind:

- schema and stage;
- V1.10 implementation commit;
- V1.10 config hash and canonical config payload;
- V1.9 bundle/study/config/implementation identities;
- all upstream source/evaluation/config identities;
- audit identity;
- chart payload identity;
- exact member names, hashes, and byte lengths;
- diagnostic-only purpose;
- audit_status: COMPLETE.

The validator must:

1. reject duplicate JSON keys recursively;
2. validate exact manifest and member schemas;
3. validate member byte lengths and SHA-256 hashes;
4. revalidate V1.9 semantically;
5. recompute the complete audit and chart payload from frozen inputs;
6. compare canonical semantic payloads exactly;
7. recompute audit, chart, and bundle identities;
8. reject explicit implementation-identity mismatch;
9. default to the manifest implementation identity when validation occurs
   after a later documentation-only commit;
10. reject rehashed semantic tampering.

An incomplete audit produces no final bundle. Do not publish an
AUDIT_INCOMPLETE evidence artifact.

## CLI Contract

Provide only:

- evaluate: validate frozen inputs, compute the audit, publish the bundle, and
  print compact JSON containing bundle_id, audit_id, case_count, audit_status,
  and V1.9 disposition;
- validate: semantically recompute a supplied bundle and print the same compact
  identity summary.

Evaluation accepts the V1.10 config path and optional output root only. It
accepts no asset, timeframe, model, parameter, horizon, filter, threshold,
candidate, seed, provider, source, or holdout override.

## Import and Runtime Boundaries

The context_audit package may depend on:

- SR domain/config/evaluation/replay contracts;
- frozen baseline_trial, cohort_readiness, and baseline_adequacy loaders;
- deterministic identity and artifact helpers;
- zone_viewer payload helpers.

It must not import:

- Binance/provider adapters;
- network clients;
- source preparation;
- holdout packages;
- execution or trading packages;
- databases or persistence services;
- pandas;
- sklearn, scipy, statsmodels, or optimization libraries;
- browser automation at package import time.

Keep import boundaries enforceable with an AST-based allowlist test and a clean
subprocess import test.

## Required Tests

### Configuration and contracts

Test:

- exact approved YAML loads;
- unknown, missing, duplicate, and wrong-type keys reject;
- all frozen identities reject mutation;
- non-finite numerics reject;
- case IDs and aggregate identities recompute;
- duplicate case, zone, record, comparison real_outcome_id, bar, event, or
  snapshot identity rejects;
- invalid enum and lifecycle class reject;
- count and population reconciliation reject mutation;
- audit_status other than COMPLETE rejects.

### Causality and ledger mapping

Test:

- entering status uses the immediately preceding aligned snapshot;
- after-touch status uses the touch snapshot;
- zone geometry is immutable across observations;
- exact 36-to-36 pooled/fold-local mapping;
- exact 31 comparison mappings and five null mappings;
- no future lifecycle class enters an input or selection path;
- daily OHLC does not produce an intrabar sequence claim;
- lifecycle window boundaries include touch through pooled bar ten only;
- event order is deterministic;
- final horizon status matches the exact snapshot;
- fold state does not reset.

### Parity and descriptive metrics

Test exact V1.9 parity and the frozen real values, including:

- approved pooled 36/36/0, median -0.014070405071082426;
- fold-local 36/34/2, median 0.1807362526958346;
- comparable mapped 31/31/0 across five folds;
- pooled excess 0.026200435413100243;
- positive-fold fraction 0.4;
- worst-fold excess -1.1546071281136923;
- fold completed counts 7, 8, 6, 6, 3, 4;
- 2025_q3 remains non-comparable;
- null and excess values are absent for non-mapped cases;
- undefined table medians stay null;
- favorable minus adverse equals quality for every completed outcome.

### Artifact and determinism

Test:

- round-trip semantic validation;
- two runs produce byte-identical three-file bundles;
- docs-after-evidence validation succeeds using manifest implementation
  identity;
- explicit wrong implementation identity rejects;
- config, source, V1.9, audit, chart, member, count, event, geometry, population,
  lifecycle-class, close-location, hash, byte-length, and bundle-ID tampering
  rejects;
- rehashed semantic counterfeit rejects;
- partial and extra-member bundles reject.

### Viewer compatibility

Test:

- legacy chart payload without casebook retains current behavior;
- all 36 case IDs are selectable;
- filters operate only on the visible selection list and never mutate payload;
- selected case renders one zone and only its events;
- outcome window endpoints are exact;
- changing cases updates zones, events, metrics, and visible range;
- empty filter result is handled without stale chart state;
- terminal-zone and event toggles remain functional;
- hitTest API shape remains valid;
- attribution remains enabled;
- standalone module/server MIME behavior remains valid;
- existing Python and Node viewer suites continue to pass.

Avoid jsdom or a new frontend test framework if pure-function extraction and
Node's existing test runner are sufficient.

## Required Validation Sequence

Run in this order:

1. V1.10 configuration and pure contract tests.
2. Ledger mapping, causality, and exact parity tests.
3. Artifact and tamper tests.
4. Viewer Python tests.
5. Viewer Node tests.
6. Import-boundary and clean-subprocess imports.
7. Complete tests/models/sr suite.
8. Ruff on all changed Python.
9. Python compilation.
10. git diff --check.
11. Verify protected config/core/provider/holdout/database surfaces are clean.
12. Run evaluate twice at the final implementation commit.
13. Compare bundle IDs and all three member files byte-for-byte.
14. Run final CLI validate from the later handoff documentation HEAD.

Do not generate final evidence until the implementation commit is fixed. The
evidence manifest must bind that implementation commit, not the later handoff
commit.

## Manual Browser Smoke

Automated code review does not substitute for visual acceptance.

Serve the final bundle with the existing SR viewer server and provide the exact
local command in the coder handoff.

The Mac Chrome smoke must confirm:

- page loads with no Console errors;
- 36 cases are represented;
- case selector and every filter work;
- selecting a case shows one zone and its event markers;
- labels do not overlap across unrelated cases;
- outcome window is visibly correct;
- pooled and fold-local metrics are distinguishable;
- null/excess is absent where not persisted;
- support/resistance geometry and visibility are correct;
- toggles, hover details, pan, and zoom work;
- TradingView attribution is visible;
- bundle ID and unchanged V1.9 negative disposition are shown.

Record browser name/version if available. If the coder environment has no
browser backend, report Browser Smoke Pending and make no visual approval
claim. This does not authorize weakening automated validation.

## Stop Conditions

Stop and return Blocked without final evidence if:

- exact base or frozen identity differs;
- V1.9 semantic validation fails;
- the 36 pooled and fold-local records cannot map one-to-one;
- comparison count differs from 31;
- replay geometry, events, statuses, or snapshots do not reconcile;
- intrabar event ordering would need to be inferred;
- a provider, new source, holdout, database, or network call would be required;
- a model, lifecycle, geometry, ATR, horizon, fold, null, gate, or production
  change would be required;
- a partial audit would need to be published;
- deterministic reruns differ;
- artifact semantic validation fails;
- legacy viewer compatibility cannot be preserved;
- unrelated worktree state cannot be preserved.

## Explicit Non-Goals

V1.10 does not:

- change or promote the SR model;
- tune or test parameters;
- add features, confidence, ranking, regimes, trendlines, volume, confluence,
  multi-timeframe logic, ML, or optimization;
- test alternative horizons, anchors, outcome formulas, nulls, or gates;
- select a profitable subgroup;
- run statistical significance tests;
- fetch or expand data;
- open, create, inspect, or score a holdout;
- change configs/sr.yaml or configs/sr_inputs.yaml;
- add Turso, SQLite, a per-model database, or any persistence service;
- modify execution or trading behavior;
- claim profitability, generalization, or production readiness;
- merge any branch.

## Required Coder Handoff

Create:

plans/coder-to-review-sr-v1.10-context-semantics-audit-v1.md

The handoff must report:

- branch, exact base, authorization, implementation, and handoff commits;
- complete changed-file inventory;
- exact frozen input identities;
- exact audit/config/chart/bundle IDs;
- member hashes and byte lengths;
- exact 36-case, 31-comparison, fold, side, lifecycle-class, and close-location
  accounting;
- V1.9 parity values and unchanged negative disposition;
- deterministic rerun comparison;
- all test commands and exact counts;
- import and protected-scope checks;
- browser smoke status and exact local command;
- dirty-worktree exclusions;
- limitations and any non-blocking follow-up.

No V1.11 work, merge, parameter change, production change, or holdout access is
authorized.

## Post-V1.10 Routing

V1.10 produces diagnostic evidence for human architecture review.

After review, exactly one route may be selected in a separately approved plan:

1. If existing lifecycle paths appear structurally meaningful, pre-register one
   causal market-context hypothesis using existing events only. Likely
   candidates are rejection, break confirmation, or false-breakout resolution,
   but V1.10 must not select among them automatically.
2. If the casebook exposes a causal, geometry, or lifecycle contract defect,
   fix and revalidate the foundation before any new study.
3. If zones remain structurally uninformative, stop the current detector family
   rather than adding features or widening searches.

V1.10 itself authorizes none of these routes.
