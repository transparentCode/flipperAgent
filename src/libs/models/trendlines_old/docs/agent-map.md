# Trendlines Agent Map

Use this map when extending or debugging `app/trendlines/`. Every canonical path listed here
is accurate as of the current codebase. The legacy `app/geometry/` module has been removed.

## Canonical Ownership

- Reusable trendline logic belongs in `app/trendlines/`.
- `app/geometry/` has been removed. Do not reintroduce it.
- Consumer-facing boundary contracts and translation helpers live in `app/trendlines/boundary/`,
  including `build_boundary_result_from_trendline_result(...)` and `trendline_to_boundary_ray(...)`.
- Trendline-native signal contracts, helpers, extractors, and the orchestrator live in
  `app/trendlines/signals/`.
- All tunable hyperparameters live in `app/trendlines/config/` — not scattered in source files.
- Bayesian hyperparameter optimization lives in `app/trendlines/optimization/`.
- Reusable trendline callers should import from `app.trendlines` and `app.trendlines.boundary`
  directly.

---

## Add A New Pivot Extractor

1. Add implementation under `app/trendlines/pivots/`.
2. Return `PivotSet` from `app/trendlines/contracts/contracts.py`.
3. Decorate with `@register_extractor(name=..., search_grid=[...])` from `app/trendlines/pivots/base.py`.
4. Declare a `SearchGrid` config in `app/trendlines/config/search_grid_config.py` and reference
   it in the decorator's `search_grid` argument — do not hardcode grid values in the class.
5. Import the new module in `app/trendlines/pivots/__init__.py` to trigger registration.
6. Add focused tests in `app/trendlines/tests/test_extractors.py` or a new extractor-specific file.

See [pivots.md](pivots.md) for algorithm patterns and the `FractalPivotExtractor` as a reference.

---

## Add A New Fitter

1. Add implementation under `app/trendlines/fitting/`.
2. Implement the `TrendlineFitter` protocol from `app/trendlines/fitting/base.py`.
3. Accept pre-extracted pivots via `fit(df, pivots=None)`. Use a default `FractalPivotExtractor`
   if `pivots` is `None`.
4. Decorate with `@register_fitter(name=..., search_grid=[...])` from `app/trendlines/fitting/base.py`.
5. Declare a `SearchGrid` config in `app/trendlines/config/search_grid_config.py`.
6. Import the module in `app/trendlines/fitting/__init__.py`.
7. Add focused tests in a new fitter-specific test file.

See [fitting.md](fitting.md) for algorithm patterns and the algorithm comparison table.

---

## Change Runtime Config

- Root config: `app/trendlines/config/base_config.py` (`TrendlinesConfig`)
- Sub-configs: `config/signal_config.py`, `config/boundary_config.py`,
  `config/evaluation_config.py`, `config/search_grid_config.py`
- YAML source: `app/trendlines/config/trendlines.yaml`
- Python fallback: `app/trendlines/config/defaults.py` (`get_default_config_dict()`)
- Loader: `app/trendlines/config/loader.py` (`load_trendlines_config()`)

Rules:
- All configs are `@dataclass(frozen=True)` — use `dataclasses.replace()` to override.
- Do not add tunable values as literals in source files — add them to the appropriate sub-config.
- `TrendlinePipelineConfig` is the backward-compat wrapper — new code should use `TrendlinesConfig`.
- Pass the same `TrendlinesConfig` into `build_boundary_result_from_trendline_result(...)` and
  `TrendlineSignalOrchestrator(trendlines_config=...)` so boundary and signal defaults come from config.

See [config.md](config.md) for the full field reference.

---

## Change Boundary Logic

- Adapter: `app/trendlines/boundary/adapters.py`
  — `trendline_to_boundary_ray()`, `build_boundary_result_from_trendline_result()`
- Contracts: `app/trendlines/boundary/contracts.py`
  — `Ray`, `BoundaryResult`, `QualityMetrics`, `BOUNDARY_INTERACTION_DIRECTION`
