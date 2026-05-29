# Regression Module Current Truth

This document is the live-code walkthrough for the current regression module.
It is intentionally narrower than older design notes because several previously
documented analysis-era surfaces no longer exist in the runtime.

## What The Module Is

The regression module is a confidence-calibrated channel estimation engine.
Its job is to transform OHLCV into structured market-state outputs:

- slope and direction
- channel center and uncertainty bands
- z-score distance from the channel
- confidence as a quality and sizing signal
- multi-timeframe alignment and conflict metadata

It is not a standalone execution engine. The core pipeline emits a structured
RegressionResult and leaves trade construction to downstream consumers.

## Public Surface

The intended entrypoints are:

- `app.regression.api.compute_single_tf`
- `app.regression.api.compute_single_tf_series`
- `app.regression.api.compute_mtf`
- `app.regression.api.compute_universe`
- `app.regression.api.optimize_regression`

`app.regression.compat` still exists, but it is now only a convenience
re-export layer over v2-native code. It is not a dependency bridge to an older
runtime.

## Runtime Walkthrough

### 1. Config Resolution

`ConfigResolver` resolves a flat `ResolvedPipelineConfig` from four tiers:

1. global defaults
2. timeframe overrides
3. asset-class overrides
4. asset and asset-timeframe overrides

The live default YAML emphasizes a small, robust stack rather than a large
plugin catalog.

### 2. Single-Timeframe Pipeline

The runtime path is:

`Features -> Methods -> Uncertainty -> Ensemble`

Current active components:

- Features: `log_price`, `volume_weighted`, with `session_aware` added by asset class where needed
- Methods: `theil_sen` (with localized Temporal and Volatility anchoring for deterministic subsets), `vwr`
- Uncertainty: `percentile_bands`
- Ensemble: `simple_weighted` or `confidence_weighted`

The output is a `RegressionResult` with arrays for bands and mid-line plus
scalar state such as slope, direction, confidence, `atr_norm`, and `z_score`.
The core result still carries `signals=[]`; strategy payloads are built outside
the module.

### 3. Confidence Is The Center

Confidence is no longer just a visual score. It is the module's intended
ranking, filtering, and sizing variable.

- Cross-sectional consumers can use confidence and slope as state features, but current three-asset tests show no standalone ranking alpha.
- Strategy logic can use confidence as a gating and sizing variable.
- Optimization explicitly rewards confidence that maps to realized move size.

That makes the module closer to a market-state estimator and risk filter than
to a raw forecasting or alpha engine.

## Universe Handling

`UniverseOrchestrator` is the batch runtime for a universe of assets.

For each asset it:

1. resolves asset metadata and per-timeframe config
2. caches pipeline instances by `(asset, timeframe)`
3. optionally injects regime context
4. runs either a single-timeframe path or a multi-timeframe cascade
5. returns both per-asset dominant results and optional MTF detail

`compute_universe` returns:

- `results`: dominant single result per asset
- `mtf_results`: full MTF outputs for assets that ran a cascade
- processing statistics such as degraded and failed counts

This matters because the regression module is built to scale across a ranked or
filtered universe, not only for one-off single-asset analysis.

## MTF Handling

MTF is top-down.

The orchestrator runs higher timeframes first, then passes a `CascadeContext`
into the next lower timeframe. The cascade context includes:

- source timeframe
- slope
- direction
- confidence
- band width
- dominant method

The resulting `MTFOutput` summarizes:

- per-timeframe results
- alignment score
- direction consensus
- consensus strength
- dominant timeframe
- weighted slope and weighted confidence
- conflict pairs when timeframes disagree

The important practical point is that MTF here is not a separate model family.
It is an orchestration layer that filters and stabilizes single-timeframe state.

## Consumer Fit

### Cross-Sectional

The cross-sectional orchestrator consumes snapshot fields such as:

- `z_score`
- `direction`
- `confidence`
- `slope`
- `atr_norm`

That is a natural fit for ranking and selection workflows:

- select strongest aligned trends
- filter weak or noisy names
- find stretched names for mean-reversion baskets

### Regime-Aware Strategy

The regime regression strategy uses the rolling series API and combines:

- regime label and changepoint gating
- regression direction and z-score
- ensemble confidence
- optional 4h alignment

This is the right division of labor. The regression module estimates state,
while the strategy decides when that state is tradable.

### Backtest Enrichment

The backtest bridge can precompute regression state once and append it to the
dataframe as plain columns. That makes the module easy to plug into other
strategy experiments without coupling those strategies to pipeline internals.

## Alpha Extraction View

The module is often described as supporting four alpha paths. Direct testing on
BTC, ETH, and SOL says otherwise. The hard truth is that three paths are dead
and the surviving path is useful as risk budgeting, not as alpha generation.

| Path | Verdict | Key evidence |
|-|-|-|
| Confidence-weighted trend following | DEAD | Negative Sharpe at all tested horizons; confidence weighting makes it worse |
| Channel-distance mean reversion | BTC only, fragile | BTC positive in small sample, ETH and SOL dead, and z-score extremes are rare |
| Cross-sectional ranking | DEAD | 87–91% direction agreement across BTC, ETH, SOL kills spread construction |
| Confidence as risk budget | Valid, not alpha | Reduces drawdowns materially but does not create positive returns |

Quant-lens audit (2026-04-16) tested each path empirically on BTC, ETH, SOL ×
1h over the 2023–2026 sample using the optimized BTCUSDT params (window=97,
band_multiplier=3.49).

### 1. Confidence-Weighted Trend Following — DEAD

Empirical test: `PnL = direction_sign × fwd_return` at horizons 4, 12, 24 bars.

| Asset | h=4 Sharpe | h=12 Sharpe | h=24 Sharpe | h=12 hit |
|-|-|-|-|-|
| BTCUSDT | -0.39 | -2.38 | -5.93 | 0.456 |
| ETHUSDT | -0.50 | -0.74 | -3.31 | 0.490 |
| SOLUSDT | -0.86 | -1.79 | -3.59 | 0.469 |

Confidence weighting makes it **worse**: top-quintile Sharpes are -8 to -24.
This path has no alpha. Using confidence as a position scaler on regression
direction is actively destructive on 1h.

### 2. Channel-Distance Mean Reversion — BTC ONLY, FRAGILE

Test: when `|z_score| >= 1.0`, bet on reversion (short when z>1, long when z<-1).

| Asset | h=12 n | h=12 Sharpe | h=12 hit | conf-gated Sharpe |
|-|-|-|-|-|
| BTCUSDT | 90 | +24.89 | 0.644 | +46.56 |
| ETHUSDT | 444 | -8.92 | 0.484 | -14.66 |
| SOLUSDT | 410 | -3.33 | 0.485 | -9.10 |

BTC MR looks strong, but the sample is tiny (n=90). With wider bands
(3.49×), `|z| >= 1.0` is rare — only 3.7% of bars. Confidence gating
improves BTC MR dramatically (Sharpe 24 → 47) but the small sample
makes this unreliable for production sizing. ETH and SOL MR is dead.

### 3. Cross-Sectional Ranking — DEAD

Test: rank assets by `confidence × direction_sign` at each bar. Long the
top-ranked, short the bottom-ranked.

| Horizon | Sharpe | Hit rate | Avg return |
|-|-|-|-|
| h=4 | -3.26 | 0.461 | -3.25 bps |
| h=12 | -7.69 | 0.423 | -12.91 bps |
| h=24 | -12.23 | 0.420 | -27.67 bps |

This fails because the 3-asset crypto universe is too correlated:
- BTC–ETH direction agreement: 90.8%
- BTC–SOL direction agreement: 87.5%
- ETH–SOL direction agreement: 89.2%

Cross-sectional ranking requires meaningful dispersion. With 87–91%
direction agreement, the long and short legs are nearly identical assets.
Confidence-only ranking (ignoring direction) is also negative but flatter.

### 4. Confidence As Risk Budget — VALID, NOT ALPHA

Test: compare buy-and-hold vs confidence-sized long exposure.

| Asset | h=24 BaH Sharpe | conf-sized Sharpe | Drawdown reduction |
|-|-|-|-|
| BTCUSDT | -8.00 | -1.83 | 77% less negative |
| ETHUSDT | -8.11 | -5.82 | 28% less negative |
| SOLUSDT | -9.16 | -3.07 | 66% less negative |

