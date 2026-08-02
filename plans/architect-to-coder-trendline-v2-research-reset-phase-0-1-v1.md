---
goal: Lock core Trendline V2 semantics and retire the obsolete script-based research programme without restructuring the core model.
stage: architect-to-coder
date_created: 2026-08-02
last_updated: 2026-08-02
owner: quant-coder
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, trendline-v2, refactor, research-reset, phase-0, phase-1]
---

# Trendline V2 Research Reset — Phase 0 + Phase 1

## Status

`READY_FOR_CODEX_IMPLEMENTATION`

The next owner can act without guessing.

This is one bounded implementation package containing only:

1. **Phase 0 — Core semantic safety lock**
2. **Phase 1 — Retirement of the obsolete research programme**

Stop after this package. Do not begin core modularization, configuration V2, provider decomposition, or notebook work.

## Required role

Act as `quant-coder`.

Read and follow:

- repository root `AGENTS.md`;
- `.agents/skills/quant-coder/SKILL.md`;
- `.agents/skills/mcp-tiered-code-intelligence/SKILL.md`;
- `.agents/skills/codebase-memory/refactoring/SKILL.md`;
- `.agents/skills/codebase-memory/impact-analysis/SKILL.md`.

Use one workspace-writing agent only. This task must run in the dedicated isolated worktree defined below. The primary checkout is read-only for this task.

## Required isolated worktree

The user is working in parallel on another feature. Do not write, stage, switch branches, or run implementation commands in the primary checkout:

```text
/Users/kajukatli/projects/flipperAgent
```

Create exactly one dedicated worktree and branch:

```text
Base commit:   ebc6084049885bee8b07aaf78bfa8d50a4fb0b8b
Branch:        refactor/trendline-v2-research-reset-phase-0-1-v1
Worktree path: /Users/kajukatli/projects/flipperAgent-wt-trendline-v2-research-reset-phase-0-1-v1
```

Required setup rules:

1. Read this handoff first from the primary checkout at:

   ```text
   /Users/kajukatli/projects/flipperAgent/plans/architect-to-coder-trendline-v2-research-reset-phase-0-1-v1.md
   ```

2. Verify the exact base commit still exists locally.
3. Verify the required branch and worktree path do not already exist.
4. Create the branch and worktree directly from the exact base commit. Do not base it on a moving branch after parallel work begins.
5. Materialize a byte-identical copy of this handoff under the worktree's `plans/` directory before implementation, because the source handoff is currently untracked in the primary checkout and is not part of the base commit.
6. Verify the copied handoff hash matches the source handoff hash.
7. Perform every source edit, deletion, test, build, and completion-handoff write inside the dedicated worktree only.
8. Do not create any additional branch or worktree.
9. Do not merge, rebase, cherry-pick, or push from either checkout.
10. Leave the primary checkout untouched even if its status changes while the user works in parallel.

If the branch or path already exists, the base commit is unavailable, or the handoff cannot be copied byte-identically, stop and return `BLOCKED`.

## Objective

Preserve the useful causal Trendline V2 model foundation while deleting the obsolete phase-based research system.

At completion:

- core Trendline V2 identities and serialized semantics are protected by deterministic synthetic tests;
- there is exactly one active Trendline V2 script facade;
- all old Trendline V2 analysis, freeze, replay, validation, benchmark, smoke, and R4/R5 diagnostic machinery is absent from active code;
- active Trendline V2 code and tests contain no hardcoded `/tmp/trendline_v2*` or `/private/tmp/trendline_v2*` paths;
- the generic provider viewer still works;
- the default Trendline V2 test suite is hermetic and does not require historical research artifacts.

## Verified starting state

Verify these facts again from the live checkout before editing:

