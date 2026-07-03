# RegimeV2 Phase 7Y Transition Micro-State Context Tag Diagnostics

## Scope

- Assets/timeframes: BNBUSDT|1h, ETHUSDT|1h, BTCUSDT|1h
- Input rows per asset: 720
- Source: Phase 7V/7W micro-state windows
- Runtime posture: offline-only / diagnostic-only

## Goal

Phase 7X showed that BNB/BTC have supported mixed windows where compression temporarily beats breakout setup. Phase 7Y tests whether policy-safe pre-outcome features can explain those windows.

Features considered:

- breakout/compression active counts
- compression share of active transition candidates
- transition score mean
- continuation score mean
- transition score-gap mean where available
- setup volatility mean where available

Outcome-derived labels were not used as candidate policy rules.

## Summary

- Assets: BNBUSDT, ETHUSDT, BTCUSDT
- Mixed windows: 3
- Candidate context tags found: 0
- Recommendation: no_context_tag_found

## Asset result

| Asset | Mixed windows | Passing windows | Support-thin | Candidate tags | Top tag |
|---|---:|---:|---:|---:|---|
| BNBUSDT | 2 | 2 | 0 | 0 | none |
| ETHUSDT | 0 | 3 | 1 | 0 | none |
| BTCUSDT | 1 | 3 | 0 | 0 | none |

## Window observations

### BNBUSDT

Mixed windows:

- `w1_0_360`: breakout active 22, compression active 21, breakout score 0.7555, compression score 0.7035
- `w2_180_540`: breakout active 18, compression active 20, breakout score 0.7366, compression score 0.7182

The failure windows do not show compression count dominance or compression score advantage. Breakout score is not obviously weak.

### BTCUSDT

Mixed window:

- `w2_180_540`: breakout active 21, compression active 9, breakout score 0.7178, compression score 0.7299

Compression score is slightly higher, but not enough to be a robust tag under the default threshold. Compression is not count-dominant.

### ETHUSDT

No supported mixed failure windows. The only weak window is support-thin:

- `w3_360_720`: breakout active 5, compression active 26

This confirms 7W's ETH issue is support quantity, not a supported mixed failure.

## Interpretation

No clean policy-safe context tag was found for the supported mixed windows.

This is an important result:

1. BNB/BTC mixed windows are not explained by simple pre-outcome count dominance.
2. They are not explained by simple compression score advantage.
3. ETH remains different: it is support-thin rather than mixed-failing.
4. Adding a filter here would likely overfit or rely on outcome-derived behavior.

## Decision

Do not add a context filter from 7Y.

Keep transition micro-states diagnostic-only.

## Next direction

Move to Phase 7Z: transition feature enrichment or stop-gate decision.

Options:

1. Stop-gate: freeze transition micro-state work as diagnostic evidence and return to broader regime/playbook integration.
2. Feature enrichment: add new historical-only features that may better explain mixed windows, such as short-term realized expansion, range slope, wick asymmetry, compression age, and local trend slope.

Recommended next step: stop-gate or feature enrichment decision before adding more rules.
