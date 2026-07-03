# RegimeV2 Phase 7O Breakout Transition-State Prototype

## Scope

- Assets/timeframes: BNBUSDT|1h, ETHUSDT|1h, BTCUSDT|1h
- Input rows per asset: 720
- Base path: Phase 7K context gate -> Phase 7F follow-through -> Phase 7O separate transition state -> dedicated transition outcome matrix / walk-forward validation
- Thresholds: 0.25, 0.30
- Transition score thresholds: 0.52, 0.58, 0.64
- Max continuation score thresholds: 0.72, 0.78
- Runtime posture: offline-only / diagnostic-only

## Implemented states

- `NO_BREAKOUT_TRANSITION`
- `BREAKOUT_EXHAUSTION_TRANSITION`
- `FAILED_BREAKOUT_REVERSAL_SETUP`

The 7O layer does not rewrite `BREAKOUT_CONFIRMATION`. It emits a separate `breakout_transition_*` namespace and validates the transition direction independently.

## Summary

- Variants: 36
- Ready variants: 0
- Recommendation: hold_off_transition_state_unstable
- Best variant: BTCUSDT|1h threshold 0.30, min_transition_score 0.52, max_continuation_score 0.72
- Best active transition states: 1
- Best splits passed: 1/4
- Best avg split directional return: 0.00993005251230855
- Best worst split directional return: 0.003604680378694455

## Per-asset observations

| Asset | Variants | Active variants | Max active states | Best avg split directional | Best passed splits | Interpretation |
|---|---:|---:|---:|---:|---:|---|
| BNBUSDT | 12 | 12 | 6 | -0.005385717491787806 | 1/4 | negative expectancy |
| ETHUSDT | 12 | 12 | 4 | -0.003989151169300934 | 0/4 | negative expectancy |
| BTCUSDT | 12 | 12 | 6 | 0.00993005251230855 | 1/4 | small positive pocket, weak support |

## Interpretation

Phase 7O is architecturally cleaner than 7L/7N because transition handling is no longer a direction rewrite on `BREAKOUT_CONFIRMATION`. However, the first prototype is not statistically useful yet:

- No variant is ready.
- BNB and ETH transition states have negative expectancy.
- BTC has one positive pocket, but support is too thin: only one active transition state in the best variant and only 1/4 splits passed.

The important outcome is architectural: transition logic now has a separate offline state namespace and validation path. The next step should improve feature design and support, not promote the current scoring rule.

## Next direction

Move to Phase 7P: transition-state feature expansion. Candidate improvements:

- add early adverse excursion / recovery features
- add failed-breakout reclaim timing
- separate exhaustion-after-success from failed-breakout reversal
- validate transition states directly from setup context, not only active 7F confirmations
- require minimum cross-asset support before any candidate promotion
