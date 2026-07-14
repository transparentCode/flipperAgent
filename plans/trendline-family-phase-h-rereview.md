# Trendline Family Model — Phase H Remediation Re-review

## Current Mode

Final Phase-H remediation re-review.

## Decision

**Revision required. Phase I remains blocked.**

The latest remediation correctly closes every previously reported source-provenance, identity and shadow point-in-time blocker. Independent re-review found one bounded policy area with three related defects:

1. A persisted MTF snapshot can contain canonical audited source timeframes outside `MTFPolicyAudit.source_timeframes`.
2. `mtf.enabled=true` permits an empty source-timeframe allowlist and then accepts arbitrary source timeframes.
3. Equivalent-duration aliases such as `1h` and `60m` are treated as distinct timeframes and can falsely satisfy multi-timeframe confluence.

No relation, clustering, projection, source-lineage, adapter, active-decision or Phase-I redesign is required.

---

## Verified Closed Findings

### Canonical source-snapshot provenance

`MTFSourceSnapshotAudit` now persists one complete canonical confirmed Phase-G snapshot per included timeframe.

The audit:

- round-trips through `TrendlineFamilySnapshot.from_dict`;
- validates the Phase-G aggregate snapshot identity;
- rejects incomplete sources;
- binds the complete source payload into a content-addressed audit ID.

`MTFGeometrySnapshot` now rebuilds from those audits:

- source references and statuses;
- source ATR and freshness;
- exact member projections;
- representative geometry and price;
- role and lifecycle;
- confidence and structural importance;
- event evidence;
- source corridor ordering;
- relations;
- complete-linkage clusters;
- diagnostics.

Independent replay confirmed:

```text
fabricated_source_id_REJECTED ContractValidationError
rewritten_source_audit_REJECTED ContractValidationError
```

### MTF policy and aggregate identity

Snapshot and cluster model/config/hash fields are now required to match `MTFPolicyAudit`.

Independent replay confirmed:

```text
policy_identity_rewrite_REJECTED ContractValidationError
```

### Point-in-time shadow attachment

The adapter now attaches MTF evidence only when all are exact:

```text
MTF asset == current single-timeframe asset
MTF decision timeframe == current single-timeframe timeframe
MTF decision timestamp == current single-timeframe snapshot timestamp
```

Mismatches fail softly into the disabled MTF namespace after preserving the valid single-timeframe repository update.

Independent replay confirmed:

```text
wrong_asset_attached false
single-timeframe head persisted true

future_decision_attached false
single-timeframe head persisted true
```

### Prior Phase-H remediation findings

Still verified closed:

- Phase-H config changes no longer alter Phase-G source identities;
- projected values are derived from audited exact geometry;
- relation and cluster labels are rebuilt from typed evidence and policy;
- latest-source store requires confirmed continuous per-timeframe lineage;
- real crossing detection compares against Phase-G corridor order;
- analytical intersections remain visible orthogonally to the primary relation label;
- artifact distributions use persisted sequence evidence;
- no active RegimeV2, selection, strategy, risk or execution consumption;
- no Phase-I implementation.

---

## Remaining Blocking Findings

### P0 — Persisted source audits are not constrained to the policy allowlist

Locations:

```text
src/libs/models/trendline_family/mtf.py
  MTFGeometrySnapshot.__post_init__
  _validate_mtf_snapshot_semantics
  _source_audit
```

The public composer correctly rejects source timeframes not configured in `mtf.source_timeframes`.

The persisted contract does not reproduce that rule. A snapshot was constructed with:

```text
policy.source_timeframes = ("1h",)
audited source timeframes = ("1h", "4h")
```

All references, projections, relations, clusters, diagnostics and the aggregate ID were derived consistently from the two canonical audits.

The `MTFGeometrySnapshot` contract accepted it:

```text
unexpected_policy_timeframe_ACCEPTED
policy:  ('1h',)
audits:  ('1h', '4h')
```

This permits a serialized MTF snapshot to claim policy-scoped source coverage that the public compositor itself would reject.

#### Required correction

Use one shared source-timeframe policy validator during both composition and `MTFGeometrySnapshot` construction/deserialization.

Required invariant:

```text
audited source timeframes ⊆ policy.source_timeframes
```

Missing configured timeframes remain valid and must continue to produce typed `MISSING` statuses.

Unexpected audited timeframes must reject before aggregate identity acceptance.

Add an adversarial public deserialization test whose nested and aggregate IDs are recomputed consistently.

---

### P0 — Enabled MTF accepts an empty source allowlist as unrestricted

Locations:

```text
src/libs/models/trendline_family/config.py
  MTFConfig.__post_init__

src/libs/models/trendline_family/mtf.py
  MTFPolicyAudit.__post_init__
  _validate_sources
```

`MTFConfig(enabled=True, source_timeframes=())` is accepted.

Because `_validate_sources` checks unexpected timeframes only when the configured tuple is truthy, an arbitrary source is then accepted:

```text
enabled_empty_allowlist_ACCEPTED
policy source_timeframes: ()
accepted source:          ('4h',)
```

An empty list must not silently mean “all timeframes” in a deterministic source-composition policy.

#### Required correction

Preserve the default-disabled empty configuration, but require:

```text
if mtf.enabled is true:
    source_timeframes must contain at least one canonical timeframe
```

`MTFPolicyAudit` must enforce the same invariant independently during deserialization.

