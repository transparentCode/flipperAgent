# Coder-to-Orchestrator Handoff: D12A Decision-Only Topology Certification

## 1. Scope executed

Executed the D12A certification contract in the fresh isolated worktree:

`/Users/kajukatli/.devspace/worktrees/flipperAgent-decision-d12-decision-only-topology-certification`

The worktree remains detached at:

`78a88f9e7db0561d49f261404fb0372de073a65d`

No commit, merge, fast-forward, push, or primary-main mutation was performed.

The implementation is certification-only. No production source, production
Decision asset, root Compose, Risk, Execution, Momentum, legacy app, or
regression code was changed.

## 2. Files and symbols changed

Added the D12A disposable fixture and certification surfaces:

- `scripts/certify_decision_d12_decision_only_topology.py`
- `tests/combined/d12_harness.py`
- `tests/combined/integration/test_decision_d12_decision_only_topology.py`
- `tests/decision/test_d12_decision_only_topology.py`
- `tests/combined/fixtures/d12/docker-compose.yml`
- `tests/combined/fixtures/d12/decision/global.yaml`
- `tests/combined/fixtures/d12/decision/assets/BTC.yaml`
- `tests/combined/fixtures/d12/decision/assets/ETH.yaml`
- `tests/combined/fixtures/d12/configs/models.yaml`
- `tests/combined/fixtures/d12/configs/risk.yaml`
- `tests/combined/fixtures/d12/configs/execution.yaml`
- `tests/combined/fixtures/d12/configs/ingestion-runtime/global.yaml`
- `tests/combined/fixtures/d12/configs/ingestion-runtime/assets/.keep`
- `tests/combined/fixtures/d12/configs/ingestion-decision/global.yaml`
- `tests/combined/fixtures/d12/configs/ingestion-decision/assets/BTC.yaml`
- `tests/combined/fixtures/d12/configs/ingestion-decision/assets/ETH.yaml`
- `artifacts/decision_d12/d12_decision_only_topology_certification.json`

The runtime/Decision ingestion split is fixture-local: ingestion starts with
an empty asset map to avoid provider startup, while Decision receives the
canonical BTC/ETH instrument contract needed by D9A validation. Effect
progress baselines are seeded through the production composition, planner,
feature/data plan, and exact lane-identity fingerprint path; this is explicit
fixture preparation, not a Decision startup fallback.

The fixture also creates the existing paper Execution persistence tables before
starting the real worker, allowing its normal idempotency/fill path to run.

## 3. Certification evidence

Artifact:

`artifacts/decision_d12/d12_decision_only_topology_certification.json`

- artifact SHA-256: `4c7b41a069845b5dccfb01a4c21ea9706aa95da3651d9724584acbd506e7940b`
- source SHA: `78a88f9e7db0561d49f261404fb0372de073a65d`
- identity digest: `2dd631509979a871f8a9c066bc0d36e14cd04adcea887011790e9b6eca9b0f2e`
- evidence digest: `2496d4e9d8183d9cab9953748e64318980d9aec247ae0956c195330b02e0c866`
- terminal status: `DECISION_D12_DECISION_ONLY_TOPOLOGY_CERTIFICATION_READY_FOR_REVIEW`
- derived gates: `28/28 true`

Real disposable topology:

`db + broker + ingestion + decision + risk-worker + execution-worker`

No `signal-worker` or `strategy-worker` container was present. The measured
flow produced five Decision signals: BTC 1h = 3, BTC 4h = 1, ETH 4h = 1.
Risk consumed and acknowledged the Decision streams, and paper Execution
processed BTCUSDT and ETHUSDT orders into fills with `state=LIVE`.

Decision restart, broker restart, database restart, and full topology restart
all returned ready, preserved authority/effect progress, and remained
duplicate-free. No `features:*` or shadow output was created. Disposable
containers, volumes, and networks were removed successfully.

Resource evidence from the six measured phases:

- maximum aggregate RSS: `540,194,895` bytes
- maximum aggregate CPU: `0.1872` core-equivalents
- maximum Decision RSS: `97,328,824` bytes under the 512 MiB cap
- maximum ingestion RSS: `157,286,400` bytes under the 512 MiB cap
- maximum Risk RSS: `73,809,264` bytes under the 512 MiB cap
- maximum Execution RSS: `72,666,316` bytes under the 512 MiB cap
- no OOM kill and no unexpected restart

The DB and broker fixture services have no per-service `deploy.resources`
memory cap; their RSS is included in aggregate resource evidence, while the
per-service cap gate applies to services with an explicit configured limit.

## 4. Protected evidence

The artifact validates the exact protected hashes for D11C, D11B, D11A, C4B,
C4A, M3, M4 functional, M4 resource, and D10. D11C is read from its approved
isolated worktree because it is not present in this historical base; it was not
regenerated or modified.

## 5. Validation results

Focused D12:

- `tests/decision/test_d12_decision_only_topology.py`
- `tests/combined/integration/test_decision_d12_decision_only_topology.py`
- result: **8 passed, 1 skipped** (real integration is opt-in; the guarded
  real certification was run directly)

Compatibility:

- `tests/decision`: **501 passed, 1 skipped**
- `tests/regression`: **105 passed**
- `tests/models/momentum`: **55 passed**
- MI0/config slice: **16 passed**
- M3/M4 slice: **45 passed**
- Risk/Execution focused slice: **83 passed**

Static and boundary checks:

- Ruff `--no-cache`: passed on D12 Python scope
- Ruff format `--check`: passed
- compileall: passed for affected application packages and D12 scripts/harness
- fresh MomentumDecisionPlugin import isolation: passed
- Decision import boundary scan: passed; no `apps.signal_app` or
  `apps.strategy_app` dependency in `src/apps/decision_app`
- D12 fixture Compose render: passed
- repository Dockerfile image build: exercised by the real D12 run for
  ingestion, Decision, Risk, and Execution
- `git diff --check`: passed
- artifact gate recomputation from stored raw evidence: `28/28 true`
- no D12 Docker containers, volumes, or networks remain
- repo-local Python caches were cleaned by the test/certification runs

The root Compose render was attempted and is blocked only by the absent
worktree `.env` referenced by existing root services (`root_compose_rc=1`). No
credentials were created, copied, or used. The D12 disposable fixture itself
does not depend on `.env`.

## 6. Two-pass self-review

Pass 1 — topology/runtime correctness:

- verified the exact six-service topology and legacy-service absence;
- verified fresh canonical ingestion -> Decision -> signals -> Risk -> paper
  Execution flow;
- verified authority ownership and effect-progress baselines;
- verified Decision, broker, DB, and full-topology restart recovery;
- verified per-stream explicit signal-ID uniqueness and no shadow/legacy output;
- verified measured RSS, CPU, OOM, and restart evidence.

Pass 2 — architecture/scope:

- all changes remain in D12 tests, fixtures, harness, script, artifact, and
  handoff surfaces;
- no second runtime, worker, authority framework, or legacy deletion was added;
- no production configs or Compose service definitions were changed;
- Risk and Execution behavior remain on their existing contracts;
- no D13 or other future-phase work was started.

## 7. Residual risks / gates

- The root Compose validation remains environment-gated by the missing local
  `.env`; this was not bypassed with fabricated credentials.
- D12A certifies the Decision-only topology in disposable infrastructure. It
  does not delete or retire legacy source; that remains D12B.
- The protected D11C artifact is external to this historical base and was
  validated from the approved D11C worktree path.

## 8. Return

`DECISION_D12_DECISION_ONLY_TOPOLOGY_CERTIFICATION_READY_FOR_REVIEW`
