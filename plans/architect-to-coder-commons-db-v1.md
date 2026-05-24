---
goal: 'Extract DB Connection Pools to Commons'
stage: 'architect-to-coder'
date_created: '2026-05-24'
owner: 'Quant Research Architect'
status: 'Ready'
tags: ['handoff', 'quant', 'architecture', 'refactor', 'timescaledb', 'asyncpg']
target_agent: 'Coder Agent'
---

# Architect-to-Coder Handoff: Extraction of DB Infrastructure to Commons

## Objective
Refactor the PostgreSQL/TimescaleDB connection pool management out of the `ingestion` module and into a shared `commons` module. This allows subsequent components (Feature Generation, Backtesting, Live Trading) to safely share the connection pool lifecycle without duplicating infra code or exhausting DB connection limits.

## Scope Boundaries
- **In-Scope**: Extracting `asyncpg.Pool` creation, lifecycle events (startup/shutdown), and config mapping into `src/flipper_agent/commons/db/` (or `commons/storage/`).
- **In-Scope**: Separating Reader and Writer pool concepts for future CQRS topologies.
- **Out-of-Scope**: Do not touch `schema.sql` or `tick_data`/`ohlcv` specific query structures; those belong intrinsically to `ingestion/storage/`.

## Affected Symbols & Modules
- `src/flipper_agent/ingestion/orchestration/worker.py` (Remove db connection lifecycle logic from arq ctx directly, delegate to commons).
- `src/flipper_agent/commons/` (New directory `db/` with connection singletons/managers).
- `src/flipper_agent/ingestion/storage/timescaledb_client.py` (Refactor to accept the generic pool manager context).

## Proposed Modules
```text
src/flipper_agent/commons/db/
├── __init__.py
├── pool_manager.py   # Handles `asyncpg.create_pool` with centralized config
└── base_client.py    # (Optional) Base context manager or health-checks
```

## Data Contracts & Interfaces
- `pool_manager.py` must expose easy `get_writer_pool()` and `get_reader_pool()` accessors (even if they point to the same host in v1).
- `TimescaleClient` in ingestion should take the pool instances passed down via DI or fetched carefully.

## Implementation Order
1. Extract configuration for Postgres (User, PW, Host, Port) into `commons/config.py` explicitly if missing.
2. Create `commons/db/pool_manager.py` and implement lifecycle hooks (`init_pools`, `close_pools`).
3. Refactor `worker.py` (the `arq` orchestration entrypoint) to invoke `init_pools` on startup.
4. Refactor `timescaledb_client.py` to point to the new pattern if necessary without changing query structures.

## Acceptance Criteria
- [ ] Database config is securely sourced in commons.
- [ ] Reader/Writer task pools can be initialized generically across any module.
- [ ] Ingestion ingestion functions remain intact and strictly domain-scoped.
- [ ] Tests for the generic DB pool initialization are operational.

## Validation Checklist
- Connection starvation is resolved (tests do not hang due to max pool limits).
- Circular dependency checks pass (ingestion depends on commons, commons DOES NOT depend on ingestion).
