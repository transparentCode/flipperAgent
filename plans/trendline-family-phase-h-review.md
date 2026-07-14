# Trendline Family Model — Phase H Review

## Current Mode

Quant implementation review.

## Decision

**Revision required. Phase I remains blocked.**

The Phase-H implementation is directionally aligned with the approved asynchronous MTF architecture and the reported regression suites are green. Independent adversarial review found four blocking correctness/audit defects:

1. Phase-H configuration changes alter canonical Phase-G source snapshot identity.
2. Persisted MTF projections are not causally bound to exact source geometry.
3. Relation labels and conflict semantics are forgeable after recomputing content IDs.
4. The latest-source wrapper accepts independent lineage branches and incomplete sources.

Three additional correctness/reporting defects must be closed in the same bounded remediation:

- `projected_order_changed` compares against member-ID order rather than source corridor order;
- forward intersection evidence can be hidden from the shadow intersection count by primary relation precedence;
- MTF artifact aggregation reports confluence-cluster count as cluster size and omits required distributions.

No Phase-I work may begin until these issues pass re-review.

---

# Validation Reproduced

## Trendline-family suite

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_h_review \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  -q -p no:cacheprovider

267 passed
```

## Phase H plus shadow and projected runtime

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_h_review \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  -q -p no:cacheprovider

295 passed
```

## Active RegimeV2, selection, and signals

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_h_review \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals \
  -q -p no:cacheprovider

148 passed
```

One unrelated OpenTelemetry `LoggingHandler` deprecation warning remains.

## Static validation

```text
ruff check: passed
compileall: passed
git diff --check: passed
```

## Codebase-memory

```text
Users-aloobhujia-flipperAgent
40,949 nodes
133,458 edges
status: ready
```

`detect_changes` continues to omit the untracked canonical trendline-family package. Direct source inspection, git status, focused tests, and adversarial probes remain the Phase-H scope evidence of record.

---

# Verified Positive Scope

The implementation correctly preserves these Phase-H boundaries:

- pure MTF composition over immutable Phase-G source snapshots;
- no pivot generation, fitting, member matching, lifecycle update, or source-family mutation;
- exact runtime projection through `LineGeometry.value_at(decision_timestamp)`;
- deterministic source input ordering;
- explicit UTC decision timestamp;
- typed freshness states and missing-source status;
- deterministic complete-linkage-style cluster construction;
- no synthetic averaged trendline;
- source timeframe/family/member/candidate provenance fields;
- additive shadow-only adapter consumption of a precomposed snapshot;
- no signal-worker timing changes;
- no active RegimeV2, selection, strategy, risk, or execution consumption;
- no Phase-I optimization or promotion implementation;
- no runtime imports from legacy trendline packages;
- YAML access remains confined to the canonical config loader.

These positive properties do not offset the blocking causal-contract defects below.

---

# Findings

## P0 — Phase-H parameters alter approved Phase-G source snapshot identity

Locations:

```text
src/libs/models/trendline_family/config.py
src/libs/models/trendline_family/config_resolver.py
src/libs/models/trendline_family/tracker.py
src/libs/models/trendline_family/contracts.py
```

The Phase-H handoff explicitly required:

```text
Changing a Phase-H parameter must not alter source Phase-G snapshots,
source family/member IDs, or source exact geometry.
```

The implementation adds `mtf` to the same resolved config hash persisted in every Phase-G source snapshot. Therefore changing only an MTF comparison threshold changes the Phase-G source snapshot ID.

Independent reproduction used identical source asset, timeframe, bars, candidate ID, anchors, and geometry. Only:

```text
mtf.max_level_distance_atr
```

changed from `0.5` to `0.7`.

Observed:

```text
config_hash_changed          True
phase_g_snapshot_id_changed  True
family_id_changed            False
member_id_changed            False
geometry_changed             False
```

The two resulting Phase-G snapshot IDs were different even though the source tracking state and exact geometry were identical.

### Why this blocks approval

Phase H is a downstream compositor. Its disabled or comparison-only policy must not rewrite upstream Phase-G identity, invalidate approved replay fixtures, or fork stored source lineage.

The implementation report explicitly noted that Phase-H defaults changed a canonical Phase-G fixture UUID. That is architecture drift, not an acceptable fixture-only update.

### Required correction

Separate source-tracker configuration identity from MTF composition identity.

A bounded design may use:

```text
tracking_config_hash
  = model/candidate/matching/lifecycle/interaction/events/rails/ranking

