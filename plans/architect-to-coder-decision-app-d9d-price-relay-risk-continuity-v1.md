---
goal: Implement the model-independent decision_app PriceRelay and prove downstream risk SL/TP continuity, retry, restart, and pause behavior without adding model plugins or changing risk mathematics
stage: architect-to-coder
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d9d, price-relay, risk, continuity, compatibility]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Architect-to-coder — decision_app D9D PriceRelay / risk continuity

## 1. Starting point

Continue only in the existing cumulative isolated worktree:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

Approved programme state before this package:

```text
D0-D9C                              APPROVED
Pre-D9D architecture hardening      APPROVED
```

Frozen behavior includes:

```text
one decision_app runtime process
one market-loop task + one lifecycle-loop task
D9A bounded PIT startup/reconstruction
D9B direct-XREAD market transaction
D8 exact-ID signal publication/finalization
D9C generation/lifecycle/control shell
lane-local failure isolation
no causal whole-generation auto-rebuild
explicit catalog / no dynamic plugin discovery
```

This package is D9D only.

Do not commit, merge, push, switch branches, reset, restore, or modify the primary checkout.

Do not start D10/D11/D12/D13 automatically.

---

# 2. User constraint — no model work

The user explicitly froze model integration until later refactoring.

Therefore D9D must not:

```text
add a new model plugin
add Momentum/D7B
refactor an existing model family
add a dummy model solely to make PriceRelay runnable
change SR math/output semantics
expand DataResolver for a model
```

The existing representative SR adapter may remain untouched as already-approved evidence.

PriceRelay must work for a **relay-only asset with zero model lanes**.

---

# 3. Objective

Implement the D0-independent price path:

```text
canonical ingestion closed candle
        ↓
InputReadCursor / BarStore
        ↓
PriceRelay
        ↓
price_update:{asset}:{timeframe}
        ↓
risk_app
        ↓
SL/TP + trailing/unrealized monitoring
```

with these core invariants:

```text
model/lane failure cannot stop PriceRelay
operator model pause cannot stop PriceRelay
PriceRelay failure cannot roll back InputReadCursor
PriceRelay failure cannot roll back LaneCommitWatermark
one relay-series failure cannot stop unrelated relay series
no missing bar may be silently skipped
restart/gap catch-up preserves every canonical H/L observation needed by risk
```

D9D also fixes the minimum downstream compatibility defects required for safe replay:

```text
risk price PEL is reclaimed after crash
historical pre-position bars cannot affect positions that did not exist
price-derived execution-order timestamps use seconds
```

Do not change risk sizing, SL/TP levels, TP priority, trailing math, or execution policy.

---

# 4. Verified downstream facts — treat as frozen compatibility evidence

## 4.1 Existing wire

Shared stream key:

```text
libs.common.stream_keys.price_update_stream_key(asset, timeframe)
→ price_update:{ASSET}:{timeframe}
```

Current shared payload:

```python
PriceUpdate
├── asset: str
├── timeframe: str
├── timestamp: float
├── open: float
├── high: float
├── low: float
├── close: float
└── volume: float
```

Do not change this public wire in D9D.

## 4.2 Timestamp compatibility

Legacy PriceUpdate timestamp semantics are:

```text
BAR-OPEN epoch MILLISECONDS
```

Verified path:

```text
ingestion payload open_time
  → signal StreamOHLCVPayload.timestamp = open_time seconds
  → normalize_timestamp_ms()
  → PriceUpdate.timestamp = bar-open ms
```

Preserve this exact compatibility representation.

Do not reinterpret PriceUpdate.timestamp as bar close or seconds.

## 4.3 Current legacy publication bounds

Existing signal-app defaults/config:

```text
price_update_stream_maxlen      200
price_update_stream_approximate true
```

D9D decision-owned PriceRelay must use the same values by default/config.

Do not invent larger retention solely for D9D.

## 4.4 Current risk behavior

RiskWorker subscribes to:

```text
signals:{asset}:{tf}
price_update:{asset}:{tf}
```

for its configured timeframes.

Price updates are processed before signal batches.

Risk uses every PriceUpdate:

```text
close → current price / trailing stop / unrealized
high/low/close → single SL/TP
high/low/close → multi-TP / SL
```

There is no staleness filter for PriceUpdate.

Therefore a missing closed bar can hide an SL/TP hit.

Skipping gaps is not compatible with the existing risk contract.

## 4.5 Current risk consumer-group defect

Risk creates `risk_app_price_group`, but startup drains/reclaims only the signal PEL.

Existing comment that price updates are ephemeral is false for SL/TP correctness.

