# Legacy Trendlines Consolidation C2-A2
## Remove Dormant Trendline-Family Shadow State and API from the Signal Pipeline

## 1. Disposition

C2-A2 implementation complete. Automatic and dormant signal-application
trendline-family shadow state, API, helpers, adapter loading, and projected
refresh call were removed. Ordinary regime history advancement remains active.

No adapter, integration package, singular trendline package, or canonical
plural trendlines package was deleted or moved. No commit was created.

## 2. Starting branch and commit

- Branch: `research/legacy-trendlines-quality-stability-v1`
- Worktree: `/Users/aloobhujia/flipperAgent-wt-legacy-trendlines`
- Starting commit: `fa95d01c6716960e087f3d1874d4edc5d8540746`
- Recent history included committed C1 archive removal and C2-A1 automatic
  shadow-activation removal.
- `src/libs/models/trendlines_old/` was absent at preflight.
- Worktree was clean at preflight; final status contains only authorized C2-A2
  changes and the required untracked handoff.

## 3. Environment and worktree proof

- Python: `/Users/aloobhujia/flipperAgent/.venv/bin/python`, version 3.13.13.
- Ruff: `/Users/aloobhujia/.local/bin/ruff`, version 0.15.20.
- `PYTHONPATH` used: `$PWD/src:$PWD`.
- `apps.signal_app.pipeline.features`, `apps.signal_app.pipeline.regime`,
  `apps.signal_app.runtime.worker`, the family adapter, its integration package,
  and `libs.models.trendline` all resolved inside this worktree.
- No dependency installation or network workflow was performed.

## 4. Pre-change dormant surface

The starting commit contained the following shadow surface in
`src/apps/signal_app/pipeline/regime.py`:

- `_UnavailableTrendlineFamilyShadowProducer` at line 29.
- `RegimeFeaturePipeline.__init__` shadow parameter at line 90 and
  `self.trendline_family_shadow` at line 114.
- Shadow state fields at lines 117-121.
- Shadow handling in `prime()` at lines 160-183 and `append_bar()` at lines
  188-206; `append_bar()` accepted `timestamp`.
- Shadow enrichment/refresh methods at lines 219-332.
- Shadow history trimming at lines 334-338.
- Shadow construction and helper functions at lines 428-643, including adapter
  loading, timestamp normalization, frame construction, and failure/cache
  payload helpers.

The starting automatic projected path in
`src/apps/signal_app/runtime/worker.py:499-510` appended a confirmed bar and
then called `refresh_trendline_family_shadow()`. Standard feature processing in
`src/apps/signal_app/pipeline/features.py:120` passed
`timestamp=candle.timestamp` to `append_bar()`.

## 5. Pre-change test baseline

At starting commit, required baselines passed:

- C2-A1 focused runtime group: `70 passed in 12.42s`.
- Canonical trendlines suite: `266 passed in 8.22s`.
- C1 compatibility group: `17 passed in 3.29s`.

## 6. Constructor and state removed

`RegimeFeaturePipeline` in
`src/apps/signal_app/pipeline/regime.py` no longer accepts
`trendline_family_shadow`; no deprecated keyword or `**kwargs` fallback was
added. Its shadow attribute and all five shadow history, revision, error, and
payload-cache fields were removed.

`prime()` now handles ordinary price history and classification cache state
only. `append_bar()` now has signature
`append_bar(self, bar_data: dict[str, float]) -> None`; it normalizes and trims
ordinary OHLCV history only. `enrich()` now attaches only legacy regime,
classification, and RegimeV2 outputs.

## 7. Shadow methods and helpers removed

Removed from `src/apps/signal_app/pipeline/regime.py`:

- `_UnavailableTrendlineFamilyShadowProducer`
- `refresh_trendline_family_shadow`
- `_attach_trendline_family_shadow`
- `_cache_trendline_family_payload`
- `_create_trendline_family_shadow`
- `_load_trendline_family_shadow_adapter`
- `_shadow_config_is_disabled`
- `_bar_tuple_to_trendline_family_bar`
- `_trendline_family_frame`
- `_normalize_shadow_timestamp`
- `_shadow_failure_payload`
- `_minimal_shadow_failure_payload`
- `_cached_shadow_payload`

No replacement helper, import shim, generic shadow cache, or fallback producer
was introduced.

## 8. Standard append path preserved

`src/apps/signal_app/pipeline/features.py:120` still appends the current bar
when `append_current_bar` is enabled, now with
`self.regime_features.append_bar(bar_data)` and no timestamp argument.
Ordinary OHLCV validation and append timing were preserved.

## 9. Projected append path preserved

`src/apps/signal_app/runtime/worker.py:497-508` still evaluates and enriches
the active projected vector before appending a bar when `projected.closed` is
true. The append remains exactly once on confirmed close, now without a
timestamp argument. The second shadow refresh call was removed. Projection
commit timing and incomplete-update behavior were not changed.

## 10. Obsolete tests retired

- Deleted `tests/models/regime_v2/adapters/test_trendline_family_shadow_pipeline.py`,
  which exercised removed signal-pipeline shadow APIs.
- Updated `tests/models/regime_v2/adapters/test_trendline_family_shadow_optional_import.py`
  to prove `RegimeFeaturePipeline` imports and constructs without importing the
  optional family adapter, and exposes no removed shadow API.
- Replaced
  `tests/signals/test_trendline_family_shadow_projected_runtime.py` with
  `tests/signals/test_regime_projected_runtime.py`.

