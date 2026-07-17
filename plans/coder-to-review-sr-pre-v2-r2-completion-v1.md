---
goal: Request independent review of completed SR pre-V2 shared research infrastructure
stage: coder-to-review
date_created: 2026-07-17
last_updated: 2026-07-17
owner: Codex Quant Coder
status: Review Ready
tags: [handoff, quant, sr, pre-v2, refactor, r2]
source_plan: plans/architect-to-coder-sr-pre-v2-modular-refactor-v1.md
supplemental_plan: plans/architect-to-coder-sr-pre-v2-streamlined-execution-v1.md
---

# Coder to Review — SR Pre-V2 Modular Refactor R2 Completion

## Verdict Requested

Review Package A only: R2 shared research infrastructure closure. R3 has not
started.

## Delivered Scope

- R2f2 recorded as an intentional no-op: no shared parity module was added
  because the sole candidate is V1.12's one-caller study-local `_digest` alias.
  V1.12 `ReplayParity`, its check matrix, and parity semantics remain
  study-owned.
- Added AST architecture enforcement in
  `tests/models/sr/architecture/test_research_boundaries.py`.
- Added the durable R2 ownership/dependency inventory:
  `plans/sr-pre-v2-r2-completion-inventory-v1.md`.
- Preserved all study code, V1.12 artifact bytes, frozen configuration, source,
  provider, holdout, viewer, and production behavior.

## Architecture Assertions

The new suite rejects active legacy `libs.sr`, core-to-research dependencies,
shared-research study/runtime-service imports, YAML outside the two canonical
loaders, new sibling-study import statements, new top-level import-cycle
components, and executable shared-package facades.

The recorded R2 baseline is 41 direct sibling-study import statements. The
only broad top-level cycles are the pre-existing `config` ↔ `domain` and
`scripts` ↔ `tools` components; they are locked against expansion and deferred
to R4/R5 cohesion.

## Frozen Evidence Assertions

- `configs/sr.yaml` SHA-256:
  `0c7c11aea8f1ea1e11ef810a6f38d7370a14834c1517d4aab43ac71c378a2119`
- Bundle: `fd3eaf4cb58a23ee47c0f8645a3d4affd09ef05bf3cafb74831621826a58c206`
- Audit: `cd452938e2befc66f0d2a4e12d79083b88cf6e03a3124180c356d56a6f2b8adb`
- Manifest SHA-256:
  `c2d0e03f43ea1154bac9c005a2c4d021188a33f56d4ddd17dd6376b9f77c43e6`
- Audit SHA-256:
  `41bd97da3cef62f10a96f263ac0278e0aff524ebe8337abce0aee986995fee32`
- Config hash:
  `9855c190ed91744b7a6bd86590be33d480bdf44cc94cc51a29e82eec9d4b099e`
- Disposition: `INSUFFICIENT_REINFORCEMENT_EVIDENCE`

## Validation Evidence

| Check | Result |
|---|---|
| R2-focused research/architecture/baseline/ATR/cohort/V1.12 suite | **344 passed** in 68.10s |
| Full active SR suite | **817 passed** in 641.07s |
| Ruff on touched paths | Passed |
| Full SR compilation | Passed |
| `git diff --check` | Passed |
| V1.12 semantic validation | Passed; returned approved bundle, audit, and disposition |
| Frozen trial, config, manifest, and audit identities | Exact SHA-256 match |

## Review Focus

1. Confirm that no useful two-consumer parity primitive was omitted.
2. Confirm the AST suite records—not prematurely removes—the R3 sibling-edge
   baseline, and does not permit new edges.
3. Confirm R2 shared modules remain neutral, study-free, and I/O-limited to
   their approved responsibilities.
4. Recompute V1.12 semantic validation and compare frozen bytes and IDs.
5. Confirm no R3 package migration or forbidden source/evidence operation
   occurred.

## Next Step if Approved

Begin R3a only: migrate baseline trial, then ATR calibration, with compatibility
facades and no behavior or evidence change. Do not merge or begin another R3
package before its approval gate.
