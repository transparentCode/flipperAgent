---
goal: Repair D9D PriceRelay live-target retention and retry semantics without reopening risk, D9B, service, or architecture
stage: architect-to-coder
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d9d, price-relay, remediation, retry, continuity]
---

# Objective

Repair the remaining D9D PriceRelay continuity defects found by independent orchestrator review.

The submitted D9D implementation is otherwise structurally sound. Do **not** redesign PriceRelay, risk_app, D9B, DecisionService, publication, checkpointing, model/plugin composition, or lifecycle architecture.

The defect is narrow: PriceRelay currently forgets the highest live canonical target after `InputReadCursor` advances, and treats retryable/bootstrappable states as terminal `UNRESOLVED`. This can permanently strand a risk-critical price bar even though canonical history remains available and transport later recovers.

Work only in the existing cumulative isolated worktree:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

Do not commit, merge, push, switch branches, reset, restore, or modify the primary checkout.

Do not start D10.

---

# Starting status

Approved before this package:

```text
D0-D9C                           APPROVED
Pre-D9D architecture hardening   APPROVED
```

Submitted D9D review baseline independently reproduced:

```text
focused D9D       21 passed
tests/decision   334 passed
tests/risk       162 passed
signals          92 passed, 1 warning
scoped Ruff      passed
format            passed
git diff --check  passed
```

No risk-side defect was found in the reviewed timestamp normalization, pre-entry eligibility, or successful duplicate-price suppression. Keep those semantics frozen.

---

# Blocker A — live catch-up target is lost after the input cursor advances

## Confirmed defect

`PriceRelay._reconcile_one()` currently chooses its target from:

```text
candidate.market_as_of
else startup warm cutoff
```

but does not retain a newer live target after a bounded catch-up step.

That violates D9D's bounded catch-up model because accepted market input and PriceRelay publication are independent progress domains:

```text
InputReadCursor may advance to target T
PriceRelayProgress may still be behind T
```

The next poll may have no new accepted input record for that series, because the input cursor has already consumed T. PriceRelay must still know it is required to reach T.

### Independent reproduction

With:

```text
startup relay baseline = bar 0 close
live accepted target    = bar 3 close
batch_size              = 1
```

first reconciliation correctly publishes only bar 1 and becomes `GAP_DETECTED`.

Current subsequent idle polls produce:

```text
first:
  continuity = GAP_DETECTED
  published  = bar 1 close

second idle poll:
  target     = startup warm cutoff (bar 0 close)   # WRONG
  published  = still bar 1 close
  no XADD

third idle poll:
  same
```

Only one price entry is ever published until another future canonical event happens to supply a new candidate.

This violates the frozen contract:

```text
multiple missing bars -> chronological order
batch_size bounds publications per step
backlog remains -> GAP_DETECTED
next bounded poll continues catch-up
```

## Required correction

PriceRelay must retain one bounded **highest observed target cutoff per relay plan**.

Do not add a queue or history journal.

A small mapping is sufficient, conceptually:

```text
_pending_target_by_plan[relay_plan_id] -> datetime | None
```

or equivalent bounded state encoded in current progress/gap evidence.

Rules:

1. Startup target begins at the startup warm cutoff when present.
2. A valid live candidate updates the remembered target monotonically:

```text
pending_target = max(previous_pending_target, candidate.market_as_of)
```

3. An idle poll with no candidate continues toward the remembered target.
4. `latest_market_as_of` remains publication progress only; do not overload it as target progress.
5. When publication catches up exactly to the remembered target:

```text
continuity = CONTINUOUS
pending target may collapse to latest / clear
```

6. A newer candidate arriving during backlog extends the target; never lowers it.
7. Target state is per relay plan and bounded O(number_of_relay_plans).
8. Fresh generation rebuild re-establishes target state from D9A warm cutoff/downstream-tail bootstrap; no durable target table is needed.

Prefer exposing current target/backlog in existing bounded `gap_evidence` / `PriceRelayResult`; do not create a new observability subsystem.

