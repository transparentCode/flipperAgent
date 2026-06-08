# Docker Topology

This page documents the full container topology for **flipperAgent**, derived directly from `docker-compose.yml`.

---

## High-Level Architecture

All containers share a single bridge network (`flipper-net`). Infrastructure services are health-checked before any app container starts. The data flow runs in one direction: scrape → ingest → signal → strategy → risk → execution → portfolio.

```mermaid
graph TD
    subgraph infra["Infrastructure"]
        DB[(TimescaleDB\nport 5432)]
        BRK[(Valkey broker\nport 6379)]
    end

    subgraph ingestion["Ingestion Layer"]
        SCH[scheduler]
        WQ[worker-queue\narq WorkerSettings]
        WS[worker-streams\ningestion_app.main]
        TV[tv-scraper\ntv_scraper.worker]
    end

    subgraph pipeline["Processing Pipeline"]
        SIG[signal-worker\nsignal_app.main]
        STR[strategy-worker\nstrategy_app.main]
        RSK[risk-worker\nrisk_app.main]
        EXE[execution-worker\nexecution_app.main]
        PRT[portfolio-worker\nportfolio_app.main]
    end

    subgraph api["API Layer"]
        API[api-server\napi_app.main :8080]
    end

    subgraph observability["Observability Stack"]
        OC[otel-collector\n:4317 gRPC]
        TMP[Tempo\ntraces]
        LOK[Loki\nlogs]
        PRM[Prometheus\nmetrics]
        GRF[Grafana\n:3000]
    end

    SCH -->|enqueue jobs| BRK
    BRK -->|dequeue| WQ
    BRK -->|dequeue| TV
    TV  -->|OHLCV stream| BRK
    BRK -->|consume stream| WS
    WS  -->|write OHLCV| DB

    DB  -->|read OHLCV| SIG
    SIG -->|features stream| STR
    STR -->|decisions stream| RSK
    RSK -->|approved orders| EXE
    EXE -->|fills| PRT

    API -->|read/write configs| DB

    WQ  -.->|OTLP| OC
    WS  -.->|OTLP| OC
    SIG -.->|OTLP| OC
    STR -.->|OTLP| OC
    RSK -.->|OTLP| OC
    EXE -.->|OTLP| OC
    PRT -.->|OTLP| OC
    API -.->|OTLP| OC
    OC  -->|traces| TMP
    OC  -->|logs| LOK
    OC  -->|metrics| PRM
    TMP --> GRF
    LOK --> GRF
    PRM --> GRF

    DB  -.->|healthcheck dep| WQ
    DB  -.->|healthcheck dep| WS
    DB  -.->|healthcheck dep| SIG
    DB  -.->|healthcheck dep| STR
    DB  -.->|healthcheck dep| RSK
    DB  -.->|healthcheck dep| EXE
    DB  -.->|healthcheck dep| PRT
    DB  -.->|healthcheck dep| TV
    DB  -.->|healthcheck dep| API
    BRK -.->|healthcheck dep| WQ
    BRK -.->|healthcheck dep| WS
    BRK -.->|healthcheck dep| SIG
    BRK -.->|healthcheck dep| TV
    BRK -.->|healthcheck dep| API
```

---

## Volume & Mount Map

```mermaid
graph LR
    subgraph named["Named Volumes"]
        V1[(timescaledb-data)]
        V2[(valkey-data)]
        V3[(flipper-logs)]
        V4[(tempo-data)]
        V5[(loki-data)]
        V6[(prometheus-data)]
        V7[(grafana-data)]
    end

    subgraph bind["Host Bind Mounts"]
        B1[./configs]
        B2[./data]
        B3[./sql]
        B4[./secrets]
    end

    DB    --> V1
    BRK   --> V2

    WQ    --> B1
    WQ    --> B2
    WQ    --> V3
    WS    --> B1
    WS    --> B2
    WS    --> V3
    SCH   --> B1
    SCH   --> B2
    SCH   --> V3
    TV    --> B1
    TV    --> B2
    TV    --> B4

    SIG   --> B1
    SIG   --> B2
    SIG   --> V3
    STR   --> B1
    STR   --> B2
    STR   --> V3
    RSK   --> B1
    RSK   --> B2
    RSK   --> V3
    EXE   --> B1
    EXE   --> B2
    EXE   --> V3
    PRT   --> B1
    PRT   --> B2
    PRT   --> V3

    API   --> B1
    API   --> V3

    DB    --> B3
```

