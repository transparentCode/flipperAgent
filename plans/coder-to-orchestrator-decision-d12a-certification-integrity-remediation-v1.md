---
goal: D12A certification integrity remediation
stage: coder-to-orchestrator
status: ready-for-review
source_sha: 78a88f9e7db0561d49f261404fb0372de073a65d
---

# D12A certification integrity remediation

## Scope

Completed only the evidence-boundary remediation in the isolated D12A
worktree:

`/Users/kajukatli/.devspace/worktrees/flipperAgent-decision-d12-decision-only-topology-certification`

The worktree remains detached at the historical D12A base
`78a88f9e7db0561d49f261404fb0372de073a65d`. No production source, main
checkout, commit, merge, fast-forward, push, D12B, or D11C work was performed.

## Changed surfaces

- `tests/combined/d12_harness.py`
  - canonicalizes measured evidence before hashing and storing it;
  - adds exact 15-member D12A source inventory and `source_sha` gate;
  - recomputes source locks from the current worktree;
  - adds identity/evidence digest integrity gates;
  - records the four surviving runtime app import boundary and explicit D12B
    retirement debt;
  - derives all content and integrity gates from stored evidence.
- `tests/decision/test_d12_decision_only_topology.py`
  - permanent stored-artifact recomputation test;
  - source-map, source-SHA, harness/certifier, identity-digest, and
    evidence-digest tamper tests;
  - source-lock recomputation seam test;
  - four-surviving-app legacy import boundary test.
- `artifacts/decision_d12/d12_decision_only_topology_certification.json`
  - regenerated once from a fresh disposable six-service run.
- `plans/coder-to-orchestrator-decision-d12a-certification-integrity-remediation-v1.md`
  - this handoff.

The D12 source-lock map contains exactly 15 members: the certifier, harness,
integration/evaluator tests, fixture Compose file, and every D12 fixture config
used by the run. The artifact itself is excluded from its own source map.

## Fresh artifact evidence

- artifact SHA-256:
  `10aef43d41fab96acbb9f21f835a21c3c6e1268eafd7c0ee8e3b7f489a4802fc`
- identity digest:
  `130f1aff120b8a4dbca5d38a3e8f02e566224a5af9acc3ad4aca7e98a7954101`
- evidence digest:
  `87e748bd396a570a4612666ecf4d367861f96d1331480b3008caa7c3ab7d3792`
- source SHA:
  `78a88f9e7db0561d49f261404fb0372de073a65d`
- derived gates: `34/34 true`
- terminal status:
  `DECISION_D12_DECISION_ONLY_TOPOLOGY_CERTIFICATION_READY_FOR_REVIEW`

The stored artifact was loaded after generation and independently verified:

- stored gates equal freshly derived gates;
- all freshly derived gates are true;
- stored identity digest equals recomputed identity digest;
- stored evidence digest equals recomputed evidence digest;
- stored terminal status is READY;
- all nine protected D11C/D11B/D11A/C4B/C4A/M3/M4/D10 hashes are exact.

The measured topology remains:

`db + broker + ingestion + decision + risk-worker + execution-worker`

with no `signal-worker` or `strategy-worker`. The artifact records the clean
survivor import boundary for `ingestion_app`, `decision_app`, `risk_app`, and
`execution_app`, and records—not removes—the known D12B retirement debt in
`api_app`, optimization, and regime backtest paths.

## Focused tamper and compatibility evidence

- D12 unit/integration scope: **12 passed, 1 skipped**;
- `tests/decision`: **505 passed, 1 skipped**;
- `tests/regression`: **105 passed**;
- `tests/models/momentum`: **55 passed**;
- MI0/config: **16 passed**;
- M3/M4: **45 passed**;
- `tests/risk`: **164 passed**;
- `tests/execution`: **60 passed**.

The stored-artifact tests fail closed when a source-map member, source SHA,
harness/certifier lock, identity digest, or evidence digest is tampered. The
existing topology, authority, paper-mode, duplicate-signal, legacy-service,
and resource tamper coverage remains active.

## Static and infrastructure checks

- Ruff `--no-cache`: passed on D12 Python scope;
- Ruff format `--check`: passed;
- compileall: passed on D12 Python scope;
- fresh surviving-app import probe: passed;
- D12 fixture Compose render: passed with dynamically supplied disposable ports;
- repository image build: exercised by the fresh real certification run;
- `git diff --check`: clean;
- protected artifact validation: passed;
- no D12 Docker containers, volumes, or networks remain;
- repo-local caches cleaned.

The root Compose render remains blocked only by the absent worktree `.env`
referenced by the pre-existing root Compose file. No credentials were created,
copied, or fabricated. The D12 fixture and real certification do not depend on
that `.env`.

## Review passes

Pass 1 — certification correctness:

- canonical JSON-safe values are hashed and stored identically;
- source SHA and all 15 current source members are bound;
- integrity gates are recomputed from stored fields;
- stored artifact gates/status are independently checked;
- fresh real Decision-only runtime evidence remains six-service and legacy-free;
- D12B retirement debt is explicit rather than incorrectly claimed absent.

Pass 2 — scope/architecture:

- no production/runtime changes;
- no legacy deletion or migration;
- no new service, framework, or recovery mechanism;
- no protected artifact regeneration;
- no D11C convergence, D12B, or D13 work.

## Sequencing and residual risks

D12A remains a historical Decision-only certification at its frozen base.
D11C is protected through its approved external artifact and was not
regenerated. D12B legacy deletion is blocked until D11C is independently
approved and converged/integrated into the D12B base.

`DECISION_D12A_CERTIFICATION_INTEGRITY_REMEDIATION_READY_FOR_REVIEW`