---

# Blocker B — transient publication `FAILED` is incorrectly terminal

## Frozen D9D rule

The approved D9D plan explicitly says:

```text
On FAILED:
  no progress advance
  gap remains
  next poll may retry same exact bar

On CONFLICT:
  UNRESOLVED
  no automatic stream rewrite
```

## Current defect

Current code treats any publisher outcome not in:

```text
PUBLISHED
ALREADY_IDENTICAL
```

through the same `_unresolved(...)` path.

Therefore `FAILED` becomes terminal `UNRESOLVED`.

### Independent reproduction

```text
baseline = bar 0 close
candidate = bar 1
first XADD = temporary broker failure
transport then recovers
```

Observed:

```text
first reconciliation:
  continuity          = UNRESOLVED
  publication_outcome = FAILED
  progress            = bar 0 close

second reconciliation with healthy transport:
  continuity          = UNRESOLVED
  publication_outcome = None
  progress            = bar 0 close
  no XADD retry
```

This is unsafe because `InputReadCursor` has already accepted bar 1.

## Required correction

Separate retryable transport failure from semantic conflict.

Required outcome mapping:

```text
PUBLISHED / ALREADY_IDENTICAL
  -> advance progress

FAILED
  -> do NOT advance progress
  -> continuity = GAP_DETECTED
  -> retain target
  -> next poll retries exact next missing bar

CONFLICT
  -> do NOT advance progress
  -> continuity = UNRESOLVED
  -> terminal until fresh reviewed generation/manual recovery
```

A transport exception caught around publisher/history access that is inherently retryable should similarly leave the relay `GAP_DETECTED` with its target retained unless the evidence proves semantic corruption.

Do not add exponential backoff/retry loops. One attempt per existing bounded market poll remains the scheduler.

---

# Blocker C — first valid bar cannot recover a no-tail/no-warm first start

## Frozen D9D rule

When both downstream tail and D9A warm cutoff are absent:

```text
latest_market_as_of = None
continuity_status   = UNRESOLVED
```

but the approved D9D plan additionally freezes:

```text
The first valid closed canonical bar may establish the baseline/publication forward.
```

## Current defect

`_set_baseline()` correctly creates:

```text
UNRESOLVED
reason = no downstream tail or canonical startup cutoff
```

but `_reconcile_one()` immediately returns for **every** `UNRESOLVED` state before considering the first candidate.

### Independent reproduction

```text
no downstream tail
warm cutoff = None
first valid canonical closed bar arrives
```

Observed:

```text
before:
  UNRESOLVED / latest=None

after first valid candidate:
  UNRESOLVED
  no publication
  latest=None
```

## Required correction

Not every `UNRESOLVED` reason is equally terminal.

Keep terminal fail-closed behavior for:

```text
CONFLICT
malformed/mismatched downstream tail
downstream tail ahead of captured canonical cutoff
missing exact canonical history in required catch-up
backlog greater than retention bound
other proven semantic/canonical corruption
```

But allow the specific bootstrappable state:

```text
no downstream tail + no startup canonical cutoff + latest=None
```

to accept the first valid canonical closed candidate.

For that first candidate:

```text
publish exact deterministic PriceUpdate ID
PUBLISHED/ALREADY_IDENTICAL -> latest=candidate.close, CONTINUOUS
FAILED                       -> GAP_DETECTED, retain candidate target
CONFLICT                     -> UNRESOLVED
```

Do not make arbitrary terminal `UNRESOLVED` states self-healing.

Use a small explicit reason/state marker; do not infer behavior by fragile substring matching if a bounded typed/internal marker is simpler.

---

# Bounded observability correction

The approved plan explicitly identified bounded gap evidence such as:

```text
expected_next_market_as_of
observed_target_market_as_of
reason
backlog_bars
baseline_source
```

Current `PriceRelayResult.backlog_bars` is `0` on ordinary partial catch-up even when continuity is `GAP_DETECTED`.

While repairing target retention, make current evidence truthful and bounded:

```text
target_market_as_of    = retained highest target
published_market_as_of = latest successful publication
backlog_bars           = number of canonical bars still required after this step
```

Exact naming inside `gap_evidence` may follow the existing plan; do not add historical arrays/journals.

Do not let observability calculation change publication semantics.

---

# Production semantics that remain frozen

Do not change:

```text
PriceUpdate wire shape
PriceUpdate.timestamp = bar-open epoch milliseconds
price stream key = price_update:{asset}:{timeframe}
Valkey entry ID = bar-close epoch-ms-0
stream maxlen default = 200
stream approximate = true
relay source = canonical ingestion series
relay-only assets / zero model lanes
one PriceRelay inside existing D9B poll
no PriceRelay task
D9B input cursor ordering
D8 signal publication/finalization
LaneCommitWatermark semantics
DecisionService PAUSED input+relay semantics
resume fresh D9A generation
risk price PEL reclaim
risk pre-entry bar eligibility
risk SL/TP/multi-TP/trailing mathematics
price-derived order timestamp = bar-close seconds
price order idempotency still includes bar-open milliseconds
```

No risk_app production change should be necessary for this remediation unless a new regression demonstrates a direct defect. Prefer zero risk production changes.

---

# Explicit non-goals

Do not implement:

```text
new model/plugin
model refactor
D7B/Momentum
D10 resource certification
D11 shadow parity
D12 cutover
PriceRelay outbox/table
persistent relay target DB state
relay worker/task per series
retry/backoff framework
risk health signal gate
consumer-lag monitor
new risk policy
new stream retention setting
production decision asset YAML
main.py / HTTP port / Compose registration
```

Do not broaden this into a generic progress/checkpoint framework.

---

# Required new regressions

Add focused tests to `tests/decision/test_d9d_price_relay.py` and, where useful, `test_d9d_price_relay_runtime.py`.

## 1. Idle-poll bounded catch-up continuation

```text
baseline bar 0
live candidate bar 3
batch_size = 1

poll/reconcile 1 with candidate:
  publish bar 1
  GAP_DETECTED
  target retained at bar 3
  backlog > 0

reconcile 2 with NO candidate:
  publish bar 2
  GAP_DETECTED

reconcile 3 with NO candidate:
  publish bar 3
  CONTINUOUS

publication order exactly bar1,bar2,bar3
```

This regression must use the same `reconcile_all()` shape used by `LiveDecisionRuntime`; do not manually resupply bar 3 after the first call.

## 2. Transient XADD failure retries exact same bar

```text
baseline bar 0
candidate bar 1
first XADD fails without insert

result:
  FAILED
  GAP_DETECTED
  progress remains bar0
  target remains bar1

next reconcile_all() with NO candidate and healthy client:
  exact bar1 XADD retried
  PUBLISHED
  progress -> bar1 close
  CONTINUOUS
```

Also prove the retry uses the same deterministic explicit stream ID.

## 3. Ambiguous insert remains idempotent

Existing insert-then-raises proof must remain green:

```text
exact entry exists after exception -> ALREADY_IDENTICAL -> progress advances
```

Do not accidentally classify it as retryable failure.

## 4. Conflict remains terminal

```text
same required ID different payload / newer head conflict
  -> UNRESOLVED
  -> subsequent idle reconcile does not attempt stream rewrite
```

## 5. First-candle establishment

```text
no downstream tail
warm cutoff None
first closed canonical bar arrives

PUBLISHED/ALREADY_IDENTICAL
  -> CONTINUOUS
  -> progress == first bar close
```

Also prove transient failure on this first bar becomes `GAP_DETECTED` and succeeds on a later idle poll.

## 6. Target monotonicity

```text
pending target = T2
new valid candidate = T3 > T2
retain T3
never lower target during idle polls
```

## 7. Runtime-level cursor independence

Through `LiveDecisionRuntime`:

```text
bar accepted -> InputReadCursor advances
relay publication fails transiently
lane path (if present) remains independent
next poll receives no duplicate ingestion bar
PriceRelay retries from durable canonical history using retained target
```

