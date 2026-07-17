---
goal: Re-review the remediated SR-V1.0 foundation against the approved domain, identity, configuration, causality, and import-boundary plan.
stage: review-to-architect
date_created: 2026-07-14
last_updated: 2026-07-14
owner: Quant Review
status: Request Changes
tags: [handoff, quant, sr, foundation, contracts, config, identity, causality]
source_agent: Quant Review
target_agent: Quant Architect
---

# Review To Architect: SR-V1.0 Foundation Rereview v1

## Review Scope

Reviewed the approved SR-V1.0 foundation-only scope:

```text
src/libs/models/sr/
  __init__.py
  domain/{__init__.py,contracts.py,identity.py}
  config/{__init__.py,models.py,resolver.py}

tests/models/sr/
  test_imports.py
  adapters/test_import_boundaries.py
  config/test_resolver.py
  domain/test_contracts.py
  domain/test_identity.py
```

The approved phase remains limited to immutable contracts, deterministic identity, strict typed configuration, and import boundaries. Detection engines, association logic, lifecycle transitions, persistence adapters, feature production, YAML integration, optimization, and legacy migration are out of scope.

## Plan Compliance Summary

### Confirmed aligned

- Package is descriptive and limited to `domain/` and `config/`.
- The approved eight-parameter surface is present exactly:
  - `pivot_span_bars`
  - `zone_half_width_atr`
  - `merge_distance_atr`
  - `touch_tolerance_atr`
  - `break_buffer_atr`
  - `break_confirm_closes`
  - `max_age_bars`
  - `max_active_zones`
- Resolution precedence is `defaults -> timeframe -> exact asset/timeframe`.
- Mandatory complete defaults are shape-checked.
- Asset-wide defaults and runtime overrides are not supported.
- V1 lifecycle is correctly represented as four statuses:
  - `ACTIVE`
  - `BREACH_PENDING`
  - `BROKEN`
  - `EXPIRED`
- Fakeouts are represented as `FALSE_BREAKOUT` events plus `fakeout_count`, not as a persistent lifecycle state.
- Candidate, zone, event, and snapshot IDs are derived with `init=False` and SHA-256 canonical content hashing.
- Aware timestamps are normalized to UTC; naive timestamps are rejected.
- Zone geometry rejects non-positive center, width, and lower bound.
- Aggregate zones enforce matching `state_key`, matching `config_hash`, unique `zone_id`, and canonical ordering.
- Snapshot zone/event input order no longer changes `snapshot_id`.
- No legacy `app.sr` or `libs.sr` runtime imports exist.
- No production runtime currently imports the new package; blast radius is isolated to the new foundation and tests.

## Findings By Severity

### Blocking 1 — Resolver configuration is still externally mutable

`src/libs/models/sr/config/resolver.py:30-38` calls `_deep_freeze_config_source`, but mappings are copied into ordinary dictionaries rather than immutable mappings. `SRConfigResolver.raw_config` then returns the internal object directly at lines `91-93`.

Independent probe:

```text
resolver.raw_config["defaults"]["detection"]["pivot_span_bars"] = 999
resolver.resolve(...).detection.pivot_span_bars == 999
```

This violates the approved deep-immutability contract and allows post-construction config identity to drift without revalidation.

Required remediation:

- recursively freeze mappings with `MappingProxyType` or an equivalent immutable structure;
- never expose a mutable internal reference;
- add adversarial tests mutating every returned nesting level;
- prove repeated resolution remains byte/content identical after attempted external mutation.

### Blocking 2 — `ResolvedSRConfig` is not actually type-safe or provenance-complete

`src/libs/models/sr/config/models.py:331-364` validates strings and the supplied hash, but does not require:

- `detection` to be `DetectionConfig`;
- `association` to be `AssociationConfig`;
- `lifecycle` to be `LifecycleConfig`;
- provenance to contain exactly all eight field paths once;
- provenance sources to be valid for the resolved asset/timeframe.

`ResolvedSRConfig.create()` at lines `366-404` bypasses `__post_init__` through `object.__new__` and directly installs caller-provided objects.

Independent probe successfully created a resolved config with:

```text
detection type: FakeDetection
pivot_span_bars: "not-an-int"
field_provenance entries: 0
```

The hash remains internally consistent because it authenticates invalid content rather than enforcing the approved typed contract.

Required remediation:

- remove the `object.__new__` bypass or route creation through one validated constructor path;
- enforce exact config-group classes;
- require the exact eight provenance keys with no duplicates or omissions;
- validate provenance source grammar against `defaults`, `timeframe:<tf>`, and `asset_timeframe:<asset>:<tf>`;
- add direct-constructor and factory adversarial tests.

### Blocking 3 — `SRConfig` claims value validation but only validates shape

`SRConfig` is documented as a “validated” raw configuration at `src/libs/models/sr/config/models.py:167-188`, but `_validate_sections()` at lines `217-249` checks only required/unknown fields and mapping shape. It does not instantiate the typed section classes or validate values.

Independent probe constructed `SRConfig` successfully with:

```text
pivot_span_bars = 0
zone_half_width_atr = 0.0
merge_distance_atr = -1.0
touch_tolerance_atr = -1.0
break_buffer_atr = -1.0
break_confirm_closes = 0
max_age_bars = 0
max_active_zones = 0
```

The invalid values fail only later if resolution happens. An immutable “validated” config object must not be able to represent invalid parameter values.

Required remediation:

- validate complete defaults through `DetectionConfig`, `AssociationConfig`, and `LifecycleConfig` during `SRConfig` and resolver construction;
- validate every override value at its source path, not only after merging;
- retain complete-default enforcement and exact layering.

### Blocking 4 — Snapshot/runtime contracts permit non-causal and orphaned truth

