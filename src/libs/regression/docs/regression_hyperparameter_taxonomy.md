# Regression Module Hyperparameter Taxonomy

This document outlines all hyperparameters and configuration knobs across the `app/regression` module. It categorizes them into structural global parameters, hierarchical overrides, plugin-specific tuning knobs, and dynamic data-derived boundaries.

---

## 1. Global Baseline Parameters (Tier 1)
These parameters form the foundation of the pipeline. They apply universally across all assets and timeframes unless explicitly overridden downstream.

| Parameter | Default | Type | Description |
|-----------|---------|------|-------------|
| `default_window_size` | `100` | `int` | The standard rolling window size for regression fits. |
| `min_window` | `15` | `int` | Hard floor for window size (prevents degenerate fits). |
| `max_window` | `300` | `int` | Hard ceiling for window size (limits computational cost). |
| `atr_period` | `14` | `int` | Lookback period for ATR normalization. |
| `trend_atr_fraction` | `0.10` | `float` | Threshold for strong trend classification. |
| `spread_atr_fraction` | `0.15` | `float` | Threshold for wide spreads/high volatility. |
| `momentum_atr_fraction` | `0.10` | `float` | Threshold for momentum breakout classification. |
| `neutral_slope_atr_fraction` | `0.04` | `float` | Used to calculate the `neutral_threshold` boundary. |
| `band_multiplier` | `2.0` | `float` | Sigma/MAD multiplier for uncertainty bands. |

---

## 2. Hierarchical Overrides (Tiers 2, 3, 4)
The regression module supports 4 tiers of resolution (`Global → Timeframe → AssetClass → Asset/AssetTimeframe`). Any Global Parameter can be overridden at a more specific tier. 

### Per-Timeframe Overrides (Tier 2)
Timeframes often require fundamentally different mathematical responsiveness.
- **`slope_acceleration_alpha`**: A timeframe-specific parameter used to smooth or accelerate slope responses (typically tuned per TF, e.g., 0.1 for `1h`, 0.2 for `15m`).
- *Overrides*: `window_size`, `band_multiplier`, and all `atr_fractions`.

### Per-Asset Class Overrides (Tier 3)
Defines structural data handling rules based on the market type.
- **`volume_profile`**: Defines how volume is treated (`CONTINUOUS` for Crypto, `SESSION` for Equities, `PROXY` for FX).
- **`session_gap_handling`**: `bool` (True for Equities). Triggers the `session_aware` feature extractor to nullify post-gap bars.
- **`low_liquidity_window_handling`**: `bool` (True for FX/illiquid assets).

### Per-Asset Overrides (Tier 4)
Defines overrides for a specific symbol (e.g., `BTCUSDT`).
- **`mtf_enabled`**: `bool`. Determines if this specific asset should be routed through the `UniverseOrchestrator`'s top-down cascade.
- **`mtf_timeframes`**: `List[str]`. The explicit timeframes to include in the cascade (e.g., `['4h', '1h', '30m']`).
- *Overrides*: All ATR fractions and window sizes can now be defined globally for the asset (thanks to the Cfg-1 fix) or specifically for `assets.BTCUSDT.timeframes.1h`.

---

## 3. Plugin-Specific Tuning Knobs
These are hyperparameters passed directly into the `params` dictionary of a `PluginConfig` in the YAML, consumed during plugin instantiation.

### Methods (`methods/`)
- **`weight`** (`float`, default `1.0`): The base trust weight assigned to the method before statistical confidence scaling.
- **`decay_factor`** (`float`, WLS specific): The exponential decay factor applied to older bars in Weighted Least Squares (e.g., `0.94`).
- **`volume_weighting_enabled`** (`bool`, WLS specific): Toggles whether volume is factored into the WLS diagonal matrix.

### Uncertainty (`uncertainty/`)
- **`mad_scale_factor`** (`float`, default `1.4826`): The constant used to scale the Median Absolute Deviation to a standard normal distribution (Gaussian equivalence).

### Ensemble (`ensemble/`)
- **`cascade_penalty`** (`float`): The penalty factor applied to a method's weight when its predicted direction conflicts with the Higher Timeframe (MTF) cascade consensus.
- **`cascade_boost_multiplier`** (`float`, default `0.5`): The bonus multiplier applied to a method's weight when it aligns with the MTF cascade consensus.
- **`min_confidence`** (`float`, default `0.0`): The minimum statistical confidence required for a method's vote to be counted.
- **`max_method_weight`** (`float`, default `0.80`): The cap on any single method's influence, forcing the ensemble to remain diversified.

---

## 4. Orchestration & MTF Hyperparameters
These dictate how the `UniverseOrchestrator` aggregates multiple assets and timeframes.
- **`tf_weights`** (`Dict[str, float]`): The voting power of each timeframe in the MTF alignment score (e.g., `{'4h': 0.5, '1h': 0.3, '30m': 0.2}`).
- **`regime_context_enabled`** (`bool`): Master switch for regime-awareness.
- **`regime_window_override`** (`bool`): Allows the `RegimeSnapshot` to dynamically hijack the `window_size`.
- **`regime_window_defaults`**: Default window lengths mapped to specific regimes:
  - `CLEAN_TREND`: 150
  - `VOLATILE_TREND`: 60
  - `CHOPPY`: 30
  - `QUIET_MR`: 100

---

## 5. Dynamic / OHLCV-Derived Parameters (Runtime)
These are not static config values, but rather boundaries dynamically calculated at runtime based on the raw OHLCV data.

- **`atr_norm`**: `ATR(14) / Close`. Calculated dynamically per tick. It normalizes volatility across assets ranging from $0.0001 to $100,000.
- **`neutral_threshold`**: `neutral_slope_atr_fraction * atr_norm`. A dynamic boundary used to classify if a regression slope is truly trending or just drifting sideways (NEUTRAL).
- **`effective_window`**: The actual `N` bars used for the regression. It starts at `default_window_size`, gets overridden by `regime.suggested_window` (if applicable), and is finally clamped securely between `min_window` and `max_window`.
- **`band_width`**: Computed dynamically via `mad_scale_factor * MAD(residuals) * band_multiplier`. Expands and contracts based purely on recent model fit errors.
- **`alignment_score`**: An MTF consensus metric calculated dynamically as `[-1.0, 1.0]` based on the ratio of BULLISH vs BEARISH timeframes and their respective `tf_weights`.
