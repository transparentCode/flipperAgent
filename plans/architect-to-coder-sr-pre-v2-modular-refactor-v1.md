---
goal: Refactor the approved SR V1.12 codebase into a cohesive, config-driven, behavior-preserving architecture before any SR V2 model design or implementation.
stage: architect-to-coder
date_created: 2026-07-17
last_updated: 2026-07-17
owner: Quant Architect
status: Ready for User Approval
tags: [handoff, quant, sr, refactor, modularity, configuration, pre-v2, behavior-preserving]
source_agent: Quant Architect
target_agent: Codex Quant Coder
base_commit: 2ae7e0812a937c63663d528d7fe2465319818123
source_branch: main
target_branch: refactor/sr-pre-v2-modularization
---

# Architect to Coder: SR Pre-V2 Modular Refactor v1

## 1. Objective

Refactor the currently approved SR implementation into a modular, explicitly owned, configuration-driven architecture before any SR V2 research, detector expansion, parameter tuning, or model implementation begins.

This is a structural change only. It must preserve the complete approved SR V1 behavior, public interfaces, deterministic replay, serialized state, artifacts, validation semantics, and evidence identities.

The refactor must solve the following current architecture problems:

1. The active SR implementation exists under `src/libs/models/sr`, while the older and currently unused implementation remains under `src/libs/sr`.
2. The active core is reasonably separated, but several large contract/config modules contain multiple ownership domains.
3. Research studies directly import internal contracts, metrics, source helpers, config loaders, and artifact validators from earlier sibling studies.
4. Deterministic artifact publication, canonical JSON, path safety, manifest validation, Git provenance, frozen-source loading, strict YAML parsing, and replay parity logic are reimplemented in multiple study packages.
5. Study-specific values that already exist in YAML are duplicated as Python constants, creating two sources of truth.
6. The core resolver currently supports global defaults, timeframe overrides, and exact asset/timeframe overrides, but explicitly rejects asset-wide defaults.
7. The current research package layout makes each new study more coupled to historical study implementation details.

The refactor must make future SR V2 work easier without pre-designing or implementing SR V2.

## 2. Authority and Starting Point

Start from the exact merged and approved V1.12 mainline state:

- source branch: `main`;
- exact base commit: `2ae7e0812a937c63663d528d7fe2465319818123`;
- merge commit contains the approved V1.12 implementation;
- approved V1.12 bundle ID: `fd3eaf4cb58a23ee47c0f8645a3d4affd09ef05bf3cafb74831621826a58c206`;
- approved V1.12 audit ID: `cd452938e2befc66f0d2a4e12d79083b88cf6e03a3124180c356d56a6f2b8adb`;
- approved disposition: `INSUFFICIENT_REINFORCEMENT_EVIDENCE`;
- independent focused suite: 49 passed;
- reported full active SR suite: 628 passed.

Create the implementation branch:

`refactor/sr-pre-v2-modularization`

The first branch commit must contain this approved handoff only. Implementation begins after the authorization commit exists.

Do not merge the branch. Return a coder-to-review handoff after implementation.

## 3. Non-Negotiable Architecture Decisions

### 3.1 Canonical active package

`src/libs/models/sr` is the only canonical active SR package.

`src/libs/sr` is legacy/reference-only. It must not be imported by active SR runtime, research, tests, applications, or new code.

Do not delete, rename, reformat, or revive `src/libs/sr` in this refactor. Add documentation and enforcement only.

### 3.2 Core and research separation

The active package must have two explicit dependency domains:

- **Core SR:** deterministic model contracts and execution.
- **SR research:** datasets, frozen inputs, studies, metrics, evaluation protocols, artifact publication, and research CLIs.

Core code must never import research code.

Research code may import public core contracts and APIs.

### 3.3 Study independence

A study may import only:

1. Python standard library and approved dependencies;
2. public SR core modules;
3. shared modules under `libs.models.sr.research`;
4. modules inside the same study package.

A study must not import implementation internals from another sibling study.

Historical import paths may temporarily remain as thin compatibility facades, but the canonical implementation must live in a neutral shared package or the owning study.

### 3.4 One source of truth

Every value that can affect model output, candidate production, association, lifecycle, state capacity, evaluation windows, source selection, metric calculation, gate result, or artifact identity must have one authoritative source.

Values already present in YAML must not be duplicated as Python constants merely to verify the same YAML.

