# RegimeV2 Phase 7J Follow-Through Invalidation Matrix

## Scope

- Asset/timeframe: BNBUSDT|1h
- Input rows: 720
- Thresholds tested: 0.25, 0.30
- Filter: deterministic invalidation plus direction-local cooldown before Phase 7H walk-forward retest

## Default filter config

- min_hold_score: 0.50
- min_follow_score: 0.50
- min_direction_return_score: 0.40
- max_reversal_penalty: 0.35
- cooldown_bars: 3
- cooldown_by_direction: true
- blocked_directions: none

## Summary

- Recommendation: hold_off_invalidation_unstable
- Ready variants: 0/2
- Best ready variant: none
- Best variant threshold: 0.25
- Active before/after: 11/4
- Removed rows: 7
- Invalidated rows: 6
- Cooldown-suppressed rows: 1
- Avg split directional return: 0.0005794698553162486
- Worst split directional return: -0.019005679090219316
- Splits passed: 0/4

## Variant matrix

| Threshold | Active before | Active after | Removed | Passed | Avg split dir | Worst split dir | Ready |
|---:|---:|---:|---:|---:|---:|---:|---|
| 0.25 | 11 | 4 | 7 | 0/4 | 0.0005794698553162486 | -0.019005679090219316 | False |
| 0.30 | 11 | 4 | 7 | 0/4 | 0.0005794698553162486 | -0.019005679090219316 | False |

## Interpretation

Phase 7J successfully removes the obvious high-reversal-pressure leakage found in Phase 7I, but it does not produce a promotion-ready follow-through candidate. The filter is too destructive for early windows: splits 1 and 2 have zero remaining active rows, causing low-support/no-direction failures. The remaining split 3/4 rows still show low passing rate and worst-cell loss failures.

This confirms the current breakout follow-through path is useful diagnostically but should not be promoted. The next redesign step should change candidate generation/context, not just add stricter post-confirmation filtering.
