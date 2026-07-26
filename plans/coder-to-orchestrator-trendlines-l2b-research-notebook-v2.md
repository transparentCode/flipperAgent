# L2-B V2 — Package-Local Research Notebook and TVLC Viewer

## 1. Disposition

Implementation is complete and validated. Direct browser evidence confirms visual smoke, layer toggles and console-clean interaction. Static HTTP smoke passed.

Disposition:

```text
READY_FOR_L2C_REAL_MARKET_VISUAL_VALIDATION
```

## 24. L2-B-R4 signal-schema remediation

The next browser attempt reached payload validation and exposed a heterogeneous-row validation defect: signal rows were incorrectly processed by the line/ray geometry branch. Canonical signal rows intentionally have no `start_position`, `end_position`, `start_time` or `end_time` fields.

Fix applied:

```text
src/libs/models/trendlines/research_viewer/web/src/contracts.ts
src/libs/models/trendlines/research_viewer/web/tests/payload.test.mjs
```

Lines and rays now share only geometry validation. Signals have a separate exact-key and semantic-validation path covering signal identities, ordinal, direction, confidence, source/name, metadata and selected signal binding. No geometry fields were added to signals.

Added four Node tests:

```text
accepts a non-empty canonical signal without geometry fields
rejects geometry fields on a signal
rejects malformed signal identity
accepts a fully populated mixed payload
```

R4 validation:

```text
Package-local Python: 30 passed
Node/TypeScript:      23 passed
Canonical trendlines: 465 passed
Ruff/compileall:       passed
git diff --check:      passed
```

A fresh signal-enabled synthetic viewer session started successfully and printed:

```text
http://127.0.0.1:52715/
```

Browser connection retry result:

```text
agent.browsers.list() == []
```

The session was closed cleanly. Browser visual inspection remains unavailable, so chart rendering after R4 cannot be independently confirmed in this environment.

```text
BLOCKED_L2B_VISUAL_SMOKE
```

## 25. Final visual smoke and L2-B checkpoint

Supplied browser evidence confirms:

```text
candles and chart scales: rendered
support/resistance geometry: rendered
fitted lines: solid and visible
boundary rays: dashed and visible
pivots/signals/selected marker: rendered
finality banner: populated
identity and diagnostic panels: populated
replay timeline: populated
```

Layer checks:

```text
fitted lines disabled: dashed boundary rays remained visible
boundary rays disabled: fitted lines remained visible
fit content and all layer toggles: no browser console errors
```

Final validation:

```text
Package-local Python: 30 passed
Node/TypeScript:      23 passed
Canonical trendlines: 465 passed
Consumer/ingestion:   71 passed
Offline workflows:    20 passed
Provider calls:       0
Ruff/compileall:       passed
Diff-check:            passed
Visual rendering:      passed
```

Committed checkpoint:

```text
79acc91 feat: add trendline research notebook viewer
```

Worktree is clean. Next phase:

```text
L2-C — Bounded real-market data run followed by notebook and TVLC evidence validation
```

## 2. Starting checkpoint

- Branch: `research/legacy-trendlines-quality-stability-v1`
- Starting commit: `387ec39 feat: add causal trendline research replay`
- Worktree was clean before L2-B edits.

## 3. Package-local viewer architecture

Viewer code lives only under `libs.models.trendlines.research_viewer`. It consumes validated L2-A2 replay/evidence contracts and does not implement extraction, fitting, boundary construction, signals, history, replay, data loading or configuration resolution.

No generic `src/apps/trendlines_research_viewer` package was created.

## 4. Dependency-boundary evidence

Import-boundary tests enforce:

- core trendlines and `workflows.research` do not import `research_viewer`;
- viewer code does not import `apps.*`, `app.*`, RegimeV2, Trendline V2, Plotly, Matplotlib, Seaborn, Jupyter or IPython;
- root `libs.models.trendlines` does not import the viewer.

Notebook-only IPython display use remains outside the viewer package.

## 5. Notebook modes and safety

Default notebook mode is deterministic synthetic smoke:

- purpose: `SMOKE`;
- data mode: `SYNTHETIC`;
- asset: `BTCUSDT`;
- timeframes: `1h`, `4h`;
- primary timeframe: `1h`;
- signals enabled;
- provider calls disabled;
- inline viewer enabled;
- permanent export disabled.