Python code validates types, ranges, schemas, invariants, supported enum values, and cross-field relationships. YAML supplies the selected values.

### 3.5 Behavior preservation

This refactor must not change:

- detected candidates;
- candidate ordering;
- association targets;
- zone identity or geometry;
- lifecycle transitions;
- event order or payload;
- replay order;
- state or snapshot serialization;
- checkpoint behavior;
- evaluation calculations;
- gate thresholds in historical studies;
- dispositions;
- artifact schemas or bytes;
- config files or their hashes;
- any approved historical evidence.

## 4. Selected Target File Structure

The final structure should converge on the following. Minor naming changes are allowed only when they improve ownership and are documented in the coder handoff.

```text
src/libs/models/sr/
├── __init__.py                         # Stable public core API only
├── adapters/
│   ├── __init__.py
│   └── yaml_config.py                  # Compatibility facade if retained
├── config/
│   ├── __init__.py
│   ├── sections.py                     # Detection/association/lifecycle/runtime typed sections
│   ├── schema.py                       # Raw SRConfig schema and strict structural validation
│   ├── resolved.py                     # ResolvedSRConfig, provenance, deterministic hash
│   ├── resolver.py                     # Layer resolution only
│   └── loader.py                       # Strict YAML loading and duplicate-key rejection
├── domain/
│   ├── __init__.py
│   ├── errors.py                       # ContractValidationError ownership
│   ├── identity.py                     # Deterministic identity/hash/time canonicalization
│   ├── bars.py                         # ClosedBar and bar/state key contracts
│   ├── geometry.py                     # Zone geometry/value objects
│   ├── candidates.py                   # Candidate contracts
│   ├── zones.py                        # Zone definition/runtime/record/status contracts
│   ├── events.py                       # Event types and event contracts
│   ├── state.py                        # SRState
│   ├── snapshots.py                    # SRSnapshot
│   ├── factory.py                      # Pure creation factories
│   └── contracts.py                    # Compatibility re-export facade only
├── detection/
│   ├── __init__.py
│   └── pivots.py
├── association/
│   ├── __init__.py
│   └── matcher.py
├── lifecycle/
│   ├── __init__.py
│   ├── engine.py                       # Thin deterministic orchestration
│   ├── validation.py                   # Step precondition/state validation
│   ├── transitions.py                  # Pure zone transition functions
│   ├── creation.py                     # Pure candidate-to-zone creation
│   └── rules.py
├── replay/
│   ├── __init__.py
│   ├── runner.py
│   └── checkpoint.py                   # Only if replay ownership justifies extraction
├── evaluation/
│   ├── __init__.py
│   ├── contracts.py                    # Compatibility facade if split
│   ├── observations.py
│   ├── outcomes.py
│   ├── diagnostics.py
│   ├── trace_builder.py
│   └── identity.py
├── serialization/
│   ├── __init__.py
│   └── state_codec.py
├── research/
│   ├── __init__.py
│   ├── config/
│   │   ├── __init__.py
│   │   ├── strict_yaml.py               # Shared strict recursive duplicate-key loader
│   │   ├── primitives.py                # Strict string/int/float/hash/commit/path/time parsers
│   │   └── identities.py                # Typed frozen identity/config references
│   ├── artifacts/
│   │   ├── __init__.py
│   │   ├── canonical_json.py            # Canonical encoding and byte hashing
│   │   ├── path_safety.py               # lstat path-component and regular-file guards
│   │   ├── manifest.py                  # Typed member identity and manifest validation
│   │   ├── publisher.py                 # Atomic deterministic publication
│   │   └── validator.py                 # Shared bundle/member validation primitives
│   ├── provenance/
│   │   ├── __init__.py
│   │   └── repository.py                # Repository commit and clean identity helpers
│   ├── source/
│   │   ├── __init__.py
│   │   ├── contracts.py                 # SourceBar/source identity/frozen-source contracts
│   │   └── frozen.py                    # Network-free frozen source loading/verification
│   ├── windows/
│   │   ├── __init__.py
│   │   └── folds.py                     # Neutral fold/window contracts and validation
│   ├── replay/
│   │   ├── __init__.py
│   │   ├── candidates.py                # Neutral candidate replay contracts/helpers
│   │   └── parity.py                    # State/snapshot/event/checkpoint parity contracts
│   ├── metrics/
│   │   ├── __init__.py
│   │   └── first_touch.py               # Neutral FirstTouchOutcome ownership
│   └── studies/
│       ├── baseline_trial/
│       ├── atr_calibration/
│       ├── cohort_readiness/
│       ├── geometry_sensitivity/
│       ├── baseline_adequacy/
│       ├── context_audit/
│       ├── lifecycle_utility/
│       └── candidate_reinforcement_audit/
├── scripts/
│   ├── __init__.py
│   └── <historical study packages>      # Temporary compatibility imports/CLI shims only
├── tools/
│   └── zone_viewer/
└── docs/
    ├── ARCHITECTURE.md
    ├── CONFIGURATION.md
    ├── RESEARCH_BOUNDARIES.md
    └── LEGACY_SR_STATUS.md
```

