# Phase 14A.1 Coder Handoff

## Phase 14A.1-R1 remediation boundary

Original canonical attempt is permanently retired after a prepublication
failure in state-stratified utility. R1 is a separately versioned contract,
not a retry or regeneration of the original study.

```text
Study schema:
trendline_v2_phase_14a1r1_actionable_interaction_shortlist_v1

Output root:
/tmp/trendline_v2_phase14a1r1_actionable_interaction_shortlist/20260522_20260701

Execution guard:
TRENDLINE_V2_ALLOW_PHASE14A1R1_STUDY=1
```

## Objective

Build a read-only, source-bound feasibility study for causal actionable
interaction shortlists. This phase tests whether approaching, near and
contacting lines can be reduced to bounded per-role populations without
introducing a quality selector or runtime behavior.

## Frozen sources

```text
H1 root:
/tmp/trendline_v2_phase13h1_consensus_corridor_families/20260522_20260701
H1 commit:
f59523c9cb8353575d79003a96e4c5f9c09aca00
H1 decision:
2cf8dcb50c4efa903108dc71b420347e0ab6187e1e86c0f151b6732e1bb8263c
H1 manifest:
1cff9a2dab15feeec7cae52a8507eb25625b63294b7acf6a82bf161396463471
H1 inventory:
b232ab323f7bb100eefc34f0c255180f73232e1bc52910b285ea23d26ee23da8

Phase 9C.2 root:
/tmp/trendline_v2_phase9c2_fresh_scope_family_validation/20260522_20260701
Phase 9C.2 decision:
4b734cbf99e1453bccdedb95f397f4b34e020f29e3d18808a131456647f78f7c
Phase 9C.2 manifest:
beab5b9acb2bfc3c25ba9cb5cb31c33c1a31e6069c1d7906f3ed5e1c2d798c81
Phase 9C.2 output inventory:
ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532
Underlying source inventory:
631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be
Source manifest SHA-256:
4db6402a4fdd911cbe8a1b4b30f8ee27431e2f2c751a572d1fec92f0b7d25121
```

Read only four validation datasets: `btcusdt_1h`, `btcusdt_4h`, `ethusdt_1h`,
`ethusdt_4h`. Do not access SUI holdout, Phase 10C.2 temporal evidence,
Binance, network, provider, legacy or runtime paths.

## Frozen study contract

- Reverify H1 before reading population rows; reconcile 27 checkpoints per
  dataset, 108 checkpoints, 216 role cells and 39,139 active rows.
- Reconcile every H1 active row to the Phase 9C.2 candidate identity,
  anchors, confirmation positions, availability, span and g0/g24/g96 values.
- Derive all features causally from the checkpoint prefix and Wilder ATR-14.
- Use role-aware range distance, close distance, historical approach velocity,
  consistency, net closure, projected contact time and exact wick contact.
- Evaluate exactly these policies:
  `actionable_immediate_v1` 24h / 0.50 ATR / 24h,
  `actionable_balanced_v1` 48h / 1.00 ATR / 48h,
  `actionable_broad_v1` 96h / 2.00 ATR / 96h.
  All use consistency `0.60` and net closure `0.50`.
- States are `CONTACTING`, `NEAR`, `APPROACHING`, `DORMANT`; only first three
  are actionable.
- Select one candidate per second anchor, then deterministic state/range/
  projection/consistency/closure/confirmation/identity ordering, with budgets
  5 and 10 per role.
- Persist every membership outcome: `SELECTED`, `OUTSIDE_BUDGET`,
  `DUPLICATE_SECOND_ANCHOR`, `NOT_ACTIONABLE`.
- Controls: exact-count nearest-distance and deterministic hash controls;
  current Focus (`100` recent bars, span `25`, unique second anchor, max `12`
  per role), with confirmation age measured from the final completed candle
  (`checkpoint_position - 1`); all-valid descriptive population.
- Evaluate horizons `24`, `48`, `96` hours. Convert each horizon exactly to
  owner-timeframe bars per dataset and persist both hour and bar-count fields.
  Contact uses exact wick intersection, zone uses `+/-0.35 ATR`, breach
  requires two consecutive closes beyond role-aware `0.50 ATR`, and reaction
  starts strictly after the contact bar with `1 ATR` favorable movement.
- Compare paired checkpoint-role cells with deterministic 1,000-replicate,
  95% bootstrap; require at least 950 valid replicates. Early is checkpoints
  1-13; late is 14-27.
- Persist descriptive adjacent shortlist stability for every policy, budget,
  dataset and role: Jaccard, full replacement, one-empty transitions and lane
  summaries. This adds no decision gate.
- Persist contender-only utility separately for `CONTACTING`, `NEAR` and
  `APPROACHING` by policy, budget, dataset, role and horizon hours. Weight
  utility by checkpoint-role cells; absent states retain null metrics.
- Derive and persist integrity diagnostics for active rows, features,
  memberships, controls, outcomes, causal feature history and future outcome
  boundaries. Derive integrity status and unresolved/reconciliation counts from
  these diagnostics.
- Construct pre-evaluation source binding from the validated `source_before`
  snapshot, capture `source_after` only after feature/selection/outcome/bootstrap
  derivation, and persist final binding and validation lock from that post-
  evaluation snapshot.

## Decision gates

Freeze gates exactly: integrity; pooled coverage `>=0.80`; worst lane coverage
`>=0.65`; median selected `2..budget`; median eligible `<=30`; worst eligible
p90 `<=60`; 48h nearest zone precision pooled `>=0.02`, bootstrap lower `>0`,
worst dataset `>=-0.02`; 48h cell-hit delta `>=0`; 96h survival delta `>=0`,
worst dataset breach increase `<=0.02`; exact precision delta `>=0`; late
pooled delta `>=0`, worst late `>=-0.03`; bootstrap sufficiency; and at least
  20% selected observations in `NEAR`/`APPROACHING`. No additional thresholds
  or changes to policies, budgets or existing gates are allowed.

Statuses are exactly:

```text
ACTIONABLE_INTERACTION_SHORTLIST_FEASIBLE
NO_ACTIONABLE_INTERACTION_SHORTLIST_FINALIST
INSUFFICIENT_ACTIONABLE_POPULATION
ACTIONABILITY_EVIDENCE_INCOMPLETE
```

No parameter recommendation, promotion, quality ranking or runtime implication.

## Files and execution boundary

Create only:

```text
scripts/analyze_trendline_v2_actionable_interaction_shortlist.py
tests/scripts/test_trendline_v2_actionable_interaction_shortlist.py
plans/architect-to-coder-trendline-v2-phase-14a1-actionable-interaction-shortlist-v1.md
plans/coder-to-orchestrator-trendline-v2-phase-14a1-actionable-interaction-shortlist-v1.md
```

Output, when separately authorized, is
`/tmp/trendline_v2_phase14a1r1_actionable_interaction_shortlist/20260522_20260701`
with 13 files and 12 manifest members. Use guard
`TRENDLINE_V2_ALLOW_PHASE14A1R1_STUDY=1`, missing-root refusal, staging before
source access, pre-evaluation validation lock, canonical JSON, source
snapshots, strict source-backed verification and one atomic replacement.

Canonical execution is not authorized in this implementation stage.