Notebook contains no model parameter values, installation cells, shell data-fetch commands, retired imports or YAML writes. Outputs are cleared and execution counts are null.

## 6. Provider-call guard

Binance mode requires all of:

- purpose `RESEARCH`;
- `provider_calls_authorized=True`;
- explicit loader.

Guard runs before loader invocation. Synthetic and injected modes require no provider authorization. Tests use fake adapters only; provider call count was zero.

## 7. Viewer payload identity

`trendlines_research_viewer_payload_v1` validates exact top-level and nested keys, lowercase SHA-256 identities, finite numeric values, selected-coordinate bindings, finality, no future candles and deterministic `payload_id`.

Payload binds dataset, research configuration, replay, source, checkpoint, content, replay point, fit/boundary/signal identities, display window, candles, geometry, pivots, signals, summary and timeline.

`display_window_id` is separate from model `source_id`; it binds the bounded chart window and never claims to be the model prefix.

## 8. Viewer bundle

`trendlines_research_viewer_bundle_v1` contains only:

```text
manifest.json
chart_payload.json
```

Bundle APIs enforce sorted UTF-8 JSON, newline termination, no non-finite values, exact members, no symlinks, stale-member detection, payload-ID verification and bundle-ID verification. Evidence export remains explicit; replay/session setup does not write permanent artifacts automatically.

## 9. Loopback server and session lifecycle

Package-local server provides:

- loopback-only bind;
- explicit URL allowlist;
- traversal and symlink rejection;
- bundle validation before bind;
- `Cache-Control: no-store`;
- ephemeral port support.

`TrendlinesResearchViewerSession` owns temporary storage when needed, starts a daemon thread, exposes the actual URL, closes and joins explicitly, cleans temporary files and is idempotently closeable.

## 10. Web viewer

Local `lightweight-charts` version is pinned to `5.2.0`. Viewer renders candles, fitted line segments, boundary rays, pivots, selected candle, signal markers, crosshair, controls, fit-content action, identity audit, timeline, geometry details and textual finality warning. `attributionLogo: true` is set.

Fractal displays `CONFIRMED / APPEND-ONLY`; RDP displays `RETROSPECTIVE / RESEARCH ONLY`.

## 11. Tests

Package-owned Python tests: `25 passed`.

New Node tests: `12 passed`.

Notebook structural and top-to-bottom execution tests passed within the package suite. Explicit evidence and viewer export round-trip is covered.

## 12. Notebook execution

Synthetic notebook-support execution completed without provider calls. It prepared data/configuration, ran causal replay, built evidence, built payload, wrote a temporary bundle, started and closed a loopback session, and removed temporary files.

Measured default smoke execution without server startup: approximately `0.63 s`; server construction measured approximately `20.9 ms`.

## 13. Manual visual smoke

Static HTTP smoke passed against a generated synthetic bundle on `127.0.0.1:8766`:

- `/` returned `200`;
- `/styles.css` returned `200`;
- `/dist/main.js` returned `200`;
- `/vendor/lightweight-charts.mjs` returned `200`;
- `/bundle/chart_payload.json` returned `200`;
- responses included `Cache-Control: no-store`.

Browser inspection could not run. Browser setup returned `No browser is available`; `agent.browsers.list()` returned `[]`. Therefore candle ordering, toggles, geometry alignment, visible finality warning and console-error state remain unverified by visual browser inspection.

## 14. Performance

Deterministic synthetic fixture: `BTCUSDT`, `1h`, seed `11`, `512` bars, boundary-only replay, positions `19..511`, `493` executed and recorded points.

Measured:

```text
boundary replay                 13.142 s
viewer payload build             242.99 ms
bundle build                     123.68 ms
bundle semantic validation        58.21 ms
payload JSON size             413,813 bytes
```

Acceptance thresholds passed:

- 512-prefix boundary replay <= 20 s;
- payload build <= 250 ms;
- bundle validation <= 100 ms;
- payload <= 5 MB.

No model execution occurs during payload construction, bundle validation or table construction.

## 15. Regression validation

