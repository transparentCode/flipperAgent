# RegimeV2 Phase 7V Transition Micro-State Split

## Scope

- Assets/timeframes: BNBUSDT|1h, ETHUSDT|1h, BTCUSDT|1h
- Input rows per asset: 720
- Candidate source: Phase 7P setup-origin transition candidates
- Runtime posture: offline-only / diagnostic-only

## Implemented diagnostic states

- `BREAKOUT_SETUP_TRANSITION_CANDIDATE`
- `COMPRESSION_TRANSITION_OBSERVE_ONLY`
- `NO_TRANSITION_MICRO_STATE`
- `OTHER_TRANSITION_OBSERVE_ONLY`

The module preserves the existing `breakout_transition_*` namespace and adds:

- `breakout_transition_micro_state`
- `breakout_transition_micro_reason`
- `breakout_transition_micro_is_research_candidate`
- `breakout_transition_micro_is_observation_only`
- `breakout_transition_micro_runtime_enabled`

`breakout_transition_micro_runtime_enabled` is always `False`.

## Summary

- Variants: 3
- Breakout-better count: 3/3
- Runtime-enabled count: 0
- Recommendation: keep_micro_state_split_diagnostic

## Asset result

| Asset | Active | Research candidates | Observation-only | Runtime-enabled | Breakout avg | Compression avg | Breakout worst | Compression worst |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ETHUSDT | 65 | 18 | 47 | 0 | 0.00787076545146753 | -0.002290854221035898 | -0.01993357142384784 | -0.1372625352770353 |
| BTCUSDT | 71 | 39 | 32 | 0 | 0.0026041664575172 | -0.0019173813647387896 | -0.019998023133609776 | -0.028108162456439937 |
| BNBUSDT | 83 | 39 | 44 | 0 | 0.0014352216200371594 | -0.0005459484582395352 | -0.021807424769890588 | -0.04197438881769332 |

## Interpretation

7V confirms the 7U separation in an explicit diagnostic state model:

1. `BREAKOUT_SETUP_TRANSITION_CANDIDATE` is better than `COMPRESSION_TRANSITION_OBSERVE_ONLY` on all three assets.
2. Compression transitions have negative average returns and worse tail losses.
3. Runtime remains disabled by construction.
4. This is an architectural improvement, not a trading promotion.

## Decision

Keep the micro-state split as diagnostic architecture.

Do not route executable trades from transition micro-states yet.

## Next direction

Move to Phase 7W: micro-state robustness and support stress test.

Focus:

- apply rolling-window validation to the 7V micro-states
- verify breakout_setup remains better than compression in rolling windows
- require support floors per asset/window
- check whether the severe ETH compression tail is isolated or recurrent
- keep runtime disabled
