---
goal: Restructure decision_app into stable package ownership boundaries without changing runtime semantics
stage: coder-to-orchestrator
date_created: 2026-08-15
last_updated: 2026-08-15
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, decision-app, r0, package-structure, mechanical-refactor]
source_base: 97ea09ab347a7b45ba25e3b054db512dc3852bf3
source_worktree: /Users/kajukatli/.devspace/worktrees/flipperAgent-1101a88e
---

# Decision app R0 package structure

## Result

R0 is complete as a mechanical namespace/package refactor. The required
terminal status is:

```text
DECISION_APP_R0_PACKAGE_STRUCTURE_READY_FOR_REVIEW
```

No decision runtime behavior, contract value, configuration value, stream
identity, state format, model behavior, risk/execution behavior, or D10
evidence was changed. No commit, merge, push, branch switch, reset, or restore
was performed.

## Starting state

```text
starting SHA: 97ea09ab347a7b45ba25e3b054db512dc3852bf3
worktree: /Users/kajukatli/.devspace/worktrees/flipperAgent-1101a88e
branch: detached cumulative worktree
baseline: 390 passed
```

The worktree was a fresh isolated checkout. The older
`.worktrees/decision-app-d0` worktree was not removed; its uncommitted
Momentum handoff drafts remain preserved outside this package.

## Completed move map

```text
catalog.py         -> planning/catalog.py
planner.py         -> planning/planner.py
readiness.py       -> planning/readiness.py

contracts.py       -> domain/contracts.py
identity.py        -> domain/identity.py
market_state.py    -> domain/market_state.py
state.py           -> domain/state.py
view.py            -> domain/view.py

features.py        -> features/planning.py
feature_engine.py  -> features/engine.py
real_features.py  -> features/definitions.py
data.py            -> data/resolver.py

model_runtime.py   -> runtime/models.py
runtime_plugins.py -> runtime/plugins.py
finalization.py    -> runtime/finalization.py
policy.py          -> runtime/policy.py
startup.py         -> runtime/startup.py
live_runtime.py    -> runtime/live.py
lifecycle.py       -> runtime/lifecycle.py
service.py         -> runtime/service.py

ingestion_input.py -> transport/ingestion.py
live_input.py      -> transport/live_input.py
signal_transport.py -> transport/signals.py
publication.py     -> transport/publication.py
price_relay.py     -> transport/price_relay.py
```

Six minimal package initializers were added for `domain`, `planning`,
`features`, `data`, `runtime`, and `transport`. Root composition modules,
`api/`, and `storage/` remain in place. No broad re-export facade or
`main.py` was added.

All discovered imports in `src`, `tests`, and `scripts` were updated to the
new canonical paths, including the D10 certification script and path-sensitive
architecture tests. No old flat module files remain under
`src/apps/decision_app/`.

## Scope and preservation checks

The normalized AST comparison covered all 25 moved modules:

```text
moved modules checked: 25
normalized AST mismatches: 0
```

The comparison normalized only moved import module names and import ordering;
the executable module structure and non-import behavior matched the source
modules. The tracked diff was reviewed as import/path migration plus the
corresponding real moves.

Unchanged protected surfaces:

```text
configs/decision/global.yaml
docker-compose.yml
src/libs/models/**
src/apps/signal_app/**
src/apps/strategy_app/**
```

The D10 artifact remains byte-for-byte unchanged. SHA-256 before and after:

```text
artifacts/decision_d10/d10_resource_capacity_certification.json
2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459
```

No Momentum implementation or integration was started. Legacy signal/strategy
retirement remains pending the approved later cutover/dependency-proof stages.

## Validation evidence

Baseline selector, unchanged from the fresh pre-R0 baseline:

```text
tests/decision
tests/risk/test_d9d_price_relay_risk.py
tests/risk/test_risk_worker.py
tests/models/sr/test_import_boundaries.py

390 passed
```

Additional affected compatibility validation:

```text
tests/commons
tests/execution
tests/integration/signals
144 passed

tests/signals
tests/risk
250 passed, 1 pre-existing OpenTelemetry deprecation warning
```

Static and boundary checks:

```text
Ruff check: passed
Ruff format --check: 78 files already formatted
compileall: passed
git diff --check: passed
full-repository Python stale flat-import scan: 0 matches
decision package stale flat files: 0
repo-local __pycache__: 0
repo-local .pyc: 0
```

The stale-import scan excluded only repository tooling/environment paths and
searched all repository Python files for the retired flat Decision module
paths. It did not modify historical plans or unrelated versioned model names.

## Self-review

Pass 1 — behavior/correctness:

- public import targets now resolve through the new package structure;
- planner outputs, fingerprints, feature/data plans, state transactions,
  publication/relay boundaries, and SR adapter behavior retain their existing
  test evidence;
- baseline and affected downstream suites pass;
- D10 evidence bytes and hash are unchanged;
- no configuration, deployment, or legacy-app surface changed.

Pass 2 — architecture/simplicity:

- package boundaries are coarse and ownership-oriented rather than framework-
  like;
- old flat modules were moved rather than retained as compatibility shims;
- no discovery, executor, worker, service, repository, or adapter framework
  was introduced;
- no model semantics or infrastructure was moved into the domain layer;
- no Momentum, Docker, server entrypoint, D11, or signal/strategy retirement
  work was mixed into R0.

## Carry-forward

```text
SIGNAL_APP_RUNTIME_RETIREMENT_PENDING_DECISION_CUTOVER
STRATEGY_APP_RUNTIME_RETIREMENT_PENDING_DECISION_CUTOVER
LEGACY_APP_SOURCE_DELETION_PENDING_ZERO_DEPENDENCY_PROOF
```

The current worktree remains uncommitted and ready for independent review.

DECISION_APP_R0_PACKAGE_STRUCTURE_READY_FOR_REVIEW
