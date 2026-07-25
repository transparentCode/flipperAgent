# Legacy Trendlines Consolidation C3-R1a
## Canonicalise All Trendlines Imports and Module Identities

## 1. Disposition

C3-R1a completed. Canonical package implementation, tests, documentation, CLI strings, workflow metadata, logger names, and module-identity assertions now use `libs.models.trendlines`. `src/app/trendlines/` remains temporarily and has no model/production consumer.

## 2. Starting branch and commit

- Branch: `research/legacy-trendlines-quality-stability-v1`.
- Starting C3 checkpoint: `bec1ae8 refactor: relocate canonical plural trendlines package`.
- Worktree: `/Users/aloobhujia/flipperAgent-wt-legacy-trendlines`.
- Starting status: clean after C3 commit. C3-R1a changes remain uncommitted.

## 3. Environment and package proof

- Python: `/Users/aloobhujia/flipperAgent/.venv/bin/python`, 3.13.13.
- Ruff: `/Users/aloobhujia/.local/bin/ruff`, 0.15.20.
- `PYTHONPATH`: `$PWD/src:$PWD`.
- Canonical package tree: `d6bb9ae4602eacbeb1391d18e172971908ec4b09`.
- Canonical package count: 147 tracked and physical files.
- Preserved Trendline V2 count: 33 tracked files.

Codebase-memory re-index was attempted after C3 but crashed on one file; graph search confirmed stale pre-C3 paths. Live grep/AST inventory was used as mandated fallback. No production behavior depended on graph output.

## 4. Pre-change namespace inventory

Live inventory before rewrite:

```text
production Python files: 57
test Python files:       34
Markdown files:           9
total files:             100
app.trendlines matches: 333
```

The task brief listed 328 occurrences; current-checkout grep returned 333, so 333 is recorded as authoritative. The pre-change executable import scan covered 89 files and 241 import lines under the broad absolute-import pattern.

Special references found included:

- four logger callsites in optimization/signals code;
- two CLI dispatch module strings;
- one workflow metadata module value;
- six Python/Markdown CLI examples in workflow docs and workflow docstrings;
- six `__module__` assertions in `test_signals.py`;
- monkeypatch/module-path strings in workflow and drift-monitor tests.

## 5. Pre-change regression baseline

- Canonical suite: 266 collected, 266 passed.
- RegimeV2 adapter test: 6 passed.
- Full V2/viewer suites: 281 collected, 281 passed.
- `tests/scripts`: 283 passed, 21 skipped.
- Retirement boundary: 6 passed.

## 6. Production namespace rewrite

All 57 production Python files containing the old namespace were rewritten to canonical absolute imports. This includes regular, `TYPE_CHECKING`, and lazy imports. No function signatures, algorithms, configuration semantics, registry behavior, or exception timing changed.

Canonical package root imports in `src/libs/models/trendlines/__init__.py` now use `libs.models.trendlines`, and its description states that this is the sole canonical model namespace.

## 7. Test namespace rewrite

All 34 canonical test Python files containing the old namespace were rewritten. This includes imports, monkeypatch targets, workflow module paths, CLI paths, and module-identity assertions. `test_signals.py` now expects `libs.models.trendlines.signals.*` identities.

`test_public_api.py` no longer imports `app.trendlines` or compares compatibility objects. It asserts canonical ownership for `PivotSet`, `Trendline`, `TrendlineFitResult`, `TrendlinePipelineConfig`, `RDPZigZagPivotExtractor`, `run_trendline_pipeline`, `fit_trendlines`, and `fit_trendlines_to_boundary` while preserving the 266-test count.

## 8. Import-boundary enforcement

`src/libs/models/trendlines/tests/test_import_boundaries.py` now uses `_absolute_imports()` to collect all absolute `ast.Import` and level-zero `ast.ImportFrom` modules. Relative imports remain excluded.

The former cross-module compatibility test is now `test_trendlines_package_has_no_app_namespace_dependencies`; it rejects every absolute import equal to or below `app`. Existing canonical layer restrictions, geometry/alpha restrictions, notebook checks, and single-definition checks remain active.

## 9. CLI, logger, metadata, and documentation rewrite