The standalone adapter test remained unchanged and continues to cover the
underlying adapter pending C2-A3.

## 11. Replacement projected-runtime contract

`tests/signals/test_regime_projected_runtime.py::test_projected_regime_history_advances_once_on_confirmed_decision_close`
records closed status, history length before and after processing, and the
RegimeV2-reported history length for each projection. It asserts:

- incomplete projections do not append;
- a confirmed close appends one ordinary price bar;
- RegimeV2 observes history before that append;
- a later projection observes advanced history;
- no vector contains `trendline_family_shadow`;
- at least one incomplete and one closed projection occur;
- no duplicate append or refresh occurs.

The replacement test has no imports from the singular model, family model,
family adapter, or trendline RegimeV2 integration.

## 12. Structural absence proof

- `RegimeFeaturePipeline` constructor has no `trendline_family_shadow`
  parameter.
- `RegimeFeaturePipeline.append_bar()` has no `timestamp` parameter.
- `RegimeFeaturePipeline` instances have no `trendline_family_shadow`,
  `refresh_trendline_family_shadow`, `_trendline_family_history`, or
  `_trendline_family_last_payload` attributes.
- `rg` over `src/apps/signal_app` found zero trendline-family shadow runtime
  references.
- Production has one standard and one projected `regime_features.append_bar`
  caller; neither passes `timestamp=`.
- The family adapter, `libs.integrations.trendline_regime_v2`,
  `libs.integrations.trendline_configuration`, `libs.models.trendline`, and
  `libs.models.trendline_family` paths remain present.
- The optional-import subprocess test passed with the family adapter blocked
  and absent from `sys.modules`.

## 13. Post-change test results

- Adapter directory plus replacement projected-runtime, wiring, and foundation
  tests: `71 passed in 11.50s`.
- Focused optional-import, replacement projected-runtime, wiring, and
  foundation group: `57 passed in 15.55s`.
- Standalone family adapter suite: `14 passed in 2.37s`.
- Canonical trendlines suite: `266 passed in 7.62s`.
- C1 compatibility group: `17 passed in 3.17s`.

The deleted shadow-pipeline test was not collected. No remaining test was
skipped, deleted merely to obtain a passing result, or weakened outside its
authorized rewrite.

## 14. Static validation

- Required `compileall` command: passed.
- Required Ruff command: `All checks passed!`.
- `git diff --check`: passed.
- Generated `__pycache__` files were removed before handoff.

## 15. Files changed

- Modified `src/apps/signal_app/pipeline/regime.py`.
- Modified `src/apps/signal_app/pipeline/features.py`.
- Modified `src/apps/signal_app/runtime/worker.py`.
- Modified `tests/models/regime_v2/adapters/test_trendline_family_shadow_optional_import.py`.
- Deleted `tests/models/regime_v2/adapters/test_trendline_family_shadow_pipeline.py`.
- Deleted `tests/signals/test_trendline_family_shadow_projected_runtime.py`.
- Added `tests/signals/test_regime_projected_runtime.py`.
- Added this handoff.

No other path changed.

## 16. Git diff summary

Before adding untracked handoff and replacement-test paths to the index, Git
reported the tracked portion as:

`6 files changed, 11 insertions(+), 1043 deletions(-)`.

Git reports the old projected test as deleted and the replacement as untracked;
the intended review interpretation is one authorized test-path replacement.

## 17. Git status

Final worktree is intentionally uncommitted. Expected status:

```text
 M src/apps/signal_app/pipeline/features.py
 M src/apps/signal_app/pipeline/regime.py
 M src/apps/signal_app/runtime/worker.py
 M tests/models/regime_v2/adapters/test_trendline_family_shadow_optional_import.py
 D tests/models/regime_v2/adapters/test_trendline_family_shadow_pipeline.py
 D tests/signals/test_trendline_family_shadow_projected_runtime.py
?? tests/signals/test_regime_projected_runtime.py
?? plans/coder-to-orchestrator-legacy-trendlines-c2a2-remove-shadow-pipeline-v1.md
```

## 18. Commands executed

Preflight and environment:

- `git branch --show-current`
- `git rev-parse HEAD`
- `git status --short --untracked-files=all`
- `git worktree list --porcelain`
- `git log -4 --oneline`
- Python/Ruff version and worktree import-resolution checks.

Baseline and validation:

- Required C2-A1 focused pytest group.
- Canonical trendlines pytest suite.
- C1 compatibility pytest group.
- Adapter-directory, signal/regime, projected-runtime, wiring, and foundation
  pytest group.
- Standalone family adapter pytest suite.
- Required `compileall` and Ruff commands.
- Structural API, import-isolation, path-presence, append-caller, forbidden
  import, and signal-application shadow-reference checks.
- `git diff --check`, status, diff stat, and diff name-status checks.
- Cleanup of generated `__pycache__` files.

## 19. Residual risks

- RegimeV2 family adapter, integration packages, and singular model packages
  remain in the repository. Their broader consumers require the separate
  C2-A3 audit/removal phase.
- Adapter behavior remains independently tested, but no signal-application
  runtime path now exercises it.
- Codebase-memory re-index was not repaired; source inspection and executable
  tests were used as authoritative evidence per phase instruction.

## 20. Recommended next phase

C2-A3 — Remove the RegimeV2 trendline-family adapter and integration packages

READY_FOR_C2A3_ADAPTER_INTEGRATION_REMOVAL
