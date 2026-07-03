# RegimeV2 Phase 7G Follow-Through Matrix

## Summary

- Variants: 16
- Ready variants: 2
- Pair count: 4
- Thresholds: [0.2, 0.25, 0.3, 0.35]
- Recommendation: candidate_found
- Best variant: {'pair': 'BNBUSDT|1h', 'threshold': 0.25, 'active_count': 10, 'passing_cells': 8, 'cell_count': 12, 'avg_dir_return': 0.0008296337916352706, 'worst_dir_return': -0.00025770518368077946, 'ready': True, 'reasons': []}
- Best ready variant: {'pair': 'BNBUSDT|1h', 'threshold': 0.25, 'active_count': 10, 'passing_cells': 8, 'cell_count': 12, 'avg_dir_return': 0.0008296337916352706, 'worst_dir_return': -0.00025770518368077946, 'ready': True, 'reasons': []}

## Variants

| Pair | Threshold | Active | Passing | Avg dir | Worst dir | Directions | Ready | Reasons |
|---|---:|---:|---:|---:|---:|---|---|---|
| BNBUSDT|1h | 0.25 | 10 | 8/12 | 0.0008296337916352706 | -0.00025770518368077946 | {'up': 5, 'down': 5} | True | none |
| BNBUSDT|1h | 0.3 | 10 | 8/12 | 0.0008296337916352706 | -0.00025770518368077946 | {'up': 5, 'down': 5} | True | none |
| BNBUSDT|1h | 0.35 | 6 | 9/12 | 0.001860899246010267 | -1.2716217647209717e-05 | {'up': 3, 'down': 3} | False | low_support |
| BNBUSDT|1h | 0.2 | 14 | 1/12 | -0.0006361139809291824 | -0.0020590951563904925 | {'up': 7, 'down': 7} | False | low_passing_rate,avg_return_too_low,worst_cell_too_negative |
| SOLUSDT|4h | 0.2 | 6 | 0/12 | -0.00800098964622237 | -0.013415330197434459 | {'down': 3, 'up': 3} | False | low_support,low_passing_rate,avg_return_too_low,worst_cell_too_negative |
| ETHUSDT|4h | 0.3 | 2 | 0/12 | -0.009977883530716963 | -0.011972484841497698 | {'up': 1, 'down': 1} | False | low_support,low_passing_rate,avg_return_too_low,worst_cell_too_negative |
| ETHUSDT|4h | 0.35 | 2 | 0/12 | -0.009977883530716963 | -0.011972484841497698 | {'up': 1, 'down': 1} | False | low_support,low_passing_rate,avg_return_too_low,worst_cell_too_negative |
| SOLUSDT|4h | 0.25 | 4 | 0/12 | -0.013880892321990268 | -0.01661231746097854 | {'up': 2, 'down': 2} | False | low_support,low_passing_rate,avg_return_too_low,worst_cell_too_negative |
| SOLUSDT|4h | 0.3 | 4 | 0/12 | -0.013880892321990268 | -0.01661231746097854 | {'up': 2, 'down': 2} | False | low_support,low_passing_rate,avg_return_too_low,worst_cell_too_negative |
| SOLUSDT|4h | 0.35 | 4 | 0/12 | -0.013880892321990268 | -0.01661231746097854 | {'up': 2, 'down': 2} | False | low_support,low_passing_rate,avg_return_too_low,worst_cell_too_negative |
| ETHUSDT|4h | 0.25 | 3 | 0/12 | -0.014437740062094211 | -0.02161144898673341 | {'down': 2, 'up': 1} | False | low_support,low_passing_rate,avg_return_too_low,worst_cell_too_negative |
| BTCUSDT|4h | 0.2 | 7 | 0/12 | -0.01477807489956777 | -0.02293166400831916 | {'up': 4, 'down': 3} | False | low_support,low_passing_rate,avg_return_too_low,worst_cell_too_negative |
| ETHUSDT|4h | 0.2 | 4 | 0/12 | -0.01748736622558294 | -0.029472792794984482 | {'down': 3, 'up': 1} | False | low_support,low_passing_rate,avg_return_too_low,worst_cell_too_negative |
| BTCUSDT|4h | 0.25 | 5 | 0/12 | -0.01863823123876016 | -0.025440570256328076 | {'up': 3, 'down': 2} | False | low_support,low_passing_rate,avg_return_too_low,worst_cell_too_negative |
| BTCUSDT|4h | 0.3 | 3 | 0/12 | -0.02646268095794545 | -0.03921552780259227 | {'up': 2, 'down': 1} | False | low_support,low_passing_rate,avg_return_too_low,worst_cell_too_negative |
| BTCUSDT|4h | 0.35 | 0 | 0/12 | None | None | {} | False | low_support,low_passing_rate,avg_return_too_low,worst_cell_too_negative,single_direction |
