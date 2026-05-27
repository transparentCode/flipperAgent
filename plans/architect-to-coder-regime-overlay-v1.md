---
goal: Cross-Asset Relative Value Regime Overlay for existing scoring models
stage: architect-to-coder
date_created: 2026-05-27
last_updated: 2026-05-27
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, regime, cross-asset, overlay, feature-engineering, tradingview]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Cross-Asset Relative Value Regime Overlay

## 1. Context Retrieved

### Prior Decisions
- **41d6e131**: TV Index Data Architecture — Option C-Hybrid. TV scraper in separate container, data to `tv_index_ohlcv` table + Valkey hashes `index:latest:{BTC.D|TOTAL2|TOTAL3}`. ARQ periodic fetch at candle-close+30s.
- **da381d60**: TV indices placement — BTC.D→regime gate, TOTAL2→momentum z, TOTAL3→relative strength. Cross-sectional features for Selection Layer and scoring models ONLY. Legacy models (SB/MR) unchanged.
- **40c11834**: Strategic pivot — feature-first approach, alpha decay acknowledged, selection layer is key missing piece.
- **14bc36cd**: 3-tier model architecture: (1) Traditional threshold (SB/MR), (2) Feature-engineered scoring, (3) Alt-data regime features.

### Existing Infrastructure
- 4 cross-sectional features already built and live: `btc_dominance_regime`, `altcoin_market_momentum`, `market_cap_breadth`, `altcoin_beta`.
- Signal worker already fetches TV index data from Valkey hashes (O(1) per index) and passes to `EngineeredFeatureManager.compute()`.
- All 4 features enabled in `features.yaml` under `engineered_features.assets.default.timeframes.default`.
- Two scoring models already consume these: `RegimePullbackScorer` (uses `eng_btc_dominance_regime`, `eng_market_cap_breadth`) and `DivergenceEdgeScorer`.
- Selection layer with `overlap_penalized_top_k` strategy already routes candidates to risk.

### User Hypothesis
> "When BTC.D rises + TOTAL3 falls → alts underperforming → potential mean-reversion entry."

---

## 2. Confirmed Facts

| Fact | Source |
|------|--------|
| TV data (BTC.D, TOTAL2, TOTAL3) flows to Valkey hashes and is consumed in signal_worker | `signal_worker.py:83-100` |
| Engineered features are prefixed `eng_` and merged into FeatureVector | `manager.py:87-97` |
| ScoringModel receives FeatureVector with `features` dict containing `eng_*` keys | `scoring_base.py`, `regime_pullback/model.py` |
| StrategyWorker calls `scoring_model_manager.evaluate()` then `selection_layer.select()` | `strategy_worker.py:72-84` |
| Legacy models (SB/MR) are NOT modified — they run through `model_manager.evaluate()` and `evaluate_adapted()` separately | `strategy_worker.py:72-78` |
| TV scraper is on 1h timeframe (`tradingview.yaml`) with 3h staleness TTL | `tradingview.yaml` |
| `EngineeredFeature.compute()` receives `index_data` param; degrades to `0.0` when unavailable | `cross_sectional.py` |

---

## 3. Open Questions (Resolved by Analysis)

| Question | Resolution |
|----------|------------|
| Where does the overlay inject? | **At the EngineeredFeature + ScoringModel level**, NOT at risk or strategy worker. This preserves the existing pipeline topology. New features feed existing and new scorers. |
| Gate vs Sizing vs Bias? | **Option D: Filter+Boost**. Regime state is encoded as features; scorers decide how to use them (gate, bias, or boost). This keeps regime logic in features and trading logic in models — proper separation of concerns. |
| How to handle multi-timeframe data mismatch? | TV data is 1h only. For 4h/30m model timeframes, the signal_worker already reads the same Valkey hashes (latest snapshot), so features naturally use the most recent 1h TV bar. This is correct — index data doesn't need TF alignment. |
| Backtesting with limited TV history? | Build a `tv_backfill.py` one-shot script using the existing TV scraper WS interceptor pattern. Target 90+ days of 1h data for BTC.D/TOTAL2/TOTAL3. Store in `tv_index_ohlcv`. Backtester joins on timestamp. |

---

## 4. Architecture Decision: Filter+Boost via Feature Layer (Option D)

### Why NOT Gate (Option A)
- Binary on/off is too crude. A gate at StrategyWorker would suppress all signals, including valid ones in ambiguous regimes.
- Doesn't let models express partial confidence adjustments.

