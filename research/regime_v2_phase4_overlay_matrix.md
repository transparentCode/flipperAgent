# RegimeV2 Phase 4 Overlay Validation Matrix

Decision: **HOLD_FOR_MORE_EVIDENCE**

## Summary

- Total combos: 16
- Passed combos: 8
- Pass rate: 0.5
- Failure reasons: combo_pass_rate_below_0.6, fee_0.0_mean_lift_below_0.0, fee_0.0_positive_rate_below_0.55, fee_0.0_valid_windows_below_2, fee_2.0_mean_lift_below_0.0, fee_2.0_positive_rate_below_0.55, fee_2.0_valid_windows_below_2, fee_5.0_mean_lift_below_0.0, fee_5.0_positive_rate_below_0.55, fee_5.0_valid_windows_below_2
- Top diagnostic reason: low_trend_score (19781)

## Combo Results

| Asset | TF | Horizon | Passed | Mean lift by fee | Positive rate by fee |
|---|---:|---:|---:|---|---|
| BTCUSDT | 1h | 6 | False | 0.0: None, 2.0: None, 5.0: None | 0.0: None, 2.0: None, 5.0: None |
| BTCUSDT | 1h | 12 | False | 0.0: None, 2.0: None, 5.0: None | 0.0: None, 2.0: None, 5.0: None |
| BTCUSDT | 4h | 6 | True | 0.0: 0.00879789, 2.0: 0.00879789, 5.0: 0.00879789 | 0.0: 1.0, 2.0: 1.0, 5.0: 1.0 |
| BTCUSDT | 4h | 12 | True | 0.0: 0.01099622, 2.0: 0.01099622, 5.0: 0.01099622 | 0.0: 0.8, 2.0: 0.8, 5.0: 0.8 |
| ETHUSDT | 1h | 6 | False | 0.0: None, 2.0: None, 5.0: None | 0.0: None, 2.0: None, 5.0: None |
| ETHUSDT | 1h | 12 | False | 0.0: None, 2.0: None, 5.0: None | 0.0: None, 2.0: None, 5.0: None |
| ETHUSDT | 4h | 6 | False | 0.0: -0.00288678, 2.0: -0.00288678, 5.0: -0.00288678 | 0.0: 0.5, 2.0: 0.5, 5.0: 0.5 |
| ETHUSDT | 4h | 12 | False | 0.0: -0.00280829, 2.0: -0.00280829, 5.0: -0.00280829 | 0.0: 0.5, 2.0: 0.5, 5.0: 0.5 |
| SOLUSDT | 1h | 6 | False | 0.0: -0.01088227, 2.0: -0.01088227, 5.0: -0.01088227 | 0.0: 0.0, 2.0: 0.0, 5.0: 0.0 |
| SOLUSDT | 1h | 12 | False | 0.0: -0.01759153, 2.0: -0.01759153, 5.0: -0.01759153 | 0.0: 0.0, 2.0: 0.0, 5.0: 0.0 |
| SOLUSDT | 4h | 6 | True | 0.0: 0.00842432, 2.0: 0.00842432, 5.0: 0.00842432 | 0.0: 0.8, 2.0: 0.8, 5.0: 0.8 |
| SOLUSDT | 4h | 12 | True | 0.0: 0.00952425, 2.0: 0.00952425, 5.0: 0.00952425 | 0.0: 0.8, 2.0: 0.8, 5.0: 0.8 |
| BNBUSDT | 1h | 6 | True | 0.0: 0.01508811, 2.0: 0.01508811, 5.0: 0.01508811 | 0.0: 1.0, 2.0: 1.0, 5.0: 1.0 |
| BNBUSDT | 1h | 12 | True | 0.0: 0.01657389, 2.0: 0.01657389, 5.0: 0.01657389 | 0.0: 1.0, 2.0: 1.0, 5.0: 1.0 |
| BNBUSDT | 4h | 6 | True | 0.0: 0.00360376, 2.0: 0.00360376, 5.0: 0.00360376 | 0.0: 0.66666667, 2.0: 0.66666667, 5.0: 0.66666667 |
| BNBUSDT | 4h | 12 | True | 0.0: 0.00275563, 2.0: 0.00275563, 5.0: 0.00275563 | 0.0: 0.6, 2.0: 0.6, 5.0: 0.6 |
