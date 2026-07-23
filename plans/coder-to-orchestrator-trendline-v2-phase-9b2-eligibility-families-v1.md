# Coder Handoff: Trendline V2 Phase 9B.2 Eligibility Families

## 1. Status

```text
READY_FOR_ORCHESTRATOR_REVIEW
PHASE_9B2: COMPLETE
ELIGIBILITY_FAMILY_SELECTION: NOT_AUTHORIZED
CANONICAL_FILTER_IMPLEMENTATION: NOT_AUTHORIZED
QUALITY_SCORE_SELECTION: NOT_AUTHORIZED
PARAMETER_PROMOTION: NOT_AUTHORIZED
TRACKER_START: NOT_AUTHORIZED
PHASE_9C_START: NOT_AUTHORIZED
COMMIT: NOT_AUTHORIZED
```

Branch:

```text
research/trendline-v2-phase-9b2-eligibility-families-v1
```

Base commit:

```text
b9f4253a84179d7765a2bf4a923e5868b5b076aa
```

## 2. Changed Files

```text
scripts/analyze_trendline_v2_candidate_eligibility_families.py
tests/scripts/test_trendline_v2_candidate_eligibility_families.py
plans/coder-to-orchestrator-trendline-v2-phase-9b2-eligibility-families-v1.md
```

No `src/`, provider, viewer, configuration, YAML, runtime, tracker, MTF,
Regime, signal, selection or legacy trendline file changed.

## 3. Verified Phase 9B.1 Source

```text
Root:
/private/tmp/trendline_v2_phase9b1_birth_evidence/
  btcusdt_4h_20250801_20251201/

Phase 9B.1 study ID:
91604d9404fba7769380d8566d38192b20c987eac990d24733b87506acdd512f

Phase 9B.1 manifest ID:
630481cbb07def66e08e6e1f4256c885a7d5f59b044efcba94eb2ca8783fbef4

Recursive inventory SHA-256:
a6c4ff28f05614a048099d83dbedc612e5d13192762d2f9c5c948564aac8d016

Source identity:
079b7cec1dde131fb91180ee910cdb84499d27bb4ac64cd1ca46eaf355fc0358

Candidates: 2697
Support: 1501
Resistance: 1196
Second-anchor groups: 321
Source rows: 732
```

Validation required exact seven-member inventory, canonical JSON, approved
member hashes, manifest hash, descriptive-only Phase 9B.1 decision fields,
zero provider executions and zero network requests. Superseded Phase 9B.1
root was not read.

## 4. Family Contract

Selector contract ID:

```text
1b19f356e186b5fa6ee802e7b738ca06edd7fccdf65c768841911f5a10bc3eb1
```

Allowed selector fields are exactly:

```text
candidate_id
candidate_structure_id
role
first_anchor_id
second_anchor_id
first_anchor_time
second_anchor_time
same_role_extrema_skip_count
minimum_body_clearance_bps
minimum_anchor_prominence_bps
```

Forward evaluations are read only after membership freezes. No outcome field,
threshold, score or composite quality value enters selection.

Families compared:

```text
all_candidates_control_v1
adjacent_extrema_only_v1
skip_le_1_v1
skip_le_3_v1
latest_valid_predecessor_v1
earliest_valid_predecessor_v1
max_minimum_body_clearance_v1
max_minimum_anchor_prominence_v1
```

## 5. Membership and Density

```text
family                                      count  fraction  support  resist  early  late  groups
all_candidates_control_v1                   2697  1.000000     1501    1196   1088  1609     321
adjacent_extrema_only_v1                     303  0.112347      147     156    150   153     303
skip_le_1_v1                                 527  0.195402      259     268    263   264     314
skip_le_3_v1                                 827  0.306637      406     421    408   419     319
latest_valid_predecessor_v1                  321  0.119021      153     168    160   161     321
earliest_valid_predecessor_v1                321  0.119021      153     168    160   161     321
max_minimum_body_clearance_v1                321  0.119021      153     168    160   161     321
max_minimum_anchor_prominence_v1             321  0.119021      153     168    160   161     321
```

