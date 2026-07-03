# RegimeV2 Phase 6V PA Paper Drift Gate Matrix

## Summary

- Gate: rolling_avg_neg_3
- Cells: 6 / 12 passing
- Improved cells: 12
- No-lost-avoided cells: 6
- Rolling-stable cells: 7
- Recommendation: hold_off
- Matrix-ready: False
- Best cell: {'horizon_bars': 24, 'fee_bps': 2.0, 'count': 40, 'gate_minus_current_suppress_avg': 0.004349387783202768, 'avg_gate_minus_baseline': 0.03300262575865177, 'recovered_missed_win_count': 6, 'lost_avoided_loss_count': 0}
- Worst cell: {'horizon_bars': 6, 'fee_bps': 10.0, 'count': 40, 'gate_minus_current_suppress_avg': 0.0005918413065712553, 'avg_gate_minus_baseline': 0.011756032177766777, 'recovered_missed_win_count': 3, 'lost_avoided_loss_count': 2}
- Worst rolling window: {'count': 20, 'start_timestamp': 1780261200.0, 'end_timestamp': 1780603200.0, 'gate_minus_current_suppress_avg': -0.0006556879307570669, 'avg_gate_minus_baseline': 0.013197801220012642, 'recovered_missed_win_count': 0, 'lost_avoided_loss_count': 1, 'horizon_bars': 6, 'fee_bps': 10.0, 'rolling_window': 20}

## Cells

| Horizon | Fee | Count | Gate-current avg | Recovered | Lost avoided | Failure pause | Rolling stable | Status | Reasons |
|---:|---:|---:|---:|---:|---:|---:|---|---|
| 3 | 2.0 | 40 | 0.0007139315225512286 | 2 | 2 | None | False | fail | lost_avoided_losses, rolling_not_stable |
| 3 | 5.0 | 40 | 0.0006839315225512286 | 2 | 2 | None | False | fail | lost_avoided_losses, rolling_not_stable |
| 3 | 10.0 | 40 | 0.0010173620933617011 | 2 | 1 | None | True | fail | lost_avoided_losses |
| 6 | 2.0 | 40 | 0.0006918413065712554 | 3 | 2 | None | False | fail | lost_avoided_losses, rolling_not_stable |
| 6 | 5.0 | 40 | 0.0006543413065712553 | 3 | 2 | None | False | fail | lost_avoided_losses, rolling_not_stable |
| 6 | 10.0 | 40 | 0.0005918413065712553 | 3 | 2 | None | False | fail | lost_avoided_losses, rolling_not_stable |
| 12 | 2.0 | 40 | 0.0022291448685004883 | 6 | 0 | None | True | pass |  |
| 12 | 5.0 | 40 | 0.0021841448685004884 | 6 | 0 | None | True | pass |  |
| 12 | 10.0 | 40 | 0.0021091448685004884 | 6 | 0 | None | True | pass |  |
| 24 | 2.0 | 40 | 0.004349387783202768 | 6 | 0 | None | True | pass |  |
| 24 | 5.0 | 40 | 0.004304387783202768 | 6 | 0 | None | True | pass |  |
| 24 | 10.0 | 40 | 0.004229387783202768 | 6 | 0 | None | True | pass |  |