### Structure constraints

- Do not create generic dumping-ground modules named `utils.py`, `common.py`, `helpers.py`, or `misc.py`.
- Each shared module must have one named ownership concern.
- `__init__.py` files expose stable APIs only and must not perform I/O or import CLI modules.
- Compatibility facades contain imports, `__all__`, and explanatory comments only; they must not contain business logic.
- New core modules should ordinarily remain below approximately 400 lines.
- Any touched production module above 500 lines requires explicit cohesion justification in the coder handoff.
- Splitting solely to satisfy a line count is forbidden.

## 5. Ownership Map for Existing Cross-Study Types

Move ownership from historical studies to neutral packages as follows:

| Existing concern | Current ownership pattern | Canonical target |
|---|---|---|
| `SourceBar` and source identity | `baseline_trial`, then imported by later studies | `research/source/contracts.py` |
| `CohortFold` / fold definitions | `cohort_readiness`, then imported by unrelated studies | `research/windows/folds.py` |
| `CandidateReplay` | `atr_calibration`, then imported by adequacy and cohort studies | `research/replay/candidates.py` |
| `FirstTouchOutcome` | `atr_calibration.metrics`, then imported by later studies | `research/metrics/first_touch.py` |
| repository commit lookup | repeated in study runners | `research/provenance/repository.py` |
| strict scalar/path/hash parsing | repeated in study configs | `research/config/primitives.py` |
| recursive duplicate-key YAML loading | repeated or partially implemented | `research/config/strict_yaml.py` |
| canonical JSON and byte hashing | repeated in artifact modules | `research/artifacts/canonical_json.py` |
| atomic publication | repeated in artifact/source modules | `research/artifacts/publisher.py` |
| manifest/member validation | repeated in artifact modules | `research/artifacts/manifest.py` and `validator.py` |
| symlink/non-regular path rejection | hardened in V1.12 but study-owned | `research/artifacts/path_safety.py` |
| replay parity/digest comparison | repeated across later studies | `research/replay/parity.py` |

Historical import paths must continue to re-export these symbols until all active callers and public tests are migrated.

## 6. Dependency Rules

The allowed dependency direction is:

```text
config/domain
    ↓
detection + association + lifecycle
    ↓
replay + serialization
    ↓
evaluation
    ↓
research shared infrastructure
    ↓
research studies
    ↓
CLI and viewer tooling
```

More precisely:

1. `domain` must not import detection, association, lifecycle, replay, evaluation, research, scripts, or tools.
2. `config` may import only domain identity/error primitives.
3. `detection` and `association` may import domain and config contracts.
4. `lifecycle` may import domain, config, detection, and association.
5. `replay` may import public lifecycle/core contracts.
6. `evaluation` may import core and replay contracts, but not study implementations.
7. `research` may import public core/evaluation APIs.
8. `research/studies/<study>` may not import another sibling study.
9. `scripts` may import canonical research study CLIs only.
10. `tools` may consume public core/research payload APIs but must not be imported by core or research computation.
11. No active package may import `libs.sr`.
12. No research package may import provider, Binance, requests, sockets, database, sealed/holdout, or viewer code unless a separately approved study explicitly authorizes it. This refactor authorizes none.

Add AST-based import-boundary tests under:

`tests/models/sr/architecture/`

Required checks:

- no active import of `libs.sr`;
- no core-to-research import;
- no sibling-study import;
- no study import of forbidden provider/network/database/holdout/viewer modules;
- compatibility wrappers contain no executable logic beyond imports and `__all__`;
- no import cycles among active SR packages.

