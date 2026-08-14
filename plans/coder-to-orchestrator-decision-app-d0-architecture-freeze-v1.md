---
goal: Freeze the D0 HLD and LLD architecture for the greenfield decision_app
stage: coder-to-orchestrator
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Codex Quant Coder
status: Ready
tags: [quant, decision-app, d0, architecture, contracts]
source_agent: quant-coder
target_agent: quant-orchestrator
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Coder-to-orchestrator handoff — `decision_app` D0 architecture freeze

## Result

This D0 package documents and freezes the greenfield `decision_app` HLD/LLD
without creating runtime code, configuration, Compose services, or downstream
migrations.

## Starting checkout

```text
starting SHA: 4fc0de62515112dc371e08a6cde503746c54f7f7
worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
branch state: detached HEAD from main
initial git status: clean
```

The main checkout was not modified. No commit, merge, push, branch switch,
reset, or restore was performed.

## Files created

```text
docs/architecture/decision_app/README.md
docs/architecture/decision_app/contracts.md
docs/architecture/decision_app/decisions.md
docs/architecture/decision_app/catalog.yaml
docs/architecture/decision_app/overview.d2
docs/architecture/decision_app/io.d2
docs/architecture/decision_app/lifecycle_sequence.d2
docs/architecture/decision_app/overview.svg
docs/architecture/decision_app/io.svg
docs/architecture/decision_app/lifecycle_sequence.svg
plans/coder-to-orchestrator-decision-app-d0-architecture-freeze-v1.md
```

No file under `src/apps/` was added or changed.

## Live repository evidence inspected

The audit covered the current canonical ingestion, signal, strategy, risk,
execution, portfolio, and scraper boundaries, plus shared contracts and
architecture catalogs. Specific evidence included:

```text
src/apps/ingestion_app/domain/candle.py
src/apps/ingestion_app/publication/
src/apps/ingestion_app/storage/
src/apps/signal_app/ohlcv_source.py
src/apps/signal_app/pipeline/features.py
src/apps/signal_app/runtime/worker.py
src/apps/signal_app/runtime/runner.py
src/apps/strategy_app/runtime/
src/apps/strategy_app/publishing/signals.py
src/apps/risk_app/runtime/worker.py
src/apps/execution_app/execution_worker.py
src/apps/scraper_app/core/models.py
src/apps/scraper_app/service/fetch_service.py
src/libs/contracts/signal.py
src/libs/contracts/strategy_model.py
src/libs/contracts/model_runtime.py
src/libs/common/asset_manifest.py
docs/architecture/{ingestion_app,signal_app,strategy_app,alert_app,scraper_app}/
```

The existing system confirms that canonical ingestion owns candle chronology and
history, signal workers prime from durable history before live reads, and risk
consumes signal and independent price streams. The new application is documented
as a target boundary rather than as a compatibility wrapper around the existing
strategy runtime.

## HLD decisions frozen

- One `decision_app` runtime; models are in-process plugins from an explicit
  catalog.
- `ingestion` remains canonical OHLCV and ordinary HTF authority.
- `AssetRuntime` owns asset availability and configured lane activation, but
  lifecycle does not invent model topology.
- Shared bounded causal `BarStore` views are driven by `InputReadCursor` and
  explicit lane cutoffs.
- `InputReadCursor`, per-lane `LaneCommitWatermark`, and independent
  `PriceRelayProgress` are distinct progress contracts; a degraded lane cannot
  block input reading, PriceRelay, or unrelated lanes.
- `PriceRelay` is an independent path and cannot be blocked by model, data, or
  policy failure.
- `FeaturePlan` computes shared features only when model demand and operator
  feature policy both allow them; model-private transforms remain private.
- `DataResolver` accepts semantic requests and owns physical acquisition,
  provenance, resolved capability, and one bounded request phase; `DataPolicy`
  owns physical source routing.
- Model dependencies are static, named, acyclic, and same-lane only in V1.
- `DecisionPolicy` is lane-local and emits zero or one authoritative result per
  market cutoff.
- Risk, sizing, SL/TP, position, and execution authority remain downstream.
- Startup captures the input cursor, stream tails, and DB cutoffs before warmup;
  restart reconstructs and resumes live rather than replaying stale trading
  decisions.
- Stateful plugins return proposed state; publication success (or final no-signal)
  precedes LaneCommitWatermark/state commit; missed required transitions force
  `DEGRADED`/`INVALID` and exact causal rewarm before `LIVE`.
