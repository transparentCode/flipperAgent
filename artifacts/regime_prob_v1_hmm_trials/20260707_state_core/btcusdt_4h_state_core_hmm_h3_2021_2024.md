# RegimeProbV1 Optimization: BTCUSDT 4h

## Run
- Profile: `state_core`
- Playbook: `multi-playbook`
- Horizon: `3`
- Trials: `24/24` completed, `24` rejected
- Study: `RegimeProbV1_BTCUSDT_4h_state_core_multi_h3`
- Storage: `in-memory`
- Data rows: `8767`

## Best Trial
- Trial: `#11`
- Validation objective: `-999999.96950682`
- Validation score: `0.03049318`
- Validation positive windows: `0.00000000`
- Validation support rate: `1.00000000`
- Validation edge return: `-0.00107675`

## OOS Gate
- Deployed: `False`
- Raw OOS gate passed: `False`
- Rejection reasons: `['validation:positive_window_rate_below_minimum', 'validation:mean_edge_return_below_minimum', 'promotion:tuned:validation:positive_window_rate_below_minimum', 'promotion:tuned:validation:mean_edge_return_below_minimum', 'promotion:positive_window_rate_regressed', 'promotion:expected_calibration_error_regressed']`
- OOS score: `0.05513836`
- OOS edge return: `0.00065491`
- OOS positive windows: `0.66666667`
- OOS support rate: `0.96527767`
- OOS Brier: `0.25353495`
- OOS ECE: `0.06279040`

## HMM Support
- State source: `hmm_state_model`
- In-sample rows: `500`
- OOS-filtered rows: `8267`
- Proxy-fallback rows: `0`
- OOS-filtered support rate: `0.94296795`

## Promotion Gate
- Ready: `False`
- Rejection reasons: `['tuned:validation:positive_window_rate_below_minimum', 'tuned:validation:mean_edge_return_below_minimum', 'positive_window_rate_regressed', 'expected_calibration_error_regressed']`
- OOS score delta: `0.00082372`
- Mean edge return delta: `0.00014805`
- Positive window rate delta: `-0.33333333`
- Brier delta: `-0.00001884`
- ECE delta: `0.00544810`

## Default Vs Tuned
- Baseline deployed: `False`
- Tuned deployed: `False`
- OOS score delta: `0.00082372`
- Mean edge return delta: `0.00014805`
- Positive window rate delta: `-0.33333333`

## Deploy Params
```json
{
  "params": {
    "max_state_entropy": 0.75,
    "max_transition_state_prob": 0.62,
    "min_breakout_state_prob": 0.41,
    "min_edge_probability": 0.25,
    "min_range_state_prob": 0.41,
    "min_trend_state_prob": 0.58
  },
  "profile": "state_core"
}
```
