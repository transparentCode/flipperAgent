# RegimeV2 Phase 6C Activation Diagnostics

## Summary

- Records: 320
- Gate active: 14 (0.04375)
- Gate inactive: 306
- Selection changed: 144
- Gate-active changed: 5
- Target candidate absent: 143 (0.446875)
- Missing policy context: 0

## Playbook Diagnostics

| Playbook | Active | Allowed | Score pass | Allow+score pass | Avg score | Floor |
|---|---:|---:|---:|---:|---:|---:|
| trend | 13 | 13 | 13 | 13 | 0.036203125 | 0.24 |
| breakout | 5 | 5 | 5 | 5 | 0.0114625 | 0.24 |
| mean_reversion | 0 | 0 | 0 | 0 | 0.006910625000000001 | 0.24 |

## Relaxed Floor Scenarios

| Floor | Potential active | Potential rate | Score-only active | Score-only rate | Trend | Breakout | MR |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.18 | 14 | 0.04375 | 21 | 0.065625 | 13 | 5 | 0 |
| 0.2 | 14 | 0.04375 | 15 | 0.046875 | 13 | 5 | 0 |
| 0.22 | 14 | 0.04375 | 14 | 0.04375 | 13 | 5 | 0 |
| 0.24 | 14 | 0.04375 | 14 | 0.04375 | 13 | 5 | 0 |

## Top Blockers

- breakout_allow_false: 306
- breakout_score_below_floor: 306
- mean_reversion_allow_false: 306
- mean_reversion_score_below_floor: 306
- trend_allow_false: 306
- trend_score_below_floor: 306
- no_target_candidate: 139