- Stateful V1 bindings use durable replay-safe external inputs only; `LIVE_ONLY`
  capability cannot be essential to reconstruction.
- Binding configuration fingerprints and effective lane/policy revisions are
  included in deterministic binding and decision identities.
- Resource design targets an 8 GiB / 4-core host with shared bounded state and
  bounded CPU/external acquisition concurrency.

## LLD contract decisions frozen

`contracts.md` defines:

```text
DecisionContext
ModelSpec
ResolvedModelBinding
DataRequirement / DataRequest
DataSnapshot
ModelArtifact
ModelOutcome
ModelDecision
DecisionPolicyResult
lane_id / binding_id / decision_id
InputReadCursor / LaneCommitWatermark / PriceRelayProgress
LaneReadiness
PriceRelayPlan
```

Models receive causal context, shared features, external snapshots, upstream
artifacts, and provenance. They do not receive infrastructure clients. Required
data, dependencies, and timeframes must be ready through the same causal
`market_as_of` before evaluation.

Publication identity is deterministic from canonical lane/policy configuration,
binding configuration fingerprints, and canonical market time. An identical retry
is success after lookup; a same-identity/different-payload retry is a fail-closed
conflict. Downstream execution idempotency remains an explicit `idempotency_key`.

## Timestamp audit

The current path was traced as:

```text
ingestion event
  -> signal event decoder
  -> FeaturePipeline.build_payloads
  -> strategy model context / candidate
  -> TradeSignal
  -> risk staleness and risk-profile selection
  -> execution request
  -> PriceUpdate-driven position monitoring
```

Observed current semantics:

- ingestion decodes candle `open_time` and `close_time` as UTC epoch seconds;
- ingestion event `occurred_at` is represented as epoch milliseconds in the
  signal payload's `ingestion_timestamp`;
- `FeaturePipeline.normalize_timestamp_ms()` stores `FeatureVector.timestamp`
  and `PriceUpdate.timestamp` as epoch milliseconds;
- strategy candidates and current `TradeSignal.timestamp` inherit that numeric
  value;
- risk staleness compares the signal timestamp with `time.time()` in seconds;
- execution passes the signal timestamp through to the order request, while fill
  status uses its own runtime time;
- price-monitoring orders use the `PriceUpdate.timestamp` as part of their
  causal/idempotency context.

D0 therefore freezes explicit UTC fields instead of inheriting an ambiguous
numeric convention:

```text
bar_open_at       inclusive candle start
bar_close_at      exclusive candle end
market_as_of      causal cutoff included in the decision
signal_time       market_as_of, never publication wall time
decision_ready_at actual runtime completion time for latency only
event_time        external observation time
available_at      earliest causal availability
fetched_at        acquisition time
```

This is a required downstream adapter/contract-test migration gate for a future
implementation package. D0 makes the inconsistency explicit and does not alter
the current signal, risk, execution, or ingestion code.

## Alternatives rejected or deferred

The decision record covers the required alternatives:

```text
one app vs separate model services
in-process plugins vs model processes
  input-progress/cutoff reconstruction vs PEL decision replay
shared/policy-gated features vs universal feature store
semantic resolver vs direct model I/O
static same-lane dependencies vs general DAG
durable reconstruction vs generic checkpoints
offline training vs live training
explicit catalog vs broad auto-discovery
canonical ingestion HTFs vs local hot-path reaggregation
one authoritative publisher vs competing lanes
```

Future extension points are recorded but are not D0 commitments: a durable
decision journal, versioned checkpoints, incremental features, cross-lane or
cross-asset dependencies, GPU/process isolation, sharding, active/standby, and a
direct risk price feed.

## D0 remediation

The narrow orchestrator review remediation was applied without creating runtime
code, configuration, Compose services, or downstream migrations:

1. `decision_ready_at` was removed from `DecisionContext` and retained only on
   the final policy/output contract; the IO diagram now shows the same boundary.
2. Stateful publication ordering is frozen as policy -> successful idempotent
   publication (or final no-signal) -> proposed-state commit -> affected
   LaneCommitWatermark advance. Publication failure/conflict leaves state and the
   affected lane's `LaneCommitWatermark` unchanged without rolling back input
   progress.
3. Startup and re-warm explicitly replay the causal chain: bars -> shared
   features -> replay-safe external data -> upstream dependencies in topological
   order -> stateful binding, with publication suppressed. Stateful V1 inputs must
   be durable and replay-safe; `LIVE_ONLY` data is prohibited for them.
