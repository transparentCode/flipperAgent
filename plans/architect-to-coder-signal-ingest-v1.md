# Architect to Coder Handoff: Signal App Indicator Ingestion

## 1. Intent & Scope
**Objective:** Connect the decoupled `ingestion_app` websocket pipeline directly into the `IndicatorRegistry` running inside `apps/signal_app`.
**Scale/Depth:** Build a Valkey Stream consumer within `signal_app` that automatically identifies active symbols and timeframes, loads their hyperparameters via the `ConfigManager`, pre-warms the internal state via `.prime()`, and triggers `.update()` correctly upon `on_bar_close` events.

## 2. Target Architecture
```text
/apps
  /signal_app
    signal_worker.py        <-- Consumer loop for market data
    feature_manager.py      <-- Handles Prime + Update state wrapping
```

## 3. High-Level Requirements

### A. The Signal Worker (`signal_worker.py`)
- Read from Valkey via `XREADGROUP` utilizing `market_data:{asset}:{timeframe}` streams.
- Identify when incoming streamed events flag as `bar_closed: true`.
- Dispatch the parsed `(high, low, close, volume, timestamp)` tuple payload natively to the `FeatureManager`.

### B. The Feature Manager (`feature_manager.py`)
- **Initialization:** During boot, dynamically load all configured indicators from `configs/base.yaml` for a stream's asset/timeframe using `libs.common.config.ConfigManager`.
- **Pre-warming (`.prime()`):** Before accepting live websocket updates, retrieve the historical DB records spanning $N$ bars (`max(curr_indicator.lookback_required)`) and parse them through `.prime()`.
- **Event Processing:** Accept incoming tuples and execute `.update()` sequentially across the warmed array of indicators in RAM $O(1)$. 
- **Parity Defense:** Any indicator that returns internal errors during `.update()` must forcefully un-prime and raise a severe pipeline warning.

## 4. Parity/Testing Requirements
- Provide `tests/integration/signals/test_feature_manager.py`.
- Mock a Valkey message payload. Test that calling `feature_manager.process_tick()` successfully updates all instantiated indicator models without state leaks.
