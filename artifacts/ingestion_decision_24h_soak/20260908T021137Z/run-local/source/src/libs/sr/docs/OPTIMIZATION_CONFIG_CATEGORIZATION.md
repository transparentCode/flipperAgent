# SR Optimization Config Categorization

This document defines the live optimizer surface for `app.sr.optimization.UniverseSROptimizer`.

It is downstream of two approved sources:

- `plan/design-sr-config-placement-matrix-1.md`
- `app/sr/docs/KERNEL_CONFIG_CATEGORIZATION.md`

The optimizer only exposes parameters that are both:

1. placement-approved by the frozen SR config matrix, and
2. tuning-approved for the initial shared universe rollout.

The live default search profile is intentionally narrower than the full approved matrix. The code and `sr.yaml` defaults keep bounds close to the canonical runtime values so first real-universe runs explore local improvements before widening outward.

## Categories

### 1. Shared Universe-Wide Tune

These affect all optimized assets together and remain shared in the initial rollout.

| Canonical Parameter | Runtime Target | Status | Notes |
|-|-|-|-|
| `ensemble.structural_vs_micro_ratio` | `sr.ensemble.structural_vs_micro_ratio` | Live | Shared ensemble blend. |
| `lifecycle.age_lambda` | `sr.lifecycle.age_lambda` | Live | Shared lifecycle decay tune. |
| `cross_asset.sector_cluster_eps_atr` | `sr.cross_asset.sector_cluster_eps_atr` | Live | Shared Tier 6 cross-asset clustering radius. |

### 2. Kernel High-Tune

These are the approved kernel-layer strictness knobs in the initial optimizer surface.

| Canonical Parameter | Runtime Target | Status | Notes |
|-|-|-|-|
| `kernels.volume_poc.hvn_prominence` | `sr.kernels.volume_poc.hvn_prominence` | Live | HVN detection strictness. |
| `kernels.fair_value_gap.gap_min_atr` | `sr.kernels.fair_value_gap.gap_min_atr` | Live | Minimum FVG size. |
| `kernels.fair_value_gap.fill_threshold` | `sr.kernels.fair_value_gap.fill_threshold` | Live | Gap fill strictness. |
| `kernels.fair_value_gap.filled_penalty_multiplier` | `sr.kernels.fair_value_gap.filled_penalty_multiplier` | Live | Filled-gap discount. |
| `kernels.order_block.displacement_atr` | `sr.kernels.order_block.displacement_atr` | Live | Displacement strictness. |
| `kernels.order_block.imbalance_ratio` | `sr.kernels.order_block.imbalance_ratio` | Live | Order-block structure threshold. |
| `kernels.regression_band.band_width_sigma` | `sr.kernels.regression_band.band_width_sigma` | Live | Regression band width. |
| `kernels.liquidity_sweep.sweep_lookback` | `sr.kernels.liquidity_sweep.sweep_lookback` | Live | Sweep structure horizon. |
| `kernels.liquidity_sweep.max_pierce_atr` | `sr.kernels.liquidity_sweep.max_pierce_atr` | Live | Sweep strictness threshold. |
| `kernels.anchored_vwap.volume_spike_multiplier` | `sr.kernels.anchored_vwap.volume_spike_multiplier` | Pending | Volume spike detection strictness threshold. Ready to be added to optimizer later. |

### 3. Metadata-Gated Tune

These are only legal when the optimized universe structurally supports them.

| Canonical Parameter | Runtime Target | Status | Gate |
|-|-|-|-|
| `kernels.session_gap.gap_min_atr` | `sr.kernels.session_gap.gap_min_atr` | Conditional | Disabled by default. Only enable when at least one optimized asset resolves with `metadata.has_session_gaps = true`. |

### 4. Fixed / Not in Initial Optimizer

These may still be configurable in YAML, but they are not part of the initial optimizer surface.

- Asset metadata fields under `asset_metadata.*`
- All formula coefficients under `sr.rule_derived.*`
- Runtime-only derived values such as ATR, round interval, and profile histograms
- Global heuristics and guardrails such as `max_age_bars`, `zone_half_width_atr`, `max_hvn_count`, and `base_confidence`
- Low-priority per-timeframe knobs such as `validity_lookback_bars`, `num_bins`, `value_area_pct`, `channel_lookback`, and `boundary_buffer_atr`
- Non-approved non-kernel fields such as regime weights and presentation controls

## Runtime Contract

The optimizer uses canonical dotted parameter identities end-to-end:

- Optuna suggestions are created with canonical dotted names.
- Trial params are projected back into nested SR overrides at the final config-application boundary.
- Cross-asset tuning maps into `sr.cross_asset.*`, not legacy short-name aliases.
- `UniverseSROptimizer.optimize()` records the resolved search-space keys in trial and result metadata.

## Current Non-Goals

The initial rollout does not support:

- per-asset optimizer dimensions
- per-asset-per-timeframe optimizer dimensions
- rule-derived formula tuning
- optimizer exposure for regime-weight placeholders
- alternate evaluator pipelines

Any expansion beyond this surface requires a follow-up matrix/policy update first.