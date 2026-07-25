# Legacy Trendlines Consolidation C2-A3b1
## Retire RegimeV2 Ablation Integration and Compatibility Surfaces

## 1. Disposition

C2-A3b1 complete. The retired RegimeV2 ablation integration, both singular
model ablation forwarders, and their dedicated tests were removed. Canonical
optimization retains generic contracts and evaluators. No trendline
configuration integration, signal application, V2 provider, singular model,
or canonical plural trendlines package was changed. (Commands: scope and
structural checks below.)

## 2. Starting branch and commit

- Branch: `research/legacy-trendlines-quality-stability-v1`.
- Worktree: `/Users/aloobhujia/flipperAgent-wt-legacy-trendlines`.
- Starting HEAD: `55a6467c669e212d8403b3da45dcb86103aa8f7f`.
- Starting commit: `refactor: remove trendline family shadow adapter`.
- Starting status: clean.
- C1 through C2-A3a plus R1 were present in `git log -7 --oneline`.
- `src/libs/integrations/trendline_regime_v2/shadow.py` and
  `src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py`
  were already absent. (Command: C2-A3b1 preflight.)

## 3. Environment and worktree proof

- Python: `/Users/aloobhujia/flipperAgent/.venv/bin/python`, version 3.13.13.
- Ruff: `/Users/aloobhujia/.local/bin/ruff`, version 0.15.20.
- `PYTHONPATH=$PWD/src:$PWD`.
- Pre-deletion imports for the integration, ablation, canonical optimization,
  canonical ablation forwarder, family optimization, and family ablation
  forwarder resolved inside this worktree. (Command: environment import
  verification.)
- No dependency installation, network request, standalone optimizer study, or
  replay study was run outside required pytest suites. (Commands: executed
  validation list.)

## 4. Pre-deletion consumer inventory

The required integration-import search found only the expected consumers:

- `src/libs/models/trendline/optimization/__init__.py`: lazy import in
  `__getattr__`.
- `src/libs/models/trendline/optimization/ablation.py`: forwarding imports.
- `src/libs/models/trendline_family/optimization/ablation.py`: forwarding
  `_reexport_module` call.
- `tests/models/trendline_family/test_ablation_compatibility.py`: integration
  identity test.
- `tests/models/trendline_family/test_phase_1b_migration.py`: scorer identity
  test.
- `tests/models/trendline_family/test_obsolete_cleanup.py`: integration
  ownership assertion.
(Command: required `rg` integration-import search.)

The direct optimization-ablation search found the expected dedicated test
import plus the migration test's historical identity string and the old
ablation implementation's returned identity string. These were classified as
test/identity or implementation text, not additional runtime consumers.
(Command: required direct compatibility-module `rg` search.)

The code graph's inbound trace for `run_regime_feature_ablation` returned no
callers before editing. Live text search and tests remained authoritative.
(Tool: CBM `trace_path`; commands: required consumer searches.)

## 5. Pre-deletion test baseline

- Combined compatibility/ownership collection: `20 tests collected`.
- Combined compatibility/ownership execution: `20 passed in 4.33s`.
- Full optimization collection: `30 tests collected`.
- Full optimization execution: `30 passed in 2.18s`.
- Canonical trendlines suite: `266 passed in 10.06s`.
(Commands: required C2-A3b1 pre-deletion baseline.)

## 6. Integration package deleted

Deleted complete directory:

```text
src/libs/integrations/trendline_regime_v2/
```

Deleted production files: `2`:

- `__init__.py`
- `ablation.py`

The path is absent, and no integration replacement or tombstone was added.
(Commands: `git rm -r`, deleted/live path checks.)

## 7. Canonical optimisation exports cleaned

Updated `src/libs/models/trendline/optimization/__init__.py`:

- Changed module description to `Offline-only Trendline optimisation APIs.`.
- Removed `import_module`.
- Removed `_DEPRECATED_ABLATION_EXPORTS`.
- Removed `__getattr__` lazy compatibility hook.
- Removed five retired ablation names from `__all__`.
- Preserved `FeatureGroup`, `CandidateGeometryEvaluator`,
  `InteractionEvaluator`, `TrackerEvaluator`, `ImmutableHistoricalFrame`,
  `ObjectiveSpec`, and ordinary optimization runners.
