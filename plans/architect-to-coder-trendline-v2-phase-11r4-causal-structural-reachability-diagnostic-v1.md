# Architect to Coder: Trendline V2 Phase 11R.4 Reachability Diagnostic

## Status

`READY_FOR_R4_IMPLEMENTATION`

Original Phase 11R.3B bundle is superseded by reviewed temporal-v2 evidence.
Contract approved for bounded implementation. It does not authorize canonical
study execution, artifact publication, provider execution, network access,
holdout access, temporal access, or production changes.

## R3B temporal supersession

- Evidence status: `TEMPORAL_V2_APPROVED`
- Finalist: `None`
- Promotion status: `NO_JOINT_STRUCTURAL_COMPRESSION_FINALIST`
- Interpretation: near, tenure, and evidence ordering at budgets 1-3 did not
  preserve required worst-dataset 96h outcomes.
- Rerun required: `Not required`
- Production promotion: `Prohibited`

The original timestamp-only R3B study is not to be regenerated or rewritten.
Its published bundle remains preserved as superseded audit evidence. The
corrected temporal-v2 bundle is separate, reviewed and approved for R4 source
binding.

## Frozen source binding

Phase 11R.4 may proceed to contract review using corrected temporal-v2 R3B
evidence. Its prior source binding is retained only for audit:

```text
/tmp/trendline_v2_phase11r3b_joint_structural_compression/20260522_20260701
```

Superseded R3B identities:

```text
decision_id:          cc0fe7b74684726c12d510b4711654afbef84781c760a9710ab811d9b0121ca4
manifest_id:          50114d67995492cc3e3ec0f0c2cf88c63a50b0bc8689f90d9fdc99a014188c3b
output_inventory:     94c2cbd43c685ddb471c186c9440f3c2cf7febd04d588fc1b23f836903ddef03
R3A inventory:        6335ec5dd2e67bc94f51ae5a1e0c0e265db743ad1aeccb0094ce4507466d2ff0
R1 inventory:         17cf5aa6f70b58a21fe436ca63a98f88ab6356250de13befa94100ac96c4ae50
R2 inventory:         382df2e22cb508d3982eb7e6d9566849dc65eb7316a8ce8c64b9c44d2d6713e4
allowed raw:          2f2db301ca6c9c355bb4d645bb2d631836749748835c0419573e7cf52d27de27
```

Corrected temporal-v2 R3B output is separate and approved for R4 source binding:

```text
root:                  /tmp/trendline_v2_phase11r3b_joint_structural_compression_temporal_v2/20260522_20260701
contract_id:           e99ae58325df06923c83e0732d3a07c77446a32a5aa913d65411518ea4742a52
decision_id:           66240c90f6d7b4c8575caebd1b248dbaa8084819c99504e19c210a0ec0b331ec
validation_lock_id:    27febb38504b51609b3bf70f7f879ce056f16ec2612bf727d33e236ee80ed276
manifest_id:           69ec5869678d136dc366039424ca2912b2940d907524f55ed43b1958e0bccc3e
output_inventory:      658e2649d2c74f5f6cf8e8bfea38efb95c55908766a01a8d8e6a8950c430907c
```

Verifier must require exact source identities and prove source bytes remain
unchanged before and after analysis. Any mismatch aborts without output.
Reading this approved temporal-v2 root is allowed. Reading separate temporal
validation evidence, Phase 10C.2 evidence, holdout, raw SUI or superseded
outcome paths for R4 interpretation is prohibited.

Origin OHLCV/ATR derivation is allowed only from this separate read-only raw
source root:

```text
root: /tmp/trendline_v2_phase9c2_fresh_scope_family_validation/20260522_20260701
aggregate_inventory: 2f2db301ca6c9c355bb4d645bb2d631836749748835c0419573e7cf52d27de27
```

Exactly these four members are allowed, with frozen bytes:

