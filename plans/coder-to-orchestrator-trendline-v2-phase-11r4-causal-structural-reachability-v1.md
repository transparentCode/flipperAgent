# Coder to Orchestrator: Trendline V2 Phase 11R.4

## Status

`R4_DIAGNOSTIC_INCOMPLETE_CLOSED`

Bounded implementation and one authorized canonical diagnostic run are complete.
R4 is incomplete because of one-sided reachability populations. This is neither
hypothesis failure nor evidence corruption.

## Scope

Created only:

```text
scripts/analyze_trendline_v2_causal_structural_reachability.py
tests/scripts/test_trendline_v2_causal_structural_reachability.py
plans/coder-to-orchestrator-trendline-v2-phase-11r4-causal-structural-reachability-v1.md
```

No R3B script or test was modified. No `src/`, configuration, viewer,
runtime, provider, tracker, MTF, Regime or YAML path was changed.

## Work Completed

- Added strict read-only verification for the approved temporal-v2 R3B bundle
  and four-member raw BTC/ETH source allowlist.
- Bound verification to the frozen temporal-v2 decision, validation lock,
  manifest and inventory identities.
- Rejected unsafe or non-allowlisted raw-member reads while permitting
  unrelated untouched files in the retained raw source root.
- Added causal OHLCV normalization, exact UTC timestamp validation, OHLC
  relationship checks, volume checks and Wilder ATR recurrence.
- Added causal origin-bar selection and horizon-independent feature rows.
- Kept contender, control, dataset, role, lineage and selection identities
  separate; retained role-transfer observations in the primary population.
- Added exact three-horizon outcome joins without duplicating feature identity.
  - Rejected relevant orphan, duplicate and missing outcome keys; independent
  diagnostic rows remain explicitly outside the actionable join namespace.
- Remediated every descriptive summary to preserve the complete population
  namespace, including contender, budget, derivation, control and dataset.
- Remediated compression retention to count unique causal feature rows in the
  primary 96h stratum over the same unstratified namespace/role rows; incumbent
  retention remains separate audit evidence.
- Remediated structural overlap to intersect exact
  `(dataset_id, checkpoint_index, semantic_role, lineage_id)` tuples using
  actionable R3B selection rows and secondary structural rows.
- Kept primary stratum membership/support counts feature-derived and outcome
  means outcome-derived; missing outcomes now mark cell reconciliation without
  changing causal support membership.
- Integrated duplicate, unresolved, missing-source, source-count, geometry,
  outcome and orphan states into per-cell terminal reconciliation.
- Enforced evaluable-only outcome denominators and independent unresolved
  evidence/reconciliation checks before complete publication.
- Added stratum reconciliation, terminal-cell classification and fail-closed
  R4 decision precedence. One-sided evidence cannot produce positive support or
  branch closure.
- Added complete deterministic evidence: feature rows/identities, descriptive
  strata, reachability, role coverage, retention, outcome denominators,
  comparison cells/deltas, R3B reference metrics and structural lineage audit.
- Added strict temporal-v2 member-byte, manifest, contract, source-audit,
  decision and validation-lock identity verification.
- Added exact three-file R4 bundle rendering and source-backed rederivation;
  forged evidence and rebound manifests fail closed.
- Added guarded canonical execution pipeline with before/after source snapshots,
  staging verification and atomic publication. It was invoked exactly once.
- Added synthetic/adversarial tests for causal invariance, namespace isolation,
  duplicate rejection, outcome binding, cell precedence, source integrity,
  allowlisted reads, atomic overwrite behavior and execution gating.

## Protected Evidence

Temporal-v2 R3B evidence was verified read-only:

```text
Decision: 66240c90f6d7b4c8575caebd1b248dbaa8084819c99504e19c210a0ec0b331ec
Inventory: 658e2649d2c74f5f6cf8e8bfea38efb95c55908766a01a8d8e6a8950c430907c
```

Superseded R3B evidence remains preserved and was not modified:

```text
Inventory: 94c2cbd43c685ddb471c186c9440f3c2cf7febd04d588fc1b23f836903ddef03
```

The approved raw source inventory remains:

```text
2f2db301ca6c9c355bb4d645bb2d631836749748835c0419573e7cf52d27de27
```

