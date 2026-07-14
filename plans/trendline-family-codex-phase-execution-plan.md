# Trendline Family Model — Codex Phase Execution Plan

Date: 2026-07-11
Status: Ready for staged implementation
Primary architecture source: `plans/trendline-family-model-architecture-plan.md`
Canonical new package: `src/libs/models/trendline_family`
Canonical config: `configs/trendline_family.yaml`

## 1. Purpose

This document is the execution contract for a Codex implementation agent.

The model must be implemented one phase at a time. The agent must stop after every phase and return evidence for architecture review before proceeding.

Do not execute multiple phases in one change, even when later work appears straightforward.

The required loop is:

```text
architecture plan
    -> one approved phase handoff
    -> Codex implementation
    -> tests and evidence
    -> architecture/review pass
    -> corrections if required
    -> explicit approval
    -> next phase
```

This staged loop is intended to catch contract drift, config drift, causality errors, unwanted coupling, and semantic changes before later phases build on them.

---

## 2. Global Non-Negotiable Rules

These rules apply to every phase.

### 2.1 New code ownership

The new runtime model is self-owned under:

```text
src/libs/models/trendline_family
```

It must not runtime-import from:

```text
src/libs/trendlines
src/libs/models/trendlines_old
app.trendlines
```

The existing trendline implementations may be inspected as offline references. When an algorithm is selected for reuse, copy only the required logic into the new package, adapt it to the new contracts, remove old-package imports, and maintain it as new canonical code.

No wrapper, compatibility bridge, dynamic import, conditional import, or fallback runtime call to the old packages is allowed.

### 2.2 Old family state is different from old code

Previously generated `TrendlineFamilySnapshot` state is an intentional runtime input to the next bar-close update.

This does not permit importing old trendline implementation code.

```text
previous family state  -> required runtime prior
old trendline code      -> reference only
```

### 2.3 Configuration ownership

Runtime modules must not read YAML directly.

Required flow:

```text
configs/trendline_family.yaml
    -> config_loader
    -> config_resolver
    -> immutable ResolvedTrendlineFamilyConfig
    -> runtime component constructor/API
```

Config precedence:

```text
schema fallback
< YAML defaults
< generic timeframe override
< asset-wide override
< asset + timeframe override
< explicit runtime/research override
```

Unknown keys must fail closed unless the architecture review explicitly approves a compatibility mode.

Every snapshot and transition must eventually carry:

```text
model_version
config_version
resolved_config_hash
```

### 2.4 Causality

- Structural state updates occur only on confirmed bar close.
- Pivots cannot become available before their confirmation time.
- No incomplete higher-timeframe candle may enter confirmed MTF state.
- Evaluation outcomes cannot enter runtime features.
- Previous-history queries must exclude the current snapshot.

### 2.5 Geometry semantics

- A trendline remains an exact straight line.
- Interaction zones are separate derived objects.
- Estimation uncertainty is separate from interaction tolerance.
- Family corridors are created from multiple exact rails and are not uncertainty bands.
- Geometry evidence, structural interpretation, and trade policy remain separate.

### 2.6 Implementation restraint

Do not add abstractions, dependencies, plugins, persistence backends, asynchronous infrastructure, databases, learned models, or general market-geometry concepts before the phase that owns them.

Prefer a small explicit implementation over speculative extensibility.

### 2.7 Tests

Use:

```text
PYTHONPATH=src .venv/bin/python -m pytest ...
```

Every optimizable/configurable parameter added after Phase A requires a controlled parameter-effect test at the phase that begins using it.

### 2.8 Existing repository changes

The repository already contains unrelated dirty and untracked work. Do not modify, delete, format, stage, or claim ownership of unrelated files.

### 2.9 Stop rule

After completing the requested phase:

- run the phase test suite,
- inspect the diff,
- prepare the mandatory review package,
- stop.

Do not begin the next phase without explicit approval.

---

## 3. Mandatory Codex Review Package

At the end of every phase, Codex must return the following sections.

