# S/R Pipeline — Architecture & Reference

> **Navigation Note:** For the latest live architecture deep dives covering the sidecar, config cascade, and optimization loops, start with the **[S/R Architecture Snapshot Index](SR_ARCHITECTURE_SNAPSHOT_INDEX.md)**.

## Overview

The S/R pipeline (`app/sr/`) implements a **kernel-ensemble architecture** for support/resistance detection, using composable, registrable kernels and a multi-strategy ensemble layer.

**Key design principles:**
- Kernels are stateless pure functions: OHLCV + config → `List[CandidateLevel]`
- Ensemble strategies score candidates using typed feature vectors
- Lifecycle manager tracks zones as stateful entities (formation → confirmation → expiry)
- Universe router enables multi-asset parallel processing
- Cross-asset analyzer enriches zones with inter-market intelligence

## Module Map

```
app/sr/
├── models.py               # Core data structures (CandidateLevel, ScoredLevel, etc.)
├── config_schema.py         # Typed config dataclasses (SRResolvedConfig)
├── config_resolver.py       # 4-tier config cascade + rule-derived params
├── pipeline.py              # SRv2Pipeline orchestrator (per asset/TF)
├── regime_gate.py           # Regime access gate + provider protocol
├── cross_asset.py           # Cross-asset zone analysis + enrichment
├── kernels/
│   ├── base.py              # BaseSRKernel ABC + KernelConfig
│   ├── registry.py          # KernelRegistry + @register_kernel decorator
│   ├── pivot_hl.py          # Swing pivot detection
│   ├── volume_poc.py        # Volume profile POC/VAH/VAL/HVN
│   ├── round_number.py      # Psychological levels
│   ├── order_block.py       # ICT-style order blocks
│   ├── fair_value_gap.py    # 3-candle FVG detection
│   ├── session_gap.py       # Session gap origin/destination/fill
│   ├── fractal_channel.py   # Fractal channel boundaries
│   ├── regression_band.py   # Regression band S/R
│   └── liquidity_sweep.py   # Stop-hunt rejection levels
├── ensemble/
│   ├── base.py              # BaseEnsembleStrategy ABC
│   ├── registry.py          # EnsembleRegistry + @register_ensemble
│   ├── weighted_average.py  # Default: structural/micro grouping
│   ├── confidence_weighted.py  # Self-calibrated kernel scoring
│   ├── regime_conditional.py   # Regime-aware with fallback
│   └── meta_learned.py      # XGBoost/LightGBM ML ensemble
├── lifecycle/
│   ├── state_machine.py     # ZoneLifecycleManager + ManagedZone
├── features/
│   ├── context.py           # FeatureContext (market data wrapper)
│   └── builder.py           # LevelFeatureBuilder (20 features)
├── universe/
│   ├── config.py            # UniverseSRConfig + AssetSRConfig
│   └── router.py            # UniverseSRRouter (parallel multi-asset)
├── optimization/
│   ├── __init__.py            # Public optimizer exports
│   ├── universe_optimizer.py  # Stage 1: Universe-wide joint optimizer (Optuna)
│   ├── benchmark_tier6.py     # Cross-asset agreement benchmark (Tier 6)
│   ├── multi_bar_runner.py    # Bar-by-bar pipeline execution engine
│   └── quality_metrics.py     # Zone lifecycle quality metrics + composite scoring
├── scripts/
│   └── smoke_test.py        # CLI smoke test for single + universe mode (package-owned bootstrap)
└── tests/
    ├── test_phase1.py       # 40 tests — models, config, kernels, features
    ├── test_phase2.py       # 39 tests — ensemble, lifecycle, pipeline
    ├── test_phase3.py       # 43 tests — new kernels, universe router
    ├── test_phase4.py       # Phase 4 tests — cross-asset and optimizer
    ├── test_phase5.py       # Phase 5 tests — hardening and integration
    └── test_phase1_optimizer.py  # 30 tests — multi-bar runner, quality metrics
```

## Kernel Catalog

