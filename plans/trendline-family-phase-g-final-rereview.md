# Trendline Family Model — Phase G Final Re-review

## Current Mode

Final Phase-G approval review.

## Decision

**Revision required. Phase H remains blocked.**

The latest remediation correctly closes the original missing-transition and false member-partition blocker. The repository now derives membership sets from previous/current family state and rejects omitted or false added/continued/removed evidence atomically.

Final adversarial review found three remaining persistence-lineage defects:

1. Phase-G enforcement can be disabled by removing the current snapshot diagnostic flag.
2. Family transition type and transition timestamp are not causally derived from previous/current state.
3. Reversal source-group provenance remains a self-consistent but arbitrarily forgeable candidate-ID claim.

These are bounded repository/contract audit issues. No Phase-G runtime grouping redesign is required.

---

## Validation Reproduced

### Trendline-family suite

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_g_final \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  -q -p no:cacheprovider

226 passed
```

### Trendline-family, shadow adapters, and projected runtime

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_g_final \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  -q -p no:cacheprovider

254 passed
```

### Active RegimeV2, selection, and signals

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_g_final \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals \
  -q -p no:cacheprovider

148 passed
```

One unrelated OpenTelemetry `LoggingHandler` deprecation warning remains.

### Static validation

```text
Ruff: passed
compileall: passed
git diff --check: passed
```

Ruff is installed at:

```text
/Users/aloobhujia/.local/bin/ruff
```

It is not installed inside `.venv`.

### Codebase-memory

```text
Users-aloobhujia-flipperAgent
40,685 nodes
131,902 edges
status: ready
```

`detect_changes` still under-reports the untracked canonical trendline-family package. Direct source inspection, focused tests, and git status remain the Phase-G scope evidence of record.

---

# Verified Closed Findings

## Complete transition coverage under an enabled Phase-G snapshot

`TrendlineFamilySnapshot` now requires one non-expiry transition per published family.

`InMemoryTrendlineFamilyRepository` requires transition-family coverage equal to:

```text
previous family IDs union current family IDs
```

Verified outcomes include:

- missing current-family transition rejected;
- duplicate transition for one family rejected;
- missing `BIRTH` rejected;
- missing `EXPIRE` rejected;
- unrelated family transition rejected.

## Membership audit derived from repository lineage

The repository now derives:

```text
added     = current member IDs - previous member IDs
continued = current member IDs intersect previous member IDs
removed   = previous member IDs - current member IDs
```

It also validates:

- previous/current rail count;
- previous/current representative member ID;
- `representative_changed`;
- birth and expiry membership semantics;
- role-reversal member IDs, representative, geometry, anchors and role change.

The previously accepted fabricated member partition is now rejected.

## Matched-candidate binding for normal structural updates

For ordinary birth and matched continuation, `matched_candidate_ids` are bound to the current family members' candidate IDs.

Unmatched lifecycle updates reject matched-candidate and source-group evidence.

## Repository atomicity

Lineage validation runs before repository-head replacement. Focused tests confirm rejected saves preserve the prior serialized head.

## Runtime Phase-G behavior

All previously reviewed runtime fixes remain green:

- non-representative member continuation;
- dormant reactivation through a valid outer rail;
- old-role reversal duplicate suppression;
- mixed residual group handling;
- final representative/event coherence;
- exact corridor bounds;
- snapshot-derived nearest-rail features;
- specific grouping rejection diagnostics;
- shadow-only active-decision invariance;
- projected-lane exactly-once behavior.

---

# Remaining Blocking Findings

## P0 — Phase-G lineage enforcement can be downgraded off

Locations:

```text
src/libs/models/trendline_family/repository.py
  InMemoryTrendlineFamilyRepository._validate_lineage
  _phase_g_enabled

src/libs/models/trendline_family/contracts.py
  TrendlineFamilySnapshot.__post_init__
```

The repository invokes Phase-G lineage validation only when the **current** snapshot contains:

```text
diagnostics["rail_grouping_enabled"] is True
```

A genuine Phase-G previous snapshot was followed by a genuine Phase-G current snapshot modified to:

```text
remove rail_grouping_enabled from diagnostics
remove all family transitions
```

The snapshot and repository accepted it.

Independent result:

```text
phase_g_downgrade_accepted 0
```

This bypasses the complete transition and membership-lineage gate after Phase G has already been activated.

### Required correction

Phase activation must be monotonic for a repository lineage.

At minimum:

```text
previous_phase_g = previous exists and previous rail_grouping_enabled == true
current_phase_g  = current rail_grouping_enabled == true

if previous_phase_g and not current_phase_g:
    reject before persistence

validate Phase-G lineage when previous_phase_g or current_phase_g
```

Legacy Phase-F compatibility remains valid only for lineages that have never entered Phase G.

Do not permit a Phase-G repository head to be followed by a diagnostic downgrade that removes corridor/transition requirements.

---

## P0 — Transition type is not causally bound to lifecycle and role changes

Location:

```text
src/libs/models/trendline_family/repository.py
  _validate_phase_g_transition
