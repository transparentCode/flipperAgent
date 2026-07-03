# RegimeV2 Phase 6U PA Paper Drift Gate Simulation

## Summary

- Active changed rows: 40
- Candidate gates: 8
- Ranked gates: 8
- Current avg paper-minus-baseline: 0.028653237975448997
- Recommendation: candidate_drift_gate_found
- Best gate: {'name': 'rolling_avg_neg_3', 'spec': {'name': 'rolling_avg_neg_3', 'kind': 'rolling_avg_neg', 'window': 3}, 'count': 40, 'paused_count': 6, 'active_count': 34, 'avg_gate_net_return': 0.004349387783202768, 'avg_gate_minus_baseline': 0.03300262575865177, 'avg_current_suppress_minus_baseline': 0.028653237975448997, 'gate_minus_current_suppress_avg': 0.004349387783202768, 'positive_gate_lift_rate': 0.8, 'recovered_missed_win_count': 6, 'lost_avoided_loss_count': 0, 'failure_window_count': 10, 'failure_window_paused_count': 6, 'failure_window_pause_rate': 0.6, 'paused_outcome_labels': {'missed_win': 6}}

## Current Suppression

- Count: 40
- Avg lift: 0.028653237975448997
- Positive lift rate: 0.8
- Outcomes: {'avoided_loss': 32, 'missed_win': 8}

## Candidate Gates

| Gate | Paused | Gate avg lift | Gate-current avg | Recovered missed | Lost avoided | Failure pause rate |
|---|---:|---:|---:|---:|---:|---:|
| rolling_avg_neg_3 | 6 | 0.03300262575865177 | 0.004349387783202768 | 6 | 0 | 0.6 |
| miss_gt_avoid_3 | 6 | 0.03300262575865177 | 0.004349387783202768 | 6 | 0 | 0.6 |
| missed_streak_2 | 5 | 0.032145508247794184 | 0.003492270272345193 | 5 | 0 | 0.5 |
| rolling_avg_neg_5 | 5 | 0.032145508247794184 | 0.003492270272345193 | 5 | 0 | 0.5 |
| miss_gt_avoid_5 | 5 | 0.032145508247794184 | 0.003492270272345193 | 5 | 0 | 0.5 |
| missed_streak_3 | 4 | 0.03119571278393509 | 0.0025424748084860995 | 4 | 0 | 0.4 |
| rolling_avg_neg_10 | 3 | 0.030232762578977862 | 0.0015795246035288668 | 3 | 0 | 0.3 |
| miss_gt_avoid_10 | 2 | 0.029447334811229298 | 0.0007940968357802999 | 2 | 0 | 0.2 |
