---
goal: 'Wire all 6 apps to run end-to-end in Docker via shared connection utilities'
stage: 'architect-to-coder'
date_created: '2026-05-26'
last_updated: '2026-05-26'
owner: 'Quant Research Architect'
status: 'Ready'
tags: ['handoff', 'quant', 'infrastructure', 'docker', 'E2E', 'stitching']
source_agent: 'Quant Research Architect'
target_agent: 'Coder Agent'
---

# E2E Docker Pipeline Stitching — Coder Handoff v1

## 1. Context Retrieved

| Source | Key Findings |
|--------|-------------|
| **automem** | Docker topology v1 already delivered (5 services: db, broker, worker-queue, worker-streams, scheduler). `valkey>=6.0.0` replaced `redis` — confirmed working. Execution, risk, portfolio apps architectured but never wired into docker-compose. |
| **memoir** | Portfolio Tracker v1, Execution App, Risk Manager architectures finalized. Pipeline breaks after strategy_app — nothing consumes `signals:*` in Docker. Debt triage G8 notes `pool_manager.py` uses raw `os.getenv("POSTGRES_URI")` — keep this pattern for backwards compat. |
| **session** | All 6 modules complete code-wise. 355 tests pass. No E2E integration in Docker yet. |
| **repo memory** | `valkey>=6.0.0` is the broker client. `POSTGRES_URI` env var override is the established pattern in `DBPoolManager`. `redis.uri` config key is used by ingestion controller (`config_manager.get("redis.uri")`). |

## 2. Objective

Connect the existing 6 applications so they run as a full pipeline in Docker Compose:

```
ingestion → stream:ohlcv:{symbol}:{tf}
  → signal_app (group: signal_app_group) → features:{asset}:{tf}
    → strategy_app (group: strategy_app_group) → signals:{asset}:{tf}
      → risk_app (group: risk_app_group) → orders:{asset}
        → execution_app (group: execution_app_group) → fills:{asset}
          → risk_app FillListener (group: risk_app_fills_group)
          → portfolio_app (group: portfolio_app_fills_group)
```

This is a **stitching** task — no worker logic or lib code changes.

## 3. Scope Boundaries

### In Scope
- Create `src/libs/common/connections.py` — shared Valkey + DB pool factory functions
- Create `sql/pipeline_schema.sql` — DDL for 6 missing tables
- Add 4 missing services to `docker-compose.yml`
- Modify 5 `main.py` files (signal, strategy, risk, execution, portfolio) to wire connections
- Add `strategy-worker` service command as already present

### Explicit Non-Goals
- Do NOT modify any worker class (`signal_worker.py`, `strategy_worker.py`, `risk_worker.py`, `execution_worker.py`, `portfolio_worker.py`, `fill_listener.py`)
- Do NOT modify any lib code (`libs/risk/*`, `libs/execution/*`, `libs/portfolio/*`)
- Do NOT modify ingestion_app (already wired)
- Do NOT add health checks, metrics, or observability (future work)
- Do NOT add Alembic migrations (G12 from debt triage — separate task)

## 4. Confirmed Facts

1. Every worker has `async def connect(self, redis_client: Any)` — uniform interface.
2. `FillListener` also has `connect(self, redis_client: Any)`.
3. `DBPoolManager` uses `os.getenv("POSTGRES_URI")` as DSN override, falls back to config values. Has 30-retry loop with 1s sleep. Uses `asyncpg.create_pool`.
4. Ingestion controller uses `redis.asyncio.from_url(config_manager.get("redis.uri"))` — but we use `valkey.asyncio.Valkey.from_url()` for new code since `valkey` is the declared dependency.
5. `config_manager.get("redis.uri")` returns `"redis://broker:6379/0"` from `configs/base.yaml`.
6. Inside Docker, `POSTGRES_URI` env var contains `postgresql://flipper:flipperpass@db:5432/flipper_db`.
7. All existing docker services already set `POSTGRES_URI`, `REDIS_URI`, and `VALKEY_URI` env vars.
8. `PortfolioWorker.__init__` takes `(asset, db_pool, config_mgr)` and its `connect(redis_client)` accepts `None` gracefully but won't consume streams.
9. Execution and risk apps need `db_pool` for persistence (`fill_tracker.save_report`, `idempotency_store.save`, `account.save_snapshot`, `positions.save_positions`).

## 5. Architecture Decisions

