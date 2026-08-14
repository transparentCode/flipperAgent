---
goal: Remediate D6 LIVE state-transaction continuity and PreparedLaneExecution trust-boundary defects without starting D7
stage: architect-to-coder
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d6, model-runtime, state, remediation]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Architect-to-coder — `decision_app` D6 state-transaction continuity remediation

## 1. Objective

D6 is structurally close and the submitted cumulative suite is green, but independent adversarial review found two LIVE state-continuity blockers and one exported-result trust gap that must be fixed before D7/D8 can depend on the runtime.

Continue only in:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

Do not commit, merge, push, switch branches, reset, restore, or start D7.

Preserve all currently correct D6 behavior:

```text
explicit RuntimePluginCatalog
D2 execution_order reuse
one request phase before evaluation
D5 single resolver batch
binding feature/data isolation
dynamic DataRequirement subset validation
same-cutoff dependency artifact reuse
runtime output identity/type validation
in-memory identity-bound state store
prepared state rather than eager commit
atomic multi-stateful commit validation
abort -> rewarm requirement
REPLAY-only causal rewarm
atomic shadow-state installation
failed/cancelled rewarm leaves real store unchanged
no DecisionPolicy/publication/LaneCommitWatermark/runtime infrastructure
```

Expected terminal status remains:

```text
DECISION_APP_D6_MODEL_RUNTIME_STATE_REWARM_READY_FOR_REVIEW
```

---

# 2. BLOCKER — LIVE state can skip required trigger transitions

## Current defect

`prepare_live()` currently rejects only:

```text
market_as_of <= committed_market_as_of
```

for initialized stateful bindings.

That is insufficient for a causal state machine. D0/D6 already freeze:

```text
stateful missed transitions cannot continue from stale state
```

and rewarm correctly requires exact trigger-interval continuity.

Independent proof on a synthetic 1h stateful counter:

```text
committed at 02:00, state count=2

prepare 03:00
  base = 02:00 / count=2
  proposed = count=3

prepare 04:00 before committing 03:00
  base = 02:00 / count=2
  proposed = count=3

commit 04:00
  committed cutoff becomes 04:00
  committed count becomes 3
```

The required 03:00 transition was silently skipped.

After that, direct preparation at 06:00 from the 04:00 state was also accepted, skipping 05:00.

This is a production correctness blocker.

## Required remediation — exact next LIVE cutoff

For an initialized stateful lane, derive:

```text
trigger_duration = TimeframeGrid.duration(resolved_lane.trigger_timeframe)
```

and require before stateful LIVE execution:

```text
target_market_as_of == common_committed_cutoff + trigger_duration
```

not merely `>`.

If target is later than the next expected cutoff:

```text
raise StateTransactionError / fail closed
stateful binding must rewarm through the missing transition(s)
```

Do not silently degrade-and-continue at the later cutoff.

If stateful records have inconsistent initialized cutoffs, treat as state corruption / rewarm error; do not choose one arbitrarily.

Stateless-only lanes retain deterministic repeated/offline evaluation behavior and are not subject to this state-cutoff rule.

## Required regressions

Prove:

```text
committed T -> prepare T+trigger accepted
committed T -> prepare T accepted? NO
committed T -> prepare T-trigger accepted? NO
committed T -> prepare T+2*trigger accepted? NO
```

Also test projected-decision lanes where `market_as_of` still advances by the configured trigger timeframe duration.

---

# 3. BLOCKER — overlapping prepared state transactions can share the same base state

## Current defect

D6 has a two-phase API:

```text
prepare_live()
  -> PreparedLaneExecution

commit_prepared() OR abort_prepared()
```

but the runtime does not remember that a state transition is already prepared and unresolved.

Therefore two stateful preparations can be produced from the same committed base record before either is finalized.

Even after exact-next-cutoff enforcement, duplicate preparation of the same next cutoff would still be possible.

A state transaction must have one outstanding owner in D6 V1.

## Required remediation — one small pending prepared transaction

Add one minimal runtime-owned pending slot/token; do **not** build a transaction manager.

Conceptually:

```text
ModelRuntime._pending_state_execution: PreparedLaneExecution | None
```

or an equivalent compact immutable token tied to:

```text
identity
market_as_of
prepared transitions/base records
```

Rules for lanes with stateful bindings:

1. `prepare_live()` may begin a new state-bearing preparation only when no unresolved prepared state execution exists.
2. A returned `PreparedLaneExecution` containing one or more prepared state transitions becomes the sole pending state transaction.
3. While pending exists, a later stateful `prepare_live()` must fail before plugin request/evaluation.
4. `commit_prepared()` must accept only the current pending prepared execution, then clear pending **after** successful atomic commit.
5. `abort_prepared()` must accept only the current pending prepared execution, degrade the transition-bearing stateful bindings per existing semantics, then clear pending.
6. A stale/copied/foreign prepared object must not clear or commit a different current pending transaction.
7. Stateless-only lanes need no pending state transaction.

