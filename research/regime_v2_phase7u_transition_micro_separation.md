# RegimeV2 Phase 7U Transition Micro-Regime Separation

## Scope

- Input: `research/regime_v2_phase7r_transition_setup_prune.json`
- Assets: BNBUSDT, ETHUSDT, BTCUSDT
- Variants analyzed: 243
- Groups: `breakout_setup`, `compressed_wait`, `all`
- Runtime posture: offline-only / diagnostic-only

## Goal

Phase 7T identified `breakout_setup` as stronger than `compressed_wait`. Phase 7U tests that separation directly using policy-safe phase groups only. It does not use outcome-derived failure tags as live rules.

## Summary

- Separation decision: `separate_breakout_setup_from_compressed_wait`
- Ready groups: 0
- Best group: `breakout_setup`
- Best group recommendation: `keep_as_research_candidate`
- `compressed_wait` recommendation: `separate_as_observation_only`

## Group result

| Group | Variants | Ready | Promising | Watch | Max active | Best passed | Avg split return | Best avg | Worst split return | Best worst | Recommendation |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| breakout_setup | 81 | 0 | 6 | 9 | 39 | 3/4 | 0.0027802186339219628 | 0.007382640965507925 | -0.018818934271775577 | -0.0019351374847817401 | keep_as_research_candidate |
| all | 81 | 0 | 3 | 16 | 83 | 3/4 | 0.0007493417752237013 | 0.00482404598918966 | -0.028108162456439937 | -0.0036750222971532417 | diagnostic_only |
| compressed_wait | 81 | 0 | 0 | 3 | 44 | 2/4 | -0.0009066273850703485 | 0.004676232582096775 | -0.04197438881769332 | -0.004511152249982155 | separate_as_observation_only |

## Best group detail

Best group: `breakout_setup`

- Cross-asset average split return: 0.0027802186339219628
- Best variant: ETHUSDT|1h
- Best variant config:
  - allowed_market_phases: breakout_setup
  - lookback_bars: 8
  - min_candidate_score: 0.62
  - max_volatility_quantile: 0.85
  - max_continuation_score: none
- Best variant active candidates: 15
- Best variant supported splits: 3/4
- Best variant passed splits: 3/4
- Best variant avg split return: 0.007382640965507925
- Best variant worst split return: -0.0019351374847817401

## Interpretation

Phase separation is justified:

1. `breakout_setup` has the best average behavior and the only meaningful promising variants.
2. `compressed_wait` is negative on average, has worse tail losses, and fails to produce promising variants.
3. The mixed `all` group dilutes the cleaner `breakout_setup` behavior.

This supports a future architecture where transition setups are not a single undifferentiated bucket:

- `breakout_setup_transition`: research candidate, still disabled
- `compressed_wait_transition`: observation-only / blocked diagnostic state

## Decision

Do not promote transition trading logic.

Do promote the architectural separation idea into the next diagnostic prototype: keep separate transition micro-regime states, but runtime-disabled.

## Next direction

Move to Phase 7V: transition micro-regime state split prototype.

Focus:

- create explicit diagnostic states for `BREAKOUT_SETUP_TRANSITION_CANDIDATE` and `COMPRESSION_TRANSITION_OBSERVE_ONLY`
- keep both separate from executable playbook states
- preserve existing 7O/7P transition namespace
- validate that the state split reproduces 7U grouping cleanly
- avoid promotion until support and robustness improve