- Policy: `app/trendlines/boundary/policy.py`
  — `ConfluenceGateConfig`, `TouchDeclusterConfig`, `RayTrackerConfig`
- Touch declustering: `app/trendlines/boundary/touches.py`
  — `decluster_touch_indices()`

**If you change boundary interaction labels or adapter-driven direction semantics**, extend
`app/trendlines/tests/test_boundary_adapters.py` because alpha direction logic in
`app/alpha/_runtime/confluence.py` consumes those outcomes downstream.

See [boundary.md](boundary.md) for the full interaction detection logic.

---

## Change Native Signals

- Base contract: `app/trendlines/signals/base.py` (`AlphaSignal`, `BaseAlphaExtractor`)
- Orchestrator: `app/trendlines/signals/orchestrator.py` (`TrendlineSignalOrchestrator`)
- Structural extractor: `app/trendlines/signals/structural.py`
- Temporal extractor: `app/trendlines/signals/temporal.py`
- Pattern extractor: `app/trendlines/signals/patterns.py`
- Fakeout extractor: `app/trendlines/signals/fakeout.py`
- Quality helpers: `app/trendlines/signals/quality.py` (uses hardcoded constants)
- Constants: `app/trendlines/signals/constants.py`
- Signal config: `app/trendlines/config/signal_config.py` (backward-compat stubs)
- Config resolution: `app/trendlines/config/resolve.py` (`ResolvedConfig`, `ResolvedSignalConfig`)

Rules:
- Keep native trendline signals self-sufficient. Do not import from `app/alpha/`.
- Architecture constants are hardcoded as module-level `_CONST` values in each extractor.
- Optimizable and derived params flow through `ResolvedConfig` → extractor kwargs.
- State transitions are derived by `build_state_transition_table()` in `config/state_transitions.py`.
- `quality.py` uses hardcoded constants — no config injection.
- Add new signal extractors by subclassing `BaseAlphaExtractor` and adding them to
  `TrendlineSignalOrchestrator.DEFAULT_EXTRACTORS`.

See [signals.md](signals.md) for per-extractor signal logic and confidence formulas.

---

## Change Pipeline Execution

- Pipeline orchestration: `app/trendlines/pipeline/orchestrator.py`
  — `run_trendline_pipeline()`, `execute_trendline_pipeline()`
- Facade API: `app/trendlines/api.py`
  — `fit_trendlines()`, `fit_trendlines_to_boundary()`, `fit_and_signal()`, `TrendlineOutput`
- Public surface: `app/trendlines/__init__.py`

Keep the pipeline module responsible for the extract → fit chain only. Boundary adaptation and
signal extraction are separate stages called by the facade, not by the pipeline orchestrator.

See [pipeline.md](pipeline.md) for the full sequence and API reference.

---

## Change Data Pipeline

- Dataset selection and replay: `app/trendlines/data/contracts.py`
- Temporal split policies and manifests: `app/trendlines/data/temporal.py`
- Injected dataset loading and manifest assembly: `app/trendlines/data/fetchers.py`
- Artifact persistence and replay I/O: `app/trendlines/data/artifacts.py`

Rules:
- Keep the data layer source-agnostic. No connector-specific behavior in `app/trendlines/data/`.
- The auto-split tier thresholds are named constants in `data/temporal.py`, not config fields.
- Manifests are hashed for deterministic replay — do not mutate them after creation.

See [data.md](data.md) for walk-forward split logic and the auto-split tier diagram.

---

## Change Workflow or Optimization Semantics

- Shared workflow contracts: `app/trendlines/workflows/common/contracts.py`
- Promotion helpers: `app/trendlines/workflows/common/promotion.py`
- Optimization engine: `app/trendlines/workflows/pipeline/engine.py`
- Fitness function: `app/trendlines/workflows/pipeline/evaluation.py`
- CLI entrypoint: `app/trendlines/workflows/pipeline/workflow.py`
- Config snippet and apply: `app/trendlines/workflows/pipeline/support.py`
- Drift monitor: `app/trendlines/workflows/monitoring/drift_monitor.py`

