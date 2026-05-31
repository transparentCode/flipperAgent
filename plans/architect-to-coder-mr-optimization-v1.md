---
goal: PBO-safe per-asset MeanReversion hyperparameter optimization
stage: architect-to-coder
date_created: 2026-06-01
last_updated: 2026-06-01
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, mean-reversion, optimization, PBO, CSCV, per-asset]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect-to-Coder: MeanReversion Per-Asset PBO-Safe Optimization

## 1. Objective

Optimize MeanReversion (MR) v2 z-score hyperparameters per-asset with PBO
validation, then re-allocate MR weight in the RegimeEnsembleBlender.

MR is the **only scoring model enabled across all assets** but has **never been
optimized** — every instance runs identical defaults. The Blender currently
assigns MR weight = 0.00 in ALL regime groups (zeroed during the 2026-05-31
blender redesign because defaults produced negative Sharpe). This creates a
two-phase problem:

1. MR params must be optimized to produce positive standalone alpha
2. Blender weights must be re-optimized with the improved MR to allocate it
   non-zero weight

## 2. Critical Finding: Existing Optimizer Bug

The current `src/libs/models/mean_reversion/optimization/optimizer.py` passes
continuous edge_scores from `batch_evaluate()` directly to `backtest_multi_tp()`
which casts values via `int()`. Since MR edge_scores are typically in [-2, 2],
`int(0.7) = 0` and `int(-0.7) = 0` — **only extreme scores |edge| >= 1 produce
trades**. This makes the objective nearly degenerate.

**Fix**: Use `compute_signal_weighted_returns()` from `libs.optim_utils.scoring`
which properly treats continuous edge_scores as proportional positions with
transaction costs. This is what `compute_signal_weighted_returns` was built for.

## 3. Scope Boundaries

### In Scope

| Item | Path | Change |
|------|------|--------|
| MR optimizer | `src/libs/models/mean_reversion/optimization/optimizer.py` | Rewrite objective to use `compute_signal_weighted_returns()` |
| Research notebook | `research/mr_optimization.ipynb` | New: full optimization + PBO for all assets |
| Config deployment | `configs/models.yaml` | Update per-asset MR params after PBO-GO |
| Blender re-opt | `configs/models.yaml` blender weights section | Update after Phase 2 blender re-optimization |

### Explicit Non-Goals

- NO changes to the MR model itself (`model.py`) — architecture is settled
- NO changes to `RegimeEnsembleBlender` code — only config weights change
- NO changes to indicator pipeline or `features.yaml`
- NO multi-objective optimization — single-objective Sharpe is sufficient for a
  scoring model
- NO live or paper-trading deployment in this handoff

## 4. Optimization Design

### 4.1 Objective Function