mtf_config_hash
  = Phase-H composition policy only
```

Required behavior:

- Phase-G source snapshot, family-transition, corridor, event, and source-group identities continue using the tracking hash only;
- changing any MTF parameter leaves byte-identical Phase-G source snapshots;
- the MTF normalization context and MTF snapshot bind the MTF policy hash;
- Phase-H configuration remains strict and content-addressed;
- existing Phase-G approval fixtures return to their approved identity unless a genuine Phase-G input changes.

Do not solve this by excluding MTF policy from all identity. It must remain bound to MTF relations, clusters, and aggregate MTF snapshot identity.

---

## P0 — Persisted projected prices are not bound to exact source geometry

Locations:

```text
src/libs/models/trendline_family/mtf.py
  ProjectedMTFMember
  ProjectedMTFFamily
  MTFGeometrySnapshot
```

At runtime, `_project_families()` evaluates exact source geometry correctly. The persisted contracts retain only:

```text
source_snapshot_id
source family/member identity
source_geometry_hash
projected price
```

They do not retain enough typed source geometry evidence to independently recompute the projected price during deserialization or contract validation.

### Independent reproduction

A valid one-source MTF snapshot projected the representative to:

```text
100.0
```

The projected family and member were changed to:

```text
110.0
```

while preserving:

```text
same source snapshot ID
same source family/member/candidate IDs
same source_geometry_hash
same decision timestamp
```

All affected projected, cluster, and aggregate IDs were recomputed.

The forged MTF snapshot was accepted:

```text
source_exact_price       100.0
forged_projected_price   110.0
geometry_hash_unchanged  True
forged_snapshot_ACCEPTED
```

The snapshot is content-addressed, but the content can make a causally false projection claim.

### Related contract gaps

The aggregate contract also does not independently bind all derived fields, including:

- projected member price to exact `LineGeometry.value_at(T)`;
- projected member offset to the exact representative price;
- projected representative price to the representative member;
- normalized slope to persisted source slope and source ATR;
- projected corridor width ATR to projected exact members and decision ATR;
- source age/freshness values to source timestamp, decision timestamp, and policy;
- source status timing/reason fields exactly to the corresponding source reference;
- diagnostics counts to persisted collections.

### Required correction

Persist one bounded typed source-geometry audit sufficient for deterministic validation.

Acceptable options include:

1. a canonical `MTFSourceGeometryAudit` per projected member containing the immutable source `LineGeometry` value plus its hash and full source identity; or
2. a bounded canonical source-family projection audit containing every exact member geometry required by the projected family.

This is copied evidence, not geometry ownership. The canonical owner remains the Phase-G source snapshot.

The MTF contract must independently recompute and validate:

```text
projected member price
projected member offset
representative member price and slope
normalized slope ATR/hour
projected member ordering
corridor lower/upper/width
crossing/order-change flag
source age seconds and age bars
freshness/contribution state
```

Changing source geometry evidence must change projected member/family IDs and the aggregate MTF snapshot ID.

A hash without the geometry payload is insufficient to verify projection mathematics.

---

## P0 — Conflict and relation semantics are forgeable

Locations:

```text
src/libs/models/trendline_family/mtf.py
  MTFRelation
  MTFGeometrySnapshot
  _build_relations
