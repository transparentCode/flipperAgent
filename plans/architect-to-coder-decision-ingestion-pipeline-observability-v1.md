---
goal: Add bounded Decision observability and certify the ingestion-to-Decision pipeline view
stage: architect-to-coder
date_created: 2026-08-21
last_updated: 2026-08-21
owner: quant-orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision, ingestion, observability]
---

# Decision / Ingestion pipeline observability

## Objective

Implement the missing Decision observability surface using the repository's existing
OpenTelemetry, Prometheus, Tempo, Loki, and Grafana stack. Extend the existing
Pipeline Health dashboard and health-check configuration so the closed-bar
ingestion -> Decision path is inspectable without changing business behavior.

The implementation must be bounded, runtime-state based, and model independent.
It must not become a new service, visualization application, event pipeline, or
tracing system.

## Frozen baseline and workspace

The live primary checkout was verified at:

```text
444c480aa65634fcb6c736dab6c449076a08f871
```

Create a fresh isolated worktree from that exact SHA, for example:

```text
/Users/kajukatli/.devspace/worktrees/flipperAgent-decision-ingestion-pipeline-observability
```

Do not implement in the primary checkout. Do not commit, merge, fast-forward, or
push. Do not alter unrelated local state.

## Existing anchors to preserve

The implementation must follow these existing repository contracts rather than
introducing parallel ones:

- `src/apps/ingestion_app/observability.py` — bounded in-memory state and
  OpenTelemetry instruments.
- `src/apps/ingestion_app/bootstrap.py` — application-owned observability wiring.
- `src/apps/decision_app/runtime/service.py` — cached
  `DecisionServiceSnapshot`, service transitions, generation/rebuild lifecycle,
  and the two long-lived service tasks.
- `src/apps/decision_app/runtime/live.py` — bounded `poll_once()` result,
  `InputRecordResult`, `LanePollResult`, and the existing lane transaction path.
- `src/apps/decision_app/bootstrap.py` — Decision application composition and
  generation factory.
- `configs/alerts.yaml` — existing HTTP readiness health-check schema.
- `configs/observability/grafana/provisioning/dashboards/pipeline-health.json` —
  existing Pipeline Health dashboard.
- `libs.common.telemetry.bootstrap` — existing OTel initialization and exporter
  lifecycle.

Do not change ingestion contracts, canonical candle schemas, outbox schemas,
Valkey stream formats, Decision input/lane/model contracts, or Decision business
classification/finalization/publication behavior.

## Scope

### 1. Decision observability surface

Add:

```text
src/apps/decision_app/observability.py
```

Create one small application-owned `DecisionObservability` object. It should
follow the IngestionObservability pattern and accept an optional injected OTel
meter plus `now_fn` for deterministic tests. Give it the existing
`TimeframeGrid` needed for pure lag arithmetic. Use a bounded lock-protected
in-memory cache for all observable gauge state. Metric callbacks may read only
that cache plus local `now_fn`/`TimeframeGrid` arithmetic; they may not query any
runtime/service/external resource.

The object must provide explicit update/record methods for the existing runtime
boundaries. It must not discover runtime state by querying Postgres, Valkey,
HTTP, or any other network resource from a metric callback.

Use stable `decision.*` instrument names. OTel's Prometheus exporter will expose
the corresponding normalized names used by Grafana. Keep the following semantic
surface:

Gauges, derived from current cached runtime state:

- `decision.service.state` — current exact `DecisionService` state;
- `decision.active_lane_count` — current installed live-lane count;
- `decision.blocked_input_count` — current blocked canonical input count;
- `decision.input.blocked` — per current Decision input, `0/1`;
- `decision.input.closed_interval_lag` — per current Decision input;
- `decision.lane.state` — exact current `LiveLaneStatus`;
- `decision.lane.watermark_closed_interval_lag` — per current lane;
- `decision.lane.last_disposition` — current committed watermark disposition when one exists.

Counters/histograms, recorded at existing hot-path boundaries:

- `decision.input.records_total` for every exact `InputDisposition`:
  `INSERTED`, `DUPLICATE`, `ALREADY_REPRESENTED`,
  `RECONSTRUCTION_REQUIRED`, `CONFLICT`, and `MALFORMED`;
- `decision.input.market_latency_ms` from canonical bar close to Decision input
  acceptance;
- `decision.input.canonical_event_latency_ms` from the outbox event's
  `occurred_at` timestamp to Decision input acceptance.  This timestamp is created
  immediately before the atomic candle/outbox commit and must not be described as
  an exact post-commit or broker-publish timestamp;