### Why NOT Sizing-only (Option B)
- Sizing belongs in the Risk layer. Duplicating it here creates competing logic.
- The Risk worker already has volatility-scaled sizing — adding regime sizing there later is additive and doesn't require model changes.

### Why NOT Bias (Option C)
- Adding directional bias independently of model signals is dangerous — it creates phantom signals not backed by price action.

### Why Filter+Boost (Option D)
- Regime information is encoded as **engineered features** (existing pattern).
- Scoring models consume features and decide how to weight regime info alongside price-action signals.
- Models can gate (return `edge_score=0` when regime is bad), boost (increase conviction when regime is aligned), or ignore regime features — each model chooses.
- This preserves the clean separation: features compute, models decide, selection layer ranks, risk sizes.
- Zero blast radius on legacy models (SB/MR) — they never see `eng_*` features.

### Regime State Machine

The regime state machine is an engineered feature that classifies the cross-asset environment into one of 4 discrete states. It uses BTC.D + TOTAL3 momentum as primary inputs.

```
                    BTC.D Rising
                   ┌─────────────┐
                   │             │
    TOTAL3 Rising  │  ROTATION   │  TOTAL3 Falling
    ───────────────┤  (BTC.D↑    ├───────────────────
                   │   T3↑)     │
                   │  neutral    │   RISK_OFF
                   │             │   (BTC.D↑ T3↓)
                   └──────┬──────┘   → alt MR entry
                          │
                   BTC.D Falling
                   ┌─────────────┐
                   │             │
    TOTAL3 Rising  │  ALT_SEASON │  TOTAL3 Falling
    ───────────────┤  (BTC.D↓    ├───────────────────
                   │   T3↑)     │
                   │  alt trend  │   BROAD_SELLOFF
                   │  follow     │   (BTC.D↓ T3↓)
                   └─────────────┘   → risk-off, no entries

State Definitions:
  RISK_OFF    = 0: BTC.D momentum > threshold AND TOTAL3 momentum < -threshold
                   → Alts underperforming, capital fleeing to BTC
                   → Mean-reversion opportunity for alts (user hypothesis)
  ALT_SEASON  = 1: BTC.D momentum < -threshold AND TOTAL3 momentum > threshold
                   → Alts outperforming, trend-following favorable
  ROTATION    = 2: BTC.D momentum > threshold AND TOTAL3 momentum > threshold
                   → Mixed, both rising — ambiguous, neutral overlay
  BROAD_SELLOFF = 3: BTC.D momentum < -threshold AND TOTAL3 momentum < -threshold
                   → Everything falling, risk-off, suppress all entries
```

---

## 5. New Features to Build

### 5a. `btc_dominance_momentum` (NEW)

The existing `btc_dominance_regime` uses a static level: `tanh((BTC.D - 50) / 10)`. This is useful but misses **rate of change**. BTC.D at 55% and rising is very different from 55% and falling.

```
btc_dominance_momentum = (BTC.D_close - SMA(BTC.D_close, period)) / ATR(BTC.D, atr_period)
```

- Rolling SMA and ATR on BTC.D close/high/low from Valkey hash history.
- Requires `state` dict for rolling windows (same pattern as `AltcoinMarketMomentum`).
- Default: `period=10`, `atr_period=14`.
- Returns: Positive = BTC.D rising (alts weakening), Negative = BTC.D falling (alt season starting).
- Degrades to `0.0` when BTC.D data unavailable.

### 5b. `total3_momentum_z` (NEW)

Z-score of TOTAL3 momentum relative to its own rolling distribution.

```
raw_momentum = TOTAL3_close - SMA(TOTAL3_close, sma_period)
z = (raw_momentum - rolling_mean(raw_momentum, z_period)) / rolling_std(raw_momentum, z_period)
```

- Default: `sma_period=20`, `z_period=50`.
- Clipped to `[-3.0, 3.0]` to prevent outlier contamination.
- Positive z → TOTAL3 momentum is unusually strong (alt trend).
- Negative z → TOTAL3 momentum is unusually weak (alt risk-off).
- Requires rolling mean+std in `state` via Welford's online algorithm.

### 5c. `cross_asset_regime_state` (NEW — the state machine)

Discrete regime classifier using `btc_dominance_momentum` and `total3_momentum_z` (or `altcoin_market_momentum` as proxy).

