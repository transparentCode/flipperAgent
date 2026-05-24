---
goal: 'Design Phase 6: E2E Integration Testing via Mocking'
stage: 'architect-to-coder'
date_created: '2026-05-24'
owner: 'Quant Research Architect'
status: 'Ready'
tags: ['handoff', 'quant', 'testing', 'pytest', 'mocking']
target_agent: 'Coder Agent'
---

# Objective
Implement end-to-end integration testing for the ingestion pipeline. Crucially, this must run entirely in-memory using strict mocking (via `pytest-mock` and `unittest.mock`), avoiding any dependency on real Docker containers, database instances (TimescaleDB), or message brokers. 

# Scope Boundaries
**In Scope:**
- Full synthetic flow testing: from the exchange adapter to storage endpoints.
- Mocking external HTTP/WebSocket responses from exchanges (Binance, CCXT).
- Data normalization validation through Pydantic models.
- Orchestration workflow testing (schedules, tasks).
- Mocking the asyncpg connection pool and `aiofiles` in the storage layer.
- Retries and backoff validation (verifying `tenacity` logic handles rate limits properly).

**Out of Scope:**
- Real database container orchestration or testcontainers.
- Real network calls to external APIs.
- Performance or latency benchmarking (this is structural validation).

# Affected Modules and Flows
- `pyproject.toml` (addition of pytest deps if missing)
- `tests/ingestion/conftest.py` (Mock fixtures for DB and API responses)
- `tests/ingestion/test_e2e_mocked.py` (New test file)
- Execution Flow: Adapter Fetch -> Model Validation -> Task Orchestration -> Storage Insertion.

# Dependencies
Ensure the following exist in `pyproject.toml` or `requirements.txt`:
- `pytest`
- `pytest-asyncio`
- `pytest-mock`

# Implementation Order
1. **conftest.py Expansion**: Introduce globally accessible, reusable fixtures for mocking `asyncpg.create_pool` (or specifically the pool object inside the arq `ctx`), `aiofiles.open`, and network clients (`aiohttp.ClientSession` or specific CCXT methods). 
2. **Adapter Mocking**: Engineer fixtures that emit realistic synthetic JSON/payloads simulating exchange WebSocket/HTTP tick data.
3. **Storage Mocking**: Implement spying on the mocked database connections to ensure exact insert SQL queries and parameter bindings execute correctly (`executemany`).
4. **E2E Test Construction**: Build the E2E tests linking the mocked adapter yields into the orchestration loop and asserting the mocks at the storage layer are called with the correctly validated Pydantic models.
5. **Backoff/Retry Tests**: Explicitly test adapter rate-limit exceptions (`ccxt.RateLimitExceeded`) and verify that the `tenacity` logic processes the backoff correctly without crashing the orchestration task.

# Key Test Cases
- **Standard Ingestion Flow**: 
  - *Given* a mocked Binance HTTP/CCXT response.
  - *When* the orchestration worker runs the `run_rest_gap_fill` or standard poll task.
  - *Then* the raw data is normalized via `TickRecord` / `OHLCVRecord`, and the mocked `asyncpg` execution is called exactly once with the transformed parameters.
- **Rate Limit Backoff Validation**:
  - *Given* an adapter configured to raise a `ccxt.RateLimitExceeded` error on the first two calls, and succeed on the third.
  - *When* the task is invoked.
  - *Then* the `tenacity` retry logic pauses safely, retries, and upon success, the DB mock receives the insertion call. No crash occurs.
- **Invalid Payload Rejection**:
  - *Given* a mocked exchange response with missing mandatory fields.
  - *When* the adapter hands off to Pydantic.
  - *Then* a validation error is caught, the event is rejected, logged, and the mocked database is *not* called.

# Acceptance Criteria
- [ ] Pytest runs synchronously and completes successfully on a clean environment instantly.
- [ ] 100% of the ingestion pipeline path is traversed without creating a real network or database connection.
- [ ] Mocks correctly assert the final `.executemany()` on the storage layer containing the expected normalized data attributes.
