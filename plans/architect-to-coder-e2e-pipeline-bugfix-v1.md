---
goal: Fix 2 critical ingestion→signal_app integration bugs + build full-pipeline E2E test infrastructure
stage: architect-to-coder
date_created: 2026-05-26
last_updated: 2026-05-26
owner: Quant Research Architect
status: 'Ready'
tags: [handoff, quant, e2e, docker, bug-fix, integration, pipeline]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect Handoff: E2E Pipeline Bug Fixes + Full-Pipeline E2E Tests

## Objective

Fix two critical integration bugs at the ingestion → signal_app boundary that prevent any data from flowing past ingestion, then extend the E2E test infrastructure to verify all 6 apps (ingestion → signal → strategy → risk → execution → portfolio) in Docker.

---

## 1. Change Categorization

### Category A: Bug Fixes (blocking — pipeline is broken without these)

| ID | Bug | File | Severity |
|----|-----|------|----------|
| B1 | Field name mismatch: ingestion publishes `is_closed`, signal_worker reads `bar_closed` | `src/apps/ingestion_app/orchestration/controller.py` | **CRITICAL** — signal worker silently drops ALL candles |
| B2 | Timestamp format mismatch: ingestion publishes ISO string, signal_worker does `float()` on it | `src/apps/ingestion_app/orchestration/controller.py` | **CRITICAL** — ValueError crashes signal worker on every message |

### Category B: E2E Test Infrastructure (non-blocking, but needed for validation)

| ID | Change | File(s) |
|----|--------|---------|
| E1 | Apply both schemas (ingestion + pipeline) in E2E bootstrap | `tests/e2e/run_e2e_tests.sh` |
| E2 | Start all 6+ services (not just ingestion) | `tests/e2e/run_e2e_tests.sh` |
| E3 | Add full-pipeline flow assertions | `tests/e2e/test_docker_integration.py` |

### Category C: Config Alignment (non-blocking, noted for awareness)

| ID | Issue | Impact |
|----|-------|--------|
| C1 | `ETHUSDT/1d` in `publish_timeframes` but no `ETHUSDT/1d` in `models.yaml` | Data published to `stream:ohlcv:ethusdt:1d` with no consumer — wasted bandwidth |
| C2 | `SOLUSDT/15m` in `publish_timeframes` but `SOLUSDT` absent from `models.yaml` entirely | Data published to `stream:ohlcv:solusdt:15m` with no consumer |

Category C items are **not** in scope for this handoff. They are harmless (orphan stream data) and should be resolved in a config alignment pass.

---

## 2. Bug Fix Specifications

### Bug 1: Field Name Mismatch (`is_closed` vs `bar_closed`)

**Root cause:** `controller.py` line 123 publishes `"is_closed": "True"`. `signal_worker.py` line 81 reads `payload.get(b"bar_closed")` / `payload.get("bar_closed")`. Different field names → `is_closed` is always `None` → signal worker treats every message as a non-closed bar → drops silently.

**Fix — two changes:**

#### Change 1a: Ingestion publisher (primary fix)

**File:** `src/apps/ingestion_app/orchestration/controller.py`
**Line 123:** Change the published field name from `is_closed` to `bar_closed`.

```python
# BEFORE (line 123)
"is_closed": "True",

# AFTER
"bar_closed": "True",
```

**Rationale:** `bar_closed` is the documented contract in `docs/signal_app.md` Section 5.1. The consumer was built to spec; the producer was not. Fix the producer.

#### Change 1b: Signal worker backwards-compat guard (defensive)

**File:** `src/apps/signal_app/signal_worker.py`
**Line 81:** Also accept the old `is_closed` field name for any messages already in-flight.

```python
# BEFORE (line 81)
is_closed = payload.get(b"bar_closed") or payload.get("bar_closed")

# AFTER
is_closed = (
    payload.get(b"bar_closed") or payload.get("bar_closed")
    or payload.get(b"is_closed") or payload.get("is_closed")
)
```

**Rationale:** If any old `is_closed` messages are sitting in Valkey streams from prior runs, the worker will still pick them up. This is a one-line safety net.

### Bug 2: Timestamp Format Mismatch (ISO string vs epoch float)

**Root cause:** `controller.py` line 117 publishes `record.timestamp.isoformat()` which produces `"2026-05-26T12:00:00+00:00"`. `signal_worker.py` line 93 does `_get_float("timestamp")` which calls `float("2026-05-26T12:00:00+00:00")` → **ValueError**.

The `record.timestamp` field is a `datetime` object (from `BaseDataModel.coerce_to_utc_datetime`). The rest of the pipeline uniformly expects epoch-seconds floats:
- `signal_worker.py:93` → `_get_float("timestamp")` → expects numeric string
- `strategy_worker.py:98` → `float(decoded.get("timestamp", 0))` → expects numeric string
- `risk_worker.py:196` → `float(decoded["timestamp"])` → expects numeric string

