---
goal: Implement the first real decision_app runtime infrastructure package: deterministic config, canonical ingestion event/history adapters, exact startup snapshotting, bounded stateful reconstruction, and minimal durable lane-state checkpoints without starting continuous live consumption or signal publication
stage: architect-to-coder
date_created: 2026-08-14
last_updated: 2026-08-14
owner: Quant Orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d9a, runtime, startup, reconstruction, checkpoint, ingestion]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Architect-to-coder — `decision_app` D9A startup/runtime reconstruction foundation

## 1. Objective

D0-D8 and D7A are approved. D9 is the first infrastructure/runtime programme.
Do **not** implement the entire D9 runtime in one step.

D9A implements and certifies only the startup/restart boundary:

```text
decision config
+ canonical ingestion market geometry
+ ingestion manifests
        ↓
static D2/D4/D5/D6/D8 plans
        ↓
capture canonical stream tails
+ capture canonical Timescale cutoffs
        ↓
load exact matching lane-state checkpoint when present
        ↓
bounded Timescale history reads
        ↓
causal publication-suppressed reconstruction
        ↓
final bounded BarStore
+ initialized ModelRuntime state stores
+ baseline LaneCommitWatermarks
+ InputReadCursor positions
        ↓
STARTUP_READY snapshot
```

D9A must stop before:

```text
continuous XREAD loop
signal XADD
actual D8 publication acknowledgement
PriceRelay publication
asset lifecycle event consumer
FastAPI application/runtime loop
Docker/Compose decision service
multi-hour soak
D9B/D9C/D9D
```

Expected final status:

```text
DECISION_APP_D9A_STARTUP_RECONSTRUCTION_READY_FOR_REVIEW
```

Continue only in the existing cumulative isolated worktree:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

No commit, merge, push, branch switch, reset, restore, or primary-checkout write.

---

# 2. Why D9A is separate

The runtime is now behaviorally complete offline:

```text
D3 market state
D4 features
D5 external data
D6 model execution/state/rewarm
D7A real stateful SR adapter
D8 policy/publication/finalization semantics
```

The first real integration risk is therefore no longer model logic. It is startup causality:

```text
broker tail
vs
Timescale history
vs
state checkpoint
vs
lane resume cutoff
```

A live reader must not race ahead of the history used to reconstruct state.
D0 explicitly froze:

```text
capture stream tails/candle cutoffs
→ warm durable history
→ reconstruct state with publication suppressed
→ begin live reads after captured stream IDs
```

D9A proves exactly that boundary before any continuous reader is added.

---

# 3. Measured D0 checkpoint exception

D0 deliberately rejected a generic checkpoint framework, but allowed a checkpoint only after a measured reconstruction problem with explicit versioning and causal validation.

That measured problem now exists:

```text
ingestion.candles retention = 90 days
SR state retains terminal BROKEN/EXPIRED zone audit history indefinitely
```

Replaying only the retained 90-day candle window cannot reproduce an arbitrarily old full SR encoded state byte-for-byte after long uptime.

Therefore D9A may add exactly one minimal checkpoint mechanism:

```text
latest successfully reconstructed/finalized state
per exact LaneExecutionIdentity
```

This is **not** a general checkpoint framework.

Do not add:

```text
checkpoint history browser
checkpoint DAG
arbitrary named checkpoints
periodic scheduler framework
event journal
state mutation log
checkpoint inheritance
cross-lane checkpoint dependencies
snapshot compaction framework
```

The checkpoint exists only to preserve exact state continuity across process restarts while the canonical market history remains bounded.

---

# 4. First-deployment state inception vs restart continuity

Distinguish these cases explicitly.

## 4.1 No existing checkpoint

This is a new state identity/inception.

Use a bounded plugin-owned initialization horizon and define the first replay step as the explicit state inception.

D6 already allows:

```text
no committed baseline
→ caller-selected first rewarm step
```

Do not claim that first deployment reconstructs hypothetical model state from before the selected inception.