```text
datasets/btcusdt_1h/provider_result.json
  sha256: 39589107f6512af36bf69987a3580668851e3781d4990fd1d7d4ac6f912ff012
  bytes: 5615167
datasets/btcusdt_4h/provider_result.json
  sha256: 0fb88993e8ceed7b3812ec8fed895164b4fd00d1d392f5018f81aeea66dd4fe3
  bytes: 877457
datasets/ethusdt_1h/provider_result.json
  sha256: 547b1818f2df0e1b95190355120960f55ca8379808fa94ce8f3f2ad0b3c5ab35
  bytes: 5509927
datasets/ethusdt_4h/provider_result.json
  sha256: 2b3ccd8316d3119cbf3459d1eb98034124a90e0b20cad661955b1b1bf627087a
  bytes: 938059
```

Every other raw-root member is prohibited. Provider execution, network access
and raw SUI access are prohibited. Record exact raw source snapshots before and
after derivation; any mutation, missing member, extra access or hash mismatch
blocks publication.

## Objective and non-goals

Determine whether the corrected R3B compression failure is concentrated in
causally identifiable geometry-reachability conditions. This is a diagnostic
study, not a selector study.

The study must distinguish:

1. geometry-only lines projected to remain distant at 24h, 48h, or 96h;
2. dataset/timeframe-specific geometry behavior;
3. loss of complementary support/resistance candidates under R3B compression;
4. reachable lines that still lose against their matched controls.

The study must not create, rank, select, tune, or promote a policy finalist. It
must not change R3B membership, selection, outcomes, gates, runtime, YAML,
viewer, provider, tracker, signal, Regime, MTF, or production configuration.

## Frozen diagnostic populations

### Primary actionable population

The primary population is the union of selected actionable rows from exactly:

- `joint_incumbent_near_v1`;
- `joint_incumbent_tenure_v1`;
- `joint_incumbent_evidence_v1`;
- `joint_hash_order_control_v1`;
- `joint_nearest_projection_control_v1`.

Each row is scoped by one policy, budget `1`, `2`, or `3` lines per role,
dataset, checkpoint, semantic role, lineage and horizon. Datasets are exactly
BTCUSDT 1h, BTCUSDT 4h, ETHUSDT 1h and ETHUSDT 4h. Roles are exactly
`support` and `resistance`; checkpoints are the 22 persisted checkpoints per
dataset; horizons are exactly 24h, 48h and 96h.

The canonical candidate observation key is the exact R3B outcome identity:

```text
(
  contender_policy_id,
  budget_per_role,
  derivation_type,
  control_policy_id_or_null,
  dataset_id,
  checkpoint_index,
  semantic_role_at_selection,
  lineage_id,
  horizon_hours
)
```

For contender rows, `contender_policy_id` is `policy_id`,
`derivation_type` is `contender`, and `control_policy_id_or_null` is null. For
matched-control rows, `contender_policy_id` is
`matched_contender_policy_id`, `derivation_type` is `matched_control`, and
`control_policy_id_or_null` is the control `policy_id`. A control row from one
contender comparison must never merge with the same control's row from another
comparison.

Checkpoint-selection joins must bind all of:

```text
matched_contender_policy_id
policy_id
budget_per_role
dataset_id
checkpoint_index
selection_id
```

Duplicate keys within one exact policy/budget/derivation/control derivation are
unresolved and block a positive decision. The same source lineage in separate
policy/control populations is not a duplicate because all R3B identity fields
are part of the population key.

The causal feature row has a separate identity because origin features do not
vary by outcome horizon:

```text
causal_feature_observation_key = (
  contender_policy_id,
  budget_per_role,
  derivation_type,
  control_policy_id_or_null,
  dataset_id,
  checkpoint_index,
  semantic_role_at_selection,
  lineage_id,
  selection_id
)
```

Compute one feature row per unique feature key before horizon expansion. That
row contains all three geometry projections and exactly one prior-history
lookup. It joins to 24h, 48h and 96h outcomes through the full R3B outcome
identity, `selection_id`, lineage, role and checkpoint. A lineage/namespace/
checkpoint may have at most one feature row. Duplicate feature rows are
unresolved; never select one by ordering or overwrite.

### Secondary structural-context population

The secondary lane contains only persisted R3B states
`PERSISTED_DISTANT` and `REVERSED_PERSISTED_DISTANT`, with at most one lineage
per role per dataset/checkpoint under existing R3B selection semantics. It is
independent of actionable budgets, actionable denominators, matched-control
gates and finalist logic.

