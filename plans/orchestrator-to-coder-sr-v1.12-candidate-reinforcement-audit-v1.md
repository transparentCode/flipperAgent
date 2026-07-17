---
goal: Implement SR-V1.12 as a deterministic, development-only audit of pivot candidates that the current association path suppresses instead of retaining as zone reinforcement evidence.
stage: orchestrator-to-coder
date_created: 2026-07-17
last_updated: 2026-07-17
owner: Quant Orchestrator
status: Approved
tags: [handoff, quant, sr, v1.12, candidate-reinforcement, association-audit, taousdt, evidence, leakage-control]
source_agent: Quant Orchestrator
target_agent: Coder Agent
base_commit: 6e6a25232ca1c55e32191945176192777c7c290d
source_branch: feature/sr-v1.11-lifecycle-utility
target_branch: feature/sr-v1.12-candidate-reinforcement-audit
---

# Orchestrator To Coder: SR-V1.12 Candidate Reinforcement Audit v1

## Objective

SR-V1.9 produced the valid development disposition:

`BASELINE_NOT_BETTER_THAN_NAIVE_NULL`

SR-V1.10 found no causal or semantic defect that invalidated that result. SR-V1.11 then tested one pre-registered lifecycle-resolution hypothesis and produced:

`LIFECYCLE_CONTEXT_NOT_SUPPORTED`

These negative results are authoritative for their respective hypotheses. V1.12 must not rescue them through parameter tuning, subgroup selection, another outcome definition, a different null, or another lifecycle feature.

A bounded architectural concern remains in the current engine. When a later same-side pivot candidate matches an existing zone, `match_candidate(...)` returns the target and the engine immediately continues. The candidate is not retained as evidence, does not strengthen the zone, and has no traceable seed-to-reinforcement lineage.

V1.12 answers one descriptive question:

> Does the frozen TAOUSDT/1d development replay contain enough independent, same-side pivot candidates currently suppressed by association to justify one separately approved reinforcement-confirmed detector challenger?

V1.12 is a forensic population/readiness audit. It does not evaluate trading utility and does not implement the challenger.

## Exact Start and Branch Workflow

Start from the exact approved V1.11 documentation HEAD:

- source branch: `feature/sr-v1.11-lifecycle-utility`;
- base/documentation commit: `6e6a25232ca1c55e32191945176192777c7c290d`;
- remediation implementation commit: `4d525ef3e50933330af0fd89c4082d550a538eee`;
- V1.11 final disposition: `LIFECYCLE_CONTEXT_NOT_SUPPORTED`.

Before implementation:

1. Confirm the source branch and HEAD exactly.
2. Confirm the updated V1.11 handoff is `Ready`.
3. Semantically validate the exact V1.11 bundle below from the documentation HEAD, using its bound implementation commit.
4. Create `feature/sr-v1.12-candidate-reinforcement-audit` from exact commit `6e6a252...`.
5. Commit this approved handoff as the first V1.12 branch commit.
6. Implement only after the authorization commit exists.
7. Do not rewrite, recommit, or mutate any V1.9, V1.10, V1.10.1, or V1.11 artifact, configuration, viewer, or handoff.
8. Do not merge any branch.

If any identity differs, stop and return `Blocked`.

## Protected Working Tree

Preserve all pre-existing user-owned state exactly, including:

- `.codebase-memory/artifact.json`;
- `.codebase-memory/graph.db.zst`;
- `.codex/config.toml`;
- historical untracked plan drafts;
- all generated evidence from earlier SR versions.

Do not stage, delete, restore, rewrite, move, clean, or include this state in a commit. Generated V1.12 evidence must remain untracked.

## Frozen Upstream Evidence

### V1.11 lifecycle utility evidence

Validate exactly:

- configuration: `configs/sr_trials/sr_v1_11_taousdt_1d_lifecycle_utility.yaml`;
- config hash: `ba2bde0651902e18cf3f9e4835ea087a1d7c0280dd6bc929683c6769b92d8b59`;
- bundle path: `research/tmp_sr_v1_11/lifecycle_utility/evaluation/d771135ca9caded7cfaff578501836c541f279d51280175588de6545aff2d3eb`;
- bundle ID: `d771135ca9caded7cfaff578501836c541f279d51280175588de6545aff2d3eb`;
- study ID: `8d6770dbba05963db93ebe1271e63a37ba369d2d4e8f5a05f6149fbf85f147b9`;
- implementation commit: `4d525ef3e50933330af0fd89c4082d550a538eee`;
- disposition: `LIFECYCLE_CONTEXT_NOT_SUPPORTED`;
- manifest SHA-256: `0709340ce6d647b777604a6e4f4b5aa54f60c606de85c18faee3dd806a4a117a`;
- manifest byte length: 9830;
- study SHA-256: `429ca0665a5b26808ff29bc988e47f46ce53777a9e343cc64761d23bc8e8be00`;
- study byte length: 81750.

File hashes alone are insufficient. Use the V1.11 semantic validator and complete recomputation.

### Frozen source and upstream identities

Bind exactly:

- venue: `binance_usdm`;
- asset: `TAOUSDT`;
- timeframe: `1d`;
- source bundle ID: `d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925`;
- upstream source bundle ID: `6b5a0a81117ba299516fb67ca2da81b3cb6e6f35ed6a85986a27689205a565d9`;
- source ID: `fc1ba274454f277a40f005f542fdfd4e6e752e5afa2e1050f3582b21fd8b1120`;
- bars SHA-256: `703367048f4ed7dc432ca9dfe0ad4afdc5a56eb2a508597ef00bdc3de8b81163`;
- row count: 629;
- exact daily UTC grid: 2024-04-11T00:00:00Z through 2025-12-31T00:00:00Z;
- V1.9 bundle ID: `12af91cecc3582606da7c41c0c1beaf0320aa17eef8c52edf615214cf0a34df6`;
- V1.9 study ID: `ed19698fec505e2e8cf1057c41336da7c0720bcf412530244139e5c523f12c9f`;
- V1.10 bundle ID: `a592276b9fed7c24949ad33b503a7b65474e10f4e3088fe734282401ac058a56`;
- V1.10 audit ID: `147df6b76fea1a2d8cf5f77840f4e82af6e7d7e8207410e2c43249442ea81c07`.

No provider construction, Binance import, network call, source refresh, bar repair, new source capsule, sealed source, or holdout path is permitted.

## Frozen Model Scope

Replay the current approved V1 engine unchanged with:

- Wilder RMA ATR period 14 with SMA seed;
- `pivot_span_bars: 5`;
- `zone_half_width_atr: 0.25`;
- `merge_distance_atr: 0.50`;
- `touch_tolerance_atr: 0.25`;
- `break_buffer_atr: 0.25`;
- `break_confirm_closes: 2`;
- `max_age_bars: 50`;
- `max_active_zones: 8`;
- the same six approved half-open development folds.

State must continue across fold boundaries. Do not reset or warm-start separately per fold.

The canonical `SREngine` state, snapshots, events, zone identities, and checkpoint behavior must remain byte/semantic equivalent to the approved replay. V1.12 may observe and independently reconstruct decisions, but it may not change the core engine to expose them.

## Package and File Scope

Add one strict trial configuration:

- `configs/sr_trials/sr_v1_12_taousdt_1d_candidate_reinforcement_audit.yaml`.

Add one research-only package:

- `src/libs/models/sr/scripts/candidate_reinforcement_audit/__init__.py`;
- `src/libs/models/sr/scripts/candidate_reinforcement_audit/config.py`;
- `src/libs/models/sr/scripts/candidate_reinforcement_audit/contracts.py`;
- `src/libs/models/sr/scripts/candidate_reinforcement_audit/audit.py`;
- `src/libs/models/sr/scripts/candidate_reinforcement_audit/artifacts.py`;
- `src/libs/models/sr/scripts/candidate_reinforcement_audit/runner.py`;
- `src/libs/models/sr/scripts/candidate_reinforcement_audit/cli.py`.

Add focused tests under:

- `tests/models/sr/scripts/candidate_reinforcement_audit/`.

Keep modules cohesive. Extra modules require a concrete separation justified in the coder handoff.

Do not modify production SR configuration, domain contracts, detector, matcher, lifecycle engine, replay engine, state codec, viewer, provider adapters, or existing research packages.