**Decision: Standalone signal-weighted returns (Option B from user's question)**

Rationale:
- MR is a continuous scoring model; its value is proportional position sizing
- `compute_signal_weighted_returns(edge_scores, close, cost_bps=10.0)` maps
  `edge_score → clipped position → bar returns − transaction costs`
- This directly measures what the Blender consumes (edge_score magnitude and sign)
- Full-pipeline optimization (Option A) is impossible because MR weight = 0.00 in
  the Blender — any MR params produce identical blended output
- IC/rank-IC (Option C) is interesting but doesn't account for transaction costs
  or holding behavior

**Optuna objective**:
```
score = sharpe(signal_weighted_returns) - 0.5 * |max_drawdown(signal_weighted_returns)|
```
This matches the objective used for all other model optimizers in the repo.

### 4.2 Parameter Search Space (4 effective params, not 6)

**Decision: Enforce simplex constraint on component weights**

The three weights (`w_rsi`, `w_bb`, `w_kama`) control relative contribution of
z-score components. Their absolute scale is absorbed by the ADX sigmoid, so only
their ratio matters. Enforce `w_rsi + w_bb + w_kama = 1.0` via:

```python
w_rsi = trial.suggest_float("w_rsi", 0.1, 0.8, step=0.05)
w_bb  = trial.suggest_float("w_bb", 0.1, min(0.8, 1.0 - w_rsi), step=0.05)
w_kama = round(1.0 - w_rsi - w_bb, 2)   # derived, not searched
# Prune if w_kama < 0.0
if w_kama < 0.0:
    raise optuna.TrialPruned()
```

This reduces the search from 6 to **4 effective parameters**:

| Param | Type | Default | Range | Step | Notes |
|-------|------|---------|-------|------|-------|
| `rsi_scale` | float | 15.0 | [5.0, 30.0] | 1.0 | Controls RSI z-score sensitivity |
| `w_rsi` | float | 0.4 | [0.1, 0.8] | 0.05 | RSI component weight (searched) |
| `w_bb` | float | 0.4 | [0.1, 0.8] | 0.05 | BB component weight (searched, upper-bounded) |
| `w_kama` | float | 0.2 | derived | — | `1.0 - w_rsi - w_bb` (not searched) |
| `adx_center` | float | 25.0 | [15.0, 40.0] | 1.0 | ADX sigmoid midpoint |
| `adx_steepness` | float | 5.0 | [2.0, 15.0] | 1.0 | ADX sigmoid slope |

**Grid for PBO CSCV** (enumerated, not Optuna):

| Param | Grid values | Count |
|-------|-------------|-------|
| `rsi_scale` | [5, 10, 15, 20, 25, 30] | 6 |
| `w_rsi` | [0.15, 0.3, 0.4, 0.5, 0.65] | 5 |
| `w_bb` | [0.15, 0.3, 0.4, 0.5, 0.65] | 5 |
| `adx_center` | [18, 25, 32, 40] | 4 |
| `adx_steepness` | [3, 5, 8, 12] | 4 |

With simplex pruning (`w_rsi + w_bb <= 1.0`), valid grid ≈ **1200–1500 configs**
(manageable for CSCV with S=16).

### 4.3 Walk-Forward Split

Use the existing `WalkForwardSplitter`:
- **Train**: 60% (Optuna searches here)
- **Validate**: 20% (Optuna objective evaluates here)
- **OOS**: 20% (held out, never seen during optimization)
- **Purge**: 24 bars between segments (avoid look-ahead leakage)

### 4.4 Data Window

- **Period**: 2024-06-01 to 2026-06-01 (2 years)
- **Source**: Binance USDⓈ-M futures klines API (same as PBO notebook)
- **Bar counts by timeframe**:
  - 30m: ~35,040 bars
  - 1h: ~17,520 bars
  - 4h: ~4,380 bars

## 5. Per-Asset Execution Order

| Priority | Asset | TF | Rationale |
|----------|-------|----|-----------|
| 1 | BTCUSDT | 1h | Most liquid, most data (17.5K bars), highest priority in production |
| 2 | BTCUSDT | 4h | Same asset different regime behavior; cross-TF validation of MR alpha |
| 3 | XRPUSDT | 1h | High vol alt, 17.5K bars, only alt with 1h MR enabled |
| 4 | ETHUSDT | 4h | 2nd most liquid, 4.4K bars |
| 5 | BNBUSDT | 30m | 35K bars but lower liquidity, different microstructure at 30m |
| 6 | DOGEUSDT | 4h | Lowest priority, uses default block, 4.4K bars |

**Early termination rule**: If BTCUSDT 1h produces PBO > 0.60 (strong overfit)
with full 4-param search, the model may lack structural alpha at these
frequencies. In that case:
1. Try reduced 2-param search (fix `adx_center=25, adx_steepness=5`)
2. If still PBO > 0.60, report NO-GO and skip remaining assets

## 6. PBO Validation Protocol

### Phase 1: Standalone MR Optimization + PBO

For each asset/timeframe:

1. **Fetch data** (Binance API, 2yr window)
2. **Compute indicators** (RSI, BB, KAMA, ATR, ADX — all already in pipeline)
3. **Build PBO grid returns matrix**:
   - For each of ~1200 valid grid configs
   - Compute `MeanReversionModel(params).batch_evaluate(feature_df)` → edge_scores
   - Compute `compute_signal_weighted_returns(edge_scores, close, cost_bps=10.0)` → per-bar returns
   - Store as column in T×N returns matrix
4. **Run CSCV**: S=16 partitions, C(16,8)=12,870 combinations
5. **Compute PBO**: fraction of logits ≤ 0
6. **Optuna refinement** (optional): Run 200 TPE trials on the train split to
   find the best continuous params, verify they fall within the GO region of the
   grid

**GO/NO-GO criteria** (same as SqueezeBreakout):

| Metric | GO | Borderline | NO-GO |
|--------|----|------------|-------|
| PBO | < 0.40 | 0.40–0.50 | > 0.50 |
| Mean logit | > 0.0 | -0.5–0.0 | < -0.5 |
| OOS Sharpe | > 0.0 | -0.3–0.0 | < -0.3 |
| OOS Sharpe degradation | < 50% of IS | 50–80% | > 80% |

### Phase 2: Blender Weight Re-Optimization

After Phase 1, for assets where MR achieved PBO-GO:

1. Use the PBO-validated MR params for each asset
2. Run MR + Momentum + SqueezeBreakout on the same 2yr data
3. Build a blender weight grid:
   - For each regime group (TREND_BULL, TREND_BEAR, RANGE, CHOPPY, TRANSITION)
   - Vary `mean_reversion` weight from 0.0 to 0.6 in steps of 0.1
   - Redistribute remaining weight proportionally to Momentum and SB
4. Compute blended signal → `compute_signal_weighted_returns()` → Sharpe
5. Run CSCV on the blender weight grid

This follows the same approach as the existing PBO notebook Cell 7 (blender
weights PBO) but now includes MR as a non-zero contributor.

### Phase 3: Cross-Validation Report

For each asset, produce:
- Full-sample Sharpe (MR standalone)
- Walk-forward train / val / OOS Sharpe
- PBO value and verdict
- Optimized params
- Blender weight allocation (post-Phase 2)
- IS vs OOS Sharpe CDF plot

## 7. Notebook Structure

Create `research/mr_optimization.ipynb` with the following cells:

| Cell | Purpose |
|------|---------|
| 1 | Imports, setup, model + indicator imports |
| 2 | Data fetching (all 6 asset/TF pairs, 2yr) |
| 3 | Feature computation (RSI, BB, KAMA, ATR, ADX for each asset) |
| 4 | `cscv_pbo()` function (copy from `pbo_analysis.ipynb` Cell 3) |
| 5 | Parameter grid construction with simplex constraint |
| 6 | `compute_mr_returns()` helper: params → returns array using `compute_signal_weighted_returns()` |
| 7 | Per-asset PBO loop: grid eval → returns matrix → CSCV → verdict |
| 8 | Optuna refinement: 200 trials per GO asset, using fixed objective |
| 9 | OOS evaluation: walk-forward degradation check for Optuna-best params |
| 10 | Phase 2: Blender weight re-optimization with MR non-zero |
| 11 | Visualization: PBO bar chart, logit distributions, IS vs OOS CDF, summary heatmap |
| 12 | Config output: `models.yaml` params for GO assets |

## 8. Implementation Order

1. **Fix `optimizer.py`**: Replace `backtest_multi_tp()` call with
   `compute_signal_weighted_returns()` in `make_objective()` and `evaluate_oos()`.
   This fixes the int-cast bug and makes the optimizer usable for any consumer.
2. **Create notebook** `research/mr_optimization.ipynb`
3. **Run Phase 1** (standalone MR PBO) sequentially for all 6 asset/TF pairs
4. **Run Phase 2** (blender re-opt) for GO assets only
5. **Update `configs/models.yaml`** with PBO-validated params and blender weights

## 9. Acceptance Criteria

- [ ] `optimizer.py` `make_objective()` uses `compute_signal_weighted_returns()`, not `backtest_multi_tp()` with int-cast
- [ ] Notebook fetches data for all 6 asset/TF pairs (BTCUSDT 1h/4h, ETHUSDT 4h, XRPUSDT 1h, BNBUSDT 30m, DOGEUSDT 4h)
- [ ] Simplex constraint enforced: `w_kama = 1 - w_rsi - w_bb`, invalid combos pruned
- [ ] CSCV uses S=16 partitions, PBO < 0.50 = GO threshold
- [ ] Per-asset PBO results table printed with verdict
- [ ] OOS Sharpe degradation checked (< 50% of IS = warning)
- [ ] Blender weight re-optimization run for GO assets
- [ ] Final summary includes: per-asset PBO, optimized params, blender weights, GO/NO-GO
- [ ] No look-ahead bias: walk-forward split with purge bars between segments
- [ ] Transaction costs included: 10 bps round-trip in signal-weighted returns

## 10. Validation Checklist

- [ ] PBO computed on grid (not Optuna trials) — Optuna trials are NOT iid configs
- [ ] Returns matrix has sufficient active configs (> 50) per asset
- [ ] Logit distribution plotted — check for bimodal pathology
- [ ] IS vs OOS Sharpe CDF shows no stochastic dominance inversion
- [ ] `w_kama` never negative in any grid config
- [ ] Data fetched via Binance API matches expected bar count ±2%
- [ ] Feature computation matches production pipeline indicators

## 11. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| MR lacks structural alpha at any frequency | All assets NO-GO, wasted effort | Early termination: if BTC 1h PBO > 0.60, stop and report |
| Standalone MR alpha doesn't survive blending | Positive standalone, negative blended | Phase 2 tests this explicitly; if blender re-opt zeros MR again, accept the result |
| 4h timeframes have only ~4,380 bars | Insufficient data for S=16 CSCV (273 bars/block) | Acceptable — 273 bars is ~45 days of 4h data, enough for Sharpe estimation. If block_size < 200, reduce to S=12 |
| Simplex constraint is too restrictive | Misses non-normalized weight combos that outperform | ADX sigmoid absorbs magnitude; constraint reduces DoF which helps PBO |
| Optimizer bug fix changes existing optimizer behavior | Other consumers of `make_objective()` may break | The current behavior is broken (zero trades for most params); fix is strictly an improvement |
| 30m BNBUSDT has 35K bars but lower liquidity | Overfitting to microstructure noise | Use higher cost_bps (15 instead of 10) for 30m to penalize turnover |

## 12. Blast Radius

### Code Changes
- `src/libs/models/mean_reversion/optimization/optimizer.py` — objective function
  rewrite (replace `backtest_multi_tp` with `compute_signal_weighted_returns`)
- `configs/models.yaml` — per-asset MR params and blender weights (config only)

### Execution Flows Affected
- MR optimization pipeline (offline only, no production impact until config deploy)
- RegimeEnsembleBlender blend weights (config-only change, no code change)

### Not Changed
- `src/libs/models/mean_reversion/model.py` — model logic unchanged
- `src/libs/models/blender/ensemble.py` — blender code unchanged
- `src/libs/optim_utils/scoring.py` — utility functions unchanged
- `src/apps/strategy_app/` — strategy worker unchanged
- All indicator pipelines, features.yaml, risk config, execution config

## 13. Architecture Tradeoffs and Rejected Options

### Option A: Full-Pipeline Optimization (MR → Blender → Backtest)
- **Rejected**: MR weight = 0.00 in all Blender regime groups. Any MR params
  produce identical blended output. Would need joint optimization of MR params +
  blender weights simultaneously, creating a ~10-dimensional search space that
  would almost certainly overfit.

### Option C: IC / Rank-IC Objective
- **Rejected**: IC measures correlation between edge_score and forward returns but
  doesn't account for transaction costs, position sizing, or drawdown. A model
  with high IC but high turnover would be penalized in production but not in IC.
  Signal-weighted returns with cost naturally penalize this.

### Free weights (no simplex)
- **Rejected**: Without normalization, Optuna can achieve the same Sharpe by
  scaling all weights up or down. The extra degree of freedom is pure noise that
  inflates PBO.

### S=8 instead of S=16
- **Rejected**: S=16 gives C(16,8)=12,870 CSCV splits — much more robust than
  S=8's C(8,4)=70 splits. The 4h assets have ~4,380 bars which gives
  block_size=273 at S=16, still sufficient for Sharpe estimation.
