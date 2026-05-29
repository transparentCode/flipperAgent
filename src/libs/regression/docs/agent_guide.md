# Regression v2 Agent Guide

Purpose: help coding agents implement regression changes safely and with full context.

## 1) Preferred Entry Points

External consumers MUST use one of:

| Import Path | Use Case |
|-|-|
| `app.regression.api` | Native v2 — typed configs, full feature set |
| `app.regression.compat` | Convenience re-export for callers that still want a stable facade |

Never import directly from:

- `app.regression.pipeline` (internal)
- `app.regression.universe` (internal)
- `app.regression.optimization.optimizer` (use `api.optimize_regression()` facade)
- Plugin packages (`features/`, `methods/`, `ensemble/`, `uncertainty/`)

## 2) Key Types Quick Reference

### Config Types (`config/schema.py`)

| Type | Purpose |
|-|-|
| `OrchestratorConfig` | Top-level config wrapping all 4 tiers |
| `GlobalConfig` | Tier 1: default features, methods, ensemble, uncertainty, ATR fractions |
| `TimeframeConfig` | Tier 2: per-TF overrides (window_size, methods, etc.) |
| `AssetClassConfig` | Tier 3: per-asset-class (volume_profile, session handling) |
| `AssetConfig` | Tier 4: per-asset + per-asset-per-TF overrides |
| `ResolvedPipelineConfig` | Fully resolved config for a single (asset, tf) pair |
| `PluginConfig` | Generic plugin config (name, enabled, weight, params dict) |
| `OptimizationTier` | Enum: GLOBAL, PER_TF, PER_ASSET_CLASS, PER_ASSET |
| `VolumeProfile` | Enum: CONTINUOUS (crypto), SESSION (stocks), PROXY (fx) |

### Contract Types (`contracts/`)

| Type | Location | Purpose |
|-|-|-|
| `PipelineRequest` | `context.py` | Input to pipeline.compute() |
| `RegimeSnapshot` | `context.py` | Regime context (label, strength, suggested_window) |
| `CascadeContext` | `context.py` | Higher-TF result passed to lower-TF |
| `AssetMeta` | `context.py` | Resolved asset metadata |
| `RegressionResult` | `result.py` | Single (asset, tf) output — slope, intercept, bands, features, etc. |
| `MethodResult` | `result.py` | Per-method output |
| `EnsembleResult` | `result.py` | Blended regression output |
| `MTFOutput` | `result.py` | Multi-TF cascade result + alignment score |
| `UniverseResult` | `result.py` | Batch N-asset output + statistics |
| `DegradationLevel` | `result.py` | Enum: FULL, PARTIAL, FALLBACK, FAILED |

### Optimization Types (`optimization/models.py`)

| Type | Purpose |
|-|-|
| `RegressionOptimizationConfig` | Search bounds, n_trials, sampler, walk-forward settings |
| `RegressionOptimizationResult` | Best params, benchmarks, all trials |
| `RegressionTrialResult` | Single trial: params, score, per-fold benchmarks |
| `RegressionBenchmarkResults` | 5-tier benchmark scores |
| `RegressionOptimizationWeights` | Tier weights + gate/constraint thresholds |

## 3) Config Resolution Chain

The 4-tier resolution works as:

```
Global → TimeframeConfig → AssetClassConfig → AssetConfig
```

`ConfigResolver.resolve(asset, timeframe) → ResolvedPipelineConfig`

Resolution rules:
1. Start with `GlobalConfig` defaults
2. Overlay `TimeframeConfig[timeframe]` (any non-None field wins)
3. Overlay `AssetClassConfig[asset_class]` (volume_profile, session handling)
4. Overlay `AssetConfig[asset]` and `AssetConfig[asset].timeframes[tf]` (most specific wins)

YAML file: `config/regression.yaml` — uses `[OPT:tier]` annotations to mark which params are optimizer-tunable.

## 4) Pipeline Stages

The pipeline executes 4 stages sequentially for each (asset, tf):

```
Features → Methods → Uncertainty → Ensemble
```

1. **Features**: Extract weighted feature arrays from OHLCV data
2. **Methods**: Run N regression algorithms (Theil-Sen, WLS)
3. **Uncertainty**: Wrap each method with uncertainty bands
4. **Ensemble**: Blend method results into consensus

