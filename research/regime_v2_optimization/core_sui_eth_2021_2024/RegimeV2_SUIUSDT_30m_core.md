# RegimeV2 Optimization: SUIUSDT 30m

## Run
- Profile: `core`
- Trials: `25/25` completed, `0` rejected
- Study: `RegimeV2_SUIUSDT_30m_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_sui_eth_2021_2024/studies.db`
- Data rows: `29153`
- Data range: `2023-05-03T16:00:00+00:00` to `2024-12-31T00:00:00+00:00`

## Best Trial
- Trial: `#22`
- Validation objective: `0.16910779`
- Validation score: `0.16910779`
- Validation positive windows: `0.83333300`
- Validation support rate: `0.63654500`
- Validation flip rate: `0.09975700`

## OOS Gate
- Deployed: `True`
- Rejection reasons: `[]`
- OOS score: `0.20107834`
- OOS mean downstream lift: `0.01432886`
- OOS positive windows: `0.91666700`
- OOS support rate: `0.61632000`
- OOS flip rate: `0.10444900`

## Default Vs Tuned
- Baseline deployed: `True`
- Tuned deployed: `True`
- OOS score delta: `0.14299766`
- Mean downstream lift delta: `0.01581941`
- Positive window rate delta: `0.50000000`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 170,
    "fusion.break_threshold": 0.74,
    "fusion.mr_threshold": 0.55,
    "fusion.shock_threshold": 0.75,
    "fusion.trend_threshold": 0.69,
    "policy.breakout_min_quality": 0.5,
    "policy.high_uncertainty_no_trade": 0.78,
    "policy.min_confidence": 0.19,
    "policy.mr_min_score": 0.51,
    "policy.threshold_width": 0.3,
    "policy.trend_max_chop": 0.64,
    "policy.trend_min_strength": 0.36,
    "trend.direction_deadzone": 0.22999999999999998,
    "trend.fast_ema": 56,
    "trend.slow_ema": 150
  }
}
```
