# Trendline Family Model — Phase G Review

## Current Mode

Quant review.

## Decision

**Revision required. Phase H remains blocked.**

The Phase-G implementation has the correct broad structure:

- exact rails remain canonical `FamilyMember` geometries;
- grouping is deterministic and complete-linkage-safe against simple transitive over-merging;
- corridors are typed and content-addressed;
- representative geometry remains one exact member;
- Phase-F interaction/event state continues to use the representative exact rail rather than corridor bounds;
- multi-rail features remain additive under the Phase-E shadow namespace;
- active RegimeV2, selection and signal regression suites remain unchanged.

However, group-to-family association does not yet honor exact continuation through non-representative rails, the role-reversal snapshot can create duplicate lineage or fail on a valid partial new-role group, and the Phase-G persistence contracts do not fully bind corridor and membership-audit facts to their canonical sources.

---

## Validation Reproduced

### Trendline-family suite

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family -q

210 passed
```

### Phase-G plus shadow integration

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py -q

238 passed
```

### Active RegimeV2, selection and signal suites

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals -q

148 passed
```

One pre-existing OpenTelemetry deprecation warning remains.

### Static validation

The normal repository Ruff command is currently blocked before file analysis by an unrelated duplicate key in `pyproject.toml`:

```text
flipper-conductor = "conductor.main:main"
flipper-conductor = "apps.conductor.main:main"
```

The isolated Phase-G source/test lint passed:

```text
ruff check --isolated <Phase-G source and test paths>

All checks passed
```

Also passed:

```text
compileall
git diff --check
```

The duplicate project-script key is outside the reported Phase-G source scope, but it must eventually be corrected so normal project-configured Ruff is runnable again.

### Codebase-memory

```text
Users-aloobhujia-flipperAgent
40,297 nodes
128,581 edges
status: ready
```

As in prior phases, `detect_changes` under-reports the untracked canonical package. Direct source inspection, `git status`, call tracing and executed tests remain the scope evidence of record.

---

# Verified Phase-G Behavior

The following behavior is correct and should be preserved:

- candidate input permutation produces deterministic rail groups;
- complete-linkage grouping prevents the tested A/B/C chain over-merge;
- opposite roles and slope-incompatible candidates remain separate;
- current candidates whose exact geometries cross inside their confirmed span are split;
- singleton and multi-rail corridors are generated from exact member geometries;
- interaction observations remain centered on the representative exact rail;
- continuing matched rails retain member IDs and `first_seen_at`;
- immediate removal of unmatched prior rails on a successful group update is explicitly audited;
- a representative change begins a new Phase-F event episode;
- standard two-direction multi-rail role reversal preserves all exact geometries, anchors, family ID, member IDs and representative ID when the provider supplies the complete new-role group;
- snapshot IDs include corridor state;
- legacy Phase-F snapshots without Phase-G fields remain decodable;
- projected-lane exactly-once behavior and active-decision invariance remain green.

---

# Blocking Findings

## P0 — Exact non-representative rail continuation can birth a duplicate family

Locations:

```text
src/libs/models/trendline_family/matching.py
  score_family_candidate
  greedy_match_rail_groups

src/libs/models/trendline_family/rails.py
  match_group_members
```

Family-to-group association is currently gated only by comparing each group candidate with the family representative line. It does not use exact continuation against every previous member before deciding whether the group belongs to the family.

Independent reproduction used a valid configuration where the corridor/grouping distance is intentionally broader than the family representative match distance:

```text
matching.max_distance_atr = 0.10
rails.max_adjacent_gap_atr = 0.50
rails.max_corridor_width_atr = 1.00
```

Initial family:

```text
three exact rails
representative = middle/medoid rail
```

Next confirmed bar:

```text
only the outer left rail remains
same exact projected level
same anchor IDs
```

The member-level matcher correctly found:

```text
RailMemberMatch
score = 1.0
projected_distance_atr = 0.0
anchor_similarity = 1.0
```

But the family/group matcher returned no association because that exact continuing outer rail was outside the representative-level gate.

Tracker result:

```text
old three-rail family -> WEAKEN, bars_since_match=1
new exact singleton   -> BIRTH with a new family_id
```

This violates the required Phase-G behavior:

```text
multi-rail -> singleton retains family identity when one valid member continues
```

It also affects dormant reactivation and any continuation where the representative rail disappears but another canonical member survives.

### Required correction

Make group-to-family eligibility member-aware:

1. Score deterministic previous-member/current-candidate continuation first.
2. A hard-valid exact member continuation must make the group eligible even when the surviving rail is outside the old representative-level distance gate.
3. Use member-level anchors for anchor similarity; do not use `family.members[0].anchors` as a family-wide proxy.
4. Aggregate member-continuation evidence into one deterministic family/group score and retain the existing one-family/one-group assignment policy.
5. Keep representative-level and corridor-overlap evidence as supplementary diagnostics rather than a gate that discards exact member continuation.

Required tests:

- three rails -> outer non-representative singleton with exact continuation;
- representative missing while another member continues;
- dormant multi-rail family reactivates from a non-representative member;
- valid member continuation outside representative match distance;
- one family eligible for multiple groups chooses one deterministic winner;
- one group eligible for multiple families does not merge lineage.

---

## P0 — Multi-rail role reversal can birth duplicate old-role lineage

Locations:

```text
src/libs/models/trendline_family/tracker.py
  _reversal_duplicate_candidate_ids
  unmatched group birth loop
