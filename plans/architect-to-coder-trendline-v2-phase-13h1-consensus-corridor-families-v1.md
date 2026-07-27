# Phase 13H.1: Consensus Corridor Families

## Status

READY_FOR_TRENDLINE_V2_CONSENSUS_CORRIDOR_FAMILY_IMPLEMENTATION

## Objective

Measure whether causal same-role trendline structures form compact, stable
consensus corridors across fixed validation checkpoints. This is diagnostic
research only. It must not select representatives, rank candidates, change the
provider, or alter viewer/runtime behavior.

## Frozen sources

Read only:

```text
/tmp/trendline_v2_phase9c2_fresh_scope_family_validation/20260522_20260701
```

Required source identities:

```text
decision:                 4b734cbf99e1453bccdedb95f397f4b34e020f29e3d18808a131456647f78f7c
manifest:                 beab5b9acb2bfc3c25ba9cb5cb31c33c1a31e6069c1d7906f3ed5e1c2d798c81
output inventory:         ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532
underlying inventory:     631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be
source manifest SHA-256:  4db6402a4fdd911cbe8a1b4b30f8ee27431e2f2c751a572d1fec92f0b7d25121
```

Validation datasets are exactly `btcusdt_1h`, `btcusdt_4h`, `ethusdt_1h` and
`ethusdt_4h`. SUI, holdout, Phase 10C.2 temporal evidence, Binance, provider,
network and legacy execution are prohibited.

## Frozen causal method

- 24-hour checkpoints after a 336-hour warmup; require at least 10 per lane.
- Causal prefix is `bar_open < checkpoint`; candidate availability is
  `candidate_available_at <= checkpoint`.
- Validate exact-side geometry on every known bar: support line is `<=
  min(open, close)` and resistance line is `>= max(open, close)`. Equality is
  valid. No minimum anchor-span filter applies to family input.
- Deduplicate observations by dataset, role and candidate structure ID.
  Keep earliest causal availability, then lexicographically smallest candidate
  ID.
- Project line geometry at checkpoint, checkpoint+24h and checkpoint+96h.
  Normalize each coordinate as `(projected line price - checkpoint close) /
  checkpoint ATR-14`. Distance is maximum absolute coordinate difference.
- Cluster support and resistance independently with deterministic complete
  linkage and Chebyshev distance at thresholds `0.25`, `0.50` and `1.00` ATR.
- Family ordering is role, `g0`, `g24`, `g96`, structure ID, candidate ID.
  Family IDs include dataset, role, checkpoint, variant and sorted member
  structure IDs.
- Adjacent families match by Jaccard descending, envelope overlap descending,
  medoid distance ascending and family ID. A match is admissible when Jaccard
  is at least `0.25`, or envelope overlap is at least `0.50` with medoid
  distance at most `0.50`. Persist birth, continuation, death, merge, split
  and unmatched events.

## Controls and gates

Persist raw valid structures, one-per-second-anchor, current Focus and prior
latest-valid-predecessor controls. Focus remains display-only: recent 100 bars,
minimum span 25, unique second anchor and maximum 12 per role.

Evaluate, without promotion:

- integrity and population;
- pooled median compression at least 5x;
- worst-lane median compression at least 3x;
- pooled median family count per role in `[4, 12]`;
- worst-lane p90 family count at most 20;
- non-singleton coverage at least 0.60;
- multi-anchor coverage at least 0.30;
- median t0 width at most 0.50 ATR;
- p90 t0 width at most 1.00 ATR;
- p90 t96 width at most 1.50 ATR;
- continuation coverage at least 0.60;
- continued-family Jaccard at least 0.30;
- family-count churn at most 0.40.

Decision statuses are limited to:

```text
CONSENSUS_CORRIDOR_FORMATION_FEASIBLE
NO_STABLE_CONSENSUS_CORRIDOR_COMPRESSION
INSUFFICIENT_ACTIVE_STRUCTURE
CONSENSUS_CORRIDOR_EVIDENCE_INCOMPLETE
```

No finalist, representative, quality score or viewer selection may be
produced.

## Artifact contract

Create exactly 13 files, with 12 manifest members, under:

```text
/tmp/trendline_v2_phase13h1_consensus_corridor_families/20260522_20260701
```

Required files:

```text
study_contract.json
source_binding.json
checkpoint_schedule.json
active_candidate_rows.json
family_membership.json
family_geometry.json
temporal_family_links.json
compression_metrics.json
control_comparison.json
validation_lock.json
decision.json
output_inventory.json
manifest.json
```

All JSON is canonical, finite and duplicate-key-free. IDs and member hashes
must be rederived. Publication is atomic and refuses an existing output root.
Staging is created before source access and removed on failure.

## Scope

Modify only the script, focused tests and coder handoff named by this phase.
Do not modify `src/`, viewer, provider, selection, tracking, interaction,
configuration, YAML, Regime, canonical Trendlines or prior research scripts.

## Execution boundary

Tests and static checks must pass before one guarded canonical execution:

```text
TRENDLINE_V2_ALLOW_PHASE13H1_STUDY=1
```

If canonical execution partially fails, do not retry. Strict verification must
run without the execution variable. H.2, viewer family mode, production
selection, parameter promotion and push remain unauthorized.