```python
def compute(...):
    btc_d_mom = features.get("eng_btc_dominance_momentum", 0.0)
    t3_mom = features.get("eng_altcoin_market_momentum", 0.0)
    # OR use eng_total3_momentum_z

    btc_d_rising = btc_d_mom > self.params["btc_d_threshold"]
    btc_d_falling = btc_d_mom < -self.params["btc_d_threshold"]
    t3_rising = t3_mom > self.params["t3_threshold"]
    t3_falling = t3_mom < -self.params["t3_threshold"]

    if btc_d_rising and t3_falling:
        return 0  # RISK_OFF — alt MR opportunity
    elif btc_d_falling and t3_rising:
        return 1  # ALT_SEASON — trend follow
    elif btc_d_rising and t3_rising:
        return 2  # ROTATION — neutral
    elif btc_d_falling and t3_falling:
        return 3  # BROAD_SELLOFF — suppress
    else:
        return 2  # ROTATION (default neutral)
```

- Default: `btc_d_threshold=0.5`, `t3_threshold=0.5`.
- All thresholds configurable in `features.yaml`.
- NOTE: This feature depends on other `eng_*` features. Compute order matters — the `EngineeredFeatureManager` must compute `btc_dominance_momentum` and `altcoin_market_momentum` BEFORE `cross_asset_regime_state`. See Implementation Note below.

### 5d. `relative_strength_vs_total3` (NEW)

Per-asset relative strength vs TOTAL3.

```
RS = (asset_return_N - TOTAL3_return_N) / max(abs(TOTAL3_return_N), epsilon)
```

- Default: `period=20`, `epsilon=1e-8`.
- Positive → asset outperforming alts basket.
- Negative → asset underperforming.
- Uses rolling returns from `bar_data["close"]` + `index_data["TOTAL3"]["close"]`.

### 5e. `regime_alignment_score` (NEW)

Continuous composite score combining regime state + alignment with model direction. This is the primary feature consumed by scoring models for regime overlay.

```
regime_alignment = w1 * btc_d_momentum_signal
                 + w2 * t3_momentum_signal
                 + w3 * breadth_signal
                 + w4 * relative_strength_signal
```

- All component signals normalized to [-1, 1].
- Default weights: `w1=0.3, w2=0.3, w3=0.2, w4=0.2`.
- Positive → regime favors longs on alts.
- Negative → regime favors shorts / risk-off.
- Models multiply this with their edge_score: `adjusted_edge = edge_score * (1.0 + regime_alignment * regime_weight)`.

---

## 6. Feature Compute Order Constraint

`EngineeredFeatureManager.compute()` iterates `self._features` in registration order. The `cross_asset_regime_state` feature reads other `eng_*` features from the `features` dict. Currently, `compute()` adds results to a separate `results` dict and does NOT update the input `features` dict mid-iteration.

**Required Change**: The manager must update the input `features` dict (or a merged view) after each feature computation so that dependent features can read previously-computed `eng_*` values.

Option: Sort features by dependency (topological) or use a simple two-pass approach:
- **Pass 1**: Compute features with no `eng_*` dependencies (all current features + new 5a, 5b, 5d).
- **Pass 2**: Compute features that read `eng_*` outputs (5c, 5e).

Implementation: Add a `depends_on_engineered: bool = False` property to `EngineeredFeature`. Manager runs `depends_on_engineered=False` features first, merges results into `features`, then runs `depends_on_engineered=True` features.

---

## 7. Integration Points

### 7a. Signal Worker (EXISTING — no change needed)

The signal worker already:
1. Fetches TV index data from Valkey hashes (`signal_worker.py:83-100`).
2. Passes `index_data` to `EngineeredFeatureManager.compute()`.
3. Merges `eng_*` features into the `FeatureVector`.
4. Publishes to `features:{asset}:{tf}` stream.

No changes to signal_worker.py.

### 7b. Scoring Models (CONSUMERS — modify existing, add new)

**RegimePullbackScorer** already reads `eng_btc_dominance_regime` and `eng_market_cap_breadth`. Add:
- Read `eng_cross_asset_regime_state` as a gate: suppress signal (return zero ScoringOutput) when regime == `BROAD_SELLOFF` (state 3).
- Read `eng_regime_alignment_score` to scale `edge_score`: `edge *= (1.0 + alignment * p["regime_overlay_weight"])`.
- Add new hyperparameters: `regime_overlay_weight` (default 0.3, range 0.0-0.8), `suppress_broad_selloff` (default True).

