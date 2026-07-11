# RegimeProbV1 Optimization: ETHUSDT 4h

## Run
- Profile: `state_core`
- Playbook: `multi-playbook`
- Horizon: `3`
- Trials: `24/24` completed, `22` rejected
- Study: `RegimeProbV1_ETHUSDT_4h_state_core_multi_h3`
- Storage: `in-memory`
- Data rows: `8767`

## Best Trial
- Trial: `#11`
- Validation objective: `0.03496900`
- Validation score: `0.03496900`
- Validation positive windows: `0.75000000`
- Validation support rate: `0.98541675`
- Validation edge return: `0.00030094`

## OOS Gate
- Deployed: `False`
- Raw OOS gate passed: `False`
- Rejection reasons: `['oos:positive_window_rate_below_minimum', 'oos:mean_edge_return_below_minimum', 'promotion:tuned:oos:positive_window_rate_below_minimum', 'promotion:tuned:oos:mean_edge_return_below_minimum']`
- OOS score: `0.02821398`
- OOS edge return: `-0.00232679`
- OOS positive windows: `0.00000000`
- OOS support rate: `0.99895825`
- OOS Brier: `0.26818821`
- OOS ECE: `0.12567967`

## HMM Support
- State source: `hmm_state_model`
- In-sample rows: `500`
- OOS-filtered rows: `8267`
- Proxy-fallback rows: `0`
- OOS-filtered support rate: `0.94296795`

## Promotion Gate
- Ready: `False`
- Rejection reasons: `['tuned:oos:positive_window_rate_below_minimum', 'tuned:oos:mean_edge_return_below_minimum']`
- OOS score delta: `0.00229769`
- Mean edge return delta: `0.00045085`
- Positive window rate delta: `0.00000000`
- Brier delta: `-0.00089228`
- ECE delta: `-0.00722708`

## Default Vs Tuned
- Baseline deployed: `False`
- Tuned deployed: `False`
- OOS score delta: `0.00229769`
- Mean edge return delta: `0.00045085`
- Positive window rate delta: `0.00000000`

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
