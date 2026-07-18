---
goal: Complete the remaining approved SR pre-V2 modular refactor through larger phase-gated work packages while preserving the original architecture, safety constraints, deterministic behavior, and rollback quality.
stage: architect-to-coder
date_created: 2026-07-17
last_updated: 2026-07-17
owner: Quant Architect
status: Ready for Authorization Commit
tags: [handoff, quant, sr, refactor, pre-v2, streamlined-execution, migration, behavior-preserving]
source_agent: Quant Architect
target_agent: Codex Quant Coder
base_commit: a5579c14ce369ea9aca6f074e8a3192bdfed8f85
source_branch: refactor/sr-pre-v2-modularization
target_branch: refactor/sr-pre-v2-modularization
supplements: plans/architect-to-coder-sr-pre-v2-modular-refactor-v1.md
---

# Architect to Coder: SR Pre-V2 Streamlined Remaining Execution v1

## 1. Purpose

This handoff supplements, and does not replace, the approved technical plan:

`plans/architect-to-coder-sr-pre-v2-modular-refactor-v1.md`

The original plan remains authoritative for:

- architecture and ownership boundaries;
- dependency direction;
- configuration and hyperparameter policy;
- behavior-preservation requirements;
- protected evidence and artifact identities;
- explicit non-goals;
- final acceptance criteria.

This supplemental handoff changes only the **execution and reporting cadence** for the remaining work.

The coder must continue using small, ordered, reviewable Git commits and focused tests after each internal step. However, the coder should return to the user/reviewer only at the larger work-package gates defined below, unless an early-stop condition is triggered.

## 2. Current Authorized State

Continue from the exact clean branch state:

- branch: `refactor/sr-pre-v2-modularization`;
- exact HEAD/base for this supplemental directive: `a5579c14ce369ea9aca6f074e8a3192bdfed8f85`;
- latest commit: `refactor(sr): share frozen source primitives`;
- no merge has occurred;
- no R2f2 or R3 work has started.

Completed and accepted phases:

1. R0 baseline and dependency inventory;
2. R1 configuration ownership split and four-layer resolver;
3. R2a path-safety extraction;
4. R2b artifact primitives and hardening;
5. R2c repository provenance and hardening;
6. R2d1 strict research configuration primitives;
7. R2d2 minimal frozen identity contracts;
8. R2e1 neutral `SourceBar` and `CohortFold` ownership;
9. R2e2 neutral `CandidateReplay` and `FirstTouchOutcome` ownership;
10. R2f1 verified frozen-file and source bar/grid identity primitives.

Latest reported validation state:

- full active SR suite: 809 passed;
- R2f1 focused: 55 passed;
- combined R2/cohort/V1.12: 244 passed;
- Ruff, compilation, and diff checks passed;
- worktree clean.

Frozen identities remain authoritative:

- V1.12 trial YAML SHA-256: `8a1c2f2c72213e62638ead381c0f7a50a67d96b527f799afe878065d59b93665`;
- V1.12 resolved config hash: `9855c190ed91744b7a6bd86590be33d480bdf44cc94cc51a29e82eec9d4b099e`;
- V1.12 manifest SHA-256: `c2d0e03f43ea1154bac9c005a2c4d021188a33f56d4ddd17dd6376b9f77c43e6`;
- V1.12 audit SHA-256: `41bd97da3cef62f10a96f263ac0278e0aff524ebe8337abce0aee986995fee32`;
- bundle ID: `fd3eaf4cb58a23ee47c0f8645a3d4affd09ef05bf3cafb74831621826a58c206`;
- audit ID: `cd452938e2befc66f0d2a4e12d79083b88cf6e03a3124180c356d56a6f2b8adb`;
- disposition: `INSUFFICIENT_REINFORCEMENT_EVIDENCE`.

## 3. Authorization Workflow

Commit this supplemental handoff as the next branch commit before implementing further code.

Suggested commit:

`docs(sr): authorize streamlined remaining refactor`

After that authorization commit:

- continue through the complete currently approved work package;
- make small internal commits;
- do not return after every internal commit;
- return only when the full work-package gate passes;
- do not begin the next work package until the current package is independently approved.

## 4. Reporting Cadence

