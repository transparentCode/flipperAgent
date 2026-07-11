# RegimeV2 Optimization: BTCUSDT 4h

## Run
- Profile: `core`
- Trials: `25/25` completed, `2` rejected
- Study: `RegimeV2_BTCUSDT_4h_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_medium/studies.db`
- Data rows: `1440`
- Data range: `2025-11-08T12:00:00+00:00` to `2026-07-06T08:00:00+00:00`

## Best Trial
- Trial: `#9`
- Validation objective: `0.17980492`
- Validation score: `0.17980492`
- Validation positive windows: `1.00000000`
- Validation support rate: `0.69791700`
- Validation flip rate: `0.22803400`

## OOS Gate
- Deployed: `True`
- Rejection reasons: `[]`
- OOS score: `0.15639315`
- OOS mean downstream lift: `0.00552548`
- OOS positive windows: `1.00000000`
- OOS support rate: `0.66041600`
- OOS flip rate: `0.21757400`

## Default Vs Tuned
- Baseline deployed: `True`
- Tuned deployed: `True`
- OOS score delta: `0.27286196`
- Mean downstream lift delta: `0.01373524`
- Positive window rate delta: `1.00000000`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 24,
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
    "trend.fast_ema": 6,
    "trend.slow_ema": 18
  }
}
```
