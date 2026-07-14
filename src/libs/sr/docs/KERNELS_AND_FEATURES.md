# Kernels and Features Architecture (S/R v2)

This document details the internal mechanics of the Support/Resistance (S/R) v2 module's detection layer (Kernels) and contextualization layer (Feature Builder). 

For per-kernel parameter categorization and optimization visibility, see `app/sr/docs/KERNEL_CONFIG_CATEGORIZATION.md` and `app/sr/docs/OPTIMIZATION_CONFIG_CATEGORIZATION.md`. For structural needs, tradeoffs, and runtime knob summaries, see `app/sr/docs/KERNEL_REFERENCE.md`.

## 1. The Kernel Layer (Detection)

Kernels are stateless, pure functions responsible for detecting specific market structures (e.g., Fair Value Gaps, Order Blocks, Volume Points of Control). 

### 1.1 Hyperparameter Classification (The 4-Tier Cascade)

To prevent hyperparameter bloat during cross-asset optimization, all kernel parameters are strictly classified into a 4-tier configuration cascade:

1. **Rule-Derived / Asset Nature**: Parameters auto-calculated based on structural asset metadata (volatility, trading hours, tick size).
   - *Examples*: `n1`/`n2` (derived from volatility profile), `vp_lookback_hours` (derived from session hours).
   - *Optimization Profile*: **Fixed**. These automatically adapt; never run them through Optuna.
2. **Global Clipping & Default Heuristics**: Universal sanity limits and base scoring weights that prevent memory bloat and standardize pipeline execution.
   - *Examples*: `max_age_bars = 200`, `max_gap_atr_cap = 2.0`, `zone_half_width_atr = 0.1`, `base_confidence = 0.5`.
   - *Optimization Profile*: **Fixed globally**. These are set once to ensure sensible memory bounding and relative kernel weighting.
3. **Per-Timeframe Tuning**: Sensitivities that change based on chart resolution.
   - *Optimization Profile*: **Low**.
4. **Per-Asset / Per-TF Tuning (The Tuning Layer)**: Highly sensitive thresholds that directly dictate the strictness of pattern detection. 
   - *Examples*: `gap_min_atr` (FVG), `displacement_atr` (Order Blocks), `band_width_sigma` (Regression Bands).
   - *Optimization Profile*: **High**. These are the kernel-layer candidates that may be promoted into the `UniverseSROptimizer` surface, but the live optimizer uses only the approved subset documented in `app/sr/docs/OPTIMIZATION_CONFIG_CATEGORIZATION.md`.

### 1.2 Available Kernels

| Kernel Name | Description | Key Tuning Params |
| :--- | :--- | :--- |
| `PivotHighLowKernel` | Standard swing points based on left/right lookback. | `historical_depth`, `smoothing_period`, `vol_factor_weight`, `dominance_weight`, `min_bars` |
| `VolumePOCKernel` | High Volume Nodes and Value Area limits across hour-derived session, weekly, and monthly lookbacks. | `value_area_pct`, `num_bins`, `max_hvn_count`, `hvn_prominence`, `min_bars` |
| `AnchoredVWAPKernel` | AVWAP levels anchored to recent pivots, volume spikes, or both. | `anchor_type`, `volume_spike_multiplier`, `min_bars` |
| `TPOValueAreaKernel` | Time-at-price POC and value area boundaries across a rolling window. | `tpo_window_bars`, `tpo_value_area_pct`, `min_bars` |
| `FairValueGapKernel` | Multi-bar imbalances with lookback chop-filtering. | `gap_min_atr`, `validity_lookback_bars`, `max_gap_atr_cap`, `filled_penalty_multiplier`, `min_bars` |
| `OrderBlockKernel` | High-displacement engulfing pivots. | `displacement_atr`, `validity_lookback_bars` |
| `RegressionBandKernel` | Regression boundaries from inline asset-scoped bands, with OLS as a last-resort fallback. | `band_width_sigma` |
| `FractalChannelKernel` | Upper/lower trend boundaries. | `boundary_buffer_atr`, `midline_strength_factor`, `min_bars` |
| `SessionGapKernel` | Weekend/overnight market gaps gated by timestamp session breaks, assuming upstream-adjusted and prefiltered bars. | `gap_min_atr`, `max_gap_atr_cap`, `min_bars` |
| `LiquiditySweepKernel`| Optional stop-hunt rejections past local structures. | `max_pierce_atr`, `sweep_lookback`, `min_bars` |
| `RoundNumberKernel` | Psychological decimal/pip levels recomputed from the live close. | `atr_snap_factor`, `max_levels`, `strength_decay`, `base_confidence`, `score_skip_threshold`, `min_bars` |

### 1.3 Score Semantics

Each kernel emits a `raw_score` ∈ [0, 1] attached to every `CandidateLevel`. Downstream ensemble weighting multiplies this by a per-kernel weight, so the scores need only be internally consistent — not cross-comparable in absolute magnitude.

