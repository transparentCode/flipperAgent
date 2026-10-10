# `scraper_app` Architecture Metadata

`scraper_app` is the always-on collector for external provider data that is not part of the
exchange websocket runtime: TradingView series (20 datasets, hourly) and CoinGlass payloads
(every 15 minutes, through a contained headless engine). It writes append-only observations to
the PostgreSQL schema `scraper` and serves `/health/live` and `/health/ready` on port 8005.

## Files

- `catalog.yaml` - machine-readable app metadata
- `v2-collector.d2` / `v2-collector.svg` - the architecture diagram (canonical source is the D2)
- this file - narrative scope and operations

Layout: `main.py`, `settings.py`, `domain/`, `adapters/{tradingview,coinglass}/`, `storage/`,
`runtime/`, `http_api/`. Config: `configs/scraper.yaml` (namespace `scraper`, strict keys). The
database URI comes only from `SCRAPER_POSTGRES_URI`.

## TradingView lane

The layering test in `tests/scraper` keeps the package free of Valkey, ARQ, pandas and the retired modules.

- Config: `configs/scraper.yaml` (namespace `scraper`, strict keys, 20 datasets).
  The database URI comes only from `SCRAPER_POSTGRES_URI`.
- Data: schema `scraper` in PostgreSQL, append-only `reads` and
  `bar_observations` (a revision adds `seq + 1`; nothing is updated or deleted).
  A bar is "final" only after a covering `ok` read finished at or after
  `bar_close + finality_horizon_seconds`; "as known at T" is answered from
  `observed_at` and `finished_at`.
- Operator step before first start (Compose runs it as `scraper-db-bootstrap`):
  `python -m apps.scraper_app.storage.bootstrap` with `POSTGRES_URI` and
  `SCRAPER_DB_PASSWORD`. Idempotent. The runtime role `scraper_app` gets
  `SELECT, INSERT` only.
- Singleton: a PostgreSQL advisory lock; a second instance exits non-zero.
- Health: `GET :8005/health/live`, `GET :8005/health/ready` (200 `ready` or
  `degraded`, 503 `not_ready`). No other routes in phase 1.
- Backup: `pg_dump --schema=scraper "$POSTGRES_URI" > scraper-backup.sql`
- Database-gated tests (`SCRAPER_TEST_POSTGRES_URI`) truncate the `scraper`
  tables and reset the `scraper_app` role password. They refuse to run unless
  `current_database()` ends with `_test`; never point them at the live database.
- Readiness is single flight (concurrent probes share one computation, so it
  holds at most one pool connection) and bounded by
  `readiness.probe_timeout_seconds` (5). A store timeout reports `not_ready` with
  reason `store_timeout`; other store errors report `database_unreachable`.
  Failures are logged once with a traceback, then at most once a minute, with
  one INFO on recovery. The Compose health check waits up to 8 s so it receives
  the 503 body. Per dataset, `recent_gap_from` is the start of the current
  gap-free run when a hole lies inside `readiness.recent_gap_window_seconds`,
  else `null` (readiness never scans the full history; `contiguous_from(dataset,
  not_before=...)` is a single ordered `lag()` scan with no self-join).
- `scraper.bar_observations` has autovacuum analyze thresholds of 2000 rows so a
  bulk load is analysed quickly; correctness of the queries does not depend on it.
