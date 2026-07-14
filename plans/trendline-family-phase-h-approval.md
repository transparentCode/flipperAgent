# Trendline Family Model — Phase H Approval

## Current Mode

Quant approval.

## Approval Scope

Phase H deterministic asynchronous multi-timeframe composition over immutable, confirmed Phase-G trendline-family snapshots, including:

- one independently updated canonical Phase-G source snapshot per included timeframe;
- exact projection of persisted member geometries to a common UTC decision timestamp;
- immutable typed source-snapshot audits, source references, source statuses, projected members, projected families, relations, clusters and aggregate MTF snapshots;
- deterministic source freshness and missing-source treatment;
- decision-timeframe ATR normalization for cross-timeframe level comparison;
- source-ATR normalization for source slope evidence;
- role-aware agreement, confluence, nesting, divergence, conflict, intersection and disjoint evidence;
- deterministic complete-linkage clustering without transitive chain over-merging;
- explicit conflict preservation without timeframe dominance or directional policy;
- exact representative-line intersection evidence within a bounded forward analytical horizon;
- content-addressed MTF policy, projection, relation, cluster and aggregate snapshot identity;
- latest-confirmed-source wrapper with per-timeframe lineage continuity;
- additive precomposed MTF evidence under `trendline_family_shadow.mtf` only;
- exact asset, decision-timeframe and decision-timestamp binding at shadow attachment;
- preserved projected-lane and active-decision invariance;
- strict source-timeframe allowlist and equal-duration alias rejection.

## Approval Decision

**Approved. Phase I may begin.**

No unresolved Phase-H blocker remains.

## Blocking Issues

None.

## Final Source-Timeframe Policy Verification

### Shared fixed-duration validator

The canonical helpers:

```text
canonical_timeframe_duration_seconds
canonical_mtf_source_timeframes
```

are shared by typed Phase-H configuration and persisted `MTFPolicyAudit` validation.

They enforce:

- lower-case fixed-duration labels using `m`, `h`, `d` or `w`;
- deterministic duration ordering;
- no duplicate labels;
- no pair of labels representing the same fixed duration;
- a nonempty source allowlist whenever MTF is enabled.

Verified rejected equivalent-duration pairs include:

```text
1h / 60m
1d / 24h
1w / 7d
```

The rule is duration-based and therefore also covers other equivalent aliases such as `2h / 120m`.

### Enabled versus disabled configuration

The default remains valid and inactive:

```text
mtf.enabled = false
mtf.source_timeframes = []
```

An enabled compositor requires at least one configured source timeframe:

```text
mtf.enabled = true
mtf.source_timeframes = []
    -> ContractValidationError
```

An empty runtime source mapping remains valid when the policy contains configured timeframes. Every configured but unavailable timeframe is represented explicitly as:

```text
MTFFreshnessState.MISSING
reason_codes = ("missing_source_snapshot",)
```

No missing timeframe is interpreted as neutral agreement or confluence.

### Runtime and persisted allowlist parity

One shared policy gate:

```text
_validate_policy_source_timeframes
```

is reached from:

- public source composition validation;
- persisted MTF snapshot construction/deserialization;
- canonical source-audit derivation;
- semantic MTF snapshot reconstruction.

The required invariant is enforced:

```text
audited source timeframes ⊆ policy.source_timeframes
```

A fully reidentified payload with:

```text
policy source_timeframes = ("1h",)
audited source timeframes = ("1h", "4h")
```

is rejected before aggregate identity acceptance.

Independent final probes produced:

```text
enabled_empty_REJECT ContractValidationError
config_alias_REJECT ('1h', '60m') ContractValidationError
config_alias_REJECT ('1d', '24h') ContractValidationError
config_alias_REJECT ('1w', '7d') ContractValidationError
off_policy_audit_REJECT ContractValidationError
```

Empty-source composition under a configured `1h/4h/1d` policy produced exactly:

```text
('1h', 'MISSING')
('4h', 'MISSING')
('1d', 'MISSING')
```

with zero source audits and zero projected families.

## Phase-H Architectural Guarantees

### Source-snapshot causality and provenance

Every included source is a complete canonical confirmed Phase-G `TrendlineFamilySnapshot`.

The compositor and latest-source wrapper reject:

- non-Phase-G snapshots;
- forged Phase-G aggregate IDs;
- future source timestamps;
- incomplete-source diagnostics;
- asset mismatches;
- mapping-key/timeframe mismatches;
- off-policy timeframes;
- duplicate timeframe lineage;
- older source replacement;
- newer independent branches that do not continue the stored source head.

One bounded `MTFSourceSnapshotAudit` persists the complete canonical source snapshot per included timeframe. Its content-addressed audit ID binds the entire source payload.

All source references and projected evidence are rebuilt from these audits during MTF deserialization. A copied geometry, role, lifecycle, confidence, event, ATR, corridor order or source ID cannot be rewritten coherently while retaining the claimed Phase-G source snapshot.

### Tracking and MTF policy identity separation

Phase-H configuration has a dedicated MTF config hash.

Changing an MTF-only parameter:

- does not alter Phase-G source snapshots;
- does not alter source family/member IDs;
- does not alter source exact geometry;
- does alter MTF policy identity and the resulting MTF snapshot identity when the parameter is relevant to the persisted policy.

The source tracker continues to use the upstream tracking config hash. The MTF snapshot, policy audit and clusters use the dedicated MTF policy identity.

### Exact common-timestamp projection

Every projected member price is recomputed from:

```text
source LineGeometry.value_at(decision_timestamp)
```

The approved contracts bind and revalidate:

- source geometry and geometry hash;
- projected member price;
- offset from the exact representative member;
- projected representative price and slope;
- source-ATR-normalized slope;
- projected member price ordering;
- projected corridor lower/upper bounds and ATR width;
- source-corridor order versus projected order;
- crossing/order-change diagnostics.

Projection never refits source geometry, regenerates pivots, rematches members, changes lifecycle, or creates a synthetic averaged line.

### Staleness and missing-source evidence

Source age derives exactly from source snapshot timestamp, source timeframe duration and the common decision timestamp.

The persisted typed states are:

```text
FRESH
STALE_INCLUDED
STALE_EXCLUDED
MISSING
```

Stale-excluded structures remain visible in source diagnostics but do not contribute to confluence clusters. Missing configured sources are explicit and do not fabricate agreement.

### Relation semantics

Pair relations are rebuilt from persisted audited geometry and typed MTF policy rather than trusted as caller labels.

The approved relation surface includes:

```text
AGREEMENT
CONFLUENCE
NESTED
DIVERGENCE
CONFLICT
INTERSECTION
DISJOINT
```

The contract rejects:

- opposite-role agreement/confluence/nesting relabels;
- missing, duplicate or extra pair relations;
- altered relation metrics or reason codes;
- relation IDs inconsistent with complete relation evidence;
- conflict suppression through recomputed nested and aggregate IDs.

An analytical forward intersection remains an orthogonal fact even when the primary pair relation is `CONFLICT` or another non-intersection type. It is not treated as a market event, breakout, signal or trade trigger.

### Complete-linkage clustering

Same-role cluster construction is deterministic, pairwise-safe and free from transitive chain over-merging.

Approved cluster invariants include:

- at most one source family per source timeframe;
- distinct source durations due to alias rejection;
- one real projected family as the reference;
- no synthetic representative geometry;
- exact membership and deterministic ordering;
- exact family/timeframe counts;
- recomputed price span, level dispersion, slope dispersion and corridor overlap;
- deterministic confluence strength and reason codes;
- stale-excluded sources do not contribute;
- singleton clusters cannot claim multi-timeframe confluence;
- a projected family cannot belong to multiple clusters.

The chain adversary remains split when A agrees with B, B agrees with C, and A is incompatible with C.

### Aggregate MTF identity and replay

The aggregate `mtf_snapshot_id` binds:

- asset and decision timestamp;
- normalization context;
- complete typed MTF policy audit;
- canonical source-snapshot audits;
- source references and statuses;
- projected families and members;
- relations;
- clusters;
- model/config identity;
- diagnostics.

Construction and deserialization rebuild semantic evidence from the canonical source audits and policy before accepting aggregate identity.

Verified replay properties include:

- input mapping order independence;
- source arrival order independence after equivalent source heads are present;
- deterministic serialization round-trip;
- changed source snapshot identity changes MTF identity;
- changed policy changes MTF identity without changing source Phase-G identity;
- removed or missing timeframe changes source coverage and aggregate identity;
- future-source input rejects;
- stale or forged nested and aggregate IDs reject.

