---
goal: Preserve baseline-trial and ATR-calibration behavior while moving their canonical implementations under research studies.
stage: coder-to-review
date_created: 2026-07-18
last_updated: 2026-07-18
owner: quant-coder
status: 'Ready'
tags: [handoff, quant, sr, refactor, r3a]
source_agent: Codex quant-coder
target_agent: quant-review
---

# SR Pre-V2 R3a — Baseline Trial and ATR Calibration Migration

## Scope Executed

Completed Package B / R3a from
`plans/architect-to-coder-sr-pre-v2-streamlined-execution-v1.md`.

- Moved canonical baseline-trial implementation to
  `libs.models.sr.research.studies.baseline_trial`.
- Moved canonical ATR-calibration implementation to
  `libs.models.sr.research.studies.atr_calibration`.
- Retained every historical `libs.models.sr.scripts.baseline_trial` and
  `libs.models.sr.scripts.atr_calibration` module as a logic-free forwarding
  facade, including CLI `__main__` forwarding.
- Removed the three ATR-calibration imports of baseline-trial through the
  historical `scripts` path. Canonical ATR code now imports canonical baseline
  modules directly.
- Reduced the recorded sibling-study import baseline from 41 to 38.
- Added R3a architecture and class-identity compatibility tests. The existing
  general import-boundary checks now recognize baseline trial at its canonical
  study location as the same approved pandas/provider integration boundary as
  the historical facade.

Implementation commits:

- `92b9efa` — `refactor(sr): migrate baseline trial study`
- `5032014` — `refactor(sr): migrate ATR calibration study`
- `1a198a7` — `test(sr): lock R3a compatibility boundaries`
- `b0fe923` — `test(sr): allow canonical baseline study imports`

## Changes Made

- Baseline and ATR public classes, functions, and CLI parser/main exports are
  re-exported as the exact canonical class/function objects; facades introduce
  no business logic.
- Production viewer input contracts now import baseline-trial types from the
  canonical study, avoiding internal dependence on the facade.
- Tests that need to monkeypatch non-public module seams target canonical
  modules; their public calls continue through the historical facade.
- Architecture tests enforce that canonical R3a study modules do not import
  `libs.models.sr.scripts`, and that both legacy study directories contain only
  imports, documentation, and necessary CLI forwarding.

## Blast Radius Considered

The codebase graph identifies the moved baseline `run_trial` and ATR
`select_development_stage` / frozen-capsule loader as direct, high-risk
execution seams. The migration changed module ownership and imports only;
focused tests cover the legacy entrypoints, private test seams, canonical
exports, and both historical CLI modules. No candidate, zone, lifecycle,
metric, artifact, or evidence behavior was altered.

## Validation Performed

- Baseline-trial, ATR-calibration, and architecture focused suites:
  **104 passed**.
- Architecture compatibility/boundary suite: **12 passed**.
- Import-boundary repair slice: **16 passed**.
- Full active SR suite: **821 passed** in 706.99 seconds.
- Historical CLI modules load successfully:
  - `python -m libs.models.sr.scripts.baseline_trial.cli --help`
  - `python -m libs.models.sr.scripts.atr_calibration.cli --help`
- Ruff across `src/libs/models/sr` and `tests/models/sr`: passed.
- Full `src/libs/models/sr` compilation: passed.
- `git diff --check`: passed.
- V1.12 semantic validation through its historical public CLI: passed:
  - bundle `fd3eaf4cb58a23ee47c0f8645a3d4affd09ef05bf3cafb74831621826a58c206`
  - audit `cd452938e2befc66f0d2a4e12d79083b88cf6e03a3124180c356d56a6f2b8adb`
  - disposition `INSUFFICIENT_REINFORCEMENT_EVIDENCE`
- Frozen identities remain exact:
  - `configs/sr.yaml`:
    `0c7c11aea8f1ea1e11ef810a6f38d7370a14834c1517d4aab43ac71c378a2119`
  - V1.12 trial YAML:
    `8a1c2f2c72213e62638ead381c0f7a50a67d96b527f799afe878065d59b93665`
  - V1.12 manifest: 11,670 bytes,
    `c2d0e03f43ea1154bac9c005a2c4d021188a33f56d4ddd17dd6376b9f77c43e6`
  - V1.12 audit: 104,978 bytes,
    `41bd97da3cef62f10a96f263ac0278e0aff524ebe8337abce0aee986995fee32`

## Not Changed

- No algorithms, candidate surfaces, indicators, gates, metrics, lifecycle
  behavior, configuration, artifact schemas, or evidence bytes changed.
- No provider, network, database, source refresh, sealed/holdout access,
  viewer change, merge, or evidence regeneration occurred.
- No R3b study migration began. All remaining sibling-study imports stay at the
  recorded R3a baseline of 38 for later approved packages.

## Risks or Follow-Up Items

No blocking issue remains for R3a review. The next permitted action is an
independent R3a review against the package gate. R3b, merge, model work, and
evidence regeneration remain out of scope until that approval.
