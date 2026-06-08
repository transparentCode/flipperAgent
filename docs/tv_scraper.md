# TradingView Scraper

The TradingView Scraper is a lightweight sidecar service that periodically fetches proprietary market-cap index data (TOTAL2, TOTAL3, BTC.D) from TradingView, persists it in TimescaleDB, and publishes the latest closed bar to Valkey hashes for real-time consumption by the Signal App.

---

## High-Level Design (HLD)

### System Context

```mermaid
flowchart TD
    subgraph TradingView [TradingView]
        TVChart[Chart WS\nwss://data.tradingview.com/...]
    end

    subgraph TVScraper [TV Scraper Container]
        ARQWorker[ARQ Worker\nfetch_tv_indices]
        Interceptor[TradingViewInterceptor\npatchright / Chromium]
    end

    subgraph Infra [Infrastructure]
        Valkey[(Valkey\nindex:latest:{symbol})]
        TimescaleDB[(TimescaleDB\ntv_index_ohlcv)]
    end

    subgraph Downstream [Downstream]
        SignalApp[Signal App\nEngineeredFeatureManager]
    end

    ARQWorker -->|every :00:30 and :30:30| Interceptor
    Interceptor -->|headless Chromium\nWS frame interception| TVChart
    TVChart -->|~m~ framed OHLCV| Interceptor
    Interceptor -->|DataFrame ~300 bars| ARQWorker
    ARQWorker -->|HSET latest bar| Valkey
    ARQWorker -->|executemany upsert all bars| TimescaleDB
    Valkey -->|HGETALL index:latest:{sym}| SignalApp
```

### Fetch Cadence and Gap-Fill

The scraper fires at `:00:30` and `:30:30` of every hour, covering candle closes for all three relevant timeframes:

| Close time | Fire time | Timeframes covered |
|---|---|---|
| On the hour (:00) | :00:30 | 1h, 4h, 30m |
| Half-hour (:30) | :30:30 | 30m |

Every successful fetch upserts **all ~300 bars** TV returns on page load (not just the latest). Because the DB upsert uses `ON CONFLICT DO UPDATE`, already-present bars are updated in place and missing bars are inserted — providing passive gap-fill with no extra architecture:

| Timeframe | ~300 bars covers |
|---|---|
| 30m | ~6 days |
| 1h | ~12 days |

Any missed cycles (e.g. container restart, Chromium crash) are automatically healed on the next successful fetch.

---

## Low-Level Design (LLD)

### Component Breakdown

#### `interceptor.py` — TradingViewInterceptor

Launches a stealth headless Chromium browser via `patchright`, navigates to a TradingView chart URL, and intercepts WebSocket frames carrying `~m~`-framed OHLCV payloads.

**Protocol parsing:**

TradingView encodes WebSocket messages as `~m~{len}~m~{payload}`. Two module-level helpers handle this:

| Function | Description |
|---|---|
| `parse_tv_messages(raw)` | Regex-walks the `~m~` framing, JSON-decodes each payload, returns `list[dict]`. Non-JSON heartbeat pings (plain integers) are silently skipped. |
| `extract_ohlcv_from_tv_response(messages)` | Finds `timescale_update` or `du` message types, navigates `sds_*` series keys, unpacks `v[0..5]` → `[timestamp_s, open, high, low, close, volume]`. Timestamps multiplied by 1000 (TV sends seconds, pipeline expects ms). |

**`TradingViewInterceptor(cookies_path, proxy_url)`**

Reads `tradingview.cookies_path` from config at construction. Stores `_config` for use by `get_historical_ohlcv`.

**`get_historical_ohlcv_batch(symbols, timeframe, ...)`**

| Step | Detail |
|---|---|
| 1 | Launch one Chromium instance for the whole fetch batch; when `tradingview.proxy_url` is set, pass it into browser launch |
| 2 | Create one browser context with configured viewport and user-agent |
| 3 | Inject session cookies from `cookies_path` (strips leading `.` from domains for Playwright compat) |
| 4 | For each symbol, open a page, hook `page.on("websocket")`, navigate to the chart URL, and capture `~m~` framed OHLCV messages |
| 5 | Poll up to `ws_intercept_timeout_seconds` at `ws_poll_interval_seconds` intervals for `timescale_update`/`du` frames |
| 6 | Parse messages into a deduplicated, timestamp-sorted `pd.DataFrame` per symbol |
| 7 | Close page / context / browser in `finally` blocks so browser resources are cleaned up on both success and failure |

Returns a `dict[symbol, DataFrame]`. Per-symbol failures degrade to empty DataFrames; batch-level launch failures return no symbol data.

**`get_historical_ohlcv(symbol, timeframe, ...)`**

