---
stage: coder-to-orchestrator
status: ready_for_review
date: 2026-08-20
owner: quant-coder
---

# D12B retirement integrity remediation

Completed in the existing isolated worktree:

`/Users/kajukatli/.devspace/worktrees/flipperAgent-decision-d12b-complete-legacy-retirement`

No remediation commit, merge, push, or primary-main mutation was performed.

## Cleanup and Decision seam

Deleted exactly:

- `tests/combined/integration/test_decision_d11a_authority_handoff.py`
- `tests/combined/integration/test_ingestion_decision_c4b_shadow_soak.py`
- `scripts/certify_ingestion_decision_c4b_shadow_soak.py`

Removed from `src/apps/decision_app/runtime/startup.py`:

- `DecisionStartupSnapshot.authority_records`;
- authority-record normalization/freezing and startup wiring;
- `_reconstruct_lane(..., authority_record)` and its always-`None` argument.

Updated the D9C API bootstrap stub accordingly. The retired combined-harness
import scan and Decision authority-seam scan are clean. No live Decision/test
reference remains to `authority_records`, `authority_record`,
`SignalAuthorityStore`, `SignalRouteAuthority`, or `signal:authority:`.

## Explicit D12B source inventory

`D12B_SOURCE_PATHS` is explicit and contains 47 retained source/config/test/
fixture members. The artifact itself and all handoffs are excluded:

```text
configs/alerts.yaml
configs/base.yaml
configs/execution.yaml
configs/models.yaml
configs/risk.yaml
docker-compose.yml
docs/docker_topology.md
docs/ingestion_operations.md
scripts/certify_decision_d12_decision_only_topology.py
scripts/certify_decision_runtime_d10.py
scripts/certify_momentum_features_m3.py
src/apps/api_app/app.py
src/apps/decision_app/bootstrap.py
src/apps/decision_app/runtime/startup.py
src/apps/decision_app/transport/signals.py
src/apps/execution_app/bootstrap.py
src/apps/risk_app/api/app.py
src/apps/risk_app/main.py
src/apps/risk_app/observability/service.py
src/libs/common/config_validator.py
src/libs/common/signal_routes.py
src/libs/features/raw_indicator_pipeline.py
src/libs/optim_utils/scoring_feature_pipeline.py
src/libs/regime/optimization/downstream_backtest.py
tests/combined/d12_harness.py
tests/combined/fixtures/d12/configs/execution.yaml
tests/combined/fixtures/d12/configs/ingestion-decision/assets/BTC.yaml
tests/combined/fixtures/d12/configs/ingestion-decision/assets/ETH.yaml
tests/combined/fixtures/d12/configs/ingestion-decision/global.yaml
tests/combined/fixtures/d12/configs/ingestion-runtime/assets/.keep
tests/combined/fixtures/d12/configs/ingestion-runtime/global.yaml
tests/combined/fixtures/d12/configs/models.yaml
tests/combined/fixtures/d12/configs/risk.yaml
tests/combined/fixtures/d12/decision/assets/BTC.yaml
tests/combined/fixtures/d12/decision/assets/ETH.yaml
tests/combined/fixtures/d12/decision/global.yaml
tests/combined/fixtures/d12/docker-compose.yml
tests/combined/integration/test_decision_d12_decision_only_topology.py
tests/decision/certification/test_d10_resource_capacity.py
tests/decision/test_architecture_guardrails.py
tests/decision/test_d12_decision_only_topology.py
tests/decision/test_d9c_api_bootstrap.py
tests/execution/test_execution_bootstrap_routes.py
tests/models/momentum/test_core.py
tests/risk/test_runtime_signal_routes.py
tests/test_raw_indicator_pipeline.py
tests/test_signal_routes.py
```

The source-lock gate requires this exact key set and compares every current
SHA-256 to the stored map. Current-state gates independently recompute deleted
paths, root Compose, Decision/Risk routes, Execution assets, paper mode,
survivor imports, live references, retired-harness imports, the Decision seam,
source inventory, and source locks.

## Fail-closed certification

Added permanent current-state counterexamples for deleted-path, Compose, Risk,
Execution, live-reference, import-boundary, and source-lock drift. Preserved
and strengthened tamper checks for protected artifacts, identity/evidence
digests, stored gates, stored terminal status, and dangling transition imports.
The certifier reloads the written artifact and returns nonzero unless the
recomputed gates, digests, stored gates, and terminal status all agree.

## Refreshed artifact

One fresh disposable six-service run was completed with:

```text
db, broker, ingestion, decision, risk-worker, execution-worker
```

Artifact:

`artifacts/decision_d12/d12b_complete_legacy_retirement_certification.json`

```text
artifact SHA-256: 64621d3309240302f9aaef4c17f47bd2df9755904e12d6df8c5b1bb3435b6a74
identity digest:  868b86753806c6c5f84bc806a482681d982ae5e4e1c043bb8d71a4f835242234
evidence digest:  d159bdb58b09ba2508eeaee31e9bcf260eb851142fb7618a95378278a3d82f73
source SHA:      ad6873a258a898a55bd148ebecba51857648414a
source members:  47
gates:           62/62 true
terminal:        DECISION_D12B_COMPLETE_LEGACY_RETIREMENT_READY_FOR_REVIEW
```

Stored reload recomputation passed; all protected historical artifact hashes
remain exact and no historical artifact was regenerated. The former D12B
artifact SHA `10feab7e...` is superseded.

## Validation

```text
D12 focused + routing/neutral-feature slice       26 passed
guarded real D12 certification                     2 passed
stored D12B integrity test                        14 passed
full tests/decision                               483 passed
Regression + Momentum + Risk + Execution/config  404 passed
ingestion + D10/M3 protected slices               509 passed, 11 skipped, 2 warnings
combined integration collection                    30 collected
```

Static/import checks all passed:

- Ruff `check --no-cache`;
- Ruff `format --check`;
- compileall;
- `git diff --check`;
- plain `import libs.models` leaves both legacy registries empty;
- fresh `MomentumDecisionPlugin` import isolation;
- live forbidden-token scan;
- root and D12 fixture Compose renders.

The root render used only a temporary empty `.env`; the fixture render used
explicit disposable test ports. No credentials were created or copied.

Cleanup verified zero D12 containers, volumes, and networks and removed all
repo-local `__pycache__` and `.pytest_cache` directories. Primary `main` remains
`ad6873a258a898a55bd148ebecba51857648414a`, with no remediation commit or main
movement.

DECISION_D12B_RETIREMENT_INTEGRITY_REMEDIATION_READY_FOR_REVIEW
