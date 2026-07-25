# Coder-to-Orchestrator Handoff: C4-B-R4 Final Regression and Closeout

## 1. Disposition

R4 completed against the fixed 184-node unrelated-exception ledger.

The final repository contains only these trendline model packages:

```text
src/libs/models/trendlines/
src/libs/models/trendline_v2/
```

4,000 tests were collected and accounted for. 3,816 runnable tests completed
without unexpected failures or errors: 3,794 passed and 22 skipped normally.
The 184 fixed exceptions reproduced their exact ledgers. Zero trendline-related
failures occurred.

Final disposition:

```text
READY_FOR_L0B_CAUSALITY_AUDIT
```

## 2. Starting branch and commit

```text
branch: research/legacy-trendlines-quality-stability-v1
HEAD:   e8869b68193ade4e5617b18b7838dd4b648eff90
subject: docs: freeze SR evidence debt ledger
```

R4 made no commit. The R3b evidence-ledger checkpoint was committed before
validation.

## 3. Expected dirty-worktree proof

Pre-R4 dirty paths were exactly:

```text
M  tests/models/test_legacy_trendline_retirement.py
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-final-ownership-regression-v1.md
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r1-known-alert-debt-v1.md
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r2-infrastructure-debt-closeout-v1.md
```

Only this R4 handoff was added. No source, test, configuration, Docker, model,
package, alert, E2E, SR, benchmark, research, script, or historical plan was
modified.

## 4. Final exact package layout

```text
src/libs/models/trendlines/     147 tracked files
src/libs/models/trendline_v2/    33 tracked files
configs/trendline_v2.yaml         1 tracked file
```

Retired physical paths remain absent:

```text
src/app/trendlines/
src/libs/trendlines/
src/libs/models/trendline/
src/libs/models/trendline_family/
src/libs/models/trendlines_old/
tests/models/trendline_family/
configs/trendline_family.yaml
configs/trendline/
benchmarks/trendline_numba_atr.py
research/trendline_family_research_lab.ipynb
```

## 5. Namespace/module-spec audit

Removed module specs remain absent:

```text
app.trendlines
libs.trendlines
libs.models.trendline
libs.models.trendline_family
libs.models.trendlines_old
```

Canonical specs resolve inside this worktree:

```text
libs.models.trendlines
libs.models.trendline_v2
```

Executable retired-namespace import search returned zero matches. Whole active
tree text search found only negative boundary assertions in V2 and retirement
tests. No source, documentation, configuration, CLI, logger, metadata, or
runtime consumer retained a retired namespace.

## 6. Fixed 184-exception ledger

```text
Alert routing contract debt:             1
Alert Docker/API environment debt:       5
Full-stack E2E environment debt:        19
SR frozen-evidence debt:                154
Scraper contract debt:                    5
------------------------------------------
Total fixed exceptions:                 184
```

Alert routing reproduced:

```text
tests/alerts/test_routing.py::test_resolve_routes_for_execution_event
expected: system_alerts
actual:   []
cause:    configs/alerts.yaml system_alerts.enabled = false
```

Alert Docker reproduced five setup errors, each timing out at:

```text
http://127.0.0.1:8096/alerts/health
```

E2E reproduced 19 setup errors through
`tests/e2e/conftest.py::docker_services_ready`, before test bodies ran, with
PostgreSQL connection refusal at `localhost:5432`.

The SR evidence node-set hash matched:

```text
bb2c285245847bd466797ddce9221c2d0ce966e1fe1763f8a70f2bbf0a8d2eb3
```

SR family counts:

```text
MISSING_APPROVED_V1_5_SOURCE_BUNDLE           36
MISSING_APPROVED_TAOUSDT_DEVELOPMENT_CAPSULE  23
FROZEN_ARTIFACT_MEMBER_SET_MISMATCH           73
V1_9_ARTIFACT_MEMBER_SET_MISMATCH             20
MISSING_V2_3_HISTORY_BUNDLE                    2
                                               ---
                                               154
```

The five root scraper failures matched:

```text
STALE_SCRAPER_CLI_MONKEYPATCH_CONTRACT        3
CONFIG_MANAGER_SINGLETON_TEST_CONTAMINATION   2
```

Normalized node-set hash:

```text
1b466db0239b747a3273a460dbfb508e1646297981c3d6b15c0061088ffe3531
```

## 7. Collection matrix

Independent top-level collection:

```text
tests/alerts             44
tests/apps               23
tests/commons            55
tests/conductor          17
tests/conductor_tests    38
tests/e2e                19
tests/execution          60
tests/ingestion          94
tests/integration        22
tests/models           1528
tests/portfolio         135
tests/risk              156
tests/risk_v2             7
tests/scripts           304
tests/signals            68
                       ----
                       2570
```

Additional independent collections:

```text
root-level matrix excluding tests/test_tv_browser_backfill.py  1049
canonical trendlines                                             266
regime                                                            115
---------------------------------------------------------------------
total                                                            4000
```

## 8. Hermetic top-level results

```text
tests/alerts passing subset  38 passed
tests/apps                   23 passed
tests/commons                55 passed
tests/conductor              17 passed
tests/conductor_tests        38 passed
tests/execution              60 passed
tests/ingestion              93 passed, 1 skipped
tests/integration            22 passed
tests/portfolio             135 passed
tests/risk                  156 passed
tests/risk_v2                 7 passed
tests/scripts               283 passed, 21 skipped
tests/signals                68 passed
```

