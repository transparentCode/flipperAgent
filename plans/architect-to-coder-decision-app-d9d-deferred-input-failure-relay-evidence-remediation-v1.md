---
goal: Make D9D bounded poll relay evidence reflect final PriceRelay continuity after deferred canonical input failure without replaying or republishing
stage: architect-to-coder
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d9d, price-relay, continuity, remediation]
---

# D9D deferred-input-failure relay evidence remediation

## 1. Starting state

Work only in the existing cumulative isolated worktree:

`/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0`

Frozen programme state before this remediation:

```text
D0-D9C                         APPROVED
Pre-D9D architecture hardening APPROVED
D9D target/retry remediation   correct
D9D input-gap continuity       correct internally
D10                            NOT STARTED
```

Do not commit, merge, push, switch branches, reset, restore, or touch the primary checkout.

## 2. Verified remaining defect

The canonical-source continuity remediation correctly makes the internal relay progress `UNRESOLVED` when a known input series fails.

However, D9B's valid-prefix/deferred-parser-failure ordering can leave `DecisionPollResult.relay_results` stale for the same bounded poll.

Independent reproduction:

```text
one XREAD batch on the relay series:
  3-0 valid canonical bar
  4-0 malformed canonical event
  5-0 otherwise valid suffix

bounded poll ordering:
  3-0 accepted
  PriceRelay publishes 3-0 PriceUpdate
  relay result at that point = CONTINUOUS / PUBLISHED
  deferred 4-0 parser failure then surfaces
  PriceRelay.mark_input_failure(...) -> internal progress UNRESOLVED

current returned evidence:
  DecisionPollResult.relay_results[plan] = CONTINUOUS / PUBLISHED   WRONG FINAL STATE

actual final relay state:
  PriceRelay.progress[plan] = UNRESOLVED / input_failure=true       CORRECT
```

The input result itself is correct:

```text
3-0 INSERTED
4-0 MALFORMED
stream blocked at 3-0
suffix not processed
```

This is an evidence-consistency defect, not a failure to invalidate the source.

## 3. Required invariant

At return from one `LiveDecisionRuntime.poll_once()`:

```text
DecisionPollResult.relay_results
```

must describe the **final PriceRelay state after every deferred input failure has surfaced**.

For a valid prefix followed by a malformed/non-forward suffix on the same canonical relay series:

```text
valid prefix PriceUpdate publication remains committed
InputReadCursor remains at valid prefix
input stream becomes blocked
PriceRelay final continuity = UNRESOLVED
DecisionPollResult relay continuity = UNRESOLVED
idle next poll remains UNRESOLVED
no suffix PriceUpdate is published
```

If the valid prefix produced `PUBLISHED` or `ALREADY_IDENTICAL`, preserve that publication outcome as evidence of what successfully happened earlier in the same bounded poll while reporting the final continuity state as `UNRESOLVED`.

A suitable final result is conceptually:

```text
publication_outcome = PUBLISHED | ALREADY_IDENTICAL  # valid prefix transaction
published_market_as_of = valid prefix close
continuity_status = UNRESOLVED                       # final source trust state
reason = deferred canonical input failure
```

Do not roll back or hide the successful prefix publication.

## 4. Smallest implementation

Keep the existing D9B ordering. Do NOT surface deferred parser failures before the valid prefix transaction; D9B valid-prefix semantics are frozen.

Keep:

```text
accept valid prefix
-> PriceRelay valid prefix publication
-> lane transaction if enabled
-> surface deferred failure
```

After `PriceRelay.mark_input_failure()` changes final relay progress, refresh only the affected relay evidence already held by the current `poll_once()` result accumulator.

Acceptable minimal approaches include:

1. make `PriceRelay.mark_input_failure()` return affected relay plan IDs or bounded current-state results, then merge those into the local `relay_results`; or
2. add one small pure/read-only PriceRelay result snapshot helper and refresh only the invalidated plan IDs.

Choose the smallest readable option.

The refresh must be pure/in-memory.

### Forbidden implementation

Do NOT solve this by calling another broad:

```python
await price_relay.reconcile_all()
```

after deferred failures.

That could perform an unintended second catch-up/publication for unrelated or partially caught-up relay plans in one market poll and violate the existing `batch_size` publication bound.

Also do not add:

```text
new task
new queue
new event bus
new relay state machine class
new persistence
new config
new retry policy
new generic evidence framework
```

## 5. Evidence merge semantics