Its contact, distance and contraction metrics are descriptive only. They cannot
be described as an explanation of actionable compression failure unless the
report proves a direct relationship by exact
`(dataset_id, checkpoint_index, semantic_role, lineage_id)` identity. A shared
dataset or checkpoint alone is not a relationship. No secondary result can
produce a decision or gate input.

## Causal origin-feature contract

Every feature below is derived at the selected row's checkpoint. Future outcome
fields, future bars, persisted outcome files, reaction, contact, breach,
survival and later lifecycle state are prohibited from eligibility, stratum
assignment, support accounting and decision inputs.

`origin_time` is checkpoint `observed_at`, represented in UTC nanoseconds.
`origin_close` and `origin_atr` are the close and ATR of the maximum source bar
satisfying both:

```text
bar_open_timestamp < origin_time
available_at <= origin_time
available_at = bar_open_timestamp + timeframe_interval
```

The ATR is the exact R3B causal Wilder-style recurrence over the source prefix:

```text
TR[0] = high[0] - low[0]

TR[t] = max(
    high[t] - low[t],
    abs(high[t] - close[t - 1]),
    abs(low[t] - close[t - 1]),
)

ATR[0] = TR[0]
ATR[t] = (13 * ATR[t - 1] + TR[t]) / 14
```

The source prefix ends at the origin bar; later rows cannot participate in ATR
calculation. `origin_close` and `origin_atr` come from that same bar and are
frozen at origin. Missing or non-finite values make the row `not_evaluable`; no
imputation is allowed.

For persisted exact geometry with ordered endpoints:

```text
line_value(t) = start_price
               + (t - start_time) / (end_time - start_time)
               * (end_price - start_price)

line_value_at_origin = line_value(origin_time)
initial_distance_atr =
    abs(origin_close - line_value_at_origin) / origin_atr

line_slope_price_per_hour =
    (end_price - start_price)
    / ((end_time - start_time) / 3_600 seconds)

line_slope_atr_per_hour = line_slope_price_per_hour / origin_atr

geometry_projected_distance_atr_H =
    abs(origin_close - line_value(origin_time + H)) / origin_atr
```

`H` is 24h, 48h or 96h. `geometry_projected_distance_atr_H` is a
geometry-only origin-time proxy, not actual future reachability and not a
future-price forecast. It uses no future close, high, low or ATR.

`prior_observed_distance_change_rate` is defined only when a valid earlier
feature row exists in the exact sequence:

```text
(
  contender_policy_id,
  budget_per_role,
  derivation_type,
  control_policy_id_or_null,
  dataset_id,
  lineage_id
)
```

Within that sequence, the previous observation is the maximum checkpoint index
strictly less than current checkpoint. Semantic role is not part of sequence
identity because role transfer is separately recorded. The rate is:

```text
(current_initial_distance_atr - previous_initial_distance_atr)
/ ((current_origin_time - previous_origin_time) / 3_600 seconds)
```

The prior observation uses its own frozen origin close and ATR. A role change is
retained as `role_transfer=true` and reported as a descriptive subgroup. It is
included in primary-stratum membership, paired cells, survival deltas and
decision denominators under its current `semantic_role_at_selection`. The
primary hypothesis uses geometry projection, not this prior-distance feature.
Same-role observations have `role_transfer=false`. No earlier observation means
`not_evaluable`; no later observation may fill it.

Persist for every row: source policy/control identity, dataset/timeframe, role,
checkpoint/origin timestamps, geometry, both slopes, origin close/ATR, initial
distance, prior observation key, prior distance, elapsed hours, change rate,
role-transfer flag, projected distances for all three horizons, and explicit
`evaluable`/`not_evaluable` reasons.

All projected-distance and prior-observation calculations must pass prefix
invariance: appending future source rows cannot change an earlier row's feature
or status.

## One primary hypothesis

Exactly one outcome-tested hypothesis is frozen:

```text
id: H_R4_GEOMETRY_PROJECTED_96H_WITHIN_8_ATR_V1
feature: geometry_projected_distance_atr_96h
criterion: feature <= 8.0
horizon: 96h
comparison: same contender/budget against each R3B matched control
statistic: paired-cell-weighted 96h survival delta
```

