---
goal: Implement the first live decision_app signal path on top of approved D9A startup state: direct-cursor canonical input reads, deterministic event acceptance/classification, serial lane evaluation, real Valkey signal publication, D8 finalization, and post-commit checkpoint durability without starting the full service/runtime supervisor
stage: architect-to-coder
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d9b, runtime, valkey, publication, checkpoint]
---

# Architect-to-coder — `decision_app` D9B live signal runtime

## 1. Starting point

Use the existing cumulative isolated worktree only:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

D0-D8, D7A, and D9A are APPROVED.

D7B remains deferred to the parallel model-refactor stream and must not be independently implemented in this worktree.

D9A now provides the trustworthy startup boundary:

```text
static decision config
+ canonical ingestion config/manifests
+ captured stream tails
+ durable DB warm cutoffs
+ bounded final BarStore
+ exact ModelRuntime state
+ baseline LaneCommitWatermarks
+ exact latest state checkpoints
        ↓
STARTUP_READY / per-lane startup evidence
```

D9B is the first phase allowed to perform **live post-startup input reads and actual signal-stream publication**.

Do not reopen approved D0-D9A semantics unless a directly demonstrated defect requires a narrow fix.

Do not commit, merge, push, switch branches, reset, restore, or modify the primary checkout.

---

# 2. D9B objective

Implement one bounded, testable live poll path:

```text
D9A startup result
        ↓
DirectCursorInputReader.read_once()
        ↓
canonical event parse + accept/classify
        ↓
BarStore + InputReadCursor
        ↓
trigger cutoff scheduling
        ↓
causal lane context reconciliation
        ↓
LaneMarketView
        ↓
D6 ModelRuntime.prepare_live()
        ↓
D8 DecisionPolicy
        ↓
NO_SIGNAL ───────────────┐
                        │
SIGNAL -> D8 envelope -> ValkeySignalPublisher -> D8 ACK
                        │
                        v
                  LaneFinalizer
                        ↓
             D6 state commit + watermark
                        ↓
          exact latest state checkpoint update
                        ↓
                lane transaction complete
```

D9B must prove this path one bounded poll/batch at a time.

D9B is **not** the full application lifecycle.

---

# 3. Hard non-goals

Do NOT implement in D9B:

```text
FastAPI app/lifespan
main.py / CLI service startup
Docker/Compose decision service
runtime supervisor/controller framework
asset:lifecycle continuous subscriber
worker-per-asset / actor framework
consumer groups
XREADGROUP
XACK
XAUTOCLAIM
PEL replay/reclaim
persistent input cursor table
signal outbox
PriceRelay
price_update:* publication
PriceRelay gap/catch-up policy
risk_app changes
execution_app changes
legacy signal_app/strategy_app changes
external HTTP/scraper adapters
live model training
D7B Momentum refactor/integration
shadow-parity harness
resource/load certification
cutover
legacy retirement
```

No generic event bus, actor system, workflow/DAG runtime, repository framework, or retry framework.

Do not create an internal feature stream.

Do not reintroduce `FeatureVector`, legacy `ModelOutput`, old model managers, or old signal/strategy runtime classes into the new path.

---

# 4. D9B execution mode

Implement **bounded one-poll primitives** first.

The preferred top-level runtime operation is conceptually:

```text
DecisionLiveProcessor.poll_once()
```

It may issue one bounded direct `XREAD`, process the returned batch, attempt eligible lane transactions, and return bounded typed evidence.

Do not add an infinite `while True` service loop in D9B. D9C will own lifecycle, cancellation/reconnect loops, FastAPI, and process supervision.

A small `read_once()` / `poll_once()` boundary gives D9B real transport behavior without prematurely building the service shell.

---

# 5. Minimal production structure

Prefer a small layout such as:

```text
src/apps/decision_app/
  live_input.py
  live_runtime.py
  signal_transport.py
```

Exact names may differ if a smaller structure is clearer.

Continue using existing modules for:

```text
ingestion_input.py       canonical stream parser/provenance
market_state.py          BarStore + grid
readiness.py             D3 lane requirements/readiness
features.py              D4 FeaturePlan/history requirements
model_runtime.py         D6 prepare/state semantics
policy.py                D8 policy
publication.py           D8 envelope/ACK identity
finalization.py          D8 state/watermark finalization
storage/checkpoints.py   D9A exact checkpoint durability
storage/market_history.py canonical read-only Timescale history
startup.py               D9A startup only
settings.py              strict decision config
```

Do not turn `startup.py` into the live worker.

---

# 6. Small D9A result extension allowed

D9B needs the already-compiled static runtime material used by D9A. Do not independently recompile a second graph inside the live processor.

It is acceptable to extend `DecisionStartupResult` with immutable/static maps such as:

```text
feature_plans: Mapping[lane_id, FeaturePlan]
lane_requirements: Mapping[lane_id, LaneMarketRequirements]
```

Optionally expose the already-resolved decision plan if it materially reduces lookup duplication.