- `decision.poll.duration_ms` for one bounded Decision market poll;
- `decision.lane.evaluation_total` for `SIGNAL`, `NO_SIGNAL`, `BLOCKED`, and
  `INVALID` policy results;
- `decision.publication.total` for the existing publication acknowledgement outcomes;
- `decision.rebuild.total` and `decision.rebuild.duration_ms` for generation rebuilds.

Do not create a generation-ID metric: generation identity already exists in the
runtime API and is not required for pipeline health visualization.

Do not add a metric for every event or every stream transport ID. A metric value
may contain a timestamp-derived lag, but timestamps must never be labels.

### 2. Label discipline

Application metric attributes may use only:

```text
lane
asset
timeframe
outcome
state
```

Do not use `stream_id`, `event_id`, `trace_id`, `timestamp`, `candle_id`,
generation UUIDs, reasons, raw stream keys, or arbitrary model/config values as
labels. The service name remains an OTel resource attribute, not an ad-hoc
per-event label.

Use the existing canonical lane/asset/timeframe identity to populate labels.
Do not parse or expose transport identity as a label merely to obtain a route.

Preserve and expose the existing exact `LiveLaneStatus` values. Do not invent an
observability-only lane-state mapping. In particular, keep
`RECONSTRUCTION_REQUIRED` visible as `RECONSTRUCTION_REQUIRED`; Grafana may assign
presentation colors, but telemetry must not rename the domain state.

### 3. Runtime wiring

Wire one `DecisionObservability` instance through the existing application
composition, `DecisionService`, and every fresh `LiveDecisionRuntime` generation,
including rebuilds, without creating another task or coordinator. Prefer the
smallest existing boundaries:

- service start, pause, resume, reconnect, rebuild success/failure, and stop;
- generation install/replacement to seed or atomically replace current input/lane
  gauge state from the already-built startup/runtime state;
- `DecisionService` around `poll_once()` for bounded poll duration and stable
  service-state refresh;
- `LiveDecisionRuntime` immediately after each `DirectCursorInput.accept()` result
  for the six exact input outcomes and accurate event/market latency timestamps;
- each existing lane policy/publication result for evaluation/publication counters;
- the existing rebuild boundary for rebuild count/duration.

Current-generation gauge maps must use **replace**, not append, semantics. After a
lifecycle/config rebuild removes an input or lane, that retired input/lane must no
longer be emitted by observable gauges. Counters/histograms remain cumulative for
the process lifetime.

Keep the optional observability dependency non-authoritative so existing unit
fixtures and runtime contracts remain valid. Do not make metrics export or a
collector outage affect a Decision transaction.

Closed-interval lag semantics are strict and timeframe-aware:

1. Reuse `TimeframeGrid.expected_closed_cutoff(timeframe, now)`; do not implement a
   second alignment/calendar function.
2. Input lag is the number of complete timeframe intervals between that expected
   closed cutoff and the input cursor's latest accepted `market_as_of`.
3. Lane watermark lag is the number of complete lane-decision-timeframe intervals
   between that expected closed cutoff and the lane's latest committed effect
   watermark.
4. A healthy 4h lane at 03:45 with a 00:00 closed-bar watermark therefore reports
   `0`, not `3.75 hours` stale.
5. Values must be non-negative. A series/lane with no cutoff may omit the observation
   rather than inventing zero.

Lag callbacks may perform only pure local arithmetic over cached cutoffs,
`TimeframeGrid`, and an injected/local `now_fn`. They must never call `snapshot()`, a
repository, Valkey, HTTP, or any service method that can perform I/O. This allows lag
to increase while an input is stalled without adding a background task.

### 4. Dashboard

Modify only the existing:

```text
configs/observability/grafana/provisioning/dashboards/pipeline-health.json
```

Keep the dashboard titled `Pipeline Health`, but replace the generic consumer
group message view with a closed-bar Ingestion -> Decision view.

Required dashboard sections/panels:

Overview:

- ingestion runtime state;
- ingestion websocket state;
- ingestion outbox pending;
- ingestion publication health;
- Decision service state;
- active Decision lane count;
- blocked Decision input count.

Decision-bound data path:

Do **not** hard-code the current asset/lane universe into dashboard JSON. Populate
panels/variables from the emitted stable `lane`, `asset`, and `timeframe` labels so a
future config-only lane change does not require a dashboard code change. In the
current certified production config, the real run must resolve exactly:

```text
BTCUSDT:momentum_1h
BTCUSDT:momentum_4h
ETHUSDT:momentum_4h
```

