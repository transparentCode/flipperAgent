# Legacy Trendlines Consolidation C1 — Remove trendlines_old

## 1. Disposition

C1 deletion complete. Archived duplicate package removed. Canonical tests, ownership checks, compatibility tests, import smoke, archive-absence checks, compileall, and diff validation passed. Broad Ruff remains non-zero because of 73 diagnostics in unchanged files; changed migration test passes targeted Ruff. No unrelated files modified.

## 2. Starting branch and commit

- Branch: research/legacy-trendlines-quality-stability-v1 (git branch --show-current).
- Starting HEAD: cba86c4ea13c20105d2389afaf584ae69798f62f (git rev-parse HEAD).
- Worktree: /Users/aloobhujia/flipperAgent-wt-legacy-trendlines (git worktree list --porcelain).
- Starting status: clean (git status --short --untracked-files=all).

## 3. Environment and worktree proof

- Python: 3.13.13, executable /Users/aloobhujia/flipperAgent/.venv/bin/python.
- PYTHONPATH: $PWD/src:$PWD.
- app.trendlines: /Users/aloobhujia/flipperAgent-wt-legacy-trendlines/src/app/trendlines/__init__.py.
- libs.trendlines: /Users/aloobhujia/flipperAgent-wt-legacy-trendlines/src/libs/trendlines/__init__.py.
- Before deletion, libs.models.trendlines_old: /Users/aloobhujia/flipperAgent-wt-legacy-trendlines/src/libs/models/trendlines_old/__init__.py.
- Root AGENTS.md, L0-A handoff, and C1-R1 handoff were read. No nested AGENTS.md governs changed paths.

## 4. Active-consumer search

Required executable/dynamic import search over src, tests, scripts, and conductor returned zero matches before deletion. Only remaining archive string is the negative import rule "libs.models.trendlines_old" in tests/models/trendline_family/test_phase_1b_migration.py; it is not an active consumer. Same executable search returned zero matches after deletion.

## 5. Pre-deletion test baseline

- Canonical collection: 266 tests collected in 0.79s from src/libs/trendlines/tests.
- Canonical suite: 265 passed, 1 failed in 7.69s.
- Sole failure: src/libs/trendlines/tests/test_import_boundaries.py::test_shared_boundary_symbols_have_single_canonical_definition.
- Failure cause: duplicate boundary definition reported under src/libs/models/trendlines_old/boundary/__init__.py, including INTERACTION_DIRECTION.
- Migration baseline: 5 passed in 0.37s for tests/models/trendline_family/test_phase_1b_migration.py.

## 6. Deleted archive inventory

- Deleted path: src/libs/models/trendlines_old/.
- Deleted tracked files: 143 (git diff --name-status --diff-filter=D -- src/libs/models/trendlines_old | wc -l; pinned tree also contained 143 files).
- Inventory included archive Python modules, tests, docs, configuration, fitting and pivot code, optimization code and result copies, pipeline/workflow code, registry, signals, and scripts under deleted path.
- Deletion command: git rm -r src/libs/models/trendlines_old.

## 7. Archive-absence proof

- test ! -e src/libs/models/trendlines_old: passed.
- git ls-files "src/libs/models/trendlines_old/**": empty.
- importlib.util.find_spec("libs.models.trendlines_old"): returned None; script printed trendlines_old is absent.
- No empty archive directory, tombstone, forwarding package, or compatibility shim was created.

## 8. Post-deletion validation

- Canonical suite: 266 passed in 7.71s.
- Focused ownership test: 1 passed in 1.09s.
- Migration/compatibility group (test_phase_1b_migration.py, test_import_boundaries.py, test_obsolete_cleanup.py): 17 passed in 3.26s.
- Canonical import smoke: passed for TrendlinePipelineConfig, BoundaryResult, TrendlineFitResult, fit_trendlines, build_extractor("fractal"), and build_fitter("pathfinding").
- Archive import absence: passed.
- Post-deletion executable import search: zero matches.
- compileall for src/libs/trendlines, src/app/trendlines, and the migration test: passed.
- Targeted Ruff for tests/models/trendline_family/test_phase_1b_migration.py: passed.
- Required broad Ruff command: exit 1, reporting 73 diagnostics in unchanged files under requested canonical/app/test paths. No finding reported for changed migration test. No lint remediation was authorised.
- git diff --check: passed.

## 9. Files changed

- Deleted: 143 tracked files under src/libs/models/trendlines_old/.
- Added: plans/coder-to-orchestrator-legacy-trendlines-c1-remove-trendlines-old-v1.md.
- No other existing file modified. src/libs/trendlines/, src/app/trendlines/, src/libs/models/trendline_family/, src/libs/models/trendline/, and src/libs/models/trendline_v2/ remain unchanged.

## 10. Git diff summary

git diff HEAD --stat reports 143-file archive deletion. Handoff is intentionally uncommitted and remains an untracked new file. No other path appears in C1 worktree change set.

## 11. Git status

Expected final status before review:

- D entries only for tracked files under src/libs/models/trendlines_old/.
- ?? plans/coder-to-orchestrator-legacy-trendlines-c1-remove-trendlines-old-v1.md.
- No generated test caches remain in inspected test/source directories.

## 12. Commands executed

Preflight and provenance:

    git branch --show-current
    git rev-parse HEAD
    git status --short --untracked-files=all
    git worktree list --porcelain
    BASE_HEAD="$(git rev-parse HEAD)"

Environment and dependency checks:

    /Users/aloobhujia/flipperAgent/.venv/bin/python --version
    PYTHONPATH="$PWD/src:$PWD" python import/path smoke

Consumer, baseline, deletion, ownership, and absence checks:

    rg -n --glob '*.py' '...trendlines_old...' src tests scripts conductor
    git rm -r src/libs/models/trendlines_old
    git ls-files "src/libs/models/trendlines_old/**"
    python -m pytest --collect-only -q src/libs/trendlines/tests
    python -m pytest -q src/libs/trendlines/tests
    python -m pytest -q src/libs/trendlines/tests/test_import_boundaries.py::test_shared_boundary_symbols_have_single_canonical_definition
    python -m pytest -q tests/models/trendline_family/test_phase_1b_migration.py tests/models/trendline_family/test_import_boundaries.py tests/models/trendline_family/test_obsolete_cleanup.py
    python importlib.util.find_spec archive-absence check

Static and scope checks:

    python -m compileall -q src/libs/trendlines src/app/trendlines tests/models/trendline_family/test_phase_1b_migration.py
    /Users/aloobhujia/.local/bin/ruff check src/libs/trendlines src/app/trendlines tests/models/trendline_family/test_phase_1b_migration.py
    /Users/aloobhujia/.local/bin/ruff check tests/models/trendline_family/test_phase_1b_migration.py
    git diff --check
    git status --short
    git diff --stat
    git diff --name-status

## 13. Residual risks

- Broad Ruff debt remains: 73 diagnostics in unchanged files. C1 did not alter those files; remediation belongs to separate authorised task.
- Historical plans or documentation may still mention trendlines_old; C1 intentionally did not rewrite historical text.
- This phase proves archive removal and canonical ownership only. It does not detach libs.models.trendline runtime or integration consumers.
- No network-enabled workflow, optimizer, or replay study was run.

## 14. Recommended next phase

C2-A — Detach libs.models.trendline from active runtime and integration consumers

## 15. Final disposition

READY_FOR_C2A_RUNTIME_DETACHMENT