Do not put Valkey clients, DB pools, background tasks, publishers, or other live infrastructure inside `DecisionStartupSnapshot`.

The immutable D9A evidence snapshot remains evidence only.

If a D3+D4 merged history requirement helper is needed in both startup and live runtime, extract one **small pure helper** instead of copying the logic.

A suitable ownership is `readiness.py` or another existing decision semantic module, e.g. conceptually:

```text
compile_lane_causal_history_requirements(
    lane,
    feature_plan,
    timeframe_grid,
) -> Mapping[MarketSeriesKey, int]
```

It must merge:

```text
D3 LaneMarketRequirements.minimum_bars_by_series
+
D4 FeaturePlan.history_requirements
```

by maximum count per series.

Do not create a second required-timeframe catalog.

---

# 7. D9B decision runtime settings

D9B is the first phase that genuinely needs live input/publication settings.

Extend strict decision global configuration with only these bounded settings:

```text
live input:
  batch_size
  block_ms

signal publication:
  stream_maxlen
  stream_approximate
```

Use the existing legacy-compatible operational values unless repository evidence requires otherwise:

```text
batch_size = 10
block_ms = 1000
signal stream maxlen = 1000
signal stream approximate = true
```

These values already exist in the current runtime contracts and are not new quantitative parameters.

Prefer explicit YAML ownership in:

```text
configs/decision/global.yaml
```

Do not add retry/backoff, concurrency, worker-count, queue-depth, context-wait, or PriceRelay settings in D9B.

Do not add production asset/lane config by inventing model parameters.

---

# 8. Direct cursor input — no consumer group

Use D9A `InputReadCursor` / captured stream IDs as the attachment point.

For each required canonical ingestion stream:

```text
stream:ohlcv:ingestion:{venue}:{instrument_id}:{timeframe}
```

D9B reads with direct `XREAD` only.

Conceptually:

```text
XREAD COUNT <batch_size> BLOCK <block_ms>
STREAMS
  stream_a cursor_a
  stream_b cursor_b
  ...
```

Rules:

```text
captured_tail_id exists -> read strictly after that ID
captured_tail_id is None -> use 0-0, never "$" after warmup
```

Using `0-0` for a stream that did not exist at tail capture prevents a stream created during D9A warmup from being skipped.

Do not recapture startup tails in D9B.

Do not use consumer groups or a PEL.

---

# 9. Stream ID contract

Add one tiny deterministic stream-ID normalization/comparison helper if needed.

Accept transport `str`/`bytes` at the boundary and normalize to canonical text.

Validate stream IDs as Redis/Valkey stream IDs:

```text
<non-negative integer ms>-<non-negative integer sequence>
```

Compare numerically, not lexicographically.

A returned record must be strictly after the mutable cursor ID used for that stream.

Malformed/non-forward stream IDs fail that stream closed.

Do not infer market time from ingestion stream IDs. Ingestion stream IDs are transport ordering only.

Market identity remains payload `close_time` / `market_as_of`.

---

# 10. Batch processing order

Do not append an entire large batch and evaluate only afterward; a steady-state BarStore may intentionally have capacity 1 and could evict an earlier trigger before it is evaluated.

Use cutoff-group processing:

1. parse each stream in its returned stream-ID order;
2. after the first invalid/blocking record for one stream, ignore later records from that same stream in that poll;
3. collect valid records from all unblocked streams;
4. process records by increasing `market_as_of`;
5. for one equal-`market_as_of` group, accept/apply all canonical series first;
6. only then attempt lane triggers at that cutoff;
7. move to the next market cutoff.

Use deterministic tie-breaking, e.g. canonical stream key then numeric stream ID.

This allows same-cutoff context and trigger bars returned in one `XREAD` to become visible before lane evaluation while still evaluating each trigger before a later cutoff can evict it.

---

# 11. Canonical live event acceptance/classification

Reuse `parse_canonical_ingestion_event()`.

Do not import ingestion production classes.

The live input layer must classify each parsed event into a small explicit result, conceptually:

```text
INSERTED
DUPLICATE
ALREADY_REPRESENTED
RECONSTRUCTION_REQUIRED
CONFLICT
```

Malformed transport is a stream failure and need not be represented as a successful disposition.

## 11.1 INSERTED

For a new forward bar:

```text
bar.open == current latest bar.close
```

and all canonical geometry is valid:

```text
BarStore.append() -> INSERTED
```

Then advance that stream's mutable `InputReadCursor`.

## 11.2 DUPLICATE

A duplicate/outbox retry of a retained bar may be accepted only when canonical content matches exactly.

Do not re-evaluate a lane for a duplicate.

Advance only the transport stream ID; market cursor cutoff must never move backward.

## 11.3 ALREADY_REPRESENTED — D9A DB-ahead window

D9A deliberately permits:

```text
captured stream tail T
DB warm cutoff R > T
```

Therefore D9B may receive post-tail stream messages for bars already represented by D9A startup history/state.

Use the immutable D9A `SeriesStartupPosition.warm_cutoff` as the startup baseline boundary.

An old event may be classified `ALREADY_REPRESENTED` only when:

```text
event.market_as_of <= D9A startup warm_cutoff for that series
AND
exact canonical DB record matches the stream event
```

Do not trigger model evaluation.

Advance the transport stream ID while keeping `latest_market_as_of = max(previous, event.market_as_of)`.

## 11.4 Late post-startup historical event

If:

```text
event.market_as_of > startup warm_cutoff
but event is older than the current live series head
```

it is a post-startup late/backfill event, not automatically "already represented".

It may have changed causal history after the lane advanced.

Return:

```text
RECONSTRUCTION_REQUIRED
```

Do not insert it behind newer retained bars.

Do not advance the cursor past it.

## 11.5 Forward market gap

For a new forward bar, require exact continuity:

```text
new.bar_open_at == current_latest.bar_close_at
```

If later:

```text
new.bar_open_at > current_latest.bar_close_at
```

classify:

```text
RECONSTRUCTION_REQUIRED
```

Do not let `BarStore.append()` silently accept a gap merely because bars do not overlap.

## 11.6 CONFLICT

Same canonical identity with different OHLCV/provenance is a hard conflict.

Do not advance the cursor.

Block the affected stream/series and mark every lane requiring that series reconstruction-required/invalid.

Unrelated streams and lanes continue.

---

# 12. Exact canonical record lookup for old/duplicate events

D9B needs exact comparison against durable canonical history for old/duplicate stream records.

Extend the decision-owned read-only history boundary minimally.

A small immutable record is acceptable, e.g.:

```text
CanonicalMarketRecord
  series_key
  bar: CausalBarView
  source_type
  source_provider
  source_timeframe
```

Add an exact lookup such as:

```text
fetch_record_at(key, bar_open_at) -> CanonicalMarketRecord | None
```

Use the same canonical provenance validator as stream parsing.

Existing `fetch_bars()` can remain `CausalBarView`-only for D3/D4 consumers.

Do not expose ingestion domain objects.

Do not compare `occurred_at` as market identity.

---

# 13. Mutable input cursor semantics

`InputReadCursor` remains immutable data; the live reader may replace the current value per stream after accepted records.

Advance cursor only after:

```text
INSERTED
DUPLICATE
ALREADY_REPRESENTED
```

Do not advance past:

```text
malformed event
CONFLICT
RECONSTRUCTION_REQUIRED
```

Cursor update:

```text
latest_stream_id = accepted transport ID
latest_market_as_of = max(previous.latest_market_as_of, event.market_as_of)
```

A lane failure/publication failure never rolls the input cursor back.

The cursor is process-local in D9B. Do not persist it to Timescale/Valkey.

Restart still uses D9A reconstruction + newly captured tails.

---

# 14. Series failure isolation

Maintain small in-memory per-stream/series status evidence.

A canonical conflict/gap/malformed record blocks that stream for the current runtime instance.

Do not continue reading later records for a blocked stream in the same `poll_once()`.

D9C will own reconnect/reconstruction supervision.

When one series blocks, identify only the lanes whose compiled D3/D4 requirements include that `MarketSeriesKey` and mark those lanes reconstruction-required.

Do not stop unrelated lanes or unrelated stream cursors.

Input reading for unaffected series remains independent of model state.

---

# 15. Lane live owner

Use one small in-process owner per D9A-ready lane, conceptually:

```text
LiveLane
  lane
  runtime: ModelRuntime
  feature_plan
  market_requirements
  finalizer: LaneFinalizer
  state_inception_at
  pending_trigger_cutoff?
  live status/reason
```

Do not spawn one task/process per lane.

The application remains one process and one serial live processor in D9B.

Use existing `LaneState` vocabulary where practical.

Do not invent a state-machine framework.

---

# 16. D9B schedules authoritative lanes only

D9B's broker publication path activates only lanes with:

```text
authority == authoritative
```

Shadow lane live-finalization semantics are not defined by D8 and must not be faked as `no_signal` merely to advance state.

Therefore D9B should not live-schedule shadow lanes for state progression/publication.

Carry shadow execution to the later shadow-parity programme, where publication can be suppressed under an explicit harness contract.

A real analytical SR binding can still be used inside an authoritative **test-only** lane to prove the live no-signal state/checkpoint path.

Do not add a production SR asset configuration.

---

# 17. Trigger scheduling — one pending cutoff per lane

D9B must not build an unbounded trigger queue.

Use at most one unresolved trigger cutoff per lane:

```text
pending_trigger_cutoff: datetime | None
```

When a newly `INSERTED` canonical event is on the lane's trigger series and its cutoff is later than the lane watermark:

```text
no pending -> set pending cutoff
same pending cutoff -> idempotent/no-op
older pending exists and a newer trigger arrives -> lane reconstruction required
```

A second trigger must never overtake an unresolved earlier trigger for a stateful lane.

For simplicity and safety, D9B may halt any authoritative lane on pending-trigger overrun rather than introducing different queue semantics for stateful/stateless lanes.

Input reading continues.

---

# 18. Pending trigger retry

