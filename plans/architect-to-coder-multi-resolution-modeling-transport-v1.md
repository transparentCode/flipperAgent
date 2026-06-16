---
goal: Finalize the architecture for multi-resolution model inputs, 1m-canonical market data, transport/storage boundedness, and 200-300 asset scaling
stage: architect-to-coder
date_created: 2026-06-16
last_updated: 2026-06-16
owner: Quant Architecture
status: Ready
tags: [handoff, architecture, signal-app, strategy-app, valkey, timescale, scaling, multi-timeframe, 1m]
source_agent: Quant Architect
target_agent: Coder Agent
---

# Architect-to-Coder Handoff: Multi-Resolution Modeling + Transport Architecture v1

## 1. Objective

Finalize the long-term architecture for:

- `1m` bars as the canonical market-data foundation
- higher-timeframe models with lower-timeframe awareness
- model integration that scales to `200-300` assets
- bounded hot-path transport using `Valkey`
- durable historical storage using `Timescale`
- six-month historical retention max

This document is the implementation handoff for the next phase of work.

---

## 2. Final Decisions

### Decision A — Keep `1m` bars as the canonical base lane

We do **not** introduce true raw trade-tick modeling now.

Reasons:

- earlier design intent already selected `1m` bars as the lowest canonical lane
- queue growth, fanout, and consumer digestion become materially harder with raw ticks
- for the current strategy scope, `1m` bars are sufficient as a “tick-surrogate”
- the repo already has a validated `1m` ingestion/storage path

**Final rule:**

- canonical live base data = `1m` OHLCV
- higher timeframes are derived from or synchronized with the canonical `1m` lane

### Decision B — Models may declare semantic data requirements, but not transport choices

Models should be free to declare:

- `decision_timeframe`
- `base_timeframe`
- trigger cadence (`every_1m_close`, `on_1h_close`, etc.)
- required context profiles
- warmup requirements
- whether they are stateful or stateless

Models must **not** choose:

- their own websocket or exchange connection
- their own queue topology
- their own direct ingestion path
- their own raw transport format

**Final rule:**

- models own **what information they need**
- infrastructure owns **how it is delivered**

### Decision C — `signal_app` owns the shared semantic feature fabric

`signal_app` remains the single interpretation layer for market data.

It owns:

- canonical `1m` rolling state
- shared raw indicators
- shared engineered features
- shared lower-timeframe context summaries
- higher-timeframe context joins
- normalized publication to downstream consumers

It must **not** become deeply model-specific.

### Decision D — `strategy_app` owns model-local view adaptation and evaluation

`strategy_app` should not consume raw exchange data.

It should own:

- model loading and runtime routing
- model-private view adapters
- final transformation from shared market context to model input
- evaluation
- selection / blending / publication

**Final rule:**

- reusable computations belong upstream in `signal_app`
- model-private transformations belong near the model in `strategy_app`

### Decision E — Do not let each model compute the full feature vector from raw data

This is explicitly rejected as the default architecture.

Why:

- duplicates rolling-state memory
- duplicates compute across models
- makes replay/backfill parity harder
- weakens observability
- increases hot-path queue fanout
- creates inconsistent definitions of “the same” feature

Instead:

- shared semantic context is computed once
- model-local “final view” is computed per model

### Decision F — Persist only canonical market history, not redundant HTF duplicates by default

For durable historical storage, the preferred default is:

- persist canonical `1m` OHLCV
- derive HTF bars from `1m` using Timescale aggregation / continuous aggregates / query-time bucketing

Do not persist every HTF copy unless there is a proven operational reason.

This is the main storage-saving decision for `200-300` assets.

### Decision G — No new hot-path framework is required now

We do **not** introduce Kafka / Redpanda / NATS / Flink / another hot-path bus in this phase.

Current stack is enough if bounded correctly:

- `Valkey` for hot-path transport and ephemeral runtime state
- `Timescale` for durable history, replay, backfill, and aggregates

**Final rule:**

- fix boundedness, retention, compression, and worker fanout first
- only revisit a new event backbone if scale materially exceeds current assumptions

### Decision H — All hot-path queues and stores must be explicitly bounded

This is mandatory.

- Valkey streams are replay buffers, not archives
- Valkey ephemeral state must use TTL where applicable
- Timescale tables must have explicit retention/compression policies
- removed assets must trigger historical purge workflows

---

## 3. Architectural Shape

### 3.1 Layered Design

#### Layer 1 — Transport / ingestion

Owner: `ingestion_app`

Responsibilities:

- fetch canonical market data
- publish `1m` OHLCV
- manage lifecycle / backfill / pause / resume
- write durable market history

#### Layer 2 — Shared semantic context

Owner: `signal_app`

Responsibilities:

- consume canonical `1m` and relevant HTF lanes
- compute reusable shared context
- maintain rolling lower-timeframe windows
- produce normalized context payloads for downstream evaluation

#### Layer 3 — Model evaluation

Owner: `strategy_app`

Responsibilities:

- route models by runtime spec
- adapt shared context into model-local input views
- evaluate models
- select / blend outputs
- publish downstream signals

