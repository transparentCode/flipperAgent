"""
Constants for ingestion adapters.
"""

OHLCV_COLUMNS = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
BINANCE_RAW_KLINE_COLUMNS = [
    'timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 
    'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 
    'taker_buy_quote_asset_volume', 'ignore'
]
BINANCE_KLINE_STREAM_TEMPLATE = "{symbol}@kline_{interval}"
EXCHANGE_BINANCE = "binance"

# Storage Constants (Phase 4)
TABLE_OHLCV = "ohlcv"
TABLE_TICKS = "ticks"
TABLE_OPEN_INTEREST = "open_interest"
RETENTION_POLICY_TICKS = "30 days"
