# Trendline Family Model — Phase G Re-review

## Current Mode

Quant re-review.

## Decision

**Revision required. Phase H remains blocked.**

The Phase-G remediation closes the runtime continuity, role-reversal, corridor, feature-truth, and grouping-diagnostic findings from the first review. One persistence-lineage blocker remains: Phase-G family membership transitions are still optional and can be replaced with causally false membership audit evidence that the repository accepts.

---

## Validation Reproduced

### Trendline-family suite

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_g_rereview \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family -q -p no:cacheprovider

217 passed
```

### Phase-G plus shadow and projected runtime

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_g_rereview \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  -q -p no:cacheprovider

245 passed
```

### Active RegimeV2, selection, and signals

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_g_rereview \
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
40,492 nodes
129,747 edges
status: ready
```

`detect_changes` continues to under-report the untracked canonical trendline-family package. Direct source inspection, git status, and executed tests remain the scope evidence of record.

---

# Verified Remediations

## Member-aware family continuation

`greedy_match_rail_groups()` now evaluates exact prior-member continuations in addition to representative-level evidence.

Verified:

- an exact non-representative outer rail retains the prior family ID even when it is outside the representative distance gate;
- dormant multi-rail families can reactivate through a valid non-representative member;
- deterministic one-to-one member matching remains intact.

## Role-reversal duplicate filtering

The tracker now checks stale old-role candidates against every prior exact member and rebuilds a content-addressed residual group after filtering.

Verified:

- stale old-role copies of all rails do not birth duplicate lineage;
- a genuinely independent residual old-role rail may still birth separately;
- mixed suppressed/residual groups are handled deterministically;
- both role directions pass.

## Final-state representative and event handling

After reversal settlement, `representative_changed` and its reason code are recalculated from the final persisted state.

Verified:

- a partial new-role group on the reversal bar preserves the prior representative and all member identities;
- the Phase-F event ID is preserved;
- no false event reset occurs;
- the persisted event reaches `ROLE_REVERSED` normally.

## Corridor binding

`FamilyCorridor` and `TrendlineFamilySnapshot` now bind:

- lower price to the first exact projected rail;
- upper price to the last exact projected rail;
- center price to the exact representative rail;
- width and ATR-normalized offsets to persisted geometry and normalization ATR.

The previous forged widened-corridor case is rejected.

## Snapshot-derived corridor features

Nearest-rail distance and corridor position now use the persisted typed observation close.

The legacy `current_price` argument is assertion-only and cannot alter semantic output. A mismatched external price is rejected.

## Specific grouping diagnostics

Grouping now records concrete rejection reasons such as:

```text
slope_delta_exceeds_maximum
crossing_rails
spacing_below_minimum
adjacent_gap_exceeds_maximum
corridor_width_exceeds_maximum
```

while retaining `complete_linkage_rejected` as the aggregate grouping outcome.

---

# Remaining Blocking Finding

## P0 — Phase-G membership transition history is optional and forgeable across repository lineage

Locations:

```text
src/libs/models/trendline_family/contracts.py
  FamilyTransition
  TrendlineFamilySnapshot

src/libs/models/trendline_family/repository.py
  InMemoryTrendlineFamilyRepository._validate_lineage
```

The remediated snapshot contract validates each supplied transition against the resulting family and content-addresses its payload. However:

1. It does not require Phase-G family-transition coverage.
2. It cannot validate previous-membership claims without the prior snapshot.
3. The repository lineage validator checks snapshot linkage and family versions, but does not compare transition audit evidence with the previous and current family states.

### Independent reproduction A — transition can be removed

A real singleton-to-two-rail update emitted a valid membership transition. Replacing:

```text
snapshot.transitions
```

with:

```text
()
```

was accepted by `TrendlineFamilySnapshot` and persisted by a fresh repository after the genuine previous snapshot.

Observed result:

```text
missing_transition_saved 0
```

This means a membership change can be persisted without the required added/continued/removed audit.

### Independent reproduction B — false membership history can be persisted

For a genuine singleton-to-two-rail continuation, the real audit was equivalent to:

```text
continued = {existing member}
added     = {new member}
removed   = {}
```

The transition was replaced with internally self-consistent but false evidence:

```text
continued = {}
added     = {both current members}
removed   = {fabricated old member}
matched_candidate_ids = {fabricated candidate}
```

After recomputing the transition ID from that forged payload and the real resulting family state, both the snapshot and repository accepted it.

Observed result:

```text
forged_audit_saved
  added       = both current member IDs
  continued   = ()
  removed     = (fabricated-old-member,)
  matched     = (fabricated-candidate,)
```

The transition is content-addressed, but its causal claims are not bound to repository lineage.

### Why this blocks Phase H

Phase H will consume asynchronous snapshots and rely on stable family/member continuity across timeframes. If a stored Phase-G snapshot can omit or falsify membership evolution, MTF continuity, confluence, and conflict audit cannot treat the repository as the source of truth.

---

# Required Correction

Keep the correction bounded to Phase-G persistence and contracts.

## 1. Require complete family-transition coverage for Phase-G snapshots

When `rail_grouping_enabled == true`, enforce exactly one current family transition per tracker update outcome:

- every newly published family has one `BIRTH` transition;
- every continuing or reactivated published family has one non-`BIRTH`, non-`EXPIRE` transition;
- every family removed from the prior repository head has one `EXPIRE` transition;
- no duplicate transitions for one family;
- no unrelated transition may be supplied.

Because removed families are not present in the current snapshot, complete expiry coverage must be enforced at the repository boundary where both snapshots are available.

Legacy Phase-F snapshots without the Phase-G diagnostics flag remain compatible.

## 2. Validate membership audit against previous and current snapshots

In `InMemoryTrendlineFamilyRepository._validate_lineage()` or one canonical helper called there, derive:

```text
previous_member_ids
current_member_ids