```

`MTFRelation` content-addresses whatever relation label and metrics are supplied. `MTFGeometrySnapshot` verifies that the referenced families, roles, and timeframes exist, but it does not derive the expected relation from projected evidence and Phase-H policy.

### Independent reproduction

A valid pair consisted of overlapping nearby opposite-role structures:

```text
left role   RESISTANCE
right role  SUPPORT
relation    CONFLICT
```

The relation was relabeled:

```text
AGREEMENT
```

with recomputed relation and MTF snapshot IDs.

The forged snapshot was accepted:

```text
forged_relation_ACCEPTED AGREEMENT
```

This can erase explicit conflict evidence while preserving internally consistent IDs.

### Related cluster gaps

The snapshot contract recomputes some cluster statistics but does not independently derive or verify:

- legal pairwise compatibility under the current Phase-H gates;
- `is_confluence` against `minimum_confluence_timeframes`;
- deterministic reference-family choice;
- confluence strength;
- reason codes;
- complete-linkage membership against relation evidence;
- expected relation coverage for every cross-timeframe family pair.

### Required correction

Persist a typed immutable MTF policy audit in the MTF snapshot, containing the exact thresholds and normalization identity used for composition.

Use shared pure helpers as the single semantic source of truth for both generation and validation:

```text
expected source freshness/statuses
expected projected families/members
expected pair relations
expected complete-linkage clusters
expected diagnostics
```

During `MTFGeometrySnapshot` construction/deserialization, recompute the expected relation and cluster evidence from the canonical projection audits and policy, then require exact equality.

At minimum reject:

- opposite-role `AGREEMENT`, `CONFLUENCE`, or `NESTED`;
- same-role `CONFLICT` unless the documented same-role conflict rule is actually met;
- relation labels inconsistent with level/slope/corridor/intersection evidence;
- missing, duplicate, or extra pair relations;
- cluster membership not supported by complete-linkage compatible pairs;
- false `is_confluence`, reference, strength, or reason codes.

Content addressing alone is not proof that a relation label is semantically true.

---

## P0 — Latest source wrapper accepts branch replacement and incomplete snapshots

Location:

```text
src/libs/models/trendline_family/mtf.py
  LatestMTFSnapshotStore.update
```

The wrapper currently accepts any newer timestamp for a source timeframe. It does not require:

```text
new.previous_snapshot_id == stored.snapshot_id
```

It also does not apply the incomplete-source rejection used by `compose_mtf_snapshot()`.

### Independent reproduction A — independent newer branch

A first valid `1h` Phase-G snapshot was stored. A second independently created first snapshot had:

```text
newer timestamp
previous_snapshot_id = None
different source state
```

The store accepted it:

```text
first              True
independent_newer  True
```

This violates the approved requirement that older or conflicting lineage snapshots reject.

### Independent reproduction B — incomplete source

A canonical Phase-G snapshot was given:

```text
diagnostics.confirmed_bar = false
```

and a correctly recomputed Phase-G snapshot ID.

The source store accepted it:

```text
incomplete_update True
```

The compositor later rejects incomplete input, but the stateful wrapper itself is required to hold latest confirmed sources only.

### Required correction

`LatestMTFSnapshotStore.update()` must:

- reject incomplete markers before mutation;
- require strictly increasing timestamps;
- require exact source lineage continuity:
  `snapshot.previous_snapshot_id == previous.snapshot_id`;
- treat an exact duplicate snapshot ID as idempotent;
- reject same-timestamp conflicts;
- reject newer independent branches and skipped lineage;
- defensively round-trip or reconstruct the source snapshot before storing so full canonical contracts are revalidated;
- leave the stored head byte-identical after every rejection.

Add tests for two source timeframes arriving in different orders to ensure valid asynchronous independence remains supported.

---

## P1 — `projected_order_changed` compares against member-ID order, not source rail order

Location:

```text
src/libs/models/trendline_family/mtf.py
  _project_families
```

Current logic compares projected price ordering with:

```text
tuple(member.member_id for member in family.members)
```

Phase-G families intentionally store members in lexical `member_id` order. The source rail ordering is persisted in:

```text
FamilyCorridor.ordered_member_ids
```

### Independent reproduction

At the exact source snapshot timestamp, no line crossing or order change occurred.

Observed:

```text
family member-ID order:
  (1fdd..., e238...)

source corridor price order:
  (e238..., 1fdd...)

projected price order:
  (e238..., 1fdd...)

projected_order_changed:
  True
```

The flag reports a crossing/order change solely because member-ID order differs from price order.

### Required correction

Compare projected member order against the source snapshot corridor’s `ordered_member_ids` for the same family.

Persist both concepts distinctly when useful:

```text
source_ordered_member_ids
projected_ordered_member_ids
projected_order_changed
```

Add tests for:

- lexical member order differing from source price order with no crossing -> `False`;
- true projected crossing after source close -> `True`;
- member IDs preserved across crossing.

---

## P1 — Orthogonal intersection evidence is hidden by primary relation precedence

Locations:

```text
src/libs/models/trendline_family/mtf.py
  _build_relations
  build_mtf_shadow_features