- primary repository: `/Users/kajukatli/projects/flipperAgent`;
- approved base commit: `ebc6084049885bee8b07aaf78bfa8d50a4fb0b8b`;
- at handoff revision, `main == origin/main == ebc6084049885bee8b07aaf78bfa8d50a4fb0b8b`;
- the primary checkout contained only this untracked architect handoff when the worktree requirement was added;
- required implementation branch: `refactor/trendline-v2-research-reset-phase-0-1-v1`;
- required implementation worktree: `/Users/kajukatli/projects/flipperAgent-wt-trendline-v2-research-reset-phase-0-1-v1`;
- model root: `src/libs/models/trendline_v2/`;
- current Trendline V2 scripts: `23` files and approximately `37,999` lines;
- current dedicated Trendline V2 script tests: `22` files and approximately `16,739` lines;
- current model suite baseline observed during audit: `319 passed, 1 skipped, 1 failed, 9 errors`;
- the failure and errors were caused by missing historical `/tmp` R4/R5 diagnostic artifacts, not by core discovery/selection/tracking/interaction failures;
- no active production module imports the old research scripts except `tools/viewer/diagnostic_export.py`;
- the package dependency graph is currently acyclic.

If the live checkout materially differs, stop and return `BLOCKED` with the exact drift.

# Scope boundaries

## In scope

- Add deterministic core semantic lock tests.
- Delete the obsolete Trendline V2 research/benchmark/smoke/validation scripts.
- Delete their dedicated tests.
- Replace the old viewer-specific script name with one generic thin facade: `scripts/run_trendline_v2.py`.
- Remove R4/R5 diagnostic viewer Python and frontend support.
- Remove `/tmp`-backed frozen viewer acceptance tests.
- Keep and validate the generic provider viewer.
- Update active Trendline V2 README wording to remove the old phase methodology.
- Add retirement-boundary tests that enforce the new state.
- Persist a coder completion report.

## Explicitly not in scope

- No changes to provider mathematics or candidate membership.
- No changes to causal boundaries, timestamp semantics, ordering, or failure states.
- No changes to candidate, evidence, snapshot, policy, family, transition, observation, payload, or configuration identity algorithms.
- No core folder modularization.
- No split of large `contracts.py` modules.
- No configuration schema change.
- No canonical YAML provider values.
- No fresh research notebook yet.
- No `research/` package yet.
- No new research metrics or methodology.
- No data acquisition redesign.
- No viewer runner decomposition.
- No Numba or performance optimization.
- No Hough, pattern, MTF, Regime, signal, quality, storage, or production integration work.
- No migration or preservation of old research artifact schemas, manifests, locks, inventories, or IDs.
- No provider, network, Binance, holdout, or retained-artifact execution.
- No edits to historical `plans/` files other than creating the completion handoff.
- No commit, merge, push, rebase, cherry-pick, primary-checkout branch switch, or worktree creation beyond the one explicitly required isolated worktree.

# Hard core-source freeze

Do not modify these core model areas in this package:

```text
src/libs/models/trendline_v2/api.py
src/libs/models/trendline_v2/configuration/
src/libs/models/trendline_v2/domain/
src/libs/models/trendline_v2/input/
src/libs/models/trendline_v2/discovery/
src/libs/models/trendline_v2/selection/
src/libs/models/trendline_v2/tracking/
src/libs/models/trendline_v2/interaction/
```

The only production model source allowed to change is:

```text
src/libs/models/trendline_v2/README.md
src/libs/models/trendline_v2/tools/viewer/server.py
src/libs/models/trendline_v2/tools/viewer/web/**
```

The two diagnostic Python modules under `tools/viewer/` are deleted, not refactored.

If a core source change appears necessary, stop and return `BLOCKED`; do not broaden scope.

# Phase 0 — Core semantic safety lock

Complete this phase before deleting or modifying any active source file.

## 0.1 Add one deterministic semantic-lock test module

Create:

```text
tests/models/trendline_v2/test_core_semantic_lock.py
```

Use small synthetic, UTC-aware, in-memory fixtures only. Do not read files, call the network, or use `/tmp`.

The module must lock the current exact semantics for representative successful flows:

1. Foundation configuration semantic hash.
2. Confirmed-extrema provider configuration semantic hash.
3. Confirmed OHLCV input identity.
4. Provider request identity and combined configuration identity.
5. Ordered candidate IDs.
6. Ordered provider evidence IDs.
7. Canonical digest of `ProviderResult.to_dict()`.
8. Discovery snapshot ID.
9. Selection policy identity.
10. Selection decision IDs and selection snapshot ID.
11. Tracking policy identity.
12. Tracking family IDs, transition IDs, and tracking snapshot ID.
13. Interaction observation policy identity.
14. Interaction bar ID, ordered observation IDs, and interaction snapshot ID.
15. Root package public `__all__` surface used by current callers.

Use existing synthetic fixture patterns from the current Trendline V2 tests. Do not invent new market or quality semantics.

## 0.2 Capture values before source deletion

Before changing or deleting production code:

- construct the canonical synthetic scenarios against the untouched dedicated worktree at the approved base commit;
- record the exact expected hashes/IDs/digest values in the new test;
- run the new test and confirm it passes against the untouched core source in that worktree;
- include the exact captured values in the coder completion report.

Do not regenerate or update expected values after source changes merely to make the test pass. Any mismatch after deletion is a blocker unless proven to be test-only path ownership with no semantic change.

## 0.3 Public surface rule

The semantic lock should protect the root public surface, not internal research scripts.

The following root call paths must remain importable:

```text
discover_trendlines
select_trendline_candidates
track_trendline_families
build_trendline_interaction_bar
observe_trendline_family_interactions
```

Existing public root types should remain available as currently exported.

# Phase 1 — Retire obsolete research programme

## 1.1 Delete obsolete scripts

Delete these files completely:

```text
scripts/analyze_trendline_v2_actionable_interaction_shortlist.py
scripts/analyze_trendline_v2_candidate_birth_evidence.py
scripts/analyze_trendline_v2_candidate_density.py
scripts/analyze_trendline_v2_candidate_eligibility_families.py
scripts/analyze_trendline_v2_causal_seed_lifecycle_feasibility.py
scripts/analyze_trendline_v2_causal_structural_reachability.py
scripts/analyze_trendline_v2_consensus_corridor_families.py
scripts/analyze_trendline_v2_fresh_scope_family_validation.py
scripts/analyze_trendline_v2_independent_sparse_geometry.py
scripts/analyze_trendline_v2_joint_structural_compression.py
scripts/analyze_trendline_v2_quality_signal_feasibility.py
scripts/analyze_trendline_v2_reachability_asymmetry_attribution.py
scripts/analyze_trendline_v2_sparse_geometry_failure_attribution.py
scripts/analyze_trendline_v2_structural_selection.py
scripts/benchmark_trendline_v2_provider.py
scripts/freeze_trendline_v2_fresh_scope_sources.py
scripts/freeze_trendline_v2_long_horizon_source.py
scripts/replay_trendline_v2_causal_temporal_tracking.py
scripts/replay_trendline_v2_lookback_eviction.py
scripts/run_trendline_v2_real_asset_smoke.py
scripts/validate_trendline_v2_canonical_selection.py
scripts/validate_trendline_v2_tracking_foundation.py
```

Do not migrate their code into `src/`, another script, a notebook, or an archive package.

Historical Git history and `plans/` documents are sufficient archival evidence.

## 1.2 Establish the single facade script

Rename:

```text
scripts/run_trendline_v2_viewer.py
```

to:

```text
scripts/run_trendline_v2.py
```

For this package, preserve the current generic viewer CLI behavior. Keep the facade thin and import-only:

```python
from libs.models.trendline_v2.tools.viewer.runner import main

if __name__ == "__main__":
    raise SystemExit(main())
```

Do not add subcommands or move runner logic into the script in this phase.

Rename and update:

```text
tests/scripts/test_run_trendline_v2_viewer.py
```

to:

```text
tests/scripts/test_run_trendline_v2.py
```

