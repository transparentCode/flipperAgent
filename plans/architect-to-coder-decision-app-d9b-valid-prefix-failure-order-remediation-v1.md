---
goal: Preserve valid per-stream XREAD prefixes when a later record in the same bounded batch is malformed or non-forward, without changing approved D9B transaction semantics
stage: architect-to-coder
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d9b, remediation, xread, causality]
---

# Architect-to-coder — `decision_app` D9B valid-prefix failure-order remediation

## 1. Starting point

Use only the existing cumulative isolated worktree:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

Approved before this review:

```text
D0-D8
D7A
D9A
```

D9B has completed its first remediation and the following review findings are now considered fixed and frozen:

```text
per-stream transport precedence / k-way market coordination
retained DB-reconciled context duplicate acceptance
removal of unbounded _accepted_records ledger
transaction-local LanePollResult evidence
D8 exact-ID publication and finalization semantics
post-finalization checkpoint ordering
```

Do not reopen those designs except where this narrow ordering fix needs a small local adjustment.

D9C, PriceRelay, lifecycle subscription, FastAPI, Docker/service wiring, cutover, and D7B remain out of scope.

Do not commit, merge, push, switch branches, reset, restore, or modify the primary checkout.

---

# 2. Confirmed remaining blocker

The D9B handoff explicitly froze this per-stream batch rule:

```text
parse each stream in returned stream-ID order
process the valid prefix
at the first invalid/blocking record, stop that stream
ignore only later records from that stream in that poll
```

Current `DirectCursorInput.read_once()` instead mutates `_blocked_streams` immediately when a later record fails parse/stream-ID validation.

`LiveDecisionRuntime.poll_once()` initializes `failed_streams` from those parse failures before it processes already-parsed records.

Therefore a valid prefix from the same stream is discarded.

Independent reproduction:

```text
startup cursor = 2-0
XREAD stream batch:
    3-0 valid canonical live candle
    4-0 malformed event_type
```

Current result:

```text
input_results:
    4-0 -> MALFORMED

InputReadCursor:
    remains 2-0

valid 3-0:
    never accepted
    never scheduled
    never finalized

lane:
    RECONSTRUCTION_REQUIRED
```

The malformed `4-0` must block the stream, but it must not erase the safe valid prefix `3-0` that precedes it in transport order.

This is a D9B input-ordering defect, not a D6/D8 defect.

---

# 3. Required semantic rule

For each returned stream independently, preserve exact transport order.

Given:

```text
cursor = C
returned IDs = I1 < I2 < ... < In
```

process conceptually:

```text
I1 valid -> eligible for normal D9B acceptance
I2 valid -> eligible after I1
...
Ik invalid/blocking -> emit failure at Ik and block stream
I(k+1..n) -> ignored for this poll/runtime instance
```

Rules:

```text
valid prefix is not discarded because of a later parse failure
cursor may advance through the last accepted prefix record
cursor must never advance to/past the failed record
later suffix records are never accepted
failure still marks only affected series/lanes reconstruction-required
unrelated streams continue
```

If a valid prefix trigger finalizes successfully before a later malformed transport record is reached, that committed transaction remains committed. The later malformed record then halts/reconstruction-requires the affected lane for subsequent work. Do not roll back the earlier signal/state/watermark.

This is consistent with the already-approved independence of:

```text
InputReadCursor
LaneCommitWatermark
committed D6 state
```

---

# 4. Implementation constraint

Do not solve this by buffering an unbounded queue or by adding a consumer group.

Keep `read_once()` / `poll_once()` bounded.

A small typed representation of an ordered per-stream parse failure is acceptable.

Possible minimal approaches include either:

```text
A. InputReadBatch carries per-stream ordered items / a failure position
```

or

```text
B. parsed records retain transport ordinal and failures carry a matching
   per-stream ordinal / predecessor ID so poll_once can process the prefix first
```

or an equivalently small design.

The important contract is semantic, not the exact class name.

Do not introduce:

```text
generic event envelope
queue framework
actor/task per stream
persistent cursor table
retry/backoff framework
PEL machinery
```

---

# 5. `DirectCursorInput.read_once()` behavior

The parser may validate the whole bounded XREAD response, but it must not make an already-parsed valid prefix unusable merely because a later record fails.

For one stream:

```text
3-0 valid
4-0 malformed
5-0 otherwise valid
```

returned bounded evidence must preserve enough ordering information for runtime processing to achieve:

```text
accept 3-0
then surface/block at 4-0
never accept 5-0
```

The parser must still reject immediately unsafe stream-level shapes where no ordered prefix can be established, for example:

```text
unknown returned stream key
stream entries are not a sequence
```

No need to invent prefix semantics where there is no valid stream entry sequence.

For entry-local failure after a valid prefix, preserve the prefix.

Entry-local failures include at least:

```text
malformed/non-normalizable stream ID
non-forward returned stream ID
invalid candle event schema/producer/event type
invalid canonical payload/geometry/provenance
invalid entry pair shape after earlier valid entries
```

---

# 6. `LiveDecisionRuntime.poll_once()` behavior

Do not pre-mark an entire stream failed before processing its known-valid prefix.

Within the existing per-stream-head/k-way merge:

1. expose only the next ordered item for each stream;
2. valid record -> run existing `DirectCursorInput.accept()`;
3. if accepted, preserve existing market-cutoff coordination and trigger semantics;
4. when the stream's failure marker becomes its next ordered item:
   - mark/block the stream;
   - emit the typed failure;
   - mark only dependent lanes reconstruction-required;
   - stop exposing later items from that stream;
5. unrelated stream heads remain eligible.

Do not globally sort records in a way that violates per-stream transport precedence.

Do not allow a parse failure at a later stream ID to move backward and invalidate already-committed earlier-prefix transactions.

---

# 7. Cursor semantics

Prove explicitly:

```text
startup cursor 2-0
3-0 valid accepted
4-0 malformed

final cursor = 3-0
not 2-0
not 4-0
```

`latest_market_as_of` remains the max accepted canonical cutoff and must not be derived from the malformed record.

If prefix acceptance itself returns:

```text
RECONSTRUCTION_REQUIRED
CONFLICT
MALFORMED
```

then existing acceptance semantics win: do not advance past that acceptance failure, and do not continue to a later parse failure.

---

# 8. Lane transaction semantics

Do not change D8.

If valid prefix record `3-0` is a live authoritative trigger and fully ready:

```text
3-0 INSERTED
-> D6 prepare
-> D8 policy
-> SIGNAL/NO_SIGNAL finalization
-> state/watermark
-> checkpoint if stateful
```

and later `4-0` is malformed:

```text
stream/lane becomes RECONSTRUCTION_REQUIRED after the completed 3-0 transaction
```

The returned `LanePollResult` may truthfully contain both:

```text
status = RECONSTRUCTION_REQUIRED
trigger_cutoff = cutoff from successful 3-0
publication/finalization fields = actual 3-0 transaction evidence
reason = later 4-0 stream failure
```

That is not stale evidence because both occurred in the same bounded poll in that order.

Do not clear valid same-poll transaction evidence merely because a later stream failure occurs.

For a prefix trigger that is still WAITING when the later malformed record arrives, halt/reconstruction-require it without finalization.

---

# 9. Required regressions

Add focused tests to `tests/decision/test_d9b_live_input.py` and/or `test_d9b_live_runtime.py`.

At minimum prove:

### 9.1 Valid prefix then malformed canonical event

```text
cursor starts 2-0
3-0 valid trigger
4-0 invalid event_type/schema/payload
```

Expected:

```text
3-0 accepted before failure
4-0 MALFORMED
cursor ends 3-0
stream blocked after 4-0
no later suffix accepted
```

For live runtime, if 3-0 is ready and decision-capable:

```text
3-0 transaction finalizes exactly once
then lane ends RECONSTRUCTION_REQUIRED because of 4-0
```