```

The relation contract can persist finite intersection fields on a relation whose primary type is `CONFLICT`, `CONFLUENCE`, or another label. However the shadow feature:

```text
intersection_relation_count
```

counts only records whose primary `relation_type == INTERSECTION`.

### Independent reproduction

An opposite-role nearby pair was both a conflict and had an exact forward representative intersection in 360 seconds.

Observed:

```text
relation_type                        CONFLICT
intersection_horizon_eligible       True
intersection_seconds_from_decision  360.0
feature intersection_relation_count 0
```

### Required correction

Choose and document one unambiguous model:

- separate orthogonal typed relation facts per pair; or
- retain one primary relation plus explicit orthogonal flags/evidence.

In either design, shadow and artifact counts must report every eligible forward intersection, not only pairs whose primary label happens to be `INTERSECTION`.

Do not suppress conflict when reporting intersection, and do not convert intersection into a trading event.

---

## P1 — MTF artifact aggregation is incomplete and `mtf_cluster_size` is incorrect

Location:

```text
src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py
  summarize_trendline_family_shadow_artifacts
```

The current implementation defines:

```text
mtf_cluster_size = distribution of confluence_cluster_count
```

This is the number of confluence clusters in a record, not each cluster’s family/timeframe size.

### Independent reproduction

A snapshot contained one cluster with two projected families:

```text
actual cluster family counts  (2,)
artifact mtf_cluster_size      {'1': 1}
```

The requested Phase-H artifact distributions are also missing:

- source age bars;
- distinct timeframe count per cluster;
- confluence strength;
- normalized slope dispersion;
- corridor overlap ratio;
- intersection horizon/seconds distribution.

### Required correction

Expose bounded typed sequences from the persisted MTF snapshot through the shadow payload or a dedicated artifact projection, then aggregate the actual values.

At minimum provide correctly named distributions for:

```text
source timeframe coverage
source age bars
fresh/stale/excluded counts
projected family/member counts
cluster family size
cluster distinct-timeframe count
confluence strength
agreement/conflict/intersection counts
normalized slope dispersion
corridor overlap ratio
intersection seconds/horizon
exclusion reason
```

Do not recompute composition in the adapter.

---

# Test Coverage Gap

Only one compact `test_mtf.py` file was added, containing eight broad tests. It does not cover most adversarial and parameter-effect gates from the approved Phase-H handoff.

The remediation must split or expand focused tests for:

```text
MTF contracts and source geometry binding
source wrapper lineage and confirmation
projection/order crossing
freshness and source-status truth
relation semantic validation
complete-linkage cluster validation
MTF aggregate identity
causality and replay
shadow feature truth
artifact distributions
parameter effects
```

Green happy-path tests are insufficient for approval while self-consistent forged MTF evidence is accepted.

---

# Required Remediation Scope

Expected bounded production scope:

```text
src/libs/models/trendline_family/mtf.py
src/libs/models/trendline_family/config.py
src/libs/models/trendline_family/config_resolver.py
src/libs/models/trendline_family/contracts.py          # only for phase-specific config identity if needed
src/libs/models/trendline_family/tracker.py            # only to consume tracking-only config identity
src/libs/models/trendline_family/api.py
src/libs/models/trendline_family/__init__.py
src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py
configs/trendline_family.yaml                          # only if schema representation changes
focused tests under tests/models/trendline_family/
```

Do not modify:

```text
signal worker timing
active RegimeV2
probability stage
overlay
MoE
existing active MTF stage
selection
strategy
risk
execution
legacy trendline runtime
```

Do not begin Phase I.

---

# Required Adversarial Tests

Add focused tests proving:

1. Changing only any MTF parameter leaves byte-identical Phase-G source snapshots and IDs.
2. MTF config changes alter MTF policy/snapshot identity and relevant derived relations only.
3. A projected member price inconsistent with its exact source geometry is rejected after all IDs are recomputed.
4. A forged projected representative price, slope, offset, corridor bound, or width is rejected.
5. Forged source age, freshness, contribution state, or source-status reason is rejected.
6. Opposite-role conflict relabeled agreement/confluence/nested is rejected after recomputing IDs.
7. Same-role legal relation labels are derived exactly from persisted policy and evidence.
8. Missing, extra, or duplicate pair relations are rejected.
9. Forged cluster membership, reference, confluence flag, strength, metrics, or reason codes are rejected.
10. The chain-overmerge adversary remains split.
11. Newer independent source lineage is rejected by `LatestMTFSnapshotStore`.
12. Incomplete canonical Phase-G source snapshots are rejected by both wrapper and pure compositor.
13. Rejected source updates leave each timeframe head byte-identical.
14. Source arrival order remains semantically invariant once the same valid source set is present.
15. Source corridor order equal to projected order reports no order change even when member-ID order differs.
16. A true projected crossing reports order change while preserving member IDs.
17. Conflict plus eligible analytical intersection reports both facts in persisted and shadow evidence.
18. `mtf_cluster_size` reports actual cluster membership size.
19. All required Phase-H artifact distributions are populated from persisted typed evidence.
20. Existing Phase-G, shadow, and projected-lane invariance suites remain green.

---

# Architecture Drift Check

Verified:

- no legacy trendline runtime import;
- no YAML read outside `config_loader.py`;
- no Phase-I optimizer or promotion implementation;
- no active RegimeV2, selection, strategy, risk, or execution consumption;
- no signal-worker timing change;
- MTF remains additive and default-disabled.

Unacceptable drift requiring correction:

- downstream Phase-H config currently changes upstream Phase-G source snapshot identity.

The worktree remains broadly untracked and also contains unrelated conductor/config changes. The eventual commit must explicitly include the complete canonical Phase A–H source, config, tests, and plans without folding unrelated work into this remediation.

---

# Codex Remediation Prompt

```text
Remediate Phase H only using:

- plans/trendline-family-phase-h-review.md
- plans/trendline-family-phase-g-approval.md
- plans/trendline-family-codex-phase-execution-plan.md
- plans/trendline-family-model-architecture-plan.md

Do not begin Phase I.

Objective:
Close the Phase-H causal identity, projection-truth, relation-truth, source-lineage, order-change, intersection-reporting, and artifact gaps while preserving the pure shadow-only MTF architecture.

Required outcomes:

1. Separate source-tracking config identity from MTF composition config identity.
   - Changing only MTF parameters must leave byte-identical Phase-G source snapshots and IDs.
   - MTF policy remains fully bound to MTF relations, clusters, and aggregate snapshot identity.

2. Persist bounded canonical source-geometry evidence sufficient to independently validate every projected member/family value.
   - Recompute exact projected prices, representative, offsets, slope normalization, corridor bounds/width, ordering, and crossing flag.
   - A source geometry hash without the geometry payload is insufficient.

3. Persist typed MTF policy evidence and use shared pure generation/validation helpers.
   - Derive expected freshness/statuses, projected structures, every pair relation, complete-linkage clusters, and diagnostics.
   - Reject self-consistent forged relation or cluster labels after IDs are recomputed.

4. Harden LatestMTFSnapshotStore.
   - Confirmed sources only.
   - Exact previous_snapshot_id continuity per timeframe.
   - Strictly newer timestamps.
   - Duplicate IDs idempotent.
   - Branches, skipped lineage, same-time conflicts, and incomplete sources reject atomically.

5. Compute projected_order_changed against the source Phase-G corridor order, not lexical member-ID order.

6. Preserve orthogonal analytical intersection evidence even when the primary pair relation is conflict/agreement/confluence.
   - Shadow and artifact intersection counts must count all eligible intersections.

7. Correct and complete MTF artifact distributions.
   - Actual cluster family/timeframe sizes, source ages, confluence strength, slope dispersion, overlap, intersection horizon, and exclusions.

8. Preserve all approved Phase-G behavior, active-decision invariance, projected-lane behavior, and default-disabled Phase-H integration.

Add the adversarial and parameter-effect tests listed in plans/trendline-family-phase-h-review.md.

Run:

PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q

PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py -q

PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals -q

ruff check \
  src/libs/models/trendline_family \
  src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py

PYTHONPATH=src .venv/bin/python -m compileall -q \
  src/libs/models/trendline_family \
  src/libs/models/regime_v2/adapters

git diff --check

Reindex codebase-memory and report project, node count, edge count, status, changed-file scope, and impacted symbols.

Stop after Phase-H remediation. Phase I remains blocked pending re-review.
```
