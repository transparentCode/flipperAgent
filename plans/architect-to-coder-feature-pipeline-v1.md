# Architect to Coder Handoff: Traditional Feature Pipeline (Independent Microservice)

## 1. Intent & Scope
**Objective:** Build dynamic, heavily optimized Traditional Indicators (RSI, BB, ATR, MACD) inside a decoupled microservice structure.
**Scale/Depth:** The Feature Engineering app will act as a completely independent background processor executing its own `main.py` entrypoint. It receives market data **only** through Valkey Streams boundaries.

## 2. Core Dependencies
- Valkey (Broker / Event Streams) for inter-service communication.
- `polars` / `numpy` for Vectorized Batch processing inside the Feature container.

## 3. High-Level Requirements

### A. Independent Service Architecture (Valkey Streams)
Decouple Ingestion from Features entirely.
1. **The Event Feed:** Feature `main.py` runs a consumer loops connecting to Valkey.
2. **XREADGROUP Parsing:** Listen on a predefined stream key (e.g., `events:market:bar_1m`). Extract the `new_closed_bar` object pushed by the upstream Ingestion apps.
3. **Execution Routing:** On receipt, pass the bar to the stateful tracking systems (`Incremental Tracker`). Upon completion, emit an acknowledgment (`XACK`) to Valkey.

### B. The Hyperparameter Registry
The models must operate dynamically based on dynamic parameters.
1. Design `ParameterRegistry` that maps `(Asset, Timeframe, IndicatorName)` to specific tuning values matching market regimes.
2. Ensure Batch optimization functions provide explicit `compute_batch_features(df, params: dict)` interfaces to integrate with Optuna gracefully offline.

### C. Dual-Mode Parity (Batch vs Incremental)
1. **Math Core:** Under `features/indicators/core.py`.
2. **Batch Processor:** Utilizing `polars`-native rollups over historical arrays to output backtest-ready dataframes swiftly.
3. **Incremental Tracker:** Execution path for live mode. A state machine offering:
   - `prime(historical_bars)`: Sync state convergence to prefeed live indicators accurately.
   - `update(new_closed_bar)`: Process incoming stream events in $O(1)$ directly off the Valkey consumer loop hook.

## 4. Required Implementation Steps

### Phase 1: Directory Setup & Monorepo Migration
- [ ] Implement the newly approved top-level layout: `apps/` and `libs/`.
- [ ] Migrate the existing ingestion codebase into `apps/ingestion_app/` and shared utilities into `libs/common/`, `libs/valkey_bus/`, and `libs/contracts/`.
- [ ] Setup `libs/features/` to hold the pure mathematical indicators and parameter registry.
- [ ] Setup `apps/signal_app/` as the execution boundary for the feature pipeline.

### Phase 2: Implementation 
- [ ] Code `apps/signal_app/main.py` orchestrating Valkey Streams connectivity.
- [ ] Translate fundamental `Indicator` base classes inside `libs/features/` covering dual parity modes.
- [ ] Include an implementation (e.g. `CustomRSI`) utilizing parameter sets injected by `ParameterRegistry`. 

### Phase 3: Parity Testing
- [ ] Target `tests/integration/features/test_indicator_parity.py`. Emulate a Valkey consumer stream feeding single bars sequentially over 10K events and assert output precision matches an equivalent 10K Polars batch rollup identically.

## 5. Exit Criteria & Quant Constraints
The Ingestion codebase cannot import Feature logic, and Feature code cannot import Ingestion logic. Valkey remains the unique data bus. Validation requires strict precision parity between offline Batch runs answering to Optuna optimizations against real-time streams answering incrementally to the broker. 
