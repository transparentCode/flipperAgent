---
goal: Make Decision bootstrap observability fallback fully non-authoritative
stage: architect-to-coder
date_created: 2026-08-21
last_updated: 2026-08-21
owner: quant-orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision, observability, remediation]
---

# Decision observability non-authoritative remediation v2

## Objective

Fix the one remaining acceptance gap from the v1 remediation review: when `DecisionObservability` construction fails, the fallback warning logger can itself raise and abort Decision startup.

This is a tiny bootstrap-only remediation. Do not reopen the runtime/metrics design.

## Baseline / workspace

Continue in the existing isolated remediation worktree only if it is still based on local main `700dcc72a3b670ef43370052f474705bddb05bf6` and contains only the reviewed v1 remediation diff. Otherwise create a fresh isolated worktree from current local main and reapply the already-reviewed v1 remediation before this patch.

Do not modify primary `main`. Do not commit, merge, or push.

Protected D12B SHA must remain:

`64621d3309240302f9aaef4c17f47bd2df9755904e12d6df8c5b1bb3435b6a74`

## Verified failure

Independent reproduction:

- `DecisionObservability(...)` raises `RuntimeError("metrics unavailable")`;
- `apps.decision_app.bootstrap._LOGGER.warning(...)` raises `RuntimeError("logging unavailable")`;
- application lifespan aborts with `RuntimeError("logging unavailable")`.

The observability fallback must not rely on a logger that can re-authoritize telemetry failure.

## Required change

In `src/apps/decision_app/bootstrap.py`, make the warning emitted after observability-construction failure best-effort as well.

Acceptable shape:

```python
try:
    current_observability = DecisionObservability(...)
except Exception:
    try:
        _LOGGER.warning(..., exc_info=True)
    except Exception:
        pass
    current_observability = None
```

Or reuse an equally small existing best-effort logging helper if one already exists and does not broaden scope.

Do not wrap any authoritative initialization work in the telemetry try/except. Only the observability constructor and its diagnostic warning belong in this failure-isolation boundary.

## Required regression

Extend `tests/decision/test_d9c_api_bootstrap.py` with the exact double-failure counterexample:

1. monkeypatch `DecisionObservability` construction to raise;
2. monkeypatch `_LOGGER.warning` to raise;
3. enter `app.router.lifespan_context(app)`;
4. assert `app.state.decision_observability is None`;
5. assert Decision service reaches `RUNNING`;
6. confirm owned Valkey/DB cleanup still occurs on exit.

Keep the existing construction-failure-only test.

## Non-goals

Do not change:

- `observe_best_effort` runtime semantics;
- input/evaluation/publication hooks;
- service transition hooks;
- publication outcome set;
- metrics, labels, dashboard, PromQL;
- alerts/readiness semantics;
- direct-XREAD/restart behavior;
- Compose/topology;
- D12B artifact or historical constants.

No nine-service rerun is required.

## Validation

Run at minimum:

```text
pytest -q tests/decision/test_d9c_api_bootstrap.py \
  tests/decision/test_observability.py \
  tests/decision/test_d9b_live_runtime.py \
  tests/decision/test_d9c_service.py \
  tests/decision/test_d12_decision_only_topology.py

pytest -q tests/decision
```

Then:

```text
/Users/kajukatli/.local/bin/ruff check --no-cache <changed files>
/Users/kajukatli/.local/bin/ruff format --check <changed files>
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m compileall -q src tests
git diff --check
sha256sum artifacts/decision_d12/d12b_complete_legacy_retirement_certification.json
```

No protected compatibility rerun outside Decision is required if the only additional production change is the bootstrap warning guard.

## Coder handoff

Update/create:

`plans/coder-to-orchestrator-decision-observability-nonauthoritative-remediation-v2.md`

Report exact code/test delta and validation. Do not merge or push.

Successful terminal:

`DECISION_OBSERVABILITY_NONAUTHORITATIVE_REMEDIATION_V2_READY_FOR_REVIEW`