The `8.0 ATR` scale is inherited from frozen R3B structural-context metric
`crossed_into_at_most_8_atr`; it is not selected from R4 outcomes. R4's
geometry-only feature is not renamed as that future outcome.

The hypothesis is evaluated for every contender policy, budget, control,
dataset and role in the primary actionable population. A control receives its
own causal feature value; contender membership is never copied onto control
rows. Initial-distance bands `<=4 ATR`, `>4-8 ATR`, `>8-16 ATR`, `>16 ATR`,
24h/48h projected strata and other bands remain secondary descriptive strata.
They cannot independently support the positive decision.

## Minimum-support rule

Support is computed before any outcome join. Counting unit is one unique
candidate observation key. For each contender/budget/control pair, dataset and
role, the primary stratum must have at least one candidate row on each side in
at least one checkpoint cell. All four datasets and both roles are required.

For each 96h pair-cell key:

```text
(contender_policy_id, budget_per_role, control_policy_id,
 dataset_id, checkpoint_index, semantic_role_at_selection, 96)
```

the exact classifications are:

- `eligible_cell`: both unstratified source populations contain rows;
- `paired_cell`: both sides contain at least one primary-stratum row;
- `contender_only_cell`: only contender has primary-stratum rows;
- `control_only_cell`: only control has primary-stratum rows;
- `empty_both_cell`: neither side has primary-stratum rows;
- `duplicate_cell`: duplicate candidate keys on either side;
- `unresolved_cell`: any invalid identity, geometry, origin or reconciliation
  condition.

The fixed minimum is one unique row per side in one paired checkpoint cell for
each required dataset/role lane. One-sided and zero-count cells never satisfy
support and are retained descriptively. Support is required separately for
all 18 contender/budget/control pairs, all four datasets and both roles. This
is an availability/reconciliation floor, not an inferential sample-size claim.
No support count may depend on survival, contact, reaction, breach or any other
future outcome.

If any required lane fails this rule, positive support is unavailable and the
decision is `INSUFFICIENT_REACHABLE_SUPPORT`.

## Within-stratum comparison contract

Comparison unit is a paired cell, not a candidate ID and not the whole 88-cell
set merely because both policies originated there. Pairing key is the full
96h pair-cell key above. A cell is comparable only when both sides have valid,
unique primary-stratum rows and no unresolved membership error.

Before role/horizon stratification, every one of the 18 R3B contender/budget/
control comparisons must independently preserve the frozen R3B source
reconciliation at exactly 88 dataset/checkpoint cells:

```text
(dataset_id, checkpoint_index)
```

Each comparison must have 88 contender cells and 88 matched-control cells, with
zero missing, extra, duplicate or unresolved source cells and exact per-role
selected-count equality. This is the source-population check. It is distinct
from the role/horizon pair-cell reconciliation below; passing 88-cell source
reconciliation does not imply a matched reachability stratum.

For each paired cell and side, calculate the mean of the binary outcome over
that side's rows. Cell delta is contender mean minus control mean. The primary
statistic is the arithmetic mean of cell deltas across paired cells
(`paired-cell-weighted`), with each cell receiving equal weight regardless of
row count. Support and resistance remain separate; they are pooled only after
their lane-level results are independently reconciled.

Every descriptive metric uses this full population namespace and may not pool
matched controls across contenders:

```text
population_namespace = (
  contender_policy_id,
  budget_per_role,
  derivation_type,
  control_policy_id_or_null,
  dataset_id
)
```

In particular, `role_present`, role coverage, one-sided counts, empty counts,
support/resistance balance and compression retention are all keyed by this
namespace. Collapsing `matched_contender_policy_id` or substituting only the
control `policy_id` is invalid and must be rejected.

Persist separate counts for every pair/dataset/role/horizon:

```text
eligible_cells
paired_cells
contender_only_cells
control_only_cells
empty_both_cells
duplicate_cells
unresolved_cells
```

