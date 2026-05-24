import pytest
import math
import random
from src.libs.features.indicators.trend.ema import EMA
from src.libs.features.indicators.momentum.rsi import RSI
from src.libs.features.indicators.registry import IndicatorRegistry

def generate_random_walk(length=1000, start=100.0):
    random.seed(42)
    val = start
    data = []
    for _ in range(length):
        val += random.uniform(-2.0, 2.0)
        data.append(val)
    return data

def test_ema_parity():
    data = generate_random_walk(1000)
    period = 14
    
    ema = EMA(period=period)
    batch_result = ema.batch(data)
    
    # sequence test
    lookback = ema.lookback_required
    ema_live = EMA(period=period)
    
    # Prime with the first 100 elements
    prime_size = 100
    ema_live.prime(data[:prime_size])
    
    live_result = [None] * prime_size
    live_result[-1] = ema_live.current_ema
    
    for val in data[prime_size:]:
        out = ema_live.update(val)
        live_result.append(out)
        
    for i in range(prime_size, len(data)):
        assert batch_result[i] is not None
        assert live_result[i] is not None
        assert math.isclose(batch_result[i], live_result[i], abs_tol=1e-9)

def test_rsi_parity():
    data = generate_random_walk(1000)
    period = 14
    
    rsi = RSI(period=period)
    batch_result = rsi.batch(data)
    
    # sequence test
    lookback = rsi.lookback_required
    rsi_live = RSI(period=period)
    
    # Prime with the first 100 elements
    prime_size = 100
    rsi_live.prime(data[:prime_size])
    
    live_result = [None] * prime_size
    live_result[-1] = batch_result[prime_size - 1] # prime doesn't explicitly return, so test the sequence logic
    
    for val in data[prime_size:]:
        out = rsi_live.update(val)
        live_result.append(out)
        
    for i in range(prime_size, len(data)):
        assert batch_result[i] is not None
        assert live_result[i] is not None
        assert math.isclose(batch_result[i], live_result[i], abs_tol=1e-9)

def test_registry():
    assert IndicatorRegistry.get("EMA") == EMA
    assert IndicatorRegistry.get("RSI") == RSI

from src.libs.features.indicators.momentum.macd import MACD
from src.libs.features.indicators.volatility.atr import ATR
from src.libs.features.indicators.volatility.bollinger import BollingerBands
from src.libs.features.indicators.trend.supertrend import Supertrend
from src.libs.features.indicators.volume.vwap import VWAP

def generate_ohlcv(length=1000, start=100.0, start_ts=1609459200): # Jan 1, 2021
    random.seed(42)
    val = start
    data = []
    ts = start_ts
    for _ in range(length):
        change = random.uniform(-2.0, 2.0)
        close = val + change
        high = max(val, close) + random.uniform(0.1, 1.0)
        low = min(val, close) - random.uniform(0.1, 1.0)
        volume = random.uniform(10.0, 1000.0)
        data.append((high, low, close, volume, ts))
        val = close
        ts += 3600 * random.choice([1, 4, 12, 24]) # random hourly steps
    return data

def test_macd_parity():
    data = generate_random_walk(1000)
    macd = MACD(fast_period=12, slow_period=26, signal_period=9)
    batch_result = macd.batch(data)
    
    live_macd = MACD(fast_period=12, slow_period=26, signal_period=9)
    lookback = live_macd.lookback_required
    prime_size = lookback + 10
    
    live_macd.prime(data[:prime_size])
    live_result = [None] * prime_size
    live_result[-1] = batch_result[prime_size - 1]
    
    for val in data[prime_size:]:
        out = live_macd.update(val)
        live_result.append(out)
        
    for i in range(prime_size, len(data)):
        b_macd, b_sig, b_hist = batch_result[i]
        l_macd, l_sig, l_hist = live_result[i]
        assert math.isclose(b_macd, l_macd, abs_tol=1e-9)
        assert math.isclose(b_sig, l_sig, abs_tol=1e-9)
        assert math.isclose(b_hist, l_hist, abs_tol=1e-9)

def test_atr_parity():
    ohlcv = generate_ohlcv(1000)
    data = [(row[0], row[1], row[2]) for row in ohlcv]
    
    atr = ATR(period=14)
    batch_result = atr.batch(data)
    
    live_atr = ATR(period=14)
    prime_size = live_atr.lookback_required + 10
    
    live_atr.prime(data[:prime_size])
    live_result = [None] * prime_size
    live_result[-1] = live_atr.current_atr
    
    for val in data[prime_size:]:
        out = live_atr.update(val)
        live_result.append(out)
        
    for i in range(prime_size, len(data)):
        assert math.isclose(batch_result[i], live_result[i], abs_tol=1e-9)

def test_bollinger_parity():
    data = generate_random_walk(1000)
    bb = BollingerBands(period=20, num_std=2.0)
    batch_result = bb.batch(data)
    
    live_bb = BollingerBands(period=20, num_std=2.0)
    prime_size = live_bb.lookback_required + 10
    
    live_bb.prime(data[:prime_size])
    live_result = [None] * prime_size
    live_result[-1] = batch_result[prime_size - 1]
    
    for val in data[prime_size:]:
        out = live_bb.update(val)
        live_result.append(out)
        
    for i in range(prime_size, len(data)):
        b_sma, b_up, b_low = batch_result[i]
        l_sma, l_up, l_low = live_result[i]
        assert math.isclose(b_sma, l_sma, abs_tol=1e-9)
        assert math.isclose(b_up, l_up, abs_tol=1e-9)
        assert math.isclose(b_low, l_low, abs_tol=1e-9)

def test_supertrend_parity():
    ohlcv = generate_ohlcv(1000)
    data = [(row[0], row[1], row[2]) for row in ohlcv]
    
    st_ind = Supertrend(period=10, multiplier=3.0)
    batch_result = st_ind.batch(data)
    
    live_st = Supertrend(period=10, multiplier=3.0)
    prime_size = live_st.lookback_required + 50
    
    live_st.prime(data[:prime_size])
    live_result = [None] * prime_size
    live_result[-1] = batch_result[prime_size - 1]
    
    for val in data[prime_size:]:
        out = live_st.update(val)
        live_result.append(out)
        
    for i in range(prime_size, len(data)):
        b_val, b_dir = batch_result[i]
        l_val, l_dir = live_result[i]
        assert math.isclose(b_val, l_val, abs_tol=1e-9)
        assert b_dir == l_dir

def test_vwap_parity():
    ohlcv = generate_ohlcv(1000)
    
    vwap_ind = VWAP()
    batch_result = vwap_ind.batch(ohlcv)
    
    live_vwap = VWAP()
    prime_size = 50
    
    live_vwap.prime(ohlcv[:prime_size])
    live_result = [None] * prime_size
    live_result[-1] = batch_result[prime_size - 1]
    
    for val in ohlcv[prime_size:]:
        out = live_vwap.update(val)
        live_result.append(out)
        
    for i in range(prime_size, len(ohlcv)):
        assert math.isclose(batch_result[i], live_result[i], abs_tol=1e-9)