```

The old-role duplicate suppression compares candidates only with the temporarily reversed family representative. It does not compare candidates with every preserved rail.

The birth loop also skips a group only when **all** candidate IDs were marked suppressed. If one candidate is not suppressed, the complete original group is birthed, including candidates already recognized as reversal duplicates.

Independent reproduction:

```text
support family with two rails
matching.max_distance_atr = 0.10
Phase-F event reaches RETEST_SUCCESS
next bar applies SUPPORT -> RESISTANCE
provider emits the same two old-role SUPPORT rails
```

Result on the reversal snapshot:

```text
original family -> ROLE_REVERSED, RESISTANCE, same two members
new family      -> BIRTH, SUPPORT, duplicate two-rail geometry
```

The snapshot therefore contains both the correctly reversed family and a newly born old-role duplicate solely from the provider's stale role rendering.

### Required correction

- compare old-role reversal candidates against every prior exact member, not only the representative;
- identify duplicate candidates through deterministic member-level continuation evidence;
- remove suppressed candidates from an unmatched birth group before birth evaluation;
- if no candidates remain, skip the group;
- if independent residual candidates remain, rebuild a content-addressed residual group and birth only those residual candidates;
- never birth a group containing a candidate already consumed as reversal continuity evidence.

Required tests in both role directions:

- provider emits complete old-role rail group on the reversal bar;
- provider emits old-role representative plus an old-role non-representative rail;
- group contains both reversal duplicates and one genuinely independent rail;
- no duplicate family is born for preserved rails;
- only the independent residual rail may birth.

---

## P0 — Valid partial new-role group can fail the role-reversal update

Locations:

```text
src/libs/models/trendline_family/tracker.py
  _matched_draft
  _settle_pending_role_reversal_drafts
  event_reset_family_ids
  _transition_from_draft
```

A reversal-bar group containing only a continuing non-representative rail is valid continuity evidence. `_matched_draft` temporarily contracts the family and marks a representative change. `_settle_pending_role_reversal_drafts` then correctly restores the complete prior member set and prior representative for the reversal snapshot, but it does not clear the draft's stale `representative_changed` flag.

Independent result:

```text
provider supplies one valid new-role candidate matching a non-representative prior rail
final frozen reversal state restores the old representative
update fails:
ContractValidationError: representative_changed must match representative IDs
```

Even if the transition contract did not reject it, the stale flag would incorrectly add the family to `event_reset_family_ids`, potentially replacing the Phase-F role-reversal event with a new episode.

### Required correction

After role-reversal settlement, derive all representative-change facts from the **final persisted draft state**:

```text
representative_changed =
    previous representative_member_id != final representative_member_id
```

For an applied Phase-F role reversal, the value must be `false` because the approved reversal snapshot preserves the representative member.

Also ensure:

- `representative_changed` reason code is removed when settlement restores the representative;
- event reset IDs use final persisted representative identity;
- the `ROLE_REVERSED` event remains on the same Phase-F event ID;
- partial new-role group evidence cannot contract/refit the frozen reversal snapshot.

Required tests:

- new-role group contains only the prior non-representative rail;
- new-role group omits the prior representative;
- complete new-role group;
- no group/new-role abstention path;
- both SUPPORT -> RESISTANCE and RESISTANCE -> SUPPORT;
- all paths preserve the same Phase-F event and exact member set on the reversal snapshot.

---

## P1 — Corridor bounds are not bound to the ordered exact rails

Locations:

```text
src/libs/models/trendline_family/contracts.py
  FamilyCorridor
  TrendlineFamilySnapshot
