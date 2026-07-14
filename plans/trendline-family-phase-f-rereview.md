# Trendline Family Model — Phase F Re-review

## Current Mode

Quant re-review.

## Decision

**Revision required. Phase G remains blocked.**

The first Phase-F remediation closes the major tracker and typed-state defects. Role-reversal geometry is now frozen correctly on the reversal snapshot, pending reversal survives tracker-level dormancy/reactivation, retest control state is typed, close magnitude is bound to the persisted distance audit, threshold-one semantics are explicit, and event/transition fields are cross-checked.

Four narrow lifecycle/audit gaps remain before approval.

---

## Validation Reproduced

### Phase-F target suite

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py -q

214 passed
```

### Active RegimeV2, selection, and signal suite

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals -q

148 passed
```

One pre-existing OpenTelemetry deprecation warning remains.

### Static validation

```text
Ruff: passed
compileall: passed
git diff --check: passed
```

### Codebase-memory

```text
Users-aloobhujia-flipperAgent
40,183 nodes
127,849 edges
status: ready
```

The memory graph remains healthy. As in earlier phases, `detect_changes` does not enumerate the untracked canonical trendline-family package reliably, so source inspection and test execution remain the scope evidence of record.

---

# Verified Remediations

## Role-reversal geometry and anchors

Verified in the tracker:

- the provider may match a candidate in the new role;
- the reversal transition retains that candidate as continuity evidence;
- the reversal snapshot restores the prior exact `LineGeometry`;
- prior member ID, anchors, and member visibility timestamps are retained;
- both SUPPORT -> RESISTANCE and RESISTANCE -> SUPPORT tests pass.

## Tracker-level dormancy/reactivation deferral

Verified:

- an active pending reversal that becomes dormant is restored to the old role;
- the `RETEST_SUCCESS` event remains frozen with `pending_role_reversal=true`;
- reactivation preserves the old role for one snapshot;
- the next active update applies the reversal deterministically.

## Observation close-distance binding

`FamilyInteractionObservation` now enforces:

```text
abs(close_price - exact_line_price) / interaction_atr
    == distance_to_line_atr
```

when `close_price` is present.

## Typed retest lifecycle state

The following are now typed event fields rather than transition-driving metadata:

```text
retest_contact_seen
retest_confirmation_streak
retest_window_expired
role_reversal_applied
required_retest_confirmation_bars
```

Malformed values fail during contract construction.

## Event and transition cross-binding

For supplied transition records, the snapshot now binds:

```text
transition.from_state == event.previous_state
transition.to_state == event.state
transition.timestamp == event.updated_at
transition.trigger_observation_id == event.last_observation_id
transition.family_id == event.family_id
```

## Threshold semantics

Verified:

- `pressure_min_bars=1` enters `PRESSURING` on first qualifying contact;
- `rejection_recovery_bars=1` resolves on the first qualifying recovery bar;
- `retest_window_bars` has minimum `2`, matching the contact-plus-confirmation design.

## Compatibility projection

Typed shadow-only labels now exist and are projected from persisted event state without changing active RegimeV2 or selection behavior.

---

# Remaining Blocking Findings

## P0 — Canonical lifecycle still permits role reversal on a dormant family

Location:

```text
src/libs/models/trendline_family/event_lifecycle.py:
  advance_interaction_events
```

The function still checks an applied reversal before checking whether the resulting family is dormant:

```text
pending reversal + family_id in role_reversed_family_ids
    -> ROLE_REVERSED

DORMANT check
    -> reached afterward
```

Independent reproduction against the remediated implementation:

```text
dormant family lifecycle = DORMANT
role_reversed_family_ids  = {family_id}
result event state        = ROLE_REVERSED
```

The tracker currently avoids sending this combination after `_settle_pending_role_reversal_drafts`, but `advance_interaction_events` is the canonical public lifecycle engine and remains capable of producing the forbidden state. The snapshot contract also has no independent rule rejecting a `ROLE_REVERSED` event attached to a dormant family.

### Required correction

Enforce the invariant in both layers:

1. In `advance_interaction_events`, process dormancy before applied reversal or explicitly reject/defer any reversal request for a dormant family.
2. In `TrendlineFamilySnapshot`, reject:

```text
family.lifecycle_state == DORMANT
and event.state == ROLE_REVERSED
```

A dormant pending-reversal event must remain the prior frozen `RETEST_SUCCESS` event with the original role and pending intent.

### Required tests

- direct lifecycle call with dormant family + `role_reversed_family_ids` cannot produce `ROLE_REVERSED`;
- snapshot contract rejects a dormant `ROLE_REVERSED` event;
- tracker-level dormancy/reactivation regression remains green;
- both role directions.

---

## P0 — Phase-F event snapshots accept missing event-critical close evidence

Locations:

```text
src/libs/models/trendline_family/contracts.py:
  FamilyInteractionObservation
  TrendlineFamilySnapshot
```

`close_price=None` remains valid for Phase-E backward compatibility. That is correct for legacy snapshots without Phase-F events.

However, the same absence is also accepted in a snapshot containing an active Phase-F event. Independent reproduction:

```text
snapshot event:
  BREAK_PENDING -> BREAK_CONFIRMED

current typed observation:
  close_price = None

snapshot contract result:
  ACCEPTED
```

Retest-side and failed-break decisions rely on persisted close-side evidence. A Phase-F event snapshot must not claim causal event progression while omitting that evidence.

### Required correction

Preserve Phase-E compatibility conditionally:

- snapshots with no `interaction_events` and no event transitions may accept legacy observations with `close_price=None`;
- any snapshot containing Phase-F interaction events must require `close_price` on every current observation used by an active event;
- any event transition must require its trigger observation to contain `close_price`;
- dormant frozen events may reference older observations, but the current snapshot observations should still follow the normal Phase-D coverage contract.

Do not make `close_price` globally mandatory in `FamilyInteractionObservation`; enforce the Phase-F requirement at the snapshot/event boundary.

### Required tests

- real Phase-E snapshot with no events and absent `close_price` remains accepted;
- Phase-F active event with absent current `close_price` is rejected;
- event transition whose trigger observation lacks `close_price` is rejected;
- valid runtime Phase-F snapshots still serialize/replay.

---

## P1 — A changed event may be persisted without its audit transition

Location:

```text
src/libs/models/trendline_family/contracts.py:
  TrendlineFamilySnapshot
```

The contract validates every supplied transition, but it does not require a transition to exist when a persisted event changed state on the current snapshot.

Independent reproduction from a real tracker snapshot:

```text
event.previous_state = BREAK_PENDING
event.state          = BREAK_CONFIRMED
event.updated_at     = snapshot.timestamp
runtime transitions  = 1

replace interaction_event_transitions with ()
contract result      = ACCEPTED
```

The runtime engine emits the record correctly, but the persistence contract permits stripping the reason/counter audit record while leaving the state change.

### Required correction

For each non-frozen event updated at the snapshot timestamp:

```text
if event.previous_state is None:
    no transition is required  # new episode
elif event.previous_state == event.state:
    no transition is allowed/required
else:
    exactly one matching interaction-event transition is required
```

Dormant frozen events with `event.updated_at < snapshot.timestamp` remain exempt.

Also reject a supplied transition for an event that did not change state.

### Required tests

- changed current event with no transition is rejected;
- changed current event with two transitions is rejected;
- unchanged event with a transition is rejected;
- new episode with `previous_state=None` requires no transition;
- dormant frozen event requires no current transition;
- valid tracker snapshots remain accepted.

---

## P1 — Compatibility labels expose a one-close breakout/breakdown

Location:

```text
src/libs/models/trendline_family/events.py:
  compatibility_label
```

The compatibility projection currently maps `BREAK_PENDING` to:

```text
SUPPORT    -> breakdown
RESISTANCE -> breakout
```

`BREAK_PENDING` exists after the first close beyond the zone. Therefore the compatibility namespace reports `breakout`/`breakdown` before the configured multi-close confirmation has reached `BREAK_CONFIRMED`.

Independent reproduction:

```text
first CLOSE_BEYOND
  event state         = BREAK_PENDING
  confirmation streak = 1 of 2
  compatibility label = breakdown
```

Although the field is shadow-only, this conflicts with the Phase-F exit gate:

```text
no one-close-only primary breakout path
```

A compatibility field should not collapse an explicitly pending state into a confirmed breakout label.

### Required correction

