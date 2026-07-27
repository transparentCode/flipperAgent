# Phase 15V.1 Architect-to-Coder Handoff

## Status

READY_FOR_TRENDLINE_V2_FINAL_VIEWER_IMPLEMENTATION

## Objective

Add one final display-only viewer mode, `Nearest now`, to Trendline V2. Show
the nearest five support and five resistance candidates by current completed
candle geometry, with an optional cap of ten per role and one representative
per exact second anchor.

This is display compression only. It is not model selection, quality scoring,
actionability ranking, prediction or trade advice.

## Repository boundary

```text
Base:
20ebe4d6c02f49e7bfa99d3e9468b2d266773a9e

Branch:
feature/trendline-v2-phase-15v1-nearest-now-finalization-v1
```

Use existing checkout. No worktree. No merge or push.

## Exact scope

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

Do not modify provider, discovery, tracking, interaction, selection runtime,
payload schema, runner, server, configuration, YAML, Regime, canonical
Trendlines, research scripts, evidence bundles, package manifests or locks.

## Display contract

```text
DisplayMode = nearest | focus | all
Nearest default = 5 per role
Nearest optional = 10 per role
Focus contract = 100 recent bars / 25 span / unique second anchor / 12 per role
All = original candidate array and order by identity
```

Nearest uses latest completed candle. Project linearly from candidate endpoints
without segment clamping. Support distance is `max(0, low - projected)`;
resistance distance is `max(0, projected - high)`. Tie order:

```text
range distance ascending
absolute close distance ascending
second confirmation position descending
validated intermediate count descending
anchor-source span descending
candidate ID ascending
```

Group independently by exact `candidate.anchors[1].anchor_id`, then cap role
lists and return support before resistance. Invalid duration or non-finite
geometry fails closed. No input array or candidate mutation.

## UI contract

Default mode is `Nearest now`; budget options are exactly `5` and `10`.
Nearest hides and disables Focus-specific controls. Focus preserves all current
controls and reset behavior. All raw hides and disables all density-specific
controls. Diagnostic payloads bypass density controls and render exact lines.

Wording must remain display-only and must not imply quality, strength,
actionability, recommendation or prediction.

## Acceptance

- Unit tests cover projection, role distance, all deterministic tie-breaks,
  anchor suppression, caps, dispatch, Focus parity, All identity, invalid
  geometry, UI labels and disabled controls.
- Guarded frozen four-asset tests validate payload IDs, file hashes, raw counts,
  exact nearest counts, selection digests, Focus counts and immutability.
- Build updates only `dist/candidate_filter.js` and `dist/main.js` for commit.
- Existing diagnostic viewer behavior remains unchanged.

## Validation

```bash
cd src/libs/models/trendline_v2/tools/viewer/web
npm test
TRENDLINE_V2_VERIFY_NEAREST_VIEWER_EVIDENCE=1 npm test

cd /Users/aloobhujia/flipperAgent
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_v2/tools/viewer \
  tests/scripts/test_run_trendline_v2_viewer.py -q -ra
PYTHONPATH=src .venv/bin/python \
  scripts/analyze_trendline_v2_actionable_interaction_shortlist.py --verify
PYTHONPATH=src .venv/bin/python -m pytest tests/models/trendline_v2 -q -ra
PYTHONPATH=src .venv/bin/python -m pytest src/libs/models/trendlines/tests -q -ra
ruff check src/libs/models/trendline_v2 tests/models/trendline_v2 \
  tests/scripts/test_run_trendline_v2_viewer.py
PYTHONPATH=src .venv/bin/python -m compileall -q src/libs/models/trendline_v2
git diff --check
```

Network, provider, holdout, temporal and evidence regeneration remain
prohibited. Return `READY_FOR_TRENDLINE_V2_FINAL_VIEWER_CLOSEOUT_REVIEW` only
after all mandatory non-browser gates pass.
