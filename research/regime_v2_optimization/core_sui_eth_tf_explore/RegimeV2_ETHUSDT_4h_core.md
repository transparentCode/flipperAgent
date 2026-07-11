# RegimeV2 Optimization: ETHUSDT 4h

## Run
- Profile: `core`
- Trials: `50/50` completed, `3` rejected
- Study: `RegimeV2_ETHUSDT_4h_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_sui_eth_tf_explore/studies.db`
- Data rows: `1440`
- Data range: `2025-11-08T12:00:00+00:00` to `2026-07-06T08:00:00+00:00`

## Best Trial
- Trial: `#25`
- Validation objective: `0.18346849`
- Validation score: `0.18346849`
- Validation positive windows: `1.00000000`
- Validation support rate: `0.62500000`
- Validation flip rate: `0.26150600`

## OOS Gate
- Deployed: `False`
- Rejection reasons: `['oos_degradation']`
- OOS score: `-0.09658153`
- OOS mean downstream lift: `-0.00462899`
- OOS positive windows: `0.00000000`
- OOS support rate: `0.59375000`
- OOS flip rate: `0.23221800`

## Default Vs Tuned
- Baseline deployed: `True`
- Tuned deployed: `False`
- OOS score delta: `0.03781403`
- Mean downstream lift delta: `0.00790842`
- Positive window rate delta: `0.00000000`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 25,
    "fusion.break_threshold": 0.68,
    "fusion.mr_threshold": 0.6799999999999999,
    "fusion.shock_threshold": 0.79,
    "fusion.trend_threshold": 0.5700000000000001,
    "policy.breakout_min_quality": 0.6000000000000001,
    "policy.high_uncertainty_no_trade": 0.62,
    "policy.min_confidence": 0.1,
    "policy.mr_min_score": 0.33,
    "policy.threshold_width": 0.28,
    "policy.trend_max_chop": 0.6799999999999999,
    "policy.trend_min_strength": 0.29,
    "trend.direction_deadzone": 0.28,
    "trend.fast_ema": 7,
    "trend.slow_ema": 21
  }
}
```
