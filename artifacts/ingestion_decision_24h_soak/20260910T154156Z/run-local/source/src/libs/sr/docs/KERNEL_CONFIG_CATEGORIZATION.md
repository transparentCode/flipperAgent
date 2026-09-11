# Kernel Config Categorization (S/R v2)

This document classifies kernel-layer inputs by source, placement policy, and optimization profile so the S/R v2 module has one durable reference for hyperparameter tuning, runtime-derived values, and non-optimizable asset-nature controls.

The full field-by-field placement source of truth is `plan/design-sr-config-placement-matrix-1.md`. The compact non-kernel policy reference lives in `app/sr/docs/SR_CONFIG_PLACEMENT_POLICY.md`. This document mirrors the approved placement policy for kernel-layer inputs using the same taxonomy vocabulary.

## 1. Categories

| Category | Meaning | Optimization Profile |
|-|-|-|
| Rule-derived / asset nature | Derived from `AssetMetadata`, `RuleDerivedParams`, or structural market assumptions. | Fixed; never optimize directly. |
| Shared runtime-derived | Computed from the input data at run time such as ATR, current price, highs/lows, or injected results. | Not config; not part of hyperparameter search. |
| Global fixed heuristic | Safety limits, clipping caps, and baseline scoring defaults that standardize execution. | Fixed globally unless research explicitly proves otherwise. |
| Per-timeframe low-tune | Sensitivities that may vary with chart resolution but should not explode the search space. | Low-priority tuning. |
| Per-asset / per-TF high-tune | Detection strictness knobs that materially change pattern frequency or selectivity. | Primary optimization surface. |
| Legacy alias | Backward-compatibility input normalized by the resolver. | Do not optimize; remove after migration. |

## 2. Shared Classes

### 2.1 `PipelineConfig`

| Input | Category | Notes |
|-|-|-|
| `enabled_kernels` | Global fixed heuristic | Feature-selection surface, not a kernel-level optimizer knob. |
| `atr_period` | Global fixed heuristic | Shared normalization horizon used by all ATR-scaled kernels. |
| `avg_volume_window` | Global fixed heuristic | Shared feature-context input, not kernel-specific. |
| `merge_threshold_pct_atr` | Global fixed heuristic | Downstream deduplication guardrail, not a detection threshold. |

### 2.2 `KernelConfig`

| Input | Category | Notes |
|-|-|-|
| `kernel_params` | Mixed | Contains the explicit per-kernel config knobs listed below. |
| `metadata` | Rule-derived / asset nature | Carries market structure flags such as `has_session_gaps` and round-number mode. |
| `rule_derived` | Rule-derived / asset nature | Carries derived values such as `n1`, `n2`, `round_interval`, `vp_lookback_hours`, and `fractal_period`. |
| `extra` | Shared runtime-derived | Injected runtime objects such as `regression_result`; not part of YAML optimization. |
| `atr_period` | Global fixed heuristic | Shared ATR normalization knob inherited from pipeline config. |

## 3. Kernel Matrix

### 3.1 `PivotHighLowKernel` (`pivot_hl`)

| Input | Source | Category | Optimization Profile | Notes |
|-|-|-|-|-|
| `n1`, `n2` | `rule_derived` | Rule-derived / asset nature | Fixed | Derived from volatility-aware pivot formulas. |
| `historical_depth` | `kernel_params` | Global fixed heuristic | Fixed or low | Bounds the candidate scan horizon without clipping the left-context bars required to confirm a pivot. |
| `smoothing_period` | `kernel_params` | Per-timeframe low-tune | Low | Noise suppression is timeframe-sensitive. |
| `zone_half_width_atr` | `kernel_params` | Global fixed heuristic | Fixed globally | Standardizes point-to-zone conversion. |
| `vol_factor_weight` | `kernel_params` | Global fixed heuristic | Fixed globally | Internal score weighting, not asset-specific structure. |
| `dominance_weight` | `kernel_params` | Global fixed heuristic | Fixed globally | Internal score weighting, paired with volume weight. |
| `min_bars` | `kernel_params` | Global fixed heuristic | Fixed globally | Data sufficiency guardrail and part of the canonical schema/default config surface. |
| ATR, highs, lows, volume, timestamps | Runtime data | Shared runtime-derived | Not optimized | Calculated per invocation. |
| `score_vol_weight`, `score_dominance_weight` | Resolver alias | Legacy alias | None | Normalized to canonical pivot score weights. |

