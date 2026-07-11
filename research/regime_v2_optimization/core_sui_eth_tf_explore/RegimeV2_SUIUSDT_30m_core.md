# RegimeV2 Optimization: SUIUSDT 30m

## Run
- Profile: `core`
- Trials: `50/50` completed, `0` rejected
- Study: `RegimeV2_SUIUSDT_30m_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_sui_eth_tf_explore/studies.db`
- Data rows: `8640`
- Data range: `2026-01-07T11:30:00+00:00` to `2026-07-06T11:00:00+00:00`

## Best Trial
- Trial: `#9`
- Validation objective: `0.18043092`
- Validation score: `0.18043092`
- Validation positive windows: `0.85714300`
- Validation support rate: `0.56458300`
- Validation flip rate: `0.09931400`

## OOS Gate
- Deployed: `True`
- Rejection reasons: `[]`
- OOS score: `0.20672512`
- OOS mean downstream lift: `0.00934551`
- OOS positive windows: `0.85714300`
- OOS support rate: `0.63422600`
- OOS flip rate: `0.08171800`

## Default Vs Tuned
- Baseline deployed: `True`
- Tuned deployed: `True`
- OOS score delta: `0.16058874`
- Mean downstream lift delta: `0.01250386`
- Positive window rate delta: `0.57142900`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 180,
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
    "trend.fast_ema": 36,
    "trend.slow_ema": 120
  }
}
```
