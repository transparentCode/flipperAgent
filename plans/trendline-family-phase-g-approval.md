# Trendline Family Model — Phase G Approval

## Current Mode

Quant approval.

## Approval Scope

Phase G deterministic multi-rail trendline families, including:

- deterministic complete-linkage grouping of same-role exact line candidates;
- pairwise-safe slope, crossing, spacing and corridor-width gates;
- stable family and exact member/rail identity across confirmed updates;
- member-aware continuation through any valid exact rail, not only the representative;
- singleton-to-multi-rail growth and multi-rail-to-singleton contraction;
- deterministic member addition, continuation and removal audits;
- stable prior representative preference and deterministic medoid fallback;
- safe event-episode reset when the exact representative changes;
- immutable typed family corridors and ordered rail projections;
- exact separation of rail geometry, family corridor, interaction zone and uncertainty;
- multi-rail role reversal preserving family/member identity, exact geometry, anchors and representative identity;
- bounded typed source-group provenance;
- repository-lineage validation for transition coverage and membership truth;
- content-addressed member, group, corridor, transition and aggregate snapshot identity;
- additive rail/corridor features under the existing shadow namespace;
- replay, future-row and projected-lane invariance;
- continued isolation from active RegimeV2, selection, strategy, risk and execution.

## Approval Decision

**Approved. Phase H may begin.**

No unresolved Phase-G blocker remains.

## Blocking Issues

None.

## Final Marker and Snapshot-Identity Verification

### Shared Phase-G evidence classifier

The canonical helper:

```text
trendline_family_snapshot_has_phase_g_evidence
```

classifies a snapshot as Phase G when any of the following is present:

- `diagnostics.rail_grouping_enabled == true`;
- family corridors;
- typed source-group audits;
- a family containing more than one exact member;
- rail membership or representative evidence in a family transition;
- transition source-group provenance;
- Phase-G rail/corridor diagnostics.

The snapshot contract and repository both use this same classifier.

Any Phase-G evidence without the explicit marker is rejected:

```text
Phase-G evidence requires diagnostics.rail_grouping_enabled=True
```

This prevents marker removal from selecting legacy validation for a Phase-G-shaped payload.

### Independent marker-stripping probes

Contract-bypassed objects were passed directly to a fresh repository to model corrupted in-memory or decoded payloads.

Each isolated evidence path was rejected with no repository head created:

```text
corridor     -> rejected
membership   -> rejected
diagnostics  -> rejected
source audit -> rejected
multi-member -> rejected
false marker -> rejected
```

A previously approved Phase-G repository head also cannot be followed by a markerless legacy-shaped downgrade.

### Canonical aggregate snapshot identity

One shared payload helper now owns the complete Phase-G snapshot identity inputs:

```text
asset
timeframe
timestamp
previous_snapshot_id
model/config identity
active and dormant families
family transitions
source-group audits
corridors
observations
interaction events
interaction-event transitions
diagnostics
```

The tracker computes `snapshot_id` from this helper. The snapshot contract and repository independently recompute and validate the same ID.

Changing any persisted aggregate component while retaining the old ID is rejected, including:

- transition state or audit;
- canonical source-group candidate content;
- corridor content;
- observation/event state;
- diagnostics.

Repository-side identity failure occurs before head replacement.

True historical Phase-C/D/F-shaped snapshots remain compatible only when all Phase-G structural evidence is absent.

## Phase-G Structural Guarantees

### Exact rail and family identity

The approved implementation guarantees:

- every `FamilyMember` remains the canonical owner of one exact `LineGeometry` and anchor set;
- member ordering does not define member identity;
- lower/upper rail labels are recomputed from projected price at each snapshot;
- a continuing exact rail keeps `member_id` and `first_seen_at`;
- a newly admitted rail receives a deterministic member ID;
- one candidate cannot update multiple prior members;
- one prior member cannot consume multiple candidates;
- candidate input permutation does not change grouping or identity;
- valid continuation through a non-representative outer rail retains the family ID;
- dormant families can reactivate through a valid non-representative member;
- unmatched rails are removed under the documented immediate-removal policy and recorded in typed audit fields.

### Rail grouping

Candidate grouping is deterministic and pairwise-safe.

Groups require:

- same asset;
- same timeframe;
- same role;
- bounded normalized slope difference;
- no crossing inside the known causal span;
- minimum rail spacing;
- bounded adjacent spacing;
- bounded total corridor width.

