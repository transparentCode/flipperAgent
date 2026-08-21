---
goal: Make Decision observability provably non-authoritative without changing pipeline semantics
stage: architect-to-coder
date_created: 2026-08-21
last_updated: 2026-08-21
owner: quant-orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision, observability, remediation]
---

# Decision observability non-authoritative remediation

## Objective

Fix the one HIGH defect identified by the independent post-merge audit: synchronous Decision telemetry failures can currently alter authoritative input/evaluation/publication/service behavior.

The remediation must make the entire `DecisionObservability` production integration best-effort while preserving the already-approved metric names, labels, Grafana queries, alert semantics, Decision contracts, and Ingestion -> Decision runtime behavior.

## Baseline

Create a fresh isolated worktree from the **current local `main` HEAD at execution time**. The reviewed production-code state immediately before this handoff was:

```text
df3bfcc87140f507370e57bcd6958c7aa8799b3a
```

Plan-record-only commits after that SHA are acceptable. If any production/config/runtime code has changed beyond the reviewed observability state, stop and report the drift instead of guessing.

Do not work in the primary checkout. Do not merge, push, or modify `origin/main`.

Protected D12B artifact must remain byte-identical:

```text
64621d3309240302f9aaef4c17f47bd2df9755904e12d6df8c5b1bb3435b6a74
```

## Verified failure to eliminate

A fault injected into `DecisionObservability.record_lane_evaluation()` on the real D9B signal path currently produces:

```text
RuntimeError synthetic telemetry failure
signal_entries 0
cursor 3-0
```

The canonical input was accepted and the transport cursor advanced, but the telemetry exception aborted the Decision transaction before signal publication. This is forbidden.

## Required behavior

### 1. Best-effort runtime hooks

Every production call into Decision observability must be exception-isolated so telemetry can never alter authoritative behavior.

At minimum review and protect calls from:

- `src/apps/decision_app/runtime/live.py`
  - input-result recording after `DirectCursorInput.accept()`;
  - lane evaluation recording;
  - publication acknowledgement recording.
- `src/apps/decision_app/runtime/service.py`
  - service/generation state synchronization;
  - poll duration recording, especially the `finally` path;
  - rebuild success/failure recording;
  - generation replacement/clear gauge synchronization.
- `src/apps/decision_app/bootstrap.py`
  - production observability construction/wiring if initialization itself can fail.

Use a small explicit best-effort helper or equally bounded mechanism; do not scatter large try/except blocks or introduce a new service/task/framework.

Telemetry failure may emit a warning log, but:

- must not change Decision service/lane/input state;
- must not change a poll result;
- must not prevent a valid evaluation or publication;
- must not alter checkpoint/effect-progress behavior;
- must not trigger rebuild/error/degraded state by itself;
- must not mask or replace the original authoritative exception;
- must not swallow `asyncio.CancelledError` from authoritative async work (telemetry calls are synchronous today; preserve cancellation semantics if structure changes).

Keep `DecisionObservability` itself strict so direct unit tests can still detect invalid telemetry inputs. The non-authoritative guarantee belongs at the production integration boundary.

### 2. Fault-injection regressions

Add deterministic production-hook tests proving failures are harmless at each class of boundary.

Required counterexamples:

1. **Input metric failure** after `DirectCursorInput.accept()`:
   - authoritative input disposition/cursor/BarStore behavior remains unchanged;
   - valid lane trigger/evaluation still occurs.
2. **Evaluation metric failure**:
   - signal/no-signal processing continues exactly as without telemetry;
   - the reproduced `cursor advanced but no signal` failure is impossible.
3. **Publication metric failure** after a real publication acknowledgement:
   - finalization/checkpoint/effect progress still execute;
   - no lane HALT/ERROR caused by telemetry.
4. **Poll-duration metric failure**:
   - a successful poll remains successful;
   - if the authoritative poll raises, that original exception/state classification is preserved rather than replaced by telemetry failure.
5. **Service/generation sync failure** during start/rebuild/stop:
   - service transitions and generation installation remain authoritative;
   - telemetry failure alone cannot set ERROR/DEGRADED or clear the installed generation.
