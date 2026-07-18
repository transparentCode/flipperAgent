---
goal: Preserve cohort-readiness and geometry-sensitivity behavior while moving their canonical implementations under research studies.
stage: coder-to-review
date_created: 2026-07-18
last_updated: 2026-07-18
owner: quant-coder
status: 'Review Ready'
tags: [handoff, quant, sr, refactor, r3b]
source_agent: Codex quant-coder
target_agent: quant-review
---

# SR Pre-V2 R3b — Cohort Readiness and Geometry Sensitivity Migration

## Scope Executed

Completed Package C / R3b from
`plans/architect-to-coder-sr-pre-v2-streamlined-execution-v1.md`.

- Moved the canonical Cohort Readiness study to
  `libs.models.sr.research.studies.cohort_readiness`.
- Moved the canonical Geometry Sensitivity study to
  `libs.models.sr.research.studies.geometry_sensitivity`.
- Retained every historical `libs.models.sr.scripts.cohort_readiness` and
  `libs.models.sr.scripts.geometry_sensitivity` module as a logic-free
  forwarding facade, including CLI `__main__` forwarding.
- Extracted the exact frozen cohort contracts, strict configuration parser,
  artifact validation/publication, and replay/aggregation services into the
  neutral `research.cohort` package. Cohort Readiness remains the owner of
  provider preparation and study-stage orchestration; Geometry consumes only
  the neutral frozen-input services.
- Reused the neutral source capsule, ATR replay, first-touch metric, production
  configuration, strict JSON, content identity, and repository path contracts.
- Removed all eight Cohort outgoing sibling-study imports and all seven
  Geometry outgoing sibling-study imports.
- Enforced that canonical studies import neither historical `scripts` studies
  nor a sibling canonical study.
- Restored the historical `SourceCapsule` acceptance range for lowercase Git
  identities: every length from 40 through 64 characters is valid.
- Made Cohort's provider boundary accept only the exact runtime
  `pandas.DataFrame` class via its study-local lazy import, retaining rejection
  of lookalikes and subclasses without adding a static pandas import outside
  the approved integration boundary.

Implementation commits:

- `5f67931` — `refactor(sr): migrate cohort readiness study`
- `58e331b` — `refactor(sr): migrate geometry sensitivity study`
- `a19e5ec` — `test(sr): lock R3b compatibility boundaries`
- `e451878` — `fix(sr): preserve source capsule commit contract`
- `4d96a03` — `fix(sr): accept real pandas cohort frames`
- `fd56184` — `fix(sr): preserve cohort import boundaries`

## Compatibility and Dependency Accounting

- Historical and canonical Cohort `AssetSource`, `SourceBundle`,
  `CohortEvaluation`, `CohortConfig`, artifact validation, replay helpers, and
  CLI parser/main exports retain exact object identity where public.
- Historical and canonical Geometry `GeometryCandidate`,
  `GeometrySensitivityStudy`, `compute_study`, and CLI parser/main exports
  retain exact object identity.
- Legacy ATR, canonical ATR, and neutral shared paths export the same exact
  `SourceCapsule` class object.
- The historical Cohort runner preserves the existing
  `default_provider_adapter` monkeypatch seam as the exact canonical adapter
  factory object.
- Logical sibling-study imports are now:
  - legacy `scripts/` edges: **23**;
  - canonical `research/studies/` edges: **0**;
  - total: **23** (**38 → 23** for Package C; **41 → 23** from the R2 baseline).

## Behavior Preservation

- No readiness, source-grid, fold, candidate-grid, replay, first-touch metric,
  selection, threshold, parity, artifact, or evidence semantics changed.
- Geometry continues to validate V1.7 source/evaluation evidence and establish
  V1.7/V1.8 baseline replay/aggregate parity before evaluating its frozen grid.
- Cohort's TAOUSDT V1.6 upstream remains an explicit frozen-input boundary;
  it validates the published development capsule directly and does not import
  ATR Calibration or Baseline Trial.

## Validation Performed

- Source capsule, Cohort source/runner, Geometry, and architecture focused
  suites: **111 passed**.
- Final exact-pandas and runtime import-boundary regression slice:
  **16 passed**.
- Full active SR suite: **838 passed** in 629.34 seconds.
- Historical CLI modules load successfully:
  - `python -m libs.models.sr.scripts.cohort_readiness.cli --help`
  - `python -m libs.models.sr.scripts.geometry_sensitivity.cli --help`
- Ruff for all touched research/study/facade/test paths: passed.
- Full `src/libs/models/sr` compilation: passed.
- `git diff --check`: passed.
- V1.12 semantic validation through its historical public CLI: passed:
  - bundle `fd3eaf4cb58a23ee47c0f8645a3d4affd09ef05bf3cafb74831621826a58c206`;
  - audit `cd452938e2befc66f0d2a4e12d79083b88cf6e03a3124180c356d56a6f2b8adb`;
  - disposition `INSUFFICIENT_REINFORCEMENT_EVIDENCE`.
- Frozen SHA-256 identities remain exact:
  - `configs/sr.yaml`:
    `0c7c11aea8f1ea1e11ef810a6f38d7370a14834c1517d4aab43ac71c378a2119`;
  - V1.12 trial YAML:
    `8a1c2f2c72213e62638ead381c0f7a50a67d96b527f799afe878065d59b93665`;
  - V1.12 manifest:
    `c2d0e03f43ea1154bac9c005a2c4d021188a33f56d4ddd17dd6376b9f77c43e6`;
  - V1.12 audit:
    `41bd97da3cef62f10a96f263ac0278e0aff524ebe8337abce0aee986995fee32`.

## Not Changed

- No provider, network, database, source refresh, sealed/holdout access,
  viewer change, artifact regeneration, or merge occurred.
- No core SR model, lifecycle, detection, association, configuration value, or
  evidence-byte change occurred.
- R3c, V2 work, model work, and promotion remain out of scope.

## Review Request

Review this package as an ownership and dependency-only migration. In
particular, confirm historical facades remain logic-free, canonical studies
have zero sibling-study imports, logical sibling accounting is exactly 23,
and frozen V1.12 bytes/semantic validation remain unchanged.
