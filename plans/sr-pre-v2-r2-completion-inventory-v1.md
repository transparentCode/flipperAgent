---
goal: Record the completed shared research infrastructure phase before study-package migration
stage: coder-r2-completion-inventory
date_created: 2026-07-17
last_updated: 2026-07-17
owner: Codex Quant Coder
status: Review Ready
tags: [quant, sr, pre-v2, refactor, r2, inventory]
source_plan: plans/architect-to-coder-sr-pre-v2-modular-refactor-v1.md
supplemental_plan: plans/architect-to-coder-sr-pre-v2-streamlined-execution-v1.md
---

# SR Pre-V2 Modular Refactor — R2 Completion Inventory

## Scope and Disposition

R2 shared research infrastructure is complete on
`refactor/sr-pre-v2-modularization`. This record closes R2 only. It neither
migrates a study package nor authorizes R3.

The R2f2 replay-parity extraction was intentionally a no-op. The only
candidate mechanic is V1.12's study-local `_digest`, a direct alias to
`deterministic_hash` with one local caller. Extracting it would create an
unused second alias and would not demonstrate reuse. `ReplayParity`, its
check matrix, and every study-owned parity semantic remain study-owned.

## Canonical Shared Ownership

| Area | Canonical modules | R2 responsibility |
|---|---|---|
| Artifact safety and publication | `research/artifacts/{canonical_json,manifest,path_safety,publisher,validator}.py` | Canonical JSON, strict members, safe immutable publication, member validation |
| Research configuration | `research/config/{strict_yaml,primitives,identities}.py` | Strict YAML boundary, typed scalar/path/hash/UTC validation, small frozen identities |
| Repository provenance | `research/provenance/repository.py` | Repository root/path containment and complete Git identity retrieval |
| Daily frozen source | `research/source/{contracts,frozen}.py` | `SourceBar`, verified byte reading, canonical bar and grid identities |
| Cohort windows | `research/windows/folds.py` | `CohortFold` contract and stable payload |
| Candidate replay | `research/replay/candidates.py` | `CandidateReplay` contract |
| First-touch metrics | `research/metrics/first_touch.py` | `FirstTouchOutcome` contract |

Shared packages are import-only facades through their `__init__.py` files.
The R2 architecture suite verifies that shared research modules import no
study implementation, provider, network, database, holdout, viewer, or
legacy `libs.sr` surface.

## Preserved Public and Compatibility Paths

Historical study paths remain valid compatibility surfaces. The moved class
objects are identical at old and canonical paths:

- `scripts.baseline_trial.contracts.SourceBar` → `research.source.contracts.SourceBar`;
- `scripts.cohort_readiness.contracts.CohortFold` → `research.windows.folds.CohortFold`;
- `scripts.atr_calibration.contracts.CandidateReplay` → `research.replay.candidates.CandidateReplay`;
- `scripts.atr_calibration.metrics.FirstTouchOutcome` → `research.metrics.first_touch.FirstTouchOutcome`.

The historical cohort bar/grid hash functions and V1.12 `_file_identity`
retain their caller-facing error context as thin compatibility wrappers. V1.12
retains its study-owned identity classes, replay-parity record, check matrix,
semantic manifest, and artifact schema.

## Active Architecture Boundaries

The Package A AST suite locks these constraints:

- no active `libs.sr` import;
- no core area (`adapters`, `association`, `config`, `detection`, `domain`,
  `evaluation`, `lifecycle`, `replay`, or `serialization`) imports `research`;
- YAML is imported only by `config/loader.py` and
  `research/config/strict_yaml.py`;
- shared-research subpackages are acyclic;
- no new direct sibling-study import statement is introduced;
- shared package facades are import/export-only.

Two pre-existing top-level import-cycle components are recorded, not expanded:
`config` ↔ `domain` and `scripts` ↔ `tools`. They are R4/R5 cohesion work and
were not modified in R2. The architecture test locks this exact baseline so a
new top-level cycle fails immediately.

## Remaining Sibling-Study Imports

R2 records **41 direct sibling-study import statements**. R3 must reduce these
in dependency order without changing valid behavior.

| Importing study | Imported study | Statements |
|---|---|---:|
| `atr_calibration` | `baseline_trial` | 3 |
| `baseline_adequacy` | `baseline_trial` | 1 |
| `baseline_adequacy` | `cohort_readiness` | 4 |
| `baseline_adequacy` | `geometry_sensitivity` | 2 |
| `candidate_reinforcement_audit` | `baseline_adequacy` | 1 |
| `candidate_reinforcement_audit` | `baseline_trial` | 1 |
| `candidate_reinforcement_audit` | `lifecycle_utility` | 3 |
| `cohort_readiness` | `atr_calibration` | 7 |
| `cohort_readiness` | `baseline_trial` | 1 |
| `context_audit` | `baseline_adequacy` | 4 |
| `context_audit` | `baseline_trial` | 1 |
| `context_audit` | `cohort_readiness` | 2 |
| `geometry_sensitivity` | `baseline_trial` | 1 |
| `geometry_sensitivity` | `cohort_readiness` | 6 |
| `lifecycle_utility` | `context_audit` | 4 |