### 3.2 Contract Direction

Current direction:

- `stream:ohlcv:{asset}:{tf}` -> `features:{asset}:{tf}` -> `signals:{asset}:{tf}`

Target semantic direction:

- canonical `1m` market state
- enriched HTF context snapshot
- strategy evaluation on a normalized market-context contract

### 3.3 Preferred future contract

Current `FeatureVector` remains valid for phased migration.

Long-term target is a richer logical contract, conceptually:

- decision timeframe bar data
- lower timeframe summaries
- cross-asset context
- derivatives context
- freshness / provenance metadata

This can still be transported using the current `FeatureVector` shape initially by adding richer feature namespaces.

---

## 4. Model Runtime Contract

Introduce a model-declared runtime spec (name may vary in implementation).

Recommended fields:

- `decision_timeframe`
- `base_timeframe`
- `trigger_mode`
- `required_context_profiles`
- `required_fields`
- `warmup_bars`
- `stateful`
- `priority_class`

### Example

```yaml
runtime:
  decision_timeframe: "1h"
  base_timeframe: "1m"
  trigger_mode: "on_bar_close"
  required_context_profiles:
    - "ltf_volatility_60m"
    - "ltf_breakout_pressure_15m"
    - "ltf_return_dispersion_30m"
  warmup_bars: 240
  stateful: false
```

This gives the model freedom over semantic requirements without handing it transport control.

---

## 5. Shared Context Policy

### 5.1 What belongs in `signal_app`

Put in `signal_app` when the computation is reusable across more than one model:

- rolling `1m` volatility
- realized range / intrabar spread proxies
- lower-timeframe trend / drift summaries
- microstructure-like summaries from `1m` bars
- cross-asset breadth / dominance / relative performance summaries
- derivatives context (funding, OI, etc.)
- higher-timeframe joins and context snapshots

### 5.2 What belongs in the model layer

Put in `strategy_app` / model adapter when it is model-private:

- feature selection from shared context
- final normalization / clipping
- learned encodings
- model-private composite transforms
- stateful rolling logic unique to one model family

### 5.3 First context profiles to support

Recommended first profiles:

- `ltf_volatility_15m`
- `ltf_volatility_60m`
- `ltf_breakout_pressure_15m`
- `ltf_return_dispersion_30m`
- `ltf_volume_pressure_15m`
- `ltf_regime_alignment_60m`

These should be produced once and reused by multiple HTF models.

---

## 6. Transport and Storage Decisions

### 6.1 Use `Valkey` for hot path only

`Valkey` is for:

- inter-app event transport
- lifecycle / orchestration state
- bounded replay buffers
- dedup keys
- short-lived runtime status
- short-lived job state

`Valkey` is **not** for:

- archival history
- long-lived analytics datasets
- unlimited observability blobs

### 6.2 Use `Timescale` for durable history

`Timescale` is for:

- canonical `1m` OHLCV history
- replay / backfill source
- open interest / funding / index OHLCV / derived persistent datasets
- execution / portfolio / risk analytical tables
- continuous aggregates

### 6.3 Streams are bounded replay buffers

Current repo already bounds several streams. That philosophy is correct and must be enforced consistently.

Recommended production caps for the `200-300` asset target:

| Stream Class | Current | Recommended Target |
|---|---:|---:|
| `features:*` | `10000` | `200-1000` |
| `price_update:*` | `100` | `50-200` |
| `signals:*` | `5000` default | `200-1000` |
| `orders:*` | `5000` | `500-2000` |
| `fills:*` | `5000` | `500-2000` |
| failure streams | `5000` | `500-2000` |

Reason:

- at `300` assets and multiple timeframes, large per-stream caps create avoidable Valkey memory growth

### 6.4 Ephemeral keys require TTL

Use TTL for:

- lifecycle dedup markers
- pending job state
- temporary orchestration state
- last-failure transient keys when feasible

Use non-TTL only when the key is canonical configuration or durable runtime control state.

### 6.5 Canonical historical policy

For market history:

- retain at most `180 days`
- canonical persistence target = `1m` bars
- HTF bars derived from canonical history

This should be the default data-retention stance unless a specific table has a stronger reason to exist longer.

---

## 7. Timescale Retention and Compression Policy

Retention and compression must be explicit for all major tables.

### 7.1 Recommended policy classes

#### Class A — canonical market history

Examples:

- `ohlcv`
- `open_interest`
- funding tables
- index OHLCV tables

Recommended:

- retention: `180 days`
- compression: enable before deletion

#### Class B — raw rebuildable data

Examples:

- `ticks`

Recommended:

- short retention
- current `30 days` on raw ticks is reasonable

#### Class C — derived rebuildable datasets

Examples:

- `market_1m_bars`
- `l2_depth_features`
- future engineered persistence tables if added

Recommended:

- medium retention
- compression enabled

#### Class D — authoritative business records

Examples:

- execution fills
- portfolio trade journal
- risk snapshots

Recommended:

- longest retention in the system
- may exceed `180 days` if business/audit logic needs it

