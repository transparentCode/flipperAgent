# RegimeV2 Optimization: SUIUSDT 1d

## Run
- Profile: `core`
- Trials: `50/50` completed, `14` rejected
- Study: `RegimeV2_SUIUSDT_1d_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_sui_eth_tf_explore/studies.db`
- Data rows: `900`
- Data range: `2024-01-19T00:00:00+00:00` to `2026-07-06T00:00:00+00:00`

## Best Trial
- Trial: `#43`
- Validation objective: `0.09666684`
- Validation score: `0.09666684`
- Validation positive windows: `1.00000000`
- Validation support rate: `0.74166700`
- Validation flip rate: `0.23949600`

## OOS Gate
- Deployed: `True`
- Rejection reasons: `[]`
- OOS score: `0.14358690`
- OOS mean downstream lift: `0.02008043`
- OOS positive windows: `1.00000000`
- OOS support rate: `0.78750000`
- OOS flip rate: `0.28571400`

## Default Vs Tuned
- Baseline deployed: `False`
- Tuned deployed: `True`
- OOS score delta: `0.29721819`
- Mean downstream lift delta: `0.02008043`
- Positive window rate delta: `1.00000000`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 10,
    "fusion.break_threshold": 0.9,
    "fusion.mr_threshold": 0.59,
    "fusion.shock_threshold": 0.89,
    "fusion.trend_threshold": 0.62,
    "policy.breakout_min_quality": 0.8200000000000001,
    "policy.high_uncertainty_no_trade": 0.9099999999999999,
    "policy.min_confidence": 0.13,
    "policy.mr_min_score": 0.7,
    "policy.threshold_width": 0.060000000000000005,
    "policy.trend_max_chop": 0.38,
    "policy.trend_min_strength": 0.28,
    "trend.direction_deadzone": 0.05,
    "trend.fast_ema": 5,
    "trend.slow_ema": 10
  }
}
```
