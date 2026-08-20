---
goal: Reconcile historical D12A Decision-only certification onto the D11C-integrated current base without rewriting historical evidence
stage: coder-to-orchestrator
date_created: 2026-08-20
last_updated: 2026-08-20
owner: quant-coder
status: Ready for review
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, decision, d12a, reconciliation, certification]
---

# D12A current-base reconciliation

## Workspace and base

- worktree: `/Users/kajukatli/.devspace/worktrees/flipperAgent-decision-d12a-current-base-reconciliation`
- worktree HEAD: `ad6873a258a898a55bd148ebecba51857648414a`
- local `main`: `ad6873a258a898a55bd148ebecba51857648414a`
- `origin/main`: `78a88f9e7db0561d49f261404fb0372de073a65d`
- ordinary main checkout: untouched in this phase

No commit, merge, fast-forward, or push was performed.

## Files added/changed in the isolated worktree

- `artifacts/decision_d12/d12_decision_only_topology_certification.json` copied from historical D12A worktree, preserved byte-identically
- `artifacts/decision_d12/d12_current_base_reconciliation_certification.json`
- `plans/coder-to-orchestrator-decision-d12-decision-only-topology-certification-v1.md` copied byte-identically
- `plans/coder-to-orchestrator-decision-d12a-certification-integrity-remediation-v1.md` copied byte-identically
- `plans/coder-to-orchestrator-decision-d12a-current-base-reconciliation-v1.md`
- `scripts/certify_decision_d12_decision_only_topology.py`
- `tests/combined/d12_harness.py`
- `tests/combined/integration/test_decision_d12_decision_only_topology.py`
- `tests/decision/test_d12_decision_only_topology.py`
- `tests/combined/fixtures/d12/**` historical fixture carried into the reconciliation worktree

No production source under `src/` or production config under `configs/` was changed.

## Historical D12A preservation

Historical artifact path:

- `artifacts/decision_d12/d12_decision_only_topology_certification.json`

Preserved exact historical facts:

- SHA-256: `10aef43d41fab96acbb9f21f835a21c3c6e1268eafd7c0ee8e3b7f489a4802fc`
- source SHA: `78a88f9e7db0561d49f261404fb0372de073a65d`
- identity digest: `130f1aff120b8a4dbca5d38a3e8f02e566224a5af9acc3ad4aca7e98a7954101`
- evidence digest: `87e748bd396a570a4612666ecf4d367861f96d1331480b3008caa7c3ab7d3792`
- stored gates: `34/34 true`
- terminal: `DECISION_D12_DECISION_ONLY_TOPOLOGY_CERTIFICATION_READY_FOR_REVIEW`
- source-lock members: `15`
- historical protected D11C hash unchanged: `d4e30bdd26b14750939b5132572b44888b2b7fc28e2a5ff821786f47bf6ca915`

Historical coder records were also carried byte-identically:

- `plans/coder-to-orchestrator-decision-d12-decision-only-topology-certification-v1.md`
- `plans/coder-to-orchestrator-decision-d12a-certification-integrity-remediation-v1.md`

## Current approved D11C binding

Current protected D11C artifact on integrated base:

- path: `artifacts/decision_d11c/d11c_default_topology_promotion_certification.json`
- SHA-256: `2f4d59eb0059a66bd1d16a619e01ec3541130360fea58404877f8147c1fc7886`
- identity digest: `134d81ac771853fab7b9712609bbca2a04448bb5f44a423d7e044ecf9bd442dd`
- evidence digest: `7c7b9fc6b21c204cbb080170b825a86e2a000db5244a46550de2f56a1fe25791`
- evaluator: `65/65 true`
- semantic parity: `matches = true`

The current-base D12A artifact binds this final D11C proof through raw evidence and gate evaluation.

## New current-base reconciliation artifact

Current artifact path:

- `artifacts/decision_d12/d12_current_base_reconciliation_certification.json`

Final artifact facts:

- SHA-256: `aa1fea5a1bf10a7269fae9dbf69b0e25311dbea106d42314913108586db5a8dc`
- source SHA: `ad6873a258a898a55bd148ebecba51857648414a`
- identity digest: `bcc5e85323099f7c4a4f072f0f2db9b229e0c1117232a4d3ddb4d1ae5bb23b25`
- evidence digest: `daf6a928022140950e82ba121898f24b8e5e0fed612d9f3883885669ed283eb9`
- source-lock members: `15`
- gates: `38/38 true`
- terminal: `DECISION_D12A_CURRENT_BASE_RECONCILIATION_READY_FOR_REVIEW`

The current artifact explicitly records:

- six-service Decision-only topology only
- historical D12A archive status as archival evidence
- current D11C proof status
- surviving runtime import boundary
- exact four remaining code-dependency debt locations for D12B
- exact five still-Strategy-owned route debt for D12B