```

The repository validates `BIRTH`, `EXPIRE`, and the special constraints **when** a transition is labeled `ROLE_REVERSED`. It does not derive which transition type is required from previous/current lifecycle and role state.

### Reproduction A — false reactivation

A genuine active-to-active matched continuation was relabeled:

```text
REACTIVATE
```

After recomputing the content-addressed transition ID, the repository accepted it.

```text
false_reactivate_accepted REACTIVATE
```

### Reproduction B — role change disguised as continuation

A genuine role-reversal snapshot was relabeled:

```text
CONTINUE
```

The source-group fields were made internally consistent with the ordinary matched path, and the repository accepted the family role change without a `ROLE_REVERSED` family transition.

```text
role_change_as_continue_accepted CONTINUE
```

This means family transition history can misrepresent reactivation, dormancy, continuation and role reversal even though membership sets are truthful.

### Required correction

Derive allowed/required transition semantics from previous/current family state.

Required minimum rules:

```text
previous missing, current present
  -> BIRTH only

previous present, current missing
  -> EXPIRE only

previous role != current role
  -> ROLE_REVERSED only

previous role == current role
  -> ROLE_REVERSED forbidden

previous lifecycle DORMANT, current ACTIVE
  -> REACTIVATE only

previous lifecycle ACTIVE, current DORMANT
  -> DORMANT only
```

For same-role, same-lifecycle updates, constrain transition types to the tracker-owned legal set:

```text
ACTIVE -> ACTIVE:
  CONTINUE / STRENGTHEN / WEAKEN

DORMANT -> DORMANT:
  the exact tracker-owned unmatched dormant transition type
```

Use `association_score`, confidence change, lifecycle change and role change where needed to distinguish the exact transition.

The repository must reject a content-addressed transition whose label does not describe the actual state evolution.

Add direct tests for:

- false `REACTIVATE` on active-to-active continuation;
- false `CONTINUE` on dormant-to-active reactivation;
- false `CONTINUE` on active-to-dormant transition;
- role change without `ROLE_REVERSED`;
- `ROLE_REVERSED` without a role change;
- normal tracker-produced transition types still persist.

---

## P1 — Current family transitions may use stale timestamps

Locations:

```text
src/libs/models/trendline_family/contracts.py
  TrendlineFamilySnapshot.__post_init__

src/libs/models/trendline_family/repository.py
  _validate_phase_g_transition
```

The generic snapshot contract requires only:

```text
transition.timestamp <= snapshot.timestamp
```

A current singleton-to-multi transition was changed to the previous snapshot timestamp. Its source-group and transition IDs were recomputed consistently.

The repository accepted it:

```text
stale_transition_timestamp_accepted
2024-01-02T00:00:00+00:00
2024-01-02T01:00:00+00:00
```

### Required correction

Every Phase-G transition carried by the current snapshot must use:

```text
transition.timestamp == snapshot.timestamp
```

This includes `BIRTH`, continuation, dormancy, reactivation, role reversal and expiry transitions emitted for that repository update.

Legacy Phase-F behavior may retain its prior contract.

---

## P1 — Reversal source-group provenance is still arbitrarily forgeable

Locations:

```text
src/libs/models/trendline_family/contracts.py
  FamilyTransition.source_group_id
  FamilyTransition.source_group_candidate_ids

src/libs/models/trendline_family/repository.py
  _validate_matched_candidate_audit
```

For a `ROLE_REVERSED` transition, the repository verifies only that:

```text
source_group_id == hash(asset, timeframe, current role, transition timestamp, candidate IDs)
```

It does not bind that source group to a canonical persisted group/candidate record from the current tracker update.

The real source group was replaced with:

```text
("fabricated-reversal-source",)
```

A matching group ID and transition ID were recomputed. The repository accepted it:

```text
fabricated_reversal_source_accepted
('fabricated-reversal-source',)
```

Content addressing makes the fabricated claim stable; it does not make the claim true.

### Required correction

Persist one bounded typed source-group audit record for groups referenced by family transitions, or another equivalent canonical evidence record.

Recommended contract:

```text
FamilySourceGroupAudit
  group_id
  asset
  timeframe
  role
  observed_at
  ordered candidate IDs
  bounded candidate identity/content hashes or canonical candidate records
  model/config identity
