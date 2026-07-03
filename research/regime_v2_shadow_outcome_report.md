# RegimeV2 Phase 6 Shadow Outcome Report

## Summary

- Source: research/regime_v2_shadow_outcomes.jsonl
- Records read: 720
- Labeled: 720
- Unlabeled: 0
- Selection changed: 197
- Gate-active changed: 15
- Subset-only changed: 185
- Avg baseline net return: -0.0071959330825019695
- Avg shadow net return: -0.008243337621960358
- Avg shadow minus baseline: -0.0010474045394583873
- Avg changed shadow minus baseline: -0.0038280775046194864
- Avg gate-active changed shadow minus baseline: -0.03894379511421357
- Changed positive lift rate: 0.47715736040609136

## Outcome Labels

- avoided_loss: 94
- missed_win: 103
- unchanged: 523

## Model Pair Outcomes

| Baseline | Shadow | Count | Avg lift | Positive rate | Labels |
|---|---|---:|---:|---:|---|
| Momentum | Momentum | 420 | 0.0 | 0.0 | {'unchanged': 420} |
| PriceAction | none | 185 | -0.0010447234480054173 | 0.4918918918918919 | {'avoided_loss': 91, 'missed_win': 94} |
| TrendFollowing | TrendFollowing | 85 | 0.0 | 0.0 | {'unchanged': 85} |
| RegimePullbackScorer | RegimePullbackScorer | 17 | 0.0 | 0.0 | {'unchanged': 17} |
| Momentum | none | 6 | 0.011699059643006259 | 0.5 | {'avoided_loss': 3, 'missed_win': 3} |
| RegimePullbackScorer | Momentum | 5 | -0.11210471267052813 | 0.0 | {'missed_win': 5} |
| RegimePullbackScorer | none | 1 | -0.07052822503443365 | 0.0 | {'missed_win': 1} |
| SqueezeBreakout | SqueezeBreakout | 1 | 0.0 | 0.0 | {'unchanged': 1} |
