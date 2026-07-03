# RegimeV2 Phase 7S Transition Support Validation

## Scope

- Input: `research/regime_v2_phase7r_transition_setup_prune.json`
- Variants scored: 243
- Assets: ETHUSDT, BNBUSDT, BTCUSDT
- Runtime posture: offline-only / diagnostic-only

## Criteria

- Minimum total active candidates: 30
- Minimum active candidates per split: 3
- Required passed splits: 4/4
- Minimum support score: 0.75
- Maximum worst split loss: -0.001

## Summary

- Support-ready variants: 0
- Promising/watch variants: 37
- Recommendation: keep_diagnostic_collect_more_support

## Asset summary

| Asset | Variants | Best grade | Max active | Best passed | Best avg split return | Best worst split return |
|---|---:|---|---:|---:|---:|---:|
| ETHUSDT | 81 | promising_thin | 61 | 3/4 | 0.007382640965507925 | -0.0019351374847817401 |
| BNBUSDT | 81 | watchlist | 83 | 2/4 | 0.004587636075841864 | -0.003977057988241181 |
| BTCUSDT | 81 | blocked | 71 | 1/4 | 0.0037205453606499023 | -0.0040799415997798015 |

## Best support-aware variant

- Asset/timeframe: ETHUSDT|1h
- Grade: promising_thin
- Config:
  - lookback_bars: 8
  - min_candidate_score: 0.62
  - allowed_market_phases: breakout_setup
  - max_volatility_quantile: 0.85
  - max_continuation_score: none
  - min_score_gap: 0.0
- Active candidates: 15
- Minimum split active count: 2
- Supported splits: 3/4
- Passed splits: 3/4
- Support score: 0.6625
- Avg split directional return: 0.007382640965507925
- Worst split directional return: -0.0019351374847817401

## Blockers

The best ETH variant is blocked by:

- total_support_low
- split_support_low
- passed_splits_low
- support_score_low
- worst_loss_too_negative

The unpruned ETH family has better support:

- active candidates: 61
- supported splits: 4/4
- support score: 0.95
- passed splits: 3/4
- avg split directional return: 0.0039739721595662865
- worst split directional return: -0.003882197085900328

This means there are two different problems:

1. Pruned ETH family improves expectancy but becomes sample-thin.
2. Unpruned ETH family has support but still has one unstable worst-loss split.

## Decision

Do not promote any transition setup candidate yet.

Phase 7S confirms that the current transition setup family is useful for research but not suitable for policy/routing. The best path is not more aggressive pruning; that makes the sample too thin. The next phase should identify whether the unstable split is a separate micro-regime that should be tagged, excluded from evaluation, or modeled as a different transition type.

## Next direction

Move to Phase 7T: transition micro-regime tagging.

Focus:

- compare split 3 against passing ETH splits
- derive a diagnostic tag for the failure pocket using only historical/context features
- avoid pruning by timestamp or split index
- test whether the tag explains BNB/BTC failures too
- keep candidate runtime-disabled until cross-asset/multi-window support improves
