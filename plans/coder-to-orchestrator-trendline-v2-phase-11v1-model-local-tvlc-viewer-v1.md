# Trendline V2 Phase 11V.1: Model-Local TVLC Diagnostic Viewer

## Status

APPROVED_FOR_COMMIT

Implementation is complete and independently reviewed. Commit is authorized;
no provider, network, R3B, R4, R5, selector, runtime or production
configuration path was changed.

## Work Completed

- Relocated the existing viewer from `src/apps/trendline_v2_viewer/` to
  `src/libs/models/trendline_v2/tools/viewer/`.
- Relocated viewer tests to
  `tests/models/trendline_v2/tools/viewer/`.
- Updated canonical consumer imports and manual serve instructions.
- Preserved provider payload and bundle schemas:
  `trendline_v2_viewer_payload_v1` and `trendline_v2_viewer_bundle_v1`.
- Added strict R4/R5 source-backed diagnostic payload and two-file bundle
  export/verification.
- Added frontend dispatch for provider and diagnostic payload schemas.
- Added diagnostic labels, finite projected segments, anchors, reachability,
  R5 attribution and non-promotion banner.

## Frozen Diagnostic Evidence

Target: BTCUSDT 4h, support, budget 1, checkpoint 5,
`2026-06-09T00:00:00Z`.

Bundle:
`/tmp/trendline_v2_phase11v1_model_local_tvlc_viewer/20260522_20260701/btcusdt_4h_support_budget1_checkpoint5`

```text
status: R5_DIAGNOSTIC_VIEWER_VERIFIED
payload_id: 824a74133a13293e4e0c7e35907da77862d2a96eb6bd299b62cd1462b4feba9c
bundle_id: d27575fc5043549458f9ed6c101c7eb4a842ffc402a6acedc88f80eecb05b167
files: 2
manifest members: 1
causal candles: 108
lines: 2
```

Protected bindings:

```text
R4 diagnostic: f4a95e118d52eec9ae60b447f08ca11a756908d7861772978b8f0393b0bbd2e2
R4 manifest:   965b4741ec0f7305b8217dbc90d5c2bb31a6185e09b42c519bc404548c290a7e
R4 inventory:  7fbd19fd1b828c09881df6236d2c3b8bdf7ae4bdfd4cd4b03d770c401ecd413c
R5 attribution:b918a2102f82670da9fbd365daa9b35d7ec86d5bfb043db149b412f57b25f083
R5 manifest:   f5569cca5cafe8f4b598a8e4a9e1609fcefc70f89cc90078d21c8f5c0dabc917
R5 inventory:  7fcde0786d367adb0dafbe9fe54349005e69d6cc33f14407477bee534a38d31e
Raw candle:   0fb88993e8ceed7b3812ec8fed895164b4fd00d1d392f5018f81aeea66dd4fe3
```

R5 cell:

```text
(joint_incumbent_near_v1, 1, joint_nearest_projection_control_v1,
 btcusdt_4h, 5, support, 96)
direction: control_only
attribution: FULL_LINEAGE_SUBSTITUTION
cross-budget: PERSISTENT_THROUGH_BUDGET_3
```

## Validation

```text
Viewer Python suite:       36 passed
Trendline V2:             294 passed
Trendline Family:         400 passed
Dependent scripts/API:     57 passed
Node/TypeScript:           15 passed
Ruff:                      passed
Compileall:                passed
git diff --check:          passed
HTTP smoke:                allowlisted assets 200; /manifest.json 404
Strict diagnostic verify: R5_DIAGNOSTIC_VIEWER_VERIFIED
```

## Boundaries

- `src/apps/trendline_v2_viewer/` and `tests/apps/trendline_v2_viewer/` are
  absent; no compatibility package remains.
- No tracked `node_modules/` or `dist/` files.
- Historical plans unchanged.
- Frozen R4/R5/raw source bundles unchanged and read-only.
- No automatic browser launcher; manual URL:
  `http://127.0.0.1:8765`.
- Local loopback server is running for manual inspection during this review.

## Closeout Decision

Phase 11V.1 relocation, provider-schema parity, diagnostic source binding,
visual labels and HTTP evidence are approved. Commit is authorized. Merge,
push, runtime promotion and further viewer integration remain unauthorized.