## 4.2 Matching checkpoint exists

The checkpoint is authoritative state continuity for that exact execution identity.

Load it, then replay **every required trigger transition after the checkpoint cutoff** through the captured startup resume cutoff.

No transition may be skipped.

## 4.3 Checkpoint is too old for retained canonical history

If the next required trigger after the checkpoint is no longer available in Timescale:

```text
FAIL CLOSED
```

Do not silently reset state from a later inception.
Do not discard the checkpoint and continue.
Do not publish.

Return an explicit startup/reconstruction blocker requiring operator action.

---

# 5. D9A production scope

Prefer a small structure such as:

```text
src/apps/decision_app/
  settings.py
  ingestion_input.py
  startup.py
  runtime_plugins.py                 additive reconstruction metadata only
  storage/
    __init__.py
    schema.sql
    bootstrap.py
    repository.py
    state_codec.py
```

Exact filenames may vary if a smaller structure is clearer.

Tests preferably:

```text
tests/decision/test_settings.py
tests/decision/test_ingestion_input.py
tests/decision/test_checkpoint_repository.py
tests/decision/test_startup_reconstruction.py
```

Integration tests may be added under an existing decision/integration convention if appropriate.

Do not touch legacy `signal_app` or `strategy_app` production code.
Do not modify canonical ingestion behavior.

---

# 6. Decision configuration boundary

D9A is the first phase allowed to implement the documented decision config namespace.

Use:

```text
configs/decision/global.yaml
configs/decision/assets/{MANIFEST_ASSET}.yaml
```

Extend the existing `ConfigManager`; do not create a second config system.

Use frozen strict Pydantic models with `extra="forbid"` for decision config.

Do not add inheritance, expressions, templates, wildcard model expansion, or hot graph mutation.

Graph/config changes apply on process restart only in V1.

## 6.1 Canonical market geometry remains ingestion-owned

Do **not** duplicate timeframe durations/alignment in decision YAML.

D9A must read and validate the existing canonical config values through `ConfigManager`:

```text
ingestion.calendar
ingestion.timeframes
ingestion.assets
```

Do not import `apps.ingestion_app.settings` into decision production code.
Treat the ingestion config namespace as an external configuration contract and validate only the fields decision_app needs.

Construct D3 `TimeframeGrid` from:

```text
ingestion.calendar.alignment_origin
ingestion.timeframes[*].duration_seconds
```

Require continuous UTC semantics already approved by ingestion.

---

# 7. Explicit asset identity mapping

Do not overload one `asset` field with two different meanings.

Current repository reality:

```text
ingestion manifest asset code: BTC
canonical instrument_id:       BTC-USDT-PERP
downstream/risk signal asset:  BTCUSDT
venue:                         binance
```

Decision asset configuration must explicitly carry at least:

```text
manifest_asset       # e.g. BTC, ingestion lifecycle authority key
decision_asset       # e.g. BTCUSDT, D2 lane asset / downstream route identity
venue
instrument_id
enabled
lanes
```

Validate against canonical ingestion config:

```text
manifest_asset exists in ingestion.assets
instrument_id exists under that ingestion asset
venue matches ingestion instrument venue
configured decision/trigger/required timeframes exist on the ingestion instrument
```

Where the canonical live provider symbol is available, validate that the configured downstream identity is consistent with the intended tradable symbol rather than guessing.

Do not derive `BTCUSDT` from string concatenation.

---

# 8. Asset/lane config mapping

Decision asset YAML should map cleanly to existing D2 contracts.

Conceptually:

```yaml
manifest_asset: BTC
decision_asset: BTCUSDT
venue: binance
instrument_id: BTC-USDT-PERP
enabled: true

lanes:
  sr_context_1h:
    decision_timeframe: 1h
    trigger_timeframe: 1h
    trigger_mode: on_bar_close
    authority: shadow
    risk_profile_key: null
    policy:
      name: passthrough
      version: "1"
      parameters:
        source_slot: sr_primary
    bindings:
      sr_primary:
        plugin: sr
        version: "1"
        parameters: {...}
        dependencies: {}
```

