# Legacy Trendlines Consolidation C1-R1
## Retire the Obsolete trendlines_old Presence Test Contract

## 1. Disposition

C1-R1 completed. Removed only obsolete archive-presence import and identity
assertion from the migration test. Renamed test to match remaining contract.
Preserved forbidden archive-import rule and all compatibility/parity assertions.

src/libs/models/trendlines_old/ still exists and was not modified. No package
deletion, package move, C2 work, or L0-B work performed.

## 2. Starting branch and commit

| Field | Result |
|---|---|
| Branch | research/legacy-trendlines-quality-stability-v1 |
| Starting commit | 2a2b324cae4fc20e325a89ed376cf1806f395a70 |
| Worktree | /Users/aloobhujia/flipperAgent-wt-legacy-trendlines |
| Starting status | clean |
| Nested AGENTS.md | none; root AGENTS.md applies |

Preflight commands: git branch --show-current, git rev-parse HEAD,
git status --short --untracked-files=all, git worktree list --porcelain.

## 3. Environment proof

Used:

~~~
PY=/Users/aloobhujia/flipperAgent/.venv/bin/python
PYTHONPATH=$PWD/src:$PWD
~~~

Results:

| Check | Result |
|---|---|
| Python | 3.13.13 |
| Executable | /Users/aloobhujia/flipperAgent/.venv/bin/python |
| numpy | 2.4.6 |
| pandas | 3.0.3 |
| yaml | 6.0.3 |
| pytest | 8.4.2 |
| optuna | 4.8.0 |

Import smoke resolved all modules inside current isolated worktree:

~~~
libs.models.trendline -> /Users/aloobhujia/flipperAgent-wt-legacy-trendlines/src/libs/models/trendline/__init__.py
libs.models.trendline_family -> /Users/aloobhujia/flipperAgent-wt-legacy-trendlines/src/libs/models/trendline_family/__init__.py
libs.models.trendlines_old -> /Users/aloobhujia/flipperAgent-wt-legacy-trendlines/src/libs/models/trendlines_old/__init__.py
libs.trendlines -> /Users/aloobhujia/flipperAgent-wt-legacy-trendlines/src/libs/trendlines/__init__.py
~~~

No dependencies installed or upgraded.

## 4. Pre-change archive consumer search

Codebase-memory graph search located the existing test function. Trace showed no
upstream callers and only local _imports_under downstream use. Required
repository search before edit returned exactly one executable import:

~~~
tests/models/trendline_family/test_phase_1b_migration.py:36:
from libs.models.trendlines_old import __name__ as legacy_copy_name
~~~

No executable consumer under src/ was found. No other active import consumer
was found under tests, scripts, or conductor.

Other trendlines_old strings remain only as negative architecture assertions,
including:

~~~
tests/models/trendline_family/test_phase_1b_migration.py:47:
    "libs.models.trendlines_old",
~~~

That string is preserved intentionally.

## 5. Obsolete contract removed

Modified tests/models/trendline_family/test_phase_1b_migration.py only:

1. Removed import:
   from libs.models.trendlines_old import __name__ as legacy_copy_name
2. Removed assertion:
   assert legacy_copy_name == "libs.models.trendlines_old"
3. Renamed:
   test_legacy_trendline_packages_remain_distinct_from_canonical_family_model
   to:
   test_legacy_trendlines_package_remains_distinct_from_canonical_family_model

Remaining test contract:

~~~
assert legacy_name == "libs.trendlines"
assert not {
    value
    for value in _imports_under(_LEGACY_ROOT)
    if value.startswith("libs.models.trendline")
}
~~~

## 6. Contracts explicitly preserved

Preserved unchanged:

- _FORBIDDEN_CANONICAL_IMPORTS entry "libs.models.trendlines_old".
- Canonical import-direction and runtime/research ownership assertions.
- trendline_family compatibility object-identity assertions.
- Serialization parity assertions.
- Provider identity assertions.
- Candidate-generation parity assertions.
- Candidate config and optimization semantics assertions.
- All source packages, including src/libs/models/trendlines_old/.
- Historical plans and documentation.

No archive-absence assertion was added.

## 7. Pre-change test result

Command:

~~~
/Users/aloobhujia/flipperAgent/.venv/bin/python -m pytest -q \
  tests/models/trendline_family/test_phase_1b_migration.py
~~~

Result:

~~~
5 passed in 0.59s
~~~

Collected: 5. Passed: 5. Failed: 0. Skipped: 0. Duration: 0.59s.

## 8. Post-change validation

| Validation | Result |
|---|---|
| Executable archive-import search | Zero matches; rg exit 1 expected for no matches |
| Focused migration test | 5 passed in 0.39s |
| Focused compatibility group | 17 passed in 3.49s |
| Canonical ownership test | Expected 1 failed in 1.56s |
| Ruff via project venv | Unavailable: No module named ruff |
| Ruff via existing system binary | ruff 0.15.20; all checks passed |
| compileall target test | Passed, exit 0 |
| git diff --check | Passed, exit 0 |
| Archive path | Present; no modification |

Focused compatibility command:

~~~
/Users/aloobhujia/flipperAgent/.venv/bin/python -m pytest -q \
  tests/models/trendline_family/test_phase_1b_migration.py \
  tests/models/trendline_family/test_import_boundaries.py \
  tests/models/trendline_family/test_obsolete_cleanup.py
~~~

No tests were deleted, skipped, or altered beyond authorized contract edits.

## 9. Expected remaining ownership failure

Command:

~~~
/Users/aloobhujia/flipperAgent/.venv/bin/python -m pytest -q --tb=short \
  src/libs/trendlines/tests/test_import_boundaries.py::test_shared_boundary_symbols_have_single_canonical_definition
