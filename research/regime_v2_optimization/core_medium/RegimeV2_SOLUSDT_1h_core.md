# RegimeV2 Optimization: SOLUSDT 1h

## Run
- Profile: `core`
- Trials: `25/25` completed, `0` rejected
- Study: `RegimeV2_SOLUSDT_1h_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_medium/studies.db`
- Data rows: `5760`
- Data range: `2025-11-08T11:00:00+00:00` to `2026-07-06T10:00:00+00:00`

## Best Trial
- Trial: `#23`
- Validation objective: `0.13802293`
- Validation score: `0.13802293`
- Validation positive windows: `0.66666700`
- Validation support rate: `0.58611100`
- Validation flip rate: `0.08740100`

## OOS Gate
- Deployed: `False`
- Rejection reasons: `['oos_degradation']`
- OOS score: `0.05014675`
- OOS mean downstream lift: `-0.00196412`
- OOS positive windows: `0.33333300`
- OOS support rate: `0.59166700`
- OOS flip rate: `0.09855900`

## Default Vs Tuned
- Baseline deployed: `False`
- Tuned deployed: `False`
- OOS score delta: `0.07118866`
- Mean downstream lift delta: `0.00351757`
- Positive window rate delta: `0.22222200`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 95,
    "fusion.break_threshold": 0.47000000000000003,
    "fusion.mr_threshold": 0.61,
    "fusion.shock_threshold": 0.95,
    "fusion.trend_threshold": 0.72,
    "policy.breakout_min_quality": 0.61,
    "policy.high_uncertainty_no_trade": 0.65,
    "policy.min_confidence": 0.16,
    "policy.mr_min_score": 0.25,
    "policy.threshold_width": 0.1,
    "policy.trend_max_chop": 0.54,
    "policy.trend_min_strength": 0.25,
    "trend.direction_deadzone": 0.27,
    "trend.fast_ema": 16,
    "trend.slow_ema": 75
  }
}
```