Do not add a real production SR asset file by inventing model parameters.
Use deterministic test config fixtures unless an already-approved production model configuration exists in the repository.

`configs/decision/global.yaml` may contain only genuinely global decision settings required by D9A and an operator feature allowlist. Do not pre-populate speculative runtime knobs for later D9 phases.

---

# 9. Compile static decision plans at startup

D9A startup must compile existing approved plans rather than inventing runtime graph logic.

Use:

```text
PluginCatalog
StaticCompositionPlanner / compile_decision_plan
FeatureCatalog / FeaturePolicy / compile_feature_plan
DataPolicy / compile_data_plan
DecisionPolicyCatalog
RuntimePluginCatalog
```

D9A must not rebuild dependency ordering.

The startup coordinator should accept explicit catalogs/registries rather than performing import scanning.

For the currently approved real model path, register only approved real components needed by the test/runtime bundle, including:

```text
SR_MODEL_SPEC
SRDecisionPlugin factory
SR_ATR_DEFINITION
PASSTHROUGH_V1 / PRIORITY_V1 as applicable
```

Do not opportunistically register/refactor D7B models.

---

# 10. Small state-initialization requirement at runtime-plugin registration

D9A needs a bounded first-inception replay horizon for stateful plugins.
Do not expand `DecisionModelPlugin` with lifecycle callbacks.

Prefer a tiny optional runtime-registration field/callback on `RuntimePluginDefinition`, e.g.:

```text
initialization_requirement(binding) -> StateInitializationRequirement
```

with a small immutable shape such as:

```text
StateInitializationRequirement
  trigger_steps: positive int
```

Rules:

```text
stateless binding -> no initialization requirement needed
stateful binding -> D9A requires an explicit bounded initialization requirement
missing/unbounded stateful requirement -> startup fails closed
```

This is app-runtime metadata, not quantitative model I/O and not a generic lifecycle API.

## 10.1 SR initialization requirement

Derive SR initialization steps from its resolved binding configuration; do not hardcode one global number.

The horizon must cover at least the state lifecycle memory implied by the configured SR parameters, including:

```text
lifecycle.max_age_bars
detection.pivot_span_bars
```

Use a conservative, documented formula proven by tests. The feature prehistory needed to compute ATR is handled separately by the D4 feature plan/history requirement and must not be double-counted as SR state transitions.

The first deployment explicitly defines state inception at the first supplied replay step. The initialization horizon is intended to establish a complete current operational state from that inception, not recreate nonexistent pre-inception audit history.

---

# 11. Canonical ingestion stream adapter

Add a decision-owned transport parser for the frozen external ingestion stream contract.

Production decision code must **not** import ingestion domain/repository/service classes.

The supported transport is frozen as:

```text
stream key:
  stream:ohlcv:ingestion:{venue}:{instrument_id}:{timeframe}

outer fields:
  event_id
  event_type = candle.committed
  schema_version = 1
  producer = ingestion
  occurred_at
  payload
```

Payload:

```text
venue
instrument_id
timeframe
open_time
close_time
open
high
low
close
volume
taker_buy_base
source_type
source_provider
source_timeframe
```

D9A may define local versioned consumer constants for this external protocol.
Add cross-contract tests using the real ingestion event builder/publisher helpers **in tests only** so producer/consumer drift is caught without a production app-to-app import.

---

# 12. Ingestion event parsing rules

Build one immutable parsed result, e.g.:

```text
CanonicalMarketEvent
  stream_key
  stream_id
  event_id
  occurred_at
  series_key: MarketSeriesKey
  bar: CausalBarView
  source provenance
```

Validate fail-closed:

```text
exact supported event_type/schema_version/producer
stream identity == payload venue/instrument/timeframe
configured expected series == event series
open_time/close_time aware UTC
close_time > open_time
OHLC finite Decimal and valid geometry
volume >= 0
taker_buy_base optional, >=0 and <= volume
market_as_of = close_time
closed = True
no seconds/ms inference
```

`occurred_at` is operational publication timing only and never becomes market identity.

Support `str`/`bytes` transport fields only at this adapter boundary and normalize deterministically.

---

# 13. Read-only canonical market history repository

Add a decision-owned read-only repository over the existing canonical table:

```text
ingestion.candles
```

Do not write or migrate the ingestion schema.
Do not import `CandleRepository` from ingestion production code.

At minimum support:

```text
fetch_latest_cutoff(MarketSeriesKey)
fetch_bars(MarketSeriesKey, start/end or through+limit)
```

Queries must be deterministic and ordered by canonical candle time.
Return shared `CausalBarView` values / decision market series data, not ingestion domain objects.

Validate DB values using the same UTC/Decimal/geometry rules as stream events.

No ORM. Use existing asyncpg/DB pool conventions directly and keep the repository small.

---

# 14. Minimal decision checkpoint schema

Add one idempotent decision-owned schema/table, approximately:

```text
schema: decision

table: decision.state_checkpoints
```

Required semantic fields:

```text
checkpoint_schema_version = 1
lane_id
effective_lane_revision
feature_plan_fingerprint
data_plan_fingerprint
market_as_of
state_inception_at
state_payload
state_payload_sha256
created_at / updated_at operational timestamp
```

Primary identity must correspond exactly to D6 `LaneExecutionIdentity`.

Store only the latest checkpoint for each exact lane execution identity.

Do not store model decisions/signals in this table.
Do not store PriceRelay state.
Do not create an outbox.

---

# 15. Checkpoint payload semantics

The checkpoint represents the atomic D6 stateful binding batch at one committed/reconstructed cutoff:

```text
binding_id -> committed ModelState
```

The binding key set must exactly match the lane's configured stateful binding IDs.

Checkpoint load must reconstruct `BindingRuntimeState` records as:

```text
health = LIVE
committed_market_as_of = checkpoint.market_as_of
committed_state = decoded state
last_failure_reason = None
```

and install them through the existing D6 state-store invariant (`install_rewarm` or an equally strict existing path).

Do not mutate D6 state internals directly.

---

# 16. Small reversible semantic state codec

D6 `ModelState` supports a deliberately bounded immutable semantic vocabulary.
D9A checkpoints need a reversible durable encoding for exactly that vocabulary.

Implement one small deterministic tagged-JSON codec owned by the decision checkpoint layer.

Support only values already accepted by `freeze_model_state`, including as applicable:

```text
None
bool
int
finite float
finite Decimal
str
bytes
timezone-aware UTC datetime
timedelta
tuple/list semantic sequences
string-keyed mappings
```

Decode then pass through `freeze_model_state` again.

Reject:

```text
custom objects
sets
cyclic values
naive datetimes
non-finite numeric values
non-string mapping keys
unknown tags
```

Canonicalize mapping order and calculate `state_payload_sha256` over canonical encoded bytes.

Do not use pickle, repr, Python hash, or object addresses.

---

# 17. Checkpoint repository idempotency

Provide a small repository such as:

```text
load(identity) -> LaneStateCheckpoint | None
save(checkpoint) -> INSERTED | UPDATED | IDENTICAL | CONFLICT
```

Rules:

```text
exact identity required
newer cutoff may replace older cutoff
same cutoff + identical payload -> idempotent success
same cutoff + different payload -> CONFLICT / fail closed
older cutoff -> reject
payload hash mismatch on load -> corruption / fail closed
```

No retries/backoff framework in D9A.

---

# 18. Capture startup stream tails before reconstruction

For every configured canonical `MarketSeriesKey` required by active decision lanes:

1. derive its canonical ingestion stream key;
2. capture the current stream tail ID and parse the tail event when present;
3. record the tail's canonical market cutoff;
4. then query the canonical DB latest cutoff.