**DivergenceEdgeScorer**: Add same regime overlay pattern:
- Gate on `BROAD_SELLOFF`.
- Scale edge by `eng_regime_alignment_score`.

**New Scorer: `RegimeRelativeValueScorer`** (the user's core hypothesis):
- Entry condition: `eng_cross_asset_regime_state == RISK_OFF` AND `eng_relative_strength_vs_total3 < rs_threshold` AND RSI < oversold_gate.
- Edge = magnitude of underperformance * regime confidence.
- Direction = LONG (mean-reversion: asset underperforming in risk-off → expect catch-up).
- Conviction = f(regime_alignment_score, RSI depth, underperformance magnitude).
- This directly implements: "BTC.D rises + TOTAL3 falls → alts underperforming → mean-reversion."

### 7c. Risk Worker (FUTURE — not in this handoff)

Future enhancement: pass `eng_cross_asset_regime_state` to risk layer for regime-aware position sizing. NOT in scope for this handoff.

### 7d. Selection Layer (NO CHANGE)

Selection layer is model-agnostic. It receives `ScoringOutput` candidates and ranks them. The overlay is invisible to it — models simply produce better/worse edge_scores based on regime.

---

## 8. Config Structure

### 8a. `features.yaml` additions

```yaml
engineered_features:
  assets:
    default:
      timeframes:
        default:
          # ... existing features ...
          btc_dominance_momentum:
            enabled: true
            params:
              sma_period: 10
              atr_period: 14
          total3_momentum_z:
            enabled: true
            params:
              sma_period: 20
              z_period: 50
              clip_range: 3.0
          cross_asset_regime_state:
            enabled: true
            params:
              btc_d_threshold: 0.5
              t3_threshold: 0.5
          relative_strength_vs_total3:
            enabled: true
            params:
              period: 20
          regime_alignment_score:
            enabled: true
            params:
              w_btc_d: 0.3
              w_t3: 0.3
              w_breadth: 0.2
              w_rs: 0.2
```

### 8b. `models.yaml` additions

```yaml
scoring_models:
  assets:
    default:
      timeframes:
        default:
          RegimeRelativeValueScorer:
            enabled: true
            params:
              rs_underperformance_threshold: -0.5
              rsi_oversold_gate: 35
              regime_state_required: 0  # RISK_OFF
              min_btc_d_momentum: 0.3
              conviction_base: 0.3
              conviction_depth_bonus: 0.4
          # Existing scorers get new params:
          RegimePullbackScorer:
            params:
              regime_overlay_weight: 0.3
              suppress_broad_selloff: true
          DivergenceEdgeScorer:
            params:
              regime_overlay_weight: 0.2
              suppress_broad_selloff: true
```

### 8c. Engineered Feature `params` Support

Currently, `EngineeredFeature` subclasses hardcode their parameters (e.g., `center = 50.0` in `BTCDominanceRegime`). The new features need configurable params from `features.yaml`.

**Required Change**: `EngineeredFeatureManager._initialize()` should pass `feat_params` to the feature constructor:
```python
feat_cls = EngineeredFeatureRegistry.get(feat_name)
params = feat_params.get("params", {}) if isinstance(feat_params, dict) else {}
self._features.append(feat_cls(params=params))
```

And `EngineeredFeature.__init__` accepts optional `params: dict`:
```python
class EngineeredFeature(ABC):
    def __init__(self, params: dict[str, Any] | None = None):
        self.params = params or {}
```

---

## 9. Implementation Order

| Step | Module | Description | Files |
|------|--------|-------------|-------|
| 1 | `EngineeredFeature` base | Add `params` to `__init__`, add `depends_on_engineered` property | `libs/features/engineered/base.py` |
| 2 | `EngineeredFeatureManager` | Pass params to constructors, add two-pass compute for dependent features | `libs/features/engineered/manager.py` |
| 3 | `btc_dominance_momentum` | New feature: SMA/ATR momentum on BTC.D | `libs/features/engineered/cross_sectional.py` |
| 4 | `total3_momentum_z` | New feature: z-score of TOTAL3 momentum | `libs/features/engineered/cross_sectional.py` |
| 5 | `relative_strength_vs_total3` | New feature: per-asset RS vs TOTAL3 | `libs/features/engineered/cross_sectional.py` |
| 6 | `cross_asset_regime_state` | New feature: 4-state regime classifier (depends on step 3-4) | `libs/features/engineered/cross_sectional.py` |
| 7 | `regime_alignment_score` | New feature: continuous composite overlay score (depends on step 3-5) | `libs/features/engineered/cross_sectional.py` |
| 8 | `features.yaml` | Add config entries for all 5 new features with defaults | `configs/features.yaml` |
| 9 | `RegimePullbackScorer` | Add regime overlay: gate on BROAD_SELLOFF, scale by alignment | `libs/models/regime_pullback/model.py` |
| 10 | `DivergenceEdgeScorer` | Add regime overlay: same pattern as step 9 | `libs/models/divergence_edge/model.py` |
| 11 | `RegimeRelativeValueScorer` | New scoring model: the user's MR hypothesis | `libs/models/regime_relative_value/model.py` |
| 12 | `models.yaml` | Add `RegimeRelativeValueScorer` config, overlay params for existing scorers | `configs/models.yaml` |
| 13 | Tests | Unit tests for all 5 features + parity, scorer unit tests, integration test | `tests/` |

---

## 10. Acceptance Criteria

1. **5 new engineered features** compute correctly and degrade to `0.0` / neutral when TV index data is unavailable.
2. **Regime state machine** correctly classifies all 4 states using configurable thresholds.
3. **Dependent feature compute order** works: `cross_asset_regime_state` and `regime_alignment_score` can read other `eng_*` values.
4. **Params from config**: all engineered features accept `params` from `features.yaml` instead of hardcoding.
5. **RegimePullbackScorer** suppresses signals during `BROAD_SELLOFF` and scales edge by `regime_alignment_score`.
6. **DivergenceEdgeScorer** same overlay behavior.
7. **RegimeRelativeValueScorer** produces LONG signals when `RISK_OFF + underperformance + RSI oversold`.
8. **All existing tests pass** (454+ unit tests).
9. **New tests**: at minimum 5 feature unit tests + 3 scorer tests + 1 integration test for compute ordering.
10. **Config-driven**: all thresholds and weights come from YAML, no magic numbers.
11. **Zero blast radius on legacy models**: SB/MR `model_manager.evaluate()` path unchanged.
12. **No signal_worker.py changes**.

---

## 11. Validation Checklist

### Quant Correctness
- [ ] Features degrade gracefully: return `0.0` when `index_data` is None or stale.
- [ ] No look-ahead bias: features only use current and past values (rolling state, not future).
- [ ] Rolling computations use `deque(maxlen=N)` or Welford's — O(1) per tick.
- [ ] Z-score clipping prevents extreme outliers (`[-3.0, 3.0]`).
- [ ] Regime state transitions are deterministic given the same inputs.
- [ ] `RegimeRelativeValueScorer` only enters LONG on alts during `RISK_OFF` — no directional assumption on BTC.

### Engineering
- [ ] All features registered with `@EngineeredFeatureRegistry.register(name)`.
- [ ] New scorer registered with `@ScoringModelRegistry.register("RegimeRelativeValueScorer")`.
- [ ] Feature compute ordering tested: swap order and verify `cross_asset_regime_state` still reads correct inputs.
- [ ] Config fallback chain works: `default/default` params apply to all assets unless overridden.
- [ ] `ScoringOutput.metadata` includes regime state for observability.
- [ ] No `import logging` — use `bind_logger(__name__)`.

### Bias Controls
- [ ] Point-in-time: TV data is latest bar only, no future data leakage.
- [ ] Staleness: if TV data is older than `staleness_ttl_seconds` (3h), features return neutral — verify existing `0.0` default handles this.
- [ ] No survivorship bias risk (index data, not individual assets).
- [ ] Backtest parity: offline batch mode must produce identical regime classifications as online.

---

## 12. Backtesting Plan

### Data Acquisition
1. Run `tv_backfill.py` (one-shot WS interceptor, existing scraper pattern) to collect 90+ days of 1h BTC.D, TOTAL2, TOTAL3 OHLCV.
2. Store in existing `tv_index_ohlcv` TimescaleDB hypertable.
3. Verify no gaps: `SELECT date_trunc('hour', ts) AS h, count(*) FROM tv_index_ohlcv GROUP BY h ORDER BY h` should show 1 row per index per hour.

### Feature Validation
4. Compute all 5 new features in batch mode over the historical data.
5. Verify regime state distribution: expect all 4 states represented, no single state > 60% of bars.
6. Verify `regime_alignment_score` distribution: should be approximately centered, |mean| < 0.2.

### Model Validation
7. Run `RegimeRelativeValueScorer` in offline batch mode.
8. Count signal frequency: if > 5% of bars trigger, thresholds are too loose.
9. Basic PnL analysis (if backtester available): Sharpe, max DD, win rate.
10. Compare with/without overlay on existing scorers: `RegimePullbackScorer` Sharpe with vs without `suppress_broad_selloff`.

### Limitation
- 90 days of 1h data = ~2,160 bars. This is sufficient for feature validation and regime distribution checks but NOT for statistically significant backtest conclusions. Treat model results as directional, not definitive.

---

## 13. Risks and Tradeoffs

| Risk | Severity | Mitigation |
|------|----------|------------|
| TV data staleness in live | Medium | Existing 3h TTL + `0.0` degradation. Monitor `index:latest:*` freshness. |
| Regime state overfitting to recent crypto cycles | High | Keep thresholds configurable. Don't optimize regime params on limited data. |
| Feature compute ordering fragility | Medium | `depends_on_engineered` property + test that verifies ordering. |
| Limited backtest history (90 days) | High | Treat as directional validation only. PBO not possible with this sample. |
| `RegimeRelativeValueScorer` generates correlated signals with existing MR scorer | Medium | Selection layer's `overlap_penalized_top_k` naturally penalizes same-direction overlap. |
| Cross-asset features add 5 more eng_ fields to FeatureVector — marginal latency | Low | All computations are O(1) per tick. Valkey hash reads are already batched. |

---

## 14. Explicit Non-Goals

- **NOT modifying legacy models** (SqueezeBreakout, MeanReversion). They continue operating independently through `model_manager.evaluate()`.
- **NOT modifying signal_worker.py**. TV data fetch and engineered feature merge are already wired.
- **NOT adding regime-aware position sizing to Risk layer**. That's a future enhancement.
- **NOT building a full backtester**. This handoff adds features and scorers; backtesting is an existing capability.
- **NOT adding new TV indices** (e.g., TOTAL, ETH.D). Scope is BTC.D, TOTAL2, TOTAL3 only.
- **NOT implementing batch mode for new features**. Online `compute()` is sufficient for v1; `batch_evaluate()` for the new scorer uses the same logic over a DataFrame.

---

## 15. Blast Radius and Affected Flows

### Modified Files
| File | Change Type | Risk |
|------|-------------|------|
| `libs/features/engineered/base.py` | Add `params` + `depends_on_engineered` | Low — additive, backward-compatible |
| `libs/features/engineered/manager.py` | Two-pass compute, pass params | Medium — changes iteration logic |
| `libs/features/engineered/cross_sectional.py` | Add 5 new feature classes | Low — additive only |
| `libs/models/regime_pullback/model.py` | Add overlay params + regime gate | Medium — changes scoring logic |
| `libs/models/divergence_edge/model.py` | Add overlay params + regime gate | Medium — changes scoring logic |
| `configs/features.yaml` | Add 5 feature entries | Low — config only |
| `configs/models.yaml` | Add new scorer + overlay params | Low — config only |

### New Files
| File | Purpose |
|------|---------|
| `libs/models/regime_relative_value/__init__.py` | Package init |
| `libs/models/regime_relative_value/model.py` | `RegimeRelativeValueScorer` |
| `tests/unit/test_regime_features.py` | Feature unit tests |
| `tests/unit/test_regime_relative_value_scorer.py` | Scorer unit tests |

### Execution Flows Affected
1. **Feature computation flow** (signal_worker → EngineeredFeatureManager → FeatureVector): Changed iteration to two-pass. Risk: if ordering breaks, dependent features get stale inputs. Mitigation: explicit test.
2. **Scoring evaluation flow** (StrategyWorker → ScoringModelManager → SelectionLayer): New scorer added, existing scorers modified. Risk: regime gate could suppress valid signals. Mitigation: configurable `suppress_broad_selloff` flag, can be disabled per-model.
3. **Legacy model flow** (StrategyWorker → ModelManager → SelectionLayer): **UNAFFECTED**. Legacy models don't read `eng_*` features.

### Not Affected
- Ingestion pipeline (ingestion_app)
- TV scraper (tv_scraper)
- Risk pipeline (risk_app)
- Execution pipeline (execution_app)
- Portfolio tracking (portfolio_app)