```

The contract validates rail ordering, offsets, width arithmetic and center/representative identity, but it does not require:

```text
lower_price == first ordered rail projected_price
upper_price == last ordered rail projected_price
```

Independent adversarial reconstruction expanded both bounds beyond the exact rails, recomputed the width and content-addressed corridor ID, and was accepted:

```text
exact projected rails: [100.0, 100.4]
forged corridor:       [99.9, 100.5]
snapshot contract:     ACCEPTED
```

This permits the persisted structural corridor to be wider than its canonical rail envelope while all exact rail records remain unchanged.

### Required correction

Enforce in `FamilyCorridor.__post_init__` and independently at the snapshot boundary:

```text
lower_price == rails[0].projected_price
upper_price == rails[-1].projected_price
center_price == projected price of representative_member_id
width_absolute == upper_price - lower_price
```

Keep singleton semantics unchanged.

Required tests:

- widened lower/upper bounds rejected;
- shifted equal-width bounds rejected;
- representative center not equal to its rail projection rejected;
- lower/upper mismatch rejected for two and three rails;
- valid singleton and multi-rail corridors continue to replay.

---

## P1 — Typed membership audit is not cross-bound to the resulting family

Locations:

```text
src/libs/models/trendline_family/contracts.py
  FamilyTransition
  TrendlineFamilySnapshot
```

The runtime constructs correct membership audit fields, but the persistence contract validates only field types and disjointness. It does not bind the audit to the published family or enforce content-addressed sensitivity.

The following forged birth transitions were all accepted by the containing snapshot:

```text
current_rail_count = 99
added_member_ids = ()
current_representative_member_id = None
duplicate matched_candidate_ids
```

The original transition ID was left unchanged and remained accepted.

This weakens the required auditable evidence for member additions, continuations, removals and representative changes.

### Required correction

For Phase-G snapshots, enforce:

```text
current_rail_count == len(current family members)
set(added_member_ids) | set(continued_member_ids)
    == set(current family member IDs)
current_representative_member_id
    == family.representative_member_id
```

General count identities:

```text
previous_rail_count == len(continued_member_ids) + len(removed_member_ids)
current_rail_count  == len(continued_member_ids) + len(added_member_ids)
```

State-specific rules:

- `BIRTH`: previous count zero, no previous representative, all current members added, none continued/removed;
- `EXPIRE`: current count zero, no current representative, no added/continued members;
- continuation/reactivation/dormancy/reversal: audit sets and representative IDs must be coherent with the resulting family;
- `matched_candidate_ids` must be unique.

Recompute the Phase-G family transition ID from the complete transition payload plus resulting family state when `rail_grouping_enabled=true`. Gate this stricter recomputation so legacy Phase-F payloads remain decodable.

Required adversarial tests for every field mutation and count/set mismatch.

---

## P1 — Phase-G nearest-rail features are not solely derived from persisted truth

Location:

```text
src/libs/models/trendline_family/features.py
  build_interaction_features
  _corridor_features
```

The feature builder accepts an external `current_price` and uses it to calculate:

```text
nearest_rail_member_id
nearest_rail_distance_atr
current_corridor_position
```

The same immutable snapshot produced different semantic Phase-G features when called with two different prices:

```text
current_price=100.0
-> nearest lower rail, distance 0.0, position 0.0

current_price=1000.0
-> nearest upper rail, distance 449.8 ATR, position 2250
```

The snapshot already contains the confirmed close in its typed observations. Therefore the Phase-G feature surface is not currently reproducible from serialized persisted state alone.

### Required correction

Derive the price for corridor/nearest-rail features from the current typed `FamilyInteractionObservation.close_price` for that family.

Preferred behavior:

- remove the external semantic `current_price` dependency from `build_interaction_features`; or
- retain it only as an assertion and reject any value that does not match the persisted confirmed close.

Do not permit callers to change semantic features while keeping the same snapshot ID.

Required tests:

- serialize/deserialize snapshot, rebuild features with no OHLCV frame, and obtain byte-identical Phase-G semantic fields;
- supplied mismatched external current price is rejected or ignored;
- support/resistance role features use their persisted observation close;
- singleton position remains explicitly `None` if that is the chosen policy.

---

## P2 — Grouping rejection diagnostics lose the actual rejection cause

Location:

```text
src/libs/models/trendline_family/rails.py
  group_rail_candidates
  _candidate_fits_group
  _pair_rejection_reason
