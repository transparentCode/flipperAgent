---
goal: Implement the deterministic SR-V1.1 lifecycle engine on top of the approved SR-V1.0 foundation.
stage: orchestrator-to-coder
date_created: 2026-07-14
last_updated: 2026-07-14
owner: Quant Orchestrator
status: Ready
tags: [handoff, quant, sr, lifecycle, state-machine, causality]
source_agent: Quant Orchestrator
target_agent: Coder Agent
source_branch: feature/sr-v1.0-foundation
target_branch: feature/sr-v1.1-lifecycle
---

# Orchestrator To Coder: SR-V1.1 Lifecycle v1

## Decision And Phase Gate

SR-V1.0 contracts, identity, typed configuration, YAML loading, and import
boundaries are approved. Implement **SR-V1.1 lifecycle only** and stop for
Quant Review.

Before starting:

1. add the approved non-blocking regression asserting that
   `SRConfigResolver.resolve` has no `runtime_override` parameter;
2. commit the approved V1.0 working tree on `feature/sr-v1.0-foundation`;
3. create `feature/sr-v1.1-lifecycle` from that exact commit;
4. do not merge either branch.

Do not mix V1.0 cleanup and V1.1 lifecycle changes in one commit.

## Approved Lifecycle Policy

These decisions are fixed for V1.1:

- Persistent statuses are exactly:
  - `ACTIVE`
  - `BREACH_PENDING`
  - `BROKEN`
  - `EXPIRED`
- Fakeout is not a persistent status. It is a `FALSE_BREAKOUT` event plus an
  increment of `fakeout_count`.
- Zone geometry is frozen for the complete zone episode:
  `center + half_width`; `half_width == 0` remains a valid line.
- Threshold distances use `ZoneDefinition.atr_at_creation`, not current-bar
  ATR.
- The first qualifying breach close counts toward
  `break_confirm_closes`.
- A close that is no longer beyond the breach threshold while a zone is
  `BREACH_PENDING` aborts the pending breach, emits `FALSE_BREAKOUT`, and
  returns the zone to `ACTIVE`.
- Interaction is evaluated before expiration on the expiry bar. Expiration is
  then applied only if the zone is still non-terminal.
- A zone cannot interact on the bar at `available_at`; it becomes eligible
  only when `closed_bar.closed_at > zone.definition.available_at`.
- `BROKEN` and `EXPIRED` are terminal and inert.
- No automatic support/resistance flip, resurrection, or role reversal exists
  in V1.1.
- Terminal zones remain in `SRState` and `SRSnapshot`. V1.1 performs no
  pruning. Retention-window and persistence policy belong to V1.3.
- The engine processes only zones already present in `previous_state`.
  Candidate generation and association belong to V1.2.

## Public Contract

Add an immutable `ClosedBar` domain contract and a stateless `SREngine`.

The intended public call is:

```python
new_state, snapshot, events = SREngine().step(
    previous_state,
    closed_bar,
    resolved_config,
)
```

The exact return shape is:

```python
tuple[SRState, SRSnapshot, tuple[SREvent, ...]]
```

Export `ClosedBar` and `SREngine` from `libs.models.sr`.

Do not introduce an abstract engine, plugin registry, dependency-injection
container, protocol hierarchy, or generic state-machine framework.

## Required File Structure

```text
src/libs/models/sr/
  domain/
    contracts.py          # add ClosedBar and minimal runtime age state
  lifecycle/
    __init__.py
    rules.py              # pure side-aware predicates
    engine.py             # SREngine orchestration

tests/models/sr/
  domain/
    test_contracts.py
  lifecycle/
    __init__.py
    test_rules.py
    test_engine.py
```

Small private helpers may be added inside these files. Do not add more
packages unless a concrete circular dependency makes one necessary and the
handoff explains it.

## ClosedBar Contract

`ClosedBar` must contain only the data required by V1.1:

```text
state_key: SRStateKey
bar_id: str
closed_at: aware UTC datetime
open: positive finite float
high: positive finite float
low: positive finite float
close: positive finite float
```

Validation must enforce:

- exact `SRStateKey` ownership;
- non-empty `bar_id`;
- aware UTC-normalized `closed_at`;
- finite positive OHLC values;
- `low <= high`;
- `low <= open <= high`;
- `low <= close <= high`.

Do not add volume, current ATR, indicators, features, regime fields, or
exchange metadata.

## Minimal Runtime Contract Extension

Add a mandatory non-negative integer `age_bars` to
`ZoneRuntimeState`.

Semantics:

- `age_bars` counts eligible closed bars processed for that zone;
- the availability bar does not increment age;
- each later processed bar increments it exactly once while the zone is
  non-terminal;
- terminal zones do not age;
- `ACTIVE`, `BROKEN`, and `EXPIRED` must have
  `pending_breach_count == 0`;
- `BREACH_PENDING` must have `pending_breach_count >= 1`.

