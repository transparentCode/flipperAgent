# RegimeV2 Phase 8B Orchestration Shadow Report

## Orchestration posture

- Orchestration attached: True
- Orchestration rows: 2160
- Routeable base-state rows: 164
- Transition postures: ['frozen_diagnostic']
- Transition runtime-enabled rows: 0
- Transition promotion-ready count: 0
- Runtime action: base_shadow_report_with_transition_diagnostics_frozen
- Recommended next step: resume_base_playbook_orchestration_and_shadow_reporting

## Shadow replay summary

- Records after filter: 720
- Selection changed: 197
- Gate active: 47

# RegimeV2 Phase 5 Shadow Replay Report

## Summary

- Source: logs/regime_v2_shadow_decisions.jsonl
- Records read: 720
- Invalid records: 0
- Records after filter: 720
- Selection changed: 197 (0.27361111111111114)
- Gate active: 47 (0.06527777777777778)
- Gate-active changed: 15 (0.3191489361702128)
- Gate-inactive changed: 182 (0.2704309063893016)
- Inactive-policy changed: 182 (0.27245508982035926)
- Subset-only changed: 185
- PriceAction subset exclusions: 185
- Missing RegimeV2 payload: 0
- Inactive policy: 668
- No active playbook: 668
- Avg edge delta: -0.002960043904419228
- Avg confidence: 0.496763846719646
- Avg uncertainty: 0.5828614580566

## Active Playbooks

- breakout: 7
- mean_reversion: 7
- none: 668
- trend: 42

## Changed Pick Groups

| Baseline | Shadow | Count | Avg edge delta |
|---|---|---:|---:|
| PriceAction | none | 185 | None |
| Momentum | none | 6 | None |
| RegimePullbackScorer | Momentum | 5 | -0.3125806363066705 |
| RegimePullbackScorer | none | 1 | None |

## Model Pair Summary

| Baseline | Shadow | Count | Changed rate | Avg edge delta |
|---|---|---:|---:|---:|
| Momentum | Momentum | 420 | 0.0 | 0.0 |
| PriceAction | none | 185 | 1.0 | None |
| TrendFollowing | TrendFollowing | 85 | 0.0 | 0.0 |
| RegimePullbackScorer | RegimePullbackScorer | 17 | 0.0 | 0.0 |
| Momentum | none | 6 | 1.0 | None |
| RegimePullbackScorer | Momentum | 5 | 1.0 | -0.3125806363066705 |
| RegimePullbackScorer | none | 1 | 1.0 | None |
| SqueezeBreakout | SqueezeBreakout | 1 | 0.0 | 0.0 |
