# RegimeV2 Optimization: ETHUSDT 1d

## Run
- Profile: `core`
- Trials: `25/25` completed, `7` rejected
- Study: `RegimeV2_ETHUSDT_1d_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_sui_eth_2021_2024/studies.db`
- Data rows: `1461`
- Data range: `2021-01-01T00:00:00+00:00` to `2024-12-31T00:00:00+00:00`

## Best Trial
- Trial: `#6`
- Validation objective: `0.14927823`
- Validation score: `0.14927823`
- Validation positive windows: `1.00000000`
- Validation support rate: `0.66111100`
- Validation flip rate: `0.27001800`

## OOS Gate
- Deployed: `False`
- Rejection reasons: `['oos_degradation']`
- OOS score: `-0.15923324`
- OOS mean downstream lift: `-0.01384584`
- OOS positive windows: `0.00000000`
- OOS support rate: `0.64259200`
- OOS flip rate: `0.30726300`

## Default Vs Tuned
- Baseline deployed: `False`
- Tuned deployed: `False`
- OOS score delta: `0.01248683`
- Mean downstream lift delta: `-0.01384584`
- Positive window rate delta: `0.00000000`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 10,
    "fusion.break_threshold": 0.78,
    "fusion.mr_threshold": 0.6699999999999999,
    "fusion.shock_threshold": 0.8400000000000001,
    "fusion.trend_threshold": 0.6699999999999999,
    "policy.breakout_min_quality": 0.63,
    "policy.high_uncertainty_no_trade": 0.72,
    "policy.min_confidence": 0.13,
    "policy.mr_min_score": 0.45,
    "policy.threshold_width": 0.060000000000000005,
    "policy.trend_max_chop": 0.73,
    "policy.trend_min_strength": 0.31,
    "trend.direction_deadzone": 0.05,
    "trend.fast_ema": 5,
    "trend.slow_ema": 10
  }
}
```
