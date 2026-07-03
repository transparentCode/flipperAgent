# RegimeV2 Phase 7E Breakout Confirmation Refinement

## Summary

- Asset/timeframe: BNBUSDT|1h
- Rows: 720
- Eligible rows: 326 (0.4527777777777778)
- Confirmed rows: 7 (0.009722222222222222)
- Promoted rows: 7 (0.009722222222222222)
- Avg confirmation score: 0.048374230094299954
- Avg confirmed score: 0.390411421685517

## Distributions

### base_state_distribution
- NO_TRADE_RISK: 351
- WAIT_COMPRESSION: 317
- SCALP_ONLY: 40
- BREAKOUT_SETUP: 9
- RANGE_REVERSION: 3

### refined_state_distribution
- NO_TRADE_RISK: 351
- WAIT_COMPRESSION: 313
- SCALP_ONLY: 40
- BREAKOUT_CONFIRMATION: 7
- BREAKOUT_SETUP: 6
- RANGE_REVERSION: 3

### confirmation_reason_distribution
- not_eligible_state: 394
- missing_break_direction: 311
- score_below_threshold: 8
- confirmed: 7

### confirmation_direction_distribution
- up: 5
- down: 2

## Recent confirmations

- 2026-06-07 05:00:00+00:00: direction=up, score=0.3512564577597243, base=WAIT_COMPRESSION, refined=BREAKOUT_CONFIRMATION, reason=confirmed
- 2026-06-07 08:00:00+00:00: direction=up, score=0.4459464126074731, base=BREAKOUT_SETUP, refined=BREAKOUT_CONFIRMATION, reason=confirmed
- 2026-06-11 08:00:00+00:00: direction=up, score=0.3569278992501104, base=WAIT_COMPRESSION, refined=BREAKOUT_CONFIRMATION, reason=confirmed
- 2026-06-20 05:00:00+00:00: direction=up, score=0.36747540508746557, base=WAIT_COMPRESSION, refined=BREAKOUT_CONFIRMATION, reason=confirmed
- 2026-06-22 13:00:00+00:00: direction=up, score=0.410428845827128, base=BREAKOUT_SETUP, refined=BREAKOUT_CONFIRMATION, reason=confirmed
- 2026-06-23 05:00:00+00:00: direction=down, score=0.38949611909642157, base=BREAKOUT_SETUP, refined=BREAKOUT_CONFIRMATION, reason=confirmed
- 2026-06-27 19:00:00+00:00: direction=down, score=0.41134881217029606, base=WAIT_COMPRESSION, refined=BREAKOUT_CONFIRMATION, reason=confirmed