## Strict Configuration Contract

The V1.12 YAML must contain and bind:

- exact upstream artifact paths and identities;
- exact source identity and row/grid contract;
- exact SR/input config hashes used by the frozen replay;
- exact detector, association, lifecycle, capacity, ATR, and fold values;
- decision categories and fixed readiness thresholds;
- artifact schema/stage identity.

Reject:

- unknown keys;
- missing keys;
- recursive duplicate keys;
- implicit defaults;
- runtime overrides;
- call-time parameter overrides;
- asset/timeframe substitution;
- path or identity substitution;
- non-finite numerics;
- booleans accepted as integers;
- unsupported disposition or action names.

The typed config and serialized payload must be immutable and canonically ordered. The config hash must bind the entire resolved payload.

## Candidate Decision Ledger

Reconstruct every candidate produced by the frozen detector in canonical bar/candidate order. Every candidate must map to exactly one decision:

1. `CREATED_ZONE`
   - no eligible match existed;
   - capacity permitted creation;
   - bind the resulting zone ID and seed candidate ID.

2. `MATCHED_START_ZONE_SUPPRESSED`
   - matched a zone present in the bar-start association set;
   - bind the exact target zone and its post-advance status.

3. `MATCHED_SAME_BATCH_ZONE_SUPPRESSED`
   - matched a zone created earlier in the same closed-bar batch;
   - bind the exact target zone and seed candidate.

4. `CAPACITY_SUPPRESSED`
   - no match existed;
   - creation was prevented only by `max_active_zones`.

Do not invent a fifth catch-all category. Any candidate that cannot be reconciled to exactly one category invalidates the audit.

For every candidate record include at least:

- candidate ID;
- state key;
- side;
- source;
- formed-at and available-at timestamps;
- causal formation and availability bar IDs;
- center, half-width, lower and upper bounds;
- ATR at candidate creation;
- replay bar ID and close timestamp;
- decision category;
- target zone ID or created zone ID, as applicable;
- target seed candidate ID, when known;
- target pre-advance and post-advance status for start-zone matches;
- absolute center distance;
- center distance divided by candidate ATR;
- merge threshold in price and ATR units;
- active-zone count before capacity evaluation;
- fold assigned from candidate `available_at`, or explicit `OUTSIDE_EVALUATION_FOLDS`.

All identities and numerics must be finite, typed, and causally available at the recorded decision time.

## Seed Lineage

Because the current `ZoneDefinition` does not retain its originating candidate ID, V1.12 must build a separate immutable audit lineage:

- every `CREATED_ZONE` binds one and only one seed candidate;
- every later match binds through the target zone to that seed candidate;
- no zone may have multiple seeds;
- no candidate may seed multiple zones;
- a same-batch target must already have a preceding canonical `CREATED_ZONE` decision;
- lineage must reconcile with canonical engine zone IDs and creation events.

Do not retrofit lineage into core model contracts.

## Eligible Reinforcement Definition

A candidate is an eligible independent reinforcement only when all conditions hold:

1. Its decision is `MATCHED_START_ZONE_SUPPRESSED`.
2. Candidate ID differs from the target seed candidate ID.
3. Candidate `formed_at` is strictly later than the seed candidate `formed_at`.
4. Candidate `available_at` is strictly later than the target zone `available_at`.
5. The target zone is non-terminal after advancing on the candidate decision bar.
6. Candidate and target zone have the same exact `SRStateKey` and side.
7. The canonical matcher selected that target under the frozen `merge_distance_atr`.
8. Candidate availability lies in one of the six evaluation folds.

A same-batch match is diagnostic but never counts as an independent reinforcement. A match to a zone that becomes `BROKEN` or `EXPIRED` on that bar is diagnostic but not eligible.

For each zone:

- the first eligible reinforcement is the confirmation episode;
- later eligible matches are additional reinforcement diagnostics;
- readiness counts unique reinforced zones, never raw match count.

Do not add minimum-bar separation, reaction strength, volume, wick, close-location, trend, regime, confluence, recency weighting, or ranking.

## Fold and Population Accounting

Assign confirmation episodes to folds by the confirming candidate's `available_at` using the exact six half-open folds.

The audit must report:

- total detector candidates;
- total decisions in each category;
- total created zones;
- total matched start-zone suppressions;
- total same-batch suppressions;
- total capacity suppressions;
- matches by target post-advance status;
- eligible reinforcement candidates;
- unique reinforced zones;
- zones with one, two, and three-or-more eligible reinforcements;
- support/resistance counts;
- per-fold candidate, created-zone, eligible-match, and unique-reinforced-zone counts;
- out-of-fold diagnostics;
- unmatched/reconciliation count, which must be zero.

Global, side, fold, and category totals must reconcile exactly with the record ledger.

## Fixed Readiness Gates

The only decision gates are:

1. `readiness.unique_reinforced_zones >= 16`;
2. `readiness.comparable_folds >= 4`;
3. `readiness.minimum_reinforced_zones_per_comparable_fold >= 2`.

A fold is comparable when it contains at least two unique confirmation episodes.

These thresholds are fixed before inspecting V1.12 results and intentionally reuse prior minimum evidence standards. They are not hyperparameters and must not be searched or relaxed.

No utility, return, excursion, win-rate, outcome, null, profitability, or statistical-significance gate is allowed.

## Required Dispositions

Use exactly:

- `INVALID_EVIDENCE` when contract, upstream validation, replay parity, causality, accounting, identity, or artifact validation fails;
- `INSUFFICIENT_REINFORCEMENT_EVIDENCE` when evidence is valid but any readiness gate fails;
- `READY_FOR_REINFORCEMENT_DETECTOR_CHALLENGER` when evidence is valid and all readiness gates pass.

The ready disposition means only that enough repeated-pivot population exists to justify a separately approved V2.0 development study. It does not claim predictive utility or authorize implementation automatically.

## Replay and Causality Requirements

The audit replay must:

- process bars once in canonical order;
- use only closed bars;
- use the frozen detector and matcher without parameter substitution;
- preserve bar-start association membership and same-batch ordering exactly;
- distinguish pre-advance and post-advance target status;
- preserve nearest-distance then zone-ID tie-breaking;
- preserve match-before-capacity ordering;
- preserve state continuation across folds;
- reproduce canonical SREngine state, snapshot, and event identities;
- produce the same ledger under uninterrupted and checkpoint/resume replay.

At minimum, assert parity at every bar for:

- state identity/payload;
- snapshot identity/payload;
- emitted event order and payload;
- candidate order;
- created zone IDs;
- terminal statuses;
- final state.

Any need to infer intrabar ordering invalidates the audit.

## Deterministic Artifacts

Publish beneath:

`research/tmp_sr_v1_12/candidate_reinforcement_audit/audit/<bundle_id>/`

Required members:

- `manifest.json`;
- `audit.json`.

Generated evidence remains untracked.

The manifest identity must bind:

- schema version and stage;
- implementation commit;
- complete resolved config and config hash;
- V1.11 bundle/study/implementation identities;
- V1.9 and V1.10 identities;
- frozen source and bars identities;
- SR/input config hashes;
- exact protocol and thresholds;
- audit ID and disposition;
- member hashes and byte lengths.

Requirements:

- canonical JSON;
- deterministic IDs;
- exact member allowlist;
- atomic publication;
- repeated publication accepts only byte-identical members;
- recursive duplicate-key rejection;
- unknown-key rejection;
- non-finite rejection;
- path/bundle-name identity validation;
- complete semantic recomputation during validation;
- rehashed tampering rejection;
- implementation-commit mismatch rejection.

Run the audit twice from the same implementation commit. Bundle ID, audit ID, and member bytes must be identical.

## Required Tests

Add focused tests covering at least:

### Decision tracing

- new-zone creation;
- start-zone match suppression;
- same-batch match suppression;
- capacity suppression only after no match;
- nearest-distance/zone-ID tie behavior;
- target that becomes broken on the candidate bar;
- target that becomes expired on the candidate bar;
- candidate/decision one-to-one accounting.

### Lineage and reinforcement

- exact seed linkage;
- duplicate seed rejection;
- missing seed rejection;
- later independent match qualifies;
- same-batch match does not qualify;
- same candidate/seed does not qualify;
- terminal post-advance target does not qualify;
- out-of-fold match does not qualify;
- multiple matches count one unique reinforced zone;
- side/state-key mismatch rejection.

