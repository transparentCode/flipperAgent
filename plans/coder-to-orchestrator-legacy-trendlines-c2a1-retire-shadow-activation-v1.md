# Legacy Trendlines Consolidation C2-A1 — Retire Automatic Family-Shadow Activation

## 1. Disposition

C2-A1 complete. Automatic RegimeFeaturePipeline shadow construction and live YAML exposure were removed. Manual constructor injection and dormant shadow implementation remain. Focused, canonical, compatibility, static, import-isolation, and scope checks passed.

## 2. Starting branch and commit

- Branch: research/legacy-trendlines-quality-stability-v1.
- Starting HEAD: 57572dd3d00990701a89ad6b5e75c7d8f3bba83d.
- Starting commit: 57572dd refactor: remove trendlines_old archive.
- C1 history also contains cba86c4 test: retire trendlines_old presence contract.
- Worktree: /Users/aloobhujia/flipperAgent-wt-legacy-trendlines.
- Starting status: clean.
- C1 archive remained absent: src/libs/models/trendlines_old/.

## 3. Environment and worktree proof

- Python: 3.13.13 from /Users/aloobhujia/flipperAgent/.venv/bin/python.
- Ruff: 0.15.20 from /Users/aloobhujia/.local/bin/ruff.
- PYTHONPATH: $PWD/src:$PWD.
- Live imports resolved inside current worktree:
  - apps.signal_app.pipeline.regime
  - libs.models.regime_v2.adapters.trendline_family_feature_producer
  - libs.integrations.trendline_regime_v2
  - libs.models.trendline
- Root AGENTS.md and C1 handoff were read. No nested AGENTS.md files were found under src, tests, configs, or plans.
- Current-worktree CBM re-index was attempted and crashed on one file without changing the worktree. Existing graph results were used for call-path discovery; live source inspection was authoritative.

## 4. Pre-change automatic activation path

- src/apps/signal_app/runtime/worker.py:75-79 constructs RegimeFeaturePipeline through RegimeFeaturePipeline.create_optional.
- Before the edit, src/apps/signal_app/pipeline/regime.py:126-160 showed create_optional calling _create_trendline_family_shadow at lines 147-151 and passing its result as trendline_family_shadow at line 159.
- Graph trace identified SignalRuntimeWorker.__init__ as an inbound caller of create_optional and _create_trendline_family_shadow as an outbound callee.
- Before the edit, _create_trendline_family_shadow remained a dormant-capable helper at src/apps/signal_app/pipeline/regime.py:434-503 and lazily imported the family adapter through _load_trendline_family_shadow_adapter at lines 506-520.
- Before the edit, configs/models.yaml:433-434 contained:
  TrendlineFamilyShadow:
    enabled: false

## 5. Pre-change test baseline

- Required focused group: 68 passed in 10.69s.
- models.yaml parse: passed.
- Baseline included the existing direct helper tests and manually injected projected-shadow regression.

## 6. Runtime construction edge removed

- RegimeFeaturePipeline.create_optional now constructs only settings, resolver, legacy orchestrator, classifier, RegimeV2, and the pipeline instance at src/apps/signal_app/pipeline/regime.py:126-154.
- It no longer calls _create_trendline_family_shadow and no longer passes trendline_family_shadow to the constructor.
- Post-edit search found _create_trendline_family_shadow only as its definition and in direct/dormant tests; no production call remains in create_optional.
- New test test_optional_pipeline_does_not_construct_enabled_shadow in tests/models/regime_v2/adapters/test_trendline_family_shadow_pipeline.py monkeypatches the helper to raise, supplies a resolver returning {"enabled": True}, verifies resolver propagation to legacy classifier and RegimeV2 factories, and asserts pipeline.trendline_family_shadow is None.

## 7. Live configuration removed

- Removed default feature-producer node from configs/models.yaml.
- Post-edit search returned zero TrendlineFamilyShadow matches in configs/models.yaml.
- YAML parse passed with message models.yaml parsed without TrendlineFamilyShadow.
- Neighbouring RegimeClassification and RegimeV2 configuration was not modified.

## 8. Dormant interfaces preserved

- RegimeFeaturePipeline.__init__(..., trendline_family_shadow=...) remains unchanged.
- RegimeFeaturePipeline.trendline_family_shadow and shadow history/revision fields remain unchanged.
- refresh_trendline_family_shadow, _attach_trendline_family_shadow, _create_trendline_family_shadow, _load_trendline_family_shadow_adapter, and shadow payload helpers remain present.
- Direct helper tests were not changed.
- Manual constructor injection remains covered by tests/models/regime_v2/adapters/test_trendline_family_shadow_pipeline.py and tests/signals/test_trendline_family_shadow_projected_runtime.py.
- Adapter, integration, and singular model package paths remained present.

