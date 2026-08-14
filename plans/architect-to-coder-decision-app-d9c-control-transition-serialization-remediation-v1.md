---
goal: Remediate the remaining D9C concurrent-control race so pause, resume, and reconnect cannot leave incoherent desired/service state or allow market polling while the service reports PAUSED
stage: architect-to-coder
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d9c, remediation, control, concurrency]
---

# Architect-to-coder — `decision_app` D9C control-transition serialization remediation

## 1. Starting point

Use only the existing cumulative isolated worktree:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

Approved/frozen before this remediation:

```text
D0-D9B
D7A
D9C architecture: one DecisionService, one market task, one lifecycle task,
one transition lock, runtime-generation rebuild rather than hot graph mutation
```

The latest D9C remediation has independently passed review for:

```text
control-state precedence / desired-state readiness gate
lifecycle reconciliation separated from causal auto-rebuild budget
exception-safe lifespan cleanup
non-default feature-policy wiring
HTTP cached readiness/control surface
D9A/D9B transaction semantics unchanged
```

Do not reopen those designs except where the narrow concurrent-control correction needs a local change.

Do not start D9D. Do not add PriceRelay, main.py, a service port, Compose registration, production decision asset YAML, PEL/consumer groups, a generic state framework, or a second control lock.

Do not commit, merge, push, switch branches, reset, restore, or modify the primary checkout.

---

# 2. Confirmed blocker — concurrent `pause()` + `reconnect()` violates pause contract

`DecisionService.pause()` currently acquires `_transition_lock`, sets:

```text
_desired_state = PAUSED
```

then releases the lock while awaiting `_poll_idle`, and reacquires it only to set:

```text
_service_state = PAUSED
```

`reconnect()` / `_manual_rebuild()` can enter that unlocked interval, set desired state back to `RUNNING`, wait for the same poll boundary, rebuild and install a fresh generation, then resume market polling.

The original `pause()` can subsequently reacquire the lock and overwrite only `service_state` to `PAUSED`.

Independent reproduction, repeated deterministically:

```text
initial generation 1 has one active gated poll

concurrently:
  pause()
  reconnect()

release current poll gate

observed:
  pause result.service_state = PAUSED
  pause result.desired_state = RUNNING

  reconnect result.service_state = RUNNING
  reconnect result.desired_state = RUNNING

  final service_state = PAUSED
  final desired_state = RUNNING
  final generation_id = 2
  generation 2 poll count > 0
```

A generation is therefore actively polling while the service reports `PAUSED`.

This violates the frozen D9C pause contract:

```text
pause returns only after no next market poll can start
service_state = PAUSED
desired_state = PAUSED
while PAUSED, market poll count does not increase
```

This is a D9C control-transition race only. It is not a D9A, D9B, D8, checkpoint, signal-publisher, lifecycle-reader, or model defect.

---

# 3. Required invariant

At every externally observable control boundary, these combinations must be coherent:

```text
service_state = PAUSED
  -> desired_state = PAUSED
  -> no new market poll begins

service_state = RUNNING
  -> desired_state = RUNNING
  -> installed generation may poll

service_state = REBUILDING
  -> desired_state = RUNNING
  -> old generation is not polled again

service_state = STOPPING / STOPPED
  -> no new market poll begins
```

Forbidden invariant after any control race:

```text
service_state = PAUSED
desired_state = RUNNING
```

Also forbidden:

```text
service_state = PAUSED
and any generation starts a new D9B poll after pause has completed
```

`DecisionServiceSnapshot.ready` must remain consistent with these control invariants.

---

# 4. Selected correction — serialize the full pause transition

Keep the existing **single** `_transition_lock`.

Do not add a generic control-state coordinator.

Preferred minimal correction:

```text
pause()
  acquire _transition_lock
  validate control available
  require generation
  set desired_state = PAUSED
  wake market loop
  await _poll_idle while still owning the transition lock
  set service_state = PAUSED
  capture/return coherent snapshot
  release lock
```

Why this is safe:

- completion of the currently active `D9B poll_once()` does not require `_transition_lock`;
- `_poll_idle` is set in the market loop `finally` block independently of this lock;
- once `desired_state = PAUSED`, the market loop checks it before starting another poll;
- lifecycle rebuild scheduling may wait briefly for the transition lock and remains notification-only;
- `resume()` / `reconnect()` cannot enter halfway through the pause transition.

An equivalent minimal serialization is acceptable if it proves the same invariants.

Do not solve this with:

```text
second lock
condition-variable framework
control queue
actor/event-bus abstraction
persistent control state
```

---

# 5. Concurrent control semantics

Use deterministic serialization rather than ambiguous partial overlap.

## 5.1 `pause()` wins the lock first

Expected order:

```text
active poll finishes
pause completes atomically -> PAUSED / PAUSED
then reconnect/resume may acquire the lock
reconnect/resume -> fresh D9A/D9B generation -> RUNNING / RUNNING
```

Final state may be RUNNING because reconnect/resume is the later serialized command, but the pause result itself must have been a truthful coherent PAUSED snapshot and no new old-generation poll may start between the pause boundary and the later control transition.

## 5.2 `reconnect()` / `resume()` wins first

Expected:

```text
manual rebuild completes -> fresh generation RUNNING
then pause acquires lock
current new-generation bounded poll, if already active, finishes
pause completes -> PAUSED / PAUSED
no next poll begins
```

## 5.3 Genuine conflict alternative

The existing architecture allows HTTP 409 for genuine conflicting transitions if necessary.

It is acceptable instead to explicitly reject a second overlapping manual control with `RuntimeError`/409, but only if:

```text
state remains coherent
first control completes safely
no generation polls under PAUSED
tests prove deterministic behavior
```

Prefer simple lock serialization unless rejection is materially cleaner.

---

# 6. Do not weaken lifecycle or rebuild-source remediation

Preserve:

```text
RebuildSource = CAUSAL_RECONSTRUCTION | LIFECYCLE_RECONCILIATION | MANUAL
```

and:

```text
causal reconstruction only -> one-shot automatic budget
lifecycle reconciliation -> never suppressed by causal budget
manual resume/reconnect -> explicit fresh rebuild
```

A lifecycle notification arriving during `pause()` may wait on the transition lock. After pause completes it may remain as bounded lifecycle evidence/rebuild request, but while globally PAUSED the market loop must not perform the rebuild or poll until a later RUNNING transition.

Do not hot-mutate graph/lane internals.

---

# 7. Do not weaken shutdown semantics

Preserve:

```text
stop sets STOPPING before releasing its transition section
current bounded poll finishes
no next market poll begins
lifecycle wait task stops
market task exits
lifespan closes all owned resources with nested exception-safe cleanup
```

A concurrent reconnect/resume that reaches `_ensure_control_available()` after STOPPING must continue to fail closed.

No changes to D9A restart semantics.

---

# 8. Required regressions

Add focused deterministic tests in `tests/decision/test_d9c_service.py` and HTTP layer only if useful.

At minimum prove:

## 8.1 Concurrent pause + reconnect, pause starts first

Use a gated generation-1 `poll_once()`.

```text
start service
wait until gen1 poll active
start pause task
allow pause to claim the transition
start reconnect task
release gen1 poll
```

Prove serialized outcomes:

```text
pause snapshot = PAUSED / PAUSED
old gen1 poll count == 1
reconnect then installs gen2
reconnect snapshot = RUNNING / RUNNING
final state coherent
```

If implementation chooses conflict rejection instead, prove the rejected control returns conflict and the winning pause stays PAUSED/PAUSED.

## 8.2 Concurrent reconnect + pause, reconnect starts first

Prove:

```text
reconnect installs fresh generation
pause subsequently waits for any bounded fresh-generation poll
pause result = PAUSED / PAUSED
final service = PAUSED / PAUSED
no later poll begins
```

## 8.3 No polling under coherent PAUSED state

After pause returns:

```text
record current generation poll count
yield event loop repeatedly
assert poll count unchanged
assert snapshot.ready is False
assert desired_state == PAUSED
assert service_state == PAUSED
```

