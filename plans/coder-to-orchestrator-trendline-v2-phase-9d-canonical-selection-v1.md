# Handoff

## Branch and scope

Branch: `feature/trendline-v2-phase-9d-canonical-selection-v1`
Base/current HEAD: `d2b6d8e57041200554ffbd1f87f2d81a9ff4259b`.
No commit, merge, push or new worktree.

Implemented the explicit immutable latest-valid-predecessor selection layer
and read-only Phase 9C.2 parity study. No provider, configuration, YAML,
viewer, tracking, MTF, Regime or legacy Trendline code changed.

Changed files:

```text
src/libs/models/trendline_v2/selection/__init__.py
src/libs/models/trendline_v2/selection/contracts.py
src/libs/models/trendline_v2/selection/latest_predecessor.py
src/libs/models/trendline_v2/api.py
src/libs/models/trendline_v2/__init__.py
tests/models/trendline_v2/test_selection_contracts.py
tests/models/trendline_v2/test_selection.py
tests/models/trendline_v2/test_api.py
scripts/validate_trendline_v2_canonical_selection.py
tests/scripts/test_trendline_v2_canonical_selection.py
plans/coder-to-orchestrator-trendline-v2-phase-9d-canonical-selection-v1.md
```

## Policy and contracts

Policy: `latest_valid_predecessor/v1`, family `latest_valid_predecessor_v1`,
provider `confirmed_extrema_pair/v1`, exactly two anchors, grouping
`(role, second_anchor_id)`, maximum first-anchor pivot time, then minimum
first-anchor ID and candidate ID, one output per nonempty group.

Policy identity: `3213d919e3e325b99ce156272759a42799bf296545b95c338ea803c087f99afc`
under `trendline_v2_candidate_selection_policy`.

Added frozen `SelectionStatus`, `CandidateSelectionDecision`,
`SelectionDiagnostics` and `CandidateSelectionSnapshot`. Tuples, canonical
IDs, UTC timestamps, source status/reason, exact partition arithmetic,
provider identity, second-anchor equality, two-anchor binding and content
identities are validated. Candidate-set identity binds the sorted complete
source candidate-ID set.

Public API requires an explicit policy and does not filter
`discover_trendlines` or load YAML. Selection does not read
`candidate_structure_id`, research scores, quality, ATR, current price,
future outcomes, viewer state or tracking state.

Identity namespaces:

```text
trendline_v2_candidate_selection_policy
trendline_v2_candidate_selection_decision
trendline_v2_candidate_set
trendline_v2_candidate_selection_snapshot
```

`VALID` maps to `SELECTED`; `ABSTAINED` maps to `SOURCE_ABSTAINED`; `FAILED`
maps to `SOURCE_FAILED`. Exact source `AbstentionReason` passes through.
Failed status requires `PROVIDER_FAILURE`; impossible combinations reject.
Synthetic timestamp-tie behavior is tested; frozen data has zero timestamp
ties.

## Frozen source and parity

Source root:
`/tmp/trendline_v2_phase9c2_fresh_scope_family_validation/20260522_20260701`

```text
source inventory: ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532
source decision: 4b734cbf99e1453bccdedb95f397f4b34e020f29e3d18808a131456647f78f7c
source manifest: beab5b9acb2bfc3c25ba9cb5cb31c33c1a31e6069c1d7906f3ed5e1c2d798c81
```

| Dataset | Source candidates | Selected |
|---|---:|---:|
| `btcusdt_1h` | 4343 | 422 |
| `btcusdt_4h` | 673 | 106 |
| `ethusdt_1h` | 4264 | 433 |
| `ethusdt_4h` | 721 | 109 |
| `suiusdt_1h` | 4410 | 437 |
| `suiusdt_4h` | 876 | 112 |

Totals: 6 datasets, 15,287 source candidates, 1,619 selected, zero missing,
zero unexpected, membership parity true.

## Evidence and accounting

Output root:
`/tmp/trendline_v2_phase9d_canonical_selection/20260522_20260701`

```text
status: SELECTION_LAYER_PARITY_VERIFIED
decision ID: c7daee89ffe745e12d4c8dcad65fc27a9c19f7da3b460acc32360af0f814b6cd
manifest ID: 51fb6ff236e8e6f94d47082c00fa27dc5692ab8e629e0a10959f35ccc2675585
output inventory: aca26bb086c3cd0b8ce04c152ab1b71fa240068c92c8f5691a7848fe3900ecb8
selection executions: 6
historical provider executions: 6
Phase 9D provider executions: 0
network requests: 0
```

Manifest binds ten data members. Historical result IDs are in
`source_audit.json`. Source inventory was identical before and after
selection. Output is outside Git, staged atomically, and existing roots are
rejected.

## Validation and indexing

```text
focused selection/API/parity: 64 passed, 1 skipped
Trendline V2/viewer: 167 passed
Trendline Family: 400 passed
benchmark: 4 passed
frontend: 13 passed
npm audit: 0 vulnerabilities
Ruff/compileall/diff check: passed
external frozen-bundle gate: 10 passed
```

Codebase-memory reindex completed non-zero: source `22,660/117,587`, tests
`5,473/22,976`, scripts `1,240/5,454`, plans `5,220/5,208`. GitNexus:
`48,512 nodes / 80,375 edges`.

## Boundaries and review state

No discovery default filtering, runtime migration, provider/YAML promotion,
tracking, lifecycle, interactions, events, MTF, viewer migration or Regime
integration. This is source-membership parity evidence only.

## Phase 9D review remediation

The contract now binds every embedded decision's
`selection_policy_identity` to the enclosing selection snapshot and derives
`latest_timestamp_tie_group_count` from the decision records. Consistent
policy rebinding remains identity-sensitive; partial rebinding and inconsistent
tie diagnostics are rejected.

Parity tests now cover missing and unexpected selected IDs, selected-count
drift, policy-identity drift after manifest rebinding, source mutation during
verification, zero provider/network execution, and exact frozen source and
selection snapshot identities. Snapshot contracts also reject duplicate
`(role, second_anchor_id)` groups and source-group diagnostic drift, including
through deserialization. The existing Phase 9D artifact root is retained
read-only and is not regenerated.

```text
PHASE_9D_GROUP_CARDINALITY_REMEDIATION_VERIFIED
COMMIT: NOT_AUTHORIZED
MERGE: NOT_AUTHORIZED
PUSH: NOT_AUTHORIZED
PHASE_10A_TRACKING: NOT_YET_AUTHORIZED
```
