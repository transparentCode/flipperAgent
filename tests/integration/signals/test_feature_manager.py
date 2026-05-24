import pytest
from src.apps.signal_app.feature_manager import FeatureManager
from src.libs.common.config import ConfigManager

def test_feature_manager():
    # Setup global config or mock it.
    ConfigManager.reset_singleton()
    config_mgr = ConfigManager()
    # It reads from default base.yaml, which contains:
    # BTC/USD -> 15m -> RSI: period 21
    
    # We will test BTCUSDT 15m
    fm = FeatureManager("BTCUSDT", "15m")
    assert len(fm.indicators) == 1
    assert fm.indicators[0].__class__.__name__ == "RSI"
    assert fm.indicators[0].period == 21
    
    # Let's mock a sequence of history data
    # (high, low, close, volume, timestamp)
    
    history = []
    base_ts = 1600000000
    for i in range(30):
        val = 100.0 + i
        history.append((val + 1, val - 1, val, 10.0, base_ts + i * 900))
        
    fm.prime(history)
    
    assert fm.indicators[0].is_primed is True
    
    # Now simulate process_tick
    tick = (131.0, 129.0, 130.0, 10.0, base_ts + 30 * 900)
    res = fm.process_tick(tick)
    
    assert "RSI" in res
    assert isinstance(res["RSI"], float)

def test_feature_manager_multiple_indicators():
    ConfigManager.reset_singleton()
    fm = FeatureManager("BTCUSDT", "1h")
    
    assert len(fm.indicators) == 2
    names = [i.__class__.__name__ for i in fm.indicators]
    assert "MACD" in names
    assert "RSI" in names
    
    history = []
    base_ts = 1600000000
    for i in range(50):
        val = 100.0 + i
        history.append((val + 1, val - 1, val, 10.0, base_ts + i * 3600))
        
    fm.prime(history)
    
    for ind in fm.indicators:
        assert ind.is_primed is True
        
    tick = (151.0, 149.0, 150.0, 10.0, base_ts + 50 * 3600)
    res = fm.process_tick(tick)
    
    assert "MACD" in res
    assert "RSI" in res

