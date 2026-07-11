# RegimeV2 Optimization: SOLUSDT 4h

## Run
- Profile: `core`
- Trials: `100/75` completed, `5` rejected
- Study: `RegimeV2_SOLUSDT_4h_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_medium/studies.db`
- Data rows: `1440`
- Data range: `2025-11-08T12:00:00+00:00` to `2026-07-06T08:00:00+00:00`

## Best Trial
- Trial: `#95`
- Validation objective: `0.17785438`
- Validation score: `0.17785438`
- Validation positive windows: `1.00000000`
- Validation support rate: `0.69791700`
- Validation flip rate: `0.24895400`

## OOS Gate
- Deployed: `True`
- Rejection reasons: `[]`
- OOS score: `0.16232617`
- OOS mean downstream lift: `0.00766491`
- OOS positive windows: `1.00000000`
- OOS support rate: `0.66250000`
- OOS flip rate: `0.19874500`

## Default Vs Tuned
- Baseline deployed: `True`
- Tuned deployed: `True`
- OOS score delta: `0.00679181`
- Mean downstream lift delta: `-0.01091764`
- Positive window rate delta: `0.00000000`

## Threshold Sweep
| Param | Value | OOS Score | Deployed | Reasons |
|---|---:|---:|---|---|
| `policy.threshold_width` | `0.19000000` | `0.16548878` | `True` | `[]` |
| `policy.trend_min_strength` | `0.32000000` | `0.16516219` | `True` | `[]` |
| `policy.trend_min_strength` | `0.26000000` | `0.16352330` | `True` | `[]` |
| `policy.trend_min_strength` | `0.24000000` | `0.16272285` | `True` | `[]` |
| `policy.trend_min_strength` | `0.30000000` | `0.16234631` | `True` | `[]` |
| `fusion.trend_threshold` | `0.70000000` | `0.16232617` | `True` | `[]` |
| `fusion.trend_threshold` | `0.72000000` | `0.16232617` | `True` | `[]` |
| `fusion.trend_threshold` | `0.74000000` | `0.16232617` | `True` | `[]` |
| `fusion.trend_threshold` | `0.76000000` | `0.16232617` | `True` | `[]` |
| `fusion.break_threshold` | `0.66000000` | `0.16232617` | `True` | `[]` |
| `fusion.break_threshold` | `0.68000000` | `0.16232617` | `True` | `[]` |
| `fusion.break_threshold` | `0.70000000` | `0.16232617` | `True` | `[]` |
| `fusion.break_threshold` | `0.72000000` | `0.16232617` | `True` | `[]` |
| `fusion.break_threshold` | `0.74000000` | `0.16232617` | `True` | `[]` |
| `policy.min_confidence` | `0.13000000` | `0.16232617` | `True` | `[]` |
| `policy.min_confidence` | `0.15000000` | `0.16232617` | `True` | `[]` |
| `policy.min_confidence` | `0.17000000` | `0.16232617` | `True` | `[]` |
| `policy.min_confidence` | `0.19000000` | `0.16232617` | `True` | `[]` |
| `policy.min_confidence` | `0.21000000` | `0.16232617` | `True` | `[]` |
| `policy.threshold_width` | `0.21000000` | `0.16232617` | `True` | `[]` |

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 27,
    "fusion.break_threshold": 0.7,
    "fusion.mr_threshold": 0.77,
    "fusion.shock_threshold": 0.72,
    "fusion.trend_threshold": 0.72,
    "policy.breakout_min_quality": 0.79,
    "policy.high_uncertainty_no_trade": 0.94,
    "policy.min_confidence": 0.17,
    "policy.mr_min_score": 0.8,
    "policy.threshold_width": 0.22999999999999998,
    "policy.trend_max_chop": 0.73,
    "policy.trend_min_strength": 0.28,
    "trend.direction_deadzone": 0.09,
    "trend.fast_ema": 5,
    "trend.slow_ema": 14
  }
}
```