Show for the currently emitted Decision-bound inputs/lanes:

- closed interval lag;
- lane watermark closed-interval lag;
- exact lane state;
- current committed last disposition when present.

Latency:

- p50, p95, and p99 for market close -> Decision input acceptance;
- p50, p95, and p99 for canonical outbox-event creation -> Decision input acceptance.

The primary steady-state latency panels should filter to `outcome="INSERTED"` so
restart/backlog `ALREADY_REPRESENTED` observations do not silently redefine normal
live latency. Outcome counts remain visible separately.

Remove the `stream_lag_pending_messages` panel and every query depending on
consumer-group pending/PEL semantics. Decision uses direct XREAD and must not be
represented as a consumer-group lag metric.

Existing useful Tempo/Loki panels may remain if they do not contradict the new
closed-bar semantics.

Use valid Prometheus metric names emitted by the OTel exporter and parse the
dashboard as JSON in tests. Do not add a frontend or a second dashboard system.

### 5. Health integration

Add one Decision readiness check to `configs/alerts.yaml` using the existing
`health_checks` schema:

```text
source_app: decision
url: http://decision:8004/health/ready
healthy_statuses: [ready]
```

For the alert reconciler, healthy means a successful readiness response whose
payload status is exactly `ready`. A `degraded` Decision response remains an
intentional HTTP-operational state but is alert-worthy. Do not change the
Decision readiness algorithm or require all lanes to be `LIVE`; existing
startup/recovery/rebuild/degraded semantics remain owned by Decision.

Do not add a new health service or modify the Decision readiness algorithm.

### 6. Documentation

Add:

```text
docs/observability/ingestion-decision-pipeline.md
```

Document this path:

```text
Timescale canonical candles
        ↓
ingestion.outbox
        ↓
Valkey ingestion streams
        ↓
Decision DirectCursorInput
        ↓
Decision lanes
        ↓
watermarks/finalization
```

Explain:

- the difference between canonical event time, market close, and observation
  time;
- closed-bar input interval lag;
- lane effect watermark lag;
- why Decision does not use consumer lag or PEL metrics;
- the bounded labels and why transport/event IDs are intentionally absent;
- what HTTP readiness means during startup/recovery/rebuild.

## Non-goals and forbidden changes

Do not:

- create React, Streamlit, Dash, or another visualization application;
- create a new service, database table, queue, outbox, or event pipeline;
- modify candle, outbox, Valkey, Decision input, lane, model, policy, or
  finalization contracts;
- add per-event tracing or trace/event IDs to metrics;
- persist W3C trace context in the canonical candle/outbox contract or add
  `_traceparent`/`_tracestate` fields to the ingestion-to-Decision stream in this
  phase; durable outbox tracing is explicitly deferred;
- redesign OTel, Prometheus, Tempo, Loki, or Grafana infrastructure;
- add Kafka-like consumer groups, PEL, XREADGROUP, or consumer-lag semantics to
  Decision;
- add model-specific observability or model/config labels;
- change root production Compose services or ports unless a current validation
  proves an existing exporter wiring defect; stop and report such a defect rather
  than widening this package;
- change production Decision asset semantics.

## Expected file scope

Expected production/config/documentation changes:

```text
src/apps/decision_app/observability.py                  # new
src/apps/decision_app/bootstrap.py                      # wiring only
src/apps/decision_app/runtime/live.py                   # metric hooks only
src/apps/decision_app/runtime/service.py                # metric hooks only
configs/alerts.yaml                                     # Decision readiness check
configs/observability/grafana/provisioning/dashboards/pipeline-health.json
docs/observability/ingestion-decision-pipeline.md       # new
```

Expected test additions/updates:

```text
tests/decision/test_observability.py                    # new or equivalent
tests/decision/test_d9c_service.py                      # only if wiring needs coverage
tests/decision/test_d9b_live_runtime.py                 # only if hot-path hooks need coverage
tests/combined/integration/*observability*              # disposable real path,
                                                         # reuse an existing fixture where possible
```

Do not add a duplicate observability stack or a production Compose service. If an
existing test fixture can exercise the real path, reuse it; otherwise add only a
minimal test-only fixture and keep it disposable.

## Acceptance criteria

1. `DecisionObservability` exports the required bounded gauges, counters, and
   histograms using the exact semantics/names above.
2. Gauge callbacks use only cached state plus pure local `now_fn`/
   `TimeframeGrid.expected_closed_cutoff()` arithmetic and perform no DB, Valkey,
   HTTP, network, or runtime/service queries.
