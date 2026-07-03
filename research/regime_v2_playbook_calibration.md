# RegimeV2 Phase 6D Playbook Calibration

## Summary

- Records: 320
- Labeled: 320
- Unlabeled: 0
- Floors: [0.1, 0.14, 0.18, 0.2, 0.22, 0.24]
- Best policy-gated cell: {'playbook': 'trend', 'floor': 0.1, 'count': 13, 'avg_shadow_minus_baseline': 1.943595169753235e-05, 'positive_shadow_lift_rate': 0.07692307692307693}
- Best score-only cell: {'playbook': 'mean_reversion', 'floor': 0.2, 'count': 1, 'avg_shadow_minus_baseline': 0.03360617413240348, 'positive_shadow_lift_rate': 1.0}
- Best allow-blocked score-pass cell: {'playbook': 'mean_reversion', 'floor': 0.2, 'count': 1, 'avg_shadow_minus_baseline': 0.03360617413240348, 'positive_shadow_lift_rate': 1.0}

## Playbook Floor Sweep

| Playbook | Floor | Policy count | Policy lift | Score-only count | Score-only lift | Allow-blocked count | Allow-blocked lift |
|---|---:|---:|---:|---:|---:|---:|---:|
| trend | 0.1 | 13 | 1.943595169753235e-05 | 38 | -9.757339066857736e-06 | 25 | -2.4937850264340582e-05 |
| trend | 0.14 | 13 | 1.943595169753235e-05 | 26 | -1.4260726328484383e-05 | 13 | -4.795740435450112e-05 |
| trend | 0.18 | 13 | 1.943595169753235e-05 | 18 | -2.0598826918921888e-05 | 5 | -0.0001246892513217029 |
| trend | 0.2 | 13 | 1.943595169753235e-05 | 14 | 1.80476694334229e-05 | 1 | 0.0 |
| trend | 0.22 | 13 | 1.943595169753235e-05 | 13 | 1.943595169753235e-05 | 0 | None |
| trend | 0.24 | 13 | 1.943595169753235e-05 | 13 | 1.943595169753235e-05 | 0 | None |
| breakout | 0.1 | 5 | 0.0 | 14 | 0.0 | 9 | 0.0 |
| breakout | 0.14 | 5 | 0.0 | 7 | 0.0 | 2 | 0.0 |
| breakout | 0.18 | 5 | 0.0 | 5 | 0.0 | 0 | None |
| breakout | 0.2 | 5 | 0.0 | 5 | 0.0 | 0 | None |
| breakout | 0.22 | 5 | 0.0 | 5 | 0.0 | 0 | None |
| breakout | 0.24 | 5 | 0.0 | 5 | 0.0 | 0 | None |
| mean_reversion | 0.1 | 0 | None | 8 | -0.00120327268584916 | 8 | -0.00120327268584916 |
| mean_reversion | 0.14 | 0 | None | 5 | -0.0008561523489729481 | 5 | -0.0008561523489729481 |
| mean_reversion | 0.18 | 0 | None | 3 | -0.00142692058162158 | 3 | -0.00142692058162158 |
| mean_reversion | 0.2 | 0 | None | 1 | 0.03360617413240348 | 1 | 0.03360617413240348 |
| mean_reversion | 0.22 | 0 | None | 1 | 0.03360617413240348 | 1 | 0.03360617413240348 |
| mean_reversion | 0.24 | 0 | None | 0 | None | 0 | None |

## PriceAction Subset Removal

- Count: 143
- Avg shadow-minus-baseline: 0.005570930285283932
- Positive lift rate: 0.6153846153846154
- Labels: {'avoided_loss': 88, 'missed_win': 55}