- Four logger callsites now use canonical `libs.models.trendlines` logger names.
- Two CLI dispatch strings now load canonical workflow modules.
- Workflow metadata now records `libs.models.trendlines.cli`.
- Python and Markdown command examples now use `python -m libs.models.trendlines.cli`.
- All nine affected Markdown files under `src/libs/models/trendlines/docs/` were updated.

No algorithm or documentation claim beyond namespace/path references was changed.

## 10. Temporary compatibility shim

`src/app/trendlines/__init__.py` remains for C3-R1b. Its public re-exports now import from `libs.models.trendlines`; it retains only the physical `__path__` mapping and no independent owner implementation. Its docstring marks it temporary. No import rooted at `app.trendlines` remains in the shim.

## 11. Structural namespace proof

- `grep -RIn 'app.trendlines' src/libs/models/trendlines`: zero matches.
- Canonical executable imports after rewrite: 241 lines.
- External executable `app.trendlines` imports: one, `tests/models/test_legacy_trendline_retirement.py`, retained as the C3-R1b compatibility smoke.
- No `libs.trendlines` executable imports were introduced. Remaining `libs.trendlines` strings occur only in negative boundary assertions in V2/retirement tests.
- Canonical class identity smoke passed for `PivotSet`, `Trendline`, `TrendlineFitResult`, `run_trendline_pipeline`, and `AlphaSignal`.
- `python -m libs.models.trendlines.cli --help` passed.
- All canonical package layers imported successfully.

## 12. Post-change test results

- Canonical suite: 266 collected, 266 passed.
- RegimeV2 adapter: 6 passed.
- Full V2/viewer suites: 281 collected, 281 passed.
- `tests/scripts`: 283 passed, 21 skipped.
- Retirement boundary: 6 passed.
- Focused public API/import-boundary/signals group: 21 passed.

## 13. Static validation

- `compileall` over canonical package, shim, and retirement boundary: passed.
- `git diff --check`: passed.
- Targeted key-file Ruff check found three unchanged pre-existing `F821` findings in `test_signals.py` for `GeometryAlphaOrchestrator` and `ConfluenceAlphaExtractor`.
- Broad canonical/shim Ruff check found 68 pre-existing findings, including existing unused imports and the same undefined names. No namespace-related lint remediation was applied.
- Generated repository-local `__pycache__` directories were removed.

## 14. Files changed

- 100 files under `src/libs/models/trendlines/`: 57 production Python, 34 test Python, 9 Markdown.
- `src/app/trendlines/__init__.py` temporary shim.
- New handoff: this file.

No Trendline V2, configuration, artifact, historical plan, or unrelated source path changed.

## 15. Git diff summary

Current C3-R1a diff contains namespace-only edits across the 100 canonical package files, the temporary shim, and this handoff. No canonical package file contains the retired namespace. No deletion was performed; compatibility namespace deletion belongs to C3-R1b.

## 16. Git status

Worktree intentionally remains dirty and uncommitted for review. Intended paths are the canonical package namespace edits, temporary shim edit, and this handoff. No unrelated path is present.

## 17. Commands executed

Preflight: branch/HEAD/status/worktree/log checks, package counts, tree identity, Python/Ruff version checks, and import smoke.

Discovery: codebase-memory indexing/search attempt, live grep namespace inventory, AST-oriented import-boundary inspection, and special logger/CLI/metadata/module-identity searches.

Validation: baseline and post-change pytest collection/execution, canonical identity smoke, CLI help, canonical-layer import smoke, compileall, Ruff, `git diff --check`, and repository-local cache cleanup.

No network, optimizer, replay, causality, or L0-B workflow was run.

## 18. Residual risks

- `app.trendlines` still exists temporarily and remains intentionally exercised by one retirement-boundary smoke; C3-R1b must delete it and remove that final compatibility assertion.
- Broad Ruff debt remains pre-existing and was not broadened into this namespace phase.
- Remaining negative `libs.trendlines` strings in V2/retirement tests are boundary assertions, not executable consumers.

## 19. Recommended next phase

`C3-R1b — Delete the app.trendlines compatibility namespace`

READY_FOR_C3R1B_COMPATIBILITY_NAMESPACE_DELETION