## 7. Configuration and Hyperparameter Policy

### 7.1 What must be config-driven

The following must never be embedded as operational literals in model or study logic:

- pivot spans and lookbacks;
- ATR method, period, seed, smoothing, and warm-up policy;
- zone width, merge distance, touch tolerance, break buffer;
- confirmation counts and lifecycle ages;
- capacity limits;
- enabled detectors or future detector-specific parameters;
- evaluation horizons and observation windows;
- folds, date ranges, warm-up boundaries, and common start indices;
- gate thresholds and minimum sample requirements;
- asset, venue, timeframe, source, or data-grid selection;
- output stage and artifact output root;
- upstream bundle IDs, hashes, byte sizes, config hashes, and implementation commits;
- outcome definitions, null/control parameters, metric thresholds, and tie-breaking policy when configurable;
- any value whose change can alter candidates, zones, events, metrics, dispositions, or artifact identity.

### 7.2 What may remain in code

The following may remain code-owned when they are true invariants rather than selected parameters:

- enum definitions and supported enum members;
- schema field names;
- cryptographic digest algorithms and canonical serialization rules;
- validation error messages;
- exact finite-number and type-safety rules;
- deterministic ordering keys mandated by the contract;
- domain invariants such as terminal statuses;
- mathematical identities such as zero/one used by an algorithm, when not a tunable threshold;
- protocol version parsers and migration logic;
- safe file-system rules.

When uncertain, treat the value as configuration and document its ownership.

### 7.3 Core model configuration location

Model-output-affecting parameters belong in:

`configs/sr.yaml`

The current file must remain byte-identical during this refactor.

Do not populate new asset overrides or tune existing values.

### 7.4 Input/transformation configuration location

Upstream indicator or input transformation policy belongs in:

`configs/sr_inputs.yaml`

Examples include ATR implementation, period, seed, or future causally computed input transformations.

Do not duplicate these values inside trial YAML unless the historical frozen contract already contains them. Future studies should reference and hash the input config instead of copying it.

### 7.5 Research protocol configuration location

Study-specific protocol belongs in:

`configs/sr_trials/*.yaml`

This includes source identities, folds, windows, gates, artifact stage, output root, and upstream evidence references.

Historical trial YAML files must not be changed because their bytes and hashes are evidence-bound.

Future study schemas should reference:

- the SR config path and expected file hash;
- the resolved SR config hash for the selected asset/timeframe;
- the input config path and expected file hash;
- upstream artifact identities.

Future studies should not copy resolved SR parameter values into a second `protocol.sr` block unless a separately approved frozen protocol explicitly requires duplication.

### 7.6 Configuration resolution hierarchy

Add support for four deterministic model-config layers:

1. global defaults;
2. timeframe override;
3. asset-wide defaults;
4. exact asset/timeframe override.

Precedence, lowest to highest:

```text
defaults
→ timeframes.<timeframe>
→ assets.<asset>.defaults
→ assets.<asset>.timeframes.<timeframe>
```

Illustrative schema:

```yaml
version: "1"

defaults:
  detection:
    pivot_span_bars: 5
    zone_half_width_atr: 0.25
  association:
    merge_distance_atr: 0.50
  lifecycle:
    touch_tolerance_atr: 0.25
    break_buffer_atr: 0.25
    break_confirm_closes: 2
    max_age_bars: 50
  runtime:
    max_active_zones: 8

timeframes:
  1h:
    lifecycle:
      max_age_bars: 120

assets:
  BTCUSDT:
    defaults:
      association:
        merge_distance_atr: 0.40
    timeframes:
      1h:
        detection:
          pivot_span_bars: 7
```

This sample is documentation/test-fixture material only. Do not add these example overrides to the live config.

### 7.7 Backward compatibility for the new asset layer

Adding `assets.<asset>.defaults` is an additive resolver capability only.

Required guarantees:

- existing `configs/sr.yaml` remains byte-identical;
- all existing raw configs remain valid;
- all existing resolved values remain identical;
- all existing field provenance remains identical when no asset-wide layer is present;
- all existing resolved config hashes remain identical;
- the new provenance source is exactly `asset:<asset>`;
- exact asset/timeframe provenance remains `asset_timeframe:<asset>:<timeframe>`;
- unknown keys continue to fail closed.

### 7.8 No implicit or call-time tuning