Rows from one selected candidate at 24h, 48h and 96h are separate observations
with horizon in identity; they are never silently pooled as independent
checkpoint observations. Within a policy/budget/control side, duplicate
candidate keys are rejected. Exact source population counts, stratum counts,
side means, paired-cell deltas and denominators are persisted.

Cell classification has one terminal result, with this precedence:

```text
1. unresolved
2. duplicate
3. paired
4. contender_only
5. control_only
6. empty_both
```

`eligible_cell` is a separate source-population boolean/count and is not a
terminal class. Exact status predicate:

```text
MATCHED_WITHIN_STRATUM iff:
  paired_cells >= 1
  contender_only_cells == 0
  control_only_cells == 0
  duplicate_cells == 0
  unresolved_cells == 0
  all source-population accounting identities hold
```

`empty_both_cells` may be non-zero and does not alone prevent matched status.
The report must use `DESCRIPTIVE_UNMATCHED` for any one-sided, duplicate or
unresolved primary-stratum comparison. It must never treat that result as a
gate-equivalent result.

## Denominators and outcome boundary

Keep separate:

- `structural_contact_denominator`: rows with valid causal geometry and a
  structural-context calculation at requested horizon;
- `outcome_contact_denominator`: rows with verified temporal-v2 persisted
  outcome evaluation at requested horizon.

Persist denominator beside every contact rate. Structural context is never used
as an actionable outcome denominator. R3B outcome rows must inherit exactly:

```text
checkpoint < available_at <= checkpoint + horizon
checkpoint <= bar_open < checkpoint + horizon
```

The R4 implementation must not use superseded timestamp-only helpers from R3A
or independent sparse-geometry studies. Actual contact, minimum future
distance, survival, reaction and breach are outcome fields only.

## Decision rules and gate separation

Study integrity status is separate from diagnostic decision:

```text
R4_DIAGNOSTIC_COMPLETE
R4_DIAGNOSTIC_INCOMPLETE
R4_DIAGNOSTIC_BLOCKED
```

`R4_DIAGNOSTIC_INCOMPLETE` is returned when duplicate or unresolved evidence,
source-accounting failure, namespace collapse or a one-sided matched stratum
prevents a complete gate-equivalent comparison. `R4_DIAGNOSTIC_BLOCKED` is
returned when a precondition fails before derivation, including source hash
drift or prohibited source access. Neither status has a diagnostic decision.
Only `R4_DIAGNOSTIC_COMPLETE` with zero duplicate and unresolved evidence may
emit one of the decisions below.

Allowed decisions only:

```text
CLOSE_STRUCTURAL_COMPRESSION_BRANCH
REACHABILITY_ELIGIBILITY_HYPOTHESIS_SUPPORTED
INSUFFICIENT_REACHABLE_SUPPORT
```

`REACHABILITY_ELIGIBILITY_HYPOTHESIS_SUPPORTED` requires, simultaneously:

- primary support passes in every required dataset and both roles for every
  contender/budget/control pair;
- every required comparison is `MATCHED_WITHIN_STRATUM`;
- paired-cell-weighted 96h survival delta is non-negative against both matched
  controls for every required dataset and role;
- support and resistance lane results are both present and consistent;
- no future field affected features, strata or support;
- unresolved evidence and reconciliation counts are zero.

Decision precedence is fixed and fail-closed:

```text
1. Protected-source or execution precondition fails:
   R4_DIAGNOSTIC_BLOCKED; diagnostic_decision = null.

2. Duplicate, unresolved, namespace-collapse or source-accounting evidence:
   R4_DIAGNOSTIC_INCOMPLETE; diagnostic_decision = null.

3. Integrity is valid, but any required dataset/role lane has
   paired_cells == 0:
   R4_DIAGNOSTIC_COMPLETE; INSUFFICIENT_REACHABLE_SUPPORT.

4. Every required lane has paired_cells >= 1, but any required comparison has
   contender_only_cells > 0 or control_only_cells > 0:
   R4_DIAGNOSTIC_INCOMPLETE; diagnostic_decision = null.

5. Every required comparison is MATCHED_WITHIN_STRATUM and every required
   delta is non-negative:
   R4_DIAGNOSTIC_COMPLETE; REACHABILITY_ELIGIBILITY_HYPOTHESIS_SUPPORTED.

6. Every required comparison is MATCHED_WITHIN_STRATUM, support passes, and
   at least one required delta is negative:
   R4_DIAGNOSTIC_COMPLETE; CLOSE_STRUCTURAL_COMPRESSION_BRANCH.
```