### 9.2 Valid prefix then non-forward stream ID

Example bounded response:

```text
3-0 valid
3-0 or 2-9 non-forward as next entry
```

Expected:

```text
first 3-0 is preserved/accepted
second entry fails
cursor remains first 3-0
```

### 9.3 Suffix ignored

```text
3-0 valid
4-0 malformed
5-0 otherwise valid
```

Expected:

```text
3-0 processed
4-0 failure surfaced
5-0 never processed
```

### 9.4 Other stream continues

One stream:

```text
valid prefix -> malformed
```

second unrelated stream:

```text
valid forward entries
```

Expected unrelated stream cursor/input remains live and independent.

### 9.5 Existing remediation regressions remain green

Do not weaken:

```text
same-stream market-time inversion
same-cutoff cross-stream context/trigger
DB-reconciled context -> delayed exact duplicate
pending trigger -> context catch-up
pending overrun
DB never manufactures trigger
1000-candle bounded-memory proof
transaction-local poll evidence
full publication ACK matrix behavior
real SR NO_SIGNAL/checkpoint path
```

---

# 10. Preserve already-approved D9B contracts

Do not change:

```text
Direct XREAD only
0-0 startup fallback
D9A captured-tail attachment
canonical ingestion parser/provenance
BarStore boundedness
one pending trigger per lane
bounded non-trigger context reconciliation
D8 SignalPublicationEnvelope
exact-ID signal publisher
PUBLISHED / ALREADY_IDENTICAL commit semantics
CONFLICT / FAILED abort semantics
checkpoint-after-finalization ordering
stateful checkpoint halt-on-durability-failure
legacy risk signal wire compatibility
```

No D9C work.

---

# 11. Validation

Run focused D9B first:

```text
tests/decision/test_d9b_live_input.py
tests/decision/test_d9b_signal_transport.py
tests/decision/test_d9b_live_runtime.py
```

Then:

```text
complete tests/decision
D9A/D8 focused compatibility
relevant non-research SR adapter/core/replay tests
risk/commons/signal transport compatibility
canonical ingestion outbox/HTF/provenance contract slice
```

Static:

```text
Ruff check
Ruff format --check
compileall
git diff --check
trailing whitespace
production app import boundary
forbidden XREADGROUP/XACK/XAUTOCLAIM/PEL/PriceRelay/FastAPI/service-loop scan
repo-local __pycache__ cleanup
```

Real local Timescale/Valkey remains optional only when the repository-provided environment is genuinely usable. If `.env` is still absent, record the environment gate exactly; do not create/copy credentials or touch external state.

---

# 12. Two-pass coder self-review

Pass 1 — causal correctness:

```text
valid stream prefix survives later parse failure
failure position itself never advances cursor
suffix after failure is ignored
other streams remain independent
successful prefix transaction is not rolled back by later malformed record
per-stream ID order remains authoritative
market cutoff coordination still works across streams
DB-context delayed duplicate remains safe
pending/overrun semantics unchanged
D8 state/publication/checkpoint ordering unchanged
```

Pass 2 — simplicity/scope:

```text
no queue framework
no consumer groups/PEL
no persistent cursor store
no generic ordered-event framework
no D6/D8 redesign
no PriceRelay
no FastAPI/service loop
no D9C
no legacy app changes
```

---

# 13. Handoff

Update:

```text
plans/coder-to-orchestrator-decision-app-d9b-live-signal-runtime-v1.md
```

Record:

```text
valid-prefix failure-order implementation
malformed/non-forward prefix regressions
suffix suppression evidence
unrelated-stream isolation evidence
cursor evidence
same-poll committed-prefix + later failure evidence
focused/cumulative test counts
compatibility counts
static/import/forbidden/cache evidence
local infra status
Pass 1 findings
Pass 2 findings
residual risks
```

Do not start D9C automatically.

Final line exactly:

```text
DECISION_APP_D9B_LIVE_SIGNAL_RUNTIME_READY_FOR_REVIEW
```
