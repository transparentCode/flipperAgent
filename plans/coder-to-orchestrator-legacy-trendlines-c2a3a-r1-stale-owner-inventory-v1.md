# Legacy Trendlines Consolidation C2-A3a-R1
## Remove Deleted `shadow.py` from Static Owner Inventory

## 1. Disposition

C2-A3a-R1 complete. Removed one stale static owner-inventory entry from
`tests/models/trendline_family/test_import_boundaries.py`. C2-A3a deletions
remain intact. Compatibility regression now passes `17/17`.

`shadow.py` was not restored. No existence filter was added. No C2-A3a or
C2-A3a-R1 commit was created.

## 2. Starting branch and commit

- Branch: `research/legacy-trendlines-quality-stability-v1`.
- Starting HEAD: `f0af88986d8ceb405b60f835364fb220fbdeeb05`.
- Starting commit: `test: retire trendline family shadow adapter contracts`.
- Worktree: `/Users/aloobhujia/flipperAgent-wt-legacy-trendlines`.
- Existing C2-A3a worktree was intentionally dirty with only authorized C2-A3a
  changes and its blocked handoff.

## 3. Expected dirty-worktree proof

Pre-remediation status contained only the existing C2-A3a change set:

- staged deletions: shadow integration, compatibility adapter, dedicated adapter
  test;
- staged rename: optional-import test to removal test;
- unstaged modifications: integration root and obsolete-cleanup test;
- existing untracked C2-A3a blocked handoff.

After remediation, one additional authorized modified test appears:
`tests/models/trendline_family/test_import_boundaries.py`. This file was the
only R1 code edit.

## 4. Original failure reproduction

Ran:

`pytest -q --tb=short tests/models/trendline_family/test_import_boundaries.py::test_api_and_integration_implementations_use_direct_owners`

Observed `FileNotFoundError` for:

`src/libs/integrations/trendline_regime_v2/shadow.py`

Failure came from `_direct_owner_implementation_files()` returning that path at
the former `tests/models/trendline_family/test_import_boundaries.py:86`, then
`test_api_and_integration_implementations_use_direct_owners()` reading it at
line 157. No other failure cause was present.

## 5. Stale inventory entry removed

Modified only `_direct_owner_implementation_files()` in
`tests/models/trendline_family/test_import_boundaries.py`:

- removed the deleted `shadow.py` path;
- preserved canonical `api.py`;
- preserved canonical `config_loader.py`;
- preserved live `trendline_regime_v2/ablation.py`.

`test_api_and_integration_implementations_use_direct_owners()` was not changed.
No existence filtering was added.

## 6. Import-boundary protections preserved

Unchanged:

- `_FORBIDDEN_PREFIXES`;
- `_FORBIDDEN_CANONICAL_UPSTREAM_PREFIXES`;
- `_TRANSITIONAL_FACADES`;
- `_REGIME_COMPATIBILITY_FILES`;
- AST parsing and direct-owner import checks;
- relative-facade, provider-implementation, and YAML ownership checks.

`ablation.py` remains in direct-owner inventory. All forbidden-import rules
remain unchanged.

## 7. Focused test result

- Previously failing direct-owner test: `1 passed in 0.06s`.
- Complete `test_import_boundaries.py`: `9 passed in 0.43s`.

## 8. Full C2-A3a regression results

- Removal tests: `2 passed in 4.36s`.
- Adapter directory: `2 passed in 3.81s`.
- Ablation/ownership subset: `9 passed in 2.94s`.
- Configuration/MTF group: `43 passed in 1.23s`.
- Canonical trendlines: `266 passed in 8.28s`.
- Compatibility group: `17 passed in 4.11s`.

The deleted standalone shadow-adapter suite was not collected. No tests were
skipped or weakened.

## 9. Structural deletion proof

Passed:

- `shadow.py` absent;
- compatibility adapter absent;
- dedicated adapter test absent;
- deleted modules return `None` from `importlib.util.find_spec`;
- no executable deleted-module references remain under `src`, `tests`,
  `scripts`, or `conductor`;
- integration root `__all__` contains exactly six ablation-owned symbols;
- ablation, configuration, singular trendline, V2, and canonical plural
  trendlines paths remain present.

## 10. Static validation

- Required compileall, including `test_import_boundaries.py`: passed.
- Required Ruff check, including `test_import_boundaries.py`: `All checks passed!`.
- `git diff --check`: passed.
- Generated `__pycache__` files were removed.

## 11. Complete combined file scope

C2-A3a plus R1 contains only:

- deleted `src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py`;
- deleted `src/libs/integrations/trendline_regime_v2/shadow.py`;
- modified `src/libs/integrations/trendline_regime_v2/__init__.py`;
- deleted `tests/models/regime_v2/adapters/test_trendline_family_feature_producer.py`;
- renamed/reworked
  `test_trendline_family_shadow_optional_import.py` to
  `test_trendline_family_shadow_removal.py`;
- modified `tests/models/trendline_family/test_obsolete_cleanup.py`;
- modified `tests/models/trendline_family/test_import_boundaries.py`;
- existing blocked C2-A3a handoff, unchanged;
- this R1 handoff.

Combined tracked diff against starting HEAD: `7 files changed, 21 insertions(+),
1506 deletions(-)`, excluding untracked handoffs.

## 12. Git status

Final worktree remains intentionally uncommitted. Staged deletion/rename state
comes from the existing C2-A3a `git rm`/`git mv` operations. Expected status:

```text
 M src/libs/integrations/trendline_regime_v2/__init__.py
D  src/libs/integrations/trendline_regime_v2/shadow.py
D  src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py
D  tests/models/regime_v2/adapters/test_trendline_family_feature_producer.py
RM tests/models/regime_v2/adapters/test_trendline_family_shadow_optional_import.py -> tests/models/regime_v2/adapters/test_trendline_family_shadow_removal.py
 M tests/models/trendline_family/test_import_boundaries.py
 M tests/models/trendline_family/test_obsolete_cleanup.py
?? plans/coder-to-orchestrator-legacy-trendlines-c2a3a-remove-shadow-adapter-v1.md
?? plans/coder-to-orchestrator-legacy-trendlines-c2a3a-r1-stale-owner-inventory-v1.md
```

## 13. Commands executed

- C2-A3a dirty-worktree preflight and file-scope inspection.
- Required stale-owner failure reproduction.
- One-line inventory remediation via `apply_patch`.
- Focused direct-owner test and complete import-boundary suite.
- Removal, adapter-directory, ablation/ownership, configuration/MTF, canonical,
  and compatibility regressions.
- Deleted-module absence, `find_spec`, executable-reference, integration-root,
  and live-path checks.
- Required compileall, Ruff, `git diff --check`, status, diff, and cache cleanup.

## 14. Residual risks

- C2-A3a and R1 remain uncommitted pending independent review.
- Ablation and trendline-configuration integration surfaces remain live for
  C2-A3b.
- `libs.models.trendline` and `libs.models.trendline_family` remain present.
- GitNexus index metadata was stale; live source inspection, CBM search, and
  executable tests were authoritative.

## 15. Recommended next phase

C2-A3b — Retire ablation and trendline-configuration integration surfaces

READY_FOR_C2A3B_RESEARCH_INTEGRATION_RETIREMENT
