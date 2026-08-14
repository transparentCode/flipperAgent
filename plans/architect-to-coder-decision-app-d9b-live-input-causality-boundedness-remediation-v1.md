---
goal: Remediate D9B live-input causality, represented-context catch-up, bounded input memory, and transaction-local poll evidence without changing approved D8 publication/finalization semantics or starting D9C
stage: architect-to-coder
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d9b, remediation, causality, boundedness, observability]
---

# Architect-to-coder — `decision_app` D9B live-input causality/boundedness remediation

## 1. Starting point

Continue only in the existing cumulative isolated worktree:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

Base remains detached at:

```text
4fc0de62515112dc371e08a6cde503746c54f7f7
```

D0-D8, D7A, and D9A are APPROVED.

D9B's core D8 transaction wiring is structurally correct:

```text
PUBLISHED / ALREADY_IDENTICAL
    -> D8 finalizer
    -> D6 state commit
    -> LaneCommitWatermark advance

CONFLICT / FAILED
    -> D8 finalizer abort
    -> no state commit
    -> watermark unchanged

stateful committed transaction
    -> checkpoint persistence afterwards
```

Do not reopen these semantics.

The submitted D9B baseline is green:

```text
focused D9B:        17 passed
complete decision: 272 passed
```

Independent review reproduced those counts and directly verified the live-wrapper ACK matrix:

```text
PUBLISHED           -> COMMITTED, watermark advances
ALREADY_IDENTICAL   -> COMMITTED, watermark advances
CONFLICT            -> ABORTED, watermark unchanged
FAILED              -> ABORTED, watermark unchanged
```

This remediation exists because four D9B-local defects were reproduced outside current coverage.

Do not commit, merge, push, switch branches, reset, restore, or touch the primary checkout.

---

# 2. Hard non-goals

Do NOT implement or start:

```text
D9C
FastAPI/lifespan/main service
Docker/Compose decision service
runtime supervisor/controller
consumer groups / PEL / XREADGROUP / XACK / XAUTOCLAIM
signal outbox
persistent input cursor storage
asset:lifecycle subscriber
PriceRelay
price_update:* publication
PriceRelay recovery semantics
retry/backoff framework
worker/task per lane
actor/event-bus/workflow framework
D7B/Momentum refactor
shadow live finalization
shadow parity
resource/load certification
cutover
legacy retirement
risk_app or execution_app changes
legacy signal_app or strategy_app changes
```

Do not redesign D6 state contracts, D8 policy, D8 signal envelopes, or D8 finalization.

Do not add a second market-history catalog or second checkpoint mechanism.

---

# 3. Blocking finding A — per-stream transport order is violated by global market-time sorting

Canonical ingestion publishes `candle.committed` with **auto-generated Valkey stream IDs**.

Therefore:

```text
stream ID order = transport/publication order
market_as_of     = candle market order
```

They are deliberately different concepts.

Current `LiveDecisionRuntime.poll_once()` sorts all parsed records globally by:

```text
market_as_of
stream_key
numeric stream_id
```

This can process a later record from one stream before an earlier transport record from that same stream.

Independent reproduction:

```text
startup warm bar: index 0
captured tail:    0-0

XREAD returns in valid transport order:
  10-0 -> new live bar index 1
  11-0 -> delayed DB-ahead/startup bar index 0
```

Current global market sort accepts `11-0` first because it has the older market cutoff:

```text
11-0 -> ALREADY_REPRESENTED -> cursor becomes 11-0
10-0 -> MALFORMED: accepted record is not forward
lane -> RECONSTRUCTION_REQUIRED
signal -> none
```

The live trigger was skipped solely by D9B's own reordering.

## 3.1 Required rule

Within each stream, returned numeric stream-ID order is a **hard precedence constraint**.

Never accept stream record N+1 before stream record N from the same `XREAD` result.

Market-time grouping may order records **across streams only when it does not violate a stream's current head order**.

Do not infer market time from stream IDs.

## 3.2 Recommended simple merge

Do not add a scheduler framework.

A small deterministic k-way merge over per-stream ordered records is sufficient:

```text
1. read_once() already validates each stream in returned stream-ID order;
2. partition parsed records by stream, preserving that order;
3. expose only the current unconsumed head from each stream;
4. choose the minimum market_as_of among current heads;
5. accept every currently eligible head at that cutoff in deterministic stream-key order;
6. after consuming one head, expose that stream's next head;
7. if the newly exposed head has the same cutoff, consume it in the same cutoff group;
8. attempt pending lanes after the cutoff group;
9. repeat.
```

A stream whose next head has an earlier market cutoff than the record just accepted is not reordered backwards. Process it only when it becomes that stream's head, then let normal duplicate/late/reconstruction classification decide its meaning.

This preserves both:

```text
transport cursor correctness
and
same-cutoff multi-stream context-before-evaluation semantics
```

If an even smaller implementation proves the same invariants, use it.

---

# 4. Blocking finding B — Timescale-reconciled context poisons its delayed stream catch-up

D9B intentionally permits bounded live context reconciliation:

```text
trigger stream arrives
required non-trigger context stream lags
canonical Timescale already has context
-> fetch forward context once
-> append to BarStore
-> evaluate pending trigger
```

Current `DirectCursorInput.accept()` knows only:

```text
D9A startup warm_cutoff represented history
or
same-open latest duplicate
```

It does not recognize bars that **D9B itself** already appended from Timescale.

Independent reproduction:

```text
startup warm bar = bar0
D9B bounded DB reconciliation appends bar1 + bar2
later outbox stream delivers exact bar1
```

Current result:

```text
RECONSTRUCTION_REQUIRED
reason = late post-startup historical event
stream blocked
cursor unchanged
```

That makes the approved delayed-context reconciliation path self-poisoning.

## 4.1 Required classification order

Before generic post-startup `event.bar_open_at < latest.bar_open_at -> RECONSTRUCTION_REQUIRED`, first test whether the event's canonical identity is **currently retained and provable**.

For an event whose open time is at or before the current retained head:

```text
retained exact bar exists at that open time
AND
retained bar == event.bar
AND
fetch_record_at(key, open_time) exactly matches OHLCV + provenance
    -> DUPLICATE
    -> advance transport cursor
    -> do not schedule/re-evaluate a trigger

same retained identity but different canonical content/provenance
    -> CONFLICT
    -> do not advance cursor

not currently retained/provable and older than current live head
    -> RECONSTRUCTION_REQUIRED
    -> do not advance cursor
```

Keep D9A startup `ALREADY_REPRESENTED` semantics unchanged for the explicit startup DB-ahead boundary if useful for evidence.

Do not broaden `ALREADY_REPRESENTED` into a generic lifetime ledger.

Do not manufacture triggers from Timescale.

---

# 5. Blocking finding C — `_accepted_records` grows without bound

Current `DirectCursorInput` stores:

```text
_accepted_records:
  MarketSeriesKey -> {bar_open_at -> CanonicalMarketRecord}
```

for every accepted live candle and never prunes it.

Independent 1,000-candle probe:

```text
BarStore capacity      = 4
BarStore retained      = 4
accepted-record cache  = 1000
```

This defeats the bounded-runtime contract.

It is also not needed as a lifetime source of truth because exact durable canonical lookup already exists.

## 5.1 Required bounded design

Remove the lifetime cache or constrain any helper state to the current bounded retained identity surface.

Preferred simplest approach:

```text
BarStore = bounded bar identity/content
fetch_record_at() = authoritative provenance comparison when required
```

If provenance for current retained live bars needs a tiny process-local cache, it must be bounded by the corresponding BarStore capacity and evict whenever the BarStore evicts.

Do not add a large LRU, TTL framework, or second historical store.

Acceptance criterion:

```text
memory used for accepted-record duplicate/provenance bookkeeping
= O(sum registered BarStore capacities)
not O(total candles processed since process start)
```

Add a deterministic long-run regression with at least 1,000 sequential accepted records.

---

# 6. Blocking finding D — `LanePollResult` leaks prior transaction success into a later failure

`LiveLane` currently keeps persistent:

```text
last_policy_status
last_publication_outcome
last_finalization_status
last_checkpoint_result
```

and `LanePollResult` is built from those values plus the current pending cutoff.

Two problems result.

## 6.1 Successful transaction loses its cutoff

On successful finalization D9B clears:

```text
pending_trigger_cutoff = None
```

before `LanePollResult` is built.

So a successful poll can report:

```text
status=LIVE
policy_status=SIGNAL
publication_outcome=PUBLISHED
finalization_status=COMMITTED
trigger_cutoff=None
```

The evidence does not identify which cutoff actually completed.

## 6.2 Later failure inherits stale success fields

Independent reproduction:

```text
poll 1: SIGNAL -> PUBLISHED -> COMMITTED
poll 2: publisher raises before ACK/finalization
```

Current poll 2 evidence:

```text
status=HALTED
trigger_cutoff=<poll2 cutoff>
policy_status=SIGNAL
publication_outcome=PUBLISHED      # stale poll1 value
finalization_status=COMMITTED      # stale poll1 value
reason=live finalization failed: broker down
```

Underlying state/watermark is safe, but the exported evidence is false and would mislead D9C observability.

## 6.3 Required result semantics

`LanePollResult` must describe the **current poll/current attempted transaction**, not historical last-success state.

Use a small transaction-local accumulator or explicitly reset attempt fields when a new trigger begins.

Required behavior:

```text
successful cutoff T:
  trigger_cutoff=T
  policy_status=current T status
  publication_outcome=current T outcome or None for NO_SIGNAL
  finalization_status=current T result
  checkpoint_result=current T checkpoint result or None

failed cutoff T+1 before broker ACK:
  trigger_cutoff=T+1
  policy_status=current status if reached
  publication_outcome=None
  finalization_status=None
  checkpoint_result=None
  reason=current failure
```

Do not add an unbounded event history.

If long-lived "last successful" operator metrics are useful later, keep them separately and name them unambiguously; they must not contaminate `LanePollResult`.

---

# 7. Preserve all already-correct D9B semantics

Do not regress:

```text
direct XREAD only
None startup tail -> 0-0, never $
numeric stream-ID validation
DB-ahead startup ALREADY_REPRESENTED
forward market gap -> reconstruction-required
same-identity different canonical content -> conflict
one pending trigger/lane
newer trigger cannot overtake unresolved trigger
no trigger manufactured from DB
one bounded non-trigger Timescale context reconciliation attempt
D6 prepare only after causal readiness
D8 canonical envelope and preflight
exact market-time signal stream ID
exact XRANGE preflight
ambiguous XADD exact-ID reconciliation
PUBLISHED / ALREADY_IDENTICAL commit exactly once
CONFLICT / FAILED abort
input cursor independent from lane outcome
checkpoint only after D8 committed state/watermark
checkpoint CONFLICT/REJECTED_OLDER/INSERTED anomaly halts after commit
checkpoint failure never rolls back already published signal/state/watermark
SR NO_SIGNAL live state progression
```

No changes to signal wire schema or downstream risk semantics.

---

# 8. D9B runtime settings

The strict settings already exist:

```text
decision.live_input.batch_size
decision.live_input.block_ms
decision.signal_publication.stream_maxlen
decision.signal_publication.stream_approximate
```

Current bounded primitive constructors also have equivalent defaults.

Do **not** create a service/bootstrap solely to wire these in this remediation. D9C may own process composition from loaded `DecisionConfig`.

If a tiny existing construction seam can consume the approved settings without adding D9C lifecycle code, that is acceptable, but it is not a blocker for this remediation.

Do not duplicate or add transport knobs.

---

# 9. Required adversarial tests

Expand the D9B focused suite. Do not chase an exact final count; cover the behaviors.

## 9.1 Per-stream transport precedence

Add the exact regression:

```text
same stream, XREAD transport order:
  ID 10 -> new live trigger T1
  ID 11 -> older DB-ahead/represented T0
```

Prove:

```text
ID 10 is accepted before ID 11
T1 trigger is evaluated/finalized exactly once
ID 11 may then classify represented/duplicate under the approved rules
cursor ends at ID 11
no self-created non-forward error
```