`CLOSE_STRUCTURAL_COMPRESSION_BRANCH` therefore requires every comparison to
be `MATCHED_WITHIN_STRATUM`. `DESCRIPTIVE_UNMATCHED` evidence can never emit
branch closure or positive support. Branch closure means only that an
adequately supported and exactly reconciled primary hypothesis failed.

Original R3B promotion gates and R3B worst-dataset 96h survival remain
reference metrics only. R4 does not reapply them to sparse strata, does not
call them R4 gates, and cannot reverse `NO_JOINT_STRUCTURAL_COMPRESSION_FINALIST`.
R4 positive status supports only a later hypothesis contract; it authorizes no
implementation, parameter, YAML, runtime, provider or viewer change.

## Required report surface

Report by dataset, timeframe, role, horizon, policy, budget and control:

- origin feature distributions and not-evaluable counts;
- primary reachable/unreachable counts;
- secondary fixed initial-distance bands and empty strata;
- support/resistance balance;
- candidate and selected-line counts;
- compression retention and complementary-role coverage;
- all denominator fields;
- matched/descriptive status and full reconciliation counts;
- survival, contact, contact-and-survival and reaction descriptive outcomes;
- primary paired-cell deltas and R3B reference metrics;
- secondary structural-context results, with any exact lineage overlap audit.

The report must use these fixed descriptive formulas. Counts use unique R3B
selection rows, not outcome rows duplicated across horizons.

```text
population_namespace = (
    contender_policy_id,
    budget_per_role,
    derivation_type,
    control_policy_id_or_null,
    dataset_id
)

role_present(population_namespace, checkpoint, role) =
    selected actionable row count for role > 0

both_role_coverage(population_namespace) =
    count(checkpoints where support_present and resistance_present) / 22

support_only_count(population_namespace) =
    count(support_present and not resistance_present)

resistance_only_count(population_namespace) =
    count(resistance_present and not support_present)

empty_role_count(population_namespace) =
    count(not support_present and not resistance_present)

support_resistance_balance(population_namespace) = {
    support_count,
    resistance_count,
    support_fraction = support_count / (support_count + resistance_count),
    resistance_fraction = resistance_count / (support_count + resistance_count),
}

compression_retention_numerator(population_namespace, role) =
    unique selected actionable rows in primary 96h stratum

compression_retention_denominator(population_namespace, role) =
    unique selected actionable rows in the same unstratified role population

compression_retention(population_namespace, role) =
    numerator / denominator, or null when denominator == 0
```

All formulas describe the unstratified R3B selected population unless explicitly
marked primary-stratum. `compression_retention` describes primary-stratum
membership among those same namespaced selected rows; it is not a new
compression policy metric and cannot enter a gate. Every zero denominator is
persisted with count `0` and rate `null`. Primary and secondary lanes retain
separate counts.

## Future implementation boundary

Future implementation may add only:

```text
scripts/analyze_trendline_v2_causal_structural_reachability.py
tests/scripts/test_trendline_v2_causal_structural_reachability.py
plans/coder-to-orchestrator-trendline-v2-phase-11r4-causal-structural-reachability-v1.md
```

It must read verified temporal-v2 artifacts through a new read-only boundary;
it must not import or modify the R3B script. No `src/`, configuration, YAML,
viewer, provider, tracker, signal, MTF, Regime or runtime changes are allowed.
Output must be outside protected roots, staged atomically, content-addressed,
and source-inventory bound. No R4 execution is authorized by this document.

## Execution and validation boundary

For any future implementation review: zero provider/network calls, zero raw SUI
reads, zero holdout reads, zero Phase 10C.2 temporal reads, zero legacy
executions, no R3B rewrite, and no production output. The corrected temporal-v2
bundle is read-only and its source inventory must match before and after.

