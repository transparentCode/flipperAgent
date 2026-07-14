---
goal: Deliver SR-V1.2 causal detection and deterministic association for review
stage: coder-to-review
date_created: 2026-07-14
last_updated: 2026-07-15
owner: Coder Agent
status: Ready
tags: [handoff, quant, sr, detection, association, pivots, causality]
source_agent: Coder Agent
target_agent: Quant Review Agent
---

# Scope Executed

Implemented only the approved SR-V1.2 causal pivot detection, deterministic
candidate association, rolling detection buffer, and lifecycle-engine
integration from the orchestrator handoff.

Implementation branch:

```text
feature/sr-v1.2-detection-association
```

Implementation commit:

```text
4b6b77edc471328be45b7bce780f7cfefb749659
```

Follow-up hardening commit:

```text
bb4444b1c7c985173783f2f993dd149f5a959bba
```

Approved V1.1 base commit:

```text
5f3a0c78b67d6b4618a45272fc7ce0936a2699de
```

The branch has not been merged.

# Changes Made

## Contracts and state

- Added mandatory, finite, strictly positive `ClosedBar.atr_at_close`.
- Added mandatory immutable `SRState.recent_bars`.
- Added exact-bar type, aggregate ownership, unique-ID, strict-timestamp,
  and final-buffer-ID validation.
- Updated every SR `ClosedBar` and `SRState` construction site explicitly;
  no compatibility defaults were added.

## Pure detection

Added `libs.models.sr.detection.detect_confirmed_pivots` in:

```text
src/libs/models/sr/detection/__init__.py
src/libs/models/sr/detection/pivots.py
```

The detector uses only the final `2 * pivot_span_bars + 1` closed bars,
requires unique strict high/low extrema, confirms a pivot only on the final
bar, and emits support/resistance candidates in
`(formed_at, available_at, candidate_id)` order. Candidate geometry uses the
confirmation bar ATR and fails closed on scaled-width or final-bound overflow.

## Pure association

Added `libs.models.sr.association.match_candidate` in:

```text
src/libs/models/sr/association/__init__.py
src/libs/models/sr/association/matcher.py
```

The matcher validates exact types, ownership, finite geometry, and derived
threshold/distance values. It compares same-side zones only, includes only
caller-provided records, matches threshold equality, and selects the nearest
record by `(distance, zone_id)`. It never mutates an input.

## Engine integration

`SREngine.step(previous_state, closed_bar, resolved_config)` retains its public
signature and return shape. Processing order is:

1. Validate state/config ownership, chronology, recent-buffer bounds,
   duplicate/current-bar identity, lifecycle consistency, and pre-step active
   capacity.
2. Capture start-of-step active and breach-pending zone IDs.
3. Process existing lifecycle transitions.
4. Detect candidates from `previous_state.recent_bars + (closed_bar,)`.
5. Associate against updated start-of-step records, including records that
   became terminal, plus zones created earlier in the candidate batch.
6. Suppress matched candidates without changing the matched record.
7. Create unmatched active zones while active/breach-pending capacity remains;
   terminal records do not consume capacity and no eviction occurs.
8. Append created records/events, retain exactly the latest `2 * span` bars,
   and construct the canonical immutable state/snapshot/events.

New zones freeze candidate geometry, source, creation/availability times, ATR,
and resolved config hash. They start with age and interaction counters at zero;
their `CREATED` event uses the current confirmation bar ID and they cannot
undergo lifecycle processing on their availability bar.

## Tests and boundaries

Added detector, association, integrated-engine, contract, and SR import-boundary
regressions, including causal warmup, strict ties, confirmation ATR ownership,
same-bar terminal precedence, later terminal reuse, deterministic capacity,
same-batch created-zone suppression, overflow, duplicate/equal-time bars, and
bounded-buffer failures.

Completed review follow-ups:

- Controlled engine test forces two same-side candidates through one batch and
  verifies first-created-zone association suppresses second candidate.
- SR boundary test now allows only Python standard library, SR-internal
  imports, and YAML imports inside `adapters/yaml_config.py`.

Exact changed implementation/test files in commit `4b6b77e`:

```text
src/libs/models/sr/association/__init__.py
src/libs/models/sr/association/matcher.py
src/libs/models/sr/detection/__init__.py
src/libs/models/sr/detection/pivots.py
src/libs/models/sr/domain/contracts.py
src/libs/models/sr/lifecycle/engine.py
tests/models/sr/association/__init__.py
tests/models/sr/association/test_matcher.py
tests/models/sr/detection/__init__.py
tests/models/sr/detection/test_pivots.py
tests/models/sr/domain/test_contracts.py
tests/models/sr/lifecycle/test_engine.py
tests/models/sr/lifecycle/test_rules.py
tests/models/sr/test_import_boundaries.py
```

# Blast Radius Considered

The public SR domain contracts are intentionally breaking at construction
sites because ATR and causal history are mandatory. The existing lifecycle
engine is the only production execution path changed; it now calls the new
detector and matcher while preserving its approved public API. The rolling
buffer is retained in `SRState` only and is not added to snapshots or any
configuration surface.

Codebase-memory was reindexed after edits and reported the SR call/import
graph at 51,829 nodes and 169,513 edges. The tracked implementation scope is
limited to the files listed above; pre-existing `.codebase-memory` artifacts
and unrelated plan drafts remain unstaged.

# Validation Performed

All commands were run with the repository `.venv` where applicable:

```text
tests/models/sr -q                                      204 passed
tests/models/sr/domain tests/models/sr/detection
tests/models/sr/association tests/models/sr/lifecycle -q 144 passed
tests/models/sr/config tests/models/sr/adapters -q       55 passed
tests/models/trendline_family/test_import_boundaries.py  2 passed
ruff check src/libs/models/sr tests/models/sr             passed
compileall src/libs/models/sr                             passed
SR package and detector/matcher imports                   passed
git diff --check                                          passed
```

Independent probe passed for earliest causal confirmation, confirmation-bar
ATR ownership, two-sided creation, and the bounded rolling buffer. Focused
regressions also pass for tied extrema, width/merge/final-bound overflow,
same-bar terminal suppression, later-bar terminal reuse, deterministic
one-slot capacity, same-batch association suppression, duplicate/equal
timestamps, over-capacity preflight, and approved-import enforcement.

# Not Changed

- Exact eight-parameter configuration surface and YAML files.
- Resolver precedence, provenance, hashes, or runtime-override API.
- Legacy `app.sr` or `libs.sr` imports.
- ATR calculation, period/method/fallback/imputation logic.
- Detection variants, smoothing, scoring, volume, ranking, or quality logic.
- Persistence, replay, restart parity, gap/out-of-order recovery, or V1.3.
- Features, tuning, optimization, strategy, execution, risk, portfolio, or
  trading-readiness work.
- Terminal retention policy, MTF composition, regime/trendline integration,
  or legacy runtime migration.

# Risks or Follow-up Items

- `ClosedBar` and `SRState` callers outside the isolated SR package must now
  supply the mandatory causal ATR and rolling-buffer fields before any future
  integration work.
- General restart/replay/gap policy and bar-ID ordering for different bars
  sharing a timestamp remain explicitly deferred to SR-V1.3.
- Quant Review should retain existing independent verification of causal event
  interval, start-of-step association pool, capacity semantics, and overflow
  probes before promotion.

This handoff is complete enough for Quant Review to act without additional
implementation assumptions. V1.2 work stops here pending review approval.
