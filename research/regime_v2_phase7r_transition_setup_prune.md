# RegimeV2 Phase 7R Setup-Transition Pruning Discovery

## Scope

- Assets/timeframes: ETHUSDT|1h, BNBUSDT|1h, BTCUSDT|1h
- Input rows per asset: 720
- Base family: Phase 7P setup-origin transition candidates
- Focused candidate config: lookback 8, min_candidate_score 0.62
- Pruning dimensions:
  - score gap: 0.0, 0.15, 0.25
  - max continuation score: none, 0.70, 0.80
  - max volatility quantile: 1.0, 0.85, 0.70
  - market phase: all, breakout_setup, compressed_wait
- Runtime posture: offline-only / diagnostic-only

## Summary

- Variants: 243
- Ready variants: 0
- Recommendation: hold_off_pruned_setup_transition_unstable
- Best variant: ETHUSDT|1h
- Best config:
  - lookback_bars: 8
  - min_candidate_score: 0.62
  - allowed_market_phases: breakout_setup
  - max_volatility_quantile: 0.85
  - min_score_gap: 0.0
  - max_continuation_score: none
- Active before/after pruning: 61 -> 15
- Splits passed: 3/4
- Avg split directional return: 0.007382640965507925
- Worst split directional return: -0.0019351374847817401

## Best variant split profile

| Split | Active | Passed | Passing cell rate | Avg directional | Worst directional | Direction mix | Failure reasons |
|---:|---:|---|---:|---:|---:|---|---|
| 1 | 4 | true | 1.0 | 0.009916265183506448 | 0.0060822193949102155 | down 1 / up 3 | none |
| 2 | 6 | true | 1.0 | 0.006447194839611815 | 0.00017713425723327568 | down 5 / up 1 | none |
| 3 | 2 | false | 0.5 | 0.0006982871287740991 | -0.0019351374847817401 | down 1 / up 1 | low_passing_rate, worst_cell_too_negative |
| 4 | 3 | true | 0.9166666666666666 | 0.012468816710139335 | 0.00005088046150295358 | up 3 | none |

## Interpretation

7R improves the best 7P family materially but does not make it candidate-ready.

Compared with 7P best ETH variant:

| Metric | 7P best | 7R best |
|---|---:|---:|
| Active candidates | 61 | 15 |
| Passed splits | 3/4 | 3/4 |
| Avg split directional return | 0.0039739721595662865 | 0.007382640965507925 |
| Worst split directional return | -0.003882197085900328 | -0.0019351374847817401 |

The pruning signal is useful: keeping only `breakout_setup` candidates and dropping the top volatility tail improves average return and reduces downside. But it also reduces support sharply. Split 3 has only two active candidates after pruning, so the remaining failure is partly a support problem and partly a residual worst-cell problem.

## Decision

Do not promote 7R. Keep the pruning result as a strong diagnostic candidate, not a policy rule.

## Next direction

Move to Phase 7S: support-aware transition candidate validation.

Focus:

- add a minimum active-per-split support gate to avoid false readiness from tiny samples
- test whether the ETH best family remains useful under relaxed support-aware scoring rather than binary 4/4 pass/fail
- compare the pruned ETH family against BNB/BTC sanity windows
- identify whether split 3 needs more data, a separate micro-regime tag, or should block promotion entirely