The remaining plan is grouped into eight major work packages:

1. Package A — complete and close R2;
2. Package B — R3a baseline trial and ATR calibration migration;
3. Package C — R3b cohort readiness and geometry sensitivity migration;
4. Package D — R3c baseline adequacy and context audit migration;
5. Package E — R3d lifecycle utility and candidate reinforcement migration;
6. Package F — R4 core domain and evaluation contract cohesion;
7. Package G — R4 lifecycle engine cohesion;
8. Package H — R5 final boundary, cleanup, documentation, and review closure.

Each package may contain multiple internal commits. The coder returns once per package, not once per commit.

## 5. Early-Stop Conditions

Stop immediately and return `Blocked` or `Architecture Escalation Required` when any of the following occurs:

1. Any frozen configuration, manifest, audit, bundle, or semantic identity changes.
2. Candidate, state, snapshot, event, replay, checkpoint, or artifact digests differ.
3. Existing valid behavior cannot be preserved with compatibility facades.
4. A migration requires changing a historical artifact schema or payload.
5. The requested move exposes architecture ambiguity not resolved by the approved plans.
6. Scope expansion is required beyond refactoring and compatibility work.
7. A provider, network, database, sealed source, or holdout path would be required.
8. Evidence would need to be regenerated, republished, normalized, moved, or rewritten.
9. Codebase-memory impact analysis reports an unaddressed HIGH or CRITICAL risk.
10. A full-suite failure cannot be isolated to the current internal commit.
11. An unrelated defect blocks progress and cannot be avoided without changing behavior.

Do not silently improvise around any early-stop condition.

## 6. Package A — Complete and Close R2

### Objective

Complete the neutral shared research infrastructure and formally close R2 before any study-package movement.

### Scope

#### A1. Minimal replay parity primitives

Add only neutral, pure, demonstrably reusable mechanics under:

`src/libs/models/sr/research/replay/parity.py`

Permitted candidates include:

- deterministic replay digest computation using the existing canonical identity implementation;
- exact equality/parity assertion with caller-supplied error context;
- ordered sequence digest helpers when at least two immediate callers use the same exact behavior.

Do not move:

- V1.12 `ReplayParity`;
- V1.12 `PARITY_CHECKS`;
- study-specific baseline parity records;
- study-specific approved check matrices;
- optional universal parity dataclasses;
- semantic interpretation of parity results.

If no useful neutral abstraction exists beyond a trivial alias, document that finding and do not manufacture one. R2f2 may legitimately be a focused no-op decision plus boundary tests.

#### A2. Architecture and import-boundary enforcement

Add or complete AST-based checks under:

`tests/models/sr/architecture/`

Enforce:

- no active import of `libs.sr`;
- no core-to-research import;
- no research shared module importing study implementations;
- no forbidden provider/network/database/holdout/viewer imports in research computation;
- only approved YAML scanner locations;
- no new sibling-study imports;
- no import cycles among active SR packages where the approved tooling can establish them;
- compatibility wrappers contain only imports, `__all__`, comments/docstrings, and necessary `__main__` forwarding.

Do not enforce the final zero sibling-study edge requirement until the R3 migrations complete. Instead record the exact remaining baseline for R3.

#### A3. Updated dependency inventory

Create a durable R2 completion inventory under `plans/` that records:

- canonical shared modules now available;
- current public/compatibility paths;
- remaining sibling-study import edges by importing and imported study;
- remaining duplicated infrastructure;
- files above 500 lines still awaiting R3/R4 ownership work;
- exact full-suite count;
- exact frozen identities;
- R3 entry conditions.

#### A4. R2 completion handoff

Create a coder-to-review handoff for the complete R2 phase.

### Suggested internal commits

1. `refactor(sr): share replay parity primitives` or a documented no-op decision commit if no valid abstraction exists;
2. `test(sr): enforce research architecture boundaries`;
3. `docs(sr): close shared research infrastructure phase`;
4. `docs(sr): hand off R2 completion for review`.

### Package A gate

- all R2-focused tests pass;
- full active SR suite passes;
- Ruff passes for all touched paths;
- full `src/libs/models/sr` compilation passes;
- `git diff --check` passes;
- V1.12 semantic validation passes;
- all frozen hashes and IDs remain exact;
- worktree is clean;
- R2 coder-to-review handoff is complete;
- R3 has not started.