The test must verify that the facade delegates to the library `main` and does not contain model, acquisition, research, or artifact logic.

## 1.3 Delete obsolete script tests

Delete these files completely:

```text
tests/scripts/test_trendline_v2_actionable_interaction_shortlist.py
tests/scripts/test_trendline_v2_candidate_birth_evidence.py
tests/scripts/test_trendline_v2_candidate_density.py
tests/scripts/test_trendline_v2_candidate_eligibility_families.py
tests/scripts/test_trendline_v2_canonical_selection.py
tests/scripts/test_trendline_v2_causal_seed_lifecycle_feasibility.py
tests/scripts/test_trendline_v2_causal_structural_reachability.py
tests/scripts/test_trendline_v2_causal_temporal_tracking.py
tests/scripts/test_trendline_v2_consensus_corridor_families.py
tests/scripts/test_trendline_v2_fresh_scope_family_validation.py
tests/scripts/test_trendline_v2_fresh_scope_sources.py
tests/scripts/test_trendline_v2_independent_sparse_geometry.py
tests/scripts/test_trendline_v2_joint_structural_compression.py
tests/scripts/test_trendline_v2_long_horizon_source.py
tests/scripts/test_trendline_v2_lookback_eviction.py
tests/scripts/test_trendline_v2_quality_signal_feasibility.py
tests/scripts/test_trendline_v2_reachability_asymmetry_attribution.py
tests/scripts/test_trendline_v2_real_asset_smoke.py
tests/scripts/test_trendline_v2_sparse_geometry_failure_attribution.py
tests/scripts/test_trendline_v2_structural_selection.py
tests/scripts/test_trendline_v2_tracking_foundation.py
```

Also delete:

```text
tests/models/trendline_v2/test_provider_benchmark_harness.py
```

because its sole owner is the retired benchmark script.

## 1.4 Remove R4/R5 diagnostic viewer Python

Delete:

```text
src/libs/models/trendline_v2/tools/viewer/diagnostic_export.py
src/libs/models/trendline_v2/tools/viewer/diagnostic_payload.py
tests/models/trendline_v2/tools/viewer/test_diagnostic_payload.py
```

Modify:

```text
src/libs/models/trendline_v2/tools/viewer/server.py
```

so it validates and serves only the generic Trendline V2 viewer bundle schema.

Remove:

- diagnostic imports;
- diagnostic schema branching;
- R4/R5 payload validation;
- source-specific diagnostic behavior.

Preserve all generic bundle security properties:

- exact member set;
- regular-file and symlink rejection;
- duplicate-key rejection;
- canonical JSON byte validation;
- payload hash and length validation;
- bundle identity validation;
- loopback-only server behavior;
- path traversal protection;
- existing generic content types and allowed static paths.

Modify:

```text
tests/models/trendline_v2/tools/viewer/test_server.py
```

by deleting diagnostic-only imports and tests while preserving generic bundle/server security coverage.

## 1.5 Remove diagnostic and `/tmp` frontend support

Delete:

```text
src/libs/models/trendline_v2/tools/viewer/web/tests/diagnostic_payload.test.mjs
src/libs/models/trendline_v2/tools/viewer/web/tests/nearest_now_frozen_payloads.test.mjs
```

The nearest-now frozen-payload test is retired because it directly reads historical `/tmp/trendline_v2_phase*` bundles. Generic nearest-now behavior remains covered by synthetic candidate-filter tests.

Remove diagnostic-only code from:

```text
src/libs/models/trendline_v2/tools/viewer/web/src/contracts.ts
src/libs/models/trendline_v2/tools/viewer/web/src/main.ts
src/libs/models/trendline_v2/tools/viewer/web/src/payload.ts
src/libs/models/trendline_v2/tools/viewer/web/src/trendline_primitive.ts
src/libs/models/trendline_v2/tools/viewer/web/tests/trendline_primitive.test.mjs
```

Remove all of the following concepts:

- diagnostic payload schema;
- R4/R5 constants and source identities;
- contender/control payload types;
- diagnostic-specific line styling;
- diagnostic-specific timeline extension;
- diagnostic-specific details and banners;
- density-control bypass for diagnostics;
- `validateDiagnosticPayload` and `isDiagnosticPayload`;
- diagnostic fixture tests.

Preserve generic provider payload validation, nearest-now, focus, all-raw modes, candidate filtering, line rendering, role styling, and generic payload error handling.

Rebuild TypeScript using the existing package scripts. Update already tracked generated output such as `web/dist/main.js` when changed. Do not force-add ignored `dist/` members that are not already tracked.

## 1.6 Update active README

Modify:

```text
src/libs/models/trendline_v2/README.md
```

Remove the historical phase-based research boundary and R4/R5 references.

State only:

- Trendline V2 is a causal research-stage geometry model;
- it is not production-ready and makes no alpha or trading claim;
- the old phase-based script research programme has been retired;
- the active package currently exposes model primitives and a generic viewer;
- a fresh notebook research workbench will be added in a later approved phase.

Do not document future APIs that do not yet exist.

## 1.7 Add retirement enforcement test

Create:

```text
tests/models/trendline_v2/test_research_retirement.py
```

The test must enforce all of these boundaries:

1. Exactly one top-level script matching `*trendline_v2*.py` exists:

   ```text
   scripts/run_trendline_v2.py
   ```

2. Exactly one top-level script imports `libs.models.trendline_v2`.
3. Active Trendline V2 Python code contains no import from `scripts`.
4. Active source/tests contain no `/tmp/trendline_v2` or `/private/tmp/trendline_v2` literal.
5. Active source/tests contain no references to:

   ```text
   diagnostic_export
   diagnostic_payload
   trendline_v2_r5_diagnostic_viewer
   R4_DIAGNOSTIC
   R5_ATTRIBUTION
   ```

6. No active Python script/module names begin with the retired families:

   ```text
   analyze_trendline_v2_
   freeze_trendline_v2_
   replay_trendline_v2_
   validate_trendline_v2_
   benchmark_trendline_v2_
   run_trendline_v2_real_asset_smoke
   ```

7. Historical `plans/` files are excluded from these ownership scans.
8. The retirement test itself must use repository-relative discovery and must not depend on the developer's home path.

# Expected changed-file boundary

## New or renamed

```text
scripts/run_trendline_v2.py
tests/scripts/test_run_trendline_v2.py
tests/models/trendline_v2/test_core_semantic_lock.py
tests/models/trendline_v2/test_research_retirement.py
plans/coder-to-orchestrator-trendline-v2-research-reset-phase-0-1-v1.md
```

## Modified

```text
src/libs/models/trendline_v2/README.md
src/libs/models/trendline_v2/tools/viewer/server.py
src/libs/models/trendline_v2/tools/viewer/web/src/contracts.ts
src/libs/models/trendline_v2/tools/viewer/web/src/main.ts
src/libs/models/trendline_v2/tools/viewer/web/src/payload.ts
src/libs/models/trendline_v2/tools/viewer/web/src/trendline_primitive.ts
src/libs/models/trendline_v2/tools/viewer/web/tests/trendline_primitive.test.mjs
src/libs/models/trendline_v2/tools/viewer/web/dist/main.js
tests/models/trendline_v2/tools/viewer/test_server.py
```

Additional modified files are allowed only when directly required to remove an executable diagnostic reference or to keep the generic viewer build/tests valid. Explain every additional file in the completion report.

## Deleted

All files explicitly listed in sections 1.1, 1.3, 1.4, and 1.5, plus the old renamed facade/test paths.

# Implementation order

Follow this order exactly:

1. Read the source handoff from the primary checkout.
2. Verify the exact approved base commit, branch absence, worktree-path absence, and primary checkout identity.
3. Create the required isolated branch and worktree from the exact base commit.
4. Copy this handoff byte-identically into the worktree and verify matching hashes.
5. Reopen repository instructions and required skills from inside the worktree.
6. Verify worktree Git status and live inventory.
7. Inspect direct dependents of the deletion targets.
8. Add `test_core_semantic_lock.py`.
9. Capture and freeze exact pre-change IDs/digests.
10. Run the semantic-lock test against untouched source.
11. Rename the single facade script and its test.
12. Delete obsolete research scripts and tests.
13. Delete diagnostic Python modules and tests.
14. Remove diagnostic branches from the generic server.
15. Remove diagnostic and `/tmp` frontend support.
16. Rebuild and run frontend tests.
17. Update README.
18. Add retirement-boundary test.
19. Run focused tests.
20. Run complete scoped validation.
21. Inspect the final worktree diff and self-review.
22. Verify no task writes were made in the primary checkout.
23. Write the coder-to-orchestrator completion handoff inside the worktree.
24. Stop.

Do not mix core modularization into any step.

# Acceptance criteria

The package is complete only when every criterion below is satisfied.

## Core safety

- The new semantic-lock test passes before and after Phase 1 deletion.
- All locked IDs/digests remain exactly unchanged.
- No core source file under the hard freeze changed.
- Root public API imports remain unchanged.

## Research retirement

- All explicitly listed obsolete scripts and tests are absent.
- `scripts/run_trendline_v2.py` is the only active Trendline V2 script.
- No active model source imports `scripts`.
- No active Trendline V2 Python source/test contains hardcoded Trendline V2 `/tmp` paths.
- No active R4/R5 diagnostic Python or frontend code remains.
- No retained test requires old artifact directories.

## Generic viewer

- Generic payload and bundle tests pass.
- Generic bundle security behavior remains covered.
- Frontend generic payload, candidate filtering, nearest, focus, all-raw, and primitive rendering tests pass.
- The thin facade `--help` path works without network access.

## Scope and hygiene

- No network/provider/holdout/artifact execution occurred.
- No historical plan was changed.
- No configuration/YAML file changed.
- No generated research artifact was created in the repository.
- Exactly one dedicated branch/worktree was created as specified.
- All task writes occurred inside that worktree only.
- No task write, stage, branch switch, or implementation command occurred in the primary checkout.
- No commit, merge, push, rebase, or cherry-pick occurred.
- Final worktree `git diff --check` passes.

# Validation commands

Use `.venv/bin/python` and `PYTHONPATH=src` where applicable.

## Pre-change lock validation

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_v2/test_core_semantic_lock.py \
  -q -ra
```

Run this before deletion and again after all changes.

## Focused Python validation

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_v2/test_core_semantic_lock.py \
  tests/models/trendline_v2/test_research_retirement.py \
  tests/models/trendline_v2/tools/viewer/test_payload.py \
  tests/models/trendline_v2/tools/viewer/test_server.py \
  tests/models/trendline_v2/tools/viewer/test_runner.py \
  tests/scripts/test_run_trendline_v2.py \
  -q -ra
```

## Full scoped Python validation

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_v2 \
  tests/scripts/test_run_trendline_v2.py \
  tests/models/test_legacy_trendline_retirement.py \
  -q -ra
```

No failure or error is acceptable. Report all skips exactly.

## Frontend validation

From:

```text
src/libs/models/trendline_v2/tools/viewer/web
```

run:

```bash
npm test
```

Do not perform a network install. If dependencies are unavailable locally, report the exact blocker rather than fetching packages.

## Facade smoke

```bash
PYTHONPATH=src .venv/bin/python scripts/run_trendline_v2.py --help
```

No market-data execution is authorized.

## Static validation

Run Ruff only on new or modified Python files in this package. Do not launch a repository-wide auto-fix.

Expected command shape:

```bash
ruff check \
  scripts/run_trendline_v2.py \
  tests/scripts/test_run_trendline_v2.py \
  tests/models/trendline_v2/test_core_semantic_lock.py \
  tests/models/trendline_v2/test_research_retirement.py \
  src/libs/models/trendline_v2/tools/viewer/server.py \
  tests/models/trendline_v2/tools/viewer/test_server.py
