---
goal: Rehome and formalize canonical Trendline Family contracts without behavior change
stage: coder-to-review
date_created: 2026-07-21
last_updated: 2026-07-21
owner: Codex
status: Ready
tags: [handoff, quant, trendline-family, architecture-refactor, phase-1b, phase-1c, phase-1d]
source_agent: Codex
target_agent: quant-review
---

# Phase 1B-1C: Structural Migration And Domain Contracts

## Scope Executed

- Canonical implementation moved from `libs.models.trendline_family` to `libs.models.trendline`.
- Old `libs.models.trendline_family` now compatibility-only. No copied algorithm code remains.
- Canonical RegimeV2 family adapter and six canonical research/optimization scripts now import `libs.models.trendline`.
- Legacy systems left unchanged:
  - `src/libs/trendlines/`
  - `src/app/trendlines/`
  - `src/libs/models/trendlines_old/`
- No repository-history, replay, lifecycle, contract-field, feature, YAML, TVLC, or algorithm change.

## Changes Made

### Exact migration map

| Old canonical path | New canonical path |
| --- | --- |
| `trendline_family/{api,config,config_loader,config_resolver,contracts,corridors,event_lifecycle,events,features,fitting,interactions,matching,mtf,pivots,provider,rails,ranking,registry,repository,tracker}.py` | `trendline/{same relative path}.py` |
| `trendline_family/optimization/{__init__,ablation,artifacts,candidate_optimizer,contracts,evaluator,folds,interaction_optimizer,metrics,runner,tracker_optimizer}.py` | `trendline/optimization/{same relative path}.py` |
| `trendline_family/research_lab/{__init__,artifacts,contracts,plotting,replay,tables}.py` | `trendline/research_lab/{same relative path}.py` |
| `trendline_family/__init__.py` | compatibility top-level re-exports from `trendline/__init__.py` |

### Compatibility-module map

- Every former module path above now exists as a forwarding module under `trendline_family`.
- `trendline_family/_compat.py` imports one named canonical module and re-exports its public surface. No wildcard import. No duplicated implementation.
- Top-level compatibility package has explicit import list and preserves historical `__all__`.
- Identity assertions cover contracts, provider, optimizer, config, API-facing snapshots.

### Persistence identity preservation

- No core contract hash derives from class module or qualname.
- No pickle, joblib, Pydantic, or class-qualified persistence path found in canonical model.
- Two persisted Stage-I identities did use class module paths:
  - native provider identity;
  - `WeightedFeatureScorer` ablation identity.
- New canonical code emits historical semantic values for these built-ins:
  - `libs.models.trendline_family.provider.NativeDeterministicLineProvider`
  - `libs.models.trendline_family.optimization.ablation.WeightedFeatureScorer`
- This preserves existing Phase-I artifact semantics while implementation moves.

### Consumers updated

- `src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py`
- `scripts/run_trendline_family_candidate_geometry_trial.py`
- `scripts/run_trendline_family_saturating_quality_fresh_window_trial.py`
- `scripts/build_trendline_family_candidate_evidence_report.py`
- `scripts/diagnose_trendline_family_candidate_rejection.py`
- `scripts/analyze_trendline_family_candidate_density.py`
- `scripts/analyze_trendline_family_candidate_quality_normalization.py`

## Blast Radius Considered

- High risk: canonical API, immutable contracts, deterministic IDs, Phase-I artifacts, RegimeV2 shadow adapter.
- Guard: old import package remains valid and resolves to same object identities.
- Legacy RegimeV2 feature producer and `collect_shadow_binance` remain on `libs.trendlines`; no imports changed.
- New package source has no import from compatibility or any legacy trendline package.
- Core canonical runtime modules have no import from research or optimization subpackages.

## Validation Performed