E2E was intentionally executed as a fixed environment-debt probe and produced
19 setup errors. Alert routing and alert Docker tests were separately reproduced
as the fixed six alert exceptions.

## 9. Model partition results

```text
non-SR models                    474 passed
ordinary SR models               440 passed
SR research/scripts              460 passed, 35 failed, 119 errors
fixed SR exception nodes         154
```

The SR exception set is limited to research/scripts evidence contracts. No
ordinary SR model test failed.

## 10. Root-level matrix result

```text
1044 passed
5 fixed failures
0 errors
0 skips
```

Fixed nodes:

```text
tests/test_scraper_cli.py::test_coinglass_cli_writes_json
tests/test_scraper_cli.py::test_tradingview_cli_writes_csv
tests/test_scraper_cli.py::test_tradingview_cli_passes_limit
tests/test_tv_scraper.py::TestInterceptorHelpers::test_history_expansion_steps_scale_with_target_rows
tests/test_tv_scraper.py::TestInterceptorPatchrightSession::test_limit_expands_history_via_chart_drag
```

The first three fail because tests monkeypatch removed CLI-level interceptor
attributes. The last two reproduce ConfigManager singleton contamination after
the scoring-model runtime-spec test.

## 11. Canonical and regime results

```text
canonical trendlines  266 passed
regime source suite   115 passed
```

Canonical package CLI passed:

```text
python -m libs.models.trendlines.cli --help
```

## 12. Complete 4,000-test accounting

```text
3,794 passed
   22 normally skipped
  184 fixed unrelated exceptions
---------------------------
4,000 collected/accounted
```

The 22 normal skips are one ingestion skip and 21 scripts skips. No trendline
test was skipped to obtain a passing result.

## 13. Known external collection debt

Independent diagnostics remained unchanged:

```text
tests/test_tv_browser_backfill.py          1 collection error, missing apps.tv_scraper
src/libs/regression/tests                  8 collection errors, missing app.regression
src/libs/regression/optimization/tests    4 collection errors, missing app.regression
src/libs/sr/tests                          17 collection errors, missing app.sr
```

No diagnostic referenced a trendline namespace.

## 14. JavaScript viewer results

```text
Trendline V2 viewer  13 passed
SR zone viewer       28 passed
```

Lockfile hashes before and after npm validation remained unchanged:

```text
src/apps/trendline_v2_viewer/web/package-lock.json
bea18c4ae00e784f5ae65efbe011b27aa3121269cbd3874e757b882468c5758d

src/libs/models/sr/tools/zone_viewer/package-lock.json
bf6e7d6be665f3b81cea9ec491911370711a143fdba71b9fc07498e7ab7345ca
```

Generated `node_modules/` and `dist/` directories were removed from the
worktree after validation.

## 15. Canonical runtime smoke

Passed:

```text
libs.models.trendlines
libs.models.trendline_v2
```

Representative canonical objects all have module identities equal to or below
`libs.models.trendlines`:

```text
PivotSet
Trendline
TrendlineFitResult
run_trendline_pipeline
AlphaSignal
```

## 16. Static validation

```text
compileall: passed
Ruff targeted retirement test: passed
git diff --check: passed
```

Compileall emitted `Can't list 'benchmarks'` because C4-A intentionally removed
the final benchmark file and left no directory; command exit status remained
zero. Repository-local Python caches were removed from active roots.

## 17. Files changed

R4 added only:

```text
plans/coder-to-orchestrator-legacy-trendlines-c4b-r4-final-closeout-v1.md
```

Pre-existing uncommitted scope remains:

```text
M  tests/models/test_legacy_trendline_retirement.py
```

The exact-layout test and earlier C4-B handoffs were not modified.

## 18. Git status

Expected final status:

```text
 M tests/models/test_legacy_trendline_retirement.py
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-final-ownership-regression-v1.md
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r1-known-alert-debt-v1.md
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r2-infrastructure-debt-closeout-v1.md
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r4-final-closeout-v1.md
```

No generated JavaScript or Python cache paths remain.

## 19. Commands executed

```text
R4 preflight, package layout, module-spec and retirement-boundary checks
15 independent top-level pytest collections
root-level pytest collection excluding tests/test_tv_browser_backfill.py
canonical and regime pytest collections
alert passing subset
alert routing debt probe
alert Docker debt probe
E2E PostgreSQL readiness probe
remaining top-level pytest suites
non-SR model partition
ordinary SR model partition
SR research/scripts ledger reproduction and hash
root-level matrix and five-node hash verification
canonical trendlines suite
regime suite
known external collection-debt diagnostics
npm ci and npm test for both viewers
canonical CLI and module-identity smoke
compileall
targeted Ruff
git diff --check
active-tree namespace audit
protected provenance/hash checks
generated-cache cleanup
```

## 20. Residual risks

Alert, E2E, SR evidence, scraper-contract, and known collection debts remain
outside trendline scope and were not repaired. SR fail-closed provenance
contracts remain active; missing evidence was not regenerated. Broad Ruff debt
outside the targeted retirement test remains outside this closure.

## 21. Consolidation closeout

No compatibility namespace or retired model was restored. Canonical ownership is
single-package and exact. All consolidation-specific suites and all runnable
non-exception tests passed without trendline regressions.

## 22. Recommended next phase

```text
L0-B — Causality and repaint-risk audit of libs.models.trendlines
```