Use exact/equality-safe immutable prepared identity; no locks/concurrency framework in D6.

### Ineligible prepared execution

If a lane has multiple stateful bindings and one fails while another successfully produced a transition, the prepared execution is already `state_commit_eligible=False`, but the successful transition is still causally unresolved.

Such a prepared execution **must still occupy the pending state slot** whenever `prepared_state_transitions` is non-empty.

It cannot be committed; future D8 (or D6 tests) must call `abort_prepared()` to discard it and degrade successful transition-bearing stateful bindings.

This prevents stale-state continuation even when another stateful binding is already INVALID/UNAVAILABLE/BLOCKED.

If no stateful transition was produced at all, no pending transaction is necessary because there is nothing uncommitted to protect; existing WARMING/DEGRADED/INVALID health rules already block those bindings.

## Required regressions

1. After successful `prepare_live(T)`, a second `prepare_live(T)` before commit/abort is rejected before a second stateful plugin evaluation.
2. After successful `prepare_live(T)`, `prepare_live(T+trigger)` before commit/abort is rejected.
3. `commit_prepared(T)` clears pending; `prepare_live(T+trigger)` can then proceed.
4. `abort_prepared(T)` clears pending and forces rewarm; next LIVE stateful prepare is unavailable until rewarm.
5. committing/aborting an older prepared object while another pending transaction exists fails closed without changing state/pending owner.

---

# 4. BLOCKER CONSEQUENCE — failed multi-stateful step must not let another stateful binding continue from stale state

Independent proof with two stateful counters after rewarm to 01:00:

```text
at 02:00:
  A -> EXECUTED, prepared transition
  B -> INVALID
  state_commit_eligible = False

health after prepare:
  A = LIVE
  B = INVALID

at 03:00 without abort:
  A executes again using committed cutoff 01:00
  B = UNAVAILABLE
```

A therefore continued from stale state across a missed 02:00 lane transaction.

The pending-transaction rule above is the preferred simple remediation:

```text
02:00 prepared transitions exist
-> pending state transaction exists
-> 03:00 prepare rejected until explicit abort
-> abort degrades A; B remains INVALID
-> rewarm required before any further LIVE state transition
```

Do not partially commit A merely because it succeeded.
Do not automatically mark B LIVE.
Do not let A advance independently of the lane-level state batch.

Add a dedicated regression matching this scenario.

---

# 5. HIGH — `PreparedLaneExecution` is not sufficiently self-validating for D8

The normal producer path is correct, but direct construction currently accepts contradictory lane evidence.

Independent proofs accepted by the current contract:

```text
A+B stateless lane:
  PreparedLaneExecution.binding_results contains A only
  -> accepted

result key/binding_id = A
outcome.artifact.binding_id = B
  -> accepted

A is BLOCKED by dependency ID "FOREIGN"
  -> accepted
```

D8 will consume `PreparedLaneExecution` as the complete model-runtime boundary. Follow the D4/D5 precedent and reject contradictory output construction.

## Required self-validation

Do not add a new graph framework or duplicate the full `ResolvedLanePlan` inside the output.

Use already-carried D4/D5 evidence where possible.

At minimum in `PreparedLaneExecution.__post_init__` require:

```text
set(binding_results)
  == set(feature_resolution.bindings)
  == set(data_resolution.bindings)
```

This gives the complete configured binding set without adding another field.

For every `EXECUTED` result:

```text
outcome.artifact.binding_id == result.binding_id
outcome.artifact.lane_id == identity.lane_id
outcome.artifact.market_as_of == prepared.market_as_of
```

D1 already validates decision/artifact identity internally.

For every `BLOCKED` result:

```text
blocked_dependency_ids are non-empty
blocked_dependency_ids subset of binding_results keys
blocked_dependency_ids excludes self
referenced blocker result is not EXECUTED
```

The actual configured dependency relationship remains guaranteed by `ModelRuntime` + D2 plan; do not duplicate D2 dependency wiring into `PreparedLaneExecution` merely for this check.

Also ensure:

```text
prepared stateful_binding_ids subset binding_results keys
commit_prepared() verifies prepared.stateful_binding_ids exactly match runtime.stateful_binding_ids
```

The state store's exact-transition check remains the final commit guard.

## Required regressions

Reject direct construction for:

```text
missing stateless binding result
extra/foreign binding result
EXECUTED A carrying B artifact
EXECUTED result carrying artifact lane mismatch
BLOCKED result with foreign blocker
BLOCKED result with self blocker
BLOCKED result whose named blocker is EXECUTED
```

