---
goal: Mature Trendlines L2-B3 full research lab notebook
stage: coder-to-orchestrator
date_created: 2026-07-26
last_updated: 2026-07-26
owner: quant-coder
status: Ready for review after R1 remediation
source_agent: quant-orchestrator
target_agent: quant-orchestrator
tags: [handoff, quant, trendlines, research-lab, notebook]
---

# Mature Trendlines L2-B3 — Full Research Lab Notebook

## 1. Disposition

L2-B3 and bounded R1 remediation complete. No commit made. Ready for
independent review. L2-D adequacy work was not started.

## 2. Starting branch and commit

Branch: `research/trendlines-adequacy-v1`.

Starting commit: `cebcead8d64ad4b1f6f30966ec1fd42024a8c626`
(`feat: validate trendlines on bounded real market data`).

## 3. Worktree/environment proof

Precondition correction switched the clean legacy worktree to the adequacy
branch. The primary checkout at `/Users/aloobhujia/flipperAgent` was not
touched. Python used: `/Users/aloobhujia/flipperAgent/.venv/bin/python`.
No provider call was made. Final status before this handoff contains only the
authorised L2-B3 paths plus this handoff.

## 4. Legacy notebook feature inventory

The old 55-cell notebook was treated as UX inventory. Useful capabilities
carried forward: controls, source manifest, resolved configuration,
multi-timeframe replay, TVLC, navigation, pivots, lines, rays, signals,
identity/timeline inspection, timings, and explicit evidence/viewer export.
Plotly, RegimeV2 scaling, retired BinanceConnector imports, notebook model
loops, and direct YAML mutation were not carried forward.

## 5. Mature redesign decisions

The notebook is a thin consumer of typed `research_lab`, `workflows.research`,
and `research_viewer` APIs. Replay, evidence validation, data preparation,
identity construction, and payload construction remain package-owned.
L2-D adequacy metrics and oscillator studies remain deferred.

## 6. Research-lab architecture

Added `libs.models.trendlines.research_lab` with contracts, session lifecycle,
navigation, descriptive comparison, deterministic Pandas tables, and timing
helpers. Dependency direction is notebook -> research_lab -> research/research_viewer.
Core model, research execution, viewer, and root trendlines exports do not
depend on `research_lab`.

## 7. Controls contract

`TrendlineResearchLabControls` binds purpose, data mode/specification, asset,
ordered timeframes, primary timeframe, replay windows, signal inclusion,
provider authorization, viewer lookback, inline-viewer policy, export policy,
explicit positions, and selection policy. Booleans and positive integer
lookbacks are strict. Model parameter dictionaries are not accepted.

Builders are `synthetic_lab_controls`, `injected_lab_controls`, and
`binance_lab_controls`. Synthetic defaults to SMOKE; injected and Binance use
RESEARCH. Binance execution still requires an explicit loader and authorization
at the session boundary.

## 8. Session lifecycle

`TrendlineResearchLabSession` owns prepared run, replay, selections, evidence,
payloads, timings, viewer sessions, exports, and study registry. `close()`
closes every server, joins its thread through the viewer session, removes owned
temporary bundles, and is idempotent. After close, selection, latest-selection,
and viewer-opening operations fail closed. Opening a viewer for an already
selected coordinate preserves the policy-derived selection reason. A failure
after partial viewer creation closes already-created viewers before propagating.

## 9. Multi-timeframe execution

`run_research_lab()` prepares and replays every requested timeframe once, in
control order. Smoke evidence used `1h, 4h`; both used 48 rows, positions 19–47
executed, and positions 20–47 recorded.

Per-timeframe source identities:

```text
1h source_id:       a3ee8f1b0a0be9293bfc536f049885ad79a913b17f7f2818a97090977ca9cab8
1h availability_id:8b5d68ae4bbf445fd709f52e7f73ce109960034695842bc1be31c89ac2ecf38f
4h source_id:       40cb8b9bef1b7743ebcbd3ba00b6f88edc2b4cbbfbf2dd63c474757c0536aff5
4h availability_id:b6e6ab09193213c4a73ceac93a0c514f7fd213d8da1efb02ffc86c8765f8456f
```

## 10. Selection policy

Default selection is latest valid point with both support/resistance lines and
rays, then latest valid point with any geometry, then final recorded point.
Explicit recorded positions override policy. Smoke selected position 47 for
both 1h and 4h; policy reason was
`latest_valid_point_with_both_line_and_ray_roles`.

## 11. Replay navigator

`select_replay_position()` validates recorded coordinates and builds selected
evidence/payload without replay execution. Notebook navigation selected 1h
position 46 with lookback 32 through `open_viewer()`, replaced the prior
viewer, rebuilt selected tables/payload, and kept `replay_id` unchanged.

