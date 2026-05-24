---
goal: 'Design Phase 4: TimescaleDB schema & JSONL Sinks'
stage: 'architect-to-coder'
date_created: '2026-05-23'
owner: 'Quant Research Architect'
status: 'Ready'
tags: ['handoff', 'quant', 'ingestion', 'timescaledb', 'asyncpg', 'storage']
target_agent: 'Coder Agent'
---

# Architect-to-Coder Handoff: The Storage Layer (Phase 4)

## Objective
Implement Phase 4 of the Ingestion Engine: The Storage Layer. This layer serves as the single source of truth for all ingestion paths, permanently retiring the usage of Parquet in the raw extraction zone. It relies on TimescaleDB for highly optimized time-series storage and `asyncpg` for non-blocking asynchronous bulk-upserts. It also implements an ephemeral `.jsonl.gz` writer pattern for WebSocket disaster recovery.

## Architectural Requirements

### 1. TimescaleDB Hypertables
The primary storage will utilize PostgreSQL + TimescaleDB. 
- **Requirement:** Create initialization scripts (e.g., `src/flipper_agent/ingestion/storage/schema.sql`) explicitly establishing hypertables chunked by `timestamp`.
- **OHLCV Schema:** `timestamp` (TIMESTAMPTZ, PK), `symbol` (TEXT, PK), `timeframe` (TEXT, PK), `open` (FLOAT), `high` (FLOAT), `low` (FLOAT), `close` (FLOAT), `volume` (FLOAT).
- **Tick Schema:** `timestamp` (TIMESTAMPTZ, PK), `symbol` (TEXT, PK), `side` (TEXT), `price` (FLOAT), `size` (FLOAT).
- **Constraint:** Call `SELECT create_hypertable('ohlcv', 'timestamp', migrate_data => true);` for each table.

### 2. Asyncpg Bulk-Upsert Implementation (`timescaledb_client.py`)
- **Connections:** Do not spin up connection pools dynamically on each request. Accept a shared `asyncpg.Pool` or `asyncpg.Connection` (provided by `arq`'s `ctx` context initialization).
- **Idempotency:** Define SQL methods utilizing `executemany()` for batch insertion. Use `INSERT INTO ... ON CONFLICT (timestamp, symbol, timeframe) DO UPDATE SET ...` to overwrite partial ticks cleanly instead of failing uniquely.

### 3. Ephemeral Backup Sinks (`ephemeral_writer.py`)
- **Purpose:** Serve as a short-term, disk-based raw drop zone if `arq` tasks fail or DB falls out of sync.
- **Pattern:** Create an `async` writer using `aiofiles`. It should append dynamically to `data/raw_sockets/YYYY-MM-DD_{stream}.jsonl.gz` inside a ThreadPool or using `aiofiles`.

## Execution Steps for Coder Agent
1. **Repository Setup**: Create `src/flipper_agent/ingestion/storage/` module holding `timescaledb_client.py` and `ephemeral_writer.py`.
2. **Setup Schema**: Write a raw `schema.sql` file that executes standard PostgreSQL + Timescale hypertable conversion.
3. **Database Client**: Use the `asyncpg` library to implement the async repository (e.g. `TimescaleClient`) capable of taking a list of Pydantic models (e.g., `OHLCVRecord`), converting them to tuples, and mapping them into the database smoothly.
4. **WebSocket Backup**: Implement `EphemeralJSONLWriter` taking raw dictionaries and dumping gzip lines.

## Validation Check
- Test queries locally to ensure no race conditions block insertion streams.
- Ensure the JSONL writer rotates filenames daily dynamically instead of dumping one giant file per startup process.