Return only after the entire Package A gate passes.

## 7. Package B — R3a Baseline Trial and ATR Calibration

Begin only after Package A is independently approved.

### Objective

Move the first two studies to canonical ownership under:

- `research/studies/baseline_trial/`;
- `research/studies/atr_calibration/`.

Retain all historical import and CLI paths under `scripts/` as compatibility facades.

### Internal order

1. baseline trial canonical movement;
2. baseline trial compatibility facades and CLI forwarding;
3. baseline trial focused validation;
4. ATR calibration canonical movement;
5. replace cross-study dependencies with neutral shared contracts/services;
6. ATR compatibility facades and CLI forwarding;
7. complete R3a boundary and deterministic validation.

### Requirements

- use `git mv` or equivalent history-preserving moves where practical;
- preserve every public module path currently used by tests or CLIs;
- old and new exported classes must reference the same class objects;
- old CLI module invocations must still work;
- wrappers must contain no business logic;
- no artifact bytes, config files, or generated evidence may change;
- no algorithm, metric, gate, candidate, or outcome computation changes;
- move study-owned constants with the study;
- shared concepts remain in neutral `research/` modules;
- do not absorb one study into another.

### Suggested internal commits

- `refactor(sr): migrate baseline trial study`;
- `refactor(sr): migrate ATR calibration study`;
- `test(sr): lock R3a compatibility boundaries`;
- `docs(sr): hand off R3a migration`.

### Package B gate

- baseline trial and ATR focused suites pass;
- historical import paths and CLIs pass;
- zero new sibling-study imports;
- R3a canonical modules import no other sibling study;
- deterministic artifacts and frozen identities remain exact;
- full SR suite passes;
- worktree clean;
- coder-to-review R3a handoff complete;
- R3b has not started.

## 8. Package C — R3b Cohort Readiness and Geometry Sensitivity

Begin only after Package B approval.

### Objective

Move canonical implementations to:

- `research/studies/cohort_readiness/`;
- `research/studies/geometry_sensitivity/`.

### Internal order

1. cohort readiness movement and facade creation;
2. replace dependencies on ATR/baseline internals with neutral/shared or explicit frozen input interfaces;
3. cohort focused and artifact validation;
4. geometry sensitivity movement and facade creation;
5. replace dependencies on cohort internals with neutral/shared contracts/services;
6. R3b compatibility and deterministic validation.

### Constraints

- do not change readiness or geometry candidate surfaces;
- do not change source or fold semantics;
- do not change baseline parity definitions;
- do not alter optimization/selection thresholds;
- preserve exact artifact and study outputs;
- maintain historical CLI/module behavior.

### Package C gate

- cohort and geometry focused suites pass;
- canonical studies have no sibling-study imports;
- old paths remain valid facades;
- deterministic source, evaluation, and geometry identities remain exact;
- full SR suite passes;
- worktree clean;
- coder-to-review R3b handoff complete;
- R3c has not started.

## 9. Package D — R3c Baseline Adequacy and Context Audit

Begin only after Package C approval.

### Objective

Move canonical implementations to:

- `research/studies/baseline_adequacy/`;
- `research/studies/context_audit/`.

### Internal order

1. baseline adequacy movement;
2. replace cohort/geometry/ATR implementation imports with neutral frozen-evidence interfaces;
3. preserve null/control and parity semantics;
4. context audit movement;
5. replace baseline-adequacy implementation imports with explicit shared input/evidence contracts;
6. compatibility and deterministic validation.

### Constraints

- no null/control changes;
- no metric or outcome changes;
- no context case/comparison population changes;
- no chart or viewer payload changes;
- no reinterpretation of negative evidence;
- preserve all public loaders, validators, and CLI paths.

### Package D gate

- adequacy and context suites pass;
- canonical studies have no sibling-study imports;
- historical CLIs and imports remain functional;
- V1.9/V1.10 artifact semantics remain exact;
- full SR suite passes;
- worktree clean;
- coder-to-review R3c handoff complete;
- R3d has not started.