```text
Canonical trendlines:       460 passed
Mocked Binance bridge:        8 passed
Consumer/ingestion matrix:   79 passed
Offline workflows:           20 passed
New viewer Node tests:       12 passed
Trendline V2 Python viewer:  23 passed
Trendline V2 Node tests:     13 passed
Targeted Ruff:               passed
Compileall:                  passed
git diff --check:            passed
```

Canonical collection reported `460 tests collected`.

## 16. Files changed

Authorized L2-B additions:

```text
research/trendlines_research_lab.ipynb
src/libs/models/trendlines/research_viewer/__init__.py
src/libs/models/trendlines/research_viewer/contracts.py
src/libs/models/trendlines/research_viewer/payload.py
src/libs/models/trendlines/research_viewer/bundle.py
src/libs/models/trendlines/research_viewer/server.py
src/libs/models/trendlines/research_viewer/notebook_support.py
src/libs/models/trendlines/research_viewer/README.md
src/libs/models/trendlines/research_viewer/web/index.html
src/libs/models/trendlines/research_viewer/web/styles.css
src/libs/models/trendlines/research_viewer/web/package.json
src/libs/models/trendlines/research_viewer/web/package-lock.json
src/libs/models/trendlines/research_viewer/web/tsconfig.json
src/libs/models/trendlines/research_viewer/web/src/contracts.ts
src/libs/models/trendlines/research_viewer/web/src/payload.ts
src/libs/models/trendlines/research_viewer/web/src/main.ts
src/libs/models/trendlines/research_viewer/web/src/trendline_primitive.ts
src/libs/models/trendlines/research_viewer/web/tests/payload.test.mjs
src/libs/models/trendlines/research_viewer/web/tests/trendline_primitive.test.mjs
src/libs/models/trendlines/tests/research_viewer/__init__.py
src/libs/models/trendlines/tests/research_viewer/test_payload.py
src/libs/models/trendlines/tests/research_viewer/test_bundle.py
src/libs/models/trendlines/tests/research_viewer/test_server.py
src/libs/models/trendlines/tests/research_viewer/test_notebook_support.py
src/libs/models/trendlines/tests/research_viewer/test_notebook.py
```

Authorized modifications:

```text
src/libs/models/trendlines/tests/test_import_boundaries.py
src/libs/models/trendlines/docs/research.md
src/libs/models/trendlines/docs/workflows.md
```

`package-lock.json` is ignored by repository-wide `.gitignore`; it must be force-added when committing the approved checkpoint.

No forbidden generic app-level viewer path exists.

## 17. Git status

No L2-B commit was made. Current worktree contains only authorized L2-B files and this handoff. Generated `node_modules/`, `dist/` and repository-local Python caches are ignored or removed.

## 18. Commands executed

Key validation commands:

```text
git branch --show-current
git rev-parse HEAD
git log -3 --oneline
git status --short --untracked-files=all
pytest -q src/libs/models/trendlines/tests/research_viewer
pytest -q src/libs/models/trendlines/tests
pytest --collect-only -q src/libs/models/trendlines/tests
pytest -q tests/ingestion/test_trendlines_research_adapter.py tests/test_regime_v2_trendline_feature_producer.py tests/test_regime_v2_shadow_binance_collector.py tests/test_regime_v2.py tests/ingestion/test_adapters.py
pytest -q src/libs/models/trendlines/tests/test_optimizer.py src/libs/models/trendlines/tests/test_optimization_integration.py src/libs/models/trendlines/tests/test_trendlines_pipeline_workflow.py
python -m compileall -q src/libs/models/trendlines
ruff check src/libs/models/trendlines/research_viewer src/libs/models/trendlines/tests/research_viewer src/libs/models/trendlines/tests/test_import_boundaries.py
git diff --check
npm run build
npm test
```

## 19. Residual risks

Only visual browser verification remains open. Browser automation is unavailable in this environment. Static server/security and HTTP endpoint smoke passed; visual layout, interactive toggles, chart geometry, finality warning visibility and browser console state require a browser-capable environment.

## 20. Recommended next phase

```text
L2-C — Bounded real-market notebook and visual validation
```

L2-C must first complete browser visual inspection, then separately authorize any bounded real-market data path. No real Binance validation was performed in L2-B.

## 21. L2-B-R1 import-map remediation

Independent browser review found a frontend bootstrap defect: compiled `main.js` imports bare `lightweight-charts`, while HTML had no import map. Static HTML loaded, but module execution stopped before payload bootstrap.