Preserve valid independent failure isolation.

---

# 6. Commit/abort validation order

`commit_prepared()` and `abort_prepared()` are mutation boundaries.

Before mutating state validate, in order:

```text
prepared type
prepared identity == runtime identity
prepared stateful_binding_ids == runtime.stateful_binding_ids
prepared is/equates to current pending state transaction when transitions exist
prepared mode == LIVE
```

Commit additionally requires:

```text
state_commit_eligible == True
prepared transitions exactly cover every configured stateful binding
current records exactly equal transition base records
prepared market_as_of is exactly next trigger cutoff from current committed state
```

Only after every check passes mutate all records atomically and clear pending.

On commit failure:

```text
state store unchanged
pending transaction unchanged
```

Abort additionally requires transition/base-state freshness before mutation.

Only after successful degradation clear pending.

---

# 7. Rewarm interaction with pending LIVE state

Do not allow causal rewarm to silently overwrite an unresolved pending LIVE state proposal.

If a pending state transaction exists:

```text
rewarm(...) -> reject
```

Caller must first explicitly abort the pending prepared execution.

After abort, rewarm remains the existing publication-free shadow-state path.

Successful rewarm must leave no pending LIVE transaction.

Add a regression:

```text
prepare LIVE transition
rewarm before commit/abort -> rejected
abort
rewarm -> allowed
```

No changes to replay/PIT semantics are needed.

---

# 8. Keep state-store invariants narrow

Do not redesign `LaneStateStore`.

Optional/appropriate hardening while touching state tests:

- `install_rewarm()` should reject reconstructed records whose committed cutoffs are not all identical, since D6 atomic state identity assumes one lane state cutoff;
- all installed records must remain `LIVE` and cover exactly configured stateful bindings as today.

This is a small invariant check, not a checkpoint/version framework.

---

# 9. Tests

Extend the existing focused files only:

```text
tests/decision/test_model_runtime.py
tests/decision/test_state_rewarm.py
```

Touch `test_runtime_plugins.py` only if genuinely necessary.

New focused coverage must include at least:

```text
LIVE exact-next-trigger enforcement
LIVE skipped trigger rejected
one outstanding prepared state transaction
same-cutoff duplicate prepare rejected
future prepare while pending rejected
pending cleared on successful commit
pending cleared on successful abort
failed commit retains pending and all state
multi-stateful partial-success prepare blocks next LIVE transition until abort
abort degrades successful transition-bearing stateful binding and preserves INVALID peer
rewarm rejected while pending
PreparedLaneExecution complete result-map enforcement
swapped outcome binding rejection
foreign/self/executed blocker rejection
commit stateful-binding-set integrity
```

Preserve all existing D6 tests.

---

# 10. Validation

Use repository interpreter:

```text
/Users/kajukatli/projects/flipperAgent/.venv/bin/python
```

Run focused D6:

```bash
PYTHONPATH=src:. /Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision/test_runtime_plugins.py \
  tests/decision/test_model_runtime.py \
  tests/decision/test_state_rewarm.py
```

Then cumulative:

```bash
PYTHONPATH=src:. /Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision \
  tests/commons/test_model_runtime_contract.py \
  tests/models/test_strategy_model_v2.py
```

Then:

```bash
/Users/kajukatli/.local/bin/ruff check \
  src/libs/contracts/decision.py src/apps/decision_app tests/decision

/Users/kajukatli/.local/bin/ruff format --check \
  src/libs/contracts/decision.py src/apps/decision_app tests/decision

/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m compileall -q \
  src/libs/contracts/decision.py src/apps/decision_app tests/decision

git diff --check
```

Repeat the infrastructure/import-boundary scan for D6 production modules.
Remove repository-local generated bytecode caches after validation.

Do not run Docker, broker, DB, network, or live-market operations.

---

# 11. Coder handoff update

Update:

```text
plans/coder-to-orchestrator-decision-app-d6-model-runtime-state-rewarm-v1.md
```

Record:

```text
exact-next LIVE cutoff rule
pending prepared state-transaction semantics
multi-stateful partial-failure stale-state proof/fix
PreparedLaneExecution trust-boundary hardening
new focused count
new cumulative count
Ruff/format/compile/diff/import results
Pass 1 findings
Pass 2 findings
residual risks
```

Explicitly retain:

```text
D6 does not publish or advance LaneCommitWatermark.
D8 owns policy/publication authorization and calls commit/abort.
D7 was not started.
```

No commit, merge, or push.

Final line exactly:

```text
DECISION_APP_D6_MODEL_RUNTIME_STATE_REWARM_READY_FOR_REVIEW
```
