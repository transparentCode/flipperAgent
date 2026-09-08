---
goal: Measure threshold-free, causal current-relevance metadata for the exact Trendlines V4 geometries established by N1, without filtering, scoring, tuning, or changing production artifacts
stage: orchestrator-decision
phase: TRENDLINES-V4-N2-CURRENT-RELEVANCE-METADATA
status: DESIGN_APPROVED
date_created: 2026-09-06
owner: quant-orchestrator
worktree: /Users/kajukatli/.devspace/worktrees/flipperAgent-cd309574
base_sha: d901474ffc290d1457e02bcbafcabaddd2de7b42
n1_approval: plans/orchestrator-decision-trendlines-v4-n1-exact-identity-persistence-approval-v1.md
production_change: NONE
research_contract_change: MATERIAL_RESEARCH_CONTRACT
required_gate: DESIGN_APPROVED
network_calls: 0
commit_merge_push: NOT_AUTHORIZED
---

# Trendlines V4 N2 — threshold-free current relevance metadata design v1

## 1. Objective

N1 established exact geometry identity and showed that the current `3/300` baseline is highly available but non-trivially dynamic.

N2 asks a narrower factual question:

> At each causal cutoff, what observable geometric facts describe how old, extended, near/far, crossed, or history-boundary-constrained each emitted line is — without deciding whether the line is good, bad, relevant, stale, or tradeable?

N2 is research/diagnostics only.

It must not change V4 selection, delete lines, create a relevance score, tune a threshold, or promote fields into `trendlines.geometry.v1`.

## 2. Frozen authority and evidence locks

Authenticate before execution and again before publication.

### Production locks

```text
c92076e72891b222cf8359cba614c8ed969f04d1734a8985abdb0b68ffc9509f  src/libs/models/trendlines_v4/core.py
66ccb45f10ab0c3b530f81919ad172fdde93b51cda04d935a6ce581641d0ac61  src/libs/models/trendlines_v4/__init__.py
9d65b6f1cc0d00bbd60c9f40299f47701a161eadc2d5d0ae29b28747d415e523  src/libs/models/trendlines_v4/adapters/decision_plugin.py
41d9d9562e48c54042b46ce9880247b4ba23769ff80d708c2ee7c15c951ee763  src/apps/decision_app/composition.py
```

### Corrected N1 locks

```text
30e17266998b445d2fb12d75e0ede590c16ca2fec2d02f0879655f49b41e444d  research/trendlines_v4/exact_geometry_identity_persistence.py
f23ad57ae9bc5a958c1bdcc88675d8e0049e90fac53cc714fa4191014a59bf9e  tests/research/trendlines_v4/test_exact_geometry_identity_persistence.py
30045237ff1bd763539addbf5645dadb862665512854731b1fdf3823c5499bd3  artifacts/trendlines_v4/n1_exact_geometry_identity_persistence_v1/report.json
9e270831b656e13b3df0e8c4cbb90e2ebeec4f24a9c5c56555c71b6d7506d464  artifacts/trendlines_v4/n1_exact_geometry_identity_persistence_v1/manifest.json
```

N2 must reuse the exact N1 source locks, 4h aggregation contract, deterministic windows, 300-bar core slices, and `geometry_id` semantics. Do not create a competing identity implementation.

## 3. Preferred authorized research surface after approval

```text
research/trendlines_v4/current_relevance_metadata.py
tests/research/trendlines_v4/test_current_relevance_metadata.py
artifacts/trendlines_v4/n2_current_relevance_metadata_v1/report.json
artifacts/trendlines_v4/n2_current_relevance_metadata_v1/manifest.json
plans/coder-to-orchestrator-trendlines-v4-n2-current-relevance-metadata-v1.md
```

A second implementation module, generic metric framework, production adapter edit, or viewer redesign is out of scope.

## 4. Measurement corpus

Use the exact N1 corpus:

```text
BTCUSDT, ETHUSDT, SOLUSDT, HYPEUSDT
× 1h, 4h
× early, late deterministic 600-bar windows
× 300 measured causal cutoffs
= 4,800 snapshots
= 19,200 possible role slots
```

At every cutoff call the unchanged P0 core on exactly the same 300-bar slice as corrected N1:

```text
window[cutoff+1 : cutoff+301]
cutoff = 0..299
```

The source bar represented by measurement cutoff `c` is local window position `c + 300`.