After every equal-market-cutoff event group, and once at the end of `poll_once()`, attempt pending lanes in deterministic `lane_id` order.

A pending cutoff may become ready because:

```text
same-cutoff context stream event arrived
or
canonical context is already durable in Timescale but its outbox stream is delayed
```

Do not republish/re-evaluate cutoffs at or below the lane watermark.

Do not process a later pending cutoff before the earlier one is resolved.

---

# 19. Bounded live context reconciliation

Before calling `ModelRuntime.prepare_live()`, ensure the pending cutoff has complete canonical D3+D4 history.

Use the already-compiled merged lane history requirements.

For each required **non-trigger** series:

```text
expected_cutoff = TimeframeGrid.expected_closed_cutoff(series_tf, pending_trigger)
required_count = compiled D3/D4 max lookback
```

Inspect the final BarStore.

If complete/contiguous through expected cutoff: no DB read.

If the missing bars can be appended **forward** from the current retained head, perform one bounded canonical Timescale read and append them in causal order.

This is the approved D0 bounded historical-resolution attempt.

Rules:

```text
DB context fetch is canonical read-only
no external provider/network
no local HTF reaggregation
no insertion behind newer bars
no silent repair of an internal historical gap
```

If repairing the required history would require inserting an older bar behind an already newer retained bar:

```text
RECONSTRUCTION_REQUIRED
```

D9C/full reconstruction owns that case.

Do not fetch a missing **current trigger** from Timescale to manufacture a live trigger. A live decision trigger must originate from an accepted post-startup canonical stream event.

Earlier trigger-history bars required by D3/D4 must already be represented/continuous; otherwise reconstruction is required.

---

# 20. View readiness before D6 execution

Only call `ModelRuntime.prepare_live()` after:

```text
merged D3/D4 required histories are complete and contiguous
DecisionViewBuilder.build(...) succeeds
pending cutoff > LaneCommitWatermark.latest_market_as_of
```

Use the mutable trigger-stream `InputReadCursor` as the view/readiness evidence.

The cursor is evidence only; D3 readiness derives actual causal completeness from BarStore histories.

Do not call D6 merely to discover ordinary expected arrival-order incompleteness, because missing required features can degrade a stateful binding.

If view/context is still not ready after one bounded DB reconciliation attempt:

```text
keep the one pending cutoff
return WAITING/WARMING evidence
```

Do not degrade state yet merely because same-cutoff context has not arrived.

If a newer trigger arrives while it is still pending, fail the lane closed as reconstruction-required.

---

# 21. Decision-time operational clock

Inject a small `now_fn` seam for deterministic tests.

For live model/data resolution:

```text
resolver_knowledge_cutoff = UTC now at evaluation start
```

For D8 policy:

```text
decision_ready_at = UTC now after model preparation
```

Both must be >= `market_as_of`.

Never use `decision_ready_at` or wall time in decision identity.

Do not infer or round timestamp units.

---

# 22. Live lane transaction

For one ready pending cutoff:

```text
view = DecisionViewBuilder.build(...)
prepared = await ModelRuntime.prepare_live(
    view,
    resolver_knowledge_cutoff=...
)
evaluation = DecisionPolicy.evaluate(
    lane,
    prepared,
    decision_ready_at=...
)
```

Then handle exactly:

```text
NO_SIGNAL
SIGNAL
BLOCKED
INVALID
```

No other composition semantics belong in D9B.

---

# 23. NO_SIGNAL path

For `NO_SIGNAL`:

```text
LaneFinalizer.finalize_no_signal(prepared, evaluation)
```

This authorizes:

```text
D6 proposed state commit
then lane watermark advance
```

No signal stream entry is written.

After finalization, persist state checkpoint if the lane contains stateful bindings.

Only after successful checkpoint durability may D9B report the stateful live transaction fully durable and clear the pending cutoff.

Use real SR in a test-only authoritative lane to prove:

```text
accepted live candle
-> SR prepare
-> analytical NO_SIGNAL
-> D8 finalize_no_signal
-> encoded SR committed state
-> watermark advance
-> checkpoint update
```

---

# 24. SIGNAL path

For `SIGNAL`:

1. build the canonical D8 `SignalPublicationEnvelope`;
2. preflight with `LaneFinalizer.preflight_signal()`;
3. call the D9B Valkey publisher;
4. receive a typed D8 `SignalPublicationAck`;
5. call `LaneFinalizer.finalize_signal(...)` with the same causal `LaneMarketView`;
6. if finalization is committed, persist a state checkpoint when stateful;
7. clear the pending cutoff only after required checkpoint durability succeeds.

Do not bypass D8 envelope revalidation.

Do not let the publisher call `ModelRuntime.commit_prepared()` directly.

Only `LaneFinalizer` authorizes state/watermark finalization.

---

# 25. Actual Valkey signal publisher

Add one small transport adapter such as:

```text
ValkeySignalPublisher.publish(envelope) -> SignalPublicationAck
```

It owns only the existing `signals:{asset}:{timeframe}` transport.

Use:

```text
libs.contracts.serialization.valkey_encode
libs.contracts.serialization.valkey_decode
TradeSignal
```

Do not invent another signal wire schema.

D8 `payload_fingerprint` remains the **semantic TradeSignal fingerprint**; W3C trace transport fields are not part of decision identity.

---

# 26. Signal publication idempotency algorithm

Use D8's exact deterministic stream ID:

```text
market_as_of epoch milliseconds + "-0"
```

Do not use auto IDs for authoritative decision signals.

## 26.1 Preflight exact lookup

Before XADD:

```text
XRANGE stream_key stream_entry_id stream_entry_id
```

If exact entry exists:

- decode as `TradeSignal`;
- recompute D8 semantic payload fingerprint;
- validate idempotency key/decision metadata through the normal D8 envelope shape;

then return:

```text
same semantic signal -> ALREADY_IDENTICAL
different/undecodable signal -> CONFLICT
```

Do not XADD when an exact entry already exists.

## 26.2 XADD

If exact ID is absent:

```text
XADD
  stream_key
  id=stream_entry_id
  maxlen=configured signal maxlen
  approximate=configured compatibility value
  fields=valkey_encode(envelope.signal)
```

Require returned ID to normalize exactly to `stream_entry_id`.

Success:

```text
PUBLISHED
```

## 26.3 Ambiguous/duplicate XADD exception

On any non-cancellation XADD exception, do not guess whether the write happened.

Perform exact-ID lookup again.

```text
entry now exists + identical -> ALREADY_IDENTICAL
entry now exists + different -> CONFLICT
```

If exact entry is absent, inspect the current stream head with one bounded `XREVRANGE count=1` if needed.

If the stream head ID is already **greater than** the required explicit ID while the exact ID is absent:

```text
CONFLICT
reason = deterministic publication ID was skipped/stream already advanced
```

Otherwise:

```text
FAILED
reason = publication outcome unresolved/transport failure
```

Do not parse arbitrary exception strings to decide duplicate semantics.

`asyncio.CancelledError` propagates.

---

# 27. Legacy signal-stream safety

D8 explicit IDs are market-time IDs.

Legacy `strategy_app` currently publishes to the same `signals:*` namespace with auto-generated stream IDs.

Therefore D9B must **not** be pointed at a shared production signal stream while the legacy authoritative writer is still active.

A newer legacy stream head with no exact D8 ID must classify as `CONFLICT`, not cause D9B to choose a different ID.

Real D9B publication tests must use isolated broker state / test streams in the repository harness.

Do not stop or modify legacy strategy_app in D9B.

D12 owns controlled publisher cutover.

---

# 28. Publication ACK matrix

Publisher returns only D8 outcomes:

```text
PUBLISHED
ALREADY_IDENTICAL
CONFLICT
FAILED
```

Then existing D8 semantics remain authoritative:

```text
PUBLISHED
ALREADY_IDENTICAL
    -> D8 finalizer commits state
    -> watermark advances

CONFLICT
FAILED
    -> D8 finalizer aborts prepared state
    -> watermark unchanged
```

For `CONFLICT`/`FAILED`, mark the authoritative lane halted/reconstruction-required for D9B. Do not automatically move to later triggers.

Input reading continues independently.

Do not add retry/backoff in D9B.

---

# 29. Policy failure matrix

If policy returns:

```text
BLOCKED
INVALID
```

use:

```text
LaneFinalizer.abort_policy_failure(...)
```

No signal publication.
No checkpoint write.
No watermark advance.

For a stateful lane the D6 health semantics already force rewarm when appropriate.

D9B should halt that lane for this runtime instance and report reconstruction-required/invalid evidence rather than trying later triggers from stale state.

Unrelated lanes continue.

---

# 30. Model preparation failure

If `ModelRuntime.prepare_live()` raises after the view was judged ready:

```text
no publication
no finalization
no checkpoint
no watermark advance
```

D6 already owns stateful health mutation for feature/data/runtime exceptions.

Mark the lane halted/reconstruction-required or invalid according to the D6 state evidence.

Do not catch `CancelledError` as an ordinary model failure.

---

# 31. Checkpoint after finalization

D9A checkpoint durability is restart continuity, not publication authorization.

For stateful lanes, persist the latest exact state **after** D8 has committed state/watermark.

Ordering is frozen:

```text
signal publication ACK / final no-signal
        ↓
D8 finalizer
        ↓
D6 committed state
        ↓
LaneCommitWatermark advanced
        ↓
D9A checkpoint persistence
```

Never write the proposed state to the checkpoint before D8 commit.

Never use checkpoint success to authorize signal publication.

---

# 32. Live checkpoint construction

Preserve the D9A `state_inception_at` for the lane across live checkpoint updates.

After a committed finalization:

```text
market_as_of = finalization receipt cutoff
state_by_binding = exact committed state for every stateful binding
state_inception_at = D9A lane inception evidence
identity = exact runtime LaneExecutionIdentity
```

Use the existing deterministic checkpoint codec/repository.

No model decisions/signals are stored in the checkpoint.