- Revisions and the two window settings. `finality_horizon_seconds` decides only
  when a bar counts as final (a covering read must finish that long after the
  bar closed). `revision_watch_seconds` (required, must be >= the horizon and fit
  in `tradingview.max_bars_per_request`) decides how far back every read
  re-reads, so revisions inside the window are observed and stored as new `seq`
  rows. Before this split the re-read stopped at the horizon, so a later revision
  could never be seen. Values are provisional until the store holds two weeks of
  revisions; the target is zero revisions first seen after the horizon.

  | Datasets | horizon | watch window |
  | --- | --- | --- |
  | `tv.cryptocap.*` 1h, 4h | 96 h | 12 d |
  | `tv.cryptocap.*` 1D | 7 d | 12 d |
  | `tv.binance.*` (open interest, funding) | 96 h | 12 d |

  Changed 2026-10-10: the watch windows were cut from 14/30 days to 12 days so that a
  14-day TradingView retention is valid (retention must cover watch + 2 intervals; for 1D
  that is exactly 14 d). 12 days is still three times the oldest revision recorded
  (about 4 days).

  Evidence (2026-10-09, five full-depth reads of each series within one minute,
  bars that differ between reads, by age from bar close):

  | Series | 0-6 h | 6-24 h | 24-48 h | 48-96 h | > 96 h |
  | --- | --- | --- | --- | --- | --- |
  | `CRYPTOCAP:TOTAL2` 1h | 2 of 6 | 0 of 18 | 0 of 24 | 0 of 48 | 0 of 1,567 |
  | `CRYPTOCAP:BTC.D` 1h | 2 of 6 | 6 of 18 | 4 of 24 | 0 of 48 | 0 of 1,567 |
  | `CRYPTOCAP:BTC.D` 4h | 1 of 1 | 4 of 5 | 1 of 6 | 0 of 12 | 0 of 1,663 |
  | `CRYPTOCAP:TOTAL3` 1D | - | 0 of 1 | 1 of 1 | 1 of 2 | 0 of 3,370 |
  | `BINANCE:BTCUSDTPERP_OI` 1h | 0 of 6 | 0 of 18 | 0 of 24 | 0 of 48 | 0 of 4,903 |

  Largest relative difference in close: 9.8e-05 (6-24 h), 2.4e-06 (24-48 h),
  4.8e-07 (48-96 h). That probe was one minute long and could not see slow
  revisions. The first 48 h re-read of the store (previous read 07:25, this read
  08:09 UTC, 2026-10-09) did:

  | Dataset | Revised bars | Bar opens (UTC, 2026-10-08) | Age since close | Largest relative change |
  | --- | --- | --- | --- | --- |
  | `tv.binance.bnbusdt_p.oi.1h` | 13 | 10:00-22:00, consecutive | 9-21 h | 3.5e-04 |
  | `tv.binance.solusdt_p.oi.1h` | 7 | 10:00-16:00, consecutive | 15-21 h | 5.8e-04 |
  | BTC and ETH open interest, all four funding series | 0 | - | - | - |

  All stored revisions at that time (137 rows, 11 datasets):

  | Age | Revisions | Largest relative change in close |
  | --- | --- | --- |
  | 0-24 h | 111 | 5.0e-04 |
  | 24-48 h | 18 | 1.5e-04 |
  | 48-96 h | 8 | 4.8e-07 |

  Hence one provisional rule for every TradingView dataset: no series is final at
  close, and funding shows no revision yet but one read is not evidence that it
  never does. Consumers: values known at close can differ from settled values by
  up to about 6 basis points; `final` lags 4 days for every 1h/4h dataset and 7
  days for 1D. Open interest and funding for models should come from Binance via
  ingestion_app; the TradingView copies are interim.
- Provider history can contain holes (TradingView daily index data from 2015).
  A read records them in `scraper.reads.holes` instead of failing; readiness
  reports `recent_gap_from` per contiguous dataset and degrades with
  `recent_gap` only for a hole inside `readiness.recent_gap_window_seconds`.
- The collector writes only to schema `scraper`.

## CoinGlass lane

A second, independent collection lane in the same process (`runtime/coinglass.py`).
It exists only when `scraper.coinglass` is present in `configs/scraper.yaml`; without
the block nothing changes.

- Flow: every slot (minutes 5, 20, 35, 50) one cycle. A fresh CDP connection to the
  engine, sweep of stale page targets, new page, cache disabled, optional cookies,
  navigate to the host page, wait for the module registry, one in-page helper call per
  dataset (helper found by factory source text; exactly one module and one export, else
  `helper_missing`), page closed. Nothing is kept between cycles. Retry: when a cycle
  fails before its first helper call (engine open, sweep, page, cookies, navigation),
  the lane waits `cycle_retry_delay_seconds` (20) and runs the cycle again, up to
  `cycle_retries` (1) times in the same pass; the first failure is one WARNING line,
  reads are recorded for the final attempt only and `reads.meta.attempts` says how
  many were made. A helper-level failure or a cycle deadline is not retried (the next
  slot re-reads everything). Reason: max pain and the liquidation map carry no
  history, so a lost cycle is a permanent hole (a single name-resolution failure at the
  proxy once cost a whole cycle). The lane never stops on an error and its
  failures never affect the TradingView lane.
