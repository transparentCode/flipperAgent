# C4-B-R3a Shadow Removal Contract Handoff

## 1. Disposition

R3a complete. Missing-parent-safe shadow removal contract restored. No
production module, parent compatibility package, SR code/evidence, alert code,
E2E code, configuration, or package ownership was changed.

Final disposition: `READY_FOR_C4BR3B_SR_EVIDENCE_DEBT_CLASSIFICATION`

## 2. Starting branch and commit

Branch: `research/legacy-trendlines-quality-stability-v1`

HEAD: `41fea18b1d6b6069500b2e21748a4202c7189527`

## 3. Expected dirty-worktree proof

Initial paths matched R3a scope:

```text
M  tests/models/test_legacy_trendline_retirement.py
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-final-ownership-regression-v1.md
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r1-known-alert-debt-v1.md
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r2-infrastructure-debt-closeout-v1.md
```

Prior C4-B handoffs remained unchanged. No commit was created.

## 4. Original failure reproduction

The focused removal test failed because subprocess `find_spec` raised:

```text
ModuleNotFoundError: No module named 'libs.integrations.trendline_regime_v2'
```

The exception came from checking:

```text
libs.integrations.trendline_regime_v2.shadow
```

after its parent package had been physically deleted.

## 5. Root cause

`importlib.util.find_spec()` returns `None` for an absent leaf module only when
its parent package can be resolved. With the deleted integration package,
missing-parent resolution raises `ModuleNotFoundError`. The test lacked the
missing-parent handling already used by the durable retirement boundary.

## 6. Missing-parent-safe remediation

Added subprocess-local helper:

```python
def module_is_absent(module_name):
    try:
        return importlib.util.find_spec(module_name) is None
    except ModuleNotFoundError:
        return True
```

Only the two existing removed module names remain checked. Active adapter
construction, `sys.modules` absence, subprocess isolation, and signal-pipeline
shadow API checks remain unchanged. No parent package was recreated.

## 7. Focused test results

```text
Previously failing test: 1 passed
Removal file:            2 passed
```

## 8. Non-SR model collection and execution

```text
474 tests collected
474 passed
3 pre-existing dependency warnings
```

The non-SR model matrix is fully green. No skip, failure, or error occurred.

## 9. Ownership regression

```text
9 passed
```

Canonical package counts remain 147 tracked files for `trendlines` and 33 for
`trendline_v2`; retired namespaces remain absent.

## 10. Canonical and adapter regressions

```text
Canonical trendlines: 266 passed
RegimeV2 adapter:       6 passed
```

No model behavior changed.

## 11. Static validation

```text
compileall: passed
Ruff:       passed
git diff --check: passed
```

Generated repository-local `__pycache__` directories were removed.

## 12. Files changed

Authorised R3a changes:

```text
M  tests/models/regime_v2/adapters/test_trendline_family_shadow_removal.py
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r3a-shadow-removal-contract-v1.md
```

The existing C4-B exact-layout test and three prior handoffs remain unchanged.

## 13. Git status

Expected final paths:

```text
M  tests/models/test_legacy_trendline_retirement.py
M  tests/models/regime_v2/adapters/test_trendline_family_shadow_removal.py
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-final-ownership-regression-v1.md
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r1-known-alert-debt-v1.md
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r2-infrastructure-debt-closeout-v1.md
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r3a-shadow-removal-contract-v1.md
```

No commit, merge, rebase, or cherry-pick was performed.

## 14. Commands executed

Executed R3a preflight, focused defect reproduction, focused remediation test,
complete removal test, non-SR model collection/execution, ownership regression,
canonical regression, RegimeV2 adapter regression, compileall, Ruff, diff
check, and cache cleanup.

## 15. Residual risks

SR remains isolated from this remediation at:

```text
900 passed
35 failed
119 errors
```

Its missing frozen-evidence families require separate R3b classification. No
SR files or evidence were modified.

## 16. Recommended next phase

```text
C4-B-R3b — Classify and freeze the pre-existing SR evidence-debt ledger
```

Do not begin R3b work from this handoff without a new bounded scope.

Final disposition:

```text
READY_FOR_C4BR3B_SR_EVIDENCE_DEBT_CLASSIFICATION
```
