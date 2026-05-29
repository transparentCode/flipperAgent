CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

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