| Kernel | Key | Description |
|-|-|-|
| `PivotHighLowKernel` | `pivot_hl` | Swing highs/lows via rolling-window local extrema |
| `VolumePOCKernel` | `volume_poc` | Volume profile POC, VAH, VAL, HVN zones across hour-derived lookbacks |
| `RoundNumberKernel` | `round_number` | Psychological round-number levels with live decimal/pip spacing |
| `OrderBlockKernel` | `order_block` | Last opposing candle before displacement move |
| `FairValueGapKernel` | `fair_value_gap` | 3-candle FVG with fill tracking |
| `SessionGapKernel` | `session_gap` | Session-boundary gap origin/destination/fill-level from upstream-adjusted, prefiltered bars |
| `FractalChannelKernel` | `fractal_channel` | Wraps `app.indicators.fractal_channel` |
| `RegressionBandKernel` | `regression_band` | Explicit injected regression result or local OLS + σ bands |
| `LiquiditySweepKernel` | `liquidity_sweep` | Optional stop-hunt rejection levels around recently swept pivots |

`volume_hvn` is not a standalone runtime kernel. HVN candidates are emitted by `VolumePOCKernel` metadata and enabled through `volume_poc`.

`liquidity_sweep` is implemented and supported, but it is not enabled in the default kernel set.

All kernels implement `BaseSRKernel.compute(df, config) → List[CandidateLevel]` and register via `@register_kernel("name")`.

## Ensemble Strategies

| Strategy | Key | Description |
|-|-|-|
| `WeightedAverageEnsemble` | `weighted_average` | Default. Groups kernels as structural/micro, redistributing weight across the active families with a configurable ratio |
| `ConfidenceWeightedEnsemble` | `confidence_weighted` | Self-calibrated by per-kernel average raw_score, with optional configured baselines for live or singleton batches |
| `RegimeConditionalEnsemble` | `regime_conditional` | Augments weighted_average with regime multipliers |
| `MetaLearnedEnsemble` | `meta_learned` | XGBoost/LightGBM prediction blended with touch/agreement priors from nested config, with weighted_average fallback |

## Feature Vector (20 features)

| Feature | Source |
|-|-|
| `touch_count` | Price history proximity |
| `rejection_ratio` | Wick analysis |
| `volume_at_touches` | Volume at level |
| `time_since_formation` | Temporal |
| `cluster_density` | Spatial clustering |
| `atr_distance_from_price` | Price proximity |
| `poc_distance_atr` | Volume profile |
| `value_area_overlap` | Volume profile |
| `mtf_confluence_count` | Multi-timeframe |
| `breakout_recency` | Temporal |
| `volume_trend_at_level` | Volume trend |
| `wick_depth_max_atr` | Wick depth |
| `false_breakout_count` | Lifecycle |
| `kernel_agreement` | Multi-kernel consensus |
| `gap_proximity_atr` | Session gaps |
| `gap_direction_alignment` | Session gaps |
| `regime_alignment` | Regime context |
| `universe_agreement` | Cross-asset (Phase 4) |
| `sector_cluster` | Cross-asset (Phase 4) |
| `dominant_alignment` | Cross-asset (Phase 4) |

Feature-runtime note:
`touch_count` now uses the explicit `sr.features.touch_proximity_atr` knob. The expensive historical scans behind `volume_trend_at_level` and `false_breakout_count` no longer assume fixed universal bar counts in the main runtime path; they derive weekly/monthly horizons from `asset_metadata.session_lookback_hours` plus the active timeframe, with explicit hour overrides available in `sr.features` and a legacy 200/500-bar fallback only when metadata is unavailable.

## Config Cascade (4-tier)

Resolution order (highest priority wins):

1. **Asset metadata** — profile-based defaults (crypto/equity/fx/commodity/futures)
2. **Global config** — `sr.*` section in YAML
3. **Per-TF overrides** — `per_tf.{timeframe}.*`
4. **Per-asset overrides** — `assets.{symbol}.defaults.*` and `assets.{symbol}.{tf}.*`

Rule-derived params computed via formula coefficients from `AssetCharacteristics` (ATR, volatility rank, volume factor, session hours, tick granularity).

## Zone Lifecycle

States: `FORMING → ACTIVE ↔ TESTED → BROKEN → FALSE_BREAKOUT → ACTIVE` / `→ FLIPPED` / `→ EXPIRED`

Every transition emits an immutable `ZoneLifecycleEvent` for audit trail.

## Usage Examples

Optimizer-surface note:
The live optimizer no longer exposes ad hoc short names such as `cluster_eps_atr` or unused regime-weight knobs. The approved initial surface uses canonical dotted SR config identities and is documented in `app/sr/docs/OPTIMIZATION_CONFIG_CATEGORIZATION.md`.

### Single Asset Pipeline

