---
goal: Propagate canonical input-series failure into PriceRelay continuity so a blocked relay source can never remain falsely CONTINUOUS
stage: architect-to-coder
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d9d, price-relay, continuity, remediation]
---

# D9D input-gap / relay-continuity remediation

## 1. Starting state

Work only in:

`/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0`

D0-D9C and Pre-D9D architecture hardening remain approved. The previous D9D target/retry remediation is verified: retained targets, retryable `FAILED`, first-candle bootstrap, paused lifecycle relay behavior, and risk PEL changes are correct.

Do not reopen those contracts unless required by this defect.

## 2. Blocking defect

Frozen D0 contract:

> PriceRelay must not silently claim continuity after a detected input gap.

Current live sequence for a relay-owned canonical series:

```text
startup BarStore/relay baseline: bar0 close
XREAD next event: bar2 (bar1 stream event missing)

DirectCursorInput.accept(bar2)
  -> RECONSTRUCTION_REQUIRED
  -> reason = forward canonical market gap
  -> input stream blocked
  -> InputReadCursor remains at old stream ID

LiveDecisionRuntime
  -> accepted_bars does not include bar2
  -> PriceRelay receives no candidate/target

PriceRelay
  -> keeps old baseline
  -> reports CONTINUOUS
```

Independent reproduction observed:

```text
input disposition = RECONSTRUCTION_REQUIRED
input reason      = forward canonical market gap
input blocked     = true
relay result      = CONTINUOUS
relay progress    = CONTINUOUS
relay latest      = old startup cutoff
```

This is false continuity evidence. The service becomes DEGRADED because of the input failure, but `PriceRelayProgress` itself remains incorrect. D12 is expected to use relay continuity as part of cutover safety, so the relay contract must be truthful independently.

## 3. Selected design

Keep the existing D9B input-failure boundary. Do not add a new recovery service, task, DB poller, queue, journal, or PriceRelay worker.

Use the existing `LiveDecisionRuntime._mark_series_failure(series_key, reason)` boundary to notify PriceRelay when that same canonical source series is no longer trustworthy.

Add one small PriceRelay operation with semantics equivalent to:

```python
PriceRelay.mark_input_failure(
    series_key: MarketSeriesKey,
    *,
    reason: str,
    observed_target_market_as_of: datetime | None = None,
) -> None
```

Name may differ if a smaller existing naming style is clearer.

Behavior for every relay plan whose `plan_series_key(plan) == series_key`:

```text
latest_market_as_of
    -> preserve last PUBLISHED / ALREADY_IDENTICAL cutoff

continuity_status
    -> UNRESOLVED

pending target
    -> may retain/max the observed failed-event cutoff for bounded evidence
       but MUST NOT trigger automatic publication while source input is blocked

bootstrap_allowed
    -> remove / disable

gap evidence
    -> bounded current facts only:
       reason
       input_failure = true (or equivalent explicit fact)
       observed_target_market_as_of when known
       backlog when safely derivable
```

The affected relay is terminal for the current generation. Recovery requires the existing fresh-generation boundaries:

```text
manual reconnect/resume where applicable
or
configured lifecycle reconciliation
```

A fresh D9A generation revalidates canonical history, input cursor, manifest state, and downstream PriceRelay tail before continuity can become `CONTINUOUS` again.

## 4. Live runtime integration

Modify the existing `_mark_series_failure()` path rather than adding another failure dispatcher.

Current responsibility:

```text
series failure
  -> halt affected model lanes
```

Required responsibility:

```text
series failure
  -> halt affected model lanes
  -> mark PriceRelay plans sourced from same canonical series UNRESOLVED
```

If `series_key is None`, preserve current behavior and do not guess a relay identity.

For an accept-time failure where the failed event is known, pass its `market_as_of` as bounded target evidence if convenient. For deferred parser failures with a known series but no trustworthy parsed bar cutoff, marking unresolved with the failure reason is sufficient.

Do not publish the failed/unaccepted candidate through PriceRelay merely to catch up. Once the canonical live input stream is blocked, the relay cannot claim continuing live source coverage in this generation.

## 5. Failure classification

At minimum, same-series PriceRelay continuity must become `UNRESOLVED` for input failures already routed through `_mark_series_failure`, including:

```text
RECONSTRUCTION_REQUIRED
CONFLICT
MALFORMED
```

when the `MarketSeriesKey` is known.

This does not mean all such failures have identical root causes. The common relay fact is simply that the current canonical live input source is no longer safe to treat as continuous.

