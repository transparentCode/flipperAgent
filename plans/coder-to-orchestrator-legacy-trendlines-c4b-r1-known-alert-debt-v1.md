# C4-B-R1 Known Alert Debt Handoff

## 1. Disposition

C4-B-R1 is blocked by an additional pre-existing E2E environment failure outside
the six approved alert exceptions. No source, alert, Docker, model, or test
implementation was changed. The alert debt was reproduced exactly; full
regression and JavaScript validation were not reached.

Final disposition: `BLOCKED_C4BR1_PYTHON_REGRESSION`

## 2. Starting branch and commit

Branch: `research/legacy-trendlines-quality-stability-v1`

Starting HEAD: `41fea18b1d6b6069500b2e21748a4202c7189527`

Starting commit subject: `refactor: retire residual legacy trendline surfaces`

## 3. Expected dirty-worktree proof

Initial dirty paths matched the prescribed C4-B worktree:

```text
M  tests/models/test_legacy_trendline_retirement.py
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-final-ownership-regression-v1.md
```

The existing C4-B handoff was not modified. Its pre-remediation SHA-256 was
`2621365c8f837b21748e746fcdf306627c7c147bd69bde20f06bcf7bbfb8f82e`.

## 4. Final package-layout proof

Present:

```text
src/libs/models/trendlines/       147 tracked files
src/libs/models/trendline_v2/      33 tracked files
```

Absent physical paths:

```text
src/app/trendlines
src/libs/trendlines
src/libs/models/trendline
src/libs/models/trendline_family
src/libs/models/trendlines_old
tests/models/trendline_family
configs/trendline_family.yaml
configs/trendline
benchmarks/trendline_numba_atr.py
research/trendline_family_research_lab.ipynb
```

## 5. Namespace and module-spec audit

Retirement boundary: `9 collected, 9 passed`.

Removed module specs were absent for:

```text
app.trendlines
libs.trendlines
libs.models.trendline
libs.models.trendline_family
libs.models.trendlines_old
```

Canonical specs remained present for:

```text
libs.models.trendlines
libs.models.trendline_v2
```

## 6. Exact-layout contract result

The exact-layout test passed within the 9-test retirement boundary. It confirms
only `trendlines` and `trendline_v2` exist under `src/libs/models/` with names
starting with `trendline`.

## 7. Alert starting-commit hash proof

C4-B changed no alert code, tests, or configuration. `git diff 41fea18` was
empty for `tests/alerts`, `src/apps/alert_app`, and `configs/alerts.yaml`.

Starting-commit and working-tree blobs matched:

```text
tests/alerts/test_routing.py
609d3bb9734b9ae7b59d2f69a11158d4ec663377

configs/alerts.yaml
1aa46dd1187edd88c76fc21f41c421e24105f53e

src/apps/alert_app/rules/routing.py
24ddb66c17924e236822c092aa675dff33d2cb18
```

## 8. Routing-contract debt reproduction

`tests/alerts/test_routing.py::test_resolve_routes_for_execution_event` failed
with exactly one failure:

```text
expected: "system_alerts"
actual:   routes == []
```

`configs/alerts.yaml` has `system_alerts.enabled: false`. Current routing code
skips disabled routes. Classification:

```text
PRE_EXISTING_ALERT_ROUTING_CONTRACT_DEBT
```

## 9. Docker-environment debt reproduction

`tests/alerts/test_docker_alerts.py` produced exactly 5 setup errors. Every
error was:

```text
Timed out waiting for alert API health
```

The fixture probes:

```text
http://127.0.0.1:8096/alerts/health
```

Classification:

```text
PRE_EXISTING_ALERT_DOCKER_ENVIRONMENT_DEBT
```

No alert Docker service was started or modified.

## 10. Passing alert subset

The alert suite excluding the two diagnosed files passed:

```text
38 passed
```

Alert accounting is therefore:

```text
44 collected
38 passed
1 pre-existing routing-contract failure
5 pre-existing Docker-environment errors
```