Update all existing construction sites and tests explicitly. Do not give
`age_bars` a hidden numeric default.

## Pure Rule Definitions

For a zone:

```text
lower = geometry.lower_bound
upper = geometry.upper_bound
touch_distance = touch_tolerance_atr * atr_at_creation
break_distance = break_buffer_atr * atr_at_creation
```

### Touch

A bar touches the expanded zone when:

```text
bar.high >= lower - touch_distance
and
bar.low <= upper + touch_distance
```

A touch represents a qualifying closed-bar observation, not a reconstructed
intrabar path or a deduplicated multi-bar touch episode.

### Breach

For support:

```text
bar.close < lower - break_distance
```

For resistance:

```text
bar.close > upper + break_distance
```

The inequalities are strict. Equality is not a breach.

Rules must be pure and side-aware. They must not mutate a zone, read YAML,
load state, or consult future bars.

## Transition Table

### Terminal statuses

`BROKEN` and `EXPIRED` return unchanged and emit no events.

### ACTIVE

1. Increment `age_bars` for an eligible bar.
2. If the close is beyond the side-aware breach threshold:
   - emit `BREACH_STARTED`;
   - the first breach count is `1`;
   - if `break_confirm_closes == 1`, transition directly to `BROKEN`,
     reset `pending_breach_count` to `0`, and also emit
     `BREAK_CONFIRMED`;
   - otherwise transition to `BREACH_PENDING` with
     `pending_breach_count = 1`;
   - do not also emit `TOUCHED` for that bar.
3. Otherwise, if the expanded zone overlaps the bar:
   - remain `ACTIVE`;
   - increment `touch_count`;
   - emit `TOUCHED`.
4. Apply expiration after interaction if the result is still non-terminal.

### BREACH_PENDING

1. Increment `age_bars` for an eligible bar.
2. If the close remains beyond the breach threshold:
   - increment `pending_breach_count`;
   - when the count reaches `break_confirm_closes`, transition to
     `BROKEN`, reset `pending_breach_count` to `0`, and emit
     `BREAK_CONFIRMED`;
   - otherwise remain `BREACH_PENDING`;
   - do not emit another `BREACH_STARTED` or `TOUCHED`.
3. If the close is no longer beyond the breach threshold:
   - transition to `ACTIVE`;
   - reset `pending_breach_count` to `0`;
   - increment `fakeout_count`;
   - emit `FALSE_BREAKOUT`;
   - do not additionally emit `TOUCHED`.
4. Apply expiration after interaction if the result is still non-terminal.

### Expiration

After the interaction transition, if the zone remains `ACTIVE` or
`BREACH_PENDING` and:

```text
age_bars >= max_age_bars
```

then:

- transition to `EXPIRED`;
- reset `pending_breach_count` to `0`;
- emit `EXPIRED`.

This may produce an interaction event followed by `EXPIRED` on the same
bar. A confirmed break is already terminal and therefore wins over expiry.

## Runtime And Event Updates

For every eligible, non-terminal zone:

- `updated_at = closed_bar.closed_at`, including bars with no event, because
  `age_bars` changed;
- set `last_interaction_at = closed_bar.closed_at` for `TOUCHED`,
  `BREACH_STARTED`, `FALSE_BREAKOUT`, and `BREAK_CONFIRMED`;
- expiration alone does not change `last_interaction_at`;
- `touch_count` changes only for `TOUCHED`;
- `fakeout_count` changes only for `FALSE_BREAKOUT`;
- use `closed_bar.close` as the V1.1 event observation price;
- use `closed_bar.bar_id` and `closed_bar.closed_at` for every event.

If `break_confirm_closes == 1`, event order for the same zone/bar is
`BREACH_STARTED` followed by `BREAK_CONFIRMED`. Final snapshot ordering
must still use the existing canonical event ordering contract.

## Engine Preconditions And Output

`SREngine.step` must fail closed when:

- `previous_state` is not `SRState`;
- `closed_bar` is not `ClosedBar`;
- `resolved_config` is not `ResolvedSRConfig`;
- the bar `state_key` differs from the state `state_key`;
- state symbol/timeframe differs from resolved asset/timeframe;
- state `config_hash` differs from
  `resolved_config.resolved_config_hash`;
- `closed_bar.bar_id == previous_state.last_processed_bar`.

V1.1 does not define general bar ordering, restart behavior, or duplicate-bar
idempotence. Those are V1.3 responsibilities. Existing causal snapshot
invariants must still reject a bar older than the stored zone runtime.

Output requirements:

- inputs remain unchanged;
- zone definitions and geometries remain byte/content identical;
- only runtime state changes;
- all previous zones remain present;
- `new_state.last_processed_bar = closed_bar.bar_id`;
- snapshot `as_of = closed_bar.closed_at`;
- snapshot contains the new zone records and only events emitted by this step;
- returned events match the snapshot events;
- output ordering and identities are deterministic.

