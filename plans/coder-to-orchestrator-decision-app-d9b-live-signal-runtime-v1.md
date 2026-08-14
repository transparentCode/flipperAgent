---
goal: Implement and remediate the bounded live decision input, signal publication, finalization, and checkpoint path
stage: coder-to-orchestrator
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, decision-app, d9b, live-runtime, valkey, publication]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Coder-to-orchestrator — `decision_app` D9B live signal runtime handoff

## Scope and starting state

D0–D8, D7A, and D9A were present in the cumulative isolated worktree. D7B,
D9C, PriceRelay recovery, and cutover remain deferred. Work started from
detached `HEAD` at:

```text
4fc0de62515112dc371e08a6cde503746c54f7f7
```

The worktree was already cumulative and dirty. Existing approved decision-app
files and the prior SR adapter changes were preserved. No commit, merge, push,
branch switch, reset, restore, or primary-checkout modification was performed.
No external database or broker state was created or mutated.

## D9B implementation

Added the three bounded live surfaces:

```text
src/apps/decision_app/live_input.py
  DirectCursorInput / LiveInputReader
  strict stream-ID normalization and numeric ordering
  bounded direct XREAD only
  canonical event acceptance/classification
  independent InputReadCursor advancement

src/apps/decision_app/signal_transport.py
  ValkeySignalPublisher
  exact-ID XRANGE preflight
  explicit market-time XADD
  identical/conflict/ambiguous-write reconciliation

src/apps/decision_app/live_runtime.py
  LiveDecisionRuntime.poll_once
  authoritative STARTUP_READY lane selection
  cutoff-grouped serial processing
  bounded context reconciliation
  D6 prepare -> D8 policy/finalization -> checkpoint sequencing
```

The runtime reuses the D9A startup result's compiled `decision_plan`,
`feature_plans`, `data_plans`, `lane_requirements`, BarStore, runtimes, and
watermarks. It does not compile a second graph or add live infrastructure to
the startup evidence snapshot.

## D9B remediation

The bounded remediation addressed four review findings without changing D6,
D8, signal wire, checkpoint ordering, or transport contracts:

```text
per-stream transport precedence
    k-way merge preserves numeric stream-ID order within each stream while
    market cutoffs coordinate records across streams

reconciled context catch-up
    retained exact bars are checked against durable fetch_record_at provenance
    and accepted as DUPLICATE without scheduling a trigger

bounded input memory
    the lifetime _accepted_records ledger was removed; BarStore retention plus
    authoritative exact history lookup are the only duplicate/provenance state

transaction-local poll evidence
    LanePollResult is built from a fresh per-poll/per-attempt accumulator, so
    completed cutoffs are retained and later failures cannot inherit success
    fields from an earlier transaction
```

An empty bounded context-history read leaves the existing trigger pending in
`WAITING`, allowing a later canonical context-stream event to complete the
same cutoff. A newer trigger still halts that pending lane as
`RECONSTRUCTION_REQUIRED`; durable history never creates a live trigger.

The remediation tests cover same-stream market-time inversion, same-cutoff
context/trigger visibility, pending trigger then context catch-up, pending
overrun, DB-not-a-trigger, delayed exact reconciled-context duplicates,
long-run input boundedness, and stale-success poll evidence.

## Final valid-prefix failure-order remediation

The final D9B correction keeps entry-local parser failures as ordered deferred
failure markers. `DirectCursorInput.read_once()` preserves the valid prefix of
each stream and stops parsing that stream at the first malformed or
non-forward entry; it does not block the stream before the runtime can consume
the prefix. `LiveDecisionRuntime.poll_once()` surfaces the marker only after
that stream's valid prefix has been accepted and its current cutoff attempted.

The runtime then blocks only the affected stream and marks its dependent lanes
`RECONSTRUCTION_REQUIRED`. Later same-stream suffix entries are not exposed to
the next poll, while unrelated streams continue independently. Existing input
acceptance failures still take precedence over a later parser marker and
suppress the remainder of that stream.

The focused regressions prove:

```text
valid 3-0 -> committed signal/no-signal transaction
malformed 4-0 -> MALFORMED, stream blocked, lane reconstruction-required
cursor -> 3-0 (never 2-0 or 4-0)
5-0 suffix -> not accepted

valid prefix -> non-forward ID -> prefix preserved, failure surfaced
unrelated stream -> continues to its own forward cursor
```

The completed prefix transaction is not rolled back when the later failure is
surfaced in the same poll; its publication, finalization, state, watermark,
and checkpoint evidence remain transaction-local and truthful.

## Direct input and cursor evidence

`DirectCursorInput.read_once()` performs one bounded direct `XREAD` over the
captured startup positions. It never uses consumer groups, PEL operations, or
ack/reclaim APIs. A missing captured tail uses `0-0`; `$` is never used. Stream
IDs are normalized from bytes/text and compared numerically, and returned
records must be strictly greater than the mutable per-stream cursor.
Entry-local parse failures are deferred until the valid prefix has been
processed by the runtime; stream-level response-shape failures remain
fail-closed immediately.

The acceptance boundary proves:

```text
INSERTED
DUPLICATE
ALREADY_REPRESENTED       startup DB-ahead match; no re-evaluation
RECONSTRUCTION_REQUIRED   late bars, forward gaps, or unbridgeable history
CONFLICT                  canonical identity/provenance disagreement
MALFORMED                 invalid transport/event shape
```

Accepted or exactly represented records advance only the affected
`InputReadCursor`. A blocked stream does not roll back unrelated streams. Late
post-startup bars, forward gaps, overlapping bars, and conflicting identities
fail closed without cursor advancement.

## Cutoff scheduling and causal context

`LiveDecisionRuntime` sorts accepted records by market cutoff, then stream and
numeric stream ID. All records at one cutoff are applied before any lane at
that cutoff is attempted. This keeps a small shared BarStore from evicting a
trigger before its causal lane is evaluated.

Only authoritative lanes with `STARTUP_READY` evidence are scheduled. Each
lane has at most one unresolved trigger cutoff. A newer trigger cannot overtake
an unresolved older trigger; the lane is halted as reconstruction-required.

The runtime performs at most one bounded Timescale/history context resolution
attempt for missing non-trigger series. It never manufactures a live trigger
from history. A missing or invalid causal context leaves the lane waiting or
reconstruction-required while input progress and unrelated lanes continue.

## Publication and finalization

`ValkeySignalPublisher` preserves the D8 envelope and explicit market-time
stream entry ID. It performs exact-ID lookup before XADD, checks a newer stream
head before attempting a write, and never chooses an alternate ID. The result
matrix is:

```text
same ID + same semantic TradeSignal       ALREADY_IDENTICAL
same ID + different/undecodable payload  CONFLICT
newer stream head without required ID    CONFLICT
ambiguous write + exact ID now present   ALREADY_IDENTICAL or CONFLICT
unresolved transport failure             FAILED
```

The bounded transaction ordering is:

```text
D6 prepare_live
    -> D8 policy
    -> NO_SIGNAL finalization, or envelope/preflight/publisher/finalization
    -> committed state and LaneCommitWatermark
    -> latest-state checkpoint
```

`PUBLISHED`/`ALREADY_IDENTICAL` reaches D8 commit. `CONFLICT`/`FAILED` aborts
the prepared state and leaves the lane watermark unchanged. A policy or
pre-finalization failure also best-effort aborts an unresolved D6 proposal.
After successful finalization, checkpoint failure does not roll back the
signal, committed state, or watermark; it halts the lane and prevents the next
automatic trigger. Only `UPDATED`/`IDENTICAL` checkpoint results complete the
stateful transaction and clear its pending trigger.

## Runtime evidence

The focused synthetic/in-memory tests prove:

```text
real SR startup -> live candle -> NO_SIGNAL -> D8 commit -> UPDATED checkpoint
test decision-capable plugin -> exact signal ID -> PUBLISHED -> committed
two cutoff groups with capacity one -> both transitions evaluated in order
checkpoint failure after commit -> side effects retained; lane halted
policy failure after prepare -> proposal aborted; committed state unchanged
```