| Decision | Rationale |
|----------|-----------|
| Use `valkey.asyncio.Valkey.from_url()` | `valkey>=6.0.0` is the declared dependency. API-identical to `redis.asyncio`. Ingestion uses `redis.asyncio` but we don't touch it. |
| Shared `create_valkey_client()` in `libs/common/connections.py` | Avoid duplicating 5 identical Valkey connection blocks across main.py files. |
| Reuse `DBPoolManager.init_pools()` directly | Already handles retry logic, env var override, config fallback. No need for a wrapper. |
| `VALKEY_URI` env var as override (matching `POSTGRES_URI` pattern) | `os.getenv("VALKEY_URI")` → falls back to `config_manager.get("redis.uri")`. Same pattern as `DBPoolManager`. |
| Centralized `sql/pipeline_schema.sql` for new tables | Single file for all 6 tables. Ingestion tables stay in their own `schema.sql`. Future: Alembic. |
| Each app `depends_on: [db, broker]` in docker-compose | Simple startup ordering. No healthchecks yet (future improvement). |

## 6. Files to Create

### 6.1 `src/libs/common/connections.py` — Shared Connection Utilities

```python
"""Shared connection factories for Valkey and DB pools."""

from __future__ import annotations

import os
from typing import Any

import valkey.asyncio as valkey

from libs.common.config import ConfigManager
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.CORE_INFRASTRUCTURE)


async def create_valkey_client(
    config_mgr: ConfigManager | None = None,
) -> valkey.Valkey:
    """Create a Valkey (redis-compatible) async client from config.

    Resolution order:
      1. ``VALKEY_URI`` env var  (Docker override)
      2. ``REDIS_URI``  env var  (legacy compat)
      3. ``redis.uri`` from config YAML
      4. Hardcoded fallback ``redis://localhost:6379/0``
    """
    uri = os.getenv("VALKEY_URI") or os.getenv("REDIS_URI")
    if not uri:
        if config_mgr is None:
            config_mgr = ConfigManager()
        uri = config_mgr.get("redis.uri", "redis://localhost:6379/0")

    logger.info(f"Connecting Valkey client → {uri}")
    client: valkey.Valkey = valkey.Valkey.from_url(uri, decode_responses=False)
    # Verify connectivity
    await client.ping()
    logger.info("Valkey client connected")
    return client


async def init_db_pools(config_mgr: ConfigManager | None = None) -> None:
    """Initialize DB connection pools via DBPoolManager.

    This is a thin wrapper that ensures ConfigManager is passed through.
    The actual retry logic and POSTGRES_URI env var override live in
    DBPoolManager.init_pools().
    """
    await DBPoolManager.init_pools(config_manager=config_mgr)
    logger.info("DB pools initialized")
```

### 6.2 `sql/pipeline_schema.sql` — Missing Table Definitions

Derived by reading the actual INSERT/SELECT statements in existing lib code. Every column, type, and constraint matches what the code expects.