### Folds and gates

- exact half-open boundaries;
- 16 unique zones, four folds, two per fold passes;
- one below each threshold fails;
- sparse folds reconcile;
- unknown gate/category/disposition fails closed;
- no quality or outcome gate can enter the payload.

### Replay and artifacts

- uninterrupted/checkpoint ledger parity;
- canonical engine state/snapshot/event parity;
- deterministic repeated publication;
- semantic recomputation;
- member allowlist;
- wrong implementation binding;
- duplicate JSON/YAML keys;
- unknown keys;
- rehashed study tampering;
- member/path/hash/byte-length tampering.

### Boundaries

- no provider, Binance, network, holdout, production, database, viewer, or legacy `libs.sr` import;
- no modifications to protected core SR packages;
- configuration is the only parameter source.

## Validation Required

Before handoff report:

- focused V1.12 tests;
- full `tests/models/sr` suite;
- approved import-boundary tests;
- Ruff on new Python and tests;
- Python compilation/import checks;
- `git diff --check`;
- protected-scope diff;
- exact branch lineage and absence of merge commits;
- semantic validation of V1.11 upstream;
- semantic validation of V1.12 artifact;
- two byte-identical V1.12 executions;
- independent accounting and gate recomputation.

Report exact commands and counts. Do not claim a check that could not be executed.

## Stop Conditions

Stop and return `Blocked` without final evidence if:

- exact base or upstream identity differs;
- V1.11 semantic validation fails;
- frozen source or config identity differs;
- canonical candidate decisions cannot be reconstructed without core model changes;
- candidate decisions do not reconcile one-to-one;
- seed lineage cannot be proven;
- canonical engine parity fails at any bar;
- checkpoint replay differs;
- intrabar order must be inferred;
- a threshold would need to be changed after seeing results;
- a provider, network, new source, holdout, database, or production path is required;
- an outcome or utility metric would need to be introduced;
- a partial artifact would need to be published;
- deterministic reruns differ;
- unrelated worktree state cannot be preserved.

## Explicit Non-Goals

V1.12 does not:

- modify or promote the SR model;
- implement evidence accumulation in runtime state;
- implement a second-pivot-confirmed zone;
- change zone geometry or lifecycle semantics;
- alter candidate association or capacity behavior;
- add features, scores, confidence, ranking, volume, regime, trendline, MTF, ML, or optimization;
- evaluate returns, excursions, outcomes, nulls, profitability, or utility;
- tune parameters or select a profitable subgroup;
- fetch or expand data;
- open, create, inspect, or score a holdout;
- modify production configs;
- add a database;
- modify the viewer;
- merge any branch;
- start V2.0.

## Required Coder Handoff

Create:

`plans/coder-to-review-sr-v1.12-candidate-reinforcement-audit-v1.md`

The handoff must report:

- branch, exact base, authorization, implementation, and handoff commits;
- complete changed-file inventory;
- exact frozen upstream/source/config identities;
- complete candidate/decision/lineage/fold accounting;
- all gate values and disposition;
- bundle/audit IDs;
- member hashes and byte lengths;
- deterministic rerun comparison;
- checkpoint and canonical replay parity;
- all validation commands and exact counts;
- import and protected-scope checks;
- dirty-worktree exclusions;
- limitations and any non-blocking follow-up.

No merge, V2.0 implementation, parameter change, provider call, holdout access, production change, or viewer work is authorized.

## Post-V1.12 Routing

After independent review, exactly one route may be approved separately:

1. If disposition is `READY_FOR_REINFORCEMENT_DETECTOR_CHALLENGER`, plan V2.0 as one KISS challenger:
   - first pivot creates an internal seed only;
   - first later eligible independent same-side pivot confirms and publishes the zone;
   - initial challenger keeps the frozen geometry and all other parameters unchanged;
   - utility evaluation begins only after confirmation availability;
   - no parameter grid or feature additions.

2. If disposition is `INSUFFICIENT_REINFORCEMENT_EVIDENCE`, retire the current pivot/association family for TAOUSDT/1d. Do not widen the search or add features to manufacture readiness.

V1.12 itself authorizes neither route.
