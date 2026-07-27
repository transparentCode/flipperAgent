# Phase 11V.4 Viewer Density Controls

## Status

`READY_FOR_TRENDLINE_V2_VIEWER_DENSITY_CONTROL_REVIEW`

## Objective

Add deterministic display-only Focus filtering to the Trendline V2 TVLC viewer. Preserve the complete provider candidate payload and provide an explicit All raw mode.

## Frozen behavior

Focus defaults:

- confirmation age: `100` bars, measured from the second confirmation position to the final candle position;
- minimum anchor span: `25` bars, measured from source positions;
- one representative per `(role, second_anchor_id)` group;
- maximum `12` candidates per role;
- stable support-then-resistance output ordering.

Representative and display ordering use only validated evidence fields: intermediate count, source-position span, confirmation position, and candidate ID. All raw mode returns the original candidate array without filtering, sorting, or copying.

R5 diagnostic payloads remain unchanged: two lines, original order, original styles and projection whitespace. Density controls are hidden for diagnostic payloads.

## Scope

Added:

- `src/libs/models/trendline_v2/tools/viewer/web/src/candidate_filter.ts`
- `src/libs/models/trendline_v2/tools/viewer/web/tests/candidate_filter.test.mjs`
- this architect handoff;
- `plans/coder-to-orchestrator-trendline-v2-phase-11v4-viewer-density-controls-v1.md`

Modified:

- `src/libs/models/trendline_v2/tools/viewer/web/index.html`
- `src/libs/models/trendline_v2/tools/viewer/web/styles.css`
- `src/libs/models/trendline_v2/tools/viewer/web/src/main.ts`
- `src/libs/models/trendline_v2/tools/viewer/web/src/trendline_primitive.ts`
- `src/libs/models/trendline_v2/tools/viewer/web/tests/trendline_primitive.test.mjs`

No provider, payload contract, runner, server, diagnostic exporter, model, configuration, evidence or Binance output changes.

## Acceptance

Frozen Phase 11V.3 outputs remain read-only. Compiled filter results are:

| Output | Raw | Focus support | Focus resistance | Focus total |
|---|---:|---:|---:|---:|
| BTCUSDT 4h | 3077 | 10 | 12 | 22 |
| ETHUSDT 1h | 2991 | 12 | 9 | 21 |
| SUIUSDT 30m | 2496 | 12 | 12 | 24 |
| SOLUSDT 1d | 198 | 9 | 8 | 17 |

All raw restores `3077`, `2991`, `2496`, and `198` candidates with original array identity.

## Non-goals

No provider pruning, quality scoring, ATR ranking, payload rewriting, selected-line persistence, YAML/runtime configuration, model promotion, or new network acquisition.
