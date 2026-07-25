# Legacy Trendlines Consolidation C2-C
## Delete the Singular `trendline` and `trendline_family` Packages

## 1. Disposition

C2-C complete. The singular `trendline` and `trendline_family` packages were
deleted after consumer, inventory, and regression gates passed. Canonical
plural trendlines, app compatibility shim, and Trendline V2 remain intact.

Final disposition:

READY_FOR_C3_CANONICAL_PLURAL_RELOCATION

## 2. Starting branch and commit

- Branch: `research/legacy-trendlines-quality-stability-v1`.
- Starting HEAD: `e90fddaa68d930744261ee5d207d6ce2aec869b6`.
- Starting commit: `refactor: retire legacy trendline configuration`.
- Starting status: clean.
- C2-B2b was committed before C2-C began.

## 3. Environment and worktree proof

- Python: `/Users/aloobhujia/flipperAgent/.venv/bin/python`, version 3.13.13.
- Ruff: `/Users/aloobhujia/.local/bin/ruff`, version 0.15.20.
- `PYTHONPATH=$PWD/src:$PWD`.
- Before deletion, `app.trendlines`, `libs.trendlines`,
  `libs.models.trendline`, `libs.models.trendline_family`, and
  `libs.models.trendline_v2` resolved inside this worktree.
- Only root `AGENTS.md` applies; no nested `AGENTS.md` exists.
- No dependencies were installed or upgraded.

## 4. Immutable package inventory

### `src/libs/models/trendline/`

- 93 tracked files.
- 92 Python files and 1 Markdown file.
- 19,377 lines.
- Git tree: `052d2358892a2557338b1dcfc8321248050253bc`.

### `src/libs/models/trendline_family/`

- 37 tracked files.
- 37 Python files.
- 155 lines.
- Git tree: `a0fbda21d744ea955192cd98e8513fd63a6762a5`.

Combined inventory: 130 files and 19,532 lines. Physical file count matched
130 before deletion. No untracked or ignored package files remained after
generated `__pycache__` cleanup.

## 5. Pre-deletion consumer proof

Static import search and literal dynamic-import search found zero executable
consumers outside the two retiring package roots. The durable retirement
boundary passed `4 tests` before deletion.

Allowed negative boundary strings were not treated as consumers. No consumer
was migrated or rewritten.

## 6. Pre-deletion regression baseline

- Canonical plural trendlines: 266 passed.
- Full Trendline V2/viewer collection: 281 tests collected.
- Full Trendline V2/viewer execution: 281 passed.
- Complete scripts suite: 283 passed, 21 skipped.

The 21 script-suite skips were unchanged pre-existing skips.

## 7. `trendline` package deleted

Deleted complete:

`src/libs/models/trendline/`

Deleted 93 tracked files and 19,377 lines using `git rm -r`.

## 8. `trendline_family` package deleted

Deleted complete:

`src/libs/models/trendline_family/`

Deleted 37 tracked files and 155 lines using `git rm -r`.

No tombstone, forwarding package, renamed copy, symlink, or code relocation was
created.

## 9. Durable retirement boundary extended

Modified:

`tests/models/test_legacy_trendline_retirement.py`

Changes:

- Added retired package paths for `trendline`, `trendline_family`, and
  `trendlines_old`.
- Removed package-root scanner exclusions.
- Scanner now covers every Python file under `src/`, `tests/`, `scripts/`, and
  `conductor/`.
- Added removed-module checks for all three singular/archive module names.
- Added `test_retired_singular_model_packages_are_absent`.

Post-change retirement boundary: `5 passed`.

## 10. Structural module-absence proof

Passed:

- Both singular package directories physically absent.
- `src/libs/models/trendlines_old/` absent.
- No tracked files remain under either singular path.
- Fresh-process `find_spec` checks report all three singular/archive modules
  absent.
- Static and dynamic executable-import searches report no matches.
- `src/libs/models/trendlines/` was not created.

## 11. Preserved ownership proof

Preserved tracked counts:

- `src/libs/models/trendline_v2/`: 33 files.
- `src/libs/trendlines/`: 147 files.
- `src/app/trendlines/`: 1 file.
- `configs/trendline_v2.yaml`: 1 file.

Preserved imports resolved inside this worktree:

- `app.trendlines`.
- `libs.trendlines`.
- `libs.models.trendline_v2`.

No preserved path changed.

## 12. Post-deletion test results

- Retirement boundary: 5 passed.
- Canonical plural trendlines: 266 passed.
- Full Trendline V2/viewer collection: 281 tests collected.
- Full Trendline V2/viewer execution: 281 passed.
- Complete scripts suite: 283 passed, 21 skipped.
- Preserved-owner import smoke: passed.

No test was skipped or weakened to obtain passing results.

## 13. Static validation

- Compileall: passed for preserved source paths and retirement test.
- Ruff: passed for retirement test.
- `git diff --check`: passed.
- Validation-created repo-local `__pycache__` directories were removed.

## 14. Files changed

- Deleted 93 files under `src/libs/models/trendline/`.
- Deleted 37 files under `src/libs/models/trendline_family/`.
- Modified `tests/models/test_legacy_trendline_retirement.py`.
- Added this handoff.

No canonical plural, app shim, V2, V2 configuration, artifact, or historical
plan changed.

## 15. Git diff summary

- 130 package files deleted.
- 19,532 package lines deleted.
- Retirement test updated.
- Handoff remains untracked pending review.

## 16. Git status

Expected current status contains only:

- `D` files under `src/libs/models/trendline/`.
- `D` files under `src/libs/models/trendline_family/`.
- `M tests/models/test_legacy_trendline_retirement.py`.
- `?? plans/coder-to-orchestrator-legacy-trendlines-c2c-delete-singular-packages-v1.md`.

C2-C was not committed.

## 17. Commands executed

- C2-B2b approved-unit commit and clean-status verification.
- C2-C branch, HEAD, worktree, history, deletion-state, and instruction
  preflight.
- Codebase-memory search attempt and direct required source review.
- Environment and preserved-owner import verification.
- Tracked/physical inventory, line counts, file types, and Git tree identities.
- Static/dynamic consumer searches and pre-deletion retirement boundary.
- Canonical, full V2/viewer, and scripts pre-deletion baselines.
- Git-aware deletion of both singular packages.
- Retirement-boundary update and package/module absence checks.
- Preserved-owner counts/import smoke.
- Canonical, full V2/viewer, and scripts post-deletion regressions.
- Compileall, Ruff, cache cleanup, protected-scope checks, and
  `git diff --check`.

## 18. Residual risks

- Canonical plural relocation remains pending C3.
- `src/app/trendlines/` remains a compatibility shim until relocation review.
- No L0-B work was started.

## 19. Recommended next phase

C3 — Relocate `src/libs/trendlines/` to
`src/libs/models/trendlines/`

Do not begin L0-B in this phase.

READY_FOR_C3_CANONICAL_PLURAL_RELOCATION
