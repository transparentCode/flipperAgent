# RegimeV2 Phase 7T Transition Micro-Regime Diagnostics

## Scope

- Input: `research/regime_v2_phase7r_transition_setup_prune.json`
- Assets: BNBUSDT, ETHUSDT, BTCUSDT
- Variants analyzed: 243
- Tagged split records: 972
- Runtime posture: offline-only / diagnostic-only

## Purpose

Phase 7S confirmed that the transition setup family is promising but support-thin. Phase 7T adds diagnostic micro-regime tags over the 7R matrix to explain failure pockets without hardcoding timestamps or split indices.

Tags are based on:

- market phase mode: all / breakout_setup / compressed_wait
- support-thin split
- direction skew
- volatility-prune mode
- continuation-prune mode
- validation failure reason tags

Only historical/config tags such as `phase_compressed_wait`, `phase_breakout_setup`, `volatility_tail_pruned`, and `continuation_pruned` are candidates for future policy research. Outcome-derived tags such as `reason_avg_return_too_low` must not be used as live rules.

## Summary

- Recommendation: test_micro_regime_exclusion_next
- Worst broad tag: `reason_avg_return_too_low`
- Failure-tag result is expected: outcome-derived failure reasons explain bad cells but are not policy-safe.

## Cross-asset tag behavior

| Tag | Splits | Failed | Avg directional return | Worst loss | Interpretation |
|---|---:|---:|---:|---:|---|
| reason_avg_return_too_low | 504 | 504 | -0.003919406153918577 | -0.04197438881769332 | outcome-derived; not policy-safe |
| reason_low_passing_rate | 713 | 713 | -0.001657332247787307 | -0.04197438881769332 | outcome-derived; not policy-safe |
| reason_worst_cell_too_negative | 734 | 734 | -0.0013485806175057746 | -0.04197438881769332 | outcome-derived; not policy-safe |
| phase_compressed_wait | 324 | 294 | -0.0009274491756564162 | -0.04197438881769332 | policy-safe diagnostic weakness |
| phase_all | 324 | 263 | 0.0006871993216562925 | -0.028108162456439937 | mixed |
| direction_skew | 426 | 348 | 0.0008186474983045726 | -0.04197438881769332 | not sufficient alone |
| continuation_pruned | 648 | 563 | 0.0009445518423996141 | -0.028108162456439937 | not sufficient alone |
| phase_breakout_setup | 324 | 264 | 0.002895328674772492 | -0.018818934271775577 | strongest policy-safe phase tag |

## Asset summary

| Asset | Tagged splits | Failed splits | Worst avg split | Worst loss | Top recurring tags |
|---|---:|---:|---:|---:|---|
| BNBUSDT | 324 | 239 | -0.020230797965835292 | -0.04197438881769332 | worst-cell / low-pass / continuation-pruned |
| ETHUSDT | 324 | 264 | -0.017957609803825245 | -0.027684296033083134 | worst-cell / low-pass / continuation-pruned |
| BTCUSDT | 324 | 318 | -0.02007353386983558 | -0.028108162456439937 | worst-cell / low-pass / continuation-pruned |

## Interpretation

7T reinforces the earlier 7R finding:

- `breakout_setup` transition candidates are materially stronger than `compressed_wait` candidates.
- `compressed_wait` is a cross-asset weakness tag and should be treated as a separate micro-regime, not merged with breakout setup.
- Direction skew and continuation pruning do not explain enough on their own.
- Outcome-derived failure tags are useful for diagnosis but must not become live rules.

## Decision

Do not promote any transition setup logic yet.

The safest next step is not to add another broad prune. Instead, test a focused exclusion / separation design:

1. keep `breakout_setup` transition candidates as the research candidate family
2. separate `compressed_wait` into a blocked or observation-only micro-regime
3. retest whether this separation improves support-aware metrics without relying on outcome-derived tags

## Next direction

Move to Phase 7U: policy-safe micro-regime separation test.

Focus:

- compare `breakout_setup` only vs `compressed_wait` only vs all candidates
- report support-aware metrics for each separately
- treat `compressed_wait` as diagnostic blocked, not deleted by outcome
- validate whether the separation holds on BNB/BTC as sanity checks