A crash after price delivery but before XACK can strand a risk-critical observation.

D9D must remediate this narrowly.

## 4.6 Position timestamp mismatch

Position/fill entry timestamps are seconds.

PriceUpdate timestamp is bar-open milliseconds.

Historical catch-up therefore requires explicit interval comparison before applying a bar to a position.

---

# 5. Selected D9D architecture

Do **not** add a PriceRelay worker/task.

PriceRelay executes inside the existing bounded D9B market transaction.

Selected topology:

```text
DecisionService market task
        ↓
LiveDecisionRuntime.poll_once()
        ↓
direct canonical XREAD
        ↓
accept canonical records / BarStore
        ↓
PriceRelay.handle accepted canonical progress
        ↓
price_update:* publication / catch-up
        ↓
lane scheduling/evaluation (when enabled)
```

Only the existing two D9C service tasks remain:

```text
1 market task
1 lifecycle task
```

Do not create:

```text
one task per relay
one task per asset
one task per timeframe
price queue
price actor
price supervisor
price event bus
```

---

# 6. Price source identity is canonical series, not model lane

Current D1 `PriceRelayPlan.source_lane` is an unused conceptual placeholder and creates the wrong coupling.

D9D must refine PriceRelayPlan so source identity is the canonical ingestion series.

A model lane must not be required to publish risk prices.

Prefer a plan shape equivalent to:

```text
PriceRelayPlan
├── relay_plan_id
├── manifest_asset
├── asset                 # downstream decision/risk symbol, e.g. BTCUSDT
├── venue
├── instrument_id
├── timeframe
├── stream_key
└── downstream_risk_compatibility
```

One plan per canonical relay series is simpler than one plan with a tuple of timeframes.

`relay_plan_id` should be a readable deterministic canonical identity, for example based only on:

```text
asset + venue + instrument_id + timeframe
```

Do not add another fingerprint framework for PriceRelay.

Remove `source_lane` from the active contract if no approved consumer requires it.

Do not retain lane coupling merely for backwards compatibility with an unused D1 field.

---

# 7. Configuration

## 7.1 Global config

Extend existing decision global config with only publication compatibility settings:

```yaml
decision:
  price_relay:
    stream_maxlen: 200
    stream_approximate: true
```

Use strict immutable settings analogous to current signal publication settings.

No new retry/backoff/concurrency/catch-up-limit knobs.

Catch-up batch bound reuses:

```text
decision.live_input.batch_size
```

because one market poll is already the bounded scheduling unit.

## 7.2 Per-asset relay config

Add a small asset-owned section such as:

```yaml
price_relay:
  enabled: true
  timeframes:
    - 1h
    - 4h
```

Exact class names are implementation details; semantics are frozen.

Rules:

```text
enabled=true -> non-empty relay timeframes required
each relay timeframe must exist in canonical ingestion instrument
each relay timeframe must exist in TimeframeGrid
no duplicate relay timeframes
```

## 7.3 Relay-only asset

`DecisionAssetSettings` currently requires at least one lane.

D9D must allow:

```text
lanes = {}
```

**only** when the asset has an explicitly enabled, non-empty PriceRelay plan.

Reject an asset with:

```text
no lanes
and no enabled price relay
```

Do not weaken `DecisionLaneSettings` or binding validation.

This is required so PriceRelay is genuinely model-independent and so D9D tests do not invent a dummy plugin.

## 7.4 No production asset YAML

Do not create:

```text
configs/decision/assets/BTC.yaml
...
```

D9D uses deterministic injected/test DecisionConfig values.

Production graph remains a later reviewed decision.

---

# 8. Relay plan compilation

Compile PriceRelay plans directly from validated DecisionConfig + canonical ingestion instrument identity.

Keep this small; do not build a second general planner.

A helper in `price_relay.py` or `settings.py` is acceptable.

Each plan must validate:

```text
manifest_asset identity
decision/risk asset identity
venue
instrument_id
timeframe
canonical stream availability
price_update stream key
```

Do not derive relay timeframes from model lanes.

For compatibility tests, prove a relay-only injected config can represent the current risk graph:

```text
BTCUSDT: 1h, 4h
ETHUSDT: 4h
XRPUSDT: 1h
SOLUSDT: 1h
BNBUSDT: 30m
DOGEUSDT: 4h
```

All currently exist in canonical ingestion configuration.

This is a test-only coverage proof, not production decision YAML.

---

# 9. D9A startup integration

D9A remains publication-suppressed.

It must prepare the canonical input state required for PriceRelay without emitting PriceUpdate.

## 9.1 Required series

Change startup required-series compilation to union:

```text
lane D3/D4 canonical series
+
PriceRelay canonical series
```

A relay-only asset therefore causes its canonical streams to be captured/read even with zero decision lanes.

## 9.2 BarStore capacity

Every relay-only series needs bounded BarStore capacity of at least 1.

Do not allocate model warmup history merely for relay.

## 9.3 Manifest gating

Manifest/timeframe LIVE validation must include relay timeframes.

A configured relay series whose asset/timeframe manifest is not LIVE must not become an active relay.

Do not make a stopped relay timeframe block unrelated active assets/relays.

## 9.4 Startup positions

Use existing D9A canonical capture:

```text
captured stream tail
DB latest canonical cutoff
warm_cutoff
```

No PriceUpdate is emitted during D9A replay/warmup.

## 9.5 Startup result

Expose compiled relay plans/static relay-series information from DecisionStartupResult as needed by D9B generation construction.

Do not duplicate the canonical series identity in a second catalog.

---

# 10. PriceRelay runtime module

Add one small decision-owned module, preferably:

```text
src/apps/decision_app/price_relay.py
```

Do not split into planner/transport/service/repository packages unless implementation evidence demonstrates a real need.

Expected responsibilities only:

```text
compile/validate relay plan if not kept in settings
build PriceUpdate from canonical bar
idempotent PriceUpdate transport
per-series continuity/progress
bounded catch-up from canonical history
```

No model logic.

No risk logic except explicit wire compatibility.

---

# 11. PriceUpdate construction

For one canonical closed bar:

```text
PriceUpdate.asset      = plan.asset
PriceUpdate.timeframe  = plan.timeframe
PriceUpdate.timestamp  = int(bar.bar_open_at.timestamp() * 1000)
PriceUpdate.open       = float(bar.open)
PriceUpdate.high       = float(bar.high)
PriceUpdate.low        = float(bar.low)
PriceUpdate.close      = float(bar.close)
PriceUpdate.volume     = float(bar.volume)
```

Preserve legacy bar-open-millisecond timestamp exactly.

Do not include taker volume or provenance in PriceUpdate; public risk wire does not support it.

Canonical provenance remains internal evidence.

---

# 12. Price stream deterministic identity

Use explicit Valkey entry ID:

```text
{int(bar.bar_close_at.timestamp() * 1000)}-0
```

Entry ID is based on **bar close**, while payload timestamp remains **bar open ms**.

Rationale:

```text
entry ID = completed canonical observation identity
payload timestamp = legacy downstream compatibility
```

Do not use wall-clock IDs in the new relay.

Do not change `price_update_stream_key`.

---

# 13. PriceUpdate idempotent publication

Implement the same semantic safety shape as D8 signal transport, locally for PriceUpdate.

Do not create a universal publisher base class.

Suggested outcomes:

```text
PUBLISHED
ALREADY_IDENTICAL
CONFLICT
FAILED
```

Algorithm:

1. `XRANGE stream exact_id exact_id`.
2. Existing exact entry:
   - decode PriceUpdate;
   - semantic payload identical -> `ALREADY_IDENTICAL`;
   - different/decode failure -> `CONFLICT`.
3. If absent: `XADD` explicit ID with configured maxlen/approximate.
4. Returned ID must equal requested ID.
5. On non-cancellation XADD exception/ambiguity:
   - exact lookup again;
   - identical -> `ALREADY_IDENTICAL`;
   - different -> `CONFLICT`;
   - exact ID absent but stream head is already newer than requested ID -> `CONFLICT`;
   - otherwise `FAILED`.
6. Cancellation propagates.

Use:

```text
stream_maxlen = decision.price_relay.stream_maxlen (default 200)
stream_approximate = decision.price_relay.stream_approximate (default true)
```

Do not generate another stream ID to escape conflict.

---

# 14. Legacy co-ownership safety

Legacy signal_app currently publishes to the same `price_update:*` streams with auto-generated Valkey IDs.

Decision PriceRelay must never share authoritative production ownership with that legacy publisher.

Therefore:

```text
D9D tests → isolated broker/fake only
D11 shadow → must not publish to production price_update streams
D12 cutover → stop legacy signal price publisher before decision PriceRelay owns production streams
```

If the first explicit decision ID is not forward of the existing stream head, fail closed as `CONFLICT`.

Do not delete/truncate/rewrite the production stream to solve this.

---

# 15. PriceRelayProgress semantics

Maintain one progress object per relay plan/series.

Keep D1 vocabulary:

```text
CONTINUOUS
GAP_DETECTED
UNRESOLVED
```

`latest_market_as_of` means:

```text
latest canonical bar close whose PriceUpdate publication is known PUBLISHED or ALREADY_IDENTICAL
```

Never advance progress for:

```text
FAILED
CONFLICT
missing canonical bar
malformed downstream tail
```

Gap evidence should remain bounded and explicit, e.g. only current relevant facts:

```text
expected_next_market_as_of
observed_target_market_as_of
reason
backlog_bars
baseline_source
```

No historical failure journal.

---

# 16. Relay bootstrap against downstream price stream

PriceRelay is constructed after D9A startup and before live polling starts.

For each active relay plan, inspect current downstream stream tail with bounded `XREVRANGE count=1`.

Decode/validate the tail PriceUpdate against the canonical series.

## 16.1 Valid downstream tail

From payload:

```text
bar_open_at = PriceUpdate.timestamp milliseconds
bar_close_at = bar_open_at + canonical timeframe duration
```

Fetch the exact canonical history record at that bar open.

Require exact semantic OHLCV/volume match.

If valid:

```text
progress.latest_market_as_of = canonical bar_close_at
```

Then compare with D9A warm cutoff:

```text
tail == warm cutoff  -> CONTINUOUS
tail < warm cutoff   -> GAP_DETECTED / catch-up required
tail > warm cutoff   -> UNRESOLVED
```

A downstream stream must never be considered more authoritative than canonical ingestion.

## 16.2 Malformed/mismatched tail

If tail:

```text
cannot decode
wrong asset/timeframe
not timeframe-aligned
canonical record missing
OHLCV differs from canonical
```

set relay `UNRESOLVED`.

Do not overwrite the stream.

## 16.3 No downstream tail

If no downstream PriceUpdate exists but D9A has a canonical warm cutoff:

```text
establish startup baseline at the canonical warm cutoff
continuity_status = CONTINUOUS
latest_market_as_of = warm cutoff
gap_evidence.baseline_source = startup_canonical_cutoff
gap_evidence.downstream_tail_present = false
```

Do **not** publish all historical bars before the startup baseline.

This baseline permits clean first-start operation, but does not certify legacy handoff continuity.

D12 must separately prove the actual production ownership handoff.

If both downstream tail and canonical warm cutoff are absent:

```text
latest_market_as_of = None
continuity_status = UNRESOLVED
```

The first valid closed canonical bar may establish the baseline/publication forward.

---

# 17. Catch-up semantics — missed bars must be replayed

Risk uses high/low to trigger SL/TP, so a missed canonical closed bar cannot be discarded.

When:

```text
relay progress < canonical target
```

replay exact missed canonical bars in chronological order.

Rules:

```text
start from exact next canonical interval
never jump ahead
never manufacture a missing bar
never use projected/incomplete bars
validate exact canonical geometry/provenance
```

Fetch from canonical Timescale history through the existing history repository.

## 17.1 Bounded work

At most:

```text
decision.live_input.batch_size
```

catch-up publications per relay plan per reconciliation step/poll.

Do not add a separate catch-up-size config.

While backlog remains:

```text
continuity = GAP_DETECTED
```

After exact final missing bar publishes:

```text
continuity = CONTINUOUS
```

## 17.2 Retention safety

Because downstream PriceUpdate stream maxlen is 200, if required catch-up backlog exceeds:

```text
price_relay.stream_maxlen
```

mark `UNRESOLVED` and do not attempt partial publication that cannot guarantee the complete retained catch-up set for an offline risk consumer.

Do not silently retain only the newest 200 and claim continuity.

## 17.3 Missing canonical history

If the exact next bar is absent from canonical durable history:

```text
UNRESOLVED
no progress advance
```

No skip-to-latest behavior.

## 17.4 Transport failure

On `FAILED`:

```text
no progress advance
gap remains
next poll may retry same exact bar
```

On `CONFLICT`:

```text
UNRESOLVED
no automatic stream rewrite
```

---

# 18. Live D9B integration ordering

Within each accepted market cutoff group:

```text
1. accept/append canonical records
2. reconcile/publish all eligible PriceRelay series for that accepted progress
3. only then evaluate model lanes when lane evaluation is enabled
```

PriceRelay cannot be a side effect of successful model evaluation.

If relay publication fails:

```text
InputReadCursor stays advanced for accepted canonical bar
BarStore stays advanced
relay progress does not advance
model lane may still evaluate if its own causal inputs are safe
unrelated relay series continue
```

Do not roll back market input because a downstream price transport failed.

---

# 19. DecisionPollResult / service observability

Extend bounded poll evidence to include relay results/progress.

Keep it small, e.g. per relay plan:

```text
relay_plan_id
stream_key
target_market_as_of
published_market_as_of
publication_outcome
continuity_status
reason
backlog_bars
```

D9C cached snapshot should expose bounded PriceRelay evidence.

Prefer integrating into existing:

```text
GET /runtime
GET /runtime/inputs
```

rather than adding a new endpoint solely for PriceRelay.

Service state:

```text
any GAP_DETECTED / UNRESOLVED / relay FAILED or CONFLICT
    -> service DEGRADED
```

But:

```text
market input continues
healthy relay series continue
healthy lanes continue
```

No automatic whole-generation rebuild solely for a price relay gap/failure.

---

# 20. Operator PAUSE semantics must change in D9D

Current D9C pause stops the entire market poll.

That was acceptable before PriceRelay existed, but violates D0 once open-position monitoring depends on PriceRelay.

D9D freezes new pause semantics:

```text
PAUSED = pause decision/model evaluation and signal publication
         NOT canonical input / PriceRelay
```

## 20.1 Runtime primitive

Extend the existing bounded live primitive minimally, for example:

```python
poll_once(*, evaluate_lanes: bool = True)
```

or equivalent explicit flag.

When `evaluate_lanes=False`:

```text
direct XREAD continues
canonical acceptance continues
InputReadCursor continues
BarStore continues
PriceRelay continues
NO trigger scheduling for model lanes
NO ModelRuntime.prepare_live
NO DecisionPolicy
NO signal publication
NO lane state commit
NO LaneCommitWatermark advance
```

Do not invent a second input-only runtime.

## 20.2 DecisionService PAUSED loop

When desired/service state is PAUSED:

```text
market task remains alive and continues bounded poll_once(evaluate_lanes=False)
lifecycle watcher remains alive
readiness remains false / PAUSED
```

No 50 ms wake spin.

Use the existing blocking direct-XREAD as pacing.

## 20.3 Resume

Resume still MUST:

```text
finish current bounded paused poll
fresh D9A reconstruction
fresh D9B generation
then re-enable lane evaluation
```

Bars accumulated while paused are reconstructed publication-suppressed.

No stale historical signal is emitted on resume.

## 20.4 Lifecycle while globally paused

A configured lifecycle change may require a fresh generation.

If generation rebuild occurs while operator desired_state remains PAUSED:

```text
install fresh generation
preserve desired_state = PAUSED
preserve service_state = PAUSED
continue input + PriceRelay only
```

Do not accidentally resume model evaluation because a lifecycle reconciliation completed.

## 20.5 Stop

STOPPING/STOPPED still stops all market input and PriceRelay after current bounded poll finishes.

---

# 21. Risk-side compatibility remediation — timestamp normalization

Do not change the PriceUpdate schema.

In RiskWorker `_process_price_update`:

```text
bar_open_seconds = PriceUpdate.timestamp / 1000
bar_close_seconds = bar_open_seconds + timeframe_duration_seconds
```

Use:

```text
libs.common.timeframes.timeframe_to_seconds(timeframe, default=0)
```

and reject/fail processing when returned duration <= 0.

Do not silently use the helper's normal 60-second default for an invalid risk timeframe.

Price-derived `OrderExecutionRequest.timestamp` must become:

```text
bar_close_seconds
```

so execution-facing timestamps are seconds.

`pending_close_requested_at` must also use `bar_close_seconds`.

Keep the existing PriceUpdate payload timestamp in the idempotency key:

```text
int(price_update.timestamp)
```

because that is stable bar-open-ms retry identity and preserves existing key compatibility.

Do not alter signal-derived order timestamp behavior.

---

# 22. Replay-safe position eligibility

Historical catch-up bars must not act on positions that did not exist for that completed interval.

Add an optional causal cutoff to existing PositionTracker price/SLTP methods rather than a new replay engine.

Affected operations used by RiskWorker:

```text
update_prices
update_trailing_stops
check_sl_tp_hlc
check_sl_tp_hlc_multi
```

Semantics when `bar_close_seconds` is supplied:

```text
skip position if position.entry_timestamp >= bar_close_seconds
```

Interpretation:

```text
bar closed before/equal position entry -> position did not exist for this completed bar
bar interval contains entry (bar_open < entry < bar_close) -> process bar
```

The second rule preserves current live bar-based semantics; we do not have intrabar post-entry OHLC, so D9D must not invent it.

Existing callers that omit the cutoff retain old behavior.

Do not change SL/TP mathematics or priority.

Prove both:

```text
fully pre-entry catch-up bar is ignored for the new position
entry-inside-bar catch-up still follows existing H/L semantics
```

