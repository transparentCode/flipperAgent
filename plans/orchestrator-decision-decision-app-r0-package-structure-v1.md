---
goal: Approve the behavior-preserving decision_app R0 package restructuring after guardrail-path remediation
stage: orchestrator-decision
date_created: 2026-08-15
last_updated: 2026-08-15
owner: quant-orchestrator
status: Approved
source_agent: quant-orchestrator
target_agent: user
tags: [handoff, quant, decision-app, r0, package-structure, approved]
---

# Decision

`DECISION_APP_R0_PACKAGE_STRUCTURE_APPROVED`

R0 is approved after independent review of the package restructuring and the focused architecture-guard remediation.

## Verified scope

- 25 decision_app production modules were moved into the approved `domain`, `planning`, `features`, `data`, `runtime`, and `transport` ownership packages.
- Root `bootstrap.py`, `composition.py`, `settings.py`, `api/**`, and `storage/**` remain composition/application boundaries as planned.
- No compatibility shims remain at the retired flat module paths.
- No `main.py`, Docker/Compose wiring, Momentum implementation/integration, D11 work, or signal_app/strategy_app retirement was introduced.
- Six new package `__init__.py` files are empty; no broad re-export facade was added.

## Independent semantic review

A direct normalized AST comparison of all 25 moved production modules against base `97ea09ab347a7b45ba25e3b054db512dc3852bf3`, removing imports/import-order only, found:

```text
moved modules checked: 25
non-import AST mismatches: 0
```

Root/application files changed only to update canonical import paths.

## Guardrail remediation closure

Initial independent review found that several architecture guards still keyed on retired flat filenames and therefore silently stopped protecting renamed modules.

The remediation now:

- keys protected modules by canonical decision_app-relative paths;
- covers `data/resolver.py`, `runtime/live.py`, `runtime/models.py`, `planning/planner.py`, `runtime/service.py`, and `runtime/startup.py` for generic-runtime guards;
- covers `runtime/lifecycle.py`, `transport/live_input.py`, `runtime/service.py`, `transport/signals.py`, and `runtime/startup.py` for signature/fallback guards;
- adds an explicit assertion that every protected path exists.

Focused guard validation independently reproduced:

```text
9 passed
```

No production file was changed by the remediation.

## Independent validation

R0 acceptance selector after the new guard:

```text
tests/decision
tests/risk/test_d9d_price_relay_risk.py
tests/risk/test_risk_worker.py
tests/models/sr/test_import_boundaries.py

391 passed
```

Broader compatibility:

```text
tests/commons + tests/execution + tests/integration/signals
144 passed

tests/signals + tests/risk
250 passed, 1 existing OpenTelemetry deprecation warning
```

Static checks independently verified:

```text
Ruff: passed
Ruff format check: passed
compileall: passed
git diff --check: passed
exact retired flat-import scan: 0 matches
```

Protected D10 evidence remains byte-for-byte unchanged:

```text
artifacts/decision_d10/d10_resource_capacity_certification.json
SHA-256 2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459
```

## Residual carry-forward

R0 is structural only. The following remain intentionally pending:

```text
MOMENTUM_PLUGIN_INTERFACE_REFACTOR_PENDING
MOMENTUM_DECISION_INTEGRATION_PENDING
FINAL_MODEL_MIX_RESOURCE_RECERTIFICATION_REQUIRED
SIGNAL_APP_RUNTIME_RETIREMENT_PENDING_DECISION_CUTOVER
STRATEGY_APP_RUNTIME_RETIREMENT_PENDING_DECISION_CUTOVER
LEGACY_APP_SOURCE_DELETION_PENDING_ZERO_DEPENDENCY_PROOF
```

The worktree is approved for commit and merge into `main`. Do not start legacy-app deletion as part of the R0 merge.

DECISION_APP_R0_PACKAGE_STRUCTURE_APPROVED