6. **Observability construction failure**, if the production bootstrap creates it eagerly:
   - Decision application can continue with observability disabled/non-authoritative.

### 3. Publication outcome hardening

Low-cost hardening is allowed in the same package: make `DecisionObservability.record_publication()` accept only the finite production outcomes already enforced by the transport contracts:

```text
PUBLISHED
ALREADY_IDENTICAL
CONFLICT
FAILED
```

Do not add new labels or metric names. Unknown direct telemetry input should remain a strict unit-test failure; production integration must isolate it from the authoritative runtime.

## Explicit non-goals

Do not:

- change direct-XREAD cursor/restart semantics;
- add PEL/XREADGROUP or persistent transport cursors;
- change `DecisionServiceSnapshot.ready` or `/health/ready` degraded semantics;
- change alert `healthy_statuses: [ready]`;
- change canonical candle/outbox/Valkey contracts;
- change model, policy, finalization, checkpoint, or effect-progress semantics;
- change Grafana panels/PromQL unless a metric surface unexpectedly changes (it should not);
- add distributed tracing;
- add another service, task, queue, DB table, or telemetry framework;
- regenerate D12B.

## Expected file scope

Likely production changes only:

```text
src/apps/decision_app/runtime/live.py
src/apps/decision_app/runtime/service.py
src/apps/decision_app/bootstrap.py        # only if needed for construction isolation
src/apps/decision_app/observability.py    # finite publication outcome hardening only
```

Tests should remain focused in existing Decision observability/D9B/D9C suites.

## Acceptance criteria

1. The exact reproduced telemetry-failure counterexample no longer changes the authoritative D9B result.
2. All production observability calls are best-effort/non-authoritative.
3. A telemetry exception cannot mask an authoritative exception.
4. Input cursor advancement, BarStore, lane scheduling, evaluation, publication, finalization, checkpoint, effect progress, and service transitions are identical with healthy vs raising telemetry.
5. Publication outcome cardinality is finite.
6. Metric names, approved labels, dashboard JSON/PromQL, alert identity/readiness semantics, and topology remain unchanged.
7. D12B historical artifact SHA remains exact.
8. No production dependency or topology change.

## Validation

Run focused tests first, including new fault-injection regressions, then:

```text
pytest -q tests/decision/test_observability.py \
  tests/decision/test_d9b_live_runtime.py \
  tests/decision/test_d9c_service.py \
  tests/decision/test_d9c_api_bootstrap.py \
  tests/decision/test_d12_decision_only_topology.py

pytest -q tests/decision
```

Also rerun protected compatibility in proportion to the very small runtime-hook change:

```text
pytest -q tests/ingestion tests/regression tests/risk tests/execution
```

Run:

```text
/Users/kajukatli/.local/bin/ruff check --no-cache <changed Python/test files>
/Users/kajukatli/.local/bin/ruff format --check <changed Python/test files>
.venv/bin/python -m compileall -q src tests
git diff --check
sha256sum artifacts/decision_d12/d12b_complete_legacy_retirement_certification.json
```

A new nine-service real-stack run is **not required** if and only if metric names, labels, exporter wiring, dashboard PromQL, Compose topology, and alert configuration are unchanged. The prior real-stack evidence remains applicable because this remediation only makes telemetry failure handling non-authoritative.

## Self-review

Pass 1 — failure isolation:

- inject telemetry faults at every hook class;
- verify authoritative state/results exactly match no-telemetry behavior;
- verify original exceptions are never masked.

Pass 2 — architecture:

- no catch-all around authoritative work;
- no silent swallowing outside telemetry calls;
- no duplicated state model;
- no new telemetry abstraction beyond the smallest reusable best-effort boundary;
- no readiness/restart redesign.

## Coder handoff

Return:

```text
plans/coder-to-orchestrator-decision-observability-nonauthoritative-remediation-v1.md
```

Report exact hooks protected, fault-injection evidence, test/static results, D12B SHA, and any residual risk. Do not merge or push.

Successful terminal:

`DECISION_OBSERVABILITY_NONAUTHORITATIVE_REMEDIATION_READY_FOR_REVIEW`
