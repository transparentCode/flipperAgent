---
goal: Configure per-asset websockets to publish close candle events for specific timeframes while retaining 1m as the base ingestion timeframe.
stage: architect-to-coder
date_created: 2026-05-25
last_updated: 2026-05-25
owner: Quant Research Architect
status: Ready
tags: [handoff, ingestion, websocket, architecture]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect to Coder Handoff: Configurable Publish Timeframes (v2)

## 1. Context & Objective
The user rejected the previous architectural design. The requirement is NOT to replace `1m` as the base timeframe, but to **continue using `1m` as the base timeframe for all assets** while allowing specific higher timeframes (e.g., `1h`, `4h`) to be configured per asset for the purpose of publishing "closed candle" events to the Valkey event bus. 

By subscribing to both the `1m` base and the configured higher timeframes directly from the exchange (like Binance), we ensure we get the official exchange candle close events for those higher timeframes without having to build complex chronological groupers internally.

## 2. Approach & Architecture
We will update `configs/base.yaml` to include a mapping of `publish_timeframes` per asset.

*   `1m` remains the universal base timeframe for system verification and base data storage.
*   The Binance adapter will subscribe to `1m` AND any target `publish_timeframes` configured for the asset using stream multiplexing.
*   When a websocket message arrives and the candle is closed (`is_candle_closed` == True):
    1.  **Database Insertion:** ONLY `1m` closed candles are written to TimescaleDB. This prevents database bloat by avoiding redundant storage of higher timeframes that can be rolled up from 1m data.
    2.  **Valkey Publishing:** The event is ONLY published to the Valkey bus if `timeframe in target_publish_timeframes[symbol]`.

## 3. Scope Boundaries
**IN SCOPE**:
*   `configs/base.yaml` ingestion asset list configuration updates.
*   `controller.py` WebSocket runner and message routing/filtering logic for Valkey integration.
*   `binance_native.py` adapter configuration to subscribe to the union of `1m` and configured publish timeframes.

**OUT OF SCOPE**:
*   Changing the `1m` historical gap-fill logic or the gatekeeper check `verify_and_launch_ws`.
*   Replacing `1m` as the base interval.

## 4. Proposed Modules / Services
**`configs/base.yaml`**:
Introduce `publish_timeframes` under assets.
```yaml
ingestion:
  assets:
    target_list:
      - BTCUSDT
      - ETHUSDT
      - SOLUSDT
    publish_timeframes:
      BTCUSDT: ["1h", "4h"]
      ETHUSDT: ["4h", "1d"]
      # If an asset is in target_list but not here, it either publishes nothing or defaults to 1m based on business rules (let's assume it publishes nothing unless specified, or defaults to 1m if empty).
```

**`controller.py` / Data Router**:
*   `run_websocket_pipeline(symbol: str, publish_timeframes: List[str])`:
    *   Initialize the Binance adapter to multiplex the base `1m` stream + the strings in `publish_timeframes`.
*   **Valkey Publish Filter**: 
    ```python
    if is_closed:
        # 1. Insert ONLY 1m candles into TimescaleDB to prevent data bloat
        if timeframe == '1m':
            db_writer.insert(...)
        
        # 2. Filter Valkey publish
        if timeframe in configured_publish_timeframes.get(symbol, []):
            valkey_publisher.publish(f"stream:ohlcv:{symbol}:{timeframe}", payload)
    ```

**`binance_native.py`**:
*   `stream_multiplex_socket` logic is updated to accept a list of timeframes per symbol to generate the subscription strings (e.g., `btcusdt@kline_1m`, `btcusdt@kline_1h`).

## 5. Affected Symbols, Modules, and Execution Flows
- **Impacts**: Real-time websocket ingestion pipeline routing in `controller.py`.
- **Flows**: Binance stream generation -> Message parsing -> Optional Valkey publish based on timeframe matching.

## 6. Implementation Order
1. Update `configs/base.yaml` with the new schema format (`publish_timeframes`).
2. Update the configuration parser in `main.py` or the `controller.py` to pass the configured `publish_timeframes` dictionary down.
3. Refactor `stream_multiplex_socket` in `binance_native.py` to subscribe to `["1m"] + publish_timeframes`.
4. Update the message consumption loop in `controller.py` to gracefully insert ONLY the `1m` timeframe into the database, while conditionally publishing to Valkey based on the target `publish_timeframes`.
5. Run the existing ingestion tests to ensure configuration schema and Valkey filtering hold up.

## 7. Acceptance Criteria
- [ ] Websocket adapter automatically subscribes to `1m` + any configured `publish_timeframes`.
- [ ] Database ONLY records the `1m` closed candles, explicitly rejecting insertion of higher timeframes to prevent data bloat.
- [ ] Valkey bus ONLY receives event publishes for the specific `publish_timeframes` configured for that asset.

## 8. Validation Checklist (Coder)
- Confirm `TimescaleWriter.insert_ohlcv` is effectively bounded to `1m` candles and does not process other timeframes.
- Verify `1m` validation gate (`verify_and_launch_ws`) remains untouched and functional.