expected_added     = current - previous
expected_continued = current & previous
expected_removed   = previous - current
```

Require transition fields to equal those exact sets and require:

```text
previous_rail_count == len(previous members)
current_rail_count  == len(current members)
previous_representative_member_id == previous representative
current_representative_member_id  == current representative
representative_changed == (previous representative != current representative)
```

For `BIRTH`:

```text
previous count = 0
previous representative = None
added = all current member IDs
continued = removed = ()
```

For `EXPIRE`:

```text
current count = 0
current representative = None
removed = all previous member IDs
added = continued = ()
```

For `ROLE_REVERSED`, additionally preserve the approved identity rule:

```text
added = removed = ()
continued = every prior/current member ID
same representative member ID
exact geometry and anchors preserved
role changes consistently
```

## 3. Constrain matched-candidate audit

Apply every inference that is possible from persisted state:

- `BIRTH`: matched candidate IDs equal the current members' candidate IDs;
- unmatched lifecycle transitions with `association_score is None`: matched candidate IDs must be empty;
- ordinary matched continuation/reactivation transitions: matched candidate IDs must correspond to the current matched group/member candidate evidence;
- `ROLE_REVERSED`: preserve the documented reversal-bar exception, but do not accept arbitrary fabricated IDs.

If existing persisted state is insufficient to validate the reversal-bar or group-level candidate evidence, add one minimal typed/content-addressed source-group audit field rather than leaving `matched_candidate_ids` unconstrained.

Do not persist full candidate histories or implement Phase-H lineage graphs.

## 4. Preserve atomicity

Any lineage/audit mismatch must fail before replacing the repository head.

Add a regression proving the prior head remains byte-identical after each rejected snapshot.

---

# Required Tests

Add focused tests under `tests/models/trendline_family/` for:

- Phase-G current family change with `transitions=()` rejected;
- new family without `BIRTH` rejected;
- continuing family without a transition rejected;
- removed family without `EXPIRE` rejected;
- duplicate family transition rejected;
- false added/continued/removed partition rejected;
- fabricated removed member ID rejected;
- false previous/current rail counts rejected across lineage;
- false previous/current representative IDs rejected across lineage;
- false `representative_changed` rejected across lineage;
- fabricated matched candidate ID rejected;
- role-reversal membership/geometry/anchor drift rejected;
- failed save leaves repository head unchanged;
- genuine singleton growth, contraction, dormancy, reactivation, expiry, and role reversal still persist;
- legacy Phase-F repository lineage remains accepted.

---

# Blast Radius

Expected correction scope:

```text
src/libs/models/trendline_family/contracts.py
src/libs/models/trendline_family/repository.py
src/libs/models/trendline_family/tracker.py  # only if minimal typed source audit is needed
tests/models/trendline_family/
```

Potentially:

```text
src/libs/models/trendline_family/matching.py
src/libs/models/trendline_family/rails.py
```

only if a minimal persisted source-group audit is required for matched-candidate validation.

Do not modify:

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

---

# Architecture Drift Check

Verified:

- no runtime imports from legacy trendline packages;
- YAML remains confined to the canonical config loader;
- exact rails remain separate from corridors, interaction zones, and uncertainty;
- Phase-F events continue to use the exact representative rail;
- no incomplete/future-bar path was introduced;
- active decision invariance remains green;
- no Phase-H source implementation was found.

The worktree also contains unrelated conductor and `pyproject.toml` changes. They are outside the Phase-G review and must not be folded into the remediation.

---

# Codex Remediation Prompt

```text
Remediate the final Phase-G persistence blocker only.

Read:
- plans/trendline-family-phase-g-review.md
- plans/trendline-family-phase-g-rereview.md
- plans/trendline-family-phase-f-approval.md
- plans/trendline-family-codex-phase-execution-plan.md
- plans/trendline-family-model-architecture-plan.md

Do not begin Phase H.

Objective:
Make Phase-G family membership transitions mandatory and causally bound to the previous and current repository snapshots.

Required outcomes:
1. A Phase-G family change cannot be persisted without exactly one appropriate FamilyTransition.
2. The repository derives and validates exact added, continued, and removed member-ID sets from previous/current family states.
3. Previous/current rail counts and representative IDs are exact.
4. BIRTH, continuation/reactivation, ROLE_REVERSED, and EXPIRE transition coverage is complete and deterministic.
5. Matched-candidate audit cannot contain fabricated IDs; persist one minimal typed source-group fact only if current state cannot validate it.
6. Any mismatch fails before repository-head replacement.
7. Legacy Phase-F snapshots remain backward-compatible.
8. Preserve all approved Phase-G runtime behavior and shadow-only decision invariance.

Add adversarial repository-lineage tests for omitted transitions, forged membership partitions, fabricated removed/member/candidate IDs, representative mismatch, missing EXPIRE/BIRTH, duplicate transitions, role-reversal drift, and unchanged head after rejection.

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

Reindex codebase-memory and report project, node count, edge count, status, changed files, and impacted symbols.

Stop after this Phase-G correction. Phase H remains blocked pending final approval.
```