4. `DataRequirement` now contains semantic demand only. `DataPolicy` and
   `DataSnapshot.resolved_capability` own physical routing and capability
   classification.
5. PIT inequalities explicitly bound represented data and `event_time` by
   `market_as_of`, replay `available_at` by the resolver knowledge cutoff, and
   exclude `fetched_at` as historical-availability evidence.
6. Canonical binding configuration fingerprints and effective lane/policy
   revisions now participate in binding and decision identity.
7. An isolated Valkey proof confirmed ordered explicit timestamp IDs, duplicate
   rejection by raw XADD, idempotent exact-retry classification through lookup,
   deterministic payload conflict, and out-of-order rejection.

The required YAML front matter was also added to this handoff.

## D0 remediation 2

The cross-contract progress correction was applied as documentation only:

1. `InputReadCursor`, per-lane `LaneCommitWatermark`, and `PriceRelayProgress`
   are now separate contracts with separate owners and advancement conditions.
2. Input reading and shared `BarStore` advancement continue when one lane is
   degraded. A failed lane leaves its own state and `LaneCommitWatermark` unchanged but
   cannot roll back the input cursor, block PriceRelay, or block unrelated lanes.
3. The stateful transaction ends with the affected lane's `LaneCommitWatermark` after
   successful publication or final no-signal disposition and proposed-state
   commit; it no longer implies shared input-reader progress is model-owned.
4. PriceRelay continuity gaps remain explicit. No replay/catch-up or discard policy
   was invented; exact missed-price semantics are a downstream risk compatibility
   gate because risk uses price high/low for SL/TP monitoring.
5. The README, contracts, catalog, IO D2, overview D2, lifecycle D2, and rendered
   SVGs now show the independent progress paths and degraded-lane non-blocking
   behavior.
6. Handoff front matter now uses `status: Ready` and declares `source_agent` and
   `target_agent`.

## Validation evidence

```text
D2 source validation (final rerun): 3/3 passed with d2 validate
SVG generation (final rerun): 3/3 rendered with scripts/render_d2.sh
SVG/XML sanity: 3/3 parsed by xmllint and non-empty; Python XML parse also passed
catalog YAML parse: passed with the project Python environment
Markdown/link/path sanity: passed for all D0 relative links
git diff --check: passed; untracked D0 artifact whitespace audit passed
isolated Valkey identity proof: passed (explicit IDs ordered; exact retry
  success after lookup; payload conflict and out-of-order ID fail closed)
independent progress contract review: passed (InputReadCursor, per-lane
  LaneCommitWatermark, and PriceRelayProgress are distinct)
```

The generated SVGs contain the new architecture labels and are included as D0
documentation outputs.

## Two-pass self-review

### Pass 1 — correctness

The specification explicitly checks PIT timing inequalities, separate
availability/fetch times, independent input/lane/price progress, startup
progress markers, multi-timeframe readiness, stream-gap reconstruction, exact stateful
causal rewarm, publication-before-state commit, missed-trigger invalidation,
dependency failure, deterministic output identity, non-blocking PriceRelay, and
risk identity compatibility. Price-gap recovery remains an explicit downstream
risk proof rather than an unverified D0 policy. The timestamp unit mismatch is
recorded as a concrete implementation gate rather than hidden.

Result: no D0 blocking correctness ambiguity remains in the architecture
specification.

### Pass 2 — architecture quality

The documents were reviewed for model-per-process expansion, workflow/DAG creep,
universal feature-store assumptions, recursive model I/O, hot graph mutation,
generic checkpoint machinery, live training, broad discovery, copied histories,
unbounded CPU/scraper concurrency, and unsupported resource assumptions.

Result: the V1 boundary remains one bounded runtime with explicit catalog,
same-lane static dependencies, shared causal state, and no speculative framework.

## Remaining implementation gates

These are D1/D8/D10 implementation checks, not unresolved D0 design questions:

1. Implement and test the explicit UTC serialization adapter at the signal/risk
   boundary; do not reuse the current seconds/milliseconds ambiguity.
2. Exercise stateful causal rewarm and multi-timeframe cutoff handling with
   controlled causal-gap fixtures, implementing the already-proven publication
   lookup/conflict rule.
3. Measure bounded CPU/external concurrency and working-set behavior under the
   8 GiB / 4-core target before selecting final limits.

## Final D0 status

DECISION_APP_D0_ARCHITECTURE_READY_FOR_REVIEW
