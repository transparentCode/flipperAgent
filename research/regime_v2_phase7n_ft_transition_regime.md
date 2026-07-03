# RegimeV2 Phase 7N Follow-Through Transition Regime

## Scope

- Assets/timeframes: BNBUSDT|1h, ETHUSDT|1h, BTCUSDT|1h
- Input rows per asset: 720
- Base path: Phase 7K context gate -> Phase 7F follow-through -> Phase 7N transition-regime score -> Phase 7H walk-forward
- Thresholds: 0.25, 0.30
- Actions: reverse_direction, suppress, tag_only
- Transition-edge thresholds: 0.10, 0.18, 0.25
- Runtime posture: offline-only / diagnostic-only

## Summary

- Recommendation: hold_off_transition_regime_unstable
- Variants: 54
- Ready variants: 0
- Best ready variant: none
- Best variant: BNBUSDT|1h threshold 0.25
- Best variant active total: 10
- Best variant flagged/applied: 0/0
- Best variant passed splits: 3/4
- Best variant avg split directional return: 0.0035751228597196783
- Best variant worst split directional return: -0.00765301617323444

## What 7N changed

Phase 7N removed the split-local 7L assumption and introduced a generic row-local transition score:

- continuation score: follow-through, hold, directional return, low reversal pressure, volume, context
- reversal score: reversal pressure, weak hold, weak directional return, weak follow-through, transition-friendly phase/horizon context
- transition edge: reversal score minus continuation score

A row is eligible only if it is already an active 7F confirmation and passes reversal, context, market phase, horizon bias, and transition-edge checks.

## Result

With default transition-edge thresholds, no row was flagged. The feature score concluded that even high-reversal rows still had stronger continuation evidence than reversal-transition evidence. Therefore the matrix effectively reproduced the 7K baseline and stayed unstable.

## Low-edge exploratory check

A deliberately permissive BNBUSDT-only run with `min_transition_edge=-0.25` was also tested to see whether the score was too conservative.

Result:

- Applied rows: 4
- Splits passed: 2/4
- Avg split directional return: 0.004263250991626486
- Worst split directional return: -0.004258271312009485
- Ready: false

This confirms the failure mode: forcing the generic transition rule can repair the old split-2 pocket, but it over-flips later rows and breaks split 3/4 stability.

## Interpretation

7N is not a candidate, but it is useful evidence. A simple row-local continuation-vs-reversal score is not enough to replace the split-local 7L finding. The transition problem likely needs a separate transition-state model, not a patch on top of 7F follow-through confirmations.

## Next direction

Move to Phase 7O as a separate transition-state prototype rather than continuing to mutate 7F confirmations. The next prototype should produce a distinct state such as `BREAKOUT_EXHAUSTION_TRANSITION` or `FAILED_BREAKOUT_REVERSAL_SETUP`, with its own outcome validation, instead of rewriting `BREAKOUT_CONFIRMATION` direction after the fact.
