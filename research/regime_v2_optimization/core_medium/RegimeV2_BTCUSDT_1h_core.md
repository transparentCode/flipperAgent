# RegimeV2 Optimization: BTCUSDT 1h

## Run
- Profile: `core`
- Trials: `25/25` completed, `0` rejected
- Study: `RegimeV2_BTCUSDT_1h_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_medium/studies.db`
- Data rows: `5760`
- Data range: `2025-11-08T11:00:00+00:00` to `2026-07-06T10:00:00+00:00`

## Best Trial
- Trial: `#9`
- Validation objective: `0.13180370`
- Validation score: `0.13180370`
- Validation positive windows: `0.66666700`
- Validation support rate: `0.55648100`
- Validation flip rate: `0.11622500`

## OOS Gate
- Deployed: `False`
- Rejection reasons: `['oos_degradation']`
- OOS score: `-0.00640910`
- OOS mean downstream lift: `-0.00214801`
- OOS positive windows: `0.11111100`
- OOS support rate: `0.60000000`
- OOS flip rate: `0.11762000`

## Default Vs Tuned
- Baseline deployed: `True`
- Tuned deployed: `False`
- OOS score delta: `0.00899901`
- Mean downstream lift delta: `0.00239562`
- Positive window rate delta: `0.00000000`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 90,
    "fusion.break_threshold": 0.56,
    "fusion.mr_threshold": 0.79,
    "fusion.shock_threshold": 0.7,
    "fusion.trend_threshold": 0.74,
    "policy.breakout_min_quality": 0.55,
    "policy.high_uncertainty_no_trade": 0.7,
    "policy.min_confidence": 0.25,
    "policy.mr_min_score": 0.28,
    "policy.threshold_width": 0.13,
    "policy.trend_max_chop": 0.5900000000000001,
    "policy.trend_min_strength": 0.27,
    "trend.direction_deadzone": 0.16,
    "trend.fast_ema": 18,
    "trend.slow_ema": 60
  }
}
```
