---
goal: Close SR pre-V2 modularization with hermetic architecture tests, zero active import cycles, documented ownership boundaries, and preserved frozen evidence.
stage: coder-to-review
date_created: 2026-07-18
last_updated: 2026-07-18
owner: quant-coder
status: 'Review Ready'
tags: [handoff, quant, sr, refactor, r5, closure, boundaries, documentation]
source_agent: Codex quant-coder
target_agent: quant-review
---

# SR Pre-V2 R5 — Final Boundary, Documentation, and Closure

## Scope Executed

Completed Package H from
`plans/architect-to-coder-sr-pre-v2-streamlined-execution-v1.md`.

- Fixed fresh-process architecture test to use exact repository `src` root
  (`_PACKAGE_DIR.parents[2]`) and a sealed `PYTHONPATH`; it no longer inherits
  shell path state.
- Removed final non-core `research` ↔ `tools` import-time cycle without
  changing payload semantics. Baseline Trial chart-payload construction now
  has canonical ownership in
  `research/studies/baseline_trial/chart_payload.py`; historical
  `tools/zone_viewer/payload.py` is an export-only compatibility facade.
- Added architecture enforcement that all research modules, including
  canonical studies, do not import tooling. Active module-scope package graph
  now has zero cycles.
- Added exact tool-to-canonical function identity coverage for chart payload
  construction and payload identity hashing.
- Added required active-SR documentation:
  - `src/libs/models/sr/docs/ARCHITECTURE.md`;
  - `src/libs/models/sr/docs/CONFIGURATION.md`;
  - `src/libs/models/sr/docs/RESEARCH_BOUNDARIES.md`;
  - `src/libs/models/sr/docs/LEGACY_SR_STATUS.md`.
- Inspected duplicate ownership. The now-obsolete viewer-tool chart-payload
  implementation was moved to its canonical Baseline Trial owner; remaining
  historical facades are intentionally retained.
- Re-indexed codebase-memory and completed final diff/impact review.

Implementation commits:

- `e856168` — `refactor(sr): close viewer payload import cycle`
- `f6b88a3` — `test(sr): close final research boundaries`
- `b020b24` — `docs(sr): close pre-v2 architecture boundaries`

## Changes Made

- Fresh-process domain import test runs a subprocess with only the exact
  source root on `PYTHONPATH`; importing `libs.models.sr.domain` still does
  not load configuration modules.
- Baseline Trial artifacts import their own canonical pure chart-payload
  builder. The tool compatibility module re-exports the same
  `build_chart_payload`, `chart_payload_identity`, payload schema constant,
  and existing casebook builder objects.
- Architecture checks now require:
  - no active `libs.sr` imports;
  - no core-to-research imports;
  - no research-to-tools imports;
  - no canonical or historical sibling-study imports;
  - no active module-scope import cycles;
  - export-only core, shared-research, historical-study, and viewer-payload
    facades.
- Documentation records canonical ownership, four-layer configuration
  precedence, hardcoding policy, research/evidence dependency boundaries,
  compatibility-facade removal conditions, and legacy `src/libs/sr` status.

## Blast Radius Considered

- Baseline Trial chart payload: **HIGH** identity boundary. It contributes to
  immutable viewer payload and historical evidence member bytes. Mitigation:
  moved implementation byte-for-byte in behavior, kept tool exports exact,
  ran baseline/viewer tests, full SR regression, and public V1.12 semantic
  validation.
- Architecture harness: **LOW** runtime impact. It only changes subprocess
  isolation and import-graph assertions; plain-environment architecture tests
  pass.
- Documentation: **LOW**. No runtime imports, configuration, artifacts, or
  evidence modified.
- Final codebase-memory diff review from Package G handoff commit `10a3bc9`
  found 9 intended files, low risk, and zero affected runtime processes.

## Validation Performed

- Plain-environment architecture suite (`env -u PYTHONPATH`): **34 passed**.
- Initial cycle/facade/baseline/viewer slice: **91 passed**.
- Final focused architecture, viewer, Baseline Trial, and Candidate Audit
  suite: **148 passed**.
- Full active SR suite in plain environment: **912 passed** in
  **640.55 seconds**.
- Ruff over `src/libs/models/sr` and `tests/models/sr`: passed.
- Full `src/libs/models/sr` compilation: passed.
- `git diff --check`: passed.
- Codebase-memory re-index completed: **55,704 nodes**, **214,572 edges**.
- Public V1.12 semantic validation passed through historical CLI using frozen
  original implementation binding `2412fbb5a26b4429ecd99025e0edb028d8cb46c4`:
  - bundle `fd3eaf4cb58a23ee47c0f8645a3d4affd09ef05bf3cafb74831621826a58c206`;
  - audit `cd452938e2befc66f0d2a4e12d79083b88cf6e03a3124180c356d56a6f2b8adb`;
  - disposition `INSUFFICIENT_REINFORCEMENT_EVIDENCE`.
- Frozen SHA-256 identities remain exact:
  - `configs/sr.yaml`:
    `0c7c11aea8f1ea1e11ef810a6f38d7370a14834c1517d4aab43ac71c378a2119`;
  - V1.12 YAML:
    `8a1c2f2c72213e62638ead381c0f7a50a67d96b527f799afe878065d59b93665`;
  - manifest:
    `c2d0e03f43ea1154bac9c005a2c4d021188a33f56d4ddd17dd6376b9f77c43e6`;
  - audit:
    `41bd97da3cef62f10a96f263ac0278e0aff524ebe8337abce0aee986995fee32`.
- V1.12 accounting remains exact: 65 candidates, 50 created zones,
  15 eligible matches, and 13 unique reinforced zones.

## Not Changed

- No domain, config value/schema, detection, association, lifecycle,
  replay/checkpoint, serialization, evaluation, metric, disposition, source,
  artifact-schema, or evidence-byte change.
- No provider/network/database call, source refresh, holdout access, evidence
  regeneration, viewer JavaScript change, legacy `libs.sr` edit, merge, or V2
  model work.
- Required historical import and CLI facades remain present and logic-free.

## Risks or Follow-up Items

- No blocking implementation issue found. Package H is complete enough for
  independent final review; merge remains unauthorized.
- Review must independently verify the hermetic subprocess test, zero active
  import cycles, facade-only modules, exact tool/canonical export identities,
  documentation claims, frozen identities, and V1.12 semantic result.
- No V2 work, provider/holdout access, evidence regeneration, or merge may
  start during review.