3. All metric attributes are within the approved label set.
4. No metric cardinality depends on stream IDs, event IDs, timestamps, candle
   IDs, trace IDs, UUIDs, or arbitrary model/config values.
5. Existing Decision state, poll, lane, publication, rebuild, and readiness
   behavior remains unchanged apart from metric side effects.
6. Dashboard JSON is valid, contains the required Ingestion/Decision/latency
   panels, derives lane/input rows from metric labels rather than a duplicated route
   list, resolves the three current production lanes in the real run, and contains
   no `stream_lag_pending_messages` query/panel.
7. `configs/alerts.yaml` contains the Decision HTTP readiness check with
   `healthy_statuses: [ready]`.
8. Documentation accurately describes closed-bar lag and direct-XREAD semantics.
9. Unit tests prove instrument creation, state updates, all six input dispositions,
   latency recording, exact-boundary closed-interval lag, stalled-lag growth from
   local time arithmetic, callback no-I/O behavior, label/cardinality rules, and
   removal of stale input/lane gauge series after generation replacement.
10. One disposable real run proves:
    - ingestion canonical events for the current Decision-bound routes reach the
      durable outbox and canonical ingestion streams;
    - Decision consumes them and advances input cursors/lane watermarks;
    - Decision metrics are exported through the real OTel Collector -> Prometheus
      path;
    - relevant Prometheus queries return the current three production lanes and
      non-empty latency/state data;
    - Grafana dashboard JSON/provisioning parses and its PromQL targets resolve;
    - the exact test topology is resource sampled in steady flow, with every
      container below its configured memory limit, aggregate RSS below the existing
      8 GiB system target, aggregate CPU within 4 cores, no OOM kill, and no
      unexpected restart;
    - no Docker resources remain afterward.

## Validation

Run focused tests first, then the complete required suites from the fresh
worktree:

```text
pytest -q tests/decision/test_observability.py
pytest -q tests/decision
pytest -q tests/ingestion
pytest -q tests/alerts
pytest -q tests/commons/test_telemetry_bootstrap.py
pytest -q tests/regression tests/models/momentum
pytest -q tests/risk tests/execution tests/test_config_alignment.py tests/models/test_import_isolation_mi0.py
```

If an unrelated pre-existing environment/research collection issue appears outside
these protected scopes, record it separately and do not widen this observability
package to repair it.

Run the real disposable observability path with isolated project name, dynamic
ports, and disposable DB/Valkey state. The intended measured topology is exactly
the Ingestion -> Decision path plus observability backend:

```text
db
broker
ingestion
decision
otel-collector
tempo
loki
prometheus
grafana
```

Use the existing OTel/Prometheus/Grafana configuration via the current `prod`
profile and test-only isolation/overrides where required; do not start unrelated
Risk/Execution/Portfolio/Scraper services merely to populate this certification.
Do not use normal developer volumes, credentials, or shared signal state. Verify
metrics through the real export path, not only by inspecting an in-process fake
meter.

Validate infrastructure/configuration:

```text
docker compose --env-file /dev/null config --quiet
docker compose --profile prod --env-file /dev/null config --quiet
Grafana provisioning/dashboard JSON parse
PromQL target/query validation against the disposable run
```

Run static checks:

```text
ruff check --no-cache <changed Python files>
ruff format --check <changed Python files>
python -m compileall -q src tests
git diff --check
```

Clean disposable containers, volumes, networks, temporary credentials, and
repository caches after the real run. Confirm no production contract/config
files outside the approved scope changed.

## Self-review

Pass 1 — observability correctness:

- metrics reflect cached runtime facts;
- closed-bar lag uses the correct causal cutoff;
- input/lane/publication/rebuild outcomes are recorded once at their existing
  boundaries;
- direct XREAD is not represented as consumer-group lag;
- real exporter and dashboard queries resolve.

Pass 2 — architecture and safety:

- no business logic or contract changes;
- no I/O in callbacks;
- no forbidden labels or unbounded maps;
- no new service, task, queue, database table, or tracing framework;
- existing Ingestion observability patterns are reused;
- production Compose and Decision semantics remain unchanged.

## Coder handoff

Create:

```text
plans/coder-to-orchestrator-decision-ingestion-pipeline-observability-v1.md
```

Report exact files changed, metric names/labels, runtime hook points, dashboard
queries, alert configuration, real disposable evidence, all test/static results,
cleanup evidence, and unresolved risks. Do not commit, merge, fast-forward, or
push.

If successful, end the handoff with exactly:

```text
DECISION_INGESTION_PIPELINE_OBSERVABILITY_READY_FOR_REVIEW
```
