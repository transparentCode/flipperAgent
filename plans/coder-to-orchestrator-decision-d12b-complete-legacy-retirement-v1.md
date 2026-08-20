---
goal: Retire the legacy Signal/Strategy runtime completely and certify the final Decision-only six-service topology
stage: coder-to-orchestrator
date_created: 2026-08-20
last_updated: 2026-08-20
owner: quant-coder
status: Ready for review
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, decision, d12b, retirement, cleanup, certification]
---

# D12B — complete legacy retirement

## Workspace and base

- worktree: `/Users/kajukatli/.devspace/worktrees/flipperAgent-decision-d12b-complete-legacy-retirement`
- worktree HEAD / local main base: `ad6873a258a898a55bd148ebecba51857648414a`
- ordinary main checkout: untouched in this phase

No commit, merge, fast-forward, push, rebase, or cherry-pick was performed.

## Outcome

The D12B retirement surface is implemented in the isolated worktree.

Retired completely:

- `src/apps/signal_app/**`
- `src/apps/strategy_app/**`
- root Compose services `signal-worker` and `strategy-worker`
- legacy Signal/Strategy API routers
- transitional D11 producer-authority/handoff runtime requirement
- obsolete five Strategy-only live routes:
  - `BNBUSDT:30m`
  - `DOGEUSDT:1h`
  - `DOGEUSDT:4h`
  - `SOLUSDT:1h`
  - `XRPUSDT:1h`

Final certified live path in D12B:

```text
db
broker
ingestion
decision
risk-worker
execution-worker
```

## Production/config/runtime changes

### Legacy app/runtime removal

Deleted:

- all tracked files under `src/apps/signal_app/**` (34 files)
- all tracked files under `src/apps/strategy_app/**` (29 files)
- `src/apps/api_app/routers/signal.py`
- `src/apps/api_app/routers/strategy.py`
- `src/libs/common/signal_authority.py`

Removed root API wiring from:

- `src/apps/api_app/app.py`

Removed legacy runtime services from:

- `docker-compose.yml`

### Configuration retirement

Updated:

- `configs/base.yaml`
  - removed obsolete `signal.runtime` configuration
- `configs/risk.yaml`
  - made Risk runtime routes explicit:
    - `BTCUSDT:1h`
    - `BTCUSDT:4h`
    - `ETHUSDT:4h`
- `configs/models.yaml`
  - removed `strategy:`
  - removed `strategy_models:`
  - removed obsolete live-route asset nodes for:
    - `BNBUSDT`
    - `DOGEUSDT`
    - `SOLUSDT`
    - `XRPUSDT`
- `configs/alerts.yaml`
  - removed legacy Signal/Strategy freshness entries

### Decision / Risk / Execution decoupling

Updated:

- `src/apps/decision_app/bootstrap.py`
- `src/apps/decision_app/runtime/startup.py`
- `src/apps/decision_app/transport/signals.py`
- `src/apps/risk_app/main.py`
- `src/apps/risk_app/api/app.py`
- `src/apps/risk_app/observability/service.py`
- `src/apps/execution_app/bootstrap.py`

Result:

- Decision no longer requires transitional `signal:authority:*` records.
- Risk runtime route discovery is no longer derived from legacy `configs/models.yaml`.
- Execution asset discovery is no longer derived from legacy `configs/models.yaml`.
- Retained live Risk/Execution scope is exactly BTC/ETH through the three Decision routes.

### Neutral extraction / retained production dependencies

Added:

- `src/libs/common/signal_routes.py`
- `src/libs/features/raw_indicator_pipeline.py`

Updated:

- `src/libs/common/config_validator.py`
- `src/libs/optim_utils/scoring_feature_pipeline.py`
- `src/libs/regime/optimization/downstream_backtest.py`

Result:

- retained route parsing moved to a neutral helper
- retained optimizer/research code no longer imports from deleted legacy app packages

## Deleted tests / docs / transitional scripts