### 3.2 `VolumePOCKernel` (`volume_poc`)

| Input | Source | Category | Optimization Profile | Notes |
|-|-|-|-|-|
| `vp_lookback_hours` | `rule_derived` | Rule-derived / asset nature | Fixed | Derived from session structure. |
| `num_bins` | `kernel_params` | Per-timeframe low-tune | Low | Histogram granularity depends on timeframe resolution. |
| `value_area_pct` | `kernel_params` | Global fixed heuristic | Fixed or low | Common market-profile convention. |
| `poc_strength`, `vah_val_strength`, `hvn_strength` | `kernel_params` | Global fixed heuristic | Fixed globally | Baseline kernel scoring weights. |
| `max_hvn_count` | `kernel_params` | Global fixed heuristic | Fixed globally | Prevents candidate explosion. |
| `hvn_prominence` | `kernel_params` | Per-asset / per-TF high-tune | High | Governs how selective HVN detection is. |
| `zone_half_width_atr` | `kernel_params` | Global fixed heuristic | Fixed globally | Shared zone-width normalization. |
| `hvn_min_distance_atr` | `kernel_params` | Per-timeframe low-tune | Low | Controls local duplicate suppression. |
| `min_bars` | `kernel_params` | Global fixed heuristic | Fixed globally | Per-lookback data sufficiency floor. |
| ATR, timestamps, profile histogram, value area extraction | Runtime data | Shared runtime-derived | Not optimized | Calculated from the active data window; timestamps normalize to deterministic UTC values, and non-datetime indexes preserve hour-based lookbacks through timeframe-aware bar conversion. |

### 3.3 `FairValueGapKernel` (`fair_value_gap`)

| Input | Source | Category | Optimization Profile | Notes |
|-|-|-|-|-|
| `gap_min_atr` | `kernel_params` | Per-asset / per-TF high-tune | High | Primary strictness threshold for gap detection. |
| `fill_threshold` | `kernel_params` | Per-asset / per-TF high-tune | High | Governs how deeply price must re-enter the gap before penalty applies. |
| `max_age_bars` | `kernel_params` | Global fixed heuristic | Fixed globally | Search bound and memory-control parameter. |
| `validity_lookback_bars` | `kernel_params` | Per-timeframe low-tune | Low | Controls the chop filter horizon. |
| `fvg_strength` | `kernel_params` | Global fixed heuristic | Fixed globally | Baseline kernel score weighting. |
| `max_gap_atr_cap` | `kernel_params` | Global fixed heuristic | Fixed globally | Scoring cap that prevents runaway gap-size rewards. |
| `filled_penalty_multiplier` | `kernel_params` | Per-asset / per-TF high-tune | High | Directly discounts partially or fully re-entered gaps. |
| `min_bars` | `kernel_params` | Global fixed heuristic | Fixed globally | Data sufficiency guardrail. |
| ATR, highs, lows, closes, timestamps | Runtime data | Shared runtime-derived | Not optimized | Computed from the active OHLCV window. |
| `score_atr_cap`, `filled_score_discount` | Resolver alias | Legacy alias | None | Normalized to `max_gap_atr_cap` and `filled_penalty_multiplier`. |

### 3.4 `OrderBlockKernel` (`order_block`)