> **Note:** `./configs` is mounted **read-only** on all workers and tv-scraper, but **read-write** on `api-server` so the config hot-reload API can write back changes.

---

## Component Contexts

### Infrastructure

#### `db` — TimescaleDB

```mermaid
graph LR
    subgraph db["db (TimescaleDB)"]
        PG["timescale/timescaledb:latest-pg15\nPostgres 15 + TimescaleDB extension"]
    end

    H["127.0.0.1:5432"] -->|exposed| PG
    PG --> V[(timescaledb-data)]
    SQL["./sql/*.sql"] -->|init scripts| PG
    PG -->|healthcheck: pg_isready| HC{healthy}
```

| Property | Value |
|---|---|
| Image | `timescale/timescaledb:latest-pg15` |
| Exposed port | `127.0.0.1:5432:5432` |
| Volume | `timescaledb-data:/var/lib/postgresql/data` |
| Init scripts | `./sql` → `/docker-entrypoint-initdb.d` (ro) |
| Resources | 1 G RAM · 0.5 CPU |
| Healthcheck | `pg_isready -U flipper` every 10 s |

---

#### `broker` — Valkey

```mermaid
graph LR
    subgraph broker["broker (Valkey)"]
        VK["valkey/valkey:latest\nRedis-compatible in-memory store"]
    end

    H2["127.0.0.1:6380"] -->|exposed| VK
    VK --> V2[(valkey-data)]
    VK -->|healthcheck: PING| HC2{healthy}
```

| Property | Value |
|---|---|
| Image | `valkey/valkey:latest` |
| Exposed port | `127.0.0.1:6380:6379` |
| Volume | `valkey-data:/data` |
| Resources | 256 M RAM · 0.5 CPU |
| Healthcheck | `valkey-cli ping` every 10 s |
| Role | arq job queue + Redis streams bus |

---

### Ingestion Layer

#### `scheduler`

```mermaid
graph LR
    CFG["./configs (ro)"] --> SCH
    subgraph SCH["scheduler"]
        CMD["sleep infinity\n(placeholder cron dispatcher)"]
    end
    SCH -->|enqueue scrape jobs| BRK[(broker)]
    SCH --> LOG[(flipper-logs)]
```

| Property | Value |
|---|---|
| Image | `Dockerfile` (shared app image) |
| Command | `sleep infinity` — placeholder; replace with APScheduler/cron |
| Depends on | `db` healthy, `broker` healthy |
| Resources | 512 M RAM · 0.5 CPU |
| Mounts | `./configs` ro · `./data` · `flipper-logs` |

---

#### `worker-queue`

```mermaid
graph LR
    BRK[(broker)] -->|dequeue arq jobs| WQ
    subgraph WQ["worker-queue"]
        ARQ["arq WorkerSettings\napps.ingestion_app.orchestration.worker"]
    end
    WQ --> DB[(TimescaleDB)]
    WQ --> LOG[(flipper-logs)]
    CFG["./configs (ro)"] --> WQ
```

| Property | Value |
|---|---|
| Command | `arq apps.ingestion_app.orchestration.worker.WorkerSettings` |
| Role | Pulls scrape jobs from Valkey queue, orchestrates ingestion tasks |
| Depends on | `db` healthy, `broker` healthy |
| Resources | 512 M RAM · 0.5 CPU |
| Security | `read_only: true` · `no-new-privileges` |

---

#### `worker-streams`

```mermaid
graph LR
    BRK[(broker)] -->|Redis streams| WS
    subgraph WS["worker-streams"]
        ST["python -m apps.ingestion_app.main\nRedis stream consumers"]
    end
    WS -->|write OHLCV rows| DB[(TimescaleDB)]
    WS --> LOG[(flipper-logs)]
```

| Property | Value |
|---|---|
| Command | `python -m apps.ingestion_app.main` |
| Port | `8002:8001` (internal management) |
| Role | Consumes OHLCV from Redis streams, persists to TimescaleDB |
| Depends on | `db` healthy, `broker` healthy |
| Resources | 512 M RAM · 0.5 CPU |
| Security | `read_only: true` · `no-new-privileges` |

---

#### `tv-scraper`

```mermaid
graph LR
    BRK[(broker)] -->|dequeue scrape jobs| TV
    subgraph TV["tv-scraper"]
        ARQ2["arq WorkerSettings\napps.scraper_app.providers.tradingview.worker\nDockerfile.tv-scraper"]
    end
    TV -->|OHLCV → Redis stream| BRK
    SEC["./secrets (ro)\ntv_cookies.json"] --> TV
    CFG["./configs (ro)"] --> TV
```