Baseline before migration:

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q -ra
347 passed in 24.48s
0 failed, 0 skipped, 0 expected pre-existing failures
```

Post-migration:

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q -ra
352 passed in 24.11s

PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/regime_v2/adapters/test_trendline_family_feature_producer.py \
  tests/signals/test_trendline_family_shadow_projected_runtime.py -q -ra
15 passed in 3.42s

PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scripts/test_trendline_family_candidate_geometry_trial.py \
  tests/scripts/test_trendline_family_saturating_quality_fresh_window_trial.py \
  tests/scripts/test_trendline_family_candidate_evidence_report.py \
  tests/scripts/test_trendline_family_candidate_rejection.py \
  tests/scripts/test_trendline_family_candidate_density.py \
  tests/scripts/test_trendline_family_candidate_quality_normalization.py -q -ra
157 passed in 70.37s

PYTHONPATH=src .venv/bin/python -m pytest tests/test_regime_v2_trendline_feature_producer.py -q -ra
6 passed in 2.75s

PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/sr/research/studies/swing_reversal_adequacy/test_import_boundaries.py -q -ra
1 passed in 0.07s

ruff check src/libs/models/trendline src/libs/models/trendline_family tests/models/trendline_family
All checks passed

PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline src/libs/models/trendline_family
Passed

git diff --check
Passed
```

New migration tests:

- Canonical package has one-way import direction.
- Canonical runtime excludes research/optimization imports.
- Legacy package remains distinct.
- Compatibility objects are identical to canonical objects.
- Candidate, snapshot, event transition, config/model version, provider and ablation Stage-I identity parity holds.

## Not Changed

- No legacy trendline file or consumer changed.
- No algorithms, parameters, YAML, candidate/family/event behavior, repository interface, replay semantics, MTF semantics, or artifact content changed.
- No historical storage, `get_state_at`, domain split, TVLC payload, or UI work added.

## Risks Or Follow-Up Items

- External third-party pickles using old class paths were not found in repository. Compatibility import paths allow unpickling if their payload resolves by import path; no external artifact proof exists.
- Codebase-memory reindex completed, but returned only `24` nodes / `36` edges. Source-level import tests used for this migration. Repair index before reviewer relies on graph blast-radius results.
- Dense-module decomposition remains deferred. Next approved phase should add domain contracts only, with snapshot/ID parity retained.

## Review Request

Review package ownership, compatibility surface, no-legacy boundary, and persisted semantic identities. Package is complete for review without further coder context.

## Phase 1C Scope Executed

- Added presentation-independent `libs.models.trendline.domain`.
- No existing runtime record moved or copied. Existing immutable records remain canonical.
- Added only one new contract: immutable `TrendlineContext`.
- Tracker, API, storage, replay, research, visualization, optimization, and legacy packages remain unchanged by Phase 1C.

## Domain Symbol Ownership Map

| Requested concept | Existing canonical type | Defining module | Domain path | Classification |
| --- | --- | --- | --- | --- |
| `TrendlineFamily` | `TrendlineFamilyState` | `trendline.contracts` | `domain.entities.TrendlineFamily` | alias unchanged |
| `TrendlineSnapshot` | `TrendlineFamilySnapshot` | `trendline.contracts` | `domain.contracts.TrendlineSnapshot` | alias unchanged |
| `TrendlineEvent` | `FamilyInteractionEvent` | `trendline.contracts` | `domain.events.TrendlineEvent` | alias unchanged |
| Event transition | `FamilyInteractionEventTransition` | `trendline.contracts` | `domain.events.TrendlineEventTransition` | alias unchanged |
| Family lifecycle transition | `FamilyTransition` | `trendline.contracts` | `domain.events.FamilyTransition` | re-export unchanged |
| Domain enums | existing family/interaction enums | `trendline.contracts` | `domain.enums` | re-export unchanged |
| `TrendlineContext` | none | `trendline.domain.contracts` | `domain.contracts.TrendlineContext` | new required read contract |

Deferred ownership:

- Geometry records remain in `trendline.contracts`; extraction would move validation helpers with them.
- Tracker lifecycle and event advancement remain in `tracker.py` and `event_lifecycle.py`; both contain runtime behavior.
- Feature calculations remain in `features.py`.

## Domain Contract Details

