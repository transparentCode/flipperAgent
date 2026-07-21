# flipperAgent: Post-Indicator Pivot — Action Plan

**Date**: 2026-05-27
**Status**: Approved
**Owner**: Quant Architect → Quant Coder

---

## Background

Standard technical indicator features (MACD, RSI, BB, KC, ADX, CCI, MFI, engineered features) have **zero tradeable alpha** on crypto at 1h and 4h frequencies (2024–2026). This was conclusively proven across:

- **4 model architectures**: RegimePullback, DivergenceEdge, SqueezeBreakout legacy, SqueezeBreakout Scorer
- **7 asset/timeframe combos**: BTC/ETH/SOL/XRP/DOGE × 1h/4h
- **200 Optuna trials**: best strategy = "don't trade" (Sharpe 0.000)
- **ML scan**: LightGBM + LogReg on 33 features → OOS AUC 0.49–0.55 (random), all trading simulations negative
- **Funding rate test**: marginal momentum signal (Sharpe +0.91, 76 signals in 2yr) — not actionable

**Conclusion**: The problem is the features, not the model architecture. Standard OHLCV-derived indicators are arbitraged away at these frequencies.

---

## Working Infrastructure (Reusable)

| Component | Status | Notes |
|-----------|--------|-------|
| Feature pipeline (FeatureManager → EngineeredFeatureManager → DataFrame) | ✅ Working | 38 columns, tested |
| ScoringModel base class + ScoringModelRegistry | ✅ Working | evaluate() + batch_evaluate() |
| SelectionLayer | ✅ Working | Ranks/filters model outputs |
| Optuna optimization + purged k-fold CV | ✅ Working | Harness proven |
| Data fetcher (Binance REST) | ✅ Working | OHLCV + funding rates |
| TradingView scraper (BTC.D, TOTAL2, TOTAL3) | ✅ Working | Cross-sectional data |
| Valkey streams event-driven pipeline | ✅ Working | Stream topology |
| TimescaleDB persistence | ✅ Working | Schema + read/write |
| Docker infrastructure | ✅ Built | Needs E2E validation |
| Test suite | ✅ 752 tests passing | 0 failures |
| Live deployed models (SB×5 assets, MR×2 assets) | ⚠️ Running | No confirmed alpha |

---

## Action Plan

### Phase 0: Live Model Risk Containment *(DEFERRED)*
> Deferred — will address after infrastructure is robust.

- Reduce live model position sizing to 25% of current levels
- Disable TrendFollowing and Momentum models if running
- Keep SB and MR running at reduced size (structural pattern, episodic alpha possible)

**Rationale for deferral**: The live models are running with risk limits already. Making the infrastructure robust (Phase 2/3) first ensures we can properly measure and manage risk before making sizing changes.

---

### Phase 1: Derivatives Microstructure MVE *(DEFERRED)*
> Deferred — searching for new alpha sources deprioritized vs making current system robust.

- Fetch 2yr funding rate + OI history for BTC/ETH/SOL
- Engineer features: funding_zscore_8h, OI_pct_change_8h, long_short_ratio
- LightGBM walk-forward OOS scan
- **Go/no-go**: OOS AUC > 0.53 → build `DerivativesMicrostructureScorer(ScoringModel)`

**Rationale for deferral**: The user prefers making the current deployed models robust rather than researching new models. This remains the top alpha research priority when ready.

---

### Phase 2: Infrastructure — Make Current System Robust *(PRIORITY 1)*

#### 2A. Backtesting Harness
- Build a proper backtesting framework that any model (current or future) can use
- Walk-forward, expanding-window, and fixed-window modes
- Standardized metrics: Sharpe, MaxDD, Calmar, win rate, profit factor
- Integration with existing `compute_signal_weighted_returns` and `compute_returns`
- Output: performance reports comparable across models

#### 2B. E2E Docker Validation
- Validate the full pipeline deploys correctly in Docker
- Test: ingestion → signal_app → strategy_app → risk_app → execution_app
- Verify Valkey stream topology, TimescaleDB persistence, config loading
- Smoke test: ingest live data, generate signals, confirm end-to-end flow

