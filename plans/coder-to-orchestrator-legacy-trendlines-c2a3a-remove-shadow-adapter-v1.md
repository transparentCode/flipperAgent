# Legacy Trendlines Consolidation C2-A3a
## Delete the Dead Family-Shadow Adapter and Integration Module

## 1. Disposition

C2-A3a is blocked by an unlisted compatibility-test path inventory. The dead
adapter and shadow integration were removed in the authorized worktree, but the
required compatibility regression now fails because
`tests/models/trendline_family/test_import_boundaries.py` still inventories the
deleted `shadow.py` implementation.

No unauthorized file was modified. No ablation or configuration integration,
singular model, or canonical plural model was deleted. No C2-A3a commit was
created.

## 2. Starting branch and commit

- Branch: `research/legacy-trendlines-quality-stability-v1`.
- Worktree: `/Users/aloobhujia/flipperAgent-wt-legacy-trendlines`.
- Starting commit: `f0af88986d8ceb405b60f835364fb220fbdeeb05`.
- Starting commit message: `test: retire trendline family shadow adapter contracts`.
- C1, C2-A1, C2-A2, and C2-A3-R1 were present in recent history.
- `src/libs/models/trendlines_old/` remained absent.
- Worktree was clean at preflight.

## 3. Environment and worktree proof

- Python: `/Users/aloobhujia/flipperAgent/.venv/bin/python`, version 3.13.13.
- Ruff: `/Users/aloobhujia/.local/bin/ruff`, version 0.15.20.
- `PYTHONPATH` used: `$PWD/src:$PWD`.
- Pre-deletion imports for the adapter package, shadow module, ablation module,
  integration root, and model adapter package resolved inside this worktree.
- No dependencies were installed or upgraded. No network workflow ran.

## 4. Pre-deletion consumer proof

The required module-string search found only expected consumers:

- `src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py`.
- `src/libs/integrations/trendline_regime_v2/__init__.py`.
- `tests/models/regime_v2/adapters/test_trendline_family_feature_producer.py`.
- `tests/models/regime_v2/adapters/test_trendline_family_shadow_optional_import.py`
  negative checks.

The exported-symbol search found only the adapter, shadow integration, root
exports, and dedicated adapter tests. `test_obsolete_cleanup.py` used a
`shadow` package import and identity assertions, which were authorized for
retirement.

Post-edit exact module-string search returns zero matches under `src`, `tests`,
`scripts`, and `conductor`. However, a path-based consumer was not found by
that search:

- `tests/models/trendline_family/test_import_boundaries.py:80-87` includes
  `src/libs/integrations/trendline_regime_v2/shadow.py` in
  `_direct_owner_implementation_files()`.
- `:154-157` opens every listed path during
  `test_api_and_integration_implementations_use_direct_owners`.

This is an active compatibility-test dependency outside C2-A3a’s authorized
write list. It causes required compatibility validation failure after deletion.

## 5. Pre-deletion test baseline

All required pre-deletion baselines passed:

- Dedicated adapter suite: `14 passed in 2.74s`.
- Optional-import suite: `2 passed in 4.79s`.
- Ablation/ownership subset: `9 passed in 3.29s`.
- Decoupled configuration/MTF group: `43 passed in 1.22s`.

## 6. Compatibility adapter deleted

Deleted:

`src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py`

The adapter was removed with `git rm`. No forwarding module, deprecated shim,
tombstone, or module-level fallback was added. Active exports in
`src/libs/models/regime_v2/adapters/__init__.py` were not modified.

Deleted production-file count: `1` compatibility adapter.

## 7. Shadow integration deleted

Deleted:

`src/libs/integrations/trendline_regime_v2/shadow.py`

The ablation implementation in
`src/libs/integrations/trendline_regime_v2/ablation.py` was not modified.

Deleted production-file count: `2` including shadow integration.

## 8. Integration root reduced to ablation

Updated `src/libs/integrations/trendline_regime_v2/__init__.py`:

- Changed module description to `Trendline/RegimeV2 ablation integration.`
- Removed all shadow imports and exports.
- `__all__` now contains exactly:

```text
FEATURE_GROUP_SPECS
FeatureGroupSpec
RegimeFeatureAblationEvaluator
WeightedFeatureScorer
evaluate_regime_feature_group_holdout
run_regime_feature_ablation
```

The integration-root identity check passed. All five removed shadow names are
absent from the root package.

## 9. Obsolete shadow ownership assertions removed

Updated `tests/models/trendline_family/test_obsolete_cleanup.py`:

- Changed `from libs.integrations.trendline_regime_v2 import ablation, shadow`
  to import `ablation` only.
- Removed only the ten shadow identity assertions listed by C2-A3a.
- Preserved `ablation.ContractValidationError is validation.ContractValidationError`.
- Preserved all non-shadow ownership and removed-domain-scaffold assertions.
- Test function count remained unchanged.

## 10. Dedicated tests retired

Deleted:

`tests/models/regime_v2/adapters/test_trendline_family_feature_producer.py`

Deleted test-file count: `1`.

Its adapter behavior assertions were not migrated elsewhere. Core owner-package
tests remain intact.

## 11. Removal tests added

Renamed and rewrote:

- Removed old path:
  `tests/models/regime_v2/adapters/test_trendline_family_shadow_optional_import.py`.
- New path:
  `tests/models/regime_v2/adapters/test_trendline_family_shadow_removal.py`.

The new file contains exactly two tests:

- `test_removed_shadow_modules_are_absent_and_active_adapters_remain_usable`:
  subprocess checks both deleted modules with `importlib.util.find_spec`,
  constructs active `RegimeV2FeatureProducer` and `TrendlineFeatureProducer`,
  and checks deleted modules stay absent from `sys.modules`.
- `test_signal_pipeline_remains_free_of_removed_shadow_api`: subprocess checks
  `RegimeFeaturePipeline.create_optional()`, removed constructor/append-bar
  parameters, removed attributes, and deleted modules absent from
  `sys.modules`.

Removal test count: `2`.

## 12. Structural module-absence proof

Passed:

- Three deleted target paths absent.
- Old optional-import test path absent.
- New removal test path present.
- `find_spec` reports both deleted modules absent.
- Exact executable module-reference search returns zero matches.
- Deleted shadow-symbol search returns zero matches.
- Integration root is ablation-only with exact six-symbol `__all__`.
- Ablation, trendline configuration, singular trendline, V2, and canonical
  plural trendlines paths remain present.

The path-based `test_import_boundaries.py` consumer remains and is the blocker.

## 13. Post-change test results

Passed:

- New removal tests: `2 passed in 6.95s`.
- Adapter directory: `2 passed in 5.47s`; deleted standalone suite was not
  collected.
- Ablation/ownership subset: `9 passed in 3.35s`.
- Configuration/MTF group: `43 passed in 1.23s`.
- Canonical trendlines suite: `266 passed in 8.80s`.

Blocked:

- Compatibility regression: `16 passed, 1 failed in 4.62s`.
- Failing test:
  `tests/models/trendline_family/test_import_boundaries.py::test_api_and_integration_implementations_use_direct_owners`.
- Failure: `FileNotFoundError` opening deleted
  `src/libs/integrations/trendline_regime_v2/shadow.py` from the test’s hard-coded
  direct-owner path list.

Required `17 passed` compatibility result was not achieved. No unauthorized
test edit was made.

## 14. Static validation

- Required compileall for authorized changed files: passed.
- Required Ruff check: `All checks passed!`.
- `git diff --check`: passed.
- Generated `__pycache__` files were removed.

## 15. Files changed

Authorized changes:

- Deleted `src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py`.
- Modified `src/libs/integrations/trendline_regime_v2/__init__.py`.
- Deleted `src/libs/integrations/trendline_regime_v2/shadow.py`.
- Deleted `tests/models/regime_v2/adapters/test_trendline_family_feature_producer.py`.
- Renamed/reworked `tests/models/regime_v2/adapters/test_trendline_family_shadow_optional_import.py`
  to `tests/models/regime_v2/adapters/test_trendline_family_shadow_removal.py`.
- Modified `tests/models/trendline_family/test_obsolete_cleanup.py`.
- Added this handoff.

No other path changed. `tests/models/trendline_family/test_import_boundaries.py`
was read but not modified because C2-A3a does not authorize it.

## 16. Git diff summary

Git records three deletions, one production-root modification, one test
modification, and the authorized test rename/rewrite. The handoff is untracked
and intentionally uncommitted.

The change is incomplete pending resolution of the unlisted path-inventory
contract. No C2-A3a commit was created.

## 17. Git status

Expected final status contains only authorized C2-A3a paths and this handoff;
staged deletion/rename state comes from required `git rm`/`git mv` commands:

```text
 M src/libs/integrations/trendline_regime_v2/__init__.py
D  src/libs/integrations/trendline_regime_v2/shadow.py
D  src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py
D  tests/models/regime_v2/adapters/test_trendline_family_feature_producer.py
RM tests/models/regime_v2/adapters/test_trendline_family_shadow_optional_import.py -> tests/models/regime_v2/adapters/test_trendline_family_shadow_removal.py
 M tests/models/trendline_family/test_obsolete_cleanup.py
?? plans/coder-to-orchestrator-legacy-trendlines-c2a3a-remove-shadow-adapter-v1.md
```

## 18. Commands executed

Preflight and environment:

- `git branch --show-current`
- `git rev-parse HEAD`
- `git status --short --untracked-files=all`
- `git worktree list --porcelain`
- `git log -6 --oneline`
- Archive absence check.
- Python/Ruff version and pre-deletion import-resolution checks.

Discovery and baseline:

- Codebase-memory graph searches for shadow producer, summary, failure-payload,
  and active adapter symbols.
- Required module-reference and exported-symbol searches.
- Required four pre-deletion pytest baselines.
- Source inspection of `test_import_boundaries.py` after compatibility failure.

Implementation and validation:

- `git rm` for two production files and dedicated adapter test.
- `git mv` for optional-import to removal test.
- Integration-root and obsolete-cleanup edits.
- Structural path, `find_spec`, symbol, export, and live-path checks.
- Removal, adapter-directory, ablation/ownership, configuration/MTF, canonical,
  and compatibility pytest runs.
- Required compileall, Ruff, `git diff --check`, and cache cleanup.

## 19. Residual risks

- C2-A3a cannot be accepted until authorized remediation retires or adjusts the
  direct-owner path inventory in `test_import_boundaries.py`.
- Compatibility regression currently fails solely from that stale path list;
  remaining 16 tests pass.
- Ablation and trendline-configuration integrations remain live and untouched.
- Singular trendline packages remain present for later phases.
- GitNexus reported stale index metadata during work; CBM results plus live source
  inspection and executable tests were authoritative.

## 20. Recommended next phase

C2-A3b — Retire ablation and trendline-configuration integration surfaces

BLOCKED_C2A3A_RUNTIME_CONTRACT