Complete-linkage behavior prevents transitive chain over-merging where A matches B and B matches C but A is incompatible with C.

Specific persisted rejection diagnostics include:

```text
slope_delta_exceeds_maximum
crossing_rails
spacing_below_minimum
adjacent_gap_exceeds_maximum
corridor_width_exceeds_maximum
complete_linkage_rejected
```

No learned clustering or split/merge lineage graph is introduced.

### Representative policy

The representative is always one exact current member rail.

The policy:

- preserves the prior representative while that member remains valid;
- otherwise selects a deterministic quality-aware medoid;
- never creates an averaged synthetic geometry;
- records previous/current representative IDs and `representative_changed`;
- begins a new Phase-F event episode when the exact representative rail changes;
- does not silently carry pending break/retest state from one exact representative to another.

### Family corridor

`FamilyCorridor` and `FamilyRailProjection` remain immutable timestamp-derived contracts.

The corridor is bound to:

- every current family member exactly once;
- exact member geometry projected at the snapshot timestamp;
- deterministic price/member ordering;
- the exact representative rail as corridor center;
- exact lower and upper projected rails;
- absolute and ATR-normalized width;
- adjacent-gap and spacing-stability diagnostics;
- model/config identity;
- a content-addressed corridor ID.

Singleton corridors remain valid with zero width and undefined gap statistics represented as `None`.

The family corridor is not an interaction zone, uncertainty envelope or synthetic line. Phase-F interaction and event classification continues to use the exact representative rail and its `InteractionZone` only.

### Role reversal

Approved multi-rail role reversal preserves:

- family ID;
- every continuing member ID;
- exact geometry for every member;
- exact anchors for every member;
- representative member ID;
- Phase-F event identity.

The reversal snapshot changes roles and timestamp-derived corridor projection only. It cannot refit exact rails from new-role candidates on the same snapshot.

Stale old-role provider candidates matching any prior exact member are suppressed from duplicate birth. Independent residual old-role candidates remain eligible for a separate deterministic family birth.

Dormant families cannot apply role reversal.

## Persistence and Audit Guarantees

### Complete family-transition coverage

For a Phase-G repository update, transition-family coverage must equal:

```text
previous family IDs union current family IDs
```

The repository requires:

- one `BIRTH` transition for each new family;
- one legal continuation/lifecycle transition for each continuing family;
- one `EXPIRE` transition for each removed family;
- no duplicate or unrelated family transition.

### Membership truth derived from repository lineage

The repository derives:

```text
added     = current member IDs - previous member IDs
continued = current member IDs intersect previous member IDs
removed   = previous member IDs - current member IDs
```

It validates exact:

- member partitions;
- previous/current rail counts;
- previous/current representative IDs;
- representative-change flag;
- birth and expiry semantics;
- role-reversal identity and geometry preservation.

Content-addressing alone is not treated as proof of causal truth; the audit must agree with both sides of the repository lineage.

### Transition type and timestamp

Transition labels are derived from actual family evolution:

```text
new family              -> BIRTH
removed family          -> EXPIRE
role change             -> ROLE_REVERSED
DORMANT -> ACTIVE       -> REACTIVATE
ACTIVE -> DORMANT       -> DORMANT
DORMANT -> DORMANT      -> WEAKEN
unmatched ACTIVE update -> WEAKEN
matched ACTIVE update   -> CONTINUE / STRENGTHEN / WEAKEN from confidence evolution
```

Every Phase-G family transition uses the containing snapshot timestamp.

False lifecycle labels, hidden role changes and stale transition timestamps are rejected even when their transition IDs are recomputed.

### Source-group provenance

`FamilySourceGroupAudit` persists bounded canonical evidence for a group used by a family transition:

- asset and timeframe;
- role;
- confirmed observation timestamp;
- ordered candidate IDs;
- canonical candidate records;
- deterministic candidate-content hashes;
- model/config identity;
- content-addressed source-group ID.

A transition source-group reference must resolve to exactly one audit in the same snapshot and match its candidate IDs and identity fields.

For role reversal, frozen current-member candidate IDs remain distinct from the new-role source group that supplied continuity evidence.

Unmatched lifecycle and expiry transitions cannot retain source-group evidence.

### Atomicity

All contract, identity and lineage checks execute before repository-head replacement.

Rejected snapshots leave the previous serialized head byte-identical.

## Feature and Shadow Guarantees

