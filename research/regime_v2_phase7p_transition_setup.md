# RegimeV2 Phase 7P Setup-Origin Transition Candidates

## Scope

- Assets/timeframes: BNBUSDT|1h, ETHUSDT|1h, BTCUSDT|1h
- Input rows per asset: 720
- Base path: Phase 7K context gate -> Phase 7P setup-origin transition candidates -> dedicated transition outcome matrix / walk-forward validation
- Candidate source: gated `WAIT_COMPRESSION`, `BREAKOUT_SETUP`, and setup-like rows
- Feature family: historical wick rejection, range breakout attempt, range position, normalized momentum, context score
- Lookbacks: 8, 12, 20 bars
- Candidate-score thresholds: 0.58, 0.62, 0.66
- Runtime posture: offline-only / diagnostic-only

## Summary

- Variants: 27
- Ready variants: 0
- Recommendation: hold_off_setup_transition_unstable
- Best variant: ETHUSDT|1h, lookback 8, min_candidate_score 0.62
- Best active candidates: 61
- Best splits passed: 3/4
- Best avg split directional return: 0.0039739721595662865
- Best worst split directional return: -0.003882197085900328

## Per-asset result

| Asset | Variants | Max active candidates | Best passed splits | Best avg split directional | Best worst split directional | Interpretation |
|---|---:|---:|---:|---:|---:|---|
| BNBUSDT | 9 | 92 | 2/4 | 0.0014702568291734288 | -0.005427503391288226 | support improves, still unstable |
| ETHUSDT | 9 | 66 | 3/4 | 0.0047578560351840115 | -0.0027732003430175805 | strongest candidate family, one failed split remains |
| BTCUSDT | 9 | 76 | 1/4 | 0.0009192539894406193 | -0.0025965827966905348 | not robust |

## Top variants

| Asset | Lookback | Min score | Active | Passed | Avg split dir | Worst split dir | Direction mix |
|---|---:|---:|---:|---:|---:|---:|---|
| ETHUSDT | 8 | 0.62 | 61 | 3/4 | 0.0039739721595662865 | -0.003882197085900328 | down 31 / up 30 |
| ETHUSDT | 8 | 0.58 | 66 | 3/4 | 0.003671589930131386 | -0.003882197085900328 | down 33 / up 33 |
| ETHUSDT | 8 | 0.66 | 52 | 2/4 | 0.004598568998353891 | -0.0028739044176989913 | down 25 / up 27 |
| ETHUSDT | 20 | 0.62 | 40 | 2/4 | 0.004074906459843064 | -0.006713553121788876 | down 24 / up 16 |
| BNBUSDT | 20 | 0.66 | 47 | 2/4 | 0.0014702568291734288 | -0.006266821230584193 | down 25 / up 22 |

## Interpretation

Phase 7P is a meaningful improvement over 7O because it generates broader support from setup context instead of waiting for active 7F confirmations. ETHUSDT shows the first useful transition candidate family: balanced long/short direction mix, 50+ candidates, positive average split return, and 3/4 splits passed.

However, 7P is still not candidate-ready:

- Ready variants: 0/27.
- ETH has one failed split with a materially negative worst split return.
- BNB and BTC do not generalize strongly enough.
- Cross-asset support is not sufficient.

## Decision

Do not promote 7P. Keep it as the first useful transition candidate family. The next phase should diagnose the ETH 3/4 failure pocket and derive a stability/pruning rule without overfitting.

## Next direction

Move to Phase 7Q: setup-transition failure diagnostics / pruning discovery.

Focus:

- identify which split and direction bucket breaks ETH
- compare lookback 8 vs 12 vs 20 failure signatures
- inspect horizon/fee cells that fail
- test a diagnostic prune such as direction balance, minimum active-per-split, or horizon-specific volatility filter
- require cross-asset sanity before any promotion