### Shadow-only attachment

The RegimeV2 adapter reads only an already composed `MTFGeometrySnapshot`.

It does not run composition, source tracking, fitting or relation construction.

MTF evidence attaches only when all are exact:

```text
MTF asset == current single-timeframe asset
MTF decision timeframe == current single-timeframe timeframe
MTF decision timestamp == current single-timeframe snapshot timestamp
```

Wrong-asset, wrong-timeframe, stale or future-decision MTF evidence fails softly into a disabled MTF subnamespace. The valid single-timeframe update and repository head remain preserved.

No active RegimeV2, probability, overlay, MoE, SelectionLayer, strategy, risk or execution component reads Phase-H fields.

## Blast Radius Confirmation

The Phase-H implementation and remediation remain bounded to:

```text
src/libs/models/trendline_family/mtf.py
src/libs/models/trendline_family/config.py
src/libs/models/trendline_family/config_resolver.py
src/libs/models/trendline_family/api.py
src/libs/models/trendline_family/__init__.py
configs/trendline_family.yaml
src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py
focused trendline-family, adapter and projected-runtime tests
```

Final graph traces confirm:

- `canonical_mtf_source_timeframes` is consumed by `MTFConfig` and `MTFPolicyAudit`;
- `_validate_policy_source_timeframes` is consumed by runtime composition, persisted MTF snapshot validation and source-audit derivation.

Verified absent:

- runtime imports from legacy trendline packages;
- YAML reads outside `config_loader.py`;
- signal-worker timing changes for Phase H;
- active MTF decision consumption;
- parameter optimization, promotion or Phase-I implementation.

`codebase-memory detect_changes` still omits the untracked canonical package. Direct source inspection, focused tests, graph traces and git status are the Phase-H scope evidence of record.

## Validation Sufficiency

Independent validation completed:

### Focused MTF files

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family/test_mtf.py \
  tests/models/trendline_family/test_mtf_remediation.py \
  -q -p no:cacheprovider

33 passed
```

The reported broader focused slice was 57 passed; the independently executed full trendline-family suite below contains all focused Phase-H tests.

### Full trendline-family suite

```text
293 passed
```

### RegimeV2 adapters and projected runtime

```text
28 passed
```

### Active RegimeV2, selection and signals

```text
148 passed, 1 warning
```

The warning is the pre-existing OpenTelemetry `LoggingHandler` deprecation.

### Static validation

```text
Ruff: passed
compileall: passed
git diff --check: passed
```

### Codebase-memory

```text
project: Users-aloobhujia-flipperAgent
nodes: 41,061
edges: 134,073
status: ready
```

## Residual Risk

Accepted residual risks:

1. MTF snapshots embed one complete Phase-G source snapshot per included timeframe. This gives strong self-contained auditability but increases serialization and memory cost; production-scale latency and payload size remain unbenchmarked.
2. The latest-source store is in-memory. Restart persistence and distributed source ownership remain intentionally outside Phase H.
3. Phase H is shadow-only and has not demonstrated predictive utility, calibration, economic benefit or production latency suitability. Those are Phase-I evaluation questions.
4. The timeframe model intentionally supports fixed-duration `m/h/d/w` labels, not calendar-month or exchange-session intervals.
5. The canonical package and approval artifacts remain broadly untracked in the current worktree. Progression approval is not a substitute for explicit commit/package inclusion review.
6. Root-wide unrelated repository issues and dirty conductor/config work remain outside this approval.

These risks do not violate the approved Phase-H boundary.

## Required Handoff

Phase I is unblocked but must remain a separate implementation and review cycle.

Phase I is limited to stage-specific optimization, evaluation and explicit promotion recommendations:

- candidate/geometry evaluation;
- tracker continuity/churn evaluation;
- interaction-event evaluation and calibration;
- downstream RegimeV2 feature-group ablation;
- walk-forward plus untouched holdout evidence;
- persisted trials and failures;
- explicit promote/hold/reject recommendations.

Phase I must not automatically write promoted values into runtime configuration. Any promotion into `configs/trendline_family.yaml` requires a separate explicit approval decision.