Return `None` for `BREAK_PENDING`.

Emit breakout/breakdown only for confirmed post-break states, for example:

```text
BREAK_CONFIRMED
RETEST_PENDING
RETEST_SUCCESS
ROLE_REVERSED  # if the chosen compatibility semantics require it
```

Keep `FAILED_BREAK` explicit or `None`; do not label it as a successful breakout.

Keep bounce/rejection mapping for `REJECTING` role-mirrored and shadow-only.

### Required tests

- first close -> `BREAK_PENDING` and compatibility label `None`;
- configured confirmation -> breakout/breakdown label appears;
- support/resistance mirror symmetry;
- failed break does not retain a successful-break label;
- compatibility projection remains excluded from active decisions.

---

# Non-blocking Hardening Note

The observation records absolute close distance, so two close values mirrored around the exact line can share the same distance while producing different retest-side decisions. `close_price` itself is currently the canonical signed-side evidence.

A future persistence-hardening change may add a typed signed-distance or close-side audit field. This re-review does not make that broader schema addition a blocker because the prior remediation requirement explicitly required the absolute-distance binding and the runtime observation ID includes `close_price`.

---

# Blast Radius

Expected production changes are limited to:

```text
src/libs/models/trendline_family/contracts.py
src/libs/models/trendline_family/event_lifecycle.py
src/libs/models/trendline_family/events.py
```

Expected tests:

```text
tests/models/trendline_family/test_event_lifecycle.py
```

A separate contract-focused test file is acceptable if it improves clarity.

No tracker redesign should be required. Do not modify signal-pipeline or projected-worker behavior.

---

# Required Validation

Run:

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py -q
```

Run:

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals -q
```

Run:

```text
ruff check \
  src/libs/models/trendline_family \
  src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py \
  src/apps/signal_app/pipeline/regime.py \
  src/apps/signal_app/runtime/worker.py \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py
```

Run:

```text
PYTHONPATH=src .venv/bin/python -m compileall -q \
  src/libs/models/trendline_family \
  src/libs/models/regime_v2/adapters \
  src/apps/signal_app/pipeline \
  src/apps/signal_app/runtime

git diff --check
```

Reindex codebase-memory and report project, nodes, edges, and status.

---

# Codex Remediation Prompt

```text
Apply the final Phase-F remediation only using:

- plans/trendline-family-phase-f-rereview.md
- plans/trendline-family-phase-f-review.md
- plans/trendline-family-phase-e-approval.md
- plans/trendline-family-codex-phase-execution-plan.md
- plans/trendline-family-model-architecture-plan.md

Do not start Phase G.

Close only these remaining gaps:

1. The canonical event lifecycle and snapshot contract must never permit ROLE_REVERSED on a dormant family.
2. Phase-E legacy snapshots may omit close_price only when no Phase-F events exist; active Phase-F events and event transitions require persisted close_price evidence.
3. Every current-bar event state change must have exactly one matching event transition; unchanged/new/frozen events must follow explicit transition-count rules.
4. BREAK_PENDING must not project breakout/breakdown compatibility labels before configured close confirmation.

Preserve all verified remediation behavior:

- exact geometry/member/anchor preservation on the reversal snapshot;
- tracker-level dormant/reactivation deferral;
- typed retest fields;
- absolute close-distance binding;
- threshold-one pressure/recovery semantics;
- retest-window minimum 2;
- shadow-only Phase-E isolation;
- projected-lane exactly-once updates;
- active RegimeV2 and selection invariance.

Expected production scope:

- src/libs/models/trendline_family/contracts.py
- src/libs/models/trendline_family/event_lifecycle.py
- src/libs/models/trendline_family/events.py

Add focused adversarial tests under tests/models/trendline_family.

Run all validation commands in the re-review document, reindex codebase-memory, return the mandatory Phase-F completion report, and stop.
```

---

## Approval Gate

Phase F can be approved when:

- dormant reversal is impossible at both lifecycle and snapshot boundaries;
- event-critical close evidence is mandatory only when Phase-F events require it;
- event state changes and transition records have exact one-to-one audit coverage;
- compatibility labels appear only after confirmed break semantics;
- all current and new adversarial tests pass;
- Phase-E decision invariance remains unchanged;
- no Phase-G work is present.