~~~

Result: 1 failed in 1.56s. Failure remains exclusively caused by duplicate
top-level symbols under src/libs/models/trendlines_old/. Static reproduction of
the test reported 14 violations:

~~~
models/trendlines_old/boundary/__init__.py -> INTERACTION_DIRECTION should live in trendlines/boundary/__init__.py
models/trendlines_old/boundary/__init__.py -> interaction_direction should live in trendlines/boundary/__init__.py
models/trendlines_old/boundary/adapters.py -> build_boundary_result_from_trendline_result should live in trendlines/boundary/adapters.py
models/trendlines_old/boundary/adapters.py -> trendline_to_boundary_ray should live in trendlines/boundary/adapters.py
models/trendlines_old/boundary/contracts.py -> Ray should live in trendlines/boundary/contracts.py
models/trendlines_old/boundary/contracts.py -> QualityMetrics should live in trendlines/boundary/contracts.py
models/trendlines_old/boundary/contracts.py -> BoundaryResult should live in trendlines/boundary/contracts.py
models/trendlines_old/boundary/policy.py -> TouchDeclusterConfig should live in trendlines/boundary/policy.py
models/trendlines_old/boundary/policy.py -> TouchDiagnostics should live in trendlines/boundary/policy.py
models/trendlines_old/boundary/policy.py -> ConfluenceGateConfig should live in trendlines/boundary/policy.py
models/trendlines_old/boundary/policy.py -> ConfluenceQualitySnapshot should live in trendlines/boundary/policy.py
models/trendlines_old/boundary/policy.py -> RayTrackerConfig should live in trendlines/boundary/policy.py
models/trendlines_old/boundary/policy.py -> TrackedRayState should live in trendlines/boundary/policy.py
models/trendlines_old/boundary/touches.py -> decluster_touch_indices should live in trendlines/boundary/touches.py
~~~

Ownership test was not modified.

## 10. Files changed

Modified:

~~~
tests/models/trendline_family/test_phase_1b_migration.py
~~~

Added:

~~~
plans/coder-to-orchestrator-legacy-trendlines-c1r1-retire-archive-presence-contract-v1.md
~~~

Unchanged and still present:

~~~
src/libs/models/trendlines_old/
~~~

## 11. Git diff summary

Tracked diff:

~~~
tests/models/trendline_family/test_phase_1b_migration.py | 4 +---
1 file changed, 1 insertion(+), 3 deletions(-)
~~~

The new handoff is untracked and therefore absent from git diff --stat and
git diff --name-status until committed or staged. No archive deletion appears
in diff.

## 12. Git status

Expected final status:

~~~
 M tests/models/trendline_family/test_phase_1b_migration.py
?? plans/coder-to-orchestrator-legacy-trendlines-c1r1-retire-archive-presence-contract-v1.md
~~~

No production package, unrelated test, script, configuration, artifact, or
existing plan changed. No commit, merge, rebase, or cherry-pick performed.

## 13. Commands executed

Preflight and instruction review:

~~~
git branch --show-current
git rev-parse HEAD
git status --short --untracked-files=all
git worktree list --porcelain
cat AGENTS.md
cat plans/coder-to-orchestrator-legacy-trendlines-l0a-baseline-audit-v1.md
cat tests/models/trendline_family/test_phase_1b_migration.py
rg --files -g AGENTS.md
~~~

Environment:

~~~
/Users/aloobhujia/flipperAgent/.venv/bin/python --version
/Users/aloobhujia/flipperAgent/.venv/bin/python <dependency/import smoke>
~~~

Code intelligence and dependency proof:

~~~
./mcp/scripts/mcp-status.sh
codebase-memory search_graph
codebase-memory trace_path
codebase-memory get_code_snippet
codebase-memory search_code
rg -n --glob '*.py' <archive import and dynamic import patterns> src tests scripts conductor
~~~

Baseline, edit, and validation:

~~~
/Users/aloobhujia/flipperAgent/.venv/bin/python -m pytest -q tests/models/trendline_family/test_phase_1b_migration.py
apply_patch tests/models/trendline_family/test_phase_1b_migration.py
rg -n --glob '*.py' <archive import and dynamic import patterns> src tests scripts conductor
/Users/aloobhujia/flipperAgent/.venv/bin/python -m pytest -q tests/models/trendline_family/test_phase_1b_migration.py
/Users/aloobhujia/flipperAgent/.venv/bin/python -m pytest -q --tb=short <canonical ownership test>
/Users/aloobhujia/.local/bin/ruff check tests/models/trendline_family/test_phase_1b_migration.py
/Users/aloobhujia/flipperAgent/.venv/bin/python -m compileall -q tests/models/trendline_family/test_phase_1b_migration.py
git diff --check
git status --short
git diff --stat
git diff --name-status
git diff -- tests/models/trendline_family/test_phase_1b_migration.py
~~~

## 14. Residual risks

- Archive remains importable and continues to duplicate canonical boundary
  symbols. C1 deletion remains required.
- Project venv lacks Ruff module; system Ruff fallback passed. Dependency state
  was not changed.
- Full canonical suite was not run in C1-R1; C1-R1 scope used focused tests and
  expected ownership failure only.
- The preserved negative import rule still references the archive string by
  design. It will remain valid after C1 deletion.
- No archive-absence assertion was added before archive deletion.

## 15. Recommended next phase

C1 — Remove the trendlines_old archive package

src/libs/models/trendlines_old/ remains present and unmodified pending separate
review and deletion authorization.

READY_TO_RETRY_C1_ARCHIVE_REMOVAL
