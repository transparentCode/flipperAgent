# RegimeV2 Phase 6M PA Paper Robustness Report

## Summary

- Total records: 180
- Candidate rows: 40
- Passing cells: 0 / 12
- Negative cells: 0
- Rolling-stable cells: 0
- Recommendation: hold_off
- Paper-ready: False
- Best cell: {'horizon_bars': 24, 'fee_bps': 10.0, 'count': 40, 'avg_paper_minus_baseline': 0.029453237975449, 'positive_paper_lift_rate': 0.8, 'bad_rate': 0.8}
- Worst cell: {'horizon_bars': 3, 'fee_bps': 2.0, 'count': 40, 'avg_paper_minus_baseline': 0.006701542048503745, 'positive_paper_lift_rate': 0.8, 'bad_rate': 0.8}
- Worst rolling window: {'count': 10, 'bad_count': 2, 'bad_rate': 0.2, 'avg_baseline_net_return': 0.019160547889928922, 'avg_paper_net_return': 0.0, 'avg_paper_minus_baseline': -0.019160547889928922, 'positive_paper_lift_rate': 0.2, 'outcome_labels': {'avoided_loss': 2, 'missed_win': 8}, 'start_timestamp': 1780696800.0, 'end_timestamp': 1780891200.0, 'horizon_bars': 24, 'fee_bps': 2.0, 'rolling_window': 30}

## Cells

| Horizon | Fee bps | Active changed | Avg lift | Positive rate | Bad rate | Rolling stable | Status | Reasons |
|---:|---:|---:|---:|---:|---:|---|---|---|
| 3 | 2.0 | 40 | 0.006701542048503745 | 0.8 | 0.8 | False | fail | rolling_not_stable |
| 3 | 5.0 | 40 | 0.007001542048503745 | 0.8 | 0.8 | False | fail | rolling_not_stable |
| 3 | 10.0 | 40 | 0.007501542048503745 | 0.8 | 0.8 | False | fail | rolling_not_stable |
| 6 | 2.0 | 40 | 0.01036419087119552 | 0.775 | 0.775 | False | fail | rolling_not_stable |
| 6 | 5.0 | 40 | 0.01066419087119552 | 0.775 | 0.775 | False | fail | rolling_not_stable |
| 6 | 10.0 | 40 | 0.011164190871195521 | 0.8 | 0.8 | False | fail | rolling_not_stable |
| 12 | 2.0 | 40 | 0.01903733430528352 | 0.775 | 0.775 | False | fail | rolling_not_stable |
| 12 | 5.0 | 40 | 0.019337334305283522 | 0.775 | 0.775 | False | fail | rolling_not_stable |
| 12 | 10.0 | 40 | 0.019837334305283522 | 0.8 | 0.8 | False | fail | rolling_not_stable |
| 24 | 2.0 | 40 | 0.028653237975448997 | 0.8 | 0.8 | False | fail | rolling_not_stable |
| 24 | 5.0 | 40 | 0.028953237975449 | 0.8 | 0.8 | False | fail | rolling_not_stable |
| 24 | 10.0 | 40 | 0.029453237975449 | 0.8 | 0.8 | False | fail | rolling_not_stable |