Confidence sizing is not an alpha source — it does not generate positive
returns. But it is a valid risk management tool that materially reduces
exposure during low-quality periods. BTC and SOL benefit most from
confidence-based risk budgeting.

### Cross-Asset Confidence Correlation

Spearman rank correlation of confidence scores at common timestamps:

| | BTC | ETH | SOL |
|-|-|-|-|
| BTC | 1.000 | 0.655 | 0.687 |
| ETH | 0.655 | 1.000 | 0.582 |
| SOL | 0.687 | 0.582 | 1.000 |

Confidence is moderately correlated across assets (0.58–0.69), meaning the
module's state estimation is partly driven by shared market factors rather
than pure asset-specific structure.

### Bottom Line On Alpha Extraction

1. **Paths 1 and 3 are empirically dead.** Confidence-weighted trend following
   and cross-sectional ranking have negative Sharpe at all horizons.
2. **Path 2 (MR) shows BTC-specific edge in tiny sample.** The wider bands
   from optimization make extreme z-scores rare, and the edge may not survive
   transaction costs or larger sample.
3. **Path 4 (risk budget) is the module's real value.** Confidence does not
   generate alpha, but it reduces drawdowns by 28–77% by scaling exposure
   to fit quality.
4. **The 3-asset crypto universe is too correlated for cross-sectional alpha.**
   Direction agreement of 87–91% kills any long-short spread construction.
5. **The regression module is primarily a state estimator and risk filter.**
   Confidence is useful for sizing, gating, and trade suppression.
   Standalone directional alpha from regression outputs appears weak or
   absent in current tests. Any future alpha role likely requires interaction
   terms with orthogonal signals, such as derivatives flow, cross-sectional
   dispersion, or regime-conditioned execution logic.

## Optimizer Truth

The optimizer is also confidence-centric.

Its composite score blends:

- direction accuracy
- band calibration
- residual quality gate
- confidence monotonicity constraint
- confidence-weighted strategy utility

The live confidence monotonicity check is not based on signed forward returns.
It checks whether higher confidence ranks with larger absolute forward moves.
That means the optimizer is training confidence to be a move-quality signal,
not just a directional probability.

The old conviction names still appear only as alias parsing for historical
result files.

## What Is Gone Or Residual

These older ideas are not active runtime surfaces anymore:

- dedicated analysis stage inside `RegressionPipeline`
- dedicated export stage in the runtime path
- conviction-first downstream contract
- larger optional plugin narrative around dead code paths

There are still residual directories, historical result files, and stale docs
that mention those concepts. When they disagree with the source, trust the
source.

## Empirical Audit

The findings below were generated from the live code with the reproducible
script at `app/regression/scripts/audit_current_truth.py`.

Audit setup:

- assets: BTCUSDT, ETHUSDT, SOLUSDT
- source data: local 1h CSV files under `app/trendlines/optimization/results/`
- sample window: last 2500 1h bars per asset
- 4h data: derived by resampling the same 1h input
- evaluation horizon: 12 bars forward

For series analysis, results were aligned positionally from `window_size`
because the rolling series API is fundamentally order-based in the current
runtime.

### Confidence Monotonicity

Aggregated across all audited assets:

- 1h: Spearman rho between confidence and absolute 12-bar move was `0.1519`
- 1h: top confidence quintile had `1.4359x` the average absolute move of the bottom quintile
- 4h: Spearman rho was `0.1636`
- 4h: top confidence quintile had `1.3621x` the average absolute move of the bottom quintile

Interpretation:

- confidence is behaving like a move-magnitude estimator on both 1h and 4h
- that supports the current optimizer design, which constrains confidence to rank with absolute forward move size
- this does not, by itself, translate into a deployable alpha stream

### Directional Quality

Directional quality is weaker than move-magnitude quality on 1h:

- 1h overall directional hit rate: `0.4716`
- 1h top-confidence hit rate: `0.4184`
- 4h overall directional hit rate: `0.4955`
- 4h top-confidence hit rate: `0.6179`

