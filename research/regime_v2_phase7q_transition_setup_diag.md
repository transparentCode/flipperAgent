# RegimeV2 Phase 7Q Setup Transition Diagnostics

## Summary

- Variants: 27
- Recommendation: diagnose_worst_cell_prune_before_promotion
- Best variant: {'asset': 'ETHUSDT', 'timeframe': '1h', 'active_count': 61, 'passed_split_count': 3, 'split_count': 4, 'avg_split_directional_return': 0.0039739721595662865, 'worst_split_directional_return': -0.003882197085900328, 'ready': False, 'direction_distribution': {'down': 31, 'up': 30}, 'state_distribution': {'BREAKOUT_EXHAUSTION_TRANSITION': 1, 'FAILED_BREAKOUT_REVERSAL_SETUP': 60, 'NO_BREAKOUT_TRANSITION': 659}, 'config': {'lookback_bars': 8, 'max_conflict_count': 1, 'max_risk_score': 0.72, 'min_attempt_score': 0.5, 'min_candidate_score': 0.62, 'min_context_score': 0.7, 'min_wick_score': 0.35}}

## Asset summary

| Asset | Variants | Max active | Best passed | Best avg | Best worst |
|---|---:|---:|---:|---:|---:|
| BNBUSDT | 9 | 92 | 2 | 0.0014702568291734288 | -0.005427503391288226 |
| BTCUSDT | 9 | 76 | 1 | 0.0009192539894406193 | -0.0025965827966905348 |
| ETHUSDT | 9 | 66 | 3 | 0.0047578560351840115 | -0.0027732003430175805 |

## Best variant failure profile

- Failed split count: 1
- Failure reasons: {'low_passing_rate': 1, 'avg_return_too_low': 1, 'worst_cell_too_negative': 1}
- Worst failed split: {'split_index': 3, 'active_count': 13, 'direction_distribution': {'down': 8, 'up': 5}, 'failure_reasons': ['low_passing_rate', 'avg_return_too_low', 'worst_cell_too_negative'], 'passing_cell_rate': 0.5, 'avg_directional_net_return': -0.0004858095056605013, 'worst_directional_net_return': -0.003882197085900328, 'start_timestamp': '2026-06-18 14:00:00+00:00', 'end_timestamp': '2026-06-26 01:00:00+00:00'}
- Direction distribution in failed splits: {'down': 8, 'up': 5}

## Top variants

| Asset | Lookback | Min score | Active | Passed | Avg | Worst |
|---|---:|---:|---:|---:|---:|---:|
| ETHUSDT | 8 | 0.62 | 61 | 3/4 | 0.0039739721595662865 | -0.003882197085900328 |
| ETHUSDT | 8 | 0.58 | 66 | 3/4 | 0.003671589930131386 | -0.003882197085900328 |
| ETHUSDT | 8 | 0.66 | 52 | 2/4 | 0.004598568998353891 | -0.0028739044176989913 |
| ETHUSDT | 20 | 0.62 | 40 | 2/4 | 0.004074906459843064 | -0.006713553121788876 |
| ETHUSDT | 12 | 0.58 | 57 | 2/4 | 0.0035872482982254035 | -0.003829429381405423 |
| ETHUSDT | 20 | 0.58 | 45 | 2/4 | 0.0034032068067827307 | -0.006819196861712534 |
| BNBUSDT | 20 | 0.66 | 47 | 2/4 | 0.0014702568291734288 | -0.006266821230584193 |
| BNBUSDT | 20 | 0.58 | 73 | 2/4 | 0.00021240966946155048 | -0.005969409615809888 |
| BNBUSDT | 8 | 0.62 | 83 | 2/4 | 0.00013537456011377476 | -0.0056916472959480146 |
| BNBUSDT | 8 | 0.58 | 92 | 2/4 | -6.948577422411363e-05 | -0.005427503391288226 |