```sql
-- =============================================================
-- Pipeline Schema — tables consumed by risk, execution, and
-- portfolio apps.  Run AFTER the ingestion schema.sql.
-- =============================================================

-- 1. risk_positions — PositionTracker persistence
--    (position_tracker.py: save_positions / load_positions)
CREATE TABLE IF NOT EXISTS risk_positions (
    asset             TEXT NOT NULL,
    direction         TEXT NOT NULL,
    entry_price       DOUBLE PRECISION NOT NULL,
    current_price     DOUBLE PRECISION NOT NULL,
    size              DOUBLE PRECISION NOT NULL,
    unrealized_pnl    DOUBLE PRECISION NOT NULL DEFAULT 0,
    entry_timestamp   DOUBLE PRECISION NOT NULL,
    source_model      TEXT,
    source_timeframe  TEXT,
    stop_loss_price   DOUBLE PRECISION,
    take_profit_price DOUBLE PRECISION,
    trailing_stop_distance DOUBLE PRECISION
);

-- 2. risk_account_snapshots — AccountState persistence
--    (account_state.py: save_snapshot / load_latest)
CREATE TABLE IF NOT EXISTS risk_account_snapshots (
    timestamp           DOUBLE PRECISION NOT NULL,
    balance             DOUBLE PRECISION NOT NULL,
    equity              DOUBLE PRECISION NOT NULL,
    unrealized_pnl      DOUBLE PRECISION NOT NULL DEFAULT 0,
    realized_pnl        DOUBLE PRECISION NOT NULL DEFAULT 0,
    drawdown_pct        DOUBLE PRECISION NOT NULL DEFAULT 0,
    peak_equity         DOUBLE PRECISION NOT NULL,
    open_position_count INTEGER NOT NULL DEFAULT 0,
    daily_pnl           DOUBLE PRECISION NOT NULL DEFAULT 0
);
SELECT create_hypertable('risk_account_snapshots', 'timestamp',
       if_not_exists => true, migrate_data => true);

-- 3. execution_fills — FillTracker persistence
--    (fill_tracker.py: save_report)
CREATE TABLE IF NOT EXISTS execution_fills (
    order_id  TEXT PRIMARY KEY,
    data      JSONB NOT NULL,
    ts        DOUBLE PRECISION NOT NULL
);

-- 4. execution_idempotency_keys — IdempotencyStore persistence
--    (idempotency.py: save / load)
CREATE TABLE IF NOT EXISTS execution_idempotency_keys (
    key  TEXT PRIMARY KEY,
    ts   DOUBLE PRECISION NOT NULL
);

-- 5. portfolio_equity_curve — EquityCurveBuilder persistence
--    (equity_curve.py: save_equity_point / get_equity_curve)
CREATE TABLE IF NOT EXISTS portfolio_equity_curve (
    timestamp            DOUBLE PRECISION NOT NULL PRIMARY KEY,
    equity               DOUBLE PRECISION NOT NULL,
    balance              DOUBLE PRECISION NOT NULL,
    unrealized_pnl       DOUBLE PRECISION NOT NULL DEFAULT 0,
    drawdown_pct         DOUBLE PRECISION NOT NULL DEFAULT 0,
    open_position_count  INTEGER NOT NULL DEFAULT 0,
    net_exposure_pct     DOUBLE PRECISION NOT NULL DEFAULT 0,
    gross_exposure_pct   DOUBLE PRECISION NOT NULL DEFAULT 0
);

-- 6. portfolio_closed_trades — TradeJournal persistence
--    (trade_journal.py: save_closed_trade / get_closed_trades)
CREATE TABLE IF NOT EXISTS portfolio_closed_trades (
    trade_id          TEXT PRIMARY KEY,
    asset             TEXT NOT NULL,
    direction         TEXT NOT NULL,
    entry_price       DOUBLE PRECISION NOT NULL,
    exit_price        DOUBLE PRECISION NOT NULL,
    size              DOUBLE PRECISION NOT NULL,
    realized_pnl      DOUBLE PRECISION NOT NULL,
    realized_pnl_pct  DOUBLE PRECISION NOT NULL,
    commission_total  DOUBLE PRECISION NOT NULL DEFAULT 0,
    slippage_bps      DOUBLE PRECISION NOT NULL DEFAULT 0,
    entry_timestamp   DOUBLE PRECISION NOT NULL,
    exit_timestamp    DOUBLE PRECISION NOT NULL,
    duration_seconds  DOUBLE PRECISION NOT NULL DEFAULT 0,
    source_model      TEXT,
    source_timeframe  TEXT,
    entry_order_id    TEXT,
    exit_order_id     TEXT,
    mae_pct           DOUBLE PRECISION,
    mfe_pct           DOUBLE PRECISION
);
```

## 7. Files to Modify

### 7.1 `docker-compose.yml` — Add 4 Missing Services

Append after the existing `strategy-worker` service, before the `volumes:` block:

```yaml
  signal-worker:
    build:
      context: .
      dockerfile: Dockerfile
    command: python -m apps.signal_app.main
    volumes:
      - ./data:/app/data
    environment:
      POSTGRES_URI: postgresql://${POSTGRES_USER:-flipper}:${POSTGRES_PASSWORD:-flipperpass}@db:5432/${POSTGRES_DB:-flipper_db}
      REDIS_URI: redis://broker:6379/0
      VALKEY_URI: redis://broker:6379/0
    depends_on:
      - db
      - broker

  risk-worker:
    build:
      context: .
      dockerfile: Dockerfile
    command: python -m apps.risk_app.main
    volumes:
      - ./data:/app/data
    environment:
      POSTGRES_URI: postgresql://${POSTGRES_USER:-flipper}:${POSTGRES_PASSWORD:-flipperpass}@db:5432/${POSTGRES_DB:-flipper_db}
      REDIS_URI: redis://broker:6379/0
      VALKEY_URI: redis://broker:6379/0
    depends_on:
      - db
      - broker

  execution-worker:
    build:
      context: .
      dockerfile: Dockerfile
    command: python -m apps.execution_app.main
    volumes:
      - ./data:/app/data
    environment:
      POSTGRES_URI: postgresql://${POSTGRES_USER:-flipper}:${POSTGRES_PASSWORD:-flipperpass}@db:5432/${POSTGRES_DB:-flipper_db}
      REDIS_URI: redis://broker:6379/0
      VALKEY_URI: redis://broker:6379/0
    depends_on:
      - db
      - broker

  portfolio-worker:
    build:
      context: .
      dockerfile: Dockerfile
    command: python -m apps.portfolio_app.main
    volumes:
      - ./data:/app/data
    environment:
      POSTGRES_URI: postgresql://${POSTGRES_USER:-flipper}:${POSTGRES_PASSWORD:-flipperpass}@db:5432/${POSTGRES_DB:-flipper_db}
      REDIS_URI: redis://broker:6379/0
      VALKEY_URI: redis://broker:6379/0
    depends_on:
      - db
      - broker
```

### 7.2 `src/apps/signal_app/main.py` — Wire Valkey + DB

Replace the `_run()` function. Changes:
- Import `create_valkey_client`, `init_db_pools`, `DBPoolManager`
- Call `init_db_pools()` and `create_valkey_client()` before spawning workers
- Call `worker.connect(redis_client)` before `worker.start()`
- Add graceful shutdown (close valkey + db pools)

```python
"""signal_app entrypoint — boots SignalWorker(s) per asset/timeframe from config."""

from __future__ import annotations

import asyncio

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging
from apps.signal_app.signal_worker import SignalWorker

CONFIG_FILE_MODELS = "configs/models.yaml"
CONFIG_FILE_FEATURES = "configs/features.yaml"
KEY_MODELS = "models"
KEY_ASSETS = "assets"
KEY_TIMEFRAMES = "timeframes"
KEY_DEFAULT = "default"

logger = bind_logger(__name__, system_component=SystemComponent.SIGNAL_APP)


def _discover_pairs(config_mgr: ConfigManager) -> list[tuple[str, str]]:
    """Return (asset, timeframe) pairs configured in models.yaml (excluding defaults)."""
    models_config = config_mgr.get(KEY_MODELS, {})
    assets_config = models_config.get(KEY_ASSETS, {})
    pairs: list[tuple[str, str]] = []
    for asset, asset_cfg in assets_config.items():
        if asset == KEY_DEFAULT:
            continue
        if not isinstance(asset_cfg, dict):
            continue
        tfs = asset_cfg.get(KEY_TIMEFRAMES, {})
        for tf in tfs:
            if tf == KEY_DEFAULT:
                continue
            pairs.append((asset, tf))
    return pairs


async def _run() -> None:
    config_mgr = ConfigManager()
    config_mgr.register_file(CONFIG_FILE_MODELS)
    config_mgr.register_file(CONFIG_FILE_FEATURES)

    log_level = config_mgr.get("logging.level", default="INFO")
    configure_logging(level=log_level, enable_file_logging=False)

    pairs = _discover_pairs(config_mgr)
    if not pairs:
        logger.warning("No asset/timeframe pairs found in models.yaml. Exiting.")
        return

    logger.info(f"Discovered {len(pairs)} asset/timeframe pairs: {pairs}")

    # --- Connection setup ---
    await init_db_pools(config_mgr)
    redis_client = await create_valkey_client(config_mgr)

    try:
        tasks = []
        for asset, tf in pairs:
            worker = SignalWorker(asset, tf)
            await worker.connect(redis_client)
            tasks.append(asyncio.create_task(worker.start()))

        await asyncio.gather(*tasks)
    finally:
        await redis_client.aclose()
        await DBPoolManager.close_pools()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

### 7.3 `src/apps/strategy_app/main.py` — Wire Valkey

Same pattern. Strategy workers only need Valkey (no direct DB writes).

```python
"""strategy_app entrypoint — boots StrategyWorker(s) per asset/timeframe from config."""

from __future__ import annotations

import asyncio

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging
from apps.strategy_app.strategy_worker import StrategyWorker

CONFIG_FILE_MODELS = "configs/models.yaml"
KEY_MODELS = "models"
KEY_ASSETS = "assets"
KEY_TIMEFRAMES = "timeframes"
KEY_DEFAULT = "default"

