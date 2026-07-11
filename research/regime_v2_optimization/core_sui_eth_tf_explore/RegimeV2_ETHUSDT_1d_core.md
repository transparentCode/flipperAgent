# RegimeV2 Optimization: ETHUSDT 1d

## Run
- Profile: `core`
- Trials: `50/50` completed, `6` rejected
- Study: `RegimeV2_ETHUSDT_1d_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_sui_eth_tf_explore/studies.db`
- Data rows: `900`
- Data range: `2024-01-19T00:00:00+00:00` to `2026-07-06T00:00:00+00:00`

## Best Trial
- Trial: `#44`
- Validation objective: `0.14806780`
- Validation score: `0.14806780`
- Validation positive windows: `1.00000000`
- Validation support rate: `0.67083300`
- Validation flip rate: `0.23949600`

## OOS Gate
- Deployed: `False`
- Rejection reasons: `['oos_degradation']`
- OOS score: `-0.10038101`
- OOS mean downstream lift: `-0.00106018`
- OOS positive windows: `0.00000000`
- OOS support rate: `0.70833300`
- OOS flip rate: `0.23949600`

## Default Vs Tuned
- Baseline deployed: `True`
- Tuned deployed: `False`
- OOS score delta: `0.02612916`
- Mean downstream lift delta: `-0.00106018`
- Positive window rate delta: `0.00000000`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 10,
    "fusion.break_threshold": 0.87,
    "fusion.mr_threshold": 0.74,
    "fusion.shock_threshold": 0.81,
    "fusion.trend_threshold": 0.6799999999999999,
    "policy.breakout_min_quality": 0.69,
    "policy.high_uncertainty_no_trade": 0.8,
    "policy.min_confidence": 0.21000000000000002,
    "policy.mr_min_score": 0.52,
    "policy.threshold_width": 0.29,
    "policy.trend_max_chop": 0.71,
    "policy.trend_min_strength": 0.28,
    "trend.direction_deadzone": 0.22000000000000003,
    "trend.fast_ema": 5,
    "trend.slow_ema": 10
  }
}
```
