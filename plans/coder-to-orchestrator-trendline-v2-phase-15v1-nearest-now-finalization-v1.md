# Phase 15V.1 Coder Handoff

## Status

READY_FOR_TRENDLINE_V2_FINAL_VIEWER_CLOSEOUT_REVIEW

## Commit boundary

```text
Branch:
feature/trendline-v2-phase-15v1-nearest-now-finalization-v1

Base:
20ebe4d6c02f49e7bfa99d3e9468b2d266773a9e

Provider/network/legacy executions:
0 / 0 / 0

Holdout/temporal:
unopened / unopened
```

Exactly ten files are in scope:

```text
src/libs/models/trendline_v2/tools/viewer/web/src/candidate_filter.ts
src/libs/models/trendline_v2/tools/viewer/web/src/main.ts
src/libs/models/trendline_v2/tools/viewer/web/index.html
src/libs/models/trendline_v2/tools/viewer/web/dist/candidate_filter.js
src/libs/models/trendline_v2/tools/viewer/web/dist/main.js
src/libs/models/trendline_v2/tools/viewer/web/tests/candidate_filter.test.mjs
src/libs/models/trendline_v2/tools/viewer/web/tests/nearest_now_frozen_payloads.test.mjs
src/libs/models/trendline_v2/README.md
plans/architect-to-coder-trendline-v2-phase-15v1-nearest-now-finalization-v1.md
plans/coder-to-orchestrator-trendline-v2-phase-15v1-nearest-now-finalization-v1.md
```

## Implementation

`Nearest now` is default display mode. It selects independently by role, one
candidate per exact second-anchor ID, with maximum five per role or optional
maximum ten per role. Projection uses the infinite line through candidate
endpoints at the latest completed candle. Role-aware wick distance, close
distance, confirmation recency, intermediate count, anchor span and candidate
ID implement the frozen deterministic ordering.

`Focus` remains `100 / 25 / unique / 12` with prior membership semantics.
`All raw` returns original candidate array identity and order. Diagnostic R4/R5
payloads bypass density controls. No provider output, payload schema or stored
evidence changes.

UI defaults to `Nearest now`, exposes budget `5` or `10`, disables hidden mode
controls, preserves Focus reset behavior and uses display-only wording.

README records model purpose, non-goals, viewer modes and negative research
results from Phases 11S, 11R, 12Q, 13H and 14A.

## Frozen four-asset evidence

Frozen payload IDs and payload-file SHA-256 values remained unchanged:

```text
BTCUSDT 4h: 7a8ab2cb09b2bb13350fbe8ac9a74d297e3509612c02d7ab716bd70354a9f476
            1c3411c15bd82621e5d9465ab7ec761c549647bffd46229e8bfd4cc15d047380
ETHUSDT 1h: 6ac982e0e72a7642496480f41b0d808dff79688011bad94c127a862815cfcf00
            f4e85f7592ca47352441e819e972b6bd0f073c5cf60a0ac937c1743863d8bd84
SUIUSDT 30m: 29e3773c81ff0d76835fddaac860875b957009f0cca62b64f3a2c1b4c7defccf
             3fef0042f55cf3e4d5d262d920f3e3fdba8ff95f1468ea3459d887beed42769f
SOLUSDT 1d: ad7bd16ca7a2fc7bd41ea12cb4cf483da6e2a1b94658067dda44da292bb56902
            79a12086373a31d64133f2dbf2e3153ecf6514138f555439d1824c81c1b4f6dd
```

Raw candidate counts: `3077 / 2991 / 2496 / 198`. Nearest counts for both
budgets: exactly `5+5` and `10+10` support/resistance. Focus counts remain:

```text
BTCUSDT 4h  10 support / 12 resistance
ETHUSDT 1h  12 support /  9 resistance
SUIUSDT 30m 12 support / 12 resistance
SOLUSDT 1d   9 support /  8 resistance
```

Selection digests, computed over case, budget and ordered support/resistance
IDs:

```text
BTCUSDT 4h:  budget 5  be17e3f7972d4fd78a992540c450ee477b57c546fadc95d017cfb4f547c0a7c2
             budget 10 19f844d84414a54b359fac37b14d4ee0a64b54405262a74e78511b79b89e5b13
ETHUSDT 1h:  budget 5  e1e9c73933cc67505048530de81d39e433f4094f61d15be8a8081f35ca0b8046
             budget 10 806f564106aeb55ac042cc43b39536e75883ed05a6f99b41e6d240e2fbf67c36
SUIUSDT 30m: budget 5  f67d8eba580d179462ca5a380857c91cb0600e79c57b960de9b956c582e56860
             budget 10 d2d8f9e655333b7c1a8b4563c144aea19f7308e0aed40d7fecba4e6dd8cc1148
SOLUSDT 1d:  budget 5  783011aae86e2f74dede9f09dc1a25326b6a560f7fd3fcdcb0c2fa6dfb16d267
             budget 10 08c4a59cb61480900d7e13c1c0463141d9034939be708dd8efe56b50e1408502
```

## Validation

```text
Web unit suite:             54 passed, 4 skipped
Frozen external web suite:  58 passed
Viewer Python + runner:     76 passed
Full Trendline V2:          327 passed
Canonical Trendlines:       493 passed
Phase 14A verifier:         passed
Phase 14 inventory:         08e9a15b88e018aebbc7b3a8f6f1d72ca21353cec8b3f232dfcd2b81eefbd2ec
Retained viewer outputs:    4 / 4 verified
Ruff:                       passed
Compileall:                 passed
Diff check:                 passed
```

Retained output verification preserved original payload hashes and candidate
counts. No bundle regeneration occurred.

HTTP smoke against frozen BTCUSDT 4h bundle, server stopped after check:

```text
200 /                         text/html
200 /styles.css               text/css
200 /dist/main.js             text/javascript
200 /dist/candidate_filter.js text/javascript
200 /bundle/chart_payload.json application/json
404 /manifest.json
```

Browser-level inspection was unavailable. No visual browser claim made.

Codebase-memory reindex was attempted and failed on contained worker crash;
existing split indexes remained intact. GitNexus reported stale metadata.

## Final boundary

No network, provider, research, evidence, YAML, runtime, canonical Trendlines,
holdout or temporal changes occurred. Commit is authorised after exact ten-file
staging. Merge and push remain unauthorised.