Model parameters must not have silent runtime defaults in engine methods, detector functions, matchers, or study runners.

Do not add generic `**kwargs`, arbitrary dict overlays, environment-variable overrides, command-line model overrides, or call-time parameter mutation.

A fully resolved, immutable typed config must enter the model boundary.

CLIs may select a config file, repository root, and explicit implementation commit. They must not override model parameters individually.

### 7.9 Provenance and hashing

Every resolved field must retain its exact source layer.

The resolved config hash must bind:

- schema version;
- asset;
- timeframe;
- every resolved model parameter;
- sorted field-level provenance.

Resolution must be deterministic across mapping insertion order and repeated process execution.

## 8. Detailed Implementation Phases

Each phase must be separately commit-worthy and independently testable. Do not perform the entire refactor as one bulk move.

### Phase R0 — Baseline lock and architecture inventory

Tasks:

1. Confirm branch and exact base commit.
2. Record clean working-tree status, excluding the authorization plan commit.
3. Run and record the active SR full suite before edits.
4. Re-run the V1.12 focused suite.
5. Semantically validate the approved V1.12 bundle without republishing it.
6. Record the approved replay digests and artifact member hashes.
7. Produce a dependency inventory covering:
   - public exports;
   - imports from `libs.models.sr` outside the package;
   - all sibling-study imports;
   - repeated artifact/config/provenance helper implementations;
   - files above 500 lines;
   - all model-output-affecting literals found outside typed config parsing/tests.
8. Use codebase-memory graph tools before moving or splitting symbols.

Deliverable:

`plans/sr-pre-v2-refactor-baseline-inventory-v1.md`

Do not edit implementation code in the R0 commit.

### Phase R1 — Configuration ownership and resolver modularization

Tasks:

1. Split `config/models.py` by ownership into typed sections, raw schema, and resolved config modules.
2. Keep existing import paths working through explicit re-exports.
3. Move strict YAML loading into `config/loader.py` or a shared research strict-YAML layer, with one canonical implementation.
4. Add the inert asset-wide default layer.
5. Extend field provenance validation with `asset:<asset>`.
6. Add exact precedence, unknown-key, duplicate-key, non-finite, boolean-as-integer, immutability, insertion-order, and hash determinism tests.
7. Add a regression fixture proving existing resolved config payloads and hashes are unchanged.
8. Do not modify `configs/sr.yaml` or historical trial YAML.

Phase gate:

- all existing config tests pass;
- new four-layer precedence tests pass;
- canonical V1 replay remains identical.

### Phase R2 — Shared research infrastructure

Create neutral shared modules for:

- strict parsing primitives;
- canonical JSON and hashing;
- file/path safety;
- atomic bundle publication;
- manifest/member contracts;
- Git provenance;
- frozen source contracts/loading;
- fold/window contracts;
- candidate replay contracts;
- first-touch outcome contracts;
- replay parity.

Rules:

1. Extract exact existing behavior before improving APIs.
2. Preserve byte-level artifact serialization.
3. Preserve V1.12 symlink and non-regular file defenses exactly or strengthen them without changing valid artifact bytes.
4. Add focused tests around the shared implementation before migrating studies.
5. No study migration in the first R2 commit unless needed to prove one shared module.
6. Use explicit module names; no generic utility package.

Phase gate:

- shared primitives have direct focused tests;
- V1.12 artifact validation passes using shared path-safety primitives;
- no valid artifact byte changes.

### Phase R3 — Migrate studies in topological order

Migrate one study at a time:

1. `baseline_trial`;
2. `atr_calibration`;
3. `cohort_readiness`;
4. `geometry_sensitivity`;
5. `baseline_adequacy`;
6. `context_audit`;
7. `lifecycle_utility`;
8. `candidate_reinforcement_audit`.

For each study:

1. Move canonical implementation to `research/studies/<study>`.
2. Replace sibling-study imports with neutral shared contracts/services.
3. Leave old `scripts/<study>` import and CLI compatibility wrappers.
4. Preserve module-level public names used by tests and CLIs.
5. Run that study's focused tests before moving to the next study.
6. Run the complete active SR suite at the end of each logical migration group.
7. Do not rewrite the study's algorithm or config schema during movement.
8. Do not modify historical configs or generated evidence.

Suggested migration commits:

- R3a: baseline trial + ATR calibration;
- R3b: cohort readiness + geometry sensitivity;
- R3c: baseline adequacy + context audit;
- R3d: lifecycle utility + candidate reinforcement audit.

Phase gate:

- canonical study code has zero sibling-study imports;
- historical CLI module paths still execute;
- public tests continue to import successfully;
- deterministic study outputs remain identical.

### Phase R4 — Core domain and lifecycle cohesion

Tasks:

1. Split `domain/contracts.py` by actual contract ownership.
2. Preserve `domain/contracts.py` as a compatibility re-export facade.
3. Move `ContractValidationError` to one canonical module and re-export it where required.
4. Split evaluation contracts only where ownership is clear.
5. Extract lifecycle step validation from `SREngine.step` into pure validation functions.
6. Extract zone transition and candidate-to-zone construction into pure functions.
7. Keep `SREngine.step` as the deterministic orchestrator.
8. Do not introduce abstract base classes, plugin systems, dependency injection, detector registries, or V2 extension points.
9. Preserve exact ordering and exception behavior for all valid inputs. Existing invalid-input error semantics should remain unless a test proves an inconsistency that requires architect escalation.

Phase gate:

- core public imports remain valid;
- engine/replay digests remain exact;
- no core import cycles;
- lifecycle focused tests remain exact.

### Phase R5 — Boundaries, documentation, and cleanup

Tasks:

1. Add architecture, configuration, research-boundary, and legacy-status documentation.
2. Add AST import-boundary tests.
3. Confirm `src/libs/sr` has zero active references.
4. Remove temporary duplicated implementations after every caller uses the canonical shared module.
5. Keep compatibility facades required by public imports.
6. Add a documented removal plan for compatibility facades, but do not remove them in this refactor.
7. Re-index codebase-memory after moves.
8. Run scope/diff impact checks.

Phase gate:

- all acceptance criteria below pass;
- coder-to-review handoff is complete;
- no merge or V2 work is performed.

## 9. Agent Execution Guidelines

### 9.1 Role and scope

The Codex agent acts as a bounded refactoring coder, not a model researcher or optimizer.

It may restructure, extract, move, re-export, and add behavior-preservation tests.

It may not invent SR V2 architecture, add detectors, tune parameters, add features, or reinterpret negative V1 evidence.

### 9.2 Codebase-memory workflow

Before modifying any existing class, function, method, or public export:

1. locate it with `search_graph` or `search_code`;
2. trace inbound and outbound impact;
3. identify direct callers and imports;
4. record high/critical impact before editing;
5. after each phase, run `detect_changes` and inspect scope.

Re-index after large file moves.

### 9.3 One writer

Use only one workspace-writing agent in this checkout.

Read-only review/research agents may run separately, but no parallel writer may modify the same branch or checkout.

### 9.4 Small commits

Use small, ordered commits. A recommended sequence is:

1. approved architecture handoff;
2. R0 baseline inventory;
3. R1 config split and additive asset layer;
4. R2 shared research foundations;
5. R3a–R3d study migrations;
6. R4 core cohesion;
7. R5 boundaries/docs/cleanup;
8. coder-to-review handoff.

Do not combine formatter noise, unrelated cleanup, or legacy SR edits.

### 9.5 Compatibility first

Before moving a public symbol:

1. add the canonical target implementation;
2. add compatibility re-export;
3. migrate internal callers;
4. run focused tests;
5. remove duplicate implementation only after all callers are migrated.

Do not use naive project-wide search-and-replace for symbol moves.

### 9.6 No opportunistic fixes

When an unrelated defect is found:

- document it in the coder handoff;
- do not fix it unless it blocks the refactor;
- escalate architecture ambiguity rather than silently broadening scope.

### 9.7 No artifact mutation

Do not regenerate, republish, normalize, reformat, move, delete, or stage historical research artifacts.

Validation should read the approved bundles in place.

Generated temporary outputs, when unavoidable for byte comparison, must remain untracked and be explicitly listed.

### 9.8 No broad formatting

Run Ruff only on touched active SR and test paths during development, then run the requested final checks.

Do not format untouched legacy files or historical configs.

### 9.9 Fail closed

Stop and return `Blocked` if:

- the base commit differs;
- the approved bundle fails semantic validation before edits;
- existing replay digests cannot be reproduced;
- a required public import cannot be preserved without semantic change;
- artifact bytes change for a valid historical payload;
- the refactor requires a model or study contract redesign;
- a high/critical blast radius is discovered beyond the approved scope;
- user-owned worktree state would be overwritten.