Represent one immutable snapshot, e.g.:

```text
SeriesStartupPosition
  series_key
  stream_key
  captured_tail_id
  captured_tail_market_as_of
  db_latest_market_as_of
  warm_cutoff
```

Rules:

```text
DB latest must not be older than a captured valid stream-tail candle
warm_cutoff = DB latest canonical close when available
stream tail may legitimately lag DB because DB commit precedes outbox publication
```

This deliberate DB-ahead-of-stream case must be tested.

Do not recapture and silently replace the original attach tail after reconstruction; D9B must attach **after the original captured stream IDs** and classify any events already represented by warmup.

---

# 19. Initial InputReadCursor semantics

After successful startup warm/reconstruction, initialize per-stream cursor evidence with:

```text
stream_key = captured canonical stream
latest_stream_id = captured tail ID when present
latest_market_as_of = warm_cutoff represented in the shared BarStore
```

It is acceptable for:

```text
latest_market_as_of > captured_tail_market_as_of
```

when Timescale was ahead of the captured outbox stream tail.

D9B will use both facts:

```text
attach after captured_tail_id
skip/classify incoming event <= warm_cutoff as already represented
append only genuinely newer canonical market state
```

Do not implement that continuous reader in D9A.

---

# 20. Manifest startup authority

Use the existing shared `AssetManifestStore` only for lifecycle availability authority.

At D9A startup, read current ingestion manifests and require:

```text
source == ingestion
manifest symbol == decision manifest_asset
manifest enabled == True
manifest desired_state == LIVE
required lane timeframes are present/live
```

Configured decision graph remains static.
A manifest can activate/deactivate availability; it cannot invent bindings, policies, or timeframes.

D9A does not consume `asset:lifecycle` continuously yet.

Configured-but-not-LIVE assets should produce explicit startup status/evidence and no active lane runtime.

---

# 21. Startup history strategy

Do not load all retained history into the final shared `BarStore`.

The final BarStore remains bounded by existing D3+D4 capacity calculations.

Startup has two distinct history needs:

```text
A. reconstruction history
   enough to execute stateful replay steps causally

B. final live BarStore history
   only the bounded tail required by D3+D4 capacities
```

Keep them separate.

Do not enlarge the steady-state BarStore merely because a stateful model needs a longer startup replay horizon.

---

# 22. Temporary reconstruction stores

Because multiple lanes may require different replay horizons and the final BarStore is intentionally bounded, do not attempt to load a huge history once and then seek backward inside one deque.

A simple acceptable startup approach is:

```text
for each stateful lane:
  build temporary bounded BarStore/FeatureEngine/ModelRuntime
  feed its required canonical history forward in causal order
  build LaneMarketView at each replay trigger
  D6 rewarm publication-suppressed
  retain resulting LaneStateStore

then:
  build final shared per-asset BarStore from only required tail capacities
  instantiate final ModelRuntime with the reconstructed LaneStateStore
```

Do not introduce a generic simulation engine.
Do not duplicate D6 model logic.

If a materially simpler implementation can satisfy the same causal invariants, use it.

---

# 23. Determine lane startup resume cutoff

For each configured live lane, derive the latest causal cutoff that can actually satisfy the D3 market-view contract from captured canonical history.

Use existing:

```text
LaneReadinessEvaluator
DecisionViewBuilder
TimeframeGrid
```

Do not equate "latest DB bar" with "lane ready" without validation.

For projected lanes, the resume cutoff may be a trigger close inside an open decision-timeframe bucket.
At exact decision boundaries, canonical decision HTF presence rules remain unchanged.

A small bounded backward search over available trigger cutoffs is acceptable if the most recent trigger cutoff is not ready.
Do not invent an older HTF substitution.

---

# 24. Stateful startup from checkpoint

For a stateful lane with a matching checkpoint:

```text
checkpoint cutoff = C
resume cutoff = R
```

Require:

```text
C <= R
```

