---
goal: Configure per-asset websockets and DB gap_fills for specific timeframes instead of universally assuming 1m.
stage: architect-to-coder
date_created: 2026-05-24
last_updated: 2026-05-24
owner: Quant Research Architect
status: Ready
tags: [handoff, ingestion, websocket, architecture]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect to Coder Handoff: Configurable Timeframes

## 1. Context & Objective
Currently, `base.yaml` requires all target assets to stream and write data using a single hardcoded `1m` interval (`binance_stream_interval: 1m`). 
The objective is to allow configuring specific timeframes for each asset. For example, `BTCUSDT` gets `1m` and `1h`, whereas `ETHUSDT` gets just `4h`. This needs to seamlessly multiplex over the binance websocket stream adapter and correctly route to the database without forcing unnecessary historical backfill checks.

## 2. Approach & Architecture
We will transition from a list-based `target_list` configuration to a dictionary-based `target_timeframes` configuration in `configs/base.yaml`. The orchestration pipeline logic will load this structured configuration and correctly multiplex socket channels per asset.

*   `target_list` will be replaced or supplemented by `target_timeframes`.
*   The `verify_and_launch_ws` logic will verify the shortest *configured* timeframe for the asset, rather than assuming it's always checking the `base_gap_fill: 1m` interval.
*   The `run_websocket_pipeline` will use the specific list of configured timeframes to register multiplex channels cleanly in Binance adapter.

## 3. Scope Boundaries
**IN SCOPE**:
*   `configs/base.yaml` ingestion asset list configuration updates.
*   `controller.py` Verification gate (`verify_and_launch_ws`) and WS runner (`run_websocket_pipeline`).
*   `binance_native.py` adapter configuration interpolation.

**OUT OF SCOPE**:
*   Historical gap fill routines (REST APIs) - this only addresses the websocket integration logic.
*   Other Exchange integrations.

## 4. Proposed Modules / Services
**`configs/base.yaml`**:
```yaml
ingestion:
  assets:
    target_timeframes:
      BTCUSDT: ["1m", "1h"]
      ETHUSDT: ["4h"]
      SOLUSDT: ["1m", "15m"]
```

**`controller.py`**:
*   `verify_and_launch_ws(symbol: str, timeframes: List[str], arq_pool: ...)`
    *   Instead of checking `base_timeframe = "1m"`, it should find the minimum timeframe string from `timeframes` (e.g., if checking `["1h", "1d"]` check `1h`). Note: `base_gap_fill` config fallback can still occur if needed.
*   `run_websocket_pipeline(symbol: str, timeframes: List[str])`
    *   Initialize the Binance adapter to multiplex the specific `timeframes` passed from the configuration instead of hardcoding `1m` inside the adapter.

**`binance_native.py`**:
*   `stream_multiplex_socket` method signature should be updated:
    *   `async def stream_multiplex_socket(self, symbols_timeframes: Dict[str, List[str]], loop, queue)` 
    *   Iterate keys and values to generate `streams` array: `"{symbol.lower()}@kline_{tf}"`

## 5. Affected Symbols, Modules, and Execution Flows
- **Impacts**: Real-time websocket ingestion pipeline in `controller.py`.
- **Flows**: Verification loop -> `run_websocket_pipeline` -> `stream_multiplex_socket` data generation -> DB & Valkey publish.
- **DB/Valkey scale nicely**: Since `OHLCVRecord` database writer and `valkey` publisher already pull `timeframe` directly from the Binance message payload (`msg["data"]["k"]["i"]`), no downstream changes are needed in `TimescaleWriter`.

## 6. Implementation Order
1. Update `configs/base.yaml` with the new schema format (`target_timeframes`).
2. Update `main.py` or the `controller.py` entrypoint to parse the new `Dict` and pass it down.
3. Modify `verify_and_launch_ws` and `run_websocket_pipeline` in `controller.py` to accept the timeframe configs.
4. Refactor `stream_multiplex_socket` in `binance_native.py`.
5. Run the existing ingestion tests to ensure configuration schema and multiplexing streams logic holds up.

## 7. Acceptance Criteria
- [ ] Users can map a list of intervals per asset in the config.
- [ ] WebSocket correctly generates multiplex subscription names for all asset/timeframe combinations.
- [ ] Gate loop does not block indefinitely looking for a `1m` catchup when `1m` is not configured for the asset.

## 8. Validation Checklist (Coder)
- Confirm `TimescaleWriter.insert_ohlcv` is effectively handling multi-timeframes simultaneously.
- Verify `reconnect` logic properly restarts utilizing `timeframes` configs.
