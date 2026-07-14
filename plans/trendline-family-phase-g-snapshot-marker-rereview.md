# Trendline Family Model — Phase G Snapshot Marker Re-review

## Current Mode

Final Phase-G approval review.

## Decision

**Revision required. Phase H remains blocked.**

The shared canonical aggregate snapshot identity helper is correctly implemented and used by the tracker, snapshot contract, and repository. Stale aggregate IDs are rejected when the snapshot is classified as Phase G.

One bounded discriminator defect remains: on an empty repository, a Phase-G-shaped snapshot can remove the mutable `rail_grouping_enabled` diagnostic marker, remove source-group audits, retain Phase-G corridors/transitions and the original stale snapshot ID, and be accepted through the legacy compatibility path.

---

## Validation Reproduced

### Trendline-family suite

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_g_identity_final \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  -q -p no:cacheprovider

251 passed
```

### Family, shadow adapters, and projected runtime

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_g_identity_final \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  -q -p no:cacheprovider

279 passed
```

### Active RegimeV2, selection, and signals

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_g_identity_final \
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

### Codebase-memory

```text
Users-aloobhujia-flipperAgent
40,776 nodes
132,654 edges
status: ready
```

`detect_changes` still under-reports the untracked canonical package. Direct source inspection and executed tests remain the Phase-G scope evidence of record.

---

# Verified Closed Finding

## Aggregate snapshot identity now has one canonical owner

The shared helpers in `contracts.py` own:

```text
trendline_family_snapshot_identity_payload
compute_trendline_family_snapshot_id
validate_trendline_family_snapshot_identity
```

Verified:

- tracker-generated IDs use the shared payload;
- the Phase-G snapshot contract recomputes the same ID;
- repository persistence revalidates before replacing the head;
- transitions, source-group audits, corridors, observations, events, diagnostics, family state, config identity and previous snapshot ID all participate;
- changing a source-group candidate and recomputing its audit/transition IDs invalidates the stale aggregate snapshot ID;
- direct contract construction rejects arbitrary/stale Phase-G IDs;
- repository-side defensive validation rejects a corrupted object that bypasses dataclass construction;
- rejected persistence preserves the repository head;
- deterministic replay retains byte-identical snapshot IDs.

The prior source-audit aggregate identity blocker is closed.

---

# Remaining Blocking Finding

## P0 — Mutable diagnostic marker can route a Phase-G first snapshot through legacy validation

Locations:

```text
src/libs/models/trendline_family/contracts.py
  TrendlineFamilySnapshot.__post_init__
  validate_trendline_family_snapshot_identity

src/libs/models/trendline_family/repository.py
  _phase_g_enabled
  InMemoryTrendlineFamilyRepository._validate_lineage
```

Phase-G classification currently depends only on:

```text
snapshot.diagnostics["rail_grouping_enabled"] is True
```

The contract rejects source-group audits when that marker is absent, but it does not reject other Phase-G structural evidence such as corridors and rail membership transitions.

### Independent reproduction

A valid tracker-produced first Phase-G snapshot was modified to:

```text
remove diagnostics["rail_grouping_enabled"]
remove source_group_audits
retain Phase-G corridor
retain Phase-G BIRTH/membership transition
retain the original snapshot_id
```

Construction and first persistence succeeded:

```text
marker_audits ACCEPTED
members=1
corridors=1
transitions=1
snapshot_id=be628af8-a752-545d-9466-122df5853355
```

The retained snapshot ID was computed from the original payload that still contained the marker and source-group audit. It is stale for the downgraded payload, but identity validation returned early because the marker had been removed.

A more aggressively stripped form was also accepted as legacy:

```text
legacy_stripped ACCEPTED
members=1
corridors=0
transitions=0
same stale snapshot_id
```

The fully stripped payload is intentionally close to a historical legacy snapshot and may be indistinguishable without a durable schema discriminator. The directly actionable blocker is that clearly Phase-G-shaped payloads—corridors, rail membership audit, Phase-G diagnostics, source provenance or multi-rail state—can currently omit the marker and bypass identity enforcement on the initial repository save.

### Why this blocks Phase H

Phase H may bootstrap asynchronous composition from independently loaded per-timeframe heads. A forged or partially downgraded Phase-G head must not enter a fresh repository under legacy rules, because MTF lineage and caching would then trust an aggregate ID that does not bind the persisted payload.

---

# Required Correction

Introduce one canonical Phase-G payload classifier that is not based solely on one mutable diagnostic flag.

Recommended helper:

```text
trendline_family_snapshot_has_phase_g_evidence(snapshot) -> bool
```

Treat a snapshot as Phase-G-shaped when any of the following exists:

```text
rail_grouping_enabled is true
source_group_audits is non-empty
corridors is non-empty
any family has more than one member
any transition contains non-default Phase-G membership/provenance evidence:
  added_member_ids
  continued_member_ids
  removed_member_ids
  previous/current representative member ID
  previous/current rail count > 0
  source_group_id
  source_group_candidate_ids
Phase-G-only diagnostics such as:
  rail_group_count
  rail_grouping_rejection_reasons
  family_corridor_count
  rail membership/churn diagnostics
```

Exact classification details may follow repository conventions, but they must be centralized and shared by contract and repository.

Required behavior:

1. If Phase-G evidence exists and `rail_grouping_enabled` is not exactly `True`, reject the snapshot as an invalid downgrade/missing Phase-G marker.
2. If Phase-G evidence exists and the marker is true, require the canonical aggregate snapshot ID.
3. Once a repository lineage enters Phase G, retain the existing monotonic no-downgrade rule.
4. Historical Phase-C/D/F snapshots without any Phase-G evidence remain decodable and persistable with their legacy IDs.
5. Rejection occurs before repository-head replacement.

A stronger top-level immutable `snapshot_schema_version` discriminator is acceptable, but do not introduce a migration framework or Phase-H schema. The smallest shared classifier is preferred for this phase.

Do not solve the indistinguishable fully stripped payload by guessing from arbitrary UUID shape. Only reject objectively Phase-G-shaped payloads and preserve true historical compatibility.

---

# Required Tests

Add focused tests under `tests/models/trendline_family/` for:

- first repository snapshot with Phase-G corridor but missing marker rejected;
- first snapshot with Phase-G membership transition fields but missing marker rejected;
- first snapshot with multi-rail family but missing marker rejected;
- first snapshot with Phase-G diagnostics but missing marker rejected;
- source-group audit without marker remains rejected;
- stale aggregate ID cannot bypass validation by removing the marker while Phase-G evidence remains;
- rejection leaves an existing repository head unchanged;
- genuine tracker-produced first Phase-G snapshot persists;
- genuine Phase-G continuation persists;
- legacy Phase-C/D/F fixture with marker, corridors, source audits and Phase-G transition fields absent still decodes and persists;
- shared classifier produces identical result in contract and repository paths.

---

# Blast Radius

Expected correction scope:

```text
src/libs/models/trendline_family/contracts.py
src/libs/models/trendline_family/repository.py
src/libs/models/trendline_family/__init__.py  # only if exporting the shared classifier
tests/models/trendline_family/test_phase_g_snapshot_identity.py
focused legacy decode/repository tests
```

`tracker.py` should not require behavioral changes unless the helper signature is shared there for assertions.

Do not modify:

```text
candidate generation
rail grouping
family/member matching
corridor computation
Phase-F events
feature projection
shadow adapter
signal pipeline
projected worker
active RegimeV2
selection
MTF
strategy
risk
execution
```

---

# Architecture Drift Check

Verified:

- no runtime import from legacy trendline packages;
- YAML reads remain confined to `config_loader.py`;
- exact rails, family corridors, interaction zones and uncertainty remain separate;
- no future/incomplete-bar path was added;
- Phase-F event semantics remain green;
- active decision and projected-lane invariance remain green;
- no Phase-H or MTF composition implementation exists.

The worktree contains unrelated conductor/config changes outside this review.

---

# Codex Remediation Prompt

```text
Apply the final Phase-G snapshot discriminator correction only.

Read:
- plans/trendline-family-phase-g-review.md
- plans/trendline-family-phase-g-rereview.md
- plans/trendline-family-phase-g-final-rereview.md
- plans/trendline-family-phase-g-snapshot-id-rereview.md
- plans/trendline-family-phase-g-snapshot-marker-rereview.md
- plans/trendline-family-phase-f-approval.md
- plans/trendline-family-codex-phase-execution-plan.md
- plans/trendline-family-model-architecture-plan.md

Do not begin Phase H.

Objective:
Prevent a Phase-G-shaped first snapshot from removing the mutable diagnostic marker and bypassing canonical aggregate snapshot-ID validation through the legacy compatibility path.

Required outcomes:

1. Add one shared canonical classifier for Phase-G payload evidence.
2. Classify from structural evidence, not only diagnostics[rail_grouping_enabled].
3. Reject Phase-G evidence when the explicit marker is absent or false.
4. Require canonical aggregate snapshot identity whenever Phase-G evidence exists.
5. Preserve monotonic Phase-G repository lineage.
6. Preserve historical Phase-C/D/F snapshots that contain no Phase-G evidence.
7. Reject before repository-head replacement.
8. Preserve all current Phase-G runtime, shadow, and projected-lane behavior.

At minimum treat corridors, source-group audits, multi-member families, non-default rail membership/provenance transition fields, and Phase-G-only diagnostics as Phase-G evidence.

Add adversarial tests for marker stripping with corridors, membership transitions, multi-rail state, Phase-G diagnostics and stale aggregate IDs. Add explicit historical compatibility tests with all Phase-G fields absent.

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

Stop after this discriminator correction. Phase H remains blocked pending final approval.
```
