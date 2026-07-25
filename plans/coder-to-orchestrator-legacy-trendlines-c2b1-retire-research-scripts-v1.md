# Legacy Trendlines Consolidation C2-B1
## Retire Legacy Trendline-Family Research Scripts and Dedicated Tests

## 1. Disposition

C2-B1 complete. Six obsolete singular-model research scripts and their six
dedicated test files were deleted. Historical artifact roots, model packages,
configuration, model tests, plans, and Trendline V2 paths remain present and
unchanged. (Commands: protected-scope, structural, regression, and final
scope checks.)

## 2. Starting branch and commit

- Branch: research/legacy-trendlines-quality-stability-v1.
- Worktree: /Users/aloobhujia/flipperAgent-wt-legacy-trendlines.
- Starting HEAD: c765f9ce0f5ab2f6f8f89e5d5525a8e3159435bb.
- Starting commit: refactor: remove trendline configuration integration.
- Starting status: clean.
- Recent history included C1 through C2-A3b2. (Commands: preflight branch,
  HEAD, worktree, status, and git log checks.)

## 3. Environment and worktree proof

- Python: /Users/aloobhujia/flipperAgent/.venv/bin/python, version 3.13.13.
- Ruff: /Users/aloobhujia/.local/bin/ruff, version 0.15.20.
- PYTHONPATH=$PWD/src:$PWD.
- All six retired script modules imported from this worktree before deletion.
  Their main functions were not executed. (Command: required module import
  verification.)
- Only root AGENTS.md applies; no nested AGENTS.md was found.
- No dependencies were installed or upgraded. No research script main function
  or network workflow was run. (Commands: environment and validation commands.)

## 4. Pre-deletion script consumer inventory

The repository-wide basename searches, excluding plans, artifacts, scripts,
dedicated script tests, and caches, returned zero matches for all six script
basenames. (Command: required six-name loop.)

The singular-model import search under scripts returned matches only in the six
authorized scripts:

- analyze_trendline_family_candidate_density.py
- analyze_trendline_family_candidate_quality_normalization.py
- build_trendline_family_candidate_evidence_report.py
- diagnose_trendline_family_candidate_rejection.py
- run_trendline_family_candidate_geometry_trial.py
- run_trendline_family_saturating_quality_fresh_window_trial.py

No other script consumer was found. (Command: required scripts import rg.)

CBM listed the six script modules with no inbound graph callers. Live text
search was authoritative for this deletion gate. (Tool: CBM search_graph;
commands: consumer searches.)

## 5. Protected evidence inventory

Pre-deletion protected-artifact status produced no output. All six protected
artifact roots existed. (Command: required protected status check and root
checks.)

Protected roots:

- artifacts/trendline_family_candidate_density_studies
- artifacts/trendline_family_candidate_diagnostics
- artifacts/trendline_family_candidate_quality_normalization_studies
- artifacts/trendline_family_candidate_reports
- artifacts/trendline_family_candidate_trials
- artifacts/trendline_family_saturating_quality_trials

No plan or evidence file was modified, deleted, regenerated, or executed
against. (Commands: scope and protected-artifact checks.)

## 6. Pre-deletion test baseline

- Dedicated script tests: 157 tests collected and 157 passed in 70.96s.
- Complete tests/scripts collection: 459 tests collected.
- Complete tests/scripts execution: 438 passed, 21 skipped in 148.06s.
- Singular model collection: 398 tests collected.
- Singular model execution: 398 passed in 24.68s.
- Canonical plural trendlines execution: 266 passed in 7.95s.
(Commands: required C2-B1 pre-deletion baseline.)

The 21 complete-scripts skips were pre-existing suite skips; no test was
skipped or altered by this phase. (Command: complete tests/scripts result.)

## 7. Research scripts deleted

Deleted six scripts:

- scripts/analyze_trendline_family_candidate_density.py
- scripts/analyze_trendline_family_candidate_quality_normalization.py
- scripts/build_trendline_family_candidate_evidence_report.py
- scripts/diagnose_trendline_family_candidate_rejection.py
- scripts/run_trendline_family_candidate_geometry_trial.py
- scripts/run_trendline_family_saturating_quality_fresh_window_trial.py

The scripts imported singular model APIs and performed offline evidence
validation/study orchestration through main entrypoints. They were not migrated
to Trendline V2. (Files read before deletion; command: git rm.)

Deleted script count: 6.

## 8. Dedicated tests deleted

Deleted six dedicated test files:

- tests/scripts/test_trendline_family_candidate_density.py
- tests/scripts/test_trendline_family_candidate_quality_normalization.py
- tests/scripts/test_trendline_family_candidate_evidence_report.py
- tests/scripts/test_trendline_family_candidate_rejection.py
- tests/scripts/test_trendline_family_candidate_geometry_trial.py
- tests/scripts/test_trendline_family_saturating_quality_fresh_window_trial.py