R4 output was published exactly once and remains protected.

## Canonical R4 Evidence

```text
status:                    R4_DIAGNOSTIC_INCOMPLETE
diagnostic_decision:       null
diagnostic_id:              f4a95e118d52eec9ae60b447f08ca11a756908d7861772978b8f0393b0bbd2e2
manifest_id:                965b4741ec0f7305b8217dbc90d5c2bb31a6185e09b42c519bc404548c290a7e
output_inventory:           7fbd19fd1b828c09881df6236d2c3b8bdf7ae4bdfd4cd4b03d770c401ecd413c
files / manifest members:   3 / 2
feature rows:               7740
joined outcomes:            23220
comparisons:                144
matched:                    93
one-sided:                  51
unresolved evidence:        0
unresolved reconciliation:  0
```

The canonical output contains exactly `manifest.json`,
`reachability_diagnostic.json` and `source_binding.json`. Strict verification
passed. Protected source snapshots remained identical before and after the
run:

```text
temporal-v2 inventory: 658e2649d2c74f5f6cf8e8bfea38efb95c55908766a01a8d8e6a8950c430907c
raw inventory:        2f2db301ca6c9c355bb4d645bb2d631836749748835c0419573e7cf52d27de27
```

## Validation

Focused tests:

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scripts/test_trendline_v2_causal_structural_reachability.py -q -ra
37 passed
```

Static validation:

```text
ruff check \
  scripts/analyze_trendline_v2_causal_structural_reachability.py \
  tests/scripts/test_trendline_v2_causal_structural_reachability.py
passed

PYTHONPATH=src .venv/bin/python -m compileall -q \
  scripts/analyze_trendline_v2_causal_structural_reachability.py \
  tests/scripts/test_trendline_v2_causal_structural_reachability.py
passed

git diff --check
passed
```

Strict source verification:

```text
PYTHONPATH=src .venv/bin/python \
  scripts/analyze_trendline_v2_causal_structural_reachability.py --verify
{"raw_inventory": "2f2db301ca6c9c355bb4d645bb2d631836749748835c0419573e7cf52d27de27", "status": "R4_SOURCE_BINDING_VERIFIED", "temporal_inventory": "658e2649d2c74f5f6cf8e8bfea38efb95c55908766a01a8d8e6a8950c430907c"}
```

Cross-phase regression:

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scripts/test_trendline_v2_joint_structural_compression.py \
  tests/scripts/test_trendline_v2_causal_structural_reachability.py -q -ra
153 passed
```

Codebase-memory reindex was retried. Its worker exited non-zero while
discovering a stale or missing legacy-worktree target; existing indexes remain
intact. This infrastructure failure did not alter source files or validation
results.

## Safety Boundary

```text
R4 canonical execution:     one authorized run
R4 evidence publication:    completed once
Provider executions:        0
Network requests:           0
Raw SUI accesses:           0
Holdout accesses:           0
Phase 10C.2 temporal reads: 0
Legacy executions:          0
```

No parameters, thresholds, contracts, protected artifacts or runtime behavior
were changed. No provider, selector, tracking, viewer, MTF, Regime or YAML
promotion is implied.

## Known Gaps and Risks

- Canonical execution was authorized once; published R4 evidence remains
  protected and must not be regenerated.
- The source verifier is pinned to the approved temporal-v2 and raw-source
  identities; source drift must fail closed.
- Synthetic tests cover contract and adversarial paths, not real R4 evidence.
- Codebase-memory refresh remains blocked by stale/missing legacy-worktree
  discovery; existing non-zero indexes are preserved.

## Closeout Review

Independently review the three R4 implementation files, causal feature and join
keys, source-binding checks, terminal-cell precedence and protected evidence.
R4 rerun, holdout access, temporal rerun, merge and push remain prohibited.

```text
IMPLEMENTATION: APPROVED
CONTRACT: APPROVED
R4 EVIDENCE: VERIFIED
R4 RERUN: PROHIBITED
R5 IMPLEMENTATION: NOT_AUTHORIZED
COMMIT: AUTHORIZED_FOR_CLOSEOUT
MERGE/PUSH: NOT_AUTHORIZED
```
