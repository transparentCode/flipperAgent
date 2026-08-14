---
goal: Prove the approved decision_app D0-D6 runtime with the representative stateful SR model adapter
stage: coder-to-orchestrator
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, decision-app, d7, sr, real-model-adapter]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Coder-to-orchestrator — `decision_app` D7A SR real adapter

## Result

D7A is complete in the cumulative D0-D6 worktree. The existing SR core remains
independent of `decision_app`; the new adapter is a thin semantic plugin boundary
and uses the approved D1-D6 contracts. D7B was deliberately deferred because no
reviewed plugin-ready stateless model was available on this base. No D8 work was
started.

Terminal status:

```text
DECISION_APP_D7A_SR_REAL_ADAPTER_READY_FOR_REVIEW
```

## Starting state

- HEAD: `4fc0de62515112dc371e08a6cde503746c54f7f7`
- Worktree: `/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0`
- Branch: detached HEAD, no commit/merge/push/branch operation performed.
- The cumulative D0-D6 source, tests, and handoffs were already present as
  untracked worktree content. The pre-existing tracked changes were the SR
  package initializer and SR import-boundary test; unrelated cumulative work was
  preserved.

## Files and symbols changed

### Production

- `src/apps/decision_app/real_features.py`
  - `SR_ATR_DEFINITION` and bounded ATR constants.
  - `calculate_sr_atr()` implements the established batch ATR recurrence over
    exactly 15 causal decision-timeframe bars.
  - No I/O, infrastructure, model execution, or mutable indicator state.
- `src/libs/models/sr/adapters/decision_plugin.py`
  - `SR_MODEL_SPEC`.
  - `SRDecisionPlugin` with `data_requests()` and `evaluate()`.
  - `to_sr_closed_bar()` and deterministic `_canonical_bar_id()`.
  - Explicit bounded SR snapshot/zone/event evidence projection.
  - `encode_state()` / `decode_state()` state boundary.
- `src/libs/models/sr/adapters/__init__.py`
  - Exports the SR plugin identity/spec/class.

### Tests

- `tests/decision/test_real_sr_plugin.py`
  - SR runtime catalog construction and exact ModelSpec checks.
  - ATR feature parity and history isolation.
  - causal closed-bar conversion and deterministic identity.
  - encoded state/config identity validation and malformed ATR rejection.
  - direct `SREngine` versus plugin parity.
  - D6 causal rewarm and LIVE prepare/abort/commit transaction proof.
  - out-of-order rewarm, post-abort rewarm requirement, analytical output,
    artifact identity, and import-boundary checks.
- `tests/models/sr/test_import_boundaries.py`
  - Allows only the approved shared semantic-contract import for the new adapter;
    the SR core import boundary remains enforced.

## Adapter architecture and exact ModelSpec

The runtime path is:

```text
DecisionContext
  -> binding-visible ATR FeatureSnapshot
  -> causal closed CausalBarView
  -> SR ClosedBar
  -> decode_state() / create_initial_state()
  -> SREngine.step()
  -> bounded ModelArtifact + encoded proposed_next_state
```

The SR model specification is:

```text
name                         = sr
version                      = 1
stateful                     = true
output_kind                  = analytical
produces_artifact_type       = sr.snapshot.v1
supported_trigger_modes      = (on_bar_close,)
intrinsic features           = ATR@1, required
intrinsic external data      = none
dependencies                 = none
durable PIT reconstruction   = required
```

The adapter accepts closed bars only, requires the bar close and causal cutoff
to equal `market_as_of`, rejects non-positive/non-finite ATR, and converts to
float only at the existing SR `ClosedBar` boundary. Bar IDs are deterministic
content/causal-identity hashes; no Python hash, repr, UUID, or wall clock is
used. Projected bars are rejected.

The SR core receives no `decision_app` import. The adapter imports only the
shared semantic contracts plus SR-owned domain/config/engine/codec modules. It
does not use legacy `FeatureVector` or `ModelOutput`, and it owns no Redis,
Valkey, Timescale, HTTP, scraper, or application-runtime access.

## State encoding and rewarm

SR state is never stored directly in D6 state. The existing canonical SR codec
is used:

```text
encoded string -> decode_state() -> SRState -> SREngine.step()
next SRState   -> encode_state() -> proposed_next_state
```

Initial state uses `create_initial_state()` with the resolver's resolved SR
configuration. Replay and LIVE both call the same `SREngine.step()` path.
The SR configuration hash and state key are checked when decoding a supplied
state, so a state from another asset or configuration is rejected.

The real adapter was exercised through D6 causal rewarm. Rewarm reaches `LIVE`
only after all replay steps succeed; replay has no publication path. A failed
or aborted prepared transaction leaves the committed encoded state unchanged,
marks the stateful binding as requiring rewarm, and prevents stale continuation.
Successful commit advances exactly one trigger transition. D6 rejects future,
skipped, duplicate, and out-of-order state transitions through its existing
continuity checks.