## 12. Position comparison

`compare_replay_positions()` generated exact descriptive differences for the
selected timeframe, including event/availability times, source/checkpoint/
content/point IDs, fit/finality/state fields, line/ray/pivot counts, quality,
and signal fields. No improvement, deterioration, return, or adequacy label is
assigned.

## 13. Table APIs

Added stable DataFrame helpers for controls, identities, source manifest,
resolved config, replay summary, timelines, pivot counts, selected pivots,
lines, rays, signals, signal history, comparisons, performance, exports, and
study registry. Tables preserve full IDs, stable columns, stable row order, and
do not execute model/replay work. Notebook table calls use a session timing
accumulator; `table_ms` is measured presentation construction time and is not
part of any research identity.

## 14. Signal-history inspection

`lab_signal_history_table()` reads selected output metadata, preserving history
snapshot/revision pairing plus `signal_input_id`, query knowledge time,
availability time, timestamp semantics, and availability provenance. It does not
reconstruct history from notebook state.

## 15. Performance instrumentation

`TrendlineResearchLabTimings` records preparation, replay, evidence per
timeframe, viewer payload per timeframe, viewer bundle per timeframe, viewer
startup per timeframe, table construction, and total timings. Timing values are
not identity inputs. Provider accounting is resolved after preparation from a
non-negative `provider_calls` attribute; explicit compatibility `calls` is
validated only when present. Malformed or unavailable Binance accounting fails
closed.

## 16. Session comparison

`compare_lab_sessions()` audits timeframe order, replay specification,
configuration identity, signal inclusion, timestamp semantics, and availability
provenance. It returns descriptive mismatches and does not fetch data or make
adequacy decisions.

## 17. Study registry

Available: causal replay inspection, pivot diagnostics, line/ray diagnostics,
signal inspection, position comparison, performance inspection, evidence export.

L2-D pending: longevity, churn/revision adequacy, null comparison,
touch/penetration utility, sensitivity, cross-window robustness, cross-asset
adequacy.

Separate programme: RSI/MACD trendlines and price/oscillator confluence.

## 18. Notebook structure

`research/trendlines_research_lab.ipynb` now contains 41 cells: 21 markdown and
20 code. It has required headings 0–19 in order, nbformat 4, 20 code cells,
cleared outputs, and null execution counts. It contains no binary output,
installation cell, provider command, model loop, or YAML write.

## 19. Notebook mode examples

Checked-in execution is deterministic SMOKE/SYNTHETIC with BTCUSDT, 1h and 4h,
seed 7, 48 bars per timeframe, replay windows `(19, 20, 47, 1)`, signals
enabled, lookback 32, inline viewers enabled, and permanent export disabled.
Markdown includes disabled injected-frame/artifact and explicit Binance control
examples. No Binance call is executed.

## 20. Multi-timeframe viewers

Smoke run opened loopback viewers for both 1h and 4h in control order. The
notebook emits one explicit `display(IFrame(...))` per timeframe, preceded by
timeframe, position, reason, event/availability, finality, and URL metadata.
Ports are intentionally ephemeral. Viewer sessions closed cleanly.

## 21. Evidence/export

Each selection builds a validated evidence bundle and viewer payload. Permanent
JSON export is opt-in and disabled in checked-in notebook. `lab_export_table()`
expands evidence files, viewer `manifest.json` and `chart_payload.json`, and
the lab manifest into deterministic inventory rows containing file class,
byte length, lowercase SHA-256, preparation/dataset/replay IDs, and applicable
evidence/viewer identities. No YAML or permanent artifact is written by
default.

## 22. Notebook execution

Two fresh-kernel top-to-bottom IPython runs passed. Each prepared both
timeframes, replayed both, built evidence and viewer payloads, explicitly
displayed both viewers, populated tables, navigated 1h to position 46 without
replay rerun, and closed all viewers. Dataset/configuration/preparation/replay,
selected evidence, and viewer payload identities matched between runs;
timings and ephemeral URLs were excluded. Provider calls: 0. Cleanup flags
were computed from actual empty viewer state and removed temporary roots.

## 23. Dedicated tests

Added exactly 20 non-parametrised tests under
`src/libs/models/trendlines/tests/research_lab`. Coverage includes controls,
production-shaped `provider_calls` accounting, multi-timeframe order,
one-session execution, selection policy, closed-session rejection, viewer
replacement without replay, table identity/content and non-placeholder timing,
signal history, export byte/checksum inventory, comparison, viewer lifecycle,
notebook IFrame structure, and cleanup. Test fixtures create isolated mutable
sessions; no cached session is shared.

Dedicated research-lab result: `20 collected; 20 passed`. Focused lab plus
viewer notebook-integration result: `24 passed`.

## 24. Import boundaries

