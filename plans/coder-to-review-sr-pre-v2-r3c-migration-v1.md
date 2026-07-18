---
goal: Preserve baseline-adequacy and context-audit behavior while moving canonical ownership under research studies and removing their sibling-study imports.
stage: coder-to-review
date_created: 2026-07-18
last_updated: 2026-07-18
owner: quant-coder
status: 'Review Ready'
tags: [handoff, quant, sr, refactor, r3c]
source_agent: Codex quant-coder
target_agent: quant-review
---

# SR Pre-V2 R3c — Baseline Adequacy and Context Audit Migration

## Scope Executed

Completed Package D / R3c from
`plans/architect-to-coder-sr-pre-v2-streamlined-execution-v1.md`.

- Added canonical Baseline Adequacy facades at
  `libs.models.sr.research.studies.baseline_adequacy`.
- Added canonical Context Audit implementation at
  `libs.models.sr.research.studies.context_audit`.
- Retained every historical
  `libs.models.sr.scripts.baseline_adequacy` and
  `libs.models.sr.scripts.context_audit` module as a logic-free forwarding
  facade, including CLI `__main__` forwarding.
- Extracted Baseline Adequacy's reusable frozen-evidence contracts,
  deterministic controls/metrics, artifact validation, and frozen-input
  replay service to `research.evidence.baseline_adequacy`.
- Restored V1.8 frozen-evidence ownership at
  `research.evidence.geometry_sensitivity`, including the complete geometry
  config, contracts, candidate grid, selection, artifact validator, and
  semantic replay runner. Canonical Geometry Sensitivity remains an
  identity-preserving facade over this neutral evidence service.
- Baseline Adequacy again resolves `v18_config_path`, verifies the complete
  Geometry config hash and payload, enforces the V1.8 bundle directory ID and
  exact `{manifest.json, study.json}` member set, and semantically recomputes
  every V1.8 candidate before consuming the complete geometry study object.
- V1.8 validation and existing-bundle publication reject symlinked or
  non-regular members. The former reduced V1.8 placeholder boundary is
  removed.
- Moved the exact `ViewerConfig` contract to
  `research.viewer.contracts`; Baseline Trial re-exports the same class object.
- Context Audit now consumes only neutral V1.9 frozen-evidence contracts and
  shared Cohort contracts. It imports no Baseline Adequacy, Baseline Trial, or
  Cohort Readiness study implementation.

Implementation commits:

- `1aab33e` — `refactor(sr): migrate baseline adequacy study`
- `8e122cf` — `refactor(sr): migrate context audit study`
- `3a9d4db` — `fix(sr): restore V1.8 evidence boundary`

## Compatibility and Dependency Accounting

- Legacy and canonical Baseline Adequacy config, contract, artifact, runner,
  CLI parser, and CLI main exports retain exact object identity where public.
- Legacy and canonical Context Audit audit, contract, runner, CLI parser, and
  CLI main exports retain exact object identity where public.
- `baseline_trial.contracts.ViewerConfig` is exactly
  `research.viewer.contracts.ViewerConfig`.
- Canonical studies import neither historical `scripts` studies nor another
  canonical study.
- Logical sibling-study imports are now:
  - legacy `scripts/` edges: **9**;
  - canonical `research/studies/` edges: **0**;
  - total: **9** (**23 → 9** for Package D; **41 → 9** from the R2 baseline).

The remaining nine legacy edges are owned by the still-unmigrated R3d studies:
Candidate Reinforcement Audit → Baseline Adequacy (1), Baseline Trial (1),
Lifecycle Utility (3); Lifecycle Utility → Context Audit (4).

## Behavior Preservation

- No null/control population, baseline parity, metric, outcome, adequacy-gate,
  context-case, comparison-population, chart-payload, configuration, or
  disposition behavior changed.
- Context Audit still requires the exact V1.9 negative disposition
  `BASELINE_NOT_BETTER_THAN_NAIVE_NULL`, 36 cases, and 31 comparable mappings.
- V1.8 regressions prove missing or mutated configuration, a wrong bundle
  directory name, unexpected or symlinked members, and fully rehashed
  manifest/study tampering all fail closed before V1.9 replay consumption.
- `FrozenInputs.v18_config` and `FrozenInputs.v18_study` are once again the
  complete canonical `GeometrySensitivityConfig` and
  `GeometrySensitivityStudy` types; historical, canonical, and neutral
  Geometry exports retain exact object identity.
- No provider, network, database, holdout, source refresh, evidence
  regeneration, or viewer operation was performed.

## Validation Performed

- R3c focused Baseline Adequacy, Context Audit, Geometry Sensitivity, and
  architecture suite: **136 passed**.
- Full active SR suite: **848 passed**.
- Historical CLI modules load successfully:
  - `python -m libs.models.sr.scripts.baseline_adequacy.cli --help`
  - `python -m libs.models.sr.scripts.context_audit.cli --help`
- Ruff for all touched source and test paths: passed.
- Full `src/libs/models/sr` compilation: passed.
- `git diff --check`: passed.
- V1.12 public semantic validation: passed:
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

- No core SR model, detection, association, lifecycle, checkpoint, provider,
  configuration-value, artifact-byte, or evidence change occurred.
- No merge, R3d, V2, model feature, parameter tuning, provider call, or
  holdout access occurred.

## Review Request

Review this package as an ownership and dependency-only migration with restored
V1.8 semantic evidence validation. Confirm `v18_config_path` is consumed, the
complete Geometry config/study types are returned, the V1.8 member/directory
and semantic-recomputation checks are fail-closed, the two historical facade
trees are logic-free, the canonical-study sibling count is zero, the remaining
logical edge count is exactly nine, and V1.12 semantic validation plus
frozen-byte identities remain unchanged.