| Property | Value |
|---|---|
| Dockerfile | `Dockerfile.tv-scraper` (separate, heavier image with browser deps) |
| Command | `arq apps.scraper_app.providers.tradingview.worker.WorkerSettings` |
| Role | Scrapes OHLCV from TradingView, publishes to broker stream |
| Secrets | `./secrets/tv_cookies.json` (ro) |
| Resources | 1 G RAM · 0.5 CPU |
| **No** `read_only` | Requires writable fs for browser/scraper temp files |

---

### Processing Pipeline

The pipeline workers are all built from the same `Dockerfile`, run as read-only containers, and communicate exclusively via Valkey streams + TimescaleDB reads.

```mermaid
sequenceDiagram
    participant DB as TimescaleDB
    participant SIG as signal-worker
    participant STR as strategy-worker
    participant RSK as risk-worker
    participant EXE as execution-worker
    participant PRT as portfolio-worker

    DB  ->> SIG: read OHLCV bars
    SIG ->> STR: publish features (Valkey stream)
    STR ->> RSK: publish decisions (Valkey stream)
    RSK ->> EXE: publish approved orders (Valkey stream)
    EXE ->> PRT: publish fills (Valkey stream)
    PRT ->> DB:  write portfolio state
```

#### `signal-worker`

| Property | Value |
|---|---|
| Command | `python -m apps.signal_app.main` |
| Role | Reads OHLCV from TimescaleDB, computes indicators & features via `FeatureManager`, publishes feature vectors to broker |
| Extra env | `NUMBA_CACHE_DIR=/tmp/numba_cache` |
| Resources | 512 M RAM · 0.5 CPU |

#### `strategy-worker`

| Property | Value |
|---|---|
| Command | `python -m apps.strategy_app.main` |
| Role | Consumes feature vectors, runs `ModelManager` scoring + regime overlay, publishes trade decisions |
| Resources | 512 M RAM · 0.5 CPU |

#### `risk-worker`

| Property | Value |
|---|---|
| Command | `python -m apps.risk_app.main` |
| Role | Applies position sizing, drawdown limits, and exposure checks; approves or rejects orders |
| Resources | 512 M RAM · 0.5 CPU |

#### `execution-worker`

| Property | Value |
|---|---|
| Command | `python -m apps.execution_app.main` |
| Role | Submits approved orders to broker/exchange, tracks fill lifecycle |
| Resources | 512 M RAM · 0.5 CPU |

#### `portfolio-worker`

| Property | Value |
|---|---|
| Command | `python -m apps.portfolio_app.main` |
| Role | Aggregates fills into positions, computes realised/unrealised PnL, publishes portfolio state |
| Resources | 512 M RAM · 0.5 CPU |

---

### API Layer

#### `api-server`

```mermaid
graph LR
    subgraph api["api-server"]
        FA["FastAPI · uvicorn :8080\npython -m apps.api_app.main"]
        CM["ConfigManager\nwatchdog hot-reload"]
        FA --> CM
    end

    H3["127.0.0.1:8080"] -->|exposed| FA
    CM -->|read/write| CFG["./configs"]
    FA --> LOG[(flipper-logs)]

    FE["External client / FE"] -->|GET /api/v1/configs| FA
    FE -->|POST /api/v1/configs/:filename| FA
```

| Property | Value |
|---|---|
| Command | `python -m apps.api_app.main` |
| Port | `127.0.0.1:8080:8080` |
| `./configs` mount | **read-write** (only container with write access) |
| Role | Serves config read/write API; `ConfigManager` watches for changes and notifies all subscribers |
| Resources | 256 M RAM · 0.5 CPU |
| Security | `read_only: true` · `no-new-privileges` |

**Endpoints:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/configs` | Returns `AllConfigsResponse` — list of `{fileName, filePath, contents}` |
| `POST` | `/api/v1/configs/{filename}` | Deep-merges `{"updates": {...}}` into named YAML, triggers watchdog reload |
| `GET` | `/health` | Liveness check |

---

### Observability Stack

All 5 observability services run on `flipper-net`. App containers send telemetry to the OTel Collector via OTLP gRPC but do **not** depend on it for startup — if the collector is down, apps continue running and silently drop telemetry.

```mermaid
graph LR
    subgraph otel["Observability"]
        OC["otel-collector\n:4317 gRPC · :4318 HTTP · :8888 metrics"]
        TMP["Tempo :3200\ntrace storage"]
        LOK["Loki :3100\nlog aggregation"]
        PRM["Prometheus :9090\nmetrics TSDB"]
        GRF["Grafana :3000\ndashboards"]
    end

    OC -->|OTLP export| TMP
    OC -->|remote-write| PRM
    OC -->|push| LOK
    TMP --> GRF
    LOK --> GRF
    PRM --> GRF
