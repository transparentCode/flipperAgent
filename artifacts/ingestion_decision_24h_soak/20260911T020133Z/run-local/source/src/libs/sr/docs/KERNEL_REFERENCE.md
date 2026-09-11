# Kernel Reference (S/R v2)

This document is the per-kernel execution reference for the Support/Resistance pipeline.

It focuses on three practical questions for each kernel:

- what market structure the kernel needs in order to be meaningful,
- where the kernel is strong or weak in live use, and
- which runtime knobs actually control its behavior.

For placement policy and optimizer exposure, see `KERNEL_CONFIG_CATEGORIZATION.md` and `OPTIMIZATION_CONFIG_CATEGORIZATION.md`.

## 1. Structural Kernels

### 1.1 Pivot HL (`pivot_hl`)

Detects swing highs and lows using left/right structural windows.

**Structural needs**

- Enough bars to satisfy the rule-derived pivot window: `n1 + n2 + 1` at minimum.
- A price series with meaningful local extrema. In highly compressed chop, the kernel will emit noisy pivots unless the surrounding configuration is conservative.

**Advantages**

- Deterministic and easy to reason about.
- Strong baseline structural layer for higher-timeframe support and resistance.
- Works without volume data.

**Disadvantages**

- Confirmation lag is unavoidable because the right-side window must complete.
- Can over-emit in sideways conditions when the swing structure is shallow.

**Runtime knobs**

- `min_bars`
- `historical_depth`
- `smoothing_period`
- `zone_half_width_atr`
- `vol_factor_weight`
- `dominance_weight`

### 1.2 Anchored VWAP (`anchored_vwap`)

Calculates VWAP from a structural anchor forward to the current bar.

**Structural needs**

- Reliable bar volume. If volume is missing or structurally meaningless, the cost-basis interpretation weakens.
- A meaningful anchor event, currently selected from pivots, volume spikes, or both.
- Enough bars to establish the anchor and accumulate post-anchor volume.

**Advantages**

- Gives an interpretable institutional-style cost basis rather than only geometric price structure.
- Useful in persistent trends where pullbacks often react around anchored fair value.
- Vectorizes efficiently with cumulative price-volume and cumulative volume arrays.

**Disadvantages**

- Anchor quality drives output quality. A weak anchor produces a weak level.
- Overlap risk rises when multiple recent anchors remain active.
- Less useful on assets with low-quality volume.

**Runtime knobs**

- `min_bars`
- `anchor_type`
- `volume_spike_multiplier`

### 1.3 Fractal Channel (`fractal_channel`)

Builds upper and lower channel boundaries from recent price structure.

**Structural needs**

- Enough bars to populate the channel lookback.
- A market regime where envelope-style structure is meaningful; very abrupt discontinuities can reduce signal quality.

**Advantages**

- Good at framing outer structure and breakout boundaries.
- Adapts to volatility changes better than static horizontal levels.
- Can optionally emit a midline for mean-reverting interpretations.

**Disadvantages**

- Channel edges can be too broad to trade directly without confirmation from a micro kernel.
- In sharp trend accelerations, the lagging boundary can remain structurally correct but tactically late.

**Runtime knobs**

- `min_bars`
- `channel_lookback`
- `boundary_buffer_atr`
- `use_rule_derived_buffer`
- `pivot_method`
- `mode`
- `emit_midline`
- `channel_strength`
- `midline_strength_factor`

### 1.4 Regression Band (`regression_band`)

Fits a trend estimate and emits upper/lower deviation bands around it.

**Structural needs**

- Enough bars to fit a stable regression.
- A price series where a local linear approximation is informative over the selected window.

**Advantages**

- Useful for mean-reversion framing and stretch detection.
- Gives an explicit center-versus-extreme interpretation.
- Compact parameter surface.

**Disadvantages**

- Linear fits can misrepresent curved or accelerating trends.
- Can produce premature reversal boundaries during strong directional runs.

**Runtime knobs**

- `min_bars`
- `band_width_sigma`
- `emit_center`
- `band_strength`
- `center_strength`
- `zone_half_width_atr`

## 2. Micro, Order-Flow, and Volume Kernels

### 2.1 Volume Profile POC (`volume_poc`)

Builds a price-volume histogram and emits POC, value area edges, and optional HVNs.

**Structural needs**

- Reliable volume data.
- Enough bars to make the histogram meaningful over the active lookback.
- A binning choice that is fine enough to capture structure without fragmenting the profile.

**Advantages**

- Strong representation of accepted value and liquidity concentration.
- Often provides durable levels that pair well with structural kernels.
- Produces multiple useful surfaces: POC, VAH, VAL, HVNs.

**Disadvantages**

- Sensitive to histogram granularity and profile horizon.
- Less informative on thin or distorted volume series.
- More computationally involved than purely geometric kernels.

**Runtime knobs**

