# RegimeV2 Phase 6I PriceAction Asset Candidate

## Summary

- Candidate: BNBUSDT|1h direction=1
- Total records: 720
- Candidate rows: 39 (0.05416666666666667)
- Passing cells: 12 / 12
- Negative cells: 0
- Rolling-stable cells: 12
- Recommendation: paper_candidate
- Promote ready: True
- Best cell: {'horizon_bars': 24, 'fee_bps': 10.0, 'count': 39, 'avg_shadow_minus_baseline': 0.03043681728217294, 'positive_shadow_lift_rate': 0.8205128205128205, 'bad_rate': 0.8205128205128205}
- Worst cell: {'horizon_bars': 3, 'fee_bps': 2.0, 'count': 39, 'avg_shadow_minus_baseline': 0.006866099415516237, 'positive_shadow_lift_rate': 0.7948717948717948, 'bad_rate': 0.7948717948717948}
- Worst rolling window: {'count': 19, 'bad_count': 13, 'bad_rate': 0.6842105263157895, 'avg_baseline_net_return': -0.003480964765908864, 'avg_shadow_minus_baseline': 0.003480964765908864, 'positive_shadow_lift_rate': 0.6842105263157895, 'outcome_labels': {'avoided_loss': 13, 'missed_win': 6}, 'start_timestamp': 1780606800.0, 'end_timestamp': 1780866000.0, 'horizon_bars': 3, 'fee_bps': 2.0, 'rolling_window': 20}

## Horizon/Fee Cells

| Horizon | Fee bps | Count | Avg lift | Positive rate | Bad rate | Rolling stable | Status | Reasons |
|---:|---:|---:|---:|---:|---:|---|---|---|
| 3 | 2.0 | 39 | 0.006866099415516237 | 0.7948717948717948 | 0.7948717948717948 | True | pass |  |
| 3 | 5.0 | 39 | 0.007166099415516238 | 0.7948717948717948 | 0.7948717948717948 | True | pass |  |
| 3 | 10.0 | 39 | 0.007666099415516239 | 0.7948717948717948 | 0.7948717948717948 | True | pass |  |
| 6 | 2.0 | 39 | 0.010694764867263637 | 0.7948717948717948 | 0.7948717948717948 | True | pass |  |
| 6 | 5.0 | 39 | 0.010994764867263638 | 0.7948717948717948 | 0.7948717948717948 | True | pass |  |
| 6 | 10.0 | 39 | 0.011494764867263639 | 0.8205128205128205 | 0.8205128205128205 | True | pass |  |
| 12 | 2.0 | 39 | 0.019839373053687614 | 0.7948717948717948 | 0.7948717948717948 | True | pass |  |
| 12 | 5.0 | 39 | 0.020139373053687615 | 0.7948717948717948 | 0.7948717948717948 | True | pass |  |
| 12 | 10.0 | 39 | 0.020639373053687612 | 0.8205128205128205 | 0.8205128205128205 | True | pass |  |
| 24 | 2.0 | 39 | 0.029636817282172937 | 0.8205128205128205 | 0.8205128205128205 | True | pass |  |
| 24 | 5.0 | 39 | 0.02993681728217294 | 0.8205128205128205 | 0.8205128205128205 | True | pass |  |
| 24 | 10.0 | 39 | 0.03043681728217294 | 0.8205128205128205 | 0.8205128205128205 | True | pass |  |

## Comparison Across Assets

| Asset/TF | Count | Avg lift | Positive rate | Bad rate |
|---|---:|---:|---:|---:|
| BNBUSDT|1h | 468 | 0.017125930321326775 | 0.8055555555555556 | 0.8055555555555556 |
| BTCUSDT|4h | 204 | -0.009219100927506059 | 0.31862745098039214 | 0.31862745098039214 |
| SOLUSDT|4h | 144 | -0.011510433970034668 | 0.3958333333333333 | 0.3958333333333333 |
| ETHUSDT|4h | 240 | -0.027960638036179316 | 0.2875 | 0.2875 |
