# RegimeV2 Optimization: SUIUSDT 1h

## Run
- Profile: `core`
- Trials: `50/50` completed, `0` rejected
- Study: `RegimeV2_SUIUSDT_1h_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_sui_eth_tf_explore/studies.db`
- Data rows: `5760`
- Data range: `2025-11-08T12:00:00+00:00` to `2026-07-06T11:00:00+00:00`

## Best Trial
- Trial: `#33`
- Validation objective: `0.18435056`
- Validation score: `0.18435056`
- Validation positive windows: `0.88888900`
- Validation support rate: `0.61064800`
- Validation flip rate: `0.12133900`

## OOS Gate
- Deployed: `False`
- Rejection reasons: `['oos_degradation']`
- OOS score: `0.01920930`
- OOS mean downstream lift: `-0.00211789`
- OOS positive windows: `0.22222200`
- OOS support rate: `0.55601800`
- OOS flip rate: `0.10088300`

## Default Vs Tuned
- Baseline deployed: `True`
- Tuned deployed: `False`
- OOS score delta: `-0.00088584`
- Mean downstream lift delta: `0.00024424`
- Positive window rate delta: `0.00000000`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 90,
    "fusion.break_threshold": 0.71,
    "fusion.mr_threshold": 0.73,
    "fusion.shock_threshold": 0.73,
    "fusion.trend_threshold": 0.75,
    "policy.breakout_min_quality": 0.56,
    "policy.high_uncertainty_no_trade": 0.65,
    "policy.min_confidence": 0.21000000000000002,
    "policy.mr_min_score": 0.63,
    "policy.threshold_width": 0.32,
    "policy.trend_max_chop": 0.62,
    "policy.trend_min_strength": 0.33999999999999997,
    "trend.direction_deadzone": 0.2,
    "trend.fast_ema": 12,
    "trend.slow_ema": 75
  }
}
```