- `min_bars`
- `num_bins`
- `value_area_pct`
- `poc_strength`
- `vah_val_strength`
- `hvn_strength`
- `max_hvn_count`
- `hvn_prominence`
- `zone_half_width_atr`
- `hvn_min_distance_atr`
- `hvn_peak_distance_bins`

### 2.2 TPO Value Area (`tpo_value_area`)

Builds a time-at-price profile and emits time POC with value area high and low.

**Structural needs**

- Enough bars in the rolling window to create a stable time-acceptance profile.
- OHLC ranges that meaningfully reflect where the market spent time.
- A binning resolution that balances stability against detail.

**Advantages**

- Works even when volume quality is weak or absent.
- Captures acceptance and rejection through time rather than traded size.
- Complements `volume_poc` by adding an orthogonal market-profile view.

**Disadvantages**

- Can react more slowly than volume-based profiles in fast directional moves.
- Time acceptance is less informative when bars are mechanically uniform and price migrates without pausing.

**Runtime knobs**

- `min_bars`
- `tpo_window_bars`
- `tpo_value_area_pct`

### 2.3 Order Block (`order_block`)

Finds the last opposing candle before a strong displacement move.

**Structural needs**

- A displacement event large enough relative to ATR.
- Candle structure that preserves the pre-displacement origin cleanly.

**Advantages**

- Useful for sharp entry zones when paired with higher-timeframe structure.
- Encodes a clear narrative around imbalance origin.

**Disadvantages**

- False positives rise quickly if displacement thresholds are too loose.
- Isolated order blocks are fragile without confluence from slower structure.

**Runtime knobs**

- `min_bars`
- `displacement_atr`
- `imbalance_ratio`
- `max_age_bars`
- `validity_lookback_bars`
- `ob_strength`

### 2.4 Fair Value Gap (`fair_value_gap`)

Detects three-bar imbalances that leave an untraded or lightly traded price void.

**Structural needs**

- Clean high/low sequencing over the three-bar pattern.
- Enough ATR context to distinguish meaningful gaps from noise.

**Advantages**

- Good for tracking inefficiency and magnet zones.
- Works well with lifecycle logic because fills and partial fills are structurally meaningful.

**Disadvantages**

- Can emit frequently in noisy markets.
- Needs clear invalidation and fill rules to avoid overstating stale gaps.

**Runtime knobs**

- `min_bars`
- `gap_min_atr`
- `fill_threshold`
- `max_age_bars`
- `validity_lookback_bars`
- `fvg_strength`
- `max_gap_atr_cap`
- `filled_penalty_multiplier`

### 2.5 Session Gap (`session_gap`)

Finds discontinuities between market sessions and emits gap boundaries and internal fill levels.

**Structural needs**

- Asset metadata must indicate meaningful session breaks.
- Timestamp continuity must allow the runtime to distinguish true session boundaries from missing data.

**Advantages**

- Important for equities, futures, and other non-continuous markets.
- Encodes a very interpretable market structure: open imbalance versus prior close.

**Disadvantages**

- Not useful for continuous markets where session gaps are absent or artificial.
- Sensitive to timestamp hygiene and upstream data conditioning.

**Runtime knobs**

- `min_bars`
- `gap_min_atr`
- `fill_level_fractions`
- `max_age_bars`
- `gap_origin_strength`
- `gap_dest_strength`
- `fill_level_strength`
- `max_gap_atr_cap`
- `session_boundary_multiplier`
- `session_boundary_baseline_bars`

### 2.6 Liquidity Sweep (`liquidity_sweep`)

Detects stop-hunt style wicks that pierce local structure and reject.

**Structural needs**

- A local reference boundary to sweep.
- Wick behavior that clearly distinguishes a rejection from a true breakout continuation.

**Advantages**

- Useful as a tactical reversal or trap signal.
- Adds a rejection-aware view that pure structure kernels do not provide.

**Disadvantages**

- Hard to separate false breaks from real breaks in isolation.
- Very sensitive to strictness settings in volatile markets.

**Runtime knobs**

- `min_bars`
- `sweep_lookback`
- `max_pierce_atr`
- `max_age_bars`
- `sweep_strength`
- `zone_half_width_atr`

## 3. Psychological Kernels

### 3.1 Round Number (`round_number`)

Generates decimal or pip-based psychological levels around the live price.

**Structural needs**

- Asset metadata that correctly declares decimal versus pip interpretation.
- A snap distance that is sensible relative to current ATR and price scale.

**Advantages**

- Adds widely observed psychological structure with almost no computational cost.
- Often improves confluence when another kernel already marks the same area.

**Disadvantages**

- Weak as a standalone signal source.
- Can overproduce nearby levels if spacing or snap logic is too permissive.

**Runtime knobs**

- `min_bars`
- `atr_snap_factor`
- `max_levels`
- `strength_decay`
- `base_confidence`
- `score_skip_threshold`
- `pip_intervals`
- `pip_thresholds`