## Real current-base D12A certification evidence

One fresh real six-service current-base run was executed and serialized into the current artifact.

Measured topology:

- `db`
- `broker`
- `ingestion`
- `decision`
- `risk-worker`
- `execution-worker`

Absent from the D12 fixture/runtime:

- `signal-worker`
- `strategy-worker`

Runtime proof in the artifact includes:

- Decision startup ready
- ingestion ready
- Risk ready
- Execution ready
- real Decision signal flow
- Risk group consumption on Decision signal streams
- paper Execution downstream evidence
- Decision restart recovery
- broker restart recovery
- database restart recovery
- full-topology restart recovery
- no required legacy streams
- no shadow output

## D12B debt recorded explicitly

Remaining code-dependency debt recorded in the current artifact:

- `src/apps/api_app/routers/signal.py -> apps.signal_app`
- `src/apps/api_app/routers/strategy.py -> apps.strategy_app`
- `src/libs/optim_utils/scoring_feature_pipeline.py -> Signal raw-indicator pipeline`
- `src/libs/regime/optimization/downstream_backtest.py -> Strategy model managers`

Remaining still-Strategy-owned routes recorded exactly:

- `BNBUSDT:30m`
- `DOGEUSDT:1h`
- `DOGEUSDT:4h`
- `SOLUSDT:1h`
- `XRPUSDT:1h`

These were recorded as D12B debt only. No legacy deletion/removal work was started here.

## Validation

Interpreter used for all Python validation:

- `/Users/kajukatli/projects/flipperAgent/.venv/bin/python`

Focused D12:

- `tests/decision/test_d12_decision_only_topology.py`
- `tests/combined/integration/test_decision_d12_decision_only_topology.py`
- result: `15 passed, 1 skipped`

Real current-base D12 certifier:

- command: `PYTHONPATH=src NUMBA_CACHE_DIR=/tmp/flipperagent-numba-d12a /Users/kajukatli/projects/flipperAgent/.venv/bin/python scripts/certify_decision_d12_decision_only_topology.py`
- final result: current artifact above, `38/38 true`

Decision compatibility:

- `tests/decision`
- result: `559 passed, 1 skipped`

Protected compatibility slice:

- `tests/regression`
- `tests/models/momentum`
- `tests/models/test_import_isolation_mi0.py`
- `tests/test_config_alignment.py`
- `tests/decision/certification/test_m3_momentum_feature_semantics.py`
- `tests/decision/certification/test_m4_certification.py`
- `tests/models/test_strategy_runtime_pairs.py`
- `tests/models/test_strategy_runtime_runner.py`
- `tests/models/test_strategy_runtime_state.py`
- `tests/signals/test_signal_main.py`
- `tests/signals/test_signal_runtime_lifecycle.py`
- `tests/signals/test_signal_runtime_pairs.py`
- `tests/signals/test_signal_runtime_state.py`
- `tests/risk/test_risk_worker.py`
- `tests/risk/test_profile_resolver.py`
- `tests/execution/test_execution_worker.py`
- `tests/execution/test_order_manager.py`
- `tests/execution/test_paper_executor.py`
- result: `299 passed, 1 known OpenTelemetry deprecation warning`

Static/import checks:

- Ruff check on changed Python: passed
- Ruff format check on changed Python: passed
- compileall on changed/import-critical Python: passed
- `git diff --check`: passed
- fresh Momentum import-isolation probe: passed

Compose and Docker:

- D12 fixture compose render: passed with explicit fixture ports
- D12 disposable leftovers after final real run:
  - containers: `0`
  - volumes: `0`
  - networks: `0`
- root compose render attempt: blocked by missing worktree `.env`
  - exact stderr: `env file /Users/kajukatli/.devspace/worktrees/flipperAgent-decision-d12a-current-base-reconciliation/.env not found: stat /Users/kajukatli/.devspace/worktrees/flipperAgent-decision-d12a-current-base-reconciliation/.env: no such file or directory`

## Scope boundaries preserved

- no production `src/` change
- no production `configs/` change
- no historical D12A artifact regeneration
- no historical D11C substitution into archival D12A
- no Signal/Strategy service in the D12 fixture
- no D12B implementation
- no commit / merge / fast-forward / push

## Residual risks / notes

- The current-base D12A artifact is a fresh reconciliation proof, not a historical overwrite. The historical D12A artifact must continue to be treated as archival evidence at source SHA `78a88f9e7db0561d49f261404fb0372de073a65d`.
- Root compose render remains environment-gated in this isolated worktree because `.env` is absent. This phase did not copy credentials or mutate root runtime state to force that command green.
- The remaining code-dependency debt and five Strategy-owned routes are explicitly recorded for D12B; they are not resolved in D12A.

DECISION_D12A_CURRENT_BASE_RECONCILIATION_READY_FOR_REVIEW
