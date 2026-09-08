---
goal: Establish exact, non-fuzzy Trendlines V4 geometry identity and observational persistence semantics on real 1h/4h crypto data without changing P0/P1 production bytes or introducing lifecycle state
stage: orchestrator-decision
phase: TRENDLINES-V4-N1-EXACT-IDENTITY-PERSISTENCE
status: DESIGN_APPROVED
date_created: 2026-09-06
last_updated: 2026-09-06
owner: quant-orchestrator
worktree: /Users/kajukatli/.devspace/worktrees/flipperAgent-cd309574
base_sha: d901474ffc290d1457e02bcbafcabaddd2de7b42
roadmap_review: plans/orchestrator-decision-trendlines-v4-post-p1-roadmap-adversarial-review-v1.md
production_change: NONE
research_contract_change: MATERIAL_RESEARCH_CONTRACT
required_gate: DESIGN_APPROVED
network_calls: 0
commit_merge_push: NOT_AUTHORIZED
---

# Trendlines V4 N1 — exact identity + observational persistence design v1

## 1. Objective

Answer one narrow question before relevance scoring or hyperparameter calibration:

> Can the exact V4 geometry emitted across consecutive causal cutoffs be given a stable, deterministic identity and measured for persistence/churn without adding fuzzy matching or production lifecycle state?

N1 is research/diagnostics only.

Do not modify:

- `src/libs/models/trendlines_v4/core.py`;
- `src/libs/models/trendlines_v4/__init__.py`;
- P1 Decision adapter/composition;
- `trendlines.geometry.v1`;
- Decision state/checkpoint contracts;
- active configuration.

## 2. Protected production locks

Authenticate before and after execution:

```text
src/libs/models/trendlines_v4/core.py
c92076e72891b222cf8359cba614c8ed969f04d1734a8985abdb0b68ffc9509f

src/libs/models/trendlines_v4/__init__.py
66ccb45f10ab0c3b530f81919ad172fdde93b51cda04d935a6ce581641d0ac61

src/libs/models/trendlines_v4/adapters/decision_plugin.py
9d65b6f1cc0d00bbd60c9f40299f47701a161eadc2d5d0ae29b28747d415e523

src/apps/decision_app/composition.py
41d9d9562e48c54042b46ce9880247b4ba23769ff80d708c2ee7c15c951ee763
```

Also run the frozen V4/P1 regression sufficient to prove G0-G7/P0/P1 behavior remains exact.

## 3. Preferred authorized research surface after approval

```text
research/trendlines_v4/exact_geometry_identity_persistence.py
tests/research/trendlines_v4/test_exact_geometry_identity_persistence.py
artifacts/trendlines_v4/n1_exact_geometry_identity_persistence_v1/report.json
artifacts/trendlines_v4/n1_exact_geometry_identity_persistence_v1/manifest.json
plans/coder-to-orchestrator-trendlines-v4-n1-exact-identity-persistence-v1.md
```

If the work requires production edits or a tracking framework, stop with a blocker.

## 4. Exact identity contract

For one emitted `TrendlineGeometry`, derive a canonical `geometry_id` from immutable anchor geometry plus market identity.

Identity semantic fields:

```text
schema_version = "trendlines_v4_exact_geometry_identity_v1"
asset
timeframe
side
start_anchor_at UTC exact timestamp
start_anchor_price exact Python-float hexadecimal representation
end_anchor_at UTC exact timestamp
end_anchor_price exact Python-float hexadecimal representation
anchor_span_bars
```

`anchor_span_bars` is the number of source-bar ordinal steps from start anchor to end anchor in the causal history used for that observation.

Use canonical JSON + SHA-256 from the standard library. No legacy identity module import.

The following must **not** enter `geometry_id`:

- structural/current-valid role;
- current observation cutoff;
- projected value at current cutoff;
- body crossing count;
- projection-positive status;
- line lifetime;
- parameter profile/history policy;
- report/window identity.

Rationale: role and current metadata can change while the anchored bar-ordinal line remains the same. Profile provenance should remain external so exact geometries can be compared across future parameter studies.

### Exactness invariants

For every identity observation:

- anchor timestamps must map uniquely to source-bar positions;
- `anchor_span_bars > 0`;
- recomputed `(end_price - start_price) / anchor_span_bars` must equal the emitted `slope_per_bar` exactly under the same Python-float arithmetic;
- repeated canonical content must reproduce the same ID;
- different canonical content must never be silently coalesced.

Report any SHA collision/content mismatch as a hard failure.

## 5. Role observation contract

Roles are observations of geometry, not geometry identity.

At each causal cutoff there are four possible role slots:

```text
support.structural
support.current_valid
resistance.structural
resistance.current_valid
```

Each slot records either `None` or one `geometry_id`.

When structural and current-valid are the same geometry on one side, both role slots point to the same `geometry_id`.

## 6. Persistence episode contract

Persistence is reconstructed from consecutive causal snapshots; no mutable line state is introduced into V4 production.

For each `(asset, timeframe, measurement_window, side, role)`:

- `BIRTH`: role changes from absent/different geometry to geometry X;
- `CONTINUE`: the immediately previous expected bar cutoff carried geometry X in the same role;
- `END`: geometry X is absent or replaced on the next expected cutoff;
- `REAPPEAR`: geometry X appears after at least one completed gap/replacement episode; it keeps the same `geometry_id` but starts a new episode.