Before any execution request, validate strict temporal-v2 R3B identity and
manifest; verify deterministic ordering/IDs; test future-row prefix invariance;
prove outcome-field mutation cannot alter eligibility; test exact 88-cell source
reconciliation for all 18 comparisons and all stratum classifications; test support, one-sided,
empty, duplicate and unresolved cells; test role/dataset/timeframe separation;
test no-new-policy/budget behavior; and run Ruff, compileall, focused tests and
`git diff --check`.

Required contract tests:

1. Feature rows are unique before horizon expansion.
2. Three outcome horizons join to one feature row.
3. Previous-history lookup cannot choose among horizon duplicates.
4. Matched-control histories remain contender-namespaced.
5. Every descriptive formula preserves full population namespace.
6. Collapsing `matched_contender_policy_id` is rejected.
7. Exact four raw files are accepted.
8. Any extra raw-member access is rejected.
9. Raw-source mutation before or after derivation is rejected.
10. Exact `MATCHED_WITHIN_STRATUM` predicate is enforced.
11. Non-zero `empty_both_cells` may remain matched.
12. Any one-sided, duplicate or unresolved cell becomes descriptive-unmatched,
    with duplicate/unresolved evidence producing incomplete status.
13. Duplicate/unresolved evidence cannot produce branch closure.
14. Outcome mutation cannot change feature or stratum membership.
15. A support-passing comparison with a one-sided cell is incomplete and has no
    diagnostic decision.
16. A lane with zero paired cells produces complete plus
    `INSUFFICIENT_REACHABLE_SUPPORT` when integrity is valid.
17. `CLOSE_STRUCTURAL_COMPRESSION_BRANCH` requires every comparison to be
    `MATCHED_WITHIN_STRATUM`.
18. `DESCRIPTIVE_UNMATCHED` evidence can never emit branch closure or positive
    support.

## Review result

The prior draft was under-specified on feature identity, matched-control
namespacing, causal raw-source binding, terminal cell status and diagnostic
integrity. Those gaps are closed above.
Threshold `8.0 ATR` is explicitly inherited from frozen R3B structural-context
semantics; no outcome-derived threshold selection is authorized.

The contract remains under review until independently approved. After approval,
the coder can implement without choosing any feature key, population namespace,
formula, raw member, support rule, role-transfer rule, denominator, cell
predicate or decision rule. This document authorizes no implementation, study
execution, artifact publication, commit, merge or push.

## Current validation evidence

```text
R3B temporal-v2 strict verifier: passed
R3B decision:                    66240c90f6d7b4c8575caebd1b248dbaa8084819c99504e19c210a0ec0b331ec
R3B validation lock:              27febb38504b51609b3bf70f7f879ce056f16ec2612bf727d33e236ee80ed276
R3B manifest:                     69ec5869678d136dc366039424ca2912b2940d907524f55ed43b1958e0bccc3e
R3B inventory:                    658e2649d2c74f5f6cf8e8bfea38efb95c55908766a01a8d8e6a8950c430907c
R3B focused suite:                116 passed
Cross-phase suite:                402 passed, 17 skipped
Ruff:                             passed
Compileall:                       passed
git diff --check:                 passed
```

Codebase-memory reindex is not rerun during this review. Existing indexes
remain intact; prior failure was caused by stale or missing legacy-worktree
target `flipperAgent-wt-legacy-trendlines`. GitNexus remains stale and is not
approval evidence.

## Authorization

```text
PHASE_11R3B: TEMPORAL_V2_APPROVED
PHASE_11R3B_FINALIST: NONE
PHASE_11R3B_RERUN: NOT_REQUIRED
PHASE_11R4_CONTRACT: APPROVED_FOR_IMPLEMENTATION
PHASE_11R4_IMPLEMENTATION: AUTHORIZED
PHASE_11R4_EXECUTION: NOT_AUTHORIZED
PROVIDER/NETWORK/HOLDOUT/PHASE_10C2_TEMPORAL: PROHIBITED
PROMOTION/RUNTIME/YAML/VIEWER/TRACKER/MTF/REGIME: NOT_AUTHORIZED
COMMIT/MERGE/PUSH: NOT_AUTHORIZED
```