### 3.1 Work completed

List each implemented requirement and the corresponding files/symbols.

### 3.2 Files changed

Separate:

```text
new files
modified files
deleted files
```

Deletion should normally be empty in early phases.

### 3.3 Architecture decisions made

List any decision that was not explicitly fixed by the handoff.

Do not hide assumptions inside code.

### 3.4 Config impact

Report:

- fields added or removed,
- default values,
- ownership stage,
- override scope,
- whether a parameter-effect test exists.

### 3.5 Tests and commands

Give exact commands and result counts.

### 3.6 Architecture drift checklist

Answer each item explicitly:

```text
[ ] No runtime import from old trendline packages
[ ] No YAML read outside config_loader/config_resolver
[ ] No incomplete-bar/future-data use
[ ] Exact line and interaction zone remain separate
[ ] Stable IDs are deterministic
[ ] Geometry is separated from policy
[ ] No next-phase functionality was introduced
[ ] No unrelated files were changed
```

### 3.7 Known gaps and risks

List anything incomplete, weakly tested, ambiguous, or intentionally deferred.

### 3.8 Next recommended phase

Name only the next phase. Do not implement it.

---

## 4. Pre-Implementation Decisions Now Locked

No further broad design workshop is required before Phase A.

The following defaults are approved for initial implementation.

| Decision | Locked choice |
|---|---|
| Package | `libs.models.trendline_family` |
| Config file | `configs/trendline_family.yaml` |
| Config resolution | fallback → defaults → timeframe → asset → asset/timeframe → runtime override |
| Schema behavior | unknown keys fail closed |
| State update | confirmed bar close only |
| First repository | in-memory, deterministic serialization |
| Geometry time basis | timezone-aware UTC timestamps |
| IDs | deterministic content-derived UUID5 or stable hash; exact algorithm documented in Phase A |
| First pivot provider | causal fractal implementation owned by new package |
| First fitter | copied/refactored pathfinding implementation owned by new package |
| Initial association | deterministic greedy matching |
| Initial tracking scope | single asset + single timeframe per update |
| MTF | deferred until single-timeframe replay is stable |
| Existing RegimeV2 adapter | remains active until shadow/OOS promotion |

Minor implementation choices such as enum serialization or canonical JSON formatting may be made in Phase A, but must be documented in its review package.

---

# Phase A — Foundation, Contracts, and Configuration

## A.1 Objective

Create the independent package foundation without candidate generation, fitting, matching, interaction classification, RegimeV2 integration, or MTF logic.

## A.2 Allowed production files

```text
src/libs/models/trendline_family/__init__.py
src/libs/models/trendline_family/contracts.py
src/libs/models/trendline_family/config.py
src/libs/models/trendline_family/config_loader.py
src/libs/models/trendline_family/config_resolver.py
src/libs/models/trendline_family/repository.py
configs/trendline_family.yaml
```

Allowed tests:

```text
tests/models/trendline_family/__init__.py
tests/models/trendline_family/test_contracts.py
tests/models/trendline_family/test_config_loader.py
tests/models/trendline_family/test_config_resolver.py
tests/models/trendline_family/test_repository.py
tests/models/trendline_family/test_import_boundaries.py
```

All phase tests must remain under the repository's top-level `tests/` tree so normal root `pytest` collection and CI include them.

## A.3 Required contracts

Define only the contracts needed to stabilize later work:

- `LineGeometry`
- `AnchorRef`
- `LineDiagnostics`
- `LineCandidate`
- `InteractionZone`
- `LineUncertainty`
- `FamilyLifecycleState`
- `FamilyRole`
- `TrendlineFamilyState`
- `FamilyTransitionType`
- `FamilyTransition`
- `TrendlineFamilySnapshot`
- `TrendlineFamilyOutput`

Fields should follow the architecture plan. Avoid adding speculative MTF, channel, horizontal-zone, scenario, or strategy fields.

## A.4 Serialization rules

Codex must define and test:

- UTC-aware datetime requirement,
- canonical ISO-8601 format,
- enum serialization,
- stable ordering for tuples/maps,
- canonical JSON representation,
- deterministic ID generation,
- deterministic config hash generation,
- round-trip behavior,
- rejection of non-finite values where unsafe.

## A.5 Config design

Create typed sections rather than one flat dataclass. Minimum sections:

```text
candidate
matching
lifecycle
interaction
ranking
repository
runtime
```

The YAML should remain small. Add only fields already required by the architecture plan.

The resolver must return an immutable resolved object plus field provenance sufficient to determine which layer supplied each final value.

## A.6 Repository

Implement an in-memory repository protocol and implementation supporting:

- load latest snapshot by asset/timeframe,
- save snapshot,
- reject obvious previous-snapshot/version mismatch,
- deterministic serialization round trip,
- isolation across asset/timeframe keys.

No database, Redis, filesystem persistence, or locking framework.

## A.7 Forbidden work

Do not implement:

- pivots,
- fitters,
- providers,
- matching,
- tracker update loop,
- interaction classification,
- features,
- RegimeV2 adapter,
- MTF,
- optimization.

## A.8 Exit gate

All must pass:

- exact timestamp-space line projection,
- timezone/UTC validation,
- deterministic ID tests,
- contract round trips,
- config precedence tests,
- field-provenance tests,
- unknown-key rejection,
- stable config hash,
- repository isolation and version checks,
- static import-boundary test proving no old trendline imports.

## A.9 Codex prompt

```text
Implement Phase A only from plans/trendline-family-codex-phase-execution-plan.md, using plans/trendline-family-model-architecture-plan.md as the semantic source.

Create the independent `src/libs/models/trendline_family` foundation, typed config loader/resolver, contracts, deterministic IDs/serialization, in-memory repository, YAML config, and Phase A tests.

Do not implement pivots, fitting, providers, tracking, interactions, RegimeV2 integration, MTF, or optimization. Do not import from `libs.trendlines`, `libs.models.trendlines_old`, or `app.trendlines`.

Run the Phase A tests and stop. Return the mandatory review package from Section 3 of the execution plan.
```

---

# Phase B — Native Candidate Generation

## B.1 Objective

Produce deterministic causal exact-line candidates using code owned entirely by the new package.

## B.2 Prerequisite

Phase A approved with no unresolved contract or config issues.

## B.3 Expected files

Production additions may include:

```text
src/libs/models/trendline_family/pivots.py
src/libs/models/trendline_family/fitting.py
src/libs/models/trendline_family/provider.py
src/libs/models/trendline_family/registry.py
```

Tests:

```text
tests/models/trendline_family/test_pivots.py
tests/models/trendline_family/test_fitting.py
tests/models/trendline_family/test_provider.py
tests/models/trendline_family/test_candidate_causality.py
tests/models/trendline_family/test_candidate_parity_fixtures.py
```

If files become genuinely crowded, `pivots/` or `fitting/` may become small subpackages, but Codex must justify that choice.

## B.4 Required work

- Implement causal fractal pivot extraction.
- Preserve pivot observation time separately from pivot confirmation time.
- Copy/refactor only the required pathfinding fitter logic into the new package.
- Remove all old package contracts and imports.
- Emit canonical `LineCandidate` directly.
- Map exact anchor provenance.
- Expose method-independent diagnostics.
- Implement provider protocol and simple registry.
- Support explicit invalid/empty/abstention results.
- Add frozen comparison fixtures where selected old behavior is useful as a benchmark.

Fixtures may contain data and expected outputs; runtime code must not import old implementations.

## B.5 Config ownership

Candidate and fitter parameters must be loaded through the resolved config.

Likely timeframe or asset/timeframe parameters:

- left/right fractal windows,
- minimum pivots,
- lookback bars,
- pathfinding pivot window,
- cut tolerance,
- refit mode if retained.

Every field introduced must have a parameter-effect test or remain non-optimizable operational metadata.

## B.6 Forbidden work

Do not implement:

- family association,
- lifecycle updates,
- interaction states,
- RegimeV2 integration,
- MTF,
- optimizer.

## B.7 Exit gate

- no old runtime imports,
- deterministic candidates for identical OHLCV/config,
- causal pivot confirmation,
- correct support/resistance semantics,
- exact UTC anchor timestamps,
- pathfinding behavior covered by controlled tests,
- every used config field changes its owned stage in a parameter-effect test,
- invalid input produces explicit abstention/error semantics.

## B.8 Codex prompt

```text
Implement Phase B only from plans/trendline-family-codex-phase-execution-plan.md after the approved Phase A contracts.

Add a self-owned causal fractal pivot implementation, copied/refactored pathfinding fitter, canonical candidate provider, registry and diagnostics under `src/libs/models/trendline_family`, with fixtures/tests under `tests/models/trendline_family`.

Do not runtime-import any existing trendline package. Do not implement matching, tracking, interactions, RegimeV2 integration, MTF, or optimization.

Run Phase A + Phase B tests and stop. Return the mandatory review package.
```

---

# Phase C — Single-Timeframe Family Tracker MVP

## C.1 Objective

Use previous family state as the prior for the next confirmed bar-close update and preserve stable family identity across observations.

## C.2 Expected files

```text
src/libs/models/trendline_family/matching.py
src/libs/models/trendline_family/tracker.py
src/libs/models/trendline_family/ranking.py
src/libs/models/trendline_family/api.py
```

Tests:

```text
tests/models/trendline_family/test_matching.py
tests/models/trendline_family/test_tracker_birth.py
tests/models/trendline_family/test_tracker_continuation.py
tests/models/trendline_family/test_tracker_lifecycle.py
tests/models/trendline_family/test_tracker_replay.py
tests/models/trendline_family/test_tracker_churn.py
```

## C.3 Required update loop

```text
load previous snapshot
-> project previous family geometry
-> generate fresh discovery candidates
-> group compatible current candidates
-> score candidate/family associations
-> deterministic greedy assignment
-> preserve matched IDs
-> birth unmatched eligible candidates
-> weaken/grace/dormant/expire unmatched families
-> reactivate eligible dormant families
-> rank active families
-> publish immutable snapshot and transitions
```

## C.4 Matching dimensions

Initial match score must use only documented, testable evidence:

- projected price distance normalized by ATR,
- normalized slope difference,
- anchor overlap,
- role compatibility,
- recency/lifecycle eligibility.

Do not introduce ML assignment or global optimization.

## C.5 Lifecycle scope

Implement:

```text
BIRTH
CONTINUE
STRENGTHEN
WEAKEN
DORMANT
REACTIVATE
EXPIRE
```

Do not implement split, merge, breakout, retest, or role reversal yet.

## C.6 Exit gate

- small candidate drift preserves ID,
- large incompatible drift births a new family,
- unmatched family follows grace → weaken → dormant → expire,
- dormant family can reactivate deterministically,
- same rolling bars produce identical snapshots/transitions,
- no future data,
- churn diagnostics are exposed,
- snapshot version lineage is enforced.

## C.7 Codex prompt

```text
Implement Phase C only from plans/trendline-family-codex-phase-execution-plan.md.

Build deterministic single-timeframe family matching, ranking, lifecycle, update API, immutable snapshots, transitions, and replay tests. Previously generated family state must act as the prior for the new confirmed bar close.

Implement only birth, continue, strengthen, weaken, dormant, reactivate, and expire. Do not add interaction events, role reversal, split/merge, MTF, RegimeV2 integration, or optimization.

Run all trendline-family tests and stop. Return the mandatory review package.
```

---

# Phase D — Interaction Zones and Basic Bar Evidence

## D.1 Objective

Derive a volatility-aware interaction zone around each exact representative line and classify current-bar evidence without changing line geometry.

## D.2 Expected files

```text
src/libs/models/trendline_family/interactions.py
src/libs/models/trendline_family/features.py
```

Tests:

```text
tests/models/trendline_family/test_interaction_zones.py
tests/models/trendline_family/test_interaction_evidence.py
tests/models/trendline_family/test_interaction_symmetry.py
tests/models/trendline_family/test_interaction_parameter_effects.py
```

## D.3 Required states

```text
FAR
APPROACHING
IN_ZONE
WICK_BREACH
BODY_BREACH
CLOSE_BEYOND
```

These are observations, not yet full multi-bar events.

## D.4 Required separation

Store separately:

- exact line center,
- interaction tolerance/zone,
- optional uncertainty diagnostics,
- wick penetration ATR,
- body penetration ATR,
- close penetration ATR.

Do not change the line to fit the current candle.

## D.5 Exit gate

- support/resistance symmetry,
- zone width config changes the classified stage on controlled inputs,
- tick-size floor and ATR behavior are documented,
- penetration evidence is auditable,
- existing tracker identity remains unchanged by visualization width.

## D.6 Codex prompt

```text
Implement Phase D only from plans/trendline-family-codex-phase-execution-plan.md.

Add derived interaction zones around exact family lines and basic confirmed-bar evidence states: FAR, APPROACHING, IN_ZONE, WICK_BREACH, BODY_BREACH, CLOSE_BEYOND. Keep exact line geometry, interaction tolerance, and uncertainty diagnostics separate.

Do not implement full breakout/retest state, role reversal, MTF, RegimeV2 integration, or optimization.

Run all trendline-family tests and stop. Return the mandatory review package.
```

---

# Phase E — Shadow RegimeV2 Integration

## E.1 Objective

Collect the new family-model features in shadow mode beside the existing trendline feature producer without changing active decisions.

## E.2 Expected files

```text
src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py
```

Additional integration/config wiring and tests may be added only where required.

## E.3 Required behavior

- New family model remains opt-in/shadow-only.
- Existing trendline feature producer remains unchanged and active.
- Load/save family snapshot state through the repository boundary.
- Emit compact family features and health diagnostics.
- Record model version and resolved config hash.
- Fail soft with explicit invalid/error fields.
- Do not affect final selection, probability, overlay, MoE, MTF, or execution decisions.

## E.4 Minimum feature groups

- validity/config identity,
- active/dormant counts,
- births/updates/dormancies/reactivations/expiries,
- churn,
- nearest support/resistance family,
- distances to exact line and interaction zone,
- family age/confidence/importance/relevance,
- basic interaction observations,
- ambiguity/abstention.

## E.5 Exit gate

- no active decision change,
- old and new features coexist,
- deterministic replay/live parity on controlled fixtures,
- shadow artifact exposes coverage/churn/error distributions,
- runtime latency and failure rate reported.

## E.6 Codex prompt

```text
Implement Phase E only from plans/trendline-family-codex-phase-execution-plan.md.

Add an opt-in shadow-only RegimeV2 `TrendlineFamilyFeatureProducer`, state loading/saving, compact features, config/model identity, fail-soft semantics, and integration tests. Keep the existing trendline feature path active and unchanged.

Do not feed new family features into promotion-sensitive decisions. Do not implement full event lifecycle, multi-rail families, MTF composition, or optimization.

Run targeted RegimeV2 + trendline-family tests and stop. Return the mandatory review package.
```

---

# Phase F — Full Interaction Event Lifecycle

## F.1 Objective

Convert per-bar evidence into persistent multi-bar interaction events while preserving family identity through break, retest, failure, and role reversal.

## F.2 Required event states

```text
FAR
APPROACHING
IN_ZONE
REJECTING
PRESSURING
WICK_BREACHED
BODY_BREACHED
BREAK_PENDING
BREAK_CONFIRMED
RETEST_PENDING
RETEST_SUCCESS
FAILED_BREAK
ROLE_REVERSED
```

## F.3 Required work

- persistent event IDs,
- confirmation-bar logic,
- pressure duration,
- maximum penetration,
- rejection recovery,
- retest window,
- failed-break detection,
- role reversal preserving the same family ID,
- compatibility mapping to simple breakout/breakdown/bounce labels.