Do not convert transient Valkey *price publication* `FAILED` into terminal state; that previous remediation remains frozen as retryable `GAP_DETECTED`.

Distinguish:

```text
PriceRelay publication FAILED
    -> retryable GAP_DETECTED

canonical input series failure/block
    -> current-generation UNRESOLVED
```

## 6. Independence requirements

One failed input/relay series must not affect unrelated relay plans or unrelated input streams.

Required behavior:

```text
series A forward input gap
  -> input A blocked
  -> relay A UNRESOLVED

series B valid same/next poll
  -> input B continues
  -> relay B publishes/continues normally
```

No whole-generation automatic rebuild is introduced.

No rollback of:

```text
InputReadCursor for already accepted unrelated series
BarStore progress for unrelated series
LaneCommitWatermark for already committed lanes
PriceRelayProgress for unrelated relay plans
```

## 7. Required tests

Add focused regressions, preferably to existing D9D runtime/core files.

### A. Same-series forward gap invalidates relay continuity

Construct a relay-only runtime:

```text
startup canonical/relay baseline = bar0
canonical durable history contains bar0, bar1, bar2
live XREAD returns bar2 directly
```

Assert:

```text
input result = RECONSTRUCTION_REQUIRED
reason includes forward canonical market gap
input cursor does not advance through bar2
input stream is blocked
relay latest_market_as_of remains bar0 close
relay continuity_status = UNRESOLVED
relay result does not report CONTINUOUS
no PriceUpdate for the failed candidate is published
```

### B. Subsequent idle poll remains unresolved

After A, call another bounded poll with no input.

Assert relay A remains `UNRESOLVED`; it must not fall back to the old startup `CONTINUOUS` baseline and must not silently retry publication while the input source remains blocked.

### C. Unrelated relay continues

Use two canonical relay series. Cause a forward gap only on A while B receives a valid bar.

Assert:

```text
A -> UNRESOLVED
B -> PUBLISHED/ALREADY_IDENTICAL and CONTINUOUS
B input cursor advances
```

### D. Model-lane failure remains independent

Keep existing proof that a lane-local `RECONSTRUCTION_REQUIRED` unrelated to the relay source does not stop a healthy relay. Do not accidentally make all lane failures invalidate PriceRelay.

### E. Price publication FAILED remains retryable

Keep previous regression green:

```text
price XADD FAILED
  -> GAP_DETECTED
idle next poll
  -> retry same exact ID
  -> CONTINUOUS after success
```

### F. Fresh generation may recover

After a current-generation input failure, construct a fresh generation with a continuous canonical startup history/tail and prove the new PriceRelay may bootstrap/catch up to `CONTINUOUS` normally. No persistent terminal flag may leak between generations.

## 8. Validation

Run at minimum:

```text
focused D9D tests
tests/decision
tests/risk
tests/signals + tests/integration/signals
tests/commons + tests/execution
architecture guardrails
scoped Ruff
Ruff format --check
compileall or equivalent syntax validation
git diff --check
repo-local cache cleanup
```

Do not force live infrastructure when `.env` is absent. Preserve:

`LOCAL_INFRASTRUCTURE_VALIDATION_BLOCKED_ENVIRONMENT`

No credentials or external/shared Valkey/Timescale state changes.

## 9. Frozen / forbidden

Do not change:

```text
D8 signal publication/finalization
D9A reconstruction architecture
D9B per-stream ordering / valid-prefix semantics
D9C two-task service architecture
retained PriceRelay target remediation
FAILED PriceRelay publication retry semantics
PriceUpdate wire fields/units
bar-close deterministic PriceRelay stream IDs
risk SL/TP / multi-TP / trailing mathematics
risk price PEL consumer group design
operator pause input+PriceRelay semantics
```

Do not add:

```text
new model/plugin integration
model refactoring
new PriceRelay task/worker/service
DB polling loop for relay recovery
persistent relay progress table
consumer group/PEL in decision_app
new retry/backoff config
D10 resource certification
D11 shadow work
D12 cutover work
main.py / decision service port / Compose registration
production decision asset YAML
```

## 10. Handoff

Update:

`plans/coder-to-orchestrator-decision-app-d9d-price-relay-risk-continuity-v1.md`

Include exact same-series gap evidence and validation counts.

Stop with exactly:

`DECISION_APP_D9D_PRICE_RELAY_RISK_CONTINUITY_READY_FOR_REVIEW`

Do not start D10 automatically.