Thin compatibility wrapper around `get_historical_ohlcv_batch([symbol], timeframe)` that returns a single DataFrame.

`since`, `until`, and `limit` parameters are accepted but not used — TV determines the available history window (~300 bars).

**`_map_timeframe(timeframe)`** — maps standard notation to TradingView resolution strings:

| Input | TV resolution |
|---|---|
| `1m` | `1` |
| `5m` | `5` |
| `15m` / `30m` | `15` / `30` |
| `1h` / `2h` / `4h` | `60` / `120` / `240` |
| `1d` / `1D` | `D` |
| `1w` / `1W` | `W` |
| unknown | `60` (default) |

---

#### `worker.py` — ARQ worker

Periodic ARQ task that coordinates index fetching, Valkey publishing, and DB persistence.

**Module-level constants (config-driven):**

```python
TV_INDICES  = config_manager.get("tradingview.indices", [...])
INDEX_KEY_MAP = {sym: sym.split(":")[-1] for sym in TV_INDICES}
# e.g. "CRYPTOCAP:TOTAL2" → "TOTAL2"
```

**`fetch_tv_indices(ctx)`**

For each job run:

1. Calls `interceptor.get_historical_ohlcv_batch(TV_INDICES, timeframe)` — one browser/context session, ~300 bars per symbol
2. Publishes `df.iloc[-1]` (latest closed bar) to `index:latest:{short_name}` Valkey hash
3. Applies `EXPIRE index:latest:{short_name} tradingview.staleness_ttl_seconds`
4. Upserts **all** returned bars to `tv_index_ohlcv` via `executemany` + `ON CONFLICT DO UPDATE`
5. Continues per symbol even if one symbol returns no data

Valkey hash payload:

| Field | Type | Description |
|---|---|---|
| `symbol` | str | Short name (e.g. `TOTAL2`) |
| `timestamp` | str(int ms) | Bar open timestamp in milliseconds |
| `open/high/low/close` | str(float) | OHLCV values |
| `volume` | str(float) | Bar volume |
| `fetched_at` | str(float) | Unix timestamp of fetch (for staleness checks) |

Hash expiry is now part of the producer contract. If the scraper stops running, `index:latest:*` keys disappear automatically after the configured TTL instead of persisting stale context indefinitely.

**`startup(ctx)` / `shutdown(ctx)`**

- `startup`: lazy-imports `TradingViewInterceptor`, creates Valkey client and DB pool (both optional — if DB is unavailable the worker still publishes to Valkey)
- `shutdown`: closes Valkey client

**`WorkerSettings`**

| Setting | Value | Source |
|---|---|---|
| `redis_settings` | `RedisSettings.from_dsn(valkey.uri)` | ConfigManager |
| `cron_jobs` | `minute={0,30}, second=30` | `tradingview.cron_minutes` + `tradingview.cron_second` |
| `max_jobs` | `1` | `tradingview.max_concurrent_jobs` |
| `job_timeout` | `120` | `tradingview.job_timeout_seconds` |

---

#### `config.py`

Holds the shared `config_manager = ConfigManager()` singleton for the tv_scraper package.

---

### Configuration Reference

All config under `configs/tradingview.yaml`.

| Key | Default | Description |
|---|---|---|
| `tradingview.indices` | `[CRYPTOCAP:TOTAL2, ...]` | Symbols to fetch |
| `tradingview.timeframe` | `1h` | Candle resolution to request |
| `tradingview.staleness_ttl_seconds` | `1800` | Max acceptable age of Valkey hash data (30m — matches fetch cadence) |
| `tradingview.fetch_delay_seconds` | `2` | Sleep between sequential index fetches |
| `tradingview.cookies_path` | `secrets/tv_cookies.json` | Path to TradingView session cookie JSON |
| `tradingview.chart_base_url` | `https://www.tradingview.com/chart/` | Chart base URL |
| `tradingview.user_agent` | `Chrome/125...` | Browser user-agent (rotate to avoid detection) |
| `tradingview.viewport_width` / `viewport_height` | `1920` / `1080` | Headless browser viewport |
| `tradingview.page_load_timeout_ms` | `60000` | `page.goto()` timeout |
| `tradingview.ws_intercept_timeout_seconds` | `15` | Max wait for `timescale_update` frames |
| `tradingview.ws_poll_interval_seconds` | `0.5` | Poll interval inside WS wait loop |
| `tradingview.cron_minutes` | `[0, 30]` | Minutes of the hour to fire at |
| `tradingview.cron_second` | `30` | Second offset within each minute |
| `tradingview.max_concurrent_jobs` | `1` | ARQ max parallel jobs |
| `tradingview.job_timeout_seconds` | `120` | ARQ job timeout |

