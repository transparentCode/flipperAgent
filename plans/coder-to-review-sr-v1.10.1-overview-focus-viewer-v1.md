---
goal: Deliver SR-V1.10.1 Overview/Focus casebook viewer modes
stage: coder-to-review
date_created: 2026-07-16
last_updated: 2026-07-16
owner: Codex
status: Needs Review
tags: [handoff, quant, sr, v1.10.1, viewer, casebook]
source_agent: Codex quant-coder
target_agent: Quant Review / Orchestrator
---

# SR-V1.10.1 Overview/Focus Viewer

## Scope executed

Implemented viewer-only Overview/Focus modes on branch
`feature/sr-v1.10.1-overview-focus-viewer`, branched from V1.10 closeout commit
`cdc523c`. Implementation commit: `c1e4d50`.

Overview is now default for casebook payloads. It renders all filtered case
zones without lifecycle events, outcome markers, or metrics. Dropdown case
selection enters Focus mode; Focus renders one immutable case zone, its
lifecycle events, outcome-window markers, causal metrics, and creation-to-
tenth-bar range. `All zones` returns to Overview.

## Changes made

- `src/libs/models/sr/tools/zone_viewer/src/casebook.js`
  - added explicit `overview`/`focus` state;
  - overview returns every matching zone and no events/markers/metrics;
  - focus returns one selected zone and its events/markers/metrics/range;
  - added mode-aware event marker visibility helper;
  - preserves immutable casebook inputs.
- `src/libs/models/sr/tools/zone_viewer/src/main.js`
  - defaults casebook viewer to Overview;
  - adds dropdown-to-Focus and `All zones` transitions;
  - applies event toggle only in Focus;
  - preserves terminal toggle in both modes;
  - fits full chart in Overview and uses exact outcome range in Focus;
  - clears stale details and rendered state for empty filters.
- `src/libs/models/sr/tools/zone_viewer/index.html`
  - adds `All zones` control.
- `src/libs/models/sr/tools/zone_viewer/src/styles.css`
  - styles the new control.
- `src/libs/models/sr/tools/zone_viewer/tests/casebook.test.js`
  - adds Overview/Focus, filtering, marker, metrics, toggle, empty-state,
    transition, and immutability regressions.
- `src/libs/models/sr/tools/zone_viewer/tests/zone_primitive.test.js`
  - adds terminal visibility regression across overview/focus zone sets.

## Blast radius considered

Codebase trace marks `updateCasebook` and `casebookState` as central viewer
flows. Change is isolated to the browser entry, casebook state helpers, viewer
shell/style, and Node tests. Legacy non-casebook behavior retains its prior
payload event markers, visibility handling, and full-chart fit path. No Python
payload builder or audit validator changed.

## Validation performed

- Node viewer suite: **24 passed**;
- relevant Python viewer suite: **7 passed**;
- full SR suite: **532 passed in 644.86s**;
- Ruff: passed with `/Users/aloobhujia/.local/bin/ruff`;
- JavaScript syntax checks: passed for `main.js`, `casebook.js`,
  `zone_primitive.js`;
- Python compile/import checks: passed;
- `git diff --check`: passed.

V1.10 audit bundle was not regenerated or modified. Existing member identities
remain byte-identical:

| Member | Bytes | SHA-256 |
|---|---:|---|
| `manifest.json` | 9854 | `482dc10c3a5eaa1142b1b8b7967eea39464f9975ceef14b3aaddb04c66588baf` |
| `audit.json` | 266791 | `27afe6242cc68e0222c7f93ef212b9ad87faaaf53c1b21e6edcbc5a8e2eaceb1` |
| `chart_payload.json` | 605404 | `621df3d8cbd6191567c00b31bed54848acf4a91d0f1f920d7fc1ea2f70cf0714` |

## Not changed

- SR model, lifecycle, detection, association, domain contracts, and config;
- V1.10 audit payload, bundle files, and evidence identities;
- provider calls, source data, database, persistence, and holdout;
- collision engine, event aggregation, parameters, and model features;
- V1.11 research or production surfaces;
- merge to master.

## Risks or follow-up items

Arc visual smoke remains required before V1.10.1 approval. Run on macOS from
this branch:

```text
PYTHONPATH=src .venv/bin/python -c "from libs.models.sr.tools.zone_viewer.server import serve_bundle; serve_bundle('src/libs/models/sr/tools/zone_viewer', 'research/tmp_sr_v1_10/audit/a592276b9fed7c24949ad33b503a7b65474e10f4e3088fe734282401ac058a56')"
```

Confirm Overview default/all filtered zones, zero Overview markers, dropdown
Focus, selected-only events and outcome markers, `All zones` reset, terminal
and event toggles, empty-filter clearing, hover, pan/zoom, attribution, exact
bundle/disposition visibility, and clean Console. Record Arc version. No Google
Chrome claim is required for this Arc-specific gate.

Package is complete for review; no further implementation guesswork is needed.
