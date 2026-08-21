---
goal: Remediate bounded Decision ingestion-pipeline observability review blockers
stage: architect-to-coder
date_created: 2026-08-21
last_updated: 2026-08-21
owner: quant-orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision, ingestion, observability, remediation]
---

# Decision / Ingestion pipeline observability remediation

## Objective

Remediate only the four blocking findings from the independent orchestrator review of the existing observability implementation in:

`/Users/kajukatli/.devspace/worktrees/flipperAgent-decision-ingestion-pipeline-observability`

Keep the current architecture and implementation direction. This is not a redesign and not a new observability phase.

Use the existing isolated worktree and preserve its current uncommitted implementation. Do not modify primary `main`. Do not commit, merge, fast-forward, or push.

Review source:

`plans/orchestrator-decision-decision-ingestion-pipeline-observability-v1.md`

## Frozen non-goals

Do not:

- add a new service, queue, DB table, exporter, collector, dashboard framework, or tracing contract;
- change canonical candle, outbox, ingestion stream, Decision input, lane, policy, publication, checkpoint, or effect-progress contracts;
- add distributed trace propagation across the durable outbox;
- redesign the Grafana dashboard beyond the bounded fixes below;
- add model/feature-specific metrics;
- alter current Decision asset/lane configuration;
- retire legacy Signal/Strategy alert enums or freshness logic in this package;
- regenerate or mutate any historical D12 artifact;
- fix baseline `httpx2` or unrelated SR/trendline collection issues.

## R1 — Correct Decision alert source identity

Current defect:

`configs/alerts.yaml` specifies `source_app: decision`, but `AlertSourceApp` cannot represent Decision and `_source_app_from_value()` silently returns `SYSTEM`.

Implement the minimum canonical fix:

1. Add a Decision value to `src/apps/alert_app/contracts.py::AlertSourceApp` using the repository's canonical runtime identity (`decision`).
2. Preserve every existing enum value. Do not remove Signal/Strategy values here.
3. Keep the YAML `source_app: decision`.
4. Add deterministic tests proving:
   - `_source_app_from_value("decision")` resolves to Decision;
   - the supported normalized Decision form also resolves to Decision;
   - Decision health breach and recovery events preserve `source_app=decision` rather than `system`.
5. Verify routing still resolves the existing `system_health_breach` policy routes. Do not add a new Decision-specific route policy unless current routing fails.

No DB/schema migration is expected because alert incident `source_app` storage is text.

## R2 — Graduate integrated D12B evidence to historical archive semantics

Current defect:

The first legitimate post-D12 changes modify two D12B-locked paths:

```text
configs/alerts.yaml
src/apps/decision_app/bootstrap.py
```

The historical D12B artifact correctly fails current-source recomputation. Do not waive this and do not regenerate the artifact.

Protected D12B artifact must remain byte-identical:

```text
artifacts/decision_d12/d12b_complete_legacy_retirement_certification.json
SHA-256:        64621d3309240302f9aaef4c17f47bd2df9755904e12d6df8c5b1bb3435b6a74
identity digest: 868b86753806c6c5f84bc806a482681d982ae5e4e1c043bb8d71a4f835242234
evidence digest: d159bdb58b09ba2508eeaee31e9bcf260eb851142fb7618a95378278a3d82f73
source SHA:      ad6873a258a898a55bd148ebecba51857648414a
source locks:    47
stored gates:    62/62
```

Implement the same lifecycle pattern already used for historical D12A:

1. Add immutable D12B archive constants/helper(s) in `tests/combined/d12_harness.py` analogous to `_historical_d12a_archive_status()`.
2. The historical status must verify at least:
   - artifact file SHA exact;
   - stored identity digest exact;
   - stored evidence digest exact;
   - historical source SHA exact;
   - success terminal status exact;
   - stored gate count = 62 and all stored gates true;
   - stored source-lock count = 47.
