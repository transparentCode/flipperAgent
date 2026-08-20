# Coder-to-Orchestrator Handoff: D11C Cutback Bootstrap Duplicate Remediation

## Result

`DECISION_D11C_CUTBACK_BOOTSTRAP_DUPLICATE_REMEDIATION_READY_FOR_REVIEW`

The remediation was completed in the existing D11C worktree without moving
`main` and without commit, merge, fast-forward, or push.

Worktree:

`/Users/kajukatli/.devspace/worktrees/flipperAgent-decision-d11c-default-topology-promotion`

Base/source SHA:

`78a88f9e7db0561d49f261404fb0372de073a65d`

## Implemented

The shared cutback primitive now reasons about transport rows as logical cutoff
runs rather than assuming one stream row equals one market cutoff.

- Stream IDs must be numeric and strictly increasing.
- Logical cutoffs must be non-decreasing.
- Adjacent equal cutoffs form one logical run.
- Unique cutoffs must advance by exactly one timeframe duration.
- The exact Decision progress cutoff must be present.
- Duplicate runs are accepted only at or before Decision progress.
- Duplicate runs after progress fail closed.
- The first unread logical cutoff must equal `R + timeframe_duration`.
- `last_id_through_progress` is the final transport ID in the logical run at `R`.
- `XGROUP SETID` therefore leaves every Decision-owned replay row behind the
  restored Strategy consumer position.

`cutback_fast_forward_group()` now requires the first retained XRANGE ID to
equal the consumer group's last-delivered ID. A trimmed anchor blocks rather
than being inferred from a later retained row.

Feature-vector duplicate identity is deterministic and limited to the approved
market identity fields: asset, timeframe, timestamp, and `bar_data`. Same-cutoff
rows with conflicting market-bar identity fail closed. Feature/metadata changes
inside a Decision-owned duplicate run remain tolerable because those rows are
skipped during rollback.

## Source-lock handling

The historical D11B artifact was not regenerated. `tests/combined/d11b_harness.py`
now validates the frozen D11B source/config map and digest, so the stored D11B
artifact remains tied to its certified historical bytes while the evolved
cutback implementation is certified by D11C.

Frozen D11B evidence preserved:

- artifact SHA: `9bf16504f114eae000fc4006712731e93f15815c0827cf18af8864aa4f74b05d`
- source-map digest: `adac68a739799eb6c29a188ddcf0586b69d4b972c51b639beb51cf5d4f0ddd3a`
- historical cutback script SHA: `7abd55c5b342f612bf67f630765207b9eba9b2f8b07d7a88bddf8857f302c257`

D11C source locks include the evolved cutback script and historical-lock test
surfaces. The D11C protected artifact map remains exact.

## Files changed or added

Remediation implementation and evidence surfaces:

- `scripts/decision_d11b_authority_cutover.py`
- `tests/combined/d11b_harness.py`
- `tests/decision/test_d11b_authority_cutover.py`
- `tests/decision/test_d11b_certification.py`
- `tests/combined/d11c_harness.py`
- `tests/combined/d11c_real.py`
- `scripts/certify_decision_d11c_default_topology.py`
- `tests/combined/integration/test_decision_d11c_default_topology.py`
- `tests/decision/test_d11c_default_topology.py`
- `artifacts/decision_d11c/d11c_default_topology_promotion_certification.json`
- this coder handoff

The pre-existing D11C production/config/fixture changes were preserved in the
worktree. No Signal runtime, Risk/Execution, Momentum, Regression, legacy
retirement, D12, R5, or geometry/trendline changes were introduced.

## Real D11C evidence

The final fresh two-trial disposable D11C certification completed with:

- terminal status:
  `DECISION_D11C_DEFAULT_TOPOLOGY_PROMOTION_READY_FOR_REVIEW`
- all `51/51` derived gates true;
- two semantically identical measured trials;
- final authority `Decision` epoch 3 on all three target routes;
- real cold-restart bootstrap duplicate rows observed;
- every tolerated duplicate is Decision-owned and at or before progress;
- exact last duplicate ID selected for rollback `SETID`;
- retained-stream anchor preserved;
- lifecycle admission and missing/corrupt-authority isolation passed;
- paper Risk/Execution path passed;
- both trials cleaned all disposable infrastructure.

Final artifact:

`artifacts/decision_d11c/d11c_default_topology_promotion_certification.json`

- SHA-256: `d4e30bdd26b14750939b5132572b44888b2b7fc28e2a5ff821786f47bf6ca915`
- `identity_digest`: `ced8ac4a71a8cdfd0f3d9ffb3dfad5a21794548ac88e186ff8b43134788d4d59`
- `evidence_digest`: `a8908a8dabc0451707f6786428ad82a240ca0b92450f592853cfc4338e2a6620`
- `source_sha`: `78a88f9e7db0561d49f261404fb0372de073a65d`

## Validation

- focused cutback/source-lock/evaluator suite: **46 passed, 2 skipped**
- `tests/decision`: **519 passed, 1 skipped**
- regression, Momentum, MI0/config, M3/M4 compatibility group: **207 passed**
- focused D11B/D11C, Strategy, Signal, Risk, and Execution suites:
  **131 passed, 1 skipped, 1 existing OTel warning**
- Ruff no-cache: passed
- Ruff format check: passed
- compileall/import validation: passed
- `git diff --check`: passed
- root and D11C Compose rendering: passed
- fresh `libs.models`/Momentum import isolation and explicit legacy bootstrap
  probes: passed
- D11C source/artifact canonical regeneration and tamper checks: passed
- no disposable D11C Docker resources remain
- repository cache directories removed
- temporary empty `.env` used only for root Compose syntax neutralization was
  removed; no credentials were created or copied

## Self-review

Pass 1 — causal/cutback correctness:

- logical duplicate runs are collapsed without deleting transport rows;
- strict stream ordering and timeframe continuity are enforced;
- exact progress presence and first unread cutoff are enforced;
- post-progress duplicates fail closed;
- same-cutoff market-bar identity conflicts fail closed;
- trimmed anchors fail closed;
- real cold restart evidence demonstrates increased transport multiplicity
  without advancing the latest logical cutoff;
- rollback selects the final transport ID in the Decision-owned run at `R`.

Pass 2 — architecture/scope:

- no Signal publication redesign or deterministic FeatureVector ID change;
- no new recovery worker, daemon, queue, or framework;
- D11B historical evidence remains frozen rather than regenerated;
- D11C source locking covers the evolved shared primitive;
- no Risk/Execution, model, regression, legacy-retirement, D12, R5, or
  geometry/trendline work;
- no commits, merges, fast-forwards, or pushes were performed.

## Residual risks

- The normal root Compose environment has no worktree `.env`; syntax was
  validated with a temporary empty environment only. Real infrastructure
  validation used the disposable D11C fixture and did not use shared state.
- Resource evidence certifies the D11C topology only; it is not a D12 or full
  production fleet certification.
- Authority cutover remains externally orchestrated as specified by D11B/D11C.

DECISION_D11C_CUTBACK_BOOTSTRAP_DUPLICATE_REMEDIATION_READY_FOR_REVIEW
