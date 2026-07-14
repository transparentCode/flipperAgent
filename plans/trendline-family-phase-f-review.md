# Trendline Family Model — Phase F Review

## Current Mode

Quant review.

## Decision

**Revision required. Phase G remains blocked.**

The Phase-F implementation has the correct broad architecture: events consume typed Phase-D observations, event and transition state are persisted in immutable snapshots, multi-close break confirmation is causal, Phase-E remains shadow-only, and the active RegimeV2/signal regression suites are unchanged.

However, the role-reversal identity boundary, dormant/reactivation behavior, event-critical persistence contracts, and minimum-threshold semantics still contain blocking defects. The current tests do not exercise these cases.

---

## Validation Reproduced

### Trendline-family, RegimeV2 adapters, and projected shadow runtime

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py -q

206 passed
```

### Active RegimeV2, legacy trendline, selection, and signal suites

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
40,146 nodes
127,741 edges
status: ready
```

---

# Blocking Findings

## P0 — Role reversal can rewrite the representative geometry and anchors

Locations:

```text
src/libs/models/trendline_family/tracker.py
  _apply_pending_role_reversals
  _matched_draft
  _mark_role_reversal_drafts
```

The family role is reversed before matching. If the provider emits a valid candidate in the new role, normal matching replaces the representative member from that candidate on the same reversal update.

Independent tracker reproduction:

```text
role: SUPPORT -> RESISTANCE
family_id_stable: true
member_id_stable: true
geometry_stable: false
anchors_stable: false
matched_candidate: new-role-match
family_transition: ROLE_REVERSED
```

The representative changed from:

```text
reference_time  = 2024-01-02T00:00:00Z
reference_price = 100.0
```

to:

```text
reference_time  = 2024-01-02T01:00:00Z
reference_price = 100.2
```

This violates the locked Phase-F rule that role reversal preserves the existing family/member/representative geometry/anchors. The current role-reversal regression uses an old-role provider candidate that is suppressed, so it cannot expose this path.

### Required correction

On the update that applies a scheduled role reversal:

- preserve the previous representative `LineGeometry` exactly;
- preserve the previous member anchors exactly;
- preserve family ID and member ID;
- preserve the historical member first/last-seen semantics according to one documented rule;
- do not let a new-role candidate refit the line on the reversal-application bar.

A matching candidate may be used only for match/lifecycle evidence if necessary, but the reversal snapshot must retain the prior exact geometry and anchors. Normal geometry updates may resume on a later confirmed update under an explicit tested rule.

Add both directions:

```text
SUPPORT -> RESISTANCE with a matchable new-role candidate
RESISTANCE -> SUPPORT with a matchable new-role candidate
```

Assert exact geometry and anchor equality across the reversal snapshot.

---

## P0 — Pending role reversal is inconsistent with dormancy and reactivation

Locations:

```text
src/libs/models/trendline_family/tracker.py:_apply_pending_role_reversals
src/libs/models/trendline_family/event_lifecycle.py:advance_interaction_events
```

Two contradictory paths are currently possible.

### A. A dormant family can be role-reversed

The lifecycle checks the applied reversal before checking `DORMANT`.

Independent reproduction:

```text
event state: ROLE_REVERSED
family lifecycle: DORMANT
```

This violates the Phase-F rule that no role reversal is applied while the family is dormant.

This can occur when the prior family was active with `RETEST_SUCCESS`, reversal is applied before matching, and the current family draft becomes dormant through unmatched lifecycle or active-cap enforcement on the same update.

### B. A frozen pending reversal cannot resume after reactivation

For a previous dormant family, `_apply_pending_role_reversals()` skips reversal before matching. If matching then reactivates the family on the current update, the event engine sees an active `RETEST_SUCCESS` event whose pending reversal was not applied and fails:

```text
ContractValidationError:
active pending role reversal was not applied before event advancement
```

This violates the required dormant behavior:

```text
dormant -> freeze
reactivate -> resume deterministically
```

### Required correction

Define one deterministic policy and encode it in tracker ordering. Recommended:

- a family that is dormant in the previous snapshot does not reverse before matching;
- if it reactivates on the current bar, preserve `RETEST_SUCCESS` and the pending reversal for this snapshot;
- apply the reversal on the next confirmed update if the family remains active;
- if an active pending-reversal family would become dormant on the reversal bar, defer the reversal and retain the old role/event intent rather than producing `ROLE_REVERSED` in a dormant snapshot;
- expiry removes the event without applying reversal.

Alternative semantics are acceptable only if they preserve causality, allow deterministic reactivation, and never persist `ROLE_REVERSED` on a dormant family.

Required tests:

- pending reversal -> dormant freeze;
- dormant pending reversal -> reactivation;
- active pending reversal -> same-bar unmatched dormancy;
- active pending reversal -> active-cap dormancy;
- pending reversal -> expiry;
- both role directions.

---

## P0 — Event-critical close evidence is not bound to the persisted observation

Location:

```text
src/libs/models/trendline_family/contracts.py:FamilyInteractionObservation
```

Phase F added `close_price`, and failed-break/retest decisions trust it. The contract validates `close_price` against the zone only for `CLOSE_BEYOND`. It does not bind it to the already persisted close-derived distance fields.

Independent reproduction from one valid `IN_ZONE` observation:

```text
original close_price = 99.9
exact_line_price     = 100.0
distance_to_line_atr = 0.1

replace close_price with 50.0  -> accepted
replace close_price with 150.0 -> accepted
```

The event engine can therefore see a close on the opposite side of the zone while the same observation reports unchanged `IN_ZONE` state and close-distance audit fields.

### Required correction

When `close_price` is present, validate at least:

```text
abs(close_price - exact_line_price) / interaction_atr
    == distance_to_line_atr
```

within the established interaction tolerance.

The existing `distance_to_zone_atr` relation must remain valid through that binding. Preserve Phase-E backward compatibility for legacy observations with `close_price` absent.

Add adversarial tests for both roles and all observation states, especially retest/failed-break inputs.

---

## P0 — Retest lifecycle state is stored in untyped metadata

Locations:

```text
src/libs/models/trendline_family/event_lifecycle.py
src/libs/models/trendline_family/contracts.py:FamilyInteractionEvent
```

The following state-machine values affect future transitions but are stored in free-form metadata:

```text
retest_contact_seen
retest_confirmation_streak
retest_window_expired
role_reversal_applied
```

The contract accepts malformed lifecycle state:

```text
retest_contact_seen = "truthy-string"
retest_confirmation_streak = "not-an-int"
```

The next confirmed update then raises an uncaught `ValueError` while converting the streak to `int`.

### Required correction

Move event-critical lifecycle values into typed fields, at minimum:

```text
retest_contact_seen: bool
retest_confirmation_streak: int | None
```

Validate them with explicit state-specific invariants. Descriptive audit metadata may remain free-form, but no value that controls a future transition may be read from untyped metadata.

All malformed persisted lifecycle values must fail during contract decoding/snapshot validation, before event advancement or repository persistence.

---

## P1 — Event and transition contracts accept impossible causal histories

Locations:

```text
src/libs/models/trendline_family/contracts.py
  FamilyInteractionEvent
  FamilyInteractionEventTransition
  TrendlineFamilySnapshot
```

Independent event-contract probes accepted:

```text
BREAK_CONFIRMED with:
  previous_state = FAR
  break_pending_at = None

RETEST_SUCCESS with:
  previous_state = IN_ZONE
  synthetic break/retest timestamps

ROLE_REVERSED with:
  previous_state = FAR
  no prior RETEST_SUCCESS evidence
```

A final role-reversal snapshot also accepted all of these audit contradictions together:

```text
event.previous_state != transition.from_state
event.last_observation_id != transition.trigger_observation_id
transition.timestamp != event.updated_at
```

### Required correction

Strengthen state-specific event invariants:

- `BREAK_CONFIRMED` requires `previous_state == BREAK_PENDING`, a non-null `break_pending_at`, and the configured consecutive close streak;
- `RETEST_PENDING` requires prior `BREAK_CONFIRMED` or `RETEST_PENDING` as appropriate;
- `RETEST_SUCCESS` requires `previous_state == RETEST_PENDING`, typed retest contact evidence, and the configured confirmation streak;
- `FAILED_BREAK` requires a valid post-break predecessor;
- `ROLE_REVERSED` requires `previous_state == RETEST_SUCCESS` and prior pending reversal evidence;
- state-specific timestamps/counters must be mutually coherent.

For an event transition persisted on the current bar, the snapshot must enforce:

```text
transition.family_id == event.family_id
transition.from_state == event.previous_state
transition.to_state == event.state
transition.timestamp == event.updated_at
transition.trigger_observation_id == event.last_observation_id
```

For active events advanced at the snapshot timestamp, `event.last_observation_id` must reference the current same-family observation. Dormant frozen events may retain an older observation ID and older `updated_at`; encode this exception explicitly rather than weakening all active-event validation.

Add every adversarial contract case required by the Phase-F handoff.

---

## P1 — Valid one-bar threshold settings are ignored on state entry

Locations:

```text
src/libs/models/trendline_family/event_lifecycle.py
  _new_event
  _advance_recovery
  BREAK_CONFIRMED handling
```

