# Legacy Trendlines Consolidation C3
## Relocate the Canonical Plural Package

## 1. Disposition

C3 completed. `src/libs/trendlines/` moved to `src/libs/models/trendlines/`; `app.trendlines` remains as compatibility namespace mapped to new physical package. No commit created.

## 2. Starting branch and commit

- Branch: `research/legacy-trendlines-quality-stability-v1` (`git branch --show-current`).
- Starting HEAD: `e858d7fb6744240819d6682b996cae6ad3d55d3e` (`git rev-parse HEAD`), committed C2-C.
- Worktree: `/Users/aloobhujia/flipperAgent-wt-legacy-trendlines`.
- Starting status: clean. Final status is listed in section 17.

## 3. Environment and worktree proof

- Python: `/Users/aloobhujia/flipperAgent/.venv/bin/python`, version `3.13.13`.
- Ruff: `/Users/aloobhujia/.local/bin/ruff`, version `0.15.20`.
- `PYTHONPATH`: `$PWD/src:$PWD`.
- Pre-relocation imports resolved inside this worktree for `app.trendlines` and `libs.trendlines`.
- Post-relocation imports resolved inside this worktree for `app.trendlines`, `libs.models.trendlines`, and preserved Trendline V2 modules.

## 4. Immutable source inventory

Before relocation, `src/libs/trendlines/` contained 147 tracked and 147 physical files. Its recorded Git tree was:

```text
d6bb9ae4602eacbeb1391d18e172971908ec4b09
```

The moved package contains 147 tracked/physical files and 737,351 total lines. File types: 117 Python, 11 Markdown, 19 other tracked files. Post-move `git diff --name-status` reports 147 source-path renames; unchanged files are `R100`.

## 5. Consumer inventory

Pre-relocation direct `libs.trendlines` imports were limited to three files:

- `src/libs/models/regime_v2/adapters/trendline_feature_producer.py`: root, boundary, and signals utility imports.
- `src/libs/models/regime_v2/scripts/collect_shadow_binance.py`: boundary import.
- `tests/test_regime_v2_trendline_feature_producer.py`: boundary import.

All five import statements were repointed to `libs.models.trendlines`. Literal dynamic-import search found no executable `libs.trendlines` loader. Post-relocation anchored executable-import search returned zero matches. Internal `app.trendlines.*` imports inside the moved package were intentionally preserved.

## 6. Pre-relocation baseline

- Canonical suite at `src/libs/trendlines/tests`: 266 collected, 266 passed.
- Direct RegimeV2 adapter test: 6 passed.
- Full Trendline V2/viewer suites: 281 collected, 281 passed.
- `tests/scripts`: 283 passed, 21 skipped.
- Durable retirement boundary: 5 passed.

## 7. Package relocation

Executed `git mv src/libs/trendlines src/libs/models/trendlines`.

Verified:

- `src/libs/trendlines/` is absent.
- `src/libs/models/trendlines/` exists with all 147 files.
- No tracked files remain under the old source path.
- No package contents were split, renamed, or algorithmically changed.

## 8. `app.trendlines` shim repointed

In `src/app/trendlines/__init__.py`, `_TRENDLINES_ROOT` now resolves to `libs/models/trendlines`. Existing `__path__`, public exports, and `app.trendlines.*` module identities remain intact. Final physical path:

```text
/Users/aloobhujia/flipperAgent-wt-legacy-trendlines/src/libs/models/trendlines
```

Added narrow `# noqa: E402` markers to intentional post-`__path__` imports so Ruff accepts this existing bootstrap pattern; runtime behavior is unchanged.

## 9. Direct consumers migrated

Three consumer files were migrated to the canonical library namespace:

- `src/libs/models/regime_v2/adapters/trendline_feature_producer.py`
- `src/libs/models/regime_v2/scripts/collect_shadow_binance.py`
- `tests/test_regime_v2_trendline_feature_producer.py`

No RegimeV2 feature semantics or signal behavior changed.

## 10. Canonical public contract updated