Deleted dedicated-test count: 6. Their 157 collected tests were retired with
the scripts. Remaining scripts tests retain existing Trendline V2 and other
script coverage. (Commands: git rm and post-collection result.)

## 9. Removal tests added

Added tests/scripts/test_legacy_trendline_research_scripts_removed.py with
exactly two tests:

- test_retired_research_script_and_test_paths_are_absent verifies all twelve
  deleted paths.
- test_remaining_scripts_do_not_import_singular_models AST-parses all remaining
  scripts, checks exact singular prefixes without matching trendline_v2, and
  checks literal import_module and __import__ calls.

The new removal test passed 2/2. (Command: focused removal-test execution.)

## 10. Structural absence proof

Passed:

- All six script paths absent.
- All six dedicated test paths absent.
- No singular-model imports remain under scripts.
- The new AST removal contract also reports no remaining singular imports.
- Model packages and configuration paths remain:
  src/libs/models/trendline
  src/libs/models/trendline_family
  configs/trendline_family.yaml
  configs/trendline
  tests/models/trendline_family
- Trendline V2 paths were not changed.
(Commands: path, rg, AST, and live-path checks.)

## 11. Historical evidence preservation

Post-deletion protected-artifact status again produced no output, and all six
protected roots remained present. No artifact path appears in final diff or
status. (Command: final protected-artifact check.)

## 12. Post-change test results

- New removal tests: 2 passed in 0.23s.
- Complete tests/scripts collection: 304 tests collected.
- Complete tests/scripts execution: 283 passed, 21 skipped in 79.10s.
- Singular model collection: 398 tests collected.
- Singular model execution: 398 passed in 21.75s.
- Canonical plural trendlines: 266 passed in 7.88s.
- Trendline V2 boundary group: 65 passed in 3.77s.
(Commands: required post-deletion validation.)

The post-change scripts count equals 459 - 157 + 2 = 304. No deleted
dedicated test was collected. (Commands: pre/post collection results.)

## 13. Static validation

- Compileall: passed for the new removal test.
- Ruff: All checks passed! for the new removal test.
- git diff --check: passed.
(Command: required static validation.)

CBM index refresh completed for indexed repository slices. GitNexus indexing
remained unavailable because mcp-proxy was not running; no dependency was
installed and no worktree file changed. Live source searches and executable
tests remain authoritative. (Command: mcp/scripts/mcp-index.sh.)

## 14. Files changed

Authorized changes:

- Deleted 6 scripts.
- Deleted 6 dedicated script-test files.
- Added tests/scripts/test_legacy_trendline_research_scripts_removed.py.
- Added this handoff.

No model, configuration, artifact, historical-plan, fixture, or V2 path
changed. (Commands: final git status, diff names, and protected-scope checks.)

## 15. Git diff summary

Tracked staged deletion diff:

12 files changed
8,631 deletions

The new removal test and this handoff are authorized untracked additions and
are not included in staged-only deletion statistics. (Commands: git diff
--cached --stat and numstat.)

## 16. Git status

No C2-B1 commit was created. Current status contains only authorized paths:

D  six scripts under scripts/
D  six dedicated tests under tests/scripts/
?? tests/scripts/test_legacy_trendline_research_scripts_removed.py
?? plans/coder-to-orchestrator-legacy-trendlines-c2b1-retire-research-scripts-v1.md

(Command: final git status --short --untracked-files=all.)

## 17. Commands executed

- C2-A3b2 approved-unit commit and clean-status verification.
- C2-B1 branch, HEAD, worktree, history, deletion-state, and instruction
  preflight.
- CBM discovery, script import/path verification, consumer searches, and
  protected-artifact checks.
- Dedicated 157-test baseline.
- Complete scripts baseline: 459 collected, 438 passed, 21 skipped.
- Singular model baseline: 398 collected and passed.
- Canonical trendlines baseline: 266 passed.
- Authorized git rm deletion.
- New removal tests, post scripts suite, singular model suite, canonical suite,
  and Trendline V2 boundary suite.
- Structural path/import checks, protected-artifact recheck, compileall, Ruff,
  git diff --check, status, and scope checks.
- CBM index refresh.

## 18. Residual risks

- C2-B1 remains uncommitted pending independent review.
- Singular model packages, model tests, configuration, and fixtures remain for
  C2-B2 preparation.
- Existing 21 skips in tests/scripts remain unchanged.
- GitNexus refresh remains unavailable due local mcp-proxy dependency state;
  live source/test validation passed.

## 19. Recommended next phase

C2-B2 — Retire the remaining singular-model test/config/fixture contract in
preparation for package deletion

READY_FOR_C2B2_MODEL_CONTRACT_RETIREMENT
