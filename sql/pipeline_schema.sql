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