Also cover a same-stream market-time regression generally: later stream ID with older market time must never be moved in front of the prior ID.

## 9.2 Same-cutoff multi-stream ordering

Use a lane requiring trigger + context series.

In one XREAD batch, return same-cutoff context and trigger records in opposite stream ordering.

Prove both canonical bars are applied before the cutoff's D6 evaluation.

Do not enlarge BarStore capacity to make the test pass.

## 9.3 Pending trigger then later context stream

```text
poll A: trigger T arrives, context T absent
  -> one pending T
  -> no D6 prepare

poll B: context stream catches up
  -> pending T becomes ready
  -> evaluate exactly once
```

## 9.4 Timescale-reconciled context then delayed stream catch-up

Use at least two context bars appended by bounded DB reconciliation.

Then deliver their delayed stream messages.

Prove:

```text
exact retained reconciled bars -> DUPLICATE/represented acceptance
cursor advances
no lane re-evaluation from context duplicate
stream is not blocked
```

A different payload/provenance for the same retained open must remain `CONFLICT`.

An old post-startup bar no longer retained/provable must remain `RECONSTRUCTION_REQUIRED`.

## 9.5 Input identity-memory boundedness

Process at least 1,000 sequential accepted bars through a small-capacity BarStore.

Prove any input duplicate/provenance bookkeeping remains bounded by the registered retained capacity (or is absent entirely).

Do not inspect only `BarStore`; assert the helper state itself cannot grow with lifetime candle count.

## 9.6 Pending overrun

```text
pending trigger T remains unresolved
trigger T+1 arrives
-> lane RECONSTRUCTION_REQUIRED
-> T+1 is not evaluated
-> state/watermark do not skip T
```

## 9.7 DB never manufactures trigger

Even if Timescale contains a newer trigger candle, absence of an accepted post-startup trigger-stream event must not schedule a live decision.

## 9.8 Full live ACK matrix

Exercise the outcomes through `LiveDecisionRuntime`, not publisher-only tests:

```text
PUBLISHED           -> COMMITTED / watermark advances
ALREADY_IDENTICAL   -> COMMITTED / watermark advances
CONFLICT            -> ABORTED / watermark unchanged
FAILED              -> ABORTED / watermark unchanged
```

For a stateful decision-capable test plugin, also prove proposed state commit/abort if practical without creating production plugin code.

## 9.9 Transaction-local evidence

Prove:

```text
successful poll exposes completed trigger_cutoff
later failed poll has no stale previous publication/finalization/checkpoint fields
waiting poll does not inherit a prior completed transaction as its own
```

## 9.10 Preserve real SR and checkpoint ordering

Keep/extend:

```text
SR live NO_SIGNAL -> state commit -> watermark -> UPDATED checkpoint
sequential SR triggers progress exactly one step each
checkpoint failure after commit retains external/in-memory commit and halts
```

---

# 10. Signal transport scope

`ValkeySignalPublisher` passed independent review of its core algorithm.

Do not rewrite it merely because this remediation touches D9B.

Retain:

```text
exact-ID XRANGE
newer-head guard
explicit-ID XADD
post-exception exact lookup
ALREADY_IDENTICAL semantic fingerprint
CONFLICT on different/undecodable exact entry
FAILED when outcome remains unresolved
CancelledError propagation
```

One direct check confirmed D8 metadata tuple/list normalization still yields the same semantic signal fingerprint after Valkey encode/decode; no change is needed there.

---

# 11. Expected production scope

Prefer changes limited to:

```text
src/apps/decision_app/live_input.py
src/apps/decision_app/live_runtime.py
```

Potentially small test/support changes in:

```text
tests/decision/test_d9b_live_input.py
tests/decision/test_d9b_live_runtime.py
tests/decision/test_d9b_signal_transport.py  # only if integration fixture support is needed
```

`readiness.py`, `startup.py`, `publication.py`, `finalization.py`, D6 state/runtime, and signal contracts should remain unchanged unless a direct regression demonstrates a narrowly necessary fix.

Do not change canonical ingestion production code.

---

# 12. Validation