- Login: the site's login state is the `obe` cookie. Anonymous, only the BTCUSDT
  5-minute 24 h heatmap and max pain answer. With a free-tier login the ETH heatmap, the
  liquidation map (pair and cross-exchange), and the 12 h and 1-week heatmaps also
  answer `code 0`; without it they return `code 40000` (`not_authorized`).
- Datasets (nine): `liq_heatmap` (BTCUSDT anonymous; ETH/SOL/BNB are `requires_login`),
  `max_pain` (BTC, ETH, SOL, BNB; projected in the page to a fixed field list), and
  `liq_map` (`cg.binance.{btc,eth,sol,bnb}usdt.liq_map.1d`, endpoint
  `/api/index/5/liqMap`, all `requires_login`). A `liq_map` payload is
  `{instrument, lastPrice, liqMapV2}` where `liqMapV2` maps a price bucket to rows
  `[price, value, leverage, tier]`. The gate checks the envelope, instrument identity,
  `lastPrice > 0`, a non-empty map, positive numeric keys, four-field rows (price > 0,
  value >= 0, integer leverage > 0, non-empty tier). It is a current-state snapshot
  like max pain: no provider time; the read's bounds are the instant the helper
  returned; `bars_seen` is the bucket count; the whole `data` is stored.
- Store: one whole payload per ok read in `scraper.payload_observations`
  (`json+gzip;v1`, canonical JSON with sorted keys and `canonical_decimal` numbers,
  `content_hash` = sha256 of the canonical text, `observed_at` = the read's
  `finished_at`). `scraper.reads.meta` carries module id, export name, source length and
  payload bytes. Read path: `latest_payload(dataset_id, at=)` only; there is no HTTP read
  API yet. Growth is about 8 MB a day per heatmap dataset, so about 31 MB a day with four
  heatmaps (liquidation maps are about 10 KB each), until the column-wise decision.
- Later column-wise form: use columns if grid changes are rare and closed columns rarely
  change; otherwise keep whole payloads. The stored payloads are the evidence for that
  decision.
- Containment: the engine (`scraper-browser`) sits on `scraper-browser-net`
  (`internal: true`) with no ports and no volumes; its only route is the allow-listing
  proxy (`scraper-egress`: default-deny, `coinglass.com` and `coinglasscdn.com`
  with subdomains, CONNECT to 443 only). The `scraper` service joins both `flipper-net`
  and `scraper-browser-net` and has no `depends_on` on the engine or proxy; an engine
  outage degrades readiness (`never_succeeded`/`stale`, `coinglass_catchup_pending`
  during catch-up) but never makes it `not_ready`.
- Cookies: optional `secrets/coinglass_cookies.json` (mounted read-only at
  `/app/secrets`; same format as the old browser runtime). Only cookies for
  `coinglass.com` and its subdomains are sent, via `Network.setCookies` every cycle;
  the file is re-read when its mtime changes. Names and values are never logged or
  stored. Without the file the `requires_login` datasets are `disabled` (not a
  degradation). A session cookie lives in the engine's memory while it runs.
- Engine archive: run `scripts/fetch_moli.sh` (aarch64 only; the default URL is the pinned release, `MOLI_URL` overrides it); it
  verifies the sha256 and skips the download when the right file is already in
  `docker/scraper-browser/vendor/`. The Dockerfile verifies the same sum again.
- Operator steps: re-run `python -m apps.scraper_app.storage.bootstrap` (adds
  `reads.meta` and the payload table; the runtime role gets SELECT, INSERT only).
  Backup must include the new table, for example
  `pg_dump -t scraper.reads -t scraper.bar_observations -t scraper.payload_observations`.