| Input | Source | Category | Optimization Profile | Notes |
|-|-|-|-|-|
| `displacement_atr` | `kernel_params` | Per-asset / per-TF high-tune | High | Main strictness threshold for valid displacement candles. |
| `imbalance_ratio` | `kernel_params` | Per-asset / per-TF high-tune | High | Controls body-vs-range selectivity. |
| `max_age_bars` | `kernel_params` | Global fixed heuristic | Fixed globally | Search bound. |
| `validity_lookback_bars` | `kernel_params` | Per-timeframe low-tune | Low | Governs break-of-structure confirmation horizon and is part of the canonical schema/default config surface. |
| `ob_strength` | `kernel_params` | Global fixed heuristic | Fixed globally | Baseline kernel scoring weight. |
| `min_bars` | `kernel_params` | Global fixed heuristic | Fixed globally | Data sufficiency guardrail. |
| ATR, candle bodies, highs/lows, volume, timestamps | Runtime data | Shared runtime-derived | Not optimized | Computed per invocation. |

### 3.5 `SessionGapKernel` (`session_gap`)

| Input | Source | Category | Optimization Profile | Notes |
|-|-|-|-|-|
| `metadata.has_session_gaps` | `AssetMetadata` | Rule-derived / asset nature | Fixed | Structural market flag; controls whether kernel is active at all. |
| `gap_min_atr` | `kernel_params` | Per-asset / per-TF high-tune | High | Primary gap strictness threshold. |
| `fill_level_fractions` | `kernel_params` | Per-timeframe low-tune | Low | Determines secondary fill-level emissions. |
| `max_age_bars` | `kernel_params` | Global fixed heuristic | Fixed globally | Search bound. |
| `gap_origin_strength`, `gap_dest_strength`, `fill_level_strength` | `kernel_params` | Global fixed heuristic | Fixed globally | Relative output scoring weights. |
| `max_gap_atr_cap` | `kernel_params` | Global fixed heuristic | Fixed globally | Score clipping guardrail. |
| `min_bars` | `kernel_params` | Global fixed heuristic | Fixed globally | Data sufficiency guardrail. |
| ATR, opens, closes, timestamps | Runtime data | Shared runtime-derived | Not optimized | Computed from the active bar stream; timestamp discontinuities define valid session boundaries, while corporate-action effects and intraday non-session jumps are expected to be adjusted or filtered upstream before any module processes the bars. |
| `score_atr_cap` | Resolver alias | Legacy alias | None | Normalized to `max_gap_atr_cap`. |

### 3.6 `FractalChannelKernel` (`fractal_channel`)

| Input | Source | Category | Optimization Profile | Notes |
|-|-|-|-|-|
| `fractal_period` | `rule_derived` | Rule-derived / asset nature | Fixed | Derived from pivot/fractal formulas and used as the base channel period. |
| `fractal_buffer` | `rule_derived` | Rule-derived / asset nature | Fixed | Resolver computes this and the wrapper can auto-use it when `use_rule_derived_buffer` is enabled. |
| `channel_lookback` | `kernel_params` | Per-timeframe low-tune | Low | Window length is timeframe-sensitive and is now part of the canonical schema/default config surface. |
| `boundary_buffer_atr` | `kernel_params` | Per-timeframe low-tune | Low | Buffer width is tied to ATR-normalized display and detection width; current runtime fallback is still a local `0.1 * ATR`, not `rule_derived.fractal_buffer`. |
| `use_rule_derived_buffer` | `kernel_params` | Global fixed heuristic | Fixed globally | Output-policy toggle that switches buffer sourcing from explicit ATR fraction to rule-derived absolute buffer. |
| `pivot_method` | `kernel_params` | Global fixed heuristic | Fixed globally | Structural algorithm choice, not a search-grid scalar. |
| `mode` | `kernel_params` | Global fixed heuristic | Fixed globally | Structural algorithm mode. |
| `emit_midline` | `kernel_params` | Global fixed heuristic | Fixed globally | Output policy rather than detection strictness. |
| `channel_strength` | `kernel_params` | Global fixed heuristic | Fixed globally | Baseline boundary scoring. |
| `midline_strength_factor` | `kernel_params` | Global fixed heuristic | Fixed globally | Derived output discount; only relevant when `emit_midline` is enabled. |
| `min_bars` | `kernel_params` | Global fixed heuristic | Fixed globally | Data sufficiency guardrail. |
| ATR, timestamp, fractal-channel result object | Runtime data | Shared runtime-derived | Not optimized | Computed or injected at run time. |
| `boundary_buffer`, `midline_score_discount` | Resolver alias | Legacy alias | None | Runtime should consume canonical names only. |