## 8.4 Concurrent API controls, if practical

At minimum service-level tests are mandatory.

If HTTP control testing is simple with existing ASGI helpers, also prove overlapping pause/reconnect requests never return an incoherent payload such as:

```text
{"service_state": "PAUSED", "desired_state": "RUNNING"}
```

Do not add complex concurrent HTTP harness machinery solely for this.

## 8.5 Existing D9C remediation tests remain green

Do not weaken:

```text
paused state dominates lifecycle transport degradation
control states not overwritten by completed polls
lifecycle rebuild independent of causal budget
cleanup continues after Valkey/DB failure
normal once-only cleanup
HTTP readiness desired-state gate
non-default feature policy wiring
pause/resume generation rebuild
reconnect old generation no-repeat
transport retry same generation
one causal reconstruction rebuild
hard faults no auto loop
real SR NO_SIGNAL service path
synthetic isolated SIGNAL path
```

---

# 9. Acceptance criteria

D9C is ready for review only when all hold:

```text
pause transition is atomic with respect to resume/reconnect
no PAUSED/RUNNING state combination can be observed
no market polling occurs while service is PAUSED
manual controls remain generation-safe
lifecycle rebuild-source semantics unchanged
causal rebuild budget unchanged
D9A/D9B/D8 contracts unchanged
shutdown/cleanup semantics unchanged
no new framework/lock/control queue
```

No D9D work.

---

# 10. Validation

Run focused D9C:

```text
tests/decision/test_d9c_composition.py
tests/decision/test_d9c_lifecycle.py
tests/decision/test_d9c_service.py
tests/decision/test_d9c_api_bootstrap.py
```

Then:

```text
complete tests/decision
relevant non-research SR adapter/core/replay suite
commons config/connections/pool/manifest slice
signal/risk compatibility slice
canonical ingestion lifecycle/outbox/provenance slice
```

Static:

```text
Ruff check
Ruff format --check
compileall or non-writing AST parse for independent review
git diff --check
production import boundary
forbidden XREADGROUP/XACK/XAUTOCLAIM/PEL scan
forbidden PriceRelay/price_update scan
no main.py/port/Compose/D9D leakage
repo-local __pycache__ cleanup
```

If `.env` remains absent, keep:

```text
LOCAL_INFRASTRUCTURE_VALIDATION_BLOCKED_ENVIRONMENT
```

Do not create/copy credentials or mutate external/shared runtime state.

---

# 11. Two-pass coder self-review

## Pass 1 — control/transaction correctness

Verify explicitly:

```text
pause owns one complete serialized transition
poll completion cannot deadlock on transition lock
concurrent reconnect/resume cannot overwrite pause halfway
pause cannot overwrite a completed reconnect into PAUSED/RUNNING
no market poll begins after completed pause
manual rebuild remains fresh D9A/D9B
lifecycle notification remains manifest-authority only
control readiness remains coherent
stop/reconnect conflict remains fail-closed
```

## Pass 2 — simplicity/scope

Verify:

```text
one transition lock only
no control queue/state framework
no D9A/D9B changes unless strictly required by signature-only compatibility
no PriceRelay
no D9D
no service port/main.py/Compose
no production decision asset config
no legacy runtime imports
```

---

# 12. Handoff

Update:

```text
plans/coder-to-orchestrator-decision-app-d9c-service-lifecycle-control-v1.md
```

Record:

```text
concurrent-control defect and chosen serialization
pause-first/reconnect-first adversarial evidence
no-poll-under-PAUSED evidence
focused/cumulative/SR/commons/risk/ingestion results
static/import/forbidden/cache evidence
local infrastructure environment gate
Pass 1 findings
Pass 2 findings
residual risks
D9D/PriceRelay carry-forward
```

Do not claim D9C approved until orchestrator review.

Do not start D9D automatically.

Final line exactly:

```text
DECISION_APP_D9C_SERVICE_LIFECYCLE_CONTROL_READY_FOR_REVIEW
```