---

# 23. Risk price PEL recovery

Replace the current incorrect assumption that price heartbeats are ephemeral.

Keep current signal PEL behavior.

Add one narrow method such as:

```text
_drain_price_pel()
```

called after `_drain_signal_pel()` and before normal `>` reads.

For each `price_stream_key`:

1. use existing `xautoclaim` pattern;
2. group = `risk_app_price_group`;
3. consumer = existing worker consumer name;
4. `min_idle_time = self.pel_reclaim_idle_ms`;
5. `count = self.batch_size`;
6. process each message with existing `_process_price_update`;
7. XACK only after successful processing;
8. processing failure leaves message pending;
9. repeat until no reclaimable messages / cursor complete.

Do not add a second PEL framework or new retry settings.

The existing pending-close idempotency plus deterministic close-order key prevents duplicate in-process close requests after a successful first processing.

Add explicit tests for crash/reclaim retry.

---

# 24. Risk consumer processing order

Preserve current normal-loop behavior:

```text
price updates before signal batch
```

Do not merge price and signal PELs into one generic consumer abstraction.

Startup order should be:

```text
signal PEL drain
price PEL drain
normal live loop
```

The replay-safe position eligibility rule prevents old price observations from applying to positions created after those bars.

---

# 25. No new risk policy

D9D must not change:

```text
position sizing
risk rules
signal aggregation
SL distance
TP targets
TP portions
TP-over-SL same-bar priority
trailing-to-breakeven policy
open/close exposure policy
```

Only transport/time/replay compatibility changes are allowed in risk code.

---

# 26. Signal-entry gating is NOT part of D9D

Do not add a new price-health gate to risk or DecisionPolicy.

Runtime may report:

```text
PriceRelay GAP_DETECTED / UNRESOLVED
```

without changing model/risk math.

D12 cutover certification must require required PriceRelay plans to be `CONTINUOUS` before production authoritative signal ownership is enabled.

Do not pre-build that cutover gate here.

---

# 27. Lifecycle semantics

PriceRelay availability follows canonical ingestion manifest/timeframe availability, not model-lane availability.

For asset manifest/timeframe:

```text
LIVE -> relay active
PAUSED/STOPPED/REMOVING -> relay not active for new market input after fresh lifecycle generation
```

Operator `/runtime/pause` is different from ingestion asset PAUSED:

```text
operator pause -> model evaluation paused, PriceRelay stays active
asset lifecycle pause -> canonical asset availability stops; fresh generation reflects it
```

Keep these concepts distinct.

Do not invent risk liquidation behavior on asset removal.

---

# 28. Required production file scope

Expected/allowed changes are bounded to:

```text
src/apps/decision_app/contracts.py
src/apps/decision_app/settings.py
src/apps/decision_app/startup.py
src/apps/decision_app/live_runtime.py
src/apps/decision_app/service.py
src/apps/decision_app/bootstrap.py
src/apps/decision_app/price_relay.py              # new, preferred single module
src/apps/decision_app/api/routes.py                # bounded status only if needed
src/apps/decision_app/composition.py               # only if relay static composition requires it
configs/decision/global.yaml

src/apps/risk_app/runtime/worker.py
src/libs/risk/position_tracker.py

docs/architecture/decision_app/README.md
docs/architecture/decision_app/contracts.md
```

Shared `PriceUpdate` contract should remain unchanged unless a discovered blocker proves impossible otherwise; report that instead of broadening it casually.

Tests under:

```text
tests/decision/
tests/risk/
```

plus existing compatibility tests as needed.

Do not change production signal_app to implement D9D.

---

# 29. Explicit non-goals

Do not implement:

```text
new model/plugin integration
model refactoring
D7B
new DataResolver sources
new state codec vocabulary
price tick websocket
new market-data provider
local candle aggregation
PriceRelay task/process
risk direct ingestion feed
signal outbox
price outbox
PriceRelay DB checkpoint table
persistent decision InputReadCursor
consumer group for decision market input
D10 resource certification
D11 shadow parity
D12 cutover
D13 legacy retirement
main.py / decision service HTTP port
Docker/Compose decision service
production decision asset YAML
```

---

# 30. Required D9D tests — PriceRelay core

Add focused tests, preferably:

```text
tests/decision/test_d9d_price_relay.py
tests/decision/test_d9d_price_relay_runtime.py
```

Prove at minimum:

### 30.1 Plan/config

```text
relay-only asset with lanes={} is valid
lanes={} + no enabled relay is rejected
relay TF must exist in canonical instrument/grid
relay plan source identity is canonical series, not lane
current six risk asset/TF routes can be represented by injected canonical config
```