(File: `src/libs/models/trendline/optimization/__init__.py`; tests:
`test_ablation_removal.py` and optimization suite.)

## 8. Forwarding modules deleted

Deleted production forwarders:

- `src/libs/models/trendline/optimization/ablation.py`
- `src/libs/models/trendline_family/optimization/ablation.py`

Deleted production-file count: `4` including the two integration files.
`src/libs/models/trendline_family/optimization/__init__.py` was not modified;
its ordinary optimization forwarding remains verified by object-identity and
callability assertions. (Commands: `git diff --name-status`, export checks.)

## 9. Obsolete ablation tests retired

Deleted test files:

- `tests/models/trendline_family/test_ablation_compatibility.py`
- `tests/models/trendline_family/optimization/test_ablation.py`

Deleted test count: `2`. Their ablation-specific behavior was not migrated.
The remaining optimization suite collected `28` tests and passed all `28`.
(Commands: optimization collection/execution.)

## 10. Migration and ownership contracts updated

Updated `tests/models/trendline_family/test_phase_1b_migration.py`:

- Removed the ablation scorer import.
- Removed only the final `scorer_identity(WeightedFeatureScorer(...))`
  assertion.
- Preserved candidate-generation parity, evaluation-spec parity,
  configuration semantics, provider identity, and historical model/config
  assertions. (File and compatibility test result.)

Updated `tests/models/trendline_family/test_obsolete_cleanup.py`:

- Removed the ablation import and its single ablation owner-identity check.
- Preserved all canonical owner and removed-domain-scaffold checks. (File and
  compatibility test result.)

Updated `tests/models/trendline_family/test_import_boundaries.py`:

- Preserved `_FORBIDDEN_CANONICAL_UPSTREAM_PREFIXES`, including
  `libs.integrations.trendline_regime_v2`.
- Removed `_REGIME_COMPATIBILITY_FILES`.
- Replaced the deprecated-facade exemption test with
  `test_canonical_package_does_not_depend_on_regime_integrations`, checking all
  canonical files.
- Removed deleted integration `ablation.py` from direct-owner inventory.
- Renamed the direct-owner test to
  `test_api_and_config_loader_implementations_use_direct_owners`.
- Preserved AST ownership logic and canonical `api.py`/`config_loader.py`
  inventory. (File and `17 passed` compatibility result.)

## 11. Removal tests added

Added `tests/models/trendline_family/test_ablation_removal.py` with exactly two
tests:

- `test_removed_ablation_modules_are_absent`: verifies deleted source paths and
  absent module specs for integration and both optimization ablation modules.
- `test_optimization_exports_remain_core_only`: verifies five retired names are
  absent from canonical and family compatibility exports while
  `CandidateGeometryEvaluator`, `FeatureGroup`, and the candidate runner remain
  usable.
(File: `tests/models/trendline_family/test_ablation_removal.py`; result:
`2 passed`.)

## 12. Structural module-absence proof

Passed:

- Integration directory absent.
- Both singular ablation forwarders absent.
- Both obsolete ablation tests absent.
- `find_spec` reports all four removed modules absent; nested missing-parent
  cases are treated as absent by the focused removal test helper.
- No executable imports or dynamic imports reference the retired integration or
  optimization-ablation modules.
- `libs.integrations.trendline_configuration` remains present.
- `libs.models.trendline`, `libs.models.trendline_family`,
  `libs.models.trendline_v2`, and `libs.trendlines` remain present.
- Canonical and compatibility optimization export checks pass.
(Commands: structural path, `find_spec`, `rg`, export, and live-path checks.)

## 13. Post-change test results

- Removal/compatibility/ownership group: `19 passed in 3.38s`.
- Remaining optimization suite: `28 tests collected; 28 passed in 1.54s`.
- Configuration/MTF regression: `43 passed in 1.18s`.
- Canonical trendlines regression: `266 passed in 7.65s`.
- Compatibility regression: `17 passed in 3.35s`.
(Commands: required post-change validation.)