Import-boundary tests allow research_lab to consume source-agnostic research
and package-local viewer APIs. They reject core/research/viewer reverse imports,
application namespaces, RegimeV2, Trendline V2, Plotly, Matplotlib, Seaborn,
Jupyter, and IPython from the package. Test passed.

## 25. Performance evidence

Measured representative fresh-kernel two-timeframe smoke session after R1:

```text
preparation:                 10.07 ms
replay:                     427.58 ms
evidence:       1h 156.46 ms; 4h 240.03 ms
viewer payload: 1h  19.88 ms; 4h  19.94 ms
viewer bundle:  1h  10.25 ms; 4h   9.47 ms
viewer startup: 1h   6.71 ms; 4h   7.84 ms
table construction:          5.58 ms
session timing total:     1856.89 ms
notebook wall time: 4902.18 ms (run 1); 2990.89 ms (run 2)
provider calls:                  0
```

Preparation ID:
`7e96cee92fe0e54cd37efd2d2f6aa6dc302106bb3de1fd83e6d44846b120b451`.
Dataset ID:
`be969b362d38c76f8fb3aa80204fe08055aff0a8bd0149bb101f372bd56aa46c`.
Research configuration ID:
`b26b507df800e3d45261544dd50d68298eef55d2a6776b81cb86c525542bdb07`.
Replay ID:
`85b110f554d9d1aec2960cdc39dea6f33ca5f7008a14513dc89bb807c52efebe`.

After notebook navigation, selected evidence was:

```text
1h position 46, reason explicit_recorded_position
  pivots 7, lines 2, rays 2, signals 1
  evidence_bundle_id a44dc4d5f5a3db572cbbce561c6c65f1b3608e3c52c32775782ec4565de9969d
  viewer_payload_id  ad3c00170b668bb7fa3d039f1130d6bed5269f5bf12d60b1287b0b31f756caf7
4h position 47, reason latest_valid_point_with_both_line_and_ray_roles
  pivots 8, lines 2, rays 2, signals 2
  evidence_bundle_id ffa7dc4c92dac16e38c7c14d9c2e3ddc3266db468b5078b2bba39e68df03c2f3
  viewer_payload_id  dd3d1188376e93b424946255b0e8c424776c5c8d74dcdc3a3dd6d2789f4fd784
```

## 26. Canonical regression

`493 collected; 493 passed in 49.81s`.

## 27. Viewer regression

Python viewer: `30 passed in 28.56s`.
Node/TypeScript viewer: `23 passed`.

## 28. Consumer/offline regression

Consumer/ingestion/bridge: `79 passed in 20.66s` (`71` consumer/ingestion
matrix plus `8` mocked bridge tests). Offline workflows: `20 passed in 7.46s`.
Provider calls: `0`.

## 29. Static validation

Targeted Ruff passed for research_lab, its tests, and import-boundary tests.
Compileall passed for lab modules and tests. `git diff --check` passed.
Repository-local Python caches were removed after final validation commands.

## 30. Files changed

```text
M  research/trendlines_research_lab.ipynb
A  src/libs/models/trendlines/research_lab/{__init__,contracts,session,tables,navigation,comparison,performance}.py
A  src/libs/models/trendlines/research_lab/README.md
A  src/libs/models/trendlines/tests/research_lab/{__init__,test_controls,test_session,test_tables,test_navigation,test_notebook}.py
M  src/libs/models/trendlines/tests/research_viewer/test_notebook.py
M  src/libs/models/trendlines/tests/test_import_boundaries.py
M  src/libs/models/trendlines/docs/research.md
M  src/libs/models/trendlines/docs/workflows.md
```

## 31. Git status

Committed L2-B3 scope is limited to paths listed in Section 30 plus this
handoff. No model, viewer, replay, YAML, Binance, RegimeV2, or L2-C artifact
path changed.

## 32. Residual risks

This phase provides inspection and presentation plumbing, not adequacy evidence.
No longevity, churn, touch accuracy, penetration utility, null comparison,
sensitivity, cross-window robustness, cross-asset comparison, predictive
outcome, promotion, or oscillator claim is made. Viewer ports are ephemeral;
permanent export remains explicit opt-in.

## 33. Recommended next phase

`L2-D — Research adequacy and model-quality evaluation`.

Do not begin L2-D until this handoff and the complete validation evidence are
independently reviewed.

## Required conclusion

The mature trendlines notebook is now a full research workbench rather than a
smoke launcher. It preserves useful legacy research experience without
restoring retired imports, RegimeV2 coupling, Plotly, notebook-owned algorithms,
or YAML mutation. Model execution, replay, diagnostics, evidence, and viewer
construction remain in tested package APIs. Adequacy metrics and oscillator
trendlines remain explicitly deferred.
