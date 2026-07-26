# Architect to Coder: Trendline V2 Phase 11R.5 Reachability Asymmetry Attribution

## Status

READY_FOR_R5_IMPLEMENTATION

R5_CONTRACT: APPROVED_FOR_IMPLEMENTATION
R5_IMPLEMENTATION: AUTHORIZED
R5_EXECUTION: NOT_AUTHORIZED

Bounded R5 implementation authorized. Canonical execution, artifact
publication, selector change and runtime promotion remain unauthorized.

## Approved predecessor

Phase 11R.4 closeout:

~~~
commit: e862c3127b1aa11297ea01d342ea095be27eae62
parent: b7cd736e08bda2eb82fa7f0dad62c842428c602a
branch: research/trendline-v2-phase-11r5-reachability-asymmetry-attribution-v1
~~~

Authoritative R4 evidence, never regenerate:

~~~
root:
/tmp/trendline_v2_phase11r4_causal_structural_reachability/20260522_20260701
diagnostic_id: f4a95e118d52eec9ae60b447f08ca11a756908d7861772978b8f0393b0bbd2e2
manifest_id: 965b4741ec0f7305b8217dbc90d5c2bb31a6185e09b42c519bc404548c290a7e
inventory: 7fbd19fd1b828c09881df6236d2c3b8bdf7ae4bdfd4cd4b03d770c401ecd413c
~~~

Protected R3B temporal-v2 secondary inventory:

~~~
658e2649d2c74f5f6cf8e8bfea38efb95c55908766a01a8d8e6a8950c430907c
~~~

R4 and R3B reruns are prohibited.

## Objective

Determine why R4 geometry_projected_distance_atr_96h <= 8.0 populations become
one-sided. Attribute asymmetry to causal selection geometry and membership only.
Future outcomes must not explain selection asymmetry.

Required classes:

~~~
FULL_LINEAGE_SUBSTITUTION
PARTIAL_LINEAGE_SUBSTITUTION
STRICT_BUDGET_RESCUE
NON_NESTED_HIGHER_BUDGET_PAIRING
PERSISTENT_THROUGH_BUDGET_3
SHARED_LINEAGE_REACHABILITY_INCONSISTENCY
UNATTRIBUTED_ONE_SIDED_CELL
~~~

Questions:
- Did one side replace every selected lineage with reachable lines?
- Did shared lineages remain while side-unique lines caused asymmetry?
- Did budget truncation explain lower-budget asymmetry?
- Did higher-budget pairing require non-nested replacement?
- Did asymmetry persist through budget 3?
- Is any shared lineage inconsistent in geometry or threshold membership?

No selector ranking, finalist selection or promotion.

## Source binding and access

Read only verified R4 source through its strict verifier:

~~~
/tmp/trendline_v2_phase11r4_causal_structural_reachability/20260522_20260701
~~~

R4 diagnostic, manifest and inventory must match frozen identities above.
R5 attribution code may not directly read temporal-v2 or raw source files.
Those sources may be accessed only internally by the strict R4 verifier.

Forbidden:
- Phase 10C.2 temporal evidence
- holdout evidence
- raw SUI evidence
- new raw source data
- network or Binance
- provider execution
- R3B or R4 rerun
- legacy trendline execution

Source drift, missing members, altered IDs, forbidden access or source mutation
must produce R5_ATTRIBUTION_BLOCKED before publication.

## Frozen primary population

Use exactly R4 comparison records where:

~~~
contender_only_cells > 0 or control_only_cells > 0
~~~

Expected reconciliation:

~~~
one-sided comparison records: 51
one-sided checkpoint-role cells: 117
contender-only cells: 25
control-only cells: 92
~~~

Any mismatch blocks R5. Do not reconstruct another population.

Cell identity:

~~~
(
  contender_policy_id,
  budget_per_role,
  control_policy_id,
  dataset_id,
  checkpoint_index,
  semantic_role_at_selection,
  96
)
~~~

Preserve full contender/control population namespace. Never merge controls by
control policy alone.

## Causal row identity

Selected-line identity:

~~~
(dataset_id, checkpoint_index, semantic_role_at_selection, lineage_id)
~~~

For every one-sided cell derive:

~~~
contender_selected
control_selected
contender_reachable
control_reachable
shared_selected
contender_unique
control_unique
~~~

Reachability remains exactly:

~~~
geometry_projected_distance_atr_96h <= 8.0
~~~

Allowed fields:

~~~
lineage_id
fixed_geometry
geometry_projected_distance_atr_96h
initial_distance_atr
selection identity
policy identity
control identity
budget
dataset
checkpoint
role
~~~

Forbidden fields:

~~~
survival
zone_contact
post_contact_reaction
breach
future minimum distance
later lifecycle state
holdout evidence
~~~

Persist exact identities. Lineage alone is insufficient when checkpoint or role
differs.

## Attribution precedence

Apply exactly one mutually exclusive class per one-sided cell.

1. SHARED_LINEAGE_REACHABILITY_INCONSISTENCY

Use when same exact lineage appears on both sides but fixed geometry, projected
distance or threshold membership differs. Unresolved; forces
R5_ATTRIBUTION_INCOMPLETE.

2. FULL_LINEAGE_SUBSTITUTION

Use when shared_selected is empty and exactly one side contains reachable rows.
Exactly one reachable direction is mandatory. If neither side, or both sides,
contain reachable rows, the cell is unresolved and forces
R5_ATTRIBUTION_INCOMPLETE.

3. PARTIAL_LINEAGE_SUBSTITUTION

Use when selected sets share at least one lineage, but side-unique lineages
create one-sided reachable membership.

4. UNATTRIBUTED_ONE_SIDED_CELL

Use when frozen identities cannot support another class. Unresolved; forces
R5_ATTRIBUTION_INCOMPLETE.

Precedence runs before cross-budget labels. Shared-lineage inconsistency cannot
be relabeled as substitution or budget rescue.

## Distance evidence

Persist for every one-sided cell:

~~~
reachable_side_projected_distances
missing_side_projected_distances
minimum_missing_side_projected_distance
minimum_excess_above_8_atr
reachable_side_headroom_below_8_atr
shared_lineage_projected_distance_equality
~~~

Use continuous excess above 8 ATR. No near-miss threshold.

## Cross-budget semantics

For lower-budget one-sided cells, inspect same contender, control, dataset,
checkpoint and role at higher budgets.

STRICT_BUDGET_RESCUE requires:
- higher-budget cell becomes paired;
- lower-budget contender selected set is subset of higher-budget contender set;
- lower-budget control selected set is subset of higher-budget control set;
- previously missing side gains at least one reachable lineage.

NON_NESTED_HIGHER_BUDGET_PAIRING applies when higher budget becomes paired but
one or both selected sets are not nested. Never call this budget truncation.

PERSISTENT_THROUGH_BUDGET_3 applies when same cell remains one-sided at budget 3.
Budget-3 source is classified directly.

Cross-budget labels are descriptive only. They cannot change R4 matching,
decision or promotion.

## Required report

Report exact rows and counts by:

~~~
contender_policy_id
control_policy_id
budget_per_role
dataset_id
timeframe
semantic_role_at_selection
one_sided_direction
attribution_class
cross_budget_class
~~~

Persist per cell:
- full population namespace;
- exact selected/reachable/shared/unique identities;
- selected-lineage overlap rates;
- unique-lineage counts;
- distance-excess distributions;
- strict rescue result;
- non-nested pairing result;
- budget-3 persistence result.

Reproduce, do not assume:
- BTCUSDT 1h has no one-sided comparisons;
- support carries most one-sided cells;
- nearest-projection control has control-only surplus;
- lower budgets show more one-sided comparisons.

No outcome metric, paired delta or promotion gate may enter attribution.

## Status rules

Allowed statuses:

~~~
R5_ATTRIBUTION_COMPLETE
R5_ATTRIBUTION_INCOMPLETE
R5_ATTRIBUTION_BLOCKED
~~~

Complete requires:
- all 117 one-sided cells reconciled;
- zero shared-lineage inconsistencies;
- zero unattributed cells;
- exact R4 source identities;
- zero forbidden accesses;
- no source mutation during derivation.

Incomplete means source valid but attribution evidence is missing, contradictory
or unresolved. It has no selector or promotion decision. Blocked means a source,
execution-boundary or forbidden-access precondition failed before derivation.