3. Replace only the test assumption that the integrated historical D12B artifact must still certify today's source tree. The stored historical artifact test should validate immutable archive integrity instead.
4. **Do not weaken or remove**:
   - `source_locks()` current-state behavior;
   - `derive_gates()` current-state recomputation;
   - `stored_artifact_valid()` semantics for a newly built/current artifact;
   - tamper/counterexample tests proving changed deleted paths, routes, references, Compose, and source hashes fail closed;
   - `test_build_artifact_recomputes_final_integrity_contracts()` or equivalent current-state synthetic certification coverage.
5. Add a direct regression proving the historical D12B artifact is accepted as immutable historical evidence even when today's two legitimate locked files differ, while a freshly built artifact still binds current source locks.

This is historical-evidence graduation only. Do not create D12C/D13, do not rewrite D12B evidence, and do not change retirement semantics.

## R3 — Remove generation-ID telemetry scope creep

The approved plan explicitly excluded a generation-ID metric.

Remove completely:

```text
decision.generation.id
Prometheus: decision_generation_id
```

Also remove:

- `_generation_id` observability cache state;
- generation-ID callback/instrument;
- generation-ID dashboard target;
- generation-ID assertions in tests;
- coder handoff claims that generation ID is exported as telemetry.

If `replace_generation()` no longer needs `generation_id`, remove that parameter and simplify callers. Keep generation identity in the existing Decision runtime API only.

Do not replace it with a version/hash/UUID metric.

## R4 — Add deterministic tests for real telemetry hook wiring

The current object-level tests are necessary but insufficient. Add a small number of deterministic tests using existing D9B/D9C fixtures and the existing fake meter pattern.

Prove through actual production hook wiring:

### Live runtime

- one accepted `InputRecordResult` increments `decision.input.records_total` exactly once;
- accepted event timestamps produce one market-latency and one canonical-event-latency observation when available;
- one lane evaluation increments `decision.lane.evaluation_total` exactly once;
- one publication acknowledgement increments `decision.publication.total` exactly once;
- a poll that has no transaction does not fabricate evaluation/publication counts.

### Service

- one bounded market poll records one `decision.poll.duration_ms` sample;
- one successful rebuild records exactly one success count/duration;
- one failed rebuild records exactly one failure count/duration;
- generation replacement through `DecisionService` removes retired lane/input gauge identities and exposes only the newly installed generation.

Prefer extending existing `tests/decision/test_d9b_live_runtime.py` and `tests/decision/test_d9c_service.py` only where their fixtures make the hook assertion natural. Do not introduce a duplicate runtime harness.

### Dashboard contract

Add a durable test (may live in `tests/decision/test_observability.py` or another existing observability/config test file) that parses `pipeline-health.json` and asserts:

- valid JSON;
- no `stream_lag_pending_messages` token;
- no `decision_generation_id` token;
- no hard-coded current production lane IDs (`BTCUSDT:momentum_1h`, `BTCUSDT:momentum_4h`, `ETHUSDT:momentum_4h`) in dashboard JSON;
- dynamic lane/asset/timeframe variables are present;
- Decision lag/latency/state metric queries remain present.

## Preserve current good behavior

Do not regress these already-reviewed properties:

- `DecisionObservability` remains application-owned and optional;
- callbacks read only lock-protected cache plus pure local timeframe arithmetic;
- callbacks perform no DB/Valkey/HTTP/runtime I/O;
- allowed metric labels remain only `lane`, `asset`, `timeframe`, `outcome`, `state`;
- all six exact input dispositions remain covered, including `ALREADY_REPRESENTED`;
- closed-interval lag reuses `TimeframeGrid.expected_closed_cutoff()`;
- current-generation lane/input gauge maps use replace semantics;
- dashboard lane selection remains label-derived, not hard-coded;
- Decision remains direct XREAD with no PEL/consumer-group semantics;
- current Ingestion telemetry is reused unchanged;
- no production Compose service/topology change.

## Validation