Fix applied:

```text
src/libs/models/trendlines/research_viewer/web/index.html
```

Added exactly one import map:

```json
{
  "imports": {
    "lightweight-charts": "/vendor/lightweight-charts.mjs"
  }
}
```

Regression added:

```text
src/libs/models/trendlines/tests/research_viewer/test_server.py
```

The test verifies:

- exactly one HTML import map;
- map target `/vendor/lightweight-charts.mjs`;
- compiled `main.js` retains bare `lightweight-charts` import;
- server HTML response matches source HTML;
- vendor route returns exact standalone module bytes.

R1 validation:

```text
Package-local Python: 25 passed
Node/TypeScript:      12 passed
Canonical trendlines: 460 passed
Ruff:                  passed
git diff --check:      passed
```

Fresh synthetic session static smoke:

```text
HTML import map:       present
main.js bare import:   present
vendor route:          200
vendor bytes:          196108
Cache-Control:         no-store
temporary cleanup:     passed
```

Browser runtime remains unavailable (`agent.browsers.list() == []`), so final disposition remains:

```text
BLOCKED_L2B_VISUAL_SMOKE
```

## 22. L2-B-R2 pivot-schema remediation

Browser reached TypeScript payload validation after R1 and exposed a second frontend defect: the shared diagnostic-row loop required `evidence_id` from canonical pivot rows. Pivot rows intentionally have no evidence ID.

Fix applied:

```text
src/libs/models/trendlines/research_viewer/web/src/contracts.ts
```

Pivot validation is now separate. It validates exact canonical pivot keys, point/source/checkpoint/boundary bindings, integer positions/timestamps, finite price, prefix bounds and event-time bounds. Evidence-ID validation remains limited to lines, rays and signals.

Tests added:

```text
accepts a non-empty canonical pivot without evidence_id
rejects an unexpected evidence_id on a pivot
```

R2 validation:

```text
Package-local Python: 25 passed
Node/TypeScript:      14 passed
Canonical trendlines: 460 passed
Ruff/compileall:       passed
git diff --check:      passed
```

Fresh synthetic session started and closed. Static endpoint/bootstrap checks passed through R1; browser visual inspection remains unavailable, so phase disposition is still:

```text
BLOCKED_L2B_VISUAL_SMOKE
```

## 23. L2-B-R3 logical-position geometry remediation

Browser review showed candles/pivots/signals rendered while fitted lines and boundary rays were dropped because their evidence anchors preceded the bounded display window. Timestamp coordinate conversion returned null for anchors outside the candle series.

Fix applied:

```text
src/libs/models/trendlines/research_viewer/payload.py
src/libs/models/trendlines/research_viewer/web/src/contracts.ts
src/libs/models/trendlines/research_viewer/web/src/trendline_primitive.ts
```

Viewer line/ray payloads now include `start_position` and `end_position`. Line positions copy canonical line evidence. Ray timestamps resolve exactly against the prepared frame index; invalid mappings fail closed. Python and TypeScript validators enforce ordered positions within the selected prefix and geometry times through selected event time.

Primitive rendering now uses logical positions relative to `display_start_position`, clips segments to horizontal viewport bounds, skips wholly offscreen segments and differentiates layers:

```text
fitted lines: solid, width 2
boundary rays: dashed [6, 4], width 1.5
```

R3 tests cover default geometry positions, pre-display anchors, canonical line positions, exact ray timestamp mapping, invalid ray mapping, logical clipping, offscreen skipping, payload position validation and independent line/ray visibility.

R3 validation:

```text
Package-local Python: 30 passed
Node/TypeScript:      19 passed
Canonical trendlines: 465 passed
Ruff/compileall:       passed
git diff --check:      passed
```

Default payload evidence:

```text
display positions: 16 → 47
display candles:   32
lines:             6 → 43, 14 → 38
rays:              6 → 43, 14 → 38
line endpoints:    97.5774, 104.9616
pivots/signals:    7 / 1
timeline rows:     28
```

Fresh default synthetic viewer session was started and closed. Browser runtime remains unavailable (`agent.browsers.list() == []`); visual confirmation of clipped lines/rays remains pending.

```text
BLOCKED_L2B_VISUAL_SMOKE
```
