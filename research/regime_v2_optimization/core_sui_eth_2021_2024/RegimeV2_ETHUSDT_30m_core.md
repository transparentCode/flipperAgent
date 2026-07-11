# RegimeV2 Optimization: ETHUSDT 30m

## Run
- Profile: `core`
- Trials: `25/25` completed, `0` rejected
- Study: `RegimeV2_ETHUSDT_30m_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_sui_eth_2021_2024/studies.db`
- Data rows: `70081`
- Data range: `2021-01-01T00:00:00+00:00` to `2024-12-31T00:00:00+00:00`

## Best Trial
- Trial: `#24`
- Validation objective: `0.18250823`
- Validation score: `0.18250823`
- Validation positive windows: `0.82758600`
- Validation support rate: `0.50075400`
- Validation flip rate: `0.09205000`

## OOS Gate
- Deployed: `True`
- Rejection reasons: `[]`
- OOS score: `0.12600121`
- OOS mean downstream lift: `0.00216934`
- OOS positive windows: `0.62069000`
- OOS support rate: `0.50585500`
- OOS flip rate: `0.09269700`

## Default Vs Tuned
- Baseline deployed: `True`
- Tuned deployed: `True`
- OOS score delta: `0.04480755`
- Mean downstream lift delta: `-0.00215029`
- Positive window rate delta: `0.17241400`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 170,
    "fusion.break_threshold": 0.87,
    "fusion.mr_threshold": 0.63,
    "fusion.shock_threshold": 0.95,
    "fusion.trend_threshold": 0.44999999999999996,
    "policy.breakout_min_quality": 0.71,
    "policy.high_uncertainty_no_trade": 0.62,
    "policy.min_confidence": 0.32,
    "policy.mr_min_score": 0.51,
    "policy.threshold_width": 0.22999999999999998,
    "policy.trend_max_chop": 0.6699999999999999,
    "policy.trend_min_strength": 0.3,
    "trend.direction_deadzone": 0.19,
    "trend.fast_ema": 24,
    "trend.slow_ema": 200
  }
}
```
