-- TradingView index OHLCV storage
-- Stores historical candle data for proprietary TV indices (TOTAL2, TOTAL3, BTC.D)

CREATE TABLE IF NOT EXISTS tv_index_ohlcv (
    symbol      TEXT            NOT NULL,
    timeframe   TEXT            NOT NULL,
    timestamp   TIMESTAMPTZ     NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION,
    volume      DOUBLE PRECISION DEFAULT 0.0,
    fetched_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, timeframe, timestamp)
);

-- Convert to hypertable for time-series optimization
SELECT create_hypertable('tv_index_ohlcv', 'timestamp', if_not_exists => TRUE);

-- Index for efficient lookups by symbol
CREATE INDEX IF NOT EXISTS idx_tv_index_symbol_tf ON tv_index_ohlcv (symbol, timeframe, timestamp DESC);

ALTER TABLE tv_index_ohlcv SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol,timeframe'
);
SELECT add_compression_policy('tv_index_ohlcv', INTERVAL '14 days', if_not_exists => TRUE);
SELECT add_retention_policy('tv_index_ohlcv', INTERVAL '180 days', if_not_exists => TRUE);