## F.4 Exit gate

- deterministic event replay,
- role reversal does not create a new geometry identity,
- no one-close-only primary breakout path,
- state transition table has exhaustive tests,
- event outcomes used for evaluation remain separate from runtime evidence.

## F.5 Codex prompt

```text
Implement Phase F only from plans/trendline-family-codex-phase-execution-plan.md.

Extend basic interaction observations into deterministic multi-bar event state with event IDs, confirmation, pressure, breakout/breakdown, retest, failed break, and role reversal. Preserve family identity when role changes.

Do not implement multi-rail families, MTF composition, or optimizers.

Run all relevant tests and stop. Return the mandatory review package.
```

---

# Phase G — Multi-Rail Trendline Families

## G.1 Objective

Represent related approximately parallel exact lines as a coherent family with explicit rails and a family corridor.

## G.2 Required concepts

- representative slope,
- exact member rails,
- stable rail/member IDs,
- rail offsets in ATR,
- lower/median/upper or ordered rail semantics,
- spacing stability,
- family corridor,
- current rail position,
- candidate family confidence.

## G.3 Required separation

```text
family corridor       != interaction zone
interaction zone      != uncertainty envelope
uncertainty envelope  != exact line
```

## G.4 Deferred inside this phase unless essential

- complex split/merge graph optimization,
- learned clustering,
- horizontal zones,
- projection scenarios.

Simple deterministic lineage may be added only when required by tests.

## G.5 Exit gate

- repeated parallel lines group correctly,
- unrelated lines do not over-merge,
- singleton family remains valid,
- rails remain exact lines,
- corridor and interaction-zone semantics are tested independently,
- family continuity is stable across bars.

## G.6 Codex prompt

```text
Implement Phase G only from plans/trendline-family-codex-phase-execution-plan.md.

Add deterministic multi-rail trendline-family semantics: exact member rails, representative slope, ordered rail offsets, spacing diagnostics, family corridor, and continuity tests. Keep corridor, interaction zone, and uncertainty separate.

Do not implement MTF composition, horizontal zones, learned clustering, or optimization.

Run all relevant tests and stop. Return the mandatory review package.
```

---

# Phase H — Asynchronous MTF Composition

## H.1 Objective

Project latest confirmed per-timeframe family snapshots to one common decision timestamp and expose agreement, conflict, nesting, intersection, and confluence without averaging everything into one synthetic line.

## H.2 Expected additions

```text
src/libs/models/trendline_family/mtf.py
```

Contracts may be extended conservatively for:

- projected MTF family member,
- MTF family cluster,
- confluence/conflict relation,
- unified MTF geometry snapshot.

## H.3 Required rules

- each timeframe tracker updates only on its confirmed close,
- higher-timeframe structures are projected between closes, not refitted,
- source timeframe and family provenance remain available,
- raw slopes are normalized to a common clock/volatility basis,
- conflicting structures remain visible,
- output is a composed geometry map, not one averaged trendline.

## H.4 Exit gate

- no incomplete-HTF leakage,
- deterministic timestamp projection,
- source provenance preserved,
- agreement and conflict both represented,
- MTF confluence feature availability reported,
- latency and state synchronization documented.

## H.5 Codex prompt

```text
Implement Phase H only from plans/trendline-family-codex-phase-execution-plan.md.

Add asynchronous MTF composition over latest confirmed per-timeframe family snapshots. Project exact lines to a common timestamp, preserve provenance, normalize slope/time semantics, and expose agreement, conflict, intersections, and confluence. Do not average all structures into one synthetic line.

Do not implement optimizer/promotion work in this phase.

Run MTF causality and composition tests and stop. Return the mandatory review package.
```

---

# Phase I — Stage-Specific Optimization, Evaluation, and Promotion

## I.1 Objective

Optimize and evaluate each stage only against outcomes it can affect, then decide whether individual feature groups are promoted.