logger = bind_logger(__name__, system_component=SystemComponent.MODEL_STRATEGY)


def _discover_pairs(config_mgr: ConfigManager) -> list[tuple[str, str]]:
    """Return (asset, timeframe) pairs configured in models.yaml (excluding defaults)."""
    models_config = config_mgr.get(KEY_MODELS, {})
    assets_config = models_config.get(KEY_ASSETS, {})
    pairs: list[tuple[str, str]] = []
    for asset, asset_cfg in assets_config.items():
        if asset == KEY_DEFAULT:
            continue
        if not isinstance(asset_cfg, dict):
            continue
        tfs = asset_cfg.get(KEY_TIMEFRAMES, {})
        for tf in tfs:
            if tf == KEY_DEFAULT:
                continue
            pairs.append((asset, tf))
    return pairs


async def _run() -> None:
    config_mgr = ConfigManager()
    config_mgr.register_file(CONFIG_FILE_MODELS)

    log_level = config_mgr.get("logging.level", default="INFO")
    configure_logging(level=log_level, enable_file_logging=False)

    pairs = _discover_pairs(config_mgr)
    if not pairs:
        logger.warning("No asset/timeframe pairs found in models.yaml. Exiting.")
        return

    logger.info(f"Discovered {len(pairs)} asset/timeframe pairs: {pairs}")

    # --- Connection setup ---
    redis_client = await create_valkey_client(config_mgr)

    try:
        tasks = []
        for asset, tf in pairs:
            worker = StrategyWorker(asset, tf)
            await worker.connect(redis_client)
            tasks.append(asyncio.create_task(worker.start()))

        await asyncio.gather(*tasks)
    finally:
        await redis_client.aclose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

### 7.4 `src/apps/risk_app/main.py` — Wire Valkey + DB

Risk app needs both Valkey (for stream consumption/publishing) and DB (for position/account persistence).

```python
"""risk_app entrypoint — discovers assets, spawns RiskWorker(s) from config."""

from __future__ import annotations

import asyncio

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging
from libs.risk.account_state import AccountState
from libs.risk.engine import RiskEngine
from libs.risk.mtf.aggregator import SignalAggregator
from libs.risk.position_tracker import PositionTracker
from libs.risk.rules.base import RiskRuleRegistry
from libs.risk.sizer import PositionSizer
from libs.risk.stop_loss import StopLossCalculator
from libs.risk.take_profit import TakeProfitCalculator

# Import rule modules to trigger @register decorators
import libs.risk.rules.max_exposure  # noqa: F401
import libs.risk.rules.max_positions  # noqa: F401
import libs.risk.rules.max_drawdown  # noqa: F401
import libs.risk.rules.daily_loss  # noqa: F401
import libs.risk.rules.cooldown  # noqa: F401

from apps.risk_app.fill_listener import FillListener
from apps.risk_app.risk_worker import RiskWorker

CONFIG_FILE_RISK = "configs/risk.yaml"
CONFIG_FILE_MODELS = "configs/models.yaml"
KEY_MODELS = "models"
KEY_ASSETS = "assets"
KEY_TIMEFRAMES = "timeframes"
KEY_DEFAULT = "default"
KEY_RISK = "risk"

logger = bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)


def _discover_assets(config_mgr: ConfigManager) -> dict[str, list[str]]:
    """Read models.yaml to find all (asset, [timeframes]) pairs."""
    models_config = config_mgr.get(KEY_MODELS, {})
    assets_config = models_config.get(KEY_ASSETS, {})
    result: dict[str, list[str]] = {}

    for asset, asset_cfg in assets_config.items():
        if asset == KEY_DEFAULT:
            continue
        if not isinstance(asset_cfg, dict):
            continue
        tfs = asset_cfg.get(KEY_TIMEFRAMES, {})
        tf_list = [tf for tf in tfs if tf != KEY_DEFAULT]
        if tf_list:
            result[asset] = tf_list

    return result


def _build_risk_engine(risk_config: dict) -> RiskEngine:
    """Instantiate RiskEngine with rules from config."""
    rule_names = risk_config.get("rules", [])
    rules = []
    for name in rule_names:
        try:
            rule_cls = RiskRuleRegistry.get(name)
            rules.append(rule_cls())
        except KeyError:
            logger.warning(f"Unknown risk rule '{name}' — skipping")

    return RiskEngine(
        rules=rules,
        sizer=PositionSizer(),
        sl_calc=StopLossCalculator(),
        tp_calc=TakeProfitCalculator(),
    )


async def _run() -> None:
    config_mgr = ConfigManager()
    config_mgr.register_file(CONFIG_FILE_RISK)
    config_mgr.register_file(CONFIG_FILE_MODELS)

    log_level = config_mgr.get("logging.level", default="INFO")
    configure_logging(level=log_level, enable_file_logging=False)

    # Discover assets from models.yaml
    asset_map = _discover_assets(config_mgr)
    if not asset_map:
        logger.warning("No asset/timeframe pairs found in models.yaml. Exiting.")
        return

    logger.info(f"Discovered {len(asset_map)} assets: {asset_map}")

    # --- Connection setup ---
    await init_db_pools(config_mgr)
    redis_client = await create_valkey_client(config_mgr)

    # Load risk config
    risk_config = config_mgr.get(KEY_RISK, {})

    # Bootstrap account and position state
    initial_balance = risk_config.get("account", {}).get("initial_balance", 10_000)
    account = AccountState(initial_balance)
    positions = PositionTracker()

    # Build engine and aggregator
    risk_engine = _build_risk_engine(risk_config)
    signal_aggregator = SignalAggregator()

    try:
        # Spawn one RiskWorker per asset
        tasks = []
        for asset, timeframes in asset_map.items():
            worker = RiskWorker(
                asset=asset,
                timeframes=timeframes,
                risk_engine=risk_engine,
                signal_aggregator=signal_aggregator,
                account=account,
                positions=positions,
                risk_config=risk_config,
            )
            await worker.connect(redis_client)
            tasks.append(asyncio.create_task(worker.start()))

        # Spawn one FillListener per asset
        unique_assets = list(asset_map.keys())
        for asset in unique_assets:
            listener = FillListener(
                asset=asset,
                account=account,
                positions=positions,
            )
            await listener.connect(redis_client)
            tasks.append(asyncio.create_task(listener.start()))

        await asyncio.gather(*tasks)
    finally:
        await redis_client.aclose()
        await DBPoolManager.close_pools()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

### 7.5 `src/apps/execution_app/main.py` — Wire Valkey + DB

```python
"""execution_app entrypoint — discovers assets, spawns ExecutionWorker(s)."""

