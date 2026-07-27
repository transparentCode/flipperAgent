# Coder Handoff: Phase 12Q.1 Quality-Signal Feasibility

## Result

`READY_FOR_TRENDLINE_V2_QUALITY_SIGNAL_FEASIBILITY_REVIEW`

Branch: `research/trendline-v2-phase-12q1-quality-signal-feasibility-v1`

Base HEAD: `a6fe843a93602af294f7a4d452bb0c9c20d2e119`

Implementation remains uncommitted. Commit, merge, and push are not
authorized.

## R1 supersession and protected source

R1 remains byte-identical and is not overwritten:

`/tmp/trendline_v2_phase12q1_quality_signal_feasibility/20260522_20260701`

R1 status: `POINT_ESTIMATE_ONLY_SUPERSEDED_PENDING_STATISTICAL_REMEDIATION`.

R1 manifest SHA: `902f0647867506c3e23b9b6f8a80f35329a4da7030980918ae1d35b9f1931524`

R1 output inventory SHA: `b4fed982c33f9cb4f23637f47b4f1ecdde9d3201e72d7b013e379d3dbd772ca7`.

R1 files/bytes: `13 / 107884045`.

The protected Phase 9C.2 source remains bound to:

- decision: `4b734cbf99e1453bccdedb95f397f4b34e020f29e3d18808a131456647f78f7c`
- manifest: `beab5b9acb2bfc3c25ba9cb5cb31c33c1a31e6069c1d7906f3ed5e1c2d798c81`
- output inventory: `ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532`
- underlying inventory: `631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be`
- source manifest SHA: `4db6402a4fdd911cbe8a1b4b30f8ee27431e2f2c751a572d1fec92f0b7d25121`

## R2 evidence

R2 output root:

`/tmp/trendline_v2_phase12q1_quality_signal_feasibility/20260522_20260701_r2`

R2 was executed exactly once under guard and strict-verified read-only. No
provider or network call occurred.

- status: `NO_ROBUST_QUALITY_SIGNAL`
- finalist: `null`
- contract: `0aae93d29f9ba7652ad10620cee308a42075cb47d654ad3b2028e61f77247e94`
- source binding: `36e1ed01daf70e61e0a6e83aab83977ec8a51cf3cfec4d6327ac9a09c22f2e32`
- validation lock: `ae38125102020a2bce83bb2ee9c75024d4cf1ed5e9b13c542ab2fc4af74dde68`
- decision: `376b3721021b0295e1cb6e70e7d0a40bd8c504ebacb253f1fc5dedaa2e2de903`
- manifest: `af82527eb19b3238494ed449158a7774630f633b61497a77075a29b8a835ef20`
- output inventory SHA: `8e6d2f18c97443f8dcb5939496e2c6b3cf4b98d68d4654473838fd87a957c8e0`
- manifest file SHA: `0d0a8855f0e53bc5571260e5eb2940360116f128243168697a98fd97b4bffd1e`
- validation lock file SHA: `7f64d87b07a2d5c7d78db1461ae80a7f507f9fe572081b018850755f543a0236`
- output inventory ID: `ac6d2ed30a935df55b75651d5828e675b003b794794e7a744e106843e82bf599`
- root files / manifest members: `13 / 12`
- inventory members / indexed bytes: `11 / 119929584`
- unresolved reconciliation: `0`

## Evidence counts and grouping

| Evidence | Count |
|---|---:|
| candidate checkpoint rows | 22,072 |
| contact episode rows | 5,814 |
| future reaction rows | 66,216 |
| feature-family rows | 20 |
| control rows | 20 |
| chronological rows | 20 |
| feature ablation rows | 12 |
| association rows | 204 |
| BH-adjusted associations below 0.05 | 122 |

Analysis identity is `(dataset, role, candidate_structure_id,
second_anchor_id)`. Source checkpoint rows: `22,072`; selected analysis groups:
`9,750`; discarded repeated rows: `12,322`. Selected checkpoint-age counts:
`0=4,513`, `6=1,170`, `12=1,047`, `24=3,020`.

At 24 bars, reached-contact rows:

| Dataset | Resistance | Support |
|---|---:|---:|
| BTCUSDT 1h | 1,658 | 1,450 |
| BTCUSDT 4h | 176 | 203 |
| ETHUSDT 1h | 1,421 | 1,476 |
| ETHUSDT 4h | 212 | 236 |

All eight dataset-role lanes reached contact. LODO and chronological train/test
group overlap are zero for all 20 model rows.

