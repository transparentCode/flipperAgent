# Regression v1 → v2 Migration Guide

## Quick Start

Change your imports:

```python
# Before (v1)
from app.regression.api import compute_single_tf, compute_single_tf_series, compute_mtf

# After (v2 compat — same signatures, v2 pipeline underneath)
from app.regression.compat import compute_single_tf, compute_single_tf_series, compute_mtf
```

No other code changes required. The compat layer accepts v1 types (`RegressionContext`, `PipelineConfig`, `OrchestratorConfig`) and returns v2 `RegressionResult`, which is a superset of v1 fields.

## What Changed

| Aspect | v1 | v2 |
|-|-|-|
| Config | `PipelineConfig` flat dataclass | 4-tier YAML: global → per-tf → per-asset-class → per-asset |
| Input | `RegressionContext` bundles df+asset+tf+lookback | `PipelineRequest` with explicit `ResolvedPipelineConfig` |
| Plugins | Hard-coded registry | Auto-registration via `PluginRegistry` |
| State | Stateless | `StateManager` ABC (Kalman, Dynamic MoE save/load) |
| Analysis | Conviction only | Removed; v2 now stops at ensemble output |
| Multi-asset | N/A | `UniverseOrchestrator` with batch processing |
| Results | `RegressionResult` | Same fields + `asset`, `config_hash`, `degradation` |

## Migration Paths

### Path 1: Drop-in Compat (Recommended First Step)

Use `app/regression/compat.py`. Exact same function signatures as v1:

```python
from app.regression.compat import compute_single_tf, compute_single_tf_series, compute_mtf
```

V1 config/context objects pass through a converter that maps them to v2 equivalents.

### Path 2: Native v2 API

For new code or when ready to fully migrate:

```python
from app.regression.api import compute_single_tf, compute_single_tf_series, compute_mtf
from app.regression.config.resolver import ConfigResolver
from app.regression.config.schema import OrchestratorConfig

# Load 4-tier config
resolver = ConfigResolver(OrchestratorConfig(...))
config = resolver.resolve("BTCUSDT", "1h")

result = compute_single_tf(df, "BTCUSDT", "1h", config)
```

### Path 3: Universe-Level Processing

New in v2 — process multiple assets at once:

```python
from app.regression.api import compute_universe
from app.regression.config.resolver import ConfigResolver

universe_data = {
    "BTCUSDT": {"1h": df_btc_1h, "4h": df_btc_4h},
    "ETHUSDT": {"1h": df_eth_1h},
}
result = compute_universe(universe_data, resolver)
```

## Config Migration

### v1 YAML (single-tier)

```yaml
timeframes: ["4h", "1h"]
pipelines:
  1h:
    window_size: 50
    features: ["log_price", "volume_weighted"]
```

### v2 YAML (4-tier)

```yaml
global:
  default_window_size: 100
  features: [log_price, volume_weighted]
  methods:
    theil_sen: {weight: 1.0}
    vwr: {weight: 1.0}

timeframes:
  1h: {window_size: 50}
  4h: {window_size: 30}

asset_classes:
  crypto: {volume_profile: continuous}
  stock: {volume_profile: session, session_gap_handling: true}

assets:
  BTCUSDT: {asset_class: crypto, mtf_enabled: true}
```

## Breaking Changes

1. **Return type**: v2 `RegressionResult` has additional fields (`asset`, `config_hash`, `degradation`, `warm_up_bars_needed`). All v1 fields are preserved.
2. **`timeframe` vs `asset`**: v1 result has `timeframe` only; v2 result has both `asset` and `timeframe`.
3. **Plugin registration**: Plugins must be imported before pipeline creation to trigger auto-registration. The compat layer does NOT auto-import plugins — your test/application code must import them.
4. **`compute_mtf` signature**: The compat version drops the `orchestrator` parameter (v1 allowed passing pre-built `MTFRegressionOrchestrator`). Pass `orchestrator_config` instead.

## New Features in v2

- **4-tier config resolution**: Global → per-timeframe → per-asset-class → per-asset
- **StateManager**: Stateful plugins (Kalman, Dynamic MoE) persist across ticks
- **Simplified runtime**: v2 now stops at ensemble output without a post-ensemble analysis stage
- **Universe orchestration**: Batch N-asset processing
- **Optional plugins**: Kalman filter, quantile regression, conformal uncertainty, dynamic mixture-of-experts
- **Asset-class awareness**: Different volume profiles for crypto vs stocks vs FX

## Already Migrated Consumers

| Consumer | File | Status |
|-|-|-|
| Cross-sectional orchestrator | `app/cross_sectional/orchestrator.py` | Migrated to compat |
| Strategy precomputer | `app/strategy/regime_regression.py` | Migrated to compat |
| Backtest bridge | `app/backtest/features/regime_regression.py` | Migrated to compat |