An episode ID may be deterministically derived from role scope + geometry ID + episode start cutoff.

Do **not** forbid reappearance.

### Continuity and data gaps

Persistence is bar-sequence persistence, but selected research windows must first be verified contiguous for their timeframe.

For 1h windows, adjacent bars must be exactly one hour apart.

For derived 4h windows, aggregation must use UTC buckets `[00,04), [04,08), ...]`, require exactly four contiguous 1h bars per completed bucket, and adjacent 4h bars must be exactly four hours apart.

Do not bridge an interior source gap. Fail that selected window/corpus construction instead of pretending continuity.

## 7. Real measurement corpus

Assets:

```text
BTCUSDT
ETHUSDT
SOLUSDT
HYPEUSDT
```

Timeframes:

```text
1h
4h
```

Use the existing local real 1h CSV histories already used by the V4 disposable viewer/research environment; no network acquisition.

For 4h, derive canonical UTC-aligned candles from the corresponding 1h source with exact OHLC aggregation:

```text
open  = first 1h open
high  = max 1h high
low   = min 1h low
close = final 1h close
close timestamp = final 1h close timestamp
```

### Deterministic windows

For each asset × timeframe series:

- select two deterministic 600-bar contiguous windows from the available series using fixed fractional positions over the eligible start-index range (early and late, e.g. 20% and 80%);
- first 300 bars are pre-roll/warmup;
- next 300 bars are the measurement cutoffs;
- at each measurement cutoff, run the unchanged production core over the latest at-most-300 bars available through that cutoff.

Expected nominal measurement inventory:

```text
4 assets × 2 timeframes × 2 windows × 300 cutoffs = 4,800 causal snapshot observations
4 role slots per cutoff = 19,200 role-slot observations
```

If deterministic source-length/gap constraints make this exact inventory impossible, return a bounded blocker/evidence note instead of silently changing selection rules.

## 8. Required measurements

Report globally and by asset/timeframe/side/role where meaningful:

- role availability rate;
- unique exact geometry count;
- geometry IDs shared by structural/current-valid roles;
- structural/current-valid divergence rate;
- role episode count;
- episode lifetime bars: min/median/p75/p90/p95/max;
- role replacement count per 100 measured cutoffs;
- exact-geometry first-appearance count per 100 measured cutoffs;
- reappearing geometry count;
- reappearance episode count;
- longest-lived exact geometry IDs/roles (small bounded examples only);
- one-bar episode fraction;
- identity collision/content-mismatch count;
- source-gap/aggregation failure count.

Do not manufacture a single persistence quality score in N1.

## 9. Questions N1 must answer

1. Is exact anchor/bar-span identity stable enough to be useful observationally?
2. Is churn primarily geometry replacement, role switching, or repeated disappearance/reappearance?
3. How different are structural vs current-valid persistence characteristics?
4. Does 1h behave materially differently from 4h under the current `3/300` baseline?
5. Are there pathological one-bar/reappearance patterns that N2/H0 must account for?

N1 does not fix any observed behavior.

## 10. Explicit non-goals

No:

- fuzzy line matching;
- slope/price/anchor tolerance matching;
- persistent family registry;
- lifecycle state in the P1 adapter;
- production geometry IDs yet;
- public artifact schema version change;
- relevance score;
- distance/recency filtering;
- hyperparameter sweep;
- Optuna;
- secondary line candidate;
- multi-timeframe fusion;
- alpha/PnL/future-return objective;
- viewer redesign.

The existing disposable TVLC viewer may be used manually to inspect bounded examples, but N1 must not turn viewer work into production scope.

## 11. Focused tests

At minimum prove:

- canonical geometry identity is deterministic;
- role is excluded from geometry identity;
- current cutoff/projection/crossing metadata are excluded from identity;
- side and asset/timeframe are included;
- anchor-span difference changes identity;
- exact float canonicalization uses `float.hex()` or equivalent exact representation;
- same geometry in structural/current-valid shares ID;
- replacement creates a new role episode;
- exact reappearance retains geometry ID but starts a new episode;
- one missing expected bar is not bridged;
- 4h aggregation is UTC-aligned, exact, and fail-closed on incomplete interior buckets;
- production protected hashes remain exact.

## 12. Validation

Run:

- N1 focused tests;
- frozen V4/P1 production/research regression sufficient to protect P0/P1/G0-G7;
- Ruff `--no-cache`;
- format check;
- AST/compile/import check;
- `git diff --check`;
- cache-deletion restoration/hygiene check.

No network, commit, merge, or push.

## 13. Completion disposition

Allowed conclusions:

```text
EXACT_IDENTITY_PERSISTENCE_SUPPORTED
EXACT_IDENTITY_SUPPORTED_PERSISTENCE_HIGH_CHURN
EXACT_IDENTITY_PERSISTENCE_INCONCLUSIVE
BLOCKED_SOURCE_OR_CONTRACT
```

A high-churn result is valid evidence, not permission to add fuzzy tracking.

## 14. Approval boundary

Required explicit user approval before Codex writes N1 implementation/research files:

```text
TRENDLINES_V4_N1_EXACT_IDENTITY_PERSISTENCE_DESIGN_APPROVED
```

After approval, issue one bounded coder handoff for N1 only. N2/H0/H1/N3/N4 remain unauthorized.

NEXT_OWNER_CAN_ACT_WITHOUT_GUESSING
