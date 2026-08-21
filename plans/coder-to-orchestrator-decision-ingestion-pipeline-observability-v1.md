# Coder-to-orchestrator: Decision ingestion-pipeline observability

## Result

Implemented the approved observability-only package in the isolated worktree:

`/Users/kajukatli/.devspace/worktrees/flipperAgent-decision-ingestion-pipeline-observability`

Baseline and worktree HEAD:

`444c480aa65634fcb6c736dab6c449076a08f871`

The primary checkout remains at the same HEAD and was not modified. No commit,
merge, fast-forward, or push was performed.

## Changed files

- `src/apps/decision_app/observability.py`
- `src/apps/decision_app/bootstrap.py`
- `src/apps/decision_app/runtime/live.py`
- `src/apps/decision_app/runtime/service.py`
- `tests/decision/test_observability.py`
- `configs/observability/grafana/provisioning/dashboards/pipeline-health.json`
- `configs/alerts.yaml`
- `tests/alerts/test_settings.py`
- `docs/observability/ingestion-decision-pipeline.md`

## Implementation evidence

`DecisionObservability` provides bounded OTel gauges, counters, and histograms
for service state, active lanes, input blocking, closed-interval
input and watermark lag, lane state/disposition, all six input dispositions,
input latency, poll duration, lane outcomes, publication outcomes, and rebuilds.

Metric callbacks read only lock-protected in-memory snapshots. Labels are limited
to `lane`, `asset`, `timeframe`, `outcome`, and `state`; event/stream/trace/candle
and generation identifiers are not metric labels. Generation replacement clears
retired input and lane identities before installing the new snapshot.

Runtime hooks record input acceptance immediately after `DirectCursorInput.accept`
returns, lane outcomes at bounded poll return, poll/rebuild timing, and lifecycle
state transitions. Lag uses `TimeframeGrid.expected_closed_cutoff()` and counts
complete closed intervals rather than wall-clock age.

The dashboard is dynamically filtered from Decision metric labels for the current
lanes, includes Decision state/active lanes/blocked inputs, closed-interval and
watermark lag, p50/p95/p99 input latency, evaluation/publication/rebuild panels,
and omits `stream_lag_pending_messages`. PromQL was checked against the live
Prometheus API; 25 expressions returned successful Prometheus responses.

The alert health entry uses Decision `/health/ready` and accepts only HTTP
`ready`, without requiring all lanes to remain LIVE during valid rebuild/recovery
states. The operational documentation describes the canonical candle -> outbox
-> ingestion stream -> DirectCursorInput -> lanes -> watermark/finalization path.

## Focused validation

- Observability, D9A/D9B/D9C, and alert settings: **18 passed**.
- Initial observability/runtime focused slice: **43 passed**.
- Ruff check (`--no-cache`): passed.
- Ruff format check: passed.
- `compileall -q src tests`: passed.
- `git diff --check`: passed.
- Dashboard JSON parsing and forbidden PEL metric scan: passed.

## Real disposable validation

Used a disposable project with only:

`db`, `broker`, `ingestion`, `decision`, `otel-collector`, `tempo`, `loki`,
`prometheus`, and `grafana`.

The stack used dynamic localhost ports, isolated volumes/network, no worktree
`.env`, and a test-only data/config override. Production Compose and production
Decision asset configuration were not changed.

Observed:

- Decision `/health/ready`: HTTP 200, `RUNNING`, generation 1, two configured
  assets, three configured lanes, three LIVE lanes, zero blocked streams.
- Prometheus exported Decision state, active lane count, all
  three lane evaluation outcomes, publication outcome, lane dispositions, input
  dispositions, and poll/latency histograms.
- Grafana health: database `ok`; provisioned dashboard title `Pipeline Health`,
  11 panels; no `stream_lag_pending_messages` token.
- Real Decision startup catch-up evaluated all three lanes: BTC 1h NO_SIGNAL,
  BTC 4h NO_SIGNAL, ETH 4h SIGNAL/PUBLISHED; watermarks reached the seeded
  cutoff and finalization committed.
- Final resource sample: approximately 806.5 MiB aggregate RSS and 0.019 core
  equivalents; all nine services were running, below their configured memory
  limits, `OOMKilled=false`, and restart count zero.
- Decision and ingestion images built successfully.
- Disposable containers, volumes, and network were removed after validation.

## Broader compatibility results

Previously run in this unchanged implementation scope:

- Ingestion: **468 passed, 11 skipped**, two existing warnings.
- Regression: **105 passed**.
- Momentum + MI0/config alignment: **71 passed**.
- Risk + execution: **228 passed**.
- Telemetry bootstrap: **5 passed**.

## Known validation caveats

The full Decision command completed with **487 passed, 1 failed**. The sole
failure is the pre-existing historical D12 stored-artifact recomputation test:

`tests/decision/test_d12_decision_only_topology.py::test_stored_artifact_recomputes_when_present`

The observability bootstrap wiring legitimately changes the current hash of
`src/apps/decision_app/bootstrap.py`, which is frozen in the historical D12
artifact source lock. The historical D12 artifact was not regenerated or
modified. This is a protected historical-evidence reconciliation issue, not a
Decision observability runtime failure.

The full `tests/models` collection remains blocked by six existing unrelated
collection imports in SR/trendline test paths (`conftest`, `test_tracking_contracts`,
and the absent research Binance loader). Alert integration tests requiring the
separate alert API also remain environment-gated; the observability-owned alert
settings test passes. No unrelated test or artifact was changed.

## Self-review

Pass 1, runtime: observability is attached at existing Decision lifecycle and
poll boundaries, no business contract or stream schema changed, callbacks do
not perform I/O, and generation replacement removes retired identities.

Pass 2, architecture: one app-owned observability module was added; no service,
database table, tracing contract, PEL framework, model-specific metric, or
runtime topology was introduced. Dashboard lane selection is label-derived and
not hard-coded.

## Terminal

`DECISION_INGESTION_PIPELINE_OBSERVABILITY_READY_FOR_REVIEW`