---

### Downstream Interface

The Signal App reads TV index data from Valkey hashes on each closed bar:

- **Hash key**: `index:latest:{short_name}` (e.g. `index:latest:TOTAL2`, `index:latest:BTC.D`)
- **Consumer**: `signal_worker.py` → `EngineeredFeatureManager.compute()` via `index_data` kwarg
- **Short names** consumed by the signal app are derived from the same `tradingview.indices` config, so adding a new index in config propagates automatically to both the scraper and the consumer

**Staleness:** the producer now sets Redis key expiry using `tradingview.staleness_ttl_seconds` (default `1800`). Consumers can still inspect `fetched_at`, but a downed scraper will naturally age out `index:latest:*` keys instead of serving stale hashes forever.

---

### DB Table

```sql
CREATE TABLE tv_index_ohlcv (
    symbol      TEXT        NOT NULL,
    timeframe   TEXT        NOT NULL,
    timestamp   TIMESTAMPTZ NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION,
    volume      DOUBLE PRECISION,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, timeframe, timestamp)
);
```

Upserts use `ON CONFLICT (symbol, timeframe, timestamp) DO UPDATE SET ...` — fully idempotent.

---

## Docker Validation

Focused runtime validation for the scraper can stay narrow; you do not need the full app stack to prove the core path.

### Preconditions

- `secrets/tv_cookies.json` exists and contains a valid TradingView session
- local `.venv` is available for the helper enqueue script

### Focused Validation Steps

1. Bring up only the required services:

```bash
docker-compose down -v
docker-compose up -d --build db broker scraper-tradingview
```

2. Verify readiness:

```bash
docker-compose exec -T -e PGPASSWORD=flipperpass db pg_isready -U flipper -h localhost
docker-compose exec -T broker redis-cli ping
docker-compose ps
```

3. Enqueue one real scraper job onto the dedicated ARQ queue:

```bash
cat <<'PY' > /tmp/enqueue_tv_job.py
import asyncio
from arq import create_pool
from arq.connections import RedisSettings

async def main():
    pool = await create_pool(RedisSettings.from_dsn("redis://127.0.0.1:6380/0"))
    job = await pool.enqueue_job("fetch_tv_indices", _queue_name="arq:tv-scraper")
    print(job.job_id if job else "NO_JOB")
    await pool.aclose()

asyncio.run(main())
PY
.venv/bin/python /tmp/enqueue_tv_job.py
```

4. Wait for the job to finish, then inspect the outputs:

```bash
docker-compose logs --tail=250 scraper-tradingview
docker-compose exec -T broker redis-cli KEYS 'index:latest:*'
docker-compose exec -T broker redis-cli HGETALL index:latest:TOTAL2
docker-compose exec -T broker redis-cli TTL index:latest:TOTAL2
docker-compose exec -T -e PGPASSWORD=flipperpass db \
  psql -U flipper -d flipper_db -Atc \
  "select symbol, timeframe, count(*) from tv_index_ohlcv group by symbol, timeframe order by symbol;"
```

5. Validate browser cleanup in-container:

```bash
docker-compose exec -T scraper-tradingview sh -lc \
  "ps -eo pid,ppid,stat,comm,args | grep -E 'chromium|chrome|headless' | grep -v grep || true"
```

6. Tear down:

```bash
docker-compose down -v
```

### Expected Results

- ARQ log line shows `fetch_tv_indices` completed successfully
- `index:latest:TOTAL2`, `index:latest:TOTAL3`, and `index:latest:BTC.D` exist in Valkey
- `TTL index:latest:*` is close to `1800` seconds immediately after a run
- `tv_index_ohlcv` contains rows for `TOTAL2`, `TOTAL3`, and `BTC.D`
- no lingering Chromium/headless browser processes remain in the container after the job finishes

### Container Note

The `scraper-tradingview` service now runs with `init: true` in Docker Compose. This is important because the worker process is PID 1 inside the container, and the init shim reaps any orphaned browser child processes that Patchright/Chromium might leave behind.

### Docker

The scraper runs in its own container (`Dockerfile.tv-scraper`) separate from the ingestion app because it requires headless Chromium:

```
CMD ["arq", "apps.scraper_app.providers.tradingview.worker.WorkerSettings"]
```

Python dependencies are installed via the `tv-scraper` optional extras group:

```toml
[project.optional-dependencies]
tv-scraper = ["patchright>=1.0.0"]
```

Chromium binaries are installed at image build time:

```dockerfile
RUN python -m patchright install chromium
```

The container mounts `configs/` and `secrets/` at runtime. It has no inbound ports — it only writes to Valkey and TimescaleDB.
