# Phase 12Q.1 Quality-Signal Feasibility

## Status

`READY_FOR_TRENDLINE_V2_QUALITY_SIGNAL_FEASIBILITY_REVIEW`

R1 point-estimate evidence is superseded by R2 statistical remediation and is
preserved unchanged:

`R1 = POINT_ESTIMATE_ONLY_SUPERSEDED_PENDING_STATISTICAL_REMEDIATION`

R2 is the only current evidence candidate. Commit, merge, and push remain
unauthorized.

## Objective

Measure whether causal birth structure and interaction quality distinguish clean
future reaction quality without changing provider generation, runtime selection,
viewer behavior, YAML, or protected evidence. Relevance families remain
diagnostic and cannot qualify.

## Frozen source boundary

Read only:

`/tmp/trendline_v2_phase9c2_fresh_scope_family_validation/20260522_20260701`

Validation datasets are exactly `btcusdt_1h`, `btcusdt_4h`, `ethusdt_1h`, and
`ethusdt_4h`. SUI datasets are holdout and were not loaded. Phase 10C.2
temporal evidence was not opened; R2 records
`NOT_OPENED_BEFORE_VALIDATION_LOCK`.

Pinned source identities remain:

- decision: `4b734cbf99e1453bccdedb95f397f4b34e020f29e3d18808a131456647f78f7c`
- manifest: `beab5b9acb2bfc3c25ba9cb5cb31c33c1a31e6069c1d7906f3ed5e1c2d798c81`
- output inventory: `ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532`
- underlying inventory: `631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be`

## Frozen method and remediation

Checkpoint ages are `0`, `6`, `12`, and `24` bars; horizons are `6`, `12`,
and `24` bars. Features use only bars through checkpoint. Labels begin strictly
after checkpoint. Contacts use causal Wilder ATR-14 and
`low <= projected line <= high`.

Analysis groups are exactly:

`(dataset, role, candidate_structure_id, second_anchor_id)`

One row is selected before any future-label filtering: highest checkpoint age,
then later checkpoint position, then lexicographically smallest feature-row ID.
LODO and chronological evaluation operate on selected groups only. Chronological
train/test group IDs are persisted and their overlap is zero.

R2 adds deterministic paired grouped bootstrap intervals: 1,000 replicates,
95 percent confidence, analysis-group sampling, paired within dataset, minimum
950 valid replicates, and equal-weight pooling across four datasets. Spearman
uses true `scipy.stats.spearmanr` p-values with full reverse-cumulative BH
correction.

Viewer Focus control is exact: recent 100 bars, minimum anchor span 25,
one per second anchor, maximum 12 per role, deterministic representative and
display ordering. Membership and hashes are persisted.

Sensitivity reruns features, models, and gates for:

- `primary_v1`: 2 bars and 0.50 ATR;
- `one_bar_quarter_atr_v1`: 1 bar and 0.25 ATR;
- `three_bars_one_atr_v1`: 3 bars and 1.00 ATR.

Only `interaction_reaction_v1` and `combined_quality_v1` are intrinsic quality
families. `relevance_only_v1` and `combined_quality_plus_relevance_v1` are
diagnostic only.

## Decision gates

`QUALITY_SIGNAL_FEASIBLE` requires sufficient events in every dataset and role,
pooled AP improvement at least `0.03`, positive paired lower bound, non-negative
dataset and chronological improvements, no top-quantile breach increase above
`0.02`, stable direction across 1h and 4h, non-negative sensitivity, relevance-
free quality utility, zero source/label reconciliation, and zero chronological
group overlap.

Otherwise use `NO_ROBUST_QUALITY_SIGNAL`, `INSUFFICIENT_REACTION_EVENTS`, or
`QUALITY_EVIDENCE_INCOMPLETE`. Q1 selects no finalist, shortlist, threshold,
viewer default, or runtime parameter.

## Output boundary

R1 output remains immutable at:

`/tmp/trendline_v2_phase12q1_quality_signal_feasibility/20260522_20260701`

R2 was published once, atomically, at:

`/tmp/trendline_v2_phase12q1_quality_signal_feasibility/20260522_20260701_r2`

R2 root has 13 files, manifest has 12 members, and output inventory has 11
pre-manifest members. Canonical JSON, deterministic IDs, source-backed
rederivation, atomic staging, cleanup, and zero provider/network calls remain
mandatory.

## Scope

Only these four Git files may change:

- `scripts/analyze_trendline_v2_quality_signal_feasibility.py`
- `tests/scripts/test_trendline_v2_quality_signal_feasibility.py`
- this architect handoff
- `plans/coder-to-orchestrator-trendline-v2-phase-12q1-quality-signal-feasibility-v1.md`

No source-model, provider, tracker, viewer, YAML, runtime, holdout, temporal,
Binance, or production selector changes are authorized.
