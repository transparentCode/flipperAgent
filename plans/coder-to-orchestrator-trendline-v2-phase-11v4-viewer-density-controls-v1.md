# Coder Handoff: Phase 11V.4 Viewer Density Controls

## Result

`READY_FOR_TRENDLINE_V2_VIEWER_DENSITY_CONTROL_REVIEW`

Branch: `research/trendline-v2-phase-11v4-viewer-density-controls-v1`

Base: `83ea26308aad380d0d772505650be5744e09b5f0`

Implementation is frontend-only display filtering. Provider outputs, payload schema, evidence, model selection and frozen Binance bundles are unchanged.

## Implementation

- Added pure `candidate_filter.ts` with exact Focus defaults and deterministic evidence-based selection.
- Added explicit All raw mode returning original candidate array and order.
- Added accessible density controls, raw/filtered counts and display-only disclaimer.
- Added `TrendlinePrimitive.setCandidates()` for redraw, hit-test and autoscale replacement without primitive reconstruction.
- Selection clears when filtered candidate leaves display set.
- Diagnostic R5 payload keeps exact two-line rendering and hides density controls.

## Frozen real-output acceptance

| Output | Raw | Focus support | Focus resistance | Focus total | All raw restored |
|---|---:|---:|---:|---:|---:|
| BTCUSDT 4h | 3077 | 10 | 12 | 22 | 3077 |
| ETHUSDT 1h | 2991 | 12 | 9 | 21 | 2991 |
| SUIUSDT 30m | 2496 | 12 | 12 | 24 | 2496 |
| SOLUSDT 1d | 198 | 9 | 8 | 17 | 198 |

All raw selections preserved original array identity. Existing payload and bundle files were not rewritten.

## Validation

- Frontend `npm ci && npm test`: `32 passed`, `0 vulnerabilities`.
- Existing viewer Python: `69 passed`.
- Generic runner: `40 passed`.
- Full Trendline V2: `1087 passed, 38 skipped`.
- Canonical plural Trendlines: `493 passed`.
- Ruff: passed.
- Compileall: passed.
- `git diff --check`: passed.

No Binance, provider, evaluator or evidence-generation execution occurred. Viewer server stopped.

## Protected boundary

Phase 11V.3 output root remains read-only:

`/tmp/trendline_v2_phase11v3_binance_viewer_acceptance/20260726/`

No commit, merge or push is authorized by this phase.
