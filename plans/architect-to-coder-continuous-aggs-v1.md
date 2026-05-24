---
goal: 'Design Phase 4+: Lambda Architecture, Gap Fill, and API Rate Limiting'
stage: 'architect-to-coder'
date_created: '2026-05-23'
owner: 'Quant Research Architect'
status: 'Ready'
tags: ['handoff', 'quant', 'ingestion', 'timescaledb', 'asyncpg', 'storage', 'rate-limiting']
target_agent: 'Coder Agent'
---

# Architect to Coder Handoff: Lambda Architecture & Gap Fill

## Objective
Implement Phase 4+ of the Ingestion Pipeline using a Lambda Architecture. Specifically, configure TimescaleDB continuous aggregates (1m bars), enforce a 30-day raw data retention policy on ticks, implement a REST gap-fill task using `arq`, and introduce robust API rate-limiting strategies to prevent bans when pulling data for multiple assets.

## Scope Boundaries
- **In Scope:** 
  - Modifying `schema.sql` in the storage layer to include Timescale DB continuous aggregates and retention policies.
  - Adding a scheduled REST gap-fill task (`arq` worker) that compares the latest ingested timestamps with the current time and pulls missing historical bars via CCXT/native adapters.
  - Implementing an explicit rate-limiting and chunking strategy for cron jobs that iterate over multiple assets.
- **Out of Scope:**
  - Changes to the WebSocket ingestion (Phase 1-3) beyond ensuring it works alongside the gap-fill.
  - Adding entirely new exchanges outside of the currently supported ones.

## Affected Symbols, Modules, and Execution Flows
- `src/flipper_agent/ingestion/storage/schema.sql`: Structure changes (aggregates & retention).
- `src/flipper_agent/ingestion/orchestration/tasks.py` & `schedules.py`: New gap fill jobs.
- `src/flipper_agent/ingestion/adapters/*`: Ensuring REST fetch methods natively support async sleeps or chunking configurations.

## Data Contracts or Interfaces
### 1. `schema.sql` Updates
```sql
-- 1. Continuous Aggregate for 1-minute bars
CREATE MATERIALIZED VIEW market_1m_bars
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    time_bucket('1 minute', timestamp) AS bucket,
    FIRST(price, timestamp) AS open,
    MAX(price) AS high,
    MIN(price) AS low,
    LAST(price, timestamp) AS close,
    SUM(size) AS volume
FROM ticks
GROUP BY symbol, bucket;

-- 2. Add continuous aggregate refresh policy
SELECT add_continuous_aggregate_policy('market_1m_bars',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute');

-- 3. Add 30-day retention on raw ticks
SELECT add_retention_policy('ticks', INTERVAL '30 days');
```
*(Note: Adjusted column names to match the Tick schema defined in earlier handoffs: `symbol`, `price`, `size`)*

### 2. Gap-Fill Task (`arq` Orchestration)
Signature for `run_rest_gap_fill`:
```python
async def run_rest_gap_fill(ctx, assets: list[str], exchange: str):
    """
    Checks the latest bucket in `market_1m_bars` for each asset.
    If latest bucket < current_time - 1m, fetches historical klines/trades 
    via REST to bridge the gap.
    """
```

### 3. API Rate Limiting Strategy
- **Layer 1: Built-in CCXT Safety:** Ensure `exchange.enableRateLimit = True` is passed at CCXT client initialization.
- **Layer 2: Async Chunking & Concurrency Limits:** Iterate over assets in batches using `asyncio.gather` with a semaphore (e.g., `asyncio.Semaphore(5)`).
- **Layer 3: Cross-Asset Sleep:** Add a base `asyncio.sleep(0.5)` between batched calls to explicitly avoid HTTP 429 warnings on bulk cron tasks. 
- **Layer 4: Retry Backoff:** Implement an exponential backoff decorator (like `tenacity`) for 429 / Rate Limit exceptions from the exchanges.

## Implementation Order
1. **Schema Updates:** Update `schema.sql` and run migrations on the Timescale database to establish the continuous aggregates and retention policies.
2. **Adapter Enhancements:** Ensure REST API methods in `crypto_ccxt.py` and `binance_native.py` handle backoffs seamlessly.
3. **Orchestration Task:** Build `run_rest_gap_fill` in `tasks.py` incorporating the concurrency semaphores and sleep logic.
4. **Cron Integration:** Add the gap-fill task to `schedules.py` running at a standard interval (e.g., every 5 minutes).

## Acceptance Criteria
- [ ] `schema.sql` cleanly applies without errors, continuous aggregates auto-refresh, and raw ticks > 30 days are dropped.
- [ ] Gap-fill job identifies missing periods, requests the data natively via REST, and writes it successfully to the database.
- [ ] When gap-filling for 100+ assets simultaneously, 0 HTTP 429 errors occur due to the combined semaphore, sleep, and backoff protections. 
- [ ] Tests exist to mock REST endpoints delivering 429s to prove the backoff triggers correctly.

## Validation Checklist
- Database indices properly cover the continuous aggregate queries.
- Look-ahead bias is prevented (no pulling incomplete current-minute bars prematurely).
- Rate limits behave properly when multiple `arq` gap-fill tasks fire close to one another or overlap (single-instance restriction or distributed locks recommended if scaling horizontally).
- `tenacity` retry logic properly respects retry intervals provided by `Retry-After` headers if present.