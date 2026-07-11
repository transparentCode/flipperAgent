# RegimeV2 Optimization: ETHUSDT 1h

## Run
- Profile: `core`
- Trials: `25/25` completed, `0` rejected
- Study: `RegimeV2_ETHUSDT_1h_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_medium/studies.db`
- Data rows: `5760`
- Data range: `2025-11-08T11:00:00+00:00` to `2026-07-06T10:00:00+00:00`

## Best Trial
- Trial: `#20`
- Validation objective: `0.18704796`
- Validation score: `0.18704796`
- Validation positive windows: `0.88888900`
- Validation support rate: `0.60787000`
- Validation flip rate: `0.10413800`

## OOS Gate
- Deployed: `False`
- Rejection reasons: `['oos_degradation']`
- OOS score: `0.04898824`
- OOS mean downstream lift: `-0.00038374`
- OOS positive windows: `0.33333300`
- OOS support rate: `0.63287000`
- OOS flip rate: `0.09530500`

## Default Vs Tuned
- Baseline deployed: `True`
- Tuned deployed: `False`
- OOS score delta: `0.06171563`
- Mean downstream lift delta: `0.00329861`
- Positive window rate delta: `0.22222200`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 90,
    "fusion.break_threshold": 0.63,
    "fusion.mr_threshold": 0.78,
    "fusion.shock_threshold": 0.8200000000000001,
    "fusion.trend_threshold": 0.71,
    "policy.breakout_min_quality": 0.85,
    "policy.high_uncertainty_no_trade": 0.6799999999999999,
    "policy.min_confidence": 0.26,
    "policy.mr_min_score": 0.6799999999999999,
    "policy.threshold_width": 0.22999999999999998,
    "policy.trend_max_chop": 0.62,
    "policy.trend_min_strength": 0.25,
    "trend.direction_deadzone": 0.19,
    "trend.fast_ema": 12,
    "trend.slow_ema": 90
  }
}
```
