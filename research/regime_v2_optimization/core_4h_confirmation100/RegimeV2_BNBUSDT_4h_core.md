# RegimeV2 Optimization: BNBUSDT 4h

## Run
- Profile: `core`
- Trials: `100/100` completed, `2` rejected
- Study: `RegimeV2_BNBUSDT_4h_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_medium/studies.db`
- Data rows: `1440`
- Data range: `2025-11-08T12:00:00+00:00` to `2026-07-06T08:00:00+00:00`

## Best Trial
- Trial: `#97`
- Validation objective: `0.19748254`
- Validation score: `0.19748254`
- Validation positive windows: `1.00000000`
- Validation support rate: `0.65208400`
- Validation flip rate: `0.21338900`

## OOS Gate
- Deployed: `True`
- Rejection reasons: `[]`
- OOS score: `0.17269564`
- OOS mean downstream lift: `0.00417152`
- OOS positive windows: `1.00000000`
- OOS support rate: `0.67916700`
- OOS flip rate: `0.23640100`

## Default Vs Tuned
- Baseline deployed: `True`
- Tuned deployed: `True`
- OOS score delta: `0.02132250`
- Mean downstream lift delta: `-0.00330256`
- Positive window rate delta: `0.00000000`

## Threshold Sweep
| Param | Value | OOS Score | Deployed | Reasons |
|---|---:|---:|---|---|
| `policy.threshold_width` | `0.04000000` | `0.17885130` | `True` | `[]` |
| `policy.trend_min_strength` | `0.37000000` | `0.17794098` | `True` | `[]` |
| `policy.trend_min_strength` | `0.39000000` | `0.17545521` | `True` | `[]` |
| `fusion.trend_threshold` | `0.63000000` | `0.17436928` | `True` | `[]` |
| `fusion.trend_threshold` | `0.65000000` | `0.17436928` | `True` | `[]` |
| `policy.threshold_width` | `0.06000000` | `0.17377412` | `True` | `[]` |
| `policy.threshold_width` | `0.12000000` | `0.17346820` | `True` | `[]` |
| `fusion.trend_threshold` | `0.61000000` | `0.17269564` | `True` | `[]` |
| `fusion.break_threshold` | `0.74000000` | `0.17269564` | `True` | `[]` |
| `fusion.break_threshold` | `0.76000000` | `0.17269564` | `True` | `[]` |
| `fusion.break_threshold` | `0.80000000` | `0.17269564` | `True` | `[]` |
| `policy.min_confidence` | `0.10000000` | `0.17269564` | `True` | `[]` |
| `policy.min_confidence` | `0.12000000` | `0.17269564` | `True` | `[]` |
| `policy.min_confidence` | `0.14000000` | `0.17269564` | `True` | `[]` |
| `policy.min_confidence` | `0.16000000` | `0.17269564` | `True` | `[]` |
| `policy.min_confidence` | `0.18000000` | `0.17269564` | `True` | `[]` |
| `policy.threshold_width` | `0.08000000` | `0.17269564` | `True` | `[]` |
| `policy.trend_min_strength` | `0.41000000` | `0.17269564` | `True` | `[]` |
| `policy.breakout_min_quality` | `0.38000000` | `0.17269564` | `True` | `[]` |
| `policy.breakout_min_quality` | `0.40000000` | `0.17269564` | `True` | `[]` |

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 20,
    "fusion.break_threshold": 0.76,
    "fusion.mr_threshold": 0.6399999999999999,
    "fusion.shock_threshold": 0.87,
    "fusion.trend_threshold": 0.61,
    "policy.breakout_min_quality": 0.42000000000000004,
    "policy.high_uncertainty_no_trade": 0.73,
    "policy.min_confidence": 0.14,
    "policy.mr_min_score": 0.35,
    "policy.threshold_width": 0.08,
    "policy.trend_max_chop": 0.35,
    "policy.trend_min_strength": 0.41000000000000003,
    "trend.direction_deadzone": 0.31,
    "trend.fast_ema": 7,
    "trend.slow_ema": 16
  }
}
```