## 9. Import-isolation proof

- New test test_optional_pipeline_does_not_import_family_shadow_adapter runs a subprocess with the current worktree src path.
- Subprocess blocks import of libs.models.regime_v2.adapters.trendline_family_feature_producer.
- Resolver returns {"enabled": True} for TrendlineFamilyShadow.
- RegimeFeaturePipeline.create_optional succeeds, blocked adapter is absent from sys.modules, and pipeline.trendline_family_shadow is None.
- Existing optional-adapter import test remains present.

## 10. Post-change test results

- Focused C2-A1 group: 70 passed in 13.92s.
- Manually injected projected-shadow test passed within focused group.
- Canonical trendlines regression: 266 passed in 8.26s.
- C1 compatibility regression: 17 passed in 3.35s.
- Live YAML parse: passed.
- Dormant path checks: adapter file, integration package, libs.models.trendline, and libs.models.trendline_family all present.

## 11. Static validation

- compileall for runtime and both changed tests: passed.
- Ruff for runtime and both changed tests: passed.
- git diff --check: passed.
- Generated __pycache__ directories were removed by test cleanup; no inspected source/test cache directories remained at handoff.

## 12. Files changed

- Modified: src/apps/signal_app/pipeline/regime.py.
- Modified: configs/models.yaml.
- Modified: tests/models/regime_v2/adapters/test_trendline_family_shadow_pipeline.py.
- Modified: tests/models/regime_v2/adapters/test_trendline_family_shadow_optional_import.py.
- Added: plans/coder-to-orchestrator-legacy-trendlines-c2a1-retire-shadow-activation-v1.md.
- No other file was modified.

## 13. Git diff summary

Before handoff creation, git diff --stat reported 4 files changed, 100 insertions, and 8 deletions:

- configs/models.yaml: 2 deletions.
- src/apps/signal_app/pipeline/regime.py: 6 deletions.
- Optional-import test: 47 insertions.
- Pipeline test: 53 insertions.

The new handoff is untracked and intentionally uncommitted. No C1 files or unrelated paths changed.

## 14. Git status

Expected final status before review:

- M configs/models.yaml
- M src/apps/signal_app/pipeline/regime.py
- M tests/models/regime_v2/adapters/test_trendline_family_shadow_optional_import.py
- M tests/models/regime_v2/adapters/test_trendline_family_shadow_pipeline.py
- ?? plans/coder-to-orchestrator-legacy-trendlines-c2a1-retire-shadow-activation-v1.md

No staged changes and no unrelated paths.

## 15. Commands executed

Preflight and provenance:

    git branch --show-current
    git rev-parse HEAD
    git status --short --untracked-files=all
    git worktree list --porcelain
    git log -3 --oneline
    test ! -e src/libs/models/trendlines_old

Environment and source/config inspection:

    /Users/aloobhujia/flipperAgent/.venv/bin/python --version
    /Users/aloobhujia/.local/bin/ruff --version
    Python current-worktree import smoke
    rg -n -C 8 '_create_trendline_family_shadow|TrendlineFamilyShadow' src/apps/signal_app/pipeline/regime.py configs/models.yaml
    rg -n -C 5 'RegimeFeaturePipeline\.create_optional|create_optional\(' src/apps/signal_app/runtime/worker.py src/apps/signal_app
    YAML parse checks

Baseline and post-change tests:

    pytest -q focused C2-A1 group
    pytest -q src/libs/trendlines/tests
    pytest -q C1 compatibility group

Static and scope checks:

    python -m compileall -q runtime and changed tests
    ruff check runtime and changed tests
    git diff --check
    git status --short
    git diff --stat
    git diff --name-status
    dormant path tests
    __pycache__ inventory

## 16. Residual risks

- Dormant shadow state, helper, adapter, integration package, and singular model packages remain by design for C2-A2.
- Direct/manual shadow injection remains possible until C2-A2; this is intentional and tested.
- Historical documentation or research references may still mention family-shadow activation; C2-A1 did not rewrite them.
- No network calls, optimizers, replay studies, package deletions, or model relocation were performed.

## 17. Recommended next phase

C2-A2 — Remove dormant trendline-family shadow state and API from the signal pipeline

READY_FOR_C2A2_SHADOW_PIPELINE_REMOVAL
