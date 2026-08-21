---
goal: Independently review the Decision ingestion-pipeline observability implementation
stage: orchestrator-decision
date_created: 2026-08-21
last_updated: 2026-08-21
owner: quant-orchestrator
status: Needs Revision
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision, ingestion, observability, review]
---

# Orchestrator decision: Decision / Ingestion pipeline observability

## Decision

**REMEDIATE.**

The implementation is directionally correct and stays within the intended architecture: existing OpenTelemetry/Prometheus/Tempo/Loki/Grafana only, one Decision-owned observability module, no new service/storage/stream contract, dynamic Grafana lane selection, and no Decision PEL/XREADGROUP retrofit.

Independent focused validation reproduced **51 passed** across the new observability tests plus D9B/D9C service/runtime/API and alert settings. The coder-reported real nine-service run is plausible and consistent with the code, but final approval is blocked by the findings below.

## Blocking findings

### B1 — Decision health incidents are currently misclassified as SYSTEM

Severity: **blocking functional defect**.

The implementation adds:

```text
configs/alerts.yaml
source_app: decision
```

but `src/apps/alert_app/contracts.py::AlertSourceApp` has no Decision member. The existing fallback in `src/apps/alert_app/runtime/reconciler.py::_source_app_from_value()` returns `AlertSourceApp.SYSTEM` for an unknown source.

Independently reproduced:

```text
ingestion    -> ingestion
decision     -> system
decision_app -> system
risk_app     -> risk_app
```

Therefore a Decision readiness breach would be recorded and displayed as a system incident, not a Decision incident. `tests/alerts/test_settings.py` validates only YAML shape and does not exercise the runtime mapping.

Required remediation:

- add the minimal canonical Decision source to `AlertSourceApp`;
- preserve existing enum values; do not widen into legacy Signal/Strategy alert retirement;
- add a deterministic reconciler/contract test proving both `decision` and the supported normalized form resolve to the Decision source rather than SYSTEM;
- verify health-breach/recovery incident creation preserves `source_app=decision`.

No alert DB schema migration is required: `source_app` is stored as text.

### B2 — D12B stored artifact guard is red and must be graduated to historical evidence, not waived

Severity: **blocking certification/integrity issue**.

Full Decision currently fails only:

```text
tests/decision/test_d12_decision_only_topology.py::test_stored_artifact_recomputes_when_present
```

Independent recomputation shows the exact current drift:

```text
false gates:
  source_locks_exact
  current_source_locks_match
  evidence_digest_integrity

changed D12B-locked paths:
  configs/alerts.yaml
  src/apps/decision_app/bootstrap.py
```

This is expected for the first legitimate post-D12 production change, but it cannot be accepted as a known red test. D12B's fail-closed source locks were intentionally built to detect this exact situation.

The repository already has the correct precedent for an integrated certification becoming historical: `_historical_d12a_archive_status()` verifies immutable artifact SHA/digests/source SHA/status/gate count/source-lock count without pretending the old artifact certifies today's source tree.

Required remediation:

- **do not regenerate or modify** `artifacts/decision_d12/d12b_complete_legacy_retirement_certification.json`;
- preserve its approved SHA-256 exactly:
  `64621d3309240302f9aaef4c17f47bd2df9755904e12d6df8c5b1bb3435b6a74`;
- preserve its identity digest exactly:
  `868b86753806c6c5f84bc806a482681d982ae5e4e1c043bb8d71a4f835242234`;
- preserve its evidence digest exactly:
  `d159bdb58b09ba2508eeaee31e9bcf260eb851142fb7618a95378278a3d82f73`;
- preserve historical source SHA `ad6873a258a898a55bd148ebecba51857648414a`, 47 source locks, 62 stored gates, and success terminal status;
- add the minimal D12B historical-archive helper/test analogous to historical D12A;
- change the stored historical D12B test so it verifies immutable archive integrity instead of requiring historical source locks to match today's repository forever;
- retain the existing synthetic/current-state `build_artifact()`, tamper, and counterexample tests so a newly built D12B artifact still fails closed against current repository drift.