## Retention purge

Stored data older than a configurable number of days is deleted by a task inside the
collector (`runtime/purge.py`), configured under `scraper.retention` in
`configs/scraper.yaml`. Without the block nothing is purged.

- Schedule: its own slot loop (`slot_minutes: [45]`), only while the advisory lock is held.
  A pass visits every dataset of a provider whose `*_days` is set; `null` keeps everything.
  Production (2026-10-10): CoinGlass 14 days, TradingView 14 days (a TradingView retention must cover
  `revision_watch_seconds + 2 intervals` of every dataset, validated at startup, because every
  read re-reads that window and would re-insert purged bars as new observations).
- Cutoff: database `now()` minus the days. CoinGlass: `payload_observations` with
  `observed_at < cutoff`; TradingView: `bar_observations` with `bar_open < cutoff` (all
  revisions). Then the dataset's reads older than the cutoff that nothing references. The
  newest ok read of a dataset and its payload are never deleted, so the last known value
  survives an outage longer than the retention. Retained bars keep all their revisions,
  so `final` and `as_of` answers for them do not change.
- Statements: batches of `batch_rows`, each its own transaction; a `LIMIT`ed index-ordered
  selection followed by a delete by primary key (no self-join, independent of planner
  statistics). `bar_observations_read` indexes `bar_observations (read_id)`.
- Role: `scraper_purge` (`SELECT, DELETE` on the three tables, nothing else; created by the
  bootstrap from `SCRAPER_PURGE_DB_PASSWORD`). The collector's role `scraper_app` still
  cannot delete. The purge pool uses `SCRAPER_PURGE_POSTGRES_URI` (environment only). If
  retention is enabled and the URI is missing, the task does not start, one ERROR is
  logged and readiness is `degraded` with `purge_not_configured`; collection continues.
- Readiness: section `purge` (`enabled`, `last_run_at`, `last_ok_at`, `deleted` per table of
  the last pass, `retention` days per provider). `purge_failing` (degraded, never
  `not_ready`) when no pass succeeded within `readiness_max_age_seconds` (counted from
  startup until the first success). One INFO line per pass, one WARNING per failed pass.
- Collector filter: when `tradingview_days` is set the collector drops bars with
  `bar_open < now - tradingview_days` after the gate and before the commit (the newest bar is
  always kept), also on the first load. Some reads reach back past the cutoff by construction
  (a sparse series such as 8-hourly funding sized in 1h bars, or the sizing margin on 1D), and
  the purge would otherwise delete them again every hour. `bars_seen` stays the provider's
  count; `covered_from`/`covered_to`, `holes` and `gap_before` describe the stored bars.
- Reads: bar rows of one read share the read's `finished_at` as `observed_at` (new rows;
  existing rows are not rewritten), like payload rows.
- Operator steps: re-run the bootstrap (new role, index) before deploying; deletion is
  irreversible, so take a backup first.

## Agent read API (`/v2`)

Read-only HTTP API in the collector process (`http_api/v2.py`, pure rules in
`http_api/rules.py`), configured under `scraper.api`. Nothing under `/v2` writes; there are no
jobs. Health routes stay unauthenticated.

- Token: `openssl rand -hex 32 > secrets/scraper_api_read_token` (never committed, mounted
  read-only at `/app/secrets`). The service reads env `SCRAPER_API_READ_TOKEN`, else the file
  named by `SCRAPER_API_READ_TOKEN_FILE`, which is re-read when its mtime changes (no restart).
  A token shorter than 32 characters is rejected with one ERROR; with no usable token `/v2/*`
  answers 503 `auth_not_configured`. Send `Authorization: Bearer <token>`; failures are 401
  `unauthorized`. The token is never logged.
- Pool: its own asyncpg pool (min 0, `pool_max_size`, `application_name=scraper_api`,
  `default_transaction_read_only=on`, `statement_timeout`), so API load cannot take a
  collector, readiness or purge connection. Errors are `{"detail": {"code", "message", ...}}`.