The config accepts minimum `1` for the event thresholds, but first-entry logic does not evaluate those thresholds.

Independent reproduction:

```text
pressure_min_bars = 1
first contact -> IN_ZONE, pressure_bars=1
expected threshold state -> PRESSURING
```

```text
rejection_recovery_bars = 1
first away bar after pressure -> REJECTING, rejection_bars=1
expected recovery threshold to be applied on that bar
```

```text
retest_window_bars = 1
retest_confirmation_bars = 1
first valid post-break retest bar -> RETEST_PENDING, streak=0
```

The last case may intentionally require a distinct `RETEST_PENDING` snapshot, but then the configuration minimums and window semantics must be adjusted so a one-bar setting is not misleading or impossible.

### Required correction

Either:

1. Make the configured threshold effective on the first qualifying bar; or
2. Raise the minimum for any parameter whose state machine inherently requires more than one bar and document the exact counting convention.

Add independent parameter-effect tests proving that each setting changes only its intended event behavior.

---

## P1 — Required compatibility labels are missing

The approved Phase-F scope requires a compatibility mapping to simple:

```text
breakout
breakdown
bounce/rejection
```

No implementation or tests for this mapping were found in the trendline-family package or shadow adapter.

### Required correction

Add a pure compatibility projection from persisted event state and role. It must not alter event state, family state, RegimeV2 policy, or selection behavior.

Use stable typed/constant labels and explicit `None` when no compatibility label applies.

---

# Test Coverage Gap

The Phase-F work adds one lifecycle test file. It does not yet provide the required exhaustive coverage for:

- every allowed and forbidden transition;
- event/transition causal contract forgery;
- new-role candidate geometry preservation;
- pending reversal across dormancy/reactivation/expiry;
- minimum and independent parameter effects;
- malformed typed retest state;
- event-specific deterministic replay and future-row invariance;
- compatibility labels;
- transition ID sensitivity to every transition field.

The existing green Phase-E replay and decision-invariance tests remain valuable, but they do not substitute for event-state-specific acceptance tests.

---

# Verified Correct and Must Be Preserved

- Phase-D observations remain the event engine input; OHLCV is not reclassified in the lifecycle module.
- Exact line and interaction-zone concepts remain separate in the normal path.
- Primary break confirmation requires consecutive confirmed `CLOSE_BEYOND` observations and a minimum configured count of two.
- An interrupted close-beyond streak is reset.
- Event IDs are deterministic and stable across the tested non-terminal episode.
- Snapshot identity includes events and event transitions.
- Failed-break direction is support/resistance mirrored in the tested path.
- Role reversal preserves family and member IDs in the tested path.
- Phase-E optional import, fail-soft, projected-lane caching, and shadow isolation remain green.
- Incomplete projected bars do not advance the tracker.
- Active RegimeV2, legacy trendline, selection, risk, and execution behavior remain unchanged.
- No Phase-G multi-rail, MTF, optimization, or promotion work was introduced.

---

# Blast Radius

Expected remediation scope:

```text
src/libs/models/trendline_family/contracts.py
src/libs/models/trendline_family/events.py
src/libs/models/trendline_family/event_lifecycle.py
src/libs/models/trendline_family/tracker.py
src/libs/models/trendline_family/features.py
src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py
configs/trendline_family.yaml        # only if threshold minimum/default semantics change
tests/models/trendline_family/
```

Signal pipeline and worker changes should not be necessary. The approved Phase-E projected-lane integration should remain untouched unless a regression test exposes a direct interface issue.

---

# Required Remediation Acceptance

Before Phase-F approval, demonstrate:

1. New-role candidates cannot mutate geometry or anchors on the reversal-application snapshot.
2. No dormant snapshot can contain a newly applied role reversal.
3. Pending reversal survives dormancy and resumes after deterministic reactivation.
4. Event-critical close and retest evidence is fully typed and contract-bound.
5. Forged BREAK_CONFIRMED, RETEST_SUCCESS, FAILED_BREAK, and ROLE_REVERSED histories are rejected.
6. Current event transitions bind exactly to the persisted event and observation.
7. Every event threshold has tested, documented boundary semantics.
8. Compatibility labels are projected without active decision consumption.
9. Event-specific replay, future-row invariance, and role symmetry pass.
10. All existing 206 Phase-F target tests and 148 active regression tests remain green.

---

# Recommended Handoff

Return to Phase-F implementation only. Do not begin Phase G.

Use this review together with:

```text
plans/trendline-family-phase-e-approval.md
plans/trendline-family-codex-phase-execution-plan.md
plans/trendline-family-model-architecture-plan.md
```
