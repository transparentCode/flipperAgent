# RegimeV2 Optimization: ETHUSDT 1h

## Run
- Profile: `core`
- Trials: `25/25` completed, `0` rejected
- Study: `RegimeV2_ETHUSDT_1h_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_sui_eth_2021_2024/studies.db`
- Data rows: `35041`
- Data range: `2021-01-01T00:00:00+00:00` to `2024-12-31T00:00:00+00:00`

## Best Trial
- Trial: `#23`
- Validation objective: `0.16074773`
- Validation score: `0.16074773`
- Validation positive windows: `0.79310300`
- Validation support rate: `0.44274400`
- Validation flip rate: `0.12986800`

## OOS Gate
- Deployed: `True`
- Rejection reasons: `[]`
- OOS score: `0.11610977`
- OOS mean downstream lift: `0.00133859`
- OOS positive windows: `0.65517200`
- OOS support rate: `0.45538800`
- OOS flip rate: `0.14657000`

## Default Vs Tuned
- Baseline deployed: `False`
- Tuned deployed: `True`
- OOS score delta: `0.13093790`
- Mean downstream lift delta: `0.00520722`
- Positive window rate delta: `0.51724100`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 110,
    "fusion.break_threshold": 0.76,
    "fusion.mr_threshold": 0.53,
    "fusion.shock_threshold": 0.73,
    "fusion.trend_threshold": 0.7,
    "policy.breakout_min_quality": 0.61,
    "policy.high_uncertainty_no_trade": 0.73,
    "policy.min_confidence": 0.39,
    "policy.mr_min_score": 0.7,
    "policy.threshold_width": 0.22000000000000003,
    "policy.trend_max_chop": 0.76,
    "policy.trend_min_strength": 0.25,
    "trend.direction_deadzone": 0.11,
    "trend.fast_ema": 16,
    "trend.slow_ema": 90
  }
}
```
