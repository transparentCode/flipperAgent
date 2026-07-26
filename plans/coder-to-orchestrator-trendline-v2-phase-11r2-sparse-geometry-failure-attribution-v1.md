# Coder to Orchestrator: Trendline V2 Phase 11R.2

## Status

`READY_FOR_CONTRACT_FREEZE_REVIEW`

No attribution study was executed or published. Read-only BTC/ETH derivation
was used only for remediation validation. No provider, network, holdout,
temporal, legacy-model, runtime, YAML, or Phase 11B path was opened.

## Branch and scope

```text
branch: research/trendline-v2-phase-11r2-failure-attribution-v1
base:   f99997c10b83082b3d3ce8de6b82f8add0996a71
files:  exactly 3 new files
```

```text
scripts/analyze_trendline_v2_sparse_geometry_failure_attribution.py
tests/scripts/test_trendline_v2_sparse_geometry_failure_attribution.py
plans/coder-to-orchestrator-trendline-v2-phase-11r2-sparse-geometry-failure-attribution-v1.md
```

No source-model, config, Phase 11R.1, or artifact file changed.

## Contract freeze

Top-level payload sections are exactly:

```text
schema_version
base_commit
phase11r1_dependency
sources
independence
targets
seed_funnel
theil_sen_attrition
churn_attribution
inversion_attribution
survival_regret
reconciliation
artifacts
execution_accounting
decision_statuses
study_controls
```

Derived contract triplet:

```text
namespace: trendline_v2_phase11r2_sparse_geometry_failure_attribution_contract
contract_id: d3a52e28ce11ffb86bb05aff826ce48ad11b9035c6796e9e938a616463686089
canonical_json_byte_length: 8504
canonical_json_sha256: 359549fc158b0785f55c49e949f15780be912ca1097b62b96a5d4b14c96d20a1
```

Identity is derived from `_contract_payload()` and checked during validation,
not accepted as an opaque input.

Execution binds Phase 11R.1 commit as an ancestor of the active branch, then
requires exact Phase 11R.1 script Git blob and SHA-256 identity. This preserves
the dependency after the Phase 11R.2 freeze commit.

## Frozen dependencies and sources

```text
Phase 11R.1 base commit: f99997c10b83082b3d3ce8de6b82f8add0996a71
Phase 11R.1 script blob: 102159f511f0a2d0598a521cf7ee42aa1cfaf64b
Phase 11R.1 script SHA:  47d4b43ce556789b7992da3777356a05682ac5165b759c4b74682f89c808ee48
Phase 11R.1 contract:    3bcad03fdd5df8b3af6754bdb38b0436cc93528964298607dd1169950cc312d3
Phase 11R.1 decision:    a06d0ca3a7a08b89db7a065133d5c30eeaa51800172187f4b75e7146e21e29fa
Phase 11R.1 manifest:    6393883d533a6b56eb2abfb7b1402bee6eb75cfb366f59e942b7e44bb128ab32
Phase 11R.1 inventory:   17cf5aa6f70b58a21fe436ca63a98f88ab6356250de13befa94100ac96c4ae50
Validation lock:         ef381809b4d0155c625be28e752786099272910d7633a9c0d29101b8a2f81815
```

Allowed raw inputs are exactly four BTC/ETH validation `provider_result.json`
files. Their bound four-file inventory is:

```text
2f2db301ca6c9c355bb4d645bb2d631836749748835c0419573e7cf52d27de27
```

Phase 9C.2 bindings remain:

```text
decision:         4b734cbf99e1453bccdedb95f397f4b34e020f29e3d18808a131456647f78f7c
manifest:         beab5b9acb2bfc3c25ba9cb5cb31c33c1a31e6069c1d7906f3ed5e1c2d798c81
output inventory: ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532
source inventory: 631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be
```

SUI raw files and `/tmp/trendline_v2_phase10c2_lookback_eviction/` are
explicitly rejected. Existing output roots are refused before source access.

## Attribution implementation

Implemented, guarded for future execution:

- exact sequential seed funnel with exclusive first-failure labels and final
  seed-set identity matching Phase 11R.1;
- Theil-Sen initial/final inlier, span, breach, projection, distance,
  deduplication and ranking attribution;
- hierarchical and Theil replacement origin recovery with fail-closed
  ambiguity handling;
- rank displacement and same-origin geometry evidence;
- all eligible support/resistance inversion combinations and deterministic
  closest non-inverted tie ordering;
- matched `(checkpoint_index, role)` 48h/96h survival-regret records,
  signed geometry differences, and Phase 11R.1 metric reconciliation;
- exact 24-file future inventory: 23 manifest members plus `manifest.json`;
- canonical JSON, content-addressed IDs, staging cleanup, and atomic directory
  publication.

Remediation controls:

- Phase 11R.1 verification is scope-limited. Persisted Phase 11R.1 SUI
  placeholders may be read; Phase 9C.2 raw SUI and Phase 10C.2 temporal roots
  are never opened or hashed.
- Every ordered pair has a content-addressed evaluation record, including
  failed pairs and source/input identity.