Moved `src/libs/models/trendlines/__init__.py` now identifies `libs.models.trendlines` as canonical while preserving public exports. `src/libs/models/trendlines/tests/test_public_api.py` asserts representative identity parity between `libs.models.trendlines` and `app.trendlines` for `TrendlinePipelineConfig`, `PivotSet`, `Trendline`, `TrendlineFitResult`, `run_trendline_pipeline`, `fit_trendlines`, and `fit_trendlines_to_boundary`.

Assertions were folded into existing `test_public_contract_exports_are_stable` to preserve canonical collection at 266 tests.

## 11. Durable relocation boundary

`tests/models/test_legacy_trendline_retirement.py` now:

- treats old `src/libs/trendlines/` and `libs.trendlines` as retired;
- scans all Python files under `src`, `tests`, `scripts`, and `conductor` without singular-package exclusions;
- verifies new package path/module presence and `app.trendlines.__path__` ownership.

Retirement boundary increased from 5 to 6 tests.

## 12. Structural namespace proof

- `importlib.util.find_spec("libs.trendlines")` is `None`.
- `importlib.util.find_spec("libs.models.trendlines")` is non-`None`.
- `libs.models.trendlines.__file__` is under `src/libs/models/trendlines/`.
- `app.trendlines.__path__[0]` equals the new physical package root.
- Anchored executable `libs.trendlines` import search: zero matches.
- Preserved tracked counts: Trendline V2 33, `app/trendlines` 1, V2 config 1.

## 13. Post-relocation test results

- Canonical suite at `src/libs/models/trendlines/tests`: 266 collected, 266 passed.
- RegimeV2 adapter test: 6 passed.
- Full Trendline V2/viewer suites: 281 collected, 281 passed.
- `tests/scripts`: 283 passed, 21 skipped.
- Durable relocation boundary: 6 passed.
- Canonical/compatibility public identity smoke: passed.

## 14. Static validation

- `compileall`: passed for moved package, shim, direct consumers, and boundary tests.
- Ruff: passed for all C3 validation targets.
- `git diff --check`: passed.
- Repository-local `__pycache__` directories generated by validation were removed.

## 15. Files changed

- 147 files moved from `src/libs/trendlines/` to `src/libs/models/trendlines/`.
- Modified shim: `src/app/trendlines/__init__.py`.
- Modified direct consumers: `src/libs/models/regime_v2/adapters/trendline_feature_producer.py`, `src/libs/models/regime_v2/scripts/collect_shadow_binance.py`, `tests/test_regime_v2_trendline_feature_producer.py`.
- Modified canonical init/public test and durable retirement boundary under their new/current paths.
- Added this handoff.

## 16. Git diff summary

`git diff --name-status HEAD` reports 147 source renames plus five standalone modified paths and two modified rename entries. The source move is content-preserving except for the canonical init documentation and public-test assertions. No deletion or addition exists outside the authorized relocation and C3 files.

## 17. Git status

Final status is intentionally dirty and uncommitted for review: the 147-file relocation, seven authorized content modifications, and this new handoff. No unrelated or protected path changed. No C3 commit was created.

## 18. Commands executed

Preflight and inventory: `git branch --show-current`, `git rev-parse HEAD`, `git status`, `git worktree list`, `git log`, `git ls-files`, `git rev-parse HEAD:src/libs/trendlines`, `find`, `wc`, and module-resolution smoke scripts.

Consumer proof: anchored `grep` searches for direct/dynamic `libs.trendlines` imports and post-move namespace checks.

Mutation: `git mv src/libs/trendlines src/libs/models/trendlines`; targeted source/test edits; `apply_patch` for final test/lint/handoff changes.

Validation: canonical pytest collection/execution, RegimeV2 adapter pytest, full V2/viewer collection/execution, scripts pytest, retirement-boundary pytest, import identity smoke, `compileall`, Ruff, `git diff --check`, and cache cleanup.

No network, optimizer, replay, causality, or L0-B workflow was run.

## 19. Residual risks

- Persisted/internal class identities remain under `app.trendlines.*` by design; C3 did not perform an 88-file identity rewrite.
- `app.trendlines` remains a compatibility namespace and depends on its runtime `__path__` bootstrap.
- Broad final ownership and repository regression remain C4 scope.

## 20. Recommended next phase

`C4 — Enforce final single-package ownership and broad repository regression`

READY_FOR_C4_FINAL_OWNERSHIP_REGRESSION