`ZoneRuntimeState` at `src/libs/models/sr/domain/contracts.py:286-328` normalizes timestamps but does not require `last_interaction_at <= updated_at`.

`ZoneRecord` at lines `331-344` checks only zone-ID equality and does not require runtime timestamps to be on or after the definition availability time.

`SRSnapshot` at lines `399-428` validates zone ownership and sorts events, but does not enforce:

- unique `event_id`;
- event ownership by a snapshot/state zone or another explicit ownership key;
- `event.timestamp <= snapshot.as_of`;
- `zone.runtime.updated_at <= snapshot.as_of`;
- runtime/definition temporal ordering.

Independent probe accepted one snapshot containing all of:

```text
2 duplicate events
an event for an unrelated zone_id
an event timestamp after snapshot.as_of
last_interaction_at after runtime.updated_at
```

This violates point-in-time correctness and the approved state/snapshot ownership requirement. Canonical hashing makes the invalid snapshot deterministic, but not valid.

Required remediation:

- define explicit event ownership semantics;
- either require event `zone_id` membership in the snapshot/state zone set or add immutable event ownership fields sufficient to verify `state_key` and `config_hash` when historical-zone events are intentionally allowed;
- reject duplicate event IDs;
- enforce all snapshot and runtime temporal inequalities;
- add adversarial causality tests before lifecycle implementation starts.

### Major 1 — Resolved config serialization omits audit identity

`ResolvedSRConfig.to_dict()` at `src/libs/models/sr/config/models.py:406-414` omits both `field_provenance` and `resolved_config_hash` even though those fields define the class’s audit contract.

Required remediation:

- include provenance and resolved hash in the canonical exported representation, or rename the method to make the intentionally reduced view explicit;
- add round-trip/audit-shape tests.

### Major 2 — Empty semantic asset blocks remain accepted

`assets.<asset> = {"timeframes": {}}` is non-empty as a mapping and therefore passes the check at `src/libs/models/sr/config/models.py:287-315`, despite containing no usable override.

Required remediation:

- reject empty `timeframes` maps inside asset blocks;
- add the exact adversarial fixture.

### Minor 1 — Ruff is not clean

Ruff reports six unused imports:

```text
src/libs/models/sr/config/resolver.py:14       asdict
src/libs/models/sr/domain/contracts.py:10      timezone
src/libs/models/sr/domain/identity.py:11       timedelta
tests/models/sr/config/test_resolver.py:6-9    three config classes
```

### Minor 2 — Import-boundary test misses `from pandas/yaml import ...`

`tests/models/sr/adapters/test_import_boundaries.py` checks forbidden modules only for `ast.Import`, not `ast.ImportFrom`. Current source is clean, but the guard can be bypassed by a future `from pandas import ...` or `from yaml import ...` statement.

## Causality And Quant-Safety Gate

Status: **FAIL**

Positive findings:

- candidate and definition availability cannot precede formation/creation;
- aware timestamps normalize to UTC;
- identity is deterministic after normalization.

Blocking failure:

- snapshots can contain future events and future runtime state relative to `as_of`;
- runtime interaction ordering can be internally contradictory;
- event ownership is unverifiable.

No detector or lifecycle engine should be built on these contracts until the causal invariants are closed.

## Blast Radius And Affected Flows

Codebase-memory status:

```text
project: Users-aloobhujia-flipperAgent
status: ready
nodes: 51,411
edges: 166,785
```

Observed callers/importers:

- package exports;
- the focused `tests/models/sr` suite;
- no production signal, strategy, risk, execution, portfolio, RegimeV2, trendline-family, or legacy S/R flow.

Expected remediation scope:

```text
src/libs/models/sr/config/models.py
src/libs/models/sr/config/resolver.py
src/libs/models/sr/domain/contracts.py
tests/models/sr/config/test_resolver.py
tests/models/sr/domain/test_contracts.py
tests/models/sr/adapters/test_import_boundaries.py
```

`identity.py` should remain unchanged unless a new ownership payload requires a deliberate identity-version decision.

## Validation Evidence

Executed independently:

```text
focused tests: 53 passed in 2.79s
compileall:     passed
Ruff:          failed, 6 F401 findings
```

Adversarial probes independently reproduced all four blocking findings.

Codebase-memory `detect_changes` reports only tracked `.codebase-memory` artifacts because the new SR source/tests are currently untracked; therefore it cannot be treated as complete change-scope evidence for this review.

## Explicit Non-Goals For Remediation

Do not add:

- detection algorithms;
- candidate association/merging logic;
- lifecycle transition engine;
- previous-zone retention policy implementation;
- persistence adapters;
- YAML loading;
- optimizer/search spaces;
- trendline or regime integration;
- legacy S/R migration.

The previous-zone preservation window remains a later lifecycle/state-store responsibility. This phase should only ensure the contracts can represent retained zones causally and immutably.

## Approval Status

**REQUEST CHANGES — SR-V1.0 foundation is not approved.**

The original parameter-surface, identity, UTC, zone ownership, and canonical-order blockers are substantially remediated. Approval remains blocked by mutable resolver state, forgeable typed resolved config/provenance, invalid raw `SRConfig` values, and non-causal/orphan snapshot truth.

## Recommended Handoff

Return to the architect/coder for one narrow foundation-integrity remediation in this order:

1. make resolver source deeply immutable and non-leaking;
2. establish one validated `ResolvedSRConfig` construction path with exact provenance;
3. validate raw config values at construction;
4. add runtime/record/snapshot ownership and temporal invariants;
5. add adversarial regression tests;
6. clear Ruff;
7. rerun focused tests, compileall, import-boundary checks, and adversarial probes.

Do not start the detector or lifecycle phase until this review passes.