Fractal Channel wrapper review notes:

- The SR kernel exposes only a thin wrapper over `app.indicators.fractal_channel.FractalChannel`; the richer indicator fit and runtime controls are not currently part of the SR kernel optimization surface.
- The wrapper now binds the exact `fc_upper_{lookback}_{mode}` and `fc_lower_{lookback}_{mode}` columns, so stale fractal-channel outputs on the same frame should not leak into candidate generation.
- Unexpected indicator failures now propagate instead of being silently normalized to `[]`; an empty candidate set should mean no usable channel output was produced.
- Rule-derived `fractal_buffer` is now available as an opt-in automatic buffer source via `use_rule_derived_buffer`; explicit `boundary_buffer_atr` remains the default path.
- Midline semantics are not operationally validated yet. The current implementation emits the optional midline as `SUPPORT` by convention, but that should be treated as provisional until the kernel is exercised in live research or replaced with an explicit classification rule.

### 3.7 `RegressionBandKernel` (`regression_band`)

| Input | Source | Category | Optimization Profile | Notes |
|-|-|-|-|-|
| `band_width_sigma` | `kernel_params` | Per-asset / per-TF high-tune | High | Primary selectivity knob for band width. |
| `emit_center` | `kernel_params` | Global fixed heuristic | Fixed globally | Output policy rather than detection strictness. |
| `band_strength`, `center_strength` | `kernel_params` | Global fixed heuristic | Fixed globally | Baseline scoring weights. |
| `zone_half_width_atr` | `kernel_params` | Global fixed heuristic | Fixed globally | Shared output width normalization. |
| `min_bars` | `kernel_params` | Global fixed heuristic | Fixed globally | Data sufficiency guardrail. |
| `extra.regression_result` | `KernelConfig.extra` | Shared runtime-derived | Not optimized | Optional pre-computed regression result; ignored when present but invalid. |
| ATR, local OLS fallback | Runtime data | Shared runtime-derived | Not optimized | Uses local OLS + σ bands when no usable injected regression result exists. |

### 3.8 `LiquiditySweepKernel` (`liquidity_sweep`)

| Input | Source | Category | Optimization Profile | Notes |
|-|-|-|-|-|
| `sweep_lookback` | `kernel_params` | Per-asset / per-TF high-tune | High | Primary structure horizon for swept pivots. |
| `max_pierce_atr` | `kernel_params` | Per-asset / per-TF high-tune | High | Strictness threshold for tolerated wick penetration. |
| `max_age_bars` | `kernel_params` | Global fixed heuristic | Fixed globally | Search bound for how far back the kernel scans for sweeps. |
| `sweep_strength` | `kernel_params` | Global fixed heuristic | Fixed globally | Baseline score weight. |
| `zone_half_width_atr` | `kernel_params` | Global fixed heuristic | Fixed globally | Shared output width normalization. |
| `min_bars` | `kernel_params` | Global fixed heuristic | Fixed globally | Data sufficiency guardrail. |
| ATR, highs, lows, closes, timestamps | Runtime data | Shared runtime-derived | Not optimized | Computed from the active OHLCV window. |

### 3.9 `RoundNumberKernel` (`round_number`)

