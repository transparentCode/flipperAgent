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

**`get_historical_ohlcv(symbol, timeframe, ...)`**

| Step | Detail |
|---|---|
| 1 | Build chart URL: `{chart_base_url}?symbol={symbol}&interval={tv_resolution}` |
| 2 | Launch Chromium headless with stealth args (`--disable-blink-features=AutomationControlled`, `--no-sandbox`) |
| 3 | Set viewport and user-agent from config |
| 4 | Inject session cookies from `cookies_path` (strips leading `.` from domains for Playwright compat) |
| 5 | Hook `page.on("websocket")` to capture frames containing `~m~` |
| 6 | `page.goto(chart_url, wait_until="networkidle", timeout=page_load_timeout_ms)` |
| 7 | Poll up to `ws_intercept_timeout_seconds` at `ws_poll_interval_seconds` intervals for `timescale_update`/`du` in captured frames |
| 8 | Close browser, parse all captured frames, return deduplicated `pd.DataFrame` sorted by timestamp |

Returns an empty DataFrame (columns: `timestamp, open, high, low, close, volume`) on any error or missing data.

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

For each symbol in `TV_INDICES`:

1. Calls `interceptor.get_historical_ohlcv(symbol, timeframe)` — returns ~300 bars
2. Publishes `df.iloc[-1]` (latest closed bar) to `index:latest:{short_name}` Valkey hash
3. Upserts **all** returned bars to `tv_index_ohlcv` via `executemany` + `ON CONFLICT DO UPDATE`
4. Sleeps `fetch_delay_seconds` between symbols (anti-detection)

Valkey hash payload:

| Field | Type | Description |
|---|---|---|
| `symbol` | str | Short name (e.g. `TOTAL2`) |
| `timestamp` | str(int ms) | Bar open timestamp in milliseconds |
| `open/high/low/close` | str(float) | OHLCV values |
| `volume` | str(float) | Bar volume |
| `fetched_at` | str(float) | Unix timestamp of fetch (for staleness checks) |

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

**Staleness:** the `fetched_at` field in each hash can be compared against `tradingview.staleness_ttl_seconds` (1800s) to detect a downed scraper. If data is older than the TTL, consumers should fall back to neutral feature values. This guard is tracked under the regime-overlay implementation plan.

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

### Docker

The scraper runs in its own container (`Dockerfile.tv-scraper`) separate from the ingestion app because it requires headless Chromium:

```
CMD ["arq", "apps.tv_scraper.worker.WorkerSettings"]
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