For an affected relay plan, final bounded evidence must use:

```text
continuity_status       <- current PriceRelay.progress final state
published_market_as_of  <- current PriceRelay.progress latest successful cutoff
reason                  <- current input-failure reason/evidence
backlog_bars            <- bounded final relay evidence
```

For fields representing successful work already completed earlier in this same poll:

```text
publication_outcome
original successful target_market_as_of when the deferred failure has no parseable target
```

preserve the earlier relay result when semantically valid.

Do not invent a market target for a malformed event whose market time could not be parsed.

If a failure itself has a valid observed market cutoff, the existing input-failure evidence may retain that cutoff according to current D9D logic.

## 6. Independence

Refreshing final evidence for relay A must not alter relay B.

Prove:

```text
relay A valid prefix publishes
relay A deferred malformed suffix -> A final UNRESOLVED
relay B in same runtime remains CONTINUOUS
relay B publication/catch-up occurs at most once for the poll
```

No global relay reconciliation is permitted solely to refresh evidence.

## 7. Required regression

Add a focused D9D runtime regression, preferably in:

`tests/decision/test_d9d_price_relay_runtime.py`

Use a real `LiveDecisionRuntime` and a real `PriceRelay`.

At minimum construct one same-stream batch:

```text
valid relay bar
malformed suffix
later otherwise-valid suffix
```

Assert after the single `poll_once()`:

```text
input_results == [INSERTED, MALFORMED]
input cursor == valid prefix ID
stream is blocked
later suffix was not accepted

exactly one PriceUpdate exists for valid prefix
no PriceUpdate exists for malformed/later suffix

returned relay result:
  continuity_status == UNRESOLVED
  published_market_as_of == valid prefix bar close
  publication_outcome == PUBLISHED (or ALREADY_IDENTICAL if deliberately preseeded)
  reason identifies input failure

PriceRelay.progress:
  continuity_status == UNRESOLVED
  latest_market_as_of == valid prefix close
  gap_evidence.input_failure == true
```

Then call an idle second `poll_once()` and prove:

```text
relay remains UNRESOLVED
no additional PriceUpdate
blocked cursor unchanged
```

Preserve the existing D9B valid-prefix signal/lane transaction semantics; this remediation must not change them.

Also add/retain one independence proof if not already naturally covered.

## 8. Retain all already-approved D9D behaviors

The remediation must not change:

```text
monotonic pending relay targets
bounded idle catch-up
FAILED -> retryable GAP_DETECTED
CONFLICT -> terminal UNRESOLVED
first-candle bootstrap
same-series forward-gap invalidation
pre-bootstrap input failure persistence
fresh-generation recovery
relay-only assets
operator PAUSED input + PriceRelay behavior
risk PriceUpdate wire contract
risk bar-close timestamp normalization
pre-entry risk filtering
risk price PEL reclaim
pending-close duplicate suppression
```

## 9. Anti-overengineering / scope constraints

Do not add or modify any model/plugin.

No D7B/Momentum work.
No model refactoring.
No D10.
No resource certification.
No shadow/cutover work.
No production decision asset YAML.
No `main.py`, HTTP port, or Compose registration.
No decision consumer group/PEL.
No PriceRelay task/worker.

Keep the fix local to final relay evidence synchronization after canonical input invalidation.

## 10. Validation

Run at minimum:

```text
new exact deferred-failure relay regression
all D9D focused tests
tests/decision
tests/risk
tests/signals + tests/integration/signals
tests/commons + tests/execution
architecture guardrails
scoped Ruff check
scoped Ruff format --check
compileall or equivalent syntax validation
git diff --check
cache cleanup
```

Re-run the previous D9D critical cases explicitly:

```text
forward canonical gap -> returned relay UNRESOLVED
idle persistence
transient downstream FAILED -> retryable, not terminal
multi-bar target catch-up
first-candle bootstrap
paused lifecycle fresh generation
risk PEL/idempotency
```

The absent `.env` remains environment-only; do not create/copy credentials or touch external Timescale/Valkey state.

## 11. Handoff

Update:

`plans/coder-to-orchestrator-decision-app-d9d-price-relay-risk-continuity-v1.md`

Include the exact before/after valid-prefix+malformed-suffix evidence and current validation counts.

No D10 work.

Stop with exactly:

`DECISION_APP_D9D_PRICE_RELAY_RISK_CONTINUITY_READY_FOR_REVIEW`
