---
goal: Historical default backfilling via CCXT pagination
stage: architect-to-coder
date_created: 2026-05-24
last_updated: 2026-05-24
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, ingestion, historical]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Historical Data Pagination Plan

## Objective
Implement robust historical pre-warming based on a YAML configuration for backfilling depth, fetching past data through a chunked pagination strategy, bypassing the default CCXT fetch limits.

## Scope Boundaries
- **In Scope**: `configs/base.yaml`, `src/flipper_agent/ingestion/orchestration/tasks.py`.
- **Out of Scope**: Changes to the core CCXT adapter (`crypto_ccxt.py`) since the adapter already supports `since` and `limit`, schema changes, or database migrations.

## Affected Symbols, Modules, and Execution Flows
- **`configs/base.yaml`**: Adding configuration param `historical_backfill_days`.
- **`src/flipper_agent/ingestion/orchestration/tasks.py`**: Changes to the execution flow of `_fetch_asset_gap` logic which currently performs single fixed-window fetches.

## Data Contracts or Interfaces
- **YAML Configuration**:
  ```yaml
  ingestion:
    assets:
      historical_backfill_days: 30
    concurrency:
      gap_fill_sleep_seconds: 0.5
  ```
- **DB Interface**: Use `TimescaleReader(pool).get_max_timestamp(symbol, timeframe)` to detect `max_ts` existing in the DB.
- **CCXT Adapter**: Consume `await ccxt_adapter.get_historical_ohlcv(symbol, timeframe, since=start_ts, limit=1000)`.

## Implementation Order
1. **Configuration**: 
   - Add `historical_backfill_days: 30` to `configs/base.yaml` under `ingestion.assets`.
2. **`tasks.py` Enhancement**: 
   - Modify `_fetch_asset_gap(ctx, ccxt_adapter, symbol)`.
   - Calculate `backfill_days = config_manager.get("ingestion.assets.historical_backfill_days", 30)`.
   - Compute `since_ms` (now minus `backfill_days` in ms).
   - Use `TimescaleReader` to get `max_ts` from the database.
   - Set `start_ts = max(since_ms, max_ts)`. If no DB data, `start_ts = since_ms`.
   - Start a `while` loop to chunk fetches until `start_ts >= current_ms`.
   - Inside the loop:
     - Log chunk fetch start.
     - Call `ccxt_adapter.get_historical_ohlcv` with `since=start_ts` and `limit=1000`.
     - Normalize with `OHLCVRecord` Pydantic models.
     - Save chunk using `TimescaleWriter.insert_ohlcv`.
     - If `len(records) < 1000` or `len(records) == 0`, break the loop (we've caught up).
     - Otherwise, set `start_ts = records[-1].timestamp + 1` to move to the next chunk.
     - Sleep using `asyncio.sleep(config_manager.get("ingestion.concurrency.gap_fill_sleep_seconds", 0.5))` to respect the API rate limit.

## Acceptance Criteria
- Configuration specifies backfill duration.
- The `_fetch_asset_gap` function fetches multiple chunks backwards.
- Overlapping fetch handles DB duplication/upsert correctly (handled internally by Timescale setup or conflict ignoring depending on our current timescale setup, though TimescaleDB relies on standard upsert constraints).
- Concurrency limit strictly enforced, waiting per loop avoids HTTP 429 constraints breaking the ingestion engine altogether.
- Graceful termination of the gap-fetch loop when the dataset catches up to present.

## Validation Checklist
- [ ] Ensure that `start_ts >= current_time` exit condition is working correctly.
- [ ] Validate loop increments using `last_record.timestamp + 1`.
- [ ] Confirm no infinite loop occurs when an exchange API returns 0 elements for a future range.

## Explicit Non-Goals
- DO NOT rewrite the CCXT adapter connection management.
- DO NOT introduce multi-threading inside the CCXT adapter.
- DO NOT add backfilling logic for Trade (tick) data; restrict purely to OHLCV for now.
