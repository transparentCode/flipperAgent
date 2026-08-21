---
goal: Approve the completed ingestion-to-Decision observability package after v2 remediation
stage: orchestrator-decision
date_created: 2026-08-21
last_updated: 2026-08-21
owner: quant-orchestrator
status: Approved
source_agent: quant-orchestrator
target_agent: user
tags: [handoff, quant, decision, ingestion, observability, approved]
---

# Decision: ingestion-to-Decision pipeline observability

## Decision

APPROVED.

The bounded observability package and both remediation rounds satisfy the approved contract. No further observability architecture or remediation is required before integration.

## Independently verified evidence

Worktree:

`/Users/kajukatli/.devspace/worktrees/flipperAgent-decision-ingestion-pipeline-observability`

Base/worktree HEAD and current primary `main` remain:

`444c480aa65634fcb6c736dab6c449076a08f871`

No implementation commit, merge, fast-forward, or push has been performed.

### v2 transaction-counting fix

Independent counterexample reproduced the corrected behavior for one `poll_once()` processing two cutoffs for the same lane:

```text
input dispositions: INSERTED, INSERTED
published signal entries: 2
evaluation counter increments after poll: 2
publication counter increments after poll: 2
idle follow-up increments: 0 evaluation, 0 publication
```

Evaluation metrics are now recorded immediately after a successful policy evaluation. Publication metrics are recorded immediately after a valid signal/shadow publication acknowledgement. Final per-lane poll summaries no longer own counter totals, eliminating multi-cutoff undercounting without changing Decision execution semantics.

### Previous remediation blockers

Verified resolved:

- `AlertSourceApp.DECISION = "decision"` is canonical.
- Both `decision` and `decision_app` normalize to the Decision alert source rather than `SYSTEM`.
- Protected D12B artifact remains byte-identical at SHA-256 `64621d3309240302f9aaef4c17f47bd2df9755904e12d6df8c5b1bb3435b6a74`.
- D12B historical archive validation reports all checks true: artifact SHA, identity/evidence digests, historical source SHA, terminal status, 62 stored gates, and 47 source locks.
- No `decision.generation.id` instrument or `decision_generation_id` dashboard metric remains.
- Deterministic D9B/D9C tests exercise production input, latency, evaluation, publication, poll, rebuild success/failure, and generation-replacement hooks.

### Test and static validation

Independent orchestrator runs:

```text
focused remediation suite: 69 passed
full tests/decision:         492 passed
Ruff check:                  passed
Ruff format --check:         passed
compileall:                  passed
git diff --check:            passed
```

No telemetry Docker containers, volumes, or networks remained after the prior disposable certification.

### Real-stack evidence retained

A repeat nine-service run is not required for v2 because v2 only relocates in-process evaluation/publication counter hooks. Metric names, labels, dashboard queries, OTel exporter wiring, service topology, and resource surfaces are unchanged from the fresh disposable nine-service remediation certification.

That prior certification established the real path across:

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

with live Decision metrics visible through Prometheus/Grafana, three active Decision lanes, zero blocked streams, all services below configured memory limits, no OOM kills/restarts, and complete disposable cleanup.

## Final architecture outcome

The implementation remains bounded to the existing observability stack:

```text
Ingestion / Decision
        ↓
OpenTelemetry
        ↓
OTel Collector
   ┌────┼────┐
 Tempo Prometheus Loki
   └────┼────┘
      Grafana
```

No new visualization application, service, storage, queue, tracing contract, consumer-group/PEL semantics, model-specific telemetry, or business-data contract was introduced.

Decision freshness uses timeframe-aware closed-interval lag. Decision direct-XREAD semantics remain intact. Gauge callbacks use cached state/local arithmetic only. Dashboard lane/asset/timeframe selection is metric-label driven rather than hard-coded.

## Residual non-blockers

The previously documented broader SR/trendline model collection imports and alert API `httpx2` environment issue are baseline/environmental and outside this package. They were not introduced or modified by the observability work.

## Next action

The package is ready for controlled integration when the user requests it. Integration should preserve unrelated primary-checkout dirty state and should not push unless explicitly authorized.

DECISION_INGESTION_PIPELINE_OBSERVABILITY_APPROVED