**Fix:**

**File:** `src/apps/ingestion_app/orchestration/controller.py`
**Line 117:** Publish epoch-seconds float instead of ISO string.

```python
# BEFORE (line 117)
"timestamp": record.timestamp.isoformat(),

# AFTER
"timestamp": str(record.timestamp.timestamp()),
```

**Explanation:** `record.timestamp` is a UTC-aware `datetime`. `.timestamp()` returns POSIX epoch-seconds as a `float` (e.g. `1716724800.0`). `str(...)` converts to `"1716724800.0"` which `float()` can parse downstream.

**Data flow after fix:**
1. Binance kline `t` = 1716724800000 (ms)
2. `OHLCVRecord(timestamp=1716724800000)` → `coerce_to_utc_datetime` → `datetime(2024-05-26, 12:00, tz=UTC)`
3. `record.timestamp.timestamp()` → `1716724800.0` (epoch seconds)
4. Published as `"1716724800.0"` → signal_worker `float("1716724800.0")` → ✓
5. Flows through features → strategy → risk as epoch-seconds float throughout

---

## 3. Additional Field/Format Mismatches Spotted

### Mismatch 3: `ingestion_timestamp` field — unused downstream

`controller.py` line 124 publishes `"ingestion_timestamp": str(now_utc)` (ms epoch). No downstream consumer reads this field. **Not a bug** — it's observability metadata. No action needed.

### Mismatch 4: Case sensitivity in stream keys vs feature keys

- Ingestion publishes to `stream:ohlcv:{symbol.lower()}:{timeframe}` → lowercase asset (e.g. `stream:ohlcv:btcusdt:1h`)
- Signal worker listens on `stream:ohlcv:{asset.lower()}:{timeframe}` → lowercase ✓ consistent
- Signal worker publishes to `features:{self.asset}:{self.timeframe}` → uses original case from `models.yaml` (uppercase, e.g. `features:BTCUSDT:1h`)
- Strategy worker listens on `features:{asset}:{timeframe}` → original case from `models.yaml` ✓ consistent

**No action needed.** Input streams use lowercase; feature/signal/order streams use original case. Both sides are consistent within their own convention.

---

## 4. E2E Test Infrastructure Design

### 4.1 Updated `tests/e2e/run_e2e_tests.sh`

**Changes from current:**

1. **Apply BOTH SQL schemas** — current script only applies `src/apps/ingestion_app/storage/schema.sql`. Must also apply `sql/pipeline_schema.sql` for risk/execution/portfolio tables.

2. **Start ALL services** — current script only starts `db`, `broker`, `worker-queue`, `worker-streams`. Must also start `signal-worker`, `strategy-worker`, `risk-worker`, `execution-worker`, `portfolio-worker`.

3. **Wait for all services to be healthy** — add container health polling for the new workers (check `docker-compose ps` or container logs for startup messages).

```bash
# Schema application order (after DB is ready):
cat $INGESTION_SCHEMA | docker-compose exec -T -e PGPASSWORD=flipperpass db psql -U flipper -d flipper_db
cat $PIPELINE_SCHEMA  | docker-compose exec -T -e PGPASSWORD=flipperpass db psql -U flipper -d flipper_db

# Service startup (after schemas):
docker-compose up -d --build worker-streams worker-queue signal-worker strategy-worker risk-worker execution-worker portfolio-worker

# Health wait: poll docker-compose ps for all containers to be running (not restarting)
```

**Full specification:**

```bash
#!/usr/bin/env bash
set -e

COMPOSE_FILE="docker-compose.yml"
INGESTION_SCHEMA="src/apps/ingestion_app/storage/schema.sql"
PIPELINE_SCHEMA="sql/pipeline_schema.sql"

echo "=== Tearing down previous run ==="
docker-compose down -v

echo "=== Starting infrastructure ==="
docker-compose up -d --build db broker

# ... existing pg_isready and Valkey PING loops (keep as-is) ...

echo "=== Applying schemas ==="
cat $INGESTION_SCHEMA | docker-compose exec -T -e PGPASSWORD=flipperpass db psql -U flipper -d flipper_db
cat $PIPELINE_SCHEMA  | docker-compose exec -T -e PGPASSWORD=flipperpass db psql -U flipper -d flipper_db

echo "=== Starting all workers ==="
docker-compose up -d --build worker-streams worker-queue signal-worker strategy-worker risk-worker execution-worker portfolio-worker

echo "=== Waiting for workers to stabilize (15s) ==="
sleep 15

echo "=== Running E2E tests ==="
if .venv/bin/python -m pytest tests/e2e/test_docker_integration.py -v --timeout=300; then
    echo "E2E tests passed."
    TEST_RESULT=0
else
    echo "E2E tests FAILED! Dumping logs:"
    docker-compose logs --tail=100 signal-worker
    docker-compose logs --tail=100 strategy-worker
    docker-compose logs --tail=100 risk-worker
    docker-compose logs --tail=100 execution-worker
    docker-compose logs --tail=100 portfolio-worker
    docker-compose logs --tail=50 worker-streams
    docker-compose logs --tail=50 worker-queue
    TEST_RESULT=1
fi

echo "=== Cleanup ==="
docker-compose down -v
exit $TEST_RESULT
```