If `C == R`:

```text
install checkpoint state
no replay steps
```

If `C < R`:

```text
first replay step = C + trigger_duration
last replay step = R
all steps contiguous
mode = REPLAY
publication suppressed
```

If any required transition/bar/data is missing, fail lane startup closed.

After successful replay, persist an idempotent newer checkpoint at `R`.

---

# 25. Stateful first startup without checkpoint

For a new exact execution identity:

1. obtain its explicit bounded state initialization requirement;
2. select the latest contiguous trigger-step window ending at lane resume cutoff;
3. ensure enough D4/D3 prehistory is available to build every replay step;
4. the first replay step is the explicit `state_inception_at`;
5. replay all steps in order with D6 `REPLAY` semantics;
6. persist the first checkpoint at the resume cutoff.

If the retained canonical history cannot satisfy the declared initialization requirement:

```text
lane remains WARMING / startup blocked for that lane
```

Do not shorten the model's required horizon silently.

---

# 26. Stateless startup

Stateless lanes require no state checkpoint or model replay.

Build/validate the latest ready causal view and establish a baseline watermark at the startup resume cutoff.

No historical decision should be emitted during startup.

---

# 27. Startup LaneCommitWatermark semantics

Process restart deliberately suppresses stale historical decisions.

After successful startup reconstruction/warmup to resume cutoff `R`, initialize:

```text
LaneCommitWatermark(
  lane_id=...,
  latest_market_as_of=R,
  last_disposition=None,
)
```

`last_disposition=None` means:

```text
startup/reconstruction baseline; no claim that R was published or NO_SIGNAL finalized
```

This prevents D9B from evaluating/finalizing an already reconstructed historical cutoff.

Do not fabricate `published` or `no_signal` disposition during startup.

If a lane has no valid resume cutoff, keep its watermark empty.

---

# 28. Startup result contract

Return one immutable startup result with enough evidence for D9B and observability.

Conceptually:

```text
DecisionStartupSnapshot
  configured identities
  active manifest assets
  final per-asset BarStores
  lane runtimes
  lane finalizers / baseline watermarks
  per-stream InputReadCursor
  original captured stream tails
  per-series warm cutoffs
  checkpoint load/save evidence
  lane startup status
  reconstruction/inception evidence
```

Do not put live tasks, Redis clients, DB pools, or mutable service objects into the immutable evidence contract unless they are deliberately kept in a separate runtime owner.

Keep evidence bounded.

---

# 29. Startup failure isolation

Do not make one lane's model reconstruction failure roll back canonical input/history for every unrelated lane.

Freeze simple behavior:

```text
invalid global config / canonical market contract / DB corruption
  -> fail application startup

asset manifest not LIVE
  -> asset inactive, not global failure

one lane insufficient warmup/reconstruction history
  -> lane WARMING/BLOCKED with evidence

one lane checkpoint identity/corruption error
  -> lane INVALID/BLOCKED; do not use state

shared canonical series malformed/conflicting
  -> affected asset/series fail closed
```

For D9A integration tests, make the distinction explicit.

Do not add retries/backoff yet.

---

# 30. No publication during startup

Hard scan/test requirement:

D9A startup/reconstruction production code must contain no calls to:

```text
xadd signals:*
build/finalize publication ACK workflow
TradeSignal publication
price_update publication
risk/execution publication
```

D6 rewarm is REPLAY-only and publication-suppressed.

D8 finalization should not be invoked for historical startup cutoffs.

---

# 31. No continuous stream consumer yet

D9A may call bounded Valkey read operations needed to capture startup state, such as:

```text
XREVRANGE/XRANGE/XINFO equivalents
manifest HGET/HSCAN helpers already owned by AssetManifestStore
```

D9A must not run:

```text
while True XREAD
XREADGROUP
XAUTOCLAIM
consumer groups
PEL reclaim
background stream reader task
```

D9B will implement direct-cursor XREAD using D9A's captured tail/cursor evidence.

