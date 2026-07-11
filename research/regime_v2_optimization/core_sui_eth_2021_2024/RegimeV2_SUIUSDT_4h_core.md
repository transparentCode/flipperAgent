# RegimeV2 Optimization: SUIUSDT 4h

## Run
- Profile: `core`
- Trials: `25/25` completed, `1` rejected
- Study: `RegimeV2_SUIUSDT_4h_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_sui_eth_2021_2024/studies.db`
- Data rows: `3645`
- Data range: `2023-05-03T16:00:00+00:00` to `2024-12-31T00:00:00+00:00`

## Best Trial
- Trial: `#2`
- Validation objective: `0.14926554`
- Validation score: `0.14926554`
- Validation positive windows: `1.00000000`
- Validation support rate: `0.44083300`
- Validation flip rate: `0.30209200`

## OOS Gate
- Deployed: `False`
- Rejection reasons: `['oos_degradation']`
- OOS score: `0.03940306`
- OOS mean downstream lift: `0.01040365`
- OOS positive windows: `0.60000000`
- OOS support rate: `0.42500000`
- OOS flip rate: `0.31297100`

## Default Vs Tuned
- Baseline deployed: `False`
- Tuned deployed: `False`
- OOS score delta: `0.05501867`
- Mean downstream lift delta: `0.00752540`
- Positive window rate delta: `0.20000000`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 11,
    "fusion.break_threshold": 0.5900000000000001,
    "fusion.mr_threshold": 0.72,
    "fusion.shock_threshold": 0.49,
    "fusion.trend_threshold": 0.74,
    "policy.breakout_min_quality": 0.27,
    "policy.high_uncertainty_no_trade": 0.75,
    "policy.min_confidence": 0.44000000000000006,
    "policy.mr_min_score": 0.8,
    "policy.threshold_width": 0.13,
    "policy.trend_max_chop": 0.52,
    "policy.trend_min_strength": 0.31,
    "trend.direction_deadzone": 0.33999999999999997,
    "trend.fast_ema": 8,
    "trend.slow_ema": 12
  }
}
```
