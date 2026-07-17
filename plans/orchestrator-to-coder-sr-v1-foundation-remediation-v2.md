---
goal: Remediate SR-V1.0 foundation blocking issues identified in review-to-architect rereview v1.
stage: orchestrator-to-coder
date_created: 2026-07-14
last_updated: 2026-07-14
owner: Quant Orchestrator
status: In Progress
tags: [handoff, quant, sr, foundation, remediation, config, contracts, causality]
source_agent: Quant Orchestrator
target_agent: Coder Agent
---

# Orchestrator to Coder: SR-V1.0 Foundation Remediation v2

## Decision

**REJECT approval; route back to coder for one narrow foundation-integrity remediation.**

The previous remediation substantially closed the original parameter-surface, identity, UTC, zone ownership, and canonical-order blockers. The Quant Review rereview (see `plans/review-to-architect-sr-v1-foundation-rereview-v1.md`) identified four blocking findings and two major findings that must be resolved before the foundation can be approved.

## Scope

Only the following files may be changed:

```text
src/libs/models/sr/config/models.py
src/libs/models/sr/config/resolver.py
src/libs/models/sr/domain/contracts.py
tests/models/sr/config/test_resolver.py
tests/models/sr/domain/test_contracts.py
tests/models/sr/adapters/test_import_boundaries.py
```

`src/libs/models/sr/domain/identity.py` should remain unchanged unless a new ownership payload requires an identity-version decision.

## Blocking Issues

### 1. Resolver configuration is still externally mutable

**Location:** `src/libs/models/sr/config/resolver.py:30-38`, `:91-93`

`_deep_freeze_config_source` returns plain dictionaries, and `raw_config` exposes the internal object directly. Mutating `resolver.raw_config["defaults"]["detection"]["pivot_span_bars"] = 999` can change resolution output without revalidation.

**Required:**
- Recursively freeze mappings with `MappingProxyType` (or equivalent).
- Never expose a mutable internal reference.
- Add adversarial tests mutating every returned nesting level.
- Prove repeated resolution remains byte/content identical after attempted external mutation.

### 2. `ResolvedSRConfig` construction bypasses typed validation

**Location:** `src/libs/models/sr/config/models.py:331-404`

`ResolvedSRConfig.create()` uses `object.__new__` to bypass `__post_init__`, and `__post_init__` does not enforce:
- exact config-group classes (`DetectionConfig`, `AssociationConfig`, `LifecycleConfig`);
- provenance contains exactly all eight field paths once;
- provenance sources match valid grammar (`defaults`, `timeframe:<tf>`, `asset_timeframe:<asset>:<tf>`).

**Required:**
- Remove the `object.__new__` bypass or route creation through one validated constructor path.
- Enforce exact config-group classes.
- Require the exact eight provenance keys with no duplicates or omissions.
- Validate provenance source grammar.
- Add direct-constructor and factory adversarial tests.

### 3. `SRConfig` only validates shape, not values

**Location:** `src/libs/models/sr/config/models.py:167-249`

`SRConfig` and the resolver accept invalid values (e.g., `pivot_span_bars=0`, negative ATR values) because `_validate_sections` checks keys but does not instantiate typed section classes.

**Required:**
- Validate complete defaults through `DetectionConfig`, `AssociationConfig`, and `LifecycleConfig` during `SRConfig` and resolver construction.
- Validate every override value at its source path, not only after merging.
- Retain complete-default enforcement and exact layering.

### 4. Snapshot/runtime contracts permit non-causal and orphaned truth

**Location:** `src/libs/models/sr/domain/contracts.py:286-428`

Missing invariants:
- `ZoneRuntimeState.last_interaction_at <= updated_at`;
- `ZoneRecord.runtime` timestamps on/after `definition.available_at`;
- unique `event_id` within a snapshot;
- event ownership by a snapshot/state zone (or explicit ownership key);
- `event.timestamp <= snapshot.as_of`;
- `zone.runtime.updated_at <= snapshot.as_of`.

**Required:**
- Define explicit event ownership semantics.
- Either require event `zone_id` membership in the snapshot/state zone set, or add immutable event ownership fields sufficient to verify `state_key` and `config_hash` for historical-zone events.
- Reject duplicate event IDs.
- Enforce all snapshot and runtime temporal inequalities.
- Add adversarial causality tests.

## Major Issues

### 1. `ResolvedSRConfig.to_dict()` omits audit identity

**Location:** `src/libs/models/sr/config/models.py:406-414`

`to_dict()` omits `field_provenance` and `resolved_config_hash`. Either include them in the exported representation, or rename the method to make the reduced view explicit and add audit-shape tests.

### 2. Empty semantic asset blocks accepted

**Location:** `src/libs/models/sr/config/models.py:287-315`

`assets.<asset> = {"timeframes": {}}` is accepted despite containing no usable override. Reject empty `timeframes` maps inside asset blocks and add the exact adversarial fixture.

## Minor Issues

- Ruff reports six unused imports across resolver, contracts, identity, and tests.
- Import-boundary test only checks `ast.Import`, not `ast.ImportFrom`.

## Non-Goals

Do **not** add:
- detection algorithms;
- association/merging logic;
- lifecycle transition engine;
- previous-zone retention policy implementation;
- persistence adapters;
- YAML loading;
- optimizer/search spaces;
- trendline or regime integration;
- legacy S/R migration.

## Acceptance Criteria

1. All four blocking issues are closed with adversarial tests.
2. Both major issues are closed.
3. `ruff check` passes for the touched files.
4. `tests/models/sr` passes.
5. `tests/models/trendline_family/test_import_boundaries.py` passes.
6. `compileall -q src/libs/models/sr` passes.
7. No forbidden `app.sr` or `libs.sr` imports.
8. Codebase-memory `detect_changes` or equivalent scope check confirms only expected files changed.

## Validation Commands

```bash
.venv/bin/python -m pytest tests/models/sr -q
.venv/bin/python -m pytest tests/models/trendline_family/test_import_boundaries.py -q
.venv/bin/python -m compileall -q src/libs/models/sr
.venv/bin/python -c "import libs.models.sr; print('ok')"
rg -n "app\.sr|libs\.sr" src/libs/models/sr tests/models/sr
ruff check src/libs/models/sr tests/models/sr
```

## Next Step

Coder Agent implements the remediation in `feature/sr-v1.0-foundation` and returns an execution handoff for Quant Review.