- `TrendlineContext` is frozen, UTC-explicit, tuple-backed, and presentation-neutral.
- Fields: `asset`, `timeframe`, `as_of`, sorted known `families`, sorted known interaction `events`.
- Validation rejects mismatched asset/timeframe, duplicate or unordered IDs, non-canonical records, and records updated after `as_of`.
- `trendline_context_from_snapshot(snapshot)` is pure adapter over already-published snapshot. It does not query storage or alter tracker/API output.
- No chart style, marker, color, UI, or browser field exists in domain.

## Import Path Map

| Old/current path | Canonical domain path | Identity |
| --- | --- | --- |
| `libs.models.trendline.contracts.TrendlineFamilyState` | `libs.models.trendline.domain.entities.TrendlineFamily` | same object |
| `libs.models.trendline_family.contracts.TrendlineFamilyState` | `libs.models.trendline.domain.entities.TrendlineFamily` | same object |
| `libs.models.trendline.contracts.TrendlineFamilySnapshot` | `libs.models.trendline.domain.contracts.TrendlineSnapshot` | same object |
| `libs.models.trendline_family.contracts.TrendlineFamilySnapshot` | `libs.models.trendline.domain.contracts.TrendlineSnapshot` | same object |
| `libs.models.trendline.events` and compatibility events path | `libs.models.trendline.domain.events` | existing event objects preserved |

## Phase 1C Serialization Evidence

- Snapshot dataclass field order/defaults and `to_dict`/`from_dict` output unchanged because domain snapshot is same object.
- Event dataclass field/default identity unchanged because domain event is same object.
- Family IDs, model version, config hash, deterministic IDs, and optimization identities remain unchanged.
- No project pickle/joblib artifacts found. Added static pre-Phase-1B protocol-0 fixture referencing `libs.models.trendline_family.contracts.FamilyRole`; it loads through compatibility path to canonical enum object.
- No `__module__` rewriting added for domain aliases.

## Phase 1C Validation

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q -ra
358 passed in 25.53s

PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/regime_v2/adapters/test_trendline_family_feature_producer.py \
  tests/signals/test_trendline_family_shadow_projected_runtime.py -q -ra
15 passed in 3.48s

PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scripts/test_trendline_family_candidate_geometry_trial.py \
  tests/scripts/test_trendline_family_saturating_quality_fresh_window_trial.py \
  tests/scripts/test_trendline_family_candidate_evidence_report.py \
  tests/scripts/test_trendline_family_candidate_rejection.py \
  tests/scripts/test_trendline_family_candidate_density.py \
  tests/scripts/test_trendline_family_candidate_quality_normalization.py -q -ra
157 passed in 74.99s

PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/models/sr/research/studies/swing_reversal_adequacy/test_import_boundaries.py -q -ra
7 passed in 3.05s

ruff check src/libs/models/trendline src/libs/models/trendline_family tests/models/trendline_family
All checks passed

PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline src/libs/models/trendline_family
Passed