The real SR path uses the approved SR codec and core adapter; no legacy
`FeatureVector` or model-output boundary was introduced. The signal test uses
an isolated fake Valkey surface and does not publish to production
`signals:*` streams.

## Validation

Fresh D9B-focused validation:

```text
tests/decision/test_d9b_live_input.py
tests/decision/test_d9b_signal_transport.py
tests/decision/test_d9b_live_runtime.py
    28 passed

tests/decision
    283 passed
```

Previously selected compatibility evidence remains:

```text
D9A/D8/SR selected decision and SR suites       417 passed
signals/commons/risk selected suites            205 passed, 1 warning
canonical ingestion outbox/HTF slice             113 passed, 2 skipped
```

The full SR tree was also attempted earlier and is not a clean repository
gate because this checkout lacks approved frozen research assets:

```text
899 passed, 36 failed, 119 errors
```

The relevant non-research SR/core/config/lifecycle/serialization/replay and
adapter grouping passed. An earlier full `tests/ingestion` attempt produced:

```text
499 passed, 14 skipped, 1 failed, 2 warnings
```

The single failure was the unrelated Compose-dependent FINAL harness reaching
the missing worktree `.env` during its preflight. It did not identify a D9B
production failure.

Static and boundary checks passed:

```text
scoped Ruff check                         passed
scoped Ruff format --check                58 files already formatted
compileall (decision scope)               passed
git diff --check                          passed
decision_app production import boundary  clean
D9B forbidden-pattern scan                clean
repo-local cache cleanup                  completed
```

The worktree has no local `.env`, so `docker compose config` and real local
Timescale/Valkey certification remain environment-gated. No credentials were
copied and no external runtime state was mutated.

## Two-pass self-review

Pass 1 — causal and transaction correctness:

```text
captured-tail attachment and 0-0 fallback             checked
DB-ahead representation without replay                 checked
numeric/strict cursor progress                         checked
late/gap/conflict fail-closed behavior                 checked
cutoff grouping before lane evaluation                 checked
per-stream transport order despite market-time inversion checked
same-cutoff cross-stream context before evaluation       checked
retained DB-context duplicate catch-up                   checked
empty context read remains WAITING                        checked
bounded input duplicate/provenance memory                 checked
transaction-local result fields                           checked
valid stream prefix before malformed suffix              checked
valid stream prefix before non-forward suffix            checked
suffix suppression after first stream failure            checked
unrelated stream independence                             checked
same-poll committed prefix not rolled back                checked
independent input/lane progress                        checked
one pending trigger and no stale continuation          checked
bounded non-trigger context reconciliation              checked
exact-ID publication and ambiguity reconciliation       checked
publication/no-signal before state/watermark            checked
post-finalization checkpoint ordering                   checked
checkpoint failure halts without rollback              checked
real SR no-signal path                                  checked
replay/publication boundary                             checked
```

Pass 2 — scope and simplicity:

```text
one bounded poll primitive; no infinite loop             checked
direct XREAD only; no PEL/group machinery                checked
no PriceRelay or price-update path                        checked
no service supervisor/FastAPI/Docker                      checked
no legacy signal/strategy changes                         checked
no D7B model refactor                                     checked
no generic retry/workflow/actor framework                  checked
no production signal-stream publication in tests          checked
```

## Residual risks and handoff

D9B is ready for independent review as a bounded primitive, not as a complete
service. D9C still owns lifecycle supervision, reconnect behavior, asset
lifecycle subscription, service wiring, operational resource handling,
PriceRelay integration/recovery, and any controlled cutover. Real local
Timescale/Valkey execution remains pending a worktree environment with the
required `.env`. D7B remains deferred.

No D9C work was started. No commit, merge, push, or external-state migration
was performed.

DECISION_APP_D9B_LIVE_SIGNAL_RUNTIME_READY_FOR_REVIEW