## Bootstrap and model evidence

Bootstrap is deterministic, paired within dataset, grouped by analysis group,
1,000 replicates, 95 percent intervals, minimum 950 valid replicates. Every
family/dataset and pooled result has `1000` valid and `0` invalid replicates.

Intrinsic family AP deltas versus birth structure:

| Family | BTC 1h | BTC 4h | ETH 1h | ETH 4h | Pooled delta | Pooled 95% CI |
|---|---:|---:|---:|---:|---:|---:|
| interaction_reaction_v1 | -0.003113 | -0.004219 | 0.027883 | 0.110030 | 0.032645 | [-0.015392, 0.081082] |
| combined_quality_v1 | -0.000383 | 0.230580 | 0.073158 | 0.028228 | 0.082896 | [0.037452, 0.141935] |

Both intrinsic families fail at least one required gate. Interaction fails
dataset-direction, chronological-direction, lower-bound, and top-breach gates.
Combined quality has positive pooled CI but fails dataset-direction,
chronological-direction, and top-breach gates. Relevance families remain
diagnostic and ineligible.

Chronological deltas for intrinsic families:

| Family | BTC 1h | BTC 4h | ETH 1h | ETH 4h |
|---|---:|---:|---:|---:|
| interaction_reaction_v1 | -0.002843 | 0.037662 | -0.033945 | 0.189435 |
| combined_quality_v1 | -0.004697 | 0.063475 | 0.007377 | -0.027041 |

## Focus control and sensitivity

Focus is exact: recent 100 bars, minimum span 25, one per second anchor,
maximum 12 per role. Each dataset selects 24 members. Membership hashes:

- BTCUSDT 1h: `eb8414745f70e2443bd57668fa8480ecf3cd5ac5a165113627975f5338e4910a`
- BTCUSDT 4h: `073c0f45a138ca98d8bb99f82e39342389e2cf5ef39e99e07ff83bf8c7963c8c`
- ETHUSDT 1h: `2966a93f985846d6f842eccafcfd23d27dd5ffb34c85255c7f3628fca1ec84d5`
- ETHUSDT 4h: `6a1faeadf960c8862cf0f844d7d9f3ff3a8c5d1bf4c670bef80e551bcf7e277c`

Sensitivity reran feature derivation, model validation, and gate inputs:

| Definition | Episodes | Clean | Clean rate | Interaction pooled delta | Combined pooled delta |
|---|---:|---:|---:|---:|---:|
| primary_v1 | 927 | 825 | 0.889968 | 0.032645 | 0.082896 |
| one_bar_quarter_atr_v1 | 1,010 | 885 | 0.876238 | 0.024020 | 0.081033 |
| three_bars_one_atr_v1 | 873 | 782 | 0.895762 | 0.000847 | 0.035621 |

Sensitivity does not rescue intrinsic-family gates.

## Validation and boundary

- guarded R2 run: exactly one execution, no retry;
- strict R2 `--verify`: passed;
- focused suite after remediation: `30 passed`;
- full Trendline V2/research gate: pending final validation;
- canonical plural Trendlines: pending final validation;
- Ruff, compileall, and diff checks: passed before final documentation edit.

No SUI holdout, temporal source, Binance adapter, provider, network, runtime,
YAML, viewer, or production selector was accessed. R1 and protected Phase 9C.2
source bytes remain unchanged. R2 source-backed verification passed with source
manifest SHA unchanged at `4db6402a4fdd911cbe8a1b4b30f8ee27431e2f2c751a572d1fec92f0b7d25121`.

## Current worktree

Exactly four intended untracked files, no staged/tracked modifications:

- `scripts/analyze_trendline_v2_quality_signal_feasibility.py`
- `tests/scripts/test_trendline_v2_quality_signal_feasibility.py`
- `plans/architect-to-coder-trendline-v2-phase-12q1-quality-signal-feasibility-v1.md`
- `plans/coder-to-orchestrator-trendline-v2-phase-12q1-quality-signal-feasibility-v1.md`

Codebase-memory reindex is required once after this handoff. Existing indexes
remain protected if indexing fails.

```text
PHASE 12Q.1 R2: COMPLETE_VALIDATION_ONLY
QUALITY_SIGNAL: NO_ROBUST_QUALITY_SIGNAL
FINALIST: NONE
HOLDOUT: UNOPENED
TEMPORAL: UNOPENED
COMMIT/MERGE/PUSH: NOT AUTHORIZED
```