Deleted legacy/transitional runtime surfaces including:

- all `tests/signals/**`
- all Strategy runtime test files under `tests/models/test_strategy_*`
- D11A / D11B / D11C harnesses, real matrices, fixtures, and Decision certification tests
- obsolete C4B / D11 fixtures
- obsolete transitional ingestion retirement/certification tests
- obsolete Signal/Strategy architecture and operations docs
- obsolete D11 authority/cutover certifier scripts
- obsolete ingestion transition certifier scripts

Key deleted top-level files include:

- `docs/decision_authority_operations.md`
- `docs/signal_app.md`
- `docs/strategy_app.md`
- `scripts/certify_decision_d11a_authority_handoff.py`
- `scripts/certify_decision_d11b_authority_cutover.py`
- `scripts/certify_decision_d11c_default_topology.py`
- `scripts/decision_d11b_authority_cutover.py`
- `scripts/retire_legacy_ingestion_n3b.py`

## New D12B certification surfaces

Added:

- `scripts/certify_decision_d12_decision_only_topology.py`
- `tests/combined/d12_harness.py`
- `tests/combined/integration/test_decision_d12_decision_only_topology.py`
- `tests/decision/test_d12_decision_only_topology.py`
- `tests/test_signal_routes.py`
- `tests/test_raw_indicator_pipeline.py`
- `tests/risk/test_runtime_signal_routes.py`
- `tests/execution/test_execution_bootstrap_routes.py`
- `tests/combined/fixtures/d12/**`

Historical D12 artifacts preserved unchanged:

- `artifacts/decision_d12/d12_decision_only_topology_certification.json`
  - SHA-256: `10aef43d41fab96acbb9f21f835a21c3c6e1268eafd7c0ee8e3b7f489a4802fc`
- `artifacts/decision_d12/d12_current_base_reconciliation_certification.json`
  - SHA-256: `aa1fea5a1bf10a7269fae9dbf69b0e25311dbea106d42314913108586db5a8dc`

Protected D11C artifact preserved unchanged:

- `artifacts/decision_d11c/d11c_default_topology_promotion_certification.json`
  - SHA-256: `2f4d59eb0059a66bd1d16a619e01ec3541130360fea58404877f8147c1fc7886`

## Final D12B artifact

Path:

- `artifacts/decision_d12/d12b_complete_legacy_retirement_certification.json`

Final facts:

- SHA-256: `10feab7e549b82dfd906f486238f3b9d1f7a2f58f033c59318f0171bed399f1b`
- source SHA: `ad6873a258a898a55bd148ebecba51857648414a`
- identity digest: `6a355e30f9c1d5a5c8270d280b184e5bd6e886b40647121a707476c7b3817a69`
- evidence digest: `f1f0f09ec565378c0ecba67d0617c6bf8685102b4a26e7462b1d316ac0572781`
- gates: `47/47 true`
- terminal: `DECISION_D12B_COMPLETE_LEGACY_RETIREMENT_READY_FOR_REVIEW`

The D12B artifact protects:

- final approved D11C artifact
- historical D12A artifact
- current-base D12A reconciliation artifact
- all prior protected M3 / M4 / D10 / C1 / C2 / C3A / C3B1 / C3B2P / C4A / C4B / D11A / D11B evidence

## Real certification result

The refreshed D12B certifier executed the real disposable six-service topology and produced the final artifact above.

Measured certified topology:

- `db`
- `broker`
- `ingestion`
- `decision`
- `risk-worker`
- `execution-worker`

Absent from the D12 fixture/runtime:

- `signal-worker`
- `strategy-worker`

Certified runtime evidence includes:

- fresh Decision startup and readiness
- real Decision signal publication
- Risk consumption on Decision signals
- paper Execution downstream activity
- Decision restart recovery
- broker restart recovery
- database restart recovery
- full topology restart recovery
- no shadow output
- no `signal:authority:*` requirement
- no surviving `features:*` runtime dependency

