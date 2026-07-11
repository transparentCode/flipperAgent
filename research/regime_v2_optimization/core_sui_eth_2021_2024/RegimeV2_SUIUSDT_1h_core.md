# RegimeV2 Optimization: SUIUSDT 1h

## Run
- Profile: `core`
- Trials: `25/25` completed, `0` rejected
- Study: `RegimeV2_SUIUSDT_1h_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_sui_eth_2021_2024/studies.db`
- Data rows: `14577`
- Data range: `2023-05-03T16:00:00+00:00` to `2024-12-31T00:00:00+00:00`

## Best Trial
- Trial: `#11`
- Validation objective: `0.11691007`
- Validation score: `0.11691007`
- Validation positive windows: `0.66666700`
- Validation support rate: `0.64062500`
- Validation flip rate: `0.17066800`

## OOS Gate
- Deployed: `False`
- Rejection reasons: `['oos_degradation']`
- OOS score: `0.04917211`
- OOS mean downstream lift: `0.00266694`
- OOS positive windows: `0.41666700`
- OOS support rate: `0.60121500`
- OOS flip rate: `0.16040400`

## Default Vs Tuned
- Baseline deployed: `True`
- Tuned deployed: `False`
- OOS score delta: `-0.01924586`
- Mean downstream lift delta: `-0.00056537`
- Positive window rate delta: `-0.08333300`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 50,
    "fusion.break_threshold": 0.9,
    "fusion.mr_threshold": 0.38999999999999996,
    "fusion.shock_threshold": 0.81,
    "fusion.trend_threshold": 0.53,
    "policy.breakout_min_quality": 0.85,
    "policy.high_uncertainty_no_trade": 0.9099999999999999,
    "policy.min_confidence": 0.23,
    "policy.mr_min_score": 0.43,
    "policy.threshold_width": 0.35,
    "policy.trend_max_chop": 0.45999999999999996,
    "policy.trend_min_strength": 0.53,
    "trend.direction_deadzone": 0.05,
    "trend.fast_ema": 40,
    "trend.slow_ema": 80
  }
}
```