git diff --check
Passed
```

## Phase 1C Architecture Checks

- Domain has no imports from storage, research, visualization, API, compatibility, or legacy trendline packages.
- Domain has no tracker/provider execution path.
- Context is immutable and deterministically ordered.
- Old/new aliases, enum values, API output, snapshot/event serialization, and historical import-path loading are covered.

## Updated Limitations

- Domain currently aliases dense root contracts. This is intentional; extracting pure type definitions now would risk serialization and runtime behavior.
- `TrendlineContext` adapts one supplied snapshot only. Historical lookup/reconstruction remains Phase 1D work.
- Codebase-memory index now reports `109` nodes / `351` edges. Still incomplete for full graph review; source-level architecture tests remain controlling evidence.

## Phase 1D Scope Executed

- Added the canonical, storage-neutral persistence boundary under `libs.models.trendline.storage`.
- Preserved existing aggregate snapshot current-head validation and clone semantics.
- Added immutable in-memory history and causal `get_state_at(asset, timeframe, as_of)`.
- No tracker, candidate, interaction, lifecycle, configuration, API, RegimeV2, research, visualization, SQLite, or legacy-algorithm change.

## Phase 1D Ownership And Compatibility Map

| Responsibility | Canonical path | Compatibility path | Notes |
| --- | --- | --- | --- |
| Repository protocol, snapshot serialization, repository errors | `trendline.storage.repository` | `trendline.repository`, then `trendline_family.repository` | Same exported protocol/error/serialization objects. |
| In-memory implementation | `trendline.storage.memory.InMemoryTrendlineRepository` | `trendline.repository.InMemoryTrendlineFamilyRepository`, then family compatibility path | Both names are the same runtime class. |
| Historical read contract | `trendline.storage.memory.get_state_at` | Available through the same compatibility class | Returns domain `TrendlineContext`, never a chart payload. |
| Historical Phase-G helper | `trendline.storage.memory._phase_g_enabled` | `trendline.repository`, then family compatibility path | Explicit legacy-test compatibility export only; new callers use storage. |

## Current-Head Parity

- One current aggregate `TrendlineFamilySnapshot` head remains stored per `(asset, timeframe)`.
- `latest_snapshot` returns the same JSON round-trip clone behavior as before.
- Existing lineage checks remain controlling: first snapshot rules, exact `previous_snapshot_id`, advancing snapshot ID/timestamp, family version rules, and Phase-G lineage validation.
- An exact duplicate snapshot remains rejected by the original predecessor mismatch rule before any duplicate-ID branch.
- The new history append happens only after existing lineage validation and new defensive family/event prevalidation succeed.

## Causal Historical Contract

- Snapshot granularity is the published aggregate family-set snapshot emitted by the tracker for a confirmed observed bar.
- Snapshot `timestamp` is the causal known/emission time. `get_state_at` selects the retained latest snapshot where `snapshot.timestamp <= as_of`; it never reconstructs the current head.
- Returned families are exactly the selected snapshot's active plus dormant families, deterministically ordered by `family_id`.
- `TrendlineFamilyState.updated_at` and `FamilyInteractionEvent.updated_at` remain causal known times.
- Interaction-event revisions are retained by `(asset, timeframe, event_id)`. The latest revision with `updated_at <= as_of` is returned, ordered by `(updated_at, event_id)`.
- Family/event transitions remain preserved in the immutable aggregate snapshot history. Storage does not synthesize new events or change tracker event semantics.
- No matching historical snapshot yields an empty immutable `TrendlineContext`; direct events known by `as_of` remain available for that partition.

## Persistence Semantics

- `save_family` and `save_event` accept only canonical immutable domain aliases and retain JSON-cloned records.
- Re-saving an identical family/event is idempotent. A family must retain partition identity and advance version/`updated_at`; an event revision cannot regress or conflict at identical `updated_at`.
- `get_family`, `latest_snapshot`, and historical contexts use canonical deserialization or frozen contract construction, so callers cannot mutate repository state.
- `TrendlineContext.events` now defaults to the empty tuple and uses causal known-time ordering, preserving pure snapshot adaptation while allowing repository-complete historical event context.

## Phase 1D Validation

```text
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family/test_phase_1d_storage.py -q -ra
8 passed in 0.34s

PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q -ra
366 passed in 23.62s

PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/regime_v2/adapters/test_trendline_family_feature_producer.py \
  tests/signals/test_trendline_family_shadow_projected_runtime.py -q -ra
15 passed in 2.33s

PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/models/sr/research/studies/swing_reversal_adequacy/test_import_boundaries.py -q -ra
7 passed in 2.17s

ruff check src/libs/models/trendline src/libs/models/trendline_family tests/models/trendline_family
All checks passed

PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline src/libs/models/trendline_family
Passed

git diff --check
Passed
```

New Phase 1D tests cover current-head parity, strict aggregate snapshot lineage, frozen history, partition isolation, event revisions and exact known-time boundaries, duplicate/conflict behavior, full-history versus independently-run causal-prefix differential behavior, break/lifecycle histories, and storage import boundaries.

## Phase 1D Review Risks And Limits

- This is an in-memory boundary only. No process-restart durability, SQLite implementation, migration format, or external store is introduced.
- Private historical collections intentionally have no bulk-query API. The approved read surface is `get_state_at` only.
- The graph index remains incomplete; source-level imports and the controlling causal-prefix differential tests are the reliable evidence for this phase.
- TVLC/replay UI, research evaluation, and any new domain behavior remain later phases.