Interpretation:

- on 1h, high confidence does not look like a clean standalone directional edge
- on 4h, high confidence is materially more useful as a directional filter
- even where the filter statistics improve, that is not the same thing as positive standalone alpha
- the module is stronger as a state-quality and move-size engine than as a direct continuation engine

### Per-Asset Read

1h monotonicity was strongest on ETH and SOL:

- ETH 1h rho: `0.1681`, top/bottom move ratio: `1.4782x`
- SOL 1h rho: `0.1785`, top/bottom move ratio: `1.4677x`
- BTC 1h rho: `0.1040`, top/bottom move ratio: `1.2628x`

4h looked mixed by asset:

- ETH 4h rho: `0.2090`, top/bottom move ratio: `1.5362x`, top hit rate: `0.6279`
- SOL 4h rho: `0.1875`, top/bottom move ratio: `1.6076x`, top hit rate: `0.5632`
- BTC 4h rho: `0.0986`, top/bottom move ratio: `0.8372x`, top hit rate: `0.6164`

Interpretation:

- ETH and SOL currently look like the cleaner confidence surfaces
- BTC 4h confidence appears more useful for direction filtering than for pure move-magnitude ranking under this sample and horizon

### Regime Fit

On 1h, regime-family slices show that TREND and CHOPPY regimes carry stronger
confidence-to-move monotonicity than MR:

- TREND: rho `0.1837`, top/bottom move ratio `1.7688x`
- CHOPPY: rho `0.1799`, top/bottom move ratio `1.4990x`
- MR: rho `0.1140`, top/bottom move ratio `1.2391x`

But raw direction-following in TREND was poor under the simple 12-bar test:

- TREND top-confidence threshold: `52.4`
- TREND top-confidence hit rate: `0.3430`
- TREND top-confidence mean signed log return: `-0.00810`

Interpretation:

- high-confidence trend states are associated with larger moves, but not reliably with immediate continuation over this horizon
- that argues for using confidence as an expansion and trade-quality filter, not as a naive trend-following trigger by itself

### Mean-Reversion Fit

The simple MR test used:

- regime family = MR
- `|z_score| >= 1.0`
- forward return signed opposite to z-score

The broad regime-family MR slice was weak overall:

- confidence threshold: `37.14`
- reversion hit rate: `0.3745`
- mean reversion log return: `-0.00906`

Interpretation:

- the broad MR slice does not support a portable standalone alpha claim
- the stricter path test in the Alpha Extraction View shows only a BTC-specific edge in a small sample, which is too fragile to treat as production alpha
- z-score remains useful as a distance feature, but it likely needs additional structure such as regime transition logic, liquidity filters, or execution timing rules

### Universe And MTF Snapshot

A live `compute_universe` run over BTC, ETH, and SOL completed with no degraded
or failed assets.

Current snapshot:

- BTCUSDT: bearish, confidence `0.5735`, z-score `0.9578`
- ETHUSDT: bearish, confidence `0.1652`, z-score `0.3778`
- SOLUSDT: bearish, confidence `0.0884`, z-score `0.4171`

MTF state:

- BTCUSDT: full bearish alignment, alignment score `1.0`, dominant timeframe `4h`, weighted confidence `0.3584`
- ETHUSDT: full bearish alignment, alignment score `1.0`, dominant timeframe `4h`, weighted confidence `0.1585`

Interpretation:

- the universe path is operational for mixed assets and mixed MTF settings
- MTF currently looks best as a conflict filter and confidence stabilizer, not as a separate alpha source

### Bottom Line

The live audit supports five conclusions:

1. Confidence is real signal, but mostly as move-size ranking rather than as a directional edge.
2. Confidence-weighted trend following is dead in current tests: negative Sharpe at all tested horizons and worse after confidence weighting.
3. Channel-distance mean reversion is not portable alpha: only BTC shows a positive read, and that edge is rare-event and fragile.
4. Cross-sectional ranking is dead in the current three-asset crypto universe because direction agreement is too high for meaningful spread construction.
5. The module's real value is as a **state estimator and risk filter**: confidence is useful for gating, suppression, and exposure scaling, not for generating directional bets.

