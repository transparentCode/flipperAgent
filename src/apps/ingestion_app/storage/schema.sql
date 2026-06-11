CREATE TABLE IF NOT EXISTS ohlcv (
    timestamp TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    open FLOAT,
    high FLOAT,
    low FLOAT,
    close FLOAT,
    volume FLOAT,
    PRIMARY KEY(timestamp, symbol, timeframe)
);
ALTER TABLE ohlcv ADD COLUMN IF NOT EXISTS taker_buy_base FLOAT DEFAULT 0;
SELECT create_hypertable('ohlcv', 'timestamp', if_not_exists => true, migrate_data => true);

CREATE TABLE IF NOT EXISTS ticks (
    timestamp TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT,
    price FLOAT,
    size FLOAT
);
SELECT create_hypertable('ticks', 'timestamp', if_not_exists => true, migrate_data => true);

CREATE TABLE IF NOT EXISTS open_interest (
    timestamp TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    open_interest FLOAT,
    PRIMARY KEY(timestamp, symbol)
);
SELECT create_hypertable('open_interest', 'timestamp', if_not_exists => true, migrate_data => true);

-- 1. Continuous Aggregate for 1-minute bars
CREATE MATERIALIZED VIEW IF NOT EXISTS market_1m_bars
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    time_bucket('1 minute', timestamp) AS bucket,
    FIRST(price, timestamp) AS open,
    MAX(price) AS high,
    MIN(price) AS low,
    LAST(price, timestamp) AS close,
    SUM(size) AS volume
FROM ticks
GROUP BY symbol, bucket;

-- 2. Add continuous aggregate refresh policy
SELECT add_continuous_aggregate_policy('market_1m_bars',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute');

-- 3. Add 30-day retention on raw ticks
SELECT add_retention_policy('ticks', INTERVAL '30 days');

-- 4. L2 orderbook depth features (pre-aggregated)
CREATE TABLE IF NOT EXISTS l2_depth_features (
    timestamp       TIMESTAMPTZ NOT NULL,
    symbol          TEXT        NOT NULL,
    bid_ask_imbalance FLOAT,
    depth_ratio     FLOAT,
    spread_bps      FLOAT,
    depth_decay_bid FLOAT,
    depth_decay_ask FLOAT,
    best_bid        FLOAT,
    best_ask        FLOAT,
    bid_depth_total FLOAT,
    ask_depth_total FLOAT,
    snapshot_levels INT DEFAULT 20,
    PRIMARY KEY(timestamp, symbol)
);
SELECT create_hypertable('l2_depth_features', 'timestamp', if_not_exists => true, migrate_data => true);
SELECT add_retention_policy('l2_depth_features', INTERVAL '90 days', if_not_exists => true);

CREATE TABLE IF NOT EXISTS ingestion_assets (
    symbol TEXT PRIMARY KEY,
    exchange TEXT NOT NULL DEFAULT 'binance',
    provider TEXT NOT NULL DEFAULT 'binance_native',
    base_timeframe TEXT NOT NULL DEFAULT '1m',
    publish_timeframes TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    historical_backfill_days INTEGER NOT NULL DEFAULT 2 CHECK (historical_backfill_days >= 0),
    retention_days INTEGER CHECK (retention_days IS NULL OR retention_days > 0),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    desired_state TEXT NOT NULL DEFAULT 'LIVE'
        CHECK (desired_state IN ('LIVE', 'PAUSED', 'STOPPED', 'REMOVING')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ingestion_assets_enabled ON ingestion_assets (enabled);
