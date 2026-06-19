"""
Constants for ingestion adapters.
"""

OHLCV_COLUMNS = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
OHLCV_TAKER_COLUMNS = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'taker_buy_base_asset_volume']
BINANCE_RAW_KLINE_COLUMNS = [
    'timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 
    'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 
    'taker_buy_quote_asset_volume', 'ignore'
]
BINANCE_KLINE_STREAM_TEMPLATE = "{symbol}@kline_{interval}"
EXCHANGE_BINANCE = "binance"
INGESTION_CONTROL_STREAM = "stream:control:ingestion"
INGESTION_EVENTS_STREAM = "stream:events:ingestion"
INGESTION_LAST_CLOSED_PUBLISHED_PREFIX = "ingestion:last_closed_published"

# Storage Constants (Phase 4)
TABLE_OHLCV = "ohlcv"
TABLE_TICKS = "ticks"
TABLE_OPEN_INTEREST = "open_interest"
TABLE_FUNDING_RATE = "funding_rate"
TABLE_L2_DEPTH_FEATURES = "l2_depth_features"
RETENTION_POLICY_TICKS = "30 days"
RETENTION_POLICY_L2 = "90 days"
