# Coder Handoff: Trendline V2 Phase 9B.1 Birth Evidence

## 1. Status

```text
READY_FOR_ORCHESTRATOR_REVIEW
PHASE_9B1: COMPLETE
PHASE_9B1_REMEDIATION: COMPLETE
QUALITY_SCORE_SELECTION: NOT_AUTHORIZED
ELIGIBILITY_RULE_SELECTION: NOT_AUTHORIZED
PARAMETER_PROMOTION: NOT_AUTHORIZED
TRACKER_START: NOT_AUTHORIZED
COMMIT: NOT_AUTHORIZED
```

Branch:

```text
research/trendline-v2-phase-9b1-birth-evidence-v1
```

Base and current code base commit:

```text
1393da8ce7ca1127dafdf25a4df73e38c3beb894
```

The branch is not committed. The only working-tree paths are the two study
files and this handoff.

## 2. Changed Files

```text
scripts/analyze_trendline_v2_candidate_birth_evidence.py
tests/scripts/test_trendline_v2_candidate_birth_evidence.py
plans/coder-to-orchestrator-trendline-v2-phase-9b1-birth-evidence-v1.md
```

No model, provider, viewer, configuration, YAML, runtime, tracking,
interaction, MTF, RegimeV2 or legacy trendline file was changed.

## 3. Verified Sources

Phase 8V.1 source:

```text
/tmp/trendline_v2_real_asset_smoke/btcusdt_4h_20250801_20251201
source_identity: 079b7cec1dde131fb91180ee910cdb84499d27bb4ac64cd1ca46eaf355fc0358
files: 4
bytes: 6226334
canonical inventory sha256: 982ea7b1f269e7d0c3a40f4f3b8dd4fa01f8f43a80e081743da1fa37e18c6022
provider_result.json: 6f15a2fc192e61a47c365509fa824cb11834161d6ee9b1c5a352f6ca816d5175
run_report.json: 930556fc624fc34a91c7037c4229201e6e91f303af3fc3fb555f4759d545ded9
viewer_bundle/chart_payload.json: bbb70f72df93631914126dc0759a6d61125814cef25ac033a931f01570a355a9
viewer_bundle/manifest.json: b344650a223f52b87b556ea2fbd102998ce05257316aff2c76eb68e99349dff5
```

The chart payload hash above is the persisted source hash. The required
viewer payload and bundle IDs are bound in the source audit:

```text
viewer payload ID: 9c1c42bf89eaa85c33af4a4787beabd5f1ce3e0c26fe02babe0bb82ab4cc2e51
viewer bundle ID: d56fc53daa4e6c69b189c5ebb72c46f87f67f23056238765106e21c3a3bc41c3
```

Phase 9A source:

```text
/tmp/trendline_v2_phase9a_density/btcusdt_4h_20250801_20251201
phase9a study ID: 8b8ea045a5e14293224250602024a3234b91e023fbac4f70e0011d6c914f1f46
phase9a matrix ID: a19a6bbee86f57a5c28bc67db33398d043f161ddc4bbe1403b4898788a8c19f6
phase9a decision ID: 587712c9a36228161f80c63a4fdcb5bc40403ff2de83c7e144eb849839080089
files: 32 (28 run records)
bytes: 112683
canonical inventory sha256: 296eb1770da76189e184eca902c4ff3c3aa979b34fd987786e18333ca4cf7fed
source_audit.json: 852a2aef65d56c204a97a33e859b38e815f7517e26082ec5171abe734a96a2f5
matrix.json: 79e19e11138b3e2fe0f4160ab72c77d3f377e499f0c4a6680a0f644e8fc0a8c9
decision.json: 11d267e9970c0914aacf112c686f0bf7bf59ad76cbd47f626b8e95859493d64b
```

The superseded Phase 9A directory was not read. The validator required the
corrected close-boundary policy, exact 28 run records, fixed identities,
canonical JSON, exact inventory digest and absence of
`candidate_id_persistence_ratio`.

## 4. Population and Causality

The persisted baseline was consumed without `discover_trendlines` execution:

```text
confirmed source rows: 732
provider candidates: 2697
provider evidence records: 2697
support candidates: 1501
resistance candidates: 1196
Phase 9B.1 provider executions: 0
Phase 9B.1 network requests: 0
```

For every candidate, availability is:

```text
last_confirmation_position = max(evidence.confirmation_positions)
confirmation_bar_open = source timestamp at that position
candidate_available_at = confirmation_bar_open + 4 hours
availability_position = last_confirmation_position + 1
```

Birth descriptors use positions before `availability_position`. Forward
evaluation starts at `availability_position`. The source population split by
availability was:

```text
early (< 2025-10-01T00:00:00Z): 1088
late  (>= 2025-10-01T00:00:00Z): 1609
```

## 5. Feature Contract

The script independently reconstructs left-strict/right-nonstrict extrema
with `left=1` and `right=1`, including adversarial plateau tests. It records:

```text
candidate_id
candidate_structure_id
role and anchor IDs
anchor span in bars and seconds
anchor price change and slope in basis points
same-role confirmed extrema between anchors
same-role skip count and bucket
minimum/median/maximum exact body clearance in basis points
first/second/minimum/mean anchor prominence in basis points
```

The structure fingerprint is explicitly research-only and excludes
`observed_at`. Persisted candidate IDs remain separate.

Fixed exact-side continuation labels were evaluated at 6, 12 and 24 bars.
They contain only contact, exact body-side violation, survival, conjunction
and first-offset fields. No bounce, rejection, breakout, breakdown, retest,
role-reversal or trading label was introduced.

Evaluation support:

```text
6 bars:  2687 evaluated, 10 unevaluated (early 1088, late 1599)
12 bars: 2675 evaluated, 22 unevaluated (early 1088, late 1587)
24 bars: 2600 evaluated, 97 unevaluated (early 1088, late 1512)
```

## 6. Cohorts and Associations

`cohort_summary.csv` contains role, chronological segment, anchor-span bucket
and same-role skip bucket rows for every fixed horizon. Empty cohorts are
represented by zero-count/null metric rows; the verified BTCUSDT 4h source
happened to have no empty generated cohort rows.

All seven declared birth descriptors were classified:

```text
CAUSAL_NONDEGENERATE
```

The association report contains per role/segment/horizon statistics and
tie-aware deterministic Spearman values for `survives_exact_side` and
`contact_and_survives_exact_side`. No p-value gate, sign rule, feature
combination, threshold, ranking or selection was applied. Undefined
associations remain explicit null/reason fields; no undefined group occurred
for this source population.

## 7. Generated Artifacts

Output root:

```text
/tmp/trendline_v2_phase9b1_birth_evidence/btcusdt_4h_20250801_20251201/
```

The prior bundle was moved unchanged before regeneration:

```text
/tmp/trendline_v2_phase9b1_birth_evidence_superseded/
  btcusdt_4h_20250801_20251201_pre_remediation/
old manifest SHA-256: bcbaac939fe15fcf04a0938d7f753cfdd536108b504e53f5d520cec83c2683b1
```

The canonical root contains exactly seven regenerated files. The manifest is
canonical, atomic, content-addressed and binds all six data files by path,
byte length and SHA-256. `source_audit.json` now persists pre/post inventory
digests and `source_immutability_verified`.

```text
source_audit.json       3e7008d739cdcd3b948a8801283c3538c47f8483bc27d2b1683e6ad29df8b2b7
feature_contract.json   224023d466c2b131c8bde05a448796819bedaf44a9c7754e3e091962ab341545
candidate_records.json  924c28bf44c0d5f7affee9a3136582bd6881ea0482875931ce40943d29dcd282
cohort_summary.csv      56d6f6aee611f72f93c66e75490f39abe07ed388868f29a2123f4f876f8c4291
feature_associations.json 38c0c94a813526604bc81514c82f74a69235612a5b17f074b95697bebd75ac63
decision.json           eed4b28c9e23319f65f301cbe079de4e4a9a25059eef47ec98eddb7f64b12104
manifest.json           0c2030da8e80cca3bb2d439e4e072a323ddd274a5ebc47a69a98e276798707e9
```

Study ID:

```text
91604d9404fba7769380d8566d38192b20c987eac990d24733b87506acdd512f
```

Manifest ID:

```text
630481cbb07def66e08e6e1f4256c885a7d5f59b044efcba94eb2ca8783fbef4
```

Independent reload verified canonical JSON, exact member set, member hashes,
manifest ID, source IDs, Phase 9A IDs, exact pre/post inventory fields, 2697
sorted records, role counts, availability arithmetic, horizon-null semantics,
zero execution counts and decision boundary fields.

## 8. Immutability and Scope

Runner computes exact recursive inventories before analysis, requires canonical
JSON in both source trees, compares both digests with fixed approved values,
rechecks both trees after output writes and refuses changed inputs. The source
audit stores:

```text
source_inventory_sha256
phase9a_inventory_sha256
post_run_source_inventory_sha256
post_run_phase9a_inventory_sha256
source_immutability_verified: true
```

The script refuses an existing output root, uses atomic writes and never writes
under either source root. Generated output is outside Git and no artifact was
staged. Superseded pre-remediation files remain byte-identical.

No network adapter, provider, evaluator, holdout, model, viewer, runtime,
configuration, YAML, tracker, interaction, MTF or Regime path was called or
modified. The source run report records its historical Phase 8V.1 request, but
the Phase 9B.1 execution count is zero.

## 9. Validation

```text
Hermetic birth-evidence tests:                17 passed, 1 explicit skip
Opt-in external evidence tests:               18 passed
Viewer + Trendline V2 suites:                135 passed
Protected Trendline Family suite:            400 passed
Provider benchmark harness:                    4 passed
Frontend npm ci:                               0 vulnerabilities
Frontend npm test/build:                      13 passed
Ruff:                                         passed
compileall:                                   passed
git diff --check:                             passed
Independent artifact verification:           passed
```

Codebase-memory reindex was attempted once and completed with non-zero indexes:

```text
flipperAgent-src:       22619 nodes / 117225 edges
flipperAgent-tests:      5435 nodes / 22821 edges
flipperAgent-conductor:   196 nodes /   981 edges
flipperAgent-scripts:     922 nodes /  3963 edges
flipperAgent-docs:        433 nodes /   431 edges
flipperAgent-plans:      5182 nodes /  5173 edges
```

GitNexus also completed with `47719` nodes and `78885` edges, but its reported
branch metadata is stale (`feature/trendline-v2-phase-8-api-v1`) and is not used
as approval evidence.

## 10. Limitations and Boundary

This is one BTCUSDT 4h historical source window and descriptive structural
evidence only. Chronological segments are not validation or holdout splits.
The structure fingerprint is not a model, tracking or runtime identity. Candidate
records share anchors and overlapping geometry. Cohort rates and Spearman
associations are candidate-weighted descriptive evidence, not independent-
sample or inferential evidence. No feature is declared predictive, useful for
trading, selected for filtering or promoted to configuration.

The next possible boundary is Phase 9B.2 predeclared eligibility-family
comparison, subject to independent approval. This handoff does not authorize
that work.