R5 must not alter:
- R4 status or diagnostic_decision;
- R3B finalist or decision;
- 8 ATR threshold;
- R4 matching rules;
- runtime, YAML, viewer, provider, tracker, MTF or Regime behavior.

## Future implementation scope

After contract approval, implementation may create only:

~~~
scripts/analyze_trendline_v2_reachability_asymmetry_attribution.py
tests/scripts/test_trendline_v2_reachability_asymmetry_attribution.py
plans/coder-to-orchestrator-trendline-v2-phase-11r5-reachability-asymmetry-attribution-v1.md
~~~

Required tests must cover exact 51/117/25/92 reconciliation, namespace and
checkpoint/role isolation, attribution precedence, shared inconsistencies,
unattributed blocking, strict rescue subsets, non-nested pairing, budget-3
persistence, distance evidence, forbidden future fields, source mutation,
coordinated rehash rejection, atomic output and identical-only overwrite.

## Final Contract Remediation

### Deterministic serialization

Freeze canonical output ordering:

~~~
cell rows:
  sort by full seven-field cell identity

selected/reachable/shared/unique identities:
  sort lexicographically by exact four-field selected-line identity

global inconsistency records:
  sort by exact four-field selected-line identity

summary rows:
  sort by contender, control, budget, dataset, role,
  one-sided direction, attribution class, cross-budget class

distance arrays:
  sort in ascending numeric order
~~~

Freeze output as exactly three files with two manifest members. Use canonical
JSON only. Reject duplicate JSON keys, NaN and Infinity.

### Exact R4 cell extraction

Select comparison records only when:

~~~
contender_only_cells > 0 or control_only_cells > 0
~~~

Within those comparisons select only cell records where:

~~~
primary_stratum_class in {contender_only, control_only}
terminal_cell_class == primary_stratum_class
reconciliation_errors == []
~~~

Any mismatch is unresolved and produces `R5_ATTRIBUTION_INCOMPLETE`. One-sided
direction derives only from `primary_stratum_class`.

### Global lineage-feature consistency

For every exact identity:

~~~
(dataset_id, checkpoint_index, semantic_role_at_selection, lineage_id)
~~~

all occurrences across contenders, controls and budgets must have exact
canonical equality for `fixed_geometry` and exact persisted numeric equality
for `initial_distance_atr`, `geometry_projected_distance_atr_96h` and threshold
membership. Scan all selected-line identities appearing in the 117 source
one-sided cells and in their budget-2/budget-3 comparison cells used for
cross-budget attribution. Any mismatch is
`SHARED_LINEAGE_REACHABILITY_INCONSISTENCY` and makes R5 incomplete.
Persist one global inconsistency record per inconsistent identity and reference
that record from every affected R5 cell. Do not create duplicate cell rows.

### Substitution and direction rules

Each extracted one-sided cell must satisfy exactly one reachable direction:

~~~
bool(contender_reachable) XOR bool(control_reachable)
~~~

Otherwise cell is unresolved. Classification is frozen:

~~~
FULL_LINEAGE_SUBSTITUTION:
  shared_selected is empty and exactly one side has reachable rows

PARTIAL_LINEAGE_SUBSTITUTION:
  shared_selected is non-empty;
  shared lineages are feature-consistent;
  reachable side has at least one reachable side-unique lineage;
  missing side has zero reachable lineages
~~~

No neither-side-reachable exception exists.

Overlap fields are exact:

~~~
selected_lineage_overlap_numerator = count(shared_selected)
selected_lineage_overlap_denominator = count(contender_selected union control_selected)
selected_lineage_overlap_rate = numerator / denominator
~~~

Zero denominator is unresolved.

### Distance formulas

Sort all distance arrays ascending. For every cell:

~~~
reachable_side_projected_distances = sorted projected distances of reachable-side reachable rows
missing_side_projected_distances = sorted projected distances of every selected row on missing side
minimum_missing_side_projected_distance = min(missing_side_projected_distances)
minimum_excess_above_8_atr = minimum_missing_side_projected_distance - 8.0
reachable_side_headroom_below_8_atr = min(8.0 - distance for distance in reachable_side_projected_distances)
~~~

Missing or non-finite values are unresolved. Require excess greater than zero
and headroom greater than or equal to zero. No tolerance or near-miss band.

