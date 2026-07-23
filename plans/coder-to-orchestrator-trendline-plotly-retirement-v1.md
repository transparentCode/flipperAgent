# Coder To Orchestrator: Trendline Plotly Retirement V1

## 1. Work Completed

Implemented Package A only on branch `cleanup/trendline-retire-plotly-v1`, based
on commit `35d333bde3f2f249e214ee76871c6f4a94251d2e`.

- Removed the canonical and compatibility Plotly research modules.
- Removed the three Plotly exports from the canonical research-lab package.
- Converted the research notebook from chart construction to browserless
  evidence notices and evidence tables.
- Converted point-in-time replay and MTF notebook paths to evidence-only output.
- Preserved validation-stage and metric identity, table output, artifact loading,
  holdout isolation, replay lineage, interaction events, and MTF geometry checks.
- Renamed the plotting-named replay test module to `test_replay_tables.py`.
- Added an active-path boundary test rejecting legacy plotting and browser-launch
  dependencies.

Package B, TVLC notebook migration, candidate selection, tracking, and model
changes were not started.

## 2. Files Changed

- Deleted `src/libs/models/trendline/research_lab/plotting.py`.
- Deleted `src/libs/models/trendline_family/research_lab/plotting.py`.
- Modified `src/libs/models/trendline/research_lab/__init__.py`.
- Modified `research/trendline_family_research_lab.ipynb`.
- Renamed `tests/models/trendline_family/research_lab/test_replay_tables_plotting.py`
  to `tests/models/trendline_family/research_lab/test_replay_tables.py`.
- Modified `tests/models/trendline_family/research_lab/test_artifacts_and_boundaries.py`.
- Modified `tests/models/trendline_family/research_lab/test_notebook_contract.py`.

The handoff itself is `plans/coder-to-orchestrator-trendline-plotly-retirement-v1.md`.
No unrelated source, runtime, TVLC, or configuration files were changed.

## 3. Architecture Decisions

- Trendline visualization ownership is now exclusively the existing
  `apps.trendline_v2_viewer` TVLC path.
- The research lab remains offline and evidence-oriented; it does not launch a
  browser or construct a replacement chart.
- Exact member/corridor/zone geometry, persisted IDs, replay timestamps,
  source identity, lifecycle/event evidence, and MTF projection rows remain
  directly testable as typed research records.
- Validation sensitivity output remains validation-only evidence. It is now
  displayed as typed rows rather than rendered as a Plotly figure.

## 4. Config Impact

No YAML, runtime, model, provider, tracker, interaction, MTF, or Regime
configuration changed. `CHART_LOOKBACK` remains part of the notebook's existing
research identity payload for replay identity compatibility, but it no longer
drives a legacy chart.

## 5. Validation

- Research-lab suite: `25 passed`.
- Full protected Trendline Family suite: `400 passed`.
  The pre-existing 399-test baseline is preserved plus the new active-path
  boundary regression test.
- Trendline V2 and TVLC viewer Python suites: `135 passed`.
- TVLC Node/TypeScript suite: `13 passed`.
- `npm ci`: passed; `0 vulnerabilities` reported.
- Ruff: passed for canonical/compatibility research modules and research tests.
- `compileall`: passed for canonical/compatibility research modules.
- `git diff --check`: passed.
- Notebook JSON parsing and browserless notebook execution: passed through the
  research-lab tests.

## 6. Architecture Drift Checklist

- [x] No runtime import from old trendline packages introduced.
- [x] No YAML read outside the existing configuration boundary.
- [x] No future or incomplete-bar data path introduced.
- [x] Exact line and interaction-zone evidence remain separate.
- [x] Existing deterministic IDs and serialization paths are preserved.
- [x] Geometry remains separate from trade policy.
- [x] No Package B, tracker, provider, selection, or research algorithm was added.
- [x] No unrelated files were changed.
- [x] Active trendline research paths contain no Plotly import, figure show,
  browser launcher, Playwright, Selenium, or Puppeteer usage.
- [x] TVLC viewer source and protected Trendline V2 behavior were not changed.

## 7. Index and Known Gaps

Codebase-memory was reindexed successfully:

- `flipperAgent-src`: 22,619 nodes / 117,225 edges.
- `flipperAgent-tests`: 5,435 nodes / 22,821 edges.
- `flipperAgent-conductor`: 196 nodes / 981 edges.
- `flipperAgent-scripts`: 781 nodes / 3,383 edges.
- `flipperAgent-docs`: 433 nodes / 431 edges.
- `flipperAgent-plans`: 5,145 nodes / 5,139 edges.

GitNexus was also refreshed with 47,437 nodes, 78,416 edges, 1,432 clusters,
and 300 flows. Its container metadata reports the older mounted branch label;
the live source/test indexes are non-zero and refreshed.

Manual browser smoke remains outside this bounded package and was not launched.
No commit was created. Review and approval are required before committing.

## 8. Recommended Next Phase

`READY_FOR_ORCHESTRATOR_REVIEW`.

After approval and commit, proceed to Package B only under its separate
authorization. Do not begin candidate selection, tracking, optimization, or
runtime integration in this branch.
