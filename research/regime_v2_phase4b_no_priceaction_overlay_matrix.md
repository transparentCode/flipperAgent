# RegimeV2 Phase 4 Overlay Validation Matrix

Decision: **PROMOTE_TO_SHADOW_CANDIDATE**

## Summary

- Total combos: 16
- Passed combos: 10
- Pass rate: 0.625
- Failure reasons: fee_2.0_mean_lift_below_0.0, fee_2.0_positive_rate_below_0.55, fee_5.0_mean_lift_below_0.0, fee_5.0_positive_rate_below_0.55
- Top diagnostic reason: no_active_playbook (11856)

## Combo Results

| Asset | TF | Horizon | Passed | Mean lift by fee | Positive rate by fee |
|---|---:|---:|---:|---|---|
| BTCUSDT | 1h | 6 | True | 2.0: 0.00016031, 5.0: 0.00016031 | 2.0: 0.66666667, 5.0: 0.66666667 |
| BTCUSDT | 1h | 12 | False | 2.0: -0.00575029, 5.0: -0.00575029 | 2.0: 0.0, 5.0: 0.0 |
| BTCUSDT | 4h | 6 | True | 2.0: 0.00892996, 5.0: 0.00892996 | 2.0: 1.0, 5.0: 1.0 |
| BTCUSDT | 4h | 12 | True | 2.0: 0.01561085, 5.0: 0.01561085 | 2.0: 0.83333333, 5.0: 0.83333333 |
| ETHUSDT | 1h | 6 | False | 2.0: 0.00211087, 5.0: 0.00211087 | 2.0: 0.5, 5.0: 0.5 |
| ETHUSDT | 1h | 12 | False | 2.0: -0.00159952, 5.0: -0.00159952 | 2.0: 0.25, 5.0: 0.25 |
| ETHUSDT | 4h | 6 | True | 2.0: 0.00091454, 5.0: 0.00091454 | 2.0: 0.66666667, 5.0: 0.66666667 |
| ETHUSDT | 4h | 12 | True | 2.0: 0.0051392, 5.0: 0.0051392 | 2.0: 0.66666667, 5.0: 0.66666667 |
| SOLUSDT | 1h | 6 | False | 2.0: -0.00301814, 5.0: -0.00301814 | 2.0: 0.4, 5.0: 0.4 |
| SOLUSDT | 1h | 12 | False | 2.0: -0.0104405, 5.0: -0.0104405 | 2.0: 0.25, 5.0: 0.25 |
| SOLUSDT | 4h | 6 | True | 2.0: 0.00870051, 5.0: 0.00870051 | 2.0: 0.83333333, 5.0: 0.83333333 |
| SOLUSDT | 4h | 12 | True | 2.0: 0.01061734, 5.0: 0.01061734 | 2.0: 0.83333333, 5.0: 0.83333333 |
| BNBUSDT | 1h | 6 | True | 2.0: 0.01251744, 5.0: 0.01251744 | 2.0: 1.0, 5.0: 1.0 |
| BNBUSDT | 1h | 12 | True | 2.0: 0.01366609, 5.0: 0.01366609 | 2.0: 1.0, 5.0: 1.0 |
| BNBUSDT | 4h | 6 | False | 2.0: 0.00379194, 5.0: 0.00379194 | 2.0: 0.5, 5.0: 0.5 |
| BNBUSDT | 4h | 12 | True | 2.0: 0.00266645, 5.0: 0.00266645 | 2.0: 0.66666667, 5.0: 0.66666667 |