```

#### `otel-collector`

| Property | Value |
|---|---|
| Image | `otel/opentelemetry-collector-contrib:0.104.0` |
| Ports | `127.0.0.1:4317` (gRPC), `:4318` (HTTP), `:8888` (self-metrics) |
| Config | `configs/observability/otel-collector.yaml` |
| Resources | 256 M RAM · 0.15 CPU |
| Healthcheck | `wget http://localhost:13133/` every 15 s |
| Role | Receives OTLP from all apps; batches and fans out to Tempo (traces), Loki (logs), Prometheus (metrics) |

#### `tempo`

| Property | Value |
|---|---|
| Image | `grafana/tempo:2.5.0` |
| Config | `configs/observability/tempo.yaml` |
| Volume | `tempo-data:/var/tempo` |
| Resources | 256 M RAM · 0.1 CPU |
| Healthcheck | `wget http://localhost:3200/ready` every 15 s |
| Retention | 72 hours (3 days) |
| Role | Stores distributed traces; search-by-trace-ID via Grafana |

#### `loki`

| Property | Value |
|---|---|
| Image | `grafana/loki:3.1.0` |
| Config | `configs/observability/loki.yaml` |
| Volume | `loki-data:/loki` |
| Resources | 256 M RAM · 0.1 CPU |
| Healthcheck | `wget http://localhost:3100/ready` every 15 s |
| Retention | 72 hours (3 days) |
| Role | Stores structured JSON logs; label-indexed, correlates to traces via `trace_id` |

#### `prometheus`

| Property | Value |
|---|---|
| Image | `prom/prometheus:v2.53.0` |
| Config | `configs/observability/prometheus.yml` |
| Volume | `prometheus-data:/prometheus` |
| Resources | 256 M RAM · 0.1 CPU |
| Healthcheck | `wget http://localhost:9090/-/healthy` every 15 s |
| Retention | 3 days / 50 MB |
| Role | Stores metrics received via remote-write from OTel Collector |

#### `grafana`

| Property | Value |
|---|---|
| Image | `grafana/grafana:11.1.0` |
| Port | `127.0.0.1:3000:3000` |
| Volume | `grafana-data:/var/lib/grafana` |
| Resources | 256 M RAM · 0.15 CPU |
| Healthcheck | `wget http://localhost:3000/api/health` every 15 s |
| Auth | Anonymous viewer access enabled; admin password via `GRAFANA_ADMIN_PASSWORD` env var |
| Provisioning | Auto-provisions Prometheus, Tempo, Loki datasources + pipeline health dashboard |
| Depends on | `tempo` (healthy), `loki` (healthy), `prometheus` (healthy) |

#### Trace Propagation

End-to-end traces flow through Valkey stream payloads via W3C `traceparent` injection:

```
ingestion_app → [_traceparent in XADD] → signal_app → ... → portfolio_app
```

Each `valkey_encode()` call injects `_traceparent` / `_tracestate` keys into the stream payload. `BaseStreamConsumer.run()` extracts the context and creates a child span, so all hops appear in a single Grafana Tempo waterfall.

---

## Security Posture

| Container | `read_only` | `no-new-privileges` | Secrets mount |
|---|---|---|---|
| db | — | — | env vars only |
| broker | — | — | — |
| worker-queue | ✅ | ✅ | — |
| worker-streams | ✅ | ✅ | — |
| scheduler | ✅ | ✅ | — |
| tv-scraper | ❌ | — | `./secrets` ro |
| signal-worker | ✅ | ✅ | — |
| strategy-worker | ✅ | ✅ | — |
| risk-worker | ✅ | ✅ | — |
| execution-worker | ✅ | ✅ | — |
| portfolio-worker | ✅ | ✅ | — |
| api-server | ✅ | ✅ | — |
| otel-collector | — | — | — |
| tempo | — | — | — |
| loki | — | — | — |
| prometheus | — | — | — |
| grafana | — | — | `GRAFANA_ADMIN_PASSWORD` env var |

All app containers use `tmpfs` for `/tmp` so ephemeral writes don't touch the host filesystem.
