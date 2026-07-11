# RegimeProbV1 Optimization: BTCUSDT 4h

## Run
- Profile: `transition`
- Playbook: `multi-playbook`
- Horizon: `3`
- Trials: `24/24` completed, `24` rejected
- Study: `RegimeProbV1_BTCUSDT_4h_transition_multi_h3`
- Storage: `in-memory`
- Data rows: `8767`

## Best Trial
- Trial: `#23`
- Validation objective: `-999999.95961053`
- Validation score: `0.04038947`
- Validation positive windows: `0.00000000`
- Validation support rate: `1.00000000`
- Validation edge return: `-0.00312027`

## OOS Gate
- Deployed: `False`
- Raw OOS gate passed: `False`
- Rejection reasons: `['validation:positive_window_rate_below_minimum', 'validation:mean_edge_return_below_minimum', 'promotion:tuned:validation:positive_window_rate_below_minimum', 'promotion:tuned:validation:mean_edge_return_below_minimum']`
- OOS score: `0.04034969`
- OOS edge return: `0.00010644`
- OOS positive windows: `1.00000000`
- OOS support rate: `1.00000000`
- OOS Brier: `0.27500038`
- OOS ECE: `0.16117627`

## HMM Support
- State source: `hmm_state_model`
- In-sample rows: `500`
- OOS-filtered rows: `8267`
- Proxy-fallback rows: `0`
- OOS-filtered support rate: `0.94296795`

## Promotion Gate
- Ready: `False`
- Rejection reasons: `['tuned:validation:positive_window_rate_below_minimum', 'tuned:validation:mean_edge_return_below_minimum']`
- OOS score delta: `0.02615846`
- Mean edge return delta: `0.00092696`
- Positive window rate delta: `1.00000000`
- Brier delta: `-0.00663228`
- ECE delta: `-0.01630972`

## Default Vs Tuned
- Baseline deployed: `False`
- Tuned deployed: `False`
- OOS score delta: `0.02615846`
- Mean edge return delta: `0.00092696`
- Positive window rate delta: `1.00000000`

## Deploy Params
```json
{
  "params": {
    "changepoint_prob_threshold": 0.42,
    "max_state_entropy": 0.95,
    "max_transition_state_prob": 0.74,
    "min_edge_probability": 0.31,
    "transition_risk_threshold": 0.32,
    "uncertainty_threshold": 0.37
  },
  "profile": "transition"
}
```