```

Required behavior:

- source-group audit ID is content-addressed;
- transition `source_group_id` references a source group persisted in the same snapshot;
- transition candidate IDs exactly match that persisted group;
- group asset/timeframe/role/timestamp/config identity match the snapshot and resulting family;
- ordinary matched transitions bind the source group to current member candidate IDs;
- reversal transitions may preserve frozen current-member candidate IDs separately, but their new-role source group must be a real persisted canonical group from the same update;
- unmatched lifecycle and expiry transitions contain no source group;
- no unbounded candidate history is accumulated.

A simpler design is acceptable when it provides equivalent typed, snapshot-local, cross-validated evidence. Candidate IDs plus a self-derived group ID alone are insufficient.

---

# Blast Radius

Expected final correction scope:

```text
src/libs/models/trendline_family/contracts.py
src/libs/models/trendline_family/repository.py
src/libs/models/trendline_family/tracker.py
src/libs/models/trendline_family/rails.py  # only if exporting a typed source-group audit
src/libs/models/trendline_family/repository.py
tests/models/trendline_family/test_phase_g_repository_lineage.py
focused event/reversal tests where provenance is asserted
```

No changes should be needed in:

```text
signal pipeline
projected worker
active RegimeV2
selection
overlay
MoE
MTF
strategy
risk
execution
```

Preserve all approved Phase-E/F behavior and all current Phase-G runtime behavior.

---

# Required Adversarial Tests

Add focused tests for:

1. Phase-G previous head followed by current snapshot with the Phase-G flag removed is rejected.
2. The failed downgrade leaves the repository head byte-identical.
3. Active-to-active continuation relabeled `REACTIVATE` is rejected.
4. Dormant-to-active reactivation relabeled `CONTINUE` is rejected.
5. Active-to-dormant update relabeled `CONTINUE` is rejected.
6. Role change relabeled `CONTINUE`, `STRENGTHEN`, or `WEAKEN` is rejected.
7. `ROLE_REVERSED` without a role change is rejected.
8. Transition timestamp earlier than the current snapshot timestamp is rejected.
9. Transition timestamp later than the current snapshot remains rejected.
10. Fabricated reversal source-group candidate IDs are rejected even after recomputing group and transition IDs.
11. Missing source-group record for a referenced source-group ID is rejected.
12. Source-group role, timestamp, config, or candidate mismatch is rejected.
13. Genuine birth, continuation, dormancy, reactivation, expiry and both role-reversal directions persist.
14. Legacy Phase-F-only repository lineage remains accepted.
15. Every rejected save preserves the prior serialized repository head.

---

# Architecture Drift Check

Verified:

- no runtime import from legacy trendline packages;
- YAML access remains confined to the canonical config loader;
- exact member geometry remains separate from corridors, interaction zones and uncertainty;
- Phase-F events still use the exact representative member;
- no incomplete or future-bar path was introduced;
- active RegimeV2 and SelectionLayer regression suites remain green;
- projected-lane exactly-once semantics remain green;
- no Phase-H module or MTF composition implementation exists.

The worktree contains unrelated conductor/config changes. They remain outside this review and must not be folded into the Phase-G remediation.

---

# Codex Remediation Prompt

```text
Apply the final Phase-G persistence/audit remediation only.

Read:
- plans/trendline-family-phase-g-review.md
- plans/trendline-family-phase-g-rereview.md
- plans/trendline-family-phase-g-final-rereview.md
- plans/trendline-family-phase-f-approval.md
- plans/trendline-family-codex-phase-execution-plan.md
- plans/trendline-family-model-architecture-plan.md

Do not begin Phase H.

Objective:
Close the remaining Phase-G repository audit bypasses without changing multi-rail runtime semantics.

Required outcomes:

1. Phase-G activation is monotonic within one repository lineage.
   - Once a repository head has rail_grouping_enabled=true, every subsequent snapshot must remain Phase G.
   - A diagnostic downgrade cannot bypass transition, corridor, or membership validation.
   - Legacy Phase-F-only lineages remain compatible.

2. FamilyTransition.transition_type is causally derived from previous/current family state.
   - BIRTH for new family only.
   - EXPIRE for removed family only.
   - ROLE_REVERSED exactly when role changes.
   - REACTIVATE exactly for DORMANT -> ACTIVE.
   - DORMANT exactly for ACTIVE -> DORMANT.
   - Same-role/same-lifecycle transitions use only tracker-legal continuation types.
   - Reject false labels even when transition IDs are recomputed.

3. Every Phase-G transition timestamp equals the containing snapshot timestamp.

4. Reversal source-group provenance references typed canonical source-group evidence persisted in the same snapshot.
   - Candidate IDs plus a self-derived group ID alone are not sufficient.
   - Bind group asset, timeframe, role, timestamp, candidate identity/content, and config identity.
   - Preserve the reversal distinction between frozen current-member candidate IDs and the new-role source group.
   - Keep the record bounded; do not persist unbounded candidate history.

5. Every rejection occurs before repository-head replacement.

6. Preserve all currently passing Phase-G grouping, continuity, corridor, feature, event, shadow, and projected-lane behavior.

Add adversarial tests for diagnostic downgrade, false lifecycle/role transition labels, stale transition timestamps, fabricated reversal source groups, source-group cross-field mismatches, and unchanged repository head after every rejected save.

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

Stop after this final Phase-G correction. Phase H remains blocked pending approval.
```
