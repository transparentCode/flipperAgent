# RegimeV2 Phase 6F PriceAction Guardrail Candidate

## Summary

- Total records: 720
- PriceAction subset removals: 185 (0.2569444444444444)
- Candidate rules: 4
- Min support: 10
- Min bad rate: 0.55
- Overall avg lift: -0.0010447234480054173
- Overall bad rate: 0.4918918918918919
- Overall positive lift rate: 0.4918918918918919

## Candidate Rules

| Rank | Condition | Count | Bad rate | Avg lift | Positive rate | Labels |
|---:|---|---:|---:|---:|---:|---|
| 1 | trend_score_bucket=trend:(0.05,0.1] | 16 | 0.6875 | 0.014448607458750982 | 0.6875 | {'avoided_loss': 11, 'missed_win': 5} |
| 2 | uncertainty_bucket=uncertainty:(0.25,0.5] | 18 | 0.6666666666666666 | 0.011799817209056634 | 0.6666666666666666 | {'avoided_loss': 12, 'missed_win': 6} |
| 3 | confidence_bucket=confidence:(0.5,0.7] | 15 | 0.6666666666666666 | 0.0041332517338866955 | 0.6666666666666666 | {'avoided_loss': 10, 'missed_win': 5} |
| 4 | trend_score_bucket=trend:(0.1,0.18] | 11 | 0.6363636363636364 | 0.021647444708385147 | 0.6363636363636364 | {'avoided_loss': 7, 'missed_win': 4} |
