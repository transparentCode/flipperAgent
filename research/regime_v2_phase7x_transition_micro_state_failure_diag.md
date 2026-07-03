# RegimeV2 Phase 7X Transition Micro-State Failure Diagnostics

- Windows: 12
- Failure windows: 4
- Supported failures: 3
- Support-thin failures: 1
- Recommendation: diagnose_supported_mixed_windows_next
- Worst window: {'asset': 'ETHUSDT', 'window_id': 'full', 'failure_class': 'supported_breakout_better', 'compression_worst_return': -0.1372625352770353, 'breakout_setup_worst_return': -0.01993357142384784, 'failure_tags': ['compression_tail_loss']}

## Asset summary

| Asset | Windows | Supported failures | Support-thin | Worst compression | Worst breakout | Top signatures |
|---|---:|---:|---:|---:|---:|---|
| BNBUSDT | 4 | 2 | 0 | -0.04197438881769332 | -0.021807424769890588 | {'breakout_tail_loss': 2, 'compression_avg_positive': 2, 'compression_beats_breakout': 2, 'compression_tail_loss': 1, 'breakout_avg_negative': 1} |
| BTCUSDT | 4 | 1 | 0 | -0.028108162456439937 | -0.019998023133609776 | {'breakout_avg_negative': 1, 'compression_avg_positive': 1, 'compression_beats_breakout': 1, 'state_inversion': 1} |
| ETHUSDT | 4 | 0 | 1 | -0.1372625352770353 | -0.01993357142384784 | {'compression_avg_positive': 1, 'compression_tail_loss': 1, 'support_thin': 1} |

## Failure signatures

| Signature | Windows | Assets | Avg breakout | Avg compression | Worst compression |
|---|---:|---|---:|---:|---:|
| compression_avg_positive | 4 | BNBUSDT,BTCUSDT,ETHUSDT | 0.0020352051481103348 | 0.0028522707956526294 | -0.04197438881769332 |
| compression_beats_breakout | 3 | BNBUSDT,BTCUSDT | 0.00012673857161603323 | 0.003166399758136637 | -0.04197438881769332 |
| breakout_avg_negative | 2 | BNBUSDT,BTCUSDT | -0.0015794531208566443 | 0.00248771690434911 | -0.0175542812581269 |
| state_inversion | 2 | BNBUSDT,BTCUSDT | -0.0015794531208566443 | 0.00248771690434911 | -0.0175542812581269 |
| breakout_tail_loss | 2 | BNBUSDT | 0.0011306210947037735 | 0.004124038865885035 | -0.04197438881769332 |
| compression_tail_loss | 2 | BNBUSDT,ETHUSDT | 0.005649863417077314 | 0.0032168246869561483 | -0.04197438881769332 |
| support_thin | 1 | ETHUSDT | 0.00776060487759324 | 0.0019098839082006063 | -0.029277202292140207 |

## Failure windows

| Asset | Window | Class | Support | Breakout active | Compression active | Breakout avg | Compression avg | Tags |
|---|---|---|---|---:|---:|---:|---:|---|
| BNBUSDT | w1_0_360 | supported_mixed_failure | True | 22 | 21 | 0.0035391219565613884 | 0.0045237654657116905 | breakout_tail_loss,compression_avg_positive,compression_beats_breakout,compression_tail_loss |
| BNBUSDT | w2_180_540 | supported_mixed_failure | True | 18 | 20 | -0.0012778797671538413 | 0.0037243122660583793 | breakout_avg_negative,breakout_tail_loss,compression_avg_positive,compression_beats_breakout,state_inversion |
| ETHUSDT | w3_360_720 | support_thin | False | 5 | 26 | 0.00776060487759324 | 0.0019098839082006063 | compression_avg_positive,compression_tail_loss,support_thin |
| BTCUSDT | w2_180_540 | supported_mixed_failure | True | 21 | 9 | -0.0018810264745594473 | 0.0012511215426398408 | breakout_avg_negative,compression_avg_positive,compression_beats_breakout,state_inversion |
