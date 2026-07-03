# RegimeV2 Phase 7M Follow-Through Transition Robustness

## Scope

- Assets/timeframes: BNBUSDT|1h, ETHUSDT|1h, BTCUSDT|1h
- Input rows per asset: 720
- Windows: full 720 rows plus rolling 360-row windows [0:360], [180:540], [360:720]
- Thresholds: 0.25, 0.30
- Target splits: 1, 2, 3, 4
- Actions: reverse_direction, suppress
- Total variants: 192
- Runtime posture: offline-only / diagnostic-only

## Summary

- Recommendation: hold_off_transition_rule_not_robust
- Robust-ready reports: 0/3
- Reusable-signature reports: 0/3
- Ready variants: 2/192
- Applied variants: 38/192
- Best report: BNBUSDT|1h
- Best report ready rate: 0.03125
- Best report non-full ready rate: 0.0

## Per-asset result

| Asset | Timeframe | Variants | Ready | Applied variants | Ready rate | Non-full ready rate | Applied support | Recommendation |
|---|---|---:|---:|---:|---:|---:|---:|---|
| BNBUSDT | 1h | 64 | 2 | 20 | 0.03125 | 0.0 | 20 | hold_off_transition_rule_not_robust |
| ETHUSDT | 1h | 64 | 0 | 6 | 0.0 | 0.0 | 6 | hold_off_transition_rule_not_robust |
| BTCUSDT | 1h | 64 | 0 | 12 | 0.0 | 0.0 | 12 | hold_off_transition_rule_not_robust |

## BNBUSDT detail

The original 7L full-window result remains visible:

- Best ready variant: full window, target split 2, reverse_direction, threshold 0.25
- Active total: 10
- Applied rows: 1
- Passed splits: 4/4
- Avg split directional return: 0.00643033562055411
- Worst split directional return: 0.0003227611267069431

But robustness fails:

- Full-window ready variants: 2
- Rolling-window ready variants: 0
- Non-full ready rate: 0.0
- Ready by target split:
  - split 1: 0/16
  - split 2: 2/16
  - split 3: 0/16
  - split 4: 0/16
- Ready by action:
  - reverse_direction: 2/32
  - suppress: 0/32

## Interpretation

Phase 7L was a useful diagnostic discovery, but Phase 7M shows it is not a reusable rule yet. The clean 4/4 result depends on the full-window BNBUSDT split layout. Once the same signature is tested across rolling windows, adjacent target splits, suppress-vs-reverse action, and adjacent assets, it does not hold.

The right decision is to keep 7L as a diagnostic insight only. Do not promote it to a candidate descriptor or runtime rule.

## Next direction

Move to Phase 7N with a broader transition-regime feature redesign rather than trying to salvage the split-local 7L rule. The next candidate should learn/score transition signatures without hardcoded chronological splits, likely using features such as:

- reversal pressure persistence
- failed breakdown recovery
- compression expansion direction flip
- post-breakout continuation vs exhaustion
- transition confidence decoupled from 7F follow-through direction