## 11. Remaining top-level Python results

Completed before blocker:

```text
tests/apps             23 passed
tests/commons          55 passed
tests/conductor        17 passed
tests/conductor_tests  38 passed
```

`tests/e2e` then produced 19 setup errors. PostgreSQL was unavailable at
`localhost:5432`, yielding `PostgreSQL did not become ready for E2E tests`.
Repository Docker services were not running; only unrelated MCP/mem0
containers were present. Per C4-B-R1 policy, remaining Python and JS gates were
not run after this unexpected non-alert regression blocker.

## 12. Root-level matrix result

Not run after the `tests/e2e` blocker. The required `1,049`-test root matrix
therefore remains unverified in this remediation.

## 13. Canonical and regime results

Not rerun after the `tests/e2e` blocker. Previously approved consolidation
results remain historical evidence, but are not claimed as C4-B-R1 completion.

## 14. Complete 4,000-test accounting

C4-B-R1 did not achieve `4,000 passed`, and did not complete the required
accounting. The required statement is not satisfied because an additional
non-alert E2E environment failure occurred:

```text
4,000 tests were not fully collected/accounted for in this remediation.
38/44 alert tests passed.
1 alert routing failure is pre-existing contract drift.
5 alert Docker errors are pre-existing environment debt.
19 E2E setup errors are an additional PostgreSQL environment blocker.
```

No trendline-related failure was observed before the blocker. No alert file was
modified.

## 15. Known unrelated collection debt

The prescribed diagnostics for the browser-backfill, regression, regression
optimization, and SR suites were not rerun after the E2E blocker. Their prior
signatures remain recorded in the unchanged C4-B handoff; no new claim is made
here.

## 16. JavaScript viewer results

Not run. No npm dependency or lockfile change was made.

## 17. Canonical runtime smoke

Not run after the E2E blocker. Canonical ownership and module-spec smoke passed
before the blocker; canonical CLI and identity results are not claimed for this
remediation.

## 18. Static validation

Not run after the E2E blocker. No tracked implementation change occurred.

## 19. Files changed

Only the pre-existing C4-B exact-layout test modification and the two allowed
handoff paths are present:

```text
M  tests/models/test_legacy_trendline_retirement.py
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-final-ownership-regression-v1.md
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r1-known-alert-debt-v1.md
```

No alert, Docker, model, package, configuration, benchmark, research, or
canonical implementation file changed.

## 20. Git status

Expected final status after cache cleanup:

```text
 M tests/models/test_legacy_trendline_retirement.py
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-final-ownership-regression-v1.md
?? plans/coder-to-orchestrator-legacy-trendlines-c4b-r1-known-alert-debt-v1.md
```

No commit was created.

## 21. Commands executed

Executed preflight, environment, ownership-boundary, module-spec, alert blob
hash, alert routing, alert Docker, alert subset, and initial top-level matrix
commands from C4-B-R1. The matrix stopped at `tests/e2e` as required after an
unexpected non-alert failure.

## 22. Residual risks

The final broad regression is incomplete. E2E requires repository Docker
services, including PostgreSQL at `localhost:5432`, Valkey at `localhost:6380`,
and ingestion health at port `8002`. Alert routing/configuration debt remains
independent and must not be repaired on this trendline branch.

## 23. Consolidation closeout

Consolidation is not closed by this remediation. Package ownership is clean and
the trendline boundary is green, but C4-B broad regression cannot be marked
complete while 19 E2E setup errors remain unexplained by the approved alert
exceptions.

## 24. Recommended next phase

Resolve or provision approved non-alert E2E test infrastructure, then rerun
C4-B-R1 from the current worktree without changing trendline or alert code.
Only after C4-B-R1 passes should the programme advance to:

```text
L0-B — Causality and repaint-risk audit of libs.models.trendlines
```

Final disposition:

```text
BLOCKED_C4BR1_PYTHON_REGRESSION
```
