# Legacy Trendlines Consolidation C2-B2a
## Retire the Singular-Model Test Suite and Fixtures

## 1. Disposition

C2-B2a complete. The complete `tests/models/trendline_family/` owner and
compatibility suite, including its two fixtures, was deleted. Singular model
packages, configuration files, canonical plural trendlines, and Trendline V2
remain present. No production source or configuration changed.

Final disposition:

READY_FOR_C2B2B_CONFIG_CONTRACT_RETIREMENT

## 2. Starting branch and commit

- Branch: `research/legacy-trendlines-quality-stability-v1`.
- Starting HEAD: `28df58cdccbcdc3e9b9c946d40e5208fcb2843b0`.
- Starting commit: `refactor: retire legacy trendline research scripts`.
- Starting status: clean.
- C2-B1 was committed before C2-B2a began.

## 3. Environment and worktree proof

- Python: `/Users/aloobhujia/flipperAgent/.venv/bin/python`, version 3.13.13.
- Ruff: `/Users/aloobhujia/.local/bin/ruff`, version 0.15.20.
- `PYTHONPATH=$PWD/src:$PWD`.
- `libs.models.trendline` resolved to the current worktree.
- `libs.models.trendline_family` resolved to the current worktree.
- Only root `AGENTS.md` applies; no nested `AGENTS.md` exists.
- No dependencies were installed or upgraded.

## 4. Pre-deletion suite inventory

`git ls-files tests/models/trendline_family` reported:

- 64 tracked files.
- 62 Python files.
- 2 fixture files.
- 11,071 tracked lines.

Fixtures:

- `tests/models/trendline_family/fixtures/native_pathfinding_reference.json`
- `tests/models/trendline_family/fixtures/pre_phase_1b_family_role.pickle`

## 5. Pre-deletion test baseline

- Singular-model suite: 398 collected, 398 passed in 24.68s.
- Canonical plural trendlines: 266 passed in 8.52s.
- Trendline V2 API/provider/real-asset smoke group: 65 passed in 6.96s.

## 6. Test suite and fixtures deleted

Deleted complete directory:

`tests/models/trendline_family/`

Deleted:

- 64 tracked files.
- 62 Python files.
- 2 fixtures.
- 11,071 lines.

Deletion used `git rm -r tests/models/trendline_family`.

## 7. Retirement-boundary tests added

Added:

`tests/models/test_legacy_trendline_retirement.py`

It contains exactly three tests:

- Retired test tree and both fixture paths are absent.
- AST scan finds no executable singular-model import outside the two excluded
  model packages. It checks `ast.Import`, `ast.ImportFrom`, literal
  `import_module(...)`, and literal `__import__(...)` calls without matching
  `trendline_v2`.
- Earlier C2 integration and forwarding modules remain absent.

Focused result: `3 passed`.

## 8. Structural preservation proof

Passed:

- `tests/models/trendline_family/` absent.
- Both former fixture paths absent.
- No external executable singular-model consumer found by AST boundary test.
- `src/libs/models/trendline/` remains present.
- `src/libs/models/trendline_family/` remains present.
- `configs/trendline_family.yaml` remains present.
- `configs/trendline/README.md` remains present.
- Earlier removed integration, adapter, and ablation modules remain absent.

## 9. Post-deletion test results

- Retirement boundary: 3 passed.
- `tests/scripts`: 283 passed, 21 skipped.
- Canonical plural trendlines: 266 passed.
- Trendline V2 API/provider/real-asset smoke/viewer server group: 70 passed.
- Singular package import/configuration smoke: passed; YAML payload version is
  `1`.

No test was skipped or altered to obtain passing results. The 21 script-suite
skips are pre-existing.

## 10. Static validation

- Compileall: passed for the new retirement test.
- Ruff: passed for the new retirement test.
- `git diff --check`: passed.
- Validation-created repo-local `__pycache__` directories were removed.

## 11. Files changed

- Deleted 64 tracked files under `tests/models/trendline_family/`.
- Added `tests/models/test_legacy_trendline_retirement.py`.
- Added this handoff.

No source package, configuration, artifact, script, V2 path, canonical plural
model, or historical plan changed.

## 12. Git diff summary

The staged deletion diff contains 64 files and 11,071 deletions. The two new
files remain untracked pending review and later commit.

## 13. Git status

Expected current status contains only:

- `D` for 64 files under `tests/models/trendline_family/`.
- `?? tests/models/test_legacy_trendline_retirement.py`.
- `?? plans/coder-to-orchestrator-legacy-trendlines-c2b2a-retire-model-test-suite-v1.md`.

C2-B2a was not committed.

## 14. Commands executed

- Branch, HEAD, status, history, prior deletion-state, and AGENTS discovery.
- Python/Ruff environment and singular-package path verification.
- Pre-deletion 398-test collection/execution.
- Canonical 266-test regression.
- Pre-deletion V2 65-test boundary group.
- Tracked-file, Python-file, fixture, and line-count inventory.
- `git rm -r tests/models/trendline_family`.
- Retirement-boundary test and structural absence checks.
- Post-deletion scripts, canonical, and V2 70-test regressions.
- Singular package/configuration smoke.
- Compileall, Ruff, cache cleanup, and `git diff --check`.

## 15. Residual risks

- Singular model packages and their configuration remain intentionally pending
  C2-B2b and C2-C.
- Canonical plural package relocation remains pending C3.
- No production runtime behavior changed in C2-B2a.

## 16. Recommended next phase

C2-B2b — Retire legacy trendline configuration and configuration documentation

Do not begin C2-C or L0-B in this phase.

READY_FOR_C2B2B_CONFIG_CONTRACT_RETIREMENT
