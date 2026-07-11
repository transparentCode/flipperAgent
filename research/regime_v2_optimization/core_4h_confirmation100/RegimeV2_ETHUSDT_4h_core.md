# RegimeV2 Optimization: ETHUSDT 4h

## Run
- Profile: `core`
- Trials: `100/75` completed, `4` rejected
- Study: `RegimeV2_ETHUSDT_4h_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_medium/studies.db`
- Data rows: `1440`
- Data range: `2025-11-08T12:00:00+00:00` to `2026-07-06T08:00:00+00:00`

## Best Trial
- Trial: `#92`
- Validation objective: `0.18446926`
- Validation score: `0.18446926`
- Validation positive windows: `1.00000000`
- Validation support rate: `0.61250000`
- Validation flip rate: `0.25523000`

## OOS Gate
- Deployed: `True`
- Rejection reasons: `[]`
- OOS score: `0.15364263`
- OOS mean downstream lift: `0.00099232`
- OOS positive windows: `1.00000000`
- OOS support rate: `0.57916700`
- OOS flip rate: `0.25732200`

## Default Vs Tuned
- Baseline deployed: `True`
- Tuned deployed: `True`
- OOS score delta: `0.28804235`
- Mean downstream lift delta: `0.01353389`
- Positive window rate delta: `1.00000000`

## Threshold Sweep
| Param | Value | OOS Score | Deployed | Reasons |
|---|---:|---:|---|---|
| `fusion.break_threshold` | `0.69000000` | `0.15447945` | `True` | `[]` |
| `fusion.trend_threshold` | `0.66000000` | `0.15364263` | `True` | `[]` |
| `fusion.trend_threshold` | `0.68000000` | `0.15364263` | `True` | `[]` |
| `fusion.trend_threshold` | `0.70000000` | `0.15364263` | `True` | `[]` |
| `fusion.trend_threshold` | `0.72000000` | `0.15364263` | `True` | `[]` |
| `fusion.break_threshold` | `0.63000000` | `0.15364263` | `True` | `[]` |
| `fusion.break_threshold` | `0.65000000` | `0.15364263` | `True` | `[]` |
| `fusion.break_threshold` | `0.67000000` | `0.15364263` | `True` | `[]` |
| `policy.min_confidence` | `0.13000000` | `0.15364263` | `True` | `[]` |
| `policy.min_confidence` | `0.15000000` | `0.15364263` | `True` | `[]` |
| `policy.min_confidence` | `0.17000000` | `0.15364263` | `True` | `[]` |
| `policy.min_confidence` | `0.19000000` | `0.15364263` | `True` | `[]` |
| `policy.min_confidence` | `0.21000000` | `0.15364263` | `True` | `[]` |
| `policy.threshold_width` | `0.23000000` | `0.15364263` | `True` | `[]` |
| `policy.threshold_width` | `0.25000000` | `0.15364263` | `True` | `[]` |
| `policy.trend_min_strength` | `0.29000000` | `0.15364263` | `True` | `[]` |
| `policy.breakout_min_quality` | `0.58000000` | `0.15364263` | `True` | `[]` |
| `policy.breakout_min_quality` | `0.60000000` | `0.15364263` | `True` | `[]` |
| `policy.breakout_min_quality` | `0.62000000` | `0.15364263` | `True` | `[]` |
| `policy.breakout_min_quality` | `0.64000000` | `0.15364263` | `True` | `[]` |

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 19,
    "fusion.break_threshold": 0.65,
    "fusion.mr_threshold": 0.6799999999999999,
    "fusion.shock_threshold": 0.7,
    "fusion.trend_threshold": 0.6799999999999999,
    "policy.breakout_min_quality": 0.62,
    "policy.high_uncertainty_no_trade": 0.6,
    "policy.min_confidence": 0.17,
    "policy.mr_min_score": 0.29,
    "policy.threshold_width": 0.22999999999999998,
    "policy.trend_max_chop": 0.42000000000000004,
    "policy.trend_min_strength": 0.29,
    "trend.direction_deadzone": 0.22999999999999998,
    "trend.fast_ema": 7,
    "trend.slow_ema": 21
  }
}
```