## 10. Package E — R3d Lifecycle Utility and Candidate Reinforcement Audit

Begin only after Package D approval.

### Objective

Move canonical implementations to:

- `research/studies/lifecycle_utility/`;
- `research/studies/candidate_reinforcement_audit/`.

### Internal order

1. lifecycle utility movement and frozen input interface cleanup;
2. preserve lifecycle resolution/outcome semantics;
3. candidate reinforcement movement;
4. preserve V1.12 semantic validator, publication, CLI, path guards, and artifact identities;
5. remove remaining sibling-study imports through neutral/shared evidence interfaces;
6. complete R3-wide boundary enforcement.

### Critical constraints

- V1.12 bundle and audit bytes must remain exact;
- V1.12 public CLI path must remain executable;
- V1.12 manifest semantic contract remains study-owned;
- V1.12 `ReplayParity` and approved check matrix remain study-owned unless separately escalated;
- no candidate accounting, lineage, fold assignment, or disposition changes;
- no provider, source regeneration, holdout, or publication of new evidence.

### Package E gate

- lifecycle and V1.12 focused suites pass;
- all eight canonical study packages exist under `research/studies/`;
- all old `scripts/<study>` modules are compatibility facades/CLI forwarders;
- production sibling-study import count is zero;
- all historical import paths remain valid;
- full SR suite passes;
- V1.12 semantic validation and frozen bytes remain exact;
- worktree clean;
- coder-to-review R3 completion handoff complete;
- R4 has not started.

## 11. Package F — R4 Core Domain and Evaluation Contract Cohesion

Begin only after Package E approval.

### Objective

Split oversized core contracts by actual ownership while preserving every public import and serialized identity.

### Scope

- canonical `ContractValidationError` ownership;
- split `domain/contracts.py` into bars, geometry, candidates, zones, events, state, snapshots, and errors where justified;
- preserve `domain/contracts.py` as a re-export facade;
- split evaluation contracts only where cohesion is clear;
- preserve evaluation public facades;
- update internal imports to canonical modules;
- remove duplicated contract implementations after all callers migrate.

### Constraints

- no schema changes;
- no constructor or field-order changes;
- no ID/hash changes;
- no broad redesign;
- no plugin systems or extension registries;
- no V2 abstractions;
- no lifecycle behavior extraction in this package beyond import adjustments required by contract movement.

### Package F gate

- all old/new import identity checks pass;
- serialization and replay digests remain exact;
- no core import cycles;
- domain and evaluation focused suites pass;
- full SR suite passes;
- frozen evidence remains exact;
- worktree clean;
- coder-to-review R4-contract handoff complete;
- Package G has not started.

## 12. Package G — R4 Lifecycle Engine Cohesion

Begin only after Package F approval.

### Objective

Make `SREngine.step()` a thin deterministic orchestrator without changing any valid behavior.

### Scope

- extract state and input precondition validation into pure functions;
- extract per-zone lifecycle transitions into pure functions;
- extract candidate-to-zone construction into pure functions;
- retain detection and association ordering exactly;
- preserve capacity accounting and same-batch behavior;
- preserve event ordering and payloads;
- preserve terminal handling and checkpoint replay.

### Constraints

- no detector registry;
- no dependency injection framework;
- no strategy/plugin abstraction;
- no parameter or config changes;
- no exception-order changes for tested invalid inputs without explicit escalation;
- no algorithmic cleanup that can change floating-point or ordering behavior.

### Package G gate

- lifecycle focused suite passes;
- canonical replay, checkpoint, state, snapshot, event, and candidate digests remain exact;
- V1.12 bundle/audit remain exact;
- full SR suite passes;
- worktree clean;
- coder-to-review lifecycle handoff complete;
- R5 has not started.

## 13. Package H — R5 Final Closure

Begin only after Package G approval.

### Objective

Close the refactor as a merge-ready, fully documented, behavior-preserving change.

### Scope

- final architecture/import-boundary tests;
- remove duplicated implementations made obsolete by canonical ownership;
- retain required compatibility facades;
- document facade deprecation/removal conditions without removing them;
- document canonical active package and legacy `src/libs/sr` status;
- document four-layer configuration and hardcoding policy;
- document research/shared/study dependency rules;
- re-index codebase-memory after all moves;
- run final impact and diff-scope checks;
- create complete coder-to-review handoff.