## I.2 Required optimizer separation

### Candidate/geometry optimizer

Owns:

- pivot windows/scales,
- lookback,
- pathfinding/fitter parameters,
- candidate quality thresholds.

Scores:

- candidate validity/coverage,
- line survival,
- touch/reaction quality,
- penetration,
- stability.

### Tracker optimizer

Owns:

- matching gates/weights,
- birth threshold,
- grace/dormancy/expiry,
- confidence decay/reactivation.

Scores:

- ID continuity,
- churn,
- association correctness,
- future structural utility.

### Interaction optimizer

Owns:

- zone width,
- approach threshold,
- confirmation bars,
- retest windows.

Scores:

- event precision/recall,
- Brier/log-loss or equivalent calibration,
- detection delay,
- failed-break discrimination.

### Downstream RegimeV2 ablation

Groups:

```text
base geometry
family identity/lifecycle
interaction observations
full events
multi-rail features
MTF features
```

## I.3 Promotion rules

- no parameter may be searched if it cannot affect the evaluated objective,
- all trials and failures are persisted,
- use walk-forward and untouched holdout,
- report coverage/counts and operational churn,
- optimized parameters are written to a review artifact first,
- promotion into `configs/trendline_family.yaml` requires explicit approval.

## I.4 Exit gate

- parameter-effect audit passes,
- OOS gain or stability improvement is demonstrated,
- no hidden lookahead,
- calibration and sample counts reported,
- latency and failure rates acceptable,
- explicit promote/hold/reject decision per feature group.

## I.5 Codex prompt

```text
Implement Phase I only from plans/trendline-family-codex-phase-execution-plan.md.

Build stage-specific candidate, tracker, and interaction optimization/evaluation paths, plus RegimeV2 feature-group ablation and promotion artifacts. Every parameter must affect its owned evaluated stage. Preserve all trials, use walk-forward plus untouched holdout, and do not auto-write promoted values into runtime config.

Run parameter-effect and evaluation tests and stop. Return the mandatory review package with promote/hold/reject recommendations.
```

---

## 5. Review Protocol After Each Phase

The architecture reviewer should check the phase in this order.

### 5.1 Scope compliance

- Did Codex implement only the requested phase?
- Did it modify files outside the allowed blast radius?
- Did it introduce speculative abstractions?

### 5.2 Import and ownership compliance

- Search for imports of old trendline packages.
- Confirm copied algorithms are fully owned in the new package.
- Confirm no hidden dynamic or optional fallback import exists.

### 5.3 Contract consistency

- Compare fields and semantics with the architecture plan.
- Check timestamp, ID, role, lifecycle, and zone meanings.
- Reject overloaded fields or mixed geometry/policy concepts.

### 5.4 Config consistency

- Confirm every runtime parameter comes from resolved config.
- Confirm precedence and field provenance.
- Confirm unknown keys fail closed.
- Confirm every active hyperparameter has a stage owner and parameter-effect test.

### 5.5 Causality and replay

- Confirm confirmed-bar-only state updates.
- Confirm pivot confirmation timing.
- Confirm history excludes current state.
- Confirm identical inputs produce identical snapshots.

### 5.6 Quant semantics

- Inspect synthetic cases, not only serialization tests.
- Check support/resistance symmetry.
- Check stability versus hysteresis/churn.
- Check that interaction zones do not mutate geometry.
- Check family identity survives legitimate small changes.

### 5.7 Decision

Issue one result:

```text
APPROVED
APPROVED WITH REQUIRED FOLLOW-UP
CHANGES REQUIRED
REJECTED / REDESIGN
```

Only `APPROVED` permits the next phase without correction.

---

## 6. Recommended Immediate Action

Send Codex only:

1. `plans/trendline-family-model-architecture-plan.md`
2. `plans/trendline-family-codex-phase-execution-plan.md`
3. the Phase A prompt from Section A.9

Do not tell Codex to implement the whole model.

After Codex finishes Phase A, return its review package and repository changes for architecture review before issuing Phase B.