```

Specific internal reasons exist:

```text
slope_delta_exceeds_maximum
crossing_rails
spacing_below_minimum
```

But the public diagnostic records only:

```text
complete_linkage_rejected
```

Adjacent-gap and total-width rejections are also collapsed into that generic label.

The Phase-G handoff requires auditable grouping rejection reason distributions. Preserve deterministic specific reasons, including group-level adjacent-gap and corridor-width rejection, while optionally retaining the generic complete-linkage category as a higher-level classification.

This is not independently sufficient to block Phase G, but it should be corrected in the same bounded remediation because the artifact field already exists.

---

# Validation Coverage Gaps

The current tests cover many happy paths but do not exercise:

- continuation through a surviving non-representative outer rail outside the representative gate;
- dormant reactivation through a non-representative rail;
- old-role provider output on a multi-rail reversal bar;
- partial new-role reversal groups that omit the representative;
- mixed duplicate/residual birth groups during reversal;
- corridor lower/upper forgery;
- family-transition audit mutation and transition-ID sensitivity;
- feature reconstruction from only a deserialized snapshot;
- fresh-repository byte-identical multi-rail replay over membership changes and role reversal.

An independent two-update candidate-permutation replay was byte-identical, which is positive evidence, but it does not cover the state transitions above.

---

# Blast Radius

Expected remediation scope:

```text
src/libs/models/trendline_family/matching.py
src/libs/models/trendline_family/rails.py
src/libs/models/trendline_family/tracker.py
src/libs/models/trendline_family/contracts.py
src/libs/models/trendline_family/features.py
src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py
tests/models/trendline_family/
tests/models/regime_v2/adapters/
```

`corridors.py` may need a narrow adjustment if corridor construction is centralized there.

No change should be required in:

```text
src/apps/signal_app/pipeline/
src/apps/signal_app/runtime/worker.py
active RegimeV2
selection
probability
MoE
overlay
risk
strategy
execution
```

Do not begin Phase H.

---

# Bounded Codex Remediation Handoff

Apply Phase-G remediation only from this review.

Required work:

1. Make group-to-family association recognize exact continuation through any prior member, including a non-representative surviving rail outside the representative-level gate.
2. Use member-specific anchor evidence rather than `family.members[0]` as a family-wide proxy.
3. Make role-reversal duplicate suppression operate against every prior member and filter suppressed candidates from mixed birth groups.
4. Recompute `representative_changed`, representative reason codes and event-reset membership from the final settled reversal state.
5. Bind corridor lower/upper/center values exactly to ordered rail projections.
6. Cross-bind Phase-G membership audit fields and counts to the resulting family, require unique matched candidate IDs, and validate content-addressed transition identity for Phase-G snapshots.
7. Derive nearest-rail/corridor-position features from persisted observation close evidence.
8. Preserve specific grouping rejection reasons.
9. Add adversarial tests for every reproduced failure and repeat all Phase-F/Phase-E invariance suites.

Preserve:

- exact geometry ownership by `FamilyMember`;
- representative as one exact member;
- Phase-F event semantics;
- one event per family;
- corridor/interaction-zone/uncertainty separation;
- default-disabled shadow integration;
- projected-lane exactly-once behavior;
- active-decision invariance;
- legacy Phase-F snapshot decoding.

Forbidden:

- Phase-H MTF composition;
- horizontal zones;
- learned clustering;
- split/merge graph optimization;
- optimizer/promotion work;
- active policy consumption;
- signal-pipeline or worker redesign.

Validation:

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family -q

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
```

Normal Ruff currently requires the unrelated duplicate `flipper-conductor` key in `pyproject.toml` to be resolved. Do not modify unrelated conductor code as part of Phase-G remediation unless the user explicitly authorizes that separate cleanup.

Reindex codebase-memory and report project, nodes, edges, status and bounded changed-file scope.

Stop after remediation. Phase H remains blocked pending re-review.