A relay-only runtime fixture is acceptable; one test with a synthetic lane may be added only if needed to prove no lane rollback.

## 8. No-baseline runtime

Through startup/live seams or direct relay seam:

```text
startup warm cutoff absent
no downstream tail
first live canonical bar establishes relay
```

---

# Complete the remaining D9D cross-domain acceptance proofs

The submitted focused D9D surface proves the core relay transport/catch-up and basic risk replay behavior, but several original D9D acceptance cases are currently inferred from implementation or older generic D9C/risk tests rather than exercised directly through the D9D integration.

Add focused regressions for these before D9D approval. They should be small and reuse existing fixtures; do not create new frameworks.

## Relay / lane independence

Prove through `LiveDecisionRuntime` or a minimal service fixture:

```text
relay A transient failure -> relay B still publishes/progresses
relay failure -> InputReadCursor remains advanced
relay failure -> already-committed lane watermark is not rolled back
lane RECONSTRUCTION_REQUIRED -> healthy relay still progresses on later poll
lane HALTED/INVALID -> healthy relay still progresses
```

## Paused lifecycle generation

Through actual `DecisionService` with a PriceRelay-capable generation:

```text
operator pause -> PAUSED/PAUSED and relay continues
lifecycle reconciliation while operator remains paused
  -> fresh generation installed
  -> desired_state remains PAUSED
  -> service_state remains PAUSED
  -> fresh generation PriceRelay continues
  -> lane evaluation flag remains false
```

Also prove `stop()` waits for the current bounded paused relay poll and no later relay/input poll starts after STOPPED.

## Risk PEL integration evidence

Add direct evidence that:

```text
RiskWorker.run startup order = signal PEL drain -> price PEL drain -> normal read loop
reclaimed SL/TP price message emits exactly one close order and marks pending close
duplicate/replayed same price after successful pending-close does not emit another close order
```

Do not redesign consumer behavior; these are certification proofs for the already-reviewed narrow risk changes.

---

# Preserve required D9D acceptance matrix

Do not delete or weaken existing D9D tests.

The final focused D9D surface must continue to cover:

```text
relay-only config
current six risk routes
wire parity
exact-ID idempotency
startup tail validation
retention overflow
missing canonical history
paused relay operation
risk timestamp normalization
pre-entry filtering
price PEL success/failure
```

The remediation adds retry/retained-target cases; it does not replace the existing matrix.

---

# Validation

Run in this order:

```text
1. new target/retry focused tests
2. all D9D focused tests
3. tests/decision
4. tests/risk
5. tests/signals + tests/integration/signals
6. relevant ingestion lifecycle/HTF/outbox/provenance slice
7. affected execution/order/idempotency slice
8. non-research SR compatibility slice
```

Static:

```text
Ruff on changed decision/risk scope
Ruff format --check on changed scope
compileall
AST/import boundary scan
git diff --check
architecture guardrails
no decision XREADGROUP/XACK/XAUTOCLAIM/XGROUP
no third decision create_task
no generic decision libs.models import
no model/plugin additions
repo-local cache cleanup
```

Do not force live Timescale/Valkey validation if the repository worktree still lacks `.env`. Record:

```text
LOCAL_INFRASTRUCTURE_VALIDATION_BLOCKED_ENVIRONMENT
```

Do not copy credentials or mutate shared/external runtime state.

---

# Coder handoff update

Update the existing D9D coder handoff:

```text
plans/coder-to-orchestrator-decision-app-d9d-price-relay-risk-continuity-v1.md
```

Add a clearly labeled remediation section containing:

```text
retained-target implementation
FAILED retry semantics
first-candle bootstrap recovery
before/after direct proofs
new tests and counts
focused/cumulative validation
static results
residual risks
```

Do not claim D10 readiness beyond D9D review readiness.

Stop with exactly:

```text
DECISION_APP_D9D_PRICE_RELAY_RISK_CONTINUITY_READY_FOR_REVIEW
```
