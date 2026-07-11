# RegimeV2 Optimization: ETHUSDT 30m

## Run
- Profile: `core`
- Trials: `50/50` completed, `0` rejected
- Study: `RegimeV2_ETHUSDT_30m_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_sui_eth_tf_explore/studies.db`
- Data rows: `8640`
- Data range: `2026-01-07T11:30:00+00:00` to `2026-07-06T11:00:00+00:00`

## Best Trial
- Trial: `#47`
- Validation objective: `0.22550551`
- Validation score: `0.22550551`
- Validation positive windows: `1.00000000`
- Validation support rate: `0.56994100`
- Validation flip rate: `0.09543700`

## OOS Gate
- Deployed: `True`
- Rejection reasons: `[]`
- OOS score: `0.12073996`
- OOS mean downstream lift: `0.00010838`
- OOS positive windows: `0.57142900`
- OOS support rate: `0.61488100`
- OOS flip rate: `0.08201600`

## Default Vs Tuned
- Baseline deployed: `False`
- Tuned deployed: `True`
- OOS score delta: `0.14917022`
- Mean downstream lift delta: `0.00477412`
- Positive window rate delta: `0.57142900`

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 50,
    "fusion.break_threshold": 0.63,
    "fusion.mr_threshold": 0.78,
    "fusion.shock_threshold": 0.8,
    "fusion.trend_threshold": 0.61,
    "policy.breakout_min_quality": 0.66,
    "policy.high_uncertainty_no_trade": 0.72,
    "policy.min_confidence": 0.27,
    "policy.mr_min_score": 0.7,
    "policy.threshold_width": 0.25,
    "policy.trend_max_chop": 0.77,
    "policy.trend_min_strength": 0.3,
    "trend.direction_deadzone": 0.32,
    "trend.fast_ema": 60,
    "trend.slow_ema": 200
  }
}
```