### Deterministic cross-budget rules

For budget 1 or 2, inspect higher budgets in ascending order and choose first
higher budget whose primary cell class is `paired`.

~~~
STRICT_BUDGET_RESCUE:
  first paired higher budget exists;
  both lower selected sets are subsets of corresponding higher sets;
  previously missing side gains at least one reachable lineage

NON_NESTED_HIGHER_BUDGET_PAIRING:
  first paired higher budget exists;
  one or both subset checks fail
~~~

Persist `rescue_budget`, `contender_nested`, `control_nested` and
`missing_side_reachable_gain`.

If no higher budget pairs and budget 3 remains `contender_only` or
`control_only`, use `PERSISTENT_THROUGH_BUDGET_3`; persist `budget3_direction`
and `direction_preserved`. For budget-3 source cells classify directly.

If no higher budget pairs and budget 3 is `empty_both`, missing, duplicate or
unresolved, set `cross_budget_class = null`, persist exact
`cross_budget_unresolved_reason`, and make R5 incomplete.

Every complete cell has exactly one attribution class and one non-null
cross-budget class.

### R4-only verifier and publication boundary

R5 may import only `verify_reachability_bundle` from
`scripts.analyze_trendline_v2_causal_structural_reachability`. It must not call
or import `execute_reachability_study`, `build_analysis` or R3B execution
functions.

After strict R4 verification, R5 may read only:

~~~
reachability_diagnostic.json
source_binding.json
manifest.json
~~~

R3B temporal-v2 and raw sources are internal to the existing R4 verifier and
must not be directly consumed by R5. Mutating survival, contact, reaction,
breach, cell deltas or R3B promotion metrics in synthetic R4 diagnostic data
must not change attribution bytes.

Publication contract:

~~~
output_root:
/tmp/trendline_v2_phase11r5_reachability_asymmetry_attribution/20260522_20260701

files:
manifest.json
reachability_asymmetry_attribution.json
source_binding.json

CLI: --execute-attribution-study
environment: TRENDLINE_V2_ALLOW_PHASE11R5_STUDY=1
verification: --verify
~~~

Execution sequence is fixed:

~~~
fresh-output refusal before source access
strict R4 verification
source snapshot before
deterministic attribution
source snapshot after
immutability comparison
staging write
source-backed byte rederivation
atomic publication
strict final verification
~~~

Synthetic verification requires explicit expected evidence.

### Final status rules

~~~
R5_ATTRIBUTION_BLOCKED:
  source verification or execution precondition fails before derivation

R5_ATTRIBUTION_INCOMPLETE:
  valid source but population mismatch, duplicate identity, feature
  inconsistency, unattributed cell, null cross-budget class or unresolved
  evidence remains

R5_ATTRIBUTION_COMPLETE:
  all 117 unique cells have exactly one attribution class and one
  cross-budget class; zero inconsistencies, unattributed cells and unresolved
  cells; exact source snapshots; zero forbidden access
~~~

R5 has no selector or promotion decision. R4/R3B decisions, the 8 ATR
threshold and R4 matching rules remain unchanged.

### Additional contract tests

Implementation review must include tests for:

1. Exact extraction by `primary_stratum_class`.
2. Primary/terminal class mismatch rejection.
3. Reachable-direction XOR enforcement.
4. Global cross-policy and cross-budget lineage consistency.
5. Exact overlap numerator, denominator and rate.
6. Exact distance and headroom formulas.
7. Earliest paired higher-budget selection.
8. Budget-1 rescue at budget 3.
9. Direction-changing budget-3 persistence.
10. Empty-both budget-3 trajectory becoming incomplete.
11. Exactly one attribution and cross-budget class per cell.
12. Forbidden outcome-field mutation invariance.
13. No direct R3B or raw attribution reads.
14. Exact three-file output inventory.
15. Source-backed coordinated-forgery rejection.
16. Output-root refusal before source verification.

## Boundaries

~~~
R4 rerun:                    prohibited
R5 implementation:          authorized
R5 execution:                not authorized
provider/network/SUI:        prohibited
holdout/temporal evidence:  prohibited
runtime/YAML/viewer:         prohibited
selector/tracker/MTF/Regime: prohibited
commit/merge/push:           not authorized
~~~