No new checkpoint schema.

---

# 33. Checkpoint save outcomes after live commit

Normal stateful D9B continuation expects an existing D9A checkpoint.

Accept as durable success:

```text
UPDATED
IDENTICAL  # safe idempotent retry of the same committed checkpoint
```

Treat as an invariant/durability failure for continued live processing:

```text
CONFLICT
REJECTED_OLDER
unsupported result
repository exception
```

`INSERTED` after a D9A-ready stateful lane means the startup checkpoint disappeared between startup and live processing. It may have restored current state, but it is evidence of unexpected durable-state loss.

For D9B V1:

```text
INSERTED -> halt the lane after recording the anomaly
```

Do not process another trigger automatically.

Do not attempt to roll back the already committed state or already published signal.

A checkpoint failure **after** finalization is an irreversible post-commit durability fault:

```text
watermark may already be advanced
signal may already be published
state is committed in memory
```

Report that fact explicitly and halt the lane.

D9C/restart reconstruction owns recovery.

---

# 34. Crash/restart semantics stay D0/D9A

D9B adds no persistent PEL and no signal outbox.

If the process crashes:

```text
after input cursor advance but before lane finalization
or
after signal XADD but before state commit
or
after state commit but before checkpoint update
```

restart uses D9A:

```text
capture new stream tails
read canonical Timescale history
load the last exact durable checkpoint
causally replay publication-suppressed through startup cutoff
resume after captured tails
```

Historical decisions are not republished.

A missed trade during crash recovery remains acceptable V1 behavior already frozen by D0.

Do not add a stale-decision replay queue to "fix" this.

---

# 35. Lane watermark and input cursor remain independent

Prove explicitly:

```text
accepted input event
-> InputReadCursor advances

lane publication/model/checkpoint failure
-> InputReadCursor does NOT roll back
-> affected LaneCommitWatermark may remain behind
-> unrelated lanes continue
```

This is a core architecture invariant.

---

# 36. Bounded evidence contracts

Return bounded data-only evidence from `read_once()` / `poll_once()`.

Conceptually useful shapes:

```text
InputRecordResult
  stream_key
  stream_id
  series
  market_as_of
  disposition
  reason?

LanePollResult
  lane_id
  trigger_cutoff?
  status
  policy_status?
  publication_outcome?
  finalization_status?
  checkpoint_result?
  reason?

DecisionPollResult
  input results
  lane results
  current cursors
```

Do not include full model state, unbounded artifacts, full historical bars, DB clients, or Valkey clients in evidence.

Avoid a generic event-envelope framework.

---

# 37. Real SR live no-signal proof

Use the approved D7A SR adapter in deterministic test-only configuration.

Start through D9A, then process one or more new canonical 1h stream candles through D9B.

Prove:

```text
D9A checkpoint cutoff = C
new trigger = C + 1h
SR state initially LIVE

D9B:
  event INSERTED
  prepare_live succeeds
  policy -> NO_SIGNAL
  no signal XADD
  finalizer -> COMMITTED/no_signal
  watermark = C + 1h
  checkpoint -> UPDATED
  decoded SR checkpoint == runtime committed SR state
```

Also prove two sequential live SR no-signal transitions can progress one trigger at a time without rewarm.

Do not alter SR mathematics.

---

# 38. Synthetic decision-capable publication proof

D7B is not available yet, so do not refactor Momentum in this worktree.

Use a small test-only decision-capable plugin to prove the real D9B signal transport.

At minimum prove:

```text
SIGNAL -> PUBLISHED -> finalizer COMMITTED -> watermark
pre-existing identical ID -> ALREADY_IDENTICAL -> COMMITTED
pre-existing different payload -> CONFLICT -> ABORTED/no watermark advance
XADD inserts then raises -> post-lookup ALREADY_IDENTICAL -> COMMITTED
XADD fails and exact ID absent -> FAILED -> ABORTED
newer stream head + exact ID absent -> CONFLICT
```

For state-transaction proofs, a small test-only stateful decision plugin is acceptable.

Do not add a production synthetic plugin/catalog entry.

---

# 39. Input-path adversarial tests

Cover at minimum:

```text
D9A captured tail attaches via direct XREAD
None tail attaches from 0-0, not $
bytes/str stream transport normalization
stream IDs compared numerically
non-forward returned stream ID rejected
DB-ahead post-tail event classified ALREADY_REPRESENTED
ALREADY_REPRESENTED does not re-evaluate lane
retained exact duplicate accepted idempotently
old post-startup event -> RECONSTRUCTION_REQUIRED
forward market gap -> RECONSTRUCTION_REQUIRED
same identity different bar/provenance -> CONFLICT
malformed event blocks only its stream
cursor advances only for accepted/represented events
cursor market cutoff never moves backward
unrelated stream continues after one stream failure
```

Use exact canonical ingestion fixtures in tests where practical.

---

# 40. Batch/capacity tests

Prove cutoff-group processing prevents eviction bugs.

Example:

```text
trigger series final BarStore capacity = 1
XREAD returns trigger bars at T1 and T2 in one batch
```

D9B must:

```text
append T1
process/finalize T1
then append/process T2
```

Both transitions must be observed exactly once.

Do not enlarge the steady-state BarStore simply to accommodate one input batch.

Also prove same-cutoff context + trigger records in one batch are applied before that cutoff's lane evaluation.

---

# 41. Pending/context tests

Cover:

```text
trigger arrives, required context absent -> one pending cutoff, no D6 call
later context stream event arrives -> pending cutoff becomes ready -> evaluate once
DB has delayed context while context stream lags -> bounded DB reconciliation appends forward context -> evaluate
pending T remains unresolved, trigger T+1 arrives -> lane reconstruction-required
no unbounded trigger queue
internal retained historical gap cannot be patched behind newer bar
trigger is never manufactured from DB without stream event
```

For a stateful lane, unresolved-trigger overrun must not allow continuation from stale committed state.

---

# 42. D8/D9B transaction tests

Cover:

```text
NO_SIGNAL -> state commit -> watermark -> checkpoint
PUBLISHED -> state commit -> watermark -> checkpoint
ALREADY_IDENTICAL -> state commit -> watermark -> checkpoint
CONFLICT -> state abort -> watermark unchanged -> no checkpoint
FAILED -> state abort -> watermark unchanged -> no checkpoint
policy BLOCKED -> abort/no publication/no watermark/no checkpoint
policy INVALID -> abort/no publication/no watermark/no checkpoint
prepare exception -> no publication/no watermark/no checkpoint
```

Prove exact ordering with recording fakes/spies where helpful.

Do not weaken D8 finalizer tests.

---

# 43. Post-commit checkpoint-failure tests

Explicitly cover the irreversible ordering case:

```text
publication PUBLISHED
D8 state commit succeeds
watermark advances
checkpoint save raises/fails
```

Required result:

```text
signal remains published
state remains committed
watermark remains advanced
lane is halted with checkpoint durability failure
next trigger is not evaluated
input cursor continues independently
```

Also cover:

```text
checkpoint CONFLICT
checkpoint REJECTED_OLDER
checkpoint INSERTED unexpectedly after D9A
```

All halt the lane after the committed transaction; none attempt rollback.

---

# 44. Downstream compatibility proof

Decode an actually encoded D9B `TradeSignal` using the current shared Valkey decoder and prove the unchanged risk-facing contract:

```text
stream key = signals:{asset}:{decision_tf}
timestamp = epoch seconds
model_name = risk_profile_key
price = causal decision-bar close
bar_high/bar_low metadata preserved
ATR only when selected binding has valid ATR
idempotency_key = D8 deterministic signal key
```

Run current risk compatibility tests relevant to:

```text
risk profile resolution
signal staleness seconds semantics
ATR sizing / stop-loss metadata
```

Do not change risk behavior.

---

# 45. Production/import boundaries

New D9B production decision code may import shared contracts/common infrastructure, but must not import production runtime code from:

```text
apps.ingestion_app
apps.signal_app
apps.strategy_app
apps.risk_app
apps.execution_app
```

Test code may use ingestion contract builders for parity fixtures.

Run an AST/import boundary scan.

Also scan D9B production code for forbidden transport/runtime patterns:

```text
xreadgroup
xack
xautoclaim
consumer group creation
PEL reclaim
price_update publication
FastAPI
Docker/service bootstrap
```

Direct `xread`, exact `xrange`/`xrevrange`, and signal `xadd` are expected in D9B.

---

# 46. Local infrastructure certification

D9B contains actual broker I/O, so use real local Valkey/Timescale integration **only if the repository harness is genuinely available**.

The current cumulative worktree previously lacked `.env` and Compose could not resolve safely.

Do not copy/create `.env`, start unrelated shared services, or mutate external state merely to force the gate.

If the environment remains unavailable:

```text
record LOCAL_INFRASTRUCTURE_VALIDATION_BLOCKED_ENVIRONMENT
```

and keep deterministic fake/in-memory transport tests as the D9B functional gate.

If a repository-provided isolated harness becomes available, prove at minimum:

```text
direct XREAD from captured ID
DB-ahead event classification
explicit-ID signal XADD
exact identical retry -> ALREADY_IDENTICAL
different payload same ID -> CONFLICT
risk-compatible TradeSignal decode
checkpoint update after committed state
```

Use isolated test DB/stream state only.

No Binance/external provider calls.

---

# 47. D9B config safety

No production asset file is required for D9B.

If `configs/decision/global.yaml` is extended, it should contain only the D9B runtime transport settings justified above.

Do not add:

```text
fake BTC SR lane
fake Momentum lane
shadow production lane
risk parameters
model alpha parameters
PriceRelay config
lifecycle config
retry framework config
```

---

# 48. Suggested implementation order

## D9B.1 — static/runtime handoff

```text
expose D9A compiled feature/lane requirements as needed
extract one shared merged D3+D4 requirement helper if necessary
add strict D9B input/publication settings
```

Validate before continuing.

