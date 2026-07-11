# RegimeProbV1 Optimization: BTCUSDT 4h

## Run
- Profile: `full_shadow_only`
- Playbook: `multi-playbook`
- Horizon: `3`
- Trials: `24/24` completed, `24` rejected
- Study: `RegimeProbV1_BTCUSDT_4h_full_shadow_only_multi_h3`
- Storage: `in-memory`
- Data rows: `8767`

## Best Trial
- Trial: `#0`
- Validation objective: `-2000000.00000000`
- Validation score: `-1000000.00000000`
- Validation positive windows: `0.00000000`
- Validation support rate: `0.00000000`
- Validation edge return: `0.00000000`

## OOS Gate
- Deployed: `False`
- Raw OOS gate passed: `False`
- Rejection reasons: `['validation:no_valid_windows', 'oos:no_valid_probability_rows', 'promotion:tuned:validation:no_valid_windows', 'promotion:tuned:oos:no_valid_probability_rows', 'promotion:oos_score_not_above_baseline']`
- OOS score: `-1000000.00000000`
- OOS edge return: `0.00000000`
- OOS positive windows: `0.00000000`
- OOS support rate: `0.00000000`
- OOS Brier: `1.00000000`
- OOS ECE: `1.00000000`

## HMM Support
- State source: `hmm_state_model`
- In-sample rows: `500`
- OOS-filtered rows: `8267`
- Proxy-fallback rows: `0`
- OOS-filtered support rate: `0.94296795`

## Promotion Gate
- Ready: `False`
- Rejection reasons: `['tuned:validation:no_valid_windows', 'tuned:oos:no_valid_probability_rows', 'oos_score_not_above_baseline']`
- OOS score delta: `0.00000000`
- Mean edge return delta: `0.00000000`
- Positive window rate delta: `0.00000000`
- Brier delta: `0.00000000`
- ECE delta: `0.00000000`

## Default Vs Tuned
- Baseline deployed: `False`
- Tuned deployed: `False`
- OOS score delta: `0.00000000`
- Mean edge return delta: `0.00000000`
- Positive window rate delta: `0.00000000`

## Deploy Params
```json
{
  "params": {
    "active_probability_threshold": 0.33,
    "beta_weight": 0.0,
    "btc_d_conflict_weight": 0.2,
    "changepoint_prob_threshold": 0.46,
    "confirmation_boost": 0.34,
    "conflict_penalty": 0.1,
    "context_staleness_penalty": 0.6,
    "entropy_max_penalty": 0.05,
    "entropy_scale": 1.25,
    "higher_tf_weight": 1.5,
    "market_alignment_weight": 0.6,
    "max_staleness_bars": 5,
    "max_state_entropy": 0.3,
    "max_transition_state_prob": 0.59,
    "min_bin_count": 39,
    "min_breakout_state_prob": 0.37,
    "min_edge_probability": 0.33,
    "min_policy_score": 0.02,
    "min_range_state_prob": 0.46,
    "min_trend_state_prob": 0.52,
    "n_bins": 10,
    "recommendation_min_probability": 0.26,
    "require_policy_allow": true,
    "strategy": "quantile",
    "top_k": 3,
    "total3_confirmation_weight": 0.5,
    "transition_max_penalty": 0.11,
    "transition_risk_threshold": 0.33,
    "uncertainty_threshold": 0.49
  },
  "profile": "full_shadow_only"
}
```