## Required Tests

At minimum, cover:

### ClosedBar

- valid support and resistance examples;
- naive datetime rejection and UTC normalization;
- non-finite/non-positive OHLC rejection;
- invalid OHLC ordering rejection;
- state-key and bar-ID validation.

### Rules

- support and resistance threshold direction;
- strict equality at breach threshold is not a breach;
- touch tolerance expansion;
- line geometry with `half_width == 0`;
- zero touch tolerance and zero break buffer;
- no mutation and deterministic repeated evaluation.

### Lifecycle transitions

- availability bar produces no interaction and no age increment;
- first eligible bar increments age once;
- `ACTIVE -> BREACH_PENDING`;
- `ACTIVE -> BROKEN` when confirmation count is one, with both events;
- consecutive breach closes confirm a break;
- non-breaching close produces exactly one fakeout and returns active;
- repeated fakeout episodes increment `fakeout_count`;
- touch increments `touch_count`;
- breach suppresses touch on the same bar;
- pending resolution suppresses touch on the same bar;
- active and pending expiration;
- touch then expiration on the same bar;
- breach start then expiration on the same bar;
- confirmed break wins over expiry;
- broken and expired zones are inert on later bars;
- no flip or resurrection;
- geometry and definition identity remain frozen.

### Engine and aggregate behavior

- empty state;
- multiple zones processed deterministically;
- support and resistance zones processed independently;
- previous input state remains immutable;
- all terminal zones remain in state and snapshot;
- config/state/bar ownership mismatches fail closed;
- exact duplicate bar ID fails closed;
- events belong to zones in the snapshot;
- state, snapshot, event IDs, and canonical ordering are stable for identical
  inputs;
- current V1.0 domain/config/YAML tests remain green.

## Import And Dependency Boundaries

Production lifecycle code must not import:

- `pandas`, NumPy, Polars, TA libraries, or ML libraries;
- YAML directly;
- `app.sr` or legacy `libs.sr`;
- persistence, database, filesystem, network, regime, trendline, strategy,
  execution, risk, or portfolio modules.

Only Python standard library and `libs.models.sr` domain/config modules are
allowed.

Extend the existing AST import-boundary test if needed so the new lifecycle
package is covered.

## Exact Configuration Surface

Do not add, remove, rename, or reinterpret configuration fields. V1.1 uses
only:

- `lifecycle.touch_tolerance_atr`
- `lifecycle.break_buffer_atr`
- `lifecycle.break_confirm_closes`
- `lifecycle.max_age_bars`

The remaining approved fields stay present but unused until their owning
phase. Do not add YAML values, per-asset tuning, current-ATR options,
cooldowns, decay, scoring, or feature flags.

## Explicit Non-Goals

Do not implement:

- pivot or swing detection;
- candidate creation;
- zone association or merging;
- active-zone ranking or eviction;
- persistence adapters or state stores;
- replay/restart parity;
- general out-of-order handling;
- duplicate-bar idempotent replay;
- terminal-zone pruning or configurable retention windows;
- automatic role reversal or flipped zones;
- breakout/retest setup logic;
- MTF composition;
- regime/trendline integration;
- features, strength scores, confidence, decay, ML, optimization, or trading
  policy;
- migration or runtime integration with legacy S/R.

## Acceptance Commands

Run and report:

```bash
.venv/bin/python -m pytest tests/models/sr -q
.venv/bin/python -m pytest tests/models/sr/domain tests/models/sr/lifecycle -q
.venv/bin/python -m pytest tests/models/sr/config tests/models/sr/adapters -q
.venv/bin/python -m pytest tests/models/trendline_family/test_import_boundaries.py -q
ruff check src/libs/models/sr tests/models/sr
.venv/bin/python -m compileall -q src/libs/models/sr
.venv/bin/python -c "from libs.models.sr import ClosedBar, SREngine; print('ok')"
rg -n "app\.sr|libs\.sr|pandas|numpy|polars" src/libs/models/sr tests/models/sr
git diff --check
```

Also run independent probes for:

1. direct break when `break_confirm_closes == 1`;
2. support and resistance fakeout symmetry;
3. touch then expiry on one bar;
4. confirmed break versus expiry priority;
5. frozen geometry across several transitions;
6. attempted duplicate-bar processing;
7. state/config/bar ownership mismatches.

## Mandatory Coder Handoff

Return a new coder-to-review handoff containing:

- branch and commit;
- exact files added/changed;
- transition-table implementation mapping;
- contract changes and compatibility impact;
- blast-radius/caller analysis;
- test and probe outputs;
- confirmation that the exact eight-parameter surface is unchanged;
- confirmation that no detector, association, persistence, retention pruning,
  feature, optimizer, or legacy migration code was added;
- known risks or intentionally deferred items.

Stop after the V1.1 implementation and handoff. Do not begin V1.2 without an
explicit Quant Review approval.
