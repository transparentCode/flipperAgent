# RegimeV2 Optimization: BTCUSDT 4h

## Run
- Profile: `core`
- Trials: `100/75` completed, `2` rejected
- Study: `RegimeV2_BTCUSDT_4h_core`
- Storage: `sqlite:///research/regime_v2_optimization/core_medium/studies.db`
- Data rows: `1440`
- Data range: `2025-11-08T12:00:00+00:00` to `2026-07-06T08:00:00+00:00`

## Best Trial
- Trial: `#78`
- Validation objective: `0.18458753`
- Validation score: `0.18458753`
- Validation positive windows: `1.00000000`
- Validation support rate: `0.69583300`
- Validation flip rate: `0.19037700`

## OOS Gate
- Deployed: `True`
- Rejection reasons: `[]`
- OOS score: `0.16013950`
- OOS mean downstream lift: `0.00485171`
- OOS positive windows: `1.00000000`
- OOS support rate: `0.64583300`
- OOS flip rate: `0.18828400`

## Default Vs Tuned
- Baseline deployed: `True`
- Tuned deployed: `True`
- OOS score delta: `0.27661193`
- Mean downstream lift delta: `0.01306510`
- Positive window rate delta: `1.00000000`

## Threshold Sweep
| Param | Value | OOS Score | Deployed | Reasons |
|---|---:|---:|---|---|
| `fusion.trend_threshold` | `0.63000000` | `0.16432361` | `True` | `[]` |
| `fusion.trend_threshold` | `0.61000000` | `0.16348678` | `True` | `[]` |
| `policy.trend_min_strength` | `0.43000000` | `0.16106466` | `True` | `[]` |
| `policy.threshold_width` | `0.30000000` | `0.16022720` | `True` | `[]` |
| `policy.threshold_width` | `0.32000000` | `0.16022720` | `True` | `[]` |
| `policy.trend_min_strength` | `0.45000000` | `0.16018711` | `True` | `[]` |
| `fusion.trend_threshold` | `0.59000000` | `0.16013950` | `True` | `[]` |
| `fusion.break_threshold` | `0.75000000` | `0.16013950` | `True` | `[]` |
| `fusion.break_threshold` | `0.77000000` | `0.16013950` | `True` | `[]` |
| `fusion.break_threshold` | `0.79000000` | `0.16013950` | `True` | `[]` |
| `fusion.break_threshold` | `0.81000000` | `0.16013950` | `True` | `[]` |
| `policy.min_confidence` | `0.16000000` | `0.16013950` | `True` | `[]` |
| `policy.min_confidence` | `0.18000000` | `0.16013950` | `True` | `[]` |
| `policy.min_confidence` | `0.20000000` | `0.16013950` | `True` | `[]` |
| `policy.min_confidence` | `0.22000000` | `0.16013950` | `True` | `[]` |
| `policy.min_confidence` | `0.24000000` | `0.16013950` | `True` | `[]` |
| `policy.threshold_width` | `0.28000000` | `0.16013950` | `True` | `[]` |
| `policy.trend_min_strength` | `0.41000000` | `0.16013950` | `True` | `[]` |
| `policy.breakout_min_quality` | `0.40000000` | `0.16013950` | `True` | `[]` |
| `policy.breakout_min_quality` | `0.42000000` | `0.16013950` | `True` | `[]` |

## Deploy Params
```json
{
  "params": {
    "breaks.breakout_window": 25,
    "fusion.break_threshold": 0.77,
    "fusion.mr_threshold": 0.62,
    "fusion.shock_threshold": 0.9299999999999999,
    "fusion.trend_threshold": 0.59,
    "policy.breakout_min_quality": 0.44,
    "policy.high_uncertainty_no_trade": 0.74,
    "policy.min_confidence": 0.2,
    "policy.mr_min_score": 0.3,
    "policy.threshold_width": 0.28,
    "policy.trend_max_chop": 0.74,
    "policy.trend_min_strength": 0.41000000000000003,
    "trend.direction_deadzone": 0.25,
    "trend.fast_ema": 6,
    "trend.slow_ema": 15
  }
}
```