## 10. Acceptance Criteria

All criteria are mandatory unless explicitly marked advisory.

### 10.1 Repository and scope

1. Implementation branch is based on exact commit `2ae7e0812a937c63663d528d7fe2465319818123`.
2. No merge commit is created.
3. `src/libs/sr` is not modified except, if strictly needed, one isolated legacy-status pointer; preference is no changes at all.
4. Historical trial configs and artifacts remain byte-identical.
5. No application, provider, database, production configuration, sealed source, or holdout code is changed.
6. Final diff contains only active SR refactor code, tests, docs, and handoffs.

### 10.2 Architecture

7. `src/libs/models/sr` is documented and enforced as the canonical active package.
8. Active code contains zero imports from `libs.sr`.
9. Core code contains zero imports from `libs.models.sr.research` or `libs.models.sr.scripts`.
10. Canonical study implementations contain zero sibling-study imports.
11. Research studies use neutral shared ownership for source bars, folds, candidate replay, first-touch outcomes, artifact infrastructure, provenance, and parity.
12. No new circular dependency exists.
13. Compatibility facades contain no business logic.
14. No generic dumping-ground utility module is introduced.
15. Public imports currently exercised by the 628-test suite remain valid.

### 10.3 Configuration and hardcoding

16. Existing `configs/sr.yaml` remains byte-identical and retains its existing file hash.
17. Existing `configs/sr_inputs.yaml` remains byte-identical and retains its existing file hash.
18. Existing historical trial YAML files remain byte-identical.
19. Existing configs resolve to identical typed values, field provenance, and resolved config hashes.
20. The resolver supports the deterministic four-layer hierarchy:
    `defaults → timeframe → asset defaults → asset/timeframe`.
21. New asset-wide provenance is exactly `asset:<asset>`.
22. Unknown keys, missing required keys, duplicate YAML keys, aliases where forbidden, non-finite numerics, booleans-as-integers, unsafe paths, and unsupported enums fail closed.
23. All model-output-affecting values are consumed from immutable typed configuration rather than duplicated operational literals.
24. All research protocol selections, thresholds, identities, folds, and paths are read from typed trial configuration rather than duplicated study constants.
25. Code-owned constants are limited to true invariants, enum definitions, schemas, canonicalization, and validation rules.
26. No call-time model overrides, environment-variable model overrides, or arbitrary dict overlays are introduced.
27. Resolved configuration and artifact hashes are deterministic across repeated runs and mapping insertion order.

### 10.4 Behavior and determinism

28. Candidate count and canonical ordering remain unchanged on the approved V1.12 replay.
29. Zone IDs, geometry, statuses, and terminal state remain unchanged.
30. Event order and payload remain unchanged.
31. Checkpoint and uninterrupted replay remain equivalent.
32. Canonical V1 replay remains equivalent.
33. Approved V1.12 state digest remains:
    `8333187c131b93fc70aba102209d336ac4885afbaa92224d75a7d64e275443e4`.
34. Approved V1.12 snapshot digest remains:
    `2b2465848b0816d0e120cc8e21fc0fdb12524cebbc55d54f8bfc0a79ce91ebe2`.
35. Approved V1.12 event digest remains:
    `028c9cf94ff80357ddbedbd86e8289b04af844454fd630463abc145931773d25`.
36. Approved V1.12 candidate digest remains:
    `1d50f701c0cb4acafc2110269bbe327bf386795cbef985331c23dc5414383ea4`.
37. Accounting remains exactly:
    - 65 candidates;
    - 50 created zones;
    - 15 eligible matches;
    - 13 unique reinforced zones.
38. Disposition remains exactly `INSUFFICIENT_REINFORCEMENT_EVIDENCE`.

### 10.5 Artifact safety and identity

39. Approved V1.12 bundle ID remains:
    `fd3eaf4cb58a23ee47c0f8645a3d4affd09ef05bf3cafb74831621826a58c206`.
40. Approved audit ID remains:
    `cd452938e2befc66f0d2a4e12d79083b88cf6e03a3124180c356d56a6f2b8adb`.