### 30.2 Wire parity

For canonical bar:

```text
PriceUpdate payload decodes with current shared contract
asset/timeframe exact
timestamp = bar-open ms
OHLCV exact float compatibility
stream key exact price_update:{asset}:{tf}
entry ID = bar-close ms-0
```

### 30.3 First publication / idempotency

```text
absent exact ID -> PUBLISHED
pre-existing identical -> ALREADY_IDENTICAL
pre-existing different -> CONFLICT
XADD inserts then raises -> lookup identical -> ALREADY_IDENTICAL
XADD failure with no entry -> FAILED
exact absent behind newer stream head -> CONFLICT
```

### 30.4 Startup baseline

```text
valid downstream tail == canonical warm cutoff -> CONTINUOUS
valid tail behind canonical -> GAP_DETECTED
valid tail ahead canonical -> UNRESOLVED
malformed/mismatched tail -> UNRESOLVED
no tail + canonical warm cutoff -> startup canonical baseline, no historical replay
```

### 30.5 Catch-up

```text
1 missing bar -> publish exact bar -> CONTINUOUS
multiple missing bars -> chronological order
batch_size bounds publications per step
backlog remains -> GAP_DETECTED
missing exact canonical bar -> UNRESOLVED
backlog > stream_maxlen -> UNRESOLVED without partial fake continuity
transport failure -> no progress advance
conflict -> no progress advance / UNRESOLVED
```

### 30.6 Independence

```text
relay A failure does not block relay B
relay failure does not rollback InputReadCursor
relay failure does not rollback lane watermark
lane RECONSTRUCTION_REQUIRED does not stop healthy PriceRelay
lane HALTED/INVALID does not stop healthy PriceRelay
relay-only generation publishes price with zero lanes
```

---

# 31. Required D9D tests — pause/lifecycle/service

Prove through actual DecisionService:

```text
operator pause returns PAUSED/PAUSED
while paused, market poll continues in evaluate_lanes=False mode
InputReadCursor advances while paused
PriceRelay publishes while paused
no ModelRuntime/policy/signal transaction occurs while paused
LaneCommitWatermark does not advance while paused
resume waits for current bounded paused poll
resume builds fresh D9A/D9B generation
historical bars accumulated during pause do not emit stale signal
lifecycle rebuild while operator-paused preserves PAUSED desired/service state
PriceRelay continues on fresh paused generation when manifest remains LIVE
stop waits for current bounded poll then stops all PriceRelay/input
```

Update existing D9C tests whose old assumption was “pause means no market poll.”

The new invariant is:

```text
pause means no model/lane evaluation, not no market input.
```

---

# 32. Required D9D tests — risk compatibility

Add/extend risk tests proving:

### 32.1 Timestamp conversion

```text
PriceUpdate timestamp remains bar-open ms
risk derives bar-close seconds from timeframe
SL/TP OrderExecutionRequest.timestamp == bar-close seconds
pending_close_requested_at == bar-close seconds
idempotency key still includes original bar-open ms
invalid timeframe fails price processing
```

### 32.2 Replay-safe position filter

```text
position entry >= catch-up bar close -> bar ignored for that position
position entry inside bar interval -> existing H/L SL/TP semantics apply
new live bar after entry -> existing semantics unchanged
current price/unrealized/trailing operations obey same eligibility cutoff
```

### 32.3 Price PEL

```text
run() drains signal PEL then price PEL
reclaimed price message processes via _process_price_update
successful reclaimed price is XACKed from risk_app_price_group
processing failure leaves price pending
reclaimed SL/TP hit produces exactly one pending close request/order
pending-close position prevents a later duplicate close request
```

### 32.4 Existing risk math stays green

Keep all existing single-TP, multi-TP, trailing, pending-close and order metadata tests green.

---

# 33. Required compatibility proof — current risk graph

Without adding production decision YAML, construct a test-only relay-only DecisionConfig covering the current configured risk graph:

```text
BTCUSDT  1h,4h
ETHUSDT  4h
XRPUSDT  1h
SOLUSDT  1h
BNBUSDT  30m
DOGEUSDT 4h
```

Prove:

```text
each relay resolves to canonical ingestion instrument
each stream key equals current RiskWorker expected key
no model lane/plugin is required
```

Do not make D9D depend on `discover_asset_timeframes()` at runtime; this is compatibility evidence only.

Decision configuration remains the future ownership source for decision PriceRelay.

---

# 34. Existing architecture guardrails

Update `tests/decision/test_architecture_guardrails.py` only as necessary so it continues to forbid accidental architecture drift while allowing the intentional D9D runtime.