F1/F2/F3 nested membership verified. F4-F7 contain exactly one candidate per
nonempty `(role, second_anchor_id)` group. All families contain both roles and
both chronological segments. Candidate IDs remain persisted observation IDs;
no cross-window identity was invented.

Admission burst and finite anchor-to-anchor overlap summaries:

```text
family                                      burst median/p95/max  overlap median/p95/max
all_candidates_control_v1                         5/26/59             424.5/519/544
adjacent_extrema_only_v1                           1/2/2                 2/3/4
skip_le_1_v1                                       2/3/4                 5/8/10
skip_le_3_v1                                       3/4/8               11/17/23
latest_valid_predecessor_v1                        1/2/2                 2/4/5
earliest_valid_predecessor_v1                      1/2/2               36/60/68
max_minimum_body_clearance_v1                      1/2/2               16/28/34
max_minimum_anchor_prominence_v1                   1/2/2               20/35/41
```

Burst uses `candidate_available_at`. Overlap uses inclusive finite source
position intervals from first anchor through second anchor only. It is not
live active-family density.

## 6. Outcome Evidence

Full candidate-weighted and second-anchor-group-weighted results are in
`outcome_summary.json`; role/segment/horizon rows are in `family_summary.csv`.
Representative aggregate 12-bar results:

```text
family                                      candidate contact/survive/both   group contact/survive/both
all_candidates_control_v1                   .630654/.482243/.126355          .681946/.343249/.094327
adjacent_extrema_only_v1                    .558528/.458194/.073579          .558528/.458194/.073579
skip_le_1_v1                                .575000/.461538/.086538          .585484/.430645/.083871
skip_le_3_v1                                .580882/.470588/.089461          .612963/.403704/.087037
latest_valid_predecessor_v1                 .561514/.454259/.075710          .561514/.454259/.075710
earliest_valid_predecessor_v1               .763407/.249211/.094637          .763407/.249211/.094637
max_minimum_body_clearance_v1               .716088/.261830/.066246          .716088/.261830/.066246
max_minimum_anchor_prominence_v1            .700315/.324921/.100946          .700315/.324921/.100946
```

Candidate-weighted rows retain the candidate medians
`median_future_contact_count` and `median_future_body_violation_count`.
Second-anchor-group-weighted rows instead expose
`mean_of_group_mean_future_contact_count` and
`mean_of_group_mean_future_body_violation_count`: each is the mean across
groups of that group's mean over horizon-eligible candidates. They are not
group medians.

For every family, role, horizon and weighting method, `outcome_summary.json`
and the decision carry late-minus-early deltas for candidate count, unique
second-anchor-group count, evaluation availability, contact, exact-side
survival and contact-and-survival. Weighting-specific future-count deltas are
also present. If an early or late metric is undefined, its value is the typed
object `{"value": null, "reason": "early_or_late_metric_undefined"}`.
`family_summary.csv` carries the same delta columns for reviewer filtering.

Values are descriptive rates, not inferential evidence. One-per-anchor
families normally have equal candidate/group weighting because each group has
one member. Role/segment splits remain separate and are not combined into a
decision.

## 7. Overlap and Architecture

Required containment verified:

```text
F1 in F2: intersection 303 / union 527 / left containment 1.0
F2 in F3: intersection 527 / union 827 / left containment 1.0
F3 in F0: intersection 827 / union 2697 / left containment 1.0
```

Complete pairwise Jaccard, union and left/right containment matrix is in
`overlap_matrix.json`.

Every family classified:

```text
ARCHITECTURALLY_VALID_FOR_FRESH_SCOPE_STUDY
```

Classification used architecture only: declared birth fields, deterministic
repeat, control subset, one-per-group cardinality where applicable, role
coverage and segment coverage. Continuation rates did not determine validity.

## 8. Generated Artifacts

Output root:

```text
/private/tmp/trendline_v2_phase9b2_eligibility_families/
  btcusdt_4h_20250801_20251201/
```

