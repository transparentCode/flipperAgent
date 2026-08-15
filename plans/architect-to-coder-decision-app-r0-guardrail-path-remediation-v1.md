---
goal: Restore full decision_app architecture guard coverage after the R0 package moves without changing production code or runtime semantics
stage: architect-to-coder
date_created: 2026-08-15
last_updated: 2026-08-15
owner: quant-orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, r0, remediation, architecture-guardrails]
source_base: 97ea09ab347a7b45ba25e3b054db512dc3852bf3
source_worktree: /Users/kajukatli/.devspace/worktrees/flipperAgent-1101a88e
---

# Decision app R0 guardrail-path remediation

## 1. Review finding

R0 production restructuring is mechanically sound, but independent review found one blocking test-coverage regression in:

`tests/decision/test_architecture_guardrails.py`

The file still identifies protected modules by the pre-R0 flat filenames:

```text
GENERIC_MODULES:
  data.py
  live_runtime.py
  model_runtime.py
  planner.py
  service.py
  startup.py

TypeError/fallback boundary list includes:
  signal_transport.py
```

After R0 the canonical modules are:

```text
data/resolver.py
runtime/live.py
runtime/models.py
planning/planner.py
runtime/service.py
runtime/startup.py
transport/signals.py
```

Because several tests compare only `path.name`, the suite remains green while no longer checking `data/resolver.py`, `runtime/live.py`, `runtime/models.py`, or `transport/signals.py` for all of their intended invariants.

This weakens permanent architecture protection and violates the approved R0 requirement that path-sensitive architecture guards be migrated without weakening their semantic assertions.

Independent manual checks show the current production code is clean; this is a guard-coverage defect, not a production behavior defect.

## 2. Scope

Modify only:

`tests/decision/test_architecture_guardrails.py`

Update the existing coder-to-orchestrator R0 handoff after validation if desired/required.

Do not modify production Decision modules, configs, Docker, Momentum, signal_app, strategy_app, D10 artifact, or other tests unless a directly necessary guard regression is discovered.

## 3. Required remediation

### 3.1 Make protected module identities path-aware

Replace filename-only targeting with canonical paths relative to:

`src/apps/decision_app`

Recommended exact generic-module targets:

```text
data/resolver.py
runtime/live.py
runtime/models.py
planning/planner.py
runtime/service.py
runtime/startup.py
```

Use one small helper to derive a source file's relative POSIX path, for example conceptually:

```text
path.relative_to(SOURCE_ROOT).as_posix()
```

Do not introduce a generic framework.

### 3.2 Restore generic model-boundary guards

The following existing guards must cover all six canonical generic modules above:

```text
test_generic_decision_modules_do_not_import_model_implementation_packages
test_generic_orchestration_has_no_model_specific_branches
```

Do not weaken the forbidden import or `plugin_name` branch semantics.

### 3.3 Restore generation/transport strict-boundary guard

The TypeError-compatibility-fallback portion of:

`test_generation_and_transport_boundaries_do_not_guess_signatures`

must target these canonical relative paths:

```text
runtime/lifecycle.py
transport/live_input.py
runtime/service.py
transport/signals.py
runtime/startup.py
```

The `asyncio.wait_for` periodic-wake prohibition must target exactly:

`runtime/service.py`

The existing global `inspect.signature` / `_maybe_await` scan remains unchanged.

### 3.4 Prevent silent future guard erosion

Add one focused regression asserting every explicitly protected canonical relative path used by the guard sets exists under `SOURCE_ROOT`.

The purpose is to make a future package move fail loudly instead of silently reducing coverage.

Keep this assertion simple and local to the architecture-guard test module.

## 4. Verified current production state

Independent review reproduced:

```text
25 moved production modules checked
non-import AST mismatches: 0
```

Manual checks against the intended new protected modules found:

```text
libs.models imports in canonical generic modules: 0
plugin_name conditional branches in canonical generic modules: 0
inspect.signature / _maybe_await fallback tokens: 0
TypeError compatibility fallback in canonical strict boundaries: 0
```

Therefore do not alter production code to fix this remediation.

## 5. Validation

Run focused first:

```text
pytest -q tests/decision/test_architecture_guardrails.py
```

Then the exact R0 baseline selector:

```text
pytest -q \
  tests/decision \
  tests/risk/test_d9d_price_relay_risk.py \
  tests/risk/test_risk_worker.py \
  tests/models/sr/test_import_boundaries.py
```

Expected baseline count remains:

`390 passed`

Run static checks on the changed test file and current R0 Decision scope:

```text
ruff check tests/decision/test_architecture_guardrails.py
ruff format --check tests/decision/test_architecture_guardrails.py
python -m compileall tests/decision/test_architecture_guardrails.py
git diff --check
```

Reconfirm:

```text
D10 artifact SHA-256 = 2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459
```

Re-run the stale old Decision import scan if the remediation touches any import string.

Clean repo-local Python caches created by validation.

## 6. Non-goals

Do not:

- change any R0 production move;
- redesign package layering;
- move `domain/view.py` or other modules;
- alter runtime behavior;
- add compatibility shims;
- add `main.py`;
- integrate Momentum;
- edit Docker/Compose;
- retire signal_app or strategy_app;
- regenerate D10 evidence;
- start D11.

Package dependency-layer hardening beyond the approved mechanical R0 move remains separate from this one blocking guard-coverage repair.

## 7. Acceptance criteria

Ready for re-review only when:

```text
all explicit guard targets use canonical relative paths
all protected target paths are asserted to exist
generic model-import guard covers all six canonical generic modules
generic plugin-name branch guard covers all six canonical generic modules
strict TypeError fallback guard covers transport/signals.py and all other canonical boundaries
focused architecture guard test passes
390-test R0 baseline remains green
no production file changed by remediation
D10 artifact hash unchanged
static checks green
```

## 8. Terminal status

If complete, stop with:

`DECISION_APP_R0_GUARDRAIL_PATH_REMEDIATION_READY_FOR_REVIEW`

If production changes appear necessary, stop with:

`DECISION_APP_R0_GUARDRAIL_PATH_REMEDIATION_BLOCKED`

and report why instead of broadening scope.
