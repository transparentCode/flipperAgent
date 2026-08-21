---
goal: Make Decision bootstrap observability fallback fully non-authoritative
stage: coder-to-orchestrator
status: Ready for review
source_sha: 700dcc72a3b670ef43370052f474705bddb05bf6
---

# Decision observability non-authoritative remediation v2

## Result

Continued in the existing v1 remediation worktree based on
`700dcc72a3b670ef43370052f474705bddb05bf6`. The v2 change is limited to the
remaining bootstrap double-failure path.

When `DecisionObservability` construction fails, the diagnostic warning is now
also best-effort. If both metrics construction and `_LOGGER.warning()` raise,
bootstrap disables observability and continues normal Decision startup. No
authoritative initialization work is inside this nested boundary.

## v2 delta

```text
src/apps/decision_app/bootstrap.py
tests/decision/test_d9c_api_bootstrap.py
```

The regression injects both failures, enters the real application lifespan,
asserts that observability is disabled and the Decision service reaches
`RUNNING`, and verifies owned Valkey/DB cleanup.

The existing construction-failure-only regression remains in place.

## Validation

```text
focused observability/D9B/D9C/D12 tests   72 passed
tests/decision                              500 passed
Ruff check --no-cache                       passed
Ruff format --check                         passed
compileall                                  passed
git diff --check                             passed
D12B artifact SHA                            64621d3309240302f9aaef4c17f47bd2df9755904e12d6df8c5b1bb3435b6a74
```

No metrics, labels, dashboards, alerts, topology, runtime hook semantics,
Decision contracts, or D12B artifacts were changed. No nine-service or
non-Decision compatibility rerun was required by the v2 contract.

## Scope review

- Primary `main` remains unchanged at `700dcc72a3b670ef43370052f474705bddb05bf6`.
- No commit, merge, or push performed.
- No D12B regeneration performed.
- Disposable Python/test caches were removed after validation.

Terminal status:

```text
DECISION_OBSERVABILITY_NONAUTHORITATIVE_REMEDIATION_V2_READY_FOR_REVIEW
```
