import pytest
DEFAULT_BINANCE_ASSET = 'BTCUSDT'
from datetime import datetime, timezone
from pydantic import ValidationError

from apps.ingestion_app.models.tick_models import OHLCVRecord, TickRecord, OIRecord

def test_timestamp_utc_coercion():
    # Ms parsing
    rec = OIRecord(symbol="BTC/USD", timestamp=1609459200000, oi=100)
    assert rec.timestamp == datetime(2021, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    # Sec parsing
    rec = OIRecord(symbol="BTC/USD", timestamp=1609459200, oi=100)
    assert rec.timestamp == datetime(2021, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    # ISO string with Z
    rec = OIRecord(symbol="BTC/USD", timestamp="2021-01-01T00:00:00Z", oi=100)
    assert rec.timestamp == datetime(2021, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

def test_ohlcv_binance_input():
    # Mock Binance raw input
    raw_data = {
        "s": DEFAULT_BINANCE_ASSET,
        "E": 1609459200000,
        "o": "40000.1",
        "h": "40100.5",
        "l": "39900.0",
        "c": "40050.2",
        "v": "100.5"
    }
    record = OHLCVRecord(**raw_data)
    assert record.symbol == DEFAULT_BINANCE_ASSET
    assert record.timestamp == datetime(2021, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert record.open == 40000.1
    assert record.high == 40100.5
    assert record.low == 39900.0
    assert record.close == 40050.2
    assert record.volume == 100.5

def test_ohlcv_validation_failures():
    # Negative Price
    with pytest.raises(ValidationError):
        OHLCVRecord(symbol="BTC", timestamp=1000, open=-10, high=10, low=1, close=5, volume=10)

    # Low > High
    with pytest.raises(ValidationError, match="High must be greater than or equal to Low"):
        OHLCVRecord(symbol="BTC", timestamp=1000, open=10, high=5, low=10, close=5, volume=10)

def test_tick_record_binance():
    # Mock Binance trade
    raw_data = {
        "s": "ETHUSDT",
        "T": 1609459200000,
        "p": "2000.5",
        "q": "2.5",
        "m": True # buyer is maker -> sell side
    }
    record = TickRecord(**raw_data)
    assert record.side == "sell"
    assert record.price == 2000.5
    assert record.size == 2.5
    assert record.symbol == "ETHUSDT"

def test_tick_record_buy_side():
    raw_data = {
        "s": "ETHUSDT",
        "T": 1609459200000,
        "p": "2000.5",
        "q": "2.5",
        "m": False 
    }
    record = TickRecord(**raw_data)
    assert record.side == "buy"

def test_oi_ccxt():
    raw_data = {
        "symbol": "BTC/USD:USD",
        "timestamp": 1609459200000,
        "openInterest": 500.5
    }
    record = OIRecord(**raw_data)
    assert record.open_interest == 500.5
    assert record.timestamp == datetime(2021, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