41. Existing manifest and audit member bytes/hashes remain unchanged.
42. Bundle and parent-directory symlinks remain rejected before resolution.
43. Member symlinks and non-regular files remain rejected during validation and publication.
44. Shared artifact infrastructure preserves atomic deterministic publication and semantic revalidation.
45. No historical artifact is republished as part of acceptance.

### 10.6 Tests and quality

46. The pre-refactor full active SR suite result is recorded.
47. The post-refactor full active SR suite has at least 628 passing tests, with no removed or skipped existing tests.
48. The V1.12 focused suite retains all 49 existing passing tests before new tests are counted.
49. New tests cover:
    - import boundaries;
    - compatibility imports;
    - sibling-study isolation;
    - four-layer config precedence;
    - field provenance;
    - config/hash backward compatibility;
    - canonical JSON bytes;
    - path component and regular-file safety;
    - publication/validation equivalence;
    - replay digest equivalence.
50. Ruff passes on all touched active SR and test paths.
51. Python compilation passes for all touched active SR packages.
52. `git diff --check` passes.
53. Codebase-memory final scope detection reports only expected symbols/files, with no unresolved high/critical risk.
54. The complete active SR suite passes twice from a clean process if any module moves or compatibility imports could be order-sensitive.

### 10.7 Documentation and handoff

55. Architecture documentation names every top-level package owner and dependency direction.
56. Configuration documentation defines parameter categories, location, precedence, provenance, and no-hardcoding rules.
57. Research-boundary documentation defines allowed imports and study isolation.
58. Legacy documentation clearly states that `src/libs/sr` is inactive and must not be reused without separate architecture approval.
59. The coder-to-review handoff lists:
    - exact commits;
    - file moves and compatibility facades;
    - extracted shared ownership;
    - config behavior proof;
    - replay/artifact equivalence proof;
    - test commands and results;
    - remaining compatibility cleanup deferred to a future phase.

## 11. Validation Checklist and Commands

Use the local virtual environment and `PYTHONPATH=src`.

Baseline and final active SR suite:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/models/sr
```

V1.12 focused suite:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/models/sr/scripts/candidate_reinforcement_audit
```

New architecture/config/shared-infrastructure tests:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/models/sr/architecture \
  tests/models/sr/config \
  tests/models/sr/research
```

Ruff, using the installed project/user binary:

```bash
ruff check src/libs/models/sr tests/models/sr
```

Compilation:

```bash
PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/sr
```

Diff validation:

```bash
git diff --check
```

Run the existing V1.12 semantic validator against the exact approved bundle and bound implementation commit. If canonical CLI paths move, preserve the historical command through a compatibility shim and also test the new canonical command.

Do not evaluate into the approved output directory. No provider call is allowed.

## 12. Explicit Non-Goals

This refactor does not authorize:

- SR V2 planning or implementation;
- reinforcement-confirmed zones;
- additional detectors or kernels;
- scoring, weighting, confidence, ranking, or ensemble logic;
- lifecycle feature changes;
- parameter search, optimization, or tuning;
- asset-specific parameter values;
- timeframe-specific parameter values in the live config;
- new data, source refresh, or provider calls;
- holdout or sealed evidence access;
- database, API, viewer, sidecar, or production integration changes;
- deletion or revival of `src/libs/sr`;
- artifact schema upgrades;
- breaking public imports;
- removal of compatibility facades;
- broad repo cleanup.

## 13. Required Coder-to-Review Output

After implementation, write:

`plans/coder-to-review-sr-pre-v2-modular-refactor-v1.md`

The handoff must include:

1. exact branch, base, authorization, and implementation commits;
2. phase-by-phase commit list;
3. before/after package map;
4. every moved canonical symbol and old compatibility path;
5. proof that no sibling-study implementation imports remain;
6. proof that no active `libs.sr` import remains;
7. config precedence/provenance/hash results;
8. hardcoding inventory and disposition for every remaining model/protocol literal;
9. replay digest comparison;
10. V1.12 bundle/member semantic validation results;
11. focused and full test counts;
12. Ruff, compile, diff, and codebase-memory results;
13. generated untracked files, if any;
14. any deferred compatibility-facade removal work;
15. an explicit statement that no V2 model work or tuning was performed.

## 14. Approval Boundary

A successful refactor makes the codebase structurally ready for a separate SR V2 research and architecture phase.

It does not itself authorize V2.

After independent review and final approval of this refactor, the next stage is:

`quant-research → quant-architect → SR V2 coder handoff`