| Input | Source | Category | Optimization Profile | Notes |
|-|-|-|-|-|
| `metadata.round_number_mode` | `AssetMetadata` | Rule-derived / asset nature | Fixed | Structural choice for decimal vs pip-style spacing. |
| `round_interval` | Live close + `metadata` (`rule_derived` is static fallback only) | Rule-derived / asset nature | Fixed | Runtime recomputes spacing from the current close and round-number mode so decimal and FX pip buckets stay aligned even when resolver inputs are static. |
| `atr_snap_factor` | `kernel_params` | Per-timeframe low-tune | Low | Controls zone width around psychological levels. |
| `max_levels` | `kernel_params` | Global fixed heuristic | Fixed globally | Output cap for nearest levels. |
| `strength_decay` | `kernel_params` | Per-timeframe low-tune | Low | Distance-based score decay. |
| `base_confidence` | `kernel_params` | Global fixed heuristic | Fixed globally | Baseline weighting for psychological levels. |
| `score_skip_threshold` | `kernel_params` | Global fixed heuristic | Fixed globally | Guards low-signal emissions. |
| `min_bars` | `kernel_params` | Global fixed heuristic | Fixed globally | Data sufficiency guardrail. |
| ATR, current price, timestamps | Runtime data | Shared runtime-derived | Not optimized | Computed from the active series, with deterministic UTC fallback for non-datetime indexes. |

## 4. Optimization Exposure Summary

| Kernel | Primary optimization knobs | Secondary low-tune knobs | Non-optimizable derived/runtime inputs |
|-|-|-|-|
| `pivot_hl` | None by default | `smoothing_period` | `n1`, `n2`, ATR |
| `volume_poc` | `hvn_prominence` | `num_bins`, `hvn_min_distance_atr` | `vp_lookback_hours`, ATR |
| `fair_value_gap` | `gap_min_atr`, `fill_threshold`, `filled_penalty_multiplier` | `validity_lookback_bars` | ATR |
| `order_block` | `displacement_atr`, `imbalance_ratio` | `validity_lookback_bars` | ATR |
| `session_gap` | `gap_min_atr` | `fill_level_fractions` | `metadata.has_session_gaps`, ATR |
| `fractal_channel` | None by default | `channel_lookback`, `boundary_buffer_atr` | `fractal_period`, `fractal_buffer` (currently unused), ATR |
| `regression_band` | `band_width_sigma` | None | ATR, `extra.regression_result` |
| `liquidity_sweep` | `sweep_lookback`, `max_pierce_atr` | None | ATR |
| `round_number` | None by default | `atr_snap_factor`, `strength_decay` | `round_interval`, ATR |

## 5. Placement Policy Overlay

This section compresses the approved placement matrix into the kernel-layer categories already used above.