Reuse N1 exact `geometry_id` for every non-null line.

## 5. Metadata contract

For every non-null role observation, derive the following values from information available at that cutoff only.

No future bars may enter any field.

### 5.1 Identity / scope fields

```text
asset
timeframe
window
cutoff
market_as_of
side
role
geometry_id
```

These identify the observation but are not relevance metrics.

### 5.2 Anchor geometry

```text
anchor_span_bars
start_anchor_age_bars
end_anchor_age_bars
start_anchor_headroom_bars
```

Definitions for a 300-bar history with final index `F`:

```text
start_anchor_age_bars     = F - start_anchor_index
end_anchor_age_bars       = F - end_anchor_index
anchor_span_bars          = end_anchor_index - start_anchor_index
start_anchor_headroom_bars= start_anchor_index
```

Require the exact invariant:

```text
start_anchor_age_bars == end_anchor_age_bars + anchor_span_bars
```

`start_anchor_headroom_bars` is important for later H0 lookback sensitivity: a value near zero means the line begins near the current history boundary. It is factual metadata, not a staleness decision.

### 5.3 Current geometric distance

Let:

```text
L = line projected value at market_as_of
C = current close
body_bottom = min(open, close)
body_top    = max(open, close)
```

Require positive finite `C`.

Record:

```text
absolute_close_distance_bps = abs(C - L) / C * 10_000
```

and side-oriented body clearance:

```text
support:    body_clearance_bps = (body_bottom - L) / C * 10_000
resistance: body_clearance_bps = (L - body_top) / C * 10_000
```

Interpretation is purely factual:

```text
positive  => current candle body is on the expected side of the line
zero      => exact body equality
negative  => current candle body crosses the line
```

Do not threshold or bucket this value into relevant/stale/valid labels.

### 5.4 Scale-normalized slope

Record:

```text
slope_bps_per_bar = line.slope_per_bar / C * 10_000
```

Preserve sign. Do not convert slope into a trend-direction signal.

### 5.5 Post-anchor crossing facts

Record:

```text
post_anchor_bar_count
post_anchor_body_cross_count
post_anchor_body_cross_rate
bars_since_last_body_cross   # null when there has never been a crossing
projection_positive
```

Definitions:

```text
post_anchor_bar_count = F - end_anchor_index
post_anchor_body_cross_rate =
    0.0 if post_anchor_bar_count == 0
    else post_anchor_body_cross_count / post_anchor_bar_count
```

Recompute crossing indices using the exact P0 body rule over bars strictly after the end anchor. The recomputed count must equal `TrendlineGeometry.post_anchor_body_cross_count` exactly or fail closed.

If crossings exist:

```text
bars_since_last_body_cross = F - latest_crossing_index
```

Else it is JSON `null`.

No wick-only interaction metric is added in N2 because any useful definition would require a tolerance/contact convention and therefore introduce a new parameter or semantic contract.

## 6. Deliberately excluded fields

Do not add in N2:

- relevance/staleness score;
- relevant/stale boolean;
- distance threshold;
- maximum anchor age;
- minimum span;
- touch/contact count;
- wick proximity count;
- ATR normalization;
- realized volatility normalization;
- regime labels;
- volume/open-interest features;
- future persistence/lifetime labels;
- future return/contact/bounce/break labels;
- alpha, PnL, signal, direction, confidence, probability;
- per-asset or per-timeframe parameter selection.

These exclusions keep N2 descriptive rather than evaluative.

## 7. Avoid double-counting shared roles

When `structural` and `current_valid` on the same side share one `geometry_id`, one physical line appears in two role slots.

N2 must therefore expose two distinct aggregate views:

### Role-observation view

Preserve all non-null role observations. This answers product-role questions such as whether `current_valid` is generally nearer/younger than `structural`.

### Unique-geometry-at-cutoff view

Deduplicate by:

```text
(asset, timeframe, window, cutoff, geometry_id)
```

before global geometry-distribution summaries. This prevents a line shared by both roles from receiving double weight merely because it occupies two product roles.

Metadata for duplicate role references to the same geometry/cutoff must be identical except for the `role` field or fail closed.

## 8. Required distributions

For each numeric metadata field, report at least:

```text
count
min
median
p75
p90
p95
max
```

Use the same explicit R-7 percentile definition as N1.

Report role-level aggregates by:

```text
global
asset × timeframe
timeframe
side × role
```

