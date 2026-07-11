# RegimeV2 Optimization: ETHUSDT 1h

## Run
- Profile: `core`
- Trials: `50/50` completed, `0` rejected
- Study: `RegimeV2_ETHUSDT_1h_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_sui_eth_tf_explore/studies.db`
- Data rows: `5760`
- Data range: `2025-11-08T12:00:00+00:00` to `2026-07-06T11:00:00+00:00`

## Best Trial
- Trial: `#31`
- Validation objective: `0.18779004`
- Validation score: `0.18779004`
- Validation positive windows: `0.88888900`
- Validation support rate: `0.51759300`
- Validation flip rate: `0.11157600`

## OOS Gate
- Deployed: `False`
- Rejection reasons: `['oos_degradation']`
- OOS score: `0.07509146`
- OOS mean downstream lift: `-0.00081458`
- OOS positive windows: `0.44444400`
- OOS support rate: `0.56157400`
- OOS flip rate: `0.10460200`

## Default Vs Tuned
- Baseline deployed: `True`
- Tuned deployed: `False`
- OOS score delta: `0.08790043`
- Mean downstream lift delta: `0.00285754`
- Positive window rate delta: `0.33333300`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 70,
    "fusion.break_threshold": 0.65,
    "fusion.mr_threshold": 0.63,
    "fusion.shock_threshold": 0.79,
    "fusion.trend_threshold": 0.6599999999999999,
    "policy.breakout_min_quality": 0.76,
    "policy.high_uncertainty_no_trade": 0.86,
    "policy.min_confidence": 0.31,
    "policy.mr_min_score": 0.69,
    "policy.threshold_width": 0.27,
    "policy.trend_max_chop": 0.6699999999999999,
    "policy.trend_min_strength": 0.25,
    "trend.direction_deadzone": 0.24,
    "trend.fast_ema": 22,
    "trend.slow_ema": 80
  }
}
```
