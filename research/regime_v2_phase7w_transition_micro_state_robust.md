# RegimeV2 Phase 7W Micro-State Robustness Stress

## Scope

- Assets/timeframes: BNBUSDT|1h, ETHUSDT|1h, BTCUSDT|1h
- Input rows per asset: 720
- Candidate source: Phase 7V micro-state split
- Windows: full, 0:360, 180:540, 360:720
- Support floor: both micro-states need at least 6 active candidates per window
- Runtime posture: offline-only / diagnostic-only

## Summary

- Variants: 3
- Supported windows: 11
- Supported breakout-better windows: 8
- Support-ready assets: 1/3
- Runtime-enabled count: 0
- Recommendation: keep_diagnostic_not_robust

## Asset result

| Asset | Supported windows | Breakout-better supported windows | Support-ready | Worst breakout | Worst compression | Recommendation |
|---|---:|---:|---|---:|---:|---|
| BNBUSDT | 4 | 2 | false | -0.021807424769890588 | -0.04197438881769332 | micro_state_split_window_mixed |
| ETHUSDT | 3 | 3 | true | -0.01993357142384784 | -0.1372625352770353 | micro_state_split_window_supported |
| BTCUSDT | 4 | 3 | false | -0.019998023133609776 | -0.028108162456439937 | micro_state_split_window_mixed |

## Window notes

### BNBUSDT

- Full window: breakout better.
- 0:360: compression average was higher than breakout despite worse tail.
- 180:540: compression average was higher; breakout average was negative.
- 360:720: breakout better, but both states remained negative.

BNB verdict: mixed.

### ETHUSDT

- Full window: breakout better.
- 0:360: breakout better.
- 180:540: breakout better.
- 360:720: breakout better but breakout support was only 5, below the support floor.

ETH verdict: strongest split, but the last rolling window is support-thin.

Compression tail remains severe: -0.1372625352770353.

### BTCUSDT

- Full window: breakout better.
- 0:360: breakout better.
- 180:540: compression average was higher; breakout average was negative.
- 360:720: breakout better.

BTC verdict: mixed.

## Interpretation

The 7V micro-state split remains useful, but it is not robust enough to promote.

Evidence in favor:

- Breakout setup is better in 8 of 11 supported windows.
- ETH is fully support-ready across supported windows.
- Runtime-enabled count is 0.

Evidence against promotion:

- BNB and BTC each have a middle rolling window where compression beats breakout.
- ETH's final rolling window has only 5 breakout candidates, below the support floor.
- Compression tails remain severe, especially ETH.
- Only 1 of 3 assets is support-ready.

## Decision

Keep the micro-state split diagnostic.

Do not promote transition micro-states into live routing or execution.

## Next direction

Move to Phase 7X: transition micro-state failure-window diagnostics.

Focus:

- explain BNB/BTC middle-window failures without timestamp rules
- inspect feature distributions for the failed windows versus passing windows
- keep `COMPRESSION_TRANSITION_OBSERVE_ONLY` blocked
- look for a policy-safe context tag that distinguishes failed middle windows from supported ETH behavior
- keep runtime disabled
