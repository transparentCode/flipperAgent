-- L2 orderbook depth snapshots (pre-aggregated features)
-- Stores computed microstructure features, NOT raw levels.
-- One row per (timestamp, symbol) at 5-minute intervals.

CREATE TABLE IF NOT EXISTS l2_depth_features (
    timestamp       TIMESTAMPTZ NOT NULL,
    symbol          TEXT        NOT NULL,
    bid_ask_imbalance FLOAT,          -- -1 to +1, top-N qty imbalance
    depth_ratio     FLOAT,            -- total bid / total ask qty
    spread_bps      FLOAT,            -- bid-ask spread in basis points
    depth_decay_bid FLOAT,            -- exponential decay rate bid side
    depth_decay_ask FLOAT,            -- exponential decay rate ask side
    best_bid        FLOAT,            -- best bid price
    best_ask        FLOAT,            -- best ask price
    bid_depth_total FLOAT,            -- total bid quantity
    ask_depth_total FLOAT,            -- total ask quantity
    snapshot_levels INT DEFAULT 20,   -- number of levels captured
    PRIMARY KEY(timestamp, symbol)
);

SELECT create_hypertable('l2_depth_features', 'timestamp', if_not_exists => true, migrate_data => true);

-- 90-day retention: L2 features are derived and reproducible
SELECT add_retention_policy('l2_depth_features', INTERVAL '90 days', if_not_exists => true);
