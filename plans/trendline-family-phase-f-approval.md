# Trendline Family Model — Phase F Approval

## Current Mode

Quant approval.

## Approval Scope

Phase F deterministic persistent interaction-event lifecycle, including:

- typed multi-bar event states derived only from persisted Phase-D observations;
- stable deterministic event identity across one interaction episode;
- consecutive-close break confirmation;
- pressure and rejection recovery;
- wick, body and close penetration maxima;
- bounded retest handling and explicit retest expiry;
- causal failed-break detection;
- delayed role reversal preserving family, member, exact geometry and anchors;
- dormant-event freezing and deterministic reactivation deferral;
- immutable event and event-transition snapshot persistence;
- compact additive event features and compatibility labels under the existing shadow namespace;
- replay, future-row and projected-lane invariance;
- continued isolation from active RegimeV2, selection, risk and execution.

## Approval Decision

**Approved. Phase G may begin.**

No unresolved Phase-F blocker remains.

## Blocking Issues

None.

## Final Remediation Verification

### Dormant role-reversal safety

The canonical event lifecycle now processes dormancy before any scheduled role reversal.

A dormant family with a pending reversal:

```text
remains RETEST_SUCCESS
retains pending_role_reversal = true
retains the original role
emits no event transition
cannot become ROLE_REVERSED
```

The snapshot contract independently rejects a `ROLE_REVERSED` event attached to a dormant family. Tracker-level dormancy, reactivation and next-active-update reversal behavior remains deterministic.

### Event-critical close evidence

Phase-E compatibility remains conditional:

- event-free legacy snapshots may deserialize observations with `close_price=None`;
- active current Phase-F events require a current same-family observation containing `close_price`;
- every event transition requires its trigger observation to contain `close_price`;
- dormant frozen events remain exempt from a current-transition requirement.

This preserves old event-free snapshot compatibility without permitting Phase-F event progression to omit the close evidence used by retest and failed-break logic.

### Exact transition audit coverage

For every persisted event updated at the current snapshot timestamp:

```text
previous_state is None
-> new episode
-> no transition permitted

previous_state == state
-> unchanged event
-> no transition permitted

previous_state != state
-> exactly one matching transition required
```

Frozen events cannot carry current transitions. Supplied transitions remain bound to the persisted event, family, timestamp, previous state, resulting state and trigger observation.

### Confirmed compatibility labels

`BREAK_PENDING` now projects no breakout or breakdown label.

The compatibility projection begins only after `BREAK_CONFIRMED`:

```text
confirmed former SUPPORT break    -> breakdown
confirmed former RESISTANCE break -> breakout
support rejection                 -> bounce
resistance rejection              -> rejection
```

`FAILED_BREAK` and unrelated states project no confirmed break label.

## Phase-F Guarantees

The approved implementation now guarantees:

- event state advances only from ordered confirmed-bar observations;
- incomplete and future bars cannot advance event counters;
- the configured primary break path requires at least two consecutive closes;
- interrupted close streaks do not combine into a later confirmation;
- pressure and rejection thresholds take effect according to their documented entry counting;
- the retest window has enough capacity for distinct contact and confirmation semantics;
- retest progression uses typed persisted fields rather than free-form metadata;
- failed breaks are detected causally from current confirmed evidence;
- role reversal is scheduled by `RETEST_SUCCESS` and applied on a later confirmed active update;
- reversal preserves family ID, member ID, exact `LineGeometry` and anchors;
- a matchable new-role candidate can provide continuity evidence but cannot refit geometry on the reversal snapshot;
- dormant events freeze without advancing pressure, confirmation or retest counters;
- reactivation defers a pending reversal for one active snapshot and resumes deterministically;
- expiry removes the current event rather than applying a pending reversal;
- event and transition identities are deterministic in normal runtime generation;
- snapshot identity includes complete persisted event and transition state;
- runtime event evidence remains separate from future outcome labels and trading policy;
- compatibility labels remain pure additive shadow projections;
- no Phase-F field is consumed by active RegimeV2, probability, overlay, MoE, MTF, selection, risk or execution logic.

## Validation Sufficiency

### Trendline-family suite

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family -q

194 passed
```

### Phase F plus shadow integration

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py -q

221 passed
```

### Active RegimeV2, selection and signal regression

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals -q

148 passed
```

One unrelated OpenTelemetry deprecation warning remains.

### Independent adversarial probes

Verified outside the normal tracker happy path:

- dormant family plus an applied-reversal request returns the frozen `RETEST_SUCCESS` event and no transition;
- removing the transition from a real `BREAK_PENDING -> BREAK_CONFIRMED` snapshot is rejected;
- replacing a real Phase-F trigger observation with `close_price=None` is rejected;
- an event-free legacy snapshot with `close_price=None` remains accepted;
- `BREAK_PENDING` has no compatibility label;
- `BREAK_CONFIRMED` produces the correct role-mirrored label.

### Static validation

```text
ruff check \
  src/libs/models/trendline_family \
  src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py \
  src/apps/signal_app/pipeline/regime.py \
  src/apps/signal_app/runtime/worker.py \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py

All checks passed
```

```text
PYTHONPATH=src .venv/bin/python -m compileall -q \
  src/libs/models/trendline_family \
  src/libs/models/regime_v2/adapters \
  src/apps/signal_app/pipeline \
  src/apps/signal_app/runtime

Passed
```

```text
git diff --check

Passed
```

## Blast Radius Confirmation

Phase F remains confined to the canonical trendline-family contracts, event lifecycle, tracker integration, feature projection, shadow adapter, configuration and tests.

No Phase-G source concepts were found:

```text
multi-rail grouping
rail identities
rail offsets
family corridor
spacing stability
```

No legacy trendline runtime import was introduced.

No active probability, overlay, MoE, MTF, selection, strategy, risk or execution behavior changed.

Codebase-memory:

```text
Users-aloobhujia-flipperAgent
40,220 nodes
127,796 edges
status: ready
```

`detect_changes` continues to under-report the untracked canonical trendline-family package. Direct source inspection, complete targeted test execution and the ready memory graph are the scope evidence of record.

## Residual Risk

Acceptable deferred risks:

- the production repository remains in-memory;
- historical-market shadow artifact inspection and event calibration have not yet been run;
- long-duration event-state churn, latency and memory behavior remain unmeasured;
- the worktree still contains untracked canonical package, test and plan files, so the eventual commit must explicitly include the complete Phase A–F source/config/test/document set;
- persistent-database migration, corruption hardening and repository recovery semantics remain deferred;
- root collection and broad unrelated legacy lint issues remain independently tracked.

These risks do not block Phase G implementation.

## Phase G Boundary

Phase G may represent related approximately parallel exact lines as coherent multi-rail families.

Required concepts:

- representative family slope;
- exact member rails;
- stable rail/member identities;
- deterministic ordered rail semantics;
- rail offsets normalized by ATR;
- spacing-stability diagnostics;
- a family corridor;
- current rail position;
- candidate family confidence;
- singleton families remaining valid;
- deterministic continuity across confirmed updates.

Required separation:

```text
family corridor       != interaction zone
interaction zone      != uncertainty envelope
uncertainty envelope  != exact line
```

Forbidden Phase-G scope:

- MTF composition;
- horizontal zones;
- learned clustering;
- complex split/merge graph optimization unless strictly required by a test;
- projection scenarios;
- optimizer search or promotion;
- probability, overlay, MoE, selection, risk or execution consumption;
- replacement of the existing active legacy trendline path;
- weakening any approved Phase-F event, role-reversal, replay or shadow-isolation invariant.

Stop for review after Phase G implementation and tests.