## Validation

Interpreter:

- `/Users/kajukatli/projects/flipperAgent/.venv/bin/python`

### Focused D12B

- `pytest -q tests/test_signal_routes.py tests/test_raw_indicator_pipeline.py tests/risk/test_runtime_signal_routes.py tests/execution/test_execution_bootstrap_routes.py tests/decision/test_d12_decision_only_topology.py`
- result: `24 passed`

### Real D12B certifier

- `PYTHONPATH=src NUMBA_CACHE_DIR=/tmp/numba-d12b-artifact /Users/kajukatli/projects/flipperAgent/.venv/bin/python scripts/certify_decision_d12_decision_only_topology.py`
- result:
  - artifact SHA-256 `10feab7e549b82dfd906f486238f3b9d1f7a2f58f033c59318f0171bed399f1b`
  - `47/47 true`
  - terminal `DECISION_D12B_COMPLETE_LEGACY_RETIREMENT_READY_FOR_REVIEW`

### Full Decision

- `pytest -q tests/decision`
- result: `481 passed in 151.84s`

### Regression + Momentum compatibility

- `pytest -q tests/regression tests/models/momentum`
- result: `160 passed`

### Risk / Execution / MI0 compatibility

- `pytest -q tests/risk tests/execution tests/test_config_alignment.py tests/models/test_import_isolation_mi0.py`
- result: `244 passed`

### Ingestion compatibility

- `pytest -q tests/ingestion`
- result: `468 passed, 11 skipped, 2 warnings`
- warnings:
  - existing OpenTelemetry `LoggingHandler` deprecation warnings from `tests/ingestion/test_main.py`

### D10 / M3 compatibility

- `pytest -q tests/decision/certification/test_d10_resource_capacity.py tests/decision/certification/test_m3_momentum_feature_semantics.py`
- result: `41 passed`

### Guarded real D12 integration

- `D12_RUN_REAL=1 pytest -q tests/combined/integration/test_decision_d12_decision_only_topology.py`
- result: `2 passed in 163.54s`

### Static / build / render

Scoped D12B-owned Python:

- `ruff check --no-cache <D12B-owned python paths>`
  - passed
- `ruff format --check <D12B-owned python paths>`
  - passed
- `python -m compileall <D12B-owned python paths>`
  - passed
- `git diff --check`
  - passed

Compose:

- root `docker compose config --quiet`
  - passed with a transient empty worktree `.env` created and removed only for render
- `docker compose -f tests/combined/fixtures/d12/docker-compose.yml config --quiet`
  - passed with explicit fixture-only port env:
    - `D12_DB_PORT=15432`
    - `D12_BROKER_PORT=16379`
    - `D12_INGESTION_PORT=18082`
    - `D12_DECISION_PORT=18004`

Cleanup:

- repo-local `__pycache__`: `0`
- D12 Docker leftovers: none observed (`no_d12_docker_leftovers`)

## Scope boundaries preserved

- no commit / merge / fast-forward / push
- no local `main` movement
- no legacy compatibility shim packages
- no new service/framework/runtime
- no migration for the five deleted Strategy-only routes
- no change to Momentum / Regression / Risk / Execution core semantics beyond retirement decoupling
- no historical D11 / D12 artifact regeneration

## Notes / residuals

- A broad repo-wide Ruff run is not a valid D12B signal because unrelated existing repository debt outside the D12B-owned surface remains. Scoped Ruff on the D12B diff is green.
- An optional API-router collection slice outside D12B scope remains environment-sensitive in this checkout because `tests/test_api_app_risk_router.py` requires `httpx2`. I did not install new dependencies or widen scope to fix that.
- The root Compose render in this isolated worktree required a transient empty `.env` only because the retained Compose file still references `env_file: .env` for non-D12 services. No credentials were created, copied, or retained.

DECISION_D12B_COMPLETE_LEGACY_RETIREMENT_READY_FOR_REVIEW