from __future__ import annotations

import asyncio

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging
from libs.execution.fill_tracker import FillTracker
from libs.execution.idempotency import IdempotencyStore
from libs.execution.order_manager import OrderManager
from libs.execution.paper_executor import PaperExecutor
from libs.execution.binance_executor import BinanceExecutor

from apps.execution_app.execution_worker import ExecutionWorker

CONFIG_FILE_EXECUTION = "configs/execution.yaml"
CONFIG_FILE_MODELS = "configs/models.yaml"
KEY_MODELS = "models"
KEY_ASSETS = "assets"
KEY_DEFAULT = "default"
KEY_EXECUTION = "execution"

logger = bind_logger(__name__, system_component=SystemComponent.TRADE_EXECUTION)


def _discover_assets(config_mgr: ConfigManager) -> list[str]:
    """Read models.yaml to find all assets."""
    models_config = config_mgr.get(KEY_MODELS, {})
    assets_config = models_config.get(KEY_ASSETS, {})
    result: list[str] = []

    for asset, asset_cfg in assets_config.items():
        if asset == KEY_DEFAULT:
            continue
        if not isinstance(asset_cfg, dict):
            continue
        result.append(asset)

    return result


async def _run() -> None:
    config_mgr = ConfigManager()
    config_mgr.register_file(CONFIG_FILE_EXECUTION)
    config_mgr.register_file(CONFIG_FILE_MODELS)

    log_level = config_mgr.get("logging.level", default="INFO")
    configure_logging(level=log_level, enable_file_logging=False)

    # Discover assets from models.yaml
    assets = _discover_assets(config_mgr)
    if not assets:
        logger.warning("No assets found in models.yaml. Exiting.")
        return

    logger.info(f"Discovered {len(assets)} assets: {assets}")

    # --- Connection setup ---
    await init_db_pools(config_mgr)
    redis_client = await create_valkey_client(config_mgr)

    # Load execution config
    exec_config = config_mgr.get(KEY_EXECUTION, {})
    mode = exec_config.get("mode", "paper")

    # Build executor
    if mode == "paper":
        paper_cfg = exec_config.get("paper", {})
        executor = PaperExecutor(
            slippage_bps=paper_cfg.get("slippage_bps", 5.0),
            slippage_jitter_bps=paper_cfg.get("slippage_jitter_bps", 2.0),
            commission_bps=paper_cfg.get("commission_bps", 4.0),
            fill_delay_ms=paper_cfg.get("fill_delay_ms", 50.0),
        )
        logger.info("Using PaperExecutor")
    elif mode == "live":
        executor = BinanceExecutor()
        logger.info("Using BinanceExecutor (stub)")
    else:
        logger.error(f"Unknown execution mode: {mode}")
        return

    # Build shared components
    idem_cfg = exec_config.get("idempotency", {})
    idempotency_store = IdempotencyStore(
        max_size=idem_cfg.get("max_memory_keys", 10_000),
    )
    fill_tracker = FillTracker()
    order_manager = OrderManager(
        executor=executor,
        idempotency_store=idempotency_store,
        fill_tracker=fill_tracker,
    )

    try:
        # Spawn one ExecutionWorker per asset
        tasks = []
        for asset in assets:
            worker = ExecutionWorker(
                asset=asset,
                order_manager=order_manager,
                exec_config=exec_config,
            )
            await worker.connect(redis_client)
            tasks.append(asyncio.create_task(worker.start()))

        await asyncio.gather(*tasks)
    finally:
        await redis_client.aclose()
        await DBPoolManager.close_pools()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