| Kernel | Formula | Typical Range | Notes |
|-|-|-|-|
| `PivotHighLowKernel` | `depth_score * vol_score * dominance_score` | 0.1 – 0.9 | Multiplicative; deeper pivots with volume confirmation score highest |
| `VolumePOCKernel` | `rel_volume` (volume fraction of total) | 0.01 – 0.6 | Naturally bounded by histogram normalization |
| `AnchoredVWAPKernel` | `min(anchor_volume_ratio, 1.0)` with spike-anchor normalization | 0.1 – 1.0 | Volume-spike anchors are normalized by `volume_spike_multiplier`; pivot anchors use the raw anchor-volume ratio |
| `TPOValueAreaKernel` | `1.0` for POC, `acceptance_bin / max_acceptance` for VAH/VAL | 0.2 – 1.0 | POC is emitted as the strongest acceptance level; VAH/VAL inherit relative time acceptance |
| `FairValueGapKernel` | `base - filled_penalty` | 0.3 – 1.0 | Starts at `base_confidence`, penalized if partially filled |
| `OrderBlockKernel` | `displacement_score` | 0.4 – 1.0 | Proportional to displacement ATR magnitude |
| `RegressionBandKernel` | fixed `base_confidence` | 0.5 | Flat; differentiation happens at the feature layer |
| `FractalChannelKernel` | `strength` or `strength * midline_factor` | 0.2 – 1.0 | `midline_strength_factor` < 1 for the midline candidate |
| `SessionGapKernel` | `min(gap_atr / cap, 1.0)` | 0.1 – 1.0 | Wider gaps in ATR terms score higher, capped at `max_gap_atr_cap` |
| `LiquiditySweepKernel` | `sweep_strength * (1 - pierce_ratio)` | 0.05 – 0.8 | `pierce_ratio = pierce_dist / (max_pierce_atr * atr)`. Shallow wick → higher score (stronger rejection signal) |
| `RoundNumberKernel` | `base_confidence * decay^rank` | 0.01 – 0.5 | Geometric decay away from the live close; `score_skip_threshold` prunes negligible levels |

**Design note — `VolumePOCKernel` zone width:** The default `zone_half_width_atr = 0.15` (vs the global default of `0.1`) is intentional. Volume profile HVNs represent broad zones of acceptance, not point levels, so a slightly wider zone better captures the HVN's structural meaning.

---

## 2. Feature Builder (Contextualization)

Once candidates are detected and spatially deduplicated, the `LevelFeatureBuilder` transforms them into a unified `LevelFeatureVector` containing historical touches, volume trends, and regime alignment.

The feature builder now follows the same parameter policy as the broader SR runtime:
1.  **Semantic thresholds stay fixed or explicitly configurable**. Example: `touch_count` uses `sr.features.touch_proximity_atr` with a stable default of `0.5 × ATR`.
2.  **Slow structural horizons derive from asset metadata at runtime**. Historical scan lengths use `AssetMetadata.session_lookback_hours` plus timeframe-to-bars conversion rather than fixed raw bar counts.
3.  **Fast market-state values stay live**. ATR and `candidate.atr_at_detection` remain runtime quantities; they are not scheduler snapshots.
4.  **Scheduler-fed asset snapshots are upstream inputs, not replacements for runtime ATR**. If a weekly scheduler later publishes slow asset characteristics, they should enrich metadata or slow priors, not replace live volatility normalization.

### 2.1 Look-Ahead Safety (`t` Indexing Rule)

The most critical requirement of the feature builder is **zero look-ahead bias** during historical scanning. 

To guarantee this, all feature extraction loops strictly terminate at the candidate's `formation_idx` (the bar at which the structure became objectively valid). 
*   **Rule**: Features evaluate *initial formation conviction* only.
*   **Post-Formation Tracking**: Touches or breaks that occur *after* formation are ignored by the feature builder. They are instead routed directly to the stateful `LifecycleManager`, which manages `Active -> Tested -> Broken` transitions.

### 2.2 Performance: Windowed Approximations and Asset-Nature Horizons

Iterating over tens of thousands of bars for every candidate creates severe O(N^2) bottlenecks during universe-wide sweeps. To maintain high throughput, expensive structural features use windowed approximations relative to the formation bar (`end_idx`):
*   `volume_trend_at_level`: Scans a **runtime-derived weekly horizon** based on `AssetMetadata.session_lookback_hours[1]`, converted to bars using the active timeframe. An explicit override exists at `sr.features.volume_trend_lookback_hours`. If metadata is unavailable, the legacy fallback remains **200 bars**.
*   `false_breakout_count`: Scans a **runtime-derived monthly horizon** based on `AssetMetadata.session_lookback_hours[2]`, converted to bars using the active timeframe. An explicit override exists at `sr.features.false_breakout_lookback_hours`. If metadata is unavailable, the legacy fallback remains **500 bars**.
*   `touch_count`: Uses the configurable semantic radius `sr.features.touch_proximity_atr` (default `0.5 × ATR`) rather than a hidden constant.

This split is intentional: scan horizons are asset/timeframe-structural and should adapt to market hours, while ATR-sensitive touch semantics should remain interpretable and stable.

### 2.3 Anti-Overfitting (Phase 3 Preparation)

As we integrate the `RegimeConditionalEnsemble` (Random Forest / XGBoost) in Phase 3, we must prune collinear and low-signal features to prevent overfitting.

The required preprocessing strategy is:
1.  **Variance Inflation Factor (VIF)**: Any features with VIF > 5.0 will be dropped or combined via PCA. (e.g., `atr_distance_from_price` and `poc_distance_atr` may be highly collinear if price is near POC).
2.  **Mutual Information (MI)**: Feature importance scoring against the target variable (forward return post-touch). Features with near-zero MI across multiple regimes will be excluded from the ensemble inputs.
3.  **Feature Normalization**: All bounded features (`rejection_ratio`, `value_area_overlap`) remain as-is. Unbounded count features (`touch_count`, `mtf_confluence_count`) will be normalized via a robust scaler or log1p transformation before feeding the ensemble.
