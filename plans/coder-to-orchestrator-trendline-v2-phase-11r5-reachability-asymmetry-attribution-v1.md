# Coder to Orchestrator: Trendline V2 Phase 11R.5

## Status

R5_COMPLETE

R5 contract, implementation and canonical evidence accepted by strict
source-backed verification.

## Work completed

Implemented read-only causal reachability asymmetry attribution with:

- strict `verify_reachability_bundle`-only R4 boundary;
- exact three-member R4 read boundary after verification;
- exact `51 / 117 / 25 / 92` population reconciliation;
- primary/terminal class agreement and primary-class direction binding;
- global feature consistency limited to source one-sided cells and higher-budget
  comparison cells used by cross-budget attribution;
- relevant higher-budget cell identities persisted on each source cell;
- reachable-direction XOR enforcement;
- mutually exclusive full and partial substitution classification;
- exact selected-line overlap and distance/headroom evidence;
- deterministic typed identity ordering;
- deterministic first paired higher-budget selection;
- strict rescue, non-nested pairing and budget-3 persistence semantics;
- outcome-field mutation invariance;
- complete-payload semantic gate rejecting unresolved evidence before rendering;
- canonical three-file atomic publication and identical-only overwrite;
- strict source-backed and explicit synthetic verification paths;
- alternate verified-R4-root binding;
- complete-only attribution classes and empty inconsistency references;
- guarded CLI execution path.

No outcome, holdout, temporal, provider, network, selector, promotion or
runtime fields enter attribution.

## Files changed

```text
scripts/analyze_trendline_v2_reachability_asymmetry_attribution.py
tests/scripts/test_trendline_v2_reachability_asymmetry_attribution.py
plans/coder-to-orchestrator-trendline-v2-phase-11r5-reachability-asymmetry-attribution-v1.md
```

No other files changed by implementation. Existing R5 output was preserved
unchanged.

## Source-backed in-memory evidence

Derivation used strict R4 verification, then read only the three R4 bundle
members. No R5 publication occurred.

```text
status:                         R5_ATTRIBUTION_COMPLETE
one-sided comparisons:          51
one-sided cells:                117
contender-only cells:            25
control-only cells:              92
unresolved evidence:              0
FULL_LINEAGE_SUBSTITUTION:       97
PARTIAL_LINEAGE_SUBSTITUTION:    20
STRICT_BUDGET_RESCUE:            52
PERSISTENT_THROUGH_BUDGET_3:     65
NON_NESTED_HIGHER_BUDGET_PAIRING: 0
```

These values are derived, not hardcoded.

## Accepted canonical evidence

The bundle was present at authorised preflight and was independently verified
read-only against protected R4 evidence. No delete, overwrite or rerun occurred.

```text
R5 status:                  R5_ATTRIBUTION_COMPLETE
Attribution ID:             b918a2102f82670da9fbd365daa9b35d7ec86d5bfb043db149b412f57b25f083
Manifest ID:                f5569cca5cafe8f4b598a8e4a9e1609fcefc70f89cc90078d21c8f5c0dabc917
Output inventory:           7fcde0786d367adb0dafbe9fe54349005e69d6cc33f14407477bee534a38d31e
Files / members:            3 / 2
Unresolved evidence:        0
Bundle timestamp:           2026-07-26T12:35:42+0530
```

Protected R4 binding:

```text
R4 diagnostic:              f4a95e118d52eec9ae60b447f08ca11a756908d7861772978b8f0393b0bbd2e2
R4 manifest:                965b4741ec0f7305b8217dbc90d5c2bb31a6185e09b42c519bc404548c290a7e
R4 inventory:               7fbd19fd1b828c09881df6236d2c3b8bdf7ae4bdfd4cd4b03d770c401ecd413c
Source before/after:        identical
```

Provenance treatment:

```text
R5_CANONICAL_EVIDENCE:      ACCEPTED_BY_SOURCE_BACKED_VERIFICATION
R5_EXECUTION_PROVENANCE:    PREEXISTING_AT_AUTHORISED_PREFLIGHT
R5_AUTHORISED_EXECUTION:    NOT_PERFORMED
R5_RERUN:                   NOT_REQUIRED_AND_PROHIBITED
```

## Validation

```text
Focused R5 tests: 33 passed
Ruff:             passed
Compileall:       passed
Diff check:       passed
```

Broader validation command and result:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/scripts/test_trendline_v2_joint_structural_compression.py \
  tests/scripts/test_trendline_v2_causal_structural_reachability.py \
  tests/scripts/test_trendline_v2_reachability_asymmetry_attribution.py \
  -q -ra
```

Result: 186 passed.

## Boundaries preserved

```text
R5 canonical execution:       pre-existing bundle accepted; not performed here
R4/R3B rerun:                 not run
Provider/network/SUI:         not accessed by R5
Holdout/temporal:             not accessed by R5
Runtime/YAML/viewer:          unchanged
Commit:                       authorised for four R5 files
Merge/push:                   not performed
```

## Closeout

R5 implementation and evidence closeout complete. Next phase is model-local
TVLC diagnostic viewer work on a new branch.

R5_COMPLETE
