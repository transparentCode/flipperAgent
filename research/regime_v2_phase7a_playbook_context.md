# RegimeV2 Phase 7A Playbook Context Report

## Summary

- Asset/timeframe: BNBUSDT|1h
- Rows: 720
- Active context rate: 0.5083333333333333
- Confirmed context rate: 1.0
- Average risk score: 0.5322576388888889
- Average conflict count: 0.9069444444444444

## Distributions

### dominant_playbook
- scalping: 631
- none: 84
- mean_reversion: 5

### market_phase
- uncertain_no_trade: 327
- compressed_wait: 177
- breakout_setup: 146
- neutral_context: 40
- shock_no_trade: 27
- range_reversion: 3

### risk_state
- ok: 361
- blocked: 354
- watch: 5

### horizon_bias
- none: 354
- wait_for_expansion: 314
- mid: 44
- short_to_mid: 8

### context_alignment
- neutral_or_missing: 720

### recommended_next_step
- skip_or_reduce_until_risk_clears: 354
- observe_or_shadow_only: 185
- watch_for_breakout_expansion: 177
- mean_reversion_candidate: 4

### top_conflict_tags
- compression_without_breakout: 333
- uncertainty_high: 320

## Recent context

- 2026-07-02 22:00:00+00:00: phase=uncertain_no_trade, playbook=scalping, risk=blocked, horizon=none, next=skip_or_reduce_until_risk_clears
- 2026-07-02 23:00:00+00:00: phase=uncertain_no_trade, playbook=scalping, risk=blocked, horizon=none, next=skip_or_reduce_until_risk_clears
- 2026-07-03 00:00:00+00:00: phase=uncertain_no_trade, playbook=scalping, risk=blocked, horizon=none, next=skip_or_reduce_until_risk_clears
- 2026-07-03 01:00:00+00:00: phase=uncertain_no_trade, playbook=scalping, risk=blocked, horizon=none, next=skip_or_reduce_until_risk_clears
- 2026-07-03 02:00:00+00:00: phase=uncertain_no_trade, playbook=scalping, risk=blocked, horizon=none, next=skip_or_reduce_until_risk_clears
- 2026-07-03 03:00:00+00:00: phase=neutral_context, playbook=scalping, risk=ok, horizon=mid, next=observe_or_shadow_only
- 2026-07-03 04:00:00+00:00: phase=neutral_context, playbook=scalping, risk=ok, horizon=mid, next=observe_or_shadow_only
- 2026-07-03 05:00:00+00:00: phase=neutral_context, playbook=scalping, risk=ok, horizon=mid, next=observe_or_shadow_only
- 2026-07-03 06:00:00+00:00: phase=compressed_wait, playbook=scalping, risk=ok, horizon=wait_for_expansion, next=watch_for_breakout_expansion
- 2026-07-03 07:00:00+00:00: phase=compressed_wait, playbook=scalping, risk=ok, horizon=wait_for_expansion, next=watch_for_breakout_expansion