This is a historical-evidence lifecycle correction, not a new D12 certification phase and not permission to weaken source-lock tests.

### B3 — Unapproved generation-ID metric was added

Severity: **blocking scope/overengineering defect**.

The finalized implementation contract explicitly removed a generation-ID metric because generation identity already exists in the Decision runtime API and is not required for pipeline health visualization.

The implementation nevertheless adds:

```text
decision.generation.id
```

and the Grafana overview queries:

```text
decision_generation_id{service_name="decision"}
```

The coder handoff also claims generation-ID telemetry as a feature.

Required remediation:

- remove the generation-ID metric instrument, cached generation state, callback, dashboard target, and unit assertions;
- keep generation identity in `/runtime` only;
- do not replace it with another ID/version label or gauge.

### B4 — Runtime hook wiring lacks deterministic telemetry assertions

Severity: **blocking evidence/test-quality gap**.

The new `tests/decision/test_observability.py` tests the observability object in isolation, but repository search found no Decision tests that instantiate `DecisionService` or `LiveDecisionRuntime` with `DecisionObservability` and assert the new hooks fire exactly once.

The existing D9B/D9C tests pass because the observability dependency is optional, but they do not prove:

- `DirectCursorInput.accept()` result -> one input counter/latency update;
- one lane transaction -> one evaluation/publication counter update;
- one bounded poll -> one poll-duration observation;
- one rebuild success/failure -> one rebuild counter/duration update;
- generation replacement removes retired gauge identities through the real service wiring.

Required remediation:

Add a small number of deterministic integration-level unit tests using the existing D9B/D9C fixtures and an injected fake meter/`DecisionObservability`. Do not create a parallel test harness or broaden production code for testing.

Also add a durable dashboard regression assertion that parses `pipeline-health.json` and proves at minimum:

- no `stream_lag_pending_messages` token;
- no hard-coded production lane IDs;
- no generation-ID metric after B3 remediation;
- dynamic lane/asset/timeframe variables remain present.

## Non-blocking observations

- The timeframe-aware lag implementation correctly reuses `TimeframeGrid.expected_closed_cutoff()` and independently reproduces the intended 4h behavior.
- All six exact `InputDisposition` values are covered, including `ALREADY_REPRESENTED`.
- Generation replacement uses replace semantics for current input/lane gauge maps, avoiding retired identities in new callback snapshots.
- The current dashboard's categorical state/disposition panels are functional but visually simple (value `1` with state/outcome encoded in labels). Do not redesign them during remediation unless a real Grafana rendering defect is found.
- Full `tests/alerts` collection is baseline-blocked by the existing missing `httpx2` dependency; the same collection error reproduces on current `main` and is not part of this remediation.
- Broader SR/trendline model collection blockers reported by the coder are outside this package unless a changed file is shown to cause a new error.

## Independent evidence reproduced

```text
Focused observability + D9B/D9C + alert settings: 51 passed
D12B stored artifact current-source test: 1 failed
D12B current drift: configs/alerts.yaml + src/apps/decision_app/bootstrap.py
Alert source mapping: decision -> system (incorrect)
Alert-suite collection: baseline httpx2 error reproduces on main
```

## Approval conditions

Approval requires all four blockers to be resolved, followed by:

1. focused observability/runtime/alert/D12 tests all green;
2. full `tests/decision` green with no D12 exception/waiver;
3. protected ingestion/regression/Momentum/Risk/Execution compatibility green;
4. static checks and dashboard JSON checks green;
5. one fresh disposable nine-service telemetry run proving Prometheus/Grafana data after the final metric surface (with generation metric removed);
6. zero disposable Docker leftovers;
7. no historical D12B artifact mutation;
8. no commit, merge, fast-forward, push, or primary-main mutation.

## Terminal

`DECISION_INGESTION_PIPELINE_OBSERVABILITY_REMEDIATION_REQUIRED`
