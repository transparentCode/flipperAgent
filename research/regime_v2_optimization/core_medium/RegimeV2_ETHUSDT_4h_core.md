# RegimeV2 Optimization: ETHUSDT 4h

## Run
- Profile: `core`
- Trials: `25/25` completed, `3` rejected
- Study: `RegimeV2_ETHUSDT_4h_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_medium/studies.db`
- Data rows: `1440`
- Data range: `2025-11-08T12:00:00+00:00` to `2026-07-06T08:00:00+00:00`

## Best Trial
- Trial: `#22`
- Validation objective: `0.17983392`
- Validation score: `0.17983392`
- Validation positive windows: `1.00000000`
- Validation support rate: `0.65625000`
- Validation flip rate: `0.25941400`

## OOS Gate
- Deployed: `False`
- Rejection reasons: `['oos_degradation']`
- OOS score: `-0.09997337`
- OOS mean downstream lift: `-0.00260135`
- OOS positive windows: `0.00000000`
- OOS support rate: `0.62291600`
- OOS flip rate: `0.24058600`

## Default Vs Tuned
- Baseline deployed: `True`
- Tuned deployed: `False`
- OOS score delta: `0.03442080`
- Mean downstream lift delta: `0.00993467`
- Positive window rate delta: `0.00000000`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 27,
    "fusion.break_threshold": 0.74,
    "fusion.mr_threshold": 0.6599999999999999,
    "fusion.shock_threshold": 0.74,
    "fusion.trend_threshold": 0.71,
    "policy.breakout_min_quality": 0.44,
    "policy.high_uncertainty_no_trade": 0.64,
    "policy.min_confidence": 0.15000000000000002,
    "policy.mr_min_score": 0.45,
    "policy.threshold_width": 0.22999999999999998,
    "policy.trend_max_chop": 0.69,
    "policy.trend_min_strength": 0.31,
    "trend.direction_deadzone": 0.27,
    "trend.fast_ema": 6,
    "trend.slow_ema": 20
  }
}
```