Use:

```text
/Users/kajukatli/projects/flipperAgent/.venv/bin/python
/Users/kajukatli/.local/bin/ruff
```

Run focused D9B first.

Then run:

```text
complete tests/decision
D9A focused startup/reconstruction surface
D8 policy/publication/finalization surface
D7A real SR adapter/runtime tests
relevant non-research SR core/config/lifecycle/replay/serialization tests
commons ConfigManager/Valkey contract tests
canonical ingestion outbox/HTF/provenance contract tests
current risk tests relevant to:
  risk-profile resolution
  signal timestamp/staleness seconds semantics
  ATR sizing / stop-loss metadata
```

Attempt broader ingestion validation only within the already-known environment limits.

Local Timescale/Valkey certification remains conditional on a genuinely usable repository harness.

If the worktree still lacks `.env`:

```text
LOCAL_INFRASTRUCTURE_VALIDATION_BLOCKED_ENVIRONMENT
```

Do not create/copy credentials, `.env`, or shared runtime state merely to force the gate.

Static:

```text
ruff check
ruff format --check
python -m compileall -q <decision scope>
git diff --check
untracked/trailing whitespace scan
AST production import boundary scan
forbidden D9C/PEL/PriceRelay scan
repo-local __pycache__ cleanup
```

Production D9B code must remain free of imports from:

```text
apps.ingestion_app
apps.signal_app
apps.strategy_app
apps.risk_app
apps.execution_app
```

Tests may use canonical ingestion builders for parity fixtures.

---

# 13. Two-pass coder self-review

## Pass 1 — causal/transaction correctness

Explicitly verify:

```text
per-stream numeric ID order cannot be violated by market-time grouping
delayed older market event cannot cause an earlier transport ID to be skipped
same-cutoff multi-stream context is visible before evaluation
DB-reconciled retained context accepts delayed exact stream duplicates
old unretained live history still fails closed
input helper memory is bounded
cursor advances only after accepted/represented records
cursor never rolls back on lane failure
pending trigger cannot be overtaken
DB cannot manufacture a live trigger
D6 prepare runs only on causal-ready view
D8 envelope/finalizer remain authoritative
PUBLISHED/ALREADY_IDENTICAL commit exactly once
CONFLICT/FAILED do not commit state/watermark
checkpoint remains post-finalization only
checkpoint failure after commit never rolls back side effects
LanePollResult fields belong to the current attempted cutoff only
real SR progression remains exact
```

## Pass 2 — architecture/simplicity

Verify:

```text
no global event-history cache
no generic scheduler/priority queue framework
no consumer group/PEL
no event bus
no signal outbox
no service supervisor
no actor/task-per-lane
no new checkpoint abstraction
no D8/D6 redesign
no legacy FeatureVector bridge
no app-to-app production imports
no PriceRelay assumption
no D9C leakage
no D7B refactor
no production synthetic model config
```

---

# 14. Handoff back to orchestrator

Update:

```text
plans/coder-to-orchestrator-decision-app-d9b-live-signal-runtime-v1.md
```

Record:

```text
files/symbols changed
per-stream transport-order merge rule
transport-order inversion regression evidence
same-cutoff cross-stream evidence
DB-context delayed-stream catch-up rule/evidence
retained duplicate vs true late-history rule
input identity-memory bound and long-run evidence
pending trigger/context/overrun evidence
DB-never-manufactures-trigger evidence
full live PUBLISHED/ALREADY_IDENTICAL/CONFLICT/FAILED matrix
transaction-local LanePollResult semantics
real SR NO_SIGNAL evidence
checkpoint post-commit durability evidence
focused and complete decision counts
SR/ingestion/commons/risk compatibility counts
local infrastructure availability status
Ruff/format/compile/diff/import/forbidden/cache evidence
Pass 1 findings
Pass 2 findings
residual risks
D9C + PriceRelay carry-forward
```

Do not claim full service/runtime operation or production readiness.

Do not start D9C automatically.

Final line exactly:

```text
DECISION_APP_D9B_LIVE_SIGNAL_RUNTIME_READY_FOR_REVIEW
```
