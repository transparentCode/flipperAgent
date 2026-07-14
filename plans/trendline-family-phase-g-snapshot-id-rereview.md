# Trendline Family Model — Phase G Snapshot Identity Re-review

## Current Mode

Final Phase-G approval review.

## Decision

**Revision required. Phase H remains blocked.**

The final remediation closes every previously reported repository-lineage issue:

- Phase-G diagnostic downgrade is rejected;
- membership-transition coverage is complete;
- membership partitions are derived from previous/current state;
- lifecycle and role transition labels are causally constrained;
- Phase-G transition timestamps must equal the current snapshot timestamp;
- typed `FamilySourceGroupAudit` records bind canonical candidate content and transition provenance;
- rejected saves preserve the repository head.

One aggregate identity blocker remains: `TrendlineFamilyTracker` generates a content-addressed `snapshot_id`, but `TrendlineFamilySnapshot` and `InMemoryTrendlineFamilyRepository` do not verify that the supplied ID matches the complete persisted Phase-G payload.

---

## Validation Reproduced

### Trendline-family suite

```text
241 passed
```

### Trendline-family, shadow adapters and projected runtime

```text
269 passed
```

### Active RegimeV2, selection and signals

```text
148 passed
```

One unrelated OpenTelemetry `LoggingHandler` deprecation warning remains.

### Static validation

```text
Ruff: passed
compileall: passed
git diff --check: passed
```

### Codebase-memory

```text
Users-aloobhujia-flipperAgent
40,729 nodes
132,398 edges
status: ready
```

`detect_changes` still omits the untracked canonical trendline-family package. Direct source inspection, git status and executed suites remain the scope evidence of record.

---

# Verified Closed Findings

## Monotonic Phase-G activation

A repository whose previous head has:

```text
rail_grouping_enabled = true
```

now rejects a current snapshot that removes or disables that diagnostic. The rejected save leaves the prior serialized head unchanged.

## Causal family-transition labels

Repository lineage now derives legal transition semantics from previous/current family state.

Verified rejected cases include:

- ACTIVE → ACTIVE relabeled `REACTIVATE`;
- ACTIVE → DORMANT relabeled `CONTINUE`;
- DORMANT → ACTIVE relabeled `CONTINUE`;
- role change labeled `CONTINUE`, `STRENGTHEN` or `WEAKEN`;
- `ROLE_REVERSED` without a role change.

Matched ACTIVE transitions are also constrained by actual confidence evolution.

## Current transition timestamps

Every Phase-G family transition now requires:

```text
transition.timestamp == snapshot.timestamp
```

Both stale and future transition timestamps are rejected.

## Typed source-group provenance

`FamilySourceGroupAudit` now persists bounded canonical evidence:

- asset/timeframe/role/timestamp;
- ordered candidate IDs;
- canonical `LineCandidate` records;
- candidate content hashes;
- model/config identity;
- content-addressed source-group ID.

Snapshot validation requires source-group audits to exactly cover transition provenance. Repository validation cross-checks the referenced audit with the snapshot and resulting family.

## Atomicity and runtime preservation

Independent probes confirmed all prior attacks are rejected without replacing the repository head.

All approved Phase-G runtime behavior remains green, including member-aware continuation, corridors, representative handling, role reversal, event preservation, shadow isolation and projected-lane exactly-once updates.

---

# Remaining Blocking Finding

## P0 — Phase-G snapshot ID is not verified against the complete persisted payload

Locations:

```text
src/libs/models/trendline_family/tracker.py
  TrendlineFamilyTracker._snapshot_id

src/libs/models/trendline_family/contracts.py
  TrendlineFamilySnapshot

src/libs/models/trendline_family/repository.py
  InMemoryTrendlineFamilyRepository._validate_lineage
```

The tracker computes a deterministic `family-snapshot` ID from:

- snapshot identity and lineage;
- active and dormant families;
- family transitions;
- source-group audits;
- corridors;
- observations;
- interaction events and transitions;
- diagnostics.

However, the snapshot contract accepts any non-empty `snapshot_id`, and the repository only checks that the current ID differs from the previous ID. Neither boundary recomputes the expected Phase-G snapshot ID.

### Independent reproduction

A valid role-reversal snapshot was modified as follows:

1. Change canonical source-group candidate diagnostics.
2. Recompute the candidate content hashes.
3. Recompute the `FamilySourceGroupAudit.source_group_id`.
4. Recompute the family transition ID using the new source-group ID.
5. Keep the original snapshot ID unchanged.

The modified audit and transition were internally valid and content-addressed, but the enclosing snapshot ID was stale.

Observed result:

```text
snapshot_id_unchanged True
audit_changed True
stale_snapshot_id_ACCEPTED
```

This means the repository can persist two different complete Phase-G payloads under the same claimed snapshot identity.

### Why this blocks Phase H

Phase H will compose asynchronous snapshots from several timeframes and rely on snapshot IDs for lineage, caching, replay and audit references. A snapshot ID that is not cryptographically/content-addressedly bound to its complete payload cannot safely serve as an MTF source identity.

---

# Required Correction

Keep the correction narrowly scoped to snapshot identity.

## 1. Create one canonical Phase-G snapshot identity helper

Move or extract the payload construction currently owned privately by:

```text
TrendlineFamilyTracker._snapshot_id
```

into one canonical helper owned by contracts or a dedicated identity module, for example:

```text
trendline_family_snapshot_identity_payload(...)
compute_trendline_family_snapshot_id(...)
```

The helper must include exactly:

```text
asset
timeframe
timestamp
previous_snapshot_id
model_version
config_version
resolved_config_hash
active_families
dormant_families
transitions
source_group_audits
corridors
observations
interaction_events
interaction_event_transitions
diagnostics
```

It must exclude `snapshot_id` itself.

The tracker and validation boundary must call the same helper. Do not maintain two independently copied payload definitions.

## 2. Validate every Phase-G snapshot ID

When:

```text
diagnostics["rail_grouping_enabled"] is true
```

require:

```text
snapshot.snapshot_id == compute_trendline_family_snapshot_id(snapshot payload)
```

Validation may occur in `TrendlineFamilySnapshot.__post_init__`, the repository boundary, or both. Contract-level validation is preferred because it rejects corrupted serialized snapshots before persistence.

## 3. Preserve legacy compatibility

Legacy Phase-F snapshots whose lineages never entered Phase G may retain historical arbitrary/non-content-addressed IDs.

Do not retroactively require the Phase-G ID algorithm for event-free or Phase-F snapshots without the Phase-G diagnostic flag.

A Phase-G lineage still cannot downgrade to legacy mode.

## 4. Preserve atomicity

A stale or forged Phase-G snapshot ID must fail before repository-head replacement.

## 5. Keep all existing IDs stable

Valid tracker-produced Phase-G snapshot IDs must remain byte-identical to the current algorithm.

Do not introduce a version bump or alter the canonical payload ordering unless unavoidable. The preferred change is extraction and validation of the existing algorithm, not redesign.

---

# Required Tests

Add focused tests for:

1. A tracker-produced Phase-G snapshot passes canonical ID validation.
2. Deterministic replay retains byte-identical snapshot IDs.
3. Changing only a source-group audit while retaining the old snapshot ID is rejected.
4. Changing a source-group audit and recomputing its audit and transition IDs, while retaining the old snapshot ID, is rejected.
5. Changing only a family transition while retaining the old snapshot ID is rejected.
6. Changing only corridor state while retaining the old snapshot ID is rejected.
7. Changing only observation/event state while retaining the old snapshot ID is rejected.
8. Changing only diagnostics while retaining the old snapshot ID is rejected.
9. An arbitrary Phase-G `snapshot_id` is rejected.
10. Recomputing the expected Phase-G snapshot ID for an otherwise valid payload succeeds.
11. A rejected stale-ID save leaves the repository head byte-identical.
12. Legacy Phase-F snapshots remain accepted.

At minimum, include the exact source-group mutation reproduction above.

---

# Blast Radius

Expected correction scope:

```text
src/libs/models/trendline_family/contracts.py
src/libs/models/trendline_family/tracker.py
src/libs/models/trendline_family/repository.py  # only if validation is repository-owned or duplicated defensively
src/libs/models/trendline_family/__init__.py    # only if exporting the canonical helper
focused tests/models/trendline_family/
```

Do not modify:

```text
candidate grouping
member matching
family lifecycle
interaction/event lifecycle
shadow adapter behavior
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

---

# Architecture Drift Check

Verified:

- no runtime imports from legacy trendline packages;
- YAML reads remain confined to `config_loader.py`;
- exact rails, corridors, interaction zones and uncertainty remain separate;
- Phase-F events still use the exact representative rail;
- no incomplete/future-bar path was introduced;
- active RegimeV2 and selection regression suites remain unchanged;
- no Phase-H/MTF implementation exists.

The worktree contains unrelated conductor and base-config changes. They remain outside this review.

---

# Codex Remediation Prompt

```text
Apply the final Phase-G snapshot identity correction only.

Read:
- plans/trendline-family-phase-g-review.md
- plans/trendline-family-phase-g-rereview.md
- plans/trendline-family-phase-g-final-rereview.md
- plans/trendline-family-phase-g-snapshot-id-rereview.md
- plans/trendline-family-phase-f-approval.md
- plans/trendline-family-codex-phase-execution-plan.md
- plans/trendline-family-model-architecture-plan.md

Do not begin Phase H.

Objective:
Make the existing Phase-G snapshot ID algorithm canonical and enforce it against the complete persisted Phase-G payload.

Required outcomes:

1. Extract one shared helper for the current `family-snapshot` identity payload and deterministic ID.
2. The tracker uses that helper; do not duplicate the payload definition.
3. Every snapshot with `rail_grouping_enabled=true` must have the exact expected content-addressed snapshot ID.
4. The ID must bind families, transitions, source-group audits, corridors, observations, events, diagnostics and lineage.
5. A changed source-group audit with recomputed audit/transition IDs but a stale snapshot ID must be rejected.
6. Rejected saves preserve the repository head.
7. Existing valid tracker-produced IDs remain byte-identical.
8. Legacy Phase-F snapshots remain backward-compatible.
9. Preserve all current Phase-G runtime, event, shadow and projected-lane behavior.

Add adversarial tests for stale IDs after source-audit, transition, corridor, observation/event and diagnostic mutations, plus deterministic replay and legacy compatibility.

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

Reindex codebase-memory and report project, node count, edge count, status, changed-file scope and impacted symbols.

Stop after this Phase-G correction. Phase H remains blocked pending approval.
```