`tools/zone_viewer/payload.py` still imports baseline-trial types as a tooling
compatibility edge. It is outside the sibling-study count and must remain
unchanged until its owning R3 package is migrated.

## Remaining Study-Owned or Duplicated Infrastructure

These concerns are deliberately not generalized in R2:

- frozen-source loading, source-capsule selection, and development-prefix
  policy;
- artifact schemas, semantic manifest recomputation, and study dispositions;
- study-owned replay parity matrices and diagnostics;
- first-touch and outcome policies beyond the neutral outcome record;
- fold/window selections, gates, venue/asset/timeframe input, and every trial
  configuration;
- historical CLI/import facades and viewer-specific payload assembly.

They move only with their owner in the ordered R3 packages. R2 introduced no
provider, network, database, holdout, viewer, production, configuration, or
artifact behavior change.

## Files Above 500 Lines Awaiting Ownership Work

| Lines | File | Planned owner phase |
|---:|---|---|
| 1,075 | `scripts/baseline_adequacy/contracts.py` | R3c |
| 816 | `scripts/atr_calibration/artifacts.py` | R3a |
| 731 | `scripts/cohort_readiness/contracts.py` | R3b |
| 711 | `domain/contracts.py` | R4 domain cohesion |
| 683 | `evaluation/contracts.py` | R4 evaluation cohesion |
| 679 | `scripts/candidate_reinforcement_audit/contracts.py` | R3d |
| 659 | `scripts/baseline_trial/contracts.py` | R3a |
| 651 | `scripts/lifecycle_utility/contracts.py` | R3d |
| 651 | `evaluation/diagnostics.py` | R4 evaluation cohesion |
| 578 | `scripts/baseline_trial/artifacts.py` | R3a |
| 557 | `scripts/context_audit/contracts.py` | R3c |
| 528 | `scripts/candidate_reinforcement_audit/config.py` | R3d |
| 513 | `scripts/candidate_reinforcement_audit/audit.py` | R3d |

## Frozen Evidence Lock

| Item | Identity |
|---|---|
| `configs/sr.yaml` SHA-256 | `0c7c11aea8f1ea1e11ef810a6f38d7370a14834c1517d4aab43ac71c378a2119` |
| V1.12 trial YAML SHA-256 | `8a1c2f2c72213e62638ead381c0f7a50a67d96b527f799afe878065d59b93665` |
| V1.12 resolved config hash | `9855c190ed91744b7a6bd86590be33d480bdf44cc94cc51a29e82eec9d4b099e` |
| V1.12 manifest SHA-256 | `c2d0e03f43ea1154bac9c005a2c4d021188a33f56d4ddd17dd6376b9f77c43e6` |
| V1.12 audit SHA-256 | `41bd97da3cef62f10a96f263ac0278e0aff524ebe8337abce0aee986995fee32` |
| Bundle ID | `fd3eaf4cb58a23ee47c0f8645a3d4affd09ef05bf3cafb74831621826a58c206` |
| Audit ID | `cd452938e2befc66f0d2a4e12d79083b88cf6e03a3124180c356d56a6f2b8adb` |
| Disposition | `INSUFFICIENT_REINFORCEMENT_EVIDENCE` |

The locked accounting remains 65 candidates, 50 created zones, 15 eligible
matches, and 13 unique reinforced zones. No bundle or evidence was regenerated
in R2.

## R3 Entry Conditions

R3 may begin only after independent approval of this R2 package and a clean
worktree. The first authorized package is R3a: baseline trial followed by ATR
calibration. It must retain public imports and CLI paths through import-only
facades, preserve frozen evidence bytes and all valid behavior, remove only
the relevant sibling-study edges, and rerun the full deterministic validation
gate. No provider call, source refresh, holdout access, artifact publication,
V2 model work, tuning, or merge is authorized.

## Package A Validation

| Check | Result |
|---|---|
| R2-focused research/architecture/baseline/ATR/cohort/V1.12 suite | **344 passed** in 68.10s |
| Full active SR suite | **817 passed** in 641.07s |
| Ruff on touched paths | Passed |
| Full `src/libs/models/sr` compilation | Passed |
| `git diff --check` | Passed |
| V1.12 semantic validation | Passed: `fd3eaf4c…`, `cd452938…`, `INSUFFICIENT_REINFORCEMENT_EVIDENCE` |
| Frozen configuration and artifact SHA-256 comparison | Exact match |
