import pytest
from apps.signal_app.feature_manager import FeatureManager
from libs.common.config import ConfigManager

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


def test_feature_manager_multi_instance_indicator(monkeypatch):
    """Multi-instance indicators produce distinct output keys."""
    ConfigManager.reset_singleton()
    config_mgr = ConfigManager()

    test_state = {
        "features": {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "EMA_fast": {"type": "EMA", "period": 9},
                            "EMA_slow": {"type": "EMA", "period": 21},
                            "RSI": {"period": 14},
                        }
                    }
                }
            }
        }
    }
    # Prevent register_file from reloading state from disk
    monkeypatch.setattr(config_mgr, "_load_configs", lambda trigger_callbacks=True: None)
    config_mgr._state = test_state

    fm = FeatureManager("ANYASSET", "1h")

    # Should have 3 indicators
    assert len(fm.indicators) == 3

    # Verify EMA instances have different periods
    ema_entries = [(k, ind) for k, ind in fm._indicator_entries if ind.__class__.__name__ == "EMA"]
    assert len(ema_entries) == 2
    periods = {k: ind.period for k, ind in ema_entries}
    assert periods == {"EMA_fast": 9, "EMA_slow": 21}

    # Prime and tick
    history = [(100.0 + i + 1, 100.0 + i - 1, 100.0 + i, 10.0, 1600000000 + i * 3600) for i in range(30)]
    fm.prime(history)

    tick = (131.0, 129.0, 130.0, 10.0, 1600000000 + 30 * 3600)
    res = fm.process_tick(tick)

    # Output keys must be the aliases, not "EMA"
    assert "EMA_fast" in res
    assert "EMA_slow" in res
    assert "RSI" in res
    assert "EMA" not in res  # No bare "EMA" key
    assert res["EMA_fast"] != res["EMA_slow"]  # Different periods -> different values


def test_feature_manager_backward_compat_no_type_key(monkeypatch):
    """Entries without 'type' key still work with class name as output key."""
    ConfigManager.reset_singleton()
    config_mgr = ConfigManager()

    test_state = {
        "features": {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "EMA": {"period": 20},
                            "RSI": {"period": 14},
                        }
                    }
                }
            }
        }
    }
    monkeypatch.setattr(config_mgr, "_load_configs", lambda trigger_callbacks=True: None)
    config_mgr._state = test_state

    fm = FeatureManager("ANYASSET", "1h")
    assert len(fm.indicators) == 2

    history = [(100.0 + i + 1, 100.0 + i - 1, 100.0 + i, 10.0, 1600000000 + i * 3600) for i in range(30)]
    fm.prime(history)

    tick = (131.0, 129.0, 130.0, 10.0, 1600000000 + 30 * 3600)
    res = fm.process_tick(tick)

    assert "EMA" in res
    assert "RSI" in res