### 7.2 Mandatory gaps to close

Add explicit retention/compression policies for:

- `ohlcv`
- `open_interest`
- funding-rate tables
- `tv_index_ohlcv`
- any other durable market-data hypertables missing policy

### 7.3 Asset removal cleanup

When an asset is removed:

- stop runtime production
- purge Valkey stream tails / runtime keys where appropriate
- schedule Timescale historical purge by `symbol`
- ensure purge respects the configured data retention policy

---

## 8. Scaling Envelope for 200-300 Assets

### 8.1 Historical storage estimate

Assumption:

- `300` assets
- canonical `1m` storage only
- `180` days

Rows:

- `300 * 1440 * 180 = 77.76M` `1m` OHLCV rows

Expected Timescale footprint:

- uncompressed: roughly `20-35 GB`
- compressed: roughly `5-12 GB`

With supporting datasets:

- practical durable-data expectation: `10-25 GB compressed`

### 8.2 Hot-path pressure estimate

The first bottlenecks are expected to be:

1. Valkey memory pressure
2. worker/task fanout
3. only then Timescale disk

### 8.3 Worker fanout warning

The current per-asset/per-pair worker model can become large.

At roughly:

- `300` assets
- `3` publish/eval timeframes

Possible fanout:

- signal workers: ~`900`
- strategy workers: ~`900`
- risk workers/listeners: hundreds more
- execution workers: ~`300`

This is not automatically invalid, but it means:

- queue sizes must stay bounded
- shared feature computation must stay shared
- task creation must remain lightweight

### 8.4 Resource budget recommendation

For the target fleet:

#### Minimum usable

- `8 vCPU`
- `16 GB RAM`
- fast SSD

#### Safer operating point

- `12-16 vCPU`
- `32 GB RAM`
- NVMe SSD

#### If many `1m`-aware models run simultaneously

- `16+ vCPU`
- `32-64 GB RAM`

---

## 9. Do We Need a New Hot-Path Tool or Framework?

### Final answer

**No, not now.**

Current stack is sufficient if we implement the architecture above correctly.

### Why not now

- asset scale is moderate, not extreme
- `1m` bars keep event pressure manageable
- current bottlenecks are architectural boundedness and worker fanout, not lack of a new event bus
- adding Kafka/Redpanda now would increase operational complexity without solving the primary design issues

### Triggers for reconsideration later

Revisit a new event backbone only if one or more become true:

- asset count grows well beyond `300`
- model fleet count grows significantly per asset/timeframe
- multiple independent consumers need deep replay history directly from the bus
- Valkey memory/consumer-group behavior becomes the dominant failure mode even after stream caps are corrected
- multi-tenant or cross-team workload isolation becomes necessary

### What to consider later if needed

- `Redpanda` / `Kafka` for partitioned event replay at larger scale
- only after the current `Valkey + Timescale` architecture has been tightened and proven insufficient

---

## 10. Operational Guardrails

### Mandatory monitoring

Track:

- per-stream `xlen`
- consumer-group lag
- pending entry count
- oldest pending entry age
- per-app processed rate
- per-app error rate
- Timescale table size growth
- chunk compression / retention execution

### Mandatory degrade modes

When lag rises:

- disable comparison/shadow model flows first
- disable optional enrichments before core trading flows
- keep risk/execution highest priority

### Replay boundary

Replay/backfill must come from:

- `Timescale`

not from:

- arbitrarily old Valkey stream tails

### Poison-message handling

For repeated message failures:

- publish failure event
- mark runtime degraded/failed
- avoid infinite silent retries without observability

---

## 11. Implementation Plan

### Phase 1 — contracts

- add model runtime spec / semantic requirement contract
- add namespaces for lower-timeframe shared context

### Phase 2 — signal fabric

- implement rolling `1m` context builders in `signal_app`
- publish enriched HTF feature payloads with lower-timeframe context

### Phase 3 — strategy integration

- add model-local view adapters in `strategy_app`
- route models by semantic runtime spec

### Phase 4 — boundedness hardening

- reduce stream caps to scale-safe values
- add missing TTLs where appropriate
- add missing Timescale retention/compression policies

### Phase 5 — storage cleanup

- implement asset removal purge policy across Valkey and Timescale
- enforce retention by table class

### Phase 6 — scale review

- measure worker/task fanout at higher asset counts
- if needed, redesign worker pooling before considering a new event framework

---

## 12. Explicit Non-Goals

Not part of this phase:

- raw trade-tick live modeling
- replacing `Valkey` immediately
- replacing `Timescale`
- fully redesigning every existing model contract at once
- introducing model-specific transport topologies

---

## 13. Approval Summary

Approved architecture:

- `1m` is the canonical base market-data lane
- models declare semantic requirements, not transport
- `signal_app` owns shared semantic context
- `strategy_app` owns model-local view adaptation and evaluation
- `Valkey` remains the bounded hot path
- `Timescale` remains the durable history/replay layer
- no new hot-path framework is needed now
- retention, compression, stream caps, and purge workflows are mandatory before scale-up

