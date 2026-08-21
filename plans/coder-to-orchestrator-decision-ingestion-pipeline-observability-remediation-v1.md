# Coder-to-orchestrator: Decision observability remediation

## Result

The bounded observability remediation is complete in:

`/Users/kajukatli/.devspace/worktrees/flipperAgent-decision-ingestion-pipeline-observability`

Base/worktree HEAD remains:

`444c480aa65634fcb6c736dab6c449076a08f871`

Primary `main` was not modified. No commit, merge, fast-forward, or push was
performed.

## Changed files

- `configs/alerts.yaml`
- `configs/observability/grafana/provisioning/dashboards/pipeline-health.json`
- `src/apps/alert_app/contracts.py`
- `src/apps/decision_app/bootstrap.py`
- `src/apps/decision_app/observability.py`
- `src/apps/decision_app/runtime/live.py`
- `src/apps/decision_app/runtime/service.py`
- `tests/alerts/test_reconciler.py`
- `tests/alerts/test_settings.py`
- `tests/combined/d12_harness.py`
- `tests/decision/test_d12_decision_only_topology.py`
- `tests/decision/test_d9b_live_runtime.py`
- `tests/decision/test_d9c_service.py`
- `tests/decision/test_observability.py`
- `docs/observability/ingestion-decision-pipeline.md`
- `plans/coder-to-orchestrator-decision-ingestion-pipeline-observability-v1.md`

Temporary `.env` and Compose override files used only for the disposable
infrastructure probe were removed. No historical artifact was regenerated.

## Remediation evidence

### Decision alert identity

`AlertSourceApp.DECISION = "decision"` is now canonical. Both `decision` and
the normalized `decision_app` input resolve to the Decision source identity.
Deterministic breach/recovery tests verify that the existing health policy
routes preserve `source_app=decision` rather than falling back to `system`.

### D12B historical graduation

The D12B artifact remains byte-identical:

`64621d3309240302f9aaef4c17f47bd2df9755904e12d6df8c5b1bb3435b6a74`

The immutable archive check binds its historical source SHA, identity digest,
evidence digest, 47 source locks, 62 stored gates, and successful terminal
status. Current synthetic/current-tree artifact checks remain fail-closed; the
two legitimate current changes to `configs/alerts.yaml` and
`src/apps/decision_app/bootstrap.py` are not waived against the historical
artifact.

### Metric surface

The final Decision instruments are:

- `decision.service.state`
- `decision.active_lane_count`
- `decision.blocked_input_count`
- `decision.input.blocked`
- `decision.input.closed_interval_lag`
- `decision.lane.state`
- `decision.lane.watermark_closed_interval_lag`
- `decision.lane.last_disposition`
- `decision.input.records_total`
- `decision.input.market_latency_ms`
- `decision.input.canonical_event_latency_ms`
- `decision.poll.duration_ms`
- `decision.lane.evaluation_total`
- `decision.publication.total`
- `decision.rebuild.total`
- `decision.rebuild.duration_ms`

Generation-ID telemetry is absent from production observability, dashboard
JSON, and the metric-surface regression. Runtime generation identity remains
available through the existing runtime API. No event, stream, trace, candle,
timestamp, UUID, or generation identifier is used as a metric label.

### Production hook tests

The deterministic D9B/D9C tests now exercise actual hook wiring for:

- one accepted input, market latency, canonical-event latency, lane evaluation,
  and publication acknowledgement;
- an idle poll producing no fabricated lane/publication outcomes;
- one successful poll duration and successful rebuild count/duration;
- one failed rebuild count/duration;
- service-driven generation replacement removing retired lane/input gauge
  identities.

The dashboard regression parses the JSON structurally, requires dynamic
lane/asset/timeframe variables, rejects the legacy
`stream_lag_pending_messages` and `decision_generation_id` surfaces, and
rejects hard-coded current production lane IDs.

## Fresh disposable telemetry run

Project: `flipper-observability-remediation`

Dynamic host ports:

- DB `54902`
- Valkey `54903`
- ingestion `54904`
- Decision `54905`
- OTEL gRPC/HTTP/metrics `54906/54907/54908`
- Grafana `54909`