The compositor may still receive an empty source mapping when configured timeframes exist; those timeframes should be represented as `MISSING`.

---

### P0 — Equivalent timeframe aliases can create false confluence

Locations:

```text
src/libs/models/trendline_family/config.py
  _TIMEFRAME_PATTERN
  MTFConfig.__post_init__

src/libs/models/trendline_family/mtf.py
  timeframe_duration_seconds
  MTFPolicyAudit.__post_init__
  _timeframe_key
  _build_clusters
```

Current validation treats timeframe strings as unique only by text.

The pair:

```text
1h
60m
```

represents the same duration but is accepted as two distinct source timeframes.

Independent result:

```text
timeframe_aliases_ACCEPTED
configured: ('1h', '60m')
cluster timeframe_count: 2
cluster is_confluence:   true
```

This can fabricate multi-timeframe confirmation from two labels for one actual timeframe duration.

Equivalent examples include:

```text
24h and 1d
7d and 1w
```

#### Required correction

Create one shared canonical timeframe validator used by:

- `MTFConfig`;
- `MTFPolicyAudit`;
- public source validation;
- source-audit contract validation;
- cluster distinct-timeframe counting.

At minimum, reject multiple configured timeframes with the same fixed duration.

Preferred behavior is to accept only one documented canonical representation per duration or normalize aliases before identity, ordering and confluence counting. Do not let alias labels count as distinct timeframes.

Add tests for:

```text
1h versus 60m
1d versus 24h
1w versus 7d
```

Also prove valid distinct timeframes such as `1h`, `4h`, and `1d` remain distinct and replay deterministic.

---

## Blast Radius

Expected correction is limited to:

```text
src/libs/models/trendline_family/config.py
src/libs/models/trendline_family/mtf.py
src/libs/models/trendline_family/config_resolver.py  # only if shared canonicalization requires it
tests/models/trendline_family/test_mtf_remediation.py
focused config/identity tests
```

No changes should be needed in:

```text
single-timeframe tracker
Phase-F events
Phase-G grouping or corridors
shadow adapter attachment
signal worker
active RegimeV2
probability
overlay
MoE
selection
strategy
risk
execution
```

---

## Validation Reproduced

### Focused MTF remediation

```text
30 passed
```

### Trendline-family suite

```text
289 passed
```

### RegimeV2 adapters and projected runtime

```text
28 passed
```

### Active RegimeV2, selection and signals

```text
148 passed, 1 warning
```

The warning is the existing OpenTelemetry `LoggingHandler` deprecation warning.

### Static validation

```text
Ruff: passed
compileall: passed
git diff --check: passed
```

### Codebase-memory

```text
Users-aloobhujia-flipperAgent
41,029 nodes
134,047 edges
status: ready
```

`detect_changes` continues to omit the untracked canonical trendline-family package. Direct source inspection, focused tests, adversarial probes and git status remain the scope evidence of record.

---

## Architecture Drift Check

Verified:

- no runtime import from legacy trendline packages;
- YAML access remains confined to the canonical config loader;
- source snapshots remain confirmed and causal;
- exact geometry remains separate from MTF policy;
- no source refitting or identity merging;
- all MTF output remains additive and shadow-only;
- no active decision path reads Phase-H output;
- no Phase-I optimizer or promotion code exists.

The worktree remains broadly dirty and the canonical package remains untracked. Eventual packaging must explicitly include all Phase A-H source, configuration, tests and durable review/approval documents.

---

## Codex Remediation Prompt

```text
Apply the final Phase-H source-timeframe policy correction only.

Read:
- plans/trendline-family-phase-h-review.md
- plans/trendline-family-phase-h-rereview.md
- plans/trendline-family-phase-g-approval.md
- plans/trendline-family-codex-phase-execution-plan.md
- plans/trendline-family-model-architecture-plan.md

Do not begin Phase I.

Objective:
Close the final source-timeframe policy and canonicalization gaps without changing projection, relation, clustering, source-audit, shadow or active-decision semantics.

Required outcomes:

1. Persisted MTF source audits must be a subset of `MTFPolicyAudit.source_timeframes`.
   - Enforce during `MTFGeometrySnapshot` construction/deserialization.
   - Reject unexpected audited timeframes even when every nested and aggregate ID is recomputed.
   - Preserve typed MISSING status for configured-but-absent sources.

2. `mtf.enabled=true` requires at least one configured source timeframe.
   - Preserve default-disabled `source_timeframes=()` compatibility.
   - An enabled policy with an empty allowlist must reject in both `MTFConfig` and `MTFPolicyAudit`.

3. Equivalent-duration timeframe aliases must not count as distinct MTF sources.
   - Use one shared canonical timeframe validator.
   - Reject duplicate semantic durations or normalize to one documented canonical form before identity and confluence counting.
   - Cover `1h`/`60m`, `1d`/`24h`, and `1w`/`7d`.

4. Preserve all currently passing behavior:
   - canonical Phase-G source audits;
   - exact source-derived projections;
   - derived relations and complete-linkage clusters;
   - source-store lineage continuity;
   - crossing diagnostics;
   - orthogonal intersections;
   - artifact distributions;
   - point-in-time shadow attachment;
   - active decision invariance.

Add public contract/deserialization tests for unexpected policy timeframes, empty enabled allowlists and equivalent-duration aliases.

Run:

PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_family -q

PYTHONPATH=src .venv/bin/python -m pytest \
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

Stop after this correction. Phase I remains blocked pending approval.
```