```

Also run:

```bash
PYTHONPATH=src .venv/bin/python -m compileall -q \
  src/libs/models/trendline_v2 \
  scripts/run_trendline_v2.py

git diff --check
```

## Required ownership scans

These must produce the stated result:

```bash
find scripts -maxdepth 1 -type f -name '*trendline_v2*.py' -print | sort
```

Expected exactly:

```text
scripts/run_trendline_v2.py
```

```bash
rg -l 'libs\.models\.trendline_v2' scripts --glob '*.py' | sort
```

Expected exactly:

```text
scripts/run_trendline_v2.py
```

```bash
rg -n '/(private/)?tmp/trendline_v2' \
  src/libs/models/trendline_v2 \
  scripts \
  tests/models/trendline_v2 \
  tests/scripts \
  --glob '*.{py,ts,mjs}'
```

Expected: no matches.

```bash
rg -n 'diagnostic_export|diagnostic_payload|trendline_v2_r5_diagnostic_viewer|R4_DIAGNOSTIC|R5_ATTRIBUTION' \
  src/libs/models/trendline_v2 \
  tests/models/trendline_v2 \
  --glob '*.{py,ts,mjs}'
```

Expected: no matches.

```bash
rg -n 'from scripts|import scripts' \
  src/libs/models/trendline_v2 \
  --glob '*.py'
```

Expected: no matches.

```bash
rg -n 'analyze_trendline_v2_|freeze_trendline_v2_|replay_trendline_v2_|validate_trendline_v2_|benchmark_trendline_v2_|run_trendline_v2_real_asset_smoke' \
  src scripts tests \
  --glob '*.{py,ts,mjs}'
```

Expected: no active-code matches.

# Stop conditions

Stop immediately and return `BLOCKED` if any of the following occurs:

- the new worktree contains any change other than the byte-identical copied architect handoff before implementation begins;
- any task write, stage, branch switch, or implementation command occurs in the primary checkout;
- a deletion target has an unexpected active production consumer outside the listed diagnostic path;
- a core identity or serialized digest changes;
- a hard-frozen core source file appears necessary to modify;
- generic viewer behavior cannot be preserved without broader redesign;
- removing diagnostic support requires changing provider or payload semantics;
- frontend dependencies are unavailable and validation cannot run without network access;
- any scope expansion into YAML, notebook, research package, model modularization, or optimization appears necessary;
- protected historical plan files or unrelated models would need modification;
- validation remains non-hermetic after the obsolete diagnostic path is deleted.

Do not work around a stop condition by weakening a test, regenerating expected hashes, or broadening scope.

# Required completion handoff

Create:

```text
plans/coder-to-orchestrator-trendline-v2-research-reset-phase-0-1-v1.md
```

Use the repository handoff front matter and include:

1. Final status:
   - `READY_FOR_ORCHESTRATOR_REVIEW`, or
   - `BLOCKED`.
2. Scope executed and explicitly not changed.
3. Exact files added, renamed, modified, and deleted.
4. Pre-change semantic-lock values.
5. Proof that the same values pass after deletion.
6. Script and test file counts before and after.
7. Lines removed, added, and net change.
8. Generic viewer changes.
9. Validation commands and exact results.
10. Ownership-scan outputs.
11. Exact base commit, branch name, worktree path, worktree Git status, and diff summary.
12. Proof that the primary checkout was not written to by this task.
13. Self-review findings ordered by severity.
14. Blockers and residual risks.
15. Confirmation that no network/provider/holdout/artifact execution, commit, merge, push, rebase, or cherry-pick occurred.

End the report with exactly one status line:

```text
TRENDLINE_V2_RESEARCH_RESET_PHASE_0_1_READY_FOR_REVIEW
```

or:

```text
TRENDLINE_V2_RESEARCH_RESET_PHASE_0_1_BLOCKED
```

Then stop. Do not begin Phase 2.