### 4.2 Updated `tests/e2e/test_docker_integration.py`

**Keep all 3 existing tests unchanged** (they test ingestion correctness).

**Add new tests:**

#### Test: `test_signal_worker_consumes_and_produces`

```
Purpose: Verify signal_worker consumed from stream:ohlcv:* and produced to features:*

Steps:
1. Wait for existing gap-fill test to prove OHLCV data exists (dependency on test_timescaledb_initialization_and_gap_fill).
2. Connect directly to Valkey at localhost:6380.
3. Poll XINFO GROUPS on stream:ohlcv:btcusdt:1h — verify signal_app_group exists.
4. Poll XLEN on features:BTCUSDT:1h — wait for count > 0 (up to 120s).
5. If count > 0, read one entry via XRANGE and verify it has keys: asset, timeframe, timestamp, features, bar_data.
6. Assert features JSON is parseable and non-empty.

Timeout: 120s (signal worker must wait for ingestion to produce closed 1h bars).
```

#### Test: `test_strategy_worker_consumes_features`

```
Purpose: Verify strategy_worker created consumer group on features:* streams.

Steps:
1. Connect to Valkey at localhost:6380.
2. Poll XINFO GROUPS on features:BTCUSDT:1h — verify strategy_app_group exists.
3. (Optional) Check XLEN on signals:BTCUSDT:1h — may be 0 if models don't fire, that's OK.

Note: Strategy producing signals depends on model logic. The test verifies the worker is RUNNING and CONSUMING, not that it fires signals.
```

#### Test: `test_downstream_workers_running_no_errors`

```
Purpose: Verify risk, execution, portfolio workers are running without crash loops.

Steps:
1. Use subprocess to run: docker-compose ps --format json
2. Verify all worker containers show status "running" (not "restarting").
3. Use subprocess to capture docker-compose logs for each downstream worker.
4. Assert no Python traceback or "ERROR" lines in the logs (filter out expected startup warnings).

Note: These workers may not have data flow (risk only acts if strategy produces signals), but they must be alive.
```

#### Test: `test_consumer_groups_exist`

```
Purpose: Verify each app created its expected consumer groups on the right streams.

Expected groups:
- stream:ohlcv:btcusdt:1h → signal_app_group
- stream:ohlcv:btcusdt:4h → signal_app_group
- features:BTCUSDT:1h → strategy_app_group
- features:BTCUSDT:4h → strategy_app_group
- signals:BTCUSDT:1h → risk_app_group (may not exist if no signals produced)

Steps:
1. Connect to Valkey at localhost:6380.
2. For each stream/group pair, run XINFO GROUPS and check group_name exists.
3. Signal and feature groups are required. Signal-output groups are best-effort (check but don't fail).
```

### 4.3 Valkey Connection for E2E Tests

The test file needs a Valkey/Redis client fixture:

```python
import redis.asyncio as redis

@pytest_asyncio.fixture
async def valkey_client():
    client = redis.from_url("redis://localhost:6380/0")
    yield client
    await client.aclose()
```

