---
goal: Adapt CCXT and Binance synchronous connectors to arq+Valkey async pipeline
stage: architect-to-coder
date_created: 2026-05-23
last_updated: 2026-05-23
owner: Quant Research Architect
status: 'Ready'
tags: [handoff, quant, ingestion, arq, asyncio]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Ingestion Adapters Refactor Plan

## Context Retrieved
- **Architecture Strategy**: `arq` + Valkey for orchestration. TimescaleDB for curated storage. Minimal architecture, research speed first. Parquet is strictly deprecated in the raw ingest zone.
- **Problem**: Adapter logic currently mixes synchronous I/O and synchronous CPU-bound operations (Pandas) inside async functions. `BinanceConnector` depends on `ThreadedWebsocketManager` (which spawns background threads) that must bridge safely to the `arq` async event loop.
- **Goal**: Refactor `src/flipper_agent/ingestion/adapters/*.py` to ensure high-performance, non-blocking ingestion.

## Objective
Update existing connectors (`CCXTAdapter`, `BinanceNativeAdapter`) to operate natively inside an `arq` async worker without blocking the event loop. Safely bridge thread-based elements to the `asyncio` domain.

## Scope Boundaries
- **In Scope**: Modifying `BinanceNativeAdapter` and `CCXTAdapter` historical REST functions. Adding an event loop bridge for `ThreadedWebsocketManager` in the Binance adapter.
- **Out of Scope**: We are not changing the core Pydantic validation schemas. We are not modifying the TimescaleDB `asyncpg` bindings—only adapting the adapter classes to correctly yield data back to the orchestration layer.

## Affected Symbols, Modules, and Execution Flows
- `src/flipper_agent/ingestion/adapters/crypto_ccxt.py`: `CCXTAdapter.get_historical_ohlcv`
- `src/flipper_agent/ingestion/adapters/binance_native.py`: `BinanceNativeAdapter.get_historical_ohlcv` and WebSocket listener integrations.

## Data Contracts or Interfaces
1. **Sync-to-Async Isolation**: All CPU-intensive data transformations (Pandas DataFrame allocation, `pd.to_numeric()`, renaming columns) and synchronous network I/O MUST be unified in a private synchronous function. This function will be dispatched via `await asyncio.to_thread()`.
2. **Thread-to-Asyncio Bridging**: Threaded callbacks from Binance web sockets must use `asyncio.get_running_loop().call_soon_threadsafe(queue.put_nowait, msg)` to push messages into an `asyncio.Queue` accessible by the main `arq` task.

## Implementation Order
1. **Refactor `BinanceNativeAdapter.get_historical_ohlcv`**:
   - Extract the `self.client.klines` REST fetch and the entire Pandas DataFrame generation logic into a private sync method (e.g. `_fetch_and_parse_klines_sync(symbol, timeframe, **params)`).
   - In `<get_historical_ohlcv>`, simply return `await asyncio.to_thread(self._fetch_and_parse_klines_sync, ...)`.
   - This ensures Pandas CPU work and sync networking happens off the `arq` loop.

2. **Refactor `CCXTAdapter.get_historical_ohlcv`**:
   - The current implementation invokes `await self.exchange.fetch_ohlcv`. This is fine as it's truly async natively.
   - However, the subsequent DataFrame assembly is sync/CPU-bound. Extract DataFrame instantiation (`pd.DataFrame(ohlcv, ...)`) into a quick private sync method and execute it via `asyncio.to_thread` if the payload limit is large, yielding the loop back.

3. **Implement WebSocket Bridging for Binance (`BinanceNativeAdapter`)**:
   - Create an async consumption method `stream_multiplex_socket(symbols: list, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue)`.
   - Initialize the `ThreadedWebsocketManager`.
   - In the callback function provided to the manager, safely push the record: `loop.call_soon_threadsafe(queue.put_nowait, message)`.
   - Start the manager background threads.
   - Using a `while True:` loop inside the wrapper `arq` coroutine, block via `msg = await queue.get()`. This async generator/consumer feeds valid frames forward to Pydantic and `.jsonl.gz`/TimescaleDB. 

## Acceptance Criteria
- [ ] No `pandas` operations occurring directly on the main event thread inside `adapters`.
- [ ] CCXT networking retains `async_support` but DataFrame mapping is deferred to threads if payloads surpass 10,000 bounds.
- [ ] Binance UMFutures REST networking runs entirely in background threads alongside its Pandas casting.
- [ ] Threaded websocket callbacks inject natively into `asyncio.Queue` via `call_soon_threadsafe`.

## Validation Checklist
- The application starts without event loop block warnings (e.g., `asyncio debug` shows no task took > 100ms).
- Adapters return perfectly formatted Pandas DataFrames as before.
- The `ThreadedWebsocketManager` continuously feeds the `asyncio.Queue` without GIL blocking or memory leaks.

## Explicit Non-Goals
- We are not rewriting CCXT to use synchronous methods. We use `ccxt.async_support` natively where possible. 
- We are not migrating Binance to an async-native websocket client right now; we MUST use the provided `um_futures.websocket.ThreadedWebsocketManager` to maintain stability with the SDK, we just adapt it to `arq`.