## D9B.2 — direct input reader + classifier

```text
XREAD direct cursor
stream-ID normalization
canonical parser
exact DB record lookup
INSERTED/DUPLICATE/ALREADY/RECONSTRUCTION/CONFLICT
cursor semantics
stream failure isolation
```

Validate adversarial input tests.

## D9B.3 — pending trigger + context reconciliation

```text
cutoff-group processing
one pending cutoff per lane
bounded Timescale context reconciliation
view readiness
no DB-manufactured trigger
```

Validate mixed-timeframe/arrival-order cases.

## D9B.4 — actual signal publisher

```text
exact lookup
explicit-ID XADD
ambiguous error reconciliation
D8 ACK outcomes
```

Validate publisher matrix independently.

## D9B.5 — serial lane transaction

```text
D6 prepare
D8 policy
D8 finalizer
checkpoint persistence
lane halt semantics
```

Prove real SR NO_SIGNAL and synthetic SIGNAL paths.

Stop after the complete D9B validation/review handoff.

Do not start D9C.

---

# 49. Focused test inventory

Prefer focused files such as:

```text
tests/decision/test_d9b_live_input.py
tests/decision/test_d9b_signal_transport.py
tests/decision/test_d9b_live_runtime.py
tests/decision/test_d9b_real_sr_live.py
```

Names may differ.

Keep existing D9A/D8 tests unchanged except where a small public helper/result extension requires updates.

---

# 50. Validation matrix

Run focused D9B first.

Then cumulative:

```text
complete tests/decision
D9A startup/reconstruction focused surface
D8 policy/publication/finalization focused surface
D7A real SR adapter/runtime surface
relevant non-research SR core/config/lifecycle/replay/serialization tests
commons ConfigManager tests
canonical ingestion outbox/HTF/provenance contract tests
current risk compatibility tests
```

Attempt the full ingestion suite excluding only genuinely environment/Compose-blocked FINAL harness gates already documented.

Static:

```text
Ruff check
Ruff format --check
compileall
git diff --check
trailing-whitespace scan
AST production import boundary scan
forbidden D9C/PEL/PriceRelay pattern scan
repo-local __pycache__ cleanup
```

No external market network calls.

---

# 51. Two-pass coder self-review

## Pass 1 — causal/transaction correctness

Explicitly verify:

```text
read begins after D9A captured IDs
None-tail race uses 0-0 safely
DB-ahead messages do not retrigger decisions
post-startup late bars cannot silently rewrite history
forward stream gaps fail closed
cursor never rolls back with lane failure
cutoff-group processing prevents trigger eviction
one pending trigger only
context reconciliation never manufactures a trigger
stateful trigger cannot be skipped
D6 prepare happens only on causal-ready view
D8 envelope remains canonical
exact signal ID idempotency is correct
ambiguous XADD is reconciled by exact lookup
PUBLISHED/ALREADY_IDENTICAL commit exactly once
CONFLICT/FAILED do not commit state/watermark
checkpoint contains only committed state
checkpoint is after finalization, never before
checkpoint failure after publication never rolls back external side effects
real SR live no-signal progression remains exact
```

## Pass 2 — architecture/simplicity

Verify:

```text
no consumer group/PEL
no service supervisor
no actor/task per lane
no generic event bus
no signal outbox
no second checkpoint framework
no duplicate D3/D4 history catalog
no legacy FeatureVector boundary
no app-to-app production imports
no PriceRelay assumption
no D7B refactor
no shadow-finalization invention
no production model config invention
no risk semantics moved upstream
```

---

# 52. Handoff back to orchestrator

Create/update:

```text
plans/coder-to-orchestrator-decision-app-d9b-live-signal-runtime-v1.md
```

Record:

```text
files/symbols changed
D9A result/static material exposed
D9B config additions and compatibility sources
direct XREAD cursor contract
stream ID comparison rule
input event disposition contract
DB-ahead classification evidence
late/gap/conflict evidence
cursor independence evidence
cutoff-group ordering evidence
pending-trigger rule
bounded context reconciliation behavior
signal publisher exact-ID algorithm
PUBLISHED/ALREADY_IDENTICAL/CONFLICT/FAILED evidence
real SR live NO_SIGNAL evidence
synthetic SIGNAL broker evidence
D8 finalization ordering evidence
post-commit checkpoint persistence evidence
checkpoint failure-after-commit evidence
risk compatibility evidence
focused/cumulative/SR/ingestion/risk test counts
local infrastructure availability/result
Ruff/format/compile/diff/import/forbidden-pattern/cache evidence
Pass 1 findings
Pass 2 findings
residual risks
D9C and PriceRelay carry-forward
```

Do not claim:

```text
full continuous runtime service
reconnect supervision
asset lifecycle hot updates
FastAPI readiness/control plane
PriceRelay
live soak/load certification
shadow parity
production cutover
```

Do not start D9C automatically.

Final line exactly:

```text
DECISION_APP_D9B_LIVE_SIGNAL_RUNTIME_READY_FOR_REVIEW
```
