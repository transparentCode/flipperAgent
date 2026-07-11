# RegimeV2 Optimization: SUIUSDT 4h

## Run
- Profile: `core`
- Trials: `50/50` completed, `2` rejected
- Study: `RegimeV2_SUIUSDT_4h_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_sui_eth_tf_explore/studies.db`
- Data rows: `1440`
- Data range: `2025-11-08T12:00:00+00:00` to `2026-07-06T08:00:00+00:00`

## Best Trial
- Trial: `#33`
- Validation objective: `0.17782801`
- Validation score: `0.17782801`
- Validation positive windows: `1.00000000`
- Validation support rate: `0.56875000`
- Validation flip rate: `0.23012600`

## OOS Gate
- Deployed: `False`
- Rejection reasons: `['oos_degradation']`
- OOS score: `-0.12722792`
- OOS mean downstream lift: `-0.01326252`
- OOS positive windows: `0.00000000`
- OOS support rate: `0.55833400`
- OOS flip rate: `0.24058600`

## Default Vs Tuned
- Baseline deployed: `True`
- Tuned deployed: `False`
- OOS score delta: `0.01143145`
- Mean downstream lift delta: `-0.00101166`
- Positive window rate delta: `0.00000000`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 11,
    "fusion.break_threshold": 0.75,
    "fusion.mr_threshold": 0.72,
    "fusion.shock_threshold": 0.87,
    "fusion.trend_threshold": 0.71,
    "policy.breakout_min_quality": 0.69,
    "policy.high_uncertainty_no_trade": 0.73,
    "policy.min_confidence": 0.28,
    "policy.mr_min_score": 0.6799999999999999,
    "policy.threshold_width": 0.22000000000000003,
    "policy.trend_max_chop": 0.42000000000000004,
    "policy.trend_min_strength": 0.35,
    "trend.direction_deadzone": 0.11,
    "trend.fast_ema": 6,
    "trend.slow_ema": 12
  }
}
```
