# RegimeV2 Phase 7B Playbook State Machine Report

## Summary

- Asset/timeframe: BNBUSDT|1h
- Rows: 720
- Executable rate: 0.059722222222222225
- Wait rate: 0.4513888888888889
- Risk/no-trade rate: 0.4888888888888889
- Average risk score: 0.5308023611111111
- Average conflict count: 0.9069444444444444

## Distributions

### state_distribution
- NO_TRADE_RISK: 352
- WAIT_COMPRESSION: 316
- SCALP_ONLY: 40
- BREAKOUT_SETUP: 9
- RANGE_REVERSION: 3

### state_group_distribution
- risk: 352
- wait: 325
- executable: 43

### reason_distribution
- risk_blocked: 352
- compression_wait: 316
- scalp_only_context: 40
- pre_breakout_setup: 9
- range_reversion_context: 3

### dominant_playbook_distribution
- scalping: 631
- none: 84
- mean_reversion: 5

### horizon_bias_distribution
- none: 352
- wait_for_expansion: 316
- mid: 44
- short_to_mid: 8

## Recent states

- 2026-07-02 23:00:00+00:00: state=NO_TRADE_RISK, reason=risk_blocked, playbook=scalping, horizon=none
- 2026-07-03 00:00:00+00:00: state=NO_TRADE_RISK, reason=risk_blocked, playbook=scalping, horizon=none
- 2026-07-03 01:00:00+00:00: state=NO_TRADE_RISK, reason=risk_blocked, playbook=scalping, horizon=none
- 2026-07-03 02:00:00+00:00: state=NO_TRADE_RISK, reason=risk_blocked, playbook=scalping, horizon=none
- 2026-07-03 03:00:00+00:00: state=SCALP_ONLY, reason=scalp_only_context, playbook=scalping, horizon=mid
- 2026-07-03 04:00:00+00:00: state=SCALP_ONLY, reason=scalp_only_context, playbook=scalping, horizon=mid
- 2026-07-03 05:00:00+00:00: state=SCALP_ONLY, reason=scalp_only_context, playbook=scalping, horizon=mid
- 2026-07-03 06:00:00+00:00: state=WAIT_COMPRESSION, reason=compression_wait, playbook=scalping, horizon=wait_for_expansion
- 2026-07-03 07:00:00+00:00: state=WAIT_COMPRESSION, reason=compression_wait, playbook=scalping, horizon=wait_for_expansion
- 2026-07-03 08:00:00+00:00: state=WAIT_COMPRESSION, reason=compression_wait, playbook=scalping, horizon=wait_for_expansion