Use the primary repository virtualenv from the isolated worktree if the worktree has no `.venv`:

```text
/Users/kajukatli/projects/flipperAgent/.venv/bin/python
```

### Focused

Run at minimum:

```text
pytest -q tests/decision/test_observability.py
pytest -q tests/decision/test_d9b_live_runtime.py
pytest -q tests/decision/test_d9c_service.py
pytest -q tests/decision/test_d9c_api_bootstrap.py
pytest -q tests/decision/test_d12_decision_only_topology.py
pytest -q tests/alerts/test_settings.py tests/alerts/test_reconciler.py
```

The focused suite must prove the Decision alert source mapping and D12 historical graduation explicitly.

### Full/protected compatibility

Run:

```text
pytest -q tests/decision
pytest -q tests/ingestion
pytest -q tests/regression
<protected Momentum + MI0/config slice used in the initial handoff>
pytest -q tests/risk tests/execution
```

`tests/decision` must be fully green. No waiver for the historical D12 artifact is allowed after R2.

For `tests/alerts`, the known full-suite collection error caused by missing `httpx2` may remain only if it still reproduces on unchanged main. Run all non-`test_api.py` alert tests or the relevant settings/reconciler/routing subset so the Decision source fix is fully exercised.

Do not widen into unrelated SR/trendline collection repairs.

### Static/config

```text
ruff check --no-cache <changed Python files>
ruff format --check <changed Python files>
python -m compileall -q src tests
git diff --check
docker compose --env-file /dev/null config --quiet
docker compose --profile prod --env-file /dev/null config --quiet
```

Verify D12B artifact SHA remains exactly `64621d3309240302f9aaef4c17f47bd2df9755904e12d6df8c5b1bb3435b6a74` before and after all validation.

### Fresh real telemetry run

Repeat one fresh disposable nine-service run using only:

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

Requirements:

- dynamic localhost ports;
- isolated project/volumes/network;
- no normal developer `.env`, credentials, or shared runtime state;
- Decision readiness succeeds after startup;
- current three production lanes resolve dynamically from Prometheus labels;
- Decision input/lane/lag/latency/evaluation/publication/rebuild metric queries used by Grafana return successful Prometheus responses where the scenario produces data;
- `decision_generation_id` is absent;
- `stream_lag_pending_messages` is absent;
- resource sample records all nine services; each stays within configured memory limit; aggregate RSS remains below 8 GiB; aggregate CPU remains within 4 cores; OOMKilled false; unexpected restart count zero;
- Grafana dashboard is provisioned and healthy;
- all disposable containers, volumes, and networks are removed afterward.

## Self-review

Pass 1 — correctness:

- Decision alerts preserve Decision identity end-to-end;
- D12B archive is immutable and historical, while current synthetic source-lock checks remain fail-closed;
- every runtime metric hook records once and only once;
- no stale generation gauge identities survive a rebuild;
- dashboard queries match the final exported metric surface.

Pass 2 — scope:

- generation metric fully removed;
- no D12 artifact mutation;
- no new service/storage/trace contract;
- no legacy alert cleanup scope creep;
- no unrelated environment/research fixes;
- final diff remains narrowly attributable to observability + D12 historical graduation + Decision alert identity.

## Coder handoff

Update/create:

`plans/coder-to-orchestrator-decision-ingestion-pipeline-observability-remediation-v1.md`

Report:

- exact files changed;
- alert source identity proof;
- D12B historical archive proof and unchanged artifact SHA;
- final metric list (with generation metric absent);
- exact deterministic hook tests added;
- final dashboard queries/variables;
- all focused/full/protected validation results;
- real nine-service Prometheus/Grafana/resource evidence;
- cleanup evidence;
- unresolved baseline-only blockers, if any.

Do not commit, merge, fast-forward, push, or modify primary main.

If successful, end with exactly:

`DECISION_INGESTION_PIPELINE_OBSERVABILITY_REMEDIATION_READY_FOR_REVIEW`