Port is `6380` (mapped from container's 6379 in docker-compose.yml).

---

## 5. Affected Symbols, Modules, and Execution Flows

### Files Modified (Bug Fixes)

| File | Change | Lines |
|------|--------|-------|
| `src/apps/ingestion_app/orchestration/controller.py` | `is_closed` → `bar_closed`, `isoformat()` → `str(.timestamp())` | 117, 123 |
| `src/apps/signal_app/signal_worker.py` | Accept both `bar_closed` and `is_closed` | 81 |

### Files Modified (E2E Infrastructure)

| File | Change |
|------|--------|
| `tests/e2e/run_e2e_tests.sh` | Apply pipeline schema, start all services, dump per-service logs on failure |
| `tests/e2e/test_docker_integration.py` | Add 4 new test functions + Valkey client fixture |

### Execution Flows Affected

| Flow | Impact |
|------|--------|
| Ingestion → Signal | **UNBLOCKED** by B1+B2 fixes. Currently completely broken. |
| Signal → Strategy | Transitively unblocked. Was never reached due to B1+B2. |
| Strategy → Risk → Execution → Portfolio | Transitively unblocked. Depends on models producing signals. |

### Blast Radius

- **B1 fix (controller.py field name):** Only changes the Valkey stream payload key. No DB schema, no Python model, no test fixture change. Signal worker already expects `bar_closed`. Strategy/risk/execution/portfolio workers never read this field. **Blast radius: 1 file, 1 line.**
- **B2 fix (controller.py timestamp):** Only changes the Valkey stream payload value format. Downstream consumers already expect epoch float. **Blast radius: 1 file, 1 line.**
- **B1b guard (signal_worker.py):** Additive — accepts additional field names. Cannot break existing behavior. **Blast radius: 1 file, 1 line.**
- **E2E changes:** Test-only files. Zero production blast radius.

---

## 6. Implementation Order

1. **B1a** — Fix `controller.py` line 123: `"is_closed"` → `"bar_closed"`
2. **B2** — Fix `controller.py` line 117: `record.timestamp.isoformat()` → `str(record.timestamp.timestamp())`
3. **B1b** — Guard `signal_worker.py` line 81: accept both field names
4. **E1** — Update `run_e2e_tests.sh` to apply both schemas
5. **E2** — Update `run_e2e_tests.sh` to start all services
6. **E3** — Add new tests + Valkey fixture to `test_docker_integration.py`
7. Run existing unit/integration tests (`pytest tests/ --ignore=tests/e2e -q`) to verify no regressions
8. (Optional) Run full E2E with `bash tests/e2e/run_e2e_tests.sh` to validate

Steps 1-3 can be done in a single commit. Steps 4-6 can be a second commit.

---

## 7. Acceptance Criteria

### Bug Fixes
- [ ] `controller.py` publishes `"bar_closed": "True"` (not `"is_closed"`)
- [ ] `controller.py` publishes `"timestamp": str(record.timestamp.timestamp())` (epoch seconds, not ISO)
- [ ] `signal_worker.py` reads both `bar_closed` AND `is_closed` from payload
- [ ] Existing tests pass: `pytest tests/ --ignore=tests/e2e -q` shows no regressions
- [ ] `docs/signal_app.md` Section 5.1 payload table remains accurate (it already documents `bar_closed`)

### E2E Infrastructure
- [ ] `run_e2e_tests.sh` applies `sql/pipeline_schema.sql` in addition to ingestion schema
- [ ] `run_e2e_tests.sh` starts signal-worker, strategy-worker, risk-worker, execution-worker, portfolio-worker
- [ ] `run_e2e_tests.sh` dumps per-service logs on test failure
- [ ] `test_docker_integration.py` has Valkey client fixture at `localhost:6380`
- [ ] `test_signal_worker_consumes_and_produces` verifies features stream has data
- [ ] `test_strategy_worker_consumes_features` verifies consumer group exists
- [ ] `test_downstream_workers_running_no_errors` verifies no crash loops
- [ ] `test_consumer_groups_exist` verifies expected consumer groups on streams

---

## 8. Validation Checklist

- [ ] No ISO-format timestamps anywhere in published Valkey stream payloads
- [ ] `bar_closed` is the canonical field name in all published OHLCV stream payloads
- [ ] Epoch-seconds floats flow consistently from ingestion → signal → strategy → risk
- [ ] All 3 existing E2E tests still pass
- [ ] New E2E tests exercise the signal_app boundary (the previously-broken junction)
- [ ] Docker services don't crash-loop (checked via container status assertions)

---

## 9. Explicit Non-Goals

- **Do NOT** fix config alignment (C1, C2) — orphan streams are harmless for now
- **Do NOT** add signal-firing assertions — models may legitimately produce no signals for a given candle
- **Do NOT** change the `features.yaml` or `models.yaml` configs
- **Do NOT** modify any indicator, model, risk, execution, or portfolio logic
- **Do NOT** add health-check endpoints to downstream workers (future work)
- **Do NOT** create a separate `docker-compose.test.yml` — use the existing compose file

---

## 10. Risks and Residual Items

| Risk | Mitigation |
|------|------------|
| 1h closed bar may take up to 60 min to appear in E2E | Use gap-fill backfill data which populates historical closed bars immediately; signal_worker primes from DB history then processes stream entries |
| Strategy models may not fire signals → risk/execution/portfolio have no data flow | E2E tests only check these workers are running without errors, not that they produce output |
| Valkey port 6380 may conflict with host Valkey | E2E script tears down previous containers first; port conflict is a host environment issue |
| Old `is_closed` messages in stream from prior runs | B1b guard handles backwards-compat |
