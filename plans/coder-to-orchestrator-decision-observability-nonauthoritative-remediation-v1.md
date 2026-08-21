---
goal: Make Decision observability non-authoritative
stage: coder-to-orchestrator
status: Ready for review
source_sha: 700dcc72a3b670ef43370052f474705bddb05bf6
---

# Decision observability non-authoritative remediation

## Result

Implemented the bounded telemetry-authority remediation in a fresh detached
worktree based on `700dcc72a3b670ef43370052f474705bddb05bf6`.

Production Decision observability calls are now best-effort at the integration
boundary. `DecisionObservability` remains strict when called directly. A
telemetry exception cannot abort input acceptance, lane evaluation,
publication/finalization, checkpoint handling, service transitions, generation
replacement, rebuild handling, or poll-result classification. The helper
catches ordinary `Exception` only, so cancellation/control-flow exceptions are
not swallowed; logging failure is also contained.

Bootstrap construction of `DecisionObservability` is isolated and falls back to
observability-disabled operation if instrumentation construction fails.

Publication telemetry accepts only the transport contract outcomes:

```text
PUBLISHED
ALREADY_IDENTICAL
CONFLICT
FAILED
```

## Files changed

```text
src/apps/decision_app/observability.py
src/apps/decision_app/runtime/live.py
src/apps/decision_app/runtime/service.py
src/apps/decision_app/bootstrap.py
tests/decision/test_observability.py
tests/decision/test_d9b_live_runtime.py
tests/decision/test_d9c_service.py
tests/decision/test_d9c_api_bootstrap.py
```

No dashboard, PromQL, alert, topology, Decision contract, model, policy,
finalization, checkpoint, effect-progress, ingestion, or D12B artifact changes
were made.

## Fault-injection coverage

Added deterministic regressions for:

- input-result telemetry failure after acceptance;
- lane-evaluation telemetry failure before publication;
- publication telemetry failure after acknowledgement;
- poll-duration telemetry failure while preserving the original transport
  error classification;
- service state/generation/rebuild telemetry failures during start, reconnect,
  and stop;
- observability construction failure during application lifespan startup;
- strict finite publication-outcome validation.

The authoritative signal-path regressions verify cursor advancement, signal
publication, committed finalization, and the absence of a telemetry-induced
lane failure.

## Validation

```text
focused Decision observability/D9B/D9C tests   56 passed
tests/decision                                  499 passed
tests/ingestion + tests/regression + tests/risk
  + tests/execution                             801 passed, 11 skipped
Ruff check --no-cache                            passed
Ruff format --check                              passed
compileall                                      passed
git diff --check                                 passed
D12B artifact SHA                                64621d3309240302f9aaef4c17f47bd2df9755904e12d6df8c5b1bb3435b6a74
```

The protected compatibility run emitted the two existing OpenTelemetry
`LoggingHandler` deprecation warnings. No new warning or failure was observed.

The required new nine-service run was not repeated because exporter wiring,
metric names/labels, dashboard queries, alerts, and topology are unchanged;
this package only makes telemetry failures non-authoritative.

## Scope review

- No commit, merge, push, or primary-checkout mutation performed.
- No D12B regeneration or modification performed.
- Repository-local Python/test caches were removed from the remediation
  worktree after validation.

Terminal status:

```text
DECISION_OBSERVABILITY_NONAUTHORITATIVE_REMEDIATION_READY_FOR_REVIEW
```