Registry-driven search grids come from `app/trendlines/registry/registry.py` via
`get_extractor_search_grid(name)` and `get_fitter_search_grid()`, which delegate to the
component's declared `search_grid` (set via `register_extractor` / `register_fitter` decorators
and backed by `config/search_grid_config.py`).

Bayesian optimization (Optuna TPE + walk-forward CV) lives in `app/trendlines/optimization/`:

- `optimizer.py` — `TrendlinesOptimizer` main class
- `models.py` — `TrendlinesOptimizationConfig`, `TrendlinesOptimizationResult`
- `walk_forward.py` — `WalkForwardValidator`
- `benchmarks/` — 5-tier scoring: longevity, touch_accuracy, penetration_gate, pivot_density, fold_stability

CLI scripts live in `app/trendlines/scripts/`:

- `run_optimization.py` — Argparse CLI: single/staged/universe modes, Binance data fetch with caching, StatusFileWriter for monitoring, plateau detection, YAML backup + apply
- `monitor_optimization.py` — Polls status JSON, displays progress bar, ETA, PID health check

Facade: `optimize_trendlines(df, asset, timeframe, config)` in `api.py`.

Do not route promoted trendlines results through any geometry-owned apply path.

See [workflows.md](workflows.md) for the 3-step optimization flow and fitness function breakdown.

---

## Change Public API

- Edit `app/trendlines/__init__.py`.
- Keep exports intentional and small.
- Prefer stable contracts and runner helpers over exposing implementation files.
- Run `app/trendlines/tests/test_public_api.py` after any export change to confirm stability.

---

## Change CLI Behavior

- Root command routing: `app/trendlines/cli.py`
- Pipeline optimization execution: `app/trendlines/workflows/pipeline/workflow.py`
- Drift monitor CLI: `app/trendlines/workflows/monitoring/drift_monitor.py`

Keep `cli.py` thin. Command-specific parsing and execution belong in the bounded workflow module.

---

## Debug Failures

| Symptom | Start Here |
|-|-|
| `KeyError` on `build_extractor` / `build_fitter` | `app/trendlines/registry/registry.py` — check aliases and registration |
| Bad or missing pivots | `app/trendlines/pivots/` — check window params and deduplication |
| Incorrect line slopes | `app/trendlines/fitting/` — check candle-body check / inlier filter |
| Contract mismatch or serialization error | `app/trendlines/contracts/contracts.py` — check `to_dict()` / `from_dict()` |
| Wrong interaction label | `app/trendlines/boundary/adapters.py` — `_detect_boundary_interaction()` |
| Signal confidence out of range | `app/trendlines/signals/` — check hardcoded `_CONST` values and `ResolvedSignalConfig` params |
| Wrong composite direction | `app/trendlines/signals/orchestrator.py` — `_compute_composite()` weights |
| Walk-forward folds wrong size | `app/trendlines/data/temporal.py` — `WalkForwardValidator.get_splits()` |
| Optimization fitness always low | `app/trendlines/workflows/pipeline/evaluation.py` — check `FitnessConfig` |
| Bayesian optimizer not converging | `app/trendlines/optimization/optimizer.py` — check search bounds, n_trials, gate thresholds |
| Import boundary violation | `app/trendlines/tests/test_import_boundaries.py` — 15 AST tests |
| E2E pipeline regression | `app/trendlines/tests/test_end_to_end_pipeline.py` |
| Boundary regression | `app/trendlines/tests/test_boundary_adapters.py` |

---

## Out of Scope

- Cross-domain confluence (trendlines + regime + oscillators) → `app/alpha/_runtime/confluence.py`
- Portfolio or strategy scoring
- Geometry compatibility shims (geometry module is gone — do not recreate it)
- Notebook-specific runtime glue
