# Regression v2 Module

## Overview

`app/regression/` is the live regression channel and confidence-estimation module. It uses a 4-tier hierarchical config system, typed contracts, universe-level orchestration, and a native Bayesian optimization subsystem.

All external consumers should import exclusively from either `api.py` (native v2) or `compat.py` (v1-compatible shim).

## Status

- **Pipeline**: Production-ready
- **Optimization**: Production-ready (298 tests total)
- **YAML write-back**: `result.apply_to_yaml()` + CLI `--apply` flag (implemented)
- **V1 Compat**: Convenience re-export only — production consumers should prefer `api.py`

## Directory Structure

```text
app/regression/
  __init__.py
  api.py                        # Public facade (compute_single_tf, compute_mtf, etc.)
  compat.py                     # V1-compatible shim (same signatures as v1 api.py)
  pipeline.py                   # Single-TF pipeline runner (Features -> Methods -> Uncertainty -> Ensemble)
  registry.py                   # Plugin auto-registration
  state.py                      # StateManager ABC + Null/InMemory/Redis implementations
  universe.py                   # UniverseOrchestrator (batch N-asset, MTF cascade)

  config/
    schema.py                   # All config dataclasses (OrchestratorConfig, GlobalConfig, etc.)
    resolver.py                 # ConfigResolver: 4-tier resolution (global→tf→asset_class→asset)
    validator.py                # Config validation rules
    regression.yaml          # Default YAML config with [OPT:tier] annotations

  contracts/
    context.py                  # PipelineRequest, RegimeSnapshot, CascadeContext, AssetMeta
    result.py                   # RegressionResult, MethodResult, EnsembleResult, MTFOutput, UniverseResult

  features/                     # Stage 1: Feature Extraction
    base.py                     #   ABC: FeatureExtractor
    log_price.py                #   Log-price + NaN/zero guards
    volume_weighted.py          #   Volume transforms (sqrt/log/linear) + outlier clipping
    session_aware.py            #   Session gap handling (stocks/fx)

  methods/                      # Stage 2: Regression Algorithms
    base.py                     #   ABC: RegressionPlugin
    theil_sen.py                #   Numba-accelerated Volume-Weighted Theil-Sen with Temporal/Volatility Anchoring
    wls.py                      #   Weighted Least Squares

  uncertainty/                  # Stage 3: Uncertainty Bands
    base.py                     #   ABC: UncertaintyWrapper
    percentile_bands.py         #   Empirical quantile bands (default)

  ensemble/                     # Stage 4: Model Blending
    base.py                     #   ABC: EnsembleStrategy
    simple_weighted.py          #   Static weight × confidence
    confidence_weighted.py      #   MoE: confidence-based voting

  optimization/                 # Bayesian Hyperparameter Optimization
    models.py                   #   Data models (Config, Trial, Result, Benchmarks, Weights)
    optimizer.py                #   RegressionOptimizer (Optuna TPE/CMA-ES/Random)
    walk_forward.py             #   WalkForwardValidator (rolling + expanding + purge gap)
    search_space.py             #   SearchSpaceBuilder (tier-aware, reads [OPT:tier] metadata)
    benchmarks/                 #   5-tier composite scoring
      _common.py                #     Shared vectorized extraction
      direction_accuracy.py     #     Tier 1 (40% weight)
      band_calibration.py       #     Tier 2 (30% weight)
      residual_quality.py       #     Tier 3 (GATE — must pass)
      confidence_correlation.py #     Tier 4 confidence-return constraint (soft penalty)
      strategy_utility.py       #     Tier 5 (20% weight)
    results/                    #   Output directory for optimization JSON

  docs/
    README.md                   #   This file
    agent_guide.md              #   Agent-friendly workflow guide
    pipeline_hld.md             #   High-level architecture design
    optimization.md             #   Optimization subsystem reference
    migration_guide.md          #   V1→V2 migration instructions
    v1_removal_readiness.md     #   V1 removal assessment

  tests/                        #   Regression subsystem test suite
```

## Quick Start

### Native v2 API

```python
from app.regression.api import compute_single_tf
from app.regression.config.resolver import ConfigResolver
from app.regression.config.schema import OrchestratorConfig

resolver = ConfigResolver(OrchestratorConfig())
config = resolver.resolve("BTCUSDT", "1h")
result = compute_single_tf(df, "BTCUSDT", "1h", config)
```

### V1-Compatible Import

```python
from app.regression.compat import compute_single_tf, compute_single_tf_series
# Same call signatures as v1 — accepts RegressionContext, PipelineConfig, etc.
```

### Multi-Timeframe

```python
from app.regression.api import compute_mtf
mtf_result = compute_mtf("BTCUSDT", {"4h": df_4h, "1h": df_1h}, resolver)
```

### Universe Processing

```python
from app.regression.api import compute_universe
universe = {"BTCUSDT": {"1h": df_btc}, "ETHUSDT": {"1h": df_eth}}
result = compute_universe(universe, resolver)
```

### Optimization

```python
from app.regression.api import optimize_regression
result = optimize_regression(df, asset="BTCUSDT", timeframe="1h", n_trials=100)
print(result.best_params)
```

## Running Tests

```bash
/opt/homebrew/Caskroom/miniconda/base/bin/python -m pytest app/regression/tests/ -q --tb=short
```

## Related Documentation

- [current_truth.md](current_truth.md) — Live-code walkthrough of runtime, MTF, universe flow, and alpha fit
- [agent_guide.md](agent_guide.md) — Agent workflow reference
- [pipeline_hld.md](pipeline_hld.md) — Architecture deep-dive
- [optimization.md](optimization.md) — Optimization subsystem + YAML write-back
- [migration_guide.md](migration_guide.md) — V1→V2 drop-in migration
- [v1_removal_readiness.md](v1_removal_readiness.md) — V1 removal assessment