```python
from app.sr.pipeline import SRv2Pipeline
from app.sr.config_resolver import SRConfigResolver

resolver = SRConfigResolver()
config = resolver.resolve("BTCUSDT", "1h", raw_config)

# No manual concrete-kernel imports are required.
pipeline = SRv2Pipeline(config, asset="BTCUSDT", timeframe="1h")
result = pipeline.run(df, bar_index=100)

# result.candidates       — raw kernel output
# result.scored_levels     — ensemble-scored
# result.active_zones      — lifecycle-managed zones
# result.events            — lifecycle transitions this bar
```

### Debug + Timing Mode

```python
result = pipeline.run(df, bar_index=100, debug=True, timing=True)

# result.timing["kernels_ms"]   — kernel detection latency
# result.timing["features_ms"]  — feature computation latency
# result.timing["ensemble_ms"]  — ensemble scoring latency
# result.timing["lifecycle_ms"] — lifecycle update latency
# result.timing["total_ms"]     — total pipeline latency

# result.debug["candidates_by_kernel"]  — candidates grouped by kernel
# result.debug["feature_vectors"]       — all computed feature vectors
# result.debug["context"]               — ATR, price, volume, regime state
# result.debug["ensemble_config"]       — ensemble config used
# result.debug["all_zones"]             — all zones including expired
# result.debug["lifecycle_config"]      — lifecycle config used
```

### Universe (Multi-Asset) Pipeline

```python
from app.sr.universe.router import UniverseSRRouter
from app.sr.universe.config import AssetSRConfig, UniverseSRConfig

universe_config = UniverseSRConfig(
    assets=[
        AssetSRConfig(symbol="BTCUSDT", timeframes=["1h", "4h"]),
        AssetSRConfig(symbol="ETHUSDT", timeframes=["1h", "4h"]),
        AssetSRConfig(symbol="SOLUSDT", timeframes=["1h", "4h"]),
    ],
    global_config=global_config,
)
router = UniverseSRRouter(universe_config)

# data_map: {asset: {timeframe: pd.DataFrame}}
result = router.process(data_map, bar_index=100)
# result.results — dict of (asset, tf) → AssetTimeframeResult
```

### Cross-Asset Enrichment

```python
from app.sr.cross_asset import CrossAssetSRAnalyzer, CrossAssetConfig

analyzer = CrossAssetSRAnalyzer(CrossAssetConfig())
enriched = analyzer.analyze(
    universe_zones=zones_per_asset,
    correlation_matrix=corr_matrix,
    dominant_assets=["BTCUSDT"],
)
# enriched["ETHUSDT"].enriched_zones — zones with cross-asset features
```

## Running Tests

```bash
# All v2 tests
pytest app/sr/tests/ -v

# Specific phase
pytest app/sr/tests/test_phase3.py -v
```

## Phase Completion Status

| Phase | Tasks | Tests | Status |
|-|-|-|-|
| Phase 1: Core Models + Kernels | TASK-001 – TASK-009 | 40 | ✅ |
| Phase 2: Ensemble + Lifecycle | TASK-010 – TASK-019 | 39 | ✅ |
| Phase 3: New Kernels + Universe | TASK-020 – TASK-028 | 43 | ✅ |
| Phase 4: Cross-Asset + Optimization | TASK-029 – TASK-035 | 26 | ✅ |
| Phase 5: Observability + Hardening | TASK-036 – TASK-042 | — | ✅ |
| Phase 6: Per-Asset Optimizer | Phase 1 of 4 complete | 30 | ⏳ |

## Related Docs

| Doc | Description |
|-|-|
| [OPTIMIZATION.md](OPTIMIZATION.md) | Full optimization architecture, parameter surface, quality metrics, two-stage design |
| [OPTIMIZATION_CONFIG_CATEGORIZATION.md](OPTIMIZATION_CONFIG_CATEGORIZATION.md) | Live optimizer parameter categorization and approval status |
| [KERNEL_REFERENCE.md](KERNEL_REFERENCE.md) | Per-kernel structural needs, tradeoffs, and runtime knobs |
| [KERNELS_AND_FEATURES.md](KERNELS_AND_FEATURES.md) | Kernel catalog and feature vector reference |
| [KERNEL_CONFIG_CATEGORIZATION.md](KERNEL_CONFIG_CATEGORIZATION.md) | Kernel config placement policy |
| [SR_CONFIG_PLACEMENT_POLICY.md](SR_CONFIG_PLACEMENT_POLICY.md) | Config cascade placement rules |
