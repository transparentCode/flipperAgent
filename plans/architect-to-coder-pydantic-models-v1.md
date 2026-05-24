---
goal: Design Pydantic validation models for Data Normalization phase
stage: architect-to-coder
date_created: 2026-05-23
last_updated: 2026-05-23
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, ingestion, pydantic, data-normalization]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect to Coder Handoff: Pydantic Validation Models for Data Normalization

## Objective
Design and implement robust Pydantic validation models for the Data Normalization phase of the ingestion engine. These models must guarantee point-in-time correctness by enforcing strict UTC datetime coercion for TimescaleDB partitioning keys, apply strict numeric bounds to trading variables, and seamlessly unify data structures emitted by `BinanceNativeAdapter`, `CCXTAdapter`, and `TradingViewSocketInterceptor`.

## Scope Boundaries
- **In Scope:**
  - Creation of a Base Pydantic model with immutable UTC datetime enforcement.
  - Creation of schema sub-models for OHLCV, ticks, and Open Interest.
  - Implementation of bridging logic (factories, pre-validators, or alias mapping) to gracefully parse output dictionaries from CCXT, Binance futures, and TradingView interceptors.
- **Out of Scope:**
  - Writing TimescaleDB integration/SQL code (handled later in `timescaledb_client.py`).
  - Connection management for Valkey or the Adapters.
  - Output formats to ephemeral Parquet (expressly banned per architecture).

## Affected Symbols, Modules, and Execution Flows
- **Files/Modules:**
  - `src/flipper_agent/ingestion/models/base_models.py` (New/Update)
  - `src/flipper_agent/ingestion/models/tick_models.py` (New/Update)
- **Execution Flows:**
  - Normalization flow constraint: Immediately after adapters yield Pandas DataFrames or JSON dicts, data routes via `.to_dict('records')` (or dict generators) into these Pydantic models before TimescaleDB bulk-upsert execution.

## Data Contracts or Interfaces

### 1. Base Structure & Point-in-Time Enforcement
- **`BaseDataModel` (in `base_models.py`):**
  - Inherits from `pydantic.BaseModel`.
  - Defines the core partitioning key: `timestamp: datetime`.
  - Employs a pre-validator (`@model_validator(mode='before')` or `@field_validator`) to enforce UTC. If the input is a float/int (milliseconds or seconds) or naive string, it must be coerced to a timezone-aware UTC datetime.

### 2. Strict Entity Models
- **`OHLCVRecord` (in `tick_models.py`):**
  - Fields: `symbol` (str), `timestamp` (datetime UTC), `open` (float), `high` (float), `low` (float), `close` (float), `volume` (float).
  - Validation: Positive numeric coercion for price & volume (`gt=0` or `ge=0`). High must be >= Low (implement carefully to avoid massive serialization overhead, or rely strictly on value bounds).
- **`TickRecord` (in `tick_models.py`):**
  - Fields: `symbol` (str), `timestamp` (datetime UTC), `price` (float, gt=0), `size` (float, gt=0), `side` (Literal['buy', 'sell', 'unknown']).
- **`OIRecord` (in `tick_models.py`):**
  - Fields: `symbol` (str), `timestamp` (datetime UTC), `open_interest` (float, ge=0).

### 3. Source Bridging & Mappers
Adapters output slight structural differences. The models must bridge these seamlessly:
- **CCXT Outputs:** Often OHLCV arrays (timestamp in ms, open, high, etc.). Code must unroll or map positional indices if fed raw, or map Pandas dataframe column keys gracefully.
- **Binance Native Futures (`UMFutures`):** Dicts containing distinct string-keys (e.g. `'o'`, `'h'`, `'c'`, `'l'`, `'v'`, open interest `'openInterest'`).
- **TradingView Interceptor:** Websocket payloads may include arbitrary nested JSON requiring flatten pre-validators.
- **Implementation Mechanism:** Use Pydantic's `AliasChoices` (e.g., `Field(validation_alias=AliasChoices('close', 'c', 'price'))`) or a `@model_validator(mode='before')` that remaps keys internally before strict typing is applied.

## Implementation Order
1. **Base Framework:** Scaffold `BaseDataModel` in `base_models.py` ensuring exhaustive datetime validation paths (float ms, float s, iso format strings).
2. **Entity Models:** Develop `OHLCVRecord`, `TickRecord`, and `OIRecord` in `tick_models.py` with tight floating-point boundaries.
3. **Cross-Adapter Aliasing:** Equip the entity models with `validation_alias` definitions or bridging factories that handle the exact raw JSON output shapes of Binance and TradingView.
4. **Testing Coverage:** Provide unit tests in `tests/ingestion/models/` exposing the models to mock data dumps from CCXT, Binance, and TradingView to confirm validation parity.

## Acceptance Criteria
- [ ] All normalized records guarantee a timezone-aware `datetime` object configured explicitly to UTC.
- [ ] Negative values in OHLCV, Tick, or OI structures instantly trigger `ValidationError` and drop the record safely.
- [ ] `BinanceNativeAdapter`, `CCXTAdapter`, and `TradingViewSocketInterceptor` dictionary outputs can be fed directly to the models (`**kwargs`) without external restructuring logic.
- [ ] Output from `.model_dump()` strictly conforms to types required by `asyncpg` bindings (int, float, datetime.datetime).

## Validation Checklist
- Confirm edge case timestamps (e.g., strings lacking 'Z', floats representing microsec vs. millisec) parse strictly to UTC without raising `ValueError` improperly.
- Verify robust casting of float strings (`"41000.5"`) commonly output by exchange websockets API payloads.
- Ensure the models do not invoke substantial performance degradation; profiling may be required if data load > 5K ticks/sec.

## Explicit Non-Goals
- Direct connection to or DDL schema management for TimescaleDB.
- Designing routing queues or valkey tasks.
- Validation of any aggregated technical indicators alongside raw inputs.