### 7.6 `src/apps/portfolio_app/main.py` — Wire Valkey + DB

```python
"""portfolio_app entrypoint — discovers assets, spawns PortfolioWorker(s)."""

from __future__ import annotations

import asyncio

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging

from apps.portfolio_app.portfolio_worker import PortfolioWorker

CONFIG_FILE_PORTFOLIO = "configs/portfolio.yaml"
CONFIG_FILE_MODELS = "configs/models.yaml"
KEY_MODELS = "models"
KEY_ASSETS = "assets"
KEY_DEFAULT = "default"

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


def _discover_assets(config_mgr: ConfigManager) -> list[str]:
    """Read models.yaml to find all asset symbols."""
    models_config = config_mgr.get(KEY_MODELS, {})
    assets_config = models_config.get(KEY_ASSETS, {})
    result: list[str] = []

    for asset, asset_cfg in assets_config.items():
        if asset == KEY_DEFAULT:
            continue
        if not isinstance(asset_cfg, dict):
            continue
        result.append(asset)

    return result


async def _run() -> None:
    config_mgr = ConfigManager()
    config_mgr.register_file(CONFIG_FILE_PORTFOLIO)
    config_mgr.register_file(CONFIG_FILE_MODELS)

    log_level = config_mgr.get("logging.level", default="INFO")
    configure_logging(level=log_level, enable_file_logging=False)

    assets = _discover_assets(config_mgr)
    logger.info(f"Portfolio tracker assets: {assets}")

    # --- Connection setup ---
    await init_db_pools(config_mgr)
    redis_client = await create_valkey_client(config_mgr)
    db_pool = DBPoolManager.get_writer_pool()

    try:
        workers: list[PortfolioWorker] = []
        tasks: list[asyncio.Task] = []

        for asset in assets:
            worker = PortfolioWorker(
                asset=asset,
                db_pool=db_pool,
                config_mgr=config_mgr,
            )
            await worker.connect(redis_client)
            workers.append(worker)
            tasks.append(asyncio.create_task(worker.start()))

        logger.info(f"Spawned {len(tasks)} portfolio workers")

        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Portfolio app shutting down")
    finally:
        await redis_client.aclose()
        await DBPoolManager.close_pools()


if __name__ == "__main__":
    asyncio.run(_run())
```

## 8. Implementation Order

| Step | File | Action | Why This Order |
|------|------|--------|---------------|
| 1 | `src/libs/common/connections.py` | **Create** | Foundation — all main.py files import from here |
| 2 | `sql/pipeline_schema.sql` | **Create** | Tables must exist before apps write to them |
| 3 | `docker-compose.yml` | **Modify** | Add 4 new service blocks |
| 4 | `src/apps/signal_app/main.py` | **Modify** | First consumer in the chain after ingestion |
| 5 | `src/apps/strategy_app/main.py` | **Modify** | Next in chain |
| 6 | `src/apps/risk_app/main.py` | **Modify** | Consumes signals, produces orders |
| 7 | `src/apps/execution_app/main.py` | **Modify** | Consumes orders, produces fills |
| 8 | `src/apps/portfolio_app/main.py` | **Modify** | Terminal consumer of fills |