## Confidence Semantics

Confidence is **not** a calibrated forward probability. It is an R²-derived in-sample fit quality metric.

### How Confidence Is Computed

- **Theil-Sen**: `1 - MAD(residuals) / MAD(y)` — measures how well the robust linear fit explains the price window. Higher values mean tighter residuals relative to price variation.
- **VWR (Volume-Weighted Regression)**: `R² × (1 - 1/√n)` — standard R-squared with a finite-sample penalty. Converges to R² as window size grows.

The ensemble confidence is the weighted average of per-method confidences.

### Empirical Identity

From the audit (`audit_current_truth.py`) aggregated across BTC, ETH, SOL:

| Metric | 1h | 4h |
|-|-|-|
| Spearman rho (confidence vs \|fwd move\|) | 0.1519 | 0.1636 |
| Top/bottom quintile move ratio | 1.4359× | 1.3621× |
| Overall directional hit rate | 0.4716 | 0.4955 |
| Top-confidence directional hit rate | 0.4184 | 0.6179 |

### Implications

1. **Confidence ranks with move magnitude, not direction.** High confidence means "the fit is tight and a large move is more likely", not "up is more likely than down".
2. **1h directional hit rate is sub-50%.** Confidence should not be used as a standalone directional trigger on 1h.
3. **4h is materially better for direction as a filter statistic.** That may help gating logic, but it is not proof of standalone alpha.
4. **Downstream consumers should treat confidence as a sizing/quality signal**, not a probability. Position sizing as `confidence × direction_sign` is exposure control, not alpha proof.
5. **Calibrating confidence into probability space** (e.g., via isotonic regression or Platt scaling) is a potential future improvement but would change the confidence contract that downstream consumers already depend on.

### IC Decay Profile

Generated by `app/regression/scripts/ic_decay.py` on 2026-04-16. Shows how confidence-to-|forward move| Spearman rho varies across forward horizons.

**1h IC Decay:**

| Asset | h=1 | h=4 | h=12 | h=24 | h=48 |
|-|-|-|-|-|-|
| BTCUSDT | 0.1083 | 0.1189 | 0.1040 | **0.1567** | 0.0187 |
| ETHUSDT | 0.1105 | 0.1621 | **0.1681** | 0.1119 | 0.0415 |
| SOLUSDT | 0.1129 | 0.1740 | **0.1785** | 0.1413 | -0.0424 |

**4h IC Decay:**

| Asset | h=1 | h=4 | h=12 | h=24 | h=48 |
|-|-|-|-|-|-|
| BTCUSDT | 0.2334 | **0.2488** | 0.0986 | -0.1023 | -0.0891 |
| ETHUSDT | 0.2079 | 0.1800 | 0.2090 | 0.2046 | **0.2149** |
| SOLUSDT | 0.0713 | 0.1149 | 0.1875 | **0.2515** | -0.0047 |

**Peak IC horizons:**

- BTCUSDT 1h: **24 bars** (rho=0.16) — longer half-life with optimized params (window=97, band=3.49)
- BTCUSDT 4h: **4 bars** (rho=0.25) — strongest overall IC, sharp decay
- ETHUSDT 1h: **12 bars** (rho=0.17) — medium half-life, gradual decay
- ETHUSDT 4h: **48 bars** (rho=0.21) — persistent signal, slow decay
- SOLUSDT 1h: **12 bars** (rho=0.18) — medium half-life, similar to ETH
- SOLUSDT 4h: **24 bars** (rho=0.25) — medium-long persistence

**Interpretation:**

- With optimized params, BTC 1h IC now peaks at 24 bars (previously 4 bars with default band=2.0). Wider bands produce a slower, more persistent signal. ETH and SOL peak at 12 bars on 1h, indicating medium-patience alpha.
- On 4h, BTC IC decays sharply after h=4, while ETH maintains IC across all horizons up to h=48. SOL peaks at h=24.
- The current optimizer default horizons (4, 12, 24 bars) are well-aligned with the empirical peak IC range.
- IC goes negative (anti-predictive) at h=48 for BTC and SOL on 1h, confirming the signal has a finite half-life.