Report unique-geometry-at-cutoff aggregates at least by:

```text
global
timeframe
side
```

Also report factual rates/counts:

- negative current body-clearance rate;
- zero current body-clearance count;
- projection-non-positive rate;
- any-post-anchor-cross rate;
- no-post-anchor-cross rate;
- start-anchor-at-history-head count (`start_anchor_headroom_bars == 0`);
- start-anchor-within-first-5-bars count (descriptive only; `5` is a reporting bucket, not a selection threshold);
- nullable `bars_since_last_body_cross` observed count;
- structural/current-valid shared-geometry count inherited/recomputed against N1.

The first-5-bars count is an explicit diagnostic bin only. It must never influence selection, scoring, or H0 parameter choice automatically.

## 9. N1 consistency gates

N2 must independently reproduce or bind to these corrected N1 facts:

```text
4,800 snapshots
19,200 role slots
9,600 side pairs
1,159 unique exact geometries across N1
2,363 N1 role episodes
```

N2 does not need to recompute persistence aggregates in its report, but its identity set and role-slot tape must be consistent with N1.

At minimum verify:

- every N2 `geometry_id` exists in the N1 identity set for the same corpus;
- N2 role availability counts agree with N1;
- same-geometry role pairs agree with N1;
- no N2 metadata changes the P0 geometry result.

## 10. Questions N2 must answer

1. How old and how long-spanned are structural versus current-valid geometries under the current `3/300` baseline?
2. How far from the current close/body are those two roles, by 1h/4h and asset?
3. How often are structural lines currently body-crossed, and how old are their most recent crossings?
4. How frequently do selected lines start near the 300-bar history boundary, indicating potential lookback sensitivity for H0?
5. Are 1h and 4h metadata distributions materially different enough that H0 should explicitly evaluate timeframe profiles?
6. Are there obvious pathological distributions that H0 must measure, without attempting to fix them in N2?

N2 must not select a hyperparameter or recommend a threshold.

## 11. Focused tests

At minimum prove:

- exact reuse of N1 `geometry_id`;
- 300-bar cutoff alignment remains `[start+300, start+599]`;
- anchor age/span/headroom arithmetic and invariant;
- absolute close distance formula;
- support and resistance body-clearance sign conventions;
- equality gives exactly zero clearance when constructed exactly;
- scale-normalized slope formula;
- crossing count recomputation equals P0 metadata;
- crossing rate denominator is bars strictly after end anchor;
- latest-cross age is null for never-crossed and exact for crossed lines;
- shared structural/current-valid role metadata deduplicates to one geometry-at-cutoff record;
- duplicate role references cannot disagree on geometry metadata;
- no future bars are accessed;
- source, N1, and production hashes remain exact.

## 12. Validation

Run:

- N2 focused tests;
- N1 focused tests;
- frozen V4/P0/P1/G0-G7 regression sufficient to protect the production core and adapter;
- deterministic N2 run twice with exact artifact-byte equality;
- Ruff `--no-cache`;
- format check;
- AST/compile/import firewall;
- `git diff --check`;
- cache-deletion restoration/hygiene check.

No network, commit, merge, or push.

## 13. Allowed conclusions

N2 is descriptive. Allowed high-level dispositions are:

```text
CURRENT_RELEVANCE_METADATA_SUPPORTED
CURRENT_RELEVANCE_METADATA_SUPPORTED_WITH_PATHOLOGICAL_DISTRIBUTIONS
CURRENT_RELEVANCE_METADATA_INCONCLUSIVE
BLOCKED_SOURCE_OR_CONTRACT
```

`PATHOLOGICAL_DISTRIBUTIONS` is evidence for H0 design, not permission to filter lines.

## 14. Production promotion boundary

N1 identity and N2 metadata remain research-only through N2.

Do not version-bump the production artifact twice. If N1+N2 later deserve production exposure, promote the stable identity/metadata contract together in one separately approved artifact-version change after H0/H1 implications are understood.

## 15. Approval boundary

Required explicit user approval before a coder implements N2:

```text
TRENDLINES_V4_N2_CURRENT_RELEVANCE_METADATA_DESIGN_APPROVED
```

N2 approval does not authorize H0/H1/H2, N3, N4, production artifact changes, config changes, commit, merge, or push.

NEXT_OWNER_CAN_ACT_WITHOUT_GUESSING
