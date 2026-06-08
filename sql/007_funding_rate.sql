-- Funding rate storage for perpetual futures
CREATE TABLE IF NOT EXISTS funding_rate (
    timestamp   TIMESTAMPTZ     NOT NULL,
    symbol      TEXT            NOT NULL,
    funding_rate DOUBLE PRECISION,
    PRIMARY KEY (timestamp, symbol)
);
SELECT create_hypertable('funding_rate', 'timestamp', if_not_exists => TRUE);
