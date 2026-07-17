---
goal: Hand off the implemented deterministic SR-V1.1 lifecycle for Quant Review
stage: coder-to-review
date_created: 2026-07-14
last_updated: 2026-07-14
owner: Codex Quant Coder
status: Ready
tags: [handoff, quant, sr, lifecycle, state-machine, causality]
source_agent: Codex Quant Coder
target_agent: Quant Reviewer
---

# Coder To Review: SR-V1.1 Lifecycle v1

## Scope Executed

Implemented only the lifecycle phase specified by the approved orchestrator
handoff. The work is on `feature/sr-v1.1-lifecycle` at commit
`4656001b56487a78c738951e69a8ba326054924b`, based directly on approved V1.0
commit `8c865617fbda5ff107b5d4547e2c0073ce655c9e`. No merge was performed.

## Changes Made

Exact committed files:

- `src/libs/models/sr/domain/contracts.py`
  - Added immutable `ClosedBar` with strict state-key, timestamp, and OHLC
    validation.
  - Added mandatory non-negative `age_bars` to `ZoneRuntimeState`.
  - Enforced pending-breach/status invariants.
- `src/libs/models/sr/domain/__init__.py`
  - Exported `ClosedBar`.
- `src/libs/models/sr/__init__.py`
  - Exported `ClosedBar` and `SREngine`.
- `src/libs/models/sr/lifecycle/__init__.py`
  - Added the lifecycle package boundary.
- `src/libs/models/sr/lifecycle/rules.py`
  - Added pure `touches_zone` and `breaches_zone` predicates using frozen
    geometry and `atr_at_creation`.
- `src/libs/models/sr/lifecycle/engine.py`
  - Added stateless `SREngine.step` orchestration, precondition checks, zone
    transitions, event creation, immutable state reconstruction, and snapshot
    output.
- `tests/models/sr/domain/test_contracts.py`
  - Added `ClosedBar`, age, and pending-status adversarial coverage.
- `tests/models/sr/domain/test_identity.py`
  - Updated existing runtime construction sites for mandatory `age_bars`.
- `tests/models/sr/lifecycle/__init__.py`
- `tests/models/sr/lifecycle/test_rules.py`
- `tests/models/sr/lifecycle/test_engine.py`
  - Added rule, transition, chronology, terminal, ownership, immutability,
    determinism, and event-audit regression coverage.

### Transition implementation mapping

- `ACTIVE` eligible bar increments age, evaluates strict side-aware breach
  first, then touch, then applies expiry if still non-terminal.
- First breach emits `BREACH_STARTED`; confirmation count one emits
  `BREAK_CONFIRMED` immediately, otherwise state becomes `BREACH_PENDING` with
  count one.
- `BREACH_PENDING` increments consecutive breach count, confirms at the
  configured threshold, or emits one `FALSE_BREAKOUT` and returns `ACTIVE`.
- `BROKEN` and `EXPIRED` remain unchanged, retained, and inert.
- Expiry clears pending count and runs after interaction; confirmed breaks win
  over expiry.
- Eligible runtime timestamps, interaction timestamps, counters, event prices,
  event bar IDs, and canonical snapshot ordering follow the handoff contract.

## Contract Compatibility Impact

`ZoneRuntimeState.age_bars` is mandatory, so all existing SR construction sites
and tests were updated explicitly; no hidden numeric default was added.
`ClosedBar` and `SREngine` are additive public exports. Zone definitions and
geometry remain reused and content-identical across transitions. V1.0 identity,
configuration, YAML, snapshot, and import-boundary behavior remains unchanged.

The approved configuration surface remains exactly eight paths:

- `detection.pivot_span_bars`
- `detection.zone_half_width_atr`
- `association.merge_distance_atr`
- `lifecycle.touch_tolerance_atr`
- `lifecycle.break_buffer_atr`
- `lifecycle.break_confirm_closes`
- `lifecycle.max_age_bars`
- `runtime.max_active_zones`

V1.1 reads only the four lifecycle paths. No configuration fields or YAML
values were added.

## Blast Radius Considered

The public flow is now:

```text
SRState + ClosedBar + ResolvedSRConfig
    -> SREngine.step
    -> SRState + SRSnapshot + canonical snapshot.events
```

Codebase-memory tracing identified the new `SREngine.step` construction path as
the production caller of `SRState` and `ZoneRuntimeState`; no pre-existing
production lifecycle callers were found. Existing domain/config tests and the
package import surface were rerun. No legacy SR, persistence, strategy, or
trading flow was connected.

## Validation Performed

All required gates passed on this commit:

- `.venv/bin/python -m pytest tests/models/sr -q` — **147 passed**
- `.venv/bin/python -m pytest tests/models/sr/domain tests/models/sr/lifecycle -q` — **90 passed**
- `.venv/bin/python -m pytest tests/models/sr/config tests/models/sr/adapters -q` — **55 passed**
- `.venv/bin/python -m pytest tests/models/trendline_family/test_import_boundaries.py -q` — **2 passed**
- `ruff check src/libs/models/sr tests/models/sr` — passed
- `.venv/bin/python -m compileall -q src/libs/models/sr` — passed
- package import probe for `ClosedBar` and `SREngine` — `ok`
- `git diff --check` — passed
- independent lifecycle probes — **7 passed**

The required forbidden-import search found only the intentional `pandas`
module-name literals in `tests/models/sr/adapters/test_import_boundaries.py`;
there were no forbidden imports in production SR code.

Independent probes covered direct confirmation, support/resistance fakeout
symmetry, touch-plus-expiry, break-over-expiry precedence, frozen geometry,
duplicate-bar rejection, and ownership mismatch rejection.

## Not Changed

No detector, candidate creation, association/merge, ranking/eviction,
persistence, replay/restart, general out-of-order handling, duplicate-bar
idempotence, terminal pruning/retention, role reversal, breakout/retest,
multi-timeframe composition, regime/trendline integration, features, scores,
ML, optimization, trading policy, migration, or legacy `libs.sr` integration
was added.

The V1.0 signature regression asserting that `runtime_override` is absent from
`SRConfigResolver.resolve` remains in the approved base commit.

## Risks Or Follow-Up Items

- General bar ordering, restart parity, and idempotent replay remain deferred
  to the explicitly scoped later phase.
- Terminal zones are retained in state and snapshots; retention belongs to the
  planned persistence/retention phase.
- No tuned hyperparameters or market-quality claims are made; the engine is a
  deterministic contract implementation only.
- Quant Review should independently verify same-bar canonical event ordering
  and the listed ownership/chronology probes before approving V1.2 work.

This package is complete and actionable for Quant Review. V1.2 work is not
started.