## 9. Acceptance Criteria

- [ ] `docker-compose up --build` starts all 10 services (db, broker, worker-queue, worker-streams, scheduler, strategy-worker, signal-worker, risk-worker, execution-worker, portfolio-worker)
- [ ] Each app logs `"Valkey client connected"` on startup
- [ ] Each app with DB access logs `"DB pools initialized"`
- [ ] Signal workers log `"Listening to stream stream:ohlcv:..."` (not `"Running in mock mode"`)
- [ ] Strategy workers log listening on `features:*` streams
- [ ] Risk workers log listening on `signals:*` streams
- [ ] Execution workers log listening on `orders:*` streams
- [ ] Portfolio workers log listening on `fills:*` streams
- [ ] SQL schema creates all 6 tables without error on a fresh TimescaleDB
- [ ] `PYTHONPATH=. .venv/bin/pytest tests/ --ignore=tests/e2e -q` still passes (355+ tests)
- [ ] No worker class files were modified

## 10. Validation Checklist

| Check | Status |
|-------|--------|
| Point-in-time correctness | N/A — stitching only, no data logic changes |
| Look-ahead bias | N/A |
| Data leakage | N/A |
| Existing tests pass | Must verify after all changes |
| `connections.py` env var fallback matches `DBPoolManager` pattern | Verified — `VALKEY_URI` → `REDIS_URI` → config → hardcoded |
| SQL column types match code INSERT statements | Verified — derived directly from `save_positions`, `save_snapshot`, `save_report`, `save`, `save_equity_point`, `save_closed_trade` |
| `decode_responses=False` on Valkey client | Required — workers parse binary stream data via `json.loads()` |
| Graceful shutdown in every main.py | All use `try/finally` with `aclose()` + `close_pools()` |

## 11. Blast Radius

| Component | Impact |
|-----------|--------|
| `libs/common/connections.py` | **New file** — zero blast radius |
| `sql/pipeline_schema.sql` | **New file** — zero blast radius |
| `docker-compose.yml` | **Additive** — 4 new service blocks, no changes to existing 6 services |
| `signal_app/main.py` | **Modified** — `_run()` function only. `_discover_pairs()` unchanged. |
| `strategy_app/main.py` | **Modified** — `_run()` function only. `_discover_pairs()` unchanged. |
| `risk_app/main.py` | **Modified** — `_run()` function only. Discovery + engine builder unchanged. |
| `execution_app/main.py` | **Modified** — `_run()` function only. Discovery + executor builder unchanged. |
| `portfolio_app/main.py` | **Modified** — `_run()` function only. Replaces `None` stubs with real connections. |
| Worker/lib files | **NOT TOUCHED** — zero changes |

## 12. Risks and Follow-ups

| Risk | Severity | Mitigation |
|------|----------|------------|
| No Docker healthchecks — apps may start before DB is ready | Medium | `DBPoolManager` has 30-retry × 1s loop. `create_valkey_client` calls `ping()`. Sufficient for dev. Healthchecks are a future improvement. |
| `risk_positions` table has no PK — `save_positions` does DELETE+INSERT | Low | Matches existing code pattern. Add PK in future schema evolution. |
| Ingestion still uses `redis.asyncio` not `valkey.asyncio` | Low | Works fine — same protocol. Not in scope to change. |
| No schema migration framework (G12) | Medium | `pipeline_schema.sql` is manually applied. Alembic is a separate debt item. |
| Single Valkey client shared across all workers in same process | Low | All workers in same app share one client — this is the standard `redis.asyncio` pattern (connection pooling is internal). |
| `fill_tracker.save_report` and `idempotency.save` do inline `CREATE TABLE IF NOT EXISTS` | Low | Redundant with `pipeline_schema.sql` but harmless. Ensures tables exist even without manual SQL. |

## 13. Open Questions (Non-Blocking)

1. **Schema init automation**: Should `pipeline_schema.sql` be auto-run by a Docker init container, or manually applied? (Recommend: add `db-init` service in follow-up.)
2. **Log level per-service**: Currently all services share `logging.level` from config. Per-service override via env var? (Defer.)
3. **`strategy-worker` already in compose but signal-worker was missing** — was this intentional? (Resolved: adding signal-worker now.)
