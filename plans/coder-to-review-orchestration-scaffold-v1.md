---
goal: Scaffold arq + Valkey orchestration layer for ingestion engine
stage: coder-to-review
date_created: 2026-05-23
last_updated: 2026-05-23
owner: GitHub Copilot (Coder Agent)
status: 'Ready'
tags: [handoff, quant, ingestion, orchestration, arq, valkey]
source_agent: Coder Agent
target_agent: Quant Review Agent
---

# Coder Execution Summary: Scaffold Orchestration Layer

## 1. Scope Executed
Scaffolded the `arq` + `Valkey` orchestration layer as defined in `plans/architect-ingestion-engine-design.md`, including:
- Created the orchestration module (`src/flipper_agent/ingestion/orchestration/`).
- Added necessary configuration files: `__init__.py`, `tasks.py`, `schedules.py`, `worker.py`.
- Integrated `arq` background tasks for data polling using simulated IO block (`asyncio.sleep`) and imported `BinanceNativeAdapter` and `CCXTAdapter` in the worker contexts.
- Updated python dependencies in `pyproject.toml` to include `arq` and `redis`.

## 2. Changes Made
- Modified `pyproject.toml` to add `arq>=0.25.0` and `redis>=5.0.0` dependencies.
- Added `src/flipper_agent/ingestion/orchestration/__init__.py`.
- Added `src/flipper_agent/ingestion/orchestration/tasks.py` defining placeholder tasks (`poll_binance_ohlcv`, `poll_funding_rates`).
- Added `src/flipper_agent/ingestion/orchestration/schedules.py` binding rules for task execution using `arq.cron`.
- Added `src/flipper_agent/ingestion/orchestration/worker.py` defining `WorkerSettings`, connecting Context `ctx` with adapters initialization.

## 3. Blast Radius Considered
- **Dependencies:** Modified `pyproject.toml`, which downstream installations will need to re-install.
- **Adapters:** Imported existing classes `BinanceNativeAdapter`, `CCXTAdapter` structurally without altering their core base functionalities.

## 4. Validation Performed
- Validated structural correctness of Python components in `src/flipper_agent/ingestion/orchestration/` module directory.
- `grep` checks confirming `BinanceNativeAdapter` and `CCXTAdapter` exist matching imports configuration.

## 5. Not Changed
- No core strategies, data payloads architecture, schemas, or models have been altered.
- Adapter components source codes (`binance_native.py`, `crypto_ccxt.py`) remain unmodified.

## 6. Risks or Follow-up Items
- **TimescaleDB Hook Context**: Mocked initializing TimeScaleDB within the worker startup function. Real initialization configuration string will need replacing downstream.
- **Docker Compose Setup**: Ensure `valkey` is correctly available matching standard valkey host settings (at `localhost:6379`) during runtime if workers are started.
- Need to run `pip install -e .` or `poetry install` or equivalent for syncing new dependencies from pyproject.toml locally.