## Direct-versus-runtime parity

For deterministic 1h fixtures with the same resolved SR configuration, initial
state, ordered causal bars, and ATR values:

- direct `SREngine.step()` replay and the D6 plugin runtime produce byte-identical
  final encoded SR state;
- plugin artifact snapshot identity matches the direct `SRSnapshot` identity;
- bounded zone/event evidence is projected from the same snapshot;
- the causal cutoff is the same closed-bar `market_as_of`.

The ATR calculator was compared with the existing `libs.features` ATR batch
implementation on the same 15-bar fixture and matched.

## Validation evidence

Successful focused and compatibility runs:

```text
focused D6/D7/SR boundary tests       35 passed
tests/decision + SR boundary          183 passed
D1-D6 downstream compatibility       12 passed
relevant SR core/config/replay tests  286 passed
```

The complete `tests/models/sr` tree was also attempted. It reported:

```text
899 passed, 36 failed, 119 errors
```

The failures/errors are in the existing research/replay suites that require
approved frozen research bundles or valid local temporary research artifacts;
the representative SR config/domain/lifecycle/serialization/replay/adapter
subset is green. No SR core source was changed to bypass those fixture gates.

Static and boundary validation:

```text
Ruff check (D0-D7 decision/contracts/SR scope)   passed
Ruff format --check (36 files)                    passed
compileall (D0-D7 decision/contracts/SR scope)    passed
SR AST/import boundary tests                      3 passed
adapter infrastructure/legacy scan                passed
```

`git diff --check` is run as the final worktree validation; the cumulative
worktree remains uncommitted and no repository state was reset or restored.
Repository-local `__pycache__` directories generated during validation are
removed before handoff.

## Pass 1 — correctness self-review

- Causal bar identity and UTC cutoff are preserved; projected/incomplete bars
  cannot enter SR.
- ATR is sourced through the D4 shared feature path and is positive/finite.
- SR state is codec-encoded, config/key checked, and deterministic.
- Direct and D6 runtime transitions match on deterministic fixtures.
- D6 rewarm is publication-free and atomic; abort does not mutate committed
  state; commit is one exact trigger transition.
- Artifact identity/type/cutoff are validated by shared D1/D6 contracts.

## Pass 2 — scope and architecture self-review

- The adapter remains one thin class plus small pure conversion/projection
  helpers; no generic adapter abstraction was introduced.
- SR core code remains app-independent.
- No legacy runtime boundary, FeatureVector bridge, data source, scheduler,
  publication, web API, Docker, or infrastructure code was added.
- No model other than SR was refactored or integrated. D7B/Momentum is deferred
  pending a separately reviewed plugin-ready model.

## Residual risks and next gate

- D7A proves the representative stateful analytical adapter only. It does not
  establish authoritative decision publication or downstream risk semantics;
  those remain D8 responsibilities.
- The broad SR research suite requires its pre-existing frozen research
  artifacts to be restored/provisioned by the owning research workflow before
  it can be used as a clean repository-wide gate.
- No D7B candidate was available without violating the no-legacy-bridge rule.

## D7A bounded-artifact remediation

The adapter projection was tightened after review without changing SR core
retention, `SRState`, `SRSnapshot`, `snapshot_id`, lifecycle events, or the
encoded proposed state.

`ModelArtifact.value` now contains:

```text
zone_count              = total authoritative snapshot zones
active_zone_count       = total non-terminal zones
terminal_zone_count     = total BROKEN/EXPIRED zones
projected_zone_count    = number of zones included in the artifact
zones                   = non-terminal zones only, canonical snapshot order
```

The projected zone count is checked against resolved
`runtime.max_active_zones`. Terminal history remains available through the
authoritative encoded next state and scalar total counts, but cannot cause the
artifact payload to grow with model lifetime. Event projection remains the
current-step snapshot event tuple and its IDs remain deterministic.

A deterministic 1,000-bar regression now proves:

```text
total zone count may exceed max_active_zones
active/projected zone count never exceeds max_active_zones
active + terminal == total
projected_zone_count == len(zones)
no projected zone is BROKEN or EXPIRED
```

The direct SR step and adapter still agree on snapshot identity, event IDs,
count semantics, and encoded state.

Updated validation:

```text
tests/decision                         181 passed
SR import-boundary tests                 3 passed
relevant SR core/config/replay tests   286 passed
D1-D6 downstream compatibility         12 passed
D6/D7 focused runtime surface          33 passed
Ruff / format / compile / diff / scan  passed
```

The broad `tests/models/sr` research-fixture result remains unchanged and is
not a D7 adapter regression: its missing approved frozen research bundles and
development capsules still produce the previously recorded failures/errors.

No D8 was started. No commit, merge, push, or external runtime mutation was
performed.

DECISION_APP_D7A_SR_REAL_ADAPTER_READY_FOR_REVIEW