Keep forbidden:

```text
legacy signal/strategy runtime imports in decision_app
FeatureVector/ModelManager legacy surface
consumer groups/PEL in decision market/lifecycle input
dynamic plugin discovery
model implementation imports in generic orchestration
model-specific branches in generic orchestration
signature guessing / compatibility wrappers
```

Do **not** forbid legitimate new:

```text
price_relay.py
PriceUpdate
price_update_stream_key
```

RiskWorker may continue to use its existing consumer groups/PEL; the decision-app PEL prohibition is unchanged.

---

# 35. Validation

Run focused first:

```text
new D9D PriceRelay tests
D9B live-input/live-runtime/signal transport tests
D9C service/control tests
architecture guardrails
risk worker + position tracker tests
```

Then cumulative:

```text
complete tests/decision
relevant non-research SR adapter/core/replay/import slice
risk suite / risk-v2 compatibility as appropriate
signal wire compatibility tests
execution order-contract tests affected by timestamp normalization
ingestion lifecycle/outbox/HTF/provenance contract slice
commons stream consumer/timeframe/config tests
```

Static:

```text
Ruff check
Ruff format --check
compileall
git diff --check
trailing whitespace
production app import boundary
no decision XREADGROUP/XACK/XAUTOCLAIM/XGROUP
no new model plugin/integration
no D10/D11/D12/D13 leakage
no main.py / decision Compose service
no production decision asset YAML
repo-local __pycache__ cleanup
no-network decision import smoke
```

If the worktree still has no `.env`, record exactly:

```text
LOCAL_INFRASTRUCTURE_VALIDATION_BLOCKED_ENVIRONMENT
```

Do not copy/create credentials or mutate shared/external price/signal streams merely to force a live test.

Real price-stream integration, when possible, must use isolated broker state only while legacy signal_app is still a potential publisher.

---

# 36. Adversarial review matrix

Before handoff, explicitly reason through and test where practical:

```text
bar accepted, relay XADD fails, lane succeeds
bar accepted, relay succeeds, lane fails
one relay conflicts, another relay succeeds
operator pause during active market poll
operator resume during paused relay poll
lifecycle event during operator pause
relay backlog appears while model lane already degraded
legacy stream head newer than decision explicit ID
risk crash after price delivery before XACK
risk restart with price PEL message older than current position entry
risk restart with price PEL message containing position entry interval
catch-up SL/TP generates order then duplicate price retry arrives
```

No hidden rollback across these independent progress domains.

---

# 37. Two-pass coder self-review

## Pass 1 — causal/downstream correctness

Verify:

```text
PriceUpdate wire parity exact
bar-open ms payload timestamp exact
bar-close explicit stream ID exact
catch-up is chronological and closed-bar-only
no canonical gap skip
PriceRelayProgress advances only on idempotent success
relay errors do not rollback input/lane progress
pause keeps risk price path alive
resume reconstructs model state before evaluation resumes
risk replay never applies fully pre-entry bar to later position
risk price-derived order timestamp is seconds
price PEL is reclaimable and acked only after success
SL/TP math unchanged
```

## Pass 2 — anti-overengineering

Verify:

```text
no third service task
no relay worker per asset/tf
no price event bus
no relay DB table
no generic publisher hierarchy
no new recovery framework
no new model plugin/refactor
no dummy model lane
no production decision asset YAML
no new retry/concurrency/catch-up knob
no risk policy change
```

---

# 38. Handoff

Create/update:

```text
plans/coder-to-orchestrator-decision-app-d9d-price-relay-risk-continuity-v1.md
```

Include:

```text
files/symbols changed
PriceRelay config/plan identity
relay-only asset proof
D9A required-series/capacity changes
PriceUpdate wire parity evidence
publisher idempotency matrix
bootstrap/downstream-tail evidence
catch-up/retention evidence
pause/resume PriceRelay evidence
failure-isolation evidence
risk timestamp normalization evidence
risk pre-entry replay filtering evidence
risk price PEL reclaim evidence
current risk graph compatibility proof
focused/cumulative validation counts
static/architecture guard results
local infrastructure gate
Pass 1 findings
Pass 2 findings
residual risks
D10/D11/D12 carry-forward
```

Do not claim:

```text
production decision asset config exists
legacy price publisher is cut over
production stream ownership is safe
resource certification complete
shadow parity complete
production cutover complete
```

Do not start D10 automatically.

Final line exactly:

```text
DECISION_APP_D9D_PRICE_RELAY_RISK_CONTINUITY_READY_FOR_REVIEW
```