Phase-G structural output adds persisted fields for:

- corridor, singleton, multi-rail and total-rail counts;
- support/resistance rail counts;
- ordered member IDs;
- exact representative member IDs;
- lower/upper corridor prices;
- corridor width in ATR units;
- adjacent-gap and spacing stability;
- nearest exact rail and ATR distance;
- unclamped current corridor position.

Nearest-rail and corridor-position features use the persisted typed observation close. An external `current_price` argument is assertion-only and cannot alter semantic output.

All Phase-G features remain additive under:

```text
trendline_family_shadow
```

No active component consumes Phase-G rail or corridor features.

## Validation Sufficiency

### Trendline-family suite

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_g_approval \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  -q -p no:cacheprovider

259 passed
```

### Phase G plus shadow adapters and projected runtime

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_g_approval \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  -q -p no:cacheprovider

287 passed
```

### Active RegimeV2, selection and signals

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_g_approval \
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
ruff check \
  src/libs/models/trendline_family \
  src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py

All checks passed
```

```text
PYTHONPATH=src .venv/bin/python -m compileall -q \
  src/libs/models/trendline_family \
  src/libs/models/regime_v2/adapters

Passed
```

```text
git diff --check

Passed
```

## Blast Radius Confirmation

The aggregate identity validator is called by:

```text
TrendlineFamilySnapshot.__post_init__
InMemoryTrendlineFamilyRepository._validate_lineage
```

The tracker uses the same canonical identity payload to generate IDs.

Phase-G changes remain confined to the canonical trendline-family package, its shadow adapter/configuration and focused tests.

Verified:

- no runtime import from legacy trendline packages;
- no YAML access outside `config_loader.py`;
- no incomplete or future-bar tracking path;
- no MTF/Phase-H implementation;
- no active probability, overlay, MoE, selection, strategy, risk or execution behavior change.

Codebase-memory:

```text
Users-aloobhujia-flipperAgent
40,809 nodes
132,780 edges
status: ready
```

`detect_changes` still under-reports the untracked canonical trendline-family package. Direct source inspection, executed tests, git status and the ready codebase-memory graph remain the scope evidence of record.

## Residual Risk

Acceptable deferred risks:

- the canonical repository remains in-memory;
- source-group audits increase each referenced snapshot payload by a bounded set of canonical candidates, but long-history storage and latency profiles remain unmeasured;
- immediate unmatched-member removal has no independent per-rail grace lifecycle;
- long-duration family churn, corridor stability and representative-switch rates have not yet been calibrated on historical market batches;
- Phase-G rail/corridor features remain unevaluated for out-of-sample downstream utility;
- true historical Phase-C/D/F snapshots retain their historical non-content-addressed aggregate IDs for backward compatibility;
- the worktree contains untracked canonical package, test, config and plan files, so the eventual commit must explicitly include the complete Phase A–G implementation and approval documents;
- persistent database migration, corruption recovery, optimization and promotion remain deferred.

These risks do not block Phase H composition.

## Phase H Boundary

Phase H may implement asynchronous multi-timeframe composition over latest confirmed per-timeframe Phase-G snapshots.

Permitted Phase-H concepts:

- `src/libs/models/trendline_family/mtf.py` or an equivalently bounded module;
- projected MTF family members;
- MTF family clusters;
- typed confluence and conflict relations;
- one unified MTF geometry snapshot;
- projection of exact lines to one common decision timestamp;
- slope normalization to a common time/volatility basis;
- agreement, conflict, nesting and intersection evidence;
- source timeframe, family, member and snapshot provenance;
- latency and synchronization diagnostics;
- additive MTF shadow features and availability reporting.

Required Phase-H rules:

- each timeframe tracker updates only at its own confirmed close;
- higher-timeframe exact structures are projected between closes, never refitted from incomplete bars;
- no incomplete higher-timeframe candle enters confirmed MTF state;
- source snapshot and structure provenance remain explicit;
- conflicting structures remain visible rather than being discarded;
- MTF output is a composed geometry map, not one averaged synthetic trendline;
- active RegimeV2, selection, strategy, risk and execution remain unchanged;
- Phase I optimization and promotion remain forbidden.

## Required Handoff

Phase H is unblocked.

Implement only the asynchronous MTF-composition scope in:

```text
plans/trendline-family-codex-phase-execution-plan.md
```

Stop after Phase H implementation and return the mandatory review package. Do not begin Phase I.