The disposable topology used the nine requested services:

`db`, `broker`, `ingestion`, `decision`, `otel-collector`, `tempo`, `loki`,
`prometheus`, `grafana`.

Ingestion was started and health-verified in the real stack. For the bounded
deterministic window, its live publisher was stopped before fixture injection
to prevent uncontrolled provider events; the existing ingestion repository,
HTF aggregation, outbox publisher, Valkey streams, and real Decision
container handled the measured path. Ingestion was restarted for the
all-nine-service resource sample. This keeps the probe reproducible without
claiming a provider-driven market feed.

Decision startup evidence:

- `/health/ready` HTTP 200;
- service state `RUNNING`;
- 2 configured assets and 3 configured lanes;
- 3 active `LIVE` lanes;
- 0 blocked streams.

The deterministic closed-bar window produced and exported:

- BTCUSDT/1h: 4 `INSERTED`, 4 `SIGNAL`, 4 `PUBLISHED`;
- BTCUSDT/4h: 1 `INSERTED`, 1 `SIGNAL`, 1 `PUBLISHED`;
- ETHUSDT/4h: 1 `INSERTED`, 1 `SIGNAL`, 1 `PUBLISHED`.

Prometheus API queries succeeded for service state, active lanes, blocked
inputs, input dispositions, evaluation/publication counters, poll count,
market/event latency counts, closed-interval input lag, and lane watermark
lag. The live metric query showed no `decision_generation_id` metric.
Grafana `/api/health` returned database `ok`, version `11.1.0`, and dashboard
search returned the provisioned `Pipeline Health` dashboard.

The all-nine-service resource sample was:

```text
decision        92.66 MiB   0.34% CPU
ingestion      158.10 MiB  34.44% CPU
grafana         60.62 MiB   0.51% CPU
db              62.85 MiB   0.02% CPU
prometheus      35.78 MiB   0.99% CPU
broker          11.20 MiB   1.66% CPU
loki            48.09 MiB   0.31% CPU
otel-collector  42.57 MiB   0.00% CPU
tempo           47.94 MiB   1.06% CPU
```

Aggregate RSS was approximately 559.8 MiB and aggregate sampled CPU was
approximately 0.39 core equivalents. Every service was below its configured
memory limit, `OOMKilled=false`, and restart count was zero.

All project containers, volumes, and networks were removed with
`docker compose ... down -v --remove-orphans`; post-cleanup inventories were
empty.

## Validation

- Focused observability/alert/D9B/D9C/D12 suite: **69 passed**.
- Full `tests/decision`: **492 passed**.
- Ingestion + Regression + Risk + Execution combined slice: **801 passed,
  11 skipped**, 2 existing OTel deprecation warnings.
- Momentum + MI0/config + M3/M4 protected slice: **116 passed**.
- Ruff `check --no-cache`: passed.
- Ruff `format --check`: passed.
- `compileall -q src tests`: passed.
- `git diff --check`: passed.
- Root Compose and profile Compose renders with the documented comment-only
  temporary `.env` neutralization: passed.
- Protected D12B artifact SHA before/after validation: unchanged and exact.

The complete `tests/models` collection remains blocked by the same six
baseline SR/trendline collection imports (`conftest`,
`test_tracking_contracts`, and the absent research Binance loader). The known
full alert API collection issue requiring `httpx2` remains environmental and
unchanged. Neither baseline issue was modified.

## Self-review

Pass 1: alert routing is typed end-to-end; historical D12B evidence is
immutable; current artifact checks remain fail-closed; runtime hooks record at
the existing acceptance/evaluation/publication/rebuild boundaries; callbacks
perform only local cached reads and timeframe arithmetic.

Pass 2: no generation metric, service, storage, tracing contract, model
observability, PEL semantics, or Decision business-contract change was added.
No production asset/config topology was activated by this remediation.

## Terminal

`DECISION_INGESTION_PIPELINE_OBSERVABILITY_REMEDIATION_READY_FOR_REVIEW`