- Churn uses exact pair failure stages and persists pair lineage/evaluation,
  passed stages, rank vectors, candidate-set IDs and deduplication evidence.
- Theil emits only contract labels: `CANDIDATE_AVAILABLE` with rank/selected
  fields, exact terminal failure labels, or explicit deduplication labels.
- Inversion requires rank-one selected roles, stores all combination
  projections, and reconciles per-provider counts with Phase 11R.1 metrics.
- One pure `_derive_attribution` path feeds generation and semantic
  verification. The verifier compares every JSON/CSV byte, decision, source
  audit, manifest and 24-path inventory.
- Source audit persists before/after hashes for Phase 11R.1 bundle inventory,
  four-file BTC/ETH raw inventory and Phase 11R.1 script SHA; any drift blocks.

Thresholds remain Phase 11R.1 values: 96h span, 0.35 ATR touch, 0.5 ATR
two-bar breach, positive projection, and 8 ATR distance. No tuning or new
provider exists.

## Execution accounting contract

```text
datasets:                         4
checkpoints:                     88
derivation repeats:               2
attribution checkpoint rebuilds: 176
Phase 11R.1 bundle verifications: 1
source immutability snapshots:    2 (before/after semantic snapshots)
SUI accesses:                     0
temporal accesses:                0
network requests:                 0
legacy executions:                0
runtime V2 provider executions:   0
```

Future CLI requires both `--execute-attribution` and
`TRENDLINE_V2_ALLOW_PHASE11R2_ATTRIBUTION=1`. `--verify` does not require the
environment guard. Execution was not run in this phase.

## Validation

```text
Phase 11R.2 freeze tests: 117 passed, 4 expected skips
Ruff:                    passed
compileall:              passed
```

Phase 11R.1 scope-limited verifier passed:

```text
study_status:             NO_INDEPENDENT_SPARSE_PROVIDER_FINALIST
decision_id:              a06d0ca3a7a08b89db7a065133d5c30eeaa51800172187f4b75e7146e21e29fa
manifest_id:              6393883d533a6b56eb2abfb7b1402bee6eb75cfb366f59e942b7e44bb128ab32
output_inventory_sha256:  17cf5aa6f70b58a21fe436ca63a98f88ab6356250de13befa94100ac96c4ae50
provider/network calls:   0 / 0
```

Read-only canonical BTC/ETH derivation passed without publication:

```text
coverage cases:            52
replacement records:      107
inversion cases:             2
unresolved cases:            0
Phase 11R.1 raw SUI reads:   0
temporal reads:              0
provider/network calls:      0 / 0
```

Source immutability snapshots matched:

```text
Phase 11R.1 member inventory before/after: 17cf5aa6f70b58a21fe436ca63a98f88ab6356250de13befa94100ac96c4ae50
Allowed BTC/ETH raw inventory before/after: 2f2db301ca6c9c355bb4d645bb2d631836749748835c0419573e7cf52d27de27
Phase 11R.1 script SHA before/after:         47d4b43ce556789b7992da3777356a05682ac5165b759c4b74682f89c808ee48
```

External boundary tests include a path-read spy and a guard proving the full
Phase 11R.1 verifier is not called. Semantic copied-bundle adversarial tests
are present and remain skipped until a canonical Phase 11R.2 bundle is
authorized and exists.

## Mandatory review package

1. Work completed: scope-limited Phase 11R.1 verification, causal attribution
   rederivation, pair/churn/Theil/inversion/survival hardening, source
   before/after binding, semantic bundle verification and adversarial tests.
2. Files changed: exactly the three files listed above. No generated evidence
   or source artifact changed.
3. Architecture decisions: persisted Phase 11R.1 SUI placeholders are allowed
   evidence reads; Phase 9C.2 raw SUI and Phase 10C.2 temporal reads are hard
   forbidden. Generation and verification share `_derive_attribution`.
4. Config impact: none. No YAML, provider, runtime, model, holdout, temporal,
   or Phase 11B configuration changed.
5. Validation: 117 hermetic tests passed with 4 expected skips; 3 external
   boundary tests passed; 1 canonical read-only attribution test passed;
   Ruff, compileall and contract-triplet checks passed.
6. Architecture drift checklist:
   - old trendline imports: absent;
   - full Phase 11R.1 verifier call: absent from runtime path;
   - Phase 9C.2 raw SUI reads: zero by path spy;
   - Phase 10C.2 temporal reads: zero by path spy;
   - provider/network execution: zero;
   - output root: absent;
   - unrelated files: unchanged.
7. Known gaps: semantic copied-bundle tests require an authorized generated
   Phase 11R.2 bundle and therefore remain skipped; codebase-memory reindex
   worker continues to crash on a contained file.
8. Next phase: independent contract-freeze review. Do not execute attribution,
   publish evidence, commit, merge or push.

One codebase-memory reindex was attempted and its worker crashed on a file;
the crash was contained. No generated Phase 11R.2 evidence exists and nothing
is staged.

## Next decision

Independent review should validate exact payload triplet, dependency
identities, source allowlist, semantic derivation and no-execution boundary.
Attribution execution requires separate authorization after contract freeze
review. Phase 11R.2 output root remains absent; no commit is authorized.