The selected restart model remains reconstruction + direct cursor, not persistent PEL replay.

---

# 32. Real infrastructure tests

D9A is an infrastructure phase. Add deterministic local integration coverage against real test Timescale/Valkey when available in the repository harness.

Do not call Binance or any external market provider.

At minimum prove with real local infrastructure:

## 32.1 Canonical transport parity

Construct/publish a real ingestion `candle.committed` fixture using the existing ingestion contract in test code and prove the D9 consumer parses the exact same fields/identity.

## 32.2 DB-ahead-of-stream startup race

Seed:

```text
stream tail through cutoff T
Timescale canonical candles through cutoff T+2
```

Capture tail first, then warm DB.

Prove:

```text
captured stream tail remains T's stream ID
warm cutoff becomes T+2
final BarStore contains through T+2
InputReadCursor records original tail ID + accepted cutoff T+2
```

No publication occurs.

## 32.3 First SR startup

Seed enough canonical bars for real SR initialization.

No checkpoint exists.

Prove:

```text
bounded initialization horizon selected
SR rewarm uses real D7A plugin
state becomes LIVE at resume cutoff
state_inception_at recorded
startup checkpoint persisted
baseline watermark = resume cutoff / disposition None
no signal entry written
```

## 32.4 Checkpointed SR restart

From the first startup checkpoint:

```text
append more canonical candles
capture new stream tail/DB cutoff
restart coordinator
```

Prove:

```text
checkpoint loaded only for exact LaneExecutionIdentity
first replay step = checkpoint + one trigger
replay contiguous through new resume cutoff
final encoded SR state equals an uninterrupted reference execution
new checkpoint advances
historical publication remains suppressed
```

This exact-state restart parity is mandatory.

## 32.5 Checkpoint identity change

Change one material identity input:

```text
binding config / lane revision / feature fingerprint / data fingerprint
```

Old checkpoint must not be reused.

The new identity uses first-inception semantics.

## 32.6 Checkpoint corruption

Tamper payload/hash or binding key coverage.
Startup must fail that lane closed.

## 32.7 Retention gap after checkpoint

Checkpoint at C, but canonical history starts after `C + trigger_duration`.

Prove startup refuses to bridge the missing state transition.

---

# 33. Unit/adversarial tests

Cover at least:

```text
strict decision config extra keys rejected
manifest_asset / decision_asset identities not conflated
ingestion geometry read from canonical ingestion config only
unknown ingestion instrument/timeframe rejected
static config compiles exact D2 lane spec
runtime plugin reconstruction requirement required for stateful binding
SR initialization requirement deterministic from config
stream parser rejects wrong producer/event/schema
stream parser rejects payload/stream identity mismatch
stream parser rejects future/invalid geometry/naive time
canonical Decimal values preserved
DB row conversion parity with stream conversion
checkpoint semantic codec round trip
checkpoint unsupported semantic state rejected
checkpoint hash tamper rejected
checkpoint same cutoff identical idempotent
checkpoint same cutoff different payload conflict
checkpoint older write rejected
checkpoint stateful binding set exact
startup checkpoint exact identity only
startup baseline watermark disposition is None
no startup call to D8 signal publication/finalization
no consumer group/PEL implementation
```

---

# 34. Preserve D0-D8 behavior

Do not regress or redesign:

```text
D2 static plan identity
D3 market view/readiness geometry
D4 feature fingerprints/capacity isolation
D5 data plan identity/PIT semantics
D6 one-pending state transaction and causal rewarm
D7A SR adapter/state codec/artifact boundedness
D8 final decision identity/publication/finalization semantics
```

The checkpoint identity is D6 `LaneExecutionIdentity`.
Do not create a second lane identity hash.

The startup watermark is a resume gate, not a D8 finalization receipt.

---

# 35. Explicit non-goals

D9A must not implement:

```text
continuous XREAD event loop
consumer groups / PEL
actual signal publication
D8 SignalPublicationAck from real broker
PriceRelay
price_update streams
PriceRelay gap recovery policy
asset:lifecycle continuous consumer
FastAPI routes/app lifespan
runtime controller/supervisor framework
Docker/Compose service
observability exporter/metrics framework
live DataResolver HTTP/scraper adapters
D7B model integration
risk/execution changes
shadow parity
load/resource certification
cutover
legacy signal/strategy retirement
```

Do not add a general workflow, actor, scheduler, repository framework, or service container.

---

# 36. PriceRelay remains intentionally out of D9A

Current risk code treats `price_update:*` as ephemeral heartbeats and intentionally does not drain their PEL after restart.
It uses each update's high/low for SL/TP monitoring.

D0 therefore requires a dedicated downstream compatibility proof before choosing missed-price replay/catch-up/discard behavior.

D9A must not accidentally solve this by assumption.

Carry forward:

```text
D9P / D9 price-relay compatibility gate required before full cutover
```

This does not block D9A startup reconstruction or D9B signal-path live integration.

---

# 37. Validation commands

Use the repository interpreter:

```text
/Users/kajukatli/projects/flipperAgent/.venv/bin/python
```

Run focused D9A tests first.

Then cumulative:

```text
tests/decision
relevant non-research SR suite
commons ConfigManager tests
canonical ingestion publication/domain/storage contract tests affected by cross-contract test only
D8 downstream compatibility subset
```

Run real local infrastructure integration tests if the repository harness provides Timescale/Valkey fixtures.

No external provider/network market calls.

Static:

```text
ruff check
ruff format --check
python -m compileall -q ...
git diff --check
trailing-whitespace scan
AST/import boundary scan
repo-local __pycache__ cleanup
```

Import boundary must prove decision startup/storage/transport code does not import:

```text
apps.signal_app
apps.strategy_app
apps.risk_app
apps.execution_app
apps.ingestion_app domain/services/storage in production
```

Test code may import ingestion event builders to prove external-contract parity.

---

# 38. Two-pass coder self-review

## Pass 1 — correctness

Explicitly verify:

```text
stream tail captured before warmup
DB-ahead-of-stream case correct
canonical market cutoff never wall-clock-derived
checkpoint exact execution identity
checkpoint payload corruption detected
first-deployment inception explicit
checkpointed restart exact SR parity
no missing trigger bridged
final BarStore bounded
startup watermark suppresses stale decisions
no publication during replay
```

## Pass 2 — simplicity/scope

Explicitly verify:

```text
no generic checkpoint framework
one latest checkpoint per identity only
no duplicate ingestion domain model
no app-to-app production import
no consumer groups/PEL
no live reader loop
no XADD
no PriceRelay assumption
no FastAPI/Docker
no D9B/D9C/D9D
no D7B compatibility bridge
```

---

# 39. Coder handoff

Create/update:

```text
plans/coder-to-orchestrator-decision-app-d9a-startup-reconstruction-v1.md
```

Record:

```text
files/symbols changed
exact decision config schema
manifest_asset vs decision_asset mapping
canonical ingestion config fields consumed
stream event consumer contract
Timescale read-only repository queries
checkpoint schema + semantic codec
checkpoint identity/idempotency rules
state initialization requirement mechanism
SR initialization horizon formula + proof
startup tail/cutoff sequence
DB-ahead-of-stream evidence
first SR startup evidence
checkpointed SR restart parity evidence
retention-gap failure evidence
baseline watermark/cursor semantics
focused/unit/integration counts
cumulative compatibility counts
Ruff/format/compile/diff/import evidence
Pass 1 findings
Pass 2 findings
residual risks
D9B and PriceRelay carry-forward
```

Do not claim live stream consumption, actual signal publication, FastAPI runtime, PriceRelay, or soak completion.

Do not start D9B automatically.

Final line exactly:

```text
DECISION_APP_D9A_STARTUP_RECONSTRUCTION_READY_FOR_REVIEW
```