#### 2C. Portfolio Tracker
- Implement the designed portfolio tracker (plans/architect-to-coder-portfolio-tracker-v1.md)
- Equity curve tracking, closed trade journal, PnL attribution
- Reads from existing DB tables (risk_account_snapshots, execution_fills)
- Essential for measuring whether live models are actually profitable

#### 2D. Risk Manager Hardening
- Review and validate risk limits on deployed models
- Ensure stop-losses, position limits, and drawdown circuit breakers are active
- Add monitoring/alerting for live model performance

---

### Phase 3: Cross-Asset Relative Value *(PRIORITY 2)*

Uses existing TradingView scraper data (BTC.D, TOTAL2, TOTAL3).

- When BTC.D rises + TOTAL3 falls → alts underperforming → potential mean-reversion
- Build relative-value signals from cross-sectional TV data
- Test as a regime overlay on top of existing deployed models
- Can enhance SB/MR signal quality without replacing them

**Why this before Phase 1**: This uses data we ALREADY have (TV scraper is running) and enhances existing models rather than building new ones.

---

### Shelved *(Revisit After Phase 2/3)*

| Item | Reason |
|------|--------|
| Feature Selection Layer v1 handoff | Designed for dead indicator features |
| RegimePullbackScorer | No alpha — archive, don't delete |
| DivergenceEdgeScorer | Signal doesn't exist — archive |
| SqueezeBreakoutScorer optimization | Proven "don't trade" is optimal |
| Multi-timeframe indicator research | Indicator features are dead |
| New scoring model development | Wait for derivatives MVE results |

---

## Execution Order

```
Phase 2A: Backtesting Harness          [PRIORITY 1 — enables everything else]
Phase 2B: E2E Docker Validation        [PRIORITY 1 — confirms deployment works]
Phase 2C: Portfolio Tracker            [PRIORITY 1 — measures live performance]
Phase 2D: Risk Manager Hardening       [PRIORITY 1 — protects live capital]
Phase 3:  Cross-Asset Relative Value   [PRIORITY 2 — enhances existing models]
Phase 0:  Live Model Risk Cuts         [DEFERRED — after infra is robust]
Phase 1:  Derivatives MVE              [DEFERRED — new alpha research]
```

---

## Decision Tree

```
Build Infrastructure (Phase 2)
├── Backtesting harness works
│   ├── Portfolio tracker shows SB/MR are profitable → Keep running, add Phase 3 overlay
│   └── Portfolio tracker shows SB/MR are losing → Execute Phase 0 (risk cuts), then Phase 1
├── E2E Docker validates
│   └── Deploy monitoring + portfolio tracker in production
└── Cross-Asset Overlay (Phase 3)
    ├── Improves SB/MR Sharpe → Deploy as regime filter
    └── No improvement → Proceed to Phase 1 (derivatives MVE)
```

---

## Evidence Archive

| Test | Result | Date |
|------|--------|------|
| RegimePullback 2yr BTCUSDT 1h | Sharpe -0.72, Return -2.71% | 2026-05-27 |
| DivergenceEdge 2yr BTCUSDT 1h | Sharpe -1.94, Return -59.44% | 2026-05-27 |
| SB Scorer 2yr BTCUSDT 1h (defaults) | Sharpe -3.30, Return -28.26% | 2026-05-27 |
| SB Scorer 200 Optuna trials | Best = "don't trade" (Sharpe 0.00) | 2026-05-27 |
| Legacy SB 2yr BTCUSDT 1h | Sharpe -3.77, Return -41.21% | 2026-05-27 |
| Multi-asset scan (7 combos) | All negative Sharpe | 2026-05-27 |
| LightGBM 33 features (1/5/10/24 bar) | AUC 0.49-0.55, all trading negative | 2026-05-27 |
| Funding rate contrarian | Sharpe -2.58 (0.01%), too sparse at higher thresholds | 2026-05-27 |
| Funding rate momentum | Sharpe +0.91, 76 signals (marginal) | 2026-05-27 |
| Buy-and-hold 2yr BTCUSDT | Sharpe +0.34, Return +10.85% | 2026-05-27 |