## 14. Static validation

- Compileall: passed for canonical optimization and all modified/added tests.
- Ruff: `All checks passed!` for canonical optimization and all modified/added
  tests.
- `git diff --check`: passed.
(Commands: required static validation.)

CBM source/tests re-index completed. The optional GitNexus substep of
`./mcp/scripts/mcp-index.sh` exited nonzero because `mcp-proxy` was not running;
it made no worktree changes. Live source searches and executable validation
remain authoritative for this phase. (Command: `./mcp/scripts/mcp-index.sh`.)

## 15. Files changed

Authorized tracked changes:

- Deleted 4 production files listed in sections 6 and 8.
- Deleted 2 ablation test files listed in section 9.
- Modified:
  - `src/libs/models/trendline/optimization/__init__.py`
  - `tests/models/trendline_family/test_phase_1b_migration.py`
  - `tests/models/trendline_family/test_import_boundaries.py`
  - `tests/models/trendline_family/test_obsolete_cleanup.py`
- Added `tests/models/trendline_family/test_ablation_removal.py`.
- Added this handoff.

No configuration, signal, V2, singular-model, or canonical plural-trendlines
path appears in `git diff HEAD --name-status`. (Command: final scope audit.)

## 16. Git diff summary

Before handoff creation, tracked diff against starting HEAD was:

```text
10 tracked files changed
4 insertions(+), 767 deletions(-)
```

The six staged deletions account for `715` deleted lines; four unstaged edits
account for `4 insertions(+), 52 deletions(-)`. The new removal test and this
handoff are untracked authorized additions and are not included by plain
`git diff HEAD --stat`. (Commands: `git diff --cached --stat`, `git diff --stat`,
`git diff HEAD --name-status`.)

## 17. Git status

No commit was created. Current status contains only authorized C2-A3b1 paths:

```text
D  src/libs/integrations/trendline_regime_v2/__init__.py
D  src/libs/integrations/trendline_regime_v2/ablation.py
 M src/libs/models/trendline/optimization/__init__.py
D  src/libs/models/trendline/optimization/ablation.py
D  src/libs/models/trendline_family/optimization/ablation.py
D  tests/models/trendline_family/optimization/test_ablation.py
D  tests/models/trendline_family/test_ablation_compatibility.py
 M tests/models/trendline_family/test_import_boundaries.py
 M tests/models/trendline_family/test_obsolete_cleanup.py
 M tests/models/trendline_family/test_phase_1b_migration.py
?? tests/models/trendline_family/test_ablation_removal.py
?? plans/coder-to-orchestrator-legacy-trendlines-c2a3b1-retire-ablation-integration-v1.md
```

(Command: `git status --short --untracked-files=all` after validation.)

## 18. Commands executed

- C2-A3b1 branch, HEAD, status, worktree, history, and deletion-state
  preflight.
- Required environment/version/import checks.
- CBM search/trace discovery and required `rg` consumer searches.
- Required pre-deletion collection and test baselines.
- Authorized `git rm` deletions and `apply_patch` edits.
- Removal, compatibility, optimization, configuration/MTF, and canonical
  trendlines test suites.
- Deleted-path, `find_spec`, no-reference, export, and live-path checks.
- Compileall, Ruff, `git diff --check`, status, and diff-scope checks.
- `./mcp/scripts/mcp-index.sh`; CBM portions indexed, GitNexus substep reported
  unavailable `mcp-proxy`.

## 19. Residual risks

- C2-A3b1 remains uncommitted pending independent review.
- `src/libs/integrations/trendline_configuration/` remains live for C2-A3b2.
- `libs.models.trendline` and `libs.models.trendline_family` remain scheduled
  for later phases.
- GitNexus index refresh did not complete because `mcp-proxy` was unavailable;
  this does not affect source, test, or scope validation.

## 20. Recommended next phase

`C2-A3b2 — Remove the trendline_configuration compatibility integration`

READY_FOR_C2A3B2_CONFIGURATION_INTEGRATION_REMOVAL
