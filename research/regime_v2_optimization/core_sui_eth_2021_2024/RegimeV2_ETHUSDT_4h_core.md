# RegimeV2 Optimization: ETHUSDT 4h

## Run
- Profile: `core`
- Trials: `25/25` completed, `0` rejected
- Study: `RegimeV2_ETHUSDT_4h_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_sui_eth_2021_2024/studies.db`
- Data rows: `8761`
- Data range: `2021-01-01T00:00:00+00:00` to `2024-12-31T00:00:00+00:00`

## Best Trial
- Trial: `#16`
- Validation objective: `0.15579205`
- Validation score: `0.15579205`
- Validation positive windows: `0.92857100`
- Validation support rate: `0.57619100`
- Validation flip rate: `0.19665300`

## OOS Gate
- Deployed: `True`
- Rejection reasons: `[]`
- OOS score: `0.11348401`
- OOS mean downstream lift: `0.00641593`
- OOS positive windows: `0.78571400`
- OOS support rate: `0.58660700`
- OOS flip rate: `0.20711300`

## Default Vs Tuned
- Baseline deployed: `True`
- Tuned deployed: `True`
- OOS score delta: `0.07443053`
- Mean downstream lift delta: `0.00196192`
- Positive window rate delta: `0.21428500`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 23,
    "fusion.break_threshold": 0.77,
    "fusion.mr_threshold": 0.75,
    "fusion.shock_threshold": 0.79,
    "fusion.trend_threshold": 0.69,
    "policy.breakout_min_quality": 0.69,
    "policy.high_uncertainty_no_trade": 0.73,
    "policy.min_confidence": 0.30000000000000004,
    "policy.mr_min_score": 0.47,
    "policy.threshold_width": 0.3,
    "policy.trend_max_chop": 0.74,
    "policy.trend_min_strength": 0.33999999999999997,
    "trend.direction_deadzone": 0.12000000000000001,
    "trend.fast_ema": 5,
    "trend.slow_ema": 10
  }
}
```