```text
source_audit.json       a831e7a7eb93fcef513dbfd651aae205e758144d96dd5974e904876d687a02c4
family_contract.json    f0aa2189fde90c7b5e4c52cf03f3d24c46c23d2ae24859c12625b1b381a15989
family_membership.json  9ad7a154ece23158364a4d0e8af0679e26847890a464c430ae74d142ed7ff1df
family_summary.csv      b4f6d6d5eb3d20e01f54ec1422d309ba2f7c7d65c41b4548b9e76e484c3d0522
outcome_summary.json    04f996aaa9f2b2b1152516e7f3bbf0b961ca59af8e004a804c5188eb0c8b0c7a
overlap_matrix.json     ad351a80bb00c42bd4686549e65fb33fd78551028bc428435821ff6419c70459
decision.json           46e5d06b34a1852376ca654a540ca9191b1400566cf7c10b1cca33d8d272af00
manifest.json           929e192d0aade5efddd2204592d3af07f9aa6ecf08218e3f92ab862f1d7836b4
```

Corrected eight-file output inventory SHA-256:

```text
748cfcd0904088eba52d2c90295e48d056e0d9a80de23319d48c3266dd5150dd
```

Decision ID:

```text
e3f251d78692fba91879b0f215fe57577e793ee6c1b6eab67cdc19e3ea212d69
```

Manifest ID (deterministic semantic ID):

```text
c50c7849352eb830dca32ffaaf03c19270c4bbe4d969ebbba1e43aa18b1d1174
```

The `manifest.json` file SHA-256 is `929e192d0aade5efddd2204592d3af07f9aa6ecf08218e3f92ab862f1d7836b4`;
the `decision.json` file SHA-256 is
`46e5d06b34a1852376ca654a540ca9191b1400566cf7c10b1cca33d8d272af00`.
Manifest validates content-addressed member hashes and its deterministic
semantic ID. JSON is canonical; writes are atomic; output root refuses
overwrite.

## 9. Immutability and Scope

Source inventory before and after study:

```text
a6c4ff28f05614a048099d83dbedc612e5d13192762d2f9c5c948564aac8d016
```

`source_immutability_verified = true`. Independent post-run reload verified
source inventory, output member hashes, output manifest ID, exact family
counts, unique membership IDs and architecture classifications. A final
source inventory check also ran after the manifest write; a dedicated test
mutates the source during that boundary and requires rejection.

The pre-remediation canonical bundle is preserved unchanged at:

```text
/private/tmp/trendline_v2_phase9b2_eligibility_families_superseded/
  btcusdt_4h_20250801_20251201_pre_reporting_remediation/
```

Its eight-file inventory digest is
`865399987eb2d04d4ed7f03a8989619205e1bf436b328ea212df3e65ccb5d080`.

Provider executions: `0`. Network requests: `0`.

No provider, evaluator, holdout, model, viewer, YAML, runtime, tracker, MTF,
Regime or old trendline path was called or changed. No output artifact entered
Git.

## 10. Validation

```text
Hermetic Phase 9B.2 tests:             16 passed, 1 skipped
Opt-in real-evidence tests:            17 passed (run twice)
Viewer + Trendline V2 suites:         135 passed
Protected Trendline Family suite:     400 passed
Provider benchmark harness:             4 passed
Frontend npm ci:                        0 vulnerabilities
Frontend npm test/build:               13 passed
Ruff:                                  passed
compileall:                            passed
git diff --check:                      passed
Independent artifact verification:     passed
```

External test is skipped unless
`TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE=1` is set. Normal tests use only
temporary synthetic source bundles. The opt-in test writes two temporary
recomputations, compares them deterministically, and compares them
read-only with the canonical bundle when it exists; it never deletes or
overwrites canonical evidence.

## 11. Limitations and Decision Boundary

The source is one exploratory BTCUSDT 4h window. Families were defined after
reviewing Phase 9B.1 architecture evidence. Outcome summaries are descriptive,
candidate-dependent, and unsuitable for selecting a production eligibility
rule without fresh cross-asset/timeframe evidence.

Candidate records share anchors and overlapping geometry. Candidate-weighted
and second-anchor-group-weighted rates are not independent-sample or inferential
evidence. No family was selected, promoted, recommended, or implemented as a
runtime filter.

Phase 9C fresh cross-asset/timeframe validation remains next possible scope,
not authorized by this handoff.