- Routes: `GET /v2/datasets`, `GET /v2/datasets/{id}` (catalog plus `vintage_available_from`,
  `first`/`last`, `last_ok_read_at`, `revisions_after_horizon`, `limits`);
  `GET /v2/datasets/{id}/bars`; for payload datasets `GET .../payload?as_of=`,
  `GET .../payloads?start=&end=&limit=` (metadata, newest first, `next`) and
  `GET .../payloads/{observation_id}`.
- Bars: `mode=final` (default), `as_of` (needs `as_of`), `current` (= database now minus
  `as_of_settle_seconds`; the response states that instant, so `mode=as_of&as_of=<it>` replays
  it exactly). A named instant later than now minus the settle interval is 422
  `as_of_too_recent` (a read that began before the instant may still be committing); one
  before `vintage_available_from` (the oldest retained ok read, which moves forward after a
  purge) is 422 `as_of_before_vintage`. `start` inclusive, `end` exclusive on `bar_open`,
  default `end` = reference time, span at most `max_limit` intervals; `limit`, `order`
  (`desc` default); `next` carries the window and mode to continue without gaps or repeats.
  Timestamps need an explicit offset (`Z` or `+00:00`; encode `+` as `%2B` in URLs). Prices and
  volumes are exact decimal strings.
- Payloads: `data` is the stored canonical JSON inserted verbatim, so the SHA-256 of that text
  equals `content_hash`. The payload list applies the same settle rule to `end`.
- Stale: the reference time minus `finished_at` of the dataset's latest ok read at or before it,
  against the provider's `max_read_age_seconds`; stale is 503 `stale` (with `age_seconds`,
  `max_age_seconds`, `last_ok_read_at`) unless `allow_stale=true`. A login dataset without
  cookies is 503 `dataset_disabled`. Store problems are 503 `store_timeout`,
  `store_unavailable` or `busy`; unknown ids are 404.
- Example: `curl -H "Authorization: Bearer $(cat secrets/scraper_api_read_token)"
  "http://127.0.0.1:8005/v2/datasets/tv.cryptocap.total3.1h/bars?mode=current&limit=24"`.

## Failure behavior (live run, 2026-10-09)

- With the engine or the proxy down, the CoinGlass lane records `engine_unreachable` or
  `navigation_failed` for each dataset; the TradingView pass is unaffected (20 of 20 in 28 s).
- `docker kill` of the engine counts as a manual stop for Docker, so the restart policy does
  not bring it back; a crash does.
- The `scraper-egress` health check sends a request for a domain the filter refuses and accepts
  any HTTP status line, so tinyproxy does not log a half-open connection every interval.

## Alerting

`alert_app` probes `http://scraper:8005/health/ready` as `alerts.health_checks.scraper_collector`
(healthy status `ready`, 120 s startup grace, source app `scraper_app`).

## Retired scraper

The browser-automation scraper (Patchright, ARQ workers, Valkey caches, the FastAPI service on
port 8081, the `api_app` bridge `/ingestion/scraper/*`) was removed. It left keys in Valkey
(`scraper:runtime_status:*`, `scraper:job:*`, `index:latest:*`, `derivatives:latest:*`,
`coinglass:latest:*`, `arq:*`). Nothing reads them. Operator cleanup, not run by any code; review
the key count first, then delete in batches:

```bash
for p in 'scraper:runtime_status:*' 'scraper:job:*' 'index:latest:*' 'derivatives:latest:*' \
         'coinglass:latest:*' 'arq:*'; do
  docker compose exec -T broker valkey-cli --scan --pattern "$p" | xargs -r -n 100 docker compose exec -T broker valkey-cli unlink
done
```

The legacy SQL tables `tv_index_ohlcv`, `funding_rate` and `open_interest` were dropped on 2026-10-10 (empty, no reader); their DDL is removed from `sql/`.

## Rendering

```bash
./scripts/render_d2.sh docs/architecture/scraper_app/v2-collector.d2 docs/architecture/scraper_app/v2-collector.svg
```
