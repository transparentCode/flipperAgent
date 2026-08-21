---
goal: Review Decision observability non-authoritative remediation v1
stage: orchestrator-decision
date_created: 2026-08-21
last_updated: 2026-08-21
owner: quant-orchestrator
status: Needs Revision
source_agent: quant-orchestrator
target_agent: user
tags: [handoff, quant, decision, observability, review]
---

# Decision observability non-authoritative remediation v1 review

## Decision

REMEDIATE.

The primary runtime remediation is correct: all production Decision observability hooks are now routed through `observe_best_effort`, publication outcomes are finite, authoritative exceptions are preserved, and observability construction failure alone falls back to metrics-disabled startup.

Independent validation reproduced:

- required focused Decision observability/D9B/D9C/D12 set: 71 passed;
- full `tests/decision`: 499 passed;
- Ruff and format: passed;
- `git diff --check`: passed;
- D12B artifact SHA exact: `64621d3309240302f9aaef4c17f47bd2df9755904e12d6df8c5b1bb3435b6a74`;
- dashboard, alert config, and Compose topology unchanged from local main.

## Remaining finding

### MEDIUM / acceptance-blocking — bootstrap telemetry fallback can still become authoritative through its warning logger

File: `src/apps/decision_app/bootstrap.py`, observability-construction fallback around `DecisionObservability(...)`.

Current shape:

```python
try:
    current_observability = DecisionObservability(...)
except Exception:
    _LOGGER.warning(..., exc_info=True)
    current_observability = None
```

Counterexample independently reproduced:

1. `DecisionObservability` construction raises `RuntimeError("metrics unavailable")`.
2. The warning logger also raises `RuntimeError("logging unavailable")`.
3. Decision lifespan startup aborts with `FAILED RuntimeError logging unavailable`.

This matters because logging is part of the same observability failure domain (the application attaches an OTel logging handler), and the approved contract is that telemetry failure must never prevent Decision startup.

All other production observability method calls were scanned and are wrapped by `observe_best_effort`; no second unprotected runtime hook was found.

## Required remediation

Make only the bootstrap warning path best-effort. Do not change Decision runtime logic, metrics, labels, dashboard, alerts, readiness, topology, or D12 evidence.

Add a deterministic regression where both observability construction and `_LOGGER.warning` raise; the application must still enter lifespan with `decision_observability is None` and Decision service RUNNING.

## Residual risk after fix

A persistent metrics failure can generate warning volume from `observe_best_effort`; this is operational hardening only and not an acceptance blocker because exporter/instrument failures are not expected to raise per hot-path operation under the normal OTel SDK.

## Terminal

`DECISION_OBSERVABILITY_NONAUTHORITATIVE_REMEDIATION_V1_NEEDS_FINAL_BOOTSTRAP_GUARD`