| Kernel / Input Family | Default Layer | Allowed Override Depth | Optimizer Exposure | Notes |
|-|-|-|-|-|
| `PipelineConfig.enabled_kernels` | `sr.pipeline` | Up to `assets.{symbol}.{tf}` | No | Operational selection surface only. |
| `PipelineConfig.{atr_period,avg_volume_window,merge_threshold_pct_atr}` | `sr.pipeline` | Global only | No | Shared normalization and dedup heuristics. |
| `pivot_hl` rule-derived pivot inputs | `sr.rule_derived.pivot.*` | Global only | No | Formula coefficients, not runtime overrides. |
| `pivot_hl` low-tune scan knobs | `sr.kernels.pivot_hl` | Up to `per_tf.{tf}` | Later | `historical_depth`, `smoothing_period`. |
| `pivot_hl` guardrails and scoring weights | `sr.kernels.pivot_hl` | Global only | No | Includes zone width, weights, and `min_bars`. |
| `volume_poc` metadata-derived horizon | `asset_metadata` to rule-derived | Per-asset metadata only | No | Session structure drives `vp_lookback_hours`. |
| `volume_poc` high-tune strictness | `sr.kernels.volume_poc` | Up to `assets.{symbol}.{tf}` | Initial | `hvn_prominence`. |
| `volume_poc` low-tune histogram knobs | `sr.kernels.volume_poc` | Up to `per_tf.{tf}` | Later | `num_bins`, `value_area_pct`, `hvn_min_distance_atr`. |
| `volume_poc` guardrails and strengths | `sr.kernels.volume_poc` | Global only | No | Scoring conventions and emission caps. |
| `fair_value_gap` high-tune strictness | `sr.kernels.fair_value_gap` | Up to `assets.{symbol}.{tf}` | Initial | `gap_min_atr`, `fill_threshold`, `filled_penalty_multiplier`. |
| `fair_value_gap` low-tune horizon | `sr.kernels.fair_value_gap` | Up to `per_tf.{tf}` | Later | `validity_lookback_bars`. |
| `fair_value_gap` guardrails | `sr.kernels.fair_value_gap` | Global only | No | Includes `max_age_bars`, cap, strength, `min_bars`. |
| `order_block` high-tune strictness | `sr.kernels.order_block` | Up to `assets.{symbol}.{tf}` | Initial | `displacement_atr`, `imbalance_ratio`. |
| `order_block` low-tune horizon | `sr.kernels.order_block` | Up to `per_tf.{tf}` | Later | `validity_lookback_bars`. |
| `order_block` guardrails | `sr.kernels.order_block` | Global only | No | Includes age, strength, and `min_bars`. |
| `session_gap` activation fact | `asset_metadata.profiles.*` | Per-asset metadata only | No | `has_session_gaps` remains structural metadata. |
| `session_gap` high-tune strictness | `sr.kernels.session_gap` | Per-TF approved, deeper conditional | Conditional | `gap_min_atr` only when metadata gate is satisfied. |
| `session_gap` low-tune output shape | `sr.kernels.session_gap` | Up to `per_tf.{tf}` | Later | `fill_level_fractions`. |
| `session_gap` guardrails | `sr.kernels.session_gap` | Global only | No | Search caps, strengths, and `min_bars`. |
| `fractal_channel` rule-derived formula inputs | `sr.rule_derived.fractal.*` | Global only | No | Formula coefficients stay global. |
| `fractal_channel` low-tune display/detection width | `sr.kernels.fractal_channel` | Up to `per_tf.{tf}` | Later | `channel_lookback`, `boundary_buffer_atr`. |
| `fractal_channel` output policy and heuristics | `sr.kernels.fractal_channel` | Global only | No | Includes mode, midline policy, strengths, and `min_bars`. |
| `regression_band` high-tune strictness | `sr.kernels.regression_band` | Up to `assets.{symbol}.{tf}` | Initial | `band_width_sigma`. |
| `regression_band` output policy and guardrails | `sr.kernels.regression_band` | Global only | No | Center emission, strengths, width normalization, `min_bars`. |
| `liquidity_sweep` high-tune strictness | `sr.kernels.liquidity_sweep` | Up to `assets.{symbol}.{tf}` | Initial | `sweep_lookback`, `max_pierce_atr`. |
| `liquidity_sweep` guardrails | `sr.kernels.liquidity_sweep` | Global only | No | Includes age, strength, width normalization, `min_bars`. |
| `round_number` structural mode | `asset_metadata.profiles.*` | Per-asset metadata only | No | `round_number_mode` remains metadata-led. |
| `round_number` low-tune knobs | `sr.kernels.round_number` | Up to `per_tf.{tf}` | Later | `atr_snap_factor`, `strength_decay`. |
| `round_number` guardrails and scoring defaults | `sr.kernels.round_number` | Global only | No | Includes level caps, confidence baseline, skip threshold, `min_bars`. |

## 6. Review Notes

- `fill_threshold` in `FairValueGapKernel` must be protected by regression tests because it changes directional fill semantics but is easy to neutralize accidentally.
- Legacy aliases belong only in `app/sr/config_resolver.py`; kernels should consume canonical names only.
- Global fixed heuristics should remain outside Optuna unless a later design note explicitly promotes them into the search surface.