## 5) Plugin System

Plugins are auto-registered via `registry.py`. Each stage has a base ABC:

| Stage | ABC | Registry Key |
|-|-|-|
| Features | `FeatureExtractor` | `features` |
| Methods | `RegressionPlugin` | `methods` |
| Uncertainty | `UncertaintyWrapper` | `uncertainty` |
| Ensemble | `EnsembleStrategy` | `ensemble` |

To add a new plugin:
1. Create file in the appropriate package (e.g., `methods/my_method.py`)
2. Implement the ABC
3. Register with `@register_plugin("methods", "my_method")`
4. Enable in config: `PluginConfig(name="my_method", weight=1.0)`

## 6) State Management

The state management infrastructure exists for future stateful plugins but no production plugins currently require it.

| Implementation | Use Case |
|-|-|
| `NullStateManager` | Default — no persistence |
| `InMemoryStateManager` | Testing / single-session |
| `RedisStateManager` | Production — cross-process state |

State key format: `{plugin_name}:{asset}:{timeframe}`

## 7) Compatibility Layer (`compat.py`)

`compat.py` is now a thin re-export layer over the v2 runtime.

It exposes the same high-level functions:
- `compute_single_tf()`, `compute_single_tf_series()`, `compute_mtf()`
- `optimize_regression()`

Production consumers should prefer `app.regression.api`. Compat remains useful
for tests, docs, and stable import surfaces.

## 8) Where To Change What

| Change | File(s) |
|-|-|
| Single-TF execution logic | `pipeline.py` |
| Multi-TF orchestration | `universe.py` |
| Config schema changes | `config/schema.py` + `config/resolver.py` |
| New regression method | `methods/new_method.py` + register |
| New feature extractor | `features/new_feature.py` + register |
| Public API surface | `api.py` |
| V1-compat shim | `compat.py` |
| Optimization benchmarks | `optimization/benchmarks/` |
| Consumer integration | Update consumer → import from `compat.py` or `api.py` |

## 9) Safe Change Workflow

1. Identify whether change is internal-only or consumer-facing.
2. If consumer-facing, update `api.py` first, then `compat.py` if needed.
3. Run tests: `/opt/homebrew/Caskroom/miniconda/base/bin/python -m pytest app/regression/tests/ -q --tb=short`
4. Verify consumer imports: `grep -r "from app.regression" app/ --include="*.py" | grep -v regression/`
5. Update docs in the same change set (README.md, this file, pipeline_hld.md).

## 10) Contract Guardrails

1. `RegressionResult` fields are the canonical output contract — do not remove fields.
2. `ResolvedPipelineConfig` is immutable after resolution — never mutate in pipeline.
3. `PipelineRequest` bundles all inputs — do not pass loose params to pipeline.
4. Compat layer must accept v1 types and return v2 `RegressionResult`.
5. ATR-normalized thresholds: do not change normalization without updating all analysis engines.

## 11) Test Organization

| Test File | Coverage Area |
|-|-|
| `test_config.py` | Schema validation, YAML loading, 4-tier resolution |
| `test_contracts.py` | Result/context dataclass construction and defaults |
| `test_features.py` | All 4 feature extractors on synthetic OHLCV |
| `test_methods.py` | All 4 regression methods |
| `test_uncertainty.py` | Percentile bands and conformal wrappers |
| `test_ensemble.py` | All 3 ensemble strategies |
| `test_pipeline.py` | End-to-end pipeline + UUID/provenance |
| `test_optimization_foundation.py` | Walk-forward, search space, model serialization |
| `test_optimization_benchmarks.py` | All 5 benchmark tiers on synthetic data |
| `test_optimization_integration.py` | Optimizer with mock pipeline, facade imports |

Total: 298 tests.

## 12) Known Deferred Work

- ~~**Dry-run mode for `apply_to_yaml`**~~: Implemented. Use `--dry-run` with `--apply` to preview YAML diff before writing.
- ~~**Backup creation**~~: Implemented. `apply_to_yaml` now creates `.bak` files before writing (controlled by `backup` parameter, default `True`).
- ~~**Search space bounds validation**~~: Implemented. `apply_to_yaml` logs warnings when params exceed optimization search bounds.