### Required documentation

- `src/libs/models/sr/docs/ARCHITECTURE.md`;
- `src/libs/models/sr/docs/CONFIGURATION.md`;
- `src/libs/models/sr/docs/RESEARCH_BOUNDARIES.md`;
- `src/libs/models/sr/docs/LEGACY_SR_STATUS.md`.

Names may vary slightly if existing documentation ownership requires it, but all four concerns must be covered.

### Package H gate

- all original and new SR tests pass;
- Ruff passes for all active SR and touched test paths;
- full compilation passes;
- `git diff --check` passes;
- no active `libs.sr` import exists;
- no canonical study imports a sibling study;
- core does not import research;
- compatibility facades contain no business logic;
- V1.12 semantic validation passes;
- all frozen identities remain exact;
- codebase-memory is re-indexed and scope impact reviewed;
- worktree clean;
- final coder-to-review handoff complete;
- no merge and no V2 work performed.

## 14. Internal Commit Policy

Within each package:

- use small commits with one ownership concern;
- keep compatibility changes adjacent to the move they protect;
- avoid broad formatter churn;
- do not mix documentation-only authorization with implementation;
- do not squash away useful rollback points;
- do not amend already reviewed commits;
- generated evidence remains untracked and untouched;
- end every package with a clean worktree.

## 15. Test Cadence Inside a Package

After each internal commit:

1. run focused tests for the touched ownership slice;
2. run Ruff on touched active paths;
3. run compilation on touched packages;
4. run `git diff --check`;
5. check relevant public import/CLI compatibility.

At the package gate:

1. run all dependent study suites;
2. run the complete active SR suite;
3. run V1.12 semantic validation;
4. compare exact frozen hashes and IDs;
5. run architecture/import scans;
6. inspect codebase-memory/diff impact;
7. confirm clean worktree.

Do not wait until the end of a large package to discover basic import or syntax failures.

## 16. Configuration and Hardcoding Policy

The original configuration policy remains fully active.

All operational values capable of changing candidates, zones, events, metrics, gates, outcomes, dispositions, or artifact identities must remain typed and configuration-driven.

Allowed precedence remains:

`global defaults → timeframe → asset defaults → exact asset/timeframe`

Historical study protocol values remain bound by their existing typed trial YAML and immutable evidence identities.

Do not introduce:

- call-time parameter overrides;
- implicit defaults;
- hidden module constants replacing YAML values;
- runtime monkeypatch configuration;
- environment-variable parameter substitution;
- dynamic fallback values;
- automatic asset/timeframe substitution.

Code-owned invariants remain limited to schema, enums, deterministic ordering, canonical serialization, safe filesystem behavior, validation rules, and mathematical identities that are not selected hyperparameters.

## 17. Global Non-Goals

This supplemental authorization does not permit:

- SR V2 planning or implementation;
- new detectors, kernels, ensembles, features, scores, or confidence logic;
- parameter tuning or search-space changes;
- new assets, timeframes, folds, windows, or sources;
- provider/network access;
- sealed or holdout access;
- evidence regeneration or republishing;
- database or production integration changes;
- deletion or revival of `src/libs/sr`;
- broad repository cleanup;
- unrelated bug fixes;
- merge to main.

## 18. Package Return Format

At the end of each major package, return one concise report containing:

1. package and commits completed;
2. canonical modules moved or added;
3. compatibility paths retained;
4. sibling/dependency edge counts before and after;
5. focused and full test totals;
6. Ruff, compile, diff, and import-boundary results;
7. deterministic/frozen identities;
8. semantic validation result;
9. worktree status;
10. explicit confirmation that the next package has not started;
11. path to the package coder-to-review handoff.

Do not return a progress report after every internal commit unless an early-stop condition is triggered.

## 19. Immediate Next Action

After committing this supplemental authorization, execute **Package A only**:

- evaluate and, only if justified, extract minimal neutral replay parity primitives;
- complete architecture/import-boundary enforcement;
- update the dependency inventory;
- run complete R2 validation;
- create the R2 coder-to-review handoff;
- return for independent approval;
- do not start R3.
