# RegimeV2 Optimization: SUIUSDT 1d

## Run
- Profile: `core`
- Trials: `25/25` completed, `6` rejected
- Study: `RegimeV2_SUIUSDT_1d_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_sui_eth_2021_2024/studies.db`
- Data rows: `609`
- Data range: `2023-05-03T00:00:00+00:00` to `2024-12-31T00:00:00+00:00`

## Best Trial
- Trial: `#11`
- Validation objective: `0.10027657`
- Validation score: `0.10027657`
- Validation positive windows: `1.00000000`
- Validation support rate: `0.63025200`
- Validation flip rate: `0.24576300`

## OOS Gate
- Deployed: `True`
- Rejection reasons: `[]`
- OOS score: `0.14038195`
- OOS mean downstream lift: `0.01924054`
- OOS positive windows: `1.00000000`
- OOS support rate: `0.67241400`
- OOS flip rate: `0.29565200`

## Default Vs Tuned
- Baseline deployed: `False`
- Tuned deployed: `True`
- OOS score delta: `0.27698121`
- Mean downstream lift delta: `0.01924054`
- Positive window rate delta: `1.00000000`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 10,
    "fusion.break_threshold": 0.89,
    "fusion.mr_threshold": 0.57,
    "fusion.shock_threshold": 0.79,
    "fusion.trend_threshold": 0.6,
    "policy.breakout_min_quality": 0.51,
    "policy.high_uncertainty_no_trade": 0.9299999999999999,
    "policy.min_confidence": 0.23,
    "policy.mr_min_score": 0.62,
    "policy.threshold_width": 0.060000000000000005,
    "policy.trend_max_chop": 0.79,
    "policy.trend_min_strength": 0.25,
    "trend.direction_deadzone": 0.05,
    "trend.fast_ema": 5,
    "trend.slow_ema": 10
  }
}
```
